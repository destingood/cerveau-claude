"""The vectorbt screening of a parameter grid and its cross-check with the reference (ADR-025).

The screening replays every combination of a grid at once, from the vectorised weights of the
strategy, with the same orders as the in-house engine: weights decided at t sized on the close
known at t and filled at the close of t+1 (``targetpercent`` with ``val_price``), whole shares,
sells first then buys by increasing gap (``call_seq="auto"``), one cash account per combination.
It ranks combinations; it gives no verdict. Every combination becomes a trial of origin
``criblage`` in the journal (ADR-026), so that the deflated Sharpe ratio counts it.

What vectorbt cannot reproduce is listed in ``Screening.approximations``: the minimum fee per
order, the rounding of fees to the cent, and corporate actions, which the screening folds into
total-return prices (dividends reinvested, splits without cash in lieu).

vectorbt is an optional dependency (group ``research``): only this module imports it, inside its
functions, so that the rest of CERVEAU runs without it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd

from core.finance.adjust import adjustment_factors
from core.finance.model import ParamValue, ResearchTrial
from core.finance.performance import sharpe
from core.finance.research import engine
from core.finance.research.execution import Costs
from core.finance.research.strategy import Params, StrategyError, VectorStrategy, checked_weights
from core.finance.research.trials import make_trial, value_returns
from core.finance.research.view import MarketHistory

MISSING_GROUP = (
    "le criblage demande le groupe optionnel research : `uv sync --group research` (ADR-025)"
)
BATCH = 64  # combinations per vectorbt call: bounds the memory of a large grid


class ScreeningError(ValueError):
    """A screening that cannot run, or a cross-check outside its scope."""


def _vectorbt() -> ModuleType:
    try:
        import vectorbt  # optional group, imported on use (ADR-025)
    except ImportError as exc:
        raise ScreeningError(MISSING_GROUP) from exc
    return vectorbt


def vectorbt_version() -> str:
    return str(_vectorbt().__version__)


@dataclass(frozen=True)
class ScreenPoint:
    """One combination of the grid: its parameters, value curve and number of orders."""

    params: dict[str, ParamValue]
    values: pd.Series
    orders: int

    def sharpe(self, sessions_per_year: int) -> float | None:
        """The annual Sharpe ratio of the daily returns, at a zero rate [Hypothèse]."""
        return sharpe(value_returns(self.values).tolist(), sessions_per_year)


@dataclass(frozen=True)
class Screening:
    strategy: str
    engine: str
    costs: str
    initial_cash: float
    start: date  # first and last sessions of the window
    end: date
    points: tuple[ScreenPoint, ...]
    approximations: tuple[str, ...]

    def trials(
        self, strategy_id: str, code_sha256: str, sessions_per_year: int
    ) -> list[ResearchTrial]:
        """One trial of origin ``criblage`` per combination, ready for the journal (ADR-026)."""
        return [
            make_trial(
                strategy=strategy_id,
                code_sha256=code_sha256,
                params=point.params,
                origin="criblage",
                values=point.values,
                sessions_per_year=sessions_per_year,
                costs=self.costs,
                engine=self.engine,
            )
            for point in self.points
        ]


def _cost_approximations(costs: Costs) -> list[str]:
    """The fee rules of ``costs`` that vectorbt does not apply."""
    labels = []
    if costs.minimum > 0:
        labels.append(f"minimum de {costs.minimum:g} € par ordre non appliqué (ADR-025)")
    if costs.rounding == "cent":
        labels.append("frais non arrondis au centime (ADR-025)")
    return labels


def _total_return_factors(
    history: MarketHistory, days: np.ndarray, closes: np.ndarray
) -> tuple[np.ndarray, list[str]]:
    """Total-return factors on the window, 1 at its last session, and the instruments they move."""
    factors = np.ones_like(closes)
    moved = []
    for column, instrument_id in enumerate(history.instruments):
        actions = history.actions(instrument_id, moment=None)
        factors[:, column] = adjustment_factors(days, closes[:, column], actions, "total_return")
        if any(
            0 < int(np.searchsorted(days, np.datetime64(a.ex_date, "D"))) < len(days)
            for a in actions
        ):
            moved.append(instrument_id)
    return factors, moved


def _checked_frame(
    frame: object,
    sessions: Sequence[date],
    instruments: tuple[str, ...],
    known: np.ndarray,
) -> np.ndarray:
    """The weights a strategy decides at each session but the last, as the engine checks them.

    One row per session, zero for no weight; the decision of the last session is never filled.
    """
    if not isinstance(frame, pd.DataFrame) or not isinstance(frame.index, pd.DatetimeIndex):
        raise StrategyError("weights_frame : un DataFrame indexé par les séances est attendu")
    if frame.index.tz is not None or [s.date() for s in frame.index] != list(sessions):
        raise StrategyError("weights_frame : une ligne par séance de la fenêtre, dans l'ordre")
    outside = sorted(str(c) for c in frame.columns if c not in instruments)
    if outside:
        raise StrategyError(f"weights_frame : {', '.join(outside)} hors de l'univers")
    if frame.columns.has_duplicates:
        raise StrategyError("weights_frame : colonne en double")
    for kind in frame.dtypes:
        if pd.api.types.is_bool_dtype(kind) or not pd.api.types.is_numeric_dtype(kind):
            raise StrategyError("weights_frame : poids non numériques")
    weights = frame.reindex(columns=list(instruments)).to_numpy(dtype=float)[:-1]
    present = ~np.isnan(weights)
    filled = np.where(present, weights, 0.0)
    suspect = (present & (~np.isfinite(weights) | (weights < 0))).any(axis=1)
    suspect |= filled.sum(axis=1) > 1
    for row in np.flatnonzero(suspect):
        entries = {instruments[k]: float(weights[row, k]) for k in np.flatnonzero(present[row])}
        checked_weights(entries, instruments, sessions[row])
    blind = (filled > 0) & np.isnan(known[:-1])
    if blind.any():
        row, column = (int(x) for x in np.argwhere(blind)[0])
        raise StrategyError(
            f"décision du {sessions[row]} : poids sur {instruments[column]} sans aucun cours connu"
        )
    return filled


def screen(
    strategy: VectorStrategy,
    grid: Sequence[Params],
    history: MarketHistory,
    *,
    start: date,
    end: date,
    cutoff: time,
    costs: Costs,
    initial_cash: float,
) -> Screening:
    """Replay every combination of ``grid`` on [start, end] with vectorbt (ADR-025).

    StrategyError propagates, as in the engine: a weight the engine would refuse fails the
    whole screening rather than one combination.
    """
    vbt = _vectorbt()
    if not grid:
        raise ScreeningError("grille vide : rien à cribler")
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ScreeningError("le cash initial doit être positif")
    sessions, closes = engine.common_calendar(history, start, end)
    instruments = history.instruments
    width, count = len(instruments), len(sessions)
    days = np.array(sessions, dtype="datetime64[D]")
    known = engine.known_closes(history, sessions, cutoff)
    factors, moved = _total_return_factors(history, days, closes)
    approximations = _cost_approximations(costs) + [
        f"{i} : opérations sur titres approchées par des cours dividendes réinvestis, "
        "splits sans soulte (ADR-025)"
        for i in moved
    ]
    adjusted = closes * factors
    sizing = np.ones_like(closes)
    sizing[1:] = known[:-1] * factors[:-1]
    # No weight and no position where nothing is known yet: any finite price does there.
    sizing[~np.isfinite(sizing)] = 1.0
    index = pd.DatetimeIndex(days)
    points: list[ScreenPoint] = []
    for first in range(0, len(grid), BATCH):
        batch = grid[first : first + BATCH]
        size = np.full((count, width * len(batch)), np.nan)
        for slot, params in enumerate(batch):
            frame = strategy.weights_frame(history, params, sessions, cutoff)
            size[1:, slot * width : (slot + 1) * width] = _checked_frame(
                frame, sessions, instruments, known
            )
        columns = pd.MultiIndex.from_product(
            [range(len(batch)), instruments], names=["combinaison", "instrument"]
        )
        prices = pd.DataFrame(np.tile(adjusted, len(batch)), index=index, columns=columns)
        portfolio: Any = vbt.Portfolio.from_orders(
            close=prices,
            size=pd.DataFrame(size, index=index, columns=columns),
            size_type="targetpercent",
            direction="longonly",
            price=prices,
            val_price=pd.DataFrame(np.tile(sizing, len(batch)), index=index, columns=columns),
            fees=costs.commission,
            fixed_fees=0.0,
            slippage=costs.slippage,
            size_granularity=1.0,
            init_cash=initial_cash,
            cash_sharing=True,
            call_seq="auto",
            update_value=False,
            ffill_val_price=False,
            group_by=np.repeat(np.arange(len(batch)), width),
            freq="1D",
        )
        # One group gives a Series and a scalar: shape both as one column per combination.
        values = np.asarray(portfolio.value(), dtype=float).reshape(count, len(batch))
        orders = np.atleast_1d(np.asarray(portfolio.orders.count()))
        for slot, params in enumerate(batch):
            curve = pd.Series(values[:, slot], index=index, name="valeur")
            points.append(ScreenPoint(dict(params), curve, int(orders[slot])))
    return Screening(
        strategy=strategy.name,
        engine=f"vectorbt {vbt.__version__}",
        costs=costs.name,
        initial_cash=float(initial_cash),
        start=sessions[0],
        end=sessions[-1],
        points=tuple(points),
        approximations=tuple(approximations),
    )


@dataclass(frozen=True)
class CrossCheck:
    """The Sharpe ratios of one combination by the screening and by the reference engine."""

    params: dict[str, ParamValue]
    screening: float | None
    reference: float | None
    gap: float | None  # relative, |a − b| / |b|; absolute when b is zero; None if both are None
    value_gap: float  # largest relative gap of the value curves, for the diagnosis
    passed: bool


def relative_gap(value: float | None, reference: float | None) -> float | None:
    if value is None and reference is None:
        return None
    if value is None or reference is None:
        return math.inf
    spread = abs(value - reference)
    return spread / abs(reference) if reference else spread


def cross_check(
    strategy: VectorStrategy,
    grid: Sequence[Params],
    history: MarketHistory,
    *,
    start: date,
    end: date,
    cutoff: time,
    costs: Costs,
    initial_cash: float,
    sessions_per_year: int,
    tolerance: float,
    sample: Sequence[int] | None = None,
) -> list[CrossCheck]:
    """Replay a sample of the grid in both engines and compare their Sharpe ratios (D12).

    Only where the screening is exact: no minimum fee, no rounding, no corporate action in the
    window. ``sample`` holds indices into ``grid``; None replays every combination.
    """
    if costs.minimum or costs.rounding != "none":
        raise ScreeningError(
            "recoupement hors périmètre : frais sans minimum ni arrondi exigés (ADR-025, D12)"
        )
    chosen = [grid[k] for k in (range(len(grid)) if sample is None else sample)]
    found = screen(
        strategy,
        chosen,
        history,
        start=start,
        end=end,
        cutoff=cutoff,
        costs=costs,
        initial_cash=initial_cash,
    )
    if found.approximations:
        raise ScreeningError(
            "recoupement hors périmètre : " + " ; ".join(found.approximations) + " (D12)"
        )
    checks = []
    for point in found.points:
        result = engine.run(
            strategy,
            point.params,
            history,
            start=start,
            end=end,
            cutoff=cutoff,
            costs=costs,
            initial_cash=initial_cash,
        )
        reference = engine.measures(result, sessions_per_year).sharpe
        mine = point.sharpe(sessions_per_year)
        gap = relative_gap(mine, reference)
        curve = result.values.to_numpy()
        value_gap = float(np.max(np.abs(point.values.to_numpy() - curve) / np.abs(curve)))
        checks.append(
            CrossCheck(
                params=point.params,
                screening=mine,
                reference=reference,
                gap=gap,
                value_gap=value_gap,
                passed=gap is None or gap <= tolerance,
            )
        )
    return checks
