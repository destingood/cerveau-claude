"""One eval case, end to end: the real orchestrator on the fixture web, the checks, the judge.

Offline, the run happens in a temporary home with its own journal and the offline copy of the
configuration: nothing reaches ``var/audit`` and no key is in reach. Live (D8), the run is a real
request of the campaign: real models, real budgets, real journal; only the web is the fixture web,
so a case reads the same pages in both modes. Each result is written as JSON for the report.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from core.audit.chain import AuditJournal, default_journal_path
from core.config import load_config
from core.config.loader import Config
from core.evals.cases import REPO_ROOT, Case, Suite
from core.evals.checks import Check, Mode, Outcome, r5_breaches, run_checks, sourcing_ok
from core.evals.judge import Judgement, judge
from core.evals.offline import (
    FIXTURE_NOW,
    FixtureReader,
    Pilot,
    Recorder,
    WebLog,
    fixture_toolbox,
    offline_config,
    presidio,
    scripted_router,
)
from core.models.router import ModelRouter
from core.orchestrator.graph import Orchestrator, RunResult
from core.policy.engine import KILL_SWITCH_FILE
from core.verification.citations import citation_numbers

MODE_ENV = "CERVEAU_EVAL_MODE"
OUT_ENV = "CERVEAU_EVAL_OUT"  # where the results go, set by `cerveau eval`
RUN_ENV = "CERVEAU_EVAL_RUN"  # the run the results belong to: the report ignores older ones
CONFIG_ENV = "CERVEAU_EVAL_CONFIG"  # live only: the --config-dir of the campaign
CASES_DIR = "cases"
MANUAL_RUN = "manuel"  # promptfoo started by hand, outside `cerveau eval`
MAX_ERROR_CHARS = 300


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    suite: Suite
    group: str
    mode: Mode
    run: str
    passed: bool
    score: float
    checks: tuple[Check, ...] = ()
    status: str | None = None
    cost_eur: Decimal = Decimal(0)  # the answer; offline, an estimate (« simulé »)
    judge_cost_eur: Decimal = Decimal(0)
    tokens: int = 0
    tool_calls: int = 0
    refused_reads: int = 0
    elapsed_s: float = 0.0
    sourcing: bool | None = None  # None: the case asks for no source
    judgement: Judgement | None = None
    error: str | None = None
    markdown: str = ""

    @property
    def r5_breaches(self) -> int:
        return r5_breaches(self.checks)

    def failures(self) -> list[Check]:
        return [check for check in self.checks if not check.passed]

    def reason(self) -> str:
        if self.error is not None:
            return f"erreur : {self.error}"
        failed = [f"{c.name} ({c.detail})" if c.detail else c.name for c in self.failures()]
        if self.judgement is not None:
            failed.append(f"juge : {self.judgement.score}")
        return " ; ".join(failed) or "ok"

    def to_promptfoo(self) -> dict[str, Any]:
        """The grading result of promptfoo's assertion."""
        return {
            "pass": self.passed,
            "score": self.score,
            "reason": self.reason(),
            "namedScores": {"r5_violations": float(self.r5_breaches)},
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "case": self.case_id,
            "suite": self.suite,
            "group": self.group,
            "mode": self.mode,
            "run": self.run,
            "passed": self.passed,
            "score": self.score,
            "status": self.status,
            "cost_eur": str(self.cost_eur),
            "cost_simulated": self.mode == "offline",
            "judge_cost_eur": str(self.judge_cost_eur),
            "tokens": self.tokens,
            "tool_calls": self.tool_calls,
            "refused_reads": self.refused_reads,
            "elapsed_s": self.elapsed_s,
            "r5_breaches": self.r5_breaches,
            "sourcing": self.sourcing,
            "checks": [check.as_dict() for check in self.checks],
            "judgement": self.judgement.as_dict() if self.judgement is not None else None,
            "error": self.error,
            "reason": self.reason(),
        }


def result_path(out_dir: Path, suite: Suite, case_id: str) -> Path:
    return out_dir / CASES_DIR / suite / f"{case_id}.json"


def save_result(result: CaseResult, out_dir: Path) -> Path:
    path = result_path(out_dir, result.suite, result.case_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(result.to_json(), ensure_ascii=False, indent=2)
    path.write_text(data + "\n", encoding="utf-8")
    return path


def decision_payload(journal: AuditJournal, request_id: str) -> dict[str, Any]:
    """The payload of the request's DECISION entry (the last one, if several)."""
    payload: dict[str, Any] = {}
    if not journal.path.exists():
        return payload
    for line in journal.path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("event") == "DECISION" and entry.get("request_id") == request_id:
            payload = journal.read_payload(entry["payload_ref"])
    return payload


def cites_a_source(outcome: Outcome) -> bool:
    """The synthesis cites a source of the list (live: an answer the judge finds factual)."""
    numbers = {source.number for source in outcome.answer.sources}
    return bool(numbers & set(citation_numbers(outcome.answer.synthese)))


def _pages_read(log: WebLog, reader: FixtureReader) -> list[tuple[str, str]]:
    pages = [reader.page(url) for url in dict.fromkeys(log.reads)]
    return [(page.url, page.text) for page in pages if page is not None]


def _outcome(
    case: Case,
    mode: Mode,
    result: RunResult,
    payload: dict[str, Any],
    recorder: Recorder,
    log: WebLog,
    reader: FixtureReader,
) -> Outcome:
    hits = case.search_hits() if log.queries else ()
    return Outcome(
        case=case,
        mode=mode,
        answer=result.answer,
        payload=payload,
        sent=tuple(recorder.sent),
        executed=tuple(log.arguments()),
        requested=tuple(recorder.requested),
        read_texts=tuple(text for _url, text in _pages_read(log, reader)),
        search_texts=tuple(f"{hit.title} {hit.snippet}" for hit in hits),
        tool_calls=result.tool_calls,
    )


def _score(checks: Sequence[Check]) -> float:
    return round(sum(c.passed for c in checks) / len(checks), 2) if checks else 0.0


def _result(
    outcome: Outcome,
    result: RunResult,
    run: str,
    judgement: Judgement | None = None,
    threshold: Decimal | None = None,
) -> CaseResult:
    case = outcome.case
    checks = tuple(run_checks(outcome))
    passed = all(check.passed for check in checks)
    score = _score(checks)
    sourcing = sourcing_ok(checks)
    if judgement is not None:
        score = float(judgement.score)
        passed = passed and threshold is not None and judgement.score >= threshold
        if judgement.verdict.factuel and sourcing is None:
            sourcing = cites_a_source(outcome)
    return CaseResult(
        case_id=case.id,
        suite=case.suite,
        group=case.group,
        mode=outcome.mode,
        run=run,
        passed=passed,
        score=score,
        checks=checks,
        status=result.answer.statut,
        cost_eur=result.cost_eur,
        judge_cost_eur=judgement.cost_eur if judgement is not None else Decimal(0),
        tokens=result.tokens,
        tool_calls=result.tool_calls,
        refused_reads=int((outcome.payload.get("planner") or {}).get("refused_urls") or 0),
        elapsed_s=result.elapsed_s,
        sourcing=sourcing,
        judgement=judgement,
        markdown=outcome.markdown,
    )


async def _offline(case: Case, root: Path, run: str) -> CaseResult:
    config = offline_config(root / "config")
    log, recorder = WebLog(), Recorder()
    reader = FixtureReader(case, log, root)
    pilot = Pilot(case, reader)
    with tempfile.TemporaryDirectory(prefix="cerveau-eval-", ignore_cleanup_errors=True) as tmp:
        home = Path(tmp)  # no plugin directory, a journal of its own
        journal = AuditJournal(home / "audit" / "journal.jsonl")
        if case.offline.kill_switch:  # R4: the switch of this temporary home only
            kill = home / KILL_SWITCH_FILE
            kill.parent.mkdir(parents=True)
            kill.write_text("éval R4\n", encoding="utf-8")
        orchestrator = Orchestrator(
            config,
            project_root=home,
            journal=journal,
            router=scripted_router(config, pilot),
            open_toolbox=fixture_toolbox(case, log, root),
            pseudonymiser=lambda: presidio(config),
            callbacks=(recorder,),
            clock=lambda: FIXTURE_NOW,
            tz=UTC,
        )
        result = await orchestrator.ask(case.question)
        payload = decision_payload(journal, result.request_id)
    outcome = _outcome(case, "offline", result, payload, recorder, log, reader)
    return _result(outcome, result, run)


def live_config(root: Path) -> Config:
    return load_config(Path(os.environ.get(CONFIG_ENV) or root / "config"))


async def _live(case: Case, root: Path, run: str) -> CaseResult:
    config = live_config(root)
    journal = AuditJournal(default_journal_path(root))
    router = ModelRouter(config)
    log, recorder = WebLog(), Recorder()
    reader = FixtureReader(case, log, root)
    orchestrator = Orchestrator(
        config,
        project_root=root,
        journal=journal,
        router=router,
        open_toolbox=fixture_toolbox(case, log, root),
        pseudonymiser=lambda: presidio(config),
        callbacks=(recorder,),
    )
    result = await orchestrator.ask(case.question)
    payload = decision_payload(journal, result.request_id)
    outcome = _outcome(case, "live", result, payload, recorder, log, reader)
    judgement = None
    threshold = Decimal(str(config.evals.thresholds.generaliste_golden_min_score))
    if case.suite == "golden" and not case.expect.pii:
        judgement = await judge(
            case,
            outcome.markdown,
            _pages_read(log, reader),
            config=config,
            router=router,
            journal=journal,
            now=datetime.now().astimezone(),
            root=root,
        )
    return _result(outcome, result, run, judgement, threshold)


def _error(case: Case, mode: Mode, run: str, exc: Exception) -> CaseResult:
    message = f"{type(exc).__name__} : {exc}"[:MAX_ERROR_CHARS]
    return CaseResult(
        case.id, case.suite, case.group, mode, run, passed=False, score=0.0, error=message
    )


async def run_case(
    case: Case, mode: Mode, *, root: Path = REPO_ROOT, run: str = MANUAL_RUN
) -> CaseResult:
    """Runs one case; an exception fails the case, never the suite."""
    try:
        if mode == "offline":
            return await _offline(case, root, run)
        return await _live(case, root, run)
    except Exception as exc:
        return _error(case, mode, run, exc)
