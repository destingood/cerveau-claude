"""The MCP server, called in process through the SDK client, against its manifest."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult

from core.net.allowlist import ALLOWLIST_ENV
from core.net.guard import FetchError
from core.registry.manifest import validate_plugin
from plugins.web_research import server as server_module
from plugins.web_research.fetcher import WebReader
from plugins.web_research.models import MAX_RESULTS, PageText
from plugins.web_research.search import Hit, SearchError
from plugins.web_research.server import build_server

PLUGIN = Path(__file__).resolve().parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
SPECS = {tool["name"]: tool for tool in MANIFEST["tools"]}
PAGE = PageText(
    url="https://example.org/a",
    final_url="https://example.org/a",
    content_type="text/html",
    title="Titre",
    published=None,
    text="Texte de la page.",
    truncated=False,
    retrieved_at="2026-10-18T12:00:00+00:00",
)


class FakeProvider:
    name = "fake"

    def __init__(self, hits: list[Hit] | None = None, error: str | None = None) -> None:
        self.hits, self.error = hits or [], error
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, count: int) -> list[Hit]:
        self.calls.append((query, count))
        if self.error:
            raise SearchError(self.error)
        return self.hits


class FakeReader:
    def __init__(self, error: str | None = None) -> None:
        self.error = error

    async def read(self, raw_url: str) -> PageText:
        if self.error:
            raise FetchError(self.error)
        return PAGE


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
    assert report.plugin_id == "web_research"


def test_published_tools_match_the_manifest() -> None:
    tools = run(build_server(None, FakeReader()), lambda c: c.list_tools()).tools
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


def test_web_search_returns_ranked_structured_results() -> None:
    hits = [Hit("Un", "https://a.example/", "a", "1 jour"), Hit("Deux", "https://b.example/", "b")]
    provider = FakeProvider(hits)
    result = call(build_server(provider, FakeReader()), "web_search", {"query": "thé"})
    assert not result.is_error
    assert provider.calls == [("thé", 5)]
    assert result.structured_content == {
        "query": "thé",
        "provider": "fake",
        "results": [
            {
                "rank": 1,
                "title": "Un",
                "url": "https://a.example/",
                "snippet": "a",
                "age": "1 jour",
            },
            {"rank": 2, "title": "Deux", "url": "https://b.example/", "snippet": "b", "age": None},
        ],
    }


def test_web_search_never_returns_more_than_asked() -> None:
    provider = FakeProvider([Hit(f"T{i}", f"https://{i}.example/", "") for i in range(10)])
    result = call(
        build_server(provider, FakeReader()), "web_search", {"query": "q", "max_results": 2}
    )
    assert len(result.structured_content["results"]) == 2


def test_web_search_without_a_key_is_an_error() -> None:
    result = call(build_server(None, FakeReader()), "web_search", {"query": "q"})
    assert "BRAVE_SEARCH_API_KEY absente" in error_text(result)


def test_search_errors_become_tool_errors() -> None:
    server = build_server(FakeProvider(error="Brave : quota ou débit dépassé"), FakeReader())
    assert "quota" in error_text(call(server, "web_search", {"query": "q"}))


def test_web_read_returns_the_page() -> None:
    result = call(build_server(None, FakeReader()), "web_read", {"url": PAGE.url})
    assert result.structured_content == PAGE.model_dump()


def test_fetch_errors_become_tool_errors() -> None:
    server = build_server(None, FakeReader(error="URL refusée : hôte absent"))
    assert "hôte absent" in error_text(call(server, "web_read", {"url": "http:///"}))


def _offline_reader() -> WebReader:
    async def no_dns(host: str, port: int) -> list[str]:
        raise OSError("offline")

    def no_web(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request to {request.url}")

    return WebReader(resolver=no_dns, transport=httpx.MockTransport(no_web))


GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]


@pytest.mark.parametrize("case", GOLDEN, ids=[case["id"] for case in GOLDEN])
def test_golden_cases(case: dict[str, Any]) -> None:
    """The plugin golden set is offline: every case is a refusal decided before any request."""
    server = build_server(FakeProvider(), _offline_reader())
    result = call(server, case["tool"], case["arguments"])
    assert result.is_error is case["expected"]["is_error"]
    assert case["expected"]["contains"] in error_text(result)


def test_main_reads_the_key_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[Any] = []

    class Stub:
        def run(self) -> None:
            built.append("run")

    def fake_build(provider: Any, reader: Any, allowlist: Any = None) -> Stub:
        built.append(provider)
        assert allowlist is None and reader.allowlist is None  # no list: the web stays open
        return Stub()

    monkeypatch.setattr(server_module, "build_server", fake_build)
    monkeypatch.delenv(ALLOWLIST_ENV, raising=False)
    monkeypatch.setenv(server_module.API_KEY_ENV, " test-key-not-a-secret ")
    server_module.main()
    monkeypatch.delenv(server_module.API_KEY_ENV)
    server_module.main()
    provider, _, missing, _ = built
    assert provider.api_key == "test-key-not-a-secret"
    assert missing is None


def test_main_hands_the_list_of_the_environment_to_the_search_and_the_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[Any] = []

    class Stub:
        def run(self) -> None:
            pass

    def fake_build(provider: Any, reader: Any, allowlist: Any = None) -> Stub:
        built.append((allowlist, reader.allowlist))
        return Stub()

    monkeypatch.setattr(server_module, "build_server", fake_build)
    monkeypatch.setenv(ALLOWLIST_ENV, "legifrance.gouv.fr,*.bad,service-public.gouv.fr")
    server_module.main()
    expected = frozenset({"legifrance.gouv.fr", "service-public.gouv.fr"})
    assert built == [(expected, expected)]


def test_web_search_with_a_list_drops_the_results_off_it() -> None:
    hits = [
        Hit("Hors liste", "https://blog.example/code-civil", ""),
        Hit("Article", "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006419292", ""),
        Hit("Usurpateur", "https://legifrance.gouv.fr.evil.example/", ""),
        Hit("Fiche", "https://www.service-public.gouv.fr/particuliers/vosdroits/F1", ""),
    ]
    provider = FakeProvider(hits)
    allowlist = frozenset({"legifrance.gouv.fr", "service-public.gouv.fr"})
    server = build_server(provider, FakeReader(), allowlist)
    result = call(server, "web_search", {"query": "bail", "max_results": 1})
    assert provider.calls == [("bail", MAX_RESULTS)]  # more asked, since some are dropped
    titles = [r["title"] for r in result.structured_content["results"]]
    assert titles == ["Article"]
    result = call(server, "web_search", {"query": "bail"})
    assert [r["rank"] for r in result.structured_content["results"]] == [1, 2]
