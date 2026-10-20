"""`cerveau strategy`: the strategy registry, its screening and its protocol (ADR-025 to ADR-027).

The commands read the registry under domain_packs/finance/strategies/ and write under var/ only:
the trial journal of the store, the reports under var/finance/research/reports/ and the audit
journal. A synthetic entry runs on its own store, var/finance/research/synthetique.db, so the
fictitious dataset never mixes with the point-in-time base that `cerveau finance sync` fills.
No command writes an approval: `show` prints the text Lucas may copy by hand (ADR-027, D14).
"""

from __future__ import annotations

import os
import uuid
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, NoReturn

import typer

from core.audit import AuditJournal, default_journal_path
from core.config import BlockedFeatureError
from core.config.loader import MARKERS
from core.finance.fixtures import load_research, research_costs, research_crises
from core.finance.model import local_date
from core.finance.research import engine
from core.finance.research.execution import Costs
from core.finance.research.protocol import Benchmark, partition, run_protocol
from core.finance.research.registry import (
    PROTOCOL_COMMAND,
    REGISTRY_DIR,
    CostsKind,
    LocalEvidence,
    RegistryError,
    StrategySpec,
    approval_text,
    audited_reports,
    code_sha256,
    expanded_grid,
    grid_sha256,
    load_registry,
    load_strategy,
    promotion_errors,
    read_stamp,
    report_blockers,
    report_sha256,
)
from core.finance.research.report import (
    VERDICT,
    build_report,
    default_reports_dir,
    latest_report,
    write_report,
)
from core.finance.research.screening import screen
from core.finance.research.trials import strategy_code_sha256
from core.finance.research.view import LookAheadError, MarketHistory
from core.finance.store import FinanceStore, FinanceStoreError, default_store_path
from interfaces.cli.common import (
    EXIT_BLOCKED,
    EXIT_ERROR,
    ConfigDirOpt,
    JournalOpt,
    OutsideVarOpt,
    blocked,
    fail,
    load,
    project_root,
    var_path,
)

if TYPE_CHECKING:
    from core.config.loader import Config, CrisisWindow

strategy_app = typer.Typer(
    help="Stratégies : registre, criblage et protocole (ADR-025 à ADR-027).", no_args_is_help=True
)

IdArg = Annotated[str, typer.Argument(help="Identifiant de la stratégie dans le registre.")]
StoreOpt = Annotated[
    Path | None,
    typer.Option(
        "--store", help="Base finance, données réelles seulement (défaut : var/finance/finance.db)."
    ),
]
SHOWN_POINTS = 5  # the best combinations a screening prints, as an indication only
SYNTHETIC_BENCHMARK = "achat-conservation à poids égaux de l'univers (synthétique)"
# What a command refuses rather than crash on: every library error of the research package is a
# ValueError (registry, screening, strategy, protocol, costs, report); LookAheadError is a bug of
# a strategy that read the future, refused as such (R10).
REFUSED = (ValueError, OSError, FinanceStoreError, LookAheadError)


def now() -> datetime:
    return datetime.now(UTC)


def registry() -> dict[str, StrategySpec]:
    directory = project_root() / REGISTRY_DIR
    try:
        return load_registry(directory)
    except RegistryError as exc:
        fail(f"Registre des stratégies invalide ({directory}) : {exc}", EXIT_ERROR)


def entry(strategy_id: str) -> StrategySpec:
    found = registry().get(strategy_id)
    if found is None:
        fail(f"Stratégie inconnue : {strategy_id} (`cerveau strategy list`).", EXIT_ERROR)
    return found


def synthetic_store_path(root: Path) -> Path:
    return root / "var" / "finance" / "research" / "synthetique.db"


def synthetic_store(root: Path) -> Path:
    """The store of the synthetic dataset, loaded once into a fresh file and then reused.

    The dataset is loaded into a temporary file renamed at the end, so an interrupted load never
    leaves a half-filled store; the trials recorded later stay with it.
    """
    path = synthetic_store_path(root)
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:12]}.tmp")
    try:
        with FinanceStore.open(tmp) as store:
            load_research(store)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


@dataclass(frozen=True)
class Inputs:
    """What a run reads besides the registry entry: the store, the costs and the crises."""

    store: Path
    costs: Costs
    costs_kind: CostsKind
    crises: Mapping[str, CrisisWindow]
    sessions_per_year: int
    benchmark_isin: str | None  # None: the universe itself, bought and held (synthetic data)


def inputs(spec: StrategySpec, config: Config, store: Path | None, *, outside: bool) -> Inputs:
    """Synthetic entries take the fixtures; real ones the configuration, or nothing (R7)."""
    root = project_root()
    if spec.donnees == "synthetiques":
        if store is not None:
            fail(
                "Refus : --store ne s'applique qu'aux données réelles ; une entrée synthétique "
                f"tourne sur {synthetic_store_path(root)}.",
                EXIT_ERROR,
            )
        named = research_costs()
        return Inputs(
            synthetic_store(root),
            Costs.from_config(named.costs, named.name),
            "fictifs",
            research_crises(),
            252,
            None,
        )
    try:
        config.require("finance.research")
    except BlockedFeatureError as exc:
        blocked(exc)
    market = config.risk.market_risk
    isin = market.benchmark.isin
    return Inputs(
        var_path(store, default_store_path(root), option="--store", outside=outside),
        Costs.from_config(config.risk.trading_costs, "risk.yaml › trading_costs"),
        "reels",
        market.historical_stress,
        market.annualisation_sessions,
        "" if isin in MARKERS else isin,
    )


def initial_cash(spec: StrategySpec) -> float:
    if isinstance(spec.capital_initial_eur, str):
        fail(
            f"Bloqué (R7) : capital_initial_eur de {spec.id} vaut {spec.capital_initial_eur}.",
            EXIT_BLOCKED,
        )
    return spec.capital_initial_eur


def benchmark(
    run: Inputs, store: FinanceStore, history: MarketHistory, at: datetime
) -> Benchmark | None:
    """The universe on synthetic data; on real data, the index of risk.yaml found by its ISIN.

    None when the ISIN is still a marker or absent from the store: the verdict is then
    ``incomplet`` (ADR-026), never ``reussi``.
    """
    if run.benchmark_isin is None:
        return Benchmark(SYNTHETIC_BENCHMARK, history)
    isin = run.benchmark_isin
    found = [i for i in store.instruments(as_of=at) if isin and i.isin == isin]
    if not found:
        return None
    index = found[0]
    label = f"achat-conservation de {index.name} ({index.isin})"
    return Benchmark(label, MarketHistory.load(store, [index.instrument_id]))


class Run:
    """One journaled command: its entry on success, or why it was refused (R11)."""

    def __init__(self, command: str, spec: StrategySpec, journal: Path, config: Config) -> None:
        self.audit = AuditJournal(journal)
        self.request_id = f"strategy-{command}-{uuid.uuid4().hex[:12]}"
        self.versions = {"config": config.digest}
        self.entry: dict[str, Any] = {"command": f"strategy {command}", "strategie": spec.id}

    def record(self, event: str, payload: Mapping[str, Any]) -> None:
        self.audit.append(
            actor="lucas",
            event=event,
            request_id=self.request_id,
            versions=self.versions,
            payload={**self.entry, **payload},
        )

    def refuse(self, exc: Exception) -> NoReturn:
        self.record("ERROR", {"error": str(exc)})
        fail(f"Refus : {exc}. Requête {self.request_id}.", EXIT_ERROR)

    @contextmanager
    def refusing(self) -> Iterator[None]:
        try:
            yield
        except REFUSED as exc:
            self.refuse(exc)


def journal_path(journal: Path | None, *, outside: bool) -> Path:
    root = project_root()
    return var_path(journal, default_journal_path(root), option="--journal", outside=outside)


@strategy_app.command("list")
def strategy_list() -> None:
    """Les stratégies du registre et le verdict de leur dernier protocole."""
    reports = default_reports_dir(project_root())
    for spec in registry().values():
        try:
            latest = latest_report(spec.id, reports)
            last = (
                f"{VERDICT[latest[1].verdict]} ({latest[0].name})" if latest else "aucun protocole"
            )
        except REFUSED as exc:
            last = f"rapport illisible : {exc}"
        typer.echo(
            f"{spec.id} — {spec.nom} : {spec.statut}, données {spec.donnees}, "
            f"{len(expanded_grid(spec))} configuration(s) ; dernier verdict : {last}"
        )


def _trial_counts(spec: StrategySpec, store: Path) -> str:
    if not store.is_file():
        return "aucune base"
    with FinanceStore.open(store, read_only=True) as db:
        counts = Counter(t.trial.origin for t in db.trials(spec.id))
    if not counts:
        return "0"
    detail = ", ".join(f"{origin} {n}" for origin, n in sorted(counts.items()))
    return f"{sum(counts.values())} ({detail})"


@strategy_app.command("show")
def strategy_show(strategy_id: IdArg) -> None:
    """Fiche d'une stratégie : hypothèse, empreintes, essais, dernier rapport, promotion."""
    root, spec = project_root(), entry(strategy_id)
    try:
        code, grid = code_sha256(spec, root), grid_sha256(spec)
    except RegistryError as exc:
        fail(f"Refus : {exc}.", EXIT_ERROR)
    lines = [
        f"{spec.id} — {spec.nom} ({spec.statut})",
        f"Hypothèse : {spec.hypothese}",
        f"Règle : {spec.regle}",
        f"Code : {spec.module} › {spec.classe} ; fréquence {spec.frequence}",
        f"Données : {spec.donnees} ({spec.source}) ; univers : {', '.join(spec.univers)}",
        f"Période : {spec.periode.debut} → {spec.periode.fin} ; capital initial : "
        f"{spec.capital_initial_eur} €",
        f"Grille : {spec.grille} ; {len(expanded_grid(spec))} configuration(s)",
        f"Contraintes : {[c.model_dump() for c in spec.contraintes] or 'aucune'}",
        f"Empreinte du code : {code}",
        f"Empreinte de la grille : {grid}",
    ]
    for line in lines:
        typer.echo(line)
    store = (
        synthetic_store_path(root) if spec.donnees == "synthetiques" else default_store_path(root)
    )
    try:
        typer.echo(f"Essais de la famille (N) : {_trial_counts(spec, store)}")
        latest = latest_report(spec.id, default_reports_dir(root))
        audited = audited_reports(default_journal_path(root)) if latest else frozenset()
    except REFUSED as exc:
        fail(f"Refus : {exc}.", EXIT_ERROR)
    for error in promotion_errors(spec, root=root):
        typer.echo(f"Promotion refusée : {error}")
    if latest is None:
        typer.echo("Dernier rapport : aucun (`cerveau strategy protocol`).")
        typer.echo("Aucun texte d'approbation : pas de rapport.")
        return
    path, report = latest
    sha = report_sha256(path)
    typer.echo(
        f"Dernier rapport : {path} ; verdict {VERDICT[report.verdict]} ; SHA-256 {sha} ; "
        + ("inscrit au journal d'audit" if sha in audited else "absent du journal d'audit")
    )
    reasons = report_blockers(
        read_stamp(path), spec, code=code, grid=grid, against="la version actuelle"
    )
    if sha not in audited:
        reasons.append("empreinte du rapport absente du journal d'audit")
    if reasons:
        typer.echo(f"Aucun texte d'approbation : {' ; '.join(reasons)}.")
        return
    day = local_date(now())
    typer.echo(approval_text(spec, report_sha256=sha, code=code, grid=grid, day=day), nl=False)


@strategy_app.command("screen")
def strategy_screen(
    strategy_id: IdArg,
    store: StoreOpt = None,
    journal: JournalOpt = None,
    outside: OutsideVarOpt = False,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Crible la grille sur la fenêtre de développement ; chaque combinaison est un essai."""
    spec = entry(strategy_id)
    journal_file = journal_path(journal, outside=outside)
    config = load(config_dir)
    run_inputs = inputs(spec, config, store, outside=outside)
    cash = initial_cash(spec)
    run = Run("screen", spec, journal_file, config)
    with run.refusing():
        strategy = load_strategy(spec)
        if not hasattr(strategy, "weights_frame"):
            raise RegistryError(f"{spec.id} : {spec.classe} n'a pas de forme vectorielle")
        code, grid = strategy_code_sha256(strategy), expanded_grid(spec)
        with FinanceStore.open(run_inputs.store) as db:
            history = MarketHistory.load(db, spec.univers)
            sessions, _ = engine.common_calendar(history, spec.periode.debut, spec.periode.fin)
            development, _ = partition(sessions, config.research)
            screening = screen(
                strategy,
                grid,
                history,
                start=sessions[0],
                end=sessions[development - 1],
                cutoff=config.research.execution.decision_cutoff_utc,
                costs=run_inputs.costs,
                initial_cash=cash,
            )
            trials = screening.trials(spec.id, code, run_inputs.sessions_per_year)
            db.add_trials(trials, recorded_at=now())
            family = len(db.trials(spec.id))
    run.record(
        "TOOL_CALL",
        {
            "code_sha256": code,
            "grille_sha256": grid_sha256(spec),
            "donnees": spec.donnees,
            "frais": run_inputs.costs.name,
            "fenetre": [screening.start.isoformat(), screening.end.isoformat()],
            "combinaisons": len(screening.points),
            "essais": family,
        },
    )
    typer.echo(
        f"Criblage de {spec.id} ({screening.engine}) sur la fenêtre de développement "
        f"{screening.start} → {screening.end} : {len(screening.points)} combinaison(s), "
        f"frais « {screening.costs} »."
    )
    ranked = sorted(
        screening.points,
        key=lambda p: -(p.sharpe(run_inputs.sessions_per_year) or float("-inf")),
    )
    for point in ranked[:SHOWN_POINTS]:
        ratio = point.sharpe(run_inputs.sessions_per_year)
        shown = "non calculable" if ratio is None else f"{ratio:.2f}"
        typer.echo(f"  {point.params} : Sharpe {shown}, {point.orders} ordre(s)")
    for approximation in screening.approximations:
        typer.echo(f"Approximation du criblage : {approximation}")
    typer.echo(
        f"Indicatif, aucun verdict : seul `cerveau strategy protocol {spec.id}` en rend un. "
        f"Essais de la famille (N) : {family}. Journalisé : requête {run.request_id}."
    )


@strategy_app.command("protocol")
def strategy_protocol(
    strategy_id: IdArg,
    store: StoreOpt = None,
    journal: JournalOpt = None,
    outside: OutsideVarOpt = False,
    config_dir: ConfigDirOpt = None,
) -> None:
    """Protocole complet (ADR-026) : verdict, rapport en neuf sections, entrée DECISION (R11)."""
    root, spec = project_root(), entry(strategy_id)
    journal_file = journal_path(journal, outside=outside)
    config = load(config_dir)
    run_inputs = inputs(spec, config, store, outside=outside)
    cash = initial_cash(spec)
    run = Run("protocol", spec, journal_file, config)
    started = now()
    with run.refusing():
        strategy = load_strategy(spec)
        with FinanceStore.open(run_inputs.store) as db:
            history = MarketHistory.load(db, spec.univers)
            reference = benchmark(run_inputs, db, history, started)
            result = run_protocol(
                strategy,
                strategy_id=spec.id,
                grid=expanded_grid(spec),
                history=history,
                start=spec.periode.debut,
                end=spec.periode.fin,
                config=config.research,
                costs=run_inputs.costs,
                initial_cash=cash,
                sessions_per_year=run_inputs.sessions_per_year,
                crises=run_inputs.crises,
                benchmark=reference,
                store=db,
                recorded_at=started,
            )
            report = build_report(
                spec,
                result,
                history=history,
                costs=run_inputs.costs,
                costs_kind=run_inputs.costs_kind,
                initial_cash=cash,
                config=config.research,
                crises=run_inputs.crises,
                trials=db.trials(spec.id),
                grid_sha256=grid_sha256(spec),
                generated_at=now(),
            )
        written = write_report(report, default_reports_dir(root))
    run.record(
        "DECISION",
        {
            "command": PROTOCOL_COMMAND,
            "verdict": result.verdict,
            "code_sha256": result.code_sha256,
            "grille_sha256": report.grille_sha256,
            "donnees": spec.donnees,
            "frais": run_inputs.costs.name,
            "rapport": written.json.name,
            "rapport_sha256": written.sha256,
        },
    )
    if reference is None:
        typer.echo(
            "Référence absente : l'ISIN de risk.yaml › market_risk.benchmark n'est pas défini ou "
            "pas dans la base ; le verdict ne peut pas être « reussi »."
        )
    typer.echo(f"Protocole de {spec.id} : verdict {VERDICT[result.verdict]}.")
    for gate in result.gates:
        typer.echo(f"  {gate.label} : {gate.status} — {gate.detail}")
    typer.echo(f"Rapport : {written.markdown}")
    typer.echo(f"JSON : {written.json} (SHA-256 {written.sha256})")
    typer.echo(f"Journalisé : requête {run.request_id} (`cerveau audit tail`).")


def registry_errors(root: Path) -> tuple[int, list[str]]:
    """For `cerveau config check`: the registry's size and every promotion refusal (ADR-027)."""
    specs = load_registry(root / REGISTRY_DIR)
    local = None
    if any(s.statut == "candidate" for s in specs.values()) and (root / "var").is_dir():
        local = LocalEvidence(
            default_reports_dir(root), audited_reports(default_journal_path(root))
        )
    errors = [e for spec in specs.values() for e in promotion_errors(spec, root=root, local=local)]
    return len(specs), errors
