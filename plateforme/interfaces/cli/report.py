"""`cerveau report`: the scheduled weekly and monthly security reports (ADR-066).

``weekly`` writes ``evals/reports/hebdo-<week>.md`` and a ``scheduler`` journal entry; a failed
report also raises a ``rapport_planifie_en_echec`` alert and exits 1, so the scheduled task fails
visibly. ``security`` writes ``docs/rapports/securite-<month>.md``. ``streak`` counts the
consecutive weeks whose report is ``ok`` (the phase closes after four, §17).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer

from core.audit import AuditError, AuditJournal, default_journal_path
from core.governance.demotion import DemotionError, demote, gate_domains
from core.governance.signatures import effective_autonomy
from core.learning.champion import default_history_path
from core.learning.forecasts import default_forecasts_path
from core.notify.alerts import Alert
from core.reports.security import build_security, security_path
from core.reports.weekly import (
    FAILED,
    ReportError,
    build_weekly,
    record,
    streak,
    weekly_path,
)
from interfaces.cli.common import (
    EXIT_ERROR,
    ConfigDirOpt,
    JournalOpt,
    OutsideVarOpt,
    alert_channels,
    fail,
    load,
    project_root,
    var_path,
)

report_app = typer.Typer(
    help="Rapports planifiés : hebdomadaire et sécurité mensuelle (écrits sans LLM).",
    no_args_is_help=True,
)

EVAL_REPORT = Path("var") / "evals" / "offline" / "report.json"
SECURITY_STATUS = "rapport_securite"


def _now() -> datetime:
    return datetime.now(UTC)


def _journal(journal: Path | None, outside: bool) -> AuditJournal:
    default = default_journal_path(project_root())
    return AuditJournal(var_path(journal, default, option="--journal", outside=outside))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@report_app.command("weekly")
def weekly_command(
    journal: JournalOpt = None,
    outside: OutsideVarOpt = False,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Rapport de la dernière semaine ISO complète ; échec = alerte et code 1."""
    root = project_root()
    audit = _journal(journal, outside)
    now = _now()
    weekly = build_weekly(
        root,
        audit,
        now,
        eval_report=root / EVAL_REPORT,
        forecasts=default_forecasts_path(root),
        history=default_history_path(root),
    )
    text = weekly.markdown()
    path = weekly_path(root, weekly.week)
    _write(path, text)
    try:
        record(audit, weekly, text, now)
    except AuditError as exc:
        fail(f"Journal d'audit : {exc}", EXIT_ERROR)
    typer.echo(f"Rapport {weekly.week.id} : {weekly.status} ({path})")
    for reason in weekly.reasons:
        typer.echo(f"  - {reason}")
    if weekly.missed_gates:
        _demote(config_dir, root, audit, weekly.missed_gates, f"hebdo-{weekly.week.id}", now)
    if weekly.status == FAILED:
        _alert(config_dir, root, audit, f"hebdo-{weekly.week.id}", now)
        raise typer.Exit(EXIT_ERROR)


def _demote(
    config_dir: Path | None,
    root: Path,
    audit: AuditJournal,
    missed: list[str],
    ref: str,
    now: datetime,
) -> None:
    """A missed eval gate demotes its domains by one level (section 8.3, ADR-067)."""
    autonomy = load(config_dir).autonomy
    effective = effective_autonomy(autonomy, root).autonomy.domains
    hit = gate_domains(missed, effective)
    try:
        done = demote(
            root,
            audit,
            levels={d: effective[d].level for d in hit},
            trigger="nightly_eval_failure",
            triggers=autonomy.demotion_triggers,
            reason=f"{ref} : {len(missed)} seuil(s) manqué(s)",
            now=now,
            once=f"{ref} : ",
        )
    except (AuditError, DemotionError, OSError) as exc:
        fail(f"Rétrogradation impossible : {exc}", EXIT_ERROR)
    for d in done:
        typer.echo(f"Rétrogradé : {d.domain} {d.from_level} → {d.to_level} ({d.trigger})")


def _alert(
    config_dir: Path | None, root: Path, audit: AuditJournal, ref: str, now: datetime
) -> None:
    alerts = alert_channels(load(config_dir), root)
    failures = alerts.send(
        [Alert.of("rapport_planifie_en_echec", ref, now)],
        journal=audit,
        actor="scheduler",
        request_id=ref,
        now=now,
    )
    for failure in failures:
        typer.echo(f"AVERTISSEMENT : alerte non envoyée ({failure})", err=True)


@report_app.command("security")
def security_command(
    journal: JournalOpt = None,
    outside: OutsideVarOpt = False,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Rapport de sécurité du mois : contrôles locaux et écart au modèle de menaces."""
    root = project_root()
    audit = _journal(journal, outside)
    now = _now()
    security = build_security(root, now)
    path = security_path(root, security.month)
    _write(path, security.markdown())
    try:
        audit.append(
            actor="scheduler",
            event="DECISION",
            request_id=f"securite-{security.month}",
            payload={
                "status": SECURITY_STATUS,
                "month": security.month,
                "result": security.status,
                "failed": security.failed,
            },
            now=now,
        )
    except AuditError as exc:
        fail(f"Journal d'audit : {exc}", EXIT_ERROR)
    typer.echo(f"Sécurité {security.month} : {security.status} ({path})")
    for name in security.failed:
        typer.echo(f"  - en échec : {name}")
    if security.status == FAILED:
        _alert(config_dir, root, audit, f"securite-{security.month}", now)
        raise typer.Exit(EXIT_ERROR)


@report_app.command("streak")
def streak_command(journal: JournalOpt = None, outside: OutsideVarOpt = False) -> None:
    """Semaines consécutives dont le rapport hebdomadaire est « ok »."""
    try:
        count = streak(_journal(journal, outside), _now())
    except ReportError as exc:
        fail(f"Journal d'audit : {exc}", EXIT_ERROR)
    typer.echo(f"Semaines consécutives sans échec : {count} (clôture de phase : 4)")
