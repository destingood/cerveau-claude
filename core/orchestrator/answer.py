"""Node 6: the answer in format 7.3, and its Markdown rendering (section 7.3, annex D).

Every text the models wrote goes through ``strip_foreign_links``: a link or an image may only
point to a source that was read or to an address Lucas gave (R5, no exfiltration through a
URL). What was dropped, masked or refused on the way is listed under « Signalements ».

The pseudonyms are put back only after the graph. A link that holds one (``…?d=<EMAIL_1>``) would
then carry Lucas's data to a domain that a domain check allows: such a link survives only when it
is exactly an address Lucas gave or a source that was read.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

from core.guardrails.injection import injection_signals
from core.guardrails.pii import PSEUDONYM
from core.orchestrator.intake import KILL_MESSAGE
from core.orchestrator.planner import LIMIT_TEXT, MAX_PLANNER_TURNS
from core.orchestrator.runtime import Run
from core.orchestrator.state import (
    MARKER,
    Answer,
    CerveauState,
    Confiance,
    Draft,
    GuardedInput,
    RoutePlan,
    SourceRef,
    required,
)
from core.verification.domains import strip_foreign_links

MAX_POINTS = 20
MAX_TITLE_CHARS = 200
CONFIDENCE_LABEL = {"faible": "faible", "moyen": "moyen", "eleve": "élevé"}
CLARIFICATION = "Une précision est nécessaire avant d'analyser"
DEFAULT_QUESTION = "Peux-tu préciser ce que tu cherches exactement ?"
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


def signals(guarded: GuardedInput, route: RoutePlan, draft: Draft, links: _Links) -> list[str]:
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
    for name, reason in route.skipped.items():
        notes.append(f"Outil {name} indisponible pour cette requête : {reason}.")
    for source in draft.sources:
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


async def output_node(run: Run, state: CerveauState) -> dict[str, Any]:
    early = _early_answer(state)
    if early is not None:
        return {"answer": early}
    guarded = required(state.guarded, "garde")
    route, draft = required(state.route, "routage"), required(state.draft, "planificateur")
    report = required(state.verification, "vérification")
    allowed = [*guarded.urls, *(u for s in draft.sources for u in (s.url, s.final_url))]
    links = _Links(allowed)
    verified = report.answer
    sources = tuple(
        SourceRef(
            number=source.number,
            title=clean_title(source.title),
            url=source.final_url,
            published=source.published,
            retrieved_at=source.retrieved_at,
        )
        for source in draft.sources
    )
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
    confiance = answer.confiance
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
        }
    )


def _source_line(source: SourceRef) -> str:
    dates = [f"consulté le {source.retrieved_at}"]
    if source.published:
        dates.insert(0, f"publié le {source.published}, date non vérifiée")
    title = source.title or "Sans titre"
    return f"{source.number}. {title} — {source.url} ({' ; '.join(dates)})"


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
