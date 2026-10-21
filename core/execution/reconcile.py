"""Reconciliation of the paper account with CERVEAU's own book (ADR-033, D14, D15).

CERVEAU's book is replayed from the order book by :func:`core.finance.portfolio.replay`, with the
exact decimals of the real portfolio: the reference capital deposited, then each fill booked as a
purchase or a sale, fees included. The splits and dividends the adapter booked apply to CERVEAU's
own fills as :mod:`core.execution.actions` says: a split as the portfolio's split, its fraction as
a sale at the session's close, a dividend as a dividend (ADR-042, B187). A broker that booked an
action wrongly therefore shows as a gap only through its effect on its own fills; checking its
actions against the reference data is a live concern (backlog).
:func:`core.finance.portfolio.compare` sets it against the
adapter's statement: positions exactly, cash to the cent. Every paper amount is in whole cents
(prices and fees to the cent, whole shares), so to the cent is exact equality, never a tolerance.

A gap blocks new intents: the Risk Gate's ``reconciliation`` check reads
:meth:`ReconciliationLog.open_gaps`. The block lifts only once a reconciliation is clean again
**and** Lucas has acknowledged it in an interactive terminal (D14). The log is append-only, in
``var/paper/reconciliation.db``: the gaps and their amounts stay there, as fills stay in the order
book, while each reconciliation and each acknowledgement writes an audit entry with counts,
assets and fingerprints, never an amount (R11). A book the portfolio cannot replay, or a statement
no account can hold, is an execution incident (§9): nothing is recorded and the caller trips the
kill switch (D15).
"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, localcontext
from pathlib import Path
from types import TracebackType
from typing import Any

from pydantic import ValidationError

from core.execution.actions import AccountAction, Effect, Movement, replay_account
from core.execution.book import BookedOrder, OrderBook, Recorder
from core.execution.broker import AccountStatement, BrokerAdapter
from core.execution.states import ExecutionIncident
from core.finance.model import StatementLine, Transaction, canonical_json, local_date, utc_text
from core.finance.portfolio import (
    DECIMAL_DIGITS,
    Booked,
    Gap,
    PortfolioError,
    Split,
    compare,
    replay,
)
from core.finance.schema import SchemaError, migrate, schema_version
from core.finance.store import PortfolioFile

PAPER_ACCOUNT = "paper"
LEDGER_NAME = "orders.db"  # where a replay error points: the order book
_SIGN = {"BUY": 1, "SELL": -1}


@dataclass(frozen=True)
class Reconciliation:
    """CERVEAU's book against the adapter's statement at ``as_of``."""

    as_of: datetime
    fills: int  # the fills of CERVEAU's book, replayed
    cursor: int  # the statement's: the broker events it covers
    book_sha256: str
    statement_sha256: str
    gaps: tuple[Gap, ...]

    @property
    def clean(self) -> bool:
        return not self.gaps

    def assets(self) -> list[str]:
        """What diverges, without the amounts: ``cash:EUR``, ``security:FICT-ACME``."""
        return [f"{gap.nature}:{gap.asset}" for gap in self.gaps]


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class PaperBook:
    """CERVEAU's book of the paper account as the portfolio replays it."""

    ledger: list[Booked]  # the deposit, then the transactions in the order they happened
    splits: list[Split]  # one per instrument and session, the session's splits together
    fills: int
    sha256: str  # what was replayed: the capital, the fills and the actions


def _book_split(effects: list[Effect]) -> tuple[Split, Decimal, Decimal]:
    """The portfolio's split of an instrument's splits at one session, and the fraction it then
    sells with what that sale brings: the portfolio holds exactly the account's shares."""
    first, last = effects[0], effects[-1]
    held = Decimal(first.held)
    with localcontext(prec=DECIMAL_DIGITS):
        ratio = Decimal(1)
        for effect in effects:
            ratio *= effect.action.value
        if held * ratio < last.shares:
            # Within the tolerance, below the whole number: the smallest ratio that reaches it.
            with localcontext(rounding=ROUND_CEILING):
                ratio = last.shares / held
        excess = held * ratio - last.shares
    cash = sum((effect.cash for effect in effects), Decimal(0))
    return Split(first.action.session, first.action.symbol, ratio), excess, cash


def paper_ledger(
    orders: Iterable[BookedOrder],
    capital_eur: Decimal,
    *,
    as_of: datetime,
    actions: Iterable[AccountAction] = (),
) -> PaperBook:
    """The reference capital, then every fill in the order it happened and the effects of
    ``actions`` on them, as the portfolio's transactions; with the fingerprint of what was
    replayed. At a session, a split's fraction is sold first, then the fills, then the
    dividends, as :func:`core.execution.actions.replay_account` applies them."""
    fills = sorted(
        ((fill, order.intent) for order in orders for fill in order.fills),
        key=lambda pair: pair[0].executed_at,  # stable: the book's order within an instant
    )
    booked = sorted(actions, key=lambda a: a.key)
    fingerprint: dict[str, object] = {
        "capital_eur": str(capital_eur),
        "fills": [f.sha256() for f, _ in fills],
    }
    if booked:
        fingerprint["actions"] = [a.text() for a in booked]
    sha256 = _sha256(fingerprint)
    movements = [
        Movement(fill.session, intent.instrument.symbol, fill.quantity * _SIGN[intent.side])
        for fill, intent in fills
    ]
    # Without actions the portfolio's replay alone checks the book (a sale beyond the position).
    effects = replay_account(booked, movements).effects if booked else ()
    entries: list[tuple[tuple[object, ...], Transaction]] = []
    for index, (fill, intent) in enumerate(fills):
        trade = Transaction(
            trade_date=fill.session,
            account=PAPER_ACCOUNT,
            kind="buy" if intent.side == "BUY" else "sell",
            asset=intent.instrument.symbol,
            quantity=Decimal(fill.quantity),
            price=fill.price,
            currency=fill.currency,
            fees=fill.fees,
        )
        entries.append(((fill.session, 1, index), trade))
    groups: dict[tuple[object, ...], list[Effect]] = {}
    for effect in effects:
        action = effect.action
        if action.kind == "split":
            groups.setdefault((action.session, action.symbol), []).append(effect)
        elif effect.cash:
            dividend = Transaction(
                trade_date=action.session,
                account=PAPER_ACCOUNT,
                kind="dividend",
                asset=action.symbol,
                quantity=effect.cash,
                currency="EUR",
            )
            entries.append(((action.session, 2, action.symbol, action.ex_date), dividend))
    splits = []
    for (session, symbol), effects in groups.items():
        split, excess, cash = _book_split(effects)
        splits.append(split)
        if excess > 0:
            assert effects[-1].action.close is not None  # noqa: S101 - a split carries its close
            close = effects[-1].action.close
            with localcontext(prec=DECIMAL_DIGITS):
                lost = excess * close
            sale = Transaction(
                trade_date=split.ex_date,
                account=PAPER_ACCOUNT,
                kind="sell",
                asset=split.instrument_id,
                quantity=excess,
                price=close,
                currency="EUR",
                amount=cash if cash > 0 else None,
                fees=Decimal(0) if cash > 0 else lost,
            )
            entries.append(((session, 0, symbol), sale))
    entries.sort(key=lambda entry: entry[0])
    file = PortfolioFile(
        sha256=sha256,
        kind="transactions",
        file_name=LEDGER_NAME,
        format="cerveau-paper",
        rows=len(entries) + 1,
        imported_at=as_of,
    )
    opened = min((t.trade_date for _, t in entries), default=local_date(as_of))
    deposit = Transaction(
        trade_date=opened,
        account=PAPER_ACCOUNT,
        kind="deposit",
        quantity=capital_eur,
        currency="EUR",
    )
    ledger = [Booked(deposit, file, 1)]
    ledger += [Booked(t, file, line) for line, (_, t) in enumerate(entries, start=2)]
    return PaperBook(ledger, splits, len(fills), sha256)


def statement_lines(statement: AccountStatement, *, as_of: datetime) -> list[StatementLine]:
    """The adapter's statement as the lines of a broker's statement; one no account can hold
    (a cash that is not a finite decimal, a position that is not a positive whole number of
    shares, an unknown kind of instrument identifier) is an incident."""
    cash, held = statement.cash_eur, statement.positions
    if not isinstance(cash, Decimal) or not cash.is_finite():
        raise ExecutionIncident("execution_incoherente", None, "relevé : cash illisible")
    if any(type(quantity) is not int or quantity <= 0 for quantity in held.values()):
        raise ExecutionIncident(
            "execution_incoherente", None, "relevé : position nulle, négative ou fractionnaire"
        )
    day = local_date(as_of)
    try:
        return [
            StatementLine(
                statement_date=day,
                account=PAPER_ACCOUNT,
                nature="cash",
                asset="EUR",
                quantity=cash,
            ),
            *(
                StatementLine(
                    statement_date=day,
                    account=PAPER_ACCOUNT,
                    nature="security",
                    asset=symbol,
                    quantity=Decimal(quantity),
                )
                for symbol, quantity in sorted(held.items())
            ),
        ]
    except ValidationError as exc:
        raise ExecutionIncident(
            "execution_incoherente", None, "relevé : identifiant d'instrument invalide"
        ) from exc


def reconcile(
    orders: Iterable[BookedOrder],
    statement: AccountStatement,
    *,
    capital_eur: Decimal,
    as_of: datetime,
) -> Reconciliation:
    """Replay CERVEAU's book of the paper account and compare it with the adapter's statement."""
    paper = paper_ledger(orders, capital_eur, as_of=as_of, actions=statement.actions)
    lines = statement_lines(statement, as_of=as_of)
    try:
        book = replay(paper.ledger, paper.splits, day=local_date(as_of), as_of=as_of)
    except PortfolioError as exc:
        raise ExecutionIncident(
            "execution_incoherente", None, f"livre paper non rejouable : {exc}"
        ) from exc
    read: dict[str, object] = {
        "cash_eur": str(statement.cash_eur),
        "positions": statement.positions,
        "cursor": statement.cursor,
    }
    if statement.actions:
        read["actions"] = [a.text() for a in sorted(statement.actions, key=lambda a: a.key)]
    return Reconciliation(
        as_of=as_of,
        fills=paper.fills,
        cursor=statement.cursor,
        book_sha256=paper.sha256,
        statement_sha256=_sha256(read),
        gaps=tuple(compare(lines, book)[PAPER_ACCOUNT]),
    )


# The log --------------------------------------------------------------------------------------

MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
            """CREATE TABLE entries (
                seq INTEGER PRIMARY KEY,
                kind TEXT NOT NULL CHECK (kind IN ('reconciliation', 'acknowledgement')),
                at TEXT NOT NULL,
                gaps INTEGER NOT NULL CHECK (gaps >= 0),
                fills INTEGER CHECK (fills >= 0),
                cursor INTEGER CHECK (cursor >= 0),
                book_sha256 TEXT CHECK (length(book_sha256) = 64),
                statement_sha256 TEXT CHECK (length(statement_sha256) = 64),
                detail TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                CHECK ((kind = 'reconciliation') = (fills IS NOT NULL AND cursor IS NOT NULL
                    AND book_sha256 IS NOT NULL AND statement_sha256 IS NOT NULL))
            ) STRICT""",
            # D14: an acknowledgement follows a clean reconciliation, with a gap to acknowledge.
            """CREATE TRIGGER entries_acknowledged_when_clean BEFORE INSERT ON entries
            WHEN NEW.kind = 'acknowledgement' AND NOT (
                COALESCE((SELECT kind = 'reconciliation' AND gaps = 0 FROM entries
                          ORDER BY seq DESC LIMIT 1), 0)
                AND EXISTS (SELECT 1 FROM entries
                    WHERE kind = 'reconciliation' AND gaps > 0 AND seq > COALESCE((
                        SELECT MAX(seq) FROM entries WHERE kind = 'acknowledgement'), 0))
            )
            BEGIN
                SELECT RAISE(ABORT, 'entries : acquittement sans réconciliation propre (D14)');
            END""",
            """CREATE TRIGGER entries_no_update BEFORE UPDATE ON entries
            BEGIN SELECT RAISE(ABORT, 'entries : le journal de réconciliation ne se modifie pas');
            END""",
            """CREATE TRIGGER entries_no_delete BEFORE DELETE ON entries
            BEGIN SELECT RAISE(ABORT, 'entries : le journal de réconciliation ne se supprime pas');
            END""",
        ),
    ),
)
LATEST_VERSION = MIGRATIONS[-1][0]

_OPEN_GAPS = (
    "SELECT gaps FROM entries WHERE kind = 'reconciliation' AND gaps > 0 AND seq > COALESCE(("
    "SELECT MAX(seq) FROM entries WHERE kind = 'acknowledgement'), 0) ORDER BY seq DESC LIMIT 1"
)


def default_log_path(project_root: Path) -> Path:
    return project_root / "var" / "paper" / "reconciliation.db"


def interactive_terminal() -> bool:
    """Lucas at a console: standard input and output both on a terminal, as a piped or scripted
    run, and an agent's shell, are not."""
    return bool(sys.stdin and sys.stdin.isatty() and sys.stdout and sys.stdout.isatty())


class ReconciliationError(Exception):
    """The log refuses a request: nothing is recorded."""


class ReconciliationLog:
    """``with ReconciliationLog.open(path, recorder) as log: log.record(result)``."""

    def __init__(
        self, conn: sqlite3.Connection, recorder: Recorder, *, read_only: bool = False
    ) -> None:
        self._conn = conn
        self._recorder = recorder
        if read_only:
            conn.execute("PRAGMA query_only = ON")
            version = schema_version(conn)
            if version != LATEST_VERSION:
                raise SchemaError(f"réconciliation au schéma {version}, attendu {LATEST_VERSION}")
        else:
            migrate(conn, MIGRATIONS)

    @classmethod
    def open(cls, path: Path, recorder: Recorder, *, read_only: bool = False) -> ReconciliationLog:
        """Read only (the dashboard, ADR-041): nothing is created or migrated; a missing file
        raises :class:`sqlite3.OperationalError`, an older schema :class:`SchemaError`."""
        if read_only:
            conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, autocommit=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), autocommit=True)
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            return cls(conn, recorder, read_only=read_only)
        except BaseException:
            conn.close()
            raise

    @classmethod
    def memory(cls, recorder: Recorder) -> ReconciliationLog:
        return cls(sqlite3.connect(":memory:", autocommit=True), recorder)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ReconciliationLog:
        return self

    def __exit__(
        self, kind: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    @contextmanager
    def _write(self) -> Iterator[None]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def _journal(self, actor: str, event: str, payload: dict[str, Any], when: datetime) -> None:
        self._recorder.journal.append(
            actor=actor,
            event=event,
            request_id=self._recorder.request_id,
            versions=self._recorder.versions,
            payload=payload,
            now=when,
        )

    def open_gaps(self) -> int:
        """The Risk Gate's ``open_reconciliation_gaps``: the gaps of the last reconciliation that
        found any since Lucas's last acknowledgement; 0 lets intents through."""
        row = self._conn.execute(_OPEN_GAPS).fetchone()
        return 0 if row is None else int(row[0])

    def awaiting_acknowledgement(self) -> bool:
        """Clean again, but blocked until Lucas acknowledges the gap (D14)."""
        last = self._conn.execute(
            "SELECT gaps FROM entries WHERE kind = 'reconciliation' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return last is not None and last[0] == 0 and self.open_gaps() > 0

    def last_reconciled_at(self) -> datetime | None:
        """The statement time of the last reconciliation, or None before the first one."""
        row = self._conn.execute(
            "SELECT at FROM entries WHERE kind = 'reconciliation' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return None if row is None else datetime.fromisoformat(row[0])

    def record(self, result: Reconciliation, *, now: datetime | None = None) -> int:
        """Record a reconciliation and journal it; returns the gaps that now block intents."""
        when = now or datetime.now(UTC)
        detail = [
            {
                "nature": gap.nature,
                "asset": gap.asset,
                "statement": str(gap.statement),
                "computed": str(gap.computed),
            }
            for gap in result.gaps
        ]
        with self._write():
            self._conn.execute(
                "INSERT INTO entries (kind, at, gaps, fills, cursor, book_sha256, "
                "statement_sha256, detail, recorded_at) "
                "VALUES ('reconciliation', ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    utc_text(result.as_of),
                    len(result.gaps),
                    result.fills,
                    result.cursor,
                    result.book_sha256,
                    result.statement_sha256,
                    canonical_json(detail),
                    utc_text(when),
                ),
            )
            blocked = self.open_gaps()
            self._journal(
                self._recorder.actor,
                "DECISION",
                {
                    "reconciliation": "propre" if result.clean else "ecart",
                    "gaps": result.assets(),
                    "fills": result.fills,
                    "cursor": result.cursor,
                    "book_sha256": result.book_sha256,
                    "statement_sha256": result.statement_sha256,
                    "open_gaps": blocked,
                },
                when,
            )
        return blocked

    def acknowledge(
        self, *, now: datetime | None = None, interactive: Callable[[], bool] = interactive_terminal
    ) -> int:
        """Lucas lifts the block after a clean reconciliation (D14); returns the gaps lifted.
        Refused outside an interactive terminal, without a gap, or while a gap is still there."""
        if not interactive():
            raise ReconciliationError(
                "acquittement refusé : il se fait par Lucas, dans un terminal interactif (D14)"
            )
        gaps = self.open_gaps()
        if not gaps:
            raise ReconciliationError("aucun écart de réconciliation à acquitter")
        if not self.awaiting_acknowledgement():
            raise ReconciliationError(
                "acquittement refusé : la dernière réconciliation n'est pas propre (D14)"
            )
        when = now or datetime.now(UTC)
        with self._write():
            self._conn.execute(
                "INSERT INTO entries (kind, at, gaps, detail, recorded_at) "
                "VALUES ('acknowledgement', ?, ?, ?, ?)",
                (utc_text(when), gaps, canonical_json({"by": "lucas"}), utc_text(when)),
            )
            self._journal("lucas", "APPROVAL", {"reconciliation": "acquittee", "gaps": gaps}, when)
        return gaps


CUT_ATTEMPTS = 3  # pairs of reads before a moving account is an incident (B169)


def settle(
    book: OrderBook,
    adapter: BrokerAdapter,
    log: ReconciliationLog,
    *,
    capital_eur: Decimal,
    now: datetime,
) -> Reconciliation:
    """Book the fills the adapter reports, then reconcile and record (§8): what the paper loop
    does after each batch of fills and at the end of each day. A fill the book already holds
    changes nothing; an incoherent one, or an incoherent account, is an incident (§9).

    The statement and the fills are two reads, taken from one consistent cut (B169): the
    statement first, then the fills, kept only when none is past the statement's cursor. A fill
    that arrives between the two reads starts the pair again; a broker that never holds still
    for :data:`CUT_ATTEMPTS` pairs is an incident, never a false gap."""
    for _ in range(CUT_ATTEMPTS):
        statement = adapter.account_snapshot()
        batch = adapter.fills_since(0)
        if batch.cursor <= statement.cursor:
            break
    else:
        raise ExecutionIncident(
            "execution_incoherente",
            None,
            f"relevé et exécutions : aucune coupe cohérente en {CUT_ATTEMPTS} lectures (B169)",
        )
    for fill in batch.fills:
        book.record_fill(fill, now=now)
    result = reconcile(book.orders(), statement, capital_eur=capital_eur, as_of=now)
    log.record(result, now=now)
    return result
