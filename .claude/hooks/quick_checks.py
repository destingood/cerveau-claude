"""PostToolUse hook for Edit|Write|NotebookEdit: fast checks on the file just written.

Ruff on Python files, `cerveau config check` on config/*.yaml, `cerveau registry validate`
on plugin manifests, a secret scan (R6), CLAUDE.md under 200 lines and agent / skill
frontmatter. Problems are reported to Claude (exit 2); the write itself already happened.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import _common as c

TIMEOUT_S = 45
MAX_SCANNED_BYTES = 2 * 1024 * 1024
CLAUDE_MD_MAX_LINES = 200
SECRET_PATTERNS = (
    ("clé privée", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("clé AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("clé Anthropic", re.compile(r"\bsk-ant-[\w-]{20,}")),
    ("clé OpenAI", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{20,}")),
    ("jeton GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("jeton Slack", re.compile(r"\bxox[abprs]-[\w-]{10,}")),
    (
        "secret en clair",
        re.compile(
            r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*['\"][^'\"\s]{16,}['\"]"
        ),
    ),
)


def venv_tool(root: Path, name: str) -> str | None:
    for candidate in (root / ".venv" / "Scripts" / f"{name}.exe", root / ".venv" / "bin" / name):
        if candidate.exists():
            return str(candidate)
    return shutil.which(name)


def run(args: list[str], root: Path) -> str | None:
    """Output of a failing command, or None when it succeeds."""
    try:
        result = subprocess.run(
            args, cwd=root, capture_output=True, text=True, timeout=TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired:
        return f"{Path(args[0]).name} : délai de {TIMEOUT_S} s dépassé"
    except OSError as exc:
        return f"{Path(args[0]).name} : lancement impossible ({exc})"
    if result.returncode == 0:
        return None
    output = (result.stdout + result.stderr).strip()
    return "\n  ".join(output.splitlines()[:20]) or f"code de sortie {result.returncode}"


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fields = {}
    for line in text[3:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            fields[key.strip()] = value.strip()
    return fields


def scan_secrets(text: str) -> list[str]:
    found = []
    for label, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            found.append(f"{label} probable ligne {line} : retirer le secret du fichier (R6)")
    return found


def check_file(path: Path, root: Path) -> list[str]:
    """Problems found in `path` (empty list when everything is fine)."""
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return []
    if not path.is_file():
        return []
    problems: list[str] = []
    if path.suffix == ".py" and (ruff := venv_tool(root, "ruff")):
        for args in ([ruff, "check", "--quiet", rel], [ruff, "format", "--check", "--quiet", rel]):
            if output := run(args, root):
                problems.append(f"ruff {args[1]} : {output}")
    cerveau = venv_tool(root, "cerveau")
    is_config = re.fullmatch(r"config/[^/]+\.ya?ml", rel)
    if cerveau and is_config and (output := run([cerveau, "config", "check"], root)):
        problems.append(f"cerveau config check : {output}")
    manifest_dir = path.parent.as_posix()
    if (
        cerveau
        and path.name == "plugin.yaml"
        and (output := run([cerveau, "registry", "validate", manifest_dir], root))
    ):
        problems.append(f"cerveau registry validate : {output}")

    if path.stat().st_size <= MAX_SCANNED_BYTES:
        text = path.read_text(encoding="utf-8", errors="ignore")
        problems.extend(scan_secrets(text))
        if rel == "CLAUDE.md" and (count := len(text.splitlines())) > CLAUDE_MD_MAX_LINES:
            problems.append(f"CLAUDE.md fait {count} lignes (maximum {CLAUDE_MD_MAX_LINES})")
        is_agent = re.fullmatch(r"\.claude/agents/[^/]+\.md", rel)
        is_skill = re.fullmatch(r"\.claude/skills/[^/]+/SKILL\.md", rel)
        if is_agent or is_skill:
            fields = frontmatter(text)
            missing = [k for k in ("name", "description") if not fields.get(k)]
            if missing:
                problems.append(f"frontmatter incomplet : {', '.join(missing)} manquant")
        if rel.startswith(".claude/") and path.suffix == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                problems.append(f"JSON invalide : {exc}")
    return problems


def main() -> None:
    hook_input = c.read_hook_input()
    tool_input = hook_input.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(target, str) or not target.strip():
        return
    cwd = hook_input.get("cwd") or c.ROOT
    path = Path(target) if Path(target).is_absolute() else Path(cwd) / target
    problems = check_file(path, c.ROOT)
    if problems:
        rel = path.resolve().relative_to(c.ROOT.resolve()).as_posix()
        sys.stderr.write(f"Contrôles rapides — {rel} :\n" + "".join(f"- {p}\n" for p in problems))
        sys.exit(2)


if __name__ == "__main__":
    c.configure_stdio()
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # a broken check must not hide itself, nor block the session
        sys.stderr.write(f"Contrôles rapides indisponibles ({type(exc).__name__}: {exc})\n")
        sys.exit(1)
