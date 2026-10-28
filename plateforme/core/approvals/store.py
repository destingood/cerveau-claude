"""Approval requests and their states, ``var/approvals/approvals.db`` (ADR-035).

An N3 FINANCIERE intent waits for Lucas: the policy requests an approval, Lucas grants it with the
one-time code of his authenticator application, and the execution consumes it once, after the
Risk Gate has been evaluated again on fresh data. Three tables, insertion only, as for the order
book (ADR-032): the requests, their state transitions and every code attempt. Nothing is updated
or deleted, and the database itself refuses an illegal transition, a second request for the same
intent and a code step that does not exceed every step accepted before (RFC 6238 §5.2).

The state of a request is its last transition, or EXPIREE once its deadline has passed: the
deadline is read against an injected clock, never by a timer, and a write that meets an overdue
request records its expiry first.

Each transition, and each code attempt, writes an ``APPROVAL`` entry to the audit journal within
the same write: the request, the intent, the state and the reason, never the code. A journal that
refuses the entry leaves the store unchanged.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Any, Literal
from uuid import UUID

from core.approvals.totp import verify
from core.config.loader import Approval
from core.execution.book import Journal
from core.execution.uuid7 import uuid7
from core.finance.model import canonical_json, from_utc_text, plain_text, utc_text
from core.finance.schema import SchemaError, migrate, schema_version

REASON_CHARS = 200
SUMMARY_CHARS = 500
Environment = Literal["paper", "live"]
Actor = Literal["policy", "interface", "lucas"]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ApprovalState(StrEnum):
    DEMANDEE = "DEMANDEE"
    ACCORDEE = "ACCORDEE"
    REFUSEE = "REFUSEE"
    EXPIREE = "EXPIREE"
    CONSOMMEE = "CONSOMMEE"


OPEN = frozenset({ApprovalState.DEMANDEE, ApprovalState.ACCORDEE})
TRANSITIONS: Mapping[ApprovalState | None, frozenset[ApprovalState]] = {
    None: frozenset({ApprovalState.DEMANDEE}),
    ApprovalState.DEMANDEE: frozenset(
        {ApprovalState.ACCORDEE, ApprovalState.REFUSEE, ApprovalState.EXPIREE}
    ),
    ApprovalState.ACCORDEE: frozenset(
        {ApprovalState.CONSOMMEE, ApprovalState.REFUSEE, ApprovalState.EXPIREE}
    ),
}

_LAST_STATE = (
    "COALESCE((SELECT state FROM transitions WHERE approval_id = NEW.approval_id "
    "ORDER BY seq DESC LIMIT 1), '')"
)


def _immutable(table: str, noun: str) -> tuple[str, str]:
    """No UPDATE and no DELETE on ``table``: the store only grows (R11)."""
    return (
        f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} : {noun} ne se modifie pas'); END",
        f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} : {noun} ne se supprime pas'); END",
    )


def _allowed_rows() -> str:
    pairs = [
        f"('{'' if source is None else source.value}', '{target.value}')"
        for source, targets in TRANSITIONS.items()
        for target in sorted(targets)
    ]
    return ", ".join(pairs)


MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
            """CREATE TABLE requests (
                approval_id TEXT PRIMARY KEY,
                intent_id TEXT NOT NULL UNIQUE,
                intent_sha256 TEXT NOT NULL CHECK (length(intent_sha256) = 64),
                environment TEXT NOT NULL CHECK (environment IN ('paper', 'live')),
                gate TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL CHECK (expires_at > created_at)
            ) STRICT""",
            *_immutable("requests", "une demande"),
            # The state machine of ADR-035, '' being the state before the first transition.
            """CREATE TABLE allowed_transitions (
                from_state TEXT NOT NULL,
                to_state TEXT NOT NULL,
                PRIMARY KEY (from_state, to_state)
            ) STRICT, WITHOUT ROWID""",
            # Only this module's constants, never an input.
            "INSERT INTO allowed_transitions (from_state, to_state) VALUES "  # noqa: S608
            + _allowed_rows(),
            """CREATE TRIGGER allowed_transitions_no_insert BEFORE INSERT ON allowed_transitions
            BEGIN
                SELECT RAISE(ABORT, 'allowed_transitions : la machine à états ne change pas');
            END""",
            *_immutable("allowed_transitions", "la machine à états"),
            """CREATE TABLE transitions (
                approval_id TEXT NOT NULL REFERENCES requests (approval_id),
                seq INTEGER NOT NULL CHECK (seq >= 1),
                state TEXT NOT NULL,
                reason TEXT NOT NULL,
                actor TEXT NOT NULL CHECK (actor IN ('policy', 'interface', 'lucas')),
                recorded_at TEXT NOT NULL,
                PRIMARY KEY (approval_id, seq)
            ) STRICT""",
            f"""CREATE TRIGGER transitions_legal BEFORE INSERT ON transitions
            WHEN NOT EXISTS (SELECT 1 FROM requests WHERE approval_id = NEW.approval_id)
            OR NOT EXISTS (
                SELECT 1 FROM allowed_transitions
                WHERE from_state = {_LAST_STATE} AND to_state = NEW.state
            )
            OR NEW.seq != 1 + (
                SELECT COUNT(*) FROM transitions WHERE approval_id = NEW.approval_id
            )
            OR (NEW.state = 'ACCORDEE' AND NEW.actor != 'lucas')
            BEGIN
                SELECT RAISE(ABORT, 'transitions : interdite par la machine à états (ADR-035)');
            END""",  # noqa: S608 - only this module's constants, never an input
            *_immutable("transitions", "une transition"),
            """CREATE TABLE code_attempts (
                approval_id TEXT NOT NULL REFERENCES requests (approval_id),
                attempted_at TEXT NOT NULL,
                ok INTEGER NOT NULL CHECK (ok IN (0, 1)),
                step INTEGER CHECK ((ok = 1) = (step IS NOT NULL))
            ) STRICT""",
            "CREATE INDEX code_attempts_time ON code_attempts (attempted_at)",
            """CREATE TRIGGER code_attempts_fresh BEFORE INSERT ON code_attempts
            WHEN NEW.ok = 1
            AND NEW.step <= (SELECT COALESCE(MAX(step), -1) FROM code_attempts WHERE ok = 1)
            BEGIN
                SELECT RAISE(ABORT, 'code_attempts : un code ne sert qu''une fois (RFC 6238)');
            END""",
            *_immutable("code_attempts", "un essai de code"),
        ),
    ),
)
LATEST_VERSION = MIGRATIONS[-1][0]


def default_store_path(project_root: Path) -> Path:
    return project_root / "var" / "approvals" / "approvals.db"


class ApprovalError(Exception):
    """The store refuses a request or cannot be read: nothing is recorded."""


@dataclass(frozen=True)
class ApprovalRules:
    """The parameters of ``autonomy.yaml: approval`` (D3), every one decided by Lucas."""

    expiry: timedelta
    max_code_attempts: int
    lockout_failures: int
    lockout_window: timedelta

    @classmethod
    def from_config(cls, approval: Approval) -> ApprovalRules:
        values = (
            approval.expiry_minutes,
            approval.max_code_attempts,
            approval.lockout_failures,
            approval.lockout_window_minutes,
        )
        known = [value for value in values if isinstance(value, int)]
        if len(known) != len(values):
            raise ApprovalError("paramètres d'approbation à définir par Lucas (R7)")
        expiry, attempts, failures, window = known
        return cls(timedelta(minutes=expiry), attempts, failures, timedelta(minutes=window))


@dataclass(frozen=True)
class Trail:
    """Where, and under which request, the store journals what it records."""

    journal: Journal
    request_id: str
    versions: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: UUID
    intent_id: UUID
    intent_sha256: str
    environment: Environment
    gate: Mapping[str, Any]  # the Risk Gate's result when the approval was requested
    summary: str  # the one message that may show an amount or a position (D12)
    created_at: datetime
    expires_at: datetime
    state: ApprovalState  # at the time it was read: EXPIREE once the deadline has passed
    failures: int  # wrong codes for this request


@dataclass(frozen=True)
class CodeOutcome:
    state: ApprovalState
    accepted: bool
    attempts_left: int
    locked: bool  # too many wrong codes lately: every approval waits (D3)


def _connect(target: str, *, uri: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(target, uri=uri, autocommit=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _text(value: str, name: str, limit: int) -> str:
    if not 1 <= len(value) <= limit:
        raise ApprovalError(f"{name} : de 1 à {limit} caractères")
    try:
        return plain_text(value)
    except ValueError as exc:
        raise ApprovalError(f"{name} refusé(e) : {exc}") from exc


class ApprovalStore:
    """``with ApprovalStore.open(path, rules=..., trail=Trail(...)) as store:``, then
    ``store.request(...)``."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        rules: ApprovalRules,
        trail: Trail | None,
        read_only: bool,
        ids: Callable[[], UUID] = uuid7,
    ) -> None:
        self._conn = conn
        self._trail = trail
        self._ids = ids
        self.rules = rules
        self.read_only = read_only
        if read_only:
            conn.execute("PRAGMA query_only = ON")
            version = schema_version(conn)
            if version != LATEST_VERSION:
                raise SchemaError(f"approbations au schéma {version}, attendu {LATEST_VERSION}")
        else:
            migrate(conn, MIGRATIONS)

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        rules: ApprovalRules,
        trail: Trail | None = None,
        read_only: bool = False,
        ids: Callable[[], UUID] = uuid7,
    ) -> ApprovalStore:
        if read_only:
            if not path.is_file():
                raise ApprovalError(f"registre des approbations absent ({path.name})")
            conn = _connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = _connect(str(path), uri=False)
        try:
            return cls(conn, rules=rules, trail=trail, read_only=read_only, ids=ids)
        except BaseException:
            conn.close()
            raise

    @classmethod
    def memory(
        cls, rules: ApprovalRules, trail: Trail, *, ids: Callable[[], UUID] = uuid7
    ) -> ApprovalStore:
        return cls(
            _connect(":memory:", uri=False), rules=rules, trail=trail, read_only=False, ids=ids
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ApprovalStore:
        return self

    def __exit__(
        self, kind: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    # Writes ---------------------------------------------------------------------------------

    @contextmanager
    def _write(self) -> Iterator[Trail]:
        if self.read_only or self._trail is None:
            raise ApprovalError("registre ouvert sans journal : lecture seule")
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._trail
        except sqlite3.IntegrityError as exc:
            # The database caught what the checks above it missed.
            self._conn.execute("ROLLBACK")
            raise ApprovalError(f"le registre refuse l'écriture : {exc}") from exc
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def _insert_transition(
        self, row: sqlite3.Row, state: ApprovalState, reason: str, actor: Actor, when: datetime
    ) -> None:
        seq = self._conn.execute(
            "SELECT COUNT(*) FROM transitions WHERE approval_id = ?", (row["approval_id"],)
        ).fetchone()[0]
        self._conn.execute(
            "INSERT INTO transitions (approval_id, seq, state, reason, actor, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (row["approval_id"], seq + 1, state.value, reason, actor, utc_text(when)),
        )

    def _journal(
        self,
        trail: Trail,
        row: sqlite3.Row,
        state: ApprovalState,
        *,
        reason: str,
        actor: Actor,
        when: datetime,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "approval_id": row["approval_id"],
            "intent_id": row["intent_id"],
            "intent_sha256": row["intent_sha256"],
            "environment": row["environment"],
            "state": state.value,
            "reason": reason,
        }
        trail.journal.append(
            actor=actor,
            event="APPROVAL",
            request_id=trail.request_id,
            versions=trail.versions,
            payload=payload | dict(extra or {}),
            now=when,
        )

    def _record(
        self,
        trail: Trail,
        row: sqlite3.Row,
        state: ApprovalState,
        *,
        reason: str,
        actor: Actor,
        when: datetime,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        """Move ``row`` to ``state`` and journal it."""
        self._insert_transition(row, state, reason, actor, when)
        self._journal(trail, row, state, reason=reason, actor=actor, when=when, extra=extra)

    def _bulk_entry(
        self,
        trail: Trail,
        rows: list[sqlite3.Row],
        state: ApprovalState,
        reason: str,
        actor: Actor,
        when: datetime,
    ) -> None:
        trail.journal.append(
            actor=actor,
            event="APPROVAL",
            request_id=trail.request_id,
            versions=trail.versions,
            payload={
                "state": state.value,
                "reason": reason,
                "approvals": [
                    {"approval_id": row["approval_id"], "intent_id": row["intent_id"]}
                    for row in rows
                ],
            },
            now=when,
        )

    def _expire_if_due(self, trail: Trail, row: sqlite3.Row, when: datetime) -> ApprovalState:
        """The request's state, after recording its expiry if its deadline has passed."""
        state = self._effective(row, when)
        if state is ApprovalState.EXPIREE and self._stored(row["approval_id"]) in OPEN:
            self._record(
                trail,
                row,
                ApprovalState.EXPIREE,
                reason="échéance passée",
                actor="policy",
                when=when,
            )
        return state

    def request(
        self,
        *,
        intent_id: UUID,
        intent_sha256: str,
        environment: Environment,
        gate: Mapping[str, Any],
        summary: str,
        now: datetime,
    ) -> ApprovalRequest:
        """Ask Lucas to approve one intent, on behalf of the policy (ADR-036). An intent is asked
        about once: whatever became of its request, it never gets a second one."""
        if not _SHA256.match(intent_sha256):
            raise ApprovalError("empreinte de l'intention : SHA-256 hexadécimal attendu")
        if environment not in ("paper", "live"):
            raise ApprovalError("environnement : paper ou live")
        text = _text(summary, "résumé", SUMMARY_CHARS)
        try:
            gate_json = canonical_json(dict(gate))
        except (TypeError, ValueError) as exc:
            raise ApprovalError(f"résultat de la Porte illisible : {exc}") from exc
        approval_id = str(self._ids())
        with self._write() as trail:
            if self._conn.execute(
                "SELECT 1 FROM requests WHERE intent_id = ?", (str(intent_id),)
            ).fetchone():
                raise ApprovalError(f"intention {intent_id} déjà soumise : pas de seconde demande")
            self._conn.execute(
                "INSERT INTO requests (approval_id, intent_id, intent_sha256, environment, gate, "
                "summary, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    approval_id,
                    str(intent_id),
                    intent_sha256,
                    environment,
                    gate_json,
                    text,
                    utc_text(now),
                    utc_text(now + self.rules.expiry),
                ),
            )
            self._record(
                trail,
                self._known(approval_id),
                ApprovalState.DEMANDEE,
                reason="approbation demandée",
                actor="policy",
                when=now,
            )
        return self.get(UUID(approval_id), now=now)

    def approve(
        self, approval_id: UUID, code: str, *, key: bytes | None, now: datetime
    ) -> CodeOutcome:
        """Check Lucas's one-time code against a request. A right code grants it, on behalf of
        ``lucas``; a wrong one counts, and the last allowed wrong code refuses it. While locked,
        no code is even looked at. A missing secret refuses before anything is counted."""
        if key is None:
            raise ApprovalError("secret TOTP absent ou invalide : aucun code ne peut être vérifié")
        with self._write() as trail:
            row = self._known(str(approval_id))
            left = self.rules.max_code_attempts - self._failures(row["approval_id"])
            if self._locked(now):
                state = self._effective(row, now)
                self._journal(
                    trail,
                    row,
                    state,
                    reason="approbations verrouillées : code non examiné",
                    actor="interface",
                    when=now,
                )
                return CodeOutcome(state, False, left, True)
            state = self._expire_if_due(trail, row, now)
            if state is ApprovalState.EXPIREE:
                return CodeOutcome(state, False, left, False)
            if state is not ApprovalState.DEMANDEE:
                raise ApprovalError(f"approbation {approval_id} {state} : aucun code attendu")
            step = verify(key, code, now, last_step=self._last_step())
            self._conn.execute(
                "INSERT INTO code_attempts (approval_id, attempted_at, ok, step) "
                "VALUES (?, ?, ?, ?)",
                (row["approval_id"], utc_text(now), int(step is not None), step),
            )
            if step is not None:
                self._record(
                    trail,
                    row,
                    ApprovalState.ACCORDEE,
                    reason="code vérifié",
                    actor="lucas",
                    when=now,
                )
                return CodeOutcome(ApprovalState.ACCORDEE, True, left, False)
            left -= 1
            locked = self._locked(now)
            extra = {"attempts_left": left, "locked": locked}
            if left == 0:
                self._record(
                    trail,
                    row,
                    ApprovalState.REFUSEE,
                    reason="trop de codes faux",
                    actor="policy",
                    when=now,
                    extra=extra,
                )
                return CodeOutcome(ApprovalState.REFUSEE, False, 0, locked)
            self._journal(
                trail,
                row,
                ApprovalState.DEMANDEE,
                reason="code refusé",
                actor="interface",
                when=now,
                extra=extra,
            )
            return CodeOutcome(ApprovalState.DEMANDEE, False, left, locked)

    def refuse(
        self, approval_id: UUID, *, reason: str, actor: Actor, now: datetime
    ) -> ApprovalState:
        """Refuse an open request: Lucas from an interface, or the policy when the Risk Gate,
        evaluated again, no longer agrees. An overdue request expires instead."""
        why = _text(reason, "raison", REASON_CHARS)
        with self._write() as trail:
            row = self._known(str(approval_id))
            state = self._expire_if_due(trail, row, now)
            if state is ApprovalState.EXPIREE:
                return state
            if state not in OPEN:
                raise ApprovalError(f"approbation {approval_id} {state} : plus rien à refuser")
            self._record(trail, row, ApprovalState.REFUSEE, reason=why, actor=actor, when=now)
        return ApprovalState.REFUSEE

    def consume(self, approval_id: UUID, *, intent_sha256: str, now: datetime) -> ApprovalRequest:
        """Spend a granted approval on the very intent it was granted for, once (D4). An overdue
        approval expires and another intent refuses it: both are recorded, then raise."""
        failure: str | None = None
        with self._write() as trail:
            row = self._known(str(approval_id))
            state = self._expire_if_due(trail, row, now)
            if state is ApprovalState.EXPIREE:
                failure = "échue"
            elif state is not ApprovalState.ACCORDEE:
                raise ApprovalError(f"approbation {approval_id} {state} : rien à exécuter")
            elif intent_sha256 != row["intent_sha256"]:
                failure = "accordée pour une autre intention"
                self._record(
                    trail,
                    row,
                    ApprovalState.REFUSEE,
                    reason="intention différente de celle approuvée",
                    actor="policy",
                    when=now,
                )
            else:
                self._record(
                    trail,
                    row,
                    ApprovalState.CONSOMMEE,
                    reason="exécution",
                    actor="policy",
                    when=now,
                )
        if failure is not None:
            raise ApprovalError(f"approbation {approval_id} {failure} : aucune exécution")
        return self.get(approval_id, now=now)

    def refuse_open(self, *, reason: str, actor: Actor, now: datetime) -> tuple[UUID, ...]:
        """Refuse every open request in one transaction and one entry: the kill switch's move
        (ADR-034). Overdue ones expire first, in one more entry."""
        why = _text(reason, "raison", REASON_CHARS)
        with self._write() as trail:
            self._expire_all(trail, now)
            rows = self._open_rows()
            for row in rows:
                self._insert_transition(row, ApprovalState.REFUSEE, why, actor, now)
            if rows:
                self._bulk_entry(trail, rows, ApprovalState.REFUSEE, why, actor, now)
        return tuple(UUID(row["approval_id"]) for row in rows)

    def expire_due(self, *, now: datetime) -> tuple[UUID, ...]:
        """Record the expiry of every overdue open request, in one entry."""
        with self._write() as trail:
            rows = self._expire_all(trail, now)
        return tuple(UUID(row["approval_id"]) for row in rows)

    def _expire_all(self, trail: Trail, now: datetime) -> list[sqlite3.Row]:
        rows = [row for row in self._open_rows() if now >= from_utc_text(row["expires_at"])]
        for row in rows:
            self._insert_transition(row, ApprovalState.EXPIREE, "échéance passée", "policy", now)
        if rows:
            self._bulk_entry(trail, rows, ApprovalState.EXPIREE, "échéance passée", "policy", now)
        return rows

    # Reads ----------------------------------------------------------------------------------

    def _known(self, approval_id: str) -> sqlite3.Row:
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT * FROM requests WHERE approval_id = ?", (approval_id,)
        ).fetchone()
        if row is None:
            raise ApprovalError(f"approbation {approval_id} inconnue")
        return row

    def _stored(self, approval_id: str) -> ApprovalState:
        row = self._conn.execute(
            "SELECT state FROM transitions WHERE approval_id = ? ORDER BY seq DESC LIMIT 1",
            (approval_id,),
        ).fetchone()
        return ApprovalState(row["state"])

    def _effective(self, row: sqlite3.Row, now: datetime) -> ApprovalState:
        stored = self._stored(row["approval_id"])
        if stored in OPEN and now >= from_utc_text(row["expires_at"]):
            return ApprovalState.EXPIREE
        return stored

    def _failures(self, approval_id: str) -> int:
        return int(
            self._conn.execute(
                "SELECT COUNT(*) FROM code_attempts WHERE approval_id = ? AND ok = 0",
                (approval_id,),
            ).fetchone()[0]
        )

    def _last_step(self) -> int | None:
        """The highest step ever accepted, whatever the request: a code serves once (§5.2)."""
        value = self._conn.execute("SELECT MAX(step) FROM code_attempts WHERE ok = 1").fetchone()[0]
        return None if value is None else int(value)

    def _locked(self, now: datetime) -> bool:
        since = utc_text(now - self.rules.lockout_window)
        wrong = self._conn.execute(
            "SELECT COUNT(*) FROM code_attempts WHERE ok = 0 AND attempted_at > ?", (since,)
        ).fetchone()[0]
        return int(wrong) >= self.rules.lockout_failures

    def _open_rows(self) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM requests AS r WHERE (SELECT state FROM transitions AS t "
                "WHERE t.approval_id = r.approval_id ORDER BY seq DESC LIMIT 1) "
                "IN ('DEMANDEE', 'ACCORDEE') ORDER BY approval_id"
            )
        )

    def _build(self, row: sqlite3.Row, now: datetime) -> ApprovalRequest:
        return ApprovalRequest(
            approval_id=UUID(row["approval_id"]),
            intent_id=UUID(row["intent_id"]),
            intent_sha256=row["intent_sha256"],
            environment=row["environment"],
            gate=json.loads(row["gate"]),
            summary=row["summary"],
            created_at=from_utc_text(row["created_at"]),
            expires_at=from_utc_text(row["expires_at"]),
            state=self._effective(row, now),
            failures=self._failures(row["approval_id"]),
        )

    def get(self, approval_id: UUID, *, now: datetime) -> ApprovalRequest:
        return self._build(self._known(str(approval_id)), now)

    def for_intent(self, intent_id: UUID, *, now: datetime) -> ApprovalRequest | None:
        row = self._conn.execute(
            "SELECT * FROM requests WHERE intent_id = ?", (str(intent_id),)
        ).fetchone()
        return None if row is None else self._build(row, now)

    def requests(
        self, states: Collection[ApprovalState] | None = None, *, now: datetime
    ) -> list[ApprovalRequest]:
        """Every request, oldest first (a UUIDv7 sorts by time), or those in ``states`` at
        ``now``: ``{DEMANDEE}`` is what waits for Lucas, ``{ACCORDEE}`` what waits to run."""
        built = [
            self._build(row, now)
            for row in self._conn.execute("SELECT * FROM requests ORDER BY approval_id")
        ]
        return [item for item in built if states is None or item.state in states]

    def locked(self, *, now: datetime) -> bool:
        return self._locked(now)

    def counts(self, *, now: datetime) -> dict[ApprovalState, int]:
        """How many requests stand in each state at ``now``: the N3 → N4 counters (ADR-035)."""
        tally = dict.fromkeys(ApprovalState, 0)
        for item in self.requests(now=now):
            tally[item.state] += 1
        return tally
