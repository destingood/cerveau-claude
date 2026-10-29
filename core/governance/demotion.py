"""Automatic demotions (section 8.3, ADR-067): a trigger lowers a domain by one level, never more
and never upwards.

A demotion is a line of ``var/governance/demotions.jsonl``, written by the program and journaled
(``policy`` / ``DECISION``). ``effective_autonomy`` holds each domain at or below the lowest level
a demotion set for it. No code lifts a demotion: Lucas removes its line by hand, after reading the
journal (R2). An unreadable file holds every domain at N0: a demotion that cannot be read must not
be lost.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from core.audit import AuditJournal
from core.config.loader import LEVELS, Level

DEMOTIONS = Path("var") / "governance" / "demotions.jsonl"
DEMOTION_STATUS = "retrogradation"
MAX_BYTES = 1024 * 1024  # a few thousand demotions; a larger file is not ours


class DemotionError(ValueError):
    """A demotion that cannot be recorded."""


@dataclass(frozen=True)
class Demotion:
    at: str
    domain: str
    from_level: Level
    to_level: Level
    trigger: str
    reason: str


def demotions_path(root: Path) -> Path:
    return root / DEMOTIONS


def read_demotions(root: Path) -> tuple[Demotion, ...] | str:
    """Every recorded demotion, or why the file cannot be read."""
    path = demotions_path(root)
    try:
        if not path.is_file():
            return ()
        if path.stat().st_size > MAX_BYTES:
            return f"{DEMOTIONS.as_posix()} trop volumineux"
        found = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            demotion = Demotion(**data)
            if demotion.to_level not in LEVELS or demotion.from_level not in LEVELS:
                return f"{DEMOTIONS.as_posix()} : niveau inconnu"
            found.append(demotion)
    except (OSError, ValueError, TypeError) as exc:
        return f"{DEMOTIONS.as_posix()} illisible ({type(exc).__name__})"
    return tuple(found)


def floors(demotions: Iterable[Demotion]) -> dict[str, Level]:
    """The lowest level each demoted domain may run at."""
    lowest: dict[str, Level] = {}
    for d in demotions:
        if d.domain not in lowest or LEVELS.index(d.to_level) < LEVELS.index(lowest[d.domain]):
            lowest[d.domain] = d.to_level
    return lowest


def one_step_down(level: Level) -> Level | None:
    index = LEVELS.index(level)
    return LEVELS[index - 1] if index > 0 else None


def demote(
    root: Path,
    journal: AuditJournal,
    *,
    levels: Mapping[str, Level],
    trigger: str,
    triggers: Iterable[str],
    reason: str,
    now: datetime,
    once: str | None = None,
) -> list[Demotion]:
    """Lower each domain of ``levels`` (its effective level now) by one step; a domain at N0 stays
    there. ``trigger`` must be one of ``demotion_triggers`` (autonomy.yaml). With ``once`` (the
    reference that ``reason`` starts with, ``hebdo-<week>``), a domain already demoted by that
    trigger for that reference is not demoted again: a rerun of a report is not a new failure."""
    if trigger not in set(triggers):
        raise DemotionError(f"déclencheur inconnu : {trigger} (autonomy.yaml › demotion_triggers)")
    seen: set[str] = set()
    if once is not None and not isinstance(recorded := read_demotions(root), str):
        seen = {d.domain for d in recorded if d.trigger == trigger and d.reason.startswith(once)}
    done: list[Demotion] = []
    for domain, level in sorted(levels.items()):
        lower = one_step_down(level)
        if lower is None or domain in seen:
            continue
        demotion = Demotion(now.isoformat(), domain, level, lower, trigger, reason)
        path = demotions_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(demotion), ensure_ascii=False) + "\n")
        journal.append(
            actor="policy",
            event="DECISION",
            request_id=f"retrogradation-{domain}",
            payload={"status": DEMOTION_STATUS, **asdict(demotion)},
            now=now,
        )
        done.append(demotion)
    return done


GATE_PREFIX = "taux de réussite : "


def gate_domains(missed: Iterable[str], domains: Iterable[str]) -> frozenset[str]:
    """The domains a missed eval gate demotes: the domain its group names (``finance``,
    ``pack_finance``, ``finance_ordres``), or every domain for a gate of no domain (R5, sourcing,
    errors, shared behaviours)."""
    known = frozenset(domains)
    hit: set[str] = set()
    for name in missed:
        group = name.removeprefix(GATE_PREFIX).removeprefix("pack_")
        owner = [d for d in known if group == d or group.startswith(d + "_")]
        if not owner:
            return known
        hit.update(owner)
    return frozenset(hit)
