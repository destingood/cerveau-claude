"""The paper loop's strategy sources (ADR-029, D7): a candidate replays its approved rule."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.audit import AuditJournal, default_journal_path
from core.execution.book import OrderBook, Recorder
from core.execution.broker import AccountStatement
from core.execution.drafter import DraftError
from core.execution.intent import SizingSource
from core.execution.market import gate_snapshot, market_facts
from core.execution.sources import (
    CHOSEN_ROW,
    SourceError,
    StrategySource,
    approved_report,
    chosen_params,
    strategy_sources,
)
from core.finance.model import canonical_json
from core.finance.research.registry import (
    APPROVALS_DIR,
    PROTOCOL_COMMAND,
    REGISTRY_DIR,
    StrategySpec,
    approval_text,
    code_sha256,
    grid_sha256,
    load_spec,
    report_sha256,
)
from core.finance.research.report import default_reports_dir
from core.finance.store import FinanceStore
from core.risk_gate.snapshot import GateSnapshot
from tests.execution_cases import MemoryJournal
from tests.test_execution_loop import (
    BASE,
    MONDAY,
    SYMBOL,
    TUESDAY,
    ingest,
    market,
    run_at,
)
from tests.test_execution_market import ACCOUNT

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / REGISTRY_DIR / "croisement_mm.yaml"
CUTOFF = BASE.research.execution.decision_cutoff_utc
SIZING = SizingSource(tool="strategy.croisement_mm", call_id="strategy.croisement_mm#1")
CHOSEN = {"long": 50, "short": 5}


def card(**changes: Any) -> dict[str, Any]:
    """The demonstration card as a candidate on the test instrument, as the user would set it."""
    raw = yaml.safe_load(DEMO.read_text(encoding="utf-8"))
    return {
        **raw,
        "statut": "candidate",
        "donnees": "reelles",
        "univers": [SYMBOL],
        "invalidation": "La règle perd sur 60 séances glissantes.",
        "horizon_jours": 60,
        **changes,
    }


def sections(chosen: object = CHOSEN) -> list[dict[str, Any]]:
    value = canonical_json(chosen) if isinstance(chosen, dict) else chosen
    return [{"titre": "Protocole", "lignes": [{"mesure": CHOSEN_ROW, "valeur": value}]}]


def promoted(root: Path, *, audited: bool = True, **report: Any) -> StrategySpec:
    """A candidate in ``root``: its card, its code, its report, the user's approval and journal."""
    registry = root / REGISTRY_DIR
    registry.mkdir(parents=True)
    path = registry / "croisement_mm.yaml"
    path.write_text(yaml.safe_dump(card(), allow_unicode=True), encoding="utf-8")
    spec = load_spec(path)
    (root / spec.module).parent.mkdir(parents=True)
    shutil.copyfile(REPO / spec.module, root / spec.module)
    code, grid = code_sha256(spec, root), grid_sha256(spec)
    body = {
        "strategie": spec.id,
        "verdict": "reussi",
        "donnees": "reelles",
        "frais": "reels",
        "code_sha256": code,
        "grille_sha256": grid,
        "sections": sections(),
        **report,
    }
    reports = default_reports_dir(root)
    reports.mkdir(parents=True)
    written = reports / "croisement_mm-2026-10-20.json"
    written.write_text(json.dumps(body), encoding="utf-8")
    sha = report_sha256(written)
    approvals = root / APPROVALS_DIR
    approvals.mkdir(parents=True)
    text = approval_text(spec, report_sha256=sha, code=code, grid=grid, day=MONDAY)
    (approvals / "croisement_mm.yaml").write_text(text, encoding="utf-8")
    if audited:
        AuditJournal(default_journal_path(root)).append(
            actor="owner",
            event="DECISION",
            payload={"command": PROTOCOL_COMMAND, "rapport_sha256": sha},
        )
    return spec


@pytest.fixture
def store() -> Iterator[FinanceStore]:
    built = market()
    yield built
    built.close()


def snapshot(store: FinanceStore, positions: dict[str, int] | None = None) -> GateSnapshot:
    facts = market_facts(store, [SYMBOL], as_of=run_at(TUESDAY), volume_sessions=20)
    book = OrderBook.memory(Recorder(MemoryJournal(), "policy", "sources-test"))
    statement = AccountStatement(cash_eur=Decimal("10000"), positions=positions or {})
    return gate_snapshot(facts, account=ACCOUNT, statement=statement, book=book, open_gaps=0)


def only_source(root: Path, store: FinanceStore) -> StrategySource:
    sources, refused = strategy_sources(root, store, CUTOFF)
    assert refused == []
    [source] = sources
    return source


def test_a_candidate_buys_toward_its_weights(tmp_path: Path, store: FinanceStore) -> None:
    promoted(tmp_path)
    research = {  # beside it, a research card proposes nothing
        **yaml.safe_load(DEMO.read_text(encoding="utf-8")),
        "id": "autre_mm",
        "module": "core/finance/research/strategies/autre_mm.py",
    }
    text = yaml.safe_dump(research, allow_unicode=True)
    (tmp_path / REGISTRY_DIR / "autre_mm.yaml").write_text(text, encoding="utf-8")
    source = only_source(tmp_path, store)
    assert (source.tool, source.symbols(), source.params) == (
        "strategy.croisement_mm",
        frozenset({SYMBOL}),
        CHOSEN,
    )
    ingest(store, TUESDAY, 110.0)  # the short mean now tops the long one
    proposal = source.propose(snapshot(store), day=TUESDAY, sizing=SIZING)
    assert proposal is not None
    [order] = proposal.orders
    assert (order.symbol, order.quantity, order.sizing) == (SYMBOL, 90, SIZING)  # 10 000 / 110
    assert (proposal.origin.kind, proposal.origin.id) == ("strategy", "croisement_mm")
    assert proposal.rationale.horizon_days == 60


def test_a_flat_market_proposes_nothing(tmp_path: Path, store: FinanceStore) -> None:
    promoted(tmp_path)
    ingest(store, TUESDAY, 100.0)
    assert only_source(tmp_path, store).propose(snapshot(store), day=TUESDAY, sizing=SIZING) is None


def test_holdings_outside_the_universe_are_left_alone(tmp_path: Path, store: FinanceStore) -> None:
    promoted(tmp_path)
    ingest(store, TUESDAY, 100.0)
    held = snapshot(store, {"FICT-AUTRE": 3})
    assert only_source(tmp_path, store).propose(held, day=TUESDAY, sizing=SIZING) is None


def test_a_strategy_that_cannot_decide_drafts_nothing(tmp_path: Path, store: FinanceStore) -> None:
    promoted(tmp_path)
    source = only_source(tmp_path, store)
    empty = FinanceStore.memory()
    with pytest.raises(DraftError, match="aucun cours dans la base"):
        StrategySource(source.spec, source.strategy, CHOSEN, empty, CUTOFF).propose(
            snapshot(store), day=TUESDAY, sizing=SIZING
        )
    empty.close()
    ingest(store, TUESDAY, 110.0)
    unpriced = snapshot(store).model_copy(update={"quotes": {}})
    with pytest.raises(DraftError, match=f"aucun dernier cours pour {SYMBOL}"):
        source.propose(unpriced, day=TUESDAY, sizing=SIZING)


def test_research_strategies_propose_nothing(store: FinanceStore) -> None:
    assert strategy_sources(REPO, store, CUTOFF) == ([], [])


def test_a_candidate_failing_its_checks_is_refused(tmp_path: Path, store: FinanceStore) -> None:
    promoted(tmp_path, audited=False)
    sources, [why] = strategy_sources(tmp_path, store, CUTOFF)
    assert sources == []
    assert why.startswith("croisement_mm : aucune intention : ")
    assert "absente du journal d'audit" in why


def test_an_unreadable_registry_or_journal_refuses_all(tmp_path: Path, store: FinanceStore) -> None:
    promoted(tmp_path)
    with default_journal_path(tmp_path).open("a", encoding="utf-8") as handle:
        handle.write("{\n")
    sources, [why] = strategy_sources(tmp_path, store, CUTOFF)
    assert sources == [] and "journal d'audit illisible" in why
    (tmp_path / REGISTRY_DIR / "croisement_mm.yaml").write_text("id: [", encoding="utf-8")
    assert strategy_sources(tmp_path, store, CUTOFF)[1][0].startswith(
        "registre des stratégies illisible"
    )


def test_the_approved_report_is_found_by_its_print(tmp_path: Path) -> None:
    spec = promoted(tmp_path)
    found = approved_report(spec, tmp_path)
    assert found.name == "croisement_mm-2026-10-20.json"
    found.write_text("{}", encoding="utf-8")
    with pytest.raises(SourceError, match="rapport approuvé introuvable"):
        approved_report(spec, tmp_path)
    approval = tmp_path / APPROVALS_DIR / "croisement_mm.yaml"
    approval.write_text("strategie: [", encoding="utf-8")
    with pytest.raises(SourceError):
        approved_report(spec, tmp_path)
    approval.unlink()
    with pytest.raises(SourceError, match="aucune approbation de l'utilisateur"):
        approved_report(spec, tmp_path)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"long": 50, "short": 7}, "hors de la grille"),  # never tested by the protocol (B179)
        ("[5, 50]", "aucune configuration retenue"),
        ("{", "illisible"),
    ],
)
def test_the_chosen_configuration_must_be_a_point_of_the_grid(
    tmp_path: Path, value: object, message: str
) -> None:
    spec = promoted(tmp_path)
    report = tmp_path / "rapport.json"
    report.write_text(json.dumps({"sections": sections(value)}), encoding="utf-8")
    with pytest.raises(SourceError, match=message):
        chosen_params(spec, report)
    report.write_text(json.dumps({"sections": []}), encoding="utf-8")
    with pytest.raises(SourceError, match="aucune configuration retenue"):
        chosen_params(spec, report)
