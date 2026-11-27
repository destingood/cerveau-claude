"""The rules a memory of the plugin passes before it leaves the reader (plan step B2, ADR-072).

Kept: an active memory (not archived, replaced or merged) of the user's own brain, valid today
(from ``meta.valid_from``, else its creation day, to ``meta.valid_to``, the end day included, as
``brainkit/temps.py`` counts), not set aside by the plugin as possibly poisoned
(``meta.a_verifier``, ``brainkit/garde.py``) and at least as trusted as
``memory.yaml › min_confidence``: these rules run at the read (``admit``). Two more run on each
memory about to leave the reader only, as they cost the most (``release``): no instruction-like
phrasing when its source is not the user (R5), and its secrets masked (R6) by the platform's own
pattern (``core.guardrails.secrets``).

Confidence comes from the source, as the plugin computes it (``brainkit/store.py``, ``confidence``):
``meta.conf`` when written, else 0.95 for « verifie », 0.9 for « utilisateur » and « obsidian »,
0.8 for « wiki », 0.7 for « claude », « mcp », « import » and unknown sources, 0.6 for « auto »,
0.5 for « deduit ». Levels: « eleve » from 0.85, « moyen » from 0.7, « faible » below. Importance
does not change it: an important memory is not truer; it only breaks ties in the ranking.
"""

from __future__ import annotations

import dataclasses
import unicodedata
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from core.config.loader import PERSONAL_DOMAIN, MemoryConfidence
from core.guardrails.injection import injection_signals
from core.guardrails.secrets import mask_secrets

TRUSTED_SOURCES = ("utilisateur", "verifie")  # brainkit/garde.py: what the user said himself
SOURCE_SCORES: Mapping[str, float] = {
    "utilisateur": 0.9,
    "verifie": 0.95,
    "obsidian": 0.9,
    "wiki": 0.8,
    "claude": 0.7,
    "mcp": 0.7,
    "import": 0.7,
    "auto": 0.6,
    "deduit": 0.5,
}
_SOURCE_ALIASES = {
    "user": "utilisateur",
    "dit": "utilisateur",
    "verified": "verifie",
    "verif": "verifie",
    "inference": "deduit",
    "suppose": "deduit",
}
DEFAULT_SCORE = 0.7
LEVELS: tuple[MemoryConfidence, ...] = ("faible", "moyen", "eleve")
HIGH, MEDIUM = 0.85, 0.7
FOREIGN_PREFIX = "c--"  # a friend's page of the shared brain (brainkit/commun.py): not the user's

# Why a memory was set aside, in the order the rules apply; shown by `cerveau memoire chercher`.
SET_ASIDE = {
    "illisible": "entrée illisible",
    "ami": "page d'un ami (cerveau commun)",
    "inactif": "archivé",
    "remplace": "remplacé ou fusionné",
    "hors_validite": "hors de sa période de validité",
    "a_verifier": "mis de côté par le plugin (a_verifier)",
    "confiance": "confiance sous le minimum",
}


def fold(text: str) -> str:
    """Lower case without accents (« Été » → « ete »)."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def day(value: object) -> str | None:
    """``AAAA-MM-JJ`` from a date or a timestamp, as the plugin reads it (``temps.day``)."""
    text = str(value or "")[:10]
    return text if len(text) == 10 and text[4] == "-" and text[7] == "-" else None


def normalise_source(value: object) -> str:
    source = fold(str(value or "claude")).strip()
    return _SOURCE_ALIASES.get(source, source or "claude")


def confidence_score(meta: Mapping[str, Any], source: str) -> float:
    written = meta.get("conf")
    if isinstance(written, int | float) and not isinstance(written, bool):
        return max(0.05, min(1.0, float(written)))
    return SOURCE_SCORES.get(source, DEFAULT_SCORE)


def level(score: float) -> MemoryConfidence:
    return "eleve" if score >= HIGH else "moyen" if score >= MEDIUM else "faible"


def _domain_list(value: object) -> list[str]:
    items = value if isinstance(value, list) else str(value or "").split(",")
    out: list[str] = []
    for item in items:
        domain = fold(str(item)).strip()
        if domain and domain not in out:
            out.append(domain)
    return out


def domains_of(
    node: Mapping[str, Any], meta: Mapping[str, Any], nodes: Mapping[str, Any]
) -> tuple[str, ...]:
    """Its own ``meta.domaine`` (every one listed), else its project's; a « perso » tag adds perso.

    The plugin keeps the first domain only (``temps.axes``); every one counts here, so that a
    memory listed under « perso » among others stays personal.
    """
    found = _domain_list(meta.get("domaine"))
    project = nodes.get(str(node.get("project") or ""))
    if not found and isinstance(project, dict) and isinstance(project.get("meta"), dict):
        found = _domain_list(project["meta"].get("domaine"))
    tags = node.get("tags")
    personal = isinstance(tags, list) and PERSONAL_DOMAIN in {fold(str(t)) for t in tags}
    if personal and PERSONAL_DOMAIN not in found:
        found.append(PERSONAL_DOMAIN)
    return tuple(found)


def _importance(value: Any) -> int:
    """1 to 5, 3 when unreadable (``store.clamp_importance``)."""
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return 3


@dataclass(frozen=True)
class Candidate:
    """A memory that passed the rules of the read: its text is the brain's, not yet checked."""

    id: str
    kind: str  # the plugin's type: feedback, fact, decision...
    title: str
    body: str
    source: str
    confidence: MemoryConfidence
    date: str | None  # last update, else creation
    valid_from: str | None
    expires: str | None  # last valid day (meta.valid_to), None: no end written
    domains: tuple[str, ...]
    importance: int
    tags: tuple[str, ...]


@dataclass(frozen=True)
class Memory(Candidate):
    """A memory that may leave the reader: checked for instructions, secrets masked."""

    masked: int = 0  # secrets masked in its title and body


def _candidate(
    nid: str, node: Any, nodes: Mapping[str, Any], today: str, floor: MemoryConfidence
) -> str | Candidate:
    """The candidate, or the key of the first rule that sets it aside."""
    if not isinstance(node, dict):
        return "illisible"
    if nid.startswith(FOREIGN_PREFIX):
        return "ami"
    meta = node.get("meta") if isinstance(node.get("meta"), dict) else {}
    if node.get("status", "active") != "active":
        return "inactif"
    if meta.get("superseded_by") or meta.get("merged_into"):
        return "remplace"
    start = day(meta.get("valid_from")) or day(node.get("created"))
    end = day(meta.get("valid_to"))
    if (start and today < start) or (end and end < today):
        return "hors_validite"
    if meta.get("a_verifier"):
        return "a_verifier"
    source = normalise_source(node.get("source"))
    confidence = level(confidence_score(meta, source))
    if LEVELS.index(confidence) < LEVELS.index(floor):
        return "confiance"
    tags = node.get("tags")
    return Candidate(
        id=nid,
        kind=str(node.get("type") or "fact"),
        title=str(node.get("title") or nid),
        body=str(node.get("body") or ""),
        source=source,
        confidence=confidence,
        date=day(node.get("updated")) or day(node.get("created")),
        valid_from=start,
        expires=end,
        domains=domains_of(node, meta, nodes),
        importance=_importance(node.get("importance", 3)),
        tags=tuple(str(t) for t in tags) if isinstance(tags, list) else (),
    )


def admit(
    nodes: Mapping[str, Any], today: date, floor: MemoryConfidence
) -> tuple[tuple[Candidate, ...], dict[str, int]]:
    """The candidates that pass the rules of the read, and how many each rule set aside."""
    kept: list[Candidate] = []
    aside: Counter[str] = Counter()
    iso = today.isoformat()
    for nid, node in nodes.items():
        verdict = _candidate(str(nid), node, nodes, iso, floor)
        if isinstance(verdict, Candidate):
            kept.append(verdict)
        else:
            aside[verdict] += 1
    return tuple(kept), dict(aside)


def release(candidate: Candidate) -> Memory | None:
    """The last two rules, run only on a memory about to leave the reader (they cost the most).

    ``None``: its text reads like an instruction and its source is not the user (R5). Otherwise
    the memory with its secrets masked (R6).
    """
    text = f"{candidate.title}\n{candidate.body}"
    if candidate.source not in TRUSTED_SOURCES and injection_signals(text):
        return None
    title, masked_title = mask_secrets(candidate.title)
    body, masked_body = mask_secrets(candidate.body)
    kept = {f.name: getattr(candidate, f.name) for f in dataclasses.fields(Candidate)}
    return Memory(**kept | {"title": title, "body": body, "masked": masked_title + masked_body})
