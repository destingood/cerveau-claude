"""The Risk Gate against its independent oracle, on worlds drawn near every edge (ADR-031).

The main property runs 10 000 derandomized cases, so that the CI replays the same ones; it also
counts the outcomes and the edges and faults drawn, so that a generator drifting to all refusals
cannot pass silently. The other properties need no oracle: a tighter limit never buys more, an
unknown limit refuses and says which, the intent's form changes nothing, and a reduced order is
accepted as it was reduced.
"""

from __future__ import annotations

from collections import Counter
from decimal import ROUND_FLOOR
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from core.risk_gate.gate import UNKNOWN, RiskGateResult, evaluate
from tests.risk_gate.cases import (
    COST_KEYS,
    EDGES,
    FAULTS,
    LIMIT_KEYS,
    QUANTITY_AIMS,
    TINY,
    Case,
    World,
    base_world,
    build,
    cases,
    changed,
)
from tests.risk_gate.oracle import FIXED, SIZED, expected

_COMMON: dict[str, Any] = {
    "derandomize": True,
    "deadline": None,
    "database": None,
    "suppress_health_check": [HealthCheck.too_slow, HealthCheck.data_too_large],
}
MAIN = settings(max_examples=10_000, **_COMMON)
SIDE = settings(max_examples=1_000, **_COMMON)
MIN_SHARE = 0.15  # of each outcome among the 10 000 cases
MIN_DRAWN = 10  # times each edge, fault and quantity aim is drawn

# Where a marker can stand, and the name its check must give (R7).
MARKABLE = (
    *(("limits", key) for key in LIMIT_KEYS),
    *(("costs", key) for key in COST_KEYS),
    ("quality", "max_staleness_sessions"),
    ("compliance", "exclusions_personnelles"),
)
# Halving these, or doubling the volume minimum, only tightens the gate.
TIGHTENABLE = (*(k for k in LIMIT_KEYS if k.endswith("_pct")), "capital_reference_eur")
TIGHTENABLE_MORE = ("max_orders_per_hour", "max_orders_per_day", "min_avg_daily_volume", "cash")


def check_invariants(got: RiskGateResult) -> None:
    """What any answer of the gate must satisfy, whatever the world."""
    names = [check.name for check in got.checks]
    if got.intent_id is None:
        assert names == ["schema"]
        assert got.result == "REFUSE"
    else:
        assert names == ["schema", *FIXED, *SIZED]
    requested = got.requested_quantity or 0
    if got.result == "ACCEPTE":
        assert got.quantity == requested
        assert got.reasons == ("toutes les vérifications passent",)
    elif got.result == "REDUIT":
        assert 1 <= got.quantity < requested
        assert got.reasons[-1] == f"quantité ramenée de {requested} à {got.quantity}"
    else:
        assert got.quantity == 0
    for check in got.checks:
        if not check.ok:
            assert any(reason.startswith(f"{check.name} : ") for reason in got.reasons)


def test_the_gate_agrees_with_its_oracle_on_10_000_generated_cases() -> None:
    outcomes: Counter[str] = Counter()
    drawn: Counter[str] = Counter()

    @MAIN
    @given(cases())
    def agree(case: Case) -> None:
        got = evaluate(*case.args)
        want = expected(case.args)
        assert (got.result, got.quantity) == (want.result, want.quantity), case.label
        assert {c.name for c in got.checks if not c.ok} == want.failed, case.label
        check_invariants(got)
        outcomes[got.result] += 1
        drawn.update(case.label.split())

    agree()
    total = sum(outcomes.values())
    assert total >= 10_000
    for result in ("ACCEPTE", "REDUIT", "REFUSE"):
        assert outcomes[result] >= MIN_SHARE * total, outcomes
    expected_labels = (
        *(f"edge:{edge}" for edge in EDGES),
        *FAULTS,
        *(f"quantity:{aim}" for aim in QUANTITY_AIMS),
    )
    rare = {label: drawn[label] for label in expected_labels if drawn[label] < MIN_DRAWN}
    assert not rare, rare


def _tightened(world: World, key: str) -> World | None:
    if key == "cash":
        cash = world["snapshot"]["account"]["cash_eur"]
        return changed(world, snapshot__account__cash_eur=(cash / 2).quantize(TINY, ROUND_FLOOR))
    value = world["limits"][key]
    if isinstance(value, str):
        return None  # a marker refuses already: nothing to tighten
    if key == "min_avg_daily_volume":
        return changed(world, limits__min_avg_daily_volume=value * 2)
    if isinstance(value, int):
        return changed(world, **{f"limits__{key}": max(1, value // 2)})
    return changed(world, **{f"limits__{key}": value / 2})


@SIDE
@given(cases(), st.sampled_from((*TIGHTENABLE, *TIGHTENABLE_MORE)))
def test_a_tighter_limit_never_retains_more(case: Case, key: str) -> None:
    tight = _tightened(case.world, key)
    if tight is None:
        return
    base = evaluate(*case.args)
    tighter = evaluate(*build(tight, case.form).args)
    assert tighter.quantity <= base.quantity, (case.label, key)
    if base.result == "REFUSE":
        assert tighter.result == "REFUSE"


def _marked(world: World, part: str, key: str) -> World:
    marker = ["A_DEFINIR"] if key == "exclusions_personnelles" else "A_DEFINIR"
    return changed(world, **{f"{part}__{key}": marker})


@SIDE
@given(cases(max_faults=0), st.sampled_from(MARKABLE))
def test_an_unknown_limit_refuses_and_names_itself(case: Case, where: tuple[str, str]) -> None:
    got = evaluate(*build(_marked(case.world, *where), case.form).args)
    assert (got.result, got.quantity) == ("REFUSE", 0)
    key = where[1]
    assert any(c.value == UNKNOWN and key in c.reason for c in got.checks), (case.label, key)


@pytest.mark.parametrize(("part", "key"), MARKABLE)
def test_every_marker_refuses_the_base_order(part: str, key: str) -> None:
    got = evaluate(*build(_marked(base_world(), part, key)).args)
    assert (got.result, got.quantity) == ("REFUSE", 0)
    unknown = [c for c in got.checks if c.value == UNKNOWN]
    assert unknown
    assert all(key in c.reason for c in unknown)


@SIDE
@given(cases())
def test_the_answer_depends_on_the_intent_not_on_its_form(case: Case) -> None:
    answers = [evaluate(*build(case.world, form).args) for form in ("model", "dict", "json")]
    again = evaluate(*case.args)
    assert answers[0] == answers[1] == answers[2] == again


@SIDE
@given(cases())
def test_a_reduced_order_is_accepted_as_reduced(case: Case) -> None:
    got = evaluate(*case.args)
    if got.result != "REDUIT":
        return
    reduced = evaluate(*build(changed(case.world, intent__quantity=got.quantity)).args)
    assert (reduced.result, reduced.quantity) == ("ACCEPTE", got.quantity)
    one_more = evaluate(*build(changed(case.world, intent__quantity=got.quantity + 1)).args)
    assert (one_more.result, one_more.quantity) == ("REDUIT", got.quantity)
