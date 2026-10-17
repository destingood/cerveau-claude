from __future__ import annotations

from itertools import product
from pathlib import Path
from typing import get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.config import load_config
from core.config.loader import ACTION_CLASSES, LEVELS, AutonomyConfig, MatrixDecision
from core.policy import (
    KILL_SWITCH_FILE,
    PHASE_ACTION_CLASSES,
    PolicyDecision,
    decide,
    kill_switch_engaged,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTONOMY = load_config(REPO_ROOT / "config").autonomy
CELLS: tuple[str, ...] = get_args(MatrixDecision)

# Section 8.2, copied by hand: the test fails if autonomy.yaml drifts from the spec.
SPEC_MATRIX = {
    "LECTURE": ("auto", "auto", "auto", "auto", "auto"),
    "CALCUL": ("auto", "auto", "auto", "auto", "auto"),
    "ECRITURE_INTERNE": ("refus", "auto", "auto", "auto", "auto"),
    "COMMUNICATION_EXTERNE": ("refus", "brouillon", "brouillon", "approbation", "approbation"),
    "IRREVERSIBLE": ("refus", "refus", "simule", "approbation", "approbation"),
    "FINANCIERE": ("refus", "proposition", "paper", "approbation", "auto_dans_limites"),
}


def _at(level: str, matrix: dict | None = None) -> AutonomyConfig:
    """The real autonomy config with a test domain at ``level``."""
    data = AUTONOMY.model_dump()
    data["domains"]["test"] = {"level": level, "max_level": "N4"}
    if matrix is not None:
        data["matrix"] = matrix
    return AutonomyConfig.model_validate(data)


def _decide(autonomy: AutonomyConfig, domain: str, action_class: str, **kw) -> PolicyDecision:
    return decide(
        autonomy,
        request_id="r1",
        domain=domain,
        action_class=action_class,  # type: ignore[arg-type]
        kill_switch=kw.pop("kill_switch", False),
        **kw,
    )


def test_matrix_matches_section_8_2() -> None:
    for action_class, row in SPEC_MATRIX.items():
        assert tuple(AUTONOMY.matrix[action_class][lvl] for lvl in LEVELS) == row


def test_phase_1_domains() -> None:
    assert (AUTONOMY.domains["generaliste"].level, AUTONOMY.domains["finance"].level) == (
        "N1",
        "N0",
    )


@pytest.mark.parametrize("action_class", ACTION_CLASSES)
@pytest.mark.parametrize("domain", ["generaliste", "finance"])
def test_phase_1_grants_reading_only(domain: str, action_class: str) -> None:
    result = _decide(AUTONOMY, domain, action_class)
    expected = "auto" if action_class == "LECTURE" else "refus"
    assert result.decision == expected
    assert result.allowed is (expected == "auto")
    level = AUTONOMY.domains[domain].level
    assert result.autonomy_level == level
    cell = SPEC_MATRIX[action_class][LEVELS.index(level)]
    assert result.reasons[0] == f"matrice {action_class} × {level} : {cell}"


@pytest.mark.parametrize(("action_class", "level"), list(product(ACTION_CLASSES, LEVELS)))
def test_every_cell_in_phase_1(action_class: str, level: str) -> None:
    cell = SPEC_MATRIX[action_class][LEVELS.index(level)]
    result = _decide(_at(level), "test", action_class)
    assert result.autonomy_level == level
    if cell == "auto" and action_class == "LECTURE":
        assert result.decision == "auto"
        assert result.reasons == (f"matrice {action_class} × {level} : auto",)
    else:
        assert result.decision == "refus"
        assert result.reasons[0] == f"matrice {action_class} × {level} : {cell}"
        if cell != "refus":
            assert result.reasons[1].endswith(": refus")


@pytest.mark.parametrize(("action_class", "level"), list(product(ACTION_CLASSES, LEVELS)))
def test_every_cell_once_all_decisions_exist(action_class: str, level: str) -> None:
    """With every decision and class implemented, the engine returns the cell itself."""
    cell = SPEC_MATRIX[action_class][LEVELS.index(level)]
    result = _decide(
        _at(level),
        "test",
        action_class,
        action_classes=frozenset(ACTION_CLASSES),
        decisions=frozenset(CELLS),
    )
    assert result.decision == cell


def test_unimplemented_decision_is_refused() -> None:
    result = _decide(AUTONOMY, "generaliste", "COMMUNICATION_EXTERNE")
    assert result.decision == "refus"
    assert result.reasons == (
        "matrice COMMUNICATION_EXTERNE × N1 : brouillon",
        "« brouillon » n'est pas encore mis en œuvre : refus",
    )


def test_auto_cell_without_capability_is_refused() -> None:
    result = _decide(AUTONOMY, "generaliste", "ECRITURE_INTERNE")
    assert result.reasons[1] == "aucune capacité ECRITURE_INTERNE dans cette phase : refus"


@pytest.mark.parametrize("action_class", ACTION_CLASSES)
def test_kill_switch_refuses_everything(action_class: str) -> None:
    result = _decide(
        _at("N4"),
        "test",
        action_class,
        kill_switch=True,
        action_classes=frozenset(ACTION_CLASSES),
        decisions=frozenset(CELLS),
    )
    assert (result.decision, result.autonomy_level) == ("refus", "N0")
    assert "kill switch" in result.reasons[0]


def test_unknown_domain_is_refused() -> None:
    result = _decide(AUTONOMY, "inconnu", "LECTURE")
    assert (result.decision, result.autonomy_level) == ("refus", "N0")


@given(
    cells=st.lists(st.sampled_from(CELLS), min_size=30, max_size=30),
    level=st.sampled_from(LEVELS),
    action_class=st.sampled_from(ACTION_CLASSES),
    granted_classes=st.frozensets(st.sampled_from(ACTION_CLASSES)),
    granted_decisions=st.frozensets(st.sampled_from(CELLS)),
    kill=st.booleans(),
)
def test_never_more_permissive_than_the_matrix(
    cells: list[str],
    level: str,
    action_class: str,
    granted_classes: frozenset,
    granted_decisions: frozenset,
    kill: bool,
) -> None:
    it = iter(cells)
    matrix = {c: {lvl: next(it) for lvl in LEVELS} for c in ACTION_CLASSES}
    result = _decide(
        _at(level, matrix),
        "test",
        action_class,
        kill_switch=kill,
        action_classes=granted_classes,
        decisions=granted_decisions,
    )
    cell = matrix[action_class][level]
    if result.decision != "refus":
        assert not kill
        assert result.decision == cell
        assert cell in granted_decisions
        assert action_class in granted_classes
    else:
        assert (
            kill
            or cell == "refus"
            or cell not in granted_decisions
            or (action_class not in granted_classes)
        )


def test_decision_payload_follows_annex_c4() -> None:
    payload = _decide(AUTONOMY, "generaliste", "LECTURE").to_payload()
    assert set(payload) == {
        "request_id",
        "domain",
        "action_class",
        "autonomy_level",
        "decision",
        "risk_gate",
        "reasons",
    }
    assert payload["risk_gate"] is None
    assert PolicyDecision.model_validate(payload).decision == "auto"


def test_phase_1_classes_are_reading_only() -> None:
    assert frozenset({"LECTURE"}) == PHASE_ACTION_CLASSES


# --- kill switch file (section 8.5) ---


def test_kill_switch_absent(tmp_path: Path) -> None:
    assert kill_switch_engaged(tmp_path) is False


def test_kill_switch_file(tmp_path: Path) -> None:
    target = tmp_path / KILL_SWITCH_FILE
    target.parent.mkdir(parents=True)
    target.write_text("", encoding="utf-8")
    assert kill_switch_engaged(tmp_path) is True


def test_kill_switch_directory_counts(tmp_path: Path) -> None:
    (tmp_path / KILL_SWITCH_FILE).mkdir(parents=True)
    assert kill_switch_engaged(tmp_path) is True


def test_kill_switch_unknown_state_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: Path, *args: object, **kwargs: object) -> bool:
        raise PermissionError("accès refusé")

    monkeypatch.setattr(Path, "exists", boom)
    assert kill_switch_engaged(tmp_path) is True


def test_repository_kill_switch_is_not_engaged() -> None:
    assert kill_switch_engaged(REPO_ROOT) is False
