"""Configuration loader (annex B) with blocking markers (R7).

A value ``A_DEFINIR`` (Lucas must decide) or ``A_VERIFIER`` (must be checked
against an official source) is never guessed: every feature that depends on it
is blocked. ``Config.require(feature)`` raises ``BlockedFeatureError`` and
``cerveau config check`` lists what is blocked and why.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

MARKERS = ("A_DEFINIR", "A_VERIFIER")
Marker = Literal["A_DEFINIR", "A_VERIFIER"]
Level = Literal["N0", "N1", "N2", "N3", "N4"]
# A judge score or a pass rate: a real number in [0, 1], never a boolean, an infinity or NaN.
Score = Annotated[float, Field(ge=0, le=1, strict=True, allow_inf_nan=False)]
LEVELS: tuple[str, ...] = ("N0", "N1", "N2", "N3", "N4")
ActionClass = Literal[
    "LECTURE", "CALCUL", "ECRITURE_INTERNE", "COMMUNICATION_EXTERNE", "IRREVERSIBLE", "FINANCIERE"
]
ACTION_CLASSES: tuple[str, ...] = (
    "LECTURE",
    "CALCUL",
    "ECRITURE_INTERNE",
    "COMMUNICATION_EXTERNE",
    "IRREVERSIBLE",
    "FINANCIERE",
)
MatrixDecision = Literal[
    "auto",
    "refus",
    "brouillon",
    "simule",
    "approbation",
    "proposition",
    "paper",
    "auto_dans_limites",
]

COMMENT_MARKER_RE = re.compile(r"#.*\b(A_DEFINIR|A_VERIFIER)\b")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- models.yaml -----------------------------------------------------------------------------


class ModelTier(_Strict):
    provider: Literal["anthropic", "ollama"]
    model: str
    status: Literal["A_VERIFIER", "verifie"] | None = None
    verified_on: date | None = None
    source: str | None = None

    @model_validator(mode="after")
    def _verified_needs_date_and_source(self) -> ModelTier:
        if self.status == "verifie" and (self.verified_on is None or not self.source):
            raise ValueError("status 'verifie' requires verified_on and source")
        return self


TierName = Literal["deep", "standard", "fast", "local"]


class Judge(_Strict):
    tier: TierName
    prefer_different_from_evaluated: bool


class Routing(_Strict):
    max_tools_to_planner: int = Field(gt=0, le=50)


class ModelsConfig(_Strict):
    tiers: dict[TierName, ModelTier]
    judge: Judge
    routing: Routing


# --- autonomy.yaml ---------------------------------------------------------------------------


class DomainAutonomy(_Strict):
    level: Level
    max_level: Level

    @model_validator(mode="after")
    def _level_within_max(self) -> DomainAutonomy:
        if LEVELS.index(self.level) > LEVELS.index(self.max_level):
            raise ValueError(f"level {self.level} dépasse max_level {self.max_level}")
        return self


class PromotionN0N1(_Strict):
    """D16: both measures come from a real campaign, never from the offline replay."""

    golden_min_score: Score | Marker
    r1_to_r5_violations_max: Annotated[int, Field(strict=True, ge=0, le=0)]
    measured_in: Literal["live"]
    manual_signature: Literal["required"]


class PromotionN2N3(_Strict):
    paper_weeks_min: int | Marker
    decisions_min: int | Marker
    max_paper_drawdown_pct: float | Marker
    execution_incidents_max: int
    manual_signature: Literal["required"]


class PromotionN3N4(_Strict):
    approvals_min: int | Marker
    agreement_rate_min: float | Marker
    manual_signature: Literal["required"]


class FinancePromotion(_Strict):
    N0_to_N1: PromotionN0N1
    N2_to_N3: PromotionN2N3
    N3_to_N4: PromotionN3N4


class Promotion(_Strict):
    finance: FinancePromotion


class Approval(_Strict):
    channel: Literal["discord"]
    one_time_code: bool
    expiry_minutes: int | Marker


class AutonomyConfig(_Strict):
    domains: dict[str, DomainAutonomy]
    matrix: dict[ActionClass, dict[Level, MatrixDecision]]
    promotion: Promotion
    demotion_triggers: list[str]
    approval: Approval

    @model_validator(mode="after")
    def _matrix_complete(self) -> AutonomyConfig:
        missing = [
            f"{cls}/{lvl}"
            for cls in ACTION_CLASSES
            for lvl in LEVELS
            if lvl not in self.matrix.get(cls, {})  # type: ignore[call-overload]
        ]
        if missing:
            raise ValueError(f"matrice d'autonomie incomplète : {missing}")
        return self


# --- risk_limits.paper.yaml / live.yaml ------------------------------------------------------


class Allow(_Strict):
    leverage: bool
    short_selling: bool
    derivatives: bool


# A percentage (5 means 5 %, D4): never 0 or less, never above the whole, never NaN.
Pct = Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)]
Count = Annotated[int, Field(gt=0)]
# An instrument of the finance store (core.finance.model.InstrumentId).
Instrument = Annotated[str, Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{0,31}$")]


class PaperRiskLimits(_Strict):
    """Limits of the Risk Gate in paper trading (section 8.4, ADR-031).

    Every ``*_pct`` is a percentage (5 means 5 %, D4). The order, position, sector, country and
    currency limits, the daily loss and the rolling loss are percentages of the reference
    capital; the drawdown is a percentage of the highest equity reached; the collar is a
    percentage of the last known price. The currency limit caps the exposure to each currency
    other than the euro, the country limit the exposure to each country. The rolling loss and
    the average volume are measured over ``rolling_loss_sessions`` and ``avg_volume_sessions``
    sessions; the volume is a number of shares. The gate accepts only the universe's instruments.
    """

    capital_reference_eur: Annotated[float, Field(gt=0, allow_inf_nan=False)] | Marker
    max_order_pct: Pct | Marker
    max_position_pct: Pct | Marker
    max_sector_pct: Pct | Marker
    max_country_pct: Pct | Marker
    max_currency_pct: Pct | Marker
    max_daily_loss_pct: Pct | Marker
    max_rolling_loss_pct: Pct | Marker
    rolling_loss_sessions: Count | Marker
    max_drawdown_pct: Pct | Marker
    max_orders_per_hour: Count | Marker
    max_orders_per_day: Count | Marker
    limit_price_collar_pct: Pct | Marker
    min_avg_daily_volume: Annotated[float, Field(gt=0, allow_inf_nan=False)] | Marker
    avg_volume_sessions: Count | Marker
    universe: Annotated[list[Instrument], Field(min_length=1)] | Marker
    allow: Allow

    @field_validator("universe")
    @classmethod
    def _unique_tickers(cls, value: list[str] | str) -> list[str] | str:
        if isinstance(value, list) and len(set(value)) != len(value):
            raise ValueError("un instrument figure deux fois dans l'univers")
        return value


class ExecutionConfig(_Strict):
    """How a paper order is drafted and filled (ADR-029, ADR-033).

    The limit price is the last known price moved by ``limit_offset_pct`` towards a fill (up for
    a buy, down for a sell), within the collar (D17). A session fills at most
    ``max_participation_pct`` of its volume (D2, a simulation hypothesis).
    """

    limit_offset_pct: Pct | Marker
    max_participation_pct: Pct | Marker


class LiveLimits(_Strict):
    max_order_pct: float = Field(ge=0)
    max_position_pct: float = Field(ge=0)
    max_daily_loss_pct: float = Field(ge=0)
    max_orders_per_day: int = Field(ge=0)


class LiveConfig(_Strict):
    enabled: bool
    broker: str
    limits: LiveLimits
    allow: Allow
    instruments_whitelist: list[str]


# --- budgets / compliance / data sources / evals / risk --------------------------------------


class LlmBudget(_Strict):
    # Money is a decision figure (R1): exact decimals, never floats.
    daily: Annotated[Decimal, Field(gt=0)] | Marker
    monthly: Annotated[Decimal, Field(gt=0)] | Marker


class PerRequest(_Strict):
    max_tool_calls: int = Field(gt=0)
    max_tokens: int | Marker
    max_seconds: int = Field(gt=0)


class PerCommittee(_Strict):
    # ADR-028, D18: one committee session exceeds a request; no real session until Lucas decides.
    max_tokens: Annotated[int, Field(gt=0)] | Marker
    max_seconds: Annotated[int, Field(gt=0)] | Marker
    max_tool_calls: Annotated[int, Field(gt=0)] | Marker


class BudgetsConfig(_Strict):
    llm_budget_eur: LlmBudget
    alerts_pct: list[Annotated[int, Field(gt=0, le=100)]] = Field(min_length=1)
    per_request: PerRequest
    per_committee: PerCommittee
    on_exceeded: list[
        Literal["refuse_new_requests", "downgrade_to_fast_or_local", "stop_non_critical_tasks"]
    ] = Field(min_length=1)

    @model_validator(mode="after")
    def _alerts_sorted_up_to_100(self) -> BudgetsConfig:
        if self.alerts_pct != sorted(set(self.alerts_pct)) or self.alerts_pct[-1] != 100:
            raise ValueError("alerts_pct must be strictly increasing and end at 100")
        return self


class Fiscal(_Strict):
    regime_plus_values: str
    comptes_etrangers_declaration: str


class Crypto(_Strict):
    plateforme_autorisee_france: str


class ComplianceConfig(_Strict):
    fiscal: Fiscal
    crypto: Crypto
    exclusions_personnelles: list[str]


class DataSource(_Strict):
    enabled: bool
    url: str | None = None
    categories: list[str] | None = None
    terms: str | None = None
    usage: str | None = None


class DataQuality(_Strict):
    # Closing prices (ADR-012): staleness is counted in exchange sessions, not minutes.
    max_staleness_sessions: Annotated[int, Field(ge=0)] | Marker
    min_quality_score_above_N1: Annotated[float, Field(ge=0, le=1)] | Marker
    # Cut-offs of the outlier and corporate action checks (ADR-016).
    outlier_robust_z: Annotated[float, Field(gt=0, allow_inf_nan=False)] | Marker
    # Below 0.5, so that the smallest usual split (3 for 2) always shows as a move.
    max_unexplained_move: Annotated[float, Field(gt=0, lt=0.5)] | Marker


class DataSourcesConfig(_Strict):
    sources: dict[str, DataSource]
    quality: DataQuality


# The golden thresholds Lucas set (D6, D17). The configuration may raise them, never lower them
# (R9): only an ADR moves these floors.
GOLDEN_FLOORS: dict[str, float] = {
    "generaliste_golden_min_score": 0.80,
    "finance_golden_min_score": 0.85,
}


class EvalThresholds(_Strict):
    generaliste_golden_min_score: Score | Marker
    finance_golden_min_score: Score | Marker
    behavior_suites_R1_to_R5_pass_rate: Score
    regression_block_delta: float | Marker

    @model_validator(mode="after")
    def _golden_floors(self) -> EvalThresholds:
        for name, floor in GOLDEN_FLOORS.items():
            value = getattr(self, name)
            if not isinstance(value, str) and value < floor:
                raise ValueError(
                    f"{name} : {value} est sous le plancher {floor} "
                    "(D6, D17 ; seule une ADR le change)"
                )
        return self


class EvalsConfig(_Strict):
    thresholds: EvalThresholds
    judge_human_review_sample_weekly: int = Field(ge=0)


Seconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class KillSwitch(_Strict):
    # ADR-034: from the trigger to the state written, every open order cancelled.
    target_seconds: Seconds | Marker
    data_loss_timeout_seconds: Seconds | Marker


class PluginHealth(_Strict):
    slo_breach_days_before_disable: int | Marker


class Keys(_Strict):
    rotation_days: int | Marker


class Infra(_Strict):
    private_network: str


Probability = Annotated[float, Field(gt=0, lt=1)]
Sessions = Annotated[int, Field(gt=0)]


class VarParameters(_Strict):
    confidence_levels: list[Probability] = Field(min_length=1)
    horizons_sessions: list[Sessions] = Field(min_length=1)
    window_sessions: Annotated[int, Field(gt=1)]
    monte_carlo_draws: Annotated[int, Field(gt=0)]
    seed: Annotated[int, Field(ge=0)]


class Backtest(_Strict):
    window_sessions: Sessions
    significance: Probability


class HypotheticalStress(_Strict):
    rates_bp: float
    equity_shock: Annotated[float, Field(gt=-1)]
    fx_eurusd_shocks: list[Annotated[float, Field(gt=-1)]] = Field(min_length=1)


class CrisisWindow(_Strict):
    label: str
    start: date | Marker
    end: date | Marker
    source: str | Marker


class Benchmark(_Strict):
    description: str
    isin: str | Marker


class CrossCheck(_Strict):
    # ADR-014: tolerances of the "independent calculation" phase criterion (never loosened, R9).
    rel_tolerance: Annotated[float, Field(gt=0)]
    monte_carlo_rel_tolerance: Annotated[float, Field(gt=0)]
    monte_carlo_draws: Annotated[int, Field(gt=0)]


class MarketRisk(_Strict):
    var: VarParameters
    backtest: Backtest
    annualisation_sessions: Sessions
    risk_free: Literal["estr"]
    benchmark: Benchmark
    hypothetical_stress: HypotheticalStress
    historical_stress: dict[str, CrisisWindow]
    cross_check: CrossCheck


Money = Annotated[Decimal, Field(ge=0)] | Marker


class TradingCosts(_Strict):
    # R10: fees and slippage are always included; unknown until Lucas gives his broker's (D13).
    commission_pct: Money  # percent of the amount traded: 0.1 for 0.1 %
    min_commission_eur: Money  # per order
    slippage_bps: Money
    fx_conversion_bps: Money  # on the amount of an order in a foreign currency


class Optimization(_Strict):
    # ADR-019: the covariance of every optimizer; mean-variance waits for Lucas's risk aversion.
    covariance: Literal["ledoit_wolf"]
    risk_aversion: Annotated[float, Field(gt=0)] | Marker


class RiskConfig(_Strict):
    kill_switch: KillSwitch
    plugin_health: PluginHealth
    keys: Keys
    infra: Infra
    market_risk: MarketRisk
    trading_costs: TradingCosts
    optimization: Optimization


# --- pricing.yaml (ADR-005) -------------------------------------------------------------------

Price = Annotated[Decimal, Field(ge=0)] | Marker


class PriceTier(_Strict):
    """USD per million tokens; applies while the prompt is at most ``max_prompt_tokens``."""

    max_prompt_tokens: int | None = Field(default=None, gt=0)
    input: Price
    cache_write_5m: Price
    cache_write_1h: Price
    cache_read: Price
    output: Price


class ModelPricing(_Strict):
    tiers: list[PriceTier] = Field(min_length=1)

    @model_validator(mode="after")
    def _tiers_ascending_and_unbounded_last(self) -> ModelPricing:
        bounds = [tier.max_prompt_tokens for tier in self.tiers]
        if bounds[-1] is not None or None in bounds[:-1]:
            raise ValueError("only the last price tier is unbounded (no max_prompt_tokens)")
        finite = [b for b in bounds if b is not None]
        if finite != sorted(set(finite)):
            raise ValueError("max_prompt_tokens must be strictly increasing")
        return self


class AnthropicPricing(_Strict):
    source: str
    verified_on: date
    models: dict[str, ModelPricing]


class SearchPrice(_Strict):
    usd_per_1000_requests: Price
    source: str
    verified_on: date


class Fx(_Strict):
    usd_per_eur: Annotated[Decimal, Field(gt=0)] | Marker
    rate_date: date
    source: str
    read_on: date


class PricingConfig(_Strict):
    anthropic: AnthropicPricing
    search: dict[str, SearchPrice]
    fx: Fx


# --- guardrails.yaml (ADR-010) ----------------------------------------------------------------


class PiiConfig(_Strict):
    language: Literal["fr"]
    spacy_model: str
    score_threshold: Annotated[float, Field(ge=0, le=1)] | Marker
    entities: dict[str, Annotated[str, Field(pattern=r"^[A-Z][A-Z_]*$")]] = Field(min_length=1)


class GuardrailsConfig(_Strict):
    pii: PiiConfig


# --- research.yaml (ADR-024, ADR-026, ADR-027) -----------------------------------------------


class Execution(_Strict):
    # A naive time, read as UTC. The execution lag (close of t+1) is fixed by the engine, not here.
    decision_cutoff_utc: time

    @field_validator("decision_cutoff_utc", mode="before")
    @classmethod
    def _quoted(cls, value: object) -> object:
        # Unquoted, YAML 1.1 reads 21:00 as the base-60 integer 1260, which pydantic would take
        # for a number of seconds (00:21).
        if not isinstance(value, str):
            raise ValueError('decision_cutoff_utc s\'écrit entre guillemets, par exemple "21:00"')
        return value

    @model_validator(mode="after")
    def _naive(self) -> Execution:
        if self.decision_cutoff_utc.tzinfo is not None:
            raise ValueError("decision_cutoff_utc est une heure UTC sans fuseau")
        return self


class Split(_Strict):
    development_fraction: Annotated[float, Field(gt=0, lt=1, allow_inf_nan=False)]
    embargo_sessions: Annotated[int, Field(ge=0)]


class WalkForward(_Strict):
    scheme: Literal["anchored"]
    blocks: Annotated[int, Field(ge=2)]


class Pbo(_Strict):
    partitions: Annotated[int, Field(ge=4)]

    @model_validator(mode="after")
    def _even(self) -> Pbo:
        if self.partitions % 2:
            raise ValueError("CSCV : partitions doit être pair")
        return self


class ResearchGates(_Strict):
    dsr_min: Score
    pbo_max: Score
    final_to_walk_forward_sharpe_min: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    benchmark_min_sessions: Sessions
    cost_stress_multiplier: Annotated[float, Field(gt=1, allow_inf_nan=False)]


class ResearchCrossCheck(_Strict):
    nautilus_rel_tolerance: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    vectorbt_rel_tolerance: Annotated[float, Field(gt=0, allow_inf_nan=False)]


class Copilot(_Strict):
    # A bound on compute time for a backtest the Copilot asks for, not a risk limit.
    max_window_sessions: Sessions


# The D9 gates, the D7 embargo and the D12 tolerances Lucas validated for phase 3, fixed before
# the first measure. The configuration may make them stricter, never looser (R9): only an ADR
# moves these bounds.
RESEARCH_BOUNDS: dict[str, tuple[Literal["min", "max"], float]] = {
    "gates.dsr_min": ("min", 0.95),
    "gates.pbo_max": ("max", 0.5),
    "gates.final_to_walk_forward_sharpe_min": ("min", 0.5),
    "gates.benchmark_min_sessions": ("min", 252),
    "gates.cost_stress_multiplier": ("min", 2),
    "split.embargo_sessions": ("min", 5),
    "cross_check.nautilus_rel_tolerance": ("max", 1e-6),
    "cross_check.vectorbt_rel_tolerance": ("max", 1e-9),
}


class ResearchConfig(_Strict):
    execution: Execution
    split: Split
    walk_forward: WalkForward
    pbo: Pbo
    gates: ResearchGates
    cross_check: ResearchCrossCheck
    copilot: Copilot

    @model_validator(mode="after")
    def _never_looser(self) -> ResearchConfig:
        errors: list[str] = []
        for dotted, (kind, bound) in RESEARCH_BOUNDS.items():
            section, name = dotted.split(".")
            value = getattr(getattr(self, section), name)
            if kind == "min" and value < bound:
                errors.append(f"{dotted} : {value} est sous le plancher {bound}")
            if kind == "max" and value > bound:
                errors.append(f"{dotted} : {value} dépasse le plafond {bound}")
        if errors:
            raise ValueError("; ".join(errors) + " (D7, D9, D12 ; seule une ADR les change)")
        return self


# --- committee.yaml (ADR-028) -----------------------------------------------------------------


class CommitteePack(_Strict):
    # Model tier of each active role; an inactive role (no data source) has none.
    tiers: dict[Annotated[str, Field(pattern=r"^[a-z][a-z_]*$")], TierName] = Field(min_length=1)


class CommitteeConfig(_Strict):
    max_debate_rounds: Annotated[int, Field(ge=1)]
    finance: CommitteePack


FILES: dict[str, tuple[str, type[BaseModel]]] = {
    "models": ("models.yaml", ModelsConfig),
    "autonomy": ("autonomy.yaml", AutonomyConfig),
    "risk_limits.paper": ("risk_limits.paper.yaml", PaperRiskLimits),
    "execution": ("execution.yaml", ExecutionConfig),
    "live": ("live.yaml", LiveConfig),
    "budgets": ("budgets.yaml", BudgetsConfig),
    "compliance": ("compliance.yaml", ComplianceConfig),
    "data_sources": ("data_sources.yaml", DataSourcesConfig),
    "evals": ("evals.yaml", EvalsConfig),
    "risk": ("risk.yaml", RiskConfig),
    "pricing": ("pricing.yaml", PricingConfig),
    "guardrails": ("guardrails.yaml", GuardrailsConfig),
    "research": ("research.yaml", ResearchConfig),
    "committee": ("committee.yaml", CommitteeConfig),
}


@dataclass(frozen=True)
class Feature:
    description: str
    requires: tuple[str, ...]  # "<file>:<dotted prefix>", "" prefix = whole file
    source: str | None = None  # data source that must also be enabled


# Which configuration values each feature depends on. A marker under any listed prefix
# blocks the feature. Kept explicit so that `cerveau config check` explains every block.
FEATURES: dict[str, Feature] = {
    "llm.deep": Feature("Modèle deep (planification, Comité, juge)", ("models:tiers.deep",)),
    "llm.standard": Feature("Modèle standard (boucle d'action)", ("models:tiers.standard",)),
    "llm.fast": Feature("Modèle fast (routage, extraction)", ("models:tiers.fast",)),
    "llm.local": Feature("Modèle local Ollama", ("models:tiers.local",)),
    "budgets": Feature(
        "Plafonds de dépense LLM", ("budgets:llm_budget_eur", "budgets:per_request")
    ),
    "approvals": Feature("Approbations N3 (Discord, code à usage unique)", ("autonomy:approval",)),
    "promotion.finance.N0_to_N1": Feature(
        "Promotion finance N0 → N1",
        ("autonomy:promotion.finance.N0_to_N1", "evals:thresholds.finance_golden_min_score"),
    ),
    "promotion.finance.N2_to_N3": Feature(
        "Promotion finance N2 → N3", ("autonomy:promotion.finance.N2_to_N3",)
    ),
    "promotion.finance.N3_to_N4": Feature(
        "Promotion finance N3 → N4", ("autonomy:promotion.finance.N3_to_N4",)
    ),
    # The gate checks the cash with the fees (R10) and every order sits under the kill switch.
    "paper_trading": Feature(
        "Porte de risque et exécution en paper trading",
        (
            "risk_limits.paper:",
            "execution:",
            "risk:trading_costs",
            "risk:kill_switch.target_seconds",
        ),
    ),
    "live_trading": Feature("Exécution live (R3 : activée à la main par Lucas)", ("live:",)),
    "kill_switch": Feature("Kill switch (cible de temps)", ("risk:kill_switch.target_seconds",)),
    "kill_switch.data_loss": Feature(
        "Kill switch sur perte d'une connexion continue aux données",
        ("risk:kill_switch.data_loss_timeout_seconds",),
    ),
    "plugin_health": Feature("Désactivation auto d'un plugin hors SLO", ("risk:plugin_health",)),
    "keys.rotation": Feature("Rotation des clés", ("risk:keys",)),
    "infra.vps": Feature("Déploiement VPS (réseau privé)", ("risk:infra",)),
    "data.openbb": Feature("Source OpenBB", ("data_sources:sources.openbb",), "openbb"),
    "data.yfinance": Feature("Source yfinance", ("data_sources:sources.yfinance",), "yfinance"),
    "data.fred": Feature("Source FRED", ("data_sources:sources.fred",), "fred"),
    "data.ecb": Feature("Source BCE", ("data_sources:sources.ecb",), "ecb"),
    "data.quality_gate": Feature(
        "Contrôle qualité des données au-delà de N1", ("data_sources:quality",)
    ),
    "evals.gate.generaliste": Feature(
        "Seuil du golden set Généraliste",
        (
            "evals:thresholds.generaliste_golden_min_score",
            "evals:thresholds.regression_block_delta",
        ),
    ),
    "evals.gate.finance": Feature(
        "Seuil du golden set Finance",
        ("evals:thresholds.finance_golden_min_score", "evals:thresholds.regression_block_delta"),
    ),
    "finance.market_risk": Feature(
        "Mesures de risque de marché (VaR, CVaR, Kupiec, stress hypothétiques)",
        (
            "risk:market_risk.var",
            "risk:market_risk.backtest",
            "risk:market_risk.annualisation_sessions",
            "risk:market_risk.risk_free",
            "risk:market_risk.hypothetical_stress",
            "risk:market_risk.cross_check",
        ),
    ),
    "finance.performance": Feature(
        "Mesures de performance (annualisation, taux sans risque)",
        ("risk:market_risk.annualisation_sessions", "risk:market_risk.risk_free"),
    ),
    "finance.historical_stress": Feature(
        "Stress historiques (fenêtres de crise)", ("risk:market_risk.historical_stress",)
    ),
    "finance.benchmark": Feature("Indice de référence (bêta)", ("risk:market_risk.benchmark",)),
    "finance.trading_costs": Feature(
        "Frais et glissement (liste d'opérations d'une proposition)", ("risk:trading_costs",)
    ),
    "finance.mean_variance": Feature(
        "Optimisation moyenne-variance (aversion au risque)", ("risk:optimization.risk_aversion",)
    ),
    "compliance.fiscal": Feature("Règles fiscales", ("compliance:fiscal",)),
    "compliance.crypto": Feature("Plateformes crypto autorisées", ("compliance:crypto",)),
    "costs": Feature("Calcul déterministe des coûts (prix, taux de change)", ("pricing:",)),
    "guardrails.pii": Feature("Pseudonymisation Presidio (seuil, entités)", ("guardrails:pii",)),
    "finance.research": Feature(
        "Backtest et protocole sur données réelles (frais et glissement, R10)",
        (
            "research:",
            "risk:trading_costs",
            "risk:market_risk.annualisation_sessions",
            "risk:market_risk.risk_free",
        ),
    ),
    # Config.blockers adds the model tiers that committee.yaml assigns to the roles.
    "finance.committee": Feature(
        "Comité d'investissement (budget d'une séance)",
        ("committee:", "budgets:llm_budget_eur", "budgets:per_committee"),
    ),
}


@dataclass(frozen=True)
class MarkerHit:
    file: str  # config key, e.g. "risk_limits.paper"
    path: str  # dotted path inside the file, or "ligne N" for a comment marker
    marker: str
    in_comment: bool = False

    def __str__(self) -> str:
        where = f"{FILES[self.file][0]} › {self.path}"
        return f"{where} = {self.marker}" + (" (commentaire)" if self.in_comment else "")


class ConfigError(Exception):
    """Structural error in a configuration file: nothing should run on it."""


class BlockedFeatureError(Exception):
    def __init__(self, feature: str, reasons: list[str]) -> None:
        self.feature = feature
        self.reasons = reasons
        super().__init__(f"fonction bloquée « {feature} » : " + " ; ".join(reasons))


def _walk(node: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, f"{prefix}[{i}]")
    else:
        yield prefix, node


def find_markers(file_key: str, raw: Any, text: str = "") -> list[MarkerHit]:
    hits = [
        MarkerHit(file_key, path, value)
        for path, value in _walk(raw)
        if isinstance(value, str) and value in MARKERS
    ]
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = COMMENT_MARKER_RE.search(line)
        if match:
            hits.append(MarkerHit(file_key, f"ligne {lineno}", match.group(1), in_comment=True))
    return hits


def _under(path: str, prefix: str) -> bool:
    return prefix == "" or path == prefix or path.startswith(prefix + ".")


@dataclass(frozen=True)
class Config:
    directory: Path
    models: ModelsConfig
    autonomy: AutonomyConfig
    risk_limits_paper: PaperRiskLimits
    execution: ExecutionConfig
    live: LiveConfig
    budgets: BudgetsConfig
    compliance: ComplianceConfig
    data_sources: DataSourcesConfig
    evals: EvalsConfig
    risk: RiskConfig
    pricing: PricingConfig
    guardrails: GuardrailsConfig
    research: ResearchConfig
    committee: CommitteeConfig
    markers: tuple[MarkerHit, ...]
    digest: str

    def blockers(self, feature: str) -> list[str]:
        if feature not in FEATURES:
            raise KeyError(f"fonction inconnue : {feature}")
        reasons: list[str] = []
        if feature == "live_trading" and not self.live.enabled:
            reasons.append("live.yaml › enabled = false (R3)")
        source = FEATURES[feature].source
        if source is not None:
            known = self.data_sources.sources.get(source)
            if known is None:
                reasons.append(f"data_sources.yaml › sources.{source} absente")
            elif not known.enabled:
                reasons.append(f"data_sources.yaml › sources.{source}.enabled = false")
        requires = list(FEATURES[feature].requires)
        if feature == "finance.committee":
            tiers = sorted(set(self.committee.finance.tiers.values()))
            requires.extend(f"models:tiers.{tier}" for tier in tiers)
        for req in requires:
            file_key, _, prefix = req.partition(":")
            reasons.extend(
                str(hit)
                for hit in self.markers
                if hit.file == file_key and not hit.in_comment and _under(hit.path, prefix)
            )
        return reasons

    def require(self, feature: str) -> None:
        reasons = self.blockers(feature)
        if reasons:
            raise BlockedFeatureError(feature, reasons)

    def status(self) -> dict[str, list[str]]:
        return {name: self.blockers(name) for name in FEATURES}


def config_digest(directory: Path) -> str:
    """Hash of every configuration file, recorded as ``versions.config`` in the audit journal."""
    h = hashlib.sha256()
    for _key, (filename, _model) in sorted(FILES.items()):
        path = directory / filename
        h.update(filename.encode() + b"\0")
        h.update(path.read_bytes() if path.exists() else b"<absent>")
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


def _cross_file_errors(parsed: dict[str, BaseModel]) -> list[str]:
    """Checks that span two files.

    Every Anthropic tier must have a price, otherwise its cost could not be computed. The score
    that promotes the finance pack is never below the gate of its golden set (D16, D17, R9),
    and « 0 violation R1-R5 » is only measured if every behaviour suite must fully pass. Every
    committee role runs on a tier that models.yaml defines. A drafted limit price stays within
    the collar of the Risk Gate (D17).
    """
    models: ModelsConfig = parsed["models"]  # type: ignore[assignment]
    pricing: PricingConfig = parsed["pricing"]  # type: ignore[assignment]
    autonomy: AutonomyConfig = parsed["autonomy"]  # type: ignore[assignment]
    evals: EvalsConfig = parsed["evals"]  # type: ignore[assignment]
    errors = [
        f"pricing.yaml › anthropic.models : prix absent pour {tier.model} (tier {name})"
        for name, tier in models.tiers.items()
        if tier.provider == "anthropic"
        and tier.model not in MARKERS
        and tier.model not in pricing.anthropic.models
    ]
    promotion = autonomy.promotion.finance.N0_to_N1.golden_min_score
    gate = evals.thresholds.finance_golden_min_score
    if not isinstance(promotion, str) and not isinstance(gate, str) and promotion < gate:
        errors.append(
            "autonomy.yaml › promotion.finance.N0_to_N1.golden_min_score : "
            f"{promotion} est sous le seuil du golden set Finance ({gate}, evals.yaml)"
        )
    committee: CommitteeConfig = parsed["committee"]  # type: ignore[assignment]
    errors.extend(
        f"committee.yaml › finance.tiers.{role} : niveau {tier} absent de models.yaml"
        for role, tier in committee.finance.tiers.items()
        if tier not in models.tiers
    )
    rate = evals.thresholds.behavior_suites_R1_to_R5_pass_rate
    if autonomy.promotion.finance.N0_to_N1.r1_to_r5_violations_max == 0 and rate != 1:
        errors.append(
            f"evals.yaml › thresholds.behavior_suites_R1_to_R5_pass_rate : {rate} laisse passer "
            "des violations R1-R5, que la promotion finance N0 → N1 exclut (D16)"
        )
    execution: ExecutionConfig = parsed["execution"]  # type: ignore[assignment]
    limits: PaperRiskLimits = parsed["risk_limits.paper"]  # type: ignore[assignment]
    offset, collar = execution.limit_offset_pct, limits.limit_price_collar_pct
    if not isinstance(offset, str) and not isinstance(collar, str) and offset > collar:
        errors.append(
            f"execution.yaml › limit_offset_pct : {offset} % dépasse la bande de prix de la Porte "
            f"de risque ({collar} %, risk_limits.paper.yaml) (D17)"
        )
    return errors


def load_config(directory: Path) -> Config:
    errors: list[str] = []
    parsed: dict[str, BaseModel] = {}
    markers: list[MarkerHit] = []
    for key, (filename, model) in FILES.items():
        path = directory / filename
        if not path.exists():
            errors.append(f"{filename} : fichier absent")
            continue
        text = path.read_text(encoding="utf-8")
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            errors.append(f"{filename} : YAML invalide ({exc})")
            continue
        if not isinstance(raw, dict):
            errors.append(f"{filename} : la racine doit être un dictionnaire")
            continue
        markers.extend(find_markers(key, raw, text))
        try:
            parsed[key] = model.model_validate(raw)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"])
                errors.append(f"{filename} › {loc} : {err['msg']}")
    if not errors:
        errors.extend(_cross_file_errors(parsed))
    if errors:
        raise ConfigError("\n".join(errors))
    return Config(
        directory=directory,
        models=parsed["models"],  # type: ignore[arg-type]
        autonomy=parsed["autonomy"],  # type: ignore[arg-type]
        risk_limits_paper=parsed["risk_limits.paper"],  # type: ignore[arg-type]
        execution=parsed["execution"],  # type: ignore[arg-type]
        live=parsed["live"],  # type: ignore[arg-type]
        budgets=parsed["budgets"],  # type: ignore[arg-type]
        compliance=parsed["compliance"],  # type: ignore[arg-type]
        data_sources=parsed["data_sources"],  # type: ignore[arg-type]
        evals=parsed["evals"],  # type: ignore[arg-type]
        risk=parsed["risk"],  # type: ignore[arg-type]
        pricing=parsed["pricing"],  # type: ignore[arg-type]
        guardrails=parsed["guardrails"],  # type: ignore[arg-type]
        research=parsed["research"],  # type: ignore[arg-type]
        committee=parsed["committee"],  # type: ignore[arg-type]
        markers=tuple(markers),
        digest=config_digest(directory),
    )
