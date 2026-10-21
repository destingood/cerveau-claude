"""Hardened in phase 6 (D8): the promotion reports a signature cites (B226) and the Discord bot's
package.json, whose npm scripts `make bot-test` runs (B229), are written by CERVEAU or Lucas only.
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
REPORT = "var/promotion/finance-N3-2026-10-21.md"
MANIFEST = "interfaces/discord_bot/package.json"

BLOCKED_BASH = [
    # promotion reports (B226)
    f"echo x > {REPORT}",
    f"rm {REPORT}",
    "rm -r var/promotion",
    "mv var/promotion /tmp/p",
    f"cp /tmp/forged.md {REPORT}",
    f"sed -i 's/impossible/possible/' {REPORT}",
    "cd var/promotion && rm *.md",
    "tee var/promotion/forged.md < /tmp/x",
    'cd "$X" && rm finance-N3-2026-10-21.md',
    # the bot's package.json (B229)
    f"echo x > {MANIFEST}",
    f"sed -i 's/node --test/node evil.js/' {MANIFEST}",
    f"cp /tmp/package.json {MANIFEST}",
    f"mv {MANIFEST} /tmp/p.json",
    "cd interfaces/discord_bot && sed -i 's/a/b/' package.json",
    "npm --prefix interfaces/discord_bot install left-pad",
    "npm --prefix interfaces/discord_bot i -D left-pad",
    "npm --prefix interfaces/discord_bot audit fix",
    "cd interfaces/discord_bot && npm install left-pad",
    "npm --prefix interfaces/discord_bot pkg set scripts.test=x",
]
BLOCKED_POWERSHELL = [
    f"Set-Content {REPORT.replace('/', chr(92))} 'x'",
    "Remove-Item var\\promotion -Recurse",
    f"Set-Content {MANIFEST.replace('/', chr(92))} '{{}}'",
    "Set-Location interfaces\\discord_bot; npm install left-pad",
]
ALLOWED_BASH = [
    f"cat {REPORT}",
    "ls var/promotion",
    f"sha256sum {REPORT}",
    f"cat {MANIFEST}",
    f"grep -n test {MANIFEST}",
    f"git add {MANIFEST}",
    "npm --prefix interfaces/discord_bot ci --ignore-scripts --no-audit --no-fund",
    "npm --prefix interfaces/discord_bot test",
    "npm --prefix interfaces/discord_bot install",
    "npm --prefix interfaces/discord_bot audit --omit=dev",
    "cd interfaces/discord_bot && npm ci && npm test",
]
ALLOWED_POWERSHELL = [
    f"Get-Content {REPORT.replace('/', chr(92))}",
    f"Get-Content {MANIFEST.replace('/', chr(92))}",
    "Set-Location interfaces\\discord_bot; npm test",
]


@pytest.mark.parametrize(
    ("command", "powershell"),
    [(cmd, False) for cmd in BLOCKED_BASH] + [(cmd, True) for cmd in BLOCKED_POWERSHELL],
)
def test_writing_a_report_or_the_bot_manifest_is_refused(command: str, powershell: bool) -> None:
    assert guard.analyse(command, powershell, CWD), f"aurait dû être refusé : {command!r}"


@pytest.mark.parametrize(
    ("command", "powershell"),
    [(cmd, False) for cmd in ALLOWED_BASH] + [(cmd, True) for cmd in ALLOWED_POWERSHELL],
)
def test_reading_testing_and_installing_stay_allowed(command: str, powershell: bool) -> None:
    reason = guard.analyse(command, powershell, CWD)
    assert reason is None, f"refusé à tort : {command!r} → {reason}"


def test_standing_in_the_bot_folder_counts() -> None:
    assert guard.analyse("npm install left-pad", False, BOT)
    assert guard.analyse("sed -i 's/a/b/' package.json", False, BOT)
    assert guard.analyse("npm install", False, BOT) is None


def test_refusals_name_their_rule() -> None:
    install = guard.analyse("npm --prefix interfaces/discord_bot install left-pad", False, CWD)
    assert install and "B229" in install and "Lucas" in install
    _, manifest = paths.decide({"file_path": MANIFEST}, CWD, "Edit")
    assert manifest and "B229" in manifest
    _, report = paths.decide({"file_path": REPORT}, CWD, "Write")
    assert report and "ADR-040" in report


@pytest.mark.parametrize("tool", ["Edit", "Write", "NotebookEdit"])
@pytest.mark.parametrize("target", [REPORT, "var/promotion", MANIFEST])
def test_reports_and_the_bot_manifest_are_write_protected(tool: str, target: str) -> None:
    _, reason = paths.decide({"file_path": target}, CWD, tool)
    assert reason


@pytest.mark.parametrize("tool", ["Edit", "Write"])
def test_the_rest_of_the_bot_stays_writable(tool: str) -> None:
    for target in ("interfaces/discord_bot/index.js", "interfaces/discord_bot/test/x.test.js"):
        _, reason = paths.decide({"file_path": target}, CWD, tool)
        assert reason is None, target
