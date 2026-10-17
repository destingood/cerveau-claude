"""Shared helpers for the CERVEAU Claude Code hooks.

Stdlib only, Python 3.12+. Every hook is fail-closed: any unexpected error
while deciding exits with code 2 (block), and settings.json adds
"onFailure": "block" for crashes that happen before this code runs.

These hooks are convenience guard-rails (section 16.5). The effective
protection of config/live.yaml is the file-system ACL (R3, ADR-003).
"""

from __future__ import annotations

import contextlib
import fnmatch
import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[2]
IS_WINDOWS = os.name == "nt"

# Write-protected: Claude Code never modifies these (R3, R11, governance).
WRITE_PROTECTED_FILES = ("config/live.yaml",)
WRITE_PROTECTED_DIRS = ("governance/approvals", "var/audit")
# Read-protected: never read, never written (R6). `.env.example` is a template without secrets.
ENV_EXAMPLE = ".env.example"
SECRETS_DIR = "secrets"
# Concrete locations used for ancestor checks (`rm -r infra`, `grep -r . `...).
SENSITIVE_LOCATIONS = (
    "config/live.yaml",
    "governance/approvals",
    "var/audit",
    ".env",
    "infra/.env",
    "secrets",
)
# Samples used to test whether a glob could match a protected path.
GLOB_SAMPLES_WRITE = ("config/live.yaml", "governance/approvals/x", "var/audit/journal.jsonl")
GLOB_SAMPLES_READ = (".env", ".env.local", "infra/.env", "secrets/key")

_KEY_CHARS = r"[A-Za-z0-9+_=-]"
_SECRET_LIKE = re.compile(
    r"sk-ant-[\w-]{8,}|sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}"
    r"|xox[abprs]-[\w-]{10,}"
    # long mixed-case alphanumeric runs (API keys, tokens), but not paths or hex hashes
    rf"|(?={_KEY_CHARS}*[a-z])(?={_KEY_CHARS}*[A-Z])(?={_KEY_CHARS}*\d){_KEY_CHARS}{{32,}}"
)
MAX_LOGGED_CHARS = 500


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


def read_hook_input() -> dict[str, Any]:
    raw = sys.stdin.buffer.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("hook input is not a JSON object")
    return data


def redact(text: str) -> tuple[str, bool]:
    """Truncate and mask secret-looking strings before they reach the audit journal (R6)."""
    masked, count = _SECRET_LIKE.subn("[MASQUÉ]", text)
    if len(masked) > MAX_LOGGED_CHARS:
        masked = masked[:MAX_LOGGED_CHARS] + "…"
    return masked, count > 0


def audit_denial(hook_input: dict[str, Any], target: str, reason: str) -> str | None:
    """Append a POLICY entry to the hash-chained journal. Returns an error message on failure."""
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from core.audit.chain import AuditJournal, default_journal_path, sha256_ref

        logged, redacted = redact(target)
        settings = ROOT / ".claude" / "settings.json"
        versions = {"config": sha256_ref(settings.read_bytes())} if settings.exists() else {}
        request_id = str(hook_input.get("tool_use_id") or "") or None
        AuditJournal(default_journal_path(ROOT)).append(
            actor="policy",
            event="POLICY",
            request_id=request_id,
            versions=versions,
            payload={
                "source": "claude_code_hook",
                "decision": "refus",
                "tool_name": str(hook_input.get("tool_name", "")),
                "target": logged,
                "reason": reason,
                "session_id": str(hook_input.get("session_id", "")),
            },
            redactions=["secret_like_strings"] if redacted else [],
        )
    except Exception as exc:  # the denial must stand even if logging fails
        return f"{type(exc).__name__}: {exc}"
    return None


def deny(hook_input: dict[str, Any], target: str, reason: str) -> NoReturn:
    sys.stderr.write(f"BLOQUÉ par le hook CERVEAU : {reason}\n")
    error = audit_denial(hook_input, target, reason)
    if error:
        sys.stderr.write(f"(journal d'audit indisponible : {error})\n")
    sys.exit(2)


def run_fail_closed(main: Callable[[], None]) -> None:
    configure_stdio()
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        sys.stderr.write(
            f"BLOQUÉ par le hook CERVEAU : contrôle impossible ({type(exc).__name__}: {exc}). "
            "Fail-closed.\n"
        )
        sys.exit(2)
    sys.exit(0)


# --- path normalisation -----------------------------------------------------------------------

_MSYS_DRIVE = re.compile(r"^/([a-zA-Z])(/|$)")
_WIN_DRIVE = re.compile(r"^[a-zA-Z]:")


def _clean_component(part: str) -> str:
    # Windows ignores trailing dots/spaces and `file::$DATA` designates the main stream.
    if IS_WINDOWS:
        if ":" in part:
            part = part.split(":", 1)[0]
        part = part.rstrip(". ")
    return part


def normalise(path: str, cwd: str | Path | None = None) -> str:
    """Absolute, '/'-separated, case-folded on Windows, symlinks resolved when they exist."""
    text = path.strip().strip("'\"").replace("\\", "/")
    if IS_WINDOWS:
        text = _MSYS_DRIVE.sub(lambda m: f"{m.group(1)}:/", text)
    if text.startswith("~"):
        text = os.path.expanduser(text)
    base = Path(cwd) if cwd else ROOT
    candidate = Path(text) if (Path(text).is_absolute() or _WIN_DRIVE.match(text)) else base / text
    try:
        resolved = os.path.realpath(candidate)
    except (OSError, ValueError):
        resolved = os.path.abspath(candidate)
    resolved = resolved.replace("\\", "/")
    drive, _, rest = resolved.partition(":/") if _WIN_DRIVE.match(resolved) else ("", "", resolved)
    parts = [_clean_component(p) for p in rest.split("/")]
    joined = "/".join(parts)
    result = f"{drive}:/{joined}" if drive else joined
    return result.lower() if IS_WINDOWS else result


def root_norm() -> str:
    return normalise(str(ROOT))


def relative_to_root(abs_norm: str) -> str | None:
    root = root_norm().rstrip("/")
    if abs_norm == root:
        return ""
    if abs_norm.startswith(root + "/"):
        return abs_norm[len(root) + 1 :]
    return None


def _fold(text: str) -> str:
    return text.lower() if IS_WINDOWS else text


def write_protection_reason(abs_norm: str) -> str | None:
    """Reason why writing this (normalised, absolute) path is forbidden, or None."""
    rel = relative_to_root(abs_norm)
    if rel is not None:
        if rel in map(_fold, WRITE_PROTECTED_FILES):
            return f"{rel} est protégé (R3) : seul Lucas le modifie, à la main"
        for directory in map(_fold, WRITE_PROTECTED_DIRS):
            if rel == directory or rel.startswith(directory + "/"):
                return f"{rel} est protégé (gouvernance / journal d'audit R11)"
    # Same file names in another checkout or worktree (mega-prompt 16.5 pattern).
    if abs_norm.endswith("/config/live.yaml") or "/governance/approvals/" in abs_norm + "/":
        return f"{abs_norm} est protégé (R3)"
    return read_protection_reason(abs_norm)


def read_protection_reason(abs_norm: str) -> str | None:
    """Reason why reading (or writing) this path is forbidden (R6), or None."""
    path = PurePosixPath(abs_norm)
    name = path.name
    if name == ".env" or (name.startswith(".env.") and name != ENV_EXAMPLE):
        return f"{name} peut contenir des secrets (R6)"
    if SECRETS_DIR in path.parts:
        return "le dossier secrets/ est interdit (R6)"
    return None


READ_SENSITIVE_LOCATIONS = (".env", "infra/.env", "secrets")


def is_ancestor_of(abs_norm: str, locations: tuple[str, ...] = SENSITIVE_LOCATIONS) -> bool:
    """Whether `abs_norm` is one of `locations` (relative to the root) or contains one."""
    root = root_norm().rstrip("/")
    for location in locations:
        target = f"{root}/{_fold(location)}"
        if target == abs_norm or target.startswith(abs_norm.rstrip("/") + "/"):
            return True
    return False


def _glob_component_match(name: str, pattern: str, dotfiles: bool) -> bool:
    if not dotfiles and name.startswith(".") and not pattern.startswith("."):
        return False
    return fnmatch.fnmatchcase(name, pattern)


def _glob_match(parts: list[str], pattern: list[str], dotfiles: bool) -> bool:
    if not pattern:
        return not parts
    head, rest = pattern[0], pattern[1:]
    if head == "**":
        return any(_glob_match(parts[i:], rest, dotfiles) for i in range(len(parts) + 1))
    if not parts:
        return False
    return _glob_component_match(parts[0], head, dotfiles) and _glob_match(
        parts[1:], rest, dotfiles
    )


def glob_could_match(
    token: str,
    cwd: str | Path | None,
    samples: tuple[str, ...],
    dotfiles: bool,
    *,
    ancestors: bool = False,
) -> bool:
    """Whether a shell glob in `token` could expand to a protected sample path.

    With `ancestors`, a match on a directory containing a sample counts too (`rm -r c*`).
    """
    if not any(c in token for c in "*?["):
        return False
    pattern = token.strip("'\"").replace("\\", "/")
    root = root_norm().rstrip("/")
    base = normalise(str(cwd)) if cwd else root
    if not (pattern.startswith("/") or _WIN_DRIVE.match(pattern)):
        pattern = f"{base}/{pattern}"
    pattern = _fold(pattern)
    if IS_WINDOWS:
        pattern = _MSYS_DRIVE.sub(lambda m: f"{m.group(1)}:/", pattern)
    pattern_parts = [p for p in pattern.split("/") if p not in ("", ".")]
    root_len = len([p for p in root.split("/") if p])
    for sample in samples:
        sample_parts = [p for p in f"{root}/{_fold(sample)}".split("/") if p]
        lengths = range(root_len + 1, len(sample_parts) + 1) if ancestors else [len(sample_parts)]
        if any(_glob_match(sample_parts[:k], pattern_parts, dotfiles) for k in lengths):
            return True
    return False
