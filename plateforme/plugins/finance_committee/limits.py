"""The deterministic checks of a committee proposal against the paper limits (D21).

The manager proposes in words: no structured order intent comes out of the committee yet (B108),
so no proposal to act can be measured against a size limit. The checks therefore say:

- a limit still at ``A_DEFINIR`` or ``A_VERIFIER`` is unknown and blocks any decision (R7);
- a decision to act is unknown against every limit, since nothing gives its size;
- a decision not to act, or to wait, adds no exposure and respects every defined limit.

Every key of ``PaperRiskLimits`` is checked (B155), even one that a decision not to act cannot
breach (daily loss, drawdown, order rate, price collar): the Risk Gate refuses any order while
one of them is unknown, so a committee that cleared such a decision would promise what the
Gate cannot keep. The daily loss and drawdown limits concern the book as it stands, not the
proposal: the Risk Gate checks them, as it checks a position that already exceeds its limit.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import get_args

from core.committee.engine import LimitChecks
from core.committee.rules import SIZE_PENDING, LimitCheck
from core.committee.schemas import Choice, ManagerDecision
from core.config.loader import Marker, PaperRiskLimits
from core.verification.trace import ToolOutput

LIMITS_FILE = "config/risk_limits.paper.yaml"
CHECKED: tuple[str, ...] = tuple(name for name in PaperRiskLimits.model_fields if name != "allow")
_MARKERS = frozenset(get_args(Marker))
NO_SIZE = SIZE_PENDING  # the drafter lifts this reason once the Risk Gate measures each intent


def check_limit(name: str, value: object, decision: Choice) -> LimitCheck:
    """One limit against one decision; an unknown limit is never assumed."""
    if isinstance(value, str) and value in _MARKERS:
        return LimitCheck(name, None, f"{value} dans {LIMITS_FILE} (R7)")
    if decision == "agir":
        return LimitCheck(name, None, NO_SIZE)
    return LimitCheck(name, True, f"décision « {decision} » : aucune exposition nouvelle")


def paper_limit_checks(limits: PaperRiskLimits) -> LimitChecks:
    """The checks the committee runs on the manager's proposal, before the controller speaks."""

    def checks(decision: ManagerDecision, _outputs: Sequence[ToolOutput]) -> list[LimitCheck]:
        return [check_limit(name, getattr(limits, name), decision.decision) for name in CHECKED]

    return checks
