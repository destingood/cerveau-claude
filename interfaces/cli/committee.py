"""`cerveau committee`: rereads a committee session and checks it against the journal (D19).

A session's full record, pseudonymised, lives in ``var/<pack>/committee/<id>.json``; each of its
roles left a DECISION entry in the audit journal that holds the file's SHA-256. ``show``
recomputes it: a file changed or removed after the session is reported, never trusted (R11).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Annotated, Any

import typer

from core.audit import AuditJournal, default_journal_path
from interfaces.cli.common import EXIT_ERROR, JournalOpt, project_root
from interfaces.cli.common import fail as _fail

committee_app = typer.Typer(
    help="Comité d'investissement : relire une séance (D19).", no_args_is_help=True
)

RECORD_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PACK_ID = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
CHOICE = {"agir": "agir", "ne_pas_agir": "ne pas agir", "attendre": "attendre"}


def journaled(journal: AuditJournal, record_id: str) -> tuple[str | None, set[str]]:
    """The pack and the file digests that the role entries of the session hold."""
    pack: str | None = None
    digests: set[str] = set()
    if not journal.path.exists():
        return pack, digests
    for line in journal.path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("event") != "DECISION" or not entry.get("payload_ref"):
            continue
        payload = journal.read_payload(entry["payload_ref"])
        committee = payload.get("committee") if isinstance(payload, dict) else None
        if not isinstance(committee, dict):
            continue
        if committee.get("committee_record_id") != record_id:
            continue
        if isinstance(committee.get("pack"), str):
            pack = committee["pack"]
        if isinstance(committee.get("file_sha256"), str):
            digests.add(committee["file_sha256"])
    return pack, digests


def _role_line(role: dict[str, Any]) -> str:
    state = "valide" if role.get("valid") else f"en échec ({role.get('error') or 'sans détail'})"
    constats = ", ".join(role.get("constats") or []) or "aucun constat"
    return (
        f"- {role.get('member')} ({role.get('kind')}, tour {role.get('round')}) : {state} ; "
        f"modèle {role.get('model')} ; {constats}"
    )


def summary(record: dict[str, Any]) -> list[str]:
    lines = [
        f"Séance {record.get('committee_record_id')} — pack {record.get('pack')}, version "
        f"{record.get('version')} : {record.get('status')}"
        + (f" ({record['reason']})" if record.get("reason") else ""),
        f"Question (pseudonymisée) : {record.get('question')}",
        f"Rôles ({len(record.get('roles') or [])}) :",
        *(_role_line(role) for role in record.get("roles") or []),
    ]
    decision = record.get("decision")
    if isinstance(decision, dict):
        choice = CHOICE.get(str(decision.get("decision")), str(decision.get("decision")))
        lines += [
            f"Décision proposée : {choice} — {decision.get('proposition')}",
            f"Confiance : {decision.get('confiance')} ; horizon : {decision.get('horizon')}",
        ]
    else:
        lines.append("Décision proposée : pas de décision")
    lines.append(f"Verdict des contrôles : {record.get('verdict') or 'aucun'}")
    lines += [f"  - {reason}" for reason in record.get("verdict_reasons") or []]
    return lines


@committee_app.command("show")
def show(
    record_id: Annotated[
        str, typer.Argument(help="L'identifiant de séance affiché sous la décision du Comité.")
    ],
    journal: JournalOpt = None,
) -> None:
    """Relit une séance du Comité et vérifie son empreinte dans le journal d'audit (D19).

    Codes de sortie : 0 séance intacte, 1 identifiant invalide, séance inconnue du journal,
    fichier introuvable ou altéré.
    """
    if not RECORD_ID.fullmatch(record_id):
        _fail(f"Identifiant de séance invalide : {record_id[:60]!r}.", EXIT_ERROR)
    root = project_root()
    audit = AuditJournal(journal or default_journal_path(root))
    pack, digests = journaled(audit, record_id)
    if pack is None or not digests or not PACK_ID.fullmatch(pack):
        _fail(f"Séance {record_id} inconnue du journal d'audit.", EXIT_ERROR)
    path = root / "var" / pack / "committee" / f"{record_id}.json"
    shown = Path("var", pack, "committee", f"{record_id}.json").as_posix()
    if not path.is_file():
        _fail(f"Séance {record_id} : fichier {shown} introuvable.", EXIT_ERROR)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() not in digests or len(digests) != 1:
        _fail(
            f"Séance {record_id} : fichier {shown} altéré (empreinte SHA-256 différente de celle "
            "du journal). Ne pas s'y fier.",
            EXIT_ERROR,
        )
    typer.echo("\n".join(summary(json.loads(data))))
    typer.echo(f"Fichier {shown} : intact (empreinte SHA-256 conforme au journal).")
