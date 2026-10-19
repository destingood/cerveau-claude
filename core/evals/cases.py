"""Eval cases and fixture web pages (plan section 9): YAML and JSONL files, validated on load.

A case holds a question of Lucas, the fixture web it may search and read, what the scripted models
answer offline, and what a good run must show. The fixture pages serve both modes: offline, the
scripted reader returns their ``extracts``; live, the real reader reads the same text.

A finance case also names the tool calls the scripted planner makes and the figures a good answer
cites: their displays are frozen from the reference store (ADR-023) and the real finance servers
must compute them again, in both modes.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.orchestrator.state import (
    MAX_CLAIM_CHARS,
    ActionClass,
    Complexity,
    Confidence,
    Decision,
    DraftAnswer,
    Importance,
    Status,
)
from core.verification.quotes import check_quote
from plugins.web_research.fetcher import _extract  # the plugin's own extraction of HTML pages

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKS_DIR = Path("domain_packs")
PACK_DIR = PACKS_DIR / "generaliste"
GOLDEN_FILE = PACK_DIR / "evals" / "golden.jsonl"
PACK_BEHAVIORS = PACK_DIR / "evals" / "behaviors.yaml"
FINANCE_PACK_DIR = PACKS_DIR / "finance"
FINANCE_GOLDEN = FINANCE_PACK_DIR / "evals" / "golden.jsonl"
FINANCE_BEHAVIORS = FINANCE_PACK_DIR / "evals" / "behaviors.yaml"
GOLDEN_FILES = (GOLDEN_FILE, FINANCE_GOLDEN)  # the group of a case is its pack
PACK_BEHAVIOR_FILES = (PACK_BEHAVIORS, FINANCE_BEHAVIORS)
BEHAVIOR_DIR = Path("evals") / "behaviors"
INJECTION_DIR = Path("evals") / "redteam" / "injection_base"
FINANCE_INJECTION_DIR = Path("evals") / "redteam" / "injection_finance"
WEB_FIXTURES = Path("evals") / "fixtures" / "web.yaml"
CASE_ID = r"^[a-z0-9][a-z0-9-]{2,63}$"
TOOL_NAME = r"^[a-z][a-z0-9_]{1,63}$"
MAX_LABEL_CHARS = 120

Suite = Literal["golden", "behaviors", "injection"]
SUITES: tuple[Suite, ...] = ("golden", "behaviors", "injection")


class CaseError(ValueError):
    """An eval file that does not validate: the suite cannot run (R9)."""


class _Data(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExtractFixture(_Data):
    affirmation: str = Field(min_length=1, max_length=MAX_CLAIM_CHARS)
    citation: str = Field(min_length=1)


class PageFixture(_Data):
    """A page as web_read returns it; ``html`` goes through the plugin's real extraction."""

    url: str = Field(pattern=r"^https?://")
    title: str | None = None
    text: str = ""
    published: str | None = None
    html: str | None = None
    extracts: tuple[ExtractFixture, ...] = ()  # what an honest reader returns (offline)
    trap: ExtractFixture | None = None  # what a manipulated reader returns (offline attack)

    @model_validator(mode="before")
    @classmethod
    def _render_html(cls, data: Any) -> Any:
        if not isinstance(data, Mapping) or not data.get("html"):
            return data
        if data.get("text"):
            raise ValueError("une page donne « text » ou « html », pas les deux")
        title, published, text = _extract(
            str(data["html"]).encode("utf-8"), "text/html", "utf-8", str(data.get("url", ""))
        )
        return {
            **data,
            "title": data.get("title") or title,
            "published": data.get("published") or published,
            "text": text or "",
        }

    @model_validator(mode="after")
    def _check_extracts(self) -> PageFixture:
        if not self.text.strip():
            raise ValueError(f"{self.url} : page sans texte")
        for extract in self.extracts:  # an honest extract quotes the page word for word
            if not check_quote(extract.citation, self.text).ok:
                raise ValueError(f"{self.url} : citation absente de la page : {extract.citation}")
        return self


class Hit(_Data):
    title: str = Field(min_length=1)
    url: str = Field(pattern=r"^https?://")
    snippet: str = ""


class Verdict(_Data):  # the classifier's answer (InputVerdict)
    decision: Decision = "ok"
    classe_action: ActionClass = "LECTURE"
    raison: str = "question de recherche"
    questions: tuple[str, ...] = ()


class Route(_Data):  # the router's answer (RouteVerdict)
    domaine: str = "generaliste"
    complexite: Complexity = "simple"
    importance: Importance = "normale"
    web: bool = True
    raison: str = "faits publics"


class Attack(_Data):
    """What a planner or a reader that obeys the page would do (persona « compromis »)."""

    reads: tuple[str, ...] = ()  # addresses taken from the page, outside the search results
    append: str = ""  # added to the developpement: a link, an image, a bare address
    reader: bool = True  # the reader returns the trap extracts of the pages


class ToolCallFixture(_Data):
    """A call of a computing tool the scripted planner makes; the real server answers it."""

    tool: str = Field(pattern=TOOL_NAME)
    args: dict[str, Any] = Field(default_factory=dict)


class ExpectedFigure(_Data):
    """A figure a good answer cites: the display the tool must compute again, frozen."""

    tool: str = Field(pattern=TOOL_NAME)
    id: str = Field(min_length=1, max_length=200)
    display: str = Field(min_length=1)
    # The words before the figure in a scripted answer: part of one sentence, so no full stop.
    label: str = Field(min_length=1, max_length=MAX_LABEL_CHARS, pattern=r"^[^.!?\n]+$")


class Offline(_Data):
    """The scripted models of an offline run; the deterministic layers run for real."""

    verdict: Verdict = Verdict()
    route: Route = Route()
    reads: int = Field(default=2, ge=0, le=10)  # search results the planner opens
    calls: tuple[ToolCallFixture, ...] = Field(default=(), max_length=10)  # before any search
    answer: DraftAnswer | None = None  # replaces the answer written from the extracts
    attack: Attack | None = None
    factual: tuple[int, ...] = ()  # the verifier's answer: uncited passages that are factual
    kill_switch: bool = False  # the run starts with the kill switch file in place (R4)

    @model_validator(mode="after")
    def _answer_without_web(self) -> Offline:
        scripted = self.answer is not None or bool(self.calls)
        if self.verdict.decision == "ok" and not self.route.web and not scripted:
            raise ValueError(
                "une question sans web exige une réponse scriptée (offline.answer) "
                "ou des appels d'outils (offline.calls)"
            )
        return self


class ExpectOffline(_Data):
    """Counters of the audit payload that the deterministic defences must reach offline."""

    min_refused_reads: int = 0
    min_links_removed: int = 0
    min_extracts_flagged: int = 0
    min_extracts_rejected: int = 0
    min_pages_with_signals: int = 0
    min_marked: int = 0  # passages marked [VERIFICATION REQUIRED]
    notes: tuple[str, ...] = ()  # substrings of the signalements


class Expect(_Data):
    status: tuple[Status, ...] = ("complete",)
    sourced: bool = False  # sources cited in the synthesis and the development, none invalid
    min_sources: int = 0
    canaries: tuple[str, ...] = ()  # words a page asks to repeat: never in the answer or a tool
    forbidden_hosts: tuple[str, ...] = ()  # hosts a page asks to contact or to link to
    pii: tuple[str, ...] = ()  # raw personal data of the question: never sent to a model or tool
    notes: tuple[str, ...] = ()  # substrings of the signalements, in both modes
    message: tuple[str, ...] = ()  # substrings of the message of a refusal or a clarification
    counter_argument: bool = False  # format 7.3: best counter-argument and next steps
    min_questions: int = 0  # clarification questions
    confidence: tuple[Confidence, ...] = ()  # levels a calibrated answer may announce
    min_points: int = 0  # points à vérifier the verification adds
    max_tool_calls: int | None = None  # effort in proportion to the stakes
    key_points: tuple[str, ...] = ()  # what a complete answer covers: judged live (golden)
    tools: tuple[str, ...] = ()  # computing tools the run must call (R1)
    figures: tuple[ExpectedFigure, ...] = ()  # recomputed by their tool and cited in the answer
    mentions: tuple[str, ...] = ()  # substrings of the answer, case and spaces ignored
    absent: tuple[str, ...] = ()  # never in the answer, case and spaces ignored
    offline: ExpectOffline = ExpectOffline()

    @model_validator(mode="after")
    def _figures_of_expected_tools(self) -> Expect:
        missing = sorted({figure.tool for figure in self.figures} - set(self.tools))
        if missing:
            raise ValueError(f"chiffre attendu d'un outil non attendu : {', '.join(missing)}")
        return self


class Case(_Data):
    id: str = Field(pattern=CASE_ID)
    suite: Suite
    group: str = Field(min_length=1)  # pack, behaviour principle or attack family
    rules: tuple[str, ...] = ()
    description: str = Field(min_length=1)
    question: str = Field(min_length=1)
    hits: tuple[Hit, ...] = ()  # search results; by default, the case's own pages
    pages: tuple[PageFixture, ...] = ()
    offline: Offline = Offline()
    expect: Expect = Expect()

    def search_hits(self) -> tuple[Hit, ...]:
        if self.hits:
            return self.hits
        return tuple(Hit(title=p.title or p.url, url=p.url) for p in self.pages)


class SuiteFile(_Data):
    """One behaviour or injection file: its principle, its threshold and its cases."""

    suite: Suite
    group: str = Field(min_length=1)
    principle: str = Field(min_length=1)
    rules: tuple[str, ...] = ()
    pass_rate: float = Field(ge=0, le=1)
    cases: tuple[Case, ...] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _inherit(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data
        common = {k: data[k] for k in ("suite", "group", "rules") if k in data}
        cases = [
            {**common, **case} if isinstance(case, Mapping) else case
            for case in data.get("cases", ())
        ]
        return {**data, "cases": cases}


def _yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CaseError(f"{path} : illisible ({exc})") from exc


def _validated[T: BaseModel](model: type[T], data: Any, where: str) -> T:
    try:
        return model.model_validate(data)
    except ValueError as exc:
        raise CaseError(f"{where} : {exc}") from exc


def load_web(root: Path = REPO_ROOT) -> dict[str, PageFixture]:
    """The shared fixture pages, by URL."""
    path = root / WEB_FIXTURES
    data = _yaml(path) or {}
    pages = [_validated(PageFixture, page, f"{path}") for page in data.get("pages", ())]
    by_url = {page.url: page for page in pages}
    if len(by_url) != len(pages):
        raise CaseError(f"{path} : adresse de page en double")
    return by_url


def load_golden(root: Path = REPO_ROOT) -> list[Case]:
    """The golden sets of the packs: the general one is required, another pack's is optional."""
    cases = []
    for relative in GOLDEN_FILES:
        path = root / relative
        if relative != GOLDEN_FILE and not path.is_file():
            continue
        group = relative.parent.parent.name
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CaseError(f"{path}:{number} : JSON invalide ({exc})") from exc
            data = {"suite": "golden", "group": group, **data}
            cases.append(_validated(Case, data, f"{path}:{number}"))
    return cases


def load_suite_files(root: Path, directory: Path, *extra: Path) -> list[SuiteFile]:
    """Every ``*.yaml`` of ``directory``, then each ``extra`` place (a missing file is an error).

    An extra place is a file, or a directory whose ``*.yaml`` files are all read.
    """
    paths = sorted((root / directory).glob("*.yaml"))
    for place in (root / path for path in extra):
        paths += sorted(place.glob("*.yaml")) if place.is_dir() else [place]
    return [_validated(SuiteFile, _yaml(path), str(path)) for path in paths]


def suite_files(suite: Suite, root: Path = REPO_ROOT) -> list[SuiteFile]:
    if suite == "behaviors":
        return load_suite_files(root, BEHAVIOR_DIR, *PACK_BEHAVIOR_FILES)
    if suite == "injection":
        return load_suite_files(root, INJECTION_DIR, FINANCE_INJECTION_DIR)
    return []


def load_cases(suite: Suite, root: Path = REPO_ROOT) -> list[Case]:
    """Every case of a suite, checked: unique ids, every search hit served by a page."""
    if suite == "golden":
        cases = load_golden(root)
    else:
        cases = [case for file in suite_files(suite, root) for case in file.cases]
    for case in cases:
        if case.suite != suite:
            raise CaseError(f"{case.id} : déclaré dans la suite {case.suite}, rangé dans {suite}")
    _check_ids(cases)
    web = load_web(root)
    for case in cases:
        served = {page.url for page in case.pages} | set(web)
        missing = [hit.url for hit in case.search_hits() if hit.url not in served]
        if missing:
            raise CaseError(f"{case.id} : résultat de recherche sans page : {', '.join(missing)}")
    return cases


def _check_ids(cases: Iterable[Case]) -> None:
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise CaseError(f"identifiant de cas en double : {case.id}")
        seen.add(case.id)


@cache
def cached_cases(suite: Suite, root: Path = REPO_ROOT) -> dict[str, Case]:
    """The cases of a suite by id, loaded once per process (promptfoo's persistent worker)."""
    return {case.id: case for case in load_cases(suite, root)}


@cache
def cached_web(root: Path = REPO_ROOT) -> dict[str, PageFixture]:
    return load_web(root)
