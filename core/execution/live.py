"""The live adapter: a real broker behind six conditions checked at every submission (ADR-036).

No broker client exists in this phase (D8): :class:`LiveAdapter` wraps any
:class:`BrokerClient` and refuses to submit an order unless, at that very call (D9):

1. ``config/live.yaml`` is complete: ``enabled``, a broker named, every limit above 0 and a
   non-empty whitelist (R3, R7);
2. ``config/live.yaml`` and ``governance/approvals/`` belong to the Administrators group, or to
   root, as ``protect-live.ps1`` leaves them (B1, B2, ADR-003);
3. Lucas signed N3 or above for finance, citing a promotion report that exists (ADR-036, D7);
4. the effective finance level, min(written, signed), is N3 or above (D6);
5. the kill switch is not engaged (R4);
6. the intent has a granted, unexpired approval for ``live``, bound to its very content (D4).

Every condition is read again from disk at each submission: nothing is cached, so a change by
Lucas, or the kill switch, applies to the next call. A false condition raises
:class:`LiveDisabled`, which names every failing condition, and the client is never called. Once
all six hold, the approval is spent, once, before the submission (D4).

Cancelling and reading never add exposure: ``cancel``, ``cancel_all`` (the kill switch's move)
and the reads stay allowed whatever the conditions. Every call to the client is bounded by a
timeout shorter than the kill switch's target, and raises :class:`TimeoutError` past it (B171).
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
from core.execution.broker import AccountStatement, BrokerAck, BrokerOrder, FillBatch
from core.execution.intent import OrderIntent
from core.execution.ownership import protected_owner
from core.governance.signatures import SIGNATURES_DIR, effective_autonomy, read_signatures
from core.policy.engine import kill_switch_engaged

LIVE_FILE = Path("config") / "live.yaml"
LIVE_DOMAIN = "finance"
LIVE_FROM = "N3"  # the lowest level that may reach a real broker (ADR-036)
_T = TypeVar("_T")


class Condition(StrEnum):
    """The six conditions of a live submission (D9), in the order they are checked."""

    CONFIGURATION = "configuration_live"
    ACL = "acl"
    SIGNATURE = "signature_n3"
    NIVEAU = "niveau_effectif"
    KILL_SWITCH = "kill_switch"
    APPROBATION = "approbation"


Verdict = Mapping[Condition, str | None]  # None: the condition holds; else why it does not
Check = Callable[[OrderIntent, datetime], Verdict]


class LiveDisabled(Exception):
    """A submission refused before the broker: every failing condition, and why."""

    def __init__(self, failures: tuple[tuple[Condition, str], ...]) -> None:
        detail = " ; ".join(f"{condition} : {reason}" for condition, reason in failures)
        super().__init__(f"live refusé, aucun appel au courtier ({detail})")
        self.failures = failures

    @property
    def conditions(self) -> tuple[Condition, ...]:
        return tuple(condition for condition, _ in self.failures)


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


class ActivationCheck:
    """The six conditions, read from the files under ``root`` at each call (D9)."""

    def __init__(
        self,
        root: Path,
        approvals: ApprovalStore,
        *,
        owner: Callable[[Path], bool] = protected_owner,
        load: Callable[[Path], Config] = load_config,
    ) -> None:
        self.root = root
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
            verdict[Condition.NIVEAU] = config
        else:
            verdict[Condition.CONFIGURATION] = live_incomplete(config.live)
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
        loose = [
            path.as_posix()
            for path in (LIVE_FILE, SIGNATURES_DIR)
            if not self.owner(self.root / path)
        ]
        if loose:
            return f"propriétaire non protégé : {', '.join(loose)} (protect-live.ps1)"
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


class LiveAdapter:
    """``BrokerAdapter`` over a real client; only ``submit`` needs the six conditions."""

    def __init__(
        self,
        client: BrokerClient,
        approvals: ApprovalStore,
        check: Check,
        *,
        call_timeout_s: float,
        kill_target_s: float | None,
    ) -> None:
        if not math.isfinite(call_timeout_s) or call_timeout_s <= 0:
            raise ValueError("délai d'appel au courtier : nombre de secondes > 0 attendu")
        if kill_target_s is not None and call_timeout_s >= kill_target_s:
            raise ValueError(
                f"délai d'appel {call_timeout_s} s : il doit rester sous la cible du kill switch "
                f"({kill_target_s} s, B171)"
            )
        self._client = client
        self._approvals = approvals
        self._check = check
        self._timeout_s = call_timeout_s

    def submit(self, intent: OrderIntent, *, now: datetime) -> BrokerAck:
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
