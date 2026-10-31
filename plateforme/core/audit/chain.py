"""Hash-chained, append-only audit journal (R11, annex C.3).

Each line of the JSONL journal is one entry. ``hash`` is the SHA-256 of the
canonical JSON of the entry without its ``hash`` field, and ``prev_hash`` is
the ``hash`` of the previous entry, so any modification, deletion, insertion
or reordering breaks the chain. Truncating the tail is only detectable against
an external anchor (``seq:hash`` copied elsewhere), see ``verify(anchor=...)``.

Payloads are stored next to the journal, content-addressed by their own hash
(``payloads/<hex>.json``); the entry only carries ``payload_ref``.

Stdlib only: the Claude Code hooks import this module with whatever Python
runs them, before the project virtualenv exists.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

GENESIS_HASH = "sha256:" + "0" * 64
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

ACTORS = frozenset({"orchestrator", "risk_gate", "policy", "owner", "scheduler", "interface"})
EVENTS = frozenset(
    {"TOOL_CALL", "DECISION", "POLICY", "ORDER_STATE", "APPROVAL", "KILL", "CONFIG_CHANGE"}
    | {"ERROR", "FEEDBACK", "FORECAST"}  # ADR-011, ADR-064: what CERVEAU learns from
    | {"LEARNING"}  # ADR-065: the gate's verdicts, promotions and rollbacks
)
VERSION_KEYS = frozenset({"prompt", "model", "plugin", "config"})
ENTRY_KEYS = frozenset(
    {
        "seq",
        "ts",
        "prev_hash",
        "hash",
        "request_id",
        "actor",
        "event",
        "versions",
        "payload_ref",
        "redactions",
    }
)
MAX_REPORTED_ERRORS = 50


class AuditError(Exception):
    """Raised when the journal cannot be appended to safely."""


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON encoding used for every hash in the journal."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256_ref(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def entry_hash(entry: Mapping[str, Any]) -> str:
    """Hash of an entry, computed over every field except ``hash`` itself."""
    return sha256_ref(canonical_json({k: v for k, v in entry.items() if k != "hash"}))


def default_journal_path(project_root: Path) -> Path:
    override = os.environ.get("CERVEAU_AUDIT_JOURNAL")
    if override:
        return Path(override)
    return project_root / "var" / "audit" / "journal.jsonl"


@contextmanager
def _exclusive_lock(lock_path: Path) -> Iterator[None]:
    """OS-level exclusive lock, released by the OS if the process dies."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if sys.platform == "win32":
            import msvcrt

            # LK_LOCK retries for about 10 s, then raises OSError.
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _read_last_line(path: Path) -> bytes | None:
    """Last complete line of the file, read backwards (the journal can be large)."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        end = f.tell()
        f.seek(end - 1)
        if f.read(1) != b"\n":
            raise AuditError(
                f"{path} : la dernière ligne est incomplète, ajout refusé. "
                "Lancer `cerveau audit verify`."
            )
        pos = end
        chunk = 4096
        buf = b""
        while pos > 0:
            step = min(chunk, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step) + buf
            idx = buf.rfind(b"\n", 0, len(buf) - 1)
            if idx != -1:
                return buf[idx + 1 : -1]
        return buf[:-1]


@dataclass
class AuditJournal:
    path: Path

    @property
    def payload_dir(self) -> Path:
        return self.path.parent / "payloads"

    @property
    def lock_path(self) -> Path:
        return self.path.with_name(self.path.name + ".lock")

    def _store_payload(self, payload: Any) -> str:
        data = canonical_json(payload)
        ref = sha256_ref(data)
        target = self.payload_dir / (ref.removeprefix("sha256:") + ".json")
        if not target.exists():
            self.payload_dir.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, target)
        return ref

    def _tail(self) -> tuple[int, str]:
        raw = _read_last_line(self.path)
        if raw is None:
            return 0, GENESIS_HASH
        try:
            last = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuditError(f"{self.path} : dernière entrée illisible ({exc}).") from exc
        if not isinstance(last, dict) or entry_hash(last) != last.get("hash"):
            raise AuditError(
                f"{self.path} : la dernière entrée ne correspond pas à son hash, ajout refusé."
            )
        return int(last["seq"]), str(last["hash"])

    def append(
        self,
        *,
        actor: str,
        event: str,
        request_id: str | None = None,
        versions: Mapping[str, str] | None = None,
        payload: Any = None,
        redactions: Sequence[str] = (),
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if actor not in ACTORS:
            raise AuditError(f"acteur inconnu : {actor!r}")
        if event not in EVENTS:
            raise AuditError(f"événement inconnu : {event!r}")
        versions = dict(versions or {})
        unknown = set(versions) - VERSION_KEYS
        if unknown:
            raise AuditError(f"clés de version inconnues : {sorted(unknown)}")
        ts = (now or datetime.now()).astimezone().isoformat(timespec="milliseconds")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _exclusive_lock(self.lock_path):
            seq, prev_hash = self._tail()
            payload_ref = self._store_payload(payload) if payload is not None else None
            entry: dict[str, Any] = {
                "seq": seq + 1,
                "ts": ts,
                "prev_hash": prev_hash,
                "request_id": request_id or str(uuid.uuid4()),
                "actor": actor,
                "event": event,
                "versions": versions,
                "payload_ref": payload_ref,
                "redactions": list(redactions),
            }
            entry["hash"] = entry_hash(entry)
            line = canonical_json(entry) + b"\n"
            with self.path.open("ab") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        return entry

    def read_payload(self, payload_ref: str) -> Any:
        if not HASH_RE.match(payload_ref):
            raise AuditError(f"référence de payload invalide : {payload_ref!r}")
        target = self.payload_dir / (payload_ref.removeprefix("sha256:") + ".json")
        return json.loads(target.read_bytes())


@dataclass
class VerifyReport:
    path: Path
    entries: int = 0
    head_seq: int = 0
    head_hash: str = GENESIS_HASH
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, msg: str) -> None:
        if len(self.errors) < MAX_REPORTED_ERRORS:
            self.errors.append(msg)
        elif len(self.errors) == MAX_REPORTED_ERRORS:
            self.errors.append("… erreurs suivantes non affichées")


def parse_anchor(anchor: str) -> tuple[int, str]:
    """Parse an external anchor ``<seq>:sha256:<hex>`` as printed by ``cerveau audit head``."""
    seq_str, _, ref = anchor.partition(":")
    if not seq_str.isdigit() or not HASH_RE.match(ref):
        raise ValueError(f"ancre invalide : {anchor!r} (attendu <seq>:sha256:<64 hex>)")
    return int(seq_str), ref


def _check_shape(entry: Any, lineno: int, report: VerifyReport) -> bool:
    if not isinstance(entry, dict):
        report.error(f"ligne {lineno} : l'entrée n'est pas un objet JSON")
        return False
    keys = set(entry)
    if keys != ENTRY_KEYS:
        missing, extra = sorted(ENTRY_KEYS - keys), sorted(keys - ENTRY_KEYS)
        report.error(f"ligne {lineno} : champs manquants {missing}, champs en trop {extra}")
        return False
    ok = True
    if not isinstance(entry["seq"], int) or isinstance(entry["seq"], bool):
        report.error(f"ligne {lineno} : seq n'est pas un entier")
        ok = False
    for key in ("prev_hash", "hash"):
        if not isinstance(entry[key], str) or not HASH_RE.match(entry[key]):
            report.error(f"ligne {lineno} : {key} mal formé")
            ok = False
    if entry["actor"] not in ACTORS:
        report.error(f"ligne {lineno} : acteur inconnu {entry['actor']!r}")
        ok = False
    if entry["event"] not in EVENTS:
        report.error(f"ligne {lineno} : événement inconnu {entry['event']!r}")
        ok = False
    versions = entry["versions"]
    if not isinstance(versions, dict) or set(versions) - VERSION_KEYS:
        report.error(f"ligne {lineno} : versions mal formées")
        ok = False
    if not isinstance(entry["redactions"], list):
        report.error(f"ligne {lineno} : redactions doit être une liste")
        ok = False
    ref = entry["payload_ref"]
    if ref is not None and (not isinstance(ref, str) or not HASH_RE.match(ref)):
        report.error(f"ligne {lineno} : payload_ref mal formé")
        ok = False
    return ok


def verify(path: Path, anchor: str | None = None) -> VerifyReport:
    """Check the whole chain. Never raises on a corrupted journal: errors go in the report."""
    report = VerifyReport(path=path)
    journal = AuditJournal(path)
    if not path.exists():
        report.warnings.append(f"{path} absent : journal vide.")
        lines: list[bytes] = []
    else:
        data = path.read_bytes()
        if data and not data.endswith(b"\n"):
            report.error("dernière ligne incomplète (écriture interrompue ou troncature)")
        lines = data.split(b"\n")
        if lines and lines[-1] == b"":
            lines.pop()

    expected_prev = GENESIS_HASH
    expected_seq = 1
    prev_ts: datetime | None = None
    hashes_by_seq: dict[int, str] = {}
    for lineno, raw in enumerate(lines, start=1):
        if not raw.strip():
            report.error(f"ligne {lineno} : ligne vide")
            continue
        try:
            entry = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            report.error(f"ligne {lineno} : JSON illisible")
            continue
        if not _check_shape(entry, lineno, report):
            continue
        report.entries += 1
        if entry["seq"] != expected_seq:
            report.error(
                f"ligne {lineno} : seq {entry['seq']} au lieu de {expected_seq} "
                "(entrée supprimée, insérée ou déplacée)"
            )
        if entry["prev_hash"] != expected_prev:
            report.error(f"ligne {lineno} : prev_hash ne correspond pas à l'entrée précédente")
        recomputed = entry_hash(entry)
        if recomputed != entry["hash"]:
            report.error(f"ligne {lineno} (seq {entry['seq']}) : contenu modifié, hash invalide")
        try:
            ts = datetime.fromisoformat(entry["ts"])
            if ts.tzinfo is None:
                report.error(f"ligne {lineno} : ts sans fuseau horaire")
            elif prev_ts is not None and ts < prev_ts:
                report.warnings.append(f"ligne {lineno} : ts antérieur à l'entrée précédente")
            else:
                prev_ts = ts
        except (TypeError, ValueError):
            report.error(f"ligne {lineno} : ts illisible")
        ref = entry["payload_ref"]
        if ref is not None:
            target = journal.payload_dir / (ref.removeprefix("sha256:") + ".json")
            if not target.exists():
                report.error(f"ligne {lineno} : payload {ref} introuvable")
            elif sha256_ref(target.read_bytes()) != ref:
                report.error(f"ligne {lineno} : payload {ref} modifié")
        hashes_by_seq[entry["seq"]] = entry["hash"]
        expected_prev = entry["hash"]
        expected_seq = entry["seq"] + 1
        report.head_seq, report.head_hash = entry["seq"], entry["hash"]

    if anchor is not None:
        a_seq, a_hash = parse_anchor(anchor)
        if a_seq > report.head_seq:
            report.error(
                f"ancre seq {a_seq} au-delà de la fin du journal (seq {report.head_seq}) : "
                "journal tronqué"
            )
        elif hashes_by_seq.get(a_seq) != a_hash:
            report.error(f"l'entrée seq {a_seq} ne correspond pas à l'ancre externe")
    return report
