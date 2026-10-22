"""Autonomy policy: action class × autonomy level → decision (section 8, Annex C.4).

``decide`` is a pure function of ``autonomy.yaml``: no model, no I/O. The kill switch and the
live configuration are read apart and passed in, so the decision stays reproducible from its
inputs. The engine is never more permissive than the matrix: a cell grants at most what it
says, and only the decisions this phase can carry out are granted, each with an explicit
``effect`` that the caller must read (ADR-030).

The orchestrator and the plugins carry out ``auto`` for ``LECTURE`` in every domain and for
``CALCUL`` in the finance pack, whose computing tools are deterministic, tested and evaluated (R1,
R8, ADR-022), and in the code pack, whose checks run in a networkless, read-only container
(ADR-048, ADR-049): their effect is ``executer``. So is ``EXECUTION_ISOLEE`` in the code pack,
whose agent works on a disposable copy in a container without Internet and returns a patch that
Lucas applies himself (ADR-051). The paper loop alone carries out an
order intent of the finance pack (``decide_order``): ``proposition`` at N1 drafts it, ``paper`` at
N2 sends it to the paper adapter, ``approbation`` at N3 files it for Lucas's approval before it
is sent (ADR-035, ADR-036), and all three need the Risk Gate's answer (R2). ``approbation`` has an
effect for ``FINANCIERE`` alone: ``COMMUNICATION_EXTERNE`` and ``IRREVERSIBLE`` stay refused at
every level (D5). Every other cell, including ``brouillon`` or ``simule``, is refused with its
reason, because no component carries it out. A live configuration that is enabled refuses
everything, since no live adapter exists (R3).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.config.loader import ActionClass, AutonomyConfig, Level, MatrixDecision

if TYPE_CHECKING:
    from core.risk_gate.gate import RiskGateResult

# What phase 2 can carry out. Widening any of these is a phase decision (ADR, evals, Lucas).
PHASE_ACTION_CLASSES: frozenset[ActionClass] = frozenset({"LECTURE"})  # in every domain
# A pack computes only with deterministic tools that are tested and evaluated (R1, R8, ADR-022);
# the code pack's checks run the repository's tools in a sandbox (ADR-048, ADR-049) and its agent
# works in an isolated container whose only output is a patch (ADR-051).
PHASE_DOMAIN_ACTION_CLASSES: Mapping[str, frozenset[ActionClass]] = MappingProxyType(
    {
        "finance": frozenset({"LECTURE", "CALCUL"}),
        "code": frozenset({"LECTURE", "CALCUL", "EXECUTION_ISOLEE"}),
    }
)
# Granted in some domains only: decided once the request is routed to its domain.
ROUTED_ACTION_CLASSES: frozenset[ActionClass] = (
    frozenset[ActionClass]().union(*PHASE_DOMAIN_ACTION_CLASSES.values()) - PHASE_ACTION_CLASSES
)
PHASE_DECISIONS: frozenset[MatrixDecision] = frozenset({"auto"})
# What the paper loop can carry out (ADR-030, ADR-036): an order intent of the finance pack,
# drafted at N1, sent to the paper adapter at N2 and filed for Lucas's approval at N3. The
# orchestrator never carries one out.
ORDER_DOMAIN = "finance"
ORDER_ACTION_CLASSES: frozenset[ActionClass] = frozenset({"FINANCIERE"})
ORDER_DECISIONS: frozenset[MatrixDecision] = frozenset({"proposition", "paper", "approbation"})

KILL_SWITCH_FILE = Path("governance") / "kill_switch" / "KILL"

Effect = Literal["executer", "proposer", "paper", "approbation", "refuser"]
# What a granted cell lets the caller do. A financial action is never executed by the engine:
# at most it waits for an approval. No other class has an effect for ``approbation`` (D5).
_EFFECTS: Mapping[bool, Mapping[MatrixDecision, Effect]] = MappingProxyType(
    {
        False: MappingProxyType({"auto": "executer"}),
        True: MappingProxyType(
            {"proposition": "proposer", "paper": "paper", "approbation": "approbation"}
        ),
    }
)


def _effect(action_class: ActionClass, decision: MatrixDecision) -> Effect | None:
    return _EFFECTS[action_class == "FINANCIERE"].get(decision)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RecordedCheck(_Strict):
    name: str
    ok: bool
    value: str
    limit: str


class RiskGateRecord(_Strict):
    """The ``risk_gate`` block of Annex C.4: the Risk Gate's answer, without its quantities."""

    result: Literal["ACCEPTE", "REFUSE", "REDUIT"]
    checks: tuple[RecordedCheck, ...] = ()


class PolicyDecision(_Strict):
    """Annex C.4. ``risk_gate`` records the Risk Gate's answer to a financial action."""

    request_id: str = Field(min_length=1)
    domain: str
    action_class: ActionClass
    autonomy_level: Level
    decision: MatrixDecision
    risk_gate: RiskGateRecord | None = None
    reasons: tuple[str, ...] = Field(min_length=1)

    @property
    def effect(self) -> Effect:
        """What the caller may do: execute, draft, send to paper, file for approval, or nothing."""
        return _effect(self.action_class, self.decision) or "refuser"

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
    live_enabled: bool,
    action_classes: frozenset[ActionClass] | None = None,
    decisions: frozenset[MatrixDecision] = PHASE_DECISIONS,
    risk_gate: RiskGateResult | None = None,
) -> PolicyDecision:
    """Decision for one action of ``action_class`` in ``domain``.

    The kill switch overrides everything (R4); an unknown domain is refused, and so is every
    action while the live configuration is enabled (R3). Otherwise the matrix cell for the
    domain's current level is granted only when this phase implements the decision and the
    action class in that domain (``action_classes``, by default ``phase_action_classes(domain)``)
    and the decision has an effect for that class. A financial action also needs the Risk Gate's
    answer, recorded in the decision, and is refused when the gate refuses (R2); any other
    action must come without one. Anything else is ``refus``.
    """
    granted = phase_action_classes(domain) if action_classes is None else action_classes
    record = (
        None if risk_gate is None else RiskGateRecord.model_validate(risk_gate.policy_payload())
    )

    def refuse(level: Level, *reasons: str) -> PolicyDecision:
        return PolicyDecision(
            request_id=request_id,
            domain=domain,
            action_class=action_class,
            autonomy_level=level,
            decision="refus",
            risk_gate=record,
            reasons=reasons,
        )

    if kill_switch:
        return refuse("N0", "kill switch engagé (R4) : toute action est refusée, niveau forcé à N0")
    spec = autonomy.domains.get(domain)
    if spec is None:
        return refuse("N0", f"domaine « {domain} » absent de autonomy.yaml : refus")
    level = spec.level
    if live_enabled:
        return refuse(
            level,
            "ALERTE : la configuration live est activée alors qu'aucun adaptateur live n'existe "
            "(R3) : toute action est refusée",
        )
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
    if _effect(action_class, cell) is None:
        return refuse(level, matrix, f"« {cell} » n'a aucun effet pour {action_class} : refus")
    reasons = (matrix,)
    if action_class == "FINANCIERE":
        if record is None:
            return refuse(level, matrix, "la Porte de risque n'a pas été consultée (R2) : refus")
        if record.result == "REFUSE":
            return refuse(level, matrix, "Porte de risque : REFUSE")
        reasons = (matrix, f"Porte de risque : {record.result}")
    elif record is not None:
        return refuse(level, matrix, "Porte de risque consultée pour une action non financière")
    return PolicyDecision(
        request_id=request_id,
        domain=domain,
        action_class=action_class,
        autonomy_level=level,
        decision=cell,
        risk_gate=record,
        reasons=reasons,
    )


def decide_order(
    autonomy: AutonomyConfig,
    *,
    request_id: str,
    kill_switch: bool,
    live_enabled: bool,
    risk_gate: RiskGateResult | None,
) -> PolicyDecision:
    """Decision for one order intent: ``proposer``, ``paper``, ``approbation`` or ``refuser``."""
    return decide(
        autonomy,
        request_id=request_id,
        domain=ORDER_DOMAIN,
        action_class="FINANCIERE",
        kill_switch=kill_switch,
        live_enabled=live_enabled,
        action_classes=ORDER_ACTION_CLASSES,
        decisions=ORDER_DECISIONS,
        risk_gate=risk_gate,
    )
