"""B7: Claude Code may call only the MCP tools listed in .claude/hooks/guard_mcp.py."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.audit import verify
from tests.conftest import REPO_ROOT
from tests.hooks.hookutil import load_hook, run_hook

guard_mcp = load_hook("guard_mcp")

LISTED = [
    "mcp__ccd_turn__update_plan",
    "mcp__ccd_turn__wrap_up",
    "mcp__ccd_session__mark_chapter",
    "mcp__ccd_session__start_session",
    "mcp__ccd_view__show_pane",
    "mcp__visualize__show_widget",
    "mcp__Claude_Browser__get_page_text",
]
UNLISTED = [
    "mcp__terminal__run_in_terminal",  # would bypass guard_shell
    "mcp__terminal__read_terminal",
    "mcp__Claude_Browser__computer",  # clicks and typing
    "mcp__Claude_Browser__browser_batch",  # may carry clicks
    "mcp__Claude_Browser__form_input",
    "mcp__Claude_Browser__javascript_tool",
    "mcp__Claude_Browser__preview_start",  # starts a command from launch.json
    "mcp__claude-in-chrome__navigate",  # Lucas's own browser and sessions
    "mcp__computer-use__left_click",
    "mcp__ccd_pr__set_auto_merge",  # a merge into main
    "mcp__ccd_session__move_to_cloud",
    "mcp__ccd_session_mgmt__delete_session",
    "mcp__ccd_connectors__set_session_connector_enabled",
    "mcp__ccd_settings__set_setting",
    "mcp__ccd_directory__change_directory",
    "mcp__scheduled-tasks__create_scheduled_task",
    "mcp__e33feaee-cc8d-4520-8cd2-c71f29a23da2__send_message",  # a mail connector
    "mcp__plugin_pdf-viewer_pdf__display_pdf",
    "mcp__ccd_turn",  # not a tool
    "mcp__ccd_turnx__update_plan",
    "mcp__CCD_TURN__update_plan",  # names are case-sensitive
    "mcp__",
]


@pytest.mark.parametrize("tool_name", LISTED)
def test_listed_tools_pass(tool_name: str) -> None:
    assert guard_mcp.decide(tool_name, frozenset()) is None


@pytest.mark.parametrize("tool_name", UNLISTED)
def test_unlisted_tools_are_refused(tool_name: str) -> None:
    reason = guard_mcp.decide(tool_name, frozenset())
    assert reason is not None and "B7" in reason and tool_name in reason


@pytest.mark.parametrize("server", ["ccd_turn", "ccd.turn"])
def test_a_project_server_never_borrows_a_listed_name(server: str) -> None:
    reason = guard_mcp.decide("mcp__ccd_turn__update_plan", frozenset({server}))
    assert reason is not None and ".mcp.json" in reason


def test_a_project_server_does_not_shadow_a_longer_server_name() -> None:
    assert guard_mcp.decide("mcp__ccd_turn__wrap_up", frozenset({"ccd"})) is None


def test_built_in_tools_are_left_to_the_other_hooks() -> None:
    assert guard_mcp.decide("Bash", frozenset()) is None


def test_no_listed_pattern_widens_to_a_whole_family_of_servers() -> None:
    for pattern in (*guard_mcp.ALLOWED, *guard_mcp.PROJECT_TOOLS):
        prefix, server, tool = pattern.split("__", 2)
        assert prefix == "mcp" and tool
        assert server and not set(server) & set("*?[]"), pattern


def test_the_project_declares_no_mcp_server() -> None:
    assert guard_mcp.project_servers(REPO_ROOT / ".mcp.json") == frozenset()
    assert guard_mcp.PROJECT_TOOLS == ()


def test_project_servers_reads_mcp_json(tmp_path: Path) -> None:
    config = tmp_path / ".mcp.json"
    assert guard_mcp.project_servers(config) == frozenset()
    config.write_text(json.dumps({"mcpServers": {"web": {"command": "x"}}}), encoding="utf-8")
    assert guard_mcp.project_servers(config) == frozenset({"web"})


@pytest.mark.parametrize("text", ["{oops", '{"mcpServers": []}', "[1]"])
def test_an_unreadable_mcp_json_raises(tmp_path: Path, text: str) -> None:
    config = tmp_path / ".mcp.json"
    config.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        guard_mcp.project_servers(config)


def test_end_to_end_refusal_is_audited_without_the_arguments(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    payload = {
        "session_id": "test-session",
        "tool_name": "mcp__terminal__run_in_terminal",
        "tool_use_id": "toolu_test_1",
        "tool_input": {"command": "echo personne@example.com"},
    }
    result = run_hook("guard_mcp", payload, journal)
    assert result.returncode == 2, result.stderr
    assert "BLOQUÉ" in result.stderr and "B7" in result.stderr
    [entry] = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert entry["actor"] == "policy" and entry["event"] == "POLICY"
    assert entry["request_id"] == "toolu_test_1"
    payload_file = tmp_path / "payloads" / (entry["payload_ref"].removeprefix("sha256:") + ".json")
    stored = json.loads(payload_file.read_text(encoding="utf-8"))
    assert stored["target"] == "mcp__terminal__run_in_terminal"
    assert stored["tool_name"] == "mcp__terminal__run_in_terminal"
    for written in tmp_path.rglob("*.json*"):
        assert "personne@example.com" not in written.read_text(encoding="utf-8")
    assert verify(journal).ok


def test_end_to_end_listed_tool_exits_zero(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    payload = {"tool_name": "mcp__ccd_turn__update_plan", "tool_input": {"advance": True}}
    result = run_hook("guard_mcp", payload, journal)
    assert result.returncode == 0, result.stderr
    assert not journal.exists()


@pytest.mark.parametrize("stdin", ["not json", "[1, 2]", "", '{"tool_input": {}}'])
def test_unreadable_input_fails_closed(tmp_path: Path, stdin: str) -> None:
    result = run_hook("guard_mcp", stdin, tmp_path / "journal.jsonl")
    assert result.returncode == 2
    assert "BLOQUÉ" in result.stderr


def test_settings_route_every_mcp_tool_to_the_guard() -> None:
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    [entry] = [
        e for e in settings["hooks"]["PreToolUse"] if "guard_mcp.py" in json.dumps(e["hooks"])
    ]
    # Claude Code reads a matcher with other characters than letters, digits, `_`, `-` and `|`
    # as an unanchored JavaScript regular expression: `^` keeps it to tool names that start so.
    pattern = re.compile(entry["matcher"])
    assert pattern.search("mcp__terminal__run_in_terminal")
    assert not pattern.search("Bash") and not pattern.search("Read")
    [hook] = entry["hooks"]
    assert hook["command"] == "python" and hook["onFailure"] == "block"
    assert hook["args"] == ["${CLAUDE_PROJECT_DIR}/.claude/hooks/guard_mcp.py"]
