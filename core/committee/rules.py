"""What the code checks on each committee output, beyond its schema (plan of phase 3, §10).

- every finding cites a tool call or a page of its analyst's own session;
- every argument cites findings that exist, and answers only arguments of earlier rounds;
- the manager treats every argument exactly once, and a figure in an invalidation condition
  comes from a tool output (R1);
- every number and date of every role is traced to its evidence (R1), and no text reads as an
  instruction (R5);
- the controller's verdict starts from the pack's deterministic limit checks: an exceeded or
  unknown limit blocks, and the model may harden the verdict, never soften it (D21).

An error names the field and the rule it breaks, never the value: a value may come from a page
(R5) or hold a pseudonym. Identifiers (``C3``, ``D1.2``) are the code's own and may be named.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from core.committee.schemas import (
    AnalystReport,
    ControllerReport,
    DebateTurn,
    ManagerDecision,
    RoleOutput,
    Verdict,
    text_fields,
)
from core.guardrails.injection import injection_signals
from core.verification.trace import FIGURE_ORIGIN, Evidence, trace

_SOURCE = re.compile(r"^source \[([1-9][0-9]*)\]$")


@dataclass(frozen=True)
class LimitCheck:
    """One deterministic control of the proposal, computed by the pack (D21)."""

    name: str
    ok: bool | None  # None: the limit is unknown (A_DEFINIR) or could not be computed
    reason: str

    def to_payload(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "reason": self.reason}


def call_of(origin: str) -> str:
    """The tool call of an evidence origin (``market_data#1 › cours`` → ``market_data#1``)."""
    return origin.partition(FIGURE_ORIGIN)[0]


def finding_origin(appel: str, calls: Collection[str], sources: Collection[int]) -> str | None:
    """The tool call or the page a finding cites, if its analyst's session has it."""
    appel = appel.strip()
    if appel in calls:
        return appel
    match = _SOURCE.match(appel)
    if match and int(match.group(1)) in sources:
        return f"source [{match.group(1)}]"
    return None


def r1_errors(fields: Iterable[tuple[str, str]], evidence: Evidence) -> list[str]:
    errors: list[str] = []
    for name, text in fields:
        for n, row in enumerate(trace(text, evidence), start=1):
            if row.contrary:
                errors.append(f"{name} : {row.kind} n° {n} de sens contraire à sa source")
            elif not row.traced:
                errors.append(f"{name} : {row.kind} n° {n} qu'aucun outil ni source ne donne")
    return [f"{error} (R1)" for error in errors]


def injection_errors(fields: Iterable[tuple[str, str]]) -> list[str]:
    return [
        f"{name} : formulation d'instruction (R5)"
        for name, text in fields
        if injection_signals(text)
    ]


def _common(output: RoleOutput, evidence: Evidence) -> list[str]:
    fields = text_fields(output)
    return injection_errors(fields) + r1_errors(fields, evidence)


def analyst_errors(
    report: AnalystReport, *, calls: Collection[str], sources: Collection[int], evidence: Evidence
) -> list[str]:
    errors = [
        f"constats[{n}].appel : ni un appel d'outil de ta séance ni une source que tu as lue"
        for n, constat in enumerate(report.constats, start=1)
        if finding_origin(constat.appel, calls, sources) is None
    ]
    return errors + _common(report, evidence)


def debate_errors(
    turn: DebateTurn, *, constats: Collection[str], earlier: Collection[str], evidence: Evidence
) -> list[str]:
    errors: list[str] = []
    for n, argument in enumerate(turn.arguments, start=1):
        unknown = [c for c in argument.constats if c not in constats]
        if unknown:
            errors.append(f"arguments[{n}].constats : {', '.join(unknown)} n'existe pas")
        unanswerable = [a for a in argument.repond_a if a not in earlier]
        if unanswerable:
            errors.append(
                f"arguments[{n}].repond_a : {', '.join(unanswerable)} n'est pas un argument "
                "d'un tour précédent"
            )
    return errors + _common(turn, evidence)


def manager_errors(
    decision: ManagerDecision,
    *,
    arguments: Sequence[str],
    constats: Collection[str],
    calls: Collection[str],
    evidence: Evidence,
) -> list[str]:
    errors: list[str] = []
    treated = [item.id for item in decision.arguments]
    missing = [a for a in arguments if a not in treated]
    if missing:
        errors.append(
            f"arguments : {', '.join(missing)} non traité (retenu ou écarté, avec raison)"
        )
    unknown = sorted({a for a in treated if a not in arguments})
    if unknown:
        errors.append(f"arguments : {', '.join(unknown)} n'existe pas")
    twice = sorted({a for a in treated if treated.count(a) > 1})
    if twice:
        errors.append(f"arguments : {', '.join(twice)} traité plusieurs fois")
    for n, item in enumerate(decision.invalidation, start=1):
        unknown_constats = [c for c in item.constats if c not in constats]
        if unknown_constats:
            errors.append(
                f"invalidation[{n}].constats : {', '.join(unknown_constats)} n'existe pas"
            )
        for k, row in enumerate(trace(item.condition, evidence), start=1):
            if row.kind == "nombre" and row.traced and call_of(row.origin or "") not in calls:
                errors.append(
                    f"invalidation[{n}].condition : seuil n° {k} qui ne vient pas d'une sortie "
                    "d'outil (R1)"
                )
    return errors + _common(decision, evidence)


def controller_errors(
    report: ControllerReport, *, calls: Collection[str], evidence: Evidence
) -> list[str]:
    errors = [
        f"scenarios[{n}].appel : appel d'outil inconnu de cette séance"
        for n, scenario in enumerate(report.scenarios, start=1)
        if scenario.appel is not None and scenario.appel.strip() not in calls
    ]
    return errors + _common(report, evidence)


def final_verdict(
    checks: Sequence[LimitCheck], report: ControllerReport
) -> tuple[Verdict, tuple[str, ...]]:
    """D21: the deterministic checks come first; the model may harden the verdict, not soften it.

    Returns the verdict and the reasons that block it, the code's before the model's.
    """
    reasons: list[str] = []
    if not checks:
        reasons.append("aucun contrôle de limite n'a pu être fait (R7)")
    for check in checks:
        if check.ok is None:
            reasons.append(f"{check.name} : limite inconnue ou non calculée ({check.reason})")
        elif not check.ok:
            reasons.append(f"{check.name} : limite dépassée ({check.reason})")
    if any(scenario.appel is None for scenario in report.scenarios):
        reasons.append("un scénario défavorable n'est chiffré par aucun outil")
    if report.verdict == "BLOQUER":
        reasons.append("le contrôleur de risque bloque")
    return ("BLOQUER" if reasons else "OK"), tuple(reasons)
