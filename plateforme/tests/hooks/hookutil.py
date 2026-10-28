"""Helpers to load the Claude Code hooks in-process or run them like Claude Code does."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from tests.conftest import REPO_ROOT

HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"


def load_hook(name: str) -> ModuleType:
    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    return importlib.import_module(name)


def run_hook(
    name: str,
    payload: dict | str,
    journal: Path,
    python: str = sys.executable,
) -> subprocess.CompletedProcess[str]:
    """Run `.claude/hooks/<name>.py` with a JSON payload on stdin, as Claude Code does."""
    env = {**os.environ, "CERVEAU_AUDIT_JOURNAL": str(journal), "PYTHONIOENCODING": "utf-8"}
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [python, str(HOOKS_DIR / f"{name}.py")],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
        check=False,
    )
