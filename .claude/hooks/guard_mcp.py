"""PreToolUse hook (B7): Claude Code may call only the MCP tools listed here.

settings.json routes every MCP tool here (matcher `^mcp__`). A tool that is not listed is refused
and the refusal is journaled (POLICY, actor "policy"), like the other hooks.

The list keeps the desktop app working (task list, wrap-up, chapters, side sessions, panes,
inline visuals) and lets Claude read web documentation in the app's own browser; web content
stays data (R5). It refuses whatever runs commands, types, clicks, sends or changes settings
outside the repository: the app terminal and the preview servers (they would bypass guard_shell),
Lucas's Chrome, computer use, the connectors (mail, calendar, shop...), scheduled tasks, plugins,
a merge into main. Tools of a server declared in the project's `.mcp.json` are refused unless
PROJECT_TOOLS lists them, even under a listed name: a server may pick any name.

Only the tool name reaches the journal: MCP arguments may carry personal data.
"""

from __future__ import annotations

import fnmatch
import json
import re
from collections.abc import Iterable
from pathlib import Path

import _common as c

MCP_PREFIX = "mcp__"
MCP_CONFIG = c.ROOT / ".mcp.json"

# Exact names or `mcp__<server>__*`; a server name is never a wildcard (tested).
ALLOWED = (
    # desktop app: no effect outside the app
    "mcp__ccd_turn__*",
    "mcp__ccd_session__mark_chapter",
    "mcp__ccd_session__start_session",
    "mcp__ccd_session__dismiss_task",
    "mcp__ccd_session__hand_off_to_session",
    "mcp__ccd_session__list_start_targets",
    "mcp__ccd_session__read_widget_context",
    "mcp__ccd_session_mgmt__list_sessions",
    "mcp__ccd_session_mgmt__get_session",
    "mcp__ccd_session_mgmt__list_events",
    "mcp__ccd_view__*",
    "mcp__ccd_window__*",
    "mcp__ccd_pr__get_status",
    "mcp__ccd_pr__bind_pr",
    "mcp__ccd_pr__unbind_pr",
    "mcp__ccd_pr__set_monitor",
    "mcp__visualize__*",
    # the app's own browser, reading only: no click, typing, form, script or server
    "mcp__Claude_Browser__navigate",
    "mcp__Claude_Browser__get_page_text",
    "mcp__Claude_Browser__find",
    "mcp__Claude_Browser__read_page",
    "mcp__Claude_Browser__tabs_context",
    "mcp__Claude_Browser__tabs_create",
    "mcp__Claude_Browser__tabs_select",
    "mcp__Claude_Browser__tabs_close",
)
# Tools of the `.mcp.json` servers that Claude Code may call: none while `.mcp.json` is empty.
PROJECT_TOOLS: tuple[str, ...] = ()

_NAME_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def project_servers(config: Path = MCP_CONFIG) -> frozenset[str]:
    """Server names declared in `.mcp.json`; an unreadable file raises (fail-closed)."""
    if not config.exists():
        return frozenset()
    data = json.loads(config.read_text(encoding="utf-8"))
    servers = data.get("mcpServers", {}) if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        raise ValueError(".mcp.json : mcpServers n'est pas un objet")
    return frozenset(str(name) for name in servers)


def listed(tool_name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(tool_name, pattern) for pattern in patterns)


def decide(tool_name: str, servers: Iterable[str]) -> str | None:
    """The refusal reason, or None when the call may go on."""
    if not tool_name.startswith(MCP_PREFIX):
        return None  # built-in tools are the other hooks' business
    for server in servers:
        prefixes = {f"{MCP_PREFIX}{name}__" for name in (server, _NAME_CHARS.sub("_", server))}
        if any(tool_name.startswith(prefix) for prefix in prefixes):
            if listed(tool_name, PROJECT_TOOLS):
                return None
            return f"outil d'un serveur MCP du projet (.mcp.json) non listé (B7) : {tool_name}"
    if listed(tool_name, ALLOWED):
        return None
    return f"outil MCP non listé dans .claude/hooks/guard_mcp.py (B7) : {tool_name}"


def main() -> None:
    hook_input = c.read_hook_input()
    tool_name = hook_input.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name:
        raise ValueError("tool_name absent")
    reason = decide(tool_name, project_servers())
    if reason:
        c.deny(hook_input, tool_name, reason)


if __name__ == "__main__":
    c.run_fail_closed(main)
