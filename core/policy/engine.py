"""Autonomy policy: action class × autonomy level → decision (section 8, Annex C.4).

``decide`` is a pure function of ``autonomy.yaml``: no model, no I/O. The kill switch is read
apart (``kill_switch_engaged``) and passed in, so the decision stays reproducible from its
inputs. The engine is never more permissive than the matrix: a cell grants at most what it
says, and only the decisions this phase can carry out are granted. In phase 2 that is ``auto``
for ``LECTURE`` in every domain and for ``CALCUL`` in the finance pack alone, whose computing
tools are deterministic, tested and evaluated (R1, R8, ADR-022); every other cell, including
``brouillon`` or ``proposition``, is refused with its reason, because no component can yet draft,
simulate or ask for an approval.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.config.loader import ActionClass, AutonomyConfig, Level, MatrixDecision

# What phase 2 can carry out. Widening any of these is a phase decision (ADR, evals, Lucas).
PHASE_ACTION_CLASSES: frozenset[ActionClass] = frozenset({"LECTURE"})  # in every domain
# A pack computes only with deterministic tools that are tested and evaluated (R1, R8, ADR-022).
PHASE_DOMAIN_ACTION_CLASSES: Mapping[str, frozenset[ActionClass]] = MappingProxyType(
    {"finance": frozenset({"LECTURE", "CALCUL"})}
)
# Granted in some domains only: decided once the request is routed to its domain.
ROUTED_ACTION_CLASSES: frozenset[ActionClass] = (
    frozenset[ActionClass]().union(*PHASE_DOMAIN_ACTION_CLASSES.values()) - PHASE_ACTION_CLASSES
)
PHASE_DECISIONS: frozenset[MatrixDecision] = frozenset({"auto"})

KILL_SWITCH_FILE = Path("governance") / "kill_switch" / "KILL"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RiskCheck(_Strict):
    name: str
    ok: bool
    value: str
    limit: str


class RiskGateResult(_Strict):
    result: Literal["ACCEPTE", "REFUSE", "REDUIT"]
    checks: tuple[RiskCheck, ...] = ()


class PolicyDecision(_Strict):
    """Annex C.4. ``risk_gate`` stays empty until the finance risk gate exists."""

    request_id: str = Field(min_length=1)
    domain: str
    action_class: ActionClass
    autonomy_level: Level
    decision: MatrixDecision
    risk_gate: RiskGateResult | None = None
    reasons: tuple[str, ...] = Field(min_length=1)

    @property
    def allowed(self) -> bool:
        return self.decision == "auto"

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def phase_action_classes(domain: str) -> frozenset[ActionClass]:
    """The action classes this phase can carry out in ``domain``."""
    return PHASE_DOMAIN_ACTION_CLASSES.get(domain, PHASE_ACTION_CLASSES)


def kill_switch_engaged(project_root: Path) -> bool:
    """True when ``governance/kill_switch/KILL`` exists, or when that cannot be known (R4)."""
    path = project_root / KILL_SWITCH_FILE
    try:
        return path.exists() or path.is_symlink()
    except OSError:
        return True


def decide(
    autonomy: AutonomyConfig,
    *,
    request_id: str,
    domain: str,
    action_class: ActionClass,
    kill_switch: bool,
    action_classes: frozenset[ActionClass] | None = None,
    decisions: frozenset[MatrixDecision] = PHASE_DECISIONS,
) -> PolicyDecision:
    """Decision for one action of ``action_class`` in ``domain``.

    The kill switch overrides everything (R4); an unknown domain is refused; otherwise the
    matrix cell for the domain's current level is granted only when this phase implements both
    the decision and the action class in that domain (``action_classes``, by default
    ``phase_action_classes(domain)``). Anything else is ``refus``.
    """
    granted = phase_action_classes(domain) if action_classes is None else action_classes

    def refuse(level: Level, *reasons: str) -> PolicyDecision:
        return PolicyDecision(
            request_id=request_id,
            domain=domain,
            action_class=action_class,
            autonomy_level=level,
            decision="refus",
            reasons=reasons,
        )

    if kill_switch:
        return refuse("N0", "kill switch engagé (R4) : toute action est refusée, niveau forcé à N0")
    spec = autonomy.domains.get(domain)
    if spec is None:
        return refuse("N0", f"domaine « {domain} » absent de autonomy.yaml : refus")
    level = spec.level
    cell = autonomy.matrix[action_class][level]
    matrix = f"matrice {action_class} × {level} : {cell}"
    if cell == "refus":
        return refuse(level, matrix)
    if cell not in decisions:
        return refuse(level, matrix, f"« {cell} » n'est pas encore mis en œuvre : refus")
    if action_class not in granted:
        return refuse(
            level,
            matrix,
            f"aucune capacité {action_class} pour le domaine « {domain} » dans cette phase : refus",
        )
    return PolicyDecision(
        request_id=request_id,
        domain=domain,
        action_class=action_class,
        autonomy_level=level,
        decision=cell,
        reasons=(matrix,),
    )
