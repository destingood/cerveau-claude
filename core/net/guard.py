"""Network guard of the reader plugins: URL checks and pinning to public addresses (ADR-006).

A URL is accepted only with an ``http`` or ``https`` scheme, a host, no credentials and port 80
or 443: another port of a public address may still reach the administration of the box through
its own public IP (NAT loopback, B24). Its name is resolved and **every** address must be public;
the request then goes to the validated address itself, with the name kept for the ``Host``
header, the SNI and the certificate check. A DNS answer that changes between the check and the
connection (rebinding) therefore cannot reach another address.

Error messages reach the planner and the traces in clear: they never show a resolved address nor
the host (the models only see the masked form of an address Lucas gave, B67), and any value a
page controls (scheme of a redirect, headers) is shown only through ``shown`` (B66).
"""

from __future__ import annotations

import asyncio
import re
import socket
from collections.abc import Awaitable, Callable, Sequence
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network

import httpx

ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_PORTS = frozenset({80, 443})
_DEFAULT_PORTS = {"http": 80, "https": 443}
_TOKEN = re.compile(r"[a-z0-9/+.-]{1,40}")
# IPv6 global unicast. Everything outside it (mapped IPv4, NAT64, unique local, link local,
# site local, multicast) is refused before the finer checks below.
_GLOBAL_UNICAST_V6 = ip_network("2000::/3")

Resolver = Callable[[str, int], Awaitable[Sequence[str]]]


class FetchError(Exception):
    """A refused or failed read. The message is French and safe to show to the planner."""


def shown(value: str) -> str:
    """A value the page controls, as an error may show it: a short token, else a placeholder."""
    token = value.strip().lower()
    return token if _TOKEN.fullmatch(token) else "non standard"


def is_public_address(ip: IPv4Address | IPv6Address) -> bool:
    """True only for a globally routable unicast address (no loopback, private, link-local...)."""
    if not ip.is_global or ip.is_multicast:
        return False
    if isinstance(ip, IPv6Address):
        # 6to4 and Teredo embed an IPv4 address that may be private.
        return ip in _GLOBAL_UNICAST_V6 and ip.sixtofour is None and ip.teredo is None
    return True


async def system_resolver(host: str, port: int) -> Sequence[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def check_url(raw: str) -> httpx.URL:
    """Parsed URL without its fragment, or ``FetchError`` for anything but plain http(s)."""
    try:
        url = httpx.URL(raw)
    except (httpx.InvalidURL, TypeError, ValueError):
        raise FetchError("URL refusée : adresse invalide") from None
    if url.scheme not in ALLOWED_SCHEMES:
        scheme = shown(url.scheme) if url.scheme else "absent"
        raise FetchError(f"URL refusée : schéma « {scheme} » interdit (http ou https seulement)")
    if url.userinfo:
        raise FetchError("URL refusée : identifiants dans l'adresse")
    if not url.raw_host:
        raise FetchError("URL refusée : hôte absent")
    return url.copy_with(fragment=None)


def host_of(url: httpx.URL) -> str:
    """ASCII host (IDNA), as used for DNS, ``Host`` and SNI."""
    return url.raw_host.decode("ascii")


async def pin(url: httpx.URL, resolver: Resolver) -> str:
    """The address to connect to; every address of the host must be public."""
    host = host_of(url)
    try:
        addresses = [ip_address(host)]
    except ValueError:
        lowered = host.lower().rstrip(".")
        if lowered == "localhost" or lowered.endswith(".localhost"):
            raise FetchError("URL refusée : la machine locale (anti-SSRF)") from None
        port = url.port or _DEFAULT_PORTS[url.scheme]
        try:
            resolved = await resolver(host, port)
            addresses = [ip_address(a) for a in resolved]
        except (OSError, UnicodeError, ValueError):
            raise FetchError("URL refusée : nom introuvable") from None
    if not addresses:
        raise FetchError("URL refusée : nom introuvable")
    if not all(is_public_address(a) for a in addresses):
        raise FetchError("URL refusée : le nom mène à une adresse non publique (anti-SSRF)")
    # After the address checks, so that a local or private target keeps its own reason.
    if url.port is not None and url.port not in ALLOWED_PORTS:
        raise FetchError("URL refusée : port interdit (80 et 443 seulement, anti-SSRF)")
    # IPv4 first: it is reachable from more networks; the order is otherwise kept.
    return str(sorted(addresses, key=lambda a: a.version)[0])


def pinned_request(
    client: httpx.AsyncClient, url: httpx.URL, address: str, headers: dict[str, str]
) -> httpx.Request:
    """GET on ``address`` with the original name for ``Host``, SNI and certificate."""
    host = host_of(url)
    netloc = f"[{host}]" if ":" in host else host
    if url.port is not None:
        netloc = f"{netloc}:{url.port}"
    return client.build_request(
        "GET",
        url.copy_with(host=address),
        headers={**headers, "Host": netloc},
        extensions={"sni_hostname": host},
    )
