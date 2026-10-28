"""robots.txt parsing and matching (RFC 9309)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.net.robots import RobotsPolicy, normalise, parse_robots


def test_longest_match_wins() -> None:
    policy = parse_robots("User-agent: *\nDisallow: /docs/\nAllow: /docs/public/\n")
    assert not policy.allows("/docs/secret.html")
    assert policy.allows("/docs/public/page.html")
    assert policy.allows("/other")


def test_allow_wins_a_tie() -> None:
    policy = parse_robots("User-agent: *\nDisallow: /page\nAllow: /page\n")
    assert policy.allows("/page")


def test_wildcards_and_end_anchor() -> None:
    policy = parse_robots("User-agent: *\nDisallow: /*.pdf$\nDisallow: /tmp*/cache\n")
    assert not policy.allows("/files/report.pdf")
    assert policy.allows("/files/report.pdf?download=1")
    assert not policy.allows("/tmp42/cache/x")
    assert policy.allows("/tmp42/other")


def test_the_query_string_is_matched() -> None:
    policy = parse_robots("User-agent: *\nDisallow: /search?q=\n")
    assert not policy.allows("/search?q=test")
    assert policy.allows("/search")


def test_our_group_is_preferred_to_the_star_group() -> None:
    text = "User-agent: *\nDisallow: /\n\nUser-agent: cerveau\nDisallow: /private\n"
    policy = parse_robots(text)
    assert policy.allows("/public")
    assert not policy.allows("/private/x")


def test_groups_of_our_agent_are_merged_and_versions_ignored() -> None:
    text = (
        "User-agent: CERVEAU/0.1\nDisallow: /a\n\n"
        "User-agent: other\nDisallow: /b\n\n"
        "User-agent: Cerveau\nDisallow: /c\n"
    )
    policy = parse_robots(text)
    assert not policy.allows("/a")
    assert policy.allows("/b")
    assert not policy.allows("/c")


def test_several_agents_share_one_group() -> None:
    policy = parse_robots("User-agent: other\nUser-agent: cerveau\nDisallow: /x\n")
    assert not policy.allows("/x")


def test_star_group_applies_when_ours_is_absent() -> None:
    policy = parse_robots("User-agent: googlebot\nDisallow: /\n\nUser-agent: *\nDisallow: /y\n")
    assert policy.allows("/x")
    assert not policy.allows("/y")


def test_no_matching_group_allows_everything() -> None:
    assert parse_robots("User-agent: googlebot\nDisallow: /\n").allows("/x")
    assert parse_robots("").allows("/x")


def test_empty_disallow_allows_and_rules_outside_groups_are_ignored() -> None:
    assert parse_robots("Disallow: /\nUser-agent: *\nDisallow:\n").allows("/x")


def test_comments_bom_case_and_crlf_are_handled() -> None:
    text = chr(0xFEFF) + "USER-AGENT: * # all\r\nDISALLOW: /secret # hidden\r\n"
    policy = parse_robots(text)
    assert not policy.allows("/secret")
    assert policy.allows("/open")


def test_robots_txt_is_always_allowed() -> None:
    assert parse_robots("User-agent: *\nDisallow: /\n").allows("/robots.txt")
    assert RobotsPolicy.deny_everything().allows("/robots.txt")
    assert not RobotsPolicy.deny_everything().allows("/")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/a%62c", "/abc"),  # unreserved octet decoded
        ("/a%2fb", "/a%2Fb"),  # reserved octet kept, uppercased
        ("/café", "/caf%C3%A9"),  # non-ASCII encoded
        ("/a b", "/a%20b"),
        ("/foo/bar?baz=https://foo.bar", "/foo/bar?baz=https://foo.bar"),
    ],
)
def test_normalise(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


def test_encoded_and_plain_forms_match_each_other() -> None:
    policy = parse_robots("User-agent: *\nDisallow: /caf%C3%A9\nDisallow: /%7Euser\n")
    assert not policy.allows("/café")
    assert not policy.allows("/~user/page")


@given(st.text(max_size=300), st.text(max_size=80))
def test_matching_never_raises(text: str, path: str) -> None:
    assert isinstance(parse_robots(text).allows("/" + path), bool)


def test_a_shorter_match_after_a_longer_one_does_not_win() -> None:
    policy = parse_robots("User-agent: *\nDisallow: /docs/private\nAllow: /docs\n")
    assert not policy.allows("/docs/private/a")
    assert policy.allows("/docs/a")
