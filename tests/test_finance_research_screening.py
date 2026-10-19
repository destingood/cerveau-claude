"""The vectorbt screening replays the reference engine where it is exact (ADR-025, D12)."""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.config.loader import load_config
from core.finance.fixtures import load_research, research_costs
from core.finance.model import Instrument, PriceRow
from core.finance.research import engine, screening
from core.finance.research.execution import Costs
from core.finance.research.strategy import Params, StrategyError, Weights
from core.finance.research.view import MarketHistory, PointInTimeView
from core.finance.store import FinanceStore

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = load_config(ROOT / "config").research
TOLERANCE = RESEARCH.cross_check.vectorbt_rel_tolerance
CUTOFF = time(21, 0)
PLAIN = ("FICT-RTEND", "FICT-RALEA3")  # the research instruments without corporate actions
UNIVERSE = ("FICT-RALEA1", "FICT-RALEA2", "FICT-RALEA3", "FICT-RTEND")
START, END = date(2016, 1, 4), date(2017, 12, 29)
CASH = 100_000.0


@pytest.fixture(scope="module")
def store() -> Iterator[FinanceStore]:
    research = FinanceStore.memory()
    load_research(research)
    yield research
    research.close()


@pytest.fixture(scope="module")
def plain(store: FinanceStore) -> MarketHistory:
    return MarketHistory.load(store, PLAIN)


@pytest.fixture(scope="module")
def universe(store: FinanceStore) -> MarketHistory:
    return MarketHistory.load(store, UNIVERSE)


@pytest.fixture(scope="module")
def costs() -> Costs:
    named = research_costs()
    return Costs.from_config(named.costs, named.name)


@pytest.fixture(scope="module")
def exact(costs: Costs) -> Costs:
    """The research costs without what vectorbt cannot apply: minimum and rounding."""
    return Costs(costs.name, costs.commission, 0.0, costs.slippage, rounding="none")


@dataclass
class Alternate:
    """``share`` of the universe in one instrument, the next one every ``period`` days."""

    name: str = "alternance (test)"

    def _held(self, instruments: Sequence[str], day: date, params: Params) -> str:
        return instruments[day.toordinal() // int(params["period"]) % len(instruments)]

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        return {self._held(view.instruments, view.day, params): float(params["share"])}

    def weights_frame(
        self, history: MarketHistory, params: Params, sessions: Sequence[date], cutoff: time
    ) -> pd.DataFrame:
        frame = pd.DataFrame(
            np.nan, index=pd.DatetimeIndex(sessions), columns=list(history.instruments)
        )
        for row, day in enumerate(sessions):
            frame.iloc[
                row, history.instruments.index(self._held(history.instruments, day, params))
            ] = float(params["share"])
        return frame


@dataclass
class Rotation:
    """``share`` in the instrument that rose most over ``lookback`` known closes.

    Its vectorised form replays ``decide`` at every session: faithful by construction, it
    isolates the execution of the screening from the vectorisation of a strategy.
    """

    name: str = "rotation (test)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        lookback, best = int(params["lookback"]), None
        for instrument_id in view.instruments:
            known = view.closes(instrument_id)
            if len(known) <= lookback:
                return {}
            rise = known.iloc[-1] / known.iloc[-1 - lookback]
            if best is None or rise > best[1]:
                best = (instrument_id, rise)
        return {best[0]: float(params["share"])} if best else {}

    def weights_frame(
        self, history: MarketHistory, params: Params, sessions: Sequence[date], cutoff: time
    ) -> pd.DataFrame:
        rows = [self.decide(history.view(day, cutoff), params) for day in sessions]
        return pd.DataFrame(
            rows, index=pd.DatetimeIndex(sessions), columns=list(history.instruments), dtype=float
        )


@dataclass
class Fixed:
    """The same frame whatever the parameters: to feed the screening a broken one."""

    frame: object
    name: str = "fixe (test)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        return {}

    def weights_frame(
        self, history: MarketHistory, params: Params, sessions: Sequence[date], cutoff: time
    ) -> object:
        return self.frame


def window(costs: Costs, start: date = START, end: date = END) -> dict[str, object]:
    return {"start": start, "end": end, "cutoff": CUTOFF, "costs": costs, "initial_cash": CASH}


# Exactness where the screening is in scope -----------------------------------------------------


@pytest.mark.parametrize(
    ("strategy", "grid"),
    [
        (Alternate(), [{"period": p, "share": s} for p in (1, 3, 10) for s in (0.5, 0.99)]),
        (Rotation(), [{"lookback": n, "share": 0.95} for n in (5, 40)]),
    ],
    ids=["alternance", "rotation"],
)
def test_the_screening_matches_the_reference_engine(
    strategy: Alternate | Rotation, grid: list[Params], plain: MarketHistory, exact: Costs
) -> None:
    checks = screening.cross_check(
        strategy,
        grid,
        plain,
        **window(exact),
        sessions_per_year=252,
        tolerance=TOLERANCE,
    )
    assert len(checks) == len(grid)
    for check in checks:
        assert check.passed, check
        assert check.screening is not None and check.gap is not None
        assert check.gap <= TOLERANCE and check.value_gap < 1e-12


def test_the_screening_places_the_engines_orders(plain: MarketHistory, exact: Costs) -> None:
    params: Params = {"period": 2, "share": 1.0}  # all in: some buys are cut to the cash
    found = screening.screen(Alternate(), [params], plain, **window(exact))
    result = engine.run(Alternate(), params, plain, **window(exact))
    assert found.points[0].orders == len(result.trades)
    assert result.cuts, "the case must include buys cut to the cash"
    assert found.start == START and found.end == END
    assert found.approximations == ()


def test_a_sample_of_the_grid_is_cross_checked(plain: MarketHistory, exact: Costs) -> None:
    grid: list[Params] = [{"period": p, "share": 0.5} for p in (1, 2, 3, 4)]
    checks = screening.cross_check(
        Alternate(),
        grid,
        plain,
        **window(exact),
        sessions_per_year=252,
        tolerance=TOLERANCE,
        sample=[3, 0],
    )
    assert [c.params["period"] for c in checks] == [4, 1]


def test_batches_give_the_same_points_as_one_call(
    plain: MarketHistory, costs: Costs, monkeypatch: pytest.MonkeyPatch
) -> None:
    grid: list[Params] = [{"period": p, "share": 0.9} for p in (1, 2, 5)]
    whole = screening.screen(Alternate(), grid, plain, **window(costs))
    monkeypatch.setattr(screening, "BATCH", 2)
    split = screening.screen(Alternate(), grid, plain, **window(costs))
    for a, b in zip(whole.points, split.points, strict=True):
        assert a.params == b.params and a.orders == b.orders
        pd.testing.assert_series_equal(a.values, b.values, check_exact=True)


def test_the_cross_check_detects_a_divergent_vectorised_form(
    plain: MarketHistory, exact: Costs
) -> None:
    class Shifted(Alternate):
        def weights_frame(
            self, history: MarketHistory, params: Params, sessions: Sequence[date], cutoff: time
        ) -> pd.DataFrame:
            return super().weights_frame(history, {**params, "period": 7}, sessions, cutoff)

    checks = screening.cross_check(
        Shifted(),
        [{"period": 3, "share": 0.5}],
        plain,
        **window(exact),
        sessions_per_year=252,
        tolerance=TOLERANCE,
    )
    assert not checks[0].passed and checks[0].gap is not None and checks[0].gap > TOLERANCE


def test_relative_gaps() -> None:
    assert screening.relative_gap(None, None) is None
    assert screening.relative_gap(1.0, None) == screening.relative_gap(None, 1.0) == float("inf")
    assert screening.relative_gap(1.1, 1.0) == pytest.approx(0.1)
    assert screening.relative_gap(0.5, 0.0) == 0.5


# Out of scope: labelled approximations, refused cross-checks ---------------------------------


def test_the_approximations_are_labelled(universe: MarketHistory, costs: Costs) -> None:
    found = screening.screen(
        Alternate(),
        [{"period": 5, "share": 0.9}],
        universe,
        **window(costs, date(2016, 1, 4), date(2025, 12, 31)),
    )
    labels = " | ".join(found.approximations)
    assert "minimum de 2 € par ordre non appliqué" in labels
    assert "frais non arrondis au centime" in labels
    moved = {label.split(" : ")[0] for label in found.approximations if "opérations" in label}
    assert moved == {"FICT-RALEA1", "FICT-RALEA2"}
    assert (found.points[0].values > 0).all()


def test_the_cross_check_refuses_what_the_screening_approximates(
    universe: MarketHistory, costs: Costs, exact: Costs
) -> None:
    grid: list[Params] = [{"period": 5, "share": 0.5}]
    with pytest.raises(screening.ScreeningError, match="sans minimum ni arrondi"):
        screening.cross_check(
            Alternate(),
            grid,
            universe,
            **window(costs),
            sessions_per_year=252,
            tolerance=TOLERANCE,
        )
    with pytest.raises(screening.ScreeningError, match="opérations sur titres"):
        screening.cross_check(
            Alternate(),
            grid,
            universe,
            **window(exact, date(2016, 1, 4), date(2025, 12, 31)),
            sessions_per_year=252,
            tolerance=TOLERANCE,
        )


# Weights the engine would refuse ---------------------------------------------------------------


def frame_of(history: MarketHistory, rows: dict[str, list[float]] | None = None) -> pd.DataFrame:
    sessions, _ = engine.common_calendar(history, START, END)
    frame = pd.DataFrame(
        np.nan, index=pd.DatetimeIndex(sessions), columns=list(history.instruments)
    )
    for column, values in (rows or {}).items():
        frame.loc[frame.index[: len(values)], column] = values
    return frame


@pytest.mark.parametrize(
    ("broken", "message"),
    [
        (lambda f: f.iloc[1:], "une ligne par séance"),
        (lambda f: f.tz_localize("UTC"), "une ligne par séance"),
        (lambda f: f.assign(**{"FICT-AUTRE": 0.1}), "FICT-AUTRE hors de l'univers"),
        (lambda f: f.astype(bool), "non numériques"),
        (lambda f: f.fillna(0.0).assign(**{"FICT-RTEND": -0.1}), "ni découvert"),
        (lambda f: f.fillna(0.6), "somme 1.200000 > 1"),
        (lambda f: f.fillna(np.inf), "ni découvert ni infini"),
        (lambda f: f.to_numpy(), "DataFrame"),
    ],
)
def test_a_frame_the_engine_would_refuse_fails_the_screening(
    plain: MarketHistory,
    costs: Costs,
    broken: Callable[[pd.DataFrame], object],
    message: str,
) -> None:
    frame = broken(frame_of(plain))
    with pytest.raises(StrategyError, match=message):
        screening.screen(Fixed(frame), [{}], plain, **window(costs))


def test_the_last_decision_is_never_filled_so_never_checked(
    plain: MarketHistory, costs: Costs
) -> None:
    frame = frame_of(plain)
    frame.iloc[-1] = 0.9  # a sum of 1.8 at the last session: the engine never decides there
    found = screening.screen(Fixed(frame), [{}], plain, **window(costs))
    assert found.points[0].orders == 0


def test_a_weight_without_a_known_close_fails_the_screening(costs: Costs) -> None:
    days = [date(2024, 3, 4) + timedelta(days=n) for n in range(6)]

    def row(instrument_id: str, day: date, published: datetime | None = None) -> PriceRow:
        return PriceRow(
            instrument_id=instrument_id,
            session=day,
            close=100.0 + day.day,
            currency="EUR",
            source="fixtures",
            published_at=published or datetime.combine(day, time(17, 35), tzinfo=UTC),
        )

    late = datetime.combine(days[1], time(10, 0), tzinfo=UTC)  # day 0 of B, known only on day 1
    records = [row("FICT-A", d) for d in days] + [
        row("FICT-B", d, late if k == 0 else None) for k, d in enumerate(days)
    ]
    history = synthetic(records)
    frame = pd.DataFrame(np.nan, index=pd.DatetimeIndex(days), columns=["FICT-A", "FICT-B"])
    frame.iloc[0, 1] = 0.5
    with pytest.raises(StrategyError, match="2024-03-04 : poids sur FICT-B sans aucun cours"):
        screening.screen(Fixed(frame), [{}], history, **window(costs, days[0], days[-1]))
    frame.iloc[0, 1], frame.iloc[1, 1] = np.nan, 0.5  # known from day 1 on
    found = screening.screen(Fixed(frame), [{}], history, **window(costs, days[0], days[-1]))
    assert found.points[0].orders == 2  # bought on day 2, sold on day 3: no weight is zero


def synthetic(records: Sequence[PriceRow]) -> MarketHistory:
    store = FinanceStore.memory()
    for instrument_id in sorted({r.instrument_id for r in records}):
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
    ordered = sorted(records, key=lambda r: r.published_at)
    store.ingest(ordered, ingested_at=ordered[-1].published_at)
    history = MarketHistory.load(store, sorted({r.instrument_id for r in records}))
    store.close()
    return history


def test_an_empty_grid_or_cash_is_refused(plain: MarketHistory, costs: Costs) -> None:
    with pytest.raises(screening.ScreeningError, match="grille vide"):
        screening.screen(Alternate(), [], plain, **window(costs))
    with pytest.raises(screening.ScreeningError, match="cash initial"):
        screening.screen(
            Alternate(),
            [{"period": 1, "share": 0.5}],
            plain,
            **{**window(costs), "initial_cash": 0.0},
        )


# Trials and the optional group ----------------------------------------------------------------


def test_every_point_becomes_a_screening_trial(
    plain: MarketHistory, costs: Costs, store: FinanceStore
) -> None:
    grid: list[Params] = [{"period": p, "share": 0.5} for p in (1, 2)]
    found = screening.screen(Alternate(), grid, plain, **window(costs))
    made = found.trials("alternance_test", "c" * 64, 252)
    assert [t.params for t in made] == grid
    assert {t.origin for t in made} == {"criblage"}
    assert {t.engine for t in made} == {f"vectorbt {screening.vectorbt_version()}"}
    assert {t.costs for t in made} == {costs.name}
    assert made[0].sharpe_annual == found.points[0].sharpe(252)
    journal = FinanceStore.memory()
    journal.add_trials(made, recorded_at=datetime(2026, 10, 20, tzinfo=UTC))
    assert journal.trial_count("alternance_test") == 2
    journal.close()


def test_without_the_research_group_the_screening_says_how_to_install_it(
    plain: MarketHistory, costs: Costs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "vectorbt", None)
    with pytest.raises(screening.ScreeningError, match="uv sync --group research"):
        screening.screen(Alternate(), [{"period": 1, "share": 0.5}], plain, **window(costs))


def test_only_the_screening_imports_vectorbt_and_only_on_use() -> None:
    importers: dict[str, list[int]] = {}
    for folder in ("core", "interfaces", "plugins", "domain_packs"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else []
                )
                if any(n == "vectorbt" or n.startswith("vectorbt.") for n in names):
                    importers.setdefault(path.relative_to(ROOT).as_posix(), []).append(
                        node.col_offset
                    )
    assert list(importers) == ["core/finance/research/screening.py"]
    assert all(offset > 0 for offset in importers["core/finance/research/screening.py"])
