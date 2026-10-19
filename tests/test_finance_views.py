"""The read views of the finance store, called directly (the MCP servers wrap them)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from core.finance import views
from core.finance.fixtures import REFERENCE_FETCHED_AT, reference_store
from core.finance.store import FinanceStore, FinanceStoreError
from core.finance.views import MAX_INSTRUMENTS, MAX_SESSIONS, ViewError

NOW = datetime(2026, 10, 18, 13, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def empty_store(tmp_path: Path) -> Path:
    path = tmp_path / "finance.db"
    FinanceStore.open(path).close()
    return path


def test_moment_defaults_to_now_and_refuses_the_future() -> None:
    assert views.moment(None, NOW) == NOW
    past = NOW - timedelta(days=400)
    assert views.moment(past, NOW) == past
    assert views.moment(NOW, NOW) == NOW
    with pytest.raises(ViewError, match="futur"):
        views.moment(NOW + timedelta(seconds=1), NOW)


@pytest.mark.parametrize(
    ("environ", "root"),
    [
        ({"CERVEAU_HOME": "C:/cerveau"}, Path("C:/cerveau")),
        ({"CERVEAU_HOME": "  "}, ROOT),
        ({}, ROOT),
    ],
)
def test_the_store_is_the_one_of_cerveau_home(environ: dict[str, str], root: Path) -> None:
    assert views.store_location(environ) == root / "var" / "finance" / "finance.db"


def test_read_store_names_no_stored_value(empty_store: Path) -> None:
    def invalid(_: FinanceStore) -> int:
        return TypeAdapter(int).validate_python("MARQUEUR")

    def broken(_: FinanceStore) -> None:
        raise sqlite3.OperationalError("no such table: MARQUEUR")

    def refused(_: FinanceStore) -> None:
        raise FinanceStoreError("refus explicite")

    with pytest.raises(ViewError) as caught:
        views.read_store(empty_store, invalid)
    assert str(caught.value) == "une donnée de la base ne passe plus ses contrôles à la relecture"
    with pytest.raises(ViewError) as caught:
        views.read_store(empty_store, broken)
    assert str(caught.value) == "base finance illisible"
    with pytest.raises(ViewError, match="refus explicite"):
        views.read_store(empty_store, refused)
    assert views.read_store(empty_store, lambda _: 42) == 42


def test_read_store_opens_read_only(empty_store: Path) -> None:
    def write(store: FinanceStore) -> None:
        store._conn.execute("CREATE TABLE intrus (x)")  # a view that tries to write

    with pytest.raises(ViewError, match="base finance illisible"):
        views.read_store(empty_store, write)


@pytest.mark.parametrize(
    ("ids", "kind", "sessions", "message"),
    [
        (["FICT-ACME"], "fondamentaux", 20, "fondamentaux indisponibles"),
        ([], "cours", 20, f"de 1 à {MAX_INSTRUMENTS} instruments distincts"),
        ([f"FICT-{i:02d}" for i in range(11)], "cours", 20, "instruments distincts"),
        (["FICT-ACME"], "cours", 0, f"de 1 à {MAX_SESSIONS} séances"),
        (["FICT-ACME"], "cours", MAX_SESSIONS + 1, "séances"),
        (["FICT-ACME"], "referentiel", 20, "FICT-ACME : absent du référentiel à cette date"),
    ],
)
def test_market_data_limits(
    empty_store: Path, ids: list[str], kind: views.Kind, sessions: int, message: str
) -> None:
    with FinanceStore.open(empty_store, read_only=True) as store, pytest.raises(ViewError) as e:
        views.market_data(store, ids, kind=kind, as_of=NOW, sessions=sessions)
    assert message in str(e.value)


def test_duplicates_count_once_against_the_limit(empty_store: Path) -> None:
    """Ten distinct ids asked twice pass the limit; the first unknown one then stops the read."""
    ids = [f"FICT-{i:02d}" for i in range(MAX_INSTRUMENTS)] * 2
    with FinanceStore.open(empty_store, read_only=True) as store, pytest.raises(ViewError) as e:
        views.market_data(store, ids, kind="cours", as_of=NOW)
    assert str(e.value) == "FICT-00 : absent du référentiel à cette date"


def test_an_empty_book_is_worth_zero_with_a_warning(empty_store: Path) -> None:
    with FinanceStore.open(empty_store, read_only=True) as store:
        snapshot = views.portfolio_snapshot(store, as_of=NOW)
    assert snapshot.positions == [] and snapshot.cash == []
    assert snapshot.total_eur is not None and snapshot.total_eur.value == 0.0
    assert snapshot.missing == [] and snapshot.reconciliation == []
    assert snapshot.alert is None
    assert snapshot.warnings == [
        "aucune transaction connue à cette date (import : `cerveau portfolio import`)"
    ]


# Quality gate (D12; plan of phase 2, §3) --------------------------------------------------------

WEAK_AT = datetime(2026, 10, 18, 12, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def weak_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The reference store, plus a later weak score of FICT-ACME computed five minutes after."""
    path = reference_store(tmp_path_factory.mktemp("finance") / "finance.db")
    with FinanceStore.open(path) as db:
        db.record_quality(
            "FICT-ACME",
            as_of=WEAK_AT,
            sub_scores={"gaps": 1.0, "corporate_actions": 1.0, "outliers": 0.62, "freshness": 1.0},
            score=0.62,
            details='{"stale_sessions": 0, "not_evaluated": {}}',
            computed_at=WEAK_AT + timedelta(minutes=5),
        )
    return path


def gate(
    path: Path, ids: list[str], at: datetime, *, strict: bool = False, threshold: float = 0.9
) -> views.QualityCheck:
    with FinanceStore.open(path, read_only=True) as db:
        return views.quality_check(db, ids, as_of=at, strict=strict, threshold=threshold)


def test_a_weak_score_is_shown_and_caps_the_decision_at_n1(weak_store: Path) -> None:
    check = gate(weak_store, ["FICT-ACME", "FICT-BOREAL"], NOW)
    assert (check.gate, check.decision_cap, check.below) == ("insuffisante", "N1", ["FICT-ACME"])
    acme, boreal = check.series
    assert acme.score is not None and acme.score.display == "0,620"
    assert acme.assessed_at == WEAK_AT
    assert boreal.score is not None and boreal.score.display == "0,992"
    assert check.note == (
        "qualité des données insuffisante : FICT-ACME score 0,620 sous le seuil 0,900 (D12) ; "
        "toute décision reste plafonnée à N1"
    )


def test_a_score_counts_from_its_date_and_in_a_replay_once_computed(weak_store: Path) -> None:
    assert gate(weak_store, ["FICT-ACME"], WEAK_AT - timedelta(seconds=1)).gate == "suffisante"
    between = WEAK_AT + timedelta(minutes=1)  # after the score's date, before its computation
    assert gate(weak_store, ["FICT-ACME"], between).gate == "insuffisante"
    assert gate(weak_store, ["FICT-ACME"], between, strict=True).gate == "suffisante"  # R10


def test_a_series_without_a_complete_score_is_not_evaluable(weak_store: Path) -> None:
    # No score before the first sync; empty scores from 12:00:02 (no close was visible yet).
    for at in (REFERENCE_FETCHED_AT, REFERENCE_FETCHED_AT + timedelta(seconds=5)):
        check = gate(weak_store, ["FICT-BOREAL"], at)
        assert (check.gate, check.decision_cap) == ("non_evaluable", "N1")
        assert check.not_evaluated == ["FICT-BOREAL"]
        assert check.note is not None
        assert "aucun score complet enregistré à cette date pour FICT-BOREAL" in check.note


def test_a_weak_score_outranks_a_missing_one(weak_store: Path) -> None:
    check = gate(weak_store, ["FICT-ACME", "FICT-ABSENT", "FICT-ACME"], NOW)
    assert (check.gate, check.below, check.not_evaluated) == (
        "insuffisante",
        ["FICT-ACME"],
        ["FICT-ABSENT"],
    )
    assert len(check.series) == 2  # a duplicate counts once
    assert check.note is not None
    assert "FICT-ACME score 0,620 sous le seuil 0,900" in check.note
    assert "aucun score complet enregistré à cette date pour FICT-ABSENT" in check.note
