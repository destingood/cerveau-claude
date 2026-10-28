"""Price adjustment computed at read time from the corporate actions known then (R10, ADR-012).

A provider's adjusted series is recomputed backwards at every split or dividend, so it already
contains events that were unknown on earlier dates. CERVEAU stores raw closes and adjusts them
here, with the actions visible at ``as_of`` only. An action applies once a session on or after its
ex-date is in the series: the last close therefore always equals the raw close.

- split of ratio r (new shares per old share): earlier closes are divided by r;
- cash dividend D (total return): earlier closes are multiplied by 1 − D / P, where P is the
  previous close expressed in shares of the ex-date (after the splits between the two).
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from datetime import date
from itertools import pairwise
from math import prod
from typing import Literal

import numpy as np

from core.finance.model import CorporateAction

Adjustment = Literal["none", "split", "total_return"]


class AdjustmentError(ValueError):
    """The corporate actions contradict the prices (a dividend above the previous close)."""


def is_effective(sessions: Sequence[date], action: CorporateAction) -> bool:
    """True when the series has closes both before and on or after the ex-date."""
    return 0 < bisect_left(sessions, action.ex_date) < len(sessions)


def adjusted_closes(
    sessions: Sequence[date],
    closes: Sequence[float],
    actions: Sequence[CorporateAction],
    mode: Adjustment,
) -> list[float]:
    if len(sessions) != len(closes):
        raise ValueError("autant de séances que de cours")
    if any(b <= a for a, b in pairwise(sessions)):
        raise ValueError("séances strictement croissantes attendues")
    if mode == "none":
        return list(closes)
    values = np.asarray(closes, dtype=float)
    days = np.array(sessions, dtype="datetime64[D]")
    return (values * adjustment_factors(days, values, actions, mode)).tolist()


def adjustment_factors(
    sessions: np.ndarray,
    closes: np.ndarray,
    actions: Sequence[CorporateAction],
    mode: Adjustment,
) -> np.ndarray:
    """The factor of each close, for ``datetime64[D]`` sessions in strictly increasing order.

    The core of adjusted_closes, on arrays: the backtest view adjusts a series at every decision
    date and cannot afford a loop over the sessions. Each factor is the product of the same
    floats in the same order, so both give the same closes to the last bit.
    """
    factors = np.ones(len(closes))
    if mode == "none":
        return factors
    splits = [a for a in actions if a.kind == "split"]
    for action in sorted(actions, key=lambda a: (a.ex_date, a.kind)):
        first = int(np.searchsorted(sessions, np.datetime64(action.ex_date, "D")))
        if not 0 < first < len(sessions):  # is_effective
            continue
        if action.kind == "split":
            factor = 1 / action.value
        elif mode == "total_return":
            previous = sessions[first - 1]
            between = [s.value for s in splits if previous < s.ex_date <= action.ex_date]
            factor = 1 - action.value * prod(between) / float(closes[first - 1])
            if factor <= 0:
                raise AdjustmentError(
                    f"{action.instrument_id} : dividende du {action.ex_date} supérieur ou égal "
                    "au cours précédent"
                )
        else:
            continue
        factors[:first] *= factor
    return factors
