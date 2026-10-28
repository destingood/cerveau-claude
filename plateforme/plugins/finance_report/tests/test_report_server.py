"""The finance_report MCP server, called in process through the SDK client."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult

from core.finance.fixtures import REFERENCE_READ_AT, reference_store
from core.registry.manifest import validate_plugin
from core.verification.figures import figures_in
from plugins.finance_report import server as server_module
from plugins.finance_report.server import INVALID_CONFIG, build_server

PLUGIN = Path(__file__).resolve().parents[1]
ROOT = PLUGIN.parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
SPECS = {tool["name"]: tool for tool in MANIFEST["tools"]}
GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return reference_store(tmp_path_factory.mktemp("finance") / "finance.db")


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A copy of config/ a test may change."""
    return Path(shutil.copytree(ROOT / "config", tmp_path / "config"))


def edit(config_dir: Path, name: str, old: str, new: str) -> None:
    path = config_dir / name
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def run(server: Any, action: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def call(
    store: Path, arguments: dict[str, Any], config_dir: Path = ROOT / "config"
) -> CallToolResult:
    server = build_server(store, config_dir, lambda: REFERENCE_READ_AT)
    return run(server, lambda c: c.call_tool("performance_report", arguments))


def error_text(result: CallToolResult) -> str:
    assert result.is_error
    return " ".join(getattr(block, "text", "") for block in result.content)


def compact(result: CallToolResult) -> str:
    """The structured output as the golden set matches it: compact JSON, accents kept."""
    assert not result.is_error, error_text(result)
    return json.dumps(result.structured_content, ensure_ascii=False, separators=(",", ":"))


def report(store: Path, arguments: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    result = call(store, arguments, **kwargs)
    assert not result.is_error, error_text(result)
    content: dict[str, Any] = result.structured_content
    return content


def test_the_plugin_passes_the_registry() -> None:
    result = validate_plugin(PLUGIN)
    assert result.ok, result.errors
    assert result.plugin_id == "finance_report"
    assert MANIFEST["parity_label"] == "[Parité]"


def test_published_tools_match_the_manifest(tmp_path: Path) -> None:
    server = build_server(tmp_path / "finance.db", ROOT / "config")
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
def test_golden_cases(store: Path, case: dict[str, Any]) -> None:
    """Offline: the reference portfolio, read at REFERENCE_READ_AT."""
    result = call(store, case["arguments"])
    assert result.is_error is case["expected"]["is_error"]
    text = error_text(result) if result.is_error else compact(result)
    assert case["expected"]["contains"] in text


@pytest.mark.parametrize(
    "arguments", [{}, {"start": "2025-01-01", "end": "2025-12-31"}, {"strict": True}]
)
def test_every_number_is_a_traceable_figure(store: Path, arguments: dict[str, Any]) -> None:
    figures, loose = figures_in(report(store, arguments))
    assert len(figures) > 50
    assert loose == []
    ids = [f.id for f in figures]
    assert len(ids) == len(set(ids))


def test_the_attribution_adds_up(store: Path) -> None:
    content = report(store, {})
    attribution = content["attribution"]
    lines = math.fsum(line["contribution"]["value"] for line in attribution["lines"])
    sectors = math.fsum(sector["contribution"]["value"] for sector in attribution["sectors"])
    twr = content["measures"]["twr"]["value"]
    assert math.isclose(lines, twr, abs_tol=1e-12) and math.isclose(sectors, twr, abs_tol=1e-12)
    gains = math.fsum(line["gain_eur"]["value"] for line in attribution["lines"])
    assert math.isclose(gains, content["values"]["gain_eur"]["value"], rel_tol=1e-9)


def test_sub_periods_chain_to_the_whole(store: Path) -> None:
    """The TWR of two adjacent periods compounds to the TWR of the union."""
    whole = report(store, {"start": "2024-01-02", "end": "2025-06-30"})["measures"]["twr"]
    first = report(store, {"start": "2024-01-02", "end": "2024-09-30"})["measures"]["twr"]
    second = report(store, {"start": "2024-09-30", "end": "2025-06-30"})["measures"]["twr"]
    chained = (1 + first["value"]) * (1 + second["value"]) - 1
    assert math.isclose(chained, whole["value"], rel_tol=1e-12)


def test_a_blocked_feature_is_refused_with_its_markers(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fields of finance.performance admit no marker yet: a blocked feature stands in."""
    monkeypatch.setattr(server_module, "FEATURE", "finance.benchmark")
    text = error_text(call(store, {}))
    assert "fonction bloquée « finance.benchmark »" in text
    assert "market_risk.benchmark.isin = A_VERIFIER" in text


def test_a_broken_configuration_is_not_echoed(store: Path, config_dir: Path) -> None:
    edit(config_dir, "risk.yaml", "covariance: ledoit_wolf", "covariance: [MARQUEUR-SECRET")
    text = error_text(call(store, {}, config_dir=config_dir))
    assert INVALID_CONFIG in text and "MARQUEUR-SECRET" not in text


def test_a_missing_store_says_how_to_fill_it(tmp_path: Path) -> None:
    result = call(tmp_path / "finance.db", {})
    assert "base finance absente (finance.db) : lancer `cerveau finance sync`" in error_text(result)
    assert not (tmp_path / "finance.db").exists()


def test_reading_never_writes_the_store(store: Path) -> None:
    before = hashlib.sha256(store.read_bytes()).hexdigest()
    call(store, {"strict": True})
    call(store, {"start": "2025-01-01", "end": "2025-12-31"})
    assert hashlib.sha256(store.read_bytes()).hexdigest() == before


def test_main_serves_the_store_and_configuration_of_cerveau_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    served: list[Path] = []

    class Stub:
        def run(self) -> None:
            served.append(Path("ran"))

    def fake_build(store: Path, config_dir: Path) -> Stub:
        served.extend((store, config_dir))
        return Stub()

    monkeypatch.setattr(server_module, "build_server", fake_build)
    monkeypatch.setenv("CERVEAU_HOME", str(tmp_path))
    server_module.main()
    assert served == [tmp_path / "var" / "finance" / "finance.db", tmp_path / "config", Path("ran")]
