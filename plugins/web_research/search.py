"""Search providers behind one interface (ADR-006; Brave in phase 1, decision D1).

Results are returned to the caller and never stored (Brave's terms allow storage only on a plan
that grants it). Titles and snippets are external content: data, never instructions (R5).
The API key is kept out of ``repr`` and out of every error message.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from core.net.guard import ALLOWED_SCHEMES

# Documented on api-dashboard.search.brave.com (web search, "get started"), read 2026-10-18.
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
SEARCH_TIMEOUT_S = 15.0

_TAG = re.compile(r"<[^>]*>")
_SPACES = re.compile(r"\s+")


class SearchError(Exception):
    """A failed search. The message is French and never contains the key."""


@dataclass(frozen=True)
class Hit:
    title: str
    url: str
    snippet: str
    age: str | None = None


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, count: int) -> list[Hit]: ...


def _plain(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return _SPACES.sub(" ", html.unescape(_TAG.sub("", value))).strip()


def _web_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        scheme = httpx.URL(value).scheme
    except httpx.InvalidURL:
        return None
    return value if scheme in ALLOWED_SCHEMES else None


def parse_brave(data: Any, count: int) -> list[Hit]:
    """``web.results[]`` of a Brave answer; entries without a title or an http(s) URL dropped."""
    if not isinstance(data, dict):
        raise SearchError("Brave : réponse inattendue")
    web = data.get("web") or {}
    results = web.get("results") or [] if isinstance(web, dict) else None
    if not isinstance(results, list):  # also when ``web`` is not an object
        raise SearchError("Brave : réponse inattendue")
    hits: list[Hit] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url, title = _web_url(item.get("url")), _plain(item.get("title"))
        if url is None or not title:
            continue
        # ``age`` (e.g. "2 days ago") is not in Brave's documented minimum: optional (A_VERIFIER).
        age = item.get("age")
        age = age.strip() or None if isinstance(age, str) else None
        hits.append(Hit(title, url, _plain(item.get("description")), age))
        if len(hits) == count:
            break
    return hits


@dataclass
class BraveSearchProvider:
    api_key: str = field(repr=False)
    transport: httpx.AsyncBaseTransport | None = field(default=None, repr=False)
    name: str = field(default="brave", init=False)

    async def search(self, query: str, count: int) -> list[Hit]:
        headers = {"Accept": "application/json", "X-Subscription-Token": self.api_key}
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                trust_env=False,
                follow_redirects=False,
                timeout=SEARCH_TIMEOUT_S,
            ) as client:
                response = await client.get(
                    BRAVE_ENDPOINT, params={"q": query, "count": count}, headers=headers
                )
        except httpx.TimeoutException:
            raise SearchError("Brave : délai dépassé") from None
        except httpx.HTTPError as exc:
            raise SearchError(f"Brave : erreur réseau ({type(exc).__name__})") from None
        status = response.status_code
        if status in (401, 403):
            raise SearchError("Brave : clé refusée (vérifier BRAVE_SEARCH_API_KEY)")
        if status == 429:
            raise SearchError("Brave : quota ou débit dépassé")
        if status != 200:
            raise SearchError(f"Brave : statut HTTP {status}")
        try:
            data = response.json()
        except ValueError:
            raise SearchError("Brave : réponse illisible") from None
        return parse_brave(data, count)
