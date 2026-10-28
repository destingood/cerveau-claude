"""arXiv API (Atom 1.0): search and lookup by identifier (ADR-044).

Terms of use of the API (https://info.arxiv.org/help/api/tou.html, read on 2026-10-21): one
request every 3 s and one connection at a time for all the machines of a user; the metadata are
CC0, the full text is not redistributed (only the abstract is returned, D12).

The planner's words become ``all:`` terms joined by ``AND``: only letters and digits are kept,
in lower case, so no field prefix, parenthesis or operator of the arXiv syntax can be injected.
The XML is parsed by ``defusedxml`` with DTDs refused (no entity, no external reference).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

from core.net.text import clean_text, clip
from plugins.scholarly.common import (
    MAX_NAME_CHARS,
    MAX_TITLE_CHARS,
    MAX_VENUE_CHARS,
    Fetcher,
    PartialDate,
    ScholarError,
    on_or_after,
    utcnow,
)
from plugins.scholarly.models import MAX_AUTHORS, ScholarRecord

ENDPOINT = "https://export.arxiv.org/api/query"
INTERVAL_S = 3.0
MAX_WORDS = 12
MAX_ABSTRACT_CHARS = 2_000
ATOM_TYPES = frozenset({"application/atom+xml", "application/xml", "text/xml"})

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_NEW_ID = re.compile(r"\d{4}\.\d{4,5}(?:v\d+)?")
_OLD_ID = re.compile(r"[a-z]+(?:-[a-z]+)*(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?")
_ABS_URL = re.compile(r"https?://arxiv\.org/abs/")
_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
_WORD = re.compile(r"[^\W_]+")
_ERROR_MARK = "arxiv.org/api/errors#"


def is_arxiv_id(value: str) -> bool:
    return bool(_NEW_ID.fullmatch(value) or _OLD_ID.fullmatch(value))


def search_query(query: str, since: date | None, now: datetime) -> str:
    # Lower case first: some letters lower to a letter plus a combining mark (İ -> i̇).
    words = _WORD.findall(query.lower())[:MAX_WORDS]
    if not words:
        raise ScholarError("requête refusée : aucun mot cherchable (lettres ou chiffres)")
    terms = [f"all:{word}" for word in words]
    if since is not None:
        terms.append(f"submittedDate:[{since:%Y%m%d}0000 TO {now:%Y%m%d%H%M}]")
    return " AND ".join(terms)


def _text(entry: Element, tag: str) -> str:
    node = entry.find(tag)
    return (node.text or "") if node is not None else ""


def _day(raw: str) -> PartialDate | None:
    try:
        day = date.fromisoformat(raw.strip()[:10])
    except ValueError:
        return None
    return PartialDate(day.year, day.month, day.day)


def _record(entry: Element, since: date | None, retrieved_at: str) -> ScholarRecord | None:
    identifier = _ABS_URL.sub("", _text(entry, f"{_ATOM}id").strip(), count=1)
    published = _day(_text(entry, f"{_ATOM}published"))
    title = clean_text(_text(entry, f"{_ATOM}title"))[:MAX_TITLE_CHARS]
    # An entry without a title or a submission date is not a record (unknown identifier).
    if not is_arxiv_id(identifier) or not title or published is None:
        return None
    if not on_or_after(published, since):
        return None
    names = [clean_text(_text(a, f"{_ATOM}name")) for a in entry.findall(f"{_ATOM}author")]
    names = [name[:MAX_NAME_CHARS] for name in names if name]
    abstract, truncated = clip(clean_text(_text(entry, f"{_ATOM}summary")), MAX_ABSTRACT_CHARS)
    updated = _day(_text(entry, f"{_ATOM}updated"))
    venue = clean_text(_text(entry, f"{_ARXIV}journal_ref"))[:MAX_VENUE_CHARS]
    doi = _text(entry, f"{_ARXIV}doi").strip()
    return ScholarRecord(
        source="arxiv",
        identifier=identifier,
        type="preprint",
        preprint=True,
        title=title,
        authors=names[:MAX_AUTHORS],
        more_authors=max(0, len(names) - MAX_AUTHORS),
        published=published.iso(),
        updated=updated.iso() if updated else None,
        venue=venue or None,
        doi=doi if _DOI.fullmatch(doi) else None,
        url=f"https://arxiv.org/abs/{identifier}",
        abstract=abstract or None,
        abstract_truncated=truncated,
        update_to=[],
        updated_by=[],
        retrieved_at=retrieved_at,
    )


def parse_feed(body: bytes, since: date | None, retrieved_at: str) -> list[ScholarRecord]:
    """Records of an Atom feed of the API; an error entry of arXiv is a ``ScholarError``."""
    try:
        root = fromstring(body, forbid_dtd=True)
    except (ParseError, DefusedXmlException):
        raise ScholarError("arXiv : réponse illisible (XML invalide ou refusé)") from None
    if root.tag != f"{_ATOM}feed":
        raise ScholarError("arXiv : réponse inattendue (pas un flux Atom)")
    records = []
    for entry in root.findall(f"{_ATOM}entry"):
        if _ERROR_MARK in _text(entry, f"{_ATOM}id"):
            raise ScholarError("arXiv : requête refusée (identifiant ou syntaxe invalide)")
        record = _record(entry, since, retrieved_at)
        if record is not None:
            records.append(record)
    return records


class ArxivSource:
    name = "arxiv"

    def __init__(self, fetcher: Fetcher, now: Callable[[], datetime] = utcnow) -> None:
        self.fetcher, self.now = fetcher, now

    async def _feed(self, params: dict[str, str | int], since: date | None) -> list[ScholarRecord]:
        reply = await self.fetcher.get(
            ENDPOINT,
            params,
            accept="application/atom+xml",
            read_statuses=frozenset({200, 400}),
        )
        if reply.media not in ATOM_TYPES:
            raise ScholarError("arXiv : type de contenu inattendu")
        records = parse_feed(reply.body, since, self.now().isoformat(timespec="seconds"))
        if reply.status != 200:
            raise ScholarError("arXiv : requête refusée (HTTP 400)")
        return records

    async def search(self, query: str, since: date | None, max_results: int) -> list[ScholarRecord]:
        params: dict[str, str | int] = {
            "search_query": search_query(query, since, self.now()),
            "start": 0,
            "max_results": max_results,
        }
        if since is not None:
            params |= {"sortBy": "submittedDate", "sortOrder": "descending"}
        return (await self._feed(params, since))[:max_results]

    async def record(self, identifier: str) -> ScholarRecord:
        records = await self._feed({"id_list": identifier, "max_results": 1}, None)
        if not records:
            raise ScholarError("arXiv : identifiant inconnu")
        return records[0]
