"""R1: numbers of a draft are read in FR and EN notations and matched against the sources."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.verification.numbers import extract_numbers, unmatched_numbers


def values(text: str) -> list[set[Decimal]]:
    return [{r.value for r in m.readings} for m in extract_numbers(text)]


def D(*numbers: str) -> set[Decimal]:
    return {Decimal(n) for n in numbers}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 234,5", D("1234.5")),
        ("1\u00a0234\u00a0567,25", D("1234567.25")),
        ("1\u202f234", D("1234")),
        ("1\u2009234.5", D("1234.5")),
        ("1,234.5", D("1234.5")),
        ("1.234,5", D("1234.5")),
        ("1,234,567", D("1234567")),
        ("1.234.567", D("1234567")),
        ("1,234", D("1.234", "1234")),  # ambiguous alone: both readings
        ("1.234", D("1.234", "1234")),
        ("0,125", D("0.125")),
        ("1234,567", D("1234.567")),
        ("12,5", D("12.5")),
        ("2026", D("2026")),
        ("12 %", D("12", "0.12")),
        ("12,5\u00a0%", D("12.5", "0.125")),
        ("12 pour cent", D("12", "0.12")),
        ("2,5 millions", D("2500000")),
        ("2,5 Millions", D("2500000")),
        ("3 Md€", D("3000000000")),
        ("4 Mds", D("4000000000")),
        ("1.2bn", D("1200000000")),
        ("2 billions", D("2000000000", "2000000000000")),  # English, French
        ("10k", D("10000")),
        ("12 M€", D("12000000")),
        ("5 mille", D("5000")),
    ],
)
def test_french_and_english_notations(text: str, expected: set[Decimal]) -> None:
    assert values(f"soit {text} environ") == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "[1]",
        "[1, 2]",
        "[3-5]",
        "<PERSONNE_12>",
        r"\<LIEU_2\>",
        "https://a.example/page/2024?id=77",
        "www.a.example/2024",
        "[lien](https://a.example/123)",
        "18/10/2026",
        "18.10.2026",
        "2026-10-18",
        "2026-10-18T12:30:00Z",
        "12:30",
        "12 h 30",
        "COVID-19",
        "H2O",
        "Q3",
        "24/7",
        "1/3",
        "3:1",
        "12 Mo",
    ],
)
def test_markers_identifiers_dates_and_urls_are_not_read(text: str) -> None:
    found = extract_numbers(f"voir {text} ici")
    assert [m.text for m in found if m.text != "12"] == []


def test_list_markers_are_not_read() -> None:
    assert [m.text for m in extract_numbers("1. premier\n  2) second 45\n3.5 %")] == [
        "45",
        "3.5 %",
    ]


def test_a_civility_is_not_a_scale() -> None:
    assert values("en 2026 M. <PERSONNE_1> a signé") == [D("2026")]


@pytest.mark.parametrize(
    ("text", "negative"),
    [("-3 %", True), ("\u22123 %", True), ("(-5)", True), ("10-20", False), ("x -2", True)],
)
def test_the_sign(text: str, negative: bool) -> None:
    assert extract_numbers(text)[-1].negative is negative


@pytest.mark.parametrize("text", ["3 options", "2 étapes", "0 erreur", "3 %", "€3", "-3"])
def test_small_counts_are_checked_too(text: str) -> None:
    """B33: a count in digits is a claim like any other; the prompt writes its own in letters."""
    assert len(unmatched_numbers(f"Il y a {text}.", ["rien"])) == 1


@pytest.mark.parametrize(
    "text", ["trois options", "la 2e étape", "1er point", "le 3ᵉ", "CAC40", "1. Lire", "M2"]
)
def test_words_ordinals_and_glued_numbers_are_not_read(text: str) -> None:
    assert unmatched_numbers(text, ["rien"]) == []


@pytest.mark.parametrize(
    ("draft", "source"),
    [
        ("12 %", "12,4 %"),  # rounded
        ("12,3 %", "12,34 %"),
        ("1,5 million", "1 512 000"),
        ("1 500 000", "1,5 million"),
        ("-3 %", "un recul de 3 %"),  # the same sign, written or said
        ("12 %", "un taux de 0,12"),
        ("1,234", "1 234"),
        ("2,1 Md€", "2 100 millions d'euros"),
        ("1.234.567", "1,234,567"),
    ],
)
def test_a_draft_number_supported_by_a_source(draft: str, source: str) -> None:
    assert unmatched_numbers(f"Le chiffre est {draft} [1].", [source]) == []


@pytest.mark.parametrize(
    ("draft", "source"),
    [
        ("12,34 %", "12,3 %"),  # more precise than the source
        ("13 %", "12,4 %"),
        ("42 000", "4 200"),
        ("1,6 million", "1 512 000"),
        ("2026", "en 2025"),
    ],
)
def test_a_draft_number_without_support(draft: str, source: str) -> None:
    assert [m.text for m in unmatched_numbers(f"Le chiffre est {draft}.", [source])] == [draft]


def test_the_question_and_several_sources_count() -> None:
    draft = "En 2026, trois sources donnent 12 % [1] et 7,5 Md€ [2]."
    sources = ["Quel taux en 2026 ?", "taux : 12 %", "budget de 7,5 milliards"]
    assert unmatched_numbers(draft, sources) == []
    assert [m.text for m in unmatched_numbers(draft, sources[1:])] == ["2026"]


@given(st.integers(0, 10**12), st.integers(0, 99))
def test_any_grouped_number_reads_back(integer: int, cents: int) -> None:
    english = f"{integer:,}.{cents:02d}"
    french = english.replace(",", "\u202f").replace(".", ",")
    expected = Decimal(f"{integer}.{cents:02d}")
    for text in (english, french):
        assert expected in values(f"total {text} euros")[0]
