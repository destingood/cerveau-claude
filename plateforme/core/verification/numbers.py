"""Every number of a draft must come from a tool output, the question or a source (R1).

The model cites numbers, it never computes them. This module reads the numbers of a text in
French and English notations (``1 234,5``, ``1,234.5``, ``12 %``, ``2,5 millions``, ``3 Md€``,
``1.2bn``) and says which source number supports a draft number; ``trace.py`` builds the sources
from the tool outputs, the question and the pages.

- A notation that is ambiguous alone (``1,234`` or ``1.234``) gives both readings, and so does
  ``billion`` (10^9 in English, 10^12 in French).
- Grouping separators (B1.1): spaces of any width (``1 234``, narrow no-break, figure space),
  apostrophes (``10'000'000``, ``10’000’000``), commas or dots; a number so grouped is one
  number, never three pieces. Invisible characters (zero-width space, soft hyphen) and Markdown
  emphasis between digits are dropped (``**1**0 000`` is ``10 000``); superscript digits glued to
  a number are its digits (``10⁶`` reads ``106``, never ``10``).
- A draft number may be a rounding of a source number: written with d decimals, it matches a
  source value within half a unit of its last digit (``12 %`` matches ``12,4 %``, ``1,5 million``
  matches ``1 512 000``). A draft more precise than every source does not match. A rounding keeps
  the order of magnitude (B1.1): a zero, with or without scale (``0 €``, ``0 Md€``), needs a source
  that is zero; ``1`` does not round ``0,87``, though ``10 %`` rounds ``9,62 %`` (half a unit of
  the draft is at most 5 % of it).
- Against a text, a percentage also reads as a fraction (``12 %`` and ``0,12``) and the currency
  is not compared; but a draft percentage matches a source percentage, or through its fraction
  reading a source fraction written with decimals: ``0,031 %`` never matches ``0.031``, nor
  ``100 %`` a bare ``1`` (B1.1). A tool figure says what it is: a draft percentage matches a
  percentage figure only, through its fraction reading, a draft number without % a figure that
  is not one, and a draft amount with a currency (``12 €``, ``$3``) a figure in that currency only.
- The sign (B35) is the written minus or plus, else the direction word right after the number
  (``3 % de hausse``) or the nearest one among the words before it in the same clause (``un
  recul de 3 %``). A draft number whose sign contradicts the one of its source is *contrary*:

  - a negative tool figure keeps its minus or a down word (``-0,08``, ``une perte de 60 €``,
    ``60 € de frais``: a cost word counts as a down word);
  - a written minus never matches a positive source, nor an up word a negative one;
  - a down word before a positive tool figure is accepted, since a loss is often given as a
    magnitude (a drawdown of 15,10 %, ``une baisse de 15,10 %``). Not caught: ``a baissé de
    5 %`` for a figure of +5 %; the claim check reads the wording.

- Every number is checked, small bare counts included (B33): the system prompt asks the model to
  write the counts that structure an answer in letters ("trois options").
- Not read: dates and times (``dates.py`` checks them; a year alone is a number, supported by
  the years of the source dates), citation markers ``[n]``, pseudonyms ``<PERSONNE_1>``, URLs,
  list markers at the start of a line, ordinals (``1er``, ``2e``, ``3rd``) and numbers glued to
  a word (``H2O``, ``COVID-19``, ``Q3``), and labels (B1.1): a small integer right after
  ``étape``, ``phase``, ``section``, ``chapitre``, ``partie``, ``annexe``, ``tableau``, ``figure``,
  ``scénario``, ``option``, ``question``, ``step``, ``chapter`` or ``appendix`` (``Étape 2``,
  ``étapes 2 et 3``), without unit, scale or decimals. A legal article (``article 1240``) stays a
  number to check.
- A number given as a computed metric (``metrics.py``) is supported by a tool figure of that
  metric only, when the caller asks for it (``supporting(..., metrics=True)``).
- Numbers written in words ("trois millions") are not read: the system prompt asks for digits.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from core.verification.citations import CITATION
from core.verification.dates import date_spans, extract_dates, years
from core.verification.metrics import draft_metric

Sign = Literal["-", "+"]
Form = Literal["pourcent", "fraction", "decimal", "entier"]  # how a text writes a number

# space, no-break, narrow no-break, thin, figure, punctuation, hair, medium mathematical
_SPACE = " \u00a0\u202f\u2009\u2007\u2008\u200a\u205f"
_APOSTROPHE = "'\u2019\u02bc"  # Swiss grouping: 10'000'000, 10’000’000
_NUMBER = re.compile(
    r"(?<![\w.,/:])"
    r"(?P<body>"
    rf"\d{{1,3}}(?:[{_SPACE}]\d{{3}})+(?:[.,]\d+)?"
    rf"|\d{{1,3}}(?:[{_APOSTROPHE}]\d{{3}})+(?:[.,]\d+)?"
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
_MINUS = frozenset("-\u2212")  # hyphen-minus, minus sign
_PLUS = frozenset("+")
_CURRENCIES = {
    "€": "EUR",
    "euro": "EUR",
    "eur": "EUR",
    "$": "USD",
    "dollar": "USD",
    "usd": "USD",
    "£": "GBP",
}
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
_MASKED = re.compile(  # neither numbers nor dates
    "|".join(
        [
            CITATION.pattern,
            r"\\?<[A-Z][A-Z_]*_\d+\\?>",  # pseudonym
            r"(?i:\b(?:https?://|www\.)[^\s<>()\[\]\"'`]+)",
            r"\]\([^)\s]*\)",  # Markdown link target
        ]
    )
)
_NOT_NUMBERS = re.compile(
    "|".join(
        [
            r"(?m:^[ \t]{0,3}\d{1,2}[.)](?=\s))",  # list marker
            r"(?<=[^\W\d_])[-_]?\d[\d.,]*",  # glued to a word: COVID-19, H2O, Q3
            r"\b\d+(?:er|re|ère|ème|eme|e|ᵉ|nde|nd|st|rd|th)\b",  # ordinal: 1er, 2e, 3rd
        ]
    )
)
_LABEL_WORDS = (
    r"[ée]tapes?|phases?|sections?|chapitres?|parties?|annexes?|tableaux?|figures?"
    r"|sc[ée]narios?|options?|questions?|steps?|chapters?|appendix|appendices"
)
_LABEL = re.compile(  # what stands before a label number: "étapes 2 et " before "3"
    rf"(?i:\b(?:{_LABEL_WORDS})\s+(?:n[°o]\s*)?(?:\d{{1,3}}\s*(?:,|-|–|et|à|ou|and|or|to)\s*)*)$"
)
_EMPHASIS = frozenset("*_~`")  # Markdown emphasis and code marks
_GLUE = frozenset(_SPACE + _APOSTROPHE + ".,")  # what may stand between the digits of one number
_SUPERSCRIPT_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SUPERSCRIPTS = str.maketrans(_SUPERSCRIPT_DIGITS, "0123456789")
_UNITS = frozenset("%€$£")
_UP = (
    r"hausses?|progress\w*|augment\w*|croissances?|gains?|gagn\w*|rebond\w*|mont[ée]es?"
    r"|grimp\w*|positi(?:f|ve|fs|ves)|plus-values?|rises?|rising|rose|increas\w*|grew|growth|up"
)
_DOWN = (
    r"baiss\w*|recul\w*|repli\w*|chut\w*|diminu\w*|pertes?|perd\w*|moins-values?"
    r"|n[ée]gati(?:f|ve|fs|ves)|fl[ée]chi\w*|falls?|fell|declin\w*|drop\w*|loss(?:es)?|lost|down"
    r"|frais|co[uû]ts?|charges?|d[ée]penses?"  # a cost the book counts as negative
)
_DIRECTION = re.compile(rf"(?i)\b(?:(?P<up>{_UP})|(?P<down>{_DOWN}))\b")
_WORD = re.compile(r"[^\W\d_][\w-]*")  # l'augmentation: two words
_CLAUSE_END = re.compile(r"[;!?\n]|[.,:](?=\s|$)")
_AFTER = re.compile(r"\s*(?:(?i:de|en)\s+|(?i:d)['’])?(?P<word>[^\W\d_][\w-]*)")
WORDS_BEFORE = 5  # how far before a number a direction word still applies to it
_LOOK_BEHIND = 160  # characters read before a number for its clause


@dataclass(frozen=True)
class Reading:
    value: Decimal  # absolute value
    tolerance: Decimal  # half a unit of the last written digit, times the scale
    fraction: bool = False  # the fraction reading of a percentage: 12 % -> 0.12


@dataclass(frozen=True)
class NumberMention:
    text: str
    start: int
    end: int
    readings: tuple[Reading, ...]
    percent: bool = False
    currency: str | None = None  # EUR, USD or GBP
    bare: bool = True  # no scale, percent or currency
    sign: Sign | None = None
    explicit: bool = False  # the sign is written (-3 %, +3 %), not read from a word
    metric: str | None = None  # the computed metric the number is given as (metrics.py)

    @property
    def negative(self) -> bool:
        return self.sign == "-"

    @property
    def year_like(self) -> bool:
        """A bare integer of four digits without a written sign, as a year: ``2026``."""
        return (
            self.bare
            and not self.explicit
            and len(self.readings) == 1
            and self.readings[0].tolerance == Decimal("0.5")
            and 1000 <= self.readings[0].value <= 2999
        )


@dataclass(frozen=True)
class Support:
    """What a source number supports: a text (``percent`` None) or a tool figure (``exact``)."""

    values: frozenset[Decimal]  # absolute values
    origin: str
    percent: bool | None = None  # None: any reading of the draft counts
    currencies: frozenset[str] = frozenset()  # a draft currency must be one of them (exact)
    sign: Sign | None = None
    exact: bool = False  # a tool figure: its sign must be kept
    years_only: bool = False  # the years of the source dates: a bare four-digit draft number
    form: Form | None = None  # a text: how it wrote the number (None for a tool figure)
    metric: str | None = None  # a tool figure: the metric its id names (metrics.py)


def _blank(match: re.Match[str]) -> str:
    return " " * len(match.group(0))


def masked(text: str) -> str:
    """``text`` with its citation markers, pseudonyms and URLs blanked, positions kept."""
    return _MASKED.sub(_blank, text)


def _without_dates(text: str) -> str:
    chars = list(text)
    for start, end in date_spans(text):
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def _digit(ch: str) -> bool:
    return ch.isdecimal() or ch in _SUPERSCRIPT_DIGITS


def _between_digits(before: str, after: str) -> bool:
    """``before`` ends with a digit, maybe then a separator; ``after`` starts the same way, or
    with the unit of the number (``**12** %``)."""
    left = bool(before) and (
        _digit(before[-1]) or (len(before) == 2 and before[-1] in _GLUE and _digit(before[0]))
    )
    right = bool(after) and (
        _digit(after[0])
        or after[0] in _UNITS
        or (len(after) == 2 and after[0] in _GLUE and (_digit(after[1]) or after[1] in _UNITS))
    )
    return left and right


def _joined(text: str) -> tuple[str, list[int]]:
    """``text`` without what splits the digits of one number, and the position in ``text`` of
    each kept character: invisible characters everywhere, Markdown emphasis between digits
    (``**1**0 000``); superscript digits glued to a digit become digits (``10⁶``)."""
    kept = [(ch, i) for i, ch in enumerate(text) if unicodedata.category(ch) != "Cf"]
    chars: list[str] = []
    index: list[int] = []
    n = 0
    while n < len(kept):
        ch, i = kept[n]
        if ch in _EMPHASIS:
            run = n
            while run < len(kept) and kept[run][0] in _EMPHASIS:
                run += 1
            after = "".join(c for c, _ in kept[run : run + 2])
            if _between_digits("".join(chars[-2:]), after):
                n = run  # dropped
                continue
        if ch in _SUPERSCRIPT_DIGITS and chars and chars[-1].isdecimal():
            ch = ch.translate(_SUPERSCRIPTS)
        chars.append(ch)
        index.append(i)
        n += 1
    index.append(len(text))
    return "".join(chars), index


def _label(text: str, start: int, match: re.Match[str]) -> bool:
    """A small integer that names a part: ``Étape 2``, ``phase 3``, ``étapes 2 et 3``."""
    if match.group("scale") or match.group("percent") or match.group("currency"):
        return False
    body = match.group("body")
    if not body.isdecimal() or len(body) > 3:
        return False
    return _LABEL.search(text[max(0, start - 80) : start]) is not None


def _plain_readings(body: str) -> list[tuple[Decimal, int]]:
    """(value, decimals) of each possible reading of a written number without its scale."""
    compact = "".join(ch for ch in body if ch not in _SPACE and ch not in _APOSTROPHE)
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
                readings.append(Reading(value * scale / 100, half * scale / 100, fraction=True))
    return tuple(dict.fromkeys(readings))


def _currency(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.strip().casefold()
    return _CURRENCIES.get(key) or _CURRENCIES.get(key.removesuffix("s"))


def _direction(word: str) -> Sign | None:
    found = _DIRECTION.fullmatch(word)
    if found is None:
        return None
    return "+" if found.group("up") else "-"


def _word_sign(text: str, start: int, end: int) -> Sign | None:
    """The direction word right after the number, else the nearest one before it."""
    after = _AFTER.match(text, end)
    if after is not None and (sign := _direction(after.group("word"))) is not None:
        return sign
    clause = _CLAUSE_END.split(text[max(0, start - _LOOK_BEHIND) : start])[-1]
    for word in reversed(_WORD.findall(clause)[-WORDS_BEFORE:]):
        if (sign := _direction(word)) is not None:
            return sign
    return None


def _written_sign(text: str, start: int) -> Sign | None:
    before = text[start - 1] if start else ""
    if start >= 2 and text[start - 2].isalnum():  # 10-20 is a range
        return None
    return "-" if before in _MINUS else "+" if before in _PLUS else None


def extract_numbers(text: str) -> list[NumberMention]:
    joined, index = _joined(masked(text))
    cleaned = _NOT_NUMBERS.sub(_blank, _without_dates(joined))
    mentions: list[NumberMention] = []
    for match in _NUMBER.finditer(cleaned):
        start, end = match.span()
        if _label(cleaned, start, match):
            continue
        before = cleaned[start - 1] if start else ""
        currency = _currency(match.group("currency")) or _currency(before)
        written = _written_sign(cleaned, start)
        sign = written or _word_sign(cleaned, start, end)
        first, last = index[start], index[end - 1] + 1
        mentions.append(
            NumberMention(
                text=text[first:last].strip(),
                start=first,
                end=last,
                readings=_readings(match),
                percent=bool(match.group("percent")),
                currency=currency,
                bare=not (match.group("scale") or match.group("percent") or currency),
                sign=sign,
                explicit=written is not None,
                metric=draft_metric(cleaned, start, end),
            )
        )
    return mentions


def _form(mention: NumberMention, reading: Reading) -> Form:
    if mention.percent:
        return "fraction" if reading.fraction else "pourcent"
    return "decimal" if reading.tolerance < Decimal("0.5") else "entier"


def text_supports(text: str, origin: str) -> list[Support]:
    """The numbers of a source text, each with its sign and the way it is written, and the
    years of its dates."""
    supports: list[Support] = []
    for m in extract_numbers(text):
        forms: dict[Form, set[Decimal]] = {}
        for r in m.readings:
            forms.setdefault(_form(m, r), set()).add(r.value)
        supports += [
            Support(frozenset(values), origin, sign=m.sign, form=form)
            for form, values in forms.items()
        ]
    keys = {key for d in extract_dates(masked(text), lenient=True) for key in d.keys}
    if found := years(keys):
        found_years = frozenset(Decimal(y) for y in found)
        supports.append(Support(found_years, origin, years_only=True, form="entier"))
    return supports


def _fits(mention: NumberMention, reading: Reading, form: Form | None) -> bool:
    """B1.1: a draft reading against the way a text wrote its number."""
    if form is None:
        return True
    if mention.percent and not reading.fraction:  # the 12 of 12 %: a percentage only
        return form == "pourcent"
    if reading.fraction:  # the 0,12 of 12 %: a percentage, or a fraction written with decimals
        return form in ("fraction", "decimal")
    return form != "pourcent"


def _close(reading: Reading, value: Decimal) -> bool:
    """Within the rounding of the draft, and of the same order of magnitude (B1.1)."""
    if reading.value == 0 or value == 0:
        return reading.value == value
    if abs(value - reading.value) > reading.tolerance:
        return False
    same_order = value.adjusted() == reading.value.adjusted()
    return same_order or reading.tolerance * 20 <= reading.value  # 9,62 % -> 10 %


def _magnitude(mention: NumberMention, support: Support) -> bool:
    if support.years_only and not mention.year_like:
        return False
    if support.exact and mention.currency and mention.currency not in support.currencies:
        return False
    if support.percent is None:
        readings: Iterable[Reading] = (
            r for r in mention.readings if _fits(mention, r, support.form)
        )
    elif support.percent != mention.percent:
        return False
    else:
        readings = (r for r in mention.readings if r.fraction is support.percent)
    return any(_close(reading, value) for reading in readings for value in support.values)


def sign_agrees(mention: NumberMention, support: Support) -> bool:
    """B35: the sign of a draft number against the sign of the source number it matches."""
    draft, source = mention.sign, support.sign
    if draft is None:
        return not (support.exact and source == "-")
    if draft == "+":
        return source != "-"
    if source != "+":
        return True
    return support.exact and not mention.explicit  # a loss given as a magnitude


def supporting(
    mention: NumberMention, supports: Iterable[Support], *, metrics: bool = False
) -> tuple[Support | None, bool]:
    """The first support of ``mention`` and ``False``; else the first source that matches its
    value with the contrary sign and ``True``; else ``(None, False)``. With ``metrics``, a
    number given as a computed metric counts only the tool figures of that metric (B1.1)."""
    contrary: Support | None = None
    for support in supports:
        if metrics and mention.metric and not (support.exact and support.metric == mention.metric):
            continue
        if _magnitude(mention, support):
            if sign_agrees(mention, support):
                return support, False
            contrary = contrary or support
    return contrary, contrary is not None


def unmatched_numbers(draft: str, sources: Iterable[str]) -> list[NumberMention]:
    """Draft numbers that no source text supports with the same sign, in order of appearance."""
    supports = [s for source in sources for s in text_supports(source, "source")]
    unmatched = []
    for mention in extract_numbers(draft):
        support, contrary = supporting(mention, supports)
        if support is None or contrary:
            unmatched.append(mention)
    return unmatched


__all__ = [
    "WORDS_BEFORE",
    "Form",
    "NumberMention",
    "Reading",
    "Sign",
    "Support",
    "extract_numbers",
    "masked",
    "sign_agrees",
    "supporting",
    "text_supports",
    "unmatched_numbers",
]
