"""Fetch a provider, date its revisions at the fetch, store the batch and check its quality.

Only ``cerveau finance sync`` calls this, on the user's command: it is the one writer of the store
(ADR-012). A value that differs from the stored one is a revision; nothing says when the
provider corrected it, so it counts as published at the fetch that saw it (ADR-017, R10).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from core.config.loader import DataQuality
from core.finance.model import (
    CorporateAction,
    Instrument,
    MarketRecord,
    PriceRow,
    end_of_day,
    utc_text,
)
from core.finance.providers import MarketDataProvider, Reference, read_instruments
from core.finance.quality import QualityError, QualityReport, assess, record
from core.finance.store import FinanceStore, IngestReport

Clock = Callable[[], datetime]

# How far back a sync starts before the last stored session: catches late revisions.
DEFAULT_LOOKBACK = timedelta(days=14)


@dataclass(frozen=True)
class SyncResult:
    source: str
    parameters: dict[str, Any]
    fetched_at: datetime
    ingested_at: datetime
    received: int
    redated: int  # revisions dated at the fetch
    report: IngestReport
    quality: list[QualityReport] = field(default_factory=list)
    not_assessed: dict[str, str] = field(default_factory=dict)  # instrument → reason

    def journal_payload(self) -> dict[str, Any]:
        """What the audit journal keeps of a sync (R11): counts and scores, never the values."""
        return {
            "source": self.source,
            "parameters": self.parameters,
            "fetched_at": utc_text(self.fetched_at),
            "ingested_at": utc_text(self.ingested_at),
            "received": self.received,
            "inserted": self.report.inserted,
            "revised": self.report.revised,
            "unchanged": self.report.unchanged,
            "redated": self.redated,
            "quality": {q.instrument_id: {"score": q.score, **q.sub_scores} for q in self.quality},
            "not_assessed": self.not_assessed,
        }


def reference(store: FinanceStore) -> Reference:
    """The version of an instrument valid on a session, as the store knows it now."""
    return lambda instrument_id, day: store.instrument(instrument_id, as_of=end_of_day(day))


def redated(record: MarketRecord, fetched_at: datetime) -> MarketRecord:
    return type(record).model_validate({**record.model_dump(), "published_at": fetched_at})


def sync(
    store: FinanceStore,
    provider: MarketDataProvider,
    *,
    clock: Clock,
    quality: DataQuality,
    window_sessions: int,
) -> SyncResult:
    """One fetch, one transaction; then the strict quality score of each instrument touched."""
    fetched_at = clock()
    records = list(provider.fetch(fetched_at=fetched_at))
    revising = store.revising(records)
    records = [
        redated(r, fetched_at) if position in revising else r for position, r in enumerate(records)
    ]
    ingested_at = clock()
    report = store.ingest(records, ingested_at=ingested_at)
    touched = sorted(
        {r.instrument_id for r in records if isinstance(r, PriceRow | CorporateAction)}
    )
    reports, not_assessed = [], {}
    for instrument_id in touched:
        try:
            assessed = assess(
                store,
                instrument_id,
                as_of=ingested_at,
                settings=quality,
                window_sessions=window_sessions,
                strict=True,
            )
        except QualityError as exc:  # e.g. an instrument delisted before today
            not_assessed[instrument_id] = str(exc)
            continue
        record(store, assessed, computed_at=clock())
        reports.append(assessed)
    return SyncResult(
        source=provider.source,
        parameters=provider.describe(),
        fetched_at=fetched_at,
        ingested_at=ingested_at,
        received=len(records),
        redated=len(revising),
        report=report,
        quality=reports,
        not_assessed=not_assessed,
    )


def import_instruments(store: FinanceStore, path: Path, *, recorded_at: datetime) -> SyncResult:
    """Record the reference of ``path`` in one transaction: a refused version cancels all."""
    table, instruments = read_instruments(path)
    added = store.add_instruments(instruments, recorded_at=recorded_at)
    return SyncResult(
        source="csv",
        parameters={"kind": "referentiel", **table.describe()},
        fetched_at=recorded_at,
        ingested_at=recorded_at,
        received=len(instruments),
        redated=0,
        report=IngestReport(inserted=added, unchanged=len(instruments) - added),
    )


def default_start(series: dict[str, Callable[..., Any]], now: datetime) -> date:
    """``DEFAULT_LOOKBACK`` before the oldest of the last stored sessions of ``series``.

    ``series`` maps a name to a store reader (``store.fx_rates`` bound to a currency, for
    instance); an empty series has no default, since how far back to start is the user's choice.
    """
    lasts: list[date] = []
    for name, read in series.items():
        stored = read(as_of=now)
        if stored.empty:
            raise ValueError(f"{name} : rien en base, préciser --start")
        lasts.append(stored.index.max().date())
    return min(lasts) - DEFAULT_LOOKBACK


def reference_currencies(instruments: list[Instrument]) -> list[str]:
    """The currencies other than the euro of the reference instruments, for the ECB rates."""
    return sorted({i.currency for i in instruments} - {"EUR"})
