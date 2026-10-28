"""Deterministic cost computation from ``config/pricing.yaml`` (R1, ADR-005).

A cost is a decision figure: it is computed here, never by a model. Prices are exact decimals
in USD per million tokens; the result is rounded up to 1e-6 so that budgets are never
under-counted, then converted to EUR at the fixed, dated rate of ``pricing.yaml`` (D5).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, Context, Decimal
from typing import Any

from core.config.loader import PriceTier, PricingConfig

COST_SCHEMA = 1  # version of the cost fields written to the audit journal
QUANTUM = Decimal("0.000001")
_CTX = Context(prec=28)
_PER_MTOK = Decimal(1_000_000)
_PER_1000 = Decimal(1000)


class CostUnavailableError(Exception):
    """A price, a rate or the usage itself is unknown: the cost cannot be computed (R7)."""


@dataclass(frozen=True)
class TokenUsage:
    """Tokens of one model call, split the way they are billed."""

    input: int = 0  # uncached input tokens
    cache_read: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    output: int = 0  # thinking tokens included: they are billed as output

    def __post_init__(self) -> None:
        for name in ("input", "cache_read", "cache_write_5m", "cache_write_1h", "output"):
            if getattr(self, name) < 0:
                raise ValueError(f"usage négatif : {name}")

    @property
    def prompt_tokens(self) -> int:
        """Prompt length as the price tiers count it: input plus cache reads and writes."""
        return self.input + self.cache_read + self.cache_write_5m + self.cache_write_1h

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.output

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input=self.input + other.input,
            cache_read=self.cache_read + other.cache_read,
            cache_write_5m=self.cache_write_5m + other.cache_write_5m,
            cache_write_1h=self.cache_write_1h + other.cache_write_1h,
            output=self.output + other.output,
        )

    @classmethod
    def from_usage_metadata(cls, usage: Mapping[str, Any]) -> TokenUsage:
        """Read LangChain ``UsageMetadata`` as built by langchain-anthropic 1.7.6.

        There, ``input_tokens`` already includes cache reads and writes, and the generic
        ``cache_creation`` detail is zeroed when the 5 min / 1 h split is known. A cache write
        without that split is priced at the 1 h rate, the higher one (prudence).
        """
        details = usage.get("input_token_details") or {}
        cache_read = details.get("cache_read") or 0
        write_5m = details.get("ephemeral_5m_input_tokens") or 0
        write_1h = details.get("ephemeral_1h_input_tokens") or 0
        if not (write_5m or write_1h):
            write_1h = details.get("cache_creation") or 0
        uncached = (usage.get("input_tokens") or 0) - cache_read - write_5m - write_1h
        if uncached < 0:
            raise CostUnavailableError("usage incohérent : cache supérieur à l'entrée")
        return cls(
            input=uncached,
            cache_read=cache_read,
            cache_write_5m=write_5m,
            cache_write_1h=write_1h,
            output=usage.get("output_tokens") or 0,
        )

    def to_payload(self) -> dict[str, int]:
        return {
            "input": self.input,
            "cache_read": self.cache_read,
            "cache_write_5m": self.cache_write_5m,
            "cache_write_1h": self.cache_write_1h,
            "output": self.output,
        }


def _price(value: Decimal | str, what: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise CostUnavailableError(f"prix inconnu ({what} = {value})")
    return value


def _round_up(value: Decimal) -> Decimal:
    return value.quantize(QUANTUM, rounding=ROUND_CEILING, context=_CTX)


class CostCalculator:
    """Prices model calls and searches with the prices of ``pricing.yaml``."""

    def __init__(self, pricing: PricingConfig) -> None:
        self._pricing = pricing
        self.rate = _price(pricing.fx.usd_per_eur, "fx.usd_per_eur")  # type: ignore[arg-type]

    @property
    def pricing_verified_on(self) -> str:
        return self._pricing.anthropic.verified_on.isoformat()

    @property
    def fx_rate_date(self) -> str:
        return self._pricing.fx.rate_date.isoformat()

    def price_tier(self, model: str, usage: TokenUsage) -> tuple[int, PriceTier]:
        """The price tier that applies to this call, chosen by its prompt length."""
        pricing = self._pricing.anthropic.models.get(model)
        if pricing is None:
            raise CostUnavailableError(f"prix absent pour le modèle {model}")
        for index, tier in enumerate(pricing.tiers):
            if tier.max_prompt_tokens is None or usage.prompt_tokens <= tier.max_prompt_tokens:
                return index, tier
        raise CostUnavailableError(f"aucun palier de prix pour {model}")  # pragma: no cover

    def llm_usd(self, model: str, usage: TokenUsage) -> tuple[Decimal, int]:
        """Cost in USD of one call and the index of the applied price tier."""
        index, tier = self.price_tier(model, usage)
        parts = (
            (usage.input, tier.input, "input"),
            (usage.cache_read, tier.cache_read, "cache_read"),
            (usage.cache_write_5m, tier.cache_write_5m, "cache_write_5m"),
            (usage.cache_write_1h, tier.cache_write_1h, "cache_write_1h"),
            (usage.output, tier.output, "output"),
        )
        total = Decimal(0)
        for tokens, price, name in parts:
            if tokens:
                per_mtok = _price(price, f"{model}.{name}")  # type: ignore[arg-type]
                total = _CTX.add(total, _CTX.multiply(Decimal(tokens), per_mtok))
        return _round_up(_CTX.divide(total, _PER_MTOK)), index

    def search_usd(self, provider: str, requests: int = 1) -> Decimal:
        if requests < 0:
            raise ValueError("nombre de requêtes négatif")
        price = self._pricing.search.get(provider)
        if price is None:
            raise CostUnavailableError(f"prix absent pour la recherche {provider}")
        per_1000 = _price(price.usd_per_1000_requests, f"search.{provider}")  # type: ignore[arg-type]
        return _round_up(_CTX.divide(_CTX.multiply(Decimal(requests), per_1000), _PER_1000))

    def round_up(self, usd: Decimal) -> Decimal:
        """An amount in USD rounded up to the precision of every computed cost."""
        return _round_up(usd)

    def to_eur(self, usd: Decimal) -> Decimal:
        return _round_up(_CTX.divide(usd, self.rate))
