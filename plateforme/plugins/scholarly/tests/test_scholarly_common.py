"""Partial dates and the bounded GET shared by the two sources."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import httpx
import pytest

from plugins.scholarly.common import (
    THROTTLE_DIR,
    USER_AGENT,
    PartialDate,
    Reply,
    ScholarError,
    first_date,
    on_or_after,
)
from plugins.scholarly.tests.support import FakeApi, respond, static

URL = "https://export.arxiv.org/api/query"
OK = frozenset({200})


def _get(api: FakeApi, directory: Path, **options: object) -> Reply:
    fetcher = api.fetcher(directory, **options)  # type: ignore[arg-type]
    return asyncio.run(fetcher.get(URL, {"q": "a b"}, accept="application/x", read_statuses=OK))


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        ([2024], PartialDate(2024)),
        ([2024, 2], PartialDate(2024, 2)),
        ([2024, 2, 29, 99], PartialDate(2024, 2, 29)),
        ([], None),
        ([999], None),
        ([2023, 2, 29], None),
        ([2024, 13], None),
        (["2024"], None),
        ([True], None),
        ([2024, None], None),
    ],
)
def test_partial_dates_from_date_parts(parts: list[object], expected: PartialDate | None) -> None:
    assert PartialDate.of(parts) == expected


def test_partial_dates_print_at_their_precision() -> None:
    assert PartialDate(2024).iso() == "2024"
    assert PartialDate(2024, 2).iso() == "2024-02"
    assert PartialDate(2024, 2, 5).iso() == "2024-02-05"
    assert PartialDate(2024, None, 5).iso() == "2024"


def test_the_first_date_is_the_earliest_known_one() -> None:
    dates = [None, PartialDate(2024, 3), PartialDate(2024, 2, 5), PartialDate(2025)]
    assert first_date(dates) == PartialDate(2024, 2, 5)
    assert first_date([None, None]) is None


def test_since_keeps_only_records_surely_on_or_after_it() -> None:
    since = date(2024, 3, 1)
    assert on_or_after(None, None)
    assert not on_or_after(None, since)
    assert on_or_after(PartialDate(2024, 3), since)
    # A record known to the year only may have appeared in January: it is left out.
    assert not on_or_after(PartialDate(2024), since)
    assert not on_or_after(PartialDate(2024, 2, 29), since)


def test_get_sends_one_bounded_request_and_returns_the_body(tmp_path: Path) -> None:
    api = static(lambda: respond("<feed/>", content_type="Application/Atom+XML; charset=utf-8"))
    reply = _get(api, tmp_path)
    assert reply == Reply(200, "application/atom+xml", b"<feed/>")
    (request,) = api.requests
    assert str(request.url) == f"{URL}?q=a+b"
    assert request.headers["user-agent"] == USER_AGENT
    assert request.headers["accept"] == "application/x"
    assert request.headers["accept-encoding"] == "gzip"
    # The request went through the shared rate limit of the API.
    assert (tmp_path / "arxiv.last").exists()


def test_a_reply_without_content_type_has_an_empty_media_type(tmp_path: Path) -> None:
    assert _get(static(lambda: respond(b"x", content_type=None)), tmp_path).media == ""


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (302, "arXiv : redirection inattendue"),
        (403, "accès refusé (HTTP 403, blocage possible du pool public)"),
        (429, "débit dépassé (HTTP 429), réessayer plus tard"),
        (503, "service indisponible (HTTP 503)"),
        (418, "réponse HTTP 418 inattendue"),
    ],
)
def test_unexpected_statuses_are_errors(tmp_path: Path, status: int, message: str) -> None:
    api = static(lambda: respond(b"", status=status))
    with pytest.raises(ScholarError, match=re.escape(message)):
        _get(api, tmp_path)
    # A redirect is never followed.
    assert len(api.requests) == 1


def test_a_slow_api_hits_the_deadline(tmp_path: Path) -> None:
    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        raise AssertionError("not reached")  # pragma: no cover

    with pytest.raises(ScholarError, match=r"arXiv : délai de 0\.01 s dépassé"):
        _get(FakeApi(slow), tmp_path, timeout_s=0.01)


def test_a_connection_error_is_reported_without_details(tmp_path: Path) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno 111] secret detail", request=request)

    with pytest.raises(ScholarError, match=r"^Crossref : connexion impossible$"):
        _get(FakeApi(refuse), tmp_path, label="Crossref")


def test_an_oversized_body_is_refused(tmp_path: Path) -> None:
    api = static(lambda: respond(b"x" * 200))
    with pytest.raises(ScholarError, match="arXiv : page trop volumineuse"):
        _get(api, tmp_path, max_bytes=100)


def test_an_unsupported_encoding_is_refused(tmp_path: Path) -> None:
    def brotli(_: httpx.Request) -> httpx.Response:
        response = respond(b"x")
        response.headers["content-encoding"] = "br"
        return response

    with pytest.raises(ScholarError, match="arXiv : encodage « br » non pris en charge"):
        _get(FakeApi(brotli), tmp_path)


def test_every_process_shares_the_locks_of_the_project_root(tmp_path: Path) -> None:
    # A plugin started from another working directory waits for the same locks (ADR-044).
    root = Path(__file__).resolve().parents[3]
    assert root / "var" / "net" == THROTTLE_DIR
    script = "from plugins.scholarly.common import THROTTLE_DIR; print(THROTTLE_DIR)"
    env = {**os.environ, "PYTHONPATH": str(root)}
    shown = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert shown.returncode == 0, shown.stderr
    assert Path(shown.stdout.strip()) == THROTTLE_DIR
