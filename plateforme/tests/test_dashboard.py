"""The read-only dashboard (ADR-041): HTTP Basic with the API's token on GET pages only, every
value escaped, strict headers, and CERVEAU's files read without a byte written."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from core.audit import AuditJournal, default_journal_path
from core.execution.book import OrderBook, default_book_path
from core.execution.loop import LoopLog, default_loop_path
from core.execution.reconcile import ReconciliationLog, default_log_path
from core.execution.states import OrderState
from core.finance.fixtures import reference_store
from core.finance.model import PARIS
from core.finance.schema import SchemaError
from core.finance.store import default_store_path as finance_path
from interfaces.api.dashboard import (
    EVAL_REPORT,
    INVALID_CONFIG,
    REALM,
    SECURITY_HEADERS,
    _day,
    _euros,
    _password,
    _when,
    dashboard_router,
    recent_errors,
)
from tests.execution_cases import DECISION_PRICE, MemoryJournal, make_intent, recorder
from tests.test_api import FRIDAY, MONDAY, NOW, TOKEN, ask, client, valued

PAGES = [
    "/dashboard",
    "/dashboard/paper",
    "/dashboard/risque",
    "/dashboard/decisions",
    "/dashboard/evals",
    "/dashboard/plugins",
]
HOSTILE = "<script>alert(1)</script>"
ESCAPED = "&lt;script&gt;alert(1)&lt;/script&gt;"


def basic(password: str, user: str = "owner") -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode("ascii")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


def browser(root: Path, config_dir: Path) -> TestClient:
    opened = client(root, config_dir, token=None)
    opened.headers["Authorization"] = basic(TOKEN)
    return opened


def snapshot(root: Path) -> dict[str, tuple[int, str]]:
    """Every file under ``root`` with its modification time and digest."""
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in root.rglob("*")
        if path.is_file()
    }


def text(opened: TestClient, path: str) -> str:
    response = opened.get(path)
    assert response.status_code == 200, response.text
    return response.text


# --- the door: the token as a Basic password, GET only ------------------------------------


@pytest.mark.parametrize("path", PAGES)
@pytest.mark.parametrize(
    "header",
    [
        None,
        f"Bearer {TOKEN}",  # the API's scheme opens no page: a browser cannot send it anyway
        basic("wrong"),
        basic(TOKEN + "x"),
        basic(TOKEN[:-1]),
        "Basic " + base64.b64encode(TOKEN.encode()).decode("ascii"),  # no colon
        "Basic !!!",
        f"Digest {TOKEN}",
    ],
)
def test_every_page_needs_the_token_as_basic_password(
    root: Path, config_dir: Path, path: str, header: str | None
) -> None:
    opened = client(root, config_dir, token=None)
    response = opened.get(path, headers={} if header is None else {"Authorization": header})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == REALM
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    assert response.json() == {"detail": "jeton absent ou invalide"}
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("user", ["", "owner", "n'importe qui"])
def test_any_user_name_with_the_token_opens_it(root: Path, config_dir: Path, user: str) -> None:
    opened = client(root, config_dir, token=None)
    assert opened.get("/dashboard", headers={"Authorization": basic(TOKEN, user)}).is_success


@pytest.mark.parametrize(
    ("header", "password"),
    [
        (None, None),
        ("", None),
        ("Basic", None),
        ("Basic é", None),  # not ASCII
        ("Basic Og==", b""),  # ":"
        ("basic " + base64.b64encode(b"a:b:c").decode(), b"b:c"),
        ("Bearer " + base64.b64encode(b"a:b").decode(), None),
    ],
)
def test_the_password_of_a_basic_header(header: str | None, password: bytes | None) -> None:
    assert _password(header) == password


def test_the_pages_answer_get_only(root: Path, config_dir: Path) -> None:
    router = dashboard_router(root, token=TOKEN.encode(), configs=config_dir, clock=lambda: NOW)
    routes = [route for route in router.routes if isinstance(route, APIRoute)]
    assert len(routes) == len(router.routes)
    assert sorted(route.path for route in routes) == sorted(PAGES)
    assert all(route.methods == {"GET"} and route.include_in_schema for route in routes)
    opened = browser(root, config_dir)
    for path in PAGES:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert opened.request(method, path).status_code == 405
    assert list(root.iterdir()) == []


def test_the_api_routes_stay_bearer_only(root: Path, config_dir: Path) -> None:
    """A browser that remembers the Basic password cannot reach an action (CSRF)."""
    opened = browser(root, config_dir)
    assert opened.get("/status").status_code == 401
    assert opened.post("/kill").status_code == 401
    assert list(root.iterdir()) == []


# --- an empty home: every page, nothing created --------------------------------------------


def test_every_page_renders_on_an_empty_home_and_creates_nothing(
    root: Path, config_dir: Path
) -> None:
    opened = browser(root, config_dir)
    for path in PAGES:
        response = opened.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        for name, value in SECURITY_HEADERS.items():
            assert response.headers[name] == value
        page = response.text
        assert '<html lang="fr">' in page
        assert "<script" not in page
        assert "<form" not in page
        assert "Lecture seule, page générée le 21/10/2026 12:00 UTC" in page
        assert 'aria-current="page"' in page
    assert list(root.iterdir()) == []
    state = text(opened, "/dashboard")
    assert "non engagé" in state
    assert "désactivé (R3)" in state
    assert "budgets à définir (R7)" in state
    assert "Chaîne vérifiée" in state
    assert "Aucune valorisation" in text(opened, "/dashboard/paper")
    assert "base finance absente" in text(opened, "/dashboard/risque")
    decisions = text(opened, "/dashboard/decisions")
    assert "Aucune demande en attente." in decisions
    assert "Aucun ordre ouvert." in decisions
    assert "aucun run hors ligne" in text(opened, "/dashboard/evals")
    plugins = text(opened, "/dashboard/plugins")
    assert "Plugins acceptés (0)" in plugins
    assert "Aucune erreur journalisée." in plugins


# --- a filled home: what stands is shown, and left as it was ---------------------------------


def fill(root: Path, config_dir: Path) -> None:
    with LoopLog.open(default_loop_path(root)) as log:
        log.record_valuation(valued(FRIDAY, "10000"))
        log.record_valuation(valued(MONDAY, "10150"))
        log.record_run(MONDAY, completed_at=NOW - timedelta(days=2), intents=1, report="r")
    ReconciliationLog.open(default_log_path(root), recorder(MemoryJournal())).close()
    with OrderBook.open(default_book_path(root), recorder=recorder(MemoryJournal())) as book:
        intent = make_intent()
        book.record_intent(intent, decision_price=DECISION_PRICE, reason="intention rédigée")
        book.transition(intent.intent_id, OrderState.VALIDEE, reason="Porte de risque : ACCEPT")
    ask(root, config_dir, summary=f"Achat {HOSTILE}")
    reference_store(finance_path(root))
    report = root / EVAL_REPORT
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps(
            {
                "run": "20261020-offline",
                "mode": "hors ligne",
                "created": "2026-10-20T08:00:00+00:00",
                "passed": True,
                "regression": None,
                "results": [],
                "suites": [
                    {"suite": "finance", "cases": 12, "passed": 12, "missing": 0, "errors": 0,
                     "r5_breaches": 0},
                ],
            }
        ),
        encoding="utf-8",
    )  # fmt: skip
    AuditJournal(default_journal_path(root)).append(
        actor="interface", event="ERROR", payload={"kind": "bot", "error": HOSTILE}
    )
    broken = root / "plugins" / "broken"
    broken.mkdir(parents=True)
    (broken / "plugin.yaml").write_text("id: [", encoding="utf-8")


def test_a_filled_home_is_shown_escaped_and_left_untouched(root: Path, config_dir: Path) -> None:
    fill(root, config_dir)
    before = snapshot(root)
    opened = browser(root, config_dir)
    pages = {path: text(opened, path) for path in PAGES}
    assert snapshot(root) == before

    state = pages["/dashboard"]
    assert "19/10/2026" in state
    assert "Dernière réconciliation" in state
    assert "Chaîne vérifiée" in state

    paper = pages["/dashboard/paper"]
    assert "Au 19/10/2026" in paper
    assert _euros(Decimal("10150")) in paper
    assert _euros(Decimal("10000")) in paper
    assert "CW8" in paper  # amounts and positions may show on the user's machine (D12)

    risk = pages["/dashboard/risque"]
    assert "[Approximation]" in risk
    assert "VaR et CVaR" in risk
    assert 'class="alerte"' not in risk.split("<h1>", 1)[1].split("<h2>", 1)[0]

    decisions = pages["/dashboard/decisions"]
    assert ESCAPED in decisions
    assert "FICT-ACME" in decisions
    assert "achat" in decisions
    assert "123,45 EUR" in decisions

    evals = pages["/dashboard/evals"]
    assert "20261020-offline" in evals
    assert "20/10/2026 08:00 UTC" in evals

    plugins = pages["/dashboard/plugins"]
    assert "Plugins refusés (1)" in plugins
    assert "broken" in plugins
    assert ESCAPED in plugins

    for page in pages.values():
        assert HOSTILE not in page
        assert "<script" not in page


# --- what cannot be read is said, never a 500 ----------------------------------------------


def test_an_invalid_configuration_is_shown_on_every_page(root: Path, config_dir: Path) -> None:
    path = config_dir / "interfaces.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["api"]["port"] = 80  # below 1024
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    opened = browser(root, config_dir)
    for page in ("/dashboard", "/dashboard/risque", "/dashboard/decisions"):
        assert INVALID_CONFIG.split(" :")[0] in text(opened, page)
    assert list(root.iterdir()) == []


def test_unreadable_files_are_reported_and_left_as_they_are(root: Path, config_dir: Path) -> None:
    for path in (
        default_loop_path(root),
        default_log_path(root),
        default_book_path(root),
        root / EVAL_REPORT,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"pas une base")
    ask(root, config_dir)
    approvals = next((root / "var").rglob("approvals.db"), None)
    assert approvals is not None
    approvals.write_bytes(b"pas une base")
    before = snapshot(root)
    opened = browser(root, config_dir)
    state = text(opened, "/dashboard")
    assert "boucle paper illisible" in state
    assert "journal de réconciliation illisible" in state
    assert "boucle paper illisible" in text(opened, "/dashboard/paper")
    decisions = text(opened, "/dashboard/decisions")
    assert "registre des approbations fermé ou illisible" in decisions
    assert "carnet d&#39;ordres illisible" in decisions  # the apostrophe escaped as well
    assert "rapport illisible" in text(opened, "/dashboard/evals")
    assert snapshot(root) == before


def test_an_older_schema_is_reported_not_migrated(root: Path, config_dir: Path) -> None:
    path = default_loop_path(root)
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE other (x)")
    conn.close()
    before = snapshot(root)
    state = text(browser(root, config_dir), "/dashboard")
    assert "boucle paper illisible : boucle paper au schéma 0" in state
    assert snapshot(root) == before


# --- the read-only logs ------------------------------------------------------------------------


def test_a_read_only_loop_log_reads_and_never_writes(tmp_path: Path) -> None:
    path = tmp_path / "var" / "loop.db"
    with pytest.raises(sqlite3.OperationalError):
        LoopLog.open(path, read_only=True)
    assert not path.parent.exists()
    with LoopLog.open(path) as log:
        log.record_valuation(valued(FRIDAY, "10000"))
    with LoopLog.open(path, read_only=True) as log:
        assert [v.day for v in log.valuations()] == [FRIDAY]
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            log.record_valuation(valued(MONDAY, "10150"))
        assert [v.day for v in log.valuations()] == [FRIDAY]


def test_a_read_only_reconciliation_log_reads_and_never_creates(tmp_path: Path) -> None:
    path = tmp_path / "var" / "reconciliation.db"
    with pytest.raises(sqlite3.OperationalError):
        ReconciliationLog.open(path, recorder(MemoryJournal()), read_only=True)
    assert not path.parent.exists()
    ReconciliationLog.open(path, recorder(MemoryJournal())).close()
    with ReconciliationLog.open(path, recorder(MemoryJournal()), read_only=True) as log:
        assert log.open_gaps() == 0
        assert log.last_reconciled_at() is None


@pytest.mark.parametrize("kind", ["loop", "reconciliation"])
def test_a_read_only_log_refuses_an_older_schema(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "old.db"
    sqlite3.connect(path).close()
    with pytest.raises(SchemaError, match="au schéma 0"):
        if kind == "loop":
            LoopLog.open(path, read_only=True)
        else:
            ReconciliationLog.open(path, recorder(MemoryJournal()), read_only=True)


# --- the filters and the journal's errors -------------------------------------------------


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        (None, "—"),
        ("2026-10-21T14:00:05+02:00", "21/10/2026 12:00 UTC"),
        (datetime(2026, 10, 21, 18, 30, tzinfo=PARIS), "21/10/2026 16:30 UTC"),
        ("2026-10-21T14:00:05", "21/10/2026 14:00"),  # no time zone: none is claimed
        ("pas une date", "pas une date"),
    ],
)
def test_a_moment_is_shown_in_utc(value: datetime | str | None, shown: str) -> None:
    assert _when(value) == shown


@pytest.mark.parametrize(
    ("value", "shown"),
    [(None, "—"), (date(2026, 10, 19), "19/10/2026"), ("2026-10-19", "19/10/2026"), ("x", "x")],
)
def test_a_day_is_shown_in_french(value: date | str | None, shown: str) -> None:
    assert _day(value) == shown


def test_the_last_errors_come_newest_first_and_bounded(root: Path) -> None:
    journal = AuditJournal(default_journal_path(root))
    assert recent_errors(root, 2) == []
    journal.append(actor="interface", event="ERROR", payload={"command": "ask", "details": "x"})
    journal.append(actor="interface", event="APPROVAL", payload={"error": "pas une erreur"})
    journal.append(actor="interface", event="ERROR", payload="y" * 500)
    journal.append(actor="interface", event="ERROR")
    journal.append(actor="owner", event="ERROR", payload={"kind": "k", "error": "z" * 500})
    errors = recent_errors(root, 3)
    assert [e["seq"] for e in errors] == [5, 4, 3]
    assert errors[0]["actor"] == "owner"
    assert errors[0]["kind"] == "k"
    assert errors[0]["error"] == "z" * 200
    assert (errors[1]["kind"], errors[1]["error"]) == ("—", "—")  # no payload
    assert errors[2]["error"] == "y" * 200
    first = recent_errors(root, 10)[-1]
    assert (first["kind"], first["error"]) == ("ask", "x")
