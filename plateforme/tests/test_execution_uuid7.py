from __future__ import annotations

import itertools
import random
from collections.abc import Callable
from uuid import RFC_4122, UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.execution.uuid7 import COUNTER_BITS, Uuid7Generator, uuid7, uuid7_from_fields


def seeded_bits(seed: int) -> Callable[[int], int]:
    return random.Random(seed).getrandbits  # noqa: S311 - seeded test data, not cryptography


def timestamp_ms(value: UUID) -> int:
    return value.int >> 80


def test_the_layout_matches_the_example_of_rfc_9562() -> None:
    """RFC 9562, Appendix A.6: 0x017F22E279B0 is 2022-02-22 19:22:22 UTC."""
    value = uuid7_from_fields(0x017F22E279B0, 0xCC3, 0x18C4DC0C0C07398F)
    assert str(value).upper() == "017F22E2-79B0-7CC3-98C4-DC0C0C07398F"
    assert value.version == 7
    assert value.variant == RFC_4122


@pytest.mark.parametrize(
    ("unix_ts_ms", "rand_a", "rand_b"),
    [(-1, 0, 0), (1 << 48, 0, 0), (0, 1 << 12, 0), (0, -1, 0), (0, 0, 1 << 62), (0, 0, -1)],
)
def test_a_field_out_of_its_size_is_refused(unix_ts_ms: int, rand_a: int, rand_b: int) -> None:
    with pytest.raises(ValueError, match="hors"):
        uuid7_from_fields(unix_ts_ms, rand_a, rand_b)


def test_the_default_generator_stamps_the_current_millisecond() -> None:
    first, second = uuid7(), uuid7()
    assert first.version == second.version == 7
    assert first < second
    assert abs(timestamp_ms(first) - 1_792_000_000_000) < 10**12  # a 2026-era clock, not zero


def test_identifiers_within_one_millisecond_count_up() -> None:
    generate = Uuid7Generator(clock_ms=lambda: 1_000, random_bits=seeded_bits(7))
    values = [generate() for _ in range(1_000)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)
    assert {timestamp_ms(value) for value in values} == {1_000}


def test_a_counter_rollover_moves_the_timestamp_ahead() -> None:
    top = (1 << (COUNTER_BITS - 1)) - 1

    def bits(n: int) -> int:
        return top if n == COUNTER_BITS - 1 else 0

    generate = Uuid7Generator(clock_ms=lambda: 5, random_bits=bits)
    values = [generate() for _ in range(3)]
    generate._counter = (1 << COUNTER_BITS) - 1  # the last value the counter can hold
    values.append(generate())
    assert values == sorted(values)
    assert timestamp_ms(values[-1]) == 6


@settings(max_examples=200, deadline=None)
@given(
    clock=st.lists(st.integers(min_value=0, max_value=(1 << 47)), min_size=1, max_size=60),
    seed=st.integers(min_value=0, max_value=2**32),
)
def test_identifiers_sort_in_creation_order_whatever_the_clock(clock: list[int], seed: int) -> None:
    """A clock that repeats or steps back never breaks the order (RFC 9562, §6.2)."""
    ticks = iter(clock)
    generate = Uuid7Generator(clock_ms=lambda: next(ticks), random_bits=seeded_bits(seed))
    values = [generate() for _ in clock]
    assert all(a < b for a, b in itertools.pairwise(values))
    assert all(value.version == 7 and value.variant == RFC_4122 for value in values)
    assert all(timestamp_ms(v) >= tick for v, tick in zip(values, clock, strict=True))
