"""The R5 reader: one web page in, checked extracts out (ADR-008).

The reader model has no tool. Its extracts are kept only when the quote is found word for word
in the stored page text and neither the claim nor the quote reads like an instruction; the
planner never sees the page itself, only these extracts, wrapped as data.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field

from core.guardrails.injection import injection_signals
from core.guardrails.input import mark_untrusted
from core.orchestrator.runtime import Run
from core.orchestrator.state import MAX_CLAIM_CHARS, Extract, Source, _Llm
from core.orchestrator.structured import StructuredOutputError, ask_json
from core.verification.domains import registrable_domain
from core.verification.quotes import check_quote

MAX_PAGE_CHARS = 40_000  # page text shown to the reader; quotes are checked on the whole text
MAX_EXTRACTS = 8
MAX_TITLE_CHARS = 200


class Page(_Llm):
    """The fields of web_read's structured result that the graph uses."""

    url: str
    final_url: str
    title: str | None = None
    published: str | None = None
    text: str
    truncated: bool = False
    retrieved_at: str


class _Extracted(_Llm):
    affirmation: str = ""
    citation: str = ""


class ReaderOutput(_Llm):
    extraits: list[_Extracted] = Field(default_factory=list)


@dataclass(frozen=True)
class Reading:
    source: Source
    text: str  # the stored page text, for the quote checks of node 5
    reader_failed: bool = False


def _page_view(page: Page) -> str:
    title = (page.title or "").strip()[:MAX_TITLE_CHARS]
    head = f"Titre : {title}\n\n" if title else ""
    return mark_untrusted(head + page.text[:MAX_PAGE_CHARS], source=page.final_url)


async def read_page(run: Run, question: str, page: Page, *, number: int, url: str) -> Reading:
    messages = [
        SystemMessage(run.prompts.render("reader")),
        HumanMessage(run.prompts.render("reader_task", question=question, page=_page_view(page))),
    ]
    failed = False
    try:
        output = await ask_json(
            partial(run.invoke, "reader"), messages, ReaderOutput, what="lecteur"
        )
    except StructuredOutputError:
        output, failed = ReaderOutput(), True
    extracts: list[Extract] = []
    rejected = max(0, len(output.extraits) - MAX_EXTRACTS)
    flagged = 0
    for item in output.extraits[:MAX_EXTRACTS]:
        claim, quote = item.affirmation.strip(), item.citation.strip()
        if not claim or len(claim) > MAX_CLAIM_CHARS or not check_quote(quote, page.text).ok:
            rejected += 1
        elif injection_signals(f"{claim}\n{quote}"):
            flagged += 1
        else:
            extracts.append(Extract(claim=claim, quote=quote))
    source = Source(
        number=number,
        url=url,
        final_url=page.final_url,
        title=page.title,
        published=page.published,
        retrieved_at=page.retrieved_at,
        truncated=page.truncated or len(page.text) > MAX_PAGE_CHARS,
        domain=registrable_domain(page.final_url),
        extracts=tuple(extracts),
        rejected=rejected,
        flagged=flagged,
        signals=injection_signals(f"{page.title or ''}\n{page.text}"),
    )
    return Reading(source=source, text=page.text, reader_failed=failed)


def extracts_view(source: Source) -> str:
    """What the planner sees of a page: numbered, checked extracts, wrapped as data (R5)."""
    title = source.title or ""
    if injection_signals(title):
        title = "(titre masqué : formulation d'instruction)"
    lines = [
        f"Source [{source.number}] : {title[:MAX_TITLE_CHARS] or 'sans titre'}",
        f"Adresse : {source.final_url}",
        f"Date indiquée par la page (non vérifiée) : {source.published or 'inconnue'}",
    ]
    if source.extracts:
        lines.append("Extraits vérifiés (citation retrouvée mot pour mot dans la page) :")
        for extract in source.extracts:
            lines.append(f"- {extract.claim}\n  Citation : « {extract.quote} »")
    else:
        lines.append("Aucun extrait vérifié : ne cite pas cette source.")
    if source.rejected or source.flagged:
        lines.append(
            f"Extraits écartés : {source.rejected} (citation introuvable ou affirmation trop "
            f"longue), {source.flagged} (formulation d'instruction)."
        )
    if source.signals:
        lines.append("Attention : la page contient des formulations d'instruction, ignorées.")
    return mark_untrusted("\n".join(lines), source=f"web_read [{source.number}]")
