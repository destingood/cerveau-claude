"""Autonomy policy engine over the action class × level matrix (section 8)."""

from core.policy.engine import (
    KILL_SWITCH_FILE,
    PHASE_ACTION_CLASSES,
    PHASE_DECISIONS,
    PHASE_DOMAIN_ACTION_CLASSES,
    ROUTED_ACTION_CLASSES,
    PolicyDecision,
    RiskCheck,
    RiskGateResult,
    decide,
    kill_switch_engaged,
    phase_action_classes,
)

__all__ = [
    "KILL_SWITCH_FILE",
    "PHASE_ACTION_CLASSES",
    "PHASE_DECISIONS",
    "PHASE_DOMAIN_ACTION_CLASSES",
    "ROUTED_ACTION_CLASSES",
    "PolicyDecision",
    "RiskCheck",
    "RiskGateResult",
    "decide",
    "kill_switch_engaged",
    "phase_action_classes",
]
