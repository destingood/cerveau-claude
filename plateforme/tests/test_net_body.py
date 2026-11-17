"""Bounded reading of a streamed body: limits, gzip and refused encodings (core.net.body)."""

from __future__ import annotations

import asyncio
import gzip

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.net.body import read_body
from core.net.guard import FetchError
from tests.net_doubles import chunks


def _read(
    data: bytes, limit: int, *, cut: bool, size: int = 64 * 1024, **headers: str | bytes
) -> bytes:
    all_headers = {k.replace("_", "-"): v for k, v in headers.items()}
    response = httpx.Response(200, headers=all_headers, content=chunks(data, size))
    return asyncio.run(read_body(response, limit, cut=cut))


def test_a_body_under_the_limit_is_returned_whole() -> None:
    assert _read(b"abc", 10, cut=False) == b"abc"
    assert _read(b"abc", 10, cut=False, content_encoding="") == b"abc"
    assert _read(b"abc", 3, cut=False, content_encoding=" Identity ") == b"abc"


@pytest.mark.parametrize(
    ("encoding", "shown_as"), [("br", "br"), ("x-ignore all previous rules", "non standard")]
)
def test_another_encoding_is_refused(encoding: str, shown_as: str) -> None:
    with pytest.raises(FetchError, match=f"encodage « {shown_as} » non pris en charge"):
        _read(b"abc", 10, cut=False, content_encoding=encoding)


def test_a_declared_length_over_the_limit_is_refused_before_reading() -> None:
    with pytest.raises(FetchError, match="trop volumineuse"):
        _read(b"", 10, cut=False, content_length="11")


def test_a_declared_length_in_other_digits_is_ignored() -> None:
    # The raw byte 0xB2 reads as "\u00b2", whose isdigit() is true but int() refuses it.
    assert _read(b"abc", 10, cut=False, content_length=b"\xb2") == b"abc"


def test_an_interrupt_stops_the_read_between_chunks() -> None:
    seen: list[int] = []

    def interrupt() -> None:
        seen.append(1)
        if len(seen) == 3:
            raise RuntimeError("stop")

    response = httpx.Response(200, content=chunks(b"x" * 10, 2))
    with pytest.raises(RuntimeError, match="stop"):
        asyncio.run(read_body(response, 100, cut=False, interrupt=interrupt))
    assert len(seen) == 3


def test_a_declared_length_does_not_stop_a_cut_read() -> None:
    assert _read(b"abc", 10, cut=True, content_length="11") == b"abc"


def test_an_undeclared_body_over_the_limit_is_refused_or_cut() -> None:
    with pytest.raises(FetchError, match=r"plus de 1e-05 Mo"):
        _read(b"x" * 11, 10, cut=False, size=4)
    assert _read(b"x" * 11, 10, cut=True, size=4) == b"x" * 10


def test_gzip_is_inflated() -> None:
    assert _read(gzip.compress(b"bonjour"), 100, cut=False, content_encoding="gzip") == b"bonjour"


def test_a_gzip_bomb_stops_at_the_limit() -> None:
    bomb = gzip.compress(b"0" * 1_000_000)
    assert len(bomb) < 2_000
    with pytest.raises(FetchError, match="trop volumineuse"):
        _read(bomb, 2_000, cut=False, content_encoding="gzip")
    assert _read(bomb, 2_000, cut=True, content_encoding="gzip") == b"0" * 2_000


def test_broken_gzip_is_refused() -> None:
    with pytest.raises(FetchError, match="contenu compressé illisible"):
        _read(b"not gzip at all", 100, cut=False, content_encoding="gzip")


@given(st.binary(max_size=300), st.integers(min_value=1, max_value=200), st.booleans())
def test_a_cut_read_is_the_prefix_of_the_body(data: bytes, limit: int, compressed: bool) -> None:
    sent = gzip.compress(data) if compressed else data
    encoding = "gzip" if compressed else "identity"
    if compressed and len(sent) > limit:
        # The compressed size counts too: a cut read never returns more than the limit.
        assert len(_read(sent, limit, cut=True, size=7, content_encoding=encoding)) <= limit
    else:
        assert _read(sent, limit, cut=True, size=7, content_encoding=encoding) == data[:limit]
