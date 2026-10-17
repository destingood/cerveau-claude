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
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

MARKERS = ("A_DEFINIR", "A_VERIFIER")
Marker = Literal["A_DEFINIR", "A_VERIFIER"]
Level = Literal["N0", "N1", "N2", "N3", "N4"]
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


class Judge(_Strict):
    tier: Literal["deep", "standard", "fast", "local"]
    prefer_different_from_evaluated: bool


class Routing(_Strict):
    max_tools_to_planner: int = Field(gt=0, le=50)


class ModelsConfig(_Strict):
    tiers: dict[Literal["deep", "standard", "fast", "local"], ModelTier]
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


class PaperRiskLimits(_Strict):
    capital_reference_eur: float | Marker
    max_order_pct: float | Marker
    max_position_pct: float | Marker
    max_sector_pct: float | Marker
    max_daily_loss_pct: float | Marker
    max_drawdown_pct: float | Marker
    max_orders_per_hour: int | Marker
    limit_price_collar_pct: float | Marker
    min_avg_daily_volume: float | Marker
    allow: Allow


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
    daily: float | Marker
    monthly: float | Marker


class PerRequest(_Strict):
    max_tool_calls: int = Field(gt=0)
    max_tokens: int | Marker
    max_seconds: int = Field(gt=0)


class BudgetsConfig(_Strict):
    llm_budget_eur: LlmBudget
    alerts_pct: list[Annotated[int, Field(gt=0, le=100)]] = Field(min_length=1)
    per_request: PerRequest
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
    max_staleness_minutes: int | Marker
    min_quality_score_above_N1: float | Marker


class DataSourcesConfig(_Strict):
    sources: dict[str, DataSource]
    quality: DataQuality


class EvalThresholds(_Strict):
    generaliste_golden_min_score: float | Marker
    finance_golden_min_score: float | Marker
    behavior_suites_R1_to_R5_pass_rate: float = Field(ge=0, le=1)
    regression_block_delta: float | Marker


class EvalsConfig(_Strict):
    thresholds: EvalThresholds
    judge_human_review_sample_weekly: int = Field(ge=0)


class KillSwitch(_Strict):
    target_seconds: float | Marker
    data_loss_timeout_seconds: float | Marker


class PluginHealth(_Strict):
    slo_breach_days_before_disable: int | Marker


class Keys(_Strict):
    rotation_days: int | Marker


class Infra(_Strict):
    private_network: str


class RiskConfig(_Strict):
    kill_switch: KillSwitch
    plugin_health: PluginHealth
    keys: Keys
    infra: Infra


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


FILES: dict[str, tuple[str, type[BaseModel]]] = {
    "models": ("models.yaml", ModelsConfig),
    "autonomy": ("autonomy.yaml", AutonomyConfig),
    "risk_limits.paper": ("risk_limits.paper.yaml", PaperRiskLimits),
    "live": ("live.yaml", LiveConfig),
    "budgets": ("budgets.yaml", BudgetsConfig),
    "compliance": ("compliance.yaml", ComplianceConfig),
    "data_sources": ("data_sources.yaml", DataSourcesConfig),
    "evals": ("evals.yaml", EvalsConfig),
    "risk": ("risk.yaml", RiskConfig),
    "pricing": ("pricing.yaml", PricingConfig),
    "guardrails": ("guardrails.yaml", GuardrailsConfig),
}


@dataclass(frozen=True)
class Feature:
    description: str
    requires: tuple[str, ...]  # "<file>:<dotted prefix>", "" prefix = whole file


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
    "promotion.finance.N2_to_N3": Feature(
        "Promotion finance N2 → N3", ("autonomy:promotion.finance.N2_to_N3",)
    ),
    "promotion.finance.N3_to_N4": Feature(
        "Promotion finance N3 → N4", ("autonomy:promotion.finance.N3_to_N4",)
    ),
    "paper_trading": Feature("Porte de risque en paper trading", ("risk_limits.paper:",)),
    "live_trading": Feature("Exécution live (R3 : activée à la main par Lucas)", ("live:",)),
    "kill_switch": Feature("Kill switch (cible de temps, perte de données)", ("risk:kill_switch",)),
    "plugin_health": Feature("Désactivation auto d'un plugin hors SLO", ("risk:plugin_health",)),
    "keys.rotation": Feature("Rotation des clés", ("risk:keys",)),
    "infra.vps": Feature("Déploiement VPS (réseau privé)", ("risk:infra",)),
    "data.openbb": Feature("Source OpenBB", ("data_sources:sources.openbb",)),
    "data.yfinance": Feature("Source yfinance", ("data_sources:sources.yfinance",)),
    "data.fred": Feature("Source FRED", ("data_sources:sources.fred",)),
    "data.ecb": Feature("Source BCE", ("data_sources:sources.ecb",)),
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
    "compliance.fiscal": Feature("Règles fiscales", ("compliance:fiscal",)),
    "compliance.crypto": Feature("Plateformes crypto autorisées", ("compliance:crypto",)),
    "costs": Feature("Calcul déterministe des coûts (prix, taux de change)", ("pricing:",)),
    "guardrails.pii": Feature("Pseudonymisation Presidio (seuil, entités)", ("guardrails:pii",)),
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
    live: LiveConfig
    budgets: BudgetsConfig
    compliance: ComplianceConfig
    data_sources: DataSourcesConfig
    evals: EvalsConfig
    risk: RiskConfig
    pricing: PricingConfig
    guardrails: GuardrailsConfig
    markers: tuple[MarkerHit, ...]
    digest: str

    def blockers(self, feature: str) -> list[str]:
        if feature not in FEATURES:
            raise KeyError(f"fonction inconnue : {feature}")
        reasons: list[str] = []
        if feature == "live_trading" and not self.live.enabled:
            reasons.append("live.yaml › enabled = false (R3)")
        for req in FEATURES[feature].requires:
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
    """Every Anthropic tier must have a price, otherwise its cost could not be computed."""
    models: ModelsConfig = parsed["models"]  # type: ignore[assignment]
    pricing: PricingConfig = parsed["pricing"]  # type: ignore[assignment]
    return [
        f"pricing.yaml › anthropic.models : prix absent pour {tier.model} (tier {name})"
        for name, tier in models.tiers.items()
        if tier.provider == "anthropic"
        and tier.model not in MARKERS
        and tier.model not in pricing.anthropic.models
    ]


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
        live=parsed["live"],  # type: ignore[arg-type]
        budgets=parsed["budgets"],  # type: ignore[arg-type]
        compliance=parsed["compliance"],  # type: ignore[arg-type]
        data_sources=parsed["data_sources"],  # type: ignore[arg-type]
        evals=parsed["evals"],  # type: ignore[arg-type]
        risk=parsed["risk"],  # type: ignore[arg-type]
        pricing=parsed["pricing"],  # type: ignore[arg-type]
        guardrails=parsed["guardrails"],  # type: ignore[arg-type]
        markers=tuple(markers),
        digest=config_digest(directory),
    )
