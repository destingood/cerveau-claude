"""Client of the API Recherche d'entreprises (DINUM): one GET, its pace, its cache (ADR-062).

- **Host.** ``recherche-entreprises.api.gouv.fr`` only; ``config/data_sources.yaml`` must name it
  exactly. Each request goes through the guard of ``core.net`` (public addresses only, connection
  pinned to the checked address, ADR-006); no redirect is followed and the proxies of the
  environment are ignored. No account and no key.
- **Pace (I9).** Two requests per second, shared by every process of the checkout
  (``core.net.throttle``), under the 7 per second per IP of the API. A 429 is retried once if its
  ``Retry-After`` is short; otherwise the source is reported unavailable.
- **Cache (I4).** Only the filtered output is kept, 24 h under ``var/business/``: the raw reply,
  which may name persons, never reaches the disk. The key is a digest of the query string.
- **Kill switch (R4).** Checked before the request and before each chunk read: an engaged switch
  stops the call within one chunk. 2 MB at most per reply.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx

from core.net.body import read_body
from core.net.guard import FetchError, Resolver, check_url, pin, pinned_request, system_resolver
from core.net.throttle import SharedThrottle
from plugins.entreprises import __version__
from plugins.entreprises.registry import RegistryError
from plugins.legifrance.client import ResponseCache

BASE = "https://recherche-entreprises.api.gouv.fr"
SEARCH_PATH = "/search"
HOST = httpx.URL(BASE).host
TIMEOUT_S = 15.0
MAX_BYTES = 2_000_000
INTERVAL_S = 0.5  # two requests per second (I9)
RETRY_MAX_S = 5
CACHE_TTL = timedelta(hours=24)
UNAVAILABLE = "source indisponible"
STOPPED = "arrêt d'urgence enclenché (kill switch) : aucune lecture"
ROOT = Path(__file__).resolve().parents[2]
THROTTLE_DIR = ROOT / "var" / "net"
CACHE_DIR = ROOT / "var" / "business" / "cache" / "entreprises"
USER_AGENT = f"CERVEAU-entreprises/{__version__} (assistant personnel, lecture seule)"
_JSON = "application/json"
_SECONDS = re.compile(r"\d{1,3}", re.ASCII)  # "²".isdigit() is true, int("²") fails


def utcnow() -> datetime:
    return datetime.now(UTC)


def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def base_url(url: str | None) -> str:
    """The configured ``url`` must be the API's own address; nothing else is reachable."""
    if (url or "").rstrip("/") != BASE:
        raise RegistryError(
            f"{UNAVAILABLE} : data_sources.yaml › sources.entreprises.url n'est pas {BASE}"
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


class RegistryClient:
    """One GET at a time to ``/search``, under its shared rate limit, through a filtered cache."""

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

    async def search(
        self, base: str, params: Mapping[str, str], keep: Callable[[bytes], bytes]
    ) -> Read:
        """``keep`` turns the raw reply into the filtered body; only that body is cached."""
        query = urlencode(sorted(params.items()))
        if self.stopped():  # a cached copy is a read too (R4)
            raise RegistryError(STOPPED)
        if self.cache is not None and (hit := self.cache.get(query)) is not None:
            return Read(hit[0], hit[1], cached=True)
        url = f"{base}{SEARCH_PATH}?{query}"
        try:
            raw = await self._get(url)
        except _Retry as retry:
            await self.sleep(retry.seconds)
            try:
                raw = await self._get(url)
            except _Retry:
                raise RegistryError(
                    f"{UNAVAILABLE} : limite de débit de l'API atteinte (HTTP 429)"
                ) from None
        read_at = self.now()
        body = keep(raw)
        if self.cache is not None:
            self.cache.put(query, body, read_at)
        return Read(body, read_at, cached=False)

    async def _get(self, url: str) -> bytes:
        if self.stopped():
            raise RegistryError(STOPPED)
        outcome = await self._attempt(url)
        if isinstance(outcome, str):
            raise RegistryError(f"{UNAVAILABLE} : {outcome}")
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
            raise RegistryError(STOPPED) from None
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
        if status != 200:
            return status_error(status)
        kind = response.headers.get("content-type", "").partition(";")[0].strip().lower()
        if kind not in (_JSON, ""):
            return "réponse qui n'est pas du JSON"
        return await read_body(response, self.max_bytes, cut=False, interrupt=self._interrupt)


def retry_after(value: str | None) -> int | None:
    """A short wait in whole seconds, or none: a date or a long wait is not waited for."""
    text = (value or "").strip()
    if _SECONDS.fullmatch(text) is None:
        return None
    seconds = int(text)
    return seconds if seconds <= RETRY_MAX_S else None


def status_error(status: int) -> str:
    if 300 <= status < 400:
        return "redirection inattendue"
    if status == 400:
        return "requête refusée par l'API (HTTP 400)"
    if status == 429:
        return "limite de débit de l'API atteinte (HTTP 429)"
    if status >= 500:
        return f"service indisponible (HTTP {status})"
    return f"réponse HTTP {status} inattendue"
