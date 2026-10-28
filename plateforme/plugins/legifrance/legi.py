"""Pure parts of the Légifrance reader: identifiers, version dates and the parsing of replies.

Nothing here touches the network (ADR-059). Every text read from a reply is external content:
cleaned, clipped and returned as data, never as an instruction (R5). Whether a version applies on
a date is decided here, by code, from the ``dateDebut`` and ``dateFin`` the API returns (H3, R10):
a version applies on ``day`` when ``dateDebut <= day < dateFin``. The API gives these dates as
milliseconds since 1970 or as ISO text; both are read, as calendar days in UTC (A_VERIFIER on a
real call). An end on or after 2999-01-01 means an open version (A_VERIFIER).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from core.net.text import clean_text, clip, strip_markup

ARTICLE_ID = re.compile(r"LEGIARTI[0-9]{12}")
TEXT_ID = re.compile(r"LEGITEXT[0-9]{12}")
# Article numbers as Légifrance writes them: 1240, L121-1, R*123-4, 5-8, D. 12, Annexe I.
_NUM = re.compile(r"[0-9A-Za-z][0-9A-Za-z .*-]{0,29}")
_STATUS = re.compile(r"[A-Z_]{1,30}")
_MILLIS = re.compile(r"-?[0-9]{1,15}")
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_BREAK = re.compile(r"<br\s*/?>|</p\s*>|</div\s*>", re.IGNORECASE)
EPOCH = datetime(1970, 1, 1)
OPEN_END = date(2999, 1, 1)
QUERY_MAX = 200
NUM_MAX = 30
TEXT_MAX = 6000
TITLE_MAX = 300
EXTRACT_MAX = 300
# Deferred entry into force or repeal; repealed, cancelled or void versions (Légifrance states).
DEFERRED = frozenset({"VIGUEUR_DIFF", "ABROGE_DIFF"})
ENDED = frozenset({"ABROGE", "ANNULE", "PERIME", "MODIFIE_MORT_NE", "DISJOINT", "TRANSFERE"})
_REFUSED = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})


class LegiError(Exception):
    """A refused or failed read. The message is French and safe to show to the planner."""


def article_id(raw: str) -> str | None:
    """``raw`` if it is exactly ``LEGIARTI`` and 12 digits (no case or space folding)."""
    return raw if ARTICLE_ID.fullmatch(raw) else None


def text_id(raw: str) -> str | None:
    return raw if TEXT_ID.fullmatch(raw) else None


def article_num(raw: str) -> str | None:
    """An article number with its spaces collapsed, or None."""
    value = " ".join(raw.split())
    return value if _NUM.fullmatch(value) else None


def same_num(left: str, right: str) -> bool:
    """``L. 121-1`` and ``L121-1`` name the same article: spaces and dots are not significant."""

    def folded(value: str) -> str:
        return value.replace(" ", "").replace(".", "").casefold()

    return folded(left) == folded(right)


def query_text(raw: str) -> str | None:
    """A search query with its spaces collapsed; None if empty, too long or with a control,
    invisible format, surrogate, private use or unassigned character."""
    if any(unicodedata.category(char) in _REFUSED for char in raw.replace(" ", "")):
        return None
    value = " ".join(raw.split())
    return value if 1 <= len(value) <= QUERY_MAX else None


def calendar_day(raw: str) -> date | None:
    """A real calendar date written ``AAAA-MM-JJ``."""
    if _DAY.fullmatch(raw) is None:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def legi_date(value: object) -> date | None:
    """A day from milliseconds since 1970 (number or digits) or from ISO text; else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        if _MILLIS.fullmatch(value) is None:
            return calendar_day(value[:10])
        value = int(value)
    if not isinstance(value, int):
        return None
    try:
        return (EPOCH + timedelta(milliseconds=value)).date()
    except OverflowError:
        return None


def status(value: object) -> str | None:
    return value if isinstance(value, str) and _STATUS.fullmatch(value) else None


@dataclass(frozen=True)
class Window:
    """The days a version applies: from ``start`` included to ``end`` excluded (None: open)."""

    start: date
    end: date | None

    def covers(self, day: date) -> bool:
        return self.start <= day and (self.end is None or day < self.end)


def window(start: object, end: object) -> Window | None:
    """The window of a version; None when the start is unreadable, the end present but
    unreadable, or the end before the start."""
    first = legi_date(start)
    if first is None:
        return None
    if end is None:
        return Window(first, None)
    last = legi_date(end)
    if last is None or last < first:
        return None
    return Window(first, None if last >= OPEN_END else last)


def warnings(span: Window, state: str | None, day: date) -> list[str]:
    """Why a version must not be read as the law applying on ``day`` (H3); empty if it is."""
    found: list[str] = []
    if day < span.start:
        found.append(
            f"version future : en vigueur à partir du {span.start.isoformat()}, "
            f"pas au {day.isoformat()}"
        )
    elif span.end is not None and day >= span.end:
        found.append(
            f"version terminée le {span.end.isoformat()} : elle ne s'appliquait plus au "
            f"{day.isoformat()}"
        )
    if state in DEFERRED:
        found.append(f"état {state} : entrée en vigueur ou abrogation différée")
    elif state in ENDED:
        found.append(f"état {state} : version abrogée, annulée ou sans effet")
    return found


def load_json(body: bytes) -> Any:
    try:
        return json.loads(body)
    except (ValueError, RecursionError):
        raise LegiError("Légifrance : réponse illisible (JSON invalide)") from None


def _short(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = clean_text(value)
    return clip(cleaned, limit)[0] if cleaned else None


def _body_text(article: dict[str, Any]) -> tuple[str, bool]:
    """The plain text of an article, one paragraph per line, clipped to ``TEXT_MAX``."""
    raw, markup = article.get("texte"), False
    if not isinstance(raw, str) or not raw.strip():
        raw, markup = article.get("texteHtml"), True
    if not isinstance(raw, str):
        return "", False
    lines = _BREAK.sub("\n", raw).splitlines() if markup else raw.splitlines()
    kept = [strip_markup(line) if markup else clean_text(line) for line in lines]
    return clip("\n".join(line for line in kept if line), TEXT_MAX)


@dataclass(frozen=True)
class Version:
    id: str
    span: Window
    state: str | None


@dataclass(frozen=True)
class Article:
    id: str
    cid: str | None
    num: str | None
    text_id: str | None
    text_title: str | None
    code: bool
    span: Window
    state: str | None
    text: str
    truncated: bool
    versions: tuple[Version, ...]


def _versions(raw: object) -> tuple[Version, ...]:
    found: list[Version] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        identifier = item.get("id")
        span = window(item.get("dateDebut"), item.get("dateFin"))
        if isinstance(identifier, str) and article_id(identifier) and span is not None:
            found.append(Version(identifier, span, status(item.get("etat"))))
    return tuple(found)


def _parent(article: dict[str, Any]) -> tuple[str | None, str | None, bool]:
    """Identifier, title and kind (code or not) of the text holding the article."""
    titles = article.get("textTitles")
    first = titles[0] if isinstance(titles, list) and titles else None
    first = first if isinstance(first, dict) else {}
    for candidate in (first.get("cid"), first.get("id"), article.get("cidTexte")):
        if isinstance(candidate, str) and text_id(candidate):
            identifier: str | None = candidate
            break
    else:
        identifier = None
    return identifier, _short(first.get("titre"), TITLE_MAX), first.get("nature") == "CODE"


def parse_article(data: Any) -> Article:
    """The article of a ``getArticle`` or ``getArticleWithIdAndNum`` reply."""
    article = data.get("article") if isinstance(data, dict) else None
    if article is None and isinstance(data, dict):
        raise LegiError("article introuvable dans Légifrance")
    if not isinstance(article, dict):
        raise LegiError("Légifrance : réponse inattendue (article absent)")
    identifier = article.get("id")
    span = window(article.get("dateDebut"), article.get("dateFin"))
    if not isinstance(identifier, str) or not article_id(identifier) or span is None:
        raise LegiError("Légifrance : réponse inattendue (identifiant ou dates de version)")
    cid = article.get("cid")
    num = article.get("num")
    parent, title, code = _parent(article)
    body, truncated = _body_text(article)
    return Article(
        id=identifier,
        cid=cid if isinstance(cid, str) and article_id(cid) else None,
        num=article_num(num) if isinstance(num, str) else None,
        text_id=parent,
        text_title=title,
        code=code,
        span=span,
        state=status(article.get("etat")),
        text=body,
        truncated=truncated,
        versions=_versions(article.get("articleVersions")),
    )


@dataclass(frozen=True)
class Hit:
    """One search result: an article extract, or a text when the result has no extract."""

    article_id: str | None
    text_id: str | None
    text_title: str | None
    num: str | None
    state: str | None
    span: Window | None
    extract: str | None


def _extract(values: object) -> str | None:
    parts = (
        [strip_markup(v) for v in values if isinstance(v, str)] if isinstance(values, list) else []
    )
    joined = " … ".join(part for part in parts if part)
    return clip(joined, EXTRACT_MAX)[0] if joined else None


def _hits_of(result: dict[str, Any]) -> list[Hit]:
    titles = result.get("titles")
    first = titles[0] if isinstance(titles, list) and titles else None
    first = first if isinstance(first, dict) else {}
    parent = next(
        (c for c in (first.get("cid"), first.get("id")) if isinstance(c, str) and text_id(c)),
        None,
    )
    title = _short(first.get("title"), TITLE_MAX)
    hits: list[Hit] = []
    sections = result.get("sections")
    for section in sections if isinstance(sections, list) else []:
        extracts = section.get("extracts") if isinstance(section, dict) else None
        for item in extracts if isinstance(extracts, list) else []:
            if not isinstance(item, dict):
                continue
            identifier, num = item.get("id"), item.get("num")
            hits.append(
                Hit(
                    article_id=identifier
                    if isinstance(identifier, str) and article_id(identifier)
                    else None,
                    text_id=parent,
                    text_title=title,
                    num=article_num(num) if isinstance(num, str) else None,
                    state=status(item.get("legalStatus")),
                    span=window(item.get("dateDebut"), item.get("dateFin")),
                    extract=_extract(item.get("values")),
                )
            )
    if not hits and parent is not None:
        hits.append(
            Hit(
                article_id=None,
                text_id=parent,
                text_title=title,
                num=None,
                state=status(first.get("legalStatus")),
                span=window(first.get("startDate"), first.get("endDate")),
                extract=None,
            )
        )
    return [hit for hit in hits if hit.article_id or hit.text_id]


def parse_search(data: Any, limit: int) -> tuple[int | None, list[Hit]]:
    """The total announced by the API and the first ``limit`` usable results, in its order."""
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise LegiError("Légifrance : réponse inattendue (résultats absents)")
    hits: list[Hit] = []
    for result in data["results"]:
        if isinstance(result, dict):
            hits.extend(_hits_of(result))
    total = data.get("totalResultNumber")
    known = total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else None
    return known, hits[:limit]
