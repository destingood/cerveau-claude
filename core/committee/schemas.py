"""What each committee role answers, as JSON validated by Pydantic (plan of phase 3, §10).

Field names are in French, like the role cards and the session record. A model never chooses an
identifier: the code numbers the findings (``C1``, ``C2``…) in the order of the analysts' cards,
and the arguments by side and round (``D1.1`` for the defender, ``X1.1`` for the challenger).
Confidence and horizon are categories, not figures produced by a model (R1).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from core.orchestrator.state import Confidence, _Llm

MemberKind = Literal["analyste", "defenseur", "contradicteur", "gestionnaire", "controleur"]
Weight = Literal["fort", "moyen", "faible"]
Horizon = Literal["court", "moyen", "long"]
Choice = Literal["agir", "ne_pas_agir", "attendre"]
Verdict = Literal["OK", "BLOQUER"]

ConstatId = Annotated[str, Field(pattern=r"^C[1-9][0-9]{0,2}$")]
ArgumentId = Annotated[str, Field(pattern=r"^[DX][1-9][0-9]?\.[1-9][0-9]?$")]
Line = Annotated[str, Field(min_length=1, max_length=300)]

HORIZONS = (
    "court : jusqu'à 3 mois ; moyen : de 3 à 12 mois ; long : au-delà de 12 mois "
    "(catégories du schéma, pas un chiffre du modèle)"
)


class Constat(_Llm):
    texte: str = Field(min_length=1, max_length=300)
    appel: str = Field(
        min_length=1,
        max_length=120,
        description="identifiant de l'appel d'outil tel qu'il t'a été montré, ou « source [n] »",
    )
    date: str | None = Field(
        default=None, max_length=40, description="date de la donnée, telle que l'outil la donne"
    )


class AnalystReport(_Llm):
    constats: list[Constat] = Field(default_factory=list, max_length=12)
    signaux: list[Line] = Field(default_factory=list, max_length=8)
    incertitudes: list[Line] = Field(default_factory=list, max_length=8)


class Argument(_Llm):
    texte: str = Field(min_length=1, max_length=400)
    poids: Weight
    constats: list[ConstatId] = Field(min_length=1, max_length=6)
    repond_a: list[ArgumentId] = Field(default_factory=list, max_length=6)


class DebateTurn(_Llm):
    arguments: list[Argument] = Field(min_length=1, max_length=8)
    changer_avis: str = Field(
        min_length=1, max_length=400, description="ce qui me ferait changer d'avis"
    )


class Invalidation(_Llm):
    condition: str = Field(min_length=1, max_length=300)
    constats: list[ConstatId] = Field(min_length=1, max_length=6)


class Catalyseur(_Llm):
    texte: str = Field(min_length=1, max_length=300)
    constats: list[ConstatId] = Field(min_length=1, max_length=6)


class Treatment(_Llm):
    id: ArgumentId
    sort: Literal["retenu", "ecarte"]
    raison: str = Field(min_length=1, max_length=300)


class ManagerDecision(_Llm):
    decision: Choice
    proposition: str = Field(min_length=1, max_length=600)
    confiance: Confidence
    horizon: Horizon = Field(description=HORIZONS)
    catalyseur: Catalyseur | None = Field(
        default=None,
        description="obligatoire pour « agir » : ce qui rend l'action opportune maintenant "
        "plutôt qu'attendre, relié aux constats qui le fondent ; null pour « ne_pas_agir » et "
        "« attendre »",
    )
    invalidation: list[Invalidation] = Field(min_length=1, max_length=5)
    desaccords: list[Line] = Field(default_factory=list, max_length=5)
    arguments: list[Treatment] = Field(min_length=1, max_length=40)


class Scenario(_Llm):
    texte: str = Field(min_length=1, max_length=300)
    appel: str | None = Field(
        default=None,
        max_length=120,
        description="identifiant de l'appel d'outil qui chiffre le scénario, sinon null",
    )


class ControllerReport(_Llm):
    scenarios: list[Scenario] = Field(min_length=1, max_length=6)
    irreversibilite: str = Field(min_length=1, max_length=300)
    verdict: Verdict
    raisons: list[Line] = Field(min_length=1, max_length=6)


RoleOutput = AnalystReport | DebateTurn | ManagerDecision | ControllerReport


def text_fields(output: RoleOutput) -> list[tuple[str, str]]:
    """Every free text of an output, by its path: what the R1 and R5 checks read."""
    fields: list[tuple[str, str]] = []
    if isinstance(output, AnalystReport):
        for n, constat in enumerate(output.constats, start=1):
            fields.append((f"constats[{n}].texte", constat.texte))
            if constat.date:
                fields.append((f"constats[{n}].date", constat.date))
        fields += [(f"signaux[{n}]", text) for n, text in enumerate(output.signaux, start=1)]
        fields += [
            (f"incertitudes[{n}]", text) for n, text in enumerate(output.incertitudes, start=1)
        ]
    elif isinstance(output, DebateTurn):
        fields += [
            (f"arguments[{n}].texte", argument.texte)
            for n, argument in enumerate(output.arguments, start=1)
        ]
        fields.append(("changer_avis", output.changer_avis))
    elif isinstance(output, ManagerDecision):
        fields.append(("proposition", output.proposition))
        if output.catalyseur:
            fields.append(("catalyseur.texte", output.catalyseur.texte))
        fields += [
            (f"invalidation[{n}].condition", item.condition)
            for n, item in enumerate(output.invalidation, start=1)
        ]
        fields += [(f"desaccords[{n}]", text) for n, text in enumerate(output.desaccords, start=1)]
        fields += [
            (f"arguments[{n}].raison", item.raison)
            for n, item in enumerate(output.arguments, start=1)
        ]
    else:
        fields += [
            (f"scenarios[{n}].texte", item.texte)
            for n, item in enumerate(output.scenarios, start=1)
        ]
        fields.append(("irreversibilite", output.irreversibilite))
        fields += [(f"raisons[{n}]", text) for n, text in enumerate(output.raisons, start=1)]
    return fields
