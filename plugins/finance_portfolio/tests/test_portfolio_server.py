"""The finance_portfolio MCP server, called in process through the SDK client."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult

from core.finance.fixtures import (
    REFERENCE_DIR,
    REFERENCE_FETCHED_AT,
    REFERENCE_QUALITY,
    REFERENCE_READ_AT,
    REFERENCE_WINDOW,
    load_reference,
    reference_store,
)
from core.finance.portfolio import import_transactions, reconcile
from core.finance.store import FinanceStore
from core.finance.sync import import_instruments
from core.registry.manifest import validate_plugin
from core.verification.figures import figures_in
from plugins.finance_portfolio import server as server_module
from plugins.finance_portfolio.server import build_server

PLUGIN = Path(__file__).resolve().parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
SPECS = {tool["name"]: tool for tool in MANIFEST["tools"]}
GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]
HEADER = "date,compte,type,identifiant,quantite,prix,devise,frais,montant,libelle\n"


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return reference_store(tmp_path_factory.mktemp("finance") / "finance.db")


def run(server: Any, action: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def call(store: Path, arguments: dict[str, Any] | None = None) -> CallToolResult:
    server = build_server(store, lambda: REFERENCE_READ_AT)
    return run(server, lambda c: c.call_tool("portfolio_snapshot", arguments or {}))


def error_text(result: CallToolResult) -> str:
    assert result.is_error
    return " ".join(getattr(block, "text", "") for block in result.content)


def compact(result: CallToolResult) -> str:
    """The structured output as the golden set matches it: compact JSON, accents kept."""
    assert not result.is_error, error_text(result)
    return json.dumps(result.structured_content, ensure_ascii=False, separators=(",", ":"))


def test_the_plugin_passes_the_registry() -> None:
    report = validate_plugin(PLUGIN)
    assert report.ok, report.errors
    assert report.plugin_id == "finance_portfolio"


def test_published_tools_match_the_manifest(tmp_path: Path) -> None:
    tools = run(build_server(tmp_path / "finance.db"), lambda c: c.list_tools()).tools
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


@pytest.mark.parametrize("as_of", [None, "2026-10-16T20:00:00Z", "2025-01-10T20:00:00Z"])
def test_every_number_is_a_traceable_figure(store: Path, as_of: str | None) -> None:
    result = call(store, {"as_of": as_of} if as_of else {})
    figures, loose = figures_in(result.structured_content)
    assert len(figures) > 50
    assert loose == []
    ids = [f.id for f in figures]
    assert len(ids) == len(set(ids))


def test_values_and_weights_add_up(store: Path) -> None:
    snapshot = call(store).structured_content
    total = snapshot["total_eur"]["value"]
    lines = snapshot["positions"] + snapshot["cash"]
    assert math.isclose(math.fsum(x["value_eur"]["value"] for x in lines), total, rel_tol=1e-12)
    assert math.isclose(math.fsum(x["weight"]["value"] for x in lines), 1.0, rel_tol=1e-12)
    for axis in ("sector", "country", "currency"):
        rows = snapshot["exposures"][axis]
        assert math.isclose(math.fsum(r["value_eur"]["value"] for r in rows), total, rel_tol=1e-12)
        assert math.isclose(math.fsum(r["weight"]["value"] for r in rows), 1.0, rel_tol=1e-12)
        values = [r["value_eur"]["value"] for r in rows]
        assert values == sorted(values, reverse=True)


def test_a_position_is_valued_from_its_close_and_rate(store: Path) -> None:
    snapshot = call(store).structured_content
    (emerg,) = [p for p in snapshot["positions"] if p["instrument_id"] == "FICT-EMERG"]
    assert emerg["account"] == "CTO-FICTIF"
    assert emerg["currency"] == "USD"
    quantity, close = emerg["quantity"]["value"], emerg["close"]["value"]
    rate = emerg["fx_rate"]["value"]
    assert emerg["fx_rate"]["unit"] == "USD/EUR"
    assert math.isclose(emerg["value_eur"]["value"], quantity * close / rate, rel_tol=1e-12)
    gain = quantity * close - emerg["cost"]["value"]
    assert math.isclose(emerg["unrealized_gain"]["value"], gain, rel_tol=1e-12)
    euro = [p for p in snapshot["positions"] if p["currency"] == "EUR"]
    assert euro
    assert all(p["fx_rate"] is None and p["fx_date"] is None for p in euro)


def test_before_any_known_transaction_the_book_is_empty(store: Path) -> None:
    for arguments in (
        {"as_of": "2026-10-18T11:00:00Z", "strict": True},  # imported at 12:00
        {"as_of": "2023-10-01T12:00:00Z"},  # before the first deposit
    ):
        snapshot = call(store, arguments).structured_content
        assert snapshot["positions"] == [] and snapshot["cash"] == []
        assert snapshot["total_eur"]["display"] == "0,00 €"
        assert snapshot["warnings"] == [
            "aucune transaction connue à cette date (import : `cerveau portfolio import`)"
        ]


def _market_store(path: Path) -> FinanceStore:
    store = FinanceStore.open(path)
    load_reference(store, quality=REFERENCE_QUALITY, window_sessions=REFERENCE_WINDOW)
    import_transactions(
        store, REFERENCE_DIR / "transactions.csv", "cerveau", imported_at=REFERENCE_FETCHED_AT
    )
    return store


def test_a_gap_raises_the_alert_without_its_quantities(tmp_path: Path) -> None:
    """ADR-018: the planner learns that an account differs and on which asset; how much is
    for the CLI. The statement file is not named either."""
    statement = tmp_path / "releve-secret-name.csv"
    text = (REFERENCE_DIR / "releve.csv").read_text(encoding="utf-8")
    assert "2026-10-16,PEA-FICTIF,titre,FICT-ACME,200\n" in text
    statement.write_text(
        text.replace("PEA-FICTIF,titre,FICT-ACME,200\n", "PEA-FICTIF,titre,FICT-ACME,213\n"),
        encoding="utf-8",
    )
    path = tmp_path / "finance.db"
    with _market_store(path) as store:
        reconcile(store, statement, at=REFERENCE_FETCHED_AT)
    result = call(path)
    snapshot = result.structured_content
    assert snapshot["alert"] == "rapprochement: ecart"
    status = {a["account"]: a for a in snapshot["reconciliation"]}
    assert status["PEA-FICTIF"]["status"] == "ecart"
    assert status["PEA-FICTIF"]["gaps"] == [{"nature": "titre", "asset": "FICT-ACME"}]
    assert status["CTO-FICTIF"]["status"] == "ok"
    figures, _ = figures_in(snapshot)
    assert all(f.value not in (13.0, 213.0) for f in figures)
    text = compact(result)
    assert "213" not in text and "releve" not in text


def test_an_unreconciled_account_is_said_so(tmp_path: Path) -> None:
    path = tmp_path / "finance.db"
    _market_store(path).close()
    snapshot = call(path).structured_content
    assert {a["status"] for a in snapshot["reconciliation"]} == {"non_rapproche"}
    assert snapshot["alert"] is None


def test_a_missing_close_leaves_the_total_absent_not_partial(tmp_path: Path) -> None:
    """R12: no closes in the store, so no total, no weight and no exposure."""
    path = tmp_path / "finance.db"
    transactions = tmp_path / "transactions.csv"
    transactions.write_text(
        HEADER
        + "2026-10-01,PEA-TEST,depot,,1000.00,,EUR,,,\n"
        + "2026-10-02,PEA-TEST,achat,FICT-ACME,10,40.00,EUR,1.00,,\n",
        encoding="utf-8",
    )
    with FinanceStore.open(path) as store:
        import_instruments(
            store, REFERENCE_DIR / "instruments.csv", recorded_at=REFERENCE_FETCHED_AT
        )
        import_transactions(store, transactions, "cerveau", imported_at=REFERENCE_FETCHED_AT)
    snapshot = call(path).structured_content
    assert snapshot["total_eur"] is None
    assert snapshot["missing"] == ["FICT-ACME"]
    assert snapshot["exposures"] is None
    (position,) = snapshot["positions"]
    assert position["close"] is None and position["value_eur"] is None
    assert position["weight"] is None and position["unrealized_gain"] is None
    assert position["cost"]["display"] == "401,00 €"
    assert position["average_price"]["display"] == "40,10 €"
    (cash,) = snapshot["cash"]
    assert cash["balance"]["display"] == "599,00 €"
    assert cash["weight"] is None


def test_a_missing_store_says_how_to_fill_it(tmp_path: Path) -> None:
    result = call(tmp_path / "finance.db")
    assert "base finance absente (finance.db) : lancer `cerveau finance sync`" in error_text(result)
    assert not (tmp_path / "finance.db").exists()


def test_reading_never_writes_the_store(store: Path) -> None:
    before = hashlib.sha256(store.read_bytes()).hexdigest()
    call(store)
    call(store, {"strict": True})
    assert hashlib.sha256(store.read_bytes()).hexdigest() == before


def test_main_serves_the_store_of_cerveau_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    served: list[Path] = []

    class Stub:
        def run(self) -> None:
            served.append(Path("ran"))

    def fake_build(store: Path) -> Stub:
        served.append(store)
        return Stub()

    monkeypatch.setattr(server_module, "build_server", fake_build)
    monkeypatch.setenv("CERVEAU_HOME", str(tmp_path))
    server_module.main()
    assert served == [tmp_path / "var" / "finance" / "finance.db", Path("ran")]
