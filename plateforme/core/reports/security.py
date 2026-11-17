"""Monthly security report (ADR-066, §17 phase 7).

Each check is a local command whose exit code decides; its output never enters the report (a
finding may quote what it found, R6), only the code and a count of lines. A missing tool is a
failed check, not a skipped one. The threat model's drift is the list of ADRs newer than the
last one it cites: decisions it has not been reviewed against.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.reports.weekly import FAILED, OK

THREAT_MODEL = Path("docs") / "threat-model.md"
ADR_DIR = Path("docs") / "adr"
MISSING = 127
_ADR = re.compile(r"ADR-(\d{3})")

Runner = Callable[[Sequence[str], Path], tuple[int, int]]  # (exit code, output lines)


@dataclass(frozen=True)
class Check:
    name: str
    command: tuple[str, ...]
    blocking: bool = True  # an informative check never fails the report


BOT = "interfaces/discord_bot"
CHECKS = (
    Check("secrets (gitleaks)", ("gitleaks", "git", "--no-banner", "--redact")),
    Check("dépendances Python (pip-audit)", ("uv", "run", "pip-audit", "--skip-editable")),
    Check("dépendances Node (npm audit)", ("npm", "--prefix", BOT, "audit", "--omit=dev")),
    Check("chaîne du journal (audit verify)", ("uv", "run", "cerveau", "audit", "verify")),
    Check("configuration (config check)", ("uv", "run", "cerveau", "config", "check")),
    Check(
        "tests des hooks", ("uv", "run", "pytest", "-q", "-p", "no:cacheprovider", "tests/hooks")
    ),
    Check("dépendances dépassées", ("uv", "pip", "list", "--outdated"), blocking=False),
)


def run_command(command: Sequence[str], cwd: Path) -> tuple[int, int]:
    """Runs a check without a shell; its output is counted, never kept."""
    if shutil.which(command[0]) is None:
        return MISSING, 0
    done = subprocess.run(  # noqa: S603  # fixed commands of CHECKS, no shell
        list(command), cwd=cwd, capture_output=True, text=True, errors="replace", check=False
    )
    return done.returncode, len((done.stdout + done.stderr).splitlines())


def threat_model_drift(root: Path) -> list[str]:
    """ADRs numbered after the last one the threat model cites."""
    model = root / THREAT_MODEL
    cited = (
        [int(n) for n in _ADR.findall(model.read_text(encoding="utf-8"))] if model.is_file() else []
    )
    last = max(cited, default=0)
    return sorted(
        path.stem[:7]
        for path in (root / ADR_DIR).glob("ADR-*.md")
        if (match := _ADR.match(path.name)) and int(match.group(1)) > last
    )


@dataclass(frozen=True)
class Security:
    month: str
    rows: tuple[tuple[Check, int, int], ...]
    drift: tuple[str, ...]

    @property
    def failed(self) -> list[str]:
        return [check.name for check, code, _ in self.rows if check.blocking and code != 0]

    @property
    def status(self) -> str:
        return FAILED if self.failed else OK

    def markdown(self) -> str:
        lines = [
            f"# Rapport de sécurité {self.month}",
            "",
            f"- Statut : {self.status}",
            *[f"  - en échec : {name}" for name in self.failed],
            "- Les sorties des outils ne sont pas recopiées (R6) : relancer la commande pour le "
            "détail.",
            "",
            "| Contrôle | Commande | Code de sortie | Lignes de sortie | Résultat |",
            "|---|---|---|---|---|",
        ]
        for check, code, count in self.rows:
            if code == MISSING:
                result = "outil absent"
            elif code == 0:
                result = "ok"
            else:
                result = "à examiner" if not check.blocking else "ÉCHEC"
            lines.append(
                f"| {check.name} | `{' '.join(check.command)}` | {code} | {count} | {result} |"
            )
        lines += [
            "",
            "## Écart au modèle de menaces (docs/threat-model.md)",
            "",
            f"- ADR postérieurs au dernier cité : {', '.join(self.drift) or 'aucun'}",
            "",
        ]
        return "\n".join(lines) + "\n"


def security_path(root: Path, month: str) -> Path:
    return root / "docs" / "rapports" / f"securite-{month}.md"


def build_security(root: Path, now: datetime, *, runner: Runner = run_command) -> Security:
    rows = tuple((check, *runner(check.command, root)) for check in CHECKS)
    return Security(f"{now.astimezone():%Y-%m}", rows, tuple(threat_model_drift(root)))
