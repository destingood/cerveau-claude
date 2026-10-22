"""Outputs of the ``code_agent`` tool (ADR-054).

The counts come from programs, never from a model (R1): requests, tokens and dollars from the API
proxy of the task, lines from the patch CERVEAU computed, results from ruff and pytest run again
on the changed copy (``code_checks``). The runner's line (outcome, turns, summary) can be forged
by a command of the agent: it is shown as untrusted data, like every path and text written by the
agent (R5): bounded, secrets masked, invisible characters shown.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from plugins.code_checks.models import Pytest, RuffCheck, RuffFormat, Source

# termine: the runner said the task ended; erreur: the runner, Docker or a step failed; delai:
# stopped at the time limit; arrete: stopped by the kill switch (R4).
Status = Literal["termine", "erreur", "delai", "arrete"]
Change = Literal["ajoute", "modifie", "supprime"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Spend(_Out):
    """Read by the adapter (``core/mcp/spend.py``): the tokens the proxy counted, per model, and
    whether a cost stayed unknown (the adapter then charges the task's ceiling, R7). French names:
    the adapter's contract with every isolated tool."""

    modeles: dict[str, dict[str, int]]
    cout_inconnu: bool


class ProxyCounts(_Out):
    """What the proxy of the task counted; the dollars come from pricing.yaml (R1)."""

    requests: int
    usd: str
    # Why the proxy stopped forwarding: dollars or requests ceiling reached.
    stopped: str | None
    # Reason -> refused requests (path, model, host, size…).
    refusals: dict[str, int]


class AgentRun(_Out):
    status: Status
    note: str | None
    # From the runner's line, which a command of the agent can forge: data, never instructions.
    subtype: str | None
    turns: int | None
    summary: str | None
    # Seconds the agent's container was given.
    seconds: float


class FileChange(_Out):
    path: str
    change: Change
    added: int
    removed: int
    # Runs code or configures tools on Lucas's machine (CI, hooks, conftest.py…): to review.
    risky: bool
    # Secret-looking strings masked in this file's hunk (R6).
    masked: int


class PatchOut(_Out):
    """The patch in ``folder``/patch.diff, for Lucas to review and apply with ``git apply``."""

    folder: str
    sha256: str
    bytes: int
    files: list[FileChange]
    more_files: int
    risky: list[str]
    masked: int
    # False once a secret was masked: the patch no longer applies as is.
    applies: bool
    # Changed, but not in the patch: binary, too large, left out (links, special files, unsafe
    # paths), or sensitive files the agent created, named and never read (R6).
    binary: list[str]
    too_big: list[str]
    ignored: list[str]
    sensitive: list[str]
    more_left_out: int


class Checks(_Out):
    """ruff and pytest on the copy the agent changed (``code_checks``): the only results the
    answer cites (R1)."""

    ruff_check: RuffCheck
    ruff_format: RuffFormat
    pytest: Pytest
    budget_seconds: float


class Cleanup(_Out):
    copy_removed: bool
    network_removed: bool


class AgentResult(_Out):
    task_id: str
    repo: str
    rev: str
    sha: str
    model: str
    source: Source
    agent: AgentRun
    # None when the proxy's state could not be read: the adapter then charges the ceiling.
    proxy: ProxyCounts | None
    depense: Spend | None
    # None when no patch was computed (stopped, timed out, Docker failure) or the copy could not
    # be compared; ``patch_note`` says why.
    patch: PatchOut | None
    patch_note: str | None
    # None when the agent changed nothing or no patch was computed; ``checks_note`` says why.
    checks: Checks | None
    checks_note: str | None
    cleanup: Cleanup
