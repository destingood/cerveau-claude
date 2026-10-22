"""Nodes 1 to 3: request context, input guard, routing (section 7.1).

The question is pseudonymised before any model sees it (ADR-007). The URLs Lucas gave are
pseudonymised one by one and remembered in the ``Run``, so that web_read can open the address
he wrote while the models only see its masked form. A failing classifier refuses (prudence); a
failing router falls back to the most careful route. An action class this phase grants to some
packs only (``CALCUL``, ADR-022) is decided once the domain is routed, before any tool opens.

A decision question of a pack that has a committee, or any question asked with ``--comite``, is
routed to the committee (D15). Its session budget replaces the request's before the pack's tools
open; while that budget or the committee's configuration holds a marker, the question is refused
rather than answered by the planner alone (R7). A question asked with ``--approfondi`` goes to the
first pack with a deep research, under that research's budget and on the same terms (ADR-045);
the router never chooses one (D14).
"""

from __future__ import annotations

import re
from datetime import datetime
from functools import partial
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.messages import HumanMessage, SystemMessage

from core.budget.gate import RequestBudget
from core.config.loader import BlockedFeatureError
from core.guardrails.input import InputRefusedError, check_question
from core.orchestrator.packs import DEFAULT_DOMAIN
from core.orchestrator.runtime import WEB_PLUGIN, Run
from core.orchestrator.state import (
    CerveauState,
    GuardedInput,
    InputVerdict,
    Mode,
    RequestContext,
    RoutePlan,
    RouteVerdict,
    required,
)
from core.orchestrator.structured import StructuredOutputError, ask_json
from core.policy.engine import ROUTED_ACTION_CLASSES, decide, kill_switch_engaged

TIMEZONE = "Europe/Paris"
KILL_MESSAGE = (
    "Le kill switch est engagé : CERVEAU est à l'arrêt et ne traite aucune requête (R4). "
    "Seul Lucas peut le désengager."
)
LIVE_MESSAGE = (
    "ALERTE : la configuration live est activée alors qu'aucun adaptateur live n'existe : "
    "CERVEAU ne traite aucune requête (R3). Seul Lucas peut la désactiver, à la main."
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
        live_enabled=run.config.live.enabled,
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
    routed_later = verdict.classe_action in ROUTED_ACTION_CLASSES  # decided by route_node
    if verdict.decision == "ok" and verdict.classe_action != "LECTURE" and not routed_later:
        context = required(state.context, "contexte")
        policy = decide(
            run.config.autonomy,
            request_id=run.request_id,
            domain=context.domain,
            action_class=verdict.classe_action,
            kill_switch=kill_switch_engaged(run.project_root),
            live_enabled=run.config.live.enabled,
        )
        if policy.effect != "executer":
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


def _routed_refusal(run: Run, guarded: GuardedInput, domain: str) -> GuardedInput | None:
    """The guard's verdict refused when the routed domain cannot carry out its action class."""
    if guarded.action_class == "LECTURE":
        return None
    policy = decide(
        run.config.autonomy,
        request_id=run.request_id,
        domain=domain,
        action_class=guarded.action_class,
        kill_switch=kill_switch_engaged(run.project_root),
        live_enabled=run.config.live.enabled,
    )
    if policy.effect == "executer":
        return None
    reason = f"action de classe {guarded.action_class} : " + " ; ".join(policy.reasons)
    return guarded.model_copy(update={"decision": "refus", "reason": reason})


def _convene(run: Run, domain: str, *, asked: bool) -> tuple[Mode, str | None, str | None]:
    """The mode, a note for the answer and the reason a committee asked for is refused.

    ``asked``: by the router or by ``--comite``. The session budget replaces the request's here,
    before any tool opens, so that the session's tool calls count against it (D18).
    """
    if not (asked or run.committee_forced):
        return "direct", None, None
    spec = run.committee_for(domain) if run.committee_for is not None else None
    if spec is None:
        if run.committee_forced:
            reason = f"Comité demandé, mais le pack « {domain} » n'a pas de Comité"
            return "direct", None, reason
        note = (
            f"Le routage demande le Comité, mais le pack « {domain} » n'en a pas : réponse directe"
        )
        return "direct", note, None
    clock = {"clock": run.budget_clock} if run.budget_clock is not None else {}
    try:
        budget = RequestBudget.for_committee(run.config, run.meter, feature=spec.feature, **clock)
    except BlockedFeatureError as exc:
        return "direct", None, "Comité bloqué (R7) : " + " ; ".join(exc.reasons)
    except ValueError as exc:
        return "direct", None, f"Comité bloqué (R7) : {exc}"
    run.budget = budget
    return "comite", None, None


def _research_domain(run: Run, routed: str) -> str:
    """``--approfondi``: the first pack whose agent is a deep research, else the routed one."""
    return next((pack_id for pack_id, pack in run.packs.items() if pack.approfondi), routed)


def _deepen(run: Run, domain: str) -> tuple[Mode, str | None]:
    """The mode and the reason a deep research asked for is refused (ADR-045, D14).

    Its budget replaces the request's here, before any tool opens, as a committee's does.
    """
    spec = run.research_for(domain) if run.research_for is not None else None
    if spec is None:
        return "direct", f"Recherche approfondie demandée, mais le pack « {domain} » n'en a pas"
    clock = {"clock": run.budget_clock} if run.budget_clock is not None else {}
    try:
        budget = RequestBudget.for_deep_research(
            run.config, run.meter, feature=spec.feature, **clock
        )
    except BlockedFeatureError as exc:
        return "direct", "Recherche approfondie bloquée (R7) : " + " ; ".join(exc.reasons)
    except ValueError as exc:
        return "direct", f"Recherche approfondie bloquée (R7) : {exc}"
    run.budget = budget
    return "approfondi", None


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
    domain = requested if requested in run.packs else DEFAULT_DOMAIN
    if run.research_forced:  # Lucas chose the deep research, hence its pack (D14)
        domain = requested = _research_domain(run, domain)
    needs_web = verdict.web or bool(guarded.urls)
    refused = _routed_refusal(run, guarded, domain)
    mode: Mode = "direct"
    note: str | None = None
    if refused is None:
        if run.research_forced:
            mode, blocked = _deepen(run, domain)
        else:
            mode, note, blocked = _convene(run, domain, asked=verdict.mode == "comite")
        if blocked is not None:
            refused = guarded.model_copy(update={"decision": "refus", "reason": blocked})
    complex_ = verdict.complexite == "complexe" or mode == "approfondi"
    role = "planner_complex" if complex_ else "planner"
    # The news analyst reads the web (D16), and so does a deep research (ADR-045).
    needs_web = needs_web or mode != "direct"
    # The web opens only when the question needs it; the pack's other plugins always do, unless
    # the policy refused the request.
    plugins = [name for name in run.packs[domain].plugins if needs_web or name != WEB_PLUGIN]
    if refused is not None:
        plugins = []
    tools: tuple[str, ...] = ()
    skipped: dict[str, str] = {}
    if plugins:
        toolbox = await run.open_tools(domain, plugins)
        tools = tuple(tool.name for tool in toolbox.tools)
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
        mode=mode,
        mode_note=note,
        experimental=run.packs[domain].experimental,
    )
    context = required(state.context, "contexte")
    level = "N0" if context.kill_switch else run.config.autonomy.domains[domain].level
    routed = context.model_copy(update={"domain": domain, "autonomy_level": level})
    if refused is not None:
        return {"route": plan, "context": routed, "guarded": refused}
    return {"route": plan, "context": routed}
