"""The score of a Claude Code bench run (ADR-074): code checks, the judge's grades, the gates.

Each case runs the same deterministic checks as the orchestrator's runs (``core/evals/checks.py``:
R5 canaries and hosts, status, format 7.3, calibration, R1 trace of every number and date against
the question, the date of the day and the pages, sourcing), plus three of this bench: every page
cited has an exact extract, every key point not optional is « couvert », and a completeness of 2
agrees with the key points. The score of a case is the mean of the judge's grades
(``core/evals/judge.py::score``), compared with the pack's frozen threshold of
``config/evals.yaml``, which is read, never written (R9).

A case fails with an error, and is not judged, when its answer is missing, malformed or edited
after the judge files were prepared, when its verdict is missing or malformed, or when the judge
is of the answering model's family: a model never grades itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.audit.chain import AuditJournal
from core.config.loader import Config
from core.evals.cases import Case, cached_web
from core.evals.checks import Check, Outcome, run_checks, sourcing_ok
from core.evals.claude_code import (
    ANSWERS_DIR,
    BENCH_DIR,
    LABELS,
    QUESTIONS_DIR,
    VERDICTS_DIR,
    BenchError,
    BenchVerdict,
    Built,
    ExportedSource,
    build_answer,
    case_sources,
    family,
    golden_path,
    is_optional,
    journal_step,
    journaled,
    load_manifest,
    pack_cases,
    read_answer,
    run_dir,
    sha256,
)
from core.evals.harness import CaseResult, cites_a_source, save_result
from core.evals.judge import Judgement, golden_threshold, score
from core.evals.report import Gate, Report, suite_report, write_report
from core.learning.layer import LEARNED_DIR, layer_digest, snapshot

REPORT = "report"
JUDGE_RULE = "juge"


def key_point_checks(case: Case, verdict: BenchVerdict) -> list[Check]:
    """One check per key point that is not optional, then the completeness's coherence."""
    checks = []
    missed = 0
    for point, given in zip(case.expect.key_points, verdict.points, strict=True):
        if is_optional(point):
            continue
        covered = given.verdict == "couvert"
        missed += not covered
        detail = "" if covered else f"{given.verdict} : {given.raison}"
        checks.append(Check(f"point clé {given.n} : {point}", covered, detail, JUDGE_RULE))
    coherent = verdict.completude < 2 or missed == 0
    detail = "" if coherent else "complétude notée 2 avec un point attendu non couvert"
    checks.append(Check("verdict du juge cohérent", coherent, detail, JUDGE_RULE))
    return checks


def citation_checks(built: Built) -> list[Check]:
    """Every page cited exists and has a passage copied word for word (R5, sources)."""
    issues = built.orphans + built.inexact
    detail = f"{built.orphans} numéro(s) sans page, {built.inexact} citation(s) sans extrait exact"
    return [Check("extraits exacts des pages citées", issues == 0, "" if not issues else detail)]


def outcome(
    case: Case, built: Built, sources: list[ExportedSource], today: str, sent: str
) -> Outcome:
    """What the session produced, as the checks of the orchestrator's runs read it."""
    issues = {"citation_orpheline": built.orphans, "citation_inexacte": built.inexact}
    return Outcome(
        case=case,
        mode="claude_code",
        answer=built.answer,
        payload={"verification": {"issues": issues}},
        sent=(sent,),
        read_texts=tuple(source.text for source in sources),
        search_texts=tuple(f"{source.title} {source.snippet}" for source in sources),
        now=today,
    )


def read_verdict(path: Path, case: Case) -> BenchVerdict:
    if not path.is_file():
        raise BenchError("verdict du juge absent")
    try:
        verdict = BenchVerdict.model_validate_json(path.read_text(encoding="utf-8"))
        return verdict.checked(len(case.expect.key_points))
    except (ValidationError, ValueError) as exc:
        reason = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
        raise BenchError(f"verdict du juge invalide : {reason}") from None


def judge_model(verdict: BenchVerdict, agent: str) -> str:
    """The model the judge says it is, when it names a family; else the subagent's own field."""
    return verdict.modele if family(verdict.modele) is not None else agent


@dataclass(frozen=True)
class Scored:
    result: CaseResult
    held_out: bool
    answer_digest: str | None = None
    verdict_digest: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {**self.result.to_json(), "held_out": self.held_out}


def _failed(case: Case, run: str, held: bool, reason: str) -> Scored:
    result = CaseResult(
        case.id, case.suite, case.group, "claude_code", run, False, 0.0, error=reason
    )
    return Scored(result, held)


def score_case(
    case: Case,
    *,
    run: str,
    directory: Path,
    manifest: dict[str, Any],
    table: dict[str, Any],
    threshold: Decimal,
    sources: list[ExportedSource],
    held: bool,
    question: str,
) -> Scored:
    """One case of the run: its checks, its judgement and whether it passes."""
    try:
        path = directory / QUESTIONS_DIR / f"{case.id}.md"
        sent = path.read_text(encoding="utf-8") if path.is_file() else ""
        if sha256(sent) != question:  # what reached the answering model, as exported
            raise BenchError("question absente ou modifiée depuis l'export")
        given, answer_digest = read_answer(directory / ANSWERS_DIR / f"{case.id}.json")
        if table["reponses"].get(case.id) != answer_digest:
            raise BenchError("réponse modifiée après la préparation du juge, ou jamais jugée")
        label = next(lab for lab, cid in table["anonymes"].items() if cid == case.id)
        verdict_path = directory / VERDICTS_DIR / f"{label}.json"
        verdict = read_verdict(verdict_path, case)
        judged_by = judge_model(verdict, table["juge"])
        if family(judged_by) == family(manifest["modele_reponse"]):
            raise BenchError(f"juge du même modèle que la réponse ({judged_by})")
    except BenchError as exc:
        return _failed(case, run, held, str(exc))
    today = manifest["date_du_jour"]
    built = build_answer(given, sources, today)
    seen = outcome(case, built, sources, today, sent)
    checks = (*run_checks(seen), *citation_checks(built), *key_point_checks(case, verdict))
    grades = verdict.grades()
    judgement = Judgement(case.id, grades, score(grades), Decimal(0), judged_by)
    sourcing = sourcing_ok(checks)
    if grades.factuel and sourcing is None:
        sourcing = cites_a_source(seen)
    result = CaseResult(
        case_id=case.id,
        suite=case.suite,
        group=case.group,
        mode="claude_code",
        run=run,
        passed=all(check.passed for check in checks) and judgement.score >= threshold,
        score=float(judgement.score),
        checks=tuple(checks),
        status=built.answer.statut,
        sourcing=sourcing,
        judgement=judgement,
        markdown=seen.markdown,
    )
    verdict_digest = sha256(verdict_path.read_text(encoding="utf-8"))
    return Scored(result, held, answer_digest, verdict_digest)


def _labels(directory: Path, journal: AuditJournal) -> dict[str, Any]:
    """The judge's table, refused when it differs from the one journaled at its preparation."""
    path = directory / LABELS
    entry = journaled(journal, directory.name, "juge")
    if not path.is_file() or entry is None:
        raise BenchError(f"{directory.name} : juge non préparé (`cerveau evals preparer-juge`)")
    text = path.read_text(encoding="utf-8")
    table: dict[str, Any] = json.loads(text)
    if entry.get("anonymes") != sha256(text) or entry.get("reponses") != table["reponses"]:
        raise BenchError(f"{directory.name} : table du juge modifiée depuis sa préparation")
    return table


def _mean(values: list[float]) -> str:
    return f"{sum(values) / len(values):.2f}" if values else "aucun"


@dataclass(frozen=True)
class Scoring:
    report: Report
    scored: list[Scored]
    written: list[Path]


def score_run(
    root: Path,
    run: str,
    *,
    config: Config,
    journal: AuditJournal,
    now: datetime,
    copy: Path | None = None,
    learned_dir: Path = LEARNED_DIR,
    bench: Path | None = None,
) -> Scoring:
    """Scores every exported case, writes the results and the report, journals the digests."""
    directory = run_dir(bench or root / BENCH_DIR, run)
    manifest = load_manifest(directory, journal)
    pack = manifest["pack"]
    if sha256(golden_path(root, pack).read_text(encoding="utf-8")) != manifest["golden"]:
        raise BenchError(f"golden set du pack {pack} modifié depuis l'export : run non comparable")
    table = _labels(directory, journal)
    threshold = golden_threshold(config, pack)
    cases = {case.id: case for case in pack_cases(root, pack)}
    web = cached_web(root)
    scored = [
        score_case(
            cases[item["id"]],
            run=run,
            directory=directory,
            manifest=manifest,
            table=table,
            threshold=threshold,
            sources=list(case_sources(cases[item["id"]], web)),
            held=bool(item["tenu_a_l_ecart"]),
            question=item["question"],
        )
        for item in manifest["cas"]
    ]
    for item in scored:
        path = save_result(item.result, directory)
        path.write_text(json.dumps(item.to_json(), ensure_ascii=False, indent=2) + "\n", "utf-8")
    exported = [cases[item["id"]] for item in manifest["cas"]]
    results = {item.result.case_id: item.to_json() for item in scored}
    suite = suite_report("golden", exported, results, mode="claude_code", config=config, root=root)
    eligible = int(manifest["cas_exportables"])
    judged = sum(1 for item in scored if item.result.error is None)
    suite.gates.append(
        Gate(
            "golden",
            f"cas exportables jugés : {pack}",
            f"{eligible}/{eligible}",
            f"{judged}/{eligible}",
            judged == eligible,
        )
    )
    held = [item.result.score for item in scored if item.held_out and item.result.error is None]
    judges = sorted({item.result.judgement.model for item in scored if item.result.judgement})
    report = Report(
        run=run,
        mode="claude_code",
        campaign=None,
        config_digest=config.digest,
        created=now,
        suites=[suite],
        review_sample=int(config.evals.judge_human_review_sample_weekly),
        learned=layer_digest(snapshot(learned_dir)),
        regression_delta=None
        if isinstance(config.evals.thresholds.regression_block_delta, str)
        else config.evals.thresholds.regression_block_delta,
        bench=(
            ("Pack", pack),
            ("Modèle qui répond (déclaré)", manifest["modele_reponse"]),
            ("Modèle juge", ", ".join(judges) or "aucun"),
            (
                "Cas exportés",
                f"{len(scored)} sur {eligible} exportables ({manifest['cas_du_pack']} au pack)",
            ),
            ("Cas exclus de cet export", str(len(manifest["exclus"]))),
            ("Cas tenus à l'écart", f"{len(held)} jugés, score moyen {_mean(held)}"),
            ("Versions", ", ".join(f"{k} {v}" for k, v in manifest["versions"].items())),
        ),
    )
    bases = [directory / REPORT, *([copy] if copy is not None else [])]
    written = write_report(report, *bases)
    journal_step(
        journal,
        run,
        "notation",
        config,
        rapport=sha256(json.dumps(report.to_json(), ensure_ascii=False, sort_keys=True)),
        reponses={item.result.case_id: item.answer_digest for item in scored},
        verdicts={item.result.case_id: item.verdict_digest for item in scored},
        reussis=sum(1 for item in scored if item.result.passed),
        cas=len(scored),
        portes_franchies=report.passed,
    )
    return Scoring(report, scored, written)
