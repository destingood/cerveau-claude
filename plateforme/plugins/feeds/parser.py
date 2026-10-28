"""RSS 2.0 and Atom 1.0 parser on ``defusedxml`` (D17).

DTDs are refused, so no entity is expanded and no external reference is fetched (XXE, "billion
laughs"). Only what CERVEAU needs is read from each entry: title, link, date and summary; full
contents (``content:encoded``, ``atom:content``) are ignored (D12). Texts are cleaned and bounded
(``core.net.text``), links are kept only if they are plain http(s) URLs, and none is followed.

Dates are compared in UTC; a date without a zone counts as UTC. With ``since``, an entry is kept
only if its date is that day or later, so an undated entry is left out (prudence, as in
``scholarly``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from xml.etree.ElementTree import Element, ParseError

import httpx
from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

from core.net.guard import FetchError, check_url
from core.net.text import clean_text, clip, strip_markup
from plugins.feeds.models import FeedEntry, FeedError

MAX_TITLE_CHARS = 500
MAX_SUMMARY_CHARS = 1_000
MAX_LINK_CHARS = 2_000

_ATOM = "{http://www.w3.org/2005/Atom}"
_DC = "{http://purl.org/dc/elements/1.1/}"

# An entry and its date in UTC, if the feed gives a usable one.
Dated = tuple[FeedEntry, datetime | None]


@dataclass(frozen=True)
class ParsedFeed:
    title: str | None
    entries: list[FeedEntry]
    skipped: int
    more_entries: int


def _text(node: Element | None) -> str:
    """All the text of an element, children included (Atom ``xhtml`` content)."""
    return "".join(node.itertext()) if node is not None else ""


def _title(node: Element | None) -> str | None:
    return strip_markup(_text(node))[:MAX_TITLE_CHARS] or None


def _summary(node: Element | None) -> tuple[str | None, bool]:
    summary, cut = clip(strip_markup(_text(node)), MAX_SUMMARY_CHARS)
    return summary or None, cut


def _link(raw: str, base: str) -> str | None:
    value = clean_text(raw)
    if not value:
        return None
    try:
        url = check_url(str(httpx.URL(base).join(value)))
    except (FetchError, httpx.InvalidURL):
        return None
    shown = str(url)
    return shown if len(shown) <= MAX_LINK_CHARS else None


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _rfc822(raw: str) -> datetime | None:
    try:
        return _utc(parsedate_to_datetime(raw.strip()))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _iso(raw: str) -> datetime | None:
    try:
        return _utc(datetime.fromisoformat(raw.strip()))
    except (ValueError, OverflowError):
        return None


def _rss_entry(item: Element, base: str) -> Dated:
    published = _rfc822(item.findtext("pubDate") or "") or _iso(item.findtext(f"{_DC}date") or "")
    link = _link(item.findtext("link") or "", base)
    guid = item.find("guid")
    if link is None and guid is not None and guid.get("isPermaLink", "true") != "false":
        link = _link(guid.text or "", base)
    summary, cut = _summary(item.find("description"))
    return _entry(_title(item.find("title")), link, published, summary, cut), published


def _atom_entry(entry: Element, base: str) -> Dated:
    published = _iso(entry.findtext(f"{_ATOM}published") or "") or _iso(
        entry.findtext(f"{_ATOM}updated") or ""
    )
    link = next(
        (
            _link(node.get("href", ""), base)
            for node in entry.findall(f"{_ATOM}link")
            if node.get("rel", "alternate") == "alternate"
        ),
        None,
    )
    summary, cut = _summary(entry.find(f"{_ATOM}summary"))
    return _entry(_title(entry.find(f"{_ATOM}title")), link, published, summary, cut), published


def _entry(
    title: str | None, link: str | None, published: datetime | None, summary: str | None, cut: bool
) -> FeedEntry:
    return FeedEntry(
        title=title,
        link=link,
        published=published.isoformat(timespec="seconds") if published else None,
        summary=summary,
        summary_truncated=cut,
    )


def _items(root: Element, base: str) -> tuple[str | None, Iterable[Dated]]:
    if root.tag == "rss":
        channel = root.find("channel")
        if channel is None:
            raise FeedError("flux RSS sans canal")
        items = channel.findall("item")
        return _title(channel.find("title")), (_rss_entry(item, base) for item in items)
    if root.tag == f"{_ATOM}feed":
        entries = root.findall(f"{_ATOM}entry")
        return _title(root.find(f"{_ATOM}title")), (_atom_entry(e, base) for e in entries)
    raise FeedError("format non pris en charge (RSS 2.0 ou Atom 1.0 seulement)")


def parse_feed(body: bytes, base: str, since: date | None, limit: int) -> ParsedFeed:
    """The first ``limit`` usable entries on or after ``since``, in the order of the feed."""
    try:
        root = fromstring(body, forbid_dtd=True)
    except (ParseError, DefusedXmlException):
        raise FeedError("flux illisible (XML invalide ou refusé)") from None
    title, items = _items(root, base)
    kept: list[FeedEntry] = []
    skipped = 0
    for entry, published in items:
        usable = entry.title is not None or entry.summary is not None
        recent = since is None or (published is not None and published.date() >= since)
        if usable and recent:
            kept.append(entry)
        else:
            skipped += 1
    return ParsedFeed(title, kept[:limit], skipped, max(0, len(kept) - limit))
