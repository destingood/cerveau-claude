"""`cerveau evals` (ADR-074): the three commands of a run, their output and their exit codes."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from core.evals import claude_code as cc
from core.evals import claude_code_score as ccs
from interfaces.cli.main import app

runner = CliRunner()
RUN_LINE = re.compile(r"^Run ([0-9T]{15}-[0-9a-f]{6}) :", re.MULTILINE)


@pytest.fixture
def bench(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    place = tmp_path / "bench"
    monkeypatch.setattr(cc, "BENCH_DIR", place)  # absolute: the project's var/ stays untouched
    monkeypatch.setattr(ccs, "BENCH_DIR", place)
    monkeypatch.setenv("CERVEAU_AUDIT_JOURNAL", str(tmp_path / "audit" / "journal.jsonl"))
    return place


def test_a_run_whose_gates_pass_exits_zero(bench: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    passed = SimpleNamespace(report=SimpleNamespace(passed=True, gates=[]), scored=[], written=[])
    monkeypatch.setattr(ccs, "score_run", lambda *_a, **_k: passed)
    done = runner.invoke(app, ["evals", "noter", "20261128T120000-abcdef"])
    assert done.exit_code == 0, done.output


def test_a_run_from_export_to_score(bench: Path, tmp_path: Path) -> None:
    done = runner.invoke(
        app,
        [
            *("evals", "exporter", "--pack", "generaliste", "--modele-reponse", "claude-opus-5-5"),
            *("--cas", "calcul-pourcentage", "--cas", "refus-achat-actions"),
        ],
    )
    assert done.exit_code == 0, done.output
    found = RUN_LINE.search(done.output)
    assert found is not None
    run = found.group(1)
    assert "2 cas exporté(s)" in done.output and "preparer-juge" in done.output
    answers = bench / run / cc.ANSWERS_DIR
    answers.mkdir()
    message = {"calcul-pourcentage": "CALCUL : aucun outil.", "refus-achat-actions": "FINANCIERE"}
    for case_id, text in message.items():
        data = {"statut": "refus", "message": f"{text} Refus motivé, rien n'est exécuté."}
        (answers / f"{case_id}.json").write_text(json.dumps(data), encoding="utf-8")
    prepared = runner.invoke(app, ["evals", "preparer-juge", run])
    assert prepared.exit_code == 0, prepared.output
    assert (
        "2 fichier(s) pour le juge" in prepared.output
        and "j01.md → verdicts/j01.json" in prepared.output
    )
    verdicts = bench / run / cc.VERDICTS_DIR
    verdicts.mkdir()
    for label in ("j01", "j02"):
        grades = dict.fromkeys(("exactitude", "completude", "sources", "honnetete", "format"), 2)
        points = [{"n": 1, "verdict": "couvert", "raison": "refus"}]
        data = grades | {"factuel": False, "justification": "ok", "points": points}
        (verdicts / f"{label}.json").write_text(json.dumps(data), encoding="utf-8")
    copy = tmp_path / "copie"
    scored = runner.invoke(app, ["evals", "noter", run, "--report", str(copy)])
    assert scored.exit_code == 1, scored.output  # 2 of 37 cases: the coverage gate is missed
    assert "calcul-pourcentage : réussi, score 1.00" in scored.output
    assert "cas exportables jugés : generaliste : 2/37 (seuil 37/37) MANQUÉ" in scored.output
    assert copy.with_suffix(".md").is_file()
    again = runner.invoke(app, ["evals", "preparer-juge", run])
    assert again.exit_code == 1 and "déjà préparé" in again.output


def test_errors_are_said_and_exit_one(bench: Path) -> None:
    refused = runner.invoke(
        app, ["evals", "exporter", "--pack", "generaliste", "--modele-reponse", "gpt-5"]
    )
    assert refused.exit_code == 1 and "ERREUR" in refused.output
    exported = runner.invoke(
        app,
        ["evals", "exporter", "--pack", "finance", "--modele-reponse", "opus", "--limite", "1"],
    )
    assert exported.exit_code == 0 and "  exclu : " in exported.output
    run = RUN_LINE.search(exported.output).group(1)  # type: ignore[union-attr]
    prepared = runner.invoke(app, ["evals", "preparer-juge", run])
    assert prepared.exit_code == 0 and "non jugé" in prepared.output
    for command in (["preparer-juge", "../x"], ["noter", "20990101T000000-000000"]):
        failed = runner.invoke(app, ["evals", *command])
        assert failed.exit_code == 1 and "ERREUR" in failed.output
