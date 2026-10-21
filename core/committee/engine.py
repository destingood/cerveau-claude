"""The committee: analysts, a debate, a manager and a risk controller (plan of phase 3, §10).

A LangGraph subgraph run within one request. The analysts work side by side (``Send``), each in
a tool session of its own; the code numbers their findings in the order of the cards, then the
defender and the challenger argue for ``max_debate_rounds`` rounds, the manager proposes and the
controller checks. Every output is a JSON object checked by its schema and by the rules of
``rules.py``; an output that breaks them gets one repair, then the role fails and the committee
concludes « pas de décision » (fail closed).

No role has an action tool and web pages reach a role through the reader only (R5). The kill
switch is checked before each model call and between roles (R4). An exceeded session budget or
the kill switch stops the session, recorded as incomplete (D18); the caller journals each role
(D19) and, after the kill switch, stops the request.

A pack gives the cards, the tools of each role and its deterministic limit checks
(``CommitteeSpec``); the model tier of each member comes from ``committee.yaml``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import operator
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel

from core.budget.gate import RequestBudgetExceeded
from core.committee.rules import (
    QUESTION,
    TODAY,
    LimitCheck,
    analyst_errors,
    controller_errors,
    debate_errors,
    decision_blockers,
    final_verdict,
    finding_origin,
    manager_errors,
)
from core.committee.schemas import (
    AnalystReport,
    ControllerReport,
    DebateTurn,
    ManagerDecision,
    MemberKind,
    RoleOutput,
    Verdict,
    Weight,
)
from core.config.loader import Config
from core.guardrails.input import mark_untrusted
from core.models.router import Seat
from core.orchestrator.planner import Session, _execute
from core.orchestrator.runtime import KillSwitchEngaged, Run
from core.orchestrator.state import Source
from core.orchestrator.structured import MAX_ERRORS, message_text, parse_json, short_error
from core.policy.engine import kill_switch_engaged
from core.verification.trace import Evidence, ToolOutput

MAX_ROLE_TURNS = 10  # model calls of one role, tool calls and the repair included
Status = Literal["complete", "incomplete", "echec"]
LimitChecks = Callable[[ManagerDecision, Sequence[ToolOutput]], Sequence[LimitCheck]]

FORMAT = "Réponds uniquement par un objet JSON conforme à ce schéma, sans texte autour :\n{schema}"
REPAIR = (
    "Ta réponse ne respecte pas le format ou les règles du Comité : {errors}. Réponds de nouveau "
    "uniquement par l'objet JSON corrigé, sans texte autour. Sans correction, ton rôle est en "
    "échec et le Comité ne conclut pas."
)
NO_TOOL = "Erreur : l'outil « {name} » n'est pas disponible pour ce rôle."
# A member reads the signals of the registry's strategies, never a backtest: its window could
# reach the protocol's final sample (quant review of phase 3, M2).
LAB = "strategy_lab"
LAB_MODES = frozenset({"signaux"})
LAB_MODE = "Erreur : au Comité, strategy_lab ne sert qu'en mode signaux."
TOO_MANY_TURNS = f"aucune réponse valide en {MAX_ROLE_TURNS} appels"

# Order of the role records: stage, then debate round, then the member's place.
_STAGES: dict[MemberKind, int] = {
    "analyste": 0,
    "defenseur": 1,
    "contradicteur": 1,
    "gestionnaire": 2,
    "controleur": 3,
}
_SIDES: dict[MemberKind, str] = {"defenseur": "D", "contradicteur": "X"}


@dataclass(frozen=True)
class Card:
    """One member: its key in ``committee.yaml``, its kind, its role card and its tools."""

    member: str
    kind: MemberKind
    system: str
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommitteeSpec:
    """What a pack gives the committee (``plugins/finance_committee`` for Finance)."""

    pack: str
    feature: str  # the feature ``config.require`` checks (``finance.committee``)
    analysts: tuple[Card, ...]
    defender: Card
    challenger: Card
    manager: Card
    controller: Card
    limit_checks: LimitChecks  # D21: the deterministic controls of the proposal
    version: str = ""

    def cards(self) -> tuple[Card, ...]:
        return (*self.analysts, self.defender, self.challenger, self.manager, self.controller)


@dataclass
class RoleRecord:
    """One answer of one member, as the journal keeps it (D19)."""

    member: str
    kind: MemberKind
    round: int  # debate round, 0 outside the debate
    model: str
    valid: bool
    attempts: int  # answers given: 1, or 2 after a repair
    constats: tuple[str, ...] = ()  # the findings it gave (analyst) or cites
    sha256: str | None = None  # of its output as canonical JSON
    error: str | None = None
    output: dict[str, Any] | None = None
    position: tuple[int, int, int] = (0, 0, 0)

    def to_payload(self) -> dict[str, Any]:
        return {
            "member": self.member,
            "kind": self.kind,
            "round": self.round,
            "model": self.model,
            "valid": self.valid,
            "attempts": self.attempts,
            "constats": list(self.constats),
            "sha256": self.sha256,
            "error": self.error,
        }


@dataclass(frozen=True)
class Finding:
    """A finding numbered by the code (``C1``…), with the call or the page it cites."""

    id: str
    member: str
    texte: str
    appel: str
    origin: str  # the call id, or "<member>:source [n]"
    date: str | None


@dataclass(frozen=True)
class Point:
    """An argument numbered by the code: ``D<round>.<n>`` (defender), ``X<round>.<n>``."""

    id: str
    member: str
    round: int
    texte: str
    poids: Weight
    constats: tuple[str, ...]
    repond_a: tuple[str, ...]


class NoDecision(Exception):
    """The committee cannot conclude: « pas de décision » (fail closed)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class RoleFailed(NoDecision):
    """A member gave no valid output after its repair."""

    def __init__(self, record: RoleRecord) -> None:
        self.record = record
        super().__init__(f"{record.member} : {record.error}")


@dataclass
class Sitting:
    """One committee session, filled as it runs: what survives a failure is kept."""

    record_id: str
    question: str
    pack: str
    version: str
    status: Status = "incomplete"
    reason: str | None = None
    halted: bool = False  # the kill switch stopped the session (R4)
    roles: list[RoleRecord] = field(default_factory=list)
    constats: list[Finding] = field(default_factory=list)
    arguments: list[Point] = field(default_factory=list)
    decision: ManagerDecision | None = None
    controller: ControllerReport | None = None
    checks: tuple[LimitCheck, ...] = ()
    verdict: Verdict | None = None
    verdict_reasons: tuple[str, ...] = ()
    sessions: dict[str, Session] = field(default_factory=dict, repr=False)
    reports: dict[str, AnalystReport] = field(default_factory=dict, repr=False)

    @property
    def concluded(self) -> bool:
        return self.status == "complete" and self.decision is not None

    def tool_outputs(self) -> list[ToolOutput]:
        return [output for session in self.sessions.values() for output in session.tool_outputs]

    def sources(self) -> list[tuple[str, Source]]:
        return [
            (member, source)
            for member, session in self.sessions.items()
            for source in session.sources
        ]

    def to_payload(self) -> dict[str, Any]:
        """The full session, for ``var/<pack>/committee/<id>.json`` (commit 17)."""
        return {
            "committee_record_id": self.record_id,
            "pack": self.pack,
            "version": self.version,
            "question": self.question,
            "status": self.status,
            "reason": self.reason,
            "halted": self.halted,
            "roles": [role.to_payload() | {"output": role.output} for role in self.roles],
            "constats": [vars(finding) for finding in self.constats],
            "arguments": [
                vars(point) | {"constats": list(point.constats), "repond_a": list(point.repond_a)}
                for point in self.arguments
            ],
            "decision": self.decision.model_dump(mode="json") if self.decision else None,
            "controller": self.controller.model_dump(mode="json") if self.controller else None,
            "checks": [check.to_payload() for check in self.checks],
            "verdict": self.verdict,
            "verdict_reasons": list(self.verdict_reasons),
            "tool_calls": [output.call for output in self.tool_outputs()],
            "sources": [
                {"member": member, "number": source.number, "url": source.final_url}
                for member, source in self.sources()
            ],
        }


def seat_for(config: Config, pack: str, member: str) -> Seat:
    """The tier ``committee.yaml`` gives a member; a member it does not list is inactive."""
    committee = getattr(config.committee, pack, None)
    if committee is None:
        raise ValueError(f"{pack} : aucun Comité dans committee.yaml")
    tiers = committee.tiers
    if member not in tiers:
        raise ValueError(f"{member} : aucun niveau de modèle dans committee.yaml (rôle inactif)")
    return Seat(member, tiers[member])


def digest(output: dict[str, Any]) -> str:
    canonical = json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _AnalystTask(BaseModel):
    member: str


class _State(BaseModel):
    done: Annotated[list[str], operator.add] = []  # members who answered, stage by stage
    round: int = 0


class _Committee:
    """The nodes of one session; the graph state only orders them, the ``Sitting`` holds all."""

    def __init__(
        self, run: Run, spec: CommitteeSpec, sitting: Sitting, *, question: str, now: str
    ) -> None:
        self.run, self.spec, self.sitting = run, spec, sitting
        self.question, self.now = question, now
        self.max_rounds = run.config.committee.max_debate_rounds
        self.seats = {
            card.member: seat_for(run.config, spec.pack, card.member) for card in spec.cards()
        }
        self.places = {card.member: n for n, card in enumerate(spec.cards())}
        self.cards = {card.member: card for card in spec.cards()}

    # --- one role ---------------------------------------------------------------------------

    def _halt_if_engaged(self) -> None:
        if kill_switch_engaged(self.run.project_root):
            raise KillSwitchEngaged

    def _tools(self, card: Card) -> list[Any]:
        toolbox = self.run.toolbox
        if toolbox is None or not card.tools:
            return []
        return [tool for tool in toolbox.tools if tool.name in card.tools]

    async def _tool(self, card: Card, session: Session | None, call: ToolCall) -> str:
        if session is None or call["name"] not in card.tools:
            return NO_TOOL.format(name=call["name"])
        if call["name"] == LAB and (call.get("args") or {}).get("mode") not in LAB_MODES:
            return LAB_MODE
        return await _execute(self.run, session, self.run.toolbox, call, self.question)

    async def _speak[T: RoleOutput](
        self,
        card: Card,
        task: str,
        schema: type[T],
        check: Callable[[T], list[str]],
        *,
        round: int = 0,
        session: Session | None = None,
    ) -> tuple[T, RoleRecord]:
        """The member's answer, checked; one repair, then ``RoleFailed``."""
        self._halt_if_engaged()
        seat = self.seats[card.member]
        record = RoleRecord(
            member=card.member,
            kind=card.kind,
            round=round,
            model=self.run.router.model_id("committee", seat),
            valid=False,
            attempts=0,
            position=(_STAGES[card.kind], round, self.places[card.member]),
        )
        system = (
            card.system
            + "\n\n"
            + FORMAT.format(schema=json.dumps(schema.model_json_schema(), ensure_ascii=False))
        )
        messages: list[BaseMessage] = [SystemMessage(system), HumanMessage(task)]
        tools = self._tools(card) if session is not None else []
        errors: list[str] = []
        for _turn in range(MAX_ROLE_TURNS):
            reply: AIMessage = await self.run.invoke("committee", messages, tools=tools, seat=seat)
            messages.append(reply)
            if reply.tool_calls:
                for call in reply.tool_calls:
                    content = await self._tool(card, session, call)
                    messages.append(ToolMessage(content=content, tool_call_id=call["id"]))
                continue
            record.attempts += 1
            try:
                output = parse_json(message_text(reply), schema)
                errors = check(output)
            except ValueError as exc:
                errors = [short_error(exc)]
            if not errors:
                dumped = output.model_dump(mode="json")
                record.valid, record.output, record.sha256 = True, dumped, digest(dumped)
                return output, record
            if record.attempts > 1:
                break
            shown = " ; ".join(errors[:MAX_ERRORS])
            messages.append(HumanMessage(REPAIR.format(errors=shown)))
        record.error = " ; ".join(errors[:MAX_ERRORS]) if errors else TOO_MANY_TURNS
        self.sitting.roles.append(record)
        raise RoleFailed(record)

    # --- evidence ---------------------------------------------------------------------------

    def _texts(self, sessions: Sequence[tuple[str, Session]]) -> list[tuple[str, str]]:
        texts = [(QUESTION, self.question), (TODAY, self.now)]
        for member, session in sessions:
            texts += [
                (f"{member}:source [{source.number}]", extract.quote)
                for source in session.sources
                for extract in source.extracts
            ]
            texts += [(f"{member}:recherche web", text) for text in session.search_texts]
        return texts

    def _evidence(self, *extra: tuple[str, Session]) -> Evidence:
        """What a role may cite: the question, the date, the search results, every tool output
        and, of a page, the quotes of the extracts kept: the rest of the page, an extract set
        aside as an instruction included, is no evidence (R5)."""
        sessions = [*self.sitting.sessions.items(), *extra]
        outputs = [output for _member, session in sessions for output in session.tool_outputs]
        return Evidence(self._texts(sessions), outputs)

    def _calls(self) -> set[str]:
        return {output.call for output in self.sitting.tool_outputs()}

    # --- material shown to the roles --------------------------------------------------------

    def _head(self) -> str:
        return f"Question de Lucas : {self.question}\nDate du jour : {self.now}\n"

    def _constats_view(self) -> str:
        lines = [
            f"{finding.id} [{finding.member}] {finding.texte}"
            + (f" (date : {finding.date})" if finding.date else "")
            for finding in self.sitting.constats
        ]
        return mark_untrusted("\n".join(lines), source="constats des analystes")

    def _arguments_view(self, points: Sequence[Point]) -> str:
        if not points:
            return "aucun"
        lines = [
            f"{point.id} [{point.member}, poids {point.poids}] {point.texte} "
            f"(constats : {', '.join(point.constats)}"
            + (f" ; répond à : {', '.join(point.repond_a)})" if point.repond_a else ")")
            for point in points
        ]
        return mark_untrusted("\n".join(lines), source="arguments du débat")

    # --- nodes ------------------------------------------------------------------------------

    def fan_out(self, _state: _State) -> list[Send]:
        return [Send("analyst", _AnalystTask(member=card.member)) for card in self.spec.analysts]

    async def analyst(self, task: _AnalystTask) -> dict[str, Any]:
        card = self.cards[task.member]
        session = Session(call_prefix=f"{card.member}:")
        self.sitting.sessions[card.member] = session
        tools = [tool.name for tool in self._tools(card)]
        prompt = (
            self._head() + f"Outils à ta disposition : {', '.join(tools) or 'aucun'}.\n"
            "Établis tes constats. Chacun cite, dans « appel », l'identifiant de l'appel d'outil "
            "tel qu'il t'est montré (attribut source des données), ou « source [n] » pour une page "
            "lue. Ne cite que ce que tes outils t'ont donné pendant cette séance."
        )

        def check(report: AnalystReport) -> list[str]:
            return analyst_errors(
                report,
                calls={output.call for output in session.tool_outputs},
                sources=set(session.pages),
                evidence=self._evidence(),
            )

        report, record = await self._speak(card, prompt, AnalystReport, check, session=session)
        self.sitting.reports[card.member] = report
        self.sitting.roles.append(record)
        return {"done": [card.member]}

    def number_findings(self, _state: _State) -> dict[str, Any]:
        """``C1``… in the order of the cards, whatever order the analysts finished in."""
        self._halt_if_engaged()
        records = {r.member: r for r in self.sitting.roles if r.kind == "analyste"}
        for card in self.spec.analysts:
            ids: list[str] = []
            session = self.sitting.sessions[card.member]
            calls = {output.call for output in session.tool_outputs}
            for constat in self.sitting.reports[card.member].constats:
                origin = finding_origin(constat.appel, calls, set(session.pages))
                if origin is None:  # analyst_errors refused it already
                    raise NoDecision(f"{card.member} : constat sans appel connu")
                if origin.startswith("source ["):
                    origin = f"{card.member}:{origin}"
                finding_id = f"C{len(self.sitting.constats) + 1}"
                self.sitting.constats.append(
                    Finding(
                        finding_id, card.member, constat.texte, constat.appel, origin, constat.date
                    )
                )
                ids.append(finding_id)
            records[card.member].constats = tuple(ids)
        if not self.sitting.constats:
            raise NoDecision("aucun constat des analystes : rien à débattre")
        return {"round": 1}

    async def _debate_turn(self, card: Card, round: int, earlier: list[Point]) -> list[Point]:
        side = _SIDES[card.kind]
        prompt = (
            self._head() + f"Débat, tour {round} sur {self.max_rounds}.\n"
            f"Constats des analystes :\n{self._constats_view()}\n"
            f"Arguments des tours précédents :\n{self._arguments_view(earlier)}\n"
            "Chaque argument cite au moins un constat par son identifiant (C1, C2…). « repond_a » "
            "ne vise que des arguments des tours précédents. Dis ce qui te ferait changer d'avis."
        )
        constats = {finding.id for finding in self.sitting.constats}
        earlier_ids = {point.id for point in earlier}

        def check(turn: DebateTurn) -> list[str]:
            return debate_errors(
                turn, constats=constats, earlier=earlier_ids, evidence=self._evidence()
            )

        turn, record = await self._speak(card, prompt, DebateTurn, check, round=round)
        record.constats = tuple(sorted({c for a in turn.arguments for c in a.constats}))
        self.sitting.roles.append(record)
        return [
            Point(
                f"{side}{round}.{n}",
                card.member,
                round,
                argument.texte,
                argument.poids,
                tuple(argument.constats),
                tuple(argument.repond_a),
            )
            for n, argument in enumerate(turn.arguments, start=1)
        ]

    async def debate(self, state: _State) -> dict[str, Any]:
        """Both sides speak at once, on what the earlier rounds said."""
        self._halt_if_engaged()
        earlier = list(self.sitting.arguments)
        results = await asyncio.gather(
            self._debate_turn(self.spec.defender, state.round, earlier),
            self._debate_turn(self.spec.challenger, state.round, earlier),
            return_exceptions=True,  # both finish before a failure is raised: no orphan call
        )
        points: list[Point] = []
        for result in results:
            if isinstance(result, BaseException):
                raise result
            points += result
        self.sitting.arguments += points
        return {"round": state.round + 1, "done": [f"tour {state.round}"]}

    def after_debate(self, state: _State) -> str:
        return "debate" if state.round <= self.max_rounds else "manager"

    async def manager(self, _state: _State) -> dict[str, Any]:
        card = self.spec.manager
        points = self.sitting.arguments
        ids = [point.id for point in points]
        prompt = (
            self._head() + f"Constats des analystes :\n{self._constats_view()}\n"
            f"Arguments du débat :\n{self._arguments_view(points)}\n"
            f"Traite chaque argument une fois, retenu ou écarté avec sa raison : {', '.join(ids)}."
            "\nUn seuil chiffré d'une condition d'invalidation doit venir d'une sortie d'outil."
            "\nSi tu décides d'agir, chaque nombre de la proposition vient d'une sortie d'outil "
            "ou de la question de Lucas, jamais d'une page."
            "\nSi tu décides d'agir, nomme le catalyseur : ce qui rend l'action opportune "
            "maintenant, relié à ses constats ; une décision d'agir sans catalyseur est bloquée "
            "par le code."
        )
        constats = {finding.id for finding in self.sitting.constats}

        def check(decision: ManagerDecision) -> list[str]:
            return manager_errors(
                decision,
                arguments=ids,
                constats=constats,
                calls=self._calls(),
                evidence=self._evidence(),
            )

        decision, record = await self._speak(card, prompt, ManagerDecision, check)
        cited = {c for i in decision.invalidation for c in i.constats}
        if decision.catalyseur is not None:
            cited |= set(decision.catalyseur.constats)
        record.constats = tuple(sorted(cited))
        self.sitting.roles.append(record)
        self.sitting.decision = decision
        return {"done": [card.member]}

    async def controller(self, _state: _State) -> dict[str, Any]:
        self._halt_if_engaged()
        card = self.spec.controller
        decision = self.sitting.decision
        if decision is None:  # the graph runs the manager first
            raise NoDecision("aucune proposition du gestionnaire")
        checks = tuple(self.spec.limit_checks(decision, self.sitting.tool_outputs()))
        self.sitting.checks = checks
        session = Session(call_prefix=f"{card.member}:")
        tools = [tool.name for tool in self._tools(card)]
        shown = [
            f"{check.name} : "
            + {True: "respectée", False: "dépassée", None: "inconnue"}[check.ok]
            + f" ({check.reason})"
            for check in checks
        ] or ["aucun contrôle n'a pu être fait"]
        blockers = decision_blockers(decision)
        blocked = (
            "Blocages de la proposition, calculés par le code (tu ne peux pas les lever) :\n- "
            + "\n- ".join(blockers)
            + "\n"
            if blockers
            else ""
        )
        proposal = json.dumps(decision.model_dump(mode="json"), ensure_ascii=False)
        prompt = (
            self._head()
            + f"Proposition du gestionnaire :\n{mark_untrusted(proposal, source='gestionnaire')}\n"
            "Contrôles des limites, calculés par le code (une limite dépassée ou inconnue "
            "bloque, et tu ne peux pas lever ce blocage) :\n- "
            + "\n- ".join(shown)
            + "\n"
            + blocked
            + f"Outils à ta disposition : {', '.join(tools) or 'aucun'}.\n"
            "Chiffre chaque scénario défavorable par un appel d'outil, dont tu donnes "
            "l'identifiant tel qu'il t'est montré ; un scénario sans appel (null) bloque."
        )

        def check(report: ControllerReport) -> list[str]:
            return controller_errors(
                report,
                calls={output.call for output in session.tool_outputs},  # its own calls only
                evidence=self._evidence((card.member, session)),
            )

        try:
            report, record = await self._speak(
                card, prompt, ControllerReport, check, session=session
            )
        finally:
            self.sitting.sessions[card.member] = session  # its tool outputs, even on failure
        self.sitting.roles.append(record)
        self.sitting.controller = report
        self.sitting.verdict, self.sitting.verdict_reasons = final_verdict(
            checks, report, decision=decision
        )
        self.sitting.status, self.sitting.reason = "complete", None
        return {"done": [card.member]}

    def graph(self) -> Any:
        builder = StateGraph(_State)
        builder.add_node("analyst", self.analyst)
        builder.add_node("findings", self.number_findings)
        builder.add_node("debate", self.debate)
        builder.add_node("manager", self.manager)
        builder.add_node("controller", self.controller)
        builder.add_conditional_edges(START, self.fan_out, ["analyst"])
        builder.add_edge("analyst", "findings")
        builder.add_edge("findings", "debate")
        builder.add_conditional_edges("debate", self.after_debate, ["debate", "manager"])
        builder.add_edge("manager", "controller")
        builder.add_edge("controller", END)
        return builder.compile()


async def run_committee(
    run: Run, spec: CommitteeSpec, *, question: str, now: str, record_id: str
) -> Sitting:
    """One session of the committee on ``question`` (already pseudonymised).

    ``run.budget`` should be the session's (``RequestBudget.for_committee``, D18), set before
    the pack's tools are opened. The session ends complete, incomplete (budget, kill switch:
    ``halted``) or failed (« pas de décision »); any other error propagates.
    """
    run.config.require(spec.feature)  # R7: a marker still blocks the committee
    sitting = Sitting(record_id=record_id, question=question, pack=spec.pack, version=spec.version)
    committee = _Committee(run, spec, sitting, question=question, now=now)
    limit = committee.max_rounds + 10  # analysts, findings, rounds, manager, controller
    try:
        await committee.graph().ainvoke(_State(), config={"recursion_limit": limit})
    except NoDecision as exc:
        sitting.status, sitting.reason = "echec", exc.reason
    except RequestBudgetExceeded as exc:
        sitting.status, sitting.reason = "incomplete", f"budget:{exc.limit}"
    except KillSwitchEngaged:
        sitting.status, sitting.reason, sitting.halted = "incomplete", "kill_switch", True
    sitting.roles.sort(key=lambda record: record.position)
    return sitting
