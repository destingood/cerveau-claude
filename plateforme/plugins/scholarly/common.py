"""Shared parts of the two sources: partial dates and the bounded GET (ADR-044).

The hosts are fixed constants of the plugin (no URL comes from the planner), so the SSRF guard of
``web_read`` does not apply; redirects are still refused and proxies of the environment ignored.
Each request waits for the shared rate limit of its API (``core.net.throttle``), then has 15 s
and 2 MB at most. Texts are cleaned by ``core.net.text``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from core.net.body import read_body
from core.net.guard import FetchError
from core.net.throttle import SharedThrottle
from plugins.scholarly import __version__

TIMEOUT_S = 15.0
MAX_BYTES = 2_000_000
MAX_TITLE_CHARS = 500
MAX_NAME_CHARS = 200
MAX_VENUE_CHARS = 300
# Under the project root whatever the working directory of the plugin process: every process of
# this checkout waits for the same locks (arXiv counts all the machines of a user).
THROTTLE_DIR = Path(__file__).resolve().parents[2] / "var" / "net"
USER_AGENT = f"CERVEAU-scholarly/{__version__} (assistant personnel, lecture seule)"


class ScholarError(Exception):
    """A refused or failed request. The message is French and safe to show to the planner."""


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class PartialDate:
    """A date known to the year, the month or the day."""

    year: int
    month: int | None = None
    day: int | None = None

    def earliest(self) -> date:
        return date(self.year, self.month or 1, self.day or 1)

    def iso(self) -> str:
        parts = [f"{self.year:04d}"]
        if self.month is not None:
            parts.append(f"{self.month:02d}")
            if self.day is not None:
                parts.append(f"{self.day:02d}")
        return "-".join(parts)

    @classmethod
    def of(cls, parts: Iterable[object]) -> PartialDate | None:
        """From ``[year, month, day]`` (each optional after the year); None if invalid."""
        values: list[int] = []
        for value in list(parts)[:3]:
            if not isinstance(value, int) or isinstance(value, bool):
                return None
            values.append(value)
        if not values or values[0] < 1000:
            return None
        month = values[1] if len(values) > 1 else None
        day = values[2] if len(values) > 2 else None
        try:
            date(values[0], 1 if month is None else month, 1 if day is None else day)
        except ValueError:
            return None
        return cls(values[0], month, day)


def first_date(dates: Iterable[PartialDate | None]) -> PartialDate | None:
    known = [d for d in dates if d is not None]
    return min(known, key=lambda d: d.earliest()) if known else None


def on_or_after(first: PartialDate | None, since: date | None) -> bool:
    """Kept only if the record surely appeared on ``since`` or later; unknown dates are not."""
    if since is None:
        return True
    return first is not None and first.earliest() >= since


def media_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").partition(";")[0].strip().lower()


@dataclass(frozen=True)
class Reply:
    status: int
    media: str
    body: bytes


class Fetcher:
    """One GET at a time to one API, under its shared rate limit."""

    def __init__(
        self,
        label: str,
        throttle: SharedThrottle,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = TIMEOUT_S,
        max_bytes: int = MAX_BYTES,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self.label, self.throttle, self.transport = label, throttle, transport
        self.timeout_s, self.max_bytes, self.now = timeout_s, max_bytes, now

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.transport,
            trust_env=False,
            follow_redirects=False,
            timeout=self.timeout_s,
            limits=httpx.Limits(max_keepalive_connections=0),
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
        )

    async def get(
        self,
        url: str,
        params: Mapping[str, str | int] | None,
        *,
        accept: str,
        read_statuses: frozenset[int],
    ) -> Reply:
        """The body of a status in ``read_statuses``; any other status is an error."""
        try:
            async with (
                self.throttle.slot(),
                asyncio.timeout(self.timeout_s),
                self._client() as client,
                client.stream("GET", url, params=params, headers={"Accept": accept}) as resp,
            ):
                status = resp.status_code
                if status not in read_statuses:
                    raise ScholarError(f"{self.label} : {_status_error(status)}")
                body = await read_body(resp, self.max_bytes, cut=False)
                return Reply(status, media_type(resp), body)
        except TimeoutError:
            raise ScholarError(f"{self.label} : délai de {self.timeout_s:g} s dépassé") from None
        except FetchError as exc:
            raise ScholarError(f"{self.label} : {exc}") from None
        except httpx.HTTPError:
            raise ScholarError(f"{self.label} : connexion impossible") from None


def _status_error(status: int) -> str:
    if 300 <= status < 400:
        return "redirection inattendue"
    if status == 403:
        return "accès refusé (HTTP 403, blocage possible du pool public)"
    if status == 429:
        return "débit dépassé (HTTP 429), réessayer plus tard"
    if status >= 500:
        return f"service indisponible (HTTP {status})"
    return f"réponse HTTP {status} inattendue"
