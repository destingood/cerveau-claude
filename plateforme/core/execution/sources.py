"""The intent sources of the paper loop (ADR-029, D7).

A ``candidate`` strategy replays each day the very code of its backtest (§10.6), with the
configuration its approved protocol report retained: the paper/backtest gap then measures the
market, not a change of rule. Its targets are the backtest's ``target_orders`` on the paper
account, at the last closes of the Gate's snapshot. Nothing here sends an order: a proposal goes
through the drafter, the policy and the Risk Gate like any other.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path

from core.audit.chain import default_journal_path
from core.execution.drafter import (
    DraftError,
    strategy_orders,
    strategy_origin,
    strategy_rationale,
)
from core.execution.intent import SizingSource
from core.execution.loop import Proposal
from core.finance.model import ParamValue, canonical_json
from core.finance.research.execution import target_orders
from core.finance.research.registry import (
    APPROVALS_DIR,
    REGISTRY_DIR,
    LocalEvidence,
    RegistryError,
    StrategySpec,
    audited_reports,
    expanded_grid,
    load_approval,
    load_registry,
    load_strategy,
    promotion_errors,
    report_sha256,
)
from core.finance.research.report import default_reports_dir
from core.finance.research.strategy import Strategy, checked_weights
from core.finance.research.view import LookAheadError, MarketHistory
from core.finance.store import FinanceStore
from core.risk_gate.snapshot import GateSnapshot

CHOSEN_ROW = "Configuration retenue (meilleur Sharpe de développement)"


class SourceError(Exception):
    """A strategy cannot propose intents; the reason says why."""


def approved_report(spec: StrategySpec, root: Path) -> Path:
    """The protocol report the user's approval cites, found by its print in ``var/``."""
    try:
        approval = load_approval(spec, root / APPROVALS_DIR)
    except RegistryError as exc:
        raise SourceError(str(exc)) from exc
    if approval is None:
        raise SourceError(f"{spec.id} : aucune approbation de l'utilisateur (ADR-027)")
    for path in sorted(default_reports_dir(root).glob(f"{spec.id}-*.json")):
        if report_sha256(path) == approval.rapport_sha256:
            return path
    raise SourceError(
        f"{spec.id} : rapport approuvé introuvable (empreinte {approval.rapport_sha256[:12]}…)"
    )


def chosen_params(spec: StrategySpec, report: Path) -> dict[str, ParamValue]:
    """The configuration the protocol retained, read from ``report``; it must be a point of the
    card's grid, or the paper would run a rule the protocol never tested (B179)."""
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
        values = [
            row["valeur"]
            for section in data["sections"]
            for row in section["lignes"]
            if row["mesure"] == CHOSEN_ROW
        ]
        params = json.loads(values[0]) if len(values) == 1 else None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SourceError(f"{spec.id} : rapport {report.name} illisible : {exc}") from exc
    if not isinstance(params, dict):
        raise SourceError(f"{spec.id} : aucune configuration retenue dans {report.name}")
    grid = {canonical_json(point) for point in expanded_grid(spec)}
    if canonical_json(params) not in grid:
        raise SourceError(f"{spec.id} : configuration retenue {params} hors de la grille")
    return params


@dataclass(frozen=True)
class StrategySource:
    """A ``candidate`` strategy as a source of intents: its targets at the day's decision."""

    spec: StrategySpec
    strategy: Strategy
    params: dict[str, ParamValue]
    store: FinanceStore
    cutoff: time

    @property
    def tool(self) -> str:
        return f"strategy.{self.spec.id}"

    def symbols(self) -> frozenset[str]:
        return frozenset(self.spec.univers)

    def propose(
        self, snapshot: GateSnapshot, *, day: date, sizing: SizingSource
    ) -> Proposal | None:
        """The orders toward the strategy's weights on the paper account's value. Holdings
        outside its universe are left alone; an instrument without a last close stops it."""
        rationale = strategy_rationale(self.spec, signal_date=day)
        universe = self.spec.univers
        try:
            view = MarketHistory.load(self.store, universe).view(day, self.cutoff)
            weights = checked_weights(self.strategy.decide(view, self.params), universe, day)
        except (ValueError, LookAheadError) as exc:  # StrategyError is a ValueError
            raise DraftError(f"{self.spec.id} : {exc}") from exc
        positions = {s: q for s, q in snapshot.holdings.items() if s in universe}
        missing = sorted((set(weights) | set(positions)) - set(snapshot.quotes))
        if missing:
            raise DraftError(f"{self.spec.id} : aucun dernier cours pour {', '.join(missing)}")
        prices = {s: float(q.price) for s, q in snapshot.quotes.items()}
        value = float(snapshot.account.equity_eur)
        orders = target_orders(weights, positions, prices, value)
        if not orders:
            return None
        return Proposal(strategy_orders(orders, sizing), rationale, strategy_origin(self.spec))


def strategy_sources(
    root: Path, store: FinanceStore, cutoff: time
) -> tuple[list[StrategySource], list[str]]:
    """Every ``candidate`` of the registry that passes its promotion checks again, and why the
    others propose nothing today."""
    sources: list[StrategySource] = []
    refused: list[str] = []
    try:
        specs = load_registry(root / REGISTRY_DIR)
    except RegistryError as exc:
        return [], [f"registre des stratégies illisible : {exc}"]
    if not any(spec.statut == "candidate" for spec in specs.values()):
        return [], []
    try:
        audited = audited_reports(default_journal_path(root))
    except RegistryError as exc:  # its message already says the journal is unreadable
        return [], [f"aucune stratégie : {exc}"]
    local = LocalEvidence(default_reports_dir(root), audited)
    for spec in sorted(specs.values(), key=lambda s: s.id):
        if spec.statut != "candidate":
            continue
        try:
            errors = promotion_errors(spec, root=root, approvals=root / APPROVALS_DIR, local=local)
            if errors:
                raise SourceError("; ".join(errors))
            params = chosen_params(spec, approved_report(spec, root))
            sources.append(StrategySource(spec, load_strategy(spec), params, store, cutoff))
        except (SourceError, RegistryError) as exc:
            refused.append(f"{spec.id} : aucune intention : {exc}")
    return sources, refused
