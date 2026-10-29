"""Closed list of INSEE Melodi datasets, input checks and filtering of the replies (plan P6, I3).

- **Datasets.** Three, chosen for a market study and read on 2026-10-29 on the API itself:
  reference populations, business creations, income and living standards (Filosofi). Each
  names the geographic levels it answers, the dimensions a caller may filter on and the unit of
  each measure it knows. Another dataset is refused; the list grows only if the evals justify it
  (R13). The pack's ``knowledge/sources.yaml`` points to this list.
- **Inputs.** A geography ``DEP-44``, ``REG-52``, ``COM-44109`` or ``FRANCE``; a year; up to
  three filters whose names are in the dataset's list and whose codes are short ASCII codes.
- **Output.** Up to 50 observations: their dimension codes, and their value as a ``Figure`` (R1)
  whose unit comes from this list or from the ``UNIT_MEASURE`` code of the observation, never
  from a guess. An observation with an unknown unit, a multiplier or a malformed value is
  omitted and counted. Titles come from this list, not from the reply (R5).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from core.verification.figures import BEFORE_UNIT, Figure, count, french, percent

MAX_OBSERVATIONS = 50
MAX_FILTERS = 3
SOURCE = "Insee, API Melodi"
LICENCE = "Licence Ouverte 2.0 (etalab-2.0) : « Source : Insee », avec la date de mise à jour"
NOTE = (
    "Statistique publique : citer chaque valeur par son identifiant, avec sa période, la date de "
    "mise à jour du jeu et « Source : Insee ». Les codes des dimensions sont ceux de l'Insee ; ne "
    "pas deviner le sens d'un code non décrit. Une valeur n'est pas une prévision (R12)."
)

DatasetId = Literal["DS_POPULATIONS_REFERENCE", "DS_SIDE_CREA_DEP_REG_NAT", "DS_FILOSOFI_CC"]
Level = Literal["COM", "DEP", "REG", "FRANCE"]


@dataclass(frozen=True)
class Dataset:
    title: str
    levels: tuple[Level, ...]
    dimensions: frozenset[str]
    measure: str | None  # the dimension that names the measure, when the unit hangs on it
    units: dict[str, str]  # measure code -> unit, for observations without UNIT_MEASURE


PERSONS, UNITS, PLACES = "habitants", "entreprises", "établissements"
DATASETS: dict[str, Dataset] = {
    "DS_POPULATIONS_REFERENCE": Dataset(
        title="Populations de référence (recensement de la population)",
        levels=("COM", "DEP", "REG", "FRANCE"),
        dimensions=frozenset({"POPREF_MEASURE"}),
        measure="POPREF_MEASURE",
        units={"PMUN": PERSONS, "PCAP": PERSONS, "PTOT": PERSONS},
    ),
    "DS_SIDE_CREA_DEP_REG_NAT": Dataset(
        title=(
            "Créations d'entreprises et d'établissements par département, région et France, "
            "par secteur (A21) et forme juridique"
        ),
        levels=("DEP", "REG", "FRANCE"),
        dimensions=frozenset({"SIDE_MEASURE", "ACTIVITY", "LEGAL_FORM"}),
        measure="SIDE_MEASURE",
        units={"BURE": UNITS, "UNIT_LOC_BURE": PLACES},
    ),
    "DS_FILOSOFI_CC": Dataset(
        title="Revenus et niveau de vie des ménages (Filosofi), communes et départements",
        levels=("COM", "DEP"),
        dimensions=frozenset({"FILOSOFI_MEASURE"}),
        measure=None,  # every observation carries its UNIT_MEASURE
        units={},
    ),
}

_COMMUNE = re.compile(r"\d{5}|2[AB]\d{3}", re.ASCII)
_DEPARTEMENT = re.compile(r"0[1-9]|1\d|2[1-9]|[3-8]\d|9[0-5]|2[AB]|97[12346]", re.ASCII)
_REGION = re.compile(r"\d{2}", re.ASCII)
_YEAR = re.compile(r"(19|20)\d{2}", re.ASCII)
_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,29}", re.ASCII)
_CODE = re.compile(r"[A-Z0-9_]{1,20}", re.ASCII)
_VALUE = re.compile(r"[A-Za-z0-9_\-]{1,40}", re.ASCII)  # no ".": it separates the id
MAX_VALUE = 10**15  # beyond, a value is not a statistic of these datasets


class StatsError(Exception):
    """A refused input or an unreadable reply. The message is French and names no value read."""


@dataclass(frozen=True)
class Query:
    dataset: str
    geo: str  # as sent: DEP-44, FRANCE-F
    period: str | None
    filters: dict[str, str]

    def params(self) -> dict[str, str]:
        """Query string of ``/data/{id}``: one more observation than shown, to tell a cut."""
        params = {"GEO": self.geo, "maxResult": str(MAX_OBSERVATIONS + 1)}
        if self.period is not None:
            params["TIME_PERIOD"] = self.period
        params.update(self.filters)
        return params


def geography(dataset: Dataset, raw: str) -> str:
    value = raw.strip().upper()
    if value == "FRANCE":
        level, sent = "FRANCE", "FRANCE-F"
    else:
        level, _, code = value.partition("-")
        pattern = {"COM": _COMMUNE, "DEP": _DEPARTEMENT, "REG": _REGION}.get(level)
        if pattern is None or pattern.fullmatch(code) is None:
            raise StatsError("geo : COM-<code commune>, DEP-<département>, REG-<région> ou FRANCE")
        sent = value
    if level not in dataset.levels:
        raise StatsError(f"geo : ce jeu répond aux niveaux {', '.join(dataset.levels)}")
    return sent


def query(dataset_id: str, geo: str, period: str | None, filters: dict[str, str] | None) -> Query:
    dataset = DATASETS.get(dataset_id)
    if dataset is None:
        raise StatsError(f"jeu : un des jeux de la liste fermée ({', '.join(DATASETS)})")
    sent = geography(dataset, geo)
    year = None
    if period is not None:
        year = period.strip()
        if _YEAR.fullmatch(year) is None:
            raise StatsError("periode : une année AAAA")
    chosen: dict[str, str] = {}
    for name, code in (filters or {}).items():
        key, value = name.strip().upper(), code.strip().upper()
        if key not in dataset.dimensions:
            allowed = ", ".join(sorted(dataset.dimensions))
            raise StatsError(f"filtres : dimensions possibles pour ce jeu : {allowed}")
        if _CODE.fullmatch(value) is None:
            raise StatsError("filtres : un code de 1 à 20 caractères (A-Z, 0-9, _)")
        chosen[key] = value  # at most MAX_FILTERS: each dataset has no more dimensions
    return Query(dataset_id, sent, year, chosen)


class Observation(BaseModel):
    dimensions: dict[str, str] = Field(description="Codes Insee des dimensions (donnée externe)")
    valeur: Figure


class StatsSeries(BaseModel):
    jeu: str
    titre: str
    geo: str
    periode: str | None
    filtres: dict[str, str]
    observations: list[Observation]
    tronque: bool = Field(description="Vrai si plus de 50 observations : préciser la demande")
    omises: int = Field(
        description="Observations écartées (unité inconnue, valeur illisible ou hors de la demande)"
    )
    mise_a_jour: str | None = Field(description="Date de mise à jour du jeu (catalogue Insee)")
    lu_le: str
    en_cache: bool
    source: str = SOURCE
    licence: str = LICENCE
    note: str = NOTE


def _figure(figure_id: str, value: float, unit: str) -> Figure | None:
    exact = Decimal(repr(value))
    if unit in (PERSONS, UNITS, PLACES):
        return count(figure_id, int(exact), unit) if exact == exact.to_integral() else None
    if unit == "EUR_YR":
        return Figure(
            id=figure_id,
            value=value,
            display=f"{french(exact, 0, max_decimals=2)}{BEFORE_UNIT}€ par an",
            unit="EUR/an",
        )
    if unit == "PT":  # a percentage: 11.3 is 11,3 %
        return percent(figure_id, float(exact / 100))
    if unit == "NR":  # a ratio without unit (Gini index, D9/D1)
        return Figure(
            id=figure_id, value=value, display=french(exact, 0, max_decimals=3), unit="nombre"
        )
    return None


def _dimensions(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    kept = {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}
    if len(kept) != len(raw) or len(kept) > 12:
        return None
    if any(_NAME.fullmatch(k) is None or _VALUE.fullmatch(v) is None for k, v in kept.items()):
        return None
    return kept


def observation(dataset_id: str, raw: Any) -> Observation | None:
    """One observation with a known unit and a finite number; ``None`` otherwise."""
    if not isinstance(raw, dict):
        return None
    dataset = DATASETS[dataset_id]
    dims = _dimensions(raw.get("dimensions"))
    attributes = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
    measures = raw.get("measures")
    level = measures.get("OBS_VALUE_NIVEAU") if isinstance(measures, dict) else None
    value = level.get("value") if isinstance(level, dict) else None
    if dims is None or attributes.get("UNIT_MULT", "0") != "0":
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or value != value:
        return None
    if not abs(value) <= MAX_VALUE:  # also NaN and infinities
        return None
    shown = {k: v for k, v in dims.items() if k != "UNIT_MEASURE"}
    if dataset.measure is None:
        unit = dims.get("UNIT_MEASURE", "")
    else:  # the closed list names the unit; a reply that names one too is not understood
        unit = (
            "" if "UNIT_MEASURE" in dims else dataset.units.get(dims.get(dataset.measure, ""), "")
        )
    figure_id = ".".join([dataset_id, *(dims[k] for k in sorted(dims))])
    if len(figure_id) > 200:
        return None
    figure = _figure(figure_id, float(value), unit)
    return None if figure is None else Observation(dimensions=shown, valeur=figure)


def _asked(asked: Query, found: Observation) -> bool:
    """Whether an observation answers the query: same place, year and filters (R1, R12).
    The API prefixes the place with the year of the geography (``2025-DEP-44``)."""
    dims = found.dimensions
    place = dims.get("GEO", "")
    if place != asked.geo and not re.fullmatch(rf"\d{{4}}-{re.escape(asked.geo)}", place, re.ASCII):
        return False
    if asked.period is not None and dims.get("TIME_PERIOD") != asked.period:
        return False
    return all(dims.get(name) == code for name, code in asked.filters.items())


def parse_data(asked: Query, body: bytes) -> tuple[list[Observation], bool, int]:
    """The kept observations, whether the reply was cut, and how many were omitted: unreadable,
    outside the query, or with an id already seen."""
    dataset_id = asked.dataset
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        raise StatsError("réponse illisible (JSON invalide)") from None
    found = data.get("observations") if isinstance(data, dict) else None
    if not isinstance(found, list) or data.get("identifier") != dataset_id:
        raise StatsError("réponse illisible (format inattendu)")
    cut = len(found) > MAX_OBSERVATIONS
    read = [observation(dataset_id, item) for item in found[:MAX_OBSERVATIONS]]
    kept: dict[str, Observation] = {}
    for item in read:
        if item is not None and _asked(asked, item) and item.valeur.id not in kept:
            kept[item.valeur.id] = item
    return list(kept.values()), cut, len(read) - len(kept)


def parse_catalog(dataset_id: str, body: bytes) -> str | None:
    """The date the dataset was last updated, from ``/catalog/{id}``; ``None`` if unreadable."""
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        raise StatsError("catalogue illisible (JSON invalide)") from None
    if not isinstance(data, dict) or data.get("identifier") != dataset_id:
        raise StatsError("catalogue illisible (format inattendu)")
    modified = data.get("modified")
    if not isinstance(modified, str):
        return None
    try:
        return datetime.fromisoformat(modified[:19]).date().isoformat()
    except ValueError:
        return None
