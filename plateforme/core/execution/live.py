"""The live adapter: a real broker behind the live Risk Gate and seven conditions, checked at
every submission (ADR-039, ADR-067, ADR-075).

No broker client exists in this phase (D8): :class:`LiveAdapter` wraps any
:class:`BrokerClient` and refuses to submit an order unless, at that very call (D9), read on its
own clock (B230), the live Risk Gate accepts it first (:class:`LiveRiskGate`: ``live.yaml``
read, never written, the book from a source passed in, every decision journaled; B353), then:

1. ``config/live.yaml`` is complete: ``enabled``, a broker named, every limit above 0 and a
   non-empty whitelist (R3, R7);
2. ``config/live.yaml``, ``governance/approvals/`` and every file in it belong to the
   Administrators group, which alone with SYSTEM may write them, or to root, as
   ``protect-live.ps1`` leaves them (B1, B2, ADR-003);
3. The user signed N3 or above for finance, citing a promotion report that exists (ADR-036, D7);
4. the effective finance level, min(written, signed), is N3 or above (D6);
5. the kill switch is not engaged (R4);
6. the intent has a granted, unexpired approval for ``live``, bound to its very content (D4);
7. the order keeps within ``live.yaml``: its instrument is whitelisted, and its size, the position,
   the day's loss, the day's order count and ``allow`` are checked. The live Risk Gate checks them
   in front; this condition stays closed for every order all the same (B200, B353, R7), until the
   user decides to open live with a broker and a source for its book: live stays closed.

The gate and the conditions are two layers, each enough to stop an order: the gate is a
required argument of the adapter, outside the injectable check, so that removing or replacing a
condition never removes it. Everything is read again from disk at each submission: nothing is
cached, so a change by the user, or the kill switch, applies to the next call. A refusal of the
gate raises :class:`LiveGateRefused`, a false condition :class:`LiveDisabled`, which names every
failing condition; either way the client is never called. Once the gate and all seven conditions
hold, the approval is spent, once, before the submission (D4).

Cancelling and reading never add exposure: ``cancel``, ``cancel_all`` (the kill switch's move)
and the reads stay allowed whatever the conditions. Every call to the client is bounded by a
timeout shorter than the kill switch's target, which must be known, and raises
:class:`TimeoutError` past it (B171).
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Mapping
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, TypeVar
from uuid import UUID

from core.approvals.store import ApprovalError, ApprovalState, ApprovalStore
from core.config.loader import LEVELS, MARKERS, Config, ConfigError, LiveConfig, load_config
from core.execution.book import Journal
from core.execution.broker import AccountStatement, BrokerAck, BrokerOrder, FillBatch
from core.execution.intent import OrderIntent
from core.execution.ownership import protected
from core.governance.signatures import SIGNATURES_DIR, effective_autonomy, read_signatures
from core.policy.engine import kill_switch_engaged
from core.risk_gate.gate import RiskGateResult
from core.risk_gate.live import NO_BOOK, LiveBook, evaluate_live, refusal

LIVE_FILE = Path("config") / "live.yaml"
LIVE_DOMAIN = "finance"
LIVE_FROM = "N3"  # the lowest level that may reach a real broker (ADR-036)
_T = TypeVar("_T")


class Condition(StrEnum):
    """The seven conditions of a live submission (D9), in the order they are checked."""

    CONFIGURATION = "configuration_live"
    LIMITES = "limites_live"
    ACL = "acl"
    SIGNATURE = "signature_n3"
    NIVEAU = "niveau_effectif"
    KILL_SWITCH = "kill_switch"
    APPROBATION = "approbation"


Verdict = Mapping[Condition, str | None]  # None: the condition holds; else why it does not
Check = Callable[[OrderIntent, datetime], Verdict]
Limits = Callable[[LiveConfig, OrderIntent], str | None]  # condition 7: why not, or None
Gate = Callable[[OrderIntent, datetime], RiskGateResult]  # the live Risk Gate (B353)
BookSource = Callable[[OrderIntent, datetime], LiveBook | None]  # None: no source


class LiveDisabled(Exception):
    """A submission refused before the broker: every failing condition, and why."""

    def __init__(self, failures: tuple[tuple[Condition, str], ...]) -> None:
        detail = " ; ".join(f"{condition} : {reason}" for condition, reason in failures)
        super().__init__(f"live refusé, aucun appel au courtier ({detail})")
        self.failures = failures

    @property
    def conditions(self) -> tuple[Condition, ...]:
        return tuple(condition for condition, _ in self.failures)


class LiveGateRefused(LiveDisabled):
    """A submission the live Risk Gate refused, before any condition is read: its reasons. A
    :class:`LiveDisabled`, so that whoever stops on one stops on both; no condition failed."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        Exception.__init__(
            self, f"live refusé par la Porte live, aucun appel au courtier ({' ; '.join(reasons)})"
        )
        self.failures = ()
        self.reasons = reasons


class BrokerClient(Protocol):
    """A real broker's client: the surface of ``BrokerAdapter``, without any guard (D8)."""

    def submit(self, intent: OrderIntent, *, now: datetime) -> BrokerAck: ...

    def cancel(self, intent_id: UUID, *, reason: str, now: datetime) -> bool: ...

    def cancel_all(self, *, reason: str, now: datetime) -> tuple[UUID, ...]: ...

    def open_orders(self) -> tuple[BrokerOrder, ...]: ...

    def account_snapshot(self) -> AccountStatement: ...

    def fills_since(self, cursor: int) -> FillBatch: ...


def live_incomplete(live: LiveConfig) -> str | None:
    """Why ``live.yaml`` does not allow a real order, or None (condition 1)."""
    if not live.enabled:
        return "enabled = false (R3)"
    if not live.broker.strip() or live.broker in MARKERS:
        return f"broker non défini ({live.broker.strip() or 'vide'})"
    zero = sorted(name for name, value in live.limits.model_dump().items() if value <= 0)
    if zero:
        return f"limites à 0 : {', '.join(zero)}"
    if not live.instruments_whitelist:
        return "liste blanche vide"
    return None


NO_LIVE_GATE = (
    "taille, position, perte du jour, ordres du jour et allow de live.yaml : la Porte live les "
    "vérifie en amont, et cette condition reste fermée jusqu'à la décision de l'utilisateur "
    "(B200, B353, R7)"
)


def live_limits(live: LiveConfig, intent: OrderIntent) -> str | None:
    """Why the order does not keep within ``live.yaml``, or None (condition 7). The live Risk
    Gate checks the limits in front of the conditions (B353); this condition stays closed for
    every order, a second lock that only the user's decision opens (ADR-075)."""
    instrument = intent.instrument
    if not {instrument.symbol, instrument.isin} & set(live.instruments_whitelist):
        return f"{instrument.symbol} hors de la liste blanche"
    return NO_LIVE_GATE


class ActivationCheck:
    """The seven conditions, read from the files under ``root`` at each call (D9)."""

    def __init__(
        self,
        root: Path,
        approvals: ApprovalStore,
        *,
        owner: Callable[[Path], bool] = protected,
        load: Callable[[Path], Config] = load_config,
        limits: Limits = live_limits,
    ) -> None:
        self.root = root
        self.limits = limits
        self.approvals = approvals
        self.owner = owner
        self.load = load

    def __call__(self, intent: OrderIntent, now: datetime) -> Verdict:
        config: Config | str
        try:
            config = self.load(self.root / "config")
        except (ConfigError, OSError) as exc:
            config = f"configuration illisible ({type(exc).__name__})"
        signed = read_signatures(self.root)
        highest = signed.highest(LIVE_DOMAIN)
        verdict: dict[Condition, str | None] = {
            Condition.ACL: self._acl(),
            Condition.SIGNATURE: (
                None
                if LEVELS.index(highest) >= LEVELS.index(LIVE_FROM)
                else f"plus haut niveau signé {highest}, {LIVE_FROM} requis"
            ),
            Condition.KILL_SWITCH: (
                "kill switch engagé (R4)" if kill_switch_engaged(self.root) else None
            ),
            Condition.APPROBATION: self._approval(intent, now),
        }
        if isinstance(config, str):
            verdict[Condition.CONFIGURATION] = config
            verdict[Condition.LIMITES] = config
            verdict[Condition.NIVEAU] = config
        else:
            verdict[Condition.CONFIGURATION] = live_incomplete(config.live)
            verdict[Condition.LIMITES] = self.limits(config.live, intent)
            effective = effective_autonomy(config.autonomy, self.root, signed=signed)
            spec = effective.autonomy.domains.get(LIVE_DOMAIN)
            level = "absent" if spec is None else spec.level
            verdict[Condition.NIVEAU] = (
                None
                if spec is not None and LEVELS.index(spec.level) >= LEVELS.index(LIVE_FROM)
                else f"niveau effectif {level}, {LIVE_FROM} requis"
            )
        return verdict

    def _acl(self) -> str | None:
        """Why the live file, the signatures folder or a file in it is not out of reach, or
        None: a signature left writable could be replaced by one the user never wrote."""
        folder = self.root / SIGNATURES_DIR
        paths = [self.root / LIVE_FILE, folder]
        try:
            if folder.is_dir():
                paths += sorted(folder.rglob("*"))
        except OSError as exc:
            return f"contenu de {SIGNATURES_DIR.as_posix()} illisible ({type(exc).__name__})"
        loose = [p.relative_to(self.root).as_posix() for p in paths if not self.owner(p)]
        if loose:
            return f"accès non protégé : {', '.join(loose)} (protect-live.ps1)"
        return None

    def _approval(self, intent: OrderIntent, now: datetime) -> str | None:
        request = self.approvals.for_intent(intent.intent_id, now=now)
        if request is None:
            return "aucune demande d'approbation pour cette intention"
        if request.environment != "live":
            return f"approbation demandée pour {request.environment}, pas pour live"
        if request.state is not ApprovalState.ACCORDEE:
            return f"approbation {request.state}"  # an overdue one reads EXPIREE
        if request.intent_sha256 != intent.sha256():
            return "approbation accordée pour un autre contenu de l'intention"
        return None


def no_live_book(intent: OrderIntent, now: datetime) -> LiveBook | None:
    """The book source while no broker is connected: there is no book, so the gate refuses."""
    del intent, now
    return None


class LiveRiskGate:
    """The live Risk Gate over the files under ``root`` (B353, ADR-075), in front of the seven
    conditions.

    At each call it reads ``config/live.yaml`` through the loader, never writes it, asks ``book``
    for the account at ``now``, refuses outright while the kill switch is engaged (R4), else
    judges with :func:`evaluate_live`, then journals the decision,
    accepted or refused, as a ``POLICY`` entry of the actor ``risk_gate`` (R11). The journal keeps
    the checks and the reasons, the book's SHA-256 alone and, for an error, its type's name
    alone (ADR-071, B197): no broker name, no account, no position. An unreadable configuration,
    a source in error or a journal that refuses the entry refuses the order (R7, R11)."""

    def __init__(
        self,
        root: Path,
        journal: Journal,
        *,
        book: BookSource = no_live_book,
        load: Callable[[Path], Config] = load_config,
    ) -> None:
        self.root = root
        self.journal = journal
        self.book = book
        self.load = load

    def __call__(self, intent: OrderIntent, now: datetime) -> RiskGateResult:
        errors: dict[str, str] = {}
        config: Config | None = None
        try:
            config = self.load(self.root / "config")
        except Exception as exc:  # whatever it is, an unread configuration refuses
            errors["config"] = type(exc).__name__
        book: LiveBook | None = None
        missing = NO_BOOK
        try:
            book = self.book(intent, now)
        except Exception as exc:  # only its type is kept: its text may name the account
            errors["book"] = type(exc).__name__
            missing = f"source du livre live en erreur ({errors['book']})"
        if book is not None and not isinstance(book, LiveBook):
            errors["book"] = type(book).__name__
            missing = f"source du livre live : LiveBook attendu ({errors['book']})"
            book = None
        if kill_switch_engaged(self.root):  # first of all, whatever else holds (R4)
            result = refusal(intent, "kill_switch", "kill switch engagé (R4)")
        elif config is None:
            reason = f"configuration illisible ({errors['config']})"
            result = refusal(intent, "configuration", reason)
        else:
            result = evaluate_live(intent, config.live, book, now=now, missing_book=missing)
        payload = {
            "environment": "live",
            "decided_at": now.isoformat(),
            "intent_id": str(intent.intent_id),
            "intent_sha256": result.intent_sha256,
            "requested_quantity": result.requested_quantity,
            "quantity": result.quantity,
            **result.policy_payload(),
            "reasons": list(result.reasons),
            "book_sha256": None if book is None else book.sha256(),
            "errors": errors,
        }
        try:
            self.journal.append(
                actor="risk_gate",
                event="POLICY",
                request_id=f"live-{intent.intent_id}",
                versions={} if config is None else {"config": config.digest},
                payload=payload,
                now=now,
            )
        except Exception as exc:  # a decision without its trace is no decision (R11)
            name = type(exc).__name__
            reason = f"journal d'audit indisponible ({name}) : aucune décision sans trace (R11)"
            return refusal(intent, "journal", reason)
        return result


class LiveAdapter:
    """``BrokerAdapter`` over a real client; only ``submit`` needs the gate and the seven
    conditions.

    ``submit`` judges the gate, the conditions and the approval's expiry on ``clock``, never on
    the caller's ``now`` (B230): a caller cannot revive an expired approval by passing an earlier
    time. Only an ``ACCEPTE`` of the gate for this very intent, at its very quantity, lets the
    conditions be read: a reduction, a verdict for another content or an error refuses."""

    def __init__(
        self,
        client: BrokerClient,
        approvals: ApprovalStore,
        check: Check,
        *,
        gate: Gate,
        call_timeout_s: float,
        kill_target_s: float | None,
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        if not math.isfinite(call_timeout_s) or call_timeout_s <= 0:
            raise ValueError("délai d'appel au courtier : nombre de secondes > 0 attendu")
        if kill_target_s is None or not math.isfinite(kill_target_s):
            # An unknown target cannot bound the calls: no live adapter until it is set.
            raise ValueError("cible du kill switch inconnue ou invalide (A_DEFINIR refusé, R4, R7)")
        if call_timeout_s >= kill_target_s:
            raise ValueError(
                f"délai d'appel {call_timeout_s} s : il doit rester sous la cible du kill switch "
                f"({kill_target_s} s, B171)"
            )
        self._client = client
        self._approvals = approvals
        self._check = check
        self._gate = gate
        self._timeout_s = call_timeout_s
        self._clock = clock

    def submit(self, intent: OrderIntent, *, now: datetime) -> BrokerAck:
        del now  # the caller's time is not trusted (B230)
        now = self._clock()
        self._pass_gate(intent, now)
        verdict = self._check(intent, now)
        reasons = {c: verdict.get(c, "condition non évaluée") for c in Condition}
        failures = tuple((c, reason) for c, reason in reasons.items() if reason is not None)
        if failures:
            raise LiveDisabled(failures)
        request = self._approvals.for_intent(intent.intent_id, now=now)
        if request is None:
            raise LiveDisabled(((Condition.APPROBATION, "demande disparue avant l'envoi"),))
        try:
            self._approvals.consume(request.approval_id, intent_sha256=intent.sha256(), now=now)
        except ApprovalError as exc:
            raise LiveDisabled(((Condition.APPROBATION, str(exc)),)) from exc
        return self._bounded("submit", lambda: self._client.submit(intent, now=now))

    def _pass_gate(self, intent: OrderIntent, now: datetime) -> None:
        """Raise :class:`LiveGateRefused` unless the gate accepts this very order (B353)."""
        try:
            result = self._gate(intent, now)
            refused, reasons = result.result == "REFUSE", tuple(result.reasons)
            accepted = (
                result.result == "ACCEPTE"
                and result.intent_sha256 == intent.sha256()
                and result.quantity == intent.quantity
            )
        except Exception as exc:  # a gate that cannot answer refuses (R7)
            raise LiveGateRefused((f"Porte live en erreur ({type(exc).__name__})",)) from exc
        if refused:
            raise LiveGateRefused(reasons)
        if not accepted:  # a reduction, or a verdict on another content: never this order
            raise LiveGateRefused(("la Porte live n'accepte pas cet ordre tel quel",))

    def cancel(self, intent_id: UUID, *, reason: str, now: datetime) -> bool:
        return self._bounded(
            "cancel", lambda: self._client.cancel(intent_id, reason=reason, now=now)
        )

    def cancel_all(self, *, reason: str, now: datetime) -> tuple[UUID, ...]:
        return self._bounded("cancel_all", lambda: self._client.cancel_all(reason=reason, now=now))

    def open_orders(self) -> tuple[BrokerOrder, ...]:
        return self._bounded("open_orders", self._client.open_orders)

    def account_snapshot(self) -> AccountStatement:
        return self._bounded("account_snapshot", self._client.account_snapshot)

    def fills_since(self, cursor: int) -> FillBatch:
        return self._bounded("fills_since", lambda: self._client.fills_since(cursor))

    def _bounded(self, name: str, call: Callable[[], _T]) -> _T:
        """``call`` in a daemon thread, waited for at most the timeout (B171). A call past it
        raises TimeoutError, one of ``NETWORK_ERRORS``: whether it reached the broker is unknown,
        and the thread is left to finish on its own; the next call does not wait for it."""
        results: list[_T] = []
        errors: list[BaseException] = []

        def run() -> None:
            try:
                results.append(call())
            except BaseException as exc:  # handed to the caller below, whatever it is
                errors.append(exc)

        worker = threading.Thread(target=run, name=f"live-{name}", daemon=True)
        worker.start()
        worker.join(self._timeout_s)
        if errors:
            raise errors[0]
        if not results:
            raise TimeoutError(f"courtier : {name} sans réponse après {self._timeout_s} s (B171)")
        return results[0]
