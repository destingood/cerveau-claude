"""What the CLI and the local API share: the paper account opened, and the stop of everything.

``open_paper_day`` and ``open_approvals`` open the files of a paper day the same way for
``cerveau paper`` and for the API (ADR-037), so an approval granted from Discord is sent exactly as
``cerveau paper envoyer`` would send it. ``stop_everything`` opens what a stop needs at best and
never refuses: a configuration, a book, a simulator or an approval store that cannot be read is
reported, and the stop goes on without it (R4, ADR-034).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

from core.approvals.store import ApprovalError, ApprovalRules, ApprovalStore, Trail
from core.approvals.store import default_store_path as approvals_path
from core.audit import AuditJournal
from core.config.loader import Config
from core.execution.book import OrderBook, Recorder, default_book_path
from core.execution.broker import BrokerAdapter
from core.execution.kill_switch import Stop, Trigger, engage
from core.execution.loop import BOOK_ACTOR, LOOP_ACTOR, LoopLog, PaperDay, default_loop_path
from core.execution.paper import (
    PaperSettings,
    PaperSimulator,
    SimulatorError,
    default_simulator_path,
)
from core.execution.reconcile import ReconciliationLog, default_log_path
from core.finance.store import FinanceStore, FinanceStoreError, default_store_path
from core.notify import Alerts


class PaperUnavailable(Exception):
    """The paper account cannot be opened; ``blocked`` when a parameter is to define (R7)."""

    def __init__(self, message: str, *, blocked: bool) -> None:
        super().__init__(message)
        self.blocked = blocked


def open_paper_day(
    stack: ExitStack,
    root: Path,
    config: Config,
    journal: AuditJournal,
    request_id: str,
    now: datetime,
    *,
    alerts: Alerts | None,
) -> PaperDay:
    """The paper account's files, opened in ``stack``; without sources nor approval store."""
    try:
        settings = PaperSettings.from_config(
            config.risk_limits_paper, config.execution, config.risk.trading_costs
        )
    except SimulatorError as exc:
        raise PaperUnavailable(str(exc), blocked=True) from exc
    try:
        store = stack.enter_context(FinanceStore.open(default_store_path(root), read_only=True))
    except FinanceStoreError as exc:
        raise PaperUnavailable(str(exc), blocked=False) from exc
    return PaperDay(
        root=root,
        config=config,
        store=store,
        book=stack.enter_context(
            OrderBook.open(
                default_book_path(root), recorder=Recorder(journal, BOOK_ACTOR, request_id)
            )
        ),
        simulator=stack.enter_context(
            PaperSimulator.open(default_simulator_path(root), settings, now=now)
        ),
        reconciliations=stack.enter_context(
            ReconciliationLog.open(
                default_log_path(root), Recorder(journal, LOOP_ACTOR, request_id)
            )
        ),
        log=stack.enter_context(LoopLog.open(default_loop_path(root))),
        journal=journal,
        request_id=request_id,
        alerts=alerts,
    )


def open_approvals(
    stack: ExitStack, root: Path, config: Config, journal: AuditJournal, request_id: str
) -> tuple[ApprovalStore | None, str | None]:
    """The approval store opened in ``stack``, or why it stays closed (R7)."""
    try:
        rules = ApprovalRules.from_config(config.autonomy.approval)
    except ApprovalError as exc:
        return None, f"registre des approbations fermé : {exc}"
    trail = Trail(journal, request_id, {"config": config.digest})
    return stack.enter_context(
        ApprovalStore.open(approvals_path(root), rules=rules, trail=trail)
    ), None


def _stop_settings(
    root: Path, config: Config | None, unavailable: list[str]
) -> tuple[float | None, PaperSettings | None, ApprovalRules | None]:
    """The target, the paper settings and the approval rules, None for what is unknown; a paper
    account or an approval store that exists but cannot be opened goes in ``unavailable``."""
    if config is None:
        unavailable.append("configuration invalide : cible, compte paper et approbations inconnus")
        return None, None, None
    target = config.risk.kill_switch.target_seconds
    settings: PaperSettings | None = None
    try:
        settings = PaperSettings.from_config(
            config.risk_limits_paper, config.execution, config.risk.trading_costs
        )
    except Exception as exc:  # a stop never waits for a setting
        if default_simulator_path(root).is_file():
            unavailable.append(f"simulateur paper non ouvert ({exc})")
    rules: ApprovalRules | None = None
    try:
        rules = ApprovalRules.from_config(config.autonomy.approval)
    except ApprovalError as exc:
        if approvals_path(root).is_file():
            unavailable.append(f"registre des approbations non ouvert ({exc})")
    target_s = None if isinstance(target, str) else float(target)
    return target_s, settings, rules


def stop_everything(
    root: Path,
    config: Config | None,
    *,
    trigger: Trigger,
    reason: str,
    journal: AuditJournal,
    actor: str,
    request_id: str,
    now: datetime,
    alerts: Alerts | None,
    unavailable: list[str] | None = None,
    clock: Callable[[], float] | None = None,
) -> Stop:
    """Open what a stop needs at best, then :func:`engage` it; never refuses (R4).

    ``config`` is None when the configuration cannot be read: the stop then has no target and
    cancels nothing it cannot open. The book and the approval store journal as ``actor``.
    """
    missing = [] if unavailable is None else unavailable
    target, settings, rules = _stop_settings(root, config, missing)
    with ExitStack() as stack:
        book: OrderBook | None = None
        if default_book_path(root).is_file():
            try:
                book = stack.enter_context(
                    OrderBook.open(
                        default_book_path(root), recorder=Recorder(journal, actor, request_id)
                    )
                )
            except Exception as exc:
                missing.append(f"carnet d'ordres non ouvert ({type(exc).__name__})")
        adapter: BrokerAdapter | None = None
        if settings is not None and default_simulator_path(root).is_file():
            try:
                adapter = stack.enter_context(
                    PaperSimulator.open(default_simulator_path(root), settings, now=now)
                )
            except Exception as exc:
                missing.append(f"simulateur paper non ouvert ({type(exc).__name__})")
        approvals: ApprovalStore | None = None
        if rules is not None and approvals_path(root).is_file():
            try:
                approvals = stack.enter_context(
                    ApprovalStore.open(
                        approvals_path(root), rules=rules, trail=Trail(journal, request_id)
                    )
                )
            except Exception as exc:
                missing.append(f"registre des approbations non ouvert ({type(exc).__name__})")
        timing = {} if clock is None else {"clock": clock}
        return engage(
            root,
            trigger=trigger,
            reason=reason,
            journal=journal,
            actor=actor,
            request_id=request_id,
            now=now,
            target_seconds=target,
            adapter=adapter,
            book=book,
            approvals=approvals,
            alerts=alerts,
            unavailable=missing,
            **timing,
        )
