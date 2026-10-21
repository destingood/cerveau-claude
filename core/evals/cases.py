"""Eval cases and fixture web pages (plan section 9): YAML and JSONL files, validated on load.

A case holds a question of Lucas, the fixture web it may search and read, what the scripted models
answer offline, and what a good run must show. The fixture pages serve both modes: offline, the
scripted reader returns their ``extracts``; live, the real reader reads the same text.

A finance case also names the tool calls the scripted planner makes and the figures a good answer
cites: their displays are frozen from the reference store (ADR-023) and the real finance servers
must compute them again, in both modes. It may add to its own copy of that store what Lucas would
import (a CSV file of instruments or transactions, possibly trapped) and quality scores (D12).

A paper case (``paper``) runs the daily paper loop on a synthetic market of one fictitious
instrument, with no model: its source proposes target orders and the drafter, the policy and the
Risk Gate decide, over a copy of the configuration (``core/evals/paper.py``).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from core.config.loader import Allow, PaperRiskLimits, TradingCosts
from core.execution.intent import IntentOrigin
from core.execution.kill_switch import Trigger
from core.execution.states import OrderState
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
from core.risk_gate.gate import Result
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
EXECUTION_INJECTION_DIR = Path("evals") / "redteam" / "injection_execution"
WEB_FIXTURES = Path("evals") / "fixtures" / "web.yaml"
CASE_ID = r"^[a-z0-9][a-z0-9-]{2,63}$"
TOOL_NAME = r"^[a-z][a-z0-9_]{1,63}$"
MAX_LABEL_CHARS = 120
PAPER_SYMBOL = "FICT-ACME"  # the paper cases' only instrument, fictitious

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
    mode: Literal["direct", "comite"] = "direct"  # « comite »: the pack's Committee answers


class Attack(_Data):
    """What a planner or a reader that obeys the page would do (persona « compromis »)."""

    reads: tuple[str, ...] = ()  # addresses taken from the page, outside the search results
    searches: tuple[str, ...] = ()  # queries the page dictates, built from Lucas's figures (R6)
    append: str = ""  # added to the developpement: a link, an image, a bare address
    reader: bool = True  # the reader returns the trap extracts of the pages


class ToolCallFixture(_Data):
    """A call of a computing tool the scripted planner makes; the real server answers it."""

    tool: str = Field(pattern=TOOL_NAME)
    args: dict[str, Any] = Field(default_factory=dict)


class CommitteeTurn(_Data):
    """One reply a scripted member gives instead of its honest one: a tool call, a JSON output
    or a raw text (an injection the engine must refuse)."""

    tool: str | None = Field(default=None, pattern=TOOL_NAME)
    args: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    text: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _one_reply(self) -> CommitteeTurn:
        given = (self.tool is not None) + (self.output is not None) + (self.text is not None)
        if given != 1:
            raise ValueError("un tour du Comité : un appel d'outil, une sortie ou un texte")
        if self.args and self.tool is None:
            raise ValueError("args sans outil")
        return self


# The keys a case may set: every paper limit, never ``allow`` (a ban, not a limit).
PAPER_LIMITS = tuple(name for name in PaperRiskLimits.model_fields if name != "allow")


def check_paper_limits(given: Mapping[str, Any], where: str) -> None:
    """Paper limits a case sets obey the bounds of risk_limits.paper.yaml (B164)."""
    unknown = sorted(set(given) - set(PAPER_LIMITS))
    if unknown:
        raise ValueError(f"{where} : clé inconnue : {', '.join(unknown)}")
    undefined: dict[str, Any] = dict.fromkeys(PAPER_LIMITS, "A_DEFINIR")
    undefined["allow"] = dict.fromkeys(Allow.model_fields, False)
    try:
        PaperRiskLimits.model_validate(undefined | dict(given))
    except ValidationError as error:
        fields = sorted({str(detail["loc"][0]) for detail in error.errors()})
        raise ValueError(f"{where} : valeur hors bornes : {', '.join(fields)}") from None


class PaperRationaleFixture(_Data):
    """The why of the source's orders, kept raw: the loop checks it when the source proposes, so
    a text that reads as an instruction is refused there (R5), not when the case loads."""

    thesis: str = "Le titre fictif reste sous sa moyenne."
    catalyst: str = "Signal de la règle à la clôture."
    invalidation: str = "Clôture sous 90 €."
    horizon_days: int = 20
    confidence: float = 0.5


class PaperDayFixture(_Data):
    """One decision day: the session's close, then the target orders the source proposes."""

    day: date
    close: float | None = Field(default=100.0, gt=0)  # None: the close is never published
    orders: tuple[int, ...] = Field(default=(), max_length=5)  # signed: above zero buys

    @model_validator(mode="after")
    def _whole_orders(self) -> PaperDayFixture:
        if 0 in self.orders:
            raise ValueError(f"{self.day} : ordre de quantité nulle")
        return self


class PaperFixture(_Data):
    """A run of the paper loop on a synthetic market of one instrument, with no model.

    The level, the limits and the costs apply to a copy of the configuration, never to the
    files. Limits left out keep the file's values (the universe is the case's instrument);
    costs left out keep the file's ``A_DEFINIR``, so the paper account is refused (R7).
    """

    level: Literal["N0", "N1", "N2"] = "N2"
    limits: dict[str, Any] = Field(default_factory=dict)
    costs: TradingCosts | None = None
    price: float = Field(default=100.0, gt=0)  # every close before the first day
    volume: int = Field(default=200_000, ge=0)  # every session's volume
    origin: IntentOrigin = IntentOrigin(kind="strategy", id="croisement_mm")
    rationale: PaperRationaleFixture = PaperRationaleFixture()
    kill_switch: bool = False  # the KILL file is in place before the first day (R4)
    days: tuple[PaperDayFixture, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def _checked(self) -> PaperFixture:
        check_paper_limits(self.limits, "paper.limits")
        days = [item.day for item in self.days]
        if days != sorted(set(days)):
            raise ValueError("paper.days : jours en double ou dans le désordre")
        return self


PaperOutcome = Literal[
    "terminee", "deja_traitee", "pas_de_seance", "attente_donnees", "injoignable", "arret", "bloque"
]


class ExpectPaper(_Data):
    """What the paper loop must show, compared exactly (order of the days, then of the intents)."""

    outcomes: tuple[PaperOutcome, ...] = Field(min_length=1)  # one per day; « bloque »: refused
    gate: tuple[Result, ...] = ()  # the Risk Gate's result of each intent
    retained: tuple[int, ...] = ()  # the quantity the Gate kept of each intent
    states: tuple[OrderState, ...] = ()  # where each order of the book ended
    stop: Trigger | None = None  # the kill switch's trigger, when the loop engages it
    notes: tuple[str, ...] = ()  # substrings of the day's remarks


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
    # Replies of committee members, by member, taken in order (repairs and rounds included)
    # before their honest replies: what a manipulated or mistaken member would say.
    committee: dict[str, tuple[CommitteeTurn, ...]] = Field(default_factory=dict)
    # Paper limits the case's committee checks over a copy of risk_limits.paper.yaml: a key left
    # out keeps the file's value, so a case about an unknown limit marks it A_DEFINIR itself.
    paper_limits: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _answer_without_web(self) -> Offline:
        scripted = self.answer is not None or bool(self.calls) or self.route.mode == "comite"
        if self.verdict.decision == "ok" and not self.route.web and not scripted:
            raise ValueError(
                "une question sans web exige une réponse scriptée (offline.answer) "
                "ou des appels d'outils (offline.calls)"
            )
        return self

    @model_validator(mode="after")
    def _bounded_limits(self) -> Offline:
        check_paper_limits(self.paper_limits or {}, "paper_limits")
        return self


class ExpectOffline(_Data):
    """Counters of the audit payload that the deterministic defences must reach offline."""

    min_refused_reads: int = 0
    min_refused_searches: int = 0  # queries refused because they carried Lucas's data (R6)
    min_links_removed: int = 0
    min_extracts_flagged: int = 0
    min_extracts_rejected: int = 0
    min_pages_with_signals: int = 0
    min_marked: int = 0  # passages marked [VERIFICATION REQUIRED]
    notes: tuple[str, ...] = ()  # substrings of the signalements


class QualityFixture(_Data):
    """A quality score recorded for a series of the store, every sub-score at ``score`` (D12).

    ``unknown``: sub-scores left unknown, as while their cut-off in ``data_sources.yaml`` is
    ``A_DEFINIR`` (ADR-016); the score is then unknown too, and the series not evaluable (B119).
    """

    instrument_id: str = Field(min_length=1, max_length=64)
    score: float = Field(ge=0, le=1)
    unknown: tuple[Literal["gaps", "corporate_actions", "outliers", "freshness"], ...] = Field(
        default=(), max_length=4
    )
    assessed_at: AwareDatetime  # the date the score holds from
    computed_at: AwareDatetime | None = None  # when it was recorded; by default, assessed_at

    @model_validator(mode="after")
    def _computed_after(self) -> QualityFixture:
        if self.computed_at is not None and self.computed_at < self.assessed_at:
            raise ValueError("un score ne se calcule pas avant la date qu'il évalue")
        return self


class StoreFixture(_Data):
    """What the case adds to its copy of the reference store before the run, as Lucas would:
    the CSV files he imports (the import refuses a trapped one whole, R5) and quality scores."""

    instruments_csv: str | None = Field(default=None, min_length=1)  # `cerveau` reference format
    transactions_csv: str | None = Field(default=None, min_length=1)  # `cerveau` ledger format
    imported_at: AwareDatetime | None = None  # by default, between the reference and its reading
    quality: tuple[QualityFixture, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def _not_empty(self) -> StoreFixture:
        if self.instruments_csv is None and self.transactions_csv is None and not self.quality:
            raise ValueError("store : un fichier CSV ou un score de qualité au moins")
        return self

    def files(self) -> int:
        return (self.instruments_csv is not None) + (self.transactions_csv is not None)


class ExpectCommittee(_Data):
    """What the committee's session must show: its status, its verdict and its journal."""

    status: tuple[Literal["complete", "echec", "incomplete"], ...] = ("complete",)
    verdict: tuple[Literal["OK", "BLOQUER"], ...] = ()  # empty: no verdict expected
    decision: tuple[Literal["agir", "ne_pas_agir", "attendre"], ...] = ()
    min_role_entries: int = Field(default=0, ge=0)  # DECISION entries of the roles
    repaired: tuple[str, ...] = ()  # members whose faulty output was refused, then repaired
    libelle: str = "analyse"  # N0: an analysis, never a proposal to execute


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
    refused_imports: int = Field(default=0, ge=0, le=2)  # files of `store` the import refuses (R5)
    committee: ExpectCommittee | None = None  # the session of the pack's Committee
    paper: ExpectPaper | None = None  # what the paper loop shows (the case's ``paper``)
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
    store: StoreFixture | None = None  # added to the case's copy of the reference store
    paper: PaperFixture | None = None  # a run of the paper loop instead of a question's run
    expect: Expect = Expect()

    @model_validator(mode="after")
    def _refusals_of_files(self) -> Case:
        files = 0 if self.store is None else self.store.files()
        if self.expect.refused_imports > files:
            raise ValueError(f"refused_imports : {files} fichier(s) seulement dans store")
        return self

    @model_validator(mode="after")
    def _paper_and_its_expectation(self) -> Case:
        if (self.paper is None) != (self.expect.paper is None):
            raise ValueError("paper et expect.paper vont ensemble")
        return self

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
        return load_suite_files(root, INJECTION_DIR, FINANCE_INJECTION_DIR, EXECUTION_INJECTION_DIR)
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
