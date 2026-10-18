#!/usr/bin/env python3
"""Économie unitaire d'une commande : marge de contribution, prix d'équilibre et prix plancher, ventes nécessaires
pour couvrir les coûts fixes (et se payer), marge par heure investie.

Aucun taux fiscal ou social n'est codé en dur : ils changent, l'utilisateur les fournit (URSSAF, impots.gouv.fr).
Les cotisations portent sur le chiffre d'affaires encaissé, port facturé compris, net des remboursements.
Bibliothèque standard uniquement. Aide : python scripts/unit_economics.py --aide"""
from __future__ import annotations

import json
import math
import sys

AIDE = """
Usage :
  python scripts/unit_economics.py --prix <TTC> --cout <€> [options]

Montants en euros, pourcentages en % (virgule ou point acceptés).
  --prix             Prix payé par le client, TTC (obligatoire)
  --cout             Coût d'achat du produit (obligatoire)
  --port-client      Frais de port facturés au client, TTC (défaut 0) : ils entrent dans le CA, les frais et commissions
  --livraison        Livraison payée au fournisseur ou au transporteur, par commande (défaut 0)
  --emballage        Emballage et consommables, par commande (défaut 0)
  --frais-pct        Frais de paiement, part variable en % du TTC (défaut 0)
  --frais-fixe       Frais de paiement, part fixe par commande (défaut 0)
  --commission-pct   Commission du canal (marketplace, affiliation) en % du TTC (défaut 0)
  --retours-pct      Provision retours et casse en % du CA HT : ventes remboursées (défaut 0)
  --cotisations-pct  Prélèvements sur le CA en % : cotisations + formation + chambre (+ versement libératoire),
                     taux en vigueur URSSAF ; calculés sur le CA net des remboursements (défaut 0)
  --tva-pct          TVA en % ; 0 en franchise en base (défaut 0)
  --marge-cible      Marge de contribution visée par commande, pour le prix plancher (défaut 0)
  --fixes-mois       Coûts fixes du mois (abonnement, domaine, apps) : donne le seuil de rentabilité (défaut 0)
  --remuneration-mois  Rémunération visée par mois : ventes nécessaires pour couvrir fixes + rémunération (défaut 0)
  --heures           Heures investies par vente (contenu, messages, préparation) : donne la marge par heure
  --json             Sortie JSON
  --aide             Afficher cette aide

Exemple (valeurs fictives) :
  python scripts/unit_economics.py --prix 39,90 --cout 12 --livraison 5,50 --frais-pct 2,9 --frais-fixe 0,30 \\
      --retours-pct 3 --cotisations-pct 12 --marge-cible 8 --fixes-mois 39 --heures 0,5
"""

OPTIONS = {"prix", "cout", "port-client", "livraison", "emballage", "frais-pct", "frais-fixe", "commission-pct",
           "retours-pct", "cotisations-pct", "tva-pct", "marge-cible", "fixes-mois", "remuneration-mois", "heures"}


def lire_args(argv: list) -> dict:
    args, i = {}, 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            cle = a[2:]
            suivant = argv[i + 1] if i + 1 < len(argv) else None
            if suivant is None or suivant.startswith("--"):
                args[cle] = True
            else:
                args[cle] = suivant
                i += 1
        i += 1
    return args


def nombre(args: dict, cle: str, defaut=None) -> float:
    if cle not in args:
        return defaut
    try:
        v = float(str(args[cle]).replace(",", ".").replace(" ", ""))
    except ValueError:
        v = math.nan
    if not math.isfinite(v) or v < 0:
        raise ValueError(f"valeur invalide pour --{cle} : {args[cle]}")
    return v


def calculer(p: dict) -> dict:
    t = p["tva_pct"] / 100
    r, s = p["retours_pct"] / 100, p["cotisations_pct"] / 100
    encaisse_ttc = p["prix_ttc"] + p["port_client"]  # ce que paie le client : produit + port facturé
    ca_ht = encaisse_ttc / (1 + t)
    frais_paiement = encaisse_ttc * p["frais_pct"] / 100 + p["frais_fixe"]
    commission = encaisse_ttc * p["commission_pct"] / 100
    retours = ca_ht * r
    cotisations = ca_ht * (1 - r) * s  # un remboursement diminue le CA déclaré
    couts_fixes = p["cout"] + p["livraison"] + p["emballage"]
    marge = ca_ht - couts_fixes - frais_paiement - commission - retours - cotisations
    # CA HT pour une marge M : CA_HT × [1 − (1 + t)(frais% + commission%) − r − s(1 − r)]
    #                              = coûts par commande + frais fixes + M ; le prix produit = CA − port facturé
    facteur = 1 - (1 + t) * (p["frais_pct"] + p["commission_pct"]) / 100 - r - s * (1 - r)
    port_ht = p["port_client"] / (1 + t)
    plancher_ht = (couts_fixes + p["frais_fixe"] + p["marge_cible"]) / facteur - port_ht if facteur > 0 else math.nan
    equilibre_ht = (couts_fixes + p["frais_fixe"]) / facteur - port_ht if facteur > 0 else math.nan
    fixes = p["fixes_mois"] + p["remuneration_mois"]
    seuil = math.ceil(fixes / marge) if marge > 0 and fixes > 0 else None
    par_heure = marge / p["heures"] if p.get("heures") else None
    return {
        "prix_ttc": p["prix_ttc"], "port_client_ttc": p["port_client"], "ca_ht": ca_ht,
        "couts_par_commande": couts_fixes, "frais_paiement": frais_paiement, "commission": commission,
        "retours": retours, "cotisations": cotisations, "marge": marge,
        "taux_marge": marge / ca_ht if ca_ht > 0 else math.nan,
        "prix_equilibre_ttc": max(equilibre_ht, 0.0) * (1 + t) if math.isfinite(equilibre_ht) else math.nan,
        "prix_plancher_ttc": max(plancher_ht, 0.0) * (1 + t) if math.isfinite(plancher_ht) else math.nan,
        "marge_cible": p["marge_cible"], "commandes_par_mois": seuil, "marge_par_heure": par_heure,
    }


def euros(v) -> str:
    if v is None or not math.isfinite(v):
        return "impossible (pourcentages ≥ 100 %)"
    signe = "-" if v < 0 else ""
    entier, dec = f"{abs(v):.2f}".split(".")
    groupes = []
    while entier:
        groupes.insert(0, entier[-3:])
        entier = entier[:-3]
    return f"{signe}{' '.join(groupes)},{dec} €"


def pourcent(v) -> str:
    return f"{v * 100:.1f} %".replace(".", ",") if math.isfinite(v) else "n/a"


def main(argv=None) -> int:
    args = lire_args(sys.argv[1:] if argv is None else argv)
    if args.get("aide") or args.get("help") or "prix" not in args or "cout" not in args:
        print(AIDE)
        return 0 if (args.get("aide") or args.get("help")) else 1
    inconnues = sorted(k for k in args if k not in OPTIONS | {"json", "aide", "help"})
    if inconnues:
        print("Erreur : option inconnue " + ", ".join("--" + k for k in inconnues), file=sys.stderr)
        return 1
    try:
        p = {"prix_ttc": nombre(args, "prix"), "cout": nombre(args, "cout"),
             "port_client": nombre(args, "port-client", 0.0),
             "livraison": nombre(args, "livraison", 0.0), "emballage": nombre(args, "emballage", 0.0),
             "frais_pct": nombre(args, "frais-pct", 0.0), "frais_fixe": nombre(args, "frais-fixe", 0.0),
             "commission_pct": nombre(args, "commission-pct", 0.0), "retours_pct": nombre(args, "retours-pct", 0.0),
             "cotisations_pct": nombre(args, "cotisations-pct", 0.0), "tva_pct": nombre(args, "tva-pct", 0.0),
             "marge_cible": nombre(args, "marge-cible", 0.0), "fixes_mois": nombre(args, "fixes-mois", 0.0),
             "remuneration_mois": nombre(args, "remuneration-mois", 0.0),
             "heures": nombre(args, "heures", None)}
    except ValueError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1

    alertes = []
    if "cotisations-pct" not in args:
        alertes.append("Cotisations non renseignées : relève le taux en vigueur sur autoentrepreneur.urssaf.fr.")
    if "tva-pct" not in args:
        alertes.append("TVA supposée à 0 % (franchise en base) : vérifie ta situation sur impots.gouv.fr.")
    if "frais-pct" not in args and "frais-fixe" not in args:
        alertes.append("Frais de paiement non renseignés : reprends les tarifs actuels de ton prestataire.")
    r = calculer(p)

    if args.get("json"):
        def propre(v):
            return None if isinstance(v, float) and not math.isfinite(v) else v
        print(json.dumps({"entrees": p, "resultats": {k: propre(v) for k, v in r.items()}, "alertes": alertes},
                         ensure_ascii=False, indent=2))
        return 0

    lignes = [("Prix TTC", euros(r["prix_ttc"]))]
    if p["port_client"]:
        lignes.append(("Port facturé au client TTC", euros(p["port_client"])))
    lignes += [
        ("Chiffre d'affaires HT de la commande", euros(r["ca_ht"])),
        ("Produit + livraison + emballage", euros(r["couts_par_commande"])),
        ("Frais de paiement", euros(r["frais_paiement"])),
        ("Commission du canal", euros(r["commission"])),
        ("Provision retours", euros(r["retours"])),
        ("Cotisations sociales", euros(r["cotisations"])),
        ("Marge de contribution / commande", euros(r["marge"])),
        ("Taux de marge de contribution (sur CA HT)", pourcent(r["taux_marge"])),
        ("Prix TTC d'équilibre (marge = 0)", euros(r["prix_equilibre_ttc"])),
        (f"Prix TTC plancher (marge = {euros(r['marge_cible'])})", euros(r["prix_plancher_ttc"])),
    ]
    if p["fixes_mois"] > 0 or p["remuneration_mois"] > 0:
        seuil = r["commandes_par_mois"]
        objet = " + ".join(x for x in (f"{euros(p['fixes_mois'])} de coûts fixes" if p["fixes_mois"] else "",
                                       f"{euros(p['remuneration_mois'])} de rémunération"
                                       if p["remuneration_mois"] else "") if x)
        lignes.append((f"Commandes par mois pour couvrir {objet}",
                       str(seuil) if seuil is not None else "jamais (marge ≤ 0)"))
    if r["marge_par_heure"] is not None:
        lignes.append(("Marge par heure investie", euros(r["marge_par_heure"])))
    largeur = max(len(libelle) for libelle, _ in lignes)
    print("\nÉconomie unitaire par commande\n")
    for libelle, valeur in lignes:
        print(f"{libelle.ljust(largeur)}  {valeur}")
    if r["marge"] < 0:
        print("\n⚠ Marge négative : chaque vente fait perdre de l'argent.")
    if alertes:
        print("\nÀ vérifier :")
        for a in alertes:
            print(f"- {a}")
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
