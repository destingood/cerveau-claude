"""Configuration loader: annex B structure and blocking markers (R3, R7)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.config import FEATURES, BlockedFeatureError, ConfigError, find_markers, load_config
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
        "llm.deep",
        "kill_switch",
        "evals.gate.generaliste",
        "compliance.fiscal",
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
    assert "risk_limits.paper.yaml › max_order_pct = A_DEFINIR" in reasons


def test_live_stays_blocked_while_disabled_even_without_markers(config_dir: Path) -> None:
    edit_yaml(config_dir / "live.yaml", lambda d: d.update(broker="paper-broker-test"))
    reasons = load_config(config_dir).blockers("live_trading")
    assert reasons == ["live.yaml › enabled = false (R3)"]


def test_filling_markers_unblocks_the_feature(config_dir: Path) -> None:
    def fill(data: dict) -> None:
        for key, value in data.items():
            if value == "A_DEFINIR":
                data[key] = 1

    edit_yaml(config_dir / "risk_limits.paper.yaml", fill)
    config = load_config(config_dir)
    config.require("paper_trading")  # no longer raises
    assert config.risk_limits_paper.max_order_pct == 1


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


def test_comment_markers_are_reported_but_do_not_block() -> None:
    config = load_config(REPO_ROOT / "config")
    comments = [m for m in config.markers if m.in_comment]
    assert any(m.file == "compliance" for m in comments)


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
