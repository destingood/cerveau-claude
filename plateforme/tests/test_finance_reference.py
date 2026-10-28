"""The fictitious reference portfolio: reproducible, fictitious, and its anomalies in place."""

from __future__ import annotations

import importlib.util
import math
import sys
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import pairwise
from types import ModuleType

import httpx
import pytest

from core.finance.fixtures import (
    FIXTURES_SOURCE,
    REFERENCE_DIR,
    REFERENCE_FETCHED_AT,
    REFERENCE_QUALITY,
    REFERENCE_WINDOW,
    ecb_files,
    load_reference,
)
from core.finance.model import CorporateAction, FxRate, PriceRow, RateObservation
from core.finance.portfolio import Book, build_book, import_transactions, reconcile, value
from core.finance.store import FinanceStore
from core.finance.sync import SyncResult

SETTINGS = REFERENCE_QUALITY
WINDOW = REFERENCE_WINDOW
NOW = REFERENCE_FETCHED_AT


def utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


def generator() -> ModuleType:
    """A fresh copy of the generator script, which is not a package module."""
    name = "reference_generate"
    spec = importlib.util.spec_from_file_location(name, REFERENCE_DIR / "generate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up while the class is built
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[name]
    return module


@pytest.fixture(scope="module")
def loaded() -> Iterator[tuple[FinanceStore, list[SyncResult]]]:
    store = FinanceStore.memory()
    results = load_reference(store, quality=SETTINGS, window_sessions=WINDOW)
    yield store, results
    store.close()


@pytest.fixture(scope="module")
def store(loaded: tuple[FinanceStore, list[SyncResult]]) -> FinanceStore:
    return loaded[0]


def log_returns(series: list[float]) -> list[float]:
    return [math.log(b / a) for a, b in pairwise(series)]


def stdev(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


# Reproducible and fictitious --------------------------------------------------------------------


def test_committed_files_match_the_generator() -> None:
    for name, text in generator().build().items():
        committed = (REFERENCE_DIR / name).read_text(encoding="utf-8")
        assert committed == text, (
            f"{name} ne correspond plus au générateur : relancer generate.py (une nouvelle "
            "version d'exchange-calendars peut changer les séances)"
        )


def test_box_muller_draws_look_gaussian() -> None:
    module = generator()
    rng = module._stream("controle")
    draws = [module.normal(rng) for _ in range(20_000)]
    assert abs(sum(draws) / len(draws)) < 0.03
    assert abs(stdev(draws) - 1) < 0.03
    assert generator().normal(module._stream("controle")) == draws[0]


def test_every_instrument_is_fictitious(store: FinanceStore) -> None:
    instruments = store.instruments(as_of=NOW)
    assert len(instruments) == 10
    assert all(i.instrument_id.startswith("FICT-") for i in instruments)
    assert all("(fictif)" in i.name or "(fictive)" in i.name for i in instruments)
    assert all(i.isin is None for i in instruments)  # no code that could name a real security
    assert {i.currency for i in instruments} == {"EUR", "USD", "GBP"}
    assert {i.asset_class for i in instruments} == {"equity", "etf", "bond", "gold"}


def test_every_record_is_stamped_fixtures(store: FinanceStore) -> None:
    for record_type in (PriceRow, CorporateAction, FxRate, RateObservation):
        sources = {stored.record.source for stored in store.revisions(record_type, {})}
        assert sources == {FIXTURES_SOURCE}, record_type.__name__


def test_the_four_syncs_insert_everything_once(
    loaded: tuple[FinanceStore, list[SyncResult]],
) -> None:
    _, results = loaded
    assert [r.report.inserted for r in results] == [10, 34, 7629, 2300]
    assert all(r.report.revised == r.report.unchanged == r.redated == 0 for r in results)
    assert results[3].parameters["stands_for"] == "ecb"
    assert results[3].parameters["observations"] == {"fx_reference_rates": 1534, "estr": 766}


def test_the_ecb_files_are_served_without_network() -> None:
    with httpx.Client(transport=ecb_files(REFERENCE_DIR)) as client:
        assert client.get(
            "https://ecb.fixtures.invalid/service/data/EXR/D.USD.EUR.SP00.A"
        ).is_success
        assert client.get("https://ecb.fixtures.invalid/service/data/YC/B.U2").status_code == 404
        assert client.get("https://ecb.fixtures.invalid/service/").status_code == 404


# The anomalies --------------------------------------------------------------------------------


def test_the_split_is_absorbed_by_the_adjustment(store: FinanceStore) -> None:
    window = {"as_of": NOW, "start": date(2025, 6, 13), "end": date(2025, 6, 16)}
    raw = store.closes("FICT-ACME", **window).tolist()
    adjusted = store.closes("FICT-ACME", adjust="split", **window).tolist()
    assert raw[1] / raw[0] == pytest.approx(0.5, abs=0.05)
    assert abs(math.log(adjusted[1] / adjusted[0])) < 0.1


def test_the_split_is_known_from_the_end_of_its_announcement_day(store: FinanceStore) -> None:
    def splits(as_of: datetime) -> list[date]:
        actions = store.corporate_actions("FICT-ACME", as_of=as_of)
        return [a.ex_date for a in actions if a.kind == "split"]

    assert splits(utc(2025, 5, 20, 21, 0)) == []  # 23:00 in Paris on the announcement day
    assert splits(utc(2025, 5, 20, 23, 0)) == [date(2025, 6, 16)]  # end of day plus the margin


def test_dividends_in_three_currencies(store: FinanceStore) -> None:
    dividends = {
        instrument_id: [
            a for a in store.corporate_actions(instrument_id, as_of=NOW) if a.kind == "dividend"
        ]
        for instrument_id in ("FICT-GLOBEX", "FICT-HELIOS", "FICT-BOREAL")
    }
    assert [len(d) for d in dividends.values()] == [12, 6, 3]
    assert {a.currency for d in dividends.values() for a in d} == {"USD", "GBP", "EUR"}
    # Without an announcement date, a dividend is known at 00:00 in Paris on its ex-date.
    before = store.corporate_actions("FICT-BOREAL", as_of=utc(2026, 4, 22, 21, 0))
    assert date(2026, 4, 23) not in {a.ex_date for a in before}
    after = store.corporate_actions("FICT-BOREAL", as_of=utc(2026, 4, 22, 23, 0))
    assert date(2026, 4, 23) in {a.ex_date for a in after}


def test_quality_finds_the_bad_print_and_the_gap(store: FinanceStore) -> None:
    def latest(instrument_id: str) -> dict[str, object]:
        return store.quality_history(instrument_id)[-1]

    boreal, cygne, acme = latest("FICT-BOREAL"), latest("FICT-CYGNE"), latest("FICT-ACME")
    assert '"2025-11-20"' in str(boreal["details"]) and '"2025-11-21"' in str(boreal["details"])
    assert boreal["corporate_actions"] == 1.0  # a 22 % print: an outlier, not a hidden split
    assert cygne["gaps"] == pytest.approx(1 - 1 / WINDOW)
    assert '"missing":["2026-09-16"]' in str(cygne["details"]).replace(" ", "")
    assert acme["corporate_actions"] == 1.0  # the declared split explains the halving


def test_volatility_rises_in_the_last_week(store: FinanceStore) -> None:
    closes = store.closes("FICT-MONDE", as_of=NOW, start=date(2025, 10, 1)).tolist()
    returns = log_returns(closes)
    last_week, before = returns[-4:], returns[-254:-5]
    assert math.sqrt(sum(r * r for r in last_week) / 4) > 2.5 * stdev(before)


def test_the_bond_has_its_duration(store: FinanceStore) -> None:
    bond = store.instrument("FICT-OAT35", as_of=NOW)
    assert bond is not None and bond.asset_class == "bond" and bond.duration == 8.4
    last = store.closes("FICT-OAT35", as_of=NOW).iloc[-1]
    assert 60 < last < 100  # a zero coupon below par


# Point in time --------------------------------------------------------------------------------


def test_a_close_is_known_an_hour_after_its_session_closes(store: FinanceStore) -> None:
    # XPAR closes at 17:30 in Paris (15:30 UTC); XNYS at 16:00 in New York (20:00 UTC).
    assert store.closes("FICT-MONDE", as_of=utc(2026, 10, 16, 16, 29)).index[-1].date() == date(
        2026, 10, 15
    )
    assert store.closes("FICT-MONDE", as_of=utc(2026, 10, 16, 16, 31)).index[-1].date() == date(
        2026, 10, 16
    )
    assert store.closes("FICT-GLOBEX", as_of=utc(2026, 10, 16, 20, 59)).index[-1].date() == date(
        2026, 10, 15
    )


def test_ecb_rates_keep_their_publication_times(store: FinanceStore) -> None:
    # Reference rates: 16:00 in Frankfurt (14:00 UTC) plus the margin.
    assert store.fx_rates("USD", as_of=utc(2026, 10, 16, 14, 59)).index[-1].date() == date(
        2026, 10, 15
    )
    assert store.fx_rates("GBP", as_of=NOW).index[-1].date() == date(2026, 10, 16)
    # €STR: the next TARGET day at 08:00 in Frankfurt; Friday's is not out on Sunday.
    estr = store.rates("estr", as_of=NOW)
    assert estr.index[-1].date() == date(2026, 10, 15)
    early = store.rates("estr", as_of=utc(2026, 10, 16, 6, 59))
    assert early.index[-1].date() == date(2026, 10, 14)
    assert estr.min() > 0 and estr.max() < 5


# The portfolio -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def book() -> Iterator[tuple[FinanceStore, Book]]:
    """A store of its own: the transactions and the statement, on top of the market data."""
    store = FinanceStore.memory()
    load_reference(store, quality=SETTINGS, window_sessions=WINDOW)
    imported = import_transactions(
        store, REFERENCE_DIR / "transactions.csv", "cerveau", imported_at=NOW
    )
    assert (imported.added, imported.warnings) == (54, [])
    reconciled = reconcile(store, REFERENCE_DIR / "releve.csv", at=NOW)
    assert reconciled.gaps == []
    assert {a.account: a.status for a in reconciled.reconciliation} == {
        "CTO-FICTIF": "ok",
        "PEA-FICTIF": "ok",
    }
    yield store, build_book(store, as_of=NOW)
    store.close()


def test_the_statement_reconciles_to_the_cent(book: tuple[FinanceStore, Book]) -> None:
    _, positions = book
    assert positions.day == date(2026, 10, 18)
    quantities = {(h.account, h.instrument_id): h.quantity for h in positions.holdings}
    assert len(quantities) == 10
    assert quantities[("PEA-FICTIF", "FICT-ACME")] == 200  # 100 bought, split 2 for 1
    assert quantities[("CTO-FICTIF", "FICT-GLOBEX")] == 80
    assert positions.cash[("CTO-FICTIF", "USD")] == Decimal("66.35")


def test_the_delta_sale_and_the_globex_basis(book: tuple[FinanceStore, Book]) -> None:
    _, positions = book
    [sale] = positions.realized
    # 200 bought at 38.73 + 4.90 of fees; 40 sold at 26.10 - 4.90; a fifth of the basis leaves.
    assert (sale.proceeds, sale.cost, sale.gain) == (
        Decimal("1039.10"),
        Decimal("1550.18"),
        Decimal("-511.08"),
    )
    basis = {(h.account, h.instrument_id): h.cost for h in positions.holdings}
    assert basis[("PEA-FICTIF", "FICT-DELTA")] == Decimal("6200.72")
    assert basis[("CTO-FICTIF", "FICT-GLOBEX")] == Decimal("8794.00") + Decimal("5324.20")


def test_the_whole_portfolio_has_a_value(book: tuple[FinanceStore, Book]) -> None:
    store, positions = book
    valuation = value(store, positions)
    assert valuation.missing == []
    assert valuation.total_eur is not None and valuation.total_eur > 0
    assert {line.close_date for line in valuation.lines if line.close_date} == {date(2026, 10, 16)}
