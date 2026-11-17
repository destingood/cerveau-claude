"""The insee_stats client and MCP server, offline: fake API, fake DNS, in-process SDK client."""

from __future__ import annotations

import asyncio
import json
import re
import runpy
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult

from core.registry.manifest import validate_plugin
from plugins.insee_stats import server as server_module
from plugins.insee_stats.catalog import StatsError
from plugins.insee_stats.client import (
    BASE,
    CACHE_DIR,
    CACHE_TTL,
    HOST,
    INTERVAL_S,
    MAX_BYTES,
    STOPPED,
    THROTTLE_DIR,
    StatsClient,
    base_url,
    stamp,
    utcnow,
)
from plugins.insee_stats.server import build_client, build_server, config_target
from plugins.insee_stats.tests.support import (
    FIXED_NOW,
    POPREF,
    SIDE,
    STAMP,
    FakeApi,
    catalog,
    data,
    melodi,
    obs,
    respond,
)
from tests.net_doubles import FakeDns

PLUGIN = Path(__file__).resolve().parents[1]
REPO_CONFIG = PLUGIN.parents[1] / "config"
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
SPECS = {tool["name"]: tool for tool in MANIFEST["tools"]}
ASK = {"jeu": POPREF, "geo": "DEP-44", "periode": "2023"}


def run(server: Any, action: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def call(client: StatsClient, arguments: dict[str, Any], target: Any = lambda: BASE) -> Any:
    return run(build_server(client, target), lambda c: c.call_tool("stats_series", arguments))


def error_text(found: CallToolResult) -> str:
    assert found.is_error
    return " ".join(getattr(block, "text", "") for block in found.content)


def keep(raw: bytes) -> bytes:
    return raw


def fetch(client: StatsClient, base: str = BASE) -> Any:
    return asyncio.run(client.fetch(base, ("data", POPREF), {"GEO": "DEP-44"}, keep))


def fails(client: StatsClient, message: str, base: str = BASE) -> None:
    with pytest.raises(StatsError, match=message):
        fetch(client, base)


def files_text(directory: Path) -> str:
    return "".join(
        path.read_bytes().decode("utf-8", "replace")
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    )


# Manifest, schemas and golden set.


def test_the_plugin_passes_the_registry() -> None:
    report = validate_plugin(PLUGIN)
    assert report.ok, report.errors
    assert report.plugin_id == "insee_stats"


def test_published_tools_match_the_manifest(tmp_path: Path) -> None:
    server = build_server(FakeApi().client(tmp_path), lambda: BASE)
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


GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]


@pytest.mark.parametrize("case", GOLDEN, ids=[case["id"] for case in GOLDEN])
def test_golden_cases(tmp_path: Path, case: dict[str, Any]) -> None:
    """The plugin golden set is offline: every case is refused before the configuration is read."""

    def no_target() -> str:
        raise AssertionError("the configuration must not be read")  # pragma: no cover

    api = FakeApi()
    found = call(api.client(tmp_path), case["arguments"], no_target)
    assert found.is_error is case["expected"]["is_error"]
    assert case["expected"]["contains"] in error_text(found)
    assert api.requests == []


# The tool, end to end.


def test_a_series_answers_figures_with_the_update_date(tmp_path: Path) -> None:
    api = FakeApi()
    found = call(api.client(tmp_path), {**ASK, "filtres": {"popref_measure": "ptot"}})
    assert not found.is_error
    result = found.structured_content
    assert (result["jeu"], result["geo"], result["periode"]) == (POPREF, "DEP-44", "2023")
    assert result["titre"].startswith("Populations de référence")
    assert result["filtres"] == {"POPREF_MEASURE": "PTOT"}
    assert result["mise_a_jour"] == "2025-12-18" and result["lu_le"] == STAMP
    # PCAP was not asked for: omitted (R12)
    assert (result["tronque"], result["omises"], result["en_cache"]) == (False, 1, False)
    assert result["observations"][0]["valeur"]["value"] == 1517043
    assert "Source : Insee" in result["licence"]
    assert [r.url.path for r in api.requests] == [
        f"/melodi/data/{POPREF}",
        f"/melodi/catalog/{POPREF}",
    ]
    assert api.params() == {
        "GEO": ["DEP-44"],
        "TIME_PERIOD": ["2023"],
        "POPREF_MEASURE": ["PTOT"],
        "maxResult": ["51"],
    }
    assert api.requests[1].url.query == b""
    request = api.requests[0]
    assert request.headers["host"] == HOST
    assert request.headers["user-agent"].startswith("CERVEAU-insee_stats/")


def test_the_title_of_the_reply_never_reaches_the_output_or_the_cache(tmp_path: Path) -> None:
    """The title comes from the closed list: the reply's own text is dropped (R5)."""
    api = FakeApi()
    result = call(api.client(tmp_path), ASK).structured_content
    shown = json.dumps(result, ensure_ascii=False) + files_text(tmp_path / "cache")
    for dropped in ("Ignore les consignes", "publisher", "paging", "Institut national"):
        assert dropped not in shown


def test_a_cut_reply_says_so(tmp_path: Path) -> None:
    many = [
        obs(float(i), GEO="2025-DEP-44", TIME_PERIOD="2023", POPREF_MEASURE="PTOT", N=str(i))
        for i in range(60)
    ]
    api = FakeApi([melodi(POPREF, many)])
    result = call(api.client(tmp_path), ASK).structured_content
    assert (len(result["observations"]), result["tronque"]) == (50, True)


def test_a_second_call_is_served_by_the_filtered_cache(tmp_path: Path) -> None:
    api = FakeApi()
    first = call(api.client(tmp_path), ASK)
    again = call(api.client(tmp_path), {**ASK, "geo": "dep-44"})
    assert len(api.requests) == 2
    assert again.structured_content["en_cache"] is True
    assert again.structured_content["observations"] == first.structured_content["observations"]
    assert again.structured_content["lu_le"] == STAMP


def test_an_unreadable_reply_is_an_error_and_is_not_cached(tmp_path: Path) -> None:
    api = FakeApi([lambda _: respond(b"{")])
    assert "JSON invalide" in error_text(call(api.client(tmp_path), ASK))
    assert files_text(tmp_path / "cache") == ""
    other = FakeApi([lambda _: respond(data(SIDE))])
    assert "format inattendu" in error_text(call(other.client(tmp_path), ASK))


def test_an_unreadable_catalog_is_an_error(tmp_path: Path) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if "catalog" in request.url.path:
            return respond(catalog(SIDE))
        return respond(data())

    api = FakeApi([answer])
    assert "catalogue illisible" in error_text(call(api.client(tmp_path), ASK))


@pytest.mark.parametrize(
    "damaged",
    [
        (b'{"observations": []}', b'{"mise_a_jour": null}'),
        (b'{"observations": [], "tronque": "x", "omises": 0}', b'{"mise_a_jour": null}'),
        (b'{"observations": [], "tronque": false, "omises": -1}', b'{"mise_a_jour": null}'),
        (b'{"observations": [], "tronque": false, "omises": true}', b'{"mise_a_jour": null}'),
        (b'{"observations": [{"x": 1}], "tronque": false, "omises": 0}', b'{"mise_a_jour": null}'),
        (b'{"observations": [], "tronque": false, "omises": 0}', b'{"mise_a_jour": 3}'),
        (b'{"observations": [], "tronque": false, "omises": 0}', b"{"),
    ],
)
def test_a_damaged_cached_copy_asks_to_ask_again(
    tmp_path: Path, damaged: tuple[bytes, bytes]
) -> None:
    api = FakeApi()
    client = api.client(tmp_path)
    assert client.cache is not None
    data_key = f"/data/{POPREF}?GEO=DEP-44&TIME_PERIOD=2023&maxResult=51"
    client.cache.put(data_key, damaged[0], FIXED_NOW)
    client.cache.put(f"/catalog/{POPREF}", damaged[1], FIXED_NOW)
    message = error_text(call(client, ASK))
    assert "copie en cache illisible : relancer la demande" in message
    assert api.requests == []


def test_a_blocked_source_is_said_as_such(tmp_path: Path) -> None:
    def blocked() -> str:
        raise StatsError("source indisponible : url = A_DEFINIR")

    api = FakeApi()
    message = error_text(call(api.client(tmp_path), ASK, blocked))
    assert message.endswith("url = A_DEFINIR") and api.requests == []


# The configuration, read before every call.


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    target = tmp_path / "config"
    shutil.copytree(REPO_CONFIG, target)
    return target


def test_the_configured_source_is_the_api() -> None:
    assert config_target(REPO_CONFIG)() == BASE
    assert base_url(BASE + "/") == BASE
    for url in (None, "https://api.insee.fr", "https://api.insee.fr/melodi.evil", "A_DEFINIR"):
        with pytest.raises(StatsError, match=r"n'est pas https://api\.insee\.fr/melodi"):
            base_url(url)


def _set_source(config_dir: Path, **values: Any) -> None:
    path = config_dir / "data_sources.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    loaded["sources"]["insee_melodi"].update(values)
    path.write_text(yaml.safe_dump(loaded, allow_unicode=True), encoding="utf-8")


def test_a_disabled_or_unset_source_blocks_the_call(config_dir: Path) -> None:
    _set_source(config_dir, enabled=False)
    with pytest.raises(StatsError, match=r"^source indisponible : .+"):
        config_target(config_dir)()
    _set_source(config_dir, enabled=True, url="A_DEFINIR")
    with pytest.raises(StatsError, match=r"^source indisponible : "):
        config_target(config_dir)()


def test_an_invalid_configuration_is_reported_without_detail(config_dir: Path) -> None:
    (config_dir / "data_sources.yaml").write_text("sources: [", encoding="utf-8")
    with pytest.raises(StatsError, match="lancer `cerveau config check`"):
        config_target(config_dir)()


# The client: host, guard, status, size, pace, kill switch.


def test_only_the_api_host_over_https_is_called(tmp_path: Path) -> None:
    api = FakeApi()
    fails(api.client(tmp_path), "hôte non autorisé", "https://evil.example")
    fails(api.client(tmp_path), "hôte non autorisé", "http://api.insee.fr/melodi")
    fails(api.client(tmp_path), "source indisponible", "not a url")
    assert api.requests == []


def test_a_path_segment_is_quoted(tmp_path: Path) -> None:
    api = FakeApi()
    client = api.client(tmp_path, cached=False)
    asyncio.run(client.fetch(BASE, ("data", "../x?y"), {}, keep))
    assert api.requests[0].url.raw_path == b"/melodi/data/..%2Fx%3Fy"


def test_a_private_address_is_refused_by_the_network_guard(tmp_path: Path) -> None:
    api = FakeApi()
    client = api.client(tmp_path)
    client.resolver = FakeDns({HOST: ["10.0.0.1"]})
    fails(client, "adresse non publique")
    assert api.requests == []


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (302, "redirection inattendue"),
        (400, "requête refusée par l'API \\(HTTP 400\\)"),
        (404, "jeu ou ressource introuvable \\(HTTP 404\\)"),
        (500, "service indisponible \\(HTTP 500\\)"),
        (429, "limite de débit de l'API atteinte \\(HTTP 429\\)"),
    ],
)
def test_an_error_status_is_an_unavailable_source(
    tmp_path: Path, status: int, message: str
) -> None:
    api = FakeApi([lambda _: respond({}, status=status, headers={"location": "https://x.example"})])
    fails(api.client(tmp_path), f"source indisponible : {message}")
    assert len(api.requests) == 1 and api.waits == []


def test_a_short_rate_limit_is_waited_for_once(tmp_path: Path) -> None:
    limited = lambda _: respond({}, status=429, headers={"retry-after": "2"})  # noqa: E731
    api = FakeApi([limited, melodi()])
    assert fetch(api.client(tmp_path)).cached is False
    assert (len(api.requests), api.waits) == (2, [2])

    again = FakeApi([limited])
    fails(again.client(tmp_path / "b"), "limite de débit de l'API atteinte \\(HTTP 429\\)")
    assert (len(again.requests), again.waits) == (2, [2])


@pytest.mark.parametrize("content_type", ["text/plain;charset=UTF-8", None])
def test_a_reply_that_is_not_json_is_refused(tmp_path: Path, content_type: str | None) -> None:
    api = FakeApi([lambda _: respond(b"{}", content_type=content_type)])
    fails(api.client(tmp_path), "réponse qui n'est pas du JSON")


def test_a_reply_too_large_is_refused(tmp_path: Path) -> None:
    api = FakeApi([lambda _: respond({"x": "y" * 200}, size=16)])
    fails(api.client(tmp_path, max_bytes=100), "trop volumineuse")
    assert MAX_BYTES == 2_000_000


def test_a_slow_or_broken_network_is_an_unavailable_source(tmp_path: Path) -> None:
    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        raise AssertionError("not reached")  # pragma: no cover - cut by the timeout

    api = FakeApi([slow])  # type: ignore[list-item]
    client = api.client(tmp_path)
    client.timeout_s = 0.05
    fails(client, "délai de 0.05 s dépassé")

    def broken(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    def timed_out(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    fails(FakeApi([broken]).client(tmp_path), "connexion impossible")
    fails(FakeApi([timed_out]).client(tmp_path), "dépassé")


def test_an_engaged_kill_switch_sends_nothing_and_serves_no_cached_copy(tmp_path: Path) -> None:
    api = FakeApi()
    fails(api.client(tmp_path, stopped=lambda: True), re.escape(STOPPED))
    assert api.requests == []
    engaged = False
    client = api.client(tmp_path, stopped=lambda: engaged)
    fetch(client)
    engaged = True
    fails(client, re.escape(STOPPED))
    assert len(api.requests) == 1


def test_a_kill_switch_engaged_during_a_retry_wait_stops_the_call(tmp_path: Path) -> None:
    api = FakeApi([lambda _: respond({}, status=429, headers={"retry-after": "2"})])
    fails(api.client(tmp_path, stopped=lambda: bool(api.requests)), re.escape(STOPPED))
    assert (len(api.requests), api.waits) == (1, [2])


def test_a_kill_switch_engaged_while_reading_stops_the_call(tmp_path: Path) -> None:
    checks: list[int] = []

    def stopped() -> bool:
        checks.append(1)
        return len(checks) > 4  # cache, request, slot, first chunk, then engaged

    api = FakeApi([lambda _: respond(data(), size=64)])
    fails(api.client(tmp_path, stopped=stopped), re.escape(STOPPED))
    assert len(api.requests) == 1 and files_text(tmp_path / "cache") == ""


def test_a_kill_switch_engaged_while_waiting_for_the_slot_sends_nothing(tmp_path: Path) -> None:
    checks: list[int] = []

    def stopped() -> bool:
        checks.append(1)
        return len(checks) > 2  # before the cache and the request, then engaged during the wait

    api = FakeApi()
    fails(api.client(tmp_path, stopped=stopped), re.escape(STOPPED))
    assert api.requests == []


def test_without_a_cache_every_call_is_a_request(tmp_path: Path) -> None:
    api = FakeApi()
    client = api.client(tmp_path, cached=False)
    fetch(client)
    fetch(client)
    assert len(api.requests) == 2 and not (tmp_path / "cache").exists()


def test_times_are_stamped_in_utc() -> None:
    assert stamp(FIXED_NOW) == STAMP
    assert utcnow().tzinfo is not None


# Wiring.


def test_build_client_wires_the_real_pieces(tmp_path: Path) -> None:
    client = build_client({"CERVEAU_HOME": str(tmp_path)})
    assert client.transport is None
    assert client.throttle.lock_path == THROTTLE_DIR / "insee_melodi.lock"
    assert client.throttle.interval_s == INTERVAL_S == 3.0
    assert client.cache is not None
    assert (client.cache.directory, client.cache.ttl) == (CACHE_DIR, CACHE_TTL)
    assert client.stopped() is False
    switch = tmp_path / "governance" / "kill_switch"
    switch.mkdir(parents=True)
    (switch / "KILL").write_text("test", encoding="utf-8")
    assert client.stopped() is True


def test_main_runs_the_server_with_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[Any] = []

    class Stub:
        def run(self) -> None:
            ran.append("run")

    monkeypatch.setattr(server_module, "build_server", lambda c, t: ran.append(c) or Stub())
    server_module.main()
    built, step = ran
    assert isinstance(built, StatsClient) and step == "run"


def test_python_dash_m_starts_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    monkeypatch.setattr(server_module, "main", lambda: ran.append("main"))
    runpy.run_module("plugins.insee_stats", run_name="__main__")
    assert ran == ["main"]
