"""Truncation invariance: a decision must not change when the data after it is cut off (R10).

The view refuses any read past the decision (``LookAheadError``). Two leaks escape it: the
vectorised form (``weights_frame``) receives whole arrays, where a ``shift(-1)`` goes unnoticed,
and a strategy may reach around its view. The check recomputes the decisions of a sample of days
on a history physically cut at each decision and compares them with the full pass; it also
proves that ``weights_frame`` gives back ``decide``. It runs in every protocol (ADR-026), not only
in the tests.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, time
from typing import Literal

import pandas as pd

from core.finance.research.strategy import Params, Strategy, StrategyError, checked_weights
from core.finance.research.view import MarketHistory

FRAME_TOLERANCE = 1e-9  # a vectorised sum may differ from a loop by rounding, never by a signal

Check = Literal["decide", "weights_frame", "decide_vs_frame"]


@dataclass(frozen=True)
class Breach:
    """A sampled day whose decision depends on data published after it: échec R10."""

    day: date
    check: Check
    detail: str


def _gaps(first: Mapping[str, float], second: Mapping[str, float], tolerance: float) -> list[str]:
    gaps: list[str] = []
    for instrument_id in sorted(set(first) | set(second)):
        a, b = first.get(instrument_id, 0.0), second.get(instrument_id, 0.0)
        if abs(a - b) > tolerance:
            gaps.append(f"{instrument_id} : {a:.6g} contre {b:.6g}")
    return gaps


def _frame(
    strategy: Strategy,
    history: MarketHistory,
    params: Params,
    sessions: Sequence[date],
    cutoff: time,
) -> pd.DataFrame:
    frame = strategy.weights_frame(history, params, sessions, cutoff)  # type: ignore[attr-defined]
    if not isinstance(frame, pd.DataFrame) or list(frame.index) != [
        pd.Timestamp(s) for s in sessions
    ]:
        raise StrategyError("weights_frame : une ligne par séance demandée, dans l'ordre")
    return frame


def _row(frame: pd.DataFrame, day: date, universe: Collection[str]) -> dict[str, float]:
    return checked_weights(frame.loc[pd.Timestamp(day)].fillna(0.0).to_dict(), universe, day)


def truncation_breaches(
    strategy: Strategy,
    params: Params,
    history: MarketHistory,
    *,
    sessions: Sequence[date],
    sample: Collection[date],
    cutoff: time,
) -> list[Breach]:
    """The sampled days whose decision depends on data published after it; empty if invariant.

    ``sessions`` are the decision days of the backtest and ``sample`` the days checked among
    them. ``decide`` must give the same weights exactly; ``weights_frame``, when the strategy
    has one, must give the same row on the cut history and match ``decide`` within
    ``FRAME_TOLERANCE``. A ``LookAheadError`` raised by ``decide`` propagates: it is already a
    failure.
    """
    calendar = sorted(sessions)
    outside = sorted(set(sample) - set(calendar))
    if outside:
        raise ValueError(f"jour {outside[0]:%d/%m/%Y} hors des séances du backtest")
    universe = history.instruments
    vector = callable(getattr(strategy, "weights_frame", None))
    whole_frame = _frame(strategy, history, params, calendar, cutoff) if vector else None
    breaches: list[Breach] = []
    for day in sorted(sample):
        cut = history.cut(day, cutoff)
        whole = checked_weights(strategy.decide(history.view(day, cutoff), params), universe, day)
        alone = checked_weights(strategy.decide(cut.view(day, cutoff), params), universe, day)
        if gaps := _gaps(whole, alone, 0.0):
            breaches.append(Breach(day, "decide", "; ".join(gaps)))
        if whole_frame is None:
            continue
        row = _row(whole_frame, day, universe)
        known = [s for s in calendar if s <= day]
        cut_row = _row(_frame(strategy, cut, params, known, cutoff), day, universe)
        if gaps := _gaps(row, cut_row, FRAME_TOLERANCE):
            breaches.append(Breach(day, "weights_frame", "; ".join(gaps)))
        if gaps := _gaps(row, whole, FRAME_TOLERANCE):
            breaches.append(Breach(day, "decide_vs_frame", "; ".join(gaps)))
    return breaches
