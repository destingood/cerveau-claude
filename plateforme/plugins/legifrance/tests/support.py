"""Offline doubles for the legifrance tests: a fake PISTE (OAuth and Légifrance API) behind
``httpx.MockTransport`` reached through a fake DNS, a rate limiter that never sleeps, and builders
of Légifrance replies (shapes from the Swagger 2.4.2 of the API, texts and identifiers invented).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx

from core.net.throttle import SharedThrottle
from plugins.legifrance.client import (
    ENVIRONMENTS,
    HOSTS,
    Credentials,
    PisteClient,
    ResponseCache,
)
from tests.net_doubles import PUBLIC_V4, FakeDns, chunks

FIXED_NOW = datetime(2026, 10, 27, 9, 30, tzinfo=UTC)
STAMP = "2026-10-27T09:30:00+00:00"
SANDBOX = ENVIRONMENTS["https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app"]
PRODUCTION = ENVIRONMENTS["https://api.piste.gouv.fr/dila/legifrance/lf-engine-app"]
# Invented values shaped like PISTE credentials: never real ones (R6).
FAKE_ID = "fake-client-id-0001"
FAKE_SECRET = "fake-client-secret-0002"  # noqa: S105 - invented for the tests
FAKE_TOKEN = "fake.token.0003"  # noqa: S105 - invented for the tests
CREDENTIALS = Credentials(FAKE_ID, FAKE_SECRET)
TEXT = "LEGITEXT000006070721"
ART = "LEGIARTI000032041571"
OLD = "LEGIARTI000006438819"
NEXT = "LEGIARTI000099999999"
MS_2016_10_01 = 1475280000000
MS_2999 = 32472144000000


async def no_sleep(_: float) -> None:
    await asyncio.sleep(0)  # pragma: no cover - the tests set a zero interval


def millis(day: str) -> int:
    moment = datetime.fromisoformat(day).replace(tzinfo=UTC)
    return int(moment.timestamp() * 1000)


def respond(body: Any = None, status: int = 200, content_type: str | None = "application/json"):
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    headers = {"content-type": content_type} if content_type else {}
    return httpx.Response(status, headers=headers, content=chunks(data))


def article(
    identifier: str = ART,
    *,
    num: str = "1240",
    start: Any = MS_2016_10_01,
    end: Any = MS_2999,
    state: str = "VIGUEUR",
    text: str | None = "Tout fait quelconque de l'homme oblige à réparer.",
    versions: list[dict[str, Any]] | None = None,
    parent: str = TEXT,
    nature: str = "CODE",
    **extra: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": identifier,
        "cid": "LEGIARTI000006438819",
        "num": num,
        "etat": state,
        "dateDebut": start,
        "dateFin": end,
        "texte": text,
        "textTitles": [{"id": parent, "cid": parent, "titre": "Code civil", "nature": nature}],
        "articleVersions": versions if versions is not None else [],
    }
    body.update(extra)
    return {"article": body, "executionTime": 3, "dereferenced": False}


def version(identifier: str, start: Any, end: Any, state: str = "VIGUEUR") -> dict[str, Any]:
    return {"id": identifier, "dateDebut": start, "dateFin": end, "etat": state}


def search_reply(*results: dict[str, Any], total: int | None = None) -> dict[str, Any]:
    return {"totalResultNumber": len(results) if total is None else total, "results": list(results)}


def result(*extracts: dict[str, Any], parent: str = TEXT, title: str = "Code civil"):
    return {
        "titles": [{"id": parent, "cid": parent, "title": title, "legalStatus": "VIGUEUR"}],
        "sections": [{"id": "s", "title": "Section", "extracts": list(extracts)}],
    }


def extract(identifier: str = ART, num: str = "1240", start: Any = "2016-10-01", end: Any = None):
    return {
        "id": identifier,
        "num": num,
        "legalStatus": "VIGUEUR",
        "dateDebut": start,
        "dateFin": end,
        "values": ["Tout fait <mark>quelconque</mark>", "de l'homme"],
    }


@dataclass
class Piste:
    """The two PISTE hosts of one environment: a token endpoint and the API routes."""

    routes: dict[str, Callable[[dict[str, Any]], httpx.Response]] = field(default_factory=dict)
    token: Callable[[dict[str, list[str]]], httpx.Response] | None = None
    requests: list[httpx.Request] = field(default_factory=list)
    dns: FakeDns = field(default_factory=lambda: FakeDns({h: [PUBLIC_V4] for h in HOSTS}))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/oauth/token":
            form = parse_qs(request.content.decode("ascii"))
            if self.token is not None:
                return self.token(form)
            return respond({"access_token": FAKE_TOKEN, "expires_in": 3600, "token_type": "x"})
        route = path.removeprefix("/dila/legifrance/lf-engine-app")
        return self.routes[route](json.loads(request.content))

    def on(self, route: str, body: Any, status: int = 200) -> Piste:
        self.routes[route] = lambda _: respond(body, status)
        return self

    def api_calls(self) -> list[str]:
        return [
            r.url.path.removeprefix("/dila/legifrance/lf-engine-app")
            for r in self.requests
            if r.url.path != "/api/oauth/token"
        ]

    def tokens(self) -> int:
        return sum(r.url.path == "/api/oauth/token" for r in self.requests)

    def client(
        self,
        directory: Path,
        *,
        secrets: Credentials | None = CREDENTIALS,
        cached: bool = True,
        now: Callable[[], datetime] = lambda: FIXED_NOW,
        **options: Any,
    ) -> PisteClient:
        throttle = SharedThrottle(directory / "net", "legifrance", 0.0, sleep=no_sleep)
        caches: dict[str, Any] = {}
        if cached:
            caches = {
                "lasting": ResponseCache(directory / "versions", timedelta(days=30), now),
                "daily": ResponseCache(directory / "daily", timedelta(hours=24), now),
            }
        return PisteClient(
            throttle,
            secrets,
            transport=httpx.MockTransport(self),
            resolver=self.dns,
            now=now,
            **caches,
            **options,
        )
