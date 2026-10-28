"""Client of the Légifrance API on PISTE: OAuth token, bounded POST, rate limit and cache (ADR-059).

- **Hosts.** Two fixed pairs only, production and sandbox: ``api.piste.gouv.fr`` with
  ``oauth.piste.gouv.fr``, and their ``sandbox-`` twins. ``config/data_sources.yaml`` chooses the
  pair by its ``url``; any other value is refused. Each request goes through the guard of
  ``core.net`` (public addresses only, connection pinned to the checked address, ADR-006); no
  redirect is followed and the proxies of the environment are ignored.
- **Credentials (H4).** ``PISTE_CLIENT_ID`` and ``PISTE_CLIENT_SECRET`` come from the environment
  the adapter passes to this plugin alone (``runtime.env``). They travel in the body of the token
  request and nowhere else. The token stays in memory, is renewed a minute before it expires and
  is dropped on a 401. No credential or token reaches a message, a log, a cache key or a file.
- **Pace and cache (H9, H10).** One request per second, shared by every process of the checkout
  (``core.net.throttle``). A reply read without error is cached under ``var/juridique/``: 30 days
  for an article version asked by its ``LEGIARTI`` identifier (frozen by nature), 24 h for the
  rest. 2 MB at most per reply.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

import httpx

from core.net.body import read_body
from core.net.guard import FetchError, Resolver, check_url, pin, pinned_request, system_resolver
from core.net.throttle import SharedThrottle
from plugins.legifrance import __version__
from plugins.legifrance.legi import LegiError, load_json

TIMEOUT_S = 20.0
MAX_BYTES = 2_000_000
INTERVAL_S = 1.0  # one request per second (H10, hypothesis until the PISTE quotas are read)
ARTICLE_TTL = timedelta(days=30)
DAILY_TTL = timedelta(hours=24)
TOKEN_MARGIN = timedelta(seconds=60)
TOKEN_MAX_S = 86_400
API_PATH = "/dila/legifrance/lf-engine-app"
OAUTH_PATH = "/api/oauth/token"
UNAVAILABLE = "source officielle indisponible"
ROOT = Path(__file__).resolve().parents[2]
THROTTLE_DIR = ROOT / "var" / "net"
CACHE_DIR = ROOT / "var" / "juridique" / "cache"
USER_AGENT = f"CERVEAU-legifrance/{__version__} (assistant personnel, lecture seule)"
ID_ENV, SECRET_ENV = "PISTE_CLIENT_ID", "PISTE_CLIENT_SECRET"
_CREDENTIAL = re.compile(r"[A-Za-z0-9._~-]{1,256}")
_TOKEN = re.compile(r"[A-Za-z0-9._~+/=-]{1,4096}")
_JSON = "application/json"
Step = Literal["token", "api"]  # the two requests of a read, each to its own host


def utcnow() -> datetime:
    return datetime.now(UTC)


def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Environment:
    name: str
    api: str
    oauth: str


ENVIRONMENTS = {
    env.api + API_PATH: env
    for env in (
        Environment("production", "https://api.piste.gouv.fr", "https://oauth.piste.gouv.fr"),
        Environment(
            "sandbox", "https://sandbox-api.piste.gouv.fr", "https://sandbox-oauth.piste.gouv.fr"
        ),
    )
}
HOSTS = frozenset(
    httpx.URL(url).host for env in ENVIRONMENTS.values() for url in (env.api, env.oauth)
)


def environment(url: str | None) -> Environment:
    """The host pair the configured ``url`` names; nothing else is reachable."""
    found = ENVIRONMENTS.get((url or "").rstrip("/"))
    if found is None:
        raise LegiError(
            f"{UNAVAILABLE} : data_sources.yaml › sources.legifrance.url n'est ni l'adresse "
            "de production ni celle du bac à sable de PISTE"
        )
    return found


@dataclass(frozen=True)
class Credentials:
    client_id: str = field(repr=False)
    secret: str = field(repr=False)


def credentials(environ: Mapping[str, str]) -> Credentials | None:
    """Both PISTE values when both look like credentials; otherwise none (H4)."""
    client_id, secret = environ.get(ID_ENV, "").strip(), environ.get(SECRET_ENV, "").strip()
    if _CREDENTIAL.fullmatch(client_id) and _CREDENTIAL.fullmatch(secret):
        return Credentials(client_id, secret)
    return None


def _digest(key: str) -> str:
    """The cache stores this digest, never the request: a search may hold personal facts."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class ResponseCache:
    """Bodies of replies read without error, kept ``ttl`` under one directory."""

    def __init__(
        self, directory: Path, ttl: timedelta, now: Callable[[], datetime] = utcnow
    ) -> None:
        self.directory, self.ttl, self.now = directory, ttl, now

    def _paths(self, key: str) -> tuple[Path, Path]:
        name = _digest(key)
        return self.directory / f"{name}.body", self.directory / f"{name}.meta"

    def _fresh(self, read_at: datetime) -> bool:
        return timedelta(0) <= self.now() - read_at < self.ttl

    def get(self, key: str) -> tuple[bytes, datetime] | None:
        """The body and the time it was read, if fresh and intact; otherwise a miss."""
        body_path, meta_path = self._paths(key)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            read_at = datetime.fromisoformat(meta["read_at"])
            if meta["key"] != _digest(key) or read_at.tzinfo is None or not self._fresh(read_at):
                return None
            body = body_path.read_bytes()
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if hashlib.sha256(body).hexdigest() != meta.get("sha256"):
            return None
        return body, read_at

    def put(self, key: str, body: bytes, read_at: datetime) -> None:
        """Best effort: a cache that cannot be written only costs a new request later."""
        body_path, meta_path = self._paths(key)
        meta = {
            "key": _digest(key),
            "read_at": read_at.astimezone(UTC).isoformat(timespec="seconds"),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._prune()
            _replace(body_path, body)
            _replace(meta_path, json.dumps(meta).encode("utf-8"))
        except OSError:
            return

    def _prune(self) -> None:
        for meta_path in self.directory.glob("*.meta"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                read_at = datetime.fromisoformat(meta["read_at"])
                stale = read_at.tzinfo is None or not self._fresh(read_at)
            except (OSError, ValueError, KeyError, TypeError):
                stale = True
            if stale:
                for path in (meta_path, meta_path.with_suffix(".body")):
                    with contextlib.suppress(OSError):
                        path.unlink()


def _replace(path: Path, data: bytes) -> None:
    """Write ``data`` to a temporary file beside ``path``, then rename it: never half a file."""
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


@dataclass(frozen=True)
class Read:
    """A parsed JSON reply and the time its body was read from Légifrance (cached or not)."""

    value: Any
    read_at: datetime
    cached: bool


@dataclass(frozen=True)
class _Token:
    environment: str
    value: str = field(repr=False)
    expires_at: datetime


class PisteClient:
    """One POST at a time to the Légifrance API, under its shared rate limit, through a cache."""

    def __init__(
        self,
        throttle: SharedThrottle,
        secrets: Credentials | None,
        *,
        lasting: ResponseCache | None = None,
        daily: ResponseCache | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = system_resolver,
        timeout_s: float = TIMEOUT_S,
        max_bytes: int = MAX_BYTES,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self.throttle, self.transport, self.resolver = throttle, transport, resolver
        self.lasting, self.daily = lasting, daily
        self.timeout_s, self.max_bytes, self.now = timeout_s, max_bytes, now
        self._secrets = secrets
        self._token: _Token | None = None

    @property
    def configured(self) -> bool:
        return self._secrets is not None

    async def post(
        self,
        env: Environment,
        path: str,
        payload: Mapping[str, Any],
        *,
        lasting: bool,
        keep: Callable[[Any], bool] = lambda _: True,
    ) -> Read:
        """The JSON of a 200 reply; a reply that ``keep`` rejects is not cached."""
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        key = f"{env.name} {path} {body}"
        cache = self.lasting if lasting else self.daily
        if cache is not None and (hit := cache.get(key)) is not None:
            try:
                return Read(load_json(hit[0]), hit[1], cached=True)
            except LegiError:
                pass  # a damaged copy: read the source again
        if self._secrets is None:
            raise LegiError(
                f"{UNAVAILABLE} : identifiants PISTE absents ou mal formés ({ID_ENV}, {SECRET_ENV})"
            )
        token = await self._bearer(env, self._secrets)
        reply = await self._send(
            env.api + API_PATH + path,
            body.encode("utf-8"),
            {"Authorization": f"Bearer {token}", "Content-Type": _JSON},
            expected=env.api,
            step="api",
        )
        read_at = self.now()
        value = load_json(reply)
        if cache is not None and keep(value):
            cache.put(key, reply, read_at)
        return Read(value, read_at, cached=False)

    async def _bearer(self, env: Environment, secrets: Credentials) -> str:
        """A token of ``env`` valid one more minute at least, asked for again when needed."""
        held = self._token
        if (
            held is not None
            and held.environment == env.name
            and self.now() < held.expires_at - TOKEN_MARGIN
        ):
            return held.value
        self._token = None
        form = urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": secrets.client_id,
                "client_secret": secrets.secret,
                "scope": "openid",
            }
        )
        reply = await self._send(
            env.oauth + OAUTH_PATH,
            form.encode("ascii"),
            {"Content-Type": "application/x-www-form-urlencoded"},
            expected=env.oauth,
            step="token",
        )
        try:
            data = json.loads(reply)
        except (ValueError, RecursionError):
            data = None
        value = data.get("access_token") if isinstance(data, dict) else None
        seconds = data.get("expires_in") if isinstance(data, dict) else None
        if (
            not isinstance(value, str)
            or _TOKEN.fullmatch(value) is None
            or not isinstance(seconds, int)
            or isinstance(seconds, bool)
            or not 1 <= seconds <= TOKEN_MAX_S
        ):
            raise LegiError(f"{UNAVAILABLE} : jeton PISTE illisible")
        self._token = _Token(env.name, value, self.now() + timedelta(seconds=seconds))
        return value

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.transport,
            trust_env=False,
            follow_redirects=False,
            timeout=self.timeout_s,
            limits=httpx.Limits(max_keepalive_connections=0),
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", "Accept": _JSON},
        )

    async def _send(
        self,
        url: str,
        content: bytes,
        headers: dict[str, str],
        *,
        expected: str,
        step: Step,
    ) -> bytes:
        """POST ``content`` to ``url``, whose host must be the ``expected`` one of its step: the
        secret goes to the token host only, the token to the API host only. No httpx exception
        is chained to the error raised, since its request holds the secret or the token."""
        outcome = await self._attempt(url, content, headers, expected, step)
        if isinstance(outcome, str):
            raise LegiError(f"{UNAVAILABLE} : {outcome}")
        return outcome

    async def _attempt(
        self, url: str, content: bytes, headers: dict[str, str], expected: str, step: Step
    ) -> bytes | str:
        try:
            target = check_url(url)
            allowed = target.host in HOSTS and target.host == httpx.URL(expected).host
            if target.scheme != "https" or not allowed:
                return "hôte non autorisé"
            async with self.throttle.slot(), asyncio.timeout(self.timeout_s):
                address = await pin(target, self.resolver)
                async with self._client() as client:
                    request = pinned_request(
                        client, target, address, headers, method="POST", content=content
                    )
                    response = await client.send(request, stream=True)
                    try:
                        return await self._body(response, step)
                    finally:
                        await response.aclose()
        except (TimeoutError, httpx.TimeoutException):
            return f"délai de {self.timeout_s:g} s dépassé"
        except FetchError as exc:
            return str(exc)
        except httpx.HTTPError:
            return "connexion impossible"

    async def _body(self, response: httpx.Response, step: Step) -> bytes | str:
        status = response.status_code
        if status == 401:
            self._token = None  # refused: the next call asks for a new one
        if status != 200:
            return _status_error(status, step)
        kind = response.headers.get("content-type", "").partition(";")[0].strip().lower()
        if kind not in (_JSON, ""):
            return "réponse qui n'est pas du JSON"
        return await read_body(response, self.max_bytes, cut=False)


def _status_error(status: int, step: Step = "api") -> str:
    if 300 <= status < 400:
        return "redirection inattendue"
    if status in (400, 404) and step == "token":
        return f"demande de jeton PISTE refusée (HTTP {status} : identifiants à vérifier)"
    if status in (400, 404):
        return f"requête refusée par Légifrance (HTTP {status})"
    if status == 401:
        return "identifiants ou jeton PISTE refusés (HTTP 401)"
    if status == 403:
        return "accès refusé (HTTP 403 : API non souscrite dans PISTE ?)"
    if status == 429:
        return "quota PISTE dépassé (HTTP 429), réessayer plus tard"
    if status >= 500:
        return f"service indisponible (HTTP {status})"
    return f"réponse HTTP {status} inattendue"
