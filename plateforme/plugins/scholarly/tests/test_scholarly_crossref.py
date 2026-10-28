"""Crossref: parsing of works and the source behind a fake API."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from plugins.scholarly.common import MAX_NAME_CHARS, ScholarError
from plugins.scholarly.crossref import MAX_ABSTRACT_CHARS, SELECT, CrossrefSource, parse_work
from plugins.scholarly.tests.support import (
    FIXED_NOW,
    JSON_TYPE,
    STAMP,
    FakeApi,
    message,
    respond,
    static,
    work,
    work_list,
)


def _source(api: FakeApi, directory: Path) -> CrossrefSource:
    return CrossrefSource(api.fetcher(directory, label="Crossref"), now=lambda: FIXED_NOW)


def _json(body: str, status: int = 200) -> FakeApi:
    return static(lambda: respond(body, status=status, content_type=JSON_TYPE))


def test_a_work_becomes_a_record() -> None:
    record = parse_work(work(), None, STAMP)
    assert record is not None
    assert record.model_dump() == {
        "source": "crossref",
        "identifier": "10.1234/abc.5678",
        "type": "journal-article",
        "preprint": False,
        "title": "Un article de test",
        "authors": ["Ada Lovelace", "Consortium X"],
        "more_authors": 0,
        "published": "2024-02-05",
        "updated": None,
        "venue": "Revue de test",
        "doi": "10.1234/abc.5678",
        "url": "https://doi.org/10.1234/abc.5678",
        "abstract": "Un résumé.",
        "abstract_truncated": False,
        "update_to": [],
        "updated_by": [],
        "retrieved_at": STAMP,
    }


def test_the_first_date_is_the_earliest_of_issued_published_and_posted() -> None:
    dated = work(
        issued={"date-parts": [[2024, 5]]},
        published={"date-parts": [[2023]]},
        posted={"date-parts": [[2023, 11, 2]]},
        type="posted-content",
    )
    record = parse_work(dated, None, STAMP)
    assert record is not None
    assert (record.published, record.preprint) == ("2023", True)


@pytest.mark.parametrize(
    "dates",
    [
        {"issued": None, "published": None},
        {"issued": {"date-parts": []}, "published": "2024"},
        {"issued": {"date-parts": [None]}, "published": {"date-parts": [["2024"]]}},
    ],
)
def test_a_work_without_a_usable_date_has_none(dates: dict[str, Any]) -> None:
    record = parse_work(work(**dates), None, STAMP)
    assert record is not None
    assert record.published is None
    assert parse_work(work(**dates), date(2000, 1, 1), STAMP) is None


def test_since_drops_works_that_may_be_older() -> None:
    since = date(2024, 2, 1)
    assert parse_work(work(published=None), since, STAMP) is not None
    assert parse_work(work(issued={"date-parts": [[2024]]}, published=None), since, STAMP) is None
    assert parse_work(work(issued={"date-parts": [[2024, 1, 31]]}), since, STAMP) is None


@pytest.mark.parametrize(
    "bad",
    [
        "not a mapping",
        work(DOI=None),
        work(DOI="10.12/x"),
        work(DOI="https://doi.org/10.1234/x"),
        work(DOI=12345),
        work(title=None),
        work(title=[]),
        work(title=["  ", None, 3]),
        work(title="Un titre hors liste"),
    ],
)
def test_works_without_doi_or_title_are_skipped(bad: Any) -> None:
    assert parse_work(bad, None, STAMP) is None


def test_messy_fields_are_cleaned_and_bounded() -> None:
    authors = [{"given": "A" * 300, "family": "B"}, "x", {"given": 3}, {"family": "Seule"}]
    authors += [{"name": f"Auteur {i}"} for i in range(12)]
    record = parse_work(
        work(
            title=[None, " Un‮ titre\n "],
            author=authors,
            abstract="<p>" + "mot " * 400 + "</p>",
            type=None,
            **{"container-title": "pas une liste"},
        ),
        None,
        STAMP,
    )
    assert record is not None
    assert record.title == "Un titre"
    assert record.authors[0] == "A" * MAX_NAME_CHARS
    assert record.authors[1:3] == ["Seule", "Auteur 0"]
    assert record.more_authors == 4
    assert record.abstract is not None
    assert len(record.abstract) == MAX_ABSTRACT_CHARS
    assert record.abstract_truncated
    assert (record.type, record.venue) == ("inconnu", None)


def test_updates_and_retractions_are_kept() -> None:
    retraction = {"type": "retraction", "DOI": "10.1234/retract.1", "updated": {}}
    record = parse_work(
        work(
            **{
                "updated-by": [retraction, {"type": "", "DOI": "10.1234/x"}, "x", {"type": "x"}],
                "update-to": [{"type": "correction", "DOI": f"10.1234/c{i}"} for i in range(12)],
            }
        ),
        None,
        STAMP,
    )
    assert record is not None
    assert [u.model_dump() for u in record.updated_by] == [
        {"type": "retraction", "doi": "10.1234/retract.1"}
    ]
    assert len(record.update_to) == 10


def test_old_sici_dois_with_angle_brackets_are_out_of_scope() -> None:
    # The pattern Crossref recommends for modern DOIs; SICI ones of the 1990s fall outside it.
    sici = "10.1002/(SICI)1097-0258(19980815/30)17:15/16<1661::AID>3.0.CO;2-2"
    assert parse_work(work(DOI=sici), None, STAMP) is None


@pytest.mark.parametrize(
    "doi", ["10.1234/../../members", "10.1234/./x", "10.1234/x/..", "10.1234/a/../b"]
)
def test_dois_with_dot_segments_are_refused(doi: str) -> None:
    # Once in the API's address, such a segment would reach another of its paths.
    assert parse_work(work(DOI=doi), None, STAMP) is None
    assert parse_work(work(DOI="10.1234/a..b/c.d"), None, STAMP) is not None


def test_the_doi_is_quoted_in_the_url() -> None:
    record = parse_work(work(DOI="10.1002/(SICI)1097-0258;2-2"), None, STAMP)
    assert record is not None
    assert record.url == "https://doi.org/10.1002/%28SICI%291097-0258%3B2-2"


def test_search_asks_the_api_and_caps_the_records(tmp_path: Path) -> None:
    works = [work(DOI=f"10.1234/w{i}") for i in range(3)]
    api = _json(work_list(work(DOI="bad"), *works))
    records = asyncio.run(_source(api, tmp_path).search("graph neural", None, 2))
    assert [r.doi for r in records] == ["10.1234/w0", "10.1234/w1"]
    (request,) = api.requests
    assert request.url.path == "/works"
    assert parse_qs(urlsplit(str(request.url)).query) == {
        "query": ["graph neural"],
        "rows": ["2"],
        "select": [SELECT],
    }
    assert "mailto" not in str(request.url)
    assert request.headers["accept"] == "application/json"


def test_search_since_filters_on_the_publication_date(tmp_path: Path) -> None:
    api = _json(work_list(work(), work(DOI="10.1234/old", issued={"date-parts": [[2020]]})))
    records = asyncio.run(_source(api, tmp_path).search("graph", date(2023, 1, 1), 5))
    assert [r.doi for r in records] == ["10.1234/abc.5678"]
    (request,) = api.requests
    assert parse_qs(urlsplit(str(request.url)).query)["filter"] == ["from-pub-date:2023-01-01"]


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ("{not json", "réponse illisible"),
        ("\udcff", "réponse illisible"),
        ("[]", "réponse inattendue"),
        (message("work", {"items": []}), "réponse inattendue"),
        ('{"message-type": "work-list", "message": "x"}', "réponse inattendue"),
    ],
)
def test_unexpected_search_replies_are_errors(tmp_path: Path, body: str, error: str) -> None:
    api = static(lambda: respond(body.encode("utf-8", "surrogateescape"), content_type=JSON_TYPE))
    with pytest.raises(ScholarError, match=f"Crossref : {error}"):
        asyncio.run(_source(api, tmp_path).search("graph", None, 5))


def test_a_list_without_items_is_empty(tmp_path: Path) -> None:
    api = _json(message("work-list", {"items": "x"}))
    assert asyncio.run(_source(api, tmp_path).search("graph", None, 5)) == []


@pytest.mark.parametrize("status", [404, 400])
def test_search_reads_only_successful_replies(tmp_path: Path, status: int) -> None:
    with pytest.raises(ScholarError, match=f"Crossref : réponse HTTP {status} inattendue"):
        asyncio.run(_source(_json("{}", status=status), tmp_path).search("graph", None, 5))


def test_a_reply_that_is_not_json_is_refused(tmp_path: Path) -> None:
    for call in ("search", "record"):
        api = static(lambda: respond(work_list(), content_type="text/html"))
        source = _source(api, tmp_path)
        coroutine = source.search("x", None, 5) if call == "search" else source.record("10.1/x")
        with pytest.raises(ScholarError, match="Crossref : type de contenu inattendu"):
            asyncio.run(coroutine)


def test_record_reads_one_doi(tmp_path: Path) -> None:
    api = _json(message("work", work(DOI="10.1234/a(b)c")))
    record = asyncio.run(_source(api, tmp_path).record("10.1234/a(b)c"))
    assert record.doi == "10.1234/a(b)c"
    (request,) = api.requests
    assert request.url.raw_path == b"/works/10.1234/a%28b%29c"


def test_record_of_an_unknown_doi_is_an_error(tmp_path: Path) -> None:
    api = static(lambda: respond("Resource not found.", status=404, content_type="text/plain"))
    with pytest.raises(ScholarError, match="Crossref : DOI inconnu"):
        asyncio.run(_source(api, tmp_path).record("10.1234/none"))


def test_record_of_an_unusable_work_is_an_error(tmp_path: Path) -> None:
    api = _json(message("work", work(title=None)))
    with pytest.raises(ScholarError, match="Crossref : notice inutilisable"):
        asyncio.run(_source(api, tmp_path).record("10.1234/abc.5678"))
