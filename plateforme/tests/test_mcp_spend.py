"""The spend of an isolated code task, read from its tool result and charged (ADR-053, ADR-054)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.config import load_config
from core.mcp.spend import AGENT_TIER, SPEND_KEY, TOKEN_FIELDS, IsolatedTask, charge, reported
from core.models import CostCalculator, Meter, TokenUsage
from core.models.meter import CEILING_TIER

CONFIG = load_config(Path(__file__).resolve().parents[1] / "config")
TASK = IsolatedTask(model="claude-sonnet-5-5", max_usd=Decimal(2))
TOKENS = {
    "input": 1000,
    "cache_read": 2000,
    "cache_write_5m": 400,
    "cache_write_1h": 0,
    "output": 500,
}
# 1000 × 2 + 2000 × 0.10 + 400 × 2.50 + 500 × 10, in USD per million tokens (pricing.yaml).
TOKENS_USD = Decimal("0.008200")


def result(models: Any = None, unknown: Any = False, **extra: Any) -> dict[str, Any]:
    models = {TASK.model: dict(TOKENS)} if models is None else models
    return {"patch": "…", SPEND_KEY: {"modeles": models, "cout_inconnu": unknown, **extra}}


def meter() -> Meter:
    return Meter(CostCalculator(CONFIG.pricing))


def test_a_known_usage_is_priced_like_any_call() -> None:
    account = meter()
    [call] = charge(account, TASK, role="code_agent", result=result())
    assert (call.role, call.tier, call.model) == ("code_agent", AGENT_TIER, TASK.model)
    assert call.usage == TokenUsage(**TOKENS)
    assert call.usd == TOKENS_USD
    assert account.total_tokens == sum(TOKENS.values())  # counted against the task's budget


def test_an_unknown_cost_adds_the_ceiling_to_what_was_counted() -> None:
    account = meter()
    counted, ceiling = charge(account, TASK, role="code_agent", result=result(unknown=True))
    assert (counted.tier, counted.usd) == (AGENT_TIER, TOKENS_USD)
    assert (ceiling.tier, ceiling.usd) == (CEILING_TIER, Decimal("2.000000"))
    assert account.total_usd == TOKENS_USD + 2


def test_a_task_that_made_no_call_costs_nothing() -> None:
    """The proxy saw no request: the report says so, not a default."""
    assert reported(TASK, result(models={})) == (None, False)
    account = meter()
    assert charge(account, TASK, role="code_agent", result=result(models={})) == ()
    assert account.llm_calls == ()


def test_no_call_and_an_unknown_cost_still_charge_the_ceiling() -> None:
    [call] = charge(meter(), TASK, role="code_agent", result=result(models={}, unknown=True))
    assert (call.tier, call.usd) == (CEILING_TIER, Decimal("2.000000"))


@pytest.mark.parametrize(
    "bad",
    [
        None,  # the call failed
        "texte",
        {},  # no report
        {SPEND_KEY: None},
        {SPEND_KEY: []},
        result(extra="champ"),
        {SPEND_KEY: {"modeles": {}}},
        result(models=[]),
        result(unknown="non"),
        result(unknown=0),
        result(models={TASK.model: dict(TOKENS), "claude-opus-5-5": dict(TOKENS)}),
        result(models={"claude-opus-5-5": dict(TOKENS)}),  # the proxy serves the task's model
        result(models={TASK.model: None}),
        result(models={TASK.model: {**TOKENS, "output": -1}}),
        result(models={TASK.model: {**TOKENS, "output": True}}),
        result(models={TASK.model: {**TOKENS, "output": 1.0}}),
        result(models={TASK.model: {**TOKENS, "output": "500"}}),
        result(models={TASK.model: {k: v for k, v in TOKENS.items() if k != "output"}}),
        result(models={TASK.model: {**TOKENS, "web_search": 1}}),
    ],
)
def test_an_unreadable_report_charges_the_ceiling(bad: Any) -> None:
    assert reported(TASK, bad) is None
    account = meter()
    [call] = charge(account, TASK, role="code_agent", result=bad)
    assert (call.role, call.tier, call.model) == ("code_agent", CEILING_TIER, TASK.model)
    assert call.usage == TokenUsage()
    assert account.total_usd == Decimal("2.000000")


def test_a_model_without_a_price_charges_the_ceiling() -> None:
    task = IsolatedTask(model="claude-inconnu-1", max_usd=Decimal("1.50"))
    usage, unknown = reported(task, result(models={task.model: dict(TOKENS)})) or (None, None)
    assert (usage, unknown) == (TokenUsage(**TOKENS), False)
    [call] = charge(meter(), task, role="code_agent", result=result(models={task.model: TOKENS}))
    assert (call.tier, call.usd) == (CEILING_TIER, Decimal("1.500000"))


counts = st.integers(min_value=0, max_value=10**9)
usages = st.fixed_dictionaries({name: counts for name in TOKEN_FIELDS})
noise = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=8),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=8), inner),
    max_leaves=10,
)


@given(models=st.dictionaries(st.sampled_from([TASK.model, "x"]), usages | noise), unknown=noise)
def test_a_sent_task_is_charged_its_ceiling_unless_its_report_reads(
    models: Any, unknown: Any
) -> None:
    """R7: whatever comes back, the charge is the counted usage, the ceiling, or both; zero only
    when the proxy reports, readably, that no request reached the API."""
    calls = charge(meter(), TASK, role="code_agent", result=result(models=models, unknown=unknown))
    report = reported(TASK, result(models=models, unknown=unknown))
    if report is None:
        assert [call.tier for call in calls] == [CEILING_TIER]
        return
    usage, flagged = report
    tiers = [AGENT_TIER] * (usage is not None) + [CEILING_TIER] * flagged
    assert [call.tier for call in calls] == tiers
