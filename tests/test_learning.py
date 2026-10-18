"""Error records (ADR-011): what CERVEAU will learn from in phase 7."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.audit import AuditJournal, verify
from core.learning import (
    budget_error,
    decision_errors,
    journal_errors,
    judge_error,
)

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


@pytest.fixture
def journal(tmp_path: Path) -> AuditJournal:
    return AuditJournal(tmp_path / "audit" / "journal.jsonl")


def _answered(journal: AuditJournal, request_id: str = "req-1") -> None:
    journal.append(
        actor="orchestrator",
        event="DECISION",
        request_id=request_id,
        payload={"status": "complete"},
    )


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
