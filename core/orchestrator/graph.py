"""The 8-node graph of section 7.1 and the orchestrator that runs one request.

context → guard → route → plan → verify → output → policy → audit. The kill switch, a refused
question and a question that needs a clarification go straight to the output; every request,
answered or not, ends with one DECISION entry in the audit journal (R11) that carries its cost
(the ledger reads it) and counts, never the question, the answer or a URL.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
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
from core.config.loader import Config
from core.guardrails.pii import PiiAnalyzer, Pseudonymiser
from core.models.router import ModelRouter
from core.orchestrator.answer import map_texts, output_node, render_json, render_markdown
from core.orchestrator.intake import context_node, guard_node, route_node
from core.orchestrator.planner import plan_node
from core.orchestrator.prompts import PromptSet
from core.orchestrator.runtime import (
    WEB_PLUGIN,
    PseudonymiserLike,
    Run,
    ToolboxOpener,
    mcp_toolbox,
)
from core.orchestrator.state import Answer, CerveauState, required
from core.orchestrator.verify import verify_node
from core.policy.engine import decide, kill_switch_engaged

Node = Callable[[Run, CerveauState], Awaitable[dict[str, Any]]]
RECURSION_LIMIT = 20  # 8 nodes, no cycle in the graph
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
    )
    if not decision.allowed and answer.statut != "refus":
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
        }
    if (draft := state.draft) is not None:
        payload["planner"] = {
            "turns": draft.turns,
            "searches": draft.searches,
            "refused_urls": draft.refused_urls,
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
        }
    if answer is not None:
        digest = hashlib.sha256(answer.model_dump_json().encode()).hexdigest()
        payload["answer"] = {"links_removed": answer.links_removed, "sha256": digest}
    return payload


async def audit_node(run: Run, state: CerveauState) -> dict[str, Any]:
    run.journal.append(
        actor="orchestrator",
        event="DECISION",
        request_id=run.request_id,
        versions=versions(run),
        payload=audit_payload(run, state),
    )
    run.audited = True
    return {"audited": True}


NODES: Sequence[tuple[str, Node]] = (
    ("contexte", context_node),
    ("garde", guard_node),
    ("routage", route_node),
    ("planification", plan_node),
    ("controle", verify_node),
    ("sortie", output_node),
    ("politique", policy_node),
    ("journal", audit_node),
)


def _after_context(state: CerveauState) -> str:
    return "sortie" if required(state.context, "contexte").kill_switch else "garde"


def _after_guard(state: CerveauState) -> str:
    return "routage" if required(state.guarded, "garde").decision == "ok" else "sortie"


def build_graph(run: Run) -> Any:
    """The compiled graph for one request; each node gets the request's ``Run``."""
    graph = StateGraph(CerveauState)

    def bind(fn: Node) -> Callable[[CerveauState], Awaitable[dict[str, Any]]]:
        async def node(state: CerveauState) -> dict[str, Any]:
            return await fn(run, state)

        return node

    for name, fn in NODES:
        graph.add_node(name, bind(fn))
    graph.set_entry_point("contexte")
    graph.add_conditional_edges("contexte", _after_context, {"sortie": "sortie", "garde": "garde"})
    graph.add_conditional_edges("garde", _after_guard, {"sortie": "sortie", "routage": "routage"})
    for source, target in (
        ("routage", "planification"),
        ("planification", "controle"),
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
        open_toolbox: ToolboxOpener | None = None,
        pseudonymiser: Callable[[], PseudonymiserLike] | None = None,
        prompts: PromptSet | None = None,
        callbacks: Sequence[BaseCallbackHandler] = (),
        clock: Callable[[], datetime] | None = None,
        budget_clock: Callable[[], float] | None = None,
        tz: tzinfo | None = None,
    ) -> None:
        self.config = config
        self.project_root = project_root
        self.journal = journal or AuditJournal(default_journal_path(project_root))
        self.router = router or ModelRouter(config)
        self.open_toolbox = open_toolbox or mcp_toolbox(project_root / "plugins" / WEB_PLUGIN)
        self.prompts = prompts or PromptSet.load()
        self.callbacks = tuple(callbacks)
        self._new_pseudonymiser = pseudonymiser or self._presidio
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._budget_clock = budget_clock
        self._tz = tz
        self._analyzer: PiiAnalyzer | None = None

    def _presidio(self) -> PseudonymiserLike:
        if self._analyzer is None:  # spaCy's French model loads once per process
            self._analyzer = PiiAnalyzer.from_config(self.config)
        return Pseudonymiser(self._analyzer)

    async def ask(self, question: str, *, request_id: str | None = None) -> RunResult:
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
            open_toolbox=self.open_toolbox,
            callbacks=self.callbacks,
        )
        try:
            result = await build_graph(run).ainvoke(
                CerveauState(request_id=request_id), config={"recursion_limit": RECURSION_LIMIT}
            )
            final = CerveauState.model_validate(result)
        except BaseException as exc:
            if not run.audited:  # the money spent so far still reaches the ledger
                payload = audit_payload(run, CerveauState(request_id=request_id), status="erreur")
                payload["error"] = type(exc).__name__
                self.journal.append(
                    actor="orchestrator",
                    event="DECISION",
                    request_id=request_id,
                    versions=versions(run),
                    payload=payload,
                )
            raise
        finally:
            await run.aclose()
        answer = map_texts(required(final.answer, "sortie"), pseudonymiser.reidentify)
        return RunResult(
            request_id=request_id,
            answer=answer,
            cost_eur=meter.total_eur,
            tokens=meter.total_tokens,
            tool_calls=budget.tool_calls,
            elapsed_s=round(budget.elapsed_s, 3),
            budget_alerts=alerts,
        )
