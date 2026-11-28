"""B228: Claude Code never reads the value of a secret of the interfaces.

Part A: `guard_shell` refuses every command that would print or read the value of one of the
secrets listed in `config/interfaces.yaml` (whole-environment dumps, expansions, the env: drive,
the registry, /proc/*/environ, inline interpreter code), and still lets their names be written as
plain text. Part B: the settings Claude Code reads for this repository blank the approval-chain
secrets for every process it starts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.audit import verify
from tests.conftest import REPO_ROOT
from tests.hooks.hookutil import load_hook, run_hook

pytestmark = pytest.mark.hooks
guard = load_hook("guard_shell")
secrets = load_hook("_env_secrets")
c = load_hook("_common")
CWD = c.root_norm()
SETTINGS = (REPO_ROOT / ".claude" / "settings.json", REPO_ROOT.parent / ".claude" / "settings.json")

BLOCKED_BASH = [
    # whole-environment dumps
    "printenv",
    "printenv -0",
    "printenv | grep CERVEAU",
    "env",
    "env | sort",
    "env -0",
    "/usr/bin/env",
    "sudo env",
    "command env",
    "FOO=1 env",
    "env -u PATH",
    "export",
    "export -p",
    "export -p | grep TOKEN",
    "declare -x",
    "declare -px",
    "declare -p",
    "declare",
    "typeset -x",
    "set",
    "set | grep CERVEAU",
    "( set -o posix ; set )",
    "xargs -0 printenv",
    "ps eww",
    "ps auxe",
    "cat /proc/self/environ",
    "tr '\\0' '\\n' < /proc/$$/environ",
    "strings /proc/1/environ",
    "xargs -0 -n1 < /proc/self/task/1/environ",
    "launchctl getenv CERVEAU_TOTP_SECRET",
    "bash -c 'printenv'",
    "bash -c env",
    "sh -c 'set'",
    # one secret, by name
    "printenv CERVEAU_TOTP_SECRET",
    "printenv CERVEAU_API_TOKEN",
    'printenv "$v"',
    "echo $CERVEAU_TOTP_SECRET",
    'echo "$CERVEAU_TOTP_SECRET"',
    "echo ${CERVEAU_TOTP_SECRET}",
    "echo ${CERVEAU_API_TOKEN:-absent}",
    "echo ${#CERVEAU_TOTP_SECRET}",
    "echo $DISCORD_BOT_TOKEN",
    "echo $NTFY_TOKEN",
    "echo $NTFY_TOPIC",
    'curl -H "Authorization: Bearer $CERVEAU_API_TOKEN" http://127.0.0.1:8427/status',
    "x=$CERVEAU_TOTP_SECRET; echo $x",
    "echo $(printenv CERVEAU_TOTP_SECRET)",
    "v=CERVEAU_TOTP_SECRET; echo ${!v}",
    "declare -p CERVEAU_TOTP_SECRET",
    "typeset -p NTFY_TOKEN",
    "set CERVEAU",
    "echo %CERVEAU_TOTP_SECRET%",
    "cmd /c set",
    "cmd /c set CERVEAU",
    "cmd /c echo %CERVEAU_TOTP_SECRET%",
    'cmd /c "echo !CERVEAU_API_TOKEN!"',
    # inline interpreter code
    "python -c \"import os; print(os.environ['CERVEAU_TOTP_SECRET'])\"",
    "python3 -c \"import os; print(os.getenv('CERVEAU_API_TOKEN'))\"",
    "uv run python -c \"import os; print(os.environ.get('DISCORD_BOT_TOKEN'))\"",
    "python -c 'import os; print(os.environ)'",
    "python -c 'import os; print(dict(os.environ))'",
    "python -c 'import os; [print(k, v) for k, v in os.environ.items()]'",
    "python -c 'import os; from core.approvals.totp import SECRET_ENV; "
    "print(os.environ[SECRET_ENV])'",
    "uv run python -c 'import os; from core.approvals.totp import key_from_environment as k; "
    "print(k(os.environ))'",
    "python - <<EOF\nimport os\nprint(os.environ['NTFY_TOPIC'])\nEOF",
    "node -e 'console.log(process.env.CERVEAU_API_TOKEN)'",
    "node -e 'console.log(process.env)'",
    "node -e 'console.log(JSON.stringify(process.env))'",
    "perl -e 'print $ENV{CERVEAU_TOTP_SECRET}'",
    "perl -e 'print %ENV'",
    "ruby -e 'puts ENV[\"CERVEAU_TOTP_SECRET\"]'",
    "ruby -e 'p ENV.to_h'",
    "php -r 'echo getenv(\"CERVEAU_API_TOKEN\");'",
    # the registry and WMI hold the persistent user variables, whatever Claude Code's env says
    "reg query HKCU\\\\Environment",
    "reg query HKCU\\\\Environment /v CERVEAU_TOTP_SECRET",
    "reg query 'HKEY_CURRENT_USER\\Environment'",
    "wmic environment get name,variablevalue",
]

ALLOWED_BASH = [
    # the names as plain text
    "git grep -n CERVEAU_TOTP_SECRET",
    "git grep -n 'SECRET_ENV' -- core",
    "git grep -n 'os.environ' -- core",
    "grep -n CERVEAU_API_TOKEN interfaces/api/app.py",
    "echo CERVEAU_TOTP_SECRET",
    "git commit -m 'fix: mask CERVEAU_TOTP_SECRET for Claude Code'",
    "python -c \"print('CERVEAU_TOTP_SECRET')\"",
    "uv run pytest -q -k CERVEAU_TOTP_SECRET tests/hooks",
    "uv run pytest -q tests/test_api.py",
    "sed -n 1,40p core/approvals/totp.py",
    # other variables, and setting or blanking one
    "printenv PATH",
    "printenv HOME USER",
    "echo $HOME",
    "echo ${CERVEAU_HOME:-.}",
    "echo $NTFY_TOPIC_SUFFIXE",
    "CERVEAU_HOME=/tmp/x uv run cerveau config check",
    "CERVEAU_TOTP_SECRET= uv run pytest -q",
    "env -u CERVEAU_TOTP_SECRET uv run pytest -q",
    "env FOO=1 uv run pytest -q",
    "env -i PATH=/usr/bin uv --version",
    'export PATH="$HOME/bin:$PATH"',
    "export CERVEAU_HOME=/tmp/x",
    "declare -a items",
    "declare -f",
    "set -euo pipefail",
    "set -o",
    "set -- a b",
    "ps aux",
    "ps -ef",
    "ps axo pid,user,command",
    "python -c 'import os; print(os.environ.get(\"PATH\"))'",
    "python -c 'import os; print(os.getcwd())'",
    "node -e 'console.log(process.env.PATH)'",
    "cat /proc/cpuinfo",
    "reg query HKCU\\\\Software\\\\Microsoft",
    "cmd /c echo %PATH%",
    "ls env.sh",
]

BLOCKED_POWERSHELL = [
    "Get-ChildItem env:",
    "Get-ChildItem Env:\\",
    "gci env:",
    "dir env:",
    "ls env:",
    "Get-ChildItem -Path env:",
    "Get-ChildItem -Path:env:",
    "gci env:CERVEAU*",
    "Get-ChildItem env:*TOKEN*",
    "Get-Item env:CERVEAU_TOTP_SECRET",
    "gi Env:\\CERVEAU_API_TOKEN",
    "Get-Content env:CERVEAU_TOTP_SECRET",
    "(Get-Item env:CERVEAU_TOTP_SECRET).Value",
    "Copy-Item env:CERVEAU_TOTP_SECRET env:ALIAS",
    "Get-ChildItem env: | Format-Table -AutoSize",
    "$env:CERVEAU_TOTP_SECRET",
    "Write-Output $env:CERVEAU_TOTP_SECRET",
    "Write-Output $Env:cerveau_api_token",
    "Write-Output ${env:CERVEAU_TOTP_SECRET}",
    '"jeton : $($env:DISCORD_BOT_TOKEN)"',
    "$x = $env:NTFY_TOKEN",
    "[Environment]::GetEnvironmentVariable('CERVEAU_TOTP_SECRET')",
    "[Environment]::GetEnvironmentVariable('CERVEAU_TOTP_SECRET', 'User')",
    '[System.Environment]::GetEnvironmentVariable("CERVEAU_API_TOKEN", "Machine")',
    "[Environment]::GetEnvironmentVariable($name)",
    "[Environment]::GetEnvironmentVariable('CERVEAU_' + 'TOTP_SECRET')",
    "[Environment]::GetEnvironmentVariables()",
    "[Environment]::GetEnvironmentVariables('User')",
    "Get-ItemProperty HKCU:\\Environment",
    "Get-ItemProperty -Path 'HKCU:\\Environment' -Name CERVEAU_TOTP_SECRET",
    "Get-ItemPropertyValue Registry::HKEY_CURRENT_USER\\Environment -Name NTFY_TOPIC",
    "Get-CimInstance Win32_Environment",
    "Get-WmiObject -Class Win32_Environment",
    "cmd /c set",
    "cmd /c set CERVEAU",
    "cmd /c echo %CERVEAU_TOTP_SECRET%",
    'pwsh -Command "Get-ChildItem env:"',
    "powershell -Command 'Write-Output $env:CERVEAU_TOTP_SECRET'",
    "python -c \"import os; print(os.environ['CERVEAU_TOTP_SECRET'])\"",
]

ALLOWED_POWERSHELL = [
    "Test-Path env:CERVEAU_TOTP_SECRET",
    "Remove-Item env:CERVEAU_TOTP_SECRET",
    "Get-ChildItem env:PATH",
    "gci env:USERNAME",
    "$env:PATH",
    "Write-Output $env:USERPROFILE",
    "$env:CERVEAU_HOME = 'C:\\cerveau'",
    "[Environment]::GetEnvironmentVariable('PATH')",
    "[Environment]::GetEnvironmentVariable('TEMP', 'User')",
    "Select-String -Pattern CERVEAU_TOTP_SECRET -Path core\\approvals\\*.py",
    "git grep -n NTFY_TOPIC",
    "Get-ItemProperty HKCU:\\Software\\Microsoft",
    "cmd /c echo %USERPROFILE%",
    "Get-ChildItem -Recurse -Filter *.py",
]


@pytest.fixture(autouse=True)
def feature_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "current_branch", lambda cwd: "feature/hooks")


@pytest.mark.parametrize("command", BLOCKED_BASH)
def test_bash_commands_reading_a_secret_variable_are_refused(command: str) -> None:
    assert guard.analyse(command, False, CWD), f"aurait dû être refusé : {command!r}"


@pytest.mark.parametrize("command", ALLOWED_BASH)
def test_bash_commands_naming_a_secret_as_text_are_allowed(command: str) -> None:
    reason = guard.analyse(command, False, CWD)
    assert reason is None, f"refusé à tort : {command!r} → {reason}"


@pytest.mark.parametrize("command", BLOCKED_POWERSHELL)
def test_powershell_commands_reading_a_secret_variable_are_refused(command: str) -> None:
    assert guard.analyse(command, True, CWD), f"aurait dû être refusé : {command!r}"


@pytest.mark.parametrize("command", ALLOWED_POWERSHELL)
def test_powershell_commands_naming_a_secret_as_text_are_allowed(command: str) -> None:
    reason = guard.analyse(command, True, CWD)
    assert reason is None, f"refusé à tort : {command!r} → {reason}"


@pytest.mark.parametrize("name", ["CERVEAU_TOTP_SECRET", "NTFY_TOPIC"])
def test_the_refusal_cites_b228_and_never_the_value(name: str) -> None:
    reason = guard.analyse(f"echo ${name}", False, CWD)
    assert reason is not None and "B228" in reason and "R6" in reason
    assert guard.analyse("printenv", False, CWD) == secrets.DUMP_REFUSAL


def test_protected_names_are_the_secrets_of_interfaces_yaml() -> None:
    """The guard protects exactly the secrets the comment of config/interfaces.yaml lists."""
    comment = "\n".join(
        line
        for line in (REPO_ROOT / "config" / "interfaces.yaml").read_text("utf-8").splitlines()
        if line.startswith("#")
    )
    listed = set(re.findall(r"\b(?:CERVEAU|DISCORD|NTFY)_[A-Z_]+\b", comment))
    assert listed == set(secrets.SECRET_VARIABLES)
    assert set(secrets.MASKED_VARIABLES) <= set(secrets.SECRET_VARIABLES)
    assert {"CERVEAU_TOTP_SECRET", "CERVEAU_API_TOKEN"} <= set(secrets.MASKED_VARIABLES)


def test_code_names_of_the_secrets_exist_in_the_repository() -> None:
    """`os.environ[SECRET_ENV]` reads the secret: the guard knows the constants the code uses."""
    from core.approvals import totp
    from core.notify import ntfy
    from interfaces.api import app

    assert totp.SECRET_ENV in secrets.SECRET_VARIABLES
    assert app.TOKEN_ENV in secrets.SECRET_VARIABLES
    assert {ntfy.TOKEN_VARIABLE, ntfy.TOPIC_VARIABLE} <= set(secrets.SECRET_VARIABLES)
    bot = (REPO_ROOT / "interfaces" / "discord_bot" / "src" / "config.js").read_text("utf-8")
    for code_name in ("DISCORD_TOKEN_ENV", "API_TOKEN_ENV"):
        assert f"export const {code_name} = " in bot and code_name in secrets.CODE_NAMES


@pytest.mark.parametrize("path", SETTINGS, ids=["plateforme", "racine"])
def test_settings_blank_the_approval_secrets_for_claude_code(path: Path) -> None:
    """Part B: every process Claude Code starts inherits these variables empty."""
    settings = json.loads(path.read_text(encoding="utf-8"))
    env = settings.get("env", {})
    for name in secrets.MASKED_VARIABLES:
        assert env.get(name) == "", f"{name} non masquée dans {path}"


@pytest.mark.parametrize("path", SETTINGS, ids=["plateforme", "racine"])
def test_settings_still_route_the_shell_to_the_guard(path: Path) -> None:
    """Masking added nothing in place of a guard: the shell hook and the deny rules stay."""
    settings = json.loads(path.read_text(encoding="utf-8"))
    pre = settings["hooks"]["PreToolUse"]
    [shell] = [e for e in pre if "guard_shell.py" in json.dumps(e["hooks"])]
    assert shell["matcher"] == "Bash|PowerShell"
    assert shell["hooks"][0]["onFailure"] == "block"
    deny = settings["permissions"]["deny"]
    assert "Read(//proc/**/environ)" in deny
    assert any(rule.startswith("Read(") and ".env" in rule for rule in deny)


def test_end_to_end_refusal_is_audited(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    payload = {
        "session_id": "test-session",
        "cwd": str(REPO_ROOT),
        "tool_name": "PowerShell",
        "tool_use_id": "toolu_b228",
        "tool_input": {"command": "Get-ChildItem env:"},
    }
    result = run_hook("guard_shell", payload, journal)
    assert result.returncode == 2, result.stderr
    assert "BLOQUÉ" in result.stderr and "B228" in result.stderr
    entry = json.loads(journal.read_text(encoding="utf-8").splitlines()[0])
    assert entry["actor"] == "policy" and entry["request_id"] == "toolu_b228"
    assert verify(journal).ok
