from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from core.audit.chain import AuditJournal, verify
from core.budget import (
    ALERT_KEY,
    BudgetExceededError,
    BudgetGate,
    LedgerError,
    RequestBudget,
    RequestBudgetExceeded,
    read_spending,
)
from core.config import BlockedFeatureError, load_config
from core.config.loader import Config, PerRequest
from core.models import COST_SCHEMA, CostCalculator, Meter, TokenUsage
from tests.test_config_code import unblock_agent

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def _budgeted(config_dir: Path, daily: str = "1.00", monthly: str = "10.00") -> Config:
    path = config_dir / "budgets.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["llm_budget_eur"] = {"daily": daily, "monthly": monthly}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_config(config_dir)


@pytest.fixture
def config(config_dir: Path) -> Config:
    return _budgeted(config_dir)


@pytest.fixture
def journal(tmp_path: Path) -> AuditJournal:
    return AuditJournal(tmp_path / "audit" / "journal.jsonl")


def _gate(config: Config, journal: AuditJournal) -> BudgetGate:
    return BudgetGate(config, journal, tz=UTC)


def _cost(eur: str) -> dict:
    return {"cost_schema": COST_SCHEMA, "cost_usd": "0", "cost_eur": eur}


def _spend(journal: AuditJournal, eur: str, at: datetime = NOW, event: str = "DECISION") -> None:
    journal.append(actor="orchestrator", event=event, payload={"cost": _cost(eur)}, now=at)


def _entries(journal: AuditJournal) -> list[dict]:
    if not journal.path.exists():
        return []
    return [json.loads(line) for line in journal.path.read_text(encoding="utf-8").splitlines()]


def _alerts(journal: AuditJournal) -> list[tuple[str, int]]:
    found = []
    for entry in _entries(journal):
        if entry["event"] == "POLICY":
            alert = journal.read_payload(entry["payload_ref"])[ALERT_KEY]
            found.append((alert["period"], alert["pct"]))
    return found


# --- blocked while the budgets are not defined (R7, D3) ---


def test_real_config_blocks_the_gate(journal: AuditJournal) -> None:
    real = load_config(REPO_CONFIG)
    with pytest.raises(BlockedFeatureError) as err:
        BudgetGate(real, journal).check(now=NOW)
    assert "llm_budget_eur.daily = A_DEFINIR" in str(err.value)
    meter = Meter(CostCalculator(real.pricing))
    with pytest.raises(BlockedFeatureError):
        RequestBudget.from_config(real, meter)
    assert not journal.path.exists()


@pytest.mark.parametrize("value", ["0", "-1"])
def test_budget_must_be_positive(config_dir: Path, value: str) -> None:
    with pytest.raises(Exception, match="greater than 0"):
        _budgeted(config_dir, daily=value)


def test_budget_is_an_exact_decimal(config: Config) -> None:
    assert config.budgets.llm_budget_eur.daily == Decimal("1.00")
    assert isinstance(config.budgets.llm_budget_eur.monthly, Decimal)


# --- ledger ---


def test_empty_journal_spends_nothing(journal: AuditJournal) -> None:
    spending = read_spending(journal, NOW, UTC)
    assert (spending.day_eur, spending.month_eur, spending.alerts) == (0, 0, frozenset())
    assert (spending.day_key, spending.month_key) == ("2026-10-18", "2026-10")


def test_ledger_sums_decisions_of_the_day_and_month_exactly(journal: AuditJournal) -> None:
    _spend(journal, "0.1")
    _spend(journal, "0.2")
    _spend(journal, "0.000001", at=NOW - timedelta(days=17))  # 1 October
    _spend(journal, "5", at=NOW - timedelta(days=18))  # 30 September: another month
    _spend(journal, "7", event="TOOL_CALL")  # detail lines are never summed
    journal.append(actor="orchestrator", event="DECISION", payload={"refus": "R15"}, now=NOW)
    journal.append(actor="orchestrator", event="DECISION", now=NOW)
    spending = read_spending(journal, NOW, UTC)
    assert spending.day_eur == Decimal("0.3")
    assert spending.month_eur == Decimal("0.300001")


def test_ledger_reads_the_meter_payload(journal: AuditJournal) -> None:
    real = load_config(REPO_CONFIG)
    meter = Meter(CostCalculator(real.pricing))
    meter.record_search("brave", 2)
    journal.append(actor="orchestrator", event="DECISION", payload={"cost": meter.to_payload()})
    assert read_spending(journal, datetime.now().astimezone()).day_eur == meter.total_eur


def test_days_follow_the_given_time_zone(journal: AuditJournal) -> None:
    late = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    _spend(journal, "0.5", at=late)
    paris_summer = timezone(timedelta(hours=2))
    assert read_spending(journal, late, UTC).day_eur == Decimal("0.5")
    next_day = read_spending(journal, late, paris_summer)
    assert next_day.day_key == "2026-10-19"
    assert next_day.day_eur == Decimal("0.5")
    assert read_spending(journal, late + timedelta(days=1), UTC).day_eur == 0


def test_month_boundary_in_the_given_time_zone(journal: AuditJournal) -> None:
    eve = datetime(2026, 10, 31, 22, 30, tzinfo=UTC)  # already 1 November at UTC+2
    _spend(journal, "0.5", at=eve)
    assert read_spending(journal, eve, UTC).month_eur == Decimal("0.5")
    november = read_spending(journal, eve, timezone(timedelta(hours=2)))
    assert (november.month_key, november.month_eur) == ("2026-11", Decimal("0.5"))
    assert read_spending(journal, eve + timedelta(days=1), UTC).month_eur == 0


def _payload_path(journal: AuditJournal) -> Path:
    ref = _entries(journal)[-1]["payload_ref"]
    return journal.payload_dir / (ref.removeprefix("sha256:") + ".json")


def test_unreadable_line_makes_spending_unknown(journal: AuditJournal) -> None:
    _spend(journal, "0.1")
    with journal.path.open("a", encoding="utf-8") as f:
        f.write("{pas du json\n")
    with pytest.raises(LedgerError, match="ligne 2 : entrée illisible"):
        read_spending(journal, NOW, UTC)


def test_altered_entry_makes_spending_unknown(journal: AuditJournal) -> None:
    _spend(journal, "0.9")
    entry = _entries(journal)[0]
    entry["ts"] = "2026-09-01T00:00:00.000+00:00"  # moved out of the month
    journal.path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    with pytest.raises(LedgerError, match="entrée modifiée"):
        read_spending(journal, NOW, UTC)


def test_altered_payload_makes_spending_unknown(journal: AuditJournal) -> None:
    _spend(journal, "0.9")
    path = _payload_path(journal)
    path.write_text(json.dumps({"cost": _cost("0.0")}), encoding="utf-8")
    with pytest.raises(LedgerError, match="payload modifié"):
        read_spending(journal, NOW, UTC)
    path.unlink()
    with pytest.raises(LedgerError, match="payload introuvable"):
        read_spending(journal, NOW, UTC)


@pytest.mark.parametrize(
    "cost",
    [
        {"cost_schema": COST_SCHEMA + 1, "cost_eur": "0.1"},
        {"cost_eur": "0.1"},
        {"cost_schema": COST_SCHEMA, "cost_eur": "-0.1"},
        {"cost_schema": COST_SCHEMA, "cost_eur": "NaN"},
        {"cost_schema": COST_SCHEMA, "cost_eur": "abc"},
        {"cost_schema": COST_SCHEMA},
        "0.1",
    ],
)
def test_unreadable_cost_makes_spending_unknown(journal: AuditJournal, cost: object) -> None:
    journal.append(actor="orchestrator", event="DECISION", payload={"cost": cost}, now=NOW)
    with pytest.raises(LedgerError):
        read_spending(journal, NOW, UTC)


def test_unreadable_spending_blocks_the_gate(config: Config, journal: AuditJournal) -> None:
    _spend(journal, "0.1")
    _payload_path(journal).unlink()
    with pytest.raises(LedgerError):
        _gate(config, journal).check(now=NOW)


# --- daily and monthly gate ---


def test_gate_passes_without_spending(config: Config, journal: AuditJournal) -> None:
    check = _gate(config, journal).check(now=NOW)
    assert (check.alerts, check.journaled, check.exceeded) == ((), (), ())
    assert not journal.path.exists()


def test_each_threshold_is_journaled_once(config: Config, journal: AuditJournal) -> None:
    gate = _gate(config, journal)
    _spend(journal, "0.49")
    assert gate.check(now=NOW).alerts == ()
    _spend(journal, "0.01")  # exactly 50 %
    first = gate.check(now=NOW, request_id="r1")
    assert [(a.period, a.pct) for a in first.journaled] == [("jour", 50)]
    assert first.journaled[0].message() == (
        "Budget du jour (2026-10-18) à 50 % : 0.50 € dépensés sur 1.00 €."
    )
    again = gate.check(now=NOW)
    assert again.journaled == ()
    assert [a.pct for a in again.highest()] == [50]
    _spend(journal, "0.30")
    assert [a.pct for a in gate.check(now=NOW).journaled] == [80]
    assert _alerts(journal) == [("jour", 50), ("jour", 80)]
    policy = [e for e in _entries(journal) if e["event"] == "POLICY"]
    assert policy[0]["actor"] == "policy"
    assert policy[0]["request_id"] == "r1"
    assert policy[0]["versions"] == {"config": config.digest}
    assert verify(journal.path).ok


def test_gate_refuses_at_100_percent(config: Config, journal: AuditJournal) -> None:
    gate = _gate(config, journal)
    _spend(journal, "0.999999")
    gate.check(now=NOW)
    _spend(journal, "0.000001")
    with pytest.raises(BudgetExceededError) as err:
        gate.check(now=NOW)
    assert "Budget du jour (2026-10-18) à 100 %" in str(err.value)
    assert "Nouvelle requête refusée" in str(err.value)
    assert [a.pct for a in err.value.check.journaled] == [100]
    assert _alerts(journal) == [("jour", 50), ("jour", 80), ("jour", 100)]
    with pytest.raises(BudgetExceededError) as again:
        gate.check(now=NOW)
    assert again.value.check.journaled == ()
    # the next day starts afresh, the month keeps counting
    tomorrow = gate.check(now=NOW + timedelta(days=1))
    assert tomorrow.alerts == ()
    assert tomorrow.spending.month_eur == Decimal("1.000000")


def test_each_refusal_is_an_error_record(config: Config, journal: AuditJournal) -> None:
    gate = _gate(config, journal)
    _spend(journal, "0.80")
    gate.check(now=NOW, request_id="r1")  # an alert is not an error
    _spend(journal, "0.20")
    for request_id in ("r2", "r3"):
        with pytest.raises(BudgetExceededError):
            gate.check(now=NOW, request_id=request_id)
    errors = [e for e in _entries(journal) if e["event"] == "ERROR"]
    assert [(e["actor"], e["request_id"]) for e in errors] == [("policy", "r2"), ("policy", "r3")]
    assert errors[0]["versions"] == {"config": config.digest}
    assert journal.read_payload(errors[0]["payload_ref"]) == {
        "error_schema": 1,
        "kind": "budget_exceeded",
        "details": {
            "exceeded": [
                {
                    "period": "jour",
                    "period_key": "2026-10-18",
                    "pct": 100,
                    "spent_eur": "1.00",
                    "limit_eur": "1.00",
                }
            ]
        },
    }
    assert verify(journal.path).ok


def test_monthly_budget_refuses_too(config_dir: Path, journal: AuditJournal) -> None:
    config = _budgeted(config_dir, daily="100", monthly="2")
    gate = _gate(config, journal)
    for day in range(1, 5):
        _spend(journal, "0.5", at=datetime(2026, 10, day, 9, tzinfo=UTC))
    with pytest.raises(BudgetExceededError) as err:
        gate.check(now=NOW)
    assert [(a.period, a.pct) for a in err.value.check.exceeded] == [("mois", 100)]
    assert _alerts(journal) == [("mois", 50), ("mois", 80), ("mois", 100)]
    assert gate.check(now=datetime(2026, 11, 1, 9, tzinfo=UTC)).alerts == ()


def test_status_does_not_write(config: Config, journal: AuditJournal) -> None:
    _spend(journal, "2")
    status = _gate(config, journal).status(now=NOW)
    assert [a.pct for a in status.exceeded] == [100]
    assert status.journaled == ()
    assert _alerts(journal) == []


# --- per-request limits ---

LIMITS = PerRequest(max_tool_calls=25, max_tokens=150000, max_seconds=120)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def meter() -> Meter:
    return Meter(CostCalculator(load_config(REPO_CONFIG).pricing))


def test_request_budget_from_config(config: Config, meter: Meter) -> None:
    budget = RequestBudget.from_config(config, meter)
    assert budget.to_payload()["tokens"] == {"used": 0, "max": 150000}


def test_tool_call_beyond_the_limit_is_refused(meter: Meter) -> None:
    budget = RequestBudget(LIMITS, meter, clock=_Clock())
    for _ in range(25):
        budget.charge_tool_call()
    with pytest.raises(RequestBudgetExceeded) as err:
        budget.charge_tool_call()
    assert (err.value.limit, err.value.used, err.value.maximum) == ("tool_calls", 26, 25)
    assert str(err.value) == "limite par requête atteinte : appels d'outils 26 sur 25"
    assert budget.tool_calls == 25


def test_token_limit(meter: Meter) -> None:
    budget = RequestBudget(LIMITS, meter, clock=_Clock())
    model = load_config(REPO_CONFIG).models.tiers["fast"].model
    meter.record_llm(role="reader", tier="fast", model=model, usage=TokenUsage(input=149_999))
    budget.check()
    assert budget.remaining_tokens() == 1
    meter.record_llm(role="reader", tier="fast", model=model, usage=TokenUsage(output=1))
    assert budget.remaining_tokens() == 0
    with pytest.raises(RequestBudgetExceeded, match="tokens 150000 sur 150000"):
        budget.check()
    with pytest.raises(RequestBudgetExceeded):
        budget.charge_tool_call()
    assert budget.tool_calls == 0


def test_time_limit(meter: Meter) -> None:
    clock = _Clock()
    budget = RequestBudget(LIMITS, meter, clock=clock)
    clock.now += 119.5
    budget.check()
    assert budget.remaining_seconds() == pytest.approx(0.5)
    clock.now += 0.5
    assert budget.remaining_seconds() == 0
    with pytest.raises(RequestBudgetExceeded) as err:
        budget.check()
    assert err.value.limit == "seconds"
    assert budget.to_payload()["seconds"] == {"used": 120.0, "max": 120}


def test_undefined_token_limit_blocks(meter: Meter) -> None:
    limits = PerRequest(max_tool_calls=25, max_tokens="A_DEFINIR", max_seconds=120)
    with pytest.raises(ValueError, match="R7"):
        RequestBudget(limits, meter)


# --- the code agent's task (ADR-054) -----------------------------------------------------------


def test_the_code_agent_budget_is_blocked_while_marked(meter: Meter) -> None:
    config = load_config(REPO_CONFIG)
    with pytest.raises(BlockedFeatureError) as err:
        RequestBudget.for_code_agent(config, meter, feature="code.agent")
    assert "budgets.yaml › per_code_agent.max_tokens = A_DEFINIR" in err.value.reasons


def test_a_marked_code_agent_budget_refuses_any_feature(config_dir: Path, meter: Meter) -> None:
    """Even a feature that does not list it cannot open a task on a marker (R7)."""
    config = load_config(config_dir)
    with pytest.raises(ValueError, match="per_code_agent non défini : tâche bloquée"):
        RequestBudget.for_code_agent(config, meter, feature="llm.fast")


def test_the_code_agent_task_has_its_own_limits(
    config_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    unblock_agent(config_dir, str(tmp_path_factory.mktemp("depot")), max_seconds=950)
    config = load_config(config_dir)
    meter = Meter(CostCalculator(config.pricing))
    clock = _Clock()
    budget = RequestBudget.for_code_agent(config, meter, feature="code.agent", clock=clock)
    assert budget.max_seconds == 950
    assert budget.to_payload() == {
        "tool_calls": {"used": 0, "max": 5},
        "tokens": {"used": 0, "max": 2_000_000},
        "seconds": {"used": 0.0, "max": 950},
    }
