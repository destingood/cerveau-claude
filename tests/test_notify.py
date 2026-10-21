"""Alerts (ADR-038, B46, B172): minimal content, ntfy, the Discord outbox, never blocking.

No test reaches the network: ntfy answers through ``httpx.MockTransport``, and conftest removes
Lucas's NTFY_TOPIC and NTFY_TOKEN from every test's environment.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from core.audit import AuditJournal
from core.audit.chain import verify
from core.budget import BudgetExceededError, BudgetGate
from core.config import load_config
from core.config.loader import NtfySettings
from core.execution import loop
from core.finance.portfolio import Gap
from core.notify import (
    ALERT_KINDS,
    NOTIFICATION_KEY,
    Alert,
    Alerts,
    DiscordOutbox,
    alerts_from,
    as_ref,
    budget_severity,
    default_outbox_path,
    read_outbox,
    stop_alerts,
)
from core.notify.alerts import LABELS, SEVERITIES
from core.notify.ntfy import NtfyError, NtfyNotifier, ntfy_from
from core.policy.engine import kill_switch_engaged
from interfaces.cli.main import app
from tests.execution_cases import MemoryJournal
from tests.test_budget import _budgeted, _spend
from tests.test_execution_kill_switch import Broker, booked, sent_order, stopped
from tests.test_execution_loop import MONDAY_RUN, World

NOW = datetime(2026, 10, 21, 14, 30, tzinfo=UTC)
SERVER = "https://ntfy.example"
TOPIC = "cerveau-essai-" + "0123456789" * 2  # 34 characters, made up for the tests
BEARER = "tk_" + "a" * 29  # made up, never a real token
runner = CliRunner()


class Channel:
    """A channel that keeps what it receives, or raises ``fails``."""

    def __init__(self, channel: str = "essai", fails: Exception | None = None) -> None:
        self.channel = channel
        self.fails = fails
        self.received: list[Alert] = []

    def send(self, alert: Alert) -> None:
        self.received.append(alert)
        if self.fails is not None:
            raise self.fails

    @property
    def kinds(self) -> list[str]:
        return [alert.kind for alert in self.received]


class Mock:
    """ntfy's side: every request kept, one scripted answer."""

    def __init__(self, status: int = 200, raises: Exception | None = None) -> None:
        self.status = status
        self.raises = raises
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raises is not None:
            raise self.raises
        headers = {"Location": "https://ailleurs.example/"} if self.status == 302 else None
        return httpx.Response(self.status, headers=headers, json={})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def ntfy(mock: Mock, token: str | None = None) -> NtfyNotifier:
    return NtfyNotifier(SERVER, TOPIC, token=token, timeout_seconds=3, transport=mock.transport)


def notifications(journal: MemoryJournal) -> list[dict[str, Any]]:
    return [
        e["payload"][NOTIFICATION_KEY]
        for e in journal.entries
        if e["event"] == "POLICY" and NOTIFICATION_KEY in e["payload"]
    ]


def interfaces(config_dir: Path, *, defined: bool = True) -> Path:
    """The interfaces defined (a bot, a local port, an https ntfy server) or all to define."""
    path = config_dir / "interfaces.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["discord"]["owner_user_id"] = "123456789012345678" if defined else "A_DEFINIR"
    data["api"]["port"] = 8765 if defined else "A_DEFINIR"
    data["ntfy"]["server"] = SERVER if defined else "A_DEFINIR"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return config_dir


# --- the alert: a kind, a severity, an identifier, never an amount (D14) -----------------------


def test_every_kind_has_a_label_and_a_severity() -> None:
    assert set(LABELS) == set(SEVERITIES) == set(ALERT_KINDS)
    assert all(1 <= severity <= 5 for severity in SEVERITIES.values())


def test_an_alert_says_its_kind_severity_identifier_and_time_in_utc() -> None:
    paris = datetime(2026, 10, 21, 16, 30, tzinfo=timezone(timedelta(hours=2)))
    alert = Alert.of("budget", "jour-2026-10-21-80", paris, severity=4)
    assert alert.title == "CERVEAU budget" and alert.title.isascii()
    assert alert.text() == (
        "seuil de budget atteint ; gravité 4/5 ; réf. jour-2026-10-21-80 ; 21/10/2026 14:30 UTC"
    )
    assert alert.to_payload() == {"kind": "budget", "severity": 4, "ref": "jour-2026-10-21-80"}
    assert Alert.of("kill_switch", "kill-1", NOW).severity == 5


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "autre"},
        {"severity": 0},
        {"severity": 6},
        {"severity": True},
        {"ref": ""},
        {"ref": "a b"},
        {"ref": "montant-12,50€"},
        {"ref": "-x"},
        {"ref": "x" * 65},
        {"at": datetime(2026, 10, 21, 14, 30)},  # the naive time refused
    ],
)
def test_an_alert_refuses_what_it_may_not_carry(changes: dict[str, Any]) -> None:
    fields: dict[str, Any] = {"kind": "kill_switch", "severity": 5, "ref": "kill-1", "at": NOW}
    with pytest.raises(ValueError):
        Alert(**(fields | changes))


@pytest.mark.parametrize(
    ("text", "ref"),
    [
        ("kill-2026 10:21/é", "kill-2026_10:21__"),
        ("", "inconnu"),
        ("_x", "inconnu"),
        ("x" * 70, "x" * 64),
        ("6f1c2a5e-3b1d-4c55-9b0e-0a1b2c3d4e5f", "6f1c2a5e-3b1d-4c55-9b0e-0a1b2c3d4e5f"),
    ],
)
def test_a_reference_keeps_only_identifier_characters(text: str, ref: str) -> None:
    assert as_ref(text) == ref


@pytest.mark.parametrize(
    ("trigger", "kind"),
    [
        ("commande", "kill_switch"),
        ("fichier", "kill_switch"),
        ("perte_donnees", "kill_switch"),
        ("incident_execution", "incident_execution"),
        ("limite", "limite_depassee"),
        ("drawdown", "limite_depassee"),
    ],
)
def test_a_stop_is_one_alert_then_one_per_unconfirmed_cancellation(trigger: str, kind: str) -> None:
    orders = (UUID(int=1), UUID(int=2))
    alerts = stop_alerts(trigger, "kill-1", orders, NOW)
    unconfirmed = "annulation_non_confirmee"
    assert [a.kind for a in alerts] == [kind, unconfirmed, unconfirmed]
    assert [a.ref for a in alerts] == ["kill-1", str(orders[0]), str(orders[1])]
    assert {a.severity for a in alerts} == {5}


@pytest.mark.parametrize(("pct", "severity"), [(50, 3), (79, 3), (80, 4), (100, 5), (120, 5)])
def test_a_budget_alert_grows_more_urgent(pct: int, severity: int) -> None:
    assert budget_severity(pct) == severity


# --- Alerts: every channel, one journal entry per alert, never raises -------------------------


def test_without_any_channel_nothing_is_sent_nor_written() -> None:
    journal = MemoryJournal()
    alert = Alert.of("kill_switch", "kill-1", NOW)
    assert Alerts().send([alert], journal=journal, actor="policy", request_id="r1") == ()
    assert journal.entries == []


def test_a_failing_channel_never_stops_the_others_and_is_journaled_by_type() -> None:
    journal = MemoryJournal()
    good = Channel("discord")
    bad = Channel("ntfy", RuntimeError(f"échec vers {TOPIC}"))
    alerts = [Alert.of("kill_switch", "kill-1", NOW), Alert.of("budget", "jour-x-50", NOW)]
    failures = Alerts((bad, good)).send(
        alerts, journal=journal, actor="policy", request_id="r1", versions={"config": "c"}
    )
    assert failures == ("ntfy : RuntimeError", "ntfy : RuntimeError")
    assert good.kinds == bad.kinds == ["kill_switch", "budget"]
    assert [(e["actor"], e["event"], e["request_id"]) for e in journal.entries] == [
        ("policy", "POLICY", "r1"),
        ("policy", "POLICY", "r1"),
    ]
    assert notifications(journal)[0] == {
        "kind": "kill_switch",
        "severity": 5,
        "ref": "kill-1",
        "sent": ["discord"],
        "failed": {"ntfy": "RuntimeError"},
    }
    assert TOPIC not in repr(journal.entries)  # the error's text is never kept


def test_a_journal_that_refuses_is_a_failure_not_an_exception() -> None:
    channel = Channel()
    failures = Alerts((channel,)).send(
        [Alert.of("kill_switch", "kill-1", NOW)],
        journal=MemoryJournal(fail_at=1),
        actor="policy",
        request_id="r1",
    )
    assert failures == ("journal : OSError",)
    assert channel.kinds == ["kill_switch"]


def test_without_a_journal_the_alert_still_leaves() -> None:
    channel = Channel()
    sent = Alerts((channel,)).send(
        [Alert.of("rapport_quotidien", "2026-10-21", NOW)],
        journal=None,
        actor="policy",
        request_id=None,
    )
    assert sent == () and channel.kinds == ["rapport_quotidien"]


def test_a_notification_entry_keeps_the_audit_chain(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path / "audit" / "journal.jsonl")
    Alerts((Channel(),)).send(
        [Alert.of("kill_switch", "kill-1", NOW)], journal=journal, actor="policy", request_id="r1"
    )
    assert verify(journal.path).ok


# --- ntfy (docs.ntfy.sh/publish) --------------------------------------------------------------


def test_ntfy_posts_the_text_with_title_priority_and_tags() -> None:
    mock = Mock()
    alert = Alert.of("kill_switch", "kill-1", NOW)
    ntfy(mock).send(alert)
    [request] = mock.requests
    assert request.method == "POST"
    assert str(request.url) == f"{SERVER}/{TOPIC}"
    assert request.headers["X-Title"] == "CERVEAU kill_switch"
    assert request.headers["X-Priority"] == "5"
    assert request.headers["X-Tags"] == "cerveau,kill_switch"
    assert "authorization" not in request.headers
    assert request.content.decode("utf-8") == alert.text()
    assert request.extensions["timeout"]["connect"] == 3


def test_ntfy_sends_the_token_as_a_bearer() -> None:
    mock = Mock()
    ntfy(mock, token=BEARER).send(Alert.of("budget", "jour-x-50", NOW))
    assert mock.requests[0].headers["Authorization"] == f"Bearer {BEARER}"


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_ntfy_refusing_or_redirecting_raises_with_the_code_only(status: int) -> None:
    mock = Mock(status)
    with pytest.raises(NtfyError) as err:
        ntfy(mock, token=BEARER).send(Alert.of("kill_switch", "kill-1", NOW))
    assert err.value.status_code == status
    assert str(err.value) == f"ntfy a répondu {status}"
    assert len(mock.requests) == 1  # a redirect is never followed
    assert TOPIC not in str(err.value) and BEARER not in str(err.value)


def test_ntfy_unreachable_is_a_failure_of_the_channel() -> None:
    mock = Mock(raises=httpx.ConnectTimeout("délai dépassé"))
    failures = Alerts((ntfy(mock),)).send(
        [Alert.of("kill_switch", "kill-1", NOW)],
        journal=MemoryJournal(),
        actor="policy",
        request_id="r1",
    )
    assert failures == ("ntfy : ConnectTimeout",)


def test_ntfy_hides_its_topic_and_token() -> None:
    shown = repr(ntfy(Mock(), token=BEARER))
    assert TOPIC not in shown and BEARER not in shown


@pytest.mark.parametrize("topic", ["zz", "x" * 31, "x" * 65, "sujet avec espaces " * 2, "é" * 32])
def test_ntfy_refuses_a_short_or_odd_topic_without_quoting_it(topic: str) -> None:
    with pytest.raises(ValueError) as err:
        NtfyNotifier(SERVER, topic, token=None, timeout_seconds=3)
    assert topic not in str(err.value)


@pytest.mark.parametrize("token", ["", "a b", "jeton-é", "x" * 257])
def test_ntfy_refuses_a_token_that_is_no_header_value(token: str) -> None:
    with pytest.raises(ValueError, match="jeton ntfy invalide"):
        NtfyNotifier(SERVER, TOPIC, token=token, timeout_seconds=3)


def test_ntfy_from_says_why_it_is_off_without_any_secret() -> None:
    undefined = NtfySettings(server="A_DEFINIR", timeout_seconds=3)
    defined = NtfySettings(server=SERVER, timeout_seconds=3)
    assert ntfy_from(undefined, {"NTFY_TOPIC": TOPIC}) == (
        None,
        "serveur ntfy à définir dans config/interfaces.yaml (R7)",
    )
    assert ntfy_from(defined, {}) == (None, "NTFY_TOPIC absente de l'environnement")
    notifier, why = ntfy_from(defined, {"NTFY_TOPIC": "zz"})
    assert notifier is None and why is not None
    assert why.endswith("(NTFY_TOPIC ou NTFY_TOKEN)") and "zz" not in why


def test_ntfy_from_builds_the_channel_from_the_environment() -> None:
    mock = Mock()
    settings = NtfySettings(server=SERVER, timeout_seconds=2)
    notifier, why = ntfy_from(
        settings, {"NTFY_TOPIC": TOPIC, "NTFY_TOKEN": ""}, transport=mock.transport
    )
    assert why is None and notifier is not None
    notifier.send(Alert.of("kill_switch", "kill-1", NOW))
    assert "authorization" not in mock.requests[0].headers  # an empty token is no token
    assert mock.requests[0].extensions["timeout"]["read"] == 2


# --- the Discord outbox -------------------------------------------------------------------------


def test_the_outbox_lives_under_var_notify(tmp_path: Path) -> None:
    assert default_outbox_path(tmp_path) == tmp_path / "var" / "notify" / "outbox.db"


def test_the_outbox_hands_the_alerts_in_order_after_a_sequence(tmp_path: Path) -> None:
    path = tmp_path / "dossier é" / "outbox.db"
    first = Alert.of("kill_switch", "kill-1", NOW)
    second = Alert.of("budget", "jour-2026-10-21-50", NOW + timedelta(minutes=1))
    outbox = DiscordOutbox(path)
    outbox.send(first)
    outbox.send(second)
    assert [(p.seq, p.alert) for p in read_outbox(path)] == [(1, first), (2, second)]
    assert [p.alert for p in read_outbox(path, after=1)] == [second]
    assert [p.alert for p in read_outbox(path, limit=1)] == [first]
    assert read_outbox(path, after=2) == []


def test_an_absent_outbox_is_empty_and_not_created(tmp_path: Path) -> None:
    path = default_outbox_path(tmp_path)
    assert read_outbox(path) == []
    assert not path.exists()


@pytest.mark.parametrize(
    "statement", ["UPDATE alerts SET severity = 1", "DELETE FROM alerts WHERE seq = 1"]
)
def test_the_outbox_is_append_only(tmp_path: Path, statement: str) -> None:
    path = tmp_path / "outbox.db"
    DiscordOutbox(path).send(Alert.of("kill_switch", "kill-1", NOW))
    conn = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="ajout seul"):
            conn.execute(statement)
    finally:
        conn.close()
    assert len(read_outbox(path)) == 1


# --- the channels from the configuration (D23) ------------------------------------------------


def test_an_invalid_configuration_leaves_the_journal_and_the_console(tmp_path: Path) -> None:
    alerts, notes = alerts_from(None, tmp_path, {"NTFY_TOPIC": TOPIC})
    assert alerts.channels == ()
    assert notes == ["configuration invalide : alertes au journal et à la console seulement"]


def test_interfaces_to_define_give_no_channel(tmp_path: Path, config_dir: Path) -> None:
    config = load_config(interfaces(config_dir, defined=False))
    alerts, notes = alerts_from(config, tmp_path, {"NTFY_TOPIC": TOPIC})
    assert alerts.channels == ()
    assert notes == [
        "alertes ntfy coupées : serveur ntfy à définir dans config/interfaces.yaml (R7)",
        "alertes Discord coupées : bot et API à définir dans config/interfaces.yaml",
    ]


def test_defined_interfaces_give_ntfy_and_the_outbox(tmp_path: Path, config_dir: Path) -> None:
    config = load_config(interfaces(config_dir))
    alerts, notes = alerts_from(config, tmp_path, {"NTFY_TOPIC": TOPIC})
    assert notes == []
    assert [c.channel for c in alerts.channels] == ["ntfy", "discord"]
    assert alerts.channels[1] == DiscordOutbox(default_outbox_path(tmp_path))


# --- the stop (B172), the loop's gap, the budget (B46) ----------------------------------------


def test_a_stop_is_alerted_once_in_force_and_a_failing_channel_never_holds_it(
    tmp_path: Path,
) -> None:
    journal = MemoryJournal()
    book = booked(MemoryJournal())
    order = sent_order(book, 0)
    in_force: list[bool] = []

    class Watching(Channel):
        def send(self, alert: Alert) -> None:
            in_force.append(kill_switch_engaged(tmp_path))
            super().send(alert)

    good, bad = Watching("discord"), Channel("ntfy", RuntimeError("hors ligne"))
    adapter = Broker(cancel_all=[ConnectionError("x")] * 3, working=ConnectionError("y"))
    stop = stopped(
        tmp_path, journal=journal, adapter=adapter, book=book, alerts=Alerts((bad, good))
    )
    assert stop.persisted and stop.unconfirmed == (order,)
    assert good.kinds == ["kill_switch", "annulation_non_confirmee"]
    assert [a.ref for a in good.received] == ["kill-test", str(order)]
    assert in_force == [True, True]  # the KILL file was written before any alert
    assert stop.alerts_failed == ("ntfy : RuntimeError", "ntfy : RuntimeError")
    events = [e["event"] for e in journal.entries]
    assert events.index("POLICY") > max(i for i, e in enumerate(events) if e == "KILL")
    assert [n["sent"] for n in notifications(journal)] == [["discord"], ["discord"]]


def test_a_loss_limit_stop_is_its_own_kind(tmp_path: Path) -> None:
    channel = Channel()
    stopped(tmp_path, trigger="limite", alerts=Alerts((channel,)))
    assert channel.kinds == ["limite_depassee"]


def test_alerts_that_raise_never_hold_the_stop(tmp_path: Path) -> None:
    class Exploding(Alerts):
        def send(self, *args: Any, **kwargs: Any) -> tuple[str, ...]:
            raise TypeError("panne")

    stop = stopped(tmp_path, alerts=Exploding())
    assert stop.persisted and stop.alerts_failed == ("alertes : TypeError",)
    assert stopped(tmp_path / "autre").alerts_failed == ()


def test_a_reconciliation_gap_is_alerted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = loop.settle

    def gapped(*args: Any, **kwargs: Any) -> Any:
        gap = Gap("paper", "security", "FICT-ACME", Decimal(1), Decimal(0))
        return replace(real(*args, **kwargs), gaps=(gap,))

    clean = World(tmp_path / "propre")
    channel = Channel("discord")
    clean.env.alerts = Alerts((channel,))
    report = clean.run(MONDAY_RUN)
    clean.store.close()
    assert report.reconciliation is not None and report.reconciliation.clean
    assert channel.kinds == []  # a clean reconciliation is not alerted

    monkeypatch.setattr(loop, "settle", gapped)
    world = World(tmp_path / "ecart")
    world.env.alerts = Alerts((Channel("ntfy", RuntimeError("hors ligne")), channel))
    report = world.run(MONDAY_RUN)
    world.store.close()
    assert report.reconciliation is not None and not report.reconciliation.clean
    assert channel.kinds == ["ecart_reconciliation"]
    assert channel.received[0].ref == "loop-test"
    assert "alerte non envoyée (ntfy : RuntimeError)" in report.notes


def test_each_budget_threshold_is_alerted_once_without_an_amount(
    config_dir: Path, tmp_path: Path
) -> None:
    journal = AuditJournal(tmp_path / "audit" / "journal.jsonl")
    channel = Channel()
    gate = BudgetGate(_budgeted(config_dir), journal, tz=UTC, alerts=Alerts((channel,)))
    at = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    _spend(journal, "0.50", at)
    gate.check(now=at, request_id="r1")
    gate.check(now=at, request_id="r2")  # already alerted
    _spend(journal, "0.30", at)
    gate.check(now=at)
    _spend(journal, "0.20", at)
    with pytest.raises(BudgetExceededError):
        gate.check(now=at)
    assert [(a.ref, a.severity) for a in channel.received] == [
        ("jour-2026-10-18-50", 3),
        ("jour-2026-10-18-80", 4),
        ("jour-2026-10-18-100", 5),
    ]
    assert all("€" not in a.text() and "0.50" not in a.text() for a in channel.received)
    assert gate.status(now=at).spending.alerts  # the notifications never trouble the ledger
    assert verify(journal.path).ok


# --- the CLI says which channel is off --------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    root.mkdir()
    monkeypatch.setenv("CERVEAU_HOME", str(root))
    return root


def test_cerveau_kill_says_which_channels_are_off(home: Path, config_dir: Path) -> None:
    undefined = interfaces(config_dir, defined=False)
    result = runner.invoke(app, ["kill", "--config-dir", str(undefined)])
    assert result.exit_code == 0, result.output
    assert "AVERTISSEMENT : alertes ntfy coupées : serveur ntfy à définir" in result.stderr
    assert "AVERTISSEMENT : alertes Discord coupées" in result.stderr
    assert read_outbox(default_outbox_path(home)) == []


def test_cerveau_kill_writes_the_stop_to_the_discord_outbox(home: Path, config_dir: Path) -> None:
    result = runner.invoke(app, ["kill", "--config-dir", str(interfaces(config_dir))])
    assert result.exit_code == 0, result.output
    assert "AVERTISSEMENT : alertes ntfy coupées : NTFY_TOPIC absente" in result.stderr
    assert "Discord" not in result.stderr
    [posted] = read_outbox(default_outbox_path(home))
    assert posted.alert.kind == "kill_switch" and posted.alert.ref.startswith("kill-")


def test_cerveau_kill_with_an_invalid_configuration_still_says_so(
    home: Path, tmp_path: Path
) -> None:
    result = runner.invoke(app, ["kill", "--config-dir", str(tmp_path / "nulle-part")])
    assert "AVERTISSEMENT : configuration invalide : alertes au journal" in result.stderr
    assert kill_switch_engaged(home)


@pytest.mark.parametrize("defined", [True, False])
def test_config_check_lists_the_alert_channels(config_dir: Path, defined: bool) -> None:
    result = runner.invoke(
        app, ["config", "check", "--config-dir", str(interfaces(config_dir, defined=defined))]
    )
    assert result.exit_code == 0, result.output
    if defined:
        assert "Canaux d'alerte (ADR-038) : discord\n" in result.stdout
        assert "  ⚠ alertes ntfy coupées : NTFY_TOPIC absente de l'environnement" in result.stdout
    else:
        assert "Canaux d'alerte (ADR-038) : aucun (journal et console)" in result.stdout
        assert "  ⚠ alertes Discord coupées : bot et API à définir" in result.stdout
