"""The offline world of the code pack's evals: the case's repository, a fake Docker, a fake GitHub.

The three code servers run for real on them. The repository « projet » is a throwaway git
repository built in the run's temporary home, with no user nor system configuration and fixed
dates. run_checks gets, instead of a container, the output the case gives for each step, in the
shape ruff 0.17 and pytest write it; ci_runs gets, instead of a request, runs shaped like the
documented answer of ``GET /repos/{owner}/{repo}/actions/runs`` (no network, no container).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.code.git import GitRunner
from core.code.process import Bounded, run_bounded
from core.config.loader import CodeChecks, CodeRepository
from core.evals.cases import REPO_ROOT, CodeChecksFixture, CodeFixture, CodeRunFixture
from plugins.code_checks.server import Settings
from plugins.code_ci.github import CiError, Rate, refusal

CODE_REPO = "projet"
CERVEAU_ID = "cerveau"
JETON_MARK = "«JETON_FICTIF»"
KEY_MARK = "«CLE_PRIVEE»"
# Built from parts: no token-looking text nor key block sits in the repository (R6, gitleaks).
FICTITIOUS_TOKEN = "ghp_" + "Z9y8X7w6V5u4T3s2R1q0" * 2
FICTITIOUS_KEY = "\n".join(
    ("-----BEGIN " + "OPENSSH PRIVATE KEY-----", "A" * 64, "-----END " + "OPENSSH PRIVATE KEY-----")
)
IMAGE = "sha256:" + "c" * 64
REPO_IMAGE = "sha256:" + "d" * 64
CHECK_LIMITS = {"image": IMAGE, "cpus": 2, "memory_mb": 2048, "pids": 256, "timeout_seconds": 300}
NO_DOCKER = 125  # docker run's own failure: the daemon does not answer
IDENTITY = (
    "-c",
    "user.name=Lucas Test",
    "-c",
    "user.email=lucas@example.test",
    "-c",
    "commit.gpgsign=false",
)
FIRST_COMMIT = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)  # one hour apart, before FIXTURE_NOW
LAST_RUN = datetime(2026, 10, 17, 18, 0, tzinfo=UTC)
GIT_OUTPUT_BYTES = 1 << 20


class FixtureError(RuntimeError):
    """The case's repository could not be built: a fixture fault, not a result."""


def filled(text: str) -> str:
    """The fictitious secrets the markers stand for."""
    return text.replace(JETON_MARK, FICTITIOUS_TOKEN).replace(KEY_MARK, FICTITIOUS_KEY)


def _git(runner: GitRunner, repo: Path, *args: str, stdin: bytes | None = None) -> str:
    command = [*runner.executable, "-C", str(repo), *args]
    out = run_bounded(
        command, env=runner.env, timeout_s=runner.timeout_s, max_bytes=GIT_OUTPUT_BYTES, stdin=stdin
    )
    if out.returncode != 0 or out.timed_out:
        raise FixtureError(f"git {args[0]} : {out.stderr.strip()[:300]}")
    return out.stdout.decode("utf-8")


def build_repo(fixture: CodeFixture, path: Path) -> Path:
    """The case's commits, in order, in a new repository at ``path`` (branch main)."""
    runner = GitRunner(("git", *IDENTITY))
    path.mkdir(parents=True)
    _git(runner, path, "init", "-q", "-b", "main")
    for number, commit in enumerate(fixture.commits):
        for name, content in commit.files.items():
            if content is None:
                _git(runner, path, "rm", "-q", "--", name)
                continue
            target = path.joinpath(*name.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(filled(content).encode("utf-8"))
            _git(runner, path, "add", "--", name)
        for name, target in commit.links.items():
            blob = _git(runner, path, "hash-object", "-w", "--stdin", stdin=target.encode())
            entry = f"120000,{blob.strip()},{name}"
            _git(runner, path, "update-index", "--add", "--cacheinfo", entry)
        stamp = (FIRST_COMMIT + timedelta(hours=number)).isoformat()
        runner.env.update(GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
        _git(runner, path, "commit", "-q", "--allow-empty", "-m", filled(commit.message))
    return path


def code_repositories(fixture: CodeFixture | None, repo: Path) -> tuple[CodeRepository, ...]:
    """The allow-list of the case: « projet » alone, or with CERVEAU's own repository."""
    if fixture is None:
        return ()
    listed = [
        CodeRepository.model_validate(
            {
                "id": CODE_REPO,
                "path": str(repo),
                "github": fixture.github,
                "pytest": fixture.pytest,
                "image": REPO_IMAGE if fixture.pytest else None,
            }
        )
    ]
    if fixture.cerveau:
        listed.append(CodeRepository.model_validate({"id": CERVEAU_ID, "path": str(REPO_ROOT)}))
    return tuple(listed)


def check_settings(repositories: Sequence[CodeRepository]) -> Settings:
    return Settings(tuple(repositories), CodeChecks.model_validate(CHECK_LIMITS))


def _ruff_item(path: str, code: str | None, message: str, row: int, column: int) -> object:
    return {
        "cell": None,
        "code": code,
        "end_location": {"column": column + 1, "row": row},
        "filename": f"/work/{path}",
        "fix": None,
        "location": {"column": column, "row": row},
        "message": filled(message),
        "name": "rule",
        "noqa_row": row,
        "severity": "error",
        "url": None,
    }


def _ruff(items: list[object]) -> Bounded:
    return Bounded(1 if items else 0, json.dumps(items).encode("utf-8"), "", False, False)


def step_of(arguments: Sequence[str]) -> str:
    """``check``, ``format`` or ``pytest``, from ``--entrypoint PROGRAM IMAGE ARGUMENTS``."""
    at = list(arguments).index("--entrypoint")
    return "pytest" if arguments[at + 1] == "python" else arguments[at + 3]


@dataclass
class FixtureDocker:
    """The containers of run_checks, answering as the case says; none is started."""

    checks: CodeChecksFixture | None
    steps: list[str] = field(default_factory=list)

    def run(
        self, arguments: Sequence[str], *, name: str, timeout_s: float, max_bytes: int
    ) -> Bounded:
        step = step_of(arguments)
        self.steps.append(step)
        checks = self.checks
        if checks is None or checks.docker is not None:
            code = NO_DOCKER if checks is None or checks.docker is None else checks.docker
            return Bounded(code, b"", "Cannot connect to the Docker daemon", False, False)
        if step in checks.timed_out:
            return Bounded(-9, b"", "", False, True)
        if step == "check":
            return _ruff(
                [_ruff_item(i.path, i.code, i.message, i.row, i.column) for i in checks.lint]
            )
        if step == "format":
            return _ruff(
                [
                    _ruff_item(path, "unformatted", "File would be reformatted", 1, 1)
                    for path in checks.unformatted
                ]
            )
        return Bounded(
            checks.pytest_code, filled(checks.pytest_output).encode("utf-8"), "", False, False
        )


def _run(run: CodeRunFixture, number: int, index: int, github: str) -> dict[str, object]:
    created = LAST_RUN - timedelta(hours=index)
    sha = hashlib.sha1(f"{github}:{number}".encode(), usedforsecurity=False).hexdigest()
    return {
        "id": 9_000 + number,
        "name": run.workflow,
        "head_branch": run.branch,
        "head_sha": sha,
        "display_title": filled(run.title),
        "run_number": number,
        "event": run.event,
        "status": run.status,
        "conclusion": run.conclusion,
        "html_url": f"https://github.com/{github}/actions/runs/{9_000 + number}",
        "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_at": (created + timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_attempt": 1,
    }


@dataclass
class FixtureGitHub:
    """The runs of the case, newest first, as the API lists them; no request leaves."""

    fixture: CodeFixture | None
    asked: list[tuple[str, str | None, int]] = field(default_factory=list)

    async def runs(
        self, github: str, branch: str | None, per_page: int
    ) -> tuple[bytes, Rate | None]:
        self.asked.append((github, branch, per_page))
        fixture = self.fixture
        if fixture is None or fixture.ci_status == 404:
            raise CiError(refusal(404, github, None, 0.0))
        if fixture.ci_status != 200:
            raise CiError(refusal(fixture.ci_status, github, None, 0.0))
        count = len(fixture.runs)
        numbered = [(count - index, index, run) for index, run in enumerate(fixture.runs)]
        kept = [item for item in numbered if branch is None or item[2].branch == branch]
        total = len(kept)
        if branch is None and fixture.total_runs is not None:
            total = fixture.total_runs
        body = {
            "total_count": total,
            "workflow_runs": [_run(run, n, i, github) for n, i, run in kept[:per_page]],
        }
        return json.dumps(body).encode("utf-8"), None
