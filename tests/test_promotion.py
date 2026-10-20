"""`cerveau promotion check`: a live report checked against the finance N0 → N1 rule (B107)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from core.audit import AuditJournal
from core.config import BlockedFeatureError, load_config
from core.config.loader import Config
from core.evals.cases import load_cases
from core.evals.promotion import (
    R1_TO_R5,
    PromotionError,
    check_promotion,
    load_report,
    report_digest,
    seal_report,
)
from interfaces.cli.main import app
from tests.conftest import REPO_ROOT

NOW = datetime(2026, 10, 20, 12, 0).astimezone()
CAMPAIGN = "finance-n1-test"
RUN = "20261020-100000-abcd"
GOLDEN = [case.id for case in load_cases("golden", REPO_ROOT) if case.group == "finance"]
RULED = [
    (case.suite, case.id)
    for suite in ("behaviors", "injection")
    for case in load_cases(suite, REPO_ROOT)
    if R1_TO_R5 & set(case.rules)
]


@pytest.fixture
def config(config_dir: Path) -> Config:
    return load_config(config_dir)


def _open(journal: AuditJournal, digest: str, *, campaign: str = CAMPAIGN, mode: str = "live",
          at: datetime = NOW - timedelta(hours=2)) -> None:  # fmt: skip
    journal.append(
        actor="orchestrator",
        event="DECISION",
        request_id=f"eval-{campaign}",
        versions={"config": digest},
        payload={"status": "campagne_eval", "campaign": campaign, "mode": mode, "suites": []},
        now=at,
    )


def _result(suite: str, case: str, **extra: Any) -> dict[str, Any]:
    return {"case": case, "suite": suite, "run": RUN, "passed": True, "error": None,
            "r5_breaches": 0, "judgement": None, **extra}  # fmt: skip


def _report(digest: str) -> dict[str, Any]:
    """A live report that meets the rule: every case of it ran, judged 0.9 or passed."""
    golden = [_result("golden", case, judgement={"score": 0.9}) for case in GOLDEN]
    return {
        "run": RUN,
        "mode": "live",
        "campaign": CAMPAIGN,
        "config": digest,
        "created": (NOW - timedelta(hours=1)).isoformat(timespec="seconds"),
        "results": golden + [_result(suite, case) for suite, case in RULED],
    }


@pytest.fixture
def journal(tmp_path: Path, config: Config) -> AuditJournal:
    audit = AuditJournal(tmp_path / "audit" / "journal.jsonl")
    _open(audit, config.digest)
    return audit


def _seal(report: dict[str, Any], config: Config, journal: AuditJournal) -> None:
    """What `cerveau eval --live` journals once it has written ``report``."""
    campaign, run = report.get("campaign"), report.get("run")
    if campaign and run:
        seal_report(journal, report, campaign=campaign, run=run, config=config.digest)


def _check(
    report: dict[str, Any], config: Config, journal: AuditJournal, *, seal: bool = True,
    **kwargs: Any,
) -> Any:  # fmt: skip
    if seal:
        _seal(report, config, journal)
    return check_promotion(
        report, config, domain="finance", level="N1", journal=journal, now=NOW, **kwargs
    )


def _failed(result: Any) -> list[str]:
    return [check.name for check in result.checks if not check.passed]


def test_the_rule_is_measured_on_the_current_cases() -> None:
    assert len(GOLDEN) >= 30  # the finance golden set (D17)
    assert len(RULED) >= 15  # behaviours and red team that measure R1 to R5


def test_a_live_report_that_meets_the_rule_proves_it(config: Config, journal: AuditJournal) -> None:
    result = _check(_report(config.digest), config, journal)
    assert result.passed, _failed(result)
    names = [check.name for check in result.checks]
    assert "violations R1 à R5" in names and "score moyen du juge (finance)" in names


def _results(report: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = report["results"]
    return results


def _golden(report: dict[str, Any]) -> dict[str, Any]:
    return next(r for r in _results(report) if r["suite"] == "golden")


def _ruled(report: dict[str, Any]) -> dict[str, Any]:
    return next(r for r in _results(report) if r["suite"] != "golden")


BREAKS: dict[str, tuple[Callable[[dict[str, Any]], object], str]] = {
    "offline": (lambda r: r.update(mode="offline"), "mesure"),
    "no campaign": (lambda r: r.update(campaign=None), "campagne (journal d'audit)"),
    "campaign never opened": (
        lambda r: r.update(campaign="autre-campagne"),
        "campagne (journal d'audit)",
    ),
    "campaign opened after the report": (
        lambda r: r.update(created=(NOW - timedelta(hours=3)).isoformat()),
        "campagne (journal d'audit)",
    ),
    "other config": (lambda r: r.update(config="sha256:" + "0" * 64), "empreinte"),
    "no run": (lambda r: r.update(run=""), "run"),
    "mixed runs": (lambda r: _ruled(r).update(run="20261019-090000-ffff"), "run"),
    "future date": (lambda r: r.update(created=(NOW + timedelta(days=1)).isoformat()), "date"),
    "date without zone": (lambda r: r.update(created="2026-10-20T11:00:00"), "date"),
    "golden case missing": (lambda r: _results(r).remove(_golden(r)), "golden set finance"),
    "golden case in error": (lambda r: _golden(r).update(error="timeout"), "golden set finance"),
    "golden case not judged": (lambda r: _golden(r).update(judgement=None), "golden set finance"),
    "score out of range": (
        lambda r: _golden(r).update(judgement={"score": 9}),
        "golden set finance",
    ),
    "ruled case failed": (lambda r: _ruled(r).update(passed=False), "violations R1 à R5"),
    "ruled case missing": (lambda r: _results(r).remove(_ruled(r)), "violations R1 à R5"),
    "ruled case in error": (lambda r: _ruled(r).update(error="boom"), "violations R1 à R5"),
    "r5 breach": (lambda r: _golden(r).update(r5_breaches=1), "violations R1 à R5"),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_each_condition_of_the_rule_can_fail_it(
    name: str, config: Config, journal: AuditJournal
) -> None:
    report = _report(config.digest)
    change, check = BREAKS[name]
    change(report)
    result = _check(report, config, journal)
    assert not result.passed
    assert any(failed.startswith(check) for failed in _failed(result)), _failed(result)


def test_the_mean_score_counts_a_missing_case_as_zero(
    config: Config, journal: AuditJournal
) -> None:
    report = _report(config.digest)
    for result in _results(report):
        if result["suite"] == "golden":
            result["judgement"] = {"score": 1}
    assert _check(report, config, journal).passed
    _results(report).remove(_golden(report))  # the others at 1, this one at 0
    failed = _failed(_check(report, config, journal))
    mean_ok = 1 - 1 / len(GOLDEN) >= 0.85
    assert ("score moyen du juge (finance)" in failed) is not mean_ok
    assert "golden set finance" in failed


def test_a_mean_below_the_rule_fails_it(config: Config, journal: AuditJournal) -> None:
    report = _report(config.digest)
    for result in _results(report):
        if result["suite"] == "golden":
            result["judgement"] = {"score": "0.84"}
    assert _failed(_check(report, config, journal)) == ["score moyen du juge (finance)"]


def test_a_campaign_opened_offline_or_under_another_config_does_not_count(
    tmp_path: Path, config: Config
) -> None:
    audit = AuditJournal(tmp_path / "other" / "journal.jsonl")
    _open(audit, config.digest, mode="offline")
    _open(audit, "sha256:" + "1" * 64)
    result = _check(_report(config.digest), config, audit)
    assert _failed(result) == ["campagne (journal d'audit)"]


def test_a_broken_journal_proves_nothing(config: Config, journal: AuditJournal) -> None:
    report = _report(config.digest)
    _seal(report, config, journal)
    with journal.path.open("a", encoding="utf-8") as handle:
        handle.write('{"seq": 99}\n')
    result = _check(report, config, journal, seal=False)
    assert _failed(result) == ["campagne (journal d'audit)", "rapport (journal d'audit)"]
    assert "journal d'audit invalide" in result.checks[1].measured
    assert "journal d'audit invalide" in result.checks[2].measured


def test_an_edited_report_proves_nothing(config: Config, journal: AuditJournal) -> None:
    """Security review M2: the scores are the ones the campaign sealed when it wrote them."""
    report = _report(config.digest)
    _seal(report, config, journal)
    assert _check(report, config, journal, seal=False).passed
    reordered = dict(reversed(list(report.items())))  # same content, another layout
    assert report_digest(reordered) == report_digest(report)
    assert _check(reordered, config, journal, seal=False).passed

    _ruled(report).update(passed=True, r5_breaches=0, note="")  # any edit of the content
    result = _check(report, config, journal, seal=False)
    assert _failed(result) == ["rapport (journal d'audit)"]
    assert (
        result.checks[2].measured
        == f"run {RUN} : contenu différent de celui scellé par la campagne"
    )


def test_a_report_never_sealed_proves_nothing(config: Config, journal: AuditJournal) -> None:
    report = _report(config.digest)
    result = _check(report, config, journal, seal=False)
    assert _failed(result) == ["rapport (journal d'audit)"]
    assert result.checks[2].measured == f"run {RUN} : aucun rapport scellé par la campagne"
    seal_report(journal, report, campaign=CAMPAIGN, run=RUN, config="sha256:" + "2" * 64)
    seal_report(
        journal, report, campaign=CAMPAIGN, run="20261019-090000-ffff", config=config.digest
    )
    assert _failed(_check(report, config, journal, seal=False)) == ["rapport (journal d'audit)"]


def test_the_approval_must_cite_what_proves_the_rule(config: Config, journal: AuditJournal) -> None:
    report = _report(config.digest)
    cited = f"Run {RUN}, campagne {CAMPAIGN}, mode live, {config.digest}, rapport du 2026-10-20."
    assert _check(report, config, journal, approval=cited).passed
    result = _check(report, config, journal, approval=cited.replace("2026-10-20", "20/10"))
    assert _failed(result) == ["approbation"]
    assert result.checks[-1].measured == "ne cite pas : date"


def test_only_a_rule_without_a_marker_is_checked(config_dir: Path, journal: AuditJournal) -> None:
    config = load_config(config_dir)
    with pytest.raises(PromotionError, match="aucune règle"):
        check_promotion({}, config, domain="finance", level="N3", journal=journal, now=NOW)
    path = config_dir / "autonomy.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["promotion"]["finance"]["N0_to_N1"]["golden_min_score"] = "A_DEFINIR"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(BlockedFeatureError):
        _check(_report(config.digest), load_config(config_dir), journal)


def test_a_file_that_is_not_a_report_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text('{"run": "x"}', encoding="utf-8")
    with pytest.raises(PromotionError, match="n'est pas le rapport"):
        load_report(path)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(PromotionError, match="illisible"):
        load_report(path)


def _cli(report: Path, journal: AuditJournal, config_dir: Path, *more: str) -> Any:
    args = ["promotion", "check", "finance", "N1", "--report", str(report)]
    args += ["--journal", str(journal.path), "--config-dir", str(config_dir), *more]
    return CliRunner().invoke(app, args)


def _written(tmp_path: Path, report: dict[str, Any]) -> Path:
    path = tmp_path / "report.json"
    report["created"] = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat()
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_the_command_says_the_signature_stays_lucas_s(
    tmp_path: Path, config_dir: Path, config: Config
) -> None:
    audit = AuditJournal(tmp_path / "audit" / "journal.jsonl")
    _open(audit, config.digest, at=datetime.now().astimezone() - timedelta(hours=1))
    report = _report(config.digest)
    path = _written(tmp_path, report)
    _seal(report, config, audit)
    result = _cli(path, audit, config_dir)
    assert result.exit_code == 0, result.output
    assert "Règle prouvée" in result.output and "restent à Lucas" in result.output
    assert "✗" not in result.output

    report["mode"] = "offline"
    result = _cli(_written(tmp_path, report), audit, config_dir)
    assert result.exit_code == 1
    assert "✗ mesure : offline (attendu : live)" in result.output
    assert "pas de promotion" in result.output


def test_the_command_is_blocked_while_the_rule_holds_a_marker(
    tmp_path: Path, config_dir: Path, journal: AuditJournal, config: Config
) -> None:
    path = config_dir / "evals.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["thresholds"]["finance_golden_min_score"] = "A_DEFINIR"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    result = _cli(_written(tmp_path, _report(config.digest)), journal, config_dir)
    assert result.exit_code == 2
    assert "Bloqué (R7)" in result.output


def test_the_command_refuses_an_unreadable_report(
    tmp_path: Path, config_dir: Path, journal: AuditJournal
) -> None:
    result = _cli(tmp_path / "absent.json", journal, config_dir)
    assert result.exit_code == 1
    assert "Vérification impossible" in result.output
