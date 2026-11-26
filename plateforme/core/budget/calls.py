"""Tool calls of the MCP bridge in one day, counted from the audit journal (G-7, ADR-071).

The journal is the authority: a restart of the bridge, or a second Claude Code session with its
own bridge, never resets the day's count. A call is one ``request_id`` of the bridge's prefix
among the day's ``TOOL_CALL`` entries, whatever the number of its entries (``en_cours``, then its
outcome) and whatever its outcome: a refusal is counted too.

The journal is read once from its start, then only what was appended since the last count; a new
day, or a journal shorter than what was read, starts again from the start. A line that cannot be
read makes the count unknown, and an unknown count refuses the call (R7). Days follow the
machine's local time unless a time zone is given, as the spending ledger does (ADR-005).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from pathlib import Path


class CallCountError(Exception):
    """The journal cannot be read reliably: the day's count is unknown."""


@dataclass
class DailyCalls:
    """The distinct ``request_id`` starting with ``prefix`` in the day's ``TOOL_CALL`` entries."""

    path: Path
    prefix: str
    tz: tzinfo | None = None  # None: the machine's local time
    _day: date | None = field(default=None, init=False, repr=False)
    _offset: int = field(default=0, init=False, repr=False)
    _seen: set[str] = field(default_factory=set, init=False, repr=False)

    def count(self, now: datetime | None = None) -> int:
        day = (now or datetime.now()).astimezone(self.tz).date()
        try:
            size = self.path.stat().st_size if self.path.exists() else 0
        except OSError as exc:
            raise CallCountError(f"journal d'audit illisible ({type(exc).__name__})") from None
        if day != self._day or size < self._offset:
            self._day, self._offset, self._seen = day, 0, set()
        if size > self._offset:
            self._read(day)
        return len(self._seen)

    def _read(self, day: date) -> None:
        try:
            with self.path.open("rb") as journal:
                journal.seek(self._offset)
                data = journal.read()
        except OSError as exc:
            raise CallCountError(f"journal d'audit illisible ({type(exc).__name__})") from None
        complete = data.rfind(b"\n") + 1  # a line being written is read at the next count
        marker = self.prefix.encode("utf-8")
        for number, line in enumerate(data[:complete].splitlines(), start=1):
            if b"TOOL_CALL" not in line or marker not in line:
                continue  # most entries: no need to parse them
            try:
                entry = json.loads(line)
                if entry["event"] != "TOOL_CALL":
                    continue
                request_id = entry["request_id"]
                at = datetime.fromisoformat(entry["ts"]).astimezone(self.tz).date()
            except (ValueError, KeyError, TypeError):
                raise CallCountError(
                    f"journal d'audit illisible après l'octet {self._offset} (ligne {number})"
                ) from None
            if at == day and isinstance(request_id, str) and request_id.startswith(self.prefix):
                self._seen.add(request_id)
        self._offset += complete
