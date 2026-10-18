"""The finance pack in the graph: its plugins, its role, the R1 trace and the kill switch (R4)."""

from __future__ import annotations

import asyncio
import json
import unicodedata
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml
from langchain_core.tools import BaseTool, StructuredTool, ToolException

from core.audit import AuditJournal
from core.config.loader import Config, load_config
from core.mcp.adapter import McpAdapterError
from core.orchestrator.graph import Orchestrator
from core.orchestrator.intake import KILL_MESSAGE
from core.orchestrator.packs import PACK_IDS, PACKS_DIR, PackError, load_pack, load_packs
from core.orchestrator.planner import MAX_VIEW_CHARS, figure_view
from core.orchestrator.runtime import WEB_PLUGIN, PluginSet, RequestScope
from core.policy.engine import KILL_SWITCH_FILE
from core.verification.figures import amount, percent
from tests.conftest import REPO_ROOT
from tests.test_orchestrator import (
    NOW,
    PROMPTS,
    Brain,
    FakePseudonymiser,
    Rig,
    World,
    _config,
    _router,
    opener,
    tool_call,
)

FINANCE_TOOLS = {
    "finance_data": "market_data",
    "finance_portfolio": "portfolio_snapshot",
    "finance_risk": "risk_report",
    "finance_optimize": "rebalance_proposal",
    "finance_report": "performance_report",
}
VOLATILITY = percent("mesures/volatilite", 0.1234)
VALUE = amount("valeurs/totale", 12450, "EUR")
RISK = {
    "as_of": "2026-10-16",
    "mesures": {"volatilite": VOLATILITY.model_dump(mode="json")},
    "valeurs": [{"totale": VALUE.model_dump(mode="json")}],
    "hypotheses": ["[Hypothèse] 252 séances par an"],
}
FINANCE_ROUTE = {
    "domaine": "finance",
    "complexite": "simple",
    "importance": "normale",
    "web": False,
    "raison": "risque du portefeuille",
}


def _finance(as_of: str = "") -> str:
    """Outil finance."""
    return ""


@dataclass
class Desk:
    """The fake finance plugins of a request."""

    failing: set[str] = field(default_factory=set)
    payload: dict[str, Any] = field(default_factory=lambda: dict(RISK))
    on_call: Callable[[], None] | None = None
    opened: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


class FinanceToolbox:
    def __init__(self, desk: Desk, plugin: str, scope: RequestScope) -> None:
        self.desk, self.scope = desk, scope
        self.tools: tuple[BaseTool, ...] = (
            StructuredTool.from_function(_finance, name=FINANCE_TOOLS[plugin]),
        )
        self.skipped: dict[str, str] = {}
        self.version = f"{plugin}@0.1.0"

    async def call(
        self, name: str, arguments: dict[str, Any], *, journaled: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        self.scope.budget.charge_tool_call()
        self.desk.calls.append((name, dict(arguments)))
        if self.desk.on_call is not None:
            self.desk.on_call()
        return self.desk.payload


def finance_opener(desk: Desk, plugin: str) -> Any:
    @asynccontextmanager
    async def open_toolbox(scope: RequestScope) -> AsyncIterator[FinanceToolbox]:
        if plugin in desk.failing:
            raise McpAdapterError(f"plugin {plugin} : démarrage impossible")
        desk.opened.append(plugin)
        try:
            yield FinanceToolbox(desk, plugin, scope)
        finally:
            desk.closed.append(plugin)

    return open_toolbox


@dataclass
class FinanceRig(Rig):
    desk: Desk = field(default_factory=Desk)

    def entries(self, event: str) -> list[dict[str, Any]]:
        lines = self.journal.path.read_text(encoding="utf-8").splitlines()
        return [entry for entry in map(json.loads, lines) if entry["event"] == event]


def make_finance_rig(root: Path, config: Config) -> FinanceRig:
    brain, world, desk = Brain(route=dict(FINANCE_ROUTE)), World(), Desk()
    journal = AuditJournal(root / "audit" / "journal.jsonl")
    toolboxes = {plugin: finance_opener(desk, plugin) for plugin in FINANCE_TOOLS}
    orchestrator = Orchestrator(
        config,
        project_root=root,
        journal=journal,
        router=_router(config, brain),
        toolboxes={**toolboxes, WEB_PLUGIN: opener(world)},
        pseudonymiser=FakePseudonymiser,
        prompts=PROMPTS,
        clock=lambda: NOW,
    )
    return FinanceRig(orchestrator, brain, world, journal, desk)


@pytest.fixture
def rig(tmp_path: Path, config_dir: Path) -> FinanceRig:
    return make_finance_rig(tmp_path, _config(config_dir))


def answer_json(synthese: str, **fields: Any) -> str:
    answer: dict[str, Any] = {
        "synthese": synthese,
        "developpement": "Mesure calculée par l'outil de risque sur l'historique disponible.",
        "contre_arguments": "",
        "confiance": {"niveau": "moyen", "justification": "Calcul déterministe de l'outil."},
        "prochaines_etapes": [],
    }
    answer.update(fields)
    return json.dumps(answer, ensure_ascii=False)


def planner_system(rig: Rig) -> str:
    return next(str(messages[0].content) for role, messages in rig.brain.seen if role == "planner")


# --- packs -------------------------------------------------------------------------------------


def test_the_packs_of_phase_2() -> None:
    packs = load_packs()
    assert list(packs) == ["generaliste", "finance"]
    assert packs["generaliste"].plugins == (WEB_PLUGIN,)
    assert packs["finance"].plugins == (*FINANCE_TOOLS, WEB_PLUGIN)


def test_every_pack_has_its_autonomy_role_and_plugins() -> None:
    config = load_config(REPO_ROOT / "config")
    for pack in load_packs().values():
        assert pack.id in config.autonomy.domains
        assert PROMPTS.roles[pack.id]
        for plugin in pack.plugins:
            assert (REPO_ROOT / "plugins" / plugin / "plugin.yaml").is_file()


@pytest.mark.parametrize(
    ("manifest", "reason"),
    [
        ({"id": "autre", "plugins": ["web_research"]}, "différent du dossier"),
        ({"id": "essai", "plugins": ["../web_research"]}, "noms de plugin invalides"),
        ({"id": "essai", "plugins": ["web_research", "web_research"]}, "listé deux fois"),
        ({"id": "essai", "plugins": []}, "invalide"),
        ({"id": "essai"}, "invalide"),
    ],
)
def test_a_malformed_pack_is_refused(tmp_path: Path, manifest: dict[str, Any], reason: str) -> None:
    (tmp_path / "essai").mkdir()
    (tmp_path / "essai" / "manifest.yaml").write_text(yaml.safe_dump(manifest), "utf-8")
    with pytest.raises(PackError, match=reason):
        load_pack("essai", tmp_path)


def test_a_missing_or_unreadable_pack_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PackError, match="illisible"):
        load_pack("essai", tmp_path)
    (tmp_path / "essai").mkdir()
    (tmp_path / "essai" / "manifest.yaml").write_text("id: [", "utf-8")
    with pytest.raises(PackError, match="YAML"):
        load_pack("essai", tmp_path)
    with pytest.raises(PackError, match="repli"):
        load_packs(("finance",), PACKS_DIR)


def test_pack_ids_have_a_manifest() -> None:
    assert all((PACKS_DIR / pack / "manifest.yaml").is_file() for pack in PACK_IDS)


# --- the plugin set ----------------------------------------------------------------------------


@dataclass
class Box:
    tools: tuple[BaseTool, ...]
    version: str
    skipped: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    async def call(
        self, name: str, arguments: dict[str, Any], *, journaled: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        self.calls.append(name)
        return {}


def _tool(name: str) -> BaseTool:
    return StructuredTool.from_function(_finance, name=name)


def test_the_plugin_set_keeps_the_pack_order_and_skips_with_reasons() -> None:
    first = Box((_tool("a"), _tool("b")), "p1@1", skipped={"z": "classe interdite"})
    second = Box((_tool("b"), _tool("c"), _tool("d")), "p2@1")
    tools = PluginSet([("p1", first), ("p2", second)], {"p3": "démarrage impossible"}, limit=3)
    assert [tool.name for tool in tools.tools] == ["a", "b", "c"]
    assert tools.skipped == {
        "p3": "démarrage impossible",
        "z": "classe interdite",
        "p2.b": "nom déjà donné par un autre plugin du pack",
        "d": "au-delà des 3 outils transmis au planificateur",
    }
    assert tools.version == "p1@1, p2@1"
    asyncio.run(tools.call("b", {}))
    asyncio.run(tools.call("c", {}))
    assert (first.calls, second.calls) == (["b"], ["c"])
    with pytest.raises(ToolException, match="indisponible"):
        asyncio.run(tools.call("d", {}))
    assert PluginSet([], {}, limit=3).version == "aucun"


def test_the_planner_reads_figures_by_their_display() -> None:
    view = figure_view(RISK)
    assert view == {
        "as_of": "2026-10-16",
        "mesures": {"volatilite": VOLATILITY.display},
        "valeurs": [{"totale": VALUE.display}],
        "hypotheses": ["[Hypothèse] 252 séances par an"],
    }


# --- requests ----------------------------------------------------------------------------------


def test_a_finance_question_opens_the_finance_plugins_without_the_web(rig: FinanceRig) -> None:
    rig.brain.planner = [answer_json("Je n'ai pas besoin d'outil pour répondre.")]
    rig.ask("Quel est le risque de mon portefeuille ?")
    assert sorted(rig.desk.opened) == sorted(FINANCE_TOOLS)
    assert sorted(rig.desk.closed) == sorted(FINANCE_TOOLS)
    assert rig.world.opened == 0
    assert rig.brain.bound["planner"] == list(FINANCE_TOOLS.values())
    system = planner_system(rig)
    assert PROMPTS.roles["finance"] in system
    assert PROMPTS.roles["generaliste"] not in system
    [entry] = rig.decisions()
    route = entry["payload"]["route"]
    assert (route["domain"], route["requested_domain"]) == ("finance", "finance")
    assert route["tools"] == list(FINANCE_TOOLS.values())
    assert entry["versions"]["plugin"] == ", ".join(f"{p}@0.1.0" for p in FINANCE_TOOLS)
    assert entry["payload"]["policy"]["domain"] == "finance"


def test_a_computing_question_routed_to_finance_is_planned(rig: FinanceRig) -> None:
    rig.brain.verdict = {"decision": "ok", "classe_action": "CALCUL", "raison": "mesure de risque"}
    rig.brain.planner = [answer_json("Réponse sans outil.")]
    result = rig.ask("Calcule la VaR de mon portefeuille.")
    assert result.answer.statut != "refus"
    assert sorted(rig.desk.opened) == sorted(FINANCE_TOOLS)
    assert "planner" in rig.brain.roles()
    [entry] = rig.decisions()
    policy = entry["payload"]["policy"]
    assert (policy["domain"], policy["action_class"], policy["decision"]) == (
        "finance",
        "CALCUL",
        "auto",
    )


def test_a_computing_question_routed_to_an_unknown_pack_is_refused(rig: FinanceRig) -> None:
    rig.brain.verdict = {"decision": "ok", "classe_action": "CALCUL", "raison": "calcul demandé"}
    rig.brain.route = {**FINANCE_ROUTE, "domaine": "astronomie"}
    answer = rig.ask("Calcule la distance de cette étoile.").answer
    assert answer.statut == "refus"
    assert "« generaliste »" in answer.message
    assert rig.desk.opened == []
    assert "planner" not in rig.brain.roles()


def test_the_finance_context_carries_its_autonomy(rig: FinanceRig) -> None:
    rig.brain.planner = [answer_json("Réponse sans outil.")]
    rig.ask("Quel est le risque de mon portefeuille ?")
    system = planner_system(rig)
    assert "finance" in system
    assert "N0" in system


def test_a_finance_question_with_news_also_opens_the_web(rig: FinanceRig) -> None:
    rig.brain.route = {**FINANCE_ROUTE, "web": True}
    rig.brain.planner = [answer_json("Réponse sans outil.")]
    rig.ask("Quelles sont les actualités de cette société ?")
    assert rig.world.opened == 1
    assert rig.brain.bound["planner"] == [*FINANCE_TOOLS.values(), "web_search", "web_read"]


def test_tool_figures_are_traced_and_never_shown_raw(rig: FinanceRig) -> None:
    rig.brain.planner = [
        tool_call("risk_report", as_of="2026-10-16"),
        answer_json(
            f"Au 16/10/2026, la volatilité est de {VOLATILITY.display} (risk_report).",
            developpement="La valeur du portefeuille est de "  # as the planner saw it
            + unicodedata.normalize("NFKC", VALUE.display)
            + " (risk_report).",
        ),
    ]
    result = rig.ask("Quelle est la volatilité de mon portefeuille ?")
    assert result.answer.statut == "complete"
    assert rig.desk.calls == [("risk_report", {"as_of": "2026-10-16"})]
    seen = rig.brain.texts("planner")
    assert unicodedata.normalize("NFKC", VOLATILITY.display) in seen  # as mark_untrusted shows it
    assert "0.1234" not in seen
    [output] = result.tool_outputs
    assert (output.call, output.tool) == ("risk_report#1", "risk_report")
    verification = rig.payload()["verification"]
    assert verification["numbers_checked"] == verification["numbers_traced"] == 2
    origins = [row["origin"] for row in verification["trace"]]
    assert "risk_report#1 › mesures/volatilite" in origins
    assert "risk_report#1 › valeurs/totale" in origins
    assert "risk_report#1" in origins  # the date


def test_a_number_the_tool_did_not_give_is_not_traced(rig: FinanceRig) -> None:
    rig.brain.planner = [
        tool_call("risk_report"),
        answer_json("La volatilité est de 13,00 % (risk_report)."),
    ]
    rig.ask("Quelle est la volatilité de mon portefeuille ?")
    verification = rig.payload()["verification"]
    assert verification["numbers_checked"] == 1
    assert verification["numbers_traced"] == 0


def test_a_result_too_large_for_the_planner_is_refused(rig: FinanceRig) -> None:
    rig.desk.payload = {"lignes": ["x" * 100] * (MAX_VIEW_CHARS // 100)}
    rig.brain.planner = [tool_call("risk_report"), answer_json("Réponse sans le résultat.")]
    result = rig.ask("Quelle est la volatilité de mon portefeuille ?")
    assert "trop" not in result.answer.message
    assert "Restreins la demande" in rig.brain.texts("planner")
    assert result.tool_outputs == ()


def test_a_plugin_that_fails_to_open_is_skipped(rig: FinanceRig) -> None:
    rig.desk.failing = {"finance_risk"}
    rig.brain.planner = [answer_json("Réponse sans l'outil de risque.")]
    result = rig.ask("Quel est le risque de mon portefeuille ?")
    assert "risk_report" not in rig.brain.bound["planner"]
    assert len(rig.brain.bound["planner"]) == len(FINANCE_TOOLS) - 1
    assert any("Outil finance_risk indisponible" in note for note in result.answer.signalements)
    assert rig.payload()["route"]["skipped"] == ["finance_risk"]


def test_a_domain_without_a_pack_falls_back_to_generaliste(rig: FinanceRig) -> None:
    rig.brain.route = {**FINANCE_ROUTE, "domaine": "juridique_fr"}
    rig.brain.planner = [answer_json("Réponse générale.")]
    result = rig.ask("Que dit le code civil ?")
    route = rig.payload()["route"]
    assert (route["domain"], route["requested_domain"]) == ("generaliste", "juridique_fr")
    assert rig.desk.opened == []
    assert any("n'existe pas encore" in note for note in result.answer.signalements)
    assert PROMPTS.roles["generaliste"] in planner_system(rig)


# --- the kill switch (R4) ----------------------------------------------------------------------


def _engage(root: Path) -> Callable[[], None]:
    def engage() -> None:
        kill = root / KILL_SWITCH_FILE
        kill.parent.mkdir(parents=True, exist_ok=True)
        kill.write_text("arrêt", encoding="utf-8")

    return engage


def test_a_kill_switch_engaged_mid_request_stops_before_the_next_model_call(
    rig: FinanceRig, tmp_path: Path
) -> None:
    rig.desk.on_call = _engage(tmp_path)  # Lucas engages it while the tool runs
    rig.brain.planner = [tool_call("risk_report"), answer_json("Jamais produite.")]
    result = rig.ask("Quelle est la volatilité de mon portefeuille ?")
    assert result.answer.statut == "refus"
    assert result.answer.message == KILL_MESSAGE
    assert rig.brain.roles().count("planner") == 1
    assert len(rig.brain.planner) == 1  # the final answer was never asked for
    assert sorted(rig.desk.closed) == sorted(FINANCE_TOOLS)
    [entry] = rig.decisions()
    payload = entry["payload"]
    assert (payload["status"], payload["halted"]) == ("refus", "kill_switch")
    assert payload["policy"]["decision"] != "auto"
    assert payload["route"]["domain"] == "finance"
    assert len(payload["cost"]["llm_calls"]) == 3  # guard, route, the planner's first turn
    assert rig.entries("ERROR") == []


def test_a_kill_switch_engaged_before_the_route_stops_the_request(
    rig: FinanceRig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engage = _engage(tmp_path)
    reply = rig.brain.reply

    def after_guard(role: str, messages: Any) -> Any:
        answer = reply(role, messages)
        engage()
        return answer

    monkeypatch.setattr(rig.brain, "reply", after_guard)
    result = rig.ask("Quel est le risque de mon portefeuille ?")
    assert result.answer.message == KILL_MESSAGE
    assert rig.brain.roles() == ["classifier"]
    assert rig.desk.opened == []
    assert rig.payload()["halted"] == "kill_switch"
