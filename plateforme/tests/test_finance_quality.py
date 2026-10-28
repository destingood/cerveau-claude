"""Data quality checks of a price series (ADR-016, D12): gaps, corporate actions, outliers."""

from __future__ import annotations

import json
import math
import random
from datetime import UTC, date, datetime, timedelta

import exchange_calendars as xc
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.config.loader import DataQuality
from core.finance.model import CorporateAction, Instrument, PriceRow
from core.finance.quality import QualityError, QualityReport, assess, record
from core.finance.store import FinanceStore, FinanceStoreError

ID = "FICT-ACME"
CAL = xc.get_calendar("XPAR", start=date(2025, 1, 1), end=date(2027, 12, 31))
NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)  # a Sunday: the last session closed is Friday 16
SESSIONS = [s.date() for s in CAL.sessions_in_range("2025-09-01", "2026-10-16")][-260:]
WINDOW = 250
SETTINGS = DataQuality(
    max_staleness_sessions=1,
    min_quality_score_above_N1=0.9,
    outlier_robust_z=3.5,
    max_unexplained_move=0.3,
)


def close_at(session: date) -> datetime:
    return CAL.session_close(pd.Timestamp(session)).to_pydatetime()


def series(seed: int = 7) -> dict[date, float]:
    """Gaussian log returns of 1.5 % a session, from 100."""
    rng, level, closes = random.Random(seed), 100.0, {}  # noqa: S311 - reproducible fixtures
    for session in SESSIONS:
        level *= math.exp(rng.gauss(0, 0.015))
        closes[session] = level
    return closes


def make_store(
    closes: dict[date, float], *actions: CorporateAction, mic: str = "XPAR"
) -> FinanceStore:
    store = FinanceStore.memory()
    instrument = Instrument(
        instrument_id=ID,
        valid_from=date(2020, 1, 1),
        name="Acme fictive",
        asset_class="equity",
        currency="EUR",
        mic=mic,
        sector="Industrie",
        country="FR",
    )
    store.add_instrument(instrument, recorded_at=datetime(2020, 1, 1, tzinfo=UTC))
    rows = [
        PriceRow(
            instrument_id=ID,
            session=session,
            close=close,
            currency="EUR",
            source="fixtures",
            published_at=close_at(session) if CAL.is_session(session) else end(session),
        )
        for session, close in closes.items()
    ]
    store.ingest([*rows, *actions], ingested_at=NOW)
    return store


def end(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 18, tzinfo=UTC)


def action(kind: str, ex_date: date, value: float) -> CorporateAction:
    return CorporateAction(
        instrument_id=ID,
        ex_date=ex_date,
        kind=kind,  # type: ignore[arg-type]
        value=value,
        currency="EUR" if kind == "dividend" else None,
        source="fixtures",
        published_at=close_at(ex_date) - timedelta(days=7),
    )


def check(store: FinanceStore, **changes: object) -> QualityReport:
    options: dict[str, object] = {
        "as_of": NOW,
        "settings": SETTINGS,
        "window_sessions": WINDOW,
        **changes,
    }
    return assess(store, ID, **options)  # type: ignore[arg-type]


# A clean series ---------------------------------------------------------------------------


def test_a_clean_series_scores_full_marks() -> None:
    report = check(make_store(series()))
    assert (report.gaps, report.corporate_actions, report.freshness) == (1.0, 1.0, 1.0)
    assert report.outliers is not None and report.outliers > 0.99
    details = report.details
    assert (details.window_start, details.last_closed) == (SESSIONS[-WINDOW], SESSIONS[-1])
    assert (details.expected_sessions, details.returns, details.stale_sessions) == (250, 249, 0)
    assert details.not_evaluated == {}
    assert report.score == report.outliers
    assert report.gate(0.9) == "suffisante"


def test_the_window_follows_the_exchange_calendar() -> None:
    sessions = check(make_store(series())).details
    # XPAR shuts on Good Friday and Easter Monday 2026, which fall inside the window.
    assert sessions.window_start is not None and sessions.window_start < date(2026, 4, 3)
    assert not CAL.is_session(pd.Timestamp("2026-04-03"))
    assert not CAL.is_session(pd.Timestamp("2026-04-06"))


# Gaps -------------------------------------------------------------------------------------


def test_a_missing_session_is_a_gap() -> None:
    closes = series()
    del closes[SESSIONS[-100]]
    report = check(make_store(closes))
    assert report.details.missing == [SESSIONS[-100]]
    assert report.gaps == pytest.approx(1 - 1 / 250)
    assert report.corporate_actions == 1.0


def test_a_close_on_a_holiday_is_a_gap() -> None:
    closes = series()
    closes[date(2026, 4, 3)] = closes[date(2026, 4, 2)]
    report = check(make_store(closes))
    assert report.details.unexpected == [date(2026, 4, 3)]
    assert report.gaps == pytest.approx(1 - 1 / 250)


def test_a_short_history_is_not_a_gap() -> None:
    closes = {s: c for s, c in series().items() if s >= SESSIONS[-40]}
    report = check(make_store(closes))
    assert (report.gaps, report.details.expected_sessions) == (1.0, 40)


@settings(max_examples=20, deadline=None)
@given(st.sets(st.integers(min_value=2, max_value=WINDOW - 1), max_size=30))
def test_the_gap_score_counts_every_missing_session(dropped: set[int]) -> None:
    closes = series()
    for offset in dropped:
        del closes[SESSIONS[-offset]]
    report = check(make_store(closes))
    assert report.details.missing == sorted(SESSIONS[-offset] for offset in dropped)
    assert report.gaps == pytest.approx(1 - len(dropped) / 250)


# Corporate actions and outliers -----------------------------------------------------------


def test_a_bad_print_is_caught_twice() -> None:
    closes = series()
    closes[SESSIONS[-50]] *= 10
    report = check(make_store(closes))
    moves = report.details.moves
    assert [m.session for m in moves] == [SESSIONS[-50], SESSIONS[-49]]
    assert [round(m.log_return / math.log(10)) for m in moves] == [1, -1]
    assert {o.session for o in report.details.outliers} >= {SESSIONS[-50], SESSIONS[-49]}
    assert (report.corporate_actions, report.score) == (0.0, 0.0)
    assert report.gate(0.9) == "insuffisante"


def test_an_undeclared_split_is_an_unexplained_move() -> None:
    closes = series()
    for session in SESSIONS[-80:]:
        closes[session] /= 2
    report = check(make_store(closes))
    [move] = report.details.moves
    assert (move.session, move.declared_split) == (SESSIONS[-80], False)
    assert move.log_return == pytest.approx(-math.log(2), abs=0.1)
    assert report.corporate_actions == 0.0


def test_a_declared_split_the_prices_show_is_explained() -> None:
    closes = series()
    for session in SESSIONS[-80:]:
        closes[session] /= 2
    report = check(make_store(closes, action("split", SESSIONS[-80], 2.0)))
    assert (report.details.moves, report.corporate_actions) == ([], 1.0)


def test_a_declared_split_the_prices_do_not_show_is_flagged() -> None:
    report = check(make_store(series(), action("split", SESSIONS[-80], 2.0)))
    [move] = report.details.moves
    assert (move.session, move.declared_split) == (SESSIONS[-80], True)
    assert move.log_return == pytest.approx(math.log(2), abs=0.1)


def test_a_three_for_two_split_left_out_still_shows() -> None:
    closes = series()
    for session in SESSIONS[-80:]:
        closes[session] /= 1.5
    report = check(make_store(closes))
    assert [m.session for m in report.details.moves] == [SESSIONS[-80]]


def test_a_dividend_above_the_previous_close_fails_the_check() -> None:
    report = check(make_store(series(), action("dividend", SESSIONS[-30], 1000.0)))
    assert report.details.adjustment_error is not None
    assert report.corporate_actions == 0.0


def test_constant_prices_leave_the_outlier_check_without_a_scale() -> None:
    report = check(make_store(dict.fromkeys(SESSIONS, 100.0)))
    assert report.outliers is None
    assert "MAD nulle" in report.details.not_evaluated["outliers"]
    assert (report.corporate_actions, report.score) == (1.0, None)
    assert report.gate(0.9) == "non_evaluable"


# Freshness and point in time --------------------------------------------------------------


@pytest.mark.parametrize(("dropped", "freshness"), [(0, 1.0), (1, 1.0), (2, 0.0), (5, 0.0)])
def test_freshness_counts_the_sessions_closed_since_the_last_close(
    dropped: int, freshness: float
) -> None:
    closes = series()
    for session in SESSIONS[len(SESSIONS) - dropped :]:
        del closes[session]
    report = check(make_store(closes))
    assert (report.details.stale_sessions, report.freshness) == (dropped, freshness)
    assert report.gaps == 1.0  # a stale series is not also gapped


def test_a_session_not_yet_closed_is_not_expected() -> None:
    as_of = close_at(SESSIONS[-1]) - timedelta(hours=1)
    report = check(make_store(series()), as_of=as_of)
    assert (report.details.last_closed, report.details.last_received) == (SESSIONS[-2],) * 2
    assert (report.gaps, report.freshness) == (1.0, 1.0)


def test_a_close_dated_on_a_session_still_open_is_unexpected() -> None:
    closes = series()
    store = make_store({s: c for s, c in closes.items() if s != SESSIONS[-1]})
    early = PriceRow(
        instrument_id=ID,
        session=SESSIONS[-1],
        close=closes[SESSIONS[-1]],
        currency="EUR",
        source="fixtures",
        published_at=close_at(SESSIONS[-1]) - timedelta(hours=4),
    )
    store.ingest([early], ingested_at=NOW)
    report = check(store, as_of=close_at(SESSIONS[-1]) - timedelta(hours=1))
    assert report.details.unexpected == [SESSIONS[-1]]
    assert report.gaps is not None and report.gaps < 1


def test_strict_mode_sees_only_what_was_ingested() -> None:
    store = make_store(series())
    report = check(store, as_of=NOW - timedelta(days=1), strict=True)
    assert report.sub_scores == dict.fromkeys(report.sub_scores)
    assert set(report.details.not_evaluated.values()) == {"aucun cours visible à cette date"}
    assert check(store, strict=True).score == check(store).score


# What cannot be evaluated -----------------------------------------------------------------


def test_unset_cut_offs_leave_their_checks_unevaluated() -> None:
    unset = SETTINGS.model_copy(
        update={"outlier_robust_z": "A_DEFINIR", "max_unexplained_move": "A_DEFINIR"}
    )
    report = check(make_store(series()), settings=unset)
    assert (report.gaps, report.freshness) == (1.0, 1.0)
    assert (report.outliers, report.corporate_actions, report.score) == (None, None, None)
    assert set(report.details.not_evaluated) == {"outliers", "corporate_actions"}
    assert all("ADR-016" in reason for reason in report.details.not_evaluated.values())
    assert report.gate(0.9) == "non_evaluable"


def test_an_unset_threshold_cannot_pass_the_gate() -> None:
    assert check(make_store(series())).gate("A_DEFINIR") == "non_evaluable"


def test_an_exchange_without_a_calendar_skips_gaps_and_freshness() -> None:
    assert "ZZZZ" not in xc.get_calendar_names()
    report = check(make_store(series(), mic="ZZZZ"))
    assert (report.gaps, report.freshness) == (None, None)
    assert report.details.not_evaluated["gaps"] == "calendrier inconnu pour la place ZZZZ"
    assert (report.corporate_actions, report.details.returns) == (1.0, 249)


def test_no_visible_close_leaves_every_check_unevaluated() -> None:
    report = check(make_store({}))
    assert report.sub_scores == dict.fromkeys(report.sub_scores)
    assert report.details.last_received is None


def test_an_unknown_instrument_or_a_tiny_window_is_refused() -> None:
    store = make_store(series())
    with pytest.raises(QualityError, match="inconnu"):
        assess(store, "FICT-NONE", as_of=NOW, settings=SETTINGS, window_sessions=WINDOW)
    with pytest.raises(ValueError, match="deux séances"):
        check(store, window_sessions=1)


# Recording --------------------------------------------------------------------------------


def test_a_strict_score_is_recorded_once() -> None:
    store = make_store(series())
    report = check(store, strict=True)
    assert record(store, report, computed_at=NOW) is True
    assert record(store, report, computed_at=NOW + timedelta(hours=1)) is False
    [row] = store.quality_history(ID)
    assert (row["gaps"], row["score"]) == (1.0, report.score)
    assert json.loads(row["details"])["expected_sessions"] == 250
    with pytest.raises(FinanceStoreError, match="un autre score"):
        record(store, report.model_copy(update={"gaps": 0.5}), computed_at=NOW)


def test_only_a_strict_past_score_is_recorded() -> None:
    store = make_store(series())
    with pytest.raises(ValueError, match="strict"):
        record(store, check(store), computed_at=NOW)
    with pytest.raises(ValueError, match="date future"):
        record(store, check(store, strict=True), computed_at=NOW - timedelta(hours=1))
