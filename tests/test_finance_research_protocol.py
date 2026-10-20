"""The anti-overfitting protocol (ADR-026): its statistics, its gates and its verdicts.

The deflated Sharpe ratio is checked against the worked example of Bailey and López de Prado
(2014), the PBO against a brute-force CSCV, and the whole protocol against the planted trend and a
random walk of the synthetic research dataset.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import pytest
from scipy.stats import kurtosis, rankdata, skew

from core.config.loader import CrisisWindow, ResearchConfig, load_config
from core.finance.fixtures import load_research, research_costs, research_crises
from core.finance.model import (
    CorporateAction,
    Instrument,
    PriceRow,
    ResearchTrial,
    params_sha256,
)
from core.finance.research import engine
from core.finance.research.execution import Costs
from core.finance.research.overfitting import (
    OverfittingError,
    column_sharpes,
    deflated_sharpe,
    expected_max_sharpe,
    moments,
    pbo,
    trial_variance,
    walk_forward,
)
from core.finance.research.protocol import (
    HYPOTHESES,
    Benchmark,
    CrisisMeasure,
    Gate,
    GateStatus,
    ProtocolError,
    ProtocolResult,
    _crisis_gate,
    _deflated,
    benchmark_curve,
    crisis_measures,
    invariance_sample,
    partition,
    run_protocol,
    verdict,
)
from core.finance.research.strategy import Params, Strategy, Weights
from core.finance.research.view import MarketHistory, PointInTimeView
from core.finance.store import FinanceStore, RecordedTrial

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"
TREND, WALK = "FICT-RTEND", "FICT-RALEA3"
START, END = date(2016, 1, 4), date(2025, 12, 31)
RECORDED = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
GRID = [{"short": s, "long": lg} for s in (5, 10, 20) for lg in (50, 100, 200)]
GATES = ("r10", "dsr", "pbo", "stabilite", "reference", "frais", "crises")


@pytest.fixture(scope="module")
def config() -> ResearchConfig:
    return load_config(REPO_CONFIG).research


@pytest.fixture(scope="module")
def market() -> Iterator[dict[str, MarketHistory]]:
    store = FinanceStore.memory()
    load_research(store)
    yield {i: MarketHistory.load(store, (i,)) for i in (TREND, WALK)}
    store.close()


@pytest.fixture(scope="module")
def costs() -> Costs:
    named = research_costs()
    return Costs.from_config(named.costs, named.name)


# 1. Deflated Sharpe ratio ---------------------------------------------------------------------

PAPER_SHARPE = 2.5 / math.sqrt(250)  # annual 2.5 in daily units
PAPER_VARIANCE = 0.5 / 250  # variance of the trials' annual Sharpe ratios, in daily units


def paper_dsr(trials: int, skewness: float = -3.0, kurt: float = 10.0) -> float | None:
    threshold = expected_max_sharpe(trials, PAPER_VARIANCE)
    return deflated_sharpe(PAPER_SHARPE, 1250, skewness, kurt, threshold)


@pytest.mark.parametrize(("trials", "expected"), [(100, 0.9004), (46, 0.9505)])
def test_the_dsr_reproduces_the_worked_example_of_the_paper(trials: int, expected: float) -> None:
    assert paper_dsr(trials) == pytest.approx(expected, abs=5e-5)


def test_the_dsr_falls_as_trials_accumulate() -> None:
    found = [paper_dsr(n) for n in (1, 2, 10, 46, 47, 100, 1000)]
    assert all(a is not None and b is not None and a > b for a, b in itertools.pairwise(found))
    assert (paper_dsr(46) or 0) >= 0.95 > (paper_dsr(47) or 0)
    # Normal returns forgive more trials: the 0.95 gate is crossed between 88 and 89.
    assert (paper_dsr(88, 0.0, 3.0) or 0) >= 0.95 > (paper_dsr(89, 0.0, 3.0) or 0)


def test_one_trial_or_no_dispersion_leaves_no_threshold() -> None:
    assert expected_max_sharpe(1, 0.4) == 0.0
    assert expected_max_sharpe(50, 0.0) == 0.0
    # With SR₀ = 0 the DSR is the probabilistic Sharpe ratio.
    expected = NormalDist().cdf(0.1 * math.sqrt(100) / math.sqrt(1 + 0.5 * 0.01))
    assert deflated_sharpe(0.1, 101, 0.0, 3.0, 0.0) == pytest.approx(expected, rel=1e-12)


def test_the_dsr_refuses_what_it_cannot_measure() -> None:
    with pytest.raises(OverfittingError, match="au moins un essai"):
        expected_max_sharpe(0, 0.1)
    for variance in (-0.1, math.nan, math.inf):
        with pytest.raises(OverfittingError, match="variance"):
            expected_max_sharpe(5, variance)
    with pytest.raises(OverfittingError, match="deux rendements"):
        deflated_sharpe(0.1, 1, 0.0, 3.0, 0.0)
    # 1 − γ₃·SR + (γ₄ − 1)/4·SR² ≤ 0: the formula does not apply.
    assert deflated_sharpe(1.0, 100, 3.0, 1.0, 0.0) is None


def test_moments_are_population_moments() -> None:
    assert moments([1, 2, 3, 4, 5]) == pytest.approx((0.0, 1.7))
    values = np.random.default_rng(3).standard_t(5, 500)
    assert moments(values.tolist()) == pytest.approx(
        (skew(values), kurtosis(values, fisher=False)), rel=1e-12
    )
    for flat in ([0.01] * 20, [0.0] * 5, []):  # the mean of 20 × 0.01 is not exactly 0.01
        with pytest.raises(OverfittingError, match="sans dispersion"):
            moments(flat)


def recorded(key: int, sharpe: float) -> RecordedTrial:
    """A journal row whose return series is fingerprinted by ``key``."""
    params = {"cle": key}
    trial = ResearchTrial(
        strategy="doublons",
        code_sha256="c" * 64,
        params=params,
        params_sha256=params_sha256(params),
        origin="protocole",
        start=START,
        end=END,
        sessions=1250,
        sharpe_daily=sharpe,
        sharpe_annual=sharpe * math.sqrt(252),
        series_sha256=f"{key:064x}",
        costs="test",
        engine="test",
    )
    return RecordedTrial(trial_id=key, recorded_at=RECORDED, trial=trial)


def test_repeated_trials_never_raise_the_deflated_sharpe() -> None:
    """Quant review of phase 3, M1: twenty copies of a middling trial cut the family's raw
    variance by two thirds, which lifted the DSR from 0,84 to 0,90. N grows, V may not shrink."""
    grid = [recorded(k, 0.03 + 0.03 * (k - 4.5) / 4.5) for k in range(10)]
    copies = [recorded(10, 0.03)] * 20
    returns = np.random.default_rng(3).normal(0.0006, 0.01, 1250)
    chosen = grid[-1].trial
    alone, _ = _deflated(returns, chosen, grid, [r.trial for r in grid])
    padded, _ = _deflated(returns, chosen, [*grid, *copies], [r.trial for r in grid])
    assert alone is not None and padded is not None
    assert (alone.trials, padded.trials) == (10, 30)
    raw = trial_variance([r.trial.sharpe_daily for r in [*grid, *copies]])
    assert raw < alone.variance / 3 and padded.variance == alone.variance
    assert alone.value is not None and padded.value is not None
    assert padded.value < alone.value
    # A narrow grid of this version: the copies of the past count once.
    narrow, _ = _deflated(returns, chosen, [*grid, *copies], [grid[4].trial, grid[5].trial])
    assert narrow is not None
    distinct = trial_variance([r.trial.sharpe_daily for r in [*grid, copies[0]]])
    assert narrow.variance == distinct > raw


def test_the_trial_variance_counts_a_trial_without_spread_as_zero() -> None:
    assert trial_variance([0.1, None, 0.3]) == pytest.approx(np.var([0.1, 0.0, 0.3], ddof=1))
    assert trial_variance([0.2]) == 0.0
    with pytest.raises(OverfittingError):
        trial_variance([])


# 2. Walk-forward ------------------------------------------------------------------------------


def test_the_walk_forward_is_anchored_on_equal_blocks() -> None:
    rows = np.zeros((10, 2))
    rows[:4, 1] = [0.02, 0.01, 0.03, 0.02]  # column 1 leads at first
    rows[4:, 0] = [0.05, 0.04, 0.06, 0.05, 0.04, 0.06]  # then column 0 takes over
    found = walk_forward(rows, 5)
    assert [(f.train, f.test) for f in found.folds] == [
        (range(0, 2), range(2, 4)),
        (range(0, 4), range(4, 6)),
        (range(0, 6), range(6, 8)),
        (range(0, 8), range(8, 10)),
    ]
    # On rows 0 to 5 column 1 still has the better Sharpe ratio (1.10 against 0.64).
    assert [f.chosen for f in found.folds] == [1, 1, 1, 0]
    # Each test block reads the column its training blocks chose, and no row twice.
    assert found.returns.tolist() == [0.03, 0.02, 0.0, 0.0, 0.0, 0.0, 0.04, 0.06]


def test_the_walk_forward_needs_two_returns_per_block() -> None:
    with pytest.raises(OverfittingError, match="deux blocs"):
        walk_forward(np.zeros((10, 2)), 1)
    with pytest.raises(OverfittingError, match="deux rendements par bloc"):
        walk_forward(np.zeros((9, 2)), 5)
    with pytest.raises(OverfittingError):
        walk_forward(np.array([[0.1, math.nan], [0.2, 0.1]]), 1)


def test_a_column_without_spread_has_a_sharpe_ratio_of_zero() -> None:
    rows = np.array([[0.01, 0.02], [0.01, -0.01], [0.01, 0.03]])
    found = column_sharpes(rows)
    assert found[0] == 0.0
    assert found[1] == pytest.approx(np.mean(rows[:, 1]) / np.std(rows[:, 1], ddof=1))


# 3. Probability of backtest overfitting -------------------------------------------------------


def brute_force_pbo(returns: np.ndarray, partitions: int) -> float:
    """CSCV the long way: every split of the blocks, Sharpe ratios and ranks from scratch."""
    rows, configurations = returns.shape
    kept = returns[rows % partitions :]
    blocks = np.array_split(np.arange(len(kept)), partitions)
    splits = list(itertools.combinations(range(partitions), partitions // 2))
    overfit = 0
    for chosen in splits:
        train = np.concatenate([blocks[k] for k in chosen])
        test = np.concatenate([blocks[k] for k in range(partitions) if k not in chosen])
        best = int(np.argmax(column_sharpes(kept[train])))
        omega = rankdata(column_sharpes(kept[test]))[best] / (configurations + 1)
        overfit += math.log(omega / (1 - omega)) <= 0
    return overfit / len(splits)


@pytest.mark.parametrize(
    ("rows", "configurations", "partitions"), [(203, 5, 6), (300, 12, 8), (97, 3, 4), (64, 2, 2)]
)
def test_the_pbo_matches_a_brute_force_cscv(
    rows: int, configurations: int, partitions: int
) -> None:
    generator = np.random.default_rng(rows)
    returns = generator.normal(0.0003, 0.01, (rows, configurations))
    returns[:, 1] += 0.0002
    found = pbo(returns, partitions)
    assert found.value == pytest.approx(brute_force_pbo(returns, partitions), abs=1e-12)
    assert found.combinations == math.comb(partitions, partitions // 2)
    assert (found.rows, found.dropped) == (rows - rows % partitions, rows % partitions)


def test_the_pbo_reads_every_combination_of_sixteen_blocks() -> None:
    returns = np.random.default_rng(16).normal(0.0, 0.01, (1800, 9))
    found = pbo(returns, 16)
    assert (found.combinations, found.configurations, found.dropped) == (12_870, 9, 8)
    assert found.value is not None and 0.0 <= found.value <= 1.0


def test_the_pbo_separates_a_dominant_column_from_identical_ones() -> None:
    generator = np.random.default_rng(5)
    dominant = generator.normal(0.0, 0.01, (400, 5))
    dominant[:, 2] += 0.02
    assert pbo(dominant, 8).value == 0.0
    # Identical columns all take the median rank: λ = 0 counts as overfitting [Hypothèse].
    identical = np.tile(generator.normal(0.0, 0.01, (200, 1)), (1, 4))
    assert pbo(identical, 8).value == 1.0


def test_the_pbo_of_pure_noise_is_close_to_one_half() -> None:
    found = [
        pbo(np.random.default_rng(seed).normal(0.0, 0.01, (480, 10)), 8).value for seed in range(40)
    ]
    assert all(v is not None for v in found)
    assert 0.4 < float(np.mean([v or 0.0 for v in found])) < 0.6


def test_the_pbo_says_why_it_cannot_be_evaluated() -> None:
    alone = pbo(np.random.default_rng(1).normal(0.0, 0.01, (100, 1)), 4)
    assert (alone.value, alone.reason) == (None, "moins de deux configurations")
    short = pbo(np.random.default_rng(1).normal(0.0, 0.01, (31, 3)), 16)
    assert short.value is None and short.reason is not None and "trop peu" in short.reason
    for partitions in (0, 3, 7):
        with pytest.raises(OverfittingError, match="nombre pair"):
            pbo(np.zeros((40, 3)), partitions)


# 4. Pieces of the protocol --------------------------------------------------------------------


def days(count: int, first: date = date(2024, 3, 4)) -> list[date]:
    return [first + timedelta(days=n) for n in range(count)]


def test_the_split_follows_the_research_parameters(config: ResearchConfig) -> None:
    assert (config.split.development_fraction, config.split.embargo_sessions) == (0.7, 5)
    assert config.walk_forward.blocks == 5
    assert partition(days(100), config) == (70, 75)
    with pytest.raises(ProtocolError, match="trop peu pour 5 blocs"):
        partition(days(14), config)
    with pytest.raises(ProtocolError, match="moins de trois séances"):
        partition(days(16), config)


def test_the_invariance_sample_never_takes_the_last_session() -> None:
    calendar = days(100)
    picked = invariance_sample(calendar)
    assert len(picked) == 12 and picked[0] == calendar[0] and picked[-1] == calendar[-2]
    assert invariance_sample(days(5)) == days(4)


def gate(status: GateStatus) -> Gate:
    return Gate("x", "x", status, "")


def test_one_failed_gate_fails_and_one_unknown_gate_leaves_the_verdict_open() -> None:
    assert verdict([gate("reussie"), gate("reussie")]) == "reussi"
    assert verdict([gate("reussie"), gate("non evaluable")]) == "incomplet"
    assert verdict([gate("non evaluable"), gate("echouee"), gate("reussie")]) == "echoue"


# The benchmark on a hand-made history --------------------------------------------------------

WEEK = days(5)


def close_row(instrument_id: str, day: date, value: float) -> PriceRow:
    return PriceRow(
        instrument_id=instrument_id,
        session=day,
        close=value,
        currency="EUR",
        source="fixtures",
        published_at=datetime.combine(day, time(17, 35), tzinfo=UTC),
    )


def hand_made(closes: dict[str, Sequence[float]], dividends: dict[str, float]) -> MarketHistory:
    """Daily closes over WEEK, and a dividend going ex on the fourth session."""
    store = FinanceStore.memory()
    for instrument_id in closes:
        store.add_instrument(
            Instrument(
                instrument_id=instrument_id,
                valid_from=date(2000, 1, 1),
                name=f"{instrument_id} (fictif)",
                asset_class="equity",
                currency="EUR",
                mic="XPAR",
                sector="Industrie",
                country="FR",
            ),
            recorded_at=datetime(2000, 1, 1, tzinfo=UTC),
        )
    records: list[PriceRow | CorporateAction] = [
        close_row(i, day, value)
        for i, values in closes.items()
        for day, value in zip(WEEK, values, strict=True)
    ]
    records += [
        CorporateAction(
            instrument_id=i,
            ex_date=WEEK[3],
            kind="dividend",
            value=amount,
            currency="EUR",
            source="fixtures",
            published_at=datetime.combine(WEEK[0], time(8, 0), tzinfo=UTC),
        )
        for i, amount in dividends.items()
    ]
    records.sort(key=lambda r: r.published_at)
    store.ingest(records, ingested_at=records[-1].published_at)
    history = MarketHistory.load(store, sorted(closes))
    store.close()
    return history


FEES = Costs("frais (test)", 0.001, 2.0, 0.0005)


def test_the_benchmark_pays_its_entry_and_reinvests_its_dividends() -> None:
    # FICT-A falls by its dividend on the ex-date: reinvested, its value does not move.
    history = hand_made(
        {"FICT-A": [100, 100, 110, 99, 99], "FICT-B": [50, 50, 55, 60, 45]}, {"FICT-A": 11.0}
    )
    curve = benchmark_curve(history, WEEK, FEES, 100_000.0)
    invested = 50_000 / (1.0005 * 1.001)  # the commission is above its minimum
    expected = [100_000.0, *(invested * k for k in (2.0, 2.2, 2.3, 2.0))]
    assert curve.tolist() == pytest.approx(expected, rel=1e-12)
    assert list(curve.index.date) == WEEK and curve.name == "valeur"


def test_the_benchmark_pays_the_minimum_commission_on_a_small_share() -> None:
    history = hand_made({"FICT-A": [100, 100, 110, 99, 99], "FICT-B": [50, 50, 55, 60, 45]}, {})
    curve = benchmark_curve(history, WEEK, FEES, 1_000.0)
    invested = (500 - 2.0) / 1.0005
    assert curve.iloc[1] == pytest.approx(2 * invested, rel=1e-12)
    assert curve.iloc[3] == pytest.approx(invested * (0.99 + 1.2), rel=1e-12)


def test_the_benchmark_refuses_what_it_cannot_buy() -> None:
    history = hand_made({"FICT-A": [100, 100, 110, 99, 99], "FICT-B": [50, 50, 55, 60, 45]}, {})
    with pytest.raises(ProtocolError, match="trois séances"):
        benchmark_curve(history, WEEK[:2], FEES, 100_000.0)
    with pytest.raises(ProtocolError, match="séances différentes"):
        benchmark_curve(history, [WEEK[0], WEEK[2], WEEK[4]], FEES, 100_000.0)
    with pytest.raises(ProtocolError, match="frais d'entrée"):
        benchmark_curve(history, WEEK, FEES, 4.0)


# Crises --------------------------------------------------------------------------------------

CALENDAR = days(8)


def curve(values: Sequence[float]) -> pd.Series:
    return pd.Series(values, index=pd.DatetimeIndex(CALENDAR), name="valeur")


def window(start: date | str, end: date | str, source: str = "fictif (test)") -> CrisisWindow:
    return CrisisWindow.model_validate(
        {"label": "Crise (test)", "start": start, "end": end, "source": source}
    )


def test_a_crisis_is_measured_from_the_last_session_before_it() -> None:
    ours = curve([100, 100, 100, 110, 99, 104.5, 104.5, 104.5])
    theirs = curve([100, 100, 100, 100, 95, 97, 97, 97])
    [found] = crisis_measures({"c": window(CALENDAR[3], CALENDAR[5])}, ours, theirs)
    assert found.reason is None
    assert found.strategy_return == pytest.approx(0.045)
    assert found.strategy_drawdown == pytest.approx(0.1)
    assert found.benchmark_return == pytest.approx(-0.03)
    assert found.benchmark_drawdown == pytest.approx(0.05)


def test_a_crisis_that_cannot_be_measured_says_why() -> None:
    ours = curve([100.0] * 8)
    crises = {
        "a_verifier": window("A_VERIFIER", "A_VERIFIER", "A_VERIFIER"),
        "source_a_verifier": window(CALENDAR[2], CALENDAR[4], "A_VERIFIER"),
        "avant": window(CALENDAR[0], CALENDAR[2]),
        "apres": window(CALENDAR[5], CALENDAR[-1] + timedelta(days=1)),
    }
    reasons = {m.key: m.reason for m in crisis_measures(crises, ours, ours)}
    assert reasons == {
        "a_verifier": "non couverte : dates A_VERIFIER",
        "source_a_verifier": "non couverte : dates A_VERIFIER",
        "avant": "non couverte par la fenêtre",
        "apres": "non couverte par la fenêtre",
    }
    [alone] = crisis_measures({"c": window(CALENDAR[3], CALENDAR[5])}, ours, None)
    assert alone.reason == "aucune référence"


def measure(ours: float | None, theirs: float | None, reason: str | None = None) -> CrisisMeasure:
    return CrisisMeasure("c", "Crise (test)", reason, 0.0, ours, 0.0, theirs)


def test_the_crisis_gate_fails_on_any_deeper_fall() -> None:
    assert _crisis_gate([measure(0.1, 0.1), measure(0.05, 0.2)]).status == "reussie"
    deeper = _crisis_gate([measure(0.1, 0.2), measure(0.21, 0.2), measure(None, None, "x")])
    assert deeper.status == "echouee" and "21.00% contre 20.00%" in deeper.detail
    assert _crisis_gate([measure(0.1, 0.2), measure(None, None, "x")]).status == "non evaluable"
    assert _crisis_gate([]).status == "non evaluable"


# 5. The whole protocol on the research dataset -----------------------------------------------


@dataclass
class MovingAverages:
    """Equal weight in each instrument whose short moving average is above its long one."""

    name: str = "moyennes mobiles (test)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        short, long = int(params["short"]), int(params["long"])
        weights: dict[str, float] = {}
        for instrument_id in view.instruments:
            closes = view.closes(instrument_id).to_numpy()
            if len(closes) >= long and closes[-short:].mean() > closes[-long:].mean():
                weights[instrument_id] = 1.0 / len(view.instruments)
        return weights


def protocol(
    strategy: Strategy,
    history: MarketHistory,
    journal: FinanceStore,
    config: ResearchConfig,
    costs: Costs,
    *,
    strategy_id: str = "moyennes_mobiles",
    grid: Sequence[Params] = GRID,
    end: date = END,
    benchmark: bool = True,
    crises: dict[str, CrisisWindow] | None = None,
) -> ProtocolResult:
    return run_protocol(
        strategy,
        strategy_id=strategy_id,
        grid=grid,
        history=history,
        start=START,
        end=end,
        config=config,
        costs=costs,
        initial_cash=100_000.0,
        sessions_per_year=252,
        crises=research_crises() if crises is None else crises,
        benchmark=Benchmark("achat-conservation (test)", history) if benchmark else None,
        store=journal,
        recorded_at=RECORDED,
    )


def statuses(result: ProtocolResult) -> dict[str, str]:
    return {g.key: g.status for g in result.gates}


def test_the_planted_trend_passes_every_gate(
    market: dict[str, MarketHistory], config: ResearchConfig, costs: Costs
) -> None:
    journal = FinanceStore.memory()
    result = protocol(MovingAverages(), market[TREND], journal, config, costs)
    assert result.verdict == "reussi", result.gates
    assert tuple(statuses(result)) == GATES
    assert result.hypotheses == HYPOTHESES and result.breaches == ()
    evaluation = result.evaluation
    assert evaluation is not None
    assert evaluation.pbo.value == 0.0 and evaluation.pbo.combinations == 12_870
    assert evaluation.dsr is not None and (evaluation.dsr.value or 0) > 0.999
    assert evaluation.final_readings_before == 0 and evaluation.trials_recorded == 10
    assert len(evaluation.folds) == config.walk_forward.blocks - 1
    assert evaluation.chosen in GRID
    assert [m.reason for m in evaluation.crises] == [None, None, None]
    # The split leaves the embargo out of both samples.
    sessions, _ = engine.common_calendar(market[TREND], START, END)
    split = result.partition
    assert split.development == (sessions[0], sessions[split.development_sessions - 1])
    assert split.final == (sessions[-split.final_sessions], sessions[-1])
    assert len(sessions) - split.development_sessions - split.final_sessions == 5
    # Nine development trials and the final reading, all of this code version.
    rows = journal.trials("moyennes_mobiles")
    assert [r.trial.origin for r in rows] == ["protocole"] * 9 + ["protocole-final"]
    assert {r.trial.code_sha256 for r in rows} == {result.code_sha256}
    assert rows[-1].trial.params == evaluation.chosen
    assert evaluation.dsr.trials == 10
    sharpes = [r.trial.sharpe_daily for r in rows]
    assert evaluation.dsr.variance == max(trial_variance(sharpes), trial_variance(sharpes[:9]))
    journal.close()


def test_a_second_reading_counts_every_trial_and_is_reported(
    market: dict[str, MarketHistory], config: ResearchConfig, costs: Costs
) -> None:
    journal = FinanceStore.memory()
    first = protocol(MovingAverages(), market[TREND], journal, config, costs)
    unknown = {"crise": window("A_VERIFIER", "A_VERIFIER", "A_VERIFIER")}
    second = protocol(
        MovingAverages(), market[TREND], journal, config, costs, benchmark=False, crises=unknown
    )
    assert second.verdict == "incomplet", second.gates
    gates = statuses(second)
    assert (gates["reference"], gates["crises"]) == ("non evaluable", "non evaluable")
    assert second.evaluation is not None and first.evaluation is not None
    assert second.evaluation.final_readings_before == 1
    assert second.evaluation.dsr is not None and second.evaluation.dsr.trials == 20
    assert journal.trial_count("moyennes_mobiles") == 20
    journal.close()


def test_a_random_walk_fails(
    market: dict[str, MarketHistory], config: ResearchConfig, costs: Costs
) -> None:
    journal = FinanceStore.memory()
    result = protocol(
        MovingAverages(), market[WALK], journal, config, costs, strategy_id="marche_aleatoire"
    )
    assert result.verdict == "echoue"
    gates = statuses(result)
    assert gates["r10"] == "reussie"
    assert "echouee" in (gates["dsr"], gates["pbo"], gates["stabilite"])
    assert journal.trial_count("marche_aleatoire") == 10
    journal.close()


@dataclass
class AroundTheView:
    """Trap: reaches the history behind its view, where nothing guards the dates."""

    name: str = "contournement de la vue (piège)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        last = view.last_close(TREND)
        future = view._history.final_closes(TREND).iloc[-1]  # the leak under test
        return {TREND: 1.0} if last is not None and future > last[1] else {}


@dataclass
class NextSession:
    """Trap: each decision asks for the next session's close."""

    calendar: Sequence[date]
    name: str = "lecture de t+1 (piège)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        view.closes(TREND, end=self.calendar[self.calendar.index(view.day) + 1])
        return {TREND: 1.0}


@dataclass
class Leveraged:
    name: str = "levier (piège)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        return {TREND: 1.5}


SHORT_END = date(2017, 12, 29)


def test_a_strategy_that_reads_the_future_fails_and_records_nothing(
    market: dict[str, MarketHistory], config: ResearchConfig, costs: Costs
) -> None:
    history = market[TREND]
    calendar, _ = engine.common_calendar(history, START, SHORT_END)
    journal = FinanceStore.memory()
    for trap, detail in [(AroundTheView(), "écart"), (NextSession(calendar), "lecture refusée")]:
        result = protocol(trap, history, journal, config, costs, grid=[{}], end=SHORT_END)
        assert result.verdict == "echoue" and result.evaluation is None
        [only] = result.gates
        assert (only.key, only.status) == ("r10", "echouee") and detail in only.detail
    assert journal.trial_count("moyennes_mobiles") == 0
    journal.close()


def test_a_strategy_that_breaks_its_contract_fails_and_records_nothing(
    market: dict[str, MarketHistory], config: ResearchConfig, costs: Costs
) -> None:
    journal = FinanceStore.memory()
    result = protocol(Leveraged(), market[TREND], journal, config, costs, grid=[{}], end=SHORT_END)
    assert result.verdict == "echoue" and result.evaluation is None
    [only] = result.gates
    assert (only.key, only.status) == ("contrat", "echouee") and "levier" in only.detail
    assert journal.trial_count("moyennes_mobiles") == 0
    journal.close()


@pytest.mark.parametrize(
    ("strategy_id", "grid", "message"),
    [
        ("moyennes-mobiles", GRID, "identifiant de stratégie invalide"),
        ("moyennes_mobiles", [], "grille vide"),
        ("moyennes_mobiles", [{"short": 5, "long": 50}, {"long": 50, "short": 5}], "en double"),
    ],
)
def test_a_protocol_that_cannot_start_refuses_before_any_run(
    market: dict[str, MarketHistory],
    config: ResearchConfig,
    costs: Costs,
    strategy_id: str,
    grid: Sequence[Params],
    message: str,
) -> None:
    journal = FinanceStore.memory()
    with pytest.raises(ProtocolError, match=message):
        protocol(
            MovingAverages(),
            market[TREND],
            journal,
            config,
            costs,
            strategy_id=strategy_id,
            grid=grid,
        )
    assert journal.trial_count(strategy_id) == 0
    journal.close()
