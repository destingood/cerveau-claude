"""The PISTE client: hosts, token, statuses, cache, credentials kept out of every output (H4)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from plugins.legifrance import client as client_module
from plugins.legifrance.client import (
    ARTICLE_TTL,
    MAX_BYTES,
    TOKEN_MARGIN,
    UNAVAILABLE,
    Environment,
    PisteClient,
    Read,
    ResponseCache,
    _status_error,
    credentials,
    environment,
    stamp,
    utcnow,
)
from plugins.legifrance.legi import LegiError
from plugins.legifrance.tests.support import (
    CREDENTIALS,
    FAKE_ID,
    FAKE_SECRET,
    FAKE_TOKEN,
    FIXED_NOW,
    PRODUCTION,
    SANDBOX,
    STAMP,
    Piste,
    respond,
)
from tests.net_doubles import FakeDns

SECRETS = (FAKE_ID, FAKE_SECRET, FAKE_TOKEN)


def post(client: PisteClient, env: Environment = SANDBOX, **options: Any) -> Read:
    options.setdefault("lasting", False)
    return asyncio.run(client.post(env, "/consult/getArticle", {"id": "A"}, **options))


def fails(client: PisteClient, message: str, env: Environment = SANDBOX) -> None:
    with pytest.raises(LegiError, match=message) as caught:
        post(client, env)
    assert str(caught.value).startswith(UNAVAILABLE)
    assert not any(secret in str(caught.value) for secret in SECRETS)


def test_only_the_two_piste_environments_are_reachable() -> None:
    assert environment("https://api.piste.gouv.fr/dila/legifrance/lf-engine-app/") is PRODUCTION
    assert environment(SANDBOX.api + "/dila/legifrance/lf-engine-app") is SANDBOX
    for url in (None, "A_DEFINIR", "https://api.piste.gouv.fr", "http://api.piste.gouv.fr/x"):
        with pytest.raises(LegiError, match="ni l'adresse de production ni celle du bac à sable"):
            environment(url)


@pytest.mark.parametrize(
    ("environ", "found"),
    [
        ({"PISTE_CLIENT_ID": FAKE_ID, "PISTE_CLIENT_SECRET": FAKE_SECRET}, True),
        ({"PISTE_CLIENT_ID": f" {FAKE_ID} ", "PISTE_CLIENT_SECRET": FAKE_SECRET}, True),
        ({"PISTE_CLIENT_ID": FAKE_ID}, False),
        ({"PISTE_CLIENT_ID": FAKE_ID, "PISTE_CLIENT_SECRET": "a b"}, False),
        ({"PISTE_CLIENT_ID": "x" * 257, "PISTE_CLIENT_SECRET": FAKE_SECRET}, False),
        ({}, False),
    ],
)
def test_credentials_are_both_present_and_well_formed(environ: dict[str, str], found: bool) -> None:
    value = credentials(environ)
    assert (value is not None) is found
    if value is not None:
        assert (value.client_id, value.secret) == (FAKE_ID, FAKE_SECRET)
        assert FAKE_SECRET not in repr(value) and FAKE_ID not in repr(value)


def test_a_post_asks_a_token_then_calls_the_api_with_it(tmp_path: Path) -> None:
    piste = Piste().on("/consult/getArticle", {"article": None})
    read = post(piste.client(tmp_path))
    assert (read.value, read.cached, stamp(read.read_at)) == ({"article": None}, False, STAMP)
    token, call = piste.requests
    assert (token.method, token.headers["host"], token.url.path) == (
        "POST",
        "sandbox-oauth.piste.gouv.fr",
        "/api/oauth/token",
    )
    form = token.content.decode("ascii")
    assert "grant_type=client_credentials" in form and "scope=openid" in form
    assert f"client_secret={FAKE_SECRET}" in form
    assert call.headers["host"] == "sandbox-api.piste.gouv.fr"
    assert call.headers["authorization"] == f"Bearer {FAKE_TOKEN}"
    assert call.headers["content-type"] == "application/json"
    assert json.loads(call.content) == {"id": "A"}
    assert "CERVEAU-legifrance" in call.headers["user-agent"]


def test_the_token_is_reused_then_renewed_before_it_expires(tmp_path: Path) -> None:
    clock = [FIXED_NOW]
    piste = Piste().on("/consult/getArticle", {"article": None})
    client = piste.client(tmp_path, cached=False, now=lambda: clock[0])
    post(client)
    clock[0] += timedelta(seconds=3600) - TOKEN_MARGIN - timedelta(seconds=1)
    post(client)
    assert piste.tokens() == 1
    clock[0] += timedelta(seconds=1)
    post(client)
    assert piste.tokens() == 2
    post(client, PRODUCTION)  # a token of another environment is not reused
    assert piste.tokens() == 3


def test_a_401_drops_the_token_and_the_next_call_asks_again(tmp_path: Path) -> None:
    piste = Piste().on("/consult/getArticle", {}, status=401)
    client = piste.client(tmp_path, cached=False)
    fails(client, "identifiants ou jeton PISTE refusés")
    fails(client, "HTTP 401")
    assert piste.tokens() == 2


def test_a_refused_token_request_says_so(tmp_path: Path) -> None:
    piste = Piste(token=lambda _: respond({"error": "invalid_client"}, 401))
    fails(piste.client(tmp_path), "HTTP 401")
    assert piste.api_calls() == []


@pytest.mark.parametrize(
    "body",
    [
        b"{",
        [],
        {"expires_in": 3600},
        {"access_token": "a b", "expires_in": 3600},
        {"access_token": FAKE_TOKEN, "expires_in": "3600"},
        {"access_token": FAKE_TOKEN, "expires_in": True},
        {"access_token": FAKE_TOKEN, "expires_in": 0},
        {"access_token": FAKE_TOKEN, "expires_in": 86_401},
    ],
)
def test_an_unreadable_token_is_refused(tmp_path: Path, body: Any) -> None:
    piste = Piste(token=lambda _: respond(body))
    fails(piste.client(tmp_path), "jeton PISTE illisible")
    assert piste.api_calls() == []


def test_without_credentials_nothing_is_sent(tmp_path: Path) -> None:
    piste = Piste()
    client = piste.client(tmp_path, secrets=None)
    assert not client.configured and piste.client(tmp_path).configured
    fails(client, "identifiants PISTE absents ou mal formés")
    assert piste.requests == []


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (301, "redirection inattendue"),
        (400, "requête refusée par Légifrance"),
        (403, "API non souscrite"),
        (404, "HTTP 404"),
        (418, "réponse HTTP 418 inattendue"),
        (429, "quota PISTE dépassé"),
        (503, "service indisponible"),
    ],
)
def test_an_error_status_is_an_unavailable_source(
    tmp_path: Path, status: int, message: str
) -> None:
    piste = Piste().on("/consult/getArticle", {"detail": FAKE_SECRET}, status=status)
    fails(piste.client(tmp_path), message)


def test_every_status_has_a_message() -> None:
    assert _status_error(302) == "redirection inattendue"
    assert _status_error(401).endswith("(HTTP 401)")
    assert _status_error(400, "token").startswith("demande de jeton PISTE refusée")
    assert _status_error(404, "api").startswith("requête refusée par Légifrance")


def test_a_refused_token_request_names_its_step(tmp_path: Path) -> None:
    piste = Piste(token=lambda _: respond({"error": "invalid_client"}, 400))
    fails(piste.client(tmp_path), "demande de jeton PISTE refusée")
    assert piste.api_calls() == []


def test_each_step_reaches_only_its_own_host(tmp_path: Path) -> None:
    piste = Piste()
    client = piste.client(tmp_path)
    for url, expected, step in (
        (SANDBOX.api + "/api/oauth/token", SANDBOX.oauth, "token"),
        (SANDBOX.oauth + "/x", SANDBOX.api, "api"),
        (PRODUCTION.api + "/x", SANDBOX.api, "api"),
    ):
        with pytest.raises(LegiError, match="hôte non autorisé"):
            asyncio.run(client._send(url, b"{}", {}, expected=expected, step=step))  # type: ignore[arg-type]
    assert piste.requests == []


def test_no_network_error_stays_chained_to_the_message(tmp_path: Path) -> None:
    def timed_out(_: Any) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    piste = Piste(token=timed_out)
    with pytest.raises(LegiError, match="dépassé") as caught:
        post(piste.client(tmp_path))
    assert caught.value.__context__ is None and caught.value.__cause__ is None


def test_a_reply_that_is_not_json_is_refused(tmp_path: Path) -> None:
    piste = Piste()
    piste.routes["/consult/getArticle"] = lambda _: respond(b"<html>", content_type="text/html")
    fails(piste.client(tmp_path), "pas du JSON")
    piste.routes["/consult/getArticle"] = lambda _: respond(b"{", content_type=None)
    with pytest.raises(LegiError, match="JSON invalide"):
        post(piste.client(tmp_path))


def test_a_reply_too_large_is_refused(tmp_path: Path) -> None:
    piste = Piste().on("/consult/getArticle", {"x": "y" * 200})
    fails(piste.client(tmp_path, max_bytes=100), "trop volumineuse")
    assert MAX_BYTES == 2_000_000


def test_a_slow_or_broken_network_is_an_unavailable_source(tmp_path: Path) -> None:
    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        raise AssertionError("not reached")  # pragma: no cover - cut by the timeout

    piste = Piste()
    piste.routes["/consult/getArticle"] = slow  # type: ignore[assignment]
    fails(piste.client(tmp_path, timeout_s=0.05), "délai de 0.05 s dépassé")

    def broken(_: Any) -> httpx.Response:
        raise httpx.ConnectError("refused")

    piste.routes["/consult/getArticle"] = broken
    fails(piste.client(tmp_path), "connexion impossible")

    def timed_out(_: Any) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    piste.routes["/consult/getArticle"] = timed_out
    fails(piste.client(tmp_path), "dépassé")


def test_a_private_address_is_refused_by_the_network_guard(tmp_path: Path) -> None:
    piste = Piste(dns=FakeDns({"sandbox-oauth.piste.gouv.fr": ["10.0.0.1"]}))
    fails(piste.client(tmp_path), "adresse non publique")
    assert piste.requests == []


def test_a_host_outside_piste_is_never_called(tmp_path: Path) -> None:
    piste = Piste()
    rogue = Environment("rogue", "https://evil.example", "https://evil.example")
    fails(piste.client(tmp_path), "hôte non autorisé", rogue)
    plain = Environment("plain", "http://api.piste.gouv.fr", "http://oauth.piste.gouv.fr")
    fails(piste.client(tmp_path), "hôte non autorisé", plain)
    assert piste.requests == []


def test_a_reply_is_cached_and_served_without_a_request(tmp_path: Path) -> None:
    piste = Piste().on("/consult/getArticle", {"article": {"id": "x"}})
    post(piste.client(tmp_path))
    # Served from the cache: no credential needed.
    again = post(piste.client(tmp_path, secrets=None))
    assert (again.value, again.cached) == ({"article": {"id": "x"}}, True)
    assert stamp(again.read_at) == STAMP
    assert len(piste.requests) == 2
    lasting = post(piste.client(tmp_path), lasting=True)  # another cache
    assert not lasting.cached
    words = json.dumps({"id": "A"})
    for path in tmp_path.rglob("*.meta"):  # the digest of the request, never its words
        assert words not in path.read_text(encoding="utf-8")
        assert '"A"' not in path.read_text(encoding="utf-8")


def test_a_rejected_reply_is_not_cached(tmp_path: Path) -> None:
    piste = Piste().on("/consult/getArticle", {"article": None})
    post(piste.client(tmp_path), keep=lambda _: False)
    assert not post(piste.client(tmp_path)).cached


def test_a_damaged_cached_copy_is_read_again(tmp_path: Path) -> None:
    piste = Piste().on("/consult/getArticle", {"ok": 1})
    post(piste.client(tmp_path))
    for path in (tmp_path / "daily").glob("*.body"):
        path.write_bytes(b"{")
    for path in (tmp_path / "daily").glob("*.meta"):
        meta = json.loads(path.read_text(encoding="utf-8"))
        meta["sha256"] = __import__("hashlib").sha256(b"{").hexdigest()
        path.write_text(json.dumps(meta), encoding="utf-8")
    assert not post(piste.client(tmp_path)).cached


def test_the_cache_keeps_a_body_for_its_lifetime_only(tmp_path: Path) -> None:
    clock = [FIXED_NOW]
    cache = ResponseCache(tmp_path, ARTICLE_TTL, lambda: clock[0])
    cache.put("k", b"body", FIXED_NOW)
    assert cache.get("k") == (b"body", FIXED_NOW)
    assert cache.get("other") is None
    clock[0] += ARTICLE_TTL
    assert cache.get("k") is None
    clock[0] = FIXED_NOW - timedelta(seconds=1)  # read in the future: not trusted
    assert cache.get("k") is None


def test_a_tampered_or_foreign_entry_is_a_miss(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path, ARTICLE_TTL, lambda: FIXED_NOW)
    cache.put("k", b"body", FIXED_NOW)
    body, meta = cache._paths("k")
    body.write_bytes(b"other")
    assert cache.get("k") is None
    for change in ({"key": "z"}, {"read_at": "2026-10-27T09:30:00"}, {"read_at": "x"}):
        cache.put("k", b"body", FIXED_NOW)
        meta.write_text(json.dumps({**json.loads(meta.read_text()), **change}), encoding="utf-8")
        assert cache.get("k") is None
    meta.write_text("[]", encoding="utf-8")
    assert cache.get("k") is None


def test_putting_prunes_stale_and_broken_entries(tmp_path: Path) -> None:
    clock = [FIXED_NOW]
    cache = ResponseCache(tmp_path, timedelta(hours=1), lambda: clock[0])
    cache.put("old", b"1", FIXED_NOW)
    (tmp_path / "broken.meta").write_text("{", encoding="utf-8")
    (tmp_path / "naive.meta").write_text('{"read_at": "2026-10-27T09:30:00"}', encoding="utf-8")
    clock[0] += timedelta(hours=2)
    cache.put("new", b"2", clock[0])
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".body", ".meta"]


def test_a_cache_that_cannot_be_written_costs_only_a_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    ResponseCache(blocker / "cache", ARTICLE_TTL).put("k", b"1", FIXED_NOW)  # mkdir fails

    def refuse(*_: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(client_module.os, "replace", refuse)
    cache = ResponseCache(tmp_path / "c", ARTICLE_TTL, lambda: FIXED_NOW)
    cache.put("k", b"1", FIXED_NOW)
    assert cache.get("k") is None
    assert [p.name for p in (tmp_path / "c").iterdir()] == []  # no temporary file left


def test_no_credential_or_token_reaches_a_log_a_file_or_an_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    piste = Piste().on("/consult/getArticle", {"article": None})
    client = piste.client(tmp_path)
    post(client)
    post(client, lasting=True)
    piste.on("/consult/getArticle", {}, status=500)
    fails(piste.client(tmp_path, cached=False), "HTTP 500")
    assert not any(secret in caplog.text for secret in SECRETS)
    assert FAKE_TOKEN not in repr(client._token)
    for root, _, names in os.walk(tmp_path):
        for name in names:
            data = (Path(root) / name).read_bytes()
            assert not any(secret.encode() in data for secret in SECRETS), name


def test_the_clock_is_utc() -> None:
    assert utcnow().utcoffset() == timedelta(0)
    assert CREDENTIALS.client_id == FAKE_ID
