"""The strategy registry (ADR-027): its entries, their fingerprints and the manual promotion."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.audit import AuditJournal
from core.finance.research.registry import (
    MAX_CONFIGURATIONS,
    PROTOCOL_COMMAND,
    LocalEvidence,
    RegistryError,
    StrategyApproval,
    StrategySpec,
    approval_text,
    audited_reports,
    code_sha256,
    expanded_grid,
    grid_sha256,
    load_registry,
    load_spec,
    load_strategy,
    promotion_errors,
    report_sha256,
)
from core.finance.research.trials import strategy_code_sha256

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "domain_packs" / "finance" / "strategies"
DEMO = REGISTRY / "croisement_mm.yaml"


def demo() -> dict[str, Any]:
    raw = yaml.safe_load(DEMO.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def spec_with(**changes: Any) -> StrategySpec:
    return StrategySpec.model_validate({**demo(), **changes})


def test_the_demo_entry_is_a_research_strategy_of_nine_configurations() -> None:
    registry = load_registry(REGISTRY)
    assert list(registry) == ["croisement_mm"]
    spec = registry["croisement_mm"]
    assert (spec.statut, spec.donnees, spec.frequence) == (
        "recherche",
        "synthetiques",
        "quotidienne",
    )
    assert len(expanded_grid(spec)) == 9
    assert promotion_errors(spec, root=REPO) == []


def test_the_code_print_is_the_one_the_trial_journal_records() -> None:
    spec = load_spec(DEMO)
    assert code_sha256(spec, REPO) == strategy_code_sha256(load_strategy(spec))


def test_the_grid_expands_in_declared_order_within_its_constraints() -> None:
    spec = spec_with(grille={"short": [5, 60], "long": [50, 100]})
    assert expanded_grid(spec) == [
        {"short": 5, "long": 50},
        {"short": 5, "long": 100},
        {"short": 60, "long": 100},
    ]


@pytest.mark.parametrize(
    "change",
    [
        {"univers": ["FICT-RTEND"]},
        {"periode": {"debut": "2017-01-02", "fin": "2025-12-31"}},
        {"capital_initial_eur": 50_000},
        {"donnees": "reelles"},
        {"grille": {"short": [5, 10], "long": [50, 100, 200]}},
    ],
)
def test_the_grid_print_covers_what_changes_the_results(change: dict[str, Any]) -> None:
    assert grid_sha256(spec_with(**change)) != grid_sha256(load_spec(DEMO))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"module": "core/finance/research/strategies/autre.py"}, "attendu"),
        ({"univers": ["FICT-RTEND", "FICT-RTEND"]}, "en double dans l'univers"),
        ({"grille": {"short": [5, 5], "long": [50]}}, "valeur en double"),
        ({"contraintes": [{"parametre": "short", "inferieur_a": "moyen"}]}, "absent de la grille"),
        (
            {
                "grille": {"short": ["a"], "long": [50]},
                "contraintes": [{"parametre": "short", "inferieur_a": "long"}],
            },
            "valeurs numériques",
        ),
        ({"grille": {"short": [100], "long": [50]}}, "aucune configuration"),
        ({"grille": {"a": list(range(30)), "b": list(range(30))}, "contraintes": []}, "plus de"),
        ({"periode": {"debut": "2025-12-31", "fin": "2016-01-04"}}, "debut"),
        ({"frequence": "horaire"}, "frequence"),
        ({"donnees": "reelle"}, "donnees"),
        ({"statut": "production"}, "statut"),
        ({"capital_initial_eur": 0}, "capital_initial_eur"),
        ({"inconnu": 1}, "inconnu"),
    ],
)
def test_an_incoherent_entry_is_refused(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        spec_with(**change)


def test_the_grid_ceiling_holds() -> None:
    assert 30 * 30 > MAX_CONFIGURATIONS >= 22 * 22
    spec_with(grille={"a": list(range(22)), "b": list(range(22))}, contraintes=[])


def test_an_entry_must_be_named_after_its_id(tmp_path: Path) -> None:
    path = tmp_path / "autre_nom.yaml"
    path.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(RegistryError, match="doit nommer le fichier"):
        load_spec(path)
    broken = tmp_path / "casse.yaml"
    broken.write_text("id: [", encoding="utf-8")
    with pytest.raises(RegistryError, match="invalide"):
        load_spec(broken)


def test_a_missing_class_or_module_is_refused() -> None:
    with pytest.raises(RegistryError, match="introuvable"):
        load_strategy(spec_with(classe="Absente"))
    missing = spec_with(id="absente", module="core/finance/research/strategies/absente.py")
    with pytest.raises(RegistryError, match="illisible"):
        code_sha256(missing, REPO)
    with pytest.raises(RegistryError, match="introuvable"):
        load_strategy(missing)


# Promotion --------------------------------------------------------------------------------

DAY = date(2026, 10, 20)


def candidate(**changes: Any) -> StrategySpec:
    return spec_with(statut="candidate", donnees="reelles", **changes)


def approve(directory: Path, spec: StrategySpec, report: str, **changes: str) -> None:
    """What Lucas would copy by hand; tests write it in a temporary folder only."""
    text = approval_text(
        spec, report_sha256=report, code=code_sha256(spec, REPO), grid=grid_sha256(spec), day=DAY
    )
    body = yaml.safe_load(text)
    body.update(changes)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{spec.id}.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")


def stamp(spec: StrategySpec, **changes: str) -> dict[str, str]:
    return {
        "strategie": spec.id,
        "verdict": "reussi",
        "donnees": "reelles",
        "frais": "reels",
        "code_sha256": code_sha256(spec, REPO),
        "grille_sha256": grid_sha256(spec),
        "nom": "ignoré par le contrôle",
        **changes,
    }


def report(directory: Path, body: dict[str, str], name: str = "croisement_mm-2026-10-20") -> str:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return report_sha256(path)


def test_the_approval_text_is_a_valid_approval_to_copy_by_hand() -> None:
    spec = candidate()
    text = approval_text(spec, report_sha256="a" * 64, code="b" * 64, grid="c" * 64, day=DAY)
    assert text.startswith("# À recopier à la main par Lucas seul")
    found = StrategyApproval.model_validate(yaml.safe_load(text))
    assert (found.strategie, found.rapport_sha256, found.date) == (spec.id, "a" * 64, DAY)


def test_a_valid_candidate_passes(tmp_path: Path) -> None:
    spec = candidate()
    sha = report(tmp_path / "reports", stamp(spec))
    approve(tmp_path / "approvals", spec, sha)
    local = LocalEvidence(tmp_path / "reports", frozenset({sha}))
    assert promotion_errors(spec, root=REPO, approvals=tmp_path / "approvals", local=local) == []
    # Without a local base, only the approval and the fingerprints are checked.
    assert promotion_errors(spec, root=REPO, approvals=tmp_path / "approvals") == []


def test_a_candidate_without_a_readable_approval_is_refused(tmp_path: Path) -> None:
    spec = candidate()
    [missing] = promotion_errors(spec, root=REPO, approvals=tmp_path)
    assert "aucune approbation" in missing
    (tmp_path / f"{spec.id}.yaml").write_text("strategie: [", encoding="utf-8")
    [unreadable] = promotion_errors(spec, root=REPO, approvals=tmp_path)
    assert "illisible" in unreadable or "invalide" in unreadable


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"strategie": "autre"}, "l'approbation porte sur autre"),
        ({"code_sha256": "0" * 64}, "code modifié"),
        ({"grille_sha256": "0" * 64}, "grille modifiée"),
    ],
)
def test_a_stale_approval_is_refused(tmp_path: Path, changes: dict[str, str], message: str) -> None:
    spec = candidate()
    approve(tmp_path, spec, "a" * 64, **changes)
    errors = promotion_errors(spec, root=REPO, approvals=tmp_path)
    assert any(message in e for e in errors), errors


def test_an_approval_goes_stale_when_the_grid_changes(tmp_path: Path) -> None:
    approve(tmp_path, candidate(), "a" * 64)
    wider = candidate(grille={"short": [5, 10, 20, 30], "long": [50, 100, 200]})
    errors = promotion_errors(wider, root=REPO, approvals=tmp_path)
    assert any("grille modifiée" in e for e in errors), errors


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"donnees": "synthetiques"}, "données synthétiques"),
        ({"frais": "fictifs"}, "frais fictifs"),
        ({"verdict": "incomplet"}, "« reussi » exigé"),
        ({"strategie": "autre"}, "le rapport porte sur autre"),
        ({"code_sha256": "0" * 64}, "empreinte de code du rapport"),
        ({"grille_sha256": "0" * 64}, "empreinte de grille du rapport"),
    ],
)
def test_a_report_that_cannot_promote_is_refused(
    tmp_path: Path, changes: dict[str, str], message: str
) -> None:
    spec = candidate()
    sha = report(tmp_path / "reports", stamp(spec, **changes))
    approve(tmp_path / "approvals", spec, sha)
    local = LocalEvidence(tmp_path / "reports", frozenset({sha}))
    errors = promotion_errors(spec, root=REPO, approvals=tmp_path / "approvals", local=local)
    assert len(errors) == 1 and message in errors[0], errors


def test_a_report_must_exist_be_readable_and_be_audited(tmp_path: Path) -> None:
    spec, reports, approvals = candidate(), tmp_path / "reports", tmp_path / "approvals"
    reports.mkdir()
    approve(approvals, spec, "a" * 64)
    [missing] = promotion_errors(
        spec, root=REPO, approvals=approvals, local=LocalEvidence(reports, frozenset({"a" * 64}))
    )
    assert "introuvable" in missing
    path = reports / "croisement_mm-2026-10-20.json"
    path.write_text("{", encoding="utf-8")
    approve(approvals, spec, report_sha256(path))
    [unreadable] = promotion_errors(
        spec,
        root=REPO,
        approvals=approvals,
        local=LocalEvidence(reports, frozenset({report_sha256(path)})),
    )
    assert "illisible" in unreadable
    sha = report(reports, stamp(spec), name="croisement_mm-2026-10-21")
    approve(approvals, spec, sha)
    [unaudited] = promotion_errors(
        spec, root=REPO, approvals=approvals, local=LocalEvidence(reports, frozenset())
    )
    assert "absente du journal d'audit" in unaudited


def test_only_the_protocol_decisions_of_lucas_audit_a_report(tmp_path: Path) -> None:
    journal = tmp_path / "audit" / "journal.jsonl"
    assert audited_reports(journal) == frozenset()
    audit = AuditJournal(journal)
    cited = {"command": PROTOCOL_COMMAND, "rapport_sha256": "a" * 64}
    audit.append(actor="lucas", event="DECISION", payload=cited)
    audit.append(actor="lucas", event="TOOL_CALL", payload={**cited, "rapport_sha256": "b" * 64})
    audit.append(
        actor="orchestrator", event="DECISION", payload={**cited, "rapport_sha256": "c" * 64}
    )
    audit.append(
        actor="lucas", event="DECISION", payload={"command": "autre", "rapport_sha256": "d" * 64}
    )
    audit.append(actor="lucas", event="DECISION", payload=None)
    assert audited_reports(journal) == frozenset({"a" * 64})
    with journal.open("a", encoding="utf-8") as handle:
        handle.write("{\n")
    with pytest.raises(RegistryError, match="journal d'audit illisible"):
        audited_reports(journal)
