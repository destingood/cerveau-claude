"""State of the graph (section 7.1, and the committee of phase 3) and the output of each node.

The state may be traced (Langfuse, commit 13): it holds the pseudonymised question only. The raw
question, the pseudonym table and the raw URLs Lucas gave stay in the request's ``Run``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.verification.trace import ToolOutput, TraceKind

MAX_CLAIM_CHARS = 300
MARKER = "[VERIFICATION REQUIRED]"

Decision = Literal["ok", "clarification", "refus"]
ActionClass = Literal[
    "LECTURE",
    "CALCUL",
    "ECRITURE_INTERNE",
    "COMMUNICATION_EXTERNE",
    "IRREVERSIBLE",
    "FINANCIERE",
]
Complexity = Literal["simple", "complexe"]
Importance = Literal["normale", "elevee"]
Confidence = Literal["faible", "moyen", "eleve"]
Status = Literal["complete", "partielle", "clarification", "refus"]
Mode = Literal["direct", "comite"]  # D15: the committee answers decision questions


def required[T](value: T | None, node: str) -> T:
    """The output of an earlier node; its absence is a wiring error of the graph."""
    if value is None:
        raise RuntimeError(f"graphe mal câblé : sortie du nœud « {node} » absente")
    return value


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Llm(BaseModel):
    """A model's JSON output: unknown keys are ignored, the rest is validated."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class RequestContext(_Node):  # node 1
    request_id: str
    now: str
    domain: str
    autonomy_level: str
    environment: str = "dev"
    app_context: str = "interface en ligne de commande (CLI), un seul utilisateur"
    memory: str = "aucune (mémoire désactivée en phase 1)"
    kill_switch: bool
    live_enabled: bool = False  # no live adapter exists: refused before any call (R3)


class InputVerdict(_Llm):  # the classifier's output, node 2
    decision: Decision
    classe_action: ActionClass = "LECTURE"
    raison: str = Field(max_length=400)
    questions: list[str] = Field(default_factory=list, max_length=3)


class GuardedInput(_Node):  # node 2
    question: str  # pseudonymised
    urls: tuple[str, ...] = ()  # given by Lucas, as written in ``question``: data only
    decision: Decision
    action_class: ActionClass = "LECTURE"
    reason: str
    questions: tuple[str, ...] = ()
    pii_counts: dict[str, int] = Field(default_factory=dict)
    removed_characters: int = 0


class RouteVerdict(_Llm):  # the router's output, node 3
    domaine: str = "generaliste"
    complexite: Complexity
    importance: Importance
    web: bool
    mode: Mode = "direct"
    raison: str = Field(max_length=400)


class RoutePlan(_Node):  # node 3
    domain: str
    requested_domain: str
    complexity: Complexity
    importance: Importance
    needs_web: bool
    reason: str
    role: Literal["planner", "planner_complex"]
    tier: str
    tools: tuple[str, ...] = ()
    skipped: dict[str, str] = Field(default_factory=dict)
    mode: Mode = "direct"
    mode_note: str | None = None  # why a committee asked for was not convened


class Extract(_Node):
    claim: str = Field(max_length=MAX_CLAIM_CHARS)
    quote: str  # checked word for word against the stored page text


class Source(_Node):
    number: int
    url: str  # as the planner asked for it
    final_url: str
    title: str | None
    published: str | None  # date found in the page, unverified
    retrieved_at: str
    truncated: bool
    domain: str | None
    extracts: tuple[Extract, ...] = ()
    rejected: int = 0  # quote not found in the page, claim too long or empty
    flagged: int = 0  # dropped for instruction-like phrasing (R5)
    signals: tuple[str, ...] = ()  # instruction-like patterns found in the page


class Confiance(_Llm):
    niveau: Confidence
    justification: str


class DraftAnswer(_Llm):  # the planner's final JSON
    synthese: str
    developpement: str
    contre_arguments: str = ""
    confiance: Confiance
    prochaines_etapes: list[str] = Field(default_factory=list)


class Draft(_Node):  # node 4
    answer: DraftAnswer
    partial: bool = False
    limit: str | None = None  # why the answer is partial
    format_issues: tuple[str, ...] = ()
    sources: tuple[Source, ...] = ()
    pages: dict[int, str] = Field(default_factory=dict)  # stored page text, by source number
    search_texts: tuple[str, ...] = ()  # titles and snippets of the search results
    tool_outputs: tuple[ToolOutput, ...] = ()  # the figures and texts of the other tool calls
    searches: int = 0
    refused_urls: int = 0  # web_read refused: URL from neither a search nor the question
    masked_urls: int = 0  # search results whose address reads as an instruction (B68)
    refused_searches: int = 0  # queries that carried a figure or an identifier of a tool (R6)
    refused_outputs: int = 0  # tool results that read as an instruction (R5)
    bounded_outputs: int = 0  # tool results shown with their lists cut (B96)
    turns: int = 0


class Issue(_Node):
    kind: str
    detail: str


class TraceRow(_Node):
    """One number or date of the answer: where it comes from, without its text (R1, R11)."""

    field: str  # synthese, developpement or contre_arguments
    n: int  # its rank in the field, from 1
    kind: TraceKind
    origin: str | None  # "<tool>#<n> › <figure id>", "<tool>#<n>", "question", "source [n]"…
    contrary: bool = False  # a source gives the value with the contrary sign

    @property
    def traced(self) -> bool:
        return self.origin is not None and not self.contrary


class VerificationReport(_Node):  # node 5
    answer: DraftAnswer  # with the markers inserted
    issues: tuple[Issue, ...] = ()
    quotes_checked: int = 0
    quotes_failed: int = 0
    numbers_unmatched: int = 0  # contrary signs included
    numbers_contrary: int = 0
    dates_unmatched: int = 0
    trace: tuple[TraceRow, ...] = ()
    uncited_marked: int = 0
    cited_domains: tuple[str, ...] = ()
    confidence: Confidence


class CommitteeOutcome(_Node):
    """What a committee session left: its record, its file and what the answer shows (D19)."""

    record_id: str
    pack: str
    version: str
    status: Literal["complete", "incomplete", "echec"]
    reason: str | None = None
    halted: bool = False
    decision: dict[str, Any] | None = None  # ManagerDecision, as JSON
    verdict: Literal["OK", "BLOQUER"] | None = None
    verdict_reasons: tuple[str, ...] = ()
    roles: int = 0
    file: str  # relative to the project root
    file_sha256: str
    tool_outputs: tuple[ToolOutput, ...] = ()
    sources: tuple[Source, ...] = ()

    @property
    def concluded(self) -> bool:
        return self.status == "complete" and self.decision is not None


class SourceRef(_Node):
    number: int
    title: str | None
    url: str
    published: str | None
    retrieved_at: str


class CommitteeView(_Node):
    """The committee's conclusion as the answer shows it: a proposal, never an order (R16)."""

    record_id: str
    libelle: str  # « analyse » at N0, « proposition non exécutée » from N1
    decision: str | None = None  # agir, ne_pas_agir or attendre; None: pas de décision
    proposition: str = ""
    horizon: str | None = None
    horizon_bornes: str = ""
    invalidation: tuple[str, ...] = ()
    desaccords: tuple[str, ...] = ()
    verdict: str | None = None
    raisons: tuple[str, ...] = ()


class Answer(_Node):  # node 6: format 7.3
    statut: Status
    synthese: str = ""
    developpement: str = ""
    contre_arguments: str = ""
    confiance: Confiance | None = None
    sources: tuple[SourceRef, ...] = ()
    points_a_verifier: tuple[str, ...] = ()
    prochaines_etapes: tuple[str, ...] = ()
    signalements: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    message: str = ""  # refusal, clarification or partial answer notice
    comite: CommitteeView | None = None
    links_removed: int = 0


class CerveauState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    context: RequestContext | None = None
    guarded: GuardedInput | None = None
    route: RoutePlan | None = None
    draft: Draft | None = None
    verification: VerificationReport | None = None
    committee: CommitteeOutcome | None = None
    answer: Answer | None = None
    policy: dict[str, Any] | None = None  # PolicyDecision.to_payload()
    audited: bool = False
