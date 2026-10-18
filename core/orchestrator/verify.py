"""Node 5: checks of the draft before it reaches Lucas (sections 7.1 and 7.3, R1, R12).

Deterministic checks first: every [n] points to a read source, every quote followed by [n] is
found word for word in source n, every checked number appears in the question, a page or a
search result title. A fast model then only says which uncited passages state a fact; the code
inserts the ``[VERIFICATION REQUIRED]`` markers and lowers the confidence when a check fails.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field

from core.budget.gate import RequestBudgetExceeded
from core.guardrails.input import mark_untrusted
from core.orchestrator.runtime import Run
from core.orchestrator.state import (
    MARKER,
    CerveauState,
    Confiance,
    Confidence,
    Issue,
    VerificationReport,
    _Llm,
    required,
)
from core.orchestrator.structured import StructuredOutputError, ask_json
from core.verification.citations import CITATION, citation_numbers, unit_spans
from core.verification.domains import independent_domains
from core.verification.numbers import NumberMention, unmatched_numbers
from core.verification.quotes import MIN_QUOTE_CHARS, check_quote, normalise

FIELDS = {
    "synthese": "synthèse",
    "developpement": "développement",
    "contre_arguments": "contre-arguments",
}
MAX_VERIFIER_UNITS = 40  # passages beyond it are marked without asking the model
MAX_DETAIL_CHARS = 80
MIN_INDEPENDENT_DOMAINS = 2  # section 7.3, importance « elevee »
_QUOTED = re.compile(
    r"(?:«(?P<g>[^»]{1,1000})»|“(?P<c>[^”]{1,1000})”|\"(?P<s>[^\"\n]{1,1000})\")\s*"
    rf"(?P<cit>{CITATION.pattern})"
)


class VerifierOutput(_Llm):
    factuels: list[int] = Field(default_factory=list)


@dataclass
class _Field:
    name: str
    label: str
    text: str
    marks: set[int] = field(default_factory=set)


def clip(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= MAX_DETAIL_CHARS else flat[: MAX_DETAIL_CHARS - 1] + "…"


def insert_markers(text: str, positions: set[int]) -> str:
    """Inserts `` [VERIFICATION REQUIRED]`` at each position, never twice in a row."""
    out = text
    for position in sorted(positions, reverse=True):
        if out[position:].lstrip().startswith(MARKER):
            continue
        out = f"{out[:position]} {MARKER}{out[position:]}"
    return out


def _number_end(text: str, mention: NumberMention) -> int:
    end = mention.end
    while end > mention.start and text[end - 1].isspace():
        end -= 1
    return end


def _check_citations(item: _Field, count: int, issues: list[Issue]) -> None:
    for marker in CITATION.finditer(item.text):
        bad = [n for n in citation_numbers(marker.group(0)) if not 1 <= n <= count]
        if bad:
            item.marks.add(marker.end())
            numbers = ", ".join(str(n) for n in bad)
            issues.append(
                Issue(
                    kind="citation_orpheline",
                    detail=f"{item.label} : renvoi [{numbers}] sans source lue correspondante",
                )
            )


def _check_quotes(item: _Field, pages: dict[int, str], issues: list[Issue]) -> tuple[int, int]:
    checked = failed = 0
    for match in _QUOTED.finditer(item.text):
        quote = match.group("g") or match.group("c") or match.group("s") or ""
        if len(normalise(quote)) < MIN_QUOTE_CHARS:
            continue
        checked += 1
        numbers = [n for n in citation_numbers(match.group("cit")) if n in pages]
        if not any(check_quote(quote, pages[n]).ok for n in numbers):
            failed += 1
            item.marks.add(match.end())
            issues.append(
                Issue(
                    kind="citation_inexacte",
                    detail=f"{item.label} : citation « {clip(quote)} » introuvable dans la "
                    "source citée",
                )
            )
    return checked, failed


def _check_numbers(item: _Field, haystack: list[str], issues: list[Issue]) -> int:
    mentions = unmatched_numbers(item.text, haystack)
    for mention in mentions:
        item.marks.add(_number_end(item.text, mention))
        issues.append(
            Issue(
                kind="chiffre_non_source",
                detail=f"{item.label} : « {mention.text} » ne figure dans aucune source",
            )
        )
    return len(mentions)


async def factual_units(run: Run, passages: list[str]) -> set[int] | None:
    """Numbers of the passages that state a fact; ``None`` when the verifier is unavailable."""
    listing = "\n".join(f"{n}. {' '.join(p.split())}" for n, p in enumerate(passages, start=1))
    messages = [
        SystemMessage(run.prompts.render("verifier")),
        HumanMessage(mark_untrusted(listing, source="passages à vérifier")),
    ]
    try:
        output = await ask_json(
            partial(run.invoke, "verifier"), messages, VerifierOutput, what="vérificateur"
        )
    except (StructuredOutputError, RequestBudgetExceeded):
        return None
    return {n for n in output.factuels if 1 <= n <= len(passages)}


async def verify_node(run: Run, state: CerveauState) -> dict[str, Any]:
    guarded = required(state.guarded, "garde")
    route, draft = required(state.route, "routage"), required(state.draft, "planificateur")
    answer, count = draft.answer, len(draft.sources)
    haystack = [guarded.question, *draft.pages.values(), *draft.search_texts]
    issues = [Issue(kind="format", detail=detail) for detail in draft.format_issues]
    items = [_Field(name, label, getattr(answer, name)) for name, label in FIELDS.items()]
    checked = failed = unmatched = 0
    pending: list[tuple[_Field, int, str]] = []  # uncited passages: field, end, text
    for item in items:
        _check_citations(item, count, issues)
        quotes = _check_quotes(item, draft.pages, issues)
        checked, failed = checked + quotes[0], failed + quotes[1]
        unmatched += _check_numbers(item, haystack, issues)
        if not draft.partial:  # a partial answer only quotes checked extracts
            for start, end in unit_spans(item.text):
                unit = item.text[start:end]
                if not CITATION.search(unit) and MARKER not in unit:
                    pending.append((item, end, unit))
    marked = 0
    if pending:
        asked = [unit for _item, _end, unit in pending[:MAX_VERIFIER_UNITS]]
        factual = await factual_units(run, asked)
        if factual is None:
            issues.append(
                Issue(
                    kind="verificateur_indisponible",
                    detail="vérificateur indisponible : chaque passage sans source est marqué",
                )
            )
            factual = set(range(1, len(pending) + 1))
        for index, (item, end, unit) in enumerate(pending, start=1):
            if index in factual or index > MAX_VERIFIER_UNITS:
                item.marks.add(end)
                marked += 1
                issues.append(
                    Issue(
                        kind="affirmation_non_sourcee",
                        detail=f"{item.label} : « {clip(unit)} » sans source",
                    )
                )
    by_number = {source.number: source for source in draft.sources}
    cited = sorted({n for item in items for n in citation_numbers(item.text) if n in by_number})
    domains = independent_domains(by_number[n].final_url for n in cited)
    few_domains = len(domains) < MIN_INDEPENDENT_DOMAINS
    if route.importance == "elevee" and not draft.partial and few_domains:
        issues.append(
            Issue(
                kind="sources_independantes",
                detail=f"question à fort enjeu : {len(domains)} domaine(s) indépendant(s) "
                f"cité(s), {MIN_INDEPENDENT_DOMAINS} au moins sont attendus",
            )
        )
    level: Confidence = answer.confiance.niveau
    justification = answer.confiance.justification.strip()
    if draft.partial:
        level = "faible"
    elif level == "eleve" and (issues or few_domains):
        level = "moyen"
        justification += (
            " (Confiance ramenée à « moyen » par la vérification : "
            + ("points à vérifier relevés." if issues else "moins de deux sources indépendantes.")
            + ")"
        )
    updates: dict[str, Any] = {item.name: insert_markers(item.text, item.marks) for item in items}
    updates["confiance"] = Confiance(niveau=level, justification=justification)
    report = VerificationReport(
        answer=answer.model_copy(update=updates),
        issues=tuple(issues),
        quotes_checked=checked,
        quotes_failed=failed,
        numbers_unmatched=unmatched,
        uncited_marked=marked,
        cited_domains=tuple(domains),
        confidence=level,
    )
    return {"verification": report}
