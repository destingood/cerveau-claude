"""Time limit of an MCP tool call, shared by the adapter and the plugin servers (ADR-052).

A plugin manifest declares how long one of its tool calls may last (``runtime.tool_timeout_s``,
30 s by default, 900 s at most). The adapter cuts a call at that limit or at the end of the
request's budget, whichever comes first, and sends the limit it applies with the call, in the
request's ``_meta``. A server whose work runs outside its own process (a container) reads it, so
that this work ends, and is stopped if late, before the adapter cuts the call.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from mcp.types import RequestParamsMeta

DEFAULT_TOOL_TIMEOUT_S = 30.0
MAX_TOOL_TIMEOUT_S = 900.0
# A ``_meta`` key of the MCP specification's form: a prefix label, a slash, a name.
TIME_LIMIT_META_KEY = "cerveau/time_limit_s"


def time_limit_meta(seconds: float) -> RequestParamsMeta:
    """The ``_meta`` the adapter sends with a call that it cuts after ``seconds``."""
    return {TIME_LIMIT_META_KEY: round(max(seconds, 0.0), 3)}


def time_limit(meta: Mapping[str, Any] | None) -> float | None:
    """The limit a server received with a call; ``None`` when absent or not a valid number.

    A value above the maximum a manifest may declare is brought back to it.
    """
    value = (meta or {}).get(TIME_LIMIT_META_KEY)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return min(max(float(value), 0.0), MAX_TOOL_TIMEOUT_S)
