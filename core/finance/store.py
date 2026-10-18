"""The point-in-time finance store over SQLite (ADR-012, R10).

Writes happen in one transaction per batch and only through the CLI; the MCP tools open the file
read-only. A market record is never updated: a different value for the same key is stored as a
new revision, and a read at ``as_of`` returns, for each key, the latest revision published by then
(and, in strict mode, also ingested by then, to replay exactly what CERVEAU knew).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

import pandas as pd

from core.finance.adjust import Adjustment, adjusted_closes
from core.finance.model import (
    CorporateAction,
    FxRate,
    Instrument,
    MarketRecord,
    PriceRow,
    RateObservation,
    from_utc_text,
    local_date,
    utc_text,
)
from core.finance.schema import (
    LATEST_VERSION,
    QUALITY_COLUMNS,
    SchemaError,
    migrate,
    schema_version,
)

MAX_SOURCE_ID_CHARS = 64


class FinanceStoreError(Exception):
    """A write is refused (unknown instrument, rewritten history) or the store is unusable."""


@dataclass(frozen=True)
class _Table:
    name: str
    keys: tuple[str, ...]  # one point of one series
    values: tuple[str, ...]  # a change of any of them is a new revision
    date_column: str


# Table and column names are constants: the f-string queries below never embed user input.
_TABLES: dict[type[MarketRecord], _Table] = {
    PriceRow: _Table(
        "prices", ("instrument_id", "session"), ("close", "volume", "currency"), "session"
    ),
    CorporateAction: _Table(
        "corporate_actions", ("instrument_id", "ex_date", "kind"), ("value", "currency"), "ex_date"
    ),
    FxRate: _Table("fx_rates", ("currency", "session"), ("rate",), "session"),
    RateObservation: _Table("rates", ("series_id", "session"), ("value_pct",), "session"),
}
_INSTRUMENT_COLUMNS = tuple(Instrument.model_fields)


@dataclass(frozen=True)
class Stored[R: MarketRecord]:
    """A record as stored: its revision and when CERVEAU ingested it (audit, strict mode)."""

    record: R
    revision: int
    ingested_at: datetime


@dataclass
class IngestReport:
    inserted: int = 0
    revised: int = 0
    unchanged: int = 0

    @property
    def total(self) -> int:
        return self.inserted + self.revised + self.unchanged


def default_store_path(project_root: Path) -> Path:
    return project_root / "var" / "finance" / "finance.db"


def _sql(value: Any) -> Any:
    if isinstance(value, datetime):
        return utc_text(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _connect(target: str, *, uri: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(target, uri=uri, autocommit=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


class FinanceStore:
    """``with FinanceStore.open(path, read_only=True) as store: store.closes(...)``."""

    def __init__(self, conn: sqlite3.Connection, *, read_only: bool) -> None:
        self._conn = conn
        self.read_only = read_only
        if read_only:
            conn.execute("PRAGMA query_only = ON")
            version = schema_version(conn)
            if version != LATEST_VERSION:
                raise SchemaError(
                    f"base au schéma {version}, attendu {LATEST_VERSION} : lancer "
                    "`cerveau finance sync` pour la mettre à jour"
                )
        else:
            migrate(conn)
        self._versions_cache: dict[str, list[tuple[Instrument, datetime]]] = {}

    @classmethod
    def open(cls, path: Path, *, read_only: bool = False) -> FinanceStore:
        if read_only:
            if not path.is_file():
                raise FinanceStoreError(
                    f"base finance absente ({path.name}) : lancer `cerveau finance sync`"
                )
            conn = _connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = _connect(str(path), uri=False)
        try:
            return cls(conn, read_only=read_only)
        except BaseException:
            conn.close()
            raise

    @classmethod
    def memory(cls) -> FinanceStore:
        return cls(_connect(":memory:", uri=False), read_only=False)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> FinanceStore:
        return self

    def __exit__(
        self, kind: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        return schema_version(self._conn)

    @contextmanager
    def _write(self) -> Iterator[None]:
        if self.read_only:
            raise FinanceStoreError("base ouverte en lecture seule : seule la CLI y écrit")
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            self._versions_cache.clear()
            raise
        self._conn.execute("COMMIT")

    # Reference ------------------------------------------------------------------------------

    def _versions(self, instrument_id: str) -> list[tuple[Instrument, datetime]]:
        if instrument_id not in self._versions_cache:
            rows = self._conn.execute(
                "SELECT * FROM instruments WHERE instrument_id = ? ORDER BY valid_from",
                (instrument_id,),
            ).fetchall()
            self._versions_cache[instrument_id] = [
                (
                    Instrument.model_validate(
                        {c: row[c] for c in _INSTRUMENT_COLUMNS}
                        | {"duration": _duration_from_sql(row["duration"])}
                    ),
                    from_utc_text(row["recorded_at"]),
                )
                for row in rows
            ]
        return self._versions_cache[instrument_id]

    def add_instrument(self, instrument: Instrument, *, recorded_at: datetime) -> bool:
        """Record a version; False when the same version is already there (idempotent).

        A version starts where the previous one ends: history is never rewritten, so a new
        version must start after the latest one.
        """
        return self.add_instruments([instrument], recorded_at=recorded_at) == 1

    def add_instruments(self, instruments: Iterable[Instrument], *, recorded_at: datetime) -> int:
        """Record versions in one transaction (a refusal cancels all); returns how many are new."""
        added = 0
        with self._write():
            for instrument in instruments:
                added += self._insert_instrument(instrument, recorded_at)
        return added

    def _insert_instrument(self, instrument: Instrument, recorded_at: datetime) -> bool:
        versions = [v for v, _ in self._versions(instrument.instrument_id)]
        if instrument in versions:
            return False
        if versions and instrument.valid_from <= versions[-1].valid_from:
            raise FinanceStoreError(
                f"{instrument.instrument_id} : une version doit commencer après le "
                f"{versions[-1].valid_from} (l'historique du référentiel ne se réécrit pas)"
            )
        values = instrument.model_dump()
        values["duration"] = _duration_to_sql(instrument.duration)
        columns = (*_INSTRUMENT_COLUMNS, "recorded_at")
        self._conn.execute(
            f"INSERT INTO instruments ({', '.join(columns)}) "  # noqa: S608 - constant names
            f"VALUES ({', '.join('?' * len(columns))})",
            [_sql(values[c]) for c in _INSTRUMENT_COLUMNS] + [utc_text(recorded_at)],
        )
        self._versions_cache.pop(instrument.instrument_id, None)
        return True

    def _version_on(
        self, instrument_id: str, day: date, *, recorded_by: datetime | None = None
    ) -> Instrument | None:
        versions = [
            v for v, at in self._versions(instrument_id) if recorded_by is None or at <= recorded_by
        ]
        for i, version in enumerate(versions):
            following = versions[i + 1].valid_from if i + 1 < len(versions) else None
            ends = [d for d in (version.valid_to, following) if d is not None]
            if version.valid_from <= day and (not ends or day < min(ends)):
                return version
        return None

    def instrument(
        self, instrument_id: str, *, as_of: datetime, strict: bool = False
    ) -> Instrument | None:
        """The version valid on the Paris date of ``as_of``; strict: also recorded by then."""
        return self._version_on(
            instrument_id, local_date(as_of), recorded_by=as_of if strict else None
        )

    def instruments(self, *, as_of: datetime, strict: bool = False) -> list[Instrument]:
        ids = [r[0] for r in self._conn.execute("SELECT DISTINCT instrument_id FROM instruments")]
        found = (self.instrument(i, as_of=as_of, strict=strict) for i in sorted(ids))
        return [i for i in found if i is not None]

    def map_source_id(
        self, source: str, source_id: str, instrument_id: str, *, recorded_at: datetime
    ) -> bool:
        """Link a source's identifier (ticker, ISIN, series key) to an instrument, once."""
        if not 0 < len(source_id) <= MAX_SOURCE_ID_CHARS or not source_id.isprintable():
            raise FinanceStoreError("identifiant de source vide, trop long ou non imprimable")
        with self._write():
            if not self._versions(instrument_id):
                raise FinanceStoreError(f"{instrument_id} : instrument absent du référentiel")
            known = self.resolve(source, source_id)
            if known == instrument_id:
                return False
            if known is not None:
                raise FinanceStoreError(f"{source}:{source_id} désigne déjà {known}")
            self._conn.execute(
                "INSERT INTO instrument_ids (source, source_id, instrument_id, recorded_at) "
                "VALUES (?, ?, ?, ?)",
                (source, source_id, instrument_id, utc_text(recorded_at)),
            )
        return True

    def resolve(self, source: str, source_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT instrument_id FROM instrument_ids WHERE source = ? AND source_id = ?",
            (source, source_id),
        ).fetchone()
        return None if row is None else str(row[0])

    # Market data: writes ---------------------------------------------------------------------

    def _check_reference(self, record: MarketRecord) -> None:
        if isinstance(record, PriceRow):
            instrument_id, day, currency = record.instrument_id, record.session, record.currency
        elif isinstance(record, CorporateAction):
            instrument_id, day, currency = record.instrument_id, record.ex_date, record.currency
        else:
            return
        version = self._version_on(instrument_id, day)
        if version is None:
            raise FinanceStoreError(f"{instrument_id} : aucune version du référentiel le {day}")
        if currency is not None and currency != version.currency:
            raise FinanceStoreError(
                f"{instrument_id} le {day} : devise {currency}, le référentiel dit "
                f"{version.currency}"
            )

    def ingest(self, records: Iterable[MarketRecord], *, ingested_at: datetime) -> IngestReport:
        """Store a batch in one transaction: any refused record cancels the whole batch."""
        stamp = utc_text(ingested_at)
        report = IngestReport()
        with self._write():
            for record in records:
                table = _TABLES[type(record)]
                self._check_reference(record)
                if record.published_at > ingested_at:
                    raise FinanceStoreError(
                        f"{table.name} : publication annoncée après l'ingestion ({record!r})"
                    )
                keys, values = _key_values(table, record)
                last = self._last_revision(table, keys)
                published = utc_text(record.published_at)
                if last is not None and [last[v] for v in table.values] == values:
                    report.unchanged += 1
                    continue
                if last is not None and published < last["published_at"]:
                    raise FinanceStoreError(
                        f"{table.name} {keys} : révision publiée avant la précédente "
                        f"({last['published_at']})"
                    )
                revision = 1 if last is None else last["revision"] + 1
                columns = (*table.keys, *table.values, "revision", "source", "published_at")
                self._conn.execute(
                    f"INSERT INTO {table.name} ({', '.join(columns)}, ingested_at) "  # noqa: S608
                    f"VALUES ({', '.join('?' * (len(columns) + 1))})",
                    [*keys, *values, revision, record.source, published, stamp],
                )
                if last is None:
                    report.inserted += 1
                else:
                    report.revised += 1
        return report

    def _last_revision(self, table: _Table, keys: list[Any]) -> sqlite3.Row | None:
        where = " AND ".join(f"{k} = ?" for k in table.keys)
        row: sqlite3.Row | None = self._conn.execute(
            f"SELECT revision, published_at, {', '.join(table.values)} "  # noqa: S608
            f"FROM {table.name} WHERE {where} ORDER BY revision DESC LIMIT 1",
            keys,
        ).fetchone()
        return row

    def revising(self, records: Sequence[MarketRecord]) -> set[int]:
        """Positions of the records whose key is stored with other values: they would revise it."""
        found: set[int] = set()
        for position, record in enumerate(records):
            table = _TABLES[type(record)]
            keys, values = _key_values(table, record)
            last = self._last_revision(table, keys)
            if last is not None and [last[v] for v in table.values] != values:
                found.add(position)
        return found

    # Market data: point-in-time reads --------------------------------------------------------

    def _visible[R: MarketRecord](
        self,
        record_type: type[R],
        where: dict[str, Any],
        *,
        as_of: datetime,
        strict: bool,
        start: date | None = None,
        end: date | None = None,
    ) -> list[sqlite3.Row]:
        table = _TABLES[record_type]
        stamp = utc_text(as_of)
        clauses = [*_key_clauses(table, where), "published_at <= ?"]
        params: list[Any] = [*map(_sql, where.values()), stamp]
        if strict:
            clauses.append("ingested_at <= ?")
            params.append(stamp)
        for bound, op in ((start, ">="), (end, "<=")):
            if bound is not None:
                clauses.append(f"{table.date_column} {op} ?")
                params.append(bound.isoformat())
        partition = ", ".join(table.keys)
        return self._conn.execute(
            f"SELECT * FROM (SELECT *, ROW_NUMBER() OVER "  # noqa: S608 - constant names
            f"(PARTITION BY {partition} ORDER BY revision DESC) AS rank_ "
            f"FROM {table.name} WHERE {' AND '.join(clauses)}) "
            f"WHERE rank_ = 1 ORDER BY {table.date_column}, {partition}",
            params,
        ).fetchall()

    @staticmethod
    def _stored[R: MarketRecord](record_type: type[R], row: sqlite3.Row) -> Stored[R]:
        table = _TABLES[record_type]
        fields = {c: row[c] for c in (*table.keys, *table.values, "source", "published_at")}
        record = record_type.model_validate(fields)
        return Stored(record, int(row["revision"]), from_utc_text(row["ingested_at"]))

    def price_bars(
        self,
        instrument_id: str,
        *,
        as_of: datetime,
        start: date | None = None,
        end: date | None = None,
        strict: bool = False,
    ) -> list[Stored[PriceRow]]:
        """Raw closes as known at ``as_of``, with their source, publication and revision."""
        rows = self._visible(
            PriceRow,
            {"instrument_id": instrument_id},
            as_of=as_of,
            strict=strict,
            start=start,
            end=end,
        )
        return [self._stored(PriceRow, row) for row in rows]

    def corporate_actions(
        self, instrument_id: str, *, as_of: datetime, strict: bool = False
    ) -> list[CorporateAction]:
        rows = self._visible(
            CorporateAction, {"instrument_id": instrument_id}, as_of=as_of, strict=strict
        )
        return [self._stored(CorporateAction, row).record for row in rows]

    def closes(
        self,
        instrument_id: str,
        *,
        as_of: datetime,
        start: date | None = None,
        end: date | None = None,
        adjust: Adjustment = "none",
        strict: bool = False,
    ) -> pd.Series:
        """Closes indexed by session, adjusted with the actions known at ``as_of`` only."""
        rows = self._visible(PriceRow, {"instrument_id": instrument_id}, as_of=as_of, strict=strict)
        sessions = [date.fromisoformat(r["session"]) for r in rows]
        values = [float(r["close"]) for r in rows]
        if adjust != "none":
            actions = self.corporate_actions(instrument_id, as_of=as_of, strict=strict)
            values = adjusted_closes(sessions, values, actions, adjust)
        # The whole known series is adjusted first: an action before ``start`` still counts.
        kept = [
            (s, v)
            for s, v in zip(sessions, values, strict=True)
            if (start is None or s >= start) and (end is None or s <= end)
        ]
        index = pd.DatetimeIndex([s for s, _ in kept])
        return pd.Series([v for _, v in kept], index=index, name=instrument_id, dtype=float)

    def _value_series[R: MarketRecord](
        self,
        record_type: type[R],
        where: dict[str, Any],
        column: str,
        *,
        as_of: datetime,
        start: date | None,
        end: date | None,
        strict: bool,
        name: str,
    ) -> pd.Series:
        rows = self._visible(record_type, where, as_of=as_of, strict=strict, start=start, end=end)
        index = pd.DatetimeIndex([date.fromisoformat(r["session"]) for r in rows])
        return pd.Series([float(r[column]) for r in rows], index=index, name=name, dtype=float)

    def fx_rates(
        self,
        currency: str,
        *,
        as_of: datetime,
        start: date | None = None,
        end: date | None = None,
        strict: bool = False,
    ) -> pd.Series:
        """Units of ``currency`` for one euro, by session (ECB reference rates)."""
        return self._value_series(
            FxRate,
            {"currency": currency},
            "rate",
            as_of=as_of,
            start=start,
            end=end,
            strict=strict,
            name=f"EUR{currency}",
        )

    def rates(
        self,
        series_id: str,
        *,
        as_of: datetime,
        start: date | None = None,
        end: date | None = None,
        strict: bool = False,
    ) -> pd.Series:
        """A rate in percent per year, by session, as published."""
        return self._value_series(
            RateObservation,
            {"series_id": series_id},
            "value_pct",
            as_of=as_of,
            start=start,
            end=end,
            strict=strict,
            name=series_id,
        )

    def revisions[R: MarketRecord](
        self, record_type: type[R], where: dict[str, Any]
    ) -> Sequence[Stored[R]]:
        """Every revision of the matching keys, oldest first (audit, quality checks)."""
        table = _TABLES[record_type]
        clauses = " AND ".join(_key_clauses(table, where)) or "1 = 1"
        rows = self._conn.execute(
            f"SELECT * FROM {table.name} WHERE {clauses} "  # noqa: S608 - constant names
            f"ORDER BY {table.date_column}, revision",
            [*map(_sql, where.values())],
        ).fetchall()
        return [self._stored(record_type, row) for row in rows]

    # Quality scores ---------------------------------------------------------------------------

    def record_quality(
        self,
        series_id: str,
        *,
        as_of: datetime,
        sub_scores: dict[str, float | None],
        score: float | None,
        details: str,
        computed_at: datetime,
    ) -> bool:
        """One score per series and date: the same one again is a no-op, another one is refused."""
        if set(sub_scores) != set(QUALITY_COLUMNS):
            raise FinanceStoreError(f"sous-scores attendus : {', '.join(QUALITY_COLUMNS)}")
        values = (*(sub_scores[c] for c in QUALITY_COLUMNS), score, details)
        stamp = utc_text(as_of)
        with self._write():
            row = self._conn.execute(
                f"SELECT {', '.join(QUALITY_COLUMNS)}, score, details "  # noqa: S608 - constants
                "FROM quality_scores WHERE series_id = ? AND as_of = ?",
                (series_id, stamp),
            ).fetchone()
            if row is not None:
                if tuple(row) == values:
                    return False
                raise FinanceStoreError(
                    f"{series_id} : un autre score est déjà enregistré à {stamp}"
                )
            columns = ", ".join(("series_id", "as_of", *QUALITY_COLUMNS, "score", "details"))
            self._conn.execute(
                f"INSERT INTO quality_scores ({columns}, computed_at) "  # noqa: S608 - constants
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (series_id, stamp, *values, utc_text(computed_at)),
            )
        return True

    def quality_history(self, series_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM quality_scores WHERE series_id = ? ORDER BY as_of", (series_id,)
        ).fetchall()
        return [dict(row) for row in rows]


def _key_values(table: _Table, record: MarketRecord) -> tuple[list[Any], list[Any]]:
    return (
        [_sql(getattr(record, k)) for k in table.keys],
        [_sql(getattr(record, v)) for v in table.values],
    )


def _key_clauses(table: _Table, where: dict[str, Any]) -> list[str]:
    """Filters on key columns only: their names are the only text interpolated into SQL."""
    unknown = set(where) - set(table.keys)
    if unknown:
        raise FinanceStoreError(f"filtre hors des clés de {table.name} : {sorted(unknown)}")
    return [f"{k} = ?" for k in where]


def _duration_to_sql(value: float | str | None) -> str | None:
    return None if value is None else str(value)


def _duration_from_sql(value: str | None) -> float | str | None:
    if value is None or value in ("A_DEFINIR", "A_VERIFIER"):
        return value
    return float(value)
