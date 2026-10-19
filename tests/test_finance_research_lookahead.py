"""Injection tests: a backtest that reads data published after its decision fails (R10, §17)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.finance.adjust import Adjustment
from core.finance.fixtures import RESEARCH_FETCHED_AT, load_research
from core.finance.model import CorporateAction, Instrument, PriceRow
from core.finance.research.engine import run
from core.finance.research.execution import Costs
from core.finance.research.lookahead import truncation_breaches
from core.finance.research.strategy import Params, Strategy, StrategyError, Weights
from core.finance.research.view import (
    LookAheadError,
    MarketHistory,
    PointInTimeView,
    decision_time,
)
from core.finance.store import FinanceStore

CUTOFF = time(21, 0)
TREND, WALKS = "FICT-RTEND", ("FICT-RALEA1", "FICT-RALEA2", "FICT-RALEA3")
UNIVERSE = (TREND, *WALKS)
MODES: tuple[Adjustment, ...] = ("none", "split", "total_return")
FREE = Costs("sans frais (test)", 0.0, 0.0, 0.0)
LATER = RESEARCH_FETCHED_AT + timedelta(hours=1)
Record = PriceRow | CorporateAction


# Histories and what a decision sees -----------------------------------------------------------


def research_store() -> FinanceStore:
    store = FinanceStore.memory()
    load_research(store)
    return store


@pytest.fixture(scope="module")
def clean() -> Iterator[MarketHistory]:
    store = research_store()
    yield MarketHistory.load(store, UNIVERSE)
    store.close()


def injected(records: Sequence[Record]) -> MarketHistory:
    """The research dataset plus records slipped into the store afterwards."""
    store = research_store()
    store.ingest(records, ingested_at=LATER)
    history = MarketHistory.load(store, UNIVERSE)
    store.close()
    return history


def sessions(history: MarketHistory, start: date, end: date) -> list[date]:
    days = [s.date() for s in history.final_closes(TREND).index]
    return [d for d in days if start <= d <= end]


def snapshot(view: PointInTimeView) -> list[object]:
    """Everything a strategy can read at its decision date."""
    reads: list[object] = []
    for instrument_id in view.instruments:
        for mode in MODES:
            series = view.closes(instrument_id, adjust=mode)
            reads.append((instrument_id, mode, list(series.index), series.tolist()))
        reads += [view.corporate_actions(instrument_id), view.last_close(instrument_id)]
    return reads


def backtest(strategy: Strategy, history: MarketHistory, start: date, end: date) -> None:
    run(
        strategy,
        {},
        history,
        start=start,
        end=end,
        cutoff=CUTOFF,
        costs=FREE,
        initial_cash=100_000.0,
    )


@dataclass
class Recorder:
    """Stays in cash and records what each decision could read."""

    seen: dict[date, list[object]] = field(default_factory=dict)
    name: str = "enregistreur (test)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        self.seen[view.day] = snapshot(view)
        return {}


# 1. Reading the next session ------------------------------------------------------------------


@dataclass
class NextSession:
    """Trap: Monday's decision asks for Tuesday's close."""

    calendar: Sequence[date]
    bound: str
    adjust: Adjustment
    name: str = "lecture de t+1 (piège)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        following = self.calendar[self.calendar.index(view.day) + 1]
        view.closes(TREND, adjust=self.adjust, **{self.bound: following})  # type: ignore[arg-type]
        return {TREND: 1.0}


@pytest.mark.parametrize("bound", ["end", "start"])
@pytest.mark.parametrize("adjust", MODES)
def test_reading_the_next_session_stops_the_backtest(
    clean: MarketHistory, bound: str, adjust: Adjustment
) -> None:
    calendar = sessions(clean, date(2020, 3, 2), date(2020, 3, 31))
    with pytest.raises(LookAheadError, match="03/03/2020 demandée par une décision du 02/03/2020"):
        backtest(NextSession(calendar, bound, adjust), clean, calendar[0], calendar[-1])
    # The guard holds on the date, not on what the data happens to contain.
    with pytest.raises(LookAheadError):
        clean.cut(calendar[0], CUTOFF).view(calendar[0], CUTOFF).closes(TREND, end=calendar[1])


@dataclass
class AroundTheView:
    """Trap: reaches the history behind its view, where nothing guards the dates."""

    name: str = "contournement de la vue (piège)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        last = view.last_close(TREND)
        future = view._history.final_closes(TREND).iloc[-1]  # the leak under test
        return {TREND: 1.0} if last is not None and future > last[1] else {}


def test_reaching_around_the_view_breaks_truncation_invariance(clean: MarketHistory) -> None:
    calendar = sessions(clean, date(2016, 1, 4), date(2025, 12, 31))
    breaches = truncation_breaches(
        AroundTheView(), {}, clean, sessions=calendar, sample=calendar[::250], cutoff=CUTOFF
    )
    assert breaches and {b.check for b in breaches} == {"decide"}
    assert "FICT-RTEND : 1 contre 0" in breaches[0].detail


# 2. A vectorised shift(-1) --------------------------------------------------------------------


@dataclass
class Momentum:
    """All in when the last close rose; the vectorised form compares with ``shift(1)``."""

    instrument_id: str = TREND
    lag: int = 1  # -1 turns it into the trap: tomorrow's close compared with today's
    name: str = "momentum (test)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        known = view.closes(self.instrument_id)
        rose = len(known) > 1 and known.iloc[-1] > known.iloc[-2]
        return {self.instrument_id: 1.0} if rose else {}

    def weights_frame(
        self, history: MarketHistory, params: Params, sessions: Sequence[date], cutoff: time
    ) -> pd.DataFrame:
        close = history.final_closes(self.instrument_id)
        moved = close > close.shift(1) if self.lag == 1 else close.shift(-1) > close
        frame = pd.DataFrame({self.instrument_id: moved.astype(float)})
        return frame.reindex(pd.DatetimeIndex(sessions))


def test_a_vectorised_shift_minus_one_breaks_truncation_invariance(clean: MarketHistory) -> None:
    calendar = sessions(clean, date(2016, 1, 4), date(2025, 12, 31))
    sample = calendar[1::97]
    breaches = truncation_breaches(
        Momentum(lag=-1), {}, clean, sessions=calendar, sample=sample, cutoff=CUTOFF
    )
    assert {b.check for b in breaches} == {"weights_frame", "decide_vs_frame"}
    assert len({b.day for b in breaches}) > len(sample) / 4


def test_an_honest_vectorised_form_passes_on_clean_data() -> None:
    closes = [100.0, 101.0, 99.5, 99.5, 102.0, 101.0, 103.0, 104.0, 100.0, 100.5]
    history = synthetic([close_row("FICT-A", DAYS[k], v) for k, v in enumerate(closes)])
    calendar = DAYS[: len(closes)]
    honest = truncation_breaches(
        Momentum("FICT-A"), {}, history, sessions=calendar, sample=calendar, cutoff=CUTOFF
    )
    assert honest == []
    trap = truncation_breaches(
        Momentum("FICT-A", lag=-1), {}, history, sessions=calendar, sample=calendar, cutoff=CUTOFF
    )
    # The cut history does not know tomorrow, so the frame row changes exactly when it rose.
    assert {b.day for b in trap if b.check == "weights_frame"} == {DAYS[k] for k in (0, 3, 5, 6, 8)}


def test_a_vectorised_form_must_read_closes_as_published(clean: MarketHistory) -> None:
    """Final closes carry corrections and late prints a decision could not see yet."""
    calendar = sessions(clean, date(2016, 1, 4), date(2025, 12, 31))
    surprises = surprise_days(clean, calendar)
    breaches = truncation_breaches(
        Momentum(), {}, clean, sessions=calendar, sample=surprises, cutoff=CUTOFF
    )
    assert len(surprises) > 10
    assert {b.check for b in breaches} == {"weights_frame", "decide_vs_frame"}


def surprise_days(history: MarketHistory, calendar: Sequence[date]) -> list[date]:
    """Days whose trend close, at the decision, is missing or not yet in its final revision."""
    final = history.final_closes(TREND)
    found = []
    for day in calendar:
        last = history.view(day, CUTOFF).last_close(TREND)
        if last != (day, float(final.loc[pd.Timestamp(day)])):
            found.append(day)
    return found


@dataclass
class Crossover:
    """Honest decide-only strategy: fast mean of total-return closes above the slow one."""

    name: str = "croisement (test)"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        chosen = []
        for instrument_id in view.instruments:
            known = view.closes(instrument_id, adjust="total_return")
            if len(known) >= 50 and known.iloc[-10:].mean() > known.iloc[-50:].mean():
                chosen.append(instrument_id)
        return {i: 1 / len(chosen) for i in chosen}


def test_an_honest_strategy_is_invariant_on_the_research_traps(clean: MarketHistory) -> None:
    calendar = sessions(clean, date(2016, 1, 4), date(2025, 12, 31))
    traps = [date(2021, 5, 14), date(2021, 5, 17), date(2021, 6, 11), date(2021, 6, 14)]
    sample = [*calendar[::211], *traps]
    assert (
        truncation_breaches(Crossover(), {}, clean, sessions=calendar, sample=sample, cutoff=CUTOFF)
        == []
    )


def test_the_check_refuses_what_it_cannot_compare(clean: MarketHistory) -> None:
    calendar = sessions(clean, date(2020, 1, 2), date(2020, 1, 31))

    @dataclass
    class Ragged(Momentum):
        def weights_frame(
            self, history: MarketHistory, params: Params, sessions: Sequence[date], cutoff: time
        ) -> pd.DataFrame:
            return super().weights_frame(history, params, sessions[1:], cutoff)

    with pytest.raises(StrategyError, match="une ligne par séance demandée"):
        truncation_breaches(
            Ragged(), {}, clean, sessions=calendar, sample=calendar[:1], cutoff=CUTOFF
        )
    with pytest.raises(ValueError, match="hors des séances"):
        truncation_breaches(
            Crossover(), {}, clean, sessions=calendar, sample=[date(2020, 2, 3)], cutoff=CUTOFF
        )


# 3. A close published after the decision ------------------------------------------------------


def test_a_close_published_after_the_decision_is_invisible_until_then(
    clean: MarketHistory,
) -> None:
    published = datetime(2020, 6, 18, 9, tzinfo=UTC)
    session = date(2020, 6, 12)
    wrong = float(clean.final_closes(TREND).loc[pd.Timestamp(session)]) * 100
    history = injected([close_row(TREND, session, wrong, published)])
    start, end = date(2020, 6, 1), date(2020, 6, 30)
    seen = {}
    for name, source in (("clean", clean), ("injected", history)):
        recorder = Recorder()
        backtest(recorder, source, start, end)
        seen[name] = recorder.seen
    before = [d for d in seen["clean"] if decision_time(d, CUTOFF) < published]
    after = [d for d in seen["clean"] if decision_time(d, CUTOFF) >= published]
    assert len(before) == 13 and len(after) == 8
    assert all(seen["injected"][d] == seen["clean"][d] for d in before)
    assert all(seen["injected"][d] != seen["clean"][d] for d in after)  # it is really there

    @dataclass
    class Forcing:
        name: str = "lecture forcée (piège)"

        def decide(self, view: PointInTimeView, params: Params) -> Weights:
            view.closes(TREND, end=published.date())
            return {}

    with pytest.raises(LookAheadError, match="18/06/2020 demandée par une décision du 01/06/2020"):
        backtest(Forcing(), history, start, end)


# 4. A future split ----------------------------------------------------------------------------


def test_a_future_split_changes_no_price_seen_before_its_publication(
    clean: MarketHistory,
) -> None:
    published, ex = datetime(2019, 9, 2, 18, tzinfo=UTC), date(2019, 9, 16)
    history = injected(
        [
            CorporateAction(
                instrument_id=WALKS[0],
                ex_date=ex,
                kind="split",
                value=2.0,
                source="fixtures",
                published_at=published,
            )
        ]
    )
    days = sessions(clean, date(2019, 8, 1), date(2019, 9, 30))
    for day in days:
        seen, expected = history.view(day, CUTOFF), clean.view(day, CUTOFF)
        if decision_time(day, CUTOFF) < published:
            assert snapshot(seen) == snapshot(expected)
            continue
        assert ex in [a.ex_date for a in seen.corporate_actions(WALKS[0])]
        pd.testing.assert_series_equal(
            seen.closes(WALKS[0]), expected.closes(WALKS[0]), check_exact=True
        )
        window = {"end": min(day, ex - timedelta(days=1))}
        for mode in ("split", "total_return"):
            moved = seen.closes(WALKS[0], adjust=mode, **window)
            reference = expected.closes(WALKS[0], adjust=mode, **window)
            if day < ex:  # announced, not effective: no price moves before its ex-date
                pd.testing.assert_series_equal(moved, reference, check_exact=True)
            else:
                assert moved.tolist() == pytest.approx((reference / 2).tolist(), rel=1e-12)


# 5. Hypothesis: no decision depends on data published after it -----------------------------

DAYS = [date(2024, 3, 4) + timedelta(days=n) for n in range(20)]
PRICES = st.floats(5, 300).map(lambda v: round(v, 2))


def close_row(
    instrument_id: str, day: date, value: float, published: datetime | None = None
) -> PriceRow:
    return PriceRow(
        instrument_id=instrument_id,
        session=day,
        close=value,
        currency="EUR",
        source="fixtures",
        published_at=published or datetime.combine(day, time(17, 35), tzinfo=UTC),
    )


def synthetic(records: Sequence[Record]) -> MarketHistory:
    store = FinanceStore.memory()
    for instrument_id in sorted({r.instrument_id for r in records}):
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
    ordered = sorted(records, key=lambda r: r.published_at)
    store.ingest(ordered, ingested_at=ordered[-1].published_at)
    history = MarketHistory.load(store, sorted({r.instrument_id for r in records}))
    store.close()
    return history


@st.composite
def action(draw: st.DrawFn, instrument_id: str, ex: date, published: datetime) -> CorporateAction:
    if draw(st.booleans()):
        ratio = draw(st.sampled_from([0.5, 2.0]))  # a dividend stays below the last close
        return CorporateAction(
            instrument_id=instrument_id,
            ex_date=ex,
            kind="split",
            value=ratio,
            source="fixtures",
            published_at=published,
        )
    return CorporateAction(
        instrument_id=instrument_id,
        ex_date=ex,
        kind="dividend",
        value=draw(st.floats(0.01, 0.5).map(lambda v: round(v, 2))),
        currency="EUR",
        source="fixtures",
        published_at=published,
    )


@st.composite
def futures(draw: st.DrawFn) -> tuple[list[Record], int, list[Record]]:
    """A market, a decision day and records published after that decision."""
    count = draw(st.integers(2, 12))
    t = draw(st.integers(0, count - 1))
    decided = decision_time(DAYS[t], CUTOFF)
    past: list[Record] = []
    future: list[Record] = []
    for instrument_id in ("FICT-A", "FICT-B"):
        for k in range(count):
            late = draw(st.booleans()) and draw(st.booleans())
            evening = datetime.combine(DAYS[k], time(17, 35), tzinfo=UTC)
            published = evening + timedelta(hours=14) if late else evening
            past.append(close_row(instrument_id, DAYS[k], draw(PRICES), published))
        for _ in range(draw(st.integers(0, 2))):
            ex, announced = draw(st.integers(1, count + 2)), draw(st.integers(0, count - 1))
            evening = datetime.combine(DAYS[announced], time(18), tzinfo=UTC)
            past.append(draw(action(instrument_id, DAYS[ex], evening)))
        for k in draw(st.lists(st.integers(0, count + 2), max_size=4)):
            evening = datetime.combine(DAYS[k], time(17, 35), tzinfo=UTC)
            after = max(decided, evening) + timedelta(hours=draw(st.integers(1, 48)))
            future.append(close_row(instrument_id, DAYS[k], draw(PRICES), after))
        for _ in range(draw(st.integers(0, 2))):
            ex = DAYS[draw(st.integers(1, count + 2))]
            after = decided + timedelta(hours=draw(st.integers(1, 400)))
            future.append(draw(action(instrument_id, ex, after)))
    return past, t, future


@settings(max_examples=60, deadline=None)
@given(case=futures())
def test_no_decision_depends_on_data_published_after_it(
    case: tuple[list[Record], int, list[Record]],
) -> None:
    past, t, future = case
    day = DAYS[t]
    expected = snapshot(synthetic(past).view(day, CUTOFF))
    both = synthetic([*past, *future])
    assert snapshot(both.view(day, CUTOFF)) == expected
    assert snapshot(both.cut(day, CUTOFF).view(day, CUTOFF)) == expected
