"""Tirage au sort d'un concours : équitable, vérifiable par n'importe qui, reproductible avec sa graine.

Chaque participant reçoit le score sha256(graine + « \\n » + nom normalisé) ; les plus petits scores gagnent, puis
viennent les suppléants. L'ordre de la liste ne compte pas, un doublon (même nom, casse, espaces ou « @ » près) ne
compte qu'une fois. La graine vient du module `secrets` (aléa du système) ; publier son empreinte AVANT le tirage
(commande engager) prouve ensuite qu'elle n'a pas été choisie après coup.

Usage :
  python tirage.py engager <participants> [--graine-fichier F]
      graine secrète écrite dans F (défaut : <participants>.graine.txt) ; affiche l'empreinte de la liste et celle de
      la graine, à publier avant le tirage
  python tirage.py tirer <participants> [--gagnants 1] [--suppleants 0] [--graine G | --graine-fichier F] [--json]
      sans graine : une graine neuve est tirée et affichée (tirage reproductible, mais pas engagé à l'avance)
  python tirage.py verifier <participants> --graine G [--gagnants 1] [--suppleants 0] [--engagement EMPREINTE]
      refait le tirage ; avec --engagement, vérifie que la graine est bien celle annoncée

<participants> : un nom par ligne (texte ; lignes vides et « # … » ignorées), ou un CSV avec --colonne <nom>.
Code de sortie : 0 bon, 1 engagement qui ne correspond pas, 3 erreur d'utilisation."""
import csv
import hashlib
import json
import re
import secrets
import sys
from pathlib import Path


def normalize(name) -> str:
    return " ".join(str(name).strip().lstrip("@").split()).casefold()


def load(path, column=None) -> tuple:
    """→ (participants dans l'ordre, sans doublon, sous leur première écriture ; nombre de doublons retirés)."""
    text = Path(path).read_text(encoding="utf-8-sig")
    if column:
        rows = list(csv.DictReader(text.splitlines(), delimiter=";" if text.count(";") > text.count(",") else ","))
        if rows and column not in rows[0]:
            raise SystemExit(f"✗ colonne « {column} » absente (colonnes : {', '.join(rows[0])})")
        names = [r.get(column) or "" for r in rows]
    else:
        names = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    seen, out, dups = set(), [], 0
    for n in names:
        key = normalize(n)
        if not key:
            continue
        if key in seen:
            dups += 1
            continue
        seen.add(key)
        out.append(" ".join(n.split()))
    return out, dups


def fingerprint(names) -> str:
    """Empreinte de la liste : sha256 des noms normalisés, triés (indépendante de l'ordre)."""
    return hashlib.sha256("\n".join(sorted(normalize(n) for n in names)).encode("utf-8")).hexdigest()


def commitment(seed) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def score(seed, name) -> str:
    return hashlib.sha256(f"{seed}\n{normalize(name)}".encode("utf-8")).hexdigest()


def draw(names, seed, winners=1, alternates=0) -> dict:
    ranked = sorted(names, key=lambda n: (score(seed, n), normalize(n)))
    return {"participants": len(names), "liste": fingerprint(names), "graine": seed, "engagement": commitment(seed),
            "gagnants": ranked[:winners], "suppleants": ranked[winners:winners + alternates],
            "scores": {n: score(seed, n)[:12] for n in ranked[:winners + alternates]}}


def opt(args, name, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 >= len(args):
            raise SystemExit(f"✗ {name} attend une valeur")
        return args[i + 1]
    return default


def number(args, name, default) -> int:
    raw = opt(args, name, str(default))
    if not re.fullmatch(r"\d{1,6}", raw):
        raise SystemExit(f"✗ {name} : un nombre entier attendu ({raw})")
    return int(raw)


def main(argv) -> int:
    if not argv or argv[0] in ("-h", "--help", "--aide", "aide"):
        print(__doc__.strip())
        return 0
    cmd, args = argv[0], argv[1:]
    valued = ("--gagnants", "--suppleants", "--graine", "--graine-fichier", "--engagement", "--colonne")
    pos = [a for i, a in enumerate(args) if not a.startswith("--") and not (i and args[i - 1] in valued)]
    if cmd not in ("engager", "tirer", "verifier") or len(pos) != 1:
        print(f"✗ commande ou liste de participants manquante : {' '.join(argv)}\n\n{__doc__.strip()}")
        return 3
    path = Path(pos[0])
    if not path.is_file():
        print(f"✗ liste introuvable : {path}")
        return 3
    names, dups = load(path, opt(args, "--colonne"))
    if not names:
        print("✗ aucun participant dans la liste")
        return 3
    seed_file = Path(opt(args, "--graine-fichier", str(path) + ".graine.txt"))
    if cmd == "engager":
        if seed_file.exists():
            print(f"✗ {seed_file} existe déjà : une graine est déjà engagée (la garder, ou choisir un autre fichier)")
            return 3
        seed = secrets.token_hex(16)
        seed_file.write_text(seed + "\n", encoding="utf-8")
        print(f"🎲 {len(names)} participant(s) ({dups} doublon(s) retiré(s)).\n"
              f"  Empreinte de la liste : {fingerprint(names)}\n  Empreinte de la graine : {commitment(seed)}\n"
              f"→ Publier ces deux empreintes AVANT le tirage. Graine secrète dans {seed_file} : ne la montrer "
              "qu'après, pour que chacun refasse le tirage.")
        return 0
    seed = opt(args, "--graine")
    if seed is None and ("--graine-fichier" in args or seed_file.is_file()):  # la graine engagée, si elle existe
        try:
            seed = seed_file.read_text(encoding="utf-8").strip()
        except OSError:
            print(f"✗ graine introuvable : {seed_file}")
            return 3
    if seed is None and cmd == "verifier":
        print("✗ verifier : --graine (ou --graine-fichier) obligatoire")
        return 3
    fresh = seed is None
    seed = secrets.token_hex(16) if fresh else seed
    res = draw(names, seed, number(args, "--gagnants", 1), number(args, "--suppleants", 0))
    res["doublons_retires"] = dups
    promised = opt(args, "--engagement")
    res["engagement_ok"] = None if promised is None else promised.strip().lower() == res["engagement"]
    if "--json" in args:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(f"🎲 Tirage parmi {res['participants']} participant(s) ({dups} doublon(s) retiré(s))")
        for i, n in enumerate(res["gagnants"], 1):
            print(f"  🏆 {i}. {n}  (score {res['scores'][n]})")
        for i, n in enumerate(res["suppleants"], 1):
            print(f"  ↪ suppléant {i} : {n}  (score {res['scores'][n]})")
        print(f"  Graine : {seed}\n  Empreinte de la liste : {res['liste']}\n  Empreinte de la graine : {res['engagement']}")
        if fresh:
            print("  (graine tirée à l'instant : publie-la avec le résultat ; pour un tirage engagé à l'avance, "
                  "`engager` d'abord)")
        if promised is not None:
            print("  ✓ graine conforme à l'empreinte annoncée" if res["engagement_ok"]
                  else "  ✗ cette graine ne correspond PAS à l'empreinte annoncée")
    return 1 if res["engagement_ok"] is False else 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    sys.exit(main(sys.argv[1:]))
