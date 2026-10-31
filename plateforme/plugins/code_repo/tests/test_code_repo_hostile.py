"""A hostile repository: its own configuration names programs for git to run (ADR-047).

Each program appends to a marker file. The witnesses show that plain git, with the same reduced
environment, does run them; then every read of ``RepoReader`` and of the three tools must leave
no marker: the reader passes ``--no-ext-diff``, ``--no-textconv``, ``--no-pager``,
``core.fsmonitor=false`` and ``log.showSignature=false``, and never checks a file out.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.code.git import GitRunner
from core.code.repos import RepoReader
from plugins.code_repo.tests.support import example_repo
from plugins.code_repo.tests.test_code_repo_server import call, data, server_for
from tests.code_support import GIT_ENV, git, listed


def _program(markers: Path, name: str, tail: str = "") -> str:
    target = (markers / name).as_posix()
    return f"echo {name} >> '{target}'{tail}"


@pytest.fixture
def hostile(tmp_path: Path) -> tuple[Path, Path]:
    repo = example_repo(tmp_path / "hostile")
    markers = tmp_path / "marques"
    markers.mkdir()
    gpg = tmp_path / "gpg.sh"
    gpg.write_bytes(f"#!/bin/sh\n{_program(markers, 'gpg')}\nexit 1\n".encode())
    gpg.chmod(0o755)
    settings = {
        "diff.external": _program(markers, "ext"),
        "diff.x.command": _program(markers, "drv"),
        "diff.x.textconv": _program(markers, "textconv", " && cat"),
        "filter.x.smudge": _program(markers, "smudge", "; cat"),
        "filter.x.clean": _program(markers, "clean", "; cat"),
        "core.fsmonitor": _program(markers, "fsmonitor"),
        "core.pager": _program(markers, "pager", "; cat"),
        "pager.log": _program(markers, "pager", "; cat"),
        "gpg.program": gpg.as_posix(),
        "log.showSignature": "true",
    }
    for key, value in settings.items():
        git(repo, "config", key, value)
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("* diff=x filter=x\n", encoding="utf-8")
    # A commit carrying a signature, on its own branch: showing it would call gpg.program.
    tree = git(repo, "rev-parse", "HEAD^{tree}").strip()
    parent = git(repo, "rev-parse", "HEAD").strip()
    who = "Utilisateur Test <utilisateur@example.test> 1792483200 +0200"
    raw = (
        f"tree {tree}\nparent {parent}\nauthor {who}\ncommitter {who}\n"
        "gpgsig -----BEGIN PGP SIGNATURE-----\n \n iQEzBAABCAAdFiEE\n -----END PGP SIGNATURE-----\n"
        "\nsigné\n"
    )
    signed = git(repo, "hash-object", "-t", "commit", "-w", "--stdin", stdin=raw.encode()).strip()
    git(repo, "update-ref", "refs/heads/signee", signed)
    return repo, markers


def fired(markers: Path) -> set[str]:
    return {path.name for path in markers.iterdir()}


def plain_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], env=GIT_ENV, capture_output=True, check=False)


def test_plain_git_runs_the_programs_of_the_repository(hostile: tuple[Path, Path]) -> None:
    repo, markers = hostile
    plain_git(repo, "diff", "HEAD~1", "HEAD")
    assert fired(markers) & {"ext", "drv"}
    plain_git(repo, "diff", "--no-ext-diff", "HEAD~1", "HEAD")
    assert "textconv" in fired(markers)
    plain_git(repo, "log", "-1", "signee")
    assert "gpg" in fired(markers)
    plain_git(repo, "status")
    assert "fsmonitor" in fired(markers)
    (repo / "README.md").unlink()
    plain_git(repo, "checkout", "HEAD", "--", "README.md")
    assert "smudge" in fired(markers)


def test_the_reader_and_the_tools_run_none_of_them(hostile: tuple[Path, Path]) -> None:
    repo, markers = hostile
    reader = RepoReader(GitRunner())
    opened = reader.open([listed("hostile", repo)], "hostile")
    sha = reader.commit(opened, "signee")
    for item in reader.tree(opened, sha):
        if item.kind == "file" and item.path != ".env":
            reader.blob(opened, item.sha, 10_000)
    server = server_for([listed("hostile", repo)])
    for tool, arguments in (
        ("repo_log", {"repo": "hostile"}),
        ("repo_log", {"repo": "hostile", "rev": "signee"}),
        ("repo_diff", {"repo": "hostile", "base": "HEAD~1"}),
        ("repo_diff", {"repo": "hostile", "base": "v1", "head": "signee"}),
        ("repo_file", {"repo": "hostile"}),
        ("repo_file", {"repo": "hostile", "path": "src/app.py"}),
        ("repo_file", {"repo": "hostile", "path": "README.md", "rev": "signee"}),
    ):
        data(call(server, tool, {**arguments}))
    assert fired(markers) == set()
