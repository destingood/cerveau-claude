"""The bounded git runner of the code pack (ADR-047): environment, limits, no repository program."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from core.code.git import GLOBAL_OPTIONS, MAX_STDERR_BYTES, GitError, GitRunner, git_environment
from tests.code_support import make_repo

PYTHON = (sys.executable, "-c")


def test_the_environment_carries_no_user_variable() -> None:
    env = git_environment(
        {"PATH": "p", "SYSTEMROOT": "s", "TEMP": "t", "HOME": "h", "CERVEAU_API_TOKEN": "x"}
    )
    assert env["PATH"] == "p"
    assert "HOME" not in env
    assert "CERVEAU_API_TOKEN" not in env
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_NO_LAZY_FETCH"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_the_global_options_switch_repository_programs_off() -> None:
    assert GLOBAL_OPTIONS[:3] == ("--no-pager", "--no-lazy-fetch", "--no-optional-locks")
    assert "core.fsmonitor=false" in GLOBAL_OPTIONS
    assert "log.showSignature=false" in GLOBAL_OPTIONS


def test_git_runs_in_the_repository(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "depot", {"a.txt": "a\n"})
    out = GitRunner().run(repo, ["rev-parse", "--show-toplevel"], max_bytes=1000)
    assert out.returncode == 0
    assert Path(out.stdout.decode().strip()).resolve() == repo.resolve()
    assert not out.truncated


def test_a_failure_is_returned_with_its_stderr(tmp_path: Path) -> None:
    out = GitRunner().run(tmp_path, ["rev-parse", "--show-toplevel"], max_bytes=1000)
    assert out.returncode != 0
    assert "not a git repository" in out.stderr


def test_the_output_is_cut_at_the_byte_limit(tmp_path: Path) -> None:
    runner = GitRunner((*PYTHON, "import sys; sys.stdout.write('x' * 200000)"))
    out = runner.run(tmp_path, [], max_bytes=1000)
    assert out.truncated
    assert out.stdout == b"x" * 1000


def test_stderr_is_drained_but_bounded(tmp_path: Path) -> None:
    runner = GitRunner((*PYTHON, "import sys; sys.stderr.write('e' * 100000); print('ok')"))
    out = runner.run(tmp_path, [], max_bytes=1000)
    assert out.stdout.strip() == b"ok"
    assert out.stderr == "e" * MAX_STDERR_BYTES


def test_a_slow_git_is_stopped(tmp_path: Path) -> None:
    runner = GitRunner((*PYTHON, "import time; time.sleep(20)"), timeout_s=0.3)
    with pytest.raises(GitError, match=r"délai de 0\.3 s dépassé"):
        runner.run(tmp_path, [], max_bytes=1000)


def test_a_missing_git_is_an_error(tmp_path: Path) -> None:
    runner = GitRunner((str(tmp_path / "absent-git"),))
    with pytest.raises(GitError, match="git ne peut pas être lancé"):
        runner.run(tmp_path, [], max_bytes=1000)


def test_literal_paths_is_set_only_when_asked(tmp_path: Path) -> None:
    script = "import os; print(os.environ.get('GIT_LITERAL_PATHSPECS', '-'))"
    runner = GitRunner((*PYTHON, script))
    assert runner.run(tmp_path, [], max_bytes=100).stdout.strip() == b"-"
    assert runner.run(tmp_path, [], max_bytes=100, literal_paths=True).stdout.strip() == b"1"


def test_the_arguments_follow_the_options_and_the_repository(tmp_path: Path) -> None:
    runner = GitRunner((*PYTHON, "import sys; print(sys.argv[1:])"))
    out = runner.run(tmp_path, ["log", "-z"], max_bytes=10_000).stdout.decode()
    assert out.strip() == str([*GLOBAL_OPTIONS, "-C", str(tmp_path), "log", "-z"])
