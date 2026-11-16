#!/usr/bin/env python3
"""Journal de prospection et de ventes, semaine par semaine : les taux qui disent où on perd des affaires, et les
preuves chiffrées qui font monter d'échelon (CV, entretien annuel, demande d'augmentation).

    python progression.py noter --appels 220 --conversations 28 --rdv 6 --opportunites 3 --signes 1 --ca 9000 \\
        --objectif-ca 12000                      # la semaine en cours (ou --semaine 2026-W47)
    python progression.py noter --mails 120 --reponses 9        # complète la même semaine
    python progression.py bilan                  # 8 dernières semaines : volumes, taux, goulot, objectif
    python progression.py bilan --semaines 13 --json
    python progression.py preuves                # phrases chiffrées pour le CV et l'entretien
    python progression.py exporter journal.csv   # tableur (séparateur « ; », virgule décimale)

Chaque champ est facultatif : on note ce que l'on fait vraiment. Les chiffres restent sur ton PC, dans
~/.claude/carriere/journal.json (CARRIERE_HOME pour le déplacer). Bibliothèque standard uniquement, aucun réseau."""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

CHAMPS = [  # (clé, libellé)
    ("appels", "appels passés"), ("conversations", "conversations"), ("mails", "messages envoyés"),
    ("reponses", "réponses reçues"), ("rdv", "rendez-vous obtenus"), ("opportunites", "opportunités ouvertes"),
    ("signes", "affaires signées"), ("ca", "chiffre signé (€)"), ("objectif_ca", "objectif de chiffre (€)"),
    ("objectif_rdv", "objectif de rendez-vous"),
]
# Étapes de l'entonnoir : (numérateur, dénominateur, libellé du taux)
TAUX = [("conversations", "appels", "appels → conversation"), ("reponses", "mails", "messages → réponse"),
        ("rdv", "conversations", "conversation → rendez-vous"), ("opportunites", "rdv", "rendez-vous → opportunité"),
        ("signes", "opportunites", "opportunité → signature")]
SEMAINE = re.compile(r"^(\d{4})-W(\d{2})$")


def dossier() -> Path:
    return Path(os.environ.get("CARRIERE_HOME") or Path.home() / ".claude" / "carriere")


def charger() -> dict:
    try:
        return json.loads((dossier() / "journal.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"semaines": {}}


def sauver(journal: dict) -> Path:
    f = dossier() / "journal.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    journal["semaines"] = dict(sorted(journal["semaines"].items()))
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(journal, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(f)
    return f


def semaine_iso(d: date | None = None) -> str:
    a, s, _ = (d or date.today()).isocalendar()
    return f"{a}-W{s:02d}"


def nombre(texte: str) -> float:
    t = str(texte).replace(" ", "").replace(" ", "").replace("€", "").replace(",", ".").lower()
    mult = 1000 if t.endswith("k") else 1
    try:
        v = float(t.rstrip("k")) * mult
    except ValueError:
        raise SystemExit(f"nombre illisible : « {texte} »")
    if v < 0:
        raise SystemExit(f"nombre négatif : « {texte} »")
    return int(v) if v == int(v) else v


def nb(v) -> str:
    return f"{v:,.0f}".replace(",", " ")


def somme(semaines: list, cle: str):
    vals = [s[cle] for s in semaines if cle in s]
    return sum(vals) if vals else None


def bilan(journal: dict, n: int = 8) -> dict:
    cles = list(journal["semaines"])[-n:]
    sem = [journal["semaines"][k] for k in cles]
    tot = {cle: somme(sem, cle) for cle, _ in CHAMPS}
    taux = []
    for num, den, libelle in TAUX:
        a, b = tot.get(num), tot.get(den)
        if a is not None and b:
            taux.append({"etape": libelle, "taux": 100 * a / b, "de": b, "a": a})
    # moitié récente contre moitié ancienne : la tendance de chaque volume
    tendance = {}
    if len(sem) >= 4:
        moitie = len(sem) // 2
        for cle, _ in CHAMPS[:8]:
            avant, apres = somme(sem[:moitie], cle), somme(sem[-moitie:], cle)
            if avant and apres is not None:
                tendance[cle] = 100 * (apres / avant - 1)
    objectif = None
    if tot.get("objectif_ca"):
        objectif = 100 * (tot.get("ca") or 0) / tot["objectif_ca"]
    # goulot : l'étape au taux le plus bas comparé à sa médiane… sans référence, on montre seulement la plus petite
    # conversion, en le disant (aucun seuil inventé)
    return {"semaines": cles, "totaux": tot, "taux": taux, "tendance": tendance, "atteinte_ca": objectif,
            "par_semaine": {k: journal["semaines"][k] for k in cles}}


def preuves(journal: dict) -> list:
    """Phrases chiffrées, vraies et vérifiables, tirées du journal (rien d'arrondi vers le haut)."""
    sem = journal["semaines"]
    if not sem:
        return []
    cles = list(sem)
    tout = list(sem.values())
    phrases = []
    trimestres = {}
    for k, s in sem.items():
        m = SEMAINE.match(k)
        if m and s.get("objectif_ca"):
            t = f"{m.group(1)} T{min(4, (int(m.group(2)) - 1) // 13 + 1)}"
            trimestres.setdefault(t, [0, 0])
            trimestres[t][0] += s.get("ca") or 0
            trimestres[t][1] += s["objectif_ca"]
    for t, (ca, obj) in trimestres.items():
        if obj:
            phrases.append(f"{t} : {100 * ca / obj:.0f} % de l'objectif de chiffre ({ca:,.0f} € signés pour "
                           f"{obj:,.0f} € attendus)".replace(",", " "))
    for cle, libelle in (("rdv", "rendez-vous obtenus"), ("signes", "affaires signées"), ("conversations", "conversations")):
        total = somme(tout, cle)
        if total:
            phrases.append(f"{total:,.0f} {libelle} en {len(cles)} semaines ({cles[0]} à {cles[-1]})".replace(",", " "))
    b = bilan(journal, len(cles))
    for t in b["taux"]:
        if t["de"] >= 20:  # sous 20 essais, un taux ne prouve rien
            phrases.append(f"Taux {t['etape']} : {t['taux']:.0f} % ({t['a']:,.0f} sur {t['de']:,.0f})".replace(",", " "))
    meilleure = max(sem.items(), key=lambda kv: kv[1].get("rdv") or 0)
    if meilleure[1].get("rdv"):
        phrases.append(f"Meilleure semaine : {meilleure[1]['rdv']} rendez-vous ({meilleure[0]})")
    return phrases


def cmd_noter(a) -> int:
    k = a.semaine or semaine_iso()
    if not SEMAINE.match(k):
        raise SystemExit(f"semaine « {k} » : attendu 2026-W47")
    j = charger()
    s = j["semaines"].setdefault(k, {})
    changes = {cle: nombre(getattr(a, cle)) for cle, _ in CHAMPS if getattr(a, cle) is not None}
    if not changes:
        raise SystemExit("rien à noter : donne au moins un chiffre (--appels, --rdv, --signes…)")
    s.update(changes)
    f = sauver(j)
    print(f"Semaine {k} notée : " + ", ".join(f"{v:,} {dict(CHAMPS)[c]}".replace(",", " ") for c, v in changes.items())
          + f"\n→ {f}")
    return 0


def cmd_bilan(a) -> int:
    j = charger()
    if not j["semaines"]:
        print("Journal vide : commence par « progression.py noter --appels … --rdv … ».")
        return 1
    b = bilan(j, a.semaines)
    if a.json:
        print(json.dumps(b, ensure_ascii=False, indent=1))
        return 0
    print(f"Bilan de {len(b['semaines'])} semaine(s) : {b['semaines'][0]} à {b['semaines'][-1]}\n")
    for cle, libelle in CHAMPS[:8]:
        v = b["totaux"][cle]
        if v is not None:
            t = b["tendance"].get(cle)
            print(f"  {libelle:<24} {v:>10,.0f}".replace(",", " ")
                  + (f"   tendance {t:+.0f} %" if t is not None else ""))
    if b["taux"]:
        print("\nTaux de passage (sur toute la période) :")
        for t in b["taux"]:
            alerte = "  (moins de 20 essais : à confirmer)" if t["de"] < 20 else ""
            pct = f"{t['taux']:.1f}".replace(".", ",")
            print(f"  {t['etape']:<28} {pct:>5} %  ({nb(t['a'])} / {nb(t['de'])}){alerte}")
        fiables = [t for t in b["taux"] if t["de"] >= 20]
        if fiables:
            bas = min(fiables, key=lambda t: t["taux"])
            print(f"\nÉtape la plus faible : {bas['etape']}. Compare-la aux chiffres de ton équipe ou de ton manager avant "
                  "de conclure : sans référence, c'est une piste, pas un verdict.")
    if b["atteinte_ca"] is not None:
        print(f"\nObjectif de chiffre : {b['atteinte_ca']:.0f} % atteint sur la période.")
    return 0


def cmd_preuves(a) -> int:
    p = preuves(charger())
    if a.json:
        print(json.dumps(p, ensure_ascii=False, indent=1))
        return 0
    if not p:
        print("Pas encore de preuves : note tes semaines avec « progression.py noter ».")
        return 1
    print("Preuves chiffrées (à reprendre telles quelles, sans les gonfler) :")
    for x in p:
        print(f"  • {x}")
    return 0


def cmd_exporter(a) -> int:
    j = charger()
    with open(a.fichier, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["semaine"] + [lib for _, lib in CHAMPS])
        for k, s in j["semaines"].items():
            w.writerow([k] + [str(s.get(c, "")).replace(".", ",") for c, _ in CHAMPS])
    print(f"{len(j['semaines'])} semaine(s) écrite(s) dans {a.fichier}")
    return 0


def main(argv=None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    p = argparse.ArgumentParser(description="Journal de prospection et de ventes.")
    sous = p.add_subparsers(dest="commande")
    n = sous.add_parser("noter")
    n.add_argument("--semaine", help="semaine ISO, 2026-W47 (défaut : la semaine en cours)")
    for cle, libelle in CHAMPS:
        n.add_argument("--" + cle.replace("_", "-"), dest=cle, help=libelle)
    b = sous.add_parser("bilan")
    b.add_argument("--semaines", type=int, default=8)
    b.add_argument("--json", action="store_true")
    r = sous.add_parser("preuves")
    r.add_argument("--json", action="store_true")
    e = sous.add_parser("exporter")
    e.add_argument("fichier")
    a = p.parse_args(argv)
    if not a.commande:
        print(__doc__)
        return 1
    return {"noter": cmd_noter, "bilan": cmd_bilan, "preuves": cmd_preuves, "exporter": cmd_exporter}[a.commande](a)


if __name__ == "__main__":
    sys.exit(main())
