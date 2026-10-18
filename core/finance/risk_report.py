"""Market risk report of the book known at ``as_of`` (plan of phase 2, F2 to F4; ADR-014).

The measures come from :mod:`core.finance.risk`; this module assembles their inputs from the
store (the book, the closes adjusted for dividends and splits, the ECB rates) and returns every
number as a :class:`Figure` (R1). Conventions (ADR-014):

- one line per instrument, all accounts together, and one per cash currency: euro cash has no
  market risk, foreign cash is a currency position [Hypothèse];
- simple daily returns in euros on the sessions common to every security held; a foreign line is
  converted at the last ECB rate published on or before each session;
- the current weights are held constant over the window [Hypothèse];
- a value missing at ``as_of`` stops the report: no partial risk (R12).

No free text: the labels come from the configuration or from this module, and a sector given in
a shock is matched, not interpreted. No number appears inside a text (R1): counts, levels and
dates are fields.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, get_args

import numpy as np
import pandas as pd
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from core.config.loader import Marker, MarketRisk
from core.finance import risk
from core.finance.model import Instrument
from core.finance.portfolio import build_book, value
from core.finance.risk import Matrix, Moments, Vector
from core.finance.store import FinanceStore
from core.finance.views import ViewError
from core.verification.figures import Figure, amount, count, percent, plain

Measure = Literal[
    "volatilite",
    "var",
    "backtest",
    "drawdown",
    "beta",
    "correlations",
    "concentration",
    "contributions",
    "stress",
    "facteurs",
]
MEASURES: tuple[Measure, ...] = get_args(Measure)
DEFAULT_MEASURES: tuple[Measure, ...] = tuple(m for m in MEASURES if m != "correlations")
VarMethod = Literal["historique", "parametrique", "monte_carlo"]
StressStatus = Literal["calcule", "partiel", "bloque", "non_couvert"]
MARKERS: frozenset[str] = frozenset(get_args(Marker))
EQUITY_CLASSES = frozenset({"equity", "etf"})
CASH = "liquidites"
MAX_SECTOR_SHOCKS = 5
SECTOR_PATTERN = r"^[A-Za-zÀ-ÖØ-öø-ÿ' -]+$"

NO_POSITION = "aucune position en titres à cette date : pas de mesure de risque"
NO_FACTORS = "régression factorielle non disponible : aucune source de facteurs validée (D9)"
ASSUMPTIONS = (
    "poids actuels constants sur toute la fenêtre [Hypothèse]",
    "liquidités en euros sans risque de marché ; liquidités en devises : risque de change seul "
    "[Hypothèse]",
    "méthodes paramétrique et Monte Carlo : loi normale des rendements [Hypothèse]",
    "Monte Carlo : erreur d'échantillonnage de l'ordre de quelques pour cent au nombre de "
    "tirages configuré [Estimation]",
    "horizon de plus d'une séance : mesure d'une séance multipliée par la racine de l'horizon "
    "[Approximation]",
)


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SectorShock(BaseModel):
    """A uniform shock on the securities of one sector (as written in the reference data)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sector: Annotated[str, Field(min_length=1, max_length=40, pattern=SECTOR_PATTERN)]
    shock: Annotated[float, Field(gt=-1.0, le=1.0, description="Variation, -0.15 pour -15 %")]


# Output -----------------------------------------------------------------------------------------


class Method(_Out):
    returns: str
    window: Figure
    first_session: date
    last_session: date
    confidence_levels: list[Figure]
    horizons: list[Figure]
    annualisation: Figure
    monte_carlo_draws: Figure
    seed: Figure
    quantile: str
    assumptions: list[str]


class GarchView(_Out):
    status: Literal["estime", "non_converge"]
    next_session: Figure | None  # forecast standard deviation of the next session
    long_run: Figure | None  # unconditional standard deviation per session; None if α + β ≥ 1
    alpha: Figure | None
    beta: Figure | None
    persistence: Figure | None
    note: str


class Volatility(_Out):
    daily: Figure
    annualized: Figure
    garch: GarchView


class VarRow(_Out):
    method: VarMethod
    confidence: Figure
    horizon: Figure
    var_eur: Figure
    var_pct: Figure
    cvar_eur: Figure
    cvar_pct: Figure
    approximation: bool  # √h scaling


class BacktestRow(_Out):
    """Kupiec test of the historical VaR at one session, current weights [Hypothèse]."""

    confidence: Figure
    sessions: Figure
    complete: bool  # False when the common history is shorter than backtest.window_sessions
    exceptions: Figure
    expected: Figure
    statistic: Figure
    p_value: Figure
    significance: Figure
    verdict: Literal["rejete", "non_rejete"]


class DrawdownView(_Out):
    """Losses from the running peak, negative fractions, on the window."""

    current: Figure
    maximum: Figure
    peak: date
    trough: date


class BetaView(_Out):
    benchmark: str
    beta: Figure
    sessions: Figure
    note: str


class Correlation(_Out):
    first: str
    second: str
    value: Figure


class Concentration(_Out):
    """Securities only, on the invested value."""

    herfindahl: Figure
    effective_lines: Figure


class LineContribution(_Out):
    """Euler split; volatilities annualized; VaR in euros at one session, parametric."""

    line: str
    nature: Literal["titre", "liquidites"]
    currency: str
    value_eur: Figure
    weight: Figure
    volatility: Figure
    marginal: Figure
    contribution: Figure
    risk_share: Figure
    var_eur: dict[str, Figure]  # by confidence level, "95" for 95 %


class RateSplit(_Out):
    """The rate shock in two parts: the bonds by their duration [Approximation], the other
    securities by an OLS of their daily euro P&L on the daily change of the risk-free rate, on
    the window [Estimation]. A p-value far from zero means the estimate is not distinguishable
    from no sensitivity at all."""

    series: str
    duration_lines: list[str]
    duration_eur: Figure
    estimated_lines: list[str]
    estimated_eur: Figure | None
    standard_error_eur: Figure | None
    p_value: Figure | None
    sessions: Figure | None


class StressResult(_Out):
    scenario: str
    label: str
    status: StressStatus
    shock: Figure | None
    impact_eur: Figure | None
    impact_pct: Figure | None
    not_estimated: list[str]
    note: str
    sector: str | None = None
    rates: RateSplit | None = None
    start: date | None = None
    end: date | None = None


class VarChangeRow(_Out):
    confidence: Figure
    before: Figure
    after: Figure
    change: Figure
    positions_effect: Figure  # new exposures, old moments
    market_effect: Figure  # old exposures, new moments
    residual: Figure


class ExposureChange(_Out):
    line: str
    before: Figure
    after: Figure
    change: Figure


class VarChangeView(_Out):
    compare_to: AwareDatetime
    day: date
    method: str
    rows: list[VarChangeRow]
    exposures: list[ExposureChange]


class Unavailable(_Out):
    measure: str
    reason: str


class RiskReport(_Out):
    as_of: AwareDatetime
    day: date
    strict: bool
    value_eur: Figure
    measures: list[Measure]
    method: Method
    volatility: Volatility | None = None
    var: list[VarRow] | None = None
    backtest: list[BacktestRow] | None = None
    drawdown: DrawdownView | None = None
    beta: BetaView | None = None
    correlations: list[Correlation] | None = None
    concentration: Concentration | None = None
    contributions: list[LineContribution] | None = None
    stress: list[StressResult] | None = None
    var_change: VarChangeView | None = None
    unavailable: list[Unavailable]
    warnings: list[str]


# Inputs from the store ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Line:
    key: str  # the instrument, or ``liquidites-<currency>``
    currency: str
    instrument: Instrument | None  # None for cash

    @property
    def is_cash(self) -> bool:
        return self.instrument is None


@dataclass(frozen=True)
class Holdings:
    day: date
    lines: list[Line]  # securities, then cash, each by key
    values: dict[str, float]  # value in euros by line
    warnings: list[str]
    quantities: dict[str, Decimal] = field(default_factory=dict)  # securities, all accounts

    def exposures(self, lines: Sequence[Line]) -> Vector:
        return np.array([self.values.get(line.key, 0.0) for line in lines], dtype=float)


@dataclass(frozen=True)
class Market:
    prices: pd.DataFrame  # euro prices, one column per line, on the common sessions
    returns: Matrix  # simple returns, one row per session after the first


def holdings(store: FinanceStore, *, as_of: datetime, strict: bool) -> Holdings:
    book = build_book(store, as_of=as_of, strict=strict)
    valuation = value(store, book, strict=strict)
    if valuation.total_eur is None:
        raise ViewError(
            f"{', '.join(valuation.missing)} : valeur inconnue à cette date ; pas de mesure de "
            "risque partielle (R12)"
        )
    lines: dict[str, Line] = {}
    sums: defaultdict[str, list[float]] = defaultdict(list)
    quantities: defaultdict[str, Decimal] = defaultdict(Decimal)
    for held in valuation.lines:
        if not held.quantity:
            continue
        if held.nature == "security":
            key = held.asset
            if key not in lines:
                card = store.instrument(key, as_of=as_of, strict=strict)
                if card is None:
                    raise ViewError(f"{key} : absent du référentiel à cette date")
                lines[key] = Line(key, held.currency, card)
            quantities[key] += held.quantity
        else:
            key = f"{CASH}-{held.currency}"
            lines.setdefault(key, Line(key, held.currency, None))
        sums[key].append(held.value_eur or 0.0)
    ordered = sorted(lines.values(), key=lambda line: (line.is_cash, line.key))
    values = {key: math.fsum(parts) for key, parts in sums.items()}
    return Holdings(book.day, ordered, values, list(book.warnings), dict(quantities))


def _per_euro(
    store: FinanceStore,
    currency: str,
    sessions: pd.DatetimeIndex,
    *,
    as_of: datetime,
    day: date,
    strict: bool,
) -> pd.Series:
    """Units of ``currency`` per euro on each session: the last ECB rate published by then."""
    if currency == "EUR":
        return pd.Series(1.0, index=sessions)
    known = store.fx_rates(currency, as_of=as_of, end=day, strict=strict)
    return known.reindex(sessions, method="ffill")


def market(
    store: FinanceStore, lines: Sequence[Line], *, as_of: datetime, day: date, strict: bool
) -> Market:
    closes = {
        line.key: store.closes(line.key, as_of=as_of, end=day, adjust="total_return", strict=strict)
        for line in lines
        if not line.is_cash
    }
    indexes = [series.index for series in closes.values()]
    sessions = indexes[0]
    for index in indexes[1:]:
        sessions = sessions.intersection(index)
    sessions = pd.DatetimeIndex(sessions).sort_values()
    rates: dict[str, pd.Series] = {}
    columns = {}
    for line in lines:
        if line.currency not in rates:
            rates[line.currency] = _per_euro(
                store, line.currency, sessions, as_of=as_of, day=day, strict=strict
            )
        local = 1.0 if line.is_cash else closes[line.key].reindex(sessions)
        columns[line.key] = local / rates[line.currency]
    prices = pd.DataFrame(columns, index=sessions).dropna()
    returns = prices.pct_change().iloc[1:].to_numpy(dtype=float)
    return Market(prices, returns)


def _window(found: Market, window: int, moment: str) -> Matrix:
    if len(found.returns) < window:
        raise ViewError(
            f"historique insuffisant à {moment} : les titres détenus ont moins de séances communes "
            "que la fenêtre de la VaR (var.window_sessions)"
        )
    return found.returns[-window:]


# Figures --------------------------------------------------------------------------------------


def _level(confidence: float) -> str:
    return f"{confidence * 100:g}"


def _eur(figure_id: str, amount_eur: float) -> Figure:
    return amount(figure_id, float(amount_eur), "EUR")


def _pct(figure_id: str, fraction: float) -> Figure:
    return percent(figure_id, float(fraction))


# Measures -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Book:
    """What every measure reads: the lines, their exposures, the window and its moments."""

    config: MarketRisk
    lines: list[Line]
    exposures: Vector  # euros
    total: float
    weights: Vector
    market: Market
    window: Matrix
    moments: Moments

    @property
    def portfolio_returns(self) -> Vector:
        return self.window @ self.weights

    @property
    def sessions(self) -> list[date]:
        """The sessions of the window prices: one more than its returns."""
        index = self.market.prices.index[-(len(self.window) + 1) :]
        return [session.date() for session in index]

    @property
    def securities(self) -> list[int]:
        return [i for i, line in enumerate(self.lines) if not line.is_cash]


def _method(book: _Book) -> Method:
    var = book.config.var
    sessions = book.sessions
    return Method(
        returns=(
            "rendements simples quotidiens en euros, cours ajustés des dividendes et des "
            "divisions, séances communes à tous les titres détenus"
        ),
        window=count("methode/fenetre", len(book.window), "séances"),
        first_session=sessions[0],
        last_session=sessions[-1],
        confidence_levels=[
            _pct(f"methode/confiance/{_level(c)}", c) for c in var.confidence_levels
        ],
        horizons=[count(f"methode/horizon/{h}", h, "séances") for h in var.horizons_sessions],
        annualisation=count("methode/annualisation", book.config.annualisation_sessions, "séances"),
        monte_carlo_draws=count("methode/tirages", var.monte_carlo_draws, "tirages"),
        seed=plain("methode/graine", float(var.seed), "graine", 0),
        quantile='quantile linéaire des pertes (numpy, method="linear") ; CVaR : moyenne des '
        "pertes au-delà de la VaR",
        assumptions=list(ASSUMPTIONS),
    )


def _volatility(book: _Book) -> tuple[Volatility, list[str]]:
    sessions = book.config.annualisation_sessions
    daily = book.moments.portfolio_sd(book.weights)
    warnings: list[str] = []
    note = "GARCH(1,1), moyenne constante, loi normale, estimé par arch sur la fenêtre [Estimation]"
    try:
        fit: risk.Garch | None = risk.garch(book.portfolio_returns)
    except (ValueError, np.linalg.LinAlgError):
        fit = None
    if fit is None or not fit.converged:
        warnings.append("GARCH : l'estimation n'a pas convergé ; aucune prévision n'est donnée")
        garch = GarchView(
            status="non_converge",
            next_session=None,
            long_run=None,
            alpha=None,
            beta=None,
            persistence=None,
            note=note,
        )
    else:
        long_run = fit.long_run_sd
        garch = GarchView(
            status="estime",
            next_session=_pct("volatilite/garch/prochaine_seance", fit.next_sd),
            long_run=None if long_run is None else _pct("volatilite/garch/long_terme", long_run),
            alpha=plain("volatilite/garch/alpha", fit.alpha, "coefficient", 3),
            beta=plain("volatilite/garch/beta", fit.beta, "coefficient", 3),
            persistence=plain("volatilite/garch/persistance", fit.persistence, "coefficient", 3),
            note=note,
        )
    return (
        Volatility(
            daily=_pct("volatilite/quotidienne", daily),
            annualized=_pct("volatilite/annualisee", risk.annualized(daily, sessions)),
            garch=garch,
        ),
        warnings,
    )


def _var(book: _Book) -> list[VarRow]:
    var = book.config.var
    w, m = book.weights, book.moments
    losses = -book.portfolio_returns
    simulated = risk.monte_carlo_losses(m, w, var.monte_carlo_draws, var.seed)
    mean, sd = m.portfolio_mean(w), m.portfolio_sd(w)

    def one_session(method: VarMethod, c: float) -> tuple[float, float]:
        if method == "historique":
            return risk.historical_var(losses, c), risk.historical_cvar(losses, c)
        if method == "parametrique":
            return risk.parametric_var(mean, sd, c), risk.parametric_cvar(mean, sd, c)
        return risk.historical_var(simulated, c), risk.historical_cvar(simulated, c)

    rows = []
    for method in get_args(VarMethod):
        for c in var.confidence_levels:
            var1, cvar1 = one_session(method, c)
            for h in var.horizons_sessions:
                base = f"var/{method}/{_level(c)}/{h}"
                v, cv = risk.scaled(var1, h), risk.scaled(cvar1, h)
                rows.append(
                    VarRow(
                        method=method,
                        confidence=_pct(f"{base}/confiance", c),
                        horizon=count(f"{base}/horizon", h, "séances"),
                        var_eur=_eur(f"{base}/eur", v * book.total),
                        var_pct=_pct(f"{base}/pct", v),
                        cvar_eur=_eur(f"{base}/cvar_eur", cv * book.total),
                        cvar_pct=_pct(f"{base}/cvar_pct", cv),
                        approximation=h > 1,
                    )
                )
    return rows


def _backtest(book: _Book) -> tuple[list[BacktestRow], list[str]]:
    config = book.config
    losses = -(book.market.returns @ book.weights)
    rows = []
    for c in config.var.confidence_levels:
        exceptions, observations = risk.rolling_exceptions(
            losses, len(book.window), c, config.backtest.window_sessions
        )
        if observations == 0:
            return [], ["backtest impossible : aucune séance après la première fenêtre de VaR"]
        test = risk.kupiec(exceptions, observations, c)
        base = f"backtest/{_level(c)}"
        rows.append(
            BacktestRow(
                confidence=_pct(f"{base}/confiance", c),
                sessions=count(f"{base}/seances", observations, "séances"),
                complete=observations == config.backtest.window_sessions,
                exceptions=count(f"{base}/exceptions", exceptions, "exceptions"),
                expected=plain(f"{base}/attendues", test.expected, "exceptions", 1, show_unit=True),
                statistic=plain(f"{base}/statistique", test.statistic, "statistique", 3),
                p_value=plain(f"{base}/p_value", test.p_value, "probabilite", 3),
                significance=_pct(f"{base}/seuil", config.backtest.significance),
                verdict="rejete" if test.rejected(config.backtest.significance) else "non_rejete",
            )
        )
    warnings = []
    if not all(row.complete for row in rows):
        warnings.append(
            "backtest incomplet : l'historique commun est plus court que la fenêtre prévue "
            "(voir backtest.sessions)"
        )
    return rows, warnings


def _drawdown(book: _Book) -> DrawdownView:
    found = risk.drawdown(book.portfolio_returns)
    sessions = book.sessions
    return DrawdownView(
        current=_pct("drawdown/actuel", -found.current),
        maximum=_pct("drawdown/maximum", -found.maximum),
        peak=sessions[found.peak],
        trough=sessions[found.trough],
    )


def _correlations(book: _Book) -> list[Correlation]:
    picked = book.securities
    matrix = risk.correlation(book.window[:, picked])
    keys = [book.lines[i].key for i in picked]
    return [
        Correlation(
            first=keys[i],
            second=keys[j],
            value=plain(f"correlations/{keys[i]}/{keys[j]}", float(matrix[i, j]), "correlation"),
        )
        for i in range(len(keys))
        for j in range(i + 1, len(keys))
    ]


def _concentration(book: _Book) -> Concentration:
    hhi = risk.herfindahl(book.exposures[book.securities])
    return Concentration(
        herfindahl=plain("concentration/herfindahl", hhi, "indice", 4),
        effective_lines=plain(
            "concentration/lignes_effectives", 1.0 / hhi, "lignes", 2, show_unit=True
        ),
    )


def _contributions(book: _Book) -> list[LineContribution]:
    scale = math.sqrt(book.config.annualisation_sessions)
    split = risk.volatility_contributions(book.weights, book.moments.cov)
    own = np.sqrt(np.clip(np.diag(book.moments.cov), 0.0, None))
    levels = book.config.var.confidence_levels
    var_eur = {
        c: risk.var_contributions(book.weights, book.moments, c) * book.total for c in levels
    }
    rows = []
    for i, line in enumerate(book.lines):
        base = f"contributions/{line.key}"
        rows.append(
            LineContribution(
                line=line.key,
                nature="liquidites" if line.is_cash else "titre",
                currency=line.currency,
                value_eur=_eur(f"{base}/valeur_eur", book.exposures[i]),
                weight=_pct(f"{base}/poids", book.weights[i]),
                volatility=_pct(f"{base}/volatilite", own[i] * scale),
                marginal=_pct(f"{base}/marginale", split.marginal[i] * scale),
                contribution=_pct(f"{base}/contribution", split.component[i] * scale),
                risk_share=_pct(f"{base}/part_risque", split.shares[i]),
                var_eur={_level(c): _eur(f"{base}/var/{_level(c)}", var_eur[c][i]) for c in levels},
            )
        )
    return rows


@dataclass(frozen=True)
class _Beta:
    view: BetaView | None
    reason: str | None
    blocked: bool


def _beta(store: FinanceStore, book: _Book, *, as_of: datetime, day: date, strict: bool) -> _Beta:
    isin = book.config.benchmark.isin
    if isin in MARKERS:
        return _Beta(None, f"indice de référence bloqué : ISIN {isin} (D8)", blocked=True)
    found = [i for i in store.instruments(as_of=as_of, strict=strict) if i.isin == isin]
    if not found:
        return _Beta(None, "indice de référence absent du référentiel de la base", blocked=False)
    benchmark = found[0]
    index = book.market.prices.index[-(len(book.window) + 1) :]
    closes = store.closes(
        benchmark.instrument_id, as_of=as_of, end=day, adjust="total_return", strict=strict
    )
    rate = _per_euro(store, benchmark.currency, index, as_of=as_of, day=day, strict=strict)
    prices = closes.reindex(index) / rate
    if prices.isna().any():
        return _Beta(
            None, "série de l'indice de référence incomplète sur la fenêtre", blocked=False
        )
    returns = prices.pct_change().iloc[1:].to_numpy(dtype=float)
    value_ = risk.beta(book.portfolio_returns, returns)
    view = BetaView(
        benchmark=benchmark.instrument_id,
        beta=plain("beta/portefeuille", value_, "beta"),
        sessions=count("beta/seances", len(returns), "séances"),
        note="bêta du portefeuille actuel contre l'indice, rendements quotidiens en euros "
        "[Estimation]",
    )
    return _Beta(view, None, blocked=False)


def _result(
    book: _Book,
    scenario: str,
    label: str,
    impact: float | None,
    *,
    status: StressStatus,
    note: str,
    shock: Figure | None = None,
    not_estimated: Sequence[str] = (),
    **extra: object,
) -> StressResult:
    base = f"stress/{scenario}"
    return StressResult(
        scenario=scenario,
        label=label,
        status=status,
        shock=shock,
        impact_eur=None if impact is None else _eur(f"{base}/impact_eur", impact),
        impact_pct=None if impact is None else _pct(f"{base}/impact_pct", impact / book.total),
        not_estimated=list(not_estimated),
        note=note,
        **extra,  # type: ignore[arg-type]
    )


def _stress(
    book: _Book, beta: _Beta, rate_changes: Vector | None, shocks: Sequence[SectorShock]
) -> list[StressResult]:
    stress = book.config.hypothetical_stress
    values = dict(zip((line.key for line in book.lines), book.exposures.tolist(), strict=True))
    securities = [line for line in book.lines if line.instrument is not None]
    results = []

    results.append(_rate_stress(book, rate_changes))

    equities = [
        line.key
        for line in securities
        if line.instrument and line.instrument.asset_class in EQUITY_CLASSES
    ]
    results.append(
        _result(
            book,
            "actions",
            "Choc actions",
            stress.equity_shock * math.fsum(values[key] for key in equities),
            status="calcule",
            shock=_pct("stress/actions/choc", stress.equity_shock),
            note="choc uniforme sur les actions et les ETF actions [Hypothèse] ; autres lignes "
            "inchangées",
        )
    )
    beta_shock = _pct("stress/actions_beta/choc", stress.equity_shock)
    if beta.view is None:
        results.append(
            _result(
                book,
                "actions_beta",
                "Choc de l'indice transmis par le bêta",
                None,
                status="bloque" if beta.blocked else "non_couvert",
                shock=beta_shock,
                note=beta.reason or "",
            )
        )
    else:
        results.append(
            _result(
                book,
                "actions_beta",
                "Choc de l'indice transmis par le bêta",
                stress.equity_shock * beta.view.beta.value * book.total,
                status="calcule",
                shock=beta_shock,
                note="modèle de marché à un facteur : choc de l'indice multiplié par le bêta du "
                "portefeuille [Hypothèse]",
            )
        )

    dollar = [line.key for line in book.lines if line.currency == "USD"]
    for s in stress.fx_eurusd_shocks:
        scenario = f"eurusd/{s * 100:+g}"
        results.append(
            _result(
                book,
                scenario,
                "Choc EUR/USD",
                math.fsum(risk.fx_revaluation(values[key], s) for key in dollar),
                status="calcule",
                shock=_pct(f"stress/{scenario}/choc", s),
                note="dollars pour un euro : conversion exacte des lignes en dollars, prix en "
                "dollars inchangés [Hypothèse]",
            )
        )

    for n, shock in enumerate(shocks, start=1):
        wanted = shock.sector.casefold()
        matched = [
            line.key
            for line in securities
            if line.instrument and line.instrument.sector.casefold() == wanted
        ]
        results.append(
            _result(
                book,
                f"secteur/{n}",
                "Choc sectoriel",
                shock.shock * math.fsum(values[key] for key in matched),
                status="calcule",
                shock=_pct(f"stress/secteur/{n}/choc", shock.shock),
                sector=shock.sector,
                note="choc uniforme sur les titres du secteur [Hypothèse]"
                if matched
                else "aucune ligne de ce secteur dans le portefeuille",
            )
        )
    results.extend(_historical(book, values))
    return results


def rate_changes(
    store: FinanceStore, book: _Book, *, as_of: datetime, day: date, strict: bool
) -> Vector | None:
    """Daily changes of the risk-free rate on the window, as fractions (0.0001 for 1 bp): the
    last value published by each session. None when the series does not cover the window."""
    index = book.market.prices.index[-(len(book.window) + 1) :]
    known = store.rates(book.config.risk_free, as_of=as_of, end=day, strict=strict)
    level = known.reindex(index, method="ffill")
    if level.isna().any():
        return None
    return np.diff(level.to_numpy(dtype=float)) / 100.0


def _rate_stress(book: _Book, changes: Vector | None) -> StressResult:
    bp = book.config.hypothetical_stress.rates_bp
    shift = bp / 10_000.0
    by_duration, estimated, not_estimated = [], [], []
    for i, line in enumerate(book.lines):
        card = line.instrument
        if card is None:
            continue  # cash: no rate effect
        if card.asset_class == "bond":
            (by_duration if _known(card.duration) else not_estimated).append(i)
        else:
            estimated.append(i)
    duration_eur = math.fsum(
        risk.duration_impact(
            float(book.exposures[i]),
            float(book.lines[i].instrument.duration),  # type: ignore[union-attr, arg-type]
            bp,
        )
        for i in by_duration
    )
    fit: risk.Regression | None = None
    reason = ""
    if estimated:
        if changes is None:
            reason = " ; série du taux sans risque incomplète sur la fenêtre : autres titres non "
            "estimés"
        else:
            pnl = book.window[:, estimated] @ book.exposures[estimated]
            try:
                fit = risk.regression(pnl, changes)
            except risk.RiskError:
                reason = " ; taux sans risque constant sur la fenêtre : autres titres non estimés"
        if fit is None:
            not_estimated += estimated
    keys = [line.key for line in book.lines]
    base = "stress/taux"
    split = RateSplit(
        series=book.config.risk_free,
        duration_lines=[keys[i] for i in by_duration],
        duration_eur=_eur(f"{base}/duration_eur", duration_eur),
        estimated_lines=[keys[i] for i in estimated] if fit else [],
        estimated_eur=None if fit is None else _eur(f"{base}/estime_eur", fit.slope * shift),
        standard_error_eur=None
        if fit is None
        else _eur(f"{base}/ecart_type_eur", fit.standard_error * abs(shift)),
        p_value=None if fit is None else plain(f"{base}/p_value", fit.p_value, "probabilite", 3),
        sessions=None if fit is None else count(f"{base}/seances", fit.observations, "séances"),
    )
    total = duration_eur + (fit.slope * shift if fit else 0.0)
    return _result(
        book,
        "taux",
        "Choc de taux",
        total,
        status="partiel" if not_estimated else "calcule",
        shock=plain(f"{base}/choc", bp, "pb", 0, show_unit=True),
        not_estimated=sorted(keys[i] for i in not_estimated),
        rates=split,
        note="obligations : duration modifiée, premier ordre [Approximation] ; autres titres : "
        "sensibilité estimée aux variations quotidiennes de l'€STR, un taux au jour le jour qui "
        "ne représente pas les taux longs [Estimation] ; liquidités sans effet" + reason,
    )


def _known(duration: object) -> bool:
    return isinstance(duration, float | int) and not isinstance(duration, bool)


def _historical(book: _Book, values: dict[str, float]) -> list[StressResult]:
    prices = book.market.prices
    first, last = prices.index[0].date(), prices.index[-1].date()
    results = []
    for name, window in book.config.historical_stress.items():
        scenario = f"historique/{name}"
        unknown = [
            f"{field} = {getattr(window, field)}"
            for field in ("start", "end", "source")
            if getattr(window, field) in MARKERS
        ]
        start, end = window.start, window.end
        if unknown or not isinstance(start, date) or not isinstance(end, date):
            results.append(
                _result(
                    book,
                    scenario,
                    window.label,
                    None,
                    status="bloque",
                    note=f"dates et source à relever avant usage (D10) : {', '.join(unknown)}",
                )
            )
            continue
        dates = {"start": start, "end": end}
        if start >= end:
            results.append(
                _result(
                    book,
                    scenario,
                    window.label,
                    None,
                    status="bloque",
                    note="fenêtre invalide : le début n'est pas avant la fin",
                    **dates,
                )
            )
            continue
        if start < first or end > last:
            results.append(
                _result(
                    book,
                    scenario,
                    window.label,
                    None,
                    status="non_couvert",
                    note="l'historique commun de la base ne couvre pas cette fenêtre",
                    **dates,
                )
            )
            continue
        before = prices.loc[: pd.Timestamp(start)].iloc[-1]
        after = prices.loc[: pd.Timestamp(end)].iloc[-1]
        moves = (after / before - 1.0).to_dict()
        results.append(
            _result(
                book,
                scenario,
                window.label,
                math.fsum(values[key] * moves[key] for key in values),
                status="calcule",
                note=f"positions actuelles soumises aux variations de la fenêtre [Hypothèse] ; "
                f"source : {window.source}",
                **dates,
            )
        )
    return results


def _var_change(
    store: FinanceStore,
    book: _Book,
    now: Holdings,
    *,
    as_of: datetime,
    compare_to: datetime,
    strict: bool,
) -> VarChangeView:
    then = holdings(store, as_of=compare_to, strict=strict)
    known = {line.key: line for line in then.lines} | {line.key: line for line in now.lines}
    union = sorted(known.values(), key=lambda line: (line.is_cash, line.key))
    if all(line.is_cash for line in union):
        raise ViewError(NO_POSITION)
    window = len(book.window)
    m0 = risk.moments(
        _window(
            market(store, union, as_of=compare_to, day=then.day, strict=strict),
            window,
            "compare_to",
        )
    )
    m1 = risk.moments(
        _window(market(store, union, as_of=as_of, day=now.day, strict=strict), window, "as_of")
    )
    x0, x1 = then.exposures(union), now.exposures(union)
    rows = []
    for c in book.config.var.confidence_levels:
        split = risk.var_change((x0, m0), (x1, m1), c)
        base = f"variation_var/{_level(c)}"
        rows.append(
            VarChangeRow(
                confidence=_pct(f"{base}/confiance", c),
                before=_eur(f"{base}/avant", split.before),
                after=_eur(f"{base}/apres", split.after),
                change=_eur(f"{base}/variation", split.change),
                positions_effect=_eur(f"{base}/effet_positions", split.positions),
                market_effect=_eur(f"{base}/effet_marche", split.market),
                residual=_eur(f"{base}/residu", split.residual),
            )
        )
    exposures = [
        ExposureChange(
            line=line.key,
            before=_eur(f"variation_var/expositions/{line.key}/avant", x0[i]),
            after=_eur(f"variation_var/expositions/{line.key}/apres", x1[i]),
            change=_eur(f"variation_var/expositions/{line.key}/variation", x1[i] - x0[i]),
        )
        for i, line in enumerate(union)
    ]
    return VarChangeView(
        compare_to=compare_to,
        day=then.day,
        method="VaR paramétrique d'une séance en euros, sur l'union des lignes des deux dates ; "
        "chaque date avec sa propre fenêtre, connue à cette date",
        rows=rows,
        exposures=exposures,
    )


# Report -----------------------------------------------------------------------------------------


def risk_report(
    store: FinanceStore,
    config: MarketRisk,
    *,
    as_of: datetime,
    measures: Sequence[Measure] | None = None,
    compare_to: datetime | None = None,
    sector_shocks: Sequence[SectorShock] = (),
    strict: bool = False,
) -> RiskReport:
    """The measures asked for, on the book known at ``as_of`` (by default, all but the
    correlations); ``compare_to`` adds the change of the parametric VaR since that moment."""
    if measures is not None and not measures:
        raise ViewError("au moins une mesure")
    wanted = list(dict.fromkeys(measures or DEFAULT_MEASURES))
    if compare_to is not None and compare_to >= as_of:
        raise ViewError("compare_to doit précéder as_of")
    if len(sector_shocks) > MAX_SECTOR_SHOCKS:
        raise ViewError(f"au plus {MAX_SECTOR_SHOCKS} chocs sectoriels")
    try:
        return _report(store, config, as_of, wanted, compare_to, sector_shocks, strict)
    except risk.RiskError as exc:
        raise ViewError(str(exc)) from None


def _report(
    store: FinanceStore,
    config: MarketRisk,
    as_of: datetime,
    wanted: list[Measure],
    compare_to: datetime | None,
    sector_shocks: Sequence[SectorShock],
    strict: bool,
) -> RiskReport:
    now = holdings(store, as_of=as_of, strict=strict)
    if all(line.is_cash for line in now.lines):
        raise ViewError(NO_POSITION)
    exposures = now.exposures(now.lines)
    total = math.fsum(exposures.tolist())
    if total <= 0:
        raise ViewError("valeur du portefeuille nulle ou négative : pas de mesure de risque")
    found = market(store, now.lines, as_of=as_of, day=now.day, strict=strict)
    window = _window(found, config.var.window_sessions, "as_of")
    book = _Book(
        config, now.lines, exposures, total, exposures / total, found, window, risk.moments(window)
    )
    warnings = list(now.warnings)
    unavailable: list[Unavailable] = []
    parts: dict[str, object] = {}
    if "volatilite" in wanted:
        parts["volatility"], extra = _volatility(book)
        warnings += extra
    if "var" in wanted:
        parts["var"] = _var(book)
    if "backtest" in wanted:
        rows, extra = _backtest(book)
        parts["backtest"] = rows or None
        warnings += extra
    if "drawdown" in wanted:
        parts["drawdown"] = _drawdown(book)
    if "beta" in wanted or "stress" in wanted:
        beta = _beta(store, book, as_of=as_of, day=now.day, strict=strict)
        if "beta" in wanted:
            parts["beta"] = beta.view
            if beta.view is None:
                unavailable.append(Unavailable(measure="beta", reason=beta.reason or ""))
    if "correlations" in wanted:
        parts["correlations"] = _correlations(book)
    if "concentration" in wanted:
        parts["concentration"] = _concentration(book)
    if "contributions" in wanted:
        parts["contributions"] = _contributions(book)
    if "stress" in wanted:
        changes = rate_changes(store, book, as_of=as_of, day=now.day, strict=strict)
        parts["stress"] = _stress(book, beta, changes, sector_shocks)
    elif sector_shocks:
        warnings.append("chocs sectoriels ignorés : la mesure stress n'est pas demandée")
    if "facteurs" in wanted:
        unavailable.append(Unavailable(measure="facteurs", reason=NO_FACTORS))
    if compare_to is not None:
        parts["var_change"] = _var_change(
            store, book, now, as_of=as_of, compare_to=compare_to, strict=strict
        )
    return RiskReport(
        as_of=as_of,
        day=now.day,
        strict=strict,
        value_eur=_eur("valeur_eur", total),
        measures=wanted,
        method=_method(book),
        unavailable=unavailable,
        warnings=warnings,
        **parts,  # type: ignore[arg-type]
    )


__all__ = [
    "DEFAULT_MEASURES",
    "MAX_SECTOR_SHOCKS",
    "MEASURES",
    "Measure",
    "RiskReport",
    "SectorShock",
    "risk_report",
]
