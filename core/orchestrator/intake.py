"""Nodes 1 to 3: request context, input guard, routing (section 7.1).

The question is pseudonymised before any model sees it (ADR-007). The URLs Lucas gave are
pseudonymised one by one and remembered in the ``Run``, so that web_read can open the address
he wrote while the models only see its masked form. A failing classifier refuses (prudence); a
failing router falls back to the most careful route.
"""

from __future__ import annotations

import re
from datetime import datetime
from functools import partial
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.messages import HumanMessage, SystemMessage

from core.guardrails.input import InputRefusedError, check_question
from core.orchestrator.runtime import WEB_PLUGIN, Run
from core.orchestrator.state import (
    CerveauState,
    GuardedInput,
    InputVerdict,
    RequestContext,
    RoutePlan,
    RouteVerdict,
    required,
)
from core.orchestrator.structured import StructuredOutputError, ask_json
from core.policy.engine import decide, kill_switch_engaged

DEFAULT_DOMAIN = "generaliste"
PACKS = frozenset({DEFAULT_DOMAIN})  # domain packs of phase 1
TIMEZONE = "Europe/Paris"
KILL_MESSAGE = (
    "Le kill switch est engagé : CERVEAU est à l'arrêt et ne traite aucune requête (R4). "
    "Seul Lucas peut le désengager."
)


def paris_time(now: datetime) -> str:
    try:
        local = now.astimezone(ZoneInfo(TIMEZONE))
    except ZoneInfoNotFoundError:  # no tz database: the machine's local time, offset shown
        local = now.astimezone()
    return local.isoformat(timespec="minutes")


async def context_node(run: Run, state: CerveauState) -> dict[str, Any]:
    kill = kill_switch_engaged(run.project_root)
    level = run.config.autonomy.domains[DEFAULT_DOMAIN].level
    context = RequestContext(
        request_id=run.request_id,
        now=paris_time(run.now),
        domain=DEFAULT_DOMAIN,
        autonomy_level="N0" if kill else level,
        kill_switch=kill,
    )
    return {"context": context}


def pseudonymise_question(run: Run, text: str, urls: tuple[str, ...]) -> tuple[str, list[str]]:
    """The question with each part masked; each URL is masked on its own and remembered."""
    if not urls:
        return run.pseudonymiser.pseudonymise(text), []
    pattern = re.compile("|".join(re.escape(url) for url in sorted(urls, key=len, reverse=True)))
    parts: list[str] = []
    shown: list[str] = []
    position = 0
    for match in pattern.finditer(text):
        before = text[position : match.start()]
        parts.append(run.pseudonymiser.pseudonymise(before) if before else "")
        masked = run.pseudonymiser.pseudonymise(match.group(0))
        run.url_map[masked] = match.group(0)
        if masked not in shown:
            shown.append(masked)
        parts.append(masked)
        position = match.end()
    rest = text[position:]
    parts.append(run.pseudonymiser.pseudonymise(rest) if rest else "")
    return "".join(parts), shown


def _refusal(question: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {"guarded": GuardedInput(question=question, decision="refus", reason=reason, **extra)}


async def guard_node(run: Run, state: CerveauState) -> dict[str, Any]:
    try:
        checked = check_question(run.raw_question)
    except InputRefusedError as exc:
        return _refusal("", f"question refusée : {exc}")
    question, urls = pseudonymise_question(run, checked.text, checked.urls)
    counts = dict(run.pseudonymiser.counts())
    common: dict[str, Any] = {
        "urls": tuple(urls),
        "pii_counts": counts,
        "removed_characters": checked.removed_characters,
    }
    messages = [
        SystemMessage(run.prompts.render("input_check")),
        HumanMessage(f"Question à classer :\n{question}"),
    ]
    try:
        verdict = await ask_json(
            partial(run.invoke, "classifier"), messages, InputVerdict, what="contrôle d'entrée"
        )
    except StructuredOutputError:
        return _refusal(
            question,
            "contrôle d'entrée indisponible (réponse illisible du classifieur) : "
            "la question est refusée par prudence",
            **common,
        )
    reason = verdict.raison.strip() or "aucune raison donnée"
    if verdict.decision == "ok" and verdict.classe_action != "LECTURE":
        context = required(state.context, "contexte")
        policy = decide(
            run.config.autonomy,
            request_id=run.request_id,
            domain=context.domain,
            action_class=verdict.classe_action,
            kill_switch=kill_switch_engaged(run.project_root),
        )
        if not policy.allowed:
            return _refusal(
                question,
                f"action de classe {verdict.classe_action} : " + " ; ".join(policy.reasons),
                action_class=verdict.classe_action,
                **common,
            )
    guarded = GuardedInput(
        question=question,
        decision=verdict.decision,
        action_class=verdict.classe_action,
        reason=reason,
        questions=tuple(q.strip() for q in verdict.questions if q.strip()),
        **common,
    )
    return {"guarded": guarded}


def _prudent_route(reason: str) -> RouteVerdict:
    return RouteVerdict(complexite="complexe", importance="elevee", web=True, raison=reason)


async def route_node(run: Run, state: CerveauState) -> dict[str, Any]:
    guarded = required(state.guarded, "garde")
    messages = [
        SystemMessage(run.prompts.render("route")),
        HumanMessage(f"Question à router :\n{guarded.question}"),
    ]
    try:
        verdict = await ask_json(
            partial(run.invoke, "classifier"), messages, RouteVerdict, what="routage"
        )
    except StructuredOutputError:
        verdict = _prudent_route("routage indisponible : route la plus prudente par défaut")
    requested = verdict.domaine.strip().lower() or DEFAULT_DOMAIN
    domain = requested if requested in PACKS else DEFAULT_DOMAIN
    role = "planner_complex" if verdict.complexite == "complexe" else "planner"
    needs_web = verdict.web or bool(guarded.urls)
    tools: tuple[str, ...] = ()
    skipped: dict[str, str] = {}
    if needs_web:
        toolbox = await run.open_tools(domain)
        if toolbox is None:
            skipped = {WEB_PLUGIN: run.toolbox_error or "indisponible"}
        else:
            limit = run.config.models.routing.max_tools_to_planner
            tools = tuple(tool.name for tool in toolbox.tools[:limit])
            skipped = dict(toolbox.skipped)
    plan = RoutePlan(
        domain=domain,
        requested_domain=requested,
        complexity=verdict.complexite,
        importance=verdict.importance,
        needs_web=needs_web,
        reason=verdict.raison.strip() or "aucune raison donnée",
        role=role,
        tier=run.router.tier_for(role),
        tools=tools,
        skipped=skipped,
    )
    return {"route": plan}
