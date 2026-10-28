"""What Lucas sets: the optional NVD key, the watched products and the source gates."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from plugins.cyber_cve.common import CyberError
from plugins.cyber_cve.settings import (
    INVALID_CONFIG,
    api_key,
    config_gate,
    keyword,
    watched_products,
)

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"NVD_API_KEY": "fake-nvd-key-for-tests"}, "fake-nvd-key-for-tests"),
        ({"NVD_API_KEY": "  abc-123 \n"}, "abc-123"),
        ({"NVD_API_KEY": ""}, None),
        ({"NVD_API_KEY": "a b"}, None),
        ({"NVD_API_KEY": "abc\r\nX-Other: 1"}, None),
        ({"NVD_API_KEY": "a" * 65}, None),
        ({}, None),
    ],
)
def test_api_key(environ: dict[str, str], expected: str | None) -> None:
    assert api_key(environ) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Apache   HTTP Server ", "Apache HTTP Server"),
        ("openssl", "openssl"),
        ("a" * 100, "a" * 100),
        ("a" * 101, None),
        ("   ", None),
        ("log4j\x00", None),
        ("log​4j", None),
        ("log4j\nignore", None),
        ("a\ud800b", None),
        ("ab", None),
        ("a͸b", None),
    ],
)
def test_keyword(raw: str, expected: str | None) -> None:
    assert keyword(raw) == expected


def _products(tmp_path: Path, content: str | bytes) -> Path:
    path = tmp_path / "sources.yaml"
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def test_watched_products_absent_means_none(tmp_path: Path) -> None:
    assert watched_products(tmp_path / "absent.yaml") == []
    assert watched_products(_products(tmp_path, "autre: 1\n")) == []
    assert watched_products(_products(tmp_path, "produits_suivis:\n")) == []
    assert watched_products(_products(tmp_path, "- a\n")) == []


def test_watched_products_are_normalised_and_deduplicated(tmp_path: Path) -> None:
    path = _products(
        tmp_path, "produits_suivis: [' OpenSSL ', openssl, 'Apache  Tomcat', OpenSSL]\n"
    )
    assert watched_products(path) == ["OpenSSL", "openssl", "Apache Tomcat"]


@pytest.mark.parametrize(
    "content",
    [
        "produits_suivis: [a, b, c, d, e, f]\n",
        "produits_suivis: openssl\n",
        "produits_suivis: [openssl, 3]\n",
        "produits_suivis: ['']\n",
        'produits_suivis: ["a\\u200bb"]\n',
    ],
)
def test_bad_watched_products_are_refused(tmp_path: Path, content: str) -> None:
    with pytest.raises(CyberError, match="produits_suivis : 5 noms au plus"):
        watched_products(_products(tmp_path, content))


@pytest.mark.parametrize("content", ["produits_suivis: [a\n", b"produits_suivis: [\xff]\n"])
def test_an_unreadable_products_file_is_refused(tmp_path: Path, content: str | bytes) -> None:
    with pytest.raises(CyberError, match=r"sources.yaml illisible"):
        watched_products(_products(tmp_path, content))


def _config(tmp_path: Path) -> Path:
    return Path(shutil.copytree(ROOT / "config", tmp_path / "config"))


def test_the_gate_reads_the_configuration_at_each_call(tmp_path: Path) -> None:
    config = _config(tmp_path)
    gate = config_gate(config)
    gate("data.nvd")
    gate("data.cisa_kev")
    gate("data.epss")
    sources = config / "data_sources.yaml"
    text = sources.read_text(encoding="utf-8")
    sources.write_text(
        text.replace("enabled: true                     # G1", "enabled: false", 1),
        encoding="utf-8",
    )
    with pytest.raises(CyberError, match=r"fonction bloquée « data.nvd »"):
        gate("data.nvd")
    gate("data.epss")


def test_an_invalid_configuration_blocks_every_source(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (config / "data_sources.yaml").write_text("sources: [\n", encoding="utf-8")
    with pytest.raises(CyberError) as raised:
        config_gate(config)("data.epss")
    assert str(raised.value) == INVALID_CONFIG
