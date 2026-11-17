"""The local internal API (D1, ADR-037): a token on every route, the loopback only, no rearm,
no amount but in an approval's summary, and a one-time code never echoed."""

from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
import uvicorn
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from core.approvals.store import ApprovalError, ApprovalRules, ApprovalState, ApprovalStore, Trail
from core.approvals.store import default_store_path as approvals_path
from core.approvals.totp import SECRET_ENV, totp
from core.audit import AuditJournal, default_journal_path
from core.config import load_config
from core.execution.book import default_book_path
from core.execution.loop import (
    DayReport,
    LoopLog,
    SendOutcome,
    Valuation,
    default_loop_path,
)
from core.execution.reconcile import default_log_path
from core.execution.states import OrderState
from core.execution.uuid7 import uuid7
from core.notify import default_outbox_path
from core.policy.engine import kill_switch_engaged
from interfaces.api import MIN_TOKEN_CHARS, TOKEN_ENV, ApiError, create_app
from interfaces.cli.main import app as cli
from tests.test_notify import interfaces

TOKEN = "t" * 40
KEY = b"12345678901234567890"  # RFC 6238's published test key
SECRET = base64.b32encode(KEY).decode("ascii")
NOW = datetime(2026, 10, 21, 12, 0, 5, tzinfo=UTC)
FRIDAY, MONDAY = date(2026, 10, 16), date(2026, 10, 19)
SUMMARY = "Achat de 3 CW8 à 512,40 EUR au plus"
ENVIRON = {TOKEN_ENV: TOKEN, SECRET_ENV: SECRET}
ROUTES = [
    ("GET", "/status"),
    ("POST", "/kill"),
    ("GET", "/approvals/pending"),
    ("POST", f"/approvals/{uuid7()}/approve"),
    ("POST", f"/approvals/{uuid7()}/refuse"),
    ("GET", "/reports/daily"),
    ("GET", "/alerts"),
    ("POST", "/events/ignored"),
    ("GET", "/bot/settings"),
]
runner = CliRunner()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def defined(config_dir: Path) -> Path:
    """The bot and the API defined: alerts go to the Discord outbox as well."""
    return interfaces(config_dir)


def client(
    root: Path,
    config_dir: Path,
    *,
    environ: dict[str, str] | None = None,
    base_url: str = "http://127.0.0.1",
    token: str | None = TOKEN,
    **kwargs: Any,
) -> TestClient:
    app = create_app(
        root, environ=ENVIRON if environ is None else environ, config_dir=config_dir,
        clock=lambda: NOW, **kwargs,
    )  # fmt: skip
    opened = TestClient(app, base_url=base_url)
    if token is not None:
        opened.headers["Authorization"] = f"Bearer {token}"
    return opened


def ask(root: Path, config_dir: Path, *, summary: str = SUMMARY) -> UUID:
    config = load_config(config_dir)
    rules = ApprovalRules.from_config(config.autonomy.approval)
    trail = Trail(AuditJournal(default_journal_path(root)), "api-test")
    with ApprovalStore.open(approvals_path(root), rules=rules, trail=trail) as store:
        return store.request(
            intent_id=uuid7(),
            intent_sha256="a" * 64,
            environment="paper",
            gate={
                "result": "accepte",
                "requested_quantity": 4,
                "quantity": 3,
                "checks": [{"name": "liquidite", "ok": True}, {"name": "secteur", "ok": False}],
            },
            summary=summary,
            now=NOW,
        ).approval_id


def code(*, right: bool = True) -> str:
    valid = {totp(KEY, NOW + timedelta(seconds=30 * step)) for step in (-1, 0, 1)}
    if right:
        return totp(KEY, NOW)
    return next(c for c in (str(d) * 6 for d in range(10)) if c not in valid)


def entries(root: Path) -> list[dict[str, Any]]:
    path = default_journal_path(root)
    journal = AuditJournal(path)
    read = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for entry in read:
        ref = entry["payload_ref"]
        entry["payload"] = None if ref is None else journal.read_payload(ref)
    return read


# --- the door: a token, the loopback, nothing else ------------------------------------------


@pytest.mark.parametrize("environ", [{}, {TOKEN_ENV: ""}, {TOKEN_ENV: "x" * (MIN_TOKEN_CHARS - 1)}])
def test_without_a_long_enough_token_the_api_does_not_start(
    root: Path, environ: dict[str, str]
) -> None:
    with pytest.raises(ApiError, match=TOKEN_ENV):
        create_app(root, environ=environ)


def test_a_token_of_the_minimum_length_starts_it(root: Path) -> None:
    assert create_app(root, environ={TOKEN_ENV: "x" * MIN_TOKEN_CHARS})


@pytest.mark.parametrize(("method", "path"), ROUTES)
@pytest.mark.parametrize(
    "header",
    [
        None,
        "Bearer wrong",
        f"Basic {TOKEN}",
        "Basic " + base64.b64encode(f"owner:{TOKEN}".encode()).decode(),  # dashboard only
        f"Bearer {TOKEN}x",
    ],
)
def test_every_route_needs_the_token(
    root: Path, config_dir: Path, method: str, path: str, header: str | None
) -> None:
    opened = client(root, config_dir, token=None)
    headers = {} if header is None else {"Authorization": header}
    response = opened.request(method, path, headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {"detail": "jeton absent ou invalide"}
    assert not kill_switch_engaged(root)
    assert not default_journal_path(root).exists()


def test_no_documentation_no_schema_and_no_rearm(root: Path, config_dir: Path) -> None:
    opened = client(root, config_dir)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert opened.get(path).status_code == 404
    # FastAPI includes routers lazily, so app.routes no longer lists them: the inventory comes
    # from the schema, generated here and never served (openapi_url=None).
    schema = opened.app.openapi()  # type: ignore[attr-defined]
    routes = {(method.upper(), path) for path, ops in schema["paths"].items() for method in ops}
    assert routes == {
        ("GET", "/status"),
        ("POST", "/kill"),
        ("GET", "/approvals/pending"),
        ("POST", "/approvals/{approval_id}/approve"),
        ("POST", "/approvals/{approval_id}/refuse"),
        ("GET", "/reports/daily"),
        ("GET", "/alerts"),
        ("POST", "/events/ignored"),
        ("GET", "/bot/settings"),
        ("GET", "/dashboard"),
        ("GET", "/dashboard/paper"),
        ("GET", "/dashboard/risque"),
        ("GET", "/dashboard/decisions"),
        ("GET", "/dashboard/evals"),
        ("GET", "/dashboard/plugins"),
    }
    assert not any("arm" in path for _, path in routes)
    assert opened.get("/rearm").status_code == 404
    assert opened.post("/kill/rearm").status_code == 404


@pytest.mark.parametrize("base_url", ["http://evil.com", "http://192.168.1.10", "http://[::1]"])
def test_a_host_other_than_the_loopback_is_refused(
    root: Path, config_dir: Path, base_url: str
) -> None:
    assert client(root, config_dir, base_url=base_url).get("/status").status_code == 400


def test_localhost_is_the_loopback(root: Path, config_dir: Path) -> None:
    assert client(root, config_dir, base_url="http://localhost:8765").get("/status").is_success


def test_an_invalid_request_is_answered_without_its_values(root: Path, config_dir: Path) -> None:
    opened = client(root, config_dir)
    secret_like = "9" * 20
    long_code = opened.post(f"/approvals/{uuid7()}/approve", json={"code": secret_like})
    assert long_code.status_code == 422
    assert long_code.json() == {"detail": "requête invalide", "fields": ["body.code"]}
    assert secret_like not in long_code.text
    extra = opened.post(f"/approvals/{uuid7()}/approve", json={"code": "1", "note": "x"})
    assert extra.json()["fields"] == ["body.note"]
    bad_id = opened.post("/approvals/pas-un-uuid/approve", json={"code": "123456"})
    assert bad_id.json()["fields"] == ["path.approval_id"]


def test_an_invalid_configuration_answers_503_but_never_stops_a_kill(
    root: Path, config_dir: Path
) -> None:
    path = config_dir / "interfaces.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["api"]["port"] = 80  # below 1024
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    opened = client(root, config_dir)
    status = opened.get("/status")
    assert status.status_code == 503
    assert "cerveau config check" in status.json()["detail"]
    kill = opened.post("/kill")
    assert kill.status_code == 200
    assert kill.json()["target_s"] is None
    assert kill.json()["within_target"] is None
    assert kill_switch_engaged(root)


# --- status --------------------------------------------------------------------------------


def test_status_reads_what_stands_and_creates_nothing(root: Path, defined: Path) -> None:
    body = client(root, defined).get("/status").json()
    assert body["kill_switch"] == {"engaged": False, "trigger": None, "engaged_at": None}
    assert body["live"] == {"enabled": False}
    assert {d["domain"] for d in body["autonomy"]["domains"]} >= {"finance", "generaliste"}
    assert body["approvals"] == {
        "open": True,
        "reason": None,
        "pending": 0,
        "granted": 0,
        "locked": False,
    }
    assert body["orders"] == {"open": 0, "total": 0}
    assert body["reconciliation"] == {
        "last_at": None,
        "open_gaps": 0,
        "awaiting_acknowledgement": False,
    }
    assert body["loop"] == {"last_day": None, "completed_at": None}
    assert body["budget"]["defined"] is False
    assert body["budget"]["reason"] == "budgets à définir (R7)"
    for path in (approvals_path(root), default_book_path(root), default_loop_path(root)):
        assert not path.exists()


@pytest.mark.parametrize("store", ["approvals", "orders", "loop", "reconciliation"])
def test_status_neither_creates_nor_migrates_a_store(root: Path, defined: Path, store: str) -> None:
    """B215, B232: an empty file is a store at schema 0, which a writer would migrate; /status
    and the daily report open it read only and say it cannot be read."""
    path = {
        "approvals": approvals_path(root),
        "orders": default_book_path(root),
        "loop": default_loop_path(root),
        "reconciliation": default_log_path(root),
    }[store]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    opened = client(root, defined)
    status = opened.get("/status")
    if store == "approvals":
        approvals = status.json()["approvals"]
        assert approvals["open"] is False
        assert approvals["reason"].startswith("registre des approbations illisible")
    else:
        assert status.status_code == 503
        assert status.json()["detail"].startswith("registre illisible")
    if store == "loop":
        assert opened.get("/reports/daily").status_code == 503
    assert path.read_bytes() == b""


def test_status_counts_the_requests_and_says_why_the_store_is_closed(
    root: Path, defined: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ask(root, defined)
    approvals = client(root, defined).get("/status").json()["approvals"]
    assert approvals["pending"] == 1

    def closed(_: object) -> ApprovalRules:
        raise ApprovalError("paramètres d'approbation à définir par l'utilisateur (R7)")

    monkeypatch.setattr(ApprovalRules, "from_config", staticmethod(closed))
    approvals = client(root, defined).get("/status").json()["approvals"]
    assert approvals["open"] is False
    assert approvals["reason"].startswith("registre des approbations fermé")


def test_one_setting_of_the_approvals_feature_to_define_keeps_the_store_closed(
    root: Path, defined: Path
) -> None:
    approval = ask(root, defined)
    path = defined / "interfaces.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["discord"]["owner_user_id"] = "A_DEFINIR"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    opened = client(root, defined)
    reason = opened.get("/status").json()["approvals"]["reason"]
    assert reason.startswith("registre des approbations fermé : fonction bloquée « approvals »")
    assert "discord.owner_user_id = A_DEFINIR" in reason
    assert "api.port" not in reason
    assert opened.get("/approvals/pending").json() == {
        "open": False,
        "reason": reason,
        "locked": False,
        "requests": [],
    }
    for action, payload in (("approve", {"code": code()}), ("refuse", None)):
        shut = opened.post(f"/approvals/{approval}/{action}", json=payload)
        assert (shut.status_code, shut.json()["detail"]) == (503, reason)
    assert client(root, interfaces(defined)).get("/status").json()["approvals"]["pending"] == 1


# --- kill ----------------------------------------------------------------------------------


def test_kill_stops_without_a_code_and_is_timed_by_the_kill_switch(
    root: Path, defined: Path
) -> None:
    """B209: the duration is the stop's, not the alerts' sent after it."""
    ticks = iter([100.0, 100.25, 101.5, 103.0])  # reception, stop, state written, answer
    opened = client(root, defined, monotonic=lambda: next(ticks))
    body = opened.post("/kill", json={"reason": "essai depuis le bot"}).json()
    assert body["trigger"] == "commande"
    assert (body["elapsed_s"], body["target_s"], body["within_target"]) == (1.25, 5, True)
    assert body["response_s"] == 3.0
    assert body["alerts_failed"] == 0
    assert kill_switch_engaged(root)
    status = opened.get("/status").json()["kill_switch"]
    assert status["engaged"] is True
    assert status["trigger"] == "commande"
    kills = [e for e in entries(root) if e["event"] == "KILL"]
    assert kills
    assert {e["actor"] for e in kills} <= {"interface", "policy"}
    assert any(e["actor"] == "interface" for e in kills)
    alerts = opened.get("/alerts").json()["alerts"]
    assert [a["kind"] for a in alerts] == ["kill_switch"]


def test_a_kill_beyond_the_target_says_so(root: Path, config_dir: Path) -> None:
    ticks = iter([0.0, 0.0, 6.0, 6.5])
    body = client(root, config_dir, monotonic=lambda: next(ticks)).post("/kill").json()
    assert body["elapsed_s"] == 6.0
    assert body["within_target"] is False


def test_a_kill_reason_is_bounded(root: Path, config_dir: Path) -> None:
    opened = client(root, config_dir)
    assert opened.post("/kill", json={"reason": ""}).status_code == 422
    assert opened.post("/kill", json={"reason": "x" * 201}).status_code == 422
    assert not kill_switch_engaged(root)


# --- approvals -----------------------------------------------------------------------------


def test_pending_requests_show_what_they_ask(root: Path, defined: Path) -> None:
    opened = client(root, defined)
    assert opened.get("/approvals/pending").json() == {
        "open": True,
        "reason": None,
        "locked": False,
        "requests": [],
    }
    first = ask(root, defined)
    ask(root, defined, summary="Vente de 2 CW8")
    body = opened.get("/approvals/pending").json()
    assert body["locked"] is False
    request = body["requests"][0]
    assert request["approval_id"] == str(first)
    assert request["summary"] == SUMMARY
    assert request["environment"] == "paper"
    assert request["attempts_left"] == 3
    assert request["gate"] == {
        "result": "accepte",
        "requested_quantity": 4,
        "quantity": 3,
        "failed_checks": ["secteur"],
    }


def test_the_right_code_grants_and_waits_for_the_paper_account(root: Path, defined: Path) -> None:
    approval = ask(root, defined)
    opened = client(root, defined)
    body = opened.post(f"/approvals/{approval}/approve", json={"code": code()}).json()
    assert body["state"] == ApprovalState.ACCORDEE
    assert body["accepted"] is True
    assert body["locked"] is False
    assert body["sending"]["outcome"] == "en_attente"
    assert "cerveau paper envoyer" in body["sending"]["notes"][0]
    again = opened.post(f"/approvals/{approval}/approve", json={"code": code()})
    assert again.status_code == 409


def test_a_granted_intent_is_sent_at_once_without_amount(
    root: Path, defined: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approval = ask(root, defined)
    env = SimpleNamespace(approvals=None)
    seen: list[object] = []
    intent_id = uuid7()

    def send(paper: SimpleNamespace, *, now: datetime) -> DayReport:
        seen.append(paper.approvals)
        sent = SendOutcome(
            intent_id=intent_id,
            approval_id=approval,
            symbol="CW8",
            side="achat",
            quantity=3,
            approval=ApprovalState.CONSOMMEE,
            state=OrderState.ENVOYEE,
            reasons=(),
        )
        return DayReport(
            day=MONDAY, as_of=now, request_id="t", outcome="terminee", sent=[sent], notes=["n"]
        )

    monkeypatch.setattr("interfaces.api.app.open_paper_day", lambda *_, **__: env)
    monkeypatch.setattr("interfaces.api.app.send_approved", send)
    response = client(root, defined).post(f"/approvals/{approval}/approve", json={"code": code()})
    sending = response.json()["sending"]
    assert sending == {
        "outcome": "terminee",
        "sent": [
            {
                "intent_id": str(intent_id),
                "approval": "CONSOMMEE",
                "order": OrderState.ENVOYEE.value,
                "reasons": [],
            }
        ],
        "notes": ["n"],
    }
    assert "CW8" not in response.text
    assert isinstance(seen[0], ApprovalStore)


def test_wrong_codes_refuse_then_lock_with_one_alert(root: Path, defined: Path) -> None:
    first, second, third = (ask(root, defined) for _ in range(3))
    opened = client(root, defined)

    def approve(approval: UUID, *, right: bool = False) -> dict[str, Any]:
        return opened.post(
            f"/approvals/{approval}/approve", json={"code": code(right=right)}
        ).json()

    assert [approve(first)["attempts_left"] for _ in range(2)] == [2, 1]
    refused = approve(first)
    assert (refused["state"], refused["attempts_left"], refused["locked"]) == ("REFUSEE", 0, False)
    assert approve(second)["locked"] is False
    locking = approve(second)
    assert (locking["state"], locking["locked"], locking["alerts_failed"]) == ("DEMANDEE", True, 0)
    locked = approve(third, right=True)
    assert (locked["accepted"], locked["locked"], locked["state"]) == (False, True, "DEMANDEE")
    assert "sending" not in locked
    assert opened.get("/approvals/pending").json()["locked"] is True
    kinds = [a["kind"] for a in opened.get("/alerts").json()["alerts"]]
    assert kinds == ["approbations_verrouillees"]


def test_approving_needs_a_store_a_request_and_a_secret(
    root: Path, defined: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = client(root, defined)
    unknown = opened.post(f"/approvals/{uuid7()}/approve", json={"code": code()})
    assert unknown.status_code == 404  # no store yet
    approval = ask(root, defined)
    assert opened.post(f"/approvals/{uuid7()}/approve", json={"code": code()}).status_code == 404
    no_secret = client(root, defined, environ={TOKEN_ENV: TOKEN})
    missing = no_secret.post(f"/approvals/{approval}/approve", json={"code": code()})
    assert missing.status_code == 503
    assert "secret TOTP absent" in missing.json()["detail"]

    def closed(_: object) -> ApprovalRules:
        raise ApprovalError("paramètres d'approbation à définir par l'utilisateur (R7)")

    monkeypatch.setattr(ApprovalRules, "from_config", staticmethod(closed))
    shut = opened.post(f"/approvals/{approval}/approve", json={"code": code()})
    assert shut.status_code == 503
    assert shut.json()["detail"].startswith("registre des approbations fermé")


def test_refusing_from_the_api(root: Path, defined: Path) -> None:
    approval = ask(root, defined)
    opened = client(root, defined)
    assert opened.post(f"/approvals/{approval}/refuse").json() == {"state": "REFUSEE"}
    assert opened.post(f"/approvals/{approval}/refuse").status_code == 409
    assert opened.get("/approvals/pending").json()["requests"] == []
    reasons = [
        e["payload"]
        for e in entries(root)
        if e["actor"] == "interface" and isinstance(e["payload"], dict)
    ]
    assert any("refusée depuis l'API interne" in json.dumps(p, ensure_ascii=False) for p in reasons)
    other = ask(root, defined)
    assert opened.post(f"/approvals/{other}/refuse", json={"reason": "x" * 201}).status_code == 422
    custom = opened.post(f"/approvals/{other}/refuse", json={"reason": "trop tard"})
    assert custom.json() == {"state": "REFUSEE"}
    assert opened.post(f"/approvals/{uuid7()}/refuse").status_code == 404


# --- daily report --------------------------------------------------------------------------


def valued(day: date, equity: str) -> Valuation:
    return Valuation(
        day=day,
        equity_eur=Decimal(equity),
        cash_eur=Decimal("2500"),
        positions={"CW8": 15},
        valued_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=21),
    )


def test_the_daily_report_names_no_amount(root: Path, defined: Path) -> None:
    opened = client(root, defined)
    assert opened.get("/reports/daily").status_code == 404
    with LoopLog.open(default_loop_path(root)) as log:
        log.record_valuation(valued(FRIDAY, "10000"))
        log.record_valuation(valued(MONDAY, "10150"))
        log.record_run(MONDAY, completed_at=NOW - timedelta(days=2), intents=2, report="r")
    ask(root, defined)
    response = opened.get("/reports/daily")
    body = response.json()
    assert body["day"] == "2026-10-19"
    assert body["intents"] == 2
    assert body["valuation_change_pct"] == "1.50"
    assert body["approvals"]["DEMANDEE"] == 1
    assert body["kill_switch"]["engaged"] is False
    assert body["audit"]["ok"] is True
    lines = body["text"].splitlines()
    assert lines[0] == "Rapport quotidien CERVEAU du 19/10/2026 (compte paper)"
    assert "Valorisation : +1,50 % sur la journée précédente." in lines
    assert lines[-1].startswith(
        f"Journal d'audit : chaîne vérifiée, tête n° {body['audit']['head_seq']}"
    )
    for amount in ("10000", "10150", "10 150", "2500", "CW8", "512"):
        assert amount not in response.text
    assert opened.get("/reports/daily", params={"day": "2026-10-19"}).is_success
    missing = opened.get("/reports/daily", params={"day": "2026-10-20"})
    assert missing.status_code == 404
    assert missing.json()["detail"] == "aucune journée traitée le 2026-10-20"


# --- alerts and ignored messages -----------------------------------------------------------


def test_alerts_are_read_after_a_sequence_number(root: Path, defined: Path) -> None:
    opened = client(root, defined)
    assert opened.get("/alerts").json() == {"alerts": []}
    opened.post("/kill")
    alerts = opened.get("/alerts").json()["alerts"]
    assert len(alerts) == 1
    alert = alerts[0]
    assert set(alert) == {"seq", "kind", "severity", "ref", "at", "text"}
    assert opened.get("/alerts", params={"after": alert["seq"]}).json() == {"alerts": []}
    assert opened.get("/alerts", params={"limit": 0}).status_code == 422
    assert opened.get("/alerts", params={"limit": 201}).status_code == 422
    assert opened.get("/alerts", params={"after": -1}).status_code == 422
    assert default_outbox_path(root).is_file()


def test_an_ignored_message_is_journaled_without_identifier_or_content(
    root: Path, config_dir: Path
) -> None:
    opened = client(root, config_dir)
    response = opened.post("/events/ignored", json={"kind": "salon"})
    assert response.json()["request_id"].startswith("api-")
    (entry,) = entries(root)
    assert (entry["actor"], entry["event"]) == ("interface", "POLICY")
    assert entry["payload"] == {"discord": "message_ignore", "source": "salon"}
    assert opened.post("/events/ignored", json={"kind": "autre"}).status_code == 422
    content = opened.post("/events/ignored", json={"kind": "salon", "content": "bonjour"})
    assert content.status_code == 422
    assert len(entries(root)) == 1


def test_the_bot_learns_whom_it_answers_only_once_defined(root: Path, config_dir: Path) -> None:
    blocked = client(root, config_dir).get("/bot/settings")
    assert blocked.status_code == 503
    assert "owner_user_id" in blocked.json()["detail"]
    interfaces(config_dir)
    defined = client(root, config_dir).get("/bot/settings")
    assert defined.json() == {"owner_user_id": "123456789012345678"}
    assert not default_journal_path(root).exists()


# --- the command line ----------------------------------------------------------------------


def test_serving_needs_the_interfaces_defined(
    root: Path, config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CERVEAU_HOME", str(root))
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    result = runner.invoke(cli, ["api", "serve", "--config-dir", str(config_dir)])
    assert result.exit_code == 2
    assert "interfaces.api" in result.output or "A_DEFINIR" in result.output


def test_a_port_to_define_alone_keeps_the_api_down(
    root: Path, defined: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B210: require() refuses the port's marker, so serving never reads it as a number."""
    monkeypatch.setenv("CERVEAU_HOME", str(root))
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    path = defined / "interfaces.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["api"]["port"] = "A_DEFINIR"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    result = runner.invoke(cli, ["api", "serve", "--config-dir", str(defined)])
    assert result.exit_code == 2
    assert "api.port = A_DEFINIR" in result.output
    assert calls == []


def test_serving_needs_the_token(
    root: Path, defined: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CERVEAU_HOME", str(root))
    result = runner.invoke(cli, ["api", "serve", "--config-dir", str(defined)])
    assert result.exit_code == 2
    assert "API non démarrée" in result.output
    assert TOKEN_ENV in result.output


def test_serving_binds_the_loopback(
    root: Path, defined: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CERVEAU_HOME", str(root))
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    result = runner.invoke(cli, ["api", "serve", "--config-dir", str(defined)])
    assert result.exit_code == 0, result.output
    assert "http://127.0.0.1:8765" in result.output
    assert TOKEN not in result.output
    (kwargs,) = calls
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8765
    assert kwargs["server_header"] is False
    assert kwargs["proxy_headers"] is False


def test_enrolling_happens_at_owner_terminal_only(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CERVEAU_HOME", str(root))
    monkeypatch.setattr("interfaces.cli.approvals.interactive_terminal", lambda: False)
    refused = runner.invoke(cli, ["approvals", "enroll"])
    assert refused.exit_code == 2
    assert "terminal interactif" in refused.output
    monkeypatch.setattr("interfaces.cli.approvals.interactive_terminal", lambda: True)
    shown = runner.invoke(cli, ["approvals", "enroll"])
    assert shown.exit_code == 0, shown.output
    assert "otpauth://totp/" in shown.output
    assert SECRET_ENV in shown.output
    assert list(root.iterdir()) == []
