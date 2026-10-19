"""The synthetic research dataset: reproducible, fictitious, and its traps in place."""

from __future__ import annotations

import csv
import importlib.util
import sys
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from core.finance.fixtures import (
    FIXTURES_SOURCE,
    RESEARCH_DIR,
    RESEARCH_FETCHED_AT,
    PublishedCloses,
    load_research,
    research_costs,
    research_crises,
)
from core.finance.model import CorporateAction, PriceRow
from core.finance.providers import ProviderError
from core.finance.store import FinanceStore, IngestReport

NOW = RESEARCH_FETCHED_AT
TREND, WALKS = "FICT-RTEND", ("FICT-RALEA1", "FICT-RALEA2", "FICT-RALEA3")


def utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


def generator() -> ModuleType:
    """A fresh copy of the generator script, which is not a package module."""
    name = "research_generate"
    spec = importlib.util.spec_from_file_location(name, RESEARCH_DIR / "generate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up while the class is built
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[name]
    return module


Published = dict[tuple[str, date], list[tuple[float, datetime]]]


@pytest.fixture(scope="module")
def published() -> Published:
    """Each (instrument, session) of cours.csv and its rows, in file order."""
    found: Published = defaultdict(list)
    with (RESEARCH_DIR / "cours.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row["identifiant"], date.fromisoformat(row["date"]))
            found[key].append((float(row["cloture"]), datetime.fromisoformat(row["publie_le"])))
    return found


@pytest.fixture(scope="module")
def loaded() -> Iterator[tuple[FinanceStore, list[IngestReport]]]:
    store = FinanceStore.memory()
    reports = load_research(store)
    yield store, reports
    store.close()


@pytest.fixture(scope="module")
def store(loaded: tuple[FinanceStore, list[IngestReport]]) -> FinanceStore:
    return loaded[0]


def last_session(store: FinanceStore, instrument_id: str, as_of: datetime) -> date:
    return store.closes(instrument_id, as_of=as_of).index[-1].date()


# Reproducible and fictitious --------------------------------------------------------------------


def test_committed_files_match_the_generator() -> None:
    for name, text in generator().build().items():
        committed = (RESEARCH_DIR / name).read_text(encoding="utf-8")
        assert committed == text, (
            f"{name} ne correspond plus au générateur : relancer generate.py (une nouvelle "
            "version d'exchange-calendars peut changer les séances)"
        )


def test_every_instrument_is_fictitious(store: FinanceStore) -> None:
    instruments = store.instruments(as_of=NOW)
    assert sorted(i.instrument_id for i in instruments) == sorted([TREND, *WALKS])
    assert all("(fictif)" in i.name and i.isin is None for i in instruments)
    assert {(i.currency, i.mic) for i in instruments} == {("EUR", "XPAR")}


def test_every_record_is_stamped_fixtures(store: FinanceStore) -> None:
    for record_type in (PriceRow, CorporateAction):
        sources = {stored.record.source for stored in store.revisions(record_type, {})}
        assert sources == {FIXTURES_SOURCE}, record_type.__name__


def test_ten_years_of_sessions_and_one_correction_a_year(
    loaded: tuple[FinanceStore, list[IngestReport]], published: Published
) -> None:
    store, reports = loaded
    assert [(r.inserted, r.revised, r.unchanged) for r in reports] == [
        (4, 0, 0),
        (11, 0, 0),
        (4 * 2560, 40, 0),
    ]
    sessions = store.closes(TREND, as_of=NOW).index
    assert (sessions[0].date(), sessions[-1].date()) == (date(2016, 1, 4), date(2025, 12, 31))
    corrected = [key for key, rows in published.items() if len(rows) == 2]
    assert len(corrected) == 40
    assert {(i, d.year) for i, d in corrected} == {
        (i, y) for i in (TREND, *WALKS) for y in range(2016, 2026)
    }


# Publication dates: what a decision at t could see --------------------------------------------


def test_no_close_is_published_before_its_session_closes(published: Published) -> None:
    for (_, session), rows in published.items():
        for _, at in rows:
            # The earliest close is 14:05 in Paris on 24 and 31 December, plus the margin.
            assert at >= datetime.combine(session, datetime.min.time(), tzinfo=UTC) + timedelta(
                hours=14
            )
            assert at <= NOW


def test_a_late_close_is_invisible_at_its_session_and_seen_the_next_morning(
    store: FinanceStore, published: Published
) -> None:
    late = sorted(
        (session, rows[0][1])
        for (instrument_id, session), rows in published.items()
        if instrument_id == TREND and len(rows) == 1 and rows[0][1].date() > session
    )
    assert 0.03 < len(late) / 2560 < 0.07  # 5 % of the closes, by design
    session, at = late[len(late) // 2]
    evening = datetime.combine(session, datetime.min.time(), tzinfo=UTC) + timedelta(hours=21)
    assert last_session(store, TREND, evening) < session  # the cut-off of a decision at t
    assert last_session(store, TREND, at - timedelta(seconds=1)) < session
    assert last_session(store, TREND, at) == session


def test_a_bad_print_is_seen_then_corrected(store: FinanceStore, published: Published) -> None:
    for instrument_id in (TREND, *WALKS):
        session, rows = next(
            (s, rows) for (i, s), rows in sorted(published.items()) if i == instrument_id
            and len(rows) == 2
        )  # fmt: skip
        (bad, printed_at), (good, corrected_at) = rows
        assert bad / good == pytest.approx(1.04, abs=0.006) or bad / good == pytest.approx(
            0.96, abs=0.006
        )
        assert corrected_at.date() > session
        for as_of, expected in ((printed_at, bad), (corrected_at, good), (NOW, good)):
            closes = store.closes(instrument_id, as_of=as_of, start=session, end=session)
            assert closes.tolist() == [expected], (instrument_id, as_of)


def test_the_split_changes_no_close_seen_before_it(store: FinanceStore) -> None:
    def splits(as_of: datetime) -> list[date]:
        actions = store.corporate_actions("FICT-RALEA2", as_of=as_of)
        return [a.ex_date for a in actions if a.kind == "split"]

    before, after = utc(2021, 5, 17, 21, 0), utc(2021, 5, 17, 23, 0)  # 23:00 and 01:00 in Paris
    assert splits(before) == [] and splits(after) == [date(2021, 6, 14)]
    window = {"start": date(2021, 1, 4), "end": date(2021, 6, 11)}
    raw = store.closes("FICT-RALEA2", as_of=NOW, **window)
    for as_of in (before, after, utc(2021, 6, 11, 21, 0)):  # known, but not yet in effect
        seen = store.closes("FICT-RALEA2", as_of=as_of, adjust="split", **window)
        assert seen.equals(raw[raw.index <= seen.index[-1]])
    adjusted = store.closes("FICT-RALEA2", as_of=NOW, adjust="split", **window)
    assert (adjusted * 2).round(6).equals(raw.round(6))


def test_dividends_are_announced_four_weeks_ahead(store: FinanceStore) -> None:
    dividends = [
        a for a in store.corporate_actions("FICT-RALEA1", as_of=NOW) if a.kind == "dividend"
    ]
    assert [a.ex_date.year for a in dividends] == list(range(2016, 2026))
    assert all(a.currency == "EUR" and a.value > 0 for a in dividends)
    assert all(a.published_at.date() <= a.ex_date - timedelta(weeks=4) for a in dividends)


# The planted structure ------------------------------------------------------------------------


def test_every_instrument_falls_at_the_start_of_each_crisis(store: FinanceStore) -> None:
    crises = research_crises()
    for instrument_id in (TREND, *WALKS):
        closes = store.closes(instrument_id, as_of=NOW, adjust="split")
        for window in crises.values():
            assert isinstance(window.start, date)
            during = closes[closes.index.date >= window.start]
            # Five sessions down 25 % together, against a few percent of noise.
            assert during.iloc[5] / closes[closes.index.date < window.start].iloc[-1] < 0.85


def test_the_crises_and_costs_are_declared_fictitious() -> None:
    crises = research_crises()
    assert sorted(crises) == ["crise_fictive_2017", "crise_fictive_2019", "crise_fictive_2024"]
    assert all("fictif" in str(c.source) and "fictive" in c.label for c in crises.values())
    assert crises["crise_fictive_2024"].start == date(2024, 2, 5)
    costs = research_costs()
    assert costs.name == "frais fictifs de démonstration"
    assert costs.costs.commission_pct == Decimal("0.1")
    assert costs.costs.min_commission_eur == Decimal("2")
    assert (costs.costs.slippage_bps, costs.costs.fx_conversion_bps) == (5, 10)


# The provider ---------------------------------------------------------------------------------


def test_published_closes_refuse_a_close_from_the_future(tmp_path: Path) -> None:
    path = tmp_path / "cours.csv"
    header = "date,identifiant,cloture,devise,publie_le\n"
    path.write_text(header + "2026-01-02,FICT-RTEND,50.00,EUR,2026-01-05T08:00:00Z\n")
    with pytest.raises(ProviderError, match="ligne 2 : publié après la récupération"):
        PublishedCloses(path).fetch(fetched_at=NOW)
    path.write_text(header + "2026-01-02,FICT-RTEND,-1,EUR,2026-01-02T17:30:00Z\n")
    with pytest.raises(ProviderError, match="ligne 2"):
        PublishedCloses(path).fetch(fetched_at=NOW)
    path.write_text(header + "2026-01-02,FICT-RTEND,50.00,EUR,2026-01-01T17:30:00Z\n")
    with pytest.raises(ProviderError, match="ligne 2"):  # published before its session
        PublishedCloses(path).fetch(fetched_at=NOW)


def test_published_closes_come_in_publication_order(tmp_path: Path) -> None:
    path = tmp_path / "cours.csv"
    path.write_text(
        "date,identifiant,cloture,devise,publie_le\n"
        "2026-01-02,FICT-RTEND,52.00,EUR,2026-01-02T17:30:00Z\n"
        "2026-01-02,FICT-RTEND,50.00,EUR,2026-01-02T16:30:00Z\n"
    )
    rows = PublishedCloses(path).fetch(fetched_at=NOW)
    assert [r.published_at.hour for r in rows] == [16, 17]
