"""The allow-list of the feeds: shipped empty (D18), strict, and blocking on unknown values (R7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from plugins.feeds.allowlist import ALLOWLIST_PATH, load_allowlist
from plugins.feeds.models import FeedError
from plugins.feeds.tests.support import FEED_URL, source

ROOT = Path(__file__).resolve().parents[3]

ENTRY = f"""  - id: exemple
    titre: Flux d'exemple
    url: {FEED_URL}
    licence: CC BY 4.0
    frequence: quotidienne
"""


def _write(tmp_path: Path, text: str | bytes) -> Path:
    path = tmp_path / "sources.yaml"
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def test_the_shipped_allow_list_is_empty() -> None:
    assert load_allowlist(ROOT / ALLOWLIST_PATH) == {}


def test_a_valid_list_is_keyed_by_identifier(tmp_path: Path) -> None:
    feeds = load_allowlist(_write(tmp_path, f"sources: []\nflux:\n{ENTRY}"))
    assert list(feeds) == ["exemple"]
    assert feeds["exemple"].url == FEED_URL
    assert feeds["exemple"].blocked() is None


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("flux: [", "liste blanche des flux illisible"),
        (b"flux: []\n# \xff\xfe", "liste blanche des flux illisible"),
        ("", "liste blanche des flux invalide (racine)"),
        ("sources: []\n", "liste blanche des flux invalide (flux)"),
        ("flux:\n  - id: exemple\n", "liste blanche des flux invalide (flux.0.titre)"),
        (f"flux:\n{ENTRY}{ENTRY}", "liste blanche des flux invalide (« exemple » en double)"),
        (f"flux:\n{ENTRY}    commentaire: non\n", "invalide (flux.0.commentaire)"),
    ],
)
def test_a_broken_list_refuses_every_read(tmp_path: Path, text: str | bytes, message: str) -> None:
    with pytest.raises(FeedError) as caught:
        load_allowlist(_write(tmp_path, text))
    assert message in str(caught.value)


def test_a_missing_or_unreadable_list_refuses_every_read(tmp_path: Path) -> None:
    with pytest.raises(FeedError, match="introuvable"):
        load_allowlist(tmp_path / "absent.yaml")
    with pytest.raises(FeedError, match="illisible"):
        load_allowlist(tmp_path)


@pytest.mark.parametrize(
    "url",
    [
        "http://feeds.example/research.xml",
        "ftp://feeds.example/research.xml",
        "https://user:pass@feeds.example/research.xml",
        "feeds.example/research.xml",
        "https:///research.xml",
    ],
)
def test_only_plain_https_urls_are_allowed(url: str) -> None:
    with pytest.raises(ValidationError):
        source(url=url)


@pytest.mark.parametrize("feed_id", ["Exemple", "-exemple", "ex_emple", "e" * 41, "", "../x"])
def test_identifiers_are_short_lowercase_slugs(feed_id: str) -> None:
    with pytest.raises(ValidationError):
        source(feed_id)


@pytest.mark.parametrize("field", ["licence", "titre", "url", "frequence"])
@pytest.mark.parametrize("mark", ["A_VERIFIER", "A_DEFINIR"])
def test_an_unknown_value_blocks_the_feed(field: str, mark: str) -> None:
    value = f"https://feeds.example/{mark}.xml" if field == "url" else f"{mark} (site)"
    reason = source(**{field: value}).blocked()
    assert reason == f"{field} à vérifier ou à définir dans la liste blanche (R7, R14)"
