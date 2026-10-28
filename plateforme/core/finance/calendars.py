"""Business-day calendars: TARGET for the ECB's series, exchange-calendars for the exchanges.

The ECB publishes its reference rates and the €STR on TARGET business days only (ADR-017).
TARGET closes on Saturdays, Sundays, New Year's Day, Good Friday, Easter Monday, 1 May,
Christmas Day and 26 December; this list holds since 2002, so earlier dates are refused.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import exchange_calendars as xc

TARGET_FIRST_YEAR = 2002


def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm of Meeus, Jones and Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    weekday_shift = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * weekday_shift) // 451
    month, day = divmod(h + weekday_shift - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=64)
def target_holidays(year: int) -> frozenset[date]:
    """The weekday closing days of TARGET in ``year``."""
    if year < TARGET_FIRST_YEAR:
        raise ValueError(f"calendrier TARGET connu à partir de {TARGET_FIRST_YEAR}")
    easter = easter_sunday(year)
    return frozenset(
        {
            date(year, 1, 1),
            easter - timedelta(days=2),  # Good Friday
            easter + timedelta(days=1),  # Easter Monday
            date(year, 5, 1),
            date(year, 12, 25),
            date(year, 12, 26),
        }
    )


def is_target_day(day: date) -> bool:
    return day.weekday() < 5 and day not in target_holidays(day.year)


def next_target_day(day: date) -> date:
    """The first TARGET business day strictly after ``day``."""
    following = day + timedelta(days=1)
    while not is_target_day(following):
        following += timedelta(days=1)
    return following


@lru_cache(maxsize=32)
def exchange_calendar(mic: str, first_year: int, last_year: int) -> xc.ExchangeCalendar | None:
    """The calendar of an exchange over whole years, or None when exchange-calendars lacks it."""
    if mic not in xc.get_calendar_names():
        return None
    return xc.get_calendar(mic, start=date(first_year, 1, 1), end=date(last_year, 12, 31))
