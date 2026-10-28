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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from core.code.process import MAX_STDERR_BYTES, run_bounded

__all__ = ["GLOBAL_OPTIONS", "MAX_STDERR_BYTES", "GitError", "GitOutput", "GitRunner"]

GIT_TIMEOUT_S = 10.0

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
        self,
        repo: Path,
        args: Sequence[str],
        *,
        max_bytes: int,
        literal_paths: bool = False,
        stdin: bytes | None = None,
    ) -> GitOutput:
        """``git -C repo <args>``; ``literal_paths`` makes every path argument a plain name."""
        command = [*self.executable, *GLOBAL_OPTIONS, "-C", str(repo), *args]
        env = dict(self.env, GIT_LITERAL_PATHSPECS="1") if literal_paths else self.env
        try:
            out = run_bounded(
                command, env=env, timeout_s=self.timeout_s, max_bytes=max_bytes, stdin=stdin
            )
        except OSError as exc:
            raise GitError(f"git ne peut pas être lancé ({type(exc).__name__})") from None
        if out.timed_out:
            raise GitError(f"git : délai de {self.timeout_s:g} s dépassé")
        return GitOutput(out.returncode, out.stdout, out.stderr, out.truncated)
