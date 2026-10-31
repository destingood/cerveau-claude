"""`cerveau` command line: ask, feedback, eval, audit, config, registry, finance, portfolio,
strategy, committee, promotion, forecast, learn, paper, approvals, api, status, kill, rearm."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from core.audit import AuditError, AuditJournal, default_journal_path, verify
from core.budget.gate import BudgetExceededError, BudgetGate
from core.config import FEATURES, BlockedFeatureError, ConfigError, load_config
from core.finance.research.registry import RegistryError
from core.governance.signatures import effective_autonomy, promoted_domains
from core.learning import FeedbackError, default_feedback_path, give_feedback
from core.learning.feedback import NotePseudonymiser
from core.notify import alerts_from
from core.observability import build_tracer
from core.orchestrator.packs import PACKS_DIR, PackError, load_packs, pack_problems
from core.registry import validate_all, validate_plugin
from interfaces.cli import evaluate
from interfaces.cli.api import api_app
from interfaces.cli.approvals import approvals_app
from interfaces.cli.committee import committee_app
from interfaces.cli.common import (
    EXIT_BLOCKED,
    EXIT_BUDGET,
    EXIT_ERROR,
    ConfigDirOpt,
    JournalOpt,
    project_root,
)
from interfaces.cli.common import blocked as _blocked
from interfaces.cli.common import fail as _fail
from interfaces.cli.common import load as _load
from interfaces.cli.cyber import cyber_app
from interfaces.cli.finance import finance_app
from interfaces.cli.forecast import forecast_app
from interfaces.cli.kill_switch import kill_command, rearm_command
from interfaces.cli.learn import learn_app
from interfaces.cli.paper import paper_app, status_command
from interfaces.cli.portfolio import portfolio_app
from interfaces.cli.promotion import promotion_app
from interfaces.cli.report import report_app
from interfaces.cli.strategy import registry_errors, strategy_app

if TYPE_CHECKING:
    from core.config.loader import AutonomyConfig, Config
    from core.observability import Tracer
    from core.orchestrator.graph import Orchestrator, RunResult

app = typer.Typer(help="CERVEAU : plateforme d'IA personnelle.", no_args_is_help=True)
audit_app = typer.Typer(help="Journal d'audit chaîné (R11).", no_args_is_help=True)
config_app = typer.Typer(help="Configuration et marqueurs bloquants (R7).", no_args_is_help=True)
registry_app = typer.Typer(help="Registre de plugins (R8).", no_args_is_help=True)
app.add_typer(audit_app, name="audit")
app.add_typer(config_app, name="config")
app.add_typer(registry_app, name="registry")
app.add_typer(finance_app, name="finance")
app.add_typer(cyber_app, name="cyber")
app.add_typer(portfolio_app, name="portfolio")
app.add_typer(strategy_app, name="strategy")
app.add_typer(committee_app, name="committee")
app.add_typer(promotion_app, name="promotion")
app.add_typer(forecast_app, name="forecast")
app.add_typer(learn_app, name="learn")
app.add_typer(report_app, name="report")
app.add_typer(paper_app, name="paper")
app.add_typer(approvals_app, name="approvals")
app.add_typer(api_app, name="api")
app.command("status")(status_command)
app.command("kill")(kill_command)
app.command("rearm")(rearm_command)


@app.callback()
def main() -> None:
    # Redirected output on Windows defaults to cp1252; French messages must stay readable.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def missing_keys(names: tuple[str, ...]) -> list[str]:
    """Names absent from the environment: a presence test, the values are never read (R6)."""
    return [name for name in names if name not in os.environ]


def build_orchestrator(config: Config, root: Path, tracer: Tracer | None = None) -> Orchestrator:
    from core.orchestrator.graph import Orchestrator  # langgraph and spaCy load only for `ask`

    alerts, _ = alerts_from(config, root, os.environ)  # `cerveau config check` says what is off
    return Orchestrator(config, project_root=root, tracer=tracer, alerts=alerts)


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
    comite: Annotated[
        bool,
        typer.Option("--comite", help="Réunir le Comité d'investissement du pack (finance, D15)."),
    ] = False,
    approfondi: Annotated[
        bool,
        typer.Option(
            "--approfondi",
            help="Recherche approfondie du pack recherche, citations vérifiées (ADR-045, D14).",
        ),
    ] = False,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Pose une question en lecture seule (N0) ; réponse sourcée au format 7.3.

    Une question de décision en finance (« dois-je vendre… ») ou --comite réunit le Comité :
    analyse en N0, proposition non exécutée en N1, jamais un ordre (R16). --approfondi lance la
    recherche approfondie : plan en sous-questions, lectures bornées, affirmations sans extrait
    vérifié retirées et listées.

    Codes de sortie : 0 réponse rendue, 1 erreur, 2 fonction bloquée (R7) ou clé absente,
    3 budget du jour ou du mois atteint (D9).
    """
    if comite and approfondi:
        _fail("--comite et --approfondi s'excluent : choisis l'un des deux.", EXIT_ERROR)
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
        orchestrator = build_orchestrator(config, root, tracer=tracer)
        result = asyncio.run(orchestrator.ask(question, committee=comite, research=approfondi))
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


class Verdict(StrEnum):
    BON = "bon"
    MAUVAIS = "mauvais"


def note_pseudonymiser(config_dir: Path | None) -> Callable[[], NotePseudonymiser]:
    """Presidio, loaded only for a note: a bare verdict works while the PII threshold is unset."""

    def load() -> NotePseudonymiser:
        from core.guardrails.pii import PiiAnalyzer, PiiUnavailableError, Pseudonymiser

        config = _load(config_dir)
        try:
            return Pseudonymiser(PiiAnalyzer.from_config(config))
        except PiiUnavailableError as exc:
            _fail(f"Note bloquée : pseudonymisation indisponible ({exc}).", EXIT_BLOCKED)

    return load


@app.command("feedback")
def feedback(
    request_id: Annotated[
        str, typer.Argument(help="L'identifiant affiché sous la réponse (« — requête … »).")
    ],
    verdict: Annotated[Verdict, typer.Argument(help="bon ou mauvais.")],
    note: Annotated[
        str | None, typer.Argument(help="Note libre, pseudonymisée avant d'être gardée (R6).")
    ] = None,
    journal: JournalOpt = None,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Note une réponse de `cerveau ask` : bon ou mauvais, avec une note facultative (ADR-011).

    Le verdict va au journal d'audit ; la note, nettoyée, secrets masqués et pseudonymisée, va
    dans var/feedback/, hors du journal, comme donnée non fiable (R5). Codes de sortie : 0 retour
    enregistré, 1 refus (requête inconnue, note trop longue, journal illisible), 2 note bloquée
    tant que la pseudonymisation n'est pas configurée (R7).
    """
    root = project_root()
    audit = AuditJournal(journal or default_journal_path(root))
    try:
        entry = give_feedback(
            audit,
            default_feedback_path(root),
            request_id,
            verdict.value,
            note,
            pseudonymiser=note_pseudonymiser(config_dir),
        )
    except BlockedFeatureError as exc:
        _blocked(exc)
    except (FeedbackError, AuditError) as exc:
        _fail(f"Refus : {exc}", EXIT_ERROR)
    typer.echo(f"Retour « {verdict.value} » enregistré pour la requête {request_id}.")
    counts = audit.read_payload(entry["payload_ref"])["note"]
    if counts is not None:
        masked = sum(counts["pii"].values())
        typer.echo(
            f"Note gardée hors du journal : {masked} donnée(s) personnelle(s) pseudonymisée(s), "
            f"{counts['secrets_masked']} secret(s) masqué(s)."
        )


@app.command("eval")
def eval_suites(
    suites: Annotated[
        list[str] | None,
        typer.Argument(help="Suites de evals/promptfoo/ (défaut : toutes)."),
    ] = None,
    live: Annotated[
        bool,
        typer.Option(
            "--live", help="Vrais modèles, payant : campagne acceptée par l'utilisateur (D8)."
        ),
    ] = False,
    campaign: Annotated[
        str | None, typer.Option("--campaign", help="Nom de la campagne réelle acceptée.")
    ] = None,
    report_copy: Annotated[
        Path | None,
        typer.Option("--report", help="Copie du rapport (chemin sans extension : .md et .json)."),
    ] = None,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Lance les suites d'évals promptfoo, hors ligne par défaut (ni clé ni appel payant).

    Les suites de CERVEAU (golden, behaviors, injection) sont jugées par les seuils du rapport,
    écrit dans le dossier du run. Codes de sortie : 0 seuils atteints, 1 suite en échec, seuil
    manqué ou erreur, 2 usage refusé ou fonction bloquée (R7), 3 budget atteint (D9).
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
    run = evaluate.new_run_id(datetime.now().astimezone())
    out_dir = root / evaluate.RUNS_DIR / (campaign or "offline")
    out_dir.mkdir(parents=True, exist_ok=True)
    env = evaluate.child_env(
        mode, root, os.environ, campaign, out_dir=out_dir, run=run, config_dir=config_dir
    )
    failed = []
    for suite in found:
        typer.echo(f"Suite {suite.stem} ({'réelle' if live else 'hors ligne'})")
        command = evaluate.promptfoo_command(npx, suite, out_dir / f"{suite.stem}.json", mode)
        if evaluate.run_suite(command, env=env, cwd=root) not in evaluate.accepted_codes(suite):
            failed.append(suite.stem)
    typer.echo(f"{len(found) - len(failed)}/{len(found)} suite(s) exécutée(s) ; run {run}")
    measured = [suite.stem for suite in found if evaluate.is_measured(suite)]
    missed = _eval_report(measured, out_dir, mode, run, campaign, config_dir, report_copy)
    if failed:
        _fail(f"Suite(s) en échec : {', '.join(failed)}", EXIT_ERROR)
    if missed:
        _fail(f"Seuil(s) manqué(s) : {', '.join(missed)}", EXIT_ERROR)


def _eval_report(
    suites: list[str],
    out_dir: Path,
    mode: evaluate.Mode,
    run: str,
    campaign: str | None,
    config_dir: Path | None,
    copy: Path | None,
) -> list[str]:
    """Writes the run's report and returns the gates it misses (R9: thresholds as declared)."""
    if not suites:
        return []
    from core.evals.promotion import seal_report
    from core.evals.report import build_report, write_report

    config = _load(config_dir)
    report = build_report(
        out_dir,
        suites,  # type: ignore[arg-type]  # names checked by evaluate.is_measured
        mode=mode,
        run=run,
        config=config,
        campaign=campaign,
        root=project_root(),
    )
    bases = [out_dir / evaluate.REPORT_NAME, *([copy] if copy is not None else [])]
    written = write_report(report, *bases)
    typer.echo(f"Rapport : {', '.join(str(path) for path in written)}")
    if campaign is not None:  # an edited live report proves nothing (`cerveau promotion check`)
        content = json.loads(json.dumps(report.to_json()))  # the report as its file reads back
        journal = AuditJournal(default_journal_path(project_root()))
        digest = seal_report(journal, content, campaign=campaign, run=run, config=config.digest)
        typer.echo(f"Rapport scellé dans le journal d'audit : {digest}")
    missed = [f"{gate.suite} · {gate.name}" for gate in report.gates if not gate.passed]
    for gate in report.gates:
        status = "atteint" if gate.passed else "MANQUÉ"
        typer.echo(
            f"  {gate.suite} · {gate.name} : {gate.measured} (seuil {gate.threshold}) {status}"
        )
    return missed


def _open_campaign(config: Config, root: Path, campaign: str, suites: list[Path]) -> None:
    """Budgets, key and journal entry of a live campaign, before any paid call (D8, R11)."""
    journal = AuditJournal(default_journal_path(root))
    request_id = f"eval-{campaign}"
    try:
        alerts, _ = alerts_from(config, root, os.environ)
        check = BudgetGate(config, journal, alerts=alerts).check(request_id=request_id)
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


def _echo_packs(config: Config, effective: AutonomyConfig) -> None:
    """Each pack's status and levels (ADR-043); a pack the configuration lacks fails the check."""
    try:
        packs = load_packs(PACKS_DIR)  # the folder the orchestrator reads (ADR-043)
    except PackError as exc:
        typer.echo(f"\nPacks de domaine invalides : {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo("\nPacks de domaine (ADR-043 ; seul l'utilisateur passe un pack à « actif ») :")
    for pack in packs.values():
        written = config.autonomy.domains.get(pack.id)
        levels = (
            "domaine absent"
            if written is None
            else f"écrit {written.level}, effectif {effective.domains[pack.id].level}"
        )
        status = "expérimental" if pack.experimental else "actif"
        typer.echo(f"  · {pack.id} : {status}, {levels}")
    problems = pack_problems(packs, config)
    for problem in problems:
        typer.echo(f"  ✗ {problem}", err=True)
    if problems:
        raise typer.Exit(1)


@config_app.command("check")
def config_check(
    config_dir: Annotated[Path | None, typer.Option("--config-dir")] = None,
) -> None:
    """Valide config/*.yaml, liste les fonctions bloquées par A_DEFINIR / A_VERIFIER et
    contrôle le registre des stratégies (promotion manuelle, ADR-027)."""
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
    effective = effective_autonomy(config.autonomy, project_root())
    typer.echo("\nNiveaux effectifs (ADR-036 : min(niveau écrit, plus haut niveau signé)) :")
    for domain, spec in sorted(config.autonomy.domains.items()):
        level = effective.autonomy.domains[domain].level
        signed = " (signature requise)" if domain in promoted_domains(config.autonomy) else ""
        typer.echo(f"  · {domain} : écrit {spec.level}, effectif {level}{signed}")
    for problem in effective.problems:
        typer.echo(f"  ⚠ signature ignorée : {problem}")
    _echo_packs(config, effective.autonomy)
    alerts, notes = alerts_from(config, project_root(), os.environ)
    channels = ", ".join(c.channel for c in alerts.channels) or "aucun (journal et console)"
    typer.echo(f"\nCanaux d'alerte (ADR-038) : {channels}")
    for note in notes:
        typer.echo(f"  ⚠ {note}")
    try:
        count, refusals = registry_errors(project_root())
    except RegistryError as exc:
        typer.echo(f"\nRegistre des stratégies invalide : {exc}", err=True)
        raise typer.Exit(1) from exc
    verdict = "promotions refusées" if refusals else "conforme"
    typer.echo(f"\nRegistre des stratégies ({count}) : {verdict}")
    for refusal in refusals:
        typer.echo(f"  ✗ {refusal}", err=True)
    if refusals:
        raise typer.Exit(1)


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


def run() -> None:
    """The ``cerveau`` command. Its output is UTF-8 even through a pipe, where Windows would
    write cp1252 and fail on « → » (B227)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    app()


if __name__ == "__main__":
    run()
