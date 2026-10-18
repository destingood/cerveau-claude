"""Portfolio optimizers against independent calculations (ADR-019).

The shrunk covariance against the formula of Ledoit and Wolf (2004) written here, the minimum
variance and the mean-variance optimum against scipy (SLSQP), the minimum CVaR against the linear
programme of Rockafellar and Uryasev (scipy, HiGHS), the closed forms with two securities, and
Hypothesis properties: weights summing to one, bounds, sector caps and turnover honoured.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from scipy.optimize import linprog, minimize

from core.config.loader import load_config
from core.finance import risk
from core.finance.fixtures import REFERENCE_READ_AT, reference_store
from core.finance.optimize import (
    TOLERANCE,
    Constraints,
    Group,
    Method,
    check_feasible,
    optimize,
    turnover,
)
from core.finance.rebalance import (
    MAX_SECTOR_CAPS,
    RebalanceProposal,
    SectorCap,
    rebalance_proposal,
)
from core.finance.risk import RiskError
from core.finance.store import FinanceStore
from core.finance.views import ViewError

ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(ROOT / "config")
SOLVER_REL = 1e-5  # two solvers agree on an optimum value to this relative precision (ADR-019)
WEIGHT_ABS = 1e-3  # and on the weights of a strictly convex problem to this absolute precision


def synthetic_returns(seed: int, n: int, sessions: int) -> np.ndarray:
    """Correlated daily returns of ``n`` securities, well conditioned."""
    rng = np.random.default_rng(seed)
    common = rng.normal(size=(sessions, n)) @ rng.normal(size=(n, n)) * 0.008
    return common + rng.normal(0.0, 0.006, (sessions, n)) + rng.normal(0.0, 0.0005, n)


def ledoit_wolf(returns: np.ndarray) -> np.ndarray:
    """Ledoit and Wolf (2004), shrinkage toward a multiple of the identity, as written there."""
    t, p = returns.shape
    centred = returns - returns.mean(axis=0)
    sample = centred.T @ centred / t
    mu = np.trace(sample) / p
    d2 = np.sum((sample - mu * np.eye(p)) ** 2) / p
    b2 = sum(np.sum((np.outer(row, row) - sample) ** 2) for row in centred) / t**2 / p
    delta = min(b2, d2) / d2
    return delta * mu * np.eye(p) + (1 - delta) * sample


def scipy_minimum(
    objective: object, n: int, upper: float, previous: np.ndarray | None = None, cap: float = 0.0
) -> np.ndarray:
    """SLSQP over long-only weights summing to one; with ``previous``, the turnover is split into
    purchases ``u`` and sales ``v`` (w = w0 + u − v, Σ(u + v) ≤ cap) to stay smooth."""
    if previous is None:
        result = minimize(
            objective,
            np.full(n, 1 / n),
            method="SLSQP",
            bounds=[(0.0, upper)] * n,
            constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
            options={"ftol": 1e-15, "maxiter": 2000},
        )
        assert result.success
        return result.x

    def weights(z: np.ndarray) -> np.ndarray:
        return previous + z[:n] - z[n:]

    result = minimize(
        lambda z: objective(weights(z)),  # type: ignore[operator]
        np.zeros(2 * n),
        method="SLSQP",
        bounds=[(0.0, None)] * (2 * n),
        constraints=[
            {"type": "eq", "fun": lambda z: weights(z).sum() - 1.0},
            {"type": "ineq", "fun": lambda z: cap - z.sum()},
            {"type": "ineq", "fun": lambda z: weights(z)},
            {"type": "ineq", "fun": lambda z: upper - weights(z)},
        ],
        options={"ftol": 1e-15, "maxiter": 2000},
    )
    assert result.success
    return weights(result.x)


def historical_cvar(returns: np.ndarray, weights: np.ndarray, beta: float) -> float:
    """min over α of α + Σ max(loss − α, 0) / ((1 − β) T): the minimum lies at a loss."""
    losses = -(returns @ weights)
    tail = 1.0 / ((1.0 - beta) * len(losses))
    return min(a + tail * np.maximum(losses - a, 0.0).sum() for a in losses)


def rockafellar_uryasev(returns: np.ndarray, beta: float, upper: float) -> float:
    """Minimum CVaR as a linear programme: variables w (n), α, z (T) ≥ 0."""
    t, n = returns.shape
    cost = np.concatenate([np.zeros(n), [1.0], np.full(t, 1.0 / ((1.0 - beta) * t))])
    # z_t ≥ −r_t·w − α  ⇔  −r_t·w − α − z_t ≤ 0
    left = np.hstack([-returns, -np.ones((t, 1)), -np.eye(t)])
    equality = np.concatenate([np.ones(n), [0.0], np.zeros(t)])[None, :]
    bounds = [(0.0, upper)] * n + [(None, None)] + [(0.0, None)] * t
    result = linprog(
        cost, A_ub=left, b_ub=np.zeros(t), A_eq=equality, b_eq=[1.0], bounds=bounds, method="highs"
    )
    assert result.status == 0
    return float(result.fun)


def uniform(n: int) -> np.ndarray:
    return np.full(n, 1 / n)


# Covariance ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(8))
def test_the_covariance_is_the_ledoit_wolf_formula(seed: int) -> None:
    n = 2 + seed % 5
    returns = synthetic_returns(seed, n, 60 + 11 * seed)
    solution = optimize("variance_minimale", returns, uniform(n), Constraints())
    np.testing.assert_allclose(solution.covariance, ledoit_wolf(returns), rtol=1e-9, atol=1e-18)


# Optima against independent solvers ---------------------------------------------------------------


@pytest.mark.parametrize(("seed", "upper"), [(0, 1.0), (1, 0.4), (2, 0.3), (3, 1.0)])
def test_minimum_variance_meets_scipy(seed: int, upper: float) -> None:
    n = 5
    returns = synthetic_returns(seed, n, 250)
    solution = optimize("variance_minimale", returns, uniform(n), Constraints(max_weight=upper))
    cov = ledoit_wolf(returns)
    reference = scipy_minimum(lambda w: w @ cov @ w, n, upper)
    found = solution.weights @ cov @ solution.weights
    assert found == pytest.approx(reference @ cov @ reference, rel=SOLVER_REL)


@pytest.mark.parametrize("cap", [0.05, 0.2, 0.5])
def test_minimum_variance_under_a_turnover_cap_meets_scipy(cap: float) -> None:
    n = 4
    returns = synthetic_returns(11, n, 200)
    previous = np.array([0.55, 0.25, 0.15, 0.05])
    solution = optimize(
        "variance_minimale", returns, previous, Constraints(max_weight=0.6, max_turnover=cap)
    )
    cov = ledoit_wolf(returns)
    reference = scipy_minimum(lambda w: w @ cov @ w, n, 0.6, previous, cap)
    assert turnover(solution.weights, previous) <= cap + TOLERANCE
    found = solution.weights @ cov @ solution.weights
    assert found == pytest.approx(reference @ cov @ reference, rel=SOLVER_REL)


@pytest.mark.parametrize(
    ("seed", "beta", "upper"), [(0, 0.95, 1.0), (4, 0.99, 1.0), (6, 0.95, 0.35)]
)
def test_minimum_cvar_meets_the_rockafellar_uryasev_programme(
    seed: int, beta: float, upper: float
) -> None:
    n = 4
    returns = synthetic_returns(seed, n, 300)
    solution = optimize(
        "cvar_minimale", returns, uniform(n), Constraints(max_weight=upper), cvar_beta=beta
    )
    optimum = rockafellar_uryasev(returns, beta, upper)
    assert historical_cvar(returns, solution.weights, beta) == pytest.approx(
        optimum, rel=SOLVER_REL
    )


@pytest.mark.parametrize("aversion", [2.0, 50.0])
def test_mean_variance_maximises_the_mean_less_aversion_times_variance(aversion: float) -> None:
    n = 4
    returns = synthetic_returns(5, n, 150)
    solution = optimize(
        "moyenne_variance", returns, uniform(n), Constraints(), risk_aversion=aversion
    )
    mean, cov = returns.mean(axis=0), ledoit_wolf(returns)

    def utility(w: np.ndarray) -> float:
        return float(w @ mean - aversion * w @ cov @ w)

    reference = scipy_minimum(lambda w: -utility(w), n, 1.0)
    assert utility(solution.weights) == pytest.approx(utility(reference), rel=SOLVER_REL)


@pytest.mark.parametrize("seed", range(10))
def test_risk_parity_gives_each_security_the_same_share_of_risk(seed: int) -> None:
    n = 2 + seed % 6
    returns = synthetic_returns(seed, n, 60 + 7 * seed)
    solution = optimize("parite_de_risque", returns, uniform(n), Constraints())
    shares = risk.volatility_contributions(solution.weights, solution.covariance).shares
    np.testing.assert_allclose(shares, 1 / n, atol=WEIGHT_ABS)


# Closed forms with two securities -----------------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_two_securities_minimum_variance_is_the_closed_form(seed: int) -> None:
    returns = synthetic_returns(seed, 2, 250)
    cov = ledoit_wolf(returns)
    first = (cov[1, 1] - cov[0, 1]) / (cov[0, 0] + cov[1, 1] - 2 * cov[0, 1])
    expected = np.clip([first, 1 - first], 0.0, 1.0)
    solution = optimize("variance_minimale", returns, uniform(2), Constraints())
    np.testing.assert_allclose(solution.weights, expected, atol=WEIGHT_ABS)


@pytest.mark.parametrize("seed", range(5))
def test_two_securities_risk_parity_is_inverse_volatility(seed: int) -> None:
    returns = synthetic_returns(seed, 2, 250)
    vol = np.sqrt(np.diag(ledoit_wolf(returns)))
    solution = optimize("parite_de_risque", returns, uniform(2), Constraints())
    np.testing.assert_allclose(solution.weights, (1 / vol) / (1 / vol).sum(), atol=WEIGHT_ABS)


@pytest.mark.parametrize("seed", range(5))
def test_two_securities_hrp_is_inverse_variance(seed: int) -> None:
    returns = synthetic_returns(seed, 2, 250)
    var = np.diag(ledoit_wolf(returns))
    solution = optimize("hrp", returns, uniform(2), Constraints())
    np.testing.assert_allclose(solution.weights, (1 / var) / (1 / var).sum(), rtol=1e-9)


# Properties ---------------------------------------------------------------------------------------


@st.composite
def problems(
    draw: st.DrawFn, methods: tuple[Method, ...]
) -> tuple[Method, np.ndarray, Constraints]:
    """A method, returns, and constraints that the current (equal) weights satisfy."""
    method = draw(st.sampled_from(methods))
    n = draw(st.integers(2, 6))
    returns = synthetic_returns(draw(st.integers(0, 10_000)), n, draw(st.integers(40, 120)))
    max_weight = draw(st.floats(1 / n, 1.0))
    groups: tuple[Group, ...] = ()
    if method != "hrp" and n >= 3 and draw(st.booleans()):
        members = tuple(sorted(draw(st.sets(st.integers(0, n - 1), min_size=1, max_size=n - 1))))
        groups = (Group(members, draw(st.floats(len(members) / n, 1.0))),)
    cap = None
    if method in ("variance_minimale", "cvar_minimale") and draw(st.booleans()):
        cap = draw(st.floats(0.0, 2.0))
    return method, returns, Constraints(max_weight=max_weight, groups=groups, max_turnover=cap)


@settings(max_examples=40, deadline=None)
@given(problems(("variance_minimale", "cvar_minimale", "parite_de_risque", "hrp")))
def test_every_solution_honours_its_constraints(
    problem: tuple[Method, np.ndarray, Constraints],
) -> None:
    method, returns, constraints = problem
    previous = uniform(returns.shape[1])
    weights = optimize(method, returns, previous, constraints).weights
    assert weights.sum() == pytest.approx(1.0, abs=1e-12)
    assert weights.min() >= 0.0
    assert weights.max() <= constraints.max_weight + TOLERANCE
    for group in constraints.groups:
        assert weights[list(group.members)].sum() <= group.cap + TOLERANCE
    if constraints.max_turnover is not None:
        assert turnover(weights, previous) <= constraints.max_turnover + TOLERANCE


@settings(max_examples=15, deadline=None)
@given(st.integers(0, 10_000), st.integers(2, 6))
def test_a_zero_turnover_cap_keeps_the_current_weights(seed: int, n: int) -> None:
    returns = synthetic_returns(seed, n, 80)
    previous = np.random.default_rng(seed).dirichlet(np.ones(n))
    weights = optimize(
        "variance_minimale", returns, previous, Constraints(max_turnover=0.0)
    ).weights
    np.testing.assert_allclose(weights, previous, atol=TOLERANCE)


# Refusals -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "n", "constraints", "reason"),
    [
        ("hrp", 1, Constraints(), "au moins deux titres"),
        ("hrp", 3, Constraints(max_turnover=0.2), "rotation maximale non prise en charge"),
        ("parite_de_risque", 3, Constraints(max_turnover=0.2), "rotation maximale non prise"),
        ("hrp", 3, Constraints(groups=(Group((0,), 0.5),)), "plafonds sectoriels non pris"),
        ("variance_minimale", 4, Constraints(max_weight=0.2), "poids maximal trop bas"),
        (
            "variance_minimale",
            3,
            Constraints(max_weight=0.5, groups=(Group((0, 1), 0.4),)),
            "plafonds sectoriels trop bas",
        ),
    ],
)
def test_impossible_constraints_are_refused_before_solving(
    method: Method, n: int, constraints: Constraints, reason: str
) -> None:
    with pytest.raises(RiskError, match=reason):
        check_feasible(method, n, constraints)


def test_a_security_without_variance_is_refused() -> None:
    returns = synthetic_returns(0, 3, 60)
    returns[:, 1] = 0.001
    with pytest.raises(RiskError, match="variance nulle"):
        optimize("variance_minimale", returns, uniform(3), Constraints())


def test_one_current_weight_per_security_is_required() -> None:
    with pytest.raises(RiskError, match="un par titre"):
        optimize("hrp", synthetic_returns(0, 3, 60), uniform(2), Constraints())


def test_mean_variance_needs_a_risk_aversion() -> None:
    with pytest.raises(RiskError, match="aversion au risque inconnue"):
        optimize("moyenne_variance", synthetic_returns(0, 3, 60), uniform(3), Constraints())


def test_a_turnover_cap_out_of_reach_of_the_current_weights_is_refused() -> None:
    constraints = Constraints(max_weight=0.6, max_turnover=0.1)
    with pytest.raises(RiskError, match="contraintes incompatibles"):
        optimize(
            "variance_minimale", synthetic_returns(1, 2, 100), np.array([0.9, 0.1]), constraints
        )


# Rebalancing proposal ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return reference_store(tmp_path_factory.mktemp("finance") / "finance.db")


def propose(path: Path, **kwargs: object) -> RebalanceProposal:
    with FinanceStore.open(path, read_only=True) as db:
        return rebalance_proposal(
            db,
            CONFIG,
            as_of=REFERENCE_READ_AT,
            **kwargs,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        (
            {"sector_caps": [SectorCap(sector="S" + "x" * i, max_weight=0.5) for i in range(11)]},
            f"au plus {MAX_SECTOR_CAPS} plafonds",
        ),
        ({"max_turnover": 2.5}, "rotation maximale entre 0 et 2"),
        ({"max_turnover": -0.1}, "rotation maximale entre 0 et 2"),
        ({"max_weight": 0.0}, "poids maximal entre 0 exclu et 1"),
        ({"max_weight": 1.5}, "poids maximal entre 0 exclu et 1"),
        (
            {
                "sector_caps": [
                    SectorCap(sector="Souverain", max_weight=0.3),
                    SectorCap(sector="souverain", max_weight=0.4),
                ]
            },
            "un secteur figure deux fois",
        ),
        ({"max_weight": 0.05}, "poids maximal trop bas"),
        ({"max_turnover": 0.2, "method_override": "hrp"}, "rotation maximale non prise"),
    ],
)
def test_the_proposal_refuses_bad_arguments(
    store: Path, kwargs: dict[str, object], reason: str
) -> None:
    method = kwargs.pop("method_override", "variance_minimale")
    with pytest.raises(ViewError, match=reason):
        propose(store, method=method, **kwargs)


def test_a_cap_on_an_unknown_sector_has_no_effect_and_says_so(store: Path) -> None:
    capped = propose(
        store,
        method="parite_de_risque",
        sector_caps=[SectorCap(sector="Aéronautique", max_weight=0.1)],
    )
    plain = propose(store, method="parite_de_risque")
    assert any("plafond sans effet" in w and "Aéronautique" in w for w in capped.warnings)
    targets = [line.target_weight.value for line in capped.lines]
    assert targets == [line.target_weight.value for line in plain.lines]


def test_a_sector_cap_matches_the_sector_whatever_its_case(store: Path) -> None:
    proposal = propose(
        store,
        method="variance_minimale",
        sector_caps=[SectorCap(sector="SOUVERAIN", max_weight=0.25)],
    )
    (souverain,) = [s for s in proposal.sectors if s.sector.casefold() == "souverain"]
    assert souverain.target_weight.value <= 0.25 + TOLERANCE
    weights = [line.target_weight.value for line in proposal.lines]
    assert sum(weights) == pytest.approx(1.0, abs=1e-9)
