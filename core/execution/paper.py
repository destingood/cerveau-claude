"""The paper simulator: CERVEAU's own broker, without network (ADR-033, D2, D16).

The account is in euros and opens with the reference capital; it holds long positions only and
never borrows, so an order whose worst case the free cash does not cover is rejected. An order is
a DAY limit order sent after the close of its decision date t and worked on the next session of
its exchange, t+1, like the backtest (D6 of phase 3). At the close of t+1, if the close reaches
the limit, it fills at the close moved by the slippage against the order, to the cent and never
past the limit, for at most ``max_participation_pct`` of the session's volume; what is left is
cancelled at the end of the session. The commission is the larger of the minimum and the rate
times the amount, the exact decimal rounded to the cent half up; NautilusTrader's ``Money``
rounds a float instead, so an exact half cent may be one cent lower there (cross-check, B154).

Its accounting is its own, in ``var/paper/simulator.db``: the capital, the orders, the
rejections, the closed sessions and the events (fills, expiries, cancellations), insertion only.
Cash and positions are replayed from them and never read from CERVEAU's order book, so that the
reconciliation compares two books (ADR-033, §8.6).

Phase 4 limits: euros only, an order in another currency being rejected like in the backtest
engines (ADR-024), and amounts within NautilusTrader's ``MONEY_MAX``, so that every fill can be
cross-checked (B122). The market is read through :class:`Market`: the synthetic market of
phase 3 in tests, the point-in-time finance store otherwise; never the network.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from types import TracebackType
from typing import Annotated, Protocol
from uuid import UUID

import pandas as pd
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from core.config.loader import ExecutionConfig, PaperRiskLimits, TradingCosts
from core.execution.book import REASON_CHARS, Fill, Positive, _connect, _immutable
from core.execution.broker import AccountStatement, BrokerAck, BrokerOrder, FillBatch
from core.execution.intent import OrderIntent
from core.execution.states import ExecutionIncident
from core.finance.calendars import exchange_calendar
from core.finance.model import (
    Currency,
    InstrumentId,
    canonical_json,
    from_utc_text,
    plain_text,
    utc_text,
)
from core.finance.schema import migrate

MONEY_MAX = Decimal(9_223_372_036)  # NautilusTrader's largest Money, read on 20/10/2026 (B122)
CENT = Decimal("0.01")
PCT = Decimal(100)
BPS = Decimal(10_000)
EURO = "EUR"

MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
            """CREATE TABLE account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                capital_eur TEXT NOT NULL,
                opened_at TEXT NOT NULL
            ) STRICT""",
            *_immutable("account", "le compte"),
            """CREATE TABLE orders (
                intent_id TEXT PRIMARY KEY,
                intent_sha256 TEXT NOT NULL CHECK (length(intent_sha256) = 64),
                intent TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                session TEXT NOT NULL,
                submitted_at TEXT NOT NULL
            ) STRICT""",
            """CREATE TRIGGER orders_not_rejected BEFORE INSERT ON orders
            WHEN EXISTS (SELECT 1 FROM rejections WHERE intent_id = NEW.intent_id)
            BEGIN
                SELECT RAISE(ABORT, 'orders : intention déjà rejetée');
            END""",
            *_immutable("orders", "un ordre"),
            """CREATE TABLE rejections (
                intent_id TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                rejected_at TEXT NOT NULL
            ) STRICT""",
            """CREATE TRIGGER rejections_not_accepted BEFORE INSERT ON rejections
            WHEN EXISTS (SELECT 1 FROM orders WHERE intent_id = NEW.intent_id)
            BEGIN
                SELECT RAISE(ABORT, 'rejections : ordre déjà accepté');
            END""",
            *_immutable("rejections", "un rejet"),
            """CREATE TABLE sessions (
                session TEXT PRIMARY KEY,
                closed_at TEXT NOT NULL
            ) STRICT""",
            """CREATE TRIGGER sessions_in_order BEFORE INSERT ON sessions
            WHEN NEW.session <= (SELECT MAX(session) FROM sessions)
            BEGIN
                SELECT RAISE(ABORT, 'sessions : une séance se clôt une fois, dans l''ordre');
            END""",
            *_immutable("sessions", "une séance"),
            """CREATE TABLE events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                intent_id TEXT NOT NULL REFERENCES orders (intent_id),
                kind TEXT NOT NULL CHECK (kind IN ('fill', 'expiry', 'cancel')),
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                cash_eur TEXT NOT NULL,
                fill TEXT,
                fill_sha256 TEXT,
                reason TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                CHECK ((kind = 'fill') = (fill IS NOT NULL AND fill_sha256 IS NOT NULL))
            ) STRICT""",
            """CREATE TRIGGER events_open_order BEFORE INSERT ON events
            WHEN EXISTS (
                SELECT 1 FROM events WHERE intent_id = NEW.intent_id AND kind != 'fill'
            )
            BEGIN
                SELECT RAISE(ABORT, 'events : ordre déjà clos');
            END""",
            """CREATE TRIGGER events_within_order BEFORE INSERT ON events
            WHEN NEW.kind = 'fill' AND NEW.quantity + (
                SELECT COALESCE(SUM(quantity), 0) FROM events
                WHERE intent_id = NEW.intent_id AND kind = 'fill'
            ) > (SELECT quantity FROM orders WHERE intent_id = NEW.intent_id)
            BEGIN
                SELECT RAISE(ABORT, 'events : exécution hors de l''ordre');
            END""",
            *_immutable("events", "un événement"),
        ),
    ),
)


def default_simulator_path(project_root: Path) -> Path:
    return project_root / "var" / "paper" / "simulator.db"


class SimulatorError(Exception):
    """The simulator refuses a request or a setting: nothing is recorded."""


def _why(text: str) -> str:
    try:
        reason = plain_text(text)
    except ValueError as exc:
        raise SimulatorError(f"raison refusée : {exc}") from exc
    if not 1 <= len(reason) <= REASON_CHARS:
        raise SimulatorError(f"raison : de 1 à {REASON_CHARS} caractères")
    return reason


def _cents(value: Decimal) -> bool:
    return value.is_finite() and value % CENT == 0


@dataclass(frozen=True)
class PaperCosts:
    """``trading_costs`` for the paper account: a rate in %, a minimum in €, a slippage in bps."""

    commission_pct: Decimal
    min_commission_eur: Decimal
    slippage_bps: Decimal

    def __post_init__(self) -> None:
        if not (self.commission_pct.is_finite() and 0 <= self.commission_pct < PCT):
            raise SimulatorError("commission_pct : de 0 à moins de 100 %")
        if not (_cents(self.min_commission_eur) and self.min_commission_eur >= 0):
            raise SimulatorError("min_commission_eur : positif ou nul, au centime")
        if not (self.slippage_bps.is_finite() and 0 <= self.slippage_bps < BPS):
            raise SimulatorError("slippage_bps : de 0 à moins de 10 000")

    @classmethod
    def from_config(cls, costs: TradingCosts) -> PaperCosts:
        """The costs of the config; one still A_DEFINIR refuses the paper account (R7, R10).

        ``fx_conversion_bps`` must be set too, though it has no effect while the simulator
        takes euros only.
        """
        values = costs.model_dump()
        unknown = sorted(name for name, value in values.items() if not isinstance(value, Decimal))
        if unknown:
            raise SimulatorError(
                f"trading_costs : {', '.join(unknown)} à définir : compte paper refusé (R7, R10)"
            )
        return cls(values["commission_pct"], values["min_commission_eur"], values["slippage_bps"])

    def commission(self, amount: Decimal) -> Decimal:
        """max(minimum, rate × amount), the rated part to the cent, half up."""
        with localcontext() as ctx:
            ctx.prec = 60
            rated = (amount * self.commission_pct / PCT).quantize(CENT, ROUND_HALF_UP)
        return max(self.min_commission_eur, rated)

    def fill_price(self, side: str, close: Decimal, limit: Decimal) -> Decimal:
        """The close moved by the slippage against the order, to the cent, never past the limit."""
        with localcontext() as ctx:
            ctx.prec = 60
            if side == "BUY":
                moved = (close * (BPS + self.slippage_bps) / BPS).quantize(CENT, ROUND_CEILING)
                return min(moved, limit)
            moved = (close * (BPS - self.slippage_bps) / BPS).quantize(CENT, ROUND_FLOOR)
            return max(moved, limit)


@dataclass(frozen=True)
class PaperSettings:
    capital_eur: Decimal  # the reference capital the account opens with (D16)
    costs: PaperCosts
    participation_pct: Decimal  # the largest share of a session's volume an order takes (D2)

    def __post_init__(self) -> None:
        if not (_cents(self.capital_eur) and 0 < self.capital_eur <= MONEY_MAX):
            raise SimulatorError(f"capital : positif, au centime, au plus {MONEY_MAX} € (B122)")
        if not (self.participation_pct.is_finite() and 0 < self.participation_pct <= PCT):
            raise SimulatorError("participation : de plus de 0 à 100 % du volume")

    @classmethod
    def from_config(
        cls, limits: PaperRiskLimits, execution: ExecutionConfig, costs: TradingCosts
    ) -> PaperSettings:
        capital, participation = limits.capital_reference_eur, execution.max_participation_pct
        if isinstance(capital, str) or isinstance(participation, str):
            names = ("capital_reference_eur", "max_participation_pct")
            unknown = [
                n
                for n, v in zip(names, (capital, participation), strict=True)
                if isinstance(v, str)
            ]
            raise SimulatorError(f"{', '.join(unknown)} à définir : compte paper refusé (R7)")
        return cls(
            capital_eur=Decimal(str(capital)),
            costs=PaperCosts.from_config(costs),
            participation_pct=Decimal(str(participation)),
        )


class SessionBar(BaseModel):
    """A session's close and volume as the market published them, in the instrument's currency."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    symbol: InstrumentId
    session: date
    close: Positive
    volume: Annotated[int, Field(ge=0)] | None  # shares; None when the source gives none
    currency: Currency
    published_at: AwareDatetime


class Market(Protocol):
    def bar(self, symbol: str, session: date) -> SessionBar | None: ...


# The first session of an exchange (its MIC) strictly after a day.
SessionCalendar = Callable[[str, date], date]


def next_exchange_session(mic: str, day: date) -> date:
    """The first session of ``mic`` strictly after ``day``, from exchange-calendars."""
    calendar = exchange_calendar(mic, day.year, day.year + 1)
    if calendar is None:
        raise SimulatorError(f"calendrier inconnu pour la place {mic}")
    later = calendar.sessions[calendar.sessions > pd.Timestamp(day)]
    return later[0].date()


@dataclass(frozen=True)
class SessionReport:
    session: date
    fills: tuple[Fill, ...]
    expired: tuple[tuple[UUID, str], ...]  # the orders closed with the session, and why


@dataclass(frozen=True)
class _Order:
    intent: OrderIntent
    session: date
    submitted_at: datetime
    filled: int
    fill_count: int
    closed: bool  # expired or cancelled

    @property
    def remaining(self) -> int:
        return self.intent.quantity - self.filled

    @property
    def open(self) -> bool:
        return not self.closed and self.remaining > 0


@dataclass(frozen=True)
class _Ledger:
    cash: Decimal
    positions: dict[str, int]
    cursor: int


class PaperSimulator:
    """``with PaperSimulator.open(path, settings, now=...) as broker: broker.submit(...)``.

    It satisfies :class:`core.execution.broker.BrokerAdapter`; :meth:`close_session` stands for
    the market, which a real broker does not need.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: PaperSettings,
        *,
        sessions: SessionCalendar,
        now: datetime,
    ) -> None:
        self._conn = conn
        self.settings = settings
        self._sessions = sessions
        migrate(conn, MIGRATIONS, now=now)
        row = conn.execute("SELECT capital_eur FROM account").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO account (id, capital_eur, opened_at) VALUES (1, ?, ?)",
                (str(settings.capital_eur), utc_text(now)),
            )
        elif Decimal(row["capital_eur"]) != settings.capital_eur:
            raise SimulatorError(
                f"compte paper ouvert avec {row['capital_eur']} € : le capital de référence a "
                "changé, ouvrir un nouveau compte (D16)"
            )

    @classmethod
    def open(
        cls,
        path: Path,
        settings: PaperSettings,
        *,
        now: datetime,
        sessions: SessionCalendar = next_exchange_session,
    ) -> PaperSimulator:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = _connect(str(path), uri=False)
        try:
            return cls(conn, settings, sessions=sessions, now=now)
        except BaseException:
            conn.close()
            raise

    @classmethod
    def memory(
        cls,
        settings: PaperSettings,
        *,
        now: datetime,
        sessions: SessionCalendar = next_exchange_session,
    ) -> PaperSimulator:
        return cls(_connect(":memory:", uri=False), settings, sessions=sessions, now=now)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PaperSimulator:
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
        except sqlite3.IntegrityError as exc:
            # The database caught what the checks above it missed: the broker is incoherent.
            self._conn.execute("ROLLBACK")
            raise ExecutionIncident(
                "execution_incoherente", None, f"le simulateur refuse l'écriture : {exc}"
            ) from exc
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    # Reads ----------------------------------------------------------------------------------

    def _orders(self) -> list[_Order]:
        """Every accepted order, oldest first, with what its events say of it."""
        orders = []
        for row in self._conn.execute(
            "SELECT o.intent, o.intent_sha256, o.session, o.submitted_at, "
            "COALESCE(SUM(CASE WHEN e.kind = 'fill' THEN e.quantity END), 0) AS filled, "
            "COUNT(CASE WHEN e.kind = 'fill' THEN 1 END) AS fill_count, "
            "COUNT(CASE WHEN e.kind != 'fill' THEN 1 END) AS closings "
            "FROM orders o LEFT JOIN events e USING (intent_id) "
            "GROUP BY o.intent_id ORDER BY o.intent_id"
        ):
            intent = OrderIntent.model_validate_json(row["intent"])
            if intent.sha256() != row["intent_sha256"]:
                raise ExecutionIncident(
                    "execution_incoherente",
                    intent.intent_id,
                    "le simulateur garde un ordre à l'empreinte différente de celle enregistrée",
                )
            orders.append(
                _Order(
                    intent=intent,
                    session=date.fromisoformat(row["session"]),
                    submitted_at=from_utc_text(row["submitted_at"]),
                    filled=row["filled"],
                    fill_count=row["fill_count"],
                    closed=row["closings"] > 0,
                )
            )
        return orders

    def _ledger(self) -> _Ledger:
        """Cash and positions replayed from the capital and the fills: the simulator's own."""
        cash = Decimal(self._conn.execute("SELECT capital_eur FROM account").fetchone()[0])
        positions: dict[str, int] = {}
        cursor = 0
        for row in self._conn.execute(
            "SELECT e.seq, e.kind, e.quantity, e.cash_eur, o.symbol, o.side "
            "FROM events e JOIN orders o USING (intent_id) ORDER BY e.seq"
        ):
            cursor = row["seq"]
            if row["kind"] == "fill":
                cash += Decimal(row["cash_eur"])
                sign = 1 if row["side"] == "BUY" else -1
                positions[row["symbol"]] = positions.get(row["symbol"], 0) + sign * row["quantity"]
        held = {symbol: quantity for symbol, quantity in sorted(positions.items()) if quantity}
        return _Ledger(cash, held, cursor)

    def _last_session(self) -> date | None:
        row = self._conn.execute("SELECT MAX(session) FROM sessions").fetchone()
        return None if row[0] is None else date.fromisoformat(row[0])

    def _reserve(self, side: str, quantity: int, limit: Decimal) -> Decimal:
        """The most cash an order can take: a buy at its limit with its commission, or what a
        sell's minimum commission costs beyond what it brings in, at its limit."""
        amount = quantity * limit
        fees = self.settings.costs.commission(amount)
        return amount + fees if side == "BUY" else max(Decimal(0), fees - amount)

    def open_orders(self) -> tuple[BrokerOrder, ...]:
        return tuple(
            BrokerOrder(
                intent_id=order.intent.intent_id,
                symbol=order.intent.instrument.symbol,
                side=order.intent.side,
                remaining=order.remaining,
                limit_price=order.intent.limit_price,
                session=order.session,
            )
            for order in self._orders()
            if order.open
        )

    def account_snapshot(self) -> AccountStatement:
        ledger = self._ledger()
        return AccountStatement(ledger.cash, ledger.positions, ledger.cursor)

    def fills_since(self, cursor: int) -> FillBatch:
        """The fills recorded after ``cursor`` (0 for all), in the order they happened."""
        if cursor < 0:
            raise SimulatorError("curseur négatif")
        fills = []
        for row in self._conn.execute(
            "SELECT seq, fill, fill_sha256 FROM events WHERE kind = 'fill' AND seq > ? "
            "ORDER BY seq",
            (cursor,),
        ):
            fill = Fill.model_validate_json(row["fill"])
            if fill.sha256() != row["fill_sha256"]:
                raise ExecutionIncident(
                    "execution_incoherente",
                    fill.intent_id,
                    f"exécution {fill.fill_id} : empreinte différente de celle enregistrée",
                )
            fills.append(fill)
            cursor = row["seq"]
        return FillBatch(tuple(fills), cursor)

    # Writes ---------------------------------------------------------------------------------

    def _event(
        self,
        intent_id: UUID,
        kind: str,
        quantity: int,
        reason: str,
        now: datetime,
        *,
        cash: Decimal = Decimal(0),
        fill: Fill | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO events (intent_id, kind, quantity, cash_eur, fill, fill_sha256, reason, "
            "recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(intent_id),
                kind,
                quantity,
                str(cash),
                None if fill is None else canonical_json(fill.model_dump(mode="json")),
                None if fill is None else fill.sha256(),
                reason,
                utc_text(now),
            ),
        )

    def _refusal(self, intent: OrderIntent, now: datetime) -> tuple[date | None, str | None]:
        """The session the order would be worked on, and why it is rejected, if it is."""
        if now < intent.created_at:
            return None, "envoyé avant la création de l'intention"
        if intent.instrument.currency != EURO:
            return None, (
                f"devise {intent.instrument.currency} : le simulateur paper ne traite que l'euro "
                "en phase 4 (ADR-033)"
            )
        if intent.quantity * intent.limit_price > MONEY_MAX:
            return None, f"montant au-delà de MONEY_MAX de NautilusTrader ({MONEY_MAX} €, B122)"
        try:
            session = self._sessions(intent.instrument.venue, intent.decision_date)
        except SimulatorError as exc:
            return None, str(exc)
        last = self._last_session()
        if last is not None and session <= last:
            return session, f"séance du {session} déjà close"
        ledger = self._ledger()
        working = [order for order in self._orders() if order.open]
        reserved = sum(
            (self._reserve(o.intent.side, o.remaining, o.intent.limit_price) for o in working),
            Decimal(0),
        )
        symbol = intent.instrument.symbol
        if intent.side == "SELL":
            selling = sum(
                o.remaining
                for o in working
                if o.intent.side == "SELL" and o.intent.instrument.symbol == symbol
            )
            if ledger.positions.get(symbol, 0) - selling < intent.quantity:
                return session, "position insuffisante : pas de vente à découvert (D16)"
        if self._reserve(intent.side, intent.quantity, intent.limit_price) > ledger.cash - reserved:
            return session, "cash libre insuffisant, frais compris : pas de levier (D16)"
        return session, None

    def submit(self, intent: OrderIntent, *, now: datetime) -> BrokerAck:
        """Accept the order for the next session of its exchange, or reject it with the reason.

        An ``intent_id`` is received once: submitted again, it sends nothing and gets the first
        answer, or a rejection if its content differs.
        """
        key = str(intent.intent_id)
        with self._write():
            known = self._conn.execute(
                "SELECT intent_sha256 FROM orders WHERE intent_id = ?", (key,)
            ).fetchone()
            if known is not None:
                if known["intent_sha256"] == intent.sha256():
                    return BrokerAck(
                        intent.intent_id,
                        True,
                        "ordre déjà reçu : aucun second ordre",
                        duplicate=True,
                    )
                return BrokerAck(
                    intent.intent_id,
                    False,
                    "intent_id déjà reçu avec un autre contenu",
                    duplicate=True,
                )
            rejected = self._conn.execute(
                "SELECT reason FROM rejections WHERE intent_id = ?", (key,)
            ).fetchone()
            if rejected is not None:
                return BrokerAck(intent.intent_id, False, rejected["reason"], duplicate=True)
            session, refusal = self._refusal(intent, now)
            if refusal is not None:
                self._conn.execute(
                    "INSERT INTO rejections (intent_id, reason, rejected_at) VALUES (?, ?, ?)",
                    (key, refusal, utc_text(now)),
                )
                return BrokerAck(intent.intent_id, False, refusal)
            self._conn.execute(
                "INSERT INTO orders (intent_id, intent_sha256, intent, symbol, side, quantity, "
                "session, submitted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    intent.sha256(),
                    canonical_json(intent.model_dump(mode="json")),
                    intent.instrument.symbol,
                    intent.side,
                    intent.quantity,
                    str(session),
                    utc_text(now),
                ),
            )
        return BrokerAck(intent.intent_id, True, f"ordre accepté pour la séance du {session}")

    def cancel(self, intent_id: UUID, *, reason: str, now: datetime) -> bool:
        """Cancel what is left of a working order; False if it is unknown or already closed."""
        why = _why(reason)
        with self._write():
            for order in self._orders():
                if order.intent.intent_id == intent_id and order.open:
                    self._event(intent_id, "cancel", order.remaining, why, now)
                    return True
        return False

    def cancel_all(self, *, reason: str, now: datetime) -> tuple[UUID, ...]:
        """Cancel every working order: the kill switch's first move (ADR-034)."""
        why = _why(reason)
        cancelled = []
        with self._write():
            for order in self._orders():
                if order.open:
                    self._event(order.intent.intent_id, "cancel", order.remaining, why, now)
                    cancelled.append(order.intent.intent_id)
        return tuple(cancelled)

    def _work(
        self, order: _Order, session: date, market: Market, ledger: _Ledger, now: datetime
    ) -> tuple[Fill | None, Decimal, str | None]:
        """The fill of ``order`` at the close of ``session`` and the cash it moves, and why the
        order, or what is left of it, ends with the session."""
        intent, settings = order.intent, self.settings
        side, limit, symbol = intent.side, intent.limit_price, intent.instrument.symbol

        def expire(why: str) -> tuple[None, Decimal, str]:
            return None, Decimal(0), f"{why} : ordre expiré"

        if order.session < session:
            return expire(f"séance du {order.session} jamais traitée")
        bar = market.bar(symbol, session)
        if bar is None or bar.symbol != symbol or bar.session != session:
            return expire("pas de cours de clôture de l'instrument pour la séance")
        if bar.published_at > now:
            # Too early, not an expiry: the whole close is refused and can run again later.
            raise SimulatorError(
                f"clôture du {session} de {symbol} publiée après maintenant : "
                "séance non close (R10)"
            )
        if bar.published_at <= order.submitted_at:
            return expire("ordre reçu après la clôture de sa séance (R10)")
        if bar.currency != intent.instrument.currency:
            return expire("cours dans une autre devise que l'ordre")
        if bar.volume is None:
            return expire("volume de la séance inconnu : participation incalculable")
        if (bar.close > limit) if side == "BUY" else (bar.close < limit):
            return expire("limite non atteinte à la clôture")
        participation = settings.participation_pct
        with localcontext() as ctx:
            ctx.prec = 60
            cap = int((bar.volume * participation / PCT).to_integral_value(ROUND_FLOOR))
        quantity = min(order.remaining, cap)
        if not quantity:
            return expire(f"participation de {participation} % du volume : aucun titre")
        price = settings.costs.fill_price(side, bar.close, limit)
        amount = quantity * price
        if amount > MONEY_MAX:
            return expire(f"montant au-delà de MONEY_MAX ({MONEY_MAX} €, B122)")
        fees = settings.costs.commission(amount)
        cash = -(amount + fees) if side == "BUY" else amount - fees
        if ledger.cash + cash < 0:
            # Possible only if the costs grew since the order was accepted.
            return expire("cash insuffisant à l'exécution, frais compris")
        if side == "SELL" and ledger.positions.get(symbol, 0) < quantity:
            # Sells are accepted within the position net of the working sells: never reached.
            raise ExecutionIncident(
                "execution_incoherente",
                intent.intent_id,
                "le simulateur vendrait au-delà de la position détenue",
            )
        fill = Fill(
            fill_id=f"paper:{intent.intent_id.hex}:{order.fill_count + 1}",
            intent_id=intent.intent_id,
            executed_at=bar.published_at,
            session=session,
            quantity=quantity,
            price=price,
            fees=fees,
            currency=bar.currency,
        )
        rest = order.remaining - quantity
        why = None
        if rest:
            why = (
                f"reste de {rest} titres annulé en fin de séance (participation de "
                f"{participation} % du volume)"
            )
        return fill, cash, why

    def close_session(self, session: date, market: Market, *, now: datetime) -> SessionReport:
        """Work the orders due at the close of ``session``, sells first, then end the session.

        What is left of an order is cancelled with the session (DAY), and an order of an earlier
        session never worked expires. Sessions close once each, in order; a close published
        after ``now`` refuses the whole session, which records nothing (R10).
        """
        fills: list[Fill] = []
        expired: list[tuple[UUID, str]] = []
        with self._write():
            last = self._last_session()
            if last is not None and session <= last:
                raise SimulatorError(f"séance du {session} déjà close (dernière : {last})")
            ledger = self._ledger()
            due = [o for o in self._orders() if o.open and o.session <= session]
            for order in sorted(due, key=lambda o: (o.intent.side == "BUY", o.intent.intent_id)):
                intent = order.intent
                fill, cash, why = self._work(order, session, market, ledger, now)
                if fill is not None:
                    self._event(
                        intent.intent_id,
                        "fill",
                        fill.quantity,
                        "exécuté à la clôture",
                        now,
                        cash=cash,
                        fill=fill,
                    )
                    fills.append(fill)
                    symbol, sign = intent.instrument.symbol, 1 if intent.side == "BUY" else -1
                    positions = dict(ledger.positions)
                    positions[symbol] = positions.get(symbol, 0) + sign * fill.quantity
                    ledger = _Ledger(ledger.cash + cash, positions, ledger.cursor)
                if why is not None:
                    rest = order.remaining - (0 if fill is None else fill.quantity)
                    self._event(intent.intent_id, "expiry", rest, why, now)
                    expired.append((intent.intent_id, why))
            self._conn.execute(
                "INSERT INTO sessions (session, closed_at) VALUES (?, ?)",
                (str(session), utc_text(now)),
            )
        return SessionReport(session, tuple(fills), tuple(expired))
