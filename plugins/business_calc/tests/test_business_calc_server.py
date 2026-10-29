"""The business_calc MCP server, called in process through the SDK client."""

from __future__ import annotations

import asyncio
import json
import runpy
import shutil
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult

from core.registry.manifest import validate_plugin
from core.verification.figures import figures_in
from plugins.business_calc import server as server_module
from plugins.business_calc.server import INVALID_CONFIG, build_server

PLUGIN = Path(__file__).resolve().parents[1]
ROOT = PLUGIN.parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
SPECS = {tool["name"]: tool for tool in MANIFEST["tools"]}
GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]
DAY = date(2026, 10, 29)
VAT = {"operation": "tva", "montant": "100", "sens": "ht_vers_ttc", "taux": "normal"}


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
    calcul: dict[str, Any], config_dir: Path = ROOT / "config", day: date = DAY
) -> CallToolResult:
    server = build_server(config_dir, lambda: day)
    return run(server, lambda c: c.call_tool("biz_calc", {"calcul": calcul}))


def error_text(result: CallToolResult) -> str:
    assert result.is_error
    return " ".join(getattr(block, "text", "") for block in result.content)


def compact(result: CallToolResult) -> str:
    assert not result.is_error, error_text(result)
    return json.dumps(result.structured_content, ensure_ascii=False, separators=(",", ":"))


def test_the_plugin_passes_the_registry() -> None:
    result = validate_plugin(PLUGIN)
    assert result.ok, result.errors


def test_published_tools_match_the_manifest_and_schemas() -> None:
    tools = run(build_server(ROOT / "config"), lambda c: c.list_tools()).tools
    assert sorted(t.name for t in tools) == sorted(SPECS)
    for tool in tools:
        spec = SPECS[tool.name]
        assert tool.description == spec["description"]
        for kind, schema in (
            ("input_schema", tool.input_schema),
            ("output_schema", tool.output_schema),
        ):
            on_disk = json.loads((PLUGIN / spec[kind]).read_text(encoding="utf-8"))
            on_disk.pop("$schema")
            assert schema == on_disk, f"{spec[kind]} is stale: regenerate it from the server"


@pytest.mark.parametrize("case", GOLDEN, ids=[case["id"] for case in GOLDEN])
def test_golden_cases(case: dict[str, Any]) -> None:
    result = call(case["arguments"]["calcul"])
    assert result.is_error is case["expected"]["is_error"]
    text = error_text(result) if result.is_error else compact(result)
    assert case["expected"]["contains"] in text


def test_every_number_is_a_traceable_figure() -> None:
    figures, loose = figures_in(call(VAT).structured_content)
    assert loose == []
    assert [f.id for f in figures] == [
        "entree.montant",
        "entree.taux_tva",
        "resultat.ht",
        "resultat.tva",
        "resultat.ttc",
    ]


def test_the_vat_refuses_after_the_validity_of_the_table() -> None:
    """The CGI references end on 2026-12-31: the CIBS takes over on 2027-01-01 (R10)."""
    assert not call(VAT, day=date(2026, 12, 31)).is_error
    assert "relire dans le CIBS" in error_text(call(VAT, day=date(2027, 1, 1)))


def test_a_marker_on_the_validity_blocks_only_the_vat(config_dir: Path) -> None:
    path = config_dir / "business.yaml"
    text = path.read_text(encoding="utf-8")
    assert "valid_until: 2026-12-31" in text
    path.write_text(text.replace("valid_until: 2026-12-31", "valid_until: A_DEFINIR"), "utf-8")
    assert "vat.valid_until" in error_text(call(VAT, config_dir))
    growth = {"operation": "variation", "valeur_initiale": "1", "valeur_finale": "2"}
    assert not call(growth, config_dir).is_error  # the other operations read no configuration


def test_an_invalid_configuration_refuses_the_vat(config_dir: Path) -> None:
    (config_dir / "business.yaml").write_text("vat: 3\n", encoding="utf-8")
    assert error_text(call(VAT, config_dir)).endswith(INVALID_CONFIG)


def test_the_server_reads_the_config_of_cerveau_home(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Path] = []

    class Fake:
        def run(self) -> None:
            pass

    def fake_build(config_dir: Path) -> Fake:
        seen.append(config_dir)
        return Fake()

    monkeypatch.setattr(server_module, "build_server", fake_build)
    monkeypatch.setenv("CERVEAU_HOME", str(ROOT))
    server_module.main()
    assert seen == [ROOT / "config"]
    assert isinstance(server_module.today(), date)


def test_python_dash_m_starts_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    monkeypatch.setattr(server_module, "main", lambda: ran.append("main"))
    runpy.run_module("plugins.business_calc", run_name="__main__")
    assert ran == ["main"]
