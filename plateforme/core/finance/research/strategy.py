"""The strategy contract: target weights from the data known at the decision date (ADR-024).

A strategy is pure: ``decide(view, params)`` reads only its PointInTimeView and its parameters,
with no I/O, no clock and no unseeded randomness. The same object runs in the in-house engine,
in the NautilusTrader adapter and, from phase 4, in paper trading: only the adapter changes.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping, Sequence
from datetime import date, time
from numbers import Real
from typing import Protocol

import pandas as pd

from core.finance.research.view import MarketHistory, PointInTimeView

Params = Mapping[str, int | float | str | bool]
Weights = Mapping[str, float]

WEIGHT_SLACK = 1e-9  # a sum of weights may pass 1 by rounding, never by leverage


class StrategyError(ValueError):
    """A strategy broke its contract: the backtest stops and the protocol fails."""


class Strategy(Protocol):
    @property
    def name(self) -> str: ...

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        """Target weights at the view's date: long only, summing to 1 at most, the rest cash."""
        ...


class VectorStrategy(Strategy, Protocol):
    """A strategy with an optional vectorised form, for the screening (ADR-024, ADR-025)."""

    def weights_frame(
        self, history: MarketHistory, params: Params, sessions: Sequence[date], cutoff: time
    ) -> pd.DataFrame:
        """The weights of every decision of ``sessions`` at once.

        One row per session, in order, one column per instrument, NaN for no weight. It reads
        whole arrays, where the view cannot guard a ``shift(-1)``: the truncation-invariance check
        proves on a sample that it gives back ``decide`` (ADR-026).
        """
        ...


def checked_weights(weights: object, universe: Collection[str], day: object) -> dict[str, float]:
    """The weights of a decision, refused unless finite, >= 0, inside the universe, sum <= 1."""
    if not isinstance(weights, Mapping):
        raise StrategyError(f"décision du {day} : un dictionnaire de poids est attendu")
    checked: dict[str, float] = {}
    for instrument_id, weight in weights.items():
        if instrument_id not in universe:
            raise StrategyError(f"décision du {day} : {instrument_id} hors de l'univers")
        if isinstance(weight, bool) or not isinstance(weight, Real):
            raise StrategyError(f"décision du {day} : poids non numérique pour {instrument_id}")
        value = float(weight)
        if not math.isfinite(value) or value < 0:
            raise StrategyError(
                f"décision du {day} : poids {value} pour {instrument_id} (ni découvert ni infini)"
            )
        if value:
            checked[instrument_id] = value
    total = math.fsum(checked.values())
    if total > 1 + WEIGHT_SLACK:
        raise StrategyError(f"décision du {day} : poids de somme {total:.6f} > 1 (pas de levier)")
    return checked
