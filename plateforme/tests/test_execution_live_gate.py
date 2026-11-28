"""The live Risk Gate in front of the seven conditions (B353, ADR-075).

The gate reads ``config/live.yaml`` at each call and never writes it, journals every decision
without a figure of the account, and stops an order on its own: even with the seventh condition
removed, nothing it refuses reaches the broker. The adapter builds the gate itself, holds a lock
from the gate to the broker, and counts the orders it accepted that the book does not show yet.
The seventh condition stays, and still refuses every order.
"""

from __future__ import annotations

import json
import re
import sys
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from core.approvals.store import ApprovalState, ApprovalStore, Trail
from core.approvals.totp import totp
from core.audit.chain import AuditJournal
from core.config.loader import Config, ConfigError, LiveConfig, load_config
from core.execution.intent import OrderIntent
from core.execution.live import (
    LIVE_FILE,
    LIVE_LOCK,
    NO_LIVE_GATE,
    ActivationCheck,
    Condition,
    LiveAdapter,
    LiveDisabled,
    LiveGateRefused,
    LiveRiskGate,
    journaled_orders,
    no_live_book,
)
from core.finance.model import PARIS
from core.policy.engine import KILL_SWITCH_FILE
from core.risk_gate.gate import RiskGateResult
from core.risk_gate.live import NO_BOOK, NO_JOURNAL, LiveBook, fingerprint
from tests.execution_cases import MemoryJournal, make_intent
from tests.risk_gate.test_live_gate import book_data
from tests.test_execution_live import (
    COMPLETE,
    KEY,
    REPO,
    RULES,
    Client,
    gate_passes,
    granted,
    project,
)

NOW = datetime(2026, 10, 17, 14, 10, tzinfo=PARIS)  # the day make_intent(0) is drafted
LIVE = COMPLETE | {
    "capital_reference_eur": 200_000,
    "timezone": "Europe/Paris",
    "max_book_age_s": 600,
}
BOOK = LiveBook.model_validate(book_data())
LATER = datetime(2026, 10, 21, 12, 1, 5, tzinfo=UTC)  # a code step after granted's


@pytest.fixture
def approvals() -> Iterator[ApprovalStore]:
    with ApprovalStore.memory(RULES, Trail(MemoryJournal(), "live-gate-test")) as store:
        yield store


def books(_intent: OrderIntent, _now: datetime) -> LiveBook:
    return BOOK


def at(moment: datetime) -> Callable[[], datetime]:
    return lambda: moment


def gate(root: Path, journal: Any = None, *, book: Any = books, **options: Any) -> LiveRiskGate:
    options.setdefault("clock", at(NOW))
    options.setdefault("book_timeout_s", 5)
    return LiveRiskGate(root, MemoryJournal() if journal is None else journal, book=book, **options)


def all_hold(_intent: OrderIntent, _now: datetime) -> dict[Condition, None]:
    return dict.fromkeys(Condition)


def live_adapter(
    root: Path,
    store: ApprovalStore,
    client: Client,
    *,
    check: Any = all_hold,
    journal: Any = None,
    book: Any = books,
    clock: Callable[[], datetime] | None = None,
) -> LiveAdapter:
    return LiveAdapter(
        client,
        store,
        check,
        root=root,
        journal=MemoryJournal() if journal is None else journal,
        book=book,
        call_timeout_s=5,
        kill_target_s=10,
        clock=clock or at(NOW),
    )


def granted_later(store: ApprovalStore, intent: OrderIntent) -> None:
    """A second approval, a code step after ``granted``'s: a code is never accepted twice."""
    moment = LATER
    approval_id = store.request(
        intent_id=intent.intent_id,
        intent_sha256=intent.sha256(),
        environment="live",
        gate={"quantity": intent.quantity, "reasons": []},
        summary="Achat de 10 FICT-ACME à 123,45 EUR au plus",
        now=moment,
    ).approval_id
    assert store.approve(approval_id, totp(KEY, moment), key=KEY, now=moment).accepted


def footprint(path: Path) -> tuple[bytes, int]:
    return path.read_bytes(), path.stat().st_mtime_ns


# The gate over the files -------------------------------------------------------------------


def test_a_complete_live_file_and_a_book_within_the_limits_accept(tmp_path: Path) -> None:
    journal = MemoryJournal()
    got = gate(project(tmp_path, live=LIVE), journal)(make_intent(0))
    assert got.result == "ACCEPTE"
    (entry,) = journal.entries
    assert (entry["actor"], entry["event"]) == ("risk_gate", "POLICY")
    assert entry["request_id"] == f"live-{make_intent(0).intent_id}"
    payload = entry["payload"]
    assert payload["environment"] == "live"
    assert payload["result"] == "ACCEPTE"
    assert payload["intent_sha256"] == make_intent(0).sha256()
    assert payload["requested_quantity"] == payload["quantity"] == 10
    assert payload["reasons"] == ["toutes les vérifications passent"]
    assert payload["book_sha256"] == BOOK.sha256()
    assert payload["errors"] == {}
    assert payload["decided_at"] == NOW.isoformat()
    assert payload["order"] == {
        "symbol": "FICT-ACME",
        "side": "BUY",
        "quantity": 10,
        "limit_price": "123.45",
        "currency": "EUR",
    }


def test_a_refusal_is_journaled_with_every_reason(tmp_path: Path) -> None:
    journal = MemoryJournal()
    root = project(tmp_path, live=LIVE | {"instruments_whitelist": ["FR0010315770"]})
    got = gate(root, journal)(make_intent(0))
    assert got.result == "REFUSE"
    (entry,) = journal.entries
    assert entry["payload"]["result"] == "REFUSE"
    assert entry["payload"]["quantity"] == 0
    assert entry["payload"]["reasons"] == ["instruments_whitelist : hors de la liste blanche"]
    failing = [check for check in entry["payload"]["checks"] if not check["ok"]]
    assert [check["name"] for check in failing] == ["instruments_whitelist"]


def test_the_journal_keeps_no_identifier_of_the_account(tmp_path: Path) -> None:
    """ADR-071: the book is journaled as its SHA-256; no broker name, no whitelist, no book."""
    journal = MemoryJournal()
    gate(project(tmp_path, live=LIVE), journal)(make_intent(0))
    text = json.dumps(journal.entries, ensure_ascii=False, default=str)
    for secret in ("courtier-de-test", "FR0010315770", "holdings", "cash_eur", "day_pnl"):
        assert secret not in text
    assert set(journal.entries[0]["payload"]) == {
        "environment",
        "decided_at",
        "intent_id",
        "intent_sha256",
        "requested_quantity",
        "quantity",
        "order",
        "result",
        "checks",
        "reasons",
        "book_sha256",
        "errors",
    }


# Figures no limit, date or order of the tests could spell by chance (M1).
SECRET = book_data(
    holdings={"FICT-ACME": 437},
    cash_eur=Decimal("98765.43"),
    day_pnl_eur=Decimal("-543.21"),
    orders_today=1,
)
SECRET_FIGURES = (
    "437",  # the holding
    "98765",  # the cash
    "98 765",
    "543.21",  # the day's P&L
    "543,21",
    "52440",  # the holding's value, 437 x 120 EUR
    "53674",  # the position after the order
    "26.83",  # that position in % of 200 000 EUR
    "0.2716",  # the day's loss in % of 200 000 EUR
)


def _without_digests(entries: list[dict[str, Any]]) -> str:
    """The entries as text, hashes taken out: a hexadecimal digest may spell anything."""
    text = json.dumps(entries, ensure_ascii=False, default=str)
    return re.sub(r"(sha256:)?[0-9a-f]{64}", "<empreinte>", text)


@pytest.mark.parametrize(
    "capital", [200_000, 10_000_000], ids=["refused-on-the-position", "accepted"]
)
@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_no_figure_of_the_book_reaches_the_journal(tmp_path: Path, capital: int, side: str) -> None:
    """M1: the cash, the holding, the P&L and the exposure never appear in the entry."""
    journal = MemoryJournal()
    secret = LiveBook.model_validate(SECRET)
    root = project(tmp_path, live=LIVE | {"capital_reference_eur": capital})
    got = gate(root, journal, book=lambda *_: secret)(make_intent(0, side=side))
    if side == "BUY":
        assert got.result == ("ACCEPTE" if capital > 200_000 else "REFUSE")
    text = _without_digests(journal.entries)
    for figure in SECRET_FIGURES:
        assert figure not in text, figure
    book_checks = {"max_order_pct", "max_position_pct", "max_daily_loss_pct", "leverage"}
    for check in journal.entries[0]["payload"]["checks"]:
        if check["name"] in book_checks | {"max_orders_per_day", "short_selling"}:
            assert check["value"] in ("masqué (livre)", "achat", "vente"), check


def test_the_shipped_live_file_refuses_and_stays_untouched() -> None:
    """The real ``config/live.yaml``, read and never written: same bytes, same mtime."""
    before = footprint(REPO / LIVE_FILE)
    journal = MemoryJournal()
    got = gate(REPO, journal)(make_intent(0))
    assert footprint(REPO / LIVE_FILE) == before
    assert got.result == "REFUSE"
    reasons = journal.entries[0]["payload"]["reasons"]
    assert "enabled : live désactivé (R3)" in reasons
    assert any(reason.startswith("day : timezone absent de live.yaml") for reason in reasons)
    assert any(reason.startswith("max_book_age_s : max_book_age_s absent") for reason in reasons)


def test_the_gate_never_writes_the_live_file(tmp_path: Path) -> None:
    root = project(tmp_path, live=LIVE)
    before = footprint(root / LIVE_FILE)
    judge = gate(root)
    for n in range(3):
        judge(make_intent(n))
        judge(make_intent(n, quantity=10_000))
    assert footprint(root / LIVE_FILE) == before


def test_a_change_of_the_live_file_applies_to_the_next_call(tmp_path: Path) -> None:
    root = project(tmp_path, live=LIVE)
    judge = gate(root)
    assert judge(make_intent(0)).result == "ACCEPTE"
    (root / LIVE_FILE).write_text(
        json.dumps(LIVE | {"enabled": False}), encoding="utf-8"
    )  # the user's own edit, in the test's copy
    assert judge(make_intent(0)).result == "REFUSE"


def test_without_a_book_source_every_order_is_refused(tmp_path: Path) -> None:
    journal = MemoryJournal()
    got = gate(project(tmp_path, live=LIVE), journal, book=no_live_book)(make_intent(0))
    assert got.result == "REFUSE"
    assert NO_BOOK in {check.reason for check in got.checks}
    assert journal.entries[0]["payload"]["book_sha256"] is None
    assert no_live_book(make_intent(0), NOW) is None


def test_a_book_source_in_error_refuses_and_names_only_the_error_type(tmp_path: Path) -> None:
    def broken(_intent: OrderIntent, _now: datetime) -> LiveBook:
        raise ConnectionError("compte 12345678 injoignable")

    journal = MemoryJournal()
    got = gate(project(tmp_path, live=LIVE), journal, book=broken)(make_intent(0))
    assert got.result == "REFUSE"
    reason = "source du livre live en erreur (ConnectionError)"
    assert reason in {check.reason for check in got.checks}
    assert journal.entries[0]["payload"]["errors"] == {"book": "ConnectionError"}
    assert "12345678" not in json.dumps(journal.entries, default=str)


def test_a_source_that_gives_something_else_than_a_book_refuses(tmp_path: Path) -> None:
    journal = MemoryJournal()
    got = gate(project(tmp_path, live=LIVE), journal, book=lambda *_: book_data())(make_intent(0))
    assert got.result == "REFUSE"
    assert "source du livre live : LiveBook attendu (dict)" in {c.reason for c in got.checks}
    assert journal.entries[0]["payload"]["book_sha256"] is None


@pytest.mark.parametrize("error", [ConfigError("x"), OSError("x")], ids=["invalid", "unreadable"])
def test_an_unreadable_configuration_refuses(tmp_path: Path, error: Exception) -> None:
    def load(_directory: Path) -> Config:
        raise error

    journal = MemoryJournal()
    got = gate(tmp_path, journal, load=load)(make_intent(0))
    name = type(error).__name__
    assert got.result == "REFUSE"
    assert got.reasons == (f"configuration : configuration illisible ({name})",)
    assert got.intent_sha256 == make_intent(0).sha256()
    assert journal.entries[0]["payload"]["errors"] == {"config": name}


def test_a_book_timeout_must_be_a_positive_number(tmp_path: Path) -> None:
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="délai de lecture du livre"):
            gate(tmp_path, book_timeout_s=bad)


# The kill switch first, and a book source that hangs (m3) ---------------------------------


def test_the_kill_switch_refuses_before_anything_is_read(tmp_path: Path) -> None:
    root = project(tmp_path, live=LIVE)
    (root / KILL_SWITCH_FILE).parent.mkdir(parents=True, exist_ok=True)
    (root / KILL_SWITCH_FILE).write_text("test\n", encoding="utf-8")
    asked: list[str] = []

    def book(_intent: OrderIntent, _now: datetime) -> LiveBook:
        asked.append("book")
        return BOOK

    def load(directory: Path) -> Config:
        asked.append("config")
        return load_config(directory)

    journal = MemoryJournal()
    got = gate(root, journal, book=book, load=load)(make_intent(0))
    assert got.reasons == ("kill_switch : kill switch engagé (R4)",)
    assert asked == []
    assert journal.entries[0]["payload"]["result"] == "REFUSE"


def test_a_book_source_that_hangs_is_cut_short(tmp_path: Path) -> None:
    release = threading.Event()

    def hangs(_intent: OrderIntent, _now: datetime) -> LiveBook:
        release.wait(5)
        return BOOK

    try:
        got = gate(project(tmp_path, live=LIVE), book=hangs, book_timeout_s=0.05)(make_intent(0))
    finally:
        release.set()
    assert "source du livre live en erreur (TimeoutError)" in {c.reason for c in got.checks}
    assert got.result == "REFUSE"


# The decision time is read once the book is in (m4) ------------------------------------------


def test_the_decision_time_is_read_after_the_book(tmp_path: Path) -> None:
    """A book observed a second after the request is not one from after the decision."""
    times = iter([NOW, NOW + timedelta(seconds=2)])
    observed = NOW + timedelta(seconds=1)
    facts = book_data()["instruments"]["FICT-ACME"] | {"priced_at": observed}
    late = LiveBook.model_validate(book_data(as_of=observed, instruments={"FICT-ACME": facts}))
    seen: list[datetime] = []

    def book(_intent: OrderIntent, asked: datetime) -> LiveBook:
        seen.append(asked)
        return late

    journal = MemoryJournal()
    got = gate(project(tmp_path, live=LIVE), journal, book=book, clock=lambda: next(times))(
        make_intent(0)
    )
    assert got.result == "ACCEPTE"
    assert seen == [NOW]
    assert journal.entries[0]["payload"]["decided_at"] == (NOW + timedelta(seconds=2)).isoformat()


def test_a_book_fetched_too_slowly_is_too_old(tmp_path: Path) -> None:
    times = iter([NOW, BOOK.as_of + timedelta(seconds=601)])
    got = gate(project(tmp_path, live=LIVE), clock=lambda: next(times))(make_intent(0))
    reasons = {check.name: check.reason for check in got.checks if not check.ok}
    assert reasons["max_book_age_s"] == "trop ancien : livre"


# A journal that cannot be written, or read (m2, M4) ----------------------------------------


def test_a_journal_that_fails_refuses_the_order_and_leaves_a_bare_refusal(tmp_path: Path) -> None:
    journal = MemoryJournal(fail_at=1)
    got = gate(project(tmp_path, live=LIVE), journal)(make_intent(0))
    assert got.result == "REFUSE"
    assert got.reasons == (
        "journal : journal d'audit indisponible (OSError) : aucune décision sans trace (R11)",
    )
    (entry,) = journal.entries
    assert entry["payload"]["result"] == "REFUSE"
    assert entry["payload"]["errors"] == {"journal": "OSError"}
    assert entry["payload"]["reasons"] == list(got.reasons)


def test_an_entry_that_cannot_be_built_leaves_a_bare_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """m2: the book's digest fails while the payload is built: still one entry, a refusal."""

    def broken(_book: LiveBook) -> str:
        raise RuntimeError("panne")

    monkeypatch.setattr(LiveBook, "sha256", broken)
    journal = MemoryJournal()
    got = gate(project(tmp_path, live=LIVE), journal)(make_intent(0))
    assert got.result == "REFUSE"
    (entry,) = journal.entries
    assert entry["payload"]["result"] == "REFUSE"
    assert entry["payload"]["errors"] == {"journal": "RuntimeError"}


def test_a_journal_that_always_fails_still_refuses(tmp_path: Path) -> None:
    class Down(MemoryJournal):
        def append(self, **_entry: Any) -> dict[str, Any]:
            raise OSError("disque plein")

    got = gate(project(tmp_path, live=LIVE), Down())(make_intent(0))
    assert got.result == "REFUSE"
    assert got.reasons[0].startswith("journal : journal d'audit indisponible (OSError)")


def test_a_journal_that_cannot_be_read_back_refuses(tmp_path: Path) -> None:
    class Unreadable(MemoryJournal):
        def payloads(self, **_query: Any) -> list[Any]:
            raise OSError("illisible")

    journal = Unreadable()
    got = gate(project(tmp_path, live=LIVE), journal)(make_intent(0))
    assert got.result == "REFUSE"
    assert NO_JOURNAL in {check.reason for check in got.checks}
    assert journal.entries[0]["payload"]["errors"] == {"journal": "OSError"}


def test_an_acceptance_journaled_without_its_order_refuses(tmp_path: Path) -> None:
    journal = MemoryJournal()
    journal.append(
        actor="risk_gate",
        event="POLICY",
        request_id="live-x",
        payload={"result": "ACCEPTE", "intent_sha256": "a" * 64, "decided_at": NOW.isoformat()},
    )
    got = gate(project(tmp_path, live=LIVE), journal)(make_intent(0))
    assert NO_JOURNAL in {check.reason for check in got.checks}
    assert journal.entries[-1]["payload"]["errors"] == {"journal": "KeyError"}


def test_the_orders_accepted_are_read_back_from_the_journal() -> None:
    journal = MemoryJournal()
    decided = {"decided_at": NOW.isoformat(), "order": {}}
    refused = {"result": "REFUSE", "intent_sha256": "b" * 64} | decided
    journal.append(actor="risk_gate", event="POLICY", request_id="live-1", payload=refused)
    found = journal.payloads(actor="risk_gate", event="POLICY", request_prefix="live-")
    assert journaled_orders(found) == ()


# An object that is no genuine intent (M3) -------------------------------------------------


def test_the_gate_refuses_and_journals_an_intent_built_without_validation(tmp_path: Path) -> None:
    journal = MemoryJournal()
    forged = make_intent(0).model_copy(update={"quantity": -500})
    got = gate(project(tmp_path, live=LIVE), journal)(forged)
    assert got.reasons == ("schema : intention invalide (ValidationError)",)
    (entry,) = journal.entries
    assert entry["request_id"] == "live-intention-invalide"
    assert entry["payload"]["intent_id"] is None
    assert entry["payload"]["order"] is None
    assert entry["payload"]["errors"] == {"intent": "ValidationError"}


def test_a_journal_failing_on_an_invalid_intent_still_refuses(tmp_path: Path) -> None:
    forged = make_intent(0).model_copy(update={"quantity": -500})
    got = gate(project(tmp_path, live=LIVE), MemoryJournal(fail_at=1))(forged)
    assert got.result == "REFUSE"


@pytest.mark.parametrize(
    "changes",
    [{"quantity": -500}, {"limit_price": Decimal("NaN")}, {"side": "HOLD"}],
    ids=["negative-quantity", "nan-price", "unknown-side"],
)
def test_the_adapter_refuses_an_intent_built_without_validation(
    tmp_path: Path, approvals: ApprovalStore, changes: dict[str, Any]
) -> None:
    forged = make_intent(0).model_copy(update=changes)
    client = Client()
    with pytest.raises(LiveGateRefused, match=r"intention invalide \(ValidationError\)"):
        live_adapter(project(tmp_path, live=LIVE), approvals, client).submit(forged, now=NOW)
    assert client.calls == []


def test_the_adapter_refuses_a_subclass_that_forges_its_fingerprint(
    tmp_path: Path, approvals: ApprovalStore
) -> None:
    class Forged(OrderIntent):
        def sha256(self) -> str:
            return "a" * 64

    forged = Forged.model_validate(make_intent(0).model_dump())
    client = Client()
    with pytest.raises(LiveGateRefused, match=r"intention invalide \(TypeError\)"):
        live_adapter(project(tmp_path, live=LIVE), approvals, client).submit(forged, now=NOW)
    assert client.calls == []


def test_the_broker_gets_the_validated_copy(tmp_path: Path, approvals: ApprovalStore) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    sent: list[OrderIntent] = []

    class Recording(Client):
        def submit(self, given: OrderIntent, *, now: datetime) -> Any:
            sent.append(given)
            return super().submit(given, now=now)

    live = live_adapter(project(tmp_path, live=LIVE), approvals, Recording())
    assert live.submit(intent, now=NOW).accepted
    (copy,) = sent
    assert copy == intent and copy is not intent
    assert type(copy) is OrderIntent


# The gate in front of the seven conditions ---------------------------------------------------


def test_a_gate_refusal_stops_the_order_before_the_seven_conditions(
    tmp_path: Path, approvals: ApprovalStore
) -> None:
    """Defence in depth: the conditions all hold, the seventh one removed, and still nothing
    the gate refuses reaches the broker."""
    intent = make_intent(0, quantity=10_000)  # 1 234 500 EUR: over every limit
    approval_id = granted(approvals, intent)
    root = project(tmp_path, live=LIVE)
    check = ActivationCheck(root, approvals, owner=lambda _path: True, limits=lambda *_: None)
    journal = MemoryJournal()
    client = Client()
    live = live_adapter(root, approvals, client, check=check, journal=journal)
    with pytest.raises(LiveGateRefused, match="aucun appel au courtier") as caught:
        live.submit(intent, now=NOW)
    assert caught.value.conditions == ()
    assert "max_order_pct : ordre trop gros" in caught.value.reasons
    assert isinstance(caught.value, LiveDisabled)
    assert client.calls == []
    assert approvals.get(approval_id, now=NOW).state is ApprovalState.ACCORDEE
    assert journal.entries[0]["payload"]["result"] == "REFUSE"


def test_the_seventh_condition_still_refuses_what_the_gate_accepts(
    tmp_path: Path, approvals: ApprovalStore
) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    root = project(tmp_path, live=LIVE)
    journal = MemoryJournal()
    client = Client()
    check = ActivationCheck(root, approvals, owner=lambda _path: True)  # the real seventh
    live = live_adapter(root, approvals, client, check=check, journal=journal)
    with pytest.raises(LiveDisabled) as caught:
        live.submit(intent, now=NOW)
    assert not isinstance(caught.value, LiveGateRefused)
    assert caught.value.failures == ((Condition.LIMITES, NO_LIVE_GATE),)
    assert journal.entries[0]["payload"]["result"] == "ACCEPTE"
    assert client.calls == []


def test_an_order_passes_only_when_the_gate_and_the_conditions_accept(
    tmp_path: Path, approvals: ApprovalStore
) -> None:
    intent = make_intent(0)
    approval_id = granted(approvals, intent)
    root = project(tmp_path, live=LIVE)
    client = Client()
    check = ActivationCheck(root, approvals, owner=lambda _path: True, limits=gate_passes)
    assert live_adapter(root, approvals, client, check=check).submit(intent, now=NOW).accepted
    assert client.calls == ["submit"]
    assert approvals.get(approval_id, now=NOW).state is ApprovalState.CONSOMMEE


def test_the_adapter_takes_no_gate_from_its_caller(
    tmp_path: Path, approvals: ApprovalStore
) -> None:
    """m5: the gate is built from the adapter's root and journal, never handed in."""
    with pytest.raises(TypeError, match="gate"):
        LiveAdapter(  # type: ignore[call-arg]
            Client(),
            approvals,
            all_hold,
            gate=lambda *_: None,
            root=tmp_path,
            journal=MemoryJournal(),
            call_timeout_s=5,
            kill_target_s=10,
        )
    journal = MemoryJournal()
    live = live_adapter(project(tmp_path, live=LIVE), approvals, Client(), journal=journal)
    with pytest.raises(LiveGateRefused):
        live.submit(make_intent(0, quantity=10_000), now=NOW)
    assert journal.entries[0]["actor"] == "risk_gate"  # its own gate, on its own journal


NOT_AS_IS = "la Porte live n'accepte pas cet ordre tel quel"


def _verdict(**changes: Any) -> RiskGateResult:
    intent = make_intent(0)
    fields: dict[str, Any] = {
        "result": "ACCEPTE",
        "intent_id": intent.intent_id,
        "intent_sha256": intent.sha256(),
        "requested_quantity": intent.quantity,
        "quantity": intent.quantity,
        "checks": (),
        "reasons": ("toutes les vérifications passent",),
    }
    return RiskGateResult(**(fields | changes))


@pytest.mark.parametrize(
    ("verdict", "reason"),
    [
        (_verdict(result="REFUSE", quantity=0, reasons=("x : non",)), "x : non"),
        (_verdict(result="REDUIT", quantity=5), NOT_AS_IS),
        (_verdict(intent_sha256="b" * 64), NOT_AS_IS),
        (_verdict(quantity=9), NOT_AS_IS),
    ],
    ids=["refused", "reduced", "other-content", "other-quantity"],
)
def test_only_an_acceptance_of_this_very_order_opens_the_way(
    tmp_path: Path,
    approvals: ApprovalStore,
    monkeypatch: pytest.MonkeyPatch,
    verdict: RiskGateResult,
    reason: str,
) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    client = Client()
    monkeypatch.setattr(LiveRiskGate, "__call__", lambda _gate, _intent: verdict)
    with pytest.raises(LiveGateRefused) as caught:
        live_adapter(tmp_path, approvals, client).submit(intent, now=NOW)
    assert caught.value.reasons == (reason,)
    assert client.calls == []


def test_a_gate_that_raises_refuses(
    tmp_path: Path, approvals: ApprovalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_gate: LiveRiskGate, _intent: OrderIntent) -> RiskGateResult:
        raise RuntimeError("panne")

    monkeypatch.setattr(LiveRiskGate, "__call__", broken)
    client = Client()
    with pytest.raises(LiveGateRefused, match=r"Porte live en erreur \(RuntimeError\)"):
        live_adapter(tmp_path, approvals, client).submit(make_intent(0), now=NOW)
    assert client.calls == []


def test_the_gate_is_judged_on_the_adapter_clock(tmp_path: Path, approvals: ApprovalStore) -> None:
    seen: list[datetime] = []

    def book(_intent: OrderIntent, asked: datetime) -> LiveBook:
        seen.append(asked)
        return BOOK

    live = live_adapter(project(tmp_path, live=LIVE), approvals, Client(), book=book)
    with pytest.raises(LiveDisabled):
        live.submit(make_intent(0), now=NOW - timedelta(days=9))
    assert seen == [NOW]


# Two orders on the same book: the lock, and the acceptances not yet in the book (M4) ---------


def test_two_orders_judged_on_the_same_book_cannot_spend_the_same_cash(
    tmp_path: Path, approvals: ApprovalStore
) -> None:
    """Cash 1 500 EUR, two approved buys of 1 234.50 EUR, the book unchanged between them."""
    first, second = make_intent(0), make_intent(1)
    granted(approvals, first)
    granted_later(approvals, second)
    poor = LiveBook.model_validate(book_data(cash_eur=Decimal("1500")))
    client = Client()
    journal = AuditJournal(tmp_path / "journal" / "journal.jsonl")  # the real one, read back
    live = live_adapter(
        project(tmp_path, live=LIVE), approvals, client, journal=journal, book=lambda *_: poor
    )
    assert live.submit(first, now=NOW).accepted
    with pytest.raises(LiveGateRefused) as caught:
        live.submit(second, now=NOW)
    # One order in the book, the first accepted, this one: 3 > 2 a day, and the cash is spent.
    assert caught.value.reasons == (
        "max_orders_per_day : trop d'ordres aujourd'hui",
        "leverage : achat au-delà du cash : ce serait du levier",
    )
    assert client.calls == ["submit"]


def test_an_order_the_book_already_shows_is_not_counted_twice(
    tmp_path: Path, approvals: ApprovalStore
) -> None:
    first, second = make_intent(0), make_intent(1)
    granted(approvals, first)
    granted_later(approvals, second)
    after = LiveBook.model_validate(
        book_data(cash_eur=Decimal("1500"), known_intents=frozenset({fingerprint(first)}))
    )
    client = Client()
    live = live_adapter(project(tmp_path, live=LIVE), approvals, client, book=lambda *_: after)
    assert live.submit(first, now=NOW).accepted
    assert live.submit(second, now=NOW).accepted  # the book's cash already counts the first
    assert client.calls == ["submit", "submit"]


@pytest.mark.skipif(sys.platform == "win32", reason="verrou testé par fcntl")
def test_the_lock_is_held_from_the_gate_to_the_broker(
    tmp_path: Path, approvals: ApprovalStore
) -> None:
    import fcntl

    root = project(tmp_path, live=LIVE)
    held: list[bool] = []

    def locked() -> bool:
        with (root / LIVE_LOCK).open("rb") as other:
            try:
                fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(other.fileno(), fcntl.LOCK_UN)
            return False

    def book(_intent: OrderIntent, _now: datetime) -> LiveBook:
        held.append(locked())
        return BOOK

    class Checking(Client):
        def submit(self, intent: OrderIntent, *, now: datetime) -> Any:
            held.append(locked())
            return super().submit(intent, now=now)

    intent = make_intent(0)
    granted(approvals, intent)
    assert live_adapter(root, approvals, Checking(), book=book).submit(intent, now=NOW).accepted
    assert held == [True, True]
    assert not locked()  # released once the broker answered


def test_the_live_config_carries_the_gate_fields_only_when_written() -> None:
    shipped = load_config(REPO / "config").live
    fields = (shipped.capital_reference_eur, shipped.timezone, shipped.max_book_age_s)
    assert fields == (None, None, None)
    marked = LiveConfig.model_validate(COMPLETE | {"capital_reference_eur": "A_DEFINIR"})
    assert marked.capital_reference_eur == "A_DEFINIR"
    with pytest.raises(ValueError, match="greater than 0"):
        LiveConfig.model_validate(COMPLETE | {"capital_reference_eur": 0})
    with pytest.raises(ValueError, match="greater than 0"):
        LiveConfig.model_validate(COMPLETE | {"max_book_age_s": 0})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("enabled", 1),
        ("enabled", "on"),
        ("enabled", "true"),
        ("capital_reference_eur", "2"),
        ("capital_reference_eur", True),
        ("max_book_age_s", True),
        ("limits", COMPLETE["limits"] | {"max_order_pct": "2"}),
        ("limits", COMPLETE["limits"] | {"max_orders_per_day": True}),
        ("limits", COMPLETE["limits"] | {"max_orders_per_day": 2.0}),
        ("allow", COMPLETE["allow"] | {"leverage": 0}),
        ("allow", COMPLETE["allow"] | {"short_selling": "no"}),
        ("instruments_whitelist", "FICT-ACME"),
    ],
)
def test_live_yaml_is_read_without_coercion(field: str, value: Any) -> None:
    """m1: a value that is only like the right type does not load."""
    with pytest.raises(ValueError, match="validation error"):
        LiveConfig.model_validate(COMPLETE | {field: value})
