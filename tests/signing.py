"""Test helper: a promotion signature in a temporary project root (ADR-036).

Only tests use it, and only under ``tmp_path``: the real ``governance/approvals/`` belongs to
Lucas and is never written by code (D18).
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from core.config.loader import Level
from core.governance.signatures import PROMOTION_DIR, SIGNATURES_DIR, signature_text


def sign(
    root: Path, domain: str, level: Level, day: date = date(2026, 10, 21), *, report: bool = True
) -> Path:
    """Sign ``level`` for ``domain`` under ``root``; with ``report``, file the cited report too."""
    text = f"Rapport de promotion {domain} {level} du {day.isoformat()}\n".encode()
    if report:
        (root / PROMOTION_DIR).mkdir(parents=True, exist_ok=True)
        (root / PROMOTION_DIR / f"{day.isoformat()}-{domain}-{level}.md").write_bytes(text)
    path = root / SIGNATURES_DIR / f"{day.isoformat()}-{domain}-{level}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(text).hexdigest()
    path.write_text(signature_text(domain, level, day, digest), encoding="utf-8")
    return path
