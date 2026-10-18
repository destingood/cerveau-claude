"""Error records and feedback (ADR-011): what CERVEAU will learn from in phase 7."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from typer.testing import CliRunner

from core.audit import AuditJournal, verify
from core.audit.chain import AuditError
from core.guardrails.input import strip_invisible
from core.guardrails.secrets import MASK, SECRET_LIKE, mask_secrets
from core.learning import (
    FeedbackError,
    budget_error,
    decision_errors,
    give_feedback,
    journal_errors,
    judge_error,
)
from core.learning.feedback import MAX_NOTE_CHARS, NOTE_SOURCE
from interfaces.cli import main as cli
from interfaces.cli.main import app

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
FAKE_KEY = "sk-ant-" + "x" * 24  # not a real key: the shape the masks look for
runner = CliRunner()


class FakePseudonymiser:
    """Replaces « Jean Dupont » like Presidio would; counts per entity type."""

    def __init__(self) -> None:
        self.calls = 0
        self._counts: dict[str, int] = {}

    def pseudonymise(self, text: str) -> str:
        self.calls += 1
        found = text.count("Jean Dupont")
        if found:
            self._counts["PERSON"] = self._counts.get("PERSON", 0) + found
        return text.replace("Jean Dupont", "<PERSON_1>")

    def counts(self) -> dict[str, int]:
        return dict(self._counts)


@pytest.fixture
def journal(tmp_path: Path) -> AuditJournal:
    return AuditJournal(tmp_path / "audit" / "journal.jsonl")


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return tmp_path / "var" / "feedback" / "feedback.jsonl"


def _answered(journal: AuditJournal, request_id: str = "req-1") -> None:
    journal.append(
        actor="orchestrator",
        event="DECISION",
        request_id=request_id,
        payload={"status": "complete"},
    )


def _entries(journal: AuditJournal) -> list[dict[str, Any]]:
    return [json.loads(line) for line in journal.path.read_text(encoding="utf-8").splitlines()]


# --- error records from a DECISION payload -----------------------------------------------------


def test_a_clean_decision_shows_no_error() -> None:
    payload = {
        "status": "complete",
        "verification": {"quotes_failed": 0, "numbers_unmatched": 0, "uncited_marked": 0},
        "answer": {"links_removed": 0},
        "planner": {"partial": False, "limit": None},
    }
    assert decision_errors(payload) == []


@pytest.mark.parametrize("status", ["refus", "clarification", "campagne_eval"])
def test_a_refusal_or_a_question_back_is_not_an_error(status: str) -> None:
    assert decision_errors({"status": status}) == []


def test_each_kind_of_error_is_one_record_in_a_fixed_order() -> None:
    payload = {
        "status": "erreur",
        "error": "RuntimeError",
        "verification": {
            "quotes_failed": 1,
            "numbers_unmatched": 2,
            "uncited_marked": 0,
            "confidence": "faible",
            "issues": {"citation_inexacte": 1, "chiffre_non_source": 2},
        },
        "answer": {"links_removed": 3},
        "planner": {"partial": True, "limit": "tours", "turns": 15, "searches": 15},
    }
    records = [r.to_payload() for r in decision_errors(payload)]
    assert records == [
        {"error_schema": 1, "kind": "task_failed", "details": {"error": "RuntimeError"}},
        {
            "error_schema": 1,
            "kind": "verification",
            "details": {
                "quotes_failed": 1,
                "numbers_unmatched": 2,
                "uncited_marked": 0,
                "links_removed": 3,
                "issues": {"chiffre_non_source": 2, "citation_inexacte": 1},
                "confidence": "faible",
            },
        },
        {
            "error_schema": 1,
            "kind": "partial_answer",
            "details": {"limit": "tours", "turns": 15, "searches": 15},
        },
    ]


def test_a_removed_link_alone_is_a_verification_error() -> None:
    [record] = decision_errors({"status": "complete", "answer": {"links_removed": 1}})
    assert record.kind == "verification" and record.details["links_removed"] == 1


def test_malformed_values_count_as_nothing() -> None:
    payload = {
        "status": "erreur",
        "verification": {"quotes_failed": True, "numbers_unmatched": "2", "issues": "x"},
        "answer": ["links_removed"],
        "planner": {"partial": "oui"},
    }
    records = [r.to_payload() for r in decision_errors(payload)]
    assert records == [{"error_schema": 1, "kind": "task_failed", "details": {"error": "inconnue"}}]


JSON_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=8),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=8), inner),
    max_leaves=8,
)
PAYLOAD_KEYS = st.sampled_from(["status", "error", "verification", "answer", "planner", "x"])


@given(st.dictionaries(PAYLOAD_KEYS, JSON_VALUES))
def test_any_payload_gives_journalable_records(payload: dict[str, Any]) -> None:
    for record in decision_errors(payload):
        json.dumps(record.to_payload(), allow_nan=False)


def test_judge_error_only_below_the_threshold() -> None:
    grades = {"sourcage": 1, "exactitude": 0}
    assert judge_error("gen-001", Decimal("0.70"), Decimal("0.70"), grades) is None
    record = judge_error("gen-001", Decimal("0.25"), Decimal("0.70"), grades)
    assert record is not None
    assert record.to_payload()["details"] == {
        "eval_case": "gen-001",
        "score": "0.25",
        "threshold": "0.70",
        "grades": {"exactitude": 0, "sourcage": 1},
    }


def test_error_entries_keep_the_chain_valid(journal: AuditJournal) -> None:
    _answered(journal)
    alert = {"period": "jour", "period_key": "2026-10-18", "pct": 100}
    written = journal_errors(
        journal,
        [budget_error([alert])],
        actor="policy",
        request_id="req-1",
        versions={"config": "sha256:abc"},
        now=NOW,
    )
    [entry] = written
    assert (entry["event"], entry["actor"], entry["versions"]) == (
        "ERROR",
        "policy",
        {"config": "sha256:abc"},
    )
    assert journal.read_payload(entry["payload_ref"])["details"] == {"exceeded": [alert]}
    assert verify(journal.path).ok


# --- feedback ----------------------------------------------------------------------------------


def test_a_bare_verdict_is_journaled_without_a_pseudonymiser(
    journal: AuditJournal, store: Path
) -> None:
    _answered(journal)

    def no_presidio() -> FakePseudonymiser:
        raise AssertionError("no note: Presidio must not load")

    entry = give_feedback(journal, store, "req-1", "bon", pseudonymiser=no_presidio, now=NOW)
    assert (entry["actor"], entry["event"], entry["request_id"]) == ("lucas", "FEEDBACK", "req-1")
    assert journal.read_payload(entry["payload_ref"]) == {
        "feedback_schema": 1,
        "verdict": "bon",
        "note": None,
    }
    assert not store.exists()
    assert verify(journal.path).ok


def test_a_note_is_pseudonymised_masked_and_kept_out_of_the_journal(
    journal: AuditJournal, store: Path
) -> None:
    _answered(journal)
    fake = FakePseudonymiser()
    note = f"Jean\u200b Dupont s'est trompé ; ma clé {FAKE_KEY} \u202equi traîne. "
    note = note.replace("Jean\u200b Dupont", "Jean Dupont\u200b")
    entry = give_feedback(journal, store, "req-1", "mauvais", note, pseudonymiser=lambda: fake)
    counts = journal.read_payload(entry["payload_ref"])["note"]
    assert counts == {
        "chars": len(strip_invisible(note)[0]),
        "removed_characters": 2,
        "secrets_masked": 1,
        "pii": {"PERSON": 1},
    }
    [record] = [json.loads(line) for line in store.read_text(encoding="utf-8").splitlines()]
    assert record["note"] == f"<PERSON_1> s'est trompé ; ma clé {MASK} qui traîne."
    assert record["untrusted"] is True and record["source"] == NOTE_SOURCE  # R5
    assert (record["seq"], record["ts"]) == (entry["seq"], entry["ts"])
    assert record["verdict"] == "mauvais"
    raw = journal.path.read_text(encoding="utf-8") + "".join(
        p.read_text(encoding="utf-8") for p in journal.payload_dir.glob("*.json")
    )
    for leak in ("Jean", "Dupont", "trompé", FAKE_KEY):
        assert leak not in raw
    assert FAKE_KEY not in store.read_text(encoding="utf-8")


def test_a_blank_note_is_no_note(journal: AuditJournal, store: Path) -> None:
    _answered(journal)
    entry = give_feedback(journal, store, "req-1", "bon", " \u200b\n", pseudonymiser=None)
    assert journal.read_payload(entry["payload_ref"])["note"] is None
    assert not store.exists()


@pytest.mark.parametrize(
    ("request_id", "verdict", "message"),
    [
        ("req-2", "bon", "absente du journal"),
        ("../etc", "bon", "identifiant de requête invalide"),
        ("req 1", "bon", "identifiant de requête invalide"),
        ("req-1", "excellent", "verdict inconnu"),
    ],
)
def test_refused_feedback_writes_nothing(
    journal: AuditJournal, store: Path, request_id: str, verdict: str, message: str
) -> None:
    _answered(journal)
    before = journal.path.read_bytes()
    with pytest.raises(FeedbackError, match=message):
        give_feedback(journal, store, request_id, verdict, "note", pseudonymiser=FakePseudonymiser)
    assert journal.path.read_bytes() == before and not store.exists()


def test_only_the_orchestrator_decision_makes_a_request_known(
    journal: AuditJournal, store: Path
) -> None:
    journal.append(actor="policy", event="POLICY", request_id="req-1")
    journal.append(actor="orchestrator", event="TOOL_CALL", request_id="req-1")
    with pytest.raises(FeedbackError, match="absente du journal"):
        give_feedback(journal, store, "req-1", "bon")


def test_a_note_needs_the_pseudonymiser(journal: AuditJournal, store: Path) -> None:
    _answered(journal)
    with pytest.raises(FeedbackError, match="pseudonymisation indisponible"):
        give_feedback(journal, store, "req-1", "bon", "une note")
    too_long = "a" * (MAX_NOTE_CHARS + 1)
    with pytest.raises(FeedbackError, match="note trop longue"):
        give_feedback(journal, store, "req-1", "bon", too_long, pseudonymiser=FakePseudonymiser)
    assert len(_entries(journal)) == 1 and not store.exists()


def test_an_unreadable_journal_refuses_feedback(journal: AuditJournal, store: Path) -> None:
    _answered(journal, "req-0")
    _answered(journal, "req-0")
    _answered(journal)
    lines = journal.path.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[1] = "{pas du json\n"  # a damaged entry before the request's decision
    journal.path.write_text("".join(lines), encoding="utf-8")
    with pytest.raises(FeedbackError, match="ligne 2"):
        give_feedback(journal, store, "req-1", "bon")


def test_an_unreadable_tail_refuses_feedback(journal: AuditJournal, store: Path) -> None:
    _answered(journal)
    with journal.path.open("a", encoding="utf-8") as f:
        f.write("{pas du json\n")
    with pytest.raises(AuditError, match="illisible"):
        give_feedback(journal, store, "req-1", "mauvais", "note", pseudonymiser=FakePseudonymiser)
    assert not store.exists()  # the note follows the journal entry, never precedes it


# --- shared guard-rails ------------------------------------------------------------------------


def test_secret_pattern_is_the_one_of_the_hooks() -> None:
    path = REPO / ".claude" / "hooks" / "_common.py"
    spec = importlib.util.spec_from_file_location("hooks_common_for_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._SECRET_LIKE.pattern == SECRET_LIKE.pattern


@pytest.mark.parametrize(
    "text",
    ["ghp_" + "a1B2" * 6, "AKIA" + "ABCDEFGHIJKLMNOP", "xoxb-" + "1234567890ab"],
)
def test_secret_like_strings_are_masked(text: str) -> None:
    assert mask_secrets(f"avant {text} après") == (f"avant {MASK} après", 1)


def test_hashes_and_paths_are_not_secrets() -> None:
    text = "sha256:" + "ab12" * 16 + " C:/Users/User/Documents/cerveau-plateforme/core/x.py"
    assert mask_secrets(text) == (text, 0)


def test_strip_invisible_counts_what_it_removes() -> None:
    assert strip_invisible("  a\u200bb\r\nc\U000e0041 ") == ("ab\nc", 2)


# --- cerveau feedback --------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CERVEAU_HOME", str(tmp_path))
    monkeypatch.setenv("CERVEAU_AUDIT_JOURNAL", str(tmp_path / "audit" / "journal.jsonl"))
    _answered(AuditJournal(tmp_path / "audit" / "journal.jsonl"))
    return tmp_path


def _events(home: Path) -> list[str]:
    return [e["event"] for e in _entries(AuditJournal(home / "audit" / "journal.jsonl"))]


def test_cli_journals_a_verdict(home: Path) -> None:
    result = runner.invoke(app, ["feedback", "req-1", "mauvais"])
    assert result.exit_code == 0, result.output
    assert "Retour « mauvais » enregistré pour la requête req-1." in result.stdout
    assert _events(home) == ["DECISION", "FEEDBACK"]
    assert not (home / "var" / "feedback").exists()


def test_cli_refuses_an_unknown_request(home: Path) -> None:
    result = runner.invoke(app, ["feedback", "req-9", "bon"])
    assert result.exit_code == 1
    assert "Refus : " in result.stderr and "absente du journal" in result.stderr
    assert _events(home) == ["DECISION"]


def test_cli_refuses_an_unknown_verdict(home: Path) -> None:
    assert runner.invoke(app, ["feedback", "req-1", "excellent"]).exit_code == 2  # usage error
    assert _events(home) == ["DECISION"]


def test_cli_blocks_a_note_while_pii_is_unset(home: Path) -> None:
    config_dir = str(REPO / "config")  # pii.score_threshold: A_DEFINIR
    result = runner.invoke(
        app, ["feedback", "req-1", "bon", "une note", "--config-dir", config_dir]
    )
    assert result.exit_code == 2, result.output
    assert "Bloqué (R7)" in result.stderr
    assert _events(home) == ["DECISION"]
    assert not (home / "var" / "feedback").exists()


def test_cli_keeps_a_note_outside_the_journal(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "note_pseudonymiser", lambda _config_dir: FakePseudonymiser)
    note = f"Jean Dupont a eu tort, clé {FAKE_KEY}"
    result = runner.invoke(app, ["feedback", "req-1", "mauvais", note])
    assert result.exit_code == 0, result.output
    assert "1 donnée(s) personnelle(s) pseudonymisée(s), 1 secret(s) masqué(s)" in result.stdout
    [record] = (
        (home / "var" / "feedback" / "feedback.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert json.loads(record)["note"] == f"<PERSON_1> a eu tort, clé {MASK}"
    assert _events(home) == ["DECISION", "FEEDBACK"]
