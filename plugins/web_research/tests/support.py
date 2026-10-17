"""Offline doubles for the web_research tests: a fake DNS and a fake web behind MockTransport.

No test opens a socket: names resolve through ``FakeDns`` and every request reaches ``FakeWeb``,
which routes on the ``Host`` header (the URL itself carries the pinned address).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from plugins.web_research.fetcher import WebReader

PUBLIC_V4 = "93.184.215.14"
OTHER_V4 = "151.101.1.69"
FIXED_NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


async def chunks(body: bytes, size: int = 64 * 1024) -> AsyncIterator[bytes]:
    """Streamed body: ``httpx.Response(content=bytes)`` is pre-read and cannot be streamed."""
    for start in range(0, len(body), size):
        yield body[start : start + size]


@dataclass
class FakeDns:
    names: dict[str, list[str]] = field(default_factory=dict)
    queries: list[str] = field(default_factory=list)

    async def __call__(self, host: str, port: int) -> Sequence[str]:
        self.queries.append(host)
        if host not in self.names:
            raise OSError("name not found")
        return self.names[host]


Handler = Callable[[httpx.Request], Awaitable[httpx.Response] | httpx.Response]


@dataclass
class FakeWeb:
    """Routes ``(Host header, raw path)`` to a response; anything else is a 404."""

    routes: dict[tuple[str, str], Handler] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)

    def page(
        self,
        host: str,
        path: str,
        body: bytes | str = b"",
        status: int = 200,
        content_type: str | None = "text/html; charset=utf-8",
        **headers: str,
    ) -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        all_headers = {k.replace("_", "-"): v for k, v in headers.items()}
        if content_type is not None:
            all_headers["content-type"] = content_type

        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(status, headers=all_headers, content=chunks(data))

        self.routes[(host, path)] = respond

    def redirect(self, host: str, path: str, location: str | None, status: int = 302) -> None:
        headers = {} if location is None else {"location": location}
        self.routes[(host, path)] = lambda _: httpx.Response(status, headers=headers)

    def on(self, host: str, path: str, handler: Handler) -> None:
        self.routes[(host, path)] = handler

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.headers["host"], request.url.raw_path.decode("ascii"))
        handler = self.routes.get(key)
        if handler is None:
            return httpx.Response(404, content=chunks(b""))
        result = handler(request)
        return await result if isinstance(result, Awaitable) else result

    def hits(self, path: str) -> int:
        return sum(1 for r in self.requests if r.url.raw_path.decode("ascii") == path)


def make_reader(web: FakeWeb, dns: FakeDns, **options: Any) -> WebReader:
    return WebReader(
        resolver=dns,
        transport=httpx.MockTransport(web),
        clock=lambda: FIXED_NOW,
        **options,
    )


ARTICLE = """<html><head><title>Titre de test</title>
<meta property="article:published_time" content="2024-05-01T10:00:00Z"></head>
<body><nav>menu accueil contact</nav><article><h1>Titre de test</h1>
<p>Le premier paragraphe de l'article explique en détail le sujet principal de la page avec
assez de mots pour être retenu par l'extracteur.</p>
<p>Un second paragraphe ajoute des précisions utiles et un chiffre : 42 pour cent.</p>
</article><footer>pied de page</footer></body></html>"""
