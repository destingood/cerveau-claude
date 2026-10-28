"""UUID version 7 (RFC 9562, §5.7): a 48-bit Unix time in milliseconds, then random bits.

Python 3.12 has no generator (``uuid.uuid7`` arrives in 3.14), and a dependency for some fifteen
lines is not worth its supply chain (ADR-029). The identifiers sort by creation time: within one
millisecond, a 42-bit counter fills ``rand_a`` and the top of ``rand_b`` (RFC 9562, §6.2,
method 1, at its longest). The counter is seeded at random on each new millisecond, its top bit
clear so that it can count; when it rolls over, or when the clock steps back, the timestamp moves
ahead of the clock rather than break the order (§6.2).
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from uuid import UUID

TIMESTAMP_BITS = 48
COUNTER_BITS = 42  # rand_a (12 bits) and the top 30 bits of rand_b
_TAIL_BITS = 32  # the rest of rand_b: random on every identifier
_RAND_B_COUNTER_BITS = COUNTER_BITS - 12


def uuid7_from_fields(unix_ts_ms: int, rand_a: int, rand_b: int) -> UUID:
    """The RFC 9562 layout: timestamp, version 7, ``rand_a``, variant ``10``, ``rand_b``."""
    if not 0 <= unix_ts_ms < 1 << TIMESTAMP_BITS:
        raise ValueError("unix_ts_ms hors de 48 bits")
    if not 0 <= rand_a < 1 << 12 or not 0 <= rand_b < 1 << 62:
        raise ValueError("rand_a ou rand_b hors de leur taille")
    return UUID(int=unix_ts_ms << 80 | 0x7 << 76 | rand_a << 64 | 0b10 << 62 | rand_b)


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


class Uuid7Generator:
    """Monotonic UUIDv7 identifiers; the clock and the random source are injectable for tests."""

    def __init__(
        self,
        clock_ms: Callable[[], int] = _now_ms,
        random_bits: Callable[[int], int] = secrets.randbits,
    ) -> None:
        self._clock_ms = clock_ms
        self._random_bits = random_bits
        self._lock = threading.Lock()
        self._last_ms = -1
        self._counter = 0

    def __call__(self) -> UUID:
        with self._lock:
            now = self._clock_ms()
            if now > self._last_ms:
                self._last_ms = now
                self._counter = self._random_bits(COUNTER_BITS - 1)
            else:  # same millisecond, or a clock that stepped back
                self._counter += 1
                if self._counter >> COUNTER_BITS:
                    self._last_ms += 1
                    self._counter = self._random_bits(COUNTER_BITS - 1)
            rand_a = self._counter >> _RAND_B_COUNTER_BITS
            low = self._counter & ((1 << _RAND_B_COUNTER_BITS) - 1)
            rand_b = low << _TAIL_BITS | self._random_bits(_TAIL_BITS)
            return uuid7_from_fields(self._last_ms, rand_a, rand_b)


uuid7 = Uuid7Generator()
