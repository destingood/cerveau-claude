"""`cerveau paper` and `cerveau status`: the paper day by hand, and what stands (ADR-033, B54).

``paper run`` treats the decision day of now, never another (R10); ``paper envoyer`` sends the
intents Lucas approved since, as paper orders while the live is disabled (D10). ``status``,
``orders`` and ``report`` only read: a file that does not exist yet is reported, never created.
``acquitter`` is Lucas's alone, at an interactive terminal (D14).
"""

from __future__ import annotations

import uuid
from collections import Counter
from contextlib import ExitStack
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import typer

from core.audit import AuditJournal, default_journal_path
from core.config.loader import Config
from core.execution.book import OrderBook, Recorder, default_book_path
from core.execution.kill_switch import recorded_stop
from core.execution.loop import (
    LoopError,
    LoopLog,
    PaperDay,
    Valuation,
    default_loop_path,
    default_reports_dir,
    finish_day,
    render_sent,
    run_day,
    send_approved,
)
from core.execution.operations import PaperUnavailable, open_approvals, open_paper_day
from core.execution.reconcile import (
    ReconciliationError,
    ReconciliationLog,
    default_log_path,
    interactive_terminal,
)
from core.execution.sources import strategy_sources
from core.execution.states import OPEN
from core.policy.engine import kill_switch_engaged
from interfaces.cli.common import (
    EXIT_BLOCKED,
    EXIT_ERROR,
    EXIT_GAP,
    ConfigDirOpt,
    JournalOpt,
    OutsideVarOpt,
    alert_channels,
    fail,
    load,
    project_root,
    var_path,
)

paper_app = typer.Typer(
    help="Compte paper : journée, ordres, rapports, acquittement (ADR-033).", no_args_is_help=True
)

EXIT_CODES = {  # the others exit 0
    "attente_donnees": EXIT_GAP,
    "injoignable": EXIT_ERROR,
    "arret": EXIT_BLOCKED,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _request_id(kind: str) -> str:
    return f"{kind}-{uuid.uuid4().hex[:12]}"


@paper_app.command("run")
def run(
    journal: JournalOpt = None, config_dir: ConfigDirOpt = None, outside: OutsideVarOpt = False
) -> None:
    """Traite une fois la journée de décision de maintenant et écrit son rapport (ADR-033).

    Pas de --date : une date choisie à la main déciderait sur une séance dont la suite est
    connue (R10). Codes de sortie : 0 journée traitée, déjà traitée ou sans séance ; 1 erreur
    ou adaptateur sans réponse ;
    2 kill switch engagé ou paramètre à définir (R7) ; 4 clôture attendue absente de la base.
    """
    root = project_root()
    journal = var_path(journal, default_journal_path(root), option="--journal", outside=outside)
    config = load(config_dir)
    now = _now()
    request_id = _request_id("paper")
    audit = AuditJournal(journal)
    with ExitStack() as stack:
        env = _open_day(stack, root, config, audit, request_id, now)
        cutoff = config.research.execution.decision_cutoff_utc
        env.sources, refused = strategy_sources(root, env.store, cutoff)
        env.approvals, _ = open_approvals(stack, root, config, audit, request_id)  # N3 (ADR-036)
        try:
            report = run_day(env, now=now)
        except LoopError as exc:
            fail(f"Journée arrêtée : {exc}.", EXIT_ERROR)
        report.notes.extend(refused)
        text = finish_day(env, report)
    typer.echo(text)
    code = EXIT_CODES.get(report.outcome, 0)
    if code:
        raise typer.Exit(code)


@paper_app.command("envoyer")
def send(
    journal: JournalOpt = None, config_dir: ConfigDirOpt = None, outside: OutsideVarOpt = False
) -> None:
    """Envoie au simulateur les intentions approuvées par Lucas (ADR-036, D10).

    Chacune repasse la Porte de risque et la politique avant que son approbation soit consommée ;
    une approbation refusée, échue ou déjà consommée rejette l'intention, jamais envoyée. Codes
    de sortie : ceux de `cerveau paper run`.
    """
    root = project_root()
    journal = var_path(journal, default_journal_path(root), option="--journal", outside=outside)
    config = load(config_dir)
    now = _now()
    request_id = _request_id("send")
    audit = AuditJournal(journal)
    with ExitStack() as stack:
        env = _open_day(stack, root, config, audit, request_id, now)
        env.approvals, closed = open_approvals(stack, root, config, audit, request_id)
        report = send_approved(env, now=now)
    if closed is not None:
        report.notes.append(closed)
    for line in render_sent(report):
        typer.echo(line)
    code = EXIT_CODES.get(report.outcome, 0)
    if code:
        raise typer.Exit(code)


def _open_day(
    stack: ExitStack,
    root: Path,
    config: Config,
    audit: AuditJournal,
    request_id: str,
    now: datetime,
) -> PaperDay:
    """The paper account's files, opened in ``stack``; without sources nor approval store."""
    try:
        return open_paper_day(
            stack, root, config, audit, request_id, now, alerts=alert_channels(config, root)
        )
    except PaperUnavailable as exc:
        if exc.blocked:
            fail(f"Bloqué (R7) : {exc}. Voir `cerveau config check`.", EXIT_BLOCKED)
        fail(f"Base finance : {exc}", EXIT_ERROR)


def _paper_lines(root: Path) -> list[str]:
    """The paper account from its files, opened read-only or not at all."""
    loop = default_loop_path(root)
    days: list[date] = []
    valuations: list[Valuation] = []
    if loop.is_file():
        with LoopLog.open(loop) as log:
            days, valuations = log.days(), log.valuations()
    last_day = f", la dernière le {days[-1]:%d/%m/%Y}" if days else ""
    lines = [f"Paper : {len(days)} journée(s) traitée(s){last_day}."]
    if valuations:
        last = valuations[-1]
        lines.append(
            f"Dernière valorisation ({last.day:%d/%m/%Y}, source : journal de la boucle) : "
            f"{last.equity_eur} € dont {last.cash_eur} € de liquidités, "
            f"{len(last.positions)} position(s)."
        )
    book = default_book_path(root)
    if book.is_file():
        with OrderBook.open(book, read_only=True) as opened:
            states = Counter(order.state for order in opened.orders())
        live = sum(count for state, count in states.items() if state in OPEN)
        lines.append(f"Ordres ouverts au carnet : {live} sur {sum(states.values())}.")
    gaps = default_log_path(root)
    if gaps.is_file():
        audit = AuditJournal(default_journal_path(root))  # read only: nothing is recorded
        recorder = Recorder(audit, "lucas", _request_id("status"))
        with ReconciliationLog.open(gaps, recorder) as rec:
            count, waiting = rec.open_gaps(), rec.awaiting_acknowledgement()
        if waiting:
            lines.append(
                f"Réconciliation : {count} écart(s) à acquitter (`cerveau paper acquitter`)."
            )
        elif count:
            lines.append(f"Réconciliation : {count} écart(s) ouverts, intentions bloquées.")
        else:
            lines.append("Réconciliation : aucun écart ouvert.")
    return lines


@paper_app.command("status")
def paper_status() -> None:
    """État du compte paper, en lecture seule : rien n'est créé ni journalisé."""
    for line in _paper_lines(project_root()):
        typer.echo(line)


@paper_app.command("orders")
def orders(
    tous: Annotated[
        bool, typer.Option("--tous", help="Tous les ordres, pas seulement les ouverts.")
    ] = False,
) -> None:
    """Ordres du carnet paper, en lecture seule."""
    path = default_book_path(project_root())
    if not path.is_file():
        typer.echo("Carnet vide : aucune journée n'a encore rédigé d'ordre.")
        return
    with OrderBook.open(path, read_only=True) as book:
        booked = book.orders(None if tous else OPEN)
    if not booked:
        typer.echo("Aucun ordre." if tous else "Aucun ordre ouvert.")
    for order in booked:
        intent = order.intent
        typer.echo(
            f"{intent.decision_date:%d/%m/%Y} {intent.side} {intent.quantity} "
            f"{intent.instrument.symbol} limite {intent.limit_price} {intent.instrument.currency} "
            f": {order.state.value}, exécuté {order.filled} ({intent.origin.kind}, "
            f"{str(intent.intent_id)[:8]}…)"
        )


@paper_app.command("report")
def report(
    jour: Annotated[
        str | None,
        typer.Option("--date", help="Jour du rapport, AAAA-MM-JJ (défaut : le dernier)."),
    ] = None,
) -> None:
    """Affiche le rapport d'une journée paper (lecture seule)."""
    directory = default_reports_dir(project_root())
    if jour is None:
        found = sorted(directory.glob("????-??-??.md")) if directory.is_dir() else []
        if not found:
            fail("Aucun rapport paper : lancer `cerveau paper run`.", EXIT_ERROR)
        path = found[-1]
    else:
        try:
            path = directory / f"{date.fromisoformat(jour).isoformat()}.md"
        except ValueError:
            fail(f"Date invalide : {jour} (attendu AAAA-MM-JJ).", EXIT_ERROR)
        if not path.is_file():
            fail(f"Aucun rapport pour le {jour}.", EXIT_ERROR)
    typer.echo(path.read_text(encoding="utf-8"))


@paper_app.command("acquitter")
def acknowledge(journal: JournalOpt = None, outside: OutsideVarOpt = False) -> None:
    """Lève le blocage après un écart réconcilié : Lucas seul, en terminal interactif (D14)."""
    root = project_root()
    journal = var_path(journal, default_journal_path(root), option="--journal", outside=outside)
    path = default_log_path(root)
    if not path.is_file():
        fail("Aucune réconciliation enregistrée : rien à acquitter.", EXIT_ERROR)
    audit = AuditJournal(journal)
    with ReconciliationLog.open(path, Recorder(audit, "lucas", _request_id("ack"))) as log:
        try:
            gaps = log.acknowledge(interactive=interactive_terminal)
        except ReconciliationError as exc:
            fail(f"{exc}.", EXIT_BLOCKED)
    typer.echo(f"{gaps} écart(s) acquitté(s) : les intentions reprennent selon la politique.")


def status_command(config_dir: ConfigDirOpt = None) -> None:
    """État de CERVEAU en lecture seule : kill switch, live, autonomie, compte paper (B54)."""
    root = project_root()
    if kill_switch_engaged(root):  # before the config: a stop is reported even if it is invalid
        stop = recorded_stop(root)
        detail = f"{stop.trigger}, {stop.engaged_at}" if stop else "fichier KILL créé à la main"
        typer.echo(f"Kill switch : ENGAGÉ ({detail}) ; réarmement par Lucas (`cerveau rearm`).")
    else:
        typer.echo("Kill switch : armé.")
    config = load(config_dir)
    live = "ACTIVÉ" if config.live.enabled else "désactivé"
    typer.echo(f"Live : {live} (config/live.yaml, R3).")
    for name, domain in sorted(config.autonomy.domains.items()):
        typer.echo(f"Autonomie {name} : {domain.level} (plafond {domain.max_level}).")
    for line in _paper_lines(root):
        typer.echo(line)
