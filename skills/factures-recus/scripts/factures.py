"""Factures et reçus : inventaire d'un dossier en vrac, relevé à compléter, contrôle, rangement sous un nom clair
(`AAAA-MM-JJ Fournisseur - Facture - Objet.pdf`), tableau pour le comptable. Bibliothèque standard, aucun réseau.

Usage :
  python factures.py inventaire <dossier> [--releve releve.csv] [--json]
      liste les documents (PDF, images, XML, e-mails), repère les doublons (même contenu), pré-remplit ce qui se lit
      sans deviner (factures électroniques Factur-X, CII, UBL ; date dans le nom du fichier) et écrit le relevé à
      compléter ; un relevé déjà là garde ses lignes remplies, seuls les nouveaux fichiers s'ajoutent
  python factures.py verifier <releve.csv> [--json]
      contrôle chaque ligne : date, fournisseur, montants (HT + TVA = TTC), fichier présent, doublons
  python factures.py ranger <releve.csv> --vers <dossier> [--appliquer] [--deplacer] [--json]
      sans --appliquer : montre le plan seulement. Avec : COPIE chaque document sous <dossier>/<année>/<catégorie>/
      <nom clair> (les originaux restent ; --deplacer pour les déplacer) ; jamais d'écrasement ; journal écrit
  python factures.py comptable <releve.csv> [--sortie comptable.csv] [--annee AAAA] [--json]
      tableau pour le comptable (point-virgule, virgule décimale, s'ouvre dans Excel), trié par date, et totaux
      par catégorie

Relevé (CSV, point-virgule) : fichier;type;date;fournisseur;numero;objet;categorie;ht;tva;ttc;devise;paiement;note
Dates en AAAA-MM-JJ (JJ/MM/AAAA accepté), montants « 1 234,56 » ou « 1234.56 ». Code de sortie : 0 bon, 1 à
corriger, 3 erreur d'utilisation."""
import csv
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import facturx  # noqa: E402

COLS = ["fichier", "type", "date", "fournisseur", "numero", "objet", "categorie", "ht", "tva", "ttc", "devise",
        "paiement", "note"]
DOC_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".tif", ".tiff", ".xml", ".eml", ".txt",
           ".html", ".htm"}
TYPES = {"facture": "Facture", "recu": "Reçu", "reçu": "Reçu", "avoir": "Avoir", "note de frais": "Note de frais",
         "releve": "Relevé", "relevé": "Relevé", "devis": "Devis", "ticket": "Reçu"}
CATEGORIES = ["marchandises", "emballage-expedition", "logiciels-abonnements", "materiel", "telephone-internet",
              "deplacements", "formation", "banque-frais", "honoraires", "marketing", "impots-taxes", "autres"]
# Fournisseur → catégorie proposée (marquée « devinée » : à confirmer) ; les vendeurs de tout (Amazon…) restent vides.
GUESS = {"emballage-expedition": "colissimo la poste laposte mondial relay chronopost boxtal sendcloud ups dhl dpd "
                                 "gls packlink",
         "logiciels-abonnements": "shopify canva adobe google microsoft notion envato epidemic wix ovh o2switch ionos "
                                  "hostinger squarespace woocommerce etsy openai anthropic",
         "telephone-internet": "orange sfr free bouygues sosh red",
         "deplacements": "sncf blablacar uber bolt totalenergies",
         "banque-frais": "stripe paypal sumup qonto shine revolut",
         "materiel": "ldlc darty boulanger fnac materiel.net"}
LEGAL = re.compile(r"\b(?:sas|sasu|sarl|eurl|sa|snc|ltd|limited|gmbh|inc|llc|bv|srl|s\.a\.r\.l\.|s\.a\.s\.)\b\.?", re.I)
MONTHS = {m: i for i, m in enumerate("janvier fevrier mars avril mai juin juillet aout septembre octobre novembre "
                                     "decembre".split(), 1)}
WIN_RESERVED = re.compile(r"(?i)^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$")


# ------------------------------------------------------------------------------------------ lectures
def parse_date(raw) -> str:
    """« 2026-03-15 », « 15/03/2026 », « 15-03-2026 », « 15 mars 2026 », « 20260315 » → « 2026-03-15 » ; sinon ""."""
    s = str(raw or "").strip().lower()
    for rx, order in ((r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", "ymd"), (r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", "dmy"),
                      (r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", "ymd")):
        m = re.search(rx, s)
        if m:
            a, b, c = (int(x) for x in m.groups())
            y, mo, d = (a, b, c) if order == "ymd" else (c, b, a)
            return _valid(y, mo, d)
    m = re.search(r"(\d{1,2})(?:er)?\s+([a-zéû]+)\.?\s+(\d{4})", s)
    if m:
        name = m.group(2).replace("é", "e").replace("û", "u")
        mo = next((n for k, n in MONTHS.items() if k.startswith(name[:4]) and len(name) >= 3), 0)
        return _valid(int(m.group(3)), mo, int(m.group(1)))
    return ""


def _valid(y, mo, d) -> str:
    try:
        return date(y, mo, d).isoformat() if 1990 <= y <= 2100 else ""
    except ValueError:
        return ""


def parse_amount(raw):
    """« 1 234,56 € », « 1234.56 », « 1,234.56 », « -12,00 » → Decimal ; "" ou illisible → None."""
    s = re.sub(r"[^\d,.\-]", "", str(raw or "").replace("\xa0", " ").replace(" ", ""))
    if not s or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".") if re.search(r",\d{1,2}$", s) else s.replace(",", "")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def fr_amount(v) -> str:
    return "" if v is None else f"{v:.2f}".replace(".", ",")


def short_vendor(name) -> str:
    """Nom de fournisseur court pour un nom de fichier : sans forme juridique, 40 caractères au plus."""
    s = LEGAL.sub("", str(name or ""))
    s = " ".join(s.replace(",", " ").split()).strip(" -.")
    if s.isupper() and len(s) > 4:
        s = s.title()
    return s[:40].strip()


def guess_category(vendor) -> str:
    low = f" {str(vendor or '').lower()} "
    for cat, words in GUESS.items():
        if any(re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", low) for w in words.split()):
            return cat
    return ""


def safe_part(text, n=60) -> str:
    """Morceau de nom de fichier valable sous Windows, macOS et Linux."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(text or ""))
    s = " ".join(s.split()).strip(" .")[:n].strip(" .")
    return f"_{s}" if WIN_RESERVED.match(s) else s


def clean_name(row) -> str:
    """Nom clair : « AAAA-MM-JJ Fournisseur - Facture - Objet.ext »."""
    ext = Path(row["fichier"]).suffix.lower()
    kind = TYPES.get(str(row.get("type") or "").strip().lower(), str(row.get("type") or "").strip() or "Facture")
    parts = [p for p in (safe_part(short_vendor(row["fournisseur"]), 40), safe_part(kind, 20),
                         safe_part(row.get("objet"), 50)) if p]
    return f"{parse_date(row['date'])} {' - '.join(parts)}{ext}"


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------ relevé
def read_releve(path) -> list:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    return [{c: (r.get(c) or "").strip() for c in COLS} for r in rows]


def write_releve(path, rows) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:  # BOM : Excel l'ouvre en UTF-8
        w = csv.DictWriter(fh, fieldnames=COLS, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def documents(folder) -> list:
    """Documents d'un dossier (sous-dossiers compris, liens jamais suivis), chemins relatifs triés."""
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not os.path.islink(os.path.join(root, d)))
        for f in sorted(files):
            p = Path(root, f)
            if p.suffix.lower() in DOC_EXT and not p.is_symlink() and not f.startswith("."):
                out.append(p.relative_to(folder).as_posix())
    return out


def inventory(folder, releve) -> dict:
    folder = Path(folder)
    old = {r["fichier"]: r for r in read_releve(releve)} if releve.is_file() else {}
    rows, seen, dups, filled = [], {}, [], 0
    for rel in documents(folder):
        if releve.resolve() == (folder / rel).resolve():
            continue
        digest = sha256(folder / rel)
        if digest in seen:
            dups.append([seen[digest], rel])
        seen.setdefault(digest, rel)
        if rel in old:
            rows.append(old[rel])
            continue
        row = dict.fromkeys(COLS, "")
        row["fichier"] = rel
        got = facturx.read(folder / rel)
        if got:
            filled += 1
            row.update({k: got.get(k, "") for k in ("type", "date", "numero", "objet", "devise")})
            row["fournisseur"] = short_vendor(got.get("fournisseur"))
            for k in ("ht", "tva", "ttc"):
                row[k] = fr_amount(parse_amount(got.get(k)))
            row["note"] = f"lu dans la facture électronique ({got['format']})"
        else:
            row["date"] = parse_date(Path(rel).stem)
        if not row["categorie"]:
            cat = guess_category(row["fournisseur"])
            if cat:
                row["categorie"] = cat
                row["note"] = (row["note"] + " ; " if row["note"] else "") + "catégorie devinée"
        if digest in seen and seen[digest] != rel:
            row["note"] = (row["note"] + " ; " if row["note"] else "") + f"doublon de {seen[digest]}"
        rows.append(row)
    write_releve(releve, rows)
    todo = sum(1 for r in rows if not (r["date"] and r["fournisseur"] and r["ttc"]))
    return {"releve": str(releve), "documents": len(rows), "factures_electroniques": filled, "doublons": dups,
            "a_completer": todo}


def problems(rows, base) -> list:
    """[(ligne du relevé, fichier, problème)]."""
    out, keys = [], {}
    for i, r in enumerate(rows, 2):
        f = r["fichier"]
        if not f or not (base / f).is_file():
            out.append((i, f, "fichier introuvable"))
        if not parse_date(r["date"]):
            out.append((i, f, "date absente ou illisible"))
        if not r["fournisseur"]:
            out.append((i, f, "fournisseur absent"))
        ht, tva, ttc = (parse_amount(r[k]) for k in ("ht", "tva", "ttc"))
        if ttc is None:
            out.append((i, f, "montant TTC absent ou illisible"))
        elif ht is not None and tva is not None and abs(ht + tva - ttc) > Decimal("0.02"):
            out.append((i, f, f"HT + TVA ({fr_amount(ht + tva)}) ≠ TTC ({fr_amount(ttc)})"))
        if r["categorie"] and r["categorie"] not in CATEGORIES:
            out.append((i, f, f"catégorie inconnue « {r['categorie']} » (liste : {', '.join(CATEGORIES)})"))
        key = (r["fournisseur"].lower(), r["numero"].lower()) if r["numero"] else None
        if key and key in keys:
            out.append((i, f, f"même fournisseur et même numéro que la ligne {keys[key]} : doublon ?"))
        elif key:
            keys[key] = i
    return out


def plan(rows, base, dest) -> tuple:
    """→ ([(source, destination)], [lignes écartées]). Destination : <dest>/<année>/<catégorie>/<nom clair>."""
    blocking = ("fichier introuvable", "date ", "fournisseur absent", "montant TTC", "HT + TVA")
    bad = {i for i, _f, p in problems(rows, base) if p.startswith(blocking)}  # catégorie, doublon : pas bloquants
    moves, skipped, taken = [], [], set()
    for i, r in enumerate(rows, 2):
        if i in bad:
            skipped.append(r["fichier"])
            continue
        src = base / r["fichier"]
        folder = dest / parse_date(r["date"])[:4] / (safe_part(r["categorie"], 40) or "a-classer")
        name = clean_name(r)
        target, n = folder / name, 2
        while target.exists() or str(target).lower() in taken:
            target = folder / f"{Path(name).stem} ({n}){Path(name).suffix}"
            n += 1
        taken.add(str(target).lower())
        moves.append((src, target))
    return moves, skipped


def accountant(rows, year=None) -> tuple:
    out, totals = [], {}
    for r in sorted(rows, key=lambda r: (parse_date(r["date"]), r["fournisseur"].lower())):
        d = parse_date(r["date"])
        if year and not d.startswith(str(year)):
            continue
        ht, tva, ttc = (parse_amount(r[k]) for k in ("ht", "tva", "ttc"))
        sign = -1 if (r["type"] or "").lower() == "avoir" and ttc is not None and ttc > 0 else 1
        cat = r["categorie"] or "a-classer"
        t = totals.setdefault(cat, [Decimal(0), Decimal(0), Decimal(0), 0])
        for j, v in enumerate((ht, tva, ttc)):
            t[j] += sign * (v or 0)
        t[3] += 1
        out.append([f"{d[8:10]}/{d[5:7]}/{d[:4]}" if d else "", r["fournisseur"], r["numero"], r["objet"], cat,
                    fr_amount(sign * ht if ht is not None else None), fr_amount(sign * tva if tva is not None else None),
                    fr_amount(sign * ttc if ttc is not None else None), r["devise"] or "EUR", r["paiement"],
                    r["type"] or "Facture", r["fichier"]])
    return out, totals


# ------------------------------------------------------------------------------------------ commandes
def opt(args, name, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
        raise SystemExit(f"✗ {name} attend une valeur")
    return default


def main(argv) -> int:
    if not argv or argv[0] in ("-h", "--help", "aide"):
        print(__doc__.strip())
        return 0
    cmd, args = argv[0], argv[1:]
    as_json = "--json" in args
    pos = [a for i, a in enumerate(args) if not a.startswith("--")
           and not (i and args[i - 1] in ("--releve", "--vers", "--sortie", "--annee"))]
    if cmd not in ("inventaire", "verifier", "ranger", "comptable") or not pos:
        print(f"✗ commande ou argument manquant : {' '.join(argv)}\n\n{__doc__.strip()}")
        return 3
    target = Path(pos[0])
    if cmd == "inventaire":
        if not target.is_dir():
            print(f"✗ dossier introuvable : {target}")
            return 3
        res = inventory(target, Path(opt(args, "--releve", str(target / "releve.csv"))))
        if as_json:
            print(json.dumps(res, ensure_ascii=False, indent=1))
            return 0
        print(f"🧾 {res['documents']} document(s) dans {target} ; {res['factures_electroniques']} facture(s) "
              f"électronique(s) lue(s) ; relevé : {res['releve']}")
        for a, b in res["doublons"]:
            print(f"  ⚠️ même contenu : {a} = {b}")
        print(f"→ {res['a_completer']} ligne(s) à compléter : lire chaque document et remplir date, fournisseur, "
              "objet, catégorie et montants (jamais deviner un montant), puis `verifier`.")
        return 0
    if not target.is_file():
        print(f"✗ relevé introuvable : {target}")
        return 3
    rows, base = read_releve(target), target.resolve().parent
    if cmd == "verifier":
        found = problems(rows, base)
        if as_json:
            print(json.dumps([{"ligne": i, "fichier": f, "probleme": p} for i, f, p in found], ensure_ascii=False,
                             indent=1))
        else:
            print(f"🧾 {len(rows)} ligne(s) ; " + (f"{len(found)} point(s) à corriger :" if found else "tout est bon."))
            for i, f, p in found:
                print(f"  ⚠️ ligne {i} ({f}) : {p}")
        return 1 if found else 0
    if cmd == "ranger":
        dest = opt(args, "--vers")
        if not dest:
            print("✗ ranger : --vers <dossier> obligatoire")
            return 3
        moves, skipped = plan(rows, base, Path(dest))
        apply, move = "--appliquer" in args, "--deplacer" in args
        if apply:
            log = Path(dest) / "journal-rangement.csv"
            new = not log.exists()
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as fh:
                w = csv.writer(fh, delimiter=";")
                if new:
                    w.writerow(["source", "destination", "action", "date"])
                for src, dst in moves:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    (shutil.move if move else shutil.copy2)(str(src), str(dst))
                    w.writerow([str(src), str(dst), "déplacé" if move else "copié", date.today().isoformat()])
        if as_json:
            print(json.dumps({"applique": apply, "deplace": move, "rangement": [[str(s), str(d)] for s, d in moves],
                              "ecartes": skipped}, ensure_ascii=False, indent=1))
        else:
            verb = ("déplacé(s)" if move else "copié(s)") if apply else "à ranger (plan seulement)"
            print(f"🗂️ {len(moves)} document(s) {verb} :")
            for src, dst in moves:
                print(f"  {src.relative_to(base) if src.is_relative_to(base) else src} → {dst}")
            for f in skipped:
                print(f"  ⏸ {f} : écarté (date, fournisseur ou montant à corriger : `verifier`)")
            if not apply:
                print("→ rien n'a bougé ; relancer avec --appliquer après l'accord de l'utilisateur.")
        return 1 if skipped else 0
    out, totals = accountant(rows, opt(args, "--annee"))
    sortie = Path(opt(args, "--sortie", str(base / "comptable.csv")))
    with open(sortie, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["Date", "Fournisseur", "N° de facture", "Objet", "Catégorie", "Montant HT", "TVA", "Montant TTC",
                    "Devise", "Moyen de paiement", "Type", "Fichier"])
        w.writerows(out)
    summary = {cat: {"ht": fr_amount(t[0]), "tva": fr_amount(t[1]), "ttc": fr_amount(t[2]), "documents": t[3]}
               for cat, t in sorted(totals.items())}
    todo = len({i for i, _f, _p in problems(rows, base)})
    if as_json:
        print(json.dumps({"sortie": str(sortie), "lignes": len(out), "totaux": summary, "lignes_a_corriger": todo},
                         ensure_ascii=False, indent=1))
    else:
        print(f"📊 {len(out)} ligne(s) → {sortie}")
        for cat, t in summary.items():
            print(f"  {cat} : {t['documents']} document(s), HT {t['ht']} · TVA {t['tva']} · TTC {t['ttc']}")
        if todo:
            print(f"  ⚠️ {todo} ligne(s) du relevé à corriger (`verifier`) : le tableau n'est pas encore à envoyer")
    return 1 if todo else 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    sys.exit(main(sys.argv[1:]))
