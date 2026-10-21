"""The paper loop's day (plan §10, ADR-033): sessions, reconciliation, valuation, intents."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from core.approvals.store import (
    ApprovalError,
    ApprovalRules,
    ApprovalState,
    ApprovalStore,
    Trail,
)
from core.approvals.totp import totp
from core.config.loader import AutonomyConfig, Config, load_config
from core.execution.book import Journal, OrderBook, Recorder
from core.execution.broker import AckCode, BrokerAck
from core.execution.drafter import TargetOrder
from core.execution.intent import IntentOrigin, IntentRationale, SizingSource
from core.execution.loop import (
    LoopError,
    LoopLog,
    PaperDay,
    Proposal,
    Valuation,
    default_loop_path,
    default_reports_dir,
    finish_day,
    run_day,
    send_approved,
    session_close,
)
from core.execution.paper import PaperSettings, PaperSimulator, SimulatorError
from core.execution.reconcile import ReconciliationLog
from core.execution.states import OrderState
from core.finance.calendars import exchange_calendar
from core.finance.model import CorporateAction, Instrument, PriceRow
from core.finance.store import FinanceStore
from core.policy.engine import KILL_SWITCH_FILE, kill_switch_engaged
from core.risk_gate.snapshot import GateSnapshot
from tests.execution_cases import MemoryJournal, make_intent
from tests.signing import sign
from tests.test_approvals_store import KEY
from tests.test_execution_intent import INJECTION
from tests.test_execution_paper import costs_config

REPO = Path(__file__).resolve().parents[1]
BASE = load_config(REPO / "config")
SYMBOL = "FICT-ACME"
MONDAY, TUESDAY, WEDNESDAY, THURSDAY = (date(2026, 10, d) for d in (19, 20, 21, 22))
MONDAY_RUN = datetime(2026, 10, 19, 21, 30, tzinfo=UTC)  # after the 21:00 UTC cut-off
LOADED = datetime(2026, 10, 19, 20, 0, tzinfo=UTC)
OPENED = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def run_at(day: date) -> datetime:
    return datetime.combine(day, MONDAY_RUN.timetz())


def config(level: str = "N2", **limits: Any) -> Config:
    """The repository's config, finance at ``level``, the test instrument in the universe, no
    personal exclusion and the simulator's test costs (the real ones are still A_DEFINIR)."""
    autonomy = BASE.autonomy.model_dump()
    autonomy["domains"]["finance"] = {"level": level, "max_level": "N4"}
    paper = BASE.risk_limits_paper.model_copy(update={"universe": [SYMBOL], **limits})
    risk = BASE.risk.model_copy(update={"trading_costs": costs_config()})
    return replace(
        BASE,
        autonomy=AutonomyConfig.model_validate(autonomy),
        risk_limits_paper=paper,
        risk=risk,
        compliance=BASE.compliance.model_copy(update={"exclusions_personnelles": []}),
    )


def sessions(first: date, last: date) -> list[tuple[date, datetime]]:
    calendar = exchange_calendar("XPAR", first.year, last.year)
    assert calendar is not None
    closes = calendar.closes
    return [
        (stamp.date(), close.to_pydatetime())
        for stamp, close in closes.items()
        if first <= stamp.date() <= last
    ]


def bar(session: date, close: float, published_at: datetime) -> PriceRow:
    return PriceRow(
        instrument_id=SYMBOL,
        session=session,
        close=close,
        volume=200_000,
        currency="EUR",
        source="fixtures",
        published_at=published_at,
    )


def ingest(store: FinanceStore, session: date, close: float) -> None:
    """The close of ``session``, published five minutes after it and ingested at once."""
    published = session_close("XPAR", session)
    assert published is not None
    published += timedelta(minutes=5)
    store.ingest([bar(session, close, published)], ingested_at=published)


def market(store: FinanceStore | None = None) -> FinanceStore:
    """Fifty sessions at 100.00 € up to Monday 19 October 2026, as known on Monday evening, in
    ``store`` or a new one in memory."""
    store = store or FinanceStore.memory()
    instrument = Instrument(
        instrument_id=SYMBOL,
        valid_from=date(2020, 1, 1),
        name="Acme fictive",
        asset_class="equity",
        currency="EUR",
        mic="XPAR",
        sector="Industrie",
        country="FR",
    )
    store.add_instrument(instrument, recorded_at=datetime(2020, 1, 1, tzinfo=UTC))
    rows = [
        bar(session, 100.0, close + timedelta(minutes=5))
        for session, close in sessions(MONDAY - timedelta(days=70), MONDAY)
    ]
    store.ingest(rows, ingested_at=LOADED)
    return store


RATIONALE = IntentRationale(
    thesis="Le titre fictif reste sous sa moyenne.",
    catalyst="Signal de la règle à la clôture.",
    invalidation="Clôture sous 90 €.",
    horizon_days=20,
    confidence=0.5,
)


@dataclass
class Fixed:
    """A source that buys ``quantity`` shares on the days given, and nothing on the others."""

    quantity: int = 4
    days: tuple[date, ...] = (MONDAY,)
    tool: str = "strategy.croisement_mm"

    def symbols(self) -> frozenset[str]:
        return frozenset({SYMBOL})

    def propose(
        self, snapshot: GateSnapshot, *, day: date, sizing: SizingSource
    ) -> Proposal | None:
        if day not in self.days:
            return None
        return Proposal(
            orders=(TargetOrder(SYMBOL, self.quantity, sizing),),
            rationale=RATIONALE,
            origin=IntentOrigin(kind="strategy", id="croisement_mm"),
        )


class World:
    def __init__(
        self,
        root: Path,
        cfg: Config | None = None,
        source: Fixed | None = None,
        journal: Journal | None = None,
    ) -> None:
        self.cfg = cfg or config()
        self.journal: Any = MemoryJournal() if journal is None else journal
        level = self.cfg.autonomy.domains["finance"].level
        if level != "N0":
            # ADR-036: the level the test sets is the one signed, before the days it runs (B240)
            sign(root, "finance", level, OPENED.date())
        settings = PaperSettings.from_config(
            self.cfg.risk_limits_paper, self.cfg.execution, self.cfg.risk.trading_costs
        )
        self.store = market()
        self.book = OrderBook.memory(Recorder(self.journal, "policy", "loop-test"))
        self.simulator = PaperSimulator.memory(settings, now=OPENED)
        self.log = LoopLog.memory()
        self.env = PaperDay(
            root=root,
            config=self.cfg,
            store=self.store,
            book=self.book,
            simulator=self.simulator,
            reconciliations=ReconciliationLog.memory(
                Recorder(self.journal, "scheduler", "loop-test")
            ),
            log=self.log,
            journal=self.journal,
            request_id="loop-test",
            sources=(source or Fixed(),),
        )

    def run(self, now: datetime) -> Any:
        report = run_day(self.env, now=now)
        finish_day(self.env, report)
        return report

    def states(self) -> list[OrderState]:
        return [order.state for order in self.book.orders()]


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    built = World(tmp_path)
    yield built
    built.store.close()


def test_the_loop_lives_in_var_paper(tmp_path: Path) -> None:
    assert default_loop_path(tmp_path) == tmp_path / "var" / "paper" / "loop.db"
    assert default_reports_dir(tmp_path) == tmp_path / "var" / "paper" / "reports"


def test_a_day_drafts_gates_and_sends_the_order_once(world: World, tmp_path: Path) -> None:
    report = world.run(MONDAY_RUN)
    assert (report.day, report.outcome) == (MONDAY, "terminee")
    [intent] = report.intents
    assert (intent.gate, intent.effect, intent.state) == ("ACCEPTE", "paper", OrderState.ENVOYEE)
    assert [order.intent_id for order in world.simulator.open_orders()] == [intent.intent_id]
    assert report.valuation.equity_eur == Decimal("10000.00")
    assert world.log.done(MONDAY)
    text = (default_reports_dir(tmp_path) / "2026-10-19.md").read_text(encoding="utf-8")
    assert "# Journée paper du 19/10/2026" in text
    assert "Valeur liquidative : 10 000,00 €" in text
    assert "Source : Porte de risque" in text
    policy = [e for e in world.journal.entries if e["event"] == "POLICY"]
    assert [e["actor"] for e in policy] == ["risk_gate", "policy"]
    assert {e["payload"]["intent_id"] for e in policy} == {str(intent.intent_id)}
    calls = [e["payload"]["call_id"] for e in world.journal.entries if e["event"] == "TOOL_CALL"]
    assert calls == ["paper_market#1", "strategy.croisement_mm#1"]

    again = world.run(MONDAY_RUN + timedelta(minutes=10))
    assert (again.outcome, again.intents) == ("deja_traitee", [])
    assert len(world.book.orders()) == 1
    kept = (default_reports_dir(tmp_path) / "2026-10-19.md").read_text(encoding="utf-8")
    assert kept == text


def test_the_next_day_closes_the_session_settles_and_values(world: World) -> None:
    world.run(MONDAY_RUN)
    ingest(world.store, TUESDAY, 100.2)
    report = world.run(run_at(TUESDAY))
    assert report.outcome == "terminee"
    [session] = report.sessions
    [fill] = session.fills
    assert (session.session, fill.quantity) == (TUESDAY, 4)
    assert world.states() == [OrderState.EXECUTEE]
    assert report.reconciliation is not None and report.reconciliation.clean
    statement = world.simulator.account_snapshot()
    assert report.valuation.positions == {SYMBOL: 4}
    assert report.valuation.equity_eur == statement.cash_eur + 4 * Decimal("100.20")
    assert report.account.day_pnl_eur == report.valuation.equity_eur - Decimal("10000.00")
    assert "strategy.croisement_mm : aucun ordre proposé" in report.notes


def test_the_losses_count_sessions_of_the_calendar_not_recorded_days(tmp_path: Path) -> None:
    built = World(tmp_path, config(rolling_loss_sessions=2))
    built.run(MONDAY_RUN)
    ingest(built.store, TUESDAY, 100.2)
    built.run(run_at(TUESDAY))
    ingest(built.store, WEDNESDAY, 101.0)  # no run on Wednesday
    ingest(built.store, THURSDAY, 102.0)
    report = built.run(run_at(THURSDAY))
    assert report.account is not None
    # Two sessions back is Tuesday's close, not Monday's (the second valuation back).
    assert report.account.rolling_pnl_eur == 4 * (Decimal("102.00") - Decimal("100.20"))
    assert report.account.day_pnl_eur == report.account.rolling_pnl_eur
    assert (
        "résultat du jour mesuré depuis le 20/10/2026 : valorisation de la séance du 21/10/2026 "
        "absente"
    ) in report.notes
    assert not [note for note in report.notes if note.startswith("résultat sur 2 séances")]


def test_an_order_whose_limit_is_not_reached_expires_in_the_book(world: World) -> None:
    world.run(MONDAY_RUN)
    ingest(world.store, TUESDAY, 101.0)  # above the 100.50 € limit of the buy
    report = world.run(run_at(TUESDAY))
    [session] = report.sessions
    assert (session.fills, len(session.expired)) == ((), 1)
    assert world.states() == [OrderState.ANNULEE]
    assert report.expired_in_book == [session.expired[0][0]]
    assert report.valuation.positions == {}


def test_a_close_not_ingested_yet_waits_for_the_data(world: World) -> None:
    world.run(MONDAY_RUN)
    waiting = world.run(run_at(TUESDAY))
    assert waiting.outcome == "attente_donnees"
    assert not world.log.done(TUESDAY)
    assert world.states() == [OrderState.ENVOYEE]
    ingest(world.store, TUESDAY, 100.2)
    assert world.run(run_at(TUESDAY) + timedelta(minutes=5)).outcome == "terminee"
    assert world.states() == [OrderState.EXECUTEE]


def test_a_close_missing_beyond_the_staleness_limit_trips_the_kill_switch(world: World) -> None:
    world.run(MONDAY_RUN)
    assert world.run(run_at(WEDNESDAY)).outcome == "attente_donnees"  # one session old
    report = world.run(run_at(THURSDAY))  # Tuesday's close, two sessions later
    assert report.outcome == "arret"
    assert report.stop is not None and report.stop.trigger == "perte_donnees"
    assert "clôture du 2026-10-20 absente pour FICT-ACME depuis 2 séances" in report.stop.reason


def staleness_to_define(world: World) -> None:
    sources = world.cfg.data_sources
    quality = sources.quality.model_copy(update={"max_staleness_sessions": "A_DEFINIR"})
    world.env.config = replace(
        world.cfg, data_sources=sources.model_copy(update={"quality": quality})
    )


def test_a_staleness_limit_to_define_is_the_strictest_for_a_missing_close(world: World) -> None:
    world.run(MONDAY_RUN)
    staleness_to_define(world)
    assert world.run(run_at(TUESDAY)).outcome == "attente_donnees"  # the close of the day
    report = world.run(run_at(WEDNESDAY))  # Tuesday's close, one session later
    assert report.outcome == "arret"
    assert report.stop is not None and report.stop.trigger == "perte_donnees"
    assert "clôture du 2026-10-20 absente pour FICT-ACME depuis 1 séances" in report.stop.reason


def test_a_staleness_limit_to_define_is_the_strictest_for_a_held_close(world: World) -> None:
    world.run(MONDAY_RUN)
    ingest(world.store, TUESDAY, 100.2)
    assert world.run(run_at(TUESDAY)).valuation.positions == {SYMBOL: 4}
    staleness_to_define(world)
    report = world.run(run_at(WEDNESDAY))  # Wednesday's close not ingested: one session old
    assert report.outcome == "arret"
    assert report.stop is not None and report.stop.trigger == "perte_donnees"
    assert f"{SYMBOL} (clôture vieille de 1 séances)" in report.stop.reason


def test_a_kill_file_stops_the_day_and_then_every_day(world: World, tmp_path: Path) -> None:
    kill = tmp_path / KILL_SWITCH_FILE
    kill.parent.mkdir(parents=True)
    kill.write_text("arrêt manuel", encoding="utf-8")
    report = world.run(MONDAY_RUN)
    assert report.outcome == "arret"
    assert report.stop is not None and report.stop.trigger == "fichier"
    assert (report.intents, world.book.orders()) == ([], [])
    again = world.run(MONDAY_RUN + timedelta(minutes=1))
    assert (again.outcome, again.stop) == ("arret", None)
    assert not world.log.done(MONDAY)


def test_a_kill_switch_engaged_after_the_decision_sends_nothing(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def engaged_then_killed(root: Path) -> bool:
        """The policy reads a free switch; a KILL file appears right after."""
        engaged = kill_switch_engaged(root)
        kill = root / KILL_SWITCH_FILE
        kill.parent.mkdir(parents=True, exist_ok=True)
        kill.write_text("arrêt manuel", encoding="utf-8")
        return engaged

    monkeypatch.setattr("core.execution.loop.kill_switch_engaged", engaged_then_killed)
    report = world.run(MONDAY_RUN)
    [outcome] = report.intents
    assert (outcome.effect, outcome.state) == ("paper", OrderState.ANNULEE)
    assert "arrêt d'urgence engagé avant l'envoi : jamais envoyé" in outcome.reasons
    assert world.states() == [OrderState.ANNULEE]
    assert world.simulator.open_orders() == ()
    assert (tmp_path / KILL_SWITCH_FILE).exists()


@pytest.mark.parametrize(
    ("code", "label"),
    [
        (AckCode.CASH_INSUFFISANT, "cash libre insuffisant, frais compris : pas de levier (D16)"),
        (AckCode.INCONNU, "refus du courtier (code inconnu)"),
    ],
)
def test_a_broker_refusal_is_recorded_in_our_words_never_the_brokers(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: AckCode, label: str
) -> None:
    """B197: the broker's text is external content; the book, the journal and the report
    keep the label of its code."""

    def refuse(intent: Any, *, now: datetime) -> BrokerAck:
        return BrokerAck(intent.intent_id, False, INJECTION, code=code)

    monkeypatch.setattr(world.simulator, "submit", refuse)
    report = world.run(MONDAY_RUN)
    [outcome] = report.intents
    assert outcome.state == OrderState.REJETEE
    assert outcome.reasons[-1] == label
    stored = world.book._conn.execute("SELECT reason FROM transitions").fetchall()
    assert label in [row["reason"] for row in stored]
    text = (default_reports_dir(tmp_path) / "2026-10-19.md").read_text(encoding="utf-8")
    assert label in text
    for written in ([row["reason"] for row in stored], text, world.journal.entries):
        assert INJECTION not in str(written)


def test_a_holding_without_a_fresh_close_trips_the_kill_switch(world: World) -> None:
    world.run(MONDAY_RUN)
    ingest(world.store, TUESDAY, 100.2)
    world.run(run_at(TUESDAY))
    report = world.run(run_at(THURSDAY))  # neither Wednesday's close nor Thursday's
    assert report.outcome == "arret"
    assert report.stop is not None and report.stop.trigger == "perte_donnees"
    assert "clôture vieille de 2 séances" in report.stop.reason


def test_a_daily_loss_beyond_the_limit_trips_the_kill_switch(world: World) -> None:
    world.run(MONDAY_RUN)
    ingest(world.store, TUESDAY, 100.0)
    world.run(run_at(TUESDAY))
    ingest(world.store, WEDNESDAY, 40.0)  # 4 × 60 € lost: 2.4 % of the capital in a day
    report = world.run(run_at(WEDNESDAY))
    assert report.outcome == "arret"
    assert report.stop is not None and report.stop.trigger == "limite"
    assert report.breaches[0][0] == "limite"


def test_at_n1_the_intent_stays_a_proposal(tmp_path: Path) -> None:
    built = World(tmp_path, config("N1"))
    report = built.run(MONDAY_RUN)
    [intent] = report.intents
    assert (intent.effect, intent.state) == ("proposer", OrderState.INTENTION)
    assert built.simulator.open_orders() == ()
    built.store.close()


APPROVAL_RULES = ApprovalRules(
    expiry=timedelta(minutes=10),
    max_code_attempts=3,
    lockout_failures=5,
    lockout_window=timedelta(minutes=15),
)


def test_at_n3_the_intent_waits_for_lucas_approval(tmp_path: Path) -> None:
    built = World(tmp_path, config("N3"))
    built.env.approvals = ApprovalStore.memory(APPROVAL_RULES, Trail(built.journal, "loop-test"))
    report = built.run(MONDAY_RUN)
    [intent] = report.intents
    assert (intent.effect, intent.state) == ("approbation", OrderState.INTENTION)
    assert built.simulator.open_orders() == ()
    booked = built.book.order(intent.intent_id).intent
    request = built.env.approvals.for_intent(intent.intent_id, now=MONDAY_RUN)
    assert request is not None
    assert (request.state, request.environment, request.intent_sha256) == (
        ApprovalState.DEMANDEE,
        "paper",
        booked.sha256(),
    )
    assert request.expires_at == MONDAY_RUN + timedelta(minutes=10)
    assert (request.gate["result"], request.gate["quantity"]) == ("ACCEPTE", intent.quantity)
    assert request.summary.startswith(f"Achat de {intent.quantity} {SYMBOL} à cours limité ")
    assert "origine : croisement_mm" in request.summary
    filed = [
        e for e in built.journal.entries if e["payload"].get("intent_id") == str(booked.intent_id)
    ]
    assert [e["actor"] for e in filed][:3] == ["risk_gate", "policy", "policy"]
    built.env.approvals.close()
    built.store.close()


def test_at_n3_without_an_approval_store_the_intent_is_rejected(tmp_path: Path) -> None:
    built = World(tmp_path, config("N3"))
    report = built.run(MONDAY_RUN)
    [intent] = report.intents
    assert (intent.effect, intent.state) == ("approbation", OrderState.REJETEE)
    assert intent.reasons[-1] == (
        "aucun registre des approbations : l'intention ne peut pas être soumise"
    )
    assert built.book.order(intent.intent_id).state == OrderState.REJETEE
    assert built.simulator.open_orders() == ()
    built.store.close()


def test_at_n3_a_request_the_store_refuses_rejects_the_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = World(tmp_path, config("N3"))
    built.env.approvals = ApprovalStore.memory(APPROVAL_RULES, Trail(built.journal, "loop-test"))

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise ApprovalError("intention déjà soumise : pas de seconde demande")

    monkeypatch.setattr(built.env.approvals, "request", refuse)
    report = built.run(MONDAY_RUN)
    [intent] = report.intents
    assert intent.state == OrderState.REJETEE
    assert intent.reasons[-1] == (
        "demande d'approbation refusée : intention déjà soumise : pas de seconde demande"
    )
    built.env.approvals.close()
    built.store.close()


def test_the_gate_reduces_an_order_beyond_the_order_limit(tmp_path: Path) -> None:
    built = World(tmp_path, source=Fixed(quantity=50))  # 5 000 € for a 5 % limit on 10 000 €
    report = built.run(MONDAY_RUN)
    [intent] = report.intents
    assert intent.gate == "REDUIT" and 0 < intent.quantity < 50
    [order] = built.simulator.open_orders()
    assert order.remaining == intent.quantity
    booked = built.book.order(intent.intent_id).intent
    assert booked.quantity == intent.quantity
    # ADR-031: the Gate's entry ties the intent drafted to the order booked.
    [gate] = [e["payload"] for e in built.journal.entries if e["actor"] == "risk_gate"]
    assert (gate["result"], gate["requested_quantity"], gate["quantity"]) == (
        "REDUIT",
        50,
        intent.quantity,
    )
    assert gate["booked_intent_sha256"] == booked.sha256() != gate["intent_sha256"]
    assert gate["reasons"] and gate["checks"]
    built.store.close()


def test_a_validated_order_never_sent_is_cancelled_not_sent_late(world: World) -> None:
    stuck = make_intent(0)
    world.book.record_intent(stuck, decision_price=Decimal("100"), reason="rédigée", now=LOADED)
    world.book.transition(stuck.intent_id, OrderState.VALIDEE, reason="validée", now=LOADED)
    report = world.run(MONDAY_RUN)
    assert world.book.order(stuck.intent_id).state == OrderState.ANNULEE
    assert stuck.intent_id in report.expired_in_book
    assert all(o.intent_id != stuck.intent_id for o in world.simulator.open_orders())


def announce_split(store: FinanceStore, ex_date: date, published_at: datetime) -> None:
    action = CorporateAction(
        instrument_id=SYMBOL,
        ex_date=ex_date,
        kind="split",
        value=2.0,
        source="fixtures",
        published_at=published_at,
    )
    store.ingest([action], ingested_at=published_at)


def test_a_split_known_at_its_session_doubles_the_position_and_reconciles(
    world: World, tmp_path: Path
) -> None:
    world.run(MONDAY_RUN)
    ingest(world.store, TUESDAY, 100.2)
    world.run(run_at(TUESDAY))
    announce_split(world.store, WEDNESDAY, run_at(TUESDAY) + timedelta(minutes=30))
    ingest(world.store, WEDNESDAY, 50.1)
    report = world.run(run_at(WEDNESDAY))
    assert (report.outcome, report.stop) == ("terminee", None)
    [action] = report.actions
    assert (action.session, action.kind, action.value) == (WEDNESDAY, "split", Decimal(2))
    assert report.valuation.positions == {SYMBOL: 8}
    assert report.reconciliation is not None and report.reconciliation.clean
    assert not kill_switch_engaged(tmp_path)
    text = (default_reports_dir(tmp_path) / "2026-10-21.md").read_text(encoding="utf-8")
    assert "## Opérations sur titres" in text
    assert "| FICT-ACME | split | 21/10/2026 | 21/10/2026 | 2 titre(s) pour 1 |" in text


def test_a_split_at_the_session_of_an_order_cancels_it_in_the_book(world: World) -> None:
    world.run(MONDAY_RUN)
    announce_split(world.store, TUESDAY, MONDAY_RUN + timedelta(minutes=15))
    ingest(world.store, TUESDAY, 50.1)
    report = world.run(run_at(TUESDAY))
    [order] = world.book.orders()
    assert order.state == OrderState.ANNULEE
    assert report.expired_in_book == [order.intent.intent_id]
    assert world.simulator.open_orders() == ()
    assert report.reconciliation is not None and report.reconciliation.clean
    assert report.valuation.positions == {}


def test_actions_the_simulator_cannot_book_are_a_note(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise SimulatorError("base en lecture seule")

    monkeypatch.setattr(world.simulator, "book_actions", refuse)
    report = world.run(MONDAY_RUN)
    assert report.outcome == "terminee"
    assert "opérations sur titres non comptabilisées : base en lecture seule" in report.notes


def test_past_midnight_in_paris_no_intent_is_drafted(world: World) -> None:
    report = world.run(datetime(2026, 10, 19, 22, 30, tzinfo=UTC))  # 00:30 on Tuesday in Paris
    assert (report.day, report.outcome, report.intents) == (MONDAY, "terminee", [])
    assert any("fenêtre de décision passée" in note for note in report.notes)


def test_a_day_without_a_session_treats_nothing(world: World) -> None:
    report = world.run(datetime(2026, 10, 24, 21, 30, tzinfo=UTC))  # a Saturday
    assert report.outcome == "pas_de_seance"
    assert not world.log.done(date(2026, 10, 24))


def test_an_unknown_universe_drafts_nothing(tmp_path: Path) -> None:
    built = World(tmp_path, config(universe="A_DEFINIR"))
    report = built.run(MONDAY_RUN)
    [intent] = report.intents
    assert (intent.gate, intent.state) == ("REFUSE", OrderState.REJETEE)
    assert built.simulator.open_orders() == ()
    [gate] = [e["payload"] for e in built.journal.entries if e["actor"] == "risk_gate"]
    assert (gate["quantity"], gate["booked_intent_sha256"]) == (0, None)
    built.store.close()


# The loop's log -------------------------------------------------------------------------------


def valuation(equity: str = "10000.00") -> Valuation:
    return Valuation(MONDAY, Decimal(equity), Decimal("10000.00"), {}, MONDAY_RUN)


def test_a_valuation_is_recorded_once_and_never_changed() -> None:
    log = LoopLog.memory()
    log.record_valuation(valuation())
    log.record_valuation(valuation())  # the same day stopped and run again
    with pytest.raises(LoopError, match="autre compte"):
        log.record_valuation(valuation("9999.00"))
    assert [v.equity_eur for v in log.valuations()] == [Decimal("10000.00")]


def test_the_log_persists_and_refuses_changes(tmp_path: Path) -> None:
    path = default_loop_path(tmp_path)
    with LoopLog.open(path) as log:
        log.record_valuation(valuation())
        log.record_run(MONDAY, completed_at=MONDAY_RUN, intents=1, report="# rapport")
    with LoopLog.open(path) as log:
        assert log.days() == [MONDAY]
        assert log.valuations()[0].valued_at == MONDAY_RUN
    conn = sqlite3.connect(path)
    for statement in ("UPDATE runs SET intents = 2", "DELETE FROM valuations"):
        with pytest.raises(sqlite3.IntegrityError, match="ne se réécrit pas"):
            conn.execute(statement)
    conn.close()


def test_a_session_close_is_known_only_for_a_session() -> None:
    close = session_close("XPAR", MONDAY)
    assert close is not None and close.tzinfo is not None
    assert session_close("XPAR", date(2026, 10, 24)) is None
    assert session_close("ZZZZ", MONDAY) is None


# Approved intents (ADR-036, D10) ---------------------------------------------------------------

GRANTED = MONDAY_RUN + timedelta(minutes=2)
SENDING = MONDAY_RUN + timedelta(minutes=3)


@contextmanager
def drafted_at_n3(tmp_path: Path, at: datetime = MONDAY_RUN) -> Iterator[tuple[World, UUID]]:
    """A day at N3 whose intent waits for Lucas's approval."""
    built = World(tmp_path, config("N3"))
    built.env.approvals = ApprovalStore.memory(APPROVAL_RULES, Trail(built.journal, "loop-test"))
    try:
        [intent] = built.run(at).intents
        yield built, intent.intent_id
    finally:
        built.env.approvals.close()
        built.store.close()


def approvals_of(built: World) -> ApprovalStore:
    assert built.env.approvals is not None
    return built.env.approvals


def grant(built: World, intent_id: UUID, at: datetime = GRANTED) -> UUID:
    """Lucas's right code, ``at``."""
    request = approvals_of(built).for_intent(intent_id, now=at)
    assert request is not None
    code = totp(KEY, at)
    assert approvals_of(built).approve(request.approval_id, code, key=KEY, now=at).accepted
    return request.approval_id


def test_an_approved_intent_is_sent_once_to_the_simulator(tmp_path: Path) -> None:
    with drafted_at_n3(tmp_path) as (built, intent_id):
        waiting = send_approved(built.env, now=SENDING)
        assert (waiting.outcome, waiting.sent) == ("terminee", [])  # Lucas has not answered
        assert built.book.order(intent_id).state == OrderState.INTENTION
        approval_id = grant(built, intent_id)
        report = send_approved(built.env, now=SENDING)
        assert (report.day, report.outcome) == (MONDAY, "terminee")
        [sent] = report.sent
        assert (sent.intent_id, sent.approval_id, sent.symbol, sent.quantity) == (
            intent_id,
            approval_id,
            SYMBOL,
            4,
        )
        assert (sent.approval, sent.state) == (ApprovalState.CONSOMMEE, OrderState.ENVOYEE)
        assert [order.intent_id for order in built.simulator.open_orders()] == [intent_id]
        reasons = [
            row["reason"] for row in built.book._conn.execute("SELECT reason FROM transitions")
        ]
        assert f"approbation {str(approval_id)[:8]} consommée : paper (D10)" in reasons[-2]
        again = [
            e
            for e in built.journal.entries
            if e["event"] == "POLICY" and e["payload"].get("approval_id") == str(approval_id)
        ]
        assert [e["actor"] for e in again] == ["risk_gate", "policy"]
        assert again[0]["payload"]["intent_sha256"] == built.book.order(intent_id).intent.sha256()

        later = send_approved(built.env, now=SENDING + timedelta(minutes=1))
        assert later.sent == [] and len(built.simulator.open_orders()) == 1


@pytest.mark.parametrize(
    "answer", [ApprovalState.REFUSEE, ApprovalState.EXPIREE, ApprovalState.CONSOMMEE]
)
def test_an_answer_other_than_a_grant_rejects_the_intent(
    tmp_path: Path, answer: ApprovalState
) -> None:
    with drafted_at_n3(tmp_path) as (built, intent_id):
        approvals, now = approvals_of(built), SENDING
        if answer is ApprovalState.REFUSEE:
            request = approvals.for_intent(intent_id, now=GRANTED)
            assert request is not None
            approvals.refuse(request.approval_id, reason="non", actor="lucas", now=GRANTED)
        elif answer is ApprovalState.EXPIREE:
            now = MONDAY_RUN + timedelta(minutes=11)
        else:  # consumed, yet the book still holds the intent: it is never sent twice
            sha = built.book.order(intent_id).intent.sha256()
            approvals.consume(grant(built, intent_id), intent_sha256=sha, now=GRANTED)
        [sent] = send_approved(built.env, now=now).sent
        why = {
            ApprovalState.REFUSEE: "approbation REFUSEE : jamais envoyée",
            ApprovalState.EXPIREE: "approbation EXPIREE : échéance passée, elle vaut refus : "
            "jamais envoyée",
            ApprovalState.CONSOMMEE: "approbation CONSOMMEE : déjà utilisée une fois : "
            "jamais envoyée",
        }[answer]
        assert (sent.approval, sent.state, sent.reasons) == (answer, OrderState.REJETEE, (why,))
        assert built.book.order(intent_id).state == OrderState.REJETEE
        assert built.simulator.open_orders() == ()


@pytest.mark.parametrize(
    ("limits", "result"),
    [({"universe": ["FICT-AUTRE"]}, "REFUSE"), ({"max_order_pct": 2}, "REDUIT")],
)
def test_a_gate_that_changed_its_mind_refuses_the_approval(
    tmp_path: Path, limits: dict[str, Any], result: str
) -> None:
    """D4: the approval is for the order the Gate accepted, not for another."""
    with drafted_at_n3(tmp_path) as (built, intent_id):
        approval_id = grant(built, intent_id)
        built.env.config = config("N3", **limits)
        [sent] = send_approved(built.env, now=SENDING).sent
        assert (sent.approval, sent.state) == (ApprovalState.REFUSEE, OrderState.REJETEE)
        assert sent.reasons[-1].startswith(f"Porte réévaluée : {result}, ")
        assert sent.reasons[-1].endswith(" au lieu des 4 approuvés : approbation refusée (D4)")
        state = approvals_of(built).get(approval_id, now=SENDING).state
        assert state is ApprovalState.REFUSEE
        assert built.simulator.open_orders() == ()


def test_a_lowered_level_refuses_the_approval(tmp_path: Path) -> None:
    with drafted_at_n3(tmp_path) as (built, intent_id):
        grant(built, intent_id)
        built.env.config = config("N2")
        [sent] = send_approved(built.env, now=SENDING).sent
        assert (sent.approval, sent.state) == (ApprovalState.REFUSEE, OrderState.REJETEE)
        assert sent.reasons[-1] == "politique : paper au lieu d'approbation : approbation refusée"
        assert built.simulator.open_orders() == ()


@pytest.mark.parametrize("answered_elsewhere", [False, True])
def test_an_approval_is_never_sent_past_midnight_in_paris(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answered_elsewhere: bool
) -> None:
    """R10: the decision belongs to its day; at 00:01 in Paris, it is no longer sent."""
    late = datetime(2026, 10, 19, 21, 55, tzinfo=UTC)  # 23:55 in Paris
    with drafted_at_n3(tmp_path, late) as (built, intent_id):
        grant(built, intent_id, late + timedelta(minutes=2))
        if answered_elsewhere:  # the refusal comes too late: the state is read back

            def answered(*_: Any, **__: Any) -> None:
                raise ApprovalError("approbation déjà traitée")

            monkeypatch.setattr(approvals_of(built), "refuse", answered)
        [sent] = send_approved(built.env, now=late + timedelta(minutes=6)).sent
        assert sent.reasons == (
            "approbation hors de sa journée de décision : jamais envoyée (R10)",
        )
        approval = ApprovalState.ACCORDEE if answered_elsewhere else ApprovalState.REFUSEE
        assert (sent.approval, sent.state) == (approval, OrderState.REJETEE)
        assert built.simulator.open_orders() == ()


@pytest.mark.parametrize("trigger", ["fichier", "perte_donnees"])
def test_a_stop_before_sending_refuses_every_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trigger: str
) -> None:
    with drafted_at_n3(tmp_path) as (built, intent_id):
        approval_id = grant(built, intent_id)
        if trigger == "fichier":
            kill = tmp_path / KILL_SWITCH_FILE
            kill.parent.mkdir(parents=True, exist_ok=True)
            kill.write_text("arrêt manuel", encoding="utf-8")
        else:
            monkeypatch.setattr("core.execution.loop._stale", lambda *_: [f"{SYMBOL} : périmé"])
        report = send_approved(built.env, now=SENDING)
        assert report.outcome == "arret" and report.sent == []
        assert report.stop is not None and report.stop.trigger == trigger
        assert report.stop.approvals_refused == (approval_id,)
        state = approvals_of(built).get(approval_id, now=SENDING).state
        assert state is ApprovalState.REFUSEE
        assert built.simulator.open_orders() == ()
        again = send_approved(built.env, now=SENDING + timedelta(minutes=1))
        assert (again.outcome, again.stop, again.sent) == ("arret", None, [])


def test_a_kill_switch_engaged_after_the_policy_sends_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def engaged_then_killed(root: Path) -> bool:
        engaged = kill_switch_engaged(root)
        kill = root / KILL_SWITCH_FILE
        kill.parent.mkdir(parents=True, exist_ok=True)
        kill.write_text("arrêt manuel", encoding="utf-8")
        return engaged

    with drafted_at_n3(tmp_path) as (built, intent_id):
        grant(built, intent_id)
        monkeypatch.setattr("core.execution.loop.kill_switch_engaged", engaged_then_killed)
        [sent] = send_approved(built.env, now=SENDING).sent
        assert (sent.approval, sent.state) == (ApprovalState.CONSOMMEE, OrderState.ANNULEE)
        assert sent.reasons[-1] == "arrêt d'urgence engagé avant l'envoi : jamais envoyé"
        assert built.simulator.open_orders() == ()


def test_a_send_without_answer_is_reported_and_kept_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with drafted_at_n3(tmp_path) as (built, intent_id):
        grant(built, intent_id)

        def silent(intent: Any, *, now: datetime) -> BrokerAck:
            raise TimeoutError(INJECTION)

        monkeypatch.setattr(built.simulator, "submit", silent)
        report = send_approved(built.env, now=SENDING)
        assert report.outcome == "injoignable"
        assert report.notes == ["adaptateur sans réponse (TimeoutError)"]
        [sent] = report.sent
        assert (sent.approval, sent.state) == (ApprovalState.CONSOMMEE, OrderState.ENVOYEE)
        assert sent.reasons[-1] == "envoi sans réponse"
        assert built.book.order(intent_id).state == OrderState.ENVOYEE
        assert INJECTION not in str(report) + str(built.journal.entries)


def test_an_approval_that_cannot_be_consumed_rejects_the_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with drafted_at_n3(tmp_path) as (built, intent_id):
        grant(built, intent_id)

        def mismatch(*_: Any, **__: Any) -> None:
            raise ApprovalError("empreinte différente de l'intention approuvée")

        monkeypatch.setattr(approvals_of(built), "consume", mismatch)
        [sent] = send_approved(built.env, now=SENDING).sent
        assert (sent.approval, sent.state) == (ApprovalState.ACCORDEE, OrderState.REJETEE)
        assert sent.reasons[-1] == (
            "approbation non consommée : empreinte différente de l'intention approuvée"
        )
        assert built.simulator.open_orders() == ()


def test_without_an_account_an_approval_waits_unspent(tmp_path: Path) -> None:
    with drafted_at_n3(tmp_path) as (built, intent_id):
        approval_id = grant(built, intent_id)
        built.env.config = config("N3", capital_reference_eur="A_DEFINIR")
        report = send_approved(built.env, now=SENDING)
        assert report.sent == [] and report.account is None
        assert "capital de référence ou séances de perte glissante à définir (R7)" in report.notes
        state = approvals_of(built).get(approval_id, now=SENDING).state
        assert state is ApprovalState.ACCORDEE


def test_without_an_approval_store_nothing_is_sent(world: World) -> None:
    report = send_approved(world.env, now=SENDING)
    assert (report.outcome, report.sent) == ("terminee", [])
    assert report.notes == ["aucun registre des approbations : rien à envoyer"]
