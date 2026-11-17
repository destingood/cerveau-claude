"""Weekly report and the streak of scheduled weeks (ADR-066, §17 phase 7).

No LLM writes it (R1): every number is read from a file or the journal, and the report names it.
It covers the last complete ISO week before ``now``, so a run caught up late covers the same week.

The report is ``ok`` when every source reads, the offline eval report was produced during or
after the covered week and every gate passed; otherwise ``echec``, with the reasons, rather than
silence. Each run writes a ``scheduler`` entry to the journal (R11); the streak counts the
consecutive weeks, back from the last covered one, whose latest entry is ``ok``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from core.audit.chain import AuditError, AuditJournal
from core.budget.ledger import LedgerError, read_spending
from core.learning.calibration import CalibrationError, probability_scores
from core.learning.champion import ChampionError, standing
from core.learning.forecasts import ForecastError, ForecastStore

REPORTS_DIR = Path("evals") / "reports"
WEEKLY_STATUS = "rapport_hebdo"
OK, FAILED = "ok", "echec"
INCIDENT_EVENTS = ("KILL", "ERROR")


class ReportError(ValueError):
    """A source of the report cannot be read."""


@dataclass(frozen=True)
class Week:
    start: datetime  # Monday 00:00, local time
    end: datetime  # the next Monday 00:00

    @property
    def id(self) -> str:
        year, week, _ = self.start.isocalendar()
        return f"{year}-S{week:02d}"

    @classmethod
    def starting(cls, monday: date) -> Week:
        """Each bound is a local midnight with its own offset: a DST change falls inside a week."""
        start = datetime.combine(monday, time()).astimezone()
        return cls(start, datetime.combine(monday + timedelta(days=7), time()).astimezone())

    @classmethod
    def covered(cls, now: datetime) -> Week:
        """The last complete ISO week before ``now``."""
        local = now.astimezone()
        return cls.starting(local.date() - timedelta(days=local.weekday() + 7))

    def previous(self) -> Week:
        return Week.starting(self.start.date() - timedelta(days=7))


@dataclass
class Weekly:
    week: Week
    lines: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    missed_gates: list[str] = field(default_factory=list)  # gate names: they demote (ADR-067)

    @property
    def status(self) -> str:
        return FAILED if self.reasons else OK

    def markdown(self) -> str:
        head = [
            f"# Rapport hebdomadaire {self.week.id}",
            "",
            f"- Semaine : du {self.week.start:%d/%m/%Y} au "
            f"{self.week.end - timedelta(days=1):%d/%m/%Y}",
            f"- Statut : {self.status}",
            *[f"  - {reason}" for reason in self.reasons],
            "- Écrit sans LLM : chaque chiffre vient de la source citée (R1).",
            "",
        ]
        return "\n".join(head + self.lines) + "\n"


def weekly_path(root: Path, week: Week) -> Path:
    return root / REPORTS_DIR / f"hebdo-{week.id}.md"


def _journal_entries(journal: AuditJournal) -> Iterator[tuple[dict[str, Any], Any]]:
    if not journal.path.exists():
        return
    with journal.path.open(encoding="utf-8") as lines:
        for number, line in enumerate(lines, start=1):
            try:
                entry = json.loads(line)
                ref = entry.get("payload_ref")
                payload = journal.read_payload(ref) if isinstance(ref, str) else None
                datetime.fromisoformat(entry["ts"])
            except (AuditError, OSError, ValueError, KeyError, TypeError, AttributeError):
                raise ReportError(f"journal illisible à la ligne {number}") from None
            yield entry, payload


def _in(week: Week, entry: Mapping[str, Any]) -> bool:
    return week.start <= datetime.fromisoformat(entry["ts"]) < week.end


def _section_journal(weekly: Weekly, journal: AuditJournal) -> None:
    events: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    refusals = notifications = learning = 0
    for entry, payload in _journal_entries(journal):
        if not _in(weekly.week, entry):
            continue
        events[entry["event"]] += 1
        data = payload if isinstance(payload, Mapping) else {}
        if entry["event"] == "DECISION" and entry["actor"] == "orchestrator":
            statuses[str(data.get("status", "inconnu"))] += 1
            guard = data.get("guard")
            refusals += isinstance(guard, Mapping) and guard.get("decision") == "refus"
        notifications += entry["event"] == "POLICY" and "notification" in data
        learning += entry["event"] == "LEARNING"
    lines = [
        "## Journal d'audit (source : var/audit/audit.jsonl)",
        "",
        f"- Entrées de la semaine : {sum(events.values())}",
        "- Par événement : "
        + (", ".join(f"{k} {v}" for k, v in sorted(events.items())) or "aucune"),
        f"- Requêtes : {sum(statuses.values())} ; refus à l'entrée : {refusals}",
        "- Statuts des requêtes : "
        + (", ".join(f"{k} {v}" for k, v in sorted(statuses.items())) or "aucun"),
        f"- Incidents (KILL, ERROR) : {sum(events[e] for e in INCIDENT_EVENTS)} ; "
        f"alertes envoyées : {notifications}",
        f"- Entrées d'apprentissage (LEARNING) : {learning}",
        "",
    ]
    weekly.lines += lines


def _section_evals(weekly: Weekly, report_path: Path) -> None:
    weekly.lines += ["## Évals hors ligne (source : var/evals/offline/report.json)", ""]
    if not report_path.is_file():
        weekly.reasons.append("aucun rapport d'évals hors ligne")
        weekly.lines += ["- Aucun rapport : `cerveau eval` n'a pas tourné.", ""]
        return
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        created = datetime.fromisoformat(report["created"])
        suites = report["suites"]
        costs = report["costs"]
    except (OSError, ValueError, KeyError, TypeError):
        raise ReportError("rapport d'évals illisible") from None
    if created < weekly.week.start:
        weekly.reasons.append(f"évals non rejouées depuis le {created:%d/%m/%Y}")
    weekly.lines += [
        f"- Run {report.get('run')} du {created:%d/%m/%Y %H:%M}, mode {report.get('mode')}",
        f"- Coûts du run ({'simulés' if costs.get('simulated') else 'réels'}) : "
        f"{costs.get('total_eur')} € pour {costs.get('requests')} requêtes",
        "",
        "| Suite | Cas réussis | Violations R5 |",
        "|---|---|---|",
    ]
    gates: list[str] = []
    groups: list[str] = []
    for suite in suites:
        weekly.lines.append(
            f"| {suite['suite']} | {suite['passed']}/{suite['cases']} | {suite['r5_breaches']} |"
        )
        for group in suite.get("groups", []):
            groups.append(
                f"| {suite['suite']} | {group['name']} | {group['passed']}/{group['cases']} "
                f"| {group['rate']} | {group['threshold']} |"
            )
        for gate in suite.get("gates", []):
            state = "atteint" if gate["passed"] else "MANQUÉ"
            gates.append(
                f"- {gate['suite']} · {gate['name']} : {gate['measured']} "
                f"(seuil {gate['threshold']}) {state}"
            )
            if not gate["passed"]:
                weekly.reasons.append(f"seuil manqué : {gate['suite']} · {gate['name']}")
                weekly.missed_gates.append(str(gate["name"]))
    weekly.lines += ["", "Scores par groupe (packs) :", ""]
    weekly.lines += ["| Suite | Groupe | Réussis | Taux | Seuil |", "|---|---|---|---|---|"]
    weekly.lines += groups or ["| — | — | — | — | — |"]
    weekly.lines += ["", "Seuils :", "", *(gates or ["- aucun"]), ""]


def _section_calibration(weekly: Weekly, forecasts: Path) -> None:
    weekly.lines += ["## Calibration (source : registre des prévisions)", ""]
    if not forecasts.is_file():
        weekly.lines += ["- Registre absent : aucune prévision enregistrée.", ""]
        return
    try:
        with ForecastStore.open(forecasts, read_only=True) as store:
            pairs = store.probability_pairs()
            overdue = len(store.overdue(weekly.week.end))
    except (ForecastError, sqlite3.Error, OSError, ValueError) as exc:
        raise ReportError(f"registre des prévisions illisible ({type(exc).__name__})") from None
    weekly.lines.append(f"- Prévisions échues non résolues : {overdue}")
    if not pairs:
        weekly.lines += ["- Aucune probabilité résolue : Brier non calculable.", ""]
        return
    try:
        scores = probability_scores(pairs)
    except CalibrationError:
        raise ReportError("prévisions résolues invalides") from None
    weekly.lines += [
        f"- Probabilités résolues : {scores.count} ; Brier {scores.brier:.4f} ; "
        f"fiabilité {scores.reliability:.4f} ; résolution {scores.resolution:.4f}",
        "",
    ]


def _section_costs(weekly: Weekly, journal: AuditJournal, now: datetime) -> None:
    try:
        spending = read_spending(journal, now)
    except LedgerError:
        raise ReportError("dépenses illisibles dans le journal") from None
    weekly.lines += [
        "## Coûts réels (source : journal, D9)",
        "",
        f"- Mois en cours ({spending.month_key}) : {spending.month_eur} €",
        f"- Jour du rapport ({spending.day_key}) : {spending.day_eur} €",
        "",
    ]


def _section_learning(weekly: Weekly, history: Path) -> None:
    weekly.lines += ["## Porte d'apprentissage (source : var/learning/champions.jsonl)", ""]
    keys: set[tuple[str, str]] = set()
    if history.is_file():
        for number, line in enumerate(history.read_text(encoding="utf-8").splitlines(), 1):
            try:
                record = json.loads(line)
                keys.add((str(record["pack"]), str(record["section"])))
            except (ValueError, KeyError, TypeError):
                raise ReportError(
                    f"historique des champions illisible à la ligne {number}"
                ) from None
    rows = []
    for pack, section in sorted(keys):
        try:
            stack = standing(history, pack, section)
        except ChampionError as exc:
            raise ReportError(str(exc)) from None
        if stack:
            rows.append(
                f"- {pack}/{section} : {len(stack)} promotion(s) en service, "
                f"dernière le {stack[-1].ts:%d/%m/%Y}"
            )
    weekly.lines += [*(rows or ["- Aucune promotion en service : couche apprise d'origine."])]
    weekly.lines += ["- Plugins hors SLO : non mesuré (désactivation auto bloquée, R7).", ""]


def build_weekly(
    root: Path,
    journal: AuditJournal,
    now: datetime,
    *,
    eval_report: Path,
    forecasts: Path,
    history: Path,
) -> Weekly:
    """The report of the week covered at ``now``; a source that cannot be read fails it."""
    weekly = Weekly(Week.covered(now))
    for name, section in (
        ("évals", lambda: _section_evals(weekly, eval_report)),
        ("calibration", lambda: _section_calibration(weekly, forecasts)),
        ("coûts", lambda: _section_costs(weekly, journal, now)),
        ("journal", lambda: _section_journal(weekly, journal)),
        ("apprentissage", lambda: _section_learning(weekly, history)),
    ):
        try:
            section()
        except ReportError as exc:
            weekly.reasons.append(f"{name} : {exc}")
            weekly.lines += [f"- Section {name} en échec : {exc}", ""]
    return weekly


def record(journal: AuditJournal, weekly: Weekly, text: str, now: datetime) -> None:
    """The ``scheduler`` entry of a run: week, status and the report's hash (R11)."""
    journal.append(
        actor="scheduler",
        event="DECISION",
        request_id=f"hebdo-{weekly.week.id}",
        payload={
            "status": WEEKLY_STATUS,
            "week": weekly.week.id,
            "result": weekly.status,
            "reasons": len(weekly.reasons),
            "digest": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
        },
        now=now,
    )


def streak(journal: AuditJournal, now: datetime) -> int:
    """Consecutive weeks, back from the last covered one, whose latest weekly run is ``ok``."""
    results: dict[str, str] = {}
    for entry, payload in _journal_entries(journal):
        if (
            entry["actor"] == "scheduler"
            and isinstance(payload, Mapping)
            and payload.get("status") == WEEKLY_STATUS
        ):
            results[str(payload.get("week"))] = str(payload.get("result"))
    count, week = 0, Week.covered(now)
    while results.get(week.id) == OK:
        count += 1
        week = week.previous()
    return count
