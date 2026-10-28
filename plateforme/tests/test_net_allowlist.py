"""Closed lists of web hosts (ADR-058): normalisation, matching and the variable of the plugins."""

from __future__ import annotations

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.net.allowlist import (
    HostError,
    host_allowed,
    normalise_host,
    normalise_list,
    parse_env,
    to_env,
    url_allowed,
)

LIST = normalise_list(["legifrance.gouv.fr", "Service-Public.gouv.fr."])
LABEL = st.from_regex(r"[a-z0-9]([a-z0-9-]{0,10}[a-z0-9])?", fullmatch=True)


@pytest.mark.parametrize(
    ("raw", "host"),
    [
        ("Legifrance.GOUV.fr", "legifrance.gouv.fr"),
        (" legifrance.gouv.fr. ", "legifrance.gouv.fr"),
        ("straße.de", "xn--strae-oqa.de"),  # IDNA 2008, as httpx connects
        ("xn--strae-oqa.de", "xn--strae-oqa.de"),
        ("ÉTAT.fr", "xn--tat-9la.fr"),  # lower case first, as httpx
    ],
)
def test_hosts_are_normalised_as_httpx_connects(raw: str, host: str) -> None:
    assert normalise_host(raw) == host


@pytest.mark.parametrize(
    "raw",
    [
        "*.gouv.fr",
        "fr",
        "",
        "legifrance..gouv.fr",
        "-a.fr",
        "a-.fr",
        "1.2.3.4",
        "a.0x7f",  # read as an IPv4 address by some resolvers
        "a.0x",
        "legifrance.gouv.fr..",  # one final dot only
        "[::1]",
        "a.fr:443",
        "https://a.fr",
        "a.fr/path",
        "u@a.fr",
        "é/x.fr",
        "é..fr",
        "ﬀ.de",  # refused by IDNA 2008
        "a" * 64 + ".fr",
        ".".join(["a" * 60] * 5),  # 304 characters
    ],
)
def test_anything_but_a_dns_name_is_refused(raw: str) -> None:
    with pytest.raises(HostError, match="hôte invalide"):
        normalise_host(raw)
    assert not host_allowed(raw, LIST)


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://www.legifrance.gouv.fr/codes/id/LEGITEXT000006070721", True),
        ("https://legifrance.gouv.fr/", True),
        ("http://entreprendre.service-public.gouv.fr/vosdroits/F1", True),
        ("https://LEGIFRANCE.GOUV.FR./a", True),
        ("https://legifrance.gouv.fr:443/", True),  # the scheme's own port
        ("https://legifrance.gouv.fr.evil.example/", False),
        ("https://evillegifrance.gouv.fr/", False),
        ("https://gouv.fr/", False),
        ("https://u@legifrance.gouv.fr/", False),
        ("https://legifrance.gouv.fr:8443/", False),
        ("ftp://legifrance.gouv.fr/", False),
        ("legifrance.gouv.fr/a", False),
        ("https://[::1]/", False),
        ("https://exa mple.fr/", False),
        ("https://\ufb00.de/", False),  # an IDNA 2008 refusal: not even parsed
        ("https://legifrance.gouv.fr:99999/", False),
        ("", False),
        ("https://legifrance.gouv.fr../", False),
        (" https://legifrance.gouv.fr/", False),  # checked as sent
    ],
)
def test_urls_are_matched_on_their_host_only(url: str, allowed: bool) -> None:
    assert url_allowed(url, LIST) is allowed


@pytest.mark.parametrize("host", ["straße.de", "ÉTAT.fr", "Bücher.example"])
def test_a_non_ascii_name_is_encoded_as_the_fetcher_encodes_it(host: str) -> None:
    assert normalise_host(host) == httpx.URL(f"https://{host}/").raw_host.decode("ascii")


def test_an_empty_list_allows_nothing() -> None:
    assert not url_allowed("https://legifrance.gouv.fr/", frozenset())


@given(st.lists(LABEL, min_size=0, max_size=3))
def test_every_subdomain_of_an_entry_is_allowed(prefix: list[str]) -> None:
    assert host_allowed(".".join([*prefix, "legifrance", "gouv", "fr"]), LIST)


@given(LABEL, st.sampled_from(["legifrance.gouv.fr", "service-public.gouv.fr"]))
def test_an_entry_glued_to_another_label_or_followed_by_one_is_refused(
    label: str, entry: str
) -> None:
    assert not host_allowed(label + entry, LIST)  # no dot: another name
    assert not host_allowed(f"{entry}.{label}", LIST)  # the entry is not the end of the name


@given(st.lists(LABEL, min_size=2, max_size=4), st.booleans(), st.booleans())
def test_case_and_the_final_dot_never_change_the_answer(
    labels: list[str], upper: bool, dot: bool
) -> None:
    host = ".".join(labels)
    variant = (host.upper() if upper else host) + ("." if dot else "")
    assert host_allowed(variant, LIST) is host_allowed(host, LIST)


def test_the_variable_carries_the_list_and_never_widens_it() -> None:
    assert parse_env(None) is None
    assert parse_env(to_env(LIST)) == LIST
    assert to_env(LIST) == "legifrance.gouv.fr,service-public.gouv.fr"
    assert parse_env("*.gouv.fr, ,legifrance.gouv.fr") == frozenset({"legifrance.gouv.fr"})
    assert parse_env(",") == frozenset()  # set but empty: nothing may be read
