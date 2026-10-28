"""Optional Langfuse traces: one trace per request, on a local server only (ADR-004).

Tracing turns on only when LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and a local
LANGFUSE_BASE_URL (or LANGFUSE_HOST) are set. CERVEAU tests that the keys exist and never reads
them (R6); the SDK reads them itself. A server off this machine is refused, because traces carry
prompts and web pages (ADR-004 rejects Langfuse Cloud), and without a URL the SDK would default to
the cloud. Without tracing nothing changes and nothing fails.

A trace receives what the models receive (the pseudonymised question, the extracts), never the
re-identified answer. CERVEAU's deterministic costs go into the trace metadata. Langfuse's own
price table is not used for any decision (R1).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager, suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlsplit

if TYPE_CHECKING:  # the CLI imports this module for every command; LangChain loads with `ask`
    from langchain_core.callbacks import BaseCallbackHandler

KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
URL_VARS = ("LANGFUSE_BASE_URL", "LANGFUSE_HOST")  # the SDK's order of precedence
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
TRACE_NAME = "cerveau.ask"

Metadata = Mapping[str, str | int]
Finish = Callable[[Metadata], None]


@dataclass(frozen=True)
class TracingStatus:
    enabled: bool
    reason: str


def tracing_status(env: Mapping[str, str]) -> TracingStatus:
    """Whether traces may be sent: presence tests on the keys, the local URL checked."""
    if env.get("LANGFUSE_TRACING_ENABLED", "true").lower() == "false":
        return TracingStatus(False, "traces Langfuse coupées (LANGFUSE_TRACING_ENABLED=false)")
    missing = [name for name in KEYS if name not in env]
    url = next((env[name] for name in URL_VARS if env.get(name)), None)
    if len(missing) == len(KEYS) and url is None:
        return TracingStatus(False, "traces Langfuse désactivées : aucune clé dans l'environnement")
    if missing:
        absent = ", ".join(missing)
        return TracingStatus(False, f"traces Langfuse désactivées : {absent} absente(s)")
    if url is None:
        return TracingStatus(
            False,
            "traces Langfuse désactivées : LANGFUSE_BASE_URL absente "
            "(le SDK enverrait les traces à Langfuse Cloud, refusé par ADR-004)",
        )
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        return TracingStatus(False, "traces Langfuse désactivées : LANGFUSE_BASE_URL illisible")
    if parts.scheme not in ("http", "https") or host not in LOCAL_HOSTS:
        return TracingStatus(
            False, f"traces Langfuse désactivées : serveur non local refusé ({host}, ADR-004)"
        )
    shown = f"[{host}]" if ":" in host else host  # IPv6 keeps its brackets
    where = f"{parts.scheme}://{shown}" + (f":{port}" if port else "")
    return TracingStatus(True, f"traces Langfuse actives ({where})")


class Tracer(Protocol):
    def callbacks(self) -> tuple[BaseCallbackHandler, ...]: ...

    def request(
        self, request_id: str, *, version: str, metadata: Metadata
    ) -> AbstractContextManager[Finish]: ...

    def flush(self) -> None: ...


class NoTracer:
    """Tracing off: no callback, nothing sent."""

    def callbacks(self) -> tuple[BaseCallbackHandler, ...]:
        return ()

    @contextmanager
    def request(self, request_id: str, *, version: str, metadata: Metadata) -> Iterator[Finish]:
        yield lambda _: None

    def flush(self) -> None:
        return None


class LangfuseTracer:
    """One root span per request; the LangChain handler nests every model call under it."""

    def __init__(self, tags: Sequence[str] = ("cerveau",)) -> None:
        from langfuse import get_client, propagate_attributes  # loaded only when tracing is on
        from langfuse.langchain import CallbackHandler

        self._client = get_client()  # reads the keys and the URL from the environment itself
        self._handler = CallbackHandler()
        self._propagate = propagate_attributes
        self.tags = list(tags)

    def callbacks(self) -> tuple[BaseCallbackHandler, ...]:
        return (self._handler,)

    @contextmanager
    def request(self, request_id: str, *, version: str, metadata: Metadata) -> Iterator[Finish]:
        root: Any
        with (
            self._client.start_as_current_observation(
                name=TRACE_NAME, as_type="chain", version=version, metadata=dict(metadata)
            ) as root,
            self._propagate(
                session_id=request_id, tags=self.tags, version=version, trace_name=TRACE_NAME
            ),
        ):
            yield lambda final: root.update(metadata=dict(final))

    def flush(self) -> None:
        with suppress(Exception):  # the answer is already given; a lost trace is not an error
            self._client.flush()


def build_tracer(
    env: Mapping[str, str], *, tags: Sequence[str] = ("cerveau",)
) -> tuple[Tracer, TracingStatus]:
    """The tracer the environment allows; a Langfuse failure here only turns tracing off."""
    status = tracing_status(env)
    if not status.enabled:
        return NoTracer(), status
    try:
        return LangfuseTracer(tags), status
    except Exception as exc:  # tracing is optional: never a reason to fail a request
        return NoTracer(), TracingStatus(
            False, f"traces Langfuse désactivées : client indisponible ({type(exc).__name__})"
        )
