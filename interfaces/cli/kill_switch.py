"""`cerveau kill` and `cerveau rearm`: the kill switch by hand (R4, D12, ADR-034).

``kill`` never refuses: a configuration, a book or a simulator that cannot be read is reported,
and the stop goes on without it. ``rearm`` is Lucas's alone, at an interactive terminal; Claude
Code's hooks refuse it (ADR-034).
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from core.audit import AuditJournal, default_journal_path
from core.config import ConfigError, load_config
from core.execution.book import OrderBook, Recorder, default_book_path
from core.execution.broker import BrokerAdapter
from core.execution.kill_switch import (
    REARM_PHRASE,
    KillSwitchError,
    Stop,
    detect,
    engage,
    rearm,
    recorded_stop,
)
from core.execution.paper import PaperSettings, PaperSimulator, default_simulator_path
from core.execution.reconcile import interactive_terminal
from interfaces.cli.common import EXIT_BLOCKED, EXIT_ERROR, ConfigDirOpt, JournalOpt, fail
from interfaces.cli.common import project_root as _project_root

ReasonOpt = Annotated[
    str, typer.Option("--raison", help="Pourquoi l'arrêt (une ligne, 200 caractères au plus).")
]


def _settings(
    root: Path, config_dir: Path, unavailable: list[str]
) -> tuple[float | None, PaperSettings | None]:
    """The target and the paper settings, None for what is unknown; a paper account that exists
    but cannot be opened goes in ``unavailable``."""
    try:
        config = load_config(config_dir)
    except ConfigError:
        unavailable.append("configuration invalide : cible et compte paper inconnus")
        return None, None
    target = config.risk.kill_switch.target_seconds
    settings: PaperSettings | None = None
    try:
        settings = PaperSettings.from_config(
            config.risk_limits_paper, config.execution, config.risk.trading_costs
        )
    except Exception as exc:  # a stop never waits for a setting
        if default_simulator_path(root).is_file():
            unavailable.append(f"simulateur paper non ouvert ({exc})")
    return (None if isinstance(target, str) else float(target)), settings


def _seconds(value: float, spec: str) -> str:
    return format(value, spec).replace(".", ",")


def _summary(stop: Stop) -> None:
    if stop.target_s is None:
        verdict = "cible à définir (R7)"
    else:
        verdict = "dans la cible" if stop.within_target else "AU-DELÀ de la cible"
        verdict += f" de {_seconds(stop.target_s, 'g')} s"
    elapsed = _seconds(stop.elapsed_s, ".3f")
    typer.echo(f"Kill switch engagé ({stop.trigger}) en {elapsed} s, {verdict}.")
    typer.echo(
        f"Ordres : {len(stop.cancelled)} passés à ANNULEE au carnet, "
        f"{len(stop.broker_cancelled)} annulations confirmées par le courtier."
    )
    if stop.report is not None:
        typer.echo(f"Rapport : {stop.report}")
    for key in stop.unconfirmed:
        typer.echo(f"ALERTE : annulation non confirmée pour l'ordre {key}", err=True)
    for key in stop.unknown:
        typer.echo(f"ALERTE : ordre {key} annulé chez le courtier, absent du carnet", err=True)
    for error in stop.errors:
        typer.echo(f"ERREUR : {error}", err=True)


def kill_command(
    raison: ReasonOpt = "commande de Lucas",
    journal: JournalOpt = None,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Arrêt total : fichier KILL, annulation des ordres ouverts, N0 forcé (R4)."""
    root = _project_root()
    now = datetime.now(UTC)
    request_id = f"kill-{uuid.uuid4().hex[:12]}"
    audit = AuditJournal(journal or default_journal_path(root))
    unavailable: list[str] = []
    target, settings = _settings(root, config_dir or root / "config", unavailable)
    with ExitStack() as stack:
        book: OrderBook | None = None
        if default_book_path(root).is_file():
            try:
                book = stack.enter_context(
                    OrderBook.open(
                        default_book_path(root), recorder=Recorder(audit, "lucas", request_id)
                    )
                )
            except Exception as exc:
                unavailable.append(f"carnet d'ordres non ouvert ({type(exc).__name__})")
        adapter: BrokerAdapter | None = None
        if settings is not None and default_simulator_path(root).is_file():
            try:
                adapter = stack.enter_context(
                    PaperSimulator.open(default_simulator_path(root), settings, now=now)
                )
            except Exception as exc:
                unavailable.append(f"simulateur paper non ouvert ({type(exc).__name__})")
        stop = engage(
            root,
            trigger="commande",
            reason=raison,
            journal=audit,
            actor="lucas",
            request_id=request_id,
            now=now,
            target_seconds=target,
            adapter=adapter,
            book=book,
            unavailable=unavailable,
        )
    _summary(stop)
    if not stop.clean:
        raise typer.Exit(EXIT_ERROR)


def rearm_command(journal: JournalOpt = None) -> None:
    """Réarmer le kill switch : Lucas seul, en terminal interactif (D12)."""
    root = _project_root()
    now = datetime.now(UTC)
    request_id = f"rearm-{uuid.uuid4().hex[:12]}"
    audit = AuditJournal(journal or default_journal_path(root))
    status = detect(root, journal=audit, request_id=request_id, now=now)
    if status == "removed_by_hand":
        typer.echo("Fichier KILL supprimé à la main : suppression journalisée, rien à réarmer.")
        return
    if status == "armed":
        fail("Aucun arrêt en cours : rien à réarmer.", EXIT_ERROR)
    if not interactive_terminal():
        fail(
            "Réarmement refusé : il se fait par Lucas, dans un terminal interactif (D12).",
            EXIT_BLOCKED,
        )
    recorded = recorded_stop(root)
    if recorded is None:
        typer.echo("Fichier KILL créé à la main : aucun arrêt journalisé, ordres non annulés.")
    else:
        typer.echo(f"Arrêt du {recorded.engaged_at} ({recorded.trigger}).")
        if recorded.report is not None:
            typer.echo(f"Rapport : {recorded.report}")
        for key in recorded.unconfirmed:
            typer.echo(f"ALERTE : annulation non confirmée pour l'ordre {key}", err=True)
    phrase = typer.prompt(f"Vérifier les ordres, puis taper {REARM_PHRASE} pour réarmer")
    try:
        rearm(
            root,
            journal=audit,
            request_id=request_id,
            now=now,
            phrase=phrase.strip(),
            interactive=interactive_terminal,
        )
    except KillSwitchError as exc:
        fail(f"{exc}.", EXIT_BLOCKED)
    typer.echo("Kill switch réarmé : l'autonomie reprend selon la politique.")
