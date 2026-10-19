"""The performance of the book over a period, with its attribution (plan of phase 2, F9).

Every number is a :class:`~core.verification.figures.Figure` computed by
:mod:`core.finance.performance` (R1); the conventions are those of ADR-020. A measure that
cannot be computed is listed in ``unavailable`` with its reason rather than estimated (R12).
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from core.config.loader import Config
from core.finance import performance as pf
from core.finance.risk_report import Unavailable
from core.finance.store import FinanceStore
from core.verification.figures import Figure, amount, count, percent, plain

NOTICE = "aide à la décision personnelle, pas un conseil en investissement (R16)"
UNCLASSIFIED = "non classé"
SHORT = "période de moins d'un an : pas d'annualisation"


def assumptions(sessions: int) -> list[str]:
    return [
        "TWR : rendements quotidiens chaînés sur les jours de valorisation (jours TARGET, le "
        "premier jour de la période comme base, le dernier jour comme fin) ; dépôts et retraits "
        "comptés en fin de journée [Hypothèse]",
        "valeur de fin de journée : derniers cours et taux de référence BCE publiés à la date de "
        "lecture, comme portfolio_snapshot",
        "dividendes, frais et conversions restent dans le rendement ; seuls les dépôts et "
        "retraits sont des flux externes",
        "MWR : taux qui annule la valeur actuelle des flux, temps en jours calendaires",
        "annualisation ACT/365, seulement sur une période d'au moins un an",
        f"volatilité, Sharpe et Sortino : écart type de l'échantillon des rendements quotidiens, "
        f"× √{sessions} séances [Hypothèse]",
        "taux sans risque : €STR capitalisé comme la BCE (ACT/360, chaque jour calendaire au "
        "fixing du dernier jour TARGET) ; Sortino sur les rendements excédentaires, cible zéro "
        "(convention skfolio)",
        "perte maximale sur l'indice TWR, la base comptant comme un sommet (convention skfolio)",
        "contribution d'une ligne : gain du jour, transactions au taux BCE de leur date, rapporté "
        "à la valeur de la veille et pondéré par l'indice TWR de la veille ; les contributions "
        "somment au TWR",
    ]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Period(_Out):
    start: date
    end: date
    calendar_days: Figure
    returns: Figure  # daily returns, one per valuation day after the base


class Values(_Out):
    start_eur: Figure
    end_eur: Figure
    net_deposits_eur: Figure  # deposits minus withdrawals
    gain_eur: Figure  # end − start − net deposits
    dividends_eur: Figure  # net of withholding, already in the gain
    fees_eur: Figure  # account and custody fees, already in the gain


class DrawdownView(_Out):
    depth: Figure
    peak: date
    trough: date
    recovery: date | None


class Measures(_Out):
    twr: Figure
    twr_annualized: Figure | None
    mwr: Figure | None
    mwr_annualized: Figure | None
    volatility: Figure | None
    risk_free: Figure | None  # €STR compounded over the period
    sharpe: Figure | None
    sortino: Figure | None
    max_drawdown: DrawdownView
    calmar: Figure | None


class LineContribution(_Out):
    line: str
    name: str
    sector: str
    currency: str
    gain_eur: Figure
    contribution: Figure


class SectorContribution(_Out):
    sector: str
    gain_eur: Figure
    contribution: Figure


class Attribution(_Out):
    lines: list[LineContribution]
    sectors: list[SectorContribution]
    total: Figure
    residual: Figure  # TWR − Σ contributions: rounding only


class PerformanceReport(_Out):
    parity_label: Literal["[Parité]"] = "[Parité]"  # as plugin.yaml (R12)
    as_of: AwareDatetime
    strict: bool
    notice: str
    period: Period
    values: Values
    measures: Measures
    attribution: Attribution
    assumptions: list[str]
    unavailable: list[Unavailable]
    warnings: list[str]


def _eur(figure_id: str, value: float) -> Figure:
    return amount(figure_id, float(value), "EUR")


def _pct(figure_id: str, fraction: float | None) -> Figure | None:
    return None if fraction is None else percent(figure_id, fraction)


def _ratio(figure_id: str, value: float | None) -> Figure | None:
    return None if value is None else plain(figure_id, value, "ratio", 2)


def performance_report(
    store: FinanceStore,
    config: Config,
    *,
    as_of: datetime,
    start: date | None = None,
    end: date | None = None,
    strict: bool = False,
) -> PerformanceReport:
    """TWR, MWR, risk-adjusted measures and contributions of the book over [start, end]."""
    found = pf.history(store, as_of=as_of, start=start, end=end, strict=strict)
    sessions = config.risk.market_risk.annualisation_sessions
    returns = found.returns
    span = (found.end - found.start).days
    yearly = span >= pf.DAYS_PER_YEAR
    unavailable: list[Unavailable] = []
    warnings = list(found.warnings)

    def missing(measure: str, reason: str) -> None:
        unavailable.append(Unavailable(measure=measure, reason=reason))

    twr = pf.chained(returns)
    period_mwr = pf.mwr(
        found.start,
        found.base_eur,
        list(zip(found.days[1:], found.flows, strict=True)),
        found.end,
        found.values[-1],
    )
    if period_mwr is None:
        missing("mwr", "aucun taux n'annule la valeur actuelle des flux : MWR indéfini")
    if not yearly:
        missing("rendements_annualises", SHORT)

    volatility = sharpe = sortino = risk_free = None
    if len(returns) < 2:
        missing("volatilite", "moins de deux rendements quotidiens")
    else:
        volatility = pf.volatility(returns, sessions)
        fixings = store.rates(
            config.risk.market_risk.risk_free, as_of=as_of, end=found.end, strict=strict
        )
        earned = pf.risk_free_returns(found.days, fixings)
        if earned is None:
            missing("sharpe_sortino", "aucun fixing €STR connu avant la période")
        else:
            risk_free = pf.chained(earned.returns)
            excess = [r - f for r, f in zip(returns, earned.returns, strict=True)]
            sharpe = pf.sharpe(excess, sessions)
            sortino = pf.sortino(excess, sessions)
            if sharpe is None:
                missing("sharpe", "rendements excédentaires constants : écart type nul")
            if sortino is None:
                missing("sortino", "aucun rendement excédentaire négatif : écart à la baisse nul")
            if earned.carried:
                warnings.append(
                    f"€STR pas encore publié pour {len(earned.carried)} jour(s) à partir du "
                    f"{earned.carried[0]:%d/%m/%Y} : dernier fixing connu reconduit [Hypothèse]"
                )
    drawdown = pf.max_drawdown(found.days, returns)
    annual_twr = pf.annualized(twr, span) if yearly else None
    calmar = None if annual_twr is None else pf.calmar(annual_twr, drawdown.depth)
    if yearly and calmar is None:
        missing("calmar", "aucune baisse depuis un sommet sur la période")

    benchmark = config.blockers("finance.benchmark")
    missing(
        "indice_de_reference",
        "; ".join(benchmark) + " (D8)" if benchmark else "comparaison à l'indice non calculée",
    )
    missing("attribution_factorielle", "modèle de facteurs non validé (D9)")
    missing("attribution_brinson", "reportée : aucun indice de référence validé (plan, F9)")

    attribution = _attribution(store, found, twr, as_of, strict, warnings)
    flows = [f for f in found.flows if f]
    return PerformanceReport(
        as_of=as_of,
        strict=strict,
        notice=NOTICE,
        period=Period(
            start=found.start,
            end=found.end,
            calendar_days=count("periode/jours", span, "jours"),
            returns=count("periode/rendements", len(returns), "séances"),
        ),
        values=Values(
            start_eur=_eur("valeurs/debut_eur", found.base_eur),
            end_eur=_eur("valeurs/fin_eur", found.values[-1]),
            net_deposits_eur=_eur("valeurs/apports_nets_eur", math.fsum(flows)),
            gain_eur=_eur(
                "valeurs/gain_eur",
                math.fsum([found.values[-1], -found.base_eur, *(-f for f in flows)]),
            ),
            dividends_eur=_eur(
                "valeurs/dividendes_eur",
                math.fsum(v for i in found.intervals for v in i.income.values()),
            ),
            fees_eur=_eur(
                "valeurs/frais_eur", math.fsum(i.pnl.get(pf.FEES, 0.0) for i in found.intervals)
            ),
        ),
        measures=Measures(
            twr=percent("mesures/twr", twr),
            twr_annualized=_pct("mesures/twr_annuel", annual_twr),
            mwr=_pct("mesures/mwr", period_mwr),
            mwr_annualized=_pct(
                "mesures/mwr_annuel",
                pf.annualized(period_mwr, span) if period_mwr is not None and yearly else None,
            ),
            volatility=_pct("mesures/volatilite", volatility),
            risk_free=_pct("mesures/estr", risk_free),
            sharpe=_ratio("mesures/sharpe", sharpe),
            sortino=_ratio("mesures/sortino", sortino),
            max_drawdown=DrawdownView(
                depth=percent("mesures/perte_max", drawdown.depth),
                peak=drawdown.peak,
                trough=drawdown.trough,
                recovery=drawdown.recovery,
            ),
            calmar=_ratio("mesures/calmar", calmar),
        ),
        attribution=attribution,
        assumptions=assumptions(sessions),
        unavailable=unavailable,
        warnings=warnings,
    )


def _attribution(
    store: FinanceStore,
    found: pf.History,
    twr: float,
    as_of: datetime,
    strict: bool,
    warnings: list[str],
) -> Attribution:
    contributions = pf.contributions(found)
    gains = pf.totals_by(found, lambda interval: interval.pnl)
    lines: list[LineContribution] = []
    by_sector: defaultdict[str, list[tuple[float, float]]] = defaultdict(list)
    for key, contribution in contributions.items():
        if key == pf.FEES:
            name, sector, currency = "frais de compte et de garde", pf.FEES, "EUR"
        elif key.startswith(f"{pf.CASH}-"):
            currency = key.removeprefix(f"{pf.CASH}-")
            name, sector = f"liquidités en {currency}", pf.CASH
        else:
            currency = found.currencies.get(key, "")
            card = store.instrument(key, as_of=as_of, strict=strict)
            if card is None:
                warnings.append(f"{key} : absent du référentiel, secteur « {UNCLASSIFIED} »")
                name, sector = key, UNCLASSIFIED
            else:
                name, sector = card.name, card.sector or UNCLASSIFIED
        base = f"attribution/lignes/{key}"
        lines.append(
            LineContribution(
                line=key,
                name=name,
                sector=sector,
                currency=currency,
                gain_eur=_eur(f"{base}/gain_eur", gains.get(key, 0.0)),
                contribution=percent(f"{base}/contribution", contribution),
            )
        )
        by_sector[sector].append((gains.get(key, 0.0), contribution))
    lines.sort(key=lambda line: (-line.contribution.value, line.line))
    sectors = sorted(
        (
            SectorContribution(
                sector=sector,
                gain_eur=_eur(
                    f"attribution/secteurs/{sector}/gain_eur", math.fsum(g for g, _ in parts)
                ),
                contribution=percent(
                    f"attribution/secteurs/{sector}/contribution", math.fsum(c for _, c in parts)
                ),
            )
            for sector, parts in by_sector.items()
        ),
        key=lambda s: (-s.contribution.value, s.sector),
    )
    total = math.fsum(contributions.values())
    return Attribution(
        lines=lines,
        sectors=sectors,
        total=percent("attribution/total", total),
        residual=percent("attribution/residu", twr - total),
    )


__all__ = ["NOTICE", "PerformanceReport", "performance_report"]
