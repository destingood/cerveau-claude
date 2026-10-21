"""The graph of section 7.1 and the orchestrator that runs one request.

context → guard → route → plan → verify → output → policy → audit; a decision question routed to
a pack's committee (D15) goes route → committee → output instead. The kill switch, an enabled
live configuration (R3), a refused question (by the guard, or once routed to a domain that cannot
carry out its action class) and a question that needs a clarification go straight to the output,
before any model call or tool for the first two; a kill switch
engaged while the request runs stops it before the next model call, with a refusal. Every request,
answered or not, ends with one DECISION entry in the audit journal (R11) that carries its cost
(the ledger reads it) and counts, never the question, the answer or a URL; one ERROR entry per
error the request shows follows it (ADR-011). A committee session writes before it one DECISION
entry per role, with the digest of the session file ``var/<pack>/committee/<id>.json`` (D19).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo
from decimal import Decimal
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langgraph.graph import END, StateGraph

from core.audit import AuditJournal
from core.audit.chain import default_journal_path
from core.budget.gate import BudgetGate, RequestBudget
from core.budget.ledger import COST_KEY
from core.committee.engine import CommitteeSpec, Sitting, run_committee
from core.config.loader import Config
from core.guardrails.pii import PiiAnalyzer, Pseudonymiser
from core.learning.errors import decision_errors, journal_errors
from core.models.router import ModelRouter
from core.observability.tracing import NoTracer, Tracer
from core.orchestrator.answer import map_texts, output_node, render_json, render_markdown
from core.orchestrator.intake import KILL_MESSAGE, context_node, guard_node, route_node
from core.orchestrator.packs import DEFAULT_DOMAIN, Pack, load_packs
from core.orchestrator.planner import plan_node
from core.orchestrator.prompts import PromptSet
from core.orchestrator.runtime import (
    KillSwitchEngaged,
    PseudonymiserLike,
    Run,
    ToolboxOpener,
    mcp_toolbox,
)
from core.orchestrator.state import (
    Answer,
    CerveauState,
    CommitteeOutcome,
    TraceRow,
    required,
)
from core.orchestrator.verify import verify_node
from core.policy.engine import decide, kill_switch_engaged
from core.registry.agents import load_agent
from core.verification.trace import ToolOutput

Node = Callable[[Run, CerveauState], Awaitable[dict[str, Any]]]
RECURSION_LIMIT = 20  # 9 nodes, no cycle in the graph
PLUGINS_DIR = Path(__file__).resolve().parents[2] / "plugins"  # in-process agents (committees)
MAX_TRACE_ROWS = 200  # the counts stay whole beyond it
POLICY_REFUSAL = "Réponse retenue par le moteur de politique"


async def policy_node(run: Run, state: CerveauState) -> dict[str, Any]:
    context, answer = required(state.context, "contexte"), required(state.answer, "sortie")
    guarded = state.guarded
    action = guarded.action_class if guarded is not None and guarded.decision == "ok" else "LECTURE"
    decision = decide(
        run.config.autonomy,
        request_id=run.request_id,
        domain=context.domain,
        action_class=action,
        kill_switch=kill_switch_engaged(run.project_root),
        live_enabled=run.config.live.enabled,
    )
    if decision.effect != "executer" and answer.statut != "refus":
        reasons = " ; ".join(decision.reasons)
        answer = Answer(statut="refus", message=f"{POLICY_REFUSAL} : {reasons}")
    return {"policy": decision.to_payload(), "answer": answer}


def versions(run: Run) -> dict[str, str]:
    models = ", ".join(f"{role}={model}" for role, model in sorted(run.models_used.items()))
    return {
        "prompt": run.prompts.version,
        "model": models or "aucun",
        "config": run.config.digest,
        "plugin": run.toolbox.version if run.toolbox is not None else "aucun",
    }


def trace_metadata(run: Run, status: str) -> dict[str, str | int]:
    """What a trace carries besides the model calls: CERVEAU's own costs (R1), no text."""
    run_versions = versions(run)
    return {
        "status": status,
        "cost_eur": str(run.meter.total_eur),
        "tokens": run.meter.total_tokens,
        "tool_calls": run.budget.tool_calls,
        "elapsed_s": f"{run.budget.elapsed_s:.3f}",
        "models": run_versions["model"],
        "plugin": run_versions["plugin"],
    }


def trace_payload(rows: Sequence[TraceRow]) -> dict[str, Any]:
    """Where each number and date of the answer comes from, without the numbers (R1, R11)."""
    numbers = [row for row in rows if row.kind == "nombre"]
    dates = [row for row in rows if row.kind != "nombre"]
    return {
        "numbers_checked": len(numbers),
        "numbers_traced": sum(row.traced for row in numbers),
        "numbers_contrary": sum(row.contrary for row in numbers),
        "dates_checked": len(dates),
        "dates_unmatched": sum(not row.traced for row in dates),
        "trace": [
            {"field": row.field, "n": row.n, "kind": row.kind, "origin": row.origin}
            | ({"contrary": True} if row.contrary else {})
            for row in rows[:MAX_TRACE_ROWS]
        ],
        "trace_truncated": len(rows) > MAX_TRACE_ROWS,
    }


def audit_payload(run: Run, state: CerveauState, *, status: str | None = None) -> dict[str, Any]:
    """Counts and versions only: no question, answer text or URL (R6, R11)."""
    answer = state.answer
    payload: dict[str, Any] = {
        "status": status or (answer.statut if answer is not None else "erreur"),
        COST_KEY: run.meter.to_payload(),
        "budget": run.budget.to_payload(),
    }
    if state.policy is not None:
        payload["policy"] = state.policy
    if (guarded := state.guarded) is not None:
        payload["guard"] = {
            "decision": guarded.decision,
            "action_class": guarded.action_class,
            "pii": dict(sorted(guarded.pii_counts.items())),
            "removed_characters": guarded.removed_characters,
            "urls_given": len(guarded.urls),
        }
    if (route := state.route) is not None:
        payload["route"] = {
            "domain": route.domain,
            "requested_domain": route.requested_domain,
            "complexity": route.complexity,
            "importance": route.importance,
            "needs_web": route.needs_web,
            "role": route.role,
            "tier": route.tier,
            "tools": list(route.tools),
            "skipped": sorted(route.skipped),
            "mode": route.mode,
        }
    if (committee := state.committee) is not None:
        payload["committee"] = {
            "committee_record_id": committee.record_id,
            "pack": committee.pack,
            "version": committee.version,
            "status": committee.status,
            "reason": committee.reason,
            "roles": committee.roles,
            "verdict": committee.verdict,
            "file_sha256": committee.file_sha256,
        }
    if (draft := state.draft) is not None:
        payload["planner"] = {
            "turns": draft.turns,
            "searches": draft.searches,
            "refused_urls": draft.refused_urls,
            "masked_urls": draft.masked_urls,
            "refused_searches": draft.refused_searches,
            "refused_outputs": draft.refused_outputs,
            "bounded_outputs": draft.bounded_outputs,
            "partial": draft.partial,
            "limit": draft.limit,
            "format_issues": len(draft.format_issues),
        }
        payload["sources"] = {
            "count": len(draft.sources),
            "domains": sorted({s.domain for s in draft.sources if s.domain}),
        }
        payload["injection"] = {
            "pages_with_signals": sum(1 for s in draft.sources if s.signals),
            "signals": sorted({name for s in draft.sources for name in s.signals}),
            "extracts_kept": sum(len(s.extracts) for s in draft.sources),
            "extracts_flagged": sum(s.flagged for s in draft.sources),
            "extracts_rejected": sum(s.rejected for s in draft.sources),
        }
    if (report := state.verification) is not None:
        payload["verification"] = {
            "quotes_checked": report.quotes_checked,
            "quotes_failed": report.quotes_failed,
            "numbers_unmatched": report.numbers_unmatched,
            "uncited_marked": report.uncited_marked,
            "cited_domains": len(report.cited_domains),
            "confidence": report.confidence,
            "issues": dict(sorted(Counter(issue.kind for issue in report.issues).items())),
            **trace_payload(report.trace),
        }
    if answer is not None:
        digest = hashlib.sha256(answer.model_dump_json().encode()).hexdigest()
        payload["answer"] = {"links_removed": answer.links_removed, "sha256": digest}
    return payload


def journal_decision(run: Run, payload: dict[str, Any]) -> None:
    """The request's DECISION entry, then one ERROR entry per error it shows (ADR-011)."""
    run_versions = versions(run)
    run.journal.append(
        actor="orchestrator",
        event="DECISION",
        request_id=run.request_id,
        versions=run_versions,
        payload=payload,
    )
    run.audited = True
    journal_errors(
        run.journal,
        decision_errors(payload),
        actor="orchestrator",
        request_id=run.request_id,
        versions=run_versions,
    )


def halted_state(run: Run) -> CerveauState:
    """R4: the state the interrupted node was given, with what it had produced when it keeps it
    (the planner's partial draft, the committee's session: B97), and the kill switch's refusal."""
    state = run.last_state
    if not isinstance(state, CerveauState):
        state = CerveauState(request_id=run.request_id)
    domain = state.context.domain if state.context is not None else DEFAULT_DOMAIN
    decision = decide(
        run.config.autonomy,
        request_id=run.request_id,
        domain=domain,
        action_class="LECTURE",
        kill_switch=True,
        live_enabled=run.config.live.enabled,
    )
    answer = Answer(statut="refus", message=KILL_MESSAGE)
    return state.model_copy(update={"answer": answer, "policy": decision.to_payload()})


def committee_file(root: Path, pack: str, record_id: str) -> Path:
    return root / "var" / pack / "committee" / f"{record_id}.json"


def _outcome(run: Run, sitting: Sitting) -> CommitteeOutcome:
    """Writes the session file, then one DECISION entry per role that cites its digest (D19)."""
    path = committee_file(run.project_root, sitting.pack, sitting.record_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(sitting.to_payload(), ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(data)
    file_sha256 = hashlib.sha256(data).hexdigest()
    run_versions = versions(run)  # the committee's version goes in the payload (VERSION_KEYS)
    for record in sitting.roles:  # no cost here: the request's entry carries it (ledger)
        entry = {
            "committee_record_id": sitting.record_id,
            "pack": sitting.pack,
            "version": sitting.version,
            **record.to_payload(),
        }
        run.journal.append(
            actor="orchestrator",
            event="DECISION",
            request_id=run.request_id,
            versions=run_versions,
            payload={"committee": entry | {"file_sha256": file_sha256}},
        )
    decision = sitting.decision.model_dump(mode="json") if sitting.decision else None
    return CommitteeOutcome(
        record_id=sitting.record_id,
        pack=sitting.pack,
        version=sitting.version,
        status=sitting.status,
        reason=sitting.reason,
        halted=sitting.halted,
        decision=decision,
        verdict=sitting.verdict,
        verdict_reasons=sitting.verdict_reasons,
        roles=len(sitting.roles),
        file=path.relative_to(run.project_root).as_posix(),
        file_sha256=file_sha256,
        tool_outputs=tuple(sitting.tool_outputs()),
        sources=tuple(source for _member, source in sitting.sources()),
    )


async def committee_node(run: Run, state: CerveauState) -> dict[str, Any]:
    """One session of the routed pack's committee; the kill switch then stops the request (R4)."""
    guarded, route = required(state.guarded, "garde"), required(state.route, "routage")
    context = required(state.context, "contexte")
    spec = run.committee_for(route.domain) if run.committee_for is not None else None
    if spec is None:  # the route only chooses the committee when the pack has one
        raise RuntimeError(f"aucun Comité pour le pack « {route.domain} »")
    sitting = await run_committee(
        run, spec, question=guarded.question, now=context.now, record_id=str(uuid.uuid4())
    )
    outcome = _outcome(run, sitting)
    if outcome.halted:
        run.last_state = state.model_copy(update={"committee": outcome})
        raise KillSwitchEngaged
    return {"committee": outcome}


async def audit_node(run: Run, state: CerveauState) -> dict[str, Any]:
    journal_decision(run, audit_payload(run, state))
    return {"audited": True}


NODES: Sequence[tuple[str, Node]] = (
    ("contexte", context_node),
    ("garde", guard_node),
    ("routage", route_node),
    ("planification", plan_node),
    ("comite", committee_node),
    ("controle", verify_node),
    ("sortie", output_node),
    ("politique", policy_node),
    ("journal", audit_node),
)


def _after_context(state: CerveauState) -> str:
    context = required(state.context, "contexte")
    return "sortie" if context.kill_switch or context.live_enabled else "garde"


def _after_guard(state: CerveauState) -> str:
    return "routage" if required(state.guarded, "garde").decision == "ok" else "sortie"


def _after_route(state: CerveauState) -> str:
    if required(state.guarded, "garde").decision != "ok":
        return "sortie"
    return "comite" if required(state.route, "routage").mode == "comite" else "planification"


def build_graph(run: Run) -> Any:
    """The compiled graph for one request; each node gets the request's ``Run``."""
    graph = StateGraph(CerveauState)

    def bind(fn: Node) -> Callable[[CerveauState], Awaitable[dict[str, Any]]]:
        async def node(state: CerveauState) -> dict[str, Any]:
            run.last_state = state  # what a kill switch engaged in this node journals
            return await fn(run, state)

        return node

    for name, fn in NODES:
        graph.add_node(name, bind(fn))
    graph.set_entry_point("contexte")
    graph.add_conditional_edges("contexte", _after_context, {"sortie": "sortie", "garde": "garde"})
    graph.add_conditional_edges("garde", _after_guard, {"sortie": "sortie", "routage": "routage"})
    graph.add_conditional_edges(
        "routage",
        _after_route,
        {"sortie": "sortie", "planification": "planification", "comite": "comite"},
    )
    for source, target in (
        ("planification", "controle"),
        ("comite", "sortie"),
        ("controle", "sortie"),
        ("sortie", "politique"),
        ("politique", "journal"),
    ):
        graph.add_edge(source, target)
    graph.add_edge("journal", END)
    return graph.compile()


@dataclass(frozen=True)
class RunResult:
    request_id: str
    answer: Answer  # re-identified: for Lucas only, never journaled
    cost_eur: Decimal
    tokens: int
    tool_calls: int
    elapsed_s: float
    budget_alerts: tuple[str, ...] = ()  # highest daily / monthly threshold reached, for display
    now: str | None = None  # the date of the day the models were given
    tool_outputs: tuple[ToolOutput, ...] = ()  # the computed results the answer may cite (R1)

    def markdown(self) -> str:
        return render_markdown(self.answer)

    def json(self) -> str:
        return render_json(self.answer)


class Orchestrator:
    def __init__(
        self,
        config: Config,
        *,
        project_root: Path,
        journal: AuditJournal | None = None,
        router: ModelRouter | None = None,
        toolboxes: Mapping[str, ToolboxOpener] | None = None,  # plugin → opener; None: MCP servers
        packs: Mapping[str, Pack] | None = None,
        pseudonymiser: Callable[[], PseudonymiserLike] | None = None,
        prompts: PromptSet | None = None,
        callbacks: Sequence[BaseCallbackHandler] = (),
        tracer: Tracer | None = None,
        clock: Callable[[], datetime] | None = None,
        budget_clock: Callable[[], float] | None = None,
        tz: tzinfo | None = None,
        committees: Mapping[str, CommitteeSpec] | None = None,  # pack → spec; None: its agent
    ) -> None:
        self.config = config
        self.project_root = project_root
        self.journal = journal or AuditJournal(default_journal_path(project_root))
        self.router = router or ModelRouter(config)
        self.toolboxes = toolboxes
        self.packs = packs if packs is not None else load_packs()
        self.prompts = prompts or PromptSet.load(tuple(self.packs))
        self.callbacks = tuple(callbacks)
        self.tracer: Tracer = tracer or NoTracer()
        self._new_pseudonymiser = pseudonymiser or self._presidio
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._budget_clock = budget_clock
        self._tz = tz
        self._analyzer: PiiAnalyzer | None = None
        self._committees: dict[str, CommitteeSpec | None] = dict(committees or {})
        self._given_committees = committees is not None

    def committee_spec(self, pack_id: str) -> CommitteeSpec | None:
        """The pack's committee (D15): the specs given (tests, evals) or its registered agent."""
        if pack_id in self._committees or self._given_committees:
            return self._committees.get(pack_id)
        pack = self.packs.get(pack_id)
        spec = None
        if pack is not None and pack.comite is not None:
            spec = load_agent(PLUGINS_DIR / pack.comite)(self.config)
        self._committees[pack_id] = spec
        return spec

    def open_plugin(self, name: str) -> ToolboxOpener | None:
        """The plugin's MCP server, or only the openers given (tests, evals)."""
        if self.toolboxes is not None:
            return self.toolboxes.get(name)
        return mcp_toolbox(self.project_root / "plugins" / name)

    def _presidio(self) -> PseudonymiserLike:
        if self._analyzer is None:  # spaCy's French model loads once per process
            self._analyzer = PiiAnalyzer.from_config(self.config)
        return Pseudonymiser(self._analyzer)

    async def ask(
        self, question: str, *, request_id: str | None = None, committee: bool = False
    ) -> RunResult:
        request_id = request_id or str(uuid.uuid4())
        now = self._clock()
        gate = BudgetGate(self.config, self.journal, tz=self._tz)
        alerts = tuple(a.message() for a in gate.check(now=now, request_id=request_id).highest())
        meter = self.router.new_meter()
        clock = {"clock": self._budget_clock} if self._budget_clock is not None else {}
        budget = RequestBudget.from_config(self.config, meter, **clock)
        pseudonymiser = self._new_pseudonymiser()
        run = Run(
            request_id=request_id,
            config=self.config,
            router=self.router,
            meter=meter,
            budget=budget,
            journal=self.journal,
            project_root=self.project_root,
            prompts=self.prompts,
            now=now,
            pseudonymiser=pseudonymiser,
            raw_question=question,
            packs=self.packs,
            open_plugin=self.open_plugin,
            callbacks=self.callbacks + self.tracer.callbacks(),
            committee_forced=committee,
            committee_for=self.committee_spec,
            budget_clock=self._budget_clock,
        )
        start = {"config": self.config.digest}
        with self.tracer.request(
            request_id, version=self.prompts.version, metadata=start
        ) as finish:
            try:
                result = await build_graph(run).ainvoke(
                    CerveauState(request_id=request_id), config={"recursion_limit": RECURSION_LIMIT}
                )
                final = CerveauState.model_validate(result)
            except KillSwitchEngaged:
                final = halted_state(run)
                payload = audit_payload(run, final)
                payload["halted"] = "kill_switch"
                journal_decision(run, payload)
            except BaseException as exc:
                if not run.audited:  # the money spent so far still reaches the ledger
                    state = CerveauState(request_id=request_id)
                    payload = audit_payload(run, state, status="erreur")
                    payload["error"] = type(exc).__name__
                    journal_decision(run, payload)
                finish({**trace_metadata(run, "erreur"), "error": type(exc).__name__})
                raise
            finally:
                await run.aclose()
            final_answer = required(final.answer, "sortie")
            finish(trace_metadata(run, final_answer.statut))
        answer = map_texts(final_answer, pseudonymiser.reidentify)
        outputs: tuple[ToolOutput, ...] = ()
        if final.draft is not None:
            outputs = final.draft.tool_outputs
        elif final.committee is not None:
            outputs = final.committee.tool_outputs
        return RunResult(
            request_id=request_id,
            answer=answer,
            cost_eur=meter.total_eur,
            tokens=meter.total_tokens,
            tool_calls=run.budget.tool_calls,  # the committee's session budget, if one sat
            elapsed_s=round(budget.elapsed_s, 3),  # the whole request
            budget_alerts=alerts,
            now=final.context.now if final.context is not None else None,
            tool_outputs=outputs,
        )
