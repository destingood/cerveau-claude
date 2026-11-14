#!/usr/bin/env python3
"""Diagnostic d'une île Fortnite publiée : où l'entonnoir fuit, et si un test A/B de miniature est tranché.

    # Les chiffres se lisent dans le portail créateur (Analytics), les références dans son menu Benchmarks
    # (la ligne pointillée : médiane des 10 % d'îles du genre qui ont le plus de temps de jeu).
    python diagnostic.py entonnoir --impressions 48000 --clics 1900 --rebond2 22 --rebond5 41 --rebond10 58 \\
        --session 11.5 --j1 9 --j7 3 --ref-ctr 5.2 --ref-rebond5 30 --ref-session 16 --ref-j1 14 --ref-j7 6
    python diagnostic.py entonnoir --j1 9 --j7 3 --reference niche.json    # niche.json : tendances.py comparer … --json
    python diagnostic.py ab --a 12000:540 --b 11800:610                   # impressions:clics de chaque miniature
    … --json

Tous les taux sont en pourcentage (4,2 ou 4.2 pour 4,2 %), la durée de session en minutes.

L'entonnoir suit la lecture qu'Epic donne de ses propres mesures : taux de clic → rebond à 2 min → rebond à 5 min →
rebond à 10 min et durée de session → retour à J1 → retour à J7. Le goulot est la première étape nettement sous sa
référence (écart relatif de plus de 10 %) ; sans référence, aucun verdict : le script n'invente pas de seuil.
Le test A/B reprend le seuil d'Epic (90 % de confiance, p < 0,1) avec un test de deux proportions : le calcul exact
d'Epic n'est pas publié, le résultat affiché sur sa page de publication fait foi.
Bibliothèque standard uniquement, aucun accès réseau."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

MARGE = 0.10  # écart relatif à la référence en dessous duquel on ne conclut pas
# (clé, libellé, sens : +1 = plus haut est mieux, lecture d'Epic quand l'étape est sous la référence, quoi faire)
ETAPES = [
    ("ctr", "Taux de clic", +1,
     "la miniature et le titre n'attirent pas le clic",
     "refaire la miniature et la tester en A/B (references/03-fiche-ile.md) ; relire le titre avec fiche.py"),
    ("rebond2", "Rebond à 2 min", -1,
     "Epic : miniature « pas représentative » de l'île, ou problème technique à l'entrée",
     "aligner la miniature sur ce qu'on joue vraiment ; mesurer le temps de chargement et la file d'attente"),
    ("rebond5", "Rebond à 5 min", -1,
     "Epic : « l'expérience initiale n'accroche pas »",
     "raccourcir le chemin jusqu'au premier combat ; lobby vide et attente (references/04-retention-combat.md)"),
    ("rebond10", "Rebond à 10 min", -1,
     "Epic : la « boucle de jeu » ne retient pas",
     "donner une raison de rejouer la manche suivante : équilibrage, variété des manches, score visible"),
    ("session", "Durée de session", +1,
     "les joueurs repartent plus tôt que dans les îles de référence",
     "même chantier que le rebond à 10 min : la boucle de jeu, puis la variété"),
    ("j1", "Retour à J1", +1,
     "les joueurs ne reviennent pas le lendemain",
     "progression qui se garde d'un jour à l'autre, parties entre amis, mise à jour annoncée dans l'île"),
    ("j7", "Retour à J7", +1,
     "les joueurs ne reviennent pas la semaine suivante",
     "rythme de mises à jour, nouveaux modes ou zones, classement de la semaine"),
]


def nombre(texte) -> float | None:
    if texte is None:
        return None
    try:
        return float(str(texte).replace("%", "").replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        raise SystemExit(f"valeur illisible : « {texte} » (attendu un nombre, 4,2 ou 4.2)")


def wilson(succes: float, total: float, z: float = 1.645) -> tuple:
    """Intervalle de confiance à 90 % d'un taux (méthode de Wilson) → (bas, haut) en pourcentage."""
    if total <= 0:
        return (0.0, 0.0)
    p = succes / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    demi = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return (max(0.0, (centre - demi) * 100), min(100.0, (centre + demi) * 100))


def test_ab(ia: float, ca: float, ib: float, cb: float) -> dict:
    """Test bilatéral de deux proportions (z) : la miniature B a-t-elle un taux de clic différent de A ?"""
    pa, pb = ca / ia, cb / ib
    commun = (ca + cb) / (ia + ib)
    ecart_type = math.sqrt(commun * (1 - commun) * (1 / ia + 1 / ib))
    z = (pb - pa) / ecart_type if ecart_type else 0.0
    p = math.erfc(abs(z) / math.sqrt(2))
    return {"ctr_a": pa * 100, "ctr_b": pb * 100, "ecart_relatif": ((pb / pa - 1) * 100) if pa else None,
            "z": z, "p": p, "tranche": p < 0.1, "gagnante": ("B" if pb > pa else "A") if p < 0.1 else None,
            "intervalle_a": wilson(ca, ia), "intervalle_b": wilson(cb, ib)}


def entonnoir(valeurs: dict, refs: dict, impressions=None, clics=None) -> dict:
    lignes, goulot = [], None
    for cle, libelle, sens, lecture, action in ETAPES:
        v, ref = valeurs.get(cle), refs.get(cle)
        ligne = {"cle": cle, "etape": libelle, "valeur": v, "reference": ref, "ecart": None, "etat": "sans chiffre"}
        if v is not None and ref:
            ecart = (v - ref) / ref * sens  # négatif = moins bien que la référence
            ligne["ecart"] = ecart * 100
            ligne["etat"] = "sous la référence" if ecart < -MARGE else "au niveau" if ecart < MARGE else "au-dessus"
            if ligne["etat"] == "sous la référence" and goulot is None:
                goulot = {**ligne, "lecture": lecture, "action": action}
        elif v is not None:
            ligne["etat"] = "sans référence"
        lignes.append(ligne)
    out = {"etapes": lignes, "goulot": goulot}
    if impressions and clics is not None:
        out["ctr_intervalle"] = wilson(clics, impressions)
        out["impressions"] = impressions
    return out


def lire_reference(chemin: str) -> dict:
    """Références tirées de `tendances.py comparer --json` : la médiane de la niche pour J1 et J7 (l'API publique ne
    donne ni taux de clic ni rebond, et ses minutes par joueur ne sont pas une durée de session)."""
    try:
        d = json.loads(Path(chemin).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as err:
        raise SystemExit(f"fichier de référence illisible : {err}")
    med = d.get("mediane") or {}
    return {cle: med[cle] for cle in ("j1", "j7") if isinstance(med.get(cle), (int, float))}


def couple(texte: str) -> tuple:
    try:
        i, c = (float(x.replace(" ", "").replace(" ", "")) for x in texte.split(":"))
    except ValueError:
        raise SystemExit(f"« {texte} » : attendu impressions:clics, par exemple 12000:540")
    if i <= 0 or c < 0 or c > i:
        raise SystemExit(f"« {texte} » : des impressions positives et des clics entre 0 et ce nombre")
    return i, c


def f1(v) -> str:
    return "—" if v is None else f"{v:.1f}".replace(".", ",")


def main(argv=None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    p = argparse.ArgumentParser(description="Diagnostic d'une île Fortnite publiée.")
    sous = p.add_subparsers(dest="commande")
    e = sous.add_parser("entonnoir")
    e.add_argument("--impressions")
    e.add_argument("--clics")
    for cle, libelle, *_ in ETAPES:
        e.add_argument(f"--{cle}", help=libelle + (" (min)" if cle == "session" else " (%)"))
        e.add_argument(f"--ref-{cle}", dest=f"ref_{cle}", help=f"référence du portail pour : {libelle}")
    e.add_argument("--reference", help="JSON de tendances.py comparer --json (références J1 et J7 de la niche)")
    e.add_argument("--json", action="store_true")
    b = sous.add_parser("ab")
    b.add_argument("--a", required=True, help="miniature A : impressions:clics")
    b.add_argument("--b", required=True, help="miniature B : impressions:clics")
    b.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if not a.commande:
        print(__doc__)
        return 1
    if a.commande == "ab":
        (ia, ca), (ib, cb) = couple(a.a), couple(a.b)
        r = test_ab(ia, ca, ib, cb)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return 0
        print(f"A : {f1(r['ctr_a'])} % de clic (entre {f1(r['intervalle_a'][0])} et {f1(r['intervalle_a'][1])} %)")
        print(f"B : {f1(r['ctr_b'])} % de clic (entre {f1(r['intervalle_b'][0])} et {f1(r['intervalle_b'][1])} %)")
        if r["tranche"]:
            print(f"Tranché à 90 % de confiance (p = {r['p']:.3f}) : la miniature {r['gagnante']} gagne, "
                  f"écart de {f1(abs(r['ecart_relatif']))} % sur le taux de clic.")
        else:
            print(f"Pas tranché (p = {r['p']:.2f}, il faut moins de 0,10) : l'écart peut venir du hasard. Laisse courir "
                  "le test ; sans écart net, Epic garde la miniature A.")
        return 0
    valeurs = {cle: nombre(getattr(a, cle)) for cle, *_ in ETAPES}
    refs = lire_reference(a.reference) if a.reference else {}
    refs.update({cle: nombre(getattr(a, f"ref_{cle}")) for cle, *_ in ETAPES if getattr(a, f"ref_{cle}") is not None})
    impressions, clics = nombre(a.impressions), nombre(a.clics)
    if valeurs["ctr"] is None and impressions and clics is not None:
        valeurs["ctr"] = clics / impressions * 100
    if all(v is None for v in valeurs.values()):
        print("Aucun chiffre donné. Exemple : diagnostic.py entonnoir --impressions 48000 --clics 1900 --rebond5 41 "
              "--j1 9 --ref-ctr 5.2 --ref-rebond5 30 --ref-j1 14", file=sys.stderr)
        return 1
    r = entonnoir(valeurs, refs, impressions, clics)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    print(f"{'étape':<18} {'île':>8} {'référence':>10} {'écart':>8}  état")
    for l in r["etapes"]:
        unite = " min" if l["cle"] == "session" else " %"
        ecart = "—" if l["ecart"] is None else f"{l['ecart']:+.0f} %"
        print(f"{l['etape']:<18} {(f1(l['valeur']) + unite) if l['valeur'] is not None else '—':>8} "
              f"{(f1(l['reference']) + unite) if l['reference'] else '—':>10} {ecart:>8}  {l['etat']}")
    if r.get("ctr_intervalle"):
        bas, haut = r["ctr_intervalle"]
        milliers = f"{impressions:,.0f}".replace(",", " ")
        print(f"\nTaux de clic sur {milliers} impressions : entre {f1(bas)} et {f1(haut)} % à 90 % de confiance.")
        if haut - bas > max(valeurs["ctr"] or 0, 0.1) * 0.5:
            print("Fourchette large : trop peu d'impressions pour juger la miniature.")
    g = r["goulot"]
    if g:
        print(f"\nGoulot : {g['etape']} ({f1(g['valeur'])} contre {f1(g['reference'])} en référence).")
        print(f"Lecture : {g['lecture']}.")
        print(f"À faire : {g['action']}.")
        print("Une seule correction à la fois, puis une semaine de mesure : sinon on ne sait pas ce qui a marché.")
    elif any(l["reference"] for l in r["etapes"]):
        print("\nAucune étape nettement sous sa référence : l'île tient la comparaison là où elle est mesurée.")
    sans_ref = [l["etape"] for l in r["etapes"] if l["etat"] == "sans référence"]
    if sans_ref:
        print(f"\nSans référence, pas de verdict pour : {', '.join(sans_ref)}. Lis la médiane dans le menu Benchmarks du "
              "portail créateur (taux de clic, rebond, durée de session, J1, J7) et repasse-la avec --ref-….")
    return 0


if __name__ == "__main__":
    sys.exit(main())
