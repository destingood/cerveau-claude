"""Optional Langfuse tracing: local server only, keys tested for presence, never a failure."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from core.observability import LangfuseTracer, NoTracer, build_tracer, tracing_status
from core.observability import tracing as tracing_module

FAKE = "test-not-a-key"
KEYS = {"LANGFUSE_PUBLIC_KEY": FAKE, "LANGFUSE_SECRET_KEY": FAKE}


@pytest.mark.parametrize(
    ("env", "enabled", "reason"),
    [
        ({}, False, "aucune clé dans l'environnement"),
        (
            {
                **KEYS,
                "LANGFUSE_BASE_URL": "http://localhost:3000",
                "LANGFUSE_TRACING_ENABLED": "False",
            },
            False,
            "LANGFUSE_TRACING_ENABLED=false",
        ),
        ({"LANGFUSE_PUBLIC_KEY": FAKE}, False, "LANGFUSE_SECRET_KEY absente(s)"),
        ({"LANGFUSE_BASE_URL": "http://localhost:3000"}, False, "LANGFUSE_PUBLIC_KEY, LANGFUSE_"),
        (KEYS, False, "le SDK enverrait les traces à Langfuse Cloud"),
        (
            {**KEYS, "LANGFUSE_BASE_URL": "https://cloud.langfuse.com"},
            False,
            "serveur non local refusé (cloud.langfuse.com, ADR-004)",
        ),
        (
            {**KEYS, "LANGFUSE_BASE_URL": "http://localhost.example.com:3000"},
            False,
            "serveur non local refusé",
        ),
        ({**KEYS, "LANGFUSE_BASE_URL": "ftp://localhost:3000"}, False, "serveur non local refusé"),
        ({**KEYS, "LANGFUSE_BASE_URL": "http://localhost:99999"}, False, "illisible"),
        (  # the SDK's precedence: LANGFUSE_BASE_URL wins over LANGFUSE_HOST
            {
                **KEYS,
                "LANGFUSE_BASE_URL": "https://eu.example.com",
                "LANGFUSE_HOST": "http://localhost:3000",
            },
            False,
            "serveur non local refusé (eu.example.com",
        ),
        (
            {**KEYS, "LANGFUSE_BASE_URL": "http://127.0.0.1:3000"},
            True,
            "actives (http://127.0.0.1:3000)",
        ),
        ({**KEYS, "LANGFUSE_HOST": "http://LOCALHOST:3000"}, True, "(http://localhost:3000)"),
        (
            {**KEYS, "LANGFUSE_BASE_URL": "", "LANGFUSE_HOST": "http://[::1]:3000"},
            True,
            "actives (http://[::1]:3000)",
        ),
    ],
)
def test_tracing_status(env: dict[str, str], enabled: bool, reason: str) -> None:
    status = tracing_status(env)
    assert status.enabled is enabled
    assert reason in status.reason
    assert FAKE not in status.reason  # R6: a key value is never shown


def test_disabled_tracing_changes_nothing() -> None:
    tracer, status = build_tracer({})
    assert isinstance(tracer, NoTracer)
    assert not status.enabled
    assert tracer.callbacks() == ()
    with tracer.request("req-1", version="v1", metadata={"config": "abc"}) as finish:
        finish({"status": "complete"})
    tracer.flush()


def test_an_unavailable_client_only_turns_tracing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(tags: object) -> None:
        raise RuntimeError(FAKE)

    monkeypatch.setattr(tracing_module, "LangfuseTracer", broken)
    tracer, status = build_tracer({**KEYS, "LANGFUSE_BASE_URL": "http://localhost:3000"})
    assert isinstance(tracer, NoTracer)
    assert status == tracing_module.TracingStatus(
        False, "traces Langfuse désactivées : client indisponible (RuntimeError)"
    )


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The real SDK 5.0.2, export turned off: nothing leaves the process."""
    from langfuse._client.resource_manager import LangfuseResourceManager

    for name, value in KEYS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://localhost:9")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    LangfuseResourceManager.reset()
    yield
    LangfuseResourceManager.reset()  # stops the SDK's background threads


@pytest.mark.usefixtures("sdk")
def test_langfuse_tracer_matches_the_installed_sdk(caplog: pytest.LogCaptureFixture) -> None:
    from langfuse.langchain import CallbackHandler

    tracer = LangfuseTracer(("cerveau", "test"))
    [handler] = tracer.callbacks()
    assert isinstance(handler, CallbackHandler)
    model = FakeListChatModel(responses=["Réponse."])
    with tracer.request("req-1", version="v1", metadata={"config": "abc"}) as finish:
        reply = asyncio.run(model.ainvoke("Question ?", config={"callbacks": [handler]}))
        finish({"status": "complete", "cost_eur": "0.0123", "tokens": 456})
    assert reply.content == "Réponse."
    # LangChain only logs a failing handler: no warning means the handler fits langchain-core
    errors = [r for r in caplog.records if r.name.startswith("langchain_core")]
    assert [r.getMessage() for r in errors if r.levelno >= logging.WARNING] == []
    tracer.flush()
