"""Inputs, units, filtering of the Melodi reader (I3): closed list, each value a Figure."""

from __future__ import annotations

import json
from typing import Any

import pytest

from core.verification.figures import figures_in
from plugins.insee_stats.catalog import (
    DATASETS,
    MAX_FILTERS,
    MAX_OBSERVATIONS,
    StatsError,
    StatsSeries,
    geography,
    observation,
    parse_catalog,
    parse_data,
    query,
)
from plugins.insee_stats.tests.support import (
    FILOSOFI,
    POPREF,
    SIDE,
    catalog,
    data,
    obs,
    popref,
)

NBSP = " "
THIN = " "


def test_the_closed_list_holds_three_datasets_within_the_filter_cap() -> None:
    assert sorted(DATASETS) == sorted([POPREF, SIDE, FILOSOFI])
    assert all(len(dataset.dimensions) <= MAX_FILTERS for dataset in DATASETS.values())


@pytest.mark.parametrize(
    ("dataset", "raw", "sent"),
    [
        (POPREF, " dep-44 ", "DEP-44"),
        (POPREF, "DEP-2A", "DEP-2A"),
        (POPREF, "DEP-976", "DEP-976"),
        (POPREF, "COM-44109", "COM-44109"),
        (POPREF, "COM-2B033", "COM-2B033"),
        (POPREF, "REG-52", "REG-52"),
        (POPREF, "france", "FRANCE-F"),
        (SIDE, "FRANCE", "FRANCE-F"),
        (FILOSOFI, "COM-44109", "COM-44109"),
    ],
)
def test_a_geography_is_sent_in_the_api_form(dataset: str, raw: str, sent: str) -> None:
    assert geography(DATASETS[dataset], raw) == sent


@pytest.mark.parametrize(
    "raw",
    [
        "DEP-20",
        "DEP-00",
        "DEP-96",
        "DEP-975",
        "COM-4410",
        "REG-5",
        "REG-5a",
        "ARR-441",
        "44",
        "FRANCE-F",
        "DEP-٤٤",
        "DEP-44&x=1",
    ],
)
def test_a_malformed_geography_is_refused(raw: str) -> None:
    with pytest.raises(StatsError, match="geo : COM-<code commune>"):
        geography(DATASETS[POPREF], raw)


@pytest.mark.parametrize(
    ("dataset", "raw", "levels"),
    [
        (FILOSOFI, "FRANCE", "COM, DEP"),
        (FILOSOFI, "REG-52", "COM, DEP"),
        (SIDE, "COM-44109", "DEP, REG, FRANCE"),
    ],
)
def test_a_level_the_dataset_lacks_is_refused(dataset: str, raw: str, levels: str) -> None:
    with pytest.raises(StatsError, match=f"niveaux {levels}$"):
        geography(DATASETS[dataset], raw)


def test_a_query_checks_every_input() -> None:
    asked = query(SIDE, "DEP-44", " 2024 ", {" side_measure ": " bure ", "ACTIVITY": "_T"})
    assert (asked.geo, asked.period) == ("DEP-44", "2024")
    assert asked.filters == {"SIDE_MEASURE": "BURE", "ACTIVITY": "_T"}
    assert asked.params() == {
        "GEO": "DEP-44",
        "maxResult": str(MAX_OBSERVATIONS + 1),
        "TIME_PERIOD": "2024",
        "SIDE_MEASURE": "BURE",
        "ACTIVITY": "_T",
    }
    bare = query(POPREF, "FRANCE", None, None)
    assert bare.params() == {"GEO": "FRANCE-F", "maxResult": "51"}


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (("DS_INCONNU", "DEP-44", None, None), "jeu : un des jeux de la liste fermée"),
        ((POPREF, "DEP-44", "1850", None), "periode : une année AAAA"),
        ((POPREF, "DEP-44", "２０２３", None), "periode : une année AAAA"),
        ((POPREF, "DEP-44", None, {"GEO": "DEP-75"}), "dimensions possibles pour ce jeu : POPREF"),
        ((SIDE, "DEP-44", None, {"SIDE_MEASURE": "BURE&GEO=X"}), "un code de 1 à 20"),
        ((SIDE, "DEP-44", None, {"ACTIVITY": "x" * 21}), "un code de 1 à 20"),
        ((SIDE, "DEP-44", None, {"ACTIVITY": ""}), "un code de 1 à 20"),
    ],
)
def test_a_bad_query_is_refused(arguments: tuple[Any, ...], message: str) -> None:
    with pytest.raises(StatsError, match=message):
        query(*arguments)


# Units: from the closed list or from UNIT_MEASURE, never guessed.


def test_a_population_is_a_count_of_inhabitants() -> None:
    found = observation(POPREF, popref())
    assert found is not None
    assert found.dimensions == {
        "GEO": "2025-DEP-44",
        "FREQ": "A",
        "TIME_PERIOD": "2023",
        "POPREF_MEASURE": "PTOT",
    }
    figure = found.valeur
    assert figure.id == f"{POPREF}.A.2025-DEP-44.PTOT.2023"
    assert (figure.value, figure.unit) == (1517043, "habitants")
    assert figure.display == f"1{THIN}517{THIN}043{NBSP}habitants"


@pytest.mark.parametrize(
    ("measure", "value", "display"),
    [
        ("BURE", 20350.0, f"20{THIN}350{NBSP}entreprises"),
        ("UNIT_LOC_BURE", 1.0, f"1{NBSP}établissement"),
    ],
)
def test_a_creation_count_takes_the_unit_of_its_measure(
    measure: str, value: float, display: str
) -> None:
    raw = obs(
        value,
        {"OBS_STATUS": "A"},
        GEO="2025-DEP-44",
        SIDE_MEASURE=measure,
        TIME_PERIOD="2024",
        LEGAL_FORM="_T",
        ACTIVITY="_T",
        FREQ="A",
    )
    found = observation(SIDE, raw)
    assert found is not None and found.valeur.display == display


@pytest.mark.parametrize(
    ("unit", "value", "shown", "display"),
    [
        ("EUR_YR", 23160.0, 23160.0, f"23{THIN}160{NBSP}€ par an"),
        ("EUR_YR", 23160.456, 23160.456, f"23{THIN}160,46{NBSP}€ par an"),
        ("PT", 11.3, 0.113, f"11,30{NBSP}%"),
        ("NR", 0.271, 0.271, "0,271"),
        ("NR", 3, 3.0, "3"),
    ],
)
def test_an_income_takes_the_unit_of_its_observation(
    unit: str, value: float, shown: float, display: str
) -> None:
    raw = obs(
        value,
        {"UNIT_MULT": "0", "OBS_STATUS": "A", "CONF_STATUS": "F"},
        GEO="2025-COM-44109",
        TIME_PERIOD="2023",
        UNIT_MEASURE=unit,
        FILOSOFI_MEASURE="MED_SL",
    )
    found = observation(FILOSOFI, raw)
    assert found is not None
    assert "UNIT_MEASURE" not in found.dimensions
    assert (found.valeur.value, found.valeur.display) == (shown, display)
    assert found.valeur.id == f"{FILOSOFI}.MED_SL.2025-COM-44109.2023.{unit}"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "obs",
        obs(1.0),  # no dimension
        obs(1.0, POPREF_MEASURE=7),
        obs(1.0, POPREF_MEASURE="PTOT", geo="x"),
        obs(1.0, POPREF_MEASURE="PTOT plus"),
        obs(1.0, POPREF_MEASURE="x" * 41),
        obs(1.0, **{f"D{i}": "A" for i in range(13)}),
        obs(1.0, POPREF_MEASURE="PTOTAL"),  # a measure the list does not know
        obs(1.0, GEO="2025-DEP-44"),  # no measure at all
        obs(1.5, POPREF_MEASURE="PTOT"),  # a fraction of a person
        obs(1.0, {"UNIT_MULT": "3"}, POPREF_MEASURE="PTOT"),
        obs(True, POPREF_MEASURE="PTOT"),
        obs("12", POPREF_MEASURE="PTOT"),
        obs(None, POPREF_MEASURE="PTOT"),
        obs(float("nan"), POPREF_MEASURE="PTOT"),
        obs(float("inf"), POPREF_MEASURE="PTOT"),
        obs(1e16, POPREF_MEASURE="PTOT"),  # beyond any statistic of the list
        obs(10**400, POPREF_MEASURE="PTOT"),  # would overflow a float
        obs(1.0, POPREF_MEASURE="PTOT", GEO="2025.DEP-44"),  # "." separates the id
        obs(1.0, POPREF_MEASURE="PTOT", UNIT_MEASURE="EUR_YR"),  # the list names the unit
        obs(1.0, POPREF_MEASURE="PTOT", **{f"D{i}": "x" * 40 for i in range(5)}),  # id > 200
        {"dimensions": {"POPREF_MEASURE": "PTOT"}, "measures": {"OBS_VALUE_NIVEAU": 3}},
        {"dimensions": {"POPREF_MEASURE": "PTOT"}, "measures": []},
        {"dimensions": {"POPREF_MEASURE": "PTOT"}, "attributes": "x", "measures": {}},
    ],
)
def test_an_observation_without_a_sure_unit_or_number_is_omitted(raw: Any) -> None:
    assert observation(POPREF, raw) is None


def test_an_income_without_its_unit_or_with_an_unknown_one_is_omitted() -> None:
    assert observation(FILOSOFI, obs(1.0, FILOSOFI_MEASURE="MED_SL")) is None
    assert observation(FILOSOFI, obs(1.0, FILOSOFI_MEASURE="MED_SL", UNIT_MEASURE="USD")) is None


# Replies.


ASKED = query(POPREF, "DEP-44", "2023", None)


def test_a_reply_keeps_its_observations_and_counts_the_omitted_ones() -> None:
    body = json.dumps(data(POPREF, [popref(), popref("PMUN", 1.5), "x"])).encode()
    kept, cut, omitted = parse_data(ASKED, body)
    assert ([o.dimensions["POPREF_MEASURE"] for o in kept], cut, omitted) == (["PTOT"], False, 2)


def test_a_reply_longer_than_the_cap_is_cut() -> None:
    many = [popref(value=float(i)) for i in range(MAX_OBSERVATIONS + 1)]
    kept, cut, omitted = parse_data(ASKED, json.dumps(data(POPREF, many)).encode())
    assert (len(kept), cut, omitted) == (1, True, MAX_OBSERVATIONS - 1)  # one id, kept once


def test_an_observation_outside_the_query_is_omitted() -> None:
    side = query(SIDE, "DEP-44", "2024", {"SIDE_MEASURE": "BURE"})

    def crea(**changed: str) -> dict[str, Any]:
        dims = {
            "GEO": "2025-DEP-44",
            "TIME_PERIOD": "2024",
            "SIDE_MEASURE": "BURE",
            "ACTIVITY": "_T",
        }
        return obs(5.0, **{**dims, **changed})

    found = [
        crea(),
        crea(GEO="DEP-44", ACTIVITY="C"),  # the place without its year prefix
        crea(GEO="2025-DEP-75"),
        crea(GEO="2025-DEP-440"),
        crea(GEO="x2025-DEP-44"),
        crea(TIME_PERIOD="2023"),
        crea(SIDE_MEASURE="UNIT_LOC_BURE"),
    ]
    kept, _, omitted = parse_data(side, json.dumps(data(SIDE, found)).encode())
    assert ([o.dimensions["GEO"] for o in kept], omitted) == (["2025-DEP-44", "DEP-44"], 5)
    bare = query(POPREF, "DEP-44", None, None)
    kept, _, omitted = parse_data(bare, json.dumps(data()).encode())
    assert (len(kept), omitted) == (2, 0)  # no year asked: every year answers


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (b"{", "JSON invalide"),
        pytest.param(b"[" * 100_000, "JSON invalide", id="deep"),
        (b"[]", "format inattendu"),
        (json.dumps({"identifier": POPREF}).encode(), "format inattendu"),
        (json.dumps(data(SIDE)).encode(), "format inattendu"),
    ],
)
def test_an_unreadable_reply_is_refused(body: bytes, reason: str) -> None:
    with pytest.raises(StatsError, match=reason):
        parse_data(ASKED, body)


def test_the_catalog_gives_the_update_date() -> None:
    assert parse_catalog(POPREF, json.dumps(catalog()).encode()) == "2025-12-18"
    for modified in (None, 20251218, "hier", ""):
        assert parse_catalog(POPREF, json.dumps(catalog(modified=modified)).encode()) is None
    for body, reason in ((b"{", "JSON invalide"), (json.dumps(catalog(SIDE)).encode(), "format")):
        with pytest.raises(StatsError, match=f"catalogue illisible \\({reason}"):
            parse_catalog(POPREF, body)


def test_every_number_of_the_output_is_a_figure() -> None:
    kept, cut, omitted = parse_data(ASKED, json.dumps(data()).encode())
    output = StatsSeries(
        jeu=POPREF,
        titre=DATASETS[POPREF].title,
        geo="DEP-44",
        periode="2023",
        filtres={},
        observations=kept,
        tronque=cut,
        omises=omitted,
        mise_a_jour="2025-12-18",
        lu_le="2026-10-29T09:30:00+00:00",
        en_cache=False,
    )
    figures, loose = figures_in(output.model_dump(mode="json"))
    assert sorted(f.id for f in figures) == [
        f"{POPREF}.A.2025-DEP-44.PCAP.2023",
        f"{POPREF}.A.2025-DEP-44.PTOT.2023",
    ]
    assert loose == ["$.omises"]
