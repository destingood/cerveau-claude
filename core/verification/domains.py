"""Registrable domains (offline public suffix list) and the outbound links of an answer.

Two sources are independent when their registrable domains differ: ``fr.wikipedia.org`` and
``en.wikipedia.org`` are one source, ``lemonde.fr`` and ``liberation.fr`` are two, and so are
``a.github.io`` and ``b.github.io`` (private suffixes of the list count). The public suffix list
is the snapshot bundled with tldextract: no network call.

A link is an exfiltration channel: its URL can carry data, and a Markdown image is fetched by the
renderer without any click. ``strip_foreign_links`` therefore removes every link or image whose
domain is not allowed (the verified sources and the URLs the user gave). A foreign image disappears;
a foreign link keeps its visible text; a bare foreign URL becomes ``(lien retiré)``. Links with
any other scheme (``javascript:``, ``data:``, relative paths) are removed the same way.

A domain match is not enough for a URL that carries data about the user: with ``exact_only``, a
URL in
which that pattern occurs survives only when it is one of the allowed URLs as is.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

import tldextract

REMOVED = "(lien retiré)"

_TLD = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)
_TITLE = r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?"
_INLINE = re.compile(
    r"(?P<image>!?)\[(?P<text>(?:[^\[\]]|\[[^\[\]]*\])*)\]"
    rf"\(\s*(?:<(?P<angled>[^<>\n]*)>|(?P<url>[^\s()]*(?:\([^\s()]*\)[^\s()]*)*)){_TITLE}\s*\)"
)
_DEFINITION = re.compile(
    rf"^[ \t]{{0,3}}\[(?P<label>[^\]\n]+)\]:[ \t]*"
    rf"(?:<(?P<angled>[^<>\n]*)>|<?(?P<url>[^\s>]*)>?){_TITLE}[ \t]*$\n?",
    re.MULTILINE,
)
_REFERENCE = re.compile(
    r"(?P<image>!?)\[(?P<text>(?:[^\[\]]|\[[^\[\]]*\])*)\]\[(?P<label>[^\]]*)\]"
)
_AUTOLINK = re.compile(r"<(?P<url>[a-z][a-z0-9+.-]{1,31}:[^\s<>]*)>", re.IGNORECASE)
_HTML_TAG = re.compile(
    r"</?(?:a|img|iframe|script|link|object|embed|source|video|audio|form|base|meta)\b[^>]*>",
    re.IGNORECASE,
)
_BARE = re.compile(
    r"(?:\b[a-z][a-z0-9+.-]{1,31}:)?//[^\s<>()\[\]\"'`]+|www\.[^\s<>()\[\]\"'`]+",
    re.IGNORECASE,  # www. even glued to a word
)
_TRAILING = ".,;:!?"
_MAX_PASSES = 5
_SCHEME = re.compile(r"[a-z][a-z0-9+.-]*:(?!\d)", re.IGNORECASE)  # not host:port
_HOST = re.compile(r"[a-z0-9_.-]+|[0-9a-f:.]+")  # a name (IDNA-encoded) or an IP literal


def registrable_domain(url: str) -> str | None:
    """``fr.wikipedia.org/wiki/x`` -> ``wikipedia.org``; an IP or a single-label host as is."""
    if "//" not in url:
        if _SCHEME.match(url):
            return None  # mailto:, javascript:, data: have no host
        url = f"//{url}"
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.rstrip(".")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    if not _HOST.fullmatch(host):
        return None
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    return _TLD(host).top_domain_under_public_suffix or host


def independent_domains(urls: Iterable[str]) -> list[str]:
    """Distinct registrable domains, in order of first appearance."""
    domains = (registrable_domain(url) for url in urls)
    return list(dict.fromkeys(d for d in domains if d))


@dataclass(frozen=True)
class LinkFilter:
    text: str
    removed_domains: tuple[str, ...]  # journal-safe: domains only, the URLs may carry data
    removed: int


class _Stripper:
    def __init__(self, allowed: Iterable[str], exact_only: re.Pattern[str] | None) -> None:
        urls = [url.strip() for url in allowed]
        self.allowed = set(independent_domains(urls))
        self.exact = set(urls)
        self.exact_only = exact_only
        self.removed: list[str] = []
        self.foreign_labels: set[str] = set()

    def is_allowed(self, url: str) -> bool:
        url = url.strip()
        web = url.lower().startswith(("http://", "https://", "//", "www."))
        # A backslash or a space is read differently by browsers and urlsplit: never allowed.
        if web and not re.search(r"[\\\s]", url):
            domain = registrable_domain(url)
            tainted = self.exact_only is not None and self.exact_only.search(url) is not None
            if domain in self.allowed and (not tainted or url in self.exact):
                return True
            self.removed.append(domain or "inconnu")
            return False
        try:
            scheme = urlsplit(url).scheme.lower()
        except ValueError:
            scheme = ""
        self.removed.append(scheme or "relatif")
        return False

    def definition(self, match: re.Match[str]) -> str:
        url = match.group("angled") if match.group("angled") is not None else match.group("url")
        if self.is_allowed(url):
            return match.group(0)
        self.foreign_labels.add(match.group("label").casefold())
        return ""

    def inline(self, match: re.Match[str]) -> str:
        url = match.group("angled") if match.group("angled") is not None else match.group("url")
        if self.is_allowed(url):
            return match.group(0)
        return "" if match.group("image") else match.group("text")

    def reference(self, match: re.Match[str]) -> str:
        label = (match.group("label") or match.group("text")).casefold()
        if label not in self.foreign_labels:
            return match.group(0)
        return "" if match.group("image") else match.group("text")

    def autolink(self, match: re.Match[str]) -> str:
        return match.group(0) if self.is_allowed(match.group("url")) else REMOVED

    def bare(self, match: re.Match[str]) -> str:
        url = match.group(0)
        tail = ""
        while url and url[-1] in _TRAILING:
            url, tail = url[:-1], url[-1] + tail
        return match.group(0) if self.is_allowed(url) else REMOVED + tail


def _strip_once(text: str, stripper: _Stripper) -> str:
    text = _HTML_TAG.sub("", text)
    text = _DEFINITION.sub(stripper.definition, text)
    text = _INLINE.sub(stripper.inline, text)
    if stripper.foreign_labels:
        text = _REFERENCE.sub(stripper.reference, text)
    text = _AUTOLINK.sub(stripper.autolink, text)
    return _BARE.sub(stripper.bare, text)


def strip_foreign_links(
    text: str, allowed_urls: Iterable[str], *, exact_only: re.Pattern[str] | None = None
) -> LinkFilter:
    """Remove raw HTML link and media tags, then every link whose domain is not allowed.

    A URL in which ``exact_only`` occurs must also be one of ``allowed_urls`` as is. A removal can
    bring two pieces together into a new link: the passes repeat until the text no longer changes.
    Past ``_MAX_PASSES``, every bracket goes, so that no Markdown link is left.
    """
    stripper = _Stripper(allowed_urls, exact_only)
    for _ in range(_MAX_PASSES):
        stripped = _strip_once(text, stripper)
        if stripped == text:
            break
        text = stripped
    else:
        text = _BARE.sub(stripper.bare, re.sub(r"[\[\]<>]", "", text))
    return LinkFilter(text, tuple(sorted(set(stripper.removed))), len(stripper.removed))
