"""Identifiers, small parsers, the reply cache and the bounded GET of the three sources."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from plugins.cyber_cve import common
from plugins.cyber_cve.common import (
    USER_AGENT,
    CyberError,
    Fetcher,
    ResponseCache,
    cache_key,
    cve_id,
    cve_order,
    day,
    load_json,
    number,
    short,
    text,
    utcnow,
)
from plugins.cyber_cve.tests.support import FIXED_NOW, FakeApi, respond, static
from tests.net_doubles import PUBLIC_V4, FakeDns

TODAY = date(2026, 10, 27)
NVD = "https://services.nvd.nist.gov/rest/json/cves/2.0"
FULL_ID = re.compile(r"CVE-[0-9]{4}-[0-9]{4,19}")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CVE-2021-44228", "CVE-2021-44228"),
        ("  cve-2021-44228 ", "CVE-2021-44228"),
        ("CVE-1999-0001", "CVE-1999-0001"),
        ("CVE-2027-1234", "CVE-2027-1234"),
        ("CVE-2024-0001", "CVE-2024-0001"),
        ("CVE-2024-1234567", "CVE-2024-1234567"),
        ("CVE-1998-0001", None),
        ("CVE-2028-0001", None),
        ("CVE-2024-123", None),
        ("CVE-2024-01234", None),
        ("CVE-2021-44228x", None),
        ("CVE-2021-44228\n", "CVE-2021-44228"),
        ("CVE-2021-44228 CVE-2021-45046", None),
        ("CVE-２０２１-44228", None),
        ("GHSA-jfh8-c2jp-5v3q", None),
        ("", None),
    ],
)
def test_cve_id_accepts_only_canonical_identifiers(raw: str, expected: str | None) -> None:
    assert cve_id(raw, TODAY) == expected


@given(
    year=st.integers(1999, 2027),
    number_=st.one_of(
        st.integers(0, 9999).map(lambda n: f"{n:04d}"),
        st.integers(10_000, 10**19 - 1).map(str),
    ),
    lower=st.booleans(),
)
def test_every_valid_identifier_is_kept(year: int, number_: str, lower: bool) -> None:
    raw = f"CVE-{year}-{number_}"
    assert cve_id(raw.lower() if lower else raw, TODAY) == raw


@given(st.text(max_size=40))
def test_any_text_gives_none_or_a_canonical_identifier(raw: str) -> None:
    found = cve_id(raw, TODAY)
    assert found is None or FULL_ID.fullmatch(found) is not None


def test_cve_order_is_numeric() -> None:
    ids = ["CVE-2021-10000", "CVE-2020-99999", "CVE-2021-9999"]
    assert sorted(ids, key=cve_order) == ["CVE-2020-99999", "CVE-2021-9999", "CVE-2021-10000"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-26", date(2026, 10, 26)),
        ("2021-12-10T10:15:09.143", date(2021, 12, 10)),
        ("2026-02-30", None),
        ("26-10-2026", None),
        ("２０２６-10-26", None),
        (20261026, None),
        (None, None),
    ],
)
def test_day(value: object, expected: date | None) -> None:
    assert day(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.94358", 0.94358),
        (0.5, 0.5),
        (1, 1.0),
        ("1.0000001", None),
        (-0.1, None),
        (True, None),
        ("nan", None),
        (float("inf"), None),
        ("abc", None),
        (None, None),
    ],
)
def test_number_in_unit_range(value: object, expected: float | None) -> None:
    assert number(value, 0, 1) == expected


def test_text_cleans_and_clips() -> None:
    assert text("  a‮b\nc  ", 10) == ("ab c", False)
    assert text("abcdef", 4) == ("abc…", True)
    assert text(" ​ ", 10) is None
    assert text(42, 10) is None
    assert short("abcdef", 4) == "abc…"
    assert short(None, 4) is None


@pytest.mark.parametrize("body", [b"{", b"\xff", b"[" * 100_000], ids=["open", "bytes", "deep"])
def test_load_json_refuses_unreadable_bodies(body: bytes) -> None:
    with pytest.raises(CyberError, match="NVD : réponse illisible"):
        load_json(body, "NVD")


def test_cache_key_orders_the_parameters() -> None:
    first = cache_key(NVD, {"cveId": "CVE-2021-44228", "a": 1})
    assert first == cache_key(NVD, {"a": 1, "cveId": "CVE-2021-44228"})
    assert first == f"{NVD}?a=1&cveId=CVE-2021-44228"


# ---------------------------------------------------------------------------------------------
# The cache


def _cache(directory: Path, offset: timedelta = timedelta(0)) -> ResponseCache:
    return ResponseCache(directory, now=lambda: FIXED_NOW + offset)


def test_cache_returns_a_fresh_body(tmp_path: Path) -> None:
    _cache(tmp_path).put("k", b"body", FIXED_NOW)
    assert _cache(tmp_path, timedelta(hours=23, minutes=59)).get("k") == (b"body", FIXED_NOW)


@pytest.mark.parametrize("offset", [timedelta(hours=24), timedelta(seconds=-1)])
def test_cache_misses_outside_its_window(tmp_path: Path, offset: timedelta) -> None:
    _cache(tmp_path).put("k", b"body", FIXED_NOW)
    assert _cache(tmp_path, offset).get("k") is None


def test_cache_misses_a_changed_body(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.put("k", b"body", FIXED_NOW)
    (body_path,) = tmp_path.glob("*.body")
    body_path.write_bytes(b"other")
    assert cache.get("k") is None


@pytest.mark.parametrize(
    "meta",
    [
        {"key": "other", "read_at": "2026-10-27T09:30:00+00:00"},
        {"key": "k", "read_at": "2026-10-27T09:30:00"},
        {"key": "k", "read_at": "hier"},
        {"key": "k"},
        ["k"],
    ],
)
def test_cache_misses_a_bad_meta(tmp_path: Path, meta: Any) -> None:
    cache = _cache(tmp_path)
    cache.put("k", b"body", FIXED_NOW)
    (meta_path,) = tmp_path.glob("*.meta")
    if isinstance(meta, dict):
        meta = {**meta, "sha256": json.loads(meta_path.read_text())["sha256"]}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    assert cache.get("k") is None


def test_cache_drops_stale_entries_when_it_writes(tmp_path: Path) -> None:
    _cache(tmp_path).put("old", b"old", FIXED_NOW - timedelta(days=2))
    (tmp_path / "junk.meta").write_text("{", encoding="utf-8")
    _cache(tmp_path).put("new", b"new", FIXED_NOW)
    assert len(list(tmp_path.glob("*.body"))) == 1
    assert not (tmp_path / "junk.meta").exists()
    assert _cache(tmp_path).get("new") == (b"new", FIXED_NOW)


def test_cache_that_cannot_be_written_is_ignored(tmp_path: Path) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("x", encoding="utf-8")
    cache = _cache(blocked / "cache")
    cache.put("k", b"body", FIXED_NOW)
    assert cache.get("k") is None


def test_a_failed_write_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: object) -> None:
        raise OSError("disque plein")

    monkeypatch.setattr(common.os, "replace", refuse)
    cache = _cache(tmp_path)
    cache.put("k", b"body", FIXED_NOW)
    assert list(tmp_path.iterdir()) == []
    assert cache.get("k") is None


def test_utcnow_is_aware() -> None:
    assert utcnow().utcoffset() is not None


# ---------------------------------------------------------------------------------------------
# The fetcher


def _get(fetcher: Fetcher, params: dict[str, str | int] | None = None, **options: Any) -> Any:
    parse = options.pop("parse", lambda body: load_json(body, fetcher.label))
    return asyncio.run(fetcher.get(NVD, params or {"cveId": "CVE-2021-44228"}, parse, **options))


def test_a_request_is_pinned_and_announced(tmp_path: Path) -> None:
    api = static({"ok": True})
    read = _get(api.fetcher(tmp_path))
    assert read.value == {"ok": True}
    assert read.read_at == FIXED_NOW
    assert read.cached is False
    (request,) = api.requests
    assert request.url.host == PUBLIC_V4
    assert request.url.scheme == "https"
    assert request.url.params["cveId"] == "CVE-2021-44228"
    assert request.headers["host"] == "services.nvd.nist.gov"
    assert request.extensions["sni_hostname"] == "services.nvd.nist.gov"
    assert request.headers["user-agent"] == USER_AGENT
    assert request.headers["accept"] == "application/json"
    assert request.headers["accept-encoding"] == "gzip"
    assert api.dns.queries == ["services.nvd.nist.gov"]


def test_a_cached_reply_is_not_read_again(tmp_path: Path) -> None:
    api = static({"ok": True})
    cache = ResponseCache(tmp_path / "cache", now=lambda: FIXED_NOW)
    fetcher = api.fetcher(tmp_path, cache=cache)
    _get(fetcher)
    read = _get(fetcher)
    assert read.cached is True
    assert read.read_at == FIXED_NOW
    assert len(api.requests) == 1


def test_a_reply_that_does_not_parse_is_not_cached(tmp_path: Path) -> None:
    api = static(b"{")
    cache = ResponseCache(tmp_path / "cache", now=lambda: FIXED_NOW)
    fetcher = api.fetcher(tmp_path, cache=cache)
    for _ in range(2):
        with pytest.raises(CyberError, match="JSON invalide"):
            _get(fetcher)
    assert len(api.requests) == 2
    assert not (tmp_path / "cache").exists()


def test_a_reply_refused_by_keep_is_not_cached(tmp_path: Path) -> None:
    api = static({"totalResults": 0})
    cache = ResponseCache(tmp_path / "cache", now=lambda: FIXED_NOW)
    fetcher = api.fetcher(tmp_path, cache=cache)
    for _ in range(2):
        _get(fetcher, keep=lambda value: value["totalResults"] > 0)
    assert len(api.requests) == 2


def test_a_damaged_cached_copy_is_read_again(tmp_path: Path) -> None:
    api = static({"ok": True})
    cache = ResponseCache(tmp_path / "cache", now=lambda: FIXED_NOW)
    cache.put(cache_key(NVD, {"cveId": "CVE-2021-44228"}), b"{", FIXED_NOW)
    read = _get(api.fetcher(tmp_path, cache=cache))
    assert read.value == {"ok": True}
    assert read.cached is False
    assert len(api.requests) == 1


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (302, "NVD : redirection inattendue"),
        (403, "NVD : accès refusé (HTTP 403 : débit dépassé ou clé refusée)"),
        (404, "NVD : réponse HTTP 404 inattendue"),
        (429, "NVD : débit dépassé (HTTP 429), réessayer plus tard"),
        (503, "NVD : service indisponible (HTTP 503)"),
    ],
)
def test_status_errors(tmp_path: Path, status: int, message: str) -> None:
    with pytest.raises(CyberError) as raised:
        _get(static(b"", status).fetcher(tmp_path))
    assert str(raised.value) == message


def test_a_reply_that_is_not_json_is_refused(tmp_path: Path) -> None:
    api = FakeApi(lambda _: respond("<html/>", content_type="text/html"))
    with pytest.raises(CyberError, match="n'est pas du JSON"):
        _get(api.fetcher(tmp_path))


def test_an_unencodable_parameter_is_refused() -> None:
    with pytest.raises(CyberError, match="paramètre de requête illisible"):
        cache_key(NVD, {"keywordSearch": "a\ud800"})


def test_a_reply_without_media_type_is_read(tmp_path: Path) -> None:
    api = FakeApi(lambda _: respond(b"[]", content_type=None))
    assert _get(api.fetcher(tmp_path)).value == []


def test_a_reply_over_the_cap_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CyberError, match="NVD : page trop volumineuse"):
        _get(static(b"[" + b"0," * 100 + b"0]").fetcher(tmp_path, max_bytes=50))


@pytest.mark.parametrize(
    ("addresses", "message"),
    [
        (["10.0.0.7"], "adresse non publique (anti-SSRF)"),
        (["93.184.215.14", "127.0.0.1"], "adresse non publique (anti-SSRF)"),
        ([], "nom introuvable"),
    ],
)
def test_a_name_that_leads_to_a_private_address_is_refused(
    tmp_path: Path, addresses: list[str], message: str
) -> None:
    api = static({"ok": True})
    api.dns = FakeDns({"services.nvd.nist.gov": addresses})
    with pytest.raises(CyberError, match=re.escape(message)):
        _get(api.fetcher(tmp_path))
    assert api.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/rest/json/cves/2.0",
        "http://services.nvd.nist.gov/rest/json/cves/2.0",
        "https://services.nvd.nist.gov:8443/rest/json/cves/2.0",
        "https://services.nvd.nist.gov.example.org/x",
    ],
)
def test_only_the_three_hosts_over_https_are_reached(tmp_path: Path, url: str) -> None:
    api = static({"ok": True})
    with pytest.raises(CyberError, match="NVD : "):
        asyncio.run(api.fetcher(tmp_path).get(url, None, lambda body: body))
    assert api.requests == []


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (httpx.ReadTimeout("slow"), "NVD : délai de 15 s dépassé"),
        (httpx.ConnectError("refused"), "NVD : connexion impossible"),
    ],
)
def test_transport_errors(tmp_path: Path, error: Exception, message: str) -> None:
    def fail(_: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(CyberError) as raised:
        _get(FakeApi(fail).fetcher(tmp_path))
    assert str(raised.value) == message


def test_the_whole_request_has_a_deadline(tmp_path: Path) -> None:
    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return respond({})

    with pytest.raises(CyberError, match=r"NVD : délai de 0\.05 s dépassé"):
        _get(FakeApi(slow).fetcher(tmp_path, timeout_s=0.05))


def test_the_nvd_key_is_sent_and_kept_nowhere(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    key = "fake-nvd-key-for-tests"
    api = static({"ok": True})
    cache = ResponseCache(tmp_path / "cache", now=lambda: FIXED_NOW)
    fetcher = api.fetcher(tmp_path, cache=cache, headers={"apiKey": key})
    with caplog.at_level(logging.DEBUG):
        read = _get(fetcher)
    assert fetcher.keyed
    assert api.requests[0].headers["apikey"] == key
    assert key not in str(api.requests[0].url)
    assert key not in repr(read)
    assert key not in caplog.text
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert key.encode() not in path.read_bytes(), path


def test_an_error_message_never_holds_the_key(tmp_path: Path) -> None:
    key = "fake-nvd-key-for-tests"
    for status in (302, 403, 429, 500):
        with pytest.raises(CyberError) as raised:
            _get(static(b"", status).fetcher(tmp_path, headers={"apiKey": key}))
        assert key not in str(raised.value)
