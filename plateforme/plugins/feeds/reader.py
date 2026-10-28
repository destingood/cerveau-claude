"""Bounded, pinned GET of an allow-listed feed (ADR-044).

The URL comes from the allow-list, never from the planner; it still goes through the SSRF guard
of ``core.net`` (every address of the name public, request pinned to the checked address, ports
80 and 443), since a public name may later point inside. No redirect is followed: a moved feed is
an error that Lucas fixes in the allow-list. 15 s and 2 MB at most; proxies of the environment
are ignored. robots.txt is not read: the allow-list, checked by Lucas against the terms of each
site, takes its place (R15).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx

from core.net.body import read_body
from core.net.guard import (
    FetchError,
    Resolver,
    check_url,
    pin,
    pinned_request,
    shown,
    system_resolver,
)
from plugins.feeds import __version__
from plugins.feeds.models import FeedError

TIMEOUT_S = 15.0
MAX_BYTES = 2_000_000
USER_AGENT = f"CERVEAU-feeds/{__version__} (assistant personnel, lecture seule)"
FEED_TYPES = frozenset(
    {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}
)
_ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8"


@dataclass
class FeedReader:
    resolver: Resolver = system_resolver
    transport: httpx.AsyncBaseTransport | None = field(default=None, repr=False)
    timeout_s: float = TIMEOUT_S
    max_bytes: int = MAX_BYTES

    async def fetch(self, raw_url: str) -> bytes:
        """The body of the feed, or ``FeedError`` with a reason safe to show."""
        try:
            url = check_url(raw_url)
            async with asyncio.timeout(self.timeout_s):
                address = await pin(url, self.resolver)
                async with self._client() as client:
                    request = pinned_request(client, url, address, {"Accept": _ACCEPT})
                    response = await client.send(request, stream=True)
                    try:
                        return await self._body(response)
                    finally:
                        await response.aclose()
        except (TimeoutError, httpx.TimeoutException):
            raise FeedError(f"délai de {self.timeout_s:g} s dépassé") from None
        except FetchError as exc:
            raise FeedError(str(exc)) from None
        except httpx.HTTPError:
            raise FeedError("connexion impossible") from None

    async def _body(self, response: httpx.Response) -> bytes:
        status = response.status_code
        if 300 <= status < 400:
            raise FeedError("flux déplacé (redirection refusée) : son URL est à revoir")
        if status != 200:
            raise FeedError(f"réponse HTTP {status}")
        media = response.headers.get("content-type", "").partition(";")[0].strip().lower()
        if media not in FEED_TYPES:
            raise FeedError(f"type « {shown(media) if media else 'absent'} » non pris en charge")
        return await read_body(response, self.max_bytes, cut=False)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(self.timeout_s),
            limits=httpx.Limits(max_keepalive_connections=0),
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
        )
