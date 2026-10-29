"""Forecast registry, ``var/learning/forecasts.db`` (section 11, ADR-064).

A forecast is a dated claim about the future: a probability that an event happens, or an estimate
of a value, with the day on which it can be checked. At or after that day it is resolved once,
with what actually happened, and only then scored (``core.learning.calibration``). Two tables,
insertion only, as for the order book (ADR-032): the database refuses an update, a deletion and a
second resolution, and a forecast whose day has not come cannot be resolved (R10: the outcome is
never known before the deadline it is judged against).

Each addition and each resolution writes a ``FORECAST`` entry to the audit journal within the
same write: identifier, domain, kind and due day, never the statement nor the values.
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import TracebackType
from typing import Literal
from uuid import UUID

from core.audit.chain import AuditJournal
from core.execution.uuid7 import uuid7
from core.finance.model import from_utc_text, local_date, plain_text, utc_text
from core.finance.schema import SchemaError, migrate, schema_version

FORECAST_EVENT = "FORECAST"
STATEMENT_CHARS = 500
SOURCE_CHARS = 200
Kind = Literal["probabilite", "estimation"]
KINDS: tuple[Kind, ...] = ("probabilite", "estimation")
Actor = Literal["owner", "orchestrator", "scheduler"]
_DOMAIN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
            """CREATE TABLE forecasts (
                forecast_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                domain TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('probabilite', 'estimation')),
                statement TEXT NOT NULL,
                value REAL NOT NULL,
                due_on TEXT NOT NULL,
                request_id TEXT,
                CHECK (kind = 'estimation' OR (value >= 0.0 AND value <= 1.0)),
                CHECK (due_on > substr(created_at, 1, 10))
            ) STRICT""",
            """CREATE TABLE resolutions (
                forecast_id TEXT PRIMARY KEY REFERENCES forecasts (forecast_id),
                resolved_at TEXT NOT NULL,
                outcome INTEGER CHECK (outcome IN (0, 1)),
                actual REAL,
                source TEXT NOT NULL,
                CHECK ((outcome IS NULL) <> (actual IS NULL))
            ) STRICT""",
            *(
                f"CREATE TRIGGER {table}_no_{verb.lower()} BEFORE {verb} ON {table} "
                f"BEGIN SELECT RAISE(ABORT, '{table} : insertion seule'); END"
                for table in ("forecasts", "resolutions")
                for verb in ("UPDATE", "DELETE")
            ),
        ),
    ),
)
LATEST_VERSION = MIGRATIONS[-1][0]


class ForecastError(Exception):
    """The forecast or its resolution is refused; nothing is written."""


@dataclass(frozen=True)
class Forecast:
    forecast_id: str
    created_at: datetime
    domain: str
    kind: Kind
    statement: str
    value: float
    due_on: date
    request_id: str | None
    resolved_at: datetime | None = None
    outcome: bool | None = None
    actual: float | None = None
    source: str | None = None

    @property
    def resolved(self) -> bool:
        return self.resolved_at is not None


def default_forecasts_path(root: Path) -> Path:
    return root / "var" / "learning" / "forecasts.db"


def _connect(target: str, *, uri: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(target, uri=uri, autocommit=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _text(value: str, name: str, limit: int) -> str:
    value = value.strip()
    if not 1 <= len(value) <= limit:
        raise ForecastError(f"{name} : de 1 à {limit} caractères")
    try:
        return plain_text(value)
    except ValueError as exc:
        raise ForecastError(f"{name} refusé(e) : {exc}") from exc


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not math.isfinite(value):
        raise ForecastError(f"{name} : nombre fini attendu")
    return float(value)


def _row(row: sqlite3.Row) -> Forecast:
    outcome = row["outcome"]
    return Forecast(
        forecast_id=row["forecast_id"],
        created_at=from_utc_text(row["created_at"]),
        domain=row["domain"],
        kind=row["kind"],
        statement=row["statement"],
        value=row["value"],
        due_on=date.fromisoformat(row["due_on"]),
        request_id=row["request_id"],
        resolved_at=from_utc_text(row["resolved_at"]) if row["resolved_at"] else None,
        outcome=None if outcome is None else bool(outcome),
        actual=row["actual"],
        source=row["source"],
    )


_SELECT = (
    "SELECT f.*, r.resolved_at, r.outcome, r.actual, r.source FROM forecasts f "
    "LEFT JOIN resolutions r ON r.forecast_id = f.forecast_id"
)


class ForecastStore:
    """``with ForecastStore.open(path, journal=...) as store:``, then ``store.add(...)``."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        journal: AuditJournal | None,
        read_only: bool,
        ids: Callable[[], UUID] = uuid7,
    ) -> None:
        self._conn = conn
        self._journal = journal
        self._ids = ids
        self.read_only = read_only
        if read_only:
            conn.execute("PRAGMA query_only = ON")
            version = schema_version(conn)
            if version != LATEST_VERSION:
                raise SchemaError(f"prévisions au schéma {version}, attendu {LATEST_VERSION}")
        else:
            migrate(conn, MIGRATIONS)

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        journal: AuditJournal | None = None,
        read_only: bool = False,
        ids: Callable[[], UUID] = uuid7,
    ) -> ForecastStore:
        if read_only:
            if not path.is_file():
                raise ForecastError(f"registre des prévisions absent ({path.name})")
            conn = _connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = _connect(str(path), uri=False)
        try:
            return cls(conn, journal=journal, read_only=read_only, ids=ids)
        except BaseException:
            conn.close()
            raise

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ForecastStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @contextmanager
    def _write(self) -> Iterator[None]:
        if self.read_only:
            raise ForecastError("registre ouvert en lecture seule")
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def _audit(self, actor: Actor, payload: dict[str, object], now: datetime) -> None:
        if self._journal is not None:  # inside the transaction: a refused entry rolls back
            self._journal.append(actor=actor, event=FORECAST_EVENT, payload=payload, now=now)

    def add(
        self,
        *,
        domain: str,
        kind: Kind,
        statement: str,
        value: float,
        due_on: date,
        now: datetime,
        actor: Actor = "owner",
        request_id: str | None = None,
    ) -> Forecast:
        if not _DOMAIN.fullmatch(domain):
            raise ForecastError(f"domaine invalide : {domain!r}")
        if kind not in KINDS:
            raise ForecastError(f"type inconnu : {kind!r} (probabilite ou estimation)")
        value = _finite(value, "valeur")
        if kind == "probabilite" and not 0.0 <= value <= 1.0:
            raise ForecastError("une probabilité est comprise entre 0 et 1")
        statement = _text(statement, "énoncé", STATEMENT_CHARS)
        created = utc_text(now)
        if due_on <= date.fromisoformat(created[:10]) or due_on <= local_date(now):
            raise ForecastError("l'échéance doit être postérieure à aujourd'hui")
        forecast_id = str(self._ids())
        with self._write():
            self._conn.execute(
                "INSERT INTO forecasts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    forecast_id,
                    created,
                    domain,
                    kind,
                    statement,
                    value,
                    due_on.isoformat(),
                    request_id,
                ),
            )
            self._audit(
                actor,
                {
                    "action": "ajout",
                    "forecast_id": forecast_id,
                    "domain": domain,
                    "kind": kind,
                    "due_on": due_on.isoformat(),
                },
                now,
            )
        return self.get(forecast_id)

    def get(self, forecast_id: str) -> Forecast:
        row = self._conn.execute(_SELECT + " WHERE f.forecast_id = ?", (forecast_id,)).fetchone()
        if row is None:
            raise ForecastError(f"prévision inconnue : {forecast_id}")
        return _row(row)

    def resolve(
        self,
        forecast_id: str,
        *,
        outcome: bool | None = None,
        actual: float | None = None,
        source: str,
        now: datetime,
        actor: Actor = "owner",
    ) -> Forecast:
        forecast = self.get(forecast_id)
        if forecast.resolved:
            raise ForecastError("prévision déjà résolue")
        if local_date(now) < forecast.due_on:
            raise ForecastError(
                f"échéance au {forecast.due_on.isoformat()} : résolution impossible avant (R10)"
            )
        if forecast.kind == "probabilite":
            if outcome is None or actual is not None:
                raise ForecastError("une probabilité se résout par oui ou non")
        else:
            if actual is None or outcome is not None:
                raise ForecastError("une estimation se résout par la valeur observée")
            actual = _finite(actual, "valeur observée")
        source = _text(source, "source", SOURCE_CHARS)
        with self._write():
            self._conn.execute(
                "INSERT INTO resolutions VALUES (?, ?, ?, ?, ?)",
                (
                    forecast_id,
                    utc_text(now),
                    None if outcome is None else int(outcome),
                    actual,
                    source,
                ),
            )
            self._audit(
                actor,
                {
                    "action": "resolution",
                    "forecast_id": forecast_id,
                    "domain": forecast.domain,
                    "kind": forecast.kind,
                    "due_on": forecast.due_on.isoformat(),
                },
                now,
            )
        return self.get(forecast_id)

    def forecasts(self, *, domain: str | None = None) -> list[Forecast]:
        query, params = _SELECT, ()
        if domain is not None:
            query, params = query + " WHERE f.domain = ?", (domain,)
        rows = self._conn.execute(query + " ORDER BY f.due_on, f.forecast_id", params)
        return [_row(row) for row in rows]

    def overdue(self, now: datetime) -> list[Forecast]:
        """Unresolved forecasts whose day has come: to resolve."""
        today = local_date(now)
        return [f for f in self.forecasts() if not f.resolved and f.due_on <= today]

    def probability_pairs(
        self, *, domain: str | None = None, since: date | None = None
    ) -> list[tuple[float, bool]]:
        return [
            (f.value, bool(f.outcome))
            for f in self.forecasts(domain=domain)
            if f.kind == "probabilite" and f.resolved and (since is None or f.due_on >= since)
        ]

    def estimate_pairs(
        self, *, domain: str | None = None, since: date | None = None
    ) -> list[tuple[float, float]]:
        return [
            (f.value, float(f.actual))
            for f in self.forecasts(domain=domain)
            if f.kind == "estimation"
            and f.actual is not None
            and (since is None or f.due_on >= since)
        ]
