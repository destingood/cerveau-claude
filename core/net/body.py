"""Bounded reading of a streamed HTTP body, for every reader plugin (ADR-006, ADR-043).

The body is read as a stream and stopped at the limit: compressed and decompressed sizes are
both counted, so a small gzip bomb cannot grow past it. Only ``identity`` and ``gzip`` are
accepted; any other encoding is refused.
"""

from __future__ import annotations

import zlib

import httpx

from core.net.guard import FetchError, shown


async def read_body(response: httpx.Response, limit: int, *, cut: bool) -> bytes:
    """Body of at most ``limit`` bytes; beyond it, ``cut`` truncates, otherwise it refuses."""
    encoding = response.headers.get("content-encoding", "identity").strip().lower() or "identity"
    if encoding not in ("identity", "gzip"):
        raise FetchError(f"encodage « {shown(encoding)} » non pris en charge")
    too_big = FetchError(f"page trop volumineuse (plus de {limit / 1_000_000:g} Mo)")
    declared = response.headers.get("content-length", "")
    if not cut and declared.isdigit() and int(declared) > limit:
        raise too_big
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
    body = bytearray()
    received = 0
    async for chunk in response.aiter_raw():
        received += len(chunk)
        try:
            # max_length is never 0 (0 would mean "no limit"): len(body) <= limit here.
            data = inflater.decompress(chunk, limit + 1 - len(body)) if inflater else chunk
        except zlib.error:
            raise FetchError("contenu compressé illisible") from None
        body += data
        over = received > limit or len(body) > limit or bool(inflater and inflater.unconsumed_tail)
        if over:
            if not cut:
                raise too_big
            return bytes(body[:limit])
    return bytes(body)
