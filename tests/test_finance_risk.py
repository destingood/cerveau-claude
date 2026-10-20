"""Market risk measures against independent calculations (ADR-014, D11).

skfolio where its definition is the same as ours, closed forms written here otherwise, and the
reference portfolio rebuilt from the generator's CSV files, with decimals and pandas, without the
store's adjusted closes (B118). The tolerances are the ones of ``config/risk.yaml``
(``market_risk.cross_check``): never loosened (R9).
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays
from scipy import stats
from skfolio import measures as sk

from core.config.loader import CrisisWindow, MarketRisk, load_config
from core.finance import risk, views
from core.finance.fixtures import REFERENCE_READ_AT, reference_store
from core.finance.risk import Moments, RiskError
from core.finance.risk_report import MEASURES, RiskReport, SectorShock, risk_report
from core.finance.store import FinanceStore
from core.finance.views import ViewError

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "tests" / "fixtures" / "finance" / "reference"
CONFIG: MarketRisk = load_config(ROOT / "config").risk.market_risk
REL = CONFIG.cross_check.rel_tolerance
MC_REL = CONFIG.cross_check.monte_carlo_rel_tolerance
MC_DRAWS = CONFIG.cross_check.monte_carlo_draws
DAY = date(2026, 10, 18)

losses_arrays = arrays(
    np.float64,
    st.integers(2, 300),
    elements=st.floats(-0.2, 0.2, allow_nan=False, allow_infinity=False),
)
confidences = st.floats(0.5, 0.999)


def linear_quantile(values: np.ndarray, q: float) -> float:
    """Hyndman and Fan type 7, written out: the order statistic at (n − 1)q, interpolated."""
    ordered = sorted(float(v) for v in values)
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (position - low) * (ordered[high] - ordered[low])


def close(a: float, b: float, rel: float = REL) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=1e-12)


def sample_moments(lines: int, seed: int) -> tuple[Moments, np.ndarray]:
    rng = np.random.default_rng(seed)
    factors = rng.normal(0.0, 0.01, (lines, lines))
    cov = factors @ factors.T
    mean = rng.normal(0.0002, 0.0003, lines)
    weights = rng.dirichlet(np.ones(lines))
    return Moments(mean, cov), weights


# Value at risk ----------------------------------------------------------------------------------


@given(losses_arrays, confidences)
def test_historical_var_is_the_linear_quantile(losses: np.ndarray, c: float) -> None:
    var = risk.historical_var(losses, c)
    assert close(var, linear_quantile(losses, c))
    tail = [x for x in losses if x >= var]
    assert close(risk.historical_cvar(losses, c), math.fsum(tail) / len(tail))


@given(losses_arrays, confidences, st.floats(0.1, 10.0), st.floats(-0.1, 0.1))
def test_historical_var_is_homogeneous_and_translation_invariant(
    losses: np.ndarray, c: float, k: float, a: float
) -> None:
    var = risk.historical_var(losses, c)
    assert math.isclose(risk.historical_var(k * losses, c), k * var, rel_tol=1e-9, abs_tol=1e-12)
    assert math.isclose(risk.historical_var(losses + a, c), var + a, rel_tol=1e-9, abs_tol=1e-12)


@given(losses_arrays, confidences, confidences)
def test_cvar_dominates_var_and_both_grow_with_confidence(
    losses: np.ndarray, c1: float, c2: float
) -> None:
    low, high = sorted((c1, c2))
    assert risk.historical_cvar(losses, low) >= risk.historical_var(losses, low) - 1e-15
    assert risk.historical_var(losses, low) <= risk.historical_var(losses, high) + 1e-15
    assert risk.historical_cvar(losses, low) <= risk.historical_cvar(losses, high) + 1e-15


@given(st.floats(-0.01, 0.01), st.floats(1e-4, 0.1), confidences)
def test_parametric_var_and_cvar_are_the_normal_closed_forms(
    mean: float, sd: float, c: float
) -> None:
    law = NormalDist()
    z = law.inv_cdf(c)
    assert close(risk.parametric_var(mean, sd, c), z * sd - mean, rel=1e-9)
    assert close(risk.parametric_cvar(mean, sd, c), sd * law.pdf(z) / (1 - c) - mean, rel=1e-9)
    assert risk.parametric_cvar(mean, sd, c) >= risk.parametric_var(mean, sd, c)


def test_the_horizon_scales_by_the_square_root_of_time() -> None:
    assert risk.scaled(2.0, 1) == 2.0
    assert close(risk.scaled(2.0, 10), 2.0 * math.sqrt(10))
    with pytest.raises(RiskError, match="horizon"):
        risk.scaled(2.0, 0)


@pytest.mark.parametrize("seed", [1, 2, 3, 2026])
@pytest.mark.parametrize("c", [0.95, 0.99])
def test_monte_carlo_meets_the_closed_form_within_the_statistical_tolerance(
    seed: int, c: float
) -> None:
    moments, weights = sample_moments(6, seed=7)
    simulated = risk.monte_carlo_losses(moments, weights, MC_DRAWS, seed)
    mean, sd = moments.portfolio_mean(weights), moments.portfolio_sd(weights)
    expected = risk.parametric_var(mean, sd, c)
    assert abs(risk.historical_var(simulated, c) / expected - 1) <= MC_REL
    assert abs(simulated.std(ddof=1) / sd - 1) <= MC_REL


def test_the_covariance_root_takes_a_line_without_variance() -> None:
    moments, _ = sample_moments(4, seed=11)
    cov = np.zeros((5, 5))
    cov[:4, :4] = moments.cov  # the fifth line is euro cash
    root = risk.covariance_root(cov)
    assert np.allclose(root, root.T)
    assert np.allclose(root @ root, cov, rtol=0, atol=1e-15)
    assert np.all(root[4] == 0)


def test_monte_carlo_is_reproducible_with_its_seed() -> None:
    moments, weights = sample_moments(3, seed=5)
    first = risk.monte_carlo_losses(moments, weights, 1000, 2026)
    assert np.array_equal(first, risk.monte_carlo_losses(moments, weights, 1000, 2026))
    assert not np.array_equal(first, risk.monte_carlo_losses(moments, weights, 1000, 2027))


# Backtest ---------------------------------------------------------------------------------------


def kupiec_statistic(x: int, t: int, p: float) -> float:
    """Written out, with the limits x = 0 and x = T of the likelihood under x/T."""
    null = (t - x) * math.log(1 - p) + x * math.log(p)
    if x == 0 or x == t:
        return -2 * null
    q = x / t
    return -2 * (null - ((t - x) * math.log(1 - q) + x * math.log(q)))


@pytest.mark.parametrize(
    ("x", "t", "c"),
    [
        (0, 250, 0.99),
        (0, 250, 0.95),
        (2, 250, 0.99),
        (10, 233, 0.95),
        (4, 233, 0.99),
        (30, 30, 0.95),
    ],
)
def test_kupiec_is_the_likelihood_ratio_of_coverage(x: int, t: int, c: float) -> None:
    p = 1 - c
    result = risk.kupiec(x, t, c)
    statistic = kupiec_statistic(x, t, p)
    assert close(result.statistic, statistic, rel=1e-9)
    assert close(result.p_value, math.erfc(math.sqrt(statistic / 2)), rel=1e-9)  # χ²(1)
    assert result.expected == pytest.approx(p * t, rel=1e-12)
    if x == 0:
        assert close(result.statistic, -2 * t * math.log(1 - p), rel=1e-12)


def test_kupiec_refuses_inconsistent_counts() -> None:
    for x, t in ((-1, 10), (11, 10), (0, 0)):
        with pytest.raises(RiskError, match="incohérent"):
            risk.kupiec(x, t, 0.99)


@given(arrays(np.float64, st.integers(30, 120), elements=st.floats(-0.1, 0.1)))
@settings(max_examples=50)
def test_rolling_exceptions_compare_each_loss_with_the_var_before_it(losses: np.ndarray) -> None:
    window, sessions, c = 20, 40, 0.9
    exceptions, observations = risk.rolling_exceptions(losses, window, c, sessions)
    expected_observations = min(sessions, len(losses) - window)
    assert observations == expected_observations
    count = sum(
        losses[i] > linear_quantile(losses[i - window : i], c)
        for i in range(len(losses) - observations, len(losses))
    )
    assert exceptions == count


def test_rolling_exceptions_need_one_session_after_the_window() -> None:
    assert risk.rolling_exceptions(np.zeros(20), 20, 0.99, 250) == (0, 0)


# Volatility, GARCH, drawdown, concentration, correlation ----------------------------------------


@given(arrays(np.float64, st.integers(2, 200), elements=st.floats(-0.1, 0.1)))
def test_the_volatility_is_the_sample_standard_deviation_of_skfolio(returns: np.ndarray) -> None:
    moments = risk.moments(returns.reshape(-1, 1))
    expected = float(sk.standard_deviation(returns))
    assert close(moments.portfolio_sd(np.ones(1)), expected, rel=1e-9)
    assert close(risk.annualized(expected, 252), expected * math.sqrt(252))


def simulate_garch(n: int, omega: float, alpha: float, beta: float, seed: int) -> np.ndarray:
    """A GARCH(1,1) path in % with a zero mean, after a burn-in of 500 sessions."""
    z = np.random.default_rng(seed).standard_normal(n + 500)
    variance, shock, path = omega / (1 - alpha - beta), 0.0, []
    for draw in z:
        variance = omega + alpha * shock**2 + beta * variance
        shock = math.sqrt(variance) * draw
        path.append(shock)
    return np.array(path[500:]) / 100.0


def test_garch_recovers_known_parameters() -> None:
    returns = simulate_garch(4000, omega=0.02, alpha=0.08, beta=0.90, seed=42)
    fitted = risk.garch(returns)
    assert fitted.converged
    assert abs(fitted.alpha - 0.08) < 0.03
    assert abs(fitted.beta - 0.90) < 0.05
    assert abs(fitted.persistence - 0.98) < 0.02
    long_run = fitted.long_run_sd
    assert long_run is not None and abs(long_run / 0.01 - 1) < 0.2  # 1 % per session
    assert not fitted.degenerate


@pytest.mark.parametrize(
    ("alpha", "beta", "degenerate"),
    [
        (0.0, 0.834, True),  # the reference portfolio: the forecast is the long-run level
        (0.0004, 0.9, True),  # shown as 0,000
        (0.1, 0.0, True),  # an ARCH(1): β on its lower bound
        (0.06, 0.9395, True),  # α + β = 1 to the third decimal
        (0.08, 0.90, False),
    ],
)
def test_a_garch_on_a_bound_of_its_domain_is_degenerate(
    alpha: float, beta: float, degenerate: bool
) -> None:
    fit = risk.Garch(mu=0.0, omega=0.01, alpha=alpha, beta=beta, next_sd=0.01, converged=True)
    assert fit.degenerate is degenerate


@given(arrays(np.float64, st.integers(1, 200), elements=st.floats(-0.3, 0.3)))
def test_the_drawdown_is_the_one_of_skfolio_compounded_from_one(returns: np.ndarray) -> None:
    result = risk.drawdown(returns)
    depths = sk.get_drawdowns(returns, compounded=True)
    assert close(result.maximum, float(sk.max_drawdown(depths)), rel=1e-9)
    assert close(result.current, -float(depths[-1]), rel=1e-9)
    wealth = np.concatenate(([1.0], np.cumprod(1 + returns)))
    assert result.peak <= result.trough
    assert wealth[result.peak] == wealth[: result.trough + 1].max()


@given(arrays(np.float64, st.integers(1, 30), elements=st.floats(0.0, 1e6)))
def test_the_effective_number_of_lines_is_the_one_of_skfolio(values: np.ndarray) -> None:
    if values.sum() <= 0:
        with pytest.raises(RiskError):
            risk.herfindahl(values)
        return
    weights = values / values.sum()
    assert close(1 / risk.herfindahl(values), float(sk.effective_number_assets(weights)), rel=1e-9)


def test_concentration_refuses_negative_values() -> None:
    with pytest.raises(RiskError, match="positives"):
        risk.herfindahl(np.array([1.0, -1.0, 3.0]))


def test_the_correlation_is_the_one_of_pandas() -> None:
    returns = np.random.default_rng(3).normal(0, 0.01, (300, 4))
    returns[:, 1] += returns[:, 0]
    expected = pd.DataFrame(returns).corr().to_numpy()
    assert np.allclose(risk.correlation(returns), expected, rtol=REL, atol=1e-15)
    returns[:, 2] = 0.001  # a constant whose rounded standard deviation is not 0
    with pytest.raises(RiskError, match="variance nulle"):
        risk.correlation(returns)


# Regression and beta ----------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_regression_and_beta_are_the_ones_of_scipy(seed: int) -> None:
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 0.01, 400)
    y = 0.7 * x + rng.normal(0, 0.01, 400)
    expected = stats.linregress(x, y)
    found = risk.regression(y, x)
    assert close(found.slope, float(expected.slope), rel=1e-9)
    assert close(found.standard_error, float(expected.stderr), rel=1e-9)
    assert close(found.p_value, float(expected.pvalue), rel=1e-7)
    assert found.observations == 400
    assert close(risk.beta(y, x), float(expected.slope), rel=1e-9)


def test_regression_refuses_what_it_cannot_fit() -> None:
    with pytest.raises(RiskError, match="trois observations"):
        risk.regression(np.ones(2), np.arange(2.0))
    with pytest.raises(RiskError, match="constante"):
        risk.regression(np.arange(5.0), np.ones(5))
    with pytest.raises(RiskError, match="variance nulle"):
        risk.beta(np.arange(5.0), np.ones(5))
    exact = risk.regression(2 * np.arange(5.0), np.arange(5.0))
    assert exact.slope == pytest.approx(2.0) and exact.p_value == 0.0


@settings(max_examples=100)
@given(st.integers(0, 2**32 - 1), st.floats(-2.0, 2.0), st.sampled_from([0.01, 0.05, 0.10]))
def test_a_slope_is_significant_exactly_when_its_interval_leaves_out_zero(
    seed: int, slope: float, significance: float
) -> None:
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 0.01, 60)
    fit = risk.regression(slope * x + rng.normal(0, 0.01, 60), x)
    low, high = fit.interval(significance)
    assert low <= fit.slope <= high
    assert math.isclose(high - fit.slope, fit.slope - low, rel_tol=1e-9)
    if abs(fit.p_value - significance) > 1e-9:  # away from the edge, where rounding decides
        assert fit.significant(significance) is not (low <= 0.0 <= high)


# Contributions and the VaR change ---------------------------------------------------------------


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_euler_contributions_add_up_and_are_derivatives(seed: int) -> None:
    moments, weights = sample_moments(5, seed)
    sd = moments.portfolio_sd(weights)
    found = risk.volatility_contributions(weights, moments.cov)
    assert close(float(found.component.sum()), sd, rel=1e-12)
    assert close(float(found.shares.sum()), 1.0, rel=1e-12)
    h = 1e-6
    for i in range(len(weights)):
        bump = np.zeros_like(weights)
        bump[i] = h
        derivative = (
            moments.portfolio_sd(weights + bump) - moments.portfolio_sd(weights - bump)
        ) / (2 * h)
        assert math.isclose(found.marginal[i], derivative, rel_tol=1e-6)
    for c in (0.95, 0.99):
        mean = moments.portfolio_mean(weights)
        total = risk.parametric_var(mean, sd, c)
        assert close(float(risk.var_contributions(weights, moments, c).sum()), total, rel=1e-12)


def test_contributions_refuse_a_book_without_variance() -> None:
    with pytest.raises(RiskError, match="variance"):
        risk.volatility_contributions(np.array([1.0, 0.0]), np.zeros((2, 2)))


@pytest.mark.parametrize("seed", [0, 1])
def test_the_var_change_splits_without_remainder(seed: int) -> None:
    m0, _ = sample_moments(4, seed)
    m1, _ = sample_moments(4, seed + 10)
    rng = np.random.default_rng(seed)
    x0, x1 = rng.uniform(1000, 5000, 4), rng.uniform(1000, 5000, 4)
    found = risk.var_change((x0, m0), (x1, m1), 0.95)
    assert close(found.positions + found.market + found.residual, found.change, rel=1e-12)
    assert close(found.after, risk.parametric_var_eur(x1, m1, 0.95), rel=1e-12)
    same = risk.var_change((x0, m0), (x0, m1), 0.95)
    assert same.positions == 0.0 and abs(same.residual) <= 1e-9
    still = risk.var_change((x0, m0), (x1, m0), 0.95)
    assert still.market == 0.0 and abs(still.residual) <= 1e-9


# Stress -----------------------------------------------------------------------------------------


@given(st.floats(1.0, 1e5), st.floats(0.5, 2.0), st.floats(-0.5, 0.5))
@example(local=10251.0, rate=1.15625, shock=5.960464477539063e-08)  # a tiny shock, once a failure
def test_the_fx_stress_is_an_exact_revaluation(local: float, rate: float, shock: float) -> None:
    """A line of ``local`` dollars at ``rate`` dollars per euro; the rate moves by ``shock``. The
    reference is exact rational arithmetic on the same floats, free of rounding."""
    exact = Fraction(local) / (Fraction(rate) * (1 + Fraction(shock))) - Fraction(local) / Fraction(
        rate
    )
    assert close(risk.fx_revaluation(local / rate, shock), float(exact), rel=1e-9)


def test_the_fx_and_duration_stresses_refuse_or_follow_their_formula() -> None:
    with pytest.raises(RiskError, match="change"):
        risk.fx_revaluation(100.0, -1.0)
    assert risk.duration_impact(10_000.0, 7.5, 100) == pytest.approx(-750.0)
    assert risk.duration_impact(10_000.0, 7.5, -50) == pytest.approx(375.0)


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: risk.historical_var(np.array([]), 0.95), "aucune perte"),
        (lambda: risk.historical_var(np.ones(3), 1.0), "strictement entre 0 et 1"),
        (lambda: risk.z_score(0.0), "strictement entre 0 et 1"),
        (lambda: risk.moments(np.ones((1, 3))), "deux séances"),
    ],
)
def test_inputs_a_measure_cannot_use_are_refused(call: object, message: str) -> None:
    with pytest.raises(RiskError, match=message):
        call()  # type: ignore[operator]


# The reference portfolio, rebuilt independently -------------------------------------------------


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return reference_store(tmp_path_factory.mktemp("finance") / "finance.db")


def report(path: Path, config: MarketRisk = CONFIG, **kwargs: object) -> RiskReport:
    with FinanceStore.open(path, read_only=True) as db:
        return risk_report(db, config, as_of=REFERENCE_READ_AT, **kwargs)  # type: ignore[arg-type]


def figure(content: RiskReport, figure_id: str) -> float:
    from core.verification.figures import figures_in

    found, _ = figures_in(content.model_dump(mode="json"))
    (value,) = [f.value for f in found if f.id == figure_id]
    return value


def _rows(name: str) -> list[dict[str, str]]:
    with (REFERENCE / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def total_return_closes(instrument: str, last: date) -> pd.Series:
    """Closes of ``instrument`` up to ``last`` adjusted for its splits and dividends, written from
    the definition on the generator's CSV files, in decimals, without ``closes()`` (B118).

    Walking back from the last session, the actions whose ex-date falls after the previous
    session and on or before the current one adjust every earlier close: a split of ratio r
    divides it by r; a dividend D multiplies it by 1 − D·s/P, P the previous raw close and s the
    product of the splits between that close and the dividend's ex-date (P in ex-date shares)."""
    (card,) = [r for r in _rows("instruments.csv") if r["identifiant"] == instrument]
    raw = sorted(
        (date.fromisoformat(r["date"]), Decimal(r["cloture"]))
        for r in _rows("cours.csv")
        if r["identifiant"] == instrument and date.fromisoformat(r["date"]) <= last
    )
    actions = sorted(
        (date.fromisoformat(r["date_ex"]), r["type"], Decimal(r["valeur"]), r["devise"])
        for r in _rows("operations.csv")
        if r["identifiant"] == instrument
    )
    assert all(cur in ("", card["devise"]) for *_, cur in actions)  # paid in the quote currency
    days, closes = [d for d, _ in raw], [c for _, c in raw]
    factor, adjusted = Decimal(1), [closes[-1]]
    for k in range(len(raw) - 1, 0, -1):
        between = [a for a in actions if days[k - 1] < a[0] <= days[k]]
        for ex, kind, value, _ in between:
            if kind == "split":
                factor /= value
            else:
                splits = [v for e, t, v, _ in between if t == "split" and e <= ex]
                factor *= 1 - value * math.prod(splits, start=Decimal(1)) / closes[k - 1]
        adjusted.append(closes[k - 1] * factor)
    return pd.Series([float(v) for v in reversed(adjusted)], index=pd.to_datetime(days))


def per_euro_rates(currency: str, last: date) -> pd.Series:
    """Units of ``currency`` for one euro, as the ECB fixes them, up to ``last``."""
    return pd.Series(
        {
            pd.Timestamp(r["TIME_PERIOD"]): float(r["OBS_VALUE"])
            for r in _rows("bce_change.csv")
            if r["CURRENCY"] == currency and date.fromisoformat(r["TIME_PERIOD"]) <= last
        }
    ).sort_index()


def euro_prices(currency: dict[str, str], last: date) -> pd.DataFrame:
    """EUR prices of the lines up to ``last``, securities then cash, on the sessions common to the
    securities; the rate of a session is the last one fixed on or before it (merge_asof), and a
    unit of cash is worth one over the rate."""
    securities = sorted(k for k in currency if not k.startswith("liquidites-"))
    cash = sorted(k for k in currency if k.startswith("liquidites-"))
    local = pd.concat(
        {key: total_return_closes(key, last) for key in securities}, axis=1, join="inner"
    ).sort_index()
    sessions = pd.DataFrame({"day": local.index.as_unit("ns")})  # one unit on both sides
    columns = {}
    for key in securities + cash:
        if currency[key] == "EUR":
            rate = np.ones(len(local))
        else:
            known = per_euro_rates(currency[key], last).rename("rate").rename_axis("day")
            known.index = known.index.as_unit("ns")
            rate = pd.merge_asof(sessions, known.reset_index(), on="day")["rate"].to_numpy()
        price = local[key].to_numpy() if key in local else np.ones(len(local))
        columns[key] = price / rate
    return pd.DataFrame(columns, index=local.index).dropna()


def held(store: Path, as_of: datetime) -> tuple[pd.Series, dict[str, str]]:
    """EUR value and currency of each line at ``as_of``, from the snapshot, which
    ``test_finance_reference`` reconciles to the cent with the generator's ``releve.csv``."""
    with FinanceStore.open(store, read_only=True) as db:
        snapshot = views.portfolio_snapshot(db, as_of=as_of)
    values: defaultdict[str, float] = defaultdict(float)
    currency: dict[str, str] = {}
    for position in snapshot.positions:
        assert position.value_eur is not None
        values[position.instrument_id] += position.value_eur.value
        currency[position.instrument_id] = position.currency
    for cash in snapshot.cash:
        assert cash.value_eur is not None
        values[f"liquidites-{cash.currency}"] += cash.value_eur.value
        currency[f"liquidites-{cash.currency}"] = cash.currency
    return pd.Series(values), currency


@pytest.fixture(scope="module")
def rebuilt(store: Path) -> tuple[pd.DataFrame, pd.Series]:
    """EUR prices on the common sessions and EUR values by line, in the report's order."""
    values, currency = held(store, REFERENCE_READ_AT)
    prices = euro_prices(currency, DAY)
    return prices, values[list(prices.columns)]


@pytest.fixture(scope="module")
def measured(store: Path) -> RiskReport:
    """The reference report with every measure, computed once."""
    return report(store, measures=list(MEASURES))


def _window(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change().iloc[1:].tail(CONFIG.var.window_sessions)


def test_the_reference_measures_equal_an_independent_assembly(
    measured: RiskReport, rebuilt: tuple[pd.DataFrame, pd.Series]
) -> None:
    prices, values = rebuilt
    window = _window(prices)
    weights = (values / values.sum()).to_numpy()
    returns = window.to_numpy() @ weights
    content = measured
    assert close(figure(content, "valeur_eur"), float(values.sum()))
    sd = float(sk.standard_deviation(returns))
    assert close(figure(content, "volatilite/quotidienne"), sd)
    for c in CONFIG.var.confidence_levels:
        level = f"{c * 100:g}"
        assert close(figure(content, f"var/historique/{level}/1/pct"), linear_quantile(-returns, c))
        z = NormalDist().inv_cdf(c)
        parametric = z * sd - float(returns.mean())
        assert close(figure(content, f"var/parametrique/{level}/1/pct"), parametric)
        assert close(
            figure(content, f"var/parametrique/{level}/10/pct"), parametric * math.sqrt(10)
        )
    depths = sk.get_drawdowns(returns, compounded=True)
    assert close(figure(content, "drawdown/maximum"), -float(sk.max_drawdown(depths)))
    securities = [k for k in prices.columns if not k.startswith("liquidites-")]
    invested = (values[securities] / values[securities].sum()).to_numpy()  # cash left out
    assert close(
        figure(content, "concentration/lignes_effectives"),
        float(sk.effective_number_assets(invested)),
    )
    corr = window[securities].corr()
    assert close(
        figure(content, "correlations/FICT-DELTA/FICT-MONDE"), corr.loc["FICT-DELTA", "FICT-MONDE"]
    )


def _levels() -> list[tuple[float, str]]:
    return [(c, f"{c * 100:g}") for c in CONFIG.var.confidence_levels]


def test_the_cvar_is_the_mean_loss_beyond_the_var(
    measured: RiskReport, rebuilt: tuple[pd.DataFrame, pd.Series]
) -> None:
    prices, values = rebuilt
    total = float(values.sum())
    returns = _window(prices).to_numpy() @ (values / total).to_numpy()
    losses, law = -returns, NormalDist()
    mean, sd = float(returns.mean()), float(returns.std(ddof=1))
    for c, level in _levels():
        var = linear_quantile(losses, c)
        tail = [x for x in losses if x >= var]
        expected = {
            "historique": math.fsum(tail) / len(tail),
            "parametrique": sd * law.pdf(law.inv_cdf(c)) / (1 - c) - mean,
        }
        for method, cvar in expected.items():
            for h in CONFIG.var.horizons_sessions:
                base = f"var/{method}/{level}/{h}"
                assert close(figure(measured, f"{base}/cvar_pct"), cvar * math.sqrt(h))
                assert close(figure(measured, f"{base}/cvar_eur"), cvar * math.sqrt(h) * total)


def test_the_backtest_counts_the_exceptions_of_the_rebuilt_history(
    measured: RiskReport, rebuilt: tuple[pd.DataFrame, pd.Series]
) -> None:
    """Today's lines over the whole common history; each loss against the historical VaR of the
    window before it, then Kupiec's likelihood ratio, written out above."""
    prices, values = rebuilt
    losses = -(prices.pct_change().iloc[1:].to_numpy() @ (values / values.sum()).to_numpy())
    window = CONFIG.var.window_sessions
    observations = min(CONFIG.backtest.window_sessions, len(losses) - window)
    assert 0 < observations < CONFIG.backtest.window_sessions  # the report says it is incomplete
    for c, level in _levels():
        exceptions = sum(
            bool(losses[i] > linear_quantile(losses[i - window : i], c))
            for i in range(len(losses) - observations, len(losses))
        )
        statistic = kupiec_statistic(exceptions, observations, 1 - c)
        base = f"backtest/{level}"
        assert figure(measured, f"{base}/seances") == observations
        assert figure(measured, f"{base}/exceptions") == exceptions
        assert close(figure(measured, f"{base}/attendues"), (1 - c) * observations)
        assert close(figure(measured, f"{base}/statistique"), statistic)
        assert close(figure(measured, f"{base}/p_value"), math.erfc(math.sqrt(statistic / 2)))


def test_the_contributions_are_the_euler_split_of_the_parametric_var(
    measured: RiskReport, rebuilt: tuple[pd.DataFrame, pd.Series]
) -> None:
    prices, values = rebuilt
    window = _window(prices)
    total = float(values.sum())
    weights = (values / total).to_numpy()
    cov, mean = window.cov().to_numpy(), window.mean().to_numpy()  # sample covariance, n − 1
    pull = cov @ weights
    sd = math.sqrt(float(weights @ pull))
    scale = math.sqrt(CONFIG.annualisation_sessions)
    for i, key in enumerate(prices.columns):
        base = f"contributions/{key}"
        marginal = float(pull[i]) / sd
        assert close(figure(measured, f"{base}/valeur_eur"), float(values[key]))
        assert close(figure(measured, f"{base}/poids"), float(weights[i]))
        assert close(figure(measured, f"{base}/volatilite"), math.sqrt(cov[i, i]) * scale)
        assert close(figure(measured, f"{base}/marginale"), marginal * scale)
        assert close(figure(measured, f"{base}/contribution"), weights[i] * marginal * scale)
        assert close(figure(measured, f"{base}/part_risque"), weights[i] * pull[i] / sd**2)
        for c, level in _levels():
            z = NormalDist().inv_cdf(c)
            expected = total * weights[i] * (z * marginal - mean[i])
            assert close(figure(measured, f"{base}/var/{level}"), expected)
    for _c, level in _levels():
        parts = [figure(measured, f"contributions/{key}/var/{level}") for key in prices.columns]
        assert close(math.fsum(parts), figure(measured, f"var/parametrique/{level}/1/eur"))


def test_the_rate_stress_regresses_the_other_securities_on_the_estr(
    measured: RiskReport, rebuilt: tuple[pd.DataFrame, pd.Series]
) -> None:
    """Bonds by their duration; the other securities by the OLS of their daily P&L on the daily
    change of the €STR, the last rate published by each session; cash has no rate effect."""
    prices, values = rebuilt
    window = _window(prices)
    estr = pd.Series(
        {pd.Timestamp(r["TIME_PERIOD"]): float(r["OBS_VALUE"]) for r in _rows("bce_estr.csv")}
    ).sort_index()
    level = estr.reindex(prices.index[-(len(window) + 1) :], method="ffill")
    changes = np.diff(level.to_numpy()) / 100.0
    cards = {r["identifiant"]: r for r in _rows("instruments.csv")}
    bonds = [k for k in window.columns if k in cards and cards[k]["classe"] == "obligation"]
    others = [k for k in window.columns if k in cards and cards[k]["classe"] != "obligation"]
    pnl = window[others].to_numpy() @ values[others].to_numpy()
    fit = stats.linregress(changes, pnl)
    bp = CONFIG.hypothetical_stress.rates_bp
    shift = bp / 10_000
    duration = math.fsum(-float(cards[k]["duration"]) * shift * float(values[k]) for k in bonds)
    t = float(stats.t.ppf(1 - CONFIG.backtest.significance / 2, len(pnl) - 2))
    low, high = sorted(shift * (fit.slope + side * t * fit.stderr) for side in (-1, 1))
    expected = {
        "duration_eur": duration,
        "estime_eur": fit.slope * shift,
        "ecart_type_eur": fit.stderr * abs(shift),
        "p_value": fit.pvalue,
        "seances": len(pnl),
        "intervalle_bas_eur": low,
        "intervalle_haut_eur": high,
        "impact_eur": duration + fit.slope * shift,
    }
    for name, value in expected.items():
        assert close(figure(measured, f"stress/taux/{name}"), float(value)), name


def test_the_var_change_since_monday_is_rebuilt_from_both_books(store: Path) -> None:
    """Monday 12/10 at 13:00 UTC, Friday's closes and rates were the last known; the lines of
    both dates, each book on the 500 returns known at its date. The values at Monday come from
    the snapshot then, the one ``test_finance_portfolio`` checks."""
    compare_to = REFERENCE_READ_AT - timedelta(days=6)
    content = report(store, measures=["var"], compare_to=compare_to)
    now, now_currency = held(store, REFERENCE_READ_AT)
    then, then_currency = held(store, compare_to)
    currency = {**then_currency, **now_currency}
    keys = sorted(currency, key=lambda k: (k.startswith("liquidites-"), k))
    r0 = _window(euro_prices(currency, date(2026, 10, 9)))[keys].to_numpy()
    r1 = _window(euro_prices(currency, DAY))[keys].to_numpy()
    x0 = then.reindex(keys, fill_value=0.0).to_numpy()
    x1 = now.reindex(keys, fill_value=0.0).to_numpy()
    for key, before, after in zip(keys, x0, x1, strict=True):
        base = f"variation_var/expositions/{key}"
        assert close(figure(content, f"{base}/avant"), before)
        assert close(figure(content, f"{base}/apres"), after)
    for c, level in _levels():
        z = NormalDist().inv_cdf(c)

        def var_eur(x: np.ndarray, r: np.ndarray, z: float = z) -> float:
            pnl = r @ x
            return z * float(pnl.std(ddof=1)) - float(pnl.mean())

        avant, apres = var_eur(x0, r0), var_eur(x1, r1)
        positions, market = var_eur(x1, r0) - avant, var_eur(x0, r1) - avant
        expected = {
            "avant": avant,
            "apres": apres,
            "variation": apres - avant,
            "effet_positions": positions,
            "effet_marche": market,
            "residu": apres - avant - positions - market,
        }
        for name, value in expected.items():
            assert close(figure(content, f"variation_var/{level}/{name}"), value), name


def test_monte_carlo_on_the_reference_meets_the_closed_form(store: Path) -> None:
    """The phase criterion: 100 000 draws within the statistical tolerance of the closed form."""
    var = CONFIG.var.model_copy(update={"monte_carlo_draws": MC_DRAWS})
    content = report(store, CONFIG.model_copy(update={"var": var}), measures=["var"])
    for c in CONFIG.var.confidence_levels:
        level = f"{c * 100:g}"
        simulated = figure(content, f"var/monte_carlo/{level}/1/eur")
        closed = figure(content, f"var/parametrique/{level}/1/eur")
        assert abs(simulated / closed - 1) <= MC_REL


def test_a_historical_window_applies_its_moves_to_the_current_lines(
    store: Path, rebuilt: tuple[pd.DataFrame, pd.Series]
) -> None:
    prices, values = rebuilt
    window = CrisisWindow(label="essai", start=date(2025, 6, 2), end=date(2025, 10, 9), source="x")
    config = CONFIG.model_copy(update={"historical_stress": {"essai": window}})
    content = report(store, config, measures=["stress"])
    before = prices.loc[: pd.Timestamp(window.start)].iloc[-1]
    after = prices.loc[: pd.Timestamp(window.end)].iloc[-1]
    expected = math.fsum(values[k] * (after[k] / before[k] - 1) for k in prices.columns)
    assert close(figure(content, "stress/historique/essai/impact_eur"), expected)


def snapshot_value(store: Path, keep: object) -> float:
    with FinanceStore.open(store, read_only=True) as db:
        snapshot = views.portfolio_snapshot(db, as_of=REFERENCE_READ_AT)
    return math.fsum(
        p.value_eur.value
        for p in snapshot.positions
        if p.value_eur and keep(p)  # type: ignore[operator]
    )


def test_the_equity_shock_moves_the_equities_and_equity_funds_only(store: Path) -> None:
    content = report(store, measures=["stress"])
    equities = snapshot_value(store, lambda p: p.asset_class in {"equity", "etf"})
    everything = snapshot_value(store, lambda p: True)
    assert 0 < equities < everything  # the bond and the other lines stay put
    shock = CONFIG.hypothetical_stress.equity_shock
    assert close(figure(content, "stress/actions/impact_eur"), shock * equities)


def test_a_sector_shock_moves_only_its_lines(store: Path) -> None:
    content = report(
        store, measures=["stress"], sector_shocks=[SectorShock(sector="Technologie", shock=-0.15)]
    )
    tech = snapshot_value(store, lambda p: p.sector == "Technologie")
    assert tech > 0
    assert close(figure(content, "stress/secteur/1/impact_eur"), -0.15 * tech)


def test_a_rate_sensitivity_not_distinguishable_from_zero_is_said_so(store: Path) -> None:
    """The reference equities barely follow the €STR (p ≈ 0,46): the total keeps the estimate,
    yet the report says only the duration part is established and gives the interval."""
    content = report(store, measures=["stress"])
    (rates,) = [s for s in content.stress or [] if s.scenario == "taux"]
    split = rates.rates
    assert split is not None and split.significant is False
    assert split.p_value is not None and split.p_value.value >= CONFIG.backtest.significance
    low, high = (
        figure(content, "stress/taux/intervalle_bas_eur"),
        figure(content, "stress/taux/intervalle_haut_eur"),
    )
    estimate = figure(content, "stress/taux/estime_eur")
    assert low < 0.0 < high and low < estimate < high
    assert close(
        figure(content, "stress/taux/impact_eur"),
        figure(content, "stress/taux/duration_eur") + estimate,
        rel=1e-6,
    )
    assert "seule la part duration est établie" in rates.note
    assert any("stress/taux/duration_eur est établie" in w for w in content.warnings)


def test_a_garch_with_alpha_at_zero_gives_no_beta_and_says_why(store: Path) -> None:
    content = report(store, measures=["volatilite"])
    assert content.volatility is not None
    garch = content.volatility.garch
    assert garch.status == "estime" and garch.degenerate
    assert garch.beta is None and garch.persistence is None
    assert garch.alpha is not None and garch.alpha.value < risk.BOUND_TOLERANCE
    assert garch.next_session is not None  # the model's forecast, read with the history
    assert any(w.startswith("GARCH dégénéré") for w in content.warnings)


def test_the_report_refuses_what_it_cannot_answer(store: Path) -> None:
    with pytest.raises(ViewError, match="au moins une mesure"):
        report(store, measures=[])
    with pytest.raises(ViewError, match="compare_to doit précéder as_of"):
        report(store, compare_to=REFERENCE_READ_AT)
    shocks = [SectorShock(sector="Technologie", shock=-0.1)] * 6
    with pytest.raises(ViewError, match="au plus 5 chocs"):
        report(store, sector_shocks=shocks)


# Parity label and data quality (plan of phase 2, §2 and §3; D12) -------------------------------


def test_the_report_carries_its_parity_label_and_the_quality_of_its_data(store: Path) -> None:
    content = report(store, measures=["var"], quality_threshold=0.9)
    assert content.parity_label == "[Approximation]"
    quality = content.data_quality
    assert (quality.gate, quality.decision_cap, quality.below) == ("suffisante", None, [])
    assert quality.threshold is not None and quality.threshold.display == "0,900"
    with FinanceStore.open(store, read_only=True) as db:
        held = views.portfolio_snapshot(db, as_of=REFERENCE_READ_AT).positions
    assert {s.instrument_id for s in quality.series} == {p.instrument_id for p in held}
    assert all(s.score is not None and s.score.value >= 0.9 for s in quality.series)
    assert not any("qualité" in warning for warning in content.warnings)


def test_a_score_under_the_threshold_caps_the_decision_at_n1(store: Path) -> None:
    content = report(store, measures=["var"], quality_threshold=0.995)
    quality = content.data_quality
    assert (quality.gate, quality.decision_cap, quality.below) == (
        "insuffisante",
        "N1",
        ["FICT-BOREAL"],
    )
    assert content.var  # the measures are still given, with the warning beside them
    assert (
        "qualité des données insuffisante : FICT-BOREAL score 0,992 sous le seuil 0,995 (D12) ; "
        "toute décision reste plafonnée à N1"
    ) in content.warnings


def test_a_threshold_still_at_a_marker_leaves_the_quality_not_evaluable(store: Path) -> None:
    content = report(store, measures=["var"])  # quality_threshold defaults to A_DEFINIR (R7)
    quality = content.data_quality
    assert (quality.gate, quality.decision_cap, quality.threshold) == ("non_evaluable", "N1", None)
    assert (
        "qualité non évaluable : le seuil min_quality_score_above_N1 vaut A_DEFINIR (R7) (D12) ; "
        "toute décision reste plafonnée à N1"
    ) in content.warnings
