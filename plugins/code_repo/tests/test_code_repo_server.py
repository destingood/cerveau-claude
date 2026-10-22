"""The MCP server, called in process through the SDK client, on a repository built in tmp_path."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult

from core.code import repos
from core.code.git import GitRunner
from core.code.repos import RepoError, RepoReader
from core.config.loader import CodeRepository
from core.registry.manifest import validate_plugin
from plugins.code_repo import server as server_module
from plugins.code_repo.server import MAX_ENTRIES, build_server
from plugins.code_repo.tests.support import ENV_VALUE, LONG_LINES, TOKEN, example_repo
from tests.code_support import commit, listed
from tests.conftest import REPO_ROOT

PLUGIN = Path(__file__).resolve().parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
SPECS = {tool["name"]: tool for tool in MANIFEST["tools"]}


@pytest.fixture(scope="module")
def example(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return example_repo(tmp_path_factory.mktemp("exemple"))


def server_for(repositories: Sequence[CodeRepository]) -> Any:
    return build_server(lambda: repositories, RepoReader(GitRunner()))


def run(server: Any, action: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def call(server: Any, tool: str, arguments: dict[str, Any]) -> CallToolResult:
    return run(server, lambda c: c.call_tool(tool, arguments))


def data(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error, text(result)
    assert result.structured_content is not None
    return result.structured_content


def text(result: CallToolResult) -> str:
    return " ".join(getattr(block, "text", "") for block in result.content)


def error_text(result: CallToolResult) -> str:
    assert result.is_error
    return text(result)


@pytest.fixture(scope="module")
def server(example: Path) -> Any:
    return server_for([listed("exemple", example)])


# --- the manifest -----------------------------------------------------------------------------


def test_the_plugin_passes_the_registry() -> None:
    report = validate_plugin(PLUGIN)
    assert report.ok, report.errors
    assert report.plugin_id == "code_repo"


def test_published_tools_match_the_manifest() -> None:
    tools = run(server_for([]), lambda c: c.list_tools()).tools
    assert [t.name for t in tools] == list(SPECS)
    for tool in tools:
        spec = SPECS[tool.name]
        assert spec["action_class"] == "LECTURE"
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


# --- repo_log ---------------------------------------------------------------------------------


def test_the_log_lists_commits_newest_first_without_emails(server: Any) -> None:
    result = data(call(server, "repo_log", {"repo": "exemple"}))
    subjects = [c["subject"] for c in result["commits"]]
    assert subjects == [
        "rotation du jeton [MASQUÉ]",
        "sous-module",
        "ajoute un lien",
        "initial",
    ]
    assert result["masked"] == 1
    assert result["more_commits"] is False
    first = result["commits"][0]
    assert first["author"] == "Lucas Test"
    assert first["date"] == "2026-10-20T10:00:00+02:00"
    assert len(first["sha"]) == 40
    assert "example.test" not in json.dumps(result)
    assert TOKEN not in json.dumps(result)


def test_the_log_is_bounded_and_says_so(server: Any) -> None:
    result = data(call(server, "repo_log", {"repo": "exemple", "max_count": 2}))
    assert len(result["commits"]) == 2
    assert result["more_commits"] is True
    older = data(call(server, "repo_log", {"repo": "exemple", "rev": "v1"}))
    assert [c["subject"] for c in older["commits"]] == ["initial"]


def test_a_cut_log_keeps_whole_commits(example: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module, "MAX_LOG_BYTES", 120)
    result = data(call(server_for([listed("exemple", example)]), "repo_log", {"repo": "exemple"}))
    assert [c["subject"] for c in result["commits"]] == ["rotation du jeton [MASQUÉ]"]


# --- repo_diff --------------------------------------------------------------------------------


def test_a_diff_withholds_sensitive_files_and_masks_secrets(server: Any) -> None:
    result = data(call(server, "repo_diff", {"repo": "exemple", "base": "HEAD~1"}))
    assert result["files"] == [{"path": "src/app.py", "added": 3, "deleted": 1}]
    assert result["withheld"] == [".env"]
    assert result["note"] is None
    patch = result["patch"]
    assert patch.startswith("diff --git a/src/app.py b/src/app.py")
    assert '+TOKEN = "[MASQUÉ]"' in patch
    assert "⟨U+202E⟩" in patch
    assert result["masked"] == 1
    dumped = json.dumps(result, ensure_ascii=False)
    assert TOKEN not in dumped
    assert ENV_VALUE not in dumped
    assert ".env b/.env" not in patch


def test_a_diff_shows_links_and_submodules_as_entries(server: Any) -> None:
    result = data(call(server, "repo_diff", {"repo": "exemple", "base": "v1", "head": "HEAD~1"}))
    assert [f["path"] for f in result["files"]] == ["lien", "vendor/lib"]
    assert "Subproject commit" in result["patch"]
    assert "new file mode 120000" in result["patch"]


def test_a_binary_change_has_no_line_counts(tmp_path: Path) -> None:
    repo = example_repo(tmp_path / "depot")
    commit(repo, {"data.bin": b"\x00\x01\x02"}, "binaire")
    result = data(
        call(server_for([listed("p", repo)]), "repo_diff", {"repo": "p", "base": "HEAD~1"})
    )
    assert result["files"] == [{"path": "data.bin", "added": None, "deleted": None}]
    assert "Binary files" in result["patch"]


def test_only_sensitive_changes_show_no_patch(tmp_path: Path) -> None:
    repo = example_repo(tmp_path / "depot")
    commit(repo, {".env": "API_KEY=autre\n"}, "env")
    result = data(
        call(server_for([listed("p", repo)]), "repo_diff", {"repo": "p", "base": "HEAD~1"})
    )
    assert (result["files"], result["withheld"], result["patch"]) == ([], [".env"], "")


def test_too_many_sensitive_files_hide_the_patch(
    example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_module, "MAX_WITHHELD", 0)
    result = data(
        call(
            server_for([listed("exemple", example)]),
            "repo_diff",
            {"repo": "exemple", "base": "HEAD~1"},
        )
    )
    assert result["patch"] == ""
    assert "patch non montré (R6)" in result["note"]
    assert result["files"] == [{"path": "src/app.py", "added": 3, "deleted": 1}]


def test_a_long_diff_is_cut_and_says_so(example: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module, "MAX_FILES", 1)
    monkeypatch.setattr(server_module, "TEXT_CHARS", 50)
    result = data(
        call(
            server_for([listed("exemple", example)]),
            "repo_diff",
            {"repo": "exemple", "base": "v1", "head": "HEAD~1"},
        )
    )
    assert len(result["files"]) == 1
    assert result["more_files"] == 1
    assert result["patch_truncated"] is True
    assert len(result["patch"]) <= 50


# --- repo_file --------------------------------------------------------------------------------


def test_the_root_is_listed_with_sensitive_entries_named_only(server: Any) -> None:
    result = data(call(server, "repo_file", {"repo": "exemple"}))
    entries = {e["name"]: e for e in result["entries"]}
    assert set(entries) == {
        ".env",
        ".env.example",
        "README.md",
        "data.bin",
        "lien",
        "src",
        "vendor",
    }
    assert entries[".env"]["withheld"] is True
    assert entries[".env.example"]["withheld"] is False
    assert (entries["src"]["kind"], entries["lien"]["kind"]) == ("directory", "symlink")
    assert (result["kind"], result["path"], result["content"]) == ("directory", "", None)


def test_a_folder_is_listed(server: Any) -> None:
    result = data(call(server, "repo_file", {"repo": "exemple", "path": "src/"}))
    assert result["path"] == "src"
    assert [(e["name"], e["kind"]) for e in result["entries"]] == [
        ("app.py", "file"),
        ("long.py", "file"),
    ]


def test_a_large_folder_is_cut(example: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module, "MAX_ENTRIES", 2)
    result = data(call(server_for([listed("exemple", example)]), "repo_file", {"repo": "exemple"}))
    assert (len(result["entries"]), result["more_entries"]) == (2, 5)
    assert MAX_ENTRIES == 300


def test_a_file_is_read_with_its_lines(server: Any) -> None:
    result = data(call(server, "repo_file", {"repo": "exemple", "path": "README.md"}))
    assert result["content"] == "# Exemple\n\nProjet de démonstration du pack code."
    assert (result["kind"], result["total_lines"], result["start_line"], result["end_line"]) == (
        "file",
        3,
        1,
        3,
    )
    assert result["content_truncated"] is False
    assert result["size"] == len("# Exemple\n\nProjet de démonstration du pack code.\n".encode())


def test_a_long_file_is_read_slice_by_slice(server: Any) -> None:
    first = data(call(server, "repo_file", {"repo": "exemple", "path": "src/long.py"}))
    assert (first["start_line"], first["end_line"], first["total_lines"]) == (1, 200, LONG_LINES)
    assert first["content_truncated"] is True
    last = data(
        call(
            server,
            "repo_file",
            {"repo": "exemple", "path": "src/long.py", "start_line": 401, "max_lines": 400},
        )
    )
    assert (last["start_line"], last["end_line"]) == (401, LONG_LINES)
    assert last["content"].splitlines()[-1] == f"x_{LONG_LINES} = {LONG_LINES}"
    assert last["content_truncated"] is False


def test_secrets_and_invisible_characters_in_a_file(server: Any) -> None:
    result = data(call(server, "repo_file", {"repo": "exemple", "path": "src/app.py"}))
    assert 'TOKEN = "[MASQUÉ]"' in result["content"]
    assert "⟨U+202E⟩" in result["content"]
    assert result["masked"] == 1
    old = data(call(server, "repo_file", {"repo": "exemple", "path": "src/app.py", "rev": "v1"}))
    assert old["content"] == "def main() -> int:\n    return 1"


def test_an_empty_file_has_no_lines(tmp_path: Path) -> None:
    repo = example_repo(tmp_path / "depot")
    commit(repo, {"vide.txt": ""}, "vide")
    result = data(
        call(server_for([listed("p", repo)]), "repo_file", {"repo": "p", "path": "vide.txt"})
    )
    assert (result["total_lines"], result["start_line"], result["content"]) == (0, None, "")


def test_a_bom_is_dropped(tmp_path: Path) -> None:
    repo = example_repo(tmp_path / "depot")
    commit(repo, {"bom.txt": "\ufeffbonjour\n"}, "bom")
    result = data(
        call(server_for([listed("p", repo)]), "repo_file", {"repo": "p", "path": "bom.txt"})
    )
    assert result["content"] == "bonjour"


def test_a_long_line_is_clipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = example_repo(tmp_path / "depot")
    monkeypatch.setattr(server_module, "TEXT_CHARS", 10)
    result = data(
        call(server_for([listed("p", repo)]), "repo_file", {"repo": "p", "path": "README.md"})
    )
    assert result["content_truncated"] is True
    assert len(result["content"]) <= 10


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"path": "lien"}, "lien symbolique : jamais suivi"),
        ({"path": "vendor/lib"}, "sous-module : hors du dépôt"),
        ({"path": "data.bin"}, "fichier binaire : non montré"),
        ({"path": ".env"}, "fichier sensible, jamais lu (R6)"),
        ({"path": "../autre"}, "chemin refusé"),
        ({"path": ".git/config"}, "le dossier .git n'est pas lisible"),
        ({"path": "absent.py"}, "« absent.py » introuvable à la révision « HEAD »"),
        ({"path": "src/long.py", "start_line": 451}, "450 lignes : début 451 hors du fichier"),
        ({"path": "README.md", "rev": "absente"}, "révision « absente » introuvable"),
    ],
)
def test_file_refusals(server: Any, arguments: dict[str, Any], message: str) -> None:
    assert message in error_text(call(server, "repo_file", {"repo": "exemple", **arguments}))


def test_a_large_file_is_refused(example: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module, "MAX_FILE_BYTES", 10)
    result = call(
        server_for([listed("exemple", example)]),
        "repo_file",
        {"repo": "exemple", "path": "src/long.py"},
    )
    assert "plus de 10 octets, non lu" in error_text(result)


def test_an_unknown_entry_type_is_refused(example: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(repos.MODES, "100644", "other")
    result = call(
        server_for([listed("exemple", example)]),
        "repo_file",
        {"repo": "exemple", "path": "README.md"},
    )
    assert "type d'entrée non pris en charge" in error_text(result)


# --- the allow list ---------------------------------------------------------------------------


def test_the_allow_list_is_read_at_each_call(example: Path) -> None:
    lists: list[list[CodeRepository]] = [[], [listed("exemple", example)]]
    server = build_server(lambda: lists.pop(0), RepoReader(GitRunner()))
    first = call(server, "repo_log", {"repo": "exemple"})
    assert "liste blanche des dépôts est vide" in error_text(first)
    assert data(call(server, "repo_log", {"repo": "exemple"}))["commits"]


def test_a_blocked_allow_list_is_a_tool_error(example: Path) -> None:
    def blocked() -> list[CodeRepository]:
        raise RepoError("fonction bloquée « code.repositories »")

    server = build_server(blocked, RepoReader(GitRunner()))
    for tool, arguments in (
        ("repo_log", {"repo": "exemple"}),
        ("repo_diff", {"repo": "exemple", "base": "HEAD~1"}),
        ("repo_file", {"repo": "exemple"}),
    ):
        assert "fonction bloquée" in error_text(call(server, tool, arguments))


def test_cerveau_is_never_readable_even_when_listed() -> None:
    server = server_for([listed("cerveau", REPO_ROOT)])
    for tool, arguments in (
        ("repo_log", {"repo": "cerveau"}),
        ("repo_diff", {"repo": "cerveau", "base": "HEAD~1"}),
        ("repo_file", {"repo": "cerveau", "path": "README.md"}),
    ):
        assert "recouvre le dépôt CERVEAU (ADR-047)" in error_text(call(server, tool, arguments))


# --- golden set -------------------------------------------------------------------------------


GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]


@pytest.mark.parametrize("case", GOLDEN, ids=[case["id"] for case in GOLDEN])
def test_golden_cases(case: dict[str, Any], example: Path) -> None:
    """Offline: each case runs on the example repository of ``support.py`` (or on CERVEAU)."""
    allow = {
        "exemple": [listed("exemple", example)],
        "vide": [],
        "cerveau": [listed("cerveau", REPO_ROOT)],
    }[case.get("allowlist", "exemple")]
    result = call(server_for(allow), case["tool"], case["arguments"])
    expected = case["expected"]
    assert result.is_error is expected["is_error"]
    shown = text(result) if result.is_error else json.dumps(data(result), ensure_ascii=False)
    assert expected["contains"] in shown
    for absent in expected.get("absent", []):
        assert absent not in shown


def test_the_golden_set_never_shows_the_example_secrets() -> None:
    raw = (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8")
    assert TOKEN not in raw
    assert ENV_VALUE in raw  # named only in "absent"


# --- entry point ------------------------------------------------------------------------------


def test_main_reads_the_allow_list_of_the_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    built: list[Any] = []

    class Stub:
        def run(self) -> None:
            built.append("run")

    def fake_build(repositories: Any, reader: Any) -> Stub:
        built.extend([repositories, reader])
        return Stub()

    monkeypatch.setenv("CERVEAU_HOME", str(tmp_path))
    monkeypatch.setattr(server_module, "build_server", fake_build)
    calls: list[Path] = []
    monkeypatch.setattr(server_module, "load_repositories", lambda d: calls.append(d) or ())
    server_module.main()
    repositories, reader, ran = built
    assert repositories() == ()
    assert isinstance(reader, RepoReader)
    assert isinstance(reader.git, GitRunner)
    assert reader.cerveau == REPO_ROOT.resolve()
    assert ran == "run"
    assert calls == [tmp_path / "config"]
