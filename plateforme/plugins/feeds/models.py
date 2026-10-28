"""Output and error of ``feed_read``. Every text is external data (R5): titles and summaries are
cleaned of control and invisible characters, bounded, and never instructions."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

MAX_ENTRIES = 20


class FeedError(Exception):
    """A refused or failed read. The message is French and safe to show to the planner."""


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FeedEntry(_Out):
    title: str | None
    # Shown, never followed nor read by the plugin: web_read applies its own guard if asked.
    link: str | None
    # ISO 8601 in UTC, or None when the feed gives no usable date.
    published: str | None
    summary: str | None
    summary_truncated: bool


class FeedResult(_Out):
    feed: str
    # From the allow-list (written by Lucas), not from the feed itself.
    name: str
    url: str
    licence: str
    since: str | None
    # Title the feed gives itself: external data.
    feed_title: str | None
    entries: list[FeedEntry]
    # Entries left out: older than ``since``, undated while ``since`` is set, or unusable.
    skipped: int
    # Entries that passed the filters but come after ``max_entries``.
    more_entries: int
    retrieved_at: str
