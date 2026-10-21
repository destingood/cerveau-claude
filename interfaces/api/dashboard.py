"""The read-only local dashboard (ADR-041): state, paper account, risk, pending decisions, evals
and the plugins' health, as HTML pages of the internal API on the loopback (D1, D16).

A browser cannot send a bearer token, so these pages take HTTP Basic with the API's token as the
password, whatever the user name. Only these GET routes accept it, never the API's: a browser
that remembers the password cannot be led to approve, refuse or stop anything. Every page reads
CERVEAU's files opened read only and renders with Jinja2's autoescaping; it carries no script
and no form, which its Content-Security-Policy forbids anyway. A risk figure shows the display
and the identifier the finance_risk tool gave it (R1). Amounts and positions may show here, on
Lucas's machine, unlike in Discord (D12).
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
from collections.abc import Callable
from contextlib import ExitStack
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from core.approvals.store import ApprovalRules, ApprovalState, ApprovalStore
from core.approvals.store import default_store_path as approvals_path
from core.audit import AuditError, AuditJournal, default_journal_path, verify
from core.config import BlockedFeatureError, ConfigError, load_config
from core.config.loader import Config
from core.evals.promotion import PromotionError, load_report
from core.execution.book import BookedOrder, OrderBook, default_book_path
from core.execution.loop import Valuation
from core.execution.states import OPEN
from core.finance.risk_report import RiskReport, risk_report
from core.finance.store import default_store_path as finance_path
from core.finance.views import ViewError, read_store
from core.registry.manifest import validate_all
from core.verification.figures import BEFORE_UNIT, french
from interfaces.api import views

TEMPLATES = Path(__file__).parent / "templates"
REALM = 'Basic realm="CERVEAU", charset="UTF-8"'
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
PAGES = {
    "": "État",
    "/paper": "Compte paper",
    "/risque": "Risque",
    "/decisions": "Décisions",
    "/evals": "Évals",
    "/plugins": "Plugins",
}
RISK_FEATURE = "finance.market_risk"
RISK_MEASURES = ["volatilite", "var", "drawdown", "concentration"]
EVAL_REPORT = Path("var") / "evals" / "offline" / "report.json"  # written by `cerveau eval`
VALUATIONS_SHOWN = 10
ERRORS_SHOWN = 10
ERROR_CHARS = 200
INVALID_CONFIG = "configuration invalide : voir `cerveau config check`"
READ_ERRORS = views.READ_ERRORS


def _password(authorization: str | None) -> bytes | None:
    """The password of an HTTP Basic header, as bytes; None for anything else."""
    scheme, _, encoded = (authorization or "").partition(" ")
    if scheme.lower() != "basic":
        return None
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True)
    except (binascii.Error, ValueError):  # ValueError: a header that is not ASCII
        return None
    _, colon, password = decoded.partition(b":")
    return password if colon else None


def _require_basic(expected: bytes) -> Callable[..., None]:
    def require(authorization: Annotated[str | None, Header()] = None) -> None:
        given = _password(authorization)
        if given is None or not secrets.compare_digest(given, expected):
            raise HTTPException(
                401,
                "jeton absent ou invalide",
                headers={**SECURITY_HEADERS, "WWW-Authenticate": REALM},
            )

    return require


def _euros(value: Decimal) -> str:
    return french(value, 2) + BEFORE_UNIT + "€"


def _price(value: Decimal) -> str:
    return french(value, 2, max_decimals=4)


def _number(value: int | Decimal) -> str:
    return french(Decimal(value), 0)


def _day(value: date | str | None) -> str:
    """A day; a text that is not a day is shown as it is."""
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime("%d/%m/%Y")


def _when(value: datetime | str | None) -> str:
    """A moment in UTC, the time zone of the journal's anchors; a text that is not a moment is
    shown as it is."""
    if value is None:
        return "—"
    try:
        moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError:
        return str(value)
    if moment.tzinfo is None:
        return moment.strftime("%d/%m/%Y %H:%M")
    return moment.astimezone(UTC).strftime("%d/%m/%Y %H:%M UTC")


def environment() -> Environment:
    """Jinja2 with autoescaping for every template, whatever its extension."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATES), autoescape=True, undefined=StrictUndefined
    )
    env.filters.update(euros=_euros, prix=_price, nombre=_number, jour=_day, quand=_when)
    return env


def recent_errors(root: Path, limit: int) -> list[dict[str, Any]]:
    """The last ``limit`` ERROR entries of the audit journal, newest first."""
    journal = AuditJournal(default_journal_path(root))
    if not journal.path.is_file():
        return []
    found: list[dict[str, Any]] = []
    for raw in journal.path.read_bytes().splitlines():
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue  # `cerveau audit verify` reports it
        if isinstance(entry, dict) and entry.get("event") == "ERROR":
            found.append(entry)
    return [
        {
            "seq": entry.get("seq"),
            "ts": entry.get("ts"),
            "actor": entry.get("actor"),
            "request_id": entry.get("request_id"),
            **_error_text(journal, entry.get("payload_ref")),
        }
        for entry in reversed(found[-limit:])
    ]


def _error_text(journal: AuditJournal, ref: object) -> dict[str, str]:
    if not isinstance(ref, str):
        return {"kind": "—", "error": "—"}
    try:
        payload = journal.read_payload(ref)
    except (AuditError, OSError, ValueError):
        return {"kind": "—", "error": "payload illisible"}
    if not isinstance(payload, dict):
        return {"kind": "—", "error": str(payload)[:ERROR_CHARS]}
    kind = payload.get("kind") or payload.get("command") or "—"
    error = payload.get("error") or payload.get("details") or "—"
    return {"kind": str(kind)[:ERROR_CHARS], "error": str(error)[:ERROR_CHARS]}


def _approvals(
    stack: ExitStack, root: Path, loaded: Config | None, now: datetime
) -> dict[str, Any]:
    """The requests waiting for Lucas, from the approval store opened read only."""
    seen: dict[str, Any] = {"problem": None, "pending": [], "counts": None, "locked": False}
    if loaded is None:
        return seen | {"problem": INVALID_CONFIG}
    path = approvals_path(root)
    try:
        rules = ApprovalRules.from_config(loaded.autonomy.approval)
        if not path.is_file():
            return seen
        store = stack.enter_context(ApprovalStore.open(path, rules=rules, read_only=True))
        tally = store.counts(now=now)
        return seen | {
            "pending": [
                views.pending_item(item, rules)
                for item in store.requests({ApprovalState.DEMANDEE}, now=now)
            ],
            "counts": {state.value: tally[state] for state in ApprovalState},
            "locked": store.locked(now=now),
        }
    except READ_ERRORS as exc:
        return seen | {"problem": f"registre des approbations fermé ou illisible : {exc}"}


def _open_orders(stack: ExitStack, root: Path) -> tuple[list[BookedOrder], str | None]:
    path = default_book_path(root)
    if not path.is_file():
        return [], None
    try:
        return stack.enter_context(OrderBook.open(path, read_only=True)).orders(OPEN), None
    except READ_ERRORS as exc:
        return [], f"carnet d'ordres illisible : {exc}"


def _risk(root: Path, loaded: Config | None, now: datetime) -> tuple[RiskReport | None, str | None]:
    """The finance_risk tool's report on the portfolio at ``now``, as the plugin computes it."""
    if loaded is None:
        return None, INVALID_CONFIG
    store = finance_path(root)
    if not store.is_file():
        return None, "base finance absente : aucune donnée importée"
    market = loaded.risk.market_risk
    threshold = loaded.data_sources.quality.min_quality_score_above_N1
    try:
        loaded.require(RISK_FEATURE)
        report = read_store(
            store,
            lambda db: risk_report(
                db, market, as_of=now, measures=RISK_MEASURES, quality_threshold=threshold
            ),
        )
    except BlockedFeatureError as exc:
        return None, "fonction bloquée : " + " ; ".join(exc.reasons)
    except ViewError as exc:
        return None, str(exc)
    return report, None


def dashboard_router(
    root: Path, *, token: bytes, configs: Path, clock: Callable[[], datetime]
) -> APIRouter:
    """The dashboard's pages under ``/dashboard``, each one behind HTTP Basic with ``token``."""
    router = APIRouter(prefix="/dashboard", dependencies=[Depends(_require_basic(token))])
    env = environment()

    def page(template: str, path: str, now: datetime, **context: Any) -> HTMLResponse:
        html = env.get_template(template).render(
            pages=PAGES, current=path, title=PAGES[path], now=now, **context
        )
        return HTMLResponse(html, headers=SECURITY_HEADERS)

    def config() -> Config | None:
        try:
            return load_config(configs)
        except ConfigError:
            return None

    @router.get("", response_class=HTMLResponse)
    def state() -> HTMLResponse:
        """Kill switch, live, levels, budget, last day, reconciliation and the audit chain."""
        now, loaded = clock(), config()
        journal = AuditJournal(default_journal_path(root))
        problems: list[str] = []
        loop: dict[str, Any] = {"last_day": None, "completed_at": None}
        reconciliation: dict[str, Any] | None = None
        with ExitStack() as stack:
            try:
                loop = views.loop_view(views.loop_log(stack, root))
            except READ_ERRORS as exc:
                problems.append(f"boucle paper illisible : {exc}")
            try:
                reconciliation = views.reconciliation_view(stack, root, journal)
            except READ_ERRORS as exc:
                problems.append(f"journal de réconciliation illisible : {exc}")
        return page(
            "etat.html",
            "",
            now,
            invalid=None if loaded is not None else INVALID_CONFIG,
            kill=views.kill_view(root),
            live=None if loaded is None else loaded.live.enabled,
            autonomy=None if loaded is None else views.autonomy_view(loaded, root),
            budget=None if loaded is None else views.budget_view(loaded, journal, now),
            loop=loop,
            reconciliation=reconciliation,
            chain=verify(journal.path),
            problems=problems,
        )

    @router.get("/paper", response_class=HTMLResponse)
    def paper() -> HTMLResponse:
        """The paper account's last valuations, as the paper loop recorded them."""
        now = clock()
        problem: str | None = None
        valuations: list[Valuation] = []
        with ExitStack() as stack:
            try:
                log = views.loop_log(stack, root)
                valuations = [] if log is None else log.valuations()
            except READ_ERRORS as exc:
                problem = f"boucle paper illisible : {exc}"
        return page(
            "paper.html",
            "/paper",
            now,
            problem=problem,
            last=valuations[-1] if valuations else None,
            recent=list(reversed(valuations[-VALUATIONS_SHOWN:])),
        )

    @router.get("/risque", response_class=HTMLResponse)
    def risk() -> HTMLResponse:
        """The finance_risk tool's report on the current portfolio, figures cited (R1)."""
        now = clock()
        report, problem = _risk(root, config(), now)
        return page("risque.html", "/risque", now, report=report, problem=problem)

    @router.get("/decisions", response_class=HTMLResponse)
    def decisions() -> HTMLResponse:
        """The approval requests waiting for Lucas and the open orders of the paper book."""
        now, loaded = clock(), config()
        with ExitStack() as stack:
            approvals = _approvals(stack, root, loaded, now)
            orders, orders_problem = _open_orders(stack, root)
            return page(
                "decisions.html",
                "/decisions",
                now,
                approvals=approvals,
                orders=orders,
                orders_problem=orders_problem,
            )

    @router.get("/evals", response_class=HTMLResponse)
    def evals() -> HTMLResponse:
        """The last offline eval run (`make eval`)."""
        now = clock()
        path = root / EVAL_REPORT
        report: dict[str, Any] | None = None
        problem: str | None = None
        if not path.is_file():
            problem = "aucun run hors ligne : lancer `make eval`"
        else:
            try:
                report = load_report(path)
            except PromotionError as exc:
                problem = str(exc)
        suites = [] if report is None else report.get("suites") or []
        return page(
            "evals.html",
            "/evals",
            now,
            report=report,
            suites=[suite for suite in suites if isinstance(suite, dict)],
            problem=problem,
        )

    @router.get("/plugins", response_class=HTMLResponse)
    def plugins() -> HTMLResponse:
        """The registry's verdict on each plugin and the journal's last errors."""
        now = clock()
        registry = validate_all(root / "plugins")
        return page(
            "plugins.html",
            "/plugins",
            now,
            accepted=registry.accepted,
            refused=registry.refused,
            errors=recent_errors(root, ERRORS_SHOWN),
        )

    return router
