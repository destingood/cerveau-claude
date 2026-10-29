"""The finance_optimize MCP server, called in process through the SDK client."""

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
from core.finance.optimize import METHODS
from core.registry.manifest import validate_plugin
from core.verification.figures import figures_in
from plugins.finance_optimize import server as server_module
from plugins.finance_optimize.server import INVALID_CONFIG, build_server

PLUGIN = Path(__file__).resolve().parents[1]
ROOT = PLUGIN.parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
SPECS = {tool["name"]: tool for tool in MANIFEST["tools"]}
GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]
COSTS = (
    "  commission_pct: A_DEFINIR       # en % du montant de l'ordre : 0.1 pour 0,1 %\n"
    "  min_commission_eur: A_DEFINIR   # par ordre\n"
    "  slippage_bps: A_DEFINIR\n"
    "  fx_conversion_bps: A_DEFINIR    # change d'un ordre en devise étrangère\n"
)
KNOWN_COSTS = (
    '  commission_pct: "0.1"\n'
    '  min_commission_eur: "2"\n'
    '  slippage_bps: "5"\n'
    '  fx_conversion_bps: "25"\n'
)


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
    return run(server, lambda c: c.call_tool("rebalance_proposal", arguments))


def error_text(result: CallToolResult) -> str:
    assert result.is_error
    return " ".join(getattr(block, "text", "") for block in result.content)


def compact(result: CallToolResult) -> str:
    """The structured output as the golden set matches it: compact JSON, accents kept."""
    assert not result.is_error, error_text(result)
    return json.dumps(result.structured_content, ensure_ascii=False, separators=(",", ":"))


def proposal(store: Path, arguments: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    result = call(store, arguments, **kwargs)
    assert not result.is_error, error_text(result)
    content: dict[str, Any] = result.structured_content
    return content


def values(content: dict[str, Any], field: str) -> dict[str, float]:
    return {line["line"]: line[field]["value"] for line in content["lines"]}


def test_the_plugin_passes_the_registry() -> None:
    result = validate_plugin(PLUGIN)
    assert result.ok, result.errors
    assert result.plugin_id == "finance_optimize"
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


@pytest.mark.parametrize("method", [m for m in METHODS if m != "moyenne_variance"])
def test_every_number_is_a_traceable_figure(store: Path, method: str) -> None:
    figures, loose = figures_in(proposal(store, {"method": method}))
    assert len(figures) > 100
    assert loose == []
    ids = [f.id for f in figures]
    assert len(ids) == len(set(ids))


def test_the_risk_before_is_the_one_of_the_risk_report(store: Path) -> None:
    """Same window, sample covariance and cash lines as risk_report (ADR-019)."""
    before = proposal(store, {"method": "hrp"})["risk"]["before"]
    assert before["volatility"]["display"] == "12,72 %"
    assert before["var_eur"]["99"]["display"] == "2 035,90 €"


def test_the_weights_split_the_invested_pocket_and_leave_cash(store: Path) -> None:
    content = proposal(store, {"method": "parite_de_risque"})
    invested = content["invested_eur"]["value"]
    assert math.isclose(
        content["value_eur"]["value"], invested + content["cash_eur"]["value"], rel_tol=1e-12
    )
    assert math.isclose(math.fsum(values(content, "target_weight").values()), 1.0, abs_tol=1e-9)
    assert math.isclose(math.fsum(values(content, "current_weight").values()), 1.0, abs_tol=1e-9)
    for line in content["lines"]:
        target = line["target_weight"]["value"] * invested
        assert math.isclose(line["target_value_eur"]["value"], target, rel_tol=1e-12)
    for shares in ("risk_share_before", "risk_share_after"):
        assert math.isclose(math.fsum(values(content, shares).values()), 1.0, abs_tol=1e-9)
    assert max(abs(s - 0.1) for s in values(content, "risk_share_after").values()) < 1e-4
    by_sector = math.fsum(s["target_weight"]["value"] for s in content["sectors"])
    assert math.isclose(by_sector, 1.0, abs_tol=1e-9)


def test_the_constraints_are_echoed_and_honoured(store: Path) -> None:
    content = proposal(
        store,
        {
            "method": "variance_minimale",
            "max_weight": 0.2,
            "max_turnover": 0.3,
            "sector_caps": [{"sector": "Matières premières", "max_weight": 0.1}],
        },
    )
    applied = content["constraints"]
    assert applied["long_only"] is True and applied["leverage"] is False
    assert applied["max_weight"]["value"] == 0.2 and applied["max_turnover"]["value"] == 0.3
    assert applied["sector_caps"][0]["sector"] == "Matières premières"
    assert max(values(content, "target_weight").values()) <= 0.2 + 1e-6
    assert content["turnover"]["value"] <= 0.3 + 1e-6
    (metals,) = [s for s in content["sectors"] if s["sector"] == "Matières premières"]
    assert metals["target_weight"]["value"] <= 0.1 + 1e-6


def test_no_operation_list_while_the_costs_are_unknown(store: Path) -> None:
    content = proposal(store, {"method": "variance_minimale"})
    assert content["trades"] is None and content["totals"] is None
    assert [u["measure"] for u in content["unavailable"]] == ["operations"]
    assert "D13" in content["unavailable"][0]["reason"]


def test_known_costs_give_whole_operations_and_their_fees(store: Path, config_dir: Path) -> None:
    edit(config_dir, "risk.yaml", COSTS, KNOWN_COSTS)
    content = proposal(store, {"method": "parite_de_risque"}, config_dir=config_dir)
    assert content["unavailable"] == [] and content["trades"]
    lines = {line["line"]: line for line in content["lines"]}
    buys, sells, fees = [], [], []
    for trade in content["trades"]:
        units = trade["quantity"]["value"]
        assert units == int(units) and units > 0
        amount = trade["amount_eur"]["value"]
        assert math.isclose(amount, units * trade["price_eur"]["value"], rel_tol=1e-12)
        assert math.isclose(trade["commission_eur"]["value"], max(amount * 0.001, 2.0))
        assert math.isclose(trade["slippage_eur"]["value"], amount * 5 / 10_000)
        foreign = trade["currency"] != "EUR"
        assert math.isclose(trade["fx_eur"]["value"], amount * 25 / 10_000 if foreign else 0.0)
        line = lines[trade["line"]]
        gap = line["target_value_eur"]["value"] - line["value_eur"]["value"]
        assert (gap > 0) is (trade["side"] == "achat")
        assert amount <= abs(gap) + 1e-6  # truncated toward zero
        assert abs(gap) - amount < trade["price_eur"]["value"]
        (buys if trade["side"] == "achat" else sells).append(amount)
        fees.append(trade["fees_eur"]["value"])
    totals = content["totals"]
    assert totals["orders"]["value"] == len(content["trades"])
    change = math.fsum(sells) - math.fsum(buys) - math.fsum(fees)
    assert math.isclose(totals["cash_change_eur"]["value"], change, rel_tol=1e-9)
    after = content["cash_eur"]["value"] + change
    assert math.isclose(totals["cash_after_eur"]["value"], after, rel_tol=1e-12)
    assert any("frais de change" in a for a in content["method"]["assumptions"])
    figures, loose = figures_in(content)
    assert loose == [] and len({f.id for f in figures}) == len(figures)


def test_the_status_follows_the_autonomy_level(store: Path, config_dir: Path) -> None:
    """Changed in a copy only: the versioned autonomy stays N0 (Claude Code never raises it)."""
    assert proposal(store, {"method": "hrp"})["status"] == "analyse"
    text = (config_dir / "autonomy.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert data["domains"]["finance"]["level"] == "N0"
    data["domains"]["finance"]["level"] = "N1"
    (config_dir / "autonomy.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    content = proposal(store, {"method": "hrp"}, config_dir=config_dir)
    assert content["status"] == "proposition non exécutée"
    assert content["autonomy_level"] == "N1"


def test_mean_variance_runs_once_owner_sets_the_risk_aversion(
    store: Path, config_dir: Path
) -> None:
    edit(config_dir, "risk.yaml", "risk_aversion: A_DEFINIR", "risk_aversion: 4")
    content = proposal(store, {"method": "moyenne_variance"}, config_dir=config_dir)
    assert content["method"]["risk_aversion"]["value"] == 4.0
    assert any("moyenne historique" in a for a in content["method"]["assumptions"])
    assert math.isclose(math.fsum(values(content, "target_weight").values()), 1.0, abs_tol=1e-9)


def test_an_infeasible_set_of_constraints_is_refused(store: Path) -> None:
    caps = [{"sector": s, "max_weight": 0.05} for s in ("Souverain", "Technologie")]
    text = error_text(
        call(store, {"method": "variance_minimale", "max_weight": 0.11, "sector_caps": caps})
    )
    assert "plafonds sectoriels trop bas" in text


def test_a_broken_configuration_is_not_echoed(store: Path, config_dir: Path) -> None:
    edit(config_dir, "risk.yaml", "covariance: ledoit_wolf", "covariance: [MARQUEUR-SECRET")
    text = error_text(call(store, {"method": "hrp"}, config_dir=config_dir))
    assert INVALID_CONFIG in text and "MARQUEUR-SECRET" not in text


def test_a_missing_store_says_how_to_fill_it(tmp_path: Path) -> None:
    result = call(tmp_path / "finance.db", {"method": "hrp"})
    assert "base finance absente (finance.db) : lancer `cerveau finance sync`" in error_text(result)
    assert not (tmp_path / "finance.db").exists()


def test_reading_never_writes_the_store(store: Path) -> None:
    before = hashlib.sha256(store.read_bytes()).hexdigest()
    call(store, {"method": "cvar_minimale", "strict": True})
    call(store, {"method": "variance_minimale", "max_turnover": 0.2})
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
