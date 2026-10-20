"""The answer of ``strategy_lab`` (plugin finance_research, ADR-027): what the Copilot may read of a
registered strategy, in three modes.

- ``signaux``: the weights and indicators of one grid point at the last decision known at as_of.
- ``backtest``: one grid point over a bounded window, on the home engine (``copilot.backtest``).
  It is a trial of the family, which the next protocol replays and counts in N.
- ``protocole``: the latest standard report, its gates, and whether it still matches the code
  and the grid.

No mode gives a verdict. Only ``cerveau strategy protocol`` does (ADR-026), and every answer says
so in ``rappel``. Every number is a Figure whose id starts with ``strategy_lab/`` (R1). The store
is opened read only; before any ``cerveau strategy`` run, a synthetic entry reads the same
fixtures in memory, with no trial recorded yet.
"""

from __future__ import annotations

import functools
import math
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from core.config.loader import Config
from core.finance.fixtures import load_research, research_costs
from core.finance.model import ParamValue, canonical_json
from core.finance.research import copilot
from core.finance.research.copilot import CopilotError, Mode
from core.finance.research.execution import Costs
from core.finance.research.protocol import ENGINE
from core.finance.research.registry import (
    REGISTRY_DIR,
    CostsKind,
    DataKind,
    StrategySpec,
    grid_sha256,
    load_registry,
    load_strategy,
    synthetic_store_path,
)
from core.finance.research.report import (
    FICTITIOUS_COSTS,
    SYNTHETIC,
    VERDICT,
    GateRecord,
    Row,
    StrategyReport,
    default_reports_dir,
    latest_report,
)
from core.finance.research.strategy import Strategy, checked_weights
from core.finance.research.trials import strategy_code_sha256
from core.finance.research.view import MarketHistory, decision_time
from core.finance.store import FinanceStore, default_store_path
from core.finance.views import read_store
from core.verification.figures import Figure, amount, count, percent, plain, price

FEATURE = "finance.research"
MAX_INSTRUMENTS = 20  # instruments a signal answer lists, largest weights first
HYPOTHESES = (
    "Taux sans risque nul pour les ratios de Sharpe, de Sortino et de Calmar [Hypothèse].",
    "Décision à l'heure de coupure de config/research.yaml › execution (UTC), sur les seules "
    "données publiées avant elle ; ordres exécutés à la clôture de la séance suivante "
    "[Hypothèse].",
)
WINDOW = (
    "Fenêtre : dans la période déclarée au registre, jusqu'à la dernière décision connue à "
    "as_of ; sans début, les dernières séances dans la limite de config/research.yaml › "
    "copilot.max_window_sessions."
)


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Indicator(_Out):
    nom: str
    valeur: Figure | None = Field(description="None : pas encore assez de clôtures connues")


class LabInstrument(_Out):
    instrument: str
    poids: Figure
    derniere_seance: date | None = Field(description="Dernière clôture connue à la décision")
    derniere_cloture: Figure | None
    indicateurs: list[Indicator]


class Signals(_Out):
    jour: date
    connu_a: AwareDatetime
    parametres: str = Field(description="Point de la grille, JSON canonique")
    instruments: list[LabInstrument]
    omis: Figure | None = Field(description="Instruments non listés, de poids les plus faibles")
    liquidites: Figure


class LabBacktest(_Out):
    parametres: str = Field(description="Point de la grille, JSON canonique")
    debut: date
    fin: date
    seances: Figure
    capital_initial: Figure
    valeur_finale: Figure
    rendement_total: Figure
    rendement_annuel: Figure
    volatilite: Figure
    sharpe: Figure | None = Field(description="None : non défini (aucune dispersion)")
    sortino: Figure | None = Field(description="None : non défini (aucune baisse)")
    perte_max: Figure
    pic_creux: str
    calmar: Figure | None = Field(description="None : non défini (aucune perte)")
    rotation: Figure
    transactions: Figure
    frais_payes: Figure
    exposition_moyenne: Figure


class LabProtocol(_Out):
    rapport: str
    genere_le: AwareDatetime
    verdict: str
    a_jour: bool = Field(description="Le rapport porte sur le code et la grille actuels")
    ecarts: list[str]
    portes: list[GateRecord]
    lignes: list[Row] = Field(description="Section 8 du rapport : verdict et portes")


class StrategyLab(_Out):
    parity_label: Literal["[Approximation]"] = "[Approximation]"
    strategie: str
    nom: str
    statut: str
    mode: Mode
    donnees: DataKind
    frais: CostsKind
    moteur: str
    dernier_verdict: str | None = Field(description="None : aucun protocole enregistré")
    rappel: str
    essais_famille: Figure
    avertissements: list[str]
    hypotheses: list[str]
    signaux: Signals | None = None
    backtest: LabBacktest | None = None
    protocole: LabProtocol | None = None


@functools.cache
def _fixture_history(universe: tuple[str, ...]) -> MarketHistory:
    with FinanceStore.memory() as store:
        load_research(store)
        return MarketHistory.load(store, universe)


def _read(
    spec: StrategySpec, root: Path, code: str, *, history: bool
) -> tuple[MarketHistory | None, int]:
    """The history of the universe (when asked) and N, the trials recorded for the family."""
    if spec.donnees == "synthetiques":
        path = synthetic_store_path(root)
        if not path.is_file():
            return (_fixture_history(tuple(spec.univers)) if history else None), 0
    else:
        path = default_store_path(root)
    return read_store(
        path,
        lambda db: (
            MarketHistory.load(db, spec.univers) if history else None,
            db.family_count(spec.id, code),
        ),
    )


def _costs(spec: StrategySpec, config: Config) -> Costs:
    if spec.donnees == "synthetiques":
        named = research_costs()
        return Costs.from_config(named.costs, named.name)
    return Costs.from_config(config.risk.trading_costs, "risk.yaml › trading_costs")


def _arguments(
    mode: Mode, params: Mapping[str, ParamValue] | None, start: date | None, end: date | None
) -> None:
    if mode == "protocole" and params is not None:
        raise CopilotError("params ne s'applique pas au mode protocole")
    if mode != "protocole" and params is None:
        raise CopilotError(f"params requis en mode {mode} : un point de la grille")
    if mode != "backtest" and (start is not None or end is not None):
        raise CopilotError("debut et fin ne s'appliquent qu'au mode backtest")


def _protocol(spec: StrategySpec, path: Path, report: StrategyReport, code: str) -> LabProtocol:
    checks = {
        "empreinte de code différente de la version actuelle": report.code_sha256 != code,
        "empreinte de grille différente de la version actuelle": (
            report.grille_sha256 != grid_sha256(spec)
        ),
    }
    gaps = [reason for reason, failed in checks.items() if failed]
    verdict = next((s for s in report.sections if s.titre.startswith("8.")), None)
    return LabProtocol(
        rapport=path.name,
        genere_le=report.genere_le,
        verdict=VERDICT[report.verdict],
        a_jour=not gaps,
        ecarts=gaps,
        portes=report.portes,
        lignes=verdict.lignes if verdict else [],
    )


def _reminder(spec: StrategySpec, latest: LabProtocol | None) -> str:
    only = f"seul `cerveau strategy protocol {spec.id}` rend un verdict (ADR-026)"
    if latest is None:
        return (
            f"Aucun protocole enregistré pour {spec.id} : ce résultat n'est pas un verdict ; "
            f"{only}."
        )
    if latest.verdict != VERDICT["reussi"]:
        return (
            f"Dernier verdict du protocole : {latest.verdict}. Un résultat favorable ici ne valide "
            f"pas la stratégie ; {only}."
        )
    stale = "" if latest.a_jour else ", qui n'est plus la version actuelle"
    return (
        f"Dernier verdict du protocole : réussi, pour la version jugée seulement{stale}. Ce "
        f"résultat-ci n'est pas un verdict ; {only}."
    )


def _signals(
    strategy: Strategy,
    params: Mapping[str, ParamValue],
    history: MarketHistory,
    *,
    at: datetime,
    config: Config,
) -> Signals:
    cutoff = config.research.execution.decision_cutoff_utc
    day = copilot.decision_day(at, cutoff)
    view = history.view(day, cutoff)
    weights = checked_weights(strategy.decide(view, params), view.instruments, day)
    indicators = getattr(strategy, "indicators", None)
    levels = indicators(view, params) if callable(indicators) else {}
    order = sorted(view.instruments, key=lambda i: (-weights.get(i, 0.0), i))
    lines: list[LabInstrument] = []
    for instrument_id in order[:MAX_INSTRUMENTS]:
        base = f"strategy_lab/signaux/{instrument_id}"
        last = view.last_close(instrument_id)
        currencies = history.currencies(instrument_id)
        close = (
            price(f"{base}/derniere_cloture", last[1], next(iter(currencies)))
            if last is not None and len(currencies) == 1
            else None
        )
        lines.append(
            LabInstrument(
                instrument=instrument_id,
                poids=percent(f"{base}/poids", weights.get(instrument_id, 0.0)),
                derniere_seance=last[0] if last is not None else None,
                derniere_cloture=close,
                indicateurs=[
                    Indicator(
                        nom=name,
                        valeur=plain(f"{base}/{name}", value, "niveau", 4)
                        if value is not None and math.isfinite(value)
                        else None,
                    )
                    for name, value in levels.get(instrument_id, {}).items()
                ],
            )
        )
    hidden = len(order) - len(lines)
    return Signals(
        jour=day,
        connu_a=decision_time(day, cutoff),
        parametres=canonical_json(dict(params)),
        instruments=lines,
        omis=count("strategy_lab/signaux/omis", hidden, "instruments") if hidden else None,
        liquidites=percent(
            "strategy_lab/signaux/liquidites", max(0.0, 1.0 - math.fsum(weights.values()))
        ),
    )


def _backtest(run: copilot.CopilotBacktest, initial_cash: float) -> LabBacktest:
    base, m = "strategy_lab/backtest", run.measures

    def ratio(key: str, value: float | None) -> Figure | None:
        return None if value is None else plain(f"{base}/{key}", value, "ratio")

    return LabBacktest(
        parametres=canonical_json(run.params),
        debut=run.window.start,
        fin=run.window.end,
        seances=count(f"{base}/seances", run.window.sessions, "séances"),
        capital_initial=amount(f"{base}/capital_initial", initial_cash, "EUR"),
        valeur_finale=amount(f"{base}/valeur_finale", float(run.result.values.iloc[-1]), "EUR"),
        rendement_total=percent(f"{base}/rendement_total", m.total_return),
        rendement_annuel=percent(f"{base}/rendement_annuel", m.annual_return),
        volatilite=percent(f"{base}/volatilite", m.volatility),
        sharpe=ratio("sharpe", m.sharpe),
        sortino=ratio("sortino", m.sortino),
        perte_max=percent(f"{base}/perte_max", m.drawdown.depth),
        pic_creux=f"{m.drawdown.peak.isoformat()} → {m.drawdown.trough.isoformat()}",
        calmar=ratio("calmar", m.calmar),
        rotation=plain(f"{base}/rotation", m.turnover, "ratio"),
        transactions=count(f"{base}/transactions", m.trades, "transactions"),
        frais_payes=amount(f"{base}/frais", m.fees, "EUR"),
        exposition_moyenne=percent(f"{base}/exposition", m.mean_exposure),
    )


def strategy_lab(
    root: Path,
    config: Config,
    *,
    strategy_id: str,
    mode: Mode,
    at: datetime,
    params: Mapping[str, ParamValue] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> StrategyLab:
    """The answer for one registry entry of ``root``, as known at ``at`` (R10)."""
    _arguments(mode, params, start, end)
    spec = load_registry(root / REGISTRY_DIR).get(strategy_id)
    if spec is None:
        raise CopilotError(f"stratégie inconnue : {strategy_id} (`cerveau strategy list`)")
    if spec.donnees == "reelles":
        config.require(FEATURE)
    if mode == "backtest" and isinstance(spec.capital_initial_eur, str):
        raise CopilotError(
            f"Bloqué (R7) : capital_initial_eur de {spec.id} vaut {spec.capital_initial_eur}"
        )
    strategy = load_strategy(spec)
    code = strategy_code_sha256(strategy)
    point = None if params is None else copilot.grid_point(spec, params)
    history, trials = _read(spec, root, code, history=mode != "protocole")
    found = latest_report(spec.id, default_reports_dir(root))
    latest = None if found is None else _protocol(spec, *found, code)
    synthetic = spec.donnees == "synthetiques"
    warnings = [SYNTHETIC, FICTITIOUS_COSTS] if synthetic else []
    hypotheses = list(HYPOTHESES)
    signals = backtest = None
    if mode == "signaux" and point is not None and history is not None:
        signals = _signals(strategy, point, history, at=at, config=config)
    elif mode == "backtest" and point is not None and history is not None:
        cash = float(spec.capital_initial_eur)
        run = copilot.backtest(
            spec,
            strategy,
            point,
            history,
            at=at,
            research=config.research,
            costs=_costs(spec, config),
            initial_cash=cash,
            sessions_per_year=252 if synthetic else config.risk.market_risk.annualisation_sessions,
            start=start,
            end=end,
        )
        backtest = _backtest(run, cash)
        warnings.append(
            f"Ce backtest est un essai de la famille {spec.id} : le prochain protocole le "
            "rejoue et le compte dans N, ce qui relève le seuil du ratio de Sharpe dégonflé."
        )
        hypotheses.append(WINDOW)
    return StrategyLab(
        strategie=spec.id,
        nom=spec.nom,
        statut=spec.statut,
        mode=mode,
        donnees=spec.donnees,
        frais="fictifs" if synthetic else "reels",
        moteur=ENGINE,
        dernier_verdict=None if latest is None else latest.verdict,
        rappel=_reminder(spec, latest),
        essais_famille=count("strategy_lab/essais_famille", trials, "essais"),
        avertissements=warnings,
        hypotheses=hypotheses,
        signaux=signals,
        backtest=backtest,
        protocole=latest if mode == "protocole" else None,
    )
