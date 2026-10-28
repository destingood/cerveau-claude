"""Structured output of ``attack_lookup``, published as its MCP output schema.

Every text field holds content of the ATT&CK bundle: data for the reader, never instructions
(R5). Names and descriptions are those MITRE publishes, in English; nothing here is computed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.cyber.attack import Kind

MAX_RESULTS = 10

Status = Literal["en vigueur", "obsolète", "révoqué"]
Match = Literal["identifiant", "mots-clés"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Ref(_Out):
    id: str = Field(description="Identifiant ATT&CK")
    name: str


class AttackItem(_Out):
    id: str = Field(description="Identifiant ATT&CK (TA, T, M, DET, G, S ou C suivi de chiffres)")
    kind: Kind
    name: str
    status: Status = Field(description="révoqué : remplacé (revoked_by) ; obsolète : retiré")
    url: str | None = Field(description="Page de l'objet sur attack.mitre.org")
    description: str = Field(
        description="Description anglaise sur une ligne, citations retirées, tronquée"
    )
    description_truncated: bool
    aliases: list[str]
    platforms: list[str]
    tactics: list[Ref] = Field(description="Tactiques d'une technique ou sous-technique")
    parent: Ref | None = Field(description="Technique parente d'une sous-technique")
    subtechniques: list[Ref]
    mitigations: list[Ref] = Field(description="Mesures d'atténuation en vigueur de la technique")
    detection_strategies: list[Ref] = Field(description="Stratégies de détection en vigueur")
    techniques: list[Ref] = Field(
        description="Techniques atténuées (mesure), détectées (stratégie) ou employées (groupe, "
        "logiciel, campagne)"
    )
    lists_truncated: bool = Field(description="Une liste a été coupée à la limite du résultat")
    revoked_by: Ref | None = Field(description="Objet qui remplace un objet révoqué")
    modified: str | None = Field(description="Dernière modification publiée par MITRE")
    version: str | None = Field(description="Version de l'objet dans ATT&CK")


class AttackSource(_Out):
    name: Literal["MITRE ATT&CK Enterprise"]
    version: str
    commit: str = Field(description="Commit épinglé de mitre-attack/attack-stix-data")
    bundle_sha256: str
    built_at: str = Field(description="Construction de l'index par `cerveau cyber attack-fetch`")
    notice: str = Field(description="Mention de MITRE à reproduire avec toute copie")
    terms_url: str


class AttackLookup(_Out):
    query: str
    match: Match
    results: list[AttackItem] = Field(
        max_length=MAX_RESULTS,
        description="Identifiant : l'objet, puis son remplaçant s'il est révoqué ; mots-clés : "
        "rangés selon order",
    )
    total_matches: int = Field(ge=0, description="Objets trouvés avant la limite")
    more_available: bool
    order: str
    source: AttackSource
