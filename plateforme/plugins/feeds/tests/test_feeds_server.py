"""The MCP server, called in process through the SDK client, against its manifest."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult

from core.registry.manifest import validate_plugin
from plugins.feeds import server as server_module
from plugins.feeds.allowlist import FeedSource, load_allowlist
from plugins.feeds.models import FeedError
from plugins.feeds.reader import FeedReader
from plugins.feeds.server import build_server
from plugins.feeds.tests.support import (
    CATALOG,
    FEED_URL,
    FIXED_NOW,
    STAMP,
    FakeReader,
    rss,
    rss_item,
)

PLUGIN = Path(__file__).resolve().parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
SPECS = {tool["name"]: tool for tool in MANIFEST["tools"]}


def _server(
    reader: FakeReader, catalog: Callable[[], Mapping[str, FeedSource]] = lambda: CATALOG
) -> Any:
    return build_server(catalog, reader, now=lambda: FIXED_NOW)


def run(server: Any, action: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def call(server: Any, arguments: dict[str, Any]) -> CallToolResult:
    return run(server, lambda c: c.call_tool("feed_read", arguments))


def error_text(result: CallToolResult) -> str:
    assert result.is_error
    return " ".join(getattr(block, "text", "") for block in result.content)


def test_the_plugin_passes_the_registry() -> None:
    report = validate_plugin(PLUGIN)
    assert report.ok, report.errors
    assert report.plugin_id == "feeds"


def test_published_tools_match_the_manifest() -> None:
    tools = run(_server(FakeReader()), lambda c: c.list_tools()).tools
    assert [t.name for t in tools] == list(SPECS)
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


def test_a_feed_is_read_from_its_allow_listed_url() -> None:
    items = [
        rss_item("Ancien", pub_date="Mon, 20 Oct 2026 08:00:00 GMT"),
        rss_item("Un", pub_date="Tue, 21 Oct 2026 08:00:00 GMT"),
        rss_item("Deux", pub_date="Wed, 22 Oct 2026 08:00:00 GMT"),
    ]
    reader = FakeReader(rss(items))
    result = call(_server(reader), {"feed": "exemple", "since": "2026-10-21", "max_entries": 1})
    assert not result.is_error
    assert reader.urls == [FEED_URL]
    data = result.structured_content
    assert data is not None
    assert data["feed"] == "exemple"
    assert data["name"] == "Flux d'exemple"
    assert data["url"] == FEED_URL
    assert data["licence"] == "CC BY 4.0"
    assert data["since"] == "2026-10-21"
    assert data["feed_title"] == "Flux RSS"
    assert [e["title"] for e in data["entries"]] == ["Un"]
    assert (data["skipped"], data["more_entries"]) == (1, 1)
    assert data["retrieved_at"] == STAMP


@pytest.mark.parametrize(
    ("reader", "message"),
    [
        (FakeReader(error="réponse HTTP 404"), "flux « exemple » : réponse HTTP 404"),
        (FakeReader(b"<html/>"), "flux « exemple » : format non pris en charge"),
    ],
)
def test_read_and_parse_errors_become_tool_errors(reader: FakeReader, message: str) -> None:
    assert message in error_text(call(_server(reader), {"feed": "exemple"}))


def test_refusals_are_decided_before_any_request() -> None:
    reader = FakeReader(rss([rss_item()]))
    for arguments in ({"feed": "inconnu"}, {"feed": "licence-a-verifier"}):
        assert call(_server(reader), arguments).is_error
    assert reader.urls == []


def test_the_allow_list_is_read_at_each_call() -> None:
    lists: list[Mapping[str, FeedSource]] = [{}, CATALOG]
    reader = FakeReader(rss([rss_item()]))
    server = _server(reader, lambda: lists.pop(0))
    assert "vide" in error_text(call(server, {"feed": "exemple"}))
    assert not call(server, {"feed": "exemple"}).is_error


def _broken() -> Mapping[str, FeedSource]:
    raise FeedError("liste blanche des flux illisible")


CATALOGS: dict[str, Callable[[], Mapping[str, FeedSource]]] = {
    "exemple": lambda: CATALOG,
    "vide": dict,
    "illisible": _broken,
}
GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]


@pytest.mark.parametrize("case", GOLDEN, ids=[case["id"] for case in GOLDEN])
def test_golden_cases(case: dict[str, Any]) -> None:
    """The plugin golden set is offline: every case is a refusal decided before any request."""
    reader = FakeReader(error="aucune requête n'est permise dans le golden set")
    catalog = CATALOGS[case.get("allowlist", "exemple")]
    result = call(_server(reader, catalog), case["arguments"])
    assert result.is_error is case["expected"]["is_error"]
    assert case["expected"]["contains"] in error_text(result)
    assert reader.urls == []


def test_main_reads_the_allow_list_and_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[Any] = []

    class Stub:
        def run(self) -> None:
            built.append("run")

    def fake_build(catalog: Any, reader: Any) -> Stub:
        built.extend([catalog, reader])
        return Stub()

    monkeypatch.setattr(server_module, "build_server", fake_build)
    server_module.main()
    catalog, reader, ran = built
    assert catalog is load_allowlist
    assert isinstance(reader, FeedReader)
    assert reader.transport is None
    assert ran == "run"


def test_utcnow_is_aware() -> None:
    assert server_module.utcnow().utcoffset() is not None
    assert server_module.utcnow().date() >= date(2026, 1, 1)
