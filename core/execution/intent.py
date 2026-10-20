"""The order intent: the only form in which an order leaves a decision (Annex C.2, ADR-029).

The model never writes an intent: the deterministic drafter fills every figure from the tool
calls it cites (R1), and the model supplies only the texts of the rationale. The schema refuses
what phase 4 forbids, whatever the caller: a live environment, a market order, a fractional
quantity, a price from after the decision (R3, R10).
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import RFC_4122

from pydantic import (
    UUID7,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from core.finance.model import (
    Currency,
    InstrumentId,
    canonical_json,
    local_date,
    plain_text,
)
from core.verification.trace import CallId

MAX_QUANTITY = 1_000_000_000
MAX_HORIZON_DAYS = 3650
RATIONALE_CHARS = 400

ToolName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}(\.[a-z][a-z0-9_]{0,63})?$")]
OriginId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")]
Price = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2, allow_inf_nan=False)]
Rationale = Annotated[str, Field(min_length=1, max_length=RATIONALE_CHARS)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class OrderInstrument(_Strict):
    symbol: InstrumentId  # the finance store's instrument id, the one the universe lists
    isin: Annotated[str, Field(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")] | None = None
    venue: Annotated[str, Field(pattern=r"^[A-Z0-9]{4}$")]  # the exchange's MIC
    currency: Currency


class PriceSource(_Strict):
    """The journaled tool call that gave the last price, and when that price was published."""

    tool: ToolName
    call_id: CallId
    as_of: AwareDatetime


class SizingSource(_Strict):
    """The journaled tool call that computed the quantity."""

    tool: ToolName
    call_id: CallId


class IntentRationale(_Strict):
    thesis: Rationale
    catalyst: Rationale
    invalidation: Rationale
    horizon_days: int = Field(ge=1, le=MAX_HORIZON_DAYS)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)

    @field_validator("thesis", "catalyst", "invalidation")
    @classmethod
    def _plain(cls, value: str) -> str:
        return plain_text(value)


class IntentOrigin(_Strict):
    """What proposed the order (D8): a ``candidate`` strategy or a committee sitting."""

    kind: Literal["strategy", "committee"]
    id: OriginId


class OrderIntent(_Strict):
    intent_id: UUID7  # also the client order id (ADR-032)
    created_at: AwareDatetime
    decision_date: date
    environment: Literal["paper"]
    instrument: OrderInstrument
    side: Literal["BUY", "SELL"]
    order_type: Literal["LIMIT"]
    quantity: int = Field(gt=0, le=MAX_QUANTITY)
    limit_price: Price
    time_in_force: Literal["DAY"]
    price_source: PriceSource
    sizing_source: SizingSource
    rationale: IntentRationale
    origin: IntentOrigin
    committee_record_id: OriginId | None = None

    @field_validator("intent_id")
    @classmethod
    def _rfc_variant(cls, value: UUID7) -> UUID7:
        if value.variant != RFC_4122:
            raise ValueError("intent_id : variante autre que celle de la RFC 9562")
        return value

    @model_validator(mode="after")
    def _coherent(self) -> OrderIntent:
        if self.decision_date != local_date(self.created_at):
            raise ValueError("decision_date : différente de la date de created_at à Paris")
        if self.price_source.as_of > self.created_at:
            raise ValueError("price_source.as_of : cours publié après l'intention (R10)")
        if self.origin.kind == "committee":
            if self.committee_record_id != self.origin.id:
                raise ValueError("committee_record_id : requis et égal à origin.id (D8)")
        elif self.committee_record_id is not None:
            raise ValueError("committee_record_id : réservé à une origine committee")
        return self

    def sha256(self) -> str:
        """The fingerprint the journal records with each state of the order (ADR-032)."""
        return hashlib.sha256(canonical_json(self.model_dump(mode="json")).encode()).hexdigest()
