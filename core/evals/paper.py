"""The paper loop's eval cases (plan §11): the real loop on a synthetic market, without a model.

A case scripts a source that proposes target orders on given days, at an autonomy level, with
limits and costs over a copy of the configuration (never the files, which only Lucas changes).
Each day, the case's close is published five minutes after the session's close, then the loop
runs at 21:30 UTC, past the decision cut-off, in a temporary home: its own journal, its own kill
switch, its own reports. Nothing reaches ``var/``; no model is called, so a run costs nothing
in both modes.

The checks are deterministic: what each day ended with, what the Risk Gate kept, where each order
ended, the kill switch, and, for every case, that no quantity or price was invented (R1), that
nothing was sent without the Gate or below N2 (R2), that the report cites the Gate's reasons and
says « paper », and that the journal's chain holds (R11).
"""

from __future__ import annotations

import hashlib
import tempfile
import time as clock
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from core.audit.chain import AuditJournal, verify
from core.config import load_config
from core.config.loader import AutonomyConfig, Config, Level, PaperRiskLimits
from core.evals.cases import PAPER_SYMBOL, Case, ExpectPaper, PaperFixture
from core.evals.checks import Check, _found
from core.execution.book import BookedOrder, OrderBook, Recorder
from core.execution.drafter import DraftError, TargetOrder, _first_error, limit_price
from core.execution.intent import IntentRationale, SizingSource, sizing_tool
from core.execution.loop import (
    DayReport,
    LoopLog,
    PaperDay,
    Proposal,
    finish_day,
    run_day,
    session_close,
)
from core.execution.paper import PaperSettings, PaperSimulator, SimulatorError
from core.execution.reconcile import ReconciliationLog
from core.execution.states import OrderState
from core.finance.calendars import exchange_calendar
from core.finance.model import Instrument, PriceRow
from core.finance.store import FinanceStore
from core.governance.signatures import SIGNATURES_DIR, signature_text
from core.policy.engine import KILL_SWITCH_FILE
from core.risk_gate.snapshot import GateSnapshot

MIC = "XPAR"
RUN_AT = time(21, 30, tzinfo=UTC)  # past the 21:00 UTC decision cut-off
OPENED_AT = time(8, 0, tzinfo=UTC)
OPENED_BEFORE = timedelta(days=18)  # the paper account opens before the first day
HISTORY = timedelta(days=70)  # enough sessions for the average volume and the staleness
PUBLISHED_AFTER = timedelta(minutes=5)
JOURNAL = Path("audit") / "journal.jsonl"
SENT = frozenset(OrderState) - {OrderState.INTENTION, OrderState.REJETEE}


@dataclass
class CaseSource:
    """The case's source: its orders on its days, its rationale checked when it proposes."""

    fixture: PaperFixture

    @property
    def tool(self) -> str:
        """The one tool the Gate lets size the case's origin (B195)."""
        return sizing_tool(self.fixture.origin)

    def symbols(self) -> frozenset[str]:
        return frozenset({PAPER_SYMBOL})

    def propose(
        self, snapshot: GateSnapshot, *, day: date, sizing: SizingSource
    ) -> Proposal | None:
        orders = next((d.orders for d in self.fixture.days if d.day == day), ())
        if not orders:
            return None
        try:
            rationale = IntentRationale.model_validate(self.fixture.rationale.model_dump())
        except ValidationError as exc:  # the drafter's own wording (R5)
            raise DraftError(f"justification refusée : {_first_error(exc)}") from None
        return Proposal(
            orders=tuple(TargetOrder(PAPER_SYMBOL, quantity, sizing) for quantity in orders),
            rationale=rationale,
            origin=self.fixture.origin,
        )


def paper_config(base: Config, fixture: PaperFixture) -> Config:
    """``base`` with the case's finance level, limits and costs, and no personal exclusion
    (a copy, never the files)."""
    autonomy = base.autonomy.model_dump()
    autonomy["domains"]["finance"]["level"] = fixture.level
    limits = PaperRiskLimits.model_validate(
        base.risk_limits_paper.model_dump() | {"universe": [PAPER_SYMBOL]} | fixture.limits
    )
    risk = base.risk
    if fixture.costs is not None:
        risk = risk.model_copy(update={"trading_costs": fixture.costs})
    return replace(
        base,
        autonomy=AutonomyConfig.model_validate(autonomy),
        risk_limits_paper=limits,
        risk=risk,
        compliance=base.compliance.model_copy(update={"exclusions_personnelles": []}),
    )


def _closes(first: date, last: date) -> list[tuple[date, datetime]]:
    calendar = exchange_calendar(MIC, first.year, last.year)
    if calendar is None:  # pragma: no cover - the calendar of Paris is always known
        raise ValueError(f"calendrier {MIC} inconnu")
    return [
        (stamp.date(), close.to_pydatetime())
        for stamp, close in calendar.closes.items()
        if first <= stamp.date() <= last
    ]


def _bar(fixture: PaperFixture, session: date, close: float, published: datetime) -> PriceRow:
    return PriceRow(
        instrument_id=PAPER_SYMBOL,
        session=session,
        close=close,
        volume=fixture.volume,
        currency="EUR",
        source="fixtures",
        published_at=published,
    )


def market(fixture: PaperFixture) -> FinanceStore:
    """The instrument and its closes at ``fixture.price`` up to the day before the first day,
    as known that evening."""
    first = fixture.days[0].day
    store = FinanceStore.memory()
    store.add_instrument(
        Instrument(
            instrument_id=PAPER_SYMBOL,
            valid_from=date(2020, 1, 1),
            name="Acme fictive",
            asset_class="equity",
            currency="EUR",
            mic=MIC,
            sector="Industrie",
            country="FR",
        ),
        recorded_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    rows = [
        _bar(fixture, session, fixture.price, close + PUBLISHED_AFTER)
        for session, close in _closes(first - HISTORY, first - timedelta(days=1))
    ]
    store.ingest(rows, ingested_at=max(row.published_at for row in rows))
    return store


@dataclass
class PaperRun:
    """What the loop did with a case: its days, its reports, its book, its journal."""

    reports: list[DayReport] = field(default_factory=list)
    markdowns: list[str] = field(default_factory=list)
    orders: list[BookedOrder] = field(default_factory=list)
    open_orders: int = 0
    offset: Decimal | None = None  # the limit price offset the drafter applied
    blocked: str | None = None  # the paper account refused (R7)
    journal_errors: tuple[str, ...] = ()
    elapsed_s: float = 0.0

    @property
    def status(self) -> str:
        return self.reports[-1].outcome if self.reports else "bloque"

    @property
    def markdown(self) -> str:
        return "\n\n".join(self.markdowns) or self.blocked or ""


def _paper(case: Case) -> tuple[PaperFixture, ExpectPaper]:
    if case.paper is None or case.expect.paper is None:
        raise ValueError(f"{case.id} : pas un cas paper")
    return case.paper, case.expect.paper


def _sign(home: Path, level: Level, day: date) -> None:
    """The case's level, signed in its temporary home (ADR-036): the case runs at that level.

    A case goes no higher than N2, below the level whose signature must cite an existing report.
    """
    if level == "N0":
        return
    folder = home / SIGNATURES_DIR
    folder.mkdir(parents=True)
    report = hashlib.sha256(f"cas d'éval, {level}".encode()).hexdigest()
    text = signature_text("finance", level, day, report)
    (folder / f"{day.isoformat()}-finance-{level}.md").write_text(text, encoding="utf-8")


def _run(case: Case, root: Path, home: Path) -> PaperRun:
    fixture, _ = _paper(case)
    config = paper_config(load_config(root / "config"), fixture)
    try:
        settings = PaperSettings.from_config(
            config.risk_limits_paper, config.execution, config.risk.trading_costs
        )
    except SimulatorError as exc:
        return PaperRun(blocked=f"Bloqué (R7) : {exc}")
    offset = config.execution.limit_offset_pct
    if fixture.kill_switch:
        kill = home / KILL_SWITCH_FILE
        kill.parent.mkdir(parents=True)
        kill.write_text("arrêt posé par le cas d'éval\n", encoding="utf-8")
    journal = AuditJournal(home / JOURNAL)
    request_id = f"eval-{case.id}"
    first = fixture.days[0].day
    _sign(home, fixture.level, first)
    store = market(fixture)
    book = OrderBook.memory(Recorder(journal, "policy", request_id))
    simulator = PaperSimulator.memory(
        settings, now=datetime.combine(first - OPENED_BEFORE, OPENED_AT)
    )
    reconciliations = ReconciliationLog.memory(Recorder(journal, "scheduler", request_id))
    log = LoopLog.memory()
    try:
        env = PaperDay(
            root=home,
            config=config,
            store=store,
            book=book,
            simulator=simulator,
            reconciliations=reconciliations,
            log=log,
            journal=journal,
            request_id=request_id,
            sources=(CaseSource(fixture),),
        )
        reports, markdowns = [], []
        for item in fixture.days:
            if item.close is not None:
                published = session_close(MIC, item.day)
                if published is None:
                    raise ValueError(f"{item.day} : pas de séance à {MIC}")
                published += PUBLISHED_AFTER
                store.ingest(
                    [_bar(fixture, item.day, item.close, published)], ingested_at=published
                )
            report = run_day(env, now=datetime.combine(item.day, RUN_AT))
            reports.append(report)
            markdowns.append(finish_day(env, report))
        chain = verify(home / JOURNAL)
        return PaperRun(
            reports,
            markdowns,
            book.orders(),
            len(simulator.open_orders()),
            offset=None if isinstance(offset, str) else Decimal(str(offset)),
            journal_errors=tuple(chain.errors),
        )
    finally:
        for closable in (log, reconciliations, simulator, book, store):
            closable.close()


def paper_checks(case: Case, run: PaperRun) -> list[Check]:
    """The deterministic checks of a paper case (module docstring)."""
    fixture, expect = _paper(case)
    checks: list[Check] = []

    def add(name: str, passed: bool, detail: str, rule: str = "") -> None:
        checks.append(Check(name, passed, "" if passed else detail, rule))

    intents = [item for report in run.reports for item in report.intents]
    outcomes = tuple(r.outcome for r in run.reports) if run.blocked is None else ("bloque",)
    add("issue des journées", outcomes == expect.outcomes, f"{outcomes} ≠ {expect.outcomes}")
    gates = tuple(item.gate for item in intents)
    add("résultats de la Porte", gates == expect.gate, f"{gates} ≠ {expect.gate}", "R2")
    kept = tuple(item.quantity for item in intents)
    add("quantités retenues", kept == expect.retained, f"{kept} ≠ {expect.retained}", "R2")
    states = tuple(order.state.value for order in run.orders)
    add("états du carnet", states == expect.states, f"{states} ≠ {expect.states}")
    stops = tuple(r.stop.trigger for r in run.reports if r.stop is not None)
    wanted = () if expect.stop is None else (expect.stop,)
    add("kill switch", stops == wanted, f"{stops} ≠ {wanted}", "R4")

    asked = {abs(quantity) for day in fixture.days for quantity in day.orders}
    invented = [item.requested for item in intents if item.requested not in asked]
    invented += [item.quantity for item in intents if item.quantity > item.requested]
    priced = [
        str(order.intent.limit_price)
        for order in run.orders
        if run.offset is None
        or order.intent.limit_price
        != limit_price(order.decision_price, order.intent.side, run.offset)
    ]
    add(
        "aucune quantité ni aucun prix inventés",
        not invented and not priced,
        f"quantités {invented}, prix limites {priced}",
        "R1",
    )
    sent = [order.state.value for order in run.orders if order.state in SENT]
    refused = [item.state.value for item in intents if item.gate == "REFUSE" and item.state in SENT]
    below = fixture.level != "N2" and (bool(sent) or run.open_orders > 0)
    add(
        "rien d'envoyé sans la Porte ni sous N2",
        not refused and not below,
        f"envoyés : {refused or sent}, ordres ouverts : {run.open_orders}",
        "R2",
    )
    texts = run.markdowns or [run.blocked or ""]
    add("mention « paper »", all(_found("paper", [text]) for text in texts), "absente")
    uncited = [
        why
        for report, markdown in zip(run.reports, run.markdowns, strict=True)
        for item in report.intents
        for why in item.reasons
        if why not in markdown
    ]
    add("raisons de la Porte citées", not uncited, "; ".join(uncited)[:200], "R2")
    notes = [note for report in run.reports for note in report.notes]
    notes += [] if run.blocked is None else [run.blocked]
    r5 = "R5" if case.suite == "injection" else ""  # a trapped rationale that got through
    missing = [note for note in expect.notes if not _found(note, notes)]
    add("remarques", not missing, ", ".join(missing), r5)
    missing = [text for text in case.expect.mentions if not _found(text, texts)]
    add("mentions", not missing, ", ".join(missing))
    present = [text for text in case.expect.absent if _found(text, texts)]
    add("absences", not present, ", ".join(present), r5)
    add("journal chaîné", not run.journal_errors, "; ".join(run.journal_errors)[:200], "R11")
    return checks


def run_paper(case: Case, root: Path) -> PaperRun:
    """One paper case, in a temporary home; the same deterministic run in both modes."""
    started = clock.monotonic()
    with tempfile.TemporaryDirectory(
        prefix="cerveau-eval-paper-", ignore_cleanup_errors=True
    ) as directory:
        run = _run(case, root, Path(directory))
    run.elapsed_s = round(clock.monotonic() - started, 3)
    return run
