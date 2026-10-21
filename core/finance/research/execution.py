"""Orders, fills and trading costs shared by every backtest engine (ADR-024, D6).

A decision at t gives target weights; ``target_orders`` turns them into whole-share orders at the
prices known at t, and ``schedule`` fills them at the close of t+1: sells first, then buys by
increasing value gap, each buy cut to what the projected cash covers, fees included. The engines
share this code, so a cross-check compares their accounting, not two schedulers.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal

from core.config.loader import TradingCosts

Rounding = Literal["cent", "none"]


class CostsError(ValueError):
    """Trading costs are missing or invalid: no backtest runs without them (R7, R10)."""


@dataclass(frozen=True)
class Fill:
    """An executed order: signed quantity, price before slippage, and the cash it moved."""

    instrument_id: str
    quantity: int  # > 0 bought, < 0 sold
    price: float
    slippage: float  # €, always >= 0
    commission: float  # €, always >= 0
    cash: float  # signed: < 0 for a buy

    @property
    def amount(self) -> float:
        """The amount traded at the close, slippage and commission excluded."""
        return abs(self.quantity) * self.price

    @property
    def fees(self) -> float:
        return self.slippage + self.commission


@dataclass(frozen=True)
class Costs:
    """Trading costs as fractions, with the name every output that uses them must show."""

    name: str
    commission: float  # fraction of the amount traded: 0.001 for 0.1 %
    minimum: float  # € per order
    slippage: float  # fraction of the price: 0.0005 for 5 bps
    rounding: Rounding = "cent"

    def __post_init__(self) -> None:
        for field in ("commission", "minimum", "slippage"):
            value = getattr(self, field)
            if not math.isfinite(value) or value < 0:
                raise CostsError(f"frais {self.name} : {field} invalide ({value})")
        if self.slippage >= 1:
            raise CostsError(f"frais {self.name} : glissement de 100 % ou plus")

    @classmethod
    def from_config(cls, costs: TradingCosts, name: str, rounding: Rounding = "cent") -> Costs:
        """Costs from ``trading_costs``; a value still A_DEFINIR or A_VERIFIER refuses the run.

        ``fx_conversion_bps`` is checked but has no effect: the engines refuse any instrument
        outside EUR in phase 3 (ADR-024).
        """
        values = costs.model_dump()
        unknown = [field for field, value in values.items() if not isinstance(value, Decimal)]
        if unknown:
            raise CostsError(
                f"frais {name} : {', '.join(sorted(unknown))} à définir : backtest refusé "
                "(R7, D13 de la phase 2)"
            )
        return cls(
            name=name,
            commission=float(values["commission_pct"] / 100),
            minimum=float(values["min_commission_eur"]),
            slippage=float(values["slippage_bps"] / 10_000),
            rounding=rounding,
        )

    def balance(self, cash: float) -> float:
        """``cash`` as a broker holds it: to the cent in ``cent`` mode, so that no float drift
        between two fills cuts a buy that fits to the cent; as computed otherwise.

        The cent is the one below, never the nearest: a price with more than two decimals then
        never overstates the cash (B246). The 1e-6 of a cent only absorbs the float's drift, so
        that 12.34 held as 12.339999999999 stays 12.34."""
        if self.rounding != "cent":
            return cash
        return math.floor(cash * 100 + 1e-6) / 100  # an int over 100: never -0.0

    def stressed(self, multiplier: float) -> Costs:
        """Every cost multiplied: the cost-stress gate of the protocol."""
        if not math.isfinite(multiplier) or multiplier < 1:
            raise CostsError("un stress de frais multiplie par 1 ou plus")
        return replace(
            self,
            name=f"{self.name} × {multiplier:g}",
            commission=self.commission * multiplier,
            minimum=self.minimum * multiplier,
            slippage=self.slippage * multiplier,
        )

    def fill(self, instrument_id: str, quantity: int, price: float) -> Fill:
        """Execute ``quantity`` shares at ``price``: p(1±s), commission max(m, c·q·p(1±s)).

        In ``cent`` mode, slippage and commission are each rounded to the cent, half to even
        on the binary value of the float (Python's round).
        """
        if not quantity:
            raise ValueError("ordre de quantité nulle")
        if not math.isfinite(price) or price <= 0:
            raise ValueError(f"{instrument_id} : prix d'exécution invalide ({price})")
        side = 1 if quantity > 0 else -1
        amount = abs(quantity) * price
        slippage = amount * self.slippage
        commission = max(self.minimum, self.commission * amount * (1 + side * self.slippage))
        if self.rounding == "cent":
            slippage, commission = round(slippage, 2), round(commission, 2)
        cash = -side * amount - slippage - commission
        return Fill(instrument_id, quantity, price, slippage, commission, cash)


@dataclass(frozen=True)
class Order:
    """A whole-share order decided at t: signed quantity and the value gap w·V − q·p."""

    instrument_id: str
    quantity: int
    gap: float


def target_orders(
    weights: Mapping[str, float],
    positions: Mapping[str, int],
    prices: Mapping[str, float],
    value: float,
) -> list[Order]:
    """Orders toward the targets qᶜ = w·V/p, truncated toward zero: never past the target.

    ``prices`` must hold every instrument with a weight or a position; an instrument with
    neither is skipped.
    """
    orders: list[Order] = []
    for instrument_id in sorted(set(weights) | {i for i, q in positions.items() if q}):
        weight, held = weights.get(instrument_id, 0.0), positions.get(instrument_id, 0)
        if not weight and not held:
            continue
        price = prices[instrument_id]
        quantity = math.trunc(weight * value / price - held)
        if quantity:
            orders.append(Order(instrument_id, quantity, weight * value - held * price))
    return orders


@dataclass(frozen=True)
class Cut:
    """An order the cash could not cover in full: what was asked, what was filled."""

    order: Order
    filled: int


@dataclass(frozen=True)
class Schedule:
    fills: list[Fill]
    cuts: list[Cut]
    cash: float


def affordable(quantity: int, price: float, cash: float, costs: Costs) -> int:
    """The largest buy of at most ``quantity`` shares that leaves the cash at zero or above."""
    if quantity <= 0:
        raise ValueError("un achat porte sur une quantité positive")

    def fits(shares: int) -> bool:
        return costs.balance(cash + costs.fill("", shares, price).cash) >= 0

    if fits(quantity):
        return quantity
    # The cost of a buy never falls when it grows: bisect on the number of shares.
    low, high = 0, quantity
    while high - low > 1:
        middle = (low + high) // 2
        low, high = (middle, high) if fits(middle) else (low, middle)
    return low


def schedule(
    orders: Sequence[Order], cash: float, prices: Mapping[str, float], costs: Costs
) -> Schedule:
    """Fill the orders of t at the closes of t+1, sells first, then buys by increasing gap.

    A sell whose fees would push the cash below zero is refused; a buy is cut to what the cash
    covers. Neither is carried over: the next decision starts again from the targets.
    """
    fills: list[Fill] = []
    cuts: list[Cut] = []
    ordered = sorted(orders, key=lambda o: (o.gap, o.instrument_id))
    for order in [o for o in ordered if o.quantity < 0] + [o for o in ordered if o.quantity > 0]:
        price = prices[order.instrument_id]
        quantity = order.quantity
        if quantity > 0:
            quantity = affordable(quantity, price, cash, costs)
        elif costs.balance(cash + costs.fill(order.instrument_id, quantity, price).cash) < 0:
            quantity = 0
        if quantity != order.quantity:
            cuts.append(Cut(order, quantity))
        if quantity:
            fill = costs.fill(order.instrument_id, quantity, price)
            cash = costs.balance(cash + fill.cash)
            fills.append(fill)
    return Schedule(fills, cuts, cash)
