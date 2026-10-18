"""`cerveau` command line: ask, eval, audit, config, registry."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, NoReturn

import typer

from core.audit import AuditJournal, default_journal_path, verify
from core.budget.gate import BudgetExceededError, BudgetGate
from core.config import FEATURES, BlockedFeatureError, ConfigError, load_config
from core.observability import build_tracer
from core.registry import validate_all, validate_plugin
from interfaces.cli import evaluate

if TYPE_CHECKING:
    from core.config.loader import Config
    from core.observability import Tracer
    from core.orchestrator.graph import Orchestrator, RunResult

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
ConfigDirOpt = Annotated[
    Path | None, typer.Option("--config-dir", help="Dossier de configuration (défaut : config/).")
]
EXIT_ERROR, EXIT_BLOCKED, EXIT_BUDGET = 1, 2, 3


def missing_keys(names: tuple[str, ...]) -> list[str]:
    """Names absent from the environment: a presence test, the values are never read (R6)."""
    return [name for name in names if name not in os.environ]


def _fail(message: str, code: int) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code)


def _load(config_dir: Path | None) -> Config:
    directory = config_dir or project_root() / "config"
    try:
        return load_config(directory)
    except ConfigError:
        _fail(f"Configuration invalide ({directory}) : lancer `cerveau config check`.", EXIT_ERROR)


def _blocked(exc: BlockedFeatureError) -> NoReturn:
    _fail(f"Bloqué (R7) : {exc}. Voir `cerveau config check`.", EXIT_BLOCKED)


def build_orchestrator(config: Config, root: Path, tracer: Tracer | None = None) -> Orchestrator:
    from core.orchestrator.graph import Orchestrator  # langgraph and spaCy load only for `ask`

    return Orchestrator(config, project_root=root, tracer=tracer)


def _decimal(value: object, places: int) -> str:
    return f"{value:.{places}f}".replace(".", ",")


def _footer(result: RunResult) -> str:
    return (
        f"— requête {result.request_id} · {_decimal(result.cost_eur, 4)} € · "
        f"{result.tokens} jetons · {result.tool_calls} appel(s) d'outil · "
        f"{_decimal(result.elapsed_s, 1)} s"
    )


@app.command("ask")
def ask(
    question: Annotated[str, typer.Argument(help="La question, entre guillemets.")],
    as_json: Annotated[
        bool, typer.Option("--json", help="Réponse en JSON (format 7.3) au lieu du Markdown.")
    ] = False,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Pose une question en lecture seule (N0) ; réponse sourcée au format 7.3.

    Codes de sortie : 0 réponse rendue, 1 erreur, 2 fonction bloquée (R7) ou clé absente,
    3 budget du jour ou du mois atteint (D9).
    """
    root = project_root()
    config = _load(config_dir)
    try:
        config.require("budgets")
    except BlockedFeatureError as exc:
        _blocked(exc)
    if missing_keys(("ANTHROPIC_API_KEY",)):
        _fail(
            "ANTHROPIC_API_KEY absente de l'environnement : à définir comme variable "
            "d'utilisateur (D7).",
            EXIT_BLOCKED,
        )
    if missing_keys(("BRAVE_SEARCH_API_KEY",)):
        typer.echo(
            "avertissement : BRAVE_SEARCH_API_KEY absente, recherche web indisponible.", err=True
        )
    tracer, tracing = build_tracer(os.environ)  # optional (ADR-004): never blocks a request
    if not tracing.enabled:
        typer.echo(f"avertissement : {tracing.reason}.", err=True)
    try:
        result = asyncio.run(build_orchestrator(config, root, tracer=tracer).ask(question))
    except BlockedFeatureError as exc:
        _blocked(exc)
    except BudgetExceededError as exc:
        _fail(f"Refus (D9) : {exc}", EXIT_BUDGET)
    except Exception as exc:  # already journaled as a DECISION with the status « erreur »
        lines = str(exc).splitlines()
        detail = f" : {lines[0][:300]}" if lines else ""
        typer.echo(f"ERREUR : {type(exc).__name__}{detail}", err=True)
        typer.echo("La requête est journalisée : `cerveau audit tail`.", err=True)
        raise typer.Exit(EXIT_ERROR) from exc
    finally:
        tracer.flush()
    for alert in result.budget_alerts:
        typer.echo(f"alerte budget : {alert}", err=True)
    typer.echo(result.json() if as_json else result.markdown(), nl=False)
    typer.echo(_footer(result), err=True)


@app.command("eval")
def eval_suites(
    suites: Annotated[
        list[str] | None,
        typer.Argument(help="Suites de evals/promptfoo/ (défaut : toutes)."),
    ] = None,
    live: Annotated[
        bool,
        typer.Option("--live", help="Vrais modèles, payant : campagne acceptée par Lucas (D8)."),
    ] = False,
    campaign: Annotated[
        str | None, typer.Option("--campaign", help="Nom de la campagne réelle acceptée.")
    ] = None,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Lance les suites d'évals promptfoo, hors ligne par défaut (ni clé ni appel payant).

    Codes de sortie : 0 suites réussies, 1 suite en échec ou erreur, 2 usage refusé ou fonction
    bloquée (R7), 3 budget du jour ou du mois atteint (D9).
    """
    root, names = project_root(), suites or []
    mode: evaluate.Mode = "live" if live else "offline"
    try:
        found = evaluate.find_suites(root, names)
        if live:
            campaign = evaluate.check_campaign(campaign, names)
        elif campaign is not None:
            raise evaluate.EvalUsageError("--campaign ne vaut qu'avec --live")
    except evaluate.EvalUsageError as exc:
        _fail(f"ERREUR : {exc}", EXIT_BLOCKED)
    if not found:
        _fail(f"Aucune suite dans {root / evaluate.SUITES_DIR}.", EXIT_ERROR)
    npx = shutil.which("npx")
    if npx is None:
        _fail("npx introuvable : installer Node.js pour promptfoo.", EXIT_ERROR)
    if campaign is not None:
        _open_campaign(_load(config_dir), root, campaign, found)
    env = evaluate.child_env(mode, root, os.environ, campaign)
    out_dir = root / evaluate.RUNS_DIR / (campaign or "offline")
    out_dir.mkdir(parents=True, exist_ok=True)
    failed = []
    for suite in found:
        typer.echo(f"Suite {suite.stem} ({'réelle' if live else 'hors ligne'})")
        command = evaluate.promptfoo_command(npx, suite, out_dir / f"{suite.stem}.json", mode)
        if evaluate.run_suite(command, env=env, cwd=root) != 0:
            failed.append(suite.stem)
    typer.echo(
        f"{len(found) - len(failed)}/{len(found)} suite(s) réussie(s) ; résultats : {out_dir}"
    )
    if failed:
        _fail(f"Suite(s) en échec : {', '.join(failed)}", EXIT_ERROR)


def _open_campaign(config: Config, root: Path, campaign: str, suites: list[Path]) -> None:
    """Budgets, key and journal entry of a live campaign, before any paid call (D8, R11)."""
    journal = AuditJournal(default_journal_path(root))
    request_id = f"eval-{campaign}"
    try:
        check = BudgetGate(config, journal).check(request_id=request_id)
    except BlockedFeatureError as exc:
        _blocked(exc)
    except BudgetExceededError as exc:
        _fail(f"Refus (D9) : {exc}", EXIT_BUDGET)
    if missing_keys(("ANTHROPIC_API_KEY",)):
        _fail("ANTHROPIC_API_KEY absente de l'environnement (D7).", EXIT_BLOCKED)
    for alert in check.highest():
        typer.echo(f"alerte budget : {alert.message()}", err=True)
    journal.append(
        actor="orchestrator",  # the spec fixes the actors of the journal (ACTORS)
        event="DECISION",
        request_id=request_id,
        versions={"config": config.digest},
        payload={
            "status": "campagne_eval",
            "campaign": campaign,
            "mode": "live",
            "suites": [suite.stem for suite in suites],
        },
    )


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
