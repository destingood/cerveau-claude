"""The order book against a model of ADR-032's state machine, over random sequences of requests
and fills: the book moves exactly when the model does, and raises an incident exactly when the
model says the move is impossible."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, rule

from core.execution.book import Fill, OrderBook
from core.execution.intent import OrderIntent
from core.execution.states import (
    BY_FILL,
    FILLABLE,
    OPEN,
    TERMINAL,
    TRANSITIONS,
    ExecutionIncident,
    OrderState,
    check_move,
)
from tests.execution_cases import DECISION_PRICE, MemoryJournal, make_fill, make_intent, recorder

S = OrderState


def test_the_table_has_three_terminal_states_and_every_other_state_leads_to_one() -> None:
    assert {S.EXECUTEE, S.ANNULEE, S.REJETEE} == TERMINAL
    assert set(TRANSITIONS) == set(OrderState)
    assert {S.VALIDEE, S.ENVOYEE, S.PARTIELLE} == OPEN
    assert FILLABLE <= OPEN and not OPEN & TERMINAL
    reach = {state: set(targets) for state, targets in TRANSITIONS.items()}
    for _ in OrderState:  # transitive closure
        for targets in reach.values():
            targets |= {after for state in set(targets) for after in reach[state]}
    assert all(reach[state] & TERMINAL for state in set(OrderState) - TERMINAL)


@pytest.mark.parametrize("target", sorted(BY_FILL))
def test_no_request_reaches_a_state_only_a_fill_gives(target: OrderState) -> None:
    intent_id = make_intent().intent_id
    for current in OrderState:
        with pytest.raises(ExecutionIncident, match="seule une exécution"):
            check_move(intent_id, current, target)


@dataclass
class Model:
    intent: OrderIntent
    state: OrderState = S.INTENTION
    fills: list[Fill] = field(default_factory=list)

    @property
    def filled(self) -> int:
        return sum(fill.quantity for fill in self.fills)


class OrderBookMachine(RuleBasedStateMachine):
    orders = Bundle("orders")

    def __init__(self) -> None:
        super().__init__()
        self.journal = MemoryJournal()
        self.book = OrderBook.memory(recorder(self.journal))
        self.model: dict[UUID, Model] = {}
        self.entries = 0  # the journal entries the model expects
        self.fill_count = 0

    def teardown(self) -> None:
        self.book.close()

    @rule(target=orders, quantity=st.integers(1, 12))
    def record_intent(self, quantity: int) -> UUID:
        intent = make_intent(len(self.model), quantity=quantity)
        booked = self.book.record_intent(
            intent, decision_price=DECISION_PRICE, reason="intention rédigée"
        )
        assert booked.state == S.INTENTION
        self.model[intent.intent_id] = Model(intent)
        self.entries += 1
        return intent.intent_id

    @rule(intent_id=orders, wanted=st.sampled_from(OrderState))
    def request(self, intent_id: UUID, wanted: OrderState) -> None:
        model = self.model[intent_id]
        legal = wanted not in BY_FILL and wanted in TRANSITIONS[model.state]
        if legal:
            assert self.book.transition(intent_id, wanted, reason="demande") == wanted
            model.state = wanted
            self.entries += 1
        else:
            with pytest.raises(ExecutionIncident) as caught:
                self.book.transition(intent_id, wanted, reason="demande")
            assert (caught.value.kind, caught.value.intent_id) == (
                "transition_interdite",
                intent_id,
            )

    @rule(intent_id=orders, quantity=st.integers(1, 14))
    def fill(self, intent_id: UUID, quantity: int) -> None:
        model = self.model[intent_id]
        self.fill_count += 1
        fill = make_fill(model.intent, self.fill_count, quantity)
        if model.state not in FILLABLE:
            expected = "transition_interdite"
        elif model.filled + quantity > model.intent.quantity:
            expected = "quantite_depassee"
        else:
            model.fills.append(fill)
            done = model.filled == model.intent.quantity
            model.state = S.EXECUTEE if done else S.PARTIELLE
            assert self.book.record_fill(fill) == model.state
            self.entries += 1
            return
        with pytest.raises(ExecutionIncident) as caught:
            self.book.record_fill(fill)
        assert caught.value.kind == expected

    @rule(intent_id=orders)
    def report_again(self, intent_id: UUID) -> None:
        model = self.model[intent_id]
        if model.fills:
            assert self.book.record_fill(model.fills[-1]) == model.state

    @rule(wanted=st.sampled_from(OrderState))
    def stranger(self, wanted: OrderState) -> None:
        unknown = make_intent(10_000 + self.fill_count).intent_id
        with pytest.raises(ExecutionIncident) as caught:
            self.book.transition(unknown, wanted, reason="demande")
        assert caught.value.kind == "ordre_inconnu"

    @invariant()
    def the_book_is_the_model(self) -> None:
        booked = {order.intent.intent_id: order for order in self.book.orders()}
        assert booked.keys() == self.model.keys()
        for intent_id, model in self.model.items():
            order = booked[intent_id]
            assert order.state == model.state
            assert order.fills == tuple(model.fills)
            assert order.filled <= order.intent.quantity
            assert (order.state == S.EXECUTEE) == (order.filled == order.intent.quantity)
            committed = order.intent.quantity - model.filled
            assert order.remaining == (0 if model.state in TERMINAL else committed)
        assert {o.intent.intent_id for o in self.book.open_orders()} == {
            intent_id for intent_id, model in self.model.items() if model.state in OPEN
        }

    @invariant()
    def replaying_the_journal_gives_the_book(self) -> None:
        assert len(self.journal.entries) == self.entries
        last: dict[str, str] = {}
        for intent_id, state in self.journal.states:
            last[intent_id] = state
        assert last == {str(i): model.state.value for i, model in self.model.items()}


OrderBookMachine.TestCase.settings = settings(
    max_examples=200,
    stateful_step_count=40,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=[HealthCheck.too_slow],
)
TestOrderBookMachine = OrderBookMachine.TestCase
