"""Performance (F9, ADR-020): valuation days, history, measures, attribution and the report."""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from skfolio import measures as sk

from core.config.loader import load_config
from core.finance import performance as pf
from core.finance.fixtures import REFERENCE_READ_AT, reference_store
from core.finance.model import Instrument, PriceRow, RateObservation
from core.finance.performance_report import NOTICE, performance_report
from core.finance.portfolio import build_book, effective_ledger, import_transactions, value
from core.finance.store import FinanceStore
from core.finance.views import ViewError
from core.verification.figures import figures_in

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(REPO_ROOT / "config")
NOW = datetime(2026, 1, 12, 20, tzinfo=UTC)
HEADER = "date,compte,type,identifiant,quantite,prix,devise,frais,montant,libelle"
# Monday 5 to Friday 9 January 2026, worked out by hand in test_values_and_returns_by_hand.
LEDGER = (
    "2026-01-05,PEA,depot,,10000.00,,EUR,,,",
    "2026-01-05,PEA,achat,FICT-ACME,10,100,EUR,5,,",
    "2026-01-07,PEA,depot,,1000.00,,EUR,,,",
    "2026-01-08,PEA,vente,FICT-ACME,5,120,EUR,5,,",
    "2026-01-09,PEA,dividende,FICT-ACME,10.00,,EUR,,,",
)
CLOSES = {5: 100.0, 6: 110.0, 7: 120.0, 8: 120.0, 9: 130.0, 12: 130.0}


def utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


def acme() -> Instrument:
    return Instrument.model_validate(
        {
            "instrument_id": "FICT-ACME",
            "valid_from": date(2020, 1, 1),
            "name": "ACME (fictif)",
            "asset_class": "equity",
            "currency": "EUR",
            "mic": "XPAR",
            "sector": "Industrie",
            "country": "FR",
        }
    )


def small_store(
    tmp_path: Path, *lines: str, closes: dict[int, float] | None = None
) -> FinanceStore:
    store = FinanceStore.memory()
    store.add_instruments([acme()], recorded_at=utc(2020, 1, 1))
    store.ingest(
        [
            PriceRow(
                instrument_id="FICT-ACME",
                session=date(2026, 1, day),
                close=close,
                currency="EUR",
                source="fixtures",
                published_at=utc(2026, 1, day, 17),
            )
            for day, close in (CLOSES if closes is None else closes).items()
        ],
        ingested_at=NOW,
    )
    path = tmp_path / "operations.csv"
    path.write_text("\n".join((HEADER, *lines)) + "\n", encoding="utf-8")
    import_transactions(store, path, "cerveau", imported_at=NOW)
    return store


@pytest.fixture
def store(tmp_path: Path) -> Iterator[FinanceStore]:
    s = small_store(tmp_path, *LEDGER)
    yield s
    s.close()


@pytest.fixture(scope="module")
def reference(tmp_path_factory: pytest.TempPathFactory) -> Iterator[FinanceStore]:
    path = reference_store(tmp_path_factory.mktemp("finance") / "finance.db")
    with FinanceStore.open(path, read_only=True) as db:
        yield db


@pytest.fixture(scope="module")
def reference_history(reference: FinanceStore) -> pf.History:
    return pf.history(reference, as_of=REFERENCE_READ_AT)


# Valuation days -------------------------------------------------------------------------------


def test_valuation_days_are_target_days_with_the_given_ends() -> None:
    # Friday 1 May is a TARGET holiday; Sunday 10 May replaces Friday 8 May.
    assert pf.valuation_days(date(2026, 4, 30), date(2026, 5, 10)) == [
        date(2026, 4, 30),
        date(2026, 5, 4),
        date(2026, 5, 5),
        date(2026, 5, 6),
        date(2026, 5, 7),
        date(2026, 5, 10),
    ]
    assert pf.valuation_days(date(2026, 1, 3), date(2026, 1, 4)) == [
        date(2026, 1, 3),
        date(2026, 1, 4),
    ]
    assert pf.valuation_days(date(2026, 1, 9), date(2026, 1, 12)) == [
        date(2026, 1, 9),
        date(2026, 1, 12),
    ]
    with pytest.raises(ValueError, match="doit suivre"):
        pf.valuation_days(date(2026, 1, 9), date(2026, 1, 9))


@given(start=st.dates(date(2024, 1, 1), date(2026, 12, 31)), length=st.integers(1, 60))
def test_valuation_days_are_increasing_and_never_hold_two_weekend_ends(
    start: date, length: int
) -> None:
    end = start + timedelta(days=length)
    days = pf.valuation_days(start, end)
    assert days[0] == start and days[-1] == end
    assert all(a < b for a, b in itertools.pairwise(days))
    inner = days[1:-1]
    assert all(d.weekday() < 5 for d in inner)


# History on a ledger worked out by hand ----------------------------------------------------------


def test_values_and_returns_by_hand(store: FinanceStore) -> None:
    found = pf.history(store, as_of=NOW, end=date(2026, 1, 9))
    assert found.days == [date(2026, 1, d) for d in (5, 6, 7, 8, 9)]
    # 5 Jan: 8 995 € cash + 10 × 100; 6: 10 × 110; 7: +1 000 € deposit, 10 × 120;
    # 8: sale of 5 at 120 less 5 € of fees; 9: 10 € of dividend, 5 × 130.
    assert found.values == [9995.0, 10095.0, 11195.0, 11190.0, 11250.0]
    assert found.flows == [0.0, 1000.0, 0.0, 0.0]
    assert found.returns == pytest.approx(
        [100 / 9995, 100 / 10095, -5 / 11195, 60 / 11190], rel=1e-15
    )
    sale, dividend = found.intervals[2], found.intervals[3]
    assert sale.pnl == {"FICT-ACME": -5.0, "liquidites-EUR": 0.0}
    assert dividend.pnl == {"FICT-ACME": 60.0, "liquidites-EUR": 0.0}
    assert dividend.income == {"FICT-ACME": 10.0}
    assert found.currencies == {"FICT-ACME": "EUR", "liquidites-EUR": "EUR"}


def test_a_weekend_end_replaces_the_last_target_day(store: FinanceStore) -> None:
    found = pf.history(store, as_of=NOW, start=date(2026, 1, 8), end=date(2026, 1, 11))
    assert found.days == [date(2026, 1, 8), date(2026, 1, 11)]
    assert found.values == [11190.0, 11250.0]


def test_the_default_period_runs_from_the_first_trade_to_the_reading_date(
    store: FinanceStore,
) -> None:
    found = pf.history(store, as_of=NOW)
    assert (found.start, found.end) == (date(2026, 1, 5), date(2026, 1, 12))
    assert found.values[-1] == 11250.0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"end": date(2026, 1, 13)}, "après la date de lecture"),
        ({"start": date(2026, 1, 9), "end": date(2026, 1, 9)}, "doit précéder"),
        ({"start": date(2026, 1, 2), "end": date(2026, 1, 9)}, "au plus tôt le 05/01/2026"),
        ({"end": date(2026, 1, 2)}, "aucune transaction"),
    ],
)
def test_history_refusals(store: FinanceStore, kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ViewError, match=message):
        pf.history(store, as_of=NOW, **kwargs)


def test_an_unknown_value_refuses_the_whole_period(tmp_path: Path) -> None:
    late = {day: close for day, close in CLOSES.items() if day >= 6}
    with (
        small_store(tmp_path, *LEDGER, closes=late) as db,
        pytest.raises(
            ViewError, match=r"FICT-ACME : valeur inconnue le 05/01/2026 ; pas de performance"
        ),
    ):
        pf.history(db, as_of=NOW)


def test_an_emptied_book_has_no_return_afterwards(tmp_path: Path) -> None:
    lines = ("2026-01-05,PEA,depot,,1000.00,,EUR,,,", "2026-01-06,PEA,retrait,,1000.00,,EUR,,,")
    with (
        small_store(tmp_path, *lines) as db,
        pytest.raises(ViewError, match="valeur nulle ou négative à la fin du 06/01/2026"),
    ):
        pf.history(db, as_of=NOW, end=date(2026, 1, 7))


# History on the reference portfolio --------------------------------------------------------------


def test_each_daily_value_is_the_snapshot_value(
    reference: FinanceStore, reference_history: pf.History
) -> None:
    traded = {
        b.transaction.trade_date for b in effective_ledger(reference, as_of=REFERENCE_READ_AT)
    }
    days = reference_history.days
    checked = sorted({d for d in days if d in traded} | set(days[::97]) | {days[-1]})
    values = dict(zip(days, reference_history.values, strict=True))
    for day in checked:
        book = build_book(reference, as_of=REFERENCE_READ_AT, day=day)
        assert value(reference, book).total_eur == values[day], day


def test_the_line_profits_add_up_to_each_day_profit(reference_history: pf.History) -> None:
    for previous, interval in zip(
        reference_history.values, reference_history.intervals, strict=False
    ):
        profit = interval.profit(previous)
        assert math.fsum(interval.pnl.values()) == pytest.approx(profit, abs=1e-9 * previous)


def test_twr_equals_the_unit_value_method(reference_history: pf.History) -> None:
    # Independent: units bought or sold at the end-of-day unit value, which starts at 1.
    units = reference_history.base_eur
    unit_value = 1.0
    for interval in reference_history.intervals:
        unit_value = (interval.value_eur - interval.flow_eur) / units
        units += interval.flow_eur / unit_value
    assert pf.chained(reference_history.returns) == pytest.approx(unit_value - 1, rel=1e-12)


def test_contributions_add_up_to_the_twr(reference_history: pf.History) -> None:
    found = pf.contributions(reference_history)
    twr = pf.chained(reference_history.returns)
    assert math.fsum(found.values()) == pytest.approx(twr, abs=1e-12)
    assert found["liquidites-EUR"] == pytest.approx(0.0, abs=1e-15)  # no interest, no fx


# Measures ---------------------------------------------------------------------------------------


returns_lists = st.lists(
    st.floats(-0.2, 0.2, allow_nan=False, allow_subnormal=False), min_size=2, max_size=80
)


@given(returns=returns_lists)
def test_volatility_and_downside_deviation_match_skfolio(returns: list[float]) -> None:
    array = np.array(returns)
    assert pf.sample_std(returns) == pytest.approx(
        float(sk.standard_deviation(array)), rel=1e-9, abs=1e-15
    )
    assert pf.downside_deviation(returns) == pytest.approx(
        float(sk.semi_deviation(array, min_acceptable_return=0.0)), rel=1e-9, abs=1e-15
    )


@given(returns=st.lists(st.floats(-0.2, 0.2, allow_nan=False), min_size=1, max_size=80))
def test_max_drawdown_matches_skfolio(returns: list[float]) -> None:
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(len(returns) + 1)]
    found = pf.max_drawdown(days, returns)
    expected = float(sk.max_drawdown(sk.get_drawdowns(np.array(returns), compounded=True)))
    assert found.depth == pytest.approx(expected, rel=1e-9, abs=1e-12)
    index = dict(zip(days, np.concatenate([[1.0], np.cumprod(1 + np.array(returns))]), strict=True))
    if found.depth > 0:
        assert index[found.trough] / index[found.peak] - 1 == pytest.approx(-found.depth, rel=1e-9)
        assert found.peak < found.trough
        if found.recovery is not None:
            assert index[found.recovery] >= index[found.peak] * (1 - 1e-12)
            between = [d for d in days if found.trough < d < found.recovery]
            assert all(index[d] < index[found.peak] for d in between)


def test_max_drawdown_dates_by_hand() -> None:
    days = [date(2026, 1, d) for d in (5, 6, 7, 8, 9, 12)]
    found = pf.max_drawdown(days, [0.10, -0.20, 0.05, 0.20, -0.01])
    assert found.depth == pytest.approx(0.20)
    assert (found.peak, found.trough, found.recovery) == (days[1], days[2], days[4])
    assert pf.max_drawdown(days[:3], [0.1, 0.1]) == pf.Drawdown(0.0, days[0], days[0], days[0])


@settings(deadline=None)
@given(
    returns=st.lists(st.floats(-0.1, 0.1, allow_nan=False), min_size=1, max_size=40),
    flows=st.lists(st.floats(-0.3, 0.3, allow_nan=False), min_size=40, max_size=40),
)
def test_daily_returns_recover_the_returns_and_the_unit_value(
    returns: list[float], flows: list[float]
) -> None:
    values, external = [1000.0], []
    for r, share in zip(returns, flows, strict=False):
        flow = share * values[-1]
        external.append(flow)
        values.append(values[-1] * (1 + r) + flow)
    assert pf.daily_returns(values, external) == pytest.approx(returns, abs=1e-12)
    expected = math.prod(1 + r for r in returns) - 1
    assert pf.chained(returns) == pytest.approx(expected, rel=1e-12, abs=1e-15)


def test_daily_returns_refuse_a_non_positive_value() -> None:
    with pytest.raises(ValueError, match="rendement non défini"):
        pf.daily_returns([100.0, 0.0, 10.0], [0.0, 10.0])
    with pytest.raises(ValueError, match="une valeur de plus"):
        pf.daily_returns([100.0], [0.0])


def test_annualization_is_act_365() -> None:
    assert pf.annualized(0.21, 730) == pytest.approx(0.1, rel=1e-14)
    assert pf.annualized(0.1, 365) == pytest.approx(0.1, rel=1e-15)


def test_sharpe_and_sortino_by_hand() -> None:
    excess = [0.01, -0.01, 0.02, 0.0]
    mean, std = 0.005, math.sqrt((0.005**2 + 0.015**2 + 0.015**2 + 0.005**2) / 3)
    assert pf.sharpe(excess, 252) == pytest.approx(mean / std * math.sqrt(252), rel=1e-14)
    assert pf.sortino(excess, 252) == pytest.approx(
        mean / math.sqrt(0.01**2 / 3) * math.sqrt(252), rel=1e-14
    )
    assert pf.sharpe([0.01, 0.01], 252) is None
    assert pf.sortino([0.01, 0.02], 252) is None
    assert pf.calmar(0.05, 0.0) is None
    assert pf.calmar(0.05, 0.25) == pytest.approx(0.2)


def test_mwr_closed_forms() -> None:
    start, end = date(2026, 1, 1), date(2027, 1, 1)
    assert pf.mwr(start, 100.0, [], end, 110.0) == pytest.approx(0.10, rel=1e-12)
    # 100 at the start and 100 at mid-period, 231 at the end: (1 + m)·100 + √(1 + m)·100 = 231
    # gives √(1 + m) = 1.1 for a flow exactly halfway.
    middle, later = start + timedelta(days=365), start + timedelta(days=730)
    assert pf.mwr(start, 100.0, [(middle, 100.0)], later, 231.0) == pytest.approx(0.21, rel=1e-12)
    assert pf.mwr(start, 100.0, [], end, 0.0) is None
    with pytest.raises(ValueError, match="doit suivre"):
        pf.mwr(end, 100.0, [], end, 110.0)


@settings(deadline=None)
@given(
    base=st.floats(100, 1e6),
    growth=st.floats(-0.5, 1.0),
    flows=st.lists(
        st.tuples(st.integers(1, 364), st.floats(-0.3, 0.5, allow_nan=False)), max_size=8
    ),
)
def test_the_mwr_cancels_the_present_value(
    base: float, growth: float, flows: list[tuple[int, float]]
) -> None:
    start, end = date(2026, 1, 1), date(2027, 1, 1)
    dated = [(start + timedelta(days=d), share * base) for d, share in flows]
    final = base * (1 + growth) + math.fsum(f for _, f in dated)
    found = pf.mwr(start, base, dated, end, final)
    if found is None:
        return
    y = math.log1p(found)
    npv = -base - math.fsum(f * math.exp(-y * (d - start).days / 365) for d, f in dated)
    npv += final * math.exp(-y)
    scale = base + math.fsum(abs(f) for _, f in dated) + abs(final)
    assert abs(npv) <= 1e-9 * scale


# The risk-free rate -----------------------------------------------------------------------------


def fixings(values: dict[date, float]) -> pd.Series:
    return pd.Series(values, index=pd.DatetimeIndex(list(values)), dtype=float)


def test_the_estr_is_compounded_the_ecb_way() -> None:
    thu, fri, mon = date(2026, 2, 5), date(2026, 2, 6), date(2026, 2, 9)
    found = pf.risk_free_returns([thu, fri, mon], fixings({thu: 2.0, fri: 3.6}))
    assert found is not None and found.carried == []
    # Friday's fixing covers Friday, Saturday and Sunday: simple interest over three days.
    assert found.returns == pytest.approx([2.0 / 36000, 3.6 * 3 / 36000], rel=1e-14)


def test_an_unpublished_fixing_carries_the_last_one_with_a_flag() -> None:
    thu, fri, mon = date(2026, 2, 5), date(2026, 2, 6), date(2026, 2, 9)
    found = pf.risk_free_returns([thu, fri, mon], fixings({thu: 2.0}))
    assert found is not None
    assert found.carried == [fri, fri + timedelta(days=1), fri + timedelta(days=2)]
    assert found.returns == pytest.approx([2.0 / 36000, 2.0 * 3 / 36000], rel=1e-14)
    assert pf.risk_free_returns([thu, fri], fixings({fri: 2.0})) is None
    assert pf.risk_free_returns([thu, fri], fixings({})) is None


# The report -------------------------------------------------------------------------------------


def test_the_report_traces_every_number(reference: FinanceStore) -> None:
    report = performance_report(reference, CONFIG, as_of=REFERENCE_READ_AT)
    found, loose = figures_in(report.model_dump(mode="json"))
    assert loose == []
    ids = [f.id for f in found]
    assert len(ids) == len(set(ids))
    assert report.notice == NOTICE
    assert abs(report.attribution.residual.value) < 1e-12
    assert report.measures.twr_annualized is not None and report.measures.calmar is not None
    assert {u.measure for u in report.unavailable} == {
        "indice_de_reference",
        "attribution_factorielle",
        "attribution_brinson",
    }
    assert any("€STR pas encore publié" in w for w in report.warnings)
    contributions = [line.contribution.value for line in report.attribution.lines]
    assert contributions == sorted(contributions, reverse=True)
    sectors = {s.sector for s in report.attribution.sectors}
    assert {"liquidites", "frais", "Technologie"} <= sectors


def test_the_report_values_on_the_hand_ledger(store: FinanceStore) -> None:
    report = performance_report(store, CONFIG, as_of=NOW, end=date(2026, 1, 9))
    values = report.values
    assert (values.start_eur.value, values.end_eur.value) == (9995.0, 11250.0)
    assert values.net_deposits_eur.value == 1000.0
    assert values.gain_eur.value == 255.0
    assert values.dividends_eur.value == 10.0
    assert values.fees_eur.value == 0.0  # trading fees stay in the security line
    assert report.measures.twr_annualized is None and report.measures.calmar is None
    assert "rendements_annualises" in {u.measure for u in report.unavailable}
    assert "sharpe_sortino" in {u.measure for u in report.unavailable}  # no €STR in this store
    line = report.attribution.lines[0]
    assert (line.line, line.name, line.sector) == ("FICT-ACME", "ACME (fictif)", "Industrie")
    assert line.gain_eur.value == 255.0


def test_the_report_with_the_estr(tmp_path: Path) -> None:
    with small_store(tmp_path, *LEDGER) as db:
        db.ingest(
            [
                RateObservation(
                    series_id="estr",
                    session=date(2026, 1, day),
                    value_pct=1.8,
                    source="fixtures",
                    published_at=utc(2026, 1, day + 1, 8),
                )
                for day in (2, 5, 6, 7, 8)
            ],
            ingested_at=NOW,
        )
        report = performance_report(db, CONFIG, as_of=NOW, end=date(2026, 1, 9))
    assert report.measures.sharpe is not None and report.measures.sortino is not None
    assert report.measures.risk_free is not None
    assert report.measures.risk_free.value == pytest.approx((1 + 1.8 / 36000) ** 4 - 1, rel=1e-12)
    assert report.warnings == []
