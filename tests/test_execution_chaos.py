"""Chaos on the paper loop (plan §12, ADR-033): network cut, missing data, duplicate order,
incoherent broker. Each test name starts with its family, which the execution eval counts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from core.execution.broker import AccountStatement, BrokerOrder, FillBatch
from core.execution.drafter import TargetOrder
from core.execution.intent import IntentOrigin, SizingSource
from core.execution.loop import Proposal, run_day
from core.execution.states import OrderState
from core.policy.engine import KILL_SWITCH_FILE
from core.risk_gate.snapshot import GateSnapshot
from tests.execution_cases import make_fill, make_intent
from tests.test_execution_loop import (
    MONDAY,
    MONDAY_RUN,
    RATIONALE,
    SYMBOL,
    TUESDAY,
    WEDNESDAY,
    World,
    bar,
    ingest,
    run_at,
)

LATER = timedelta(minutes=10)


def cut(*_: Any, **__: Any) -> Any:
    raise TimeoutError("délai dépassé")


def refused(*_: Any, **__: Any) -> Any:
    raise ConnectionError("connexion refusée")


@pytest.fixture
def world(tmp_path: Path) -> Any:
    built = World(tmp_path)
    yield built
    built.store.close()


def sent_on_monday(world: World) -> Any:
    world.run(MONDAY_RUN)
    [order] = world.book.orders()
    return order.intent


# Network cut ------------------------------------------------------------------------------------


def test_network_cut_before_the_order_arrives_never_sends_it_again(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []

    def lost(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        cut()

    monkeypatch.setattr(world.simulator, "submit", lost)
    report = world.run(MONDAY_RUN)
    assert report.outcome == "injoignable"
    assert "adaptateur sans réponse (TimeoutError)" in report.notes
    [intent] = report.intents
    assert intent.state == OrderState.ENVOYEE and "envoi sans réponse" in intent.reasons
    assert world.states() == [OrderState.ENVOYEE]
    assert world.simulator.open_orders() == ()
    assert not world.log.done(MONDAY)

    again = world.run(MONDAY_RUN + LATER)
    assert again.outcome == "terminee"
    assert world.states() == [OrderState.ANNULEE]  # never received: let go, not sent late
    assert again.expired_in_book == [intent.intent_id]
    assert any("(reprise)" in note for note in again.notes)
    assert again.reconciliation is not None and again.reconciliation.clean
    assert len(calls) == 1


def test_network_cut_after_the_order_arrives_keeps_one_order(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = world.simulator.submit

    def ack_lost(intent: Any, *, now: datetime) -> Any:
        real(intent, now=now)
        cut()

    monkeypatch.setattr(world.simulator, "submit", ack_lost)
    assert world.run(MONDAY_RUN).outcome == "injoignable"
    again = world.run(MONDAY_RUN + LATER)
    assert again.outcome == "terminee"
    assert world.states() == [OrderState.ENVOYEE]  # the simulator works it: it stays
    assert len(world.simulator.open_orders()) == 1

    ingest(world.store, TUESDAY, 100.2)
    tuesday = world.run(run_at(TUESDAY))
    assert world.states() == [OrderState.EXECUTEE]
    assert tuesday.reconciliation is not None and tuesday.reconciliation.clean


def test_network_cut_while_reading_the_fills_books_them_once_later(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent = sent_on_monday(world)
    ingest(world.store, TUESDAY, 100.2)
    real = world.simulator.fills_since
    monkeypatch.setattr(world.simulator, "fills_since", refused)
    report = world.run(run_at(TUESDAY))
    assert report.outcome == "injoignable"
    assert "adaptateur sans réponse (ConnectionError)" in report.notes
    assert world.states() == [OrderState.ENVOYEE]  # nothing booked from an unread batch

    monkeypatch.setattr(world.simulator, "fills_since", real)
    again = world.run(run_at(TUESDAY) + LATER)
    assert again.outcome == "terminee"
    assert world.book.order(intent.intent_id).filled == 4
    assert world.states() == [OrderState.EXECUTEE]
    assert again.reconciliation is not None and again.reconciliation.clean


def test_network_cut_while_reading_the_account_stops_the_day(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(world.simulator, "account_snapshot", refused)
    report = world.run(MONDAY_RUN)
    assert (report.outcome, report.intents, report.valuation) == ("injoignable", [], None)
    assert world.book.orders() == []
    assert not world.log.done(MONDAY)


def test_network_cut_during_a_stop_leaves_the_order_unconfirmed(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent = sent_on_monday(world)
    kill = tmp_path / KILL_SWITCH_FILE
    kill.parent.mkdir(parents=True)
    kill.write_text("arrêt manuel", encoding="utf-8")
    monkeypatch.setattr(world.simulator, "cancel_all", cut)
    monkeypatch.setattr(world.simulator, "cancel", cut)
    report = world.run(run_at(TUESDAY))
    assert report.outcome == "arret"
    assert report.stop is not None and report.stop.persisted
    assert report.stop.unconfirmed == (intent.intent_id,)
    assert not report.stop.clean
    assert world.states() == [OrderState.ENVOYEE]


# Missing data -----------------------------------------------------------------------------------


def holding_on_tuesday(world: World) -> None:
    world.run(MONDAY_RUN)
    ingest(world.store, TUESDAY, 100.2)
    world.run(run_at(TUESDAY))
    assert world.states() == [OrderState.EXECUTEE]


def test_missing_data_an_unreadable_close_of_a_holding_trips_the_kill_switch(
    world: World,
) -> None:
    holding_on_tuesday(world)
    ingest(world.store, WEDNESDAY, 100.1234567)  # beyond six decimals: not a price
    report = world.run(run_at(WEDNESDAY))
    assert report.outcome == "arret"
    assert report.stop is not None and report.stop.trigger == "perte_donnees"
    assert "aucun dernier cours exploitable" in report.stop.reason


def test_missing_data_a_close_ingested_after_now_is_not_read(world: World) -> None:
    world.run(MONDAY_RUN)
    published = run_at(TUESDAY) - timedelta(hours=3)
    world.store.ingest([bar(TUESDAY, 100.2, published)], ingested_at=run_at(TUESDAY) + LATER)
    report = world.run(run_at(TUESDAY))
    assert report.outcome == "attente_donnees"  # known later: never read before (R10)
    assert world.states() == [OrderState.ENVOYEE]


@dataclass
class Unknown:
    """A source that buys an instrument the store does not know."""

    tool: str = "unknown_source"

    def symbols(self) -> frozenset[str]:
        return frozenset({"FICT-NOPE"})

    def propose(
        self, snapshot: GateSnapshot, *, day: date, sizing: SizingSource
    ) -> Proposal | None:
        return Proposal(
            orders=(TargetOrder("FICT-NOPE", 3, sizing),),
            rationale=RATIONALE,
            origin=IntentOrigin(kind="strategy", id="croisement_mm"),
        )


def test_missing_data_an_instrument_without_a_price_drafts_nothing(tmp_path: Path) -> None:
    built = World(tmp_path)
    built.env.sources = (Unknown(),)
    report = built.run(MONDAY_RUN)
    assert (report.outcome, report.intents) == ("terminee", [])
    assert "unknown_source : FICT-NOPE : référentiel absent du snapshot de la Porte (R7)" in (
        report.notes
    )
    assert built.book.orders() == [] and built.simulator.open_orders() == ()
    built.store.close()


# Duplicate order --------------------------------------------------------------------------------


def test_duplicate_order_the_same_intent_twice_is_one_order(world: World) -> None:
    intent = sent_on_monday(world)
    ack = world.simulator.submit(intent, now=MONDAY_RUN + LATER)
    assert (ack.accepted, ack.duplicate) == (True, True)
    assert len(world.simulator.open_orders()) == 1


def test_duplicate_order_another_content_under_the_same_id_is_rejected(world: World) -> None:
    intent = sent_on_monday(world)
    ack = world.simulator.submit(intent.model_copy(update={"quantity": 3}), now=MONDAY_RUN)
    assert not ack.accepted and "autre contenu" in ack.reason
    [order] = world.simulator.open_orders()
    assert order.remaining == 4


def test_duplicate_order_a_day_run_again_drafts_no_second_intent(world: World) -> None:
    first = run_day(world.env, now=MONDAY_RUN)  # stopped before its report: not marked done
    assert first.outcome == "terminee" and not world.log.done(MONDAY)
    again = world.run(MONDAY_RUN + LATER)
    assert again.intents == []
    assert len(world.book.orders()) == 1 and len(world.simulator.open_orders()) == 1


def test_duplicate_order_a_fill_reported_twice_is_booked_once(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent = sent_on_monday(world)
    ingest(world.store, TUESDAY, 100.2)
    real = world.simulator.fills_since

    def twice(cursor: int) -> FillBatch:
        batch = real(cursor)
        return FillBatch(batch.fills * 2, batch.cursor)

    monkeypatch.setattr(world.simulator, "fills_since", twice)
    report = world.run(run_at(TUESDAY))
    assert report.outcome == "terminee"
    assert world.book.order(intent.intent_id).filled == 4
    assert report.reconciliation is not None and report.reconciliation.clean


# Incoherent broker ------------------------------------------------------------------------------


def test_incoherent_broker_a_fill_of_an_unknown_order_trips_the_kill_switch(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    stray = make_fill(make_intent(9), 0, 1)
    monkeypatch.setattr(world.simulator, "fills_since", lambda _: FillBatch((stray,), 1))
    report = world.run(MONDAY_RUN)
    assert report.outcome == "arret"
    assert report.stop is not None and report.stop.trigger == "incident_execution"
    assert report.stop.reason.startswith("ordre_inconnu : ")
    assert world.book.orders() == []


def test_incoherent_broker_a_fill_beyond_the_order_trips_the_kill_switch(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent = sent_on_monday(world)
    ingest(world.store, TUESDAY, 100.2)
    over = make_fill(intent, 9, 5)
    monkeypatch.setattr(world.simulator, "fills_since", lambda _: FillBatch((over,), 1))
    report = world.run(run_at(TUESDAY))
    assert report.stop is not None and report.stop.trigger == "incident_execution"
    assert report.stop.reason.startswith("quantite_depassee : ")
    assert world.book.order(intent.intent_id).filled == 0


def test_incoherent_broker_an_order_absent_from_the_book_trips_the_kill_switch(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    phantom = BrokerOrder(uuid4(), SYMBOL, "BUY", 1, Decimal("100"), MONDAY)
    monkeypatch.setattr(world.simulator, "open_orders", lambda: (phantom,))
    report = world.run(MONDAY_RUN)
    assert report.outcome == "arret"
    assert report.stop is not None and report.stop.trigger == "incident_execution"
    assert "absent du carnet" in report.stop.reason


def test_incoherent_broker_a_diverging_account_blocks_the_intents_without_a_stop(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    capital = world.simulator.settings.capital_eur
    short = AccountStatement(cash_eur=capital - Decimal(1))
    monkeypatch.setattr(world.simulator, "account_snapshot", lambda: short)
    report = world.run(MONDAY_RUN)
    assert (report.outcome, report.stop) == ("terminee", None)
    assert report.reconciliation is not None and not report.reconciliation.clean
    [intent] = report.intents
    assert (intent.gate, intent.state) == ("REFUSE", OrderState.REJETEE)
    assert "reconciliation : écart de réconciliation ouvert" in intent.reasons
    assert world.simulator.open_orders() == ()


def test_incoherent_broker_a_negative_position_trips_the_kill_switch(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    capital = world.simulator.settings.capital_eur
    impossible = AccountStatement(cash_eur=capital, positions={SYMBOL: -4})
    monkeypatch.setattr(world.simulator, "account_snapshot", lambda: impossible)
    report = world.run(MONDAY_RUN)
    assert report.stop is not None and report.stop.trigger == "incident_execution"
    assert "position nulle, négative ou fractionnaire" in report.stop.reason


def test_the_chaos_families_are_all_here() -> None:
    names = [name for name in globals() if name.startswith("test_")]
    for family in ("network_cut", "missing_data", "duplicate_order", "incoherent_broker"):
        assert sum(name.startswith(f"test_{family}_") for name in names) >= 3, family
