"""The GET of a feed, against a fake DNS and a fake web: pinned, bounded, never redirected."""

from __future__ import annotations

import asyncio
import gzip
from typing import Any

import httpx
import pytest

from plugins.feeds.models import FeedError
from plugins.feeds.reader import USER_AGENT, FeedReader
from plugins.feeds.tests.support import FEED_URL, rss, rss_item
from tests.net_doubles import PUBLIC_V4, FakeDns, FakeWeb, chunks

HOST = "feeds.example"
PATH = "/research.xml"
RSS_TYPE = "application/rss+xml; charset=utf-8"


def _reader(web: FakeWeb, dns: FakeDns | None = None, **options: Any) -> FeedReader:
    names = FakeDns({HOST: [PUBLIC_V4]}) if dns is None else dns
    return FeedReader(resolver=names, transport=httpx.MockTransport(web), **options)


def _fetch(reader: FeedReader, url: str = FEED_URL) -> bytes:
    return asyncio.run(reader.fetch(url))


def _refused(reader: FeedReader, url: str = FEED_URL) -> str:
    with pytest.raises(FeedError) as caught:
        _fetch(reader, url)
    return str(caught.value)


def test_the_feed_is_read_on_the_checked_address() -> None:
    body = rss([rss_item()])
    web = FakeWeb()
    web.page(HOST, PATH, body, content_type=RSS_TYPE)
    assert _fetch(_reader(web)) == body
    (request,) = web.requests
    assert request.url.host == PUBLIC_V4
    assert request.headers["host"] == HOST
    assert request.headers["user-agent"] == USER_AGENT
    assert "application/rss+xml" in request.headers["accept"]
    assert request.extensions["sni_hostname"] == HOST


@pytest.mark.parametrize(
    "content_type",
    ["application/atom+xml", "application/xml", "text/xml; charset=iso-8859-1", "TEXT/XML"],
)
def test_the_xml_media_types_are_accepted(content_type: str) -> None:
    web = FakeWeb()
    web.page(HOST, PATH, b"<rss/>", content_type=content_type)
    assert _fetch(_reader(web)) == b"<rss/>"


def test_a_gzip_body_is_inflated() -> None:
    body = rss([rss_item()])
    web = FakeWeb()
    web.page(HOST, PATH, gzip.compress(body), content_type=RSS_TYPE, content_encoding="gzip")
    assert _fetch(_reader(web)) == body


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_a_redirect_is_refused_and_not_followed(status: int) -> None:
    web = FakeWeb()
    web.redirect(HOST, PATH, "https://feeds.example/new.xml", status)
    web.page(HOST, "/new.xml", b"<rss/>", content_type=RSS_TYPE)
    assert "redirection refusée" in _refused(_reader(web))
    assert web.hits("/new.xml") == 0


@pytest.mark.parametrize("status", [204, 403, 404, 500])
def test_a_status_other_than_200_is_refused(status: int) -> None:
    web = FakeWeb()
    web.page(HOST, PATH, b"", status=status, content_type=RSS_TYPE)
    assert _refused(_reader(web)) == f"réponse HTTP {status}"


@pytest.mark.parametrize(
    ("content_type", "shown"),
    [("text/html", "text/html"), (None, "absent"), ("application/x-<script>", "non standard")],
)
def test_other_media_types_are_refused(content_type: str | None, shown: str) -> None:
    web = FakeWeb()
    web.page(HOST, PATH, b"<rss/>", content_type=content_type)
    assert _refused(_reader(web)) == f"type « {shown} » non pris en charge"


def test_a_body_over_the_limit_is_refused() -> None:
    web = FakeWeb()
    web.page(HOST, PATH, b"x" * 2_000, content_type=RSS_TYPE)
    assert "trop volumineuse" in _refused(_reader(web, max_bytes=1_000))


@pytest.mark.parametrize(
    ("names", "url", "reason"),
    [
        ({HOST: ["10.0.0.5"]}, FEED_URL, "adresse non publique"),
        ({HOST: [PUBLIC_V4, "127.0.0.1"]}, FEED_URL, "adresse non publique"),
        ({}, FEED_URL, "nom introuvable"),
        ({HOST: [PUBLIC_V4]}, "https://feeds.example:8443/research.xml", "port interdit"),
        ({}, "https://localhost/research.xml", "machine locale"),
        ({}, "file:///etc/passwd", "schéma"),
    ],
)
def test_the_ssrf_guard_applies_to_allow_listed_urls(
    names: dict[str, list[str]], url: str, reason: str
) -> None:
    web = FakeWeb()
    assert reason in _refused(_reader(web, FakeDns(names)), url)
    assert web.requests == []


def test_a_slow_feed_times_out() -> None:
    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, content=chunks(b""))  # pragma: no cover

    web = FakeWeb()
    web.on(HOST, PATH, slow)
    assert _refused(_reader(web, timeout_s=0.05)) == "délai de 0.05 s dépassé"


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (httpx.ReadTimeout, "délai de 15 s dépassé"),
        (httpx.ConnectError, "connexion impossible"),
        (httpx.RemoteProtocolError, "connexion impossible"),
    ],
)
def test_transport_errors_are_reported_plainly(
    error: type[httpx.TransportError], message: str
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise error("panne", request=request)

    web = FakeWeb()
    web.on(HOST, PATH, fail)
    assert _refused(_reader(web)) == message
