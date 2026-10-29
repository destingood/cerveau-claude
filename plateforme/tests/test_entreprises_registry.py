"""Checks and filtering of the company registry reader (ADR-062): inputs, Luhn, no person out."""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.verification.figures import figures_in
from plugins.entreprises.registry import (
    MAX_RESULTS,
    MAX_YEARS,
    CompanySearch,
    Filters,
    RegistryError,
    company,
    filters,
    luhn_ok,
    named,
    parse_reply,
    query_text,
    search_params,
    siren,
    total_figure,
    words,
)
from plugins.entreprises.tests.support import (
    PERSON_NAMES,
    SECRET_FIELDS,
    SIREN,
    reply,
)
from plugins.entreprises.tests.support import (
    company as raw_company,
)

NBSP = " "
THIN = " "


@given(st.text(alphabet="0123456789", min_size=8, max_size=8))
def test_exactly_one_key_digit_completes_a_siren(stem: str) -> None:
    assert sum(luhn_ok(stem + key) for key in "0123456789") == 1


def test_a_siren_needs_nine_digits_and_its_key() -> None:
    assert siren("356 000 000") == SIREN
    for bad in ("356000001", "35600000", "3560000000", "35600000A", "３５６０００００ ０"):
        with pytest.raises(RegistryError, match="Luhn"):
            siren(bad)


def test_a_search_text_is_bounded_and_clean() -> None:
    assert query_text("  Matcha \t atelier ") == "Matcha atelier"
    for bad in ("ab", "x" * 101, "matcha\u0007", "matcha​"):
        with pytest.raises(RegistryError, match="caractère de contrôle"):
            query_text(bad)
    with pytest.raises(RegistryError, match="champ siren"):
        query_text("356 000 000")


def test_filters_match_their_expressions() -> None:
    chosen = filters("69003", "2a", "47.91b", "A")
    assert chosen == Filters(
        code_postal="69003", departement="2A", activite_principale="47.91B", etat_administratif="A"
    )
    assert filters(None, None, None, None) == Filters()
    for value in ("01", "95", "2B", "971", "976"):
        assert filters(None, value, None, None).departement == value
    for name, args in (
        ("code_postal", ("6900", None, None)),
        ("departement", (None, "20", None)),
        ("departement", (None, "96", None)),
        ("departement", (None, "975", None)),
        ("activite_principale", (None, None, "4791B")),
    ):
        with pytest.raises(RegistryError, match=name):
            filters(*args, None)


def test_the_request_never_asks_for_a_person() -> None:
    chosen = filters("69003", None, None, "A")
    by_text = search_params("matcha", None, chosen)
    assert by_text == {
        "q": "matcha",
        "page": "1",
        "per_page": str(MAX_RESULTS),
        "minimal": "true",
        "include": "siege,finances",
        "code_postal": "69003",
        "etat_administratif": "A",
    }
    by_number = search_params(None, SIREN, chosen)
    assert by_number["q"] == SIREN and "code_postal" not in by_number  # the API ignores them
    for params in (by_text, by_number):
        assert "dirigeants" not in json.dumps(params)


def test_a_result_keeps_only_the_closed_list_of_fields() -> None:
    kept = company(raw_company())
    assert kept is not None
    shown = json.dumps(kept.model_dump(mode="json"), ensure_ascii=False)
    for secret in (*PERSON_NAMES, *SECRET_FIELDS, "nature_juridique", "latitude", "35600000000048"):
        assert secret not in shown
    assert (kept.siren, kept.denomination, kept.sigle) == (
        SIREN,
        "Matcha Atelier (MATCHA)",
        "MATCHA",
    )
    assert (kept.siege_commune, kept.siege_code_postal, kept.siege_departement) == (
        "LYON 3EME",
        "69003",
        "69",
    )
    assert (kept.etat_administratif, kept.categorie_entreprise) == ("active", "PME")
    assert (kept.mise_a_jour_insee, kept.mise_a_jour_rne) == ("2026-10-01", "2026-09-30")
    assert [a.annee for a in kept.comptes] == ["2023", "2022", "2021"]
    latest = kept.comptes[0]
    assert latest.chiffre_affaires is not None and latest.resultat_net is not None
    assert latest.chiffre_affaires.display == f"245{THIN}678{NBSP}€"
    assert latest.resultat_net.display == f"-1{THIN}234{NBSP}€"
    assert latest.chiffre_affaires.id == f"{SIREN}.2023.chiffre_affaires"
    assert kept.comptes[1].resultat_net is None


@pytest.mark.parametrize("legal_form", ["1000", None, "5x10", 5710, "0000"])
def test_the_head_office_of_a_natural_person_is_dropped(legal_form: Any) -> None:
    """An individual entrepreneur's head office is often a home (I4): kept only for a legal
    entity whose form is read."""
    kept = company(raw_company(nature_juridique=legal_form))
    assert kept is not None and kept.siren == SIREN and kept.comptes
    assert (kept.siege_commune, kept.siege_code_postal, kept.siege_departement) == (None,) * 3


def test_words_ignore_case_accents_and_punctuation() -> None:
    assert words("L'Atelier-Thé  N°2") == ["l", "atelier", "the", "n", "2"]


def test_a_result_is_named_after_every_word_of_the_text() -> None:
    raw = raw_company()
    assert named(raw, "matcha") and named(raw, "atelier MATCHA") and named(raw, "MATCHA")
    for text in ("Dupontel", "Josiane", "rue des Lilas", "Lyon", "matcha lilas"):
        assert not named(raw, text), text
    assert not named("356000000", "matcha")
    assert named(raw_company(nom_complet=None, nom_raison_sociale=None, sigle="TMX"), "tmx")


def test_malformed_fields_are_dropped_not_guessed() -> None:
    kept = company(
        raw_company(
            nom_complet=None,
            nom_raison_sociale="  MATCHA  ",
            sigle=12,
            activite_principale="47.91",
            categorie_entreprise="TPE",
            annee_categorie_entreprise=2023,
            etat_administratif="X",
            date_creation="2019-13-01",
            date_fermeture=20200101,
            date_mise_a_jour_insee="hier",
            date_mise_a_jour_rne=None,
            tranche_effectif_salarie="3",
            annee_tranche_effectif_salarie=True,
            siege="Lyon",
            finances={"2024": "n/a", "20x5": {"ca": 1}, "2023": {"ca": True, "resultat_net": 1.5}},
        )
    )
    assert kept is not None
    assert kept.denomination == "MATCHA"
    assert kept.annee_categorie_entreprise == "2023"  # an integer year becomes text
    for name in (
        "sigle",
        "activite_principale",
        "categorie_entreprise",
        "etat_administratif",
        "date_creation",
        "date_fermeture",
        "mise_a_jour_insee",
        "mise_a_jour_rne",
        "tranche_effectif_salarie",
        "annee_tranche_effectif_salarie",
        "siege_commune",
    ):
        assert getattr(kept, name) is None, name
    assert [(a.annee, a.chiffre_affaires, a.resultat_net) for a in kept.comptes] == [
        ("2024", None, None),
        ("2023", None, None),
    ]
    assert company(raw_company(finances=[1, 2])).comptes == []  # type: ignore[union-attr]


def test_only_the_latest_years_are_kept() -> None:
    years = {str(2015 + i): {"ca": i, "resultat_net": i} for i in range(9)}
    kept = company(raw_company(finances=years))
    assert kept is not None
    assert [a.annee for a in kept.comptes] == [str(2023 - i) for i in range(MAX_YEARS)]


@pytest.mark.parametrize(
    "raw",
    [
        "356000000",
        raw_company(siren="35600000"),
        raw_company(siren=356000000),
        raw_company(nom_complet="", nom_raison_sociale=None),
    ],
)
def test_a_result_without_identity_is_dropped(raw: Any) -> None:
    assert company(raw) is None


def test_a_reply_is_parsed_and_bounded() -> None:
    many = [raw_company() for _ in range(MAX_RESULTS + 3)] + ["bruit"]
    total, found = parse_reply(json.dumps(reply(many, total=250)).encode())
    assert (total, len(found)) == (250, MAX_RESULTS)
    total, found = parse_reply(json.dumps(reply(["bruit", raw_company()])).encode())
    assert (total, len(found)) == (1, 1)
    total, found = parse_reply(json.dumps(reply(many, total=250)).encode(), "Josiane")
    assert (total, found) == (0, [])
    total, found = parse_reply(json.dumps(reply(many, total=250)).encode(), "matcha")
    assert (total, len(found)) == (MAX_RESULTS, MAX_RESULTS)


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (b"{", "JSON invalide"),
        (b"[" * 100_000, "JSON invalide"),
        (b"[]", "format inattendu"),
        (json.dumps({"results": {}, "total_results": 1}).encode(), "format inattendu"),
        (json.dumps(reply(total=-1)).encode(), "format inattendu"),
        (json.dumps(reply(total="1")).encode(), "format inattendu"),
        (json.dumps(reply(total=True)).encode(), "format inattendu"),
    ],
    ids=["truncated", "too-deep", "list", "results-not-list", "negative", "text", "bool"],
)
def test_an_unreadable_reply_is_refused(body: bytes, reason: str) -> None:
    with pytest.raises(RegistryError, match=reason):
        parse_reply(body)


def test_every_number_of_the_output_is_a_figure() -> None:
    total, found = parse_reply(json.dumps(reply()).encode())
    output = CompanySearch(
        recherche="matcha",
        siren=None,
        filtres=Filters(),
        total=total_figure(total),
        resultats=found,
        lu_le="2026-10-29T09:30:00+00:00",
        en_cache=False,
    )
    figures, loose = figures_in(output.model_dump(mode="json"))
    assert loose == []
    assert figures[0].id == "total"
    assert len(figures) == 1 + 5  # the total, then two amounts for 2023 and 2021, one for 2022
