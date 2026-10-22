"""Outputs of the ``code_ci`` tool. Identifiers, numbers, states and dates come from the GitHub API
and counts from the plugin (R1); workflow names, branches and titles come from an untrusted
repository (R5): bounded, secrets masked, invisible characters shown, never instructions."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

MAX_RUNS = 20


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Run(_Out):
    id: int
    run_number: int
    run_attempt: int | None
    workflow: str | None
    event: str
    # queued, in_progress, completed... as GitHub writes it; "non standard" for anything else.
    status: str | None
    # success, failure, cancelled... once completed, else None.
    conclusion: str | None
    branch: str | None
    head_sha: str
    title: str
    # ISO 8601, UTC, as GitHub writes it.
    created_at: str
    updated_at: str
    # Built from the allow list and the run identifier, never taken from the answer.
    url: str


class RateLimit(_Out):
    # GitHub's own counters for this IP address (60 requests per hour without a token).
    limit: int
    remaining: int
    reset_at: str


class CiRunsResult(_Out):
    repo: str
    github: str
    branch: str | None
    # Runs GitHub knows for this filter; at most ``MAX_RUNS`` are shown.
    total_count: int
    runs: list[Run]
    # Conclusion -> runs shown, most frequent first; "en_cours" for a run not completed.
    by_conclusion: dict[str, int]
    rate: RateLimit | None
    retrieved_at: str
