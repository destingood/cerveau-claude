"""The MCP server, called in process through the SDK client, against its manifest."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult

from core.net.throttle import SharedThrottle
from core.registry.manifest import validate_plugin
from plugins.scholarly import server as server_module
from plugins.scholarly.arxiv import ArxivSource
from plugins.scholarly.common import THROTTLE_DIR, Fetcher, ScholarError
from plugins.scholarly.crossref import CrossrefSource
from plugins.scholarly.models import ScholarRecord
from plugins.scholarly.server import build_server
from plugins.scholarly.tests.support import STAMP, FakeApi, entry, feed, respond

PLUGIN = Path(__file__).resolve().parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
SPECS = {tool["name"]: tool for tool in MANIFEST["tools"]}


def _record(source: str = "crossref", identifier: str = "10.1234/x") -> ScholarRecord:
    return ScholarRecord(
        source=source,  # type: ignore[arg-type]
        identifier=identifier,
        type="journal-article",
        preprint=False,
        title="Titre",
        authors=["Ada Lovelace"],
        more_authors=0,
        published="2024-02-05",
        updated=None,
        venue=None,
        doi=identifier,
        url=f"https://doi.org/{identifier}",
        abstract=None,
        abstract_truncated=False,
        update_to=[],
        updated_by=[],
        retrieved_at=STAMP,
    )


class FakeSource:
    def __init__(self, name: str, error: str | None = None) -> None:
        self.name, self.error = name, error
        self.searches: list[tuple[str, date | None, int]] = []
        self.lookups: list[str] = []

    async def search(self, query: str, since: date | None, max_results: int) -> list[ScholarRecord]:
        self.searches.append((query, since, max_results))
        if self.error:
            raise ScholarError(self.error)
        return [_record(self.name)]

    async def record(self, identifier: str) -> ScholarRecord:
        self.lookups.append(identifier)
        if self.error:
            raise ScholarError(self.error)
        return _record(self.name, identifier)


def _fakes(error: str | None = None) -> dict[str, FakeSource]:
    return {"arxiv": FakeSource("arxiv", error), "crossref": FakeSource("crossref", error)}


def run(server: Any, action: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def call(server: Any, tool: str, arguments: dict[str, Any]) -> CallToolResult:
    return run(server, lambda c: c.call_tool(tool, arguments))


def error_text(result: CallToolResult) -> str:
    assert result.is_error
    return " ".join(getattr(block, "text", "") for block in result.content)


def test_the_plugin_passes_the_registry() -> None:
    report = validate_plugin(PLUGIN)
    assert report.ok, report.errors
    assert report.plugin_id == "scholarly"


def test_published_tools_match_the_manifest() -> None:
    tools = run(build_server(_fakes()), lambda c: c.list_tools()).tools  # type: ignore[arg-type]
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


def test_search_returns_structured_results() -> None:
    sources = _fakes()
    arguments = {"query": "graphes", "source": "crossref", "since": "2024-02-05"}
    result = call(build_server(sources), "scholar_search", arguments)  # type: ignore[arg-type]
    assert not result.is_error
    assert sources["crossref"].searches == [("graphes", date(2024, 2, 5), 5)]
    assert sources["arxiv"].searches == []
    assert result.structured_content == {
        "query": "graphes",
        "source": "crossref",
        "since": "2024-02-05",
        "records": [_record().model_dump()],
    }


def test_search_errors_become_tool_errors() -> None:
    server = build_server(_fakes(error="Crossref : débit dépassé"))  # type: ignore[arg-type]
    result = call(server, "scholar_search", {"query": "q", "source": "crossref"})
    assert error_text(result).endswith("Crossref : débit dépassé")


@pytest.mark.parametrize(
    ("identifier", "key"),
    [
        ("10.1038/nature14539", "10.1038/nature14539"),
        (" https://doi.org/10.1038/nature14539 ", "10.1038/nature14539"),
        ("http://dx.doi.org/10.1103/PhysRevLett.116.061102", "10.1103/PhysRevLett.116.061102"),
        ("DOI:10.1145/3065386", "10.1145/3065386"),
    ],
)
def test_record_sends_dois_to_crossref(identifier: str, key: str) -> None:
    sources = _fakes()
    result = call(build_server(sources), "scholar_record", {"identifier": identifier})  # type: ignore[arg-type]
    assert not result.is_error
    assert sources["crossref"].lookups == [key]
    assert sources["arxiv"].lookups == []
    assert result.structured_content == _record("crossref", key).model_dump()


@pytest.mark.parametrize(
    ("identifier", "key"),
    [
        ("1706.03762", "1706.03762"),
        ("arXiv:1706.03762v7", "1706.03762v7"),
        ("hep-th/9901001", "hep-th/9901001"),
    ],
)
def test_record_sends_arxiv_identifiers_to_arxiv(identifier: str, key: str) -> None:
    sources = _fakes()
    call(build_server(sources), "scholar_record", {"identifier": identifier})  # type: ignore[arg-type]
    assert sources["arxiv"].lookups == [key]
    assert sources["crossref"].lookups == []


@pytest.mark.parametrize("identifier", ["10.1234/../../members", "doi:10.1234/./x"])
def test_record_refuses_dois_with_dot_segments(identifier: str) -> None:
    sources = _fakes()
    result = call(build_server(sources), "scholar_record", {"identifier": identifier})  # type: ignore[arg-type]
    assert "identifiant non reconnu" in error_text(result)
    assert sources["crossref"].lookups == sources["arxiv"].lookups == []


def test_record_errors_become_tool_errors() -> None:
    server = build_server(_fakes(error="arXiv : identifiant inconnu"))  # type: ignore[arg-type]
    result = call(server, "scholar_record", {"identifier": "2401.99999"})
    assert error_text(result).endswith("arXiv : identifiant inconnu")


def test_a_search_through_the_real_sources_reaches_arxiv_only(tmp_path: Path) -> None:
    api = FakeApi(lambda _: respond(feed(entry())))
    sources = {
        "arxiv": ArxivSource(api.fetcher(tmp_path)),
        "crossref": CrossrefSource(api.fetcher(tmp_path, label="Crossref")),
    }
    result = call(build_server(sources), "scholar_search", {"query": "graph", "source": "arxiv"})  # type: ignore[arg-type]
    assert [r["identifier"] for r in result.structured_content["records"]] == ["2401.01234v2"]
    assert [request.url.host for request in api.requests] == ["export.arxiv.org"]


def _offline_sources(directory: Path) -> dict[str, Any]:
    def no_web(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request to {request.url}")

    api = FakeApi(no_web)
    return {
        "arxiv": ArxivSource(api.fetcher(directory)),
        "crossref": CrossrefSource(api.fetcher(directory, label="Crossref")),
    }


GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]


@pytest.mark.parametrize("case", GOLDEN, ids=[case["id"] for case in GOLDEN])
def test_golden_cases(tmp_path: Path, case: dict[str, Any]) -> None:
    """The plugin golden set is offline: every case is a refusal decided before any request."""
    result = call(build_server(_offline_sources(tmp_path)), case["tool"], case["arguments"])
    assert result.is_error is case["expected"]["is_error"]
    assert case["expected"]["contains"] in error_text(result)


def test_main_builds_the_two_rate_limited_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[Any] = []

    class Stub:
        def run(self) -> None:
            built.append("run")

    def fake_build(sources: dict[str, Any]) -> Stub:
        built.append(sources)
        return Stub()

    monkeypatch.setattr(server_module, "build_server", fake_build)
    server_module.main()
    sources, ran = built
    assert ran == "run"
    assert isinstance(sources["arxiv"], ArxivSource)
    assert isinstance(sources["crossref"], CrossrefSource)
    for name, interval in (("arxiv", 3.0), ("crossref", 1.0)):
        fetcher: Fetcher = sources[name].fetcher
        throttle: SharedThrottle = fetcher.throttle
        assert fetcher.transport is None
        assert throttle.lock_path == THROTTLE_DIR / f"{name}.lock"
        assert throttle.interval_s == interval
