"""`cerveau finance sync`: Lucas fills the point-in-time store; every run is journaled.

This is the only writer of the finance store (ADR-012) and the only one that reaches the network
for market data (ADR-017): the finance MCP tools read the store and nothing else.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import httpx
import typer

from core.audit import AuditJournal, default_journal_path
from core.config import BlockedFeatureError
from core.finance.model import local_date
from core.finance.providers import (
    CsvCloses,
    CsvCorporateActions,
    EcbProvider,
    MarketDataProvider,
    ProviderError,
)
from core.finance.providers.ecb import ESTR_CATEGORY, ESTR_SERIES_ID, FX_CATEGORY
from core.finance.quality import QualityReport
from core.finance.store import FinanceStore, FinanceStoreError, default_store_path
from core.finance.sync import (
    SyncResult,
    default_start,
    import_instruments,
    reference,
    reference_currencies,
    sync,
)
from interfaces.cli.common import (
    EXIT_ERROR,
    ConfigDirOpt,
    JournalOpt,
    blocked,
    fail,
    load,
    project_root,
)

if TYPE_CHECKING:
    from core.config.loader import Config

finance_app = typer.Typer(
    help="Pack Finance : données de marché point-in-time.", no_args_is_help=True
)
sync_app = typer.Typer(
    help="Remplit la base finance ; chaque synchronisation est journalisée (R11).",
    no_args_is_help=True,
)
finance_app.add_typer(sync_app, name="sync")

StoreOpt = Annotated[
    Path | None, typer.Option("--store", help="Base finance (défaut : var/finance/finance.db).")
]
FileArg = Annotated[
    Path, typer.Argument(exists=True, dir_okay=False, readable=True, help="Fichier CSV.")
]


def now() -> datetime:
    return datetime.now(UTC)


def ecb_transport() -> httpx.BaseTransport | None:
    """The HTTP transport of the ECB provider: None is the network; tests replace it."""
    return None


@contextmanager
def _store(path: Path | None) -> Iterator[FinanceStore]:
    with FinanceStore.open(path or default_store_path(project_root())) as store:
        yield store


def _run(
    command: str, journal: Path | None, config: Config, action: Callable[[], SyncResult]
) -> SyncResult:
    """Run a sync and journal it (R11): its counts and scores, or why it was refused."""
    audit = AuditJournal(journal or default_journal_path(project_root()))
    request_id = f"finance-sync-{uuid.uuid4().hex[:12]}"
    entry: dict[str, Any] = {"command": f"finance sync {command}"}
    try:
        result = action()
    except (ProviderError, FinanceStoreError) as exc:
        # These messages never quote a downloaded value (R5): see providers.base.
        audit.append(
            actor="lucas",
            event="ERROR",
            request_id=request_id,
            versions={"config": config.digest},
            payload={**entry, "error": str(exc)},
        )
        fail(f"Refus : {exc}. Rien n'est enregistré ; requête {request_id}.", EXIT_ERROR)
    audit.append(
        actor="lucas",
        event="TOOL_CALL",
        request_id=request_id,
        versions={"config": config.digest},
        payload={**entry, **result.journal_payload()},
    )
    _summary(result, request_id)
    return result


def _decimal(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _quality_line(report: QualityReport) -> str:
    if report.score is not None:
        return f"  · {report.instrument_id} : {_decimal(report.score)}"
    missing = ", ".join(sorted(report.details.not_evaluated)) or "?"
    return f"  · {report.instrument_id} : non évaluable ({missing})"


def _summary(result: SyncResult, request_id: str) -> None:
    report = result.report
    typer.echo(
        f"{result.source} : {result.received} enregistrement(s) reçu(s) — "
        f"{report.inserted} nouveau(x), {report.revised} révisé(s), "
        f"{report.unchanged} inchangé(s)."
    )
    if result.redated:
        typer.echo(f"{result.redated} révision(s) datée(s) à la récupération (ADR-017).")
    if result.quality or result.not_assessed:
        typer.echo("Qualité des séries (score strict, ADR-016) :")
        for quality in result.quality:
            typer.echo(_quality_line(quality))
        for instrument_id, reason in sorted(result.not_assessed.items()):
            typer.echo(f"  · {instrument_id} : non évaluée ({reason})")
    typer.echo(f"Journalisé : requête {request_id} (`cerveau audit tail`).")


def _sync(
    store: FinanceStore, config: Config, provider: Callable[[], MarketDataProvider]
) -> Callable[[], SyncResult]:
    return lambda: sync(
        store,
        provider(),
        clock=now,
        quality=config.data_sources.quality,
        window_sessions=config.risk.market_risk.var.window_sessions,
    )


@sync_app.command("ecb")
def sync_ecb(
    start: Annotated[
        datetime | None,
        typer.Option(
            "--start",
            formats=["%Y-%m-%d"],
            help="Première date (défaut : 14 jours avant la dernière séance en base).",
        ),
    ] = None,
    end: Annotated[
        datetime | None,
        typer.Option("--end", formats=["%Y-%m-%d"], help="Dernière date (défaut : aujourd'hui)."),
    ] = None,
    currency: Annotated[
        list[str] | None,
        typer.Option("--currency", help="Devise en plus de celles du référentiel (répétable)."),
    ] = None,
    store: StoreOpt = None,
    journal: JournalOpt = None,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Cours de référence et €STR de la BCE (réseau, sans clé), selon data_sources.yaml.

    Codes de sortie : 0 synchronisé, 1 refus (réseau, format, base), 2 source bloquée (R7).
    """
    config = load(config_dir)
    try:
        config.require("data.ecb")
    except BlockedFeatureError as exc:
        blocked(exc)
    source = config.data_sources.sources["ecb"]
    categories = list(source.categories or [])
    moment = now()
    with _store(store) as db:
        currencies = sorted(
            set(reference_currencies(db.instruments(as_of=moment)))
            | {c.strip().upper() for c in currency or []}
        )
        if FX_CATEGORY in categories and not currencies:
            typer.echo("Aucune devise hors euro dans le référentiel : change non demandé.")
        series: dict[str, Callable[..., Any]] = {}
        if FX_CATEGORY in categories:
            series |= {f"EUR{c}": partial(db.fx_rates, c) for c in currencies}
        if ESTR_CATEGORY in categories:
            series[ESTR_SERIES_ID] = partial(db.rates, ESTR_SERIES_ID)
        if not series:
            fail("Rien à demander à la BCE (catégories et devises vides).", EXIT_ERROR)
        try:
            first = start.date() if start else default_start(series, moment)
        except ValueError as exc:
            fail(f"Refus : {exc}.", EXIT_ERROR)
        last = end.date() if end else local_date(moment)
        try:
            provider = EcbProvider(
                base_url=source.url or "",
                categories=categories,
                currencies=currencies,
                start=first,
                end=last,
                transport=ecb_transport(),
            )
        except ProviderError as exc:
            fail(f"Refus : {exc}.", EXIT_ERROR)
        _run("ecb", journal, config, _sync(db, config, lambda: provider))


@sync_app.command("prices")
def sync_prices(
    file: FileArg,
    store: StoreOpt = None,
    journal: JournalOpt = None,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Clôtures exportées par Lucas : date, identifiant, cloture, devise[, volume] (ADR-017)."""
    config = load(config_dir)
    with _store(store) as db:
        _run("prices", journal, config, _sync(db, config, lambda: CsvCloses(file, reference(db))))


@sync_app.command("corporate-actions")
def sync_corporate_actions(
    file: FileArg,
    store: StoreOpt = None,
    journal: JournalOpt = None,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Splits et dividendes : date_ex, identifiant, type, valeur[, devise, date_annonce]."""
    config = load(config_dir)
    with _store(store) as db:
        provider = partial(CsvCorporateActions, file, reference(db))
        _run("corporate-actions", journal, config, _sync(db, config, provider))


@sync_app.command("instruments")
def sync_instruments(
    file: FileArg,
    store: StoreOpt = None,
    journal: JournalOpt = None,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Référentiel : une ligne par version d'instrument (identifiant, nom, classe, devise…)."""
    config = load(config_dir)
    with _store(store) as db:
        action = partial(import_instruments, db, file, recorded_at=now())
        _run("instruments", journal, config, action)
