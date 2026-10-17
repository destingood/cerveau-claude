"""Deterministic input checks, before pseudonymisation and before any model (section 13, R5).

``check_question`` refuses an empty or oversized question, removes invisible characters that can
hide instructions (controls, bidirectional overrides, zero-width and Unicode tag characters) and
lists the URLs Lucas provided: they are untrusted content, read as data only, and they are the
only addresses ``web_read`` may open besides search results. ``mark_untrusted`` wraps external
text in ``<donnees_externes>`` so that the text cannot close the wrapper itself.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MAX_QUESTION_CHARS = 8000
MAX_URLS = 10

_INVISIBLE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f"  # C0 / C1 controls except tab and newlines
    "\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff"  # zero-width, bidi
    "\U000e0000-\U000e007f]"  # tag characters (ASCII smuggling)
)
_URL = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
_URL_TRAILING = ".,;:!?)]}»"
_WRAPPER = re.compile(r"<\s*(/?)\s*donnees_externes", re.IGNORECASE)


class InputRefusedError(Exception):
    """The question is refused before anything else runs; the message is shown to Lucas."""


@dataclass(frozen=True)
class CheckedQuestion:
    text: str
    urls: tuple[str, ...]  # provided by Lucas, untrusted: data only, never instructions
    removed_characters: int


def _strip_url(raw: str) -> str:
    url = raw
    while url and url[-1] in _URL_TRAILING:
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break  # https://fr.wikipedia.org/wiki/Lyon_(ville) keeps its parenthesis
        url = url[:-1]
    return url


def provided_urls(text: str) -> tuple[str, ...]:
    """The http(s) URLs of a text, in order, without duplicates or trailing punctuation."""
    urls: list[str] = []
    for match in _URL.finditer(text):
        url = _strip_url(match.group(0))
        if "://" in url and len(url) > len("https://") and url not in urls:
            urls.append(url)
    return tuple(urls)


def check_question(raw: str) -> CheckedQuestion:
    text = unicodedata.normalize("NFC", raw)
    cleaned = _INVISIBLE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    removed = len(text) - len(_INVISIBLE.sub("", text))
    cleaned = cleaned.strip()
    if not cleaned:
        raise InputRefusedError("question vide")
    if len(cleaned) > MAX_QUESTION_CHARS:
        raise InputRefusedError(
            f"question trop longue ({len(cleaned)} caractères, maximum {MAX_QUESTION_CHARS})"
        )
    urls = provided_urls(cleaned)
    if len(urls) > MAX_URLS:
        raise InputRefusedError(f"trop d'adresses web ({len(urls)}, maximum {MAX_URLS})")
    return CheckedQuestion(cleaned, urls, removed)


def mark_untrusted(text: str, source: str) -> str:
    """Wrap external content as data; inner wrapper tags are neutralised, not trusted.

    NFKC first, so that full-width or compatibility look-alikes of ``<`` cannot rebuild a tag.
    """
    body = _INVISIBLE.sub("", unicodedata.normalize("NFKC", text))
    body = _WRAPPER.sub(lambda m: f"‹{m.group(1)}donnees_externes", body)
    label = _INVISIBLE.sub("", unicodedata.normalize("NFKC", source))
    label = " ".join(_WRAPPER.sub("‹donnees_externes", label).split())
    label = label.replace('"', "'").replace("<", "‹").replace(">", "›")
    return f'<donnees_externes source="{label}">\n{body}\n</donnees_externes>'
