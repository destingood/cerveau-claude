"""The committee in the graph: routing, one journal entry per role, the session file (D15, D19)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC
from pathlib import Path
from typing import Any

import pytest
import yaml
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool, StructuredTool
from typer.testing import CliRunner

from core.audit.chain import AuditJournal, verify
from core.budget.ledger import COST_KEY
from core.committee import CommitteeSpec, LimitCheck
from core.config import load_config
from core.config.loader import Config
from core.models.router import ModelRequest, ModelRouter
from core.orchestrator.answer import NOT_ADVICE
from core.orchestrator.graph import Orchestrator, RunResult
from core.orchestrator.intake import KILL_MESSAGE
from core.orchestrator.runtime import WEB_PLUGIN, RequestScope
from core.policy.engine import KILL_SWITCH_FILE
from interfaces.cli.main import app
from tests.conftest import REPO_ROOT
from tests.test_committee import CATALYST, FOLIO, MARKET, RISK, SPEC, TOOLS, act, as_json
from tests.test_committee import Brain as CommitteeBrain
from tests.test_committee import ScriptedModel as MemberModel
from tests.test_orchestrator import NOW, PROMPTS, FakePseudonymiser, World, final, opener
from tests.test_orchestrator_finance import FINANCE_TOOLS

QUESTION = "Faut-il renforcer FICT-A pour Jean Dupont ?"
DECISION_ROUTE = {
    "domaine": "finance",
    "complexite": "complexe",
    "importance": "elevee",
    "web": False,
    "mode": "comite",
    "raison": "décision sur une position",
}
runner = CliRunner()


@dataclass
class Brain(CommitteeBrain):
    """The orchestrator's roles on top of the committee's scripted members."""

    verdict: dict[str, Any] = field(
        default_factory=lambda: {"decision": "ok", "raison": "analyse d'une position"}
    )
    route: dict[str, Any] = field(default_factory=lambda: dict(DECISION_ROUTE))
    planner: list[str] = field(default_factory=list)

    def reply(self, member: str, messages: Sequence[BaseMessage]) -> Any:
        if member in self.scripts:
            return super().reply(member, messages)
        self.seen.append((member, list(messages)))
        if member == "classifier":
            first = str(messages[1].content)
            return json.dumps(
                self.verdict if first.startswith("Question à classer") else self.route
            )
        if member == "reader":
            return json.dumps({"extraits": []})
        if member == "verifier":
            return json.dumps({"factuels": []})
        return self.planner.pop(0)


def _other(as_of: str = "") -> str:
    """Outil finance."""
    return ""


TOOL_BY_NAME = {tool.name: tool for tool in TOOLS}


@dataclass
class Desk:
    opened: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)


class DeskToolbox:
    def __init__(self, desk: Desk, plugin: str, scope: RequestScope) -> None:
        name = FINANCE_TOOLS[plugin]
        tool = TOOL_BY_NAME.get(name) or StructuredTool.from_function(_other, name=name)
        self.desk, self.scope = desk, scope
        self.tools: tuple[BaseTool, ...] = (tool,)
        self.skipped: dict[str, str] = {}
        self.version = f"{plugin}@0.1.0"

    async def call(
        self, name: str, arguments: dict[str, Any], *, journaled: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        self.scope.budget.charge_tool_call()  # as the MCP adapter does
        self.desk.calls.append(name)
        return dict(MARKET if name == "market_data" else RISK)


def desk_opener(desk: Desk, plugin: str) -> Any:
    @asynccontextmanager
    async def open_toolbox(scope: RequestScope) -> AsyncIterator[DeskToolbox]:
        desk.opened.append(plugin)
        yield DeskToolbox(desk, plugin, scope)

    return open_toolbox


def _router(config: Config, brain: Brain) -> ModelRouter:
    def factory(request: ModelRequest) -> MemberModel:
        brain.requests.append(request)
        return MemberModel(
            brain=brain,
            member=request.member or request.role,
            model_id=request.model,
            callbacks=list(request.callbacks),
        )

    return ModelRouter(config, factory=factory)


@dataclass
class Rig:
    orchestrator: Orchestrator
    brain: Brain
    desk: Desk
    journal: AuditJournal
    root: Path

    def ask(self, question: str = QUESTION, *, committee: bool = False) -> RunResult:
        return asyncio.run(self.orchestrator.ask(question, request_id="req-1", committee=committee))

    def decisions(self) -> list[dict[str, Any]]:
        lines = self.journal.path.read_text(encoding="utf-8").splitlines()
        entries = [e for e in map(json.loads, lines) if e["event"] == "DECISION"]
        return [e | {"payload": self.journal.read_payload(e["payload_ref"])} for e in entries]

    def final_payload(self) -> dict[str, Any]:
        return self.decisions()[-1]["payload"]

    def session_file(self, record_id: str) -> Path:
        return self.root / "var" / "finance" / "committee" / f"{record_id}.json"

    def engage_kill_switch(self) -> None:
        kill = self.root / KILL_SWITCH_FILE
        kill.parent.mkdir(parents=True, exist_ok=True)
        kill.write_text("arrêt", encoding="utf-8")


def _config(config_dir: Path, *, committee: bool = True, **per_committee: int) -> Config:
    path = config_dir / "budgets.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["llm_budget_eur"] = {"daily": "1.00", "monthly": "10.00"}
    if committee:  # otherwise the session budget keeps the repository's markers (R7)
        limits = {"max_tokens": 400_000, "max_seconds": 600, "max_tool_calls": 40}
        data["per_committee"] = limits | per_committee
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_config(config_dir)


def make_rig(
    root: Path, config: Config, committees: Mapping[str, CommitteeSpec] | None = None
) -> Rig:
    brain, desk = Brain(), Desk()
    journal = AuditJournal(root / "audit" / "journal.jsonl")
    toolboxes = {plugin: desk_opener(desk, plugin) for plugin in FINANCE_TOOLS}
    orchestrator = Orchestrator(
        config,
        project_root=root,
        journal=journal,
        router=_router(config, brain),
        toolboxes={**toolboxes, WEB_PLUGIN: opener(World())},
        pseudonymiser=FakePseudonymiser,
        prompts=PROMPTS,
        clock=lambda: NOW,
        tz=UTC,
        committees={"finance": SPEC} if committees is None else committees,
    )
    return Rig(orchestrator, brain, desk, journal, root)


@pytest.fixture
def rig(tmp_path: Path, config_dir: Path) -> Rig:
    return make_rig(tmp_path, _config(config_dir))


def _direct(rig: Rig, **route: Any) -> None:
    """A simple route whose planner answers at once, without a tool."""
    rig.brain.route = DECISION_ROUTE | {"complexite": "simple", "importance": "normale"} | route
    rig.brain.planner = [
        final(
            synthese="Une réponse directe, sans le Comité.",
            developpement="Aucune source n'est nécessaire ici.",
            confiance={"niveau": "faible", "justification": "Réponse générale."},
            prochaines_etapes=["Reformuler la question si besoin."],
        )
    ]


# --- routing (D15) -----------------------------------------------------------------------------


def test_a_decision_question_convenes_the_committee(rig: Rig) -> None:
    result = rig.ask()
    answer = result.answer
    assert answer.statut == "complete"
    assert answer.synthese == "Attendre avant de renforcer FICT-A"
    assert answer.comite is not None
    assert (answer.comite.libelle, answer.comite.decision) == ("analyse", "attendre")
    assert answer.comite.invalidation == ("Un cours sous 102,50 EUR (C1)",)
    assert answer.comite.desaccords == ("le poids du stress",)
    assert answer.comite.verdict == "OK"
    assert NOT_ADVICE in answer.signalements
    assert answer.prochaines_etapes == (
        f"Relire la séance complète : `cerveau committee show {answer.comite.record_id}`.",
    )
    assert "planner" not in rig.brain.members() and "planner_complex" not in rig.brain.members()
    markdown = result.markdown()
    assert "## Décision du Comité (analyse)" in markdown
    assert "- Décision proposée : attendre" in markdown
    assert "- Désaccords non résolus :\n  - le poids du stress" in markdown
    assert result.tool_outputs and result.tool_calls == len(rig.desk.calls) == 3


def test_the_comite_flag_convenes_the_committee(rig: Rig) -> None:
    rig.brain.route = DECISION_ROUTE | {"mode": "direct"}
    answer = rig.ask(committee=True).answer
    assert answer.comite is not None and answer.comite.decision == "attendre"
    assert rig.final_payload()["route"]["mode"] == "comite"


def test_a_measure_question_stays_direct(rig: Rig) -> None:
    _direct(rig, mode="direct")
    answer = rig.ask("Quelle est ma VaR ?").answer
    assert answer.comite is None
    assert "gestionnaire" not in rig.brain.members()
    assert rig.final_payload()["route"]["mode"] == "direct"
    assert not (rig.root / "var" / "finance" / "committee").exists()


def test_a_pack_without_a_committee_answers_directly_with_a_note(rig: Rig) -> None:
    _direct(rig, domaine="generaliste")
    answer = rig.ask("Faut-il changer de fournisseur d'électricité ?").answer
    assert answer.comite is None and answer.statut != "refus"
    assert (
        "Le routage demande le Comité, mais le pack « generaliste » n'en a pas : réponse directe."
        in answer.signalements
    )
    assert rig.final_payload()["route"]["mode"] == "direct"


def test_the_comite_flag_on_a_pack_without_a_committee_is_refused(rig: Rig) -> None:
    _direct(rig, domaine="generaliste", mode="direct")
    answer = rig.ask("Faut-il changer de fournisseur ?", committee=True).answer
    assert answer.statut == "refus"
    assert answer.message == "Comité demandé, mais le pack « generaliste » n'a pas de Comité"
    assert rig.brain.planner  # never planned


def test_a_marked_committee_budget_refuses_before_any_tool(
    tmp_path: Path, config_dir: Path
) -> None:
    rig = make_rig(tmp_path, _config(config_dir, committee=False))
    answer = rig.ask().answer
    assert answer.statut == "refus"
    assert answer.message.startswith("Comité bloqué (R7) : ")
    assert "A_DEFINIR" in answer.message
    assert rig.desk.opened == [] and "gestionnaire" not in rig.brain.members()
    assert rig.brain.planner == []  # not answered by the planner alone either


def test_the_repository_committee_is_its_registered_agent() -> None:
    config = load_config(REPO_ROOT / "config")
    orchestrator = Orchestrator(config, project_root=REPO_ROOT, prompts=PROMPTS)
    spec = orchestrator.committee_spec("finance")
    assert spec is not None
    assert (spec.pack, spec.feature) == ("finance", "finance.committee")
    assert orchestrator.committee_spec("finance") is spec  # loaded once
    assert orchestrator.committee_spec("generaliste") is None


# --- the journal and the session file (D19) ----------------------------------------------------


def test_every_role_is_journaled_before_the_decision(rig: Rig) -> None:
    answer = rig.ask().answer
    assert answer.comite is not None
    *roles, last = rig.decisions()
    final_payload = last["payload"]
    committee = final_payload["committee"]
    assert committee["roles"] == len(roles) == 8
    assert final_payload["route"]["mode"] == "comite"
    assert COST_KEY in final_payload
    for entry in roles:
        assert entry["actor"] == "orchestrator" and entry["request_id"] == "req-1"
        role = entry["payload"]["committee"]
        assert role["version"] == "test@1"
        assert role["committee_record_id"] == answer.comite.record_id
        assert role["pack"] == "finance"
        assert role["file_sha256"] == committee["file_sha256"]
        assert COST_KEY not in entry["payload"]  # the request's entry carries the cost
    members = [entry["payload"]["committee"]["member"] for entry in roles]
    assert members[:2] == ["analyste_technique", "analyste_portefeuille"]
    assert members[-2:] == ["gestionnaire", "controleur_risque"]
    assert verify(rig.journal.path).ok


def test_the_session_file_matches_its_digest_and_is_pseudonymised(rig: Rig) -> None:
    answer = rig.ask().answer
    assert answer.comite is not None
    path = rig.session_file(answer.comite.record_id)
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == rig.final_payload()["committee"]["file_sha256"]
    record = json.loads(data)
    assert record["question"] == "Faut-il renforcer FICT-A pour <PERSON_1> ?"
    assert "Jean Dupont" not in data.decode("utf-8")
    assert "Jean Dupont" not in rig.journal.path.read_text(encoding="utf-8")


def test_no_finding_gives_no_decision(rig: Rig) -> None:
    empty = as_json({"constats": [], "incertitudes": ["aucune donnée"]})
    rig.brain.scripts["analyste_technique"] = [empty]
    rig.brain.scripts["analyste_portefeuille"] = [empty]
    result = rig.ask()
    answer = result.answer
    assert answer.statut == "partielle"
    assert answer.synthese.startswith("Pas de décision")
    assert answer.message == "Pas de décision : aucun constat des analystes : rien à débattre."
    assert answer.comite is not None and answer.comite.decision is None
    assert "- Décision proposée : pas de décision" in result.markdown()
    assert rig.final_payload()["committee"]["status"] == "echec"


def test_an_exceeded_session_budget_gives_no_decision(tmp_path: Path, config_dir: Path) -> None:
    rig = make_rig(tmp_path, _config(config_dir, max_tool_calls=1))
    answer = rig.ask().answer
    assert answer.statut == "partielle"
    assert answer.message == (
        "Pas de décision : la séance a atteint le nombre maximal d'appels d'outils de son budget."
    )


def test_the_kill_switch_mid_session_halts_the_request(rig: Rig) -> None:
    def last_words() -> str:
        rig.engage_kill_switch()
        return FOLIO

    rig.brain.scripts["analyste_portefeuille"][1] = last_words
    answer = rig.ask().answer
    assert (answer.statut, answer.message) == ("refus", KILL_MESSAGE)
    payload = rig.final_payload()
    assert payload["halted"] == "kill_switch"
    assert (payload["committee"]["status"], payload["committee"]["reason"]) == (
        "incomplete",
        "kill_switch",
    )
    assert "gestionnaire" not in rig.brain.members()
    assert verify(rig.journal.path).ok


# --- cerveau committee show --------------------------------------------------------------------


def _show(rig: Rig, record_id: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("CERVEAU_HOME", str(rig.root))
    args = ["committee", "show", record_id, "--journal", str(rig.journal.path)]
    return runner.invoke(app, args)


def test_show_reads_an_intact_session(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    answer = rig.ask().answer
    assert answer.comite is not None
    result = _show(rig, answer.comite.record_id, monkeypatch)
    assert result.exit_code == 0, result.output
    assert "Décision proposée : attendre — Attendre avant de renforcer FICT-A" in result.stdout
    assert "Question (pseudonymisée) : Faut-il renforcer FICT-A pour <PERSON_1> ?" in result.stdout
    assert "Verdict des contrôles : OK" in result.stdout
    assert "intact (empreinte SHA-256 conforme au journal)" in result.stdout


def test_a_decision_to_act_shows_its_catalyst(
    tmp_path: Path, config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-029: what makes the action timely is shown in the answer and in the session file."""
    checks = (LimitCheck("poids_max", True, "sous la limite"),)
    spec = replace(SPEC, limit_checks=lambda decision, outputs: checks)
    rig = make_rig(tmp_path, _config(config_dir), {"finance": spec})
    rig.brain.scripts["gestionnaire"] = [act(CATALYST)]
    result = rig.ask()
    view = result.answer.comite
    assert view is not None and view.decision == "agir"
    assert view.catalyseur == "Le stress reste borné (C2)"
    lines = result.markdown().splitlines()
    decided = lines.index("- Décision proposée : agir")
    assert lines[decided + 1] == "- Catalyseur : Le stress reste borné (C2)"
    shown = _show(rig, view.record_id, monkeypatch)
    assert shown.exit_code == 0, shown.output
    assert "Catalyseur : Le stress reste borné (C2)" in shown.stdout


def test_a_decision_without_a_catalyst_shows_none(rig: Rig) -> None:
    result = rig.ask()
    assert result.answer.comite is not None and result.answer.comite.catalyseur is None
    assert "Catalyseur" not in result.markdown()


def test_show_reports_an_altered_session(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    answer = rig.ask().answer
    assert answer.comite is not None
    path = rig.session_file(answer.comite.record_id)
    path.write_text(path.read_text(encoding="utf-8").replace("attendre", "agir"), "utf-8")
    result = _show(rig, answer.comite.record_id, monkeypatch)
    assert result.exit_code == 1
    assert "altéré" in result.stderr and "Ne pas s'y fier" in result.stderr
    assert "agir" not in result.stdout


def test_show_refuses_a_broken_audit_chain(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """B149: the session's digest is only as good as the chain that holds it."""
    answer = rig.ask().answer
    assert answer.comite is not None
    lines = rig.journal.path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["ts"] = "2000-01-01T00:00:00+00:00"
    lines[0] = json.dumps(first, ensure_ascii=False)
    rig.journal.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = _show(rig, answer.comite.record_id, monkeypatch)
    assert result.exit_code == 1
    assert "Journal d'audit invalide (chaîne rompue)" in result.stderr
    assert "Décision proposée" not in result.stdout


def test_show_reports_a_missing_session(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    answer = rig.ask().answer
    assert answer.comite is not None
    rig.session_file(answer.comite.record_id).unlink()
    result = _show(rig, answer.comite.record_id, monkeypatch)
    assert result.exit_code == 1 and "introuvable" in result.stderr


@pytest.mark.parametrize(
    ("record_id", "message"),
    [
        ("00000000-0000-4000-8000-000000000000", "inconnue du journal"),
        ("../../audit/journal", "Identifiant de séance invalide"),
    ],
)
def test_show_refuses_an_unknown_or_invalid_id(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, record_id: str, message: str
) -> None:
    rig.ask()
    result = _show(rig, record_id, monkeypatch)
    assert result.exit_code == 1 and message in result.stderr
