"""The finance committee: its manifest, its cards and toolboxes, and its limit checks (offline)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.committee.cards import CARDS_DIR, COMMITTEE_FILE, CommitteeError, read_committee
from core.committee.rules import final_verdict
from core.committee.schemas import ControllerReport, ManagerDecision
from core.config.loader import PaperRiskLimits, load_config
from core.orchestrator.packs import PACKS_DIR, load_packs
from core.registry.agents import load_agent
from core.registry.manifest import validate_plugin
from plugins.finance_committee.agent import FEATURE, PACK, finance_committee
from plugins.finance_committee.limits import CHECKED, NO_SIZE, paper_limit_checks

PLUGIN = Path(__file__).resolve().parents[1]
ROOT = PLUGIN.parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]
ANALYSTS = ("analyste_technique", "analyste_actualites_macro", "analyste_portefeuille")
READ_ONLY = {"LECTURE", "CALCUL"}  # R5: no role has an action tool
UNDEFINED: dict[str, Any] = {
    name: "A_DEFINIR" for name in PaperRiskLimits.model_fields if name != "allow"
} | {"allow": {"leverage": False, "short_selling": False, "derivatives": False}}
# Every limit defined: the golden cases' values, in percent (D4).
DEFINED: dict[str, Any] = UNDEFINED | next(c["limits"] for c in GOLDEN if c["id"] == "fcom-005")


@pytest.fixture(scope="module")
def config() -> Any:
    return load_config(ROOT / "config")


def decision(choice: str) -> ManagerDecision:
    return ManagerDecision.model_validate(
        {
            "decision": choice,
            "proposition": "Proposition de test",
            "confiance": "faible",
            "horizon": "court",
            "invalidation": [{"condition": "un constat contraire", "constats": ["C1"]}],
            "arguments": [{"id": "D1.1", "sort": "retenu", "raison": "fondé"}],
        }
    )


def report(verdict: str = "OK", appel: str | None = "controleur_risque:risk_report#1") -> Any:
    return ControllerReport.model_validate(
        {
            "scenarios": [{"texte": "Choc de marché", "appel": appel}],
            "irreversibilite": "Aucune : rien n'est exécuté",
            "verdict": verdict,
            "raisons": ["contrôles du code"],
        }
    )


def pack_copy(tmp_path: Path) -> Path:
    target = tmp_path / PACK
    shutil.copytree(PACKS_DIR / PACK, target)
    return target


def test_the_registry_validates_and_loads_the_agent() -> None:
    report_ = validate_plugin(PLUGIN)
    assert report_.ok, report_.errors
    assert report_.manifest is not None and report_.manifest.tools == []
    assert load_agent(PLUGIN) is finance_committee


def test_the_committee_follows_annex_e(config: Any) -> None:
    spec = finance_committee(config)
    assert (spec.pack, spec.feature) == ("finance", "finance.committee") == (PACK, FEATURE)
    assert tuple(card.member for card in spec.analysts) == ANALYSTS
    assert {card.member: card.tools for card in spec.analysts} == {
        "analyste_technique": ("strategy_lab", "market_data"),
        "analyste_actualites_macro": ("web_search", "web_read", "market_data"),
        "analyste_portefeuille": ("portfolio_snapshot", "risk_report"),
    }
    debate = (spec.defender, spec.challenger, spec.manager)
    assert [(c.member, c.kind, c.tools) for c in debate] == [
        ("defenseur", "defenseur", ()),
        ("contradicteur", "contradicteur", ()),
        ("gestionnaire", "gestionnaire", ()),
    ]
    assert (spec.controller.member, spec.controller.kind) == ("controleur_risque", "controleur")
    assert spec.controller.tools == ("risk_report",)
    assert spec.version.startswith("0.1.0+") and len(spec.version) == len("0.1.0+") + 12


def test_every_member_sits_at_its_tier_and_inactive_ones_have_none(config: Any) -> None:
    spec = finance_committee(config)
    tiers = config.committee.finance.tiers
    assert set(tiers) == {card.member for card in spec.cards()}
    assert tiers["gestionnaire"] == "deep"  # D17
    file, _ = read_committee(PACKS_DIR / PACK, PACK)
    assert [i.membre for i in file.inactifs] == ["analyste_fondamental", "analyste_sentiment"]
    assert not set(tiers) & {i.membre for i in file.inactifs}


def test_every_toolbox_tool_reads_or_computes_in_a_plugin_of_the_pack(config: Any) -> None:
    classes: dict[str, str] = {}
    for plugin in load_packs()[PACK].plugins:
        manifest = validate_plugin(ROOT / "plugins" / plugin).manifest
        assert manifest is not None
        classes |= {tool.name: tool.action_class for tool in manifest.tools}
    for card in finance_committee(config).cards():
        for tool in card.tools:
            assert classes.get(tool) in READ_ONLY, (card.member, tool)


def test_every_card_states_its_mission_and_what_is_forbidden(config: Any) -> None:
    for card in finance_committee(config).cards():
        assert not card.system.startswith("<!--"), card.member  # the header is dropped
        assert "(R16)" in card.system and "\nInterdit : " in card.system, card.member
        if card.kind != "analyste":
            assert "(R5)" in card.system, card.member
    controller = finance_committee(config).controller.system
    assert "jamais l'assouplir" in controller and "A_DEFINIR" in controller


def test_a_changed_card_changes_the_version_but_line_endings_do_not(
    config: Any, tmp_path: Path
) -> None:
    pack = pack_copy(tmp_path)
    before = finance_committee(config, tmp_path).version
    card = pack / CARDS_DIR / "gestionnaire.md"
    card.write_bytes(card.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert finance_committee(config, tmp_path).version == before
    card.write_text(card.read_text(encoding="utf-8") + "\nUne règle de plus.", encoding="utf-8")
    assert finance_committee(config, tmp_path).version != before


def test_a_card_that_only_holds_its_header_is_refused(config: Any, tmp_path: Path) -> None:
    card = pack_copy(tmp_path) / CARDS_DIR / "contradicteur.md"
    card.write_text("<!-- en-tête seul -->\n", encoding="utf-8")
    with pytest.raises(CommitteeError, match="fiche de rôle vide pour contradicteur"):
        finance_committee(config, tmp_path)
    card.unlink()
    with pytest.raises(CommitteeError, match="illisible pour contradicteur"):
        finance_committee(config, tmp_path)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["defenseur"].update(outils=["risk_report"]), "sans outil"),
        (lambda d: d["analystes"][0].update(outils=[]), "par ses outils"),
        (lambda d: d["controleur"].pop("outils"), "par ses outils"),
        (lambda d: d["analystes"].append({"membre": "defenseur", "outils": ["x"]}), "deux fois"),
        (lambda d: d["inactifs"].append({"membre": "gestionnaire", "raison": "r"}), "inactif"),
        (lambda d: d["analystes"][1].update(outils=list("abcdef")), "at most 5"),
        (lambda d: d["analystes"][0].update(outils=["market_data"] * 2), "deux fois"),
        (lambda d: d["analystes"][0].update(membre="../role"), "membre"),
        (lambda d: d.update(executeur={"membre": "x"}), "executeur"),
        (lambda d: d.update(analystes=[]), "analystes"),
    ],
)
def test_a_committee_file_that_breaks_annex_e_is_refused(
    config: Any, tmp_path: Path, change: Any, message: str
) -> None:
    path = pack_copy(tmp_path) / COMMITTEE_FILE
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(CommitteeError, match=message):
        finance_committee(config, tmp_path)


@pytest.mark.parametrize("choice", ["agir", "ne_pas_agir", "attendre"])
def test_every_session_blocks_while_the_paper_limits_are_undefined(
    config: Any, choice: str
) -> None:
    """R7: the versioned limits are all A_DEFINIR, so no proposal can be cleared today."""
    checks = finance_committee(config).limit_checks(decision(choice), [])
    assert [(c.name, c.ok) for c in checks] == [(name, None) for name in CHECKED]
    assert all("A_DEFINIR dans config/risk_limits.paper.yaml" in c.reason for c in checks)
    verdict, reasons = final_verdict(checks, report())
    assert verdict == "BLOQUER" and len(reasons) == len(CHECKED)


def test_a_decision_to_act_stays_unknown_until_the_order_intent(config: Any) -> None:
    limits = PaperRiskLimits.model_validate(DEFINED)
    checks = paper_limit_checks(limits)(decision("agir"), [])
    assert {c.reason for c in checks} == {NO_SIZE} and {c.ok for c in checks} == {None}


@pytest.mark.parametrize("case", GOLDEN, ids=[case["id"] for case in GOLDEN])
def test_golden_cases(case: dict[str, Any]) -> None:
    limits = PaperRiskLimits.model_validate(UNDEFINED | case["limits"])
    checks = paper_limit_checks(limits)(decision(case["decision"]), [])
    controller = case.get("controleur", {})
    verdict, _ = final_verdict(
        checks,
        report(controller.get("verdict", "OK"), controller.get("appel", "risk_report#1")),
    )
    assert {c.name: c.ok for c in checks} == case["expected"]["checks"]
    assert verdict == case["expected"]["verdict"]
