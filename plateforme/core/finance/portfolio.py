"""The user's portfolio rebuilt from his transactions, valued in euros and reconciled (ADR-018).

Every imported file is kept. The ledger that stands is recomputed at each read: files apply in
import order, and each one replaces, account by account, what earlier imports said about its
period (first to last day it holds for that account). Replaying that ledger gives positions,
weighted average costs, realized gains and cash, all as exact decimals; floats only appear when
a position is valued (close × rate). Reconciliation compares a broker's statement with the
positions on its date, with exact equality, and its status is recomputed at each read.

Nothing here reaches the network or calls a model: the numbers come from the files and the
finance store (R1), and the journal never receives an amount or a label.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from core.finance.brokers import FORMATS, read_statement
from core.finance.model import PARIS, StatementLine, Transaction, end_of_day, local_date
from core.finance.store import FinanceStore, PortfolioFile
from core.finance.sync import reference

if TYPE_CHECKING:
    import pandas as pd

ZERO = Decimal(0)
EUR = "EUR"
Status = Literal["ok", "ecart", "non_rapproche"]
Nature = Literal["security", "cash"]
SeriesLookup = Callable[[str], "pd.Series"]
GAP_ALERT = "rapprochement: ecart"
# Enough for the product of two file numbers (25 digits each) to be exact: sums and products
# stay exact, and only the share of a cost basis a sale removes is rounded, at 60 digits.
DECIMAL_DIGITS = 60


class PortfolioError(Exception):
    """A ledger that cannot be replayed (a sale above the position): the file is refused."""


@dataclass(frozen=True)
class Booked:
    """A transaction of the ledger, with the file and the line it comes from."""

    transaction: Transaction
    file: PortfolioFile
    line: int

    @property
    def known_at(self) -> datetime:
        """At the end of its day in Paris, or at its import if that came first (R10)."""
        return min(end_of_day(self.transaction.trade_date, PARIS), self.file.imported_at)

    @property
    def where(self) -> str:
        return f"{self.file.file_name}, ligne {self.line}"


@dataclass(frozen=True, order=True)
class Split:
    ex_date: date
    instrument_id: str
    ratio: Decimal  # new shares per old share


@dataclass(frozen=True)
class Holding:
    account: str
    instrument_id: str
    currency: str
    quantity: Decimal
    cost: Decimal  # weighted average cost basis, fees included, in ``currency``

    @property
    def average_price(self) -> Decimal:
        return self.cost / self.quantity


@dataclass(frozen=True)
class RealizedGain:
    account: str
    instrument_id: str
    trade_date: date
    currency: str
    quantity: Decimal
    price: Decimal  # unit sale price, before fees
    fees: Decimal
    proceeds: Decimal  # net of fees
    cost: Decimal  # the share of the cost basis the sale removed
    where: str

    @property
    def gain(self) -> Decimal:
        return self.proceeds - self.cost


@dataclass(frozen=True)
class Book:
    """The positions at the end of ``day``, as known at ``as_of``."""

    day: date
    as_of: datetime
    holdings: list[Holding]
    cash: dict[tuple[str, str], Decimal]  # (account, currency) -> balance
    realized: list[RealizedGain]
    splits: list[Split]
    warnings: list[str]

    @property
    def accounts(self) -> list[str]:
        return sorted({h.account for h in self.holdings} | {a for a, _ in self.cash})


@dataclass
class _Lot:
    currency: str
    quantity: Decimal = ZERO
    cost: Decimal = ZERO


# The ledger ------------------------------------------------------------------------------------


def effective_ledger(
    store: FinanceStore, *, as_of: datetime | None = None, strict: bool = False
) -> list[Booked]:
    """The transactions that stand, in trade order; ``as_of``: only those known by then.

    Strict mode also leaves out the files imported after ``as_of``. Within an account and a
    day, every transaction comes from one file, so the stable sort keeps its line order.
    """
    ledger: list[Booked] = []
    for file in store.portfolio_files("transactions", imported_by=as_of if strict else None):
        rows = store.transactions(file.sha256)
        spans: dict[str, tuple[date, date]] = {}
        for _, t in rows:
            first, last = spans.get(t.account, (t.trade_date, t.trade_date))
            spans[t.account] = (min(first, t.trade_date), max(last, t.trade_date))
        ledger = [b for b in ledger if not _covered(b.transaction, spans)]
        ledger.extend(Booked(t, file, line) for line, t in rows)
    if as_of is not None:
        ledger = [b for b in ledger if b.known_at <= as_of]
    return sorted(ledger, key=lambda b: b.transaction.trade_date)


def _covered(transaction: Transaction, spans: dict[str, tuple[date, date]]) -> bool:
    span = spans.get(transaction.account)
    return span is not None and span[0] <= transaction.trade_date <= span[1]


def _ratio(value: float) -> Decimal:
    # The store keeps a split ratio as a float; its shortest text is the ratio as written.
    return Decimal(int(value)) if value.is_integer() else Decimal(repr(value))


def replay(
    ledger: Sequence[Booked], splits: Iterable[Split], *, day: date, as_of: datetime
) -> Book:
    """Apply the ledger in order; a split applies at the start of its ex-date (ADR-018)."""
    with localcontext(prec=DECIMAL_DIGITS):
        return _replay(ledger, splits, day=day, as_of=as_of)


def _replay(
    ledger: Sequence[Booked], splits: Iterable[Split], *, day: date, as_of: datetime
) -> Book:
    lots: dict[tuple[str, str], _Lot] = {}
    cash: dict[tuple[str, str], Decimal] = {}
    realized: list[RealizedGain] = []
    negative: dict[tuple[str, str], date] = {}
    applied = sorted(s for s in splits if s.ex_date <= day)
    pending = list(reversed(applied))

    def split_until(moment: date) -> None:
        while pending and pending[-1].ex_date <= moment:
            split = pending.pop()
            for (_, instrument_id), lot in lots.items():
                if instrument_id == split.instrument_id:
                    lot.quantity *= split.ratio

    for booked in ledger:
        t = booked.transaction
        if t.trade_date > day:
            raise PortfolioError(f"{booked.where} : opération après le {day:%d/%m/%Y}")
        split_until(t.trade_date)
        if t.kind in ("buy", "sell"):
            assert t.asset is not None  # noqa: S101 - required by the model for these kinds
            lot = lots.setdefault((t.account, t.asset), _Lot(t.currency))
            if lot.currency != t.currency:
                raise PortfolioError(
                    f"{booked.where} : {t.asset} est tenu dans une autre devise sur le compte "
                    f"{t.account}"
                )
            if t.kind == "buy":
                lot.quantity += t.quantity
                lot.cost -= t.cash_flow
            else:
                realized.append(_sell(booked, lot))
        elif t.kind == "fx":
            assert t.asset is not None  # noqa: S101 - the currency bought, required
            target = (t.account, t.asset)
            cash[target] = cash.get(target, ZERO) + t.quantity
        key = (t.account, t.currency)
        cash[key] = cash.get(key, ZERO) + t.cash_flow
        if cash[key] < 0 and key not in negative:
            negative[key] = t.trade_date
    split_until(day)
    holdings = [
        Holding(account, instrument_id, lot.currency, lot.quantity, lot.cost)
        for (account, instrument_id), lot in sorted(lots.items())
        if lot.quantity
    ]
    warnings = [
        f"cash négatif sur le compte {account} en {currency} (première fois le {first:%d/%m/%Y})"
        for (account, currency), first in sorted(negative.items())
    ]
    return Book(day, as_of, holdings, dict(sorted(cash.items())), realized, applied, warnings)


def _sell(booked: Booked, lot: _Lot) -> RealizedGain:
    t = booked.transaction
    assert t.asset is not None and t.price is not None  # noqa: S101 - required for a sale
    if t.quantity > lot.quantity:
        raise PortfolioError(
            f"{booked.where} : vente supérieure à la position détenue ({t.asset}, compte "
            f"{t.account})"
        )
    removed = lot.cost if t.quantity == lot.quantity else lot.cost * t.quantity / lot.quantity
    lot.quantity -= t.quantity
    lot.cost -= removed
    return RealizedGain(
        account=t.account,
        instrument_id=t.asset,
        trade_date=t.trade_date,
        currency=t.currency,
        quantity=t.quantity,
        price=t.price,
        fees=t.fees,
        proceeds=t.cash_flow,
        cost=removed,
        where=booked.where,
    )


def build_book(
    store: FinanceStore, *, as_of: datetime, strict: bool = False, day: date | None = None
) -> Book:
    """The positions at the end of ``day`` (default: the Paris date of ``as_of``)."""
    day = day or local_date(as_of)
    ledger = [
        b
        for b in effective_ledger(store, as_of=as_of, strict=strict)
        if b.transaction.trade_date <= day
    ]
    return replay(
        ledger, known_splits(store, ledger, as_of=as_of, strict=strict), day=day, as_of=as_of
    )


def held_instruments(ledger: Iterable[Booked]) -> list[str]:
    """The instruments the ledger buys or sells, sorted."""
    return sorted(
        {
            b.transaction.asset
            for b in ledger
            if b.transaction.kind in ("buy", "sell") and b.transaction.asset is not None
        }
    )


def known_splits(
    store: FinanceStore, ledger: Iterable[Booked], *, as_of: datetime, strict: bool
) -> list[Split]:
    """The splits known at ``as_of`` of the instruments the ledger trades."""
    return [
        Split(action.ex_date, action.instrument_id, _ratio(action.value))
        for instrument_id in held_instruments(ledger)
        for action in store.corporate_actions(instrument_id, as_of=as_of, strict=strict)
        if action.kind == "split"
    ]


# Valuation -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ValuedLine:
    """A position or a cash balance; ``value_eur`` is None when a close or a rate is missing."""

    account: str
    nature: Nature
    asset: str  # the instrument, or the currency of the balance
    currency: str
    quantity: Decimal
    cost: Decimal | None = None
    close: float | None = None  # on the basis of the quantity held (splits since applied)
    close_date: date | None = None
    fx_rate: float | None = None  # units of ``currency`` per euro, ECB reference rate
    fx_date: date | None = None
    value_eur: float | None = None


@dataclass(frozen=True)
class Valuation:
    day: date
    as_of: datetime
    lines: list[ValuedLine]

    @property
    def missing(self) -> list[str]:
        return sorted({line.asset for line in self.lines if line.value_eur is None})

    @property
    def total_eur(self) -> float | None:
        """Absent rather than partial when one value is missing (R12)."""
        values = [line.value_eur for line in self.lines]
        if any(v is None for v in values):
            return None
        return math.fsum(v for v in values if v is not None)


def value(store: FinanceStore, book: Book, *, strict: bool = False) -> Valuation:
    """Last close and last ECB rate published by ``book.as_of``, up to ``book.day``."""
    return valuation(
        book,
        lambda instrument_id: store.closes(
            instrument_id, as_of=book.as_of, end=book.day, strict=strict
        ),
        lambda currency: store.fx_rates(currency, as_of=book.as_of, end=book.day, strict=strict),
    )


def valuation(book: Book, closes_of: SeriesLookup, rates_of: SeriesLookup) -> Valuation:
    """:func:`value` on given series: raw closes and ECB rates, none after ``book.day``."""
    rates: dict[str, tuple[float | None, date | None]] = {}

    def rate(currency: str) -> tuple[float | None, date | None]:
        if currency == EUR:
            return 1.0, None
        if currency not in rates:
            series = rates_of(currency)
            known = not series.empty
            rates[currency] = (
                (float(series.iloc[-1]), series.index[-1].date()) if known else (None, None)
            )
        return rates[currency]

    lines: list[ValuedLine] = []
    for h in book.holdings:
        closes = closes_of(h.instrument_id)
        fx_rate, fx_date = rate(h.currency)
        close = close_date = amount = None
        if not closes.empty:
            close_date = closes.index[-1].date()
            # A raw close older than a split brought to the basis of the quantity held.
            factor = math.prod(
                float(s.ratio)
                for s in book.splits
                if s.instrument_id == h.instrument_id and close_date < s.ex_date
            )
            close = float(closes.iloc[-1]) / factor
            if fx_rate is not None:
                amount = float(h.quantity) * close / fx_rate
        lines.append(
            ValuedLine(
                h.account,
                "security",
                h.instrument_id,
                h.currency,
                h.quantity,
                cost=h.cost,
                close=close,
                close_date=close_date,
                fx_rate=fx_rate,
                fx_date=fx_date,
                value_eur=amount,
            )
        )
    for (account, currency), balance in book.cash.items():
        if not balance:
            continue
        fx_rate, fx_date = rate(currency)
        amount = None if fx_rate is None else float(balance) / fx_rate
        lines.append(
            ValuedLine(
                account,
                "cash",
                currency,
                currency,
                balance,
                fx_rate=fx_rate,
                fx_date=fx_date,
                value_eur=amount,
            )
        )
    return Valuation(book.day, book.as_of, lines)


# Reconciliation --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Gap:
    account: str
    nature: Nature
    asset: str
    statement: Decimal
    computed: Decimal


@dataclass(frozen=True)
class AccountReconciliation:
    account: str
    status: Status
    statement_date: date | None = None
    statement_file: str | None = None
    gaps: tuple[Gap, ...] = ()


def compare(lines: Sequence[StatementLine], book: Book) -> dict[str, list[Gap]]:
    """The gaps of each account of the statement; a position it leaves out is zero."""
    accounts = sorted({line.account for line in lines})
    stated: dict[tuple[str, Nature, str], Decimal] = {
        (line.account, line.nature, line.asset): line.quantity for line in lines
    }
    computed: dict[tuple[str, Nature, str], Decimal] = {
        (h.account, "security", h.instrument_id): h.quantity
        for h in book.holdings
        if h.account in accounts
    }
    computed |= {
        (account, "cash", currency): balance
        for (account, currency), balance in book.cash.items()
        if account in accounts and balance
    }
    gaps: dict[str, list[Gap]] = {account: [] for account in accounts}
    for key in sorted(stated.keys() | computed.keys()):
        account, nature, asset = key
        stated_quantity, computed_quantity = stated.get(key, ZERO), computed.get(key, ZERO)
        if stated_quantity != computed_quantity:
            gaps[account].append(Gap(account, nature, asset, stated_quantity, computed_quantity))
    return gaps


def _statements(
    store: FinanceStore, *, as_of: datetime, strict: bool
) -> list[tuple[PortfolioFile, list[StatementLine]]]:
    """The statements known at ``as_of``, in import order."""
    known: list[tuple[PortfolioFile, list[StatementLine]]] = []
    for file in store.portfolio_files("statement", imported_by=as_of if strict else None):
        lines = [line for _, line in store.statement(file.sha256)]
        day = lines[0].statement_date
        if min(end_of_day(day, PARIS), file.imported_at) <= as_of:
            known.append((file, lines))
    return known


def reconciliation_status(
    store: FinanceStore, *, as_of: datetime, strict: bool = False
) -> list[AccountReconciliation]:
    """Each account against its latest statement known at ``as_of``, recomputed now."""
    latest: dict[str, tuple[date, PortfolioFile, list[StatementLine]]] = {}
    for file, lines in _statements(store, as_of=as_of, strict=strict):
        day = lines[0].statement_date
        for account in {line.account for line in lines}:
            # A later import of a statement on the same date replaces the earlier one.
            if account not in latest or day >= latest[account][0]:
                latest[account] = (day, file, [line for line in lines if line.account == account])
    ledger = effective_ledger(store, as_of=as_of, strict=strict)
    accounts = sorted({b.transaction.account for b in ledger} | latest.keys())
    books: dict[date, Book] = {}
    result: list[AccountReconciliation] = []
    for account in accounts:
        if account not in latest:
            result.append(AccountReconciliation(account, "non_rapproche"))
            continue
        day, file, lines = latest[account]
        if day not in books:
            books[day] = build_book(store, as_of=as_of, strict=strict, day=day)
        gaps = compare(lines, books[day])[account]
        status: Status = "ecart" if gaps else "ok"
        result.append(AccountReconciliation(account, status, day, file.file_name, tuple(gaps)))
    return result


# The two commands the user runs -------------------------------------------------------------------


def _alert(reconciliation: Sequence[AccountReconciliation]) -> dict[str, Any]:
    """Each account's status and, on a gap, the alert: identifiers only, never quantities."""
    payload: dict[str, Any] = {"reconciliation": {a.account: a.status for a in reconciliation}}
    gaps = [gap for account in reconciliation for gap in account.gaps]
    if gaps:
        payload["alert"] = GAP_ALERT
        payload["gaps"] = [
            {"account": g.account, "nature": g.nature, "asset": g.asset} for g in gaps
        ]
    return payload


@dataclass(frozen=True)
class ImportResult:
    file: PortfolioFile
    new: bool
    added: int
    removed: int
    accounts: list[str]  # the accounts the file names
    reconciliation: list[AccountReconciliation]  # every account, once the file is in
    warnings: list[str] = field(default_factory=list)

    @property
    def gaps(self) -> list[Gap]:
        return [gap for account in self.reconciliation for gap in account.gaps]

    def journal_payload(self) -> dict[str, Any]:
        """Counts and statuses, never amounts nor labels (ADR-018)."""
        return {
            "file": self.file.file_name,
            "sha256": self.file.sha256,
            "format": self.file.format,
            "rows": self.file.rows,
            "new": self.new,
            "added": self.added,
            "removed": self.removed,
            "accounts": self.accounts,
            "warnings": self.warnings,
            **_alert(self.reconciliation),
        }


def import_transactions(
    store: FinanceStore, path: Path, fmt: str, *, imported_at: datetime
) -> ImportResult:
    """Read, replay with the new file, then record it; an unreplayable ledger refuses it.

    The replay and the reconciliation status run inside the store's transaction: if either
    fails, nothing is recorded.
    """
    reader: Callable[..., Any] | None = FORMATS.get(fmt)
    if reader is None:
        raise PortfolioError(f"format inconnu ; formats disponibles : {', '.join(FORMATS)}")
    table, rows = reader(path, reference(store), local_date(imported_at))
    file = PortfolioFile(table.sha256, "transactions", table.name, fmt, len(rows), imported_at)
    before = Counter(b.transaction for b in effective_ledger(store))
    checked: list[tuple[Book, list[AccountReconciliation]]] = []

    def check() -> None:
        book = build_book(store, as_of=imported_at)
        checked.append((book, reconciliation_status(store, as_of=imported_at)))

    new = store.add_portfolio_file(file, rows, check=check)
    after = Counter(b.transaction for b in effective_ledger(store))
    if checked:
        book, status = checked[0]
        warnings = book.warnings
    else:  # the same file again: nothing changed
        status, warnings = reconciliation_status(store, as_of=imported_at), []
    return ImportResult(
        file=file,
        new=new,
        added=(after - before).total(),
        removed=(before - after).total(),
        accounts=sorted({t.account for _, t in rows}),
        reconciliation=status,
        warnings=warnings,
    )


@dataclass(frozen=True)
class ReconcileResult:
    file: PortfolioFile
    new: bool
    statement_date: date
    reconciliation: list[AccountReconciliation]  # the accounts of the statement

    @property
    def gaps(self) -> list[Gap]:
        return [gap for account in self.reconciliation for gap in account.gaps]

    def journal_payload(self) -> dict[str, Any]:
        """Accounts and identifiers in gap, never the quantities (ADR-018)."""
        return {
            "file": self.file.file_name,
            "sha256": self.file.sha256,
            "rows": self.file.rows,
            "new": self.new,
            "statement_date": self.statement_date.isoformat(),
            **_alert(self.reconciliation),
        }


def reconcile(store: FinanceStore, path: Path, *, at: datetime) -> ReconcileResult:
    """Compare the statement with the positions on its date, then record it (idempotent)."""
    table, rows = read_statement(path, reference(store), local_date(at))
    file = PortfolioFile(table.sha256, "statement", table.name, "cerveau", len(rows), at)
    lines = [line for _, line in rows]
    day = lines[0].statement_date
    gaps = compare(lines, build_book(store, as_of=at, day=day))
    new = store.add_portfolio_file(file, rows)
    status = [
        AccountReconciliation(account, "ecart" if found else "ok", day, table.name, tuple(found))
        for account, found in gaps.items()
    ]
    return ReconcileResult(file, new, day, status)
