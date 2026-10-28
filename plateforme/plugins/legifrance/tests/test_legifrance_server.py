"""The MCP server, called in process through the SDK client, against its manifest and PISTE."""

from __future__ import annotations

import asyncio
import json
import runpy
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult

from core.registry.manifest import validate_plugin
from plugins.legifrance import server as server_module
from plugins.legifrance.client import (
    ARTICLE_TTL,
    CACHE_DIR,
    DAILY_TTL,
    INTERVAL_S,
    THROTTLE_DIR,
    Environment,
)
from plugins.legifrance.legi import LegiError
from plugins.legifrance.server import Sources, build_server, build_sources
from plugins.legifrance.tests.support import (
    ART,
    FAKE_ID,
    FAKE_SECRET,
    FIXED_NOW,
    NEXT,
    OLD,
    SANDBOX,
    STAMP,
    TEXT,
    Piste,
    article,
    extract,
    respond,
    result,
    search_reply,
    version,
)

PLUGIN = Path(__file__).resolve().parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
SPECS = {tool["name"]: tool for tool in MANIFEST["tools"]}


def sources(piste: Piste, directory: Path, target: Callable[[], Environment] = lambda: SANDBOX):
    return Sources(piste.client(directory), target=target, now=lambda: FIXED_NOW)


def run(server: Any, action: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def call(piste: Piste, directory: Path, tool: str, arguments: dict[str, Any]) -> CallToolResult:
    server = build_server(sources(piste, directory))
    return run(server, lambda c: c.call_tool(tool, arguments))


def error_text(found: CallToolResult) -> str:
    assert found.is_error
    return " ".join(getattr(block, "text", "") for block in found.content)


def by_id(*replies: dict[str, Any]) -> Callable[[dict[str, Any]], Any]:
    """A getArticle route answering each version by its identifier."""
    table = {reply["article"]["id"]: reply for reply in replies}
    return lambda payload: respond(table[payload["id"]])


def test_the_plugin_passes_the_registry() -> None:
    report = validate_plugin(PLUGIN)
    assert report.ok, report.errors
    assert report.plugin_id == "legifrance"


def test_published_tools_match_the_manifest(tmp_path: Path) -> None:
    tools = run(build_server(sources(Piste(), tmp_path)), lambda c: c.list_tools()).tools
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


GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]


@pytest.mark.parametrize("case", GOLDEN, ids=[case["id"] for case in GOLDEN])
def test_golden_cases(tmp_path: Path, case: dict[str, Any]) -> None:
    """The plugin golden set is offline: every case is refused before the configuration is read."""

    def no_target() -> Environment:
        raise AssertionError("the configuration must not be read")  # pragma: no cover

    piste = Piste()
    server = build_server(sources(piste, tmp_path, no_target))
    found = run(server, lambda c: c.call_tool(case["tool"], case["arguments"]))
    assert found.is_error is case["expected"]["is_error"]
    assert case["expected"]["contains"] in error_text(found)
    assert piste.requests == []


def test_a_search_sends_the_documented_body_and_dates_each_hit(tmp_path: Path) -> None:
    payloads: list[dict[str, Any]] = []
    reply = search_reply(
        result(extract(), extract(NEXT, "1241", end="2020-01-01")),
        {"titles": [{"id": TEXT, "title": "Code civil"}], "sections": []},
        total=57,
    )

    def route(payload: dict[str, Any]) -> Any:
        payloads.append(payload)
        return respond(reply)

    piste = Piste()
    piste.routes["/search"] = route
    arguments = {"query": "  responsabilité   faute ", "max_results": 3}
    found = call(piste, tmp_path, "legi_search", arguments)
    assert not found.is_error, error_text(found)
    (payload,) = payloads
    assert payload["fond"] == "CODE_ETAT"
    search = payload["recherche"]
    assert (search["pageSize"], search["pageNumber"], search["sort"]) == (3, 1, "PERTINENCE")
    assert search["champs"][0]["criteres"][0]["valeur"] == "responsabilité faute"
    content = found.structured_content
    assert (content["query"], content["reference_date"], content["total"]) == (
        "responsabilité faute",
        "2026-10-27",
        57,
    )
    assert content["retrieved_at"] == STAMP and content["note"]
    first, second, title = content["items"]
    assert (first["article_id"], first["in_force_on_date"], first["end"]) == (ART, True, None)
    assert first["url"] == f"https://www.legifrance.gouv.fr/codes/article_lc/{ART}"
    assert (second["in_force_on_date"], second["end"]) == (False, "2020-01-01")
    assert (title["article_id"], title["url"], title["in_force_on_date"]) == (None, None, None)


def test_a_dated_search_in_laws_links_to_the_loda_pages(tmp_path: Path) -> None:
    piste = Piste().on("/search", search_reply(result(extract())))
    arguments = {"query": "bail", "fond": "LODA_DATE", "date": "2010-01-01"}
    content = call(piste, tmp_path, "legi_search", arguments).structured_content
    (item,) = content["items"]
    assert item["url"] == f"https://www.legifrance.gouv.fr/loda/article_lc/{ART}"
    assert item["in_force_on_date"] is False
    assert content["reference_date"] == "2010-01-01"


def test_an_unusable_search_reply_is_an_error_and_is_not_cached(tmp_path: Path) -> None:
    piste = Piste().on("/search", {"results": "x"})
    assert "résultats absents" in error_text(call(piste, tmp_path, "legi_search", {"query": "a"}))
    call(piste, tmp_path, "legi_search", {"query": "a"})
    assert piste.api_calls() == ["/search", "/search"]


def test_an_article_is_read_by_its_version_id(tmp_path: Path) -> None:
    piste = Piste()
    piste.routes["/consult/getArticle"] = by_id(article())
    found = call(piste, tmp_path, "legi_article", {"id": ART})
    content = found.structured_content
    assert (content["id"], content["num"], content["text_id"], content["text_title"]) == (
        ART,
        "1240",
        TEXT,
        "Code civil",
    )
    assert (content["start"], content["end"], content["legal_status"]) == (
        "2016-10-01",
        None,
        "VIGUEUR",
    )
    assert (content["covers_reference_date"], content["version_for_date"]) == (True, None)
    assert (content["warnings"], content["text_truncated"]) == ([], False)
    assert content["url"] == f"https://www.legifrance.gouv.fr/codes/article_lc/{ART}"
    assert content["retrieved_at"] == STAMP and content["text"].startswith("Tout fait")


def test_a_version_that_misses_the_date_is_flagged_with_the_one_that_applies(
    tmp_path: Path,
) -> None:
    piste = Piste()
    older = version(OLD, "2000-01-01", "2016-10-01", "MODIFIE")
    piste.routes["/consult/getArticle"] = by_id(article(versions=[older]))
    found = call(piste, tmp_path, "legi_article", {"id": ART, "date": "2010-06-01"})
    content = found.structured_content
    assert content["covers_reference_date"] is False
    assert content["version_for_date"] == OLD
    assert content["warnings"][0].startswith("version future")
    assert content["reference_date"] == "2010-06-01"


def test_a_reply_about_another_article_is_refused(tmp_path: Path) -> None:
    piste = Piste()
    piste.routes["/consult/getArticle"] = lambda _: respond(article(NEXT))
    message = error_text(call(piste, tmp_path, "legi_article", {"id": ART}))
    assert f"Légifrance a renvoyé l'article {NEXT} au lieu de {ART} : réponse refusée" in message


def test_the_article_in_force_is_read_by_text_and_number(tmp_path: Path) -> None:
    payloads: list[dict[str, Any]] = []

    def route(payload: dict[str, Any]) -> Any:
        payloads.append(payload)
        return respond(article(num="L. 121-1", nature="LOI"))

    piste = Piste()
    piste.routes["/consult/getArticleWithIdAndNum"] = route
    found = call(piste, tmp_path, "legi_article", {"text_id": TEXT, "num": " L121-1 "})
    assert payloads == [{"id": TEXT, "num": "L121-1"}]
    content = found.structured_content
    assert (content["id"], content["covers_reference_date"]) == (ART, True)
    assert content["url"] == f"https://www.legifrance.gouv.fr/loda/article_lc/{ART}"
    assert piste.api_calls() == ["/consult/getArticleWithIdAndNum"]


def test_for_a_past_date_the_version_that_applied_is_read(tmp_path: Path) -> None:
    piste = Piste()
    older = version(OLD, "2000-01-01", "2016-10-01", "MODIFIE")
    piste.on("/consult/getArticleWithIdAndNum", article(versions=[older]))
    old_reply = article(OLD, start="2000-01-01", end="2016-10-01", state="MODIFIE", text="Ancien.")
    piste.routes["/consult/getArticle"] = by_id(old_reply)
    arguments = {"text_id": TEXT, "num": "1240", "date": "2010-06-01"}
    content = call(piste, tmp_path, "legi_article", arguments).structured_content
    assert piste.api_calls() == ["/consult/getArticleWithIdAndNum", "/consult/getArticle"]
    assert (content["id"], content["text"], content["covers_reference_date"]) == (
        OLD,
        "Ancien.",
        True,
    )
    assert (content["end"], content["version_for_date"]) == ("2016-10-01", None)


def test_without_a_covering_version_the_article_in_force_is_flagged(tmp_path: Path) -> None:
    piste = Piste().on("/consult/getArticleWithIdAndNum", article())
    arguments = {"text_id": TEXT, "num": "1240", "date": "1990-01-01"}
    content = call(piste, tmp_path, "legi_article", arguments).structured_content
    assert (content["id"], content["covers_reference_date"]) == (ART, False)
    assert content["version_for_date"] is None
    assert content["warnings"][0].startswith("version future")
    assert piste.api_calls() == ["/consult/getArticleWithIdAndNum"]


@pytest.mark.parametrize(
    "reply",
    [
        article(num="1241"),
        article(parent="LEGITEXT000000000002"),
        article(num=None),  # type: ignore[arg-type]
    ],
)
def test_another_article_than_the_one_asked_is_refused(tmp_path: Path, reply: Any) -> None:
    piste = Piste().on("/consult/getArticleWithIdAndNum", reply)
    message = error_text(call(piste, tmp_path, "legi_article", {"text_id": TEXT, "num": "1240"}))
    assert f"un autre article que l'article 1240 de {TEXT} : réponse refusée" in message


def test_an_unavailable_source_is_said_as_such(tmp_path: Path) -> None:
    piste = Piste().on("/consult/getArticle", {}, status=429)
    message = error_text(call(piste, tmp_path, "legi_article", {"id": ART}))
    assert "source officielle indisponible : quota PISTE dépassé" in message

    def blocked() -> Environment:
        raise LegiError("source officielle indisponible : url = A_DEFINIR")

    server = build_server(sources(Piste(), tmp_path, blocked))
    for tool, arguments in (("legi_search", {"query": "a"}), ("legi_article", {"id": ART})):
        found = run(server, lambda c, t=tool, a=arguments: c.call_tool(t, a))
        assert error_text(found).endswith("url = A_DEFINIR")


def test_build_sources_wires_the_real_client(tmp_path: Path) -> None:
    built = build_sources(
        {"PISTE_CLIENT_ID": FAKE_ID, "PISTE_CLIENT_SECRET": FAKE_SECRET, "CERVEAU_HOME": "x"}
    )
    client = built.client
    assert client.configured and client.transport is None
    assert client.throttle.lock_path == THROTTLE_DIR / "legifrance.lock"
    assert client.throttle.interval_s == INTERVAL_S
    assert (client.lasting.directory, client.lasting.ttl) == (CACHE_DIR / "versions", ARTICLE_TTL)
    assert (client.daily.directory, client.daily.ttl) == (CACHE_DIR / "daily", DAILY_TTL)
    assert not build_sources({}).client.configured


def test_main_runs_the_server_with_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[Any] = []

    class Stub:
        def run(self) -> None:
            ran.append("run")

    monkeypatch.setattr(server_module, "build_server", lambda s: ran.append(s) or Stub())
    server_module.main()
    built, step = ran
    assert isinstance(built, Sources) and step == "run"


def test_python_dash_m_starts_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    monkeypatch.setattr(server_module, "main", lambda: ran.append("main"))
    runpy.run_module("plugins.legifrance", run_name="__main__")
    assert ran == ["main"]
