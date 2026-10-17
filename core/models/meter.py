"""Usage and cost of one request, recorded call by call (ADR-005).

The meter is the per-request account: every model call and every paid search adds a line. The
lines go into the audit payloads (``DECISION`` / ``TOOL_CALL``), from which the daily and
monthly ledger is rebuilt. Missing usage is an error, never a zero cost.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from core.models.costs import COST_SCHEMA, CostCalculator, CostUnavailableError, TokenUsage


@dataclass(frozen=True)
class LlmCall:
    role: str
    tier: str
    model: str
    model_reported: str | None
    usage: TokenUsage
    price_tier: int
    usd: Decimal
    eur: Decimal

    def to_payload(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "tier": self.tier,
            "model": self.model,
            "model_reported": self.model_reported,
            "tokens": self.usage.to_payload(),
            "price_tier": self.price_tier,
            "cost_usd": str(self.usd),
            "cost_eur": str(self.eur),
        }


@dataclass(frozen=True)
class SearchCall:
    provider: str
    requests: int
    usd: Decimal
    eur: Decimal

    def to_payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "requests": self.requests,
            "cost_usd": str(self.usd),
            "cost_eur": str(self.eur),
        }


class Meter:
    """Thread-safe account of one request."""

    def __init__(self, calculator: CostCalculator) -> None:
        self._calculator = calculator
        self._lock = threading.Lock()
        self._llm: list[LlmCall] = []
        self._search: list[SearchCall] = []

    def record_llm(
        self,
        *,
        role: str,
        tier: str,
        model: str,
        usage: TokenUsage,
        model_reported: str | None = None,
    ) -> LlmCall:
        usd, price_tier = self._calculator.llm_usd(model, usage)
        call = LlmCall(
            role=role,
            tier=tier,
            model=model,
            model_reported=model_reported,
            usage=usage,
            price_tier=price_tier,
            usd=usd,
            eur=self._calculator.to_eur(usd),
        )
        with self._lock:
            self._llm.append(call)
        return call

    def record_search(self, provider: str, requests: int = 1) -> SearchCall:
        usd = self._calculator.search_usd(provider, requests)
        call = SearchCall(provider, requests, usd, self._calculator.to_eur(usd))
        with self._lock:
            self._search.append(call)
        return call

    @property
    def llm_calls(self) -> tuple[LlmCall, ...]:
        with self._lock:
            return tuple(self._llm)

    @property
    def search_calls(self) -> tuple[SearchCall, ...]:
        with self._lock:
            return tuple(self._search)

    @property
    def usage(self) -> TokenUsage:
        total = TokenUsage()
        for call in self.llm_calls:
            total = total + call.usage
        return total

    @property
    def total_tokens(self) -> int:
        return self.usage.total

    @property
    def total_usd(self) -> Decimal:
        return sum((c.usd for c in (*self.llm_calls, *self.search_calls)), Decimal(0))

    @property
    def total_eur(self) -> Decimal:
        return sum((c.eur for c in (*self.llm_calls, *self.search_calls)), Decimal(0))

    def to_payload(self) -> dict[str, Any]:
        """Cost block of the request's ``DECISION`` entry (cost schema ``COST_SCHEMA``)."""
        return {
            "cost_schema": COST_SCHEMA,
            "pricing_verified_on": self._calculator.pricing_verified_on,
            "fx_usd_per_eur": str(self._calculator.rate),
            "fx_rate_date": self._calculator.fx_rate_date,
            "llm_calls": [c.to_payload() for c in self.llm_calls],
            "searches": [c.to_payload() for c in self.search_calls],
            "tokens_total": self.total_tokens,
            "cost_usd": str(self.total_usd),
            "cost_eur": str(self.total_eur),
        }


class MeterCallback(BaseCallbackHandler):
    """Records the usage of every call of one model into a meter.

    ``raise_error`` makes LangChain propagate our errors: a call whose usage is missing or
    cannot be priced fails instead of being silently free.
    """

    raise_error = True

    def __init__(self, meter: Meter, *, role: str, tier: str, model: str) -> None:
        super().__init__()
        self.meter = meter
        self.role = role
        self.tier = tier
        self.model = model

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        try:
            generation = response.generations[0][0]
        except IndexError:
            generation = None
        message = generation.message if isinstance(generation, ChatGeneration) else None
        usage = message.usage_metadata if isinstance(message, AIMessage) else None
        if not usage:
            raise CostUnavailableError(f"usage absent pour un appel {self.model} : coût inconnu")
        reported = message.response_metadata.get("model_name") if message else None
        self.meter.record_llm(
            role=self.role,
            tier=self.tier,
            model=self.model,
            usage=TokenUsage.from_usage_metadata(usage),
            model_reported=reported,
        )
