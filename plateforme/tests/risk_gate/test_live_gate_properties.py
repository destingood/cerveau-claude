"""The live Risk Gate against an oracle written apart, on orders drawn near every limit (B353).

The oracle recomputes each limit in fractions, from the same plain values: the gate accepts an
order if and only if the oracle finds it within every limit. Drawn faults (a marker, a missing,
infinite, zero or negative value, a permission switched on, an instrument off the whitelist, a
book of another day) must always refuse. Derandomized, so that the CI replays the same cases.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from core.config.loader import LiveAllow, LiveConfig, LiveLimits
from core.finance.model import PARIS
from core.risk_gate.live import JournaledOrder, LiveBook, evaluate_live, fingerprint
from tests.execution_cases import make_intent

NOW = datetime(2026, 10, 17, 14, 10, tzinfo=PARIS)
COMMON: dict[str, Any] = {
    "derandomize": True,
    "deadline": None,
    "database": None,
    "suppress_health_check": [HealthCheck.too_slow],
}
MAIN = settings(max_examples=3_000, **COMMON)
MIN_SHARE = 0.2  # of each outcome among the cases drawn without a fault
PCTS = ("max_order_pct", "max_position_pct", "max_daily_loss_pct")
FAULTS = (
    "marker",
    "absent",
    "infinite",
    "zero",
    "negative",
    "allow",
    "whitelist",
    "disabled",
    "day",
    "timezone",
    "stale",
)
CENT = Decimal("0.01")


@dataclass(frozen=True)
class World:
    side: str
    quantity: int
    limit_price: Decimal
    last_price: Decimal
    held: int
    open_buy: int  # shares of the same instrument still to buy, at the limit price
    open_sell: int
    accepted: int  # shares of a buy the gate accepted today, not yet in the book (M4)
    cash: Decimal
    day_pnl: Decimal
    orders_today: int
    capital: float
    limits: dict[str, Any]
    fault: str | None
    fault_key: str


def _cents(low: int, high: int) -> st.SearchStrategy[Decimal]:
    return st.integers(low, high).map(lambda n: Decimal(n) * CENT)


@st.composite
def worlds(draw: st.DrawFn) -> World:
    return World(
        side=draw(st.sampled_from(("BUY", "SELL"))),
        quantity=draw(st.integers(1, 30)),
        limit_price=draw(_cents(100, 10_000)),
        last_price=draw(_cents(100, 10_000)),
        held=draw(st.integers(0, 200)),
        open_buy=draw(st.integers(0, 10)),
        open_sell=draw(st.integers(0, 10)),
        accepted=draw(st.integers(0, 10)),
        cash=draw(_cents(0, 5_000_000)),
        day_pnl=draw(_cents(-100_000, 100_000)),
        orders_today=draw(st.integers(0, 2)),
        capital=draw(st.integers(50_000, 500_000).map(float)),
        limits={
            **{name: draw(st.integers(50, 10_000).map(lambda n: n / 100)) for name in PCTS},
            "max_orders_per_day": draw(st.integers(1, 8)),
        },
        fault=draw(st.none() | st.sampled_from(FAULTS)),
        fault_key=draw(st.sampled_from((*PCTS, "max_orders_per_day", "capital_reference_eur"))),
    )


def _live(world: World) -> LiveConfig:
    limits: dict[str, Any] = dict(world.limits)
    fields: dict[str, Any] = {
        "enabled": True,
        "broker": "courtier-de-test",
        "allow": {"leverage": False, "short_selling": False, "derivatives": False},
        "instruments_whitelist": ["FICT-ACME"],
        "capital_reference_eur": world.capital,
        "timezone": "Europe/Paris",
        "max_book_age_s": 600,
    }
    bad = {
        "marker": "A_DEFINIR",
        "absent": None,
        "infinite": float("inf"),
        "zero": 0,
        "negative": -1,
    }
    if world.fault in bad:
        target = limits if world.fault_key in limits else fields
        target[world.fault_key] = bad[world.fault]
    elif world.fault == "allow":
        fields["allow"] = fields["allow"] | {"short_selling": True}
    elif world.fault == "whitelist":
        fields["instruments_whitelist"] = ["FICT-OTHER"]
    elif world.fault == "disabled":
        fields["enabled"] = False
    elif world.fault == "timezone":
        fields["timezone"] = "A_DEFINIR"
    fields["allow"] = LiveAllow.model_construct(**fields["allow"])
    return LiveConfig.model_construct(limits=LiveLimits.model_construct(**limits), **fields)


def _book(world: World) -> LiveBook:
    orders = [
        {"symbol": "FICT-ACME", "side": side, "remaining": n, "limit_price": world.limit_price}
        for side, n in (("BUY", world.open_buy), ("SELL", world.open_sell))
        if n
    ]
    return LiveBook.model_validate(
        {
            "as_of": NOW - timedelta(seconds=601 if world.fault == "stale" else 60),
            "day": date(2026, 10, 16) if world.fault == "day" else date(2026, 10, 17),
            "instruments": {
                "FICT-ACME": {
                    "asset_class": "equity",
                    "currency": "EUR",
                    "last_price": world.last_price,
                    "priced_at": NOW - timedelta(minutes=20),
                }
            },
            "fx": {},
            "holdings": {"FICT-ACME": world.held} if world.held else {},
            "open_orders": tuple(orders),
            "cash_eur": world.cash,
            "day_pnl_eur": world.day_pnl,
            "orders_today": world.orders_today,
        }
    )


def _journaled(world: World) -> tuple[JournaledOrder, ...]:
    if not world.accepted:
        return ()
    order = {
        "intent_sha256": fingerprint(make_intent(1)),
        "decided_at": NOW - timedelta(minutes=3),
        "symbol": "FICT-ACME",
        "side": "BUY",
        "quantity": world.accepted,
        "limit_price": world.limit_price,
        "currency": "EUR",
    }
    return (JournaledOrder.model_validate(order),)


def within_every_limit(world: World) -> bool:
    """The oracle, in fractions: the order keeps within each limit of ``live.yaml``."""
    capital = Fraction(str(world.capital))
    pct = {name: Fraction(str(world.limits[name])) for name in PCTS}
    unit = Fraction(max(world.limit_price, world.last_price))
    amount = world.quantity * unit
    buying = (world.open_buy + world.accepted) * Fraction(world.limit_price)
    loss = max(-Fraction(world.day_pnl), Fraction(0))
    if world.side == "BUY":
        position = world.held * Fraction(world.last_price) + buying + amount
        sized = position * 100 <= pct["max_position_pct"] * capital
        covered = buying + amount <= Fraction(world.cash)
    else:
        sized = True
        covered = world.quantity <= world.held - world.open_sell
    return (
        amount * 100 <= pct["max_order_pct"] * capital
        and sized
        and covered
        and loss * 100 < pct["max_daily_loss_pct"] * capital
        and world.orders_today + bool(world.accepted) + 1 <= world.limits["max_orders_per_day"]
    )


def test_no_order_beyond_a_limit_is_ever_accepted() -> None:
    seen: Counter[str] = Counter()

    @MAIN
    @given(worlds())
    def agree(world: World) -> None:
        intent = make_intent(
            0, side=world.side, quantity=world.quantity, limit_price=world.limit_price
        )
        got = evaluate_live(
            intent, _live(world), _book(world), now=NOW, journaled=_journaled(world)
        )
        if world.fault is not None:
            assert got.result == "REFUSE", world
            assert got.quantity == 0
            seen[f"fault:{world.fault}"] += 1
            return
        want = "ACCEPTE" if within_every_limit(world) else "REFUSE"
        assert got.result == want, world
        assert got.quantity == (world.quantity if want == "ACCEPTE" else 0)
        seen[want] += 1

    agree()
    # A generator drifting to one outcome, or never drawing a fault, would prove nothing.
    clean = seen["ACCEPTE"] + seen["REFUSE"]
    assert seen["ACCEPTE"] >= MIN_SHARE * clean, seen
    assert seen["REFUSE"] >= MIN_SHARE * clean, seen
    assert all(seen[f"fault:{fault}"] >= 10 for fault in FAULTS), seen
