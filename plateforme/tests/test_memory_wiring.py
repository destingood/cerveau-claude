"""The memory's configuration, its command and node 1 « Contexte » (plan step B2, ADR-072).

The orchestrator does not run at 0 € of API; these tests drive it with scripted models to show
the path of the memory snippets into the planner's system prompt and into the journal.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from core.config import ConfigError, load_config
from core.memory import BrainMemory
from core.policy.engine import KILL_SWITCH_FILE
from interfaces.cli.main import app, build_orchestrator
from tests.conftest import REPO_ROOT
from tests.test_memory import FINANCE, PERSO_FACT, PREFERENCE, node, write_brain
from tests.test_orchestrator import Brain, _config, _read_insee, make_rig

runner = CliRunner()


def edit_memory(config_dir: Path, **changes: Any) -> None:
    path = config_dir / "memory.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


# --- config/memory.yaml --------------------------------------------------------------------------


def test_the_repository_memory_settings_are_prudent() -> None:
    memory = load_config(REPO_ROOT / "config").memory
    assert memory.enabled and memory.brain_home is None
    assert memory.min_confidence == "moyen"
    assert memory.preference_types == ["feedback"]
    assert memory.packs == {
        "generaliste": [],
        "finance": ["finance"],
        "recherche": ["recherche"],
        "code": ["code", "infra"],
        "cyber": ["infra"],
        "juridique_fr": [],
        "business": ["business", "contenu"],
    }
    assert not any("perso" in domains for domains in memory.packs.values())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"packs": {"finance": ["finance", "perso"]}}, "« perso » n'est lu que sur demande"),
        ({"packs": {"astrologie": []}}, "packs.astrologie : pack inconnu"),
        ({"packs": {"code": ["cuisine"]}}, "domaines inconnus du plugin"),
        ({"preference_types": ["feedback", "humeur"]}, "types inconnus du plugin"),
        ({"brain_home": "  "}, "chemin vide"),
        ({"top_k": 0}, "top_k"),
        ({"min_confidence": "nulle"}, "min_confidence"),
        ({"secret": "x"}, "secret"),
    ],
)
def test_memory_yaml_is_validated(config_dir: Path, changes: dict[str, Any], message: str) -> None:
    edit_memory(config_dir, **changes)
    with pytest.raises(ConfigError, match=message):
        load_config(config_dir)


def test_config_check_reports_the_memory(
    config_dir: Path, tmp_path: Path, monkeypatch: Any
) -> None:
    write_brain(tmp_path / "cerveau", [FINANCE, PREFERENCE, node("vieux", "x", status="archived")])
    monkeypatch.setenv("BRAIN_HOME", str(tmp_path / "cerveau"))
    result = runner.invoke(app, ["config", "check", "--config-dir", str(config_dir)])
    assert result.exit_code == 0, result.output
    assert "\nMémoire (ADR-072) :\n" in result.stdout
    assert "    mode classique : 2 souvenir(s) lisible(s)\n" in result.stdout
    assert "    écartés : 1 archivé\n" in result.stdout
    assert "  · cyber : domaines infra, plus les préférences générales\n" in result.stdout
    monkeypatch.setenv("BRAIN_HOME", str(tmp_path / "rien"))
    result = runner.invoke(app, ["config", "check", "--config-dir", str(config_dir)])
    assert "aucun souvenir lu : cerveau du plugin introuvable (pas de graph.json)" in result.stdout


# --- cerveau memoire chercher --------------------------------------------------------------------


def test_the_command_shows_what_a_pack_would_read(tmp_path: Path, monkeypatch: Any) -> None:
    secret = "sk-ant-" + "x" * 24
    dated = node(
        "plafond",
        "Plafond des ETF",
        f"20 % au plus.\nJeton {secret}",
        meta={"domaine": "finance", "valid_to": "2099-12-31"},
    )
    write_brain(tmp_path, [dated, PREFERENCE, PERSO_FACT])
    monkeypatch.setenv("BRAIN_HOME", str(tmp_path))
    result = runner.invoke(app, ["memoire", "chercher", "plafond ETF", "--domaine", "finance"])
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert f"Cerveau du plugin : {tmp_path} (lecture seule)" in out
    assert "Pack finance : domaines finance, plus les préférences générales" in out
    assert "  hors du périmètre du pack : 1" in out  # the perso memory
    assert "2 souvenir(s) rendu(s), marqués comme données (R5) :" in out
    assert (
        "- [plafond] fait · domaine finance · source utilisateur · confiance élevée · "
        "date 2026-11-02 · expire le 2099-12-31 · score "
    ) in out
    assert "(1 secret(s) masqué(s))" in out and secret not in out
    assert "    Plafond des ETF\n    20 % au plus.\n    Jeton [MASQUÉ]" in out
    assert "- [reponses-courtes] règle · domaine préférence générale" in out
    assert "PEA des enfants" not in out
    perso = runner.invoke(app, ["memoire", "chercher", "PEA enfants", "--perso"])
    assert "Pack generaliste : domaines perso" in perso.stdout
    assert "PEA des enfants" in perso.stdout


def test_the_command_says_why_nothing_is_read(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("BRAIN_HOME", str(tmp_path / "rien"))
    missing = runner.invoke(app, ["memoire", "chercher", "ETF"])
    assert missing.exit_code == 0
    assert "aucun souvenir lu : cerveau du plugin introuvable" in missing.stdout
    assert "rendu" not in missing.stdout
    write_brain(tmp_path, [FINANCE])
    monkeypatch.setenv("BRAIN_HOME", str(tmp_path))
    none = runner.invoke(app, ["memoire", "chercher", "météo", "--domaine", "finance"])
    assert "Aucun souvenir rendu pour ce texte." in none.stdout
    unknown = runner.invoke(app, ["memoire", "chercher", "ETF", "--domaine", "astrologie"])
    assert unknown.exit_code == 1
    assert "Pack inconnu : astrologie" in unknown.output


# --- node 1 « Contexte » and node 3 (routing) ----------------------------------------------------


def test_cerveau_ask_gives_the_orchestrator_the_brain(tmp_path: Path, monkeypatch: Any) -> None:
    """Only `cerveau ask` hands a brain to the orchestrator; evals and tests go without one."""
    monkeypatch.setenv("BRAIN_HOME", str(tmp_path))
    orchestrator = build_orchestrator(load_config(REPO_ROOT / "config"), tmp_path)
    assert isinstance(orchestrator.memory, BrainMemory)
    assert orchestrator.memory.home == tmp_path


def _system_prompt(brain: Brain) -> str:
    [system] = [str(m[0].content) for role, m in brain.seen if role.startswith("planner")][:1]
    return system


def test_the_routed_packs_memories_reach_the_planner_as_data(
    tmp_path: Path, config_dir: Path
) -> None:
    edit_memory(config_dir, packs={"generaliste": ["recherche"]})
    config = _config(config_dir)
    home = tmp_path / "cerveau"
    research = node(
        "insee",
        "Source préférée sur la population",
        "Jean Dupont lit l'Insee en premier.",
        meta={"domaine": "recherche"},
    )
    flagged = node(
        "piege", "Population", "Note.", meta={"domaine": "recherche", "a_verifier": ["x"]}
    )
    memories = [research, flagged, PREFERENCE, PERSO_FACT, FINANCE]
    # The rig's clock reads 2026-10-18: every memory starts before it.
    write_brain(home, [n | {"created": "2026-09-01T09:00:00"} for n in memories])
    rig = make_rig(tmp_path / "projet", config)
    rig.orchestrator.memory = BrainMemory(config.memory, env={"BRAIN_HOME": str(home)})
    _read_insee(rig)
    rig.ask("Quelle est la population de la France ?")
    system = _system_prompt(rig.brain)
    assert "2 souvenir(s) du plugin « cerveau », lus en lecture seule" in system
    assert system.count('<donnees_externes source="cerveau · ') == 2
    assert "<PERSON_1> lit l'Insee en premier." in system  # pseudonymised like the question
    assert "Jean Dupont" not in system
    assert "Je préfère des réponses courtes." in system
    for absent in ("PEA des enfants", "Note.", "20 % du portefeuille"):
        assert absent not in system  # perso, set aside, another pack's domain
    assert rig.payload()["memory"] == {"mode": "classique", "read": 4, "given": 2}
    assert "Jean Dupont" not in rig.raw() and "Insee en premier" not in rig.raw()


def test_without_a_brain_the_planner_is_told_there_is_none(
    tmp_path: Path, config_dir: Path
) -> None:
    config = _config(config_dir)
    rig = make_rig(tmp_path, config)
    rig.orchestrator.memory = BrainMemory(config.memory, env={"BRAIN_HOME": str(tmp_path / "x")})
    _read_insee(rig)
    rig.ask("Quelle est la population de la France ?")
    assert (
        "Mémoire pertinente (faits validés, avec source et date) : aucune (cerveau du plugin "
        "introuvable (pas de graph.json))"
    ) in _system_prompt(rig.brain)
    assert rig.payload()["memory"] == {"mode": "absent", "read": 0, "given": 0}


def test_no_memory_is_read_without_a_reader_or_under_the_kill_switch(
    tmp_path: Path, config_dir: Path
) -> None:
    config = _config(config_dir)
    rig = make_rig(tmp_path, config)
    _read_insee(rig)
    rig.ask("Quelle est la population de la France ?")
    assert "aucune (mémoire non lue pour cette requête)" in _system_prompt(rig.brain)
    assert "memory" not in rig.payload()
    home = tmp_path / "cerveau"
    write_brain(home, [PREFERENCE | {"created": "2026-09-01T09:00:00"}])
    rig.orchestrator.memory = BrainMemory(config.memory, env={"BRAIN_HOME": str(home)})
    kill = tmp_path / KILL_SWITCH_FILE
    kill.parent.mkdir(parents=True, exist_ok=True)
    kill.write_text("arrêt", encoding="utf-8")
    asyncio.run(rig.orchestrator.ask("Quelle est la population de la France ?", request_id="r2"))
    last = rig.decisions()[-1]["payload"]
    assert last["status"] == "refus" and "memory" not in last  # R4: nothing is read
