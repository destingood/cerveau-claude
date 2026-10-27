"""Download of the pinned ATT&CK bundle and the one config line it writes (ADR-056): offline."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from core.config.loader import ConfigError, load_config
from core.cyber import fetch
from core.cyber.attack import AttackError
from core.cyber.fetch import (
    BUNDLE_HOST,
    SOURCES_FILE,
    USER_AGENT,
    Pin,
    bundle_url,
    git_blob_sha1,
    record_sha256,
    verify,
)
from tests.attack_bundle import COMMIT, VERSION, bundle
from tests.net_doubles import PUBLIC_V4, FakeDns, FakeWeb

ROOT = Path(__file__).resolve().parents[1]
PATH = f"/mitre-attack/attack-stix-data/{COMMIT}/enterprise-attack/enterprise-attack-20.0.json"
DIGEST = "ab" * 32


def pin_of(body: bytes) -> Pin:
    return Pin(commit=COMMIT, size=len(body), blob_sha1=git_blob_sha1(body))


def test_the_git_blob_name_is_the_one_git_gives() -> None:
    # `git hash-object` of an empty file and of "hello\n".
    assert git_blob_sha1(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert git_blob_sha1(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_the_pin_of_version_20_0() -> None:
    pin = fetch.PINS["20.0"]
    assert (pin.commit, pin.size, pin.blob_sha1) == (
        "20664a889568dce884a1dac0ec7b12ae3a199f51",
        55_271_014,
        "b39ce73c609d0f028841546e042ec16ffd7fe63f",
    )
    assert bundle_url("20.0", pin) == (
        "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/"
        "20664a889568dce884a1dac0ec7b12ae3a199f51/enterprise-attack/enterprise-attack-20.0.json"
    )


def test_only_the_pinned_body_is_accepted() -> None:
    body = bundle()
    pin = pin_of(body)
    assert verify(body, pin) == hashlib.sha256(body).hexdigest()
    with pytest.raises(AttackError, match="octets au lieu de"):
        verify(body + b" ", pin)
    same_size = body[:-1] + b"]" if body[-1:] != b"]" else body[:-1] + b"}"
    with pytest.raises(AttackError, match="empreinte différente"):
        verify(same_size, pin)


def serve(body: bytes, *, address: str = PUBLIC_V4) -> tuple[FakeWeb, FakeDns]:
    web = FakeWeb()
    web.page(BUNDLE_HOST, PATH, body, content_type="application/json")
    return web, FakeDns({BUNDLE_HOST: [address]})


def download(
    web: FakeWeb, dns: FakeDns, body: bytes, interrupt: Callable[[], None] | None = None
) -> bytes:
    transport = httpx.MockTransport(web)
    run = fetch.download(
        VERSION, pin_of(body), transport=transport, resolver=dns, interrupt=interrupt
    )
    return asyncio.run(run)


def test_the_bundle_is_read_from_github_only() -> None:
    body = bundle()
    web, dns = serve(body)
    assert download(web, dns, body) == body
    (request,) = web.requests
    assert request.url.host == PUBLIC_V4
    assert request.headers["host"] == BUNDLE_HOST
    assert request.headers["user-agent"] == USER_AGENT
    assert dns.queries == [BUNDLE_HOST]


@pytest.mark.parametrize("status", [404, 500, 302], ids=["404", "500", "302"])
def test_any_other_answer_is_refused(status: int) -> None:
    body = bundle()
    web, dns = serve(body)
    if status == 302:
        web.redirect(BUNDLE_HOST, PATH, "https://attack.example/bundle.json")
    else:
        web.page(BUNDLE_HOST, PATH, b"", status=status)
    with pytest.raises(AttackError, match=f"réponse HTTP {status}"):
        download(web, dns, body)
    assert len(web.requests) == 1  # no redirect followed


def test_a_private_address_is_refused_before_any_request() -> None:
    body = bundle()
    web, dns = serve(body, address="10.0.0.7")
    with pytest.raises(AttackError, match="téléchargement : "):
        download(web, dns, body)
    assert web.requests == []


@pytest.mark.parametrize(
    "url",
    ["https://attack.example/enterprise-attack-20.0.json", "http://raw.githubusercontent.com/x"],
    ids=["host", "scheme"],
)
def test_another_host_or_scheme_is_refused(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    body = bundle()
    web, dns = serve(body)
    monkeypatch.setattr(fetch, "bundle_url", lambda *_: url)
    with pytest.raises(AttackError, match="hôte non autorisé"):
        download(web, dns, body)
    assert (web.requests, dns.queries) == ([], [])


def test_a_body_too_large_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    body = bundle()
    web, dns = serve(body)
    monkeypatch.setattr(fetch, "MAX_BUNDLE_BYTES", 100)
    with pytest.raises(AttackError, match="trop volumineuse"):
        download(web, dns, body)


def test_a_body_larger_than_its_pin_stops_at_the_pinned_size() -> None:
    body = bundle()
    web, dns = serve(body + b" " * 10)
    with pytest.raises(AttackError, match="trop volumineuse"):
        download(web, dns, body)


def test_a_broken_connection_is_refused() -> None:
    body = bundle()
    web, dns = serve(body)

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    web.on(BUNDLE_HOST, PATH, broken)
    with pytest.raises(AttackError, match="connexion impossible"):
        download(web, dns, body)


def test_a_slow_download_is_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    body = bundle()
    web, dns = serve(body)

    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200)

    web.on(BUNDLE_HOST, PATH, slow)
    monkeypatch.setattr(fetch, "TIMEOUT_S", 0.05)
    with pytest.raises(AttackError, match="délai dépassé"):
        download(web, dns, body)


def test_an_interrupt_stops_the_download_between_chunks() -> None:
    body = bundle() + b" " * 200_000  # several chunks of 64 kio
    web, dns = serve(body)
    seen: list[int] = []

    def interrupt() -> None:
        seen.append(1)
        if len(seen) == 2:
            raise AttackError("kill switch")

    with pytest.raises(AttackError, match="kill switch"):
        download(web, dns, body, interrupt=interrupt)
    assert len(seen) == 2


def copy_config(tmp_path: Path, *, crlf: bool | None = None) -> Path:
    target = tmp_path / "config"
    shutil.copytree(ROOT / "config", target)
    if crlf is not None:
        path = target / SOURCES_FILE
        lf = path.read_bytes().replace(b"\r\n", b"\n")
        path.write_bytes(lf.replace(b"\n", b"\r\n") if crlf else lf)
    return target


@pytest.mark.parametrize("crlf", [False, True], ids=["lf", "crlf"])
def test_the_digest_replaces_the_marker_and_nothing_else(tmp_path: Path, crlf: bool) -> None:
    config = copy_config(tmp_path, crlf=crlf)
    path = config / SOURCES_FILE
    before = path.read_bytes()
    assert load_config(config).blockers("data.attack")
    record_sha256(config, DIGEST)
    after = path.read_bytes()
    changed = [
        (old, new)
        for old, new in zip(before.splitlines(True), after.splitlines(True), strict=True)
        if old != new
    ]
    newline = b"\r\n" if crlf else b"\n"
    assert changed == [
        (b"    sha256: A_VERIFIER" + newline, b"    sha256: " + DIGEST.encode() + newline)
    ]
    loaded = load_config(config)
    assert loaded.data_sources.sources["attack"].sha256 == DIGEST
    loaded.require("data.attack")
    assert [p.name for p in config.iterdir() if p.name.startswith(".tmp-")] == []


def test_a_comment_after_the_marker_is_kept(tmp_path: Path) -> None:
    config = copy_config(tmp_path, crlf=False)
    path = config / SOURCES_FILE
    path.write_bytes(
        path.read_bytes().replace(b"    sha256: A_VERIFIER\n", b"    sha256: A_VERIFIER  # G5\n")
    )
    record_sha256(config, DIGEST)
    assert b"    sha256: " + DIGEST.encode() + b"  # G5\n" in path.read_bytes()


def test_a_recorded_digest_is_never_replaced(tmp_path: Path) -> None:
    config = copy_config(tmp_path)
    record_sha256(config, DIGEST)
    path = config / SOURCES_FILE
    before = path.read_bytes()
    with pytest.raises(AttackError, match="introuvable"):
        record_sha256(config, "cd" * 32)
    assert path.read_bytes() == before


def test_only_the_attack_block_is_searched(tmp_path: Path) -> None:
    config = copy_config(tmp_path, crlf=False)
    path = config / SOURCES_FILE
    original = path.read_bytes()
    path.write_bytes(original.replace(b"  attack:\n", b"  attack_old:\n"))
    with pytest.raises(AttackError, match="source « attack » introuvable"):
        record_sha256(config, DIGEST)
    path.write_bytes(original.replace(b"    sha256: A_VERIFIER\n", b""))
    with pytest.raises(AttackError, match="introuvable"):
        record_sha256(config, DIGEST)


def test_an_invalid_digest_is_refused(tmp_path: Path) -> None:
    config = copy_config(tmp_path)
    before = (config / SOURCES_FILE).read_bytes()
    for digest in ("A" * 64, "ab" * 31, "ab" * 32 + "\n"):
        with pytest.raises(AttackError, match="SHA-256 invalide"):
            record_sha256(config, digest)
    assert (config / SOURCES_FILE).read_bytes() == before


def test_a_digest_not_read_back_restores_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = copy_config(tmp_path)
    before = (config / SOURCES_FILE).read_bytes()

    def broken(_: Path) -> None:
        raise ConfigError("broken")

    monkeypatch.setattr(fetch, "load_config", broken)
    with pytest.raises(AttackError, match="fichier restauré"):
        record_sha256(config, DIGEST)
    assert (config / SOURCES_FILE).read_bytes() == before
    assert [p.name for p in config.iterdir() if p.name.startswith(".tmp-")] == []
