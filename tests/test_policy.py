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
    ORDER_ACTION_CLASSES,
    ORDER_DECISIONS,
    ORDER_DOMAIN,
    PHASE_ACTION_CLASSES,
    PHASE_DOMAIN_ACTION_CLASSES,
    ROUTED_ACTION_CLASSES,
    PolicyDecision,
    RecordedCheck,
    RiskGateRecord,
    decide,
    decide_order,
    kill_switch_engaged,
    phase_action_classes,
)
from core.risk_gate.gate import RiskCheck, RiskGateResult

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


def _at(level: str, matrix: dict | None = None, domain: str = "test") -> AutonomyConfig:
    """The real autonomy config with ``domain`` (a test domain by default) at ``level``."""
    data = AUTONOMY.model_dump()
    data["domains"][domain] = {"level": level, "max_level": "N4"}
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
        live_enabled=kw.pop("live_enabled", False),
        **kw,
    )


def _gate(result: str) -> RiskGateResult:
    """A Risk Gate answer, written by hand: the policy reads its result and its checks."""
    check = RiskCheck(
        name="max_order_pct", ok=result != "REFUSE", value="3.015", limit="5", reason="ordre"
    )
    return RiskGateResult(
        result=result,  # type: ignore[arg-type]
        intent_id=None,
        intent_sha256=None,
        requested_quantity=3,
        quantity={"ACCEPTE": 3, "REDUIT": 2, "REFUSE": 0}[result],
        checks=(check,),
        reasons=("max_order_pct : ordre",),
    )


GATES = (None, *(_gate(result) for result in ("ACCEPTE", "REDUIT", "REFUSE")))


def _order(level: str, gate: RiskGateResult | None, **kw: bool) -> PolicyDecision:
    return decide_order(
        _at(level, domain="finance"),
        request_id="r1",
        kill_switch=kw.get("kill_switch", False),
        live_enabled=kw.get("live_enabled", False),
        risk_gate=gate,
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
def test_phase_2_grants_reading_and_finance_computing(domain: str, action_class: str) -> None:
    granted = action_class == "LECTURE" or (action_class, domain) == ("CALCUL", "finance")
    result = _decide(AUTONOMY, domain, action_class)
    expected = "auto" if granted else "refus"
    assert result.decision == expected
    assert result.effect == ("executer" if expected == "auto" else "refuser")
    level = AUTONOMY.domains[domain].level
    assert result.autonomy_level == level
    cell = SPEC_MATRIX[action_class][LEVELS.index(level)]
    assert result.reasons[0] == f"matrice {action_class} × {level} : {cell}"


@pytest.mark.parametrize(("action_class", "level"), list(product(ACTION_CLASSES, LEVELS)))
def test_every_cell_of_a_domain_without_computing(action_class: str, level: str) -> None:
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
def test_every_cell_of_finance_in_phase_2(action_class: str, level: str) -> None:
    """Finance computes at every level (CALCUL is ``auto`` in the matrix), and nothing more."""
    cell = SPEC_MATRIX[action_class][LEVELS.index(level)]
    result = _decide(_at(level, domain="finance"), "finance", action_class)
    assert result.autonomy_level == level
    if cell == "auto" and action_class in {"LECTURE", "CALCUL"}:
        assert result.decision == "auto"
        assert result.reasons == (f"matrice {action_class} × {level} : auto",)
    else:
        assert result.decision == "refus"
        assert result.reasons[0] == f"matrice {action_class} × {level} : {cell}"


@pytest.mark.parametrize(("action_class", "level"), list(product(ACTION_CLASSES, LEVELS)))
def test_every_cell_once_all_decisions_exist(action_class: str, level: str) -> None:
    """With every decision and class implemented, a cell is granted only if it has an effect.

    ``auto`` executes any class but a financial one; a financial action is only drafted, sent
    to the paper adapter or filed for approval, with the Risk Gate's answer. ``brouillon``,
    ``simule``, ``auto_dans_limites`` and ``approbation`` for any other class have no effect and
    are refused (D5).
    """
    cell = SPEC_MATRIX[action_class][LEVELS.index(level)]
    financial = action_class == "FINANCIERE"
    result = _decide(
        _at(level),
        "test",
        action_class,
        action_classes=frozenset(ACTION_CLASSES),
        decisions=frozenset(CELLS),
        risk_gate=_gate("ACCEPTE") if financial else None,
    )
    effects = (
        {"proposition": "proposer", "paper": "paper", "approbation": "approbation"}
        if financial
        else {"auto": "executer"}
    )
    if cell in effects:
        assert (result.decision, result.effect) == (cell, effects[cell])
    else:
        assert (result.decision, result.effect) == ("refus", "refuser")
        if cell != "refus":
            assert result.reasons[1] == f"« {cell} » n'a aucun effet pour {action_class} : refus"


def test_unimplemented_decision_is_refused() -> None:
    result = _decide(AUTONOMY, "generaliste", "COMMUNICATION_EXTERNE")
    assert result.decision == "refus"
    assert result.reasons == (
        "matrice COMMUNICATION_EXTERNE × N1 : brouillon",
        "« brouillon » n'est pas encore mis en œuvre : refus",
    )


def test_auto_cell_without_capability_is_refused() -> None:
    result = _decide(AUTONOMY, "generaliste", "ECRITURE_INTERNE")
    assert result.reasons[1] == (
        "aucune capacité ECRITURE_INTERNE pour le domaine « generaliste » dans cette phase : refus"
    )


def test_computing_outside_finance_is_refused() -> None:
    result = _decide(AUTONOMY, "generaliste", "CALCUL")
    assert result.reasons == (
        "matrice CALCUL × N1 : auto",
        "aucune capacité CALCUL pour le domaine « generaliste » dans cette phase : refus",
    )


def test_explicit_classes_replace_the_phase_grants() -> None:
    assert _decide(AUTONOMY, "finance", "CALCUL", action_classes=PHASE_ACTION_CLASSES).decision == (
        "refus"
    )
    granted = frozenset({"LECTURE", "CALCUL"})
    assert _decide(AUTONOMY, "generaliste", "CALCUL", action_classes=granted).decision == "auto"


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
    live=st.booleans(),
    gate=st.sampled_from(GATES),
)
def test_never_more_permissive_than_the_matrix(
    cells: list[str],
    level: str,
    action_class: str,
    granted_classes: frozenset,
    granted_decisions: frozenset,
    kill: bool,
    live: bool,
    gate: RiskGateResult | None,
) -> None:
    it = iter(cells)
    matrix = {c: {lvl: next(it) for lvl in LEVELS} for c in ACTION_CLASSES}
    result = _decide(
        _at(level, matrix),
        "test",
        action_class,
        kill_switch=kill,
        live_enabled=live,
        action_classes=granted_classes,
        decisions=granted_decisions,
        risk_gate=gate,
    )
    cell = matrix[action_class][level]
    financial = action_class == "FINANCIERE"
    effective = {"proposition", "paper", "approbation"} if financial else {"auto"}
    gate_ok = gate is not None and gate.result != "REFUSE" if financial else gate is None
    if result.decision != "refus":
        assert result.decision == cell
        assert result.effect != "refuser"
        assert not kill
        assert not live
        assert cell in granted_decisions & effective
        assert action_class in granted_classes
        assert gate_ok
    else:
        assert result.effect == "refuser"
        assert (
            kill
            or live
            or cell not in granted_decisions & effective
            or action_class not in granted_classes
            or not gate_ok
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


def test_phase_2_classes() -> None:
    assert frozenset({"LECTURE"}) == PHASE_ACTION_CLASSES
    assert dict(PHASE_DOMAIN_ACTION_CLASSES) == {
        "finance": frozenset({"LECTURE", "CALCUL"}),
        "code": frozenset({"LECTURE", "CALCUL"}),  # ADR-049
    }
    assert frozenset({"CALCUL"}) == ROUTED_ACTION_CLASSES
    assert phase_action_classes("finance") == frozenset({"LECTURE", "CALCUL"})
    assert phase_action_classes("code") == frozenset({"LECTURE", "CALCUL"})
    for domain in ("generaliste", "recherche", "cyber", "test", "inconnu", ""):
        assert phase_action_classes(domain) == PHASE_ACTION_CLASSES


def test_phase_grants_are_read_only() -> None:
    with pytest.raises(TypeError):
        PHASE_DOMAIN_ACTION_CLASSES["generaliste"] = frozenset({"CALCUL"})  # type: ignore[index]


@given(
    domain=st.sampled_from(["generaliste", "finance", "recherche", "test"]),
    known=st.booleans(),
    action_class=st.sampled_from(ACTION_CLASSES),
    level=st.sampled_from(LEVELS),
    kill=st.booleans(),
)
def test_the_phase_grants_nothing_beyond_reading_and_finance_computing(
    domain: str, known: bool, action_class: str, level: str, kill: bool
) -> None:
    autonomy = _at(level, domain=domain) if known else AUTONOMY
    result = _decide(autonomy, domain, action_class, kill_switch=kill)
    if result.effect != "refuser":
        assert result.effect == "executer"
        assert not kill
        assert action_class == "LECTURE" or (action_class, domain) == ("CALCUL", "finance")


# --- order intents of the paper loop (ADR-030) ---

ALERT = (
    "ALERTE : la configuration live est activée alors qu'aucun adaptateur live n'existe (R3) : "
    "toute action est refusée"
)
DOMAINS = ("generaliste", "finance", "recherche", "test", "inconnu")


def test_order_constants() -> None:
    assert ORDER_DOMAIN == "finance"
    assert frozenset({"FINANCIERE"}) == ORDER_ACTION_CLASSES
    assert frozenset({"proposition", "paper", "approbation"}) == ORDER_DECISIONS


@pytest.mark.parametrize("result", ["ACCEPTE", "REDUIT"])
@pytest.mark.parametrize(
    ("level", "cell", "effect"),
    [
        ("N1", "proposition", "proposer"),
        ("N2", "paper", "paper"),
        ("N3", "approbation", "approbation"),
    ],
)
def test_an_order_is_drafted_at_n1_sent_at_n2_and_awaits_approval_at_n3(
    level: str, cell: str, effect: str, result: str
) -> None:
    decision = _order(level, _gate(result))
    assert (decision.domain, decision.action_class, decision.autonomy_level) == (
        "finance",
        "FINANCIERE",
        level,
    )
    assert (decision.decision, decision.effect) == (cell, effect)
    assert decision.reasons == (
        f"matrice FINANCIERE × {level} : {cell}",
        f"Porte de risque : {result}",
    )
    check = RecordedCheck(name="max_order_pct", ok=True, value="3.015", limit="5")
    assert decision.risk_gate == RiskGateRecord(result=result, checks=(check,))  # type: ignore[arg-type]


@pytest.mark.parametrize("level", ["N1", "N2", "N3"])
def test_an_order_without_the_risk_gate_is_refused(level: str) -> None:
    decision = _order(level, None)
    assert (decision.decision, decision.effect, decision.risk_gate) == ("refus", "refuser", None)
    assert decision.reasons[1] == "la Porte de risque n'a pas été consultée (R2) : refus"


@pytest.mark.parametrize("level", ["N1", "N2", "N3"])
def test_an_order_the_risk_gate_refuses_is_refused_and_recorded(level: str) -> None:
    decision = _order(level, _gate("REFUSE"))
    assert (decision.decision, decision.effect) == ("refus", "refuser")
    assert decision.reasons[1] == "Porte de risque : REFUSE"
    assert decision.risk_gate is not None
    assert decision.risk_gate.result == "REFUSE"
    assert [c.ok for c in decision.risk_gate.checks] == [False]


@pytest.mark.parametrize("gate", GATES)
@pytest.mark.parametrize("level", ["N0", "N4"])
def test_an_order_at_n0_or_n4_is_refused(level: str, gate: RiskGateResult | None) -> None:
    decision = _order(level, gate)
    cell = SPEC_MATRIX["FINANCIERE"][LEVELS.index(level)]
    matrix = f"matrice FINANCIERE × {level} : {cell}"
    expected = (
        (matrix,)
        if cell == "refus"
        else (matrix, f"« {cell} » n'est pas encore mis en œuvre : refus")
    )
    assert (decision.decision, decision.effect, decision.reasons) == ("refus", "refuser", expected)


@pytest.mark.parametrize("gate", GATES)
def test_the_real_finance_domain_refuses_every_order(gate: RiskGateResult | None) -> None:
    assert AUTONOMY.domains["finance"].level == "N0"
    decision = decide_order(
        AUTONOMY, request_id="r1", kill_switch=False, live_enabled=False, risk_gate=gate
    )
    assert (decision.decision, decision.autonomy_level) == ("refus", "N0")
    assert decision.reasons == ("matrice FINANCIERE × N0 : refus",)


@pytest.mark.parametrize("level", LEVELS)
def test_the_kill_switch_refuses_every_order(level: str) -> None:
    decision = _order(level, _gate("ACCEPTE"), kill_switch=True, live_enabled=True)
    assert (decision.decision, decision.autonomy_level) == ("refus", "N0")
    assert decision.reasons[0].startswith("kill switch engagé (R4)")


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("action_class", ACTION_CLASSES)
def test_an_enabled_live_configuration_refuses_everything(action_class: str, level: str) -> None:
    """Even reading, even with every decision implemented: no live adapter exists (R3)."""
    decision = _decide(
        _at(level, domain="finance"),
        "finance",
        action_class,
        live_enabled=True,
        action_classes=frozenset(ACTION_CLASSES),
        decisions=frozenset(CELLS),
        risk_gate=_gate("ACCEPTE") if action_class == "FINANCIERE" else None,
    )
    assert (decision.decision, decision.autonomy_level, decision.reasons) == (
        "refus",
        level,
        (ALERT,),
    )


@pytest.mark.parametrize("level", LEVELS)
def test_an_enabled_live_configuration_refuses_every_order(level: str) -> None:
    decision = _order(level, _gate("ACCEPTE"), live_enabled=True)
    assert (decision.decision, decision.reasons) == ("refus", (ALERT,))
    assert decision.risk_gate is not None  # the gate's answer is still journaled


@pytest.mark.parametrize("action_class", ["LECTURE", "CALCUL"])
def test_a_risk_gate_answer_for_a_non_financial_action_is_refused(action_class: str) -> None:
    decision = _decide(
        _at("N2", domain="finance"), "finance", action_class, risk_gate=_gate("ACCEPTE")
    )
    assert decision.decision == "refus"
    assert decision.reasons[1] == "Porte de risque consultée pour une action non financière"


def _phase_3_executes(domain: str, action_class: str, level: str, kill: bool) -> bool:
    """Phase 3's rule, written apart: ``auto`` for reading everywhere and computing in finance."""
    cell = SPEC_MATRIX[action_class][LEVELS.index(level)]
    return (
        domain != "inconnu"
        and not kill
        and cell == "auto"
        and (action_class == "LECTURE" or (action_class, domain) == ("CALCUL", "finance"))
    )


def test_no_path_is_more_permissive_than_phase_3() -> None:
    """Every domain, level, class, kill switch, live state and gate answer, for both entry points.

    ``decide`` still executes exactly what phase 3 executed, without live and without a gate
    answer, and nothing else; ``decide_order`` never executes: it drafts at N1, sends to paper
    at N2 and files for approval at N3 an order the gate accepted or reduced, without the kill
    switch and without live.
    """
    autonomies = {(d, lvl): _at(lvl, domain=d) for d in DOMAINS[:-1] for lvl in LEVELS}
    for domain, level, action_class, kill, live, gate in product(
        DOMAINS, LEVELS, ACTION_CLASSES, (False, True), (False, True), GATES
    ):
        autonomy = autonomies.get((domain, level), AUTONOMY)
        result = _decide(
            autonomy, domain, action_class, kill_switch=kill, live_enabled=live, risk_gate=gate
        )
        phase_3 = _phase_3_executes(domain, action_class, level, kill)
        assert result.effect in ("executer", "refuser")
        assert (result.effect == "executer") == (phase_3 and not live and gate is None)
    for level, kill, live, gate in product(LEVELS, (False, True), (False, True), GATES):
        result = _order(level, gate, kill_switch=kill, live_enabled=live)
        gate_ok = gate is not None and gate.result != "REFUSE"
        expected = (
            {"N1": "proposer", "N2": "paper", "N3": "approbation"}.get(level) if gate_ok else None
        )
        assert result.effect == (expected if not (kill or live) and expected else "refuser")


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("action_class", ACTION_CLASSES)
def test_approbation_files_only_a_financial_action(action_class: str, level: str) -> None:
    """D5: with every class and every decision granted, only FINANCIERE waits for an approval."""
    matrix = {c: dict.fromkeys(LEVELS, "approbation") for c in ACTION_CLASSES}
    financial = action_class == "FINANCIERE"
    result = _decide(
        _at(level, matrix),
        "test",
        action_class,
        action_classes=frozenset(ACTION_CLASSES),
        decisions=frozenset(CELLS),
        risk_gate=_gate("ACCEPTE") if financial else None,
    )
    assert result.effect == ("approbation" if financial else "refuser")
    if not financial:
        assert result.reasons[-1] == f"« approbation » n'a aucun effet pour {action_class} : refus"


def test_an_order_decision_payload_records_the_risk_gate() -> None:
    decision = _order("N2", _gate("REDUIT"))
    payload = decision.to_payload()
    assert payload["decision"] == "paper"
    assert payload["risk_gate"] == {
        "result": "REDUIT",
        "checks": [{"name": "max_order_pct", "ok": True, "value": "3.015", "limit": "5"}],
    }
    assert "effect" not in payload
    assert PolicyDecision.model_validate(payload) == decision


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
