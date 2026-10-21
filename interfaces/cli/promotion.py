"""`cerveau promotion`: whether a live eval report proves an autonomy promotion rule (B107), and
the N2 → N3 promotion report (ADR-040, B181).

``check`` reads and writes nothing else; ``report`` writes only its report under
``var/promotion/`` and its journal entry. Lucas signs ``governance/approvals/`` and changes
``domains.<domain>.level`` in ``config/autonomy.yaml`` by hand, whatever they say.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from core.audit import AuditJournal, default_journal_path
from core.config import BlockedFeatureError
from core.evals.promotion import PromotionError, check_promotion, load_report
from core.governance.promotion_report import (
    STATUS_TEXT,
    VERDICT_TEXT,
    PromotionReportError,
    build_report,
    write_report,
)
from core.governance.signatures import REPORT_PASSED, signature_text
from interfaces.cli.common import (
    EXIT_BLOCKED,
    EXIT_ERROR,
    ConfigDirOpt,
    JournalOpt,
    project_root,
)
from interfaces.cli.common import blocked as _blocked
from interfaces.cli.common import fail as _fail
from interfaces.cli.common import load as _load

promotion_app = typer.Typer(
    help="Promotion d'autonomie : vérifier un rapport d'évals réel (B107), générer le rapport "
    "de promotion N2 → N3 (B181).",
    no_args_is_help=True,
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


MARKS = {"atteint": "✓", "non_atteint": "✗", "non_evaluable": "?", "sans_objet": "–"}


@promotion_app.command("report")
def report(
    domain: Annotated[str, typer.Argument(help="Le domaine : finance.")],
    to: Annotated[str, typer.Option("--to", help="Le niveau visé : N3.")],
    evals: Annotated[
        Path | None,
        typer.Option(
            "--evals",
            help="Le report.json d'une campagne d'évals réelle du domaine (var/evals/<campagne>/).",
        ),
    ] = None,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Génère le rapport de promotion finance N2 → N3 sous var/promotion/ (ADR-040, B181).

    Chaque critère y figure avec sa valeur, son seuil, son statut et l'outil source (R1). Rien
    n'est signé : si la promotion est possible, le texte de signature s'affiche et tu le copies
    toi-même dans governance/approvals/. Codes de sortie : 0 promotion possible, 1 promotion
    impossible ou rapport impossible, 2 critère non évaluable (R7).
    """
    config = _load(config_dir)
    root = project_root()
    now = datetime.now().astimezone()
    try:
        built = build_report(root, config, domain=domain, level=to, at=now, evals=evals)
        path = write_report(root, built)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except (PromotionReportError, OSError) as exc:
        _fail(f"Rapport impossible : {exc}", EXIT_ERROR)
    verdict = built.verdict
    relative = path.relative_to(root).as_posix()
    request_id = f"promotion-report-{uuid.uuid4().hex[:12]}"
    AuditJournal(default_journal_path(root)).append(
        actor="lucas",
        event="TOOL_CALL",
        request_id=request_id,
        versions={"config": config.digest},
        payload={
            "command": f"promotion report {domain} --to {to}",
            "statut": verdict,
            "rapport": relative,
            "rapport_sha256": digest,
            "criteres": {criterion.name: criterion.status for criterion in built.criteria},
        },
    )
    typer.echo(f"Rapport de promotion {domain} N2 → {built.level} : {relative}")
    typer.echo(f"SHA-256 : {digest} ; requête {request_id}")
    for criterion in built.criteria:
        typer.echo(
            f"{MARKS[criterion.status]} {criterion.name} : {criterion.value} "
            f"(seuil : {criterion.threshold}) : {STATUS_TEXT[criterion.status]}"
        )
    if verdict != REPORT_PASSED:
        code = EXIT_BLOCKED if verdict == "non_evaluable" else EXIT_ERROR
        _fail(f"Conclusion : {VERDICT_TEXT[verdict]}. Aucun texte de signature.", code)
    typer.echo(f"Conclusion : {VERDICT_TEXT[verdict]}.")
    typer.echo(
        f"Texte à copier toi-même, si tu signes, dans governance/approvals/"
        f"{now.date().isoformat()}-{domain}-{built.level}.md (la date du nom et de l'en-tête est "
        "celle du jour où tu signes) :"
    )
    typer.echo(signature_text(domain, built.level, now.date(), digest), nl=False)
    typer.echo(
        f"Le niveau écrit (domains.{domain}.level dans config/autonomy.yaml) se change aussi à la "
        "main ; le live reste une décision séparée."
    )
