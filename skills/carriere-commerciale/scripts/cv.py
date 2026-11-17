#!/usr/bin/env python3
"""CV de commercial, d'un fichier cv.json à une page HTML propre à imprimer en PDF (une colonne, lisible par les
logiciels de recrutement), avec un contrôle de ce qui fait passer un CV de vente : des résultats chiffrés.

    python cv.py --modele > cv.json      # un cv.json à remplir
    python cv.py cv.json --controle      # ne génère rien : dit ce qui affaiblit le CV
    python cv.py cv.json                 # écrit cv.html à côté (Ctrl+P → « Enregistrer au format PDF »)
    python cv.py cv.json -o sortie/cv.html

Le script ne corrige pas l'orthographe : fais relire le texte (Claude, Antidote, LanguageTool…) avant de générer.
Il signale les phrases longues, les qualités sans preuve (« dynamique », « motivé »…) et les expériences sans chiffre.
Bibliothèque standard uniquement, aucun accès réseau ; la page n'a ni script, ni police distante, ni traceur."""
from __future__ import annotations

import argparse
import json
import re
import sys
from html import escape
from pathlib import Path

MODELE = {
    "nom": "Prénom Nom",
    "titre": "Vendeur conseil — informatique, téléphonie, multimédia",
    "contact": {"telephone": "06 00 00 00 00", "email": "ton adresse e-mail", "ville": "Ville (mobilité : …)",
                "linkedin": "linkedin.com/in/…"},
    "accroche": "Deux phrases : ce que tu vends ou veux vendre, la preuve la plus forte, le poste visé.",
    "experiences": [
        {"poste": "Vendeur", "entreprise": "Magasin X", "lieu": "Ville", "debut": "2025-09", "fin": "",
         "resultats": ["Un résultat par ligne, avec un chiffre : 112 % de l'objectif de ventes au T1 2026.",
                       "Ce que tu as fait pour l'obtenir : 40 clients conseillés par jour en période de soldes."]}
    ],
    "formations": [{"diplome": "Titre ou formation", "ecole": "Organisme", "annee": "2026", "detail": ""}],
    "competences": ["Prospection téléphonique", "CRM (HubSpot, Salesforce…)", "Négociation"],
    "langues": ["Français (langue maternelle)", "Anglais (niveau à préciser honnêtement)"],
    "centres_interet": ["Un intérêt qui dit quelque chose de toi : compétition, sport d'équipe, projet mené seul…"],
}
VAGUES = {"dynamique", "motivé", "motivée", "rigoureux", "rigoureuse", "polyvalent", "polyvalente", "autonome",
          "passionné", "passionnée", "sérieux", "sérieuse", "organisé", "organisée", "curieux", "curieuse",
          "persévérant", "persévérante", "bon relationnel", "esprit d'équipe", "force de proposition"}
PHRASE_MAX = 25  # mots : au-delà, une phrase de CV se lit mal (et se relit mal)
DATE = re.compile(r"^\d{4}(-\d{2})?$")
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def date_fr(d: str) -> str:
    if not d:
        return "aujourd'hui"
    if re.fullmatch(r"\d{4}-\d{2}", d):
        a, m = d.split("-")
        return f"{MOIS[int(m) - 1]} {a}" if 1 <= int(m) <= 12 else d
    return d


def textes(cv: dict) -> list:
    """Toutes les phrases à contrôler : (où, texte)."""
    out = [("accroche", cv.get("accroche") or "")]
    for e in cv.get("experiences") or []:
        out += [(f"{e.get('poste', '?')} — {e.get('entreprise', '?')}", r) for r in e.get("resultats") or []]
    return [(o, t) for o, t in out if t.strip()]


def controle(cv: dict) -> tuple[list, list]:
    """→ (bloquants, conseils)."""
    bloquants, conseils = [], []
    if not str(cv.get("nom") or "").strip() or cv.get("nom") == MODELE["nom"]:
        bloquants.append("« nom » à remplir")
    contact = cv.get("contact") or {}
    if not (contact.get("telephone") or contact.get("email")):
        bloquants.append("aucun moyen de te joindre (téléphone ou e-mail)")
    if json.dumps(cv, ensure_ascii=False).count("…") and any(v == MODELE["contact"][k] for k, v in contact.items()
                                                             if k in MODELE["contact"]):
        bloquants.append("des champs du modèle sont encore là (contact)")
    if not cv.get("titre"):
        conseils.append("pas de titre : le recruteur doit lire le poste visé en une seconde")
    for e in cv.get("experiences") or []:
        nom = f"{e.get('poste', '?')} — {e.get('entreprise', '?')}"
        for champ in ("debut", "fin"):
            v = str(e.get(champ) or "")
            if v and not DATE.match(v):
                conseils.append(f"{nom} : date « {v} » à écrire 2025-09 ou 2025")
        res = e.get("resultats") or []
        if not res:
            conseils.append(f"{nom} : aucune ligne de résultat")
        elif not any(re.search(r"\d", r) for r in res):
            conseils.append(f"{nom} : aucun chiffre. Un recruteur commercial cherche des nombres : objectif atteint (%), "
                            "clients par jour, panier moyen, appels, rendez-vous")
        if len(res) > 5:
            conseils.append(f"{nom} : {len(res)} lignes ; garde les 3 à 5 plus fortes")
    for ou, t in textes(cv):
        mots = len(t.split())
        if mots > PHRASE_MAX:
            conseils.append(f"{ou} : phrase de {mots} mots (« {t[:50]}… ») ; coupe en deux")
        bas = t.lower()
        vides = sorted(v for v in VAGUES if re.search(r"(?<!\w)" + re.escape(v) + r"(?!\w)", bas))
        if vides and not re.search(r"\d", t):
            conseils.append(f"{ou} : « {', '.join(vides)} » sans preuve ; remplace par un fait")
    if not cv.get("experiences"):
        conseils.append("aucune expérience : mets tout ce qui montre que tu sais convaincre et tenir un objectif "
                        "(job d'été, vente sur Vinted, association, sport en compétition, projet perso)")
    total = sum(len(t.split()) for _, t in textes(cv)) + sum(len(" ".join(map(str, f.values())).split())
                                                         for f in cv.get("formations") or [])
    if total > 450:
        conseils.append(f"{total} mots : au-delà d'une page pour un premier poste ; enlève le moins fort")
    return bloquants, conseils


def page(cv: dict) -> str:
    e = escape
    c = cv.get("contact") or {}
    contact = " · ".join(e(str(c[k])) for k in ("telephone", "email", "ville", "linkedin") if c.get(k))
    blocs = [f"<header><h1>{e(cv['nom'])}</h1>"
             + (f"<p class=\"titre\">{e(cv['titre'])}</p>" if cv.get("titre") else "")
             + f"<p class=\"contact\">{contact}</p></header>"]
    if cv.get("accroche"):
        blocs.append(f"<p class=\"accroche\">{e(cv['accroche'])}</p>")
    if cv.get("experiences"):
        items = []
        for x in cv["experiences"]:
            quand = f"{date_fr(str(x.get('debut') or ''))} – {date_fr(str(x.get('fin') or ''))}"
            lieu = f", {e(x['lieu'])}" if x.get("lieu") else ""
            items.append(f"<article><h3>{e(x.get('poste', ''))} — {e(x.get('entreprise', ''))}{lieu}"
                         f"<span>{e(quand)}</span></h3><ul>"
                         + "".join(f"<li>{e(r)}</li>" for r in x.get("resultats") or []) + "</ul></article>")
        blocs.append("<section><h2>Expérience</h2>" + "".join(items) + "</section>")
    if cv.get("formations"):
        blocs.append("<section><h2>Formation</h2>" + "".join(
            f"<article><h3>{e(f.get('diplome', ''))} — {e(f.get('ecole', ''))}<span>{e(str(f.get('annee', '')))}</span></h3>"
            + (f"<p>{e(f['detail'])}</p>" if f.get("detail") else "") + "</article>" for f in cv["formations"]) + "</section>")
    for cle, titre in (("competences", "Compétences"), ("langues", "Langues"), ("centres_interet", "Centres d'intérêt")):
        if cv.get(cle):
            blocs.append(f"<section><h2>{titre}</h2><p>{' · '.join(e(str(x)) for x in cv[cle])}</p></section>")
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CV — {e(cv['nom'])}</title>
<style>
@page{{size:A4;margin:14mm 15mm}}
*{{box-sizing:border-box}}
body{{margin:0;background:#fff;color:#16181d;font:10.5pt/1.45 Arial,Helvetica,sans-serif}}
main{{max-width:180mm;margin:0 auto;padding:10mm 0}}
h1{{font-size:20pt;margin:0}}
.titre{{font-size:12pt;font-weight:700;margin:2pt 0;color:#1f4fa8}}
.contact{{margin:2pt 0 8pt;color:#3c4250}}
.accroche{{margin:0 0 6pt}}
h2{{font-size:11pt;text-transform:uppercase;letter-spacing:.06em;border-bottom:1.5pt solid #1f4fa8;padding-bottom:2pt;margin:12pt 0 5pt;color:#1f4fa8}}
h3{{font-size:10.5pt;margin:6pt 0 2pt;display:flex;justify-content:space-between;gap:8pt}}
h3 span{{font-weight:400;color:#3c4250;white-space:nowrap}}
ul{{margin:0;padding-left:14pt}}
li{{margin:1pt 0}}
p{{margin:0}}
@media screen{{main{{padding:24px 16px}}}}
</style>
</head>
<body>
<main>
{chr(10).join(blocs)}
</main>
</body>
</html>
"""


def main(argv=None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    p = argparse.ArgumentParser(description="CV de commercial : contrôle et page HTML à imprimer en PDF.")
    p.add_argument("fichier", nargs="?")
    p.add_argument("-o", "--sortie")
    p.add_argument("--controle", action="store_true")
    p.add_argument("--modele", action="store_true")
    a = p.parse_args(argv)
    if a.modele:
        print(json.dumps(MODELE, ensure_ascii=False, indent=2))
        return 0
    if not a.fichier:
        print(__doc__)
        return 1
    try:
        cv = json.loads(Path(a.fichier).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as err:
        print(f"cv.json illisible : {err}", file=sys.stderr)
        return 1
    bloquants, conseils = controle(cv)
    for b in bloquants:
        print(f"✗ {b}")
    for c in conseils:
        print(f"· {c}")
    if bloquants:
        print(f"{len(bloquants)} point(s) bloquant(s) : CV non généré.")
        return 1
    if a.controle:
        print("CV sans point faible repéré." if not conseils else f"{len(conseils)} conseil(s), rien de bloquant.")
        return 0
    sortie = Path(a.sortie) if a.sortie else Path(a.fichier).with_name("cv.html")
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_bytes(page(cv).encode("utf-8"))
    print(f"CV écrit : {sortie} — ouvre-le dans le navigateur, Ctrl+P, « Enregistrer au format PDF ».")
    return 0


if __name__ == "__main__":
    sys.exit(main())
