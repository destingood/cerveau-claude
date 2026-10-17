"""`cerveau` command line (Phase 0: audit, config, registry)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from core.audit import AuditJournal, default_journal_path, verify
from core.config import FEATURES, ConfigError, load_config
from core.registry import validate_all, validate_plugin

app = typer.Typer(help="CERVEAU : plateforme d'IA personnelle.", no_args_is_help=True)
audit_app = typer.Typer(help="Journal d'audit chaîné (R11).", no_args_is_help=True)
config_app = typer.Typer(help="Configuration et marqueurs bloquants (R7).", no_args_is_help=True)
registry_app = typer.Typer(help="Registre de plugins (R8).", no_args_is_help=True)
app.add_typer(audit_app, name="audit")
app.add_typer(config_app, name="config")
app.add_typer(registry_app, name="registry")


@app.callback()
def main() -> None:
    # Redirected output on Windows defaults to cp1252; French messages must stay readable.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def project_root() -> Path:
    override = os.environ.get("CERVEAU_HOME")
    return Path(override) if override else Path(__file__).resolve().parents[2]


JournalOpt = Annotated[
    Path | None, typer.Option("--journal", help="Chemin du journal (défaut : var/audit).")
]


@audit_app.command("verify")
def audit_verify(
    journal: JournalOpt = None,
    anchor: Annotated[
        str | None,
        typer.Option(help="Ancre externe <seq>:sha256:<hex> pour détecter une troncature."),
    ] = None,
) -> None:
    """Vérifie toute la chaîne de hash du journal."""
    path = journal or default_journal_path(project_root())
    try:
        report = verify(path, anchor=anchor)
    except ValueError as exc:
        typer.echo(f"ERREUR : {exc}", err=True)
        raise typer.Exit(2) from exc
    for warning in report.warnings:
        typer.echo(f"avertissement : {warning}")
    if report.ok:
        typer.echo(f"OK : {report.entries} entrée(s), tête {report.head_seq}:{report.head_hash}")
        if anchor is None and report.entries:
            typer.echo("Sans ancre externe, une troncature de fin de journal reste indétectable.")
        return
    typer.echo(f"ÉCHEC : {len(report.errors)} problème(s) dans {path}", err=True)
    for error in report.errors:
        typer.echo(f"  - {error}", err=True)
    raise typer.Exit(1)


@audit_app.command("head")
def audit_head(journal: JournalOpt = None) -> None:
    """Affiche l'ancre <seq>:<hash> à copier hors de la machine."""
    path = journal or default_journal_path(project_root())
    report = verify(path)
    if not report.ok:
        typer.echo("Journal invalide : lancer `cerveau audit verify`.", err=True)
        raise typer.Exit(1)
    typer.echo(f"{report.head_seq}:{report.head_hash}")


@audit_app.command("tail")
def audit_tail(
    journal: JournalOpt = None,
    n: Annotated[int, typer.Option("-n", min=1, help="Nombre d'entrées.")] = 5,
) -> None:
    """Affiche les dernières entrées avec leur payload."""
    path = journal or default_journal_path(project_root())
    if not path.exists():
        typer.echo("Journal vide.")
        return
    store = AuditJournal(path)
    lines = path.read_text(encoding="utf-8").splitlines()[-n:]
    for line in lines:
        entry = json.loads(line)
        if entry.get("payload_ref"):
            entry["payload"] = store.read_payload(entry["payload_ref"])
        typer.echo(json.dumps(entry, ensure_ascii=False, indent=2))


@config_app.command("check")
def config_check(
    config_dir: Annotated[Path | None, typer.Option("--config-dir")] = None,
) -> None:
    """Valide config/*.yaml et liste les fonctions bloquées par A_DEFINIR / A_VERIFIER."""
    directory = config_dir or project_root() / "config"
    try:
        config = load_config(directory)
    except ConfigError as exc:
        typer.echo("Configuration invalide :", err=True)
        for line in str(exc).splitlines():
            typer.echo(f"  - {line}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Configuration valide ({directory}), empreinte {config.digest}")
    typer.echo(f"live.yaml : enabled = {str(config.live.enabled).lower()}")
    status = config.status()
    blocked = {k: v for k, v in status.items() if v}
    available = [k for k, v in status.items() if not v]
    typer.echo(f"\nFonctions disponibles ({len(available)}) : {', '.join(available) or 'aucune'}")
    typer.echo(f"Fonctions bloquées ({len(blocked)}) :")
    for name, reasons in blocked.items():
        typer.echo(f"  ✗ {name} — {FEATURES[name].description}")
        for reason in reasons:
            typer.echo(f"      · {reason}")
    comments = [m for m in config.markers if m.in_comment]
    if comments:
        typer.echo("\nMarqueurs en commentaire (décisions à prendre, non bloquants) :")
        for marker in comments:
            typer.echo(f"  · {marker}")


@registry_app.command("validate")
def registry_validate(
    path: Annotated[
        Path | None, typer.Argument(help="Dossier d'un plugin, ou plugins/ par défaut.")
    ] = None,
) -> None:
    """Valide les manifestes plugin.yaml (annexe C.1) et refuse les plugins non conformes."""
    target = path or project_root() / "plugins"
    if (target / "plugin.yaml").exists():
        reports = [validate_plugin(target)]
    else:
        result = validate_all(target)
        reports = result.accepted + result.refused
    if not reports:
        typer.echo(f"Aucun plugin dans {target}.")
        return
    refused = 0
    for report in reports:
        name = report.plugin_id or report.directory.name
        if report.ok:
            typer.echo(f"ACCEPTÉ  {name}")
        else:
            refused += 1
            typer.echo(f"REFUSÉ   {name}")
            for error in report.errors:
                typer.echo(f"    - {error}")
        for warning in report.warnings:
            typer.echo(f"    avertissement : {warning}")
    if refused:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
