"""The Copilot's backtests: decision day, grid point, journal lookup and replay (ADR-027)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.audit import AuditJournal
from core.config import load_config
from core.finance.fixtures import load_research, research_costs
from core.finance.research.copilot import (
    PLUGIN,
    TOOL,
    CopilotError,
    CopilotRequest,
    backtest,
    copilot_requests,
    copilot_trials,
    decision_day,
    grid_point,
)
from core.finance.research.execution import Costs
from core.finance.research.protocol import ENGINE
from core.finance.research.registry import REGISTRY_DIR, load_registry, load_strategy
from core.finance.research.trials import strategy_code_sha256
from core.finance.research.view import MarketHistory, decision_time
from core.finance.store import FinanceStore

REPO = Path(__file__).resolve().parents[1]
SPEC = load_registry(REPO / REGISTRY_DIR)["croisement_mm"]
STRATEGY = load_strategy(SPEC)
RESEARCH = load_config(REPO / "config").research
NAMED = research_costs()
COSTS = Costs.from_config(NAMED.costs, NAMED.name)
CUTOFF = RESEARCH.execution.decision_cutoff_utc
AT = datetime(2021, 6, 1, 12, 0, tzinfo=UTC)
TS = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
ASKED = {"strategie": "croisement_mm", "mode": "backtest", "params": '{"short": 20, "long": 50}'}


@pytest.fixture(scope="module")
def history() -> Iterator[MarketHistory]:
    with FinanceStore.memory() as store:
        load_research(store)
        yield MarketHistory.load(store, SPEC.univers)


def replay(requests: list[CopilotRequest], history: MarketHistory, **kwargs: Any) -> Any:
    return copilot_trials(
        requests,
        recorded=kwargs.pop("recorded", ()),
        spec=SPEC,
        strategy=STRATEGY,
        history=history,
        research=RESEARCH,
        costs=COSTS,
        initial_cash=100_000.0,
        sessions_per_year=252,
        **kwargs,
    )


def request(source: str = "audit#1 abc", **changes: Any) -> CopilotRequest:
    fields: dict[str, Any] = {
        "source": source,
        "at": AT,
        "params": {"short": 20, "long": 50},
        "start": None,
        "end": None,
    }
    fields.update(changes)
    return CopilotRequest(**fields)


def call(journal: AuditJournal, *, actor: str = "orchestrator", **changes: Any) -> dict[str, Any]:
    """A strategy_lab TOOL_CALL as the MCP adapter journals it (arguments clipped to scalars)."""
    payload: dict[str, Any] = {
        "plugin": PLUGIN,
        "tool": TOOL,
        "action_class": "CALCUL",
        "arguments": dict(ASKED),
        "status": "ok",
        "duration_ms": 1500,
    }
    arguments = changes.pop("arguments", {})
    payload["arguments"].update(arguments)
    payload.update(changes)
    return journal.append(actor=actor, event="TOOL_CALL", payload=payload, now=TS)


@given(
    st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1)),
    st.integers(min_value=-14 * 60, max_value=14 * 60).map(
        lambda minutes: timezone(timedelta(minutes=minutes))
    ),
    st.times(),
)
def test_the_decision_day_is_the_last_cutoff_passed(
    moment: datetime, zone: timezone, cutoff: time
) -> None:
    at = moment.replace(tzinfo=zone)
    day = decision_day(at, cutoff)
    assert decision_time(day, cutoff) <= at < decision_time(day + timedelta(days=1), cutoff)


def test_the_decision_day_at_the_cutoff_and_across_time_zones() -> None:
    cutoff = time(21, 0)
    assert decision_day(datetime(2026, 10, 20, 12, 0, tzinfo=UTC), cutoff) == date(2026, 10, 19)
    assert decision_day(datetime(2026, 10, 20, 21, 0, tzinfo=UTC), cutoff) == date(2026, 10, 20)
    paris = timezone(timedelta(hours=2))
    assert decision_day(datetime(2026, 10, 20, 23, 30, tzinfo=paris), cutoff) == date(2026, 10, 20)
    assert decision_day(datetime(2026, 10, 21, 1, 0, tzinfo=paris), cutoff) == date(2026, 10, 20)


def test_a_grid_point_matches_types_included() -> None:
    assert grid_point(SPEC, {"long": 50, "short": 20}) == {"short": 20, "long": 50}
    for params in (
        {"short": 20.0, "long": 50},
        {"short": True, "long": 50},
        {"short": "20", "long": 50},
        {"short": 20},
        {"short": 20, "long": 50, "autre": 1},
        {"short": 7777, "long": 50},
    ):
        with pytest.raises(CopilotError, match="hors de la grille de croisement_mm") as refused:
            grid_point(SPEC, params)
        # The message names the grid, never the values the planner asked (R5).
        assert "7777" not in str(refused.value) and "9 point(s)" in str(refused.value)


def test_the_lookup_keeps_the_answered_backtests_of_the_strategy(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path / "journal.jsonl")
    kept = [call(journal, arguments={"as_of": "2021-06-01T14:00:00+02:00", "debut": "2020-01-02"})]
    call(journal, status="erreur")
    call(journal, arguments={"mode": "signaux"})
    call(journal, arguments={"strategie": "autre"})
    call(journal, plugin="finance_risk")
    call(journal, tool="autre_outil")
    call(journal, actor="owner")
    journal.append(actor="orchestrator", event="DECISION", payload={"arguments": dict(ASKED)})
    kept.append(call(journal, arguments={"fin": "2021-12-31"}))
    found = copilot_requests(journal.path, "croisement_mm")
    assert [r.source for r in found] == [f"audit#{e['seq']} {e['hash']}" for e in kept]
    first, second = found
    assert first.at == AT and first.params == {"short": 20, "long": 50}
    assert (first.start, first.end) == (date(2020, 1, 2), None)
    # Without as_of the tool read its clock when called: the entry's time less the call.
    assert second.at == TS - timedelta(milliseconds=1500)
    assert (second.start, second.end) == (None, date(2021, 12, 31))
    assert all(len(r.source) <= 120 for r in found)
    assert copilot_requests(tmp_path / "absent.jsonl", "croisement_mm") == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"params": '{"short": 20, "lo…'},
        {"params": None},
        {"as_of": "2021-06-01T12:00:00"},
        {"as_of": "hier"},
        {"debut": "02/01/2020"},
    ],
)
def test_an_unreadable_entry_refuses_the_lookup(tmp_path: Path, arguments: dict[str, Any]) -> None:
    journal = AuditJournal(tmp_path / "journal.jsonl")
    entry = call(journal, arguments=arguments)
    with pytest.raises(CopilotError, match=f"entrée audit#{entry['seq']} .* illisible"):
        copilot_requests(journal.path, "croisement_mm")


def test_a_broken_journal_refuses_the_lookup(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path / "journal.jsonl")
    call(journal)
    with journal.path.open("a", encoding="utf-8") as handle:
        handle.write("pas du json\n")
    with pytest.raises(CopilotError, match="journal d'audit illisible"):
        copilot_requests(journal.path, "croisement_mm")


def test_a_replayed_request_is_a_copilot_trial_of_its_window(history: MarketHistory) -> None:
    asked = request(start=date(2020, 1, 2), end=date(2021, 5, 31))
    [trial] = replay([asked, request("audit#2 def")], history, recorded={"audit#2 def"})
    assert (trial.origin, trial.source, trial.engine) == ("copilote", "audit#1 abc", ENGINE)
    assert trial.strategy == "croisement_mm" and trial.params == {"short": 20, "long": 50}
    assert trial.code_sha256 == strategy_code_sha256(STRATEGY) and trial.costs == COSTS.name
    run = backtest(
        SPEC,
        STRATEGY,
        asked.params,
        history,
        at=AT,
        research=RESEARCH,
        costs=COSTS,
        initial_cash=100_000.0,
        sessions_per_year=252,
        start=asked.start,
        end=asked.end,
    )
    assert (trial.start, trial.end) == (run.window.start, run.window.end)
    assert (trial.start, trial.end) == (date(2020, 1, 2), date(2021, 5, 31))
    assert trial.sharpe_annual == run.measures.sharpe


def test_a_replay_reads_the_history_as_published_at_the_request(history: MarketHistory) -> None:
    """R10: a store filled later, revisions included, replays the same curve."""
    asked = request()
    [later] = replay([asked], history)
    [then] = replay([asked], history.known_by(AT, decision_day(AT, CUTOFF)))
    assert later == then
    assert later.end == date(2021, 5, 31)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"params": {"short": 15, "long": 50}}, "hors de la grille"),
        ({"end": date(2021, 12, 31)}, "(R10)"),
        ({"start": date(2016, 1, 4), "end": date(2025, 12, 31), "at": TS}, "au plus 2520"),
    ],
)
def test_a_request_that_no_longer_replays_refuses_them_all(
    history: MarketHistory, changes: dict[str, Any], reason: str
) -> None:
    with pytest.raises(CopilotError, match="non rejouable") as refused:
        replay([request("audit#2 def"), request(**changes)], history)
    assert reason in str(refused.value) and "il compte dans N" in str(refused.value)
    assert "audit#1 abc" in str(refused.value)


def test_the_params_round_trip_through_the_journal(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path / "journal.jsonl")
    point = {"short": 5, "long": 200}
    call(journal, arguments={"params": json.dumps(point), "as_of": "2021-06-01T12:00:00Z"})
    [found] = copilot_requests(journal.path, "croisement_mm")
    assert grid_point(SPEC, found.params) == point and found.at == AT
