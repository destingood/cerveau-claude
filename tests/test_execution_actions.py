"""Splits and dividends on the paper account (ADR-042, B187)."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from core.execution.actions import (
    AccountAction,
    Movement,
    dividend_effect,
    exact_value,
    replay_account,
    split_effect,
)
from core.execution.book import OrderBook
from core.execution.intent import OrderIntent
from core.execution.paper import PaperSimulator
from core.execution.reconcile import ReconciliationLog, settle
from core.execution.states import ExecutionIncident
from core.finance.model import PARIS, CorporateAction
from tests.execution_cases import MemoryJournal, make_intent, recorder
from tests.test_execution_book import sent
from tests.test_execution_paper import (
    CAPITAL,
    CLOSED,
    FILLED_AT,
    SESSION,
    SUBMITTED,
    TUESDAY,
    Market,
    bar,
    sell,
    simulator,
    tuesday,
)

SYMBOL = "FICT-ACME"
WEDNESDAY = date(2026, 10, 21)
ANNOUNCED = datetime(2026, 10, 19, 20, 0, tzinfo=PARIS)
NEXT_DAY = CLOSED + timedelta(days=1)  # Tuesday 18:00, after Tuesday's close
CASH = Decimal("8767.30")  # 10,000.00 less 10 × 123.07 and the 2.00 minimum commission


def split(value: float, ex_date: date = TUESDAY, symbol: str = SYMBOL) -> CorporateAction:
    return CorporateAction(
        instrument_id=symbol,
        ex_date=ex_date,
        kind="split",
        value=value,
        source="fixtures",
        published_at=ANNOUNCED,
    )


def dividend(value: float, currency: str = "EUR", ex_date: date = TUESDAY) -> CorporateAction:
    return CorporateAction(
        instrument_id=SYMBOL,
        ex_date=ex_date,
        kind="dividend",
        value=value,
        currency=currency,
        source="fixtures",
        published_at=ANNOUNCED,
    )


def entry(kind: str = "split", value: str = "2", **changes: Any) -> AccountAction:
    data: dict[str, Any] = {
        "session": TUESDAY,
        "symbol": SYMBOL,
        "ex_date": TUESDAY,
        "kind": kind,
        "value": Decimal(value),
    }
    data |= {"close": Decimal("60.00")} if kind == "split" else {"currency": "EUR"}
    return AccountAction(**(data | changes))


def wednesday(**changes: Any) -> Any:
    return bar(session=WEDNESDAY, published_at=FILLED_AT + timedelta(days=2), **changes)


def held(
    quantity: int = 10, journal: MemoryJournal | None = None
) -> tuple[PaperSimulator, OrderBook, OrderIntent]:
    """``quantity`` shares bought on Monday's close, in the simulator and in the book."""
    sim = simulator()
    book = OrderBook.memory(recorder(journal or MemoryJournal()))
    buy = make_intent(0, quantity=quantity)
    sent(book, buy)
    assert sim.submit(buy, now=SUBMITTED).accepted
    [fill] = sim.close_session(SESSION, Market(bar()), now=CLOSED).fills
    assert fill.quantity == quantity
    return sim, book, buy


def clean(sim: PaperSimulator, book: OrderBook, now: datetime) -> Any:
    log = ReconciliationLog.memory(recorder(MemoryJournal()))
    result = settle(book, sim, log, capital_eur=CAPITAL, now=now)
    assert result.gaps == ()
    return result


# The rules ---------------------------------------------------------------------------------------


def test_a_stored_float_is_the_decimal_it_was_written_as() -> None:
    assert exact_value(2.0) == Decimal(2) and str(exact_value(2.0)) == "2"
    assert str(exact_value(0.35)) == "0.35"
    assert str(exact_value(1 / 3)) == "0.3333333333333333"


@pytest.mark.parametrize(
    "changes",
    [
        {"value": Decimal(0)},
        {"value": Decimal("NaN")},
        {"session": SESSION},  # before its ex-date
        {"close": None},
        {"currency": "EUR"},
    ],
)
def test_an_action_the_account_cannot_book_is_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"opération sur titres|un split porte"):
        entry(**changes)
    with pytest.raises(ValueError, match="un split porte"):
        entry("dividend", close=Decimal(1))


@pytest.mark.parametrize(
    ("held", "value", "shares", "cash"),
    [
        (10, "2", 20, "0"),
        (5, "1.5", 7, "30.00"),  # half a share at 60.00
        (7, "0.5", 3, "30.00"),  # a reverse split: the half share is paid
        (3, "0.3333333333333333", 1, "0"),  # within the tolerance: one share, nothing paid
        (3, "2.0000000000000004", 6, "0"),
        (1, "1.001", 1, "0.06"),  # 0.001 share at 60.00 is 0.06, rounded down
    ],
)
def test_a_split_keeps_whole_shares_and_pays_the_fraction_rounded_down(
    held: int, value: str, shares: int, cash: str
) -> None:
    effect = split_effect(entry(value=value), held)
    assert (effect.held, effect.shares, effect.cash) == (held, shares, Decimal(cash))


def test_a_dividend_is_rounded_down_and_never_credited_in_another_currency() -> None:
    assert dividend_effect(entry("dividend", "0.3333"), 10).cash == Decimal("3.33")
    assert dividend_effect(entry("dividend", "0.35", currency="USD"), 10).cash == 0


def test_a_session_applies_its_splits_then_its_fills_then_its_dividends() -> None:
    monday = Movement(SESSION, SYMBOL, 10, Decimal("-1232.70"))
    tuesday_buy = Movement(TUESDAY, SYMBOL, 4, Decimal("-200.00"))
    replayed = replay_account(
        [entry("dividend", "1"), entry(value="2")], [monday, tuesday_buy, Movement(TUESDAY, "X", 1)]
    )
    # 10 shares doubled at the start of Tuesday, then 4 bought; the dividend is paid on 20.
    assert replayed.positions == {SYMBOL: 24, "X": 1}
    assert replayed.cash == Decimal("-1232.70") - Decimal("200.00") + Decimal("20.00")
    assert [(e.action.kind, e.held, e.shares) for e in replayed.effects] == [
        ("split", 10, 20),
        ("dividend", 20, 20),
    ]


def test_an_action_on_a_position_of_zero_has_no_effect() -> None:
    replayed = replay_account([entry(), entry("dividend")], [Movement(WEDNESDAY, SYMBOL, 1)])
    assert (replayed.positions, replayed.cash, replayed.effects) == ({SYMBOL: 1}, 0, ())


def test_a_sale_beyond_the_position_after_the_actions_is_an_incident() -> None:
    movements = [Movement(SESSION, SYMBOL, 10), Movement(TUESDAY, SYMBOL, -10)]
    with pytest.raises(ExecutionIncident, match="au-delà de la position"):
        replay_account([entry(value="0.5")], movements)


# The simulator -----------------------------------------------------------------------------------


def test_a_split_is_booked_at_its_session_with_its_fraction_paid() -> None:
    sim, book, _ = held(5)
    before = sim.account_snapshot()
    report = sim.book_actions([split(1.5)], Market(tuesday(close=Decimal("82.00"))), now=NEXT_DAY)
    [booked] = report.booked
    assert (booked.session, booked.value, booked.close) == (TUESDAY, Decimal("1.5"), Decimal(82))
    assert (report.cancelled, report.notes) == ((), ())
    after = sim.account_snapshot()
    assert after.positions == {SYMBOL: 7}
    assert after.cash_eur == before.cash_eur + Decimal("41.00")
    assert (after.cursor, after.actions) == (before.cursor, (booked,))
    assert clean(sim, book, NEXT_DAY).fills == 1


@pytest.mark.parametrize(("value", "shares"), [(1 / 3, 1), (2.0000000000000004, 6)])
def test_a_split_within_the_tolerance_reconciles_exactly(value: float, shares: int) -> None:
    sim, book, _ = held(3)
    before = sim.account_snapshot().cash_eur
    sim.book_actions([split(value)], Market(tuesday()), now=NEXT_DAY)
    after = sim.account_snapshot()
    assert (after.positions, after.cash_eur) == ({SYMBOL: shares}, before)
    clean(sim, book, NEXT_DAY)


def test_a_dividend_is_credited_on_the_shares_held_and_reconciles() -> None:
    sim, book, _ = held()
    report = sim.book_actions([dividend(0.3333)], Market(tuesday()), now=NEXT_DAY)
    assert [a.kind for a in report.booked] == ["dividend"]
    assert sim.account_snapshot().cash_eur == CASH + Decimal("3.33")
    first = clean(sim, book, NEXT_DAY)
    report = sim.book_actions(
        [dividend(0.5, "USD", WEDNESDAY)], Market(wednesday()), now=NEXT_DAY + timedelta(days=1)
    )
    assert report.notes == (
        "dividende de FICT-ACME (ex-date 2026-10-21) : versé en USD, non crédité (ADR-042)",
    )
    assert sim.account_snapshot().cash_eur == CASH + Decimal("3.33")
    second = clean(sim, book, NEXT_DAY + timedelta(days=1))
    assert first.book_sha256 != second.book_sha256
    assert first.statement_sha256 != second.statement_sha256


def test_an_action_waits_for_the_close_of_its_session() -> None:
    sim, _, _ = held()
    for market, now in [(Market(tuesday()), CLOSED), (Market(), NEXT_DAY)]:
        report = sim.book_actions([split(2.0)], market, now=now)
        assert (report.booked, report.notes) == ((), ())
    assert sim.account_snapshot().positions == {SYMBOL: 10}
    assert sim.book_actions([split(2.0)], Market(tuesday()), now=NEXT_DAY).booked


def test_an_action_is_booked_once_and_keeps_its_first_version() -> None:
    sim, _, _ = held()
    sim.book_actions([split(2.0)], Market(tuesday()), now=NEXT_DAY)
    again = sim.book_actions([split(2.0)], Market(tuesday()), now=NEXT_DAY)
    assert (again.booked, again.notes) == ((), ())
    revised = sim.book_actions([split(3.0)], Market(tuesday()), now=NEXT_DAY)
    assert revised.notes == (
        "split de FICT-ACME (ex-date 2026-10-20) : révision ignorée, la première version reste",
    )
    assert sim.account_snapshot().positions == {SYMBOL: 20}


def test_actions_before_the_first_order_or_on_other_instruments_are_not_booked() -> None:
    sim, _, _ = held()
    friday = date(2026, 10, 16)
    actions = [split(2.0, friday), split(2.0, symbol="FICT-BETA")]
    market = Market(tuesday(), bar(session=friday, published_at=FILLED_AT - timedelta(days=3)))
    report = sim.book_actions(actions, market, now=NEXT_DAY)
    assert (report.booked, report.notes) == ((), ())


def test_a_split_cancels_the_working_orders_of_its_instrument_from_its_session() -> None:
    sim, _, _ = held()
    order = sell(1, limit_price=Decimal("120.00"))
    assert sim.submit(order, now=CLOSED + timedelta(hours=1)).accepted
    report = sim.book_actions([split(2.0)], Market(tuesday()), now=NEXT_DAY)
    assert report.cancelled == (order.intent_id,)
    assert sim.open_orders() == ()
    assert sim.account_snapshot().positions == {SYMBOL: 20}


def test_an_action_known_after_its_session_closed_is_booked_late() -> None:
    sim, book, _ = held()
    sim.close_session(TUESDAY, Market(tuesday()), now=NEXT_DAY)
    report = sim.book_actions([split(2.0)], Market(tuesday()), now=NEXT_DAY)
    assert report.notes == (
        "split de FICT-ACME (ex-date 2026-10-20) connu après la clôture de sa séance du "
        "2026-10-20 : comptabilisé en retard, exécutions passées inchangées",
    )
    assert sim.account_snapshot().positions == {SYMBOL: 20}
    clean(sim, book, NEXT_DAY)


def test_a_reverse_split_after_a_sale_of_the_position_is_an_incident() -> None:
    sim, _, _ = held()
    assert sim.submit(sell(1, limit_price=Decimal("120.00")), now=CLOSED + timedelta(hours=1))
    assert sim.close_session(TUESDAY, Market(tuesday()), now=NEXT_DAY).fills
    with pytest.raises(ExecutionIncident, match="au-delà de la position"):
        sim.book_actions([split(0.5)], Market(tuesday()), now=NEXT_DAY)
    assert sim.account_snapshot().actions == ()


def test_a_split_quoted_in_another_currency_is_not_booked() -> None:
    sim, _, _ = held()
    report = sim.book_actions([split(2.0)], Market(tuesday(currency="USD")), now=NEXT_DAY)
    assert report.booked == ()
    assert report.notes == (
        "split de FICT-ACME (ex-date 2026-10-20) : clôture en USD, split non comptabilisé",
    )


def test_the_actions_only_grow() -> None:
    sim, _, _ = held()
    sim.book_actions([split(2.0)], Market(tuesday()), now=NEXT_DAY)
    for statement in ("UPDATE actions SET value = '3'", "DELETE FROM actions"):
        with pytest.raises(sqlite3.IntegrityError, match="ne se"):
            sim._conn.execute(statement)
