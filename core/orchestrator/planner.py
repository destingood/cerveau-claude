"""Node 4: the planner's tool loop and its draft answer (sections 7.1 and 7.3).

The planner model asks for tools; the code runs them. web_read only opens an address that came
from a web_search of this request or from Lucas's question (R5), and the planner never sees a
page: the reader turns it into checked extracts first (``reader.py``). Hitting a request limit
gives an honest partial answer built from the verified extracts only, without a conclusion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
)
from langchain_core.tools import ToolException
from pydantic import Field, ValidationError

from core.budget.gate import RequestBudgetExceeded
from core.guardrails.injection import injection_signals
from core.guardrails.input import mark_untrusted
from core.mcp.adapter import McpAdapterError, ToolRefusedError
from core.orchestrator.reader import Page, extracts_view, read_page
from core.orchestrator.runtime import Run, Toolbox
from core.orchestrator.state import (
    CerveauState,
    Complexity,
    Confiance,
    Draft,
    DraftAnswer,
    Source,
    _Llm,
    required,
)
from core.orchestrator.structured import REPAIR, message_text, parse_json, short_error
from core.verification.citations import CITATION

SEARCH, READ = "web_search", "web_read"
MAX_PLANNER_TURNS = 15
MAX_TITLE_CHARS = 120
MAX_PARTIAL_QUOTES = 10
LIMIT_TEXT = {
    "tool_calls": "le nombre maximal d'appels d'outils",
    "tokens": "le nombre maximal de tokens",
    "seconds": "la durée maximale",
    "tours": "le nombre maximal de tours du planificateur",
    "format": "deux réponses mal formées du planificateur",
}
FORMAT_REPAIR = (
    "Ta réponse ne respecte pas le format demandé : {issues}. "
    "Réponds de nouveau uniquement par l'objet JSON corrigé, sans texte autour."
)
READ_REFUSED = (
    "Refus : web_read n'ouvre que les adresses données par web_search dans cette requête ou "
    "écrites dans la question de Lucas (R5). Lance d'abord une recherche."
)
_SENTENCE_END = re.compile(r"[.!?…]+[\"»”)\]]*(?=\s|$)")


class _Hit(_Llm):
    rank: int = 0
    title: str = ""
    url: str
    snippet: str = ""


class _Results(_Llm):
    results: list[_Hit] = Field(default_factory=list)


@dataclass
class Session:
    allowed: set[str] = field(default_factory=set)  # addresses web_read may open
    sources: list[Source] = field(default_factory=list)
    pages: dict[int, str] = field(default_factory=dict)
    read: dict[str, int] = field(default_factory=dict)  # address → source number
    search_texts: list[str] = field(default_factory=list)
    searches: int = 0
    refused_urls: int = 0
    turns: int = 0
    reader_failures: int = 0

    def draft(self, answer: DraftAnswer, **extra: Any) -> Draft:
        return Draft(
            answer=answer,
            sources=tuple(self.sources),
            pages=dict(self.pages),
            search_texts=tuple(self.search_texts),
            searches=self.searches,
            refused_urls=self.refused_urls,
            turns=self.turns,
            **extra,
        )


def sentence_count(text: str) -> int:
    """Approximate: citation markers removed, runs of terminal punctuation counted."""
    plain = CITATION.sub("", text).strip()
    if not plain:
        return 0
    ends = list(_SENTENCE_END.finditer(plain))
    tail = plain[ends[-1].end() :].strip() if ends else plain
    return len(ends) + (1 if tail else 0)


def format_issues(answer: DraftAnswer, complexity: Complexity) -> list[str]:
    issues: list[str] = []
    low, high = (3, 5) if complexity == "complexe" else (1, 3)
    count = sentence_count(answer.synthese)
    if not low <= count <= high:
        issues.append(f"la synthèse doit compter {low} à {high} phrases (environ {count})")
    if not answer.developpement.strip():
        issues.append("le développement est vide")
    if complexity == "complexe":
        if not answer.contre_arguments.strip():
            issues.append("le meilleur argument contraire manque (contre_arguments)")
        if not any(step.strip() for step in answer.prochaines_etapes):
            issues.append("aucune prochaine étape")
    if not answer.confiance.justification.strip():
        issues.append("la justification de la confiance est vide")
    return issues


def partial_draft(session: Session, limit: str) -> Draft:
    lines: list[str] = []
    for source in session.sources:
        for extract in source.extracts:
            if len(lines) < MAX_PARTIAL_QUOTES:
                lines.append(f"- {extract.claim} : « {extract.quote} » [{source.number}]")
    read = (
        "Les extraits vérifiés des sources déjà lues sont repris ci-dessous, mot pour mot, "
        "sans conclusion."
        if lines
        else "Aucun extrait vérifié n'a pu être tiré des sources avant l'arrêt."
    )
    answer = DraftAnswer(
        synthese=(
            f"Réponse partielle : la requête a atteint {LIMIT_TEXT[limit]} avant la fin de "
            f"l'analyse. {read} Vérifie ces sources ou relance une question plus ciblée."
        ),
        developpement="\n".join(lines) or "Aucun extrait vérifié n'est disponible.",
        confiance=Confiance(
            niveau="faible",
            justification="Analyse interrompue avant sa vérification complète : aucune "
            "conclusion n'en est tirée.",
        ),
        prochaines_etapes=[
            "Reformuler ou découper la question pour qu'elle tienne dans les limites d'une "
            "requête.",
            "Lire les sources citées pour compléter l'analyse.",
        ],
    )
    return session.draft(answer, partial=True, limit=limit)


def _masked_title(title: str) -> str:
    title = " ".join(title.split())[:MAX_TITLE_CHARS]
    return "(titre masqué : formulation d'instruction)" if injection_signals(title) else title


async def _search(session: Session, toolbox: Toolbox, arguments: dict[str, Any]) -> str:
    hits = _Results.model_validate(await toolbox.call(SEARCH, arguments)).results
    session.searches += 1
    lines: list[str] = []
    for position, hit in enumerate(hits, start=1):
        session.allowed.add(hit.url)
        session.search_texts.append(hit.title)  # the planner sees titles, not snippets
        lines.append(f"{hit.rank or position}. {_masked_title(hit.title)} — {hit.url}")
    body = "\n".join(lines) or "Aucun résultat."
    return (
        mark_untrusted(body, source="web_search")
        + "\nPour lire une page, appelle web_read avec l'une de ces adresses."
    )


async def _read(
    run: Run, session: Session, toolbox: Toolbox, arguments: dict[str, Any], question: str
) -> str:
    url = str(arguments.get("url", "")).strip()
    given = run.url_map.get(url)
    if url not in session.allowed and given is None:
        session.refused_urls += 1
        return READ_REFUSED
    if url in session.read:
        return f"Source [{session.read[url]}] déjà lue : réutilise ses extraits."
    page = Page.model_validate(await toolbox.call(READ, {**arguments, "url": given or url}))
    if given is not None:  # an address Lucas wrote: the models only see its masked form
        page = page.model_copy(update={"final_url": run.pseudonymiser.pseudonymise(page.final_url)})
    number = len(session.sources) + 1
    reading = await read_page(run, question, page, number=number, url=url)
    session.sources.append(reading.source)
    session.pages[number] = reading.text
    session.read[url] = number
    session.read.setdefault(page.final_url, number)
    session.reader_failures += int(reading.reader_failed)
    return extracts_view(reading.source)


async def _execute(
    run: Run, session: Session, toolbox: Toolbox | None, call: ToolCall, question: str
) -> str:
    name, arguments = call["name"], dict(call.get("args") or {})
    if toolbox is None or name not in {tool.name for tool in toolbox.tools}:
        return f"Erreur : l'outil « {name} » n'est pas disponible pour cette requête."
    try:
        if name == SEARCH:
            return await _search(session, toolbox, arguments)
        if name == READ:
            return await _read(run, session, toolbox, arguments, question)
        return f"Erreur : l'outil « {name} » n'est pas géré par le planificateur."
    except ValidationError as exc:
        error = f"résultat inattendu ({short_error(exc)})"
    except ToolRefusedError as exc:
        error = "refusé par le moteur de politique : " + " ; ".join(exc.decision.reasons)
    except (ToolException, McpAdapterError) as exc:
        error = str(exc)
    return "Erreur de l'outil :\n" + mark_untrusted(error, source=f"{name} (erreur)")


def _task(run: Run, state: CerveauState) -> str:
    guarded, route = required(state.guarded, "garde"), required(state.route, "routage")
    return run.prompts.render(
        "planner_task",
        question=guarded.question,
        urls=", ".join(guarded.urls) or "aucune",
        complexite=route.complexity,
        importance=route.importance,
        tools=", ".join(route.tools) or "aucun (réponds sans recherche web)",
        max_tool_calls=str(run.config.budgets.per_request.max_tool_calls),
    )


async def plan_node(run: Run, state: CerveauState) -> dict[str, Any]:
    context = required(state.context, "contexte")
    guarded, route = required(state.guarded, "garde"), required(state.route, "routage")
    toolbox = run.toolbox if route.tools else None
    tools = [tool for tool in toolbox.tools if tool.name in route.tools] if toolbox else []
    messages: list[BaseMessage] = [
        SystemMessage(run.prompts.system(context)),
        HumanMessage(_task(run, state)),
    ]
    session = Session()
    json_repaired = format_repaired = False
    try:
        while session.turns < MAX_PLANNER_TURNS:
            session.turns += 1
            reply: AIMessage = await run.invoke(route.role, messages, tools=tools)
            messages.append(reply)
            if reply.tool_calls:
                for call in reply.tool_calls:
                    content = await _execute(run, session, toolbox, call, guarded.question)
                    messages.append(ToolMessage(content=content, tool_call_id=call["id"]))
                continue
            try:
                answer = parse_json(message_text(reply), DraftAnswer)
            except ValueError as exc:
                if json_repaired:
                    return {"draft": partial_draft(session, "format")}
                json_repaired = True
                messages.append(HumanMessage(REPAIR.format(error=short_error(exc))))
                continue
            issues = format_issues(answer, route.complexity)
            if issues and not format_repaired:
                format_repaired = True
                messages.append(HumanMessage(FORMAT_REPAIR.format(issues=" ; ".join(issues))))
                continue
            return {"draft": session.draft(answer, format_issues=tuple(issues))}
    except RequestBudgetExceeded as exc:
        return {"draft": partial_draft(session, exc.limit)}
    return {"draft": partial_draft(session, "tours")}
