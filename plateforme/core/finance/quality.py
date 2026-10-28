"""Quality checks of a price series as known at ``as_of`` (ADR-016, D12).

Four sub-scores in [0, 1], or None when a check cannot be evaluated (R7). They look at the last
``window_sessions`` sessions of the instrument's exchange closed at ``as_of``:

- ``gaps``: closes received against the exchange's sessions (exchange-calendars); a missing
  session or a close dated on a day the exchange was shut both count;
- ``corporate_actions``: 0 as soon as a close moves by ``max_unexplained_move`` or more once the
  declared splits and dividends are applied. An undeclared split, a declared split the prices do
  not show and a bad print all leave such a move, and each one corrupts every return before it;
- ``outliers``: share of returns whose modified z-score (median and MAD) stays within
  ``outlier_robust_z``;
- ``freshness``: 1 when the last close received is at most ``max_staleness_sessions`` sessions
  behind the last session closed at ``as_of``, 0 otherwise.

The score is the minimum of the four, and None as soon as one of them is None: there is no weight
to tune, and a single anomaly is enough to lower it.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from statistics import NormalDist, median
from typing import TYPE_CHECKING, Literal

import exchange_calendars as xc
import pandas as pd
from pydantic import AwareDatetime, BaseModel, ConfigDict

from core.config.loader import DataQuality
from core.finance.adjust import AdjustmentError
from core.finance.calendars import exchange_calendar
from core.finance.model import local_date, utc_text
from core.finance.schema import QUALITY_COLUMNS

if TYPE_CHECKING:
    from core.finance.store import FinanceStore

# Iglewicz and Hoaglin: z = Φ⁻¹(3/4) (x − median) / MAD, which matches a normal score.
MAD_SCALE = NormalDist().inv_cdf(0.75)
Gate = Literal["suffisante", "insuffisante", "non_evaluable"]


class QualityError(LookupError):
    """The series cannot be checked at all: the instrument is unknown at ``as_of``."""


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Move(_Frozen):
    session: date
    log_return: float
    declared_split: bool  # a declared split takes effect here: the prices do not show it


class Outlier(_Frozen):
    session: date
    robust_z: float


class QualityDetails(_Frozen):
    mic: str
    window_sessions: int
    window_start: date | None = None
    last_closed: date | None = None  # the last session closed at as_of
    last_received: date | None = None
    expected_sessions: int = 0
    missing: list[date] = []
    unexpected: list[date] = []  # closes dated on a day the exchange was shut, or not yet closed
    moves: list[Move] = []
    adjustment_error: str | None = None
    returns: int = 0
    outliers: list[Outlier] = []
    stale_sessions: int | None = None  # counted within the window
    not_evaluated: dict[str, str] = {}  # sub-score → reason


class QualityReport(_Frozen):
    instrument_id: str
    as_of: AwareDatetime
    strict: bool
    gaps: float | None
    corporate_actions: float | None
    outliers: float | None
    freshness: float | None
    details: QualityDetails

    @property
    def sub_scores(self) -> dict[str, float | None]:
        return {name: getattr(self, name) for name in QUALITY_COLUMNS}

    @property
    def score(self) -> float | None:
        values = list(self.sub_scores.values())
        if any(v is None for v in values):
            return None
        return min(v for v in values if v is not None)

    def gate(self, threshold: float | str) -> Gate:
        """Above N1, a decision is capped at N1 unless the quality is ``suffisante`` (D12)."""
        score = self.score
        if score is None or isinstance(threshold, str):
            return "non_evaluable"
        return "suffisante" if score >= threshold else "insuffisante"


def _closed_sessions(calendar: xc.ExchangeCalendar, as_of: datetime, count: int) -> list[date]:
    """The last ``count`` sessions whose close is at or before ``as_of``."""
    moment = pd.Timestamp(as_of).tz_convert(UTC)
    upper = min(pd.Timestamp(moment.date() + timedelta(days=1)), calendar.last_session)
    sessions = list(calendar.sessions_in_range(calendar.first_session, upper))
    while sessions and calendar.session_close(sessions[-1]) > moment:
        sessions.pop()
    return [s.date() for s in sessions[-count:]]


def _cut_off(settings: DataQuality, name: str) -> float | str:
    """The cut-off, or why it cannot be used yet (R7)."""
    value = getattr(settings, name)
    return f"quality.{name} vaut {value} (ADR-016)" if isinstance(value, str) else float(value)


# (session the return starts from, session it ends on, log return)
Return = tuple[date, date, float]


def assess(
    store: FinanceStore,
    instrument_id: str,
    *,
    as_of: datetime,
    settings: DataQuality,
    window_sessions: int,
    strict: bool = False,
) -> QualityReport:
    """Check the closes of ``instrument_id`` visible at ``as_of`` (``strict``: also ingested)."""
    if window_sessions < 2:
        raise ValueError("une fenêtre d'au moins deux séances")
    instrument = store.instrument(instrument_id, as_of=as_of, strict=strict)
    if instrument is None:
        raise QualityError(f"{instrument_id} : instrument inconnu à {utc_text(as_of)}")
    scores: dict[str, float | None] = dict.fromkeys(QUALITY_COLUMNS)
    found: dict[str, object] = {"mic": instrument.mic, "window_sessions": window_sessions}
    not_evaluated: dict[str, str] = {}

    def report() -> QualityReport:
        details = QualityDetails.model_validate({**found, "not_evaluated": not_evaluated})
        return QualityReport(
            instrument_id=instrument_id, as_of=as_of, strict=strict, details=details, **scores
        )

    received = [ts.date() for ts in store.closes(instrument_id, as_of=as_of, strict=strict).index]
    if not received:
        not_evaluated.update(dict.fromkeys(QUALITY_COLUMNS, "aucun cours visible à cette date"))
        return report()
    found["last_received"] = received[-1]

    day = local_date(as_of)  # Paris, as everywhere else
    first_year = (day - timedelta(days=2 * window_sessions + 30)).year
    calendar = exchange_calendar(instrument.mic, first_year, day.year + 1)
    if calendar is None:
        reason = f"calendrier inconnu pour la place {instrument.mic}"
        not_evaluated.update(gaps=reason, freshness=reason)
        start = received[-window_sessions:][0]  # the last closes received stand for the window
    else:
        closed = _closed_sessions(calendar, as_of, window_sessions)
        start = closed[0]
        found.update(window_start=start, last_closed=closed[-1])
        _check_gaps(received, closed, scores, found, not_evaluated)
        _check_freshness(received[-1], closed, settings, scores, found, not_evaluated)

    try:
        adjusted = store.closes(
            instrument_id, as_of=as_of, start=start, adjust="total_return", strict=strict
        )
    except AdjustmentError as error:  # a dividend at or above the previous close
        found["adjustment_error"] = str(error)
        adjusted = store.closes(
            instrument_id, as_of=as_of, start=start, adjust="split", strict=strict
        )
    returns: list[Return] = [
        (a.date(), b.date(), math.log(adjusted[b] / adjusted[a]))
        for a, b in pairwise(adjusted.index)
    ]
    found["returns"] = len(returns)
    splits = [
        a.ex_date
        for a in store.corporate_actions(instrument_id, as_of=as_of, strict=strict)
        if a.kind == "split"
    ]
    _check_moves(returns, splits, settings, scores, found, not_evaluated)
    _check_outliers(returns, settings, scores, found, not_evaluated)
    return report()


def _check_gaps(
    received: list[date],
    closed: list[date],
    scores: dict[str, float | None],
    found: dict[str, object],
    not_evaluated: dict[str, str],
) -> None:
    in_window = [d for d in received if d >= closed[0]]
    closed_set, received_set = set(closed), set(in_window)
    settled = [d for d in in_window if d in closed_set]
    if not settled:
        not_evaluated["gaps"] = "aucun cours dans la fenêtre"
        return
    # From the first close received: a short history is not a gap.
    expected = [s for s in closed if settled[0] <= s <= settled[-1]]
    missing = [s for s in expected if s not in received_set]
    unexpected = [d for d in in_window if d not in closed_set]
    found.update(expected_sessions=len(expected), missing=missing, unexpected=unexpected)
    scores["gaps"] = max(0.0, 1 - (len(missing) + len(unexpected)) / len(expected))


def _check_freshness(
    last_received: date,
    closed: list[date],
    settings: DataQuality,
    scores: dict[str, float | None],
    found: dict[str, object],
    not_evaluated: dict[str, str],
) -> None:
    stale = sum(1 for s in closed if s > last_received)
    found["stale_sessions"] = stale
    limit = _cut_off(settings, "max_staleness_sessions")
    if isinstance(limit, str):
        not_evaluated["freshness"] = limit
        return
    scores["freshness"] = 1.0 if stale <= limit else 0.0


def _check_moves(
    returns: list[Return],
    splits: list[date],
    settings: DataQuality,
    scores: dict[str, float | None],
    found: dict[str, object],
    not_evaluated: dict[str, str],
) -> None:
    limit = _cut_off(settings, "max_unexplained_move")
    if isinstance(limit, str):
        not_evaluated["corporate_actions"] = limit
        return
    if not returns:
        not_evaluated["corporate_actions"] = "moins de deux cours dans la fenêtre"
        return
    cut = math.log1p(limit)
    moves = [
        Move(
            session=session,
            log_return=value,
            declared_split=any(before < ex <= session for ex in splits),
        )
        for before, session, value in returns
        if abs(value) >= cut
    ]
    found["moves"] = moves
    scores["corporate_actions"] = 0.0 if moves or found.get("adjustment_error") else 1.0


def _check_outliers(
    returns: list[Return],
    settings: DataQuality,
    scores: dict[str, float | None],
    found: dict[str, object],
    not_evaluated: dict[str, str],
) -> None:
    limit = _cut_off(settings, "outlier_robust_z")
    if isinstance(limit, str):
        not_evaluated["outliers"] = limit
        return
    if len(returns) < 2:
        not_evaluated["outliers"] = "moins de deux rendements dans la fenêtre"
        return
    values = [v for _, _, v in returns]
    center = median(values)
    mad = median(abs(v - center) for v in values)
    if mad == 0:
        not_evaluated["outliers"] = "MAD nulle : la moitié au moins des rendements sont égaux"
        return
    outliers = [
        Outlier(session=session, robust_z=z)
        for _, session, value in returns
        if abs(z := MAD_SCALE * (value - center) / mad) > limit
    ]
    found["outliers"] = outliers
    scores["outliers"] = 1 - len(outliers) / len(values)


def record(store: FinanceStore, report: QualityReport, *, computed_at: datetime) -> bool:
    """Keep a strict assessment: it uses only what was ingested by then, so it never changes."""
    if not report.strict:
        raise ValueError("seul un score « connu à » (strict) s'enregistre")
    if report.as_of > computed_at:
        raise ValueError("un score ne s'enregistre pas pour une date future")
    return store.record_quality(
        report.instrument_id,
        as_of=report.as_of,
        sub_scores=report.sub_scores,
        score=report.score,
        details=report.details.model_dump_json(),
        computed_at=computed_at,
    )
