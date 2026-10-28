"""RSS 2.0 and Atom 1.0 parsing: bounded texts, safe links, UTC dates, and no DTD at all (D17)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from plugins.feeds.models import FeedError
from plugins.feeds.parser import (
    MAX_SUMMARY_CHARS,
    MAX_TITLE_CHARS,
    ParsedFeed,
    parse_feed,
)
from plugins.feeds.tests.support import FEED_URL, atom, atom_entry, rss, rss_item

DC = ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
CONTENT = ' xmlns:content="http://purl.org/rss/1.0/modules/content/"'


def _parse(body: bytes, since: date | None = None, limit: int = 10) -> ParsedFeed:
    return parse_feed(body, FEED_URL, since, limit)


def test_an_rss_feed_gives_its_entries_in_order() -> None:
    parsed = _parse(rss([rss_item("Premier"), rss_item("Second", link="/b")]))
    assert parsed.title == "Flux RSS"
    assert [e.title for e in parsed.entries] == ["Premier", "Second"]
    first, second = parsed.entries
    assert first.link == "https://feeds.example/a"
    assert first.published == "2026-10-21T08:00:00+00:00"
    assert first.summary == "Résumé"
    assert first.summary_truncated is False
    # A relative link is resolved against the URL of the feed.
    assert second.link == "https://feeds.example/b"
    assert (parsed.skipped, parsed.more_entries) == (0, 0)


def test_an_atom_feed_gives_its_entries_in_order() -> None:
    parsed = _parse(atom([atom_entry("Premier"), atom_entry("Second", published=None)]))
    assert parsed.title == "Flux Atom"
    assert [e.title for e in parsed.entries] == ["Premier", "Second"]
    assert parsed.entries[0].published == "2026-10-21T08:00:00+00:00"
    assert parsed.entries[1].published is None


def test_dates_are_converted_to_utc() -> None:
    parsed = _parse(
        rss(
            [
                rss_item(pub_date="Tue, 21 Oct 2026 10:00:00 +0200"),
                rss_item(pub_date="pas une date"),
                rss_item(pub_date=None, extra="<dc:date>2026-10-20T23:30:00-01:00</dc:date>"),
            ],
            extra_ns=DC,
        )
    )
    assert [e.published for e in parsed.entries] == [
        "2026-10-21T08:00:00+00:00",
        None,
        "2026-10-21T00:30:00+00:00",
    ]


def test_atom_dates_fall_back_on_updated_and_a_naive_date_counts_as_utc() -> None:
    parsed = _parse(
        atom(
            [
                atom_entry(published=None, extra="<updated>2026-10-20T07:00:00</updated>"),
                atom_entry(published="hier"),
            ]
        )
    )
    assert [e.published for e in parsed.entries] == ["2026-10-20T07:00:00+00:00", None]


def test_since_keeps_entries_of_that_day_or_later_and_drops_undated_ones() -> None:
    items = [
        rss_item("Ancien", pub_date="Mon, 20 Oct 2026 23:59:59 GMT"),
        rss_item("Du jour", pub_date="Tue, 21 Oct 2026 00:00:00 GMT"),
        rss_item("Sans date", pub_date=None),
        rss_item("Récent", pub_date="Wed, 22 Oct 2026 06:00:00 GMT"),
    ]
    parsed = _parse(rss(items), since=date(2026, 10, 21))
    assert [e.title for e in parsed.entries] == ["Du jour", "Récent"]
    assert parsed.skipped == 2
    # Without since, the undated entry is kept.
    assert len(_parse(rss(items)).entries) == 4


def test_the_limit_counts_what_is_left_over() -> None:
    parsed = _parse(rss([rss_item(f"N{i}") for i in range(7)]), limit=3)
    assert [e.title for e in parsed.entries] == ["N0", "N1", "N2"]
    assert (parsed.skipped, parsed.more_entries) == (0, 4)


def test_an_entry_without_title_nor_summary_is_skipped() -> None:
    parsed = _parse(rss([rss_item(title=None, description=None), rss_item(title=" ")]))
    assert len(parsed.entries) == 1
    assert parsed.entries[0].title is None
    assert parsed.skipped == 1


def test_texts_are_stripped_of_markup_and_bounded() -> None:
    long_title = "T" * (MAX_TITLE_CHARS + 50)
    summary = "<p>Un <b>résumé</b>&amp;co​‮</p>" + "x" * MAX_SUMMARY_CHARS
    parsed = _parse(rss([rss_item(long_title, description=summary)]))
    entry = parsed.entries[0]
    assert entry.title == "T" * MAX_TITLE_CHARS
    assert entry.summary is not None
    assert entry.summary.startswith("Un résumé &co")
    assert len(entry.summary) <= MAX_SUMMARY_CHARS
    assert entry.summary_truncated is True


def test_full_contents_are_ignored() -> None:
    body = rss(
        [rss_item(description=None, extra="<content:encoded>Article entier</content:encoded>")],
        extra_ns=CONTENT,
    )
    entry = _parse(body).entries[0]
    assert entry.summary is None
    entry = _parse(atom([atom_entry(summary=None, extra="<content>Article entier</content>")]))
    assert entry.entries[0].summary is None


@pytest.mark.parametrize(
    "link",
    [
        "javascript:alert(1)",
        "data:text/html,x",
        "file:///etc/passwd",
        "https://user:pass@feeds.example/a",
        "https://feeds.example/" + "a" * 2_000,
        "http://[::1",
        "   ",
    ],
)
def test_unsafe_or_odd_links_are_dropped(link: str) -> None:
    assert _parse(rss([rss_item(link=link)])).entries[0].link is None


def test_rss_links_fall_back_on_a_permalink_guid_only() -> None:
    parsed = _parse(
        rss(
            [
                rss_item(link=None, extra="<guid>https://feeds.example/g</guid>"),
                rss_item(link=None, extra='<guid isPermaLink="false">id-42</guid>'),
                rss_item(link=None),
            ]
        )
    )
    assert [e.link for e in parsed.entries] == ["https://feeds.example/g", None, None]


def test_atom_links_are_the_alternate_ones() -> None:
    entries = [
        atom_entry(href=None, extra='<link rel="self" href="https://feeds.example/self"/>'),
        atom_entry(
            href=None,
            extra='<link rel="enclosure" href="https://feeds.example/e.mp3"/>'
            '<link rel="alternate" href="https://feeds.example/alt"/>',
        ),
    ]
    assert [e.link for e in _parse(atom(entries)).entries] == [None, "https://feeds.example/alt"]


def test_atom_xhtml_texts_keep_the_text_of_their_children() -> None:
    xhtml = (
        '<summary type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">'
        "Un <em>résumé</em> riche</div></summary>"
    )
    entry = _parse(atom([atom_entry(summary=None, extra=xhtml)])).entries[0]
    assert entry.summary == "Un résumé riche"


XXE = b"""<?xml version="1.0"?>
<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<rss version="2.0"><channel><item><title>&xxe;</title></item></channel></rss>"""
LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]>
<rss version="2.0"><channel><item><title>&lol3;</title></item></channel></rss>"""
EXTERNAL_DTD = b"""<?xml version="1.0"?>
<!DOCTYPE rss SYSTEM "https://feeds.example/rss.dtd">
<rss version="2.0"><channel><item><title>x</title></item></channel></rss>"""


@pytest.mark.parametrize("body", [XXE, LAUGHS, EXTERNAL_DTD, b"", b"<rss", b"\xff\xfe<rss/>"])
def test_dtds_and_broken_xml_are_refused(body: bytes) -> None:
    with pytest.raises(FeedError, match="flux illisible"):
        _parse(body)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b'<rss version="2.0"/>', "flux RSS sans canal"),
        (b"<html><body>page</body></html>", "format non pris en charge"),
        (b'<feed xmlns="http://example.org/autre"/>', "format non pris en charge"),
    ],
)
def test_other_documents_are_refused(body: bytes, message: str) -> None:
    with pytest.raises(FeedError, match=message):
        _parse(body)


@settings(max_examples=200, deadline=None)
@given(
    st.one_of(
        st.binary(max_size=2_000),
        st.text(max_size=300).map(lambda t: rss([rss_item(t, link=t, description=t)])),
        st.text(max_size=300).map(lambda t: atom([atom_entry(t, href=t, summary=t)])),
    )
)
def test_any_bytes_give_a_feed_or_a_feed_error(body: bytes) -> None:
    try:
        parsed = _parse(body)
    except FeedError:
        return
    assert len(parsed.entries) <= 10
    for entry in parsed.entries:
        assert entry.title is None or len(entry.title) <= MAX_TITLE_CHARS
        assert entry.link is None or entry.link.startswith(("http://", "https://"))


_DAY0 = datetime(2026, 1, 1, tzinfo=UTC)
_dated = st.one_of(
    st.none(),
    st.integers(min_value=0, max_value=60).map(lambda d: _DAY0 + timedelta(days=d, hours=13)),
)


@settings(max_examples=100, deadline=None)
@given(
    st.lists(_dated, max_size=25),
    st.integers(min_value=0, max_value=60).map(lambda d: (_DAY0 + timedelta(days=d)).date()),
    st.integers(min_value=1, max_value=20),
)
def test_no_entry_older_than_since_is_ever_kept(
    moments: list[datetime | None], since: date, limit: int
) -> None:
    def pub(moment: datetime | None) -> str | None:
        return None if moment is None else moment.strftime("%a, %d %b %Y %H:%M:%S GMT")

    parsed = _parse(rss([rss_item(pub_date=pub(m)) for m in moments]), since=since, limit=limit)
    kept = [m for m in moments if m is not None and m.date() >= since]
    assert len(parsed.entries) == min(limit, len(kept))
    assert parsed.more_entries == max(0, len(kept) - limit)
    assert parsed.skipped == len(moments) - len(kept)
    for entry in parsed.entries:
        assert entry.published is not None
        assert datetime.fromisoformat(entry.published).date() >= since
