"""Paper fills replayed in NautilusTrader with its native commission model (ADR-033, B154).

Each fill of the paper simulator becomes one bar at the fill price and one market order in a
NautilusTrader backtest: a cash account in euros opened with the capital, NautilusTrader's own
``MakerTakerFeeModel`` at the taker rate ``commission_pct``, raised to the minimum per order by a
thin subclass. NautilusTrader books its own commissions, cash and positions; they are compared
with the simulator's account, so a fee, cash or position error of the simulator shows, and so
does a fill the cash does not cover, which NautilusTrader leaves unfilled. The fill prices and
quantities are the simulator's: the exact oracle of ``test_execution_paper`` checks them.

``Money`` of NautilusTrader rounds ``float(value) * 100`` to the nearest integer: an exact half
cent such as 1.005 € may become 1.00 €, where the simulator rounds the exact decimal half up
(1.01 €). That gap is predicted fill by fill, never tolerated in bulk.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.backtest.models import MakerTakerFeeModel
from nautilus_trader.config import LoggingConfig, StrategyConfig
from nautilus_trader.model.currencies import EUR
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import (
    AccountType,
    AggregationSource,
    BarAggregation,
    OmsType,
    OrderSide,
    PriceType,
)
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.objects import MONEY_MAX as NAUTILUS_MONEY_MAX
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.trading.strategy import Strategy

from core.execution.book import Fill
from core.execution.intent import OrderIntent
from core.execution.paper import MONEY_MAX, PaperCosts, PaperSettings, PaperSimulator
from core.finance.model import PARIS
from tests.execution_cases import SESSION, make_intent
from tests.test_execution_paper import (
    CAPITAL,
    CLOSED,
    OPENED,
    SETTINGS,
    SUBMITTED,
    TUESDAY,
    Market,
    bar,
    sell,
    simulator,
    tuesday,
    weekdays,
)

VENUE = Venue("SIM")
CENT = Decimal("0.01")
BAR_VOLUME = 10**10  # no replayed order comes near it


class _MinimumFeeModel(MakerTakerFeeModel):
    """NautilusTrader's taker commission on the notional, raised to the minimum per order."""

    def __init__(self, minimum: Decimal) -> None:
        super().__init__()
        self._minimum = Money(minimum, EUR)

    def get_commission(self, order: Any, fill_qty: Any, fill_px: Any, instrument: Any) -> Money:
        native = super().get_commission(order, fill_qty, fill_px, instrument)
        return native if native.as_decimal() >= self._minimum.as_decimal() else self._minimum


@dataclass
class Replayed:
    """What NautilusTrader booked: per fill its price and commission, then the account."""

    prices: list[Decimal] = field(default_factory=list)
    commissions: list[Decimal] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cash: Decimal = Decimal(0)
    positions: dict[str, int] = field(default_factory=dict)


class _Replayer(Strategy):
    """Sends, on each bar, the market order of the paper fill the bar stands for."""

    def __init__(
        self, orders: dict[int, tuple[InstrumentId, OrderSide, int]], bar_types: list[BarType]
    ) -> None:
        super().__init__(StrategyConfig(strategy_id="CERVEAU-002"))
        self._orders, self._bar_types = orders, bar_types
        self.replayed = Replayed()

    def on_start(self) -> None:
        for bar_type in self._bar_types:
            self.subscribe_bars(bar_type)

    def on_bar(self, bar: Bar) -> None:
        instrument_id, side, quantity = self._orders[bar.ts_event]
        order = self.order_factory.market(instrument_id, side, Quantity.from_int(quantity))
        self.submit_order(order)

    def on_order_filled(self, event: Any) -> None:
        self.replayed.prices.append(event.last_px.as_decimal())
        self.replayed.commissions.append(event.commission.as_decimal())

    def on_order_denied(self, event: Any) -> None:
        self.replayed.errors.append(f"refusé : {event.reason}")

    def on_order_rejected(self, event: Any) -> None:
        self.replayed.errors.append(f"rejeté : {event.reason}")


def replay(
    fills: Sequence[Fill], intents: dict[Any, OrderIntent], paper: PaperSettings
) -> Replayed:
    """Replay ``fills`` in order in a NautilusTrader cash account opened with the capital."""
    if not fills:
        return Replayed(cash=paper.capital_eur)
    symbols = sorted({intents[f.intent_id].instrument.symbol for f in fills})
    ids = {s: InstrumentId(Symbol(s), VENUE) for s in symbols}
    bar_types = {
        s: BarType(
            ids[s],
            BarSpecification(1, BarAggregation.DAY, PriceType.LAST),
            AggregationSource.EXTERNAL,
        )
        for s in symbols
    }
    engine = BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True)))
    try:
        engine.add_venue(
            venue=VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            starting_balances=[Money(paper.capital_eur, EUR)],
            base_currency=EUR,
            fee_model=_MinimumFeeModel(paper.costs.min_commission_eur),
        )
        for s in symbols:
            engine.add_instrument(
                Equity(
                    instrument_id=ids[s],
                    raw_symbol=Symbol(s),
                    currency=EUR,
                    price_precision=2,
                    price_increment=Price.from_str("0.01"),
                    lot_size=Quantity.from_int(1),
                    ts_event=0,
                    ts_init=0,
                    maker_fee=paper.costs.commission_pct / 100,
                    taker_fee=paper.costs.commission_pct / 100,
                )
            )
        orders: dict[int, tuple[InstrumentId, OrderSide, int]] = {}
        bars = []
        for n, fill in enumerate(fills):
            intent = intents[fill.intent_id]
            symbol = intent.instrument.symbol
            # One microsecond apart, in the simulator's order: sells before buys in a session.
            ns = int(pd.Timestamp(fill.executed_at).value) + n * 1_000
            side = OrderSide.BUY if intent.side == "BUY" else OrderSide.SELL
            orders[ns] = (ids[symbol], side, fill.quantity)
            price = Price.from_str(str(fill.price))
            volume = Quantity.from_int(BAR_VOLUME)
            bars.append(Bar(bar_types[symbol], price, price, price, price, volume, ns, ns))
        engine.add_data(bars)
        runner = _Replayer(orders, list(bar_types.values()))
        engine.add_strategy(runner)
        engine.run(end=fills[-1].executed_at + timedelta(seconds=1))
        account = engine.portfolio.account(VENUE)
        runner.replayed.cash = account.balance_total(EUR).as_decimal()
        for s in symbols:
            net = engine.portfolio.net_position(ids[s])
            if net:
                runner.replayed.positions[s] = int(net)
    finally:
        engine.dispose()
    return runner.replayed


def float_cents(value: Decimal) -> Decimal:
    """``value`` to the cent as ``Money`` stores it: the float times 100, rounded half away."""
    return Decimal(float(value) * 100).quantize(Decimal(1), ROUND_HALF_UP) / 100


def assert_agrees(sim: PaperSimulator, intents: dict[Any, OrderIntent]) -> list[Fill]:
    """NautilusTrader books every fill of ``sim`` like the simulator, to the predicted cent."""
    fills = list(sim.fills_since(0).fills)
    statement = sim.account_snapshot()
    theirs = replay(fills, intents, sim.settings)
    assert theirs.errors == []
    assert theirs.prices == [f.price for f in fills]
    costs = sim.settings.costs
    gaps = Decimal(0)
    for fill, commission in zip(fills, theirs.commissions, strict=True):
        exact = fill.quantity * fill.price * costs.commission_pct / 100
        expected = max(costs.min_commission_eur, float_cents(exact))
        assert commission == expected
        assert fill.fees == max(costs.min_commission_eur, exact.quantize(CENT, ROUND_HALF_UP))
        gap = fill.fees - commission
        assert gap in (0, CENT)
        if gap:
            assert exact % CENT == CENT / 2  # an exact half cent, and nothing else
        gaps += gap
    assert theirs.cash == statement.cash_eur + gaps
    assert theirs.positions == statement.positions
    return fills


# Fixed cases ------------------------------------------------------------------------------------


def test_nautilus_books_a_buy_and_a_partial_sell_like_the_simulator() -> None:
    sim = simulator()
    buy = make_intent(0, quantity=40)
    assert sim.submit(buy, now=SUBMITTED).accepted
    sim.close_session(SESSION, Market(bar()), now=CLOSED)
    out = sell(1, quantity=30, limit_price=Decimal("120.00"))
    assert sim.submit(out, now=CLOSED + timedelta(hours=1)).accepted
    sim.close_session(TUESDAY, Market(tuesday(volume=400)), now=CLOSED + timedelta(days=1))
    fills = assert_agrees(sim, {buy.intent_id: buy, out.intent_id: out})
    assert [f.quantity for f in fills] == [40, 20]  # 5 % of 400 on Tuesday
    assert [f.fees for f in fills] == [Decimal("4.92"), Decimal("2.46")]  # 4 922.80 and 2 458.60


def test_a_half_cent_commission_is_the_one_predicted_gap() -> None:
    # 201.00 € at 0.5 % is exactly 1.005 €: 1.01 € in the simulator, 1.00 € in NautilusTrader,
    # whose float 1.005 times 100 is 100.49999999999999.
    costs = PaperCosts(Decimal("0.5"), Decimal("0.50"), Decimal(0))
    sim = PaperSimulator.memory(
        PaperSettings(CAPITAL, costs, Decimal(5)), now=OPENED, sessions=weekdays
    )
    buy = make_intent(0, quantity=1, limit_price=Decimal("201.00"))
    assert sim.submit(buy, now=SUBMITTED).accepted
    sim.close_session(SESSION, Market(bar(close=Decimal("201.00"))), now=CLOSED)
    (fill,) = assert_agrees(sim, {buy.intent_id: buy})
    assert fill.fees == Decimal("1.01")
    assert float_cents(Decimal("1.005")) == Decimal("1.00")
    assert float_cents(Decimal("5.025")) == Decimal("5.03")  # not every half cent loses one


def test_nautilus_leaves_unfilled_what_the_cash_does_not_cover() -> None:
    sim = simulator()
    buy = make_intent(0, quantity=40)
    assert sim.submit(buy, now=SUBMITTED).accepted
    sim.close_session(SESSION, Market(bar()), now=CLOSED)
    fills = sim.fills_since(0).fills
    assert fills
    poor = PaperSettings(Decimal("100.00"), SETTINGS.costs, SETTINGS.participation_pct)
    theirs = replay(fills, {buy.intent_id: buy}, poor)
    assert (theirs.prices, theirs.cash, theirs.positions) == ([], Decimal("100.00"), {})


def test_the_simulator_refuses_what_nautilus_cannot_hold() -> None:
    """B122: NautilusTrader refuses a Money above MONEY_MAX; the simulator says so first."""
    assert Decimal(NAUTILUS_MONEY_MAX) == MONEY_MAX
    assert Money(MONEY_MAX, EUR).as_decimal() == MONEY_MAX
    with pytest.raises(ValueError):  # its message reads "invalid format string" (1.231.0)
        Money(MONEY_MAX + 1, EUR)
    sim = simulator()
    huge = make_intent(0, quantity=92_233_721, limit_price=Decimal("100.00"))  # 9 223 372 100 €
    ack = sim.submit(huge, now=SUBMITTED)
    assert not ack.accepted
    assert ack.reason.startswith("montant au-delà de MONEY_MAX de NautilusTrader")


# Any small market -------------------------------------------------------------------------------

SYMBOLS = ("FICT-ACME", "FICT-BETA")
SESSIONS = (SESSION, TUESDAY, date(2026, 10, 21))
CLOSE = st.one_of(st.integers(50, 150).map(lambda euros: euros * 100), st.integers(5_000, 15_000))
VOLUME = st.integers(-500, 4_000).map(lambda v: None if v < 0 else v)  # None: no volume given
DAY = st.tuples(
    st.fixed_dictionaries({s: st.tuples(CLOSE, VOLUME) for s in SYMBOLS}),
    st.lists(
        st.tuples(
            st.sampled_from(SYMBOLS),
            st.sampled_from(["BUY", "SELL"]),
            st.integers(1, 60),
            st.integers(-200, 500),  # the limit, in cents from the coming close
        ),
        min_size=1,
        max_size=5,
    ),
)
COSTS = st.builds(
    PaperCosts,
    st.sampled_from([Decimal(0), Decimal("0.1"), Decimal("0.25"), Decimal("0.5")]),
    st.sampled_from([Decimal(0), Decimal("1.00"), Decimal("2.00")]),
    st.sampled_from([Decimal(0), Decimal(5), Decimal(10)]),
)


@settings(max_examples=50, deadline=None)
@given(COSTS, st.lists(DAY, min_size=3, max_size=3))
def test_nautilus_agrees_on_any_small_paper_account(
    costs: PaperCosts,
    days: list[tuple[dict[str, tuple[int, int | None]], list[tuple[str, str, int, int]]]],
) -> None:
    sim = PaperSimulator.memory(
        PaperSettings(CAPITAL, costs, SETTINGS.participation_pct), now=OPENED, sessions=weekdays
    )
    intents: dict[Any, OrderIntent] = {}
    decided = [datetime(2026, 10, 17, 18, 30, tzinfo=PARIS)]
    decided += [datetime(s.year, s.month, s.day, 18, 30, tzinfo=PARIS) for s in SESSIONS[:-1]]
    for (closes, orders), session, at in zip(days, SESSIONS, decided, strict=True):
        for symbol, side, quantity, offset in orders:
            intent = make_intent(
                len(intents),
                side=side,
                quantity=quantity,
                limit_price=Decimal(closes[symbol][0] + offset).scaleb(-2),
                created_at=at,
                decision_date=at.date(),
                instrument__symbol=symbol,
            )
            intents[intent.intent_id] = intent
            sim.submit(intent, now=at + timedelta(minutes=1))
        published = datetime(session.year, session.month, session.day, 17, 35, tzinfo=PARIS)
        bars = (
            bar(
                symbol=s,
                session=session,
                close=Decimal(close).scaleb(-2),
                volume=volume,
                published_at=published,
            )
            for s, (close, volume) in closes.items()
        )
        sim.close_session(session, Market(*bars), now=published + timedelta(minutes=25))
    assert_agrees(sim, intents)
