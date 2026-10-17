"""PreToolUse hook for Edit|Write|NotebookEdit: refuse writes to protected paths.

Protected (mega-prompt 16.5, R3, R6, R11): config/live.yaml, governance/approvals/**,
var/audit/**, .env / .env.* (except .env.example) and anything under a secrets/ directory.
"""

from __future__ import annotations

from typing import Any

import _common as c


def decide(tool_input: dict[str, Any], cwd: str | None) -> tuple[str, str | None]:
    """Return (target, reason); reason is None when the write is allowed."""
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(target, str) or not target.strip():
        return str(tool_input), "chemin cible absent ou illisible : refus par précaution"
    return target, c.write_protection_reason(c.normalise(target, cwd))


def main() -> None:
    hook_input = c.read_hook_input()
    tool_input = hook_input.get("tool_input")
    if not isinstance(tool_input, dict):
        c.deny(hook_input, str(tool_input), "entrée d'outil illisible : refus par précaution")
    target, reason = decide(tool_input, hook_input.get("cwd") or None)
    if reason:
        c.deny(hook_input, target, reason)


if __name__ == "__main__":
    c.run_fail_closed(main)
