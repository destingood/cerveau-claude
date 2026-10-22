"""Results of ruff and pytest read from their output (R1: the counts come from the tools).

``ruff check`` and ``ruff format --check`` print a JSON list with ``--output-format=json``
(checked with ruff 0.17.1). pytest is read from its terminal summary with ``-q -rfE --tb=no``:
the last line ``1 failed, 2 passed in 0.12s`` and one ``FAILED <id>`` or ``ERROR <id>`` line per
failure. The text after `` - `` on those lines is the exception message, written by the code under
test: it is dropped. Paths and test names stay untrusted data (R5): the caller shows them through
``core.code.text``.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

WORKDIR = "/work"
# pytest names an error "error" or "errors" and a warning "warning" or "warnings".
_OUTCOMES = {
    "passed": "passed",
    "failed": "failed",
    "error": "errors",
    "errors": "errors",
    "skipped": "skipped",
    "xfailed": "xfailed",
    "xpassed": "xpassed",
    "deselected": "deselected",
    "warning": "warnings",
    "warnings": "warnings",
}
_SUMMARY = re.compile(
    r"^=*\s*(?P<body>no tests ran|\d+ [a-z]+(?:, \d+ [a-z]+)*) in [0-9.]+s(?: \([^)]*\))?\s*=*$"
)
_COUNT = re.compile(r"(\d+) ([a-z]+)")
_FAILURE = re.compile(r"^(?P<kind>FAILED|ERROR) (?P<id>.+?)(?: - .*)?$")


class ChecksError(Exception):
    """A tool output that cannot be read. The message is French and safe to show."""


class _Location(BaseModel):
    model_config = ConfigDict(extra="ignore")
    row: int
    column: int


class _RuffItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    filename: str
    # None for a syntax error.
    code: str | None
    message: str
    location: _Location | None


_RUFF = TypeAdapter(list[_RuffItem])


@dataclass(frozen=True)
class Diagnostic:
    path: str
    line: int | None
    column: int | None
    code: str
    message: str


@dataclass(frozen=True)
class PytestSummary:
    # Outcome -> count, as pytest printed them; empty when no summary line was found.
    counts: dict[str, int]
    failed: tuple[str, ...]
    errors: tuple[str, ...]
    summary_found: bool


def _relative(filename: str) -> str:
    return filename.removeprefix(f"{WORKDIR}/")


def parse_ruff(stdout: bytes) -> tuple[Diagnostic, ...]:
    """Diagnostics of ``ruff check`` or ``ruff format --check`` in JSON."""
    try:
        items = _RUFF.validate_json(stdout)
    except ValidationError:
        raise ChecksError("sortie de ruff illisible") from None
    return tuple(
        Diagnostic(
            _relative(item.filename),
            item.location.row if item.location else None,
            item.location.column if item.location else None,
            item.code or "syntax-error",
            item.message,
        )
        for item in items
    )


def count_codes(diagnostics: tuple[Diagnostic, ...]) -> dict[str, int]:
    """Diagnostics per rule, most frequent first, then by code."""
    counts = Counter(diagnostic.code for diagnostic in diagnostics)
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


def parse_pytest(stdout: bytes) -> PytestSummary:
    """Counts of the last summary line and the identifiers of failed and erroneous tests."""
    counts: dict[str, int] = {}
    found = False
    failed: list[str] = []
    errors: list[str] = []
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if match := _FAILURE.match(line):
            (failed if match["kind"] == "FAILED" else errors).append(match["id"])
        elif match := _SUMMARY.match(line):
            found = True
            counts = {}
            for number, word in _COUNT.findall(match["body"]):
                if word in _OUTCOMES:
                    counts[_OUTCOMES[word]] = counts.get(_OUTCOMES[word], 0) + int(number)
    return PytestSummary(counts, tuple(failed), tuple(errors), found)
