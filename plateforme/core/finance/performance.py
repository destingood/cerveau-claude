"""Performance measures and the daily history of the book (plan of phase 2, F9; ADR-020).

The book is replayed and valued at the end of each valuation day: the TARGET business days of
the period, with its first day as the base and its last day as the end. Closes, ECB rates and
the €STR are those known at ``as_of``, read once and cut at each day exactly as
:func:`core.finance.portfolio.value` does. Deposits and withdrawals are the only external flows,
counted at the end of their day; dividends, fees and conversions stay inside the return.

Each day's profit is split by line with every transaction measured in euros at the ECB rate of
its trade date: what leaves a line enters another at the same value, so the parts add up to the
day's profit. The measures (TWR, MWR, volatility, Sharpe, Sortino, drawdown, Calmar) are plain
functions of the daily returns, written here (D14) and checked in the tests against independent
formulas and skfolio. Nothing here reaches the network or calls a model (R1).
"""

from __future__ import annotations

import bisect
import itertools
import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
from scipy.optimize import brentq

from core.finance.calendars import is_target_day
from core.finance.model import local_date
from core.finance.portfolio import (
    EUR,
    Booked,
    PortfolioError,
    Valuation,
    effective_ledger,
    held_instruments,
    known_splits,
    replay,
    valuation,
)
from core.finance.store import FinanceStore
from core.finance.views import ViewError

CASH = "liquidites"  # the line of a cash balance: liquidites-EUR (as risk_report)
FEES = "frais"  # custody and account fees: a line of their own
DAYS_PER_YEAR = 365  # ACT/365: annualized returns and the time of an MWR flow
ESTR_DAY_COUNT = 360  # ACT/360, the €STR convention
LOG_BOUND = 30.0  # the period MWR is searched in ]e^-30 - 1, e^30 - 1[


def cash_line(currency: str) -> str:
    return f"{CASH}-{currency}"


# Valuation days ---------------------------------------------------------------------------------


def valuation_days(start: date, end: date) -> list[date]:
    """``start`` (the base), the TARGET days after it, and ``end`` in place of the last one.

    An ``end`` outside TARGET replaces the last TARGET day before it, so that a weekend never
    adds a return of zero: the last interval runs to ``end``.
    """
    if end <= start:
        raise ValueError("la fin de la période doit suivre son début")
    days = [start]
    current = start + timedelta(days=1)
    while current <= end:
        if is_target_day(current):
            days.append(current)
        current += timedelta(days=1)
    if days[-1] != end:
        if len(days) > 1:
            days[-1] = end
        else:
            days.append(end)
    return days


# History ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Interval:
    """From the end of the previous valuation day to the end of ``day``."""

    day: date
    value_eur: float  # end of day, cash included
    flow_eur: float  # deposits minus withdrawals of the interval
    pnl: dict[str, float]  # profit by line; the parts add up to the profit of the interval
    income: dict[str, float]  # dividends net of withholding, by security

    def profit(self, previous: float) -> float:
        return self.value_eur - previous - self.flow_eur


@dataclass(frozen=True)
class History:
    as_of: datetime
    start: date
    end: date
    base_eur: float  # value at the end of ``start``
    intervals: list[Interval]
    currencies: dict[str, str]  # line -> currency
    warnings: list[str]

    @property
    def days(self) -> list[date]:
        return [self.start, *(i.day for i in self.intervals)]

    @property
    def values(self) -> list[float]:
        return [self.base_eur, *(i.value_eur for i in self.intervals)]

    @property
    def flows(self) -> list[float]:
        return [i.flow_eur for i in self.intervals]

    @property
    def returns(self) -> list[float]:
        return daily_returns(self.values, self.flows)


def _up_to(series: pd.Series, day: date) -> pd.Series:
    return series.loc[: pd.Timestamp(day)]


def _rate_on(series: pd.Series | None, day: date) -> float | None:
    """Units of the currency per euro: the last ECB rate known on ``day`` (1 for the euro)."""
    if series is None:
        return 1.0
    known = _up_to(series, day)
    return None if known.empty else float(known.iloc[-1])


def _line_values(found: Valuation) -> dict[str, float]:
    """The value of each line, all accounts together; cash by currency."""
    parts: defaultdict[str, list[float]] = defaultdict(list)
    for line in found.lines:
        key = line.asset if line.nature == "security" else cash_line(line.currency)
        parts[key].append(line.value_eur or 0.0)
    return {key: math.fsum(values) for key, values in parts.items()}


class _Interval:
    """The transactions of one interval, in euros at the rate of their trade date."""

    def __init__(self) -> None:
        self.inflow: defaultdict[str, float] = defaultdict(float)
        self.income: defaultdict[str, float] = defaultdict(float)
        self.fees = 0.0
        self.flow = 0.0

    def book(self, booked: Booked, rate: float) -> None:
        t = booked.transaction
        eur = float(t.cash_flow) / rate
        self.inflow[cash_line(t.currency)] += eur
        match t.kind:
            case "buy" | "sell":
                assert t.asset is not None  # noqa: S101 - required by the model
                self.inflow[t.asset] -= eur
            case "fx":
                assert t.asset is not None  # noqa: S101 - the currency bought, required
                self.inflow[cash_line(t.asset)] -= eur  # at the value of the euros paid
            case "dividend":
                assert t.asset is not None  # noqa: S101 - required by the model
                self.income[t.asset] += eur
            case "fee":
                self.fees += eur
            case "deposit" | "withdrawal":
                self.flow += eur

    def close(
        self, day: date, total: float, before: dict[str, float], after: dict[str, float]
    ) -> Interval:
        keys = sorted(set(before) | set(after) | set(self.inflow) | set(self.income))
        pnl = {
            key: after.get(key, 0.0)
            - before.get(key, 0.0)
            - self.inflow.get(key, 0.0)
            + self.income.get(key, 0.0)
            for key in keys
        }
        if self.fees:
            pnl[FEES] = self.fees
        return Interval(day, total, self.flow, pnl, dict(self.income))


def history(
    store: FinanceStore,
    *,
    as_of: datetime,
    start: date | None = None,
    end: date | None = None,
    strict: bool = False,
) -> History:
    """The book valued at each valuation day of [start, end], as known at ``as_of``.

    ``start`` defaults to the first trade date, ``end`` to the Paris date of ``as_of``.
    """
    today = local_date(as_of)
    end = end or today
    if end > today:
        raise ViewError(f"fin de période après la date de lecture ({today:%d/%m/%Y}) (R10)")
    ledger = [
        b
        for b in effective_ledger(store, as_of=as_of, strict=strict)
        if b.transaction.trade_date <= end
    ]
    if not ledger:
        raise ViewError("aucune transaction connue à cette date : pas de performance")
    first = ledger[0].transaction.trade_date
    start = start or first
    if start >= end:
        raise ViewError("le début de la période doit précéder sa fin")
    splits = known_splits(store, ledger, as_of=as_of, strict=strict)
    closes = {
        i: store.closes(i, as_of=as_of, end=end, strict=strict) for i in held_instruments(ledger)
    }
    currencies = {b.transaction.currency for b in ledger} | {
        b.transaction.asset
        for b in ledger
        if b.transaction.kind == "fx" and b.transaction.asset is not None
    }
    rates = {
        c: store.fx_rates(c, as_of=as_of, end=end, strict=strict)
        for c in sorted(currencies - {EUR})
    }
    trade_days = [b.transaction.trade_date for b in ledger]

    def valued(day: date) -> tuple[dict[str, float], float, list[str]]:
        prefix = ledger[: bisect.bisect_right(trade_days, day)]
        try:
            book = replay(prefix, splits, day=day, as_of=as_of)
        except PortfolioError as exc:
            raise ViewError(str(exc)) from None
        found = valuation(
            book,
            lambda instrument_id: _up_to(closes[instrument_id], day),
            lambda currency: _up_to(rates[currency], day),
        )
        total = found.total_eur
        if total is None:
            raise ViewError(
                f"{', '.join(found.missing)} : valeur inconnue le {day:%d/%m/%Y} ; pas de "
                "performance partielle (R12)"
            )
        return _line_values(found), total, book.warnings

    days = valuation_days(start, end)
    before, base, warnings = valued(start)
    if base <= 0:
        raise ViewError(
            f"aucun avoir à la fin du {start:%d/%m/%Y} : la période commence au plus tôt le "
            f"{first:%d/%m/%Y}"
        )
    intervals: list[Interval] = []
    for previous, day in itertools.pairwise(days):
        if intervals and intervals[-1].value_eur <= 0:
            raise ViewError(
                f"valeur nulle ou négative à la fin du {previous:%d/%m/%Y} : pas de rendement "
                "ensuite"
            )
        after, total, warnings = valued(day)
        moves = _Interval()
        low = bisect.bisect_right(trade_days, previous)
        for booked in ledger[low : bisect.bisect_right(trade_days, day)]:
            t = booked.transaction
            rate = _rate_on(rates.get(t.currency) if t.currency != EUR else None, t.trade_date)
            if rate is None:
                raise ViewError(
                    f"{booked.where} : aucun taux BCE {t.currency} connu le "
                    f"{t.trade_date:%d/%m/%Y} (R12)"
                )
            moves.book(booked, rate)
        intervals.append(moves.close(day, total, before, after))
        before = after
    line_currency = {
        b.transaction.asset: b.transaction.currency
        for b in ledger
        if b.transaction.kind in ("buy", "sell") and b.transaction.asset is not None
    }
    for interval in intervals:
        for key in interval.pnl:
            if key.startswith(f"{CASH}-"):
                line_currency[key] = key.removeprefix(f"{CASH}-")
    return History(
        as_of, start, end, base, intervals, dict(sorted(line_currency.items())), warnings
    )


# Measures ---------------------------------------------------------------------------------------


def daily_returns(values: Sequence[float], flows: Sequence[float]) -> list[float]:
    """r_t = (V_t − V_{t−1} − F_t) / V_{t−1}: flows at the end of their day."""
    if len(values) != len(flows) + 1:
        raise ValueError("une valeur de plus que de flux attendue")
    returns = []
    for (previous, current), flow in zip(itertools.pairwise(values), flows, strict=True):
        if previous <= 0:
            raise ValueError("valeur nulle ou négative : rendement non défini")
        returns.append((current - previous - flow) / previous)
    return returns


def chained(returns: Sequence[float]) -> float:
    """Π(1 + r) − 1, summed in logarithms so that small returns keep their digits."""
    return math.expm1(math.fsum(math.log1p(r) for r in returns))


def annualized(period_return: float, calendar_days: int) -> float:
    """(1 + R)^(365 / days) − 1 (ACT/365)."""
    return math.expm1(math.log1p(period_return) * DAYS_PER_YEAR / calendar_days)


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def sample_std(values: Sequence[float]) -> float:
    m = _mean(values)
    return math.sqrt(math.fsum((v - m) ** 2 for v in values) / (len(values) - 1))


def downside_deviation(values: Sequence[float]) -> float:
    """√(Σ min(x, 0)² / (n − 1)): skfolio's semi-deviation with a target of zero."""
    return math.sqrt(math.fsum(min(v, 0.0) ** 2 for v in values) / (len(values) - 1))


def volatility(returns: Sequence[float], sessions: int) -> float:
    return sample_std(returns) * math.sqrt(sessions)


def sharpe(excess: Sequence[float], sessions: int) -> float | None:
    """Mean over standard deviation of the excess returns, × √sessions; None without spread."""
    spread = sample_std(excess)
    return None if spread == 0 else _mean(excess) / spread * math.sqrt(sessions)


def sortino(excess: Sequence[float], sessions: int) -> float | None:
    """Mean excess over its downside deviation, × √sessions; None without a loss."""
    downside = downside_deviation(excess)
    return None if downside == 0 else _mean(excess) / downside * math.sqrt(sessions)


@dataclass(frozen=True)
class Drawdown:
    depth: float  # positive: 0.12 for a fall of 12 % from the peak
    peak: date
    trough: date
    recovery: date | None  # the first day back at the peak, None if not yet


def max_drawdown(days: Sequence[date], returns: Sequence[float]) -> Drawdown:
    """The deepest fall of the TWR index from its running peak (the base counts as a peak)."""
    if len(days) != len(returns) + 1:
        raise ValueError("un jour de plus que de rendements attendu")
    log_index = 0.0
    peak_log, peak_day = 0.0, days[0]
    worst = Drawdown(0.0, days[0], days[0], days[0])
    worst_peak_log = 0.0
    recovery_open = False
    for day, r in zip(days[1:], returns, strict=True):
        log_index += math.log1p(r)
        if log_index >= peak_log:
            if recovery_open and worst.recovery is None and log_index >= worst_peak_log:
                worst = Drawdown(worst.depth, worst.peak, worst.trough, day)
                recovery_open = False
            peak_log, peak_day = log_index, day
            continue
        depth = -math.expm1(log_index - peak_log)
        if depth > worst.depth:
            worst = Drawdown(depth, peak_day, day, None)
            worst_peak_log = peak_log
            recovery_open = True
    return worst


def calmar(annual_return: float, drawdown: float) -> float | None:
    return None if drawdown <= 0 else annual_return / drawdown


def mwr(
    start: date, base: float, flows: Sequence[tuple[date, float]], end: date, final: float
) -> float | None:
    """Money-weighted return over the period: e^y − 1 where y solves the NPV.

    NPV(y) = −base − Σ F_k·e^(−y·τ_k) + final·e^(−y), τ_k the time of flow k as a share of
    the period (ACT/365 on both sides cancels). The root is searched by Brent's method in
    [−30, 30]; None when the NPV does not change sign there.
    """
    span = (end - start).days
    if span <= 0:
        raise ValueError("la fin de la période doit suivre son début")
    times = [((day - start).days / span, flow) for day, flow in flows if flow]

    def npv(y: float) -> float:
        return math.fsum(
            [-base, *(-f * math.exp(-y * tau) for tau, f in times), final * math.exp(-y)]
        )

    if npv(-LOG_BOUND) * npv(LOG_BOUND) > 0:
        return None
    return math.expm1(float(brentq(npv, -LOG_BOUND, LOG_BOUND, xtol=1e-14)))


def annualized_mwr(period_mwr: float, calendar_days: int) -> float:
    return annualized(period_mwr, calendar_days)


# The risk-free rate -----------------------------------------------------------------------------


def _target_on_or_before(day: date) -> date:
    while not is_target_day(day):
        day -= timedelta(days=1)
    return day


@dataclass(frozen=True)
class RiskFree:
    returns: list[float]  # earned over each interval
    carried: list[date]  # calendar days earning a fixing published later than ``as_of``


def risk_free_returns(days: Sequence[date], fixings: pd.Series) -> RiskFree | None:
    """The €STR earned over each interval, compounded the way the ECB compounds it.

    Each calendar day earns the fixing of the last TARGET day on or before it, simple interest
    over the days a fixing covers (ACT/360), compounded from one fixing to the next. A fixing not
    yet published (the €STR of a day comes out the next TARGET day) is replaced by the last one
    known, and the days concerned are listed. None when no fixing precedes the period.
    """
    known = {stamp.date(): float(v) for stamp, v in fixings.items()}
    published = sorted(known)
    if not published or published[0] > _target_on_or_before(days[0]):
        return None
    returns: list[float] = []
    carried: list[date] = []
    for previous, day in itertools.pairwise(days):
        log_factor = 0.0
        current = previous
        while current < day:
            applicable = _target_on_or_before(current)
            fixing_day = published[bisect.bisect_right(published, applicable) - 1]
            covered = current + timedelta(days=1)
            while covered < day and not is_target_day(covered):
                covered += timedelta(days=1)
            if fixing_day != applicable:
                carried.extend(current + timedelta(days=k) for k in range((covered - current).days))
            n = (covered - current).days
            log_factor += math.log1p(known[fixing_day] / 100 * n / ESTR_DAY_COUNT)
            current = covered
        returns.append(math.expm1(log_factor))
    return RiskFree(returns, carried)


# Attribution ------------------------------------------------------------------------------------


def contributions(found: History) -> dict[str, float]:
    """Σ_t I_{t−1} · pnl_{i,t} / V_{t−1} for each line, I the TWR index (1 at the base).

    Each day's contribution is counted per euro of the base, grown by the return so far: the
    lines add up to the TWR itself, Σ_t (I_t − I_{t−1}) = I_T − 1, up to rounding.
    """
    sums: defaultdict[str, list[float]] = defaultdict(list)
    log_index = 0.0
    for previous, interval in zip(found.values, found.intervals, strict=False):
        index = math.exp(log_index)
        for key, pnl in interval.pnl.items():
            sums[key].append(index * pnl / previous)
        log_index += math.log1p(interval.profit(previous) / previous)
    return {key: math.fsum(parts) for key, parts in sorted(sums.items())}


def totals_by(found: History, read: Callable[[Interval], dict[str, float]]) -> dict[str, float]:
    sums: defaultdict[str, list[float]] = defaultdict(list)
    for interval in found.intervals:
        for key, amount in read(interval).items():
            sums[key].append(amount)
    return {key: math.fsum(parts) for key, parts in sorted(sums.items())}
