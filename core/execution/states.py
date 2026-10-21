"""The order state machine (ADR-032, §10.8): the only moves an order may make.

EXECUTEE, ANNULEE and REJETEE are terminal. Any other move is an execution incident (§9): the
book records nothing of it and the caller trips the kill switch (ADR-034).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Literal
from uuid import UUID


class OrderState(StrEnum):
    INTENTION = "INTENTION"
    VALIDEE = "VALIDEE"
    ENVOYEE = "ENVOYEE"
    PARTIELLE = "PARTIELLE"
    EXECUTEE = "EXECUTEE"
    ANNULEE = "ANNULEE"
    REJETEE = "REJETEE"


_S = OrderState
TRANSITIONS: Mapping[OrderState, frozenset[OrderState]] = MappingProxyType(
    {
        _S.INTENTION: frozenset({_S.VALIDEE, _S.REJETEE}),
        _S.VALIDEE: frozenset({_S.ENVOYEE, _S.ANNULEE}),
        _S.ENVOYEE: frozenset({_S.PARTIELLE, _S.EXECUTEE, _S.ANNULEE, _S.REJETEE}),
        _S.PARTIELLE: frozenset({_S.EXECUTEE, _S.ANNULEE}),
        _S.EXECUTEE: frozenset(),
        _S.ANNULEE: frozenset(),
        _S.REJETEE: frozenset(),
    }
)
TERMINAL = frozenset(state for state, targets in TRANSITIONS.items() if not targets)
FILLABLE = frozenset({_S.ENVOYEE, _S.PARTIELLE})  # the market can still fill it
OPEN = frozenset({_S.VALIDEE, *FILLABLE})  # it still commits cash; the kill switch cancels it
BY_FILL = frozenset({_S.PARTIELLE, _S.EXECUTEE})  # reached by a fill only, never by a request

IncidentKind = Literal[
    "transition_interdite", "ordre_inconnu", "quantite_depassee", "execution_incoherente"
]


class ExecutionIncident(Exception):
    """An incoherence of execution (§9); the caller trips the kill switch (ADR-034).

    The message names orders and states, never an amount: it goes to the journal, while amounts
    stay in the book (ADR-032).
    """

    def __init__(self, kind: IncidentKind, intent_id: UUID | None, message: str) -> None:
        super().__init__(message)
        self.kind: IncidentKind = kind
        self.intent_id = intent_id


def check_move(intent_id: UUID, current: OrderState, target: OrderState) -> None:
    """Refuse a move the table does not allow, or one only a fill can make."""
    if target in BY_FILL or target not in TRANSITIONS[current]:
        why = " : seule une exécution y mène" if target in BY_FILL else ""
        raise ExecutionIncident(
            "transition_interdite",
            intent_id,
            f"ordre {intent_id} : {current} → {target} interdit par la machine à états{why}",
        )
