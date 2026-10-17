"""Model router: one role, one tier, one metered chat model (ADR-005).

The role → tier mapping is a code constant, not configuration: changing it changes the
behaviour under evaluation, so it goes through review and evals (R9). Only the judge's tier is
read from ``models.yaml`` (``judge.tier``), where it is declared.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel

from core.config.loader import Config
from core.models.costs import CostCalculator
from core.models.meter import Meter, MeterCallback

Role = Literal["classifier", "reader", "verifier", "planner", "planner_complex", "judge"]
Tier = Literal["deep", "standard", "fast", "local"]

ROLE_TIERS: Mapping[Role, Tier] = MappingProxyType(
    {
        "classifier": "fast",  # nodes 2 and 3: refusal / clarification, domain, complexity
        "reader": "fast",  # R5 reader: page text → validated extracts, no tools
        "verifier": "fast",  # node 5: support of uncited claims
        "planner": "standard",
        "planner_complex": "deep",
    }
)

# Pinned so that ANTHROPIC_BASE_URL, ANTHROPIC_API_URL, a LangSmith gateway or
# ANTHROPIC_PROXY in the environment cannot redirect requests (and the API key) elsewhere.
ANTHROPIC_BASE_URL = "https://api.anthropic.com"


@dataclass(frozen=True)
class ModelRequest:
    role: Role
    tier: Tier
    model: str
    timeout_s: float
    max_output_tokens: int | None
    callbacks: tuple[BaseCallbackHandler, ...]


ModelFactory = Callable[[ModelRequest], BaseChatModel]


def anthropic_factory(request: ModelRequest) -> BaseChatModel:
    """Builds the real model. The API key is read by langchain-anthropic from
    ``ANTHROPIC_API_KEY``; CERVEAU never reads, stores or logs it (R6)."""
    from langchain_anthropic import ChatAnthropic

    def build(max_tokens: int | None) -> ChatAnthropic:
        return ChatAnthropic(
            model=request.model,
            max_tokens=max_tokens,  # None: the output limit of the model's profile
            timeout=request.timeout_s,
            base_url=ANTHROPIC_BASE_URL,
            anthropic_proxy=None,
            callbacks=list(request.callbacks),
        )

    model = build(None)
    cap = request.max_output_tokens
    if cap is not None and (model.max_tokens is None or cap < model.max_tokens):
        model = build(cap)
    return model


class ModelRouter:
    """Hands out chat models by role, each wired to the request's meter."""

    def __init__(self, config: Config, *, factory: ModelFactory = anthropic_factory) -> None:
        config.require("costs")  # no model call whose cost could not be computed (R1, R7)
        self._config = config
        self._factory = factory
        self.calculator = CostCalculator(config.pricing)

    def tier_for(self, role: Role) -> Tier:
        if role == "judge":
            return self._config.models.judge.tier
        return ROLE_TIERS[role]

    def model_id(self, role: Role) -> str:
        return self._config.models.tiers[self.tier_for(role)].model

    def new_meter(self) -> Meter:
        return Meter(self.calculator)

    def chat(
        self,
        role: Role,
        meter: Meter,
        *,
        timeout_s: float,
        max_output_tokens: int | None = None,
    ) -> BaseChatModel:
        """A chat model for ``role`` whose every call is priced into ``meter``.

        ``max_output_tokens`` is an upper bound (usually what is left of the request's token
        budget); the model's own output limit applies when it is lower. Raises
        ``BlockedFeatureError`` when the tier still holds a marker (R7).
        """
        if timeout_s <= 0:
            raise ValueError("délai d'appel nul ou négatif")
        if max_output_tokens is not None and max_output_tokens <= 0:
            raise ValueError("plafond de tokens de sortie nul ou négatif")
        tier = self.tier_for(role)
        self._config.require(f"llm.{tier}")
        spec = self._config.models.tiers[tier]
        if spec.provider != "anthropic":
            raise NotImplementedError(f"fournisseur {spec.provider} non pris en charge en phase 1")
        callback = MeterCallback(meter, role=role, tier=tier, model=spec.model)
        return self._factory(
            ModelRequest(
                role=role,
                tier=tier,
                model=spec.model,
                timeout_s=timeout_s,
                max_output_tokens=max_output_tokens,
                callbacks=(callback,),
            )
        )
