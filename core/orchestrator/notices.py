"""Notices the sources of an answer require, appended under it by the code (G9, R14).

No model writes them and none can drop them: they follow from the tool results the planner kept
and from the pages it read. A tool result refused as an instruction (R5) brings none, since
nothing of it reaches the answer. Texts and terms read on 2026-10-22 and 2026-10-27
(``config/data_sources.yaml``, plan of P4); the exact copyright designation of the CVE program
is not published on its terms page: the notice points to its licence (A_VERIFIER, backlog).
"""

from __future__ import annotations

from collections.abc import Iterable
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
}
OWASP_HOST = "owasp.org"


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
    return ()


def page_sources(urls: Iterable[str]) -> tuple[str, ...]:
    """The sources of the pages read, by the host they were read on (after redirects)."""
    hosts = {(urlsplit(url).hostname or "") for url in urls}
    owasp = any(host == OWASP_HOST or host.endswith(f".{OWASP_HOST}") for host in hosts)
    return ("owasp",) if owasp else ()


def notices(keys: Iterable[str]) -> tuple[str, ...]:
    """The notices of ``keys``, each once, in the order of ``NOTICES``; unknown keys add none."""
    wanted = set(keys)
    return tuple(text for key, text in NOTICES.items() if key in wanted)
