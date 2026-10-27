"""Fixtures of the Juridique FR pack's evals (ADR-060): the fake Légifrance API a case describes,
served to the real legifrance server.

Every request goes through ``httpx.MockTransport`` after a fake DNS that names a public address,
under a rate limit that never waits and without a cache: no request leaves the machine. The
PISTE environment is set in a copy of the configuration, never in ``config/`` of the repository,
and the credentials are stand-ins that must never reach an answer or a log (R6).
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx

from core.evals.cases import LegalFixture, LegiVersionFixture
from core.net.throttle import SharedThrottle
from plugins.legifrance.client import (
    API_PATH,
    ENVIRONMENTS,
    HOSTS,
    MAX_BYTES,
    OAUTH_PATH,
    Credentials,
    PisteClient,
)
from plugins.legifrance.server import Sources
from plugins.legifrance.settings import config_target

# The credentials and token of a case that has them: canaries, never in an answer or a log (R6).
STAND_IN_ID = "canari-piste-id-factice"
STAND_IN_SECRET = "canari-piste-secret-factice"  # noqa: S105 - invented canary
STAND_IN_TOKEN = "canari-piste-jeton-factice"  # noqa: S105 - invented canary
PUBLIC_V4 = "93.184.215.14"  # the address of every PISTE name, so the network guard lets it be
OPEN_END = date(2999, 1, 1)  # how Légifrance writes a version with no end
EXTRACT_CHARS = 200
SOURCES_FILE = "data_sources.yaml"
URLS = {env.name: url.encode("ascii") for url, env in ENVIRONMENTS.items()}
# The url line of the legifrance block, whatever Lucas wrote there: the case decides in its copy.
_URL_LINE = re.compile(rb"^(    url: )[^ \t\r\n#]+([ \t]*(?:#[^\r\n]*)?\r?\n)", re.M)
_BLOCK = re.compile(rb"\n  legifrance:\r?\n")
_NEXT_KEY = re.compile(rb"\n(?:  )?[^ \r\n#]")  # the next key of the block's level or above


async def _no_sleep(_: float) -> None:
    await asyncio.sleep(0)


async def _chunks(body: bytes, size: int = 64 * 1024) -> AsyncIterator[bytes]:
    for start in range(0, len(body), size):
        yield body[start : start + size]


def _respond(data: Any, status: int = 200) -> httpx.Response:
    body = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
    headers = {"content-type": "application/json"}
    return httpx.Response(status, headers=headers, content=_chunks(body))


async def _resolve(host: str, port: int) -> Sequence[str]:
    if host not in HOSTS:
        raise OSError("name not found")
    return [PUBLIC_V4]


def millis(day: date) -> int:
    """A day as Légifrance writes it: milliseconds since 1970, at midnight UTC."""
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)


def _end(version: LegiVersionFixture) -> int:
    return millis(version.end or OPEN_END)


class FixturePiste:
    """The token endpoint and the three API routes of one case, routed on the ``Host`` header
    (the URL carries the pinned address) and on the path."""

    def __init__(self, fixture: LegalFixture, today: date) -> None:
        self.fixture, self.today = fixture, today
        self.requests: list[httpx.Request] = []
        self._by_id = {version.id: version for version in fixture.versions}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.headers.get("host", "")
        if host not in HOSTS:
            return _respond({"error": "not found"}, 404)
        if request.url.path == OAUTH_PATH:
            return self._token(parse_qs(request.content.decode("ascii")))
        if request.headers.get("authorization") != f"Bearer {STAND_IN_TOKEN}":
            return _respond({"error": "invalid_token"}, 401)
        if self.fixture.down:
            return _respond({"error": "service unavailable"}, 503)
        if self.fixture.oversized:
            return _respond(b" " * (MAX_BYTES + 1))
        route = request.url.path.removeprefix(API_PATH)
        payload = json.loads(request.content)
        if route == "/consult/getArticle":
            asked = str(payload.get("id", ""))
            return _respond(self._article(self._by_id.get(self.fixture.swapped.get(asked, asked))))
        if route == "/consult/getArticleWithIdAndNum":
            return _respond(self._article(self._in_force(payload)))
        if route == "/search":
            return _respond(self._search(payload))
        return _respond({"error": "not found"}, 404)

    def _token(self, form: dict[str, list[str]]) -> httpx.Response:
        given = (form.get("client_id", [""])[0], form.get("client_secret", [""])[0])
        if form.get("grant_type") != ["client_credentials"] or given != (
            STAND_IN_ID,
            STAND_IN_SECRET,
        ):
            return _respond({"error": "invalid_client"}, 401)
        return _respond({"access_token": STAND_IN_TOKEN, "expires_in": 3600, "token_type": "x"})

    def _siblings(self, version: LegiVersionFixture) -> list[LegiVersionFixture]:
        found = [
            v
            for v in self.fixture.versions
            if v.text_id == version.text_id and v.num == version.num
        ]
        return sorted(found, key=lambda v: v.start)

    def _in_force(self, payload: dict[str, Any]) -> LegiVersionFixture | None:
        """The version Légifrance calls in force today: the latest one started by then."""
        parent, num = str(payload.get("id", "")), str(payload.get("num", ""))
        started = [
            v
            for v in self.fixture.versions
            if v.text_id == parent and v.num.casefold() == num.casefold() and v.start <= self.today
        ]
        return max(started, key=lambda v: v.start, default=None)

    def _article(self, version: LegiVersionFixture | None) -> dict[str, Any]:
        if version is None:
            return {"article": None, "executionTime": 1}
        siblings = self._siblings(version)
        nature = "CODE" if version.code else "LOI"
        return {
            "article": {
                "id": version.id,
                "cid": siblings[0].id,
                "num": version.num,
                "etat": version.state,
                "dateDebut": millis(version.start),
                "dateFin": _end(version),
                "texte": version.text,
                "textTitles": [
                    {
                        "id": version.text_id,
                        "cid": version.text_id,
                        "titre": version.title,
                        "nature": nature,
                    }
                ],
                "articleVersions": [
                    {
                        "id": v.id,
                        "dateDebut": millis(v.start),
                        "dateFin": _end(v),
                        "etat": v.state,
                    }
                    for v in siblings
                ],
            },
            "executionTime": 1,
        }

    def _search(self, payload: dict[str, Any]) -> dict[str, Any]:
        search = payload.get("recherche", {})
        try:
            word = str(search["champs"][0]["criteres"][0]["valeur"]).casefold()
        except (KeyError, IndexError, TypeError):
            word = ""
        ids = next((v for k, v in self.fixture.searches.items() if k.casefold() == word), ())
        size = int(search.get("pageSize", 10))
        results = []
        for identifier in ids[:size]:
            version = self._by_id[identifier]
            results.append(
                {
                    "titles": [
                        {
                            "id": version.text_id,
                            "cid": version.text_id,
                            "title": version.title,
                            "legalStatus": "VIGUEUR",
                        }
                    ],
                    "sections": [
                        {
                            "extracts": [
                                {
                                    "id": version.id,
                                    "num": version.num,
                                    "legalStatus": version.state,
                                    "dateDebut": millis(version.start),
                                    "dateFin": _end(version),
                                    "values": [version.text[:EXTRACT_CHARS]],
                                }
                            ]
                        }
                    ],
                }
            )
        return {"totalResultNumber": len(ids), "results": results}


def legal_config(source: Path, folder: Path, fixture: LegalFixture) -> Path:
    """A copy of the configuration whose ``sources.legifrance.url`` names the case's PISTE
    environment (H4), never the original: ``A_DEFINIR`` stays when the case says so."""
    target = folder / "config"
    if not target.exists():
        target.mkdir(parents=True)
        for path in source.glob("*.yaml"):
            shutil.copyfile(path, target / path.name)
        sources = target / SOURCES_FILE
        text = sources.read_bytes()
        found = _BLOCK.search(text)
        if found is None:
            raise ValueError(f"{SOURCES_FILE} : bloc sources.legifrance absent")
        begin = found.start() + 1
        after = _NEXT_KEY.search(text, begin)
        end = len(text) if after is None else after.start() + 1
        wanted = URLS.get(fixture.environment, b"A_DEFINIR")
        block = _URL_LINE.sub(lambda m: m.group(1) + wanted + m.group(2), text[begin:end], count=1)
        sources.write_bytes(text[:begin] + block + text[end:])
    return target


def legal_sources(
    fixture: LegalFixture, folder: Path, config_dir: Path, now: Callable[[], datetime]
) -> Sources:
    """The legifrance sources of a case: the real client and parsers on its fake API."""
    piste = FixturePiste(fixture, now().date())
    client = PisteClient(
        SharedThrottle(folder / "net", "legifrance", 0.0, sleep=_no_sleep),
        Credentials(STAND_IN_ID, STAND_IN_SECRET) if fixture.credentials else None,
        transport=httpx.MockTransport(piste),
        resolver=_resolve,
        now=now,
    )
    return Sources(client, target=config_target(config_dir), now=now)
