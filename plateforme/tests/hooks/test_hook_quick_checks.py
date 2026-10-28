"""quick_checks.py: lint, secret scan and Claude Code file checks after each write."""

from __future__ import annotations

import contextlib
import shutil
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT
from tests.hooks.hookutil import load_hook, run_hook

pytestmark = pytest.mark.hooks
qc = load_hook("quick_checks")
HAS_RUFF = qc.venv_tool(REPO_ROOT, "ruff") is not None


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A throwaway project root sharing the repository ruff settings and virtualenv."""
    shutil.copy(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    venv = REPO_ROOT / ".venv"
    if venv.exists():
        # without symlink rights, venv_tool() falls back to the ruff on PATH
        with contextlib.suppress(OSError):
            (tmp_path / ".venv").symlink_to(venv, target_is_directory=True)
    return tmp_path


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.skipif(not HAS_RUFF, reason="ruff absent")
def test_clean_python_file_passes(project: Path) -> None:
    path = write(project, "core/ok.py", '"""Ok."""\n\nVALUE = 1\n')
    assert qc.check_file(path, project) == []


@pytest.mark.skipif(not HAS_RUFF, reason="ruff absent")
def test_ruff_errors_are_reported(project: Path) -> None:
    path = write(project, "core/bad.py", "import os\n")
    problems = qc.check_file(path, project)
    assert any("F401" in p for p in problems), problems


@pytest.mark.skipif(not HAS_RUFF, reason="ruff absent")
def test_unformatted_python_is_reported(project: Path) -> None:
    path = write(project, "core/ugly.py", "VALUE   =   {ʼaʼ:1}\n".replace("ʼ", '"'))
    assert any("ruff format" in p for p in qc.check_file(path, project))


def test_fake_aws_key_is_reported(project: Path) -> None:
    path = write(project, "docs/notes.md", "clé : " + "AKIA" + "Q" * 16 + "\n")
    problems = qc.check_file(path, project)
    assert any("AWS" in p and "ligne 1" in p for p in problems), problems


def test_hardcoded_password_is_reported(project: Path) -> None:
    path = write(project, "config/x.txt", "password = '" + "z" * 20 + "'\n")
    assert any("secret en clair" in p for p in qc.check_file(path, project))


def test_placeholder_is_not_a_secret(project: Path) -> None:
    path = write(project, "infra/.env.example", "POSTGRES_PASSWORD=A_DEFINIR\n")
    assert qc.check_file(path, project) == []


def test_claude_md_over_200_lines_is_reported(project: Path) -> None:
    path = write(project, "CLAUDE.md", "ligne\n" * 201)
    assert any("201 lignes" in p for p in qc.check_file(path, project))


def test_agent_without_description_is_reported(project: Path) -> None:
    path = write(project, ".claude/agents/x.md", "---\nname: x\n---\nCorps.\n")
    assert any("description" in p for p in qc.check_file(path, project))


def test_complete_skill_frontmatter_passes(project: Path) -> None:
    text = "---\nname: s\ndescription: Fait une chose.\n---\nCorps.\n"
    assert qc.check_file(write(project, ".claude/skills/s/SKILL.md", text), project) == []


def test_invalid_claude_json_is_reported(project: Path) -> None:
    path = write(project, ".claude/settings.json", "{oops")
    assert any("JSON invalide" in p for p in qc.check_file(path, project))


def test_files_outside_the_root_are_ignored(tmp_path: Path, project: Path) -> None:
    outside = tmp_path.parent / "outside_quick_checks.md"
    outside.write_text("AKIA" + "Q" * 16, encoding="utf-8")
    try:
        assert qc.check_file(outside, project) == []
    finally:
        outside.unlink()


def test_hook_reports_problems_with_exit_2(tmp_path: Path) -> None:
    target = REPO_ROOT / "var" / "cache" / "quick_checks_probe.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("AKIA" + "Q" * 16 + "\n", encoding="utf-8")
    try:
        payload = {"cwd": str(REPO_ROOT), "tool_input": {"file_path": str(target)}}
        result = run_hook("quick_checks", payload, tmp_path / "journal.jsonl")
    finally:
        target.unlink()
    assert result.returncode == 2
    assert "Contrôles rapides" in result.stderr and "AWS" in result.stderr


def test_hook_is_silent_without_a_target(tmp_path: Path) -> None:
    result = run_hook("quick_checks", {"tool_input": {}}, tmp_path / "journal.jsonl")
    assert result.returncode == 0 and result.stderr == ""
