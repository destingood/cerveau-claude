"""Quotes must appear word for word in the stored page text, after a tolerant normalisation.

The normalisation only removes differences that do not change the words: Unicode compatibility
forms (NFKC), case, runs of white space, typographic quotes and dashes, soft hyphens. An ellipsis
or any reworded part makes the quote fail: the reader must copy, not paraphrase.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MIN_QUOTE_CHARS = 10
MAX_QUOTE_CHARS = 600

_QUOTES = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u00ab": '"',
        "\u00bb": '"',
        "\u2039": "'",
        "\u203a": "'",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
    }
)
_INVISIBLE = re.compile("[\u00ad\u200b-\u200f\u2060\ufeff]")
_SPACES = re.compile(r"\s+")
_EDGES = " \"'"


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    text = _INVISIBLE.sub("", text).casefold()
    return _SPACES.sub(" ", text).strip()


@dataclass(frozen=True)
class QuoteCheck:
    ok: bool
    reason: str | None = None


def check_quote(quote: str, page_text: str) -> QuoteCheck:
    needle = normalise(quote).strip(_EDGES)
    if len(needle) < MIN_QUOTE_CHARS:
        return QuoteCheck(False, f"citation trop courte (< {MIN_QUOTE_CHARS} caractères)")
    if len(needle) > MAX_QUOTE_CHARS:
        return QuoteCheck(False, f"citation trop longue (> {MAX_QUOTE_CHARS} caractères)")
    if needle not in normalise(page_text):
        return QuoteCheck(False, "citation absente du texte de la page")
    return QuoteCheck(True)
