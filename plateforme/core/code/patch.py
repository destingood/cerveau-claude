"""Patch of the code agent's changes, computed by CERVEAU from the files (ADR-054).

The agent works on a throwaway copy of one commit. Once its container is gone, the files of the
copy are compared with the commit's blobs, read again from the repository's git objects; no git
command runs on whatever ``.git`` folder the agent may have written (same reason as ADR-047).

- The copy is scanned without following any link: a symbolic link, an NTFS junction, a FIFO or
  any other special file is listed and left out, so nothing outside the copy is ever read. The
  scan is bounded.
- ``.git`` folders and tool caches are skipped. Files the copy never had (sensitive, skipped by
  ``plan_copy``) are not compared: their absence is not a deletion.
- A new file with a sensitive name is never read (R6); one whose path is not portable, not plain
  ASCII or collides with an entry the copy left out is listed and left out.
- A text file gets a hunk in git's format (``git apply``); a binary or too large one is listed.
  Secret-looking strings are masked (R6): the patch then no longer applies as is, which the
  result says. The patch is data written by an untrusted agent (R5).
- Paths that run code or configure tools on Lucas's machine (CI, hooks, ``conftest.py``,
  ``pyproject.toml``…) are flagged for review.
"""

from __future__ import annotations

import difflib
import os
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core.code.repos import RepoError, check_path, is_sensitive
from core.code.sandbox import portable
from core.guardrails.secrets import mask_secrets

Change = Literal["ajoute", "modifie", "supprime"]
SKIPPED_DIRS = frozenset({".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"})
# Plain names only: git writes other paths quoted, which this patch does not do.
SAFE_PATH = re.compile(r"[A-Za-z0-9._@+-]+(?:/[A-Za-z0-9._@+-]+)*")
NEW_MODE = "100644"
NO_NEWLINE = "\\ No newline at end of file\n"
CONTEXT_LINES = 3
RISKY_DIRS = frozenset(
    {".github", ".claude", ".vscode", ".devcontainer", ".idea", ".husky", ".circleci", ".gitlab"}
)
RISKY_FILES = frozenset(
    {
        ".envrc",
        ".gitattributes",
        ".gitlab-ci.yml",
        ".gitmodules",
        ".mcp.json",
        ".npmrc",
        ".pre-commit-config.yaml",
        ".pypirc",
        ".coveragerc",
        ".ruff.toml",
        "agents.md",
        "claude.md",
        "compose.yaml",
        "conftest.py",
        "docker-compose.yml",
        "dockerfile",
        "gnumakefile",
        "makefile",
        "noxfile.py",
        "package.json",
        "pyproject.toml",
        "pytest.ini",
        "ruff.toml",
        "setup.cfg",
        "setup.py",
        "sitecustomize.py",
        "tox.ini",
        "usercustomize.py",
        "uv.lock",
    }
)
# Read by Python at start-up: a line of a .pth file can run code.
RISKY_SUFFIXES = (".pth",)
# What pip installs: requirements.txt, requirements-dev.txt...
REQUIREMENTS = ("requirements", ".txt")
# Files that set what ruff and pytest check or how: changed by the agent, the checks of the
# changed copy are no proof (ADR-054).
CHECK_FILES = frozenset(
    {
        ".coveragerc",
        ".ruff.toml",
        "conftest.py",
        "pyproject.toml",
        "pytest.ini",
        "ruff.toml",
        "setup.cfg",
        "sitecustomize.py",
        "tox.ini",
        "usercustomize.py",
    }
)


class PatchError(Exception):
    """The copy cannot be compared. The message is French and safe to show to the planner."""


@dataclass(frozen=True)
class BaseFile:
    mode: str
    content: bytes


@dataclass(frozen=True)
class FileChange:
    path: str
    change: Change
    added: int
    removed: int
    risky: bool
    masked: int


@dataclass(frozen=True)
class Patch:
    text: str
    changes: tuple[FileChange, ...]
    # Changed, but not in the text: binary, or too large (alone or past the patch's limit).
    binary: tuple[str, ...]
    too_big: tuple[str, ...]
    # Links, special files, unsafe or colliding paths: left out.
    ignored: tuple[str, ...]
    # Sensitive files the agent created: named, never read (R6).
    sensitive: tuple[str, ...]

    @property
    def masked(self) -> int:
        return sum(change.masked for change in self.changes)

    @property
    def risky(self) -> tuple[str, ...]:
        return tuple(change.path for change in self.changes if change.risky)


def is_risky(path: str) -> bool:
    segments = path.lower().split("/")
    name = segments[-1]
    return (
        any(segment in RISKY_DIRS for segment in segments[:-1])
        or name in RISKY_FILES
        or name.endswith(RISKY_SUFFIXES)
        or (name.startswith(REQUIREMENTS[0]) and name.endswith(REQUIREMENTS[1]))
    )


def sets_checks(path: str) -> bool:
    """Whether ``path`` sets what ruff or pytest check, or runs code at Python's start-up."""
    name = path.lower().rsplit("/", 1)[-1]
    return name in CHECK_FILES or name.endswith(RISKY_SUFFIXES)


def _skipped(path: str) -> bool:
    return any(segment in SKIPPED_DIRS for segment in path.split("/"))


def scan(root: Path, max_entries: int) -> tuple[dict[str, int], list[str]]:
    """Regular files of the copy with their size, and the other entries; links not followed."""
    files: dict[str, int] = {}
    others: list[str] = []
    pending = [""]
    seen = 0
    while pending:
        prefix = pending.pop()
        with os.scandir(root.joinpath(*prefix.split("/")) if prefix else root) as entries:
            for entry in entries:
                seen += 1
                if seen > max_entries:
                    raise PatchError(
                        f"copie de plus de {max_entries} entrées après l'agent : patch non calculé"
                    )
                path = f"{prefix}/{entry.name}" if prefix else entry.name
                if entry.is_symlink() or entry.is_junction():
                    others.append(path)
                elif entry.is_dir(follow_symlinks=False):
                    if entry.name not in SKIPPED_DIRS:
                        pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    files[path] = entry.stat(follow_symlinks=False).st_size
                else:
                    others.append(path)
    return files, others


def _lines(text: str) -> list[str]:
    """Lines cut at ``\\n`` only, as git does; ``str.splitlines`` also cuts at ``\\r``…"""
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _text(content: bytes) -> str | None:
    if b"\0" in content:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def file_diff(path: str, change: Change, old: str, new: str, mode: str) -> tuple[str, int, int]:
    """The diff of one file in git's format, with the lines it adds and removes."""
    header = [f"diff --git a/{path} b/{path}\n"]
    if change == "ajoute":
        header.append(f"new file mode {NEW_MODE}\n")
    elif change == "supprime":
        header.append(f"deleted file mode {mode}\n")
    before = "/dev/null" if change == "ajoute" else f"a/{path}"
    after = "/dev/null" if change == "supprime" else f"b/{path}"
    body: list[str] = []
    added = removed = 0
    lines = difflib.unified_diff(_lines(old), _lines(new), before, after, n=CONTEXT_LINES)
    for index, line in enumerate(lines):
        body.append(line)
        if index >= 2 and line.startswith("+"):
            added += 1
        elif index >= 2 and line.startswith("-"):
            removed += 1
        if not line.endswith("\n"):
            body.append("\n" + NO_NEWLINE)
    return "".join(header + body), added, removed


def _under(path: str, others: set[str]) -> bool:
    """The path, or one of its folders, became a link or a special file (listed already)."""
    segments = path.split("/")
    return any("/".join(segments[:end]) in others for end in range(1, len(segments) + 1))


def _new_path_ok(path: str, taken: set[str]) -> bool:
    try:
        check_path(path)
    except RepoError:
        return False
    return bool(SAFE_PATH.fullmatch(path)) and portable(path) and path.casefold() not in taken


def compute_patch(
    base: Mapping[str, BaseFile],
    reserved: Collection[str],
    root: Path,
    *,
    max_entries: int,
    max_file_bytes: int,
    max_read_bytes: int,
    max_patch_bytes: int,
) -> Patch:
    """Compare the copy at ``root`` with ``base``, the files it was written with.

    ``reserved``: entries of the commit the copy left out (sensitive, links, submodules…); a new
    file at one of these paths, case aside, is left out. ``max_read_bytes`` bounds what is read
    of changed files; past it, or past ``max_patch_bytes``, a changed file is listed as too big.
    """
    files, others = scan(root, max_entries)
    other_set = set(others)
    taken = {path.casefold() for path in reserved}
    parts: list[str] = []
    size = read = 0
    changes: list[FileChange] = []
    binary: list[str] = []
    too_big: list[str] = []
    ignored = sorted(others)
    sensitive: list[str] = []
    for path in sorted(set(base) | set(files)):
        original = base.get(path)
        if _skipped(path):
            continue
        if original is None and is_sensitive(path):
            sensitive.append(path)
            continue
        if original is None and not _new_path_ok(path, taken):
            ignored.append(path)
            continue
        if path not in files:
            if _under(path, other_set):
                continue
            change: Change = "supprime"
            content = b""
        else:
            target = root.joinpath(*path.split("/"))
            if (
                original is not None
                and files[path] == len(original.content)
                and target.read_bytes() == original.content
            ):
                continue
            if files[path] > max_file_bytes or read + files[path] > max_read_bytes:
                too_big.append(path)
                continue
            content = target.read_bytes()
            read += len(content)
            change = "ajoute" if original is None else "modifie"
        if not SAFE_PATH.fullmatch(path):
            ignored.append(path)
            continue
        old = "" if original is None else _text(original.content)
        new = _text(content)
        if old is None or new is None:
            binary.append(path)
            continue
        mode = NEW_MODE if original is None else original.mode
        diff, added, removed = file_diff(path, change, old, new, mode)
        diff, masked = mask_secrets(diff)
        encoded = len(diff.encode("utf-8"))
        if size + encoded > max_patch_bytes:
            too_big.append(path)
            continue
        size += encoded
        parts.append(diff)
        changes.append(FileChange(path, change, added, removed, is_risky(path), masked))
    return Patch(
        text="".join(parts),
        changes=tuple(changes),
        binary=tuple(binary),
        too_big=tuple(too_big),
        ignored=tuple(ignored),
        sensitive=tuple(sensitive),
    )
