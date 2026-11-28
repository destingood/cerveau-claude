"""The check sandbox (ADR-048): the docker command, its environment, its runner, the copy plan."""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

import core.code.sandbox as sandbox
from core.code.git import GitRunner
from core.code.process import Bounded
from core.code.repos import RepoReader, Repository, TreeItem
from core.code.sandbox import (
    CONTAINER_USER,
    KILL_TIMEOUT_S,
    LABEL,
    PROXY_VARIABLES,
    STALE_AFTER_S,
    TMPFS,
    DockerRunner,
    Limits,
    SandboxError,
    container_seconds,
    copy_tree,
    docker_command,
    docker_environment,
    leftover_command,
    leftovers,
    overdue,
    plan_copy,
    portable,
    private_folder,
)
from tests.code_support import add_entry, blob, git, listed, make_repo

LIMITS = Limits(cpus=2, memory_mb=2048, pids=256)
SHA = "a" * 40
ENDS_BY = 1_764_300_000


def option(command: list[str], name: str) -> list[str]:
    """Every value given to ``name``."""
    return [command[index + 1] for index, value in enumerate(command) if value == name]


def build(source: Path = Path("/var/runs/1"), **kwargs: object) -> list[str]:
    arguments = {
        "name": "cerveau-check-1",
        "image": f"sha256:{'b' * 64}",
        "source": source,
        "limits": LIMITS,
        "program": "ruff",
        "arguments": ["check", "--no-cache", "--output-format=json", "."],
        "max_seconds": 27,
        "ends_by": ENDS_BY,
        **kwargs,
    }
    return docker_command(**arguments)  # type: ignore[arg-type]


def test_the_container_has_no_network_and_a_read_only_root() -> None:
    command = build()
    assert command[:4] == ["run", "--rm", "--name", "cerveau-check-1"]
    assert option(command, "--network") == ["none"]
    assert "--read-only" in command
    assert option(command, "--tmpfs") == [TMPFS]
    assert "noexec" in TMPFS
    assert "nosuid" in TMPFS


def test_the_image_is_never_pulled() -> None:
    assert option(build(), "--pull") == ["never"]


def test_the_process_has_no_privilege() -> None:
    command = build()
    assert option(command, "--user") == [CONTAINER_USER]
    assert CONTAINER_USER == "65534:65534"
    assert option(command, "--cap-drop") == ["ALL"]
    assert option(command, "--security-opt") == ["no-new-privileges=true"]
    assert "--privileged" not in command
    assert "--cap-add" not in command


def test_the_resources_are_bounded_without_swap() -> None:
    command = build(limits=Limits(cpus=1.5, memory_mb=512, pids=64))
    assert option(command, "--pids-limit") == ["64"]
    assert option(command, "--memory") == ["512m"]
    assert option(command, "--memory-swap") == ["512m"]
    assert option(command, "--cpus") == ["1.5"]
    assert "--init" in command


def test_the_copy_is_mounted_read_only_and_is_the_only_mount() -> None:
    command = build(source=Path("/var/runs/42"))
    expected = f"type=bind,source={Path('/var/runs/42')},target=/work,readonly"
    assert option(command, "--mount") == [expected]
    assert "-v" not in command
    assert "--volume" not in command
    assert option(command, "--workdir") == ["/work"]


def test_the_environment_inside_is_fixed() -> None:
    assert option(build(), "--env") == [
        "HOME=/tmp",
        "PYTHONDONTWRITEBYTECODE=1",
        *(f"{name}=" for name in PROXY_VARIABLES),
    ]


def test_no_proxy_of_the_client_configuration_reaches_the_container() -> None:
    """B284: the client fills only the proxy names the command does not set (docker/cli)."""
    assert sorted(PROXY_VARIABLES) == sorted(
        [
            "HTTP_PROXY",
            "http_proxy",
            "HTTPS_PROXY",
            "https_proxy",
            "FTP_PROXY",
            "ftp_proxy",
            "NO_PROXY",
            "no_proxy",
            "ALL_PROXY",
            "all_proxy",
        ]
    )
    assert set(PROXY_VARIABLES) <= {value.removesuffix("=") for value in option(build(), "--env")}


def test_the_program_runs_under_its_own_time_limit() -> None:
    """B282: the container ends by itself even when nobody kills it."""
    command = build(max_seconds=27)
    image = f"sha256:{'b' * 64}"
    assert option(command, "--entrypoint") == ["timeout"]
    assert command[command.index(image) :] == [
        image,
        "-s",
        "KILL",
        "27",
        "ruff",
        "check",
        "--no-cache",
        "--output-format=json",
        ".",
    ]


def test_the_container_is_labelled_with_the_time_it_ends_by() -> None:
    assert option(build(ends_by=ENDS_BY), "--label") == [f"cerveau.code_checks.ends_by={ENDS_BY}"]
    assert LABEL == "cerveau.code_checks.ends_by"


@pytest.mark.parametrize(("given", "own"), [(25.0, 27), (24.2, 27), (0.5, 3), (300.0, 302)])
def test_the_container_limit_comes_after_the_clients(given: float, own: int) -> None:
    assert container_seconds(given) == own


def test_the_leftovers_are_listed_by_label_with_their_end() -> None:
    assert leftover_command() == [
        "ps",
        "--filter",
        f"label={LABEL}",
        "--format",
        '{{.ID}} {{.Label "cerveau.code_checks.ends_by"}}',
    ]


def test_only_containers_past_their_end_are_overdue() -> None:
    late, early, now = "a" * 12, "b" * 12, 1_000.0
    stdout = (
        f"{late} 999\n{early} 1000\n{'c' * 64} 12\n"
        # Not ours, or not readable: left alone.
        f"{'d' * 12}\n{'e' * 12} demain\nZZZZZZZZZZZZ 5\n{'f' * 11} 5\n{'0' * 12} 5 x\n"
        f"{'1' * 12} ٣\n\n"
    ).encode()
    assert overdue(stdout, now) == [late, "c" * 64]
    assert overdue(b"", now) == []


@pytest.mark.parametrize("folder", ["/var/a,b", "/var/a=b", '/var/a"b'])
def test_a_source_that_would_change_the_mount_is_refused(folder: str) -> None:
    with pytest.raises(SandboxError, match="dossier des contrôles refusé"):
        build(source=Path(folder))


def test_the_docker_client_gets_only_what_it_needs() -> None:
    env = docker_environment(
        {
            "PATH": "p",
            "USERPROFILE": "u",
            "DOCKER_HOST": "npipe:////./pipe/docker_engine",
            "CERVEAU_API_TOKEN": "x",
            "ANTHROPIC_API_KEY": "x",
            "GITHUB_TOKEN": "x",
        }
    )
    assert env == {"PATH": "p", "USERPROFILE": "u", "DOCKER_HOST": "npipe:////./pipe/docker_engine"}


def test_a_variable_for_a_container_is_passed_by_name_only_when_asked() -> None:
    """The proxy's ``docker run --env ANTHROPIC_API_KEY`` reads it from the client (ADR-054)."""
    environ = {"PATH": "p", "ANTHROPIC_API_KEY": "cle-factice", "GITHUB_TOKEN": "x"}
    assert "ANTHROPIC_API_KEY" not in DockerRunner(environ=environ).env
    passed = DockerRunner(environ=environ, passed=("ANTHROPIC_API_KEY", "ABSENTE"))
    assert passed.env == {"PATH": "p", "ANTHROPIC_API_KEY": "cle-factice"}


FAKE_DOCKER = """
import sys, time
arguments = sys.argv[1:]
if arguments[0] == "kill":
    with open(sys.argv[0] + ".killed", "w") as handle:
        handle.write(arguments[1])
    sys.exit(0)
mode = arguments[-1]
if mode == "slow":
    time.sleep(20)
elif mode == "flood":
    sys.stdout.write("x" * 200000)
elif mode == "fail":
    sys.stderr.write("Unable to find image")
    sys.exit(125)
else:
    print("[]")
"""


@pytest.fixture
def fake_docker(tmp_path: Path) -> tuple[DockerRunner, Path]:
    script = tmp_path / "docker.py"
    script.write_text(FAKE_DOCKER, encoding="utf-8")
    return DockerRunner((sys.executable, str(script))), tmp_path / "docker.py.killed"


def test_a_check_runs_and_its_output_is_returned(fake_docker: tuple[DockerRunner, Path]) -> None:
    runner, killed = fake_docker
    out = runner.run(["run", "ok"], name="c1", timeout_s=10, max_bytes=1_000)
    assert out.returncode == 0
    assert out.stdout.strip() == b"[]"
    assert not killed.exists()


def test_a_docker_error_is_returned_with_its_code(fake_docker: tuple[DockerRunner, Path]) -> None:
    runner, killed = fake_docker
    out = runner.run(["run", "fail"], name="c1", timeout_s=10, max_bytes=1_000)
    assert out.returncode == 125
    assert "Unable to find image" in out.stderr
    assert not killed.exists()


def test_a_slow_container_is_killed_by_name(fake_docker: tuple[DockerRunner, Path]) -> None:
    runner, killed = fake_docker
    out = runner.run(["run", "slow"], name="cerveau-check-7", timeout_s=0.5, max_bytes=1_000)
    assert out.timed_out
    assert out.stopped is True
    assert killed.read_text(encoding="utf-8") == "cerveau-check-7"


def test_a_flooding_container_is_killed_by_name(fake_docker: tuple[DockerRunner, Path]) -> None:
    runner, killed = fake_docker
    out = runner.run(["run", "flood"], name="cerveau-check-8", timeout_s=10, max_bytes=1_000)
    assert out.truncated
    assert out.stopped is True
    assert len(out.stdout) == 1_000
    assert killed.read_text(encoding="utf-8") == "cerveau-check-8"


def test_a_container_within_its_limits_is_not_killed(
    fake_docker: tuple[DockerRunner, Path],
) -> None:
    runner, killed = fake_docker
    assert runner.run(["run", "ok"], name="c1", timeout_s=10, max_bytes=1_000).stopped is None
    assert not killed.exists()


class Steps:
    """``run_bounded`` answering each command in turn; the clock moves as each one asks."""

    def __init__(self, *answers: Bounded | OSError, takes: Sequence[float] = ()) -> None:
        self.answers = list(answers)
        self.takes = list(takes)
        self.calls: list[list[str]] = []
        self.timeouts: list[float] = []
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def __call__(self, command: Sequence[str], *, timeout_s: float, **_: object) -> Bounded:
        self.calls.append(list(command))
        self.timeouts.append(timeout_s)
        self.now += self.takes.pop(0) if self.takes else 0.0
        answer = self.answers.pop(0)
        if isinstance(answer, OSError):
            raise answer
        return answer


SLOW = Bounded(-9, b"", "", truncated=False, timed_out=True)
DONE = Bounded(0, b"", "", truncated=False, timed_out=False)
NOT_RUNNING = Bounded(1, b"", "Error: No such container", truncated=False, timed_out=False)
NO_ANSWER = Bounded(-9, b"", "", truncated=False, timed_out=True)
DOWN = Bounded(1, b"", "Cannot connect to the Docker daemon", truncated=False, timed_out=False)
LISTED = Bounded(0, b"f00d\n", "", truncated=False, timed_out=False)
KILL = ["docker", "kill", "c1"]
PS = ["docker", "ps", "--quiet", "--filter", "name=c1"]


@pytest.mark.parametrize(
    ("answers", "stopped", "commands"),
    [
        # docker kill answered 0.
        ((DONE,), True, [KILL]),
        # Already gone (ended meanwhile, removed by --rm): docker ps no longer lists it.
        ((NOT_RUNNING, DONE), True, [KILL, PS]),
        # The kill failed and the container still runs: not stopped (B282).
        ((NOT_RUNNING, LISTED), False, [KILL, PS]),
        # The engine does not answer, or cannot be reached: nothing is confirmed.
        ((NO_ANSWER,), False, [KILL]),
        ((OSError("gone"),), False, [KILL]),
        ((NOT_RUNNING, NO_ANSWER), False, [KILL, PS]),
        ((NOT_RUNNING, DOWN), False, [KILL, PS]),
        ((NOT_RUNNING, OSError("gone")), False, [KILL, PS]),
    ],
)
def test_a_container_is_said_stopped_only_when_docker_confirms_it(
    answers: tuple[Bounded | OSError, ...],
    stopped: bool,
    commands: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steps = Steps(SLOW, *answers)
    monkeypatch.setattr(sandbox, "run_bounded", steps)
    out = DockerRunner(("docker",), clock=steps.clock).run(
        ["run"], name="c1", timeout_s=1, max_bytes=10
    )
    assert (out.timed_out, out.stopped) == (True, stopped)
    assert steps.calls == [["docker", "run"], *commands]


def test_the_check_after_a_failed_kill_shares_its_time(monkeypatch: pytest.MonkeyPatch) -> None:
    steps = Steps(SLOW, NOT_RUNNING, DONE, takes=[1.0, 4.0])
    monkeypatch.setattr(sandbox, "run_bounded", steps)
    out = DockerRunner(("docker",), clock=steps.clock).run(
        ["run"], name="c1", timeout_s=1, max_bytes=10
    )
    assert out.stopped is True
    assert steps.timeouts == [1, KILL_TIMEOUT_S, KILL_TIMEOUT_S - 4.0]


def test_no_check_is_made_once_the_kill_took_all_its_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steps = Steps(SLOW, NOT_RUNNING, takes=[1.0, KILL_TIMEOUT_S])
    monkeypatch.setattr(sandbox, "run_bounded", steps)
    out = DockerRunner(("docker",), clock=steps.clock).run(
        ["run"], name="c1", timeout_s=1, max_bytes=10
    )
    assert out.stopped is False
    assert steps.calls == [["docker", "run"], KILL]


def test_a_command_without_container_is_never_followed_by_a_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steps = Steps(SLOW)
    monkeypatch.setattr(sandbox, "run_bounded", steps)
    out = DockerRunner(("docker",)).run(["ps"], name="", timeout_s=1, max_bytes=10)
    assert (out.timed_out, out.stopped) == (True, None)
    assert steps.calls == [["docker", "ps"]]


def test_a_missing_docker_is_an_error(tmp_path: Path) -> None:
    runner = DockerRunner((str(tmp_path / "absent-docker"),))
    with pytest.raises(SandboxError, match="Docker ne peut pas être lancé"):
        runner.run(["run"], name="c1", timeout_s=1, max_bytes=10)


def test_a_kill_that_cannot_start_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    slow = Bounded(-9, b"", "", truncated=False, timed_out=True)

    def fake(command: Sequence[str], **_: object) -> Bounded:
        calls.append(list(command))
        if len(calls) == 2:
            raise OSError("gone")
        return slow

    monkeypatch.setattr(sandbox, "run_bounded", fake)
    out = DockerRunner(("docker",)).run(["run"], name="c1", timeout_s=1, max_bytes=10)
    assert (out.returncode, out.timed_out) == (slow.returncode, True)
    # Not confirmed: the kill never ran (B282).
    assert out.stopped is False
    assert calls == [["docker", "run"], ["docker", "kill", "c1"]]


@pytest.mark.parametrize(
    "path",
    [
        "src/mod.py",
        "README",
        "docs/a b/c.md",
        "console.py",
        "con2.txt",
        "aux_data/x",
        "naïve.py",
    ],
)
def test_portable_paths(path: str) -> None:
    assert portable(path)


@pytest.mark.parametrize(
    "path",
    [
        "CON",
        "con.txt",
        "src/nul.py",
        "Aux",
        "com1",
        "LPT9.log",
        "COM¹",
        "CONIN$",
        "src/conout$.txt",
        "a/trailing.",
        "a/trailing ",
        "x<y",
        "x>y",
        "what?",
        "star*",
        "pipe|x",
        'quote"x',
    ],
)
def test_paths_that_windows_cannot_write(path: str) -> None:
    assert not portable(path)


def item(path: str, mode: str = "100644", size: int | None = 3) -> TreeItem:
    kind = {"120000": "blob", "160000": "commit"}.get(mode, "blob")
    return TreeItem(mode, kind, SHA, size, path)


def test_regular_files_are_copied() -> None:
    files, withheld, skipped = plan_copy([item("a.py"), item("bin/run", "100755")])
    assert [entry.path for entry in files] == ["a.py", "bin/run"]
    assert withheld == skipped == []


def test_sensitive_files_are_withheld() -> None:
    files, withheld, skipped = plan_copy(
        [item(".env"), item("secrets/token.txt"), item("deploy/id_ed25519"), item("ok.py")]
    )
    assert [entry.path for entry in files] == ["ok.py"]
    assert withheld == [".env", "secrets/token.txt", "deploy/id_ed25519"]
    assert skipped == []


def test_links_submodules_and_other_modes_are_skipped() -> None:
    entries = [item("link", "120000"), item("vendor/lib", "160000", None), item("odd", "100664")]
    files, withheld, skipped = plan_copy(entries)
    assert files == []
    assert withheld == []
    assert skipped == ["link", "vendor/lib", "odd"]


def test_paths_refused_by_the_reader_are_skipped() -> None:
    files, _, skipped = plan_copy([item("a\\b.py"), item("x‮.py"), item("ok.py")])
    assert [entry.path for entry in files] == ["ok.py"]
    assert skipped == ["a\\b.py", "x‮.py"]


def test_paths_that_are_not_portable_are_skipped() -> None:
    files, _, skipped = plan_copy([item("nul.py"), item("ok.py")])
    assert [entry.path for entry in files] == ["ok.py"]
    assert skipped == ["nul.py"]


def test_case_collisions_keep_the_first_file() -> None:
    files, _, skipped = plan_copy([item("Readme.md"), item("README.md"), item("readme.MD")])
    assert [entry.path for entry in files] == ["Readme.md"]
    assert skipped == ["README.md", "readme.MD"]


@pytest.fixture
def opened(tmp_path: Path) -> tuple[RepoReader, Repository]:
    repo = make_repo(
        tmp_path / "projet",
        {
            "README.md": "Projet\n",
            "src/app.py": "print('ok')\r\n",
            "data.bin": b"\x00\xff\n",
            ".env": "API_KEY=x\n",
        },
    )
    # Windows cannot hold this name, and git for Windows refuses it unless told otherwise: the
    # entry goes straight into the commit, as a repository made elsewhere would carry it.
    entry = f"100644,{blob(repo, b'')},nul.txt"
    git(repo, "-c", "core.protectNTFS=false", "update-index", "--add", "--cacheinfo", entry)
    git(repo, "commit", "-q", "-m", "reserved name")
    add_entry(repo, "120000", blob(repo, b"../../etc/passwd"), "lien", "link")
    add_entry(repo, "160000", git(repo, "rev-parse", "HEAD").strip(), "vendor/lib", "submodule")
    reader = RepoReader(GitRunner(), cerveau_root=tmp_path / "cerveau-absent")
    return reader, reader.open([listed("p", repo)], "p")


def test_the_copy_holds_the_committed_bytes_only(
    opened: tuple[RepoReader, Repository], tmp_path: Path
) -> None:
    reader, repo = opened
    (repo.root / "README.md").write_text("modifié, non commité\n", encoding="utf-8")
    sha = reader.commit(repo, "HEAD")
    copy = copy_tree(reader, repo, sha, tmp_path / "runs" / "1", max_files=10, max_bytes=1_000)
    root = tmp_path / "runs" / "1"
    written = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert written == ["README.md", "data.bin", "src/app.py"]
    assert (root / "README.md").read_bytes() == b"Projet\n"
    assert (root / "src" / "app.py").read_bytes() == b"print('ok')\r\n"
    assert (root / "data.bin").read_bytes() == b"\x00\xff\n"
    assert (copy.root, copy.files, copy.size) == (root, 3, 23)
    assert copy.withheld == (".env",)
    assert sorted(copy.skipped) == ["lien", "nul.txt", "vendor/lib"]


def test_an_existing_destination_is_refused(
    opened: tuple[RepoReader, Repository], tmp_path: Path
) -> None:
    reader, repo = opened
    (tmp_path / "runs").mkdir()
    with pytest.raises(SandboxError, match="copie du dépôt impossible"):
        copy_tree(reader, repo, "HEAD", tmp_path / "runs", max_files=10, max_bytes=1_000)


def test_a_destination_under_a_file_is_refused(
    opened: tuple[RepoReader, Repository], tmp_path: Path
) -> None:
    reader, repo = opened
    (tmp_path / "fichier").write_text("x", encoding="utf-8")
    with pytest.raises(SandboxError, match="copie du dépôt impossible"):
        copy_tree(reader, repo, "HEAD", tmp_path / "fichier" / "1", max_files=10, max_bytes=1_000)


@pytest.mark.parametrize(("max_files", "max_bytes"), [(2, 1_000), (10, 22)])
def test_a_repository_past_the_ceilings_is_not_copied(
    opened: tuple[RepoReader, Repository], tmp_path: Path, max_files: int, max_bytes: int
) -> None:
    reader, repo = opened
    with pytest.raises(SandboxError, match="dépôt trop gros pour les contrôles : 3 fichiers"):
        copy_tree(reader, repo, "HEAD", tmp_path / "1", max_files=max_files, max_bytes=max_bytes)
    assert not (tmp_path / "1").exists()


def test_a_file_named_like_a_folder_is_skipped() -> None:
    files, _, skipped = plan_copy([item("Pkg"), item("pkg/mod.py")])
    assert [entry.path for entry in files] == ["pkg/mod.py"]
    assert skipped == ["Pkg"]


# --- the throwaway folders (B283) -------------------------------------------------------------


def test_a_private_folder_is_new_and_closed_to_others(tmp_path: Path) -> None:
    folder = private_folder(tmp_path / "temp", "cerveau-checks-1")
    assert folder == tmp_path / "temp" / "cerveau-checks-1"
    assert folder.is_dir() and list(folder.iterdir()) == []
    if os.name == "posix":
        assert stat.S_IMODE(folder.stat().st_mode) & 0o077 == 0


def test_a_folder_that_already_exists_is_refused_and_left_as_is(tmp_path: Path) -> None:
    taken = tmp_path / "cerveau-checks-1"
    taken.mkdir()
    (taken / "conftest.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(SandboxError, match="dossier temporaire des contrôles impossible à créer"):
        private_folder(tmp_path, "cerveau-checks-1")
    assert (taken / "conftest.py").exists()


def test_a_private_folder_under_a_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "fichier").write_text("x", encoding="utf-8")
    with pytest.raises(SandboxError, match="dossier temporaire des contrôles impossible à créer"):
        private_folder(tmp_path / "fichier", "cerveau-checks-1")


NOW = 2_000_000_000.0


def aged(path: Path, seconds: float) -> Path:
    os.utime(path, (NOW - seconds, NOW - seconds))
    return path


def test_the_folders_crashed_calls_left_are_found(tmp_path: Path) -> None:
    current = private_folder(tmp_path, "cerveau-checks-courant")
    old = aged(private_folder(tmp_path, "cerveau-checks-ancien"), STALE_AFTER_S + 1)
    older = aged(private_folder(tmp_path, "cerveau-checks-0-plus-ancien"), 10 * STALE_AFTER_S)
    # A call under way (recent), another plugin's folder, a file, the call's own folder.
    aged(private_folder(tmp_path, "cerveau-checks-recent"), STALE_AFTER_S - 1)
    aged(private_folder(tmp_path, "cerveau-agent-ancien"), 10 * STALE_AFTER_S)
    aged(private_folder(tmp_path, "autre"), 10 * STALE_AFTER_S)
    file = tmp_path / "cerveau-checks-fichier"
    file.write_text("x", encoding="utf-8")
    aged(file, 10 * STALE_AFTER_S)
    aged(current, 10 * STALE_AFTER_S)
    assert leftovers(tmp_path, "cerveau-checks-", current, NOW) == [older, old]


def test_a_link_to_a_folder_is_never_a_leftover(tmp_path: Path) -> None:
    current = private_folder(tmp_path / "temp", "cerveau-checks-courant")
    target = aged(private_folder(tmp_path, "ailleurs"), 10 * STALE_AFTER_S)
    link = tmp_path / "temp" / "cerveau-checks-lien"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("pas de lien symbolique sur ce système (droits Windows)")
    assert leftovers(tmp_path / "temp", "cerveau-checks-", current, NOW) == []


class OtherOwner:
    """The call's own folder, as another account would own it."""

    name = "cerveau-checks-courant"

    def stat(self) -> os.stat_result:
        return os.stat_result((0, 0, 0, 0, -1, 0, 0, 0, 0, 0))


def test_a_folder_of_another_account_is_never_a_leftover(tmp_path: Path) -> None:
    aged(private_folder(tmp_path, "cerveau-checks-ancien"), 10 * STALE_AFTER_S)
    assert leftovers(tmp_path, "cerveau-checks-", OtherOwner(), NOW) == []  # type: ignore[arg-type]


def test_a_missing_temporary_folder_has_no_leftover(tmp_path: Path) -> None:
    current = private_folder(tmp_path, "cerveau-checks-courant")
    assert leftovers(tmp_path / "absent", "cerveau-checks-", current, NOW) == []
