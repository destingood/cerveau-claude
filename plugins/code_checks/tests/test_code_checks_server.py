"""The MCP server, called in process through the SDK client, with a fake Docker (support.py)."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult

from core.code.git import GitRunner
from core.code.process import Bounded
from core.code.repos import RepoReader
from core.code.sandbox import KILL_TIMEOUT_S, DockerRunner, SandboxError, docker_command
from core.config.loader import CHECKS_CEILINGS, CodeRepository
from core.mcp.time_limit import TIME_LIMIT_META_KEY
from core.registry.manifest import validate_plugin
from plugins.code_checks import server as server_module
from plugins.code_checks.models import MAX_SHOWN
from plugins.code_checks.server import (
    BUDGET_S,
    MAX_OUTPUT_BYTES,
    NOT_PREPARED,
    PYTEST,
    RESERVE_S,
    RUFF_CHECK,
    RUFF_FORMAT,
    Settings,
    build_server,
    load_settings,
)
from plugins.code_checks.tests.support import (
    ENV_VALUE,
    IMAGE,
    INJECTION,
    REPO_IMAGE,
    SCENARIOS,
    TOKEN,
    Clock,
    FakeDocker,
    allow_lists,
    example_repo,
    item,
    out,
    ruff,
    settings,
)
from tests.code_support import listed
from tests.conftest import REPO_ROOT

PLUGIN = Path(__file__).resolve().parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
(SPEC,) = MANIFEST["tools"]


@pytest.fixture(scope="module")
def example(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return example_repo(tmp_path_factory.mktemp("exemple"))


def run(server: Any, action: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def text(result: CallToolResult) -> str:
    return " ".join(getattr(block, "text", "") for block in result.content)


def checks_with(
    repositories: Sequence[CodeRepository],
    docker: FakeDocker,
    runs: Path,
    arguments: Mapping[str, Any] | None = None,
    *,
    meta: Any = None,
    **limits: Any,
) -> CallToolResult:
    current = settings(repositories, **limits)
    server = build_server(lambda: current, RepoReader(GitRunner()), docker, runs, docker.clock)
    arguments = {"repo": "exemple", **(arguments or {})}
    return run(server, lambda c: c.call_tool("run_checks", arguments, meta=meta))


def data(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error, text(result)
    assert result.structured_content is not None
    return result.structured_content


def scenario(
    name: str | Mapping[str, Bounded],
    example: Path,
    tmp_path: Path,
    arguments: Mapping[str, Any] | None = None,
    allow: str = "exemple",
    **limits: Any,
) -> tuple[dict[str, Any], FakeDocker]:
    docker = FakeDocker(SCENARIOS[name] if isinstance(name, str) else name)
    result = checks_with(
        allow_lists(example)[allow], docker, tmp_path / "runs", arguments, **limits
    )
    return data(result), docker


# --- the manifest -----------------------------------------------------------------------------


def test_the_plugin_passes_the_registry() -> None:
    report = validate_plugin(PLUGIN)
    assert report.ok, report.errors
    assert report.plugin_id == "code_checks"


def test_the_call_limit_covers_e5_and_the_reserve() -> None:
    """ADR-052 (B272): the containers may use the whole 300 s of E5 when the budget allows."""
    manifest = validate_plugin(PLUGIN).manifest
    assert manifest is not None and manifest.runtime is not None
    assert manifest.runtime.tool_timeout_s == CHECKS_CEILINGS["timeout_seconds"] + RESERVE_S
    assert RESERVE_S > KILL_TIMEOUT_S


def test_the_published_tool_matches_the_manifest(tmp_path: Path) -> None:
    server = build_server(lambda: settings([]), RepoReader(GitRunner()), FakeDocker({}), tmp_path)
    (tool,) = run(server, lambda c: c.list_tools()).tools
    assert tool.name == SPEC["name"] == "run_checks"
    assert SPEC["action_class"] == "CALCUL"
    assert tool.description == SPEC["description"]
    assert tool.annotations.model_dump(by_alias=True, exclude_none=True) == SPEC["annotations"]
    for kind, schema in (
        ("input_schema", tool.input_schema),
        ("output_schema", tool.output_schema),
    ):
        on_disk = json.loads((PLUGIN / SPEC[kind]).read_text(encoding="utf-8"))
        on_disk.pop("$schema")
        assert schema == on_disk, f"{SPEC[kind]} is stale: regenerate it from the server"


# --- what runs, where, with what --------------------------------------------------------------


def test_a_clean_repository(example: Path, tmp_path: Path) -> None:
    result, docker = scenario("propre", example, tmp_path)
    assert (result["repo"], result["rev"], len(result["sha"])) == ("exemple", "HEAD", 40)
    assert result["ruff_check"] == {
        "status": "ok",
        "note": None,
        "count": 0,
        "by_code": {},
        "diagnostics": [],
        "more_diagnostics": 0,
    }
    assert result["ruff_format"] == {
        "status": "ok",
        "note": None,
        "count": 0,
        "files": [],
        "more_files": 0,
    }
    assert result["pytest"] == {
        "status": "ok",
        "note": None,
        "counts": {"passed": 2},
        "failed": [],
        "errors": [],
        "more_failures": 0,
    }
    assert result["budget_seconds"] == BUDGET_S  # no limit sent with the call
    assert [call.step for call in docker.calls] == ["check", "format", "pytest"]


def test_each_container_gets_the_hardened_command(example: Path, tmp_path: Path) -> None:
    _, docker = scenario("propre", example, tmp_path, cpus=1.5, memory_mb=512, pids=64)
    check, form, tests = docker.calls
    for call in docker.calls:
        assert call.max_bytes == MAX_OUTPUT_BYTES
        assert re.fullmatch(r"cerveau-check-[0-9a-f]{12}", call.name)
        mount = call.arguments[call.arguments.index("--mount") + 1]
        source = Path(mount.split(",")[1].removeprefix("source="))
        assert source.parent == tmp_path / "runs"
    assert len({call.name for call in docker.calls}) == 3
    limits = server_module.Limits(1.5, 512, 64)

    def expected(call: Any, image: str, program: str, arguments: Sequence[str]) -> list[str]:
        mount = call.arguments[call.arguments.index("--mount") + 1]
        source = Path(mount.split(",")[1].removeprefix("source="))
        return docker_command(call.name, image, source, limits, program, arguments)

    assert check.arguments == expected(check, IMAGE, "ruff", RUFF_CHECK)
    assert form.arguments == expected(form, IMAGE, "ruff", RUFF_FORMAT)
    # pytest runs in the repository's own image, prepared by Lucas (E3).
    assert tests.arguments == expected(tests, REPO_IMAGE, "python", PYTEST)


def test_the_containers_see_the_committed_files_only(example: Path, tmp_path: Path) -> None:
    (example / "src" / "brouillon.py").write_text("non commité\n", encoding="utf-8")
    try:
        result, docker = scenario("propre", example, tmp_path)
    finally:
        (example / "src" / "brouillon.py").unlink()
    for call in docker.calls:
        assert call.files == ["README.md", "src/app.py", "tests/test_app.py"]
    assert result["source"] == {
        "files": 3,
        "bytes": result["source"]["bytes"],
        "withheld": [".env"],
        "more_withheld": 0,
        "skipped": ["lien"],
        "more_skipped": 0,
        "removed": True,
    }
    assert result["source"]["bytes"] > 0
    # The copy is gone once the call ends.
    assert list((tmp_path / "runs").iterdir()) == []
    assert ENV_VALUE not in json.dumps(result)


def test_a_copy_that_cannot_be_removed_is_reported(
    example: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_module.shutil, "rmtree", lambda path, ignore_errors: None)
    result, _ = scenario("propre", example, tmp_path)
    assert result["source"]["removed"] is False


def test_a_revision_is_checked_at_its_commit(example: Path, tmp_path: Path) -> None:
    result, _ = scenario("propre", example, tmp_path, {"rev": "HEAD~1"})
    head, _ = scenario("propre", example, tmp_path)
    assert result["rev"] == "HEAD~1"
    assert result["sha"] != head["sha"]
    assert result["source"]["skipped"] == []


# --- ruff -------------------------------------------------------------------------------------


def test_violations_are_counted_by_code(example: Path, tmp_path: Path) -> None:
    result, _ = scenario("violations", example, tmp_path)
    check = result["ruff_check"]
    assert (check["status"], check["count"]) == ("echec", 3)
    assert check["by_code"] == {"F401": 2, "E501": 1}
    assert check["diagnostics"][0] == {
        "path": "src/app.py",
        "line": 1,
        "column": 8,
        "code": "F401",
        "message": "`os` imported but unused",
    }
    assert result["ruff_format"]["files"] == ["src/app.py"]
    assert (result["ruff_format"]["status"], result["ruff_format"]["count"]) == ("echec", 1)


def test_diagnostics_past_the_limit_are_counted_not_shown(example: Path, tmp_path: Path) -> None:
    many = [item(f"m{i}.py", "F401", "unused") for i in range(MAX_SHOWN + 7)]
    replies = {"check": ruff(*many), "format": ruff(*many), "pytest": SCENARIOS["propre"]["pytest"]}
    result, _ = scenario(replies, example, tmp_path)
    assert result["ruff_check"]["count"] == MAX_SHOWN + 7
    assert len(result["ruff_check"]["diagnostics"]) == MAX_SHOWN
    assert result["ruff_check"]["more_diagnostics"] == 7
    assert len(result["ruff_format"]["files"]) == MAX_SHOWN
    assert result["ruff_format"]["more_files"] == 7


def test_texts_are_data_bounded_masked_and_visible(example: Path, tmp_path: Path) -> None:
    result, _ = scenario("injection", example, tmp_path)
    (diagnostic,) = result["ruff_check"]["diagnostics"]
    assert diagnostic["path"] == "src/a⟨U+202E⟩pp.py"
    assert diagnostic["message"] == INJECTION
    secret, _ = scenario("secret", example, tmp_path)
    assert TOKEN not in json.dumps(secret)
    assert "[MASQUÉ]" in secret["ruff_check"]["diagnostics"][0]["message"]
    assert secret["pytest"]["failed"] == ["tests/test_app.py::test_main"]
    long = "x" * 1_000
    replies = {
        "check": ruff(item("a.py", "E" * 100, long + "\nsuite")),
        "format": ruff(),
        "pytest": SCENARIOS["propre"]["pytest"],
    }
    clipped, _ = scenario(replies, example, tmp_path)
    (diagnostic,) = clipped["ruff_check"]["diagnostics"]
    assert len(diagnostic["message"]) == server_module.MESSAGE_CHARS
    assert diagnostic["message"].endswith("…")
    assert len(diagnostic["code"]) == server_module.CODE_CHARS
    assert list(clipped["ruff_check"]["by_code"]) == [diagnostic["code"]]


@pytest.mark.parametrize(
    ("reply", "note"),
    [
        (out(1, "pas du JSON"), "sortie de ruff illisible"),
        (out(2, "", "ruff: erreur"), "ruff s'est arrêté anormalement (code 2)"),
        (out(1, "[]"), "code de sortie de ruff et diagnostics incohérents"),
        (out(0, json.dumps([item("a.py", "F401", "x")])), "incohérents"),
    ],
)
def test_an_unreadable_ruff_is_an_error(
    reply: Bounded, note: str, example: Path, tmp_path: Path
) -> None:
    replies = {"check": reply, "format": reply, "pytest": SCENARIOS["propre"]["pytest"]}
    result, _ = scenario(replies, example, tmp_path)
    for step in ("ruff_check", "ruff_format"):
        assert result[step]["status"] == "erreur"
        assert note in result[step]["note"]
        assert result[step]["count"] is None
    assert result["ruff_check"]["by_code"] == {}


# --- Docker, time and output limits -----------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "note"),
    [
        (125, "Docker n'a pas lancé le conteneur (code 125)"),
        (126, "non exécutable (code 126)"),
        (127, "introuvable dans l'image (code 127)"),
    ],
)
def test_a_container_docker_did_not_run_is_an_error(
    code: int, note: str, example: Path, tmp_path: Path
) -> None:
    down = out(code, stderr="détail du moteur")
    result, _ = scenario({"check": down, "format": down, "pytest": down}, example, tmp_path)
    for step in ("ruff_check", "ruff_format", "pytest"):
        assert result[step]["status"] == "erreur"
        assert note in result[step]["note"]
    assert "détail du moteur" not in json.dumps(result)


def test_a_slow_container_is_stopped_and_spends_the_budget(example: Path, tmp_path: Path) -> None:
    result, docker = scenario("lent", example, tmp_path)
    assert result["ruff_check"]["status"] == "delai"
    assert result["ruff_check"]["note"] == "délai de 25 s dépassé : conteneur arrêté"
    for step in ("ruff_format", "pytest"):
        assert result[step]["status"] == "non_lance"
        assert "budget de temps épuisé" in result[step]["note"]
    assert [call.step for call in docker.calls] == ["check"]


def test_the_budget_is_shared_by_the_containers(example: Path, tmp_path: Path) -> None:
    docker = FakeDocker(SCENARIOS["propre"], takes=4.0)
    data(checks_with(allow_lists(example)["exemple"], docker, tmp_path, timeout_seconds=10))
    assert [call.timeout_s for call in docker.calls] == [10.0, 6.0, 2.0]
    late = FakeDocker(SCENARIOS["propre"], takes=4.5)
    result = data(checks_with(allow_lists(example)["exemple"], late, tmp_path, timeout_seconds=10))
    assert [call.timeout_s for call in late.calls] == [10.0, 5.5]
    assert result["pytest"]["status"] == "non_lance"
    assert result["budget_seconds"] == 10.0


@pytest.mark.parametrize(("limit", "budget"), [(315, 300.0), (100, 85.0), (40.5, 25.5)])
def test_the_containers_share_the_limit_sent_with_the_call(
    limit: float, budget: float, example: Path, tmp_path: Path
) -> None:
    """ADR-052: the call's limit less the reserve, within the configured E5 time."""
    docker = FakeDocker(SCENARIOS["propre"])
    meta = {TIME_LIMIT_META_KEY: limit}
    result = data(checks_with(allow_lists(example)["exemple"], docker, tmp_path, meta=meta))
    assert result["budget_seconds"] == budget
    assert docker.calls[0].timeout_s == budget


def test_a_call_cut_too_soon_launches_no_container(example: Path, tmp_path: Path) -> None:
    docker = FakeDocker(SCENARIOS["propre"])
    meta = {TIME_LIMIT_META_KEY: RESERVE_S - 1}
    result = data(checks_with(allow_lists(example)["exemple"], docker, tmp_path, meta=meta))
    assert result["budget_seconds"] == 0.0
    assert docker.calls == []
    for step in ("ruff_check", "ruff_format", "pytest"):
        assert result[step]["status"] == "non_lance"


def test_the_configured_time_comes_first(example: Path, tmp_path: Path) -> None:
    docker = FakeDocker(SCENARIOS["propre"])
    meta = {TIME_LIMIT_META_KEY: 315}
    repos = allow_lists(example)["exemple"]
    result = data(checks_with(repos, docker, tmp_path, meta=meta, timeout_seconds=60))
    assert result["budget_seconds"] == 60.0


def test_the_copy_counts_in_the_budget(
    example: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    docker = FakeDocker(SCENARIOS["propre"], clock=clock)
    real = server_module.copy_tree

    def slow_copy(*args: Any, **kwargs: Any) -> Any:
        clock.now += 5.0
        return real(*args, **kwargs)

    monkeypatch.setattr(server_module, "copy_tree", slow_copy)
    data(checks_with(allow_lists(example)["exemple"], docker, tmp_path))
    assert docker.calls[0].timeout_s == BUDGET_S - 5.0


def test_a_flooding_container_is_stopped(example: Path, tmp_path: Path) -> None:
    result, _ = scenario("inonde", example, tmp_path)
    assert result["ruff_check"]["status"] == "erreur"
    assert result["ruff_check"]["note"] == (
        f"sortie de plus de {MAX_OUTPUT_BYTES} octets : conteneur arrêté"
    )
    assert result["ruff_format"]["status"] == "ok"


# --- pytest -----------------------------------------------------------------------------------


def test_failed_tests_are_named(example: Path, tmp_path: Path) -> None:
    result, _ = scenario("violations", example, tmp_path)
    assert result["pytest"] == {
        "status": "echec",
        "note": None,
        "counts": {"failed": 1, "passed": 1},
        "failed": ["tests/test_app.py::test_main"],
        "errors": [],
        "more_failures": 0,
    }


def test_failures_past_the_limit_are_counted(example: Path, tmp_path: Path) -> None:
    lines = "".join(f"FAILED t.py::test_{i}\nERROR e.py::test_{i}\n" for i in range(MAX_SHOWN + 2))
    summary = f"{MAX_SHOWN + 2} failed, {MAX_SHOWN + 2} errors in 1.00s\n"
    replies = {"check": ruff(), "format": ruff(), "pytest": out(1, lines + summary)}
    result, _ = scenario(replies, example, tmp_path)
    assert len(result["pytest"]["failed"]) == len(result["pytest"]["errors"]) == MAX_SHOWN
    assert result["pytest"]["more_failures"] == 4


@pytest.mark.parametrize(
    ("name", "status", "note"),
    [
        ("sans_tests", "aucun_test", "aucun test collecté (code 5)"),
        ("collecte", "erreur", "pytest interrompu (code 2)"),
        ("sans_resume", "erreur", "résumé de pytest introuvable dans sa sortie"),
    ],
)
def test_pytest_outcomes(name: str, status: str, note: str, example: Path, tmp_path: Path) -> None:
    result, _ = scenario(name, example, tmp_path)
    assert result["pytest"]["status"] == status
    assert note in result["pytest"]["note"]


@pytest.mark.parametrize(
    ("code", "note"),
    [
        (3, "erreur interne de pytest (code 3)"),
        (4, "pytest mal appelé (code 4) : option ou configuration du dépôt"),
        (9, "code de sortie de pytest inattendu (9)"),
    ],
)
def test_other_pytest_codes_are_errors(code: int, note: str, example: Path, tmp_path: Path) -> None:
    replies = {"check": ruff(), "format": ruff(), "pytest": out(code, "1 error in 0.10s\n")}
    result, _ = scenario(replies, example, tmp_path)
    assert (result["pytest"]["status"], result["pytest"]["note"]) == ("erreur", note)
    assert result["pytest"]["counts"] == {"errors": 1}


def test_pytest_runs_only_when_asked_and_prepared(example: Path, tmp_path: Path) -> None:
    unasked, docker = scenario("propre", example, tmp_path, {"pytest": False})
    assert (unasked["pytest"]["status"], unasked["pytest"]["note"]) == ("non_lance", "non demandé")
    assert [call.step for call in docker.calls] == ["check", "format"]
    unprepared, docker = scenario("propre", example, tmp_path, allow="non_prepare")
    assert (unprepared["pytest"]["status"], unprepared["pytest"]["note"]) == (
        "non_lance",
        NOT_PREPARED,
    )
    assert [call.step for call in docker.calls] == ["check", "format"]
    no_image = [listed("exemple", example, pytest=True)]
    docker = FakeDocker(SCENARIOS["propre"])
    result = data(checks_with(no_image, docker, tmp_path))
    assert result["pytest"]["note"] == NOT_PREPARED


# --- refusals ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("allow", "arguments", "message"),
    [
        ("vide", {}, "la liste blanche des dépôts est vide"),
        ("exemple", {"repo": "inconnu"}, "« inconnu » non autorisé : liste blanche = exemple"),
        ("cerveau", {"repo": "cerveau"}, "recouvre le dépôt CERVEAU (ADR-047)"),
        ("exemple", {"rev": "v1..HEAD"}, "révision « v1..HEAD » refusée"),
        ("exemple", {"rev": "absente"}, "révision « absente » introuvable"),
        ("exemple", {"rev": "--all"}, "validation"),
        ("exemple", {"repo": "../projet"}, "validation"),
    ],
)
def test_refusals_run_no_container(
    allow: str, arguments: dict[str, Any], message: str, example: Path, tmp_path: Path
) -> None:
    docker = FakeDocker(SCENARIOS["propre"])
    result = checks_with(allow_lists(example)[allow], docker, tmp_path / "runs", arguments)
    assert result.is_error
    assert message in text(result)
    assert docker.calls == []
    assert not (tmp_path / "runs").exists()


def test_a_repository_too_big_is_not_copied(
    example: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_module, "MAX_COPY_FILES", 2)
    docker = FakeDocker(SCENARIOS["propre"])
    result = checks_with(allow_lists(example)["exemple"], docker, tmp_path / "runs")
    assert "dépôt trop gros pour les contrôles : 3 fichiers" in text(result)
    assert docker.calls == []
    assert not (tmp_path / "runs").exists()


def test_the_settings_are_read_at_each_call(example: Path, tmp_path: Path) -> None:
    def blocked() -> Settings:
        raise SandboxError("fonction bloquée « code.checks »")

    answers: list[Callable[[], Settings]] = [
        blocked,
        lambda: settings(allow_lists(example)["exemple"]),
    ]
    docker = FakeDocker(SCENARIOS["propre"])
    server = build_server(lambda: answers.pop(0)(), RepoReader(GitRunner()), docker, tmp_path)
    first = run(server, lambda c: c.call_tool("run_checks", {"repo": "exemple"}))
    assert "fonction bloquée « code.checks »" in text(first)
    second = run(server, lambda c: c.call_tool("run_checks", {"repo": "exemple"}))
    assert data(second)["ruff_check"]["status"] == "ok"


# --- configuration and entry point ------------------------------------------------------------


def test_the_checks_are_blocked_while_lucas_has_not_set_the_image() -> None:
    with pytest.raises(SandboxError, match=re.escape("fonction bloquée « code.checks »")):
        load_settings(REPO_ROOT / "config")


def test_an_invalid_configuration_is_reported_without_detail(tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="configuration invalide"):
        load_settings(tmp_path)


def test_the_settings_come_from_the_configuration(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    import shutil

    config = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", config)
    repo = tmp_path_factory.mktemp("projet")
    path = config / "code.yaml"
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["repositories"] = [{"id": "projet", "path": str(repo), "pytest": True, "image": IMAGE}]
    raw["checks"]["image"] = IMAGE
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    loaded = load_settings(config)
    assert [(entry.id, entry.pytest, entry.image) for entry in loaded.repositories] == [
        ("projet", True, IMAGE)
    ]
    assert (loaded.checks.image, loaded.checks.memory_mb) == (IMAGE, 2048)


def test_main_wires_the_configuration_docker_and_the_runs_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    built: list[Any] = []

    class Stub:
        def run(self) -> None:
            built.append("run")

    def fake_build(current: Any, reader: Any, runner: Any, runs: Any) -> Stub:
        built.extend([current, reader, runner, runs])
        return Stub()

    monkeypatch.setenv("CERVEAU_HOME", str(tmp_path))
    monkeypatch.setattr(server_module, "build_server", fake_build)
    calls: list[Path] = []
    monkeypatch.setattr(server_module, "load_settings", lambda d: calls.append(d) or "réglages")
    server_module.main()
    current, reader, runner, runs, ran = built
    assert current() == "réglages"
    assert calls == [tmp_path / "config"]
    assert isinstance(reader, RepoReader)
    assert reader.cerveau == REPO_ROOT.resolve()
    assert isinstance(runner, DockerRunner)
    assert runs == tmp_path / "var" / "code" / "runs"
    assert ran == "run"


# --- golden set -------------------------------------------------------------------------------


GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]


@pytest.mark.parametrize("case", GOLDEN, ids=[case["id"] for case in GOLDEN])
def test_golden_cases(case: dict[str, Any], example: Path, tmp_path: Path) -> None:
    """Offline: each case runs on the example repository, Docker answering as its scenario says."""
    docker = FakeDocker(SCENARIOS[case.get("scenario", "propre")])
    allow = allow_lists(example)[case.get("allowlist", "exemple")]
    result = checks_with(allow, docker, tmp_path / "runs", case["arguments"])
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
