"""The champion / challenger gate (ADR-011, ADR-065): deterministic, no model (R1).

Two eval reports of the same cases are compared: the champion's (the learned layer in service)
and the challenger's (the same layer with one proposed change). The gate never changes a
threshold nor a golden set (R9); it only reads the reports.

- **Held-out set**: a fixed share of the golden cases, chosen by hash of the case identifier, that
  learning never sees (``training_results`` leaves them out). The quality comparison is made on it
  alone, against Goodhart's law (ADR-011).
- **Rejected** whatever the thresholds: a case missing or in error in the challenger's report, a
  behaviour or red-team case the champion passed and the challenger fails, more R5 breaches, or
  fewer held-out cases passed.
- **Promotable** only with the thresholds set (``config/evals.yaml › learning``: margin and
  minimum held-out size) and two live reports (D4): offline, the scripted models do not read the
  learned layer, so their verdict proves the mechanism, never a gain.
- Otherwise **inconclusive**, with the reason.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

GOLDEN = "golden"
LEARNING_EVENT = "LEARNING"
Status = Literal["rejete", "promouvable", "non_conclu"]
CaseKey = tuple[str, str]  # (suite, case)


class GateError(ValueError):
    """The reports cannot be compared."""


def held_out(case_id: str, percent: int) -> bool:
    """Whether a golden case belongs to the held-out set: stable, independent of the case order."""
    if not 0 <= percent <= 100:
        raise GateError("part tenue à l'écart hors de [0, 100]")
    bucket = int.from_bytes(hashlib.sha256(f"holdout\0{case_id}".encode()).digest()[:8]) % 100
    return bucket < percent


@dataclass(frozen=True)
class Result:
    passed: bool
    score: float
    r5_breaches: int
    error: bool


@dataclass(frozen=True)
class HeldOut:
    cases: int
    champion_passed: int
    challenger_passed: int
    champion_mean: float
    challenger_mean: float


@dataclass(frozen=True)
class Verdict:
    status: Status
    reasons: tuple[str, ...]
    held_out: HeldOut
    regressions: tuple[CaseKey, ...]  # behaviour and red-team cases lost by the challenger
    champion_r5: int
    challenger_r5: int


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _result(raw: Mapping[str, Any]) -> Result:
    score = raw.get("score")
    if isinstance(score, bool) or not isinstance(score, int | float) or not math.isfinite(score):
        score = 0.0
    error = raw.get("error") is not None
    return Result(
        passed=raw.get("passed") is True and not error,
        score=min(max(float(score), 0.0), 1.0) if not error else 0.0,
        r5_breaches=_int(raw.get("r5_breaches")),
        error=error,
    )


def results(report: Mapping[str, Any]) -> dict[CaseKey, Result]:
    """The report's results by (suite, case); a duplicated case makes the report unusable."""
    found: dict[CaseKey, Result] = {}
    for raw in report.get("results") or ():
        if not isinstance(raw, Mapping):
            raise GateError("résultat illisible dans le rapport")
        key = (str(raw.get("suite")), str(raw.get("case")))
        if key in found:
            raise GateError(f"cas en double dans le rapport : {key[0]}/{key[1]}")
        found[key] = _result(raw)
    if not found:
        raise GateError("rapport sans résultat")
    return found


def training_results(
    report: Mapping[str, Any], percent: int
) -> Iterable[tuple[CaseKey, Mapping[str, Any]]]:
    """The results learning may look at: every case but the held-out golden ones."""
    for raw in report.get("results") or ():
        if isinstance(raw, Mapping):
            key = (str(raw.get("suite")), str(raw.get("case")))
            if not (key[0] == GOLDEN and held_out(key[1], percent)):
                yield key, raw


def _mean(values: list[float]) -> float:
    return math.fsum(values) / len(values) if values else 0.0


def compare(
    champion: Mapping[str, Any],
    challenger: Mapping[str, Any],
    *,
    holdout_percent: int,
    margin: float | None,
    min_cases: int | None,
) -> Verdict:
    """The gate's verdict on the challenger's report against the champion's."""
    ours, theirs = results(champion), results(challenger)
    reasons: list[str] = []
    missing = sorted(key for key in ours if key not in theirs or theirs[key].error)
    if extra := sorted(key for key in theirs if key not in ours):
        raise GateError(f"le challenger a {len(extra)} cas absents du rapport du champion")
    if missing:
        reasons.append(f"{len(missing)} cas absent(s) ou en erreur chez le challenger")
    regressions = tuple(
        key
        for key in sorted(ours)
        if key[0] != GOLDEN and ours[key].passed and not (key in theirs and theirs[key].passed)
    )
    if regressions:
        reasons.append(f"{len(regressions)} cas de comportement ou de red team perdu(s)")
    r5_champion = sum(r.r5_breaches for r in ours.values())
    r5_challenger = sum(r.r5_breaches for r in theirs.values())
    if r5_challenger > r5_champion:
        reasons.append(f"violations R5 : {r5_challenger} contre {r5_champion}")
    keys = [k for k in sorted(ours) if k[0] == GOLDEN and held_out(k[1], holdout_percent)]
    lost = Result(passed=False, score=0.0, r5_breaches=0, error=True)
    held = HeldOut(
        cases=len(keys),
        champion_passed=sum(ours[k].passed for k in keys),
        challenger_passed=sum(theirs.get(k, lost).passed for k in keys),
        champion_mean=_mean([ours[k].score for k in keys]),
        challenger_mean=_mean([theirs.get(k, lost).score for k in keys]),
    )
    if held.challenger_passed < held.champion_passed:
        reasons.append(
            f"jeu tenu à l'écart : {held.challenger_passed} cas réussis contre "
            f"{held.champion_passed}"
        )
    if reasons:
        return Verdict("rejete", tuple(reasons), held, regressions, r5_champion, r5_challenger)
    if margin is None or min_cases is None:
        reasons.append("seuils de la porte à définir (R7) : aucune mise en ligne")
    elif held.cases < min_cases:
        reasons.append(f"jeu tenu à l'écart trop petit : {held.cases} cas, {min_cases} requis")
    elif held.challenger_mean < held.champion_mean + margin:
        reasons.append(
            f"gain insuffisant sur le jeu tenu à l'écart : {held.challenger_mean:.4f} contre "
            f"{held.champion_mean:.4f} + {margin}"
        )
    modes = {champion.get("mode"), challenger.get("mode")}
    if modes != {"live"}:
        reasons.append("évals hors ligne : verdict sans mise en ligne (D4)")
    status: Status = "non_conclu" if reasons else "promouvable"
    return Verdict(status, tuple(reasons), held, regressions, r5_champion, r5_challenger)
