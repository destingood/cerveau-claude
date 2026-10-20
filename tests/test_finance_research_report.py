"""The standard strategy report (ADR-027): nine sections, every number a traced figure (R1)."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.config.loader import ResearchConfig, load_config
from core.finance.fixtures import load_research, research_costs, research_crises
from core.finance.research.execution import Costs
from core.finance.research.protocol import (
    INVARIANCE_DAYS,
    Benchmark,
    Gate,
    ProtocolResult,
    run_protocol,
)
from core.finance.research.registry import (
    StrategySpec,
    expanded_grid,
    grid_sha256,
    load_strategy,
    report_sha256,
)
from core.finance.research.report import (
    FICTITIOUS_COSTS,
    NOTICE,
    SYNTHETIC,
    TOOLS,
    ReportError,
    Row,
    StrategyReport,
    build_report,
    report_json,
    report_markdown,
    write_report,
)
from core.finance.research.view import MarketHistory
from core.finance.store import FinanceStore
from core.verification.figures import Figure, figures_in, plain

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "domain_packs" / "finance" / "strategies" / "croisement_mm.yaml"
GENERATED = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def spec_with(**changes: Any) -> StrategySpec:
    raw = yaml.safe_load(DEMO.read_text(encoding="utf-8"))
    return StrategySpec.model_validate({**raw, **changes})


@dataclasses.dataclass(frozen=True)
class Run:
    spec: StrategySpec
    result: ProtocolResult
    history: MarketHistory
    costs: Costs
    config: ResearchConfig
    store: FinanceStore

    def report(self, **changes: Any) -> StrategyReport:
        arguments: dict[str, Any] = {
            "history": self.history,
            "costs": self.costs,
            "costs_kind": "fictifs",
            "initial_cash": 100_000.0,
            "config": self.config,
            "crises": research_crises(),
            "trials": self.store.trials(self.spec.id),
            "grid_sha256": grid_sha256(self.spec),
            "generated_at": GENERATED,
        }
        spec = changes.pop("spec", self.spec)
        result = changes.pop("result", self.result)
        return build_report(spec, result, **{**arguments, **changes})


@pytest.fixture(scope="module")
def run() -> Iterator[Run]:
    """The demo strategy on the planted trend alone, over a grid of four: a quick protocol."""
    spec = spec_with(univers=["FICT-RTEND"], grille={"short": [10, 20], "long": [50, 100]})
    config = load_config(REPO / "config").research
    named = research_costs()
    costs = Costs.from_config(named.costs, named.name)
    store = FinanceStore.memory()
    load_research(store)
    history = MarketHistory.load(store, spec.univers)
    result = run_protocol(
        load_strategy(spec),
        strategy_id=spec.id,
        grid=expanded_grid(spec),
        history=history,
        start=spec.periode.debut,
        end=spec.periode.fin,
        config=config,
        costs=costs,
        initial_cash=100_000.0,
        sessions_per_year=252,
        crises=research_crises(),
        benchmark=Benchmark("achat-conservation (test)", history),
        store=store,
        recorded_at=GENERATED,
    )
    yield Run(spec, result, history, costs, config, store)
    store.close()


def rows(report: StrategyReport) -> list[Row]:
    return [row for section in report.sections for row in section.lignes]


def test_the_protocol_keeps_its_invariance_days(run: Run) -> None:
    days = run.result.invariance_days
    assert len(days) == INVARIANCE_DAYS and list(days) == sorted(set(days))
    assert (
        run.result.partition.development[0] <= days[0] and days[-1] < run.result.partition.final[1]
    )


def test_the_report_has_nine_sections_and_no_loose_number(run: Run) -> None:
    report = run.report()
    assert [s.titre.split(".")[0] for s in report.sections] == [str(k) for k in range(1, 10)]
    figures, loose = figures_in(report.model_dump(mode="json"))
    assert loose == []
    assert len(figures) > 80
    assert report.verdict == run.result.verdict and report.strategie == "croisement_mm"
    assert [g.cle for g in report.portes] == [g.key for g in run.result.gates]


def test_every_figure_names_its_tool_and_keeps_one_value(run: Run) -> None:
    report = run.report()
    seen: dict[str, Figure] = {}
    for row in rows(report):
        assert row.outil in TOOLS
        if isinstance(row.valeur, Figure):
            assert row.valeur.id.split("/")[0] == row.outil
            assert seen.setdefault(row.valeur.id, row.valeur) == row.valeur
    # §8 cites the figures the earlier sections computed, under the same ids.
    verdict = report.sections[7]
    cited = [r.valeur.id for r in verdict.lignes if isinstance(r.valeur, Figure)]
    assert {"dsr/valeur", "pbo/valeur", "moteur/final/sharpe"} <= set(cited)
    earlier = {
        r.valeur.id for s in report.sections[:7] for r in s.lignes if isinstance(r.valeur, Figure)
    }
    assert set(cited) <= earlier


def test_the_measures_are_those_of_the_protocol(run: Run) -> None:
    evaluation = run.result.evaluation
    assert evaluation is not None and evaluation.dsr is not None
    found = {
        r.valeur.id: r.valeur.value for r in rows(run.report()) if isinstance(r.valeur, Figure)
    }
    assert found["dsr/essais"] == evaluation.dsr.trials == len(run.store.trials("croisement_mm"))
    assert found["moteur/final/rendements"] == evaluation.final.sessions
    assert found["pbo/combinaisons"] == evaluation.pbo.combinations
    assert found["protocole/invariance/configurations"] == 4
    assert found["registre/configurations"] == 4
    assert found["journal/essais/protocole-final"] == 1
    assert found["protocole/partition/final/rendements"] == run.result.partition.final_sessions - 1


def test_a_figure_with_a_tool_that_did_not_compute_it_is_refused() -> None:
    with pytest.raises(ValueError, match="n'est pas calculé par"):
        Row(mesure="x", valeur=plain("dsr/valeur", 1.0, "score"), outil="pbo")
    with pytest.raises(ValueError, match="outil inconnu"):
        Row(mesure="x", valeur="texte", outil="llm")


def test_the_synthetic_demo_carries_its_warnings(run: Run) -> None:
    report = run.report()
    assert report.avertissements == [SYNTHETIC, FICTITIOUS_COSTS]
    text = report_markdown(report)
    assert text.count("> **Avertissement**") == 2 and NOTICE in text
    assert [line for line in text.splitlines() if line.startswith("## ")][:9] == [
        f"## {s.titre}" for s in report.sections
    ]
    for row in rows(report):
        if isinstance(row.valeur, Figure):
            assert f"| {row.valeur.display} | `{row.valeur.id}` |" in text
    real = run.report(spec=spec_with(univers=["FICT-RTEND"], donnees="reelles"), costs_kind="reels")
    assert real.avertissements == []
    assert SYNTHETIC not in report_markdown(real)


def test_a_protocol_stopped_before_any_measure_says_why(run: Run) -> None:
    stopped = dataclasses.replace(
        run.result,
        verdict="echoue",
        gates=(Gate("contrat", "Contrat de la stratégie", "echouee", "levier 1.5"),),
        evaluation=None,
    )
    report = run.report(result=stopped)
    for section in report.sections[4:7]:
        [only] = section.lignes
        assert only.valeur == "non évalué : Contrat de la stratégie : levier 1.5"
    assert figures_in(report.model_dump(mode="json"))[1] == []


def test_a_report_refuses_another_strategy_or_universe(run: Run) -> None:
    other = dataclasses.replace(run.result, strategy_id="autre")
    with pytest.raises(ReportError, match="protocole de autre"):
        run.report(result=other)
    with pytest.raises(ReportError, match="univers"):
        run.report(spec=spec_with())


def test_the_json_round_trips_and_its_print_is_the_file_print(run: Run, tmp_path: Path) -> None:
    report = run.report()
    body = report_json(report)
    assert StrategyReport.model_validate_json(body) == report
    stamp = json.loads(body)
    assert {"strategie", "verdict", "donnees", "frais", "code_sha256", "grille_sha256"} <= set(
        stamp
    )
    first = write_report(report, tmp_path)
    assert first.json.name == "croisement_mm-2026-10-20.json"
    assert first.sha256 == report_sha256(first.json)
    assert first.markdown.read_text(encoding="utf-8") == report_markdown(report)
    second = write_report(report, tmp_path)
    assert second.json.name == "croisement_mm-2026-10-20-2.json"
    assert second.sha256 == first.sha256
    assert first.json.read_bytes() == body.encode("utf-8")
