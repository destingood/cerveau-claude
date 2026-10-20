"""Node 6: the answer in format 7.3, and its Markdown rendering (section 7.3, annex D).

Every text the models wrote goes through ``strip_foreign_links``: a link or an image may only
point to a source that was read or to an address Lucas gave (R5, no exfiltration through a
URL). What was dropped, masked or refused on the way is listed under « Signalements ».

The pseudonyms are put back only after the graph. A link that holds one (``…?d=<EMAIL_1>``) would
then carry Lucas's data to a domain that a domain check allows: such a link survives only when it
is exactly an address Lucas gave or a source that was read.

A committee session (D15) answers in the same format, with its decision, horizon, invalidation
conditions, unresolved disagreements and verdict on top: an « analyse » at N0, a « proposition
non exécutée » from N1, never an order (R16).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

from core.committee.schemas import HORIZONS
from core.guardrails.injection import injection_signals
from core.guardrails.pii import PSEUDONYM
from core.orchestrator.intake import KILL_MESSAGE
from core.orchestrator.planner import LIMIT_TEXT, MAX_PLANNER_TURNS
from core.orchestrator.runtime import Run
from core.orchestrator.state import (
    MARKER,
    Answer,
    CerveauState,
    CommitteeOutcome,
    CommitteeView,
    Confiance,
    Draft,
    GuardedInput,
    RequestContext,
    RoutePlan,
    Source,
    SourceRef,
    required,
)
from core.verification.domains import strip_foreign_links

MAX_POINTS = 20
MAX_TITLE_CHARS = 200
CONFIDENCE_LABEL = {"faible": "faible", "moyen": "moyen", "eleve": "élevé"}
CLARIFICATION = "Une précision est nécessaire avant d'analyser"
DEFAULT_QUESTION = "Peux-tu préciser ce que tu cherches exactement ?"
NOT_ADVICE = (
    "Aide à la décision personnelle, pas un conseil en investissement ni un ordre : rien n'est "
    "exécuté (R16)."
)
NO_DECISION = "Pas de décision"
CHOICE_LABEL = {"agir": "agir", "ne_pas_agir": "ne pas agir", "attendre": "attendre"}
COMMITTEE_CONFIDENCE = (
    "Catégorie choisie par le gestionnaire du Comité au vu des constats cités ; aucun chiffre "
    "n'est produit par un modèle (R1)."
)
_TITLE_DROP = re.compile(r"[\[\]<>`]")
_GLUED = re.compile("\ue000([A-Z][A-Z_]*_\\d+)\ue001")  # a pseudonym as one URL-safe word


def clean_title(title: str | None) -> str | None:
    """A page title fit for a Markdown list, or ``None`` when it reads like an instruction."""
    if not title or injection_signals(title):
        return None
    flat = " ".join(_TITLE_DROP.sub("", title).split())[:MAX_TITLE_CHARS]
    return flat or None


def _glue(text: str) -> str:
    """Each pseudonym, escaped or not, as one word: the link filter then sees the URL whole."""
    return PSEUDONYM.sub(lambda m: f"\ue000{m.group(1)}_{m.group(2)}\ue001", text)


class _Links:
    def __init__(self, allowed: Iterable[str]) -> None:
        self.allowed = tuple(dict.fromkeys(_glue(url) for url in allowed))
        self.removed = 0
        self.domains: list[str] = []

    def __call__(self, text: str) -> str:
        result = strip_foreign_links(_glue(text), self.allowed, exact_only=_GLUED)
        self.removed += result.removed
        self.domains.extend(d for d in result.removed_domains if d not in self.domains)
        return _GLUED.sub(r"<\1>", result.text)


def _limit_message(run: Run, limit: str) -> str:
    per_request = run.config.budgets.per_request
    maxima: dict[str, object] = {
        "tool_calls": per_request.max_tool_calls,
        "tokens": per_request.max_tokens,
        "seconds": per_request.max_seconds,
        "tours": MAX_PLANNER_TURNS,
    }
    value = f" ({maxima[limit]})" if limit in maxima else ""
    return (
        f"Réponse partielle : la requête a atteint {LIMIT_TEXT.get(limit, limit)}{value}. "
        "Seuls des extraits vérifiés sont repris, sans conclusion."
    )


def _input_notes(guarded: GuardedInput, route: RoutePlan) -> list[str]:
    notes: list[str] = []
    if guarded.pii_counts:
        detail = ", ".join(f"{label} {n}" for label, n in sorted(guarded.pii_counts.items()))
        notes.append(f"Données personnelles masquées avant tout envoi aux modèles : {detail}.")
    if guarded.removed_characters:
        notes.append(
            f"{guarded.removed_characters} caractère(s) invisible(s) retiré(s) de la question."
        )
    if route.requested_domain != route.domain:
        notes.append(
            f"Le pack « {route.requested_domain} » n'existe pas encore : réponse du pack "
            f"« {route.domain} », sans outil spécialisé."
        )
    if route.mode_note:
        notes.append(f"{route.mode_note}.")
    for name, reason in route.skipped.items():
        notes.append(f"Outil {name} indisponible pour cette requête : {reason}.")
    return notes


def _source_notes(sources: Iterable[Source]) -> list[str]:
    notes: list[str] = []
    for source in sources:
        if source.signals:
            notes.append(
                f"La source [{source.number}] contient des formulations d'instruction "
                f"({', '.join(source.signals)}) : traitées comme des données, aucune suivie."
            )
        if source.flagged:
            notes.append(
                f"Source [{source.number}] : {source.flagged} extrait(s) écarté(s) pour "
                "formulation d'instruction."
            )
        if source.rejected:
            notes.append(
                f"Source [{source.number}] : {source.rejected} extrait(s) écarté(s) (citation "
                "introuvable dans la page ou affirmation trop longue)."
            )
    return notes


def signals(guarded: GuardedInput, route: RoutePlan, draft: Draft, links: _Links) -> list[str]:
    notes = _input_notes(guarded, route) + _source_notes(draft.sources)
    if draft.refused_urls:
        notes.append(
            f"{draft.refused_urls} lecture(s) refusée(s) : adresse venue ni d'une recherche ni "
            "de la question (R5)."
        )
    if draft.masked_urls:
        notes.append(
            f"{draft.masked_urls} résultat(s) de recherche écarté(s) : adresse à formulation "
            "d'instruction (R5)."
        )
    if draft.refused_searches:
        notes.append(
            f"{draft.refused_searches} recherche(s) refusée(s) : la requête reprenait un chiffre "
            "ou un identifiant de tes données (R6)."
        )
    if draft.refused_outputs:
        notes.append(
            f"{draft.refused_outputs} résultat(s) d'outil écarté(s) : texte à formulation "
            "d'instruction, à vérifier dans tes fichiers importés (R5)."
        )
    if links.removed:
        notes.append(
            f"{links.removed} lien(s) ou image(s) vers un domaine hors des sources retiré(s)"
            + (f" ({', '.join(links.domains)})." if links.domains else ".")
        )
    return notes


def _early_answer(state: CerveauState) -> Answer | None:
    context = required(state.context, "contexte")
    if context.kill_switch:
        return Answer(statut="refus", message=KILL_MESSAGE)
    guarded = required(state.guarded, "garde")
    links = _Links(guarded.urls)
    if guarded.decision == "refus":
        return Answer(statut="refus", message=links(guarded.reason), links_removed=links.removed)
    if guarded.decision == "clarification":
        questions = tuple(links(q) for q in guarded.questions) or (DEFAULT_QUESTION,)
        return Answer(
            statut="clarification",
            message=f"{CLARIFICATION} : {links(guarded.reason)}",
            questions=questions,
            links_removed=links.removed,
        )
    return None


def _source_ref(source: Source) -> SourceRef:
    return SourceRef(
        number=source.number,
        title=clean_title(source.title),
        url=source.final_url,
        published=source.published,
        retrieved_at=source.retrieved_at,
    )


def _no_decision(outcome: CommitteeOutcome) -> str:
    reason = outcome.reason or "le Comité n'a pas conclu"
    if reason.startswith("budget:"):
        limit = reason.removeprefix("budget:")
        reason = f"la séance a atteint {LIMIT_TEXT.get(limit, limit)} de son budget"
    elif reason == "kill_switch":
        reason = "le kill switch a arrêté la séance"
    return f"{NO_DECISION} : {reason}."


def _arguments(decision: dict[str, Any], sort: str) -> str:
    return "\n".join(
        f"- {item['id']} : {item['raison']}"
        for item in decision["arguments"]
        if item["sort"] == sort
    )


def committee_answer(
    context: RequestContext, guarded: GuardedInput, route: RoutePlan, outcome: CommitteeOutcome
) -> Answer:
    """The committee's conclusion in format 7.3; « pas de décision » unless it concluded."""
    links = _Links([*guarded.urls, *(u for s in outcome.sources for u in (s.url, s.final_url))])
    decision = outcome.decision if outcome.concluded else None
    command = f"cerveau committee show {outcome.record_id}"
    view = CommitteeView(
        record_id=outcome.record_id,
        libelle="analyse" if context.autonomy_level == "N0" else "proposition non exécutée",
        verdict=outcome.verdict,
        raisons=tuple(links(reason) for reason in outcome.verdict_reasons),
    )
    if decision is None:
        answer = Answer(
            statut="partielle",
            synthese=f"{NO_DECISION} : le Comité n'a pas conclu ; rien n'est proposé.",
            message=links(_no_decision(outcome)),
        )
    else:
        view = view.model_copy(
            update={
                "decision": decision["decision"],
                "proposition": links(decision["proposition"]),
                "horizon": decision["horizon"],
                "horizon_bornes": HORIZONS,
                "invalidation": tuple(
                    links(f"{item['condition']} ({', '.join(item['constats'])})")
                    for item in decision["invalidation"]
                ),
                "desaccords": tuple(links(text) for text in decision["desaccords"]),
            }
        )
        retained, set_aside = _arguments(decision, "retenu"), _arguments(decision, "ecarte")
        answer = Answer(
            statut="complete",
            synthese=view.proposition,
            developpement=links(f"Arguments retenus par le gestionnaire :\n{retained}")
            if retained
            else "",
            contre_arguments=links(f"Arguments écartés :\n{set_aside}") if set_aside else "",
            confiance=Confiance(niveau=decision["confiance"], justification=COMMITTEE_CONFIDENCE),
        )
    notes = [*_input_notes(guarded, route), *_source_notes(outcome.sources), NOT_ADVICE]
    if links.removed:
        notes.append(
            f"{links.removed} lien(s) ou image(s) vers un domaine hors des sources retiré(s)."
        )
    return answer.model_copy(
        update={
            "sources": tuple(_source_ref(source) for source in outcome.sources),
            "prochaines_etapes": (f"Relire la séance complète : `{command}`.",),
            "signalements": tuple(notes),
            "comite": view,
            "links_removed": links.removed,
        }
    )


async def output_node(run: Run, state: CerveauState) -> dict[str, Any]:
    early = _early_answer(state)
    if early is not None:
        return {"answer": early}
    if state.committee is not None:
        context, guarded = required(state.context, "contexte"), required(state.guarded, "garde")
        route = required(state.route, "routage")
        return {"answer": committee_answer(context, guarded, route, state.committee)}
    guarded = required(state.guarded, "garde")
    route, draft = required(state.route, "routage"), required(state.draft, "planificateur")
    report = required(state.verification, "vérification")
    allowed = [*guarded.urls, *(u for s in draft.sources for u in (s.url, s.final_url))]
    links = _Links(allowed)
    verified = report.answer
    sources = tuple(_source_ref(source) for source in draft.sources)
    points = list(dict.fromkeys(links(issue.detail) for issue in report.issues))[:MAX_POINTS]
    answer = Answer(
        statut="partielle" if draft.partial else "complete",
        synthese=links(verified.synthese),
        developpement=links(verified.developpement),
        contre_arguments=links(verified.contre_arguments),
        confiance=Confiance(
            niveau=report.confidence, justification=links(verified.confiance.justification)
        ),
        sources=sources,
        points_a_verifier=tuple(points),
        prochaines_etapes=tuple(links(s) for s in verified.prochaines_etapes if s.strip()),
        message=_limit_message(run, draft.limit) if draft.partial and draft.limit else "",
    )
    notes = signals(guarded, route, draft, links)  # after the last link filter
    return {
        "answer": answer.model_copy(
            update={"signalements": tuple(notes), "links_removed": links.removed}
        )
    }


def map_texts(answer: Answer, fn: Callable[[str], str]) -> Answer:
    """``answer`` with ``fn`` applied to every text (re-identification after the graph)."""
    confiance, view = answer.confiance, answer.comite
    if view is not None:
        view = view.model_copy(
            update={
                "proposition": fn(view.proposition),
                "invalidation": tuple(fn(text) for text in view.invalidation),
                "desaccords": tuple(fn(text) for text in view.desaccords),
                "raisons": tuple(fn(text) for text in view.raisons),
            }
        )
    return answer.model_copy(
        update={
            "synthese": fn(answer.synthese),
            "developpement": fn(answer.developpement),
            "contre_arguments": fn(answer.contre_arguments),
            "confiance": confiance
            and Confiance(niveau=confiance.niveau, justification=fn(confiance.justification)),
            "sources": tuple(
                s.model_copy(update={"title": s.title and fn(s.title), "url": fn(s.url)})
                for s in answer.sources
            ),
            "points_a_verifier": tuple(fn(p) for p in answer.points_a_verifier),
            "prochaines_etapes": tuple(fn(s) for s in answer.prochaines_etapes),
            "signalements": tuple(fn(s) for s in answer.signalements),
            "questions": tuple(fn(q) for q in answer.questions),
            "message": fn(answer.message),
            "comite": view,
        }
    )


def _source_line(source: SourceRef) -> str:
    dates = [f"consulté le {source.retrieved_at}"]
    if source.published:
        dates.insert(0, f"publié le {source.published}, date non vérifiée")
    title = source.title or "Sans titre"
    return f"{source.number}. {title} — {source.url} ({' ; '.join(dates)})"


def _committee_lines(view: CommitteeView) -> list[str]:
    parts = [f"## Décision du Comité ({view.libelle})", ""]
    choice = CHOICE_LABEL.get(view.decision or "", NO_DECISION.lower())
    parts.append(f"- Décision proposée : {choice}")
    if view.horizon:
        parts.append(f"- Horizon : {view.horizon} ({view.horizon_bornes})")
    if view.invalidation:
        parts.append("- Conditions d'invalidation :")
        parts += [f"  - {condition}" for condition in view.invalidation]
    if view.decision is not None:
        parts.append("- Désaccords non résolus :" + ("" if view.desaccords else " aucun"))
        parts += [f"  - {text}" for text in view.desaccords]
    parts.append(f"- Verdict des contrôles : {view.verdict or 'aucun'}")
    parts += [f"  - {reason}" for reason in view.raisons]
    parts += [f"- Séance : {view.record_id}", ""]
    return parts


def render_markdown(answer: Answer) -> str:
    if answer.statut == "refus":
        return f"**Refus.** {answer.message}\n"
    if answer.statut == "clarification":
        numbered = [f"{n}. {q}" for n, q in enumerate(answer.questions, start=1)]
        return "\n".join([answer.message, "", *numbered]) + "\n"
    parts = ["## La Synthèse (Le « Quoi »)", ""]
    if answer.message:
        parts += [f"> {answer.message}", ""]
    parts += [answer.synthese.strip(), ""]
    if answer.comite is not None:
        parts += _committee_lines(answer.comite)
    parts += ["## Le Développement (Le « Pourquoi » et le « Comment »)", ""]
    parts += [answer.developpement.strip() or "Rien à ajouter à la synthèse.", ""]
    if answer.contre_arguments.strip():
        parts += ["### Meilleur argument contraire", "", answer.contre_arguments.strip(), ""]
    parts += ["## Confiance et sources", ""]
    if answer.confiance is not None:
        label = CONFIDENCE_LABEL[answer.confiance.niveau]
        parts += [f"**Confiance : {label}.** {answer.confiance.justification.strip()}", ""]
    parts += ["**Sources**", ""]
    parts += [_source_line(s) for s in answer.sources] or ["Aucune source web."]
    if answer.points_a_verifier:
        parts += ["", f"**Points {MARKER}**", ""]
        parts += [f"- {point}" for point in answer.points_a_verifier]
    if answer.signalements:
        parts += ["", "**Signalements**", ""]
        parts += [f"- {note}" for note in answer.signalements]
    parts += ["", "## Optimisation & Prochaines Étapes", ""]
    steps = [f"{n}. {step}" for n, step in enumerate(answer.prochaines_etapes, start=1)]
    parts += steps or ["Aucune étape proposée."]
    return "\n".join(parts).rstrip() + "\n"


def render_json(answer: Answer) -> str:
    return answer.model_dump_json(indent=2) + "\n"
