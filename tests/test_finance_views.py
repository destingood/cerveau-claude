"""The read views of the finance store, called directly (the MCP servers wrap them)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from core.finance import views
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
