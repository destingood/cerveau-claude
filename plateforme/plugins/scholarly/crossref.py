"""Crossref REST API: search of works and lookup by DOI (ADR-044).

Public pool, without the ``mailto`` of the polite pool (D11): no e-mail address leaves the
machine. The pool announced 1 request per second and 1 concurrent request in its headers on
2026-10-21 (``x-rate-limit-*``, ``x-concurrency-limit``); 429 means too fast, 403 a block.
Bibliographic metadata are facts free of restriction; abstracts remain under the copyright of
their publishers or authors, so they are only shown, cut short, and never stored (no cache).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

from core.net.text import clean_text, clip, strip_markup
from plugins.scholarly.common import (
    MAX_NAME_CHARS,
    MAX_TITLE_CHARS,
    MAX_VENUE_CHARS,
    Fetcher,
    PartialDate,
    ScholarError,
    first_date,
    on_or_after,
    utcnow,
)
from plugins.scholarly.models import MAX_AUTHORS, ScholarRecord, Update

ENDPOINT = "https://api.crossref.org/works"
INTERVAL_S = 1.0
MAX_ABSTRACT_CHARS = 1_000
MAX_UPDATES = 10
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
_DOT_SEGMENTS = frozenset({".", ".."})
SELECT = ",".join(
    (
        "DOI",
        "title",
        "author",
        "issued",
        "published",
        "posted",
        "container-title",
        "type",
        "abstract",
        "update-to",
        "updated-by",
    )
)
PREPRINT_TYPES = frozenset({"posted-content"})
_DATE_FIELDS = ("issued", "published", "posted")


def valid_doi(doi: str) -> bool:
    """A modern DOI (the pattern Crossref recommends) with no « . » or « .. » segment: once in
    the address of the API, such a segment would reach another of its paths."""
    return DOI_RE.fullmatch(doi) is not None and not _DOT_SEGMENTS.intersection(doi.split("/"))


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_str(value: object) -> str:
    return next((clean_text(v) for v in _list(value) if isinstance(v, str) and v.strip()), "")


def _date(value: object) -> PartialDate | None:
    if not isinstance(value, Mapping):
        return None
    parts = _list(value.get("date-parts"))
    return PartialDate.of(_list(parts[0])) if parts else None


def _author(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    name = " ".join(p for p in (_str(value.get("given")), _str(value.get("family"))) if p)
    return clean_text(name or _str(value.get("name")))[:MAX_NAME_CHARS]


def _updates(value: object) -> list[Update]:
    updates = []
    for item in _list(value):
        if not isinstance(item, Mapping):
            continue
        kind, doi = clean_text(_str(item.get("type")))[:60], _str(item.get("DOI")).strip()
        if kind and valid_doi(doi):
            updates.append(Update(type=kind, doi=doi))
    return updates[:MAX_UPDATES]


def parse_work(work: object, since: date | None, retrieved_at: str) -> ScholarRecord | None:
    """One work of the API; None if it has no usable DOI or title, or appeared before ``since``."""
    if not isinstance(work, Mapping):
        return None
    doi = _str(work.get("DOI")).strip()
    title = _first_str(work.get("title"))[:MAX_TITLE_CHARS]
    first = first_date(_date(work.get(field)) for field in _DATE_FIELDS)
    if not valid_doi(doi) or not title or not on_or_after(first, since):
        return None
    names = [name for name in map(_author, _list(work.get("author"))) if name]
    abstract, truncated = clip(strip_markup(_str(work.get("abstract"))), MAX_ABSTRACT_CHARS)
    kind = clean_text(_str(work.get("type")))[:60] or "inconnu"
    return ScholarRecord(
        source="crossref",
        identifier=doi,
        type=kind,
        preprint=kind in PREPRINT_TYPES,
        title=title,
        authors=names[:MAX_AUTHORS],
        more_authors=max(0, len(names) - MAX_AUTHORS),
        published=first.iso() if first else None,
        updated=None,
        venue=_first_str(work.get("container-title"))[:MAX_VENUE_CHARS] or None,
        doi=doi,
        url=f"https://doi.org/{quote(doi, safe='/')}",
        abstract=abstract or None,
        abstract_truncated=truncated,
        update_to=_updates(work.get("update-to")),
        updated_by=_updates(work.get("updated-by")),
        retrieved_at=retrieved_at,
    )


def _message(body: bytes, kind: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        raise ScholarError("Crossref : réponse illisible (JSON invalide)") from None
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, dict) or payload.get("message-type") != kind:
        raise ScholarError("Crossref : réponse inattendue")
    return message


class CrossrefSource:
    name = "crossref"

    def __init__(self, fetcher: Fetcher, now: Callable[[], datetime] = utcnow) -> None:
        self.fetcher, self.now = fetcher, now

    def _stamp(self) -> str:
        return self.now().isoformat(timespec="seconds")

    async def search(self, query: str, since: date | None, max_results: int) -> list[ScholarRecord]:
        params: dict[str, str | int] = {"query": query, "rows": max_results, "select": SELECT}
        if since is not None:
            params["filter"] = f"from-pub-date:{since.isoformat()}"
        reply = await self.fetcher.get(
            ENDPOINT, params, accept="application/json", read_statuses=frozenset({200})
        )
        if reply.media != "application/json":
            raise ScholarError("Crossref : type de contenu inattendu")
        stamp = self._stamp()
        works = _list(_message(reply.body, "work-list").get("items"))
        records = [parse_work(work, since, stamp) for work in works]
        return [record for record in records if record is not None][:max_results]

    async def record(self, doi: str) -> ScholarRecord:
        reply = await self.fetcher.get(
            f"{ENDPOINT}/{quote(doi, safe='/')}",
            None,
            accept="application/json",
            read_statuses=frozenset({200, 404}),
        )
        if reply.status == 404:
            raise ScholarError("Crossref : DOI inconnu")
        if reply.media != "application/json":
            raise ScholarError("Crossref : type de contenu inattendu")
        record = parse_work(_message(reply.body, "work"), None, self._stamp())
        if record is None:
            raise ScholarError("Crossref : notice inutilisable (DOI ou titre absent)")
        return record
