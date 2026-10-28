"""Every date and time of a draft must come from a tool output, the question or a source (R1, B33).

Read in French and English notations: ``18/10/2026``, ``2026-10-18``, ``2026-10-18T13:00:00Z``,
``18 octobre 2026``, ``1er janvier 2025``, ``October 18, 2026``, a month (``octobre 2026``), a
day without its year (``le 18 octobre``) and a time (``13:00``, ``13 h 30``, ``13 h``).

- A full date matches the same day in a source, whatever the notation. A numeric date of a source
  that reads both ways (``03/04/2025``, an English page may mean 4 March) gives both readings; a
  draft, written in French, reads the day first.
- A month matches any date of that month in a source, a day without year any date of that day.
- A time matches the same hour and minute in a source, as written. No time zone is converted: a
  draft that turns 13:00 UTC into 15 h does not match, since the model computed it.
- A year alone is a number (``numbers.py``); the years of the source dates support it.
"""

from __future__ import annotations

import re
from collections.abc import Hashable
from dataclasses import dataclass
from datetime import date
from typing import Literal

DateKind = Literal["date", "mois", "jour", "heure"]
DateKey = tuple[DateKind, Hashable]

_FULL_MONTHS = {
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_SHORT_MONTHS = {
    "janv": 1,
    "jan": 1,
    "févr": 2,
    "fevr": 2,
    "fév": 2,
    "fev": 2,
    "feb": 2,
    "mar": 3,
    "avr": 4,
    "apr": 4,
    "juil": 7,
    "jul": 7,
    "jun": 6,
    "aug": 8,
    "sept": 9,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "déc": 12,
    "dec": 12,
}
_MONTHS = {**_FULL_MONTHS, **_SHORT_MONTHS}


def _alternatives(names: dict[str, int]) -> str:
    return "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))


_ANY_MONTH = rf"(?:{_alternatives(_MONTHS)})\.?"
_FULL_MONTH = rf"(?:{_alternatives(_FULL_MONTHS)})"
_DATES = re.compile(
    "|".join(
        [
            r"(?<![\d.,/-])(?P<iy>\d{4})-(?P<im>\d{2})-(?P<id>\d{2})"
            r"(?:[T ](?P<iH>\d{2}):(?P<iM>\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
            r"(?!\d)",
            r"(?<![\d.,/:-])(?P<na>\d{1,2})(?P<sep>[/.-])(?P<nb>\d{1,2})(?P=sep)"
            r"(?P<ny>\d{4}|\d{2})(?!\d|[.,/-]\d)",
            rf"(?<![\w.,])(?P<wd>1er|\d{{1,2}})\s+(?P<wm>{_ANY_MONTH})\s+(?P<wy>\d{{4}})(?!\d)",
            rf"(?<![\w])(?P<em>{_ANY_MONTH})\s+(?P<ed>\d{{1,2}})(?:st|nd|rd|th)?,?\s+"
            r"(?P<ey>\d{4})(?!\d)",
            rf"(?<![\w])(?P<mm>{_FULL_MONTH})\s+(?P<my>\d{{4}})(?!\d)",
            rf"(?<![\w.,])(?P<jd>1er|\d{{1,2}})\s+(?P<jm>{_FULL_MONTH})(?![^\W\d_])",
            r"(?<![\d:,.])(?P<tH>\d{1,2})\s?(?::|h)\s?(?P<tM>\d{2})(?![\d:]|[.,]\d)",
            r"(?<![\d:,.])(?P<hH>\d{1,2})\s?h(?![^\W\d_])",
        ]
    ),
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DateMention:
    text: str
    start: int
    end: int
    kind: DateKind
    keys: frozenset[DateKey]  # a draft: all must be supported; a source: all are supports


def _month(name: str) -> int:
    return _MONTHS[name.rstrip(".").casefold()]


def _day(text: str) -> int:
    return 1 if text.casefold() == "1er" else int(text)


def _year(text: str) -> int:
    if len(text) == 4:
        return int(text)
    two = int(text)
    return 2000 + two if two < 70 else 1900 + two


def _date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _time(hour: str, minute: str = "0") -> tuple[int, int] | None:
    h, m = int(hour), int(minute)
    return (h, m) if h <= 23 and m <= 59 else None


def _keys(match: re.Match[str], *, lenient: bool) -> tuple[DateKind, set[DateKey]] | None:
    g = match.group
    if g("iy"):
        day = _date(int(g("iy")), int(g("im")), int(g("id")))
        if day is None:
            return None
        keys: set[DateKey] = {("date", day)}
        if g("iH") and (moment := _time(g("iH"), g("iM"))) is not None:
            keys.add(("heure", moment))
        return "date", keys
    if g("na"):
        a, b, year = int(g("na")), int(g("nb")), _year(g("ny"))
        readings = [_date(year, b, a)]
        if lenient:  # an English source writes the month first
            readings.append(_date(year, a, b))
        days = {("date", d) for d in readings if d is not None}
        return ("date", set(days)) if days else None
    if g("wd"):
        day = _date(int(g("wy")), _month(g("wm")), _day(g("wd")))
        return ("date", {("date", day)}) if day else None
    if g("em"):
        day = _date(int(g("ey")), _month(g("em")), int(g("ed")))
        return ("date", {("date", day)}) if day else None
    if g("mm"):
        return "mois", {("mois", (int(g("my")), _month(g("mm"))))}
    if g("jd"):
        month, day_of_month = _month(g("jm")), _day(g("jd"))
        if _date(2024, month, day_of_month) is None:  # a leap year admits 29 February
            return None
        return "jour", {("jour", (month, day_of_month))}
    hour, minute = (g("tH"), g("tM")) if g("tH") else (g("hH"), "0")
    moment = _time(hour, minute)
    return ("heure", {("heure", moment)}) if moment else None


def extract_dates(text: str, *, lenient: bool = False) -> list[DateMention]:
    """The dates and times of ``text``; ``lenient`` for a source (both readings of 03/04/2025)."""
    mentions: list[DateMention] = []
    for match in _DATES.finditer(text):
        found = _keys(match, lenient=lenient)
        if found is not None:
            kind, keys = found
            start, end = match.span()
            mentions.append(DateMention(text[start:end], start, end, kind, frozenset(keys)))
    return mentions


def derived(keys: set[DateKey]) -> set[DateKey]:
    """What the dates of a source also support: their month and their day of the year."""
    more: set[DateKey] = set()
    for kind, value in keys:
        if kind == "date" and isinstance(value, date):
            more |= {("mois", (value.year, value.month)), ("jour", (value.month, value.day))}
    return keys | more


def date_spans(text: str) -> list[tuple[int, int]]:
    """Where the dates and times stand, for the number reader to skip them."""
    return [(m.start, m.end) for m in extract_dates(text, lenient=True)]


def years(keys: set[DateKey]) -> set[int]:
    return {value.year for kind, value in keys if kind == "date" and isinstance(value, date)} | {
        value[0] for kind, value in keys if kind == "mois" and isinstance(value, tuple)
    }


__all__ = ["DateKey", "DateKind", "DateMention", "date_spans", "derived", "extract_dates", "years"]
