"""What the API shows: states, counts and percentages read from CERVEAU's files (D12, ADR-037).

A store is opened only if its file exists, so a read never creates one, and nothing here writes:
a reader opens it read only, so it neither locks nor migrates it (B215, B232); only the approval
routes open the approval store for writing.
The one exception to D12 is the summary of an approval request, which names what is asked.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from contextlib import ExitStack
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from core.approvals.store import (
    ApprovalError,
    ApprovalRequest,
    ApprovalRules,
    ApprovalState,
    ApprovalStore,
    Trail,
)
from core.approvals.store import default_store_path as approvals_path
from core.audit import AuditJournal, default_journal_path, verify
from core.budget.gate import BudgetGate
from core.config import BlockedFeatureError
from core.config.loader import Config
from core.execution.book import OrderBook, OrderBookError, Recorder, default_book_path
from core.execution.kill_switch import recorded_stop
from core.execution.loop import LoopLog, Run, Valuation, default_loop_path
from core.execution.reconcile import ReconciliationLog, default_log_path
from core.execution.states import OPEN
from core.finance.schema import SchemaError
from core.governance.signatures import effective_autonomy
from core.policy.engine import kill_switch_engaged

READER = "interface"  # opening a book or a log journals nothing; the recorder is never used
CENT = Decimal("0.01")
READ_ERRORS = (ApprovalError, OrderBookError, SchemaError, sqlite3.Error)  # opened read only


def _iso(value: datetime | date | None) -> str | None:
    return None if value is None else value.isoformat()


def kill_view(root: Path) -> dict[str, Any]:
    engaged = kill_switch_engaged(root)
    recorded = recorded_stop(root) if engaged else None
    return {
        "engaged": engaged,
        "trigger": None if recorded is None else recorded.trigger,
        "engaged_at": None if recorded is None else recorded.engaged_at,
    }


def autonomy_view(config: Config, root: Path) -> dict[str, Any]:
    """Each domain's written level and the level in force once capped by the signatures (D6)."""
    effective = effective_autonomy(config.autonomy, root)
    domains = [
        {
            "domain": name,
            "written": spec.level,
            "effective": effective.autonomy.domains[name].level,
        }
        for name, spec in sorted(config.autonomy.domains.items())
    ]
    return {
        "domains": domains,
        "capped": list(effective.capped),
        "problems": list(effective.problems),
    }


def approval_store(
    stack: ExitStack,
    root: Path,
    config: Config,
    journal: AuditJournal,
    request_id: str,
    *,
    read_only: bool = False,
) -> tuple[ApprovalStore | None, str | None]:
    """The approval store if its file exists, or why it stays closed (a marker in a setting of
    the ``approvals`` feature, R7); None, None without file. ``read_only`` neither locks nor
    migrates it, and a store that cannot be read so stays closed (B232)."""
    try:
        config.require("approvals")
        rules = ApprovalRules.from_config(config.autonomy.approval)
    except (BlockedFeatureError, ApprovalError) as exc:
        return None, f"registre des approbations fermé : {exc}"
    path = approvals_path(root)
    if not path.is_file():
        return None, None
    if read_only:
        try:
            return stack.enter_context(ApprovalStore.open(path, rules=rules, read_only=True)), None
        except READ_ERRORS as exc:
            return None, f"registre des approbations illisible : {exc}"
    trail = Trail(journal, request_id, {"config": config.digest})
    return stack.enter_context(ApprovalStore.open(path, rules=rules, trail=trail)), None


def approvals_view(
    store: ApprovalStore | None, closed: str | None, now: datetime
) -> dict[str, Any]:
    if closed is not None:
        return {"open": False, "reason": closed, "pending": 0, "granted": 0, "locked": False}
    if store is None:
        return {"open": True, "reason": None, "pending": 0, "granted": 0, "locked": False}
    counts = store.counts(now=now)
    return {
        "open": True,
        "reason": None,
        "pending": counts[ApprovalState.DEMANDEE],
        "granted": counts[ApprovalState.ACCORDEE],
        "locked": store.locked(now=now),
    }


def pending_item(request: ApprovalRequest, rules: ApprovalRules) -> dict[str, Any]:
    """One request waiting for Lucas: the only answer that may name an amount (D12)."""
    gate: Mapping[str, Any] = request.gate
    checks = gate.get("checks", [])
    failed = [
        str(check.get("name"))
        for check in checks
        if isinstance(check, Mapping) and not check.get("ok")
    ]
    return {
        "approval_id": str(request.approval_id),
        "intent_id": str(request.intent_id),
        "environment": request.environment,
        "summary": request.summary,
        "created_at": _iso(request.created_at),
        "expires_at": _iso(request.expires_at),
        "attempts_left": max(rules.max_code_attempts - request.failures, 0),
        "gate": {
            "result": gate.get("result"),
            "requested_quantity": gate.get("requested_quantity"),
            "quantity": gate.get("quantity"),
            "failed_checks": failed,
        },
    }


def orders_view(stack: ExitStack, root: Path) -> dict[str, int]:
    path = default_book_path(root)
    if not path.is_file():
        return {"open": 0, "total": 0}
    book = stack.enter_context(OrderBook.open(path, read_only=True))
    return {"open": len(book.orders(OPEN)), "total": len(book.orders())}


def reconciliation_view(stack: ExitStack, root: Path, journal: AuditJournal) -> dict[str, Any]:
    path = default_log_path(root)
    if not path.is_file():
        return {"last_at": None, "open_gaps": 0, "awaiting_acknowledgement": False}
    recorder = Recorder(journal, READER, "api")
    log = stack.enter_context(ReconciliationLog.open(path, recorder, read_only=True))
    return {
        "last_at": _iso(log.last_reconciled_at()),
        "open_gaps": log.open_gaps(),
        "awaiting_acknowledgement": log.awaiting_acknowledgement(),
    }


def loop_log(stack: ExitStack, root: Path) -> LoopLog | None:
    path = default_loop_path(root)
    if not path.is_file():
        return None
    return stack.enter_context(LoopLog.open(path, read_only=True))


def loop_view(log: LoopLog | None) -> dict[str, Any]:
    run = None if log is None else log.run()
    return {
        "last_day": None if run is None else _iso(run.day),
        "completed_at": None if run is None else _iso(run.completed_at),
    }


def _pct(spent: Decimal, limit: Decimal) -> int:
    return int(spent * 100 / limit) if limit > 0 else 100


def budget_view(config: Config, journal: AuditJournal, now: datetime) -> dict[str, Any]:
    """The LLM budget spent today and this month, as whole percentages of the ceilings (B46)."""
    try:
        check = BudgetGate(config, journal).status(now=now)
    except (BlockedFeatureError, ValueError):
        return {
            "defined": False,
            "reason": "budgets à définir (R7)",
            "day_pct": None,
            "month_pct": None,
        }
    return {
        "defined": True,
        "reason": None,
        "day_pct": _pct(check.spending.day_eur, check.daily_limit_eur),
        "month_pct": _pct(check.spending.month_eur, check.monthly_limit_eur),
    }


def change_pct(valuations: list[Valuation], day: date) -> Decimal | None:
    """The equity's change from the last valuation before ``day`` to ``day``'s, in percent."""
    today = next((v for v in valuations if v.day == day), None)
    before = [v for v in valuations if v.day < day]
    if today is None or not before or before[-1].equity_eur <= 0:
        return None
    previous = before[-1].equity_eur
    return ((today.equity_eur - previous) * 100 / previous).quantize(CENT)


def _signed(value: Decimal) -> str:
    return f"{value:+}".replace(".", ",")


def daily_report(
    stack: ExitStack,
    root: Path,
    config: Config,
    journal: AuditJournal,
    request_id: str,
    now: datetime,
    run: Run,
    log: LoopLog,
) -> dict[str, Any]:
    """The day's report for Lucas's private message: no amount, no position (D12), and the head
    of the audit chain as an external, timestamped anchor (D13, B8)."""
    change = change_pct(log.valuations(), run.day)
    store, closed = approval_store(stack, root, config, journal, request_id, read_only=True)
    counts = dict.fromkeys(ApprovalState, 0) if store is None else store.counts(now=now)
    orders = orders_view(stack, root)
    reconciliation = reconciliation_view(stack, root, journal)
    kill = kill_view(root)
    chain = verify(default_journal_path(root))
    audit = {"ok": chain.ok, "head_seq": chain.head_seq, "head_hash": chain.head_hash}
    approvals = {state.value: counts[state] for state in ApprovalState}
    lines = [
        f"Rapport quotidien CERVEAU du {run.day:%d/%m/%Y} (compte paper)",
        f"Journée traitée : {run.intents} intention(s).",
        "Valorisation : "
        + (
            "pas de journée précédente."
            if change is None
            else f"{_signed(change)} % sur la journée précédente."
        ),
        f"Approbations : {counts[ApprovalState.DEMANDEE]} en attente, "
        f"{counts[ApprovalState.ACCORDEE]} accordée(s), {counts[ApprovalState.REFUSEE]} "
        f"refusée(s), {counts[ApprovalState.EXPIREE]} expirée(s), "
        f"{counts[ApprovalState.CONSOMMEE]} consommée(s)"
        + ("." if closed is None else f" ; {closed}."),
        f"Ordres ouverts : {orders['open']}.",
        "Réconciliation : "
        + (
            f"{reconciliation['open_gaps']} écart(s) ouvert(s)."
            if reconciliation["open_gaps"]
            else "aucun écart ouvert."
        ),
        "Kill switch : " + (f"ENGAGÉ ({kill['trigger']})." if kill["engaged"] else "armé."),
        f"Journal d'audit : chaîne {'vérifiée' if chain.ok else 'ROMPUE'}, tête n° "
        f"{chain.head_seq} {chain.head_hash}",
    ]
    return {
        "day": _iso(run.day),
        "completed_at": _iso(run.completed_at),
        "intents": run.intents,
        "valuation_change_pct": None if change is None else str(change),
        "approvals": approvals,
        "approvals_closed": closed,
        "orders": orders,
        "reconciliation": reconciliation,
        "kill_switch": kill,
        "audit": audit,
        "text": "\n".join(lines),
    }
