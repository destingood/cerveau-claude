"""Notices the sources of an answer require, appended under it by the code (G9, R14).

No model writes them and none can drop them: they follow from the tool results the planner kept
and from the pages it read. A tool result refused as an instruction (R5) brings none, since
nothing of it reaches the answer. Texts and terms read on 2026-10-22 and 2026-10-27
(``config/data_sources.yaml``, plan of P4); the exact copyright designation of the CVE program
is not published on its terms page: the notice points to its licence (A_VERIFIER, backlog).

The legal pack (H7, ADR-059) adds dated notices: each Légifrance article read brings its version
dates and reading day, taken from the tool output and checked by strict patterns; a
service-public page brings the update date found on it, if any. Any legal source, or a question
routed to ``juridique_fr``, adds the R16 warning.

The business pack (I5, I8) does the same: a company search is dated by its reading day, a
statistic of INSEE by its dataset, update date and reading day; a question routed to
``business`` adds its R16 warning, and the draft marker when the question asks for a text to
send or the answer holds one (D22): nothing is ever sent, the code says so.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from typing import Protocol
from urllib.parse import urlsplit

from core.cyber.attack import NOTICE as ATTACK_NOTICE
from core.cyber.attack import TERMS_URL as ATTACK_TERMS_URL

# In the order they are shown; the keys of config/data_sources.yaml where one exists.
NOTICES: dict[str, str] = {
    "nvd": "This product uses the NVD API but is not endorsed or certified by the NVD.",
    "cve": (
        "Descriptions des CVE : programme CVE™ de The MITRE Corporation, sous sa licence "
        "(https://www.cve.org/Legal/TermsOfUse)."
    ),
    "cisa_kev": (
        "Catalogue Known Exploited Vulnerabilities de la CISA, sous licence CC0 1.0 ; cet usage "
        "n'implique aucun aval de la CISA ni du DHS."
    ),
    "epss": "Scores EPSS : FIRST, EPSS Special Interest Group (https://www.first.org/epss/).",
    "attack": (
        f"{ATTACK_NOTICE} ATT&CK® est une marque déposée de The MITRE Corporation ; conditions : "
        f"{ATTACK_TERMS_URL}"
    ),
    "owasp": (
        "Pages de l'OWASP sous licence CC BY-SA 4.0, sauf mention contraire "
        "(https://creativecommons.org/licenses/by-sa/4.0/)."
    ),
    "legifrance": (
        "Source : Légifrance (DILA), Licence Ouverte 2.0 ; seules les publications du Journal "
        "officiel font foi."
    ),
    "service_public": (
        "Source : Service Public / DILA (service-public.gouv.fr), licence etalab-2.0 ; date de "
        "mise à jour : voir la fiche."
    ),
    "juridique": (
        "Information générale sur le droit français, pour l'aide à la décision personnelle : ce "
        "n'est pas un conseil juridique. Pour une situation précise, consulter un avocat, un "
        "notaire ou l'administration concernée (R16)."
    ),
    "entreprises": "Source : API Recherche d'entreprises (DINUM, données INSEE et INPI).",
    "insee": "Source : Insee, API Melodi, Licence Ouverte 2.0.",
    "business": (
        "Aide à la décision personnelle : ni conseil en gestion, ni conseil juridique, fiscal ou "
        "comptable. Les chiffres viennent des outils cités et des hypothèses fournies (R1, R16)."
    ),
    "brouillon": (
        "Brouillon — non envoyé : CERVEAU n'a aucun outil d'envoi ; relire avant tout usage (D22)."
    ),
}
OWASP_HOST = "owasp.org"
LEGIFRANCE_HOST = "legifrance.gouv.fr"
SERVICE_PUBLIC_HOST = "service-public.gouv.fr"
LEGAL_DOMAIN = "juridique_fr"
MAX_ARTICLES = 10  # dated Légifrance notices shown; the planner's tool budget is lower
ARTICLE_NOTICE = (
    "Source : Légifrance (DILA), Licence Ouverte 2.0 ; article {id}, version applicable du "
    "{start} {end}, lue le {read} ; seules les publications du Journal officiel font foi."
)
SERVICE_PUBLIC_DATED = (
    "Source : Service Public / DILA (service-public.gouv.fr), licence etalab-2.0, mise à jour "
    "du {days} (date lue sur la fiche)."
)
_DAY = r"\d{4}-\d{2}-\d{2}"
COMPANY_NOTICE = (
    "Source : API Recherche d'entreprises (DINUM, données INSEE et INPI), lue le {days}."
)
STATS_NOTICE = (
    "Source : Insee, API Melodi, Licence Ouverte 2.0 ; jeu {id}, mis à jour le {updated}, lu le "
    "{read}."
)
BUSINESS_DOMAIN = "business"
MAX_SERIES = 10  # dated INSEE notices shown
_ARTICLE_KEY = re.compile(rf"legifrance:(LEGIARTI\d{{12}}):({_DAY}):({_DAY}|-):({_DAY})", re.ASCII)
_SERVICE_PUBLIC_KEY = re.compile(rf"service_public:({_DAY})", re.ASCII)
_COMPANY_KEY = re.compile(rf"entreprises:({_DAY})", re.ASCII)
_STATS_KEY = re.compile(rf"insee:(DS_[A-Z0-9_]{{1,60}}):({_DAY}|-):({_DAY})", re.ASCII)
# A question asking for a text meant for someone else (D22): checked on the pseudonymised text.
_DRAFT_ASK = re.compile(
    r"\b(r[ée]dige\w*|[ée]cri[st]\w*|courriel|e-?mail|mail|newsletter|fiche produit|"
    r"publication|post|annonce|message|relance|devis|r[ée]ponse [àa] (un|une|mon|ma|ce|cette) "
    r"client\w*|pitch|slogan)\b",
    re.IGNORECASE,
)
_LEADING_DAY = re.compile(rf"({_DAY})", re.ASCII)


class Page(Protocol):
    @property
    def final_url(self) -> str: ...

    @property
    def published(self) -> str | None: ...


def _day(raw: object) -> str | None:
    """The calendar day ``raw`` starts with, if it is a real one."""
    found = _LEADING_DAY.match(raw) if isinstance(raw, str) else None
    if found is None:
        return None
    try:
        return date.fromisoformat(found.group(1)).isoformat()
    except ValueError:
        return None


def _on(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def _article_key(result: dict[str, object]) -> str | None:
    end = "-" if result.get("end") is None else _day(result.get("end"))
    parts = (result.get("id"), _day(result.get("start")), end, _day(result.get("retrieved_at")))
    key = "legifrance:" + ":".join(str(part) for part in parts)
    return key if None not in parts and _ARTICLE_KEY.fullmatch(key) else None


def _stats_key(result: dict[str, object]) -> str | None:
    updated = "-" if result.get("mise_a_jour") is None else _day(result.get("mise_a_jour"))
    parts = (result.get("jeu"), updated, _day(result.get("lu_le")))
    key = "insee:" + ":".join(str(part) for part in parts)
    return key if None not in parts and _STATS_KEY.fullmatch(key) else None


def tool_sources(name: str, result: object) -> tuple[str, ...]:
    """The sources whose data a kept tool result holds, read from its structured output."""
    if not isinstance(result, dict):
        return ()
    if name == "attack_lookup":
        return ("attack",)
    if name == "cve_watch":
        return {"kev": ("cisa_kev",), "nvd": ("nvd", "cve")}.get(str(result.get("source")), ())
    if name == "cve_lookup":  # the NVD always; the KEV and EPSS when they could be read
        read = {
            str(item.get("source"))
            for item in result.get("sources") or ()
            if isinstance(item, dict) and item.get("error") is None
        }
        return ("nvd", "cve", *(key for key in ("cisa_kev", "epss") if key in read))
    if name == "legi_search":
        return ("legifrance", "juridique")
    if name == "legi_article":  # dated by the version read; undated if its fields are odd
        return (_article_key(result) or "legifrance", "juridique")
    if name == "company_search":  # dated by the reading day; undated if it is odd
        day = _day(result.get("lu_le"))
        return ("entreprises", *([f"entreprises:{day}"] if day else []))
    if name == "stats_series":
        return (_stats_key(result) or "insee",)
    return ()


def page_sources(pages: Iterable[Page]) -> tuple[str, ...]:
    """The sources of the pages read, by the host they were read on (after redirects)."""
    keys: list[str] = []
    for page in pages:
        host = urlsplit(page.final_url).hostname or ""
        if _on(host, OWASP_HOST):
            keys.append("owasp")
        elif _on(host, LEGIFRANCE_HOST):
            keys += ["legifrance", "juridique"]
        elif _on(host, SERVICE_PUBLIC_HOST):
            day = _day(page.published)
            keys += ["service_public", "juridique", *([f"service_public:{day}"] if day else [])]
    return tuple(dict.fromkeys(keys))


def domain_sources(domain: str) -> tuple[str, ...]:
    """A question routed to the legal or business pack always carries its R16 warning."""
    return {LEGAL_DOMAIN: ("juridique",), BUSINESS_DOMAIN: ("business",)}.get(domain, ())


def draft_sources(domain: str, question: str, texts: Iterable[str]) -> tuple[str, ...]:
    """The draft marker of a business answer (D22, I5): the question asks for a text to send, or
    the answer calls itself a draft. Marking too often is harmless; missing one is not."""
    if domain != BUSINESS_DOMAIN:
        return ()
    asked = _DRAFT_ASK.search(question) is not None
    return ("brouillon",) if asked or any("brouillon" in t.lower() for t in texts) else ()


def _articles(wanted: Iterable[str]) -> list[str]:
    texts: list[str] = []
    for key in wanted:
        found = _ARTICLE_KEY.fullmatch(key)
        if found is not None:
            identifier, start, end, read = found.groups()
            until = "sans date de fin" if end == "-" else f"au {end}"
            texts.append(ARTICLE_NOTICE.format(id=identifier, start=start, end=until, read=read))
    return texts[:MAX_ARTICLES]


def _series(wanted: Iterable[str]) -> list[str]:
    texts: list[str] = []
    for key in wanted:
        found = _STATS_KEY.fullmatch(key)
        if found is not None:
            identifier, updated, read = found.groups()
            shown = "(date non publiée)" if updated == "-" else updated
            texts.append(STATS_NOTICE.format(id=identifier, updated=shown, read=read))
    return texts[:MAX_SERIES]


def notices(keys: Iterable[str]) -> tuple[str, ...]:
    """The notices of ``keys``, each once, in the order of ``NOTICES``; unknown keys add none.

    Dated Légifrance and INSEE notices replace the undated one; the update dates of
    service-public pages, and the reading days of company searches, are gathered in one notice.
    """
    wanted = list(dict.fromkeys(keys))
    texts: list[str] = []
    for key, text in NOTICES.items():
        if key == "legifrance":
            texts += _articles(wanted) or ([text] if key in wanted else [])
        elif key == "service_public":
            days = sorted({m.group(1) for k in wanted if (m := _SERVICE_PUBLIC_KEY.fullmatch(k))})
            if days:
                texts.append(SERVICE_PUBLIC_DATED.format(days=", du ".join(days)))
            elif key in wanted:
                texts.append(text)
        elif key == "entreprises":
            days = sorted({m.group(1) for k in wanted if (m := _COMPANY_KEY.fullmatch(k))})
            if days:
                texts.append(COMPANY_NOTICE.format(days=", le ".join(days)))
            elif key in wanted:
                texts.append(text)
        elif key == "insee":
            texts += _series(wanted) or ([text] if key in wanted else [])
        elif key in wanted:
            texts.append(text)
    return tuple(texts)
