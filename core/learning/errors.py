"""Structured error records (ADR-011): what CERVEAU will learn from in phase 7.

Beside a request's ``DECISION`` entry, one ``ERROR`` entry per kind of error the request shows:
counts, codes and versions only, never a question, an answer, a note or a URL (R6, R11). In
phase 1 nothing reads them back to change CERVEAU; the learning loop and its gate are phase 7.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from core.audit.chain import AuditJournal

ERROR_EVENT = "ERROR"
ERROR_SCHEMA = 1
ErrorKind = Literal[
    "task_failed", "verification", "partial_answer", "budget_exceeded", "judge_score"
]
VERIFICATION_COUNTS = ("quotes_failed", "numbers_unmatched", "uncited_marked")
UNKNOWN = "inconnue"


@dataclass(frozen=True)
class ErrorRecord:
    kind: ErrorKind
    details: Mapping[str, Any] = field(default_factory=dict)  # counts and codes only

    def to_payload(self) -> dict[str, Any]:
        return {"error_schema": ERROR_SCHEMA, "kind": self.kind, "details": dict(self.details)}


def _section(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}


def _count(section: Mapping[str, Any], key: str) -> int:
    value = section.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _code(value: object) -> str:
    return value if isinstance(value, str) and value else UNKNOWN


def decision_errors(payload: Mapping[str, Any]) -> list[ErrorRecord]:
    """The errors a request's DECISION payload shows (``graph.audit_payload``), in a fixed order.

    A refusal is not an error: the guard, the policy or the kill switch did their job.
    """
    records: list[ErrorRecord] = []
    if payload.get("status") == "erreur":
        records.append(ErrorRecord("task_failed", {"error": _code(payload.get("error"))}))
    verification = _section(payload, "verification")
    counts = {key: _count(verification, key) for key in VERIFICATION_COUNTS}
    counts["links_removed"] = _count(_section(payload, "answer"), "links_removed")
    if any(counts.values()):
        details: dict[str, Any] = dict(counts)
        issues = _section(verification, "issues")
        details["issues"] = {str(kind): _count(issues, kind) for kind in sorted(issues)}
        if isinstance(confidence := verification.get("confidence"), str):
            details["confidence"] = confidence
        records.append(ErrorRecord("verification", details))
    planner = _section(payload, "planner")
    if planner.get("partial") is True:
        details = {
            "limit": _code(planner.get("limit")),
            "turns": _count(planner, "turns"),
            "searches": _count(planner, "searches"),
        }
        records.append(ErrorRecord("partial_answer", details))
    return records


def budget_error(exceeded: Iterable[Mapping[str, Any]]) -> ErrorRecord:
    """A request refused because a daily or monthly budget is reached (D9)."""
    return ErrorRecord("budget_exceeded", {"exceeded": [dict(alert) for alert in exceeded]})


def judge_error(
    case_id: str, score: Decimal, threshold: Decimal, grades: Mapping[str, int]
) -> ErrorRecord | None:
    """A live golden case the judge scored below the threshold of ``config/evals.yaml``."""
    if score >= threshold:
        return None
    details = {
        "eval_case": case_id,
        "score": str(score),
        "threshold": str(threshold),
        "grades": dict(sorted(grades.items())),
    }
    return ErrorRecord("judge_score", details)


def journal_errors(
    journal: AuditJournal,
    records: Iterable[ErrorRecord],
    *,
    actor: str,
    request_id: str | None,
    versions: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """One ``ERROR`` entry per record, in order; the entries written."""
    return [
        journal.append(
            actor=actor,
            event=ERROR_EVENT,
            request_id=request_id,
            versions=versions,
            payload=record.to_payload(),
            now=now,
        )
        for record in records
    ]
