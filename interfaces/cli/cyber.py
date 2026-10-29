"""`cerveau cyber` : what the user runs himself for the defensive Cyber pack (phase 6, P4).

`attack-fetch` is the only download of the ATT&CK bundle (G5): never automatic, never called by
a plugin or by the orchestrator. Every run is journaled (R11), refusals and unexpected failures
included, except four refused before the journal is open: a malformed version, an engaged kill
switch, an invalid configuration and a `--journal` outside `var/`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Annotated, Any, NoReturn

import httpx
import typer

from core.audit import AuditJournal, default_journal_path
from core.cyber import fetch
from core.cyber.attack import (
    KIND_LABELS,
    KINDS,
    SHA256,
    VERSION,
    AttackError,
    BuildReport,
    build_index,
    index_path,
    write_index,
)
from core.net.guard import Resolver, system_resolver
from core.policy.engine import kill_switch_engaged
from interfaces.cli.common import (
    EXIT_BLOCKED,
    EXIT_ERROR,
    ConfigDirOpt,
    JournalOpt,
    OutsideVarOpt,
    fail,
    load,
    project_root,
    var_path,
)

cyber_app = typer.Typer(
    help="Pack cyber défensif : copies figées de sources (P4).", no_args_is_help=True
)
VersionOpt = Annotated[
    str, typer.Option("--version", help="Version d'ATT&CK Enterprise, par exemple 20.0.")
]
COMMAND = "cyber attack-fetch"


class _Stopped(AttackError):
    """The kill switch was engaged during the run."""


def now() -> datetime:
    return datetime.now(UTC)


def attack_transport() -> httpx.AsyncBaseTransport | None:
    """The HTTP transport of the download: None is the network; tests replace it."""
    return None


def attack_resolver() -> Resolver:
    """The DNS resolver of the download; tests replace it."""
    return system_resolver


def _stop_if_engaged(root: Path) -> None:
    if kill_switch_engaged(root):
        raise _Stopped("kill switch engagé : arrêt avant la fin, rien n'est écrit (R4)")


@cyber_app.callback()
def _cyber() -> None:
    """Pack cyber défensif : copies figées de sources (P4)."""


@cyber_app.command("attack-fetch")
def attack_fetch(
    version: VersionOpt,
    config_dir: ConfigDirOpt = None,
    journal: JournalOpt = None,
    outside: OutsideVarOpt = False,
) -> None:
    """Télécharge le bundle ATT&CK Enterprise épinglé, le vérifie et construit l'index local.

    Taille et SHA-1 git du commit épinglé vérifiés avant tout ; le SHA-256 est inscrit dans
    config/data_sources.yaml à la première lecture, puis comparé à chaque lecture (ADR-056).
    """
    root = project_root()
    path = var_path(journal, default_journal_path(root), option="--journal", outside=outside)
    if not VERSION.fullmatch(version):
        fail("Refus : version attendue sous la forme 20.0. Rien n'est téléchargé.", EXIT_ERROR)
    if kill_switch_engaged(root):
        fail("Kill switch engagé (R4) : rien n'est téléchargé.", EXIT_BLOCKED)
    config = load(config_dir)
    audit = AuditJournal(path)
    request_id = f"cyber-attack-fetch-{uuid.uuid4().hex[:12]}"
    entry: dict[str, Any] = {"command": COMMAND, "version": version}

    def refuse(reason: str, code: int, prefix: str = "Refus") -> NoReturn:
        audit.append(
            actor="owner",
            event="ERROR",
            request_id=request_id,
            versions={"config": config.digest},
            payload={**entry, "error": reason},
        )
        fail(f"{prefix} : {reason}. Requête {request_id}.", code)

    source = config.data_sources.sources.get("attack")
    if source is None or not source.enabled:
        refuse(
            "source « attack » absente ou désactivée dans config/data_sources.yaml ; rien "
            "n'est téléchargé",
            EXIT_BLOCKED,
            prefix="Bloqué (R7)",
        )
    if source.version != version:
        refuse(
            f"config/data_sources.yaml attend ATT&CK {source.version}, pas {version} ; rien "
            "n'est téléchargé",
            EXIT_ERROR,
        )
    pin = fetch.PINS.get(version)
    if pin is None:
        refuse(f"aucun commit épinglé pour ATT&CK {version} (ADR-056)", EXIT_ERROR)
    entry["commit"] = pin.commit
    known = source.sha256 if source.sha256 and SHA256.fullmatch(source.sha256) else None
    stop = partial(_stop_if_engaged, root)
    try:
        body = asyncio.run(
            fetch.download(
                version,
                pin,
                transport=attack_transport(),
                resolver=attack_resolver(),
                interrupt=stop,
            )
        )
        sha256 = fetch.verify(body, pin)
        if known is not None and known != sha256:
            raise AttackError("SHA-256 différent de celui de config/data_sources.yaml : refusé")
        index, report = build_index(
            body,
            version=version,
            commit=pin.commit,
            source_url=fetch.bundle_url(version, pin),
            sha256=sha256,
            built_at=now().isoformat(timespec="seconds"),
        )
        del body
        stop()
        target = index_path(root, version)
        index_sha256 = write_index(target, index)
        if known is None:
            stop()  # before the configuration too (R4)
            fetch.record_sha256(config_dir or root / "config", sha256)
    except AttackError as exc:
        refuse(str(exc), EXIT_BLOCKED if isinstance(exc, _Stopped) else EXIT_ERROR)
    except OSError as exc:  # index or configuration not written
        refuse(f"écriture impossible ({exc.strerror or type(exc).__name__})", EXIT_ERROR)
    except (Exception, KeyboardInterrupt) as exc:  # memory, interruption: journaled too (R11)
        refuse(f"échec inattendu ({type(exc).__name__})", EXIT_ERROR)
    audit.append(
        actor="owner",
        event="TOOL_CALL",
        request_id=request_id,
        versions={"config": config.digest},
        payload={
            **entry,
            "bundle_bytes": index.bundle_bytes,
            "sha256": sha256,
            "sha256_recorded": known is None,
            "index_sha256": index_sha256,
            "collection_version": index.collection_version,
            "spec_versions": index.spec_versions,
            "kinds": dict(report.kinds),
            "skipped": report.skipped,
            "duplicates": report.duplicates,
            "relationships": report.relationships,
        },
    )
    _summary(version, pin, sha256, known is None, target, report, request_id)


def _summary(
    version: str,
    pin: fetch.Pin,
    sha256: str,
    recorded: bool,
    target: Path,
    report: BuildReport,
    request_id: str,
) -> None:
    typer.echo(
        f"ATT&CK Enterprise {version} (commit {pin.commit[:12]}) : {pin.size} octets vérifiés "
        "(taille et SHA-1 git du commit épinglé)."
    )
    if recorded:
        typer.echo(f"SHA-256 {sha256} inscrit dans config/data_sources.yaml (première lecture).")
        typer.echo("Lancer `cerveau config check` : data.attack doit être disponible.")
    else:
        typer.echo(f"SHA-256 {sha256} identique à celui de config/data_sources.yaml.")
    counts = ", ".join(f"{report.kinds[kind]} {KIND_LABELS[kind]}" for kind in KINDS)
    typer.echo(f"Index : {target} — {counts}.")
    typer.echo(
        f"Écartés : {report.skipped} objet(s) sans identifiant ATT&CK valide, "
        f"{report.duplicates} doublon(s) ; {report.relationships} relation(s) retenue(s). "
        "Comptes à comparer aux chiffres publiés par MITRE (modèle 3.3.0, ADR-056)."
    )
    typer.echo(f"Journalisé : requête {request_id} (`cerveau audit tail`).")
