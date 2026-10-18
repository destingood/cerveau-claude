"""CSV files written or exported by Lucas: reference, closes, corporate actions (ADR-017).

A file is external content (R5): its size is bounded, every column must be known, every field
goes through the record's validation, and an error names the line without echoing the value.
A file is read whole or refused whole. Columns are in French, separated by ``;`` (Excel in
French, decimal comma accepted) or ``,`` (decimal point only); dates are ``AAAA-MM-JJ`` or
``JJ/MM/AAAA``.

- reference (``instruments``): ``identifiant, nom, classe, devise, place, secteur, pays,
  debut`` and optionally ``isin, duration, fin``;
- closes (``cours``): ``date, identifiant, cloture, devise`` and optionally ``volume``; raw
  closes, never adjusted ones;
- corporate actions (``operations``): ``date_ex, identifiant, type, valeur`` and optionally
  ``devise`` (dividends) and ``date_annonce``.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import ValidationError

from core.finance.calendars import exchange_calendar
from core.finance.model import (
    PARIS,
    CorporateAction,
    Instrument,
    MarketRecord,
    PriceRow,
    end_of_day,
    local_date,
)
from core.finance.providers.base import (
    ProviderError,
    Reference,
    published,
    validation_message,
)

CSV_SOURCE = "csv"
MAX_FILE_BYTES = 64_000_000
MAX_ROWS = 1_000_000
MAX_FIELD_CHARS = 200

ASSET_CLASSES = {
    "action": "equity",
    "etf": "etf",
    "obligation": "bond",
    "or": "gold",
    "fonds": "fund",
}
ACTION_KINDS = {"split": "split", "dividende": "dividend"}


@dataclass(frozen=True)
class CsvLayout:
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()


INSTRUMENTS = CsvLayout(
    ("identifiant", "nom", "classe", "devise", "place", "secteur", "pays", "debut"),
    ("isin", "duration", "fin"),
)
CLOSES = CsvLayout(("date", "identifiant", "cloture", "devise"), ("volume",))
ACTIONS = CsvLayout(("date_ex", "identifiant", "type", "valeur"), ("devise", "date_annonce"))


@dataclass(frozen=True)
class CsvTable:
    name: str
    sha256: str
    decimal_comma: bool
    rows: list[tuple[int, dict[str, str]]]  # (line number, non-empty fields)

    def describe(self) -> dict[str, Any]:
        return {"file": self.name, "sha256": self.sha256, "rows": len(self.rows)}


def read_table(path: Path, layout: CsvLayout) -> CsvTable:
    """Read ``path`` against ``layout``: unknown or missing columns refuse the file."""
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ProviderError(f"{path.name} : fichier de plus de {MAX_FILE_BYTES} octets")
        raw = path.read_bytes()
    except OSError as exc:
        raise ProviderError(f"{path.name} : lecture impossible ({type(exc).__name__})") from None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ProviderError(f"{path.name} : le fichier doit être encodé en UTF-8") from None
    header = text.split("\n", 1)[0]
    delimiter = ";" if ";" in header else ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        columns = [c.strip().lower() for c in next(reader)]
    except (StopIteration, csv.Error):
        raise ProviderError(f"{path.name} : en-tête absent ou illisible") from None
    unknown = sorted(set(columns) - {*layout.required, *layout.optional})
    missing = [c for c in layout.required if c not in columns]
    if unknown or missing or len(set(columns)) != len(columns):
        raise ProviderError(
            f"{path.name} : colonnes attendues {', '.join(layout.required)} "
            f"(facultatives : {', '.join(layout.optional) or 'aucune'}) ; "
            f"inconnues : {', '.join(unknown) or 'aucune'}, manquantes : "
            f"{', '.join(missing) or 'aucune'}"
        )
    rows: list[tuple[int, dict[str, str]]] = []
    try:
        for fields in reader:
            line = reader.line_num
            if not any(f.strip() for f in fields):
                continue
            if len(fields) != len(columns):
                raise ProviderError(
                    f"{path.name}, ligne {line} : {len(fields)} champs au lieu de {len(columns)}"
                )
            if any(len(f) > MAX_FIELD_CHARS for f in fields):
                raise ProviderError(
                    f"{path.name}, ligne {line} : champ de plus de {MAX_FIELD_CHARS} caractères"
                )
            values = {c: f.strip() for c, f in zip(columns, fields, strict=True) if f.strip()}
            rows.append((line, values))
            if len(rows) > MAX_ROWS:
                raise ProviderError(f"{path.name} : plus de {MAX_ROWS} lignes")
    except csv.Error:
        raise ProviderError(f"{path.name}, ligne {reader.line_num} : CSV mal formé") from None
    return CsvTable(
        name=path.name,
        sha256=hashlib.sha256(raw).hexdigest(),
        decimal_comma=delimiter == ";",
        rows=rows,
    )


def parse_date(text: str) -> date:
    """``AAAA-MM-JJ`` or ``JJ/MM/AAAA`` (a French date: the day comes first)."""
    if "/" in text:
        day, month, year = text.split("/")
        if len(year) != 4:
            raise ValueError("date JJ/MM/AAAA attendue")
        return date(int(year), int(month), int(day))
    return date.fromisoformat(text)


def _number(text: str, decimal_comma: bool) -> float:
    if decimal_comma:
        text = text.replace(",", ".")
    elif "," in text:
        raise ValueError("virgule décimale : séparer les colonnes par « ; »")
    return float(text)


class _Rows:
    """Turns each row into a record; the first error refuses the file."""

    def __init__(self, table: CsvTable) -> None:
        self.table = table

    def build[T](self, convert: Callable[[dict[str, str]], T]) -> Iterator[tuple[int, T]]:
        for line, fields in self.table.rows:
            try:
                yield line, convert(fields)
            except ValidationError as exc:
                raise self.error(line, validation_message(exc)) from None
            except (ValueError, KeyError) as exc:
                raise self.error(line, _plain(exc)) from None

    def error(self, line: int, message: str) -> ProviderError:
        return ProviderError(f"{self.table.name}, ligne {line} : {message}")

    def number(self, text: str) -> float:
        return _number(text, self.table.decimal_comma)


def _plain(exc: Exception) -> str:
    if isinstance(exc, KeyError):
        return f"champ {exc.args[0]} vide"
    message = str(exc)
    # Python's own messages may quote the refused text: keep only ours (R5).
    return message if "'" not in message and '"' not in message else "valeur invalide"


def _unique[T](rows: _Rows, built: Iterator[tuple[int, T]], key: Callable[[T], object]) -> list[T]:
    """Drop exact duplicates; two different rows for one key refuse the file."""
    seen: dict[object, T] = {}
    for line, item in built:
        known = seen.get(key(item))
        if known is not None and known != item:
            raise rows.error(line, "deux lignes différentes pour la même clé")
        seen[key(item)] = item
    return list(seen.values())


def read_instruments(path: Path) -> tuple[CsvTable, list[Instrument]]:
    """The reference file, sorted by instrument then start date (versions in order)."""
    table = read_table(path, INSTRUMENTS)
    rows = _Rows(table)

    def convert(fields: dict[str, str]) -> Instrument:
        kind = fields["classe"].lower()
        if kind not in ASSET_CLASSES:
            raise ValueError(f"classe attendue : {', '.join(ASSET_CLASSES)}")
        duration: float | str | None = fields.get("duration")
        if duration is not None and duration != "A_DEFINIR":
            duration = rows.number(duration)
        return Instrument.model_validate(
            {
                "instrument_id": fields["identifiant"],
                "isin": fields.get("isin"),
                "name": fields["nom"],
                "asset_class": ASSET_CLASSES[kind],
                "currency": fields["devise"],
                "mic": fields["place"],
                "sector": fields["secteur"],
                "country": fields["pays"],
                "duration": duration,
                "valid_from": parse_date(fields["debut"]),
                "valid_to": parse_date(fields["fin"]) if "fin" in fields else None,
            }
        )

    versions = _unique(rows, rows.build(convert), lambda i: (i.instrument_id, i.valid_from))
    return table, sorted(versions, key=lambda i: (i.instrument_id, i.valid_from))


@dataclass
class CsvCloses:
    """Raw closes: known at the session's close plus the margin (exchange-calendars)."""

    path: Path
    reference: Reference
    source: str = CSV_SOURCE

    def __post_init__(self) -> None:
        self._table: CsvTable | None = None

    def describe(self) -> dict[str, Any]:
        described = {"kind": "cours", "file": self.path.name}
        return described | (self._table.describe() if self._table else {})

    def fetch(self, *, fetched_at: datetime) -> Sequence[MarketRecord]:
        self._table = table = read_table(self.path, CLOSES)
        rows = _Rows(table)
        days = [day for _, day in rows.build(lambda f: parse_date(f["date"]))]
        if not days:
            return []
        closes = _CloseTimes(min(days).year, max(days).year)

        def convert(fields: dict[str, str]) -> PriceRow:
            session = parse_date(fields["date"])
            version = self.reference(fields["identifiant"], session)
            if version is None:
                raise ValueError("instrument absent du référentiel à cette date")
            close_at = closes.close(version.mic, session)
            if fetched_at < close_at:
                raise ValueError("séance pas encore close : pas de cours de clôture")
            return PriceRow.model_validate(
                {
                    "instrument_id": fields["identifiant"],
                    "session": session,
                    "close": rows.number(fields["cloture"]),
                    "volume": int(fields["volume"]) if "volume" in fields else None,
                    "currency": fields["devise"],
                    "source": self.source,
                    "published_at": published(close_at, fetched_at),
                }
            )

        return _unique(rows, rows.build(convert), lambda p: (p.instrument_id, p.session))


class _CloseTimes:
    """When a session's close is known: its close time, or the end of the day in Paris."""

    def __init__(self, first_year: int, last_year: int) -> None:
        self.first_year, self.last_year = first_year, last_year

    def close(self, mic: str, session: date) -> datetime:
        calendar = exchange_calendar(mic, self.first_year, self.last_year)
        day = pd.Timestamp(session)
        if calendar is None or not calendar.is_session(day):
            # No known close time: the end of the day is later than any European or US close.
            return end_of_day(session, PARIS)
        moment: datetime = calendar.session_close(day).to_pydatetime()
        return moment


@dataclass
class CsvCorporateActions:
    """Splits and dividends: known at the end of the announcement day, or by the ex-date."""

    path: Path
    reference: Reference
    source: str = CSV_SOURCE

    def __post_init__(self) -> None:
        self._table: CsvTable | None = None

    def describe(self) -> dict[str, Any]:
        described = {"kind": "operations", "file": self.path.name}
        return described | (self._table.describe() if self._table else {})

    def fetch(self, *, fetched_at: datetime) -> Sequence[MarketRecord]:
        self._table = table = read_table(self.path, ACTIONS)
        rows = _Rows(table)

        def convert(fields: dict[str, str]) -> CorporateAction:
            ex_date = parse_date(fields["date_ex"])
            kind = fields["type"].lower()
            if kind not in ACTION_KINDS:
                raise ValueError(f"type attendu : {', '.join(ACTION_KINDS)}")
            if self.reference(fields["identifiant"], ex_date) is None:
                raise ValueError("instrument absent du référentiel à la date ex")
            if "date_annonce" in fields:
                announced = parse_date(fields["date_annonce"])
                if announced > ex_date:
                    raise ValueError("annonce postérieure à la date ex")
                if announced > local_date(fetched_at):
                    raise ValueError("annonce datée dans le futur")
                documented = end_of_day(announced, PARIS)
            else:
                # Always announced before its ex-date: known at the start of it at the latest.
                documented = datetime.combine(ex_date, time(), tzinfo=PARIS)
            return CorporateAction.model_validate(
                {
                    "instrument_id": fields["identifiant"],
                    "ex_date": ex_date,
                    "kind": ACTION_KINDS[kind],
                    "value": rows.number(fields["valeur"]),
                    "currency": fields.get("devise"),
                    "source": self.source,
                    "published_at": published(documented, fetched_at),
                }
            )

        return _unique(rows, rows.build(convert), lambda a: (a.instrument_id, a.ex_date, a.kind))
