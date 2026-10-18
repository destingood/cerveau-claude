"""`cerveau eval`: the promptfoo suites, offline by default, live only for an agreed campaign (D8).

An offline run inherits no API key, so nothing in it can reach a paid service. A live run goes
one request at a time, each checked against the € budgets by the orchestrator, and journals the
campaign it belongs to; Lucas agrees to each campaign beforehand (D8).
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

PROMPTFOO = "promptfoo@0.124.1"
SUITES_DIR = Path("evals") / "promptfoo"
RUNS_DIR = Path("var") / "evals"  # raw promptfoo results, ignored by git
CAMPAIGN = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")
API_KEYS = ("ANTHROPIC_API_KEY", "BRAVE_SEARCH_API_KEY")
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


def child_env(
    mode: Mode, root: Path, base: Mapping[str, str], campaign: str | None = None
) -> dict[str, str]:
    """The environment of promptfoo and of the Python provider it starts."""
    env = dict(base)
    if mode == "offline":  # the keys stay out of reach, whatever a suite asks for
        for name in [*API_KEYS, *(n for n in env if n.upper().startswith("LANGFUSE_"))]:
            env.pop(name, None)
    env.pop("CERVEAU_EVAL_CAMPAIGN", None)
    env.update(
        {
            "CERVEAU_HOME": str(root),
            "CERVEAU_EVAL_MODE": mode,
            "PROMPTFOO_PYTHON": sys.executable,  # the provider runs in CERVEAU's environment
            "PROMPTFOO_DISABLE_TELEMETRY": "1",
            "PROMPTFOO_DISABLE_UPDATE": "1",
        }
    )
    if campaign is not None:
        env["CERVEAU_EVAL_CAMPAIGN"] = campaign
    return env


def promptfoo_command(npx: str, suite: Path, output: Path, mode: Mode) -> list[str]:
    command = [npx, "-y", PROMPTFOO, "eval", "-c", str(suite), "-o", str(output)]
    command += ["--no-cache", "--no-write", "--no-table", "--no-progress-bar"]
    if mode == "live":  # one request at a time, each checked against the budgets first
        command += ["-j", "1"]
    return command


def run_suite(command: Sequence[str], *, env: Mapping[str, str], cwd: Path) -> int:
    return subprocess.run(list(command), env=dict(env), cwd=cwd, check=False).returncode  # noqa: S603
