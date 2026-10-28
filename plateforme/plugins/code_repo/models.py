"""Outputs of the ``code_repo`` tools. Every text taken from a repository (code, commit messages,
author names, paths) is untrusted data (R5): bounded, secrets masked, invisible characters shown or
dropped, never instructions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

MAX_COMMITS = 50
MAX_LINES = 400
Kind = Literal["file", "directory", "symlink", "submodule", "other"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Commit(_Out):
    sha: str
    # Name only: the e-mail address stays in the repository.
    author: str
    # ISO 8601, as the author's clock wrote it.
    date: str
    subject: str


class LogResult(_Out):
    repo: str
    rev: str
    commits: list[Commit]
    # More commits follow the last one shown.
    more_commits: bool
    # Secret-looking strings replaced by [MASQUÉ] in the subjects.
    masked: int


class ChangedFile(_Out):
    path: str
    # None for a binary file.
    added: int | None
    deleted: int | None


class DiffResult(_Out):
    repo: str
    base: str
    head: str
    base_sha: str
    head_sha: str
    files: list[ChangedFile]
    more_files: int
    # Sensitive files (R6) that changed: named, never shown.
    withheld: list[str]
    patch: str
    patch_truncated: bool
    masked: int
    note: str | None


class Entry(_Out):
    name: str
    kind: Kind
    # Bytes, for a file.
    size: int | None
    # A sensitive name (R6): repo_file refuses to read it.
    withheld: bool


class FileResult(_Out):
    repo: str
    rev: str
    sha: str
    path: str
    kind: Literal["file", "directory"]
    size: int | None
    # For a file: its line count and the slice shown.
    total_lines: int | None
    start_line: int | None
    end_line: int | None
    content: str | None
    content_truncated: bool
    masked: int
    # For a directory.
    entries: list[Entry]
    more_entries: int
