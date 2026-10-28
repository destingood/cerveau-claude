"""The one interface between CERVEAU and a broker, paper or real (ADR-033).

The rest of the code knows only :class:`BrokerAdapter`. The broker keeps its own accounting:
what it reports (acknowledgements, fills, open orders, the account) is what the order book and
the reconciliation compare with CERVEAU's own records, never something they take on trust.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from core.execution.actions import AccountAction
from core.execution.book import Fill
from core.execution.intent import OrderIntent


class AckCode(StrEnum):
    """What a broker's answer means, in CERVEAU's own closed vocabulary (B197).

    A client maps its broker's answers onto these codes; what it cannot map stays ``INCONNU``.
    """

    ACCEPTE = "accepte"
    DEJA_RECU = "deja_recu"
    AUTRE_CONTENU = "autre_contenu"
    POSITION_INSUFFISANTE = "position_insuffisante"
    CASH_INSUFFISANT = "cash_insuffisant"
    SEANCE_CLOSE = "seance_close"
    HORS_PERIMETRE = "hors_perimetre"
    INCONNU = "inconnu"


# What the book and the reports say of an answer: our words, never the broker's (ADR-034, B197).
ACK_LABELS: dict[AckCode, str] = {
    AckCode.ACCEPTE: "ordre accepté par le courtier",
    AckCode.DEJA_RECU: "intent_id déjà reçu par le courtier : aucun second ordre",
    AckCode.AUTRE_CONTENU: "intent_id déjà reçu par le courtier avec un autre contenu",
    AckCode.POSITION_INSUFFISANTE: "position insuffisante : pas de vente à découvert (D16)",
    AckCode.CASH_INSUFFISANT: "cash libre insuffisant, frais compris : pas de levier (D16)",
    AckCode.SEANCE_CLOSE: "séance visée déjà close chez le courtier",
    AckCode.HORS_PERIMETRE: (
        "ordre hors du périmètre du courtier (date, devise, montant ou calendrier)"
    ),
    AckCode.INCONNU: "refus du courtier (code inconnu)",
}


@dataclass(frozen=True)
class BrokerAck:
    """The broker's answer to a submission: accepted, or rejected, with its code.

    ``duplicate`` marks an ``intent_id`` the broker had already received: nothing new was sent,
    and the answer is the one of the first submission, or a rejection if the content differs.
    ``reason`` is the broker's own text: external content, never written to the book, the
    journal or a report; ``code`` is what they record, through :data:`ACK_LABELS` (B197).
    """

    intent_id: UUID
    accepted: bool
    reason: str
    duplicate: bool = False
    code: AckCode = AckCode.INCONNU

    @property
    def label(self) -> str:
        return ACK_LABELS[self.code]


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
    """The broker's account in euros after the events up to ``cursor``: cash and long positions.

    ``cursor`` counts in the same sequence as :attr:`FillBatch.cursor`: a statement and a batch
    of fills read with equal cursors describe the same instant (B169). The splits and dividends
    the broker booked are not in that sequence: the paper loop books them before it reads the
    account, never between the two reads (ADR-042).
    """

    cash_eur: Decimal
    positions: dict[str, int] = field(default_factory=dict)  # held instruments only
    cursor: int = 0
    actions: tuple[AccountAction, ...] = ()  # the splits and dividends booked (B187)


@dataclass(frozen=True)
class FillBatch:
    fills: tuple[Fill, ...]
    cursor: int  # the cursor of the next call, in the sequence of AccountStatement.cursor


# What a call the broker does not answer raises: whether it arrived is unknown (§12, chaos).
NETWORK_ERRORS: tuple[type[OSError], ...] = (TimeoutError, ConnectionError)


@runtime_checkable
class BrokerAdapter(Protocol):
    """A call the broker does not answer raises one of :data:`NETWORK_ERRORS`; it is never
    retried without the ``intent_id`` that makes it idempotent."""

    def submit(self, intent: OrderIntent, *, now: datetime) -> BrokerAck: ...

    def cancel(self, intent_id: UUID, *, reason: str, now: datetime) -> bool: ...

    def cancel_all(self, *, reason: str, now: datetime) -> tuple[UUID, ...]: ...

    def open_orders(self) -> tuple[BrokerOrder, ...]: ...

    def account_snapshot(self) -> AccountStatement: ...

    def fills_since(self, cursor: int) -> FillBatch: ...
