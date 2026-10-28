"""The MCP server, called in process through the SDK client, with a fake Docker (support.py)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
import threading
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult

from core.code import agent
from core.code.agent_runner import MAX_PROMPT_CHARS
from core.code.git import GitRunner
from core.code.process import Bounded
from core.code.repos import RepoError, RepoReader
from core.code.sandbox import KILL_TIMEOUT_S, DockerRunner, SandboxError
from core.config.loader import AGENT_CEILINGS, CodeRepository, load_config
from core.mcp.spend import IsolatedTask, reported
from core.mcp.time_limit import TIME_LIMIT_META_KEY
from core.registry.manifest import validate_plugin
from plugins.code_agent import server as server_module
from plugins.code_agent.server import (
    AFTER_AGENT_S,
    ALARM_MARGIN_S,
    CALL_S,
    CHECKS_CHANGED,
    KILLED,
    LEFT_OUT,
    MASKED,
    MAX_OUTPUT_BYTES,
    MAX_STATE_BYTES,
    NETWORK_TRIES,
    NOT_RUN,
    NOT_STOPPED,
    PATCH_FILE,
    REPORT_FILE,
    RESERVE_S,
    STOPPED,
    UNWRITABLE,
    build_server,
    load_settings,
)
from plugins.code_agent.tests.support import (
    AGENT_IMAGE,
    BIDI,
    DAEMON_DOWN,
    GONE,
    KEY,
    MODEL,
    OK,
    PROXY_IMAGE,
    SCENARIOS_AGENT,
    STILL_THERE,
    TIMED_OUT,
    TOKENS,
    Call,
    FakeDocker,
    Scenario,
    fix_main,
    kind_of,
    mounted,
    settings,
    state,
)
from plugins.code_checks.server import DOCKER_CODES
from plugins.code_checks.tests.support import (
    ENV_VALUE,
    INJECTION,
    REPO_IMAGE,
    TOKEN,
    allow_lists,
    example_repo,
    out,
)
from tests.code_support import git
from tests.conftest import REPO_ROOT

PLUGIN = Path(__file__).resolve().parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
(SPEC,) = MANIFEST["tools"]
TASK = "Corrige main() et ajoute un test."
# The watcher then never reads the kill switch before the agent ends: the switch is read at
# known points only (before the start, once the proxy runs, after the agent, before the checks).
QUIET_S = 60.0
AGENT_S = CALL_S - RESERVE_S - AFTER_AGENT_S
STARTED = ["network", "outside", "proxy", "connect"]
STOPPED_KINDS = ["kill", "remove", "remove"]
# Once the agent ran: docker ps confirms both containers are gone.
ENDED = [*STOPPED_KINDS, "running"]
CHECKS = ["check", "format", "pytest"]
CLEAN = {"copy_removed": True, "network_removed": True, "containers_stopped": True}


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


@dataclass
class Unreachable:
    """Docker cannot be launched for these steps: ``DockerRunner`` raises ``SandboxError``."""

    docker: FakeDocker
    kinds: frozenset[str]

    def run(
        self, arguments: Sequence[str], *, name: str, timeout_s: float, max_bytes: int
    ) -> Bounded:
        if kind_of(arguments) in self.kinds:
            raise SandboxError("Docker ne peut pas être lancé (FileNotFoundError)")
        return self.docker.run(arguments, name=name, timeout_s=timeout_s, max_bytes=max_bytes)


@dataclass
class Done:
    result: CallToolResult
    docker: FakeDocker
    # var/code/agent of the test's home.
    folder: Path

    @property
    def data(self) -> dict[str, Any]:
        assert not self.result.is_error, text(self.result)
        assert self.result.structured_content is not None
        return self.result.structured_content

    @property
    def error(self) -> str:
        assert self.result.is_error
        return text(self.result)

    def calls(self, kind: str) -> list[Call]:
        return [call for call in self.docker.calls if call.kind == kind]

    def call(self, kind: str) -> Call:
        (found,) = self.calls(kind)
        return found

    def patch(self) -> bytes:
        return (self.folder / self.data["task_id"] / PATCH_FILE).read_bytes()

    def nothing_left(self) -> bool:
        """No copy under runs/ and no task folder: what a refusal leaves."""
        runs = self.folder / "runs"
        entries = [path.name for path in self.folder.iterdir()] if self.folder.exists() else []
        return entries in ([], ["runs"]) and not (runs.exists() and any(runs.iterdir()))


def agent_task(
    example: Path,
    home: Path,
    scenario: str | Scenario = "corrige",
    arguments: Mapping[str, Any] | None = None,
    *,
    repositories: Sequence[CodeRepository] | None = None,
    environ: Mapping[str, str] = KEY,
    engaged: Callable[[], bool] = lambda: False,
    wrap: Callable[[FakeDocker], Any] | None = None,
    meta: Any = None,
    watch_s: float = QUIET_S,
    **limits: Any,
) -> Done:
    docker = FakeDocker(SCENARIOS_AGENT[scenario] if isinstance(scenario, str) else scenario)
    allowed = allow_lists(example)["exemple"] if repositories is None else repositories
    current = settings(allowed, **limits)
    server = build_server(
        lambda: current,
        RepoReader(GitRunner()),
        docker if wrap is None else wrap(docker),
        docker.proxy,
        home,
        engaged,
        environ=environ,
        clock=docker.clock,
        sleep=docker.clock.sleep,
        watch_s=watch_s,
    )
    arguments = {"repo": "exemple", "task": TASK, **(arguments or {})}
    result = run(server, lambda c: c.call_tool("agent_task", arguments, meta=meta))
    return Done(result, docker, home / "var" / "code" / "agent")


def switch(*answers: bool) -> Callable[[], bool]:
    """The kill switch: one answer per read, the last one kept."""
    left = list(answers)
    return lambda: left.pop(0) if len(left) > 1 else left[0]


# --- the manifest -----------------------------------------------------------------------------


def test_the_plugin_passes_the_registry() -> None:
    report = validate_plugin(PLUGIN)
    assert report.ok, report.errors
    assert report.plugin_id == "code_agent"


def test_the_call_limit_is_f5s_and_the_key_is_passed_by_name() -> None:
    manifest = validate_plugin(PLUGIN).manifest
    assert manifest is not None and manifest.runtime is not None
    assert manifest.runtime.tool_timeout_s == CALL_S == AGENT_CEILINGS["timeout_seconds"]
    assert manifest.runtime.env == [agent.KEY_ENV]
    assert manifest.max_autonomy_level == "N0"
    assert RESERVE_S > 2 * KILL_TIMEOUT_S


def test_the_published_tool_matches_the_manifest(tmp_path: Path) -> None:
    docker = FakeDocker()
    server = build_server(
        lambda: settings([]), RepoReader(GitRunner()), docker, docker.proxy, tmp_path, lambda: False
    )
    (tool,) = run(server, lambda c: c.list_tools()).tools
    assert tool.name == SPEC["name"] == "agent_task"
    assert SPEC["action_class"] == "EXECUTION_ISOLEE"
    assert tool.description == SPEC["description"]
    assert tool.annotations.model_dump(by_alias=True, exclude_none=True) == SPEC["annotations"]
    for kind, schema in (
        ("input_schema", tool.input_schema),
        ("output_schema", tool.output_schema),
    ):
        on_disk = json.loads((PLUGIN / SPEC[kind]).read_text(encoding="utf-8"))
        on_disk.pop("$schema")
        assert schema == on_disk, f"{SPEC[kind]} is stale: regenerate it from the server"
    assert tool.input_schema["properties"]["task"]["maxLength"] == MAX_PROMPT_CHARS


# --- a task, from the copy to the checks ------------------------------------------------------


def test_a_task_runs_the_agent_and_returns_its_patch(example: Path, tmp_path: Path) -> None:
    done = agent_task(example, tmp_path)
    data, docker = done.data, done.docker
    task = agent.names(data["task_id"])
    assert (data["repo"], data["rev"], len(data["sha"]), data["model"]) == (
        "exemple",
        "HEAD",
        40,
        MODEL,
    )
    assert docker.kinds() == [*STARTED, "agent", *ENDED, *CHECKS]
    # Only the proxy's `docker run` goes through the runner whose environment holds the key.
    assert [call.via for call in docker.calls] == ["docker", "docker", "proxy", *["docker"] * 9]
    assert done.call("outside").arguments == agent.outside_create(task.outside)
    proxy = done.call("proxy").arguments
    assert proxy[proxy.index("--env") + 1] == agent.KEY_ENV
    assert proxy[proxy.index("--network") + 1] == task.network
    assert PROXY_IMAGE in proxy
    # The proxy stops by itself at the kill switch and once the call's time is over (R4).
    assert mounted(proxy, "/kill_switch") == tmp_path / "governance" / "kill_switch"
    assert proxy[proxy.index("--kill-switch") + 1] == "/kill_switch/KILL"
    assert int(proxy[proxy.index("--max-seconds") + 1]) == CALL_S - RESERVE_S
    assert done.call("connect").arguments == agent.network_connect(task.outside, task.proxy)
    run_agent = done.call("agent")
    assert run_agent.arguments[run_agent.arguments.index("--network") + 1] == task.network
    assert AGENT_IMAGE in run_agent.arguments
    assert agent.KEY_ENV not in " ".join(run_agent.arguments)
    assert (run_agent.timeout_s, run_agent.max_bytes) == (AGENT_S, MAX_OUTPUT_BYTES)
    assert run_agent.arguments[-2:] == ["--max-seconds", str(int(AGENT_S) + ALARM_MARGIN_S)]
    assert done.call("kill").arguments == agent.kill(task.agent, task.proxy)
    assert [call.arguments for call in done.calls("remove")] == [
        agent.network_remove(task.network),
        agent.network_remove(task.outside),
    ]
    assert done.call("running").arguments == agent.running(task)
    for call in docker.calls:
        assert KEY[agent.KEY_ENV] not in " ".join(call.arguments)
    # What the containers saw: the commit's files without the sensitive ones; the task; the
    # proxy's settings for the task's model alone.
    assert docker.seen["before"] == ["README.md", "src/app.py", "tests/test_app.py"]
    assert docker.seen["task"] == agent.task_document(TASK, MODEL, 30, Decimal(2))
    assert list(docker.seen["settings"]["models"]) == [MODEL]
    assert (docker.seen["settings"]["max_usd"], docker.seen["settings"]["max_requests"]) == (
        "2",
        200,
    )
    work = mounted(run_agent.arguments, "/work")
    assert work == done.folder / "runs" / data["task_id"] / "work"
    assert "tests/test_more.py" in done.call("check").files
    assert mounted(done.call("check").arguments, "/work") == work
    assert not work.parent.exists()
    # The runner's line, the proxy's counts.
    assert data["agent"] == {
        "status": "termine",
        "note": None,
        "subtype": "success",
        "turns": 4,
        "summary": "main() corrigé ; un test ajouté.",
        "seconds": AGENT_S,
    }
    assert data["proxy"] == {"requests": 3, "usd": "0.025000", "stopped": None, "refusals": {}}
    assert data["depense"] == {"modeles": {MODEL: TOKENS}, "cout_inconnu": False}
    assert reported(IsolatedTask(MODEL, Decimal(2)), data) is not None
    # The patch, written for Lucas, who applies it himself.
    patch = data["patch"]
    on_disk = done.patch()
    assert patch["folder"] == f"var/code/agent/{data['task_id']}"
    assert (patch["sha256"], patch["bytes"]) == (hashlib.sha256(on_disk).hexdigest(), len(on_disk))
    assert [(f["path"], f["change"], f["added"], f["removed"]) for f in patch["files"]] == [
        ("src/app.py", "modifie", 1, 4),
        ("tests/test_more.py", "ajoute", 5, 0),
    ]
    assert (patch["applies"], patch["masked"], patch["risky"], patch["more_files"]) == (
        True,
        0,
        [],
        0,
    )
    assert "+    return 2\n" in on_disk.decode("utf-8")
    git(example, "apply", "--check", str(done.folder / data["task_id"] / PATCH_FILE))
    # The checks of the changed copy: their counts are the ones to cite (R1).
    assert data["checks"]["ruff_check"]["status"] == "ok"
    assert data["checks"]["pytest"]["status"] == "ok"
    assert data["checks"]["budget_seconds"] == 300
    assert (data["checks"]["conclusive"], data["checks"]["caveats"]) == (True, [])
    assert (data["patch_note"], data["checks_note"]) == (None, None)
    assert data["source"]["withheld"] == [".env"]
    assert data["source"]["removed"] is True
    assert data["cleanup"] == CLEAN
    report = json.loads((done.folder / data["task_id"] / REPORT_FILE).read_text(encoding="utf-8"))
    assert report == data


def test_a_leaked_secret_is_masked_and_the_patch_no_longer_applies(
    example: Path, tmp_path: Path
) -> None:
    done = agent_task(example, tmp_path, "secret")
    patch = done.data["patch"]
    assert patch["masked"] >= 1 and patch["applies"] is False
    assert [f["masked"] >= 1 for f in patch["files"]] == [True]
    assert TOKEN not in done.patch().decode("utf-8")
    report = (done.folder / done.data["task_id"] / REPORT_FILE).read_text(encoding="utf-8")
    assert TOKEN not in json.dumps(done.data) + report


def test_files_that_run_code_on_lucass_machine_are_flagged(example: Path, tmp_path: Path) -> None:
    patch = agent_task(example, tmp_path, "risque").data["patch"]
    assert patch["risky"] == [".github/workflows/ci.yml", "conftest.py"]
    assert all(f["risky"] for f in patch["files"])


@pytest.mark.parametrize(
    ("name", "caveats"),
    [
        ("corrige", []),
        ("risque", [CHECKS_CHANGED]),
        ("ecartes", [LEFT_OUT]),
        ("secret", [MASKED]),
    ],
)
def test_checks_that_prove_nothing_say_so(
    name: str, caveats: list[str], example: Path, tmp_path: Path
) -> None:
    """The agent's conftest.py runs in the checks; a copy unlike the patch is not the patch."""
    checks = agent_task(example, tmp_path, name).data["checks"]
    assert (checks["conclusive"], checks["caveats"]) == (not caveats, caveats)


def test_what_the_patch_leaves_out_is_listed(example: Path, tmp_path: Path) -> None:
    done = agent_task(example, tmp_path, "ecartes")
    patch = done.data["patch"]
    assert [(f["path"], f["change"]) for f in patch["files"]] == [("README.md", "modifie")]
    assert patch["sensitive"] == [".env"]
    assert patch["binary"] == ["src/data.bin"]
    assert patch["ignored"] == ["src/a⟨U+202E⟩pp.py"]
    assert (patch["too_big"], patch["more_left_out"]) == ([], 0)
    shown = json.dumps(done.data, ensure_ascii=False) + done.patch().decode("utf-8")
    for absent in ("CREEE-PAR-L-AGENT", ENV_VALUE, BIDI):
        assert absent not in shown


def test_a_deleted_file_is_in_the_patch(example: Path, tmp_path: Path) -> None:
    done = agent_task(example, tmp_path, "suppression")
    files = done.data["patch"]["files"]
    assert [(f["path"], f["change"], f["added"], f["removed"]) for f in files] == [
        ("README.md", "supprime", 0, 1)
    ]
    git(example, "apply", "--check", str(done.folder / done.data["task_id"] / PATCH_FILE))


def test_no_change_runs_no_check(example: Path, tmp_path: Path) -> None:
    done = agent_task(example, tmp_path, "rien")
    data = done.data
    assert (data["patch"]["files"], data["patch"]["bytes"], data["checks"]) == ([], 0, None)
    assert data["checks_note"] == "l'agent n'a changé aucun fichier : contrôles non lancés"
    assert done.docker.kinds() == [*STARTED, "agent", *ENDED]


def test_the_agents_words_are_data(example: Path, tmp_path: Path) -> None:
    """R5: the summary is shown, bounded, its secrets masked and invisible characters shown."""
    data = agent_task(example, tmp_path, "injection").data
    assert INJECTION in data["agent"]["summary"]
    assert "⟨U+202E⟩" in data["agent"]["summary"]
    assert data["agent"]["subtype"] == INJECTION
    shown = json.dumps(data, ensure_ascii=False)
    assert TOKEN not in shown and BIDI not in shown


@pytest.mark.parametrize(
    ("name", "status", "note", "patched"),
    [
        ("echec_agent", "erreur", "runner : arret_sur_erreur", True),
        (
            "inonde",
            "erreur",
            f"sortie de l'agent de plus de {MAX_OUTPUT_BYTES} octets : conteneurs arrêtés",
            False,
        ),
        ("agent_absent", "erreur", DOCKER_CODES[125], False),
        ("ligne_illisible", "erreur", "compte rendu du runner illisible (code 0)", True),
        ("incoherent", "erreur", "compte rendu du runner et code de sortie (1) incohérents", True),
        ("lent", "delai", f"délai de {AGENT_S:.0f} s dépassé : conteneurs arrêtés", False),
    ],
)
def test_how_the_agent_ended(
    name: str, status: str, note: str, patched: bool, example: Path, tmp_path: Path
) -> None:
    """A patch only once the container ended by itself; its copy is never compared otherwise."""
    done = agent_task(example, tmp_path, name)
    data = done.data
    assert (data["agent"]["status"], data["agent"]["note"]) == (status, note)
    assert (data["patch"] is not None, data["checks"] is not None) == (patched, patched)
    if not patched:
        assert data["patch_note"] == NOT_RUN
        assert data["checks_note"] == "aucun patch : contrôles non lancés"
        assert done.docker.kinds() == [*STARTED, "agent", *ENDED]
    assert data["depense"] == {"modeles": {MODEL: TOKENS}, "cout_inconnu": False}
    assert data["cleanup"] == CLEAN


def test_the_runners_report_is_kept_when_it_disagrees_with_the_exit_code(
    example: Path, tmp_path: Path
) -> None:
    run_ = agent_task(example, tmp_path, "incoherent").data["agent"]
    assert (run_["turns"], run_["subtype"]) == (4, "success")
    failed = agent_task(example, tmp_path, "echec_agent").data["agent"]
    assert (failed["turns"], failed["subtype"], failed["summary"]) == (
        30,
        "error_max_turns",
        "main() corrigé ; un test ajouté.",
    )


@pytest.mark.parametrize(
    ("name", "proxy", "spend"),
    [
        (
            "plafond",
            {
                "requests": 41,
                "usd": "2.004000",
                "stopped": "plafond_usd",
                "refusals": {"plafond_usd": 2},
            },
            {"modeles": {MODEL: TOKENS}, "cout_inconnu": False},
        ),
        (
            "cout_inconnu",
            {"requests": 3, "usd": "0.025000", "stopped": None, "refusals": {}},
            {"modeles": {MODEL: TOKENS}, "cout_inconnu": True},
        ),
        ("etat_illisible", None, None),
        ("autre_modele", None, None),
    ],
)
def test_the_spend_is_the_proxys_count(
    name: str,
    proxy: dict[str, Any] | None,
    spend: dict[str, Any] | None,
    example: Path,
    tmp_path: Path,
) -> None:
    """Without counts the proxy wrote, ``depense`` is null and the adapter charges the ceiling."""
    data = agent_task(example, tmp_path, name).data
    assert (data["proxy"], data["depense"]) == (proxy, spend)
    assert (reported(IsolatedTask(MODEL, Decimal(2)), data) is None) is (spend is None)


def test_the_state_file_is_read_within_bounds(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    assert server_module._read_state(path, MODEL) is None
    path.write_bytes(b"\xff")
    assert server_module._read_state(path, MODEL) is None
    path.write_text(json.dumps(state()) + " " * MAX_STATE_BYTES, encoding="utf-8")
    assert server_module._read_state(path, MODEL) is None
    path.write_text(json.dumps(state()), encoding="utf-8")
    read = server_module._read_state(path, MODEL)
    assert read is not None and read.requests == 3


# --- the kill switch (R4) ---------------------------------------------------------------------


def test_the_kill_switch_stops_both_containers_while_the_agent_works(
    example: Path, tmp_path: Path
) -> None:
    engaged = threading.Event()

    def edit(work: Path) -> None:
        fix_main(work)
        engaged.set()

    scenario = Scenario(edit=edit, until_killed=True)
    done = agent_task(example, tmp_path, scenario, engaged=engaged.is_set, watch_s=0.01)
    data = done.data
    task = agent.names(data["task_id"])
    # The watcher's kill is recorded before the agent's run, which it ends.
    assert done.docker.kinds() == [*STARTED, "kill", "agent", *ENDED]
    assert done.docker.calls[4].arguments == agent.kill(task.agent, task.proxy)
    assert (data["agent"]["status"], data["agent"]["note"]) == ("arrete", STOPPED)
    assert (data["agent"]["turns"], data["agent"]["summary"]) == (None, None)
    assert (data["patch"], data["patch_note"], data["checks"]) == (None, NOT_RUN, None)
    assert data["depense"] == {"modeles": {MODEL: TOKENS}, "cout_inconnu": False}
    assert data["cleanup"] == CLEAN


def test_the_kill_switch_engaged_as_the_agent_ends_computes_no_patch(
    example: Path, tmp_path: Path
) -> None:
    data = agent_task(example, tmp_path, engaged=switch(False, False, True)).data
    assert (data["agent"]["status"], data["agent"]["note"]) == ("arrete", STOPPED)
    assert (data["patch"], data["patch_note"], data["checks"]) == (None, NOT_RUN, None)


def test_a_copy_past_its_bounds_stops_both_containers(
    example: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F5: the copy is watched while the agent writes in it."""
    monkeypatch.setattr(server_module, "MAX_WORK_ENTRIES", 1)
    done = agent_task(example, tmp_path, Scenario(until_killed=True), watch_s=0.01)
    data = done.data
    task = agent.names(data["task_id"])
    assert done.docker.kinds() == [*STARTED, "kill", "agent", *ENDED]
    assert done.docker.calls[4].arguments == agent.kill(task.agent, task.proxy)
    assert data["agent"]["status"] == "erreur"
    assert data["agent"]["note"] == (
        f"copie au-delà de ses bornes (1 entrées, {server_module.MAX_WORK_BYTES} octets) "
        "pendant le travail de l'agent : conteneurs arrêtés"
    )
    assert (data["patch"], data["patch_note"], data["checks"]) == (None, NOT_RUN, None)
    # Both containers seen gone: the proxy's counts are final.
    assert data["depense"] == {"modeles": {MODEL: TOKENS}, "cout_inconnu": False}


@dataclass
class HeldCheck:
    """The first check runs until its container is killed; the kill switch is engaged meanwhile."""

    docker: FakeDocker
    engaged: threading.Event
    killed: threading.Event

    def run(
        self, arguments: Sequence[str], *, name: str, timeout_s: float, max_bytes: int
    ) -> Bounded:
        kind = kind_of(arguments)
        if kind == "kill" and self.engaged.is_set():
            self.killed.set()
        if kind == "check":
            self.engaged.set()
            assert self.killed.wait(10), "the check's container was never killed"
        return self.docker.run(arguments, name=name, timeout_s=timeout_s, max_bytes=max_bytes)


def test_the_kill_switch_stops_a_running_check(example: Path, tmp_path: Path) -> None:
    engaged, killed = threading.Event(), threading.Event()
    done = agent_task(
        example,
        tmp_path,
        engaged=engaged.is_set,
        wrap=lambda docker: HeldCheck(docker, engaged, killed),
        watch_s=0.01,
    )
    data = done.data
    assert done.docker.kinds() == [*STARTED, "agent", *ENDED, "kill", "check"]
    assert done.docker.calls[-2].arguments == agent.kill(done.call("check").name)
    assert data["patch"] is not None
    assert (data["checks"], data["checks_note"]) == (None, STOPPED)


def test_the_kill_switch_engaged_between_two_checks_starts_no_more(
    example: Path, tmp_path: Path
) -> None:
    # Read before the start, once the proxy runs, after the agent, before and between the checks.
    done = agent_task(example, tmp_path, engaged=switch(False, False, False, False, False, True))
    assert done.docker.kinds() == [*STARTED, "agent", *ENDED, "check"]
    assert (done.data["checks"], done.data["checks_note"]) == (None, STOPPED)


def test_an_engaged_kill_switch_starts_nothing(example: Path, tmp_path: Path) -> None:
    done = agent_task(example, tmp_path, engaged=lambda: True)
    assert KILLED in done.error
    assert done.docker.calls == []
    assert not done.folder.exists()


def test_the_kill_switch_engaged_while_the_proxy_starts(example: Path, tmp_path: Path) -> None:
    done = agent_task(example, tmp_path, engaged=switch(False, True))
    assert KILLED in done.error
    assert done.docker.kinds() == [*STARTED, *STOPPED_KINDS]
    assert done.nothing_left()


def test_the_kill_switch_engaged_after_the_agent_skips_the_checks(
    example: Path, tmp_path: Path
) -> None:
    done = agent_task(example, tmp_path, engaged=switch(False, False, False, True))
    data = done.data
    assert data["agent"]["status"] == "termine"
    assert data["patch"] is not None
    assert (data["checks"], data["checks_note"]) == (None, STOPPED)
    assert done.docker.kinds() == [*STARTED, "agent", *ENDED]


# --- Docker failing ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scenario", "message", "kinds"),
    [
        (
            "moteur_arrete",
            f"Docker : réseau de la tâche impossible ({DOCKER_CODES[125]})",
            ["network", "remove"],
        ),
        (
            Scenario(replies={"network": TIMED_OUT}),
            "Docker : réseau de la tâche, sans réponse en 20 s",
            ["network", "remove"],
        ),
        (
            Scenario(replies={"outside": DAEMON_DOWN}),
            f"Docker : réseau de sortie du proxy impossible ({DOCKER_CODES[125]})",
            ["network", "outside", "remove", "remove"],
        ),
        (
            "proxy_absent",
            "Docker : démarrage du proxy impossible (",
            ["network", "outside", "proxy", *STOPPED_KINDS],
        ),
        ("proxy_muet", "le proxy n'a pas démarré en 15 s", [*STARTED, *STOPPED_KINDS]),
        (
            Scenario(replies={"connect": TIMED_OUT}),
            "Docker : sortie du proxy vers l'API, sans réponse en 20 s",
            [*STARTED, *STOPPED_KINDS],
        ),
    ],
)
def test_a_failed_start_stops_what_started(
    scenario: str | Scenario, message: str, kinds: list[str], example: Path, tmp_path: Path
) -> None:
    done = agent_task(example, tmp_path, scenario)
    assert message in done.error
    assert done.docker.kinds() == kinds
    assert done.nothing_left()


def test_the_network_is_removed_once_the_containers_are_gone(example: Path, tmp_path: Path) -> None:
    busy = out(1, stderr="error while removing network: has active endpoints")
    done = agent_task(example, tmp_path, Scenario(replies={"remove": [busy, OK]}))
    assert done.docker.kinds().count("remove") == 3
    assert done.data["cleanup"]["network_removed"] is True


@pytest.mark.parametrize(
    ("replies", "count"),
    [
        (out(1, stderr="has active endpoints"), 2 * NETWORK_TRIES),
        (TIMED_OUT, 2 * NETWORK_TRIES),
        # The task's network goes, the way out stays: both are tried all the same.
        ([OK, out(1, stderr="has active endpoints")], 1 + NETWORK_TRIES),
    ],
)
def test_a_network_that_stays_is_reported(
    replies: Bounded | list[Bounded], count: int, example: Path, tmp_path: Path
) -> None:
    done = agent_task(example, tmp_path, Scenario(replies={"remove": replies}))
    removed = [call.arguments[-1] for call in done.calls("remove")]
    task = agent.names(done.data["task_id"])
    assert len(removed) == count
    assert set(removed) == {task.network, task.outside}
    assert done.data["cleanup"]["network_removed"] is False


def test_docker_that_cannot_be_launched_after_the_agent(example: Path, tmp_path: Path) -> None:
    done = agent_task(
        example,
        tmp_path,
        wrap=lambda docker: Unreachable(docker, frozenset({"kill", "remove", "check"})),
    )
    data = done.data
    assert done.docker.kinds() == [*STARTED, "agent", "running"]
    assert data["cleanup"] == {**CLEAN, "network_removed": False}
    assert data["checks"] is None
    assert data["checks_note"] == "Docker ne peut pas être lancé (FileNotFoundError)"
    assert data["patch"] is not None


@pytest.mark.parametrize("reply", [STILL_THERE, TIMED_OUT, out(1, stderr="ps")])
def test_containers_still_running_leave_no_patch(
    reply: Bounded, example: Path, tmp_path: Path
) -> None:
    """Until ``docker ps`` shows both gone, the copy and the proxy's counts may still change."""
    done = agent_task(example, tmp_path, Scenario(replies={"running": reply}))
    data = done.data
    assert done.docker.kinds() == [*STARTED, "agent", *STOPPED_KINDS, *["running"] * NETWORK_TRIES]
    assert data["agent"]["status"] == "termine"
    assert (data["patch"], data["patch_note"], data["checks"]) == (None, NOT_STOPPED, None)
    # Unknown spend: the adapter charges the ceiling (core/mcp/spend.py).
    assert (data["proxy"], data["depense"]) == (None, None)
    assert data["cleanup"] == {**CLEAN, "containers_stopped": False}


def test_containers_seen_gone_at_last_are_stopped(example: Path, tmp_path: Path) -> None:
    done = agent_task(example, tmp_path, Scenario(replies={"running": [STILL_THERE, GONE]}))
    assert done.docker.kinds() == [*STARTED, "agent", *ENDED, "running", *CHECKS]
    assert done.data["cleanup"] == CLEAN
    assert done.data["patch"] is not None


def test_docker_ps_that_cannot_be_launched_leaves_no_patch(example: Path, tmp_path: Path) -> None:
    done = agent_task(
        example, tmp_path, wrap=lambda docker: Unreachable(docker, frozenset({"running"}))
    )
    assert done.data["patch_note"] == NOT_STOPPED
    assert done.data["cleanup"]["containers_stopped"] is False


def test_checks_that_fail_to_run_are_reported(example: Path, tmp_path: Path) -> None:
    checks = agent_task(example, tmp_path, "controles_en_panne").data["checks"]
    assert (checks["ruff_check"]["status"], checks["ruff_check"]["note"]) == (
        "erreur",
        DOCKER_CODES[125],
    )


# --- time -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("limit", "limits", "seconds"),
    [
        (None, {}, AGENT_S),
        (600, {}, 600 - RESERVE_S - AFTER_AGENT_S),
        (None, {"timeout_seconds": 300}, 300),
    ],
)
def test_the_agent_gets_the_time_left_after_the_reserve(
    limit: float | None,
    limits: dict[str, Any],
    seconds: float,
    example: Path,
    tmp_path: Path,
) -> None:
    meta = None if limit is None else {TIME_LIMIT_META_KEY: limit}
    done = agent_task(example, tmp_path, meta=meta, **limits)
    assert done.call("agent").timeout_s == seconds == done.data["agent"]["seconds"]


@pytest.mark.parametrize(("limit", "shown"), [(200, "50 s"), (100, "0 s")])
def test_too_little_time_starts_no_agent(
    limit: float, shown: str, example: Path, tmp_path: Path
) -> None:
    done = agent_task(example, tmp_path, meta={TIME_LIMIT_META_KEY: limit})
    assert f"temps restant trop court pour l'agent : {shown} (minimum 60 s" in done.error
    assert done.docker.kinds() == [*STARTED, *STOPPED_KINDS]
    assert done.nothing_left()


def test_the_checks_share_what_the_agent_left(example: Path, tmp_path: Path) -> None:
    done = agent_task(example, tmp_path, Scenario(takes=700.0))
    assert done.data["checks"]["budget_seconds"] == CALL_S - RESERVE_S - 700


# --- refusals ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("arguments", "environ", "message"),
    [
        ({}, {}, "variable ANTHROPIC_API_KEY absente"),
        ({}, {agent.KEY_ENV: ""}, "variable ANTHROPIC_API_KEY absente"),
        ({"repo": "inconnu"}, KEY, "« inconnu » non autorisé : liste blanche = exemple"),
        ({"rev": "absente"}, KEY, "révision « absente » introuvable"),
        ({"rev": "--all"}, KEY, "validation"),
        ({"task": ""}, KEY, "validation"),
        ({"task": "x" * (MAX_PROMPT_CHARS + 1)}, KEY, "validation"),
    ],
)
def test_refusals_start_no_container(
    arguments: dict[str, Any],
    environ: dict[str, str],
    message: str,
    example: Path,
    tmp_path: Path,
) -> None:
    done = agent_task(example, tmp_path, arguments=arguments, environ=environ)
    assert message in done.error
    assert done.docker.calls == []
    assert not done.folder.exists()


def test_a_repository_too_big_is_not_copied(
    example: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_module, "MAX_COPY_FILES", 2)
    done = agent_task(example, tmp_path)
    assert "dépôt trop gros pour les contrôles : 3 fichiers" in done.error
    assert done.docker.calls == []
    assert done.nothing_left()


class FixedId:
    hex = "0123456789ab" + "0" * 20


@pytest.mark.parametrize("taken", ["task", "config", "state"])
def test_task_files_that_cannot_be_written(
    taken: str, example: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_module.uuid, "uuid4", FixedId)
    run_folder = tmp_path / "var" / "code" / "agent" / "runs" / FixedId.hex[:12]
    run_folder.mkdir(parents=True)
    (run_folder / taken).write_text("un fichier à la place du dossier", encoding="utf-8")
    done = agent_task(example, tmp_path)
    assert UNWRITABLE in done.error
    assert done.docker.calls == []
    assert done.nothing_left()


# --- the patch --------------------------------------------------------------------------------


def _raise(error: Exception) -> Callable[..., Any]:
    def fail(*_: Any, **__: Any) -> Any:
        raise error

    return fail


@pytest.mark.parametrize(
    ("name", "replacement", "note"),
    [
        ("MAX_SCAN_ENTRIES", 2, "copie de plus de 2 entrées après l'agent : patch non calculé"),
        ("compute_patch", _raise(OSError("disque")), "copie illisible après l'agent"),
        ("_base", _raise(RepoError("objet git illisible")), "objet git illisible"),
    ],
)
def test_a_patch_that_cannot_be_computed(
    name: str,
    replacement: Any,
    note: str,
    example: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_module, name, replacement)
    data = agent_task(example, tmp_path).data
    assert data["patch"] is None and note in data["patch_note"]
    assert (data["checks"], data["checks_note"]) == (None, "aucun patch : contrôles non lancés")


def test_a_patch_that_cannot_be_written(
    example: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_module.uuid, "uuid4", FixedId)
    folder = tmp_path / "var" / "code" / "agent"
    folder.mkdir(parents=True)
    (folder / FixedId.hex[:12]).write_text("occupé", encoding="utf-8")
    data = agent_task(example, tmp_path).data
    assert data["patch"] is None
    assert data["patch_note"] == f"patch impossible à écrire sous var/code/agent/{FixedId.hex[:12]}"


# --- cleaning up the copy ---------------------------------------------------------------------


def test_a_read_only_copy_is_removed(tmp_path: Path) -> None:
    folder = tmp_path / "copie"
    (folder / "src").mkdir(parents=True)
    file = folder / "src" / "app.py"
    file.write_text("x = 1\n", encoding="utf-8")
    file.chmod(stat.S_IREAD)
    (folder / "src").chmod(stat.S_IREAD | stat.S_IEXEC)
    assert server_module._remove(folder)
    assert not folder.exists()


def test_only_a_failed_removal_is_tried_again(tmp_path: Path) -> None:
    error = PermissionError("refusé")
    with pytest.raises(PermissionError):
        server_module._unlocked(os.scandir, str(tmp_path), error)


@pytest.mark.parametrize("check", ["islink", "isjunction"])
def test_a_link_is_never_unlocked(
    check: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "cible"
    file.write_text("x", encoding="utf-8")
    file.chmod(stat.S_IREAD)
    monkeypatch.setattr(os.path, check, lambda _: True)
    with pytest.raises(PermissionError):
        server_module._unlocked(os.unlink, str(file), PermissionError("refusé"))
    assert file.exists() and not os.access(file, os.W_OK)
    file.chmod(stat.S_IRWXU)


def test_a_copy_left_behind_is_reported(
    example: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_module.shutil, "rmtree", _raise(OSError("occupé")))
    data = agent_task(example, tmp_path).data
    assert data["cleanup"]["copy_removed"] is False
    assert data["source"]["removed"] is False
    monkeypatch.undo()
    shutil.rmtree(tmp_path / "var")


def test_unwritable_helpers_say_so(tmp_path: Path) -> None:
    taken = tmp_path / "fichier"
    taken.write_text("x", encoding="utf-8")
    with pytest.raises(SandboxError, match=re.escape(UNWRITABLE)):
        server_module._make_dir(taken / "dossier")
    with pytest.raises(SandboxError, match=re.escape(UNWRITABLE)):
        server_module._write_json(taken / "dossier" / "x.json", {})


# --- configuration and entry point ------------------------------------------------------------


def test_the_agent_is_blocked_while_lucas_has_not_set_it() -> None:
    with pytest.raises(SandboxError, match=re.escape("fonction bloquée « code.agent »")):
        load_settings(REPO_ROOT / "config")


def test_an_invalid_configuration_is_reported_without_detail(tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="configuration invalide"):
        load_settings(tmp_path)


def test_the_settings_come_from_the_configuration(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    config = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", config)
    repo = tmp_path_factory.mktemp("projet")
    path = config / "code.yaml"
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["repositories"] = [{"id": "projet", "path": str(repo), "pytest": True, "image": REPO_IMAGE}]
    raw["checks"]["image"] = REPO_IMAGE
    raw["agent"].update(image=AGENT_IMAGE, proxy_image=PROXY_IMAGE, max_requests=200)
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    budgets = config / "budgets.yaml"
    data: dict[str, Any] = yaml.safe_load(budgets.read_text(encoding="utf-8"))
    data["llm_budget_eur"] = {"daily": "1.00", "monthly": "10.00"}
    data["per_code_agent"] = {"max_tokens": 1_000_000, "max_seconds": 900, "max_tool_calls": 1}
    budgets.write_text(yaml.safe_dump(data), encoding="utf-8")
    loaded = load_settings(config)
    assert [entry.id for entry in loaded.repositories] == ["projet"]
    assert (loaded.agent.image, loaded.agent.proxy_image) == (AGENT_IMAGE, PROXY_IMAGE)
    assert (loaded.agent.model, loaded.max_requests) == (MODEL, 200)
    assert loaded.pricing == load_config(config).pricing.anthropic.models[MODEL]
    assert loaded.checks.image == REPO_IMAGE


def test_main_wires_the_configuration_both_dockers_and_the_kill_switch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    built: list[Any] = []

    class Stub:
        def run(self) -> None:
            built.append("run")

    def fake_build(*arguments: Any) -> Stub:
        built.extend(arguments)
        return Stub()

    monkeypatch.setenv("CERVEAU_HOME", str(tmp_path))
    monkeypatch.setenv(agent.KEY_ENV, KEY[agent.KEY_ENV])
    monkeypatch.setattr(server_module, "build_server", fake_build)
    calls: list[Path] = []
    monkeypatch.setattr(server_module, "load_settings", lambda d: calls.append(d) or "réglages")
    server_module.main()
    current, reader, docker, proxy_docker, home, engaged, ran = built
    assert current() == "réglages"
    assert calls == [tmp_path / "config"]
    assert isinstance(reader, RepoReader)
    assert reader.cerveau == REPO_ROOT.resolve()
    assert isinstance(docker, DockerRunner) and agent.KEY_ENV not in docker.env
    assert isinstance(proxy_docker, DockerRunner)
    assert proxy_docker.env[agent.KEY_ENV] == KEY[agent.KEY_ENV]
    assert home == tmp_path
    assert engaged() is False
    (tmp_path / "governance" / "kill_switch").mkdir(parents=True)
    (tmp_path / "governance" / "kill_switch" / "KILL").write_text("", encoding="utf-8")
    assert engaged() is True
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
    done = agent_task(example, tmp_path, case.get("scenario", "corrige"), case["arguments"])
    expected = case["expected"]
    assert done.result.is_error is expected["is_error"]
    shown = done.error if done.result.is_error else json.dumps(done.data, ensure_ascii=False)
    assert expected["contains"] in shown
    for absent in expected.get("absent", []):
        assert absent not in shown


def test_the_golden_set_never_shows_the_example_secrets() -> None:
    raw = (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8")
    assert TOKEN not in raw
    assert ENV_VALUE in raw  # named only in "absent"
