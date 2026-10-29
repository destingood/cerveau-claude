"""The report of one eval run (plan section 9): gates, pass rates, R5, sourcing, costs, judgements.

It reads the case results of the run (``<out>/cases/<suite>/<id>.json``) and checks them against
the thresholds that the suites and ``config/evals.yaml`` declare; a threshold is never lowered
here (R9). A case without a result of this run counts as failed, so a crash cannot pass a gate.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from core.config.loader import Config
from core.evals.cases import REPO_ROOT, Case, Suite, load_cases, suite_files
from core.evals.checks import Mode
from core.evals.harness import CASES_DIR
from core.evals.judge import CRITERIA, golden_threshold
from core.learning.layer import LEARNED_DIR, layer_digest, snapshot

REPORT_MD = "report.md"
REPORT_JSON = "report.json"
CENT = Decimal("0.0001")


@dataclass(frozen=True)
class Gate:
    suite: str
    name: str
    threshold: str
    measured: str
    passed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "name": self.name,
            "threshold": self.threshold,
            "measured": self.measured,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class Group:
    name: str
    cases: int
    passed: int
    threshold: float  # pass rate a group must reach
    members: tuple[str, ...] = ()  # case ids

    @property
    def rate(self) -> float:
        return round(self.passed / self.cases, 3) if self.cases else 0.0

    def as_dict(self) -> dict[str, Any]:
        keys = ("name", "cases", "passed", "threshold")
        return {**{key: getattr(self, key) for key in keys}, "rate": self.rate}


@dataclass
class SuiteReport:
    suite: Suite
    results: list[dict[str, Any]]
    missing: list[str]
    groups: list[Group]
    gates: list[Gate] = field(default_factory=list)

    @property
    def cases(self) -> int:
        return len(self.results) + len(self.missing)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r["passed"])

    @property
    def errors(self) -> list[dict[str, Any]]:
        return [r for r in self.results if r["error"] is not None]

    @property
    def r5_breaches(self) -> int:
        return sum(int(r["r5_breaches"]) for r in self.results)

    @property
    def sourcing(self) -> tuple[int, int]:
        """(cases that must cite their sources, cases that do)."""
        relevant = [r for r in self.results if r["sourcing"] is not None]
        return len(relevant), sum(1 for r in relevant if r["sourcing"])

    @property
    def judged(self) -> list[dict[str, Any]]:
        return [r for r in self.results if r["judgement"] is not None]

    def as_dict(self) -> dict[str, Any]:
        required, cited = self.sourcing
        return {
            "suite": self.suite,
            "cases": self.cases,
            "passed": self.passed,
            "missing": self.missing,
            "errors": [r["case"] for r in self.errors],
            "r5_breaches": self.r5_breaches,
            "sourcing": {"required": required, "cited": cited},
            "groups": [group.as_dict() for group in self.groups],
            "gates": [gate.as_dict() for gate in self.gates],
        }


# --- statistics ----------------------------------------------------------------------------------


def percentile(values: Sequence[Decimal], q: float) -> Decimal:
    """Nearest-rank percentile; 0 for no value."""
    if not values:
        return Decimal(0)
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / len(values) if values else Decimal(0)


def _money(value: Decimal) -> str:
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def _rate(part: int, whole: int) -> str:
    return f"{part}/{whole} ({part / whole:.0%})" if whole else "0/0"


# --- reading the results -------------------------------------------------------------------------


def load_results(out_dir: Path, suite: Suite, run: str) -> dict[str, dict[str, Any]]:
    """The results of this run only: an older file of the same case is ignored."""
    results = {}
    for path in sorted((out_dir / CASES_DIR / suite).glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("run") == run and data.get("suite") == suite:
            results[data["case"]] = data
    return results


def _thresholds(suite: Suite, config: Config, root: Path) -> dict[str, float]:
    """Pass rate per group: the file's own, never below ``config/evals.yaml`` (R9). A case that
    names its own group (a theme of the file) takes the file's rate too."""
    floor = float(config.evals.thresholds.behavior_suites_R1_to_R5_pass_rate)
    thresholds: dict[str, float] = {}
    for file in suite_files(suite, root):
        for group in dict.fromkeys([file.group, *(case.group for case in file.cases)]):
            thresholds[group] = max(thresholds.get(group, 0.0), file.pass_rate, floor)
    return thresholds


def suite_report(
    suite: Suite,
    cases: Sequence[Case],
    results: dict[str, dict[str, Any]],
    *,
    mode: Mode,
    config: Config,
    root: Path = REPO_ROOT,
) -> SuiteReport:
    found = [results[case.id] for case in cases if case.id in results]
    missing = [case.id for case in cases if case.id not in results]
    thresholds = _thresholds(suite, config, root) if suite != "golden" else {}
    names = list(dict.fromkeys(case.group for case in cases))
    groups = []
    for name in names:
        members = [case.id for case in cases if case.group == name]
        passed = sum(1 for case_id in members if results.get(case_id, {}).get("passed"))
        groups.append(Group(name, len(members), passed, thresholds.get(name, 1.0), tuple(members)))
    report = SuiteReport(suite, found, missing, groups)
    report.gates = _gates(report, mode, config)
    return report


def _gates(report: SuiteReport, mode: Mode, config: Config) -> list[Gate]:
    suite = report.suite
    complete = not report.missing and not report.errors
    gates = [
        Gate(
            suite,
            "cas exécutés sans erreur",
            f"{report.cases}/{report.cases}",
            f"{len(report.results) - len(report.errors)}/{report.cases}",
            complete,
        ),
        Gate(suite, "violations R5", "0", str(report.r5_breaches), report.r5_breaches == 0),
    ]
    required, cited = report.sourcing
    if required:
        gates.append(Gate(suite, "sourçage", "100 %", _rate(cited, required), cited == required))
    if suite == "golden" and mode == "live":  # one gate per pack, at the pack's own threshold
        for group in report.groups:
            threshold = golden_threshold(config, group.name)
            scores = [
                Decimal(r["judgement"]["score"])
                for r in report.judged
                if r["case"] in group.members
            ]
            average = mean(scores)
            gates.append(
                Gate(
                    suite,
                    f"score moyen du juge : {group.name}",
                    f"≥ {threshold}",
                    f"{average:.2f} sur {len(scores)} cas jugés",
                    bool(scores) and average >= threshold,
                )
            )
        return gates
    for group in report.groups:  # offline golden: every deterministic check, every case
        gates.append(
            Gate(
                suite,
                f"taux de réussite : {group.name}",
                f"≥ {group.threshold:.0%}",
                _rate(group.passed, group.cases),
                group.cases > 0 and group.rate >= group.threshold,
            )
        )
    return gates


# --- the whole run -------------------------------------------------------------------------------


@dataclass
class Report:
    run: str
    mode: Mode
    campaign: str | None
    config_digest: str
    created: datetime
    suites: list[SuiteReport]
    review_sample: int
    learned: str | None = None  # digest of the learned layer the run used (ADR-065)

    @property
    def gates(self) -> list[Gate]:
        return [gate for suite in self.suites for gate in suite.gates]

    @property
    def passed(self) -> bool:
        return all(gate.passed for gate in self.gates)

    def results(self) -> list[dict[str, Any]]:
        return [r for suite in self.suites for r in suite.results]

    def costs(self) -> dict[str, str]:
        values = [Decimal(r["cost_eur"]) for r in self.results() if r["error"] is None]
        judge = sum((Decimal(r["judge_cost_eur"]) for r in self.results()), Decimal(0))
        return {
            "requests": str(len(values)),
            "total_eur": _money(sum(values, Decimal(0))),
            "mean_eur": _money(mean(values)),
            "p50_eur": _money(percentile(values, 0.5)),
            "p95_eur": _money(percentile(values, 0.95)),
            "judge_total_eur": _money(judge),
        }

    def latency(self) -> dict[str, str]:
        values = [Decimal(str(r["elapsed_s"])) for r in self.results() if r["error"] is None]
        return {
            "mean_s": f"{mean(values):.2f}",
            "p50_s": f"{percentile(values, 0.5):.2f}",
            "p95_s": f"{percentile(values, 0.95):.2f}",
        }

    def sample(self) -> list[dict[str, Any]]:
        """Judgements for Lucas's review: a reproducible draw, not the best or the worst."""
        judged = [r for suite in self.suites for r in suite.judged]

        def draw(result: dict[str, Any]) -> str:
            return hashlib.sha256(f"{self.run}:{result['case']}".encode()).hexdigest()

        return sorted(judged, key=draw)[: self.review_sample]

    def to_json(self) -> dict[str, Any]:
        return {
            "run": self.run,
            "mode": self.mode,
            "campaign": self.campaign,
            "config": self.config_digest,
            "learned": self.learned,
            "created": self.created.isoformat(timespec="seconds"),
            "passed": self.passed,
            "costs": {**self.costs(), "simulated": self.mode == "offline"},
            "latency": self.latency(),
            "regression": "bloquée : regression_block_delta vaut A_DEFINIR (config/evals.yaml)",
            "suites": [suite.as_dict() for suite in self.suites],
            "review": [
                {"case": r["case"], **{k: v for k, v in r["judgement"].items() if k != "case"}}
                for r in self.sample()
            ],
            "results": self.results(),
        }

    def markdown(self) -> str:
        return "\n".join(_markdown(self)) + "\n"


def build_report(
    out_dir: Path,
    suites: Iterable[Suite],
    *,
    mode: Mode,
    run: str,
    config: Config,
    campaign: str | None = None,
    root: Path = REPO_ROOT,
    now: datetime | None = None,
    learned_dir: Path = LEARNED_DIR,
) -> Report:
    reports = [
        suite_report(
            suite,
            load_cases(suite, root),
            load_results(out_dir, suite, run),
            mode=mode,
            config=config,
            root=root,
        )
        for suite in suites
    ]
    return Report(
        run=run,
        mode=mode,
        campaign=campaign,
        config_digest=config.digest,
        created=now or datetime.now().astimezone(),
        suites=reports,
        review_sample=int(config.evals.judge_human_review_sample_weekly),
        learned=layer_digest(snapshot(learned_dir)),
    )


def write_report(report: Report, *paths: Path) -> list[Path]:
    """``<path>.md`` and ``<path>.json`` for each base path given (without suffix)."""
    written = []
    for base in paths:
        base.parent.mkdir(parents=True, exist_ok=True)
        markdown, data = base.with_suffix(".md"), base.with_suffix(".json")
        markdown.write_text(report.markdown(), encoding="utf-8")
        text = json.dumps(report.to_json(), ensure_ascii=False, indent=2)
        data.write_text(text + "\n", encoding="utf-8")
        written += [markdown, data]
    return written


# --- markdown ------------------------------------------------------------------------------------


def _markdown(report: Report) -> list[str]:
    live = report.mode == "live"
    lines = [
        f"# Rapport d'évals — {report.run}",
        "",
        f"- Mode : {'réel (campagne ' + str(report.campaign) + ')' if live else 'hors ligne'}",
        f"- Date : {report.created.isoformat(timespec='seconds')}",
        f"- Configuration : `{report.config_digest}`",
        f"- Résultat : **{'portes franchies' if report.passed else 'porte(s) en échec'}**",
        "",
    ]
    if not live:
        lines += [
            "> Hors ligne : des modèles scriptés remplacent Claude ; toutes les couches "
            "déterministes tournent pour de vrai (pseudonymisation, contrôle des citations, des "
            "chiffres et des liens, politique). Ce rapport mesure ces couches, pas la qualité "
            "d'un modèle ; le juge ne tourne qu'en mode réel. Coûts **simulés** : tarifs réels, "
            "jetons estimés à 4 caractères par jeton, sans cache.",
            "",
        ]
    lines += [
        "## Portes",
        "",
        "| Suite | Porte | Seuil | Mesuré | Résultat |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {g.suite} | {g.name} | {g.threshold} | {g.measured} | {'✅' if g.passed else '❌'} |"
        for g in report.gates
    ]
    lines += [
        "",
        "Comparaison à la dernière exécution de référence : **bloquée**, "
        "`regression_block_delta` vaut `A_DEFINIR` dans `config/evals.yaml` (décision de Lucas).",
        "",
        "## Suites",
        "",
        "| Suite | Groupe | Cas | Réussis | Taux | Seuil |",
        "|---|---|---|---|---|---|",
    ]
    for suite in report.suites:
        for group in suite.groups:
            lines.append(
                f"| {suite.suite} | {group.name} | {group.cases} | {group.passed} "
                f"| {group.rate:.0%} | {group.threshold:.0%} |"
            )
    costs, latency = report.costs(), report.latency()
    label = "simulé" if not live else "mesuré"
    lines += [
        "",
        "## Coûts et latence par requête",
        "",
        f"- Requêtes : {costs['requests']} ; total ({label}) : {costs['total_eur']} €",
        f"- Coût ({label}) : moyenne {costs['mean_eur']} €, p50 {costs['p50_eur']} €, "
        f"p95 {costs['p95_eur']} €",
        f"- Latence : moyenne {latency['mean_s']} s, p50 {latency['p50_s']} s, "
        f"p95 {latency['p95_s']} s",
    ]
    if live:
        lines.append(f"- Juge (compté dans les budgets) : {costs['judge_total_eur']} €")
    lines += _failures(report)
    if live:
        lines += _review(report)
    return lines


def _failures(report: Report) -> list[str]:
    lines = ["", "## Cas en échec", ""]
    failed = [r for r in report.results() if not r["passed"]]
    missing = [(s.suite, case_id) for s in report.suites for case_id in s.missing]
    if not failed and not missing:
        return [*lines, "Aucun."]
    lines += [f"- `{r['suite']}/{r['case']}` : {r['reason']}" for r in failed]
    lines += [
        f"- `{suite}/{case_id}` : aucun résultat de cette exécution" for suite, case_id in missing
    ]
    return lines


def _review(report: Report) -> list[str]:
    sample = report.sample()
    lines = [
        "",
        f"## Jugements à relire par Lucas ({len(sample)})",
        "",
        "Tirage reproductible (empreinte de l'exécution et du cas), ni les meilleurs ni les pires.",
        "",
        "| Cas | Score | Exactitude | Complétude | Sources | Honnêteté | Format | Factuel |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for result in sample:
        j = result["judgement"]
        grades = " | ".join(str(j["grades"][name]) for name in CRITERIA)
        factual = "oui" if j["factuel"] else "non"
        lines.append(f"| {result['case']} | {j['score']} | {grades} | {factual} |")
    lines.append("")
    lines += [f"- `{r['case']}` : {r['judgement']['justification']}" for r in sample]
    return lines
