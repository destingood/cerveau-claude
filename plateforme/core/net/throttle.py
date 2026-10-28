"""Rate limit shared by every process of the machine, for the APIs that set one (ADR-044).

Each tool call runs in its own plugin process (``LazyPlugin``), and the terms of arXiv count
requests from all the machines of a user: one connection at a time and a minimum interval
between two requests. A lock file serialises the requests (it is held for the whole request,
and the OS releases it if the process dies) and a state file keeps the wall-clock end of the
last request. A state file that cannot be read, or a date in the future (clock set back), makes
the next request wait the whole interval.

The two OS lock calls are excluded from the coverage measure, since each platform runs only one
of them; the tests run them on Windows and on Linux (CI matrix).
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from core.net.guard import FetchError

WAIT_MAX_S = 30.0
POLL_S = 0.1

if sys.platform == "win32":  # pragma: no cover - one backend per platform
    import msvcrt

    def _try_lock(fd: int) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:  # pragma: no cover - one backend per platform
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


class SharedThrottle:
    """At most one request at a time and ``interval_s`` between two, across processes."""

    def __init__(
        self,
        directory: Path,
        name: str,
        interval_s: float,
        *,
        wait_max_s: float = WAIT_MAX_S,
        poll_s: float = POLL_S,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.directory, self.interval_s = directory, interval_s
        self.lock_path = directory / f"{name}.lock"
        self.last_path = directory / f"{name}.last"
        self.wait_max_s, self.poll_s = wait_max_s, poll_s
        self._clock, self._sleep = clock, sleep

    def _wait_for_interval(self) -> float:
        try:
            last = float(self.last_path.read_text(encoding="ascii"))
        except FileNotFoundError:
            return 0.0
        except (OSError, UnicodeError, ValueError):
            return self.interval_s
        now = self._clock()
        if not last <= now:  # also true for NaN
            return self.interval_s
        return max(0.0, last + self.interval_s - now)

    def _record_end(self) -> None:
        temporary = self.last_path.with_suffix(".tmp")
        temporary.write_text(repr(self._clock()), encoding="ascii")
        os.replace(temporary, self.last_path)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Waits for the lock and the interval, then holds the lock while the request runs."""
        self.directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            polls = 0
            while not _try_lock(fd):
                if polls * self.poll_s >= self.wait_max_s:
                    raise FetchError(
                        f"source occupée par une autre requête depuis {self.wait_max_s:g} s : "
                        "réessayer plus tard"
                    )
                await self._sleep(self.poll_s)
                polls += 1
            try:
                pause = self._wait_for_interval()
                if pause > 0:
                    await self._sleep(pause)
                try:
                    yield
                finally:
                    self._record_end()
            finally:
                _unlock(fd)
        finally:
            os.close(fd)
