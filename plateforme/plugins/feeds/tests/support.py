"""Offline doubles for the feeds tests: builders of RSS 2.0 and Atom 1.0 feeds (texts invented),
a fixed allow-list and a reader that never reaches the network.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from xml.sax.saxutils import escape

from plugins.feeds.allowlist import FeedSource
from plugins.feeds.models import FeedError

FIXED_NOW = datetime(2026, 10, 22, 9, 30, tzinfo=UTC)
STAMP = "2026-10-22T09:30:00+00:00"
FEED_URL = "https://feeds.example/research.xml"


def source(feed_id: str = "exemple", **fields: str) -> FeedSource:
    values = {
        "id": feed_id,
        "titre": "Flux d'exemple",
        "url": FEED_URL,
        "licence": "CC BY 4.0",
        "frequence": "quotidienne",
        **fields,
    }
    return FeedSource.model_validate(values)


CATALOG: Mapping[str, FeedSource] = {
    "exemple": source(),
    "licence-a-verifier": source("licence-a-verifier", licence="A_VERIFIER"),
    "frequence-a-definir": source("frequence-a-definir", frequence="A_DEFINIR"),
}


@dataclass
class FakeReader:
    """Returns ``body`` for every URL, or raises ``error``; keeps the URLs asked for."""

    body: bytes = b""
    error: str | None = None
    urls: list[str] = field(default_factory=list)

    async def fetch(self, raw_url: str) -> bytes:
        self.urls.append(raw_url)
        if self.error is not None:
            raise FeedError(self.error)
        return self.body


def _element(tag: str, value: str | None) -> str:
    return "" if value is None else f"<{tag}>{escape(value)}</{tag}>"


def rss_item(
    title: str | None = "Titre",
    link: str | None = "https://feeds.example/a",
    pub_date: str | None = "Tue, 21 Oct 2026 08:00:00 GMT",
    description: str | None = "Résumé",
    extra: str = "",
) -> str:
    parts = (
        _element("title", title),
        _element("link", link),
        _element("pubDate", pub_date),
        _element("description", description),
    )
    return f"<item>{''.join(parts)}{extra}</item>"


def rss(items: Sequence[str], title: str | None = "Flux RSS", extra_ns: str = "") -> bytes:
    channel = _element("title", title) + "".join(items)
    return (
        f'<?xml version="1.0" encoding="utf-8"?><rss version="2.0"{extra_ns}>'
        f"<channel>{channel}</channel></rss>"
    ).encode()


def atom_entry(
    title: str | None = "Titre",
    href: str | None = "https://feeds.example/a",
    published: str | None = "2026-10-21T08:00:00Z",
    summary: str | None = "Résumé",
    extra: str = "",
) -> str:
    link = "" if href is None else f'<link href="{escape(href)}"/>'
    parts = (
        _element("title", title),
        link,
        _element("published", published),
        _element("summary", summary),
    )
    return f"<entry>{''.join(parts)}{extra}</entry>"


def atom(entries: Sequence[str], title: str | None = "Flux Atom") -> bytes:
    body = _element("title", title) + "".join(entries)
    return (
        f'<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
        f"{body}</feed>"
    ).encode()
