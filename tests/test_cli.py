"""`cerveau` CLI: audit, config and registry commands."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from core.audit import AuditJournal
from interfaces.cli.main import app
from tests.conftest import REPO_ROOT

runner = CliRunner()


@pytest.fixture
def journal_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "audit" / "journal.jsonl"
    monkeypatch.setenv("CERVEAU_AUDIT_JOURNAL", str(path))
    return path


def test_audit_verify_on_empty_journal(journal_path: Path) -> None:
    result = runner.invoke(app, ["audit", "verify"])
    assert result.exit_code == 0, result.output
    assert "OK : 0 entrée(s)" in result.output


def test_redirected_output_is_utf8(journal_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
    run = subprocess.run(
        [sys.executable, "-m", "interfaces.cli.main", "audit", "verify"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert "OK : 0 entrée(s)" in run.stdout.decode("utf-8")


def test_audit_verify_reports_tampering(journal_path: Path) -> None:
    journal = AuditJournal(journal_path)
    for _ in range(3):
        journal.append(actor="orchestrator", event="TOOL_CALL", payload={"x": 1})
    ok = runner.invoke(app, ["audit", "verify"])
    assert ok.exit_code == 0
    assert "OK : 3 entrée(s)" in ok.output

    content = journal_path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(content[0])
    entry["actor"] = "lucas"
    content[0] = json.dumps(entry)
    journal_path.write_text("\n".join(content) + "\n", encoding="utf-8")
    failed = runner.invoke(app, ["audit", "verify"])
    assert failed.exit_code == 1
    assert "ÉCHEC" in failed.output


def test_audit_head_and_anchor_roundtrip(journal_path: Path) -> None:
    journal = AuditJournal(journal_path)
    journal.append(actor="scheduler", event="DECISION")
    head = runner.invoke(app, ["audit", "head"])
    assert head.exit_code == 0
    anchor = head.output.strip()
    assert anchor.startswith("1:sha256:")
    assert runner.invoke(app, ["audit", "verify", "--anchor", anchor]).exit_code == 0


def test_audit_verify_rejects_malformed_anchor(journal_path: Path) -> None:
    result = runner.invoke(app, ["audit", "verify", "--anchor", "abc"])
    assert result.exit_code == 2


def test_audit_tail_shows_payloads(journal_path: Path) -> None:
    AuditJournal(journal_path).append(actor="policy", event="POLICY", payload={"reason": "R3"})
    result = runner.invoke(app, ["audit", "tail", "-n", "1"])
    assert result.exit_code == 0
    assert '"reason": "R3"' in result.output


def test_config_check_lists_blocked_features() -> None:
    result = runner.invoke(app, ["config", "check", "--config-dir", str(REPO_ROOT / "config")])
    assert result.exit_code == 0, result.output
    assert "Configuration valide" in result.output
    assert "live.yaml : enabled = false" in result.output
    assert "✗ live_trading" in result.output
    assert "✗ paper_trading" in result.output


def test_config_check_fails_on_invalid_config(config_dir: Path) -> None:
    (config_dir / "live.yaml").write_text("enabled: maybe\n", encoding="utf-8")
    result = runner.invoke(app, ["config", "check", "--config-dir", str(config_dir)])
    assert result.exit_code == 1
    assert "Configuration invalide" in result.output


def test_registry_validate_accepts_and_refuses(make_plugin: Callable[..., Path]) -> None:
    good = make_plugin("good_plugin")
    accepted = runner.invoke(app, ["registry", "validate", str(good)])
    assert accepted.exit_code == 0
    assert "ACCEPTÉ  good_plugin" in accepted.output

    (good / "evals" / "questions.xml").unlink()
    refused = runner.invoke(app, ["registry", "validate", str(good.parent)])
    assert refused.exit_code == 1
    assert "REFUSÉ   good_plugin" in refused.output


def test_registry_validate_on_empty_directory(tmp_path: Path) -> None:
    result = runner.invoke(app, ["registry", "validate", str(tmp_path)])
    assert result.exit_code == 0
    assert "Aucun plugin" in result.output
