"""Test helper: a promotion signature in a temporary project root (ADR-036).

Only tests use it, and only under ``tmp_path``: the real ``governance/approvals/`` belongs to
Lucas and is never written by code (D18).
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from core.config.loader import Level
from core.governance.signatures import (
    PROMOTION_DIR,
    REPORT_KIND,
    REPORT_PASSED,
    SIGNATURES_DIR,
    signature_text,
)


def report_text(
    domain: str, level: str, day: date, statut: str = REPORT_PASSED, *, generated: str = ""
) -> bytes:
    """A promotion report as ``signatures.py`` reads it: its header, then a title. It was
    generated on ``day`` in Paris unless ``generated`` gives its ISO timestamp."""
    generated = generated or f"{day.isoformat()}T08:00:00+02:00"
    return (
        f"---\nrapport: {REPORT_KIND}\ndomain: {domain}\nlevel: {level}\nstatut: {statut}\n"
        f'genere_le: "{generated}"\n'
        f"---\n# Rapport de promotion {domain} {level} du {day.isoformat()}\n"
    ).encode()


def sign(
    root: Path,
    domain: str,
    level: Level,
    day: date = date(2026, 10, 21),
    *,
    report: bool = True,
    statut: str = REPORT_PASSED,
) -> Path:
    """Sign ``level`` for ``domain`` under ``root``; with ``report``, file the cited report too,
    concluding ``statut``."""
    text = report_text(domain, level, day, statut)
    if report:
        (root / PROMOTION_DIR).mkdir(parents=True, exist_ok=True)
        (root / PROMOTION_DIR / f"{day.isoformat()}-{domain}-{level}.md").write_bytes(text)
    path = root / SIGNATURES_DIR / f"{day.isoformat()}-{domain}-{level}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(text).hexdigest()
    path.write_text(signature_text(domain, level, day, digest), encoding="utf-8")
    return path
