"""Plain text of external content (core.net.text): one line, no hidden characters, bounded."""

from __future__ import annotations

import unicodedata

from hypothesis import given
from hypothesis import strategies as st

from core.net.text import clean_text, clip, strip_markup


def test_clean_text_drops_invisible_characters_and_joins_lines() -> None:
    raw = "  Un​ ti‮tre\n\tsur\x00deux lignes fines  "
    assert clean_text(raw) == "Un titre sur deux lignes fines"


@given(st.text())
def test_clean_text_is_one_trimmed_line_without_control_characters(raw: str) -> None:
    text = clean_text(raw)
    assert text == text.strip()
    assert "  " not in text
    assert not any(unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"} for c in text)


def test_strip_markup_removes_the_title_element_tags_and_entities() -> None:
    raw = "<jats:title>Abstract</jats:title>\n<jats:p>Un r&#233;sum&#233; &lt;b&gt;</jats:p>"
    assert strip_markup(raw) == "Un résumé <b>"
    assert strip_markup("<title id='t'>Résumé</title><p>Texte</p>") == "Texte"
    assert strip_markup("<p>Un <a href='https://x.example'>lien</a>&nbsp;!</p>") == "Un lien !"


def test_clip_cuts_with_an_ellipsis_within_the_limit() -> None:
    assert clip("abcdef", 6) == ("abcdef", False)
    text, cut = clip("abc defgh", 5)
    assert (text, cut) == ("abc…", True)
    assert len(clip("x" * 50, 10)[0]) == 10


@given(st.text(), st.integers(min_value=1, max_value=60))
def test_clip_never_exceeds_the_limit(text: str, limit: int) -> None:
    clipped, cut = clip(text, limit)
    assert len(clipped) <= limit
    assert cut is (len(text) > limit)
