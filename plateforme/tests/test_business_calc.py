"""The deterministic business calculator (ADR-061): formulas, rounding, refusals, properties."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from core.business.calc import CalcError, Request, calculate
from core.config.loader import VatConfig, load_config
from tests.conftest import REPO_ROOT

ADAPTER: TypeAdapter[Any] = TypeAdapter(Request)
DAY = date(2026, 10, 29)
VAT = load_config(REPO_ROOT / "config").business.vat
NBSP = " "
THIN = " "


def shown(vat: VatConfig | None = VAT, day: date = DAY, **fields: Any) -> dict[str, str]:
    out = calculate(ADAPTER.validate_python(fields), vat=vat, today=day)
    return {figure.id: figure.display for figure in [*out.inputs, *out.results]}


def values(**fields: Any) -> dict[str, float]:
    out = calculate(ADAPTER.validate_python(fields), vat=VAT, today=DAY)
    return {figure.id: figure.value for figure in out.results}


def test_margin_rates_and_multiplier() -> None:
    got = shown(operation="marge", prix_vente_ht="25", cout_achat_ht="15")
    assert got["resultat.marge_brute"] == f"10,00{NBSP}€"
    assert got["resultat.taux_marge"] == f"66,67{NBSP}%"
    assert got["resultat.taux_marque"] == f"40,00{NBSP}%"
    assert got["resultat.coefficient"] == "1,6667"


@pytest.mark.parametrize(
    ("cible", "valeur", "price"),
    [
        ("taux_marge", "0.5", "22,50"),
        ("taux_marque", "0.4", "25,00"),
        ("coefficient", "2.2", "33,00"),
    ],
)
def test_price_from_each_target(cible: str, valeur: str, price: str) -> None:
    got = shown(operation="prix_de_vente", cout_achat_ht="15", cible=cible, valeur=valeur)
    assert got["resultat.prix_vente_ht"] == f"{price}{NBSP}€"


def test_vat_both_ways_rounds_to_the_cent() -> None:
    up = shown(operation="tva", montant="49.90", sens="ht_vers_ttc", taux="normal")
    assert (up["resultat.tva"], up["resultat.ttc"]) == (f"9,98{NBSP}€", f"59,88{NBSP}€")
    down = shown(operation="tva", montant="100", sens="ttc_vers_ht", taux="normal")
    assert (down["resultat.ht"], down["resultat.tva"]) == (f"83,33{NBSP}€", f"16,67{NBSP}€")
    assert down["entree.taux_tva"] == f"20,00{NBSP}%"


def test_vat_refusals() -> None:
    vat = {"operation": "tva", "montant": "1", "sens": "ht_vers_ttc"}
    with pytest.raises(CalcError, match="table de TVA absente"):
        shown(vat=None, taux="normal", **vat)
    with pytest.raises(CalcError, match=r"vat\.rates\.particulier\.rate = A_VERIFIER"):
        shown(taux="particulier", **vat)
    with pytest.raises(CalcError, match="31/12/2026"):
        shown(day=date(2027, 1, 1), taux="normal", **vat)
    marked = VAT.model_copy(update={"valid_until": "A_VERIFIER"})
    with pytest.raises(CalcError, match=r"vat\.valid_until = A_VERIFIER"):
        shown(vat=marked, taux="normal", **vat)


def test_break_even_and_its_day() -> None:
    fields = {
        "operation": "seuil_rentabilite",
        "chiffre_affaires_ht": "120000",
        "charges_variables_ht": "72000",
    }
    got = shown(charges_fixes="30000", **fields)
    assert got["resultat.seuil_rentabilite"] == f"75{THIN}000,00{NBSP}€"
    assert got["resultat.point_mort"] == f"225,0{NBSP}jours"
    assert got["resultat.marge_de_securite"] == f"45{THIN}000,00{NBSP}€"
    out = calculate(ADAPTER.validate_python({**fields, "charges_fixes": "60000"}), today=DAY)
    assert any("au-delà de l'exercice" in c for c in out.conventions)


def test_cac_ltv_and_growth() -> None:
    got = shown(
        operation="cac_ltv",
        depenses_acquisition="500",
        nouveaux_clients=20,
        panier_moyen_ht="35",
        achats_par_an="3",
        duree_vie_ans="2",
        taux_marge_brute="0.6",
    )
    assert (got["resultat.cac"], got["resultat.ltv"]) == (f"25,00{NBSP}€", f"126,00{NBSP}€")
    assert got["resultat.ltv_sur_cac"] == "5,04"
    growth = shown(operation="variation", valeur_initiale="8000", valeur_finale="9200")
    assert growth["resultat.variation"] == f"15,00{NBSP}%"
    cagr = shown(operation="tcac", valeur_initiale="100", valeur_finale="200", annees="3")
    assert cagr["resultat.tcac"] == f"25,99{NBSP}%"


@pytest.mark.parametrize(
    "fields",
    [
        {"operation": "marge", "prix_vente_ht": "10", "cout_achat_ht": "0"},
        {"operation": "marge", "prix_vente_ht": "NaN", "cout_achat_ht": "1"},
        {"operation": "marge", "prix_vente_ht": "1", "cout_achat_ht": "1", "extra": "1"},
        {"operation": "prix_de_vente", "cout_achat_ht": "1", "cible": "taux_marque", "valeur": "1"},
        {
            "operation": "seuil_rentabilite",
            "chiffre_affaires_ht": "10",
            "charges_variables_ht": "10",
            "charges_fixes": "1",
        },
        {
            "operation": "cac_ltv",
            "depenses_acquisition": "1",
            "nouveaux_clients": 0,
            "panier_moyen_ht": "1",
            "achats_par_an": "1",
            "duree_vie_ans": "1",
            "taux_marge_brute": "0.5",
        },
        {
            "operation": "cac_ltv",
            "depenses_acquisition": "1",
            "nouveaux_clients": 1,
            "panier_moyen_ht": "1",
            "achats_par_an": "1",
            "duree_vie_ans": "1",
            "taux_marge_brute": "1.5",
        },
        {"operation": "tcac", "valeur_initiale": "1", "valeur_finale": "2", "annees": "0"},
        {"operation": "prix_de_vente", "cout_achat_ht": "1", "cible": "taux_marge", "valeur": "40"},
        {"operation": "tva", "montant": "10.0049", "sens": "ht_vers_ttc", "taux": "normal"},
        {"operation": "devis"},
    ],
)
def test_inconsistent_inputs_are_refused(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ADAPTER.validate_python(fields)


def conventions(**fields: Any) -> list[str]:
    return calculate(ADAPTER.validate_python(fields), vat=VAT, today=DAY).conventions


def test_conventions_flag_the_unusual_cases() -> None:
    below = conventions(
        operation="prix_de_vente", cout_achat_ht="10", cible="coefficient", valeur="0.8"
    )
    assert any("sous le coût d'achat" in c for c in below)
    assert not any(
        "sous le coût" in c
        for c in conventions(
            operation="prix_de_vente", cout_achat_ht="10", cible="coefficient", valeur="1.2"
        )
    )
    vat = {"operation": "tva", "sens": "ttc_vers_ht", "taux": "normal"}
    assert any("aucun montant HT" in c for c in conventions(montant="0.15", **vat))
    assert not any("aucun montant HT" in c for c in conventions(montant="100", **vat))
    growth = {"operation": "tcac", "valeur_initiale": "100", "valeur_finale": "110"}
    assert any("extrapolé" in c for c in conventions(annees="0.5", **growth))
    assert not any("extrapolé" in c for c in conventions(annees="1", **growth))


def test_a_daily_purchase_is_accepted() -> None:
    fields = {"depenses_acquisition": "100", "nouveaux_clients": 10, "panier_moyen_ht": "5"}
    got = shown(
        operation="cac_ltv",
        achats_par_an="250",
        duree_vie_ans="1",
        taux_marge_brute="0.5",
        **fields,
    )
    assert got["resultat.ltv"] == f"625,00{NBSP}€"


@pytest.mark.parametrize(
    "fields",
    [
        {"operation": "tcac", "valeur_initiale": "1", "valeur_finale": "2", "annees": "0.0001"},
        {
            "operation": "cac_ltv",
            "depenses_acquisition": "0.0001",
            "nouveaux_clients": 1_000_000_000,
            "panier_moyen_ht": "1000000000000",
            "achats_par_an": "366",
            "duree_vie_ans": "100",
            "taux_marge_brute": "1",
        },
    ],
)
def test_out_of_range_results_are_refused_with_a_message(fields: dict[str, Any]) -> None:
    with pytest.raises(CalcError, match="hors des bornes affichables"):
        calculate(ADAPTER.validate_python(fields), vat=VAT, today=DAY)


money = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("1000000"), places=2)


@given(money, money)
def test_a_margin_and_its_multiplier_rebuild_the_price(price: Decimal, cost: Decimal) -> None:
    assume(Decimal("0.01") <= price / cost <= 100)  # the multiplier input lies in (0, 100]
    got = values(operation="marge", prix_vente_ht=str(price), cout_achat_ht=str(cost))
    assert got["resultat.marge_brute"] == float(price - cost)
    rebuilt = values(
        operation="prix_de_vente",
        cout_achat_ht=str(cost),
        cible="coefficient",
        valeur=str(round(price / cost, 6)),
    )
    # The multiplier is given to six places: the rebuilt price is within that error of cost.
    tolerance = max(0.01, float(cost) * 1e-6)
    assert rebuilt["resultat.prix_vente_ht"] == pytest.approx(float(price), abs=tolerance)


@given(money)
def test_vat_adds_up_to_the_cent(amount: Decimal) -> None:
    for sens in ("ht_vers_ttc", "ttc_vers_ht"):
        got = values(operation="tva", montant=str(amount), sens=sens, taux="normal")
        ht, tax, ttc = (Decimal(repr(got[f"resultat.{k}"])) for k in ("ht", "tva", "ttc"))
        assert ht + tax == ttc
        assert abs(tax - ht * Decimal("0.20")) <= Decimal("0.01")


@given(money, money, st.decimals(min_value=Decimal("0.5"), max_value=Decimal("50"), places=2))
def test_growth_matches_the_compound_formula(start: Decimal, end: Decimal, years: Decimal) -> None:
    rate = values(
        operation="tcac", valeur_initiale=str(start), valeur_finale=str(end), annees=str(years)
    )["resultat.tcac"]
    assert rate == pytest.approx(float(end / start) ** (1 / float(years)) - 1, rel=1e-12, abs=1e-12)
