"""Fixtures of the Business pack's evals (ADR-063): the fake API Recherche d'entreprises and the
fake INSEE Melodi API a case describes, served to the real entreprises and insee_stats servers.

Every request goes through ``httpx.MockTransport`` after a fake DNS that names a public address,
under a rate limit that never waits and without a cache: no request leaves the machine. Each
company of the fake registry carries an invented director, birth date and street, as the real API
does: the plugin must drop them, and none may reach an answer or a log (I4).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx

from core.evals.cases import BusinessFixture, CompanyFixture, StatsFixture
from core.net.throttle import SharedThrottle
from plugins.entreprises.client import HOST as REGISTRY_HOST
from plugins.entreprises.client import SEARCH_PATH, RegistryClient
from plugins.insee_stats.client import HOST as MELODI_HOST
from plugins.insee_stats.client import StatsClient

PUBLIC_V4 = "93.184.215.14"  # the address of both API names, so the network guard lets it be
HOSTS = frozenset({REGISTRY_HOST, MELODI_HOST})
# What the fake registry adds to every company: canaries, never in an answer or a log (I4).
DIRECTOR_NAME = "Canariot"
DIRECTOR_FIRST_NAMES = "Gaëlle Ondine"
DIRECTOR_BIRTH = "1971-02"
STREET = "7 impasse des Canaris"
CANARIES = (DIRECTOR_NAME, DIRECTOR_FIRST_NAMES, DIRECTOR_BIRTH, STREET)
PER_PAGE = 10
_DATA = "/melodi/data/"
_CATALOG = "/melodi/catalog/"


async def _no_sleep(_: float) -> None:
    await asyncio.sleep(0)


async def _chunks(body: bytes, size: int = 64 * 1024) -> AsyncIterator[bytes]:
    for start in range(0, len(body), size):
        yield body[start : start + size]


def _respond(data: Any, status: int = 200) -> httpx.Response:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    headers = {"content-type": "application/json"}
    return httpx.Response(status, headers=headers, content=_chunks(body))


async def _resolve(host: str, port: int) -> Sequence[str]:
    if host not in HOSTS:
        raise OSError("name not found")
    return [PUBLIC_V4]


def company_reply(company: CompanyFixture) -> dict[str, Any]:
    """One result as the API gives it, with the person and the street the plugin must drop."""
    finances = {
        year: {"ca": accounts.ca, "resultat_net": accounts.resultat_net}
        for year, accounts in company.finances.items()
    }
    return {
        "siren": company.siren,
        "nom_complet": company.nom,
        "nom_raison_sociale": company.nom.upper(),
        "activite_principale": company.naf,
        "categorie_entreprise": company.categorie,
        "etat_administratif": company.etat,
        "date_creation": company.creation.isoformat(),
        "date_fermeture": company.fermeture.isoformat() if company.fermeture else None,
        "date_mise_a_jour_insee": f"{company.mise_a_jour.isoformat()}T04:00:00",
        "tranche_effectif_salarie": company.effectif,
        "siege": {
            "libelle_commune": company.commune,
            "code_postal": company.code_postal,
            "departement": company.departement,
            "adresse": f"{STREET} {company.code_postal} {company.commune}",
        },
        "dirigeants": [
            {
                "nom": DIRECTOR_NAME,
                "prenoms": DIRECTOR_FIRST_NAMES,
                "date_de_naissance": DIRECTOR_BIRTH,
                "qualite": "Gérant",
                "type_dirigeant": "personne physique",
            }
        ],
        "finances": finances,
        "matching_etablissements": [{"adresse": STREET}],
    }


def _matches(company: CompanyFixture, params: dict[str, str]) -> bool:
    asked = params.get("q", "")
    if asked.isdigit():
        found = company.siren == asked
    else:
        name = company.nom.casefold()
        found = all(word in name for word in asked.casefold().split())
    wanted = {
        "code_postal": company.code_postal,
        "departement": company.departement,
        "activite_principale": company.naf,
        "etat_administratif": company.etat,
    }
    return found and all(params.get(key, value) == value for key, value in wanted.items())


def _observation(dimensions: dict[str, str], value: float) -> dict[str, Any]:
    return {"dimensions": dimensions, "measures": {"OBS_VALUE_NIVEAU": {"value": value}}}


class FixtureApis:
    """Both APIs of one case, routed on the ``Host`` header (the URL carries the pinned address)
    and on the path."""

    def __init__(self, fixture: BusinessFixture) -> None:
        self.fixture = fixture
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.headers.get("host", "")
        if host == REGISTRY_HOST and request.url.path == SEARCH_PATH:
            if "entreprises" in self.fixture.down:
                return _respond({"erreur": "service indisponible"}, 503)
            return self._search(request)
        if host == MELODI_HOST and request.url.path.startswith((_DATA, _CATALOG)):
            if "insee_melodi" in self.fixture.down:
                return _respond({"error": "service unavailable"}, 503)
            return self._melodi(request.url.path)
        return _respond({"error": "not found"}, 404)

    def _search(self, request: httpx.Request) -> httpx.Response:
        query = parse_qs(request.url.query.decode("ascii"))
        params = {key: values[0] for key, values in query.items()}
        found = [c for c in self.fixture.companies if _matches(c, params)]
        return _respond(
            {
                "results": [company_reply(c) for c in found[:PER_PAGE]],
                "total_results": len(found),
                "page": 1,
                "per_page": PER_PAGE,
                "total_pages": 1,
            }
        )

    def _melodi(self, path: str) -> httpx.Response:
        catalog = path.startswith(_CATALOG)
        dataset_id = path.removeprefix(_CATALOG if catalog else _DATA)
        dataset: StatsFixture | None = self.fixture.datasets.get(dataset_id)
        if dataset is None:
            return _respond({"error": "not found"}, 404)
        if catalog:
            modified = f"{dataset.updated.isoformat()}T12:00:00"
            return _respond({"identifier": dataset_id, "modified": modified})
        observations = [_observation(o.dimensions, o.value) for o in dataset.observations]
        return _respond(
            {"observations": observations, "identifier": dataset_id, "paging": {"first": True}}
        )


def business_clients(
    fixture: BusinessFixture,
    folder: Path,
    stopped: Callable[[], bool],
    now: Callable[[], datetime],
) -> tuple[RegistryClient, StatsClient]:
    """The real clients of a case on its fake APIs, without a cache."""
    apis = httpx.MockTransport(FixtureApis(fixture))
    registry = RegistryClient(
        SharedThrottle(folder / "net", "entreprises", 0.0, sleep=_no_sleep),
        stopped=stopped,
        transport=apis,
        resolver=_resolve,
        now=now,
        sleep=_no_sleep,
    )
    stats = StatsClient(
        SharedThrottle(folder / "net", "insee_melodi", 0.0, sleep=_no_sleep),
        stopped=stopped,
        transport=apis,
        resolver=_resolve,
        now=now,
        sleep=_no_sleep,
    )
    return registry, stats
