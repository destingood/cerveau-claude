"""The in-house daily backtest engine: the reference of every cross-check (ADR-024, D6).

Each session d of the window, in this order:

1. splits effective at d (first session on or after their ex-date) change the quantities: the
   new quantity is rounded down to a whole share and the fraction is paid in cash at the close
   of d; the orders waiting for d are scaled the same way, toward zero;
2. a dividend entitles the quantity held at the start of its effective session;
3. the orders decided at the previous session are filled at the close of d (``schedule``);
4. a dividend is credited at its effective session if it was announced by the decision cut-off
   of that session, else at the first session whose cut-off follows the announcement (its last
   revision's amount, ADR-024): after the fills, so that it never funds them (B158);
5. the book is valued at the closes of d: V = cash + Σ q·P;
6. except at the last session, the strategy decides at d on its PointInTimeView, and the
   weights become orders sized at the prices known then, split-adjusted with the splits that
   view knows (B157).

Fills and values use each session's last revision (``MarketHistory.final_closes``): what the
market did. Decisions see only their view. Every instrument must trade in EUR on the same
sessions (ADR-024). No tax is modelled and cash earns nothing [Hypothèse].
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time
from typing import Literal

import numpy as np
import pandas as pd

from core.finance.performance import (
    Drawdown,
    annualized,
    calmar,
    chained,
    daily_returns,
    max_drawdown,
    sharpe,
    sortino,
    volatility,
)
from core.finance.research.execution import Costs, Cut, Fill, Order, schedule, target_orders
from core.finance.research.strategy import Params, Strategy, StrategyError, checked_weights
from core.finance.research.view import MarketHistory, PointInTimeView, decision_time

CURRENCY = "EUR"
SPLIT_TOLERANCE = 1e-9  # q·r this close to a whole number is that number, not a fraction


class BacktestError(ValueError):
    """The backtest cannot run on this universe or window (currency, calendar, cash)."""


@dataclass(frozen=True)
class Trade:
    decided: date
    executed: date
    fill: Fill


@dataclass(frozen=True)
class Credit:
    """Cash from a corporate action: a dividend, or the fraction of a share left by a split."""

    instrument_id: str
    kind: Literal["dividend", "cash_in_lieu"]
    ex_date: date
    quantity: int  # the shares entitled (dividend) or split (cash in lieu)
    amount: float
    credited: date | None  # None: announced too late for the window, never paid


@dataclass(frozen=True)
class CutOrder:
    decided: date
    executed: date
    cut: Cut


@dataclass(frozen=True)
class BacktestResult:
    strategy: str
    params: dict[str, int | float | str | bool]
    costs: Costs
    initial_cash: float
    values: pd.Series  # V at each close
    cash: pd.Series
    positions: pd.DataFrame  # shares held at each close, one column per instrument
    exposure: pd.Series  # Σ q·P / V
    trades: tuple[Trade, ...]
    credits: tuple[Credit, ...]
    cuts: tuple[CutOrder, ...]

    @property
    def fees(self) -> float:
        return math.fsum(t.fill.fees for t in self.trades)


@dataclass(frozen=True)
class _Split:
    session: int  # index of its effective session in the window, len(window) if after it
    ex_date: date
    ratio: float


@dataclass
class _Dividend:
    instrument_id: str
    ex_date: date
    session: int
    per_share: float
    payable: int  # index of the session it is credited at, len(window) if never
    quantity: int = 0


def common_calendar(
    history: MarketHistory, start: date, end: date
) -> tuple[list[date], np.ndarray]:
    """The common sessions of [start, end] and the final closes, one column per instrument."""
    if end <= start:
        raise BacktestError("la fenêtre du backtest doit compter au moins deux jours")
    columns: list[pd.Series] = []
    for instrument_id in history.instruments:
        if history.currencies(instrument_id) != {CURRENCY}:
            raise BacktestError(
                f"{instrument_id} : devise {sorted(history.currencies(instrument_id))} ; "
                "seul l'EUR est accepté en phase 3 (ADR-024)"
            )
        closes = history.final_closes(instrument_id)
        window = closes[(closes.index.date >= start) & (closes.index.date <= end)]
        if columns and not window.index.equals(columns[0].index):
            raise BacktestError(
                f"{instrument_id} : séances différentes de {columns[0].name} sur la fenêtre ; "
                "un calendrier commun est exigé (ADR-024)"
            )
        columns.append(window)
    sessions = [stamp.date() for stamp in columns[0].index]
    if len(sessions) < 2:
        raise BacktestError("moins de deux séances dans la fenêtre")
    return sessions, np.column_stack([c.to_numpy() for c in columns])


def known_close(view: PointInTimeView, instrument_id: str) -> float | None:
    """The last close the view knows, in shares of its day; None before the first one.

    A close older than a split effective by then is divided by its ratio, so that target
    quantities are counted in the shares the order will trade (ADR-024). Only the splits the
    view knows count, each in its revision known then: a later announcement or correction
    cannot reach the sizing (B157, R10).
    """
    last = view.last_close(instrument_id)
    if last is None:
        return None
    session, close = last
    return close / math.prod(
        float(action.value)
        for action in view.corporate_actions(instrument_id)
        if action.kind == "split" and session < action.ex_date <= view.day
    )


def known_closes(history: MarketHistory, sessions: Sequence[date], cutoff: time) -> np.ndarray:
    """The close each decision of ``sessions`` sizes its orders with, one column per instrument.

    NaN where no close is known yet. The same ``known_close`` as ``run``: the screening sizes its
    orders exactly as the reference does (ADR-025).
    """
    instruments = history.instruments
    known = np.full((len(sessions), len(instruments)), np.nan)
    for row, day in enumerate(sessions):
        view = history.view(day, cutoff)
        for column, instrument_id in enumerate(instruments):
            close = known_close(view, instrument_id)
            if close is not None:
                known[row, column] = close
    return known


def _effective(sessions: np.ndarray, day: date) -> int:
    """The index of the first session on or after ``day``: when an action takes effect."""
    return int(np.searchsorted(sessions, np.datetime64(day, "D")))


def run(
    strategy: Strategy,
    params: Params,
    history: MarketHistory,
    *,
    start: date,
    end: date,
    cutoff: time,
    costs: Costs,
    initial_cash: float,
) -> BacktestResult:
    """Replay ``strategy`` on [start, end] from ``initial_cash`` euros, with ``costs``.

    LookAheadError and StrategyError propagate: the protocol turns them into a failed verdict.
    """
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise BacktestError("le cash initial doit être positif")
    sessions, closes = common_calendar(history, start, end)
    instruments = history.instruments
    count = len(sessions)
    days = np.array(sessions, dtype="datetime64[D]")
    splits: dict[str, list[_Split]] = {}
    dividends: list[_Dividend] = []
    for instrument_id in instruments:
        splits[instrument_id] = []
        for event in history.events(instrument_id):
            action, at = event.action, _effective(days, event.action.ex_date)
            if action.kind == "split":
                splits[instrument_id].append(_Split(at, action.ex_date, float(action.value)))
            elif at < count and action.ex_date > sessions[0]:
                payable = next(
                    (
                        k
                        for k in range(at, count)
                        if decision_time(sessions[k], cutoff) >= event.announced
                    ),
                    count,
                )
                dividends.append(
                    _Dividend(instrument_id, action.ex_date, at, float(action.value), payable)
                )

    def cents(amount: float) -> float:
        return round(amount, 2) if costs.rounding == "cent" else amount

    cash = float(initial_cash)
    held = dict.fromkeys(instruments, 0)
    pending: list[Order] = []
    trades: list[Trade] = []
    credits: list[Credit] = []
    cuts: list[CutOrder] = []
    values, cash_line, exposure = np.empty(count), np.empty(count), np.empty(count)
    positions = np.zeros((count, len(instruments)), dtype=np.int64)

    for k, day in enumerate(sessions):
        prices = dict(zip(instruments, closes[k].tolist(), strict=True))
        # 1. Splits effective today.
        for column, instrument_id in enumerate(instruments):
            for split in (s for s in splits[instrument_id] if s.session == k and k > 0):
                shares = held[instrument_id] * split.ratio
                whole = round(shares)
                if abs(shares - whole) > SPLIT_TOLERANCE:
                    whole = math.floor(shares)
                    amount = cents((shares - whole) * float(closes[k, column]))
                    cash += amount
                    credits.append(
                        Credit(
                            instrument_id,
                            "cash_in_lieu",
                            split.ex_date,
                            held[instrument_id],
                            amount,
                            day,
                        )
                    )
                held[instrument_id] = int(whole)
                pending = [
                    Order(o.instrument_id, math.trunc(o.quantity * split.ratio), o.gap)
                    if o.instrument_id == instrument_id
                    else o
                    for o in pending
                ]
                pending = [o for o in pending if o.quantity]
        # 2. Dividends: entitlement at the start of the effective session.
        for dividend in dividends:
            if dividend.session == k:
                dividend.quantity = held[dividend.instrument_id]
        # 3. Yesterday's orders, filled at today's close.
        if pending:
            done = schedule(pending, cash, prices, costs)
            cash = done.cash
            for fill in done.fills:
                held[fill.instrument_id] += fill.quantity
                trades.append(Trade(sessions[k - 1], day, fill))
            cuts.extend(CutOrder(sessions[k - 1], day, cut) for cut in done.cuts)
            pending = []
        # 4. Dividends due today, after the fills: they never fund them (B158).
        for dividend in dividends:
            if dividend.payable == k and dividend.quantity:
                amount = cents(dividend.quantity * dividend.per_share)
                cash += amount
                credits.append(
                    Credit(
                        dividend.instrument_id,
                        "dividend",
                        dividend.ex_date,
                        dividend.quantity,
                        amount,
                        day,
                    )
                )
        # 5. The book at today's close.
        invested = math.fsum(held[i] * prices[i] for i in instruments)
        values[k], cash_line[k] = cash + invested, cash
        exposure[k] = invested / values[k]
        positions[k] = [held[i] for i in instruments]
        # 6. Today's decision, filled tomorrow.
        if k < count - 1:
            view = history.view(day, cutoff)
            weights = checked_weights(strategy.decide(view, params), instruments, day)
            known: dict[str, float] = {}
            for instrument_id in instruments:
                if not weights.get(instrument_id) and not held[instrument_id]:
                    continue
                close = known_close(view, instrument_id)
                if close is None:
                    raise StrategyError(
                        f"décision du {day} : poids sur {instrument_id} sans aucun cours connu"
                    )
                known[instrument_id] = close
            value = cash + math.fsum(held[i] * known[i] for i in known)
            pending = target_orders(weights, held, known, value)

    for dividend in dividends:
        if dividend.payable >= count and dividend.quantity:
            amount = cents(dividend.quantity * dividend.per_share)
            credits.append(
                Credit(
                    dividend.instrument_id,
                    "dividend",
                    dividend.ex_date,
                    dividend.quantity,
                    amount,
                    None,
                )
            )

    index = pd.DatetimeIndex(days)
    return BacktestResult(
        strategy=strategy.name,
        params=dict(params),
        costs=costs,
        initial_cash=float(initial_cash),
        values=pd.Series(values, index=index, name="valeur"),
        cash=pd.Series(cash_line, index=index, name="liquidites"),
        positions=pd.DataFrame(positions, index=index, columns=list(instruments)),
        exposure=pd.Series(exposure, index=index, name="exposition"),
        trades=tuple(trades),
        credits=tuple(credits),
        cuts=tuple(cuts),
    )


@dataclass(frozen=True)
class BacktestMeasures:
    """The ADR-020 measures of a backtest, plus turnover, trades, fees and exposure."""

    sessions: int  # daily returns measured
    total_return: float
    annual_return: float  # ACT/365
    volatility: float
    sharpe: float | None
    sortino: float | None
    drawdown: Drawdown
    calmar: float | None
    turnover: float  # annualised: Σ traded / (2 × mean V) × sessions_per_year / sessions
    trades: int
    fees: float
    mean_exposure: float


def measures(
    result: BacktestResult,
    sessions_per_year: int,
    risk_free: Sequence[float] | None = None,
) -> BacktestMeasures:
    """Measures of the daily returns V_d / V_{d−1} − 1; a zero risk-free rate when none is given.

    Synthetic data have no €STR: their Sharpe and Sortino use a zero rate [Hypothèse].
    """
    values = result.values.tolist()
    if len(values) < 3:
        raise ValueError("au moins trois séances pour mesurer un backtest")
    days = [stamp.date() for stamp in result.values.index]
    returns = daily_returns(values, [0.0] * (len(values) - 1))
    if risk_free is not None and len(risk_free) != len(returns):
        raise ValueError("un taux sans risque par rendement quotidien attendu")
    excess = (
        returns if risk_free is None else [r - f for r, f in zip(returns, risk_free, strict=True)]
    )
    total = chained(returns)
    annual = annualized(total, (days[-1] - days[0]).days)
    drawdown = max_drawdown(days, returns)
    traded = math.fsum(t.fill.amount for t in result.trades)
    mean_value = math.fsum(values) / len(values)
    return BacktestMeasures(
        sessions=len(returns),
        total_return=total,
        annual_return=annual,
        volatility=volatility(returns, sessions_per_year),
        sharpe=sharpe(excess, sessions_per_year),
        sortino=sortino(excess, sessions_per_year),
        drawdown=drawdown,
        calmar=calmar(annual, drawdown.depth),
        turnover=traded / (2 * mean_value) * sessions_per_year / len(returns),
        trades=len(result.trades),
        fees=result.fees,
        mean_exposure=float(result.exposure.mean()),
    )
