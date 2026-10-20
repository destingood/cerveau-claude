"""The deterministic checks of a committee proposal against the paper limits (D21).

In phase 3 the manager proposes in words: no structured order intent exists yet (B108, phase 4),
so no proposal to act can be measured against a size limit. The checks therefore say:

- a limit still at ``A_DEFINIR`` or ``A_VERIFIER`` is unknown and blocks any decision (R7);
- a decision to act is unknown against every limit, since nothing gives its size;
- a decision not to act, or to wait, adds no exposure and respects every defined limit.

The capital of reference comes first: the percentage limits are fractions of it. The daily loss
and drawdown limits concern the book as it stands, not the proposal: the Risk Gate checks them in
phase 4, as it will check a position that already exceeds its limit before any decision.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import get_args

from core.committee.engine import LimitChecks
from core.committee.rules import LimitCheck
from core.committee.schemas import Choice, ManagerDecision
from core.config.loader import Marker, PaperRiskLimits
from core.verification.trace import ToolOutput

LIMITS_FILE = "config/risk_limits.paper.yaml"
CHECKED: tuple[str, ...] = (
    "capital_reference_eur",
    "max_order_pct",
    "max_position_pct",
    "max_sector_pct",
)
_MARKERS = frozenset(get_args(Marker))
NO_SIZE = "proposition sans ordre chiffré : la taille s'évaluera sur l'intention structurée (B108)"


def check_limit(name: str, value: float | str, decision: Choice) -> LimitCheck:
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
