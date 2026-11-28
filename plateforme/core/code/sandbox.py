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
   an image pinned by content and never pulled, no proxy variable of the client's configuration,
   and a time limit of its own (``timeout -s KILL``), labelled with the time it ends by.
3. ``DockerRunner`` runs it without a shell under a time limit; past it, or past the output
   limit, the container is killed by name (stopping the client alone would leave it running) and
   is said stopped only once Docker confirms it.
4. A crash skips the cleanups: ``overdue`` finds the containers running past their end and
   ``leftovers`` the throwaway folders of earlier calls, removed at the start of the next one.

The copies are written in the system's temporary folder, outside CERVEAU (B283): no tool that
searches CERVEAU's folders (pytest, an editor, Claude Code and the ``CLAUDE.md`` of a copy) finds
them, even when a crash leaves one behind.
"""

from __future__ import annotations

import contextlib
import dataclasses
import math
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
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
# The container's own limit (B282), past the client's: GNU coreutils ``timeout`` of the image
# (Debian's ``coreutils``, essential, ships /usr/bin/timeout: packages.debian.org, trixie, the base
# of python:3.12-slim, read on 2026-11-28). With ``-s KILL`` it kills the program's process group
# and itself at the end (exit code 137, coreutils manual, « timeout invocation », read on
# 2026-11-28); once PID 1 (``--init``) is gone, the kernel ends every process left in the
# container. This holds when ``docker kill`` fails or when this process is gone. The margin lets
# the client's limit come first, so that the check normally ends as ``delai``.
TIMEOUT_PROGRAM = "timeout"
CONTAINER_MARGIN_S = 2
# Key of the label holding the time (Unix seconds, host clock) a check container ends by: its own
# limit plus a slack for its start. Labels are not visible inside the container (docs.docker.com,
# docker run, --label, read on 2026-11-28). A container still running past that time is a leftover
# that ``timeout`` did not stop: the next call kills it; another call's containers, within their
# time, are left alone.
LABEL = "cerveau.code_checks.ends_by"
START_SLACK_S = 10
_CONTAINER_ID = re.compile(r"[0-9a-f]{12,64}")
# The Docker client gives each new container the proxies of ``~/.docker/config.json`` as these
# variables (docs.docker.com, « Use a proxy server with the Docker CLI »), but only the names the
# command does not set already (docker/cli, ``ConfigFile.ParseProxyConfig``, which fills a name
# only when the ``--env`` of the command lacks it; both read on 2026-11-28). A proxy's address may
# hold credentials (B284): each name is set empty, in both cases.
PROXY_VARIABLES = tuple(
    name
    for upper in ("HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "NO_PROXY", "ALL_PROXY")
    for name in (upper, upper.lower())
)
# A throwaway folder older than this is a leftover of a crashed call: four times the longest call
# of the code pack (code_agent, 900 s).
STALE_AFTER_S = 3_600.0
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


def private_folder(parent: Path, name: str) -> Path:
    """A new folder that only this account can enter, for the throwaway files of one call; never
    one that already exists (its name is random: one made by another is refused). The containers
    mount folders inside it: the engine, not their user, opens the mount."""
    try:
        parent.mkdir(parents=True, exist_ok=True)
        folder = parent / name
        folder.mkdir(mode=0o700)
    except OSError:
        raise SandboxError("dossier temporaire des contrôles impossible à créer") from None
    return folder


def leftovers(parent: Path, prefix: str, current: Path, now: float) -> list[Path]:
    """Throwaway folders that crashed calls left in ``parent``: named with ``prefix``, real
    folders (never a link or a junction), owned like ``current`` (the call's own folder, never
    listed) and unchanged for ``STALE_AFTER_S``."""
    try:
        owner = current.stat().st_uid
        with os.scandir(parent) as entries:
            found = [
                Path(entry.path)
                for entry in entries
                if entry.name.startswith(prefix)
                and entry.name != current.name
                and entry.is_dir(follow_symlinks=False)
                and not entry.is_junction()
                and entry.stat(follow_symlinks=False).st_uid == owner
                and now - entry.stat(follow_symlinks=False).st_mtime > STALE_AFTER_S
            ]
    except OSError:
        return []
    return sorted(found)


def container_seconds(timeout_s: float) -> int:
    """The container's own limit for a check the client gives ``timeout_s`` to."""
    return math.ceil(timeout_s) + CONTAINER_MARGIN_S


def blank_proxies() -> list[str]:
    """``--env NAME=`` for each proxy variable: the client then injects none (B284)."""
    return [part for name in PROXY_VARIABLES for part in ("--env", f"{name}=")]


def leftover_command() -> list[str]:
    """``docker ps`` of the running check containers, with the time each one ends by (the
    ``.ID`` and ``.Label`` placeholders of ``--format``; ``docker ps`` lists running containers
    only: docs.docker.com, docker container ls, read on 2026-11-28)."""
    return ["ps", "--filter", f"label={LABEL}", "--format", '{{.ID}} {{.Label "' + LABEL + '"}}']


def overdue(stdout: bytes, now: float) -> list[str]:
    """The containers of ``leftover_command``'s answer still running past their end. A line that
    is not ``<id> <time>`` is not one of ours and is left alone."""
    found: list[str] = []
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split()
        if (
            len(parts) == 2
            and _CONTAINER_ID.fullmatch(parts[0])
            and parts[1].isascii()
            and parts[1].isdigit()
            and int(parts[1]) < now
        ):
            found.append(parts[0])
    return found


def docker_command(
    name: str,
    image: str,
    source: Path,
    limits: Limits,
    program: str,
    arguments: Sequence[str],
    *,
    max_seconds: int,
    ends_by: int,
) -> list[str]:
    """Arguments of ``docker run`` for one check (ADR-048); each option is tested. The program
    runs under ``timeout`` for ``max_seconds``; ``ends_by`` (Unix seconds) labels the container."""
    mount_source = str(source)
    if any(char in mount_source for char in ',="'):
        raise SandboxError('dossier des contrôles refusé : « , », « = » ou « " » dans son chemin')
    return [
        "run",
        "--rm",
        "--name",
        name,
        "--label",
        f"{LABEL}={ends_by}",
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
        *blank_proxies(),
        "--entrypoint",
        TIMEOUT_PROGRAM,
        image,
        "-s",
        "KILL",
        str(max_seconds),
        program,
        *arguments,
    ]


def docker_environment(environ: Mapping[str, str]) -> dict[str, str]:
    return {name: environ[name] for name in _PASSED if name in environ}


class DockerRunner:
    def __init__(
        self,
        executable: Sequence[str] = ("docker",),
        *,
        environ: Mapping[str, str] = os.environ,
        passed: Sequence[str] = (),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """``passed``: further variables the client hands to a container by name (``--env``)."""
        self.executable = tuple(executable)
        self.env = docker_environment(environ) | {
            name: environ[name] for name in passed if name in environ
        }
        self.clock = clock

    def _quiet(self, arguments: Sequence[str], timeout_s: float) -> Bounded | None:
        with contextlib.suppress(OSError):
            return run_bounded(
                [*self.executable, *arguments], env=self.env, timeout_s=timeout_s, max_bytes=_SMALL
            )
        return None

    def stop(self, name: str) -> bool:
        """Kills container ``name``; whether it is seen stopped, within ``KILL_TIMEOUT_S``.

        The documentation of ``docker kill`` gives no exit code (docs.docker.com, read on
        2026-11-28): 0 is taken as done; any other answer in time (the container may have ended
        meanwhile, ``--rm`` removing it) is checked by ``docker ps``, which lists running
        containers only. No answer, or a client that cannot start, confirms nothing."""
        end = self.clock() + KILL_TIMEOUT_S
        killed = self._quiet(["kill", name], KILL_TIMEOUT_S)
        if killed is None or killed.timed_out:
            return False
        if killed.returncode == 0:
            return True
        left = end - self.clock()
        if left <= 0:
            return False
        listed = self._quiet(["ps", "--quiet", "--filter", f"name={name}"], left)
        return (
            listed is not None
            and not listed.timed_out
            and listed.returncode == 0
            and not listed.stdout.strip()
        )

    def run(
        self, arguments: Sequence[str], *, name: str, timeout_s: float, max_bytes: int
    ) -> Bounded:
        """Past the time or output limit, container ``name`` is killed and ``stopped`` says
        whether that was confirmed. An empty ``name``: a command that starts no container."""
        try:
            out = run_bounded(
                [*self.executable, *arguments],
                env=self.env,
                timeout_s=timeout_s,
                max_bytes=max_bytes,
            )
        except OSError as exc:
            raise SandboxError(f"Docker ne peut pas être lancé ({type(exc).__name__})") from None
        if name and (out.timed_out or out.truncated):
            # --rm removes the container once killed.
            return dataclasses.replace(out, stopped=self.stop(name))
        return out
