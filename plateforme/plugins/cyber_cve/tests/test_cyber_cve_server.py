"""The MCP server, called in process through the SDK client, against its manifest."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult

from core.registry.manifest import validate_plugin
from plugins.cyber_cve import kev
from plugins.cyber_cve import server as server_module
from plugins.cyber_cve.common import CACHE_DIR, CyberError
from plugins.cyber_cve.epss import EpssSource
from plugins.cyber_cve.kev import KevSource
from plugins.cyber_cve.models import RANKING_RULE
from plugins.cyber_cve.nvd import NvdSource
from plugins.cyber_cve.server import (
    DESCRIPTIONS,
    EPSS_INTERVAL_S,
    KEV_INTERVAL_S,
    NVD_INTERVAL_S,
    NVD_KEYED_INTERVAL_S,
    WATCH_ORDER,
    Sources,
    build_server,
    build_sources,
)
from plugins.cyber_cve.settings import SOURCES_FILE
from plugins.cyber_cve.tests.support import (
    FIXED_NOW,
    STAMP,
    FakeApi,
    cve,
    cvss_item,
    epss_body,
    epss_item,
    kev_feed,
    kev_item,
    page,
    respond,
)

PLUGIN = Path(__file__).resolve().parents[1]
ROOT = PLUGIN.parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
SPECS = {tool["name"]: tool for tool in MANIFEST["tools"]}
NVD_HOST, KEV_HOST, EPSS_HOST = "services.nvd.nist.gov", "www.cisa.gov", "api.first.org"


@dataclass
class Gate:
    """The configuration gate: records each feature asked for and refuses the blocked ones."""

    blocked: frozenset[str] = frozenset()
    seen: list[str] = field(default_factory=list)

    def __call__(self, feature: str) -> None:
        self.seen.append(feature)
        if feature in self.blocked:
            raise CyberError(f"fonction bloquée « {feature} » : désactivée pour le test")


@dataclass
class World:
    """The three APIs behind one fake network; each answer is built anew for each request.

    ``searches`` maps a keyword to its CVEs, oldest published first, as the NVD sorts them.
    """

    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    searches: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    kev: list[dict[str, Any]] = field(default_factory=list)
    epss: list[dict[str, Any]] = field(default_factory=list)
    status: dict[str, int] = field(default_factory=dict)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        if host in self.status:
            return respond(b"", self.status[host])
        if host == KEV_HOST:
            return respond(kev_feed(*self.kev))
        if host == EPSS_HOST:
            return respond(epss_body(*self.epss))
        params = dict(request.url.params)
        if "cveId" in params:
            found = self.records.get(params["cveId"])
            return respond(page(found) if found else page())
        matches = self.searches.get(params["keywordSearch"], [])
        start, size = int(params["startIndex"]), int(params["resultsPerPage"])
        return respond(page(*matches[start : start + size], total=len(matches), start=start))


@dataclass
class Setup:
    server: Any
    api: FakeApi
    gate: Gate

    def hosts(self) -> list[str]:
        return [request.headers["host"] for request in self.api.requests]


def _setup(
    tmp_path: Path,
    world: World | None = None,
    *,
    blocked: frozenset[str] = frozenset(),
    products: str | None = None,
) -> Setup:
    api = FakeApi(world or World())
    gate = Gate(blocked)
    products_file = tmp_path / "sources.yaml"
    if products is not None:
        products_file.write_text(products, encoding="utf-8")
    sources = Sources(
        NvdSource(api.fetcher(tmp_path, "NVD")),
        KevSource(api.fetcher(tmp_path, "KEV")),
        EpssSource(api.fetcher(tmp_path, "EPSS")),
        gate=gate,
        products_file=products_file,
        now=lambda: FIXED_NOW,
    )
    return Setup(build_server(sources), api, gate)


def run(server: Any, action: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def call(server: Any, tool: str, arguments: dict[str, Any]) -> CallToolResult:
    return run(server, lambda c: c.call_tool(tool, arguments))


def data_of(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error, error_text(result)
    assert result.structured_content is not None
    return result.structured_content


def error_text(result: CallToolResult) -> str:
    assert result.is_error
    return " ".join(getattr(block, "text", "") for block in result.content)


def _scored(identifier: str, score: float) -> dict[str, Any]:
    return cve(identifier, metrics={"cvssMetricV31": [cvss_item(score=score)]})


def test_the_plugin_passes_the_registry() -> None:
    report = validate_plugin(PLUGIN)
    assert report.ok, report.errors
    assert report.plugin_id == "cyber_cve"


def test_published_tools_match_the_manifest(tmp_path: Path) -> None:
    tools = run(_setup(tmp_path).server, lambda c: c.list_tools()).tools
    assert [t.name for t in tools] == list(SPECS)
    for tool in tools:
        spec = SPECS[tool.name]
        assert tool.description == spec["description"] == DESCRIPTIONS[tool.name]
        published = tool.annotations.model_dump(by_alias=True, exclude_none=True)
        assert published == spec["annotations"]
        for kind, schema in (
            ("input_schema", tool.input_schema),
            ("output_schema", tool.output_schema),
        ):
            on_disk = json.loads((PLUGIN / spec[kind]).read_text(encoding="utf-8"))
            on_disk.pop("$schema")
            assert schema == on_disk, f"{spec[kind]} is stale: regenerate it from the server"


def test_a_lookup_ranks_the_records_and_dates_every_source(tmp_path: Path) -> None:
    world = World(
        records={
            "CVE-2021-44228": _scored("CVE-2021-44228", 10.0),
            "CVE-2024-0001": _scored("CVE-2024-0001", 9.8),
            "CVE-2023-0002": _scored("CVE-2023-0002", 5.0),
        },
        kev=[kev_item("CVE-2023-0002"), kev_item("CVE-2020-0001")],
        epss=[epss_item("CVE-2021-44228", "0.9"), epss_item("CVE-2024-0001", "0.95")],
    )
    setup = _setup(tmp_path, world)
    ids = [" cve-2021-44228 ", "CVE-2024-0001", "CVE-2023-0002", "CVE-2021-44228", "CVE-2025-9999"]
    data = data_of(call(setup.server, "cve_lookup", {"ids": ids}))
    records = data["records"]
    assert [r["id"] for r in records] == ["CVE-2023-0002", "CVE-2024-0001", "CVE-2021-44228"]
    assert [r["rank"] for r in records] == [1, 2, 3]
    assert data["not_found"] == ["CVE-2025-9999"]
    assert data["ranking_rule"] == RANKING_RULE
    assert data["ranking_complete"] is True
    assert data["sources"] == [
        {"source": "cisa_kev", "retrieved_at": STAMP, "version": "2026.10.26", "error": None},
        {"source": "epss", "retrieved_at": STAMP, "version": None, "error": None},
    ]
    first, _, last = records
    assert first["kev"]["date_added"] == "2021-12-10"
    assert first["epss"] is None
    assert last["kev"] is None
    assert last["epss"]["epss"] == 0.9
    assert last["ranking_cvss"]["base_score"] == 10.0
    assert last["nvd_retrieved_at"] == STAMP
    assert last["nvd_url"] == "https://nvd.nist.gov/vuln/detail/CVE-2021-44228"
    assert setup.hosts() == [NVD_HOST] * 4 + [KEV_HOST, EPSS_HOST]
    assert setup.api.params() == {"cve": "CVE-2021-44228,CVE-2024-0001,CVE-2023-0002"}
    assert setup.gate.seen == ["data.nvd", "data.cisa_kev", "data.epss"]


def test_without_any_record_the_other_sources_are_not_read(tmp_path: Path) -> None:
    setup = _setup(tmp_path)
    data = data_of(call(setup.server, "cve_lookup", {"ids": ["CVE-2025-9999"]}))
    assert data["records"] == []
    assert data["not_found"] == ["CVE-2025-9999"]
    assert (data["ranking_complete"], data["sources"]) == (True, [])
    assert setup.hosts() == [NVD_HOST]
    assert setup.gate.seen == ["data.nvd"]


@pytest.mark.parametrize(
    ("status", "blocked", "index", "message"),
    [
        ({KEV_HOST: 503}, frozenset(), 0, "KEV : service indisponible (HTTP 503)"),
        ({EPSS_HOST: 429}, frozenset(), 1, "EPSS : débit dépassé (HTTP 429), réessayer plus tard"),
        ({}, frozenset({"data.cisa_kev"}), 0, "fonction bloquée « data.cisa_kev »"),
        ({}, frozenset({"data.epss"}), 1, "fonction bloquée « data.epss »"),
    ],
    ids=["kev-down", "epss-down", "kev-off", "epss-off"],
)
def test_a_missing_kev_or_epss_only_degrades_the_answer(
    tmp_path: Path, status: dict[str, int], blocked: frozenset[str], index: int, message: str
) -> None:
    world = World(
        records={"CVE-2021-44228": cve()},
        kev=[kev_item()],
        epss=[epss_item()],
        status=status,
    )
    setup = _setup(tmp_path, world, blocked=blocked)
    data = data_of(call(setup.server, "cve_lookup", {"ids": ["CVE-2021-44228"]}))
    assert data["ranking_complete"] is False
    failed, read = data["sources"][index], data["sources"][1 - index]
    assert message in failed["error"]
    assert (failed["retrieved_at"], failed["version"]) == (None, None)
    assert (read["error"], read["retrieved_at"]) == (None, STAMP)
    (record,) = data["records"]
    assert (record["kev"] is None, record["epss"] is None) == (index == 0, index == 1)
    skipped = set() if status else {EPSS_HOST if index else KEV_HOST}
    assert set(setup.hosts()) == {NVD_HOST, KEV_HOST, EPSS_HOST} - skipped


def test_the_nvd_record_is_required(tmp_path: Path) -> None:
    down = _setup(tmp_path, World(status={NVD_HOST: 503}))
    result = call(down.server, "cve_lookup", {"ids": ["CVE-2021-44228"]})
    assert "NVD : service indisponible (HTTP 503)" in error_text(result)
    assert down.hosts() == [NVD_HOST]
    off = _setup(tmp_path, World(records={"CVE-2021-44228": cve()}), blocked={"data.nvd"})
    result = call(off.server, "cve_lookup", {"ids": ["CVE-2021-44228"]})
    assert "fonction bloquée « data.nvd »" in error_text(result)
    assert off.api.requests == []


def test_identifiers_are_checked_before_any_request(tmp_path: Path) -> None:
    setup = _setup(tmp_path, World(records={"CVE-2021-44228": cve()}))
    result = call(setup.server, "cve_lookup", {"ids": ["CVE-2021-44228", "CVE-21-1"]})
    assert "identifiant n° 2 non reconnu (forme CVE-AAAA-NNNN)" in error_text(result)
    assert (setup.api.requests, setup.gate.seen) == ([], [])


def _kev_world() -> World:
    return World(
        kev=[
            kev_item("CVE-2024-0001", dateAdded="2026-10-20", vendorProject="OpenSSL"),
            kev_item("CVE-2024-0002", dateAdded="2026-10-25", vendorProject="Microsoft"),
            kev_item("CVE-2024-10000", dateAdded="2026-10-25", product="Tomcat"),
            kev_item("CVE-2024-9999", dateAdded="2026-10-25", product="HTTP Server"),
            kev_item("CVE-2024-0003", dateAdded="2026-09-30", product="Windows"),
        ]
    )


def test_the_kev_watch_keeps_the_range_newest_first(tmp_path: Path) -> None:
    setup = _setup(tmp_path, _kev_world())
    data = data_of(call(setup.server, "cve_watch", {"source": "kev", "since": "2026-10-01"}))
    ids = [item["id"] for item in data["items"]]
    assert ids == ["CVE-2024-10000", "CVE-2024-9999", "CVE-2024-0002", "CVE-2024-0001"]
    assert (data["source"], data["since"], data["until"]) == ("kev", "2026-10-01", "2026-10-27")
    assert (data["total"], data["more_available"], data["keywords"]) == (4, False, [])
    assert (data["order"], data["retrieved_at"]) == (WATCH_ORDER, STAMP)
    assert data["version"] == "2026.10.26"
    assert data["items"][2] == {
        "id": "CVE-2024-0002",
        "date": "2026-10-25",
        "title": "Apache Log4j2 Remote Code Execution Vulnerability",
        "vendor": "Microsoft",
        "product": "Log4j2",
        "cvss": None,
        "status": None,
        "ransomware": "Known",
        "due_date": "2021-12-24",
    }
    assert setup.hosts() == [KEV_HOST]
    assert setup.gate.seen == ["data.cisa_kev"]


@pytest.mark.parametrize(
    ("arguments", "ids", "total"),
    [
        ({"keyword": "apache", "max_results": 1}, ["CVE-2024-10000"], 2),
        ({"keyword": "OPENSSL"}, ["CVE-2024-0001"], 1),
        ({"keyword": "windows", "since": "2020-01-01"}, ["CVE-2024-0003"], 1),
        ({"until": "2026-10-24"}, ["CVE-2024-0001"], 1),
        ({"since": "2026-10-26"}, [], 0),
    ],
    ids=["vendor", "case", "product", "until", "none"],
)
def test_the_kev_watch_filters(
    tmp_path: Path, arguments: dict[str, Any], ids: list[str], total: int
) -> None:
    setup = _setup(tmp_path, _kev_world())
    data = data_of(
        call(setup.server, "cve_watch", {"source": "kev", "since": "2026-10-01", **arguments})
    )
    assert [item["id"] for item in data["items"]] == ids
    assert data["total"] == total


def _published(identifier: str, when: str | None, **overrides: Any) -> dict[str, Any]:
    return cve(identifier, published=when, **overrides)


def test_the_nvd_watch_sends_the_range_and_checks_it(tmp_path: Path) -> None:
    long_text = [{"lang": "en", "value": "x" * 300}]
    world = World(
        searches={
            "openssl": [
                _published("CVE-2026-0004", "2026-09-30T23:59:59.000"),
                _published("CVE-2026-0001", "2026-10-01T08:00:00.000"),
                _published("CVE-2026-0002", "2026-10-20T08:00:00.000", descriptions=long_text),
                _published("CVE-2026-0003", None),
            ]
        }
    )
    setup = _setup(tmp_path, world)
    arguments = {"source": "nvd", "since": "2026-10-01", "keyword": " openssl "}
    data = data_of(call(setup.server, "cve_watch", arguments))
    assert setup.api.params() == {
        "keywordSearch": "openssl",
        "pubStartDate": "2026-10-01T00:00:00.000Z",
        "pubEndDate": "2026-10-27T23:59:59.999Z",
        "resultsPerPage": "20",
        "startIndex": "0",
    }
    assert [item["id"] for item in data["items"]] == ["CVE-2026-0002", "CVE-2026-0001"]
    assert (data["total"], data["more_available"], data["version"]) == (2, False, None)
    assert (data["keywords"], data["retrieved_at"]) == (["openssl"], STAMP)
    newest = data["items"][0]
    assert (newest["date"], newest["title"]) == ("2026-10-20", "x" * 200)
    assert (newest["status"], newest["cvss"]["base_score"]) == ("Analyzed", 9.8)
    assert (newest["vendor"], newest["product"], newest["due_date"]) == (None, None, None)
    assert setup.gate.seen == ["data.nvd"]


def test_the_nvd_watch_reads_the_last_page_when_more_match(tmp_path: Path) -> None:
    matches = [
        _published(f"CVE-2026-{1000 + n}", f"2026-10-{1 + n:02d}T08:00:00.000") for n in range(25)
    ]
    setup = _setup(tmp_path, World(searches={"log4j": matches}))
    arguments = {"source": "nvd", "since": "2026-10-01", "keyword": "log4j", "max_results": 3}
    data = data_of(call(setup.server, "cve_watch", arguments))
    assert [setup.api.params(i)["startIndex"] for i in (0, 1)] == ["0", "5"]
    assert [item["id"] for item in data["items"]] == [
        "CVE-2026-1024",
        "CVE-2026-1023",
        "CVE-2026-1022",
    ]
    assert (data["total"], data["more_available"]) == (20, True)


def test_the_nvd_watch_falls_back_on_the_watched_products(tmp_path: Path) -> None:
    shared = _published("CVE-2026-0002", "2026-10-10T08:00:00.000")
    world = World(
        searches={
            "OpenSSL": [_published("CVE-2026-0001", "2026-10-05T08:00:00.000"), shared],
            "Tomcat": [shared, _published("CVE-2026-0003", "2026-10-15T08:00:00.000")],
        }
    )
    setup = _setup(tmp_path, world, products="produits_suivis: [OpenSSL, Tomcat]\n")
    data = data_of(call(setup.server, "cve_watch", {"source": "nvd", "since": "2026-10-01"}))
    assert data["keywords"] == ["OpenSSL", "Tomcat"]
    assert [item["id"] for item in data["items"]] == [
        "CVE-2026-0003",
        "CVE-2026-0002",
        "CVE-2026-0001",
    ]
    assert data["total"] == 3
    assert [p["keywordSearch"] for p in map(setup.api.params, (0, 1))] == ["OpenSSL", "Tomcat"]


@pytest.mark.parametrize(
    ("products", "message"),
    [
        (None, "aucun mot-clé : donner keyword, ou remplir produits_suivis"),
        ("produits_suivis: []\n", "domain_packs/cyber/knowledge/sources.yaml (G10)"),
        ("produits_suivis: [a\n", "sources.yaml illisible"),
    ],
    ids=["absent", "empty", "unreadable"],
)
def test_the_nvd_watch_needs_a_keyword(tmp_path: Path, products: str | None, message: str) -> None:
    setup = _setup(tmp_path, products=products)
    result = call(setup.server, "cve_watch", {"source": "nvd", "since": "2026-10-01"})
    assert message in error_text(result)
    assert (setup.api.requests, setup.gate.seen) == ([], [])


def test_the_nvd_range_limit_is_inclusive(tmp_path: Path) -> None:
    setup = _setup(tmp_path)
    arguments = {"source": "nvd", "keyword": "x", "since": "2026-06-30"}
    assert data_of(call(setup.server, "cve_watch", arguments))["total"] == 0
    result = call(setup.server, "cve_watch", {**arguments, "since": "2026-06-29"})
    assert "plage de plus de 120 jours : le NVD la refuse" in error_text(result)
    assert len(setup.api.requests) == 1


def test_a_blocked_or_failing_watch_source_is_an_error(tmp_path: Path) -> None:
    off = _setup(tmp_path, _kev_world(), blocked={"data.cisa_kev"})
    result = call(off.server, "cve_watch", {"source": "kev", "since": "2026-10-01"})
    assert "fonction bloquée « data.cisa_kev »" in error_text(result)
    assert off.api.requests == []
    down = _setup(tmp_path, World(status={NVD_HOST: 403}))
    arguments = {"source": "nvd", "since": "2026-10-01", "keyword": "x"}
    assert "NVD : accès refusé" in error_text(call(down.server, "cve_watch", arguments))


GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]


@pytest.mark.parametrize("case", GOLDEN, ids=[case["id"] for case in GOLDEN])
def test_golden_cases(tmp_path: Path, case: dict[str, Any]) -> None:
    """The plugin golden set is offline: every case is a refusal decided before any request."""
    setup = _setup(tmp_path, World(records={"CVE-2021-44228": cve()}, kev=[kev_item()]))
    result = call(setup.server, case["tool"], case["arguments"])
    assert result.is_error is case["expected"]["is_error"]
    assert case["expected"]["contains"] in error_text(result)
    assert (setup.api.requests, setup.gate.seen) == ([], [])


def _project(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "config", tmp_path / "config")
    return tmp_path


def test_the_real_sources_without_a_key(tmp_path: Path) -> None:
    sources = build_sources({"CERVEAU_HOME": str(_project(tmp_path))})
    fetchers = {
        "nvd": sources.nvd.fetcher,
        "cisa_kev": sources.kev.fetcher,
        "epss": sources.epss.fetcher,
    }
    intervals = {name: f.throttle.interval_s for name, f in fetchers.items()}
    assert intervals == {"nvd": NVD_INTERVAL_S, "cisa_kev": KEV_INTERVAL_S, "epss": EPSS_INTERVAL_S}
    for name, fetcher in fetchers.items():
        assert fetcher.cache is not None
        assert fetcher.cache.directory == CACHE_DIR / name
        assert fetcher.transport is None
        assert not fetcher.keyed
    assert fetchers["cisa_kev"].max_bytes == kev.MAX_BYTES
    assert sources.products_file == tmp_path / SOURCES_FILE
    sources.gate("data.nvd")


def test_the_key_goes_to_the_nvd_only(tmp_path: Path) -> None:
    environ = {"CERVEAU_HOME": str(tmp_path), "NVD_API_KEY": "fake-nvd-key-for-tests"}
    sources = build_sources(environ)
    assert sources.nvd.fetcher.keyed
    assert sources.nvd.fetcher.throttle.interval_s == NVD_KEYED_INTERVAL_S
    assert not sources.kev.fetcher.keyed
    assert not sources.epss.fetcher.keyed
    with pytest.raises(CyberError, match="configuration invalide"):
        sources.gate("data.nvd")


def test_main_serves_the_real_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CERVEAU_HOME", str(tmp_path))
    monkeypatch.delenv("NVD_API_KEY", raising=False)
    built: list[Any] = []

    class Stub:
        def run(self) -> None:
            built.append("run")

    def fake_build(sources: Sources) -> Stub:
        built.append(sources)
        return Stub()

    monkeypatch.setattr(server_module, "build_server", fake_build)
    server_module.main()
    sources, ran = built
    assert isinstance(sources, Sources)
    assert sources.products_file == tmp_path / SOURCES_FILE
    assert not sources.nvd.fetcher.keyed
    assert ran == "run"
