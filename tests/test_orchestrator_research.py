"""The deep research in the graph: route, research, check, output and audit (ADR-045, D14, D15)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC
from pathlib import Path
from typing import Any

import pytest
import yaml
from langchain_core.messages import BaseMessage

from core.audit.chain import AuditJournal, verify
from core.config import load_config
from core.config.loader import Config
from core.models.router import ModelRequest, ModelRouter
from core.orchestrator.answer import MASKED_UNVERIFIED, UNVERIFIED, research_notes
from core.orchestrator.graph import Orchestrator, RunResult, research_file
from core.orchestrator.intake import KILL_MESSAGE
from core.orchestrator.packs import Pack, PackAgent, experimental_note, load_packs
from core.orchestrator.planner import LIMIT_TEXT
from core.orchestrator.runtime import WEB_PLUGIN, RequestScope
from core.orchestrator.state import ResearchOutcome
from core.policy.engine import KILL_SWITCH_FILE
from core.research import ResearchSpec
from plugins.deep_research.agent import deep_research
from tests.test_orchestrator import NOW, PROMPTS, FakePseudonymiser, final
from tests.test_research import (
    ARTICLE,
    INJECTION,
    NO_ABSTRACT,
    PLAN,
    PREPRINT,
    PREPRINT_ABSTRACT,
    QUESTION,
    READINGS,
    REPORT,
    RETRACTED,
    SPEC,
    A,
    B,
    Brain,
    C,
    FakeWeb,
    ScriptedModel,
    as_json,
    reader,
)

ROUTE = {
    "domaine": "generaliste",
    "complexite": "simple",
    "importance": "normale",
    "web": False,
    "raison": "état des connaissances",
}
VERDICT = {"decision": "ok", "raison": "question de recherche"}
# The Recherche pack as its manifest will declare it, on the web plugin only (ADR-043).
RECHERCHE = Pack(
    id="recherche",
    statut="experimental",
    plugins=(WEB_PLUGIN,),
    agent=PackAgent(plugin="deep_research", mode="approfondi"),
)
SPECS: Mapping[str, ResearchSpec] = {"recherche": SPEC}
# Its role.md arrives with its manifest; the planner of a direct route needs one.
ROLES = replace(PROMPTS, roles={**PROMPTS.roles, "recherche": "Tu réponds en chercheur."})


def no_fact(messages: Sequence[BaseMessage]) -> str:
    return as_json({"factuels": []})


def web_opener(webs: list[FakeWeb]) -> Any:
    @asynccontextmanager
    async def open_toolbox(scope: RequestScope) -> AsyncIterator[FakeWeb]:
        web = FakeWeb(
            scope.budget,  # the research's, once the route has replaced the request's
            results={"sommeil mémoire": [A, B], "sommeil mémoire limites": [C, A]},
            records={"sleep memory consolidation": [ARTICLE, RETRACTED, NO_ABSTRACT, PREPRINT]},
        )
        webs.append(web)
        yield web

    return open_toolbox


@dataclass
class Rig:
    orchestrator: Orchestrator
    brain: Brain
    webs: list[FakeWeb]
    journal: AuditJournal
    root: Path
    route: dict[str, Any]

    def ask(self, question: str = QUESTION, **flags: bool) -> RunResult:
        return asyncio.run(self.orchestrator.ask(question, request_id="req-1", **flags))

    def decision(self) -> dict[str, Any]:
        lines = self.journal.path.read_text(encoding="utf-8").splitlines()
        [entry] = [e for e in map(json.loads, lines) if e["event"] == "DECISION"]
        return self.journal.read_payload(entry["payload_ref"])

    def raw(self) -> str:
        """The journal and its payload files, as written on disk."""
        files = [self.journal.path, *sorted(self.journal.payload_dir.glob("*.json"))]
        return "\n".join(path.read_text(encoding="utf-8") for path in files)

    def engage_kill_switch(self) -> None:
        kill = self.root / KILL_SWITCH_FILE
        kill.parent.mkdir(parents=True, exist_ok=True)
        kill.write_text("arrêt", encoding="utf-8")


def _config(config_dir: Path, *, research: bool = True, **limits: int) -> Config:
    path = config_dir / "budgets.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["llm_budget_eur"] = {"daily": "1.00", "monthly": "10.00"}
    if research:  # otherwise the research budget keeps the repository's markers (R7)
        defaults = {"max_tokens": 400_000, "max_seconds": 600, "max_tool_calls": 40}
        data["per_deep_research"] = data["per_deep_research"] | defaults | limits
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_config(config_dir)


def make_rig(
    root: Path,
    config: Config,
    *,
    packs: Mapping[str, Pack] | None = None,
    researches: Mapping[str, ResearchSpec] | None = SPECS,  # None: the packs' agents
) -> Rig:
    route = dict(ROUTE)

    def classifier(messages: Sequence[BaseMessage]) -> str:
        first = str(messages[1].content)
        return as_json(VERDICT if first.startswith("Question à classer") else route)

    brain = Brain(
        {
            "classifier": classifier,
            "verifier": no_fact,
            "reader": reader(READINGS),
            "planner": [PLAN],
            "planner_complex": [REPORT],
        }
    )

    def factory(request: ModelRequest) -> ScriptedModel:
        return ScriptedModel(
            brain=brain, role=request.role, model_id=request.model, callbacks=request.callbacks
        )

    webs: list[FakeWeb] = []
    journal = AuditJournal(root / "audit" / "journal.jsonl")
    orchestrator = Orchestrator(
        config,
        project_root=root,
        journal=journal,
        router=ModelRouter(config, factory=factory),
        toolboxes={WEB_PLUGIN: web_opener(webs)},
        packs={**load_packs(), "recherche": RECHERCHE} if packs is None else packs,
        pseudonymiser=FakePseudonymiser,
        prompts=ROLES,
        clock=lambda: NOW,
        tz=UTC,
        researches=researches,
    )
    return Rig(orchestrator, brain, webs, journal, root, route)


@pytest.fixture
def rig(tmp_path: Path, config_dir: Path) -> Rig:
    return make_rig(tmp_path, _config(config_dir))


# --- a deep research, end to end ---------------------------------------------------------------


def test_approfondi_runs_the_research_of_the_pack_that_has_one(rig: Rig) -> None:
    rig.ask(research=True)
    route = rig.decision()["route"]
    assert (route["domain"], route["requested_domain"]) == ("recherche", "recherche")
    assert (route["mode"], route["role"], route["needs_web"]) == (
        "approfondi",
        "planner_complex",
        True,
    )
    assert route["tools"] == ["web_search", "web_read", "scholar_search"]
    assert rig.brain.roles().count("planner") == 1  # the plan, never the planner's loop
    assert rig.brain.roles().count("planner_complex") == 1  # the writing


def test_the_answer_keeps_the_verified_claims_and_lists_the_others(rig: Rig) -> None:
    result = rig.ask(research=True)
    answer = result.answer
    assert answer.synthese == "Le sommeil consolide la mémoire [1, 3]."
    assert answer.contre_arguments == "La privation réduit l'attention [4]."
    assert answer.non_verifies == (
        "Un gain de 25 % est observé. — chiffre « 25 % » absent des extraits cités",
        "Sans appui. — aucun extrait vérifié cité",
    )
    markdown = result.markdown()
    unverified = markdown.split(f"**{UNVERIFIED}**")[1].split("**Signalements**")[0]
    assert "- Un gain de 25 % est observé. — chiffre « 25 % » absent" in unverified
    assert "- Sans appui. — aucun extrait vérifié cité" in unverified
    assert "Notice 10.1000/abc — https://doi.org/10.1000/abc (article publié ;" in markdown
    assert "(préprint, sans relecture par les pairs annoncée ;" in markdown
    assert "un gain de 25 %" not in markdown.split("**Sources**")[0].lower()


def test_a_removed_claim_phrased_as_an_instruction_is_masked(rig: Rig) -> None:
    report = json.loads(REPORT)
    report["synthese"].append({"texte": INJECTION, "extraits": []})
    rig.brain.scripts["planner_complex"] = [as_json(report)]
    result = rig.ask(research=True)
    assert MASKED_UNVERIFIED in result.answer.non_verifies
    assert INJECTION not in result.markdown()


def test_the_signals_say_what_the_research_planned_skipped_and_removed(rig: Rig) -> None:
    notes = rig.ask(research=True).answer.signalements
    record_id = rig.decision()["research"]["research_record_id"]
    assert notes[0] == experimental_note("recherche")
    assert (
        f"Recherche approfondie {record_id} : 2 sous-question(s), 3 recherche(s), 5 lecture(s)."
        in notes
    )
    expected = [
        "1 publication(s) trouvée(s) sans résumé : non lue(s), donc non citée(s) (D12).",
        "1 publication(s) rétractée(s), retirée(s) ou supprimée(s) : jamais citée(s).",
        "Source [3] : correction : mise à jour publiée de la notice, à lire avant de s'y fier.",
        "2 affirmation(s) retirée(s) de la réponse : aucun extrait vérifié ne la fondait (D15). "
        f"Voir « {UNVERIFIED} ».",
    ]
    assert all(note in notes for note in expected)
    assert not any("sous-question(s) du plan écartée(s)" in note for note in notes)
    assert not any("appel(s) d'outil en échec" in note for note in notes)


def test_the_decision_entry_cites_the_research_file_by_its_digest(rig: Rig) -> None:
    rig.ask(research=True)
    payload = rig.decision()
    research = payload["research"]
    path = research_file(rig.root, "recherche", research["research_record_id"])
    assert research["file_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    counts = {key: value for key, value in research.items() if key != "research_record_id"}
    assert counts == {
        "pack": "recherche",
        "version": "test@1",
        "halted": False,
        "sub_questions": 2,
        "sub_questions_cut": 0,
        "searches": 3,
        "reads": 5,
        "without_abstract": 1,
        "retracted": 1,
        "updated": 1,
        "tool_errors": 0,
        "removed": 2,
        "file_sha256": research["file_sha256"],
    }
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["record_id"] == research["research_record_id"]
    assert PREPRINT_ABSTRACT not in path.read_text(encoding="utf-8")  # its extract only
    raw = rig.raw()
    assert QUESTION not in raw and A not in raw and PREPRINT_ABSTRACT not in raw
    assert verify(rig.journal.path).ok


def test_the_research_budget_replaces_the_request_s(tmp_path: Path, config_dir: Path) -> None:
    rig = make_rig(tmp_path, _config(config_dir, max_tool_calls=4))
    result = rig.ask(research=True)
    answer = result.answer
    assert answer.message.startswith(
        f"Réponse partielle : la requête a atteint {LIMIT_TEXT['tool_calls']} (4)."
    )
    assert result.tool_calls == 4
    [web] = rig.webs
    assert len(web.calls) == 4
    assert rig.decision()["research"]["halted"] is False


# --- what the router and the flags may do ------------------------------------------------------


def test_the_router_never_starts_the_deep_research(rig: Rig) -> None:
    rig.route["domaine"] = "recherche"
    direct = final(synthese="Une réponse directe.", developpement="Sans source lue.")
    rig.brain.scripts["planner"] = [direct]
    rig.ask()
    payload = rig.decision()
    assert (payload["route"]["domain"], payload["route"]["mode"]) == ("recherche", "direct")
    assert "research" not in payload
    assert not (rig.root / "var" / "recherche" / "approfondi").exists()


def test_committee_and_research_exclude_each_other(rig: Rig) -> None:
    with pytest.raises(ValueError, match="--comite et --approfondi s'excluent"):
        rig.ask(committee=True, research=True)
    assert rig.brain.seen == [] and rig.webs == []


@pytest.mark.parametrize(
    ("research", "specs", "reason"),
    [
        (
            True,
            {},
            "Recherche approfondie demandée, mais le pack « generaliste » n'en a pas",
        ),
        (False, SPECS, "Recherche approfondie bloquée (R7) : "),
        (
            False,
            {"generaliste": replace(SPEC, feature="llm.fast")},  # its budget still has markers
            "Recherche approfondie bloquée (R7) : per_deep_research non défini : recherche "
            "bloquée (R7)",
        ),
    ],
    ids=["no-research", "feature-blocked", "budget-undefined"],
)
def test_a_research_that_cannot_run_is_refused_before_any_tool(
    tmp_path: Path,
    config_dir: Path,
    research: bool,
    specs: Mapping[str, ResearchSpec],
    reason: str,
) -> None:
    packs = load_packs() if "recherche" not in specs else None  # the repository's: no research
    rig = make_rig(tmp_path, _config(config_dir, research=research), packs=packs, researches=specs)
    answer = rig.ask(research=True).answer
    assert answer.statut == "refus" and answer.message.startswith(reason)
    if specs is SPECS:
        assert "per_deep_research" in answer.message
    assert rig.webs == [] and "planner" not in rig.brain.roles()
    payload = rig.decision()
    assert payload["route"]["mode"] == "direct" and "research" not in payload


# --- the kill switch and the specs -------------------------------------------------------------


def test_the_kill_switch_mid_research_halts_the_request(rig: Rig) -> None:
    def reading_then_halt(messages: Sequence[BaseMessage]) -> str:
        rig.engage_kill_switch()
        return reader(READINGS)(messages)

    rig.brain.scripts["reader"] = reading_then_halt
    answer = rig.ask(research=True).answer
    assert (answer.statut, answer.message) == ("refus", KILL_MESSAGE)
    payload = rig.decision()
    assert payload["halted"] == "kill_switch"
    research = payload["research"]
    assert research["halted"] is True and research["reads"] == 1
    path = research_file(rig.root, "recherche", research["research_record_id"])
    assert research["file_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert "planner_complex" not in rig.brain.roles()
    assert verify(rig.journal.path).ok


def test_the_pack_agent_gives_the_research_once(tmp_path: Path, config_dir: Path) -> None:
    config = _config(config_dir)
    orchestrator = make_rig(tmp_path, config, researches=None).orchestrator
    spec = orchestrator.research_spec("recherche")
    assert spec == deep_research(config)
    assert orchestrator.research_spec("recherche") is spec
    assert orchestrator.research_spec("finance") is None  # a committee, not a research
    assert orchestrator.research_spec("inconnu") is None


def test_the_research_node_refuses_a_pack_without_research(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = iter([SPEC, None])  # the route saw one, the node none
    monkeypatch.setattr(rig.orchestrator, "research_spec", lambda pack_id: next(specs))
    with pytest.raises(
        RuntimeError, match="aucune recherche approfondie pour le pack « recherche »"
    ):
        rig.ask(research=True)
    payload = rig.decision()
    assert (payload["status"], payload["error"]) == ("erreur", "RuntimeError")
    assert rig.webs != [] and rig.brain.roles().count("planner") == 0


def test_the_notes_count_the_cut_plan_and_the_failed_tools() -> None:
    outcome = ResearchOutcome(
        record_id="rch-9",
        pack="recherche",
        version="test@1",
        sub_questions=("Q1 ?",),
        sub_questions_cut=2,
        searches=1,
        tool_errors=3,
        file="var/recherche/approfondi/rch-9.json",
        file_sha256="0" * 64,
    )
    assert research_notes(outcome) == [
        "Recherche approfondie rch-9 : 1 sous-question(s), 1 recherche(s), 0 lecture(s).",
        "2 sous-question(s) du plan écartée(s) au-delà du maximum.",
        "3 appel(s) d'outil en échec pendant la recherche.",
    ]
