"""Plugin registry: manifest C.1, annotations 6.3, tests and evals required (R8)."""

from __future__ import annotations

import importlib
import itertools
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import yaml

import plugins
from core.mcp.time_limit import DEFAULT_TOOL_TIMEOUT_S, MAX_TOOL_TIMEOUT_S
from core.registry import (
    EXPECTED_ANNOTATIONS,
    AgentLoadError,
    load_agent,
    validate_all,
    validate_plugin,
)
from tests.conftest import agent_manifest, base_manifest

HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


def test_conforming_plugin_is_accepted(make_plugin: Callable[..., Path]) -> None:
    report = validate_plugin(make_plugin())
    assert report.ok, report.errors
    assert report.plugin_id == "demo_plugin"
    assert any("p95_latency_ms" in w for w in report.warnings)


def test_missing_manifest_is_refused(tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    report = validate_plugin(tmp_path / "x")
    assert report.errors == ["plugin.yaml absent (R8)"]


def test_invalid_yaml_is_refused(make_plugin: Callable[..., Path]) -> None:
    root = make_plugin()
    (root / "plugin.yaml").write_text("id: [broken", encoding="utf-8")
    assert "YAML invalide" in validate_plugin(root).errors[0]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda m: m.pop("evals"), "evals"),
        (lambda m: m.update(kind="robot"), "kind"),
        (lambda m: m.update(domain="astrologie"), "domain"),
        (lambda m: m.update(parity_label="[Parfait]"), "parity_label"),
        (lambda m: m.update(version="v1"), "version"),
        (lambda m: m.update(environments=[]), "environments"),
        (lambda m: m.update(max_autonomy_level="N9"), "max_autonomy_level"),
        (lambda m: m.update(tools=[]), "au moins un outil"),
        (lambda m: m.update(unexpected=True), "unexpected"),
        (lambda m: m["tools"][0]["annotations"].pop("openWorldHint"), "openWorldHint"),
        (lambda m: m["tools"].append(dict(m["tools"][0])), "double"),
    ],
)
def test_invalid_manifest_fields_are_refused(
    make_plugin: Callable[..., Path], mutate, expected: str
) -> None:
    manifest = base_manifest()
    mutate(manifest)
    report = validate_plugin(make_plugin(manifest=manifest))
    assert not report.ok
    assert any(expected in e for e in report.errors), report.errors


RUNTIME = {"module": "plugins.demo_plugin", "env": ["DEMO_KEY"], "priced_tools": {}}


def test_declared_runtime_is_accepted(make_plugin: Callable[..., Path]) -> None:
    manifest = base_manifest()
    manifest["runtime"] = {**RUNTIME, "priced_tools": {"portfolio_var": "brave"}}
    report = validate_plugin(make_plugin(manifest=manifest))
    assert report.ok, report.errors
    assert report.manifest is not None and report.manifest.runtime is not None
    assert report.manifest.runtime.module == "plugins.demo_plugin"
    assert report.manifest.runtime.tool_timeout_s == DEFAULT_TOOL_TIMEOUT_S  # ADR-052


@pytest.mark.parametrize("seconds", [0.5, 300, MAX_TOOL_TIMEOUT_S])
def test_a_plugin_may_declare_its_tool_timeout(
    make_plugin: Callable[..., Path], seconds: float
) -> None:
    manifest = base_manifest()
    manifest["runtime"] = {**RUNTIME, "tool_timeout_s": seconds}
    report = validate_plugin(make_plugin(manifest=manifest))
    assert report.ok, report.errors
    assert report.manifest is not None and report.manifest.runtime is not None
    assert report.manifest.runtime.tool_timeout_s == seconds


@pytest.mark.parametrize("seconds", [0, -1, MAX_TOOL_TIMEOUT_S + 1, "A_DEFINIR"])
def test_a_tool_timeout_out_of_bounds_is_refused(
    make_plugin: Callable[..., Path], seconds: object
) -> None:
    manifest = base_manifest()
    manifest["runtime"] = {**RUNTIME, "tool_timeout_s": seconds}
    report = validate_plugin(make_plugin(manifest=manifest))
    assert any("tool_timeout_s" in e for e in report.errors), report.errors


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"module": "os"}, "plugins.demo_plugin ou l'un de ses modules"),
        ({"module": "plugins.demo_plugin_evil"}, "plugins.demo_plugin ou l'un de ses modules"),
        ({"module": "plugins.web_research"}, "plugins.demo_plugin ou l'un de ses modules"),
        ({"module": "plugins.demo_plugin; rm"}, "module"),
        ({"env": ["lower_case"]}, "env"),
        ({"env": ["DEMO_KEY", "DEMO_KEY"]}, "variables en double"),
        ({"priced_tools": {"ghost_tool": "brave"}}, "outils non déclarés"),
        ({"surprise": True}, "surprise"),
    ],
)
def test_invalid_runtime_is_refused(
    make_plugin: Callable[..., Path], change: dict, expected: str
) -> None:
    manifest = base_manifest()
    manifest["runtime"] = {**RUNTIME, **change}
    report = validate_plugin(make_plugin(manifest=manifest))
    assert any(expected in e for e in report.errors), report.errors


def test_runtime_describes_a_stdio_start_only(make_plugin: Callable[..., Path]) -> None:
    manifest = base_manifest()
    manifest.update(transport="mcp-http", runtime=RUNTIME)
    report = validate_plugin(make_plugin(manifest=manifest))
    assert any("mcp-stdio" in e for e in report.errors), report.errors


def test_id_must_match_directory(make_plugin: Callable[..., Path]) -> None:
    report = validate_plugin(make_plugin(manifest=base_manifest("other_name")))
    assert any("ne correspond pas au dossier" in e for e in report.errors)


@pytest.mark.parametrize("action_class", sorted(EXPECTED_ANNOTATIONS))
def test_expected_annotations_are_accepted(
    make_plugin: Callable[..., Path], action_class: str
) -> None:
    manifest = base_manifest()
    annotations = dict.fromkeys(HINTS, False)
    annotations.update(EXPECTED_ANNOTATIONS[action_class])
    manifest["tools"][0].update(action_class=action_class, annotations=annotations)
    report = validate_plugin(make_plugin(manifest=manifest))
    assert report.ok, report.errors


@pytest.mark.parametrize(
    ("action_class", "annotations"),
    [
        (cls, dict(zip(HINTS, combo, strict=True)))
        for cls in sorted(EXPECTED_ANNOTATIONS)
        for combo in itertools.product([False, True], repeat=4)
    ],
)
def test_annotation_matrix_matches_section_6_3(
    make_plugin: Callable[..., Path], action_class: str, annotations: dict
) -> None:
    manifest = base_manifest()
    manifest["tools"][0].update(action_class=action_class, annotations=annotations)
    report = validate_plugin(make_plugin(manifest=manifest))
    expected_ok = all(
        annotations[h] is v for h, v in EXPECTED_ANNOTATIONS[action_class].items()
    ) and not (annotations["readOnlyHint"] and annotations["destructiveHint"])
    assert report.ok is expected_ok, report.errors


def test_financial_tool_declared_read_only_is_refused(make_plugin: Callable[..., Path]) -> None:
    manifest = base_manifest()
    manifest["tools"][0]["action_class"] = "FINANCIERE"  # annotations still say read-only
    report = validate_plugin(make_plugin(manifest=manifest))
    assert any("FINANCIERE exige readOnlyHint: false" in e for e in report.errors)


def test_plugin_without_tests_is_refused(make_plugin: Callable[..., Path]) -> None:
    root = make_plugin()
    (root / "tests" / "test_demo.py").unlink()
    assert any("aucun fichier test_" in e for e in validate_plugin(root).errors)


def test_plugin_with_fewer_than_ten_questions_is_refused(make_plugin: Callable[..., Path]) -> None:
    root = make_plugin()
    xml = "<evaluation>" + "<qa_pair><question>q</question><answer>a</answer></qa_pair>" * 9
    (root / "evals" / "questions.xml").write_text(xml + "</evaluation>", encoding="utf-8")
    assert any("9 question(s), minimum 10" in e for e in validate_plugin(root).errors)


def test_question_without_answer_is_refused(make_plugin: Callable[..., Path]) -> None:
    root = make_plugin()
    path = root / "evals" / "questions.xml"
    path.write_text(path.read_text().replace("<answer>3</answer>", "<answer> </answer>"))
    errors = validate_plugin(root).errors
    assert any("sans réponse" in e for e in errors)
    assert any("9 question(s)" in e for e in errors)


def test_xml_with_dtd_is_refused(make_plugin: Callable[..., Path]) -> None:
    root = make_plugin()
    bomb = '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><evaluation/>'
    (root / "evals" / "questions.xml").write_text(bomb, encoding="utf-8")
    assert any("DTD" in e for e in validate_plugin(root).errors)


def test_missing_or_empty_golden_set_is_refused(make_plugin: Callable[..., Path]) -> None:
    root = make_plugin()
    (root / "evals" / "golden.jsonl").write_text("\n", encoding="utf-8")
    assert any("golden set vide" in e for e in validate_plugin(root).errors)
    (root / "evals" / "golden.jsonl").unlink()
    assert any("introuvable" in e for e in validate_plugin(root).errors)


def test_invalid_json_schema_is_refused(make_plugin: Callable[..., Path]) -> None:
    root = make_plugin()
    (root / "schemas" / "portfolio_var.in.json").write_text('{"type": 12}', encoding="utf-8")
    assert any("schéma JSON invalide" in e for e in validate_plugin(root).errors)


def test_paths_escaping_the_plugin_are_refused(make_plugin: Callable[..., Path]) -> None:
    manifest = base_manifest()
    manifest["tests"] = "../../"
    report = validate_plugin(make_plugin(manifest=manifest))
    assert any("sort du dossier du plugin" in e for e in report.errors)


def test_restrictive_licence_is_flagged(make_plugin: Callable[..., Path]) -> None:
    manifest = base_manifest()
    manifest["dependencies_licences"] = ["MIT", "Elastic-2.0", "GPL-3.0"]
    report = validate_plugin(make_plugin(manifest=manifest))
    assert report.ok
    assert any("R14" in w for w in report.warnings)


def test_validate_all_separates_accepted_and_refused(make_plugin: Callable[..., Path]) -> None:
    good = make_plugin("good_plugin")
    bad = make_plugin("bad_plugin")
    manifest = yaml.safe_load((bad / "plugin.yaml").read_text())
    manifest["tools"][0]["action_class"] = "IRREVERSIBLE"
    (bad / "plugin.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    result = validate_all(good.parent)
    assert [r.plugin_id for r in result.accepted] == ["good_plugin"]
    assert [r.plugin_id for r in result.refused] == ["bad_plugin"]


def test_repository_plugins_directory_is_valid() -> None:
    from tests.conftest import REPO_ROOT

    result = validate_all(REPO_ROOT / "plugins")
    assert not result.refused, [(r.plugin_id, r.errors) for r in result.refused]
    # Every repository plugin starts or loads from its own folder (ADR-015, B26, ADR-028).
    assert all(r.manifest and (r.manifest.runtime or r.manifest.agent) for r in result.accepted)


def write_agent(root: Path, source: str = "def build_graph():\n    return 'graphe'\n") -> Path:
    """The agent's package and its ``graph`` module, as the entry point names them."""
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "graph.py").write_text(source, encoding="utf-8")
    return root


def make_agent(make_plugin: Callable[..., Path], manifest: dict | None = None) -> Path:
    return make_plugin("demo_agent", manifest=manifest or agent_manifest())


def test_an_in_process_agent_is_accepted(make_plugin: Callable[..., Path]) -> None:
    report = validate_plugin(write_agent(make_agent(make_plugin)))
    assert report.ok, report.errors
    assert report.manifest is not None and report.manifest.agent is not None
    assert report.manifest.tools == [] and report.manifest.runtime is None
    agent = report.manifest.agent
    assert (agent.module, agent.function) == ("plugins.demo_agent.graph", "build_graph")


def test_an_agent_may_live_in_its_package_itself(make_plugin: Callable[..., Path]) -> None:
    manifest = agent_manifest()
    manifest["agent"] = {"entrypoint": "plugins.demo_agent:build_graph"}
    root = make_agent(make_plugin, manifest)
    assert any("introuvable dans le plugin" in e for e in validate_plugin(root).errors)
    (root / "__init__.py").write_text("", encoding="utf-8")
    assert validate_plugin(root).ok


def _entrypoint(value: str) -> Callable[[dict], None]:
    return lambda m: m.update(agent={"entrypoint": value})


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda m: m.update(kind="tool", tools=base_manifest()["tools"]),
            "réservé aux plugins de type agent",
        ),
        (lambda m: m.update(tools=base_manifest()["tools"]), "ne publie aucun outil"),
        (lambda m: m.pop("agent"), "agent.entrypoint"),
        (lambda m: m.update(transport="mcp-stdio"), "agent ne décrit qu'un chargement in-process"),
        (lambda m: m.update(runtime={"module": "plugins.demo_agent"}), "démarrage mcp-stdio"),
        (_entrypoint("os.path:join"), "plugins.demo_agent ou l'un de ses modules"),
        (_entrypoint("plugins.demo_agent_evil.graph:f"), "plugins.demo_agent ou l'un de ses"),
        (_entrypoint("plugins.web_research.server:build_server"), "plugins.demo_agent ou l'un"),
        (_entrypoint("plugins.demo_agent.graph"), "entrypoint"),
        (_entrypoint("plugins.demo_agent.graph:x; rm"), "entrypoint"),
        (lambda m: m["agent"].update(surprise=True), "surprise"),
    ],
)
def test_invalid_agents_are_refused(
    make_plugin: Callable[..., Path], mutate: Callable[[dict], object], expected: str
) -> None:
    manifest = agent_manifest()
    mutate(manifest)
    report = validate_plugin(write_agent(make_agent(make_plugin, manifest)))
    assert any(expected in e for e in report.errors), report.errors


def test_an_agent_whose_module_is_missing_is_refused(make_plugin: Callable[..., Path]) -> None:
    assert validate_plugin(make_agent(make_plugin)).errors == [
        "agent.entrypoint : module plugins.demo_agent.graph introuvable dans le plugin"
    ]


@pytest.fixture
def agents_root(
    make_plugin: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    """The test's plugins folder, searched by the ``plugins`` package after the repository's."""
    root = make_agent(make_plugin).parent
    monkeypatch.setattr(plugins, "__path__", [*plugins.__path__, str(root)])
    importlib.invalidate_caches()
    yield root
    for name in [n for n in sys.modules if n.split(".")[:2] == ["plugins", "demo_agent"]]:
        del sys.modules[name]


def test_an_agent_is_loaded_from_its_own_folder(agents_root: Path) -> None:
    build = load_agent(write_agent(agents_root / "demo_agent"))
    assert build() == "graphe"
    module = sys.modules["plugins.demo_agent.graph"]
    assert Path(module.__file__ or "").resolve().is_relative_to(agents_root.resolve())


def test_an_agent_refused_by_the_registry_is_never_imported(agents_root: Path) -> None:
    root = write_agent(agents_root / "demo_agent", "raise SystemExit('importé')\n")
    (root / "evals" / "golden.jsonl").unlink()
    with pytest.raises(AgentLoadError, match="refusé par le registre"):
        load_agent(root)
    assert "plugins.demo_agent" not in sys.modules


def test_an_agent_outside_the_plugins_package_is_never_imported(
    make_plugin: Callable[..., Path],
) -> None:
    root = write_agent(make_agent(make_plugin), "raise SystemExit('importé')\n")
    with pytest.raises(AgentLoadError, match="hors du paquet plugins"):
        load_agent(root)
    assert "plugins.demo_agent" not in sys.modules


def test_an_agent_shadowed_by_a_repository_plugin_is_refused(
    agents_root: Path, make_plugin: Callable[..., Path]
) -> None:
    """``plugins.finance_research`` resolves to the repository's folder, not the one validated."""
    manifest = agent_manifest("finance_research")
    manifest["agent"] = {"entrypoint": "plugins.finance_research:build_graph"}
    root = make_plugin("finance_research", manifest=manifest)
    (root / "__init__.py").write_text("raise SystemExit('importé')\n", encoding="utf-8")
    with pytest.raises(AgentLoadError, match="ne vient pas du dossier validé"):
        load_agent(root)


def test_an_entry_point_that_is_not_a_function_is_refused(agents_root: Path) -> None:
    root = write_agent(agents_root / "demo_agent", "build_graph = 3\n")
    with pytest.raises(AgentLoadError, match="n'est pas une fonction"):
        load_agent(root)


def test_a_tool_plugin_is_not_an_agent(make_plugin: Callable[..., Path]) -> None:
    with pytest.raises(AgentLoadError, match="pas un agent in-process"):
        load_agent(make_plugin())


def test_an_agent_of_another_domain_is_refused_before_import(agents_root: Path) -> None:
    """A pack never runs an agent registered, and measured, for another domain (ADR-043)."""
    root = write_agent(agents_root / "demo_agent", "raise SystemExit('importé')\n")
    with pytest.raises(AgentLoadError, match="domaine finance, pas celui du pack « recherche »"):
        load_agent(root, domain="recherche")
    assert "plugins.demo_agent" not in sys.modules
