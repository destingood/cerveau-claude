"""`cerveau forecast`: the forecast registry and its calibration (section 11, ADR-064).

``add`` and ``resolve`` write ``var/learning/forecasts.db`` and a ``FORECAST`` journal entry;
``list`` and ``calibration`` only read. Every score is computed by ``core.learning.calibration``.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from core.audit import AuditError, AuditJournal, default_journal_path
from core.config import BlockedFeatureError
from core.learning.calibration import CalibrationError, estimate_scores, probability_scores
from core.learning.forecasts import Forecast as ForecastRow
from core.learning.forecasts import ForecastError, ForecastStore, default_forecasts_path
from interfaces.cli.common import (
    EXIT_ERROR,
    ConfigDirOpt,
    JournalOpt,
    OutsideVarOpt,
    fail,
    load,
    project_root,
    var_path,
)

forecast_app = typer.Typer(
    help="Prévisions datées, leur résolution et leur calibration (score de Brier).",
    no_args_is_help=True,
)

StoreOpt = Annotated[
    Path | None,
    typer.Option("--store", help="Registre des prévisions (défaut : var/learning/forecasts.db)."),
]


class KindArg(StrEnum):
    probabilite = "probabilite"
    estimation = "estimation"


def _store_path(store: Path | None, outside: bool) -> Path:
    return var_path(
        store, default_forecasts_path(project_root()), option="--store", outside=outside
    )


def _journal(journal: Path | None, outside: bool) -> AuditJournal:
    default = default_journal_path(project_root())
    return AuditJournal(var_path(journal, default, option="--journal", outside=outside))


def _day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        fail(f"Refus : date invalide {text!r} (AAAA-MM-JJ).", EXIT_ERROR)


def _line(f: ForecastRow) -> str:
    value = f"{f.value:.0%}" if f.kind == "probabilite" else f"{f.value:g}"
    if f.resolved:
        result = ("oui" if f.outcome else "non") if f.kind == "probabilite" else f"{f.actual:g}"
        state = f"résolue : {result}"
    else:
        state = "ouverte"
    return f"{f.forecast_id}  {f.due_on}  {f.domain}  {value}  {state}  — {f.statement}"


@forecast_app.command("add")
def add_command(
    domain: Annotated[str, typer.Argument(help="Domaine (finance, recherche…).")],
    kind: Annotated[KindArg, typer.Argument(help="probabilite ou estimation.")],
    value: Annotated[float, typer.Argument(help="Probabilité entre 0 et 1, ou valeur estimée.")],
    due_on: Annotated[str, typer.Argument(help="Échéance AAAA-MM-JJ, après aujourd'hui.")],
    statement: Annotated[str, typer.Argument(help="Ce qui est prévu, vérifiable à l'échéance.")],
    store: StoreOpt = None,
    journal: JournalOpt = None,
    outside_var: OutsideVarOpt = False,
) -> None:
    """Enregistre une prévision datée (section 11)."""
    path = _store_path(store, outside_var)
    audit = _journal(journal, outside_var)
    try:
        with ForecastStore.open(path, journal=audit) as forecasts:
            row = forecasts.add(
                domain=domain,
                kind=kind.value,
                statement=statement,
                value=value,
                due_on=_day(due_on),
                now=datetime.now().astimezone(),
            )
    except (ForecastError, AuditError) as exc:
        fail(f"Refus : {exc}", EXIT_ERROR)
    typer.echo(f"Prévision enregistrée : {row.forecast_id} (échéance {row.due_on}).")


@forecast_app.command("resolve")
def resolve_command(
    forecast_id: Annotated[str, typer.Argument(help="Identifiant de la prévision.")],
    result: Annotated[str, typer.Argument(help="oui ou non (probabilité), ou valeur observée.")],
    source: Annotated[str, typer.Option("--source", help="D'où vient le résultat.")],
    store: StoreOpt = None,
    journal: JournalOpt = None,
    outside_var: OutsideVarOpt = False,
) -> None:
    """Résout une prévision échue : une seule fois, jamais avant l'échéance (R10)."""
    path = _store_path(store, outside_var)
    audit = _journal(journal, outside_var)
    try:
        with ForecastStore.open(path, journal=audit) as forecasts:
            kind = forecasts.get(forecast_id).kind
            now = datetime.now().astimezone()
            if kind == "probabilite":
                if result not in ("oui", "non"):
                    fail("Refus : une probabilité se résout par oui ou non.", EXIT_ERROR)
                row = forecasts.resolve(
                    forecast_id, outcome=result == "oui", source=source, now=now
                )
            else:
                try:
                    actual = float(result.replace(",", "."))
                except ValueError:
                    fail(f"Refus : valeur observée invalide {result!r}.", EXIT_ERROR)
                row = forecasts.resolve(forecast_id, actual=actual, source=source, now=now)
    except (ForecastError, AuditError) as exc:
        fail(f"Refus : {exc}", EXIT_ERROR)
    typer.echo(f"Prévision résolue : {_line(row)}")


@forecast_app.command("list")
def list_command(
    domain: Annotated[str | None, typer.Option("--domaine", help="Un seul domaine.")] = None,
    overdue: Annotated[
        bool, typer.Option("--echues", help="Seulement les prévisions échues à résoudre.")
    ] = False,
    store: StoreOpt = None,
    outside_var: OutsideVarOpt = False,
) -> None:
    """Liste les prévisions, par échéance."""
    try:
        with ForecastStore.open(_store_path(store, outside_var), read_only=True) as forecasts:
            rows = (
                forecasts.overdue(datetime.now().astimezone())
                if overdue
                else forecasts.forecasts(domain=domain)
            )
    except ForecastError as exc:
        fail(f"Refus : {exc}", EXIT_ERROR)
    if domain is not None:
        rows = [row for row in rows if row.domain == domain]
    for row in rows:
        typer.echo(_line(row))
    typer.echo(f"{len(rows)} prévision(s).")


@forecast_app.command("calibration")
def calibration_command(
    domain: Annotated[str | None, typer.Option("--domaine", help="Un seul domaine.")] = None,
    bins: Annotated[int, typer.Option("--classes", min=1, max=20, help="Classes.")] = 10,
    store: StoreOpt = None,
    outside_var: OutsideVarOpt = False,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Score de Brier, décomposition de Murphy et erreurs des estimations résolues."""
    try:
        with ForecastStore.open(_store_path(store, outside_var), read_only=True) as forecasts:
            probabilities = forecasts.probability_pairs(domain=domain)
            estimates = forecasts.estimate_pairs(domain=domain)
    except ForecastError as exc:
        fail(f"Refus : {exc}", EXIT_ERROR)
    scope = domain or "tous domaines"
    try:
        scores = probability_scores(probabilities, bins=bins)
    except CalibrationError:
        typer.echo(f"Probabilités ({scope}) : aucune prévision résolue.")
    else:
        typer.echo(
            f"Probabilités ({scope}) : {scores.count} résolue(s), Brier {scores.brier:.4f} "
            f"(fiabilité {scores.reliability:.4f}, résolution {scores.resolution:.4f}, "
            f"incertitude {scores.uncertainty:.4f}, fréquence observée {scores.base_rate:.0%})."
        )
        for b in scores.bins:
            typer.echo(
                f"  [{b.lower:.0%} ; {b.upper:.0%}] : {b.count} prévision(s), annoncé "
                f"{b.mean_forecast:.0%}, observé {b.observed_rate:.0%}"
            )
    try:
        errors = estimate_scores(estimates)
    except CalibrationError:
        typer.echo(f"Estimations ({scope}) : aucune estimation résolue.")
    else:
        relative = (
            f"{errors.mean_relative_error:.1%} sur {errors.relative_count}"
            if errors.mean_relative_error is not None
            else "non calculable (valeurs observées nulles)"
        )
        typer.echo(
            f"Estimations ({scope}) : {errors.count} résolue(s), erreur absolue moyenne "
            f"{errors.mean_absolute_error:g}, erreur relative moyenne {relative}."
        )
    try:
        load(config_dir).require("learning.calibration_drift")
    except BlockedFeatureError:
        typer.echo("Dérive de calibration : non évaluée, seuils à définir (R7).")
