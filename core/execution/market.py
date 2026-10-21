"""What the paper loop knows of the market at an instant, from the finance store (ADR-031).

:class:`StoreMarket` gives the simulator a session's close as the store knows it at an instant,
and :func:`market_facts` reads what the Risk Gate needs of the market: reference data, the last
close and its age in sessions, ECB rates, average volumes. :func:`gate_snapshot` adds the
account and what the order book already commits. Every figure comes from the store, the
simulator, the book or the reconciliation log; none is guessed. A close the store keeps with
more than six decimals is not rounded into a price: it counts as missing (R7). Only records
already ingested at the instant are read (strict mode, R10).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext

import pandas as pd
from pydantic import ValidationError

from core.execution.book import OrderBook
from core.execution.broker import AccountStatement
from core.execution.paper import EURO, SessionBar, SimulatorError, next_exchange_session
from core.execution.states import OrderState
from core.finance.calendars import exchange_calendar, is_target_day
from core.finance.model import PriceRow, local_date
from core.finance.store import FinanceStore
from core.risk_gate.snapshot import (
    Account,
    AverageVolume,
    FxRate,
    GateSnapshot,
    InstrumentFacts,
    OpenOrder,
    Quote,
)

PLACES = Decimal("0.000001")  # the six decimals of the snapshot's amounts
# The orders the rate limits count: every booked intent that went past a proposal.
SENT = frozenset(OrderState) - {OrderState.INTENTION, OrderState.REJETEE}


class MarketError(Exception):
    """The market cannot be read at this instant: nothing is decided on it."""


def exact(value: float) -> Decimal | None:
    """``value`` as the decimal it prints as, or None beyond six decimals (never rounded)."""
    number = Decimal(str(value))
    exponent = number.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -6:
        return None
    return number


def sessions_since(mic: str, session: date, as_of: datetime) -> int:
    """Sessions of ``mic`` after ``session`` whose close is past at ``as_of``: a close's age."""
    calendar = exchange_calendar(mic, session.year, max(session.year, local_date(as_of).year))
    if calendar is None:
        raise MarketError(f"calendrier inconnu pour la place {mic}")
    closes = calendar.closes
    later = closes[(closes.index > pd.Timestamp(session)) & (closes <= pd.Timestamp(as_of))]
    return len(later)


def target_days_since(session: date, day: date) -> int:
    """TARGET days after ``session`` up to ``day`` included: the age of an ECB rate. The rate of
    ``day`` itself is counted as missing until its day is over, the cautious side."""
    count, current = 0, session + timedelta(days=1)
    while current <= day:
        count += is_target_day(current)
        current += timedelta(days=1)
    return count


def _bar(row: PriceRow) -> SessionBar | None:
    close = exact(row.close)
    if close is None:
        return None
    try:
        return SessionBar(
            symbol=row.instrument_id,
            session=row.session,
            close=close,
            volume=row.volume,
            currency=row.currency,
            published_at=row.published_at,
        )
    except ValidationError:
        return None


class StoreMarket:
    """The simulator's :class:`core.execution.paper.Market`: the store as known at ``as_of``."""

    def __init__(self, store: FinanceStore, *, as_of: datetime) -> None:
        self._store = store
        self._as_of = as_of

    def bar(self, symbol: str, session: date) -> SessionBar | None:
        rows = self._store.price_bars(
            symbol, as_of=self._as_of, start=session, end=session, strict=True
        )
        return _bar(rows[-1].record) if rows else None


@dataclass(frozen=True)
class MarketFacts:
    """The market part of the Gate's snapshot, and why an instrument lacks a part of it."""

    as_of: datetime
    instruments: dict[str, InstrumentFacts]
    quotes: dict[str, Quote]
    fx: dict[str, FxRate]
    volumes: dict[str, AverageVolume]
    open_markets: frozenset[str]
    gaps: dict[str, str] = field(default_factory=dict)  # symbol or currency -> what is missing


def _average(rows: list[PriceRow], sessions: int) -> AverageVolume | None:
    last = rows[-sessions:]
    volumes = [row.volume for row in last]
    if len(last) < sessions or any(volume is None for volume in volumes):
        return None
    with localcontext() as ctx:
        ctx.prec = 60
        mean = Decimal(sum(v for v in volumes if v is not None)) / sessions
        # The cautious side: a lower volume caps the order sooner.
        return AverageVolume(shares=mean.quantize(PLACES, ROUND_FLOOR), sessions=sessions)


def _rate(store: FinanceStore, currency: str, as_of: datetime) -> FxRate | None:
    series = store.fx_rates(currency, as_of=as_of, strict=True)
    if series.empty:
        return None
    units = exact(float(series.iloc[-1]))
    if units is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 60
        # Units per euro inverted, rounded up: a foreign holding never looks smaller in euros.
        eur_per_unit = (1 / units).quantize(PLACES, ROUND_CEILING)
    session = series.index[-1].date()
    return FxRate(
        eur_per_unit=eur_per_unit, sessions_old=target_days_since(session, local_date(as_of))
    )


def market_facts(
    store: FinanceStore, symbols: Iterable[str], *, as_of: datetime, volume_sessions: int | str
) -> MarketFacts:
    """What the store knows at ``as_of`` of ``symbols``. A missing part is left out and named
    in ``gaps``: the Gate then refuses the order, it never guesses (R7)."""
    day = local_date(as_of)
    instruments: dict[str, InstrumentFacts] = {}
    quotes: dict[str, Quote] = {}
    volumes: dict[str, AverageVolume] = {}
    open_markets: set[str] = set()
    gaps: dict[str, str] = {}
    for symbol in sorted(set(symbols)):
        instrument = store.instrument(symbol, as_of=as_of, strict=True)
        if instrument is None:
            gaps[symbol] = "absent du référentiel"
            continue
        facts = InstrumentFacts(
            asset_class=instrument.asset_class,
            currency=instrument.currency,
            sector=instrument.sector,
            country=instrument.country,
            mic=instrument.mic,
            isin=instrument.isin,
        )
        instruments[symbol] = facts
        try:
            next_exchange_session(facts.mic, day)
            open_markets.add(facts.mic)
        except SimulatorError:
            gaps[symbol] = f"calendrier inconnu pour la place {facts.mic}"
            continue
        rows = [stored.record for stored in store.price_bars(symbol, as_of=as_of, strict=True)]
        bar = _bar(rows[-1]) if rows else None
        if bar is None or bar.currency != facts.currency:
            gaps[symbol] = "aucun dernier cours exploitable"
            continue
        quotes[symbol] = Quote(
            price=bar.close,
            session=bar.session,
            published_at=bar.published_at,
            sessions_old=sessions_since(facts.mic, bar.session, as_of),
        )
        if isinstance(volume_sessions, str):
            gaps[symbol] = f"avg_volume_sessions vaut {volume_sessions} (R7)"
            continue
        average = _average(rows, volume_sessions)
        if average is None:
            gaps[symbol] = f"volume inconnu sur l'une des {volume_sessions} dernières séances"
            continue
        volumes[symbol] = average
    fx: dict[str, FxRate] = {}
    for currency in sorted({f.currency for f in instruments.values()} - {EURO}):
        rate = _rate(store, currency, as_of)
        if rate is None:
            gaps[currency] = "aucun taux BCE exploitable"
        else:
            fx[currency] = rate
    return MarketFacts(as_of, instruments, quotes, fx, volumes, frozenset(open_markets), gaps)


def gate_snapshot(
    facts: MarketFacts,
    *,
    account: Account,
    statement: AccountStatement,
    book: OrderBook,
    open_gaps: int,
) -> GateSnapshot:
    """The Gate's snapshot: the market facts, the account, the broker's holdings and what the
    book commits and has seen. Rate limits count every order that went past a proposal."""
    as_of = facts.as_of
    day = local_date(as_of)
    sent = [order.intent.created_at for order in book.orders(SENT)]
    return GateSnapshot(
        as_of=as_of,
        instruments=facts.instruments,
        quotes=facts.quotes,
        fx=facts.fx,
        volumes=facts.volumes,
        open_markets=facts.open_markets,
        holdings={s: q for s, q in statement.positions.items() if q > 0},
        open_orders=tuple(
            OpenOrder(
                symbol=order.intent.instrument.symbol,
                side=order.intent.side,
                remaining=order.remaining,
                limit_price=order.intent.limit_price,
            )
            for order in book.open_orders()
            if order.remaining
        ),
        account=account,
        orders_last_hour=sum(as_of - timedelta(hours=1) < at <= as_of for at in sent),
        orders_today=sum(local_date(at) == day for at in sent),
        seen_intent_ids=book.intent_ids(),
        open_reconciliation_gaps=open_gaps,
    )
