"""Weekly and monthly security reports, and the streak of scheduled weeks (ADR-066)."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from core.audit import AuditError, AuditJournal
from core.learning.calibration import CalibrationError
from core.learning.forecasts import ForecastStore
from core.notify.alerts import Alert, Alerts
from core.reports import security as security_mod
from core.reports import weekly as weekly_mod
from core.reports.security import (
    CHECKS,
    MISSING,
    build_security,
    run_command,
    security_path,
    threat_model_drift,
)
from core.reports.weekly import (
    FAILED,
    OK,
    Week,
    build_weekly,
    record,
    streak,
    weekly_path,
)
from interfaces.cli import report as report_cli
from interfaces.cli.main import app

runner = CliRunner()
NOW = datetime(2026, 10, 29, 12, 0).astimezone()  # a Thursday: the covered week is 2026-S43
IN_WEEK = datetime(2026, 10, 21, 10, 0).astimezone()


def _report(created: datetime, *, passed: bool = True) -> dict[str, Any]:
    gate = {"suite": "behaviors", "name": "global", "threshold": 0.9, "measured": 0.95}
    return {
        "run": "r1",
        "mode": "offline",
        "created": created.isoformat(),
        "costs": {"requests": 4, "total_eur": 0.0, "simulated": True},
        "suites": [
            {
                "suite": "behaviors",
                "cases": 4,
                "passed": 4,
                "r5_breaches": 0,
                "groups": [
                    {"name": "finance", "cases": 4, "passed": 4, "threshold": 0.9, "rate": 1.0}
                ],
                "gates": [{**gate, "passed": passed}],
            },
            {"suite": "redteam", "cases": 2, "passed": 2, "r5_breaches": 0},
        ],
    }


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def journal(root: Path) -> AuditJournal:
    return AuditJournal(root / "var" / "audit" / "audit.jsonl")


def _paths(root: Path) -> dict[str, Path]:
    return {
        "eval_report": root / "report.json",
        "forecasts": root / "forecasts.db",
        "history": root / "champions.jsonl",
    }


def _write_json(path: Path, content: Any) -> None:
    path.write_text(json.dumps(content), encoding="utf-8")


def _build(root: Path, journal: AuditJournal, now: datetime = NOW) -> weekly_mod.Weekly:
    return build_weekly(root, journal, now, **_paths(root))


# --- weeks --------------------------------------------------------------------------------


def test_week_covered_is_the_last_complete_iso_week() -> None:
    week = Week.covered(NOW)
    assert week.id == "2026-S43"
    assert week.start == datetime(2026, 10, 19).astimezone()
    assert week.end == datetime(2026, 10, 26).astimezone()  # 25/10: back to winter time
    assert Week.covered(week.end).id == "2026-S43"  # Monday 00:00 still covers the past week
    assert week.previous().id == "2026-S42"


# --- weekly report ------------------------------------------------------------------------


def test_weekly_without_any_source_fails_on_the_missing_evals(
    root: Path, journal: AuditJournal
) -> None:
    weekly = _build(root, journal)
    assert weekly.status == FAILED
    assert weekly.reasons == ["aucun rapport d'évals hors ligne"]
    text = weekly.markdown()
    assert "# Rapport hebdomadaire 2026-S43" in text
    assert "du 19/10/2026 au 25/10/2026" in text
    assert "Registre absent" in text
    assert "Aucune promotion en service" in text
    assert "Entrées de la semaine : 0" in text


def test_weekly_reads_every_source(root: Path, journal: AuditJournal) -> None:
    paths = _paths(root)
    _write_json(paths["eval_report"], _report(IN_WEEK))
    guard = {"decision": "refus", "action_class": "lecture"}
    journal.append(
        actor="orchestrator",
        event="DECISION",
        payload={"status": "refuse", "guard": guard},
        now=IN_WEEK,
    )
    journal.append(actor="orchestrator", event="DECISION", payload={"status": "ok"}, now=IN_WEEK)
    journal.append(actor="orchestrator", event="DECISION", now=IN_WEEK)
    journal.append(actor="policy", event="POLICY", payload={"notification": {}}, now=IN_WEEK)
    journal.append(actor="lucas", event="LEARNING", payload={"pack": "x"}, now=IN_WEEK)
    journal.append(actor="orchestrator", event="ERROR", payload=["x"], now=IN_WEEK)
    journal.append(actor="orchestrator", event="ERROR", now=NOW)  # outside the week
    with ForecastStore.open(paths["forecasts"]) as store:
        fid = store.add(
            domain="finance",
            kind="probabilite",
            statement="Le taux reste stable",
            value=0.7,
            due_on=date(2026, 10, 20),
            now=NOW - timedelta(days=30),
        ).forecast_id
        store.resolve(fid, outcome=True, source="BCE", now=NOW - timedelta(days=5))
        store.add(
            domain="finance",
            kind="probabilite",
            statement="Une prévision échue",
            value=0.4,
            due_on=date(2026, 10, 20),
            now=NOW - timedelta(days=30),
        )
    history = [
        {"pack": "finance", "section": "lessons", "action": "promote", "previous": None,
         "current": "a", "ts": IN_WEEK.isoformat(), "report": {}},
        {"pack": "code", "section": "examples", "action": "promote", "previous": None,
         "current": "b", "ts": IN_WEEK.isoformat(), "report": {}},
        {"pack": "code", "section": "examples", "action": "rollback"},
    ]  # fmt: skip
    paths["history"].write_text("\n".join(json.dumps(r) for r in history), encoding="utf-8")

    weekly = _build(root, journal)
    assert weekly.status == OK, weekly.reasons
    text = weekly.markdown()
    assert "Entrées de la semaine : 6" in text
    assert "Requêtes : 3 ; refus à l'entrée : 1" in text
    assert "inconnu 1, ok 1, refuse 1" in text
    assert "Incidents (KILL, ERROR) : 1 ; alertes envoyées : 1" in text
    assert "Entrées d'apprentissage (LEARNING) : 1" in text
    assert "| behaviors | finance | 4/4 | 1.0 | 0.9 |" in text
    assert "behaviors · global : 0.95 (seuil 0.9) atteint" in text
    assert "Coûts du run (simulés)" in text
    assert "Prévisions échues non résolues : 1" in text
    assert "Probabilités résolues : 1 ; Brier 0.0900" in text
    assert "finance/lessons : 1 promotion(s) en service, dernière le 21/10/2026" in text
    assert "code/examples" not in text
    assert "Plugins hors SLO : non mesuré" in text


def test_weekly_fails_on_a_stale_report_and_a_missed_gate(
    root: Path, journal: AuditJournal
) -> None:
    _write_json(
        _paths(root)["eval_report"], _report(datetime(2026, 10, 1).astimezone(), passed=False)
    )
    weekly = _build(root, journal)
    assert weekly.reasons == [
        "évals non rejouées depuis le 01/10/2026",
        "seuil manqué : behaviors · global",
    ]
    assert "MANQUÉ" in weekly.markdown()


def test_weekly_turns_unreadable_sources_into_reasons(root: Path, journal: AuditJournal) -> None:
    paths = _paths(root)
    paths["eval_report"].write_text("{", encoding="utf-8")
    paths["forecasts"].write_text("not a database", encoding="utf-8")
    paths["history"].write_text("{", encoding="utf-8")
    journal.path.parent.mkdir(parents=True)
    journal.path.write_text("{\n", encoding="utf-8")
    weekly = _build(root, journal)
    assert weekly.reasons == [
        "évals : rapport d'évals illisible",
        "calibration : registre des prévisions illisible (DatabaseError)",
        "coûts : dépenses illisibles dans le journal",
        "journal : journal illisible à la ligne 1",
        "apprentissage : historique des champions illisible à la ligne 1",
    ]
    assert "- Section évals en échec : rapport d'évals illisible" in weekly.markdown()


def test_weekly_reports_a_registry_without_resolved_probabilities(
    root: Path, journal: AuditJournal
) -> None:
    _write_json(_paths(root)["eval_report"], _report(IN_WEEK))
    with ForecastStore.open(_paths(root)["forecasts"]):
        pass
    weekly = _build(root, journal)
    assert weekly.status == OK
    assert "Brier non calculable" in weekly.markdown()


def test_weekly_rejects_invalid_resolved_probabilities(
    root: Path, journal: AuditJournal, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(pairs: object) -> None:
        raise CalibrationError("x")

    monkeypatch.setattr(weekly_mod, "probability_scores", broken)
    monkeypatch.setattr(ForecastStore, "probability_pairs", lambda self: [(0.5, True)])
    with ForecastStore.open(_paths(root)["forecasts"]):
        pass
    weekly = _build(root, journal)
    assert "calibration : prévisions résolues invalides" in weekly.reasons


def test_weekly_refuses_an_impossible_history(root: Path, journal: AuditJournal) -> None:
    record_ = {"pack": "finance", "section": "lessons", "action": "rollback"}
    _paths(root)["history"].write_text(json.dumps(record_), encoding="utf-8")
    weekly = _build(root, journal)
    assert "apprentissage : historique des champions illisible à la ligne 1" in weekly.reasons


def test_weekly_detects_a_tampered_journal(root: Path, journal: AuditJournal) -> None:
    journal.append(actor="orchestrator", event="DECISION", payload={"status": "ok"}, now=IN_WEEK)
    entry = json.loads(journal.path.read_text(encoding="utf-8"))
    entry["actor"] = "lucas"
    journal.path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    weekly = _build(root, journal)
    assert "coûts : dépenses illisibles dans le journal" in weekly.reasons


def test_record_and_streak(root: Path, journal: AuditJournal) -> None:
    assert streak(journal, NOW) == 0
    week = Week.covered(NOW)
    for back, status in ((3, OK), (2, FAILED), (1, OK), (0, FAILED), (0, OK)):
        target = week
        for _ in range(back):
            target = target.previous()
        weekly = weekly_mod.Weekly(target, reasons=[] if status == OK else ["x"])
        record(journal, weekly, weekly.markdown(), target.end + timedelta(hours=1))
    journal.append(actor="orchestrator", event="DECISION", payload={"status": "rapport_hebdo"})
    journal.append(actor="scheduler", event="DECISION", payload={"status": "autre"})
    journal.append(actor="scheduler", event="DECISION")
    assert streak(journal, NOW) == 2  # S43 (caught up after its failure) and S42; S41 failed
    assert weekly_path(root, week) == root / "evals" / "reports" / "hebdo-2026-S43.md"


# --- security report ----------------------------------------------------------------------


def _runner(codes: dict[str, int]) -> security_mod.Runner:
    def run(command: Sequence[str], cwd: Path) -> tuple[int, int]:
        return codes.get(" ".join(command), 0), 3

    return run


def test_security_report(root: Path) -> None:
    (root / "docs" / "adr").mkdir(parents=True)
    (root / "docs" / "threat-model.md").write_text("ADR-001, ADR-063.", encoding="utf-8")
    for name in ("ADR-063-a.md", "ADR-064-b.md", "ADR-066-c.md", "README.md"):
        (root / "docs" / "adr" / name).write_text("", encoding="utf-8")
    pip, npm, outdated = (" ".join(c.command) for c in (CHECKS[1], CHECKS[2], CHECKS[6]))
    report = build_security(root, NOW, runner=_runner({pip: 1, npm: MISSING, outdated: 1}))
    assert report.month == "2026-10"
    assert report.status == FAILED
    assert report.failed == [CHECKS[1].name, CHECKS[2].name]
    text = report.markdown()
    assert "| 1 | 3 | ÉCHEC |" in text
    assert "| 127 | 3 | outil absent |" in text
    assert "à examiner" in text
    assert "ADR postérieurs au dernier cité : ADR-064, ADR-066" in text
    assert security_path(root, "2026-10") == root / "docs" / "rapports" / "securite-2026-10.md"


def test_security_report_ok_without_threat_model(root: Path) -> None:
    report = build_security(root, NOW, runner=_runner({}))
    assert report.status == OK and report.failed == []
    assert threat_model_drift(root) == []
    assert "ADR postérieurs au dernier cité : aucun" in report.markdown()


def test_run_command_counts_lines_and_reports_a_missing_tool(tmp_path: Path) -> None:
    assert run_command([sys.executable, "-c", "print('a'); print('b')"], tmp_path) == (0, 2)
    assert run_command(["cerveau-no-such-tool-xyz"], tmp_path) == (MISSING, 0)


# --- CLI ----------------------------------------------------------------------------------


class _Failing:
    channel = "test"

    def send(self, alert: Alert) -> None:
        raise ConnectionError


@pytest.fixture
def cli(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(report_cli, "project_root", lambda: root)
    monkeypatch.setenv("CERVEAU_AUDIT_JOURNAL", str(root / "var" / "audit" / "audit.jsonl"))
    monkeypatch.setattr(report_cli, "_now", lambda: NOW)
    monkeypatch.setattr(report_cli, "build_security", partial(build_security, runner=_runner({})))
    return root


def _invoke(*args: str):
    return runner.invoke(app, ["report", *args])


def test_cli_weekly_failed_alerts_and_exits(
    cli: Path, config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report_cli, "alert_channels", lambda config, root: Alerts((_Failing(),)))
    result = _invoke("weekly", "--config-dir", str(config_dir))
    assert result.exit_code == 1
    assert "Rapport 2026-S43 : echec" in result.output
    assert "alerte non envoyée (test : ConnectionError)" in result.output
    assert (cli / "evals" / "reports" / "hebdo-2026-S43.md").is_file()
    lines = (cli / "var" / "audit" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["DECISION", "POLICY"]


def test_cli_weekly_ok_and_streak(cli: Path) -> None:
    report = cli / report_cli.EVAL_REPORT
    report.parent.mkdir(parents=True)
    _write_json(report, _report(IN_WEEK))
    assert _invoke("weekly").exit_code == 0
    result = _invoke("streak")
    assert result.exit_code == 0
    assert "Semaines consécutives sans échec : 1" in result.output


def test_cli_streak_refuses_an_unreadable_journal(cli: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{\n", encoding="utf-8")
    result = _invoke("streak", "--journal", str(bad), "--hors-var")
    assert result.exit_code == 1
    assert "journal illisible à la ligne 1" in result.output


class _BrokenJournal(AuditJournal):
    def append(self, **kwargs: Any) -> dict[str, Any]:
        raise AuditError("chaîne rompue")


def test_cli_reports_a_journal_that_refuses_the_entry(
    cli: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = _BrokenJournal(cli / "var" / "audit" / "audit.jsonl")
    monkeypatch.setattr(report_cli, "_journal", lambda journal, outside: broken)
    for command in ("weekly", "security"):
        result = _invoke(command)
        assert result.exit_code == 1
        assert "Journal d'audit : chaîne rompue" in result.output


def test_cli_security(cli: Path, config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke("security")
    assert result.exit_code == 0
    assert "Sécurité 2026-10 : ok" in result.output
    assert (cli / "docs" / "rapports" / "securite-2026-10.md").is_file()
    failing = _runner({" ".join(CHECKS[0].command): 1})
    monkeypatch.setattr(report_cli, "build_security", partial(build_security, runner=failing))
    result = _invoke("security", "--config-dir", str(config_dir))
    assert result.exit_code == 1
    assert f"en échec : {CHECKS[0].name}" in result.output


def test_cli_clock_is_aware() -> None:
    assert report_cli._now().tzinfo is not None
