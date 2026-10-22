from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from core.config import BlockedFeatureError, load_config
from core.config.loader import Config
from core.models import (
    ANTHROPIC_BASE_URL,
    ROLE_TIERS,
    CostCalculator,
    CostUnavailableError,
    Meter,
    MeterCallback,
    ModelRequest,
    ModelRouter,
    TokenUsage,
    anthropic_factory,
)
from core.models.meter import CEILING_TIER

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture(scope="module")
def config() -> Config:
    return load_config(REPO_CONFIG)


@pytest.fixture(scope="module")
def calc(config: Config) -> CostCalculator:
    return CostCalculator(config.pricing)


def _edit(path: Path, change) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _ai(usage: dict | None, model: str = "claude-haiku-5-5") -> AIMessage:
    return AIMessage(content="ok", usage_metadata=usage, response_metadata={"model_name": model})


HAIKU_USAGE = {
    "input_tokens": 1200,
    "output_tokens": 30,
    "total_tokens": 1230,
    "input_token_details": {
        "cache_read": 1000,
        "cache_creation": 0,
        "ephemeral_5m_input_tokens": 100,
        "ephemeral_1h_input_tokens": 0,
    },
}


# --- usage -------------------------------------------------------------------------------------


def test_usage_metadata_is_split_as_billed() -> None:
    usage = TokenUsage.from_usage_metadata(HAIKU_USAGE)
    assert usage == TokenUsage(input=100, cache_read=1000, cache_write_5m=100, output=30)
    assert usage.prompt_tokens == 1200
    assert usage.total == 1230


def test_cache_write_without_ttl_is_priced_at_the_higher_rate() -> None:
    usage = TokenUsage.from_usage_metadata(
        {"input_tokens": 500, "output_tokens": 1, "input_token_details": {"cache_creation": 200}}
    )
    assert usage == TokenUsage(input=300, cache_write_1h=200, output=1)


def test_usage_without_details_is_all_uncached_input() -> None:
    usage = TokenUsage.from_usage_metadata({"input_tokens": 42, "output_tokens": 7})
    assert usage == TokenUsage(input=42, output=7)


def test_inconsistent_usage_is_refused() -> None:
    with pytest.raises(CostUnavailableError):
        TokenUsage.from_usage_metadata(
            {"input_tokens": 10, "output_tokens": 0, "input_token_details": {"cache_read": 11}}
        )
    with pytest.raises(ValueError, match="négatif"):
        TokenUsage(output=-1)


# --- costs -------------------------------------------------------------------------------------


def test_opus_cost_is_exact(calc: CostCalculator) -> None:
    usage = TokenUsage(input=1000, cache_read=2000, cache_write_5m=100, output=500)
    # 1000 × 4 + 2000 × 0.20 + 100 × 5 + 500 × 20 = 14 900 $ / MTok
    assert calc.llm_usd("claude-opus-5-5", usage) == (Decimal("0.014900"), 0)
    # 0.0149 / 1.1253 = 0.0132409135… rounded up
    assert calc.to_eur(Decimal("0.0149")) == Decimal("0.013241")


def test_haiku_price_tier_follows_the_prompt_length(calc: CostCalculator) -> None:
    at_limit = TokenUsage(input=100_000)
    assert calc.llm_usd("claude-haiku-5-5", at_limit) == (Decimal("0.010000"), 0)
    # cache reads count in the prompt length: 99 000 + 1 001 > 100 000
    over = TokenUsage(input=99_000, cache_read=1001)
    # 99 000 × 0.50 + 1 001 × 0.05 = 49 550.05 $ / MTok
    assert calc.llm_usd("claude-haiku-5-5", over) == (Decimal("0.049551"), 1)


def test_costs_are_rounded_up_never_down(calc: CostCalculator) -> None:
    assert calc.llm_usd("claude-haiku-5-5", TokenUsage(input=1)) == (Decimal("0.000001"), 0)
    assert calc.llm_usd("claude-haiku-5-5", TokenUsage()) == (Decimal("0.000000"), 0)


def test_search_cost(calc: CostCalculator) -> None:
    assert calc.search_usd("brave") == Decimal("0.005000")
    assert calc.search_usd("brave", 3) == Decimal("0.015000")
    assert calc.to_eur(Decimal("0.005")) == Decimal("0.004444")
    with pytest.raises(CostUnavailableError):
        calc.search_usd("unknown")
    with pytest.raises(ValueError):
        calc.search_usd("brave", -1)


def test_unknown_model_has_no_cost(calc: CostCalculator) -> None:
    with pytest.raises(CostUnavailableError, match="prix absent"):
        calc.llm_usd("claude-unknown", TokenUsage(input=1))


@given(
    st.integers(0, 2_000_000),
    st.integers(0, 2_000_000),
    st.integers(0, 2_000_000),
    st.integers(0, 2_000_000),
    st.integers(0, 2_000_000),
    st.sampled_from(["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]),
)
def test_cost_is_the_exact_price_rounded_up(
    calc: CostCalculator, i: int, cr: int, w5: int, w1: int, out: int, model: str
) -> None:
    usage = TokenUsage(input=i, cache_read=cr, cache_write_5m=w5, cache_write_1h=w1, output=out)
    usd, index = calc.llm_usd(model, usage)
    tier_index, tier = calc.price_tier(model, usage)
    assert index == tier_index
    exact = (
        i * tier.input
        + cr * tier.cache_read
        + w5 * tier.cache_write_5m
        + w1 * tier.cache_write_1h
        + out * tier.output
    ) / Decimal(1_000_000)
    assert exact <= usd < exact + Decimal("0.000001")
    assert usd.as_tuple().exponent == -6


# --- meter -------------------------------------------------------------------------------------


def test_meter_totals_and_payload(calc: CostCalculator) -> None:
    meter = Meter(calc)
    meter.record_llm(
        role="planner", tier="standard", model="claude-sonnet-5-5", usage=TokenUsage(input=1000)
    )
    meter.record_search("brave", 2)
    assert meter.total_usd == Decimal("0.012000")  # 0.002 + 0.010
    assert meter.total_tokens == 1000
    payload = meter.to_payload()
    assert payload["cost_schema"] == 1
    assert payload["cost_usd"] == "0.012000"
    assert payload["fx_usd_per_eur"] == "1.1253"
    assert payload["llm_calls"][0]["tokens"]["input"] == 1000
    assert payload["searches"][0] == {
        "provider": "brave",
        "requests": 2,
        "cost_usd": "0.010000",
        "cost_eur": "0.008887",
    }


def test_a_ceiling_is_charged_when_the_usage_is_unknown(calc: CostCalculator) -> None:
    """ADR-054: an isolated task whose spend cannot be read costs its whole ceiling (R7)."""
    meter = Meter(calc)
    call = meter.record_ceiling(role="code_agent", model="claude-sonnet-5-5", usd=Decimal(2))
    assert (call.tier, call.model, call.model_reported, call.price_tier) == (
        CEILING_TIER,
        "claude-sonnet-5-5",
        None,
        0,
    )
    assert call.usage == TokenUsage()  # no token is invented
    assert (call.usd, call.eur) == (Decimal("2.000000"), Decimal("1.777304"))  # rounded up
    assert meter.llm_calls == (call,)
    assert (meter.total_usd, meter.total_tokens) == (Decimal("2.000000"), 0)
    assert meter.to_payload()["llm_calls"][0]["tier"] == "plafond"


def test_a_ceiling_is_rounded_up_like_any_cost(calc: CostCalculator) -> None:
    assert calc.round_up(Decimal("0.1234561")) == Decimal("0.123457")
    assert calc.round_up(Decimal("0.5")) == Decimal("0.500000")
    call = Meter(calc).record_ceiling(role="r", model="m", usd=Decimal("0.1234561"))
    assert (call.usd, call.eur) == (Decimal("0.123457"), Decimal("0.109711"))


@pytest.mark.parametrize("usd", ["0", "-1", "NaN", "Infinity"])
def test_a_ceiling_is_a_positive_amount(calc: CostCalculator, usd: str) -> None:
    meter = Meter(calc)
    with pytest.raises(ValueError, match="plafond invalide"):
        meter.record_ceiling(role="r", model="m", usd=Decimal(usd))
    assert meter.llm_calls == ()


def test_callback_records_every_call(calc: CostCalculator) -> None:
    meter = Meter(calc)
    callback = MeterCallback(meter, role="reader", tier="fast", model="claude-haiku-5-5")
    model = FakeMessagesListChatModel(responses=[_ai(HAIKU_USAGE)], callbacks=[callback])
    model.invoke("bonjour")
    model.invoke("encore")
    calls = meter.llm_calls
    assert len(calls) == 2
    # 100 × 0.10 + 1000 × 0.01 + 100 × 0.125 + 30 × 0.50 = 47.5 $ / MTok
    assert calls[0].usd == Decimal("0.000048")
    assert calls[0].model_reported == "claude-haiku-5-5"
    assert calls[0].role == "reader"


def test_call_without_usage_fails_instead_of_being_free(calc: CostCalculator) -> None:
    meter = Meter(calc)
    callback = MeterCallback(meter, role="reader", tier="fast", model="claude-haiku-5-5")
    model = FakeMessagesListChatModel(responses=[_ai(None)], callbacks=[callback])
    with pytest.raises(CostUnavailableError, match="usage absent"):
        model.invoke("bonjour")
    assert meter.llm_calls == ()


# --- router ------------------------------------------------------------------------------------


def _fake_factory(seen: list[ModelRequest]):
    def factory(request: ModelRequest) -> FakeMessagesListChatModel:
        seen.append(request)
        return FakeMessagesListChatModel(
            responses=[_ai(HAIKU_USAGE, request.model)], callbacks=list(request.callbacks)
        )

    return factory


def test_roles_map_to_the_planned_tiers(config: Config) -> None:
    router = ModelRouter(config, factory=_fake_factory([]))
    assert dict(ROLE_TIERS) == {
        "classifier": "fast",
        "reader": "fast",
        "verifier": "fast",
        "planner": "standard",
        "planner_complex": "deep",
    }
    assert router.tier_for("judge") == "deep"
    assert router.model_id("planner") == "claude-sonnet-5-5"
    assert router.model_id("judge") != router.model_id("planner")


def test_router_meters_the_model_it_hands_out(config: Config) -> None:
    seen: list[ModelRequest] = []
    router = ModelRouter(config, factory=_fake_factory(seen))
    meter = router.new_meter()
    router.chat("reader", meter, timeout_s=15, max_output_tokens=2000).invoke("page")
    assert seen[0].model == "claude-haiku-5-5"
    assert seen[0].timeout_s == 15
    assert seen[0].max_output_tokens == 2000
    assert len(meter.llm_calls) == 1
    assert meter.llm_calls[0].tier == "fast"


@pytest.mark.parametrize("bad", [{"timeout_s": 0}, {"timeout_s": 5, "max_output_tokens": 0}])
def test_router_refuses_empty_limits(config: Config, bad: dict) -> None:
    router = ModelRouter(config, factory=_fake_factory([]))
    with pytest.raises(ValueError):
        router.chat("reader", router.new_meter(), **bad)


def test_unverified_tier_is_refused(config_dir: Path) -> None:
    _edit(config_dir / "models.yaml", lambda d: d["tiers"]["fast"].update(model="A_VERIFIER"))
    router = ModelRouter(load_config(config_dir), factory=_fake_factory([]))
    with pytest.raises(BlockedFeatureError, match=r"llm\.fast"):
        router.chat("reader", router.new_meter(), timeout_s=5)
    router.chat("planner", router.new_meter(), timeout_s=5)  # other tiers still work


def test_local_judge_stays_blocked(config_dir: Path) -> None:
    _edit(config_dir / "models.yaml", lambda d: d["judge"].update(tier="local"))
    router = ModelRouter(load_config(config_dir), factory=_fake_factory([]))
    with pytest.raises(BlockedFeatureError, match=r"llm\.local"):
        router.chat("judge", router.new_meter(), timeout_s=5)


def test_unknown_price_blocks_the_router(config_dir: Path) -> None:
    def change(d: dict) -> None:
        d["anthropic"]["models"]["claude-sonnet-5-5"]["tiers"][0]["output"] = "A_VERIFIER"

    _edit(config_dir / "pricing.yaml", change)
    with pytest.raises(BlockedFeatureError, match="costs"):
        ModelRouter(load_config(config_dir), factory=_fake_factory([]))


def test_real_factory_ignores_redirecting_environment(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://attacker.invalid")
    monkeypatch.setenv("ANTHROPIC_API_URL", "https://attacker.invalid")
    monkeypatch.setenv("ANTHROPIC_PROXY", "http://attacker.invalid:8080")
    monkeypatch.setenv("LANGSMITH_GATEWAY", "true")
    router = ModelRouter(config)
    model = router.chat("planner", router.new_meter(), timeout_s=30, max_output_tokens=4000)
    assert model.anthropic_api_url == ANTHROPIC_BASE_URL  # type: ignore[attr-defined]
    assert model.anthropic_proxy is None  # type: ignore[attr-defined]
    assert model.model == "claude-sonnet-5-5"  # type: ignore[attr-defined]
    assert model.max_tokens == 4000  # type: ignore[attr-defined]
    assert model.default_request_timeout == 30  # type: ignore[attr-defined]
    assert any(isinstance(c, MeterCallback) for c in model.callbacks)  # type: ignore[union-attr]
    assert anthropic_factory is not None


def test_real_factory_keeps_the_lower_output_limit(config: Config) -> None:
    router = ModelRouter(config)
    meter = router.new_meter()
    default = router.chat("reader", meter, timeout_s=10)
    assert default.max_tokens  # type: ignore[attr-defined]  # from the model profile
    capped = router.chat("reader", meter, timeout_s=10, max_output_tokens=10**9)
    assert capped.max_tokens == default.max_tokens  # type: ignore[attr-defined]
