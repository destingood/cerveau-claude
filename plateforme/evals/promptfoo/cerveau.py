"""promptfoo entry points of CERVEAU's suites (ADR-009): a thin layer over ``core.evals``.

`cerveau eval` starts promptfoo with CERVEAU's own Python (``PROMPTFOO_PYTHON``): the generators
list the cases, the provider runs one case end to end and writes its result for the report, the
assertion hands promptfoo the verdict of the deterministic checks (and of the judge, live).
Live mode needs the campaign that `cerveau eval --live` opens and journals (D8).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

CODE_ROOT = Path(__file__).resolve().parents[2]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))


def _root() -> Path:
    return Path(os.environ.get("CERVEAU_HOME") or CODE_ROOT)


def _tests(suite: str) -> list[dict[str, Any]]:
    from core.evals.cases import cached_cases

    return [
        {
            "description": f"{case.id} — {case.description}",
            "vars": {"case_id": case.id, "suite": suite, "question": case.question},
            "metadata": {"group": case.group, "rules": list(case.rules)},
        }
        for case in cached_cases(suite, _root()).values()  # type: ignore[arg-type]
    ]


def golden_tests(config: Any = None) -> list[dict[str, Any]]:
    return _tests("golden")


def behavior_tests(config: Any = None) -> list[dict[str, Any]]:
    return _tests("behaviors")


def injection_tests(config: Any = None) -> list[dict[str, Any]]:
    return _tests("injection")


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from core.evals.cases import cached_cases
    from core.evals.harness import MANUAL_RUN, MODE_ENV, OUT_ENV, RUN_ENV, run_case, save_result

    variables = context.get("vars") or {}
    mode = os.environ.get(MODE_ENV, "offline")
    if mode not in ("offline", "live"):
        return {"error": f"mode d'éval inconnu : {mode}"}
    if mode == "live" and not os.environ.get("CERVEAU_EVAL_CAMPAIGN"):
        return {"error": "mode réel sans campagne : lancer `cerveau eval --live --campaign` (D8)"}
    root = _root()
    try:
        case = cached_cases(variables["suite"], root)[variables["case_id"]]
    except (KeyError, ValueError) as exc:
        return {"error": f"cas introuvable : {exc}"}
    run = os.environ.get(RUN_ENV, MANUAL_RUN)
    result = asyncio.run(run_case(case, mode, root=root, run=run))  # type: ignore[arg-type]
    out_dir = Path(os.environ.get(OUT_ENV) or root / "var" / "evals" / MANUAL_RUN)
    save_result(result, out_dir)
    response: dict[str, Any] = {
        "output": result.markdown or result.reason(),
        "metadata": {"grading": result.to_promptfoo(), "eval": result.to_json()},
        "tokenUsage": {"total": result.tokens},
    }
    if mode == "live":  # offline costs are estimates: they stay in the report, labelled
        response["cost"] = float(result.cost_eur + result.judge_cost_eur)
    return response


def get_assert(output: str, context: dict[str, Any]) -> dict[str, Any]:
    metadata = context.get("metadata") or {}
    grading = metadata.get("grading")
    if not isinstance(grading, dict):
        return {"pass": False, "score": 0.0, "reason": "aucun résultat de CERVEAU pour ce cas"}
    return grading
