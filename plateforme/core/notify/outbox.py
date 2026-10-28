"""The Discord channel (ADR-037, ADR-038): an outbox the local API reads for the bot.

The bot is a thin client of the API and CERVEAU never connects to Discord itself (D22): an alert
goes to ``var/notify/outbox.db``, in append only, and the API hands the bot what it has not seen
yet, by sequence number. A process that sends holds no connection between two alerts.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from core.finance.model import from_utc_text, utc_text
from core.notify.alerts import Alert

BUSY_TIMEOUT_SECONDS = 1.0  # a locked outbox fails fast: an alert never holds a stop

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    severity INTEGER NOT NULL,
    ref TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS alerts_no_update BEFORE UPDATE ON alerts
BEGIN SELECT RAISE(ABORT, 'outbox en ajout seul'); END;
CREATE TRIGGER IF NOT EXISTS alerts_no_delete BEFORE DELETE ON alerts
BEGIN SELECT RAISE(ABORT, 'outbox en ajout seul'); END;
"""


def default_outbox_path(project_root: Path) -> Path:
    return project_root / "var" / "notify" / "outbox.db"


@dataclass(frozen=True)
class DiscordOutbox:
    path: Path
    channel: str = "discord"

    def send(self, alert: Alert) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_SECONDS)) as conn, conn:
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT INTO alerts (at, kind, severity, ref) VALUES (?, ?, ?, ?)",
                (utc_text(alert.at), alert.kind, alert.severity, alert.ref),
            )


@dataclass(frozen=True)
class Posted:
    seq: int
    alert: Alert


def read_outbox(path: Path, *, after: int = 0, limit: int = 50) -> list[Posted]:
    """The alerts after ``after``, oldest first; none while the outbox does not exist."""
    if not path.is_file():
        return []
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
        rows = conn.execute(
            "SELECT seq, at, kind, severity, ref FROM alerts WHERE seq > ? ORDER BY seq LIMIT ?",
            (after, limit),
        ).fetchall()
    return [
        Posted(seq, Alert(kind, severity, ref, from_utc_text(at)))
        for seq, at, kind, severity, ref in rows
    ]
