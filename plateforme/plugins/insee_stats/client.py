"""Client of the INSEE Melodi API: one GET, its pace, its cache (plan P6, I3).

- **Host.** ``api.insee.fr`` only, under ``/melodi``; ``config/data_sources.yaml`` must name it
  exactly. Each request goes through the guard of ``core.net`` (public addresses only, connection
  pinned to the checked address, ADR-006); no redirect is followed and the proxies of the
  environment are ignored. Anonymous access: no account and no key.
- **Pace (I9).** 20 requests per minute, shared by every process of the checkout
  (``core.net.throttle``), under the 30 per minute of anonymous access. A 429 is retried once if
  its ``Retry-After`` is short; otherwise the source is reported unavailable.
- **Cache.** Only the filtered output is kept, 7 days under ``var/business/``: public statistics
  change once a year at most. The key is a digest of the path and query string.
- **Kill switch (R4).** Checked before the cache, before each request and before each chunk read.
  2 MB at most per reply.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx

from core.net.body import read_body
from core.net.guard import FetchError, Resolver, check_url, pin, pinned_request, system_resolver
from core.net.throttle import SharedThrottle
from plugins.entreprises.client import retry_after, status_error
from plugins.insee_stats import __version__
from plugins.insee_stats.catalog import StatsError
from plugins.legifrance.client import ResponseCache

BASE = "https://api.insee.fr/melodi"
HOST = httpx.URL(BASE).host
TIMEOUT_S = 10.0
MAX_BYTES = 2_000_000
INTERVAL_S = 3.0  # 20 requests per minute (I9)
CACHE_TTL = timedelta(days=7)
UNAVAILABLE = "source indisponible"
STOPPED = "arrêt d'urgence enclenché (kill switch) : aucune lecture"
ROOT = Path(__file__).resolve().parents[2]
THROTTLE_DIR = ROOT / "var" / "net"
CACHE_DIR = ROOT / "var" / "business" / "cache" / "insee_stats"
USER_AGENT = f"CERVEAU-insee_stats/{__version__} (assistant personnel, lecture seule)"
_JSON = "application/json"


def utcnow() -> datetime:
    return datetime.now(UTC)


def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def base_url(url: str | None) -> str:
    """The configured ``url`` must be the API's own address; nothing else is reachable."""
    if (url or "").rstrip("/") != BASE:
        raise StatsError(
            f"{UNAVAILABLE} : data_sources.yaml › sources.insee_melodi.url n'est pas {BASE}"
        )
    return BASE


@dataclass(frozen=True)
class Read:
    """The filtered body and the time the source was read (cached or not)."""

    body: bytes
    read_at: datetime
    cached: bool


class _Retry(Exception):
    def __init__(self, seconds: int) -> None:
        self.seconds = seconds


class _Stopped(Exception):
    pass


class StatsClient:
    """One GET at a time under ``/melodi``, under a shared rate limit, through a filtered cache."""

    def __init__(
        self,
        throttle: SharedThrottle,
        *,
        cache: ResponseCache | None = None,
        stopped: Callable[[], bool] = lambda: False,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = system_resolver,
        timeout_s: float = TIMEOUT_S,
        max_bytes: int = MAX_BYTES,
        now: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.throttle, self.cache, self.stopped = throttle, cache, stopped
        self.transport, self.resolver = transport, resolver
        self.timeout_s, self.max_bytes, self.now, self.sleep = timeout_s, max_bytes, now, sleep

    async def fetch(
        self,
        base: str,
        segments: tuple[str, ...],
        params: Mapping[str, str],
        keep: Callable[[bytes], bytes],
    ) -> Read:
        """GET ``base/segment/...?params``; ``keep`` turns the raw reply into the filtered body,
        and only that body is cached."""
        path = "/" + "/".join(quote(segment, safe="") for segment in segments)
        query = path + ("?" + urlencode(sorted(params.items())) if params else "")
        if self.stopped():
            raise StatsError(STOPPED)
        if self.cache is not None and (hit := self.cache.get(query)) is not None:
            return Read(hit[0], hit[1], cached=True)
        url = f"{base}{query}"
        try:
            raw = await self._get(url)
        except _Retry as retry:
            await self.sleep(retry.seconds)
            try:
                raw = await self._get(url)
            except _Retry:
                raise StatsError(
                    f"{UNAVAILABLE} : limite de débit de l'API atteinte (HTTP 429)"
                ) from None
        read_at = self.now()
        body = keep(raw)
        if self.cache is not None:
            self.cache.put(query, body, read_at)
        return Read(body, read_at, cached=False)

    async def _get(self, url: str) -> bytes:
        if self.stopped():
            raise StatsError(STOPPED)
        outcome = await self._attempt(url)
        if isinstance(outcome, str):
            raise StatsError(f"{UNAVAILABLE} : {outcome}")
        return outcome

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.transport,
            trust_env=False,
            follow_redirects=False,
            timeout=self.timeout_s,
            limits=httpx.Limits(max_keepalive_connections=0),
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", "Accept": _JSON},
        )

    def _interrupt(self) -> None:
        if self.stopped():
            raise _Stopped

    async def _attempt(self, url: str) -> bytes | str:
        try:
            target = check_url(url)
            if target.scheme != "https" or target.host != HOST:
                return "hôte non autorisé"
            async with self.throttle.slot(), asyncio.timeout(self.timeout_s):
                self._interrupt()  # the wait for the slot may be long (R4)
                address = await pin(target, self.resolver)
                async with self._client() as client:
                    request = pinned_request(client, target, address, {})
                    response = await client.send(request, stream=True)
                    try:
                        return await self._body(response)
                    finally:
                        await response.aclose()
        except _Stopped:
            raise StatsError(STOPPED) from None
        except (TimeoutError, httpx.TimeoutException):
            return f"délai de {self.timeout_s:g} s dépassé"
        except FetchError as exc:
            return str(exc)
        except httpx.HTTPError:
            return "connexion impossible"

    async def _body(self, response: httpx.Response) -> bytes | str:
        status = response.status_code
        if status == 429:
            wait = retry_after(response.headers.get("retry-after"))
            if wait is not None:
                raise _Retry(wait)
        if status == 404:
            return "jeu ou ressource introuvable (HTTP 404)"
        if status != 200:
            return status_error(status)
        kind = response.headers.get("content-type", "").partition(";")[0].strip().lower()
        if kind != _JSON:
            return "réponse qui n'est pas du JSON"
        return await read_body(response, self.max_bytes, cut=False, interrupt=self._interrupt)
