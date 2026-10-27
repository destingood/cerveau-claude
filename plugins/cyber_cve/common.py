"""Shared parts of the three sources: identifiers, dates, the cache and the bounded GET (ADR-055).

The hosts are fixed constants of the plugin: no URL comes from the planner. Each request is still
checked against the list of the three hosts, then goes through the guard of ``core.net`` (every
address of the name public, connection pinned to the checked address, ADR-006); redirects are
refused and proxies of the environment ignored. Each request waits for the shared rate limit of
its API (``core.net.throttle``, G4), then has 15 s and a size cap.

A reply is cached under ``var/cyber/cache/`` for 24 h once it has been read without error. The
cache is keyed by the URL and its parameters only: the optional NVD key travels in the ``apiKey``
header and never reaches a file, a log or an output (G3, R6).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, TypeGuard, TypeVar

import httpx

from core.net.body import read_body
from core.net.guard import FetchError, Resolver, check_url, pin, pinned_request, system_resolver
from core.net.text import clean_text, clip
from core.net.throttle import SharedThrottle
from plugins.cyber_cve import __version__

TIMEOUT_S = 15.0
MAX_BYTES = 2_000_000
CACHE_TTL = timedelta(hours=24)
HOSTS = frozenset({"services.nvd.nist.gov", "www.cisa.gov", "api.first.org"})
ROOT = Path(__file__).resolve().parents[2]
# Under the project root whatever the working directory of the plugin process: every process of
# this checkout waits for the same locks (the NVD counts the requests of a key or an address).
THROTTLE_DIR = ROOT / "var" / "net"
CACHE_DIR = ROOT / "var" / "cyber" / "cache"
USER_AGENT = f"CERVEAU-cyber_cve/{__version__} (assistant personnel, lecture seule)"
# CVE-YYYY-NNNN: four digits at least, no leading zero beyond four (CVE numbering rules).
_CVE = re.compile(r"CVE-([0-9]{4})-([0-9]{4,19})")
_CWE = re.compile(r"CWE-[0-9]{1,6}|NVD-CWE-Other|NVD-CWE-noinfo")
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
FIRST_CVE_YEAR = 1999
_JSON = "application/json"

T = TypeVar("T")


class CyberError(Exception):
    """A refused or failed request. The message is French and safe to show to the planner."""


def utcnow() -> datetime:
    return datetime.now(UTC)


def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def cve_id(raw: str, today: date) -> str | None:
    """The canonical ``CVE-YYYY-NNNN`` of ``raw`` (case and spaces ignored), else None."""
    value = raw.strip().upper()
    match = _CVE.fullmatch(value)
    if match is None:
        return None
    year, number = int(match.group(1)), match.group(2)
    if not FIRST_CVE_YEAR <= year <= today.year + 1:
        return None
    if len(number) > 4 and number.startswith("0"):
        return None
    return value


def cve_order(identifier: str) -> tuple[int, int]:
    """Numeric order of two valid identifiers: CVE-2021-9999 before CVE-2021-10000."""
    _, year, number = identifier.split("-")
    return int(year), int(number)


def is_cwe(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and _CWE.fullmatch(value) is not None


def day(value: object) -> date | None:
    """A calendar date written ``YYYY-MM-DD``, alone or at the head of a timestamp."""
    if not isinstance(value, str) or _DAY.fullmatch(value[:10]) is None:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def text(value: object, limit: int) -> tuple[str, bool] | None:
    """Clean external text clipped to ``limit`` characters (R5); None when empty or not a text."""
    if not isinstance(value, str):
        return None
    cleaned = clean_text(value)
    return clip(cleaned, limit) if cleaned else None


def short(value: object, limit: int) -> str | None:
    found = text(value, limit)
    return found[0] if found else None


def number(value: object, low: float, high: float) -> float | None:
    """A finite number within ``[low, high]``, given as a number or a decimal string (EPSS)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value) if low <= value <= high else None


def load_json(body: bytes, label: str) -> Any:
    try:
        return json.loads(body)
    except (ValueError, RecursionError):
        raise CyberError(f"{label} : réponse illisible (JSON invalide)") from None


def media_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").partition(";")[0].strip().lower()


class ResponseCache:
    """Bodies of replies read without error, kept ``ttl`` under one directory per source."""

    def __init__(
        self, directory: Path, ttl: timedelta = CACHE_TTL, now: Callable[[], datetime] = utcnow
    ) -> None:
        self.directory, self.ttl, self.now = directory, ttl, now

    def _paths(self, key: str) -> tuple[Path, Path]:
        name = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.directory / f"{name}.body", self.directory / f"{name}.meta"

    def _fresh(self, read_at: datetime) -> bool:
        age = self.now() - read_at
        return timedelta(0) <= age < self.ttl

    def get(self, key: str) -> tuple[bytes, datetime] | None:
        """The body and the time it was read, if fresh and intact; otherwise a miss."""
        body_path, meta_path = self._paths(key)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            read_at = datetime.fromisoformat(meta["read_at"])
            if meta["key"] != key or read_at.tzinfo is None or not self._fresh(read_at):
                return None
            body = body_path.read_bytes()
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if hashlib.sha256(body).hexdigest() != meta.get("sha256"):
            return None
        return body, read_at

    def put(self, key: str, body: bytes, read_at: datetime) -> None:
        """Best effort: a cache that cannot be written only costs a new request later."""
        body_path, meta_path = self._paths(key)
        meta = {"key": key, "read_at": stamp(read_at), "sha256": hashlib.sha256(body).hexdigest()}
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._prune()
            _replace(body_path, body)
            _replace(meta_path, json.dumps(meta).encode("utf-8"))
        except OSError:
            return

    def _prune(self) -> None:
        for meta_path in self.directory.glob("*.meta"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                read_at = datetime.fromisoformat(meta["read_at"])
                stale = read_at.tzinfo is None or not self._fresh(read_at)
            except (OSError, ValueError, KeyError, TypeError):
                stale = True
            if stale:
                for path in (meta_path, meta_path.with_suffix(".body")):
                    with contextlib.suppress(OSError):
                        path.unlink()


def _replace(path: Path, data: bytes) -> None:
    """Write ``data`` to a temporary file beside ``path``, then rename it: never half a file."""
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def cache_key(url: str, params: Mapping[str, str | int] | None) -> str:
    """The full URL with its parameters in a fixed order: the cache key and the request target."""
    try:
        return str(httpx.URL(url, params=sorted((params or {}).items())))
    except (ValueError, httpx.InvalidURL):  # a lone surrogate cannot be encoded
        raise CyberError("paramètre de requête illisible") from None


@dataclass(frozen=True)
class Read[V]:
    """A parsed reply and the time its body was read from the source (cached or not)."""

    value: V
    read_at: datetime
    cached: bool


class Fetcher:
    """One GET at a time to one API, under its shared rate limit, through an optional cache."""

    def __init__(
        self,
        label: str,
        throttle: SharedThrottle,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = TIMEOUT_S,
        max_bytes: int = MAX_BYTES,
        headers: Mapping[str, str] | None = None,
        cache: ResponseCache | None = None,
        resolver: Resolver = system_resolver,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self.label, self.throttle, self.transport = label, throttle, transport
        self.resolver = resolver
        self.timeout_s, self.max_bytes, self.now = timeout_s, max_bytes, now
        self.cache = cache
        # Kept apart from every message, key and file: only the client sends it (G3, R6).
        self._headers = dict(headers or {})

    @property
    def keyed(self) -> bool:
        return bool(self._headers)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.transport,
            trust_env=False,
            follow_redirects=False,
            timeout=self.timeout_s,
            limits=httpx.Limits(max_keepalive_connections=0),
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", **self._headers},
        )

    async def get(
        self,
        url: str,
        params: Mapping[str, str | int] | None,
        parse: Callable[[bytes], T],
        *,
        keep: Callable[[T], bool] = lambda _: True,
    ) -> Read[T]:
        """The parsed body of a 200 reply; a body that does not parse is never cached."""
        key = cache_key(url, params)
        if self.cache is not None and (hit := self.cache.get(key)) is not None:
            body, read_at = hit
            try:
                return Read(parse(body), read_at, cached=True)
            except CyberError:
                pass  # a damaged copy: read the source again
        body = await self._fetch(url, params)
        read_at = self.now()
        value = parse(body)
        if self.cache is not None and keep(value):
            self.cache.put(key, body, read_at)
        return Read(value, read_at, cached=False)

    async def _fetch(self, url: str, params: Mapping[str, str | int] | None) -> bytes:
        try:
            target = check_url(cache_key(url, params))
            if target.scheme != "https" or target.host not in HOSTS:
                raise CyberError(f"{self.label} : hôte non autorisé")
            async with self.throttle.slot(), asyncio.timeout(self.timeout_s):
                address = await pin(target, self.resolver)
                async with self._client() as client:
                    request = pinned_request(client, target, address, {"Accept": _JSON})
                    response = await client.send(request, stream=True)
                    try:
                        return await self._body(response)
                    finally:
                        await response.aclose()
        except (TimeoutError, httpx.TimeoutException):
            raise CyberError(f"{self.label} : délai de {self.timeout_s:g} s dépassé") from None
        except FetchError as exc:
            raise CyberError(f"{self.label} : {exc}") from None
        except httpx.HTTPError:
            raise CyberError(f"{self.label} : connexion impossible") from None

    async def _body(self, response: httpx.Response) -> bytes:
        if response.status_code != 200:
            raise CyberError(f"{self.label} : {_status_error(response.status_code)}")
        if media_type(response) not in (_JSON, ""):
            raise CyberError(f"{self.label} : réponse qui n'est pas du JSON")
        return await read_body(response, self.max_bytes, cut=False)


def _status_error(status: int) -> str:
    if 300 <= status < 400:
        return "redirection inattendue"
    if status == 403:
        return "accès refusé (HTTP 403 : débit dépassé ou clé refusée)"
    if status == 429:
        return "débit dépassé (HTTP 429), réessayer plus tard"
    if status >= 500:
        return f"service indisponible (HTTP {status})"
    return f"réponse HTTP {status} inattendue"
