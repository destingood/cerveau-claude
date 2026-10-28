"""What every market data provider promises, and how it dates what it delivers (ADR-017, R10).

A provider fetches records and gives each one the time it became public, ``published_at``:
the documented publication time plus a margin, never later than the fetch that saw it. A value
that differs from the stored one is a revision; ``core.finance.sync`` dates it at the fetch,
since nothing says when the provider corrected it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from pydantic import ValidationError

from core.finance.model import Instrument, MarketRecord

# Margin added to a documented publication time: « around 16:00 » may mean 16:05.
PUBLICATION_MARGIN = timedelta(hours=1)

# The reference version of an instrument on a date, or None (``store.instrument``).
Reference = Callable[[str, date], Instrument | None]


class ProviderError(Exception):
    """A provider cannot deliver: network failure, unexpected format or refused row."""


class MarketDataProvider(Protocol):
    @property
    def source(self) -> str:
        """The source stamped on every record (``SourceId``)."""
        ...

    def describe(self) -> dict[str, Any]:
        """The parameters of the fetch, for the audit journal (R11); never a secret (R6)."""
        ...

    def fetch(self, *, fetched_at: datetime) -> Sequence[MarketRecord]: ...


@dataclass(frozen=True)
class StaticProvider:
    """Records given in advance: the offline ``fixtures`` provider of tests and evals."""

    records: Sequence[MarketRecord]
    source: str = "fixtures"
    parameters: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        return {**self.parameters, "records": len(self.records)}

    def fetch(self, *, fetched_at: datetime) -> Sequence[MarketRecord]:
        return list(self.records)


def published(documented: datetime, fetched_at: datetime) -> datetime:
    """The documented publication time plus the margin, capped at the fetch that saw the value."""
    return min(documented + PUBLICATION_MARGIN, fetched_at)


def validation_message(error: ValidationError) -> str:
    """The first problem, without the refused value: it is external content (R5)."""
    first = error.errors(include_url=False, include_input=False)[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"{where} : {first['msg']}" if where else str(first["msg"])
