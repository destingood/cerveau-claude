"""The order-intent drafter (ADR-029, B108): every figure from code, any doubt drafts nothing."""

from __future__ import annotations

import copy
import shutil
from dataclasses import replace
from datetime import date
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.committee.engine import Sitting
from core.committee.rules import NO_CATALYST, SIZE_PENDING, LimitCheck
from core.committee.schemas import ControllerReport, ManagerDecision
from core.config import load_config
from core.config.loader import ExecutionConfig, PaperRiskLimits
from core.execution.drafter import (
    CONFIDENCE,
    ELLIPSIS,
    HORIZON_DAYS,
    DraftError,
    IntentDrafter,
    TargetOrder,
    clip,
    committee_orders,
    committee_origin,
    committee_rationale,
    limit_price,
    strategy_orders,
    strategy_origin,
    strategy_rationale,
    within_collar,
)
from core.execution.intent import IntentOrigin, IntentRationale, SizingSource
from core.execution.uuid7 import uuid7_from_fields
from core.finance import views
from core.finance.fixtures import REFERENCE_READ_AT, reference_store
from core.finance.rebalance import RebalanceProposal, rebalance_proposal
from core.finance.research.execution import Order
from core.finance.research.registry import StrategySpec
from core.orchestrator.planner import Session
from core.risk_gate.gate import evaluate
from core.risk_gate.snapshot import GateSnapshot
from core.verification.trace import tool_output
from plugins.finance_optimize.tests.test_optimize_server import COSTS, KNOWN_COSTS
from tests.risk_gate.cases import AS_OF, CLOSE_PUBLISHED, MICS, World, base_world, build
from tests.test_finance_research_registry import candidate

ROOT = Path(__file__).resolve().parents[1]
SIZING = SizingSource(tool="strategy.momentum_12_1", call_id="strategy.momentum_12_1#1")
PRICE = {"price_tool": "market_data", "price_call": "market_data#1"}
RATIONALE = IntentRationale(
    thesis="Le titre s'échange sous sa valeur estimée.",
    catalyst="Résultats trimestriels du 24 octobre.",
    invalidation="Marge opérationnelle sous 10 % au trimestre.",
    horizon_days=90,
    confidence=0.6,
)
STRATEGY = IntentOrigin(kind="strategy", id="momentum_12_1")
RECORD = "0199f6a2-7c1e-7d3a-9b2f-3c4d5e6f7a8b"
CALL = "analyste_portefeuille:rebalance_proposal#1"


def ids() -> Any:
    counter = iter(range(1, 1_000))
    return lambda: uuid7_from_fields(0x019A0000_0000, next(counter), 0x1234_5678_9ABC_DEF0)


def drafter(offset: float | str = 0.5, collar: float | str = 2.0) -> IntentDrafter:
    limits = PaperRiskLimits.model_validate(
        base_world()["limits"] | {"limit_price_collar_pct": collar}
    )
    execution = ExecutionConfig(limit_offset_pct=offset, max_participation_pct=10.0)
    return IntentDrafter(execution, limits, ids=ids())


def snapshot(world: World | None = None) -> GateSnapshot:
    return GateSnapshot.model_validate((world or base_world())["snapshot"])


def draft(*orders: TargetOrder, world: World | None = None, **kwargs: Any) -> tuple[Any, ...]:
    return drafter(**kwargs).draft(
        orders, snapshot(world), **PRICE, rationale=RATIONALE, origin=STRATEGY
    )


# Limit price -------------------------------------------------------------------------------------


def test_the_limit_price_moves_toward_a_fill_and_rounds_on_the_cautious_side() -> None:
    assert limit_price(Decimal("100.00"), "BUY", Decimal("0.5")) == Decimal("100.50")
    assert limit_price(Decimal("50.00"), "SELL", Decimal("0.5")) == Decimal("49.75")
    # 33.33 × 1.005 = 33.49665: a buy pays at most 33.49, a sell receives at least 33.17.
    assert limit_price(Decimal("33.33"), "BUY", Decimal("0.5")) == Decimal("33.49")
    assert limit_price(Decimal("33.33"), "SELL", Decimal("0.5")) == Decimal("33.17")


@given(
    cents=st.integers(1, 10**9),
    offset=st.integers(0, 2_000),
    extra=st.integers(0, 2_000),
    side=st.sampled_from(["BUY", "SELL"]),
)
def test_a_limit_price_stays_within_the_collar_the_gate_applies(
    cents: int, offset: int, extra: int, side: str
) -> None:
    last, off = Decimal(cents) / 100, Decimal(offset) / 100
    collar = off + Decimal(extra) / 100  # the drafter refuses an offset above the collar (D17)
    limit = limit_price(last, side, off)  # type: ignore[arg-type]
    assert limit == limit.quantize(Decimal("0.01"))
    assert (limit >= last) if side == "BUY" else (limit <= last)
    # The gate's formula, checked against exact fractions.
    exact = abs(Fraction(limit) - Fraction(last)) * 100 <= Fraction(collar) * Fraction(last)
    assert within_collar(limit, last, collar) is exact is True


# Drafting ----------------------------------------------------------------------------------------


def test_a_drafted_buy_is_the_order_the_gate_accepts() -> None:
    [intent] = draft(TargetOrder("AAA", 3, SIZING))
    world = base_world()
    assert intent.side == "BUY" and intent.quantity == 3 and intent.limit_price == Decimal("100.50")
    assert (intent.created_at, intent.decision_date) == (AS_OF, date(2026, 10, 19))
    assert intent.instrument.model_dump() == world["intent"]["instrument"]
    assert intent.price_source.as_of == CLOSE_PUBLISHED  # the close the gate reads (R10)
    assert intent.sizing_source == SIZING and intent.committee_record_id is None
    result = evaluate(intent, *build(world).args[1:])
    assert result.result == "ACCEPTE", result.reasons


def test_a_drafted_sell_passes_the_collar() -> None:
    [intent] = draft(TargetOrder("BBB", -4, SIZING))
    assert (intent.side, intent.quantity, intent.limit_price) == ("SELL", 4, Decimal("49.75"))
    assert intent.instrument.isin is None and intent.instrument.venue == "XNYS"
    result = evaluate(intent, *build(base_world()).args[1:])
    [collar] = [c for c in result.checks if c.name == "limit_price_collar_pct"]
    assert collar.ok


def test_each_intent_gets_its_own_id() -> None:
    first, second = draft(TargetOrder("AAA", 1, SIZING), TargetOrder("CCC", 2, SIZING))
    assert first.intent_id != second.intent_id


def test_a_committee_origin_names_its_record() -> None:
    origin = IntentOrigin(kind="committee", id=RECORD)
    [intent] = drafter().draft(
        [TargetOrder("AAA", 1, SIZING)], snapshot(), **PRICE, rationale=RATIONALE, origin=origin
    )
    assert intent.committee_record_id == RECORD


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"offset": "A_DEFINIR"}, "limit_offset_pct vaut A_DEFINIR"),
        ({"collar": "A_VERIFIER"}, "limit_price_collar_pct vaut A_VERIFIER"),
        ({"offset": 2.5}, "dépasse la bande de prix de la Porte"),
    ],
)
def test_an_unknown_or_loose_setting_drafts_nothing(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(DraftError, match=message):
        drafter(**kwargs)


def _missing_quote() -> World:
    world = base_world()
    del world["snapshot"]["quotes"]["AAA"]
    return world


def _missing_facts() -> World:
    world = base_world()
    del world["snapshot"]["instruments"]["CCC"], world["snapshot"]["quotes"]["CCC"]
    return world


def _odd_price() -> World:
    world = base_world()
    world["snapshot"]["quotes"]["AAA"]["price"] = Decimal("10.005")  # beyond the cent
    return world


@pytest.mark.parametrize(
    ("orders", "world", "kwargs", "message"),
    [
        ([("AAA", 1), ("AAA", 2)], None, {}, "deux ordres pour un même instrument : AAA"),
        ([("AAA", 0)], None, {}, "AAA : quantité nulle"),
        ([("AAA", 1)], _missing_quote(), {}, "AAA : dernier cours absent"),
        ([("CCC", 1)], _missing_facts(), {}, "CCC : référentiel absent"),
        ([("AAA", -1)], None, {"offset": 100.0, "collar": 100.0}, "prix limite 0.00 hors"),
        ([("AAA", 1)], _odd_price(), {"offset": 0.01, "collar": 0.01}, "prix limite 10.00 hors"),
        ([("ZZZ", 1)], None, {}, "ZZZ : référentiel absent"),
    ],
)
def test_any_doubt_drafts_nothing(
    orders: list[tuple[str, int]], world: World | None, kwargs: dict[str, Any], message: str
) -> None:
    with pytest.raises(DraftError, match=message):
        draft(*(TargetOrder(s, q, SIZING) for s, q in orders), world=world, **kwargs)


def test_a_last_price_beyond_the_cent_may_leave_no_cent_in_the_collar() -> None:
    # 10.005 × 1.0001 rounds down to 10.00: 0.05 % away, outside a collar of 0.01 %.
    assert limit_price(Decimal("10.005"), "BUY", Decimal("0.01")) == Decimal("10.00")
    [intent] = draft(TargetOrder("AAA", 1, SIZING), world=_odd_price(), offset=0.01, collar=0.1)
    assert intent.limit_price == Decimal("10.00")


# Texts -------------------------------------------------------------------------------------------


def test_a_long_text_is_cut_at_a_word_with_an_ellipsis() -> None:
    assert clip("  court   texte ") == "court texte"
    long = "mot, " * 200
    cut = clip(long)
    assert len(cut) <= 400 and cut.endswith(ELLIPSIS) and not cut.endswith(", " + ELLIPSIS)
    assert clip("x" * 500).startswith("x" * 399) and len(clip("x" * 500)) == 400


# Strategy source ---------------------------------------------------------------------------------


def test_a_candidate_strategy_drafts_its_rule_signal() -> None:
    spec = candidate()
    rationale = strategy_rationale(spec, signal_date=date(2026, 10, 16))
    assert rationale.thesis == " ".join(spec.hypothese.split())
    assert rationale.catalyst == f"Signal de la règle « {spec.nom} » à la clôture du 16/10/2026."
    assert (rationale.invalidation, rationale.horizon_days) == (spec.invalidation, 60)
    assert rationale.confidence == CONFIDENCE["faible"]
    assert strategy_origin(spec) == IntentOrigin(kind="strategy", id=spec.id)
    orders = strategy_orders([Order("AAA", 3, 0.0), Order("BBB", -2, 0.0)], SIZING)
    assert [(o.symbol, o.quantity) for o in orders] == [("AAA", 3), ("BBB", -2)]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"statut": "recherche"}, "statut « recherche »"),
        ({"invalidation": None}, "sans invalidation ou sans horizon"),
        ({"horizon_jours": None}, "sans invalidation ou sans horizon"),
    ],
)
def test_only_a_complete_candidate_drafts(changes: dict[str, Any], message: str) -> None:
    spec: StrategySpec = candidate(**changes)
    with pytest.raises(DraftError, match=message):
        strategy_rationale(spec, signal_date=date(2026, 10, 16))


# Committee source --------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def proposal(tmp_path_factory: pytest.TempPathFactory) -> RebalanceProposal:
    """A risk-parity proposal on the reference base, with costs known so that it has trades."""
    root = tmp_path_factory.mktemp("drafter")
    store = reference_store(root / "finance.db")
    config_dir = Path(shutil.copytree(ROOT / "config", root / "config"))
    risk = config_dir / "risk.yaml"
    text = risk.read_text(encoding="utf-8")
    assert COSTS in text
    risk.write_text(text.replace(COSTS, KNOWN_COSTS), encoding="utf-8")
    config = load_config(config_dir)
    return views.read_store(
        store,
        lambda db: rebalance_proposal(
            db, config, as_of=REFERENCE_READ_AT, method="parite_de_risque"
        ),
    )


def decision(**changes: Any) -> ManagerDecision:
    return ManagerDecision.model_validate(
        {
            "decision": "agir",
            "proposition": "Rééquilibrer vers la parité de risque",
            "confiance": "moyen",
            "horizon": "moyen",
            "catalyseur": {"texte": "La volatilité de FICT-ACME a doublé", "constats": ["C1"]},
            "invalidation": [
                {"condition": "La volatilité revient sous sa moyenne", "constats": ["C1"]},
                {"condition": "Un choc de taux de 100 pb", "constats": ["C1"]},
            ],
            "desaccords": [],
            "arguments": [{"id": "D1.1", "sort": "retenu", "raison": "fondé"}],
        }
        | changes
    )


def report(verdict: str = "OK") -> ControllerReport:
    return ControllerReport.model_validate(
        {
            "scenarios": [{"texte": "Choc de marché : -12,0 %", "appel": "controleur:risk#1"}],
            "irreversibilite": "Aucune : rien n'est exécuté",
            "verdict": verdict,
            "raisons": ["les contrôles du code sont respectés"],
        }
    )


def sitting(
    proposal: RebalanceProposal,
    *,
    manager: ManagerDecision | None = None,
    checks: tuple[LimitCheck, ...] = (LimitCheck("max_order_pct", None, SIZE_PENDING),),
    verdict: str = "OK",
    **changes: Any,
) -> Sitting:
    read = tool_output(CALL, "rebalance_proposal", proposal.model_dump(mode="json"))
    session = Session(call_prefix="analyste_portefeuille:", tool_outputs=[read])
    record = Sitting(
        record_id=RECORD,
        question="Faut-il rééquilibrer ?",
        pack="finance",
        version="test",
        status="complete",
        decision=manager or decision(),
        controller=report(verdict),
        checks=checks,
        sessions={"analyste_portefeuille": session},
    )
    return replace(record, **changes)


def test_a_decision_to_act_drafts_the_proposal_trades(proposal: RebalanceProposal) -> None:
    record = sitting(proposal)
    orders = committee_orders(record, proposal, call=CALL)
    assert proposal.trades
    assert [(o.symbol, o.quantity) for o in orders] == [
        (t.line, int(t.quantity.value) * (1 if t.side == "achat" else -1)) for t in proposal.trades
    ]
    assert {o.sizing for o in orders} == {SizingSource(tool="rebalance_proposal", call_id=CALL)}
    rationale = committee_rationale(record)
    assert rationale.thesis == "Rééquilibrer vers la parité de risque"
    assert rationale.catalyst == "La volatilité de FICT-ACME a doublé"
    assert rationale.invalidation == (
        "La volatilité revient sous sa moyenne ; Un choc de taux de 100 pb"
    )
    assert (rationale.horizon_days, rationale.confidence) == (HORIZON_DAYS["moyen"], 0.5)
    origin = committee_origin(record)
    # Every line of the proposal, quoted by the Gate's snapshot: each draft is in its collar.
    world = base_world()
    for trade in proposal.trades:
        world["snapshot"]["instruments"][trade.line] = {
            "asset_class": "equity",
            "currency": trade.currency,
            "sector": "tech",
            "country": "FR",
            "mic": MICS[trade.currency],
        }
        world["snapshot"]["quotes"][trade.line] = copy.deepcopy(world["snapshot"]["quotes"]["AAA"])
    intents = drafter().draft(orders, snapshot(world), **PRICE, rationale=rationale, origin=origin)
    assert [i.instrument.symbol for i in intents] == [o.symbol for o in orders]
    assert {i.committee_record_id for i in intents} == {RECORD}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"manager": "attendre"}, "décision « attendre »"),
        ({"status": "incomplete"}, "non conclue"),
        ({"decision": None}, "non conclue"),
        ({"verdict": "BLOQUER"}, "le contrôleur de risque bloque"),
        (
            {"checks": (LimitCheck("max_order_pct", None, "A_DEFINIR dans config (R7)"),)},
            r"max_order_pct : limite inconnue",
        ),
        ({"checks": ()}, "aucun contrôle de limite"),
        ({"manager": "sans catalyseur"}, "sans catalyseur"),
    ],
)
def test_only_a_cleared_decision_to_act_drafts(
    proposal: RebalanceProposal, changes: dict[str, Any], message: str
) -> None:
    if changes.get("manager") == "attendre":
        changes["manager"] = decision(decision="attendre", catalyseur=None)
    elif changes.get("manager") == "sans catalyseur":
        changes["manager"] = decision(catalyseur=None)
    record = sitting(proposal, **changes)
    with pytest.raises(DraftError, match=message):
        committee_orders(record, proposal, call=CALL)
    with pytest.raises(DraftError, match=message):
        committee_rationale(record)


def test_the_missing_catalyst_reason_is_the_committee_one(proposal: RebalanceProposal) -> None:
    record = sitting(proposal, manager=decision(catalyseur=None))
    with pytest.raises(DraftError) as raised:
        committee_rationale(record)
    assert NO_CATALYST in str(raised.value)


def test_the_proposal_must_be_the_one_the_sitting_read(proposal: RebalanceProposal) -> None:
    record = sitting(proposal)
    with pytest.raises(DraftError, match="aucun appel rebalance_proposal"):
        committee_orders(record, proposal, call="analyste_portefeuille:rebalance_proposal#2")
    assert proposal.trades
    first = proposal.trades[0]
    other_quantity = first.quantity.model_copy(update={"value": first.quantity.value + 1})
    altered = proposal.model_copy(
        update={"trades": [first.model_copy(update={"quantity": other_quantity})]}
    )
    with pytest.raises(DraftError, match="diffère de celle que la séance a lue"):
        committee_orders(record, altered, call=CALL)


def test_a_proposal_without_known_costs_drafts_nothing(proposal: RebalanceProposal) -> None:
    unpriced = proposal.model_copy(update={"trades": None})
    with pytest.raises(DraftError, match="coûts inconnus"):
        committee_orders(sitting(unpriced), unpriced, call=CALL)
    empty = proposal.model_copy(update={"trades": []})
    with pytest.raises(DraftError, match="sans opération"):
        committee_orders(sitting(empty), empty, call=CALL)
