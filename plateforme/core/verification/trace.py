"""Where each number and date of a draft comes from: the R1 trace (plan of phase 2, B33, B35).

The evidence of a request, in order of priority:

1. the figures of each tool output, by value then by display (``performance_report#1 ›
   mesures/twr``): a figure knows its unit and its sign (``numbers.py``);
2. the other texts of each tool output (string leaves, keys that hold a digit, numbers outside a
   figure), cited by the call alone (``finance_data#2``);
3. the texts the request gathered: the question, the date of the day, the pages read
   (``source [n]``) and the search results.

``trace`` lists the numbers and dates of a draft, in order, each with the first evidence that
supports it, or none. A number that a source matches with the contrary sign is *contrary*: it is
not traced. The audit keeps the table without the numbers themselves (R11), so the share of
traced numbers is measured on every request.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.verification.dates import DateKey, derived, extract_dates
from core.verification.figures import FIGURE_KEYS, Figure
from core.verification.numbers import (
    Sign,
    Support,
    extract_numbers,
    masked,
    supporting,
    text_supports,
)

TraceKind = Literal["nombre", "date", "mois", "jour", "heure"]
FIGURE_ORIGIN = " › "  # call › figure id
CallId = Annotated[str, Field(min_length=1, max_length=120)]


class ToolOutput(BaseModel):
    """What one tool call returned, as the check reads it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call: CallId  # "<tool>#<n>": the n-th call of this tool in the request
    tool: str
    figures: tuple[Figure, ...] = ()
    texts: tuple[str, ...] = ()


def tool_output(call: str, tool: str, payload: object) -> ToolOutput:
    """Split a structured tool output into its figures and its other texts."""
    figures: list[Figure] = []
    texts: list[str] = []

    def walk(item: object) -> None:
        if isinstance(item, dict):
            if item.keys() == FIGURE_KEYS:
                figures.append(Figure.model_validate(item))
                return
            for key, value in item.items():
                if any(ch.isdigit() for ch in str(key)):
                    texts.append(str(key))
                walk(value)
        elif isinstance(item, list | tuple):
            for value in item:
                walk(value)
        elif isinstance(item, str):
            texts.append(item)
        elif isinstance(item, int | float) and not isinstance(item, bool):
            texts.append(repr(item))  # a loose number: no display, cited as written

    walk(payload)
    return ToolOutput(call=call, tool=tool, figures=tuple(figures), texts=tuple(texts))


def _currencies(unit: str) -> frozenset[str]:
    if unit.endswith("/EUR"):  # a rate: units of XXX for one euro
        return frozenset({unit.removesuffix("/EUR")})
    is_code = len(unit) == 3 and unit.isalpha() and unit.isupper()  # EUR, USD
    return frozenset({unit}) if is_code else frozenset()


def _figure_sign(figure: Figure) -> Sign | None:
    """The sign the display shows: a value that rounds to zero has none."""
    shown = extract_numbers(figure.display)
    if shown and shown[0].sign == "-" and shown[0].explicit:
        return "-"
    if shown and all(r.value == 0 for r in shown[0].readings):
        return None
    return "+" if figure.value > 0 else "-" if figure.value < 0 else None


def figure_supports(figure: Figure, origin: str) -> list[Support]:
    """The value of a figure (a fraction for ``%``), then each number of its display."""
    sign = _figure_sign(figure)
    percent = figure.unit == "%"
    value = abs(Decimal(repr(figure.value)))
    supports = [
        Support(frozenset({value}), origin, percent, _currencies(figure.unit), sign, exact=True)
    ]
    for shown in extract_numbers(figure.display):
        french = shown.readings[: 2 if shown.percent else 1]  # 1,175 is never 1175 here
        values = frozenset(r.value for r in french if r.fraction is shown.percent)
        currencies = frozenset({shown.currency}) if shown.currency else frozenset()
        supports.append(Support(values, origin, shown.percent, currencies, sign, exact=True))
    return supports


@dataclass(frozen=True)
class Traced:
    kind: TraceKind
    text: str
    start: int
    end: int
    origin: str | None  # the supporting evidence, or the contrary one
    contrary: bool = False  # a source matches the value with the contrary sign

    @property
    def traced(self) -> bool:
        return self.origin is not None and not self.contrary


class Evidence:
    """The numbers and dates a request may cite, each with its origin."""

    def __init__(
        self, texts: Iterable[tuple[str, str]] = (), outputs: Iterable[ToolOutput] = ()
    ) -> None:
        self.supports: list[Support] = []
        self.dates: dict[DateKey, tuple[int, str]] = {}  # rank of the first origin, origin
        sourced: list[tuple[str, str]] = []
        for output in outputs:
            for figure in output.figures:
                self.supports += figure_supports(figure, f"{output.call}{FIGURE_ORIGIN}{figure.id}")
            sourced += [(output.call, text) for text in output.texts]
        for rank, (origin, text) in enumerate([*sourced, *texts]):
            self.supports += text_supports(text, origin)
            keys = {key for d in extract_dates(masked(text), lenient=True) for key in d.keys}
            for key in derived(keys):
                self.dates.setdefault(key, (rank, origin))


def trace(draft: str, evidence: Evidence) -> list[Traced]:
    """The numbers and dates of ``draft``, in order, each with its origin or none."""
    rows: list[Traced] = []
    for mention in extract_numbers(draft):
        support, contrary = supporting(mention, evidence.supports)
        origin = support.origin if support is not None else None
        rows.append(Traced("nombre", mention.text, mention.start, mention.end, origin, contrary))
    for found in extract_dates(masked(draft)):
        known = [evidence.dates.get(key) for key in found.keys]
        origin = min(o for o in known if o is not None)[1] if all(known) else None
        rows.append(Traced(found.kind, found.text, found.start, found.end, origin))
    return sorted(rows, key=lambda row: row.start)


__all__ = [
    "FIGURE_ORIGIN",
    "Evidence",
    "ToolOutput",
    "TraceKind",
    "Traced",
    "figure_supports",
    "tool_output",
    "trace",
]
