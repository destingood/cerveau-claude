"""The strategy registry, its fingerprints and the manual promotion check (ADR-027, D14).

One ``domain_packs/finance/strategies/<id>.yaml`` per strategy says, in French, what it bets on
and how it decides, which module implements it, which grid the protocol tries and on which data.
A new strategy is ``recherche``. Only Lucas makes it ``candidate``, by writing an approval by hand
in ``governance/approvals/strategies/<id>.yaml``; no code here writes one. ``promotion_errors``
gives every reason to refuse that status: ``cerveau config check`` fails on any of them.

Two fingerprints make a version: the SHA-256 of the module source (``code_sha256``, the same as
``trials.strategy_code_sha256``) and the SHA-256 of the canonical grid (``grid_sha256``). Any
change to either invalidates the verdict and the approval.
"""

from __future__ import annotations

import hashlib
import importlib
import itertools
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from core.audit import AuditError, AuditJournal
from core.config.loader import Marker
from core.finance.model import (
    ParamName,
    ParamValue,
    Sha256,
    StrategyId,
    canonical_json,
    params_sha256,
)
from core.finance.research.strategy import Strategy
from core.finance.research.trials import source_sha256

REGISTRY_DIR = Path("domain_packs/finance/strategies")
APPROVALS_DIR = Path("governance/approvals/strategies")
STRATEGIES_PACKAGE = "core.finance.research.strategies"
PROTOCOL_COMMAND = "strategy protocol"  # the audit entry that cites a report print
# The store of the synthetic dataset, apart from the point-in-time base of `cerveau finance sync`.
SYNTHETIC_STORE = Path("var/finance/research/synthetique.db")
MAX_CONFIGURATIONS = 500  # a grid beyond it is refused: the protocol runs each one [Hypothèse]

Status = Literal["recherche", "candidate"]
DataKind = Literal["synthetiques", "reelles"]
CostsKind = Literal["fictifs", "reels"]
Text = Annotated[str, Field(min_length=1)]


class RegistryError(ValueError):
    """A registry entry, an approval or a strategy module that cannot be used."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Period(_Strict):
    debut: date
    fin: date

    @model_validator(mode="after")
    def _ordered(self) -> Period:
        if self.debut >= self.fin:
            raise ValueError(f"période {self.debut} → {self.fin} : le début précède la fin")
        return self


class Constraint(_Strict):
    """Only the points where ``parametre`` < ``inferieur_a`` are tried."""

    parametre: ParamName
    inferieur_a: ParamName


class StrategySpec(_Strict):
    id: StrategyId
    nom: Text
    statut: Status
    hypothese: Text
    regle: Text
    module: Text
    classe: Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
    frequence: Literal["quotidienne"]
    donnees: DataKind
    source: Text
    univers: Annotated[list[Text], Field(min_length=1)]
    periode: Period
    capital_initial_eur: Annotated[float, Field(gt=0, allow_inf_nan=False)] | Marker
    grille: Annotated[
        dict[ParamName, Annotated[list[ParamValue], Field(min_length=1)]], Field(min_length=1)
    ]
    contraintes: list[Constraint] = []

    @model_validator(mode="after")
    def _coherent(self) -> StrategySpec:
        expected = f"{STRATEGIES_PACKAGE.replace('.', '/')}/{self.id}.py"
        if self.module != expected:
            raise ValueError(f"module {self.module} : {expected} attendu (ADR-027)")
        if len(set(self.univers)) != len(self.univers):
            raise ValueError("instrument en double dans l'univers")
        for name, values in self.grille.items():
            if len({canonical_json(v) for v in values}) != len(values):
                raise ValueError(f"grille › {name} : valeur en double")
        for rule in self.contraintes:
            for name in (rule.parametre, rule.inferieur_a):
                if name not in self.grille:
                    raise ValueError(f"contrainte sur {name}, absent de la grille")
                if any(isinstance(v, bool | str) for v in self.grille[name]):
                    raise ValueError(f"contrainte sur {name} : valeurs numériques attendues")
        points = expanded_grid(self)
        if not points:
            raise ValueError("aucune configuration ne respecte les contraintes")
        if len(points) > MAX_CONFIGURATIONS:
            raise ValueError(f"{len(points)} configurations, plus de {MAX_CONFIGURATIONS}")
        return self


class StrategyApproval(_Strict):
    """What Lucas writes by hand to promote a strategy to ``candidate`` (D14)."""

    strategie: StrategyId
    rapport_sha256: Sha256
    code_sha256: Sha256
    grille_sha256: Sha256
    date: date


class ReportStamp(BaseModel):
    """The fields of a standard report a promotion reads; the rest is ignored."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    strategie: str
    verdict: str
    donnees: str
    frais: str
    code_sha256: str
    grille_sha256: str


@dataclass(frozen=True)
class LocalEvidence:
    """The local base: the reports written there and the report prints of the audit journal."""

    reports: Path
    audited: frozenset[str]


def expanded_grid(spec: StrategySpec) -> list[dict[str, ParamValue]]:
    """The cartesian product of the grid in declared order, minus the points the constraints
    exclude."""
    names = list(spec.grille)
    points = [
        dict(zip(names, values, strict=True))
        for values in itertools.product(*(spec.grille[n] for n in names))
    ]
    return [
        p
        for p in points
        if all(_number(p[c.parametre]) < _number(p[c.inferieur_a]) for c in spec.contraintes)
    ]


def _number(value: ParamValue) -> float:
    if isinstance(value, bool | str):  # refused by the spec; kept for the type checker
        raise RegistryError(f"valeur non numérique dans une contrainte : {value!r}")
    return float(value)


def load_spec(path: Path) -> StrategySpec:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        spec = StrategySpec.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise RegistryError(f"{path.name} : entrée du registre invalide : {exc}") from exc
    if spec.id != path.stem:
        raise RegistryError(f"{path.name} : l'identifiant {spec.id} doit nommer le fichier")
    return spec


def synthetic_store_path(root: Path) -> Path:
    return root / SYNTHETIC_STORE


def load_registry(directory: Path = REGISTRY_DIR) -> dict[str, StrategySpec]:
    """Every entry of the registry, by id; an invalid one refuses the whole registry."""
    return {path.stem: load_spec(path) for path in sorted(directory.glob("*.yaml"))}


def code_sha256(spec: StrategySpec, root: Path = Path()) -> str:
    """SHA-256 of the module source, as ``trials.strategy_code_sha256`` reads it once imported."""
    try:
        text = (root / spec.module).read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryError(f"{spec.id} : module {spec.module} illisible") from exc
    return source_sha256(text)


def grid_sha256(spec: StrategySpec) -> str:
    """SHA-256 of the canonical grid: its expanded points, with what the protocol runs them on.

    The universe, the period, the data kind, the frequency and the initial cash change the
    results as much as a parameter: they belong to the version [Hypothèse].
    """
    canonical = {
        "capital_initial_eur": spec.capital_initial_eur,
        "donnees": spec.donnees,
        "frequence": spec.frequence,
        "periode": [spec.periode.debut.isoformat(), spec.periode.fin.isoformat()],
        "points": [params_sha256(p) for p in expanded_grid(spec)],
        "univers": spec.univers,
    }
    return hashlib.sha256(canonical_json(canonical).encode("utf-8")).hexdigest()


def load_strategy(spec: StrategySpec) -> Strategy:
    """The strategy object: ``classe`` of the module named after the id, built without
    arguments."""
    try:
        module = importlib.import_module(f"{STRATEGIES_PACKAGE}.{spec.id}")
        strategy = getattr(module, spec.classe)()
    except (ImportError, AttributeError, TypeError) as exc:
        raise RegistryError(f"{spec.id} : stratégie {spec.classe} introuvable : {exc}") from exc
    if not callable(getattr(strategy, "decide", None)):
        raise RegistryError(f"{spec.id} : {spec.classe} n'a pas de méthode decide")
    return strategy


def approval_text(
    spec: StrategySpec, *, report_sha256: str, code: str, grid: str, day: date
) -> str:
    """The approval Lucas may copy by hand into ``governance/approvals/strategies/<id>.yaml``."""
    body = {
        "strategie": spec.id,
        "rapport_sha256": report_sha256,
        "code_sha256": code,
        "grille_sha256": grid,
        "date": day.isoformat(),
    }
    StrategyApproval.model_validate(body)
    header = (
        f"# À recopier à la main par Lucas seul dans {APPROVALS_DIR.as_posix()}/{spec.id}.yaml\n"
        "# (ADR-027, D14) ; aucune commande ne l'écrit.\n"
    )
    return header + yaml.safe_dump(body, allow_unicode=True, sort_keys=False)


def load_approval(spec: StrategySpec, approvals: Path) -> StrategyApproval | None:
    path = approvals / f"{spec.id}.yaml"
    if not path.is_file():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return StrategyApproval.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise RegistryError(f"approbation {path.name} invalide : {exc}") from exc


def report_sha256(path: Path) -> str:
    """SHA-256 of the bytes of a report file: what the audit journal and the approval cite."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_stamp(path: Path) -> ReportStamp:
    try:
        return ReportStamp.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise RegistryError(f"rapport {path.name} illisible : {exc}") from exc


def audited_reports(journal: Path) -> frozenset[str]:
    """The report prints ``cerveau strategy protocol`` journaled as Lucas's decisions (R11).

    The chain itself is checked by ``cerveau audit verify``; an unreadable line or payload
    refuses the lookup rather than hide a report.
    """
    if not journal.is_file():
        return frozenset()
    audit, found = AuditJournal(journal), set[str]()
    try:
        for line in journal.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if (entry.get("event"), entry.get("actor")) != ("DECISION", "lucas"):
                continue
            payload = audit.read_payload(entry["payload_ref"]) if entry["payload_ref"] else None
            if isinstance(payload, dict) and payload.get("command") == PROTOCOL_COMMAND:
                found.add(str(payload["rapport_sha256"]))
    except (OSError, ValueError, KeyError, AuditError) as exc:
        raise RegistryError(f"journal d'audit illisible : {exc}") from exc
    return frozenset(found)


def report_blockers(
    stamp: ReportStamp, spec: StrategySpec, *, code: str, grid: str, against: str
) -> list[str]:
    """Why a report cannot back a promotion: its strategy, verdict, data, costs or prints."""
    checks: Mapping[str, bool] = {
        f"le rapport porte sur {stamp.strategie}": stamp.strategie != spec.id,
        f"verdict « {stamp.verdict} », « reussi » exigé": stamp.verdict != "reussi",
        "rapport sur données synthétiques": stamp.donnees != "reelles",
        "rapport à frais fictifs": stamp.frais != "reels",
        f"empreinte de code du rapport différente de {against}": stamp.code_sha256 != code,
        f"empreinte de grille du rapport différente de {against}": stamp.grille_sha256 != grid,
    }
    return [reason for reason, failed in checks.items() if failed]


def _find_report(spec: StrategySpec, reports: Path, wanted: str) -> Path | None:
    for path in sorted(reports.glob(f"{spec.id}-*.json")):
        if report_sha256(path) == wanted:
            return path
    return None


def promotion_errors(
    spec: StrategySpec,
    *,
    root: Path = Path(),
    approvals: Path = APPROVALS_DIR,
    local: LocalEvidence | None = None,
) -> list[str]:
    """Every reason to refuse ``candidate`` (ADR-027); empty for ``recherche`` or a valid one.

    ``local`` is None when no local base exists: the report and the audit journal are then out
    of reach, and only the approval and the fingerprints are checked.
    """
    if spec.statut != "candidate":
        return []
    where = f"{spec.id} (candidate)"
    try:
        approval = load_approval(spec, root / approvals)
    except RegistryError as exc:
        return [f"{where} : {exc}"]
    if approval is None:
        return [f"{where} : aucune approbation dans {approvals.as_posix()}/{spec.id}.yaml"]
    errors: list[str] = []
    if approval.strategie != spec.id:
        errors.append(f"{where} : l'approbation porte sur {approval.strategie}")
    code, grid = code_sha256(spec, root), grid_sha256(spec)
    if approval.code_sha256 != code:
        errors.append(f"{where} : code modifié depuis l'approbation (empreinte périmée)")
    if approval.grille_sha256 != grid:
        errors.append(f"{where} : grille modifiée depuis l'approbation (empreinte périmée)")
    if local is None:
        return errors
    path = _find_report(spec, local.reports, approval.rapport_sha256)
    if path is None:
        return [*errors, f"{where} : rapport {approval.rapport_sha256[:12]}… introuvable"]
    try:
        stamp = read_stamp(path)
    except RegistryError as exc:
        return [*errors, f"{where} : {exc}"]
    reasons = report_blockers(
        stamp, spec, code=approval.code_sha256, grid=approval.grille_sha256, against="l'approbation"
    )
    errors += [f"{where} : {reason}" for reason in reasons]
    if approval.rapport_sha256 not in local.audited:
        errors.append(f"{where} : empreinte du rapport absente du journal d'audit")
    return errors
