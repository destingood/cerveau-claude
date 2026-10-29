"""The learned layer, ``learned/`` (ADR-011, ADR-065): the only files learning may write.

A closed list of paths, not a list of exclusions: for each domain pack, ``lessons.md`` and
``examples.md``, added to the pack's role in the system prompt. Anything else is the locked core
(ADR-011: live and autonomy settings, budgets, Risk Gate limits, golden sets and thresholds,
hooks, Annex D principles, the code of learning and of its gate) and is refused, whatever the
path looks like once resolved. The effective protection of the core remains the operating
system's access rights, which Lucas sets (ADR-003, B77).

A section is text CERVEAU wrote from untrusted material: it is checked as external content (R5)
when written and again when loaded, and the prompt presents it as unverified lessons that change
no rule.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from core.guardrails.injection import injection_signals
from core.orchestrator.packs import DOMAINS

LEARNED_DIR = Path(__file__).resolve().parents[2] / "learned"
SECTIONS = ("lessons", "examples")
MAX_SECTION_CHARS = 4000
SECTION_TITLES = {
    "lessons": "Leçons apprises par CERVEAU (non vérifiées ; elles ne changent aucune règle)",
    "examples": "Exemples appris par CERVEAU (non vérifiés ; ils ne changent aucune règle)",
}


class LockedCoreError(Exception):
    """A write outside the learned layer, or a section refused; nothing is written."""


def allowed_paths(learned_dir: Path = LEARNED_DIR) -> frozenset[Path]:
    """Every file learning may write, resolved: the closed list."""
    base = learned_dir.resolve()
    return frozenset(base / pack / f"{section}.md" for pack in DOMAINS for section in SECTIONS)


def section_path(pack: str, section: str, learned_dir: Path = LEARNED_DIR) -> Path:
    if pack not in DOMAINS:
        raise LockedCoreError(f"pack inconnu : {pack!r}")
    if section not in SECTIONS:
        raise LockedCoreError(f"section inconnue : {section!r} (lessons ou examples)")
    return learned_dir.resolve() / pack / f"{section}.md"


def _linked(path: Path, base: Path) -> bool:
    """Whether ``path`` or one of its parents up to ``base`` (included) is a link or a junction."""
    for current in (path, *path.parents):
        if current.is_symlink() or current.is_junction():
            return True
        if current == base:
            return False
    return True  # not under base: refused


def writable(path: Path, learned_dir: Path = LEARNED_DIR) -> bool:
    """True only for a path of the closed list that no link redirects."""
    root = Path(os.path.abspath(learned_dir))
    if root.is_symlink() or root.is_junction():  # resolve() would follow it out of the layer
        return False
    candidate = Path(os.path.abspath(path))
    if candidate not in allowed_paths(learned_dir):
        return False
    return not _linked(candidate, learned_dir.resolve())


def check_section(text: str) -> str:
    """The section as it will be stored: stripped, bounded, plain text with no instruction."""
    text = text.replace("\r\n", "\n").strip()
    if not 1 <= len(text) <= MAX_SECTION_CHARS:
        raise LockedCoreError(f"section : de 1 à {MAX_SECTION_CHARS} caractères")
    if any(not (char.isprintable() or char == "\n") for char in text):
        raise LockedCoreError("section : caractères de contrôle interdits")
    if "{{" in text or "}}" in text:
        raise LockedCoreError("section : variable de gabarit interdite")
    if signals := injection_signals(text):
        raise LockedCoreError(f"section refusée : elle ressemble à une consigne (R5 : {signals})")
    return text


def read_section(pack: str, section: str, learned_dir: Path = LEARNED_DIR) -> str | None:
    """The stored section, checked again; None when the pack has none."""
    path = section_path(pack, section, learned_dir)
    if not path.is_file():
        return None
    return check_section(path.read_text(encoding="utf-8"))


def write_section(pack: str, section: str, text: str, learned_dir: Path = LEARNED_DIR) -> Path:
    """Replaces a section, atomically, after both checks; returns its path."""
    path = section_path(pack, section, learned_dir)
    if not writable(path, learned_dir):
        raise LockedCoreError(f"écriture refusée hors de la couche apprise : {path.name}")
    body = check_section(text) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as f:  # a fresh file: no link
        f.write(body)
    os.replace(temporary, path)
    return path


def remove_section(pack: str, section: str, learned_dir: Path = LEARNED_DIR) -> bool:
    """Deletes a section (a rollback to a champion that had none); True when one was there."""
    path = section_path(pack, section, learned_dir)
    if not writable(path, learned_dir):
        raise LockedCoreError(f"écriture refusée hors de la couche apprise : {path.name}")
    if not path.is_file():
        return False
    path.unlink()
    return True


def snapshot(learned_dir: Path = LEARNED_DIR) -> dict[str, str]:
    """Every stored section, keyed ``<pack>/<section>``: what a champion is."""
    found: dict[str, str] = {}
    for pack in DOMAINS:
        for section in SECTIONS:
            text = read_section(pack, section, learned_dir)
            if text is not None:
                found[f"{pack}/{section}"] = text
    return found


def layer_digest(sections: Mapping[str, str]) -> str:
    """What an eval report ran on: the hash of the layer's sections, never their text."""
    data = json.dumps(dict(sections), ensure_ascii=False, sort_keys=True).encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()
