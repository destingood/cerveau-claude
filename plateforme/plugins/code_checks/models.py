"""Outputs of the ``code_checks`` tool. Counts come from ruff and pytest (R1); paths, messages and
test names come from an untrusted repository (R5): bounded, secrets masked, invisible characters
shown, never instructions. A hostile repository can also fake its own results: only the
confinement of its code is guaranteed (ADR-048)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

MAX_SHOWN = 50
# ok: nothing to report; echec: violations, files to reformat or failed tests; erreur: the check
# ran but its result cannot be read; aucun_test: pytest collected nothing; non_lance: not run;
# delai: stopped at the time limit.
Status = Literal["ok", "echec", "erreur", "aucun_test", "non_lance", "delai"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Diagnostic(_Out):
    path: str
    line: int | None
    column: int | None
    code: str
    message: str


class RuffCheck(_Out):
    status: Status
    note: str | None
    # None when ruff did not run or its output could not be read.
    count: int | None
    # Rule -> diagnostics, most frequent first.
    by_code: dict[str, int]
    diagnostics: list[Diagnostic]
    more_diagnostics: int


class RuffFormat(_Out):
    status: Status
    note: str | None
    count: int | None
    # Files ruff would reformat.
    files: list[str]
    more_files: int


class Pytest(_Out):
    status: Status
    note: str | None
    # Outcome -> count, as pytest printed them (passed, failed, errors, skipped...).
    counts: dict[str, int]
    failed: list[str]
    errors: list[str]
    more_failures: int


class Source(_Out):
    """The throwaway copy the containers read."""

    files: int
    bytes: int
    # Sensitive files (R6): named, never copied.
    withheld: list[str]
    more_withheld: int
    # Symbolic links, submodules, paths not portable or colliding without case.
    skipped: list[str]
    more_skipped: int
    # The copy was deleted after the checks.
    removed: bool


class ChecksResult(_Out):
    repo: str
    rev: str
    sha: str
    source: Source
    ruff_check: RuffCheck
    ruff_format: RuffFormat
    pytest: Pytest
    # Seconds shared by the containers of this call.
    budget_seconds: float
