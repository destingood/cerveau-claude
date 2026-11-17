"""Offline doubles for the entreprises tests: a fake API Recherche d'entreprises behind
``httpx.MockTransport`` reached through a fake DNS, a rate limiter that never sleeps, and replies
shaped like the OpenAPI of the API (read on 2026-10-29). Every name, person and figure is invented.
The replies hold ``dirigeants``, a birth date and a street: none of them may reach the output or
the cache (I4).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx

from core.net.throttle import SharedThrottle
from plugins.entreprises.client import HOST, RegistryClient
from plugins.legifrance.client import ResponseCache
from tests.net_doubles import PUBLIC_V4, FakeDns, chunks

FIXED_NOW = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)
STAMP = "2026-10-29T09:30:00+00:00"
SIREN = "356000000"  # a valid Luhn key; the company below is invented
PERSON_NAMES = ("Dupontel", "Josiane", "Martinot")
SECRET_FIELDS = ("dirigeants", "date_de_naissance", "adresse", "1965-04", "12 rue des Lilas")


def company(siren: str = SIREN, **extra: Any) -> dict[str, Any]:
    """One result, with every field the code must drop."""
    body: dict[str, Any] = {
        "siren": siren,
        "nom_complet": "Boulangerie Atelier (BOULANGERIE)",
        "nom_raison_sociale": "BOULANGERIE ATELIER",
        "sigle": "BOULANGERIE",
        "activite_principale": "47.91B",
        "categorie_entreprise": "PME",
        "annee_categorie_entreprise": "2023",
        "etat_administratif": "A",
        "date_creation": "2019-03-01",
        "date_fermeture": None,
        "date_mise_a_jour_insee": "2026-10-01T04:12:00",
        "date_mise_a_jour_rne": "2026-09-30T22:00:00",
        "nature_juridique": "5710",
        "tranche_effectif_salarie": "03",
        "annee_tranche_effectif_salarie": "2023",
        "statut_diffusion": "O",
        "siege": {
            "libelle_commune": "LYON 3EME",
            "code_postal": "69003",
            "departement": "69",
            "commune": "69383",
            "adresse": "12 rue des Lilas 69003 LYON 3EME",
            "latitude": "45.7",
        },
        "dirigeants": [
            {
                "nom": "Dupontel",
                "prenoms": "Josiane",
                "date_de_naissance": "1965-04",
                "qualite": "Président",
                "type_dirigeant": "personne physique",
            },
            {"siren": "552100554", "denomination": "Martinot Holding", "type_dirigeant": "pm"},
        ],
        "finances": {
            "2021": {"ca": 120000, "resultat_net": 8000},
            "2023": {"ca": 245678, "resultat_net": -1234},
            "2022": {"ca": 180000, "resultat_net": None},
        },
        "matching_etablissements": [{"adresse": "12 rue des Lilas", "siret": "35600000000048"}],
    }
    body.update(extra)
    return body


def reply(results: list[Any] | None = None, total: Any = 1) -> dict[str, Any]:
    return {
        "results": [company()] if results is None else results,
        "total_results": total,
        "page": 1,
        "per_page": 10,
        "total_pages": 1,
    }


def respond(
    body: Any = None,
    status: int = 200,
    content_type: str | None = "application/json",
    headers: dict[str, str] | None = None,
    size: int = 64 * 1024,
) -> httpx.Response:
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    sent = {"content-type": content_type} if content_type else {}
    sent.update(headers or {})
    return httpx.Response(status, headers=sent, content=chunks(data, size))


async def no_sleep(_: float) -> None:
    return None  # pragma: no cover - the tests set a zero interval


@dataclass
class FakeApi:
    """Answers each request with the next queued handler (the last one repeats). Handlers, not
    responses: a streamed body can be read once only."""

    replies: list[Callable[[httpx.Request], httpx.Response]] = field(
        default_factory=lambda: [lambda _: respond(reply())]
    )
    requests: list[httpx.Request] = field(default_factory=list)
    waits: list[float] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return answer(request)

    def params(self, index: int = -1) -> dict[str, list[str]]:
        return parse_qs(self.requests[index].url.query.decode("ascii"))

    async def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)

    def client(
        self,
        directory: Path,
        *,
        cached: bool = True,
        stopped: Callable[[], bool] = lambda: False,
        max_bytes: int = 2_000_000,
        now: Callable[[], datetime] = lambda: FIXED_NOW,
    ) -> RegistryClient:
        cache = ResponseCache(directory / "cache", timedelta(hours=24), now) if cached else None
        return RegistryClient(
            SharedThrottle(directory / "net", "entreprises", 0.0, sleep=no_sleep),
            cache=cache,
            stopped=stopped,
            transport=httpx.MockTransport(self),
            resolver=FakeDns({HOST: [PUBLIC_V4]}),
            max_bytes=max_bytes,
            now=now,
            sleep=self.sleep,
        )


def files_text(directory: Path) -> str:
    """Every byte written under ``directory``, decoded, to search for a person."""
    return "".join(
        path.read_bytes().decode("utf-8", "replace")
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    )
