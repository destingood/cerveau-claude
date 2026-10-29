"""The N2 → N3 and N3 → N4 promotion reports (ADR-040, B181, ADR-067): criteria, verdict and
signature."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from typer.testing import CliRunner

from core.audit import AuditJournal, default_journal_path
from core.config import BlockedFeatureError
from core.evals.promotion import Check, PromotionCheck
from core.execution.book import BookedOrder, OrderBook, default_book_path
from core.execution.loop import LoopLog, Valuation, default_loop_path
from core.execution.states import OrderState
from core.finance.research import engine
from core.finance.research.execution import Costs
from core.finance.store import FinanceStore, default_store_path
from core.governance.demotion import demotions_path
from core.governance.promotion_report import (
    Criterion,
    Decisions,
    Gap,
    Incident,
    PromotionReport,
    PromotionReportError,
    StrategyBacktest,
    Unavailable,
    agreement_rate,
    approvals_count,
    build_report,
    current_level,
    demotions_criterion,
    evals_criterion,
    execution_incidents,
    gap_criterion,
    incidents,
    lucas_decisions,
    paper_backtest_gap,
    paper_decisions,
    paper_drawdown,
    paper_strategy,
    paper_weeks,
    render,
    strategy_backtest,
    write_report,
)
from core.governance.signatures import (
    PROMOTION_DIR,
    REPORT_PASSED,
    SIGNATURES_DIR,
    effective_level,
    read_signatures,
    signature_text,
)
from interfaces.cli.main import app
from tests.execution_cases import DECISION_PRICE, MemoryJournal, make_fill, make_intent, recorder
from tests.signing import sign
from tests.test_execution_loop import (
    BASE,
    MONDAY,
    THURSDAY,
    TUESDAY,
    WEDNESDAY,
    config,
    ingest,
    market,
    run_at,
)
from tests.test_execution_sources import promoted

AT = run_at(THURSDAY)
STRATEGY = {"kind": "strategy", "id": "croisement_mm"}
COSTS = Costs("test", commission=0.001, minimum=2.0, slippage=0.0005)
PAPER = {MONDAY: "10000.00", TUESDAY: "10000.00", WEDNESDAY: "10050.00", THURSDAY: "10100.00"}


@pytest.fixture(autouse=True)
def _default_journal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every journal of these tests is the default one of their temporary root."""
    monkeypatch.delenv("CERVEAU_AUDIT_JOURNAL", raising=False)


def strategy_intent(n: int) -> Any:
    return make_intent(n, origin=STRATEGY, committee_record_id=None)


def booked(intent: Any, state: OrderState, *fills: Any) -> BookedOrder:
    return BookedOrder(intent, DECISION_PRICE, state, tuple(fills))


def valued(day: date, equity: str, positions: Mapping[str, int] | None = None) -> Valuation:
    return Valuation(day, Decimal(equity), Decimal(equity), dict(positions or {}), run_at(day))


# The criteria ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "status"), [("N1", "non_atteint"), ("N2", "atteint"), ("N3", "atteint")]
)
def test_the_promotion_climbs_from_n2_in_force(level: Any, status: str) -> None:
    assert current_level(level, required="N2").status == status


def _weekdays(first: date, last: date) -> list[date]:
    days = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    return [day for day in days if day.weekday() < 5]


@pytest.mark.parametrize(
    ("days", "weeks"),
    [
        ([], 0),
        ([date(2026, 10, 23), date(2026, 10, 26)], 1),  # a Friday and the next Monday
        ([date(2026, 10, 5), date(2026, 10, 19)], 2),  # three weeks begun, two with a day
        (_weekdays(date(2026, 7, 27), date(2026, 10, 23)), 13),
    ],
)
def test_the_paper_weeks_count_neither_a_gap_nor_a_weekend(days: list[date], weeks: int) -> None:
    criterion = paper_weeks(days, 13)
    assert criterion.value == str(weeks)
    assert criterion.status == ("atteint" if weeks >= 13 else "non_atteint")


def test_the_paper_weeks_need_a_threshold_and_the_loop() -> None:
    days = _weekdays(date(2026, 7, 27), date(2026, 10, 23))
    unknown = paper_weeks(days, "A_DEFINIR")
    assert unknown.status == "non_evaluable"
    assert "A_DEFINIR" in unknown.threshold
    unread = paper_weeks(Unavailable("boucle paper illisible"), 13)
    assert (unread.value, unread.status) == ("boucle paper illisible", "non_evaluable")


def _equities(*values: int) -> list[Valuation]:
    return [valued(MONDAY + timedelta(days=n), f"{value}.00") for n, value in enumerate(values)]


def test_the_drawdown_is_the_deepest_fall_from_a_running_peak() -> None:
    curve = _equities(10000, 10500, 9450, 10600)
    reached = paper_drawdown(curve, 10)
    assert (reached.value, reached.status) == ("10.00 %", "atteint")
    assert "Pic de 10500.00 €" in reached.details[0]
    assert paper_drawdown(curve, 9.99).status == "non_atteint"
    later = paper_drawdown(_equities(100, 90, 200, 170), 20)  # 10 % then 15 % from a new peak
    assert later.value == "15.00 %"


def test_a_drawdown_without_a_value_or_a_threshold_is_not_evaluable() -> None:
    assert paper_drawdown([], 10).value == "aucune valorisation"
    assert paper_drawdown([], 10).status == "non_evaluable"
    assert paper_drawdown(_equities(100, 90), "A_DEFINIR").status == "non_evaluable"
    flat = paper_drawdown(_equities(100, 100), 10)
    assert (flat.value, flat.status, flat.details[0]) == (
        "0.00 %",
        "atteint",
        "Aucune baisse depuis un pic.",
    )
    empty = paper_drawdown(_equities(0, 0), 10)
    assert (empty.value, empty.status) == ("valeur du compte nulle", "non_evaluable")


def test_every_booked_intent_is_a_decision_whatever_its_fate() -> None:
    first, second, third = strategy_intent(1), strategy_intent(2), make_intent(3)
    orders = [
        booked(first, OrderState.EXECUTEE, make_fill(first, 1, first.quantity)),
        booked(second, OrderState.REJETEE),
        booked(third, OrderState.INTENTION),
    ]
    reached = paper_decisions(orders, 3)
    assert (reached.value, reached.status) == ("3", "atteint")
    assert reached.details[1] == "États : EXECUTEE 1, INTENTION 1, REJETEE 1"
    assert "strategy croisement_mm : 2" in reached.details[2]
    assert paper_decisions(orders, 4).status == "non_atteint"
    assert paper_decisions(orders, "A_DEFINIR").status == "non_evaluable"
    assert paper_decisions(Unavailable("carnet illisible"), 3).status == "non_evaluable"


def _kill(journal: AuditJournal, trigger: str, reason: str, event: str = "KILL") -> None:
    payload = {"kill_switch": "declenchement", "trigger": trigger, "reason": reason}
    journal.append(actor="policy", event=event, payload=payload)


def test_only_the_stops_for_an_execution_incident_count(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path / "journal.jsonl")
    assert execution_incidents(journal) == []
    _kill(journal, "incident_execution", "exécution d'un ordre inconnu")
    _kill(journal, "commande", "/kill")
    _kill(journal, "drawdown", "drawdown au-delà de la limite")
    _kill(journal, "incident_execution", "copie d'un arrêt", event="DECISION")
    found = execution_incidents(journal)
    assert isinstance(found, list)
    assert [incident.reason for incident in found] == ["exécution d'un ordre inconnu"]
    assert incidents(found, 0).status == "non_atteint"
    assert incidents([], 0).status == "atteint"


def test_an_altered_journal_counts_no_incident(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path / "journal.jsonl")
    _kill(journal, "commande", "/kill")
    text = journal.path.read_text(encoding="utf-8")
    journal.path.write_text(text.replace('"policy"', '"lucas"'), encoding="utf-8")
    found = execution_incidents(journal)
    assert isinstance(found, Unavailable)
    assert "cerveau audit verify" in found.reason
    assert incidents(found, 0).status == "non_evaluable"


def test_a_payload_that_cannot_be_read_counts_no_incident(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = AuditJournal(tmp_path / "journal.jsonl")
    _kill(journal, "incident_execution", "ordre inconnu")

    def unreadable(self: AuditJournal, payload_ref: str) -> Any:
        raise PermissionError(payload_ref)

    monkeypatch.setattr(AuditJournal, "read_payload", unreadable)
    assert execution_incidents(journal) == Unavailable(
        "journal d'audit illisible (PermissionError)"
    )


def test_the_detail_lists_ten_incidents_and_counts_them_all() -> None:
    found = [Incident(f"2026-10-{day:02d}", "ordre inconnu") for day in range(1, 13)]
    criterion = incidents(found, 0)
    assert criterion.value == "12"
    assert len(criterion.details) == 11
    assert criterion.details[-1] == "… et 2 autre(s)."


# The gap between the paper account and the backtest ------------------------------------------


def test_the_paper_account_has_a_backtest_only_with_one_strategy() -> None:
    first, second = strategy_intent(1), strategy_intent(2)
    other = make_intent(
        3, origin={"kind": "strategy", "id": "momentum_12_1"}, committee_record_id=None
    )
    committee = make_intent(4)
    assert isinstance(paper_strategy([]), Unavailable)
    assert isinstance(paper_strategy([booked(committee, OrderState.INTENTION)]), Unavailable)
    mixed = [booked(first, OrderState.REJETEE), booked(other, OrderState.REJETEE)]
    assert "plusieurs origines" in str(paper_strategy(mixed))
    alone = [booked(first, OrderState.REJETEE), booked(second, OrderState.INTENTION)]
    assert paper_strategy(alone) == "croisement_mm"


def backtest(*values: float, start: date = MONDAY) -> StrategyBacktest:
    index = pd.DatetimeIndex([pd.Timestamp(start + timedelta(days=n)) for n in range(len(values))])
    result = engine.BacktestResult(
        strategy="croisement_mm",
        params={"long": 50, "short": 5},
        costs=COSTS,
        initial_cash=values[0],
        values=pd.Series(values, index=index),
        cash=pd.Series(values, index=index),
        positions=pd.DataFrame(index=index),
        exposure=pd.Series(0.0, index=index),
        trades=(),
        credits=(),
        cuts=(),
    )
    return StrategyBacktest("croisement_mm", {"long": 50, "short": 5}, COSTS, result)


def test_the_gap_compares_the_returns_over_the_common_sessions() -> None:
    first, second = strategy_intent(1), strategy_intent(2)
    orders = [
        booked(first, OrderState.EXECUTEE, make_fill(first, 1, first.quantity)),
        booked(second, OrderState.REJETEE),
    ]
    paper = [valued(MONDAY, "10000"), valued(TUESDAY, "10050"), valued(WEDNESDAY, "10150")]
    gap = paper_backtest_gap(paper, orders, backtest(10000.0, 10100.0, 10200.0, 10300.0))
    assert isinstance(gap, Gap)
    assert (gap.first, gap.last, gap.sessions) == (MONDAY, WEDNESDAY, 3)
    assert gap.points == pytest.approx(-0.5)
    assert (gap.paper_fills, gap.paper_fees_eur, gap.unfilled) == (1, Decimal("1.50"), 1)
    assert gap.backtest_slippage_bps == pytest.approx(5.0)
    criterion = gap_criterion(gap)
    assert (criterion.value, criterion.status) == ("-0.50 point(s)", "atteint")
    assert '{"long":50,"short":5}' in criterion.details[0]
    assert "Ordres paper terminés sans exécution (refusés, rejetés ou annulés) : 1." in (
        criterion.details
    )


def test_a_gap_needs_two_common_sessions_and_euros() -> None:
    paper = [valued(MONDAY, "10000"), valued(TUESDAY, "10050")]
    late = paper_backtest_gap(paper, [], backtest(10000.0, 10100.0, start=TUESDAY))
    assert isinstance(late, Unavailable)
    assert gap_criterion(late).status == "non_evaluable"
    dollars = strategy_intent(1).model_copy(
        update={"instrument": strategy_intent(1).instrument.model_copy(update={"currency": "USD"})}
    )
    orders = [booked(dollars, OrderState.EXECUTEE, make_fill(dollars, 1, 10))]
    foreign = paper_backtest_gap(paper, orders, backtest(10000.0, 10100.0))
    assert isinstance(foreign, Unavailable)
    assert "USD" in foreign.reason


def paper_home(
    root: Path,
    equities: Mapping[date, str] = PAPER,
    *,
    held: Mapping[str, int] | None = None,
) -> None:
    """A promoted strategy that ran the paper account from Monday to Thursday: its store, the
    loop's days and valuations, and one order it bought."""
    promoted(root)
    store = market(FinanceStore.open(default_store_path(root)))
    for day in (TUESDAY, WEDNESDAY, THURSDAY):
        ingest(store, day, 100.0)
    store.close()
    with LoopLog.open(default_loop_path(root)) as log:
        for n, (day, equity) in enumerate(equities.items()):
            log.record_valuation(valued(day, equity, held if n == 0 else None))
            log.record_run(day, completed_at=run_at(day), intents=1, report="# journée")
    intent = strategy_intent(1)
    with OrderBook.open(default_book_path(root), recorder=recorder(MemoryJournal())) as book:
        book.record_intent(intent, decision_price=DECISION_PRICE, reason="rédigée")
        book.transition(intent.intent_id, OrderState.VALIDEE, reason="porte de risque")
        book.transition(intent.intent_id, OrderState.ENVOYEE, reason="simulateur")
        book.record_fill(make_fill(intent, 1, intent.quantity))


def test_the_strategy_is_backtested_with_its_approved_configuration(tmp_path: Path) -> None:
    paper_home(tmp_path)
    run = strategy_backtest(
        tmp_path,
        config(),
        "croisement_mm",
        start=MONDAY,
        end=THURSDAY,
        initial_cash=10000.0,
        at=AT,
    )
    assert isinstance(run, StrategyBacktest), run
    assert dict(run.params) == {"long": 50, "short": 5}
    assert [stamp.date() for stamp in run.result.values.index] == [
        MONDAY,
        TUESDAY,
        WEDNESDAY,
        THURSDAY,
    ]


def test_a_backtest_needs_the_costs_and_an_approved_strategy(tmp_path: Path) -> None:
    paper_home(tmp_path)
    window: dict[str, Any] = {"start": MONDAY, "end": THURSDAY, "initial_cash": 1e4, "at": AT}
    no_costs = strategy_backtest(tmp_path, BASE, "croisement_mm", **window)
    assert isinstance(no_costs, Unavailable)
    unknown = strategy_backtest(tmp_path, config(), "momentum_12_1", **window)
    assert isinstance(unknown, Unavailable)
    assert "sans configuration approuvée" in unknown.reason
    absent = strategy_backtest(tmp_path / "ailleurs", config(), "croisement_mm", **window)
    assert isinstance(absent, Unavailable)
    assert absent.reason.startswith("base finance illisible : base finance absente")


def test_a_backtest_that_fails_is_not_a_measure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper_home(tmp_path)

    def failing(*args: Any, **kwargs: Any) -> Any:
        raise engine.BacktestError("historique trop court")

    monkeypatch.setattr(engine, "run", failing)
    run = strategy_backtest(
        tmp_path, config(), "croisement_mm", start=MONDAY, end=THURSDAY, initial_cash=1e4, at=AT
    )
    assert run == Unavailable("backtest de croisement_mm impossible : historique trop court")


# Evals and the verdict ------------------------------------------------------------------------


def test_the_evals_criterion_is_the_rule_n1_to_n2_measured_live(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    passed = PromotionCheck(
        "finance",
        "N2",
        (Check("golden", "≥ 0.9", "0.95", True), Check("red team", "0 fuite", "0 fuite", True)),
    )
    reached = evals_criterion(passed, report)
    assert (reached.value, reached.status) == ("2/2 condition(s)", "atteint")
    failed = PromotionCheck("finance", "N2", (Check("golden", "≥ 0.9", "0.80", False),))
    missed = evals_criterion(failed, report)
    assert (missed.status, missed.details) == (
        "non_atteint",
        ("✗ golden : 0.80 (attendu : ≥ 0.9)",),
    )
    none = evals_criterion(Unavailable("aucun rapport"), None)
    assert (none.status, none.source) == ("non_evaluable", "`check_promotion` sur aucun rapport")


def test_a_blocked_evals_rule_leaves_its_criterion_not_evaluable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def blocked(*args: Any, **kwargs: Any) -> Any:
        raise BlockedFeatureError("promotion N1_to_N2", ["seuil golden A_DEFINIR"])

    monkeypatch.setattr("core.governance.promotion_report.load_report", lambda path: None)
    monkeypatch.setattr("core.governance.promotion_report.check_promotion", blocked)
    evals = tmp_path / "report.json"
    report = build_report(tmp_path, BASE, domain="finance", level="N3", at=AT, evals=evals)
    value, status = _criteria(report)["Golden et red team du domaine"]
    assert status == "non_evaluable"
    assert value.startswith("règle N1_to_N2 bloquée : fonction bloquée")


def _report(*statuses: Any, value: str = "valeur") -> PromotionReport:
    criteria = tuple(
        Criterion(f"Critère {n}", value, "seuil", status, "test")
        for n, status in enumerate(statuses)
    )
    return PromotionReport("finance", "N3", AT, "abc123", criteria)


@pytest.mark.parametrize(
    ("statuses", "verdict"),
    [
        ((), "non_evaluable"),
        (("atteint", "sans_objet"), REPORT_PASSED),
        (("atteint", "non_evaluable"), "non_evaluable"),
        (("non_evaluable", "non_atteint"), "promotion_impossible"),
    ],
)
def test_a_failed_criterion_outranks_an_unknown_one(statuses: Any, verdict: str) -> None:
    assert _report(*statuses).verdict == verdict


# The report from the project's files -----------------------------------------------------------


def _criteria(report: PromotionReport) -> dict[str, tuple[str, str]]:
    return {c.name: (c.value, c.status) for c in report.criteria}


def test_the_report_reads_the_loop_the_book_the_journal_and_the_backtest(tmp_path: Path) -> None:
    paper_home(tmp_path)
    sign(tmp_path, "finance", "N2")
    report = build_report(tmp_path, config(), domain="finance", level="N3", at=AT)
    assert _criteria(report) == {
        "Niveau en vigueur": ("N2", "atteint"),
        "Semaines de paper": ("1", "non_atteint"),
        "Décisions de paper": ("1", "non_atteint"),
        "Drawdown paper": ("0.00 %", "atteint"),
        "Incidents d'exécution": ("0", "atteint"),
        "Écart paper/backtest": ("+1.00 point(s)", "atteint"),
        "Golden et red team du domaine": (
            "aucun rapport d'évals réel fourni (--evals)",
            "non_evaluable",
        ),
        "Éval nocturne": ("aucune éval nocturne n'existe", "sans_objet"),
    }
    assert report.verdict == "promotion_impossible"
    assert report.config_digest == config().digest


def _snapshot(root: Path) -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_the_report_changes_no_file(tmp_path: Path) -> None:
    paper_home(tmp_path)
    before = _snapshot(tmp_path)
    build_report(tmp_path, config(), domain="finance", level="N3", at=AT)
    assert _snapshot(tmp_path) == before


def test_an_empty_home_gives_a_report_that_refuses_the_promotion(tmp_path: Path) -> None:
    report = build_report(tmp_path, BASE, domain="finance", level="N3", at=AT)
    found = _criteria(report)
    assert found["Niveau en vigueur"] == ("N0", "non_atteint")
    assert found["Semaines de paper"] == ("0", "non_atteint")
    assert found["Drawdown paper"] == ("aucune valorisation", "non_evaluable")
    assert found["Écart paper/backtest"][1] == "non_evaluable"
    assert report.verdict == "promotion_impossible"
    assert list(tmp_path.iterdir()) == []


def test_unreadable_files_leave_their_criteria_not_evaluable(tmp_path: Path) -> None:
    for path in (default_loop_path(tmp_path), default_book_path(tmp_path)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"pas une base SQLite")
    evals = tmp_path / "report.json"
    evals.write_text("{", encoding="utf-8")
    report = build_report(tmp_path, config(), domain="finance", level="N3", at=AT, evals=evals)
    found = _criteria(report)
    assert found["Semaines de paper"][1] == "non_evaluable"
    assert found["Semaines de paper"][0].startswith("boucle paper illisible")
    assert found["Décisions de paper"][0].startswith("carnet d'ordres illisible")
    assert found["Golden et red team du domaine"][0].startswith("rapport d'évals illisible")


def test_a_first_valuation_holding_positions_has_no_comparable_backtest(tmp_path: Path) -> None:
    paper_home(tmp_path, held={"FICT-ACME": 10})
    report = build_report(tmp_path, config(), domain="finance", level="N3", at=AT)
    value, status = _criteria(report)["Écart paper/backtest"]
    assert (status, value) == (
        "non_evaluable",
        "positions détenues dès la première valorisation : départs différents",
    )


def _gap_of(root: Path, base: Any = None) -> tuple[str, str]:
    report = build_report(root, base or config(), domain="finance", level="N3", at=AT)
    return _criteria(report)["Écart paper/backtest"]


def test_the_gap_needs_the_book_the_strategy_and_its_backtest(tmp_path: Path) -> None:
    unread = tmp_path / "carnet_illisible"
    paper_home(unread)
    default_book_path(unread).write_bytes(b"pas une base SQLite")
    value, status = _gap_of(unread)
    assert status == "non_evaluable"
    assert value.startswith("carnet d'ordres illisible")
    alone = tmp_path / "sans_ordre"
    with LoopLog.open(default_loop_path(alone)) as log:
        for day in (MONDAY, TUESDAY):
            log.record_valuation(valued(day, "10000.00"))
    assert _gap_of(alone) == ("aucun ordre au carnet : rien à comparer", "non_evaluable")
    costless = tmp_path / "sans_frais"
    paper_home(costless)
    value, status = _gap_of(costless, BASE)
    assert status == "non_evaluable"
    assert "trading_costs" in value


@pytest.mark.parametrize(("domain", "level"), [("finance", "N2"), ("code", "N3"), ("code", "N4")])
def test_there_is_a_report_for_finance_n3_and_n4_only(
    tmp_path: Path, domain: str, level: str
) -> None:
    with pytest.raises(PromotionReportError, match="finance N3 ou N4 seulement"):
        build_report(tmp_path, BASE, domain=domain, level=level, at=AT)


# N3 → N4 (ADR-067) -------------------------------------------------------------------------------


def _decide(journal: AuditJournal, actor: str, state: str, environment: str = "live") -> None:
    payload = {"approval_id": "a", "environment": environment, "state": state, "reason": "r"}
    journal.append(actor=actor, event="APPROVAL", payload=payload)


def test_only_lucas_answers_in_live_are_decisions(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path / "journal.jsonl")
    assert lucas_decisions(journal) == Decisions(0, 0)
    _decide(journal, "lucas", "ACCORDEE")
    _decide(journal, "lucas", "ACCORDEE")
    _decide(journal, "interface", "REFUSEE")
    _decide(journal, "policy", "REFUSEE")  # wrong codes or the Risk Gate: not Lucas
    _decide(journal, "policy", "EXPIREE")
    _decide(journal, "lucas", "ACCORDEE", environment="paper")
    _decide(journal, "policy", "DEMANDEE")
    journal.append(actor="lucas", event="DECISION", payload={"state": "ACCORDEE"})
    assert lucas_decisions(journal) == Decisions(2, 1)


def test_an_altered_journal_decides_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = AuditJournal(tmp_path / "journal.jsonl")
    _decide(journal, "lucas", "ACCORDEE")
    text = journal.path.read_text(encoding="utf-8")
    journal.path.write_text(text.replace('"lucas"', '"policy"'), encoding="utf-8")
    found = lucas_decisions(journal)
    assert isinstance(found, Unavailable)
    assert approvals_count(found, 5).status == "non_evaluable"
    assert agreement_rate(found, 0.9).status == "non_evaluable"
    clean = AuditJournal(tmp_path / "propre.jsonl")
    _decide(clean, "lucas", "ACCORDEE")

    def unreadable(self: AuditJournal, payload_ref: str) -> Any:
        raise PermissionError(payload_ref)

    monkeypatch.setattr(AuditJournal, "read_payload", unreadable)
    assert lucas_decisions(clean) == Unavailable("journal d'audit illisible (PermissionError)")


@pytest.mark.parametrize(
    ("decisions", "minimum", "value", "status"),
    [
        (Decisions(3, 2), 5, "5", "atteint"),
        (Decisions(3, 1), 5, "4", "non_atteint"),
        (Decisions(9, 9), "A_DEFINIR", "18", "non_evaluable"),
    ],
)
def test_the_approvals_are_counted_against_their_minimum(
    decisions: Decisions, minimum: Any, value: str, status: str
) -> None:
    criterion = approvals_count(decisions, minimum)
    assert (criterion.value, criterion.status) == (value, status)


@pytest.mark.parametrize(
    ("decisions", "minimum", "value", "status"),
    [
        (Decisions(9, 1), 0.9, "0.9000", "atteint"),
        (Decisions(8, 2), 0.9, "0.8000", "non_atteint"),
        (Decisions(9, 1), "A_DEFINIR", "0.9000", "non_evaluable"),
        (Decisions(0, 0), 0.5, "aucune décision", "non_evaluable"),
    ],
)
def test_the_agreement_rate_is_the_share_lucas_granted(
    decisions: Decisions, minimum: Any, value: str, status: str
) -> None:
    criterion = agreement_rate(decisions, minimum)
    assert (criterion.value, criterion.status) == (value, status)


def test_a_standing_demotion_refuses_n4(tmp_path: Path) -> None:
    assert demotions_criterion(tmp_path, "finance").status == "atteint"
    path = demotions_path(tmp_path)
    path.parent.mkdir(parents=True)
    line = {
        "at": "2026-10-29T07:00:00+01:00",
        "domain": "finance",
        "from_level": "N3",
        "to_level": "N2",
        "trigger": "nightly_eval_failure",
        "reason": "hebdo",
    }
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")
    criterion = demotions_criterion(tmp_path, "finance")
    assert (criterion.value, criterion.status) == ("1", "non_atteint")
    assert "N3 → N2 (nightly_eval_failure)" in criterion.details[0]
    assert demotions_criterion(tmp_path, "code").status == "atteint"
    path.write_text("{", encoding="utf-8")
    assert demotions_criterion(tmp_path, "finance").status == "non_evaluable"


def test_the_n4_report_asks_n3_in_force_and_cannot_pass_today(tmp_path: Path) -> None:
    journal = AuditJournal(default_journal_path(tmp_path))
    for _ in range(3):
        _decide(journal, "lucas", "ACCORDEE")
    sign(tmp_path, "finance", "N2")
    report = build_report(tmp_path, config(), domain="finance", level="N4", at=AT)
    found = _criteria(report)
    assert report.level == "N4"
    assert found["Niveau en vigueur"] == ("N2", "non_atteint")
    assert found["Approbations N3 décidées par Lucas"] == ("3", "non_evaluable")
    assert found["Taux d'accord Lucas / CERVEAU"] == ("1.0000", "non_evaluable")
    assert found["Incidents d'exécution"] == ("0", "atteint")
    assert found["Drawdown live"][1] == "non_evaluable"
    assert found["Rétrogradations en vigueur"] == ("0", "atteint")
    assert report.verdict == "promotion_impossible"
    assert "# Rapport de promotion finance N3 → N4" in render(report)


# Rendering, writing and signing ------------------------------------------------------------------


def test_the_table_escapes_a_pipe_and_a_new_line() -> None:
    text = render(_report("atteint", value="a|b\nc"))
    assert "| Critère 0 | a\\|b c | seuil | atteint | test |" in text
    assert text.startswith("---\nrapport: promotion\ndomain: finance\nlevel: N3\n")


def test_a_report_is_never_written_over(tmp_path: Path) -> None:
    report = _report("atteint")
    first = write_report(tmp_path, report)
    data = first.read_bytes()
    second = write_report(tmp_path, report)
    assert (first.name, second.name) == ("finance-N3-2026-10-22.md", "finance-N3-2026-10-22-2.md")
    assert first.read_bytes() == data
    assert first.parent == tmp_path / PROMOTION_DIR


def test_a_thousandth_report_of_the_same_day_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / PROMOTION_DIR
    folder.mkdir(parents=True)
    (folder / "finance-N3-2026-10-22.md").write_text("pris", encoding="utf-8")
    for rank in range(2, 1000):
        (folder / f"finance-N3-2026-10-22-{rank}.md").write_text("pris", encoding="utf-8")
    with pytest.raises(PromotionReportError, match="trop de rapports du même jour"):
        write_report(tmp_path, _report("atteint"))


def _signed(root: Path, report: PromotionReport) -> Path:
    path = write_report(root, report)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    signature = root / SIGNATURES_DIR / "2026-10-22-finance-N3.md"
    signature.parent.mkdir(parents=True, exist_ok=True)
    signature.write_text(signature_text("finance", "N3", AT.date(), digest), encoding="utf-8")
    return signature


def test_a_signature_citing_a_possible_report_raises_the_level(tmp_path: Path) -> None:
    passed = _report("atteint", "sans_objet")
    assert "Aucun texte de signature" not in render(passed)
    (tmp_path / PROMOTION_DIR / "brouillons").mkdir(parents=True)  # a folder is no report
    _signed(tmp_path, passed)
    signed = read_signatures(tmp_path, today=AT.date())
    assert (signed.problems, signed.highest("finance")) == ((), "N3")
    assert effective_level(config("N3").autonomy, tmp_path, "finance", today=AT.date()) == "N3"


def test_a_signature_citing_a_refusing_report_counts_for_nothing(tmp_path: Path) -> None:
    refused = _report("atteint", "non_atteint")
    assert "Aucun texte de signature" in render(refused)
    _signed(tmp_path, refused)
    [problem] = read_signatures(tmp_path, today=AT.date()).problems
    assert "conclut « promotion_impossible »" in problem
    assert effective_level(config("N3").autonomy, tmp_path, "finance", today=AT.date()) == "N0"


# The command ------------------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "home"
    root.mkdir()
    monkeypatch.setenv("CERVEAU_HOME", str(root))
    yield root


def _invoke(config_dir: Path, *args: str) -> Any:
    command = ["promotion", "report", "finance", *args, "--config-dir", str(config_dir)]
    return CliRunner().invoke(app, command)


def _entries(root: Path) -> list[dict[str, Any]]:
    path = default_journal_path(root)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_the_command_writes_and_journals_a_refused_report(home: Path, config_dir: Path) -> None:
    result = _invoke(config_dir, "--to", "N3")
    assert result.exit_code == 1, result.output
    [written] = (home / PROMOTION_DIR).iterdir()
    digest = hashlib.sha256(written.read_bytes()).hexdigest()
    assert digest in result.output
    assert "Aucun texte de signature" in result.output
    assert "signed_by" not in result.output
    [entry] = _entries(home)
    assert (entry["actor"], entry["event"]) == ("lucas", "TOOL_CALL")
    payload = AuditJournal(default_journal_path(home)).read_payload(entry["payload_ref"])
    assert payload["statut"] == "promotion_impossible"
    assert payload["rapport_sha256"] == digest
    assert payload["rapport"] == f"var/promotion/{written.name}"


def test_the_command_refuses_a_level_without_a_report(home: Path, config_dir: Path) -> None:
    result = _invoke(config_dir, "--to", "N2")
    assert result.exit_code == 1
    assert "Rapport impossible" in result.output
    assert list(home.iterdir()) == []


def _built(*statuses: Any) -> Any:
    def build(root: Path, config: Any, **kwargs: Any) -> PromotionReport:
        criteria = tuple(
            Criterion(f"Critère {n}", "v", "s", status, "test") for n, status in enumerate(statuses)
        )
        return PromotionReport("finance", "N3", kwargs["at"], config.digest, criteria)

    return build


def test_a_possible_promotion_shows_the_signature_lucas_copies(
    home: Path, config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("interfaces.cli.promotion.build_report", _built("atteint"))
    result = _invoke(config_dir, "--to", "N3")
    assert result.exit_code == 0, result.output
    [written] = (home / PROMOTION_DIR).iterdir()
    digest = hashlib.sha256(written.read_bytes()).hexdigest()
    assert f'promotion_report_sha256: "{digest}"' in result.output
    assert "signed_by: lucas" in result.output
    assert not (home / SIGNATURES_DIR).exists()


def test_an_unknown_criterion_exits_blocked(
    home: Path, config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("interfaces.cli.promotion.build_report", _built("non_evaluable"))
    result = _invoke(config_dir, "--to", "N3")
    assert result.exit_code == 2, result.output
    assert "signed_by" not in result.output
