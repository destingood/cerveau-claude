"""The MCP server, called in process through the SDK client, on an index built from the fixture."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult

from core.cyber.attack import NOTICE, TERMS_URL, AttackIndex, index_path, write_index
from core.cyber.fetch import SOURCES_FILE, record_sha256
from core.evals.attack_sample import BUILT_AT, COMMIT, VERSION, build, bundle, sha256_of
from core.registry.manifest import validate_plugin
from plugins.cyber_attack import server as server_module
from plugins.cyber_attack.models import MAX_RESULTS
from plugins.cyber_attack.search import ORDER, ORDER_ID, Catalogue, QueryError
from plugins.cyber_attack.server import (
    DESCRIPTIONS,
    INVALID_CONFIG,
    IndexReader,
    build_reader,
    build_server,
)

PLUGIN = Path(__file__).resolve().parents[1]
ROOT = PLUGIN.parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
SPECS = {tool["name"]: tool for tool in MANIFEST["tools"]}
SHA256 = sha256_of(bundle())
MISSING = "index ATT&CK 20.0 absent : lancer `cerveau cyber attack-fetch --version 20.0` (the user)"


def _home(tmp_path: Path, *, recorded: bool = True, indexed: bool = True) -> Path:
    """A project as `cerveau cyber attack-fetch` leaves it, here from the synthetic bundle."""
    shutil.copytree(ROOT / "config", tmp_path / "config")
    if recorded:
        record_sha256(tmp_path / "config", SHA256)
    if indexed:
        write_index(index_path(tmp_path, VERSION), build()[0])
    return tmp_path


def _server(home: Path) -> Any:
    return build_server(IndexReader(home, home / "config"))


def run(server: Any, action: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def call(server: Any, arguments: dict[str, Any]) -> CallToolResult:
    return run(server, lambda c: c.call_tool("attack_lookup", arguments))


def data_of(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error, error_text(result)
    assert result.structured_content is not None
    return result.structured_content


def error_text(result: CallToolResult) -> str:
    assert result.is_error
    return " ".join(getattr(block, "text", "") for block in result.content)


def ids(data: dict[str, Any]) -> list[str]:
    return [item["id"] for item in data["results"]]


def test_the_plugin_passes_the_registry() -> None:
    report = validate_plugin(PLUGIN)
    assert report.ok, report.errors
    assert report.plugin_id == "cyber_attack"


def test_the_published_tool_matches_the_manifest(tmp_path: Path) -> None:
    tools = run(_server(_home(tmp_path)), lambda c: c.list_tools()).tools
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


def test_an_identifier_gives_the_object_its_links_and_the_copy(tmp_path: Path) -> None:
    data = data_of(call(_server(_home(tmp_path)), {"query": " t1059.001 "}))
    assert (data["query"], data["match"], data["order"]) == ("T1059.001", "identifiant", ORDER_ID)
    assert (data["total_matches"], data["more_available"]) == (1, False)
    (item,) = data["results"]
    assert (item["id"], item["kind"], item["name"], item["status"]) == (
        "T1059.001",
        "subtechnique",
        "PowerShell",
        "en vigueur",
    )
    assert item["url"] == "https://attack.mitre.org/techniques/T1059/001"
    assert item["description"] == (
        "Adversaries may abuse PowerShell commands and scripts for execution."
    )
    assert item["parent"] == {"id": "T1059", "name": "Command and Scripting Interpreter"}
    assert item["tactics"] == [{"id": "TA0002", "name": "Execution"}]
    assert item["mitigations"] == [{"id": "M1042", "name": "Disable or Remove Feature or Program"}]
    assert item["detection_strategies"] == [{"id": "DET0001", "name": "Detect PowerShell abuse"}]
    assert (item["revoked_by"], item["lists_truncated"]) == (None, False)
    assert data["source"] == {
        "name": "MITRE ATT&CK Enterprise",
        "version": VERSION,
        "commit": COMMIT,
        "bundle_sha256": SHA256,
        "built_at": BUILT_AT,
        "notice": NOTICE,
        "terms_url": TERMS_URL,
    }


def test_a_revoked_identifier_comes_with_its_replacement(tmp_path: Path) -> None:
    data = data_of(call(_server(_home(tmp_path)), {"query": "T1086"}))
    assert ids(data) == ["T1086", "T1059.001"]
    old, new = data["results"]
    assert (old["status"], old["revoked_by"]) == (
        "révoqué",
        {"id": "T1059.001", "name": "PowerShell"},
    )
    assert new["status"] == "en vigueur"
    assert data["total_matches"] == 2


def test_an_unknown_identifier_finds_nothing(tmp_path: Path) -> None:
    data = data_of(call(_server(_home(tmp_path)), {"query": "T9999"}))
    assert (ids(data), data["total_matches"], data["match"]) == ([], 0, "identifiant")


def test_keywords_follow_the_published_order(tmp_path: Path) -> None:
    server = _server(_home(tmp_path))
    data = data_of(call(server, {"query": "PowerShell", "max_results": 10}))
    # Current objects first, the name before the description, then the kind.
    assert ids(data) == ["T1059.001", "DET0001", "G0007", "T1086"]
    assert (data["match"], data["order"], data["query"]) == ("mots-clés", ORDER, "PowerShell")
    assert (data["total_matches"], data["more_available"]) == (4, False)
    first = data_of(call(server, {"query": "powershell", "max_results": 1}))
    assert (ids(first), first["total_matches"], first["more_available"]) == (
        ["T1059.001"],
        4,
        True,
    )


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("\x07powershell", "caractère de contrôle"),
        ("power​shell", "caractère de contrôle, invisible ou non attribué refusé"),
        ("‮T1059", "caractère de contrôle"),
        ("   ", "query : 1 à 200 caractères"),
        ("a b c", "query : au moins un mot de 2 caractères"),
        ("one two three four five six seven eight nine", "query : 8 mots au plus"),
        ("x" * 201, "validation"),
    ],
    ids=["bell", "zero-width", "bidi", "blank", "letters", "nine", "long"],
)
def test_a_refused_query_is_not_quoted(tmp_path: Path, query: str, message: str) -> None:
    text = error_text(call(_server(_home(tmp_path)), {"query": query}))
    assert message in text
    if message != "validation" and query.strip():
        assert query.strip() not in text


def _disable(home: Path) -> None:
    path = home / "config" / SOURCES_FILE
    data = path.read_bytes()
    old = b"    enabled: true                     # G5"
    assert old in data
    path.write_bytes(data.replace(old, b"    enabled: false", 1))


def _edit(home: Path, old: bytes, new: bytes) -> None:
    path = home / "config" / SOURCES_FILE
    data = path.read_bytes()
    assert data.count(old) == 1
    path.write_bytes(data.replace(old, new))


def _alter(home: Path) -> None:
    path = index_path(home, VERSION)
    path.write_text(path.read_text(encoding="utf-8").replace('"T1059"', '"X1059"', 1), "utf-8")


@pytest.mark.parametrize(
    ("prepare", "message"),
    [
        (lambda home: index_path(home, VERSION).unlink(), MISSING),
        (_disable, "source « attack » absente ou désactivée (R7)"),
        (_alter, "illisible ou altéré"),
        (lambda home: (home / "config" / SOURCES_FILE).write_text("[", "utf-8"), INVALID_CONFIG),
        (
            lambda home: _edit(home, b'version: "20.0"', b'version: "latest"'),
            "source « attack » sans version valide (R7)",
        ),
        (
            lambda home: _edit(home, b'version: "20.0"', b'version: "20.0"\n    terms: A_DEFINIR'),
            "fonction bloquée « data.attack » : ",
        ),
    ],
    ids=["no-index", "disabled", "altered", "config", "version", "blocked"],
)
def test_the_tool_needs_the_index_the_configuration_designates(
    tmp_path: Path, prepare: Callable[[Path], object], message: str
) -> None:
    home = _home(tmp_path)
    prepare(home)
    assert message in error_text(call(_server(home), {"query": "T1059"}))


@pytest.mark.parametrize("count", [0, MAX_RESULTS + 1], ids=["none", "too-many"])
def test_the_catalogue_bounds_the_number_of_results(count: int) -> None:
    with pytest.raises(QueryError, match=f"^max_results : 1 à {MAX_RESULTS}$"):
        Catalogue(build()[0]).lookup("T1059", max_results=count)


def test_an_unknown_digest_names_the_command(tmp_path: Path) -> None:
    home = _home(tmp_path, recorded=False)
    text = error_text(call(_server(home), {"query": "T1059"}))
    assert text.endswith(
        ": index absent : lancer `cerveau cyber attack-fetch --version 20.0` (the user)"
    )


def test_an_index_of_another_bundle_is_refused(tmp_path: Path) -> None:
    home = _home(tmp_path, recorded=False)
    record_sha256(home / "config", "cd" * 32)
    text = error_text(call(_server(home), {"query": "T1059"}))
    assert "index d'une autre version ou d'un autre bundle que la configuration" in text


def test_the_index_is_read_again_only_when_its_file_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _home(tmp_path)
    reads: list[Path] = []
    real = server_module.read_index

    def counted(path: Path, version: str) -> AttackIndex:
        reads.append(path)
        return real(path, version)

    monkeypatch.setattr(server_module, "read_index", counted)
    reader = IndexReader(home, home / "config")
    first = reader.catalogue()
    assert reader.catalogue() is first
    assert len(reads) == 1
    path = index_path(home, VERSION)
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert reader.catalogue() is not first
    assert len(reads) == 2


GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]


@pytest.mark.parametrize("case", GOLDEN, ids=[case["id"] for case in GOLDEN])
def test_golden_cases(tmp_path: Path, case: dict[str, Any]) -> None:
    """Offline: refusals, and searches in the index built from the synthetic bundle."""
    result = call(_server(_home(tmp_path)), case["arguments"])
    expected = case["expected"]
    assert result.is_error is expected["is_error"]
    if expected["is_error"]:
        assert expected["contains"] in error_text(result)
        return
    data = data_of(result)
    assert (data["match"], ids(data)) == (expected["match"], expected["ids"])
    assert data["total_matches"] == expected["total_matches"]
    assert data["more_available"] is expected["more_available"]


def test_the_reader_serves_the_home_it_is_given(tmp_path: Path) -> None:
    reader = build_reader({"CERVEAU_HOME": str(tmp_path)})
    assert (reader.home, reader.config_dir) == (tmp_path, tmp_path / "config")


def test_main_serves_the_index_of_cerveau_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CERVEAU_HOME", str(tmp_path))
    built: list[Any] = []

    class Stub:
        def run(self) -> None:
            built.append("run")

    def fake_build(reader: IndexReader) -> Stub:
        built.append(reader)
        return Stub()

    monkeypatch.setattr(server_module, "build_server", fake_build)
    server_module.main()
    reader, ran = built
    assert isinstance(reader, IndexReader)
    assert (reader.home, ran) == (tmp_path, "run")
