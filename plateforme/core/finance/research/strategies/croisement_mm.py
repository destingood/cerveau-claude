"""The demonstration strategy: a moving-average crossover with a cash fallback (D5, ADR-027).

At each decision, every instrument of the universe whose mean of the ``short`` last total-return
closes is above the mean of its ``long`` last ones gets an equal share 1/n of the portfolio; the
rest stays in cash. An instrument with fewer than ``long`` known closes stays out. Total-return
closes, adjusted with the actions known at the decision, keep a split or an ex-dividend drop from
reading as a trend reversal.

It is a textbook case of overfitting, with many window pairs to try: it exercises the trial
journal, the deflated Sharpe ratio and the PBO. It runs on the synthetic research dataset and its
fictitious costs; no investment conclusion can come out of it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time

import numpy as np
import pandas as pd

from core.finance.research.strategy import Params, StrategyError, Weights
from core.finance.research.view import MarketHistory, PointInTimeView


def windows(params: Params) -> tuple[int, int]:
    """The ``short`` and ``long`` windows, refused unless whole numbers with 1 <= short < long."""
    short, long = params.get("short"), params.get("long")
    if (
        not isinstance(short, int)
        or not isinstance(long, int)
        or isinstance(short, bool)
        or isinstance(long, bool)
    ):
        raise StrategyError("croisement : les fenêtres short et long sont des nombres entiers")
    if not 1 <= short < long:
        raise StrategyError(f"croisement : fenêtres {short} et {long}, 1 <= short < long attendu")
    return short, long


@dataclass(frozen=True)
class MovingAverageCrossover:
    name: str = "croisement de moyennes mobiles"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        short, long = windows(params)
        share = 1.0 / len(view.instruments)
        weights: dict[str, float] = {}
        for instrument_id, (fast, slow) in self._means(view, short, long).items():
            if fast is not None and slow is not None and fast > slow:
                weights[instrument_id] = share
        return weights

    def indicators(
        self, view: PointInTimeView, params: Params
    ) -> dict[str, dict[str, float | None]]:
        """Both means of each instrument at the decision, None while too few closes are known."""
        short, long = windows(params)
        return {
            instrument_id: {"moyenne_courte": fast, "moyenne_longue": slow}
            for instrument_id, (fast, slow) in self._means(view, short, long).items()
        }

    def weights_frame(
        self, history: MarketHistory, params: Params, sessions: Sequence[date], cutoff: time
    ) -> pd.DataFrame:
        """``decide`` replayed at every session [Hypothèse].

        Late prints, revisions and adjustments known only from a later date leave no closed form
        that stays point-in-time: the replay is exact by construction, and the truncation check
        of the protocol compares it with ``decide`` on a sample.
        """
        rows = [self.decide(history.view(day, cutoff), params) for day in sessions]
        return pd.DataFrame(
            rows, index=pd.DatetimeIndex(sessions), columns=list(history.instruments), dtype=float
        )

    @staticmethod
    def _means(
        view: PointInTimeView, short: int, long: int
    ) -> dict[str, tuple[float | None, float | None]]:
        means: dict[str, tuple[float | None, float | None]] = {}
        for instrument_id in view.instruments:
            _, known = view.values(instrument_id, adjust="total_return")
            if len(known) < long:
                means[instrument_id] = (None, None)
                continue
            means[instrument_id] = (float(np.mean(known[-short:])), float(np.mean(known[-long:])))
        return means
