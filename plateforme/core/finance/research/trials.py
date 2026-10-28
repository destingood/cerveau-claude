"""The fingerprints and the measures of a research trial (ADR-026, ADR-027).

Every evaluated combination of a strategy and its parameters becomes one ``ResearchTrial`` in the
append-only journal of the finance store: the deflated Sharpe ratio counts them all, whatever
their origin. The fingerprints tie a trial to the exact code, parameters and return series.
"""

from __future__ import annotations

import hashlib
import inspect
import sys
from collections.abc import Mapping, Sequence

import pandas as pd

from core.finance.model import ParamValue, ResearchTrial, TrialOrigin, params_sha256
from core.finance.performance import daily_returns, sharpe
from core.finance.research.strategy import Strategy


class TrialError(ValueError):
    """A trial that cannot be measured or fingerprinted."""


def source_sha256(text: str) -> str:
    """SHA-256 of a source text with LF line ends: a Windows checkout gives the same print."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def strategy_code_sha256(strategy: Strategy) -> str:
    """SHA-256 of the module that defines the strategy (ADR-027).

    Only that module: a helper it imports from elsewhere is not covered [Hypothèse].
    """
    module = sys.modules.get(type(strategy).__module__)
    if module is None:
        raise TrialError(f"{strategy.name} : module de la stratégie introuvable")
    try:
        text = inspect.getsource(module)
    except (OSError, TypeError) as exc:
        raise TrialError(f"{strategy.name} : source de la stratégie illisible") from exc
    return source_sha256(text)


def series_sha256(returns: pd.Series) -> str:
    """SHA-256 of a daily return series: one ``date hex`` line per session, exact to the bit."""
    lines = [
        f"{stamp.date().isoformat()} {float(value).hex()}\n" for stamp, value in returns.items()
    ]
    return hashlib.sha256("".join(lines).encode("ascii")).hexdigest()


def value_returns(values: pd.Series) -> pd.Series:
    """The daily returns V_d / V_{d−1} − 1 of a value curve, indexed by their session."""
    if len(values) < 3:
        raise TrialError("au moins trois séances pour mesurer un essai")
    return pd.Series(
        daily_returns(values.tolist(), [0.0] * (len(values) - 1)), index=values.index[1:]
    )


def make_trial(
    *,
    strategy: str,
    code_sha256: str,
    params: Mapping[str, ParamValue],
    origin: TrialOrigin,
    values: pd.Series,
    sessions_per_year: int,
    costs: str,
    engine: str,
    risk_free: Sequence[float] | None = None,
    source: str | None = None,
) -> ResearchTrial:
    """The trial of one value curve: its daily returns, Sharpe ratios and fingerprints.

    ``values`` is the portfolio value at each session, indexed by date. Without ``risk_free``
    the Sharpe ratios use a zero rate, as ``engine.measures`` does [Hypothèse].
    """
    returns = value_returns(values)
    if risk_free is not None and len(risk_free) != len(returns):
        raise TrialError("un taux sans risque par rendement quotidien attendu")
    excess = (
        returns.tolist()
        if risk_free is None
        else [r - f for r, f in zip(returns.tolist(), risk_free, strict=True)]
    )
    return ResearchTrial(
        strategy=strategy,
        code_sha256=code_sha256,
        params=dict(params),
        params_sha256=params_sha256(params),
        origin=origin,
        start=values.index[0].date(),
        end=values.index[-1].date(),
        sessions=len(returns),
        sharpe_daily=sharpe(excess, 1),
        sharpe_annual=sharpe(excess, sessions_per_year),
        series_sha256=series_sha256(returns),
        costs=costs,
        engine=engine,
        source=source,
    )
