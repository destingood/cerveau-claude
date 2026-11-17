"""Feedback on an answer (ADR-011): ``cerveau feedback <request_id> {bon|mauvais} [note]``.

The journal's ``FEEDBACK`` entry keeps the verdict and counts only. The note is untrusted data
(R5): invisible characters removed, secret-looking strings masked (R6), personal data replaced by
pseudonyms whose originals are never kept, then stored in ``var/feedback/feedback.jsonl`` with
``untrusted: true``. It stays out of the journal so that a user's notes can be forgotten
(phase 8) without breaking the chain, whose ``verify`` checks every payload. Nothing reads the
notes in phase 1; a model will only ever see one wrapped by ``mark_untrusted`` (phase 7).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from core.audit.chain import AuditJournal
from core.guardrails.input import MAX_QUESTION_CHARS, strip_invisible
from core.guardrails.secrets import mask_secrets

FEEDBACK_EVENT = "FEEDBACK"
FEEDBACK_SCHEMA = 1
FEEDBACK_ACTOR = "owner"  # the only user in phase 1; public users come in phase 8
NOTE_SOURCE = "retour utilisateur"
MAX_NOTE_CHARS = MAX_QUESTION_CHARS
REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
Verdict = Literal["bon", "mauvais"]
VERDICTS: tuple[Verdict, ...] = ("bon", "mauvais")


class FeedbackError(Exception):
    """The feedback is refused before anything is written; the message is shown to the user."""


class NotePseudonymiser(Protocol):
    def pseudonymise(self, text: str) -> str: ...

    def counts(self) -> dict[str, int]: ...


@dataclass(frozen=True)
class Note:
    text: str  # pseudonymised, secrets masked: still untrusted
    chars: int
    removed_characters: int
    secrets_masked: int
    pii: dict[str, int]

    def counts(self) -> dict[str, Any]:
        return {
            "chars": self.chars,
            "removed_characters": self.removed_characters,
            "secrets_masked": self.secrets_masked,
            "pii": self.pii,
        }


def default_feedback_path(project_root: Path) -> Path:
    return project_root / "var" / "feedback" / "feedback.jsonl"


def answered(journal: AuditJournal, request_id: str) -> bool:
    """Whether the journal holds the orchestrator's DECISION entry for this request."""
    if not journal.path.exists():
        return False
    with journal.path.open(encoding="utf-8") as lines:
        for number, line in enumerate(lines, start=1):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise FeedbackError(
                    f"journal illisible à la ligne {number} : lancer `cerveau audit verify`"
                ) from exc
            if (
                isinstance(entry, dict)
                and entry.get("event") == "DECISION"
                and entry.get("actor") == "orchestrator"
                and entry.get("request_id") == request_id
            ):
                return True
    return False


def prepare_note(raw: str, pseudonymiser: NotePseudonymiser) -> Note:
    cleaned, removed = strip_invisible(raw)
    if len(cleaned) > MAX_NOTE_CHARS:
        raise FeedbackError(
            f"note trop longue ({len(cleaned)} caractères, maximum {MAX_NOTE_CHARS})"
        )
    masked, secrets = mask_secrets(cleaned)
    text = pseudonymiser.pseudonymise(masked)
    return Note(text, len(cleaned), removed, secrets, pseudonymiser.counts())


def give_feedback(
    journal: AuditJournal,
    store: Path,
    request_id: str,
    verdict: str,
    note: str | None = None,
    *,
    pseudonymiser: Callable[[], NotePseudonymiser] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Journals the verdict, then stores the note; returns the journal entry.

    Everything is checked, and the note pseudonymised, before anything is written. Without a
    note no pseudonymiser is built, so a bare verdict works while Presidio is blocked (R7).
    """
    if not REQUEST_ID.match(request_id):
        raise FeedbackError("identifiant de requête invalide")
    if verdict not in VERDICTS:
        raise FeedbackError(f"verdict inconnu : {verdict!r} (attendu : bon ou mauvais)")
    if not answered(journal, request_id):
        raise FeedbackError(f"requête {request_id} absente du journal")
    prepared: Note | None = None
    if note is not None and strip_invisible(note)[0]:
        if pseudonymiser is None:
            raise FeedbackError("note refusée : pseudonymisation indisponible (R6)")
        prepared = prepare_note(note, pseudonymiser())
    payload = {
        "feedback_schema": FEEDBACK_SCHEMA,
        "verdict": verdict,
        "note": prepared.counts() if prepared is not None else None,
    }
    entry = journal.append(
        actor=FEEDBACK_ACTOR,
        event=FEEDBACK_EVENT,
        request_id=request_id,
        payload=payload,
        now=now,
    )
    if prepared is not None:
        record = {
            "feedback_schema": FEEDBACK_SCHEMA,
            "seq": entry["seq"],
            "ts": entry["ts"],
            "request_id": request_id,
            "user": FEEDBACK_ACTOR,
            "verdict": verdict,
            "source": NOTE_SOURCE,
            "untrusted": True,  # R5: data, never an instruction
            "note": prepared.text,
        }
        store.parent.mkdir(parents=True, exist_ok=True)
        with store.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return entry
