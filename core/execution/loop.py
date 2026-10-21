"""The paper loop's day (plan §10, ADR-033): close the sessions due, settle, value, then draft,
gate and send the day's intents.

:func:`run_day` treats the decision day of ``now`` once. In order:

1. the kill switch: a ``KILL`` file nobody recorded is engaged (``fichier``), an engaged switch
   stops the day;
2. the sessions due: each order the simulator works on a session whose close is past is worked
   at that close, from the store as known now; a close the store does not have yet stops the day
   until it is ingested (``attente_donnees``), unless it is older than ``max_staleness_sessions``:
   the kill switch is then tripped (``perte_donnees``);
3. the reconciliation (:func:`core.execution.reconcile.settle`), then the book follows the
   simulator: an order it no longer works expired with its session; an incident trips the kill
   switch (``incident_execution``);
4. the freshness of the market data the account depends on: a held or working instrument without
   a close younger than ``max_staleness_sessions`` trips the kill switch (``perte_donnees``);
5. the valuation, recorded once a day in ``var/paper/loop.db``, and the loss limits
   (``limite``, ``drawdown``);
6. each intent source's orders, drafted (:mod:`core.execution.drafter`), gated
   (:func:`core.risk_gate.gate.evaluate`), decided (:func:`core.policy.engine.decide_order`) and,
   for ``paper``, sent to the simulator, one at a time against a snapshot rebuilt from the book;
   a day that already drafted, stopped and run again, drafts nothing more.

The day ends with its Markdown report and a line in ``runs``: a day already there is never
treated again, and a past day is never replayed (R10). Every figure of the report comes from the
simulator, the book, the store or the Gate, named next to it (R1). The book must journal on
behalf of ``policy``, the kill switch's automatic actor.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_FLOOR, Decimal, localcontext
from pathlib import Path
from types import TracebackType
from typing import Literal, Protocol
from uuid import UUID

import pandas as pd

from core.config.loader import Config
from core.execution.book import Journal, OrderBook, OrderBookError, slippage_bps
from core.execution.broker import NETWORK_ERRORS, AccountStatement, BrokerOrder
from core.execution.drafter import DraftError, IntentDrafter, TargetOrder, clip
from core.execution.intent import IntentOrigin, IntentRationale, OrderIntent, SizingSource
from core.execution.kill_switch import Stop, Trigger, detect, engage, loss_breaches
from core.execution.market import (
    PLACES,
    MarketFacts,
    StoreMarket,
    gate_snapshot,
    market_facts,
    sessions_since,
)
from core.execution.paper import EURO, PaperSimulator, SessionReport, SimulatorError
from core.execution.reconcile import Reconciliation, ReconciliationLog, settle
from core.execution.states import FILLABLE, ExecutionIncident, OrderState
from core.execution.uuid7 import uuid7
from core.finance.calendars import exchange_calendar
from core.finance.model import canonical_json, local_date, utc_text
from core.finance.research.copilot import decision_day
from core.finance.schema import migrate
from core.finance.store import FinanceStore
from core.policy.engine import decide_order, kill_switch_engaged
from core.risk_gate.gate import Result, evaluate
from core.risk_gate.snapshot import Account, GateSnapshot

PRICE_TOOL = "paper_market"  # the read of the store's closes the intents are priced from
PRICE_CALL = f"{PRICE_TOOL}#1"
BOOK_ACTOR = "policy"  # engage() needs the book to journal as the automatic actor
LOOP_ACTOR = "scheduler"

Outcome = Literal[
    "terminee", "deja_traitee", "pas_de_seance", "attente_donnees", "injoignable", "arret"
]
OUTCOMES: Mapping[Outcome, str] = {
    "terminee": "journée traitée",
    "deja_traitee": "journée déjà traitée : rien n'est refait",
    "pas_de_seance": "aucune séance ce jour sur les places en jeu",
    "attente_donnees": "clôture attendue absente de la base : relancer après l'ingestion",
    "injoignable": "adaptateur sans réponse : rien n'est renvoyé ; relancer, la réconciliation "
    "tranchera",
    "arret": "kill switch engagé : la journée s'arrête",
}


def default_loop_path(project_root: Path) -> Path:
    return project_root / "var" / "paper" / "loop.db"


def default_reports_dir(project_root: Path) -> Path:
    return project_root / "var" / "paper" / "reports"


class LoopError(Exception):
    """The day cannot go on without Lucas: nothing more is recorded."""


MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
            """CREATE TABLE valuations (
                day TEXT PRIMARY KEY,
                equity_eur TEXT NOT NULL,
                cash_eur TEXT NOT NULL,
                positions TEXT NOT NULL,
                valued_at TEXT NOT NULL
            ) STRICT""",
            """CREATE TABLE runs (
                day TEXT PRIMARY KEY,
                completed_at TEXT NOT NULL,
                intents INTEGER NOT NULL CHECK (intents >= 0),
                report_sha256 TEXT NOT NULL CHECK (length(report_sha256) = 64)
            ) STRICT""",
            *(
                f"""CREATE TRIGGER {table}_no_{verb} BEFORE {verb.upper()} ON {table}
                BEGIN SELECT RAISE(ABORT, '{table} : la boucle paper ne se réécrit pas'); END"""
                for table in ("valuations", "runs")
                for verb in ("update", "delete")
            ),
        ),
    ),
)


@dataclass(frozen=True)
class Valuation:
    """The account at the end of a day, as the loop valued it."""

    day: date
    equity_eur: Decimal
    cash_eur: Decimal
    positions: Mapping[str, int]
    valued_at: datetime


class LoopLog:
    """The days the loop treated and the valuations the loss limits are measured from;
    append-only."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        migrate(conn, MIGRATIONS)

    @classmethod
    def open(cls, path: Path) -> LoopLog:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), autocommit=True)
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            return cls(conn)
        except BaseException:
            conn.close()
            raise

    @classmethod
    def memory(cls) -> LoopLog:
        return cls(sqlite3.connect(":memory:", autocommit=True))

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> LoopLog:
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

    def done(self, day: date) -> bool:
        row = self._conn.execute("SELECT 1 FROM runs WHERE day = ?", (day.isoformat(),))
        return row.fetchone() is not None

    def days(self) -> list[date]:
        rows = self._conn.execute("SELECT day FROM runs ORDER BY day")
        return [date.fromisoformat(row[0]) for row in rows]

    def valuations(self) -> list[Valuation]:
        rows = self._conn.execute(
            "SELECT day, equity_eur, cash_eur, positions, valued_at FROM valuations ORDER BY day"
        )
        return [
            Valuation(
                day=date.fromisoformat(row[0]),
                equity_eur=Decimal(row[1]),
                cash_eur=Decimal(row[2]),
                positions=dict(sorted(_positions(row[3]).items())),
                valued_at=datetime.fromisoformat(row[4]),
            )
            for row in rows
        ]

    def record_valuation(self, valuation: Valuation) -> None:
        """Record the day's valuation once. The same one again changes nothing (a day stopped
        after it and run again); another one is refused: the account moved within the day."""
        key = valuation.day.isoformat()
        positions = canonical_json(dict(valuation.positions))
        with self._write():
            row = self._conn.execute(
                "SELECT equity_eur, cash_eur, positions FROM valuations WHERE day = ?", (key,)
            ).fetchone()
            if row is not None:
                if (Decimal(row[0]), Decimal(row[1]), row[2]) == (
                    valuation.equity_eur,
                    valuation.cash_eur,
                    positions,
                ):
                    return
                raise LoopError(
                    f"valorisation du {valuation.day} déjà enregistrée avec un autre compte : "
                    "à examiner par Lucas"
                )
            self._conn.execute(
                "INSERT INTO valuations (day, equity_eur, cash_eur, positions, valued_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    key,
                    str(valuation.equity_eur),
                    str(valuation.cash_eur),
                    positions,
                    utc_text(valuation.valued_at),
                ),
            )

    def record_run(self, day: date, *, completed_at: datetime, intents: int, report: str) -> None:
        with self._write():
            self._conn.execute(
                "INSERT INTO runs (day, completed_at, intents, report_sha256) VALUES (?, ?, ?, ?)",
                (
                    day.isoformat(),
                    utc_text(completed_at),
                    intents,
                    hashlib.sha256(report.encode()).hexdigest(),
                ),
            )


def _positions(text: str) -> dict[str, int]:
    loaded = json.loads(text)
    return {str(key): int(value) for key, value in loaded.items()}


# Intent sources ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Proposal:
    """What a source wants traded today, and why."""

    orders: tuple[TargetOrder, ...]
    rationale: IntentRationale
    origin: IntentOrigin


class IntentSource(Protocol):
    """A strategy or a committee: sizes target orders from the Gate's snapshot."""

    @property
    def tool(self) -> str:
        """The tool the sizing is cited from (``SizingSource.tool``)."""
        ...

    def symbols(self) -> frozenset[str]:
        """The instruments it may trade: their facts are read before it proposes."""
        ...

    def propose(
        self, snapshot: GateSnapshot, *, day: date, sizing: SizingSource
    ) -> Proposal | None: ...


# The day ----------------------------------------------------------------------------------------


@dataclass
class PaperDay:
    """What a day of the paper loop works with. The book journals as ``policy``."""

    root: Path
    config: Config
    store: FinanceStore
    book: OrderBook
    simulator: PaperSimulator
    reconciliations: ReconciliationLog
    log: LoopLog
    journal: Journal
    request_id: str
    sources: Sequence[IntentSource] = ()
    ids: Callable[[], UUID] = uuid7


@dataclass(frozen=True)
class IntentOutcome:
    """One drafted intent: what the Gate kept, what the policy decided, where it ended."""

    intent_id: UUID
    origin: str
    symbol: str
    side: str
    requested: int
    quantity: int
    gate: Result
    effect: str
    state: OrderState
    reasons: tuple[str, ...]


@dataclass
class DayReport:
    day: date
    as_of: datetime
    request_id: str
    outcome: Outcome = "terminee"
    sessions: list[SessionReport] = field(default_factory=list)
    reconciliation: Reconciliation | None = None
    expired_in_book: list[UUID] = field(default_factory=list)
    valuation: Valuation | None = None
    account: Account | None = None
    breaches: tuple[tuple[Trigger, str], ...] = ()
    intents: list[IntentOutcome] = field(default_factory=list)
    stop: Stop | None = None
    notes: list[str] = field(default_factory=list)  # what is missing or blocked, and why


def session_close(mic: str, session: date) -> datetime | None:
    """The close of ``session`` on ``mic``, None for an unknown calendar or a day off."""
    calendar = exchange_calendar(mic, session.year, session.year)
    if calendar is None:
        return None
    key = pd.Timestamp(session)
    if key not in calendar.closes.index:
        return None
    close: datetime = calendar.closes[key].to_pydatetime()
    return close


def _versions(env: PaperDay) -> dict[str, str]:
    return {"config": env.config.digest}


def _target_seconds(config: Config) -> float | None:
    target = config.risk.kill_switch.target_seconds
    return None if isinstance(target, str) else float(target)


def _engage(env: PaperDay, report: DayReport, trigger: Trigger, reason: str) -> DayReport:
    report.stop = engage(
        env.root,
        trigger=trigger,
        reason=clip(reason, 200),
        journal=env.journal,
        actor=BOOK_ACTOR,
        request_id=env.request_id,
        now=report.as_of,
        target_seconds=_target_seconds(env.config),
        adapter=env.simulator,
        book=env.book,
        versions=_versions(env),
    )
    report.outcome = "arret"
    return report


def _due(env: PaperDay, day: date, now: datetime) -> dict[date, list[BrokerOrder]]:
    """The simulator's orders whose session is over at ``now``, by session."""
    due: dict[date, list[BrokerOrder]] = {}
    for order in env.simulator.open_orders():
        if order.session > day:
            continue
        try:
            venue = env.book.order(order.intent_id).intent.instrument.venue
        except OrderBookError as exc:
            raise ExecutionIncident(
                "ordre_inconnu",
                order.intent_id,
                "ordre travaillé par le simulateur, absent du carnet",
            ) from exc
        close = session_close(venue, order.session)
        if close is not None and close <= now:
            due.setdefault(order.session, []).append(order)
    return dict(sorted(due.items()))


class _DataLoss(Exception):
    """A close the simulator needs is missing for longer than ``max_staleness_sessions``."""


def _close_sessions(env: PaperDay, report: DayReport) -> bool:
    """Work the sessions due; False when a close is not in the store yet, :class:`_DataLoss`
    when it is missing for longer than ``max_staleness_sessions``."""
    now = report.as_of
    market = StoreMarket(env.store, as_of=now)
    limit = env.config.data_sources.quality.max_staleness_sessions
    for session, orders in _due(env, report.day, now).items():
        late = [o for o in orders if market.bar(o.symbol, session) is None]
        if late:
            missing = ", ".join(sorted({o.symbol for o in late}))
            age = max(
                sessions_since(env.book.order(o.intent_id).intent.instrument.venue, session, now)
                for o in late
            )
            if not isinstance(limit, str) and age > limit:
                raise _DataLoss(f"clôture du {session} absente pour {missing} depuis {age} séances")
            report.notes.append(f"clôture du {session} absente pour {missing}")
            return False
        try:
            report.sessions.append(env.simulator.close_session(session, market, now=now))
        except SimulatorError as exc:
            report.notes.append(str(exc))
            return False
    return True


def _follow_simulator(env: PaperDay, report: DayReport) -> None:
    """Expire in the book what the simulator no longer works; cancel what was never sent."""
    now = report.as_of
    working = {order.intent_id for order in env.simulator.open_orders()}
    for order in env.book.orders(FILLABLE):
        intent_id = order.intent.intent_id
        if intent_id not in working:
            env.book.transition(
                intent_id,
                OrderState.ANNULEE,
                reason="plus travaillé par le simulateur : expiré en fin de séance ou jamais reçu",
                now=now,
            )
            report.expired_in_book.append(intent_id)
    for order in env.book.orders({OrderState.VALIDEE}):
        # Validated, never sent: the day stopped between the two. It is not sent late.
        env.book.transition(
            order.intent.intent_id,
            OrderState.ANNULEE,
            reason="jamais envoyé : journée interrompue avant l'envoi",
            now=now,
        )
        report.expired_in_book.append(order.intent.intent_id)


def _symbols(env: PaperDay, statement: AccountStatement) -> tuple[set[str], set[str]]:
    """What the account depends on (held or working), and everything read today."""
    exposed = {s for s, q in statement.positions.items() if q > 0}
    exposed |= {order.intent.instrument.symbol for order in env.book.open_orders()}
    universe = env.config.risk_limits_paper.universe
    read = set(exposed) | (set(universe) if isinstance(universe, list) else set())
    for source in env.sources:
        read |= source.symbols()
    return exposed, read


def _stale(env: PaperDay, facts: MarketFacts, exposed: set[str]) -> list[str]:
    """The exposed instruments whose value is unknown or too old at ``facts.as_of``."""
    limit = env.config.data_sources.quality.max_staleness_sessions
    stale = []
    for symbol in sorted(exposed):
        quote = facts.quotes.get(symbol)
        instrument = facts.instruments.get(symbol)
        if quote is None or instrument is None:
            stale.append(f"{symbol} ({facts.gaps.get(symbol, 'aucun cours')})")
        elif not isinstance(limit, str) and quote.sessions_old > limit:
            stale.append(f"{symbol} (clôture vieille de {quote.sessions_old} séances)")
        elif instrument.currency != EURO and instrument.currency not in facts.fx:
            stale.append(f"{symbol} (taux {instrument.currency} absent)")
    return stale


def _valuation(statement: AccountStatement, facts: MarketFacts, day: date) -> Valuation:
    """Cash and each position at its last close, in euros, to six decimals rounded down."""
    with localcontext() as ctx:
        ctx.prec = 60
        equity = statement.cash_eur
        for symbol, quantity in statement.positions.items():
            price = facts.quotes[symbol].price
            currency = facts.instruments[symbol].currency
            rate = Decimal(1) if currency == EURO else facts.fx[currency].eur_per_unit
            equity += quantity * price * rate
        equity = equity.quantize(PLACES, ROUND_FLOOR)
    positions = {s: q for s, q in sorted(statement.positions.items()) if q}
    return Valuation(day, equity, statement.cash_eur, positions, facts.as_of)


def _account(env: PaperDay, valuation: Valuation, report: DayReport) -> Account | None:
    """The account the limits read: losses against the previous valuations, or the capital."""
    limits = env.config.risk_limits_paper
    sessions, capital = limits.rolling_loss_sessions, limits.capital_reference_eur
    if isinstance(sessions, str) or isinstance(capital, str):
        report.notes.append("capital de référence ou séances de perte glissante à définir (R7)")
        return None
    reference = Decimal(str(capital))
    before = [v.equity_eur for v in env.log.valuations() if v.day < valuation.day]
    equity = valuation.equity_eur
    if equity <= 0:
        report.notes.append("valeur liquidative nulle ou négative : compte incohérent")
        return None
    return Account(
        cash_eur=valuation.cash_eur,
        equity_eur=equity,
        peak_equity_eur=max([reference, equity, *before]),
        day_pnl_eur=equity - (before[-1] if before else reference),
        rolling_pnl_eur=equity - (before[-sessions] if len(before) >= sessions else reference),
        rolling_sessions=sessions,
    )


def _journal_call(env: PaperDay, payload: dict[str, object], now: datetime) -> None:
    env.journal.append(
        actor=LOOP_ACTOR,
        event="TOOL_CALL",
        request_id=env.request_id,
        versions=_versions(env),
        payload=payload,
        now=now,
    )


def _snapshot(env: PaperDay, facts: MarketFacts, account: Account) -> GateSnapshot:
    return gate_snapshot(
        facts,
        account=account,
        statement=env.simulator.account_snapshot(),
        book=env.book,
        open_gaps=env.reconciliations.open_gaps(),
    )


def _treat(
    env: PaperDay, intent: OrderIntent, snapshot: GateSnapshot, report: DayReport
) -> IntentOutcome:
    """Gate, decide, book and, for ``paper``, send one intent."""
    now, config = report.as_of, env.config
    gate = evaluate(
        intent,
        snapshot,
        config.risk_limits_paper,
        config.risk.trading_costs,
        config.compliance,
        config.data_sources.quality,
    )
    booked = intent
    if gate.result == "REDUIT":  # the same client order id, at the quantity the Gate kept
        booked = intent.model_copy(update={"quantity": gate.quantity})
    # ADR-031: the Gate's own POLICY entry, with the quantities the C.4 block leaves out, so
    # that a reduced order is traced from the intent drafted to the order booked.
    env.journal.append(
        actor="risk_gate",
        event="POLICY",
        request_id=env.request_id,
        versions=_versions(env),
        payload={
            "intent_id": str(intent.intent_id),
            "intent_sha256": intent.sha256(),
            "requested_quantity": intent.quantity,
            "quantity": gate.quantity,
            "booked_intent_sha256": None if gate.result == "REFUSE" else booked.sha256(),
            **gate.policy_payload(),
            "reasons": list(gate.reasons),
        },
        now=now,
    )
    decision = decide_order(
        config.autonomy,
        request_id=env.request_id,
        kill_switch=kill_switch_engaged(env.root),
        live_enabled=config.live.enabled,
        risk_gate=gate,
    )
    env.journal.append(
        actor="policy",
        event="POLICY",
        request_id=env.request_id,
        versions=_versions(env),
        payload={
            "intent_id": str(intent.intent_id),
            "intent_sha256": intent.sha256(),
            **decision.to_payload(),
        },
        now=now,
    )
    effect = decision.effect
    quote = snapshot.quotes[intent.instrument.symbol]
    env.book.record_intent(
        booked, decision_price=quote.price, reason=f"rédigée ({intent.origin.id})", now=now
    )
    key, reasons = intent.intent_id, tuple(gate.reasons) + tuple(decision.reasons)

    def outcome(state: OrderState, why: tuple[str, ...]) -> IntentOutcome:
        return IntentOutcome(
            intent_id=key,
            origin=intent.origin.id,
            symbol=intent.instrument.symbol,
            side=intent.side,
            requested=intent.quantity,
            quantity=booked.quantity if gate.result != "REFUSE" else 0,
            gate=gate.result,
            effect=effect,
            state=state,
            reasons=why,
        )

    state = OrderState.INTENTION
    if effect == "paper" and gate.result != "REFUSE":
        env.book.transition(
            key, OrderState.VALIDEE, reason=f"Porte : {gate.result}, politique : paper", now=now
        )
        if kill_switch_engaged(env.root):
            # R4: engaged since the policy read it; the order is cancelled, never sent.
            why = "arrêt d'urgence engagé avant l'envoi : jamais envoyé"
            env.book.transition(key, OrderState.ANNULEE, reason=why, now=now)
            return outcome(OrderState.ANNULEE, (*reasons, why))
        env.book.transition(key, OrderState.ENVOYEE, reason="envoyé au simulateur paper", now=now)
        try:
            ack = env.simulator.submit(booked, now=now)
        except NETWORK_ERRORS:
            # Arrived or not, nobody knows: the order stays ENVOYEE and is never sent again;
            # the next run tells, the simulator working it or the book letting it go.
            report.intents.append(outcome(OrderState.ENVOYEE, (*reasons, "envoi sans réponse")))
            raise
        state = OrderState.ENVOYEE
        if not ack.accepted:
            env.book.transition(key, OrderState.REJETEE, reason=clip(ack.reason, 200), now=now)
            state, reasons = OrderState.REJETEE, (*reasons, ack.reason)
    elif effect != "proposer":
        why = clip(f"Porte : {gate.result}, politique : {effect}", 200)
        env.book.transition(key, OrderState.REJETEE, reason=why, now=now)
        state = OrderState.REJETEE
    return outcome(state, reasons)


def _intents(env: PaperDay, facts: MarketFacts, account: Account, report: DayReport) -> None:
    """Each source's proposal, drafted and treated one intent at a time."""
    if not env.sources:
        return
    now = report.as_of
    _journal_call(
        env,
        {
            "tool": PRICE_TOOL,
            "call_id": PRICE_CALL,
            "as_of": utc_text(now),
            "instruments": sorted(facts.quotes),
            "gaps": sorted(facts.gaps),
        },
        now,
    )
    try:
        drafter = IntentDrafter(env.config.execution, env.config.risk_limits_paper, ids=env.ids)
    except DraftError as exc:
        report.notes.append(f"aucune intention rédigée : {exc}")
        return
    for source in env.sources:
        sizing = SizingSource(tool=source.tool, call_id=f"{source.tool}#1")
        try:
            proposal = source.propose(_snapshot(env, facts, account), day=report.day, sizing=sizing)
        except DraftError as exc:
            report.notes.append(f"{source.tool} : {exc}")
            continue
        _journal_call(
            env,
            {
                "tool": source.tool,
                "call_id": sizing.call_id,
                "orders": 0 if proposal is None else len(proposal.orders),
                "origin": None if proposal is None else proposal.origin.id,
            },
            now,
        )
        if proposal is None or not proposal.orders:
            report.notes.append(f"{source.tool} : aucun ordre proposé")
            continue
        try:
            drafted = drafter.draft(
                proposal.orders,
                _snapshot(env, facts, account),
                price_tool=PRICE_TOOL,
                price_call=PRICE_CALL,
                rationale=proposal.rationale,
                origin=proposal.origin,
            )
        except DraftError as exc:
            report.notes.append(f"{source.tool} : {exc}")
            continue
        for intent in drafted:  # each against the book as the previous one left it
            report.intents.append(_treat(env, intent, _snapshot(env, facts, account), report))


def _is_session(mics: set[str], day: date) -> bool:
    return not mics or any(session_close(mic, day) is not None for mic in mics)


def run_day(env: PaperDay, *, now: datetime) -> DayReport:
    """Treat the decision day of ``now`` once (module docstring). Never a past day (R10).

    A call the adapter does not answer stops the day where it is (``injoignable``): what was
    booked stays booked, nothing is sent again, and the next run reconciles first."""
    day = decision_day(now, env.config.research.execution.decision_cutoff_utc)
    report = DayReport(day=day, as_of=now, request_id=env.request_id)
    if env.log.done(day):
        report.outcome = "deja_traitee"
        return report
    try:
        return _run(env, report)
    except NETWORK_ERRORS as exc:  # the broker's text is not kept, only the kind of failure
        report.outcome = "injoignable"
        report.notes.append(f"adaptateur sans réponse ({type(exc).__name__})")
        return report


def _drafted_today(env: PaperDay, day: date) -> bool:
    return any(order.intent.decision_date == day for order in env.book.orders())


def _run(env: PaperDay, report: DayReport) -> DayReport:
    config, day, now = env.config, report.day, report.as_of
    status = detect(env.root, journal=env.journal, request_id=env.request_id, now=now)
    if status == "engaged":
        report.outcome = "arret"
        return report
    if status == "new_file":
        return _engage(env, report, "fichier", "fichier KILL trouvé au démarrage de la boucle")

    try:
        if not _close_sessions(env, report):
            report.outcome = "attente_donnees"
            return report
        report.reconciliation = settle(
            env.book,
            env.simulator,
            env.reconciliations,
            capital_eur=env.simulator.settings.capital_eur,
            now=now,
        )
        _follow_simulator(env, report)
    except ExecutionIncident as exc:
        return _engage(env, report, "incident_execution", f"{exc.kind} : {exc}")
    except _DataLoss as exc:
        return _engage(env, report, "perte_donnees", str(exc))

    statement = env.simulator.account_snapshot()
    exposed, read = _symbols(env, statement)
    volume_sessions = config.risk_limits_paper.avg_volume_sessions
    facts = market_facts(env.store, read, as_of=now, volume_sessions=volume_sessions)
    if not _is_session({f.mic for f in facts.instruments.values()}, day):
        report.outcome = "pas_de_seance"
        return report
    if isinstance(config.data_sources.quality.max_staleness_sessions, str):
        report.notes.append("max_staleness_sessions à définir : aucune intention (R7)")
    stale = _stale(env, facts, exposed)
    if stale:
        return _engage(env, report, "perte_donnees", "données absentes : " + ", ".join(stale))

    report.valuation = _valuation(statement, facts, day)
    env.log.record_valuation(report.valuation)
    report.account = _account(env, report.valuation, report)
    if report.account is not None:
        try:
            report.breaches = loss_breaches(report.account, config.risk_limits_paper)
        except ValueError as exc:
            report.notes.append(f"limites de perte inconnues : {exc} (R7)")
            report.account = None
    if report.breaches:
        trigger = report.breaches[0][0]
        return _engage(env, report, trigger, "; ".join(why for _, why in report.breaches))

    blocked = isinstance(config.data_sources.quality.max_staleness_sessions, str)
    if env.sources and local_date(now) != day:
        # An intent's session follows its Paris date: past midnight it would skip one.
        report.notes.append(
            "fenêtre de décision passée (minuit à Paris) : aucune intention, elle viserait "
            "une séance trop tard"
        )
        blocked = True
    if env.sources and not blocked and _drafted_today(env, day):
        # A day stopped after drafting and run again: its intents are in the book already.
        report.notes.append(
            "intentions déjà rédigées pour cette journée (reprise) : aucune nouvelle rédaction"
        )
        blocked = True
    if report.account is not None and not blocked:
        try:
            _intents(env, facts, report.account, report)
        except ExecutionIncident as exc:
            return _engage(env, report, "incident_execution", f"{exc.kind} : {exc}")
    return report


def finish_day(env: PaperDay, report: DayReport) -> str:
    """Write the day's report and, for a completed day, mark it treated. Returns the report;
    a day already treated keeps the report it was closed with."""
    text = render_report(report, env)
    if report.outcome == "deja_traitee":
        return text
    directory = default_reports_dir(env.root)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{report.day.isoformat()}.md").write_text(text, encoding="utf-8")
    if report.outcome == "terminee":
        env.log.record_run(
            report.day, completed_at=report.as_of, intents=len(report.intents), report=text
        )
    return text


# The report -------------------------------------------------------------------------------------


def _fr(value: Decimal, places: str = "0.01") -> str:
    """French figures: a space between thousands, a decimal comma."""
    quantized = value.quantize(Decimal(places))
    return f"{quantized:,}".replace(",", " ").replace(".", ",")


def _pct(part: Decimal, whole: Decimal) -> str:
    with localcontext() as ctx:
        ctx.prec = 60
        return _fr(part * 100 / whole) if whole else "n.d."


def _limit(value: float | str) -> str:
    return value if isinstance(value, str) else _fr(Decimal(str(value)))


def _sessions_section(env: PaperDay, report: DayReport) -> list[str]:
    lines = ["## Séances closes", "", "Source : simulateur paper, `close_session`.", ""]
    if not report.sessions:
        return [*lines, "Aucune séance close aujourd'hui.", ""]
    lines += [
        "| Séance | Ordre | Instrument | Sens | Quantité | Prix | Frais | Glissement (pb) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for session in report.sessions:
        for fill in session.fills:
            order = env.book.order(fill.intent_id)
            slip = slippage_bps([order])
            lines.append(
                f"| {session.session} | `{str(fill.intent_id)[:8]}` | "
                f"{order.intent.instrument.symbol} | {order.intent.side} | {fill.quantity} | "
                f"{_fr(fill.price)} {fill.currency} | {_fr(fill.fees)} {fill.currency} | "
                f"{'n.d.' if slip is None else _fr(slip)} |"
            )
    expired = [(s.session, i, why) for s in report.sessions for i, why in s.expired]
    if expired:
        lines += ["", "Ordres clos avec la séance :", ""]
        lines += [f"- {s} `{str(i)[:8]}` : {why}" for s, i, why in expired]
    return [*lines, ""]


def _account_section(env: PaperDay, report: DayReport) -> list[str]:
    lines = [
        "## Valorisation et limites",
        "",
        f"Source : relevé du simulateur paper et clôtures de `{PRICE_CALL}` ; limites de "
        "`risk_limits.paper.yaml`.",
        "",
    ]
    valuation, account = report.valuation, report.account
    if valuation is None:
        return [*lines, "Pas de valorisation aujourd'hui.", ""]
    limits = env.config.risk_limits_paper
    lines += [
        f"- Valeur liquidative : {_fr(valuation.equity_eur)} €",
        f"- Liquidités : {_fr(valuation.cash_eur)} €",
        "- Positions : "
        + (", ".join(f"{s} {q}" for s, q in valuation.positions.items()) or "aucune"),
    ]
    if account is not None:
        capital = Decimal(str(limits.capital_reference_eur))
        drawdown = account.peak_equity_eur - account.equity_eur
        lines += [
            f"- Résultat du jour : {_fr(account.day_pnl_eur)} € "
            f"({_pct(account.day_pnl_eur, capital)} % du capital ; perte maximale "
            f"{_limit(limits.max_daily_loss_pct)} %)",
            f"- Résultat sur {account.rolling_sessions} séances : "
            f"{_fr(account.rolling_pnl_eur)} € ({_pct(account.rolling_pnl_eur, capital)} % ; "
            f"perte maximale {_limit(limits.max_rolling_loss_pct)} %)",
            f"- Résultat cumulé : {_fr(account.equity_eur - capital)} € "
            f"({_pct(account.equity_eur - capital, capital)} %)",
            f"- Drawdown : {_pct(drawdown, account.peak_equity_eur)} % du plus haut "
            f"({_fr(account.peak_equity_eur)} €) ; maximum {_limit(limits.max_drawdown_pct)} %",
        ]
    today = sum(
        o.intent.decision_date == report.day
        for o in env.book.orders()
        if o.state not in (OrderState.INTENTION, OrderState.REJETEE)
    )
    lines.append(f"- Ordres du jour : {today} (maximum {_limit(limits.max_orders_per_day)})")
    return [*lines, ""]


def _intents_section(report: DayReport) -> list[str]:
    lines = ["## Intentions", "", "Source : Porte de risque (`evaluate`) et `decide_order`.", ""]
    if not report.intents:
        return [*lines, "Aucune intention aujourd'hui.", ""]
    lines += [
        "| Intention | Origine | Instrument | Sens | Demandé | Retenu | Porte | Politique | État |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for item in report.intents:
        lines.append(
            f"| `{str(item.intent_id)[:8]}` | {item.origin} | {item.symbol} | {item.side} | "
            f"{item.requested} | {item.quantity} | {item.gate} | {item.effect} | "
            f"{item.state.value} |"
        )
    refused = [item for item in report.intents if item.gate != "ACCEPTE" or item.reasons]
    if refused:
        lines += ["", "Raisons :", ""]
        for item in refused:
            lines += [f"- `{str(item.intent_id)[:8]}` : {why}" for why in item.reasons]
    return [*lines, ""]


def render_report(report: DayReport, env: PaperDay) -> str:
    """The day's report in French Markdown; every figure names where it comes from (R1)."""
    lines = [
        f"# Journée paper du {report.day:%d/%m/%Y}",
        "",
        f"- Issue : {OUTCOMES[report.outcome]}",
        f"- Instant : {utc_text(report.as_of)} (UTC)",
        f"- Requête : `{report.request_id}`",
        "",
        "## Kill switch",
        "",
    ]
    if report.stop is not None:
        stop = report.stop
        lines += [
            f"Engagé ({stop.trigger}) : {stop.reason}",
            f"Ordres annulés au carnet : {len(stop.cancelled)} ; non confirmés : "
            f"{len(stop.unconfirmed)}.",
        ]
    elif report.outcome == "arret":
        lines.append("Déjà engagé : rien n'est traité avant le réarmement par Lucas.")
    else:
        lines.append("Armé.")
    lines.append("")
    lines += _sessions_section(env, report)
    lines += ["## Réconciliation", "", "Source : `settle` (carnet contre relevé).", ""]
    if report.reconciliation is None:
        lines.append("Non faite aujourd'hui.")
    elif report.reconciliation.clean:
        lines.append(f"Propre ({report.reconciliation.fills} exécutions rejouées).")
    else:
        lines.append("ÉCARTS : " + ", ".join(report.reconciliation.assets()))
    if report.expired_in_book:
        lines.append(f"Ordres passés à ANNULEE au carnet : {len(report.expired_in_book)}.")
    lines.append("")
    lines += _account_section(env, report)
    lines += _intents_section(report)
    states = Counter(order.state.value for order in env.book.orders())
    lines += ["## Carnet", "", "Source : carnet d'ordres.", ""]
    lines += [f"- {state} : {count}" for state, count in sorted(states.items())] or ["- vide"]
    lines += [
        "",
        "## Non couvert",
        "",
        "- Écart paper/backtest de la stratégie et compteurs N2→N3 : B181.",
        "",
    ]
    if report.notes:
        lines += ["## Remarques", ""] + [f"- {note}" for note in report.notes] + [""]
    return "\n".join(lines)
