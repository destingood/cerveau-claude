"""`cerveau memoire`: what the platform would read of the plugin's brain (ADR-072).

Read only, like the orchestrator: the user checks which memories a pack would see for a request,
with their source, date, confidence and end of validity, and what the rules set aside.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import typer

from core.config.loader import DOMAIN_MAX_LEVELS, Config
from core.memory import BrainMemory, Found, Recall, paris_today
from core.memory.reader import CONFIDENCE_LABELS, TYPE_LABELS, excerpt, set_aside_lines
from interfaces.cli.common import EXIT_ERROR, ConfigDirOpt, fail
from interfaces.cli.common import load as _load

memory_app = typer.Typer(
    help="Mémoire : le cerveau du plugin, en lecture seule (ADR-072).", no_args_is_help=True
)


def describe(memory: BrainMemory, recall: Recall) -> list[str]:
    """Where the brain is and what one read gives: for `memoire chercher` and `config check`."""
    lines = [f"Cerveau du plugin : {memory.home} (lecture seule)"]
    if recall.reason is not None:
        lines.append(f"  aucun souvenir lu : {recall.reason}")
        return lines
    lines.append(f"  mode {recall.mode} : {len(recall.candidates)} souvenir(s) lisible(s)")
    aside = set_aside_lines(recall)
    if aside:
        lines.append("  écartés : " + ", ".join(aside))
    return lines


def _found(found: Found, limit: int) -> list[str]:
    m = found.memory
    kind = TYPE_LABELS.get(m.kind, m.kind)
    domains = ", ".join(m.domains) or ("préférence générale" if found.preference else "aucun")
    head = (
        f"- [{m.id}] {kind} · domaine {domains} · source {m.source} · "
        f"confiance {CONFIDENCE_LABELS[m.confidence]} · date {m.date or 'inconnue'} · "
        + (f"expire le {m.expires}" if m.expires else "sans fin de validité")
        + f" · score {found.score:.2f}"
    )
    masked = f" ({m.masked} secret(s) masqué(s))" if m.masked else ""
    body = excerpt(m, limit).replace("\n", "\n    ")
    return [head + masked, f"    {body}"]


@memory_app.command("chercher")
def search(
    text: Annotated[str, typer.Argument(help="Le texte d'une requête, entre guillemets.")],
    domaine: Annotated[
        str, typer.Option("--domaine", help="Pack de la requête (generaliste, finance, code…).")
    ] = "generaliste",
    perso: Annotated[
        bool,
        typer.Option("--perso", help="Inclure le domaine « perso » (jamais sans cette option)."),
    ] = False,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Montre les souvenirs que la plateforme lirait pour ce texte et ce pack, et pourquoi."""
    if domaine not in DOMAIN_MAX_LEVELS:
        fail(f"Pack inconnu : {domaine} (packs : {', '.join(DOMAIN_MAX_LEVELS)}).", EXIT_ERROR)
    config: Config = _load(config_dir)
    memory = BrainMemory.from_config(config)
    recall = memory.read(paris_today(datetime.now().astimezone()))
    selection = memory.select(recall, text, domaine, perso=perso)
    for line in describe(memory, recall):
        typer.echo(line)
    scope = ", ".join(selection.domains) or "aucun"
    typer.echo(f"Pack {domaine} : domaines {scope}, plus les préférences générales")
    if selection.reason is not None:
        return
    typer.echo(f"  hors du périmètre du pack : {selection.out_of_scope}")
    if selection.instructions:
        typer.echo(f"  écartés pour une tournure de consigne (R5) : {selection.instructions}")
    if not selection.found:
        typer.echo("Aucun souvenir rendu pour ce texte.")
        return
    typer.echo(f"\n{len(selection.found)} souvenir(s) rendu(s), marqués comme données (R5) :")
    for found in selection.found:
        for line in _found(found, config.memory.max_chars_per_memory):
            typer.echo(line)
