"""Offline doubles for the scholarly tests: a fake API behind ``httpx.MockTransport``, a rate
limiter that never sleeps, and builders of Atom feeds and Crossref works (shapes taken from the
real answers of 2026-10-21, texts invented).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import httpx

from core.net.throttle import SharedThrottle
from plugins.scholarly.common import Fetcher
from tests.net_doubles import chunks

FIXED_NOW = datetime(2026, 10, 22, 9, 30, tzinfo=UTC)
STAMP = "2026-10-22T09:30:00+00:00"
ATOM_TYPE = "application/atom+xml; charset=utf-8"
JSON_TYPE = "application/json"


async def no_sleep(_: float) -> None:
    await asyncio.sleep(0)


def respond(
    body: bytes | str = b"", status: int = 200, content_type: str | None = ATOM_TYPE
) -> httpx.Response:
    data = body.encode("utf-8") if isinstance(body, str) else body
    headers = {"content-type": content_type} if content_type else {}
    return httpx.Response(status, headers=headers, content=chunks(data))


Handler = Callable[[httpx.Request], Awaitable[httpx.Response] | httpx.Response]


@dataclass
class FakeApi:
    """Answers every request with ``handler`` and keeps the requests for inspection."""

    handler: Handler
    requests: list[httpx.Request] = field(default_factory=list)

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        result = self.handler(request)
        return await result if isinstance(result, Awaitable) else result

    def fetcher(self, directory: Path, label: str = "arXiv", **options: Any) -> Fetcher:
        throttle = SharedThrottle(directory, label.lower(), 0.0, sleep=no_sleep)
        return Fetcher(label, throttle, transport=httpx.MockTransport(self), **options)


def static(response: Callable[[], httpx.Response]) -> FakeApi:
    return FakeApi(lambda _: response())


def entry(
    identifier: str = "2401.01234v2",
    title: str = "Un titre de test",
    published: str = "2024-01-03T18:00:00Z",
    updated: str = "2024-02-10T08:00:00Z",
    authors: tuple[str, ...] = ("Ada Lovelace", "Alan Turing"),
    summary: str = "Un résumé de test.",
    doi: str | None = None,
    journal_ref: str | None = None,
    id_base: str = "http://arxiv.org/abs/",
) -> str:
    parts = [f"<id>{id_base}{escape(identifier)}</id>"]
    if title:
        parts.append(f"<title>{escape(title)}</title>")
    if updated:
        parts.append(f"<updated>{updated}</updated>")
    if published:
        parts.append(f"<published>{published}</published>")
    parts.append(f"<summary>{escape(summary)}</summary>")
    parts += [f"<author><name>{escape(name)}</name></author>" for name in authors]
    if doi is not None:
        parts.append(f"<arxiv:doi>{escape(doi)}</arxiv:doi>")
    if journal_ref is not None:
        parts.append(f"<arxiv:journal_ref>{escape(journal_ref)}</arxiv:journal_ref>")
    return "<entry>" + "".join(parts) + "</entry>"


def feed(*entries: str) -> str:
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom" '
        'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
        "<id>https://arxiv.org/api/test</id><title>arXiv Query</title>"
        f"<opensearch:totalResults>{len(entries)}</opensearch:totalResults>"
        + "".join(entries)
        + "</feed>"
    )


ERROR_FEED = feed(
    "<entry><id>https://arxiv.org/api/errors#incorrect_id_format_for_1234</id>"
    "<title>Error</title><summary>incorrect id format for 1234</summary></entry>"
)


def work(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "DOI": "10.1234/abc.5678",
        "title": ["Un article de test"],
        "author": [{"given": "Ada", "family": "Lovelace"}, {"name": "Consortium X"}],
        "issued": {"date-parts": [[2024, 2, 5]]},
        "published": {"date-parts": [[2024, 3]]},
        "container-title": ["Revue de test"],
        "type": "journal-article",
        "abstract": "<jats:title>Abstract</jats:title><jats:p>Un r&#233;sum&#233;.</jats:p>",
    }
    base.update(overrides)
    return {key: value for key, value in base.items() if value is not None}


def message(kind: str, payload: Any) -> str:
    return json.dumps({"status": "ok", "message-type": kind, "message": payload})


def work_list(*works: dict[str, Any]) -> str:
    return message("work-list", {"items": list(works), "total-results": len(works)})
