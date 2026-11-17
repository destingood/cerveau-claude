"""Promotion, rollback and watch of the learned layer (ADR-011, ADR-065).

- **Promotion** recomputes the gate's verdict itself (it never trusts a verdict handed to it) and
  requires the ``learning.promotion`` feature: thresholds and budgets set (R7), live evals (D4).
- **Rollback** brings back the section a promotion replaced, or removes it when there was none.
  It goes towards caution, so no threshold gates it.
- **Watch**: within ``rollback_window_days`` of a promotion, a production report that the gate
  rejects against the challenger's report of that promotion rolls it back.

Every promotion and rollback writes a ``LEARNING`` entry (R11): hashes and counts, never the text.
The texts replaced live in ``var/learning/champions.jsonl``, append-only and replayed as a stack
per section, so that successive rollbacks go back one promotion at a time.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.audit.chain import AuditJournal
from core.config import Config
from core.learning.gate import LEARNING_EVENT, Verdict, compare
from core.learning.layer import (
    LEARNED_DIR,
    layer_digest,
    read_section,
    remove_section,
    snapshot,
    write_section,
)


class ChampionError(ValueError):
    """Nothing was promoted nor rolled back."""


@dataclass(frozen=True)
class Promotion:
    pack: str
    section: str
    previous: str | None
    current: str
    ts: datetime
    report: Mapping[str, Any]  # the challenger's eval report, reference for the watch


def default_history_path(project_root: Path) -> Path:
    return project_root / "var" / "learning" / "champions.jsonl"


def _digest(text: str | None) -> str | None:
    return None if text is None else "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _set[T: (int, float)](value: T | str) -> T | None:
    return None if isinstance(value, str) else value  # a marker: not set (R7)


def verdict_for(
    config: Config, champion: Mapping[str, Any], challenger: Mapping[str, Any]
) -> Verdict:
    learning = config.evals.learning
    return compare(
        champion,
        challenger,
        holdout_percent=learning.holdout_percent,
        margin=_set(learning.promotion_margin),
        min_cases=_set(learning.min_held_out_cases),
    )


def _bound(
    config: Config, report: Mapping[str, Any], sections: Mapping[str, str], name: str
) -> None:
    """A verdict holds only for the configuration and the layer its reports were measured on."""
    if report.get("config") != config.digest or report.get("learned") != layer_digest(sections):
        raise ChampionError(
            f"rapport du {name} non lié à cette configuration et à cette couche apprise "
            "(champs config et learned) : relancer ses évals"
        )


def standing(history: Path, pack: str, section: str) -> list[Promotion]:
    """The promotions of a section still in service, oldest first."""
    stack: list[Promotion] = []
    if not history.exists():
        return stack
    with history.open(encoding="utf-8") as lines:
        for number, line in enumerate(lines, start=1):
            try:
                record = json.loads(line)
                key = (record["pack"], record["section"])
                if key != (pack, section):
                    continue
                if record["action"] == "rollback":
                    stack.pop()
                else:
                    stack.append(
                        Promotion(
                            pack,
                            section,
                            record["previous"],
                            record["current"],
                            datetime.fromisoformat(record["ts"]),
                            record["report"],
                        )
                    )
            except (ValueError, KeyError, TypeError, IndexError):
                raise ChampionError(
                    f"historique des champions illisible à la ligne {number}"
                ) from None
    return stack


def _record(history: Path, record: dict[str, Any]) -> None:
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def promote(
    config: Config,
    champion: Mapping[str, Any],
    challenger: Mapping[str, Any],
    challenger_dir: Path,
    pack: str,
    section: str,
    *,
    journal: AuditJournal,
    history: Path,
    now: datetime,
    learned_dir: Path = LEARNED_DIR,
) -> Verdict:
    """Puts the challenger's section in service; refused unless the gate says ``promouvable``."""
    config.require("learning.promotion")  # BlockedFeatureError while anything is A_DEFINIR
    verdict = verdict_for(config, champion, challenger)
    if verdict.status != "promouvable":
        raise ChampionError(f"verdict {verdict.status} : " + " ; ".join(verdict.reasons))
    current = read_section(pack, section, challenger_dir)
    if current is None:
        raise ChampionError(f"le challenger n'a pas de section {pack}/{section}")
    served = snapshot(learned_dir)
    _bound(config, champion, served, "champion")
    _bound(config, challenger, {**served, f"{pack}/{section}": current}, "challenger")
    previous = read_section(pack, section, learned_dir)
    write_section(pack, section, current, learned_dir)  # first: a failed write records nothing
    journal.append(
        actor="orchestrator",
        event=LEARNING_EVENT,
        payload={
            "action": "promotion",
            "pack": pack,
            "section": section,
            "previous": _digest(previous),
            "current": _digest(current),
            "held_out_cases": verdict.held_out.cases,
        },
        now=now,
    )
    _record(
        history,
        {
            "action": "promotion",
            "pack": pack,
            "section": section,
            "previous": previous,
            "current": current,
            "ts": now.isoformat(),
            "report": dict(challenger),
        },
    )
    return verdict


def rollback(
    pack: str,
    section: str,
    *,
    journal: AuditJournal,
    history: Path,
    now: datetime,
    reason: str,
    learned_dir: Path = LEARNED_DIR,
) -> Promotion:
    """Undoes the section's last standing promotion; the promotion undone."""
    stack = standing(history, pack, section)
    if not stack:
        raise ChampionError(f"aucune promotion en service pour {pack}/{section}")
    last = stack[-1]
    journal.append(
        actor="orchestrator",
        event=LEARNING_EVENT,
        payload={
            "action": "rollback",
            "pack": pack,
            "section": section,
            "reason": reason,
            "restored": _digest(last.previous),
            "removed": _digest(last.current),
        },
        now=now,
    )
    _record(
        history, {"action": "rollback", "pack": pack, "section": section, "ts": now.isoformat()}
    )
    if last.previous is None:
        remove_section(pack, section, learned_dir)
    else:
        write_section(pack, section, last.previous, learned_dir)
    return last


def watch(
    config: Config,
    production: Mapping[str, Any],
    pack: str,
    section: str,
    *,
    journal: AuditJournal,
    history: Path,
    now: datetime,
    learned_dir: Path = LEARNED_DIR,
) -> Verdict | None:
    """Rolls the last promotion back when production drops within the window; the verdict.

    None when no promotion of the section stands or its window is over. The window is a
    threshold (R7): while it is ``A_DEFINIR``, any standing promotion is watched.
    """
    stack = standing(history, pack, section)
    if not stack:
        return None
    last = stack[-1]
    days = _set(config.evals.learning.rollback_window_days)
    if days is not None and now - last.ts > timedelta(days=days):
        return None
    verdict = verdict_for(config, last.report, production)
    if verdict.status == "rejete":
        rollback(
            pack,
            section,
            journal=journal,
            history=history,
            now=now,
            reason="baisse en production",
            learned_dir=learned_dir,
        )
    return verdict
