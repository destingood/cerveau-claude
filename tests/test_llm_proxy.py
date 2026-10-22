"""Anthropic API proxy of the code agent (ADR-053): checks, key, prices and ceilings, offline."""

from __future__ import annotations

import ast
import http.client
import io
import itertools
import json
import ssl
import sys
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.code import llm_proxy
from core.code.llm_proxy import (
    KEY_ENV,
    LISTEN_HOST,
    LISTEN_PORT,
    MAX_DEPTH,
    MAX_EVENT_BYTES,
    UPSTREAM_HOST,
    UPSTREAM_PORT,
    HttpsUpstream,
    JsonMeter,
    Message,
    Proxy,
    ProxyServer,
    Refusal,
    SettingsError,
    StreamMeter,
    UpstreamError,
    UpstreamReply,
    Usage,
    body_size,
    cost_usd,
    handler_for,
    header_map,
    inspect,
    load_settings,
    main,
    price_tier,
    read_usage,
    reply_headers,
    upstream_headers,
)
from core.config import load_config
from core.config.loader import ModelPricing
from core.models import CostCalculator, TokenUsage

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"
PRICING = load_config(REPO_CONFIG).pricing
CALCULATOR = CostCalculator(PRICING)
PRICES = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")
SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"
KEY = "fake-proxy-test-key"  # never a real key: the tests run offline


def model_settings(pricing: ModelPricing) -> dict[str, Any]:
    tiers = []
    for tier in pricing.tiers:
        item: dict[str, Any] = {name: str(getattr(tier, name)) for name in PRICES}
        if tier.max_prompt_tokens is not None:
            item["max_prompt_tokens"] = tier.max_prompt_tokens
        tiers.append(item)
    return {"tiers": tiers}


def settings_payload(**changes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": 1,
        "models": {name: model_settings(p) for name, p in PRICING.anthropic.models.items()},
        "max_usd": "2",
        "max_requests": 100,
        "max_body_bytes": 8 << 20,
        "upstream_timeout_s": 600,
    }
    payload.update(changes)
    return payload


SETTINGS = load_settings(json.dumps(settings_payload()))


def sse(*events: dict[str, Any]) -> bytes:
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)


START_USAGE = {
    "input_tokens": 1000,
    "cache_read_input_tokens": 2000,
    "cache_creation_input_tokens": 300,
    "cache_creation": {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 200},
    "output_tokens": 1,
    "service_tier": "standard",
}
START = {"type": "message_start", "message": {"id": "msg_1", "usage": START_USAGE}}
TEXT = {
    "type": "content_block_delta",
    "index": 0,
    "delta": {"type": "text_delta", "text": 'le texte cite "message_start"'},
}
DELTA = {
    "type": "message_delta",
    "delta": {"stop_reason": "end_turn"},
    "usage": {**START_USAGE, "output_tokens": 500},
}
STREAM = sse(START, {"type": "ping"}, TEXT, DELTA, {"type": "message_stop"})
STREAM_USAGE = Usage(
    input=1000, cache_read=2000, cache_write_5m=100, cache_write_1h=200, output=500
)


def expected_usd(model: str, usage: Usage) -> Decimal:
    return CALCULATOR.llm_usd(model, TokenUsage(**usage.to_payload()))[0]


# --- the image's dependencies ------------------------------------------------------------------


def test_the_proxy_imports_the_standard_library_only() -> None:
    tree = ast.parse(Path(llm_proxy.__file__).read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module is not None
            modules.add(node.module.split(".")[0])
    assert modules - {"__future__"} <= sys.stdlib_module_names


def test_the_image_holds_the_proxy_alone_and_runs_it_isolated_without_root() -> None:
    dockerfile = REPO_CONFIG.parent / "infra" / "agent" / "llm-proxy.Dockerfile"
    lines = [
        line
        for line in dockerfile.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    instructions = [line.split()[0] for line in lines]
    assert instructions == ["FROM", "COPY", "USER", "EXPOSE", "ENTRYPOINT"]
    assert lines[0] == "FROM python:3.12-slim@sha256:A_DEFINIR"  # pinned by Lucas, R7
    assert lines[1].endswith(" llm_proxy.py /app/llm_proxy.py")
    assert lines[2] == "USER 65534:65534"
    assert lines[3] == f"EXPOSE {LISTEN_PORT}"
    assert json.loads(lines[4].removeprefix("ENTRYPOINT ")) == [
        "python",
        "-I",
        "-B",
        "/app/llm_proxy.py",
    ]


# --- settings ------------------------------------------------------------------------------------


def test_the_settings_carry_the_prices_and_the_ceilings() -> None:
    assert SETTINGS.max_usd == Decimal("2")
    assert SETTINGS.max_requests == 100
    assert SETTINGS.upstream_timeout_s == 600.0
    haiku = SETTINGS.models[HAIKU]
    assert [t.max_prompt_tokens for t in haiku] == [100_000, None]
    assert haiku[0].input == Decimal("0.10")


def bad_tiers(*tiers: Any) -> dict[str, Any]:
    return settings_payload(models={SONNET: {"tiers": list(tiers)}})


PRICE = {name: "1" for name in PRICES}


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("[", "JSON illisible"),
        ("[]", "réglages : table attendue"),
        (json.dumps({"schema": 1}), "clés attendues"),
        (json.dumps(settings_payload(schema=2)), "schema"),
        (json.dumps(settings_payload(models=[])), "models : table attendue"),
        (json.dumps(settings_payload(models={})), "au moins un modèle"),
        (json.dumps(settings_payload(models={SONNET: {}})), "clés attendues"),
        (json.dumps(bad_tiers()), "liste non vide"),
        (json.dumps(settings_payload(models={SONNET: {"tiers": {}}})), "liste non vide"),
        (json.dumps(bad_tiers("x")), "table attendue"),
        (json.dumps(bad_tiers({**PRICE, "max_prompt_tokens": 10})), "clés attendues"),
        (json.dumps(bad_tiers(PRICE, PRICE)), "clés attendues"),
        (json.dumps(bad_tiers({**PRICE, "max_prompt_tokens": True}, PRICE)), "entier"),
        (json.dumps(bad_tiers({**PRICE, "max_prompt_tokens": 0}, PRICE)), "entier"),
        (
            json.dumps(
                bad_tiers(
                    {**PRICE, "max_prompt_tokens": 10}, {**PRICE, "max_prompt_tokens": 10}, PRICE
                )
            ),
            "bornes croissantes",
        ),
        (json.dumps(bad_tiers({**PRICE, "input": 1})), "nombre décimal"),
        (json.dumps(bad_tiers({**PRICE, "input": "un"})), "nombre décimal"),
        (json.dumps(bad_tiers({**PRICE, "input": "NaN"})), "nombre décimal"),
        (json.dumps(bad_tiers({**PRICE, "input": "-1"})), "nombre décimal"),
        (json.dumps(settings_payload(max_usd="0")), "max_usd"),
        (json.dumps(settings_payload(max_requests=True)), "max_requests"),
        (json.dumps(settings_payload(max_body_bytes=0)), "max_body_bytes"),
        (json.dumps(settings_payload(upstream_timeout_s=True)), "upstream_timeout_s"),
        (json.dumps(settings_payload(upstream_timeout_s="600")), "upstream_timeout_s"),
        (json.dumps(settings_payload(upstream_timeout_s=0)), "upstream_timeout_s"),
        (json.dumps(settings_payload(upstream_timeout_s=3600)), "upstream_timeout_s"),
    ],
)
def test_a_wrong_setting_stops_the_proxy(payload: str, message: str) -> None:
    with pytest.raises(SettingsError, match=message):
        load_settings(payload)


def test_a_free_price_is_allowed() -> None:
    settings = load_settings(json.dumps(bad_tiers({**PRICE, "cache_read": "0"})))
    assert settings.models[SONNET][0].cache_read == 0


# --- usage and prices ----------------------------------------------------------------------------


def test_the_usage_is_split_the_way_it_is_billed() -> None:
    assert read_usage(START_USAGE | {"output_tokens": 500}) == STREAM_USAGE


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"cache_creation_input_tokens": 30}, Usage(cache_write_1h=30)),
        (
            {
                "cache_creation_input_tokens": 50,
                "cache_creation": {"ephemeral_5m_input_tokens": 10},
            },
            Usage(cache_write_5m=10, cache_write_1h=40),
        ),
        (
            {"cache_creation": {"ephemeral_5m_input_tokens": 10, "ephemeral_1h_input_tokens": 5}},
            Usage(cache_write_5m=10, cache_write_1h=5),
        ),
        ({"output_tokens": 7, "iterations": []}, Usage(output=7)),
        ({"server_tool_use": {"web_search_requests": 0}}, Usage()),
        ({"service_tier": "standard", "speed": None}, Usage()),
    ],
)
def test_cache_writes_without_a_split_are_priced_at_the_higher_rate(
    raw: dict[str, Any], expected: Usage
) -> None:
    assert read_usage(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {"speed": "fast"},
        {"inference_geo": "us"},
        {"service_tier": "priority"},
        {"iterations": [{"type": "compaction"}]},
        {"server_tool_use": {"web_search_requests": 1}},
        {"server_tool_use": {"web_fetch_requests": "1"}},
        {"server_tool_use": []},
        {"cache_creation": 3},
        {"input_tokens": -1},
        {"input_tokens": True},
        {"output_tokens": 1.5},
    ],
)
def test_a_usage_this_proxy_cannot_price_is_unknown(raw: object) -> None:
    assert read_usage(raw) is None


@given(
    model=st.sampled_from(sorted(PRICING.anthropic.models)),
    tokens=st.tuples(*(st.integers(0, 400_000) for _ in PRICES)),
)
def test_the_proxy_prices_as_the_cost_calculator(model: str, tokens: tuple[int, ...]) -> None:
    usage = Usage(**dict(zip(PRICES, tokens, strict=True)))
    assert cost_usd(SETTINGS.models[model], usage) == expected_usd(model, usage)


def test_the_tier_follows_the_prompt_length() -> None:
    tiers = SETTINGS.models[HAIKU]
    assert price_tier(tiers, Usage(input=100_000)) is tiers[0]
    assert price_tier(tiers, Usage(input=99_000, cache_read=1_001)) is tiers[1]
    assert price_tier(SETTINGS.models[SONNET], Usage(input=10**9)) is SETTINGS.models[SONNET][0]


def test_usages_add_up() -> None:
    assert STREAM_USAGE + Usage(input=1, output=2) == Usage(
        input=1001, cache_read=2000, cache_write_5m=100, cache_write_1h=200, output=502
    )


# --- meters --------------------------------------------------------------------------------------


@given(st.lists(st.integers(1, len(STREAM) - 1), unique=True, max_size=12))
def test_a_stream_is_metered_whatever_its_chunks(cuts: list[int]) -> None:
    meter = StreamMeter()
    bounds = [0, *sorted(cuts), len(STREAM)]
    for start, end in itertools.pairwise(bounds):
        meter.feed(STREAM[start:end])
    assert meter.usage(max_tokens=4096) == STREAM_USAGE


def test_a_stream_cut_before_its_end_is_charged_its_max_tokens() -> None:
    meter = StreamMeter()
    meter.feed(sse(START, TEXT))
    assert meter.usage(max_tokens=4096) == Usage(
        input=1000, cache_read=2000, cache_write_5m=100, cache_write_1h=200, output=4096
    )


def test_a_cut_stream_without_an_output_count_is_charged_its_max_tokens() -> None:
    meter = StreamMeter()
    meter.feed(sse({"type": "message_start", "message": {"usage": {"output_tokens": None}}}))
    assert meter.usage(max_tokens=64) == Usage(output=64)


def test_the_larger_count_of_a_stream_is_kept() -> None:
    meter = StreamMeter()
    meter.feed(sse(START, {"type": "message_delta", "usage": {"output_tokens": 9}}))
    meter.feed(sse({"type": "message_delta", "usage": {"output_tokens": 3, "speed": None}}))
    usage = meter.usage(max_tokens=4096)
    assert usage is not None and usage.output == 9 and usage.input == 1000


@pytest.mark.parametrize(
    "chunk",
    [
        b"",
        sse({"type": "message_delta", "usage": {"output_tokens": 5}}),
        b'data: {"type": "message_start", oops}\n',
        sse({"type": "message_start", "message": "x"}),
        sse(START, {"type": "message_delta"}),
        sse({"type": "message_start", "message": {"usage": {"speed": "fast"}}}),
    ],
)
def test_a_stream_whose_usage_cannot_be_read_has_an_unknown_cost(chunk: bytes) -> None:
    meter = StreamMeter()
    meter.feed(chunk)
    assert meter.usage(max_tokens=10) is None


def test_lines_that_are_not_usage_are_ignored() -> None:
    meter = StreamMeter()
    meter.feed(b'event: message_start\ndata: ["message_start"]\n: commentaire\n')
    meter.feed(sse(START, DELTA))
    assert meter.usage(max_tokens=10) == STREAM_USAGE


def test_an_endless_line_breaks_the_meter() -> None:
    meter = StreamMeter()
    meter.feed(sse(START))
    meter.feed(b"x" * (MAX_EVENT_BYTES + 1))
    assert meter.usage(max_tokens=10) is None


def test_a_json_reply_is_metered() -> None:
    meter = JsonMeter()
    body = json.dumps({"id": "msg_1", "usage": START_USAGE | {"output_tokens": 500}}).encode()
    meter.feed(body[:10])
    meter.feed(body[10:])
    assert meter.usage(max_tokens=10) == STREAM_USAGE


@pytest.mark.parametrize("body", [b"{", b"[]", b'{"id": "msg_1"}'])
def test_a_json_reply_without_a_readable_usage_has_an_unknown_cost(body: bytes) -> None:
    meter = JsonMeter()
    meter.feed(body)
    assert meter.usage(max_tokens=10) is None


def test_a_json_reply_too_large_has_an_unknown_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_proxy, "MAX_JSON_BYTES", 8)
    meter = JsonMeter()
    meter.feed(b'{"usage":')
    meter.feed(b"{}}")
    assert meter.usage(max_tokens=10) is None


# --- requests ------------------------------------------------------------------------------------


def body(**changes: Any) -> bytes:
    payload: dict[str, Any] = {
        "model": SONNET,
        "max_tokens": 1024,
        "stream": True,
        "messages": [{"role": "user", "content": "Bonjour"}],
    }
    payload.update(changes)
    return json.dumps(payload).encode()


def image(source_type: str, **source: Any) -> dict[str, Any]:
    return {"type": "image", "source": {"type": source_type, **source}}


def user(*blocks: Any) -> list[dict[str, Any]]:
    return [{"role": "user", "content": list(blocks)}]


def test_a_request_of_the_agent_is_let_through() -> None:
    allowed = body(
        system=[{"type": "text", "text": "consignes", "cache_control": {"type": "ephemeral"}}],
        tools=[{"name": "Read", "input_schema": {"type": "object"}}, {"type": "custom"}],
        thinking={"type": "enabled", "budget_tokens": 512},
        inference_geo="global",
        speed="standard",
        service_tier="auto",
        messages=user(
            {"type": "text", "text": "lis"},
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"url": "https://x"}},
            {
                "type": "tool_result",
                "tool_use_id": "t1",
                "content": [
                    {"type": "text", "text": "ok"},
                    image("base64", media_type="image/png", data="AA=="),
                    {
                        "type": "document",
                        "source": {"type": "content", "content": [{"type": "text", "text": "a"}]},
                    },
                    {"type": "document", "source": {"type": "content", "content": "texte"}},
                ],
            },
            {"type": "document", "source": {"type": "text", "data": "b"}},
        ),
    )
    assert inspect(allowed, SETTINGS.models) == Message(model=SONNET, max_tokens=1024)


def nested(depth: int) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "text", "text": "fond"}
    for _ in range(depth):
        block = {"type": "tool_result", "tool_use_id": "t", "content": [block]}
    return block


@pytest.mark.parametrize(
    ("data", "status", "code", "message"),
    [
        (b"{", 400, "corps", "illisible"),
        (b"[]", 400, "corps", "objet attendu"),
        (body(mcp_servers=[]), 403, "champ", "mcp_servers"),
        (body(container="c"), 403, "champ", "container"),
        (body(**{"X-Odd": 1}), 403, "champ", "proxy : ?"),
        (body(context_management={}), 403, "champ", "context_management"),
        (body(speed="fast"), 403, "champ", "speed"),
        (body(inference_geo="us"), 403, "champ", "inference_geo"),
        (body(service_tier="priority"), 403, "champ", "service_tier"),
        (body(model="claude-mythos"), 403, "modele", SONNET),
        (body(model=None), 403, "modele", "permis"),
        (body(max_tokens=0), 400, "corps", "max_tokens"),
        (body(max_tokens=True), 400, "corps", "max_tokens"),
        (body(tools={}), 400, "corps", "tools"),
        (body(tools=[{"type": "web_search_20250305", "name": "web_search"}]), 403, "outil", ""),
        (body(tools=[{"type": "web_fetch_20250910"}]), 403, "outil", ""),
        (body(tools=["Read"]), 403, "outil", ""),
        (body(messages={}), 400, "corps", "messages"),
        (body(messages=["Bonjour"]), 400, "corps", "messages"),
        (body(system={"type": "text"}), 400, "corps", "contenu"),
        (body(system=[{"type": "text"}, "x"]), 403, "bloc", ""),
        (body(messages=user({"type": "container_upload", "file_id": "f"})), 403, "bloc", ""),
        (body(messages=user({"type": "search_result"})), 403, "bloc", ""),
        (body(messages=user(image("url", url="https://x/y.png"))), 403, "source", "URL"),
        (body(messages=user(image("file", file_id="file_1"))), 403, "source", ""),
        (body(messages=user({"type": "document"})), 403, "source", ""),
        (
            body(
                messages=user(
                    {"type": "tool_result", "tool_use_id": "t", "content": [image("url")]}
                )
            ),
            403,
            "source",
            "",
        ),
        (
            body(
                messages=user(
                    {
                        "type": "document",
                        "source": {"type": "content", "content": [image("url", url="https://x")]},
                    }
                )
            ),
            403,
            "source",
            "",
        ),
        (body(messages=user(nested(MAX_DEPTH + 2))), 400, "corps", "contenu"),
    ],
)
def test_a_request_outside_the_list_is_refused(
    data: bytes, status: int, code: str, message: str
) -> None:
    refusal = inspect(data, SETTINGS.models)
    assert isinstance(refusal, Refusal)
    assert (refusal.status, refusal.code) == (status, code)
    assert message in refusal.message


def test_a_deep_but_bounded_content_is_let_through() -> None:
    assert isinstance(inspect(body(messages=user(nested(MAX_DEPTH))), SETTINGS.models), Message)


def test_a_json_bomb_is_refused() -> None:
    refusal = inspect(b"[" * 100_000 + b"]" * 100_000, SETTINGS.models)
    assert isinstance(refusal, Refusal) and refusal.code == "corps"


# --- headers -------------------------------------------------------------------------------------

AGENT_HEADERS = {
    "content-type": "application/json",
    "anthropic-version": "2023-06-01",
    "x-api-key": "agent-placeholder",
    "authorization": "Bearer agent-placeholder",
    "cookie": "a=b",
    "accept-encoding": "gzip",
}


def test_the_real_key_replaces_the_agents() -> None:
    sent = upstream_headers(
        AGENT_HEADERS
        | {
            "anthropic-beta": "a-2025-01-01, b.c-1",
            "content-type": "application/json; charset=utf-8",
        },
        KEY,
    )
    assert sent == {
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "a-2025-01-01, b.c-1",
        "x-api-key": KEY,
    }


def test_no_version_header_is_needed() -> None:
    assert upstream_headers({"content-type": "application/json"}, KEY) == {
        "content-type": "application/json",
        "x-api-key": KEY,
    }


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({}, 415),
        ({"content-type": "text/plain"}, 415),
        (AGENT_HEADERS | {"anthropic-version": "2023-06-01\r\nx-api-key: y"}, 400),
        (AGENT_HEADERS | {"anthropic-beta": "Beta"}, 400),
        (AGENT_HEADERS | {"anthropic-beta": "a\r\nx-api-key: y"}, 400),
    ],
)
def test_a_wrong_header_is_refused(headers: dict[str, str], status: int) -> None:
    refusal = upstream_headers(headers, KEY)
    assert isinstance(refusal, Refusal) and refusal.status == status


def test_repeated_headers_are_joined() -> None:
    assert header_map([("Anthropic-Beta", "a"), ("anthropic-beta", "b"), ("Host", "p")]) == {
        "anthropic-beta": "a, b",
        "host": "p",
    }


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({}, 0),
        ({"content-length": "12"}, 12),
        ({"content-length": "100"}, 100),
        ({"content-length": "101"}, 413),
        ({"content-length": "-1"}, 400),
        ({"content-length": "1, 1"}, 400),
        ({"transfer-encoding": "chunked"}, 411),
    ],
)
def test_the_body_size_comes_from_content_length_only(
    headers: dict[str, str], expected: int
) -> None:
    size = body_size(headers, limit=100)
    assert (size.status if isinstance(size, Refusal) else size) == expected


def test_only_harmless_reply_headers_reach_the_agent() -> None:
    kept = reply_headers(
        [
            ("Content-Type", "text/event-stream"),
            ("request-id", "r"),
            ("Set-Cookie", "c"),
            ("anthropic-organization-id", "o"),
            ("Retry-After", "3"),
            ("x-should-retry", "true"),
        ]
    )
    assert kept == [
        ("Content-Type", "text/event-stream"),
        ("request-id", "r"),
        ("Retry-After", "3"),
        ("x-should-retry", "true"),
    ]


# --- upstream ------------------------------------------------------------------------------------


class FakeResponse:
    status = 200

    def __init__(self, parts: list[bytes]) -> None:
        self._parts = list(parts)

    def getheaders(self) -> list[tuple[str, str]]:
        return [("content-type", "application/json")]

    def read1(self, size: int) -> bytes:
        assert size == llm_proxy.CHUNK_BYTES
        return self._parts.pop(0) if self._parts else b""


def connection_class(fail_at: str | None = None) -> tuple[type, list[Any]]:
    made: list[Any] = []

    class Connection:
        def __init__(self, host: str, port: int, *, timeout: float, context: Any) -> None:
            self.args = (host, port, timeout, context)
            self.closed = False
            made.append(self)

        def connect(self) -> None:
            if fail_at == "connect":
                raise ConnectionRefusedError

        def request(self, method: str, url: str, *, body: bytes, headers: dict[str, str]) -> None:
            self.request_args = (method, url, body, headers)
            if fail_at == "request":
                raise TimeoutError

        def getresponse(self) -> FakeResponse:
            if fail_at == "response":
                raise http.client.BadStatusLine("x")
            return FakeResponse([b"ab", b"c"])

        def close(self) -> None:
            self.closed = True

    return Connection, made


def test_the_upstream_is_the_api_over_tls() -> None:
    connection, made = connection_class()
    context = ssl.create_default_context()
    reply = HttpsUpstream(30.0, connect=connection, context=context).send(
        "/v1/messages?beta=true", {"x-api-key": KEY}, b"{}"
    )
    assert made[0].args == (UPSTREAM_HOST, UPSTREAM_PORT, 30.0, context)
    assert made[0].request_args == ("POST", "/v1/messages?beta=true", b"{}", {"x-api-key": KEY})
    assert (reply.status, list(reply.chunks)) == (200, [b"ab", b"c"])
    reply.close()
    assert made[0].closed


def test_the_upstream_checks_certificates_by_default() -> None:
    upstream = HttpsUpstream(1.0)
    assert upstream._context.verify_mode == ssl.CERT_REQUIRED
    assert upstream._context.check_hostname


@pytest.mark.parametrize(
    ("fail_at", "sent"), [("connect", False), ("request", True), ("response", True)]
)
def test_an_unreachable_api_tells_whether_it_may_have_read_the_request(
    fail_at: str, sent: bool
) -> None:
    connection, made = connection_class(fail_at)
    with pytest.raises(UpstreamError) as error:
        HttpsUpstream(1.0, connect=connection).send("/v1/messages", {}, b"{}")
    assert error.value.sent is sent
    assert made[0].closed


# --- the proxy -----------------------------------------------------------------------------------


class Closing:
    def __init__(self) -> None:
        self.closed = 0

    def __call__(self) -> None:
        self.closed += 1


def upstream_reply(
    status: int = 200,
    chunks: tuple[bytes, ...] = (STREAM,),
    content_type: str = "text/event-stream; charset=utf-8",
    error: Exception | None = None,
) -> UpstreamReply:
    def produce() -> Iterator[bytes]:
        yield from chunks
        if error is not None:
            raise error

    headers = [("Content-Type", content_type), ("request-id", "req_1"), ("set-cookie", "s")]
    return UpstreamReply(status, headers, produce(), Closing())


class FakeUpstream:
    def __init__(self, *replies: UpstreamReply | UpstreamError) -> None:
        self.replies = list(replies)
        self.sent: list[tuple[str, dict[str, str], bytes]] = []

    def send(self, path: str, headers: Any, body: bytes) -> UpstreamReply:
        self.sent.append((path, dict(headers), body))
        reply = self.replies.pop(0)
        if isinstance(reply, UpstreamError):
            raise reply
        return reply


class FakeReply:
    def __init__(self, fail_start: bool = False, fail_write: bool = False) -> None:
        self.fail_start = fail_start
        self.fail_write = fail_write
        self.status: int | None = None
        self.headers: list[tuple[str, str]] = []
        self.body = b""

    def start(self, status: int, headers: list[tuple[str, str]]) -> None:
        if self.fail_start:
            raise BrokenPipeError
        self.status, self.headers = status, headers

    def write(self, chunk: bytes) -> None:
        if self.fail_write:
            raise ConnectionResetError
        self.body += chunk

    def error(self) -> dict[str, Any]:
        return json.loads(self.body)["error"]


def make_proxy(
    tmp_path: Path, *replies: UpstreamReply | UpstreamError, **changes: Any
) -> tuple[Proxy, FakeUpstream, Path]:
    upstream = FakeUpstream(*replies)
    state = tmp_path / "state.json"
    settings = load_settings(json.dumps(settings_payload(**changes)))
    return Proxy(settings, KEY, upstream, state), upstream, state


def call(
    proxy: Proxy,
    data: bytes | None = None,
    method: str = "POST",
    target: str = "/v1/messages?beta=true",
    reply: FakeReply | None = None,
) -> FakeReply:
    reply = reply or FakeReply()
    proxy.serve(method, target, AGENT_HEADERS, body() if data is None else data, reply)
    return reply


def state_of(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_streamed_reply_is_passed_on_and_counted(tmp_path: Path) -> None:
    proxy, upstream, state = make_proxy(tmp_path, upstream_reply(chunks=(STREAM[:7], STREAM[7:])))
    reply = call(proxy)
    path, headers, sent = upstream.sent[0]
    assert (path, sent) == ("/v1/messages?beta=true", body())
    assert headers["x-api-key"] == KEY and "authorization" not in headers
    assert reply.status == 200 and reply.body == STREAM
    assert reply.headers == [
        ("Content-Type", "text/event-stream; charset=utf-8"),
        ("request-id", "req_1"),
    ]
    usd = expected_usd(SONNET, STREAM_USAGE)
    assert state_of(state) == {
        "schema": 1,
        "requests": 1,
        "usd": str(usd),
        "max_usd": "2",
        "max_requests": 100,
        "unknown_cost": False,
        "pending": False,
        "stopped": None,
        "refusals": {},
        "models": {SONNET: {"requests": 1, "usd": str(usd), "tokens": STREAM_USAGE.to_payload()}},
    }
    assert KEY not in state.read_text(encoding="utf-8")
    assert not (tmp_path / "state.json.tmp").exists()


def test_the_state_says_when_a_request_is_on_its_way(tmp_path: Path) -> None:
    """Killed while it waits for the API, the proxy leaves ``pending`` set: the plugin then
    charges an unknown cost (R7)."""
    proxy, upstream, state = make_proxy(tmp_path, upstream_reply(), UpstreamError(sent=True))
    seen: list[tuple[int, bool]] = []
    send = upstream.send

    def sending(path: str, headers: Any, data: bytes) -> UpstreamReply:
        counts = state_of(state)
        seen.append((counts["requests"], counts["pending"]))
        return send(path, headers, data)

    upstream.send = sending  # type: ignore[method-assign]
    call(proxy)
    call(proxy)
    assert seen == [(1, True), (2, True)]
    assert state_of(state)["pending"] is False


def test_a_json_reply_is_counted(tmp_path: Path) -> None:
    data = json.dumps({"usage": {"input_tokens": 10, "output_tokens": 20}}).encode()
    proxy, _, state = make_proxy(
        tmp_path,
        upstream_reply(chunks=(data,), content_type="application/json"),
        upstream_reply(chunks=(data,), content_type="application/json"),
    )
    call(proxy, body(stream=False))
    call(proxy, body(stream=False))
    usd = expected_usd(SONNET, Usage(input=10, output=20))
    counts = state_of(state)
    assert counts["usd"] == str(2 * usd)
    assert counts["models"][SONNET]["tokens"]["output"] == 40


def test_an_api_error_costs_nothing(tmp_path: Path) -> None:
    error = b'{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'
    proxy, _, state = make_proxy(
        tmp_path, upstream_reply(529, (error,), "application/json"), upstream_reply()
    )
    assert call(proxy).status == 529
    assert call(proxy).status == 200
    counts = state_of(state)
    assert counts["requests"] == 2 and not counts["unknown_cost"]
    assert counts["models"][SONNET]["requests"] == 2
    assert counts["usd"] == str(expected_usd(SONNET, STREAM_USAGE))


def test_a_reply_whose_cost_is_unknown_stops_the_task(tmp_path: Path) -> None:
    proxy, upstream, state = make_proxy(
        tmp_path, upstream_reply(chunks=(b"data: {}\n",)), upstream_reply()
    )
    call(proxy)
    refused = call(proxy)
    assert len(upstream.sent) == 1
    assert refused.status == 403 and refused.error()["type"] == "permission_error"
    assert "coût" in refused.error()["message"]
    assert ("x-should-retry", "false") in refused.headers
    counts = state_of(state)
    assert counts["unknown_cost"] and counts["stopped"] == "cout_inconnu"
    assert counts["refusals"] == {"cout_inconnu": 1}


def test_the_usd_ceiling_stops_the_task_after_one_request_at_most(tmp_path: Path) -> None:
    proxy, upstream, state = make_proxy(
        tmp_path, upstream_reply(), upstream_reply(), max_usd="0.001"
    )
    assert call(proxy).status == 200
    assert call(proxy).error()["message"] == "plafond de coût de la tâche atteint"
    assert len(upstream.sent) == 1
    assert state_of(state)["stopped"] == "plafond_usd"


def test_the_request_ceiling_stops_the_task(tmp_path: Path) -> None:
    proxy, upstream, state = make_proxy(tmp_path, upstream_reply(), max_requests=1)
    call(proxy)
    assert call(proxy).status == 403
    assert len(upstream.sent) == 1
    assert state_of(state)["refusals"] == {"plafond_requetes": 1}


@pytest.mark.parametrize(
    ("method", "target", "status", "code"),
    [
        ("GET", "/v1/messages", 405, "methode"),
        ("POST", "/v1/models", 404, "chemin"),
        ("POST", "/v1/messages/count_tokens", 404, "chemin"),
        ("POST", "/v1/messages?beta=true&x=1", 404, "chemin"),
        ("POST", "http://api.anthropic.com/v1/messages", 404, "chemin"),
    ],
)
def test_only_the_messages_endpoint_is_served(
    tmp_path: Path, method: str, target: str, status: int, code: str
) -> None:
    proxy, upstream, state = make_proxy(tmp_path)
    reply = call(proxy, method=method, target=target)
    assert reply.status == status and not upstream.sent
    assert state_of(state)["refusals"] == {code: 1}


def test_a_refused_request_never_reaches_the_api(tmp_path: Path) -> None:
    proxy, upstream, state = make_proxy(tmp_path)
    reply = FakeReply()
    proxy.serve("POST", "/v1/messages", {"content-type": "text/plain"}, body(), reply)
    refused = call(proxy, body(tools=[{"type": "web_search_20250305"}]))
    assert reply.status == 415 and reply.error()["type"] == "invalid_request_error"
    assert refused.status == 403 and not upstream.sent
    assert state_of(state)["refusals"] == {"entete": 1, "outil": 1}


@pytest.mark.parametrize(("sent", "unknown"), [(False, False), (True, True)])
def test_an_unreachable_api_answers_502(tmp_path: Path, sent: bool, unknown: bool) -> None:
    proxy, _, state = make_proxy(tmp_path, UpstreamError(sent=sent))
    reply = call(proxy)
    assert reply.status == 502 and reply.error()["type"] == "api_error"
    assert (("x-should-retry", "false") in reply.headers) is sent
    counts = state_of(state)
    assert counts["unknown_cost"] is unknown and counts["refusals"] == {"amont": 1}


def test_a_reply_cut_upstream_is_charged_its_max_tokens(tmp_path: Path) -> None:
    cut = upstream_reply(chunks=(sse(START),), error=http.client.IncompleteRead(b""))
    proxy, _, state = make_proxy(tmp_path, cut)
    call(proxy)
    assert cut.close.closed == 1  # type: ignore[attr-defined]
    assert state_of(state)["models"][SONNET]["tokens"]["output"] == 1024


@pytest.mark.parametrize(
    "reply", [FakeReply(fail_start=True), FakeReply(fail_write=True)], ids=["start", "write"]
)
def test_a_client_gone_away_is_still_charged(tmp_path: Path, reply: FakeReply) -> None:
    proxy, _, state = make_proxy(tmp_path, upstream_reply(chunks=(STREAM[:9], STREAM[9:])))
    call(proxy, reply=reply)
    assert reply.body == b""
    assert state_of(state)["usd"] == str(expected_usd(SONNET, STREAM_USAGE))


def test_a_refusal_to_a_client_gone_away_is_dropped(tmp_path: Path) -> None:
    proxy, _, state = make_proxy(tmp_path)
    reply = FakeReply(fail_start=True)
    call(proxy, method="DELETE", reply=reply)
    assert reply.body == b"" and state_of(state)["refusals"] == {"methode": 1}


def test_the_state_says_nothing_of_the_requests(tmp_path: Path) -> None:
    proxy, _, state = make_proxy(tmp_path, upstream_reply())
    call(proxy, body(messages=[{"role": "user", "content": "secret-de-test"}]))
    assert "secret-de-test" not in state.read_text(encoding="utf-8")


# --- HTTP side -----------------------------------------------------------------------------------


class FakeSocket:
    def __init__(self, request: bytes) -> None:
        self.reader = io.BytesIO(request)
        self.sent = bytearray()
        self.timeout: float | None = None

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def makefile(self, mode: str, size: int = -1) -> io.BytesIO:
        return self.reader

    def sendall(self, data: bytes) -> None:
        self.sent += data


def http_request(method: str, data: bytes, headers: dict[str, str]) -> bytes:
    lines = [f"{method} /v1/messages HTTP/1.1", "Host: llm-proxy:8080"]
    lines += [f"{name}: {value}" for name, value in headers.items()]
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + data


def handle(proxy: Proxy, raw: bytes) -> FakeSocket:
    socket = FakeSocket(raw)
    handler_for(proxy)(socket, ("172.30.0.2", 50000), None)
    return socket


def test_the_handler_serves_one_request(tmp_path: Path) -> None:
    proxy, upstream, _ = make_proxy(tmp_path, upstream_reply())
    data = body()
    headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(data)),
        "X-Api-Key": "agent-placeholder",
    }
    socket = handle(proxy, http_request("POST", data, headers))
    head, _, payload = bytes(socket.sent).partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.0 200")
    assert b"text/event-stream" in head and b"Python" not in head
    assert payload == STREAM
    assert upstream.sent[0][1]["x-api-key"] == KEY
    assert socket.timeout == llm_proxy.CLIENT_TIMEOUT_S


def test_the_handler_refuses_a_chunked_body(tmp_path: Path) -> None:
    proxy, upstream, state = make_proxy(tmp_path)
    socket = handle(proxy, http_request("POST", b"0\r\n\r\n", {"Transfer-Encoding": "chunked"}))
    assert bytes(socket.sent).startswith(b"HTTP/1.0 411") and not upstream.sent
    assert state_of(state)["refusals"] == {"taille": 1}


def test_the_handler_drops_a_truncated_body(tmp_path: Path) -> None:
    proxy, upstream, state = make_proxy(tmp_path)
    socket = handle(proxy, http_request("POST", b"{}", {"Content-Length": "50"}))
    assert socket.sent == b"" and not upstream.sent and not state.exists()


def test_the_handler_passes_other_methods_to_the_proxy(tmp_path: Path) -> None:
    proxy, _, _ = make_proxy(tmp_path)
    socket = handle(proxy, http_request("GET", b"", {}))
    assert bytes(socket.sent).startswith(b"HTTP/1.0 405")


def test_a_server_error_prints_one_line(capsys: pytest.CaptureFixture[str]) -> None:
    server = ProxyServer.__new__(ProxyServer)
    try:
        raise RuntimeError(KEY)
    except RuntimeError:
        server.handle_error(None, None)
    err = capsys.readouterr().err
    assert err == "cerveau-llm-proxy : erreur interne sur une requête\n"


# --- entry point ---------------------------------------------------------------------------------


def server_class(interrupt: bool = False) -> tuple[type, dict[str, Any]]:
    calls: dict[str, Any] = {}

    class Server:
        def __init__(self, address: tuple[str, int], handler: type) -> None:
            calls["address"], calls["handler"] = address, handler

        def serve_forever(self) -> None:
            calls["served"] = True
            if interrupt:
                raise KeyboardInterrupt

        def server_close(self) -> None:
            calls["closed"] = True

    return Server, calls


def run_main(tmp_path: Path, environ: dict[str, str], **kwargs: Any) -> int:
    settings = tmp_path / "proxy.json"
    if not settings.exists():
        settings.write_text(json.dumps(settings_payload()), encoding="utf-8")
    argv = ["--settings", str(settings), "--state", str(tmp_path / "state.json")]
    return main(argv + kwargs.pop("extra", []), environ=environ, **kwargs)


@pytest.mark.parametrize("interrupt", [False, True])
def test_the_proxy_starts_with_its_settings_and_key(tmp_path: Path, interrupt: bool) -> None:
    server, calls = server_class(interrupt)
    timeouts: list[float] = []

    def upstream(timeout: float) -> FakeUpstream:
        timeouts.append(timeout)
        return FakeUpstream()

    code = run_main(
        tmp_path, {KEY_ENV: KEY}, upstream=upstream, server=server, extra=["--port", "9000"]
    )
    assert code == 0 and timeouts == [600.0]
    assert calls["address"] == (LISTEN_HOST, 9000) and calls["served"] and calls["closed"]
    assert calls["handler"].proxy.max_body_bytes == 8 << 20
    assert state_of(tmp_path / "state.json")["requests"] == 0


def test_the_default_port() -> None:
    assert LISTEN_PORT == 8080


@pytest.mark.parametrize("key", [None, "", "court", "deux mots-dans-la-cle", "clé-accentuée"])
def test_the_proxy_does_not_start_without_a_well_formed_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], key: str | None
) -> None:
    server, calls = server_class()
    environ = {} if key is None else {KEY_ENV: key}
    assert run_main(tmp_path, environ, upstream=lambda t: FakeUpstream(), server=server) == 2
    assert not calls
    err = capsys.readouterr().err
    assert KEY_ENV in err and (not key or key not in err)


@pytest.mark.parametrize("problem", ["missing", "invalid", "state"])
def test_the_proxy_does_not_start_with_wrong_settings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], problem: str
) -> None:
    settings = tmp_path / "proxy.json"
    if problem == "invalid":
        settings.write_text("{}", encoding="utf-8")
    server, calls = server_class()
    argv = ["--settings", str(settings), "--state", str(tmp_path / "absent" / "state.json")]
    if problem == "state":
        settings.write_text(json.dumps(settings_payload()), encoding="utf-8")
    code = main(argv, environ={KEY_ENV: KEY}, upstream=lambda t: FakeUpstream(), server=server)
    assert code == 2 and not calls
    assert KEY not in capsys.readouterr().err
