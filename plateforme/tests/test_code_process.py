"""The bounded runner shared by git and the check containers: limits, stdin, no blocking."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from core.code.process import MAX_STDERR_BYTES, Bounded, run_bounded

PYTHON = (sys.executable, "-c")
ENV = {
    name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if name in os.environ
}


def run(script: str, **kwargs: Any) -> Bounded:
    options: dict[str, Any] = {"env": ENV, "timeout_s": 10.0, "max_bytes": 1_000, **kwargs}
    return run_bounded([*PYTHON, script], **options)


def test_the_output_and_the_return_code_are_returned() -> None:
    out = run("import sys; print('ok'); sys.exit(3)")
    assert out.returncode == 3
    assert out.stdout.strip() == b"ok"
    assert not out.truncated
    assert not out.timed_out


def test_the_output_is_cut_at_the_byte_limit() -> None:
    out = run("import sys; sys.stdout.write('x' * 200000)")
    assert out.truncated
    assert out.stdout == b"x" * 1_000


def test_stderr_is_drained_but_bounded() -> None:
    out = run("import sys; sys.stderr.write('e' * 100000); print('ok')")
    assert out.stdout.strip() == b"ok"
    assert out.stderr == "e" * MAX_STDERR_BYTES


def test_a_slow_program_is_stopped() -> None:
    out = run("import time; time.sleep(20)", timeout_s=0.3)
    assert out.timed_out
    assert out.returncode != 0


def test_a_missing_program_raises_oserror(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        run_bounded([str(tmp_path / "absent")], env=ENV, timeout_s=1, max_bytes=10)


def test_stdin_is_closed_when_not_given() -> None:
    out = run("import sys; print(len(sys.stdin.read()))")
    assert out.stdout.strip() == b"0"


def test_stdin_is_written_when_given() -> None:
    out = run("import sys; print(len(sys.stdin.buffer.read()))", stdin=b"a" * 300_000)
    assert out.stdout.strip() == b"300000"


def test_a_program_that_does_not_read_its_stdin_does_not_block() -> None:
    out = run("print('done')", stdin=b"a" * 5_000_000)
    assert out.returncode == 0
    assert out.stdout.strip() == b"done"
    assert not out.timed_out


def test_the_environment_is_exactly_the_one_given() -> None:
    script = "import os; print(os.environ.get('CERVEAU_TEST_VALUE', '-'))"
    assert run(script).stdout.strip() == b"-"
    assert run(script, env={**ENV, "CERVEAU_TEST_VALUE": "v"}).stdout.strip() == b"v"
