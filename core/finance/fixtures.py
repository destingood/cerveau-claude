"""The fictitious reference portfolio of tests and evals, loaded the way Lucas's data is.

``tests/fixtures/finance/reference/`` holds invented instruments and synthetic market data
(phase 2 plan, §4; its README lists the anomalies placed in them). They go through the real
providers, so they are dated and checked as a CSV export or an ECB response would be (ADR-017),
then scored like any sync. Every record is stamped ``fixtures``: a synthetic value never passes
for one from a real source (R12). Nothing here reaches the network; the ECB files are served
by an in-memory transport behind a host that cannot resolve.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import Any

import httpx

from core.config.loader import DataQuality
from core.finance.model import MarketRecord, local_date
from core.finance.providers import (
    CsvCloses,
    CsvCorporateActions,
    EcbProvider,
    MarketDataProvider,
)
from core.finance.providers.ecb import CATEGORIES
from core.finance.store import FinanceStore
from core.finance.sync import SyncResult, import_instruments, reference, reference_currencies, sync

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "finance" / "reference"
# The Sunday after the last session: the generator leaves out what was published later.
REFERENCE_FETCHED_AT = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
REFERENCE_FIRST_DAY = date(2023, 10, 16)
FIXTURES_SOURCE = "fixtures"
FIXTURE_ECB_URL = "https://ecb.fixtures.invalid/service/"  # .invalid never resolves (RFC 6761)
ECB_FILES = {"EXR": "bce_change.csv", "EST": "bce_estr.csv"}


@dataclass(frozen=True)
class AsFixtures:
    """A provider whose records are restamped ``fixtures``, whatever source it stands for."""

    provider: MarketDataProvider
    source: str = FIXTURES_SOURCE

    def describe(self) -> dict[str, Any]:
        return {"stands_for": self.provider.source, **self.provider.describe()}

    def fetch(self, *, fetched_at: datetime) -> Sequence[MarketRecord]:
        return [
            type(r).model_validate({**r.model_dump(), "source": self.source})
            for r in self.provider.fetch(fetched_at=fetched_at)
        ]


def ecb_files(directory: Path) -> httpx.MockTransport:
    """Answer ``/data/<flow>/…`` from the ECB files of ``directory``; anything else is a 404."""

    def handle(request: httpx.Request) -> httpx.Response:
        parts = request.url.path.split("/")
        flow = parts[parts.index("data") + 1] if "data" in parts[:-1] else ""
        if flow not in ECB_FILES:
            return httpx.Response(404)
        return httpx.Response(200, content=(directory / ECB_FILES[flow]).read_bytes())

    return httpx.MockTransport(handle)


def ticking(start: datetime, step: timedelta = timedelta(seconds=1)) -> Callable[[], datetime]:
    """A clock that moves ``step`` forward at each call: every load gives the same timestamps."""
    moments = count()
    return lambda: start + step * next(moments)


def load_reference(
    store: FinanceStore,
    *,
    quality: DataQuality,
    window_sessions: int,
    directory: Path = REFERENCE_DIR,
    fetched_at: datetime = REFERENCE_FETCHED_AT,
) -> list[SyncResult]:
    """Instruments, corporate actions, closes, then the ECB rates: four syncs, in that order.

    The corporate actions come before the closes, so that the quality score of each series is
    computed once its splits are known.
    """
    clock = ticking(fetched_at)
    results = [import_instruments(store, directory / "instruments.csv", recorded_at=clock())]
    known = reference(store)
    ecb = EcbProvider(
        base_url=FIXTURE_ECB_URL,
        categories=list(CATEGORIES),
        currencies=reference_currencies(store.instruments(as_of=fetched_at)),
        start=REFERENCE_FIRST_DAY,
        end=local_date(fetched_at),
        transport=ecb_files(directory),
    )
    providers: list[MarketDataProvider] = [
        CsvCorporateActions(directory / "operations.csv", known, source=FIXTURES_SOURCE),
        CsvCloses(directory / "cours.csv", known, source=FIXTURES_SOURCE),
        AsFixtures(ecb),
    ]
    for provider in providers:
        results.append(
            sync(store, provider, clock=clock, quality=quality, window_sessions=window_sessions)
        )
    return results
