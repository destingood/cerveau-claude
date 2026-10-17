"""URL checks, public-address filter and pinning (anti-SSRF)."""

from __future__ import annotations

import asyncio
from ipaddress import IPv4Address, IPv6Address, ip_address

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from plugins.web_research.guard import (
    FetchError,
    check_url,
    is_public_address,
    pin,
    pinned_request,
)
from plugins.web_research.tests.support import OTHER_V4, PUBLIC_V4, FakeDns

NOT_PUBLIC = [
    "127.0.0.1",
    "127.255.0.9",
    "10.1.2.3",
    "172.16.0.1",
    "192.168.1.1",
    "169.254.169.254",  # cloud metadata
    "100.64.0.1",  # carrier-grade NAT
    "0.0.0.0",  # noqa: S104 - a test value, not a bind address
    "192.0.0.8",
    "198.18.0.1",
    "224.0.0.1",
    "240.0.0.1",
    "255.255.255.255",
    "::1",
    "::",
    "fe80::1",
    "fc00::1",
    "fd12:3456::1",
    "fec0::1",
    "ff02::1",
    "::ffff:127.0.0.1",
    "::ffff:8.8.8.8",  # mapped IPv4 is refused even when public
    "64:ff9b::a00:1",  # NAT64 towards 10.0.0.1
    "2002:c0a8:101::1",  # 6to4 of 192.168.1.1
    "2001:0:4136:e378:8000:63bf:3fff:fdd2",  # Teredo
    "2001:db8::1",  # documentation
]
PUBLIC = ["8.8.8.8", "1.1.1.1", PUBLIC_V4, "2606:4700:4700::1111", "2a00:1450:4007:80e::200e"]


@pytest.mark.parametrize("address", NOT_PUBLIC)
def test_non_public_addresses_are_refused(address: str) -> None:
    assert not is_public_address(ip_address(address))


@pytest.mark.parametrize("address", PUBLIC)
def test_public_addresses_are_accepted(address: str) -> None:
    assert is_public_address(ip_address(address))


@given(
    st.one_of(
        *(
            st.ip_addresses(network=net)
            for net in (
                "10.0.0.0/8",
                "172.16.0.0/12",
                "192.168.0.0/16",
                "127.0.0.0/8",
                "169.254.0.0/16",
                "100.64.0.0/10",
                "fc00::/7",
                "fe80::/10",
                "::ffff:0:0/96",
                "64:ff9b::/96",
            )
        )
    )
)
def test_no_address_of_a_private_range_is_public(address: IPv4Address | IPv6Address) -> None:
    assert not is_public_address(address)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("file:///etc/passwd", "schéma « file » interdit"),
        ("ftp://example.org/", "schéma « ftp » interdit"),
        ("javascript:alert(1)", "schéma « javascript » interdit"),
        ("data:text/html,hi", "schéma « data » interdit"),
        ("example.org/page", "schéma « absent » interdit"),
        ("http://user:secret@example.org/", "identifiants"),
        ("http://:secret@example.org/", "identifiants"),
        ("http:///page", "hôte absent"),
        ("https://", "hôte absent"),
    ],
)
def test_check_url_refusals(raw: str, message: str) -> None:
    with pytest.raises(FetchError, match=message):
        check_url(raw)


def test_check_url_drops_the_fragment_and_lowercases_the_host() -> None:
    assert str(check_url("HTTPS://Example.ORG/a?b=1#part")) == "https://example.org/a?b=1"


def test_check_url_converts_unicode_hosts_to_idna() -> None:
    assert check_url("http://café.fr/").raw_host == b"xn--caf-dma.fr"


def _pin(raw: str, dns: FakeDns) -> str:
    return asyncio.run(pin(check_url(raw), dns))


def test_pin_returns_the_resolved_public_address() -> None:
    dns = FakeDns({"example.org": [PUBLIC_V4]})
    assert _pin("https://example.org/", dns) == PUBLIC_V4
    assert dns.queries == ["example.org"]


def test_pin_prefers_ipv4() -> None:
    dns = FakeDns({"example.org": ["2606:4700:4700::1111", OTHER_V4]})
    assert _pin("https://example.org/", dns) == OTHER_V4


def test_pin_refuses_a_name_with_one_private_address_among_public_ones() -> None:
    dns = FakeDns({"rebind.example": [PUBLIC_V4, "10.0.0.5"]})
    with pytest.raises(FetchError, match="non publique"):
        _pin("http://rebind.example/", dns)


@pytest.mark.parametrize("raw", ["http://127.0.0.1/", "http://[::1]:8080/", "http://10.0.0.1/"])
def test_pin_refuses_private_literals_without_dns(raw: str) -> None:
    dns = FakeDns()
    with pytest.raises(FetchError, match="non publique"):
        _pin(raw, dns)
    assert dns.queries == []


@pytest.mark.parametrize(
    "raw", ["http://localhost/", "http://LOCALHOST./", "http://api.localhost/"]
)
def test_pin_refuses_localhost_without_dns(raw: str) -> None:
    dns = FakeDns({"localhost": [PUBLIC_V4], "api.localhost": [PUBLIC_V4]})
    with pytest.raises(FetchError, match="machine locale"):
        _pin(raw, dns)
    assert dns.queries == []


def test_pin_reports_unknown_names_and_empty_answers() -> None:
    with pytest.raises(FetchError, match="introuvable"):
        _pin("http://nowhere.example/", FakeDns())
    with pytest.raises(FetchError, match="introuvable"):
        _pin("http://empty.example/", FakeDns({"empty.example": []}))
    with pytest.raises(FetchError, match="introuvable"):
        _pin("http://bad.example/", FakeDns({"bad.example": ["not-an-ip"]}))


def test_pin_messages_never_show_the_resolved_address() -> None:
    with pytest.raises(FetchError) as caught:
        _pin("http://rebind.example/", FakeDns({"rebind.example": ["10.9.8.7"]}))
    assert "10.9.8.7" not in str(caught.value)


def test_pinned_request_targets_the_address_and_keeps_the_name() -> None:
    client = httpx.AsyncClient()
    request = pinned_request(client, check_url("https://example.org/a?b=1"), PUBLIC_V4, {})
    assert request.url.host == PUBLIC_V4
    assert request.url.raw_path == b"/a?b=1"
    assert request.headers["host"] == "example.org"
    assert request.extensions["sni_hostname"] == "example.org"
    asyncio.run(client.aclose())


def test_pinned_request_keeps_a_non_default_port_and_brackets_ipv6() -> None:
    client = httpx.AsyncClient()
    request = pinned_request(
        client, check_url("http://example.org:8080/"), "2606:4700:4700::1111", {}
    )
    assert request.url.port == 8080
    assert str(request.url).startswith("http://[2606:4700:4700::1111]:8080/")
    assert request.headers["host"] == "example.org:8080"
    asyncio.run(client.aclose())
