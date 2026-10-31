"""Deterministic business calculations of ``biz_calc`` (phase 6, P6; ADR-061).

One closed list of operations (I2): margin, selling price from a target, VAT, break-even, CAC and
LTV, change and compound annual growth. Inputs are exact decimals and the arithmetic is decimal,
so ``0.1 + 0.2`` is ``0.3``. Every input and result leaves as a Figure with its French display
(R1): the planner cites it and never recomputes it. Values are not rounded, except VAT amounts,
rounded to the cent half up so that HT + TVA = TTC to the cent, as on an invoice.

The VAT rate comes from ``config/business.yaml`` (I7): a rate still ``A_VERIFIER``, or a date past
the table's validity, refuses the operation (R7, R10). No input is guessed: each operation states
its formulas and conventions, and assumes nothing else.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.config.loader import VatConfig
from core.verification.figures import Figure, amount, count, percent, plain

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("1e12")
# A margin rate above 1000 % is read as a percentage given for a fraction (40 for 0.4).
MAX_MARGIN_RATE = 10
# The commercial year of French management accounting, for the break-even day.
COMMERCIAL_YEAR_DAYS = 360
NOTICE = (
    "Calcul déterministe de biz_calc : citer les affichages tels quels, ne pas les recalculer "
    "(R1). Aide à la décision personnelle, pas un conseil (R16)."
)

Amount = Annotated[Decimal, Field(ge=0, le=MAX_AMOUNT, decimal_places=4, allow_inf_nan=False)]
PositiveAmount = Annotated[
    Decimal, Field(gt=0, le=MAX_AMOUNT, decimal_places=4, allow_inf_nan=False)
]
Rate = Annotated[Decimal, Field(gt=0, le=100, decimal_places=6, allow_inf_nan=False)]
Years = Annotated[Decimal, Field(gt=0, le=100, decimal_places=4, allow_inf_nan=False)]
PerYear = Annotated[Decimal, Field(gt=0, le=366, decimal_places=4, allow_inf_nan=False)]
VatKey = Literal["normal", "intermediaire", "reduit", "particulier"]


class CalcError(Exception):
    """A calculation refused: a missing rate, an outdated table or inconsistent inputs."""


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Marge(_In):
    """Margin, mark-up rate, margin rate and multiplier from a price and a cost."""

    operation: Literal["marge"]
    prix_vente_ht: PositiveAmount = Field(description="Prix de vente HT, en €")
    cout_achat_ht: PositiveAmount = Field(description="Coût d'achat HT, en €")


class PrixDeVente(_In):
    """The selling price HT that reaches a target margin rate, mark-up rate or multiplier."""

    operation: Literal["prix_de_vente"]
    cout_achat_ht: PositiveAmount = Field(description="Coût d'achat HT, en €")
    cible: Literal["taux_marge", "taux_marque", "coefficient"] = Field(
        description="Cible : taux de marge (sur le coût), taux de marque (sur le prix) ou "
        "coefficient multiplicateur HT/HT (prix de vente HT ÷ coût d'achat HT)"
    )
    valeur: Rate = Field(
        description="Valeur de la cible en fraction : 0.4 pour 40 % (taux de marge ≤ 10, taux "
        "de marque < 1) ; coefficient 1.8"
    )

    @model_validator(mode="after")
    def _below_the_price(self) -> PrixDeVente:
        if self.cible == "taux_marque" and self.valeur >= 1:
            raise ValueError("un taux de marque est inférieur à 1 (100 % du prix)")
        if self.cible == "taux_marge" and self.valeur > MAX_MARGIN_RATE:
            raise ValueError("taux de marge en fraction : 0.4 pour 40 % (1 000 % au plus)")
        return self


class Tva(_In):
    """HT to TTC or TTC to HT at a rate of ``config/business.yaml``."""

    operation: Literal["tva"]
    montant: Annotated[
        Decimal, Field(gt=0, le=MAX_AMOUNT, decimal_places=2, allow_inf_nan=False)
    ] = Field(description="Montant de départ, en €, au centime")
    sens: Literal["ht_vers_ttc", "ttc_vers_ht"]
    taux: VatKey = Field(
        description="Taux de la configuration : normal, intermediaire, reduit ou particulier"
    )


class SeuilRentabilite(_In):
    """Break-even revenue and day from the revenue, variable costs and fixed costs of a year."""

    operation: Literal["seuil_rentabilite"]
    chiffre_affaires_ht: PositiveAmount = Field(description="Chiffre d'affaires HT annuel, en €")
    charges_variables_ht: Amount = Field(description="Charges variables HT annuelles, en €")
    charges_fixes: Amount = Field(description="Charges fixes annuelles, en €")

    @model_validator(mode="after")
    def _positive_contribution(self) -> SeuilRentabilite:
        if self.charges_variables_ht >= self.chiffre_affaires_ht:
            raise ValueError(
                "marge sur coûts variables nulle ou négative : aucun seuil de rentabilité"
            )
        return self


class CacLtv(_In):
    """Customer acquisition cost, lifetime value on gross margin and their ratio."""

    operation: Literal["cac_ltv"]
    depenses_acquisition: PositiveAmount = Field(
        description="Dépenses d'acquisition de la période, en €"
    )
    nouveaux_clients: int = Field(
        ge=1, le=1_000_000_000, strict=True, description="Nouveaux clients de la même période"
    )
    panier_moyen_ht: PositiveAmount = Field(description="Panier moyen HT, en €")
    achats_par_an: PerYear = Field(description="Nombre moyen d'achats par client et par an")
    duree_vie_ans: Years = Field(description="Durée de vie moyenne d'un client, en années")
    taux_marge_brute: Annotated[
        Decimal, Field(gt=0, le=1, decimal_places=6, allow_inf_nan=False)
    ] = Field(description="Marge brute en part du chiffre d'affaires HT : 0.6 pour 60 %")


class Variation(_In):
    """Change between two values, as a share of the first."""

    operation: Literal["variation"]
    valeur_initiale: PositiveAmount
    valeur_finale: Amount


class Tcac(_In):
    """Compound annual growth rate between two values over a number of years."""

    operation: Literal["tcac"]
    valeur_initiale: PositiveAmount
    valeur_finale: PositiveAmount
    annees: Years = Field(description="Durée en années entre les deux valeurs (12 mois = 1)")


Request = Annotated[
    Marge | PrixDeVente | Tva | SeuilRentabilite | CacLtv | Variation | Tcac,
    Field(discriminator="operation"),
]
OPERATIONS = ("marge", "prix_de_vente", "tva", "seuil_rentabilite", "cac_ltv", "variation", "tcac")


class BizCalc(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: str
    inputs: list[Figure] = Field(description="Paramètres repris tels que reçus")
    results: list[Figure]
    formulas: list[str]
    conventions: list[str] = Field(description="Arrondis et conventions appliqués, rien d'autre")
    source: str | None = Field(description="Article qui fixe le taux de TVA employé")
    notice: str = NOTICE


def _eur(figure_id: str, value: Decimal) -> Figure:
    return amount(figure_id, value, "EUR")


def _pct(figure_id: str, fraction: Decimal) -> Figure:
    return percent(figure_id, float(fraction))


DISPLAY = "affichages arrondis au demi supérieur (2 décimales) ; valeurs non arrondies"


def _marge(req: Marge) -> BizCalc:
    price, cost = req.prix_vente_ht, req.cout_achat_ht
    margin = price - cost
    return BizCalc(
        operation=req.operation,
        inputs=[_eur("entree.prix_vente_ht", price), _eur("entree.cout_achat_ht", cost)],
        results=[
            _eur("resultat.marge_brute", margin),
            _pct("resultat.taux_marge", margin / cost),
            _pct("resultat.taux_marque", margin / price),
            plain("resultat.coefficient", float(price / cost), "coefficient", 4),
        ],
        formulas=[
            "marge brute = prix de vente HT − coût d'achat HT",
            "taux de marge = marge brute ÷ coût d'achat HT",
            "taux de marque = marge brute ÷ prix de vente HT",
            "coefficient multiplicateur = prix de vente HT ÷ coût d'achat HT",
        ],
        conventions=[DISPLAY],
        source=None,
    )


def _prix(req: PrixDeVente) -> BizCalc:
    cost, target = req.cout_achat_ht, req.valeur
    if req.cible == "taux_marge":
        price = cost * (1 + target)
        given = _pct("entree.taux_marge", target)
        formula = "prix de vente HT = coût d'achat HT × (1 + taux de marge)"
    elif req.cible == "taux_marque":
        price = cost / (1 - target)
        given = _pct("entree.taux_marque", target)
        formula = "prix de vente HT = coût d'achat HT ÷ (1 − taux de marque)"
    else:
        price = cost * target
        given = plain("entree.coefficient", float(target), "coefficient", 4)
        formula = "prix de vente HT = coût d'achat HT × coefficient multiplicateur"
    conventions = [DISPLAY]
    if req.cible == "coefficient" and target < 1:
        conventions.append("coefficient inférieur à 1 : prix de vente sous le coût d'achat")
    return BizCalc(
        operation=req.operation,
        inputs=[_eur("entree.cout_achat_ht", cost), given],
        results=[_eur("resultat.prix_vente_ht", price), _eur("resultat.marge_brute", price - cost)],
        formulas=[formula, "marge brute = prix de vente HT − coût d'achat HT"],
        conventions=conventions,
        source=None,
    )


def _rate(vat: VatConfig | None, key: VatKey, today: date) -> tuple[Decimal, str, date]:
    if vat is None:
        raise CalcError("table de TVA absente : config/business.yaml non lu")
    if isinstance(vat.valid_until, str):
        raise CalcError(f"business.yaml › vat.valid_until = {vat.valid_until} (R7)")
    if today > vat.valid_until:
        raise CalcError(
            f"table de TVA valable jusqu'au {vat.valid_until:%d/%m/%Y} : taux à relire dans le "
            "CIBS avant tout calcul (R7, R10)"
        )
    entry = vat.rates[key]
    if isinstance(entry.rate, str):
        raise CalcError(
            f"taux {key} non vérifié : business.yaml › vat.rates.{key}.rate = {entry.rate} (R7)"
        )
    return entry.rate, entry.source, vat.valid_until


def _tva(req: Tva, vat: VatConfig | None, today: date) -> BizCalc:
    rate, source, valid_until = _rate(vat, req.taux, today)
    if req.sens == "ht_vers_ttc":
        ht = req.montant
        tax = (ht * rate).quantize(CENT, ROUND_HALF_UP)
        ttc = ht + tax
        formulas = ["TVA = montant HT × taux, arrondie au centime", "TTC = HT + TVA"]
    else:
        ttc = req.montant
        ht = (ttc / (1 + rate)).quantize(CENT, ROUND_HALF_UP)
        tax = ttc - ht
        formulas = ["HT = TTC ÷ (1 + taux), arrondi au centime", "TVA = TTC − HT"]
    conventions = [
        "montants arrondis au centime, au demi supérieur",
        f"taux de config/business.yaml ({req.taux}), table valable jusqu'au {valid_until:%d/%m/%Y}",
    ]
    if (ht * rate).quantize(CENT, ROUND_HALF_UP) != tax:
        conventions.append("aucun montant HT ne redonne ce TTC au centime : TVA = TTC − HT")
    return BizCalc(
        operation=req.operation,
        inputs=[_eur("entree.montant", req.montant), _pct("entree.taux_tva", rate)],
        results=[_eur("resultat.ht", ht), _eur("resultat.tva", tax), _eur("resultat.ttc", ttc)],
        formulas=formulas,
        conventions=conventions,
        source=source,
    )


def _seuil(req: SeuilRentabilite) -> BizCalc:
    revenue, fixed = req.chiffre_affaires_ht, req.charges_fixes
    contribution = revenue - req.charges_variables_ht
    rate = contribution / revenue
    threshold = fixed / rate
    day = threshold / revenue * COMMERCIAL_YEAR_DAYS
    conventions = [DISPLAY, f"année commerciale de {COMMERCIAL_YEAR_DAYS} jours, ventes régulières"]
    if threshold > revenue:
        conventions.append("chiffre d'affaires sous le seuil : point mort au-delà de l'exercice")
    return BizCalc(
        operation=req.operation,
        inputs=[
            _eur("entree.chiffre_affaires_ht", revenue),
            _eur("entree.charges_variables_ht", req.charges_variables_ht),
            _eur("entree.charges_fixes", fixed),
        ],
        results=[
            _eur("resultat.marge_sur_couts_variables", contribution),
            _pct("resultat.taux_marge_sur_couts_variables", rate),
            _eur("resultat.seuil_rentabilite", threshold),
            plain("resultat.point_mort", float(day), "jours", 1, show_unit=True),
            _eur("resultat.marge_de_securite", revenue - threshold),
        ],
        formulas=[
            "marge sur coûts variables = chiffre d'affaires HT − charges variables HT",
            "taux de marge sur coûts variables = marge sur coûts variables ÷ chiffre d'affaires HT",
            "seuil de rentabilité = charges fixes ÷ taux de marge sur coûts variables",
            f"point mort = seuil de rentabilité ÷ chiffre d'affaires HT × {COMMERCIAL_YEAR_DAYS}",
            "marge de sécurité = chiffre d'affaires HT − seuil de rentabilité",
        ],
        conventions=conventions,
        source=None,
    )


def _cac_ltv(req: CacLtv) -> BizCalc:
    cac = req.depenses_acquisition / req.nouveaux_clients
    ltv = req.panier_moyen_ht * req.achats_par_an * req.duree_vie_ans * req.taux_marge_brute
    return BizCalc(
        operation=req.operation,
        inputs=[
            _eur("entree.depenses_acquisition", req.depenses_acquisition),
            count("entree.nouveaux_clients", req.nouveaux_clients, "clients"),
            _eur("entree.panier_moyen_ht", req.panier_moyen_ht),
            plain("entree.achats_par_an", float(req.achats_par_an), "achats par an"),
            plain("entree.duree_vie_ans", float(req.duree_vie_ans), "ans", show_unit=True),
            _pct("entree.taux_marge_brute", req.taux_marge_brute),
        ],
        results=[
            _eur("resultat.cac", cac),
            _eur("resultat.ltv", ltv),
            plain("resultat.ltv_sur_cac", float(ltv / cac), "rapport"),
        ],
        formulas=[
            "CAC = dépenses d'acquisition ÷ nouveaux clients",
            "LTV = panier moyen HT × achats par an × durée de vie × taux de marge brute",
            "rapport LTV/CAC = LTV ÷ CAC",
        ],
        conventions=[DISPLAY, "LTV sur la marge brute, sans actualisation"],
        source=None,
    )


def _variation(req: Variation) -> BizCalc:
    start, end = req.valeur_initiale, req.valeur_finale
    return BizCalc(
        operation=req.operation,
        inputs=[_eur("entree.valeur_initiale", start), _eur("entree.valeur_finale", end)],
        results=[_pct("resultat.variation", (end - start) / start)],
        formulas=["variation = (valeur finale − valeur initiale) ÷ valeur initiale"],
        conventions=[DISPLAY],
        source=None,
    )


def _tcac(req: Tcac) -> BizCalc:
    start, end = req.valeur_initiale, req.valeur_finale
    growth = (end / start) ** (1 / req.annees) - 1
    conventions = [DISPLAY, "calcul décimal à 28 chiffres significatifs"]
    if req.annees < 1:
        conventions.append("durée inférieure à un an : taux extrapolé sur une année")
    return BizCalc(
        operation=req.operation,
        inputs=[
            _eur("entree.valeur_initiale", start),
            _eur("entree.valeur_finale", end),
            plain("entree.annees", float(req.annees), "ans", show_unit=True),
        ],
        results=[_pct("resultat.tcac", growth)],
        formulas=["TCAC = (valeur finale ÷ valeur initiale) ^ (1 ÷ années) − 1"],
        conventions=conventions,
        source=None,
    )


def calculate(request: Request, *, vat: VatConfig | None = None, today: date) -> BizCalc:
    """The operation of ``request``; ``vat`` is read only by the VAT operation.

    The decimal context is local (28 digits), so no other module changes the arithmetic; a result
    too large or too small to show is refused with a message instead of an empty error."""
    with localcontext(prec=28):
        try:
            return _dispatch(request, vat, today)
        except (ArithmeticError, ValueError):
            raise CalcError(
                "résultat hors des bornes affichables : vérifier les ordres de grandeur"
            ) from None


def _dispatch(request: Request, vat: VatConfig | None, today: date) -> BizCalc:
    if isinstance(request, Marge):
        return _marge(request)
    if isinstance(request, PrixDeVente):
        return _prix(request)
    if isinstance(request, Tva):
        return _tva(request, vat, today)
    if isinstance(request, SeuilRentabilite):
        return _seuil(request)
    if isinstance(request, CacLtv):
        return _cac_ltv(request)
    if isinstance(request, Variation):
        return _variation(request)
    return _tcac(request)
