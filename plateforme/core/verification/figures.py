"""The numbers of a tool output: each one carries its value, its French display and an id (R1).

The planner reads ``display`` and cites it as it is ("12 450,12 €", "2,34 %"). The check of a
draft matches a draft number against the value or the display of a figure; the id, unique within
one output, tells which part of which tool call a number comes from.

Displays follow French typography: a narrow no-break space between thousands, a decimal comma,
a no-break space before the unit. Rounding is half up, from the shortest decimal reading of a
float (``0.125`` displays ``0,13``), so the same value always displays the same way.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

THOUSANDS = " "  # narrow no-break space
BEFORE_UNIT = " "  # no-break space
SYMBOLS = {"EUR": "€"}  # other currencies display their ISO code: "1 234,50 USD"

FigureId = Annotated[str, Field(min_length=1, max_length=200)]


class Figure(BaseModel):
    """A number for the planner. ``unit``: a currency code, ``%`` (``value`` is a fraction),
    ``XXX/EUR`` (units of XXX for one euro), ``titres``, ``jours``, ``séances``, ``ans`` or
    ``score`` (in [0, 1])."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: FigureId
    value: Annotated[float, Field(allow_inf_nan=False)]
    display: str
    unit: str


def french(value: float | Decimal, decimals: int, *, max_decimals: int | None = None) -> str:
    """``value`` with ``decimals`` decimals, or up to ``max_decimals`` when they are not zeros."""
    exact = value if isinstance(value, Decimal) else Decimal(repr(value))
    if not exact.is_finite():
        raise ValueError("un nombre affiché est fini")
    shown = exact.quantize(Decimal(1).scaleb(-(max_decimals or decimals)), ROUND_HALF_UP)
    text = f"{abs(shown):f}"
    whole, _, fraction = text.partition(".")
    fraction = fraction.rstrip("0").ljust(decimals, "0") if max_decimals else fraction
    groups = []
    while len(whole) > 3:
        whole, groups = whole[:-3], [whole[-3:], *groups]
    body = THOUSANDS.join([whole, *groups]) + ("," + fraction if fraction else "")
    return ("-" if shown < 0 else "") + body


def noun(unit: str, value: float | Decimal) -> str:
    """French agreement: singular below two (``0 jour``, ``1,5 an``), plural from two."""
    return unit[:-1] if abs(value) < 2 and unit.endswith("s") else unit


def amount(figure_id: str, value: float | Decimal, currency: str) -> Figure:
    unit = SYMBOLS.get(currency, currency)
    return Figure(
        id=figure_id,
        value=float(value),
        display=f"{french(value, 2)}{BEFORE_UNIT}{unit}",
        unit=currency,
    )


def price(figure_id: str, value: float | Decimal, currency: str) -> Figure:
    """A unit price: two decimals, four when the price has them."""
    unit = SYMBOLS.get(currency, currency)
    return Figure(
        id=figure_id,
        value=float(value),
        display=f"{french(value, 2, max_decimals=4)}{BEFORE_UNIT}{unit}",
        unit=currency,
    )


def percent(figure_id: str, fraction: float) -> Figure:
    return Figure(
        id=figure_id,
        value=fraction,
        display=f"{french(Decimal(repr(fraction)) * 100, 2)}{BEFORE_UNIT}%",
        unit="%",
    )


def fx_rate(figure_id: str, rate: float, currency: str) -> Figure:
    """Units of ``currency`` for one euro, with the decimals the ECB publishes (up to six)."""
    return Figure(
        id=figure_id,
        value=rate,
        display=f"{french(rate, 2, max_decimals=6)}{BEFORE_UNIT}{currency} pour 1{BEFORE_UNIT}€",
        unit=f"{currency}/EUR",
    )


def quantity(figure_id: str, value: Decimal) -> Figure:
    """A number of securities, exact: ``1 800``, ``12,5``."""
    return Figure(
        id=figure_id,
        value=float(value),
        display=f"{french(value, 0, max_decimals=10)}{BEFORE_UNIT}{noun('titres', value)}",
        unit="titres",
    )


def count(figure_id: str, value: int, unit: str) -> Figure:
    return Figure(
        id=figure_id,
        value=value,
        display=f"{french(Decimal(value), 0)}{BEFORE_UNIT}{noun(unit, value)}",
        unit=unit,
    )


def plain(
    figure_id: str, value: float, unit: str, decimals: int = 2, *, show_unit: bool = False
) -> Figure:
    """A score (no unit in the display) or a duration in years (``8,4 ans``)."""
    shown = french(value, decimals)
    return Figure(
        id=figure_id,
        value=value,
        display=f"{shown}{BEFORE_UNIT}{noun(unit, value)}" if show_unit else shown,
        unit=unit,
    )


FIGURE_KEYS = frozenset(Figure.model_fields)


def figures_in(payload: object) -> tuple[list[Figure], list[str]]:
    """The figures of a structured tool output, and the JSON paths of the numbers outside one.

    A tool that follows R1 leaves the second list empty: a loose number has no display to cite
    and no id to trace.
    """
    figures: list[Figure] = []
    loose: list[str] = []

    def walk(item: object, where: str) -> None:
        if isinstance(item, dict):
            if item.keys() == FIGURE_KEYS:
                figures.append(Figure.model_validate(item))
                return
            for key, value in item.items():
                walk(value, f"{where}.{key}")
        elif isinstance(item, list):
            for i, value in enumerate(item):
                walk(value, f"{where}[{i}]")
        elif isinstance(item, int | float) and not isinstance(item, bool):
            loose.append(where)

    walk(payload, "$")
    return figures, loose
