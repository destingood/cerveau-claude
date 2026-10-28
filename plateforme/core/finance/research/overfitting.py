"""The statistics of the anti-overfitting protocol: walk-forward, DSR and PBO (ADR-026).

Plain functions of daily net return matrices, one row per session and one column per grid
configuration, written from the two papers read for ADR-026:

- the deflated Sharpe ratio of Bailey and López de Prado (SSRN 2460551, 2014);
- the probability of backtest overfitting of Bailey, Borwein, López de Prado and Zhu, by
  combinatorially symmetric cross-validation (CSCV, §2.2, February 2015 revision).

A configuration whose returns have no spread has a Sharpe ratio of 0 here, wherever it is ranked
[Hypothèse]. Nothing here reaches the store, the network or a model (R1).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np

EULER_GAMMA = 0.5772156649015329  # Euler–Mascheroni constant, as in the DSR paper
PBO_CHUNK = 1024  # CSCV combinations per vectorised step: bounds the memory of a large grid

_NORMAL = NormalDist()


class OverfittingError(ValueError):
    """A statistic asked of data that cannot carry it."""


def _matrix(returns: np.ndarray) -> np.ndarray:
    matrix = np.asarray(returns, dtype=float)
    if matrix.ndim != 2 or not matrix.size:
        raise OverfittingError("une matrice séances × configurations est attendue")
    if not np.isfinite(matrix).all():
        raise OverfittingError("rendement non fini dans la matrice")
    return matrix


def column_sharpes(returns: np.ndarray) -> np.ndarray:
    """The per-period Sharpe ratio of each column (ddof = 1), 0 where a column has no spread."""
    matrix = _matrix(returns)
    if len(matrix) < 2:
        raise OverfittingError("au moins deux rendements par configuration")
    spread = matrix.std(axis=0, ddof=1)
    mean = matrix.mean(axis=0)
    return np.divide(mean, spread, out=np.zeros_like(mean), where=spread > 0)


def best_column(returns: np.ndarray) -> int:
    """The column with the best Sharpe ratio; on a tie, the first of the grid."""
    return int(np.argmax(column_sharpes(returns)))


# Walk-forward ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fold:
    """Fold k learns on the rows of blocks 1..k and tests on block k+1 (anchored, D8)."""

    train: range  # row indices of the returns
    test: range
    chosen: int  # the column with the best training Sharpe ratio


@dataclass(frozen=True)
class WalkForward:
    folds: tuple[Fold, ...]
    returns: np.ndarray  # out-of-sample returns of the chosen columns, folds end to end


def walk_forward(returns: np.ndarray, blocks: int) -> WalkForward:
    """Anchored walk-forward over equal blocks of rows, equal to within one row (ADR-026).

    The transition between two folds costs nothing here [Hypothèse]: each column runs once,
    continuously, and the test block of a fold reads the returns of the chosen column.
    """
    matrix = _matrix(returns)
    if blocks < 2:
        raise OverfittingError("au moins deux blocs pour un walk-forward")
    if len(matrix) < 2 * blocks:
        raise OverfittingError(
            f"{len(matrix)} rendements pour {blocks} blocs : deux rendements par bloc au moins"
        )
    bounds = [int(chunk[0]) for chunk in np.array_split(np.arange(len(matrix)), blocks)]
    bounds.append(len(matrix))
    folds = []
    for k in range(1, blocks):
        train, test = range(0, bounds[k]), range(bounds[k], bounds[k + 1])
        folds.append(Fold(train, test, best_column(matrix[train.start : train.stop])))
    tested = np.concatenate([matrix[f.test.start : f.test.stop, f.chosen] for f in folds])
    return WalkForward(tuple(folds), tested)


# Deflated Sharpe ratio -------------------------------------------------------------------------


def moments(returns: Sequence[float]) -> tuple[float, float]:
    """Skewness γ₃ and non-excess kurtosis γ₄, from population moments [Hypothèse].

    The paper leaves the estimator open; these are scipy's defaults (``bias=True``).
    """
    values = np.asarray(returns, dtype=float)
    # Equal values have no dispersion, whatever the rounding of their mean leaves.
    if values.size == 0 or values.min() == values.max():
        raise OverfittingError("rendements sans dispersion : moments non définis")
    centred = values - values.mean()
    m2 = float(np.mean(centred**2))
    if m2 == 0:
        raise OverfittingError("rendements sans dispersion : moments non définis")
    return float(np.mean(centred**3)) / m2**1.5, float(np.mean(centred**4)) / m2**2


def expected_max_sharpe(trials: int, variance: float) -> float:
    """SR₀ = √V·((1−γ)·Z⁻¹[1 − 1/N] + γ·Z⁻¹[1 − 1/(N·e)]); 0 when N = 1 or V = 0."""
    if trials < 1:
        raise OverfittingError("au moins un essai")
    if not math.isfinite(variance) or variance < 0:
        raise OverfittingError("variance des Sharpe négative ou non finie")
    if trials == 1 or variance == 0:
        return 0.0
    return math.sqrt(variance) * (
        (1 - EULER_GAMMA) * _NORMAL.inv_cdf(1 - 1 / trials)
        + EULER_GAMMA * _NORMAL.inv_cdf(1 - 1 / (trials * math.e))
    )


def deflated_sharpe(
    sharpe: float,
    sessions: int,
    skewness: float,
    kurtosis: float,
    threshold: float,
) -> float | None:
    """DSR = Z[(SR − SR₀)·√(T−1) / √(1 − γ₃·SR + (γ₄−1)/4·SR²)], per-period SR and SR₀.

    None when the denominator is not positive: the formula does not apply to such moments.
    """
    if sessions < 2:
        raise OverfittingError("au moins deux rendements pour un DSR")
    spread = 1 - skewness * sharpe + (kurtosis - 1) / 4 * sharpe**2
    if not spread > 0:
        return None
    return _NORMAL.cdf((sharpe - threshold) * math.sqrt(sessions - 1) / math.sqrt(spread))


def trial_variance(sharpes: Sequence[float | None]) -> float:
    """V: the variance (ddof = 1) of the per-period Sharpe ratios of a family; 0 for one trial.

    A trial without spread (None) counts for 0 [Hypothèse].
    """
    values = [0.0 if s is None else s for s in sharpes]
    if not values:
        raise OverfittingError("aucun essai dans la famille")
    return 0.0 if len(values) == 1 else float(np.var(values, ddof=1))


# Probability of backtest overfitting (CSCV) ----------------------------------------------------


@dataclass(frozen=True)
class Pbo:
    value: float | None  # share of the combinations whose logit λ ≤ 0; None if not evaluable
    partitions: int  # S
    combinations: int  # C(S, S/2)
    configurations: int  # N
    rows: int  # rows kept: T − (T mod S)
    dropped: int  # the first T mod S rows, set aside
    reason: str | None = None  # why it is not evaluable


def _sharpes(count: int, means: np.ndarray, m2: np.ndarray) -> np.ndarray:
    variance = np.clip(m2, 0.0, None) / (count - 1)
    spread = np.sqrt(variance)
    return np.divide(means, spread, out=np.zeros_like(means), where=spread > 0)


def pbo(returns: np.ndarray, partitions: int) -> Pbo:
    """The CSCV probability of backtest overfitting over ``partitions`` blocks of rows.

    For each choice of S/2 training blocks: n* is the column with the best training Sharpe
    ratio (the first on a tie), ω̄ its rank among the test Sharpe ratios over N + 1 (ascending,
    ties at their mean rank) and λ = ln(ω̄ / (1 − ω̄)). The PBO is the share of λ ≤ 0. Block
    moments are pooled exactly (Chan et al.), so that each combination costs no pass over rows.
    """
    matrix = _matrix(returns)
    if partitions < 2 or partitions % 2:
        raise OverfittingError("CSCV : un nombre pair de blocs est attendu")
    rows, configurations = matrix.shape
    dropped = rows % partitions
    size = rows // partitions
    half = partitions // 2
    combinations = math.comb(partitions, half)
    found = Pbo(None, partitions, combinations, configurations, rows - dropped, dropped)
    if configurations < 2:
        return Pbo(**(found.__dict__ | {"reason": "moins de deux configurations"}))
    if size < 2:
        return Pbo(
            **(found.__dict__ | {"reason": f"{rows} rendements pour {partitions} blocs : trop peu"})
        )
    blocks = matrix[dropped:].reshape(partitions, size, configurations)
    block_means = blocks.mean(axis=1)
    block_m2 = ((blocks - block_means[:, None, :]) ** 2).sum(axis=1)
    squares = block_means**2
    count = half * size
    overfit = 0
    chosen = list(itertools.combinations(range(partitions), half))
    for first in range(0, combinations, PBO_CHUNK):
        train = np.zeros((len(chosen[first : first + PBO_CHUNK]), partitions))
        for row, blocks_in in enumerate(chosen[first : first + PBO_CHUNK]):
            train[row, list(blocks_in)] = 1.0
        sides = []
        for side in (train, 1.0 - train):
            means = side @ block_means / half
            m2 = side @ block_m2 + size * (side @ squares - half * means**2)
            sides.append(_sharpes(count, means, m2))
        learned, tested = sides
        best = np.argmax(learned, axis=1)
        score = tested[np.arange(len(best)), best][:, None]
        rank = (tested < score).sum(axis=1) + ((tested == score).sum(axis=1) + 1) / 2
        omega = rank / (configurations + 1)
        overfit += int(np.count_nonzero(np.log(omega / (1 - omega)) <= 0))
    return Pbo(**(found.__dict__ | {"value": overfit / combinations}))
