"""Configuration loader: annex B structure and blocking markers (R3, R7)."""

from __future__ import annotations

from datetime import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.config import FEATURES, BlockedFeatureError, ConfigError, find_markers, load_config
from core.config.loader import RESEARCH_BOUNDS
from tests.conftest import REPO_ROOT


def edit_yaml(path: Path, mutate) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_repository_config_is_structurally_valid() -> None:
    config = load_config(REPO_ROOT / "config")
    assert config.digest.startswith("sha256:")


def test_live_is_disabled_with_zero_limits_in_the_repository() -> None:
    live = load_config(REPO_ROOT / "config").live
    assert live.enabled is False
    assert live.limits.model_dump() == {
        "max_order_pct": 0,
        "max_position_pct": 0,
        "max_daily_loss_pct": 0,
        "max_orders_per_day": 0,
    }
    assert live.allow.model_dump() == {
        "leverage": False,
        "short_selling": False,
        "derivatives": False,
    }
    assert live.instruments_whitelist == []


def test_every_marker_dependent_feature_is_blocked_by_default() -> None:
    config = load_config(REPO_ROOT / "config")
    for feature in (
        "paper_trading",
        "live_trading",
        "budgets",
        "approvals",
        "llm.local",
        "kill_switch.data_loss",
        "evals.gate.generaliste",
        "compliance.fiscal",
        "guardrails.pii",
        "finance.historical_stress",
        "finance.benchmark",
        "finance.trading_costs",
        "finance.mean_variance",
        "finance.research",
        "finance.committee",
        "data.openbb",
        "data.yfinance",
    ):
        with pytest.raises(BlockedFeatureError):
            config.require(feature)


def test_features_without_markers_are_available() -> None:
    status = load_config(REPO_ROOT / "config").status()
    assert status.keys() == FEATURES.keys()
    # ccxt is disabled and has no marker: nothing in FEATURES depends on it.
    assert all(isinstance(v, list) for v in status.values())


def test_blocker_messages_name_file_and_path() -> None:
    reasons = load_config(REPO_ROOT / "config").blockers("paper_trading")
    assert "risk_limits.paper.yaml › universe = A_DEFINIR" in reasons


def test_paper_trading_waits_for_the_personal_exclusions() -> None:
    """A marker inside a list blocks too: an empty list would mean no exclusion at all."""
    reasons = load_config(REPO_ROOT / "config").blockers("paper_trading")
    assert "compliance.yaml › exclusions_personnelles[0] = A_DEFINIR" in reasons


def test_live_stays_blocked_while_disabled_even_without_markers(config_dir: Path) -> None:
    edit_yaml(config_dir / "live.yaml", lambda d: d.update(broker="paper-broker-test"))
    reasons = load_config(config_dir).blockers("live_trading")
    assert reasons == ["live.yaml › enabled = false (R3)"]


def test_filling_markers_unblocks_the_feature(config_dir: Path) -> None:
    def fill(data: dict) -> None:
        for key, value in data.items():
            if value == "A_DEFINIR":
                data[key] = ["FICT-A"] if key == "universe" else 1

    edit_yaml(config_dir / "risk_limits.paper.yaml", fill)
    edit_yaml(config_dir / "risk.yaml", lambda d: fill(d["trading_costs"]))
    edit_yaml(config_dir / "compliance.yaml", lambda d: d.update(exclusions_personnelles=[]))
    config = load_config(config_dir)
    config.require("paper_trading")  # no longer raises
    assert config.risk.trading_costs.commission_pct == 1
    assert config.risk_limits_paper.universe == ["FICT-A"]


def test_paper_trading_waits_for_the_fees_and_the_execution_parameters(config_dir: Path) -> None:
    """R10: the gate checks the cash with the fees; the drafter needs its offset (D17)."""
    reasons = load_config(config_dir).blockers("paper_trading")
    assert "risk.yaml › trading_costs.commission_pct = A_DEFINIR" in reasons
    edit_yaml(config_dir / "execution.yaml", lambda d: d.update(limit_offset_pct="A_DEFINIR"))
    assert "execution.yaml › limit_offset_pct = A_DEFINIR" in load_config(config_dir).blockers(
        "paper_trading"
    )


def test_the_kill_switch_target_is_set_and_the_data_loss_timeout_is_not() -> None:
    """ADR-034: 5 s set by Lucas; a continuous data connection does not exist yet (D11)."""
    config = load_config(REPO_ROOT / "config")
    config.require("kill_switch")
    assert config.risk.kill_switch.target_seconds == 5
    assert config.blockers("kill_switch.data_loss") == [
        "risk.yaml › kill_switch.data_loss_timeout_seconds = A_DEFINIR"
    ]


PAPER_PCT = (
    "max_order_pct",
    "max_position_pct",
    "max_sector_pct",
    "max_country_pct",
    "max_currency_pct",
    "max_daily_loss_pct",
    "max_rolling_loss_pct",
    "max_drawdown_pct",
    "limit_price_collar_pct",
)
PAPER_COUNTS = (
    "rolling_loss_sessions",
    "max_orders_per_hour",
    "max_orders_per_day",
    "avg_volume_sessions",
)


@pytest.mark.parametrize("name", PAPER_PCT)
@pytest.mark.parametrize("value", [0, -5, 100.5, 500, float("nan"), float("inf")])
def test_a_paper_percentage_outside_0_to_100_is_refused(
    config_dir: Path, name: str, value: float
) -> None:
    """B156, B164: a limit is a percentage (5 = 5 %), strictly positive and at most 100."""
    edit_yaml(config_dir / "risk_limits.paper.yaml", lambda d: d.update({name: value}))
    with pytest.raises(ConfigError, match=name):
        load_config(config_dir)


@pytest.mark.parametrize("name", PAPER_COUNTS)
@pytest.mark.parametrize("value", [0, -1, 2.5])
def test_a_paper_count_is_a_positive_integer(config_dir: Path, name: str, value: float) -> None:
    edit_yaml(config_dir / "risk_limits.paper.yaml", lambda d: d.update({name: value}))
    with pytest.raises(ConfigError, match=name):
        load_config(config_dir)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("capital_reference_eur", 0),
        ("capital_reference_eur", -10000),
        ("min_avg_daily_volume", 0),
        ("min_avg_daily_volume", -1),
        ("universe", []),
        ("universe", ["FICT-A", "FICT-A"]),
        ("universe", ["fict-a"]),
        ("universe", "FICT-A"),
    ],
)
def test_capital_volume_and_universe_are_bounded(
    config_dir: Path, name: str, value: object
) -> None:
    edit_yaml(config_dir / "risk_limits.paper.yaml", lambda d: d.update({name: value}))
    with pytest.raises(ConfigError, match=name):
        load_config(config_dir)


def test_a_percentage_of_100_is_the_upper_bound(config_dir: Path) -> None:
    edit_yaml(config_dir / "risk_limits.paper.yaml", lambda d: d.update(max_sector_pct=100))
    assert load_config(config_dir).risk_limits_paper.max_sector_pct == 100


@pytest.mark.parametrize("name", ["limit_offset_pct", "max_participation_pct"])
@pytest.mark.parametrize("value", [0, -0.5, 101])
def test_execution_percentages_are_bounded(config_dir: Path, name: str, value: float) -> None:
    edit_yaml(config_dir / "execution.yaml", lambda d: d.update({name: value}))
    with pytest.raises(ConfigError, match=name):
        load_config(config_dir)


def test_the_limit_offset_stays_within_the_price_collar(config_dir: Path) -> None:
    """D17: a drafted limit price the Risk Gate's collar would refuse is a configuration error."""
    edit_yaml(config_dir / "risk_limits.paper.yaml", lambda d: d.update(limit_price_collar_pct=2))
    edit_yaml(config_dir / "execution.yaml", lambda d: d.update(limit_offset_pct=2))
    load_config(config_dir)  # equal to the collar: allowed
    edit_yaml(config_dir / "execution.yaml", lambda d: d.update(limit_offset_pct=2.5))
    with pytest.raises(ConfigError, match=r"limit_offset_pct : 2\.5 % dépasse la bande de prix"):
        load_config(config_dir)


@pytest.mark.parametrize("value", [0, -5, float("nan")])
def test_the_kill_switch_target_is_strictly_positive(config_dir: Path, value: float) -> None:
    edit_yaml(config_dir / "risk.yaml", lambda d: d["kill_switch"].update(target_seconds=value))
    with pytest.raises(ConfigError, match="target_seconds"):
        load_config(config_dir)


def test_unknown_marker_spelling_is_a_structural_error(config_dir: Path) -> None:
    edit_yaml(config_dir / "risk_limits.paper.yaml", lambda d: d.update(max_order_pct="A_DEFNIR"))
    with pytest.raises(ConfigError, match="max_order_pct"):
        load_config(config_dir)


def test_unknown_key_is_refused(config_dir: Path) -> None:
    edit_yaml(config_dir / "live.yaml", lambda d: d.update(withdrawals=True))
    with pytest.raises(ConfigError, match="withdrawals"):
        load_config(config_dir)


def test_negative_live_limit_is_refused(config_dir: Path) -> None:
    edit_yaml(config_dir / "live.yaml", lambda d: d["limits"].update(max_order_pct=-1))
    with pytest.raises(ConfigError, match="max_order_pct"):
        load_config(config_dir)


def test_missing_file_is_reported(config_dir: Path) -> None:
    (config_dir / "budgets.yaml").unlink()
    with pytest.raises(ConfigError, match=r"budgets\.yaml : fichier absent"):
        load_config(config_dir)


def test_invalid_yaml_is_reported(config_dir: Path) -> None:
    (config_dir / "evals.yaml").write_text("thresholds: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML invalide"):
        load_config(config_dir)


def test_autonomy_level_above_max_is_refused(config_dir: Path) -> None:
    edit_yaml(
        config_dir / "autonomy.yaml", lambda d: d["domains"]["generaliste"].update(level="N3")
    )
    with pytest.raises(ConfigError, match="max_level"):
        load_config(config_dir)


def test_incomplete_autonomy_matrix_is_refused(config_dir: Path) -> None:
    edit_yaml(config_dir / "autonomy.yaml", lambda d: d["matrix"]["FINANCIERE"].pop("N4"))
    with pytest.raises(ConfigError, match="FINANCIERE/N4"):
        load_config(config_dir)


def test_unknown_matrix_decision_is_refused(config_dir: Path) -> None:
    edit_yaml(
        config_dir / "autonomy.yaml", lambda d: d["matrix"]["FINANCIERE"].update(N0="auto_total")
    )
    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_comment_markers_are_reported_but_do_not_block(config_dir: Path) -> None:
    path = config_dir / "compliance.yaml"
    path.write_text(
        path.read_text(encoding="utf-8") + "# A_VERIFIER : note de relecture\n", encoding="utf-8"
    )
    config = load_config(config_dir)
    comments = [m for m in config.markers if m.in_comment]
    assert [m.file for m in comments] == ["compliance"]
    assert not any(str(comments[0]) in config.blockers(feature) for feature in FEATURES)


def test_find_markers_walks_nested_lists_and_dicts() -> None:
    hits = find_markers("models", {"a": [{"b": "A_VERIFIER"}], "c": "ok", "d": "A_DEFINIR"})
    assert sorted(h.path for h in hits) == ["a[0].b", "d"]


def test_digest_changes_when_a_file_changes(config_dir: Path) -> None:
    before = load_config(config_dir).digest
    edit_yaml(config_dir / "budgets.yaml", lambda d: d["per_request"].update(max_tool_calls=10))
    assert load_config(config_dir).digest != before


def test_unknown_feature_raises_key_error() -> None:
    with pytest.raises(KeyError):
        load_config(REPO_ROOT / "config").require("nope")


# --- phase 1: verified models, pricing, budgets, guardrails ----------------------------------


def test_verified_anthropic_tiers_and_costs_are_available() -> None:
    config = load_config(REPO_ROOT / "config")
    for feature in ("llm.deep", "llm.standard", "llm.fast", "costs"):
        config.require(feature)
    assert all(
        tier.status == "verifie" and tier.verified_on and tier.source
        for name, tier in config.models.tiers.items()
        if name != "local"
    )


def test_phase_1_decisions_are_recorded() -> None:
    config = load_config(REPO_ROOT / "config")
    assert config.budgets.per_request.max_tokens == 150_000  # D4
    assert config.budgets.on_exceeded == ["refuse_new_requests"]  # D9
    assert config.evals.thresholds.generaliste_golden_min_score == 0.80  # D6
    assert config.pricing.fx.usd_per_eur == Decimal("1.1253")  # D5
    assert config.budgets.llm_budget_eur.daily == "A_DEFINIR"  # D3: not provided


def test_verified_status_requires_date_and_source(config_dir: Path) -> None:
    edit_yaml(config_dir / "models.yaml", lambda d: d["tiers"]["deep"].pop("source"))
    with pytest.raises(ConfigError, match="verified_on and source"):
        load_config(config_dir)


def test_every_anthropic_model_needs_a_price(config_dir: Path) -> None:
    edit_yaml(
        config_dir / "pricing.yaml", lambda d: d["anthropic"]["models"].pop("claude-opus-5-5")
    )
    with pytest.raises(ConfigError, match="prix absent pour claude-opus-5-5"):
        load_config(config_dir)


def test_prices_are_exact_decimals() -> None:
    haiku = load_config(REPO_ROOT / "config").pricing.anthropic.models["claude-haiku-5-5"]
    assert [tier.max_prompt_tokens for tier in haiku.tiers] == [100_000, None]
    assert haiku.tiers[0].cache_write_5m == Decimal("0.125")


@pytest.mark.parametrize(
    "tiers",
    [
        [
            {
                "input": "1",
                "cache_write_5m": "1",
                "cache_write_1h": "1",
                "cache_read": "1",
                "output": "1",
                "max_prompt_tokens": 10,
            }
        ],
        [
            {
                "input": "1",
                "cache_write_5m": "1",
                "cache_write_1h": "1",
                "cache_read": "1",
                "output": "1",
            }
        ]
        * 2,
    ],
)
def test_price_tiers_must_end_unbounded_and_be_unique(config_dir: Path, tiers: list) -> None:
    edit_yaml(
        config_dir / "pricing.yaml",
        lambda d: d["anthropic"]["models"]["claude-opus-5-5"].update(tiers=tiers),
    )
    with pytest.raises(ConfigError, match="price tier"):
        load_config(config_dir)


def test_negative_price_is_refused(config_dir: Path) -> None:
    def mutate(d: dict) -> None:
        d["anthropic"]["models"]["claude-opus-5-5"]["tiers"][0]["output"] = "-1"

    edit_yaml(config_dir / "pricing.yaml", mutate)
    with pytest.raises(ConfigError, match="output"):
        load_config(config_dir)


def test_unknown_price_marker_blocks_costs(config_dir: Path) -> None:
    edit_yaml(config_dir / "pricing.yaml", lambda d: d["fx"].update(usd_per_eur="A_VERIFIER"))
    reasons = load_config(config_dir).blockers("costs")
    assert reasons == ["pricing.yaml › fx.usd_per_eur = A_VERIFIER"]


@pytest.mark.parametrize("alerts", [[80, 50, 100], [50, 80], [50, 50, 100], [0, 100]])
def test_budget_alerts_must_increase_and_end_at_100(config_dir: Path, alerts: list) -> None:
    edit_yaml(config_dir / "budgets.yaml", lambda d: d.update(alerts_pct=alerts))
    with pytest.raises(ConfigError, match="alerts_pct"):
        load_config(config_dir)


def test_unknown_budget_overrun_action_is_refused(config_dir: Path) -> None:
    edit_yaml(config_dir / "budgets.yaml", lambda d: d.update(on_exceeded=["keep_spending"]))
    with pytest.raises(ConfigError, match="on_exceeded"):
        load_config(config_dir)


def test_pii_threshold_unblocks_guardrails_once_decided(config_dir: Path) -> None:
    edit_yaml(config_dir / "guardrails.yaml", lambda d: d["pii"].update(score_threshold=0.5))
    load_config(config_dir).require("guardrails.pii")


@pytest.mark.parametrize("value", [1.5, -0.1])
def test_pii_threshold_must_be_a_probability(config_dir: Path, value: float) -> None:
    edit_yaml(config_dir / "guardrails.yaml", lambda d: d["pii"].update(score_threshold=value))
    with pytest.raises(ConfigError, match="score_threshold"):
        load_config(config_dir)


# --- phase 2: finance pack parameters ---------------------------------------------------------


def test_phase_2_decisions_are_recorded() -> None:
    config = load_config(REPO_ROOT / "config")
    market = config.risk.market_risk
    assert market.var.confidence_levels == [0.95, 0.99]  # D7
    assert market.var.horizons_sessions == [1, 10]  # D7
    assert market.var.window_sessions == 500  # D7
    assert market.annualisation_sessions == 252  # D7
    assert market.risk_free == "estr"  # D7
    assert market.cross_check.rel_tolerance == 1e-9  # D11
    assert config.data_sources.quality.max_staleness_sessions == 1  # D12
    assert config.data_sources.quality.min_quality_score_above_N1 == 0.90  # D12
    assert config.evals.thresholds.finance_golden_min_score == 0.85  # D17
    assert config.risk.trading_costs.commission_pct == "A_DEFINIR"  # D13: not provided


def test_the_finance_n0_to_n1_promotion_is_recorded_but_never_applied() -> None:
    config = load_config(REPO_ROOT / "config")
    config.require("promotion.finance.N0_to_N1")
    rule = config.autonomy.promotion.finance.N0_to_N1
    assert rule.golden_min_score == config.evals.thresholds.finance_golden_min_score  # D16, D17
    assert (rule.r1_to_r5_violations_max, rule.measured_in) == (0, "live")
    assert rule.manual_signature == "required"
    assert config.autonomy.domains["finance"].level == "N0"  # Lucas promotes, by hand


def test_the_promotion_score_cannot_go_below_the_golden_gate(config_dir: Path) -> None:
    edit_yaml(
        config_dir / "autonomy.yaml",
        lambda d: d["promotion"]["finance"]["N0_to_N1"].update(golden_min_score=0.80),
    )
    with pytest.raises(ConfigError, match="sous le seuil du golden set Finance"):
        load_config(config_dir)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("r1_to_r5_violations_max", 1),
        ("measured_in", "offline"),
        ("manual_signature", "optional"),
        ("golden_min_score", 1.2),
    ],
)
def test_the_promotion_rule_cannot_be_loosened(config_dir: Path, field: str, value: object) -> None:
    edit_yaml(
        config_dir / "autonomy.yaml",
        lambda d: d["promotion"]["finance"]["N0_to_N1"].update({field: value}),
    )
    with pytest.raises(ConfigError, match=f"N0_to_N1.{field}"):
        load_config(config_dir)


def test_a_missing_promotion_score_blocks_the_promotion(config_dir: Path) -> None:
    edit_yaml(
        config_dir / "autonomy.yaml",
        lambda d: d["promotion"]["finance"]["N0_to_N1"].update(golden_min_score="A_DEFINIR"),
    )
    with pytest.raises(BlockedFeatureError):
        load_config(config_dir).require("promotion.finance.N0_to_N1")


@pytest.mark.parametrize(
    ("field", "value"),
    [("golden_min_score", True), ("r1_to_r5_violations_max", False)],
)
def test_the_promotion_rule_is_strictly_typed(config_dir: Path, field: str, value: object) -> None:
    edit_yaml(
        config_dir / "autonomy.yaml",
        lambda d: d["promotion"]["finance"]["N0_to_N1"].update({field: value}),
    )
    with pytest.raises(ConfigError, match=f"N0_to_N1.{field}"):
        load_config(config_dir)


def test_the_promotion_rule_cannot_be_dropped(config_dir: Path) -> None:
    edit_yaml(config_dir / "autonomy.yaml", lambda d: d["promotion"]["finance"].pop("N0_to_N1"))
    with pytest.raises(ConfigError, match="N0_to_N1"):
        load_config(config_dir)


def test_the_finance_n1_to_n2_promotion_adds_the_execution_red_team() -> None:
    config = load_config(REPO_ROOT / "config")
    config.require("promotion.finance.N1_to_N2")
    rule = config.autonomy.promotion.finance.N1_to_N2
    first = config.autonomy.promotion.finance.N0_to_N1
    assert rule.golden_min_score == first.golden_min_score  # D9: the conditions of N0 → N1
    assert (rule.r1_to_r5_violations_max, rule.measured_in) == (0, "live")
    assert (rule.redteam_group, rule.redteam_violations_max) == ("injection_execution", 0)
    assert rule.manual_signature == "required"
    assert config.autonomy.domains["finance"].level == "N0"  # Lucas promotes, by hand


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("r1_to_r5_violations_max", 1),
        ("redteam_violations_max", 1),
        ("redteam_violations_max", False),
        ("redteam_group", "finance_chiffres"),
        ("measured_in", "offline"),
        ("manual_signature", "optional"),
        ("golden_min_score", 1.2),
    ],
)
def test_the_n1_to_n2_rule_cannot_be_loosened(config_dir: Path, field: str, value: object) -> None:
    edit_yaml(
        config_dir / "autonomy.yaml",
        lambda d: d["promotion"]["finance"]["N1_to_N2"].update({field: value}),
    )
    with pytest.raises(ConfigError, match=f"N1_to_N2.{field}"):
        load_config(config_dir)


@pytest.mark.parametrize(
    "field",
    [
        "golden_min_score",
        "r1_to_r5_violations_max",
        "redteam_group",
        "redteam_violations_max",
        "measured_in",
        "manual_signature",
    ],
)
def test_an_incomplete_n1_to_n2_rule_is_refused(config_dir: Path, field: str) -> None:
    edit_yaml(
        config_dir / "autonomy.yaml", lambda d: d["promotion"]["finance"]["N1_to_N2"].pop(field)
    )
    with pytest.raises(ConfigError, match=f"N1_to_N2.{field}"):
        load_config(config_dir)


def test_the_n1_to_n2_rule_cannot_be_dropped(config_dir: Path) -> None:
    edit_yaml(config_dir / "autonomy.yaml", lambda d: d["promotion"]["finance"].pop("N1_to_N2"))
    with pytest.raises(ConfigError, match="N1_to_N2"):
        load_config(config_dir)


def test_the_n1_to_n2_score_cannot_go_below_the_golden_gate(config_dir: Path) -> None:
    edit_yaml(
        config_dir / "autonomy.yaml",
        lambda d: d["promotion"]["finance"]["N1_to_N2"].update(golden_min_score=0.80),
    )
    with pytest.raises(ConfigError, match=r"N1_to_N2\.golden_min_score : 0\.8 est sous le seuil"):
        load_config(config_dir)


def test_the_n1_to_n2_score_cannot_go_below_the_n0_to_n1_score(config_dir: Path) -> None:
    def edit(d: dict[str, Any]) -> None:
        d["promotion"]["finance"]["N0_to_N1"]["golden_min_score"] = 0.95
        d["promotion"]["finance"]["N1_to_N2"]["golden_min_score"] = 0.90

    edit_yaml(config_dir / "autonomy.yaml", edit)
    with pytest.raises(ConfigError, match=r"0\.9 est sous celui de N0_to_N1 \(0\.95\)"):
        load_config(config_dir)


def test_a_missing_n1_to_n2_score_blocks_only_that_promotion(config_dir: Path) -> None:
    edit_yaml(
        config_dir / "autonomy.yaml",
        lambda d: d["promotion"]["finance"]["N1_to_N2"].update(golden_min_score="A_DEFINIR"),
    )
    config = load_config(config_dir)
    config.require("promotion.finance.N0_to_N1")
    with pytest.raises(BlockedFeatureError):
        config.require("promotion.finance.N1_to_N2")


def test_a_golden_gate_raised_above_the_promotion_score_is_refused(config_dir: Path) -> None:
    edit_yaml(
        config_dir / "evals.yaml",
        lambda d: d["thresholds"].update(finance_golden_min_score=0.90),
    )
    with pytest.raises(ConfigError, match="sous le seuil du golden set Finance"):
        load_config(config_dir)


def test_a_missing_golden_gate_blocks_the_promotion(config_dir: Path) -> None:
    edit_yaml(
        config_dir / "evals.yaml",
        lambda d: d["thresholds"].update(finance_golden_min_score="A_DEFINIR"),
    )
    with pytest.raises(BlockedFeatureError):
        load_config(config_dir).require("promotion.finance.N0_to_N1")


@pytest.mark.parametrize("value", [float("nan"), -1.0, 1.5, True])
@pytest.mark.parametrize("field", ["generaliste_golden_min_score", "finance_golden_min_score"])
def test_a_golden_gate_is_a_score_in_0_1(config_dir: Path, field: str, value: object) -> None:
    edit_yaml(config_dir / "evals.yaml", lambda d: d["thresholds"].update({field: value}))
    with pytest.raises(ConfigError, match=field):
        load_config(config_dir)


@pytest.mark.parametrize(
    ("field", "value"),
    [("generaliste_golden_min_score", 0.79), ("finance_golden_min_score", 0.84)],
)
def test_the_golden_gates_cannot_go_below_their_floor(
    config_dir: Path, field: str, value: float
) -> None:
    def lower(d: dict[str, Any]) -> None:
        d["thresholds"][field] = value

    edit_yaml(config_dir / "evals.yaml", lower)
    if field == "finance_golden_min_score":  # lowered together: the cross check alone would pass
        edit_yaml(
            config_dir / "autonomy.yaml",
            lambda d: d["promotion"]["finance"]["N0_to_N1"].update(golden_min_score=value),
        )
    with pytest.raises(ConfigError, match="sous le plancher"):
        load_config(config_dir)


def test_every_behaviour_suite_must_fully_pass(config_dir: Path) -> None:
    config = load_config(REPO_ROOT / "config")
    assert config.evals.thresholds.behavior_suites_R1_to_R5_pass_rate == 1.0  # D16: 0 violation
    edit_yaml(
        config_dir / "evals.yaml",
        lambda d: d["thresholds"].update(behavior_suites_R1_to_R5_pass_rate=0.5),
    )
    with pytest.raises(ConfigError, match="violations R1-R5"):
        load_config(config_dir)


def test_finance_read_only_features_are_available() -> None:
    config = load_config(REPO_ROOT / "config")
    for feature in ("finance.market_risk", "finance.performance", "data.ecb"):
        config.require(feature)
    assert config.data_sources.sources["yfinance"].enabled is False  # R15, ADR-013


def test_the_quality_gate_waits_for_the_two_check_cut_offs() -> None:
    blockers = load_config(REPO_ROOT / "config").blockers("data.quality_gate")
    assert len(blockers) == 2  # ADR-016: proposed, not decided by Lucas
    assert all("outlier_robust_z" in b or "max_unexplained_move" in b for b in blockers)


@pytest.mark.parametrize("value", [0.5, 0.0])
def test_the_move_cut_off_always_catches_a_three_for_two_split(
    config_dir: Path, value: float
) -> None:
    edit_yaml(
        config_dir / "data_sources.yaml",
        lambda d: d["quality"].update(max_unexplained_move=value),
    )
    with pytest.raises(ConfigError, match="max_unexplained_move"):
        load_config(config_dir)


def test_disabled_source_blocks_its_feature_without_markers(config_dir: Path) -> None:
    edit_yaml(config_dir / "data_sources.yaml", lambda d: d["sources"]["ecb"].update(enabled=False))
    reasons = load_config(config_dir).blockers("data.ecb")
    assert reasons == ["data_sources.yaml › sources.ecb.enabled = false"]


def test_missing_source_blocks_its_feature(config_dir: Path) -> None:
    edit_yaml(config_dir / "data_sources.yaml", lambda d: d["sources"].pop("ecb"))
    reasons = load_config(config_dir).blockers("data.ecb")
    assert reasons == ["data_sources.yaml › sources.ecb absente"]


@pytest.mark.parametrize("value", [1.5, -0.1])
def test_quality_score_must_be_a_probability(config_dir: Path, value: float) -> None:
    edit_yaml(
        config_dir / "data_sources.yaml",
        lambda d: d["quality"].update(min_quality_score_above_N1=value),
    )
    with pytest.raises(ConfigError, match="min_quality_score_above_N1"):
        load_config(config_dir)


@pytest.mark.parametrize(("field", "value"), [("confidence_levels", [1.0]), ("seed", -1)])
def test_invalid_var_parameters_are_refused(config_dir: Path, field: str, value: object) -> None:
    edit_yaml(config_dir / "risk.yaml", lambda d: d["market_risk"]["var"].update({field: value}))
    with pytest.raises(ConfigError, match=field):
        load_config(config_dir)


def test_equity_shock_cannot_wipe_out_more_than_the_position(config_dir: Path) -> None:
    edit_yaml(
        config_dir / "risk.yaml",
        lambda d: d["market_risk"]["hypothetical_stress"].update(equity_shock=-1.5),
    )
    with pytest.raises(ConfigError, match="equity_shock"):
        load_config(config_dir)


def test_trading_costs_unblock_as_exact_decimals_once_decided(config_dir: Path) -> None:
    costs = {
        "commission_pct": "0.1",
        "min_commission_eur": "1.99",
        "slippage_bps": "5",
        "fx_conversion_bps": "25",
    }
    edit_yaml(config_dir / "risk.yaml", lambda d: d["trading_costs"].update(costs))
    config = load_config(config_dir)
    config.require("finance.trading_costs")
    assert config.risk.trading_costs.min_commission_eur == Decimal("1.99")


def test_mean_variance_waits_for_a_positive_risk_aversion(config_dir: Path) -> None:
    edit_yaml(config_dir / "risk.yaml", lambda d: d["optimization"].update(risk_aversion=0))
    with pytest.raises(ConfigError):
        load_config(config_dir)
    edit_yaml(config_dir / "risk.yaml", lambda d: d["optimization"].update(risk_aversion=4))
    config = load_config(config_dir)
    config.require("finance.mean_variance")
    assert config.risk.optimization.risk_aversion == 4.0


def test_historical_stress_unblocks_once_dates_and_sources_are_checked(config_dir: Path) -> None:
    def fill(d: dict) -> None:
        for window in d["market_risk"]["historical_stress"].values():
            window.update(start="2020-02-19", end="2020-03-23", source="test")

    edit_yaml(config_dir / "risk.yaml", fill)
    load_config(config_dir).require("finance.historical_stress")


# --- phase 3: research protocol and investment committee ---------------------------------------


def test_phase_3_decisions_are_recorded() -> None:
    config = load_config(REPO_ROOT / "config")
    research = config.research
    assert research.execution.decision_cutoff_utc == time(21, 0)  # D6
    assert research.split.development_fraction == 0.7  # D7
    assert research.split.embargo_sessions == 5  # D7
    assert (research.walk_forward.scheme, research.walk_forward.blocks) == ("anchored", 5)  # D8
    assert research.pbo.partitions == 16  # ADR-026
    assert research.gates.model_dump() == {  # D9
        "dsr_min": 0.95,
        "pbo_max": 0.5,
        "final_to_walk_forward_sharpe_min": 0.5,
        "benchmark_min_sessions": 252,
        "cost_stress_multiplier": 2,
    }
    assert research.cross_check.nautilus_rel_tolerance == 1e-6  # D12
    assert research.cross_check.vectorbt_rel_tolerance == 1e-9  # D12
    assert config.committee.max_debate_rounds == 2  # D17
    tiers = config.committee.finance.tiers
    assert tiers["gestionnaire"] == "deep"  # D17
    assert {tier for role, tier in tiers.items() if role != "gestionnaire"} == {"standard"}
    # D18: proposed to Lucas, not decided; no real committee session before his answer.
    assert set(config.budgets.per_committee.model_dump().values()) == {"A_DEFINIR"}


LOOSER = {
    "gates.dsr_min": 0.9,
    "gates.pbo_max": 0.6,
    "gates.final_to_walk_forward_sharpe_min": 0.4,
    "gates.benchmark_min_sessions": 251,
    "gates.cost_stress_multiplier": 1.5,
    "split.embargo_sessions": 4,
    "cross_check.nautilus_rel_tolerance": 1e-5,
    "cross_check.vectorbt_rel_tolerance": 1e-8,
}


def test_every_research_bound_has_a_looser_case() -> None:
    assert LOOSER.keys() == RESEARCH_BOUNDS.keys()


@pytest.mark.parametrize(("dotted", "value"), LOOSER.items())
def test_the_research_gates_cannot_be_loosened(config_dir: Path, dotted: str, value: float) -> None:
    section, name = dotted.split(".")
    edit_yaml(config_dir / "research.yaml", lambda d: d[section].update({name: value}))
    with pytest.raises(ConfigError, match=r"plancher|plafond") as caught:
        load_config(config_dir)
    assert dotted in str(caught.value)


def test_the_research_gates_can_be_tightened(config_dir: Path) -> None:
    def tighten(d: dict[str, Any]) -> None:
        d["gates"].update(dsr_min=0.99, pbo_max=0.2, cost_stress_multiplier=3)
        d["split"].update(embargo_sessions=10)
        d["cross_check"].update(nautilus_rel_tolerance=1e-8)

    edit_yaml(config_dir / "research.yaml", tighten)
    assert load_config(config_dir).research.gates.pbo_max == 0.2


@pytest.mark.parametrize(
    "line",
    [
        "decision_cutoff_utc: 21:00",  # YAML 1.1 base 60: the integer 1260, never 00:21
        'decision_cutoff_utc: "21:00+02:00"',
        'decision_cutoff_utc: "25:00"',
    ],
)
def test_the_decision_cutoff_is_a_quoted_naive_utc_time(config_dir: Path, line: str) -> None:
    path = config_dir / "research.yaml"
    text = path.read_text(encoding="utf-8")
    assert 'decision_cutoff_utc: "21:00"' in text
    path.write_text(text.replace('decision_cutoff_utc: "21:00"', line), encoding="utf-8")
    with pytest.raises(ConfigError, match="decision_cutoff_utc"):
        load_config(config_dir)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("pbo", "partitions", 15),
        ("pbo", "partitions", 2),
        ("walk_forward", "blocks", 1),
        ("walk_forward", "scheme", "rolling"),
        ("split", "development_fraction", 1.0),
        ("copilot", "max_window_sessions", 0),
    ],
)
def test_invalid_research_parameters_are_refused(
    config_dir: Path, section: str, field: str, value: object
) -> None:
    edit_yaml(config_dir / "research.yaml", lambda d: d[section].update({field: value}))
    with pytest.raises(ConfigError, match=r"research\.yaml"):
        load_config(config_dir)


def test_research_on_real_data_waits_for_the_trading_costs(config_dir: Path) -> None:
    reasons = load_config(REPO_ROOT / "config").blockers("finance.research")
    assert reasons and all("trading_costs" in reason for reason in reasons)
    costs = {
        "commission_pct": "0.1",
        "min_commission_eur": "1.99",
        "slippage_bps": "5",
        "fx_conversion_bps": "25",
    }
    edit_yaml(config_dir / "risk.yaml", lambda d: d["trading_costs"].update(costs))
    load_config(config_dir).require("finance.research")


def _decide_committee_budgets(config_dir: Path) -> None:
    def fill(d: dict[str, Any]) -> None:
        d["llm_budget_eur"].update(daily="2", monthly="40")
        d["per_committee"].update(max_tokens=400_000, max_seconds=600, max_tool_calls=40)

    edit_yaml(config_dir / "budgets.yaml", fill)


def test_the_committee_waits_for_the_budgets(config_dir: Path) -> None:
    reasons = load_config(REPO_ROOT / "config").blockers("finance.committee")
    assert any("per_committee" in reason for reason in reasons)
    assert any("llm_budget_eur" in reason for reason in reasons)
    _decide_committee_budgets(config_dir)
    load_config(config_dir).require("finance.committee")


def test_the_committee_is_blocked_by_an_undecided_model_tier(config_dir: Path) -> None:
    _decide_committee_budgets(config_dir)
    edit_yaml(
        config_dir / "committee.yaml", lambda d: d["finance"]["tiers"].update(defenseur="local")
    )
    reasons = load_config(config_dir).blockers("finance.committee")
    assert reasons and all("tiers.local" in reason for reason in reasons)


def test_a_committee_tier_must_exist_in_models(config_dir: Path) -> None:
    edit_yaml(config_dir / "models.yaml", lambda d: d["tiers"].pop("local"))
    edit_yaml(
        config_dir / "committee.yaml", lambda d: d["finance"]["tiers"].update(defenseur="local")
    )
    with pytest.raises(ConfigError, match=r"absent de models\.yaml"):
        load_config(config_dir)


@pytest.mark.parametrize(
    ("mutate", "where"),
    [
        (lambda d: d.update(max_debate_rounds=0), "max_debate_rounds"),
        (lambda d: d["finance"]["tiers"].update(defenseur="turbo"), "defenseur"),
        (lambda d: d["finance"]["tiers"].update({"Défenseur": "standard"}), "tiers"),
        (lambda d: d["finance"].update(tiers={}), "tiers"),
    ],
)
def test_invalid_committee_parameters_are_refused(config_dir: Path, mutate, where: str) -> None:
    edit_yaml(config_dir / "committee.yaml", mutate)
    with pytest.raises(ConfigError, match=where):
        load_config(config_dir)


@pytest.mark.parametrize("field", ["max_tokens", "max_seconds", "max_tool_calls"])
def test_committee_budget_limits_are_positive(config_dir: Path, field: str) -> None:
    edit_yaml(config_dir / "budgets.yaml", lambda d: d["per_committee"].update({field: 0}))
    with pytest.raises(ConfigError, match="per_committee"):
        load_config(config_dir)


def test_approval_and_promotion_values_validated_by_lucas() -> None:
    """D3 and D17 of the phase 5 plan, set by Lucas on 21/10/2026."""
    autonomy = load_config(REPO_ROOT / "config").autonomy
    approval = autonomy.approval
    assert (approval.expiry_minutes, approval.max_code_attempts) == (10, 3)
    assert (approval.lockout_failures, approval.lockout_window_minutes) == (5, 15)
    promotion = autonomy.promotion.finance.N2_to_N3
    assert (promotion.paper_weeks_min, promotion.decisions_min) == (13, 30)
    assert promotion.max_paper_drawdown_pct == 10


@pytest.mark.parametrize(
    "feature", ["approvals", "interfaces.api", "interfaces.discord", "notify.ntfy"]
)
def test_interfaces_stay_blocked_until_lucas_sets_them(feature: str) -> None:
    reasons = load_config(REPO_ROOT / "config").blockers(feature)
    assert reasons
    assert all(reason.startswith("interfaces.yaml") for reason in reasons)


@pytest.mark.parametrize(
    ("mutate", "where"),
    [
        (lambda d: d.update(one_time_code=False), "one_time_code"),
        (lambda d: d.update(expiry_minutes=0), "expiry_minutes"),
        (lambda d: d.update(expiry_minutes=61), "expiry_minutes"),
        (lambda d: d.update(expiry_minutes=10.5), "expiry_minutes"),
        (lambda d: d.update(max_code_attempts=0), "max_code_attempts"),
        (lambda d: d.update(max_code_attempts=6), "max_code_attempts"),
        (lambda d: d.update(lockout_failures=0), "lockout_failures"),
        (lambda d: d.update(lockout_window_minutes=0), "lockout_window_minutes"),
        (lambda d: d.update(channel="email"), "channel"),
    ],
)
def test_invalid_approval_parameters_are_refused(config_dir: Path, mutate, where: str) -> None:
    edit_yaml(config_dir / "autonomy.yaml", lambda d: mutate(d["approval"]))
    with pytest.raises(ConfigError, match=where):
        load_config(config_dir)


@pytest.mark.parametrize(
    ("mutate", "where"),
    [
        (lambda d: d.update(paper_weeks_min=0), "paper_weeks_min"),
        (lambda d: d.update(decisions_min=-1), "decisions_min"),
        (lambda d: d.update(max_paper_drawdown_pct=0), "max_paper_drawdown_pct"),
        (lambda d: d.update(max_paper_drawdown_pct=101), "max_paper_drawdown_pct"),
        (lambda d: d.update(max_paper_drawdown_pct=float("nan")), "max_paper_drawdown_pct"),
    ],
)
def test_invalid_n2_to_n3_thresholds_are_refused(config_dir: Path, mutate, where: str) -> None:
    edit_yaml(config_dir / "autonomy.yaml", lambda d: mutate(d["promotion"]["finance"]["N2_to_N3"]))
    with pytest.raises(ConfigError, match=where):
        load_config(config_dir)


def test_valid_interfaces_unblock_the_api_and_the_bot(config_dir: Path) -> None:
    def fill(d: dict[str, Any]) -> None:
        d["discord"]["owner_user_id"] = "123456789012345678"
        d["api"]["port"] = 8765
        d["ntfy"]["server"] = "https://ntfy.example"

    edit_yaml(config_dir / "interfaces.yaml", fill)
    config = load_config(config_dir)
    for feature in ("approvals", "interfaces.api", "interfaces.discord", "notify.ntfy"):
        assert config.blockers(feature) == []
    assert config.interfaces.api.host == "127.0.0.1"


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("api", "host", "0.0.0.0"),  # noqa: S104 - the value under test is refused
        ("api", "host", "localhost"),
        ("api", "port", 80),
        ("api", "port", 70000),
        ("api", "port", "8765"),
        ("discord", "owner_user_id", 123456789012345678),  # unquoted: lost in JavaScript
        ("discord", "owner_user_id", "12345"),
        ("discord", "owner_user_id", "lucas"),
        ("ntfy", "server", "http://ntfy.sh"),
        ("ntfy", "server", "https://ntfy.sh/"),
        ("ntfy", "server", "https://ntfy.sh/sujet"),
        ("ntfy", "timeout_seconds", 0),
        ("ntfy", "timeout_seconds", 6),
    ],
)
def test_invalid_interface_settings_are_refused(
    config_dir: Path, section: str, field: str, value: Any
) -> None:
    edit_yaml(config_dir / "interfaces.yaml", lambda d: d[section].update({field: value}))
    with pytest.raises(ConfigError, match=field):
        load_config(config_dir)


def test_interfaces_refuse_a_secret_field(config_dir: Path) -> None:
    """Tokens live in environment variables (R6): the schema has no place for one."""
    edit_yaml(config_dir / "interfaces.yaml", lambda d: d["ntfy"].update({"token": "x"}))
    with pytest.raises(ConfigError, match="token"):
        load_config(config_dir)
