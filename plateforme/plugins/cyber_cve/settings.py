"""What Lucas sets for the tools: the optional NVD key, the watched products and the gates.

- ``NVD_API_KEY`` (G3) is read from the environment the adapter passes (``runtime.env``); a value
  that does not look like a key is ignored, and the key is never written anywhere.
- ``produits_suivis`` (G10) lives in ``domain_packs/cyber/knowledge/sources.yaml`` of the served
  project and is read at each call; its names go to the NVD as keywords, nothing else.
- Each source is called only while ``config/data_sources.yaml`` enables it (R7).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping
from pathlib import Path

import yaml

from core.config.loader import BlockedFeatureError, ConfigError, load_config
from plugins.cyber_cve.common import CyberError

KEY_ENV = "NVD_API_KEY"
SOURCES_FILE = Path("domain_packs") / "cyber" / "knowledge" / "sources.yaml"
MAX_PRODUCTS = 5
KEYWORD_MAX = 100
INVALID_CONFIG = "configuration invalide : lancer `cerveau config check`"
_KEY = re.compile(r"[A-Za-z0-9-]{1,64}")

Gate = Callable[[str], None]


def api_key(environ: Mapping[str, str]) -> str | None:
    value = environ.get(KEY_ENV, "").strip()
    return value if _KEY.fullmatch(value) else None


_REFUSED = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})


def keyword(raw: str) -> str | None:
    """``raw`` with its spaces normalised, or None if empty, too long or with a char that is a
    control, an invisible format char, a lone surrogate, a private use or an unassigned code."""
    if any(unicodedata.category(char) in _REFUSED for char in raw.replace(" ", "")):
        return None
    value = " ".join(raw.split())
    return value if 1 <= len(value) <= KEYWORD_MAX else None


def watched_products(path: Path) -> list[str]:
    """The ``produits_suivis`` list; an absent file or key means no product (G10)."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError, yaml.YAMLError):
        raise CyberError(f"{SOURCES_FILE.as_posix()} illisible") from None
    products = data.get("produits_suivis") if isinstance(data, dict) else None
    if products is None:
        return []
    names = (
        [keyword(p) if isinstance(p, str) else None for p in products]
        if isinstance(products, list)
        else [None]
    )
    if len(names) > MAX_PRODUCTS or None in names:
        raise CyberError(
            f"produits_suivis : {MAX_PRODUCTS} noms au plus, de 1 à {KEYWORD_MAX} caractères "
            "chacun, sans caractère de contrôle"
        )
    return list(dict.fromkeys(name for name in names if name))


def config_gate(directory: Path) -> Gate:
    """A check run before each source is called: the configuration is read again every time."""

    def gate(feature: str) -> None:
        try:
            load_config(directory).require(feature)
        except ConfigError:
            raise CyberError(INVALID_CONFIG) from None
        except BlockedFeatureError as exc:
            raise CyberError(str(exc)) from None

    return gate
