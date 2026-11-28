"""The live Risk Gate in front of the seven conditions (B353, ADR-075).

The gate reads ``config/live.yaml`` at each call and never writes it, journals every decision,
and stops an order on its own: even with the seventh condition removed, nothing it refuses
reaches the broker. The seventh condition stays, and still refuses every order.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from core.approvals.store import ApprovalState, ApprovalStore, Trail
from core.config.loader import Config, ConfigError, LiveConfig, load_config
from core.execution.intent import OrderIntent
from core.execution.live import (
    LIVE_FILE,
    NO_LIVE_GATE,
    ActivationCheck,
    Condition,
    LiveAdapter,
    LiveDisabled,
    LiveGateRefused,
    LiveRiskGate,
    no_live_book,
)
from core.finance.model import PARIS
from core.policy.engine import KILL_SWITCH_FILE
from core.risk_gate.gate import RiskGateResult
from core.risk_gate.live import NO_BOOK, LiveBook
from tests.execution_cases import MemoryJournal, make_intent
from tests.risk_gate.test_live_gate import book_data
from tests.test_execution_live import (
    COMPLETE,
    REPO,
    RULES,
    Client,
    gate_passes,
    granted,
    project,
)

NOW = datetime(2026, 10, 17, 14, 10, tzinfo=PARIS)  # the day make_intent(0) is drafted
LIVE = COMPLETE | {"capital_reference_eur": 200_000, "timezone": "Europe/Paris"}
BOOK = LiveBook.model_validate(book_data())


@pytest.fixture
def approvals() -> Iterator[ApprovalStore]:
    with ApprovalStore.memory(RULES, Trail(MemoryJournal(), "live-gate-test")) as store:
        yield store


def books(_intent: OrderIntent, _now: datetime) -> LiveBook:
    return BOOK


def live_adapter(
    store: ApprovalStore,
    client: Client,
    gate: Any,
    *,
    check: Any = None,
) -> LiveAdapter:
    def all_hold(_intent: OrderIntent, _now: datetime) -> dict[Condition, None]:
        return dict.fromkeys(Condition)

    return LiveAdapter(
        client,
        store,
        check or all_hold,
        gate=gate,
        call_timeout_s=5,
        kill_target_s=10,
        clock=lambda: NOW,
    )


def footprint(path: Path) -> tuple[bytes, int]:
    return path.read_bytes(), path.stat().st_mtime_ns


# The gate over the files -------------------------------------------------------------------


def test_a_complete_live_file_and_a_book_within_the_limits_accept(tmp_path: Path) -> None:
    journal = MemoryJournal()
    got = LiveRiskGate(project(tmp_path, live=LIVE), journal, book=books)(make_intent(0), NOW)
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


def test_a_refusal_is_journaled_with_every_reason(tmp_path: Path) -> None:
    journal = MemoryJournal()
    root = project(tmp_path, live=LIVE | {"instruments_whitelist": ["FR0010315770"]})
    got = LiveRiskGate(root, journal, book=books)(make_intent(0), NOW)
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
    LiveRiskGate(project(tmp_path, live=LIVE), journal, book=books)(make_intent(0), NOW)
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
        "result",
        "checks",
        "reasons",
        "book_sha256",
        "errors",
    }


def test_the_shipped_live_file_refuses_and_stays_untouched() -> None:
    """The real ``config/live.yaml``, read and never written: same bytes, same mtime."""
    before = footprint(REPO / LIVE_FILE)
    journal = MemoryJournal()
    got = LiveRiskGate(REPO, journal, book=books)(make_intent(0), NOW)
    assert footprint(REPO / LIVE_FILE) == before
    assert got.result == "REFUSE"
    reasons = journal.entries[0]["payload"]["reasons"]
    assert "enabled : live désactivé (R3)" in reasons
    assert any(reason.startswith("day : timezone absent de live.yaml") for reason in reasons)


def test_the_gate_never_writes_the_live_file(tmp_path: Path) -> None:
    root = project(tmp_path, live=LIVE)
    before = footprint(root / LIVE_FILE)
    gate = LiveRiskGate(root, MemoryJournal(), book=books)
    for n in range(3):
        gate(make_intent(n), NOW)
        gate(make_intent(n, quantity=10_000), NOW)
    assert footprint(root / LIVE_FILE) == before


def test_a_change_of_the_live_file_applies_to_the_next_call(tmp_path: Path) -> None:
    root = project(tmp_path, live=LIVE)
    gate = LiveRiskGate(root, MemoryJournal(), book=books)
    assert gate(make_intent(0), NOW).result == "ACCEPTE"
    (root / LIVE_FILE).write_text(
        json.dumps(LIVE | {"enabled": False}), encoding="utf-8"
    )  # the user's own edit, in the test's copy
    assert gate(make_intent(0), NOW).result == "REFUSE"


def test_without_a_book_source_every_order_is_refused(tmp_path: Path) -> None:
    journal = MemoryJournal()
    got = LiveRiskGate(project(tmp_path, live=LIVE), journal)(make_intent(0), NOW)
    assert got.result == "REFUSE"
    assert NO_BOOK in {check.reason for check in got.checks}
    assert journal.entries[0]["payload"]["book_sha256"] is None
    assert no_live_book(make_intent(0), NOW) is None


def test_a_book_source_in_error_refuses_and_names_only_the_error_type(tmp_path: Path) -> None:
    def broken(_intent: OrderIntent, _now: datetime) -> LiveBook:
        raise ConnectionError("compte 12345678 injoignable")

    journal = MemoryJournal()
    got = LiveRiskGate(project(tmp_path, live=LIVE), journal, book=broken)(make_intent(0), NOW)
    assert got.result == "REFUSE"
    reason = "source du livre live en erreur (ConnectionError)"
    assert reason in {check.reason for check in got.checks}
    assert journal.entries[0]["payload"]["errors"] == {"book": "ConnectionError"}
    assert "12345678" not in json.dumps(journal.entries, default=str)


def test_a_source_that_gives_something_else_than_a_book_refuses(tmp_path: Path) -> None:
    journal = MemoryJournal()
    gate = LiveRiskGate(project(tmp_path, live=LIVE), journal, book=lambda *_: book_data())
    got = gate(make_intent(0), NOW)
    assert got.result == "REFUSE"
    assert "source du livre live : LiveBook attendu (dict)" in {c.reason for c in got.checks}
    assert journal.entries[0]["payload"]["book_sha256"] is None


@pytest.mark.parametrize("error", [ConfigError("x"), OSError("x")], ids=["invalid", "unreadable"])
def test_an_unreadable_configuration_refuses(tmp_path: Path, error: Exception) -> None:
    def load(_directory: Path) -> Config:
        raise error

    journal = MemoryJournal()
    got = LiveRiskGate(tmp_path, journal, book=books, load=load)(make_intent(0), NOW)
    name = type(error).__name__
    assert got.result == "REFUSE"
    assert got.reasons == (f"configuration : configuration illisible ({name})",)
    assert got.intent_sha256 == make_intent(0).sha256()
    assert journal.entries[0]["payload"]["errors"] == {"config": name}


def test_the_kill_switch_refuses_before_any_check(tmp_path: Path) -> None:
    root = project(tmp_path, live=LIVE)
    (root / KILL_SWITCH_FILE).parent.mkdir(parents=True, exist_ok=True)
    (root / KILL_SWITCH_FILE).write_text("test\n", encoding="utf-8")
    journal = MemoryJournal()
    got = LiveRiskGate(root, journal, book=books)(make_intent(0), NOW)
    assert got.result == "REFUSE"
    assert got.reasons == ("kill_switch : kill switch engagé (R4)",)
    assert journal.entries[0]["payload"]["result"] == "REFUSE"


def test_a_journal_that_fails_refuses_the_order(tmp_path: Path) -> None:
    got = LiveRiskGate(project(tmp_path, live=LIVE), MemoryJournal(fail_at=1), book=books)(
        make_intent(0), NOW
    )
    assert got.result == "REFUSE"
    assert got.reasons == (
        "journal : journal d'audit indisponible (OSError) : aucune décision sans trace (R11)",
    )


def test_a_decision_time_later_than_the_book_day_refuses(tmp_path: Path) -> None:
    got = LiveRiskGate(project(tmp_path, live=LIVE), MemoryJournal(), book=books)(
        make_intent(0), NOW + timedelta(days=1)
    )
    assert "day" in {check.name for check in got.checks if not check.ok}


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
    gate = LiveRiskGate(root, journal, book=books)
    with pytest.raises(LiveGateRefused, match="aucun appel au courtier") as caught:
        live_adapter(approvals, client, gate, check=check).submit(intent, now=NOW)
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
    live = live_adapter(approvals, client, LiveRiskGate(root, journal, book=books), check=check)
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
    gate = LiveRiskGate(root, MemoryJournal(), book=books)
    assert live_adapter(approvals, client, gate, check=check).submit(intent, now=NOW).accepted
    assert client.calls == ["submit"]
    assert approvals.get(approval_id, now=NOW).state is ApprovalState.CONSOMMEE


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
    approvals: ApprovalStore, verdict: RiskGateResult, reason: str
) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    client = Client()
    live = live_adapter(approvals, client, lambda _intent, _now: verdict)
    with pytest.raises(LiveGateRefused) as caught:
        live.submit(intent, now=NOW)
    assert caught.value.reasons == (reason,)
    assert client.calls == []


def test_a_gate_that_raises_refuses(approvals: ApprovalStore) -> None:
    def broken(_intent: OrderIntent, _now: datetime) -> RiskGateResult:
        raise RuntimeError("panne")

    client = Client()
    with pytest.raises(LiveGateRefused, match=r"Porte live en erreur \(RuntimeError\)"):
        live_adapter(approvals, client, broken).submit(make_intent(0), now=NOW)
    assert client.calls == []


def test_the_gate_is_judged_on_the_adapter_clock(approvals: ApprovalStore) -> None:
    seen: list[datetime] = []

    def gate(_intent: OrderIntent, now: datetime) -> RiskGateResult:
        seen.append(now)
        return _verdict(result="REFUSE", quantity=0)

    with pytest.raises(LiveGateRefused):
        live_adapter(approvals, Client(), gate).submit(make_intent(0), now=NOW - timedelta(days=9))
    assert seen == [NOW]


def test_the_live_config_carries_the_gate_fields_only_when_written() -> None:
    shipped = load_config(REPO / "config").live
    assert (shipped.capital_reference_eur, shipped.timezone) == (None, None)
    marked = LiveConfig.model_validate(COMPLETE | {"capital_reference_eur": "A_DEFINIR"})
    assert marked.capital_reference_eur == "A_DEFINIR"
    with pytest.raises(ValueError, match="greater than 0"):
        LiveConfig.model_validate(COMPLETE | {"capital_reference_eur": 0})
