"""The NautilusTrader adapter replays the in-house engine to the D12 tolerance (ADR-024)."""

from __future__ import annotations

import ast
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest
from hypothesis import assume, event, given, settings
from hypothesis import strategies as st
from nautilus_trader.model.objects import MONEY_MAX

from core.config.loader import load_config
from core.finance.fixtures import load_research, research_costs
from core.finance.model import Instrument, PriceRow
from core.finance.research import engine, nautilus
from core.finance.research.execution import Costs, Order, Schedule
from core.finance.research.strategy import Params, Strategy, StrategyError, Weights
from core.finance.research.view import LookAheadError, MarketHistory, PointInTimeView
from core.finance.store import FinanceStore

ROOT = Path(__file__).resolve().parents[1]
TOLERANCE = load_config(ROOT / "config").research.cross_check.nautilus_rel_tolerance
CUTOFF = time(21, 0)
PLAIN = ("FICT-RTEND", "FICT-RALEA3")  # the research instruments without corporate actions


@pytest.fixture(scope="module")
def research() -> MarketHistory:
    store = FinanceStore.memory()
    load_research(store)
    history = MarketHistory.load(store, PLAIN)
    store.close()
    return history


@pytest.fixture(scope="module")
def costs() -> Costs:
    named = research_costs()
    return Costs.from_config(named.costs, named.name)


def both(
    strategy: Strategy,
    history: MarketHistory,
    start: date,
    end: date,
    costs: Costs,
    cash: float = 100_000.0,
) -> tuple[engine.BacktestResult, nautilus.NautilusResult]:
    window = {"start": start, "end": end, "cutoff": CUTOFF, "costs": costs, "initial_cash": cash}
    return (
        engine.run(strategy, {}, history, **window),
        nautilus.run(strategy, {}, history, **window),
    )


# Strategies -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Momentum:
    """Half the book on each instrument whose total return over a month is positive."""

    name: str = "momentum un mois (test)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        weights: dict[str, float] = {}
        for instrument_id in view.instruments:
            closes = view.closes(instrument_id, adjust="total_return")
            if len(closes) > 21 and closes.iloc[-1] > closes.iloc[-22]:
                weights[instrument_id] = 0.5
        return weights


@dataclass(frozen=True)
class Rotation:
    """The whole book on one instrument, then the other: every buy needs the same-day sell."""

    name: str = "rotation (test)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        return {PLAIN[view.day.toordinal() % 2]: 1.0}


@dataclass
class Script:
    plan: Mapping[date, Weights] = field(default_factory=dict)
    name: str = "script (test)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        return self.plan.get(view.day, {})


# The research dataset ---------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", [Momentum(), Rotation()], ids=["momentum", "rotation"])
def test_nautilus_replays_ten_years_of_the_in_house_engine(
    strategy: Strategy, research: MarketHistory, costs: Costs
) -> None:
    sessions = research.final_closes(PLAIN[0]).index
    ours, theirs = both(strategy, research, sessions[0].date(), sessions[-1].date(), costs)
    check = nautilus.cross_check(ours, theirs, TOLERANCE)
    assert check.passed, check.trade_gaps[:3] or check.relative_gap
    assert check.trades == len(theirs.trades) > 500
    assert check.engine == f"NautilusTrader {nautilus.nautilus_trader.__version__}"
    assert theirs.positions.equals(ours.positions)
    assert len(theirs.cuts) == len(ours.cuts)
    # Fees are compared on their own (D12): the fee model books Costs.fill once per order.
    fees = [t.fill.fees for t in ours.trades]
    assert [t.fees for t in theirs.trades] == pytest.approx(fees, rel=0, abs=1e-9)
    assert check.fees_gap == pytest.approx(0, abs=1e-6)
    assert ((theirs.cash - ours.cash).abs() <= TOLERANCE * ours.values).all()


def test_a_buy_funded_by_the_same_day_sale_passes_the_nautilus_checks(
    research: MarketHistory, costs: Costs
) -> None:
    """NautilusTrader cannot price a market order from bars alone, so its pre-trade balance
    check lets it through; the cash account still refuses any fill that would overdraw it."""
    ours, theirs = both(Rotation(), research, date(2019, 1, 2), date(2019, 3, 29), costs)
    rotations = [t for t in theirs.trades if t.quantity > 0 and t.decided > date(2019, 1, 2)]
    assert rotations
    assert min(theirs.cash) >= 0
    assert nautilus.cross_check(ours, theirs, TOLERANCE).passed


# Small markets ----------------------------------------------------------------------------------

DAYS = [date(2024, 3, 4) + timedelta(days=n) for n in range(30)]
IDS = ("FICT-A", "FICT-B")


def synthetic(rows: Sequence[PriceRow]) -> MarketHistory:
    store = FinanceStore.memory()
    for instrument_id in sorted({r.instrument_id for r in rows}):
        store.add_instrument(
            Instrument(
                instrument_id=instrument_id,
                valid_from=date(2000, 1, 1),
                name=f"{instrument_id} (fictif)",
                asset_class="equity",
                currency="EUR",
                mic="XPAR",
                sector="Industrie",
                country="FR",
            ),
            recorded_at=datetime(2000, 1, 1, tzinfo=UTC),
        )
    ordered = sorted(rows, key=lambda r: r.published_at)
    store.ingest(ordered, ingested_at=ordered[-1].published_at)
    history = MarketHistory.load(store, sorted({r.instrument_id for r in rows}))
    store.close()
    return history


def row(instrument_id: str, day: date, value: float, hours_late: int = 0) -> PriceRow:
    return PriceRow(
        instrument_id=instrument_id,
        session=day,
        close=value,
        currency="EUR",
        source="fixtures",
        published_at=datetime.combine(day, time(17, 35), UTC) + timedelta(hours=hours_late),
    )


@st.composite
def markets(draw: st.DrawFn) -> tuple[MarketHistory, int, dict[date, Weights]]:
    """Two instruments, some closes published after the cut-off, some bad prints corrected."""
    count = draw(st.integers(3, len(DAYS)))
    rows: list[PriceRow] = []
    for instrument_id in IDS:
        for day in DAYS[:count]:
            value = round(draw(st.floats(1, 500)), 2)
            if draw(st.integers(0, 5)) == 0:  # a bad print, corrected the next morning
                wrong = round(value * draw(st.sampled_from([0.5, 1.5])), 2)
                rows += [row(instrument_id, day, wrong), row(instrument_id, day, value, 14)]
            else:
                rows.append(row(instrument_id, day, value, draw(st.sampled_from([0, 0, 0, 14]))))
    weight = st.sampled_from([0.0, 0.1, 0.33, 0.5, 0.9, 1.0])
    plan: dict[date, Weights] = {}
    for day in DAYS[1 : count - 1]:  # the first close of each instrument is known by then
        a, b = draw(weight), draw(weight)
        plan[day] = {IDS[0]: a, IDS[1]: b} if a + b <= 1 else {IDS[0]: a}
    return synthetic(rows), count, plan


@settings(max_examples=25, deadline=None)
@given(
    market=markets(),
    commission=st.sampled_from([0.0, 0.001, 0.0025]),
    minimum=st.sampled_from([0.0, 1.0, 4.95]),
    slippage=st.sampled_from([0.0, 0.0005, 0.002]),
    cash=st.sampled_from([150.0, 2_500.0, 1_000_000.0]),
)
def test_nautilus_agrees_on_any_small_market(
    market: tuple[MarketHistory, int, dict[date, Weights]],
    commission: float,
    minimum: float,
    slippage: float,
    cash: float,
) -> None:
    history, count, plan = market
    costs = Costs("frais tirés (test)", commission, minimum, slippage)
    window = {"start": DAYS[0], "end": DAYS[count - 1], "cutoff": CUTOFF, "costs": costs}
    ours = engine.run(Script(plan), {}, history, **window, initial_cash=cash)
    # Independent closes between 1 and 500 can multiply the book a hundredfold a day; Nautilus
    # stores money as fixed-point and refuses an amount above MONEY_MAX (B122). Such a book is out
    # of the cross-check's domain, not a disagreement.
    assume(float(ours.values.max()) < MONEY_MAX / 10)
    theirs = nautilus.run(Script(plan), {}, history, **window, initial_cash=cash)
    event("avec exécutions" if ours.trades else "sans exécution")
    event("avec coupes" if ours.cuts else "sans coupe")
    check = nautilus.cross_check(ours, theirs, TOLERANCE)
    assert check.passed, (check.trade_gaps[:3], check.relative_gap)
    assert theirs.positions.equals(ours.positions)
    assert check.fees_gap == pytest.approx(0, abs=1e-6)


# Errors -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Peek:
    name: str = "lecture du lendemain (test)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        view.closes(PLAIN[0], end=view.day + timedelta(days=1))
        return {}


@dataclass(frozen=True)
class Leveraged:
    name: str = "levier (test)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        return {PLAIN[0]: 0.8, PLAIN[1]: 0.8}


def test_an_error_inside_nautilus_stops_the_replay(research: MarketHistory, costs: Costs) -> None:
    window = {
        "start": date(2019, 1, 2),
        "end": date(2019, 1, 31),
        "cutoff": CUTOFF,
        "costs": costs,
        "initial_cash": 1e5,
    }
    with pytest.raises(LookAheadError, match="03/01/2019 demandée par une décision du 02/01"):
        nautilus.run(Peek(), {}, research, **window)
    with pytest.raises(StrategyError, match="pas de levier"):
        nautilus.run(Leveraged(), {}, research, **window)


def test_an_overdraft_refused_by_nautilus_fails_the_replay(
    research: MarketHistory, costs: Costs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scheduler that forgot the cash: the NautilusTrader account must refuse it, loudly."""

    def careless(
        orders: Sequence[Order], cash: float, prices: Mapping[str, float], costs: Costs
    ) -> Schedule:
        fills = [
            costs.fill(o.instrument_id, 3 * o.quantity, prices[o.instrument_id]) for o in orders
        ]
        return Schedule(fills, [], cash + math.fsum(f.cash for f in fills))

    monkeypatch.setattr(nautilus, "schedule", careless)
    with pytest.raises(engine.BacktestError, match="AccountError"):
        nautilus.run(
            Rotation(),
            {},
            research,
            start=date(2019, 1, 2),
            end=date(2019, 1, 31),
            cutoff=CUTOFF,
            costs=costs,
            initial_cash=1e5,
        )


def test_the_adapter_refuses_what_it_cannot_reproduce(costs: Costs) -> None:
    store = FinanceStore.memory()
    load_research(store)
    with_dividends = MarketHistory.load(store, ("FICT-RALEA1", "FICT-RTEND"))
    store.close()
    window = {"cutoff": CUTOFF, "costs": costs, "initial_cash": 1e5}
    with pytest.raises(engine.BacktestError, match="opération sur titre"):
        nautilus.run(
            Rotation(), {}, with_dividends, start=date(2019, 1, 2), end=date(2019, 12, 31), **window
        )
    fine = synthetic(
        [row(i, day, 10 + n / 3) for i in IDS for n, day in enumerate(DAYS[:5])]
    )  # 10.333…: more decimals than a NautilusTrader price holds
    with pytest.raises(engine.BacktestError, match="décimales"):
        nautilus.run(Script(), {}, fine, start=DAYS[0], end=DAYS[4], **window)
    exact = synthetic([row(i, day, 10.25) for i in IDS for day in DAYS[:5]])
    unrounded = replace(costs, rounding="none")
    with pytest.raises(engine.BacktestError, match="centime"):
        nautilus.run(
            Script(),
            {},
            exact,
            start=DAYS[0],
            end=DAYS[4],
            cutoff=CUTOFF,
            costs=unrounded,
            initial_cash=1e5,
        )
    with pytest.raises(engine.BacktestError, match="cash initial"):
        nautilus.run(
            Script(),
            {},
            exact,
            start=DAYS[0],
            end=DAYS[4],
            cutoff=CUTOFF,
            costs=costs,
            initial_cash=0.0,
        )


# The cross-check itself -------------------------------------------------------------------------


def test_the_cross_check_names_every_gap(research: MarketHistory, costs: Costs) -> None:
    ours, theirs = both(Momentum(), research, date(2019, 1, 2), date(2019, 6, 28), costs)
    assert nautilus.cross_check(ours, theirs, TOLERANCE).passed
    first = theirs.trades[0]
    moved = replace(
        theirs, trades=(replace(first, quantity=first.quantity + 1), *theirs.trades[1:])
    )
    check = nautilus.cross_check(ours, moved, TOLERANCE)
    assert not check.passed
    assert check.trade_gaps[0].startswith("exécution n° 1 : moteur maison")
    lost = nautilus.cross_check(ours, replace(theirs, trades=theirs.trades[:-1]), TOLERANCE)
    assert lost.trade_gaps == (
        f"{len(ours.trades)} exécutions dans le moteur maison, "
        f"{len(ours.trades) - 1} dans {nautilus.ENGINE}",
    )
    drift = theirs.values.copy()
    drift.iloc[40] *= 1 + 2 * TOLERANCE
    drifted = nautilus.cross_check(ours, replace(theirs, values=drift), TOLERANCE)
    assert not drifted.passed and drifted.trade_gaps == ()
    assert drifted.worst_session == ours.values.index[40].date()
    assert drifted.relative_gap == pytest.approx(2 * TOLERANCE, rel=1e-6)
    with pytest.raises(ValueError, match="mêmes entrées"):
        nautilus.cross_check(ours, replace(theirs, initial_cash=1.0), TOLERANCE)
    with pytest.raises(ValueError, match="strictement positif"):
        nautilus.cross_check(ours, theirs, 0.0)


def test_only_the_adapter_imports_nautilus_trader() -> None:
    """ADR-024: a migration to NautilusTrader 2 touches one module."""
    importers = []
    for path in sorted((ROOT / "core").rglob("*.py")) + sorted((ROOT / "plugins").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            if any(n.split(".")[0] == "nautilus_trader" for n in names):
                importers.append(path.relative_to(ROOT).as_posix())
    assert sorted(set(importers)) == ["core/finance/research/nautilus.py"]


def test_the_replay_is_deterministic(research: MarketHistory, costs: Costs) -> None:
    rng = random.Random(7)  # noqa: S311 - seeded test data, not cryptography
    days = [s.date() for s in research.final_closes(PLAIN[0]).index[300:340]]
    plan = {d: {PLAIN[rng.randrange(2)]: rng.choice([0.2, 0.6, 1.0])} for d in days}
    first = nautilus.run(
        Script(plan),
        {},
        research,
        start=days[0],
        end=days[-1],
        cutoff=CUTOFF,
        costs=costs,
        initial_cash=5e4,
    )
    again = nautilus.run(
        Script(plan),
        {},
        research,
        start=days[0],
        end=days[-1],
        cutoff=CUTOFF,
        costs=costs,
        initial_cash=5e4,
    )
    assert first.trades == again.trades
    assert first.values.equals(again.values)
