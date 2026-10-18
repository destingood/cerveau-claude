#!/usr/bin/env python3
"""Relecture d'un texte de vente en français : risques juridiques, promesses à prouver, tics d'écriture, lisibilité.

Pour une fiche produit, une description de collection, un e-mail, un post ou une annonce de marketplace. Repère les
allégations environnementales génériques (interdites depuis le 27/09/2026 sans preuve), la fausse urgence, les
superlatifs invérifiables, les promesses de santé, les demandes d'avis orientées, les prix barrés à vérifier, les
mentions de partenariat sans « Publicité », les tics d'écriture IA, les unités non métriques, les phrases trop longues ;
pour une fiche produit, les informations attendues qui manquent (prix, livraison, retours, dimensions, matière).

Ce n'est pas un avis juridique : chaque point dit quoi vérifier et où (module 10 du skill).
Bibliothèque standard uniquement. Usage : python scripts/relire_texte.py <fichier|-> [--type fiche|email|post|annonce]
[--json]   (code de sortie 1 s'il reste un point 🔴)"""
from __future__ import annotations

import html
import json
import re
import sys
import unicodedata

# (niveau, sujet, motif, ce qu'il faut faire) — 🔴 risque juridique fort · ⚠ à vérifier ou à prouver · · style
RULES = [
    ("🔴", "Allégation environnementale générique",
     r"éco[- ]?responsables?|écologiques?|écolos?|eco[- ]?friendly|green|respectueu(?:x|se|ses) de "
     r"l['’]environnement|respectueu(?:x|se|ses) de la planète|bons? pour la planète|neutres? en carbone|carbo[- ]?neutres?|"
     r"z[ée]ro (?:carbone|émissions?)|climatiquement neutres?|(?:produit|choix|geste|achat)s? verts?|100 ?% verts?",
     "interdit sans performance environnementale reconnue et prouvée (directive (UE) 2024/825, depuis le 27/09/2026 ; "
     "déjà sanctionnable : C. conso., L121-2, et C. env., L541-9-1) : "
     "remplacer par un fait précis, mesuré et daté (ex. « emballage 100 % carton recyclé, certifié … »)"),
    ("⚠", "Allégation environnementale ou de composition à prouver",
     r"biodégradables?|compostables?|recyclables?|z[ée]ro déchet|naturel(?:le)?s?|non toxiques?|"
     r"sans produits? chimiques?|bio|anti[- ]?rides",
     "garder seulement avec la preuve (norme, certificat, pourcentage) et sans généraliser à tout le produit ; "
     "« biodégradable » est interdit sur le produit et l'emballage (C. env., L541-9-1)"),
    ("🔴", "Promesse de santé",
     r"guéri(?:t|r|son)|(?:soigne|soigner|traite|traiter) (?:les|la|le|vos|votre|ton|ta|tes) (?:douleurs?|maux|"
     r"maladies?|symptômes|migraines?|insomnies?|infections?|acné|eczéma|rhumatismes?|arthrose)|anti[- ]?cancer|"
     r"anti[- ]?inflammatoires?|perte de poids garantie|maigrir sans effort|élimine les toxines|détox(?:ifiant)?|"
     r"(?:renforce|booste) (?:l['’])?immunité",
     "allégation de santé interdite pour un produit qui n'est ni un médicament ni un dispositif médical autorisé"),
    ("🔴", "Superlatif invérifiable",
     r"(?:le|la|les) meilleure?s?(?! ventes)|n[°ºo] ?1|numéro (?:1|un)|leader|unique au monde|révolutionnaire|miracle|"
     r"imbattable|incomparable|sans égal",
     "allégation objective non prouvée = pratique commerciale trompeuse (C. conso., art. L121-2) : la prouver ou la "
     "remplacer par un fait mesuré"),
    ("⚠", "Garantie ou résultat promis",
     r"garanti(?:e|s|es)? (?:à )?100 ?%|100 ?% (?:efficaces?|garantie?s?|satisfaite?s?)|résultats? garantis?|"
     r"garantie à vie|satisfait ou remboursé|cliniquement (?:testée?s?|prouvée?s?)|testée?s? dermatologiquement|"
     r"recommandée?s? par (?:les )?(?:experts|médecins|dermatologues)",
     "écrire les conditions exactes (durée, démarches) et garder la preuve ; la garantie commerciale ne remplace pas "
     "les garanties légales"),
    ("⚠", "Urgence ou rareté",
     r"dernière chance|derni(?:er|ère)s? (?:articles?|pièces?|jours?)|plus que \d+|stocks? limités?|quantités? limitées?|"
     r"offres? limitées?|dépêchez[- ]vous|vite\s*!|aujourd['’]hui seulement|expire bientôt|ne ratez pas|"
     r"dans les prochaines? \d+ ?h",
     "seulement si c'est vrai (vrai stock, vraie date) : une fausse urgence est une pratique réputée trompeuse "
     "(C. conso., art. L121-4, 7° ; faux stock : L121-2)"),
    ("⚠", "Réduction ou prix barré",
     r"-\s?\d{1,2} ?%|au lieu de|prix barrés?|soldes?|black friday|prix (?:cassés?|chocs?)|d['’]une valeur de",
     "prix de référence = prix le plus bas des 30 jours précédents (C. conso., art. L112-1-1) ; « soldes » seulement "
     "pendant les périodes légales ; « d'une valeur de » seulement avec un élément de comparaison"),
    ("🔴", "Demande d'avis orientée",
     r"(?:laissez|mettez|donnez)[- ](?:nous|-nous)? ?(?:un avis )?(?:à )?5 étoiles|avis 5 étoiles contre|"
     r"5 étoiles (?:et|pour) (?:recevez|obtenez|gagnez)",
     "demander un avis de façon neutre, à tous les acheteurs, sans contrepartie ni note suggérée"),
    ("⚠", "Origine annoncée",
     r"fabriquée?s? en france|made in france|conçue?s? en france|origine france|artisanale?s?|faits? main",
     "vrai et prouvable (lieu de fabrication réel) ; « conçu en » ne vaut pas « fabriqué en »"),
    ("·", "Tic d'écriture IA",
     r"ce n['’]est pas [^.,;!?]{1,40}, c['’]est|pas de [^.,;!?]{1,25}, pas de|le résultat ?\?|dites adieu (?:à|aux)|"
     r"plongez dans|imaginez|véritable allié|n['’]attendez plus|que vous soyez|sublime[rz]?|élevez votre|"
     r"incontournable|dans un monde où",
     "réécrire simplement : un fait, un bénéfice, une preuve"),
    ("·", "Unité non métrique",
     r"\d+(?:[.,]\d+)?\s?(?:inch(?:es)?|in\.|lbs?|oz|ft|feet|°f|fl\.? ?oz)",
     "convertir en cm, kg, g, ml, °C"),
    ("·", "Appel à l'action vague", r"cliquez ici|click here|en savoir plus",
     "dire ce que la personne obtient (« Voir les tailles », « Choisir ma couleur »)"),
]
SPONSOR = re.compile(r"\b(?:partenariat|code promo|offert par|en collaboration avec|sponsoris[ée]|lien affilié|#ad)\b",
                     re.I)
DISCLOSURE = re.compile(r"\b(?:publicité|collaboration commerciale)\b", re.I)
EXPECT_FICHE = [
    ("prix", r"\d+(?:[.,]\d{2})?\s?€|\beur\b"),
    ("livraison ou délai", r"\blivr(?:aison|é|ée)s?\b|\bexpédi|\bdélai\b"),
    ("retours ou rétractation", r"\bretours?\b|\brétractation\b|\brembours"),
    ("dimensions ou poids", r"\b\d+(?:[.,]\d+)?\s?(?:mm|cm|m|kg|g|ml|cl|l)\b"),
    ("matière ou composition", r"\bmatière|\bcomposition|\ben (?:coton|lin|bois|acier|inox|verre|céramique|cuir|laine|"
                               r"bambou|silicone|plastique|aluminium)\b"),
]
FICHE_TYPES = ("fiche", "produit", "annonce")


def texte_brut(raw: str) -> str:
    """HTML → texte (sauts de ligne conservés pour numéroter les lignes)."""
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
    t = re.sub(r"(?i)<br\s*/?>|</(?:p|div|li|h[1-6]|tr)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return html.unescape(t)


def phrases(text: str) -> list:
    return [p.strip() for p in re.split(r"(?<=[.!?…])\s+|\n+", text) if p.strip()]


def relire(raw: str, kind: str = "fiche") -> dict:
    text = unicodedata.normalize("NFC", texte_brut(raw))
    lines = text.splitlines()
    found = []
    for niveau, sujet, motif, conseil in RULES:
        rx = re.compile(rf"(?<!\w)(?:{motif})(?!\w)", re.I)
        for i, line in enumerate(lines, 1):
            for m in rx.finditer(line):
                found.append({"niveau": niveau, "sujet": sujet, "ligne": i, "extrait": m.group(0).strip(),
                              "conseil": conseil})
    if kind == "post" and SPONSOR.search(text) and not DISCLOSURE.search(text):
        found.append({"niveau": "⚠", "sujet": "Partenariat sans mention", "ligne": None,
                      "extrait": SPONSOR.search(text).group(0),
                      "conseil": "contenu rémunéré (argent ou produit offert) : « Publicité » ou « Collaboration "
                                 "commerciale » visible pendant toute la promotion (loi n° 2023-451, art. 5-2)"})
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ'’-]+", text)
    caps = [w for w in words if len(w) >= 4 and w.isupper()]
    if len(caps) >= 3:
        found.append({"niveau": "·", "sujet": "Majuscules", "ligne": None, "extrait": " ".join(caps[:5]),
                      "conseil": "les majuscules crient : les réserver aux sigles"})
    excl = text.count("!")
    if excl > 3:
        found.append({"niveau": "·", "sujet": "Points d'exclamation", "ligne": None, "extrait": f"{excl} fois",
                      "conseil": "un seul suffit, ou aucun"})
    dashes = text.count("—")
    if dashes > 2 and len(words) < 400:
        found.append({"niveau": "·", "sujet": "Tirets cadratins", "ligne": None, "extrait": f"{dashes} fois",
                      "conseil": "tic d'écriture fréquent des IA : préférer des phrases courtes"})
    ph = phrases(text)
    longues = [p for p in ph if len(p.split()) > 25]
    for p in longues[:3]:
        found.append({"niveau": "·", "sujet": "Phrase longue", "ligne": None, "extrait": p[:90] + ("…" if len(p) > 90 else ""),
                      "conseil": "couper en deux : sur mobile, 15 à 20 mots par phrase se lisent d'un coup d'œil"})
    manque = []
    if kind in FICHE_TYPES:
        manque = [nom for nom, rx in EXPECT_FICHE if not re.search(rx, text, re.I)]
        for nom in manque:
            found.append({"niveau": "·", "sujet": "Information attendue absente", "ligne": None, "extrait": nom,
                          "conseil": "une fiche qui répond avant qu'on pose la question convertit mieux (module 03)"})
    ordre = {"🔴": 0, "⚠": 1, "·": 2}
    found.sort(key=lambda f: (ordre.get(f["niveau"], 3), f["ligne"] or 0))
    nb_mots = len(words)
    return {"type": kind, "mots": nb_mots, "phrases": len(ph),
            "mots_par_phrase": round(nb_mots / len(ph), 1) if ph else 0,
            "rouges": sum(f["niveau"] == "🔴" for f in found), "a_verifier": sum(f["niveau"] == "⚠" for f in found),
            "style": sum(f["niveau"] == "·" for f in found), "points": found}


def rapport(r: dict) -> str:
    out = [f"Relecture ({r['type']}) : {r['mots']} mots, {r['phrases']} phrases, {r['mots_par_phrase']} mots par phrase",
           f"🔴 {r['rouges']} risque(s) juridique(s) · ⚠ {r['a_verifier']} point(s) à vérifier · · {r['style']} "
           "remarque(s) de style", ""]
    for f in r["points"]:
        where = f"ligne {f['ligne']} : " if f["ligne"] else ""
        out.append(f"{f['niveau']} {f['sujet']} — {where}« {f['extrait']} »")
        out.append(f"    → {f['conseil']}")
    if not r["points"]:
        out.append("✓ rien à signaler")
    out.append("\nCe n'est pas un avis juridique : les références du module 10 du skill disent quoi vérifier.")
    return "\n".join(out)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "--aide"):
        print(__doc__)
        return 0 if args else 1
    kind, as_json, src = "fiche", False, None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            as_json = True
        elif a == "--type" and i + 1 < len(args):
            kind = args[i + 1].lower()
            i += 1
        elif a.startswith("--"):
            print(f"Erreur : option inconnue {a}", file=sys.stderr)
            return 2
        else:
            src = a
        i += 1
    if not src:
        print("Erreur : donne un fichier, ou « - » pour lire le texte au clavier", file=sys.stderr)
        return 2
    try:
        raw = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
    except OSError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2
    r = relire(raw, kind)
    print(json.dumps(r, ensure_ascii=False, indent=2) if as_json else rapport(r))
    return 1 if r["rouges"] else 0


if __name__ == "__main__":
    sys.exit(main())
