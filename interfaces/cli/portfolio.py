"""`cerveau portfolio`: Lucas imports his transactions and reconciles a statement (ADR-018).

Only Lucas runs these commands: neither the scheduler nor an MCP tool imports a file. Every run
is journaled (R11) with counts, accounts and identifiers, never an amount nor a label; the
quantities of a gap are printed here only.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, NoReturn, TypeVar

import typer

from core.audit import AuditJournal, default_journal_path
from core.finance.brokers import FORMATS
from core.finance.portfolio import (
    AccountReconciliation,
    Gap,
    ImportResult,
    PortfolioError,
    ReconcileResult,
    import_transactions,
    reconcile,
)
from core.finance.providers import ProviderError
from core.finance.schema import SchemaError
from core.finance.store import FinanceStore, FinanceStoreError, default_store_path
from interfaces.cli.common import (
    EXIT_ERROR,
    EXIT_GAP,
    ConfigDirOpt,
    JournalOpt,
    fail,
    load,
    project_root,
)
from interfaces.cli.finance import FileArg, StoreOpt

if TYPE_CHECKING:
    from core.config.loader import Config

T = TypeVar("T", ImportResult, ReconcileResult)

portfolio_app = typer.Typer(
    help="Portefeuille : import des transactions et rapprochement avec le courtier (ADR-018).",
    no_args_is_help=True,
)
STATUS = {"ok": "ok", "ecart": "écart", "non_rapproche": "non rapproché"}
NATURE = {"security": "titre", "cash": "espèces"}


def now() -> datetime:
    return datetime.now(UTC)


def _quantity(value: Decimal) -> str:
    return f"{value:f}".replace(".", ",")


class _Run:
    """One journaled command: its entry on success, or why it was refused (R11)."""

    def __init__(self, command: str, journal: Path | None, config: Config) -> None:
        self.audit = AuditJournal(journal or default_journal_path(project_root()))
        self.request_id = f"portfolio-{command}-{uuid.uuid4().hex[:12]}"
        self.versions = {"config": config.digest}
        self.entry: dict[str, Any] = {"command": f"portfolio {command}"}

    def attempt(self, store: Path | None, action: Callable[[FinanceStore], T]) -> T:
        """Open the store, act, journal; a refusal, even at opening, records nothing."""
        try:
            with FinanceStore.open(store or default_store_path(project_root())) as db:
                result = action(db)
        except (ProviderError, FinanceStoreError, PortfolioError, SchemaError) as exc:
            self.refuse(exc)
        self.audit.append(
            actor="lucas",
            event="TOOL_CALL",
            request_id=self.request_id,
            versions=self.versions,
            payload={**self.entry, **result.journal_payload()},
        )
        return result

    def refuse(self, exc: Exception) -> NoReturn:
        # These messages name a file, a line, an account or an identifier, never a value (R5).
        self.audit.append(
            actor="lucas",
            event="ERROR",
            request_id=self.request_id,
            versions=self.versions,
            payload={**self.entry, "error": str(exc)},
        )
        fail(f"Refus : {exc}. Rien n'est enregistré ; requête {self.request_id}.", EXIT_ERROR)

    def close(self, gaps: Sequence[Gap]) -> None:
        typer.echo(f"Journalisé : requête {self.request_id} (`cerveau audit tail`).")
        if gaps:
            fail("Alerte : rapprochement: ecart (code de sortie 4).", EXIT_GAP)


def _status_lines(reconciliation: Sequence[AccountReconciliation]) -> None:
    typer.echo("Rapprochement :")
    for account in reconciliation:
        line = f"  · {account.account} : {STATUS[account.status]}"
        if account.statement_date is not None:
            line += f" (relevé du {account.statement_date:%d/%m/%Y}, {account.statement_file})"
        typer.echo(line)
        for gap in account.gaps:
            typer.echo(
                f"      {NATURE[gap.nature]} {gap.asset} : relevé {_quantity(gap.statement)}, "
                f"calculé {_quantity(gap.computed)}"
            )


FormatOpt = Annotated[
    str, typer.Option("--format", help=f"Format du fichier ({', '.join(FORMATS)}).")
]


@portfolio_app.command("import")
def import_command(
    file: FileArg,
    fmt: FormatOpt = "cerveau",
    store: StoreOpt = None,
    journal: JournalOpt = None,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Importer un fichier de transactions.

    Colonnes : date, compte, type, identifiant, quantite, prix, devise, frais, et en option
    montant, libelle. Le fichier fait foi, compte par compte, sur sa période ; le même fichier
    une seconde fois ne change rien.

    Codes de sortie : 0 importé, 1 refus (format, vente au-delà de la position, base), 4 un
    compte en écart avec son dernier relevé.
    """
    run = _Run("import", journal, load(config_dir))
    moment = now()
    result = run.attempt(store, lambda db: import_transactions(db, file, fmt, imported_at=moment))
    if result.new:
        typer.echo(
            f"{result.file.file_name} : {result.file.rows} ligne(s) ; {result.added} "
            f"transaction(s) ajoutée(s), {result.removed} retirée(s) "
            f"(comptes : {', '.join(result.accounts)})."
        )
    else:
        typer.echo(f"{result.file.file_name} : déjà importé, rien ne change.")
    for warning in result.warnings:
        typer.echo(f"Avertissement : {warning}.")
    _status_lines(result.reconciliation)
    run.close(result.gaps)


@portfolio_app.command("reconcile")
def reconcile_command(
    file: FileArg,
    store: StoreOpt = None,
    journal: JournalOpt = None,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Rapprocher un relevé de positions du courtier.

    Colonnes : date, compte, nature (titre, especes), identifiant, quantite ; une seule date.
    Comparaison exacte avec les positions calculées à cette date.

    Codes de sortie : 0 rapproché, 1 refus, 4 écart (alerte, aussi dans le journal).
    """
    run = _Run("reconcile", journal, load(config_dir))
    moment = now()
    result = run.attempt(store, lambda db: reconcile(db, file, at=moment))
    known = "nouveau" if result.new else "déjà enregistré"
    typer.echo(
        f"{result.file.file_name} : relevé du {result.statement_date:%d/%m/%Y}, "
        f"{result.file.rows} ligne(s) ({known})."
    )
    _status_lines(result.reconciliation)
    run.close(result.gaps)
