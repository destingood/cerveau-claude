"""Closed list of hosts that a pack's web reading may reach (ADR-058, H6 of P5).

A pack whose domain has a list in ``config/data_sources.yaml#web_allowlists`` reads the web only
on those hosts: the MCP adapter refuses a ``web_read`` off the list before the call, the fetcher
checks every redirection again, and ``web_search`` drops the results off the list. The list comes
from the configuration, never from a model, a page or a manifest. A domain without a list keeps
the behaviour it had.

Matching is pure and strict: a host matches an entry when it is that entry or one of its
subdomains, both normalised the same way (IDNA, lower case, final dot removed). There is no
wildcard and no URL pattern; an IP address, a port or a path never matches.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

import httpx

# The variable through which the orchestrator hands a request's list to a plugin server that
# declares it in ``runtime.env``; the hosts, normalised, separated by commas.
ALLOWLIST_ENV = "CERVEAU_WEB_ALLOWLIST"
# The tools whose ``url`` argument the adapter checks against the list before the call.
READ_TOOLS = frozenset({"web_read"})
# The tools whose server must receive the list (redirections, search results): a plugin that
# publishes one of them without declaring ``ALLOWLIST_ENV`` is refused for a listed domain.
LISTED_TOOLS = READ_TOOLS | {"web_search"}
OFF_LIST_REFUSAL = "adresse hors de la liste de sites de ce domaine (ADR-058)"

_LABEL = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)")
_MAX_HOST_CHARS = 253
# A last label that inet_aton or the WHATWG URL rules read as a number (decimal or hexadecimal).
_NUMERIC_END = re.compile(r"[0-9]+|0x[0-9a-f]*")


class HostError(ValueError):
    """A list entry or a host that is not a plain DNS name."""


def normalise_host(raw: str) -> str:
    """The host as compared: IDNA (ASCII), lower case, without its final dot.

    Raises ``HostError`` for anything but a DNS name of two labels at least: a wildcard, a scheme,
    a port, a path, an IP address or an empty label.
    """
    text = raw.strip().lower().removesuffix(".")  # one final dot only
    host = text if text.isascii() else _idna(text, raw)
    labels = host.split(".")
    if (
        len(host) > _MAX_HOST_CHARS
        or len(labels) < 2
        or not all(_LABEL.fullmatch(label) for label in labels)
        or _NUMERIC_END.fullmatch(labels[-1])  # an IPv4 address, or a name a resolver may read so
    ):
        raise HostError(f"hôte invalide : {raw!r}")
    return host


def _idna(text: str, raw: str) -> str:
    """A non-ASCII name in IDNA 2008, as httpx encodes the host it connects to."""
    if any(mark in text for mark in "/:@?#[]"):  # a URL, not a name
        raise HostError(f"hôte invalide : {raw!r}")
    try:
        return httpx.URL(f"https://{text}/").raw_host.decode("ascii")
    except (httpx.InvalidURL, UnicodeError):
        raise HostError(f"hôte invalide : {raw!r}") from None


def normalise_list(entries: Iterable[str]) -> frozenset[str]:
    """The entries of a list, each normalised; ``HostError`` on the first invalid one."""
    return frozenset(normalise_host(entry) for entry in entries)


def host_allowed(host: str, allowlist: frozenset[str]) -> bool:
    """True when ``host`` is an entry of ``allowlist`` (normalised) or a subdomain of one."""
    try:
        name = normalise_host(host)
    except HostError:
        return False
    labels = name.split(".")
    return any(".".join(labels[i:]) in allowlist for i in range(len(labels) - 1))


def url_allowed(url: str, allowlist: frozenset[str]) -> bool:
    """True for an http(s) URL, without credentials nor a port other than the scheme's, whose
    host is allowed. The URL is parsed as the fetcher parses it (httpx)."""
    try:
        parsed = httpx.URL(url)  # as sent: no stripping, the fetcher does none
        host = parsed.raw_host.decode("ascii")
    except (httpx.InvalidURL, TypeError, ValueError):
        return False
    if parsed.scheme not in {"http", "https"} or parsed.userinfo or parsed.port is not None:
        return False
    return host_allowed(host, allowlist)


def parse_env(value: str | None) -> frozenset[str] | None:
    """The list a plugin server received in ``ALLOWLIST_ENV``; ``None`` when there is none.

    A value that is set but holds no valid host is an empty list: nothing may be read, rather
    than everything.
    """
    if value is None:
        return None
    hosts: set[str] = set()
    for entry in value.split(","):
        try:
            hosts.add(normalise_host(entry))
        except HostError:
            continue
    return frozenset(hosts)


def to_env(allowlist: frozenset[str]) -> str:
    """The list as ``ALLOWLIST_ENV`` carries it: sorted, separated by commas."""
    return ",".join(sorted(allowlist))
