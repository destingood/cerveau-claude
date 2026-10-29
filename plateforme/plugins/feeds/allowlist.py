"""Allow-list of the feeds (D16): key ``flux`` of ``domain_packs/recherche/knowledge/sources.yaml``.

Only the user adds a feed, after checking the terms of use and the licence of its site (R14, R15);
the list stays empty until he does (D18). The URL is never given by the planner, who names a feed
by its identifier. An unknown value blocks (R7): a feed whose fields hold ``A_VERIFIER`` or
``A_DEFINIR`` is listed but cannot be read. The file is read at each call, so an edit applies to
the next request; a missing or invalid file refuses every read.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from core.net.guard import FetchError, check_url
from plugins.feeds.models import FeedError

# Relative to the working directory of the plugin process: the project root (ADR-015).
ALLOWLIST_PATH = Path("domain_packs") / "recherche" / "knowledge" / "sources.yaml"
FEED_ID = r"^[a-z0-9][a-z0-9-]{0,39}$"
UNKNOWN_MARKS = ("A_VERIFIER", "A_DEFINIR")


class FeedSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=FEED_ID)
    titre: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2_000)
    licence: str = Field(min_length=1, max_length=200)
    frequence: str = Field(min_length=1, max_length=100)

    @field_validator("url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        try:
            url = check_url(value)
        except FetchError as exc:
            raise ValueError(str(exc)) from None
        if url.scheme != "https":
            raise ValueError("URL refusée : https seulement")
        return value

    def blocked(self) -> str | None:
        """Why the feed cannot be read yet, or None."""
        for field, value in (
            ("licence", self.licence),
            ("titre", self.titre),
            ("url", self.url),
            ("frequence", self.frequence),
        ):
            if any(mark in value for mark in UNKNOWN_MARKS):
                return f"{field} à vérifier ou à définir dans la liste blanche (R7, R14)"
        return None


class _File(BaseModel):
    # The other keys (``sources``: corpus of the pack) are not the plugin's business.
    model_config = ConfigDict(extra="allow")

    flux: list[FeedSource]


def load_allowlist(path: Path = ALLOWLIST_PATH) -> Mapping[str, FeedSource]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FeedError("liste blanche des flux introuvable") from None
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        raise FeedError("liste blanche des flux illisible") from None
    try:
        feeds = _File.model_validate(raw).flux
    except ValidationError as exc:
        where = ".".join(str(part) for part in exc.errors()[0]["loc"]) or "racine"
        raise FeedError(f"liste blanche des flux invalide ({where})") from None
    by_id: dict[str, FeedSource] = {}
    for feed in feeds:
        if feed.id in by_id:
            raise FeedError(f"liste blanche des flux invalide (« {feed.id} » en double)")
        by_id[feed.id] = feed
    return by_id
