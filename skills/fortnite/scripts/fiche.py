#!/usr/bin/env python3
"""Contrôle la fiche d'une île Fortnite avant publication : titre, description, tags, genre, texte de la miniature.

    python fiche.py --titre "NEON 2V2 ZONE WARS" --tags "ZoneWars, 2v2, Competitive" --genre "Battle Royale"
    python fiche.py --titre "…" --description "…" --miniature "TEXTE SUR LA MINIATURE"
    python fiche.py fiche.json                       # {"titres": ["…", "…"], "description": "…", "tags": […], "genre": "…"}
    python fiche.py --titre "…" --concurrents titres.txt   # un titre par ligne (sortie de tendances.py --titres)
    python fiche.py … --json

Trois niveaux : ✗ bloquant (une règle écrite d'Epic), ! attention (un conseil d'Epic ou un risque), ✓ bon.
Plusieurs titres : classés du plus sûr au plus risqué. Aucune note sur 100 : rien ne permet d'en calibrer une.

Ce que le script ne sait pas : la longueur maximale d'un titre et d'une description (Epic ne la publie pas ; le
portail créateur la montre à la saisie), ni ce que la recherche du jeu indexe au-delà du nom et des tags.
Bibliothèque standard uniquement, aucun accès réseau. Règles et listes lues le 14/11/2026 (references/sources.md)."""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

# Règles des développeurs Fortnite (legal.epicgames.com/fortnite/developer-rules, mise à jour du 29/04/2026) :
# (motif, règle, explication). Elles valent pour le nom, la description, la miniature et le texte de chargement.
INTERDITS = [
    (r"v[\s-]?bucks?", "1.13", "ne pas mentionner les V-Bucks"),
    (r"battle\s?pass|passe de combat", "1.13", "ne pas mentionner le Passe de combat"),
    (r"[$€£]|\b(?:dollars?|euros?)\b", "1.13", "ne pas mentionner de monnaie réelle"),
    (r"\brewards?\b|\br[ée]compenses?\b", "1.13", "ne pas mentionner de récompenses"),
    (r"\bafk\b", "1.13", "le terme « AFK » est interdit"),
    (r"\bxp\b", "1.13", "le terme « XP » est interdit"),
    (r"coin\s?farm|coin\s?slide", "1.13", "« Coin farm » et « Coin slide » sont interdits"),
    (r"https?://|www\.|\b[\w-]+\.(?:com|gg|fr|net|io|tv|me)\b", "1.2", "aucune adresse web"),
    (r"qr\s?code", "1.2", "aucun QR code"),
    (r"\bdms?\b|\bmp\b|messages? priv[ée]s?|private messages?", "1.2", "aucune demande de message privé"),
    (r"support[\s-]a[\s-]creator|creator code|code cr[ée]ateur|use code", "4.2", "ne pas solliciter son code créateur"),
    (r"\b(?:discord|youtube|tiktok|twitch|instagram|twitter|snapchat)\b|\babonne[sz]?[\s-]?(?:toi|vous)\b|\bsubscribe\b"
     r"|\bfollow (?:me|us)\b", "4.3", "aucun appel à l'action hors de Fortnite"),
]

# Les 13 genres d'Epic (How Discover Works) : un seul par île, il décide de la rangée de genre.
GENRES = ["Adventure & RPG", "Battle Royale", "Deathrun & Platformer", "Horror", "Music & Rhythm", "Party & Mini Games",
          "Roguelike", "Roleplaying & Social", "Shooter", "Simulation & Tycoon", "Sports & Racing", "Strategy", "Survival"]

# Tags officiels utiles à une map de combat ou d'entraînement (liste fermée d'Epic, orthographe exacte).
TAGS = ["1v1", "2v2", "3v3", "4v4", "5v5", "6v6", "7v7", "8v8", "Boxfight", "ZoneWars", "Free for All",
        "Team Free for All", "Gun Fight", "Gun Game", "One in the Chamber", "One Shot", "Search & Destroy",
        "Capture the Flag", "King of the Hill", "Battle Royale", "Aim Course", "Edit Course", "Practice", "Training",
        "Skills", "Tutorial", "Arena", "Attack", "Battle", "Building", "Competitive", "Fighting", "Melee", "PVP",
        "Shooter", "Sniper", "Teams", "Rounds", "Respawn", "Hardcore", "Classes", "Solo", "Duo", "Trios", "Squad"]
MAX_TAGS = 4

# Ce que les joueurs tapent pour trouver une map de combat : (motif dans le texte, terme, tag officiel, genre d'Epic).
TERMES = [
    (r"zone\s?wars?", "zone wars", "ZoneWars", "Battle Royale"),
    (r"box\s?fights?", "box fight", "Boxfight", None),
    (r"realistics?", "realistics", None, None),
    (r"\b([1-8])\s?v\s?\1\b", "NvN", None, None),
    (r"\bffa\b|free for all", "ffa", "Free for All", "Shooter"),
    (r"build\s?fights?", "build fight", "Building", None),
    (r"\baim\b", "aim", "Aim Course", "Shooter"),
    (r"edit (?:course|map|training|practice)", "edit course", "Edit Course", "Shooter"),
    (r"piece control", "piece control", "Practice", "Shooter"),
    (r"gun\s?game", "gun game", "Gun Game", "Shooter"),
    (r"red\s?(?:vs?\.?|versus)\s?blue", "red vs blue", "Teams", None),
    (r"\bpvp\b", "pvp", "PVP", None),
    (r"\bscrims?\b", "scrims", "Competitive", None),
    (r"\btdm\b|team deathmatch", "team deathmatch", "Team Free for All", "Shooter"),
    (r"one\s?shot", "one shot", "One Shot", "Shooter"),
    (r"\bsnipers?\b", "sniper", "Sniper", "Shooter"),
    (r"\barena\b|\bar[èe]ne\b", "arena", "Arena", "Shooter"),
    (r"warm\s?up", "warm up", "Practice", "Shooter"),
    (r"\btraining\b|\bentra[îi]nement\b", "training", "Training", "Shooter"),
    (r"\bpractice\b", "practice", "Practice", "Shooter"),
]
# Mots qui ne distinguent pas une map d'une autre : une fois retirés avec les termes du genre, il doit rester un nom.
BANALS = set("""best new the a an of and with for in on to map maps fortnite season saison chapter chapitre og pro
update updated fr eu na le la les un une de du des et avec pour meilleur meilleure nouvelle nouveau by solo duo trio
trios squad squads fast fun rapide""".split())
GENERIQUES = [r"best map", r"fun map", r"meilleure map", r"play with (?:your )?friends", r"joue avec tes amis",
              r"have fun", r"amuse[sz]?[- ]?(?:toi|vous)", r"good luck", r"bonne chance", r"enjoy"]


def norm(texte: str) -> str:
    """Minuscules, sans accents ni symboles : pour comparer deux titres."""
    t = unicodedata.normalize("NFKD", texte.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()


def termes(texte: str) -> list:
    """Termes de recherche présents dans le texte : [(terme, tag officiel ou None, genre ou None)]."""
    bas, vus = texte.lower(), []
    for motif, terme, tag, genre in TERMES:
        m = re.search(motif, bas)
        if m:
            if terme == "NvN":
                terme = tag = f"{m.group(1)}v{m.group(1)}"
            vus.append((terme, tag, genre))
    return vus


def interdits(texte: str) -> list:
    return [(re.search(motif, texte, re.I).group(0), regle, quoi) for motif, regle, quoi in INTERDITS
            if re.search(motif, texte, re.I)]


def nom_propre(titre: str) -> list:
    """Ce qui reste du titre une fois retirés les termes du genre et les mots banals : son nom."""
    bas = titre.lower()
    for motif, *_ in TERMES:
        bas = re.sub(motif, " ", bas)
    return [m for m in norm(bas).split() if m not in BANALS and not m.isdigit() and len(m) > 1]


def proche(a: str, b: str) -> float:
    """Ressemblance de deux titres : part des mots communs (Jaccard), 1.0 = mêmes mots."""
    x, y = set(norm(a).split()), set(norm(b).split())
    return len(x & y) / len(x | y) if x and y else 0.0


def controle_titre(titre: str, concurrents=()) -> dict:
    notes = []
    t = titre.strip()
    for mot, regle, quoi in interdits(t):
        notes.append(("bloquant", f"« {mot} » : {quoi} (règle {regle})"))
    vus = termes(t)
    if vus:
        notes.append(("bon", "contient ce que les joueurs tapent : " + ", ".join(v[0] for v in vus)))
    else:
        notes.append(("attention", "aucun terme de recherche du genre (zone wars, box fight, 1v1, ffa, aim…) : la "
                                   "recherche du jeu fait d'abord une correspondance exacte des mots"))
    nom = nom_propre(t)
    if nom:
        notes.append(("bon", "a un nom à lui : " + " ".join(nom)))
    else:
        notes.append(("attention", "le titre ne dit que le genre : Epic demande un nom qui aille « au-delà du genre », "
                                   "et un titre trop proche d'un autre réduit la visibilité dans Discover"))
    lettres = [c for c in t if c.isalpha()]
    if not lettres:
        notes.append(("bloquant", "aucune lettre dans le titre"))
    doubles = sorted(terme for motif, terme, *_ in TERMES
                     if terme != "NvN" and len(re.findall(motif, t.lower())) > 1)
    if doubles:
        notes.append(("attention", "terme répété dans le titre : " + ", ".join(doubles)))
    if len(vus) > 4:
        notes.append(("attention", f"{len(vus)} termes de genre empilés : le titre doit décrire une seule expérience "
                                   "(règle 1.13 : ne pas tromper sur ce qu'on va jouer)"))
    pires = sorted(((proche(t, c), c) for c in concurrents if c.strip()), reverse=True)[:1]
    if pires and pires[0][0] >= 1.0:
        notes.append(("bloquant", f"mêmes mots que « {pires[0][1].strip()} » : contrôle de similarité d'Epic, et "
                                  "copier le titre d'un autre est interdit (règle 1.6)"))
    elif pires and pires[0][0] >= 0.6:
        notes.append(("attention", f"très proche de « {pires[0][1].strip()} » ({pires[0][0]:.0%} de mots communs) : "
                                   "risque d'avertissement de similarité, donc de visibilité réduite"))
    elif concurrents:
        notes.append(("bon", f"distinct des {len([c for c in concurrents if c.strip()])} titres concurrents fournis"))
    return {"titre": t, "caracteres": len(t), "termes": [v[0] for v in vus], "notes": notes}


def controle_tags(tags: list, titre: str = "") -> list:
    notes = []
    propres = [x.strip() for x in tags if x.strip()]
    officiels = {norm(x).replace(" ", ""): x for x in TAGS}
    if len(propres) > MAX_TAGS:
        notes.append(("bloquant", f"{len(propres)} tags : quatre au plus par île"))
    vus = set()
    for tag in propres:
        cle = norm(tag).replace(" ", "")
        if cle in vus:
            notes.append(("attention", f"tag en double : {tag}"))
        vus.add(cle)
        if cle not in officiels:
            notes.append(("attention", f"« {tag} » n'est pas dans la liste des tags de combat de cette skill : vérifie "
                                       "son orthographe dans la liste officielle (les tags sont une liste fermée)"))
    attendus = [tag for _, tag, _ in termes(titre) if tag]
    manquants = [x for x in dict.fromkeys(attendus) if norm(x).replace(" ", "") not in vus]
    tailles = {norm(x) for x in propres if re.fullmatch(r"\dv\d", norm(x))}
    titre_tailles = {f"{x}v{y}" for x, y in re.findall(r"\b([1-8])\s?v\s?([1-8])\b", titre.lower())}
    if tailles and titre_tailles and not tailles & titre_tailles:
        notes.append(("attention", f"le titre annonce {', '.join(sorted(titre_tailles))} et les tags "
                                   f"{', '.join(sorted(tailles))} : la fiche doit décrire la même partie"))
    if manquants and len(propres) < MAX_TAGS:
        notes.append(("attention", "tags qui correspondent au titre et ne sont pas posés : " + ", ".join(manquants)))
    elif propres and not notes:
        notes.append(("bon", f"{len(propres)} tag(s), tous dans la liste officielle"))
    if propres and len(propres) < MAX_TAGS:
        notes.append(("attention", f"{MAX_TAGS - len(propres)} emplacement(s) de tag libre(s) : les tags servent à la "
                                   "recherche du jeu"))
    if not propres:
        notes.append(("attention", "aucun tag : quatre emplacements, qui servent à la recherche du jeu"))
    return notes


def controle_genre(genre: str, titre: str) -> list:
    notes = []
    g = genre.strip()
    connus = {norm(x): x for x in GENRES}
    if norm(g) not in connus:
        return [("bloquant", f"« {g} » n'est pas un des 13 genres : " + ", ".join(GENRES))]
    g = connus[norm(g)]
    attendus = [(terme, ge) for terme, _, ge in termes(titre) if ge]
    contraires = sorted({f"{terme} → {ge}" for terme, ge in attendus if ge != g})
    if contraires and not any(ge == g for _, ge in attendus):
        notes.append(("attention", f"genre choisi : {g} ; la définition d'Epic range plutôt " + ", ".join(contraires)
                      + ". Vérifie où sont classées les maps concurrentes : tendances.py ile <code>"))
    else:
        notes.append(("bon", f"genre {g} : il décide de la rangée de genre (une seule à la fois)"))
    return notes


def controle_description(description: str, titre: str = "") -> list:
    notes = []
    d = description.strip()
    if not d:
        return [("attention", "description vide : Epic conseille une accroche puis le détail du jeu")]
    for mot, regle, quoi in interdits(d):
        notes.append(("bloquant", f"« {mot} » : {quoi} (règle {regle})"))
    premiere = re.split(r"(?<=[.!?])\s|\n", d, maxsplit=1)[0]
    if len(premiere) > 160:
        notes.append(("attention", f"première phrase de {len(premiere)} caractères : l'accroche doit tenir en une ligne"))
    else:
        notes.append(("bon", f"accroche en une phrase ({len(premiere)} caractères)"))
    if re.search(r"\d", d):
        notes.append(("bon", "donne des faits chiffrés (joueurs, manches, zones)"))
    else:
        notes.append(("attention", "aucun chiffre : nombre de joueurs, durée d'une manche, nombre de zones… Epic demande "
                                   "une description propre à l'île, pas générique"))
    creux = [g for g in GENERIQUES if re.search(g, d, re.I)]
    if creux and len(norm(d).split()) < 40:
        notes.append(("attention", "formules qui valent pour n'importe quelle map : dis ce que celle-ci a de particulier"))
    if titre and termes(titre) and not {v[0] for v in termes(titre)} & {v[0] for v in termes(d)}:
        notes.append(("attention", "la description ne reprend aucun des termes du titre : la page de l'île sur "
                                   "fortnite.com affiche ce texte, et Google en tire son extrait"))
    for motif, terme, *_ in TERMES:
        n = len(re.findall(motif, d.lower()))
        if n > 3:
            notes.append(("attention", f"« {terme} » répété {n} fois : une liste de mots-clés n'est pas une description"))
    notes.append(("bon", f"{len(d)} caractères (limite non publiée par Epic : le portail la montre à la saisie)"))
    return notes


def controle_miniature(texte: str, titre: str = "") -> list:
    notes = [("bloquant", f"« {mot} » sur la miniature : {quoi} (règle {regle})") for mot, regle, quoi in interdits(texte)]
    if titre and norm(texte) and norm(texte) == norm(titre):
        notes.append(("attention", "le texte de la miniature répète le titre : le logo du nom de l'île est déjà posé "
                                   "par-dessus l'image par Fortnite"))
    if not notes:
        notes.append(("bon", "texte de miniature sans terme interdit"))
    return notes


def gravite(notes: list) -> tuple:
    return (sum(1 for n in notes if n[0] == "bloquant"), sum(1 for n in notes if n[0] == "attention"))


MARQUE = {"bloquant": "✗", "attention": "!", "bon": "✓"}


def affiche(titre_bloc: str, notes: list) -> None:
    print(f"\n{titre_bloc}")
    for niveau, texte in notes:
        print(f"  {MARQUE[niveau]} {texte}")


def main(argv=None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    p = argparse.ArgumentParser(description="Contrôle la fiche d'une île Fortnite avant publication.")
    p.add_argument("fichier", nargs="?", help="fiche.json (titre ou titres, description, tags, genre, miniature)")
    p.add_argument("--titre", action="append", default=[], help="un titre candidat (répétable)")
    p.add_argument("--description", default="")
    p.add_argument("--tags", default="", help="tags séparés par des virgules")
    p.add_argument("--genre", default="")
    p.add_argument("--miniature", default="", help="le texte écrit sur la miniature")
    p.add_argument("--concurrents", help="fichier de titres concurrents, un par ligne")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    titres, description, tags, genre, miniature = list(a.titre), a.description, a.tags, a.genre, a.miniature
    if a.fichier:
        try:
            f = json.loads(Path(a.fichier).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as err:
            print(f"fiche illisible : {err}", file=sys.stderr)
            return 1
        titres += [f["titre"]] if f.get("titre") else []
        titres += list(f.get("titres") or [])
        description = description or f.get("description", "")
        tags = tags or f.get("tags", "")
        genre = genre or f.get("genre", "")
        miniature = miniature or f.get("miniature", "")
    if isinstance(tags, str):
        tags = [x for x in tags.split(",") if x.strip()]
    if not titres:
        print(__doc__)
        return 1
    concurrents = []
    if a.concurrents:
        try:
            concurrents = Path(a.concurrents).read_text(encoding="utf-8-sig").splitlines()
        except OSError as err:
            print(f"fichier de titres concurrents illisible : {err}", file=sys.stderr)
            return 1
    resultats = sorted((controle_titre(t, concurrents) for t in titres), key=lambda r: gravite(r["notes"]))
    premier = resultats[0]["titre"]
    blocs = {"tags": controle_tags(tags, premier) if (tags or a.fichier or a.tags) else [],
             "genre": controle_genre(genre, premier) if genre else [],
             "description": controle_description(description, premier) if (description or a.fichier) else [],
             "miniature": controle_miniature(miniature, premier) if miniature else []}
    toutes = [n for r in resultats[:1] for n in r["notes"]] + [n for b in blocs.values() for n in b]
    bloquants, attentions = gravite(toutes)
    if a.json:
        print(json.dumps({"titres": resultats, **blocs, "bloquants": bloquants, "attentions": attentions},
                         ensure_ascii=False, indent=1))
        return 1 if bloquants else 0
    for i, r in enumerate(resultats, 1):
        affiche(f"Titre {i if len(resultats) > 1 else ''}« {r['titre']} » — {r['caracteres']} caractères".replace("  ", " "),
                r["notes"])
    for nom, notes in blocs.items():
        if notes:
            affiche(nom.capitalize(), notes)
    print(f"\n{bloquants} bloquant(s), {attentions} point(s) d'attention"
          + (f" (pour le titre « {premier} »)." if len(resultats) > 1 else "."))
    if not genre:
        print("Genre non donné (--genre) : c'est lui, pas les tags, qui décide de la rangée de genre dans Discover.")
    return 1 if bloquants else 0


if __name__ == "__main__":
    sys.exit(main())
