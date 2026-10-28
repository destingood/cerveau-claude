"""The deep research of a pack: plan, collection, verified writing (plan of phase 6, §5, ADR-045).

Inspired by gpt-researcher (a planner, executors, a writer) and STORM (questions from several
angles, an outline before the writing); no code is taken from either. The planner model splits
the question into at most ``max_sub_questions`` sub-questions; the code searches the web and the
scholarly registries for each, then reads at most ``max_reads`` pages or abstracts, one
sub-question after the other. Every text goes through the reader (R5): only the quotes found word
for word in the text read are kept. A scholarly record is read from its abstract only (D12); one
without an abstract is left unread, and one retracted, withdrawn or removed is never read.

The writer model sees the checked extracts only and ties each claim to the extracts it rests on.
The code keeps a claim only when every extract it cites exists and each of its numbers and dates
appears in them; any other claim is removed from the answer and listed with its reason (D15,
R12). The kept claims carry their source numbers, and node 5 checks the answer as it checks the
planner's.

``run.budget`` should be the research's (``RequestBudget.for_deep_research``, D13), set before the
pack's tools open. An exceeded budget, two malformed answers or the kill switch stop the research
with a partial answer built from the verified extracts only (B97).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import ToolException
from pydantic import BaseModel, Field, ValidationError

from core.budget.gate import RequestBudgetExceeded
from core.guardrails.injection import injection_signals
from core.guardrails.input import mark_untrusted
from core.mcp.adapter import McpAdapterError, ToolRefusedError
from core.orchestrator.planner import (
    MASKED_URL,
    Session,
    format_issues,
    keep_reading,
    open_page,
    partial_draft,
    search_web,
)
from core.orchestrator.reader import MAX_TITLE_CHARS, Page, read_page
from core.orchestrator.runtime import KillSwitchEngaged, Run, Toolbox
from core.orchestrator.state import (
    Confiance,
    Confidence,
    Draft,
    DraftAnswer,
    Extract,
    Source,
    SourceKind,
    Unverified,
    _Llm,
    required,
)
from core.orchestrator.structured import StructuredOutputError, ask_json
from core.policy.engine import kill_switch_engaged
from core.verification.citations import CITATION
from core.verification.trace import Evidence, trace

SCHOLAR = "scholar_search"
MAX_WEB_RESULTS = 5
MAX_SCHOLAR_RESULTS = 3
MAX_PLANNED = 20  # a longer plan is malformed; a shorter one is cut to max_sub_questions
MAX_REFS = 6
MAX_REMOVED_CHARS = 300
PROMPTS_DIR = Path("prompts")
PLAN_PROMPT, WRITE_PROMPT = "plan.md", "write.md"
_HEADER = re.compile(r"\A\s*<!--.*?-->[ \t]*\n?", re.DOTALL)  # as in the orchestrator's prompts
# Crossmark update types after which a record is never read (crossref.org, checked 2026-10-22).
WITHDRAWN = frozenset({"retraction", "partial_retraction", "withdrawal", "removal"})
TOOL_ERRORS = (ValidationError, ToolRefusedError, ToolException, McpAdapterError)
FORMAT = "Réponds uniquement par un objet JSON conforme à ce schéma, sans texte autour :\n{schema}"
_REF = re.compile(r"\[?\s*(\d{1,3})\s*\.\s*(\d{1,2})\s*\]?")
_DOI_URL = re.compile(r"https?://(?:dx\.)?doi\.org/(10\.\S+)", re.IGNORECASE)
_END = re.compile(r"[.!?…]+$")
KIND_LABELS: Mapping[SourceKind, str] = {
    "page_web": "page web",
    "preprint": "préprint (aucune relecture par les pairs annoncée)",
    "article": "article publié (relecture par les pairs non vérifiée)",
}
NOTHING_VERIFIED = (
    "Aucune affirmation n'a pu être vérifiée dans les sources lues : la recherche approfondie ne "
    "conclut pas."
)
SYNTHESIS_REMOVED = (
    "Aucune affirmation de la synthèse n'a pu être vérifiée dans les sources lues : voir le "
    "développement et les points non vérifiés."
)
NO_DEVELOPMENT = "Aucune affirmation vérifiée ne développe la synthèse."
# No count here: the answer's R1 check would flag it, and the research signal already gives it.
NOTHING_READ = "Aucune source n'a pu être lue : aucun extrait ne peut être vérifié."
NOTHING_CHECKED = "Aucun extrait des sources lues n'a pu y être vérifié mot pour mot."
LIMITS = (
    " Limites : au plus {reads} lectures ; les publications scientifiques sont lues par leur seul "
    "résumé (D12) ; la recherche n'est pas exhaustive."
)
MASKED_REASON = "(justification masquée : formulation d'instruction)"
MASKED_STEP = "(étape masquée : formulation d'instruction)"
RETRY_STEPS = (
    "Reformuler la question ou la restreindre à un angle précis.",
    "Consulter directement des sources spécialisées du domaine.",
)


class ResearchError(ValueError):
    """The prompts of a deep research are missing or unreadable."""


class SubQuestion(_Llm):
    question: str = Field(min_length=1, max_length=300)
    angle: str = Field(default="", max_length=120, description="Point de vue de la sous-question")
    requete_web: str = Field(min_length=1, max_length=200, description="Requête du moteur web")
    requete_scientifique: str = Field(
        default="",
        max_length=200,
        description="Requête dans les publications scientifiques ; vide si inutile",
    )
    source_scientifique: Literal["arxiv", "crossref"] = "crossref"


class ResearchPlan(_Llm):
    sous_questions: list[SubQuestion] = Field(min_length=1, max_length=MAX_PLANNED)


class Claim(_Llm):
    texte: str = Field(min_length=1, max_length=600)
    extraits: list[str] = Field(
        default_factory=list,
        max_length=MAX_REFS,
        description="Identifiants « n.k » des extraits vérifiés qui fondent l'affirmation",
    )


class Section(_Llm):
    titre: str = Field(min_length=1, max_length=120)
    affirmations: list[Claim] = Field(min_length=1, max_length=12)


class ResearchReport(_Llm):
    synthese: list[Claim] = Field(min_length=1, max_length=6)
    sections: list[Section] = Field(default_factory=list, max_length=8)
    contre_arguments: list[Claim] = Field(default_factory=list, max_length=6)
    confiance: Confiance
    prochaines_etapes: list[str] = Field(default_factory=list, max_length=6)


class _Update(_Llm):
    type: str


class _Record(_Llm):
    """The fields of a scholar_search record that the research uses."""

    source: Literal["arxiv", "crossref"] = "crossref"  # a Crossref abstract is never stored
    identifier: str
    preprint: bool = False
    title: str = ""
    published: str | None = None
    doi: str | None = None
    url: str
    abstract: str | None = None
    abstract_truncated: bool = False
    updated_by: list[_Update] = Field(default_factory=list)
    retrieved_at: str


class _Records(_Llm):
    records: list[_Record] = Field(default_factory=list)


@dataclass(frozen=True)
class ResearchSpec:
    """What a pack gives the deep research (``plugins/deep_research`` for Recherche)."""

    pack: str
    feature: str  # the feature ``config.require`` checks (``recherche.deep_research``)
    planner: str  # system text of the plan
    writer: str  # system text of the writing
    version: str = ""


def _prompt(directory: Path, name: str) -> str:
    try:
        text = (directory / PROMPTS_DIR / name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        reason = f"recherche approfondie : {name} illisible ({type(exc).__name__})"
        raise ResearchError(reason) from exc
    return text.replace("\r\n", "\n")


def load_research(directory: Path, *, pack: str, feature: str, version: str) -> ResearchSpec:
    """The prompts of ``directory/prompts`` without their leading comment. The version adds a
    digest of both, line endings normalised, so that a changed prompt is a new version (R9)."""
    plan, write = _prompt(directory, PLAN_PROMPT), _prompt(directory, WRITE_PROMPT)
    digest = hashlib.sha256(f"{plan}\0{write}".encode()).hexdigest()[:12]
    return ResearchSpec(
        pack=pack,
        feature=feature,
        planner=_HEADER.sub("", plan, count=1).strip(),
        writer=_HEADER.sub("", write, count=1).strip(),
        version=f"{version}+{digest}",
    )


def _update_type(text: str) -> str:
    return "_".join(text.strip().lower().replace("-", " ").split())


@dataclass(frozen=True)
class _Candidate:
    sub: int  # index of its sub-question
    url: str
    record: _Record | None = None

    def keys(self) -> set[str]:
        """What makes two candidates one source: the address, the DOI, the identifier."""
        keys = {self.url.strip().lower().rstrip("/")}
        doi = self.record.doi if self.record is not None else None
        if doi is None and (match := _DOI_URL.fullmatch(self.url.strip())):
            doi = match.group(1)
        if doi:
            keys.add("doi:" + doi.lower())
        if self.record is not None:
            keys.add("id:" + self.record.identifier.lower())
        return keys


def _alternate[T](*queues: Sequence[T]) -> Iterator[T]:
    """The first item of each queue, then the second of each, and so on."""
    for rank in range(max((len(queue) for queue in queues), default=0)):
        for queue in queues:
            if rank < len(queue):
                yield queue[rank]


@dataclass
class Research:
    """What one deep research left: its draft, what it collected and what it removed."""

    record_id: str
    pack: str
    version: str
    question: str  # pseudonymised
    now: str
    plan: list[SubQuestion] = field(default_factory=list)
    sub_questions_cut: int = 0
    scholar_searches: int = 0
    reads: int = 0
    without_abstract: int = 0
    retracted: int = 0
    tool_errors: int = 0
    removed: list[Unverified] = field(default_factory=list)
    updated: dict[int, tuple[str, ...]] = field(default_factory=dict)  # source → update types
    digested: set[int] = field(default_factory=set)  # sources read from a Crossref abstract
    limit: str | None = None  # why it stopped early: a budget limit, format or kill_switch
    halted: bool = False
    draft: Draft | None = None
    session: Session = field(default_factory=Session, repr=False)

    @property
    def searches(self) -> int:
        return self.session.searches + self.scholar_searches

    def to_payload(self) -> dict[str, Any]:
        """The research file: plan, sources, extracts and removed claims; no page, no abstract."""
        return {
            "record_id": self.record_id,
            "pack": self.pack,
            "version": self.version,
            "question": self.question,
            "now": self.now,
            "sub_questions": [sub.model_dump(mode="json") for sub in self.plan],
            "sub_questions_cut": self.sub_questions_cut,
            "searches": self.searches,
            "refused_searches": self.session.refused_searches,
            "masked_urls": self.session.masked_urls,
            "reads": self.reads,
            "without_abstract": self.without_abstract,
            "retracted": self.retracted,
            "tool_errors": self.tool_errors,
            "limit": self.limit,
            "halted": self.halted,
            "sources": [self._stored(source) for source in self.session.sources],
            "removed": [claim.model_dump(mode="json") for claim in self.removed],
        }

    def _stored(self, source: Source) -> dict[str, Any]:
        """A source as the file keeps it. A Crossref abstract is never stored (ADR-044): the
        quotes taken from one give way to their digest."""
        data = source.model_dump(mode="json")
        data["updates"] = list(self.updated.get(source.number, ()))
        if source.number in self.digested:
            data["extracts"] = [
                {"claim": e.claim, "quote_sha256": hashlib.sha256(e.quote.encode()).hexdigest()}
                for e in source.extracts
            ]
        return data


def extract_index(sources: Sequence[Source]) -> dict[str, tuple[Source, Extract]]:
    """Each checked extract under its identifier « n.k »: source n, extract k from 1."""
    return {
        f"{source.number}.{k}": (source, extract)
        for source in sources
        for k, extract in enumerate(source.extracts, start=1)
    }


def _unverified(text: str, reason: str) -> Unverified:
    if len(text) > MAX_REMOVED_CHARS:
        text = text[: MAX_REMOVED_CHARS - 1].rstrip() + "…"
    return Unverified(texte=text, raison=reason)


def _cite(text: str, numbers: Sequence[int]) -> str:
    marker = "[" + ", ".join(str(n) for n in numbers) + "]"
    end = _END.search(text)
    if end is None:
        return f"{text} {marker}"
    return f"{text[: end.start()].rstrip()} {marker}{end.group(0)}"


def _sentences(claims: Sequence[str]) -> str:
    """Claims joined as sentences: the answer's checks count them by their full stops."""
    return " ".join(claim if _END.search(claim) else f"{claim}." for claim in claims)


def check_claim(claim: Claim, extracts: Mapping[str, tuple[Source, Extract]]) -> str | Unverified:
    """The claim with its source numbers, or why it is removed (D15): it cites known extracts
    only, at least one, and each of its numbers and dates appears in what it cites (R1)."""
    text = " ".join(CITATION.sub("", claim.texte).split())
    if not text:
        return _unverified(claim.texte, "aucun texte hors des renvois")
    refs: list[str] = []
    for raw in claim.extraits:
        match = _REF.fullmatch(raw.strip())
        ref = f"{int(match.group(1))}.{int(match.group(2))}" if match else raw.strip()
        if ref not in extracts:
            return _unverified(text, f"renvoi inconnu : {raw.strip()[:20]}")
        if ref not in refs:
            refs.append(ref)
    if not refs:
        return _unverified(text, "aucun extrait vérifié cité")
    cited = [extracts[ref] for ref in refs]
    sources = {source.number: source for source, _extract in cited}
    texts = [(f"source [{source.number}]", extract.quote) for source, extract in cited]
    for number, source in sources.items():  # a title or a date of publication may be cited
        texts += [(f"source [{number}]", text) for text in (source.title, source.published) if text]
    for row in trace(text, Evidence(texts)):
        if not row.traced:
            what = "chiffre" if row.kind == "nombre" else "date"
            if row.contrary:
                return _unverified(text, f"{what} « {row.text} » de sens contraire à l'extrait")
            return _unverified(text, f"{what} « {row.text} » absent des extraits cités")
    return _cite(text, sorted(sources))


def _title(title: str, rank: int) -> str:
    """A section title states no fact: one with a number, a date, a marker or an instruction-like
    phrasing gives way to « Partie n »."""
    title = " ".join(title.split())
    if trace(title, Evidence()) or CITATION.search(title) or injection_signals(title):
        return f"Partie {rank}"
    return title


def compose(
    report: ResearchReport,
    extracts: Mapping[str, tuple[Source, Extract]],
    removed: list[Unverified],
    *,
    max_reads: int,
) -> DraftAnswer:
    """The answer from the claims that pass ``check_claim``; the others go to ``removed``."""

    def kept(claims: Sequence[Claim]) -> list[str]:
        texts: list[str] = []
        for claim in claims:
            checked = check_claim(claim, extracts)
            if isinstance(checked, Unverified):
                removed.append(checked)
            else:
                texts.append(checked)
        return texts

    before = len(removed)
    synthesis = kept(report.synthese)
    parts: list[str] = []
    for rank, section in enumerate(report.sections, start=1):
        claims = kept(section.affirmations)
        if claims:
            items = "\n".join(f"- {claim}" for claim in claims)
            parts.append(f"### {_title(section.titre, rank)}\n\n{items}")
    contrary = kept(report.contre_arguments)
    level: Confidence = report.confiance.niveau
    justification = _unless_instruction(report.confiance.justification.strip(), MASKED_REASON)
    if not synthesis:
        level = "faible"
        justification += (
            " (Confiance ramenée à « faible » : aucune affirmation de la synthèse n'a pu être "
            "vérifiée.)"
        )
    elif level == "eleve" and len(removed) > before:
        level = "moyen"
        justification += (
            " (Confiance ramenée à « moyen » : des affirmations non vérifiées ont été retirées.)"
        )
    return DraftAnswer(
        synthese=_sentences(synthesis)
        or (SYNTHESIS_REMOVED if parts or contrary else NOTHING_VERIFIED),
        developpement="\n\n".join(parts) or NO_DEVELOPMENT,
        contre_arguments=_sentences(contrary),
        confiance=Confiance(
            niveau=level, justification=justification + LIMITS.format(reads=max_reads)
        ),
        prochaines_etapes=[
            _unless_instruction(step.strip(), MASKED_STEP)
            for step in report.prochaines_etapes
            if step.strip()
        ],
    )


def _unless_instruction(text: str, masked: str) -> str:
    """The writer read external content: a free text of it phrased as an instruction is masked
    (R5), as a section title is."""
    return masked if injection_signals(text) else text


def unverified_answer(reads: int, max_reads: int) -> DraftAnswer:
    """No extract could be checked in what was read: no conclusion, and no writer is called."""
    return DraftAnswer(
        synthese=NOTHING_VERIFIED,
        developpement=NOTHING_CHECKED if reads else NOTHING_READ,
        confiance=Confiance(
            niveau="faible",
            justification="Aucun extrait vérifié : aucune conclusion n'en est tirée."
            + LIMITS.format(reads=max_reads),
        ),
        prochaines_etapes=list(RETRY_STEPS),
    )


def _system(text: str, schema: type[BaseModel]) -> str:
    return f"{text}\n\n" + FORMAT.format(
        schema=json.dumps(schema.model_json_schema(), ensure_ascii=False)
    )


class _Researcher:
    def __init__(self, run: Run, spec: ResearchSpec, research: Research) -> None:
        self.run, self.spec, self.research = run, spec, research
        self.session = research.session
        self.toolbox: Toolbox = required(run.toolbox, "outils du pack")
        limits = run.config.budgets.per_deep_research
        self.max_sub_questions, self.max_reads = limits.max_sub_questions, limits.max_reads

    def _halt_if_engaged(self) -> None:
        if kill_switch_engaged(self.run.project_root):  # R4: before each tool call
            raise KillSwitchEngaged

    def _head(self) -> str:
        return (
            f"Question de Lucas :\n{self.research.question}\n\nDate du jour : {self.research.now}"
        )

    async def plan(self) -> list[SubQuestion]:
        task = f"{self._head()}\n\nPropose au plus {self.max_sub_questions} sous-questions."
        messages = [SystemMessage(_system(self.spec.planner, ResearchPlan)), HumanMessage(task)]
        plan = await ask_json(
            partial(self.run.invoke, "planner"), messages, ResearchPlan, what="plan de recherche"
        )
        kept = plan.sous_questions[: self.max_sub_questions]
        self.research.plan = kept
        self.research.sub_questions_cut = len(plan.sous_questions) - len(kept)
        return kept

    async def _search(self, index: int, sub: SubQuestion) -> list[_Candidate]:
        self._halt_if_engaged()
        arguments: dict[str, Any] = {"query": sub.requete_web, "max_results": MAX_WEB_RESULTS}
        try:
            hits = await search_web(self.session, self.toolbox, arguments) or []
        except TOOL_ERRORS:
            self.research.tool_errors += 1
            hits = []
        web = [_Candidate(index, hit.url) for hit in hits if hit.url != MASKED_URL]
        records: list[_Candidate] = []
        if sub.requete_scientifique.strip():
            self._halt_if_engaged()
            arguments = {
                "query": sub.requete_scientifique,
                "source": sub.source_scientifique,
                "max_results": MAX_SCHOLAR_RESULTS,
            }
            try:
                found = _Records.model_validate(await self.toolbox.call(SCHOLAR, arguments))
            except TOOL_ERRORS:
                self.research.tool_errors += 1
            else:
                self.research.scholar_searches += 1
                for record in found.records:
                    self.session.search_texts.append(record.title)
                    records.append(_Candidate(index, record.url, record))
        return list(_alternate(web, records))

    async def collect(self, plan: Sequence[SubQuestion]) -> None:
        """Searches for each sub-question, then reads in turn, one sub-question after the other."""
        queues = [await self._search(index, sub) for index, sub in enumerate(plan)]
        seen: set[str] = set()
        for candidate in _alternate(*queues):
            if self.research.reads >= self.max_reads:
                break
            keys = candidate.keys()
            if keys & seen:
                continue
            seen |= keys
            question = f"{self.research.question}\n\nSous-question : {plan[candidate.sub].question}"
            await self._read(candidate, question)

    async def _read(self, candidate: _Candidate, question: str) -> None:
        self._halt_if_engaged()
        record = candidate.record
        if record is None:
            arguments = {"url": candidate.url}
            try:
                source = await open_page(self.run, self.session, self.toolbox, arguments, question)
            except TOOL_ERRORS:
                self.research.tool_errors += 1
                return
            # A text instead: the address is that of a page already read, after its redirection.
            self.research.reads += isinstance(source, Source)
            return
        updates = tuple(sorted({_update_type(update.type) for update in record.updated_by}))
        if WITHDRAWN.intersection(updates):
            self.research.retracted += 1
            return
        abstract = (record.abstract or "").strip()
        if not abstract:
            self.research.without_abstract += 1
            return
        page = Page(
            url=record.url,
            final_url=record.url,
            title=record.title or None,
            published=record.published,
            text=abstract,
            truncated=record.abstract_truncated,
            retrieved_at=record.retrieved_at,
        )
        number = len(self.session.sources) + 1
        reading = await read_page(self.run, question, page, number=number, url=record.url)
        kind: SourceKind = "preprint" if record.preprint else "article"
        source = reading.source.model_copy(update={"kind": kind})
        keep_reading(self.session, dataclasses.replace(reading, source=source), record.url)
        self.research.reads += 1
        if record.source == "crossref":
            self.research.digested.add(number)
        if updates:
            self.research.updated[number] = updates

    def _view(self, source: Source) -> str:
        title = source.title or "sans titre"
        if injection_signals(title):
            title = "(titre masqué : formulation d'instruction)"
        lines = [
            f"Source [{source.number}] : {title[:MAX_TITLE_CHARS]}",
            f"Type : {KIND_LABELS[source.kind]}",
            f"Date indiquée (non vérifiée) : {source.published or 'inconnue'}",
            f"Domaine : {source.domain or 'inconnu'}",
        ]
        if updates := self.research.updated.get(source.number):
            lines.append("Mise à jour publiée de la notice : " + ", ".join(updates))
        lines.append("Extraits vérifiés (citation retrouvée mot pour mot) :")
        for k, extract in enumerate(source.extracts, start=1):
            lines.append(f"- [{source.number}.{k}] {extract.claim}")
            lines.append(f"  Citation : « {extract.quote} »")
        return mark_untrusted("\n".join(lines), source=f"source [{source.number}]")

    async def write(self, plan: Sequence[SubQuestion]) -> ResearchReport:
        listing = "\n".join(f"{n}. {sub.question}" for n, sub in enumerate(plan, start=1))
        views = "\n\n".join(self._view(s) for s in self.session.sources if s.extracts)
        task = (
            f"{self._head()}\n\nSous-questions étudiées :\n{listing}\n\n"
            f"Extraits vérifiés des sources lues :\n\n{views}"
        )
        messages = [SystemMessage(_system(self.spec.writer, ResearchReport)), HumanMessage(task)]
        return await ask_json(
            partial(self.run.invoke, "planner_complex"), messages, ResearchReport, what="rédaction"
        )

    async def execute(self) -> Draft:
        plan = await self.plan()
        await self.collect(plan)
        extracts = extract_index(self.session.sources)
        if not extracts:
            return self.session.draft(unverified_answer(self.research.reads, self.max_reads))
        report = await self.write(plan)
        answer = compose(report, extracts, self.research.removed, max_reads=self.max_reads)
        return self.session.draft(answer, format_issues=tuple(format_issues(answer, "complexe")))


async def run_research(
    run: Run, spec: ResearchSpec, *, question: str, now: str, record_id: str
) -> Research:
    """One deep research on ``question`` (already pseudonymised).

    It ends with a draft, partial when a budget limit, two malformed answers or the kill switch
    (``halted``) stopped it; any other error propagates.
    """
    run.config.require(spec.feature)  # R7: a marker still blocks the research
    research = Research(
        record_id=record_id, pack=spec.pack, version=spec.version, question=question, now=now
    )
    try:
        research.draft = await _Researcher(run, spec, research).execute()
        return research
    except StructuredOutputError:
        limit = "format"
    except RequestBudgetExceeded as exc:
        limit = exc.limit
    except KillSwitchEngaged:
        limit, research.halted = "kill_switch", True
    research.limit = limit
    research.draft = partial_draft(research.session, limit)
    return research
