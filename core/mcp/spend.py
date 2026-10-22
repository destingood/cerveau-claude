"""Spend of an isolated code task, charged to the request's meter (ADR-054).

The code agent's model calls go through its API proxy (ADR-053), not through the request's
meter. Its tool result reports, under ``depense``, the tokens the proxy counted for the task's
model and whether a cost stayed unknown; the adapter charges them here, priced by the request's
calculator like any other call (R1). Prudence (R7): a report that is missing or unreadable, that
names another model, or that the calculator cannot price charges the task's ceiling; a cost the
proxy could not compute adds the ceiling to what it counted. Never zero by default. The task's
tokens are priced as one call: with tiered prices, their summed prompt never picks a cheaper tier
than each of its requests would.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from core.models.costs import CostUnavailableError, TokenUsage
from core.models.meter import LlmCall, Meter

SPEND_KEY = "depense"
AGENT_TIER = "agent"
TOKEN_FIELDS = ("input", "cache_read", "cache_write_5m", "cache_write_1h", "output")


@dataclass(frozen=True)
class IsolatedTask:
    """The model and the spending ceiling of a code agent task (``code.yaml`` › ``agent``)."""

    model: str
    max_usd: Decimal


def _usage(raw: Any) -> TokenUsage | None:
    if not isinstance(raw, Mapping) or set(raw) != set(TOKEN_FIELDS):
        return None
    counts = [raw[name] for name in TOKEN_FIELDS]
    if not all(type(count) is int and count >= 0 for count in counts):
        return None
    return TokenUsage(**dict(zip(TOKEN_FIELDS, counts, strict=True)))


def reported(task: IsolatedTask, result: Any) -> tuple[TokenUsage | None, bool] | None:
    """The tokens of the task's model (``None`` when it made no call) and whether a cost stayed
    unknown; ``None`` when the report is missing or unreadable."""
    spend = result.get(SPEND_KEY) if isinstance(result, Mapping) else None
    if not isinstance(spend, Mapping) or set(spend) != {"modeles", "cout_inconnu"}:
        return None
    models, unknown = spend["modeles"], spend["cout_inconnu"]
    if not isinstance(models, Mapping) or not isinstance(unknown, bool):
        return None
    if set(models) - {task.model}:  # the proxy serves the task's model only
        return None
    if task.model not in models:
        return None, unknown
    usage = _usage(models[task.model])
    return None if usage is None else (usage, unknown)


def charge(meter: Meter, task: IsolatedTask, *, role: str, result: Any) -> tuple[LlmCall, ...]:
    """Charges the task's spend to ``meter``; ``result`` is ``None`` when the call failed."""

    def ceiling() -> tuple[LlmCall, ...]:
        return (meter.record_ceiling(role=role, model=task.model, usd=task.max_usd),)

    report = reported(task, result)
    if report is None:
        return ceiling()
    usage, unknown = report
    calls: list[LlmCall] = []
    if usage is not None:
        try:
            calls.append(
                meter.record_llm(role=role, tier=AGENT_TIER, model=task.model, usage=usage)
            )
        except CostUnavailableError:
            return ceiling()
    if unknown:
        calls.extend(ceiling())
    return tuple(calls)
