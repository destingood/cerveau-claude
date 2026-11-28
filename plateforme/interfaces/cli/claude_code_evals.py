"""`cerveau evals`: the golden sets passed in Claude Code, judged by another model (ADR-074).

No API key and no paid call: the session of Claude Code answers the exported questions, a
subagent of another model judges (skill `evals-claude-code`), the code scores. Every step is
journaled by its digests (R11); the thresholds of `config/evals.yaml` are only read (R9).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from core.audit import AuditJournal, default_journal_path
from interfaces.cli.common import EXIT_ERROR, ConfigDirOpt, fail, project_root
from interfaces.cli.common import load as _load

claude_code_app = typer.Typer(
    help="Golden sets passés dans Claude Code, jugés par un autre modèle (ADR-074).",
    no_args_is_help=True,
)


def new_run(now: datetime) -> str:
    return f"{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


def _journal() -> AuditJournal:
    return AuditJournal(default_journal_path(project_root()))


@claude_code_app.command("exporter")
def export_command(
    pack: Annotated[str, typer.Option("--pack", help="Pack dont le golden set est passé.")],
    answer_model: Annotated[
        str,
        typer.Option(
            "--modele-reponse",
            help="Modèle de la session qui répondra (claude-opus-5-5, sonnet…) : jamais le juge.",
        ),
    ],
    cases: Annotated[
        list[str] | None, typer.Option("--cas", help="Un cas du golden set (répétable).")
    ] = None,
    limit: Annotated[
        int | None, typer.Option("--limite", min=1, help="Nombre maximal de cas exportés.")
    ] = None,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Écrit les questions d'un run : question et pages du cas, jamais ce qui est attendu."""
    # trafilatura and spaCy load with the cases: only for this command (as for `cerveau eval`)
    from core.evals.claude_code import ANSWERS_DIR, BENCH_DIR, QUESTIONS_DIR, BenchError, export_run

    config, root = _load(config_dir), project_root()
    now = datetime.now().astimezone()
    try:
        export = export_run(
            root,
            pack,
            run=new_run(now),
            now=now,
            config=config,
            journal=_journal(),
            answer_model=answer_model,
            only=cases or (),
            limit=limit,
        )
    except BenchError as exc:
        fail(f"ERREUR : {exc}", EXIT_ERROR)
    run = export.manifest["run"]
    typer.echo(f"Run {run} : {len(export.cases)} cas exporté(s) dans {export.directory}")
    for item in export.manifest["exclus"]:
        typer.echo(f"  exclu : {item['id']} ({item['raison']})")
    typer.echo(
        f"Questions : {BENCH_DIR / run / QUESTIONS_DIR} ; réponses : {ANSWERS_DIR}/<cas>.json"
    )
    typer.echo(f"Ensuite : `cerveau evals preparer-juge {run}`")


@claude_code_app.command("preparer-juge")
def judge_command(
    run: Annotated[str, typer.Argument(help="Identifiant du run.")],
    config_dir: ConfigDirOpt = None,
) -> None:
    """Contrôle les réponses et écrit un fichier anonyme par réponse pour le sous-agent juge."""
    from core.evals.claude_code import BENCH_DIR, JUDGE_DIR, VERDICTS_DIR, BenchError, prepare_judge

    try:
        files = prepare_judge(project_root(), run, config=_load(config_dir), journal=_journal())
    except BenchError as exc:
        fail(f"ERREUR : {exc}", EXIT_ERROR)
    for case_id, reason in files.refused.items():
        typer.echo(f"  non jugé : {case_id} ({reason})")
    typer.echo(f"{len(files.labels)} fichier(s) pour le juge : {BENCH_DIR / run / JUDGE_DIR}")
    for label in files.labels:
        typer.echo(f"  {JUDGE_DIR}/{label}.md → {VERDICTS_DIR}/{label}.json")
    typer.echo(f"Ensuite, verdicts écrits : `cerveau evals noter {run}`")


@claude_code_app.command("noter")
def score_command(
    run: Annotated[str, typer.Argument(help="Identifiant du run.")],
    report_copy: Annotated[
        Path | None,
        typer.Option("--report", help="Copie du rapport (chemin sans extension : .md et .json)."),
    ] = None,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Note le run : contrôles du code, notes du juge, seuils de config/evals.yaml (lus, R9).

    Codes de sortie : 0 portes franchies, 1 porte manquée ou run refusé.
    """
    from core.evals.claude_code import BenchError
    from core.evals.claude_code_score import score_run

    now = datetime.now().astimezone()
    try:
        scoring = score_run(
            project_root(),
            run,
            config=_load(config_dir),
            journal=_journal(),
            now=now,
            copy=report_copy,
        )
    except (BenchError, ValueError) as exc:
        fail(f"ERREUR : {exc}", EXIT_ERROR)
    typer.echo(f"Rapport : {', '.join(str(path) for path in scoring.written)}")
    for item in scoring.scored:
        result = item.result
        state = "réussi" if result.passed else "ÉCHEC"
        typer.echo(f"  {result.case_id} : {state}, score {result.score:.2f} ({result.reason()})")
    for gate in scoring.report.gates:
        status = "atteint" if gate.passed else "MANQUÉ"
        typer.echo(
            f"  {gate.suite} · {gate.name} : {gate.measured} (seuil {gate.threshold}) {status}"
        )
    if not scoring.report.passed:
        fail("Porte(s) manquée(s) : voir le rapport.", EXIT_ERROR)
