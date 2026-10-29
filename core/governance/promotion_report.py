"""The N2 → N3 and N3 → N4 promotion reports (ADR-040, B181, ADR-067): each criterion of §8.3
with its value, its threshold, its status and the tool it comes from (R1).

No model writes a figure here: each one is counted or computed from what the paper loop, the
order book, the audit journal, the backtest engine and a sealed eval campaign recorded. A
threshold still ``A_DEFINIR`` or a measure that cannot be made leaves its criterion « non
évaluable », and the promotion impossible (R7).

The report signs nothing. It opens with a YAML header that ``signatures.py`` reads: a signature
from N3 on counts only when the report it cites is about the same domain and level and concludes
``promotion_possible``. Lucas copies the proposed signature text into ``governance/approvals/``
himself (ADR-036); no code writes there.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from core.audit import AuditError, AuditJournal, default_journal_path, verify
from core.config import BlockedFeatureError
from core.config.loader import LEVELS, Config, Level
from core.evals.promotion import PromotionCheck, PromotionError, check_promotion, load_report
from core.execution.book import (
    BookedOrder,
    OrderBook,
    OrderBookError,
    default_book_path,
    execution_gap_bps,
)
from core.execution.loop import LoopLog, Valuation, default_loop_path
from core.execution.sources import strategy_sources
from core.execution.states import TERMINAL
from core.finance.model import ParamValue, canonical_json
from core.finance.research import engine
from core.finance.research.execution import Costs, CostsError
from core.finance.research.view import LookAheadError, MarketHistory
from core.finance.schema import SchemaError
from core.finance.store import FinanceStore, FinanceStoreError, default_store_path
from core.governance.demotion import DEMOTIONS, read_demotions
from core.governance.signatures import (
    PROMOTION_DIR,
    REPORT_KIND,
    REPORT_PASSED,
    effective_level,
)

Status = Literal["atteint", "non_atteint", "non_evaluable", "sans_objet"]
Verdict = Literal["promotion_possible", "promotion_impossible", "non_evaluable"]
REPORTED = {("finance", "N3"): "N2_to_N3", ("finance", "N4"): "N3_to_N4"}  # ADR-040, ADR-067
EVALS_RULE = "N1_to_N2"  # golden, R1 to R5 and red team, measured live: the previous conditions
STATUS_TEXT: Mapping[Status, str] = {
    "atteint": "atteint",
    "non_atteint": "non atteint",
    "non_evaluable": "non évaluable",
    "sans_objet": "sans objet",
}
VERDICT_TEXT: Mapping[Verdict, str] = {
    REPORT_PASSED: "promotion possible, sous ta signature",
    "promotion_impossible": "promotion impossible : au moins un critère n'est pas atteint",
    "non_evaluable": "promotion impossible : au moins un critère est non évaluable (R7)",
}
MAX_LISTED = 10  # incidents listed in the detail; the count stays exact


class PromotionReportError(ValueError):
    """No report for this promotion, or it cannot be written."""


@dataclass(frozen=True)
class Unavailable:
    """Why a measure cannot be made: its criterion is « non évaluable »."""

    reason: str


@dataclass(frozen=True)
class Criterion:
    name: str
    value: str
    threshold: str
    status: Status
    source: str  # the tool or the file the value comes from (R1)
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class PromotionReport:
    domain: str
    level: Level
    generated_at: datetime
    config_digest: str
    criteria: tuple[Criterion, ...]

    @property
    def verdict(self) -> Verdict:
        """Possible only when every criterion is reached; a failed criterion outranks one that
        cannot be measured: the promotion is impossible whatever the missing value."""
        statuses = {criterion.status for criterion in self.criteria}
        if "non_atteint" in statuses:
            return "promotion_impossible"
        if "non_evaluable" in statuses or not self.criteria:
            return "non_evaluable"
        return REPORT_PASSED


def _threshold(value: int | float | str) -> int | float | None:
    return None if isinstance(value, str) else value


def _status(reached: bool, threshold: object) -> Status:
    if threshold is None:
        return "non_evaluable"
    return "atteint" if reached else "non_atteint"


def _unknown(name: str, value: str) -> str:
    return f"{name} = {value} dans autonomy.yaml (R7)"


# The criteria ------------------------------------------------------------------------------------


def current_level(level: Level, *, required: Level) -> Criterion:
    """Promotions climb one level at a time: N3 is asked from N2 in force."""
    reached = LEVELS.index(level) >= LEVELS.index(required)
    return Criterion(
        "Niveau en vigueur",
        level,
        f"{required} au moins",
        "atteint" if reached else "non_atteint",
        "`effective_level` : le plus bas du niveau écrit et du niveau signé (ADR-036)",
    )


def paper_weeks(days: Sequence[date] | Unavailable, minimum: int | str) -> Criterion:
    """The weeks the paper loop ran: the fewer of the ISO weeks with a day treated and of the
    weeks begun between the first and the last day, so that a gap counts for nothing and two
    days astride a weekend do not count as two weeks."""
    source = "`LoopLog.days` : journées traitées (var/paper/loop.db, table runs)"
    threshold = _threshold(minimum)
    shown = f"≥ {minimum}" if threshold is not None else _unknown("paper_weeks_min", str(minimum))
    if isinstance(days, Unavailable):
        return Criterion("Semaines de paper", days.reason, shown, "non_evaluable", source)
    if not days:
        details: tuple[str, ...] = ("Aucune journée traitée par la boucle paper.",)
        weeks = 0
    else:
        first, last = days[0], days[-1]
        span = (last - first).days + 1
        begun = math.ceil(span / 7)
        iso = len({day.isocalendar()[:2] for day in days})
        weeks = min(iso, begun)
        details = (
            f"{len(days)} journée(s) traitée(s), du {first:%d/%m/%Y} au {last:%d/%m/%Y} : "
            f"{span} jour(s), {begun} semaine(s) entamée(s).",
            f"{iso} semaine(s) ISO comptant au moins une journée traitée.",
            "Retenu : le plus petit des deux.",
        )
    reached = threshold is not None and weeks >= threshold
    return Criterion(
        "Semaines de paper", str(weeks), shown, _status(reached, threshold), source, details
    )


def paper_decisions(orders: Sequence[BookedOrder] | Unavailable, minimum: int | str) -> Criterion:
    """Every intent the loop drafted and booked, whatever became of it: the Risk Gate, the
    policy and the market each decided something about it."""
    source = "`OrderBook.orders` : intentions inscrites au carnet (var/paper/orders.db)"
    threshold = _threshold(minimum)
    shown = f"≥ {minimum}" if threshold is not None else _unknown("decisions_min", str(minimum))
    if isinstance(orders, Unavailable):
        return Criterion("Décisions de paper", orders.reason, shown, "non_evaluable", source)
    states = Counter(order.state.value for order in orders)
    origins = Counter(f"{o.intent.origin.kind} {o.intent.origin.id}" for o in orders)
    details = (
        "Une décision : une intention rédigée et inscrite au carnet, quel que soit son sort.",
        "États : " + (", ".join(f"{s} {n}" for s, n in sorted(states.items())) or "aucun"),
        "Origines : " + (", ".join(f"{o} : {n}" for o, n in sorted(origins.items())) or "aucune"),
    )
    reached = threshold is not None and len(orders) >= threshold
    return Criterion(
        "Décisions de paper", str(len(orders)), shown, _status(reached, threshold), source, details
    )


def paper_drawdown(
    valuations: Sequence[Valuation] | Unavailable, maximum: float | str
) -> Criterion:
    """The deepest fall of the account's end-of-day value from its running peak, the first
    valuation counting as a peak; compared like the Risk Gate does, without a division."""
    source = "`LoopLog.valuations` : valeur du compte en fin de journée (var/paper/loop.db)"
    limit = _threshold(maximum)
    shown = (
        f"≤ {maximum} %" if limit is not None else _unknown("max_paper_drawdown_pct", str(maximum))
    )
    if isinstance(valuations, Unavailable):
        return Criterion("Drawdown paper", valuations.reason, shown, "non_evaluable", source)
    if not valuations:
        return Criterion("Drawdown paper", "aucune valorisation", shown, "non_evaluable", source)
    peak, peak_day = valuations[0].equity_eur, valuations[0].day
    worst = (Decimal(0), peak, peak_day, peak, peak_day)  # drop, peak, its day, trough, its day
    for valuation in valuations:
        equity = valuation.equity_eur
        if equity > peak:
            peak, peak_day = equity, valuation.day
        drop = peak - equity
        if drop * worst[1] > worst[0] * peak:  # drop / peak > worst drop / worst peak
            worst = (drop, peak, peak_day, equity, valuation.day)
    drop, top, top_day, trough, trough_day = worst
    if top <= 0:
        return Criterion("Drawdown paper", "valeur du compte nulle", shown, "non_evaluable", source)
    depth = drop * 100 / top
    if drop:
        detail = (
            f"Pic de {top} € le {top_day:%d/%m/%Y}, creux de {trough} € le {trough_day:%d/%m/%Y}."
        )
    else:
        detail = "Aucune baisse depuis un pic."
    details = (
        detail,
        f"{len(valuations)} valorisation(s), du {valuations[0].day:%d/%m/%Y} "
        f"au {valuations[-1].day:%d/%m/%Y}.",
    )
    reached = limit is not None and drop * 100 <= Decimal(str(limit)) * top
    return Criterion(
        "Drawdown paper", f"{depth:.2f} %", shown, _status(reached, limit), source, details
    )


@dataclass(frozen=True)
class Incident:
    at: str  # the journal's timestamp
    reason: str


def execution_incidents(journal: AuditJournal) -> list[Incident] | Unavailable:
    """Every stop the kill switch journaled for an execution incident, from the whole journal,
    once its chain is verified: an unverifiable journal counts nothing."""
    if not journal.path.exists():
        return []
    chain = verify(journal.path)
    if not chain.ok:
        return Unavailable(
            f"journal d'audit invalide ({len(chain.errors)} erreur(s)) : `cerveau audit verify`"
        )
    found: list[Incident] = []
    try:
        for line in journal.path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if entry.get("event") != "KILL" or not entry.get("payload_ref"):
                continue
            payload = journal.read_payload(entry["payload_ref"])
            if (
                isinstance(payload, Mapping)
                and payload.get("kill_switch") == "declenchement"
                and payload.get("trigger") == "incident_execution"
            ):
                found.append(Incident(str(entry.get("ts")), str(payload.get("reason") or "")))
    except (AuditError, OSError, ValueError) as exc:
        return Unavailable(f"journal d'audit illisible ({type(exc).__name__})")
    return found


def incidents(found: Sequence[Incident] | Unavailable, maximum: int) -> Criterion:
    source = (
        "journal d'audit vérifié : entrées KILL « declenchement » de déclencheur "
        "incident_execution (var/audit/journal.jsonl)"
    )
    shown = f"≤ {maximum}"
    if isinstance(found, Unavailable):
        return Criterion("Incidents d'exécution", found.reason, shown, "non_evaluable", source)
    details = tuple(f"{i.at} : {i.reason}" for i in found[:MAX_LISTED])
    if len(found) > MAX_LISTED:
        details += (f"… et {len(found) - MAX_LISTED} autre(s).",)
    status: Status = "atteint" if len(found) <= maximum else "non_atteint"
    return Criterion("Incidents d'exécution", str(len(found)), shown, status, source, details)


@dataclass(frozen=True)
class StrategyBacktest:
    """The backtest of the strategy that drove the paper account, over the paper's days."""

    strategy: str
    params: Mapping[str, ParamValue]
    costs: Costs
    result: engine.BacktestResult


@dataclass(frozen=True)
class Gap:
    strategy: str
    params: Mapping[str, ParamValue]
    first: date
    last: date
    sessions: int
    paper_return: float
    backtest_return: float
    paper_fills: int
    paper_fees_eur: Decimal
    paper_execution_gap_bps: Decimal | None
    unfilled: int  # orders ended without any fill: refused, rejected or cancelled
    backtest_trades: int
    backtest_fees_eur: float
    backtest_slippage_bps: float

    @property
    def points(self) -> float:
        return (self.paper_return - self.backtest_return) * 100


def paper_strategy(orders: Sequence[BookedOrder]) -> str | Unavailable:
    """The one strategy behind every booked order: only then has the account a backtest."""
    origins = sorted({(o.intent.origin.kind, o.intent.origin.id) for o in orders})
    if not origins:
        return Unavailable("aucun ordre au carnet : rien à comparer")
    if len(origins) > 1:
        listed = ", ".join(f"{kind} {name}" for kind, name in origins)
        return Unavailable(f"plusieurs origines au carnet ({listed}) : aucun backtest unique")
    kind, name = origins[0]
    if kind != "strategy":
        return Unavailable(f"ordres de {kind} {name} : aucun backtest de référence")
    return name


def paper_backtest_gap(
    valuations: Sequence[Valuation], orders: Sequence[BookedOrder], backtest: StrategyBacktest
) -> Gap | Unavailable:
    """The paper return against the backtest's over the sessions both valued, and what the
    two executions did differently: fills, fees, slippage, orders left unfilled."""
    paper = {v.day: v.equity_eur for v in valuations}
    curve = {stamp.date(): float(value) for stamp, value in backtest.result.values.items()}
    common = sorted(set(paper) & set(curve))
    if len(common) < 2:
        return Unavailable("moins de deux séances valorisées à la fois en paper et en backtest")
    fills = [fill for order in orders for fill in order.fills]
    currencies = sorted({fill.currency for fill in fills} - {"EUR"})
    if currencies:
        return Unavailable(f"exécutions en {', '.join(currencies)} : euros seulement (ADR-024)")
    first, last = common[0], common[-1]
    return Gap(
        strategy=backtest.strategy,
        params=backtest.params,
        first=first,
        last=last,
        sessions=len(common),
        paper_return=float(paper[last] / paper[first]) - 1,
        backtest_return=curve[last] / curve[first] - 1,
        paper_fills=len(fills),
        paper_fees_eur=sum((fill.fees for fill in fills), Decimal(0)),
        paper_execution_gap_bps=execution_gap_bps(orders),
        unfilled=sum(1 for o in orders if o.state in TERMINAL and o.filled == 0),
        backtest_trades=len(backtest.result.trades),
        backtest_fees_eur=backtest.result.fees,
        backtest_slippage_bps=backtest.costs.slippage * 10_000,
    )


def gap_criterion(gap: Gap | Unavailable) -> Criterion:
    """§8.3 asks the gap measured and explained, without a threshold: the criterion is reached
    once it is measured, and its detail is the explanation Lucas reads before signing."""
    name = "Écart paper/backtest"
    source = "`engine.run` (moteur maison, ADR-024) contre `LoopLog.valuations` et le carnet"
    shown = "mesuré et expliqué (§8.3) ; aucun seuil d'écart dans autonomy.yaml"
    if isinstance(gap, Unavailable):
        return Criterion(name, gap.reason, shown, "non_evaluable", source)
    paper_gap = gap.paper_execution_gap_bps
    execution = "aucune exécution" if paper_gap is None else f"{paper_gap} pb"
    details = (
        f"Stratégie {gap.strategy}, configuration approuvée aujourd'hui "
        f"{canonical_json(dict(gap.params))}, du {gap.first:%d/%m/%Y} au {gap.last:%d/%m/%Y} "
        f"({gap.sessions} séances valorisées des deux côtés).",
        f"Rendement paper : {gap.paper_return * 100:+.2f} % ; backtest, même capital de départ et "
        f"mêmes frais (risk.yaml › trading_costs) : {gap.backtest_return * 100:+.2f} %.",
        f"Exécutions : {gap.paper_fills} en paper, {gap.backtest_trades} en backtest ; frais : "
        f"{gap.paper_fees_eur} € contre {gap.backtest_fees_eur:.2f} €.",
        f"Écart d'exécution moyen paper : {execution} (mouvement depuis la clôture de "
        f"décision compris) ; glissement supposé par le backtest : "
        f"{gap.backtest_slippage_bps:.2f} pb.",
        f"Ordres paper terminés sans exécution (refusés, rejetés ou annulés) : {gap.unfilled}.",
        "Les deux exécutent à la clôture de la séance qui suit la décision ; le simulateur paper "
        "seulement si la clôture atteint le prix limite, et pour au plus la participation "
        "maximale au volume (config/execution.yaml) : le reste de l'écart tient à ces règles.",
    )
    return Criterion(name, f"{gap.points:+.2f} point(s)", shown, "atteint", source, details)


def evals_criterion(check: PromotionCheck | Unavailable, report: Path | None) -> Criterion:
    """The golden set, R1 to R5 and the red team of the domain, measured live: the rule
    ``N1_to_N2`` of autonomy.yaml, checked on the campaign's sealed report."""
    name = "Golden et red team du domaine"
    shown = f"toutes les conditions de la règle {EVALS_RULE} (autonomy.yaml), en réel"
    source = f"`check_promotion` sur {report.name if report else 'aucun rapport'}"
    if isinstance(check, Unavailable):
        return Criterion(name, check.reason, shown, "non_evaluable", source)
    details = tuple(
        f"{'✓' if c.passed else '✗'} {c.name} : {c.measured} (attendu : {c.expected})"
        for c in check.checks
    )
    passed = sum(1 for c in check.checks if c.passed)
    status: Status = "atteint" if check.passed else "non_atteint"
    value = f"{passed}/{len(check.checks)} condition(s)"
    return Criterion(name, value, shown, status, source, details)


def nightly_criterion() -> Criterion:
    return Criterion(
        "Éval nocturne",
        "aucune éval nocturne n'existe",
        "réussie, si elle existe (§8.3)",
        "sans_objet",
        "evals/ : aucune suite nocturne",
    )


@dataclass(frozen=True)
class Decisions:
    """Lucas's answers to N3 approval requests, in live: granted with his code, or refused."""

    granted: int
    refused: int

    @property
    def total(self) -> int:
        return self.granted + self.refused


def lucas_decisions(journal: AuditJournal) -> Decisions | Unavailable:
    """Every live approval Lucas decided, from the verified journal: ``ACCORDEE`` by ``lucas``
    (his code), ``REFUSEE`` from an interface or by ``lucas``. A refusal by the policy (wrong
    codes, a Risk Gate that no longer agrees) and an expiry are not his answer and do not count."""
    if not journal.path.exists():
        return Decisions(0, 0)
    chain = verify(journal.path)
    if not chain.ok:
        return Unavailable(
            f"journal d'audit invalide ({len(chain.errors)} erreur(s)) : `cerveau audit verify`"
        )
    granted = refused = 0
    try:
        for line in journal.path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if entry.get("event") != "APPROVAL" or not entry.get("payload_ref"):
                continue
            payload = journal.read_payload(entry["payload_ref"])
            if not isinstance(payload, Mapping) or payload.get("environment") != "live":
                continue
            actor, state = entry.get("actor"), payload.get("state")
            if state == "ACCORDEE" and actor == "lucas":
                granted += 1
            elif state == "REFUSEE" and actor in ("lucas", "interface"):
                refused += 1
    except (AuditError, OSError, ValueError) as exc:
        return Unavailable(f"journal d'audit illisible ({type(exc).__name__})")
    return Decisions(granted, refused)


_DECISIONS_SOURCE = (
    "journal d'audit vérifié : entrées APPROVAL en live, ACCORDEE par lucas ou REFUSEE depuis "
    "une interface (ADR-035)"
)


def approvals_count(found: Decisions | Unavailable, minimum: int | str) -> Criterion:
    name = "Approbations N3 décidées par Lucas"
    threshold = _threshold(minimum)
    shown = f"≥ {minimum}"
    if isinstance(found, Unavailable):
        return Criterion(name, found.reason, shown, "non_evaluable", _DECISIONS_SOURCE)
    details = () if threshold is not None else (_unknown("approvals_min", str(minimum)),)
    reached = threshold is not None and found.total >= threshold
    return Criterion(
        name, str(found.total), shown, _status(reached, threshold), _DECISIONS_SOURCE, details
    )


def agreement_rate(found: Decisions | Unavailable, minimum: float | str) -> Criterion:
    """The share of CERVEAU's N3 proposals Lucas granted: his agreement with CERVEAU."""
    name = "Taux d'accord Lucas / CERVEAU"
    threshold = _threshold(minimum)
    shown = f"≥ {minimum}"
    if isinstance(found, Unavailable):
        return Criterion(name, found.reason, shown, "non_evaluable", _DECISIONS_SOURCE)
    if found.total == 0:
        return Criterion(
            name,
            "aucune décision",
            shown,
            "non_evaluable",
            _DECISIONS_SOURCE,
            ("Taux non calculable sans approbation décidée.",),
        )
    rate = found.granted / found.total
    details = (f"{found.granted} accordée(s), {found.refused} refusée(s).",)
    if threshold is None:
        details += (_unknown("agreement_rate_min", str(minimum)),)
    reached = threshold is not None and rate >= threshold
    return Criterion(
        name, f"{rate:.4f}", shown, _status(reached, threshold), _DECISIONS_SOURCE, details
    )


def live_drawdown_criterion() -> Criterion:
    """Same risk conditions as N2 → N3 (§8.3): the live drawdown is not measured yet (B350), so
    the promotion stays impossible (R7)."""
    return Criterion(
        "Drawdown live",
        "non mesuré : aucune valorisation du compte live n'est enregistrée",
        "≤ max_paper_drawdown_pct (règle N2_to_N3), sur le compte live",
        "non_evaluable",
        "aucun outil : B350",
    )


def demotions_criterion(root: Path, domain: str) -> Criterion:
    """No demotion of the domain may stand: a demotion trigger fired against N4 (ADR-067)."""
    name = "Rétrogradations en vigueur"
    source = f"{DEMOTIONS.as_posix()} (ADR-067)"
    found = read_demotions(root)
    if isinstance(found, str):
        return Criterion(name, found, "aucune", "non_evaluable", source)
    mine = [d for d in found if d.domain == domain]
    details = tuple(
        f"{d.at} : {d.from_level} → {d.to_level} ({d.trigger}) : {d.reason}"
        for d in mine[:MAX_LISTED]
    )
    status: Status = "non_atteint" if mine else "atteint"
    return Criterion(name, str(len(mine)), "aucune", status, source, details)


# Gathering, read only --------------------------------------------------------------------------


def _loop(root: Path) -> tuple[list[date], list[Valuation]] | Unavailable:
    path = default_loop_path(root)
    if not path.is_file():
        return [], []
    try:
        with LoopLog.open(path, read_only=True) as log:
            return log.days(), log.valuations()
    except (sqlite3.Error, SchemaError, ValueError) as exc:
        return Unavailable(f"boucle paper illisible ({type(exc).__name__})")


def _orders(root: Path) -> list[BookedOrder] | Unavailable:
    path = default_book_path(root)
    if not path.is_file():
        return []
    try:
        with OrderBook.open(path, read_only=True) as book:
            return book.orders()
    except (sqlite3.Error, SchemaError, OrderBookError, ValueError) as exc:
        return Unavailable(f"carnet d'ordres illisible ({type(exc).__name__})")


def strategy_backtest(
    root: Path,
    config: Config,
    strategy: str,
    *,
    start: date,
    end: date,
    initial_cash: float,
    at: datetime,
) -> StrategyBacktest | Unavailable:
    """The strategy's backtest from the paper's first day, with its approved configuration, the
    costs of risk.yaml and the history as known at ``at``."""
    try:
        costs = Costs.from_config(config.risk.trading_costs, "risk.yaml › trading_costs")
    except CostsError as exc:
        return Unavailable(str(exc))
    cutoff = config.research.execution.decision_cutoff_utc
    try:
        with FinanceStore.open(default_store_path(root), read_only=True) as store:
            sources, refused = strategy_sources(root, store, cutoff)
            found = [source for source in sources if source.spec.id == strategy]
            if not found:
                why = "; ".join(refused) or "absente du registre ou plus candidate"
                return Unavailable(f"stratégie {strategy} sans configuration approuvée : {why}")
            source = found[0]
            history = MarketHistory.load(store, source.spec.univers).known_by(at, end)
            result = engine.run(
                source.strategy,
                source.params,
                history,
                start=start,
                end=end,
                cutoff=cutoff,
                costs=costs,
                initial_cash=initial_cash,
            )
    except (FinanceStoreError, sqlite3.Error, SchemaError) as exc:
        return Unavailable(f"base finance illisible : {exc}")
    except (ValueError, LookAheadError) as exc:  # BacktestError and StrategyError included
        return Unavailable(f"backtest de {strategy} impossible : {exc}")
    return StrategyBacktest(strategy, source.params, costs, result)


def _gap(
    root: Path,
    config: Config,
    loop: tuple[list[date], list[Valuation]] | Unavailable,
    orders: list[BookedOrder] | Unavailable,
    at: datetime,
) -> Gap | Unavailable:
    if isinstance(loop, Unavailable):
        return loop
    if isinstance(orders, Unavailable):
        return orders
    valuations = loop[1]
    if len(valuations) < 2:
        return Unavailable("moins de deux valorisations paper")
    strategy = paper_strategy(orders)
    if isinstance(strategy, Unavailable):
        return strategy
    start = valuations[0]
    if start.positions:
        return Unavailable("positions détenues dès la première valorisation : départs différents")
    backtest = strategy_backtest(
        root,
        config,
        strategy,
        start=start.day,
        end=valuations[-1].day,
        initial_cash=float(start.equity_eur),
        at=at,
    )
    if isinstance(backtest, Unavailable):
        return backtest
    return paper_backtest_gap(valuations, orders, backtest)


def _evals(
    root: Path, config: Config, report: Path | None, journal: AuditJournal, at: datetime
) -> PromotionCheck | Unavailable:
    if report is None:
        return Unavailable("aucun rapport d'évals réel fourni (--evals)")
    try:
        return check_promotion(
            load_report(report),
            config,
            domain="finance",
            level="N2",  # the rule N1_to_N2: golden, R1 to R5, red team
            journal=journal,
            now=at,
            root=root,
        )
    except BlockedFeatureError as exc:
        return Unavailable(f"règle {EVALS_RULE} bloquée : {exc}")
    except (PromotionError, OSError, UnicodeDecodeError) as exc:
        return Unavailable(f"rapport d'évals illisible : {exc}")


def build_report(
    root: Path,
    config: Config,
    *,
    domain: str,
    level: str,
    at: datetime,
    evals: Path | None = None,
) -> PromotionReport:
    """Every criterion of the promotion, read from the project's files without changing any."""
    key = REPORTED.get((domain, level))
    if key is None:
        raise PromotionReportError(
            f"aucun rapport de promotion pour {domain} {level} : finance N3 ou N4 seulement "
            "(ADR-040, ADR-067)"
        )
    rule = getattr(config.autonomy.promotion.finance, key)
    journal = AuditJournal(default_journal_path(root))
    if key == "N3_to_N4":
        decisions = lucas_decisions(journal)
        n2_n3 = config.autonomy.promotion.finance.N2_to_N3
        criteria: tuple[Criterion, ...] = (
            current_level(effective_level(config.autonomy, root, domain), required="N3"),
            approvals_count(decisions, rule.approvals_min),
            agreement_rate(decisions, rule.agreement_rate_min),
            incidents(execution_incidents(journal), n2_n3.execution_incidents_max),
            live_drawdown_criterion(),
            demotions_criterion(root, domain),
            evals_criterion(_evals(root, config, evals, journal, at), evals),
        )
        return PromotionReport(domain, "N4", at, config.digest, criteria)
    loop = _loop(root)
    orders = _orders(root)
    criteria = (
        current_level(effective_level(config.autonomy, root, domain), required="N2"),
        paper_weeks(loop if isinstance(loop, Unavailable) else loop[0], rule.paper_weeks_min),
        paper_decisions(orders, rule.decisions_min),
        paper_drawdown(
            loop if isinstance(loop, Unavailable) else loop[1], rule.max_paper_drawdown_pct
        ),
        incidents(execution_incidents(journal), rule.execution_incidents_max),
        gap_criterion(_gap(root, config, loop, orders, at)),
        evals_criterion(_evals(root, config, evals, journal, at), evals),
        nightly_criterion(),
    )
    return PromotionReport(domain, "N3", at, config.digest, criteria)


# Rendering and writing ---------------------------------------------------------------------------


def previous_level(level: Level) -> Level:
    return LEVELS[max(LEVELS.index(level) - 1, 0)]


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def render(report: PromotionReport) -> str:
    """The report in Markdown, opening with the header ``signatures.py`` reads."""
    verdict = report.verdict
    at = report.generated_at
    lines = [
        "---",
        f"rapport: {REPORT_KIND}",
        f"domain: {report.domain}",
        f"level: {report.level}",
        f"statut: {verdict}",
        f'genere_le: "{at.isoformat(timespec="seconds")}"',
        f'config: "{report.config_digest}"',
        "---",
        f"# Rapport de promotion {report.domain} {previous_level(report.level)} → {report.level}",
        "",
        f"Généré le {at:%d/%m/%Y à %H:%M} ({at:%z}) par "
        f"`cerveau promotion report {report.domain} --to {report.level}` (ADR-040), sous la "
        f"configuration `{report.config_digest}`. Chaque valeur vient de l'outil cité (R1) ; "
        "aucun modèle n'en produit.",
        "",
        f"**Conclusion : {VERDICT_TEXT[verdict]}.**",
        "",
        "| Critère | Valeur | Seuil | Statut | Source |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {_cell(c.name)} | {_cell(c.value)} | {_cell(c.threshold)} | "
        f"{STATUS_TEXT[c.status]} | {_cell(c.source)} |"
        for c in report.criteria
    ]
    lines += ["", "## Détail", ""]
    for criterion in report.criteria:
        if criterion.details:
            lines += [f"### {criterion.name}", ""]
            lines += [f"- {_cell(detail)}" for detail in criterion.details]
            lines.append("")
    lines += ["## Signature", ""]
    if verdict == REPORT_PASSED:
        lines += [
            "Ce rapport ne signe rien. La commande affiche le texte de signature, qui cite "
            "l'empreinte SHA-256 de ce fichier : tu le copies toi-même dans "
            f"`governance/approvals/AAAA-MM-JJ-{report.domain}-{report.level}.md`. La signature "
            "ne compte que tant que ce fichier reste inchangé sous `var/promotion/` (ADR-036).",
            "",
            f"Le niveau écrit (`domains.{report.domain}.level` dans `config/autonomy.yaml`) se "
            "change aussi à la main ; le passage en live est une décision séparée "
            "(`config/live.yaml`, procédure live).",
        ]
    else:
        lines.append(
            "Aucun texte de signature : une signature citant ce rapport ne compterait pas "
            "(ADR-036), tant qu'un critère n'est pas atteint."
        )
    return "\n".join(lines) + "\n"


def write_report(root: Path, report: PromotionReport) -> Path:
    """Write the report under ``var/promotion/``, never over an earlier one: a signature may
    cite it. The bytes are written as rendered, so that their SHA-256 is the one shown."""
    folder = root / PROMOTION_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{report.domain}-{report.level}-{report.generated_at.date().isoformat()}"
    data = render(report).encode("utf-8")
    for rank in range(1, 1000):
        path = folder / (f"{stem}.md" if rank == 1 else f"{stem}-{rank}.md")
        try:
            with path.open("xb") as handle:
                handle.write(data)
        except FileExistsError:
            continue
        return path
    raise PromotionReportError(f"trop de rapports du même jour sous {PROMOTION_DIR.as_posix()}")
