"""Time limit sent with an MCP tool call (ADR-052)."""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.mcp.time_limit import (
    MAX_TOOL_TIMEOUT_S,
    TIME_LIMIT_META_KEY,
    time_limit,
    time_limit_meta,
)


def test_the_key_has_the_form_of_an_mcp_meta_key() -> None:
    prefix, _, name = TIME_LIMIT_META_KEY.partition("/")
    assert prefix == "cerveau" and name == "time_limit_s"


@given(st.floats(min_value=0, max_value=MAX_TOOL_TIMEOUT_S, allow_nan=False))
def test_a_limit_sent_is_the_limit_read(seconds: float) -> None:
    assert time_limit(time_limit_meta(seconds)) == pytest.approx(seconds, abs=1e-3)


def test_a_negative_limit_is_sent_as_zero() -> None:
    assert time_limit_meta(-3) == {TIME_LIMIT_META_KEY: 0.0}


@pytest.mark.parametrize(
    "meta",
    [
        None,
        {},
        {"progress_token": 1},
        {TIME_LIMIT_META_KEY: "300"},
        {TIME_LIMIT_META_KEY: True},
        {TIME_LIMIT_META_KEY: None},
        {TIME_LIMIT_META_KEY: math.nan},
        {TIME_LIMIT_META_KEY: math.inf},
    ],
)
def test_an_absent_or_invalid_limit_is_none(meta: dict[str, object] | None) -> None:
    assert time_limit(meta) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [(-5, 0.0), (0, 0.0), (12, 12.0), (MAX_TOOL_TIMEOUT_S + 1, MAX_TOOL_TIMEOUT_S)],
)
def test_a_limit_is_brought_within_bounds(value: float, expected: float) -> None:
    assert time_limit({TIME_LIMIT_META_KEY: value}) == expected
