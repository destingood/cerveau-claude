"""Market risk measures on simple daily returns in EUR: pure, deterministic functions (ADR-014).

A loss is positive: ``L = -r``. The store, the positions and the figures are assembled by
``core.finance.risk_report``; this module only computes. Definitions:

- historical VaR: the ``linear`` quantile of ``numpy.quantile`` of the losses; CVaR: the mean of
  the losses at or beyond that VaR;
- parametric: normal law, sample mean and covariance (ddof=1): ``VaR = zσ − μ`` and
  ``CVaR = σφ(z)/(1 − c) − μ``;
- Monte Carlo: normal draws with a fixed seed through the symmetric root of the covariance,
  read with the historical estimators;
- horizon h: the one-session figure times √h ``[Approximation]``;
- Kupiec: likelihood ratio of unconditional coverage, chi-squared with one degree of freedom;
- regression: ordinary least squares with an intercept, Student test of the slope;
- Euler: the contributions ``wᵢ(Σw)ᵢ/σ`` add up to σ, and ``wᵢ(z(Σw)ᵢ/σ − μᵢ)`` to the
  parametric VaR;
- drawdown: on the wealth compounded from 1, below its running peak (the start counts as a peak).
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import numpy as np
from arch import arch_model
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray
from scipy import special, stats

Vector = NDArray[np.float64]
Matrix = NDArray[np.float64]


class RiskError(ValueError):
    """Inputs a measure cannot be computed from: too few observations, a zero variance."""


def _confidence(confidence: float) -> float:
    if not 0.0 < confidence < 1.0:
        raise RiskError("le niveau de confiance doit être strictement entre 0 et 1")
    return confidence


# Value at risk ---------------------------------------------------------------------------------


def historical_var(losses: Vector, confidence: float) -> float:
    if len(losses) == 0:
        raise RiskError("aucune perte observée")
    return float(np.quantile(losses, _confidence(confidence), method="linear"))


def historical_cvar(losses: Vector, confidence: float) -> float:
    """Mean of the losses at or beyond the historical VaR (the largest loss always is)."""
    var = historical_var(losses, confidence)
    return float(np.mean(losses[losses >= var]))


def z_score(confidence: float) -> float:
    return float(stats.norm.ppf(_confidence(confidence)))


def parametric_var(mean: float, sd: float, confidence: float) -> float:
    return z_score(confidence) * sd - mean


def parametric_cvar(mean: float, sd: float, confidence: float) -> float:
    z = z_score(confidence)
    return sd * float(stats.norm.pdf(z)) / (1.0 - confidence) - mean


@dataclass(frozen=True)
class Moments:
    """Sample mean and covariance (ddof=1) of the daily returns of each line."""

    mean: Vector
    cov: Matrix

    def portfolio_mean(self, weights: Vector) -> float:
        return float(weights @ self.mean)

    def portfolio_sd(self, weights: Vector) -> float:
        return math.sqrt(max(float(weights @ self.cov @ weights), 0.0))


def moments(returns: Matrix) -> Moments:
    """``returns``: one row per session, one column per line."""
    if returns.ndim != 2 or returns.shape[0] < 2:
        raise RiskError("au moins deux séances sont nécessaires")
    cov = np.atleast_2d(np.cov(returns, rowvar=False, ddof=1))
    return Moments(mean=returns.mean(axis=0), cov=cov)


def covariance_root(cov: Matrix) -> Matrix:
    """The symmetric square root S of a covariance, S @ S = cov: unique, so it does not depend on
    the signs or the order of the eigenvectors LAPACK returns, unlike ``multivariate_normal``.
    A line of zero variance, such as euro cash, is allowed."""
    values, vectors = np.linalg.eigh(cov)
    return np.asarray((vectors * np.sqrt(np.clip(values, 0.0, None))) @ vectors.T)


def monte_carlo_losses(moments: Moments, weights: Vector, draws: int, seed: int) -> Vector:
    """Portfolio losses of ``draws`` multivariate normal sessions ``μ + zS``, z standard normal
    from ``default_rng(seed)``."""
    z = np.random.default_rng(seed).standard_normal((draws, len(moments.mean)))
    return -(moments.portfolio_mean(weights) + z @ (covariance_root(moments.cov) @ weights))


def scaled(value: float, horizon: int) -> float:
    """The one-session figure at ``horizon`` sessions, by √h [Approximation]."""
    if horizon < 1:
        raise RiskError("l'horizon compte au moins une séance")
    return value * math.sqrt(horizon)


# Backtest --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Kupiec:
    observations: int
    exceptions: int
    expected: float
    statistic: float
    p_value: float

    def rejected(self, significance: float) -> bool:
        return self.p_value < significance


def kupiec(exceptions: int, observations: int, confidence: float) -> Kupiec:
    """LR = −2 ln[(1 − p)^(T−x) p^x] + 2 ln[(1 − x/T)^(T−x) (x/T)^x], with p = 1 − c."""
    if observations < 1 or not 0 <= exceptions <= observations:
        raise RiskError("backtest : nombre d'exceptions ou d'observations incohérent")
    p = 1.0 - _confidence(confidence)
    x, t = exceptions, observations

    def log_likelihood(q: float) -> float:
        return float(special.xlogy(x, q) + special.xlog1py(t - x, -q))

    statistic = max(-2.0 * (log_likelihood(p) - log_likelihood(x / t)), 0.0)
    return Kupiec(t, x, p * t, statistic, float(stats.chi2.sf(statistic, 1)))


def rolling_exceptions(
    losses: Vector, window: int, confidence: float, sessions: int
) -> tuple[int, int]:
    """Each of the last ``sessions`` losses (at most) against the historical VaR of the
    ``window`` losses just before it: (exceptions, observations). An exception is a loss above
    its VaR."""
    observations = min(sessions, len(losses) - window)
    if observations < 1:
        return 0, 0
    windows = sliding_window_view(losses[:-1], window)[-observations:]
    var = np.quantile(windows, _confidence(confidence), axis=1, method="linear")
    return int(np.sum(losses[-observations:] > var)), observations


# Volatility ------------------------------------------------------------------------------------


def annualized(daily: float, sessions: int) -> float:
    return daily * math.sqrt(sessions)


@dataclass(frozen=True)
class Garch:
    """GARCH(1,1) with a constant mean, fitted by arch on returns in %."""

    mu: float  # % per session
    omega: float  # %² per session
    alpha: float
    beta: float
    next_sd: float  # forecast for the next session, a fraction
    converged: bool

    @property
    def persistence(self) -> float:
        return self.alpha + self.beta

    @property
    def long_run_sd(self) -> float | None:
        """Unconditional standard deviation per session, a fraction; None when α + β ≥ 1."""
        if self.persistence >= 1.0:
            return None
        return math.sqrt(self.omega / (1.0 - self.persistence)) / 100.0


def garch(returns: Vector) -> Garch:
    model = arch_model(
        returns * 100.0, mean="Constant", vol="GARCH", p=1, q=1, dist="normal", rescale=False
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # convergence is read from the flag below
        result = model.fit(disp="off", show_warning=False)
    params = result.params
    variance = float(result.forecast(horizon=1, reindex=False).variance.iloc[-1, 0])
    return Garch(
        mu=float(params["mu"]),
        omega=float(params["omega"]),
        alpha=float(params["alpha[1]"]),
        beta=float(params["beta[1]"]),
        next_sd=math.sqrt(variance) / 100.0,
        converged=result.convergence_flag == 0,
    )


# Drawdown, concentration, correlation, beta -----------------------------------------------------


@dataclass(frozen=True)
class Drawdown:
    """Depths are positive fractions; ``peak`` and ``trough`` index the wealth series, whose
    index 0 is the start (wealth 1, before the first return)."""

    current: float
    maximum: float
    peak: int
    trough: int


def drawdown(returns: Vector) -> Drawdown:
    wealth = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    peaks = np.maximum.accumulate(wealth)
    depth = 1.0 - wealth / peaks
    trough = int(np.argmax(depth))
    peak = int(np.argmax(wealth[: trough + 1]))
    return Drawdown(float(depth[-1]), float(depth[trough]), peak, trough)


def herfindahl(values: Vector) -> float:
    """Σ sᵢ² over the shares sᵢ of a total of non-negative values."""
    if len(values) == 0 or np.any(values < 0) or values.sum() <= 0:
        raise RiskError("concentration : valeurs positives attendues")
    shares = values / values.sum()
    return float(np.sum(shares**2))


def correlation(returns: Matrix) -> Matrix:
    if np.any(np.ptp(returns, axis=0) == 0):  # exact, unlike a rounded std of a constant
        raise RiskError("corrélation : une ligne a une variance nulle")
    return np.atleast_2d(np.corrcoef(returns, rowvar=False))


def beta(returns: Vector, benchmark: Vector) -> float:
    """cov(r, b) / var(b), both with ddof=1."""
    if np.ptp(benchmark) == 0:
        raise RiskError("bêta : l'indice a une variance nulle")
    variance = float(np.var(benchmark, ddof=1))
    return float(np.cov(returns, benchmark, ddof=1)[0, 1]) / variance


@dataclass(frozen=True)
class Regression:
    """Ordinary least squares of y on x with an intercept."""

    slope: float
    standard_error: float
    p_value: float  # two-sided, Student with n − 2 degrees of freedom
    observations: int


def regression(y: Vector, x: Vector) -> Regression:
    n = len(y)
    if n < 3 or len(x) != n:
        raise RiskError("régression : au moins trois observations alignées sont nécessaires")
    if np.ptp(x) == 0:
        raise RiskError("régression : la variable explicative est constante")
    xc = x - x.mean()
    sxx = float(xc @ xc)
    slope = float(xc @ (y - y.mean())) / sxx
    residuals = y - y.mean() - slope * xc
    se = math.sqrt(float(residuals @ residuals) / (n - 2) / sxx)
    if se == 0:
        p_value = 1.0 if slope == 0 else 0.0
    else:
        p_value = float(2.0 * stats.t.sf(abs(slope / se), n - 2))
    return Regression(slope, se, p_value, n)


# Contributions and decomposition ---------------------------------------------------------------


@dataclass(frozen=True)
class Contributions:
    marginal: Vector  # ∂σ/∂wᵢ = (Σw)ᵢ / σ
    component: Vector  # wᵢ (Σw)ᵢ / σ: adds up to σ

    @property
    def shares(self) -> Vector:
        """Share of each line in the variance: adds up to 1."""
        return self.component / self.component.sum()


def volatility_contributions(weights: Vector, cov: Matrix) -> Contributions:
    sigma_w = cov @ weights
    variance = float(weights @ sigma_w)
    if variance <= 0:
        raise RiskError("contributions : la variance du portefeuille est nulle")
    marginal = sigma_w / math.sqrt(variance)
    return Contributions(marginal, weights * marginal)


def var_contributions(weights: Vector, moments: Moments, confidence: float) -> Vector:
    """Euler contributions to the parametric VaR, ``wᵢ(z(Σw)ᵢ/σ − μᵢ)``: they add up to it."""
    marginal = volatility_contributions(weights, moments.cov).marginal
    return weights * (z_score(confidence) * marginal - moments.mean)


@dataclass(frozen=True)
class VarChange:
    """Parametric VaR on EUR exposures at two dates, and the split of its change."""

    before: float
    after: float
    positions: float  # new exposures, old moments
    market: float  # old exposures, new moments
    residual: float

    @property
    def change(self) -> float:
        return self.after - self.before


def parametric_var_eur(exposures: Vector, moments: Moments, confidence: float) -> float:
    return parametric_var(
        moments.portfolio_mean(exposures), moments.portfolio_sd(exposures), confidence
    )


def var_change(
    before: tuple[Vector, Moments], after: tuple[Vector, Moments], confidence: float
) -> VarChange:
    """``before`` and ``after``: the EUR exposures and the moments on the same lines."""
    (x0, m0), (x1, m1) = before, after
    var0 = parametric_var_eur(x0, m0, confidence)
    var1 = parametric_var_eur(x1, m1, confidence)
    positions = parametric_var_eur(x1, m0, confidence) - var0
    market = parametric_var_eur(x0, m1, confidence) - var0
    return VarChange(var0, var1, positions, market, (var1 - var0) - positions - market)


# Stress ----------------------------------------------------------------------------------------


def fx_revaluation(value_eur: float, shock: float) -> float:
    """Change in EUR of a line priced in a currency whose rate per euro moves by ``shock``
    (+0.10: one euro buys 10 % more of it), exact: ``V/(1 + s) − V``."""
    if shock <= -1.0:
        raise RiskError("choc de change : supérieur à −100 % attendu")
    return value_eur / (1.0 + shock) - value_eur


def duration_impact(value_eur: float, duration: float, rates_bp: float) -> float:
    """First order: ``−D × Δy × V`` with the modified duration D [Approximation]."""
    return -duration * rates_bp / 10_000.0 * value_eur
