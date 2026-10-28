"""protect_paths.py: Edit / Write / NotebookEdit on protected paths are refused (R3, R6, R11)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.audit import verify
from tests.conftest import REPO_ROOT
from tests.hooks.hookutil import load_hook, run_hook

pytestmark = pytest.mark.hooks
hook = load_hook("protect_paths")
ROOT = str(REPO_ROOT)
WINDOWS = os.name == "nt"

BLOCKED = [
    "config/live.yaml",
    f"{ROOT}/config/live.yaml",
    f"{ROOT}\\config\\live.yaml",
    "./config/../config/live.yaml",
    "governance/approvals/2026-10-17.yaml",
    "var/audit/journal.jsonl",
    "var/audit/payloads/abc.json",
    ".env",
    "infra/.env",
    ".env.local",
    "secrets/broker.key",
    "core/secrets/x.txt",
    "/elsewhere/checkout/config/live.yaml",
]
ALLOWED = [
    "config/budgets.yaml",
    "config/live.yaml.md",
    "docs/live.yaml-notes.md",
    "infra/.env.example",
    "governance/README.md",
    "var/cache/x",
    "core/audit/chain.py",
    "docs/secrets-policy.md",
]
WINDOWS_ONLY_BLOCKED = [
    "CONFIG/LIVE.YAML",
    "config/live.yaml.",
    "config/live.yaml ",
    "config/live.yaml::$DATA",
    f"/{ROOT[0].lower()}/{ROOT[3:]}/config/live.yaml".replace("\\", "/"),
]


@pytest.mark.parametrize("target", BLOCKED)
def test_protected_targets_are_refused(target: str) -> None:
    _, reason = hook.decide({"file_path": target}, ROOT)
    assert reason, f"{target} aurait dû être refusé"


@pytest.mark.parametrize("target", ALLOWED)
def test_ordinary_targets_are_allowed(target: str) -> None:
    _, reason = hook.decide({"file_path": target}, ROOT)
    assert reason is None, f"{target} refusé à tort : {reason}"


@pytest.mark.skipif(not WINDOWS, reason="variantes de chemin propres à Windows")
@pytest.mark.parametrize("target", WINDOWS_ONLY_BLOCKED)
def test_windows_path_variants_are_refused(target: str) -> None:
    _, reason = hook.decide({"file_path": target}, ROOT)
    assert reason, f"{target} aurait dû être refusé"


def test_notebook_path_is_checked() -> None:
    _, reason = hook.decide({"notebook_path": "secrets/analysis.ipynb"}, ROOT)
    assert reason


def test_missing_target_is_refused() -> None:
    _, reason = hook.decide({"content": "x"}, ROOT)
    assert reason and "absent" in reason


def test_symlink_to_protected_file_is_refused(tmp_path: Path) -> None:
    link = tmp_path / "innocent.yaml"
    try:
        link.symlink_to(REPO_ROOT / "config" / "live.yaml")
    except OSError:
        pytest.skip("création de lien symbolique non autorisée sur ce poste")
    _, reason = hook.decide({"file_path": str(link)}, ROOT)
    assert reason


def test_end_to_end_refusal_is_audited(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    payload = {
        "session_id": "test-session",
        "cwd": ROOT,
        "tool_name": "Edit",
        "tool_use_id": "toolu_test_1",
        "tool_input": {
            "file_path": f"{ROOT}/config/live.yaml",
            "old_string": "a",
            "new_string": "b",
        },
    }
    result = run_hook("protect_paths", payload, journal)
    assert result.returncode == 2, result.stderr
    assert "BLOQUÉ" in result.stderr and "R3" in result.stderr
    entries = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 1
    assert entries[0]["actor"] == "policy" and entries[0]["event"] == "POLICY"
    assert entries[0]["request_id"] == "toolu_test_1"
    assert verify(journal).ok


def test_end_to_end_allowed_write_exits_zero(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    payload = {"cwd": ROOT, "tool_name": "Write", "tool_input": {"file_path": "docs/x.md"}}
    result = run_hook("protect_paths", payload, journal)
    assert result.returncode == 0, result.stderr
    assert not journal.exists()


@pytest.mark.parametrize("stdin", ["not json", "[1, 2]", "", '{"tool_input": "x"}'])
def test_unreadable_input_fails_closed(tmp_path: Path, stdin: str) -> None:
    result = run_hook("protect_paths", stdin, tmp_path / "journal.jsonl")
    assert result.returncode == 2
    assert "BLOQUÉ" in result.stderr
