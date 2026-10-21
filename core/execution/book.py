"""The append-only paper order book, ``var/paper/orders.db`` (ADR-032).

Three tables, insertion only: the intents, their state transitions and their fills. The state of
an order is its last transition. Nothing is ever updated or deleted, and the database itself
refuses an illegal transition, a fill beyond the order's quantity and a second order under the
same ``intent_id`` (the client order id), whatever the code does.

Each state change, and each fill, writes an ``ORDER_STATE`` entry to the audit journal within the
same write: the order, its state, the reason and the fingerprints of the intent and of the fill,
never an amount, which stays in the book as for the portfolio. A journal that refuses the entry
leaves the book unchanged. An incoherence of execution raises :class:`ExecutionIncident` and
records nothing.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from types import TracebackType
from typing import Annotated, Any, Protocol
from uuid import UUID

from pydantic import UUID7, AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from core.execution.intent import MAX_QUANTITY, OrderIntent, OriginId
from core.execution.states import (
    FILLABLE,
    OPEN,
    TERMINAL,
    ExecutionIncident,
    OrderState,
    check_move,
)
from core.finance.model import Currency, canonical_json, from_utc_text, plain_text, utc_text
from core.finance.schema import SchemaError, migrate, schema_version

REASON_CHARS = 200
BPS = Decimal(10_000)
BPS_STEP = Decimal("0.01")  # slippage is reported to the hundredth of a basis point

Amount = Annotated[Decimal, Field(ge=0, allow_inf_nan=False, max_digits=24, decimal_places=6)]
Positive = Annotated[Decimal, Field(gt=0, allow_inf_nan=False, max_digits=24, decimal_places=6)]

_LAST_STATE = (
    "COALESCE((SELECT state FROM transitions WHERE intent_id = NEW.intent_id "
    "ORDER BY seq DESC LIMIT 1), '')"
)
_FILLED = "(SELECT COALESCE(SUM(quantity), 0) FROM fills WHERE intent_id = NEW.intent_id)"
_ORDERED = "(SELECT quantity FROM intents WHERE intent_id = NEW.intent_id)"
_KNOWN = "EXISTS (SELECT 1 FROM intents WHERE intent_id = NEW.intent_id)"


def _immutable(table: str, noun: str) -> tuple[str, str]:
    """No UPDATE and no DELETE on ``table``: the book only grows (R11)."""
    return (
        f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} : {noun} ne se modifie pas'); END",
        f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} : {noun} ne se supprime pas'); END",
    )


MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
            """CREATE TABLE intents (
                intent_id TEXT PRIMARY KEY,
                intent_sha256 TEXT NOT NULL CHECK (length(intent_sha256) = 64),
                intent TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                decision_price TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            ) STRICT""",
            """CREATE TRIGGER intents_no_overwrite BEFORE INSERT ON intents
            WHEN EXISTS (SELECT 1 FROM intents WHERE intent_id = NEW.intent_id)
            BEGIN
                SELECT RAISE(ABORT, 'intents : un intent_id ne sert qu''une fois (ADR-032)');
            END""",
            *_immutable("intents", "une intention"),
            # The state machine of ADR-032, '' being the state before the first transition.
            """CREATE TABLE allowed_transitions (
                from_state TEXT NOT NULL,
                to_state TEXT NOT NULL,
                PRIMARY KEY (from_state, to_state)
            ) STRICT, WITHOUT ROWID""",
            """INSERT INTO allowed_transitions (from_state, to_state) VALUES
                ('', 'INTENTION'),
                ('INTENTION', 'VALIDEE'), ('INTENTION', 'REJETEE'),
                ('VALIDEE', 'ENVOYEE'), ('VALIDEE', 'ANNULEE'),
                ('ENVOYEE', 'PARTIELLE'), ('ENVOYEE', 'EXECUTEE'),
                ('ENVOYEE', 'ANNULEE'), ('ENVOYEE', 'REJETEE'),
                ('PARTIELLE', 'EXECUTEE'), ('PARTIELLE', 'ANNULEE')""",
            """CREATE TRIGGER allowed_transitions_no_insert BEFORE INSERT ON allowed_transitions
            BEGIN
                SELECT RAISE(ABORT, 'allowed_transitions : la machine à états ne change pas');
            END""",
            *_immutable("allowed_transitions", "la machine à états"),
            """CREATE TABLE transitions (
                intent_id TEXT NOT NULL REFERENCES intents (intent_id),
                seq INTEGER NOT NULL CHECK (seq >= 1),
                state TEXT NOT NULL,
                reason TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                PRIMARY KEY (intent_id, seq)
            ) STRICT""",
            f"""CREATE TRIGGER transitions_legal BEFORE INSERT ON transitions
            WHEN NOT {_KNOWN}
            OR NOT EXISTS (
                SELECT 1 FROM allowed_transitions
                WHERE from_state = {_LAST_STATE} AND to_state = NEW.state
            )
            OR NEW.seq != 1 + (SELECT COUNT(*) FROM transitions WHERE intent_id = NEW.intent_id)
            OR (NEW.state = 'EXECUTEE' AND {_FILLED} != {_ORDERED})
            OR (NEW.state = 'PARTIELLE' AND {_FILLED} NOT BETWEEN 1 AND {_ORDERED} - 1)
            BEGIN
                SELECT RAISE(ABORT, 'transitions : interdite par la machine à états (ADR-032)');
            END""",  # noqa: S608 - only this module's constants, never an input
            *_immutable("transitions", "une transition"),
            """CREATE TABLE fills (
                fill_id TEXT PRIMARY KEY,
                intent_id TEXT NOT NULL REFERENCES intents (intent_id),
                fill_sha256 TEXT NOT NULL CHECK (length(fill_sha256) = 64),
                executed_at TEXT NOT NULL,
                session TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                price TEXT NOT NULL,
                fees TEXT NOT NULL,
                currency TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            ) STRICT""",
            "CREATE INDEX fills_intent ON fills (intent_id)",
            f"""CREATE TRIGGER fills_within_order BEFORE INSERT ON fills
            WHEN EXISTS (SELECT 1 FROM fills WHERE fill_id = NEW.fill_id)
            OR NOT {_KNOWN}
            OR {_LAST_STATE} NOT IN ('ENVOYEE', 'PARTIELLE')
            OR {_FILLED} + NEW.quantity > {_ORDERED}
            BEGIN
                SELECT RAISE(ABORT, 'fills : exécution hors de l''ordre (ADR-032)');
            END""",  # noqa: S608 - only this module's constants, never an input
            *_immutable("fills", "une exécution"),
        ),
    ),
)
LATEST_VERSION = MIGRATIONS[-1][0]


def default_book_path(project_root: Path) -> Path:
    return project_root / "var" / "paper" / "orders.db"


class OrderBookError(Exception):
    """The book refuses a request or cannot be read: nothing is recorded."""


class Journal(Protocol):
    """The part of :class:`core.audit.chain.AuditJournal` the book uses."""

    def append(
        self,
        *,
        actor: str,
        event: str,
        request_id: str | None = None,
        versions: Mapping[str, str] | None = None,
        payload: Any = None,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Recorder:
    """Where, and on whose behalf, the book journals what it records."""

    journal: Journal
    actor: str
    request_id: str
    versions: Mapping[str, str] = field(default_factory=dict)


class Fill(BaseModel):
    """One execution the adapter reports, in the instrument's currency."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    fill_id: OriginId
    intent_id: UUID7
    executed_at: AwareDatetime
    session: date
    quantity: int = Field(gt=0, le=MAX_QUANTITY)
    price: Positive
    fees: Amount
    currency: Currency

    @field_validator("executed_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)  # the stored form: the same fill, the same fingerprint

    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json")).encode()).hexdigest()


@dataclass(frozen=True)
class BookedOrder:
    intent: OrderIntent
    decision_price: Decimal  # the last close the Risk Gate saw: the reference of slippage
    state: OrderState
    fills: tuple[Fill, ...]

    @property
    def filled(self) -> int:
        return sum(fill.quantity for fill in self.fills)

    @property
    def remaining(self) -> int:
        """What the order still commits; nothing once it is terminal."""
        return 0 if self.state in TERMINAL else self.intent.quantity - self.filled

    @property
    def slippage_bps(self) -> Decimal | None:
        return slippage_bps([self])


def slippage_bps(orders: Iterable[BookedOrder]) -> Decimal | None:
    """Fill prices against the decision price, in basis points of the notional at the decision
    price, over every fill of ``orders``. Positive is a cost: paid more on a buy, received less
    on a sell. None without a fill. Fees are not slippage; they are booked apart."""
    with localcontext() as ctx:
        ctx.prec = 60  # beyond any product of two book amounts: the division is the only rounding
        cost = notional = Decimal(0)
        for order in orders:
            sign = 1 if order.intent.side == "BUY" else -1
            for fill in order.fills:
                cost += sign * fill.quantity * (fill.price - order.decision_price)
                notional += fill.quantity * order.decision_price
        if not notional:
            return None
        return (cost * BPS / notional).quantize(BPS_STEP, rounding=ROUND_HALF_EVEN)


def _connect(target: str, *, uri: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(target, uri=uri, autocommit=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _reason(text: str) -> str:
    try:
        reason = plain_text(text)
    except ValueError as exc:
        raise OrderBookError(f"raison refusée : {exc}") from exc
    if not 1 <= len(reason) <= REASON_CHARS:
        raise OrderBookError(f"raison : de 1 à {REASON_CHARS} caractères")
    return reason


class OrderBook:
    """``with OrderBook.open(path, recorder=Recorder(...)) as book: book.record_intent(...)``."""

    def __init__(
        self, conn: sqlite3.Connection, *, recorder: Recorder | None, read_only: bool
    ) -> None:
        self._conn = conn
        self._recorder = recorder
        self.read_only = read_only
        if read_only:
            conn.execute("PRAGMA query_only = ON")
            version = schema_version(conn)
            if version != LATEST_VERSION:
                raise SchemaError(f"carnet au schéma {version}, attendu {LATEST_VERSION}")
        else:
            migrate(conn, MIGRATIONS)

    @classmethod
    def open(
        cls, path: Path, *, recorder: Recorder | None = None, read_only: bool = False
    ) -> OrderBook:
        if read_only:
            if not path.is_file():
                raise OrderBookError(f"carnet d'ordres absent ({path.name})")
            conn = _connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = _connect(str(path), uri=False)
        try:
            return cls(conn, recorder=recorder, read_only=read_only)
        except BaseException:
            conn.close()
            raise

    @classmethod
    def memory(cls, recorder: Recorder) -> OrderBook:
        return cls(_connect(":memory:", uri=False), recorder=recorder, read_only=False)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> OrderBook:
        return self

    def __exit__(
        self, kind: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        return schema_version(self._conn)

    # Writes ---------------------------------------------------------------------------------

    @contextmanager
    def _write(self) -> Iterator[Recorder]:
        if self.read_only or self._recorder is None:
            raise OrderBookError("carnet ouvert sans journal : lecture seule")
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._recorder
        except sqlite3.IntegrityError as exc:
            # The database caught what the checks above it missed: still an incoherence.
            self._conn.execute("ROLLBACK")
            raise ExecutionIncident(
                "execution_incoherente", None, f"le carnet refuse l'écriture : {exc}"
            ) from exc
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def _journal(
        self,
        recorder: Recorder,
        row: sqlite3.Row,
        state: OrderState,
        reason: str,
        when: datetime,
        fill: Fill | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "intent_id": row["intent_id"],
            "state": state.value,
            "reason": reason,
            "intent_sha256": row["intent_sha256"],
        }
        if fill is not None:
            payload |= {"fill_id": fill.fill_id, "fill_sha256": fill.sha256()}
        recorder.journal.append(
            actor=recorder.actor,
            event="ORDER_STATE",
            request_id=recorder.request_id,
            versions=recorder.versions,
            payload=payload,
            now=when,
        )

    def _move(self, intent_id: str, state: OrderState, reason: str, when: datetime) -> None:
        seq = self._conn.execute(
            "SELECT COUNT(*) FROM transitions WHERE intent_id = ?", (intent_id,)
        ).fetchone()[0]
        self._conn.execute(
            "INSERT INTO transitions (intent_id, seq, state, reason, recorded_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (intent_id, seq + 1, state.value, reason, utc_text(when)),
        )

    def record_intent(
        self,
        intent: OrderIntent,
        *,
        decision_price: Decimal,
        reason: str,
        now: datetime | None = None,
    ) -> BookedOrder:
        """Book a drafted intent as INTENTION. A booked ``intent_id`` is refused: the client
        order id never gives a second order."""
        price = _decision_price(decision_price)
        why = _reason(reason)
        when = now or datetime.now(UTC)
        key = str(intent.intent_id)
        with self._write() as recorder:
            if self._row(key) is not None:
                raise OrderBookError(f"intention {key} déjà au carnet : pas de second ordre")
            self._conn.execute(
                "INSERT INTO intents (intent_id, intent_sha256, intent, quantity, decision_price, "
                "recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    key,
                    intent.sha256(),
                    canonical_json(intent.model_dump(mode="json")),
                    intent.quantity,
                    str(price),
                    utc_text(when),
                ),
            )
            self._move(key, OrderState.INTENTION, why, when)
            self._journal(recorder, self._known(key), OrderState.INTENTION, why, when)
        return self.order(intent.intent_id)

    def transition(
        self, intent_id: UUID, target: OrderState, *, reason: str, now: datetime | None = None
    ) -> OrderState:
        """Move an order along the state machine; PARTIELLE and EXECUTEE follow from fills
        only. Any other move, or an unknown order, is an execution incident (§9)."""
        why = _reason(reason)
        when = now or datetime.now(UTC)
        key = str(intent_id)
        with self._write() as recorder:
            row = self._known(key)
            check_move(intent_id, self._state(key), target)
            self._move(key, target, why, when)
            self._journal(recorder, row, target, why, when)
        return target

    def record_fill(self, fill: Fill, *, now: datetime | None = None) -> OrderState:
        """Book a fill and move the order to PARTIELLE or EXECUTEE. The same fill reported
        again is already booked and changes nothing; any incoherence is an incident (§9)."""
        when = now or datetime.now(UTC)
        key = str(fill.intent_id)
        with self._write() as recorder:
            row = self._known(key)
            current = self._state(key)
            seen = self._conn.execute(
                "SELECT fill_sha256 FROM fills WHERE fill_id = ?", (fill.fill_id,)
            ).fetchone()
            if seen is not None:
                if seen["fill_sha256"] == fill.sha256():
                    return current
                raise ExecutionIncident(
                    "execution_incoherente",
                    fill.intent_id,
                    f"exécution {fill.fill_id} déjà reçue avec un autre contenu",
                )
            booked = self._booked(row)
            _check_fill(booked, fill)
            self._conn.execute(
                "INSERT INTO fills (fill_id, intent_id, fill_sha256, executed_at, session, "
                "quantity, price, fees, currency, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fill.fill_id,
                    key,
                    fill.sha256(),
                    utc_text(fill.executed_at),
                    fill.session.isoformat(),
                    fill.quantity,
                    str(fill.price),
                    str(fill.fees),
                    fill.currency,
                    utc_text(when),
                ),
            )
            done = booked.filled + fill.quantity == booked.intent.quantity
            state = OrderState.EXECUTEE if done else OrderState.PARTIELLE
            why = "exécution totale" if done else "exécution partielle"
            if state != current:
                self._move(key, state, why, when)
            self._journal(recorder, row, state, why, when, fill)
        return state

    # Reads ----------------------------------------------------------------------------------

    def _row(self, intent_id: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT * FROM intents WHERE intent_id = ?", (intent_id,)
        ).fetchone()
        return row

    def _known(self, intent_id: str) -> sqlite3.Row:
        row = self._row(intent_id)
        if row is None:
            raise ExecutionIncident(
                "ordre_inconnu", UUID(intent_id), f"ordre {intent_id} absent du carnet"
            )
        return row

    def _state(self, intent_id: str) -> OrderState:
        row = self._conn.execute(
            "SELECT state FROM transitions WHERE intent_id = ? ORDER BY seq DESC LIMIT 1",
            (intent_id,),
        ).fetchone()
        return OrderState(row["state"])

    def _booked(self, row: sqlite3.Row) -> BookedOrder:
        intent = OrderIntent.model_validate_json(row["intent"])
        if intent.sha256() != row["intent_sha256"]:
            raise OrderBookError(
                f"intention {row['intent_id']} : empreinte différente de celle enregistrée"
            )
        fills = []
        for stored in self._conn.execute(
            "SELECT * FROM fills WHERE intent_id = ? ORDER BY rowid", (row["intent_id"],)
        ):
            fill = Fill(
                fill_id=stored["fill_id"],
                intent_id=intent.intent_id,
                executed_at=from_utc_text(stored["executed_at"]),
                session=date.fromisoformat(stored["session"]),
                quantity=stored["quantity"],
                price=Decimal(stored["price"]),
                fees=Decimal(stored["fees"]),
                currency=stored["currency"],
            )
            if fill.sha256() != stored["fill_sha256"]:
                raise OrderBookError(
                    f"exécution {fill.fill_id} : empreinte différente de celle enregistrée"
                )
            fills.append(fill)
        return BookedOrder(
            intent=intent,
            decision_price=Decimal(row["decision_price"]),
            state=self._state(row["intent_id"]),
            fills=tuple(fills),
        )

    def order(self, intent_id: UUID) -> BookedOrder:
        row = self._row(str(intent_id))
        if row is None:
            raise OrderBookError(f"ordre {intent_id} absent du carnet")
        return self._booked(row)

    def orders(self, states: Collection[OrderState] | None = None) -> list[BookedOrder]:
        """Every booked order, oldest first (a UUIDv7 sorts by time), or those in ``states``."""
        booked = [
            self._booked(row)
            for row in self._conn.execute("SELECT * FROM intents ORDER BY intent_id")
        ]
        return [order for order in booked if states is None or order.state in states]

    def open_orders(self) -> list[BookedOrder]:
        """The orders that still commit cash: those the kill switch cancels (ADR-034)."""
        return self.orders(OPEN)

    def intent_ids(self) -> frozenset[UUID]:
        """Every booked ``intent_id``: the Risk Gate's ``seen_intent_ids``."""
        return frozenset(
            UUID(row["intent_id"]) for row in self._conn.execute("SELECT intent_id FROM intents")
        )


def _decision_price(value: Decimal) -> Decimal:
    """The Risk Gate's quote price, under the same bounds as :class:`Quote` (ADR-031)."""
    exponent = value.as_tuple().exponent if isinstance(value, Decimal) else "n"
    if (
        not isinstance(exponent, int)
        or exponent < -6
        or value <= 0
        or len(value.as_tuple().digits) > 24
    ):
        raise OrderBookError("prix de décision : décimal positif, six décimales au plus")
    return value


def _check_fill(order: BookedOrder, fill: Fill) -> None:
    """A fill the order cannot have: an incoherent broker (§9)."""
    intent = order.intent
    if order.state not in FILLABLE:
        raise ExecutionIncident(
            "transition_interdite",
            intent.intent_id,
            f"exécution {fill.fill_id} d'un ordre {order.state}",
        )
    if order.filled + fill.quantity > intent.quantity:
        raise ExecutionIncident(
            "quantite_depassee",
            intent.intent_id,
            f"exécution {fill.fill_id} : quantité cumulée au-delà de celle de l'ordre",
        )
    beyond = (
        fill.price > intent.limit_price if intent.side == "BUY" else fill.price < intent.limit_price
    )
    problems = {
        "devise différente de celle de l'ordre": fill.currency != intent.instrument.currency,
        "prix au-delà de la limite": beyond,
        "exécutée avant l'intention": fill.executed_at < intent.created_at,
        "séance antérieure à la décision": fill.session < intent.decision_date,
    }
    if found := [problem for problem, present in problems.items() if present]:
        raise ExecutionIncident(
            "execution_incoherente",
            intent.intent_id,
            f"exécution {fill.fill_id} : {', '.join(found)}",
        )
