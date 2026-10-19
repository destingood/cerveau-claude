"""The finance_data MCP server, called in process through the SDK client, on the reference store."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult

from core.finance.fixtures import REFERENCE_READ_AT, reference_store
from core.registry.manifest import validate_plugin
from core.verification.figures import figures_in
from plugins.finance_data import server as server_module
from plugins.finance_data.server import build_server

PLUGIN = Path(__file__).resolve().parents[1]
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


def run(server: Any, action: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def call(store: Path, arguments: dict[str, Any]) -> CallToolResult:
    server = build_server(store, lambda: REFERENCE_READ_AT)
    return run(server, lambda c: c.call_tool("market_data", arguments))


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
    assert report.plugin_id == "finance_data"


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
    """Offline: the reference store, read at REFERENCE_READ_AT."""
    result = call(store, case["arguments"])
    assert result.is_error is case["expected"]["is_error"]
    text = error_text(result) if result.is_error else compact(result)
    assert case["expected"]["contains"] in text


def test_every_number_is_a_traceable_figure(store: Path) -> None:
    for arguments in (
        {"instruments": ["FICT-ACME", "FICT-GLOBEX", "FICT-OAT35"], "sessions": 260},
        {"instruments": ["FICT-OAT35", "FICT-MONDE"], "kind": "referentiel"},
    ):
        result = call(store, arguments)
        figures, loose = figures_in(result.structured_content)
        assert figures
        assert loose == []
        ids = [f.id for f in figures]
        assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    ("as_of", "day", "last"),
    [
        # Already the 16th in Paris, but its session has not traded yet.
        ("2026-10-15T22:30:00Z", "2026-10-16", {"FICT-ACME": "2026-10-15"}),
        # Paris trades on the 16th: its close is not known before the session ends.
        ("2026-10-16T12:00:00Z", "2026-10-16", {"FICT-ACME": "2026-10-15"}),
        # Paris has closed, New York has not.
        (
            "2026-10-16T20:00:00Z",
            "2026-10-16",
            {"FICT-ACME": "2026-10-16", "FICT-GLOBEX": "2026-10-15"},
        ),
    ],
)
def test_a_close_is_read_only_once_it_was_known(
    store: Path, as_of: str, day: str, last: dict[str, str]
) -> None:
    """R10: the Paris date of as_of bounds the sessions, and a close counts once published."""
    result = call(store, {"instruments": list(last), "as_of": as_of})
    assert result.structured_content["day"] == day
    for series in result.structured_content["series"]:
        assert series["last_session"] == last[series["instrument_id"]]
        assert all(close["session"] <= series["last_session"] for close in series["closes"])
        assert len(series["closes"]) == 20


def test_sessions_counts_the_last_closes(store: Path) -> None:
    result = call(store, {"instruments": ["FICT-OAT35"], "sessions": 3})
    closes = result.structured_content["series"][0]["closes"]
    assert [c["session"] for c in closes] == ["2026-10-14", "2026-10-15", "2026-10-16"]
    assert [c["close"]["display"] for c in closes] == ["79,71 €", "80,73 €", "80,61 €"]


def test_an_instrument_asked_twice_is_read_once(store: Path) -> None:
    result = call(store, {"instruments": ["FICT-ACME", "FICT-ACME"], "sessions": 1})
    assert [s["instrument_id"] for s in result.structured_content["series"]] == ["FICT-ACME"]


def test_strict_reads_only_what_was_recorded_by_as_of(store: Path) -> None:
    """The reference was ingested at 12:00 UTC on 18 October: at 11:00 strict, nothing is known;
    not strict, the closes of the past are read as the store holds them now."""
    loose = call(store, {"instruments": ["FICT-ACME"], "as_of": "2026-10-18T11:00:00Z"})
    assert loose.structured_content["series"][0]["last_session"] == "2026-10-16"
    strict = call(
        store, {"instruments": ["FICT-ACME"], "as_of": "2026-10-18T11:00:00Z", "strict": True}
    )
    assert "absent du référentiel" in error_text(strict)


def test_the_quality_score_is_the_last_one_recorded(store: Path) -> None:
    result = call(store, {"instruments": ["FICT-GLOBEX"], "sessions": 1})
    quality = result.structured_content["series"][0]["quality"]
    assert quality["assessed_at"] <= REFERENCE_READ_AT.isoformat()
    assert quality["score"]["unit"] == "score"
    assert 0.0 <= quality["score"]["value"] <= 1.0
    subscores = ("gaps", "corporate_actions", "outliers", "freshness")
    assert quality["score"]["value"] == min(quality[name]["value"] for name in subscores)


def test_the_reference_card_carries_no_free_text(store: Path) -> None:
    result = call(store, {"instruments": ["FICT-OAT35"], "kind": "referentiel"})
    (card,) = result.structured_content["cards"]
    assert set(card) == {
        "instrument_id",
        "name",
        "asset_class",
        "currency",
        "mic",
        "sector",
        "country",
        "isin",
        "valid_from",
        "valid_to",
        "duration",
        "duration_note",
    }
    assert card["asset_class"] == "bond"
    assert card["duration"]["id"] == "FICT-OAT35/duration"
    assert date.fromisoformat(card["valid_from"]) == date(2023, 10, 16)


def test_a_missing_store_says_how_to_fill_it(tmp_path: Path) -> None:
    result = call(tmp_path / "finance.db", {"instruments": ["FICT-ACME"]})
    assert "base finance absente (finance.db) : lancer `cerveau finance sync`" in error_text(result)
    assert not (tmp_path / "finance.db").exists()


def test_a_file_that_is_not_a_store_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "finance.db"
    path.write_bytes(b"ceci n'est pas une base SQLite" * 100)
    assert "base finance illisible" in error_text(call(path, {"instruments": ["FICT-ACME"]}))


def test_a_stored_name_that_fails_its_checks_is_not_quoted(store: Path, tmp_path: Path) -> None:
    """R5: a record altered after its import is refused at reading, and its text never reaches
    the planner, not even in the error."""
    altered = tmp_path / "finance.db"
    shutil.copyfile(store, altered)
    conn = sqlite3.connect(altered)
    with conn:
        conn.execute(
            "UPDATE instruments SET name = ? WHERE instrument_id = 'FICT-ACME'",
            ("MARQUEUR-ALTERE\x07",),
        )
    conn.close()
    for kind in ("cours", "referentiel"):
        text = error_text(call(altered, {"instruments": ["FICT-ACME"], "kind": kind}))
        assert "ne passe plus ses contrôles à la relecture" in text
        assert "MARQUEUR" not in text


def test_reading_never_writes_the_store(store: Path) -> None:
    before = hashlib.sha256(store.read_bytes()).hexdigest()
    call(store, {"instruments": ["FICT-ACME"], "sessions": 260})
    call(store, {"instruments": ["FICT-ACME"], "kind": "referentiel"})
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
