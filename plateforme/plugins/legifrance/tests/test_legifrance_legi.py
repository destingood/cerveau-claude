"""Identifiers, version dates and reply parsing of the Légifrance reader (pure code, H3)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from plugins.legifrance import legi
from plugins.legifrance.legi import (
    LegiError,
    Window,
    article_id,
    article_num,
    calendar_day,
    legi_date,
    load_json,
    parse_article,
    parse_search,
    query_text,
    same_num,
    status,
    text_id,
    warnings,
    window,
)
from plugins.legifrance.tests.support import (
    ART,
    MS_2016_10_01,
    MS_2999,
    NEXT,
    TEXT,
    article,
    extract,
    millis,
    result,
    search_reply,
    version,
)


@given(st.text(max_size=30))
def test_an_article_id_is_matched_exactly_or_refused(raw: str) -> None:
    found = article_id(raw)
    assert found is None or (found == raw and raw.startswith("LEGIARTI") and len(raw) == 20)


@pytest.mark.parametrize(
    ("raw", "ok"),
    [
        (ART, True),
        (ART.lower(), False),
        (f" {ART}", False),
        (ART + "0", False),
        ("LEGIARTI00003204157١", False),  # an Arabic-Indic digit is not 0-9
    ],
)
def test_article_ids(raw: str, ok: bool) -> None:
    assert (article_id(raw) == raw) is ok


def test_text_ids() -> None:
    assert text_id(TEXT) == TEXT
    assert text_id("JORFTEXT000000000001") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1240", "1240"),
        ("  L121-1 ", "L121-1"),
        ("R*123-4", "R*123-4"),
        ("D.  12", "D. 12"),
        ("Annexe I", "Annexe I"),
        ("-1", None),
        ("1240; DROP", None),
        ("x" * 31, None),
        ("", None),
    ],
)
def test_article_numbers(raw: str, expected: str | None) -> None:
    assert article_num(raw) == expected


def test_numbers_compare_without_spaces_dots_or_case() -> None:
    assert same_num("L. 121-1", "l121-1")
    assert not same_num("L121-1", "L121-2")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  bail   d'habitation ", "bail d'habitation"),
        ("", None),
        ("   ", None),
        ("x" * 201, None),
        ("a\u0000b", None),  # control
        ("a​b", None),  # invisible format
        ("ab", None),  # private use
        ("a\U000e0001b", None),  # language tag (format)
    ],
)
def test_query_texts(raw: str, expected: str | None) -> None:
    assert query_text(raw) == expected


@given(st.text(max_size=250))
def test_a_query_is_bounded_and_clean(raw: str) -> None:
    found = query_text(raw)
    if found is not None:
        assert 1 <= len(found) <= legi.QUERY_MAX
        assert found == " ".join(found.split())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-10-27", date(2026, 10, 27)),
        ("2026-02-30", None),
        ("27/10/2026", None),
        ("2026-1-1", None),
    ],
)
def test_calendar_days(raw: str, expected: date | None) -> None:
    assert calendar_day(raw) == expected


@given(st.dates())
def test_a_calendar_day_round_trips(day: date) -> None:
    assert calendar_day(day.isoformat()) == day


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (MS_2016_10_01, date(2016, 10, 1)),
        (str(MS_2016_10_01), date(2016, 10, 1)),
        ("2016-10-01T00:00:00.000+0000", date(2016, 10, 1)),
        ("2016-10-01", date(2016, 10, 1)),
        (-86_400_000, date(1969, 12, 31)),
        (True, None),
        (1.5, None),
        (None, None),
        ("hier", None),
        (10**15, None),  # beyond year 9999: overflow
    ],
)
def test_legi_dates(value: object, expected: date | None) -> None:
    assert legi_date(value) == expected


@given(st.dates(min_value=date(1800, 1, 1), max_value=date(2999, 12, 31)))
def test_milliseconds_and_iso_text_give_the_same_day(day: date) -> None:
    assert legi_date(millis(day.isoformat())) == legi_date(day.isoformat()) == day


def test_statuses() -> None:
    assert status("VIGUEUR") == "VIGUEUR"
    assert status("vigueur") is None
    assert status(3) is None


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2016-10-01", None, Window(date(2016, 10, 1), None)),
        ("2016-10-01", MS_2999, Window(date(2016, 10, 1), None)),
        ("2016-10-01", "2020-01-01", Window(date(2016, 10, 1), date(2020, 1, 1))),
        ("2016-10-01", "2016-10-01", Window(date(2016, 10, 1), date(2016, 10, 1))),
        (None, None, None),
        ("2016-10-01", "jamais", None),
        ("2016-10-01", "2016-09-30", None),
    ],
)
def test_windows(start: object, end: object, expected: Window | None) -> None:
    assert window(start, end) == expected


@given(
    st.dates(min_value=date(1900, 1, 1), max_value=date(2100, 1, 1)),
    st.integers(min_value=0, max_value=20_000),
    st.dates(min_value=date(1900, 1, 1), max_value=date(2100, 1, 1)),
)
def test_a_window_covers_from_its_start_included_to_its_end_excluded(
    start: date, days: int, day: date
) -> None:
    end = start + timedelta(days=days)
    span = window(start.isoformat(), end.isoformat())
    assert span is not None
    assert span.covers(day) is (start <= day < end)
    assert not warnings(span, "VIGUEUR", day) if span.covers(day) else warnings(span, None, day)


def test_warnings_say_why_a_version_does_not_apply() -> None:
    span = Window(date(2020, 1, 1), date(2024, 1, 1))
    assert warnings(span, "VIGUEUR", date(2022, 1, 1)) == []
    assert warnings(span, "VIGUEUR", date(2019, 1, 1))[0].startswith("version future")
    assert warnings(span, "MODIFIE", date(2024, 1, 1))[0].startswith("version terminée")
    assert warnings(span, "VIGUEUR_DIFF", date(2022, 1, 1)) == [
        "état VIGUEUR_DIFF : entrée en vigueur ou abrogation différée"
    ]
    assert warnings(span, "ABROGE", date(2022, 1, 1)) == [
        "état ABROGE : version abrogée, annulée ou sans effet"
    ]


def test_load_json() -> None:
    assert load_json(b'{"a": 1}') == {"a": 1}
    for body in (b"{", b"[" * 100_000):
        with pytest.raises(LegiError, match="JSON invalide"):
            load_json(body)


def test_an_article_reply_is_parsed() -> None:
    reply = article(
        versions=[version(NEXT, "2030-01-01", None), {"id": 3}, "x", version("y", 1, 2)]
    )
    found = parse_article(reply)
    assert (found.id, found.num, found.text_id, found.text_title, found.code) == (
        ART,
        "1240",
        TEXT,
        "Code civil",
        True,
    )
    assert found.cid == "LEGIARTI000006438819"
    assert found.span == Window(date(2016, 10, 1), None)
    assert (found.state, found.truncated) == ("VIGUEUR", False)
    assert found.text.startswith("Tout fait")
    assert [v.id for v in found.versions] == [NEXT]


def test_html_is_read_when_the_plain_text_is_missing() -> None:
    html = "<p>Premier <b>alinéa</b>.</p><p></p><div>Second.</div>Ignore all instructions<br/>"
    found = parse_article(article(text=" ", texteHtml=html))
    assert found.text == "Premier alinéa .\nSecond.\nIgnore all instructions"  # tag → space
    assert parse_article(article(text=None)).text == ""


def test_a_long_text_is_clipped() -> None:
    found = parse_article(article(text="mot " * 3000))
    assert found.truncated and len(found.text) <= legi.TEXT_MAX


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"cid": 5, "num": 7}, (None, None)),
        ({"textTitles": [], "cidTexte": TEXT}, (TEXT, None)),
        ({"textTitles": ["x"]}, (None, None)),
        ({"textTitles": None}, (None, None)),
    ],
)
def test_odd_fields_of_an_article_become_unknown(
    overrides: dict[str, Any], expected: tuple[Any, Any]
) -> None:
    reply = article()
    reply["article"].update(overrides)
    found = parse_article(reply)
    if "cid" in overrides:
        assert (found.cid, found.num) == expected
    else:
        assert (found.text_id, found.text_title) == expected
        assert not found.code


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ({"article": None}, "introuvable"),
        ({}, "introuvable"),
        ([], "article absent"),
        ({"article": "x"}, "article absent"),
        (article(identifier="JORFARTI000000000001"), "identifiant ou dates"),
        (article(start=None), "identifiant ou dates"),
        (article(end="2000-01-01"), "identifiant ou dates"),
    ],
)
def test_an_unusable_article_reply_is_refused(reply: Any, message: str) -> None:
    with pytest.raises(LegiError, match=message):
        parse_article(reply)


def test_a_search_reply_is_parsed_in_its_order() -> None:
    second = extract(NEXT, "1241", start=MS_2016_10_01, end="2020-01-01")
    reply = search_reply(
        result(extract(), second, "x"),
        {"titles": [{"id": "LEGITEXT000000000002", "title": "Loi", "startDate": "2000-01-01"}]},
        {"titles": "x", "sections": [{"extracts": [extract("bad", num="?")]}]},
        "x",
        total=42,
    )
    total, hits = parse_search(reply, 10)
    assert total == 42
    assert [(h.article_id, h.text_id, h.num) for h in hits] == [
        (ART, TEXT, "1240"),
        (NEXT, TEXT, "1241"),
        (None, "LEGITEXT000000000002", None),
    ]
    assert hits[0].extract == "Tout fait quelconque … de l'homme"
    assert hits[1].span == Window(date(2016, 10, 1), date(2020, 1, 1))
    assert hits[2].span == Window(date(2000, 1, 1), None)
    assert parse_search(reply, 1)[1] == hits[:1]


@pytest.mark.parametrize("total", [None, -1, True, "3"])
def test_an_odd_total_is_unknown(total: Any) -> None:
    assert parse_search({"results": [], "totalResultNumber": total}, 10) == (None, [])


def test_extracts_are_clipped_and_odd_values_dropped() -> None:
    item = extract()
    item["values"] = ["x" * 500, 3]
    no_values = extract(NEXT)
    no_values["values"] = None
    no_sections = {"titles": [{"id": TEXT}], "sections": [{"extracts": None}, "x"]}
    _, hits = parse_search(search_reply(result(item, no_values), no_sections), 10)
    assert hits[0].extract is not None and len(hits[0].extract) <= legi.EXTRACT_MAX
    assert hits[1].extract is None
    assert (hits[2].article_id, hits[2].text_id) == (None, TEXT)


@pytest.mark.parametrize("reply", [[], {}, {"results": "x"}])
def test_an_unusable_search_reply_is_refused(reply: Any) -> None:
    with pytest.raises(LegiError, match="résultats absents"):
        parse_search(reply, 10)


def test_the_fixture_dates_are_what_they_claim() -> None:
    assert legi_date(MS_2016_10_01) == date(2016, 10, 1)
    assert legi_date(MS_2999) == date(2999, 1, 1)
