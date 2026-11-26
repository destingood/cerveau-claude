"""The MCP bridge's calls of one day, counted from the audit journal (G-7, ADR-071)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.audit import AuditJournal
from core.budget.calls import CallCountError, DailyCalls

PREFIX = "mcp-appel-"
NOON = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


def journal(tmp_path: Path) -> AuditJournal:
    return AuditJournal(tmp_path / "audit" / "journal.jsonl")


def write(log: AuditJournal, request_id: str, at: datetime, event: str = "TOOL_CALL") -> None:
    log.append(actor="orchestrator", event=event, request_id=request_id, payload={}, now=at)


def test_a_call_counts_once_whatever_its_entries(tmp_path: Path) -> None:
    log = journal(tmp_path)
    write(log, f"{PREFIX}a", NOON)  # en_cours
    write(log, f"{PREFIX}a", NOON)  # its outcome
    write(log, f"{PREFIX}b", NOON)
    write(log, "mcp-plafond-c", NOON)  # refused at the cap: not a call
    write(log, "api-d", NOON)  # another interface
    write(log, f"{PREFIX}e", NOON, event="POLICY")
    assert DailyCalls(log.path, PREFIX, tz=UTC).count(NOON) == 2


def test_only_the_day_counts_and_a_new_day_starts_again(tmp_path: Path) -> None:
    log = journal(tmp_path)
    write(log, f"{PREFIX}hier", NOON - timedelta(days=1))
    write(log, f"{PREFIX}a", NOON)
    calls = DailyCalls(log.path, PREFIX, tz=UTC)
    assert calls.count(NOON) == 1
    write(log, f"{PREFIX}b", NOON)
    assert calls.count(NOON) == 2  # read from where it stopped
    assert calls.count(NOON + timedelta(days=1)) == 0


def test_an_absent_journal_counts_nothing(tmp_path: Path) -> None:
    assert DailyCalls(tmp_path / "absent.jsonl", PREFIX).count() == 0


def test_a_line_being_written_is_read_at_the_next_count(tmp_path: Path) -> None:
    log = journal(tmp_path)
    write(log, f"{PREFIX}a", NOON)
    whole = log.path.read_bytes()
    write(log, f"{PREFIX}b", NOON)
    last = log.path.read_bytes()[len(whole) :]
    log.path.write_bytes(whole + last[:20])
    calls = DailyCalls(log.path, PREFIX, tz=UTC)
    assert calls.count(NOON) == 1
    log.path.write_bytes(whole + last)
    assert calls.count(NOON) == 2


def test_an_unreadable_line_makes_the_count_unknown(tmp_path: Path) -> None:
    """R7: a count that cannot be trusted refuses the call rather than under-count."""
    log = journal(tmp_path)
    write(log, f"{PREFIX}a", NOON)
    log.path.write_bytes(log.path.read_bytes() + b'{"event": "TOOL_CALL", "mcp-appel-x"\n')
    with pytest.raises(CallCountError, match="illisible"):
        DailyCalls(log.path, PREFIX, tz=UTC).count(NOON)


def test_a_shorter_journal_is_read_again(tmp_path: Path) -> None:
    log = journal(tmp_path)
    write(log, f"{PREFIX}a", NOON)
    write(log, f"{PREFIX}b", NOON)
    calls = DailyCalls(log.path, PREFIX, tz=UTC)
    assert calls.count(NOON) == 2
    first = log.path.read_bytes().splitlines(keepends=True)[0]
    log.path.write_bytes(first)
    assert calls.count(NOON) == 1
