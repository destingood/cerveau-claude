"""The kill switch (R4, ADR-034): engage, detect, rearm, the loss triggers and the CLI.

Everything happens under ``tmp_path``: no test touches the real ``governance/kill_switch/KILL``.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from hypothesis import HealthCheck, given, settings
from typer.testing import CliRunner

from core.approvals.store import ApprovalError, ApprovalRules, ApprovalState, ApprovalStore, Trail
from core.approvals.store import default_store_path as approvals_path
from core.approvals.totp import totp
from core.audit import AuditJournal
from core.config import load_config
from core.config.loader import PaperRiskLimits
from core.execution import kill_switch as ks
from core.execution.book import OrderBook, Recorder, default_book_path
from core.execution.broker import BrokerOrder
from core.execution.kill_switch import (
    REARM_PHRASE,
    KillSwitchEngaged,
    KillSwitchError,
    Recorded,
    Stop,
    detect,
    engage,
    incidents_dir,
    loss_breaches,
    rearm,
    recorded_stop,
    state_path,
)
from core.execution.paper import PaperSettings, PaperSimulator, default_simulator_path
from core.execution.states import ExecutionIncident
from core.execution.states import OrderState as S
from core.finance.model import utc_text
from core.policy.engine import KILL_SWITCH_FILE, decide_order, kill_switch_engaged
from core.risk_gate.gate import UNKNOWN, evaluate
from core.risk_gate.snapshot import Account
from interfaces.cli.main import app
from tests.conftest import REPO_ROOT
from tests.execution_cases import DECISION_PRICE, MemoryJournal, make_intent
from tests.risk_gate.cases import Case, base_world, cases
from tests.test_approvals_store import KEY, RULES, ask
from tests.test_execution_book import sent
from tests.test_execution_paper import OPENED, SETTINGS, SUBMITTED, simulator, weekdays

NOW = datetime(2026, 10, 21, 14, 30, tzinfo=UTC)
runner = CliRunner()


# --- helpers ----------------------------------------------------------------------------------


class Clock:
    """A monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Broker:
    """A scripted adapter: each answer in turn, an exception raised; every call recorded."""

    def __init__(
        self,
        *,
        cancel_all: Sequence[tuple[UUID, ...] | Exception] = ((),),
        working: Sequence[UUID] | Exception = (),
        cancel: Mapping[UUID, Sequence[bool | Exception]] | None = None,
        on_call: Callable[[], None] = lambda: None,
    ) -> None:
        self._all = list(cancel_all)
        self._working = working
        self._cancel = {key: list(answers) for key, answers in (cancel or {}).items()}
        self._on_call = on_call
        self.calls: list[str] = []

    def _called(self, name: str) -> None:
        self.calls.append(name)
        self._on_call()

    def cancel_all(self, *, reason: str, now: datetime) -> tuple[UUID, ...]:
        self._called("cancel_all")
        answer = self._all.pop(0) if self._all else ()
        if isinstance(answer, Exception):
            raise answer
        return answer

    def open_orders(self) -> tuple[BrokerOrder, ...]:
        self._called("open_orders")
        if isinstance(self._working, Exception):
            raise self._working
        return tuple(
            BrokerOrder(key, "FICT-ACME", "BUY", 10, Decimal("123.45"), date(2026, 10, 21))
            for key in self._working
        )

    def cancel(self, intent_id: UUID, *, reason: str, now: datetime) -> bool:
        self._called(f"cancel {intent_id}")
        answers = self._cancel.get(intent_id, [])
        answer = answers.pop(0) if answers else False
        if isinstance(answer, Exception):
            raise answer
        return answer


class Refusing:
    """A journal that refuses every entry."""

    def append(self, **_: Any) -> dict[str, Any]:
        raise OSError("disque plein")


def stopped(root: Path, **changes: Any) -> Stop:
    args: dict[str, Any] = {
        "trigger": "commande",
        "reason": "essai",
        "journal": MemoryJournal(),
        "actor": "lucas",
        "request_id": "kill-test",
        "now": NOW,
        "target_seconds": 5.0,
    } | changes
    return engage(root, **args)


def booked(journal: Any) -> OrderBook:
    return OrderBook.memory(Recorder(journal=journal, actor="lucas", request_id="kill-test"))


def validated(book: OrderBook, n: int) -> UUID:
    """The n-th order, VALIDEE: accepted by the Gate, not sent yet."""
    intent = make_intent(n)
    book.record_intent(intent, decision_price=DECISION_PRICE, reason="intention rédigée")
    book.transition(intent.intent_id, S.VALIDEE, reason="Porte de risque : ACCEPT")
    return intent.intent_id


def sent_order(book: OrderBook, n: int) -> UUID:
    intent = make_intent(n)
    sent(book, intent)
    return intent.intent_id


def kills(journal: MemoryJournal) -> list[dict[str, Any]]:
    return [e["payload"] for e in journal.entries if e["event"] == "KILL"]


# --- engage -----------------------------------------------------------------------------------


def test_the_paths_live_under_var_incidents(tmp_path: Path) -> None:
    assert incidents_dir(tmp_path) == tmp_path / "var" / "incidents"
    assert state_path(tmp_path) == tmp_path / "var" / "incidents" / "kill_switch.json"


def test_a_stop_cancels_every_open_order_and_reports_what_is_unconfirmed(tmp_path: Path) -> None:
    journal = MemoryJournal()
    book, sim = booked(journal), simulator()
    working = sent_order(book, 0)
    assert sim.submit(make_intent(0), now=SUBMITTED).accepted
    never_sent = validated(book, 1)
    lost = sent_order(book, 2)  # sent, but the simulator never got it
    before = len(journal.entries)

    stop = stopped(tmp_path, journal=journal, adapter=sim, book=book)

    assert stop.broker_cancelled == (working,)
    assert stop.cancelled == tuple(sorted((working, never_sent)))
    assert (stop.unconfirmed, stop.unknown, stop.errors) == ((lost,), (), ())
    assert stop.persisted and not stop.clean and stop.within_target
    assert kill_switch_engaged(tmp_path)
    assert sim.open_orders() == ()
    states = {key: book.order(key).state for key in (working, never_sent, lost)}
    assert states == {working: S.ANNULEE, never_sent: S.ANNULEE, lost: S.ENVOYEE}

    entries = journal.entries[before:]
    assert [e["event"] for e in entries] == ["KILL", "ORDER_STATE", "KILL"]
    assert {e["actor"] for e in entries} == {"lucas"}
    assert entries[0]["payload"] == {
        "kill_switch": "declenchement",
        "trigger": "commande",
        "reason": "essai",
    }
    moved = entries[1]["payload"]
    assert moved["state"] == "ANNULEE" and moved["reason"] == "kill switch (commande)"
    assert [order["intent_id"] for order in moved["orders"]] == [str(k) for k in stop.cancelled]
    arret = entries[2]["payload"]
    assert arret.pop("elapsed_ms") >= 0
    assert arret == {  # counts and ids, never an amount
        "kill_switch": "arret",
        "trigger": "commande",
        "persisted": True,
        "broker_cancelled": 1,
        "cancelled": 2,
        "unconfirmed": [str(lost)],
        "unknown": [],
        "approvals_refused": 0,
        "errors": 0,
        "target_s": 5.0,
        "within_target": True,
    }

    state = json.loads(state_path(tmp_path).read_text(encoding="utf-8"))
    assert state == {
        "engaged_at": utc_text(NOW),
        "trigger": "commande",
        "report": stop.report.name if stop.report else None,
        "unconfirmed": [str(lost)],
    }
    assert stop.report == incidents_dir(tmp_path) / "20261021T143000Z-commande.md"
    report = stop.report.read_text(encoding="utf-8")
    assert report.startswith("# Kill switch — arrêt du 21/10/2026 à 14:30:00 (UTC)")
    assert "dans la cible de 5 s" in report
    assert "**Annulation non confirmée (alerte)** : 1\n  - `" + str(lost) in report
    assert "## Erreurs\n\n- Aucune." in report
    assert "- Demandes ouvertes passées à REFUSEE : 0" in report
    assert not any(word in report for word in ("123,45", "123.45", "EUR", "€"))


def test_a_stop_refuses_every_open_approval(tmp_path: Path) -> None:
    journal = MemoryJournal()
    with ApprovalStore.memory(RULES, Trail(journal, "kill-test")) as approvals:
        waiting, granted, refused = (ask(approvals, now=NOW) for _ in range(3))
        assert approvals.approve(granted, totp(KEY, NOW), key=KEY, now=NOW).accepted
        approvals.refuse(refused, reason="non", actor="lucas", now=NOW)
        stop = stopped(tmp_path, journal=journal, approvals=approvals)
        states = {key: approvals.get(key, now=NOW).state for key in (waiting, granted, refused)}
    assert sorted(stop.approvals_refused) == sorted((waiting, granted))
    assert set(states.values()) == {ApprovalState.REFUSEE}
    assert stop.clean and kills(journal)[-1]["approvals_refused"] == 2
    assert stop.report is not None
    assert "- Demandes ouvertes passées à REFUSEE : 2" in stop.report.read_text(encoding="utf-8")


def test_an_approval_store_that_fails_never_holds_the_stop(tmp_path: Path) -> None:
    class Broken:
        def refuse_open(self, **_: Any) -> tuple[UUID, ...]:
            raise sqlite3.OperationalError("database is locked")

    stop = stopped(tmp_path, approvals=Broken())
    assert stop.persisted and kill_switch_engaged(tmp_path) and stop.approvals_refused == ()
    assert stop.errors == (
        "approbations ouvertes non refusées : OperationalError (database is locked)",
    )


def test_a_project_without_paper_account_stops_cleanly(tmp_path: Path) -> None:
    stop = stopped(tmp_path)
    assert stop.clean and stop.cancelled == () and stop.broker_cancelled == ()
    assert (tmp_path / KILL_SWITCH_FILE).read_text(encoding="utf-8") == (
        f"declencheur: commande\nle: {utc_text(NOW)}\n"
    )


@pytest.mark.parametrize("with_book", [True, False])
def test_a_confirmed_cancellation_unknown_to_the_book_is_an_alert(
    tmp_path: Path, with_book: bool
) -> None:
    stray = make_intent(7).intent_id
    book = booked(MemoryJournal()) if with_book else None
    stop = stopped(tmp_path, adapter=Broker(cancel_all=[(stray,)]), book=book)
    assert stop.unknown == (stray,) and not stop.clean
    assert stop.report is not None
    assert f"absents des ordres ouverts du carnet (alerte)** : 1\n  - `{stray}`" in (
        stop.report.read_text(encoding="utf-8")
    )


def test_cancel_all_is_tried_again_and_the_broker_text_is_not_kept(tmp_path: Path) -> None:
    book = booked(MemoryJournal())
    order = sent_order(book, 0)
    adapter = Broker(cancel_all=[TimeoutError("réponse du courtier : compte 1234"), (order,)])
    stop = stopped(tmp_path, adapter=adapter, book=book)
    assert adapter.calls == ["cancel_all", "cancel_all", "open_orders"]
    assert stop.cancelled == (order,)
    assert stop.errors == ("courtier, tout annuler, essai 1 : TimeoutError",)


def test_an_unreachable_broker_leaves_every_open_order_unconfirmed(tmp_path: Path) -> None:
    book = booked(MemoryJournal())
    orders = {sent_order(book, 0), validated(book, 1)}  # VALIDEE may have been sent: unknown
    adapter = Broker(cancel_all=[ConnectionError("x")] * 3, working=ConnectionError("y"))
    stop = stopped(tmp_path, adapter=adapter, book=book)
    assert set(stop.unconfirmed) == orders and stop.cancelled == ()
    assert stop.errors == (
        "courtier, tout annuler, essai 1 : ConnectionError",
        "courtier, tout annuler, essai 2 : ConnectionError",
        "courtier, tout annuler, essai 3 : ConnectionError",
        "courtier, ordres ouverts : ConnectionError",
    )


def test_orders_still_worked_are_cancelled_one_by_one(tmp_path: Path) -> None:
    book = booked(MemoryJournal())
    late, stubborn, refused = (sent_order(book, n) for n in range(3))
    adapter = Broker(
        working=(late, stubborn, refused),
        cancel={late: [OSError(), True], stubborn: [OSError()] * 3, refused: [False]},
    )
    stop = stopped(tmp_path, adapter=adapter, book=book)
    assert stop.cancelled == (late,)
    assert set(stop.unconfirmed) == {stubborn, refused}
    assert stop.errors == (
        f"courtier, annuler {late}, essai 1 : OSError",
        *(f"courtier, annuler {stubborn}, essai {n} : OSError" for n in (1, 2, 3)),
    )


def test_the_calls_stop_at_the_target_but_the_first(tmp_path: Path) -> None:
    clock = Clock()
    book = booked(MemoryJournal())
    order = validated(book, 0)

    def slow() -> None:
        clock.now += 3

    adapter = Broker(cancel_all=[TimeoutError()] * 3, on_call=slow)
    stop = stopped(tmp_path, adapter=adapter, book=book, clock=clock)
    assert adapter.calls == ["cancel_all", "cancel_all"]  # at 0 s and 3 s; 6 s is past 5 s
    assert stop.unconfirmed == (order,)
    assert stop.errors[-1] == "cible atteinte : 2 appel(s) au courtier non tenté(s)"
    assert (stop.elapsed_s, stop.within_target) == (6.0, False)
    assert stop.report is not None
    assert "Durée mesurée : 6 s, AU-DELÀ de la cible de 5 s" in stop.report.read_text("utf-8")


def test_a_cancellation_past_the_target_is_not_tried(tmp_path: Path) -> None:
    clock = Clock()
    book = booked(MemoryJournal())
    order = sent_order(book, 0)

    def slow() -> None:
        clock.now += 3

    adapter = Broker(working=(order,), cancel={order: [True]}, on_call=slow)
    stop = stopped(tmp_path, adapter=adapter, book=book, clock=clock)
    assert adapter.calls == ["cancel_all", "open_orders"]
    assert stop.unconfirmed == (order,)
    assert stop.errors == ("cible atteinte : 1 appel(s) au courtier non tenté(s)",)


def test_without_a_target_every_attempt_is_made(tmp_path: Path) -> None:
    clock = Clock()

    def slow() -> None:
        clock.now += 100

    adapter = Broker(cancel_all=[TimeoutError()] * 3, on_call=slow)
    stop = stopped(tmp_path, adapter=adapter, clock=clock, target_seconds=None)
    assert adapter.calls == ["cancel_all"] * 3 + ["open_orders"]
    assert stop.within_target is None
    assert stop.report is not None
    assert "cible à définir (R7)" in stop.report.read_text(encoding="utf-8")


def test_what_the_caller_could_not_open_is_reported(tmp_path: Path) -> None:
    stop = stopped(tmp_path, unavailable=["carnet d'ordres\nnon ouvert (DatabaseError)"])
    assert stop.errors == ("carnet d'ordres non ouvert (DatabaseError)",)
    assert not stop.clean and stop.persisted


def test_a_book_that_refuses_the_move_keeps_every_order_open(tmp_path: Path) -> None:
    journal = MemoryJournal()
    book = booked(journal)
    order = validated(book, 0)
    journal.fail_at = journal.calls + 2  # the KILL entry passes, the book's entry is refused
    stop = stopped(tmp_path, journal=journal, adapter=Broker(), book=book)
    assert book.order(order).state is S.VALIDEE
    assert stop.cancelled == () and stop.unconfirmed == (order,)
    assert stop.errors == ("carnet d'ordres, passage à ANNULEE : OSError (journal indisponible)",)


def test_an_unreadable_book_is_reported(tmp_path: Path) -> None:
    book = booked(MemoryJournal())
    book.close()
    stop = stopped(tmp_path, book=book)
    assert stop.errors == (
        "carnet d'ordres illisible : ProgrammingError (Cannot operate on a closed database.)",
    )


def test_a_kill_file_that_cannot_be_created_is_reported(tmp_path: Path) -> None:
    (tmp_path / KILL_SWITCH_FILE).parent.parent.mkdir()
    (tmp_path / KILL_SWITCH_FILE).parent.write_text("un fichier à la place du dossier")
    stop = stopped(tmp_path)
    assert not stop.persisted and not stop.clean
    assert stop.errors[0].startswith("fichier KILL non créé : l'arrêt ne survit pas au processus")
    assert not state_path(tmp_path).exists()
    assert stop.report is not None
    assert "NON CRÉÉ : l'arrêt ne survit pas au processus" in stop.report.read_text("utf-8")


def test_an_engaged_switch_is_left_as_it_is(tmp_path: Path) -> None:
    kill = tmp_path / KILL_SWITCH_FILE
    kill.parent.mkdir(parents=True)
    kill.write_text("posé à la main\n", encoding="utf-8")
    first, second = stopped(tmp_path), stopped(tmp_path, trigger="limite")
    assert first.clean and second.clean
    assert kill.read_text(encoding="utf-8") == "posé à la main\n"
    assert first.report is not None and second.report is not None
    assert (first.report.name, second.report.name) == (
        "20261021T143000Z-commande.md",
        "20261021T143000Z-limite.md",
    )
    assert stopped(tmp_path).report == first.report.with_name("20261021T143000Z-commande-2.md")


def test_a_journal_that_refuses_never_prevents_the_stop(tmp_path: Path) -> None:
    stop = stopped(tmp_path, journal=Refusing())
    assert stop.persisted and state_path(tmp_path).is_file()
    assert stop.errors == (
        "journal, entrée declenchement : OSError (disque plein)",
        "journal, entrée arret : OSError (disque plein)",
    )
    assert stop.report is not None
    assert "- journal, entrée arret : OSError (disque plein)" in stop.report.read_text("utf-8")


def test_a_report_and_a_state_that_cannot_be_written_are_reported(tmp_path: Path) -> None:
    incidents_dir(tmp_path).parent.mkdir()
    incidents_dir(tmp_path).write_text("un fichier à la place du dossier")
    stop = stopped(tmp_path)
    assert stop.report is None and stop.persisted
    assert [error.split(" : ")[0] for error in stop.errors] == [
        "rapport d'incident non créé",
        "état du kill switch non écrit",
    ]


def test_a_report_whose_text_cannot_be_written_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(stop: Stop) -> str:
        raise OSError("disque plein")

    monkeypatch.setattr(ks, "render_report", broken)
    stop = stopped(tmp_path)
    assert stop.errors == ("rapport non écrit : OSError (disque plein)",)
    assert stop.report is not None and stop.report.read_text(encoding="utf-8") == ""


def test_reports_are_never_overwritten(tmp_path: Path) -> None:
    directory = tmp_path / "incidents"
    assert ks._reserve_report(directory, "commande", NOW).name == "20261021T143000Z-commande.md"
    assert ks._reserve_report(directory, "commande", NOW).name == "20261021T143000Z-commande-2.md"
    for index in range(3, 1_000):
        (directory / f"20261021T143000Z-commande-{index}.md").touch()
    with pytest.raises(FileExistsError, match="999 rapports déjà présents"):
        ks._reserve_report(directory, "commande", NOW)


def test_the_reason_is_cleaned_never_refused(tmp_path: Path) -> None:
    assert stopped(tmp_path, reason="ligne 1\n\tligne 2\x00" + "x" * 300).reason == (
        "ligne 1 ligne 2 " + "x" * 184
    )
    assert stopped(tmp_path, reason=" \n ").reason == "sans raison"


def test_the_exception_carries_the_stop(tmp_path: Path) -> None:
    stop = stopped(tmp_path, trigger="incident_execution", reason="transition interdite")
    error = KillSwitchEngaged(stop)
    assert error.stop is stop
    assert str(error) == "kill switch engagé (incident_execution) : transition interdite"


def test_an_engaged_switch_refuses_every_order_at_n0(tmp_path: Path) -> None:
    autonomy = load_config(REPO_ROOT / "config").autonomy
    stopped(tmp_path)
    decision = decide_order(
        autonomy,
        request_id="r1",
        kill_switch=kill_switch_engaged(tmp_path),
        live_enabled=False,
        risk_gate=None,
    )
    assert (decision.decision, decision.autonomy_level) == ("refus", "N0")


def test_a_thousand_open_orders_stop_within_five_seconds(tmp_path: Path) -> None:
    """On disk, with the real journal and an adapter that answers in 0.5 s after a time-out."""
    memory = booked(MemoryJournal())
    ids = [sent_order(memory, n) for n in range(1_000)]
    default_book_path(tmp_path).parent.mkdir(parents=True)
    target = sqlite3.connect(default_book_path(tmp_path))
    memory._conn.backup(target)
    target.close()
    journal = AuditJournal(tmp_path / "var" / "audit" / "journal.jsonl")
    adapter = Broker(cancel_all=[TimeoutError(), tuple(ids)], on_call=lambda: time.sleep(0.5))
    with OrderBook.open(
        default_book_path(tmp_path), recorder=Recorder(journal, "lucas", "kill-test")
    ) as book:
        started = time.monotonic()
        stop = stopped(tmp_path, journal=journal, adapter=adapter, book=book)
        wall = time.monotonic() - started
        assert len(book.open_orders()) == 0
    assert len(stop.cancelled) == 1_000 and stop.unconfirmed == ()
    assert stop.within_target and wall < 5.0
    lines = journal.path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["KILL", "ORDER_STATE", "KILL"]


# --- the book's bulk move ---------------------------------------------------------------------


def test_cancel_many_moves_every_order_in_one_entry() -> None:
    journal = MemoryJournal()
    book = booked(journal)
    orders = [validated(book, 0), sent_order(book, 1)]
    before = journal.calls
    assert book.cancel_many([], reason="rien") == ()
    assert book.cancel_many(reversed(orders), reason="kill switch", now=NOW) == tuple(orders)
    assert journal.calls == before + 1
    assert [book.order(key).state for key in orders] == [S.ANNULEE, S.ANNULEE]
    payload = journal.entries[-1]["payload"]
    assert payload["orders"] == [
        {"intent_id": str(key), "intent_sha256": book.order(key).intent.sha256()} for key in orders
    ]


@pytest.mark.parametrize("kind", ["transition_interdite", "ordre_inconnu"])
def test_cancel_many_moves_nothing_if_one_order_cannot_move(kind: str) -> None:
    journal = MemoryJournal()
    book = booked(journal)
    movable = validated(book, 0)
    if kind == "transition_interdite":
        blocking = make_intent(1)
        book.record_intent(blocking, decision_price=DECISION_PRICE, reason="intention rédigée")
        other = blocking.intent_id
    else:
        other = make_intent(9).intent_id
    calls = journal.calls
    with pytest.raises(ExecutionIncident) as caught:
        book.cancel_many([movable, other], reason="kill switch")
    assert caught.value.kind == kind
    assert book.order(movable).state is S.VALIDEE and journal.calls == calls


# --- detect and rearm -------------------------------------------------------------------------


def test_detect_tells_the_four_situations_apart(tmp_path: Path) -> None:
    journal = MemoryJournal()

    def status() -> str:
        return detect(tmp_path, journal=journal, request_id="start", now=NOW)

    assert status() == "armed"
    kill = tmp_path / KILL_SWITCH_FILE
    kill.parent.mkdir(parents=True)
    kill.write_text("à la main")
    assert status() == "new_file"
    stopped(tmp_path)
    assert status() == "engaged"
    kill.unlink()
    assert status() == "removed_by_hand"
    assert journal.entries == [
        {
            "actor": "policy",
            "event": "KILL",
            "request_id": "start",
            "payload": {"kill_switch": "suppression_detectee"},
        }
    ]
    assert not state_path(tmp_path).exists() and status() == "armed"


def test_the_recorded_stop_is_read_back(tmp_path: Path) -> None:
    assert recorded_stop(tmp_path) is None
    stop = stopped(tmp_path, book=_with_validated())
    assert stop.report is not None
    assert recorded_stop(tmp_path) == Recorded(
        engaged_at=utc_text(NOW),
        trigger="commande",
        report=stop.report,
        unconfirmed=tuple(str(key) for key in stop.unconfirmed),
    )


def _with_validated() -> OrderBook:
    book = booked(MemoryJournal())
    validated(book, 0)
    return book


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("pas du json", None),
        ("[1, 2]", None),
        (
            '{"engaged_at": "le\\u0007 jour", "trigger": 3, "report": "../secret.md",'
            ' "unconfirmed": "abc"}',
            Recorded(engaged_at="le jour", trigger="3", report=None, unconfirmed=()),
        ),
        (
            '{"report": "absent.md", "unconfirmed": ["a\\nb"]}',
            Recorded(engaged_at="None", trigger="None", report=None, unconfirmed=("a b",)),
        ),
    ],
)
def test_a_damaged_state_never_points_outside(
    tmp_path: Path, state: str, expected: Recorded | None
) -> None:
    incidents_dir(tmp_path).mkdir(parents=True)
    (tmp_path / "var" / "secret.md").write_text("hors du dossier")
    state_path(tmp_path).write_text(state, encoding="utf-8")
    assert recorded_stop(tmp_path) == expected


def _rearm(
    root: Path, journal: Any, *, phrase: str = REARM_PHRASE, at_console: bool = True
) -> None:
    rearm(
        root,
        journal=journal,
        request_id="rearm-test",
        now=NOW,
        phrase=phrase,
        interactive=lambda: at_console,
    )


@pytest.mark.parametrize(
    ("phrase", "at_console", "engaged", "message"),
    [
        (REARM_PHRASE, False, True, "terminal interactif"),
        ("rearmer", True, True, "phrase de confirmation incorrecte"),
        (REARM_PHRASE, True, False, "aucun arrêt en cours"),
    ],
)
def test_a_rearm_is_refused(
    tmp_path: Path, phrase: str, at_console: bool, engaged: bool, message: str
) -> None:
    if engaged:
        stopped(tmp_path)
    journal = MemoryJournal()
    with pytest.raises(KillSwitchError, match=message):
        _rearm(tmp_path, journal, phrase=phrase, at_console=at_console)
    assert journal.entries == [] and kill_switch_engaged(tmp_path) is engaged


def test_lucas_rearms_at_the_console(tmp_path: Path) -> None:
    stopped(tmp_path)
    journal = MemoryJournal()
    _rearm(tmp_path, journal)
    assert kills(journal) == [{"kill_switch": "rearmement"}]
    assert journal.entries[0]["actor"] == "lucas"
    assert not kill_switch_engaged(tmp_path) and not state_path(tmp_path).exists()
    assert detect(tmp_path, journal=journal, request_id="start", now=NOW) == "armed"


def test_a_kill_file_that_resists_keeps_the_stop(tmp_path: Path) -> None:
    (tmp_path / KILL_SWITCH_FILE).mkdir(parents=True)  # a folder cannot be unlinked
    journal = MemoryJournal()
    with pytest.raises(KillSwitchError, match="le fichier KILL reste en place"):
        _rearm(tmp_path, journal)
    assert kill_switch_engaged(tmp_path)
    assert kills(journal) == [
        {"kill_switch": "rearmement"},
        {"kill_switch": "rearmement_echoue", "error": kills(journal)[1]["error"]},
    ]
    assert kills(journal)[1]["error"] in {"PermissionError", "IsADirectoryError"}


def test_a_state_that_resists_is_reported(tmp_path: Path) -> None:
    stopped(tmp_path)
    state_path(tmp_path).unlink()
    state_path(tmp_path).mkdir()
    with pytest.raises(KillSwitchError, match="réarmé, mais l'état n'est pas effacé"):
        _rearm(tmp_path, MemoryJournal())
    assert not kill_switch_engaged(tmp_path)


# --- the loss triggers ------------------------------------------------------------------------

LIMITS = PaperRiskLimits.model_validate(base_world()["limits"])  # 2 %, 5 % on 20, 10 %
LOSS_CHECKS = {
    "perte du jour": "max_daily_loss_pct",
    "perte sur": "max_rolling_loss_pct",
    "drawdown": "max_drawdown_pct",
}


def account(**changes: Any) -> Account:
    return Account.model_validate(base_world()["snapshot"]["account"] | changes)


def test_losses_at_their_limits_trip_nothing() -> None:
    at_limits = account(
        day_pnl_eur=Decimal(-200), rolling_pnl_eur=Decimal(-500), equity_eur=Decimal(9000)
    )
    assert loss_breaches(at_limits, LIMITS) == ()
    assert loss_breaches(account(day_pnl_eur=Decimal(800)), LIMITS) == ()


def test_each_loss_beyond_its_limit_trips_with_percentages_only() -> None:
    beyond = account(
        day_pnl_eur=Decimal(-300),
        rolling_pnl_eur=Decimal("-612.34"),
        equity_eur=Decimal("8765.43"),
    )
    assert loss_breaches(beyond, LIMITS) == (
        ("limite", "perte du jour de 3 % du capital de référence, au-delà de la limite de 2 %"),
        (
            "limite",
            "perte sur 20 séances de 6,12 % du capital de référence, au-delà de la limite de 5 %",
        ),
        ("drawdown", "drawdown de 12,35 % depuis le plus haut, au-delà de la limite de 10 %"),
    )


@pytest.mark.parametrize(
    ("limits", "rolling_sessions", "message"),
    [
        ({"max_drawdown_pct": "A_DEFINIR"}, 20, "max_drawdown_pct vaut A_DEFINIR"),
        ({"capital_reference_eur": "A_VERIFIER"}, 20, "capital_reference_eur vaut A_VERIFIER"),
        ({"rolling_loss_sessions": "A_DEFINIR"}, 20, "rolling_loss_sessions vaut A_DEFINIR"),
        ({}, 10, "perte glissante sur 10 séances, et non 20"),
    ],
)
def test_an_unknown_loss_raises(
    limits: dict[str, Any], rolling_sessions: int, message: str
) -> None:
    marked = PaperRiskLimits.model_validate(base_world()["limits"] | limits)
    with pytest.raises(ValueError, match=message):
        loss_breaches(account(rolling_sessions=rolling_sessions), marked)


def test_the_loss_triggers_agree_with_the_risk_gate() -> None:
    """Tripped exactly when the Gate's loss check fails on known values; unknown when it is."""
    seen: Counter[str] = Counter()

    @settings(
        max_examples=1_500,
        derandomize=True,
        deadline=None,
        database=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )
    @given(cases())
    def agree(case: Case) -> None:
        checks = {c.name: c for c in evaluate(*case.args).checks if c.name in LOSS_CHECKS.values()}
        if len(checks) < len(LOSS_CHECKS):
            return  # a malformed intent stops the Gate before the loss checks
        snapshot, limits = case.args[1], case.args[2]
        try:
            breaches = loss_breaches(snapshot.account, limits)
        except ValueError:
            assert any(c.value == UNKNOWN for c in checks.values()), case.label
            seen["inconnue"] += 1
            return
        assert all(c.value != UNKNOWN for c in checks.values()), case.label
        tripped = {
            name
            for _, reason in breaches
            for prefix, name in LOSS_CHECKS.items()
            if reason.startswith(prefix)
        }
        assert tripped == {name for name, c in checks.items() if not c.ok}, case.label
        seen.update(tripped)

    agree()
    assert all(seen[key] > 0 for key in ("inconnue", *LOSS_CHECKS.values())), seen


# --- the CLI ----------------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    root.mkdir()
    monkeypatch.setenv("CERVEAU_HOME", str(root))
    return root


def kill(config_dir: Path, *extra: str) -> Any:
    return runner.invoke(app, ["kill", "--config-dir", str(config_dir), *extra])


def test_cerveau_kill_without_paper_account(home: Path, config_dir: Path) -> None:
    result = kill(config_dir, "--raison", "essai à la main")
    assert result.exit_code == 0, result.output
    assert "Kill switch engagé (commande) en " in result.stdout
    assert "dans la cible de 5 s." in result.stdout
    assert "Ordres : 0 passés à ANNULEE au carnet, 0 annulations confirmées" in result.stdout
    assert "Approbations : 0 demande(s) ouverte(s) refusée(s)." in result.stdout
    assert kill_switch_engaged(home)
    assert not approvals_path(home).exists()  # a stop creates no store
    report = recorded_stop(home)
    assert report is not None and report.report is not None and report.trigger == "commande"
    assert "Raison : essai à la main" in report.report.read_text(encoding="utf-8")


def test_cerveau_kill_stops_even_with_an_invalid_configuration(home: Path, tmp_path: Path) -> None:
    result = kill(tmp_path / "nulle-part")
    assert result.exit_code == 1
    assert "cible à définir (R7)" in result.stdout
    assert "ERREUR : configuration invalide" in result.stderr
    assert kill_switch_engaged(home)


def _book_on_disk(home: Path) -> UUID:
    with OrderBook.open(
        default_book_path(home), recorder=Recorder(MemoryJournal(), "orchestrator", "setup")
    ) as book:
        return sent_order(book, 0)


def test_cerveau_kill_cancels_at_the_simulator(
    home: Path, config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(PaperSettings, "from_config", staticmethod(lambda *_: SETTINGS))
    order = _book_on_disk(home)
    with PaperSimulator.open(
        default_simulator_path(home), SETTINGS, now=OPENED, sessions=weekdays
    ) as sim:
        assert sim.submit(make_intent(0), now=SUBMITTED).accepted
    result = kill(config_dir)
    assert result.exit_code == 0, result.output
    assert "Ordres : 1 passés à ANNULEE au carnet, 1 annulations confirmées" in result.stdout
    with OrderBook.open(default_book_path(home), read_only=True) as book:
        assert book.order(order).state is S.ANNULEE


def test_cerveau_kill_refuses_the_open_approvals(home: Path, config_dir: Path) -> None:
    asked = datetime.now(UTC)
    trail = Trail(MemoryJournal(), "setup")
    with ApprovalStore.open(approvals_path(home), rules=RULES, trail=trail) as approvals:
        waiting = ask(approvals, now=asked)
    result = kill(config_dir)
    assert result.exit_code == 0, result.output
    assert "Approbations : 1 demande(s) ouverte(s) refusée(s)." in result.stdout
    with ApprovalStore.open(approvals_path(home), rules=RULES, read_only=True) as approvals:
        assert approvals.get(waiting, now=asked).state is ApprovalState.REFUSEE


def _no_rules(_: object) -> ApprovalRules:
    raise ApprovalError("paramètres d'approbation à définir par Lucas (R7)")


def test_cerveau_kill_without_approval_rules_or_store(
    home: Path, config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ApprovalRules, "from_config", staticmethod(_no_rules))
    result = kill(config_dir)
    assert result.exit_code == 0, result.output  # nothing to refuse: not an error
    assert "Approbations : 0 demande(s)" in result.stdout


@pytest.mark.parametrize("settings_known", [True, False])
def test_cerveau_kill_reports_what_it_cannot_open(
    home: Path, config_dir: Path, monkeypatch: pytest.MonkeyPatch, settings_known: bool
) -> None:
    if settings_known:
        monkeypatch.setattr(PaperSettings, "from_config", staticmethod(lambda *_: SETTINGS))
    else:
        monkeypatch.setattr(ApprovalRules, "from_config", staticmethod(_no_rules))
    for path in (default_book_path(home), default_simulator_path(home), approvals_path(home)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ceci n'est pas une base SQLite" * 100)
    result = kill(config_dir)
    assert result.exit_code == 1
    assert "ERREUR : carnet d'ordres non ouvert (DatabaseError)" in result.stderr
    expected = "(DatabaseError)" if settings_known else "(trading_costs : commission_pct"
    assert f"ERREUR : simulateur paper non ouvert {expected}" in result.stderr
    expected = "(DatabaseError)" if settings_known else "(paramètres d'approbation à définir"
    assert f"ERREUR : registre des approbations non ouvert {expected}" in result.stderr
    assert kill_switch_engaged(home)


def test_lucas_rearms_with_the_cli(
    home: Path, config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order = _book_on_disk(home)  # sent, no simulator: its cancellation is unconfirmed
    result = kill(config_dir)
    assert result.exit_code == 1
    assert f"ALERTE : annulation non confirmée pour l'ordre {order}" in result.stderr

    refused = runner.invoke(app, ["rearm"], input=f"{REARM_PHRASE}\n")
    assert refused.exit_code == 2 and "terminal interactif" in refused.stderr

    monkeypatch.setattr("interfaces.cli.kill_switch.interactive_terminal", lambda: True)
    wrong = runner.invoke(app, ["rearm"], input="oui\n")
    assert wrong.exit_code == 2 and "phrase de confirmation incorrecte" in wrong.stderr
    assert kill_switch_engaged(home)

    done = runner.invoke(app, ["rearm"], input=f"{REARM_PHRASE}\n")
    assert done.exit_code == 0, done.output
    assert "Arrêt du " in done.stdout and "(commande)" in done.stdout
    assert "Rapport : " in done.stdout
    assert f"ALERTE : annulation non confirmée pour l'ordre {order}" in done.stderr
    assert "Kill switch réarmé" in done.stdout
    assert not kill_switch_engaged(home)

    nothing = runner.invoke(app, ["rearm"])
    assert nothing.exit_code == 1 and "Aucun arrêt en cours" in nothing.stderr


def test_cerveau_kill_alerts_on_an_order_unknown_to_the_book(
    home: Path, config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(PaperSettings, "from_config", staticmethod(lambda *_: SETTINGS))
    stray = make_intent(0)
    with PaperSimulator.open(
        default_simulator_path(home), SETTINGS, now=OPENED, sessions=weekdays
    ) as sim:
        assert sim.submit(stray, now=SUBMITTED).accepted
    result = kill(config_dir)
    assert result.exit_code == 1
    assert f"ALERTE : ordre {stray.intent_id} annulé chez le courtier, absent du carnet" in (
        result.stderr
    )
    recorded = recorded_stop(home)
    assert recorded is not None and recorded.report is not None
    recorded.report.unlink()  # the state no longer points to a report

    monkeypatch.setattr("interfaces.cli.kill_switch.interactive_terminal", lambda: True)
    done = runner.invoke(app, ["rearm"], input=f"{REARM_PHRASE}\n")
    assert done.exit_code == 0, done.output
    assert "Arrêt du " in done.stdout and "Rapport : " not in done.stdout


def test_cerveau_kill_without_a_report(home: Path, config_dir: Path) -> None:
    incidents_dir(home).parent.mkdir(parents=True)
    incidents_dir(home).write_text("un fichier à la place du dossier")
    result = kill(config_dir)
    assert result.exit_code == 1
    assert "Rapport : " not in result.stdout
    assert "ERREUR : rapport d'incident non créé" in result.stderr
    assert kill_switch_engaged(home)


def test_cerveau_rearm_after_a_removal_by_hand(home: Path, config_dir: Path) -> None:
    assert kill(config_dir).exit_code == 0
    (home / KILL_SWITCH_FILE).unlink()
    result = runner.invoke(app, ["rearm"])
    assert result.exit_code == 0
    assert "supprimé à la main : suppression journalisée" in result.stdout


def test_cerveau_kill_keeps_its_journal_under_var(
    home: Path, config_dir: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "ailleurs" / "journal.jsonl"
    result = kill(config_dir, "--journal", str(elsewhere))
    assert result.exit_code == 0, result.output  # a stop never refuses (R4)
    assert "AVERTISSEMENT (B103) : --journal" in result.stderr
    assert not elsewhere.exists() and (home / "var" / "audit").is_dir()
    assert kill_switch_engaged(home)


@pytest.mark.parametrize("under_var", [True, False])
def test_cerveau_kill_takes_a_journal_under_var_or_with_the_option(
    home: Path, config_dir: Path, tmp_path: Path, under_var: bool
) -> None:
    journal = home / "var" / "essai.jsonl" if under_var else tmp_path / "ailleurs.jsonl"
    extra = () if under_var else ("--hors-var",)
    result = kill(config_dir, "--journal", str(journal), *extra)
    assert result.exit_code == 0, result.output
    assert "AVERTISSEMENT" not in result.stderr and journal.is_file()


def test_cerveau_rearm_refuses_a_journal_outside_var(home: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "ailleurs.jsonl"
    result = runner.invoke(app, ["rearm", "--journal", str(elsewhere)])
    assert result.exit_code == 1
    assert "Refus (B103) : --journal" in result.output and not elsewhere.exists()


def test_cerveau_rearm_of_a_file_created_by_hand(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (home / KILL_SWITCH_FILE).parent.mkdir(parents=True)
    (home / KILL_SWITCH_FILE).write_text("à la main")
    monkeypatch.setattr("interfaces.cli.kill_switch.interactive_terminal", lambda: True)
    result = runner.invoke(app, ["rearm"], input=f"{REARM_PHRASE}\n")
    assert result.exit_code == 0, result.output
    assert "Fichier KILL créé à la main" in result.stdout
    assert not kill_switch_engaged(home)
