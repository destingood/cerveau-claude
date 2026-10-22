"""Anthropic API proxy of the code agent (ADR-053, F2, F3); standard library only.

It runs in a container of its own, one per task. The agent's container reaches it on an internal
Docker network with no other way out; only the proxy reaches ``api.anthropic.com``. The proxy

- lets through ``POST /v1/messages`` alone, for a model of its list and with the request fields
  the agent needs: no server tool, no URL or file source, no container, no costlier speed or
  region. The API fetches or runs nothing on the agent's behalf, so nothing leaves by that way;
- drops any key the agent sends and adds the real one, read from its own environment; the key
  goes into the upstream request only, never into a reply, a log or the state file (R6);
- counts the tokens of each reply and prices them with the prices it was given, with the
  arithmetic of ``core/models/costs.py`` (R1). Once the task's ceiling in USD or in requests is
  reached, or once a cost could not be read (R7), it refuses every further request. One request
  runs at a time, so a ceiling is exceeded by the cost of one request at most;
- writes its counts, never a request's content, to a state file that the plugin reads. The file
  also says whether a request is on its way (``pending``): stopped then, the proxy may owe the API
  a cost it never read, which the plugin charges as unknown (R7).

The file is copied alone into the ``cerveau-llm-proxy`` image: it imports the standard library
only (a test checks it).
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import ssl
import sys
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, fields
from decimal import ROUND_CEILING, Context, Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol

SCHEMA = 1  # version of the settings and of the state file
UPSTREAM_HOST = "api.anthropic.com"
UPSTREAM_PORT = 443
MESSAGES_PATH = "/v1/messages"
# Query strings the CLI may add (A_VERIFIER at the first real test, B270).
ALLOWED_QUERIES = frozenset({"", "beta=true"})
KEY_ENV = "ANTHROPIC_API_KEY"
LISTEN_HOST = "0.0.0.0"  # noqa: S104 - inside its container, on the agent's internal network only
LISTEN_PORT = 8080
CLIENT_TIMEOUT_S = 60.0  # a client that stops sending or reading is dropped

# Request fields let through (A_VERIFIER against the CLI's requests, B270); a field listed in
# FIELD_VALUES only with one of those values: the other ones cost more (fast speed, US-only
# inference) or are not priced here. ``context_management`` is left out: a server-side
# compaction is a sampling of its own whose billing this proxy does not read (A_VERIFIER).
REQUEST_FIELDS = frozenset(
    {
        "model",
        "messages",
        "system",
        "max_tokens",
        "metadata",
        "stop_sequences",
        "stream",
        "temperature",
        "top_k",
        "top_p",
        "tools",
        "tool_choice",
        "thinking",
        "output_config",
        "cache_control",
        "service_tier",
        "inference_geo",
        "speed",
    }
)
FIELD_VALUES: Mapping[str, frozenset[str]] = {
    "inference_geo": frozenset({"global"}),
    "speed": frozenset({"standard"}),
    "service_tier": frozenset({"auto", "standard_only"}),
}
# Content blocks a client sends; an image or a document only from data it carries itself.
BLOCK_TYPES = frozenset(
    {"text", "image", "document", "tool_use", "tool_result", "thinking", "redacted_thinking"}
)
SOURCE_TYPES = frozenset({"base64", "text", "content"})
MAX_DEPTH = 4  # tool_result > document > content source > block
# A reply priced otherwise than the price list: its cost is unknown (R7).
USAGE_VALUES: Mapping[str, frozenset[str]] = {
    "inference_geo": frozenset({"global"}),
    "speed": frozenset({"standard"}),
    "service_tier": frozenset({"standard"}),
}

RESPONSE_HEADERS = frozenset({"content-type", "request-id", "retry-after", "x-should-retry"})
_VERSION = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_BETA = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}(?:\s*,\s*[a-z0-9][a-z0-9.-]{0,63}){0,31}")
_KEY = re.compile(r"[\x21-\x7e]{8,512}")
_LENGTH = re.compile(r"[0-9]{1,12}")
_FIELD_NAME = re.compile(r"[a-z_]{1,40}")

CHUNK_BYTES = 65536
MAX_EVENT_BYTES = 1 << 20  # one SSE line
MAX_JSON_BYTES = 32 << 20  # a reply that is not a stream

QUANTUM = Decimal("0.000001")
_CTX = Context(prec=28)
_PER_MTOK = Decimal(1_000_000)
_ERROR_TYPES = {
    403: "permission_error",
    404: "not_found_error",
    413: "request_too_large",
    502: "api_error",
}


class SettingsError(ValueError):
    """The settings file is missing a value or has a wrong one: the proxy does not start."""


@dataclass(frozen=True)
class Tier:
    """USD per million tokens, while the prompt is at most ``max_prompt_tokens`` tokens."""

    max_prompt_tokens: int | None
    input: Decimal
    cache_write_5m: Decimal
    cache_write_1h: Decimal
    cache_read: Decimal
    output: Decimal


@dataclass(frozen=True)
class Settings:
    models: Mapping[str, tuple[Tier, ...]]
    max_usd: Decimal
    max_requests: int
    max_body_bytes: int
    upstream_timeout_s: float


_PRICES = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")
_SETTINGS_KEYS = frozenset(
    {"schema", "models", "max_usd", "max_requests", "max_body_bytes", "upstream_timeout_s"}
)


def _mapping(value: object, what: str, keys: frozenset[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SettingsError(f"{what} : table attendue")
    if keys is not None and set(value) != keys:
        raise SettingsError(f"{what} : clés attendues {sorted(keys)}")
    return value


def _decimal(value: object, what: str, *, positive: bool = False) -> Decimal:
    try:
        number = Decimal(value) if isinstance(value, str) else None
    except InvalidOperation:
        number = None
    if number is None or not number.is_finite() or number < 0 or (positive and number == 0):
        raise SettingsError(f"{what} : nombre décimal positif attendu, en texte")
    return number


def _count(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SettingsError(f"{what} : entier supérieur ou égal à 1 attendu")
    return value


def _tiers(value: object, model: str) -> tuple[Tier, ...]:
    raw = _mapping(value, f"models.{model}", frozenset({"tiers"}))["tiers"]
    if not isinstance(raw, list) or not raw:
        raise SettingsError(f"models.{model}.tiers : liste non vide attendue")
    tiers: list[Tier] = []
    for index, item in enumerate(raw):
        what = f"models.{model}.tiers[{index}]"
        last = index == len(raw) - 1
        keys = frozenset(_PRICES) | (frozenset() if last else frozenset({"max_prompt_tokens"}))
        tier = _mapping(item, what, keys)
        bound = None if last else _count(tier["max_prompt_tokens"], f"{what}.max_prompt_tokens")
        if bound is not None and tiers and bound <= (tiers[-1].max_prompt_tokens or 0):
            raise SettingsError(f"{what}.max_prompt_tokens : bornes croissantes attendues")
        prices = {name: _decimal(tier[name], f"{what}.{name}") for name in _PRICES}
        tiers.append(Tier(max_prompt_tokens=bound, **prices))
    return tuple(tiers)


def load_settings(text: str) -> Settings:
    """Read the settings the plugin wrote: prices of the allowed models and the task's ceilings.

    The last price tier of a model has no bound, so that a tier always applies.
    """
    try:
        raw = json.loads(text)
    except ValueError:
        raise SettingsError("fichier de réglages : JSON illisible") from None
    data = _mapping(raw, "réglages", _SETTINGS_KEYS)
    if data["schema"] != SCHEMA:
        raise SettingsError(f"schema : {SCHEMA} attendu")
    models = _mapping(data["models"], "models")
    if not models:
        raise SettingsError("models : au moins un modèle attendu")
    timeout = data["upstream_timeout_s"]
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or not 0 < timeout < 3600:
        raise SettingsError("upstream_timeout_s : nombre de secondes entre 0 et 3600 attendu")
    return Settings(
        models={name: _tiers(value, name) for name, value in models.items()},
        max_usd=_decimal(data["max_usd"], "max_usd", positive=True),
        max_requests=_count(data["max_requests"], "max_requests"),
        max_body_bytes=_count(data["max_body_bytes"], "max_body_bytes"),
        upstream_timeout_s=float(timeout),
    )


@dataclass(frozen=True)
class Usage:
    """Tokens of one reply, split the way they are billed (as ``core.models.costs.TokenUsage``)."""

    input: int = 0  # tokens after the last cache breakpoint
    cache_read: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    output: int = 0  # thinking included

    @property
    def prompt_tokens(self) -> int:
        return self.input + self.cache_read + self.cache_write_5m + self.cache_write_1h

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            **{f.name: getattr(self, f.name) + getattr(other, f.name) for f in fields(self)}
        )

    def to_payload(self) -> dict[str, int]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


class _Unreadable(Exception):
    pass


def _tokens(raw: Mapping[str, Any], name: str) -> int:
    value = raw.get(name)
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _Unreadable(name)
    return value


def read_usage(raw: object) -> Usage | None:
    """The billed tokens of an API ``usage`` object; ``None`` when they cannot be priced here.

    Cache writes not reported as 5 min ones are priced at the 1 h rate, the higher one (prudence,
    as ``core/models/costs.py``). A server tool use, a fast speed, a US-only region, another
    service tier or several sampling iterations have prices this proxy does not read: the cost
    is unknown.
    """
    if not isinstance(raw, dict):
        return None
    try:
        for name, allowed in USAGE_VALUES.items():
            if raw.get(name) is not None and raw[name] not in allowed:
                raise _Unreadable(name)
        if raw.get("iterations"):
            raise _Unreadable("iterations")
        server = {} if raw.get("server_tool_use") is None else raw["server_tool_use"]
        creation = {} if raw.get("cache_creation") is None else raw["cache_creation"]
        if not isinstance(server, dict) or not isinstance(creation, dict):
            raise _Unreadable("server_tool_use")
        if any(_tokens(server, name) for name in server):
            raise _Unreadable("server_tool_use")
        write_5m = _tokens(creation, "ephemeral_5m_input_tokens")
        writes = max(
            _tokens(raw, "cache_creation_input_tokens"),
            write_5m + _tokens(creation, "ephemeral_1h_input_tokens"),
        )
        return Usage(
            input=_tokens(raw, "input_tokens"),
            cache_read=_tokens(raw, "cache_read_input_tokens"),
            cache_write_5m=write_5m,
            cache_write_1h=writes - write_5m,
            output=_tokens(raw, "output_tokens"),
        )
    except _Unreadable:
        return None


def price_tier(tiers: tuple[Tier, ...], usage: Usage) -> Tier:
    for tier in tiers[:-1]:
        if usage.prompt_tokens <= (tier.max_prompt_tokens or 0):
            return tier
    return tiers[-1]


def cost_usd(tiers: tuple[Tier, ...], usage: Usage) -> Decimal:
    """Cost of one reply in USD, rounded up to 1e-6 (as ``CostCalculator.llm_usd``)."""
    tier = price_tier(tiers, usage)
    total = Decimal(0)
    for name in _PRICES:
        total = _CTX.add(total, _CTX.multiply(Decimal(getattr(usage, name)), getattr(tier, name)))
    return _CTX.divide(total, _PER_MTOK).quantize(QUANTUM, rounding=ROUND_CEILING, context=_CTX)


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _merge(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    """Usage of a stream: counts are cumulative, so the larger one is kept (prudence)."""
    merged = dict(old)
    for name, value in new.items():
        before = merged.get(name)
        if isinstance(before, dict) and isinstance(value, dict):
            merged[name] = _merge(before, value)
        elif _is_count(before) and _is_count(value):
            merged[name] = max(before, value)
        else:
            merged[name] = value
    return merged


class Meter(Protocol):
    def feed(self, chunk: bytes) -> None: ...
    def usage(self, max_tokens: int) -> Usage | None: ...


class StreamMeter:
    """Reads the usage of a streamed reply from its ``message_start`` and ``message_delta`` events.

    The counts of ``message_delta`` are cumulative (streaming documentation, 22/10/2026). A
    stream cut before its ``message_delta`` is charged the request's ``max_tokens`` as output,
    an upper bound; without ``message_start`` its cost is unknown.
    """

    def __init__(self) -> None:
        self._pending = b""
        self._usage: dict[str, Any] = {}
        self._started = False
        self._finished = False
        self._broken = False

    def feed(self, chunk: bytes) -> None:
        *lines, self._pending = (self._pending + chunk).split(b"\n")
        for line in lines:
            self._line(line)
        if len(self._pending) > MAX_EVENT_BYTES:
            self._broken = True
            self._pending = b""

    def _line(self, line: bytes) -> None:
        if not line.startswith(b"data:") or b'"message_' not in line:
            return
        try:
            event = json.loads(line[5:])
        except (ValueError, RecursionError):
            self._broken = True
            return
        kind = event.get("type") if isinstance(event, dict) else None
        if kind == "message_start":
            message = event.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
        elif kind == "message_delta":
            usage = event.get("usage")
        else:
            return
        if not isinstance(usage, dict):
            self._broken = True
            return
        self._usage = _merge(self._usage, usage)
        self._started = self._started or kind == "message_start"
        self._finished = self._finished or kind == "message_delta"

    def usage(self, max_tokens: int) -> Usage | None:
        if self._broken or not self._started:
            return None
        raw = dict(self._usage)
        if not self._finished:
            output = raw.get("output_tokens")
            raw["output_tokens"] = max(output if _is_count(output) else 0, max_tokens)
        return read_usage(raw)


class JsonMeter:
    """Reads the usage of a reply that is not a stream, kept up to ``MAX_JSON_BYTES``."""

    def __init__(self) -> None:
        self._parts: list[bytes] = []
        self._size = 0

    def feed(self, chunk: bytes) -> None:
        self._size += len(chunk)
        if self._size <= MAX_JSON_BYTES:
            self._parts.append(chunk)

    def usage(self, max_tokens: int) -> Usage | None:
        if self._size > MAX_JSON_BYTES:
            return None
        try:
            body = json.loads(b"".join(self._parts))
        except (ValueError, RecursionError):
            return None
        return read_usage(body.get("usage") if isinstance(body, dict) else None)


@dataclass(frozen=True)
class Refusal:
    """A request the proxy does not pass on. ``code`` is counted in the state file; ``message``
    is shown to the agent and never repeats the key or the request's content."""

    status: int
    code: str
    message: str
    retry: bool = False


@dataclass(frozen=True)
class Message:
    model: str
    max_tokens: int


def _bad_body(message: str) -> Refusal:
    return Refusal(400, "corps", message)


def _check_content(content: object, depth: int = 0) -> Refusal | None:
    if content is None or isinstance(content, str):
        return None
    if not isinstance(content, list) or depth > MAX_DEPTH:
        return _bad_body("contenu mal formé")
    for block in content:
        kind = block.get("type") if isinstance(block, dict) else None
        if kind not in BLOCK_TYPES:
            return Refusal(403, "bloc", "type de bloc non autorisé par le proxy")
        nested = block.get("content") if kind == "tool_result" else None
        if kind in ("image", "document"):
            source = block.get("source")
            if not isinstance(source, dict) or source.get("type") not in SOURCE_TYPES:
                return Refusal(403, "source", "source non autorisée par le proxy (URL ou fichier)")
            nested = source.get("content") if source["type"] == "content" else None
        refusal = _check_content(nested, depth + 1)
        if refusal is not None:
            return refusal
    return None


def inspect(body: bytes, models: Mapping[str, object]) -> Message | Refusal:
    """Check a ``/v1/messages`` request: fields, model, tools and content sources."""
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        return _bad_body("corps JSON illisible")
    if not isinstance(payload, dict):
        return _bad_body("corps JSON : objet attendu")
    extra = sorted(set(payload) - REQUEST_FIELDS)
    if extra:
        name = extra[0] if _FIELD_NAME.fullmatch(extra[0]) else "?"
        return Refusal(403, "champ", f"champ non autorisé par le proxy : {name}")
    for name, values in FIELD_VALUES.items():
        if name in payload and payload[name] not in values:
            return Refusal(403, "champ", f"valeur non autorisée par le proxy : {name}")
    model = payload.get("model")
    if not isinstance(model, str) or model not in models:
        allowed = ", ".join(sorted(models))
        return Refusal(403, "modele", f"modèle non autorisé par le proxy ; permis : {allowed}")
    max_tokens = payload.get("max_tokens")
    if not _is_count(max_tokens) or max_tokens < 1:
        return _bad_body("max_tokens : entier supérieur ou égal à 1 attendu")
    tools = payload.get("tools", [])
    if not isinstance(tools, list):
        return _bad_body("tools : liste attendue")
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type", "custom") != "custom":
            return Refusal(403, "outil", "outil serveur non autorisé par le proxy")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not all(isinstance(m, dict) for m in messages):
        return _bad_body("messages : liste d'objets attendue")
    for part in [payload.get("system"), *(m.get("content") for m in messages)]:
        refusal = _check_content(part)
        if refusal is not None:
            return refusal
    return Message(model=model, max_tokens=max_tokens)


def header_map(items: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Request headers by lower-case name; a repeated header is joined with commas."""
    headers: dict[str, str] = {}
    for name, value in items:
        key = name.lower()
        headers[key] = f"{headers[key]}, {value}" if key in headers else value
    return headers


def body_size(headers: Mapping[str, str], limit: int) -> int | Refusal:
    """Length of the body to read: ``Content-Length`` only, never a chunked body."""
    if "transfer-encoding" in headers:
        return Refusal(411, "taille", "content-length requis ; transfer-encoding refusé")
    raw = headers.get("content-length", "0")
    if not _LENGTH.fullmatch(raw):
        return Refusal(400, "taille", "content-length mal formé")
    if int(raw) > limit:
        return Refusal(413, "taille", "corps de requête trop gros pour le proxy")
    return int(raw)


def upstream_headers(headers: Mapping[str, str], key: str) -> dict[str, str] | Refusal:
    """Headers sent upstream: content type, API version and betas, then the real key.

    A key, a cookie or any other header the agent sends is dropped. No ``Accept-Encoding`` is
    passed on, so the reply comes uncompressed and its usage can be read.
    """
    content_type = headers.get("content-type", "")
    if content_type.split(";")[0].strip().lower() != "application/json":
        return Refusal(415, "entete", "content-type application/json attendu")
    sent = {"content-type": "application/json"}
    version = headers.get("anthropic-version")
    if version is not None:
        if not _VERSION.fullmatch(version):
            return Refusal(400, "entete", "anthropic-version mal formé")
        sent["anthropic-version"] = version
    beta = headers.get("anthropic-beta")
    if beta is not None:
        if not _BETA.fullmatch(beta):
            return Refusal(400, "entete", "anthropic-beta mal formé")
        sent["anthropic-beta"] = beta
    sent["x-api-key"] = key
    return sent


def reply_headers(headers: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(name, value) for name, value in headers if name.lower() in RESPONSE_HEADERS]


@dataclass
class UpstreamReply:
    status: int
    headers: list[tuple[str, str]]
    chunks: Iterator[bytes]
    close: Callable[[], None]


class UpstreamError(Exception):
    """The API could not be reached; ``sent`` tells whether it may have read the request."""

    def __init__(self, sent: bool) -> None:
        super().__init__("API injoignable")
        self.sent = sent


class Upstream(Protocol):
    def send(self, path: str, headers: Mapping[str, str], body: bytes) -> UpstreamReply: ...


def _chunks(response: http.client.HTTPResponse) -> Iterator[bytes]:
    while chunk := response.read1(CHUNK_BYTES):
        yield chunk


class HttpsUpstream:
    """``api.anthropic.com`` over TLS with the system's certificates; no HTTP proxy is used."""

    def __init__(
        self,
        timeout_s: float,
        connect: Callable[..., http.client.HTTPSConnection] = http.client.HTTPSConnection,
        context: ssl.SSLContext | None = None,
    ) -> None:
        self._timeout_s = timeout_s
        self._connect = connect
        self._context = context or ssl.create_default_context()

    def send(self, path: str, headers: Mapping[str, str], body: bytes) -> UpstreamReply:
        connection = self._connect(
            UPSTREAM_HOST, UPSTREAM_PORT, timeout=self._timeout_s, context=self._context
        )
        try:
            connection.connect()
        except OSError:
            connection.close()
            raise UpstreamError(sent=False) from None
        try:
            connection.request("POST", path, body=body, headers=dict(headers))
            response = connection.getresponse()
        except (OSError, http.client.HTTPException):
            connection.close()
            raise UpstreamError(sent=True) from None
        return UpstreamReply(
            response.status, response.getheaders(), _chunks(response), connection.close
        )


class Reply(Protocol):
    def start(self, status: int, headers: list[tuple[str, str]]) -> None: ...
    def write(self, chunk: bytes) -> None: ...


@dataclass
class _ModelCount:
    requests: int = 0
    usage: Usage = field(default_factory=Usage)
    usd: Decimal = Decimal(0)


class Proxy:
    """Checks, forwards and counts the agent's requests, one at a time."""

    def __init__(self, settings: Settings, key: str, upstream: Upstream, state: Path) -> None:
        self._settings = settings
        self._key = key
        self._upstream = upstream
        self._state = state
        self._lock = threading.Lock()
        self._requests = 0
        self._usd = Decimal(0)
        self._unknown = False
        self._pending = False
        self._refusals: dict[str, int] = {}
        self._models: dict[str, _ModelCount] = {}

    @property
    def max_body_bytes(self) -> int:
        return self._settings.max_body_bytes

    def _stopped(self) -> Refusal | None:
        if self._unknown:
            return Refusal(403, "cout_inconnu", "coût d'une réponse illisible : tâche arrêtée")
        if self._usd >= self._settings.max_usd:
            return Refusal(403, "plafond_usd", "plafond de coût de la tâche atteint")
        if self._requests >= self._settings.max_requests:
            return Refusal(403, "plafond_requetes", "plafond de requêtes de la tâche atteint")
        return None

    def snapshot(self) -> dict[str, Any]:
        """Counts of the task, without any request's content or the key."""
        stopped = self._stopped()
        return {
            "schema": SCHEMA,
            "requests": self._requests,
            "usd": str(self._usd),
            "max_usd": str(self._settings.max_usd),
            "max_requests": self._settings.max_requests,
            "unknown_cost": self._unknown,
            "pending": self._pending,
            "stopped": stopped.code if stopped else None,
            "refusals": dict(sorted(self._refusals.items())),
            "models": {
                name: {"requests": c.requests, "usd": str(c.usd), "tokens": c.usage.to_payload()}
                for name, c in sorted(self._models.items())
            },
        }

    def write_state(self) -> None:
        temporary = self._state.with_name(self._state.name + ".tmp")
        temporary.write_text(json.dumps(self.snapshot(), indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self._state)

    def refuse(self, refusal: Refusal, reply: Reply) -> None:
        with self._lock:
            self._note(refusal.code)
            self.write_state()
        _send_refusal(refusal, reply)

    def serve(
        self, method: str, target: str, headers: Mapping[str, str], body: bytes, reply: Reply
    ) -> None:
        """Answer one request: a refusal, or the API's reply passed on as it comes."""
        checked = self._check(method, target, headers, body)
        if isinstance(checked, Refusal):
            self.refuse(checked, reply)
            return
        sent, message = checked
        with self._lock:
            stopped = self._stopped()
            if stopped is None:
                self._requests += 1
                self._pending = True
                self.write_state()
                try:
                    self._forward(target, sent, body, message, reply)
                finally:
                    self._pending = False
            else:
                self._note(stopped.code)
            self.write_state()
        if stopped is not None:
            _send_refusal(stopped, reply)

    def _check(
        self, method: str, target: str, headers: Mapping[str, str], body: bytes
    ) -> tuple[dict[str, str], Message] | Refusal:
        path, _, query = target.partition("?")
        if method != "POST":
            return Refusal(405, "methode", "seule la méthode POST est permise")
        if path != MESSAGES_PATH or query not in ALLOWED_QUERIES:
            return Refusal(404, "chemin", f"seul {MESSAGES_PATH} est permis")
        sent = upstream_headers(headers, self._key)
        if isinstance(sent, Refusal):
            return sent
        message = inspect(body, self._settings.models)
        if isinstance(message, Refusal):
            return message
        return sent, message

    def _note(self, code: str) -> None:
        self._refusals[code] = self._refusals.get(code, 0) + 1

    def _forward(
        self, target: str, headers: dict[str, str], body: bytes, message: Message, reply: Reply
    ) -> None:
        try:
            upstream = self._upstream.send(target, headers, body)
        except UpstreamError as exc:
            # Sent but unanswered: the API may have billed it, by an amount nobody knows.
            self._unknown = self._unknown or exc.sent
            self._note("amont")
            _send_refusal(Refusal(502, "amont", "API injoignable", retry=not exc.sent), reply)
            return
        kept = reply_headers(upstream.headers)
        streamed = any(
            name.lower() == "content-type" and value.lower().startswith("text/event-stream")
            for name, value in kept
        )
        meter: Meter = StreamMeter() if streamed else JsonMeter()
        client = _try(reply.start, upstream.status, kept)
        try:
            for chunk in upstream.chunks:
                meter.feed(chunk)
                # A client gone away: the reply is still read to its end, so as to be counted.
                client = client and _try(reply.write, chunk)
        except (OSError, http.client.HTTPException):
            pass  # a cut reply: the meter charges what it saw, or reports the cost unknown
        finally:
            upstream.close()
        usage = meter.usage(message.max_tokens)
        billed = upstream.status == 200
        self._unknown = self._unknown or (billed and usage is None)
        count = self._models.setdefault(message.model, _ModelCount())
        count.requests += 1
        if billed and usage is not None:
            usd = cost_usd(self._settings.models[message.model], usage)
            count.usage = count.usage + usage
            count.usd += usd
            self._usd += usd


def _try(write: Callable[..., None], *args: Any) -> bool:
    """Write to the client; ``False`` when it went away."""
    try:
        write(*args)
    except OSError:
        return False
    return True


def _send_refusal(refusal: Refusal, reply: Reply) -> None:
    """An error in the API's format, so that the agent's client reads it as such."""
    error = _ERROR_TYPES.get(refusal.status, "invalid_request_error")
    body = {"type": "error", "error": {"type": error, "message": refusal.message}}
    headers = [("content-type", "application/json")]
    if not refusal.retry:
        headers.append(("x-should-retry", "false"))
    if _try(reply.start, refusal.status, headers):
        _try(reply.write, json.dumps(body, ensure_ascii=False).encode())


class HandlerReply:
    """The HTTP reply of one connection; it is closed once the reply is sent (HTTP/1.0)."""

    def __init__(self, handler: BaseHTTPRequestHandler) -> None:
        self._handler = handler

    def start(self, status: int, headers: list[tuple[str, str]]) -> None:
        self._handler.send_response(status)
        for name, value in headers:
            self._handler.send_header(name, value)
        self._handler.end_headers()

    def write(self, chunk: bytes) -> None:
        self._handler.wfile.write(chunk)


class ProxyHandler(BaseHTTPRequestHandler):
    """Reads one request, hands it to the ``Proxy``; bound to it by ``handler_for``."""

    proxy: Proxy
    server_version = "cerveau-llm-proxy"
    sys_version = ""
    timeout = CLIENT_TIMEOUT_S

    def log_message(self, format: str, *args: Any) -> None:
        """No access log: a path or a header may carry what the agent wrote."""

    def _handle(self) -> None:
        headers = header_map(self.headers.items())
        reply = HandlerReply(self)
        size = body_size(headers, self.proxy.max_body_bytes)
        if isinstance(size, Refusal):
            self.proxy.refuse(size, reply)
            return
        body = self.rfile.read(size)
        if len(body) == size:  # otherwise the client went away
            self.proxy.serve(self.command, self.path, headers, body, reply)

    do_POST = do_GET = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _handle


def handler_for(proxy: Proxy) -> type[ProxyHandler]:
    return type("BoundProxyHandler", (ProxyHandler,), {"proxy": proxy})


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        """One line, never a traceback: its frames may hold a request or the key."""
        print("cerveau-llm-proxy : erreur interne sur une requête", file=sys.stderr)


class Serving(Protocol):
    def serve_forever(self) -> None: ...
    def server_close(self) -> None: ...


def main(
    argv: list[str] | None = None,
    environ: Mapping[str, str] = os.environ,
    upstream: Callable[[float], Upstream] = HttpsUpstream,
    server: Callable[[tuple[str, int], type[ProxyHandler]], Serving] = ProxyServer,
) -> int:
    parser = argparse.ArgumentParser(
        prog="cerveau-llm-proxy", description="Proxy de l'API d'Anthropic pour code_agent."
    )
    parser.add_argument("--settings", type=Path, required=True, help="réglages JSON du plugin")
    parser.add_argument("--state", type=Path, required=True, help="fichier d'état à écrire")
    parser.add_argument("--port", type=int, default=LISTEN_PORT)
    args = parser.parse_args(argv)
    key = environ.get(KEY_ENV, "")
    if not _KEY.fullmatch(key):
        print(f"cerveau-llm-proxy : {KEY_ENV} absente ou mal formée", file=sys.stderr)
        return 2
    try:
        settings = load_settings(args.settings.read_text(encoding="utf-8"))
        proxy = Proxy(settings, key, upstream(settings.upstream_timeout_s), args.state)
        proxy.write_state()
    except (OSError, UnicodeDecodeError, SettingsError) as exc:
        print(f"cerveau-llm-proxy : {exc}", file=sys.stderr)
        return 2
    listening = server((LISTEN_HOST, args.port), handler_for(proxy))
    try:
        listening.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        listening.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point of the image
    sys.exit(main())
