"""The point-in-time view of a backtest: the store's answer at the cut-off, read in memory (R10)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
import pytest

from core.finance.adjust import Adjustment
from core.finance.fixtures import RESEARCH_FETCHED_AT, load_research
from core.finance.model import CorporateAction, Instrument, PriceRow
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


@pytest.fixture(scope="module")
def store() -> Iterator[FinanceStore]:
    found = FinanceStore.memory()
    load_research(found)
    yield found
    found.close()


@pytest.fixture(scope="module")
def history(store: FinanceStore) -> MarketHistory:
    return MarketHistory.load(store, UNIVERSE)


def sessions(store: FinanceStore) -> list[date]:
    return [s.date() for s in store.closes(TREND, as_of=RESEARCH_FETCHED_AT).index]


def trap_days(store: FinanceStore) -> list[date]:
    """Days around the traps: late closes, bad prints and their corrections, the split."""
    days: set[date] = set()
    for instrument_id in UNIVERSE:
        for stored in store.revisions(PriceRow, {"instrument_id": instrument_id}):
            row = stored.record
            if stored.revision == 2 or row.published_at.date() > row.session:
                days.update({row.session, row.published_at.date()})
    late = sorted(days)
    split = [date(2021, 5, 17), date(2021, 5, 18), date(2021, 6, 11), date(2021, 6, 14)]
    actions = store.corporate_actions(WALKS[0], as_of=RESEARCH_FETCHED_AT)
    dividends = [a.ex_date for a in actions][::3]
    return [*late[::31], *split, *dividends, *(d - timedelta(days=1) for d in dividends)]


def test_the_view_gives_the_store_answer_at_the_cutoff(
    store: FinanceStore, history: MarketHistory
) -> None:
    every = sessions(store)
    days = sorted({*every[::317], every[0], every[-1], *trap_days(store)})
    assert len(days) > 30
    for day in days:
        view = history.view(day, CUTOFF)
        as_of = decision_time(day, CUTOFF)
        for instrument_id in UNIVERSE:
            for mode in MODES:
                expected = store.closes(instrument_id, as_of=as_of, adjust=mode)
                seen = view.closes(instrument_id, adjust=mode)
                pd.testing.assert_series_equal(seen, expected, check_exact=True)
                if mode == "none":
                    last = (expected.index[-1].date(), expected.iloc[-1])
                    assert view.last_close(instrument_id) == last
            assert view.corporate_actions(instrument_id) == store.corporate_actions(
                instrument_id, as_of=as_of
            )


def test_a_window_is_cut_after_the_adjustment(store: FinanceStore, history: MarketHistory) -> None:
    day, window = date(2021, 12, 30), {"start": date(2021, 3, 1), "end": date(2021, 9, 30)}
    for mode in MODES:
        expected = store.closes(
            "FICT-RALEA2", as_of=decision_time(day, CUTOFF), adjust=mode, **window
        )
        seen = history.view(day, CUTOFF).closes("FICT-RALEA2", adjust=mode, **window)
        pd.testing.assert_series_equal(seen, expected, check_exact=True)
        assert seen.index[0].date() >= window["start"] and seen.index[-1].date() <= window["end"]


def test_a_history_cut_at_the_decision_gives_the_same_view(
    store: FinanceStore, history: MarketHistory
) -> None:
    every = sessions(store)
    for day in sorted({*every[::211], *trap_days(store)[::5]}):
        whole, cut = history.view(day, CUTOFF), history.cut(day, CUTOFF).view(day, CUTOFF)
        for instrument_id in UNIVERSE:
            for mode in MODES:
                pd.testing.assert_series_equal(
                    cut.closes(instrument_id, adjust=mode),
                    whole.closes(instrument_id, adjust=mode),
                    check_exact=True,
                )
            assert cut.corporate_actions(instrument_id) == whole.corporate_actions(instrument_id)


def test_reading_past_the_decision_raises(history: MarketHistory) -> None:
    view = history.view(date(2020, 6, 15), CUTOFF)
    assert view.closes(TREND, end=date(2020, 6, 15)).index[-1].date() == date(2020, 6, 15)
    with pytest.raises(LookAheadError, match="postérieure à la décision"):
        view.closes(TREND, end=date(2020, 6, 16))
    with pytest.raises(LookAheadError, match="16/06/2020"):
        view.closes(TREND, start=date(2020, 6, 16), adjust="split")


def test_the_view_refuses_what_it_cannot_answer(history: MarketHistory) -> None:
    with pytest.raises(ValueError, match="pas dans l'univers du backtest"):
        history.view(date(2020, 6, 15), CUTOFF).closes("FICT-AUTRE")
    with pytest.raises(ValueError, match="précéder sa journée"):
        PointInTimeView(history, date(2020, 6, 15), datetime(2020, 6, 14, 23, tzinfo=UTC))
    assert history.view(date(2015, 12, 31), CUTOFF).last_close(TREND) is None
    assert history.view(date(2016, 1, 4), time(0, 0)).closes(TREND).empty


def test_the_final_closes_are_the_last_revisions(
    store: FinanceStore, history: MarketHistory
) -> None:
    for instrument_id in UNIVERSE:
        pd.testing.assert_series_equal(
            history.final_closes(instrument_id),
            store.closes(instrument_id, as_of=RESEARCH_FETCHED_AT),
            check_exact=True,
        )
    assert history.currencies(WALKS[0]) == frozenset({"EUR"})


def test_an_event_keeps_its_last_amount_and_its_first_announcement() -> None:
    store = FinanceStore.memory()
    first, revised = datetime(2024, 4, 2, 18, tzinfo=UTC), datetime(2024, 4, 9, 18, tzinfo=UTC)
    store.add_instrument(
        Instrument(
            instrument_id="FICT-VUE",
            valid_from=date(2024, 1, 1),
            name="Vue (fictif)",
            asset_class="equity",
            currency="EUR",
            mic="XPAR",
            sector="Industrie",
            country="FR",
        ),
        recorded_at=first,
    )
    dividend = CorporateAction(
        instrument_id="FICT-VUE",
        ex_date=date(2024, 5, 2),
        kind="dividend",
        value=1.0,
        currency="EUR",
        source="fixtures",
        published_at=first,
    )
    close = PriceRow(
        instrument_id="FICT-VUE",
        session=date(2024, 4, 2),
        close=40.0,
        currency="EUR",
        source="fixtures",
        published_at=first,
    )
    store.ingest([close, dividend], ingested_at=first)
    store.ingest(
        [dividend.model_copy(update={"value": 1.2, "published_at": revised})], ingested_at=revised
    )
    history = MarketHistory.load(store, ["FICT-VUE"])
    [event] = history.events("FICT-VUE")
    assert (event.action.value, event.announced) == (1.2, first)
    assert [a.value for a in history.view(date(2024, 4, 5), CUTOFF).corporate_actions(
        "FICT-VUE"
    )] == [1.0]  # fmt: skip
    with pytest.raises(ValueError, match="aucun cours"):
        MarketHistory.load(store, ["FICT-VUE", "FICT-RIEN"])
