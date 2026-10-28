"""Rate limit shared across processes: lock, interval and state file (core.net.throttle).

Two instances on the same files stand for two plugin processes: the OS lock is held per open
file (``flock``) or per handle (``LockFileEx``), so they exclude each other within one process too.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.net.guard import FetchError
from core.net.throttle import SharedThrottle


class Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)


def _throttle(directory: Path, clock: Clock, **options: float) -> SharedThrottle:
    return SharedThrottle(directory, "api", 3.0, clock=clock, sleep=clock.sleep, **options)


async def _request(throttle: SharedThrottle, clock: Clock, duration: float = 0.5) -> None:
    async with throttle.slot():
        clock.now += duration


def test_the_first_request_does_not_wait_and_records_its_end(tmp_path: Path) -> None:
    clock = Clock()
    throttle = _throttle(tmp_path / "net", clock)
    asyncio.run(_request(throttle, clock))
    assert clock.sleeps == []
    assert float((tmp_path / "net" / "api.last").read_text(encoding="ascii")) == 1_000.5
    assert not (tmp_path / "net" / "api.tmp").exists()


def test_the_next_request_waits_the_rest_of_the_interval(tmp_path: Path) -> None:
    clock = Clock()
    first, second = _throttle(tmp_path, clock), _throttle(tmp_path, clock)
    asyncio.run(_request(first, clock))
    clock.now += 1.0
    asyncio.run(_request(second, clock))
    assert clock.sleeps == [2.0]
    clock.now += 10.0
    asyncio.run(_request(first, clock))
    assert clock.sleeps == [2.0]


@pytest.mark.parametrize("state", [b"abc", b"\xff", b"nan", b"5000.0"])
def test_an_unreadable_or_future_state_waits_the_whole_interval(
    tmp_path: Path, state: bytes
) -> None:
    (tmp_path / "api.last").write_bytes(state)
    clock = Clock()
    asyncio.run(_request(_throttle(tmp_path, clock), clock))
    assert clock.sleeps == [3.0]


def test_a_failed_request_still_counts_and_releases_the_lock(tmp_path: Path) -> None:
    clock = Clock()
    throttle = _throttle(tmp_path, clock)

    async def fail() -> None:
        async with throttle.slot():
            raise RuntimeError("network down")

    with pytest.raises(RuntimeError):
        asyncio.run(fail())
    asyncio.run(_request(_throttle(tmp_path, clock), clock))
    assert clock.sleeps == [3.0]


def test_a_second_process_waits_for_the_lock_then_for_the_interval(tmp_path: Path) -> None:
    clock = Clock()
    holder, waiter = _throttle(tmp_path, clock), _throttle(tmp_path, clock, poll_s=0.25)
    order: list[str] = []

    async def go() -> None:
        entered = asyncio.Event()

        async def hold() -> None:
            async with holder.slot():
                entered.set()
                for _ in range(3):
                    await asyncio.sleep(0)
                order.append("holder done")

        task = asyncio.create_task(hold())
        await entered.wait()
        async with waiter.slot():
            order.append("waiter in")
        await task

    asyncio.run(go())
    assert order == ["holder done", "waiter in"]
    polls = [s for s in clock.sleeps if s == 0.25]
    # The holder ends after the polls: the waiter then waits the whole interval.
    assert polls and clock.sleeps == [*polls, 3.0]


def test_a_lock_held_too_long_is_an_error(tmp_path: Path) -> None:
    clock = Clock()
    holder, waiter = _throttle(tmp_path, clock), _throttle(tmp_path, clock, wait_max_s=1.0)

    async def go() -> None:
        async with holder.slot():
            with pytest.raises(FetchError, match=r"source occupée .* depuis 1 s"):
                async with waiter.slot():
                    pytest.fail("the lock is held")

    asyncio.run(go())
    assert clock.sleeps == [0.1] * 10
