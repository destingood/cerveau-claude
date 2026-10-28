"""What a strategy may read at its decision date: the point-in-time view (R10, ADR-026).

A backtest reads the store once (MarketHistory), then hands the strategy, at each decision date
t, a PointInTimeView: the closes published before the cut-off of t (``config/research.yaml`` ›
``execution.decision_cutoff_utc``) and on a session up to t, each in its last revision known then,
adjusted with the corporate actions known then. It filters in memory what FinanceStore.closes
filters in SQL, and gives the same series to the last bit (tested). A request beyond t raises
LookAheadError: the backtest stops and the protocol fails (R10).

The view guards the honest path only: Python cannot stop a strategy from reaching into private
attributes. The truncation check of the protocol catches that, by recomputing decisions on a
history physically cut at t (``MarketHistory.cut``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

import numpy as np
import pandas as pd

from core.finance.adjust import Adjustment, adjustment_factors
from core.finance.model import CorporateAction, PriceRow
from core.finance.store import FinanceStore, Stored


class LookAheadError(Exception):
    """A strategy asked for data after its decision date (R10): the backtest fails."""


def decision_time(day: date, cutoff: time) -> datetime:
    """The moment of a decision at ``day``: its cut-off, read as UTC."""
    return datetime.combine(day, cutoff, tzinfo=UTC)


def _instant(moment: datetime) -> np.datetime64:
    if moment.tzinfo is None:
        raise ValueError("instant sans fuseau horaire")
    return np.datetime64(moment.astimezone(UTC).replace(tzinfo=None), "us")


def _session(day: date) -> np.datetime64:
    return np.datetime64(day, "D")


def _series(name: str, sessions: np.ndarray, values: np.ndarray) -> pd.Series:
    return pd.Series(values, index=pd.DatetimeIndex(sessions), name=name, dtype=float)


@dataclass(frozen=True)
class _Closes:
    """Every revision of one instrument's closes, sorted by session then revision."""

    sessions: np.ndarray  # datetime64[D]
    published: np.ndarray  # datetime64[us], UTC
    values: np.ndarray  # float64
    currencies: frozenset[str]

    def kept(self, mask: np.ndarray) -> _Closes:
        return _Closes(
            self.sessions[mask], self.published[mask], self.values[mask], self.currencies
        )


@dataclass(frozen=True)
class Publications:
    """How one instrument's closes reached the store over a window: what the view guards."""

    sessions: int  # sessions with a close
    corrected: int  # sessions published more than once
    late: int  # sessions first published after the decision cut-off of their own session
    actions: int  # corporate actions with an ex-date in the window


@dataclass(frozen=True)
class CorporateEvent:
    """A corporate action as the engine books it: its last revision, first announced when."""

    action: CorporateAction
    announced: datetime


class MarketHistory:
    """Every revision of a universe's closes and corporate actions, read once from the store.

    Reads are non-strict (``published_at`` only), as FinanceStore.closes by default: a backtest
    asks what was published at t, not when CERVEAU happened to ingest it.
    """

    def __init__(
        self,
        closes: Mapping[str, _Closes],
        actions: Mapping[str, Sequence[Stored[CorporateAction]]],
    ) -> None:
        if not closes:
            raise ValueError("univers vide")
        self._closes = dict(sorted(closes.items()))
        self._actions = {
            i: tuple((s, _instant(s.record.published_at)) for s in actions.get(i, ()))
            for i in self._closes
        }

    @classmethod
    def load(cls, store: FinanceStore, instrument_ids: Iterable[str]) -> MarketHistory:
        closes: dict[str, _Closes] = {}
        actions: dict[str, Sequence[Stored[CorporateAction]]] = {}
        for instrument_id in sorted(set(instrument_ids)):
            rows = store.revisions(PriceRow, {"instrument_id": instrument_id})
            if not rows:
                raise ValueError(f"{instrument_id} : aucun cours dans la base")
            closes[instrument_id] = _Closes(
                np.array([r.record.session for r in rows], dtype="datetime64[D]"),
                np.array([_instant(r.record.published_at) for r in rows], dtype="datetime64[us]"),
                np.array([r.record.close for r in rows], dtype=float),
                frozenset(r.record.currency for r in rows),
            )
            actions[instrument_id] = store.revisions(
                CorporateAction, {"instrument_id": instrument_id}
            )
        return cls(closes, actions)

    @property
    def instruments(self) -> tuple[str, ...]:
        return tuple(self._closes)

    def currencies(self, instrument_id: str) -> frozenset[str]:
        """The currencies of the closes and of the dividends: the engines accept EUR only."""
        found = set(self._series(instrument_id).currencies)
        found.update(
            s.record.currency for s, _ in self._actions[instrument_id] if s.record.currency
        )
        return frozenset(found)

    def view(self, day: date, cutoff: time) -> PointInTimeView:
        return PointInTimeView(self, day, decision_time(day, cutoff))

    def cut(self, day: date, cutoff: time) -> MarketHistory:
        """The history as it stood at the decision of ``day``: every later row is gone."""
        return self.known_by(decision_time(day, cutoff), day)

    def known_by(self, at: datetime, day: date) -> MarketHistory:
        """Sessions up to ``day`` as published by ``at``, and the actions announced by then."""
        moment, last = _instant(at), _session(day)
        closes = {
            i: c.kept((c.published <= moment) & (c.sessions <= last))
            for i, c in self._closes.items()
        }
        actions = {i: [s for s, at in found if at <= moment] for i, found in self._actions.items()}
        return MarketHistory(closes, actions)

    def final_closes(self, instrument_id: str) -> pd.Series:
        """Each session in its last revision: what the market did, as far as the store knows.

        The engines value positions and fill orders at these closes; a decision never sees them
        before its view does.
        """
        sessions, values = self.known(instrument_id, moment=None, day=None)
        return _series(instrument_id, sessions, values)

    def events(self, instrument_id: str) -> list[CorporateEvent]:
        """Each corporate action in its last revision, with the moment it was first announced."""
        first: dict[tuple[date, str], datetime] = {}
        for stored, _ in self._actions[instrument_id]:
            key = (stored.record.ex_date, stored.record.kind)
            first[key] = min(first.get(key, stored.record.published_at), stored.record.published_at)
        return [
            CorporateEvent(action, first[(action.ex_date, action.kind)])
            for action in self.actions(instrument_id, moment=None)
        ]

    def known(
        self, instrument_id: str, *, moment: np.datetime64 | None, day: np.datetime64 | None
    ) -> tuple[np.ndarray, np.ndarray]:
        """Sessions up to ``day`` and their closes published by ``moment``, last revision each."""
        closes = self._series(instrument_id)
        end = len(closes.sessions)
        if day is not None:
            end = int(np.searchsorted(closes.sessions, day, side="right"))
        sessions, values = closes.sessions[:end], closes.values[:end]
        if moment is not None:
            visible = closes.published[:end] <= moment
            sessions, values = sessions[visible], values[visible]
        # Rows run by session then revision: the last row of a session is its latest revision.
        latest = np.ones(len(sessions), dtype=bool)
        latest[:-1] = sessions[1:] != sessions[:-1]
        return sessions[latest], values[latest]

    def actions(self, instrument_id: str, *, moment: np.datetime64 | None) -> list[CorporateAction]:
        """Corporate actions published by ``moment``, last revision each, by ex-date then kind."""
        self._series(instrument_id)
        latest: dict[tuple[date, str], Stored[CorporateAction]] = {}
        for stored, published in self._actions[instrument_id]:
            if moment is not None and published > moment:
                continue
            key = (stored.record.ex_date, stored.record.kind)
            if key not in latest or stored.revision > latest[key].revision:
                latest[key] = stored
        return [latest[key].record for key in sorted(latest)]

    def publications(
        self, instrument_id: str, *, start: date, end: date, cutoff: time
    ) -> Publications:
        """Sessions, corrections, late first prints and corporate actions on [start, end]."""
        closes = self._series(instrument_id)
        inside = (closes.sessions >= _session(start)) & (closes.sessions <= _session(end))
        sessions, published = closes.sessions[inside], closes.published[inside]
        days, first, counts = np.unique(sessions, return_index=True, return_counts=True)
        if not len(days):
            return Publications(0, 0, 0, 0)
        earliest = np.minimum.reduceat(published, first)
        offset = np.timedelta64(cutoff.hour * 3600 + cutoff.minute * 60 + cutoff.second, "s")
        deadline = days.astype("datetime64[us]") + offset
        actions = self.actions(instrument_id, moment=None)
        return Publications(
            sessions=len(days),
            corrected=int(np.count_nonzero(counts > 1)),
            late=int(np.count_nonzero(earliest > deadline)),
            actions=sum(1 for a in actions if start <= a.ex_date <= end),
        )

    def _series(self, instrument_id: str) -> _Closes:
        try:
            return self._closes[instrument_id]
        except KeyError:
            raise ValueError(f"{instrument_id} n'est pas dans l'univers du backtest") from None


class PointInTimeView:
    """The data of a decision at ``day``: no row published after its cut-off, no later session."""

    __slots__ = ("_day", "_history", "_known_at")

    def __init__(self, history: MarketHistory, day: date, known_at: datetime) -> None:
        if known_at < datetime.combine(day, time(), tzinfo=UTC):
            raise ValueError("une décision ne peut pas précéder sa journée")
        self._history, self._day, self._known_at = history, day, known_at

    @property
    def day(self) -> date:
        return self._day

    @property
    def known_at(self) -> datetime:
        return self._known_at

    @property
    def instruments(self) -> tuple[str, ...]:
        return self._history.instruments

    def closes(
        self,
        instrument_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
        adjust: Adjustment = "none",
    ) -> pd.Series:
        """Closes known at the decision, adjusted with the actions known then.

        The same series as ``FinanceStore.closes(as_of=known_at)``: the whole known series is
        adjusted first, then cut to [start, end].
        """
        self._guard(start, end)
        sessions, values = self.values(instrument_id, adjust=adjust)
        kept = np.ones(len(sessions), dtype=bool)
        if start is not None:
            kept &= sessions >= _session(start)
        if end is not None:
            kept &= sessions <= _session(end)
        return _series(instrument_id, sessions[kept], values[kept])

    def values(
        self, instrument_id: str, *, adjust: Adjustment = "none"
    ) -> tuple[np.ndarray, np.ndarray]:
        """The whole series of ``closes`` as two fresh arrays: sessions (datetime64[D]), values.

        No Series is built: a strategy replayed at every session (``weights_frame``) spends most
        of its time there otherwise.
        """
        moment = _instant(self._known_at)
        sessions, values = self._history.known(
            instrument_id, moment=moment, day=_session(self._day)
        )
        if adjust != "none":
            actions = self._history.actions(instrument_id, moment=moment)
            values = values * adjustment_factors(sessions, values, actions, adjust)
        return sessions, values

    def corporate_actions(self, instrument_id: str) -> list[CorporateAction]:
        return self._history.actions(instrument_id, moment=_instant(self._known_at))

    def last_close(self, instrument_id: str) -> tuple[date, float] | None:
        """The last raw close known at the decision, with its session; None before the first."""
        sessions, values = self._history.known(
            instrument_id, moment=_instant(self._known_at), day=_session(self._day)
        )
        if not len(sessions):
            return None
        return sessions[-1].item(), float(values[-1])

    def _guard(self, *bounds: date | None) -> None:
        for bound in bounds:
            if bound is not None and bound > self._day:
                raise LookAheadError(
                    f"lecture du {bound:%d/%m/%Y} demandée par une décision du "
                    f"{self._day:%d/%m/%Y} : donnée postérieure à la décision (R10)"
                )
