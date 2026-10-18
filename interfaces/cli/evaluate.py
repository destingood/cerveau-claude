"""`cerveau eval`: the promptfoo suites, offline by default, live only for an agreed campaign (D8).

An offline run inherits no API key, so nothing in it can reach a paid service. A live run goes
one request at a time, each checked against the € budgets by the orchestrator, and journals the
campaign it belongs to; Lucas agrees to each campaign beforehand (D8).
"""

from __future__ import annotations

import re
import subprocess
import sys
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

PROMPTFOO = "promptfoo@0.124.1"
SUITES_DIR = Path("evals") / "promptfoo"
RUNS_DIR = Path("var") / "evals"  # raw promptfoo results, ignored by git
REPORT_NAME = "report"  # <run dir>/report.md and report.json
CAMPAIGN = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")
API_KEYS = ("ANTHROPIC_API_KEY", "BRAVE_SEARCH_API_KEY")
# The variables that core/evals/harness.py reads; a test keeps both sides in step.
OUT_ENV, RUN_ENV, CONFIG_ENV = "CERVEAU_EVAL_OUT", "CERVEAU_EVAL_RUN", "CERVEAU_EVAL_CONFIG"
FAILED_TESTS_EXIT = 100  # PROMPTFOO_FAILED_TEST_EXIT_CODE: a case failed, the run went through
Mode = Literal["offline", "live"]


class EvalUsageError(ValueError):
    """The command line asks for something the eval harness refuses."""


def find_suites(root: Path, names: Sequence[str]) -> list[Path]:
    """The suites named on the command line, or every suite of ``evals/promptfoo``."""
    available = {path.stem: path for path in sorted((root / SUITES_DIR).glob("*.yaml"))}
    unknown = [name for name in names if name not in available]
    if unknown:
        raise EvalUsageError(
            f"suite(s) inconnue(s) : {', '.join(unknown)} ; "
            f"disponibles : {', '.join(available) or 'aucune'}"
        )
    return [available[name] for name in dict.fromkeys(names)] or list(available.values())


def check_campaign(campaign: str | None, names: Sequence[str]) -> str:
    """A live run names its campaign and its suites: no paid run by default (D8)."""
    if campaign is None or not CAMPAIGN.fullmatch(campaign):
        raise EvalUsageError(
            "--live exige --campaign <nom> (a-z, 0-9, tirets, 3 à 64 caractères), "
            "le nom de la campagne acceptée par Lucas (D8)"
        )
    if not names:
        raise EvalUsageError("--live exige la liste des suites de la campagne")
    return campaign


def new_run_id(now: datetime) -> str:
    """The run the case results belong to: the report ignores the results of older runs."""
    return f"{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


def is_measured(suite: Path) -> bool:
    """A suite of CERVEAU (golden, behaviours, injection), as opposed to the witness test."""
    from core.evals.cases import SUITES  # trafilatura and spaCy load only for `eval`

    return suite.stem in SUITES


def accepted_codes(suite: Path) -> frozenset[int]:
    """promptfoo exit codes of a run that went through: the report's gates judge the cases."""
    return frozenset({0, FAILED_TESTS_EXIT}) if is_measured(suite) else frozenset({0})


def child_env(
    mode: Mode,
    root: Path,
    base: Mapping[str, str],
    campaign: str | None = None,
    *,
    out_dir: Path | None = None,
    run: str | None = None,
    config_dir: Path | None = None,
) -> dict[str, str]:
    """The environment of promptfoo and of the Python provider it starts."""
    env = dict(base)
    if mode == "offline":  # the keys stay out of reach, whatever a suite asks for
        for name in [*API_KEYS, *(n for n in env if n.upper().startswith("LANGFUSE_"))]:
            env.pop(name, None)
    for name in ("CERVEAU_EVAL_CAMPAIGN", OUT_ENV, RUN_ENV, CONFIG_ENV):
        env.pop(name, None)
    env.update(
        {
            "CERVEAU_HOME": str(root),
            "CERVEAU_EVAL_MODE": mode,
            "PROMPTFOO_PYTHON": sys.executable,  # the provider runs in CERVEAU's environment
            "PROMPTFOO_DISABLE_TELEMETRY": "1",
            "PROMPTFOO_DISABLE_UPDATE": "1",
            "PROMPTFOO_FAILED_TEST_EXIT_CODE": str(FAILED_TESTS_EXIT),
        }
    )
    if campaign is not None:
        env["CERVEAU_EVAL_CAMPAIGN"] = campaign
    if out_dir is not None:
        env[OUT_ENV] = str(out_dir)
    if run is not None:
        env[RUN_ENV] = run
    if mode == "live" and config_dir is not None:
        env[CONFIG_ENV] = str(config_dir)
    return env


def promptfoo_command(npx: str, suite: Path, output: Path, mode: Mode) -> list[str]:
    command = [npx, "-y", PROMPTFOO, "eval", "-c", str(suite), "-o", str(output)]
    command += ["--no-cache", "--no-write", "--no-table", "--no-progress-bar"]
    if mode == "live":  # one request at a time, each checked against the budgets first
        command += ["-j", "1"]
    return command


def run_suite(command: Sequence[str], *, env: Mapping[str, str], cwd: Path) -> int:
    return subprocess.run(list(command), env=dict(env), cwd=cwd, check=False).returncode  # noqa: S603
