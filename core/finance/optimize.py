"""Portfolio optimizers of the rebalancing proposal (plan of phase 2, F4; ADR-019).

Checked wrappers around skfolio 1.8: each takes the daily returns of the securities, their
current weights and the constraints, and returns long-only weights that sum to one, without
leverage. The covariance is shrunk with Ledoit-Wolf. A constraint a method cannot honour is
refused with its reason, never dropped, and the solution is checked against every constraint
before it is returned. Pure functions: no store, no configuration file, no network.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, get_args

import cvxpy as cp
import numpy as np
from skfolio import RiskMeasure
from skfolio.exceptions import SkfolioError
from skfolio.moments import LedoitWolf
from skfolio.optimization import (
    HierarchicalRiskParity,
    MeanRisk,
    ObjectiveFunction,
    RiskBudgeting,
)
from skfolio.prior import EmpiricalPrior

from core.finance.risk import Matrix, RiskError, Vector

Method = Literal[
    "variance_minimale", "cvar_minimale", "parite_de_risque", "hrp", "moyenne_variance"
]
METHODS: tuple[Method, ...] = get_args(Method)
# skfolio takes a total turnover cap only through the cvxpy problem of MeanRisk (ADR-019).
TURNOVER_METHODS: frozenset[Method] = frozenset(
    {"variance_minimale", "cvar_minimale", "moyenne_variance"}
)
SECTOR_METHODS: frozenset[Method] = TURNOVER_METHODS | {"parite_de_risque"}
TOLERANCE = 1e-6  # on a weight, a sector sum or the turnover; above it, the solution is refused
RESIDUE = 1e-9  # a weight below it is a solver residue and set to zero


@dataclass(frozen=True)
class Group:
    """A cap on the total weight of some lines (a sector)."""

    members: tuple[int, ...]
    cap: float


@dataclass(frozen=True)
class Constraints:
    max_weight: float = 1.0
    groups: tuple[Group, ...] = ()
    max_turnover: float | None = None  # sum of |w - w0|, as skfolio's Portfolio.turnover


@dataclass(frozen=True)
class Solution:
    weights: Vector
    covariance: Matrix  # shrunk, the one the optimizer used (maximum likelihood, ddof = 0)


def turnover(weights: Vector, previous: Vector) -> float:
    return float(np.abs(weights - previous).sum())


def check_feasible(method: Method, n: int, constraints: Constraints) -> None:
    """Refuse, before solving, what a method cannot honour or no portfolio can satisfy."""
    if n < 2:
        raise RiskError("au moins deux titres sont nécessaires pour optimiser")
    if constraints.max_turnover is not None and method not in TURNOVER_METHODS:
        raise RiskError(
            f"rotation maximale non prise en charge par la méthode {method} : seules "
            "variance_minimale, cvar_minimale et moyenne_variance l'acceptent"
        )
    if constraints.groups and method not in SECTOR_METHODS:
        raise RiskError(f"plafonds sectoriels non pris en charge par la méthode {method}")
    if constraints.max_weight * n < 1 - TOLERANCE:
        raise RiskError("poids maximal trop bas : les titres ne peuvent pas totaliser 100 %")
    grouped = {i for group in constraints.groups for i in group.members}
    room = (n - len(grouped)) * constraints.max_weight + sum(
        min(group.cap, len(group.members) * constraints.max_weight) for group in constraints.groups
    )
    if room < 1 - TOLERANCE:
        raise RiskError("plafonds sectoriels trop bas : les titres ne peuvent pas totaliser 100 %")


def _prior() -> EmpiricalPrior:
    return EmpiricalPrior(covariance_estimator=LedoitWolf())


def _inequalities(groups: Sequence[Group], n: int) -> dict[str, Matrix]:
    if not groups:
        return {}
    left = np.zeros((len(groups), n))
    for row, group in enumerate(groups):
        left[row, list(group.members)] = 1.0
    return {
        "left_inequality": left,
        "right_inequality": np.array([group.cap for group in groups], dtype=float),
    }


def _model(
    method: Method,
    previous: Vector,
    constraints: Constraints,
    *,
    cvar_beta: float,
    risk_aversion: float | None,
) -> MeanRisk | RiskBudgeting | HierarchicalRiskParity:
    bounds = {"min_weights": 0.0, "max_weights": constraints.max_weight}
    if method == "hrp":
        return HierarchicalRiskParity(prior_estimator=_prior(), **bounds)
    inequalities = _inequalities(constraints.groups, len(previous))
    if method == "parite_de_risque":
        return RiskBudgeting(prior_estimator=_prior(), **bounds, **inequalities)
    cap = constraints.max_turnover
    extra = {} if cap is None else {"add_constraints": lambda w: [cp.norm1(w - previous) <= cap]}
    if method == "moyenne_variance":
        if risk_aversion is None:
            raise RiskError("moyenne-variance : aversion au risque inconnue")
        return MeanRisk(
            objective_function=ObjectiveFunction.MAXIMIZE_UTILITY,
            risk_aversion=risk_aversion,
            prior_estimator=_prior(),
            **bounds,
            **inequalities,
            **extra,
        )
    measure = RiskMeasure.CVAR if method == "cvar_minimale" else RiskMeasure.VARIANCE
    return MeanRisk(
        objective_function=ObjectiveFunction.MINIMIZE_RISK,
        risk_measure=measure,
        cvar_beta=cvar_beta,
        prior_estimator=_prior(),
        **bounds,
        **inequalities,
        **extra,
    )


def _check(weights: Vector, previous: Vector, constraints: Constraints) -> None:
    if abs(weights.sum() - 1.0) > TOLERANCE or weights.min() < -TOLERANCE:
        raise RiskError("solution refusée : poids négatifs ou de somme différente de 100 %")
    if weights.max() > constraints.max_weight + TOLERANCE:
        raise RiskError("solution refusée : poids maximal dépassé")
    for group in constraints.groups:
        if weights[list(group.members)].sum() > group.cap + TOLERANCE:
            raise RiskError("solution refusée : plafond sectoriel dépassé")
    cap = constraints.max_turnover
    if cap is not None and turnover(weights, previous) > cap + TOLERANCE:
        raise RiskError("solution refusée : rotation maximale dépassée")


def optimize(
    method: Method,
    returns: Matrix,
    previous: Vector,
    constraints: Constraints,
    *,
    cvar_beta: float = 0.95,
    risk_aversion: float | None = None,
) -> Solution:
    """``returns``: one row per session, one column per security; ``previous``: the current
    weights within the securities (they sum to one)."""
    n = returns.shape[1]
    if previous.shape != (n,):
        raise RiskError("poids actuels : un par titre")
    check_feasible(method, n, constraints)
    if np.any(np.ptp(returns, axis=0) == 0):
        raise RiskError("optimisation : un titre a une variance nulle sur la fenêtre")
    model = _model(method, previous, constraints, cvar_beta=cvar_beta, risk_aversion=risk_aversion)
    try:
        model.fit(returns)
    except (SkfolioError, cp.error.SolverError, ValueError) as exc:
        raise RiskError(
            "optimisation impossible : contraintes incompatibles entre elles ou avec les poids "
            "actuels"
        ) from exc
    raw = np.asarray(model.weights_, dtype=float)
    if not np.all(np.isfinite(raw)):
        raise RiskError("optimisation impossible : le solveur n'a pas convergé")
    weights = np.where(raw < RESIDUE, 0.0, raw)
    weights = weights / weights.sum()
    _check(weights, previous, constraints)
    covariance = np.asarray(model.prior_estimator_.return_distribution_.covariance, dtype=float)
    return Solution(weights, covariance)


__all__ = [
    "METHODS",
    "SECTOR_METHODS",
    "TOLERANCE",
    "TURNOVER_METHODS",
    "Constraints",
    "Group",
    "Method",
    "Solution",
    "check_feasible",
    "optimize",
    "turnover",
]
