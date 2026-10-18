"""The finance_risk MCP server, called in process through the SDK client."""

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
from core.finance.risk_report import DEFAULT_MEASURES, MEASURES
from core.registry.manifest import validate_plugin
from core.verification.figures import figures_in
from plugins.finance_risk import server as server_module
from plugins.finance_risk.server import INVALID_CONFIG, build_server

PLUGIN = Path(__file__).resolve().parents[1]
ROOT = PLUGIN.parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
SPECS = {tool["name"]: tool for tool in MANIFEST["tools"]}
GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]
EVERYTHING = {
    "measures": list(MEASURES),
    "compare_to": "2026-10-12T13:00:00Z",
    "sector_shocks": [{"sector": "Technologie", "shock": -0.15}],
}
LEHMAN = (
    'crise_2008:  { label: "Crise financière (faillite de Lehman)", start: A_VERIFIER, '
    "end: A_VERIFIER, source: A_VERIFIER }"
)
COVID = (
    'covid_2020:  { label: "Krach du Covid", start: A_VERIFIER, end: A_VERIFIER, '
    "source: A_VERIFIER }"
)


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return reference_store(tmp_path_factory.mktemp("finance") / "finance.db")


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A copy of config/ a test may change."""
    return Path(shutil.copytree(ROOT / "config", tmp_path / "config"))


def edit_risk(config_dir: Path, old: str, new: str) -> None:
    path = config_dir / "risk.yaml"
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def run(server: Any, action: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def call(
    store: Path, arguments: dict[str, Any] | None = None, config_dir: Path = ROOT / "config"
) -> CallToolResult:
    server = build_server(store, config_dir, lambda: REFERENCE_READ_AT)
    return run(server, lambda c: c.call_tool("risk_report", arguments or {}))


def error_text(result: CallToolResult) -> str:
    assert result.is_error
    return " ".join(getattr(block, "text", "") for block in result.content)


def compact(result: CallToolResult) -> str:
    """The structured output as the golden set matches it: compact JSON, accents kept."""
    assert not result.is_error, error_text(result)
    return json.dumps(result.structured_content, ensure_ascii=False, separators=(",", ":"))


def report(store: Path, arguments: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    result = call(store, arguments, **kwargs)
    assert not result.is_error, error_text(result)
    content: dict[str, Any] = result.structured_content
    return content


def scenario(content: dict[str, Any], name: str) -> dict[str, Any]:
    (found,) = [s for s in content["stress"] if s["scenario"] == name]
    return found


def test_the_plugin_passes_the_registry() -> None:
    result = validate_plugin(PLUGIN)
    assert result.ok, result.errors
    assert result.plugin_id == "finance_risk"
    assert MANIFEST["parity_label"] == "[Approximation]"


def test_published_tools_match_the_manifest(tmp_path: Path) -> None:
    server = build_server(tmp_path / "finance.db", ROOT / "config")
    tools = run(server, lambda c: c.list_tools()).tools
    assert sorted(t.name for t in tools) == sorted(SPECS)
    for tool in tools:
        spec = SPECS[tool.name]
        assert tool.description == spec["description"]
        published = tool.annotations.model_dump(by_alias=True, exclude_none=True)
        assert published == spec["annotations"]
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


@pytest.mark.parametrize("as_of", [None, "2026-10-16T20:00:00Z"])
def test_every_number_is_a_traceable_figure(store: Path, as_of: str | None) -> None:
    arguments = dict(EVERYTHING, **({"as_of": as_of} if as_of else {}))
    figures, loose = figures_in(report(store, arguments))
    assert len(figures) > 300
    assert loose == []
    ids = [f.id for f in figures]
    assert len(ids) == len(set(ids))


def test_the_default_measures_leave_out_the_correlations(store: Path) -> None:
    content = report(store)
    assert content["measures"] == list(DEFAULT_MEASURES)
    assert content["correlations"] is None and content["var_change"] is None
    assert content["day"] == "2026-10-18"
    assert content["method"]["last_session"] == "2026-10-16"
    only = report(store, {"measures": ["drawdown"]})
    assert only["var"] is None and only["stress"] is None and only["drawdown"] is not None


def test_a_measure_that_cannot_be_computed_is_said_not_estimated(store: Path) -> None:
    content = report(store, {"measures": ["beta", "facteurs", "stress"]})
    reasons = {u["measure"]: u["reason"] for u in content["unavailable"]}
    assert reasons["beta"] == "indice de référence bloqué : ISIN A_VERIFIER (D8)"
    assert "D9" in reasons["facteurs"]
    assert content["beta"] is None
    adjusted = scenario(content, "actions_beta")
    assert adjusted["status"] == "bloque" and adjusted["impact_eur"] is None
    for name in ("crise_2008", "covid_2020", "taux_2022"):
        blocked = scenario(content, f"historique/{name}")
        assert blocked["status"] == "bloque" and blocked["impact_eur"] is None
        assert "D10" in blocked["note"]


def test_the_rate_stress_adds_its_duration_and_estimated_parts(store: Path) -> None:
    rates = scenario(report(store, {"measures": ["stress"]}), "taux")
    split = rates["rates"]
    assert rates["status"] == "calcule" and split["series"] == "estr"
    assert split["duration_lines"] == ["FICT-OAT35"]
    assert "FICT-OAT35" not in split["estimated_lines"] and split["estimated_lines"]
    total = split["duration_eur"]["value"] + split["estimated_eur"]["value"]
    assert math.isclose(rates["impact_eur"]["value"], total, rel_tol=1e-12)
    assert split["standard_error_eur"]["value"] > 0
    assert 0.0 <= split["p_value"]["value"] <= 1.0
    assert "[Estimation]" in rates["note"] and "[Approximation]" in rates["note"]


def test_the_var_change_splits_into_positions_market_and_residual(store: Path) -> None:
    content = report(store, {"measures": ["var"], "compare_to": "2026-10-12T13:00:00Z"})
    change = content["var_change"]
    assert change["day"] == "2026-10-12"
    for row in change["rows"]:
        parts = (row["positions_effect"], row["market_effect"], row["residual"])
        total = math.fsum(part["value"] for part in parts)
        assert math.isclose(total, row["change"]["value"], rel_tol=1e-9)
        assert math.isclose(
            row["after"]["value"] - row["before"]["value"], row["change"]["value"], rel_tol=1e-12
        )
    (after,) = [
        r
        for r in content["var"]
        if r["method"] == "parametrique"
        and r["confidence"]["value"] == 0.95
        and r["horizon"]["value"] == 1
    ]
    assert math.isclose(
        change["rows"][0]["after"]["value"], after["var_eur"]["value"], rel_tol=1e-9
    )


def test_monte_carlo_is_reproducible(store: Path) -> None:
    first = report(store, {"measures": ["var"]})["var"]
    assert report(store, {"measures": ["var"]})["var"] == first


def test_a_marker_in_a_typed_parameter_is_an_invalid_configuration(
    store: Path, config_dir: Path
) -> None:
    """The market risk parameters take no marker: one there fails the schema (R7)."""
    edit_risk(config_dir, "window_sessions: 500", "window_sessions: A_DEFINIR")
    assert INVALID_CONFIG in error_text(call(store, config_dir=config_dir))


def test_a_blocked_feature_is_refused_with_its_reasons(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The historical windows of the versioned configuration are still A_VERIFIER (D10)."""
    monkeypatch.setattr(server_module, "FEATURE", "finance.historical_stress")
    text = error_text(call(store))
    assert "fonction bloquée « finance.historical_stress »" in text and "A_VERIFIER" in text


def test_a_broken_configuration_is_not_echoed(store: Path, config_dir: Path) -> None:
    edit_risk(config_dir, "seed: 2026", "seed: [MARQUEUR-SECRET")
    text = error_text(call(store, config_dir=config_dir))
    assert INVALID_CONFIG in text and "MARQUEUR-SECRET" not in text


def test_a_dated_historical_window_is_computed_or_said_uncovered(
    store: Path, config_dir: Path
) -> None:
    edit_risk(
        config_dir,
        LEHMAN,
        'crise_2008: { label: "Fenêtre d\'essai", start: 2025-06-02, end: 2025-10-09, '
        'source: "essai" }',
    )
    edit_risk(
        config_dir,
        COVID,
        'covid_2020: { label: "Krach du Covid", start: 2020-02-19, end: 2020-03-23, '
        'source: "essai" }',
    )
    content = report(store, {"measures": ["stress"]}, config_dir=config_dir)
    computed = scenario(content, "historique/crise_2008")
    assert computed["status"] == "calcule"
    assert (computed["start"], computed["end"]) == ("2025-06-02", "2025-10-09")
    assert computed["impact_eur"]["value"] < 0 and "essai" in computed["note"]
    uncovered = scenario(content, "historique/covid_2020")
    assert uncovered["status"] == "non_couvert" and uncovered["impact_eur"] is None
    assert scenario(content, "historique/taux_2022")["status"] == "bloque"


def test_a_missing_store_says_how_to_fill_it(tmp_path: Path) -> None:
    result = call(tmp_path / "finance.db")
    assert "base finance absente (finance.db) : lancer `cerveau finance sync`" in error_text(result)
    assert not (tmp_path / "finance.db").exists()


def test_reading_never_writes_the_store(store: Path) -> None:
    before = hashlib.sha256(store.read_bytes()).hexdigest()
    call(store, EVERYTHING)
    call(store, {"strict": True})
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
