"""Structured outputs of the tools, published as their MCP output schemas.

Every text field holds external content: data for the reader, never instructions (R5). Dates are
ISO 8601 at the precision the source gives (``2024``, ``2024-02`` or ``2024-02-05``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_RESULTS = 10
MAX_AUTHORS = 10

Source = Literal["arxiv", "crossref"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Update(_Out):
    type: str = Field(description="Nature de la mise à jour (correction, rétractation...)")
    doi: str = Field(description="DOI de la notice liée")


class ScholarRecord(_Out):
    source: Source
    identifier: str = Field(description="Identifiant arXiv (avec version) ou DOI")
    type: str = Field(description="Type de document annoncé par la source")
    preprint: bool = Field(description="Prépublication, sans relecture par les pairs annoncée")
    title: str
    authors: list[str] = Field(max_length=MAX_AUTHORS)
    more_authors: int = Field(ge=0, description="Auteurs non listés au-delà de 10")
    published: str | None = Field(description="Première date de publication ou de dépôt")
    updated: str | None = Field(description="Dernière version (arXiv)")
    venue: str | None = Field(description="Revue, actes ou référence de publication")
    doi: str | None
    url: str = Field(description="Page de la notice (arXiv ou doi.org)")
    abstract: str | None = Field(description="Résumé sans balises, tronqué")
    abstract_truncated: bool
    update_to: list[Update] = Field(description="Notices que celle-ci met à jour (Crossref)")
    updated_by: list[Update] = Field(
        description="Mises à jour publiées de cette notice, dont les rétractations (Crossref)"
    )
    retrieved_at: str


class ScholarResults(_Out):
    query: str
    source: Source
    since: str | None = Field(description="Date de début demandée, vérifiée sur chaque notice")
    records: list[ScholarRecord] = Field(max_length=MAX_RESULTS)
