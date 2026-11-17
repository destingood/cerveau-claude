#!/usr/bin/env python3
"""Vérifie les images d'une île Fortnite avant de les envoyer au portail créateur : format, dimensions exactes,
poids, transparence du logo, et jeu complet (les cinq images obligatoires depuis le 22/10/2026).

    python medias.py dossier-des-images/
    python medias.py paysage-logo.png paysage-art.png portrait-logo.png portrait-art.png logo.png fond-lobby.jpg
    python medias.py dossier/ --json

Le rôle de chaque image est déduit de ses dimensions :
  1920 × 1080  miniature paysage, deux exemplaires (avec illustration et logo ; illustration seule), PNG ou JPG, 5 Mo au plus
  1440 × 1920  miniature portrait, deux exemplaires (mêmes deux versions), PNG ou JPG
  1440 × 608   logo du nom de l'île, PNG à fond transparent
  2048 × 1024  fond du lobby (facultatif), PNG ou JPG, 10 Mo au plus

Le script lit l'en-tête des fichiers, pas leur contenu : il ne voit ni les armes, ni le texte, ni la zone à laisser
libre. La liste de ce qu'Epic refuse sur une miniature est dans references/03-fiche-ile.md.
Bibliothèque standard uniquement, aucun accès réseau. Dimensions lues dans la documentation d'Epic le 14/11/2026."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

MO = 1024 * 1024
ROLES = {(1920, 1080): "miniature paysage", (1440, 1920): "miniature portrait", (1440, 608): "logo du nom",
         (2048, 1024): "fond du lobby"}
ATTENDUS = {"miniature paysage": 2, "miniature portrait": 2, "logo du nom": 1}
POIDS_MAX = {"miniature paysage": 5 * MO, "fond du lobby": 10 * MO}
EXTENSIONS = {".png", ".jpg", ".jpeg"}


def lire_image(chemin: Path) -> dict:
    """→ {format, largeur, hauteur, transparence, octets} lus dans l'en-tête ; format None si ce n'est ni PNG ni JPEG."""
    info = {"fichier": chemin.name, "format": None, "largeur": 0, "hauteur": 0, "transparence": False,
            "octets": chemin.stat().st_size}
    with open(chemin, "rb") as f:
        tete = f.read(26)
        if tete[:8] == b"\x89PNG\r\n\x1a\n" and tete[12:16] == b"IHDR":
            info["format"] = "PNG"
            info["largeur"], info["hauteur"] = struct.unpack(">II", tete[16:24])
            info["transparence"] = tete[25] in (4, 6)  # type de couleur avec canal alpha
            if not info["transparence"]:  # palette ou couleurs pleines : un bloc tRNS peut encore porter la transparence
                f.seek(8)
                while True:
                    bloc = f.read(8)
                    if len(bloc) < 8:
                        break
                    taille, nom = struct.unpack(">I4s", bloc)
                    if nom == b"tRNS":
                        info["transparence"] = True
                        break
                    if nom in (b"IDAT", b"IEND"):
                        break
                    f.seek(taille + 4, 1)
        elif tete[:2] == b"\xff\xd8":
            info["format"] = "JPG"
            f.seek(2)
            while True:
                marque = f.read(4)
                if len(marque) < 4 or marque[0] != 0xFF:
                    break
                code, taille = marque[1], struct.unpack(">H", marque[2:4])[0]
                if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):  # bloc SOF : dimensions de l'image
                    donnees = f.read(5)
                    info["hauteur"], info["largeur"] = struct.unpack(">HH", donnees[1:5])
                    break
                f.seek(taille - 2, 1)
    return info


def plus_proche(largeur: int, hauteur: int) -> tuple | None:
    """Le format officiel visé par une image aux mauvaises dimensions : même proportion, à 3 % près."""
    if not largeur or not hauteur:
        return None
    for (l, h) in ROLES:
        if abs(largeur / hauteur - l / h) / (l / h) < 0.03:
            return (l, h)
    return None


def controle(chemins: list) -> dict:
    images, notes = [], []
    for chemin in chemins:
        try:
            info = lire_image(chemin)
        except (OSError, struct.error) as err:
            notes.append(("bloquant", f"{chemin.name} : illisible ({err})"))
            continue
        if not info["format"]:
            notes.append(("bloquant", f"{chemin.name} : ni PNG ni JPG (seuls formats acceptés)"))
            continue
        role = ROLES.get((info["largeur"], info["hauteur"]))
        info["role"] = role
        images.append(info)
        taille = f"{info['largeur']} × {info['hauteur']}"
        if not role:
            vise = plus_proche(info["largeur"], info["hauteur"])
            if vise:
                notes.append(("bloquant", f"{chemin.name} : {taille}, attendu exactement {vise[0]} × {vise[1]} "
                                          f"({ROLES[vise]})"))
            else:
                notes.append(("attention", f"{chemin.name} : {taille} ne correspond à aucune image de la fiche"))
            continue
        if role in POIDS_MAX and info["octets"] > POIDS_MAX[role]:
            notes.append(("bloquant", f"{chemin.name} ({role}) : {info['octets'] / MO:.1f} Mo, "
                                      f"{POIDS_MAX[role] // MO} Mo au plus"))
        if role == "logo du nom" and not (info["format"] == "PNG" and info["transparence"]):
            notes.append(("bloquant", f"{chemin.name} (logo du nom) : PNG à fond transparent attendu "
                                      f"(reçu {info['format']}{'' if info['transparence'] else ' sans transparence'})"))
        elif role != "logo du nom" or info["transparence"]:
            notes.append(("bon", f"{chemin.name} : {role}, {taille}, {info['format']}, {info['octets'] / MO:.1f} Mo"))
    for role, nombre in ATTENDUS.items():
        trouve = sum(1 for i in images if i.get("role") == role)
        if trouve < nombre:
            detail = " (une avec illustration et logo, une avec l'illustration seule)" if nombre == 2 else ""
            notes.append(("bloquant", f"{role} : {trouve} image(s) sur {nombre} obligatoire(s){detail}"))
        elif trouve > nombre:
            notes.append(("attention", f"{role} : {trouve} images pour {nombre} emplacement(s) ; les autres servent à "
                                       "un test A/B de miniature, qui prend le jeu complet en variante B"))
    if not any(i.get("role") == "fond du lobby" for i in images):
        notes.append(("attention", "pas de fond de lobby (2048 × 1024) : facultatif"))
    return {"images": images, "notes": notes,
            "bloquants": sum(1 for niveau, _ in notes if niveau == "bloquant")}


def main(argv=None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    args = list(sys.argv[1:] if argv is None else argv)
    en_json = "--json" in args
    args = [x for x in args if x != "--json"]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if args else 1
    chemins = []
    for x in args:
        p = Path(x)
        if p.is_dir():
            chemins += sorted(q for q in p.iterdir() if q.is_file() and q.suffix.lower() in EXTENSIONS)
        elif p.is_file():
            chemins.append(p)
        else:
            print(f"introuvable : {x}", file=sys.stderr)
            return 1
    r = controle(chemins)
    if en_json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 1 if r["bloquants"] else 0
    marque = {"bloquant": "✗", "attention": "!", "bon": "✓"}
    for niveau, texte in r["notes"]:
        print(f"{marque[niveau]} {texte}")
    print(f"\n{len(r['images'])} image(s) lue(s), {r['bloquants']} point(s) bloquant(s).")
    print("Non contrôlé ici : 200 px libres en haut et en bas des miniatures (le logo y est posé), armes tenues par un "
          "personnage et présentes dans l'île, ni viseur sur une tête ni arme pointée vers le joueur, pas de fond uni.")
    return 1 if r["bloquants"] else 0


if __name__ == "__main__":
    sys.exit(main())
