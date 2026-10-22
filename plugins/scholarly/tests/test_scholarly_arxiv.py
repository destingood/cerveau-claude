"""arXiv: query building, Atom parsing (defusedxml) and the source behind a fake API."""

from __future__ import annotations

import asyncio
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from hypothesis import given
from hypothesis import strategies as st

from plugins.scholarly.arxiv import (
    MAX_ABSTRACT_CHARS,
    ArxivSource,
    is_arxiv_id,
    parse_feed,
    search_query,
)
from plugins.scholarly.common import ScholarError
from plugins.scholarly.tests.support import (
    ERROR_FEED,
    FIXED_NOW,
    STAMP,
    FakeApi,
    entry,
    feed,
    respond,
    static,
)

TERM = re.compile(r"all:[^\W_]+")


def _parse(*entries: str, since: date | None = None) -> list:
    return parse_feed(feed(*entries).encode(), since, STAMP)


def _source(api: FakeApi, directory: Path) -> ArxivSource:
    return ArxivSource(api.fetcher(directory), now=lambda: FIXED_NOW)


def _params(api: FakeApi) -> dict[str, list[str]]:
    (request,) = api.requests
    return parse_qs(urlsplit(str(request.url)).query)


@pytest.mark.parametrize(
    "value", ["1706.03762", "1706.03762v7", "2401.01234", "hep-th/9901001", "math.GT/0309136v2"]
)
def test_arxiv_identifiers_are_recognised(value: str) -> None:
    assert is_arxiv_id(value)


@pytest.mark.parametrize(
    "value", ["", "1706.037", "1706.03762v", "10.1234/x", "HEP-TH/9901001", "a/b", "1706.03762 "]
)
def test_other_strings_are_not_arxiv_identifiers(value: str) -> None:
    assert not is_arxiv_id(value)


def test_the_query_keeps_only_words_so_no_syntax_can_be_injected() -> None:
    query = 'ti:"x") OR (cat:* ANDNOT au_Doe [Étude]'
    expected = "all:ti AND all:x AND all:or AND all:cat AND all:andnot AND all:au AND all:doe"
    assert search_query(query, None, FIXED_NOW) == f"{expected} AND all:étude"


def test_the_query_has_at_most_twelve_words() -> None:
    words = search_query(" ".join(f"w{i}" for i in range(20)), None, FIXED_NOW).split(" AND ")
    assert words == [f"all:w{i}" for i in range(12)]


def test_since_becomes_a_submission_date_range_up_to_now() -> None:
    query = search_query("graph", date(2024, 2, 5), FIXED_NOW)
    assert query == "all:graph AND submittedDate:[202402050000 TO 202610220930]"


def test_a_query_without_words_is_refused() -> None:
    with pytest.raises(ScholarError, match="aucun mot cherchable"):
        search_query("_ -- !? «»", None, FIXED_NOW)


@given(st.text(max_size=400))
def test_every_term_of_any_query_is_a_plain_word(query: str) -> None:
    try:
        built = search_query(query, None, FIXED_NOW)
    except ScholarError:
        return
    terms = built.split(" AND ")
    assert 1 <= len(terms) <= 12
    assert all(TERM.fullmatch(term) for term in terms)


def test_an_entry_becomes_a_record() -> None:
    (record,) = _parse(
        entry(
            title="  Un\ntitre​  ",
            doi="10.1234/abc",
            journal_ref="Revue X 12 (2024)",
            id_base="https://arxiv.org/abs/",
        )
    )
    assert record.model_dump() == {
        "source": "arxiv",
        "identifier": "2401.01234v2",
        "type": "preprint",
        "preprint": True,
        "title": "Un titre",
        "authors": ["Ada Lovelace", "Alan Turing"],
        "more_authors": 0,
        "published": "2024-01-03",
        "updated": "2024-02-10",
        "venue": "Revue X 12 (2024)",
        "doi": "10.1234/abc",
        "url": "https://arxiv.org/abs/2401.01234v2",
        "abstract": "Un résumé de test.",
        "abstract_truncated": False,
        "update_to": [],
        "updated_by": [],
        "retrieved_at": STAMP,
    }


def test_optional_fields_may_be_missing_or_invalid() -> None:
    (record,) = _parse(entry(updated="", summary="", authors=(), doi="not a doi"))
    assert (record.updated, record.abstract, record.authors, record.doi, record.venue) == (
        None,
        None,
        [],
        None,
        None,
    )


def test_long_author_lists_and_abstracts_are_cut() -> None:
    names = tuple(f"Auteur {i}" for i in range(13))
    (record,) = _parse(entry(authors=(*names, " "), summary="mot " * 1000))
    assert record.authors == list(names[:10])
    assert record.more_authors == 3
    assert record.abstract_truncated
    assert len(record.abstract) == MAX_ABSTRACT_CHARS
    assert record.abstract.endswith("…")


@pytest.mark.parametrize(
    "bad",
    [
        entry(identifier="not-an-id"),
        entry(identifier="2401.01234", id_base="https://evil.example/abs/"),
        entry(title=""),
        entry(title=" ​ "),
        entry(published=""),
        entry(published="hier"),
    ],
)
def test_entries_without_identifier_title_or_date_are_skipped(bad: str) -> None:
    assert [r.identifier for r in _parse(bad, entry())] == ["2401.01234v2"]


def test_since_drops_older_entries() -> None:
    older = entry("2401.00001", published="2024-01-31T23:59:59Z")
    newer = entry("2402.00002", published="2024-02-01T00:00:00Z")
    records = _parse(older, newer, since=date(2024, 2, 1))
    assert [r.identifier for r in records] == ["2402.00002"]
    assert len(_parse(older, newer)) == 2


def test_an_error_entry_is_an_error() -> None:
    with pytest.raises(ScholarError, match=r"arXiv : requête refusée \(identifiant ou syntaxe"):
        parse_feed(ERROR_FEED.encode(), None, STAMP)


@pytest.mark.parametrize(
    "body",
    [
        b"<feed",
        b"",
        b"\xff\xfe<",
        b'<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b'<feed xmlns="http://www.w3.org/2005/Atom"><title>&x;</title></feed>',
        b'<!DOCTYPE lol [<!ENTITY a "aaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        b"<feed>&b;</feed>",
        b'<!DOCTYPE feed SYSTEM "http://evil.example/feed.dtd"><feed/>',
    ],
)
def test_unreadable_or_dangerous_xml_is_refused(body: bytes) -> None:
    with pytest.raises(ScholarError, match="arXiv : réponse illisible"):
        parse_feed(body, None, STAMP)


def test_a_document_that_is_not_an_atom_feed_is_refused() -> None:
    with pytest.raises(ScholarError, match="pas un flux Atom"):
        parse_feed(b"<html><body>Maintenance</body></html>", None, STAMP)


def test_search_asks_the_api_and_caps_the_records(tmp_path: Path) -> None:
    api = static(lambda: respond(feed(entry("2401.00001"), entry("2401.00002"))))
    records = asyncio.run(_source(api, tmp_path).search("Graph neural", None, 1))
    assert [r.identifier for r in records] == ["2401.00001"]
    assert _params(api) == {
        "search_query": ["all:graph AND all:neural"],
        "start": ["0"],
        "max_results": ["1"],
    }
    assert api.requests[0].headers["accept"] == "application/atom+xml"


def test_search_since_sorts_by_submission_date(tmp_path: Path) -> None:
    api = static(lambda: respond(feed(entry(published="2024-03-01T00:00:00Z"))))
    records = asyncio.run(_source(api, tmp_path).search("graph", date(2024, 2, 5), 5))
    assert len(records) == 1
    params = _params(api)
    assert params["sortBy"] == ["submittedDate"]
    assert params["sortOrder"] == ["descending"]
    assert params["search_query"] == ["all:graph AND submittedDate:[202402050000 TO 202610220930]"]


def test_record_reads_one_identifier(tmp_path: Path) -> None:
    api = static(lambda: respond(feed(entry("1706.03762v7"))))
    record = asyncio.run(_source(api, tmp_path).record("1706.03762"))
    assert record.identifier == "1706.03762v7"
    assert _params(api) == {"id_list": ["1706.03762"], "max_results": ["1"]}


def test_record_of_an_unknown_identifier_is_an_error(tmp_path: Path) -> None:
    api = static(lambda: respond(feed()))
    with pytest.raises(ScholarError, match="arXiv : identifiant inconnu"):
        asyncio.run(_source(api, tmp_path).record("2401.99999"))


def test_a_refusal_of_the_api_is_explained(tmp_path: Path) -> None:
    api = static(lambda: respond(ERROR_FEED, status=400))
    with pytest.raises(ScholarError, match="identifiant ou syntaxe invalide"):
        asyncio.run(_source(api, tmp_path).record("2401.01234"))


def test_a_bare_http_400_is_an_error(tmp_path: Path) -> None:
    api = static(lambda: respond(feed(entry()), status=400))
    with pytest.raises(ScholarError, match=r"arXiv : requête refusée \(HTTP 400\)"):
        asyncio.run(_source(api, tmp_path).record("2401.01234"))


@pytest.mark.parametrize("content_type", ["text/html; charset=utf-8", None])
def test_a_reply_that_is_not_xml_is_refused(tmp_path: Path, content_type: str | None) -> None:
    api = static(lambda: respond(feed(entry()), content_type=content_type))
    with pytest.raises(ScholarError, match="arXiv : type de contenu inattendu"):
        asyncio.run(_source(api, tmp_path).search("graph", None, 5))
