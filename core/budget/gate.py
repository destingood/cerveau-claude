"""Budget gate: daily and monthly LLM spending, and the limits of one request (ADR-005).

``BudgetGate.check`` runs before every request. It is blocked while a budget holds a marker
(R7), journals each alert threshold of ``alerts_pct`` once per period as a ``POLICY`` entry,
sends it as an alert when channels are given (B46, ADR-038: the period and the percentage, never
an amount), and refuses any new request once a budget is reached (100 %, D9). Phase 1
implements only the refusal: ``downgrade_to_fast_or_local`` and ``stop_non_critical_tasks`` are
in the backlog, so a reached budget refuses whatever ``on_exceeded`` lists. The check happens
before a request, so
the overshoot is at most the cost of one request, itself bounded by ``RequestBudget``.

Two requests started at the same instant may both pass the gate or both journal an alert:
CERVEAU is a single-user tool in phase 1, and the per-request limits bound the overshoot.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, tzinfo
from decimal import Decimal
from typing import Any, Literal

from core.audit.chain import AuditJournal
from core.budget.ledger import ALERT_KEY, Spending, read_spending
from core.config.loader import Config, PerCommittee, PerRequest
from core.learning.errors import budget_error, journal_errors
from core.models.meter import Meter
from core.notify.alerts import Alert, Alerts, budget_severity

Period = Literal["jour", "mois"]
Limit = Literal["tool_calls", "tokens", "seconds"]

_LIMIT_LABELS: dict[Limit, str] = {
    "tool_calls": "appels d'outils",
    "tokens": "tokens",
    "seconds": "secondes",
}


@dataclass(frozen=True)
class BudgetAlert:
    period: Period
    period_key: str
    pct: int
    spent_eur: Decimal
    limit_eur: Decimal

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.period, self.period_key, self.pct)

    def to_payload(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "period_key": self.period_key,
            "pct": self.pct,
            "spent_eur": str(self.spent_eur),
            "limit_eur": str(self.limit_eur),
        }

    def alert(self, at: datetime) -> Alert:
        """The alert of this threshold: the period and the percentage, never an amount (D14)."""
        ref = f"{self.period}-{self.period_key}-{self.pct}"
        return Alert.of("budget", ref, at, budget_severity(self.pct))

    def message(self) -> str:
        return (
            f"Budget du {self.period} ({self.period_key}) à {self.pct} % : "
            f"{self.spent_eur} € dépensés sur {self.limit_eur} €."
        )


@dataclass(frozen=True)
class BudgetCheck:
    spending: Spending
    daily_limit_eur: Decimal
    monthly_limit_eur: Decimal
    alerts: tuple[BudgetAlert, ...]  # every threshold reached in the current day and month
    journaled: tuple[BudgetAlert, ...] = ()  # those written to the journal by this check

    @property
    def exceeded(self) -> tuple[BudgetAlert, ...]:
        return tuple(a for a in self.alerts if a.pct >= 100)

    def highest(self) -> tuple[BudgetAlert, ...]:
        """The highest threshold reached per period, for display."""
        best: dict[str, BudgetAlert] = {}
        for alert in self.alerts:
            if alert.period not in best or alert.pct > best[alert.period].pct:
                best[alert.period] = alert
        return tuple(best.values())


class BudgetExceededError(Exception):
    """A daily or monthly budget is reached: new requests are refused (D9)."""

    def __init__(self, check: BudgetCheck) -> None:
        self.check = check
        details = " ".join(a.message() for a in check.exceeded)
        super().__init__(f"{details} Nouvelle requête refusée jusqu'à la période suivante.")


class BudgetGate:
    def __init__(
        self,
        config: Config,
        journal: AuditJournal,
        *,
        tz: tzinfo | None = None,
        alerts: Alerts | None = None,
    ) -> None:
        self._config = config
        self._journal = journal
        self._tz = tz  # None: the machine's local time
        self._alerts = alerts  # None: the journal and the console only

    def _limits(self) -> tuple[Decimal, Decimal]:
        self._config.require("budgets")  # a marker blocks every request (R7)
        budget = self._config.budgets.llm_budget_eur
        if not (isinstance(budget.daily, Decimal) and isinstance(budget.monthly, Decimal)):
            raise ValueError("budgets non définis : requête bloquée (R7)")
        return budget.daily, budget.monthly

    def status(self, *, now: datetime | None = None) -> BudgetCheck:
        """Spending and thresholds reached, without writing to the journal."""
        daily, monthly = self._limits()
        spending = read_spending(self._journal, now or datetime.now().astimezone(), self._tz)
        alerts = [
            BudgetAlert(period, key, pct, spent, limit)
            for period, key, spent, limit in (
                ("jour", spending.day_key, spending.day_eur, daily),
                ("mois", spending.month_key, spending.month_eur, monthly),
            )
            for pct in self._config.budgets.alerts_pct
            if spent * 100 >= limit * pct
        ]
        return BudgetCheck(spending, daily, monthly, tuple(alerts))

    def check(self, *, now: datetime | None = None, request_id: str | None = None) -> BudgetCheck:
        """Journals the new thresholds, then refuses the request if a budget is reached."""
        now = now or datetime.now().astimezone()
        check = self.status(now=now)
        journaled: list[BudgetAlert] = []
        for alert in check.alerts:
            if alert.key in check.spending.alerts:
                continue
            self._journal.append(
                actor="policy",
                event="POLICY",
                request_id=request_id,
                versions={"config": self._config.digest},
                payload={ALERT_KEY: alert.to_payload()},
                now=now,
            )
            journaled.append(alert)
        if journaled and self._alerts is not None:  # never refuses for an alert (ADR-038)
            self._alerts.send(
                [alert.alert(now) for alert in journaled],
                journal=self._journal,
                actor="policy",
                request_id=request_id,
                versions={"config": self._config.digest},
                now=now,
            )
        check = BudgetCheck(
            check.spending,
            check.daily_limit_eur,
            check.monthly_limit_eur,
            check.alerts,
            tuple(journaled),
        )
        if check.exceeded:
            journal_errors(
                self._journal,
                [budget_error(alert.to_payload() for alert in check.exceeded)],
                actor="policy",
                request_id=request_id,
                versions={"config": self._config.digest},
                now=now,
            )
            raise BudgetExceededError(check)
        return check


class RequestBudgetExceeded(Exception):
    """A per-request limit is reached: the request ends with an honest partial answer."""

    def __init__(self, limit: Limit, used: float, maximum: int) -> None:
        self.limit = limit
        self.used = used
        self.maximum = maximum
        super().__init__(
            f"limite par requête atteinte : {_LIMIT_LABELS[limit]} {used:g} sur {maximum}"
        )


def _session(limits: PerCommittee, refusal: str) -> PerRequest:
    """The limits of a committee session or a deep research, as a request's; a marker refuses."""
    values = (limits.max_tool_calls, limits.max_tokens, limits.max_seconds)
    if not all(isinstance(value, int) for value in values):  # a marker remains
        raise ValueError(refusal)
    tool_calls, tokens, seconds = (int(value) for value in values)
    return PerRequest(max_tool_calls=tool_calls, max_tokens=tokens, max_seconds=seconds)


class RequestBudget:
    """Tool calls, tokens and seconds of one request (``budgets.yaml`` › ``per_request``)."""

    def __init__(
        self,
        per_request: PerRequest,
        meter: Meter,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(per_request.max_tokens, int):
            raise ValueError("per_request.max_tokens non défini : requête bloquée (R7)")
        self._limits = per_request
        self._max_tokens = per_request.max_tokens
        self._meter = meter
        self._clock = clock
        self._start = clock()
        self.tool_calls = 0

    @classmethod
    def from_config(cls, config: Config, meter: Meter, **kwargs: Any) -> RequestBudget:
        config.require("budgets")
        return cls(config.budgets.per_request, meter, **kwargs)

    @classmethod
    def for_committee(
        cls, config: Config, meter: Meter, *, feature: str, **kwargs: Any
    ) -> RequestBudget:
        """The limits of one committee session (``per_committee``, D18), checked like a request's.

        Blocked while ``feature`` (``finance.committee``) still holds a marker (R7).
        """
        config.require(feature)
        limits = config.budgets.per_committee
        refusal = "per_committee non défini : séance bloquée (R7)"
        return cls(_session(limits, refusal), meter, **kwargs)

    @classmethod
    def for_deep_research(
        cls, config: Config, meter: Meter, *, feature: str, **kwargs: Any
    ) -> RequestBudget:
        """The limits of one deep research (``per_deep_research``, D13), checked like a request's.

        Blocked while ``feature`` (``recherche.deep_research``) still holds a marker (R7).
        """
        config.require(feature)
        limits = config.budgets.per_deep_research
        refusal = "per_deep_research non défini : recherche bloquée (R7)"
        return cls(_session(limits, refusal), meter, **kwargs)

    @property
    def max_seconds(self) -> int:
        return self._limits.max_seconds

    @property
    def elapsed_s(self) -> float:
        return self._clock() - self._start

    def charge_tool_call(self) -> None:
        """Counts one tool call before it is made; refuses the one beyond the limit."""
        self.check()
        if self.tool_calls >= self._limits.max_tool_calls:
            raise RequestBudgetExceeded(
                "tool_calls", self.tool_calls + 1, self._limits.max_tool_calls
            )
        self.tool_calls += 1

    def check(self) -> None:
        tokens = self._meter.total_tokens
        if tokens >= self._max_tokens:
            raise RequestBudgetExceeded("tokens", tokens, self._max_tokens)
        elapsed = self.elapsed_s
        if elapsed >= self._limits.max_seconds:
            raise RequestBudgetExceeded("seconds", round(elapsed, 3), self._limits.max_seconds)

    def remaining_seconds(self) -> float:
        return max(0.0, self._limits.max_seconds - self.elapsed_s)

    def remaining_tokens(self) -> int:
        return max(0, self._max_tokens - self._meter.total_tokens)

    def to_payload(self) -> dict[str, Any]:
        return {
            "tool_calls": {"used": self.tool_calls, "max": self._limits.max_tool_calls},
            "tokens": {"used": self._meter.total_tokens, "max": self._max_tokens},
            "seconds": {"used": round(self.elapsed_s, 3), "max": self._limits.max_seconds},
        }
