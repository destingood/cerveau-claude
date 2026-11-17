"""The local internal API (ADR-037, D1): the only door of the Discord bot and the dashboard.

`cerveau api serve` binds it to 127.0.0.1 (D16), and only the user starts it (D22). Every route
needs the bearer token of ``CERVEAU_API_TOKEN``, compared in constant time; the dashboard's
read-only pages take the same token as an HTTP Basic password instead (ADR-041). A Host other
than the loopback is refused, and there is neither documentation route nor OpenAPI schema. No
route rearms the kill switch: rearming stays at the user's interactive terminal (ADR-034).

Answers carry states, counts and percentages, never an amount or a position, except the
summary of an approval request (D12). The configuration is read again at each request, so an
edited ``autonomy.yaml`` or a new signature applies at once. A one-time code is never journaled,
echoed or kept: a malformed request is answered with the names of its fields only.
"""

from __future__ import annotations

import secrets
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from core.approvals.store import REASON_CHARS, ApprovalError, ApprovalState, ApprovalStore
from core.approvals.totp import key_from_environment
from core.audit import AuditJournal, default_journal_path
from core.config import ConfigError, load_config
from core.config.loader import Config
from core.execution.loop import send_approved
from core.execution.operations import PaperUnavailable, open_paper_day, stop_everything
from core.notify import Alert, Alerts, alerts_from, default_outbox_path, read_outbox
from interfaces.api import views
from interfaces.api.dashboard import dashboard_router

TOKEN_ENV = "CERVEAU_API_TOKEN"  # noqa: S105 - the variable's name, not a secret
MIN_TOKEN_CHARS = 32
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
CODE_CHARS = 16  # a TOTP code has 6 digits; anything longer is refused before it is looked at
MAX_ALERTS = 200
ACTOR = "interface"


class ApiError(Exception):
    """The API refuses to start."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KillBody(_Strict):
    reason: str = Field(default="arrêt demandé par l'API interne", min_length=1, max_length=200)


class CodeBody(_Strict):
    code: str = Field(min_length=1, max_length=CODE_CHARS)


class RefusalBody(_Strict):
    reason: str = Field(
        default="refusée depuis l'API interne", min_length=1, max_length=REASON_CHARS
    )


class IgnoredBody(_Strict):
    kind: Literal["utilisateur", "salon"]  # who or where the bot ignored, never what was said


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _request_id() -> str:
    return f"api-{uuid.uuid4().hex[:12]}"


def _token(environ: Mapping[str, str]) -> bytes:
    token = environ.get(TOKEN_ENV, "")
    if len(token) < MIN_TOKEN_CHARS:
        raise ApiError(
            f"{TOKEN_ENV} absente ou trop courte ({MIN_TOKEN_CHARS} caractères au moins) : "
            "l'API ne démarre pas"
        )
    return token.encode()


def create_app(
    root: Path,
    *,
    environ: Mapping[str, str],
    config_dir: Path | None = None,
    clock: Callable[[], datetime] = _utc_now,
    monotonic: Callable[[], float] = time.monotonic,
) -> FastAPI:
    """The API over the project at ``root``; raises :class:`ApiError` without a valid token.

    The token and the TOTP secret are read once from ``environ``, here, and never shown."""
    expected = _token(environ)
    totp_key = key_from_environment(environ)
    configs = config_dir or root / "config"

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        scheme, _, given = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(given.encode(), expected):
            raise HTTPException(
                401, "jeton absent ou invalide", headers={"WWW-Authenticate": "Bearer"}
            )

    app = FastAPI(title="CERVEAU", docs_url=None, redoc_url=None, openapi_url=None)
    api = APIRouter(dependencies=[Depends(require_token)])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(part) for part in error.get("loc", ())) for error in exc.errors()]
        return JSONResponse(
            status_code=422, content={"detail": "requête invalide", "fields": fields}
        )

    def journal() -> AuditJournal:
        return AuditJournal(default_journal_path(root))

    def config() -> Config:
        try:
            return load_config(configs)
        except ConfigError as exc:
            raise HTTPException(
                503, "configuration invalide : voir `cerveau config check`"
            ) from exc

    def alerts(loaded: Config | None) -> Alerts:
        return alerts_from(loaded, root, environ)[0]

    def store(
        stack: ExitStack,
        loaded: Config,
        audit: AuditJournal,
        request_id: str,
        approval_id: UUID,
        now: datetime,
    ) -> ApprovalStore:
        opened, closed = views.approval_store(stack, root, loaded, audit, request_id)
        if closed is not None:
            raise HTTPException(503, closed)
        try:
            if opened is None:
                raise ApprovalError("aucune demande d'approbation")
            opened.get(approval_id, now=now)
        except ApprovalError as exc:
            raise HTTPException(404, f"approbation {approval_id} inconnue") from exc
        return opened

    @api.get("/status")
    def status() -> dict[str, Any]:
        """Kill switch, live, levels, approvals, orders, reconciliation, loop, budget (D1). It
        only reads: no store is created, locked or migrated (B215, B232), and one that cannot be
        read so answers 503 rather than a count nobody read."""
        now, request_id, audit, loaded = clock(), _request_id(), journal(), config()
        with ExitStack() as stack:
            opened, closed = views.approval_store(
                stack, root, loaded, audit, request_id, read_only=True
            )
            try:
                orders = views.orders_view(stack, root)
                reconciliation = views.reconciliation_view(stack, root, audit)
                loop = views.loop_view(views.loop_log(stack, root))
            except views.READ_ERRORS as exc:
                raise HTTPException(503, f"registre illisible : {exc}") from exc
            return {
                "kill_switch": views.kill_view(root),
                "live": {"enabled": loaded.live.enabled},
                "autonomy": views.autonomy_view(loaded, root),
                "approvals": views.approvals_view(opened, closed, now),
                "orders": orders,
                "reconciliation": reconciliation,
                "loop": loop,
                "budget": views.budget_view(loaded, audit, now),
            }

    @api.post("/kill")
    def kill(body: Annotated[KillBody | None, Body()] = None) -> dict[str, Any]:
        """Stop everything, without a code (D11). ``elapsed_s`` is the kill switch's own
        measure, up to the stop's state written, as the CLI and the bot show it; the alerts
        come after it and only count in ``response_s``, from reception to the answer (B209)."""
        started = monotonic()
        now, request_id = clock(), _request_id()
        try:
            loaded: Config | None = load_config(configs)
        except ConfigError:
            loaded = None  # a stop never waits for the configuration (R4)
        stop = stop_everything(
            root,
            loaded,
            trigger="commande",
            reason=(body or KillBody()).reason,
            journal=journal(),
            actor=ACTOR,
            request_id=request_id,
            now=now,
            alerts=alerts(loaded),
            clock=monotonic,
        )
        answered = monotonic() - started
        return {
            "request_id": request_id,
            "trigger": stop.trigger,
            "elapsed_s": round(stop.elapsed_s, 3),
            "target_s": stop.target_s,
            "within_target": stop.within_target,
            "response_s": round(answered, 3),
            "cancelled": len(stop.cancelled),
            "broker_cancelled": len(stop.broker_cancelled),
            "unconfirmed": len(stop.unconfirmed),
            "unknown": len(stop.unknown),
            "approvals_refused": len(stop.approvals_refused),
            "errors": list(stop.errors),
            "alerts_failed": len(stop.alerts_failed),
            "clean": stop.clean,
        }

    @api.get("/approvals/pending")
    def pending() -> dict[str, Any]:
        """The requests waiting for the user, oldest first, with what each one asks (D12)."""
        now, request_id, audit, loaded = clock(), _request_id(), journal(), config()
        with ExitStack() as stack:
            opened, closed = views.approval_store(stack, root, loaded, audit, request_id)
            if opened is None:
                return {"open": closed is None, "reason": closed, "locked": False, "requests": []}
            return {
                "open": True,
                "reason": None,
                "locked": opened.locked(now=now),
                "requests": [
                    views.pending_item(request, opened.rules)
                    for request in opened.requests({ApprovalState.DEMANDEE}, now=now)
                ],
            }

    @api.post("/approvals/{approval_id}/approve")
    def approve(approval_id: UUID, body: CodeBody) -> dict[str, Any]:
        """Check the user's one-time code; a granted intent is sent at once, to paper while the live
        is disabled (D10), exactly as ``cerveau paper envoyer`` would send it."""
        now, request_id, audit, loaded = clock(), _request_id(), journal(), config()
        with ExitStack() as stack:
            opened = store(stack, loaded, audit, request_id, approval_id, now)
            if totp_key is None:
                raise HTTPException(503, "secret TOTP absent : aucun code ne peut être vérifié")
            was_locked = opened.locked(now=now)
            try:
                outcome = opened.approve(approval_id, body.code, key=totp_key, now=now)
            except ApprovalError as exc:
                raise HTTPException(409, str(exc)) from exc
            channels = alerts(loaded)
            failed: list[str] = []
            if outcome.locked and not was_locked:
                failed = channels.send(
                    [Alert.of("approbations_verrouillees", request_id, now)],
                    journal=audit,
                    actor=ACTOR,
                    request_id=request_id,
                    versions={"config": loaded.digest},
                    now=now,
                )
            answer: dict[str, Any] = {
                "state": outcome.state.value,
                "accepted": outcome.accepted,
                "attempts_left": outcome.attempts_left,
                "locked": outcome.locked,
                "alerts_failed": len(failed),
            }
            if outcome.state is ApprovalState.ACCORDEE:
                answer["sending"] = send(stack, loaded, audit, request_id, now, channels, opened)
            return answer

    def send(
        stack: ExitStack,
        loaded: Config,
        audit: AuditJournal,
        request_id: str,
        now: datetime,
        channels: Alerts,
        opened: ApprovalStore,
    ) -> dict[str, Any]:
        try:
            env = open_paper_day(stack, root, loaded, audit, request_id, now, alerts=channels)
        except PaperUnavailable as exc:
            return {
                "outcome": "en_attente",
                "sent": [],
                "notes": [
                    f"compte paper non ouvert ({exc}) : `cerveau paper envoyer` enverra "
                    "l'intention approuvée"
                ],
            }
        env.approvals = opened
        report = send_approved(env, now=now)
        return {
            "outcome": report.outcome,
            "sent": [
                {
                    "intent_id": str(item.intent_id),
                    "approval": item.approval.value,
                    "order": item.state.value,
                    "reasons": list(item.reasons),
                }
                for item in report.sent
            ],
            "notes": list(report.notes),
        }

    @api.post("/approvals/{approval_id}/refuse")
    def refuse(
        approval_id: UUID, body: Annotated[RefusalBody | None, Body()] = None
    ) -> dict[str, Any]:
        """Refuse a request on the user's behalf, from an interface (ADR-035)."""
        now, request_id, audit, loaded = clock(), _request_id(), journal(), config()
        with ExitStack() as stack:
            opened = store(stack, loaded, audit, request_id, approval_id, now)
            try:
                state = opened.refuse(
                    approval_id, reason=(body or RefusalBody()).reason, actor=ACTOR, now=now
                )
            except ApprovalError as exc:
                raise HTTPException(409, str(exc)) from exc
        return {"state": state.value}

    @api.get("/reports/daily")
    def daily(day: date | None = None) -> dict[str, Any]:
        """The report of ``day``, or of the last day the loop treated (D12, D13)."""
        now, request_id, audit, loaded = clock(), _request_id(), journal(), config()
        with ExitStack() as stack:
            try:
                log = views.loop_log(stack, root)
                run = None if log is None else log.run(day)
                if log is None or run is None:
                    raise HTTPException(
                        404,
                        "aucune journée traitée"
                        + ("" if day is None else f" le {day.isoformat()}"),
                    )
                return views.daily_report(stack, root, loaded, audit, request_id, now, run, log)
            except views.READ_ERRORS as exc:  # read only (B215)
                raise HTTPException(503, f"registre illisible : {exc}") from exc

    @api.get("/alerts")
    def outbox(
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=MAX_ALERTS)] = 50,
    ) -> dict[str, Any]:
        """The alerts for the bot to post, after the last sequence number it posted (ADR-038)."""
        path = default_outbox_path(root)
        posted = read_outbox(path, after=after, limit=limit) if path.is_file() else []
        return {
            "alerts": [
                {
                    "seq": item.seq,
                    "kind": item.alert.kind,
                    "severity": item.alert.severity,
                    "ref": item.alert.ref,
                    "at": item.alert.at.isoformat(),
                    "text": item.alert.text(),
                }
                for item in posted
            ]
        }

    @api.post("/events/ignored")
    def ignored(body: IgnoredBody) -> dict[str, Any]:
        """Journal that the bot ignored a user or a channel other than the user's private messages;
        neither an identifier nor a content is kept (R5)."""
        request_id = _request_id()
        journal().append(
            actor=ACTOR,
            event="POLICY",
            request_id=request_id,
            payload={"discord": "message_ignore", "source": body.kind},
            now=clock(),
        )
        return {"request_id": request_id}

    @api.get("/bot/settings")
    def bot_settings() -> dict[str, Any]:
        """Whom the Discord bot answers; 503 while ``interfaces.yaml`` leaves it to the user, so the
        bot refuses to start rather than answer anyone (R7, ADR-037)."""
        loaded = config()
        blockers = loaded.blockers("interfaces.discord")
        if blockers:
            raise HTTPException(503, "bot Discord bloqué : " + " ; ".join(blockers))
        return {"owner_user_id": loaded.interfaces.discord.owner_user_id}

    app.include_router(api)
    app.include_router(dashboard_router(root, token=expected, configs=configs, clock=clock))
    return app
