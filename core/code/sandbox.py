"""The check sandbox of the code pack: a throwaway copy, a networkless container (ADR-048).

The repository's code is untrusted: a test suite runs it. So the checks never run on the
repository itself nor on the host:

1. ``copy_tree`` writes the files of one commit, read from git objects (``ls-tree`` then one
   ``cat-file --batch``), into a fresh folder. Sensitive files (R6) are never written; symbolic
   links, submodules and paths that are not portable or that collide without case are skipped.
   Nothing is checked out, so no filter of the repository runs (ADR-047).
2. ``docker_command`` builds the ``docker run`` arguments, a pure function: no network, read-only
   root, a small ``noexec`` tmpfs, the copy mounted read only, an unprivileged user, every
   capability dropped, no new privileges, bounded processors, memory (no swap) and processes,
   an image pinned by content and never pulled.
3. ``DockerRunner`` runs it without a shell under a time limit; past it, or past the output
   limit, the container is killed by name (stopping the client alone would leave it running).
"""

from __future__ import annotations

import contextlib
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from core.code.process import Bounded, run_bounded
from core.code.repos import RepoError, RepoReader, Repository, TreeItem, check_path, is_sensitive

WORKDIR = "/work"
# nobody:nogroup on Debian, the base of python:3.12-slim.
CONTAINER_USER = "65534:65534"
# A tmpfs inside the container, not a folder of the host.
TMPFS = "/tmp:rw,noexec,nosuid,size=65536k"  # noqa: S108
KILL_TIMEOUT_S = 10.0
_SMALL = 8_000
# Variables the Docker client needs to find its configuration and its engine; nothing else.
_PASSED = (
    "PATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
)
# Names Windows cannot create, with or without an extension.
_RESERVED = re.compile(
    r"^(?:con|prn|aux|nul|conin\$|conout\$|com[0-9¹²³]|lpt[0-9¹²³])(?:\..*)?$", re.IGNORECASE
)
_NOT_PORTABLE = frozenset('<>:"|?*')


class SandboxError(Exception):
    """The checks cannot run. The message is French and safe to show to the planner."""


@dataclass(frozen=True)
class Limits:
    cpus: float
    memory_mb: int
    pids: int


@dataclass(frozen=True)
class Copy:
    root: Path
    files: int
    size: int
    # Sensitive files: named, never written (R6).
    withheld: tuple[str, ...]
    # Symbolic links, submodules, other modes, paths not portable or colliding without case.
    skipped: tuple[str, ...]


def portable(path: str) -> bool:
    """A path that every system can write: no reserved name, no trailing dot or space."""
    return not any(
        _RESERVED.match(segment)
        or segment.endswith((".", " "))
        or any(char in _NOT_PORTABLE for char in segment)
        for segment in path.split("/")
    )


def _parents(path: str) -> list[str]:
    segments = path.split("/")
    return ["/".join(segments[:end]) for end in range(1, len(segments))]


def plan_copy(items: Sequence[TreeItem]) -> tuple[list[TreeItem], list[str], list[str]]:
    """The files to write, the sensitive files withheld and the entries skipped."""
    withheld: list[str] = []
    skipped: list[str] = []
    candidates: list[TreeItem] = []
    for item in items:
        if item.kind != "file":
            skipped.append(item.path)
        elif is_sensitive(item.path):
            withheld.append(item.path)
        else:
            try:
                check_path(item.path)
            except RepoError:
                skipped.append(item.path)
                continue
            if portable(item.path):
                candidates.append(item)
            else:
                skipped.append(item.path)
    folders = {parent.casefold() for item in candidates for parent in _parents(item.path)}
    seen: set[str] = set()
    files: list[TreeItem] = []
    for item in candidates:
        key = item.path.casefold()
        if key in seen or key in folders:
            skipped.append(item.path)
        else:
            seen.add(key)
            files.append(item)
    return files, withheld, skipped


def copy_tree(
    reader: RepoReader,
    repo: Repository,
    sha: str,
    destination: Path,
    *,
    max_files: int,
    max_bytes: int,
) -> Copy:
    """Write the files of commit ``sha`` into ``destination``, which must not exist yet."""
    files, withheld, skipped = plan_copy(reader.tree(repo, sha, recursive=True))
    size = sum(item.size or 0 for item in files)
    if len(files) > max_files or size > max_bytes:
        raise SandboxError(
            f"dépôt trop gros pour les contrôles : {len(files)} fichiers, {size} octets "
            f"(plafonds : {max_files} fichiers, {max_bytes} octets)"
        )
    contents = reader.blobs(repo, [item.sha for item in files], size)
    try:
        destination.mkdir(parents=True)
        for item in files:
            target = destination.joinpath(*item.path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(contents[item.sha])
    except OSError:
        raise SandboxError("copie du dépôt impossible dans le dossier des contrôles") from None
    return Copy(destination, len(files), size, tuple(withheld), tuple(skipped))


def docker_command(
    name: str,
    image: str,
    source: Path,
    limits: Limits,
    program: str,
    arguments: Sequence[str],
) -> list[str]:
    """Arguments of ``docker run`` for one check (ADR-048); each option is tested."""
    mount_source = str(source)
    if any(char in mount_source for char in ',="'):
        raise SandboxError('dossier des contrôles refusé : « , », « = » ou « " » dans son chemin')
    return [
        "run",
        "--rm",
        "--name",
        name,
        "--pull",
        "never",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        TMPFS,
        "--user",
        CONTAINER_USER,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges=true",
        "--pids-limit",
        str(limits.pids),
        "--memory",
        f"{limits.memory_mb}m",
        "--memory-swap",
        f"{limits.memory_mb}m",
        "--cpus",
        f"{limits.cpus:g}",
        "--init",
        "--mount",
        f"type=bind,source={mount_source},target={WORKDIR},readonly",
        "--workdir",
        WORKDIR,
        "--env",
        "HOME=/tmp",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--entrypoint",
        program,
        image,
        *arguments,
    ]


def docker_environment(environ: Mapping[str, str]) -> dict[str, str]:
    return {name: environ[name] for name in _PASSED if name in environ}


class DockerRunner:
    def __init__(
        self, executable: Sequence[str] = ("docker",), *, environ: Mapping[str, str] = os.environ
    ) -> None:
        self.executable = tuple(executable)
        self.env = docker_environment(environ)

    def run(
        self, arguments: Sequence[str], *, name: str, timeout_s: float, max_bytes: int
    ) -> Bounded:
        try:
            out = run_bounded(
                [*self.executable, *arguments],
                env=self.env,
                timeout_s=timeout_s,
                max_bytes=max_bytes,
            )
        except OSError as exc:
            raise SandboxError(f"Docker ne peut pas être lancé ({type(exc).__name__})") from None
        if out.timed_out or out.truncated:
            # --rm removes the container once killed.
            with contextlib.suppress(OSError):
                run_bounded(
                    [*self.executable, "kill", name],
                    env=self.env,
                    timeout_s=KILL_TIMEOUT_S,
                    max_bytes=_SMALL,
                )
        return out
