"""The finance_research MCP server, called in process through the SDK client."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult
from typer.testing import CliRunner

from core.finance.research import lab
from core.finance.research.registry import REGISTRY_DIR
from core.finance.research.report import VERDICT, default_reports_dir, latest_report
from core.registry.manifest import validate_plugin
from core.verification.figures import figures_in
from interfaces.cli import strategy as strategy_cli
from interfaces.cli.main import app
from plugins.finance_research import server as server_module
from plugins.finance_research.server import INVALID_CONFIG, build_server

PLUGIN = Path(__file__).resolve().parents[1]
ROOT = PLUGIN.parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
SPECS = {tool["name"]: tool for tool in MANIFEST["tools"]}
GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]
ENTRY = Path(REGISTRY_DIR) / "croisement_mm.yaml"
MODULE = Path("core/finance/research/strategies/croisement_mm.py")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
SIGNALS = {"strategie": "croisement_mm", "mode": "signaux", "params": {"short": 20, "long": 50}}
BACKTEST = {
    "strategie": "croisement_mm",
    "mode": "backtest",
    "params": {"short": 20, "long": 50},
    "debut": "2020-01-02",
    "fin": "2021-12-31",
}
PROTOCOL = {"strategie": "croisement_mm", "mode": "protocole"}


def make_home(root: Path, **changes: Any) -> Path:
    """A CERVEAU_HOME holding the demo entry as versioned, with ``changes`` applied."""
    raw = yaml.safe_load((ROOT / ENTRY).read_text(encoding="utf-8"))
    raw.update(changes)
    (root / ENTRY).parent.mkdir(parents=True)
    text = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)
    (root / ENTRY).write_text(text, encoding="utf-8")
    (root / MODULE).parent.mkdir(parents=True)
    shutil.copyfile(ROOT / MODULE, root / MODULE)
    return root


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The demo entry alone: no research store and no protocol report yet (N = 0)."""
    return make_home(tmp_path_factory.mktemp("research") / "home")


@pytest.fixture(scope="module")
def judged(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """The demo narrowed to the planted trend and four points, after one protocol run."""
    root = make_home(
        tmp_path_factory.mktemp("judged") / "home",
        univers=["FICT-RTEND"],
        grille={"short": [10, 20], "long": [50, 100]},
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CERVEAU_HOME", str(root))
        patch.delenv("CERVEAU_AUDIT_JOURNAL", raising=False)
        patch.setattr(strategy_cli, "now", lambda: NOW)
        result = CliRunner().invoke(
            app, ["strategy", "protocol", "croisement_mm", "--config-dir", str(ROOT / "config")]
        )
    assert result.exit_code == 0, result.output
    yield root


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A copy of config/ a test may change."""
    return Path(shutil.copytree(ROOT / "config", tmp_path / "config"))


def run(server: Any, action: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def call(
    root: Path, arguments: dict[str, Any], config_dir: Path = ROOT / "config"
) -> CallToolResult:
    server = build_server(root, config_dir, lambda: NOW)
    return run(server, lambda c: c.call_tool("strategy_lab", arguments))


def error_text(result: CallToolResult) -> str:
    assert result.is_error
    return " ".join(getattr(block, "text", "") for block in result.content)


def compact(result: CallToolResult) -> str:
    """The structured output as the golden set matches it: compact JSON, accents kept."""
    assert not result.is_error, error_text(result)
    return json.dumps(result.structured_content, ensure_ascii=False, separators=(",", ":"))


def answer(root: Path, arguments: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    result = call(root, arguments, **kwargs)
    assert not result.is_error, error_text(result)
    content: dict[str, Any] = result.structured_content
    return content


def test_the_plugin_passes_the_registry() -> None:
    result = validate_plugin(PLUGIN)
    assert result.ok, result.errors
    assert result.plugin_id == "finance_research"
    assert MANIFEST["parity_label"] == "[Approximation]"
    assert MANIFEST["max_autonomy_level"] == "N1"
    assert {tool["action_class"] for tool in MANIFEST["tools"]} == {"CALCUL"}


def test_published_tools_match_the_manifest(tmp_path: Path) -> None:
    server = build_server(tmp_path, ROOT / "config")
    tools = run(server, lambda c: c.list_tools()).tools
    assert sorted(t.name for t in tools) == sorted(SPECS)
    for tool in tools:
        spec = SPECS[tool.name]
        assert tool.description == spec["description"]
        published = tool.annotations.model_dump(by_alias=True, exclude_none=True)
        assert published == spec["annotations"]
        label = tool.output_schema["properties"]["parity_label"]  # type: ignore[index]
        assert label["const"] == label["default"] == MANIFEST["parity_label"]  # R12
        for kind, schema in (
            ("input_schema", tool.input_schema),
            ("output_schema", tool.output_schema),
        ):
            on_disk = json.loads((PLUGIN / spec[kind]).read_text(encoding="utf-8"))
            on_disk.pop("$schema")
            assert schema == on_disk, f"{spec[kind]} is stale: regenerate it from the server"


@pytest.mark.parametrize("case", GOLDEN, ids=[case["id"] for case in GOLDEN])
def test_golden_cases(home: Path, case: dict[str, Any]) -> None:
    """Offline: the versioned demo entry, read on 20/10/2026 at 12:00 UTC."""
    result = call(home, case["arguments"])
    assert result.is_error is case["expected"]["is_error"]
    text = error_text(result) if result.is_error else compact(result)
    assert case["expected"]["contains"] in text


@pytest.mark.parametrize("arguments", [SIGNALS, BACKTEST])
def test_every_number_is_a_traceable_figure_of_the_tool(
    home: Path, arguments: dict[str, Any]
) -> None:
    figures, loose = figures_in(answer(home, arguments))
    assert loose == []
    ids = [f.id for f in figures]
    assert len(ids) == len(set(ids)) > 3
    assert all(i.startswith("strategy_lab/") for i in ids)


def test_no_mode_gives_a_verdict_and_a_backtest_says_it_is_a_trial(home: Path) -> None:
    for arguments in (SIGNALS, BACKTEST, PROTOCOL):
        content = answer(home, arguments)
        assert content["dernier_verdict"] is None and content["protocole"] is None
        assert content["rappel"].startswith("Aucun protocole enregistré pour croisement_mm")
        assert content["essais_famille"]["value"] == 0
        assert content["donnees"] == "synthetiques" and content["frais"] == "fictifs"
    warnings = answer(home, BACKTEST)["avertissements"]
    assert any("essai de la famille croisement_mm" in w for w in warnings)


def test_a_signal_answer_lists_the_largest_weights_and_counts_the_rest(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    full = answer(home, SIGNALS)["signaux"]
    assert full["omis"] is None and len(full["instruments"]) == 4
    monkeypatch.setattr(lab, "MAX_INSTRUMENTS", 2)
    short = answer(home, SIGNALS)["signaux"]
    assert [line["instrument"] for line in short["instruments"]] == [
        line["instrument"] for line in full["instruments"][:2]
    ]
    assert short["omis"]["value"] == 2 and short["omis"]["id"] == "strategy_lab/signaux/omis"
    assert short["liquidites"] == full["liquidites"]


def test_reading_writes_nothing(home: Path) -> None:
    before = sorted(p.relative_to(home) for p in home.rglob("*"))
    for arguments in (SIGNALS, BACKTEST, PROTOCOL):
        answer(home, arguments)
    assert sorted(p.relative_to(home) for p in home.rglob("*")) == before


def test_real_data_stays_blocked_while_its_parameters_are_undefined(tmp_path: Path) -> None:
    root = make_home(tmp_path / "home", donnees="reelles")
    for arguments in (SIGNALS, BACKTEST, PROTOCOL):
        text = error_text(call(root, arguments))
        assert "fonction bloquée « finance.research »" in text
    assert not (root / "var").exists()


def test_an_undefined_capital_blocks_the_backtest_only(tmp_path: Path) -> None:
    root = make_home(tmp_path / "home", capital_initial_eur="A_DEFINIR")
    text = error_text(call(root, BACKTEST))
    assert "Bloqué (R7) : capital_initial_eur de croisement_mm vaut A_DEFINIR" in text
    assert answer(root, SIGNALS)["signaux"]["instruments"]


def test_a_broken_configuration_is_not_echoed(home: Path, config_dir: Path) -> None:
    path = config_dir / "research.yaml"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nsecret: [MARQUEUR-SECRET\n", encoding="utf-8"
    )
    text = error_text(call(home, SIGNALS, config_dir=config_dir))
    assert INVALID_CONFIG in text and "MARQUEUR-SECRET" not in text


def test_the_protocol_mode_cites_the_last_verdict_and_its_gates(judged: Path) -> None:
    found = latest_report("croisement_mm", default_reports_dir(judged))
    assert found is not None
    path, report = found
    content = answer(judged, PROTOCOL)
    protocol = content["protocole"]
    assert protocol["rapport"] == path.name
    assert protocol["verdict"] == content["dernier_verdict"] == VERDICT[report.verdict]
    assert protocol["a_jour"] is True and protocol["ecarts"] == []
    assert [g["cle"] for g in protocol["portes"]] == [g.cle for g in report.portes]
    assert protocol["lignes"]
    assert content["rappel"].startswith(f"Dernier verdict du protocole : {protocol['verdict']}")
    assert "n'est plus la version actuelle" not in content["rappel"]
    assert content["essais_famille"]["value"] > 0
    backtest = answer(judged, {**BACKTEST, "params": {"short": 10, "long": 50}})
    assert backtest["dernier_verdict"] == protocol["verdict"] and backtest["protocole"] is None


def test_a_changed_grid_makes_the_last_verdict_stale(judged: Path, tmp_path: Path) -> None:
    root = Path(shutil.copytree(judged, tmp_path / "home"))
    entry = root / ENTRY
    raw = yaml.safe_load(entry.read_text(encoding="utf-8"))
    raw["grille"] = {"short": [10, 20], "long": [50, 200]}
    entry.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    content = answer(root, PROTOCOL)
    assert content["protocole"]["a_jour"] is False
    assert content["protocole"]["ecarts"] == [
        "empreinte de grille différente de la version actuelle"
    ]
    # The planted trend alone passes the protocol: the reminder says which version it judged.
    assert content["dernier_verdict"] == VERDICT["reussi"]
    stale = "pour la version jugée seulement, qui n'est plus la version actuelle"
    assert stale in content["rappel"]


def test_main_serves_the_project_of_cerveau_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    served: list[Path] = []

    class Stub:
        def run(self) -> None:
            served.append(Path("ran"))

    def fake_build(root: Path, config_dir: Path) -> Stub:
        served.extend((root, config_dir))
        return Stub()

    monkeypatch.setattr(server_module, "build_server", fake_build)
    monkeypatch.setenv("CERVEAU_HOME", str(tmp_path))
    server_module.main()
    assert served == [tmp_path, tmp_path / "config", Path("ran")]
