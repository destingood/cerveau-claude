"""Every number of a draft must come from a tool output or from the question (R1).

The model cites numbers, it never computes them. This check reads the numbers of the draft and of
the source texts in French and English notations (``1 234,5``, ``1,234.5``, ``12 %``,
``2,5 millions``, ``3 Md€``, ``1.2bn``) and lists the draft numbers that match none of them.

- A notation that is ambiguous alone (``1,234`` or ``1.234``) gives both readings, and so does
  ``billion`` (10^9 in English, 10^12 in French). A percentage also reads as a fraction.
- A draft number may be a rounding of a source number: written with d decimals, it matches a
  source value within half a unit of its last digit (``12 %`` matches ``12,4 %``, ``1,5 million``
  matches ``1 512 000``). A draft more precise than every source does not match.
- The sign is compared apart from the value: "a reculé de 3 %" supports "-3 %". Whether the
  wording is right is the claim check's job, not this one's.
- Not read: citation markers ``[n]``, pseudonyms ``<PERSONNE_1>``, URLs, dates, times, list
  markers at the start of a line, and numbers glued to a word (``H2O``, ``COVID-19``, ``Q3``).
- Small bare counts (an integer up to ``SMALL_COUNT_MAX`` without unit, scale or percent, as in
  "trois options" written "3 options") are read but not checked: they structure the answer and
  are not decision figures.
- Numbers written in words ("trois millions") are not read: the system prompt asks for digits.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from core.verification.citations import CITATION

SMALL_COUNT_MAX = 10

_SPACE = " \u00a0\u202f\u2009"  # space, no-break, narrow no-break, thin
_NUMBER = re.compile(
    r"(?<![\w.,/:])"
    r"(?P<body>"
    rf"\d{{1,3}}(?:[{_SPACE}]\d{{3}})+(?:[.,]\d+)?"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"
    r"|\d{1,3}(?:\.\d{3})+(?:,\d+)?"
    r"|\d+(?:[.,]\d+)?"
    r")"
    r"(?!\d|[.,]\d|/|:\d)"
    r"(?P<scale>\s?(?:(?i:milliards?|millions?|mille|billions?|trillions?|thousands?)"
    r"|Mds?|Mrds?|bn|[kKM](?!\.\s))(?![^\W\d_]))?"  # "en 2026 M. Martin" is not a scale
    r"(?P<percent>\s?(?:%|(?i:pour\s?cent|per\s?cent)\b))?"
    r"(?P<currency>\s?(?:[€$£]|(?i:euros?|dollars?|eur|usd)\b))?"
)
_SIGN = frozenset("-\u2212")  # hyphen-minus, minus sign
_CURRENCY_BEFORE = frozenset("€$£")
_SCALES: dict[str, tuple[Decimal, ...]] = {
    "mille": (Decimal(10) ** 3,),
    "thousand": (Decimal(10) ** 3,),
    "k": (Decimal(10) ** 3,),
    "million": (Decimal(10) ** 6,),
    "m": (Decimal(10) ** 6,),
    "milliard": (Decimal(10) ** 9,),
    "md": (Decimal(10) ** 9,),
    "mds": (Decimal(10) ** 9,),
    "mrd": (Decimal(10) ** 9,),
    "mrds": (Decimal(10) ** 9,),
    "bn": (Decimal(10) ** 9,),
    "billion": (Decimal(10) ** 9, Decimal(10) ** 12),  # English, French
    "trillion": (Decimal(10) ** 12, Decimal(10) ** 18),
}
_IGNORED = re.compile(
    "|".join(
        [
            CITATION.pattern,
            r"\\?<[A-Z][A-Z_]*_\d+\\?>",  # pseudonym
            r"(?i:\b(?:https?://|www\.)[^\s<>()\[\]\"'`]+)",
            r"\]\([^)\s]*\)",  # Markdown link target
            r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b",  # 18/10/2026
            r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?",
            r"\b\d{1,2}\s?[:h]\s?\d{2}\b",  # 12:30, 12 h 30
            r"(?m:^[ \t]{0,3}\d{1,2}[.)](?=\s))",  # list marker
            r"(?<=[^\W\d_])[-_]?\d[\d.,]*",  # glued to a word: COVID-19, H2O, Q3
        ]
    )
)


@dataclass(frozen=True)
class Reading:
    value: Decimal  # absolute value
    tolerance: Decimal  # half a unit of the last written digit, times the scale


@dataclass(frozen=True)
class NumberMention:
    text: str
    start: int
    end: int
    negative: bool
    readings: tuple[Reading, ...]
    checked: bool  # False for a small bare count


def _blank(match: re.Match[str]) -> str:
    return " " * len(match.group(0))


def _plain_readings(body: str) -> list[tuple[Decimal, int]]:
    """(value, decimals) of each possible reading of a written number without its scale."""
    compact = "".join(ch for ch in body if ch not in _SPACE)
    if compact != body:  # grouped by spaces: the only separator left is the decimal one
        integer, _, fraction = compact.replace(",", ".").partition(".")
        return [(Decimal(f"{integer}.{fraction or 0}"), len(fraction))]
    commas, dots = body.count(","), body.count(".")
    if commas and dots:  # the last separator is the decimal one
        decimal_sep = "," if body.rfind(",") > body.rfind(".") else "."
        group_sep = "." if decimal_sep == "," else ","
        integer, _, fraction = body.replace(group_sep, "").partition(decimal_sep)
        return [(Decimal(f"{integer}.{fraction}"), len(fraction))]
    if commas + dots > 1:  # 1,234,567 or 1.234.567: grouping
        return [(Decimal(body.replace(",", "").replace(".", "")), 0)]
    if commas + dots == 0:
        return [(Decimal(body), 0)]
    integer, _, fraction = body.replace(",", ".").partition(".")
    readings = [(Decimal(f"{integer}.{fraction}"), len(fraction))]
    if len(fraction) == 3 and len(integer) <= 3 and not integer.startswith("0"):
        readings.append((Decimal(integer + fraction), 0))  # 1,234 in English, 1.234 in German
    return readings


def _scales(raw: str | None) -> tuple[Decimal, ...]:
    if not raw:
        return (Decimal(1),)
    key = raw.strip().casefold()  # k, K -> k; M -> m (million); lowercase m is never a scale
    return _SCALES[key] if key in _SCALES else _SCALES[key.removesuffix("s")]


def _readings(match: re.Match[str]) -> tuple[Reading, ...]:
    readings: list[Reading] = []
    for value, decimals in _plain_readings(match.group("body")):
        half = Decimal("0.5").scaleb(-decimals)
        for scale in _scales(match.group("scale")):
            readings.append(Reading(value * scale, half * scale))
            if match.group("percent"):
                readings.append(Reading(value * scale / 100, half * scale / 100))
    return tuple(dict.fromkeys(readings))


def extract_numbers(text: str) -> list[NumberMention]:
    cleaned = _IGNORED.sub(_blank, text)
    mentions: list[NumberMention] = []
    for match in _NUMBER.finditer(cleaned):
        start, end = match.span()
        before = cleaned[start - 1] if start else ""
        negative = before in _SIGN and (start < 2 or not cleaned[start - 2].isalnum())
        bare = not (match.group("scale") or match.group("percent") or match.group("currency"))
        bare = bare and before not in _CURRENCY_BEFORE
        body = match.group("body")
        small = bare and not negative and body.isdigit() and int(body) <= SMALL_COUNT_MAX
        mentions.append(
            NumberMention(
                text=text[start:end].strip(),
                start=start,
                end=end,
                negative=negative,
                readings=_readings(match),
                checked=not small,
            )
        )
    return mentions


def _supported(mention: NumberMention, values: set[Decimal]) -> bool:
    return any(
        abs(value - reading.value) <= reading.tolerance
        for reading in mention.readings
        for value in values
    )


def unmatched_numbers(draft: str, sources: Iterable[str]) -> list[NumberMention]:
    """Checked draft numbers that no source number supports, in order of appearance."""
    values = {
        reading.value
        for source in sources
        for mention in extract_numbers(source)
        for reading in mention.readings
    }
    return [m for m in extract_numbers(draft) if m.checked and not _supported(m, values)]
