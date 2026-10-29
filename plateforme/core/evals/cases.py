"""Eval cases and fixture web pages (plan section 9): YAML and JSONL files, validated on load.

A case holds a question of Lucas, the fixture web it may search and read, what the scripted models
answer offline, and what a good run must show. The fixture pages serve both modes: offline, the
scripted reader returns their ``extracts``; live, the real reader reads the same text.

A finance case also names the tool calls the scripted planner makes and the figures a good answer
cites: their displays are frozen from the reference store (ADR-023) and the real finance servers
must compute them again, in both modes. It may add to its own copy of that store what Lucas would
import (a CSV file of instruments or transactions, possibly trapped) and quality scores (D12).

A research case (``approfondi``) is asked as with ``cerveau ask --approfondi`` (ADR-045): it may
add scholarly records (``records``), whose abstracts the reader reads as it reads a page, and
feeds of its own allow-list (``feeds``), the repository's staying empty (D18). Its scripted
planner proposes the case's sub-questions and its writer cites the checked extracts it is shown,
plus the claims, titles and steps the case adds to test what the engine removes or masks.

A paper case (``paper``) runs the daily paper loop on a synthetic market of fictitious
instruments, with no model: its source proposes target orders and the drafter, the policy and the
Risk Gate decide, over a copy of the configuration; at N3, the case answers the approval requests
as Lucas would, with the one-time codes of a test key (``core/evals/paper.py``).

A cyber case (``cyber``) gives the records the fake NVD, KEV and EPSS serve to the real cyber_cve
server and the state of the ATT&CK index the real cyber_attack server reads, built from a
synthetic bundle in the run's temporary home (ADR-057); a source may be down or answer too much.

A legal case (``legal``) gives the article versions and searches the fake Légifrance API serves
to the real legifrance server, the PISTE environment of its configuration copy and whether it has
stand-in credentials; the API may be down, answer too much or send another article (ADR-060).

A business case (``business``) gives the companies the fake API Recherche d'entreprises finds and
the INSEE datasets the fake Melodi API serves to the real entreprises and insee_stats servers; a
company may carry a director and an address the plugin must drop, and an API may be down (ADR-063).

A learning case (``learning``) runs the learning loop's own code with no model, in a temporary
home: feedback with its notes, the harvest of patterns, a challenger's lesson, writes aimed past
the learned layer, a promotion on synthetic eval reports, forecasts and the weekly report
(``core/evals/learning.py``, ADR-065).
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

from core.approvals.store import ApprovalState
from core.config.loader import Allow, PaperRiskLimits, TradingCosts
from core.execution.intent import IntentOrigin
from core.execution.kill_switch import Trigger
from core.execution.states import OrderState
from core.orchestrator.packs import DEFAULT_DOMAIN, pack_ids
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
from plugins.feeds.allowlist import FEED_ID
from plugins.web_research.fetcher import _extract  # the plugin's own extraction of HTML pages

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKS_DIR = Path("domain_packs")
# Each pack of domain_packs/ brings its golden set and its behaviours, both required, and may
# bring its red team in evals/redteam/injection_<id>/ (ADR-043). The general golden set is
# required even without a manifest: it is the fallback pack's.
GOLDEN_FILE = PACKS_DIR / DEFAULT_DOMAIN / "evals" / "golden.jsonl"
BEHAVIOR_DIR = Path("evals") / "behaviors"
REDTEAM_DIR = Path("evals") / "redteam"
INJECTION_DIR = REDTEAM_DIR / "injection_base"
# The red teams of an action, whatever the pack (ADR-030, ADR-035): read after the packs' own.
EXECUTION_INJECTION_DIR = REDTEAM_DIR / "injection_execution"
APPROVAL_INJECTION_DIR = REDTEAM_DIR / "injection_approbation"
LEARNING_INJECTION_DIR = REDTEAM_DIR / "injection_learning"  # the learning loop (ADR-065)
WEB_FIXTURES = Path("evals") / "fixtures" / "web.yaml"
CASE_ID = r"^[a-z0-9][a-z0-9-]{2,63}$"
TOOL_NAME = r"^[a-z][a-z0-9_]{1,63}$"
MAX_LABEL_CHARS = 120
PAPER_SYMBOL = "FICT-ACME"  # the paper cases' first instrument, fictitious
PAPER_SYMBOLS = r"^FICT-[A-Z]{1,8}$"  # the others (B186: limits across instruments)

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


class RecordFixture(_Data):
    """A record as scholar_search returns it; its abstract is what the reader reads (ADR-044)."""

    source: Literal["arxiv", "crossref"] = "crossref"
    identifier: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1)
    preprint: bool = False
    published: str | None = None
    doi: str | None = None
    url: str = Field(pattern=r"^https?://")
    abstract: str | None = None  # None: a record without abstract, never read (no PDF, D12)
    updated_by: tuple[str, ...] = ()  # the types of its published updates (« retraction »...)
    extracts: tuple[ExtractFixture, ...] = ()  # what an honest reader returns (offline)
    trap: ExtractFixture | None = None  # what a manipulated reader returns (offline attack)

    @model_validator(mode="after")
    def _check_extracts(self) -> RecordFixture:
        for extract in self.extracts:  # an honest extract quotes the abstract word for word
            if not check_quote(extract.citation, self.abstract or "").ok:
                raise ValueError(f"{self.url} : citation absente du résumé : {extract.citation}")
        return self


class FeedFixture(_Data):
    """A feed of the case's own allow-list and the XML it serves."""

    id: str = Field(pattern=FEED_ID)
    titre: str = "Flux de test"
    url: str = Field(pattern=r"^https://")
    licence: str = "CC BY 4.0"
    frequence: str = "quotidienne"
    xml: str = Field(min_length=1)


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


class ResearchClaim(_Data):
    """A claim the scripted writer adds to its honest report, citing extracts as « n.k »."""

    texte: str = Field(min_length=1)
    extraits: tuple[str, ...] = ()


class ResearchFixture(_Data):
    """The scripted planner and writer of a deep research; the engine runs for real.

    The honest plan has ``sub_questions`` sub-questions, each searching the web and, when
    ``scholar`` is set, that source; above the cap, the engine cuts it. ``plans`` and ``reports``
    are raw replies given first (a malformed output, then its repair). The honest report cites the
    checked extracts it is shown; the case's claims, section title, steps and reason are what a
    mistaken or manipulated writer would add (R1, R5, D15).
    """

    sub_questions: int = Field(default=2, ge=1, le=20)
    scholar: Literal["", "arxiv", "crossref"] = ""
    plans: tuple[str, ...] = Field(default=(), max_length=2)
    reports: tuple[str, ...] = Field(default=(), max_length=2)
    claims: tuple[ResearchClaim, ...] = Field(default=(), max_length=6)
    section: str | None = Field(default=None, min_length=1)  # the title of the sources' section
    steps: tuple[str, ...] = Field(default=(), max_length=4)
    reason: str | None = Field(default=None, min_length=1)  # the confidence's justification
    level: Confidence = "moyen"


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


class PaperOrderFixture(_Data):
    """A target order on another fictitious instrument than ``PAPER_SYMBOL``."""

    symbol: str = Field(pattern=PAPER_SYMBOLS)
    quantity: int  # signed: above zero buys

    @model_validator(mode="after")
    def _whole(self) -> PaperOrderFixture:
        if self.quantity == 0:
            raise ValueError(f"{self.symbol} : ordre de quantité nulle")
        return self


class PaperAnswerFixture(_Data):
    """Lucas's answer to one approval request of the day (N3), as from the bot: wrong codes
    first, then the right one-time code, a refusal, or nothing."""

    answer: Literal["accorder", "refuser", "aucune"] = "accorder"
    wrong_codes: int = Field(default=0, ge=0, le=5)
    after: int | None = Field(default=None, ge=1, le=60)  # minutes after the loop's run


class PaperDayFixture(_Data):
    """One decision day: the session's close, then the target orders the source proposes; at
    N3, Lucas's answers to the day's approval requests, in the order they were filed."""

    day: date
    close: float | None = Field(default=100.0, gt=0)  # None: the close is never published
    # signed: above zero buys; a bare quantity is on PAPER_SYMBOL
    orders: tuple[int | PaperOrderFixture, ...] = Field(default=(), max_length=5)
    answers: tuple[PaperAnswerFixture, ...] = Field(default=(), max_length=5)
    kill_switch: bool = False  # the KILL file is put in place after the run (R4)
    send_after: int | None = Field(default=None, ge=1, le=120)  # `paper envoyer`, minutes

    @model_validator(mode="after")
    def _whole_orders(self) -> PaperDayFixture:
        if 0 in self.orders:
            raise ValueError(f"{self.day} : ordre de quantité nulle")
        minutes = self.answer_minutes()
        if list(minutes) != sorted(set(minutes)):
            raise ValueError(f"{self.day} : deux réponses à la même minute ou dans le désordre")
        if self.send_after is not None and minutes and self.send_after < minutes[-1]:
            raise ValueError(f"{self.day} : envoi avant la dernière réponse")
        return self

    def targets(self) -> tuple[tuple[str, int], ...]:
        """Each order as (instrument, signed quantity)."""
        return tuple(
            (PAPER_SYMBOL, order) if isinstance(order, int) else (order.symbol, order.quantity)
            for order in self.orders
        )

    def answer_minutes(self) -> tuple[int, ...]:
        """When each answer comes, in minutes after the run: two, then one more per earlier
        request, unless given. A right code is never of the last one's step (anti-replay), so
        two answers never share a minute."""
        return tuple(
            2 + index if answer.after is None else answer.after
            for index, answer in enumerate(self.answers)
        )


class PaperFixture(_Data):
    """A run of the paper loop on a synthetic market of fictitious instruments, with no model.

    The level, the limits and the costs apply to a copy of the configuration, never to the
    files. Limits left out keep the file's values (the universe is the case's instruments);
    costs left out keep the file's ``A_DEFINIR``, so the paper account is refused (R7). N3 is
    signed on a promotion report of the case's home: « promotion_impossible » leaves it unsigned,
    and the loop runs at N2 (ADR-036).
    """

    level: Literal["N0", "N1", "N2", "N3"] = "N2"
    promotion_report: Literal["promotion_possible", "promotion_impossible"] = "promotion_possible"
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
        approving = any(d.answers or d.kill_switch or d.send_after for d in self.days)
        if approving and self.level != "N3":
            raise ValueError("paper.days : réponses, kill switch du jour et envoi en N3 seulement")
        return self

    def symbols(self) -> tuple[str, ...]:
        """The case's instruments: ``PAPER_SYMBOL`` first, then the others by name."""
        others = {symbol for day in self.days for symbol, _ in day.targets()}
        return (PAPER_SYMBOL, *sorted(others - {PAPER_SYMBOL}))


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
    approvals: tuple[ApprovalState, ...] = ()  # each request at the end, in filing order (N3)


LearningStep = Literal[
    "retour", "lecon", "ecriture", "chemin", "promotion", "prevision", "resolution"
]
GateStatus = Literal["rejete", "promouvable", "non_conclu"]


class LearningPromotionFixture(_Data):
    """A promotion asked on two synthetic eval reports: the champion passes every case."""

    lost: tuple[Literal["comportement", "red_team"], ...] = ()  # cases the challenger fails
    r5: int = Field(default=0, ge=0, le=10)  # R5 breaches the challenger adds
    forged: bool = False  # the challenger's report claims its own verdict and scores (R1)
    mode: Literal["offline", "live"] = "offline"  # of both reports (D4)
    thresholds: bool = False  # the gate's margin and minimum set to 0 and 1 for the comparison


class LearningForecastFixture(_Data):
    """A forecast made 30 days before the report; resolved five days after its due day."""

    kind: Literal["probabilite", "estimation"] = "probabilite"
    value: float = Field(allow_inf_nan=False)
    due_days: int = Field(default=10, ge=-5, le=25)  # 0 or less: refused, the day has come
    outcome: bool | float | None = None  # what happened; None: left open
    early: bool = False  # also tries to resolve it the day after it is made (R10)


class LearningWeeklyFixture(_Data):
    """The weekly report on a synthetic offline eval report of the week."""

    summary: str = ""  # free text slipped into the eval report: never in the weekly report
    gate_passed: bool = True


class LearningFixture(_Data):
    """A run of the learning loop's code, with no model, in a temporary home (ADR-065).

    Each note and each bare verdict is a « mauvais » feedback on its own request, routed to
    ``pack`` (any text: what a routed decision would carry). ``min_support`` and
    ``max_feedback_per_user`` stand for the ``A_DEFINIR`` values of ``evals.yaml``, in the run
    only. A challenger is proposed for each pattern kept, with ``lesson`` as the drafter's text
    when given (on a pattern of its own when none is kept), else the scripted drafter's.
    """

    pack: str = Field(default=DEFAULT_DOMAIN, min_length=1, max_length=64)
    notes: tuple[str, ...] = Field(default=(), max_length=20)
    bare: int = Field(default=0, ge=0, le=50)
    min_support: int = Field(default=2, ge=2, le=10)
    max_feedback_per_user: int = Field(default=3, ge=1, le=50)
    lesson: str | None = None
    targets: tuple[str, ...] = Field(default=(), max_length=10)  # packs or paths a write aims at
    promotion: LearningPromotionFixture | None = None
    forecasts: tuple[LearningForecastFixture, ...] = Field(default=(), max_length=10)
    weekly: LearningWeeklyFixture | None = None


class ExpectLearning(_Data):
    """What the learning loop must show; a count left out is not checked."""

    refused: tuple[LearningStep, ...] = ()  # the steps refused, in order
    patterns: int | None = None  # patterns the harvest keeps
    capped: int | None = None  # verdicts over the per-user cap
    notes_aside: int | None = None  # notes set aside for their injection signals
    challengers: int | None = None  # challengers written
    verdict: GateStatus | None = None
    reasons: tuple[str, ...] = ()  # substrings of the gate's reasons
    forecasts: int | None = None  # FORECAST entries of the journal


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
    research: ResearchFixture = ResearchFixture()  # the planner and writer of ``approfondi``
    # per_code_agent set in the run's copy of budgets.yaml; False leaves it A_DEFINIR, as in the
    # repository, so that a code agent task is blocked (R7).
    agent_budget: bool = True

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


class ExpectResearch(_Data):
    """What the deep research's audit payload and its answer must show (ADR-045)."""

    min_reads: int = Field(default=0, ge=0)
    max_reads: int | None = Field(default=None, ge=0)
    min_removed: int = Field(default=0, ge=0)  # claims removed and listed (D15)
    retracted: int | None = Field(default=None, ge=0)
    without_abstract: int | None = Field(default=None, ge=0)
    updated: int | None = Field(default=None, ge=0)  # sources shown with a published update
    sub_questions: int | None = Field(default=None, ge=0)
    sub_questions_cut: int | None = Field(default=None, ge=0)
    halted: bool = False
    removed: tuple[str, ...] = ()  # substrings of the « Points non vérifiés »


class Expect(_Data):
    status: tuple[Status, ...] = ("complete",)
    sourced: bool = False  # sources cited in the synthesis and the development, none invalid
    min_sources: int = 0
    canaries: tuple[str, ...] = ()  # words a page asks to repeat: never in the answer or a tool
    # Values the run holds (a stand-in key): never in the answer, a tool call, a message sent to
    # a model or the run's journal (R6).
    secrets: tuple[str, ...] = ()
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
    notices: tuple[str, ...] = ()  # substrings of the notices the code appends (G9, R14)
    refused_imports: int = Field(default=0, ge=0, le=2)  # files of `store` the import refuses (R5)
    committee: ExpectCommittee | None = None  # the session of the pack's Committee
    paper: ExpectPaper | None = None  # what the paper loop shows (the case's ``paper``)
    learning: ExpectLearning | None = None  # what the learning loop shows (``learning``)
    research: ExpectResearch | None = None  # what the deep research shows (``approfondi``)
    offline: ExpectOffline = ExpectOffline()

    @model_validator(mode="after")
    def _figures_of_expected_tools(self) -> Expect:
        missing = sorted({figure.tool for figure in self.figures} - set(self.tools))
        if missing:
            raise ValueError(f"chiffre attendu d'un outil non attendu : {', '.join(missing)}")
        return self


CodeStep = Literal["check", "format", "pytest"]


class CodeCommitFixture(_Data):
    """One commit of the case's repository. A file set to None is deleted; a link is a symbolic
    link written in the index only, never on the disk. « «JETON_FICTIF» » and « «CLE_PRIVEE» »
    become a fictitious token and key block when the repository is built (R6: none sits here)."""

    message: str = Field(min_length=1)
    files: dict[str, str | None] = Field(default_factory=dict)
    links: dict[str, str] = Field(default_factory=dict)  # path → target

    @model_validator(mode="after")
    def _paths_inside(self) -> CodeCommitFixture:
        # Written under the temporary home: a path never climbs out of the repository.
        for path in [*self.files, *self.links]:
            parts = path.split("/")
            if "\\" in path or ":" in path or any(p in ("", ".", "..", ".git") for p in parts):
                raise ValueError(f"{path} : chemin relatif au dépôt attendu")
        return self


class RuffItemFixture(_Data):
    """One diagnostic as ruff 0.17 writes it with ``--output-format=json``."""

    path: str = Field(min_length=1)
    code: str | None = None
    message: str = Field(min_length=1)
    row: int = Field(default=1, ge=1)
    column: int = Field(default=1, ge=1)


class CodeChecksFixture(_Data):
    """What the fake Docker of run_checks answers for each step; no container runs."""

    lint: tuple[RuffItemFixture, ...] = ()
    unformatted: tuple[str, ...] = ()  # files ruff format would reformat
    pytest_code: int = 0
    pytest_output: str = "..\n2 passed in 0.05s\n"
    docker: int | None = None  # an exit code every step answers instead (125: daemon down)
    timed_out: tuple[CodeStep, ...] = ()


class CodeRunFixture(_Data):
    """One GitHub Actions run, shaped like the documented answer of the API (texts invented)."""

    title: str = Field(min_length=1)
    workflow: str = "CI"
    branch: str = "main"
    event: str = "push"
    status: str = "completed"
    conclusion: str | None = "success"


class CodeAgentProxyFixture(_Data):
    """The API proxy's counts once the agent is done, as core/code/llm_proxy.py writes them."""

    requests: int = Field(default=3, ge=0)
    usd: str = Field(default="0.025000", pattern=r"^[0-9]{1,4}\.[0-9]{1,6}$")
    input_tokens: int = Field(default=9000, ge=0)
    output_tokens: int = Field(default=700, ge=0)
    stopped: str | None = None  # the ceiling that stopped it: plafond_usd, plafond_requetes…
    refusals: dict[str, int] = Field(default_factory=dict)  # reason → requests refused
    unknown_cost: bool = False


class CodeAgentFixture(_Data):
    """What the fake Docker of agent_task does instead of the two containers: the agent's
    changes to the copy, the runner's last line and the proxy's counts. No container runs, no
    model is called and no key is read: the variable is a stand-in value, or absent (``key``)."""

    writes: dict[str, str | None] = Field(default_factory=dict)  # path → content; None deletes
    status: Literal["termine", "erreur", "delai"] = "termine"  # delai: out of its time
    subtype: str | None = "success"
    turns: int | None = Field(default=4, ge=0)
    summary: str | None = "Tâche faite."
    error: str | None = None
    proxy: CodeAgentProxyFixture = CodeAgentProxyFixture()
    docker: int | None = None  # an exit code every agent step answers instead (125: no daemon)
    key: bool = True  # ANTHROPIC_API_KEY set, to a stand-in value the server never reads

    @model_validator(mode="after")
    def _paths_inside(self) -> CodeAgentFixture:
        # Written in the throwaway copy under the temporary home, never out of it.
        for path in self.writes:
            parts = path.split("/")
            if "\\" in path or ":" in path or any(p in ("", ".", "..", ".git") for p in parts):
                raise ValueError(f"{path} : chemin relatif à la copie attendu")
        return self


class CodeFixture(_Data):
    """The repository « projet » of a code case, built in the run's temporary home and alone on
    the allow-list (with CERVEAU's own when ``cerveau``), the fake Docker of run_checks and of
    agent_task and the fake GitHub of ci_runs: no network, no container, no real repository read
    but CERVEAU's."""

    commits: tuple[CodeCommitFixture, ...] = Field(min_length=1, max_length=10)
    cerveau: bool = False  # CERVEAU listed too: every tool must refuse it (ADR-047)
    pytest: bool = False  # Lucas prepared the repository's pytest environment (E3)
    github: str | None = "lucas-exemple/projet"
    checks: CodeChecksFixture | None = None  # None: every step answers 125 (no Docker)
    runs: tuple[CodeRunFixture, ...] = Field(default=(), max_length=20)
    total_runs: int | None = Field(default=None, ge=0)  # the API's total_count; None: the runs
    ci_status: int = Field(default=200, ge=200, le=599)  # the API's HTTP status
    agent: CodeAgentFixture = CodeAgentFixture()  # what agent_task's containers would do


CVE_ID = r"^CVE-[0-9]{4}-[0-9]{4,19}$"
NVD_TIMESTAMP = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,3})?$"
SCORE = r"^(0(\.[0-9]{1,9})?|1(\.0{1,9})?)$"  # EPSS writes its scores as decimal strings
ATTACK_TECHNIQUE = r"^T[0-9]{4}(\.[0-9]{3})?$"
CYBER_DAY = date(2026, 10, 18)  # the day of the offline runs (offline.FIXTURE_NOW): none after
CyberSource = Literal["nvd", "kev", "epss"]


class CvssFixture(_Data):
    """One published CVSS score; its vector is the one of a network flaw of its version."""

    version: Literal["2.0", "3.0", "3.1", "4.0"] = "3.1"
    score: float = Field(default=9.8, ge=0, le=10)
    severity: str = "CRITICAL"
    source: str = "nvd@nist.gov"
    primary: bool = True


class CveReferenceFixture(_Data):
    url: str = Field(pattern=r"^https?://")
    tags: tuple[str, ...] = ()


class CveFixture(_Data):
    """One NVD record, shaped like the API's answer of 2026-10-27; its texts are invented."""

    id: str = Field(pattern=CVE_ID)
    published: str = Field(default="2021-12-10T10:15:09.143", pattern=NVD_TIMESTAMP)
    last_modified: str = Field(default="2025-02-04T15:15:13.773", pattern=NVD_TIMESTAMP)
    status: str = "Analyzed"
    assigner: str = "security@example.org"
    description: str = Field(min_length=1)
    cvss: tuple[CvssFixture, ...] = (CvssFixture(),)
    cwes: tuple[str, ...] = ()
    references: tuple[CveReferenceFixture, ...] = ()


class KevFixture(_Data):
    """One entry of the CISA KEV catalogue; its texts are invented."""

    id: str = Field(pattern=CVE_ID)
    vendor: str = Field(min_length=1)
    product: str = Field(min_length=1)
    name: str = Field(min_length=1)
    date_added: date
    due_date: date
    description: str = Field(min_length=1)
    required_action: str = "Apply updates per vendor instructions."
    ransomware: Literal["Known", "Unknown"] = "Unknown"
    notes: str = ""
    cwes: tuple[str, ...] = ()


class EpssFixture(_Data):
    id: str = Field(pattern=CVE_ID)
    epss: str = Field(pattern=SCORE)
    percentile: str = Field(pattern=SCORE)
    day: date = date(2026, 10, 17)  # the API's "date" field


class AttackObjectFixture(_Data):
    """A technique added to the synthetic ATT&CK bundle (``core/evals/attack_sample.py``)."""

    id: str = Field(pattern=ATTACK_TECHNIQUE)
    name: str = Field(min_length=1)
    tactic: str = "execution"
    description: str = Field(min_length=1)


class CyberFixture(_Data):
    """The fake NVD, KEV and EPSS of a cyber case and the state of its ATT&CK index, served to
    the real cyber_cve and cyber_attack servers (``core/evals/cyber_fixtures.py``): no request
    leaves the machine and nothing is written under ``var/`` of the repository."""

    nvd: tuple[CveFixture, ...] = ()
    searches: dict[str, tuple[str, ...]] = Field(default_factory=dict)  # keyword → ids, oldest 1st
    kev: tuple[KevFixture, ...] = ()  # an empty catalogue is refused by the plugin, as it should
    kev_version: str = "2026.10.17"
    epss: tuple[EpssFixture, ...] = ()
    down: tuple[CyberSource, ...] = ()  # answer HTTP 503
    oversized: tuple[CyberSource, ...] = ()  # answer one byte more than the plugin reads
    attack: Literal["present", "absent", "altered"] = "present"  # altered: another bundle's digest
    techniques: tuple[AttackObjectFixture, ...] = ()
    products: tuple[str, ...] = ()  # produits_suivis of the case's own sources file
    nvd_key: bool = False  # the NVD client sends a stand-in key: never in an answer or log (R6)

    @model_validator(mode="after")
    def _consistent(self) -> CyberFixture:
        for name, ids in (
            ("nvd", [c.id for c in self.nvd]),
            ("kev", [k.id for k in self.kev]),
            ("epss", [e.id for e in self.epss]),
            ("techniques", [t.id for t in self.techniques]),
        ):
            if len(set(ids)) != len(ids):
                raise ValueError(f"{name} : identifiant en double")
        known = {c.id for c in self.nvd}
        for keyword, ids in self.searches.items():
            if missing := sorted(set(ids) - known):
                raise ValueError(f"searches[{keyword}] : absent de nvd : {', '.join(missing)}")
        days = [date.fromisoformat(c.published[:10]) for c in self.nvd]
        days += [k.date_added for k in self.kev] + [e.day for e in self.epss]
        if any(day > CYBER_DAY for day in days):  # R10: nothing after the run's date
            raise ValueError(f"date postérieure au {CYBER_DAY.isoformat()} (R10)")
        return self


LEGI_ARTICLE = r"^LEGIARTI[0-9]{12}$"
LEGI_TEXT = r"^LEGITEXT[0-9]{12}$"


class LegiVersionFixture(_Data):
    """One version of an article as Légifrance publishes it; versions sharing ``text_id`` and
    ``num`` are the versions of one article, each listing the others (``articleVersions``)."""

    id: str = Field(pattern=LEGI_ARTICLE)
    num: str = Field(min_length=1, max_length=40)
    text_id: str = Field(pattern=LEGI_TEXT)
    title: str = Field(min_length=1, max_length=200)  # « Code civil »
    code: bool = True  # a code (CODE) or another text (LODA)
    state: str = Field(default="VIGUEUR", pattern=r"^[A-Z_]{2,30}$")
    start: date
    end: date | None = None  # None: open (Légifrance writes 2999-01-01)
    text: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def _ordered(self) -> LegiVersionFixture:
        if self.end is not None and self.end < self.start:
            raise ValueError(f"{self.id} : fin avant le début")
        return self


class LegalFixture(_Data):
    """The fake Légifrance API of a legal case, served to the real legifrance server
    (``core/evals/legifrance_fixtures.py``): no request leaves the machine, no cache is kept.

    A version may start after the run's day: Légifrance publishes deferred versions before they
    apply, and the plugin must say so (H3); nothing else in the case is dated after it (R10)."""

    versions: tuple[LegiVersionFixture, ...] = ()
    searches: dict[str, tuple[str, ...]] = Field(default_factory=dict)  # keyword → version ids
    environment: Literal["sandbox", "production", "A_DEFINIR"] = "sandbox"  # sources.legifrance
    credentials: bool = True  # stand-in PISTE credentials: never in an answer or a log (R6)
    down: bool = False  # the API answers HTTP 503 (the token endpoint still answers)
    oversized: bool = False  # the API answers one byte more than the plugin reads
    swapped: dict[str, str] = Field(default_factory=dict)  # asked version id → the one sent back

    @model_validator(mode="after")
    def _consistent(self) -> LegalFixture:
        ids = [v.id for v in self.versions]
        if len(set(ids)) != len(ids):
            raise ValueError("versions : identifiant en double")
        known = set(ids)
        for keyword, found in self.searches.items():
            if missing := sorted(set(found) - known):
                raise ValueError(f"searches[{keyword}] : absent de versions : {', '.join(missing)}")
        if missing := sorted(set(self.swapped.values()) - known):
            raise ValueError(f"swapped : absent de versions : {', '.join(missing)}")
        return self


class CompanyYear(_Data):
    """The published accounts of one year, in euros, as the API gives them."""

    ca: int | None = None
    resultat_net: int | None = None


class CompanyFixture(_Data):
    """One company of the fake API Recherche d'entreprises; every name and figure is invented. A
    director, a birth date and a street are added to the reply: none may reach an answer (I4)."""

    siren: str = Field(pattern=r"^[0-9]{9}$")
    nom: str = Field(min_length=1, max_length=200)  # nom_complet, read as data (R5)
    naf: str = Field(default="47.91B", pattern=r"^[0-9]{2}\.[0-9]{2}[A-Z]$")
    categorie: str = Field(default="PME", pattern=r"^(PME|ETI|GE)$")
    etat: Literal["A", "C"] = "A"
    creation: date
    fermeture: date | None = None
    commune: str = Field(min_length=1, max_length=80)
    code_postal: str = Field(pattern=r"^[0-9]{5}$")
    departement: str = Field(pattern=r"^([0-9]{2,3}|2[AB])$")
    effectif: str | None = Field(default="03", pattern=r"^([0-9]{2}|NN)$")
    finances: dict[str, CompanyYear] = Field(default_factory=dict)  # year → accounts
    mise_a_jour: date


class StatsObservationFixture(_Data):
    dimensions: dict[str, str] = Field(min_length=1, max_length=12)
    value: float


class StatsFixture(_Data):
    """One Melodi dataset: its update date and the observations ``/data`` sends back, unfiltered;
    the plugin keeps those that answer the query (R12)."""

    updated: date
    observations: tuple[StatsObservationFixture, ...] = ()


class BusinessFixture(_Data):
    """The fake APIs of a business case, served to the real entreprises and insee_stats servers
    (``core/evals/business_fixtures.py``): no request leaves the machine, no cache is kept."""

    companies: tuple[CompanyFixture, ...] = ()
    datasets: dict[str, StatsFixture] = Field(default_factory=dict)  # Melodi id → dataset
    down: tuple[Literal["entreprises", "insee_melodi"], ...] = ()  # answers HTTP 503

    @model_validator(mode="after")
    def _unique(self) -> BusinessFixture:
        sirens = [company.siren for company in self.companies]
        if len(set(sirens)) != len(sirens):
            raise ValueError("companies : SIREN en double")
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
    records: tuple[RecordFixture, ...] = ()  # what scholar_search finds, by source
    feeds: tuple[FeedFixture, ...] = ()  # the allow-list feed_read reads (the case's own)
    approfondi: bool = False  # asked as with `cerveau ask --approfondi` (D14)
    offline: Offline = Offline()
    store: StoreFixture | None = None  # added to the case's copy of the reference store
    paper: PaperFixture | None = None  # a run of the paper loop instead of a question's run
    learning: LearningFixture | None = None  # a run of the learning loop instead, no model
    code: CodeFixture | None = None  # the repository the code tools read (pack code)
    cyber: CyberFixture | None = None  # the sources the cyber tools read (pack cyber)
    legal: LegalFixture | None = None  # the Légifrance API the legal tools read
    business: BusinessFixture | None = None  # the APIs the business tools read
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
        if (self.learning is None) != (self.expect.learning is None):
            raise ValueError("learning et expect.learning vont ensemble")
        if self.learning is not None and self.paper is not None:
            raise ValueError("learning et paper s'excluent")
        return self

    @model_validator(mode="after")
    def _research_and_its_records(self) -> Case:
        if self.expect.research is not None and not self.approfondi:
            raise ValueError("expect.research suppose approfondi")
        urls = [record.url for record in self.records]
        if len(set(urls)) != len(urls):
            raise ValueError("records : adresse de notice en double")
        if len({feed.id for feed in self.feeds}) != len(self.feeds):
            raise ValueError("feeds : identifiant de flux en double")
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


def golden_files(root: Path = REPO_ROOT) -> list[Path]:
    """The golden set of each pack, in the order of section 9.2; the group of a case is its pack."""
    others = [pack for pack in pack_ids(root / PACKS_DIR) if pack != DEFAULT_DOMAIN]
    return [GOLDEN_FILE, *(PACKS_DIR / pack / "evals" / "golden.jsonl" for pack in others)]


def pack_behavior_files(root: Path = REPO_ROOT) -> list[Path]:
    """The behaviours of each pack, in the order of section 9.2."""
    return [PACKS_DIR / pack / "evals" / "behaviors.yaml" for pack in pack_ids(root / PACKS_DIR)]


def pack_redteam_dirs(root: Path = REPO_ROOT) -> list[Path]:
    """The red team of each pack, in the order of section 9.2; a missing one is an error.

    The general pack's injections are the suite's own (``INJECTION_DIR``); every other pack reads
    other sources and brings its own (ADR-043).
    """
    packs = [pack for pack in pack_ids(root / PACKS_DIR) if pack != DEFAULT_DOMAIN]
    places = [REDTEAM_DIR / f"injection_{pack}" for pack in packs]
    for place in places:
        if not any((root / place).glob("*.yaml")):
            raise CaseError(f"{root / place} : red team absente (ADR-043)")
    return places


def load_golden(root: Path = REPO_ROOT) -> list[Case]:
    """The golden sets of the packs; a pack's missing golden set is an error."""
    cases = []
    for relative in golden_files(root):
        path = root / relative
        if not path.is_file():
            raise CaseError(f"{path} : golden set absent (ADR-043)")
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
        return load_suite_files(root, BEHAVIOR_DIR, *pack_behavior_files(root))
    if suite == "injection":
        return load_suite_files(
            root,
            INJECTION_DIR,
            *pack_redteam_dirs(root),
            EXECUTION_INJECTION_DIR,
            APPROVAL_INJECTION_DIR,
            LEARNING_INJECTION_DIR,
        )
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
