"""Daily and monthly spending, rebuilt from the audit journal (ADR-005).

The journal is the only source of truth for money spent: each request's ``DECISION`` entry
carries a ``cost`` block (``core.models.Meter.to_payload``) and only ``DECISION`` entries are
summed, so detail figures in ``TOOL_CALL`` entries can never be counted twice. Budget alerts
already raised are ``POLICY`` entries with a ``budget_alert`` block. Days and months follow the
machine's local time unless a time zone is given.

Anything unreadable or altered (an entry or payload that no longer matches its hash) makes the
spending unknown, and an unknown spending blocks (R7). The whole journal is read at each check;
an index is in the backlog.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from decimal import Decimal, InvalidOperation
from typing import Any

from core.audit.chain import HASH_RE, AuditJournal, entry_hash, sha256_ref
from core.models.costs import COST_SCHEMA

COST_KEY = "cost"
ALERT_KEY = "budget_alert"


class LedgerError(Exception):
    """The journal cannot be read reliably: spending is unknown."""


@dataclass(frozen=True)
class Spending:
    day: date
    day_eur: Decimal = Decimal(0)
    month_eur: Decimal = Decimal(0)
    # (period, period_key, pct) of the alerts already written to the journal
    alerts: frozenset[tuple[str, str, int]] = field(default_factory=frozenset)

    @property
    def day_key(self) -> str:
        return self.day.isoformat()

    @property
    def month_key(self) -> str:
        return f"{self.day:%Y-%m}"


def _cost_eur(cost: Any, where: str) -> Decimal:
    if not isinstance(cost, dict) or cost.get("cost_schema") != COST_SCHEMA:
        raise LedgerError(f"{where} : bloc de coût illisible ou de schéma inconnu")
    try:
        value = Decimal(str(cost["cost_eur"]))
    except (KeyError, InvalidOperation) as exc:
        raise LedgerError(f"{where} : montant en euros illisible") from exc
    if not value.is_finite() or value < 0:
        raise LedgerError(f"{where} : montant en euros invalide")
    return value


def _alert_key(alert: Any, where: str) -> tuple[str, str, int]:
    try:
        return (str(alert["period"]), str(alert["period_key"]), int(alert["pct"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise LedgerError(f"{where} : alerte de budget illisible") from exc


def _read_payload(journal: AuditJournal, ref: Any, where: str) -> Any:
    if not isinstance(ref, str) or not HASH_RE.match(ref):
        raise LedgerError(f"{where} : référence de payload invalide")
    target = journal.payload_dir / (ref.removeprefix("sha256:") + ".json")
    try:
        data = target.read_bytes()
    except OSError as exc:
        raise LedgerError(f"{where} : payload introuvable") from exc
    if sha256_ref(data) != ref:
        raise LedgerError(f"{where} : payload modifié")
    try:
        return json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LedgerError(f"{where} : payload illisible") from exc


def read_spending(journal: AuditJournal, now: datetime, tz: tzinfo | None = None) -> Spending:
    """Spending of the day and month of ``now``, and the alerts already raised this month."""
    today = now.astimezone(tz).date()
    if not journal.path.exists():
        return Spending(day=today)
    day_eur = month_eur = Decimal(0)
    alerts: set[tuple[str, str, int]] = set()
    try:
        lines = journal.path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise LedgerError(f"journal illisible : {exc}") from exc
    for lineno, line in enumerate(lines, start=1):
        where = f"journal, ligne {lineno}"
        try:
            entry = json.loads(line)
            event = entry["event"]
            ts = datetime.fromisoformat(entry["ts"]).astimezone(tz)
            intact = entry_hash(entry) == entry["hash"]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise LedgerError(f"{where} : entrée illisible") from exc
        if not intact:
            raise LedgerError(f"{where} : entrée modifiée")
        if (ts.year, ts.month) != (today.year, today.month):
            continue
        if event not in ("DECISION", "POLICY") or not entry.get("payload_ref"):
            continue
        payload = _read_payload(journal, entry["payload_ref"], where)
        if not isinstance(payload, dict):
            continue
        if event == "DECISION" and COST_KEY in payload:
            eur = _cost_eur(payload[COST_KEY], where)
            month_eur += eur
            if ts.date() == today:
                day_eur += eur
        if event == "POLICY" and ALERT_KEY in payload:
            alerts.add(_alert_key(payload[ALERT_KEY], where))
    return Spending(day=today, day_eur=day_eur, month_eur=month_eur, alerts=frozenset(alerts))
