"""The check sandbox (ADR-048): the docker command, its environment, its runner, the copy plan."""

from __future__ import annotations

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
    TMPFS,
    DockerRunner,
    Limits,
    SandboxError,
    copy_tree,
    docker_command,
    docker_environment,
    plan_copy,
    portable,
)
from tests.code_support import add_entry, blob, git, listed, make_repo

LIMITS = Limits(cpus=2, memory_mb=2048, pids=256)
SHA = "a" * 40


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
    assert option(build(), "--env") == ["HOME=/tmp", "PYTHONDONTWRITEBYTECODE=1"]


def test_the_program_and_its_arguments_follow_the_image() -> None:
    command = build()
    image = f"sha256:{'b' * 64}"
    assert option(command, "--entrypoint") == ["ruff"]
    assert command[command.index(image) :] == [
        image,
        "check",
        "--no-cache",
        "--output-format=json",
        ".",
    ]


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
    assert killed.read_text(encoding="utf-8") == "cerveau-check-7"


def test_a_flooding_container_is_killed_by_name(fake_docker: tuple[DockerRunner, Path]) -> None:
    runner, killed = fake_docker
    out = runner.run(["run", "flood"], name="cerveau-check-8", timeout_s=10, max_bytes=1_000)
    assert out.truncated
    assert len(out.stdout) == 1_000
    assert killed.read_text(encoding="utf-8") == "cerveau-check-8"


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
    assert out is slow
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
