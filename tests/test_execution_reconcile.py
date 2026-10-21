"""Reconciliation of the paper account with CERVEAU's book (ADR-033, D14, D15)."""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.execution.book import OrderBook
from core.execution.broker import AccountStatement, BrokerAdapter, FillBatch
from core.execution.paper import PaperSimulator
from core.execution.reconcile import (
    ReconciliationError,
    ReconciliationLog,
    default_log_path,
    interactive_terminal,
    reconcile,
    settle,
)
from core.execution.states import ExecutionIncident, OrderState
from core.finance.portfolio import Gap
from core.finance.schema import SchemaError
from core.risk_gate.gate import RiskGateResult, evaluate
from tests.execution_cases import (
    BOOKED_AT,
    FILLED_AT,
    MemoryJournal,
    make_fill,
    make_intent,
    recorder,
)
from tests.risk_gate.cases import base_world, build, changed
from tests.test_execution_book import sent
from tests.test_execution_paper import (
    CAPITAL,
    CLOSED,
    SUBMITTED,
    TUESDAY,
    Market,
    bar,
    sell,
    simulator,
    tuesday,
)

CASH = Decimal("8767.30")  # 10,000.00 less 10 × 123.07 and the 2.00 minimum commission
NEXT_DAY = CLOSED + timedelta(days=1)
DECISION_KEYS = {
    "reconciliation",
    "gaps",
    "fills",
    "cursor",
    "book_sha256",
    "statement_sha256",
    "open_gaps",
}


def at_console() -> bool:
    return True


def scripted() -> bool:
    return False


def bought(journal: MemoryJournal) -> tuple[OrderBook, PaperSimulator, ReconciliationLog]:
    """Ten shares bought on Monday's close by the simulator; the fills not booked yet."""
    book = OrderBook.memory(recorder(journal))
    sim = simulator()
    buy = make_intent(0)
    sent(book, buy)
    assert sim.submit(buy, now=SUBMITTED).accepted
    sim.close_session(make_fill(buy, 1, 10).session, Market(bar()), now=CLOSED)
    return book, sim, ReconciliationLog.memory(recorder(journal))


def gate(open_gaps: int) -> RiskGateResult:
    world = changed(base_world(), snapshot__open_reconciliation_gaps=open_gaps)
    return evaluate(*build(world).args)


def events(journal: MemoryJournal, event: str) -> list[dict[str, Any]]:
    return [entry for entry in journal.entries if entry["event"] == event]


def rows(path: Path) -> list[tuple[str, int]]:
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT kind, gaps FROM entries ORDER BY seq").fetchall()


def test_the_log_lives_next_to_the_order_book(tmp_path: Path) -> None:
    assert default_log_path(tmp_path) == tmp_path / "var" / "paper" / "reconciliation.db"


# A clean account --------------------------------------------------------------------------------


def test_a_paper_account_reconciles_cleanly_after_a_buy_and_a_partial_sale() -> None:
    journal = MemoryJournal()
    book, sim, log = bought(journal)
    first = settle(book, sim, log, capital_eur=CAPITAL, now=CLOSED)
    assert (first.clean, first.fills, first.gaps) == (True, 1, ())
    assert sim.account_snapshot().cash_eur == CASH

    order = sell(1, quantity=4, limit_price=Decimal("120.00"))
    sent(book, order)
    assert sim.submit(order, now=CLOSED + timedelta(hours=1)).accepted
    sim.close_session(TUESDAY, Market(tuesday()), now=NEXT_DAY)
    second = settle(book, sim, log, capital_eur=CAPITAL, now=NEXT_DAY)

    assert (second.clean, second.fills) == (True, 2)
    assert second.cursor == sim.account_snapshot().cursor
    assert book.order(order.intent_id).state == OrderState.EXECUTEE
    assert sim.account_snapshot().positions == {"FICT-ACME": 6}
    assert log.open_gaps() == 0
    assert not log.awaiting_acknowledgement()
    decisions = events(journal, "DECISION")
    assert [d["payload"]["reconciliation"] for d in decisions] == ["propre", "propre"]
    assert {d["actor"] for d in decisions} == {"orchestrator"}
    last = decisions[-1]["payload"]
    assert set(last) == DECISION_KEYS  # counts, assets and fingerprints: never an amount
    assert (last["gaps"], last["fills"], last["open_gaps"]) == ([], 2, 0)
    assert (last["book_sha256"], last["statement_sha256"]) == (
        second.book_sha256,
        second.statement_sha256,
    )
    assert first.book_sha256 != second.book_sha256


def test_settling_again_books_nothing_twice() -> None:
    journal = MemoryJournal()
    book, sim, log = bought(journal)
    first = settle(book, sim, log, capital_eur=CAPITAL, now=CLOSED)
    states = len(events(journal, "ORDER_STATE"))
    again = settle(book, sim, log, capital_eur=CAPITAL, now=CLOSED)
    assert again == first
    assert len(events(journal, "ORDER_STATE")) == states
    assert len(book.orders()[0].fills) == 1
    assert len(events(journal, "DECISION")) == 2


def test_an_account_without_fills_holds_the_capital() -> None:
    result = reconcile([], AccountStatement(CAPITAL), capital_eur=CAPITAL, as_of=BOOKED_AT)
    assert (result.clean, result.fills, result.cursor) == (True, 0, 0)


# Gaps --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cash", "positions", "gap"),
    [
        (
            CASH - Decimal("0.01"),
            {"FICT-ACME": 10},
            Gap("paper", "cash", "EUR", CASH - Decimal("0.01"), CASH),
        ),
        (CASH, {}, Gap("paper", "security", "FICT-ACME", Decimal(0), Decimal(10))),
        (CASH, {"FICT-ACME": 11}, Gap("paper", "security", "FICT-ACME", Decimal(11), Decimal(10))),
        (
            CASH,
            {"FICT-ACME": 10, "FICT-BETA": 3},
            Gap("paper", "security", "FICT-BETA", Decimal(3), Decimal(0)),
        ),
    ],
    ids=["cash-one-cent", "position-missing", "one-share-more", "unknown-position"],
)
def test_each_gap_is_found_exactly(cash: Decimal, positions: dict[str, int], gap: Gap) -> None:
    book, sim, log = bought(MemoryJournal())
    settle(book, sim, log, capital_eur=CAPITAL, now=CLOSED)
    statement = AccountStatement(cash, positions, sim.account_snapshot().cursor)
    result = reconcile(book.orders(), statement, capital_eur=CAPITAL, as_of=CLOSED)
    assert result.gaps == (gap,)
    assert result.assets() == [f"{gap.nature}:{gap.asset}"]


def test_a_gap_blocks_intents_until_lucas_acknowledges_a_clean_reconciliation() -> None:
    journal = MemoryJournal()
    book, sim, log = bought(journal)
    settle(book, sim, log, capital_eur=CAPITAL, now=CLOSED)
    honest = sim.account_snapshot()
    short = replace(honest, cash_eur=CASH - Decimal("0.01"), positions={})

    gap = reconcile(book.orders(), short, capital_eur=CAPITAL, as_of=CLOSED)
    assert log.record(gap, now=CLOSED) == 2
    assert log.open_gaps() == 2
    refused = gate(log.open_gaps())
    assert refused.result == "REFUSE"
    assert "reconciliation : écart de réconciliation ouvert" in refused.reasons
    decision = events(journal, "DECISION")[-1]["payload"]
    assert decision["reconciliation"] == "ecart"
    assert decision["gaps"] == ["cash:EUR", "security:FICT-ACME"]
    assert decision["open_gaps"] == 2
    assert str(CASH) not in str(journal.entries)

    with pytest.raises(ReconciliationError, match="n'est pas propre"):
        log.acknowledge(now=CLOSED, interactive=at_console)
    one = reconcile(
        book.orders(),
        replace(short, positions={"FICT-ACME": 10}),
        capital_eur=CAPITAL,
        as_of=CLOSED,
    )
    assert log.record(one, now=CLOSED) == 1  # the last reconciliation's gaps
    assert settle(book, sim, log, capital_eur=CAPITAL, now=CLOSED).clean
    assert log.open_gaps() == 1  # clean again, still blocked
    assert log.awaiting_acknowledgement()
    assert gate(log.open_gaps()).result == "REFUSE"

    with pytest.raises(ReconciliationError, match="terminal interactif"):
        log.acknowledge(now=CLOSED, interactive=scripted)
    assert log.acknowledge(now=CLOSED, interactive=at_console) == 1
    assert (log.open_gaps(), log.awaiting_acknowledgement()) == (0, False)
    assert not [c for c in gate(log.open_gaps()).checks if c.name == "reconciliation" and not c.ok]
    approval = events(journal, "APPROVAL")
    assert [(a["actor"], a["payload"]) for a in approval] == [
        ("lucas", {"reconciliation": "acquittee", "gaps": 1})
    ]
    with pytest.raises(ReconciliationError, match="aucun écart"):
        log.acknowledge(now=CLOSED, interactive=at_console)

    assert log.record(gap, now=NEXT_DAY) == 2  # a new gap blocks again
    assert not log.awaiting_acknowledgement()


def test_without_a_gap_there_is_nothing_to_acknowledge() -> None:
    log = ReconciliationLog.memory(recorder(MemoryJournal()))
    with pytest.raises(ReconciliationError, match="aucun écart"):
        log.acknowledge(now=CLOSED, interactive=at_console)
    assert not log.awaiting_acknowledgement()


# Incidents ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cash", "positions", "message"),
    [
        (CASH, {"FICT-ACME": -10}, "position nulle, négative ou fractionnaire"),
        (CASH, {"FICT-ACME": 0}, "position nulle, négative ou fractionnaire"),
        (CASH, {"FICT-ACME": True}, "position nulle, négative ou fractionnaire"),
        (CASH, {"FICT-ACME": 10.0}, "position nulle, négative ou fractionnaire"),
        (8767.3, {"FICT-ACME": 10}, "cash illisible"),
        (Decimal("NaN"), {"FICT-ACME": 10}, "cash illisible"),
        (Decimal("Infinity"), {"FICT-ACME": 10}, "cash illisible"),
        (CASH, {"fict acme": 10}, "identifiant d'instrument invalide"),
    ],
    ids=["negative", "zero", "bool", "float-shares", "float-cash", "nan", "infinity", "symbol"],
)
def test_a_statement_no_account_can_hold_is_an_incident_and_records_nothing(
    cash: Any, positions: dict[str, Any], message: str
) -> None:
    journal = MemoryJournal()
    book, sim, log = bought(journal)
    settle(book, sim, log, capital_eur=CAPITAL, now=CLOSED)
    before = list(journal.entries)
    adapter = Lying(sim, AccountStatement(cash, positions, 1))
    with pytest.raises(ExecutionIncident, match=message) as caught:
        settle(book, cast(BrokerAdapter, adapter), log, capital_eur=CAPITAL, now=CLOSED)
    assert caught.value.kind == "execution_incoherente"
    assert journal.entries == before
    assert log.open_gaps() == 0


class Lying:
    """The simulator's fills, with a statement of its own."""

    def __init__(self, sim: PaperSimulator, statement: AccountStatement) -> None:
        self.sim = sim
        self.statement = statement

    def fills_since(self, cursor: int) -> FillBatch:
        return self.sim.fills_since(cursor)

    def account_snapshot(self) -> AccountStatement:
        return self.statement


def test_a_sale_the_book_cannot_replay_is_an_incident() -> None:
    book = OrderBook.memory(recorder(MemoryJournal()))
    order = make_intent(0, side="SELL")
    sent(book, order)
    book.record_fill(make_fill(order, 1, 10), now=BOOKED_AT)
    with pytest.raises(ExecutionIncident, match=r"non rejouable : .*vente supérieure") as caught:
        reconcile(book.orders(), AccountStatement(CAPITAL), capital_eur=CAPITAL, as_of=BOOKED_AT)
    assert caught.value.kind == "execution_incoherente"


def test_a_fill_after_the_reconciliation_day_is_an_incident() -> None:
    book = OrderBook.memory(recorder(MemoryJournal()))
    order = make_intent(0)
    sent(book, order)
    book.record_fill(make_fill(order, 1, 10), now=BOOKED_AT)
    with pytest.raises(ExecutionIncident, match=r"non rejouable : .*opération après"):
        reconcile(
            book.orders(),
            AccountStatement(CAPITAL),
            capital_eur=CAPITAL,
            as_of=FILLED_AT - timedelta(days=1),
        )


def test_a_fill_of_an_order_the_book_never_sent_is_an_incident() -> None:
    journal = MemoryJournal()
    book = OrderBook.memory(recorder(journal))
    log = ReconciliationLog.memory(recorder(journal))
    sim = simulator()
    stray = make_intent(0)
    assert sim.submit(stray, now=SUBMITTED).accepted
    sim.close_session(make_fill(stray, 1, 10).session, Market(bar()), now=CLOSED)
    with pytest.raises(ExecutionIncident) as caught:
        settle(book, sim, log, capital_eur=CAPITAL, now=CLOSED)
    assert (caught.value.kind, caught.value.intent_id) == ("ordre_inconnu", stray.intent_id)
    assert journal.entries == []
    assert log.open_gaps() == 0


# The log ----------------------------------------------------------------------------------------


def test_a_refused_journal_entry_records_nothing(tmp_path: Path) -> None:
    path = tmp_path / "reconciliation.db"
    book, sim, _ = bought(MemoryJournal())
    settle(
        book,
        sim,
        ReconciliationLog.memory(recorder(MemoryJournal())),
        capital_eur=CAPITAL,
        now=CLOSED,
    )
    statement = sim.account_snapshot()
    gap = reconcile(
        book.orders(), replace(statement, positions={}), capital_eur=CAPITAL, as_of=CLOSED
    )
    clean = reconcile(book.orders(), statement, capital_eur=CAPITAL, as_of=CLOSED)

    with ReconciliationLog.open(path, recorder(MemoryJournal(fail_at=1))) as log:
        with pytest.raises(OSError, match="journal indisponible"):
            log.record(gap, now=CLOSED)
        assert log.open_gaps() == 0
    assert rows(path) == []

    with ReconciliationLog.open(path, recorder(MemoryJournal(fail_at=3))) as log:
        log.record(gap, now=CLOSED)
        log.record(clean, now=CLOSED)
        with pytest.raises(OSError, match="journal indisponible"):
            log.acknowledge(now=CLOSED, interactive=at_console)
        assert log.open_gaps() == 1
    assert rows(path) == [("reconciliation", 1), ("reconciliation", 0)]


def test_the_log_persists_and_refuses_changes(tmp_path: Path) -> None:
    path = tmp_path / "var" / "paper" / "reconciliation.db"
    book, sim, _ = bought(MemoryJournal())
    settle(
        book,
        sim,
        ReconciliationLog.memory(recorder(MemoryJournal())),
        capital_eur=CAPITAL,
        now=CLOSED,
    )
    gap = reconcile(
        book.orders(),
        replace(sim.account_snapshot(), positions={}),
        capital_eur=CAPITAL,
        as_of=CLOSED,
    )
    with ReconciliationLog.open(path, recorder(MemoryJournal())) as log:
        log.record(gap, now=CLOSED)
    with ReconciliationLog.open(path, recorder(MemoryJournal())) as log:
        assert log.open_gaps() == 1

    with sqlite3.connect(path) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="ne se modifie pas"):
            conn.execute("UPDATE entries SET gaps = 0")
        with pytest.raises(sqlite3.DatabaseError, match="ne se supprime pas"):
            conn.execute("DELETE FROM entries")
        with pytest.raises(sqlite3.DatabaseError, match="D14"):
            conn.execute(
                "INSERT INTO entries (kind, at, gaps, detail, recorded_at) "
                "VALUES ('acknowledgement', 'x', 1, '{}', 'x')"
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute(
                "INSERT INTO entries (kind, at, gaps, detail, recorded_at) "
                "VALUES ('reconciliation', 'x', 0, '[]', 'x')"
            )
        assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone() == (1,)
    assert rows(path) == [("reconciliation", 1)]


class Tty:
    def __init__(self, tty: bool) -> None:
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


@pytest.mark.parametrize(
    ("stdin", "stdout", "expected"),
    [
        (Tty(True), Tty(True), True),
        (Tty(True), Tty(False), False),
        (Tty(False), Tty(True), False),
        (None, Tty(True), False),
        (Tty(True), None, False),
    ],
)
def test_only_a_console_on_both_ends_is_interactive(
    monkeypatch: pytest.MonkeyPatch, stdin: Tty | None, stdout: Tty | None, expected: bool
) -> None:
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    assert interactive_terminal() is expected


def test_an_acknowledgement_under_pytest_is_refused_by_default() -> None:
    log = ReconciliationLog.memory(recorder(MemoryJournal()))
    with pytest.raises(ReconciliationError, match="terminal interactif"):
        log.acknowledge(now=CLOSED)


# Property -----------------------------------------------------------------------------------------

SYMBOLS = ("FICT-ACME", "FICT-BETA")
TRADES = st.lists(
    st.tuples(
        st.sampled_from(SYMBOLS),
        st.booleans(),  # a sale, when something is held
        st.integers(1, 50),
        st.integers(1, 50_000),  # the price, in cents
        st.integers(0, 2_000),  # the fees, in cents
    ),
    max_size=8,
)


@settings(max_examples=50, deadline=None)
@given(
    trades=TRADES,
    perturbation=st.sampled_from(["none", "cash", "position", "missing", "extra"]),
    delta=st.integers(1, 1_000),
)
def test_any_paper_book_reconciles_and_one_change_gives_exactly_its_gap(
    trades: list[tuple[str, bool, int, int, int]], perturbation: str, delta: int
) -> None:
    book = OrderBook.memory(recorder(MemoryJournal()))
    cash, held = CAPITAL, dict.fromkeys(SYMBOLS, 0)
    for n, (symbol, selling, quantity, cents, fee_cents) in enumerate(trades):
        price, fees = Decimal(cents).scaleb(-2), Decimal(fee_cents).scaleb(-2)
        selling = selling and held[symbol] > 0
        quantity = min(quantity, held[symbol]) if selling else quantity
        order = make_intent(
            n,
            side="SELL" if selling else "BUY",
            quantity=quantity,
            limit_price=price,
            instrument__symbol=symbol,
        )
        sent(book, order)
        fill = make_fill(
            order, 1, quantity, fees=fees, executed_at=FILLED_AT + timedelta(minutes=n)
        )
        book.record_fill(fill, now=BOOKED_AT)
        held[symbol] += -quantity if selling else quantity
        cash += quantity * price - fees if selling else -(quantity * price + fees)

    positions = {symbol: quantity for symbol, quantity in held.items() if quantity}
    owned = sorted(positions)
    if perturbation in ("position", "missing") and not owned:
        perturbation = "extra"
    expected: tuple[Gap, ...] = ()
    if perturbation == "cash":
        stated = cash + Decimal(delta).scaleb(-2)
        expected = (Gap("paper", "cash", "EUR", stated, cash),)
        cash = stated
    elif perturbation == "position":
        quantity = positions[owned[0]]
        positions[owned[0]] = quantity + delta
        expected = (
            Gap("paper", "security", owned[0], Decimal(quantity + delta), Decimal(quantity)),
        )
    elif perturbation == "missing":
        quantity = positions.pop(owned[0])
        expected = (Gap("paper", "security", owned[0], Decimal(0), Decimal(quantity)),)
    elif perturbation == "extra":
        positions["FICT-GAMMA"] = delta
        expected = (Gap("paper", "security", "FICT-GAMMA", Decimal(delta), Decimal(0)),)

    statement = AccountStatement(cash, positions, len(trades))
    result = reconcile(book.orders(), statement, capital_eur=CAPITAL, as_of=BOOKED_AT)
    assert result.gaps == expected
    assert result.fills == len(trades)


def test_a_log_from_a_newer_cerveau_is_refused_and_closed(tmp_path: Path) -> None:
    path = tmp_path / "reconciliation.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT)")
        conn.execute("INSERT INTO schema_version VALUES (2, 'x')")
    conn.close()
    with pytest.raises(SchemaError, match="plus récent"):
        ReconciliationLog.open(path, recorder(MemoryJournal()))
    path.unlink()  # the connection was closed: Windows would refuse otherwise
