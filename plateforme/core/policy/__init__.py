"""Autonomy policy engine over the action class × level matrix (section 8)."""

from core.policy.engine import (
    KILL_SWITCH_FILE,
    ORDER_ACTION_CLASSES,
    ORDER_DECISIONS,
    ORDER_DOMAIN,
    PHASE_ACTION_CLASSES,
    PHASE_DECISIONS,
    PHASE_DOMAIN_ACTION_CLASSES,
    ROUTED_ACTION_CLASSES,
    Effect,
    PolicyDecision,
    RecordedCheck,
    RiskGateRecord,
    decide,
    decide_order,
    kill_switch_engaged,
    phase_action_classes,
)

__all__ = [
    "KILL_SWITCH_FILE",
    "ORDER_ACTION_CLASSES",
    "ORDER_DECISIONS",
    "ORDER_DOMAIN",
    "PHASE_ACTION_CLASSES",
    "PHASE_DECISIONS",
    "PHASE_DOMAIN_ACTION_CLASSES",
    "ROUTED_ACTION_CLASSES",
    "Effect",
    "PolicyDecision",
    "RecordedCheck",
    "RiskGateRecord",
    "decide",
    "decide_order",
    "kill_switch_engaged",
    "phase_action_classes",
]
