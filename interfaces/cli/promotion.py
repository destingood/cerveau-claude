"""`cerveau promotion`: whether a live eval report proves an autonomy promotion rule (B107).

The check reads and writes nothing else: Lucas signs ``governance/approvals/`` and changes
``domains.<domain>.level`` in ``config/autonomy.yaml`` by hand, whatever it says.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from core.audit import AuditJournal, default_journal_path
from core.config import BlockedFeatureError
from core.evals.promotion import PromotionError, check_promotion, load_report
from interfaces.cli.common import EXIT_ERROR, ConfigDirOpt, JournalOpt, project_root
from interfaces.cli.common import blocked as _blocked
from interfaces.cli.common import fail as _fail
from interfaces.cli.common import load as _load

promotion_app = typer.Typer(
    help="Promotion d'autonomie : vérifier un rapport d'évals réel (B107).", no_args_is_help=True
)


@promotion_app.command("check")
def check(
    domain: Annotated[str, typer.Argument(help="Le domaine, par exemple finance.")],
    level: Annotated[str, typer.Argument(help="Le niveau visé, par exemple N1.")],
    report: Annotated[
        Path,
        typer.Option("--report", help="Le report.json d'un run réel (var/evals/<campagne>/)."),
    ],
    approval: Annotated[
        Path | None,
        typer.Option("--approval", help="Le texte d'approbation, pour vérifier ce qu'il cite."),
    ] = None,
    journal: JournalOpt = None,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Vérifie qu'un rapport d'évals réel prouve la règle de promotion (D16, B107).

    Rien n'est modifié : la signature et le changement de niveau restent à Lucas, à la main.
    Codes de sortie : 0 règle prouvée, 1 règle non prouvée ou rapport illisible, 2 règle
    bloquée par un A_DEFINIR (R7).
    """
    config = _load(config_dir)
    root = project_root()
    try:
        data = load_report(report)
        signed = approval.read_text(encoding="utf-8") if approval is not None else None
        result = check_promotion(
            data,
            config,
            domain=domain,
            level=level,
            journal=AuditJournal(journal or default_journal_path(root)),
            now=datetime.now().astimezone(),
            root=root,
            approval=signed,
        )
    except BlockedFeatureError as exc:
        _blocked(exc)
    except (PromotionError, OSError, UnicodeDecodeError) as exc:
        _fail(f"Vérification impossible : {exc}", EXIT_ERROR)
    typer.echo(f"Promotion {domain} → {level} : rapport {report}")
    for item in result.checks:
        mark = "✓" if item.passed else "✗"
        typer.echo(f"{mark} {item.name} : {item.measured} (attendu : {item.expected})")
    if not result.passed:
        _fail("Règle non prouvée par ce rapport : pas de promotion.", EXIT_ERROR)
    typer.echo(
        "Règle prouvée par ce rapport. La signature (governance/approvals/) et le changement de "
        "niveau (config/autonomy.yaml) restent à Lucas, à la main."
    )
