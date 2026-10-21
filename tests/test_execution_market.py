"""What the paper loop reads of the market from the finance store (ADR-031)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from core.execution.book import OrderBook, Recorder
from core.execution.broker import AccountStatement
from core.execution.market import (
    MarketError,
    StoreMarket,
    exact,
    gate_snapshot,
    market_facts,
    sessions_since,
    target_days_since,
)
from core.execution.states import OrderState
from core.finance.model import FxRate, Instrument, PriceRow
from core.finance.store import FinanceStore
from core.risk_gate.snapshot import Account
from tests.execution_cases import MemoryJournal, make_intent
from tests.test_execution_loop import (
    LOADED,
    MONDAY,
    MONDAY_RUN,
    SYMBOL,
    TUESDAY,
    ingest,
    market,
    run_at,
)

ACCOUNT = Account(
    cash_eur=Decimal("10000"),
    equity_eur=Decimal("10000"),
    peak_equity_eur=Decimal("10000"),
    day_pnl_eur=Decimal(0),
    rolling_pnl_eur=Decimal(0),
    rolling_sessions=20,
)


@pytest.fixture
def store() -> Iterator[FinanceStore]:
    built = market()
    yield built
    built.close()


def add_usd(store: FinanceStore, rate: float | None) -> None:
    """A New York instrument at 50 USD on Monday, and the ECB rate of Monday if given."""
    store.add_instrument(
        Instrument(
            instrument_id="FICT-USD",
            valid_from=date(2020, 1, 1),
            name="Fictive US",
            asset_class="equity",
            currency="USD",
            mic="XNYS",
            sector="Industrie",
            country="US",
        ),
        recorded_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    records: list[PriceRow | FxRate] = [
        PriceRow(
            instrument_id="FICT-USD",
            session=MONDAY,
            close=50.0,
            volume=300_000,
            currency="USD",
            source="fixtures",
            published_at=datetime(2026, 10, 19, 20, 5, tzinfo=UTC),
        )
    ]
    if rate is not None:
        records.append(
            FxRate(
                currency="USD",
                session=MONDAY,
                rate=rate,
                source="fixtures",
                published_at=datetime(2026, 10, 19, 14, 0, tzinfo=UTC),
            )
        )
    store.ingest(records, ingested_at=MONDAY_RUN - timedelta(minutes=30))


def test_a_close_is_exact_to_six_decimals_or_missing() -> None:
    assert exact(123.45) == Decimal("123.45")
    assert exact(0.000001) == Decimal("0.000001")
    assert exact(1.2345678) is None  # never rounded into a price


def test_the_age_of_a_close_counts_the_sessions_closed_since() -> None:
    assert sessions_since("XPAR", MONDAY, MONDAY_RUN) == 0
    assert sessions_since("XPAR", MONDAY, run_at(TUESDAY)) == 1
    assert sessions_since("XPAR", date(2026, 10, 16), MONDAY_RUN) == 1  # Friday, then Monday
    with pytest.raises(MarketError, match="calendrier inconnu"):
        sessions_since("ZZZZ", MONDAY, MONDAY_RUN)


def test_the_age_of_a_rate_counts_target_days_up_to_the_day() -> None:
    assert target_days_since(MONDAY, MONDAY) == 0
    assert target_days_since(date(2026, 10, 16), MONDAY) == 1  # the weekend is no TARGET day
    assert target_days_since(date(2026, 12, 24), date(2026, 12, 28)) == 1  # 25 and 26 closed


def test_the_simulator_reads_a_close_only_once_ingested(store: FinanceStore) -> None:
    ingest(store, TUESDAY, 100.2)
    assert StoreMarket(store, as_of=MONDAY_RUN).bar(SYMBOL, TUESDAY) is None
    later = StoreMarket(store, as_of=run_at(TUESDAY)).bar(SYMBOL, TUESDAY)
    assert later is not None and later.close == Decimal("100.2")


def test_the_facts_of_a_euro_instrument(store: FinanceStore) -> None:
    facts = market_facts(store, [SYMBOL], as_of=MONDAY_RUN, volume_sessions=20)
    assert facts.gaps == {}
    assert facts.open_markets == frozenset({"XPAR"})
    quote = facts.quotes[SYMBOL]
    assert (quote.price, quote.session, quote.sessions_old) == (Decimal("100"), MONDAY, 0)
    assert facts.volumes[SYMBOL].shares == Decimal(200_000)


def test_each_missing_fact_is_named_never_guessed(store: FinanceStore) -> None:
    facts = market_facts(store, [SYMBOL, "FICT-NONE"], as_of=MONDAY_RUN, volume_sessions=60)
    assert facts.gaps["FICT-NONE"] == "absent du référentiel"
    assert "volume inconnu" in facts.gaps[SYMBOL]
    assert SYMBOL in facts.quotes and SYMBOL not in facts.volumes
    marked = market_facts(store, [SYMBOL], as_of=MONDAY_RUN, volume_sessions="A_DEFINIR")
    assert marked.gaps[SYMBOL] == "avg_volume_sessions vaut A_DEFINIR (R7)"
    before = market_facts(store, [SYMBOL], as_of=LOADED - timedelta(minutes=1), volume_sessions=20)
    assert before.gaps[SYMBOL] == "aucun dernier cours exploitable"  # nothing ingested yet


def test_a_foreign_rate_is_inverted_on_the_cautious_side(store: FinanceStore) -> None:
    add_usd(store, 1.1)
    facts = market_facts(store, ["FICT-USD"], as_of=MONDAY_RUN, volume_sessions=1)
    rate = facts.fx["USD"]
    assert rate.eur_per_unit == Decimal("0.909091")  # 1 / 1.1 = 0.9090909…, rounded up
    assert rate.sessions_old == 0


def test_a_foreign_instrument_without_a_rate_is_a_gap(store: FinanceStore) -> None:
    add_usd(store, None)
    facts = market_facts(store, ["FICT-USD"], as_of=MONDAY_RUN, volume_sessions=1)
    assert facts.gaps["USD"] == "aucun taux BCE exploitable"
    assert "USD" not in facts.fx


def test_the_snapshot_counts_what_the_book_committed(store: FinanceStore) -> None:
    facts = market_facts(store, [SYMBOL], as_of=MONDAY_RUN, volume_sessions=20)
    book = OrderBook.memory(Recorder(MemoryJournal(), "policy", "market-test"))
    sent, proposed = make_intent(0), make_intent(1)
    for intent in (sent, proposed):
        book.record_intent(intent, decision_price=Decimal("100"), reason="rédigée", now=LOADED)
    for state in (OrderState.VALIDEE, OrderState.ENVOYEE):
        book.transition(sent.intent_id, state, reason="envoyée", now=LOADED)
    statement = AccountStatement(cash_eur=Decimal("10000"), positions={SYMBOL: 0}, cursor=0)
    snapshot = gate_snapshot(facts, account=ACCOUNT, statement=statement, book=book, open_gaps=2)
    assert snapshot.holdings == {}
    assert [order.remaining for order in snapshot.open_orders] == [sent.quantity]
    # Both were created on 17 October: neither counts today, the proposal never counts.
    assert (snapshot.orders_today, snapshot.orders_last_hour) == (0, 0)
    assert snapshot.seen_intent_ids == {sent.intent_id, proposed.intent_id}
    assert snapshot.open_reconciliation_gaps == 2
