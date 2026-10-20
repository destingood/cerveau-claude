"""The anti-overfitting protocol: one verdict for a strategy and its grid (ADR-026, D7 to D11).

The window is split once: development (``split.development_fraction`` of the sessions), an
embargo, then the final sample. Every computation runs in the in-house engine (ADR-025), from
cash, with the given costs:

1. R10: the truncation-invariance check, on every configuration of the grid. A breach, or a read
   the view refuses, fails the protocol at once and records no trial [Hypothèse];
2. each configuration runs once on the development sample: a ``protocole`` trial each;
3. the anchored walk-forward, the PBO (CSCV) and the choice of the configuration with the best
   development Sharpe ratio;
4. that configuration on the final sample, with normal then stressed costs: a ``protocole-final``
   trial, the stressed run being none (ADR-026);
5. the same configuration and the benchmark over the whole window, for the crises;
6. the deflated Sharpe ratio, with N and V read from the journal after the trials are recorded.

The six gates of D9 give the verdict: ``echoue`` if one fails, else ``incomplet`` if one cannot be
evaluated, else ``reussi``. Annualising changes no gate: gates 3 to 5 compare Sharpe ratios of the
same scale and the DSR works in daily units. Nothing here calls a model (R1).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import TypeAdapter, ValidationError

from core.config.loader import CrisisWindow, ResearchConfig
from core.finance.adjust import adjustment_factors
from core.finance.model import (
    ParamValue,
    ResearchTrial,
    StrategyId,
    TrialOrigin,
    params_sha256,
)
from core.finance.performance import Drawdown, max_drawdown, sharpe
from core.finance.research import engine
from core.finance.research.engine import BacktestMeasures, BacktestResult
from core.finance.research.execution import Costs
from core.finance.research.lookahead import Breach, truncation_breaches
from core.finance.research.overfitting import (
    OverfittingError,
    Pbo,
    deflated_sharpe,
    expected_max_sharpe,
    moments,
    pbo,
    trial_variance,
    walk_forward,
)
from core.finance.research.strategy import Strategy, StrategyError
from core.finance.research.trials import make_trial, strategy_code_sha256, value_returns
from core.finance.research.view import LookAheadError, MarketHistory
from core.finance.store import FinanceStore, RecordedTrial

ENGINE = "moteur maison"
INVARIANCE_DAYS = 12  # decision days checked per configuration, evenly spaced [Hypothèse]
MARKERS = frozenset({"A_DEFINIR", "A_VERIFIER"})

Verdict = Literal["reussi", "echoue", "incomplet"]
GateStatus = Literal["reussie", "echouee", "non evaluable"]

HYPOTHESES = (
    "Toutes les mesures du protocole viennent du moteur maison (ADR-025), à taux sans risque nul.",
    "Une configuration sans dispersion de rendement a un Sharpe de 0, partout où il compte.",
    "Le walk-forward ne compte aucun coût de transition entre deux plis : chaque configuration "
    "tourne une fois, en continu, sur l'échantillon de développement.",
    "PBO : un rang médian (λ = 0) compte comme un surapprentissage, comme le λ ≤ 0 de l'article.",
    "DSR : asymétrie et aplatissement (non centré) calculés sur les moments de population.",
    "La variante à frais multipliés et le passage sur toute la fenêtre (crises) ne sont pas des "
    "essais : ils ne peuvent qu'écarter une stratégie, jamais en choisir une.",
    f"L'invariance par troncature est vérifiée sur {INVARIANCE_DAYS} jours de décision "
    "également espacés, pour chaque configuration de la grille.",
    "La référence achète à parts égales, fractionnaires, à la clôture de la deuxième séance, avec "
    "les mêmes frais d'entrée, puis réinvestit ses dividendes sans frais ni arrondi.",
    "Une version de la stratégie est identifiée par l'empreinte de son code seule.",
    "Un échec R10 n'inscrit aucun essai : les mesures d'une stratégie qui lit le futur ne valent "
    "rien.",
)


class ProtocolError(ValueError):
    """A protocol that cannot start: a window, a grid or a benchmark it cannot carry."""


@dataclass(frozen=True)
class Partition:
    """Development, embargo and final sample, as first and last sessions."""

    development: tuple[date, date]
    embargo_sessions: int
    final: tuple[date, date]
    development_sessions: int
    final_sessions: int


@dataclass(frozen=True)
class Benchmark:
    """Instruments bought at equal weight and held: the index on real data, or the universe."""

    label: str
    history: MarketHistory


@dataclass(frozen=True)
class Gate:
    key: str
    label: str
    status: GateStatus
    detail: str


@dataclass(frozen=True)
class CrisisMeasure:
    """A crisis window measured on the whole-window runs, or why it cannot be."""

    key: str
    label: str
    reason: str | None  # None when covered
    strategy_return: float | None = None
    strategy_drawdown: float | None = None
    benchmark_return: float | None = None
    benchmark_drawdown: float | None = None


@dataclass(frozen=True)
class DeflatedSharpe:
    value: float | None  # None when the formula does not apply to the moments
    trials: int  # N: the family's rows in the journal, all origins
    variance: float  # V: of their daily Sharpe ratios, never lowered by a repeat (``_variance``)
    sharpe: float  # SR: daily, of the chosen configuration on the development sample
    skewness: float
    kurtosis: float
    sessions: int  # T: development returns
    threshold: float  # SR₀


@dataclass(frozen=True)
class Fold:
    train: tuple[date, date]  # first and last days of the returns learnt on
    test: tuple[date, date]
    params: dict[str, ParamValue]


@dataclass(frozen=True)
class Evaluation:
    """Every figure of a protocol that went past R10."""

    chosen: dict[str, ParamValue]
    development: BacktestMeasures
    folds: tuple[Fold, ...]
    walk_forward_sharpe: float | None  # annual
    pbo: Pbo
    dsr: DeflatedSharpe | None
    dsr_reason: str | None
    final: BacktestMeasures
    final_stressed: BacktestMeasures
    stress_multiplier: float
    benchmark_label: str | None
    benchmark_sharpe: float | None  # annual, on the final sample
    crises: tuple[CrisisMeasure, ...]
    final_readings_before: int  # earlier rows of this code version over the final sample
    trials_recorded: int


@dataclass(frozen=True)
class ProtocolResult:
    strategy_id: str
    code_sha256: str
    grid: tuple[dict[str, ParamValue], ...]
    partition: Partition
    verdict: Verdict
    gates: tuple[Gate, ...]
    breaches: tuple[Breach, ...]
    evaluation: Evaluation | None  # None when R10 or the strategy contract failed
    invariance_days: tuple[date, ...] = ()  # the decision days of the truncation check
    hypotheses: tuple[str, ...] = HYPOTHESES


def verdict(gates: Sequence[Gate]) -> Verdict:
    statuses = {g.status for g in gates}
    if "echouee" in statuses:
        return "echoue"
    return "incomplet" if "non evaluable" in statuses else "reussi"


def partition(sessions: Sequence[date], config: ResearchConfig) -> tuple[int, int]:
    """The number of development sessions and the index of the first final session."""
    development = int(len(sessions) * config.split.development_fraction)
    first_final = development + config.split.embargo_sessions
    blocks = config.walk_forward.blocks
    if development - 1 < 2 * blocks:
        raise ProtocolError(
            f"{development} séances de développement : trop peu pour {blocks} blocs de "
            "walk-forward (deux rendements par bloc au moins)"
        )
    if len(sessions) - first_final < 3:
        raise ProtocolError("moins de trois séances dans l'échantillon final après l'embargo")
    return development, first_final


def invariance_sample(sessions: Sequence[date], count: int = INVARIANCE_DAYS) -> list[date]:
    """``count`` decision days evenly spaced; the last session takes no decision."""
    decisions = list(sessions[:-1])
    picks = np.unique(np.linspace(0, len(decisions) - 1, min(count, len(decisions))).round())
    return [decisions[int(k)] for k in picks]


def benchmark_curve(
    history: MarketHistory,
    sessions: Sequence[date],
    costs: Costs,
    initial_cash: float,
) -> pd.Series:
    """Equal-weight buy-and-hold: in cash at the first session, bought at the second one's close.

    Each instrument gets an equal share of the cash, net of the slippage and of the commission
    (with its minimum); then its value follows its total-return close. Fractional and unrounded
    [Hypothèse].
    """
    if len(sessions) < 3:
        raise ProtocolError("au moins trois séances pour une référence")
    found, closes = engine.common_calendar(history, sessions[0], sessions[-1])
    if found != list(sessions):
        raise ProtocolError(
            f"référence {history.instruments} : séances différentes de celles de la stratégie"
        )
    days = np.array(found, dtype="datetime64[D]")
    share = initial_cash / len(history.instruments)
    rate = costs.commission
    if rate * share / (1 + rate) >= costs.minimum:
        invested = share / ((1 + costs.slippage) * (1 + rate))
    else:
        invested = (share - costs.minimum) / (1 + costs.slippage)
    if invested <= 0:
        raise ProtocolError("frais d'entrée de la référence supérieurs à sa part de liquidités")
    values = np.zeros(len(found))
    for column, instrument_id in enumerate(history.instruments):
        actions = history.actions(instrument_id, moment=None)
        total = closes[:, column] * adjustment_factors(
            days, closes[:, column], actions, "total_return"
        )
        values += invested * total / total[1]
    values[0] = initial_cash
    return pd.Series(values, index=pd.DatetimeIndex(found), name="valeur")


def _annual_sharpe(values: pd.Series, sessions_per_year: int) -> float | None:
    return sharpe(value_returns(values).tolist(), sessions_per_year)


def _or_zero(value: float | None) -> float:
    return 0.0 if value is None else value


def _drawdown(values: pd.Series) -> Drawdown:
    days = [stamp.date() for stamp in values.index]
    return max_drawdown(days, value_returns(values).tolist())


def crisis_measures(
    crises: Mapping[str, CrisisWindow], strategy: pd.Series, benchmark: pd.Series | None
) -> list[CrisisMeasure]:
    """Return and maximum drawdown of each crisis, from the last session before it to its end.

    A crisis whose dates or source are still markers, or that the window does not cover, is not
    measured: its gate cannot be evaluated (ADR-026).
    """
    measures = []
    days = [stamp.date() for stamp in strategy.index]
    for key, crisis in crises.items():
        start, end = crisis.start, crisis.end
        if not isinstance(start, date) or not isinstance(end, date) or crisis.source in MARKERS:
            measures.append(CrisisMeasure(key, crisis.label, "non couverte : dates A_VERIFIER"))
            continue
        before = [k for k, day in enumerate(days) if day < start]
        inside = [k for k, day in enumerate(days) if start <= day <= end]
        if not before or not inside or end > days[-1]:
            measures.append(CrisisMeasure(key, crisis.label, "non couverte par la fenêtre"))
            continue
        if benchmark is None:
            measures.append(CrisisMeasure(key, crisis.label, "aucune référence"))
            continue
        rows = slice(before[-1], inside[-1] + 1)
        ours, theirs = strategy.iloc[rows], benchmark.iloc[rows]
        measures.append(
            CrisisMeasure(
                key,
                crisis.label,
                None,
                strategy_return=float(ours.iloc[-1] / ours.iloc[0] - 1),
                strategy_drawdown=_drawdown(ours).depth,
                benchmark_return=float(theirs.iloc[-1] / theirs.iloc[0] - 1),
                benchmark_drawdown=_drawdown(theirs).depth,
            )
        )
    return measures


def _crisis_gate(measures: Sequence[CrisisMeasure]) -> Gate:
    label = "6. Perte maximale sur chaque crise ≤ celle de la référence"
    worse = [
        f"{m.label} : {_or_zero(m.strategy_drawdown):.2%} contre "
        f"{_or_zero(m.benchmark_drawdown):.2%}"
        for m in measures
        if m.reason is None and _or_zero(m.strategy_drawdown) > _or_zero(m.benchmark_drawdown)
    ]
    if worse:
        return Gate("crises", label, "echouee", "; ".join(worse))
    if not measures:
        return Gate("crises", label, "non evaluable", "aucune crise datée")
    missing = [f"{m.label} : {m.reason}" for m in measures if m.reason is not None]
    if missing:
        return Gate("crises", label, "non evaluable", "; ".join(missing))
    return Gate("crises", label, "reussie", f"{len(measures)} crise(s), aucune plus profonde")


def _gates(evaluation: Evaluation, config: ResearchConfig, final_returns: int) -> list[Gate]:
    gates = config.gates
    dsr = evaluation.dsr
    if dsr is None or dsr.value is None:
        first = Gate("dsr", "1. DSR", "non evaluable", evaluation.dsr_reason or "DSR non défini")
    else:
        first = Gate(
            "dsr",
            "1. DSR",
            "reussie" if dsr.value >= gates.dsr_min else "echouee",
            f"DSR {dsr.value:.4f} (seuil {gates.dsr_min}) ; N = {dsr.trials} essais",
        )
    found = evaluation.pbo
    if found.value is None:
        second = Gate("pbo", "2. PBO", "non evaluable", found.reason or "PBO non défini")
    else:
        second = Gate(
            "pbo",
            "2. PBO",
            "reussie" if found.value < gates.pbo_max else "echouee",
            f"PBO {found.value:.4f} (doit rester sous {gates.pbo_max}) ; "
            f"{found.combinations} combinaisons",
        )
    walk = _or_zero(evaluation.walk_forward_sharpe)
    final = _or_zero(evaluation.final.sharpe)
    ratio = gates.final_to_walk_forward_sharpe_min
    third = Gate(
        "stabilite",
        "3. Sharpe final ≥ ratio × Sharpe du walk-forward (> 0)",
        "reussie" if walk > 0 and final >= ratio * walk else "echouee",
        f"walk-forward {walk:.4f}, final {final:.4f}, ratio minimal {ratio}",
    )
    label = "4. Sharpe final > référence"
    if evaluation.benchmark_label is None:
        fourth = Gate("reference", label, "non evaluable", "aucune référence")
    elif final_returns < gates.benchmark_min_sessions:
        fourth = Gate(
            "reference",
            label,
            "non evaluable",
            f"{final_returns} rendements finals, moins de {gates.benchmark_min_sessions}",
        )
    else:
        theirs = _or_zero(evaluation.benchmark_sharpe)
        fourth = Gate(
            "reference",
            label,
            "reussie" if final > theirs else "echouee",
            f"final {final:.4f} contre {theirs:.4f} ({evaluation.benchmark_label})",
        )
    stressed = _or_zero(evaluation.final_stressed.sharpe)
    fifth = Gate(
        "frais",
        f"5. Sharpe final > 0 à frais × {evaluation.stress_multiplier:g}",
        "reussie" if stressed > 0 else "echouee",
        f"Sharpe final à frais multipliés : {stressed:.4f}",
    )
    return [first, second, third, fourth, fifth, _crisis_gate(evaluation.crises)]


R10_LABEL = "R10. Aucune décision ne lit une donnée postérieure"


def _column_sharpes(runs: Sequence[BacktestResult]) -> list[float]:
    """The daily development Sharpe ratio of each run, 0 without spread."""
    return [_or_zero(sharpe(value_returns(r.values).tolist(), 1)) for r in runs]


def _reads_final(trial: ResearchTrial, final: tuple[date, date]) -> bool:
    """A final reading of the protocol, or any other backtest whose window reaches the final
    sample: a Copilot or screening run has read it too (quant review of phase 3, M2)."""
    if trial.origin == "protocole-final":
        return True
    return trial.origin != "protocole" and trial.start <= final[1] and trial.end >= final[0]


def _variance(family: Sequence[RecordedTrial], grid: Sequence[ResearchTrial]) -> float:
    """V: the largest variance of the family's Sharpe ratios, of its distinct return series and
    of the current grid's development runs.

    Copies of a middling trial shrink the family's variance while N grows, which lowers SR₀ and
    raises the DSR (quant review of phase 3, M1). A series counts once by its window and
    fingerprint, and the grid's own spread is a floor: repeating a trial can only raise SR₀.
    """
    distinct = {
        (row.trial.start, row.trial.end, row.trial.series_sha256): row.trial.sharpe_daily
        for row in family
    }
    return max(
        trial_variance([row.trial.sharpe_daily for row in family]),
        trial_variance(list(distinct.values())),
        trial_variance([trial.sharpe_daily for trial in grid]),
    )


def _deflated(
    chosen_returns: np.ndarray,
    chosen: ResearchTrial,
    family: Sequence[RecordedTrial],
    grid: Sequence[ResearchTrial],
) -> tuple[DeflatedSharpe | None, str | None]:
    """The DSR of the chosen configuration against every trial of its family (ADR-026)."""
    try:
        skewness, kurtosis = moments(chosen_returns.tolist())
    except OverfittingError as exc:
        return None, str(exc)
    trials = len(family)
    variance = _variance(family, grid)
    threshold = expected_max_sharpe(trials, variance)
    sr = _or_zero(chosen.sharpe_daily)
    value = deflated_sharpe(sr, chosen.sessions, skewness, kurtosis, threshold)
    found = DeflatedSharpe(
        value, trials, variance, sr, skewness, kurtosis, chosen.sessions, threshold
    )
    return found, None if value is not None else "moments hors du domaine de la formule"


def run_protocol(
    strategy: Strategy,
    *,
    strategy_id: str,
    grid: Sequence[Mapping[str, ParamValue]],
    history: MarketHistory,
    start: date,
    end: date,
    config: ResearchConfig,
    costs: Costs,
    initial_cash: float,
    sessions_per_year: int,
    crises: Mapping[str, CrisisWindow],
    benchmark: Benchmark | None,
    store: FinanceStore,
    recorded_at: datetime,
) -> ProtocolResult:
    """Run the whole protocol on [start, end] and record its trials in one transaction."""
    try:
        TypeAdapter(StrategyId).validate_python(strategy_id)
    except ValidationError as exc:
        raise ProtocolError(f"identifiant de stratégie invalide : {strategy_id!r}") from exc
    points = [dict(params) for params in grid]
    if not points:
        raise ProtocolError("grille vide")
    if len({params_sha256(p) for p in points}) != len(points):
        raise ProtocolError("configuration en double dans la grille : elle compterait deux fois")
    sessions, _ = engine.common_calendar(history, start, end)
    development, first_final = partition(sessions, config)
    split = Partition(
        development=(sessions[0], sessions[development - 1]),
        embargo_sessions=config.split.embargo_sessions,
        final=(sessions[first_final], sessions[-1]),
        development_sessions=development,
        final_sessions=len(sessions) - first_final,
    )
    code = strategy_code_sha256(strategy)

    def ended(gates: Sequence[Gate], evaluation: Evaluation | None = None) -> ProtocolResult:
        return ProtocolResult(
            strategy_id=strategy_id,
            code_sha256=code,
            grid=tuple(points),
            partition=split,
            verdict=verdict(gates),
            gates=tuple(gates),
            breaches=tuple(breaches),
            evaluation=evaluation,
            invariance_days=tuple(sample),
        )

    def replay(params: Mapping[str, ParamValue], first: date, last: date, fees: Costs):
        return engine.run(
            strategy,
            params,
            history,
            start=first,
            end=last,
            cutoff=cutoff,
            costs=fees,
            initial_cash=initial_cash,
        )

    cutoff = config.execution.decision_cutoff_utc
    sample = invariance_sample(sessions)
    stress = config.gates.cost_stress_multiplier
    breaches: list[Breach] = []
    try:
        for params in points:
            breaches += truncation_breaches(
                strategy, params, history, sessions=sessions, sample=sample, cutoff=cutoff
            )
        if breaches:
            return ended([Gate("r10", R10_LABEL, "echouee", f"{len(breaches)} écart(s)")])
        runs = [replay(p, sessions[0], sessions[development - 1], costs) for p in points]
        chosen = int(np.argmax(_column_sharpes(runs)))
        final = replay(points[chosen], sessions[first_final], sessions[-1], costs)
        final_stressed = replay(
            points[chosen], sessions[first_final], sessions[-1], costs.stressed(stress)
        )
        whole = replay(points[chosen], sessions[0], sessions[-1], costs)
    except LookAheadError as exc:
        return ended([Gate("r10", R10_LABEL, "echouee", f"lecture refusée par la vue : {exc}")])
    except StrategyError as exc:
        return ended([Gate("contrat", "Contrat de la stratégie", "echouee", str(exc))])

    returns = np.column_stack([value_returns(r.values).to_numpy() for r in runs])
    tested = walk_forward(returns, config.walk_forward.blocks)
    reference_final = reference_whole = None
    if benchmark is not None:
        reference_final = benchmark_curve(
            benchmark.history, sessions[first_final:], costs, initial_cash
        )
        reference_whole = benchmark_curve(benchmark.history, sessions, costs, initial_cash)

    def trial(run: BacktestResult, origin: TrialOrigin) -> ResearchTrial:
        return make_trial(
            strategy=strategy_id,
            code_sha256=code,
            params=run.params,
            origin=origin,
            values=run.values,
            sessions_per_year=sessions_per_year,
            costs=costs.name,
            engine=ENGINE,
        )

    trials = [trial(r, "protocole") for r in runs]
    trials.append(trial(final, "protocole-final"))
    readings = sum(
        1
        for row in store.family(strategy_id, code)
        if row.trial.code_sha256 == code and _reads_final(row.trial, split.final)
    )
    store.add_trials(trials, recorded_at=recorded_at)
    dsr, dsr_reason = _deflated(
        returns[:, chosen], trials[chosen], store.family(strategy_id, code), trials[: len(runs)]
    )
    # Returns run from the second session: return row k ends at session k + 1.
    folds = tuple(
        Fold(
            train=(sessions[f.train.start + 1], sessions[f.train.stop]),
            test=(sessions[f.test.start + 1], sessions[f.test.stop]),
            params=points[f.chosen],
        )
        for f in tested.folds
    )
    evaluation = Evaluation(
        chosen=points[chosen],
        development=engine.measures(runs[chosen], sessions_per_year),
        folds=folds,
        walk_forward_sharpe=sharpe(tested.returns.tolist(), sessions_per_year),
        pbo=pbo(returns, config.pbo.partitions),
        dsr=dsr,
        dsr_reason=dsr_reason,
        final=engine.measures(final, sessions_per_year),
        final_stressed=engine.measures(final_stressed, sessions_per_year),
        stress_multiplier=stress,
        benchmark_label=None if benchmark is None else benchmark.label,
        benchmark_sharpe=(
            None if reference_final is None else _annual_sharpe(reference_final, sessions_per_year)
        ),
        crises=tuple(crisis_measures(crises, whole.values, reference_whole)),
        final_readings_before=readings,
        trials_recorded=len(trials),
    )
    invariant = Gate(
        "r10",
        R10_LABEL,
        "reussie",
        f"{len(sample)} jours × {len(points)} configurations invariants par troncature",
    )
    return ended([invariant, *_gates(evaluation, config, split.final_sessions - 1)], evaluation)
