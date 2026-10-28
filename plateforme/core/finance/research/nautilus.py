"""The NautilusTrader adapter: the same strategy replayed by a third-party engine (ADR-024, D12).

This is the only module that imports ``nautilus_trader``. A cross-check replays a strategy in
NautilusTrader with the in-house conventions, then compares trades and final value with
``engine.run``: two independent accountings of one decision sequence.

- one ``Equity`` per instrument (whole shares) on a simulated venue ``SIM``, netting book, cash
  account in EUR without borrowing;
- one daily bar per session, O = H = L = C = the final close, stamped one second before the
  decision cut-off of its session, with a volume no order can exhaust;
- a time alert at each decision cut-off: the strategy decides on its PointInTimeView with the
  cash and positions of the NautilusTrader account, and ``target_orders`` sizes the orders;
- at the next session, once every instrument's bar is in, the common scheduler (``schedule``)
  turns them into market orders, sells first, filled at that close;
- a fee model returns slippage plus commission of ``Costs.fill``, rounded to the cent.

The pre-trade balance check of NautilusTrader cannot price a market order without a quote or a
trade tick: with bars only, it lets every order through, and the cash account refuses any fill
that would overdraw it (``AccountError``), which this adapter reports as a failure.

Scope (ADR-024): EUR instruments on one calendar, no corporate action effective inside the
window, costs rounded to the cent. Anything else is refused, never approximated.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from typing import Any, Literal

import nautilus_trader
import numpy as np
import pandas as pd
from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.backtest.models import FeeModel
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
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.trading.strategy import Strategy as NautilusStrategy

from core.finance.research.engine import BacktestError, BacktestResult, common_calendar
from core.finance.research.execution import Costs, Cut, Order, schedule, target_orders
from core.finance.research.strategy import Params, Strategy, StrategyError, checked_weights
from core.finance.research.view import MarketHistory, decision_time

ENGINE = f"NautilusTrader {nautilus_trader.__version__}"
VENUE = Venue("SIM")
BAR_VOLUME = 10**10  # shares per bar, under QUANTITY_MAX: no backtest order comes near it
MAX_PRICE_DECIMALS = 9
BAR_LEAD = timedelta(seconds=1)  # a session's bar is stamped this long before its cut-off


@dataclass(frozen=True)
class NautilusTrade:
    """A fill reported by NautilusTrader: the price and the fees it booked."""

    decided: date
    executed: date
    instrument_id: str
    quantity: int  # > 0 bought, < 0 sold
    price: float
    fees: float  # slippage + commission, as the fee model returned them


@dataclass(frozen=True)
class NautilusResult:
    strategy: str
    params: dict[str, int | float | str | bool]
    costs: Costs
    initial_cash: float
    values: pd.Series  # cash + Σ q·P at each close, from the NautilusTrader account
    cash: pd.Series
    positions: pd.DataFrame
    trades: tuple[NautilusTrade, ...]
    cuts: tuple[Cut, ...]

    @property
    def fees(self) -> float:
        return math.fsum(t.fees for t in self.trades)


@dataclass(frozen=True)
class CrossCheck:
    """D12: same trades, value curves within ``tolerance``, fees compared on their own."""

    engine: str
    trades: int
    trade_gaps: tuple[str, ...]  # every mismatch of date, instrument, side, quantity or price
    final_value: float  # in-house engine
    other_final_value: float
    relative_gap: float  # the largest |V' − V| / V over the sessions
    worst_session: date
    fees: float
    other_fees: float
    tolerance: float

    @property
    def fees_gap(self) -> float:
        return self.other_fees - self.fees

    @property
    def passed(self) -> bool:
        return not self.trade_gaps and self.relative_gap <= self.tolerance


def _price_decimals(closes: np.ndarray) -> int:
    """The fewest decimals that write every close exactly; refused beyond nine."""
    for decimals in range(MAX_PRICE_DECIMALS + 1):
        if all(round(float(c), decimals) == float(c) for c in closes.ravel()):
            return decimals
    raise BacktestError(
        f"cours à plus de {MAX_PRICE_DECIMALS} décimales : non représentables dans "
        "NautilusTrader sans arrondi (ADR-024)"
    )


def _refuse_out_of_scope(history: MarketHistory, sessions: list[date], costs: Costs) -> None:
    for instrument_id in history.instruments:
        for event in history.events(instrument_id):
            if sessions[0] < event.action.ex_date <= sessions[-1]:
                raise BacktestError(
                    f"{instrument_id} : opération sur titre du {event.action.ex_date} dans la "
                    "fenêtre ; le recoupement NautilusTrader porte sur des séries sans "
                    "dividende ni division (ADR-024)"
                )
    if costs.rounding != "cent":
        raise BacktestError(
            "NautilusTrader tient ses frais au centime : recoupement réservé à l'arrondi 'cent'"
        )


class _CostsFeeModel(FeeModel):
    """Slippage plus commission of ``Costs.fill``, booked as one NautilusTrader commission."""

    def __init__(self, costs: Costs, names: dict[InstrumentId, str]) -> None:
        super().__init__()
        self._costs, self._names = costs, names

    def get_commission(
        self, order: Any, fill_qty: Quantity, fill_px: Price, instrument: Any
    ) -> Money:
        side = 1 if order.side == OrderSide.BUY else -1
        quantity = side * int(fill_qty.as_double())
        fill = self._costs.fill(self._names[instrument.id], quantity, fill_px.as_double())
        return Money(fill.fees, EUR)


@dataclass
class _Replay:
    """The state of one replay, shared by the NautilusTrader callbacks."""

    strategy: Strategy
    params: Params
    history: MarketHistory
    cutoff: time
    costs: Costs
    sessions: list[date]
    ids: dict[str, InstrumentId]
    values: np.ndarray
    cash: np.ndarray
    positions: np.ndarray
    session: int = -1  # the session whose bars arrive, then whose decision runs
    seen: int = 0  # bars of that session already in
    prices: dict[str, float] = field(default_factory=dict)
    pending: list[Order] = field(default_factory=list)
    submitted: int = 0
    trades: list[NautilusTrade] = field(default_factory=list)
    cuts: list[Cut] = field(default_factory=list)
    error: BaseException | None = None


class _Runner(NautilusStrategy):
    """Feeds the decisions of ``strategy`` to NautilusTrader; every error is kept for later.

    An exception raised inside a NautilusTrader callback may be logged and swallowed by the
    engine, so each callback stores it and the adapter raises it once the run is over.
    """

    def __init__(self, replay: _Replay, bar_types: list[BarType]) -> None:
        super().__init__(StrategyConfig(strategy_id="CERVEAU-001"))
        self._replay, self._bar_types = replay, bar_types
        self._names = {v: k for k, v in replay.ids.items()}

    def _guarded(self, step: Callable[[], None]) -> None:
        if self._replay.error is not None:
            return
        try:
            step()
        except Exception as error:  # kept and raised after the run, see the class docstring
            self._replay.error = error

    def on_start(self) -> None:
        for bar_type in self._bar_types:
            self.subscribe_bars(bar_type)
        for k, day in enumerate(self._replay.sessions):
            self.clock.set_time_alert(
                f"decision-{k}", decision_time(day, self._replay.cutoff), self._on_decision
            )

    def on_bar(self, bar: Bar) -> None:
        self._guarded(lambda: self._bar(bar))

    def on_order_filled(self, event: Any) -> None:
        self._guarded(lambda: self._filled(event))

    def on_order_denied(self, event: Any) -> None:
        self._guarded(lambda: self._refused("refusé par le contrôle pré-négociation", event))

    def on_order_rejected(self, event: Any) -> None:
        self._guarded(lambda: self._refused("rejeté par la plateforme simulée", event))

    def _on_decision(self, event: Any) -> None:
        self._guarded(self._decide)

    def _bar(self, bar: Bar) -> None:
        replay = self._replay
        if replay.seen == 0:
            replay.session += 1
            replay.prices = {}
        replay.prices[self._names[bar.bar_type.instrument_id]] = bar.close.as_double()
        replay.seen += 1
        if replay.seen < len(replay.ids):
            return
        replay.seen = 0
        if not replay.pending:
            return
        done = schedule(replay.pending, self._cash(), replay.prices, replay.costs)
        replay.cuts.extend(done.cuts)
        replay.pending = []
        for fill in done.fills:
            side = OrderSide.BUY if fill.quantity > 0 else OrderSide.SELL
            order = self.order_factory.market(
                replay.ids[fill.instrument_id], side, Quantity.from_int(abs(fill.quantity))
            )
            self.submit_order(order)
            replay.submitted += 1

    def _filled(self, event: Any) -> None:
        replay = self._replay
        side = 1 if event.order_side == OrderSide.BUY else -1
        k = replay.session
        replay.trades.append(
            NautilusTrade(
                decided=replay.sessions[k - 1],
                executed=replay.sessions[k],
                instrument_id=self._names[event.instrument_id],
                quantity=side * int(event.last_qty.as_double()),
                price=event.last_px.as_double(),
                fees=event.commission.as_double(),
            )
        )

    def _refused(self, what: str, event: Any) -> None:
        raise BacktestError(f"ordre {event.client_order_id} {what} : {event.reason}")

    def _cash(self) -> float:
        return float(self.portfolio.account(VENUE).balance_total(EUR).as_double())

    def _held(self) -> dict[str, int]:
        held: dict[str, int] = {}
        for name, instrument_id in self._replay.ids.items():
            net = self.portfolio.net_position(instrument_id)
            if net != int(net):
                raise BacktestError(f"{name} : position fractionnaire {net} dans NautilusTrader")
            held[name] = int(net)
        return held

    def _decide(self) -> None:
        replay = self._replay
        k = replay.session
        if k < 0 or replay.seen:
            raise BacktestError("alerte de décision avant la clôture de sa séance")
        day = replay.sessions[k]
        cash, held = self._cash(), self._held()
        invested = math.fsum(held[i] * replay.prices[i] for i in held)
        replay.values[k], replay.cash[k] = cash + invested, cash
        replay.positions[k] = [held[i] for i in replay.history.instruments]
        if k == len(replay.sessions) - 1:
            return
        view = replay.history.view(day, replay.cutoff)
        instruments = replay.history.instruments
        weights = checked_weights(replay.strategy.decide(view, replay.params), instruments, day)
        known: dict[str, float] = {}
        for instrument_id in instruments:
            if not weights.get(instrument_id) and not held[instrument_id]:
                continue
            last = view.last_close(instrument_id)
            if last is None:
                raise StrategyError(
                    f"décision du {day} : poids sur {instrument_id} sans aucun cours connu"
                )
            known[instrument_id] = last[1]  # no split inside the window: nothing to adjust
        value = cash + math.fsum(held[i] * known[i] for i in known)
        replay.pending = target_orders(weights, held, known, value)


def _bar_type(instrument_id: InstrumentId) -> BarType:
    specification = BarSpecification(1, BarAggregation.DAY, PriceType.LAST)
    return BarType(instrument_id, specification, AggregationSource.EXTERNAL)


def run(
    strategy: Strategy,
    params: Params,
    history: MarketHistory,
    *,
    start: date,
    end: date,
    cutoff: time,
    costs: Costs,
    initial_cash: float,
) -> NautilusResult:
    """Replay ``strategy`` in NautilusTrader with the arguments of ``engine.run``.

    LookAheadError and StrategyError propagate as in the in-house engine; BacktestError reports
    what NautilusTrader refused (an overdraft, a denied or rejected order, a lost fill).
    """
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise BacktestError("le cash initial doit être positif")
    sessions, closes = common_calendar(history, start, end)
    _refuse_out_of_scope(history, sessions, costs)
    decimals = _price_decimals(closes)
    instruments = history.instruments
    ids = {name: InstrumentId(Symbol(name), VENUE) for name in instruments}
    count = len(sessions)
    replay = _Replay(
        strategy=strategy,
        params=params,
        history=history,
        cutoff=cutoff,
        costs=costs,
        sessions=sessions,
        ids=ids,
        values=np.full(count, np.nan),
        cash=np.full(count, np.nan),
        positions=np.zeros((count, len(instruments)), dtype=np.int64),
    )
    stamps = [decision_time(day, cutoff) - BAR_LEAD for day in sessions]
    engine = BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True)))
    try:
        engine.add_venue(
            venue=VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            starting_balances=[Money(initial_cash, EUR)],
            base_currency=EUR,
            fee_model=_CostsFeeModel(costs, {v: k for k, v in ids.items()}),
        )
        bar_types = []
        for column, name in enumerate(instruments):
            engine.add_instrument(
                Equity(
                    instrument_id=ids[name],
                    raw_symbol=Symbol(name),
                    currency=EUR,
                    price_precision=decimals,
                    price_increment=Price(10.0**-decimals, decimals),
                    lot_size=Quantity.from_int(1),
                    ts_event=0,
                    ts_init=0,
                )
            )
            bar_type = _bar_type(ids[name])
            bar_types.append(bar_type)
            bars = []
            for k, stamp in enumerate(stamps):
                price = Price(float(closes[k, column]), decimals)
                ns = int(pd.Timestamp(stamp).value)
                bars.append(
                    Bar(bar_type, price, price, price, price, Quantity.from_int(BAR_VOLUME), ns, ns)
                )
            engine.add_data(bars)
        engine.add_strategy(_Runner(replay, bar_types))
        engine.run(end=decision_time(sessions[-1], cutoff) + BAR_LEAD)
    finally:
        engine.dispose()
    if replay.error is not None:
        raise replay.error
    if len(replay.trades) != replay.submitted or np.isnan(replay.values).any():
        raise BacktestError(
            f"{ENGINE} : {replay.submitted} ordres soumis, {len(replay.trades)} exécutés ; "
            "le compte a sans doute refusé un découvert (AccountError)"
        )
    index = pd.DatetimeIndex(np.array(sessions, dtype="datetime64[D]"))
    return NautilusResult(
        strategy=strategy.name,
        params=dict(params),
        costs=costs,
        initial_cash=float(initial_cash),
        values=pd.Series(replay.values, index=index, name="valeur"),
        cash=pd.Series(replay.cash, index=index, name="liquidites"),
        positions=pd.DataFrame(replay.positions, index=index, columns=list(instruments)),
        trades=tuple(replay.trades),
        cuts=tuple(replay.cuts),
    )


Side = Literal["achat", "vente"]


def _key(executed: date, instrument_id: str, quantity: int) -> tuple[date, str, Side, int]:
    return executed, instrument_id, "achat" if quantity > 0 else "vente", abs(quantity)


def cross_check(reference: BacktestResult, other: NautilusResult, tolerance: float) -> CrossCheck:
    """Compare a NautilusTrader replay with the in-house run of the same strategy (D12)."""
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("une tolérance de recoupement est un réel strictement positif")
    if (reference.strategy, reference.params, reference.costs, reference.initial_cash) != (
        other.strategy,
        other.params,
        other.costs,
        other.initial_cash,
    ):
        raise ValueError("recoupement de deux exécutions qui n'ont pas les mêmes entrées")
    if not reference.values.index.equals(other.values.index):
        raise ValueError("recoupement de deux exécutions sur des séances différentes")
    gaps: list[str] = []
    ours = [
        (t.executed, t.fill.instrument_id, t.fill.quantity, t.fill.price) for t in reference.trades
    ]
    theirs = [(t.executed, t.instrument_id, t.quantity, t.price) for t in other.trades]
    for n, (mine, its) in enumerate(zip(ours, theirs, strict=False)):
        if _key(*mine[:3]) != _key(*its[:3]) or mine[3] != its[3]:
            gaps.append(
                f"exécution n° {n + 1} : moteur maison {_key(*mine[:3])} à {mine[3]}, "
                f"{ENGINE} {_key(*its[:3])} à {its[3]}"
            )
    if len(ours) != len(theirs):
        gaps.append(f"{len(ours)} exécutions dans le moteur maison, {len(theirs)} dans {ENGINE}")
    final, other_final = float(reference.values.iloc[-1]), float(other.values.iloc[-1])
    gaps_by_session = ((other.values - reference.values).abs() / reference.values.abs()).to_numpy()
    worst = int(np.argmax(gaps_by_session))
    return CrossCheck(
        engine=ENGINE,
        trades=len(ours),
        trade_gaps=tuple(gaps),
        final_value=final,
        other_final_value=other_final,
        relative_gap=float(gaps_by_session[worst]),
        worst_session=reference.values.index[worst].date(),
        fees=reference.fees,
        other_fees=other.fees,
        tolerance=tolerance,
    )
