"""Tokenless, bounded reads of the GitHub Actions API for ``code_ci`` (E6).

The host is a constant and the path is built from the allow list (``owner/name``, checked by the
configuration), so no URL comes from the planner and the SSRF guard of ``web_read`` does not
apply; redirects are refused, proxies of the environment ignored, and no ``Authorization`` header
is ever sent. One request at a time leaves this checkout (``core.net.throttle``), with 15 s and
2 MB at most.

Without a token GitHub allows 60 requests per hour and per IP address. When it refuses one (HTTP
403 or 429), its documentation asks not to retry before ``x-ratelimit-reset`` when the window is
exhausted, after ``retry-after`` seconds when given, else after one minute: ``Pause`` keeps that
time in a file shared by every process, and no request leaves before it.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from core.code.text import visible
from core.guardrails.secrets import mask_secrets
from core.net.body import read_body
from core.net.guard import FetchError
from core.net.text import clean_text, clip
from core.net.throttle import SharedThrottle
from plugins.code_ci import __version__
from plugins.code_ci.models import Run

API = "https://api.github.com"
API_VERSION = "2026-03-10"
ACCEPT = "application/vnd.github+json"
TIMEOUT_S = 15.0
MAX_BYTES = 2_000_000
INTERVAL_S = 1.0
# No retry-after and a window not exhausted: GitHub asks to wait at least one minute.
DEFAULT_WAIT_S = 60.0
# A primary window lasts one hour: a longer wait comes from a damaged file or a clock set back.
MAX_WAIT_S = 3_600.0
NAME_CHARS = 100
BRANCH_CHARS = 200
TITLE_CHARS = 200
USER_AGENT = f"CERVEAU-code_ci/{__version__} (assistant personnel, lecture seule)"
NOT_STANDARD = "non standard"
RUNNING = "en_cours"

_SHA = re.compile(r"[0-9a-f]{40}")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_TOKEN = re.compile(r"[a-z_]{1,30}")
# Ten digits at most: a reset time stays within the range of ``datetime``.
_COUNTER = re.compile(r"[0-9]{1,10}")


class CiError(Exception):
    """A refused or failed read. The message is French and safe to show to the planner."""


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Rate:
    limit: int
    remaining: int
    # UTC epoch seconds.
    reset: int


def _counter(headers: httpx.Headers, name: str) -> int | None:
    value = headers.get(name, "").strip()
    return int(value) if _COUNTER.fullmatch(value) else None


def rate_of(headers: httpx.Headers) -> Rate | None:
    """GitHub's counters for this IP address, or None if one of them is missing or not a number."""
    values = [_counter(headers, f"x-ratelimit-{name}") for name in ("limit", "remaining", "reset")]
    if any(value is None for value in values):
        return None
    limit, remaining, reset = (int(value or 0) for value in values)
    return Rate(limit, remaining, reset)


class Pause:
    """Until when GitHub refuses requests from this machine, shared by every process."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path, self.clock = path, clock

    def left(self) -> float:
        """Seconds before the next request may leave; a damaged state means one default wait."""
        try:
            until = float(self.path.read_text(encoding="ascii"))
        except FileNotFoundError:
            return 0.0
        except (OSError, UnicodeError, ValueError):
            return self.hold(DEFAULT_WAIT_S)
        wait = until - self.clock()
        if not wait <= MAX_WAIT_S:  # also true for NaN
            return self.hold(DEFAULT_WAIT_S)
        return max(0.0, wait)

    def hold(self, seconds: float) -> float:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(repr(self.clock() + seconds), encoding="ascii")
        os.replace(temporary, self.path)
        return seconds


def wait_of(headers: httpx.Headers, rate: Rate | None, now: float) -> float:
    """Seconds GitHub asks to wait after a refusal, between 1 s and one hour."""
    if rate is not None and rate.remaining == 0:
        return min(MAX_WAIT_S, max(1.0, rate.reset - now))
    retry_after = _counter(headers, "retry-after")
    if retry_after is not None:
        return min(MAX_WAIT_S, max(1.0, float(retry_after)))
    return DEFAULT_WAIT_S


def refusal(status: int, github: str, rate: Rate | None, wait: float) -> str:
    if status in (403, 429):
        if rate is not None and rate.remaining == 0:
            return (
                f"limite de {rate.limit} requêtes par heure de GitHub atteinte (HTTP {status}) : "
                f"aucune requête avant {iso(rate.reset)}"
            )
        return f"requête refusée par GitHub (HTTP {status}) : aucune requête pendant {wait:.0f} s"
    if status == 404:
        return f"dépôt GitHub « {github} » introuvable, privé ou sans Actions (aucun jeton, E6)"
    if 300 <= status < 400:
        return (
            "redirection refusée : dépôt renommé ou déplacé ? corriger github dans config/code.yaml"
        )
    if status >= 500:
        return f"service indisponible (HTTP {status})"
    return f"réponse HTTP {status} inattendue"


class GitHub:
    """GET of the runs of one repository, under the shared rate limit and pause."""

    def __init__(
        self,
        throttle: SharedThrottle,
        pause: Pause,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = TIMEOUT_S,
        max_bytes: int = MAX_BYTES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.throttle, self.pause, self.transport = throttle, pause, transport
        self.timeout_s, self.max_bytes, self.clock = timeout_s, max_bytes, clock

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.transport,
            trust_env=False,
            follow_redirects=False,
            timeout=self.timeout_s,
            limits=httpx.Limits(max_keepalive_connections=0),
            headers={
                "User-Agent": USER_AGENT,
                "Accept": ACCEPT,
                "X-GitHub-Api-Version": API_VERSION,
                "Accept-Encoding": "gzip",
            },
        )

    async def runs(
        self, github: str, branch: str | None, per_page: int
    ) -> tuple[bytes, Rate | None]:
        params: dict[str, str | int] = {"per_page": per_page, "exclude_pull_requests": "true"}
        if branch is not None:
            params["branch"] = branch
        try:
            async with self.throttle.slot():
                wait = self.pause.left()
                if wait > 0:
                    raise CiError(
                        f"GitHub : limite de débit, aucune requête envoyée ; réessayer dans "
                        f"{math.ceil(wait)} s"
                    )
                async with (
                    asyncio.timeout(self.timeout_s),
                    self._client() as client,
                    client.stream("GET", f"{API}/repos/{github}/actions/runs", params=params) as r,
                ):
                    rate = rate_of(r.headers)
                    if r.status_code != 200:
                        held = 0.0
                        if r.status_code in (403, 429):
                            held = self.pause.hold(wait_of(r.headers, rate, self.clock()))
                        raise CiError(f"GitHub : {refusal(r.status_code, github, rate, held)}")
                    media = r.headers.get("content-type", "").partition(";")[0].strip().lower()
                    if media != "application/json":
                        raise CiError("GitHub : réponse qui n'est pas du JSON")
                    return await read_body(r, self.max_bytes, cut=False), rate
        except TimeoutError:
            raise CiError(f"GitHub : délai de {self.timeout_s:g} s dépassé") from None
        except FetchError as exc:
            raise CiError(f"GitHub : {exc}") from None
        except httpx.HTTPError:
            raise CiError("GitHub : connexion impossible") from None


def _text(raw: str, limit: int) -> str:
    """One line; invisible characters shown as ⟨U+XXXX⟩, secrets masked."""
    masked, _ = mask_secrets(clean_text(visible(raw)))
    return clip(masked, limit)[0]


def _unreadable(field: str) -> CiError:
    return CiError(f"GitHub : run illisible (champ « {field} »)")


def _number(item: Mapping[str, Any], field: str, *, optional: bool = False) -> int | None:
    value = item.get(field)
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _unreadable(field)
    return value


def _string(item: Mapping[str, Any], field: str, *, optional: bool = False) -> str | None:
    value = item.get(field)
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise _unreadable(field)
    return value


def _token(value: str | None) -> str | None:
    if value is None:
        return None
    return value if _TOKEN.fullmatch(value) else NOT_STANDARD


def _stamp(item: Mapping[str, Any], field: str) -> str:
    value = _string(item, field) or ""
    if not _STAMP.fullmatch(value):
        raise _unreadable(field)
    return value


def _run(item: object, github: str) -> Run:
    if not isinstance(item, dict):
        raise CiError("GitHub : run illisible")
    run_id = _number(item, "id") or 0
    head_sha = _string(item, "head_sha") or ""
    if not _SHA.fullmatch(head_sha):
        raise _unreadable("head_sha")
    workflow = _string(item, "name", optional=True)
    branch = _string(item, "head_branch", optional=True)
    return Run(
        id=run_id,
        run_number=_number(item, "run_number") or 0,
        run_attempt=_number(item, "run_attempt", optional=True),
        workflow=None if workflow is None else _text(workflow, NAME_CHARS),
        event=_token(_string(item, "event")) or NOT_STANDARD,
        status=_token(_string(item, "status", optional=True)),
        conclusion=_token(_string(item, "conclusion", optional=True)),
        branch=None if branch is None else _text(branch, BRANCH_CHARS),
        head_sha=head_sha,
        title=_text(_string(item, "display_title") or "", TITLE_CHARS),
        created_at=_stamp(item, "created_at"),
        updated_at=_stamp(item, "updated_at"),
        url=f"https://github.com/{github}/actions/runs/{run_id}",
    )


def parse_runs(body: bytes, github: str, limit: int) -> tuple[int, list[Run]]:
    """GitHub's total for the filter and the first ``limit`` runs; any odd field is an error."""
    try:
        data = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        raise CiError("GitHub : réponse illisible (JSON invalide)") from None
    if not isinstance(data, dict):
        raise CiError("GitHub : réponse illisible")
    total = data.get("total_count")
    runs = data.get("workflow_runs")
    if isinstance(total, bool) or not isinstance(total, int) or not isinstance(runs, list):
        raise CiError("GitHub : réponse illisible (total_count ou workflow_runs)")
    return total, [_run(item, github) for item in runs[:limit]]


def by_conclusion(runs: Sequence[Run]) -> dict[str, int]:
    counts = Counter(run.conclusion or RUNNING for run in runs)
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))
