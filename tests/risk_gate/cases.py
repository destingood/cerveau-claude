"""Worlds for the Risk Gate's tests: plain data, built into the gate's six arguments on demand.

A world is a dict of plain values, so that a test or a strategy changes one field and builds
again. ``worlds()`` draws them near the edges: the quantity at, below and above the largest that
fits, a limit reached exactly or missed by one unit, and up to three faults (a missing datum, a
marker, a closed market...) injected on purpose. All instruments are fictitious.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any

from hypothesis import strategies as st

from core.config.loader import ComplianceConfig, DataQuality, PaperRiskLimits, TradingCosts
from core.execution.intent import OrderIntent
from core.execution.uuid7 import uuid7_from_fields
from core.finance.model import PARIS
from core.risk_gate.snapshot import GateSnapshot
from tests.risk_gate.oracle import size_bound

World = dict[str, Any]
AS_OF = datetime(2026, 10, 19, 15, 0, tzinfo=PARIS)  # a Monday, during the session
CLOSE_PUBLISHED = datetime(2026, 10, 16, 17, 35, tzinfo=PARIS)  # Friday's close
PRICE_AS_OF = datetime(2026, 10, 16, 17, 40, tzinfo=PARIS)
SYMBOLS = ("AAA", "BBB", "CCC", "DDD")
CURRENCIES = ("EUR", "USD", "GBP")
MICS = {"EUR": "XPAR", "USD": "XNYS", "GBP": "XLON"}
SECTORS = ("tech", "energie", "sante")
COUNTRIES = ("FR", "US", "DE")
CENT = Decimal("0.01")
TINY = Decimal("0.000001")


@dataclass(frozen=True)
class Case:
    world: World
    form: str  # how the intent reaches the gate: "model", "dict" or "json"
    label: str
    args: tuple[Any, ...]


def base_world() -> World:
    """An order of 3 AAA at 100.50 EUR that every check accepts, with the limits of D3."""
    return {
        "intent": {
            "intent_id": uuid7_from_fields(0x019A0000_0000, 0x123, 0x1234_5678_9ABC_DEF0),
            "created_at": AS_OF - timedelta(minutes=5),
            "decision_date": date(2026, 10, 19),
            "environment": "paper",
            "instrument": {
                "symbol": "AAA",
                "isin": "FR0000000001",
                "venue": "XPAR",
                "currency": "EUR",
            },
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": 3,
            "limit_price": Decimal("100.50"),
            "time_in_force": "DAY",
            "price_source": {
                "tool": "finance_data.market_data",
                "call_id": "market_data#1",
                "as_of": PRICE_AS_OF,
            },
            "sizing_source": {"tool": "rebalance", "call_id": "rebalance#1"},
            "rationale": {
                "thesis": "Le titre s'échange sous sa valeur estimée.",
                "catalyst": "Résultats trimestriels du 24 octobre.",
                "invalidation": "Marge opérationnelle sous 10 % au trimestre.",
                "horizon_days": 90,
                "confidence": 0.6,
            },
            "origin": {"kind": "strategy", "id": "momentum_12_1"},
            "committee_record_id": None,
        },
        "snapshot": {
            "as_of": AS_OF,
            "instruments": {
                "AAA": {
                    "asset_class": "equity",
                    "currency": "EUR",
                    "sector": "tech",
                    "country": "FR",
                    "mic": "XPAR",
                    "isin": "FR0000000001",
                },
                "BBB": {
                    "asset_class": "equity",
                    "currency": "USD",
                    "sector": "tech",
                    "country": "US",
                    "mic": "XNYS",
                },
                "CCC": {
                    "asset_class": "etf",
                    "currency": "EUR",
                    "sector": "energie",
                    "country": "DE",
                    "mic": "XPAR",
                },
                "DDD": {
                    "asset_class": "equity",
                    "currency": "GBP",
                    "sector": "sante",
                    "country": "US",
                    "mic": "XLON",
                },
            },
            "quotes": {
                symbol: {
                    "price": price,
                    "session": date(2026, 10, 16),
                    "published_at": CLOSE_PUBLISHED,
                    "sessions_old": 0,
                }
                for symbol, price in zip(
                    SYMBOLS,
                    (Decimal("100.00"), Decimal("50.00"), Decimal("20.00"), Decimal("10.00")),
                    strict=True,
                )
            },
            "fx": {
                "USD": {"eur_per_unit": Decimal("0.9"), "sessions_old": 0},
                "GBP": {"eur_per_unit": Decimal("1.15"), "sessions_old": 0},
            },
            "volumes": {s: {"shares": Decimal(1_000_000), "sessions": 20} for s in SYMBOLS},
            "open_markets": frozenset(MICS.values()),
            "holdings": {"BBB": 10, "CCC": 20},
            "open_orders": (),
            "account": {
                "cash_eur": Decimal("5000"),
                "equity_eur": Decimal("10000"),
                "peak_equity_eur": Decimal("10000"),
                "day_pnl_eur": Decimal("0"),
                "rolling_pnl_eur": Decimal("0"),
                "rolling_sessions": 20,
            },
            "orders_last_hour": 0,
            "orders_today": 0,
            "seen_intent_ids": frozenset(),
            "open_reconciliation_gaps": 0,
        },
        "limits": {
            "capital_reference_eur": 10000.0,
            "max_order_pct": 5.0,
            "max_position_pct": 10.0,
            "max_sector_pct": 30.0,
            "max_country_pct": 60.0,
            "max_currency_pct": 50.0,
            "max_daily_loss_pct": 2.0,
            "max_rolling_loss_pct": 5.0,
            "rolling_loss_sessions": 20,
            "max_drawdown_pct": 10.0,
            "max_orders_per_hour": 10,
            "max_orders_per_day": 20,
            "limit_price_collar_pct": 2.0,
            "min_avg_daily_volume": 100000.0,
            "avg_volume_sessions": 20,
            "universe": list(SYMBOLS),
            "allow": {"leverage": False, "short_selling": False, "derivatives": False},
        },
        "costs": {
            "commission_pct": Decimal("0.1"),
            "min_commission_eur": Decimal("1"),
            "slippage_bps": Decimal("5"),
            "fx_conversion_bps": Decimal("25"),
        },
        "compliance": {
            "fiscal": {
                "regime_plus_values": "A_DEFINIR",
                "comptes_etrangers_declaration": "A_DEFINIR",
            },
            "crypto": {"plateforme_autorisee_france": "A_DEFINIR"},
            "exclusions_personnelles": [],
        },
        "quality": {
            "max_staleness_sessions": 1,
            "min_quality_score_above_N1": 0.8,
            "outlier_robust_z": 5.0,
            "max_unexplained_move": 0.4,
        },
    }


def _intent_form(data: dict[str, Any], form: str) -> object:
    if form == "dict":
        return data
    try:
        intent = OrderIntent.model_validate(data)
    except ValueError:
        return data  # an invalid intent reaches the gate as the caller gave it
    return intent.model_dump_json() if form == "json" else intent


def build(world: World, form: str = "model", label: str = "") -> Case:
    return Case(
        world=world,
        form=form,
        label=label,
        args=(
            _intent_form(world["intent"], form),
            GateSnapshot.model_validate(world["snapshot"]),
            PaperRiskLimits.model_validate(world["limits"]),
            TradingCosts.model_validate(world["costs"]),
            ComplianceConfig.model_validate(world["compliance"]),
            DataQuality.model_validate(world["quality"]),
        ),
    )


def changed(world: World, **changes: Any) -> World:
    """A copy of ``world`` with ``part__field__...`` paths set; ``None`` at a dict key drops it."""
    result = copy.deepcopy(world)
    for path, value in changes.items():
        *parents, leaf = path.split("__")
        target = result
        for parent in parents:
            target = target[parent]
        if value is _DROP:
            del target[leaf]
        else:
            target[leaf] = value
    return result


_DROP = object()
DROP: Any = _DROP


# --- drawing worlds ----------------------------------------------------------------------------

LIMIT_KEYS = tuple(k for k in base_world()["limits"] if k != "allow")
COST_KEYS = tuple(base_world()["costs"])


def _price(draw: st.DrawFn, low: int, high: int) -> Decimal:
    return Decimal(draw(st.integers(low, high))) / 100


def _draw_market(draw: st.DrawFn, world: World) -> None:
    snap = world["snapshot"]
    for symbol in SYMBOLS:
        currency = draw(st.sampled_from(CURRENCIES))
        snap["instruments"][symbol].update(
            currency=currency,
            mic=MICS[currency],
            sector=draw(st.sampled_from(SECTORS)),
            country=draw(st.sampled_from(COUNTRIES)),
        )
        snap["quotes"][symbol]["price"] = _price(draw, 100, 10_000)
        snap["quotes"][symbol]["sessions_old"] = draw(st.sampled_from((0, 0, 0, 1)))
    for currency in ("USD", "GBP"):
        snap["fx"][currency] = {
            "eur_per_unit": Decimal(draw(st.integers(500_000, 1_500_000))) / 1_000_000,
            "sessions_old": draw(st.sampled_from((0, 0, 1))),
        }
    facts = snap["instruments"]["AAA"]
    world["intent"]["instrument"].update(currency=facts["currency"], venue=facts["mic"])


def _draw_book(draw: st.DrawFn, world: World) -> None:
    snap = world["snapshot"]
    snap["holdings"] = draw(
        st.dictionaries(st.sampled_from(SYMBOLS), st.integers(1, 8), max_size=3)
    )
    orders = draw(
        st.lists(
            st.fixed_dictionaries(
                {
                    "symbol": st.sampled_from(SYMBOLS),
                    "side": st.sampled_from(("BUY", "BUY", "SELL")),
                    "remaining": st.integers(1, 10),
                    "limit_price": st.integers(100, 10_000).map(lambda c: Decimal(c) / 100),
                }
            ),
            max_size=2,
        )
    )
    snap["open_orders"] = tuple(orders)
    peak = Decimal(draw(st.integers(8_000, 14_000)))
    drop = Decimal(draw(st.integers(0, 400))) / 10_000  # below every drawdown limit
    snap["account"] = {
        "cash_eur": _price(draw, 100_000, 5_000_000),
        "equity_eur": (peak * (1 - drop)).quantize(CENT),
        "peak_equity_eur": peak,
        "day_pnl_eur": _price(draw, -9_000, 20_000),
        "rolling_pnl_eur": _price(draw, -25_000, 40_000),
        "rolling_sessions": 20,
    }
    snap["orders_last_hour"] = draw(st.integers(0, 4))  # the edges reach the counts' limits
    snap["orders_today"] = snap["orders_last_hour"] + draw(st.integers(0, 5))


def _draw_limits(draw: st.DrawFn, world: World) -> None:
    pick = {
        "capital_reference_eur": (10000.0, 25000.0, 50000.0),
        "max_order_pct": (2.5, 5.0, 10.0, 20.0),
        "max_position_pct": (5.0, 10.0, 20.0),
        "max_sector_pct": (15.0, 30.0, 50.0),
        "max_country_pct": (30.0, 60.0),
        "max_currency_pct": (20.0, 50.0),
        "max_daily_loss_pct": (1.0, 2.0, 3.0),
        "max_rolling_loss_pct": (3.0, 5.0, 8.0),
        "max_drawdown_pct": (5.0, 10.0, 15.0),
        "max_orders_per_hour": (5, 10),
        "max_orders_per_day": (10, 20),
        "limit_price_collar_pct": (1.0, 2.0, 5.0),
    }
    for key, values in pick.items():
        world["limits"][key] = draw(st.sampled_from(values))
    world["costs"] = {
        "commission_pct": draw(st.sampled_from(("0", "0.1", "0.25"))),
        "min_commission_eur": draw(st.sampled_from(("0", "1", "2.5"))),
        "slippage_bps": draw(st.sampled_from(("0", "5", "10"))),
        "fx_conversion_bps": draw(st.sampled_from(("0", "25", "50"))),
    }
    world["costs"] = {key: Decimal(value) for key, value in world["costs"].items()}


def _draw_intent(draw: st.DrawFn, world: World) -> None:
    intent = world["intent"]
    intent["intent_id"] = uuid7_from_fields(
        draw(st.integers(0x0190_0000_0000, 0x019F_FFFF_FFFF)),
        draw(st.integers(0, (1 << 12) - 1)),
        draw(st.integers(0, (1 << 62) - 1)),
    )
    intent["side"] = draw(st.sampled_from(("BUY", "BUY", "SELL")))
    if intent["side"] == "SELL" and draw(st.booleans()):
        world["snapshot"]["holdings"]["AAA"] = draw(st.integers(50, 400))
    last = world["snapshot"]["quotes"]["AAA"]["price"]
    reach = int(world["limits"]["limit_price_collar_pct"] * 100)  # in basis points
    moved = last * (10_000 + draw(st.integers(-reach, reach))) / 10_000
    intent["limit_price"] = max(moved.quantize(CENT, ROUND_HALF_UP), CENT)
    if not draw(st.integers(0, 3)):
        intent["instrument"]["isin"] = None


# Each edge sets one limit exactly at what the world needs, or one unit beyond it.
def _edge_collar(draw: st.DrawFn, world: World) -> None:
    last = Decimal(draw(st.integers(5, 100)))
    collar = Decimal(str(world["limits"]["limit_price_collar_pct"]))
    sign = draw(st.sampled_from((1, -1)))
    beyond = CENT if draw(st.booleans()) else Decimal(0)
    world["snapshot"]["quotes"]["AAA"]["price"] = last
    world["intent"]["limit_price"] = (last + sign * (last * collar / 100 + beyond)).quantize(CENT)


def _edge_daily_loss(draw: st.DrawFn, world: World) -> None:
    limit = Decimal(str(world["limits"]["max_daily_loss_pct"]))
    capital = Decimal(str(world["limits"]["capital_reference_eur"]))
    beyond = TINY if draw(st.booleans()) else Decimal(0)
    world["snapshot"]["account"]["day_pnl_eur"] = -(limit * capital / 100) - beyond


def _edge_rolling_loss(draw: st.DrawFn, world: World) -> None:
    limit = Decimal(str(world["limits"]["max_rolling_loss_pct"]))
    capital = Decimal(str(world["limits"]["capital_reference_eur"]))
    beyond = TINY if draw(st.booleans()) else Decimal(0)
    world["snapshot"]["account"]["rolling_pnl_eur"] = -(limit * capital / 100) - beyond


def _edge_drawdown(draw: st.DrawFn, world: World) -> None:
    limit = Decimal(str(world["limits"]["max_drawdown_pct"]))
    account = world["snapshot"]["account"]
    beyond = TINY if draw(st.booleans()) else Decimal(0)
    account["equity_eur"] = account["peak_equity_eur"] * (1 - limit / 100) - beyond


def _edge_orders(draw: st.DrawFn, world: World) -> None:
    snap, limits = world["snapshot"], world["limits"]
    at = draw(st.sampled_from((0, 1)))
    if draw(st.booleans()):
        snap["orders_last_hour"] = limits["max_orders_per_hour"] - 1 + at
        snap["orders_today"] = snap["orders_last_hour"]
    else:
        snap["orders_last_hour"] = 0
        snap["orders_today"] = limits["max_orders_per_day"] - 1 + at


def _edge_volume(draw: st.DrawFn, world: World) -> None:
    minimum = Decimal(str(world["limits"]["min_avg_daily_volume"]))
    beyond = TINY if draw(st.booleans()) else Decimal(0)
    world["snapshot"]["volumes"]["AAA"]["shares"] = minimum - beyond


def _edge_freshness(draw: st.DrawFn, world: World) -> None:
    age = world["quality"]["max_staleness_sessions"] + draw(st.sampled_from((0, 1)))
    if draw(st.booleans()):
        world["snapshot"]["quotes"]["AAA"]["sessions_old"] = age
    else:
        currency = world["intent"]["instrument"]["currency"]
        if currency != "EUR":
            world["snapshot"]["fx"][currency]["sessions_old"] = age


def _edge_order_size(draw: st.DrawFn, world: World) -> None:
    """Capital such that ``target`` shares are exactly the largest order (an order in euros)."""
    if world["intent"]["instrument"]["currency"] != "EUR":
        return
    limit = draw(st.sampled_from((1, 2, 4, 5, 10, 20, 25, 50)))
    target = draw(st.integers(1, 60))
    capital = target * world["intent"]["limit_price"] * 100 / limit
    world["limits"]["max_order_pct"] = float(limit)
    world["limits"]["capital_reference_eur"] = float(capital)


def _edge_cash(draw: st.DrawFn, world: World) -> None:
    """Cash exactly what a buy of ``target`` shares needs, fees included (an order in euros)."""
    intent = world["intent"]
    if intent["instrument"]["currency"] != "EUR" or intent["side"] != "BUY":
        return
    world["snapshot"]["open_orders"] = ()
    costs = {key: Fraction(value) for key, value in world["costs"].items()}
    gross = draw(st.integers(1, 60)) * Fraction(intent["limit_price"])
    need = (
        gross
        + max(gross * costs["commission_pct"] / 100, costs["min_commission_eur"])
        + gross * costs["slippage_bps"] / 10_000
    )
    if (need * 10**6).denominator == 1:
        cash = Decimal(need.numerator) / Decimal(need.denominator)
        world["snapshot"]["account"]["cash_eur"] = cash - (TINY if draw(st.booleans()) else 0)


EDGES: dict[str, Callable[[st.DrawFn, World], None]] = {
    "collar": _edge_collar,
    "daily_loss": _edge_daily_loss,
    "rolling_loss": _edge_rolling_loss,
    "drawdown": _edge_drawdown,
    "orders": _edge_orders,
    "volume": _edge_volume,
    "freshness": _edge_freshness,
    "order_size": _edge_order_size,
    "cash": _edge_cash,
}


def _fault(draw: st.DrawFn, world: World, name: str) -> None:
    snap, intent, limits = world["snapshot"], world["intent"], world["limits"]
    other = draw(st.sampled_from(SYMBOLS[1:]))
    if name.startswith("marker:"):
        limits[name.removeprefix("marker:")] = draw(st.sampled_from(("A_DEFINIR", "A_VERIFIER")))
    elif name.startswith("cost:"):
        world["costs"][name.removeprefix("cost:")] = "A_DEFINIR"
    elif name.startswith("allow:"):
        limits["allow"][name.removeprefix("allow:")] = True
    elif name == "quality_marker":
        world["quality"]["max_staleness_sessions"] = "A_DEFINIR"
    elif name == "exclusion_marker":
        world["compliance"]["exclusions_personnelles"].append("A_VERIFIER")
    elif name == "exclude_symbol":
        world["compliance"]["exclusions_personnelles"].append("aaa")
    elif name == "exclude_sector":
        sector = snap["instruments"].get("AAA", {}).get("sector", "tech")
        world["compliance"]["exclusions_personnelles"].append(sector.upper())
    elif name == "exclude_isin":
        world["compliance"]["exclusions_personnelles"].append("fr0000000001")
    elif name == "exclude_other":
        world["compliance"]["exclusions_personnelles"].append("ZZZ")
    elif name == "drop_facts":
        snap["instruments"].pop(draw(st.sampled_from(SYMBOLS)), None)
    elif name == "drop_quote":
        snap["quotes"].pop(draw(st.sampled_from(SYMBOLS)), None)
    elif name == "drop_fx":
        snap["fx"].pop(draw(st.sampled_from(("USD", "GBP"))), None)
    elif name == "drop_volume":
        snap["volumes"].pop("AAA", None)
    elif name == "volume_sessions":
        snap["volumes"]["AAA"] = {"shares": Decimal(10**6), "sessions": 19}
    elif name == "rolling_sessions":
        snap["account"]["rolling_sessions"] = 19
    elif name == "market_closed":
        snap["open_markets"] = snap["open_markets"] - {intent["instrument"]["venue"]}
    elif name == "seen_id":
        snap["seen_intent_ids"] = frozenset({intent["intent_id"]})
    elif name == "other_day":
        snap["as_of"] = AS_OF + timedelta(days=1)
    elif name == "price_after":
        snap["as_of"] = PRICE_AS_OF - timedelta(minutes=2)
    elif name == "outside_universe":
        limits["universe"] = [s for s in SYMBOLS if s != "AAA"]
    elif name == "venue_mismatch":
        intent["instrument"]["venue"] = "XAMS"
    elif name == "currency_mismatch":
        given = intent["instrument"]["currency"]
        intent["instrument"]["currency"] = "USD" if given != "USD" else "EUR"
    elif name == "isin_mismatch":
        intent["instrument"]["isin"] = "US0000000002"
    elif name == "stale":
        snap["quotes"].get("AAA", {})["sessions_old"] = 3
        for rate in snap["fx"].values():
            rate["sessions_old"] = 3
    elif name == "reconciliation_gap":
        snap["open_reconciliation_gaps"] = 1
    elif name == "short":
        intent["side"] = "SELL"
        snap["holdings"].pop("AAA", None)
    elif name == "other_buys":
        snap["open_orders"] = (
            *snap["open_orders"],
            {"symbol": other, "side": "BUY", "remaining": 40, "limit_price": Decimal("90")},
        )
    elif name == "invalid_intent":
        intent["environment"] = "live"


FAULTS = (
    *(f"marker:{key}" for key in LIMIT_KEYS),
    *(f"cost:{key}" for key in COST_KEYS),
    *(f"allow:{key}" for key in ("leverage", "short_selling", "derivatives")),
    "quality_marker",
    "exclusion_marker",
    "exclude_symbol",
    "exclude_sector",
    "exclude_isin",
    "exclude_other",
    "drop_facts",
    "drop_quote",
    "drop_fx",
    "drop_volume",
    "volume_sessions",
    "rolling_sessions",
    "market_closed",
    "seen_id",
    "other_day",
    "price_after",
    "outside_universe",
    "venue_mismatch",
    "currency_mismatch",
    "isin_mismatch",
    "stale",
    "reconciliation_gap",
    "short",
    "other_buys",
    "invalid_intent",
)
QUANTITY_AIMS = ("at", "below", "above", "far", "any")


@st.composite
def cases(draw: st.DrawFn, max_faults: int = 3) -> Case:
    """A world near an edge, with the quantity aimed at the largest that fits."""
    world = base_world()
    _draw_market(draw, world)
    _draw_book(draw, world)
    _draw_limits(draw, world)
    _draw_intent(draw, world)
    labels = []
    edge = draw(st.sampled_from((*EDGES, *[None] * len(EDGES))))
    if edge is not None:
        EDGES[edge](draw, world)
        labels.append(f"edge:{edge}")
    faults = draw(st.sampled_from((*[0] * 12, 1, 1, 1, 2, 3)))
    for name in draw(st.lists(st.sampled_from(FAULTS), min_size=faults, max_size=faults)):
        if len(labels) - (edge is not None) < max_faults:
            _fault(draw, world, name)
            labels.append(name)
    world["intent"]["quantity"] = 1
    bound = size_bound(build(world).args)
    aim = draw(st.sampled_from(QUANTITY_AIMS))
    if bound is None or bound < 1 or aim == "any":
        quantity = draw(st.integers(1, 2_000))
    else:
        quantity = {
            "at": bound,
            "below": max(1, bound - draw(st.integers(1, 3))),
            "above": bound + 1,
            "far": bound * draw(st.integers(2, 5)) + draw(st.integers(0, 9)),
        }[aim]
    world["intent"]["quantity"] = min(quantity, 1_000_000_000)
    if world["intent"]["side"] == "SELL" and "short" not in labels:
        selling = sum(
            o["remaining"]
            for o in world["snapshot"]["open_orders"]
            if o["symbol"] == "AAA" and o["side"] == "SELL"
        )
        covered = world["intent"]["quantity"] + selling - draw(st.sampled_from((0, 1)))
        world["snapshot"]["holdings"]["AAA"] = covered
        if covered <= 0:
            del world["snapshot"]["holdings"]["AAA"]
        labels.append("edge:short_selling")
    labels.append(f"quantity:{aim}")
    form = draw(st.sampled_from(("model", "model", "dict", "json")))
    return build(world, form, " ".join(labels))
