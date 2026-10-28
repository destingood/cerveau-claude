"""Dates and times of a draft and of its sources (core.verification.dates, B33)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.verification.dates import date_spans, derived, extract_dates, years

FRENCH_MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août")
FRENCH_MONTHS += ("septembre", "octobre", "novembre", "décembre")
ENGLISH_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August")
ENGLISH_MONTHS += ("September", "October", "November", "December")


def keys(text: str, *, lenient: bool = False) -> list[set[object]]:
    return [set(m.keys) for m in extract_dates(text, lenient=lenient)]


@pytest.mark.parametrize(
    "text",
    [
        "18/10/2026",
        "18.10.2026",
        "18-10-26",
        "2026-10-18",
        "18 octobre 2026",
        "18 oct. 2026",
        "October 18, 2026",
        "Oct 18th 2026",
    ],
)
def test_every_notation_reads_the_same_day(text: str) -> None:
    assert keys(f"publié le {text}.") == [{("date", date(2026, 10, 18))}]


def test_the_first_of_the_month() -> None:
    assert keys("le 1er janvier 2025") == [{("date", date(2025, 1, 1))}]


def test_an_iso_timestamp_gives_its_day_and_time() -> None:
    assert keys("2026-10-18T13:05:00Z") == [{("date", date(2026, 10, 18)), ("heure", (13, 5))}]


def test_a_draft_reads_the_day_first_a_source_both_ways() -> None:
    assert keys("03/04/2025") == [{("date", date(2025, 4, 3))}]
    assert keys("03/04/2025", lenient=True) == [
        {("date", date(2025, 4, 3)), ("date", date(2025, 3, 4))}
    ]


@pytest.mark.parametrize(
    ("text", "kind", "key"),
    [
        ("en octobre 2026", "mois", (2026, 10)),
        ("le 18 octobre", "jour", (10, 18)),
        ("le 29 février", "jour", (2, 29)),
        ("à 13:00", "heure", (13, 0)),
        ("à 13 h 30", "heure", (13, 30)),
        ("à 9h", "heure", (9, 0)),
    ],
)
def test_months_days_and_times(text: str, kind: str, key: object) -> None:
    (found,) = extract_dates(text)
    assert (found.kind, set(found.keys)) == (kind, {(kind, key)})


@pytest.mark.parametrize(
    "text",
    [
        "31/02/2026",  # no such day
        "le 30 février",
        "à 25 h",
        "à 12:75",
        "1,5 million",
        "12,34 %",
        "version 1.2.3",
        "10-20 titres",
        "2026",  # a year alone is a number
        "12 450,12 €",
    ],
)
def test_what_is_not_a_date(text: str) -> None:
    assert extract_dates(text) == []


def test_the_spans_keep_the_positions() -> None:
    text = "Le 18/10/2026 à 15 h, TWR de 8,80 %."
    assert [text[a:b] for a, b in date_spans(text)] == ["18/10/2026", "15 h"]


def test_a_date_supports_its_month_its_day_and_its_year() -> None:
    known = derived({("date", date(2025, 3, 12))})
    assert {("mois", (2025, 3)), ("jour", (3, 12))} <= known
    assert years(known) == {2025}
    assert years({("mois", (2024, 5))}) == {2024}


@given(st.dates(date(1970, 1, 1), date(2069, 12, 31)))
def test_any_date_reads_back_in_every_notation(day: date) -> None:
    month, english = FRENCH_MONTHS[day.month - 1], ENGLISH_MONTHS[day.month - 1]
    texts = [
        f"{day:%d/%m/%Y}",
        f"{day:%Y-%m-%d}",
        f"{day.day} {month} {day.year}",
        f"{english} {day.day}, {day.year}",
    ]
    for text in texts:
        assert keys(f"le {text}") == [{("date", day)}], text


@given(st.dates(date(2000, 1, 1), date(2068, 12, 30)))
def test_the_next_day_is_another_date(day: date) -> None:
    after = day + timedelta(days=1)
    assert keys(f"{day:%d/%m/%Y}") != keys(f"{after:%d/%m/%Y}")
