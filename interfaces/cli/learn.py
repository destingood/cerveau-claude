"""`cerveau learn`: the learned layer and its champion / challenger gate (ADR-011, ADR-065).

``status`` only reads. ``gate`` compares two eval reports and journals its verdict as a
``LEARNING`` entry (counts and status, never a lesson); it promotes nothing (D4). ``patterns``
lists what the journal teaches and, with ``--proposer``, writes challengers under
``var/learning/challengers/``. ``promote`` (blocked until thresholds and budgets are set),
``rollback`` and ``watch`` change the layer in service, each journaled (R11).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from core.audit import AuditError, AuditJournal, default_journal_path
from core.config import BlockedFeatureError
from core.learning.champion import (
    ChampionError,
    default_history_path,
    promote,
    rollback,
    verdict_for,
    watch,
)
from core.learning.feedback import default_feedback_path
from core.learning.gate import LEARNING_EVENT, GateError
from core.learning.layer import SECTIONS, LockedCoreError, read_section
from core.learning.patterns import PatternError, harvest, propose
from core.orchestrator.packs import pack_ids
from core.orchestrator.prompts import PromptError, PromptSet
from interfaces.cli.common import (
    EXIT_ERROR,
    ConfigDirOpt,
    JournalOpt,
    OutsideVarOpt,
    blocked,
    fail,
    load,
    project_root,
    var_path,
)

learn_app = typer.Typer(
    help="Couche apprise (learned/) et porte champion / challenger.",
    no_args_is_help=True,
)


@learn_app.command("status")
def status_command(config_dir: ConfigDirOpt = None) -> None:
    """Sections apprises par pack, version du prompt et état de la porte."""
    try:
        version = PromptSet.load().version
    except PromptError as exc:
        fail(f"Refus : {exc}", EXIT_ERROR)
    for pack in pack_ids():
        parts = []
        for section in SECTIONS:
            try:
                text = read_section(pack, section)
            except LockedCoreError as exc:  # pragma: no cover - PromptSet.load refused it first
                fail(f"Refus : {exc}", EXIT_ERROR)
            parts.append(f"{section} {len(text)} car." if text else f"{section} aucune")
        typer.echo(f"{pack} : {', '.join(parts)}")
    typer.echo(f"Version du prompt : {version}")
    try:
        load(config_dir).require("learning.promotion")
    except BlockedFeatureError:
        typer.echo("Mise en ligne : bloquée, seuils ou budgets à définir (R7).")
    else:
        typer.echo("Mise en ligne : seuils fixés ; seulement après des évals réelles (D4).")


def _journal(journal: Path | None, outside_var: bool) -> AuditJournal:
    default = default_journal_path(project_root())
    return AuditJournal(var_path(journal, default, option="--journal", outside=outside_var))


def _report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"Refus : rapport illisible {path.name} ({type(exc).__name__})", EXIT_ERROR)
    if not isinstance(report, dict):
        fail(f"Refus : rapport illisible {path.name}", EXIT_ERROR)
    return report


@learn_app.command("gate")
def gate_command(
    champion: Annotated[Path, typer.Argument(help="Rapport d'évals JSON du champion.")],
    challenger: Annotated[Path, typer.Argument(help="Rapport d'évals JSON du challenger.")],
    journal: JournalOpt = None,
    outside_var: OutsideVarOpt = False,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Verdict de la porte sur deux rapports des mêmes cas ; ne met rien en ligne."""
    config = load(config_dir)
    try:
        verdict = verdict_for(config, _report(champion), _report(challenger))
    except GateError as exc:
        fail(f"Refus : {exc}", EXIT_ERROR)
    held = verdict.held_out
    try:
        _journal(journal, outside_var).append(
            actor="orchestrator",
            event=LEARNING_EVENT,
            payload={
                "action": "verdict",
                "status": verdict.status,
                "held_out_cases": held.cases,
                "champion_passed": held.champion_passed,
                "challenger_passed": held.challenger_passed,
                "regressions": len(verdict.regressions),
            },
            now=datetime.now().astimezone(),
        )
    except AuditError as exc:
        fail(f"Refus : {exc}", EXIT_ERROR)
    typer.echo(f"Verdict : {verdict.status}")
    typer.echo(
        f"Jeu tenu à l'écart : {held.cases} cas ; champion {held.champion_passed} réussis "
        f"(moyenne {held.champion_mean:.4f}), challenger {held.challenger_passed} "
        f"(moyenne {held.challenger_mean:.4f})."
    )
    for reason in verdict.reasons:
        typer.echo(f"  - {reason}")
    for suite, case in verdict.regressions:
        typer.echo(f"  perdu : {suite}/{case}")


PackOpt = Annotated[str, typer.Option("--pack", help="Pack de domaine.")]
SectionOpt = Annotated[str, typer.Option("--section", help="lessons ou examples.")]


@learn_app.command("patterns")
def patterns_command(
    proposer: Annotated[
        bool, typer.Option("--proposer", help="Écrire un challenger par motif retenu.")
    ] = False,
    journal: JournalOpt = None,
    outside_var: OutsideVarOpt = False,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Motifs d'erreurs et de retours du journal ; un retour seul ne change rien (B78)."""
    config = load(config_dir)
    try:
        config.require("learning.patterns")
    except BlockedFeatureError as exc:
        blocked(exc)
    learning = config.evals.learning
    root = project_root()
    try:
        found = harvest(
            _journal(journal, outside_var),
            default_feedback_path(root),
            min_support=int(learning.min_support),  # set: require passed
            max_feedback_per_user=int(learning.max_feedback_per_user),
        )
    except PatternError as exc:
        fail(f"Refus : {exc}", EXIT_ERROR)
    typer.echo(
        f"Motifs retenus : {len(found.patterns)} ; sous le seuil : {found.below_support} ; "
        f"retours au-delà du plafond : {found.capped}."
    )
    typer.echo(
        f"Notes : {found.notes_kept} gardées, {found.notes_set_aside} écartées (consigne, R5)."
    )
    for pattern in found.patterns:
        line = f"  {pattern.pack} / {pattern.kind} : {pattern.requests} requêtes"
        if proposer:
            try:
                where = propose(pattern, root / "var" / "learning" / "challengers")
            except (PatternError, LockedCoreError) as exc:
                line += f" ; pas de challenger ({exc})"
            else:
                line += f" ; challenger : {where.name}"
        typer.echo(line)


@learn_app.command("promote")
def promote_command(
    champion: Annotated[Path, typer.Argument(help="Rapport d'évals JSON du champion.")],
    challenger: Annotated[Path, typer.Argument(help="Rapport d'évals JSON du challenger.")],
    candidate: Annotated[Path, typer.Option("--challenger-dir", help="Couche du challenger.")],
    pack: PackOpt,
    section: SectionOpt = "lessons",
    journal: JournalOpt = None,
    outside_var: OutsideVarOpt = False,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Met le challenger en service, seulement sur un verdict « promouvable » (D4)."""
    try:
        verdict = promote(
            load(config_dir),
            _report(champion),
            _report(challenger),
            candidate,
            pack,
            section,
            journal=_journal(journal, outside_var),
            history=default_history_path(project_root()),
            now=datetime.now().astimezone(),
        )
    except BlockedFeatureError as exc:
        blocked(exc)
    except (ChampionError, GateError, LockedCoreError, AuditError) as exc:
        fail(f"Refus : {exc}", EXIT_ERROR)
    typer.echo(f"Mis en service : {pack}/{section} ({verdict.held_out.cases} cas tenus à l'écart).")


@learn_app.command("rollback")
def rollback_command(
    pack: PackOpt,
    section: SectionOpt = "lessons",
    journal: JournalOpt = None,
    outside_var: OutsideVarOpt = False,
) -> None:
    """Revient au champion d'avant la dernière promotion de la section."""
    try:
        undone = rollback(
            pack,
            section,
            journal=_journal(journal, outside_var),
            history=default_history_path(project_root()),
            now=datetime.now().astimezone(),
            reason="demande de Lucas",
        )
    except (ChampionError, LockedCoreError, AuditError) as exc:
        fail(f"Refus : {exc}", EXIT_ERROR)
    state = "section retirée" if undone.previous is None else "section précédente rétablie"
    typer.echo(f"Retour arrière : {pack}/{section}, {state}.")


@learn_app.command("watch")
def watch_command(
    production: Annotated[Path, typer.Argument(help="Rapport d'évals JSON en production.")],
    pack: PackOpt,
    section: SectionOpt = "lessons",
    journal: JournalOpt = None,
    outside_var: OutsideVarOpt = False,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Retour arrière automatique si la production baisse dans la fenêtre de surveillance."""
    try:
        verdict = watch(
            load(config_dir),
            _report(production),
            pack,
            section,
            journal=_journal(journal, outside_var),
            history=default_history_path(project_root()),
            now=datetime.now().astimezone(),
        )
    except (ChampionError, GateError, LockedCoreError, AuditError) as exc:
        fail(f"Refus : {exc}", EXIT_ERROR)
    if verdict is None:
        typer.echo("Rien à surveiller : aucune promotion en service dans la fenêtre.")
    elif verdict.status == "rejete":
        typer.echo("Baisse en production : retour arrière effectué.")
        for reason in verdict.reasons:
            typer.echo(f"  - {reason}")
    else:
        typer.echo(f"Production : {verdict.status}, promotion maintenue.")
