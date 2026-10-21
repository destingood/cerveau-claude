"""The in-house backtest engine and its execution model (ADR-024, D6)."""

from __future__ import annotations

import math
import random
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.config.loader import TradingCosts, load_config
from core.finance.fixtures import load_research, research_costs
from core.finance.model import CorporateAction, Instrument, PriceRow
from core.finance.performance import (
    annualized,
    chained,
    daily_returns,
    max_drawdown,
    sharpe,
    volatility,
)
from core.finance.research.engine import (
    BacktestError,
    BacktestResult,
    Credit,
    Trade,
    measures,
    run,
)
from core.finance.research.execution import (
    Costs,
    CostsError,
    Cut,
    Fill,
    Order,
    affordable,
    schedule,
    target_orders,
)
from core.finance.research.strategy import Params, StrategyError, Weights
from core.finance.research.view import LookAheadError, MarketHistory, PointInTimeView
from core.finance.store import FinanceStore

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"
CUTOFF = time(21, 0)
FREE = Costs("sans frais (test)", 0.0, 0.0, 0.0)
DAYS = [date(2024, 3, 4) + timedelta(days=n) for n in range(40)]


# Small markets ----------------------------------------------------------------------------------


def evening(day: date) -> datetime:
    return datetime.combine(day, time(17, 35), tzinfo=UTC)


def morning_after(day: date, hour: int = 7) -> datetime:
    return datetime.combine(day + timedelta(days=1), time(hour), tzinfo=UTC)


def close(
    instrument_id: str,
    day: date,
    value: float,
    published: datetime | None = None,
    currency: str = "EUR",
) -> PriceRow:
    return PriceRow(
        instrument_id=instrument_id,
        session=day,
        close=value,
        currency=currency,
        source="fixtures",
        published_at=published or evening(day),
    )


def closes(instrument_id: str, values: Sequence[float]) -> list[PriceRow]:
    return [close(instrument_id, day, value) for day, value in zip(DAYS, values, strict=False)]


def split(instrument_id: str, ex_date: date, ratio: float, published: datetime) -> CorporateAction:
    return CorporateAction(
        instrument_id=instrument_id,
        ex_date=ex_date,
        kind="split",
        value=ratio,
        source="fixtures",
        published_at=published,
    )


def dividend(
    instrument_id: str, ex_date: date, per_share: float, published: datetime
) -> CorporateAction:
    return CorporateAction(
        instrument_id=instrument_id,
        ex_date=ex_date,
        kind="dividend",
        value=per_share,
        currency="EUR",
        source="fixtures",
        published_at=published,
    )


def market(records: Sequence[PriceRow | CorporateAction]) -> MarketHistory:
    """A fresh store with these records, ingested in publication order, read back."""
    store = FinanceStore.memory()
    currencies = {r.instrument_id: r.currency for r in records if isinstance(r, PriceRow)}
    for instrument_id, currency in currencies.items():
        store.add_instrument(
            Instrument(
                instrument_id=instrument_id,
                valid_from=date(2000, 1, 1),
                name=f"{instrument_id} (fictif)",
                asset_class="equity",
                currency=currency,
                mic="XPAR",
                sector="Industrie",
                country="FR",
            ),
            recorded_at=datetime(2000, 1, 1, tzinfo=UTC),
        )
    ordered = sorted(records, key=lambda r: r.published_at)
    store.ingest(ordered, ingested_at=ordered[-1].published_at)
    history = MarketHistory.load(store, currencies)
    store.close()
    return history


@dataclass
class Script:
    """Weights by decision date; no entry means all cash."""

    plan: Mapping[date, Weights] = field(default_factory=dict)
    name: str = "script (test)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        return self.plan.get(view.day, {})


@dataclass
class Fixed:
    weights: Weights
    name: str = "poids fixes (test)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        return self.weights


def backtest(
    strategy: Script | Fixed,
    history: MarketHistory,
    sessions: int,
    *,
    costs: Costs = FREE,
    cash: float = 1000.0,
) -> BacktestResult:
    return run(
        strategy,
        {},
        history,
        start=DAYS[0],
        end=DAYS[sessions - 1],
        cutoff=CUTOFF,
        costs=costs,
        initial_cash=cash,
    )


def trades(result: BacktestResult) -> list[tuple[date, date, int, float]]:
    return [(t.decided, t.executed, t.fill.quantity, t.fill.price) for t in result.trades]


def held(result: BacktestResult, instrument_id: str = "FICT-A") -> list[int]:
    return result.positions[instrument_id].tolist()


# Costs ------------------------------------------------------------------------------------------


def test_unknown_costs_refuse_the_backtest() -> None:
    real = load_config(REPO_CONFIG).risk.trading_costs
    with pytest.raises(CostsError, match="commission_pct, fx_conversion_bps, min_commission_eur"):
        Costs.from_config(real, "frais du courtier")
    partial = TradingCosts(
        commission_pct=Decimal("0.1"),
        min_commission_eur=Decimal("2"),
        slippage_bps=Decimal("5"),
        fx_conversion_bps="A_VERIFIER",
    )
    with pytest.raises(CostsError, match="fx_conversion_bps à définir : backtest refusé"):
        Costs.from_config(partial, "frais du courtier")


def test_the_fictitious_costs_become_fractions() -> None:
    named = research_costs()
    costs = Costs.from_config(named.costs, named.name)
    assert (costs.name, costs.commission, costs.minimum, costs.slippage) == (
        "frais fictifs de démonstration",
        0.001,
        2.0,
        0.0005,
    )
    stressed = costs.stressed(2)
    assert (stressed.commission, stressed.minimum, stressed.slippage) == (0.002, 4.0, 0.001)
    assert stressed.name == "frais fictifs de démonstration × 2"
    with pytest.raises(CostsError):
        costs.stressed(0.5)
    with pytest.raises(CostsError):
        Costs("faux", -0.1, 0.0, 0.0)


def test_fees_follow_adr_024() -> None:
    costs = Costs("fictifs", 0.001, 2.0, 0.0005)
    # 120 × 50 = 6 000: slippage 3, commission 0.1 % of 6 000 × (1 ± 0.0005), to the cent.
    assert costs.fill("A", 120, 50.0) == Fill("A", 120, 50.0, 3.0, 6.0, -6009.0)
    assert costs.fill("A", -120, 50.0) == Fill("A", -120, 50.0, 3.0, 6.0, 5991.0)
    # The minimum commission, and the slippage rounded on its own.
    small = costs.fill("A", 3, 33.33)
    assert (small.slippage, small.commission) == (0.05, 2.0)
    assert small.cash == pytest.approx(-102.04, abs=1e-9)
    exact = Costs("fictifs", 0.001, 2.0, 0.0005, rounding="none").fill("A", 3000, 33.33)
    amount = Decimal(3000) * Decimal("33.33")
    assert exact.slippage == pytest.approx(float(amount * Decimal("0.0005")), abs=1e-9)
    assert exact.commission == pytest.approx(float(amount * Decimal("0.001000500")), abs=1e-9)
    assert exact.cash == pytest.approx(-float(amount) - exact.slippage - exact.commission)
    with pytest.raises(ValueError, match="quantité nulle"):
        costs.fill("A", 0, 50.0)


# Orders and the scheduler -------------------------------------------------------------------


def test_target_orders_never_pass_the_target() -> None:
    orders = target_orders(
        {"A": 1 / 3, "B": 0.1, "D": 0.0},
        {"A": 0, "B": 20, "C": 4, "D": 0},
        {"A": 7.0, "B": 7.0, "C": 50.0},
        1000.0,
    )
    # A: 333.33 / 7 = 47.6 → 47; B: 100 / 7 − 20 = −5.7 → −5; C: no weight, sold in full.
    assert [(o.instrument_id, o.quantity) for o in orders] == [("A", 47), ("B", -5), ("C", -4)]
    assert [o.gap for o in orders] == pytest.approx([1000 / 3, 100 - 140, -200])


def test_the_scheduler_sells_first_then_buys_by_gap() -> None:
    orders = [Order("B", 10, 300.0), Order("A", 5, 100.0), Order("C", -4, -80.0)]
    done = schedule(orders, 50.0, {"A": 20.0, "B": 30.0, "C": 20.0}, FREE)
    assert [(f.instrument_id, f.quantity) for f in done.fills] == [("C", -4), ("A", 5), ("B", 1)]
    assert done.cuts == [Cut(Order("B", 10, 300.0), 1)]
    assert done.cash == 0.0


def test_a_buy_is_cut_to_the_cash_fees_included() -> None:
    costs = Costs("fictifs", 0.001, 2.0, 0.0005)
    assert affordable(100, 10.0, 1000.0, costs) == 99
    assert affordable(100, 10.0, 1.0, costs) == 0
    done = schedule([Order("A", 100, 1000.0)], 1000.0, {"A": 10.0}, costs)
    assert [f.quantity for f in done.fills] == [99] and done.cash >= 0


def test_a_sell_whose_fees_exceed_the_cash_is_refused() -> None:
    heavy = Costs("lourds", 0.0, 10.0, 0.0)
    done = schedule([Order("A", -1, -5.0)], 0.0, {"A": 5.0}, heavy)
    assert (done.fills, done.cuts, done.cash) == ([], [Cut(Order("A", -1, -5.0), 0)], 0.0)
    done = schedule([Order("A", -1, -5.0)], 10.0, {"A": 5.0}, heavy)
    assert [f.cash for f in done.fills] == [-5.0] and done.cash == 5.0


@settings(max_examples=200, deadline=None)
@given(
    quantity=st.integers(1, 300),
    price=st.floats(0.5, 500, allow_nan=False),
    cash=st.floats(0, 50_000, allow_nan=False),
    commission=st.sampled_from([0.0, 0.001, 0.005]),
    minimum=st.sampled_from([0.0, 2.0, 9.9]),
    slippage=st.sampled_from([0.0, 0.0005, 0.002]),
    rounding=st.sampled_from(["cent", "none"]),
)
def test_affordable_is_the_largest_buy_the_cash_covers(
    quantity: int,
    price: float,
    cash: float,
    commission: float,
    minimum: float,
    slippage: float,
    rounding: str,
) -> None:
    costs = Costs("test", commission, minimum, slippage, rounding)  # type: ignore[arg-type]
    fits = [k for k in range(1, quantity + 1) if cash + costs.fill("A", k, price).cash >= 0]
    assert affordable(quantity, price, cash, costs) == max(fits, default=0)


# The daily loop -----------------------------------------------------------------------------


def test_a_decision_at_t_is_filled_at_the_close_of_t_plus_one() -> None:
    result = backtest(Fixed({"FICT-A": 1.0}), market(closes("FICT-A", [10, 11, 12, 13])), 4)
    # 100 shares wanted at 10; at 11 the cash buys 90.
    assert trades(result) == [(DAYS[0], DAYS[1], 90, 11.0)]
    assert result.cuts[0].cut == Cut(Order("FICT-A", 100, 1000.0), 90)
    assert result.values.tolist() == [1000.0, 1000.0, 1090.0, 1180.0]
    assert result.cash.tolist() == [1000.0, 10.0, 10.0, 10.0]
    assert held(result) == [0, 90, 90, 90]


def test_a_late_close_sizes_on_the_close_known_at_the_decision() -> None:
    rows = closes("FICT-A", [10, 20, 20, 20])
    rows[1] = close("FICT-A", DAYS[1], 20, morning_after(DAYS[1]))  # known the next morning
    result = backtest(Script({DAYS[1]: {"FICT-A": 0.5}}), market(rows), 4)
    # At the cut-off of DAYS[1] the last known close is 10: 500 / 10 = 50 shares, not 25.
    assert trades(result) == [(DAYS[1], DAYS[2], 50, 20.0), (DAYS[2], DAYS[3], -50, 20.0)]


def test_a_bad_print_is_decided_on_and_never_filled_at() -> None:
    rows = closes("FICT-A", [10, 20, 10, 10])
    rows.append(close("FICT-A", DAYS[1], 10, morning_after(DAYS[1], 9)))  # corrected
    result = backtest(Fixed({"FICT-A": 0.5}), market(rows), 4)
    # Filled and valued at 10; the decision of DAYS[1] saw 20 and sold 12 of 50 shares.
    assert trades(result) == [
        (DAYS[0], DAYS[1], 50, 10.0),
        (DAYS[1], DAYS[2], -12, 10.0),
        (DAYS[2], DAYS[3], 12, 10.0),
    ]
    assert result.values.tolist() == [1000.0] * 4


def test_a_split_changes_the_shares_and_pays_the_fraction() -> None:
    rows = closes("FICT-A", [30, 30, 20, 20])
    rows[2] = close("FICT-A", DAYS[2], 20, morning_after(DAYS[2]))  # late on the ex-date
    rows.append(split("FICT-A", DAYS[2], 1.5, evening(DAYS[0])))
    plan = {DAYS[0]: {"FICT-A": 0.35}, DAYS[1]: {"FICT-A": 0.65}, DAYS[2]: {"FICT-A": 0.65}}
    result = backtest(Script(plan), market(rows), 4)
    # DAYS[0]: 350 / 30 → 11. DAYS[1]: 650 / 30 − 11 → 10, scaled by the split to 15.
    # DAYS[2]: 11 × 1.5 = 16.5 → 16 shares and 0.5 × 20 € in cash; with the order, 31.
    # Its decision knows 30 (DAYS[1]), split-adjusted to 20: 650 / 20 − 31 → 1.
    assert held(result) == [0, 11, 31, 32]
    assert trades(result)[1:] == [(DAYS[1], DAYS[2], 15, 20.0), (DAYS[2], DAYS[3], 1, 20.0)]
    assert result.credits == (Credit("FICT-A", "cash_in_lieu", DAYS[2], 11, 10.0, DAYS[2]),)
    assert result.values.tolist() == [1000.0] * 4


def test_a_split_announced_after_the_decision_does_not_size_it() -> None:
    rows = closes("FICT-A", [30, 30, 20, 20])
    rows[2] = close("FICT-A", DAYS[2], 20, morning_after(DAYS[2]))
    rows.append(split("FICT-A", DAYS[2], 1.5, morning_after(DAYS[2], 6)))  # after the cut-off
    plan = {DAYS[0]: {"FICT-A": 0.35}, DAYS[1]: {"FICT-A": 0.65}, DAYS[2]: {"FICT-A": 0.65}}
    result = backtest(Script(plan), market(rows), 4)
    # The market splits on DAYS[2] all the same. Its decision knows neither the split nor the
    # close of DAYS[2]: 30 unadjusted, V = 380 + 31 × 30 = 1310, 0.65 × 1310 / 30 − 31 → −2 (B157).
    assert held(result) == [0, 11, 31, 29]
    assert trades(result)[2] == (DAYS[2], DAYS[3], -2, 20.0)


def test_a_dividend_announced_after_the_close_does_not_fund_the_fills() -> None:
    rows: list[PriceRow | CorporateAction] = [*closes("FICT-A", [10, 10, 10.5, 10.5])]
    after_close = datetime.combine(DAYS[2], time(19), tzinfo=UTC)  # before the cut-off
    rows.append(dividend("FICT-A", DAYS[2], 0.5, after_close))
    result = backtest(Script({DAYS[0]: {"FICT-A": 0.5}, DAYS[1]: {"FICT-A": 1.0}}), market(rows), 4)
    # 50 more shares wanted at 10.5 with 500 € of cash: 47. The 25 € come after the fills (B158).
    assert trades(result)[1] == (DAYS[1], DAYS[2], 47, 10.5)
    assert [(c.quantity, c.amount, c.credited) for c in result.credits] == [(50, 25.0, DAYS[2])]
    assert result.cash.iloc[2] == pytest.approx(500 - 47 * 10.5 + 25)


def test_a_dividend_is_paid_at_its_ex_date_or_once_announced() -> None:
    rows: list[PriceRow | CorporateAction] = [*closes("FICT-A", [10] * 6)]
    rows += [
        dividend("FICT-A", DAYS[2], 0.5, evening(DAYS[0])),
        dividend("FICT-A", DAYS[3], 0.5, datetime.combine(DAYS[4], time(10), tzinfo=UTC)),
        dividend("FICT-A", DAYS[5], 0.5, morning_after(DAYS[5])),
    ]
    result = backtest(Script({DAYS[0]: {"FICT-A": 0.5}, DAYS[1]: {"FICT-A": 0.5}}), market(rows), 6)
    # Sold at the close of DAYS[3], its ex-date: the shares held at its start keep the right.
    assert held(result) == [0, 50, 50, 0, 0, 0]
    assert [(c.ex_date, c.quantity, c.credited) for c in result.credits] == [
        (DAYS[2], 50, DAYS[2]),
        (DAYS[3], 50, DAYS[4]),
    ]
    later = backtest(Fixed({"FICT-A": 0.5}), market(rows), 6)
    assert [(c.ex_date, c.quantity, c.amount, c.credited) for c in later.credits] == [
        (DAYS[2], 50, 25.0, DAYS[2]),
        (DAYS[3], 50, 25.0, DAYS[4]),  # announced the morning of DAYS[4]
        (DAYS[5], 51, 25.5, None),  # announced after the window: never paid
    ]
    assert later.cash.iloc[2] - later.cash.iloc[1] == 25.0


def test_the_engine_refuses_foreign_currencies_and_mismatched_calendars() -> None:
    usd = market([*closes("FICT-A", [10, 10, 10]), close("FICT-U", DAYS[0], 5, currency="USD")])
    with pytest.raises(BacktestError, match="seul l'EUR"):
        backtest(Fixed({}), usd, 3)
    gaps = market([*closes("FICT-A", [10, 10, 10]), *closes("FICT-B", [10, 10])])
    with pytest.raises(BacktestError, match="calendrier commun"):
        backtest(Fixed({}), gaps, 3)
    with pytest.raises(BacktestError, match="cash initial"):
        backtest(Fixed({}), market(closes("FICT-A", [10, 10])), 2, cash=0.0)


@pytest.mark.parametrize(
    ("weights", "message"),
    [
        ({"FICT-A": 1.2}, "pas de levier"),
        ({"FICT-A": -0.1}, "ni découvert"),
        ({"FICT-A": math.nan}, "ni découvert"),
        ({"FICT-A": True}, "non numérique"),
        ({"FICT-Z": 0.1}, "hors de l'univers"),
        ([("FICT-A", 0.5)], "dictionnaire"),
        ({"FICT-B": 0.5}, "sans aucun cours connu"),
    ],
)
def test_a_strategy_breaking_its_contract_stops_the_backtest(weights: object, message: str) -> None:
    rows = [*closes("FICT-A", [10, 10, 10]), *closes("FICT-B", [10, 10, 10])]
    rows[3] = close("FICT-B", DAYS[0], 10, morning_after(DAYS[0]))  # unknown at DAYS[0]
    with pytest.raises(StrategyError, match=message):
        backtest(Fixed(weights), market(rows), 3)  # type: ignore[arg-type]


def test_a_strategy_reading_the_future_stops_the_backtest() -> None:
    class Peeking:
        name = "lecture du futur (test)"

        def decide(self, view: PointInTimeView, params: Params) -> Weights:
            view.closes("FICT-A", end=view.day + timedelta(days=1))
            return {}

    with pytest.raises(LookAheadError):
        run(
            Peeking(),
            {},
            market(closes("FICT-A", [10, 10, 10])),
            start=DAYS[0],
            end=DAYS[2],
            cutoff=CUTOFF,
            costs=FREE,
            initial_cash=1000.0,
        )


# Invariants -----------------------------------------------------------------------------------


@dataclass
class Random:
    """Seeded random weights over the instruments with a known close: pure and repeatable."""

    name: str = "hasard (test)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        draw = random.Random(f"{params['seed']}-{view.day}")  # noqa: S311 - seeded test data
        if draw.random() < 0.2:
            return {}
        known = [i for i in view.instruments if view.last_close(i) is not None]
        raw = {i: draw.random() for i in known}
        scale = draw.random() / (math.fsum(raw.values()) or 1.0)
        return {i: w * scale for i, w in raw.items()}


@st.composite
def markets(draw: st.DrawFn) -> list[PriceRow | CorporateAction]:
    count = draw(st.integers(3, 15))
    records: list[PriceRow | CorporateAction] = []
    for instrument_id in draw(st.sampled_from([["FICT-A"], ["FICT-A", "FICT-B"]])):
        values = draw(st.lists(st.floats(1, 300), min_size=count, max_size=count))
        for day, value in zip(DAYS, values, strict=False):
            late = draw(st.booleans()) and draw(st.booleans())
            records.append(
                close(instrument_id, day, round(value, 2), morning_after(day) if late else None)
            )
        if draw(st.booleans()):
            ex = DAYS[draw(st.integers(1, count - 1))]
            records.append(
                split(instrument_id, ex, draw(st.sampled_from([0.5, 1.5, 2, 3])), evening(DAYS[0]))
            )
        for ex in draw(st.lists(st.integers(1, count - 1), max_size=2, unique=True)):
            announced = DAYS[draw(st.integers(0, count - 1))]
            records.append(
                dividend(instrument_id, DAYS[ex], draw(st.floats(0.01, 1)), evening(announced))
            )
    return records


@settings(max_examples=40, deadline=None)
@given(
    records=markets(),
    seed=st.integers(0, 10_000),
    cash=st.floats(100, 1_000_000),
    costs=st.sampled_from(
        [
            FREE,
            Costs("fictifs", 0.001, 2.0, 0.0005),
            Costs("fictifs", 0.001, 2.0, 0.0005, rounding="none"),
            Costs("lourds", 0.01, 25.0, 0.005),
        ]
    ),
)
def test_the_book_always_adds_up(
    records: list[PriceRow | CorporateAction], seed: int, cash: float, costs: Costs
) -> None:
    history = market(records)
    count = len({r.session for r in records if isinstance(r, PriceRow)})
    result = run(
        Random(),
        {"seed": seed},
        history,
        start=DAYS[0],
        end=DAYS[count - 1],
        cutoff=CUTOFF,
        costs=costs,
        initial_cash=cash,
    )
    prices = [history.final_closes(i).to_numpy() for i in result.positions.columns]
    for k, value in enumerate(result.values):
        invested = math.fsum(
            int(result.positions[i].iloc[k]) * prices[n][k]
            for n, i in enumerate(result.positions.columns)
        )
        assert value == pytest.approx(result.cash.iloc[k] + invested, rel=1e-12)
        assert 0 <= result.exposure.iloc[k] <= 1 + 1e-12
    assert (result.cash >= 0).all() and (result.positions >= 0).all().all()
    assert all(isinstance(q, int) for q in result.positions.to_numpy().ravel().tolist())
    for trade in result.trades:
        assert trade.fill.quantity != 0 and trade.executed > trade.decided
        assert trade.fill.slippage >= 0 and trade.fill.commission >= costs.minimum - 0.005
    paid = math.fsum(c.amount for c in result.credits if c.credited is not None)
    flows = math.fsum(t.fill.cash for t in result.trades)
    assert result.cash.iloc[-1] == pytest.approx(cash + flows + paid, abs=1e-6)


# Measures and the research dataset ------------------------------------------------------------


def test_measures_follow_adr_020() -> None:
    result = backtest(Fixed({"FICT-A": 1.0}), market(closes("FICT-A", [10, 11, 12, 13])), 4)
    found = measures(result, 252)
    values = result.values.tolist()
    returns = daily_returns(values, [0.0, 0.0, 0.0])
    assert found.sessions == 3
    assert found.total_return == chained(returns) == pytest.approx(0.18)
    assert found.annual_return == annualized(chained(returns), 3)
    assert found.volatility == volatility(returns, 252)
    assert found.sharpe == sharpe(returns, 252)
    assert found.drawdown == max_drawdown(DAYS[:4], returns)
    assert found.turnover == pytest.approx(990 / (2 * sum(values) / 4) * 252 / 3)
    assert (found.trades, found.fees) == (1, 0.0)
    assert found.mean_exposure == pytest.approx((0 + 990 / 1000 + 1080 / 1090 + 1170 / 1180) / 4)
    excess = measures(result, 252, risk_free=[0.001] * 3)
    assert excess.sharpe == sharpe([r - 0.001 for r in returns], 252)
    with pytest.raises(ValueError, match="un taux sans risque par rendement"):
        measures(result, 252, risk_free=[0.0])


@pytest.fixture(scope="module")
def research() -> Iterator[MarketHistory]:
    store = FinanceStore.memory()
    load_research(store)
    yield MarketHistory.load(store, ["FICT-RTEND", "FICT-RALEA1", "FICT-RALEA2", "FICT-RALEA3"])
    store.close()


def test_a_ten_year_backtest_on_the_research_dataset(research: MarketHistory) -> None:
    named = research_costs()
    costs = Costs.from_config(named.costs, named.name)
    result = run(
        Fixed({"FICT-RALEA1": 0.3, "FICT-RALEA2": 0.3, "FICT-RTEND": 0.3}),
        {},
        research,
        start=date(2016, 1, 4),
        end=date(2025, 12, 31),
        cutoff=CUTOFF,
        costs=costs,
        initial_cash=100_000.0,
    )
    assert len(result.values) == 2560 and result.costs.name == "frais fictifs de démonstration"
    dividends = [c for c in result.credits if c.kind == "dividend"]
    assert [c.ex_date.year for c in dividends] == list(range(2016, 2026))
    assert all(c.credited == c.ex_date for c in dividends)  # announced four weeks ahead
    shares = result.positions["FICT-RALEA2"]
    before, after = shares.loc["2021-06-11"], shares.loc["2021-06-14"]
    assert after >= 2 * before - 1  # the split doubles the shares, plus the day's trade
    found = measures(result, 252)
    assert found.fees > 0 and found.trades > 100 and 0.85 < found.mean_exposure <= 0.9
    assert all(math.isfinite(v) for v in (found.total_return, found.volatility, found.turnover))
    assert isinstance(result.trades[0], Trade) and result.trades[0].decided == date(2016, 1, 4)
