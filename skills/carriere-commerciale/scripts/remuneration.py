#!/usr/bin/env python3
"""Ce que rapporte vraiment un poste de commercial : fixe + variable selon l'objectif atteint, et comparaison d'offres.

    python remuneration.py calcul --fixe 32000 --variable 12000
    python remuneration.py calcul --fixe 32000 --variable 12000 --atteinte 50,80,100,130 --seuil 50 \\
        --accelerateur 1.5 --plafond 200
    python remuneration.py comparer "Startup A;30000;15000;45" "Éditeur B;36000;8000;75"
    … --net 22          # ajoute une estimation du net avant impôt (taux de cotisations en %, à confirmer)
    … --json

calcul : revenu annuel brut pour plusieurs taux d'atteinte de l'objectif (le quota).
  --fixe          salaire fixe brut annuel
  --variable      variable « à objectif » : ce qui est versé à 100 % de l'objectif
  --atteinte      taux d'atteinte à simuler, en % (défaut : 50,75,100,125,150)
  --seuil         en dessous de ce taux, aucun variable (défaut : 0)
  --accelerateur  au-delà de 100 %, chaque point compte ce multiple (1,5 → 110 % d'objectif paie 115 % du variable)
  --plafond       variable maximal, en % du variable à objectif (défaut : aucun plafond)

comparer : plusieurs offres « nom;fixe;variable;atteinte probable en % ». L'atteinte probable, c'est la part de
l'objectif que les commerciaux de l'équipe font vraiment : à demander en entretien (« combien de commerciaux ont
atteint leur objectif l'an dernier ? »). Un gros variable avec un objectif que personne n'atteint vaut moins qu'un
fixe solide.

Les montants sont ceux de l'offre : le script ne connaît ni la convention collective, ni l'impôt, ni les primes
hors variable. Bibliothèque standard uniquement, aucun accès réseau."""
from __future__ import annotations

import argparse
import json
import sys


def montant(texte: str) -> float:
    t = str(texte).lower().replace(" ", "").replace(" ", "").replace(" ", "").replace("€", "")
    mult = 1000 if t.endswith("k") else 1
    t = t.rstrip("k").replace(",", ".")
    try:
        v = float(t) * mult
    except ValueError:
        raise SystemExit(f"montant illisible : « {texte} » (exemples : 32000, 32 000, 32k)")
    if v < 0:
        raise SystemExit(f"montant négatif : « {texte} »")
    return v


def taux(texte: str) -> float:
    try:
        return float(str(texte).replace("%", "").replace(",", ".").strip())
    except ValueError:
        raise SystemExit(f"pourcentage illisible : « {texte} »")


def variable_verse(cible: float, atteinte: float, seuil: float = 0.0, accelerateur: float = 1.0,
                   plafond: float | None = None) -> float:
    """Variable versé pour un taux d'atteinte (en %) : proportionnel jusqu'à 100 %, accéléré au-delà, rien sous le
    seuil, borné par le plafond (en % du variable à objectif)."""
    if atteinte < seuil:
        return 0.0
    part = atteinte if atteinte <= 100 else 100 + (atteinte - 100) * accelerateur
    if plafond is not None:
        part = min(part, plafond)
    return cible * part / 100


def scenario(fixe, cible, atteinte, seuil=0.0, accelerateur=1.0, plafond=None, net=None) -> dict:
    var = variable_verse(cible, atteinte, seuil, accelerateur, plafond)
    total = fixe + var
    d = {"atteinte": atteinte, "fixe": fixe, "variable": var, "total": total, "par_mois": total / 12}
    if net:
        d["net_estime"] = total * (1 - net / 100)
        d["net_par_mois"] = d["net_estime"] / 12
    return d


def euros(v: float) -> str:
    return f"{v:,.0f} €".replace(",", " ")


def cmd_calcul(a) -> int:
    fixe, cible = montant(a.fixe), montant(a.variable)
    niveaux = [taux(x) for x in a.atteinte.split(",") if x.strip()]
    plafond = taux(a.plafond) if a.plafond else None
    lignes = [scenario(fixe, cible, x, taux(a.seuil), a.accelerateur, plafond, a.net) for x in niveaux]
    ote = fixe + cible
    info = {"fixe": fixe, "variable_a_objectif": cible, "package_a_objectif": ote,
            "part_fixe": 100 * fixe / ote if ote else None, "scenarios": lignes}
    if a.json:
        print(json.dumps(info, ensure_ascii=False, indent=1))
        return 0
    print(f"Package à objectif (fixe + variable à 100 %) : {euros(ote)} brut par an — "
          f"{info['part_fixe']:.0f} % de fixe, {100 - info['part_fixe']:.0f} % de variable.\n")
    entete = f"{'objectif atteint':>16} {'fixe':>10} {'variable':>10} {'total brut/an':>14} {'brut/mois':>10}"
    print(entete + (f" {'net estimé/mois':>16}" if a.net else ""))
    for l in lignes:
        print(f"{l['atteinte']:>15.0f} % {euros(l['fixe']):>10} {euros(l['variable']):>10} {euros(l['total']):>14} "
              f"{euros(l['par_mois']):>10}" + (f" {euros(l['net_par_mois']):>16}" if a.net else ""))
    print(f"\nLe fixe, c'est ce qui tombe même un mauvais mois : {euros(fixe / 12)} brut par mois.")
    if a.net:
        print(f"Net estimé avec {a.net:g} % de cotisations : un ordre de grandeur, pas un bulletin de paie.")
    return 0


def offre(texte: str) -> dict:
    morceaux = [m.strip() for m in texte.split(";")]
    if len(morceaux) != 4:
        raise SystemExit(f"offre « {texte} » : attendu « nom;fixe;variable;atteinte probable en % »")
    nom, fixe, var, atteinte = morceaux
    return {"nom": nom, "fixe": montant(fixe), "variable": montant(var), "atteinte": taux(atteinte)}


def cmd_comparer(a) -> int:
    offres = [offre(o) for o in a.offres]
    for o in offres:
        fixe, cible = o["fixe"], o["variable"]
        o["package_a_objectif"] = fixe + cible
        o["mauvaise_annee"] = scenario(fixe, cible, min(o["atteinte"], 50))["total"]
        o.update(scenario(fixe, cible, o["atteinte"], net=a.net))
        o["variable_a_objectif"] = cible
    offres.sort(key=lambda o: -o["total"])
    if a.json:
        print(json.dumps(offres, ensure_ascii=False, indent=1))
        return 0
    print(f"{'offre':<20} {'package annoncé':>15} {'atteinte':>9} {'attendu brut/an':>16} {'année à 50 %':>13}")
    for o in offres:
        print(f"{o['nom'][:20]:<20} {euros(o['package_a_objectif']):>15} {o['atteinte']:>8.0f} % {euros(o['total']):>16} "
              f"{euros(o['mauvaise_annee']):>13}")
    meilleure, annonce = offres[0], max(offres, key=lambda o: o["package_a_objectif"])
    print(f"\nLa plus intéressante si l'atteinte annoncée est juste : {meilleure['nom']} ({euros(meilleure['total'])}).")
    if annonce is not meilleure:
        print(f"Attention : {annonce['nom']} affiche le plus gros package, mais rapporte moins avec l'atteinte donnée.")
    print("« Année à 50 % » : ce qui reste si l'objectif est à moitié atteint. Regarde aussi la formation, la marque de "
          "l'entreprise sur ton CV et la promotion possible : ils comptent pour l'échelon suivant.")
    return 0


def main(argv=None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    commun = argparse.ArgumentParser(add_help=False)
    commun.add_argument("--net", type=float, help="taux de cotisations salariales en %, pour un net estimé")
    commun.add_argument("--json", action="store_true")
    p = argparse.ArgumentParser(description="Rémunération d'un commercial : fixe, variable, offres.")
    sous = p.add_subparsers(dest="commande")
    c = sous.add_parser("calcul", parents=[commun])
    c.add_argument("--fixe", required=True)
    c.add_argument("--variable", required=True)
    c.add_argument("--atteinte", default="50,75,100,125,150")
    c.add_argument("--seuil", default="0")
    c.add_argument("--accelerateur", type=float, default=1.0)
    c.add_argument("--plafond")
    k = sous.add_parser("comparer", parents=[commun])
    k.add_argument("offres", nargs="+", help="« nom;fixe;variable;atteinte probable en % »")
    a = p.parse_args(argv)
    if not a.commande:
        print(__doc__)
        return 1
    if a.net is not None and not 0 < a.net < 60:
        raise SystemExit("--net : un taux entre 0 et 60 %")
    return cmd_calcul(a) if a.commande == "calcul" else cmd_comparer(a)


if __name__ == "__main__":
    sys.exit(main())
