"""Quotes copied word for word from the page, and citation markers pointing to real sources."""

from __future__ import annotations

from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.verification.citations import (
    citation_numbers,
    dangling_citations,
    uncited_units,
    unit_spans,
    units,
)
from core.verification.quotes import MAX_QUOTE_CHARS, QuoteCheck, check_quote, normalise

PAGE = (
    "Selon l’Insee, l’inflation — mesurée sur un an — atteint 2,1 % en septembre.\n"
    "Les prix de l’énergie   reculent."
)


def test_an_exact_quote_is_found() -> None:
    assert check_quote("l’inflation — mesurée sur un an — atteint 2,1 %", PAGE).ok


@pytest.mark.parametrize(
    "quote",
    [
        "L'INFLATION - mesurée sur un an - atteint 2,1 %",  # case, quotes, dashes
        "« les prix de l'énergie reculent »",  # wrapping quotes, spaces
        "atteint 2,1\u00a0% en septembre",  # no-break space
        "Selon l’Ins\u00adee, l’inflation",  # soft hyphen
        "ＳＥＬＯＮ l’Insee, l’inflation",  # full-width letters (NFKC)
    ],
)
def test_harmless_differences_are_tolerated(quote: str) -> None:
    assert check_quote(quote, PAGE).ok


@pytest.mark.parametrize(
    "quote",
    [
        "l’inflation atteint 2,1 % en septembre",  # words left out
        "l’inflation … atteint 2,1 %",  # ellipsis
        "l’inflation — mesurée sur un an — atteint 2,2 %",  # changed number
        "les prix de l’énergie baissent",  # paraphrase
    ],
)
def test_a_reworded_quote_is_rejected(quote: str) -> None:
    assert check_quote(quote, PAGE) == QuoteCheck(False, "citation absente du texte de la page")


def test_quote_length_limits() -> None:
    assert check_quote("2,1 %", PAGE).reason == "citation trop courte (< 10 caractères)"
    long_page = "mot " * 400
    too_long = check_quote("mot " * (MAX_QUOTE_CHARS // 4 + 1), long_page)
    assert too_long.reason == f"citation trop longue (> {MAX_QUOTE_CHARS} caractères)"


_ALPHABET = st.sampled_from(list("abcdeéèàçABC ,.'’-—«»\n\t"))


@given(st.lists(_ALPHABET, min_size=30, max_size=200).map("".join), st.data())
def test_any_slice_of_the_page_is_a_valid_quote(page: str, data: st.DataObject) -> None:
    start = data.draw(st.integers(0, len(page) - 1))
    end = data.draw(st.integers(start, len(page)))
    quote = page[start:end]
    if len(normalise(quote).strip(" \"'")) >= 10:
        assert check_quote(quote, page).ok


def test_citation_numbers_in_order() -> None:
    text = "A [2]. B [1, 3]. C [2-4] et [5–6]. D [1; 7]."
    assert citation_numbers(text) == [2, 1, 3, 4, 5, 6, 7]


@pytest.mark.parametrize(
    "text", ["[1](https://a.example/)", "[1][a]", "[1]: https://a.example/", "[a]", "[]", "[1a]"]
)
def test_links_and_references_are_not_citations(text: str) -> None:
    assert citation_numbers(text) == []


def test_reversed_or_huge_ranges_count_their_first_number_only() -> None:
    assert citation_numbers("[3-1] [10-999]") == [3, 10]


def test_dangling_citations() -> None:
    assert dangling_citations("A [1]. B [0]. C [2, 4].", source_count=3) == [0, 4]
    assert dangling_citations("A [1-3].", source_count=3) == []


def test_units_are_paragraphs_and_list_items() -> None:
    text = (
        "## Développement\n\n"
        "Premier paragraphe\nsur deux lignes [1].\n\n"
        "Introduction de liste :\n"
        "- premier point [2]\n"
        "  qui continue\n"
        "- second point\n"
        "1. étape\n\n\n"
        "Dernier paragraphe."
    )
    assert units(text) == [
        "Premier paragraphe sur deux lignes [1].",
        "Introduction de liste :",
        "- premier point [2] qui continue",
        "- second point",
        "1. étape",
        "Dernier paragraphe.",
    ]
    assert uncited_units(text) == [
        "Introduction de liste :",
        "- second point",
        "1. étape",
        "Dernier paragraphe.",
    ]


@given(st.text(alphabet=st.sampled_from([*"ab1 .-*#[]", "\n"]), max_size=200))
def test_unit_spans_locate_each_unit(text: str) -> None:
    spans, found = unit_spans(text), units(text)
    assert len(spans) == len(found)
    assert all(a < b <= c for (a, b), (c, _) in pairwise(spans))
    for (start, end), unit in zip(spans, found, strict=True):
        lines = text[start:end].splitlines()
        assert lines[0] == lines[0].lstrip() and lines[-1] == lines[-1].rstrip()
        assert unit.startswith(lines[0].strip()) and unit.endswith(lines[-1].strip())
