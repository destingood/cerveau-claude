"""The R1 trace: each number and date of a draft with its origin (core.verification.trace)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from core.verification.figures import amount, count, fx_rate, percent
from core.verification.trace import Evidence, ToolOutput, Traced, tool_output, trace

NOW = "2026-10-18T15:00+02:00"
REPORT = ToolOutput(
    call="performance_report#1",
    tool="performance_report",
    figures=(
        percent("mesures/twr", 0.088),
        percent("mesures/volatilite", -0.0548),  # a negative figure, for the signs
        amount("valeurs/frais_eur", Decimal("-60"), "EUR"),
        amount("valeurs/finale", Decimal("4833.42"), "EUR"),
        fx_rate("taux/USD", 1.175, "USD"),
        count("periode/seances", 3, "séances"),
    ),
    texts=("2025-01-01", "2025-12-31"),
)
EVIDENCE = Evidence(
    [("question", "Quelle performance ?"), ("date du jour", NOW), ("source [1]", "12 %")],
    [REPORT],
)


def rows(draft: str, evidence: Evidence = EVIDENCE) -> list[Traced]:
    return trace(draft, evidence)


def origins(draft: str, evidence: Evidence = EVIDENCE) -> list[str | None]:
    return [row.origin if row.traced else None for row in rows(draft, evidence)]


@pytest.mark.parametrize(
    ("draft", "origin"),
    [
        ("TWR de 8,80 %", "performance_report#1 › mesures/twr"),
        ("TWR de 8,8 %", "performance_report#1 › mesures/twr"),  # the value, rounded
        ("valeur finale de 4 833,42 €", "performance_report#1 › valeurs/finale"),
        ("valeur finale de 4 833,42", "performance_report#1 › valeurs/finale"),
        ("un taux de 1,175 USD", "performance_report#1 › taux/USD"),
        ("sur trois séances, soit 3 séances", "performance_report#1 › periode/seances"),
        ("un taux de 12 %", "source [1]"),
    ],
)
def test_a_number_traces_to_its_figure(draft: str, origin: str) -> None:
    assert origins(draft) == [origin]


@pytest.mark.parametrize(
    "draft",
    [
        "TWR de 0,088",  # a fraction without % is not the percentage figure
        "valeur finale de 4 833,42 USD",  # another currency
        "TWR de 8,81 %",
        "TWR de 7 %",  # 9 % would be 8,80 % rounded
        "1 175 USD",  # 1,175 of a figure display is never read 1175
        "4 options",  # a small count is checked too (units other than % and currencies are not)
    ],
)
def test_a_number_without_support(draft: str) -> None:
    assert origins(draft) == [None]
    assert not rows(draft)[0].contrary


@pytest.mark.parametrize(
    "draft",
    [
        "volatilité de -5,48 %",
        "volatilité de −5,48 %",
        "une baisse de 5,48 %",
        "un recul de 5,48 % sur l'année",
        "frais de 60,00 €",  # a cost is a down word
        "frais de -60,00 €",
        "TWR de 8,80 %",
        "TWR de +8,80 %",
        "une hausse de 8,80 %",
    ],
)
def test_the_sign_agrees(draft: str) -> None:
    assert all(row.traced for row in rows(draft))


@pytest.mark.parametrize(
    ("draft", "origin"),
    [
        ("volatilité de 5,48 %", "performance_report#1 › mesures/volatilite"),
        ("volatilité de +5,48 %", "performance_report#1 › mesures/volatilite"),
        ("une hausse de 5,48 %", "performance_report#1 › mesures/volatilite"),
        ("TWR de -8,80 %", "performance_report#1 › mesures/twr"),
        ("frais de +60,00 €", "performance_report#1 › valeurs/frais_eur"),
    ],
)
def test_the_contrary_sign_is_not_traced(draft: str, origin: str) -> None:
    (row,) = rows(draft)
    assert (row.traced, row.contrary, row.origin) == (False, True, origin)


def test_a_down_word_against_a_positive_figure_is_a_known_limit() -> None:
    """B35: « a baissé de 8,80 % » may describe a fall in a cost; the reviewer reads it."""
    assert all(row.traced for row in rows("le TWR a baissé de 8,80 %"))


def test_years_and_dates_trace_to_the_tool_texts() -> None:
    found = rows("Du 1er janvier 2025 au 31/12/2025, TWR de 8,80 % en 2025.")
    assert [(row.kind, row.origin) for row in found] == [
        ("date", "performance_report#1"),
        ("date", "performance_report#1"),
        ("nombre", "performance_report#1 › mesures/twr"),
        ("nombre", "performance_report#1"),
    ]
    assert origins("en 2027") == [None]
    assert [row.kind for row in rows("le 12/03/2025")] == ["date"]
    assert origins("le 12/03/2025") == [None]


def test_the_date_of_the_day_is_evidence() -> None:
    found = rows("Au 18/10/2026 à 15 h, en octobre 2026, le 18 octobre.")
    assert [(row.kind, row.origin) for row in found] == [
        ("date", "date du jour"),
        ("heure", "date du jour"),
        ("mois", "date du jour"),
        ("jour", "date du jour"),
    ]
    assert origins("à 13 h") == [None]  # no time zone is converted


def test_the_first_evidence_wins() -> None:
    first = Evidence([("question", "8,80 % en 2025")], [REPORT])
    assert origins("8,80 % en 2025", first) == [
        "performance_report#1 › mesures/twr",
        "performance_report#1",
    ]
    later = ToolOutput(call="t#2", tool="t", texts=("2025-01-01",))
    assert origins("le 01/01/2025", Evidence([], [later, REPORT])) == ["t#2"]


def test_citations_and_markers_are_not_numbers() -> None:
    assert rows("TWR de 8,80 % [1, 2] [VERIFICATION REQUIRED].")[0].text.strip() == "8,80 %"
    assert len(rows("TWR de 8,80 % [1, 2].")) == 1


def test_tool_output_splits_figures_and_texts() -> None:
    payload = {
        "mesures": {"twr": percent("mesures/twr", 0.088).model_dump()},
        "periode": {"debut": "2025-01-01", "jours": [364]},
        "2025": "année",
        "complet": True,
    }
    output = tool_output("performance_report#1", "performance_report", payload)
    assert [f.id for f in output.figures] == ["mesures/twr"]
    assert output.texts == ("2025-01-01", "364", "2025", "année")


@given(st.integers(-(10**11), 10**11))
def test_any_amount_display_traces_back(cents: int) -> None:
    figure = amount("valeurs/x", Decimal(cents) / 100, "EUR")
    known = Evidence([], [ToolOutput(call="t#1", tool="t", figures=(figure,))])
    assert origins(f"montant de {figure.display}", known) == ["t#1 › valeurs/x"]


@given(st.integers(-(10**6), 10**6))
def test_any_percentage_display_traces_back_and_its_opposite_is_contrary(ppm: int) -> None:
    figure = percent("mesures/x", ppm / 10**6)
    known = Evidence([], [ToolOutput(call="t#1", tool="t", figures=(figure,))])
    assert origins(f"mesure de {figure.display}", known) == ["t#1 › mesures/x"]
    shown = figure.display.removeprefix("-")
    assume(any(ch in "123456789" for ch in shown))
    opposite = f"+{shown}" if figure.display.startswith("-") else f"-{shown}"
    (row,) = rows(f"mesure de {opposite}", known)
    assert row.contrary
