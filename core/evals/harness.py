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
from core.committee.cards import load_committee
from core.committee.engine import CommitteeSpec
from core.config import load_config
from core.config.loader import Config, PaperRiskLimits
from core.evals.cases import REPO_ROOT, Case, Suite
from core.evals.checks import Check, Mode, Outcome, r5_breaches, run_checks, sourcing_ok
from core.evals.judge import Judgement, golden_threshold, judge
from core.evals.offline import (
    FINANCE_NOW,
    FIXTURE_NOW,
    FinanceLog,
    FixtureReader,
    Pilot,
    Recorder,
    WebLog,
    case_store,
    code_toolboxes,
    finance_toolboxes,
    fixture_toolbox,
    offline_config,
    presidio,
    research_toolboxes,
    scripted_router,
    uses_finance,
)
from core.evals.paper import paper_checks, run_paper
from core.learning.errors import journal_errors, judge_error
from core.models.router import ModelRouter
from core.orchestrator.graph import Orchestrator, RunResult, committee_file
from core.orchestrator.packs import PACKS_DIR
from core.orchestrator.runtime import WEB_PLUGIN
from core.policy.engine import KILL_SWITCH_FILE
from core.research.engine import WITHDRAWN
from core.verification.citations import citation_numbers
from plugins.finance_committee.agent import FEATURE, PACK
from plugins.finance_committee.limits import CHECKED, paper_limit_checks

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


def role_entries(journal: AuditJournal, request_id: str) -> tuple[dict[str, Any], ...]:
    """The committee entries the request wrote to the journal, one DECISION entry per role (D19):
    member, kind, round, validity and number of answers (2 after a repair)."""
    if not journal.path.exists():
        return ()
    roles: list[dict[str, Any]] = []
    for line in journal.path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("event") != "DECISION" or entry.get("request_id") != request_id:
            continue
        role = journal.read_payload(entry["payload_ref"]).get("committee") or {}
        if "member" in role:
            roles.append(role)
    return tuple(roles)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def committee_texts(root: Path, payload: dict[str, Any]) -> tuple[str, ...]:
    """Every text of the valid outputs the session file keeps, as ``cerveau committee show``
    shows them: findings, arguments, decision and controller report, model-written (R5)."""
    session = payload.get("committee") or {}
    record_id, pack = session.get("committee_record_id"), session.get("pack")
    if not record_id or not pack:
        return ()
    path = committee_file(root, pack, record_id)
    if not path.exists():
        return ()
    roles = json.loads(path.read_text(encoding="utf-8")).get("roles", [])
    return tuple(text for role in roles for text in _strings(role.get("output")))


def paper_limits(config: Config, case: Case) -> PaperRiskLimits:
    """The paper limits of the run: the configuration's, or the case's values over a copy of
    them (never the file, which only Lucas changes)."""
    given = case.offline.paper_limits
    if given is None:
        return config.risk_limits_paper
    return PaperRiskLimits.model_validate(config.risk_limits_paper.model_dump() | dict(given))


def unknown_limits(limits: PaperRiskLimits) -> tuple[str, ...]:
    """The limits the committee checks that are still a marker (A_DEFINIR, A_VERIFIER)."""
    return tuple(name for name in CHECKED if isinstance(getattr(limits, name), str))


def paper_committee(limits: PaperRiskLimits) -> CommitteeSpec:
    """The finance committee, checked against ``limits`` instead of the configuration's."""
    return load_committee(
        PACKS_DIR / PACK, pack=PACK, feature=FEATURE, limit_checks=paper_limit_checks(limits)
    )


def cites_a_source(outcome: Outcome) -> bool:
    """The synthesis cites a source of the list (live: an answer the judge finds factual)."""
    numbers = {source.number for source in outcome.answer.sources}
    return bool(numbers & set(citation_numbers(outcome.answer.synthese)))


def _pages_read(log: WebLog, reader: FixtureReader) -> list[tuple[str, str]]:
    pages = [reader.page(url) for url in dict.fromkeys(log.reads)]
    return [(page.url, page.text) for page in pages if page is not None]


def _abstracts_read(case: Case, log: WebLog) -> list[tuple[str, str]]:
    """The abstracts a scholarly search could hand the reader: never a withdrawn record's."""
    if not log.scholar:
        return []
    return [
        (record.url, record.abstract)
        for record in case.records
        if record.abstract and not WITHDRAWN.intersection(record.updated_by)
    ]


def _computed(finance: FinanceLog) -> list[tuple[str, str]]:
    """What the finance tools computed, as the judge reads it: figures, warnings, limits."""
    references = []
    for number, (tool, result) in enumerate(finance.results(), start=1):
        lines = [f"{figure.id} : {figure.display}" for figure in finance.figures(tool, result)]
        lines += [f"avertissement : {warning}" for warning in result.get("warnings") or ()]
        lines += [
            f"indisponible : {item.get('reason', '')}" for item in result.get("unavailable") or ()
        ]
        references.append((f"outil:{tool}#{number}", "\n".join(lines) or "(aucun chiffre)"))
    return references


def _outcome(
    case: Case,
    mode: Mode,
    result: RunResult,
    payload: dict[str, Any],
    recorder: Recorder,
    log: WebLog,
    reader: FixtureReader,
    refused: tuple[str, ...] = (),
    *,
    roles: tuple[dict[str, Any], ...] = (),
    texts: tuple[str, ...] = (),
    unknown: tuple[str, ...] = (),
) -> Outcome:
    hits = [f"{hit.title} {hit.snippet}" for hit in case.search_hits()] if log.queries else []
    titles = [record.title for record in case.records] if log.scholar else []
    read = [*_pages_read(log, reader), *_abstracts_read(case, log)]
    return Outcome(
        case=case,
        mode=mode,
        answer=result.answer,
        payload=payload,
        sent=tuple(recorder.sent),
        executed=tuple(log.arguments()),
        requested=tuple(recorder.requested),
        read_texts=tuple(text for _url, text in read),
        search_texts=(*hits, *titles),
        now=result.now,
        tool_calls=result.tool_calls,
        tool_outputs=result.tool_outputs,
        refused_imports=refused,
        role_entries=len(roles),
        repaired_roles=tuple(r["member"] for r in roles if r.get("attempts", 1) > 1),
        committee_texts=texts,
        unknown_limits=unknown,
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
    log, recorder, finance = WebLog(), Recorder(), FinanceLog()
    reader = FixtureReader(case, log, root)
    pilot = Pilot(case, reader, finance)
    # A run on the reference store is dated when the store is read (R10, ADR-023).
    now = FINANCE_NOW if uses_finance(case) else FIXTURE_NOW
    with tempfile.TemporaryDirectory(prefix="cerveau-eval-", ignore_cleanup_errors=True) as tmp:
        home = Path(tmp)  # no plugin directory, a journal of its own
        journal = AuditJournal(home / "audit" / "journal.jsonl")
        if case.offline.kill_switch:  # R4: the switch of this temporary home only
            kill = home / KILL_SWITCH_FILE
            kill.parent.mkdir(parents=True)
            kill.write_text("éval R4\n", encoding="utf-8")
        data = home / "finance"
        data.mkdir()
        store, refused = case_store(case, data)
        limits = paper_limits(config, case)
        given = case.offline.paper_limits is not None
        orchestrator = Orchestrator(
            config,
            project_root=home,
            journal=journal,
            router=scripted_router(config, pilot),
            toolboxes={
                WEB_PLUGIN: fixture_toolbox(case, log, root),
                **research_toolboxes(case, log),
                **finance_toolboxes(finance, root / "config", store),
                **code_toolboxes(case, home),
            },
            pseudonymiser=lambda: presidio(config),
            callbacks=(recorder,),
            clock=lambda: now,
            tz=UTC,
            committees={PACK: paper_committee(limits)} if given else None,
        )
        result = await orchestrator.ask(case.question, research=case.approfondi)
        payload = decision_payload(journal, result.request_id)
        roles = role_entries(journal, result.request_id)
        texts = committee_texts(home, payload)
    outcome = _outcome(
        case,
        "offline",
        result,
        payload,
        recorder,
        log,
        reader,
        refused,
        roles=roles,
        texts=texts,
        unknown=unknown_limits(limits),
    )
    return _result(outcome, result, run)


def live_config_dir(root: Path) -> Path:
    return Path(os.environ.get(CONFIG_ENV) or root / "config")


def live_config(root: Path) -> Config:
    return load_config(live_config_dir(root))


async def _live(case: Case, root: Path, run: str) -> CaseResult:
    config = live_config(root)
    journal = AuditJournal(default_journal_path(root))
    router = ModelRouter(config)
    log, recorder, finance = WebLog(), Recorder(), FinanceLog()
    reader = FixtureReader(case, log, root)
    # Live, the request keeps the real clock (budgets of the day); the finance tools still read
    # the reference store at its own date, so a finance question names its dates (ADR-023).
    with tempfile.TemporaryDirectory(prefix="cerveau-eval-", ignore_cleanup_errors=True) as tmp:
        store, refused = case_store(case, Path(tmp))
        orchestrator = Orchestrator(
            config,
            project_root=root,
            journal=journal,
            router=router,
            toolboxes={
                WEB_PLUGIN: fixture_toolbox(case, log, root),
                **research_toolboxes(case, log),
                **finance_toolboxes(finance, live_config_dir(root), store),
                **code_toolboxes(case, Path(tmp)),
            },
            pseudonymiser=lambda: presidio(config),
            callbacks=(recorder,),
        )
        result = await orchestrator.ask(case.question, research=case.approfondi)
    payload = decision_payload(journal, result.request_id)
    roles = role_entries(journal, result.request_id)
    texts = committee_texts(root, payload)
    outcome = _outcome(
        case,
        "live",
        result,
        payload,
        recorder,
        log,
        reader,
        refused,
        roles=roles,
        texts=texts,
        unknown=unknown_limits(config.risk_limits_paper),
    )
    judgement = None
    pack = case.group if case.suite == "golden" else "generaliste"
    threshold = golden_threshold(config, pack)
    if case.suite == "golden" and not case.expect.pii:
        judgement = await judge(
            case,
            outcome.markdown,
            [*_pages_read(log, reader), *_abstracts_read(case, log), *_computed(finance)],
            config=config,
            router=router,
            journal=journal,
            now=datetime.now().astimezone(),
            root=root,
            pack=pack,
        )
        grades = judgement.as_dict()["grades"]
        low = judge_error(case.id, judgement.score, threshold, grades)
        journal_errors(
            journal,
            [low] if low is not None else [],
            actor="orchestrator",
            request_id=result.request_id,
            versions={"config": config.digest},
        )
    return _result(outcome, result, run, judgement, threshold)


def _error(case: Case, mode: Mode, run: str, exc: Exception) -> CaseResult:
    message = f"{type(exc).__name__} : {exc}"[:MAX_ERROR_CHARS]
    return CaseResult(
        case.id, case.suite, case.group, mode, run, passed=False, score=0.0, error=message
    )


def _paper(case: Case, mode: Mode, root: Path, run: str) -> CaseResult:
    paper = run_paper(case, root)
    checks = tuple(paper_checks(case, paper))
    return CaseResult(
        case.id,
        case.suite,
        case.group,
        mode,
        run,
        passed=all(check.passed for check in checks),
        score=_score(checks),
        checks=checks,
        status=paper.status,
        elapsed_s=paper.elapsed_s,
        markdown=paper.markdown,
    )


async def run_case(
    case: Case, mode: Mode, *, root: Path = REPO_ROOT, run: str = MANUAL_RUN
) -> CaseResult:
    """Runs one case; an exception fails the case, never the suite."""
    try:
        if case.paper is not None:  # the paper loop, without a model, the same in both modes
            return _paper(case, mode, root, run)
        if mode == "offline":
            return await _offline(case, root, run)
        return await _live(case, root, run)
    except Exception as exc:
        return _error(case, mode, run, exc)
