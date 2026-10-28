"""What the Risk Gate knows at the decision: a snapshot frozen before it speaks (ADR-031).

The gate reads nothing else: no clock, no store, no book. Whoever builds the snapshot counts
sessions with the exchange calendar and reads the finance store and the order book as of
``as_of``; the gate only compares. Amounts are ``Decimal``, so that a limit reached to the cent
is reached, not missed by a float rounding. A price published after the decision, or an
equity above its own peak, cannot be put in a snapshot (R10).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from core.finance.model import AssetClass, Currency, InstrumentId

Amount = Annotated[Decimal, Field(allow_inf_nan=False, max_digits=24, decimal_places=6)]
Positive = Annotated[Decimal, Field(gt=0, allow_inf_nan=False, max_digits=24, decimal_places=6)]
Sessions = Annotated[int, Field(ge=0)]
Quantity = Annotated[int, Field(gt=0, le=1_000_000_000)]
Mic = Annotated[str, Field(pattern=r"^[A-Z0-9]{4}$")]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class InstrumentFacts(_Frozen):
    """An instrument's reference data, as the finance store gives it at the decision."""

    asset_class: AssetClass
    currency: Currency
    sector: str = Field(min_length=1, max_length=40)
    country: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    mic: Mic
    isin: Annotated[str, Field(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")] | None = None


class Quote(_Frozen):
    """The last close known at the decision, in the instrument's currency."""

    price: Positive
    session: date
    published_at: AwareDatetime
    sessions_old: Sessions  # sessions closed since ``session``, on the exchange's calendar


class FxRate(_Frozen):
    """Euros for one unit of a currency, and its age in sessions."""

    eur_per_unit: Positive
    sessions_old: Sessions


class AverageVolume(_Frozen):
    shares: Annotated[Decimal, Field(ge=0, allow_inf_nan=False, max_digits=24, decimal_places=6)]
    sessions: Annotated[int, Field(gt=0)]


class OpenOrder(_Frozen):
    """An order of the book not yet filled or cancelled: it still commits cash and exposure."""

    symbol: InstrumentId
    side: Literal["BUY", "SELL"]
    remaining: Quantity
    limit_price: Positive


class Account(_Frozen):
    """The paper account in euros: cash, equity and the losses the limits cap."""

    cash_eur: Amount
    equity_eur: Positive
    peak_equity_eur: Positive  # the highest equity reached: the drawdown's reference
    day_pnl_eur: Amount
    rolling_pnl_eur: Amount
    rolling_sessions: Annotated[int, Field(gt=0)]  # sessions summed in ``rolling_pnl_eur``

    @model_validator(mode="after")
    def _peak(self) -> Account:
        if self.equity_eur > self.peak_equity_eur:
            raise ValueError("equity_eur : au-dessus du plus haut, l'instantané est incohérent")
        return self


class GateSnapshot(_Frozen):
    as_of: AwareDatetime  # the decision instant
    instruments: dict[InstrumentId, InstrumentFacts]
    quotes: dict[InstrumentId, Quote]
    fx: dict[Currency, FxRate]  # every currency but the euro
    volumes: dict[InstrumentId, AverageVolume]
    open_markets: frozenset[Mic]  # exchanges open at the order's execution session
    holdings: dict[InstrumentId, Quantity]  # long positions only
    open_orders: tuple[OpenOrder, ...] = ()
    account: Account
    orders_last_hour: Sessions
    orders_today: Sessions
    seen_intent_ids: frozenset[UUID] = frozenset()
    open_reconciliation_gaps: Sessions = 0

    @model_validator(mode="after")
    def _point_in_time(self) -> GateSnapshot:
        late = sorted(s for s, quote in self.quotes.items() if quote.published_at > self.as_of)
        if late:
            raise ValueError(f"quotes : publiés après la décision (R10) : {', '.join(late)}")
        if "EUR" in self.fx:
            raise ValueError("fx : l'euro n'a pas de taux, il vaut 1")
        return self
