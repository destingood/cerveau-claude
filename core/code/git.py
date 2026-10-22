"""A bounded ``git`` runner that runs no program a repository names (ADR-047).

A repository is untrusted: its ``.git/config`` and ``.gitattributes`` may name programs (external
diff, textconv, pager, fsmonitor, signature checker, lazy fetch from a promisor remote). Every call
goes without a shell, with a minimal environment that ignores the system and global configuration,
with options that switch those programs off, under a time limit, its output read up to a byte limit.
Callers read objects only (``log``, ``diff`` between commits, ``ls-tree``, ``cat-file``), never the
working tree, so no checkout filter runs either.
"""

from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, cast

GIT_TIMEOUT_S = 10.0
MAX_STDERR_BYTES = 4_000
_CHUNK = 65_536

# Before the subcommand. The -c values override the repository's own configuration.
GLOBAL_OPTIONS = (
    "--no-pager",
    "--no-lazy-fetch",
    "--no-optional-locks",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "log.showSignature=false",
    "-c",
    "color.ui=false",
)
_PASSED = ("PATH", "SYSTEMROOT", "TEMP", "TMP")


class GitError(Exception):
    """git could not run or ran too long. The message is French and safe to show."""


@dataclass(frozen=True)
class GitOutput:
    returncode: int
    stdout: bytes
    stderr: str
    # The output went past the byte limit: git was stopped there.
    truncated: bool


def git_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """No user variable but the few git needs to start; no system nor global configuration."""
    env = {name: environ[name] for name in _PASSED if name in environ}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
        GIT_NO_LAZY_FETCH="1",
        GIT_ATTR_NOSYSTEM="1",
        GIT_NO_REPLACE_OBJECTS="1",
        LC_ALL="C",
    )
    return env


def _read_bounded(stream: IO[bytes], limit: int) -> tuple[bytes, bool]:
    data = bytearray()
    while chunk := stream.read1(_CHUNK):  # type: ignore[attr-defined]
        data.extend(chunk)
        if len(data) > limit:
            return bytes(data[:limit]), True
    return bytes(data), False


def _drain(stream: IO[bytes], sink: bytearray) -> None:
    """Read stderr to its end so git never blocks on it; keep only its beginning."""
    while chunk := stream.read1(_CHUNK):  # type: ignore[attr-defined]
        sink.extend(chunk[: max(0, MAX_STDERR_BYTES - len(sink))])


class GitRunner:
    def __init__(
        self,
        executable: Sequence[str] = ("git",),
        *,
        timeout_s: float = GIT_TIMEOUT_S,
        environ: Mapping[str, str] = os.environ,
    ) -> None:
        self.executable = tuple(executable)
        self.timeout_s = timeout_s
        self.env = git_environment(environ)

    def run(
        self, repo: Path, args: Sequence[str], *, max_bytes: int, literal_paths: bool = False
    ) -> GitOutput:
        """``git -C repo <args>``; ``literal_paths`` makes every path argument a plain name."""
        command = [*self.executable, *GLOBAL_OPTIONS, "-C", str(repo), *args]
        env = dict(self.env, GIT_LITERAL_PATHSPECS="1") if literal_paths else self.env
        try:
            process = subprocess.Popen(  # noqa: S603 - fixed arguments, no shell
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
        except OSError as exc:
            raise GitError(f"git ne peut pas être lancé ({type(exc).__name__})") from None
        stdout_pipe = cast(IO[bytes], process.stdout)
        timed_out = threading.Event()

        def stop() -> None:
            timed_out.set()
            process.kill()

        timer = threading.Timer(self.timeout_s, stop)
        errors = bytearray()
        reader = threading.Thread(target=_drain, args=(process.stderr, errors), daemon=True)
        timer.start()
        reader.start()
        try:
            stdout, truncated = _read_bounded(stdout_pipe, max_bytes)
            if truncated:
                process.kill()
            process.wait()
        finally:
            timer.cancel()
            reader.join(timeout=1.0)
            stdout_pipe.close()
        if timed_out.is_set():
            raise GitError(f"git : délai de {self.timeout_s:g} s dépassé")
        return GitOutput(
            process.returncode, stdout, errors.decode("utf-8", errors="replace"), truncated
        )
