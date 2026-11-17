"""Calibration scores of resolved forecasts (section 11, ADR-064): deterministic, no model (R1).

A probability forecast is scored by the Brier score, the mean of ``(p - o)²`` where ``o`` is 1 when
the event happened and 0 otherwise: 0 is perfect, 0.25 is what a constant 50 % earns, 1 is always
certain and always wrong. Murphy's decomposition (Murphy 1973) splits it over bins of forecasts into
reliability (lower is better), resolution (higher is better) and the uncertainty of the outcomes;
with binned forecasts ``reliability - resolution + uncertainty`` equals the Brier score of the bin
means, which differs from the plain score by the spread of forecasts inside each bin.

An estimate is scored by its absolute error and, when the actual value is not zero, its relative
error.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

DEFAULT_BINS = 10


class CalibrationError(ValueError):
    """The scores cannot be computed from these values."""


@dataclass(frozen=True)
class ReliabilityBin:
    lower: float
    upper: float
    count: int
    mean_forecast: float
    observed_rate: float


@dataclass(frozen=True)
class ProbabilityScores:
    count: int
    brier: float
    reliability: float
    resolution: float
    uncertainty: float
    base_rate: float
    bins: tuple[ReliabilityBin, ...]


@dataclass(frozen=True)
class EstimateScores:
    count: int
    mean_absolute_error: float
    relative_count: int  # estimates whose actual value is not zero
    mean_relative_error: float | None


def _probability(value: float) -> float:
    if not (math.isfinite(value) and 0.0 <= value <= 1.0):
        raise CalibrationError(f"probabilité hors de [0, 1] : {value!r}")
    return float(value)


def brier(pairs: Sequence[tuple[float, bool]]) -> float:
    """Mean squared difference between each probability and its outcome (0 or 1)."""
    if not pairs:
        raise CalibrationError("aucune prévision résolue")
    total = math.fsum((_probability(p) - (1.0 if o else 0.0)) ** 2 for p, o in pairs)
    return total / len(pairs)


def _bin_index(p: float, bins: int) -> int:
    return min(int(p * bins), bins - 1)  # 1.0 falls in the last bin


def probability_scores(
    pairs: Sequence[tuple[float, bool]], *, bins: int = DEFAULT_BINS
) -> ProbabilityScores:
    """Brier score, Murphy's decomposition and the reliability table over ``bins`` equal bins."""
    if bins < 1:
        raise CalibrationError("au moins une classe")
    score = brier(pairs)
    n = len(pairs)
    base = sum(1 for _, o in pairs if o) / n
    grouped: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for p, o in pairs:
        grouped[_bin_index(p, bins)].append((p, o))
    table: list[ReliabilityBin] = []
    reliability = resolution = 0.0
    for index, members in enumerate(grouped):
        if not members:
            continue
        count = len(members)
        mean_p = math.fsum(p for p, _ in members) / count
        rate = sum(1 for _, o in members if o) / count
        reliability += count * (mean_p - rate) ** 2
        resolution += count * (rate - base) ** 2
        table.append(ReliabilityBin(index / bins, (index + 1) / bins, count, mean_p, rate))
    return ProbabilityScores(
        count=n,
        brier=score,
        reliability=reliability / n,
        resolution=resolution / n,
        uncertainty=base * (1.0 - base),
        base_rate=base,
        bins=tuple(table),
    )


def estimate_scores(pairs: Sequence[tuple[float, float]]) -> EstimateScores:
    """Mean absolute error and mean relative error of ``(estimate, actual)`` pairs."""
    if not pairs:
        raise CalibrationError("aucune estimation résolue")
    for estimate, actual in pairs:
        if not (math.isfinite(estimate) and math.isfinite(actual)):
            raise CalibrationError("valeur non finie")
    absolute = math.fsum(abs(e - a) for e, a in pairs) / len(pairs)
    relative = [abs(e - a) / abs(a) for e, a in pairs if a != 0]
    return EstimateScores(
        count=len(pairs),
        mean_absolute_error=absolute,
        relative_count=len(relative),
        mean_relative_error=math.fsum(relative) / len(relative) if relative else None,
    )


def calibration_drift(recent: float, baseline: float, max_increase: float) -> bool:
    """True when the recent Brier score exceeds the baseline by more than ``max_increase``
    (section 8.3: a calibration drift demotes)."""
    for value in (recent, baseline):
        _probability(value)  # a Brier score lies in [0, 1] too
    if not (math.isfinite(max_increase) and max_increase >= 0):
        raise CalibrationError("écart maximal négatif ou non fini")
    return recent - baseline > max_increase
