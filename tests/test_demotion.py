"""Automatic demotions (ADR-067): one step down, never up, held until Lucas lifts them."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.audit import AuditJournal, verify
from core.config import load_config
from core.config.loader import PromotionN3N4
from core.governance.demotion import (
    DEMOTION_STATUS,
    Demotion,
    DemotionError,
    demote,
    demotions_path,
    floors,
    gate_domains,
    one_step_down,
    read_demotions,
)
from core.governance.signatures import effective_autonomy
from interfaces.cli import report as report_cli
from tests.test_reports import IN_WEEK, _invoke, _report, _write_json

NOW = datetime(2026, 10, 29, 7, 0).astimezone()
TRIGGERS = ("nightly_eval_failure", "calibration_drift")
DOMAINS = ("generaliste", "finance", "code", "juridique_fr")


def test_one_step_down_stops_at_n0() -> None:
    assert one_step_down("N3") == "N2"
    assert one_step_down("N1") == "N0"
    assert one_step_down("N0") is None


def test_demote_lowers_each_domain_by_one_step_and_journals_it(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path / "audit.jsonl")
    done = demote(
        tmp_path,
        journal,
        levels={"finance": "N3", "generaliste": "N1", "code": "N0"},
        trigger="nightly_eval_failure",
        triggers=TRIGGERS,
        reason="hebdo-2026-S43",
        now=NOW,
    )
    assert [(d.domain, d.from_level, d.to_level) for d in done] == [
        ("finance", "N3", "N2"),
        ("generaliste", "N1", "N0"),
    ]
    assert read_demotions(tmp_path) == tuple(done)
    assert verify(journal.path).ok
    entries = [json.loads(line) for line in journal.path.read_text(encoding="utf-8").splitlines()]
    payloads = [journal.read_payload(e["payload_ref"]) for e in entries]
    assert {e["actor"] for e in entries} == {"policy"}
    assert [p["status"] for p in payloads] == [DEMOTION_STATUS] * 2


def test_an_unknown_trigger_demotes_nothing(tmp_path: Path) -> None:
    with pytest.raises(DemotionError, match="déclencheur inconnu"):
        demote(
            tmp_path,
            AuditJournal(tmp_path / "audit.jsonl"),
            levels={"finance": "N3"},
            trigger="humeur",
            triggers=TRIGGERS,
            reason="r",
            now=NOW,
        )
    assert read_demotions(tmp_path) == ()


def test_floors_keep_the_lowest_level_per_domain() -> None:
    def d(domain: str, to: str) -> Demotion:
        return Demotion("t", domain, "N4", to, "nightly_eval_failure", "r")  # type: ignore[arg-type]

    assert floors(
        [d("finance", "N3"), d("finance", "N1"), d("finance", "N2"), d("code", "N1")]
    ) == {
        "finance": "N1",
        "code": "N1",
    }


@pytest.mark.parametrize(
    "content",
    [
        "{",
        '{"at": "t"}\n',
        json.dumps(
            {
                **{"at": "t", "domain": "x"},
                "from_level": "N9",
                "to_level": "N0",
                "trigger": "t",
                "reason": "r",
            }
        ),
    ],
)
def test_an_unreadable_file_is_reported(tmp_path: Path, content: str) -> None:
    path = demotions_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    assert isinstance(read_demotions(tmp_path), str)


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    line = json.dumps(
        {
            "at": "t",
            "domain": "code",
            "from_level": "N1",
            "to_level": "N0",
            "trigger": "nightly_eval_failure",
            "reason": "r",
        }
    )
    path = demotions_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(f"\n{line}\n\n", encoding="utf-8")
    found = read_demotions(tmp_path)
    assert isinstance(found, tuple)
    assert [d.domain for d in found] == ["code"]


def test_a_huge_file_is_not_read(tmp_path: Path) -> None:
    path = demotions_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b" " * (1024 * 1024 + 1))
    assert "trop volumineux" in str(read_demotions(tmp_path))


@pytest.mark.parametrize(
    ("missed", "expected"),
    [
        (["taux de réussite : finance_ordres"], {"finance"}),
        (
            ["taux de réussite : pack_juridique_fr", "taux de réussite : code"],
            {"juridique_fr", "code"},
        ),
        (["violations R5"], set(DOMAINS)),
        (["taux de réussite : finance", "sourçage"], set(DOMAINS)),
        ([], set()),
    ],
)
def test_a_missed_gate_demotes_its_domain_or_all(missed: list[str], expected: set[str]) -> None:
    assert gate_domains(missed, DOMAINS) == expected


def test_effective_autonomy_holds_a_demoted_domain(config_dir: Path, tmp_path: Path) -> None:
    autonomy = load_config(config_dir).autonomy
    assert effective_autonomy(autonomy, tmp_path).autonomy.domains["generaliste"].level == "N1"
    demote(
        tmp_path,
        AuditJournal(tmp_path / "audit.jsonl"),
        levels={"generaliste": "N1"},
        trigger="nightly_eval_failure",
        triggers=TRIGGERS,
        reason="r",
        now=NOW,
    )
    effective = effective_autonomy(autonomy, tmp_path)
    assert effective.autonomy.domains["generaliste"].level == "N0"
    assert "generaliste : N1, rétrogradé à N0" in effective.capped


def test_an_unreadable_file_holds_every_domain_at_n0(config_dir: Path, tmp_path: Path) -> None:
    path = demotions_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    effective = effective_autonomy(load_config(config_dir).autonomy, tmp_path)
    assert {spec.level for spec in effective.autonomy.domains.values()} == {"N0"}
    assert any("illisible" in problem for problem in effective.problems)


@pytest.mark.parametrize(
    "values",
    [
        {"approvals_min": 0},
        {"approvals_min": True},
        {"agreement_rate_min": 0},
        {"agreement_rate_min": 1.5},
        {"agreement_rate_min": float("nan")},
    ],
)
def test_the_n3_to_n4_rule_is_bounded(values: dict[str, object]) -> None:
    base = {"approvals_min": 10, "agreement_rate_min": 0.9, "manual_signature": "required"}
    PromotionN3N4.model_validate(base)
    with pytest.raises(ValidationError):
        PromotionN3N4.model_validate(base | values)


# The weekly report wires the scheduled eval failure (section 8.3) -------------------------------


@pytest.fixture
def cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(report_cli, "project_root", lambda: tmp_path)
    monkeypatch.setenv("CERVEAU_AUDIT_JOURNAL", str(tmp_path / "var" / "audit" / "audit.jsonl"))
    monkeypatch.setattr(report_cli, "_now", lambda: datetime(2026, 10, 29, 12, 0).astimezone())
    monkeypatch.setattr(report_cli, "_alert", lambda *args: None)
    report = tmp_path / report_cli.EVAL_REPORT
    report.parent.mkdir(parents=True)
    return report


def test_a_missed_gate_demotes_the_general_domain(cli: Path, config_dir: Path) -> None:
    _write_json(cli, _report(IN_WEEK, passed=False))
    result = _invoke("weekly", "--config-dir", str(config_dir))
    assert result.exit_code == 1
    assert "Rétrogradé : generaliste N1 → N0 (nightly_eval_failure)" in result.output
    root = cli.parents[3]
    found = read_demotions(root)
    assert isinstance(found, tuple)
    assert [(d.domain, d.trigger) for d in found] == [("generaliste", "nightly_eval_failure")]
    # A second failure finds the domain at N0 already: nothing goes lower.
    assert "Rétrogradé" not in _invoke("weekly", "--config-dir", str(config_dir)).output


def test_a_passed_week_demotes_nothing(cli: Path, config_dir: Path) -> None:
    _write_json(cli, _report(IN_WEEK))
    assert _invoke("weekly", "--config-dir", str(config_dir)).exit_code == 0
    assert read_demotions(cli.parents[3]) == ()


def test_a_demotion_that_cannot_be_written_fails(
    cli: Path, config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_json(cli, _report(IN_WEEK, passed=False))

    def refuse(*args: object, **kwargs: object) -> None:
        raise DemotionError("déclencheur inconnu : nightly_eval_failure")

    monkeypatch.setattr(report_cli, "demote", refuse)
    result = _invoke("weekly", "--config-dir", str(config_dir))
    assert result.exit_code == 1
    assert "Rétrogradation impossible" in result.output
