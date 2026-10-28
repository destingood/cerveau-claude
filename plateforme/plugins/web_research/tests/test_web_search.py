"""Brave provider and parsing, against MockTransport (no network, no real key)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from plugins.web_research.search import (
    BRAVE_ENDPOINT,
    BraveSearchProvider,
    Hit,
    SearchError,
    parse_brave,
)

FAKE_KEY = "test-key-not-a-secret"


def brave(*results: dict[str, Any]) -> dict[str, Any]:
    return {"type": "search", "web": {"type": "search", "results": list(results)}}


def test_parse_strips_markup_and_keeps_order() -> None:
    data = brave(
        {
            "title": "<strong>Matcha</strong> &amp; thé",
            "url": "https://a.example/1",
            "description": "Le <strong>matcha</strong>\n est   vert.",
            "age": "2 jours",
        },
        {"title": "Second", "url": "http://b.example/2", "description": "Texte"},
    )
    assert parse_brave(data, 10) == [
        Hit("Matcha & thé", "https://a.example/1", "Le matcha est vert.", "2 jours"),
        Hit("Second", "http://b.example/2", "Texte", None),
    ]


def test_parse_drops_unusable_entries_and_caps_the_count() -> None:
    data = brave(
        {"title": "No URL"},
        {"title": "Bad scheme", "url": "javascript:alert(1)"},
        {"title": "", "url": "https://empty-title.example/"},
        {"title": 3, "url": "https://number-title.example/"},
        "not an object",
        {"title": "Kept", "url": "https://ok.example/", "age": 7},
        {"title": "Over the cap", "url": "https://cap.example/"},
    )
    assert parse_brave(data, 1) == [Hit("Kept", "https://ok.example/", "", None)]


def test_parse_accepts_answers_without_web_results() -> None:
    assert parse_brave({"type": "search"}, 5) == []
    assert parse_brave({"web": {}}, 5) == []


@pytest.mark.parametrize("data", [[], {"web": "x"}, {"web": {"results": "x"}}, "x"])
def test_parse_refuses_unexpected_shapes(data: Any) -> None:
    with pytest.raises(SearchError, match="inattendue"):
        parse_brave(data, 5)


def search(handler: Any, query: str = "matcha", count: int = 3) -> list[Hit]:
    provider = BraveSearchProvider(FAKE_KEY, transport=httpx.MockTransport(handler))
    return asyncio.run(provider.search(query, count))


def test_the_request_follows_the_brave_api() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=brave({"title": "T", "url": "https://t.example/"}))

    assert search(handler, "thé matcha", 3) == [Hit("T", "https://t.example/", "", None)]
    (request,) = seen
    assert str(request.url.copy_with(query=None)) == BRAVE_ENDPOINT
    assert dict(request.url.params) == {"q": "thé matcha", "count": "3"}
    assert request.headers["x-subscription-token"] == FAKE_KEY
    assert request.headers["accept"] == "application/json"


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "clé refusée"), (403, "clé refusée"), (429, "quota"), (500, "statut HTTP 500")],
)
def test_http_errors_are_explained(status: int, message: str) -> None:
    with pytest.raises(SearchError, match=message) as caught:
        search(lambda _: httpx.Response(status, json={"error": FAKE_KEY}))
    assert FAKE_KEY not in str(caught.value)


def test_unreadable_json_is_refused() -> None:
    with pytest.raises(SearchError, match="illisible"):
        search(lambda _: httpx.Response(200, content=b"<html>"))


def test_network_errors_never_show_the_key() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"boom {request.headers['x-subscription-token']}", request=request)

    with pytest.raises(SearchError, match=r"erreur réseau \(ConnectError\)") as caught:
        search(fail)
    assert FAKE_KEY not in str(caught.value)
    assert caught.value.__cause__ is None


def test_timeouts_are_reported() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(SearchError, match="délai"):
        search(slow)


def test_the_key_is_not_in_the_repr() -> None:
    provider = BraveSearchProvider(FAKE_KEY)
    assert FAKE_KEY not in repr(provider)
    assert provider.name == "brave"
