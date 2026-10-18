"""Versioned schema of the finance store and its idempotent migrations (ADR-012, D6).

Each migration is a list of statements applied in one transaction together with its row in
``schema_version``; a database newer than the code is refused rather than guessed at.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from core.finance.model import utc_text

# Market tables are bitemporal and append-only: a correction is a new revision, never an UPDATE.
_MARKET_COLUMNS = """
    revision INTEGER NOT NULL CHECK (revision >= 1),
    source TEXT NOT NULL,
    published_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
"""

MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
            """CREATE TABLE instruments (
                instrument_id TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                valid_to TEXT,
                isin TEXT,
                name TEXT NOT NULL,
                asset_class TEXT NOT NULL,
                currency TEXT NOT NULL,
                mic TEXT NOT NULL,
                sector TEXT NOT NULL,
                country TEXT NOT NULL,
                duration TEXT,
                recorded_at TEXT NOT NULL,
                PRIMARY KEY (instrument_id, valid_from),
                CHECK (valid_to IS NULL OR valid_to > valid_from)
            ) STRICT""",
            """CREATE TABLE instrument_ids (
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                instrument_id TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                PRIMARY KEY (source, source_id)
            ) STRICT""",
            f"""CREATE TABLE prices (
                instrument_id TEXT NOT NULL,
                session TEXT NOT NULL,
                close REAL NOT NULL CHECK (close > 0),
                volume INTEGER CHECK (volume >= 0),
                currency TEXT NOT NULL,
                {_MARKET_COLUMNS}
                PRIMARY KEY (instrument_id, session, revision)
            ) STRICT""",
            f"""CREATE TABLE corporate_actions (
                instrument_id TEXT NOT NULL,
                ex_date TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('split', 'dividend')),
                value REAL NOT NULL CHECK (value > 0),
                currency TEXT,
                {_MARKET_COLUMNS}
                PRIMARY KEY (instrument_id, ex_date, kind, revision)
            ) STRICT""",
            f"""CREATE TABLE fx_rates (
                currency TEXT NOT NULL,
                session TEXT NOT NULL,
                rate REAL NOT NULL CHECK (rate > 0),
                {_MARKET_COLUMNS}
                PRIMARY KEY (currency, session, revision)
            ) STRICT""",
            f"""CREATE TABLE rates (
                series_id TEXT NOT NULL,
                session TEXT NOT NULL,
                value_pct REAL NOT NULL,
                {_MARKET_COLUMNS}
                PRIMARY KEY (series_id, session, revision)
            ) STRICT""",
            # Quality sub-scores in [0, 1]; NULL when a check cannot be evaluated (R7).
            """CREATE TABLE quality_scores (
                series_id TEXT NOT NULL,
                as_of TEXT NOT NULL,
                gaps REAL,
                corporate_actions REAL,
                outliers REAL,
                freshness REAL,
                score REAL,
                details TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                PRIMARY KEY (series_id, as_of)
            ) STRICT""",
        ),
    ),
    (
        2,
        # Lucas's ledger and his broker's statements (ADR-018): every imported file is kept, so
        # the effective history can be replayed as it was known at any time. Decimals are text.
        (
            """CREATE TABLE portfolio_files (
                sha256 TEXT PRIMARY KEY CHECK (length(sha256) = 64),
                kind TEXT NOT NULL CHECK (kind IN ('transactions', 'statement')),
                file_name TEXT NOT NULL,
                format TEXT NOT NULL,
                rows INTEGER NOT NULL CHECK (rows >= 0),
                imported_at TEXT NOT NULL
            ) STRICT""",
            """CREATE TABLE transactions (
                file_sha256 TEXT NOT NULL REFERENCES portfolio_files (sha256),
                line INTEGER NOT NULL,
                trade_date TEXT NOT NULL,
                account TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (
                    kind IN ('buy', 'sell', 'dividend', 'fee', 'deposit', 'withdrawal', 'fx')
                ),
                asset TEXT,
                quantity TEXT NOT NULL,
                price TEXT,
                currency TEXT NOT NULL,
                fees TEXT NOT NULL,
                amount TEXT,
                label TEXT,
                PRIMARY KEY (file_sha256, line)
            ) STRICT""",
            """CREATE TABLE statement_lines (
                file_sha256 TEXT NOT NULL REFERENCES portfolio_files (sha256),
                line INTEGER NOT NULL,
                statement_date TEXT NOT NULL,
                account TEXT NOT NULL,
                nature TEXT NOT NULL CHECK (nature IN ('security', 'cash')),
                asset TEXT NOT NULL,
                quantity TEXT NOT NULL,
                PRIMARY KEY (file_sha256, line)
            ) STRICT""",
        ),
    ),
)
LATEST_VERSION = MIGRATIONS[-1][0]
# The four sub-scores of ``quality_scores``, in column order (ADR-016).
QUALITY_COLUMNS = ("gaps", "corporate_actions", "outliers", "freshness")


class SchemaError(Exception):
    """The database cannot be used by this version of the code."""


def schema_version(conn: sqlite3.Connection) -> int:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
    ).fetchone()
    if exists is None:
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0] or 0)


def migrate(
    conn: sqlite3.Connection,
    migrations: tuple[tuple[int, tuple[str, ...]], ...] = MIGRATIONS,
    *,
    now: datetime | None = None,
) -> int:
    """Apply the missing migrations in order; running it again changes nothing."""
    latest = migrations[-1][0]
    current = schema_version(conn)
    if current > latest:
        raise SchemaError(
            f"base au schéma {current}, plus récent que ce code ({latest}) : mettre CERVEAU à jour"
        )
    for version, statements in migrations:
        if version <= current:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version ("
                "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL) STRICT"
            )
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, utc_text(now or datetime.now(UTC))),
            )
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        current = version
    return current
