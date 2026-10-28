"""The figures of a tool output: French displays, agreement, and the walk that finds them (R1)."""

from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from core.verification.figures import (
    BEFORE_UNIT,
    THOUSANDS,
    Figure,
    amount,
    count,
    figures_in,
    french,
    fx_rate,
    percent,
    plain,
    price,
    quantity,
)

N, NN = THOUSANDS, BEFORE_UNIT


@pytest.mark.parametrize(
    ("figure", "display"),
    [
        (amount("a", 12450.125, "EUR"), f"12{N}450,13{NN}€"),
        (amount("a", -0.004, "EUR"), f"0,00{NN}€"),
        (amount("a", -1234.5, "USD"), f"-1{N}234,50{NN}USD"),
        (amount("a", Decimal("1000000"), "EUR"), f"1{N}000{N}000,00{NN}€"),
        (price("p", 42.405, "USD"), f"42,405{NN}USD"),
        (price("p", 278.1, "USD"), f"278,10{NN}USD"),
        (price("p", 176.4775, "USD"), f"176,4775{NN}USD"),
        (price("p", 9.123456, "EUR"), f"9,1235{NN}€"),
        (percent("w", 0.02345), f"2,35{NN}%"),
        (percent("w", -0.5), f"-50,00{NN}%"),
        (fx_rate("r", 1.0912, "USD"), f"1,0912{NN}USD pour 1{NN}€"),
        (fx_rate("r", 163.5, "JPY"), f"163,50{NN}JPY pour 1{NN}€"),
        (quantity("q", Decimal("1800")), f"1{N}800{NN}titres"),
        (quantity("q", Decimal("1")), f"1{NN}titre"),
        (quantity("q", Decimal("12.5")), f"12,5{NN}titres"),
        (count("c", 0, "jours"), f"0{NN}jour"),
        (count("c", 2, "jours"), f"2{NN}jours"),
        (count("c", 1234, "séances"), f"1{N}234{NN}séances"),
        (plain("d", 8.4, "ans", 1, show_unit=True), f"8,4{NN}ans"),
        (plain("d", 1.5, "ans", 1, show_unit=True), f"1,5{NN}an"),
        (plain("s", 0.998, "score", 3), "0,998"),
    ],
)
def test_displays_follow_french_typography(figure: Figure, display: str) -> None:
    assert figure.display == display


def test_rounding_is_half_up_from_the_shortest_reading() -> None:
    """0.125 is stored a hair above, 2.675 a hair below: both round as written."""
    assert french(0.125, 2) == "0,13"
    assert french(2.675, 2) == "2,68"
    assert french(Decimal("2.665"), 2) == "2,67"


def test_a_figure_keeps_the_value_it_displays() -> None:
    figure = quantity("FICT-ACME/quantite", Decimal("1800"))
    assert figure.value == 1800.0 and figure.unit == "titres"
    assert percent("w", 0.25).value == 0.25
    assert fx_rate("r", 1.0912, "USD").unit == "USD/EUR"
    assert amount("a", 1.5, "EUR").unit == "EUR"


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_a_non_finite_number_is_never_displayed(value: float) -> None:
    with pytest.raises(ValueError, match="fini"):
        french(value, 2)
    with pytest.raises(ValidationError):
        Figure(id="x", value=value, display="?", unit="EUR")


def test_a_figure_is_closed_and_frozen() -> None:
    with pytest.raises(ValidationError):
        Figure.model_validate({"id": "x", "value": 1.0, "display": "1", "unit": "u", "note": "y"})
    with pytest.raises(ValidationError):
        Figure(id="", value=1.0, display="1", unit="u")
    figure = amount("a", 1.0, "EUR")
    with pytest.raises(ValidationError):
        figure.value = 2.0  # type: ignore[misc]


def test_figures_in_finds_the_figures_and_the_loose_numbers() -> None:
    payload = {
        "total": amount("total", 10.0, "EUR").model_dump(),
        "lines": [{"weight": percent("w", 0.5).model_dump(), "rank": 1}],
        "flags": [True, False],
        "score": 0.5,
        "note": None,
        "label": "12,5 %",
        "almost": {"id": "x", "value": 1.0, "display": "1", "unit": "u", "extra": 2},
    }
    figures, loose = figures_in(payload)
    assert [f.id for f in figures] == ["total", "w"]
    assert loose == ["$.lines[0].rank", "$.score", "$.almost.value", "$.almost.extra"]


def test_figures_in_refuses_a_figure_that_breaks_its_schema() -> None:
    with pytest.raises(ValidationError):
        figures_in({"bad": {"id": "x", "value": "beaucoup", "display": "1", "unit": "u"}})


DISPLAY = re.compile(rf"-?\d{{1,3}}({N}\d{{3}})*,\d{{2}}")


@given(st.floats(min_value=-1e12, max_value=1e12, allow_nan=False, allow_infinity=False))
def test_french_reads_back_as_the_half_up_value(value: float) -> None:
    text = french(value, 2)
    assert DISPLAY.fullmatch(text)
    expected = Decimal(repr(value)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    assert Decimal(text.replace(N, "").replace(",", ".")) == expected
    assert not text.startswith("-") or expected < 0


@given(st.decimals(min_value=0, max_value=10**9, places=4, allow_nan=False))
def test_a_quantity_shows_every_decimal_it_has(value: Decimal) -> None:
    number, unit = quantity("q", value).display.split(NN)
    assert Decimal(number.replace(N, "").replace(",", ".")) == value
    assert unit == ("titre" if value < 2 else "titres")
