"""Throwaway git repositories for the code pack tests, built in tmp_path with no user or system
configuration (no hook, no signing, no line-ending conversion)."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from core.code.git import git_environment
from core.config.loader import CodeRepository

GIT_ENV = {
    **git_environment(os.environ),
    "GIT_AUTHOR_DATE": "2026-10-20T10:00:00+02:00",
    "GIT_COMMITTER_DATE": "2026-10-20T10:00:00+02:00",
}
IDENTITY = ("-c", "user.name=Lucas Test", "-c", "user.email=lucas@example.test")


def git(
    repo: Path, *args: str, stdin: bytes | None = None, env: Mapping[str, str] = GIT_ENV
) -> str:
    result = subprocess.run(
        ["git", *IDENTITY, "-c", "commit.gpgsign=false", "-C", str(repo), *args],
        input=stdin,
        env=dict(env),
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("utf-8")


def commit(repo: Path, files: Mapping[str, str | bytes], message: str) -> str:
    """Write the files (exact bytes, LF kept), stage them and commit; the new commit's hash."""
    for name, content in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        git(repo, "add", "--", name)
    git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


def make_repo(root: Path, files: Mapping[str, str | bytes], message: str = "initial") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    commit(root, files, message)
    return root


def add_entry(repo: Path, mode: str, sha: str, path: str, message: str) -> None:
    """Commit a raw tree entry (a symbolic link or a submodule) without touching the disk."""
    git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{sha},{path}")
    git(repo, "commit", "-q", "-m", message)


def blob(repo: Path, content: bytes) -> str:
    return git(repo, "hash-object", "-w", "--stdin", stdin=content).strip()


def listed(repo_id: str, path: Path, **extra: object) -> CodeRepository:
    return CodeRepository.model_validate({"id": repo_id, "path": str(path), **extra})
