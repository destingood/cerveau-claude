"""An independent statement of the Risk Gate (ADR-031), for its tests only.

Written apart from ``core.risk_gate.gate``, from the plan's specification: exact fractions
instead of decimals, and the largest quantity in closed form instead of a search. Every
reducible limit is linear in the quantity q once the fee's maximum is split in two, since
``max(a, b) + c <= x`` holds exactly when ``a + c <= x`` and ``b + c <= x``; the largest
quantity is then the smallest floor of the bounds. A sale's cash is the one exception
(B188): what its fees exceed of its amount only shrinks as it grows, so it gives a lower
bound, :meth:`World.least`, and the quantity retained must reach it.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from zoneinfo import ZoneInfo

from core.config.loader import ComplianceConfig, DataQuality, PaperRiskLimits, TradingCosts
from core.execution.intent import OrderIntent
from core.risk_gate.snapshot import GateSnapshot, InstrumentFacts

PARIS = ZoneInfo("Europe/Paris")
MARKERS = {"A_DEFINIR", "A_VERIFIER"}
FIXED = (
    "idempotence",
    "decision",
    "instrument",
    "universe",
    "market_open",
    "min_avg_daily_volume",
    "limit_price_collar_pct",
    "price_freshness",
    "max_daily_loss_pct",
    "max_rolling_loss_pct",
    "max_drawdown_pct",
    "max_orders_per_hour",
    "max_orders_per_day",
    "allow",
    "short_selling",
    "rationale",
    "compliance",
    "reconciliation",
)
SIZED = (
    "max_order_pct",
    "max_position_pct",
    "max_sector_pct",
    "max_country_pct",
    "max_currency_pct",
    "cash",
)


class Missing(Exception):
    """A marker or an absent datum: the check is unknown."""


@dataclass(frozen=True)
class Expected:
    result: str
    quantity: int
    failed: frozenset[str]


def exact(value: object) -> Fraction:
    if isinstance(value, str):
        raise Missing(value)
    return Fraction(str(value))


def whole(value: object) -> int:
    if isinstance(value, str):
        raise Missing(value)
    assert isinstance(value, int)
    return value


def linear(slope: Fraction, room: Fraction) -> int | None:
    """The largest whole q with ``q * slope <= room``; None when every q fits, -1 when none."""
    if slope > 0:
        return math.floor(room / slope)
    return None if room >= 0 else -1


def tighter(*bounds: int | None) -> int | None:
    finite = [b for b in bounds if b is not None]
    return min(finite) if finite else None


@dataclass(frozen=True)
class World:
    intent: OrderIntent
    snap: GateSnapshot
    limits: PaperRiskLimits
    costs: TradingCosts
    rules: ComplianceConfig  # not ``compliance``: that name is the check's
    quality: DataQuality

    @property
    def symbol(self) -> str:
        return self.intent.instrument.symbol

    @property
    def currency(self) -> str:
        return self.intent.instrument.currency

    def facts(self, symbol: str) -> InstrumentFacts:
        if symbol not in self.snap.instruments:
            raise Missing(symbol)
        return self.snap.instruments[symbol]

    def rate(self, currency: str) -> Fraction:
        if currency == "EUR":
            return Fraction(1)
        if currency not in self.snap.fx:
            raise Missing(currency)
        return Fraction(self.snap.fx[currency].eur_per_unit)

    def close(self, symbol: str) -> Fraction:
        if symbol not in self.snap.quotes:
            raise Missing(symbol)
        return Fraction(self.snap.quotes[symbol].price)

    def unit(self) -> Fraction:
        return Fraction(self.intent.limit_price) * self.rate(self.currency)

    def capital(self) -> Fraction:
        return exact(self.limits.capital_reference_eur)

    # --- fixed checks: True or False, or Missing ------------------------------------------

    def idempotence(self) -> bool:
        return self.intent.intent_id not in self.snap.seen_intent_ids

    def decision(self) -> bool:
        day = self.snap.as_of.astimezone(PARIS).date()
        return (
            self.intent.decision_date == day and self.intent.price_source.as_of <= self.snap.as_of
        )

    def instrument(self) -> bool:
        facts, given = self.facts(self.symbol), self.intent.instrument
        return (
            facts.currency == given.currency
            and facts.mic == given.venue
            and given.isin in (None, facts.isin)
        )

    def universe(self) -> bool:
        if isinstance(self.limits.universe, str):
            raise Missing(self.limits.universe)
        return self.symbol in self.limits.universe

    def market_open(self) -> bool:
        return self.intent.instrument.venue in self.snap.open_markets

    def min_avg_daily_volume(self) -> bool:
        minimum = exact(self.limits.min_avg_daily_volume)
        sessions = whole(self.limits.avg_volume_sessions)
        volume = self.snap.volumes.get(self.symbol)
        if volume is None or volume.sessions != sessions:
            raise Missing("volume")
        return Fraction(volume.shares) >= minimum

    def limit_price_collar_pct(self) -> bool:
        collar, last = exact(self.limits.limit_price_collar_pct), self.close(self.symbol)
        return abs(Fraction(self.intent.limit_price) - last) * 100 <= collar * last

    def price_freshness(self) -> bool:
        limit = whole(self.quality.max_staleness_sessions)
        if self.symbol not in self.snap.quotes:
            raise Missing(self.symbol)
        ages = [self.snap.quotes[self.symbol].sessions_old]
        if self.currency != "EUR":
            if self.currency not in self.snap.fx:
                raise Missing(self.currency)
            ages.append(self.snap.fx[self.currency].sessions_old)
        return all(age <= limit for age in ages)

    def max_daily_loss_pct(self) -> bool:
        limit, capital = exact(self.limits.max_daily_loss_pct), self.capital()
        return max(-Fraction(self.snap.account.day_pnl_eur), Fraction(0)) * 100 <= limit * capital

    def max_rolling_loss_pct(self) -> bool:
        limit, capital = exact(self.limits.max_rolling_loss_pct), self.capital()
        if self.snap.account.rolling_sessions != whole(self.limits.rolling_loss_sessions):
            raise Missing("rolling_sessions")
        loss = max(-Fraction(self.snap.account.rolling_pnl_eur), Fraction(0))
        return loss * 100 <= limit * capital

    def max_drawdown_pct(self) -> bool:
        limit = exact(self.limits.max_drawdown_pct)
        peak = Fraction(self.snap.account.peak_equity_eur)
        return (peak - Fraction(self.snap.account.equity_eur)) * 100 <= limit * peak

    def max_orders_per_hour(self) -> bool:
        return self.snap.orders_last_hour < whole(self.limits.max_orders_per_hour)

    def max_orders_per_day(self) -> bool:
        return self.snap.orders_today < whole(self.limits.max_orders_per_day)

    def allow(self) -> bool:
        allow = self.limits.allow
        return not (allow.leverage or allow.short_selling or allow.derivatives)

    def short_selling(self) -> bool:
        if self.intent.side == "BUY":
            return True
        held = self.snap.holdings.get(self.symbol, 0)
        selling = sum(
            o.remaining
            for o in self.snap.open_orders
            if o.symbol == self.symbol and o.side == "SELL"
        )
        return self.intent.quantity + selling <= held

    def rationale(self) -> bool:
        """The size comes from the one tool that sizes the origin (B195): a strategy's own, the
        committee's rebalance proposal."""
        origin = self.intent.origin
        own = "strategy." + origin.id if origin.kind == "strategy" else "rebalance_proposal"
        return self.intent.sizing_source.tool == own

    def compliance(self) -> bool:
        exclusions = self.compliance_config_exclusions()
        facts = self.facts(self.symbol)
        names = {self.symbol.casefold(), facts.sector.casefold()}
        if facts.isin is not None:
            names.add(facts.isin.casefold())
        return not names & {entry.casefold() for entry in exclusions}

    def compliance_config_exclusions(self) -> list[str]:
        exclusions = self.rules.exclusions_personnelles
        if MARKERS & set(exclusions):
            raise Missing("exclusions")
        return exclusions

    def reconciliation(self) -> bool:
        return self.snap.open_reconciliation_gaps == 0

    # --- reducible checks: the largest q that passes, None when unbounded, or Missing ------

    def max_order_pct(self) -> int | None:
        limit, capital = exact(self.limits.max_order_pct), self.capital()
        return linear(self.unit() * 100, limit * capital)

    def exposure(
        self, limit_value: object, target: Callable[[], object], key: Callable[[str], object]
    ) -> int | None:
        """Holdings and open buys whose ``key`` is the order's ``target``, plus the order."""
        limit, capital = exact(limit_value), self.capital()
        if self.intent.side == "SELL":
            return None
        aim = target()
        held = Fraction(0)
        for symbol, quantity in self.snap.holdings.items():
            if key(symbol) == aim:
                currency = self.facts(symbol).currency
                held += quantity * self.close(symbol) * self.rate(currency)
        for order in self.snap.open_orders:
            if order.side == "BUY" and key(order.symbol) == aim:
                currency = self.facts(order.symbol).currency
                held += order.remaining * Fraction(order.limit_price) * self.rate(currency)
        return linear(self.unit() * 100, limit * capital - held * 100)

    def max_position_pct(self) -> int | None:
        return self.exposure(self.limits.max_position_pct, lambda: self.symbol, lambda s: s)

    def max_sector_pct(self) -> int | None:
        return self.exposure(
            self.limits.max_sector_pct,
            lambda: self.facts(self.symbol).sector,
            lambda s: self.facts(s).sector,
        )

    def max_country_pct(self) -> int | None:
        return self.exposure(
            self.limits.max_country_pct,
            lambda: self.facts(self.symbol).country,
            lambda s: self.facts(s).country,
        )

    def max_currency_pct(self) -> int | None:
        """Only a currency other than the euro is capped: the order's own, as it gives it."""
        if self.currency == "EUR":
            exact(self.limits.max_currency_pct), self.capital()
            return None
        return self.exposure(
            self.limits.max_currency_pct, lambda: self.currency, lambda s: self.facts(s).currency
        )

    def cash_terms(self) -> tuple[Fraction, Fraction, Fraction, Fraction]:
        """The commission rate, its minimum, the rate charged on top of both, the free cash."""
        costs = self.costs
        commission = exact(costs.commission_pct) / 100
        minimum = exact(costs.min_commission_eur)
        slippage = exact(costs.slippage_bps) / 10_000
        conversion = exact(costs.fx_conversion_bps) / 10_000

        def fee(gross: Fraction, currency: str) -> Fraction:
            extra = slippage + (conversion if currency != "EUR" else 0)
            return max(gross * commission, minimum) + gross * extra

        reserved = Fraction(0)
        for order in self.snap.open_orders:
            currency = self.facts(order.symbol).currency
            gross = order.remaining * Fraction(order.limit_price) * self.rate(currency)
            reserved += fee(gross, currency) + (gross if order.side == "BUY" else 0)
        extra = slippage + (conversion if self.currency != "EUR" else 0)
        return commission, minimum, extra, Fraction(self.snap.account.cash_eur) - reserved

    def cash(self) -> int | None:
        """A buy needs its amount and its fees. A sale needs what its fees exceed of its amount,
        ``max(0, fee - gross)`` (B188): out of reach when the free cash is negative, otherwise
        a lower bound on q, :meth:`least`, since that need only shrinks as the sale grows."""
        commission, minimum, extra, room = self.cash_terms()
        unit = self.unit()
        if self.intent.side == "SELL":
            if commission + extra >= 1:
                raise Missing("fees")  # a sale would never cover them
            return None if room >= 0 else -1
        return tighter(
            linear(unit * (1 + commission + extra), room),
            linear(unit * (1 + extra), room - minimum),
        )

    def least(self) -> int:
        """The smallest quantity a sale's cash allows, 1 for a buy. With ``g = q * unit``,
        ``max(g c, m) + g extra - g <= room`` splits in two: ``g (c + extra - 1) <= room``,
        true for every q once room >= 0 and c + extra < 1, and ``m + g (extra - 1) <= room``.
        """
        if self.intent.side == "BUY":
            return 1
        _, minimum, extra, room = self.cash_terms()
        return max(1, math.ceil((minimum - room) / (self.unit() * (1 - extra))))


def _intent(raw: object) -> OrderIntent:
    if isinstance(raw, OrderIntent):
        return raw
    if isinstance(raw, str):
        return OrderIntent.model_validate_json(raw)
    return OrderIntent.model_validate(raw)


def _world(args: tuple[object, ...]) -> World | None:
    raw, snap, limits, costs, compliance, quality = args
    try:
        intent = _intent(raw)
    except ValueError:
        return None
    return World(intent, snap, limits, costs, compliance, quality)  # type: ignore[arg-type]


def _bounds(world: World) -> dict[str, int | Missing | None]:
    found: dict[str, int | Missing | None] = {}
    for name in SIZED:
        try:
            found[name] = getattr(world, name)()
        except Missing as missing:
            found[name] = missing
    return found


def size_bound(args: tuple[object, ...]) -> int | None:
    """The largest quantity every reducible limit allows, whatever the request; None if unknown."""
    world = _world(args)
    if world is None:
        return None
    bounds = _bounds(world)
    if any(isinstance(b, Missing) for b in bounds.values()):
        return None
    return tighter(*(b for b in bounds.values() if not isinstance(b, Missing)))


def cash_floor(args: tuple[object, ...]) -> int | None:
    """The smallest quantity a sale's cash allows (B188), 1 for a buy; None if unknown."""
    world = _world(args)
    if world is None:
        return None
    try:
        world.cash()
        return world.least()
    except Missing:
        return None


def expected(args: tuple[object, ...]) -> Expected:
    """What the gate must answer: the result, the quantity retained and the checks that fail."""
    world = _world(args)
    if world is None:
        return Expected("REFUSE", 0, frozenset({"schema"}))
    failed: set[str] = set()
    for name in FIXED:
        try:
            ok = getattr(world, name)()
        except Missing:
            ok = False
        if not ok:
            failed.add(name)
    requested = world.intent.quantity
    bounds = _bounds(world)
    unknown = False
    for name, bound in bounds.items():
        if isinstance(bound, Missing):
            unknown = True
            failed.add(name)
        elif bound is not None and bound < requested:
            failed.add(name)
    least = 1 if isinstance(bounds["cash"], Missing) else world.least()
    if requested < least:
        failed.add("cash")
    if unknown or failed & set(FIXED):
        return Expected("REFUSE", 0, frozenset(failed))
    best = tighter(requested, *(b for b in bounds.values() if not isinstance(b, Missing)))
    assert best is not None
    if best < least:
        return Expected("REFUSE", 0, frozenset(failed))
    if best >= requested:
        return Expected("ACCEPTE", requested, frozenset(failed))
    return Expected("REDUIT", best, frozenset(failed))
