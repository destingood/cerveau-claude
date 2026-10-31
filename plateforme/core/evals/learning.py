"""The learning loop's eval cases (plan §7 of phase 7): its own code, with no model, offline.

A case runs, in a temporary home, what ``cerveau feedback``, ``cerveau learn`` and ``cerveau
report weekly`` run: « mauvais » verdicts with their notes on routed requests, the harvest of
patterns, a challenger proposed for each pattern kept, writes aimed past the learned layer, a
promotion asked on two synthetic eval reports, forecasts made and resolved, and the weekly report.
The configuration is the repository's, read only; ``min_support`` and ``max_feedback_per_user``,
still ``A_DEFINIR``, are the case's. Nothing reaches ``var/`` nor ``learned/``.

The checks are deterministic: the steps refused, what the harvest kept, capped and set aside, the
challengers written, the gate's verdict, that no note ever became a lesson (R5), that nothing was
put in service, that the core, the golden sets and the thresholds are untouched (R9), and that the
journal's chain holds (R11).
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import time as clock
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from core.audit.chain import AuditJournal, verify
from core.config import BlockedFeatureError, load_config
from core.config.loader import Config
from core.evals.cases import (
    Case,
    ExpectLearning,
    LearningFixture,
    LearningForecastFixture,
    LearningPromotionFixture,
    LearningStep,
    LearningWeeklyFixture,
)
from core.evals.checks import Check, _found
from core.learning.champion import ChampionError, promote
from core.learning.feedback import FeedbackError, give_feedback
from core.learning.forecasts import FORECAST_EVENT, ForecastError, ForecastStore
from core.learning.gate import LEARNING_EVENT, GateError, Verdict, compare
from core.learning.layer import LockedCoreError, snapshot, writable, write_section
from core.learning.patterns import BAD, Pattern, PatternError, harvest, propose
from core.reports.weekly import build_weekly

NOW = datetime(2026, 10, 29, 7, 0, tzinfo=UTC)  # a Thursday: the report covers the week before
REFUSALS = (
    FeedbackError,
    PatternError,
    LockedCoreError,
    ChampionError,
    GateError,
    BlockedFeatureError,
    ForecastError,
)
GOLDEN_CASES = 30  # enough for a held-out set at 20 % (D6)
LOST = {"comportement": ("behaviors", "comportement-a"), "red_team": ("injection", "red-team-a")}


class _AsIs:
    """A pseudonymiser that changes nothing: the notes are synthetic, Presidio is not needed."""

    def pseudonymise(self, text: str) -> str:
        return text

    def counts(self) -> dict[str, int]:
        return {}


@dataclass
class LearningRun:
    refused: list[tuple[LearningStep, str]] = field(default_factory=list)
    patterns: int = 0
    capped: int = 0
    notes_aside: int = 0
    challengers: list[Path] = field(default_factory=list)
    lessons: list[str] = field(default_factory=list)
    verdict: Verdict | None = None
    in_service: dict[str, str] = field(default_factory=dict)  # the run's learned layer, after
    promotions: int = 0  # LEARNING entries of the journal
    forecasts: int = 0  # FORECAST entries of the journal
    texts: list[str] = field(default_factory=list)  # lessons, journal and report: what is shown
    markdown: str = ""
    journal_errors: list[str] = field(default_factory=list)
    core_changed: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0


def _protected(root: Path) -> dict[str, str]:
    """Hashes of what learning must never touch: configuration, golden sets, learned layer."""
    files = [*sorted((root / "config").glob("*.yaml"))]
    files += sorted(root.glob("domain_packs/*/evals/golden.jsonl"))
    found = {path.relative_to(root).as_posix(): path.read_bytes() for path in files}
    found |= {f"learned/{k}": v.encode() for k, v in snapshot(root / "learned").items()}
    return {name: hashlib.sha256(body).hexdigest() for name, body in found.items()}


def _refuse(run: LearningRun, step: LearningStep, exc: Exception) -> None:
    run.refused.append((step, f"{type(exc).__name__} : {exc}"))


def _feedback(fixture: LearningFixture, journal: AuditJournal, store: Path) -> list[str]:
    """One routed request per note and per bare verdict; returns the steps' refusals."""
    errors: list[str] = []
    notes: list[str | None] = [*fixture.notes, *([None] * fixture.bare)]
    for number, note in enumerate(notes, 1):
        request = f"req-{number:03d}"
        journal.append(
            actor="orchestrator",
            event="DECISION",
            request_id=request,
            payload={"status": "complete", "route": {"domain": fixture.pack}},
            now=NOW,
        )
        try:
            give_feedback(journal, store, request, BAD, note, pseudonymiser=_AsIs, now=NOW)
        except FeedbackError as exc:
            errors.append(str(exc))
    return errors


def _propose(fixture: LearningFixture, run: LearningRun, kept: tuple[Pattern, ...], home: Path):
    if fixture.lesson is not None and not kept:
        kept = (Pattern(fixture.pack, "retour_mauvais", fixture.min_support, 1),)
    lesson = fixture.lesson
    for pattern in kept:
        try:
            if lesson is None:
                where = propose(pattern, home / "challengers", learned_dir=home / "learned")
            else:
                where = propose(
                    pattern,
                    home / "challengers",
                    drafter=lambda _pattern: lesson,
                    learned_dir=home / "learned",
                )
        except REFUSALS as exc:
            _refuse(run, "lecon", exc)
            continue
        run.challengers.append(where)
        run.lessons += [p.read_text(encoding="utf-8") for p in sorted(where.rglob("*.md"))]


def _targets(fixture: LearningFixture, run: LearningRun, root: Path, home: Path) -> None:
    """Each target as a pack the layer is asked to write (in a directory of its own, never the
    run's learned layer), then as a path of the repository, only tested, never written."""
    for target in fixture.targets:
        try:
            write_section(target, "lessons", "Leçon sans consigne.", home / "cibles")
        except REFUSALS as exc:
            _refuse(run, "ecriture", exc)
        if writable(root / target, root / "learned"):
            continue  # a path of the closed list: allowed, so not refused (never written here)
        _refuse(run, "chemin", LockedCoreError(f"chemin hors de la couche apprise : {target}"))


def _reports(fixture: LearningPromotionFixture) -> tuple[dict[str, Any], dict[str, Any]]:
    keys = [("golden", f"golden-{n:02d}") for n in range(1, GOLDEN_CASES + 1)]
    keys += list(LOST.values())
    lost = {LOST[kind] for kind in fixture.lost}

    def result(key: tuple[str, str], *, challenger: bool) -> dict[str, Any]:
        golden = key[0] == "golden"
        score = (7.0 if fixture.forged else 0.9) if challenger and golden else 0.8
        passed = not (challenger and key in lost)
        return {"suite": key[0], "case": key[1], "passed": passed, "score": score}

    champion = {"mode": fixture.mode, "results": [result(k, challenger=False) for k in keys]}
    theirs = [result(k, challenger=True) for k in keys]
    theirs[0]["r5_breaches"] = fixture.r5
    challenger: dict[str, Any] = {"mode": fixture.mode, "results": theirs}
    if fixture.forged:  # what a challenger would claim for itself: never read (R1)
        challenger |= {"verdict": "promouvable", "held_out": {"challenger_mean": 1.0}}
    return champion, challenger


def _promotion(
    fixture: LearningFixture, run: LearningRun, config: Config, journal: AuditJournal, home: Path
) -> None:
    asked = fixture.promotion
    if asked is None:
        return
    champion, challenger = _reports(asked)
    learning = config.evals.learning
    margin, minimum = (0.0, 1) if asked.thresholds else (None, None)
    run.verdict = compare(
        champion,
        challenger,
        holdout_percent=learning.holdout_percent,
        margin=margin,
        min_cases=minimum,
    )
    where = run.challengers[-1] if run.challengers else home / "challengers" / "aucun"
    try:
        promote(
            config,
            champion,
            challenger,
            where,
            fixture.pack,
            "lessons",
            journal=journal,
            history=home / "champions.jsonl",
            now=NOW,
            learned_dir=home / "learned",
        )
    except REFUSALS as exc:
        _refuse(run, "promotion", exc)


def _forecast(store: ForecastStore, item: LearningForecastFixture, run: LearningRun) -> None:
    made = NOW - timedelta(days=30)
    try:
        forecast = store.add(
            domain="generaliste",
            kind=item.kind,
            statement="Prévision synthétique de l'éval d'apprentissage.",
            value=item.value,
            due_on=(made + timedelta(days=item.due_days)).date(),
            now=made,
        )
    except ForecastError as exc:
        _refuse(run, "prevision", exc)
        return
    outcome = item.outcome
    tries = [made + timedelta(days=1)] if item.early else []
    tries += [] if outcome is None else [made + timedelta(days=item.due_days + 5)]
    for when in tries:
        try:
            store.resolve(
                forecast.forecast_id,
                outcome=outcome if isinstance(outcome, bool) else None,
                actual=None if isinstance(outcome, bool) else outcome,
                source="éval d'apprentissage",
                now=when,
            )
        except ForecastError as exc:
            _refuse(run, "resolution", exc)


def _weekly(
    fixture: LearningWeeklyFixture, run: LearningRun, journal: AuditJournal, home: Path
) -> None:
    report = home / "report.json"
    rate = 1.0 if fixture.gate_passed else 0.9
    gate = {
        "suite": "behaviors",
        "name": "taux de réussite : comportements",
        "measured": rate,
        "threshold": 0.95,
        "passed": fixture.gate_passed,
    }
    suite = {"suite": "behaviors", "cases": 10, "passed": round(rate * 10), "r5_breaches": 0}
    body = {
        "created": (NOW - timedelta(days=2)).isoformat(),
        "run": "eval-apprentissage",
        "mode": "offline",
        "summary": fixture.summary,
        "suites": [suite | {"groups": [], "gates": [gate]}],
        "costs": {"simulated": True, "total_eur": "0.00", "requests": 0},
    }
    report.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    weekly = build_weekly(
        home,
        journal,
        NOW,
        eval_report=report,
        forecasts=home / "forecasts.db",
        history=home / "champions.jsonl",
    )
    run.markdown = weekly.markdown()


def _journal(journal: AuditJournal, run: LearningRun) -> None:
    if not journal.path.is_file():
        return
    for line in journal.path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        run.promotions += entry.get("event") == LEARNING_EVENT
        run.forecasts += entry.get("event") == FORECAST_EVENT
        payload = journal.read_payload(entry["payload_ref"]) if entry.get("payload_ref") else None
        run.texts.append(json.dumps([entry, payload], ensure_ascii=False))
    report = verify(journal.path)
    run.journal_errors = [str(error) for error in report.errors]


def _run(case: Case, root: Path, home: Path) -> LearningRun:
    fixture = case.learning
    if fixture is None:
        raise ValueError(f"{case.id} : cas sans learning")
    run = LearningRun()
    before = _protected(root)
    config = load_config(root / "config")
    journal = AuditJournal(home / "audit" / "journal.jsonl")
    store = home / "feedback" / "feedback.jsonl"
    for error in _feedback(fixture, journal, store):
        _refuse(run, "retour", FeedbackError(error))
    found = harvest(
        journal,
        store,
        min_support=fixture.min_support,
        max_feedback_per_user=fixture.max_feedback_per_user,
    )
    run.patterns, run.capped, run.notes_aside = (
        len(found.patterns),
        found.capped,
        found.notes_set_aside,
    )
    _propose(fixture, run, found.patterns, home)
    _targets(fixture, run, root, home)
    _promotion(fixture, run, config, journal, home)
    if fixture.forecasts:
        with ForecastStore.open(home / "forecasts.db", journal=journal) as forecasts:
            for item in fixture.forecasts:
                _forecast(forecasts, item, run)
    if fixture.weekly is not None:
        _weekly(fixture.weekly, run, journal, home)
    run.in_service = snapshot(home / "learned")
    _journal(journal, run)
    run.texts += [*run.lessons, *run.in_service.values(), run.markdown]
    after = _protected(root)
    run.core_changed = sorted(
        k for k in before.keys() | after.keys() if before.get(k) != after.get(k)
    )
    return run


def run_learning(case: Case, root: Path) -> LearningRun:
    """One learning case, in a temporary home; the same deterministic run in both modes."""
    started = clock.monotonic()
    with tempfile.TemporaryDirectory(
        prefix="cerveau-eval-learning-", ignore_cleanup_errors=True
    ) as directory:
        run = _run(case, root, Path(directory))
    run.elapsed_s = round(clock.monotonic() - started, 3)
    return run


def learning_checks(case: Case, run: LearningRun) -> list[Check]:
    """The deterministic checks of a learning case (module docstring)."""
    fixture, expect = case.learning, case.expect.learning
    if fixture is None or expect is None:
        raise ValueError(f"{case.id} : cas sans learning")
    r5 = "R5" if case.suite == "injection" else ""
    checks: list[Check] = []

    def add(name: str, passed: bool, detail: str, rule: str = "") -> None:
        checks.append(Check(name, passed, "" if passed else detail, rule))

    steps = tuple(step for step, _ in run.refused)
    detail = f"{steps} ≠ {expect.refused} ; " + " | ".join(why for _, why in run.refused)
    add("étapes refusées", steps == expect.refused, detail[:300], r5)
    _counts(add, expect, run)
    if expect.verdict is not None:
        status = None if run.verdict is None else run.verdict.status
        add("verdict de la porte", status == expect.verdict, f"{status} ≠ {expect.verdict}", "R1")
    reasons = () if run.verdict is None else run.verdict.reasons
    missing = [text for text in expect.reasons if not _found(text, reasons)]
    add("raisons de la porte", not missing, ", ".join(missing))
    copied = [n for n in fixture.notes if n.strip() and _found(n.strip(), run.lessons)]
    add("aucune note devenue leçon", not copied, "; ".join(copied)[:200], "R5")
    put = sorted(run.in_service)
    add("rien de mis en service", not put and not run.promotions, f"{put}, {run.promotions}", "R9")
    add("noyau, golden et seuils intacts", not run.core_changed, ", ".join(run.core_changed), "R9")
    missing = [text for text in case.expect.mentions if not _found(text, [run.markdown])]
    add("mentions", not missing, ", ".join(missing))
    present = [text for text in case.expect.absent if _found(text, run.texts)]
    add("absences", not present, ", ".join(present), r5)
    add("journal chaîné", not run.journal_errors, "; ".join(run.journal_errors)[:200], "R11")
    return checks


def _counts(add: Any, expect: ExpectLearning, run: LearningRun) -> None:
    for name, wanted, got in (
        ("motifs retenus", expect.patterns, run.patterns),
        ("retours plafonnés", expect.capped, run.capped),
        ("notes mises de côté", expect.notes_aside, run.notes_aside),
        ("challengers écrits", expect.challengers, len(run.challengers)),
        ("prévisions journalisées", expect.forecasts, run.forecasts),
    ):
        if wanted is not None:
            add(name, got == wanted, f"{got} ≠ {wanted}")
