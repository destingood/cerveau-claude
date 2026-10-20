"""The append-only trial journal and the fingerprints of a trial (ADR-026, ADR-027, D10)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from core.finance.model import ResearchTrial, canonical_json, params_sha256
from core.finance.performance import sharpe
from core.finance.research import trials
from core.finance.research.strategy import Params, Weights
from core.finance.research.view import PointInTimeView
from core.finance.schema import LATEST_VERSION, MIGRATIONS, migrate, schema_version
from core.finance.store import FinanceStore, FinanceStoreError

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
HASH = "a" * 64


def curve(*values: float, start: str = "2024-01-02") -> pd.Series:
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), name="valeur")


def a_trial(**changes: Any) -> ResearchTrial:
    params = changes.pop("params", {"lookback": 20, "share": 0.5})
    fields: dict[str, Any] = {
        "strategy": "rotation_test",
        "code_sha256": HASH,
        "params": params,
        "params_sha256": params_sha256(params),
        "origin": "criblage",
        "start": date(2024, 1, 2),
        "end": date(2024, 12, 31),
        "sessions": 251,
        "sharpe_daily": 0.05,
        "sharpe_annual": 0.05 * 252**0.5,
        "series_sha256": "b" * 64,
        "costs": "recherche",
        "engine": "vectorbt 1.1.2",
    }
    return ResearchTrial(**(fields | changes))


# The model ------------------------------------------------------------------------------------


def test_canonical_json_sorts_keys_and_refuses_nan() -> None:
    assert canonical_json({"b": 1, "a": "é"}) == '{"a":"é","b":1}'
    assert params_sha256({"b": 1, "a": 2}) == params_sha256({"a": 2, "b": 1})
    with pytest.raises(ValueError, match="JSON"):
        canonical_json({"a": float("nan")})


def test_one_and_one_point_zero_are_different_parameters() -> None:
    # [Hypothèse] reported: a grid written 20 then 20.0 counts two trials.
    assert params_sha256({"lookback": 1}) != params_sha256({"lookback": 1.0})


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"end": date(2024, 1, 2)}, "au moins deux séances"),
        ({"sharpe_daily": None}, "tous deux connus"),
        ({"params_sha256": HASH}, "empreinte des paramètres"),
        ({"source": "audit:12"}, "Copilot"),
        ({"origin": "copilote"}, "Copilot"),
        ({"sharpe_annual": float("inf")}, "finite"),
        ({"sessions": 1}, "greater than or equal"),
        ({"strategy": "Rotation"}, "pattern"),
        ({"params": {"Lookback": 3}}, "pattern"),
        ({"origin": "manuel"}, "criblage"),
    ],
)
def test_an_inconsistent_trial_is_refused(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        a_trial(**changes)


def test_a_copilot_trial_carries_its_audit_entry() -> None:
    assert a_trial(origin="copilote", source="audit:12").source == "audit:12"


# Fingerprints and measures -------------------------------------------------------------------


def test_the_source_print_ignores_windows_line_ends() -> None:
    assert trials.source_sha256("a = 1\r\nb = 2\r\n") == trials.source_sha256("a = 1\nb = 2\n")
    assert trials.source_sha256("a = 1\n") != trials.source_sha256("a = 2\n")


@dataclass
class _Named:
    name: str = "test"

    def decide(self, view: PointInTimeView, params: Params) -> Weights:
        return {}


def test_the_code_print_is_the_strategy_module() -> None:
    printed = trials.strategy_code_sha256(_Named())
    assert printed == trials.source_sha256(Path(__file__).read_text(encoding="utf-8"))


def test_a_strategy_without_a_module_has_no_code_print() -> None:
    orphan = type("Orphan", (), {"name": "orphelin", "__module__": "absent.module"})()
    with pytest.raises(trials.TrialError, match="introuvable"):
        trials.strategy_code_sha256(orphan)


def test_the_series_print_is_exact_to_the_bit() -> None:
    returns = trials.value_returns(curve(100.0, 101.0, 100.5))
    same = trials.value_returns(curve(100.0, 101.0, 100.5))
    nudged = returns.copy()
    nudged.iloc[0] = np.nextafter(nudged.iloc[0], 1.0)
    assert trials.series_sha256(returns) == trials.series_sha256(same)
    assert trials.series_sha256(returns) != trials.series_sha256(nudged)
    shifted = trials.value_returns(curve(100.0, 101.0, 100.5, start="2024-01-03"))
    assert trials.series_sha256(returns) != trials.series_sha256(shifted)


def test_a_trial_measures_its_value_curve() -> None:
    values = curve(100.0, 102.0, 101.0, 103.0, 103.5)
    trial = trials.make_trial(
        strategy="rotation_test",
        code_sha256=HASH,
        params={"lookback": 5},
        origin="criblage",
        values=values,
        sessions_per_year=252,
        costs="recherche",
        engine="moteur interne",
    )
    returns = [102 / 100 - 1, 101 / 102 - 1, 103 / 101 - 1, 103.5 / 103 - 1]
    assert trial.start == date(2024, 1, 2) and trial.end == date(2024, 1, 8)
    assert trial.sessions == 4
    assert trial.sharpe_daily == pytest.approx(sharpe(returns, 1), rel=1e-15)
    assert trial.sharpe_annual == pytest.approx(sharpe(returns, 252), rel=1e-15)
    assert trial.series_sha256 == trials.series_sha256(trials.value_returns(values))


def test_a_flat_curve_has_no_sharpe_and_a_short_one_no_trial() -> None:
    flat = trials.make_trial(
        strategy="rotation_test",
        code_sha256=HASH,
        params={},
        origin="protocole",
        values=curve(100.0, 100.0, 100.0),
        sessions_per_year=252,
        costs="recherche",
        engine="moteur interne",
    )
    assert flat.sharpe_daily is None and flat.sharpe_annual is None
    with pytest.raises(trials.TrialError, match="trois séances"):
        trials.value_returns(curve(100.0, 101.0))


def test_the_risk_free_rate_is_subtracted_day_by_day() -> None:
    values = curve(100.0, 102.0, 101.0, 103.0)
    rate = [0.001, 0.001, 0.002]
    trial = trials.make_trial(
        strategy="rotation_test",
        code_sha256=HASH,
        params={},
        origin="protocole",
        values=values,
        sessions_per_year=252,
        costs="recherche",
        engine="moteur interne",
        risk_free=rate,
    )
    excess = [r - f for r, f in zip(trials.value_returns(values), rate, strict=True)]
    assert trial.sharpe_annual == pytest.approx(sharpe(excess, 252), rel=1e-15)
    with pytest.raises(trials.TrialError, match="taux sans risque"):
        trials.make_trial(
            strategy="rotation_test",
            code_sha256=HASH,
            params={},
            origin="protocole",
            values=values,
            sessions_per_year=252,
            costs="recherche",
            engine="moteur interne",
            risk_free=rate[:2],
        )


# The journal ---------------------------------------------------------------------------------


@pytest.fixture
def store() -> FinanceStore:
    return FinanceStore.memory()


def test_trials_are_appended_and_read_back_in_order(store: FinanceStore) -> None:
    first = a_trial()
    second = a_trial(params={"lookback": 60, "share": 0.99, "flag": True, "mode": "x"})
    other = a_trial(strategy="autre")
    assert store.add_trials([first, second], recorded_at=NOW) == 2
    assert store.add_trials([other], recorded_at=NOW) == 1
    found = store.trials("rotation_test")
    assert [r.trial for r in found] == [first, second]
    assert [r.trial_id for r in found] == [1, 2]
    assert found[0].recorded_at == NOW
    assert store.trial_count("rotation_test") == 2
    assert store.trial_count("autre") == 1
    assert store.trial_count("inconnue") == 0


def test_a_copy_under_another_name_shares_the_family(store: FinanceStore) -> None:
    """Quant review of phase 3, M3: N follows the code, not only the identifier."""
    other = "d" * 64
    store.add_trials(
        [a_trial(), a_trial(strategy="copie"), a_trial(strategy="autre", code_sha256=other)],
        recorded_at=NOW,
    )
    assert [r.trial.strategy for r in store.family("copie")] == ["rotation_test", "copie"]
    assert (store.family_count("rotation_test"), store.trial_count("rotation_test")) == (2, 1)
    assert store.family_count("autre") == 1
    assert store.family_count("nouvelle") == 0
    assert store.family_count("nouvelle", HASH) == 2
    assert [r.trial.strategy for r in store.family("autre", HASH)] == [
        "rotation_test",
        "copie",
        "autre",
    ]


def test_the_same_trial_twice_is_two_trials(store: FinanceStore) -> None:
    # N counts every evaluation (ADR-026): re-running a configuration is not free.
    store.add_trials([a_trial(), a_trial()], recorded_at=NOW)
    assert store.trial_count("rotation_test") == 2


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE research_trials SET sharpe_annual = 9.9 WHERE trial_id = 1",
        "DELETE FROM research_trials WHERE trial_id = 1",
        "DELETE FROM research_trials",
        "REPLACE INTO research_trials SELECT * FROM research_trials WHERE trial_id = 1",
        "INSERT OR REPLACE INTO research_trials SELECT * FROM research_trials WHERE trial_id = 1",
        "INSERT OR IGNORE INTO research_trials SELECT * FROM research_trials WHERE trial_id = 1",
    ],
)
def test_a_recorded_trial_cannot_be_changed(store: FinanceStore, statement: str) -> None:
    store.add_trials([a_trial()], recorded_at=NOW)
    with pytest.raises(sqlite3.IntegrityError, match="research_trials : un essai enregistré"):
        store._conn.execute(statement)
    assert [r.trial for r in store.trials("rotation_test")] == [a_trial()]


def test_a_copilot_entry_is_imported_once(store: FinanceStore) -> None:
    copilot = a_trial(origin="copilote", source="audit:12")
    store.add_trials([copilot], recorded_at=NOW)
    with pytest.raises(sqlite3.IntegrityError, match="ne se remplace pas"):
        store.add_trials([a_trial(), copilot], recorded_at=NOW)
    # The batch is one transaction: the first trial of the refused batch is not kept either.
    assert store.trial_count("rotation_test") == 1


def test_a_read_only_store_records_no_trial(tmp_path: Path) -> None:
    path = tmp_path / "finance.db"
    FinanceStore.open(path).close()
    with (
        FinanceStore.open(path, read_only=True) as reader,
        pytest.raises(FinanceStoreError, match="lecture seule"),
    ):
        reader.add_trials([a_trial()], recorded_at=NOW)


def test_a_schema_2_store_gains_the_trial_journal(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    assert migrate(conn, MIGRATIONS[:2]) == 2
    conn.close()
    with FinanceStore.open(path) as s:
        assert s.schema_version == LATEST_VERSION == 3
        assert s.trial_count("rotation_test") == 0
        s.add_trials([a_trial()], recorded_at=NOW)
    conn = sqlite3.connect(path)
    assert schema_version(conn) == LATEST_VERSION
    conn.close()
