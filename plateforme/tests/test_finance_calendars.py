"""TARGET calendar of the ECB's series and the exchange calendars (ADR-017)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.finance.calendars import (
    easter_sunday,
    exchange_calendar,
    is_target_day,
    next_target_day,
    target_holidays,
)


@pytest.mark.parametrize(
    "easter",
    [
        date(2000, 4, 23),
        date(2008, 3, 23),  # earliest of the century
        date(2019, 4, 21),
        date(2024, 3, 31),
        date(2025, 4, 20),
        date(2026, 4, 5),
        date(2038, 4, 25),  # latest possible
    ],
)
def test_easter_sunday_matches_published_dates(easter: date) -> None:
    assert easter_sunday(easter.year) == easter


@given(st.integers(min_value=1583, max_value=4099))
def test_easter_is_a_sunday_between_march_22_and_april_25(year: int) -> None:
    easter = easter_sunday(year)
    assert easter.weekday() == 6
    assert date(year, 3, 22) <= easter <= date(year, 4, 25)


def test_target_closes_on_its_six_holidays_in_2026() -> None:
    assert target_holidays(2026) == {
        date(2026, 1, 1),
        date(2026, 4, 3),  # Good Friday
        date(2026, 4, 6),  # Easter Monday
        date(2026, 5, 1),
        date(2026, 12, 25),
        date(2026, 12, 26),
    }
    assert not is_target_day(date(2026, 4, 3))
    assert not is_target_day(date(2026, 10, 17))  # Saturday
    assert is_target_day(date(2026, 4, 7))
    assert is_target_day(date(2026, 7, 14))  # a French holiday, not a TARGET one


@pytest.mark.parametrize(
    ("day", "following"),
    [
        (date(2026, 10, 15), date(2026, 10, 16)),
        (date(2026, 10, 16), date(2026, 10, 19)),  # Friday → Monday
        (date(2026, 4, 2), date(2026, 4, 7)),  # Thursday before Easter → Tuesday after
        (date(2026, 12, 24), date(2026, 12, 28)),
        (date(2026, 12, 31), date(2027, 1, 4)),  # 1 January 2027 is a Friday
    ],
)
def test_next_target_day_skips_weekends_and_holidays(day: date, following: date) -> None:
    assert next_target_day(day) == following


@given(st.dates(min_value=date(2002, 1, 1), max_value=date(2099, 12, 1)))
def test_next_target_day_is_the_first_open_day_after(day: date) -> None:
    following = next_target_day(day)
    assert following > day and is_target_day(following)
    between = (day + timedelta(days=n) for n in range(1, (following - day).days))
    assert not any(is_target_day(d) for d in between)


def test_target_calendar_is_refused_before_2002() -> None:
    with pytest.raises(ValueError, match="2002"):
        is_target_day(date(2001, 12, 31))


def test_exchange_calendar_is_none_for_an_unknown_exchange() -> None:
    assert exchange_calendar("ZZZZ", 2025, 2026) is None
    calendar = exchange_calendar("XPAR", 2025, 2026)
    assert calendar is not None and calendar.is_session("2026-10-16")
