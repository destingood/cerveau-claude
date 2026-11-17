"""Plain text of external content, shared by the reader plugins (ADR-044).

Titles, names and abstracts that APIs and feeds return become one line of plain text: control and
invisible format characters (Cf: zero width, bidirectional overrides) are dropped, so a text
cannot hide words from the user while the model still reads them (R5).
"""

from __future__ import annotations

import html
import re
import unicodedata

_TAG = re.compile(r"<[^>]*>")
_TITLE_ELEMENT = re.compile(
    r"<(?:jats:)?title\b[^>]*>.*?</(?:jats:)?title\s*>", re.IGNORECASE | re.DOTALL
)
_BREAKS = frozenset({"Cc", "Zl", "Zp"})


def clean_text(raw: str) -> str:
    """One line of plain text: control and invisible format characters (Cf) dropped."""
    kept = (
        " " if unicodedata.category(c) in _BREAKS else c
        for c in raw
        if unicodedata.category(c) != "Cf"
    )
    return " ".join("".join(kept).split())


def strip_markup(raw: str) -> str:
    """Text of an HTML or JATS fragment, without its title element (abstracts, summaries)."""
    return clean_text(html.unescape(_TAG.sub(" ", _TITLE_ELEMENT.sub(" ", raw))))


def clip(text: str, limit: int) -> tuple[str, bool]:
    """At most ``limit`` characters, an ellipsis marking a cut; and whether it was cut."""
    if len(text) <= limit:
        return text, False
    return text[: limit - 1].rstrip() + "…", True
