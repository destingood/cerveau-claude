"""Rebalancing proposal of the book known at ``as_of`` (plan of phase 2, F4; ADR-019).

The optimizers of :mod:`core.finance.optimize` run on the securities held, from the market that
:mod:`core.finance.risk_report` assembles; cash is left as it is [Hypothèse]. Every number is a
:class:`Figure` (R1) and no number appears inside a text.

Nothing here executes anything. At N0 the proposal is an analysis, from N1 a proposal not
executed; in phase 4 it becomes order intentions submitted to the Risk Gate (§10.5). While the
trading costs are unknown (D13), it gives the target weights but no list of operations (R7).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from core.config.loader import Config, TradingCosts
from core.finance import risk
from core.finance.optimize import Constraints, Group, Method, optimize, turnover
from core.finance.risk import Matrix, Moments, Vector
from core.finance.risk_report import (
    SECTOR_PATTERN,
    Holdings,
    Line,
    Unavailable,
    holdings,
    market,
)
from core.finance.risk_report import _window as window_of
from core.finance.store import FinanceStore
from core.finance.views import QualityCheck, ViewError, quality_check
from core.verification.figures import Figure, amount, count, percent, plain, price, quantity

Status = Literal["analyse", "proposition non exécutée"]
Side = Literal["achat", "vente"]
NOTICE = "aide à la décision personnelle, pas un conseil en investissement (R16)"
MAX_SECTOR_CAPS = 10
NO_SECURITY = "aucune position en titres à cette date : rien à optimiser"
NO_COSTS = (
    "liste d'opérations indisponible : frais et glissement du courtier A_DEFINIR (D13) ; "
    "seuls les poids cibles sont donnés (R7)"
)
DESCRIPTIONS: dict[Method, str] = {
    "variance_minimale": "variance minimale (skfolio MeanRisk, MINIMIZE_RISK, VARIANCE)",
    "cvar_minimale": (
        "CVaR minimale sur les séances de la fenêtre (skfolio MeanRisk, MINIMIZE_RISK, CVAR)"
    ),
    "parite_de_risque": (
        "parité de risque : contributions égales à la variance (skfolio RiskBudgeting)"
    ),
    "hrp": (
        "parité de risque hiérarchique (skfolio HierarchicalRiskParity : distance de Pearson "
        "tirée de la covariance rétrécie, liaison de Ward)"
    ),
    "moyenne_variance": (
        "moyenne-variance : rendement moyen moins aversion fois variance, maximisé (skfolio "
        "MeanRisk, MAXIMIZE_UTILITY)"
    ),
}
ASSUMPTIONS = (
    "liquidités inchangées : seule la poche investie en titres est réallouée [Hypothèse]",
    "positions longues seulement, sans levier ni dérivés (risk_limits.paper : allow)",
    "covariance de Ledoit-Wolf sur la fenêtre, celle de l'optimiseur et des parts de risque "
    "[Estimation]",
    "le risque de la fenêtre passée représente le risque à venir [Hypothèse]",
    "risque avant et après : covariance de l'échantillon (ddof = 1), comme risk_report ; VaR "
    "paramétrique sur une séance",
    "rotation : somme des écarts de poids en valeur absolue sur la poche investie (convention "
    "skfolio, achats et ventes)",
)
MEAN_ASSUMPTION = "la moyenne historique des rendements n'est pas une prévision [Hypothèse]"
TRADE_ASSUMPTIONS = (
    "exécution au dernier cours connu, glissement compté en coût à l'achat comme à la vente "
    "[Hypothèse]",
    "quantités entières tronquées vers zéro : les poids atteints s'écartent un peu des poids "
    "cibles",
    "règlement en euros, devises converties au taux BCE du jour, frais de change compris",
)


class SectorCap(BaseModel):
    """A cap on the share of one sector (as written in the reference data) in the securities."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sector: Annotated[str, Field(min_length=1, max_length=40, pattern=SECTOR_PATTERN)]
    max_weight: Annotated[
        float, Field(gt=0.0, le=1.0, description="Part maximale de la poche investie, 0.3 = 30 %")
    ]


# Output -----------------------------------------------------------------------------------------


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OptimizationMethod(_Out):
    name: Method
    description: str
    covariance: str
    window: Figure
    first_session: date
    last_session: date
    cvar_confidence: Figure | None
    risk_aversion: Figure | None
    assumptions: list[str]


class SectorCapView(_Out):
    sector: str
    max_weight: Figure


class AppliedConstraints(_Out):
    long_only: bool
    leverage: bool
    max_weight: Figure | None
    sector_caps: list[SectorCapView]
    max_turnover: Figure | None


class ProposedLine(_Out):
    """Weights within the securities; risk shares of their volatility, shrunk covariance."""

    line: str
    name: str
    sector: str
    currency: str
    value_eur: Figure
    current_weight: Figure
    target_weight: Figure
    change: Figure
    target_value_eur: Figure
    risk_share_before: Figure
    risk_share_after: Figure


class SectorWeights(_Out):
    sector: str
    current_weight: Figure
    target_weight: Figure


class RiskSide(_Out):
    volatility: Figure  # annualized
    var_eur: dict[str, Figure]  # parametric, one session, by confidence level ("95")


class RiskComparison(_Out):
    before: RiskSide
    after: RiskSide


class Trade(_Out):
    line: str
    currency: str
    side: Side
    quantity: Figure
    price_eur: Figure
    amount_eur: Figure
    commission_eur: Figure
    slippage_eur: Figure
    fx_eur: Figure
    fees_eur: Figure


class TradeTotals(_Out):
    orders: Figure
    buys_eur: Figure
    sells_eur: Figure
    fees_eur: Figure
    cash_change_eur: Figure
    cash_after_eur: Figure


class RebalanceProposal(_Out):
    parity_label: Literal["[Approximation]"] = "[Approximation]"  # as plugin.yaml (ADR-019)
    as_of: AwareDatetime
    day: date
    strict: bool
    status: Status
    autonomy_level: str
    notice: str
    value_eur: Figure
    invested_eur: Figure
    cash_eur: Figure
    method: OptimizationMethod
    constraints: AppliedConstraints
    lines: list[ProposedLine]
    sectors: list[SectorWeights]
    turnover: Figure
    risk: RiskComparison
    trades: list[Trade] | None = None
    totals: TradeTotals | None = None
    data_quality: QualityCheck
    unavailable: list[Unavailable]
    warnings: list[str]


# Pieces -----------------------------------------------------------------------------------------


def _eur(figure_id: str, value: float) -> Figure:
    return amount(figure_id, float(value), "EUR")


def _pct(figure_id: str, fraction: float) -> Figure:
    return percent(figure_id, float(fraction))


def _level(confidence: float) -> str:
    return f"{confidence * 100:g}"


def _sector(line: Line) -> str:
    return line.instrument.sector if line.instrument else ""


def status_of(level: str) -> Status:
    return "analyse" if level == "N0" else "proposition non exécutée"


def _groups(
    securities: Sequence[Line], caps: Sequence[SectorCap]
) -> tuple[tuple[Group, ...], list[str]]:
    groups: list[Group] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for cap in caps:
        wanted = cap.sector.casefold()
        if wanted in seen:
            raise ViewError("plafonds sectoriels : un secteur figure deux fois")
        seen.add(wanted)
        members = tuple(
            i for i, line in enumerate(securities) if _sector(line).casefold() == wanted
        )
        if members:
            groups.append(Group(members, cap.max_weight))
        else:
            warnings.append(f"plafond sans effet : aucun titre du secteur {cap.sector}")
    return tuple(groups), warnings


def _risk_side(side: str, exposures: Vector, moments: Moments, config: Config) -> RiskSide:
    market_risk = config.risk.market_risk
    total = math.fsum(exposures.tolist())
    daily = moments.portfolio_sd(exposures / total)
    return RiskSide(
        volatility=_pct(
            f"risque/{side}/volatilite",
            risk.annualized(daily, market_risk.annualisation_sessions),
        ),
        var_eur={
            _level(c): _eur(
                f"risque/{side}/var/{_level(c)}", risk.parametric_var_eur(exposures, moments, c)
            )
            for c in market_risk.var.confidence_levels
        },
    )


def _shares(weights: Vector, covariance: Matrix) -> Vector:
    return risk.volatility_contributions(weights, covariance).shares


def _trades(
    securities: Sequence[Line],
    now: Holdings,
    targets: Vector,
    cash: float,
    costs: TradingCosts,
) -> tuple[list[Trade], TradeTotals, list[str]]:
    commission_pct = float(costs.commission_pct)  # type: ignore[arg-type]
    minimum = float(costs.min_commission_eur)  # type: ignore[arg-type]
    slippage_bps = float(costs.slippage_bps)  # type: ignore[arg-type]
    fx_bps = float(costs.fx_conversion_bps)  # type: ignore[arg-type]
    trades: list[Trade] = []
    buys: list[float] = []
    sells: list[float] = []
    all_fees: list[float] = []
    for line, target in zip(securities, targets, strict=True):
        held = now.quantities[line.key]
        unit = now.values[line.key] / float(held)
        units = math.trunc(round((target - now.values[line.key]) / unit, 6))
        if units == 0:
            continue
        traded = abs(units) * unit
        commission = max(traded * commission_pct / 100, minimum)
        slippage = traded * slippage_bps / 10_000
        fx = traded * fx_bps / 10_000 if line.currency != "EUR" else 0.0
        fees = math.fsum((commission, slippage, fx))
        (buys if units > 0 else sells).append(traded)
        all_fees.append(fees)
        base = f"operations/{line.key}"
        trades.append(
            Trade(
                line=line.key,
                currency=line.currency,
                side="achat" if units > 0 else "vente",
                quantity=quantity(f"{base}/quantite", Decimal(abs(units))),
                price_eur=price(f"{base}/cours_eur", unit, "EUR"),
                amount_eur=_eur(f"{base}/montant_eur", traded),
                commission_eur=_eur(f"{base}/commission_eur", commission),
                slippage_eur=_eur(f"{base}/glissement_eur", slippage),
                fx_eur=_eur(f"{base}/change_eur", fx),
                fees_eur=_eur(f"{base}/frais_eur", fees),
            )
        )
    change = math.fsum(sells) - math.fsum(buys) - math.fsum(all_fees)
    totals = TradeTotals(
        orders=count("operations/ordres", len(trades), "ordres"),
        buys_eur=_eur("operations/achats_eur", math.fsum(buys)),
        sells_eur=_eur("operations/ventes_eur", math.fsum(sells)),
        fees_eur=_eur("operations/frais_eur", math.fsum(all_fees)),
        cash_change_eur=_eur("operations/variation_liquidites_eur", change),
        cash_after_eur=_eur("operations/liquidites_apres_eur", cash + change),
    )
    warnings = []
    if cash + change < 0:
        warnings.append(
            "liquidités insuffisantes après les opérations : proposition non finançable telle "
            "quelle"
        )
    return trades, totals, warnings


# Proposal -------------------------------------------------------------------------------------


def rebalance_proposal(
    store: FinanceStore,
    config: Config,
    *,
    as_of: datetime,
    method: Method,
    max_weight: float | None = None,
    sector_caps: Sequence[SectorCap] = (),
    max_turnover: float | None = None,
    strict: bool = False,
) -> RebalanceProposal:
    """Target weights of the securities held at ``as_of`` under ``method``, the risk before and
    after, and, once the trading costs are known, the operations in whole units."""
    if len(sector_caps) > MAX_SECTOR_CAPS:
        raise ViewError(f"au plus {MAX_SECTOR_CAPS} plafonds sectoriels")
    if max_turnover is not None and not 0 <= max_turnover <= 2:
        raise ViewError("rotation maximale entre 0 et 2 (200 %)")
    if max_weight is not None and not 0 < max_weight <= 1:
        raise ViewError("poids maximal entre 0 exclu et 1")
    try:
        return _proposal(
            store, config, as_of, method, max_weight, sector_caps, max_turnover, strict
        )
    except risk.RiskError as exc:
        raise ViewError(str(exc)) from None


def _proposal(
    store: FinanceStore,
    config: Config,
    as_of: datetime,
    method: Method,
    max_weight: float | None,
    sector_caps: Sequence[SectorCap],
    max_turnover: float | None,
    strict: bool,
) -> RebalanceProposal:
    market_risk = config.risk.market_risk
    now = holdings(store, as_of=as_of, strict=strict)
    securities = [line for line in now.lines if not line.is_cash]
    if not securities:
        raise ViewError(NO_SECURITY)
    exposures = now.exposures(now.lines)
    total = math.fsum(exposures.tolist())
    k = len(securities)  # securities come first in now.lines
    invested = math.fsum(exposures[:k].tolist())
    if invested <= 0 or total <= 0:
        raise ViewError("valeur investie nulle ou négative : rien à optimiser")
    found = market(store, now.lines, as_of=as_of, day=now.day, strict=strict)
    window = window_of(found, market_risk.var.window_sessions, "as_of")
    groups, warnings = _groups(securities, sector_caps)
    constraints = Constraints(
        max_weight=1.0 if max_weight is None else max_weight,
        groups=groups,
        max_turnover=max_turnover,
    )
    previous = exposures[:k] / invested
    cvar_beta = market_risk.var.confidence_levels[0]
    aversion = config.risk.optimization.risk_aversion
    known_aversion = None if isinstance(aversion, str) else float(aversion)
    solution = optimize(
        method,
        window[:, :k],
        previous,
        constraints,
        cvar_beta=cvar_beta,
        risk_aversion=known_aversion,
    )
    targets = solution.weights * invested
    after = exposures.copy()
    after[:k] = targets
    moments = risk.moments(window)
    before_shares = _shares(previous, solution.covariance)
    after_shares = _shares(solution.weights, solution.covariance)
    lines = []
    for i, line in enumerate(securities):
        card = line.instrument
        base = f"lignes/{line.key}"
        lines.append(
            ProposedLine(
                line=line.key,
                name=card.name if card else line.key,
                sector=_sector(line),
                currency=line.currency,
                value_eur=_eur(f"{base}/valeur_eur", exposures[i]),
                current_weight=_pct(f"{base}/poids_actuel", previous[i]),
                target_weight=_pct(f"{base}/poids_cible", solution.weights[i]),
                change=_pct(f"{base}/ecart", solution.weights[i] - previous[i]),
                target_value_eur=_eur(f"{base}/valeur_cible_eur", targets[i]),
                risk_share_before=_pct(f"{base}/part_risque_avant", before_shares[i]),
                risk_share_after=_pct(f"{base}/part_risque_apres", after_shares[i]),
            )
        )
    by_sector: defaultdict[str, list[int]] = defaultdict(list)
    for i, line in enumerate(securities):
        by_sector[_sector(line)].append(i)
    sectors = [
        SectorWeights(
            sector=name,
            current_weight=_pct(f"secteurs/{name}/poids_actuel", previous[members].sum()),
            target_weight=_pct(f"secteurs/{name}/poids_cible", solution.weights[members].sum()),
        )
        for name, members in sorted(by_sector.items())
    ]
    sessions = found.prices.index[-(len(window) + 1) :]
    assumptions = list(ASSUMPTIONS)
    if method == "moyenne_variance":
        assumptions.append(MEAN_ASSUMPTION)
    unavailable: list[Unavailable] = []
    parts: dict[str, object] = {}
    cash = total - invested
    if config.blockers("finance.trading_costs"):
        unavailable.append(Unavailable(measure="operations", reason=NO_COSTS))
    else:
        parts["trades"], parts["totals"], extra = _trades(
            securities, now, targets, cash, config.risk.trading_costs
        )
        warnings += extra
        assumptions += TRADE_ASSUMPTIONS
    level = config.autonomy.domains["finance"].level
    quality = quality_check(
        store,
        [line.key for line in securities],
        as_of=as_of,
        strict=strict,
        threshold=config.data_sources.quality.min_quality_score_above_N1,
    )
    if quality.note:
        warnings.append(quality.note)
    return RebalanceProposal(
        as_of=as_of,
        day=now.day,
        strict=strict,
        status=status_of(level),
        autonomy_level=level,
        notice=NOTICE,
        value_eur=_eur("valeur_eur", total),
        invested_eur=_eur("investi_eur", invested),
        cash_eur=_eur("liquidites_eur", cash),
        method=OptimizationMethod(
            name=method,
            description=DESCRIPTIONS[method],
            covariance="Ledoit-Wolf (skfolio LedoitWolf), estimée sur la fenêtre",
            window=count("methode/fenetre", len(window), "séances"),
            first_session=sessions[0].date(),
            last_session=sessions[-1].date(),
            cvar_confidence=(
                _pct("methode/confiance_cvar", cvar_beta) if method == "cvar_minimale" else None
            ),
            risk_aversion=(
                plain("methode/aversion", known_aversion, "coefficient", 2)
                if method == "moyenne_variance" and known_aversion is not None
                else None
            ),
            assumptions=assumptions,
        ),
        constraints=AppliedConstraints(
            long_only=True,
            leverage=False,
            max_weight=None if max_weight is None else _pct("contraintes/poids_max", max_weight),
            sector_caps=[
                SectorCapView(
                    sector=cap.sector,
                    max_weight=_pct(f"contraintes/secteur/{n}", cap.max_weight),
                )
                for n, cap in enumerate(sector_caps)
            ],
            max_turnover=(
                None if max_turnover is None else _pct("contraintes/rotation_max", max_turnover)
            ),
        ),
        lines=lines,
        sectors=sectors,
        turnover=_pct("rotation", turnover(solution.weights, previous)),
        risk=RiskComparison(
            before=_risk_side("avant", exposures, moments, config),
            after=_risk_side("apres", after, moments, config),
        ),
        data_quality=quality,
        unavailable=unavailable,
        warnings=list(now.warnings) + warnings,
        **parts,  # type: ignore[arg-type]
    )


__all__ = [
    "MAX_SECTOR_CAPS",
    "NOTICE",
    "RebalanceProposal",
    "SectorCap",
    "rebalance_proposal",
    "status_of",
]
