"""The kill switch (R4, ADR-034): stop everything within a measured target; only Lucas rearms.

Engaged means that ``governance/kill_switch/KILL`` exists: the policy engine then refuses every
action at N0 (:func:`core.policy.engine.decide`), and so does every reader of the file.
:func:`engage` creates it first, so that nothing after it can prevent the stop, then does the rest
at best and reports it: a ``KILL`` audit entry, the cancellation of every open order at the
adapter with retries bounded by the target, the book's moves to ANNULEE in one transaction, the
refusal of every open approval request (ADR-035), a state file, a second ``KILL`` entry with the
measured duration, an incident report in French in ``var/incidents/``, then the alerts, once the
stop is in force (ADR-038, B172). A step that fails goes to the report, never stops the rest: R4
comes first.
An order whose cancellation is not confirmed stays open in the book, marked as such in the
journal, the state and the report, until a reconciliation settles it.

Only Lucas rearms (D12): :func:`rearm` refuses outside an interactive terminal and without the
confirmation phrase, journals ``KILL`` (actor ``lucas``), then removes the file. A file Lucas
removes by hand is found by :func:`detect` at the next start, from the state file the program
keeps, and journaled.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Context, Decimal, DivisionByZero, InvalidOperation, Overflow, localcontext
from pathlib import Path
from typing import Literal, get_args
from uuid import UUID

from core.approvals.store import ApprovalStore
from core.config.loader import PaperRiskLimits
from core.execution.book import Journal, OrderBook
from core.execution.broker import BrokerAdapter
from core.execution.reconcile import interactive_terminal
from core.execution.states import OrderState
from core.finance.model import utc_text
from core.notify.alerts import Alerts, stop_alerts
from core.policy.engine import KILL_SWITCH_FILE, kill_switch_engaged
from core.risk_gate.snapshot import Account

Trigger = Literal[
    "fichier", "commande", "limite", "drawdown", "perte_donnees", "incident_execution"
]
TRIGGERS: tuple[Trigger, ...] = get_args(Trigger)
Status = Literal["armed", "engaged", "new_file", "removed_by_hand"]
REARM_PHRASE = "REARMER"
ATTEMPTS = 3  # calls to the adapter for one cancellation, within the target
REASON_CHARS = 200
_EXACT = Context(prec=60, traps=[InvalidOperation, DivisionByZero, Overflow])  # as the Gate


def incidents_dir(project_root: Path) -> Path:
    return project_root / "var" / "incidents"


def state_path(project_root: Path) -> Path:
    """What the program knows of the stop in force: a file removed by hand is found from it."""
    return incidents_dir(project_root) / "kill_switch.json"


class KillSwitchError(Exception):
    """A rearm refused or left unfinished: the stop stays in force."""


@dataclass(frozen=True)
class Stop:
    """What :func:`engage` did, measured and reported."""

    trigger: Trigger
    reason: str
    engaged_at: datetime
    persisted: bool  # the KILL file exists: the stop survives the process
    broker_cancelled: tuple[UUID, ...]  # cancellations the adapter confirmed
    cancelled: tuple[UUID, ...]  # moved to ANNULEE in the book
    unconfirmed: tuple[UUID, ...]  # open in the book, cancellation not confirmed: alert
    unknown: tuple[UUID, ...]  # cancelled at the adapter but not open in the book: alert
    errors: tuple[str, ...]
    elapsed_s: float  # from the trigger to the state written
    target_s: float | None  # None while kill_switch.target_seconds is A_DEFINIR
    report: Path | None = field(default=None)
    approvals_refused: tuple[UUID, ...] = ()  # open approval requests moved to REFUSEE
    alerts_failed: tuple[str, ...] = ()  # "<channel> : <error type>": the stop holds anyway

    @property
    def within_target(self) -> bool | None:
        return None if self.target_s is None else self.elapsed_s <= self.target_s

    @property
    def clean(self) -> bool:
        """Persisted, every open order cancelled and confirmed, nothing failed."""
        return self.persisted and not (self.unconfirmed or self.unknown or self.errors)


class KillSwitchEngaged(Exception):
    """Raised once the kill switch is engaged, to stop the caller's loop; carries the stop."""

    def __init__(self, stop: Stop) -> None:
        super().__init__(f"kill switch engagé ({stop.trigger}) : {stop.reason}")
        self.stop = stop


def _clean(text: str) -> str:
    """A reason as one printable line: never refused, since nothing may prevent a stop."""
    line = " ".join("".join(c if c.isprintable() else " " for c in text).split())
    return line[:REASON_CHARS] or "sans raison"


def _failure(step: str, exc: BaseException, *, detail: bool = True) -> str:
    """A failure for the report and the journal: the adapter's own message may carry what the
    broker sent, so only its type is kept."""
    message = _clean(str(exc)) if detail and str(exc) else ""
    return f"{step} : {type(exc).__name__}" + (f" ({message})" if message else "")


class _Broker:
    """The adapter calls of one stop: each failure recorded, none after the deadline but the
    first, which a stop always makes."""

    def __init__(
        self,
        adapter: BrokerAdapter,
        *,
        reason: str,
        now: datetime,
        deadline: float | None,
        clock: Callable[[], float],
        attempts: int,
        errors: list[str],
    ) -> None:
        self._adapter = adapter
        self._reason = reason
        self._now = now
        self._deadline = deadline
        self._clock = clock
        self._attempts = attempts
        self._errors = errors
        self._calls = 0
        self.skipped = 0

    def _may_call(self) -> bool:
        if self._calls and self._deadline is not None and self._clock() >= self._deadline:
            self.skipped += 1
            return False
        self._calls += 1
        return True

    def cancel_all(self) -> set[UUID] | None:
        for attempt in range(1, self._attempts + 1):
            if not self._may_call():
                return None
            try:
                return set(self._adapter.cancel_all(reason=self._reason, now=self._now))
            except Exception as exc:  # any adapter failure: recorded, the stop goes on
                self._errors.append(
                    _failure(f"courtier, tout annuler, essai {attempt}", exc, detail=False)
                )
        return None

    def open_orders(self) -> set[UUID] | None:
        if not self._may_call():
            return None
        try:
            return {order.intent_id for order in self._adapter.open_orders()}
        except Exception as exc:
            self._errors.append(_failure("courtier, ordres ouverts", exc, detail=False))
            return None

    def cancel(self, intent_id: UUID) -> bool:
        for attempt in range(1, self._attempts + 1):
            if not self._may_call():
                return False
            try:
                return self._adapter.cancel(intent_id, reason=self._reason, now=self._now)
            except Exception as exc:
                self._errors.append(
                    _failure(f"courtier, annuler {intent_id}, essai {attempt}", exc, detail=False)
                )
        return False


def _cancel_at_broker(broker: _Broker) -> tuple[set[UUID], set[UUID] | None]:
    """The cancellations the adapter confirmed, and the orders it still works afterwards (None
    when it cannot say)."""
    confirmed = broker.cancel_all() or set()
    still_open = broker.open_orders()
    if still_open is None:
        return confirmed, None
    for intent_id in sorted(still_open):
        if broker.cancel(intent_id):
            confirmed.add(intent_id)
            still_open.discard(intent_id)
    return confirmed, still_open


@dataclass(frozen=True)
class _Entries:
    """The KILL entries of one stop or one rearm, all on behalf of one actor."""

    journal: Journal
    actor: str
    request_id: str
    versions: Mapping[str, str] | None
    now: datetime

    def write(self, payload: dict[str, object]) -> None:
        self.journal.append(
            actor=self.actor,
            event="KILL",
            request_id=self.request_id,
            versions=self.versions,
            payload=payload,
            now=self.now,
        )

    def write_at_best(self, payload: dict[str, object], errors: list[str]) -> None:
        try:
            self.write(payload)
        except Exception as exc:  # a journal that refuses never prevents the stop (R4)
            errors.append(_failure(f"journal, entrée {payload['kill_switch']}", exc))


def _create_kill(path: Path, trigger: Trigger, now: datetime, errors: list[str]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            handle.write(f"declencheur: {trigger}\nle: {utc_text(now)}\n")
    except OSError as exc:
        # Already engaged, or created but not fully written: the file stays, the stop holds. A
        # FileExistsError alone proves nothing: the folder's name may be taken by a file.
        if path.exists() or path.is_symlink():
            return True
        errors.append(_failure("fichier KILL non créé : l'arrêt ne survit pas au processus", exc))
        return False
    return True


def _reserve_report(directory: Path, trigger: Trigger, now: datetime) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{now.astimezone(UTC):%Y%m%dT%H%M%SZ}-{trigger}"
    for index in range(1, 1_000):
        path = directory / (f"{stem}.md" if index == 1 else f"{stem}-{index}.md")
        try:
            path.open("x", encoding="utf-8").close()
        except FileExistsError:
            continue
        return path
    raise FileExistsError(f"{stem} : 999 rapports déjà présents")


def _write_state(path: Path, state: dict[str, object]) -> None:
    """Atomic: the state is either the previous one or this one, never half written."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def engage(
    project_root: Path,
    *,
    trigger: Trigger,
    reason: str,
    journal: Journal,
    actor: str,
    request_id: str,
    now: datetime,
    target_seconds: float | None,
    adapter: BrokerAdapter | None = None,
    book: OrderBook | None = None,
    approvals: ApprovalStore | None = None,
    alerts: Alerts | None = None,
    versions: Mapping[str, str] | None = None,
    unavailable: Sequence[str] = (),
    clock: Callable[[], float] = time.monotonic,
    attempts: int = ATTEMPTS,
) -> Stop:
    """Stop everything (R4, ADR-034) and return what was done; never raises for a failed step.

    ``adapter``, ``book`` and ``approvals`` are None when there is no paper account, book or
    approval store yet: nothing to cancel or refuse there. What the caller could not open goes in
    ``unavailable``, reported as errors. The book must journal on behalf of ``actor``: ``lucas``
    for ``cerveau kill``, ``policy`` for an automatic trigger. An order is moved to ANNULEE when
    the adapter confirms its cancellation, or when it was VALIDEE and the reachable adapter does
    not work it (it was never sent); any other open order stays open, and its cancellation is
    unconfirmed. Every open approval request is refused: none outlives the stop (ADR-035).
    ``alerts`` then sends the stop and each unconfirmed cancellation; a channel that fails is
    journaled and reported, and the stop stands (ADR-038).
    """
    start = clock()
    deadline = None if target_seconds is None else start + target_seconds
    why = _clean(reason)
    errors = [_clean(text) for text in unavailable]
    persisted = _create_kill(project_root / KILL_SWITCH_FILE, trigger, now, errors)
    entries = _Entries(journal, actor, request_id, versions, now)
    entries.write_at_best(
        {"kill_switch": "declenchement", "trigger": trigger, "reason": why}, errors
    )

    confirmed: set[UUID] = set()
    still_open: set[UUID] | None = None
    skipped = 0
    if adapter is not None:
        broker = _Broker(
            adapter,
            reason=f"kill switch ({trigger})",
            now=now,
            deadline=deadline,
            clock=clock,
            attempts=attempts,
            errors=errors,
        )
        confirmed, still_open = _cancel_at_broker(broker)
        skipped = broker.skipped
    if skipped:
        errors.append(f"cible atteinte : {skipped} appel(s) au courtier non tenté(s)")

    cancelled: tuple[UUID, ...] = ()
    unconfirmed: set[UUID] = set()
    unknown = set(confirmed)  # without a readable book, nothing confirmed is known to it
    if book is not None:
        try:
            booked = {order.intent.intent_id: order.state for order in book.open_orders()}
        except Exception as exc:
            errors.append(_failure("carnet d'ordres illisible", exc))
        else:
            never_sent = {
                key
                for key, state in booked.items()
                if state is OrderState.VALIDEE and still_open is not None and key not in still_open
            }
            moving = (confirmed & booked.keys()) | never_sent
            unconfirmed = booked.keys() - moving
            unknown = confirmed - booked.keys()
            try:
                cancelled = book.cancel_many(moving, reason=f"kill switch ({trigger})", now=now)
            except Exception as exc:
                errors.append(_failure("carnet d'ordres, passage à ANNULEE", exc))
                unconfirmed = set(booked)

    refused: tuple[UUID, ...] = ()
    if approvals is not None:
        try:
            refused = approvals.refuse_open(
                reason=f"kill switch ({trigger})",
                actor="lucas" if actor == "lucas" else "policy",
                now=now,
            )
        except Exception as exc:  # still open, but never sent while the stop lasts (R4)
            errors.append(_failure("approbations ouvertes non refusées", exc))

    report: Path | None = None
    try:
        report = _reserve_report(incidents_dir(project_root), trigger, now)
    except OSError as exc:
        errors.append(_failure("rapport d'incident non créé", exc))
    if persisted:
        try:
            _write_state(
                state_path(project_root),
                {
                    "engaged_at": utc_text(now),
                    "trigger": trigger,
                    "report": report.name if report else None,
                    "unconfirmed": sorted(str(key) for key in unconfirmed),
                },
            )
        except OSError as exc:
            errors.append(_failure("état du kill switch non écrit", exc))
    stop = Stop(
        trigger=trigger,
        reason=why,
        engaged_at=now,
        persisted=persisted,
        broker_cancelled=tuple(sorted(confirmed)),
        cancelled=cancelled,
        unconfirmed=tuple(sorted(unconfirmed)),
        unknown=tuple(sorted(unknown)),
        errors=tuple(errors),
        elapsed_s=clock() - start,
        target_s=target_seconds,
        report=report,
        approvals_refused=refused,
    )
    entries.write_at_best(_stop_payload(stop), errors)
    stop = replace(stop, errors=tuple(errors))
    if report is not None:
        try:
            report.write_text(render_report(stop), encoding="utf-8")
        except OSError as exc:  # the stop is in force: the journal entry above says so
            stop = replace(stop, errors=(*stop.errors, _failure("rapport non écrit", exc)))
    if alerts is not None:
        try:
            failed = alerts.send(
                stop_alerts(trigger, request_id, stop.unconfirmed, now),
                journal=journal,
                actor="policy",
                request_id=request_id,
                versions=versions,
                now=now,
            )
        except Exception as exc:  # an alert never holds a stop (R4)
            failed = (f"alertes : {type(exc).__name__}",)
        stop = replace(stop, alerts_failed=failed)
    return stop


def _stop_payload(stop: Stop) -> dict[str, object]:
    """The second KILL entry: counts, order ids and the duration, never an amount."""
    return {
        "kill_switch": "arret",
        "trigger": stop.trigger,
        "persisted": stop.persisted,
        "broker_cancelled": len(stop.broker_cancelled),
        "cancelled": len(stop.cancelled),
        "unconfirmed": [str(key) for key in stop.unconfirmed],
        "unknown": [str(key) for key in stop.unknown],
        "approvals_refused": len(stop.approvals_refused),
        "errors": len(stop.errors),
        "elapsed_ms": round(stop.elapsed_s * 1000),
        "target_s": stop.target_s,
        "within_target": stop.within_target,
    }


def _seconds(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def _ids(keys: tuple[UUID, ...]) -> list[str]:
    return [f"  - `{key}`" for key in keys]


def render_report(stop: Stop) -> str:
    """The incident report, in French, without any amount (ADR-034)."""
    if stop.target_s is None:
        verdict = "cible à définir (R7)"
    elif stop.within_target:
        verdict = f"dans la cible de {_seconds(stop.target_s)} s"
    else:
        verdict = f"AU-DELÀ de la cible de {_seconds(stop.target_s)} s"
    kill = (
        "présent : l'arrêt dure jusqu'au réarmement par Lucas"
        if stop.persisted
        else "NON CRÉÉ : l'arrêt ne survit pas au processus, le créer à la main"
    )
    lines = [
        f"# Kill switch — arrêt du {stop.engaged_at.astimezone(UTC):%d/%m/%Y à %H:%M:%S} (UTC)",
        "",
        f"- Déclencheur : {stop.trigger}",
        f"- Raison : {stop.reason}",
        f"- Durée mesurée : {_seconds(round(stop.elapsed_s, 3))} s, {verdict}",
        f"- Fichier `{KILL_SWITCH_FILE.as_posix()}` : {kill}",
        "- Autonomie : N0 forcé ; toute nouvelle intention est refusée tant que l'arrêt dure (R4).",
        "",
        "## Ordres",
        "",
        f"- Annulations confirmées par le courtier : {len(stop.broker_cancelled)}",
        f"- Passés à ANNULEE au carnet : {len(stop.cancelled)}",
        f"- **Annulation non confirmée (alerte)** : {len(stop.unconfirmed)}",
        *_ids(stop.unconfirmed),
        f"- **Annulés chez le courtier, absents des ordres ouverts du carnet (alerte)** : "
        f"{len(stop.unknown)}",
        *_ids(stop.unknown),
        "",
        "## Approbations",
        "",
        f"- Demandes ouvertes passées à REFUSEE : {len(stop.approvals_refused)}",
        "",
        "## Erreurs",
        "",
        *([f"- {error}" for error in stop.errors] or ["- Aucune."]),
        "",
        "## Réarmer",
        "",
        "Seul Lucas réarme, après avoir vérifié les ordres non confirmés et lancé une "
        f"réconciliation : `cerveau rearm` dans un terminal interactif, phrase « {REARM_PHRASE} »,"
        " ou suppression manuelle du fichier, détectée et journalisée au lancement suivant.",
        "",
    ]
    return "\n".join(lines)


def detect(
    project_root: Path,
    *,
    journal: Journal,
    request_id: str,
    now: datetime,
    versions: Mapping[str, str] | None = None,
) -> Status:
    """At start: ``new_file`` when KILL exists without a stop recorded (the caller then engages
    with the ``fichier`` trigger), ``removed_by_hand`` when a recorded stop lost its file (Lucas
    rearmed by hand: journaled, the state cleared), else ``engaged`` or ``armed``."""
    engaged = kill_switch_engaged(project_root)
    state = state_path(project_root)
    recorded = state.is_file()
    if engaged:
        return "engaged" if recorded else "new_file"
    if not recorded:
        return "armed"
    journal.append(
        actor="policy",
        event="KILL",
        request_id=request_id,
        versions=versions,
        payload={"kill_switch": "suppression_detectee"},
        now=now,
    )
    state.unlink(missing_ok=True)
    return "removed_by_hand"


@dataclass(frozen=True)
class Recorded:
    """The stop in force as the state file records it, for Lucas before he rearms."""

    engaged_at: str
    trigger: str
    report: Path | None  # None if not written or since removed
    unconfirmed: tuple[str, ...]


def recorded_stop(project_root: Path) -> Recorded | None:
    """The stop the state file records; None if there is none or it cannot be read."""
    try:
        state = json.loads(state_path(project_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict):
        return None
    name = state.get("report")
    report = incidents_dir(project_root) / name if isinstance(name, str) else None
    # A plain file name only: the state never points outside var/incidents.
    if report is not None and (Path(name).name != name or not report.is_file()):
        report = None
    unconfirmed = state.get("unconfirmed")
    return Recorded(
        engaged_at=_clean(str(state.get("engaged_at"))),
        trigger=_clean(str(state.get("trigger"))),
        report=report,
        unconfirmed=tuple(_clean(str(key)) for key in unconfirmed)
        if isinstance(unconfirmed, list)
        else (),
    )


def rearm(
    project_root: Path,
    *,
    journal: Journal,
    request_id: str,
    now: datetime,
    phrase: str,
    versions: Mapping[str, str] | None = None,
    interactive: Callable[[], bool] = interactive_terminal,
) -> None:
    """Lucas lifts the stop (D12): refused outside an interactive terminal, without the exact
    phrase or without a stop. Journaled first, so that no removal goes unrecorded; a removal
    that fails leaves the stop in force."""
    if not interactive():
        raise KillSwitchError(
            "réarmement refusé : il se fait par Lucas, dans un terminal interactif (D12)"
        )
    if phrase != REARM_PHRASE:
        raise KillSwitchError("réarmement refusé : phrase de confirmation incorrecte")
    if not kill_switch_engaged(project_root):
        raise KillSwitchError("aucun arrêt en cours : rien à réarmer")
    entries = _Entries(journal, "lucas", request_id, versions, now)
    entries.write({"kill_switch": "rearmement"})
    try:
        (project_root / KILL_SWITCH_FILE).unlink()
    except OSError as exc:
        entries.write({"kill_switch": "rearmement_echoue", "error": type(exc).__name__})
        raise KillSwitchError(
            f"réarmement inachevé : le fichier KILL reste en place ({type(exc).__name__})"
        ) from exc
    try:
        state_path(project_root).unlink(missing_ok=True)
    except OSError as exc:
        raise KillSwitchError(
            "réarmé, mais l'état n'est pas effacé : le prochain lancement journalisera une "
            f"suppression manuelle ({type(exc).__name__})"
        ) from exc


def _known(value: float | str, name: str) -> Decimal:
    if isinstance(value, str):
        raise ValueError(f"{name} vaut {value} : limite à définir (R7)")
    return Decimal(str(value))


def _fr(value: Decimal) -> str:
    return format(value.normalize(), "f").replace(".", ",")


def _pct(part: Decimal, whole: Decimal) -> str:
    return _fr((part * 100 / whole).quantize(Decimal("0.01")))


def loss_breaches(account: Account, limits: PaperRiskLimits) -> tuple[tuple[Trigger, str], ...]:
    """The loss limits the account is beyond at a valuation: what trips the kill switch.

    The formulas are the Risk Gate's checks ``max_daily_loss_pct``, ``max_rolling_loss_pct``
    and ``max_drawdown_pct`` (ADR-031), in the same exact context. A limit at a marker, or a
    rolling loss over another number of sessions, raises ValueError: the loss is unknown, and
    the Gate already refuses every order. The reasons give percentages, never an amount.
    """
    capital = _known(limits.capital_reference_eur, "capital_reference_eur")
    daily = _known(limits.max_daily_loss_pct, "max_daily_loss_pct")
    rolling = _known(limits.max_rolling_loss_pct, "max_rolling_loss_pct")
    drawdown = _known(limits.max_drawdown_pct, "max_drawdown_pct")
    sessions = limits.rolling_loss_sessions
    if isinstance(sessions, str):
        raise ValueError(f"rolling_loss_sessions vaut {sessions} : limite à définir (R7)")
    if account.rolling_sessions != sessions:
        raise ValueError(
            f"perte glissante sur {account.rolling_sessions} séances, et non {sessions}"
        )
    breaches: list[tuple[Trigger, str]] = []
    with localcontext(_EXACT):
        day_loss = max(-account.day_pnl_eur, Decimal(0))
        if day_loss * 100 > daily * capital:
            breaches.append(
                (
                    "limite",
                    f"perte du jour de {_pct(day_loss, capital)} % du capital de "
                    f"référence, au-delà de la limite de {_fr(daily)} %",
                )
            )
        rolling_loss = max(-account.rolling_pnl_eur, Decimal(0))
        if rolling_loss * 100 > rolling * capital:
            breaches.append(
                (
                    "limite",
                    f"perte sur {sessions} séances de {_pct(rolling_loss, capital)} % du "
                    f"capital de référence, au-delà de la limite de {_fr(rolling)} %",
                )
            )
        drop = account.peak_equity_eur - account.equity_eur
        if drop * 100 > drawdown * account.peak_equity_eur:
            breaches.append(
                (
                    "drawdown",
                    f"drawdown de {_pct(drop, account.peak_equity_eur)} % depuis le plus "
                    f"haut, au-delà de la limite de {_fr(drawdown)} %",
                )
            )
    return tuple(breaches)
