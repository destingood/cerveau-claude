"""A program run without a shell, under a time limit, its output read up to a byte limit.

Shared by the git runner (ADR-047) and the check containers (ADR-048). stderr is drained so the
program never blocks on it, and only its beginning is kept; stdin, when given, is written from
its own thread so that a program that stops reading cannot block the caller.
"""

from __future__ import annotations

import contextlib
import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import IO, cast

MAX_STDERR_BYTES = 4_000
_CHUNK = 65_536


@dataclass(frozen=True)
class Bounded:
    returncode: int
    stdout: bytes
    stderr: str
    # The output went past the byte limit: the program was stopped there.
    truncated: bool
    # The time limit expired: the program was stopped.
    timed_out: bool


def _read_bounded(stream: IO[bytes], limit: int) -> tuple[bytes, bool]:
    data = bytearray()
    while chunk := stream.read1(_CHUNK):  # type: ignore[attr-defined]
        data.extend(chunk)
        if len(data) > limit:
            return bytes(data[:limit]), True
    return bytes(data), False


def _drain(stream: IO[bytes], sink: bytearray) -> None:
    """Read stderr to its end so the program never blocks on it; keep only its beginning."""
    while chunk := stream.read1(_CHUNK):  # type: ignore[attr-defined]
        sink.extend(chunk[: max(0, MAX_STDERR_BYTES - len(sink))])


def _feed(stream: IO[bytes], data: bytes) -> None:
    # A program that exits or is stopped before reading everything closes the pipe.
    with contextlib.suppress(OSError):
        stream.write(data)
    with contextlib.suppress(OSError):
        stream.close()


def run_bounded(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    timeout_s: float,
    max_bytes: int,
    stdin: bytes | None = None,
) -> Bounded:
    """Run ``command``; raises ``OSError`` when it cannot start."""
    process = subprocess.Popen(  # noqa: S603 - fixed arguments, no shell
        list(command),
        stdin=subprocess.DEVNULL if stdin is None else subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(env),
    )
    stdout_pipe = cast(IO[bytes], process.stdout)
    timed_out = threading.Event()

    def stop() -> None:
        timed_out.set()
        process.kill()

    timer = threading.Timer(timeout_s, stop)
    errors = bytearray()
    threads = [threading.Thread(target=_drain, args=(process.stderr, errors), daemon=True)]
    if stdin is not None:
        threads.append(threading.Thread(target=_feed, args=(process.stdin, stdin), daemon=True))
    timer.start()
    for thread in threads:
        thread.start()
    try:
        stdout, truncated = _read_bounded(stdout_pipe, max_bytes)
        if truncated:
            process.kill()
        process.wait()
    finally:
        timer.cancel()
        for thread in threads:
            thread.join(timeout=1.0)
        stdout_pipe.close()
    return Bounded(
        process.returncode,
        stdout,
        errors.decode("utf-8", errors="replace"),
        truncated,
        timed_out.is_set(),
    )
