"""The fictitious datasets of tests and evals, loaded the way the user's data is.

``tests/fixtures/finance/reference/`` holds invented instruments and synthetic market data
(phase 2 plan, §4; its README lists the anomalies placed in them). They go through the real
providers, so they are dated and checked as a CSV export or an ECB response would be (ADR-017),
then scored like any sync. Every record is stamped ``fixtures``: a synthetic value never passes
for one from a real source (R12). Nothing here reaches the network; the ECB files are served
by an in-memory transport behind a host that cannot resolve.

``tests/fixtures/finance/research/`` is the ten-year synthetic dataset of the backtest protocol
(phase 3 plan, §7): one planted trend, three random walks, fictitious crises and costs, and
closes that say when they were published.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import Any

import httpx
import yaml
from pydantic import ValidationError

from core.config.loader import CrisisWindow, DataQuality, TradingCosts
from core.finance.model import MarketRecord, PriceRow, local_date
from core.finance.portfolio import ImportResult, ReconcileResult, import_transactions, reconcile
from core.finance.providers import (
    CsvCloses,
    CsvCorporateActions,
    EcbProvider,
    MarketDataProvider,
    ProviderError,
    validation_message,
)
from core.finance.providers.csv_files import CsvLayout, read_table
from core.finance.providers.ecb import CATEGORIES
from core.finance.store import FinanceStore, IngestReport
from core.finance.sync import SyncResult, import_instruments, reference, reference_currencies, sync

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "finance" / "reference"
# The Sunday after the last session: the generator leaves out what was published later.
REFERENCE_FETCHED_AT = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
# A moment after every reference record, the quality scores included: what the tools read at.
REFERENCE_READ_AT = REFERENCE_FETCHED_AT + timedelta(hours=1)
REFERENCE_FIRST_DAY = date(2023, 10, 16)
FIXTURES_SOURCE = "fixtures"
FIXTURE_ECB_URL = "https://ecb.fixtures.invalid/service/"  # .invalid never resolves (RFC 6761)
ECB_FILES = {"EXR": "bce_change.csv", "EST": "bce_estr.csv"}
# The settings the anomalies of the reference are tested with. They are test values, not the
# cut-offs of config/data_sources.yaml, which stay A_DEFINIR until the user sets them (ADR-016).
REFERENCE_QUALITY = DataQuality(
    max_staleness_sessions=1,
    min_quality_score_above_N1=0.9,
    outlier_robust_z=3.5,
    max_unexplained_move=0.3,
)
REFERENCE_WINDOW = 500

RESEARCH_DIR = REFERENCE_DIR.parent / "research"
# The Sunday after the last session: every close, late or corrected, is published by then.
RESEARCH_FETCHED_AT = datetime(2026, 1, 4, 12, 0, tzinfo=UTC)
PUBLISHED_CLOSES = CsvLayout(("date", "identifiant", "cloture", "devise", "publie_le"))


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


@dataclass(frozen=True)
class PublishedCloses:
    """Closes that say when each one reached the feed: the research dataset's ``cours.csv``.

    A CSV export gives only the session, so CsvCloses dates a close at the session's close. The
    research dataset also has closes published the next morning and prints corrected the next
    day: each row keeps its own date (``publie_le``), and the rows come in publication order, so
    that a correction is stored as a revision of the print before it.
    """

    path: Path
    source: str = FIXTURES_SOURCE

    def describe(self) -> dict[str, Any]:
        return {"kind": "cours publies", "file": self.path.name}

    def fetch(self, *, fetched_at: datetime) -> Sequence[MarketRecord]:
        table = read_table(self.path, PUBLISHED_CLOSES)
        rows: list[PriceRow] = []
        for line, fields in table.rows:
            try:
                row = PriceRow.model_validate(
                    {
                        "instrument_id": fields["identifiant"],
                        "session": date.fromisoformat(fields["date"]),
                        "close": float(fields["cloture"]),
                        "currency": fields["devise"],
                        "source": self.source,
                        "published_at": fields["publie_le"],
                    }
                )
            except ValidationError as exc:
                raise ProviderError(
                    f"{table.name}, ligne {line} : {validation_message(exc)}"
                ) from None
            except (ValueError, KeyError):
                raise ProviderError(f"{table.name}, ligne {line} : valeur invalide") from None
            if row.published_at > fetched_at:
                raise ProviderError(f"{table.name}, ligne {line} : publié après la récupération")
            rows.append(row)
        return sorted(rows, key=lambda r: r.published_at)


def load_research(
    store: FinanceStore,
    *,
    directory: Path = RESEARCH_DIR,
    fetched_at: datetime = RESEARCH_FETCHED_AT,
) -> list[IngestReport]:
    """Instruments, corporate actions, then closes, all ingested at ``fetched_at``.

    No quality score: a backtest reads each series as it was published (PointInTimeView), not
    through the scores of a sync. Load a dataset once into a fresh store: reading the same
    file again would store each corrected print as a new revision.
    """
    instruments = import_instruments(store, directory / "instruments.csv", recorded_at=fetched_at)
    actions = CsvCorporateActions(directory / "operations.csv", reference(store), FIXTURES_SOURCE)
    reports = [instruments.report]
    for provider in (actions, PublishedCloses(directory / "cours.csv")):
        reports.append(store.ingest(provider.fetch(fetched_at=fetched_at), ingested_at=fetched_at))
    return reports


def research_crises(directory: Path = RESEARCH_DIR) -> dict[str, CrisisWindow]:
    """The fictitious crisis windows, in the form of risk.yaml › historical_stress."""
    raw = yaml.safe_load((directory / "crises_fictives.yaml").read_text(encoding="utf-8"))
    return {name: CrisisWindow.model_validate(window) for name, window in raw.items()}


@dataclass(frozen=True)
class NamedCosts:
    """Trading costs and the name every output that uses them must show."""

    name: str
    costs: TradingCosts


def research_costs(directory: Path = RESEARCH_DIR) -> NamedCosts:
    """The fictitious trading costs of the demonstration (D13 of phase 2 stays A_DEFINIR)."""
    raw = yaml.safe_load((directory / "frais_fictifs.yaml").read_text(encoding="utf-8"))
    return NamedCosts(raw["nom"], TradingCosts.model_validate(raw["trading_costs"]))


def load_reference_portfolio(
    store: FinanceStore, *, at: datetime = REFERENCE_FETCHED_AT, directory: Path = REFERENCE_DIR
) -> tuple[ImportResult, ReconcileResult]:
    """The two fictitious accounts on top of the market data: transactions, then the statement."""
    imported = import_transactions(store, directory / "transactions.csv", "cerveau", imported_at=at)
    return imported, reconcile(store, directory / "releve.csv", at=at)


def reference_store(path: Path) -> Path:
    """A store file with the reference market data and the two fictitious accounts."""
    with FinanceStore.open(path) as store:
        load_reference(store, quality=REFERENCE_QUALITY, window_sessions=REFERENCE_WINDOW)
        load_reference_portfolio(store)
    return path
