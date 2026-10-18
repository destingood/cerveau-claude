"""``web_read``: guarded fetch and main-text extraction (ADR-006).

Limits: 15 s for the whole read (``robots.txt``, redirects and text extraction included), 2 MB
of body read as a stream and cut at the limit (compressed and decompressed sizes both counted), at
most 5 redirects followed by hand, ``text/html`` and ``text/plain`` only. Each hop is checked
again: URL, public addresses (``guard``) and ``robots.txt`` of its host. Proxies from the
environment are ignored (``trust_env=False``) so that pinning holds, and connections are never
reused, so a TLS session opened for one name never carries a request for another.

A ``robots.txt`` that answered (2xx parsed, 4xx allows all) is kept an hour per origin, below the
24 h of RFC 9309 §2.4 (B22); one that could not be read (429, 5xx, network) is asked again at the
next read. The extraction is synchronous: it runs in a thread so that the time limit holds (B72);
a thread cannot be stopped, so one that overruns ends on its own and its result is dropped.
"""

from __future__ import annotations

import asyncio
import codecs
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
from trafilatura import bare_extraction

from plugins.web_research import __version__
from plugins.web_research.guard import (
    FetchError,
    Resolver,
    check_url,
    host_of,
    pin,
    pinned_request,
    shown,
    system_resolver,
)
from plugins.web_research.models import PageText
from plugins.web_research.robots import ROBOTS_AGENT, RobotsPolicy, parse_robots

TIMEOUT_S = 15.0
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5
# About 15 000 tokens: one page must not eat the per-request token budget (ADR-005).
MAX_TEXT_CHARS = 60_000
# RFC 9309 §2.5: at least 500 KiB must be parsed; the rest may be ignored.
ROBOTS_MAX_BYTES = 512_000
ROBOTS_TTL = timedelta(hours=1)  # RFC 9309 §2.4: 24 h at most
ROBOTS_CACHE_SIZE = 256  # origins kept; the oldest goes first
PAGE_TYPES = frozenset({"text/html", "text/plain"})
USER_AGENT = f"{ROBOTS_AGENT}/{__version__} (assistant personnel, lecture seule)"

_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_PAGE_HEADERS = {"Accept": "text/html, text/plain;q=0.9", "Accept-Language": "fr, en;q=0.8"}
_ROBOTS_HEADERS = {"Accept": "text/plain"}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _media_type(response: httpx.Response) -> tuple[str, str | None]:
    main, _, params = response.headers.get("content-type", "").partition(";")
    charset = None
    for param in params.split(";"):
        key, _, value = param.partition("=")
        if key.strip().lower() == "charset":
            charset = value.strip().strip("\"'") or None
    return main.strip().lower(), charset


def _decode(body: bytes, charset: str | None) -> str:
    try:
        codec = codecs.lookup(charset or "utf-8").name
    except LookupError:
        codec = "utf-8"
    return body.decode(codec, errors="replace")


async def _read_body(response: httpx.Response, limit: int, *, cut: bool) -> bytes:
    """Body of at most ``limit`` bytes; beyond it, ``cut`` truncates, otherwise it refuses."""
    encoding = response.headers.get("content-encoding", "identity").strip().lower() or "identity"
    if encoding not in ("identity", "gzip"):
        raise FetchError(f"encodage « {shown(encoding)} » non pris en charge")
    too_big = FetchError(f"page trop volumineuse (plus de {limit / 1_000_000:g} Mo)")
    declared = response.headers.get("content-length", "")
    if not cut and declared.isdigit() and int(declared) > limit:
        raise too_big
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
    body = bytearray()
    received = 0
    async for chunk in response.aiter_raw():
        received += len(chunk)
        try:
            # max_length is never 0 (0 would mean "no limit"): len(body) <= limit here.
            data = inflater.decompress(chunk, limit + 1 - len(body)) if inflater else chunk
        except zlib.error:
            raise FetchError("contenu compressé illisible") from None
        body += data
        over = received > limit or len(body) > limit or bool(inflater and inflater.unconsumed_tail)
        if over:
            if not cut:
                raise too_big
            return bytes(body[:limit])
    return bytes(body)


Extracted = tuple[str | None, str | None, str]
Extractor = Callable[[bytes, str, str | None, str], Extracted]


def _extract(body: bytes, media: str, charset: str | None, url: str) -> Extracted:
    """(title, published, text) of the page."""
    if media == "text/plain":
        return None, None, _decode(body, charset)
    source: str | bytes = _decode(body, charset) if charset else body
    doc = bare_extraction(
        source,
        url=url,
        include_comments=False,
        include_links=False,
        include_images=False,
        with_metadata=True,
    )
    if doc is None:
        return None, None, ""
    return doc.title or None, doc.date or None, doc.text or ""


@dataclass
class WebReader:
    resolver: Resolver = system_resolver
    transport: httpx.AsyncBaseTransport | None = field(default=None, repr=False)
    timeout_s: float = TIMEOUT_S
    max_bytes: int = MAX_BYTES
    max_redirects: int = MAX_REDIRECTS
    max_text_chars: int = MAX_TEXT_CHARS
    clock: Callable[[], datetime] = _utcnow
    extract: Extractor = _extract
    robots_ttl: timedelta = ROBOTS_TTL
    # origin → (fetched at, policy); only answers from the site are kept.
    _robots: dict[str, tuple[datetime, RobotsPolicy]] = field(
        default_factory=dict, init=False, repr=False
    )

    async def read(self, raw_url: str) -> PageText:
        url = check_url(raw_url)
        try:
            async with asyncio.timeout(self.timeout_s):
                final, media, charset, body = await self._fetch(url)
                title, published, text = await asyncio.to_thread(
                    self.extract, body, media, charset, str(final)
                )
        except (TimeoutError, httpx.TimeoutException):
            raise FetchError(f"délai de {self.timeout_s:g} s dépassé") from None
        except httpx.HTTPError as exc:
            raise FetchError(f"erreur réseau ({type(exc).__name__})") from None
        text = (text or "").strip()
        if not text:
            raise FetchError("aucun texte lisible (page vide ou rendue en JavaScript)")
        truncated = len(text) > self.max_text_chars
        return PageText(
            url=str(url),
            final_url=str(final),
            content_type=media,
            title=title,
            published=published,
            text=text[: self.max_text_chars],
            truncated=truncated,
            retrieved_at=self.clock().isoformat(timespec="seconds"),
        )

    async def _fetch(self, url: httpx.URL) -> tuple[httpx.URL, str, str | None, bytes]:
        """Final URL, media type, charset and body of the page."""
        async with self._client() as client:
            final, response = await self._open(client, url, _PAGE_HEADERS, robots=True)
            try:
                if not 200 <= response.status_code < 300:
                    raise FetchError(f"statut HTTP {response.status_code}")
                media, charset = _media_type(response)
                if media not in PAGE_TYPES:
                    kind = shown(media) if media else "absent"
                    raise FetchError(f"type « {kind} » non pris en charge")
                body = await _read_body(response, self.max_bytes, cut=False)
            finally:
                await response.aclose()
        return final, media, charset, body

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(self.timeout_s),
            limits=httpx.Limits(max_keepalive_connections=0),
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
        )

    async def _open(
        self,
        client: httpx.AsyncClient,
        url: httpx.URL,
        headers: dict[str, str],
        *,
        robots: bool,
    ) -> tuple[httpx.URL, httpx.Response]:
        """Final URL and open response; every hop is checked, and its ``robots.txt`` if asked."""
        for _ in range(self.max_redirects + 1):
            address = await pin(url, self.resolver)
            if robots and not await self._allowed(client, url):
                raise FetchError("le robots.txt du site interdit cette page (R15)")
            response = await client.send(pinned_request(client, url, address, headers), stream=True)
            if response.status_code not in _REDIRECTS:
                return url, response
            location = response.headers.get("location", "").strip()
            await response.aclose()
            if not location:
                raise FetchError("redirection sans destination")
            try:
                joined = str(url.join(location))
            except httpx.InvalidURL:
                raise FetchError("redirection vers une adresse invalide") from None
            url = check_url(joined)
        raise FetchError(f"plus de {self.max_redirects} redirections")

    async def _allowed(self, client: httpx.AsyncClient, url: httpx.URL) -> bool:
        origin = f"{url.scheme}://{host_of(url)}:{url.port or ''}"
        now = self.clock()
        cached = self._robots.get(origin)
        if cached is not None and timedelta(0) <= now - cached[0] < self.robots_ttl:
            policy = cached[1]
        else:
            policy, answered = await self._robots_policy(client, url)
            self._robots.pop(origin, None)
            if answered:
                while len(self._robots) >= ROBOTS_CACHE_SIZE:
                    del self._robots[next(iter(self._robots))]
                self._robots[origin] = (now, policy)
        return policy.allows(url.raw_path.decode("ascii"))

    async def _robots_policy(
        self, client: httpx.AsyncClient, url: httpx.URL
    ) -> tuple[RobotsPolicy, bool]:
        """RFC 9309 §2.3.1: 2xx parsed, 4xx allows all, 429, 5xx or unreachable deny all.

        The flag says whether the site answered, in which case the policy may be kept.
        """
        target = url.copy_with(raw_path=b"/robots.txt")
        try:
            _, response = await self._open(client, target, _ROBOTS_HEADERS, robots=False)
        except (FetchError, httpx.HTTPError):
            return RobotsPolicy.deny_everything(), False
        try:
            status = response.status_code
            if 200 <= status < 300:
                body = await _read_body(response, ROBOTS_MAX_BYTES, cut=True)
                return parse_robots(body.decode("utf-8", errors="replace")), True
            if 400 <= status < 500 and status != 429:
                return RobotsPolicy.allow_everything(), True
            return RobotsPolicy.deny_everything(), False
        except (FetchError, httpx.HTTPError):
            return RobotsPolicy.deny_everything(), False
        finally:
            await response.aclose()
