"""Patterns of errors and feedback, and the challengers drafted from them (ADR-011, ADR-065).

Learning reads the journal only: ``ERROR`` entries and ``mauvais`` ``FEEDBACK`` verdicts, each tied
by its request to the pack its ``DECISION`` entry was routed to. Against poisoning (B78):

- each user counts for at most ``max_feedback_per_user`` verdicts (later ones are dropped);
- a pattern needs ``min_support`` distinct requests, and never fewer than two: one feedback alone
  changes nothing;
- a note is untrusted data (R5): a note with injection signals is set aside and counted, and no
  note text ever reaches a lesson. The offline drafter writes from counts only.

A challenger is a copy of a learned section with one lesson appended, written under
``var/learning/challengers/<id>/`` in the layout of ``learned/`` so that the prompt set can load it;
it changes nothing in service until the gate and ``promote`` (``core.learning.champion``) say so.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from core.audit.chain import AuditError, AuditJournal
from core.guardrails.injection import injection_signals
from core.learning.errors import ERROR_EVENT
from core.learning.feedback import FEEDBACK_EVENT
from core.learning.layer import LEARNED_DIR, check_section, read_section, write_section

MIN_SUPPORT_FLOOR = 2  # one feedback alone changes nothing, whatever the configuration
BAD = "mauvais"


class PatternError(ValueError):
    """The journal or the feedback store cannot be read for learning."""


@dataclass(frozen=True)
class Pattern:
    pack: str
    kind: str  # an ERROR kind, or "retour_mauvais"
    requests: int  # distinct requests
    users: int  # distinct users


@dataclass(frozen=True)
class Harvest:
    patterns: tuple[Pattern, ...]  # supported ones, most requests first
    below_support: int  # patterns seen on too few requests
    capped: int  # feedback verdicts beyond a user's cap
    notes_kept: int
    notes_set_aside: int  # notes with injection signals (R5)


class Drafter(Protocol):
    def __call__(self, pattern: Pattern) -> str: ...


LESSONS = {
    "task_failed": "Quand un outil échoue, le dire, donner ce qui manque et ne pas compléter "
    "sans source.",
    "verification": "Chaque chiffre cite l'outil qui l'a calculé et chaque citation sa source "
    "exacte ; sinon, marquer « à vérifier ».",
    "partial_answer": "Une réponse partielle annonce d'emblée ce qui manque et pourquoi.",
    "budget_exceeded": "Viser la réponse la plus courte qui répond, avec le moins d'appels "
    "d'outils.",
    "judge_score": "Relire la grille du pack avant de répondre : faits sourcés, estimations, "
    "hypothèses et opinions séparés.",
    "retour_mauvais": "Des réponses de ce domaine ont été jugées mauvaises : vérifier la "
    "question posée, les sources et les limites avant de conclure.",
}


def scripted_drafter(pattern: Pattern) -> str:
    """The offline drafter: a fixed lesson per kind, from counts only (never a note, R5)."""
    lesson = LESSONS.get(pattern.kind, "Vérifier la méthode du pack sur ce type de demande.")
    return f"- {lesson} (motif « {pattern.kind} », {pattern.requests} requêtes)"


def _entries(journal: AuditJournal) -> Iterator[tuple[dict[str, Any], Mapping[str, Any]]]:
    if not journal.path.exists():
        return
    with journal.path.open(encoding="utf-8") as lines:
        for number, line in enumerate(lines, start=1):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                raise PatternError(f"journal illisible à la ligne {number}") from None
            if not isinstance(entry, dict) or entry.get("event") not in (
                "DECISION",
                ERROR_EVENT,
                FEEDBACK_EVENT,
            ):
                continue
            ref = entry.get("payload_ref")
            try:
                payload = journal.read_payload(ref) if isinstance(ref, str) else {}
            except (AuditError, OSError, ValueError):
                raise PatternError(f"payload illisible à la ligne {number}") from None
            yield entry, payload if isinstance(payload, Mapping) else {}


def _notes(store: Path) -> tuple[int, int]:
    kept = aside = 0
    if not store.exists():
        return kept, aside
    with store.open(encoding="utf-8") as lines:
        for line in lines:
            try:
                note = json.loads(line).get("note")
            except (json.JSONDecodeError, AttributeError):
                raise PatternError("magasin de retours illisible") from None
            if isinstance(note, str) and injection_signals(note):
                aside += 1
            else:
                kept += 1
    return kept, aside


def harvest(
    journal: AuditJournal, store: Path, *, min_support: int, max_feedback_per_user: int
) -> Harvest:
    """The supported patterns of the journal, with what was dropped and why."""
    if min_support < 1 or max_feedback_per_user < 1:
        raise PatternError("min_support et max_feedback_per_user doivent valoir au moins 1")
    support = max(min_support, MIN_SUPPORT_FLOOR)
    packs: dict[str, str] = {}
    signals: list[tuple[str, str, str]] = []  # (request, kind, user)
    per_user: dict[str, int] = defaultdict(int)
    capped = 0
    for entry, payload in _entries(journal):
        request = entry.get("request_id")
        if not isinstance(request, str):
            continue
        event, user = entry["event"], str(entry.get("actor"))
        if event == "DECISION" and entry.get("actor") == "orchestrator":
            route = payload.get("route")
            if isinstance(route, Mapping) and isinstance(route.get("domain"), str):
                packs.setdefault(request, route["domain"])
        elif event == ERROR_EVENT and isinstance(payload.get("kind"), str):
            signals.append((request, payload["kind"], user))
        elif event == FEEDBACK_EVENT and payload.get("verdict") == BAD:
            per_user[user] += 1
            if per_user[user] > max_feedback_per_user:
                capped += 1
            else:
                signals.append((request, "retour_mauvais", user))
    groups: dict[tuple[str, str], tuple[set[str], set[str]]] = {}
    for request, kind, user in signals:
        if (pack := packs.get(request)) is None:
            continue  # a request without a routed decision teaches no pack
        requests, users = groups.setdefault((pack, kind), (set(), set()))
        requests.add(request)
        users.add(user)
    found = [Pattern(p, k, len(r), len(u)) for (p, k), (r, u) in groups.items()]
    kept = sorted(
        (p for p in found if p.requests >= support), key=lambda p: (-p.requests, p.pack, p.kind)
    )
    notes_kept, notes_aside = _notes(store)
    return Harvest(tuple(kept), len(found) - len(kept), capped, notes_kept, notes_aside)


def challenger_id(pattern: Pattern, lesson: str) -> str:
    digest = hashlib.sha256(f"{pattern.pack}\0{pattern.kind}\0{lesson}".encode()).hexdigest()
    return f"{pattern.pack}-{pattern.kind}-{digest[:12]}"


def propose(
    pattern: Pattern,
    challengers_dir: Path,
    *,
    drafter: Drafter = scripted_drafter,
    learned_dir: Path = LEARNED_DIR,
) -> Path:
    """Writes the challenger's learned directory (champion's lessons + one lesson); its path.

    The new section passes the same checks as the layer (R5); a lesson already present is refused.
    """
    lesson = check_section(drafter(pattern))
    current = read_section(pattern.pack, "lessons", learned_dir)
    if current is not None and lesson in current:
        raise PatternError("leçon déjà présente dans la couche apprise")
    text = check_section(f"{current}\n{lesson}" if current else lesson)
    root = challengers_dir / challenger_id(pattern, lesson)
    write_section(pattern.pack, "lessons", text, root)
    return root
