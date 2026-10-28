"""Splits and dividends on the paper account, replayed with its fills (ADR-042, B187).

An action applies at its session: the first session of the instrument's exchange on or after its
ex-date. A split applies at the start of that session: the shares held become ``held × ratio``; a
result within :data:`TOLERANCE` of a whole number is that number, otherwise the fraction is paid
in cash at the session's close, rounded down to the cent. A dividend entitles the shares held at
the start of its session, after that session's splits, and is credited at that session, rounded
down to the cent; one in another currency than the euro is not credited (the paper account holds
euros only, ADR-033). The backtest engine rounds both to the nearest cent: the paper account is at
most one cent lower, the cautious side.

Everything here is pure: the simulator replays its own fills with the actions it booked, and the
reconciliation replays CERVEAU's book with the same actions, so that both compute the same effect.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal, localcontext
from typing import Literal

from core.execution.states import ExecutionIncident

TOLERANCE = Decimal("1e-9")  # the backtest engine's SPLIT_TOLERANCE
CENT = Decimal("0.01")
EURO = "EUR"
DIGITS = 60  # the portfolio's DECIMAL_DIGITS: every product here is exact


def exact_value(value: float) -> Decimal:
    """A stored float as the decimal it was written as: ``2.0`` is 2, ``0.35`` is 0.35."""
    return Decimal(int(value)) if value.is_integer() else Decimal(repr(value))


@dataclass(frozen=True)
class AccountAction:
    """A split or a dividend as the account books it, at ``session``."""

    session: date  # the first session of the exchange on or after ``ex_date``
    symbol: str
    ex_date: date
    kind: Literal["split", "dividend"]
    value: Decimal  # new shares per old share, or the dividend per share
    currency: str | None = None  # the dividend's
    close: Decimal | None = None  # the close of ``session``: the price of a split's fraction

    def __post_init__(self) -> None:
        if not (self.value.is_finite() and self.value > 0):
            raise ValueError("opération sur titres : valeur positive")
        if self.session < self.ex_date:
            raise ValueError("opération sur titres : séance avant l'ex-date")
        split = self.kind == "split"
        if split != (self.close is not None) or split == (self.currency is not None):
            raise ValueError("un split porte la clôture de sa séance, un dividende sa devise")

    @property
    def key(self) -> tuple[date, str, date, str]:
        return (self.session, self.symbol, self.ex_date, self.kind)

    def text(self) -> dict[str, str | None]:
        """What a fingerprint covers."""
        return {
            "symbol": self.symbol,
            "kind": self.kind,
            "ex_date": str(self.ex_date),
            "session": str(self.session),
            "value": str(self.value),
            "currency": self.currency,
            "close": None if self.close is None else str(self.close),
        }


@dataclass(frozen=True)
class Movement:
    """A fill as the account sees it: shares in (positive) or out, and the cash it moves."""

    session: date
    symbol: str
    shares: int
    cash: Decimal = Decimal(0)


@dataclass(frozen=True)
class Effect:
    action: AccountAction
    held: int  # the shares the action applied to
    shares: int  # the shares after it; a dividend leaves them
    cash: Decimal  # in euros: the price of a split's fraction, or the dividend


@dataclass(frozen=True)
class Replay:
    positions: dict[str, int]  # held instruments only, sorted
    cash: Decimal  # what the movements and the actions moved, without the capital
    effects: tuple[Effect, ...]  # in the order they applied; none on a position of zero


def split_effect(action: AccountAction, held: int) -> Effect:
    with localcontext() as ctx:
        ctx.prec = DIGITS
        shares = held * action.value
        nearest = shares.to_integral_value()
        if abs(shares - nearest) <= TOLERANCE:
            return Effect(action, held, int(nearest), Decimal(0))
        whole = shares.to_integral_value(ROUND_FLOOR)
        assert action.close is not None  # noqa: S101 - a split carries its close
        cash = ((shares - whole) * action.close).quantize(CENT, ROUND_FLOOR)
    return Effect(action, held, int(whole), cash)


def dividend_effect(action: AccountAction, held: int) -> Effect:
    if action.currency != EURO:
        return Effect(action, held, held, Decimal(0))
    with localcontext() as ctx:
        ctx.prec = DIGITS
        cash = (held * action.value).quantize(CENT, ROUND_FLOOR)
    return Effect(action, held, held, cash)


def replay_account(actions: Iterable[AccountAction], movements: Sequence[Movement]) -> Replay:
    """The positions and cash of ``movements``, session by session, with ``actions`` applied:
    a session's splits, then its movements in their order, then its dividends. A movement that
    takes a position below zero is an incident."""
    by_session: dict[date, list[Movement]] = defaultdict(list)
    for movement in movements:
        by_session[movement.session].append(movement)
    applying: dict[date, list[AccountAction]] = defaultdict(list)
    for action in sorted(actions, key=lambda a: a.key):
        applying[action.session].append(action)
    positions: dict[str, int] = {}
    cash = Decimal(0)
    effects: list[Effect] = []
    for session in sorted(by_session.keys() | applying.keys()):
        today = applying.get(session, [])
        for action in today:
            if action.kind == "split" and positions.get(action.symbol, 0):
                effect = split_effect(action, positions[action.symbol])
                positions[action.symbol] = effect.shares
                cash += effect.cash
                effects.append(effect)
        entitled = dict(positions)
        for movement in by_session.get(session, []):
            held = positions.get(movement.symbol, 0) + movement.shares
            if held < 0:
                raise ExecutionIncident(
                    "execution_incoherente",
                    None,
                    f"vente de {movement.symbol} au-delà de la position, opérations sur titres "
                    "comprises",
                )
            positions[movement.symbol] = held
            cash += movement.cash
        for action in today:
            if action.kind == "dividend" and entitled.get(action.symbol, 0):
                effect = dividend_effect(action, entitled[action.symbol])
                cash += effect.cash
                effects.append(effect)
    kept = {symbol: quantity for symbol, quantity in sorted(positions.items()) if quantity}
    return Replay(kept, cash, tuple(effects))
