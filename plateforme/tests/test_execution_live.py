"""The live adapter's guard (ADR-036, D8, D9): no broker call unless all six conditions hold.

Every project here lives under ``tmp_path``: a copy of ``config/``, its own live file and
signatures, and a fake client. Nothing touches the real ``config/`` or ``governance/``.
"""

from __future__ import annotations

import dataclasses
import shutil
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml

from core.approvals.store import ApprovalRules, ApprovalState, ApprovalStore, Trail
from core.approvals.totp import totp
from core.config.loader import Config, ConfigError, LiveConfig, load_config
from core.execution.broker import AccountStatement, BrokerAck, BrokerAdapter, FillBatch
from core.execution.intent import OrderIntent
from core.execution.live import (
    LIVE_FILE,
    NO_LIVE_GATE,
    ActivationCheck,
    Condition,
    LiveAdapter,
    LiveDisabled,
    Verdict,
    live_incomplete,
    live_limits,
)
from core.governance.signatures import SIGNATURES_DIR
from core.policy.engine import KILL_SWITCH_FILE
from tests.execution_cases import MemoryJournal, make_intent
from tests.signing import sign

REPO = Path(__file__).resolve().parents[1]
KEY = b"12345678901234567890"
NOW = datetime(2026, 10, 21, 12, 0, 5, tzinfo=UTC)
RULES = ApprovalRules(
    expiry=timedelta(minutes=10),
    max_code_attempts=3,
    lockout_failures=5,
    lockout_window=timedelta(minutes=15),
)
COMPLETE: dict[str, Any] = {
    "enabled": True,
    "broker": "courtier-de-test",
    "limits": {
        "max_order_pct": 1,
        "max_position_pct": 5,
        "max_daily_loss_pct": 1,
        "max_orders_per_day": 2,
    },
    "allow": {"leverage": False, "short_selling": False, "derivatives": False},
    "instruments_whitelist": ["FR0010315770", "FICT-ACME"],
}
ALL_HOLD: Verdict = dict.fromkeys(Condition)


class Client:
    """A broker that records what reached it."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.hold: threading.Event | None = None  # set: submit waits for it
        self.error: Exception | None = None

    def submit(self, intent: OrderIntent, *, now: datetime) -> BrokerAck:
        self.calls.append("submit")
        if self.hold is not None:
            self.hold.wait(5)
        if self.error is not None:
            raise self.error
        return BrokerAck(intent.intent_id, True, "reçu")

    def cancel(self, intent_id: UUID, *, reason: str, now: datetime) -> bool:
        self.calls.append("cancel")
        return True

    def cancel_all(self, *, reason: str, now: datetime) -> tuple[UUID, ...]:
        self.calls.append("cancel_all")
        return ()

    def open_orders(self) -> tuple[Any, ...]:
        self.calls.append("open_orders")
        return ()

    def account_snapshot(self) -> AccountStatement:
        self.calls.append("account_snapshot")
        return AccountStatement(cash_eur=0)  # type: ignore[arg-type]

    def fills_since(self, cursor: int) -> FillBatch:
        self.calls.append("fills_since")
        return FillBatch((), cursor)


@pytest.fixture
def approvals() -> Iterator[ApprovalStore]:
    with ApprovalStore.memory(RULES, Trail(MemoryJournal(), "live-test")) as store:
        yield store


def project(
    root: Path,
    *,
    live: dict[str, Any] | None = None,
    written: str = "N3",
    signed: str | None = "N3",
    report: bool = True,
) -> Path:
    """A project under ``root``: the real configuration, then this test's live file and level."""
    shutil.copytree(REPO / "config", root / "config")
    (root / LIVE_FILE).write_text(
        yaml.safe_dump(COMPLETE if live is None else live), encoding="utf-8"
    )
    autonomy_file = root / "config" / "autonomy.yaml"
    autonomy = yaml.safe_load(autonomy_file.read_text(encoding="utf-8"))
    autonomy["domains"]["finance"]["level"] = written
    autonomy_file.write_text(yaml.safe_dump(autonomy, allow_unicode=True), encoding="utf-8")
    if signed is not None:
        sign(root, "finance", signed, report=report)  # type: ignore[arg-type]
    return root


def granted(
    store: ApprovalStore, intent: OrderIntent, *, environment: str = "live", sha: str = ""
) -> UUID:
    approval_id = store.request(
        intent_id=intent.intent_id,
        intent_sha256=sha or intent.sha256(),
        environment=environment,  # type: ignore[arg-type]
        gate={"quantity": 3, "reasons": []},
        summary="Achat de 3 CW8 à 512,40 EUR au plus",
        now=NOW,
    ).approval_id
    assert store.approve(approval_id, totp(KEY, NOW), key=KEY, now=NOW).accepted
    return approval_id


def adapter(
    root: Path,
    store: ApprovalStore,
    client: Client,
    *,
    owner: bool = True,
    timeout: float = 5.0,
    now: datetime = NOW,
) -> LiveAdapter:
    check = ActivationCheck(root, store, owner=lambda _path: owner, limits=gate_passes)
    return LiveAdapter(
        client, store, check, call_timeout_s=timeout, kill_target_s=10, clock=lambda: now
    )


def gate_passes(live: LiveConfig, intent: OrderIntent) -> str | None:
    """A live risk gate that accepts every whitelisted order: none exists yet (B353)."""
    reason = live_limits(live, intent)
    return None if reason == NO_LIVE_GATE else reason


def failing(caught: pytest.ExceptionInfo[LiveDisabled]) -> set[Condition]:
    return set(caught.value.conditions)


# All six hold ---------------------------------------------------------------------------------


def test_an_order_reaches_the_broker_when_all_six_conditions_hold(
    tmp_path: Path, approvals: ApprovalStore
) -> None:
    intent = make_intent(0)
    approval_id = granted(approvals, intent)
    client = Client()
    ack = adapter(project(tmp_path), approvals, client).submit(intent, now=NOW)
    assert ack.accepted
    assert client.calls == ["submit"]
    assert approvals.get(approval_id, now=NOW).state is ApprovalState.CONSOMMEE


def test_the_live_adapter_is_a_broker_adapter(tmp_path: Path, approvals: ApprovalStore) -> None:
    assert isinstance(adapter(tmp_path, approvals, Client()), BrokerAdapter)


def test_an_approval_is_spent_once(tmp_path: Path, approvals: ApprovalStore) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    client = Client()
    live = adapter(project(tmp_path), approvals, client)
    live.submit(intent, now=NOW)
    with pytest.raises(LiveDisabled) as caught:
        live.submit(intent, now=NOW)
    assert failing(caught) == {Condition.APPROBATION}
    assert client.calls == ["submit"]


# One condition fails ------------------------------------------------------------------------


def _off(live: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {**live, **changes}


@pytest.mark.parametrize(
    ("live", "reason"),
    [
        (_off(COMPLETE, enabled=False), "enabled = false (R3)"),
        (_off(COMPLETE, broker="A_DEFINIR"), "broker non défini (A_DEFINIR)"),
        (_off(COMPLETE, broker=" "), "broker non défini (vide)"),
        (_off(COMPLETE, broker=""), "broker non défini (vide)"),
        (
            _off(COMPLETE, limits={**COMPLETE["limits"], "max_orders_per_day": 0}),
            "limites à 0 : max_orders_per_day",
        ),
        (_off(COMPLETE, instruments_whitelist=[]), "liste blanche vide"),
    ],
    ids=["disabled", "marker", "blank", "empty", "zero-limit", "no-whitelist"],
)
def test_an_incomplete_live_file_refuses(
    tmp_path: Path, approvals: ApprovalStore, live: dict[str, Any], reason: str
) -> None:
    intent = make_intent(0)
    approval_id = granted(approvals, intent)
    client = Client()
    with pytest.raises(LiveDisabled, match="aucun appel au courtier") as caught:
        adapter(project(tmp_path, live=live), approvals, client).submit(intent, now=NOW)
    # An empty whitelist also fails the seventh condition, which reads it.
    assert caught.value.failures[0] == (Condition.CONFIGURATION, reason)
    assert failing(caught) <= {Condition.CONFIGURATION, Condition.LIMITES}
    assert client.calls == []
    assert approvals.get(approval_id, now=NOW).state is ApprovalState.ACCORDEE


def test_the_shipped_live_file_is_incomplete() -> None:
    assert live_incomplete(load_config(REPO / "config").live) == "enabled = false (R3)"


def test_a_file_the_current_account_owns_refuses(tmp_path: Path, approvals: ApprovalStore) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    root = project(tmp_path)
    seen: list[Path] = []

    def owner(path: Path) -> bool:
        seen.append(path)
        return path != root / SIGNATURES_DIR

    check = ActivationCheck(root, approvals, owner=owner, limits=gate_passes)
    live = LiveAdapter(
        Client(), approvals, check, call_timeout_s=5, kill_target_s=10, clock=lambda: NOW
    )
    with pytest.raises(LiveDisabled) as caught:
        live.submit(intent, now=NOW)
    assert caught.value.failures == (
        (Condition.ACL, "accès non protégé : governance/approvals (protect-live.ps1)"),
    )
    signature = root / SIGNATURES_DIR / "2026-10-21-finance-N3.md"
    assert seen == [root / LIVE_FILE, root / SIGNATURES_DIR, signature]


def test_a_signature_file_left_writable_is_named(tmp_path: Path, approvals: ApprovalStore) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    root = project(tmp_path)
    signature = root / SIGNATURES_DIR / "2026-10-21-finance-N3.md"
    check = ActivationCheck(
        root, approvals, owner=lambda path: path != signature, limits=gate_passes
    )
    live = LiveAdapter(
        Client(), approvals, check, call_timeout_s=5, kill_target_s=10, clock=lambda: NOW
    )
    with pytest.raises(LiveDisabled) as caught:
        live.submit(intent, now=NOW)
    assert caught.value.failures == (
        (
            Condition.ACL,
            "accès non protégé : governance/approvals/2026-10-21-finance-N3.md (protect-live.ps1)",
        ),
    )


def test_an_unreadable_signatures_folder_refuses(
    tmp_path: Path, approvals: ApprovalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    root = project(tmp_path)
    rglob = Path.rglob

    def denied(path: Path, pattern: str) -> Iterator[Path]:
        if path == root / SIGNATURES_DIR:
            raise PermissionError("refusé")
        return rglob(path, pattern)

    monkeypatch.setattr(Path, "rglob", denied)
    with pytest.raises(LiveDisabled) as caught:
        adapter(root, approvals, Client()).submit(intent, now=NOW)
    assert caught.value.failures == (
        (Condition.ACL, "contenu de governance/approvals illisible (PermissionError)"),
    )


def test_no_owner_at_all_names_both_paths(tmp_path: Path, approvals: ApprovalStore) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    with pytest.raises(LiveDisabled, match=r"config/live\.yaml, governance/approvals") as caught:
        adapter(project(tmp_path), approvals, Client(), owner=False).submit(intent, now=NOW)
    assert failing(caught) == {Condition.ACL}


@pytest.mark.parametrize(
    ("signed", "report"),
    [(None, True), ("N2", True), ("N3", False)],
    ids=["unsigned", "signed-n2", "report-missing"],
)
def test_without_a_valid_n3_signature_the_effective_level_falls_too(
    tmp_path: Path, approvals: ApprovalStore, signed: str | None, report: bool
) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    root = project(tmp_path, signed=signed, report=report)
    with pytest.raises(LiveDisabled) as caught:
        adapter(root, approvals, Client()).submit(intent, now=NOW)
    assert failing(caught) == {Condition.SIGNATURE, Condition.NIVEAU}


def test_a_written_level_below_n3_refuses_despite_the_signature(
    tmp_path: Path, approvals: ApprovalStore
) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    root = project(tmp_path, written="N2")
    with pytest.raises(LiveDisabled) as caught:
        adapter(root, approvals, Client()).submit(intent, now=NOW)
    assert caught.value.failures == ((Condition.NIVEAU, "niveau effectif N2, N3 requis"),)


def test_a_configuration_without_finance_refuses(tmp_path: Path, approvals: ApprovalStore) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    root = project(tmp_path)

    def load(directory: Path) -> Config:
        config = load_config(directory)
        domains = {k: v for k, v in config.autonomy.domains.items() if k != "finance"}
        return dataclasses.replace(
            config, autonomy=config.autonomy.model_copy(update={"domains": domains})
        )

    check = ActivationCheck(
        root, approvals, owner=lambda _path: True, load=load, limits=gate_passes
    )
    live = LiveAdapter(
        Client(), approvals, check, call_timeout_s=5, kill_target_s=10, clock=lambda: NOW
    )
    with pytest.raises(LiveDisabled) as caught:
        live.submit(intent, now=NOW)
    assert caught.value.failures == ((Condition.NIVEAU, "niveau effectif absent, N3 requis"),)


@pytest.mark.parametrize("error", [ConfigError("x"), OSError("x")], ids=["invalid", "unreadable"])
def test_an_unreadable_configuration_refuses(
    tmp_path: Path, approvals: ApprovalStore, error: Exception
) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    root = project(tmp_path)

    def load(_directory: Path) -> Config:
        raise error

    check = ActivationCheck(
        root, approvals, owner=lambda _path: True, load=load, limits=gate_passes
    )
    live = LiveAdapter(
        Client(), approvals, check, call_timeout_s=5, kill_target_s=10, clock=lambda: NOW
    )
    with pytest.raises(LiveDisabled) as caught:
        live.submit(intent, now=NOW)
    reason = f"configuration illisible ({type(error).__name__})"
    assert caught.value.failures == (
        (Condition.CONFIGURATION, reason),
        (Condition.LIMITES, reason),
        (Condition.NIVEAU, reason),
    )


def test_the_kill_switch_refuses(tmp_path: Path, approvals: ApprovalStore) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    root = project(tmp_path)
    (root / KILL_SWITCH_FILE).parent.mkdir(parents=True)
    (root / KILL_SWITCH_FILE).write_text("test", encoding="utf-8")
    client = Client()
    with pytest.raises(LiveDisabled) as caught:
        adapter(root, approvals, client).submit(intent, now=NOW)
    assert caught.value.failures == ((Condition.KILL_SWITCH, "kill switch engagé (R4)"),)
    assert client.calls == []


def test_an_intent_never_asked_about_refuses(tmp_path: Path, approvals: ApprovalStore) -> None:
    with pytest.raises(LiveDisabled) as caught:
        adapter(project(tmp_path), approvals, Client()).submit(make_intent(0), now=NOW)
    assert caught.value.failures == (
        (Condition.APPROBATION, "aucune demande d'approbation pour cette intention"),
    )


def test_a_paper_approval_does_not_open_live(tmp_path: Path, approvals: ApprovalStore) -> None:
    intent = make_intent(0)
    granted(approvals, intent, environment="paper")
    with pytest.raises(LiveDisabled, match="demandée pour paper, pas pour live") as caught:
        adapter(project(tmp_path), approvals, Client()).submit(intent, now=NOW)
    assert failing(caught) == {Condition.APPROBATION}


def test_an_overdue_approval_refuses(tmp_path: Path, approvals: ApprovalStore) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    later = NOW + RULES.expiry
    with pytest.raises(LiveDisabled, match="approbation EXPIREE") as caught:
        adapter(project(tmp_path), approvals, Client(), now=later).submit(intent, now=NOW)
    assert failing(caught) == {Condition.APPROBATION}


def test_an_approval_for_other_content_refuses(tmp_path: Path, approvals: ApprovalStore) -> None:
    intent = make_intent(0)
    granted(approvals, intent, sha="b" * 64)
    with pytest.raises(LiveDisabled, match="un autre contenu") as caught:
        adapter(project(tmp_path), approvals, Client()).submit(intent, now=NOW)
    assert failing(caught) == {Condition.APPROBATION}


# The adapter around the check -------------------------------------------------------------


def fixed(verdict: Verdict) -> Any:
    return lambda _intent, _now: verdict


def test_a_condition_left_out_of_the_verdict_refuses(approvals: ApprovalStore) -> None:
    verdict = {c: None for c in Condition if c is not Condition.ACL}
    live = LiveAdapter(
        Client(), approvals, fixed(verdict), call_timeout_s=5, kill_target_s=10, clock=lambda: NOW
    )
    with pytest.raises(LiveDisabled) as caught:
        live.submit(make_intent(0), now=NOW)
    assert caught.value.failures == ((Condition.ACL, "condition non évaluée"),)


def test_a_request_gone_before_sending_refuses(approvals: ApprovalStore) -> None:
    client = Client()
    live = LiveAdapter(
        client, approvals, fixed(ALL_HOLD), call_timeout_s=5, kill_target_s=10, clock=lambda: NOW
    )
    with pytest.raises(LiveDisabled, match="demande disparue") as caught:
        live.submit(make_intent(0), now=NOW)
    assert failing(caught) == {Condition.APPROBATION}
    assert client.calls == []


def test_an_approval_that_cannot_be_spent_refuses(approvals: ApprovalStore) -> None:
    intent = make_intent(0)
    granted(approvals, intent, sha="b" * 64)  # consume refuses another content
    client = Client()
    live = LiveAdapter(
        client, approvals, fixed(ALL_HOLD), call_timeout_s=5, kill_target_s=10, clock=lambda: NOW
    )
    with pytest.raises(LiveDisabled, match="autre intention") as caught:
        live.submit(intent, now=NOW)
    assert failing(caught) == {Condition.APPROBATION}
    assert client.calls == []


def test_cancelling_and_reading_need_no_condition(approvals: ApprovalStore) -> None:
    def refuse(_intent: OrderIntent, _now: datetime) -> Verdict:
        raise AssertionError("the check is for submissions only")

    client = Client()
    live = LiveAdapter(
        client, approvals, refuse, call_timeout_s=5, kill_target_s=10, clock=lambda: NOW
    )
    assert live.cancel_all(reason="kill switch", now=NOW) == ()
    assert live.cancel(make_intent(0).intent_id, reason="test", now=NOW)
    assert live.open_orders() == ()
    assert live.account_snapshot().cursor == 0
    assert live.fills_since(7).cursor == 7
    assert client.calls == [
        "cancel_all",
        "cancel",
        "open_orders",
        "account_snapshot",
        "fills_since",
    ]


def test_a_broker_that_does_not_answer_times_out(approvals: ApprovalStore) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    client = Client()
    client.hold = threading.Event()
    live = LiveAdapter(
        client, approvals, fixed(ALL_HOLD), call_timeout_s=0.05, kill_target_s=1, clock=lambda: NOW
    )
    try:
        with pytest.raises(TimeoutError, match=r"submit sans réponse après 0\.05 s"):
            live.submit(intent, now=NOW)
    finally:
        client.hold.set()
    assert live.cancel_all(reason="kill switch", now=NOW) == ()  # the next call does not wait


def test_a_broker_error_reaches_the_caller(approvals: ApprovalStore) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    client = Client()
    client.error = ConnectionError("coupé")
    live = LiveAdapter(
        client, approvals, fixed(ALL_HOLD), call_timeout_s=5, kill_target_s=10, clock=lambda: NOW
    )
    with pytest.raises(ConnectionError, match="coupé"):
        live.submit(intent, now=NOW)


@pytest.mark.parametrize(
    ("timeout", "target", "message"),
    [
        (0.0, None, "> 0"),
        (-1.0, None, "> 0"),
        (float("nan"), None, "> 0"),
        (float("inf"), None, "> 0"),
        (2.0, 2.0, "sous la cible du kill switch"),
        (3.0, 2.0, "sous la cible du kill switch"),
        (1.0, None, "cible du kill switch inconnue"),  # still A_DEFINIR (R4, R7)
        (1.0, float("nan"), "cible du kill switch inconnue"),
        (1.0, float("inf"), "cible du kill switch inconnue"),
    ],
)
def test_the_timeout_stays_under_the_kill_switch_target(
    approvals: ApprovalStore, timeout: float, target: float | None, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        LiveAdapter(
            Client(), approvals, fixed(ALL_HOLD), call_timeout_s=timeout, kill_target_s=target
        )


# The seventh condition and the adapter's clock (B200, B230, ADR-067) ---------------------------


def test_without_a_live_gate_every_order_is_refused(
    tmp_path: Path, approvals: ApprovalStore
) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    client = Client()
    check = ActivationCheck(project(tmp_path), approvals, owner=lambda _path: True)
    live = LiveAdapter(
        client, approvals, check, call_timeout_s=5, kill_target_s=10, clock=lambda: NOW
    )
    with pytest.raises(LiveDisabled) as caught:
        live.submit(intent, now=NOW)
    assert caught.value.failures == ((Condition.LIMITES, NO_LIVE_GATE),)
    assert client.calls == []


def test_an_instrument_off_the_whitelist_is_refused(
    tmp_path: Path, approvals: ApprovalStore
) -> None:
    intent = make_intent(0)
    granted(approvals, intent)
    client = Client()
    root = project(tmp_path, live={**COMPLETE, "instruments_whitelist": ["FR0010315770"]})
    with pytest.raises(LiveDisabled) as caught:
        adapter(root, approvals, client).submit(intent, now=NOW)
    assert caught.value.failures == ((Condition.LIMITES, "FICT-ACME hors de la liste blanche"),)
    assert client.calls == []


def test_the_adapter_reads_its_own_clock(tmp_path: Path, approvals: ApprovalStore) -> None:
    """A caller passing an earlier time cannot revive an expired approval (B230)."""
    intent = make_intent(0)
    granted(approvals, intent)
    client = Client()
    check = ActivationCheck(
        project(tmp_path), approvals, owner=lambda _path: True, limits=gate_passes
    )
    later = NOW + timedelta(days=30)
    live = LiveAdapter(
        client, approvals, check, call_timeout_s=5, kill_target_s=10, clock=lambda: later
    )
    with pytest.raises(LiveDisabled) as caught:
        live.submit(intent, now=NOW)
    assert failing(caught) == {Condition.APPROBATION}
    assert client.calls == []
