"""Plugin manifest validation (section 6, annex C.1, R8).

The registry refuses a plugin, with explicit reasons, when its manifest is
invalid, when its MCP annotations contradict its action class (6.3), or when
it has no tests or fewer than 10 evaluation questions.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from core.config.loader import ActionClass, Level, Marker

MIN_EVAL_QUESTIONS = 10
DOMAINS = ("generaliste", "finance", "recherche", "code", "cyber", "juridique_fr", "business")
PARITY_LABELS = ("[Parité]", "[Approximation]", "[Reconstruction]", "[Hors de portée]")
# R14: usage personnel uniquement, à isoler et lister dans docs/licences.md.
RESTRICTIVE_LICENCE_RE = re.compile(
    r"(commons[- ]clause|elastic|^el-?2|cc[- ]by[- ]nc|^a?gpl|^lgpl|sspl|busl|bsl)", re.IGNORECASE
)
SEMVER_RE = r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$"

# Section 6.3: expected MCP annotations per action class. Write classes must also declare
# readOnlyHint false: a tool that sends, deletes or orders is never read-only.
EXPECTED_ANNOTATIONS: dict[str, dict[str, bool]] = {
    "LECTURE": {"readOnlyHint": True},
    "CALCUL": {"readOnlyHint": True, "idempotentHint": True},
    "ECRITURE_INTERNE": {"readOnlyHint": False, "destructiveHint": False},
    "COMMUNICATION_EXTERNE": {"readOnlyHint": False, "openWorldHint": True},
    "IRREVERSIBLE": {"readOnlyHint": False, "destructiveHint": True},
    "FINANCIERE": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Annotations(_Strict):
    readOnlyHint: bool
    destructiveHint: bool
    idempotentHint: bool
    openWorldHint: bool


class ToolSpec(_Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    description: str = Field(min_length=10)
    action_class: ActionClass
    annotations: Annotations
    input_schema: str
    output_schema: str


class EvalsSpec(_Strict):
    questions: str
    golden: str


class Slo(_Strict):
    success_rate_min: float = Field(gt=0, le=1)
    p95_latency_ms: int | Marker


class Runtime(_Strict):
    """How the adapter starts the server (ADR-015, B26): ``python -m <module>`` over stdio."""

    module: str = Field(pattern=r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$")
    # Variables copied by name into the server's environment; their values are never logged.
    env: list[Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]] = Field(default_factory=list)
    priced_tools: dict[str, str] = Field(default_factory=dict)  # tool → pricing.search key


class PluginManifest(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    version: str = Field(pattern=SEMVER_RE)
    domain: Literal[DOMAINS]  # type: ignore[valid-type]
    kind: Literal["tool", "agent"]
    transport: Literal["mcp-stdio", "mcp-http"]
    parity_label: Literal[PARITY_LABELS]  # type: ignore[valid-type]
    environments: list[Literal["dev", "paper", "live"]] = Field(min_length=1)
    max_autonomy_level: Level
    tools: list[ToolSpec] = Field(default_factory=list)
    tests: str
    evals: EvalsSpec
    slo: Slo
    dependencies_licences: list[str]
    runtime: Runtime | None = None

    @model_validator(mode="after")
    def _tools_present(self) -> PluginManifest:
        if self.kind == "tool" and not self.tools:
            raise ValueError("un plugin de type tool doit déclarer au moins un outil")
        names = [t.name for t in self.tools]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"noms d'outils en double : {duplicates}")
        if len(set(self.environments)) != len(self.environments):
            raise ValueError("environnements en double")
        return self

    @model_validator(mode="after")
    def _runtime_stays_in_the_plugin(self) -> PluginManifest:
        if self.runtime is None:
            return self
        package = f"plugins.{self.id}"
        module = self.runtime.module
        if module != package and not module.startswith(package + "."):
            raise ValueError(f"runtime.module doit être {package} ou l'un de ses modules")
        if self.transport != "mcp-stdio":
            raise ValueError("runtime ne décrit qu'un démarrage mcp-stdio")
        unknown = sorted(set(self.runtime.priced_tools) - {t.name for t in self.tools})
        if unknown:
            raise ValueError(f"runtime.priced_tools : outils non déclarés {unknown}")
        if len(set(self.runtime.env)) != len(self.runtime.env):
            raise ValueError("runtime.env : variables en double")
        return self


@dataclass
class PluginReport:
    directory: Path
    plugin_id: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest: PluginManifest | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


def annotation_errors(tool: ToolSpec) -> list[str]:
    errors = []
    actual = tool.annotations.model_dump()
    for hint, expected in EXPECTED_ANNOTATIONS[tool.action_class].items():
        if actual[hint] is not expected:
            errors.append(
                f"outil {tool.name} : {tool.action_class} exige {hint}: "
                f"{str(expected).lower()} (6.3)"
            )
    if actual["readOnlyHint"] and actual["destructiveHint"]:
        errors.append(f"outil {tool.name} : readOnlyHint et destructiveHint sont contradictoires")
    return errors


def _inside(base: Path, rel: str, what: str, errors: list[str]) -> Path | None:
    """Resolve a manifest path and refuse anything escaping the plugin directory."""
    target = (base / rel).resolve()
    if not target.is_relative_to(base.resolve()):
        errors.append(f"{what} : le chemin {rel!r} sort du dossier du plugin")
        return None
    return target


def _count_questions(path: Path, errors: list[str]) -> int:
    text = path.read_text(encoding="utf-8")
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        errors.append(f"{path.name} : DTD ou entités XML interdites")
        return 0
    try:
        root = ET.fromstring(text)  # noqa: S314 - DTD and entities rejected above
    except ET.ParseError as exc:
        errors.append(f"{path.name} : XML invalide ({exc})")
        return 0
    count = 0
    for pair in root.iter("qa_pair"):
        question = (pair.findtext("question") or "").strip()
        answer = (pair.findtext("answer") or "").strip()
        if question and answer:
            count += 1
        else:
            errors.append(f"{path.name} : qa_pair sans question ou sans réponse")
    return count


def _check_golden(path: Path, errors: list[str]) -> None:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        errors.append(f"{path.name} : golden set vide")
    for i, line in enumerate(lines, start=1):
        try:
            if not isinstance(json.loads(line), dict):
                errors.append(f"{path.name} ligne {i} : objet JSON attendu")
        except json.JSONDecodeError:
            errors.append(f"{path.name} ligne {i} : JSON invalide")


def _check_schema_file(path: Path, what: str, errors: list[str]) -> None:
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except json.JSONDecodeError as exc:
        errors.append(f"{what} : JSON invalide ({exc})")
    except SchemaError as exc:
        errors.append(f"{what} : schéma JSON invalide ({exc.message})")


def validate_plugin(directory: Path) -> PluginReport:
    report = PluginReport(directory=directory)
    manifest_path = directory / "plugin.yaml"
    if not manifest_path.is_file():
        report.errors.append("plugin.yaml absent (R8)")
        return report
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        report.errors.append(f"plugin.yaml : YAML invalide ({exc})")
        return report
    if isinstance(raw, dict) and isinstance(raw.get("id"), str):
        report.plugin_id = raw["id"]
    try:
        manifest = PluginManifest.model_validate(raw)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "racine"
            report.errors.append(f"plugin.yaml › {loc} : {err['msg']}")
        return report
    report.manifest = manifest
    errors = report.errors

    if manifest.id != directory.name:
        errors.append(f"l'id {manifest.id!r} ne correspond pas au dossier {directory.name!r}")
    for tool in manifest.tools:
        errors.extend(annotation_errors(tool))
        for attr in ("input_schema", "output_schema"):
            rel = getattr(tool, attr)
            path = _inside(directory, rel, f"outil {tool.name} › {attr}", errors)
            if path is None:
                continue
            if not path.is_file():
                errors.append(f"outil {tool.name} › {attr} : {rel} introuvable")
            else:
                _check_schema_file(path, f"outil {tool.name} › {attr}", errors)

    tests_dir = _inside(directory, manifest.tests, "tests", errors)
    if tests_dir is not None and not any(tests_dir.glob("test_*.py")):
        errors.append(f"tests : aucun fichier test_*.py dans {manifest.tests} (R8)")

    questions = _inside(directory, manifest.evals.questions, "evals.questions", errors)
    if questions is not None:
        if not questions.is_file():
            errors.append(f"evals.questions : {manifest.evals.questions} introuvable (R8)")
        else:
            n = _count_questions(questions, errors)
            if n < MIN_EVAL_QUESTIONS:
                errors.append(
                    f"evals.questions : {n} question(s), minimum {MIN_EVAL_QUESTIONS} (R8)"
                )
    golden = _inside(directory, manifest.evals.golden, "evals.golden", errors)
    if golden is not None:
        if not golden.is_file():
            errors.append(f"evals.golden : {manifest.evals.golden} introuvable (R8)")
        else:
            _check_golden(golden, errors)

    if manifest.slo.p95_latency_ms in ("A_DEFINIR", "A_VERIFIER"):
        report.warnings.append("slo.p95_latency_ms à définir : surveillance SLO bloquée")
    restrictive = [x for x in manifest.dependencies_licences if RESTRICTIVE_LICENCE_RE.search(x)]
    if restrictive:
        report.warnings.append(
            f"licences restrictives {restrictive} : usage personnel, à lister dans "
            "docs/licences.md (R14)"
        )
    return report


@dataclass
class RegistryReport:
    accepted: list[PluginReport] = field(default_factory=list)
    refused: list[PluginReport] = field(default_factory=list)


def validate_all(plugins_dir: Path) -> RegistryReport:
    """Validate every plugin directory. Only accepted plugins may ever be loaded (R8)."""
    result = RegistryReport()
    if not plugins_dir.is_dir():
        return result
    for child in sorted(p for p in plugins_dir.iterdir() if p.is_dir()):
        if child.name.startswith((".", "_")):
            continue
        report = validate_plugin(child)
        (result.accepted if report.ok else result.refused).append(report)
    ids = [r.plugin_id for r in result.accepted]
    for report in list(result.accepted):
        if ids.count(report.plugin_id) > 1:
            report.errors.append(f"id {report.plugin_id!r} déclaré par plusieurs plugins")
            result.accepted.remove(report)
            result.refused.append(report)
    return result
