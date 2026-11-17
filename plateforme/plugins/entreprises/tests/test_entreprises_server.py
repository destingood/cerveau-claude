"""The entreprises client and MCP server, offline: fake API, fake DNS, in-process SDK client."""

from __future__ import annotations

import asyncio
import json
import re
import runpy
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult

from core.registry.manifest import validate_plugin
from plugins.entreprises import server as server_module
from plugins.entreprises.client import (
    BASE,
    CACHE_DIR,
    CACHE_TTL,
    HOST,
    INTERVAL_S,
    MAX_BYTES,
    STOPPED,
    THROTTLE_DIR,
    RegistryClient,
    base_url,
    retry_after,
    stamp,
    status_error,
    utcnow,
)
from plugins.entreprises.registry import Filters, RegistryError, search_params
from plugins.entreprises.server import (
    build_client,
    build_server,
    config_target,
    search,
)
from plugins.entreprises.tests.support import (
    FIXED_NOW,
    PERSON_NAMES,
    SECRET_FIELDS,
    SIREN,
    STAMP,
    FakeApi,
    company,
    files_text,
    reply,
    respond,
)
from tests.net_doubles import FakeDns

PLUGIN = Path(__file__).resolve().parents[1]
REPO_CONFIG = PLUGIN.parents[1] / "config"
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
SPECS = {tool["name"]: tool for tool in MANIFEST["tools"]}


def run(server: Any, action: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def call(client: RegistryClient, arguments: dict[str, Any], target: Any = lambda: BASE) -> Any:
    return run(build_server(client, target), lambda c: c.call_tool("company_search", arguments))


def error_text(found: CallToolResult) -> str:
    assert found.is_error
    return " ".join(getattr(block, "text", "") for block in found.content)


def keep(raw: bytes) -> bytes:
    return raw


def fetch(client: RegistryClient, base: str = BASE) -> Any:
    return asyncio.run(client.search(base, {"q": "boulangerie"}, keep))


def fails(client: RegistryClient, message: str, base: str = BASE) -> None:
    with pytest.raises(RegistryError, match=message):
        fetch(client, base)


# Manifest, schemas and golden set.


def test_the_plugin_passes_the_registry() -> None:
    report = validate_plugin(PLUGIN)
    assert report.ok, report.errors
    assert report.plugin_id == "entreprises"


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


def test_a_search_answers_the_closed_list_and_no_person(tmp_path: Path) -> None:
    api = FakeApi()
    arguments = {
        "recherche": "Boulangerie atelier",
        "code_postal": "69003",
        "etat_administratif": "A",
    }
    found = call(api.client(tmp_path), arguments)
    assert not found.is_error
    data = found.structured_content
    assert data["recherche"] == "Boulangerie atelier" and data["siren"] is None
    assert data["filtres"]["code_postal"] == "69003"
    assert data["total"]["value"] == 1 and data["lu_le"] == STAMP and data["en_cache"] is False
    assert data["resultats"][0]["siren"] == SIREN
    assert api.params() == {
        "q": ["Boulangerie atelier"],
        "page": ["1"],
        "per_page": ["10"],
        "minimal": ["true"],
        "include": ["siege,finances"],
        "code_postal": ["69003"],
        "etat_administratif": ["A"],
    }
    request = api.requests[0]
    assert request.headers["host"] == HOST and request.url.path == "/search"
    assert request.headers["user-agent"].startswith("CERVEAU-entreprises/")
    assert "dirigeants filtrés" in data.pop("note")
    shown = json.dumps(data, ensure_ascii=False) + files_text(tmp_path)
    for secret in (*PERSON_NAMES, *SECRET_FIELDS):
        assert secret not in shown


@pytest.mark.parametrize(
    "recherche",
    ["Josiane Dupontel", "Dupontel", "12 rue des Lilas", "Boulangerie Martinot"],
    ids=["manager", "surname", "street", "half-match"],
)
def test_a_person_or_an_address_finds_no_company(tmp_path: Path, recherche: str) -> None:
    """The API matches its text on the managers and the address too (I4): such a result is
    dropped, and the total counts only the companies named after the text."""
    api = FakeApi([lambda _: respond(reply(total=7))])
    data = call(api.client(tmp_path), {"recherche": recherche}).structured_content
    assert (data["total"]["value"], data["resultats"]) == (0, [])


def test_a_text_search_counts_only_the_named_companies(tmp_path: Path) -> None:
    other = company(siren="552100554", nom_complet="Thé Vert", nom_raison_sociale="THE VERT")
    api = FakeApi([lambda _: respond(reply([company(), other], total=40))])
    data = call(api.client(tmp_path), {"recherche": "BOULANGERIE ateliér"}).structured_content
    assert data["total"]["value"] == 1
    assert [r["siren"] for r in data["resultats"]] == [SIREN]
    by_number = call(FakeApi().client(tmp_path / "b"), {"siren": SIREN}).structured_content
    assert by_number["total"]["value"] == 1


def test_an_unknown_argument_is_never_sent(tmp_path: Path) -> None:
    api = FakeApi()
    call(
        api.client(tmp_path),
        {"recherche": "boulangerie", "dirigeant": "Dupontel", "nom": "Josiane"},
    )
    assert sorted(api.params()) == ["include", "minimal", "page", "per_page", "q"]
    assert "Dupontel" not in str(api.requests[0].url)


def test_a_second_search_is_served_by_the_filtered_cache(tmp_path: Path) -> None:
    api = FakeApi()
    first = call(api.client(tmp_path), {"siren": "356 000 000"})
    again = call(api.client(tmp_path), {"siren": SIREN})
    assert len(api.requests) == 1 and api.params()["q"] == [SIREN]
    assert again.structured_content["en_cache"] is True
    assert again.structured_content["resultats"] == first.structured_content["resultats"]
    assert again.structured_content["lu_le"] == STAMP
    text = files_text(tmp_path / "cache")
    assert SIREN in text
    for secret in (*PERSON_NAMES, *SECRET_FIELDS):
        assert secret not in text


def test_an_unreadable_reply_is_an_error_and_is_not_cached(tmp_path: Path) -> None:
    api = FakeApi([lambda _: respond(b"{")])
    message = error_text(call(api.client(tmp_path), {"recherche": "boulangerie"}))
    assert "JSON invalide" in message
    assert files_text(tmp_path / "cache") == ""


def test_a_damaged_cached_copy_asks_to_search_again(tmp_path: Path) -> None:
    api = FakeApi()
    client = api.client(tmp_path)
    query = urlencode(sorted(search_params("boulangerie", None, Filters()).items()))
    assert client.cache is not None
    for damaged in (b'{"total": 1}', b'{"total": "x", "resultats": []}', b'{"total": -1}'):
        client.cache.put(query, damaged, FIXED_NOW)
        message = error_text(call(client, {"recherche": "boulangerie"}))
        assert "copie en cache illisible : relancer la recherche" in message
    assert api.requests == []


@pytest.mark.parametrize("arguments", [{}, {"recherche": "boulangerie", "siren": SIREN}])
def test_exactly_one_form_of_input_is_taken(tmp_path: Path, arguments: dict[str, Any]) -> None:
    api = FakeApi()
    assert "une seule forme" in error_text(call(api.client(tmp_path), arguments))
    assert api.requests == []


def test_a_blocked_source_is_said_as_such(tmp_path: Path) -> None:
    def blocked() -> str:
        raise RegistryError("source indisponible : url = A_DEFINIR")

    api = FakeApi()
    message = error_text(call(api.client(tmp_path), {"recherche": "boulangerie"}, blocked))
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
    for url in (None, "https://recherche-entreprises.api.gouv.fr.evil.example", "A_DEFINIR"):
        with pytest.raises(RegistryError, match="n'est pas https://recherche"):
            base_url(url)


def _set_source(config_dir: Path, **values: Any) -> None:
    path = config_dir / "data_sources.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["sources"]["entreprises"].update(values)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_a_disabled_or_unset_source_blocks_the_call(config_dir: Path) -> None:
    _set_source(config_dir, enabled=False)
    with pytest.raises(RegistryError, match=r"^source indisponible : .+"):
        config_target(config_dir)()
    _set_source(config_dir, enabled=True, url="A_DEFINIR")
    with pytest.raises(RegistryError, match=r"^source indisponible : "):
        config_target(config_dir)()


def test_an_invalid_configuration_is_reported_without_detail(config_dir: Path) -> None:
    (config_dir / "data_sources.yaml").write_text("sources: [", encoding="utf-8")
    with pytest.raises(RegistryError, match="lancer `cerveau config check`"):
        config_target(config_dir)()


# The client: host, guard, status, size, pace, kill switch.


def test_only_the_api_host_over_https_is_called(tmp_path: Path) -> None:
    api = FakeApi()
    fails(api.client(tmp_path), "hôte non autorisé", "https://evil.example")
    fails(api.client(tmp_path), "hôte non autorisé", "http://recherche-entreprises.api.gouv.fr")
    fails(api.client(tmp_path), "source indisponible", "not a url")
    assert api.requests == []


def test_a_private_address_is_refused_by_the_network_guard(tmp_path: Path) -> None:
    api = FakeApi()
    client = api.client(tmp_path)
    client.resolver = FakeDns({HOST: ["10.0.0.1"]})
    fails(client, "adresse non publique")
    client.resolver = FakeDns()
    fails(client, "source indisponible")
    assert api.requests == []


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (302, "redirection inattendue"),
        (400, "requête refusée par l'API \\(HTTP 400\\)"),
        (404, "réponse HTTP 404 inattendue"),
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


def test_every_status_has_a_message() -> None:
    assert status_error(301) == "redirection inattendue"
    assert status_error(429).endswith("(HTTP 429)")
    assert status_error(503) == "service indisponible (HTTP 503)"
    assert status_error(418) == "réponse HTTP 418 inattendue"


def test_a_short_rate_limit_is_waited_for_once(tmp_path: Path) -> None:
    limited = lambda _: respond({}, status=429, headers={"retry-after": "2"})  # noqa: E731
    api = FakeApi([limited, lambda _: respond(reply())])
    assert fetch(api.client(tmp_path)).cached is False
    assert (len(api.requests), api.waits) == (2, [2])

    again = FakeApi([limited])
    fails(again.client(tmp_path / "b"), "limite de débit de l'API atteinte \\(HTTP 429\\)")
    assert (len(again.requests), again.waits) == (2, [2])


@pytest.mark.parametrize(
    ("value", "seconds"),
    [
        (None, None),
        ("", None),
        ("abc", None),
        ("1000", None),
        ("6", None),
        ("²", None),  # isdigit() is true, int() refuses it
        ("5", 5),
        (" 0 ", 0),
    ],
)
def test_only_a_short_retry_after_is_kept(value: str | None, seconds: int | None) -> None:
    assert retry_after(value) == seconds


def test_a_reply_that_is_not_json_is_refused(tmp_path: Path) -> None:
    api = FakeApi([lambda _: respond(b"<html>", content_type="text/html; charset=utf-8")])
    fails(api.client(tmp_path), "réponse qui n'est pas du JSON")
    bare = FakeApi([lambda _: respond(b"{}", content_type=None)])
    assert fetch(bare.client(tmp_path / "b")).body == b"{}"


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


def test_an_engaged_kill_switch_sends_nothing(tmp_path: Path) -> None:
    api = FakeApi()
    fails(api.client(tmp_path, stopped=lambda: True), re.escape(STOPPED))
    assert api.requests == []


def test_a_kill_switch_engaged_during_a_retry_wait_stops_the_call(tmp_path: Path) -> None:
    api = FakeApi([lambda _: respond({}, status=429, headers={"retry-after": "2"})])
    fails(api.client(tmp_path, stopped=lambda: bool(api.requests)), re.escape(STOPPED))
    assert (len(api.requests), api.waits) == (1, [2])


def test_an_engaged_kill_switch_serves_no_cached_copy(tmp_path: Path) -> None:
    api = FakeApi()
    engaged = False
    client = api.client(tmp_path, stopped=lambda: engaged)
    fetch(client)
    engaged = True
    fails(client, re.escape(STOPPED))
    assert len(api.requests) == 1


def test_a_kill_switch_engaged_while_reading_stops_the_call(tmp_path: Path) -> None:
    checks: list[int] = []

    def stopped() -> bool:
        checks.append(1)
        return len(checks) > 3  # before the request, after the slot, the first chunk, engaged

    api = FakeApi([lambda _: respond(reply([company()] * 10), size=64)])
    fails(api.client(tmp_path, stopped=stopped), re.escape(STOPPED))
    assert len(api.requests) == 1 and files_text(tmp_path / "cache") == ""


def test_a_kill_switch_engaged_while_waiting_for_the_slot_sends_nothing(tmp_path: Path) -> None:
    checks: list[int] = []

    def stopped() -> bool:
        checks.append(1)
        return len(checks) > 1  # before the request, then engaged during the wait

    api = FakeApi()
    fails(api.client(tmp_path, stopped=stopped), re.escape(STOPPED))
    assert api.requests == []


def test_without_a_cache_every_search_is_a_request(tmp_path: Path) -> None:
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
    assert client.throttle.lock_path == THROTTLE_DIR / "entreprises.lock"
    assert client.throttle.interval_s == INTERVAL_S
    assert client.cache is not None
    assert (client.cache.directory, client.cache.ttl) == (CACHE_DIR, CACHE_TTL)
    assert client.stopped() is False
    switch = tmp_path / "governance" / "kill_switch"
    switch.mkdir(parents=True)
    (switch / "KILL").write_text("test", encoding="utf-8")
    assert client.stopped() is True


async def _direct(tmp_path: Path) -> Any:
    return await search(
        FakeApi().client(tmp_path), lambda: BASE, None, SIREN, "69003", None, None, None
    )


def test_a_siren_search_ignores_the_filters(tmp_path: Path) -> None:
    found = asyncio.run(_direct(tmp_path))
    assert (found.siren, found.recherche, found.filtres.code_postal) == (SIREN, None, "69003")


def test_main_runs_the_server_with_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[Any] = []

    class Stub:
        def run(self) -> None:
            ran.append("run")

    monkeypatch.setattr(server_module, "build_server", lambda c, t: ran.append(c) or Stub())
    server_module.main()
    built, step = ran
    assert isinstance(built, RegistryClient) and step == "run"


def test_python_dash_m_starts_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    monkeypatch.setattr(server_module, "main", lambda: ran.append("main"))
    runpy.run_module("plugins.entreprises", run_name="__main__")
    assert ran == ["main"]
