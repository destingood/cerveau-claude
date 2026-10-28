"""Orders, fills and journals shared by the execution tests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from core.execution.book import Fill, Recorder
from core.execution.intent import OrderIntent
from core.execution.uuid7 import uuid7_from_fields
from core.finance.model import PARIS
from tests.test_execution_intent import intent_data

DECISION_PRICE = Decimal("123.00")  # the last close the Risk Gate saw
FILLED_AT = datetime(2026, 10, 19, 17, 35, tzinfo=PARIS)  # the close of the next session
SESSION = date(2026, 10, 19)
BOOKED_AT = datetime(2026, 10, 19, 18, 0, tzinfo=PARIS)


def make_intent(n: int = 0, **changes: Any) -> OrderIntent:
    """The n-th order: a later UUIDv7 for each n, Annex C.2's example otherwise."""
    intent_id = uuid7_from_fields(0x0199F1A2B3C4 + n, 0x123, 0x1234_5678_9ABC_DEF0 + n)
    return OrderIntent.model_validate(intent_data(intent_id=intent_id, **changes))


def make_fill(intent: OrderIntent, n: int, quantity: int, **changes: Any) -> Fill:
    data: dict[str, Any] = {
        "fill_id": f"paper:{intent.intent_id.hex[-12:]}:{n}",
        "intent_id": intent.intent_id,
        "executed_at": FILLED_AT,
        "session": SESSION,
        "quantity": quantity,
        "price": intent.limit_price,
        "fees": Decimal("1.50"),
        "currency": intent.instrument.currency,
    } | changes
    return Fill.model_validate(data)


class MemoryJournal:
    """The audit journal's ``append``, kept in memory; ``fail_at`` refuses that call (1-based)."""

    def __init__(self, fail_at: int | None = None) -> None:
        self.entries: list[dict[str, Any]] = []
        self.calls = 0
        self.fail_at = fail_at

    def append(
        self,
        *,
        actor: str,
        event: str,
        request_id: str | None = None,
        versions: Mapping[str, str] | None = None,
        payload: Any = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.calls += 1
        if self.calls == self.fail_at:
            raise OSError("journal indisponible")
        entry = {"actor": actor, "event": event, "request_id": request_id, "payload": payload}
        self.entries.append(entry)
        return entry

    @property
    def states(self) -> list[tuple[str, str]]:
        return [(e["payload"]["intent_id"], e["payload"]["state"]) for e in self.entries]


def recorder(journal: Any) -> Recorder:
    return Recorder(journal=journal, actor="orchestrator", request_id="paper-test")
