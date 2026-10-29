"""Approval hooks: Claude Code never enrolls the TOTP secret, never writes the approval store and
never starts the Discord bot or the internal API (D2, D18, D22, ADR-035, ADR-037).
"""

from __future__ import annotations

import pytest

from tests.hooks.hookutil import load_hook

pytestmark = pytest.mark.hooks
guard = load_hook("guard_shell")
paths = load_hook("protect_paths")
c = load_hook("_common")
CWD = c.root_norm()
BOT = f"{CWD}/interfaces/discord_bot"

BLOCKED_BASH = [
    # the approval store
    "echo x > var/approvals/approvals.db",
    "rm var/approvals/approvals.db",
    "mv var/approvals /tmp/a",
    "cp /tmp/x.db var/approvals/approvals.db",
    "sed -i 's/a/b/' var/approvals/approvals.db",
    "cd var/approvals && rm approvals.db",
    # enrolling the TOTP secret, however launched
    "cerveau approvals enroll",
    "uv run cerveau approvals enroll",
    "uv run cerveau approvals ENROLL",
    "uv run --color never cerveau approvals enroll",
    "uv run python -m interfaces.cli.main approvals enroll",
    "uv run -m interfaces.cli.main approvals enroll",
    "python -c 'from core.approvals.totp import enroll; enroll()'",
    "bash -c 'uv run cerveau approvals enroll'",
    "winpty cerveau approvals enroll",
    "c=cerveau; $c approvals enroll",
    # starting the Discord bot
    "node interfaces/discord_bot/index.js",
    "node interfaces/discord_bot",
    "npm --prefix interfaces/discord_bot start",
    "npm --prefix interfaces/discord_bot run start",
    "npm -C interfaces/discord_bot exec discord-bot",
    "cd interfaces/discord_bot && npm start",
    "cd interfaces/discord_bot && node index.js",
    "cd interfaces/discord_bot && node --test index.js",
    "npx node interfaces/discord_bot/index.js",
    "bash -c 'node interfaces/discord_bot/index.js'",
    "uv run node interfaces/discord_bot/index.js",
    "pm2 start interfaces/discord_bot/index.js",
    "nohup node interfaces\\discord_bot\\index.js &",
    # starting the internal API
    "cerveau api serve",
    "uv run cerveau api serve",
    "uv run --color never cerveau api SERVE",
    "uv run python -m interfaces.cli.main api serve",
    "bash -c 'uv run cerveau api serve'",
    "uvicorn --factory interfaces.api:create_app",
    "uv run uvicorn interfaces.api.app:create_app --factory --port 8800",
    "nohup uvicorn x:app &",
    "uvx uvicorn x:app",
    "uv tool run gunicorn x:app",
    "fastapi run interfaces/api/app.py",
    "python -m uvicorn x:app",
    "uv run python -m hypercorn x:app",
    "python -c 'import uvicorn; from interfaces.api import create_app; uvicorn.run(create_app())'",
    "$launcher uvicorn x:app",
]
BLOCKED_POWERSHELL = [
    "Remove-Item var\\approvals\\approvals.db",
    "Set-Content var\\approvals\\approvals.db 'x'",
    "cerveau approvals enroll",
    "& .venv\\Scripts\\cerveau.exe approvals enroll",
    "cmd /c cerveau approvals enroll",
    "Start-Process cerveau -ArgumentList 'approvals','enroll'",
    "& (Get-Command cerveau) approvals enroll",
    "Start-Process node -ArgumentList interfaces\\discord_bot\\index.js",
    "node interfaces\\discord_bot\\index.js",
    "Set-Location interfaces\\discord_bot; npm start",
    "cerveau api serve",
    "Start-Process cerveau -ArgumentList 'api','serve'",
    "Start-Process uvicorn -ArgumentList 'x:app'",
    "& .venv\\Scripts\\uvicorn.exe x:app",
]
ALLOWED_BASH = [
    "cat var/approvals/approvals.db",
    "ls var/approvals",
    "uv run cerveau approvals list",
    "uv run pytest tests/test_approvals_store.py -k enroll",
    "grep -n enroll core/approvals/totp.py",
    "git commit -m 'feat: enroll guard'",
    "node --test interfaces/discord_bot/test",
    "npm --prefix interfaces/discord_bot test",
    "npm --prefix interfaces/discord_bot run test",
    "npm --prefix interfaces/discord_bot ci",
    "npm --prefix interfaces/discord_bot ls",
    "npm --prefix interfaces/discord_bot audit",
    "cd interfaces/discord_bot && npm ci && npm test",
    "cd interfaces/discord_bot && node --test",
    "grep -n node interfaces/discord_bot/index.js",
    "git add interfaces/discord_bot/index.js",
    "npx promptfoo eval",
    "uv add uvicorn==0.54.0",
    "uv lock --upgrade-package fastapi",
    "uv run pip-audit",
    "grep -n uvicorn uv.lock",
    "uv run pytest tests/test_api.py -k serve",
    "uv run cerveau api --help",
    "uv run ruff check interfaces/api",
    "git add interfaces/api/app.py interfaces/cli/api.py",
    "python -c 'import fastapi; print(fastapi.__version__)'",
]
ALLOWED_POWERSHELL = [
    "Get-Content var\\approvals\\approvals.db",
    "Select-String -Pattern uvicorn uv.lock",
    "Set-Location interfaces\\discord_bot; npm test",
    "node --test interfaces\\discord_bot\\test",
]


@pytest.mark.parametrize(
    ("command", "powershell"),
    [(cmd, False) for cmd in BLOCKED_BASH] + [(cmd, True) for cmd in BLOCKED_POWERSHELL],
)
def test_store_enrollment_and_bot_launch_are_refused(command: str, powershell: bool) -> None:
    assert guard.analyse(command, powershell, CWD), f"aurait dû être refusé : {command!r}"


@pytest.mark.parametrize(
    ("command", "powershell"),
    [(cmd, False) for cmd in ALLOWED_BASH] + [(cmd, True) for cmd in ALLOWED_POWERSHELL],
)
def test_reading_testing_and_installing_stay_allowed(command: str, powershell: bool) -> None:
    reason = guard.analyse(command, powershell, CWD)
    assert reason is None, f"refusé à tort : {command!r} → {reason}"


def test_refusals_name_their_rule() -> None:
    enroll = guard.analyse("uv run cerveau approvals enroll", False, CWD)
    assert enroll and "D2" in enroll and "utilisateur" in enroll
    bot = guard.analyse("node interfaces/discord_bot/index.js", False, CWD)
    assert bot and "D22" in bot and "utilisateur" in bot
    rearm = guard.analyse("uv run cerveau rearm", False, CWD)
    assert rearm and "R4" in rearm
    for api in ("uv run cerveau api serve", "uv run uvicorn x:app"):
        reason = guard.analyse(api, False, CWD)
        assert reason and "D22" in reason and "API" in reason


def test_standing_in_the_bot_folder_counts() -> None:
    assert guard.analyse("npm start", False, BOT)
    assert guard.analyse("node index.js", False, BOT)
    assert guard.analyse("npm test", False, BOT) is None


def test_an_unknown_folder_counts_as_the_bot_folder() -> None:
    reason = guard.analyse("npm start", False, None)
    assert reason and "D22" in reason


@pytest.mark.parametrize("tool", ["Edit", "Write", "NotebookEdit"])
def test_approval_store_is_write_protected(tool: str) -> None:
    _, reason = paths.decide({"file_path": "var/approvals/approvals.db"}, CWD, tool)
    assert reason and "D18" in reason
