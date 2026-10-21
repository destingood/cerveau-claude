"""The one interface between CERVEAU and a broker, paper or real (ADR-033).

The rest of the code knows only :class:`BrokerAdapter`. The broker keeps its own accounting:
what it reports (acknowledgements, fills, open orders, the account) is what the order book and
the reconciliation compare with CERVEAU's own records, never something they take on trust.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from core.execution.book import Fill
from core.execution.intent import OrderIntent


@dataclass(frozen=True)
class BrokerAck:
    """The broker's answer to a submission: accepted, or rejected with its reason.

    ``duplicate`` marks an ``intent_id`` the broker had already received: nothing new was sent,
    and the answer is the one of the first submission, or a rejection if the content differs.
    """

    intent_id: UUID
    accepted: bool
    reason: str
    duplicate: bool = False


@dataclass(frozen=True)
class BrokerOrder:
    """An order the broker still works, and what is left of it."""

    intent_id: UUID
    symbol: str
    side: Literal["BUY", "SELL"]
    remaining: int
    limit_price: Decimal
    session: date  # the session the order is worked on


@dataclass(frozen=True)
class AccountStatement:
    """The broker's account in euros after the events up to ``cursor``: cash and long positions."""

    cash_eur: Decimal
    positions: dict[str, int] = field(default_factory=dict)  # held instruments only
    cursor: int = 0


@dataclass(frozen=True)
class FillBatch:
    fills: tuple[Fill, ...]
    cursor: int  # the cursor of the next call: the fills after these


@runtime_checkable
class BrokerAdapter(Protocol):
    def submit(self, intent: OrderIntent, *, now: datetime) -> BrokerAck: ...

    def cancel(self, intent_id: UUID, *, reason: str, now: datetime) -> bool: ...

    def cancel_all(self, *, reason: str, now: datetime) -> tuple[UUID, ...]: ...

    def open_orders(self) -> tuple[BrokerOrder, ...]: ...

    def account_snapshot(self) -> AccountStatement: ...

    def fills_since(self, cursor: int) -> FillBatch: ...
