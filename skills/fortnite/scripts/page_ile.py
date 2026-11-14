#!/usr/bin/env python3
"""Page web d'une île Fortnite, prête à mettre en ligne : une page HTML autonome que Google, Bing et les assistants IA
peuvent lire et citer (réponse directe en tête, code d'île en clair, faits datés, FAQ visible, données structurées).

    python page_ile.py ile.json                    # écrit index.html à côté de ile.json
    python page_ile.py ile.json -o site/index.html
    python page_ile.py ile.json --controle         # ne génère rien : dit ce qui manque dans ile.json
    python page_ile.py --modele > ile.json         # un ile.json à remplir

Bibliothèque standard uniquement, aucun accès réseau. La page n'a ni script de mesure, ni cookie, ni police distante.
Elle porte la mention exigée par la politique « Fan Content » d'Epic Games (règle 1.10) et ne doit ressembler en rien
à un site officiel (règle 1.8) : garde ton propre habillage."""
from __future__ import annotations

import argparse
import json
import re
import sys
from html import escape
from pathlib import Path

CODE = re.compile(r"^\d{4}-\d{4}-\d{4}$")
# Politique « Fan Content » d'Epic Games, règle 1.10 (legal.epicgames.com/epicgames/fan-art-policy, lue le 14/11/2026)
MENTION = ("Portions of the materials used are trademarks and/or copyrighted works of Epic Games, Inc. All rights "
           "reserved by Epic. This material is not official and is not endorsed by Epic.")
TITRE_MAX, DESC_MAX = 60, 155  # au-delà, Google coupe le titre et l'extrait dans ses résultats (ordre de grandeur)

MODELE = {
    "titre": "",
    "code": "0000-0000-0000",
    "createur": "",
    "genre": "Zone Wars",
    "accroche": "Une phrase : pour qui, quel mode, ce que cette map a que les autres n'ont pas.",
    "description": ["Premier paragraphe : ce qu'on y fait, en clair.", "Deuxième paragraphe : ce qui la distingue."],
    "joueurs_min": 2,
    "joueurs_max": 16,
    "modes": ["Solo", "Duos"],
    "points_forts": ["Un fait vérifiable par ligne : nombre de zones, durée d'une manche, réglages disponibles."],
    "comment_jouer": ["Lance Fortnite et ouvre le menu de sélection du mode.",
                      "Ouvre la recherche et saisis le code de l'île.",
                      "Lance la partie."],
    "faq": [{"q": "Combien de joueurs ?", "r": "De 2 à 16."}],
    "images": [{"src": "capture-1.webp", "alt": "Ce que montre l'image, en une phrase", "largeur": 1280, "hauteur": 720}],
    "video": "",
    "publiee_le": "",
    "mise_a_jour": "",
    "nouveautes": [{"date": "", "texte": "Ce qui a changé dans cette version."}],
    "langue": "fr",
    "url": "https://exemple.fr/ma-map/",
    "lien_ile": "",
}

TEXTES = {
    "fr": {"code": "Code de l'île", "copier": "Copier le code", "copie": "Code copié", "jouer": "Ouvrir l'île sur fortnite.com",
           "resume": "En bref", "genre": "Genre", "joueurs": "Joueurs", "modes": "Modes", "createur": "Créateur",
           "maj": "Dernière mise à jour", "publiee": "Publiée le", "forts": "Ce que la map propose",
           "comment": "Comment jouer", "faq": "Questions fréquentes", "nouveautes": "Nouveautés", "video": "Vidéo de la map",
           "de_a": "de {a} à {b}", "suffixe": "code de map {genre} Fortnite"},
    "en": {"code": "Island code", "copier": "Copy code", "copie": "Code copied", "jouer": "Open the island on fortnite.com",
           "resume": "At a glance", "genre": "Genre", "joueurs": "Players", "modes": "Modes", "createur": "Creator",
           "maj": "Last updated", "publiee": "Published", "forts": "What the map offers",
           "comment": "How to play", "faq": "Frequently asked questions", "nouveautes": "What's new", "video": "Map video",
           "de_a": "{a} to {b}", "suffixe": "Fortnite {genre} map code"},
}


def controle(ile: dict) -> tuple[list, list]:
    """→ (bloquants, conseils) : ce qui empêche de générer la page, et ce qui la rendrait plus facile à citer."""
    bloquants, conseils = [], []
    for champ in ("titre", "code", "genre", "accroche", "url"):
        if not str(ile.get(champ) or "").strip():
            bloquants.append(f"« {champ} » est vide")
    code = str(ile.get("code") or "")
    if code and (not CODE.match(code) or code == MODELE["code"]):
        bloquants.append(f"code d'île « {code} » : attendu 12 chiffres en trois groupes, 1234-5678-9012")
    url = str(ile.get("url") or "")
    if url and (not url.startswith("https://") or "exemple." in url):
        bloquants.append(f"« url » : l'adresse https définitive de la page (reçu « {url} »)")
    if ile.get("langue", "fr") not in TEXTES:
        bloquants.append(f"« langue » : fr ou en (reçu « {ile.get('langue')} »)")
    if not ile.get("description"):
        conseils.append("« description » vide : deux paragraphes de faits, sinon la page n'a rien à citer")
    if not ile.get("mise_a_jour"):
        conseils.append("« mise_a_jour » vide : une date visible dit au lecteur et aux moteurs que la page est tenue")
    if len(ile.get("faq") or []) < 3:
        conseils.append("moins de 3 questions dans « faq » : mets les vraies questions des joueurs (code, joueurs, "
                        "modes, réglages, mises à jour)")
    if not ile.get("images"):
        conseils.append("aucune image : une capture en jeu au moins, avec un texte alternatif qui la décrit")
    for img in ile.get("images") or []:
        if not str(img.get("alt") or "").strip():
            conseils.append(f"image « {img.get('src')} » sans texte alternatif")
        if not (img.get("largeur") and img.get("hauteur")):
            conseils.append(f"image « {img.get('src')} » sans largeur ni hauteur : la page saute au chargement")
    if not ile.get("createur"):
        conseils.append("« createur » vide : le nom affiché sur l'île relie la page à ta page de créateur")
    if not (ile.get("joueurs_min") and ile.get("joueurs_max")):
        conseils.append("« joueurs_min » et « joueurs_max » vides : c'est une des premières questions posées")
    titre = titre_page(ile)
    if len(titre) > TITRE_MAX:
        conseils.append(f"titre de page de {len(titre)} caractères (« {titre} ») : Google coupe vers {TITRE_MAX}")
    return bloquants, conseils


def titre_page(ile: dict) -> str:
    t = TEXTES.get(ile.get("langue", "fr"), TEXTES["fr"])
    titre, genre = ile.get("titre", "").strip(), ile.get("genre", "").strip()
    if genre.lower() in titre.lower():  # « Neon Zone Wars » dit déjà le genre : ne pas le répéter
        genre = ""
    suffixe = re.sub(r"\s+", " ", t["suffixe"].format(genre=genre)).strip()
    return f"{titre} — {suffixe} {ile.get('code', '')}"


def meta_description(ile: dict) -> str:
    texte = f"{ile.get('accroche', '').strip()} {TEXTES[ile.get('langue', 'fr')]['code']} : {ile.get('code', '')}."
    if len(texte) <= DESC_MAX:
        return texte
    court = ile.get("accroche", "").strip()[:DESC_MAX - 30].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return f"{court} {TEXTES[ile.get('langue', 'fr')]['code']} : {ile.get('code', '')}."


def lien_ile(ile: dict) -> str:
    """Lien vers l'île : celui que donne l'utilisateur (« lien_ile », copié depuis la page de son île), sinon la
    page de l'île sur fortnite.com construite avec son nom de créateur."""
    if ile.get("lien_ile"):
        return str(ile["lien_ile"])
    createur = str(ile.get("createur") or "").strip().lstrip("@")
    return f"https://www.fortnite.com/@{createur}/{ile['code']}" if createur else ""


def donnees_structurees(ile: dict) -> dict:
    """schema.org/VideoGame : aide les moteurs à comprendre de quoi parle la page (nom, genre, nombre de joueurs,
    auteur, dates). Aucun résultat enrichi n'y est attaché : c'est de la clarté, pas une promesse d'affichage."""
    d = {"@context": "https://schema.org", "@type": "VideoGame", "name": ile["titre"], "url": ile["url"],
         "description": ile["accroche"], "genre": ile["genre"], "inLanguage": ile.get("langue", "fr"),
         "identifier": ile["code"], "isPartOf": {"@type": "VideoGame", "name": "Fortnite"},
         "playMode": "https://schema.org/MultiPlayer" if int(ile.get("joueurs_max") or 2) > 1 else "https://schema.org/SinglePlayer"}
    if ile.get("joueurs_min") and ile.get("joueurs_max"):
        d["numberOfPlayers"] = {"@type": "QuantitativeValue", "minValue": int(ile["joueurs_min"]),
                                "maxValue": int(ile["joueurs_max"])}
    if ile.get("createur"):
        d["author"] = {"@type": "Person", "name": str(ile["createur"]).lstrip("@")}
    if ile.get("publiee_le"):
        d["datePublished"] = ile["publiee_le"]
    if ile.get("mise_a_jour"):
        d["dateModified"] = ile["mise_a_jour"]
    images = [absolu(ile["url"], i["src"]) for i in ile.get("images") or [] if i.get("src")]
    if images:
        d["image"] = images
    lien = lien_ile(ile)
    if lien:
        d["sameAs"] = [lien]
    return d


def absolu(base: str, src: str) -> str:
    if re.match(r"^https?://", src):
        return src
    return base.rstrip("/") + "/" + src.lstrip("/")


def youtube_id(lien: str) -> str:
    m = re.search(r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/))([\w-]{11})", lien or "")
    return m.group(1) if m else ""


def page(ile: dict) -> str:
    t = TEXTES[ile.get("langue", "fr")]
    e = escape
    code = ile["code"]
    lien = lien_ile(ile)
    faits = [(t["genre"], ile["genre"])]
    if ile.get("joueurs_min") and ile.get("joueurs_max"):
        faits.append((t["joueurs"], t["de_a"].format(a=ile["joueurs_min"], b=ile["joueurs_max"])))
    if ile.get("modes"):
        faits.append((t["modes"], ", ".join(ile["modes"])))
    if ile.get("createur"):
        faits.append((t["createur"], str(ile["createur"]).lstrip("@")))
    if ile.get("publiee_le"):
        faits.append((t["publiee"], ile["publiee_le"]))
    if ile.get("mise_a_jour"):
        faits.append((t["maj"], ile["mise_a_jour"]))
    paragraphes = ile.get("description") or []
    if isinstance(paragraphes, str):
        paragraphes = [p for p in paragraphes.split("\n") if p.strip()]
    images = ile.get("images") or []
    og = absolu(ile["url"], images[0]["src"]) if images else ""
    corps = []
    corps.append(f"<h1>{e(ile['titre'])}</h1>")
    corps.append(f"<p class=\"accroche\">{e(ile['accroche'])}</p>")
    corps.append(f"<p class=\"code\"><span>{e(t['code'])}</span> <strong id=\"code\">{e(code)}</strong> "
                 f"<button type=\"button\" id=\"copier\" data-fait=\"{e(t['copie'])}\">{e(t['copier'])}</button></p>")
    if lien:
        corps.append(f"<p><a class=\"jouer\" href=\"{e(lien)}\" rel=\"noopener\">{e(t['jouer'])}</a></p>")
    corps.append(f"<h2>{e(t['resume'])}</h2>\n<dl>" + "".join(f"<dt>{e(k)}</dt><dd>{e(str(v))}</dd>" for k, v in faits)
                 + "</dl>")
    corps.extend(f"<p>{e(p)}</p>" for p in paragraphes)
    for i, img in enumerate(images):
        taille = (f" width=\"{int(img['largeur'])}\" height=\"{int(img['hauteur'])}\""
                  if img.get("largeur") and img.get("hauteur") else "")
        paresse = "" if i == 0 else " loading=\"lazy\""
        corps.append(f"<img src=\"{e(img['src'])}\" alt=\"{e(img.get('alt') or '')}\"{taille}{paresse}>")
    if ile.get("points_forts"):
        corps.append(f"<h2>{e(t['forts'])}</h2>\n<ul>" + "".join(f"<li>{e(p)}</li>" for p in ile["points_forts"]) + "</ul>")
    if ile.get("comment_jouer"):
        corps.append(f"<h2>{e(t['comment'])}</h2>\n<ol>" + "".join(f"<li>{e(p)}</li>" for p in ile["comment_jouer"])
                     + "</ol>")
    vid = youtube_id(ile.get("video") or "")
    if vid:  # un lien, pas un lecteur intégré : aucun traceur tiers chargé sur la page
        corps.append(f"<h2>{e(t['video'])}</h2>\n<p><a href=\"https://www.youtube.com/watch?v={vid}\" rel=\"noopener\">"
                     f"{e(t['video'])} — YouTube</a></p>")
    if ile.get("faq"):
        corps.append(f"<h2>{e(t['faq'])}</h2>\n" + "\n".join(
            f"<h3>{e(q['q'])}</h3>\n<p>{e(q['r'])}</p>" for q in ile["faq"] if q.get("q") and q.get("r")))
    nouveautes = [n for n in ile.get("nouveautes") or [] if n.get("date") and n.get("texte")]
    if nouveautes:
        corps.append(f"<h2>{e(t['nouveautes'])}</h2>\n<ul>" + "".join(
            f"<li><time datetime=\"{e(n['date'])}\">{e(n['date'])}</time> — {e(n['texte'])}</li>" for n in nouveautes)
            + "</ul>")
    ld = json.dumps(donnees_structurees(ile), ensure_ascii=False, indent=1).replace("</", "<\\/")
    tete = [
        "<meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"<title>{e(titre_page(ile))}</title>",
        f"<meta name=\"description\" content=\"{e(meta_description(ile))}\">",
        f"<link rel=\"canonical\" href=\"{e(ile['url'])}\">",
        "<meta property=\"og:type\" content=\"website\">",
        f"<meta property=\"og:title\" content=\"{e(titre_page(ile))}\">",
        f"<meta property=\"og:description\" content=\"{e(meta_description(ile))}\">",
        f"<meta property=\"og:url\" content=\"{e(ile['url'])}\">",
    ]
    if og:
        tete += [f"<meta property=\"og:image\" content=\"{e(og)}\">",
                 "<meta name=\"twitter:card\" content=\"summary_large_image\">"]
    return f"""<!doctype html>
<html lang="{e(ile.get('langue', 'fr'))}">
<head>
{chr(10).join(tete)}
<script type="application/ld+json">
{ld}
</script>
<style>
:root{{color-scheme:light dark;--fond:#fff;--texte:#16181d;--doux:#5b6270;--trait:#d9dde4;--accent:#1f5fd0}}
@media (prefers-color-scheme:dark){{:root{{--fond:#111318;--texte:#eceef2;--doux:#a3aab8;--trait:#2c313b;--accent:#8ab4ff}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--fond);color:var(--texte);font:17px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
main{{max-width:44rem;margin:0 auto;padding:2rem 1rem 3rem}}
h1{{font-size:2rem;line-height:1.2;margin:0 0 .5rem}}
h2{{font-size:1.3rem;margin:2.2rem 0 .6rem}}
h3{{font-size:1.05rem;margin:1.2rem 0 .2rem}}
.accroche{{font-size:1.15rem;color:var(--doux);margin:0 0 1.2rem}}
.code{{display:flex;flex-wrap:wrap;align-items:center;gap:.6rem;padding:1rem;border:1px solid var(--trait);border-radius:.6rem}}
.code strong{{font:700 1.5rem/1 ui-monospace,Consolas,monospace;letter-spacing:.04em}}
button,.jouer{{font:inherit;padding:.5rem .9rem;border-radius:.5rem;border:1px solid var(--accent);background:transparent;color:var(--accent);cursor:pointer;text-decoration:none;display:inline-block}}
button:focus-visible,a:focus-visible{{outline:3px solid var(--accent);outline-offset:2px}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:.3rem 1rem;margin:0}}
dt{{color:var(--doux)}}dd{{margin:0}}
img{{max-width:100%;height:auto;border-radius:.6rem;margin:1rem 0;display:block}}
a{{color:var(--accent)}}
footer{{max-width:44rem;margin:0 auto;padding:1rem;border-top:1px solid var(--trait);color:var(--doux);font-size:.85rem}}
</style>
</head>
<body>
<main>
{chr(10).join(corps)}
</main>
<footer><p>{e(MENTION)}</p></footer>
<script>
document.getElementById("copier").addEventListener("click",function(){{var b=this;navigator.clipboard.writeText(document.getElementById("code").textContent).then(function(){{b.textContent=b.dataset.fait}})}});
</script>
</body>
</html>
"""


def main(argv=None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    p = argparse.ArgumentParser(description="Page web d'une île Fortnite (HTML autonome, SEO et GEO).", add_help=True)
    p.add_argument("fichier", nargs="?", help="ile.json")
    p.add_argument("-o", "--sortie", help="fichier HTML à écrire (défaut : index.html à côté de ile.json)")
    p.add_argument("--controle", action="store_true", help="dit ce qui manque, sans rien écrire")
    p.add_argument("--modele", action="store_true", help="affiche un ile.json à remplir")
    a = p.parse_args(argv)
    if a.modele:
        print(json.dumps(MODELE, ensure_ascii=False, indent=2))
        return 0
    if not a.fichier:
        print(__doc__)
        return 1
    try:
        ile = json.loads(Path(a.fichier).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as err:
        print(f"ile.json illisible : {err}", file=sys.stderr)
        return 1
    bloquants, conseils = controle(ile)
    for b in bloquants:
        print(f"✗ {b}")
    for c in conseils:
        print(f"· {c}")
    if bloquants:
        print(f"{len(bloquants)} point(s) bloquant(s) : page non générée.")
        return 1
    if a.controle:
        print("ile.json complet." if not conseils else f"{len(conseils)} conseil(s), rien de bloquant.")
        return 0
    sortie = Path(a.sortie) if a.sortie else Path(a.fichier).with_name("index.html")
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_bytes(page(ile).encode("utf-8"))
    print(f"Page écrite : {sortie} — titre « {titre_page(ile)} » ({len(titre_page(ile))} caractères).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
