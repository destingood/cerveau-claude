"""Alerts with minimal content, sent to every channel without ever blocking (ADR-038).

An alert carries a kind, a severity (1 to 5, ntfy's priority) and an identifier: a request, an
order or a period. Never an amount, an instrument or an external text: a topic that leaks teaches
nothing (D14). :class:`Alerts` sends each alert to every channel, journals one ``POLICY`` entry per
alert with the channels reached and the type of each failure, never its text, and never raises:
an alert that cannot leave never holds a stop (R4).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, get_args
from uuid import UUID

AlertKind = Literal[
    "kill_switch",
    "annulation_non_confirmee",
    "incident_execution",
    "limite_depassee",
    "ecart_reconciliation",
    "approbations_verrouillees",
    "budget",
    "rapport_quotidien",
    "rapport_planifie_en_echec",
]
ALERT_KINDS: tuple[AlertKind, ...] = get_args(AlertKind)
NOTIFICATION_KEY = "notification"

LABELS: Mapping[AlertKind, str] = {
    "kill_switch": "kill switch engagé",
    "annulation_non_confirmee": "annulation non confirmée par le courtier",
    "incident_execution": "incident d'exécution : kill switch engagé",
    "limite_depassee": "limite de perte dépassée : kill switch engagé",
    "ecart_reconciliation": "écart de réconciliation",
    "approbations_verrouillees": "approbations verrouillées : trop de codes faux",
    "budget": "seuil de budget atteint",
    "rapport_quotidien": "rapport quotidien prêt",
    "rapport_planifie_en_echec": "rapport planifié en échec",
}
SEVERITIES: Mapping[AlertKind, int] = {
    "kill_switch": 5,
    "annulation_non_confirmee": 5,
    "incident_execution": 5,
    "limite_depassee": 5,
    "ecart_reconciliation": 4,
    "approbations_verrouillees": 4,
    "budget": 3,
    "rapport_quotidien": 2,
    "rapport_planifie_en_echec": 4,
}
# Which kind a kill switch trigger gives; any other trigger is a plain "kill_switch".
TRIGGER_KINDS: Mapping[str, AlertKind] = {
    "incident_execution": "incident_execution",
    "limite": "limite_depassee",
    "drawdown": "limite_depassee",
}

_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,63}$")
_NOT_REF = re.compile(r"[^A-Za-z0-9:._-]")


def as_ref(text: str) -> str:
    """An identifier an alert may carry: unexpected characters become ``_``, 64 at most."""
    ref = _NOT_REF.sub("_", text)[:64]
    return ref if _REF.match(ref) else "inconnu"


@dataclass(frozen=True)
class Alert:
    kind: AlertKind
    severity: int  # 1 (min) to 5 (urgent), as ntfy's priority
    ref: str  # an identifier, never an amount, an instrument or an external text (D14)
    at: datetime

    def __post_init__(self) -> None:
        if self.kind not in ALERT_KINDS:
            raise ValueError(f"type d'alerte inconnu : {self.kind!r}")
        if isinstance(self.severity, bool) or self.severity not in range(1, 6):
            raise ValueError(f"gravité hors de 1 à 5 : {self.severity!r}")
        if not _REF.match(self.ref):
            raise ValueError(
                "identifiant d'alerte invalide : lettres, chiffres, « :._- », 64 au plus"
            )
        if self.at.tzinfo is None:
            raise ValueError("horodatage d'alerte sans fuseau")

    @classmethod
    def of(cls, kind: AlertKind, ref: str, at: datetime, severity: int | None = None) -> Alert:
        return cls(kind, SEVERITIES[kind] if severity is None else severity, as_ref(ref), at)

    @property
    def title(self) -> str:
        """ASCII only: an HTTP header (``X-Title``) carries it."""
        return f"CERVEAU {self.kind}"

    def text(self) -> str:
        when = self.at.astimezone(UTC).strftime("%d/%m/%Y %H:%M")
        return f"{LABELS[self.kind]} ; gravité {self.severity}/5 ; réf. {self.ref} ; {when} UTC"

    def to_payload(self) -> dict[str, Any]:
        return {"kind": self.kind, "severity": self.severity, "ref": self.ref}


def stop_alerts(trigger: str, ref: str, unconfirmed: Iterable[UUID], at: datetime) -> list[Alert]:
    """A stop's alerts: the stop itself, then one per unconfirmed cancellation (B172)."""
    alerts = [Alert.of(TRIGGER_KINDS.get(trigger, "kill_switch"), ref, at)]
    alerts.extend(Alert.of("annulation_non_confirmee", str(key), at) for key in unconfirmed)
    return alerts


def budget_severity(pct: int) -> int:
    """50 % informs, 80 % warns, 100 % refuses every request (D9): urgent."""
    if pct >= 100:
        return 5
    return 4 if pct >= 80 else 3


class Notifier(Protocol):
    """One channel. ``send`` raises when the alert does not leave; :class:`Alerts` catches."""

    @property
    def channel(self) -> str: ...

    def send(self, alert: Alert) -> None: ...


class _Journal(Protocol):
    def append(
        self,
        *,
        actor: str,
        event: str,
        request_id: str | None = None,
        versions: Mapping[str, str] | None = None,
        payload: Any = None,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Alerts:
    """Every configured channel. Without any, an alert stays in the journal and on the console."""

    channels: tuple[Notifier, ...] = ()

    def send(
        self,
        alerts: Sequence[Alert],
        *,
        journal: _Journal | None,
        actor: str,
        request_id: str | None,
        versions: Mapping[str, str] | None = None,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        """Send each alert to each channel; the failures, ``"<channel> : <error type>"``.
        Without any channel, nothing is written: the event's own entry is already journaled."""
        failures: list[str] = []
        if not self.channels:
            return ()
        for alert in alerts:
            sent: list[str] = []
            failed: dict[str, str] = {}
            for notifier in self.channels:
                try:
                    notifier.send(alert)
                except Exception as exc:  # an alert never holds what raised it (R4, ADR-038)
                    failed[notifier.channel] = type(exc).__name__
                    failures.append(f"{notifier.channel} : {type(exc).__name__}")
                else:
                    sent.append(notifier.channel)
            if journal is None:
                continue
            payload = {NOTIFICATION_KEY: {**alert.to_payload(), "sent": sent, "failed": failed}}
            try:
                journal.append(
                    actor=actor,
                    event="POLICY",
                    request_id=request_id,
                    versions=versions,
                    payload=payload,
                    now=now or alert.at,
                )
            except Exception as exc:
                failures.append(f"journal : {type(exc).__name__}")
        return tuple(failures)
