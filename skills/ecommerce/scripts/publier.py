#!/usr/bin/env python3
"""Publication par API officielle, sur les comptes de l'utilisateur, après une configuration unique.

- Page Facebook (post, lien, programmation jusqu'à 75 jours) et Instagram professionnel (image JPEG ou Reel) : API
  Graph de Meta, accès « Standard » d'une app dont l'utilisateur a un rôle (pas d'App Review pour ses propres comptes).
- Pinterest : `pinterest-csv` prépare le fichier de l'import en masse de Pinterest (fonction officielle et gratuite,
  l'utilisateur dépose le fichier) ; l'API v5 (`pinterest`) ne publie en public qu'avec l'accès « Standard » accordé
  par Pinterest (en accès d'essai, les épingles restent privées, dans un bac à sable).
- YouTube et la boutique Shopify : leurs connecteurs officiels (module 14 du skill), pas ce script.

Les règles des plateformes veulent que l'utilisateur ait vu chaque publication : Claude lui présente le lot (le
calendrier de la semaine), puis publie ce qu'il a approuvé. Avant chaque envoi : relecture par relire_texte.py (un 🔴
bloque), plafond quotidien (jamais plus qu'un humain ne publierait), journal local. `--essai` montre la requête sans
rien envoyer.

Accès : saisis une seule fois par l'utilisateur, dans SON terminal, à une invite masquée (`acces <plateforme>`) — ils
ne passent jamais par la conversation ni par la ligne de commande. Ils sont gardés dans ~/.claude/brain/acces/ (hors
sauvegardes et hors cerveau commun) ; une variable d'environnement (PINTEREST_TOKEN, META_TOKEN) a la priorité.

Bibliothèque standard uniquement. Usage :
  python scripts/publier.py acces pinterest|meta            (une fois, dans un terminal : invite masquée)
  python scripts/publier.py etat                            (accès présents, publications du jour)
  python scripts/publier.py facebook --page <id> --texte "…" [--lien <url>] [--quand 2026-10-20T18:00] [--essai]
  python scripts/publier.py instagram --compte <id> --texte "…" (--image <url.jpg> | --video <url>) [--essai]
  python scripts/publier.py pinterest-csv --entree epingles.json --sortie epingles.csv
  python scripts/publier.py pinterest-tableaux · pinterest --tableau <id> --titre … --texte … --lien … --image …"""
from __future__ import annotations

import csv
import datetime as _dt
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import relire_texte  # noqa: E402  (même dossier)

PINTEREST = os.environ.get("PUBLIER_API_PINTEREST") or "https://api.pinterest.com/v5"
GRAPH = os.environ.get("PUBLIER_API_GRAPH") or "https://graph.facebook.com"
ENV = {"pinterest": "PINTEREST_TOKEN", "meta": "META_TOKEN"}
PLAFOND = {"pinterest": 10, "facebook": 3, "instagram": 3}  # par jour [HEURISTIQUE : rythme humain, à régler]


def dossier() -> Path:
    base = os.environ.get("BRAIN_HOME") or str(Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
                                               / "brain")
    return Path(base) / "acces"


# ------------------------------------------------------------------------------------------------ accès
def lire_acces(nom: str) -> str | None:
    if os.environ.get(ENV[nom]):
        return os.environ[ENV[nom]].strip()
    try:
        data = json.loads((dossier() / f"{nom}.json").read_text(encoding="utf-8"))
        return (data.get("token") or "").strip() or None
    except (OSError, ValueError):
        return None


def enregistrer_acces(nom: str) -> int:
    if not sys.stdin.isatty():
        print("✗ à lancer dans ton propre terminal (invite masquée) : l'accès ne doit pas passer par la conversation",
              file=sys.stderr)
        return 2
    token = getpass.getpass(f"Jeton d'accès {nom} (rien ne s'affiche) : ").strip()
    if len(token) < 20:
        print("✗ jeton trop court : rien n'est enregistré", file=sys.stderr)
        return 2
    d = dossier()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{nom}.json"
    path.write_text(json.dumps({"token": token, "enregistre": _dt.date.today().isoformat()}), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    print(f"✓ accès {nom} enregistré dans {path} (hors sauvegardes et hors cerveau commun)")
    return 0


# ------------------------------------------------------------------------------------------------ journal, plafond
def journal_path() -> Path:
    return dossier() / "publications.jsonl"


def publications_du_jour(plateforme: str) -> int:
    today = _dt.date.today().isoformat()
    try:
        lines = journal_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    n = 0
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        n += e.get("plateforme") == plateforme and str(e.get("date", "")).startswith(today) and not e.get("essai")
    return n


def journaliser(entry: dict) -> None:
    d = dossier()
    d.mkdir(parents=True, exist_ok=True)
    with open(journal_path(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------------------------------------ HTTP
def appel(method: str, url: str, token: str | None = None, data: dict | None = None, form: dict | None = None,
          timeout: float = 60) -> dict:
    """→ {"status", "json", "erreur"} ; jamais d'exception, jamais le jeton dans un message."""
    headers = {"User-Agent": "cerveau-publier/1.0", "Accept": "application/json"}
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif form is not None:
        body = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw, status = resp.read(), resp.status
    except urllib.error.HTTPError as exc:
        raw, status = (exc.read() if exc.fp else b""), exc.code
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"status": None, "json": None, "erreur": str(getattr(exc, "reason", exc))}
    try:
        payload = json.loads(raw.decode("utf-8") or "null")
    except ValueError:
        payload = None
    err = None
    if status >= 400:
        detail = payload.get("message") or (payload.get("error") or {}).get("message") if isinstance(payload, dict) else None
        err = f"HTTP {status}" + (f" : {str(detail)[:200]}" if detail else "")
    return {"status": status, "json": payload, "erreur": err}


# ------------------------------------------------------------------------------------------------ garde-fous
def controler(plateforme: str, texte: str, essai: bool) -> str | None:
    """Relecture (🔴 bloque) et plafond du jour. → message d'arrêt ou None."""
    rel = relire_texte.relire(texte, "post")
    rouges = [f for f in rel["points"] if f["niveau"] == "🔴"]
    if rouges:
        return "relecture : " + " ; ".join(f"{f['sujet']} « {f['extrait']} »" for f in rouges[:3]) + \
               " → corriger le texte (rien n'a été publié)"
    sponsor = [f for f in rel["points"] if f["sujet"] == "Partenariat sans mention"]
    if sponsor:
        return "contenu rémunéré sans « Publicité » ou « Collaboration commerciale » → l'ajouter (rien n'a été publié)"
    if not essai and publications_du_jour(plateforme) >= PLAFOND[plateforme]:
        return (f"plafond du jour atteint ({PLAFOND[plateforme]} publications {plateforme}) : la suite attend demain "
                "(rythme humain)")
    return None


def _https(url: str, nom: str) -> str | None:
    if not url:
        return None
    if not url.lower().startswith("https://"):
        return f"--{nom} doit être une adresse https publique"
    return None


# ------------------------------------------------------------------------------------------------ plateformes
def pinterest_tableaux(token: str) -> dict:
    return appel("GET", f"{PINTEREST}/boards?page_size=100", token)


def pinterest(token: str, tableau: str, titre: str, texte: str, lien: str, image: str, essai: bool) -> dict:
    corps = {"board_id": tableau, "title": titre[:100], "description": texte[:500], "link": lien,
             "media_source": {"source_type": "image_url", "url": image}}
    if essai:
        return {"essai": True, "requete": {"POST": f"{PINTEREST}/pins", "json": corps}}
    r = appel("POST", f"{PINTEREST}/pins", token, data=corps)
    pin = (r.get("json") or {}).get("id") if not r["erreur"] else None
    return {**r, "id": pin, "url": f"https://www.pinterest.com/pin/{pin}/" if pin else None}


def quand_vers_unix(quand: str, maintenant: float | None = None) -> int:
    """« 2026-10-20T18:00 » (heure locale) → horodatage ; Facebook accepte de 10 minutes à 75 jours plus tard."""
    try:
        t = _dt.datetime.fromisoformat(quand.strip()).timestamp()
    except ValueError:
        raise ValueError(f"--quand illisible : {quand} (forme 2026-10-20T18:00)") from None
    now = maintenant if maintenant is not None else time.time()
    if not now + 600 <= t <= now + 75 * 86400:
        raise ValueError("--quand doit être entre 10 minutes et 75 jours plus tard (règle de Facebook)")
    return int(t)


def facebook(token: str, page: str, texte: str, lien: str | None, essai: bool, quand: int | None = None) -> dict:
    form = {"message": texte}
    if lien:
        form["link"] = lien
    if quand:
        form.update({"published": "false", "scheduled_publish_time": str(quand)})
    url = f"{GRAPH}/{urllib.parse.quote(page)}/feed"
    if essai:
        return {"essai": True, "requete": {"POST": url, "form": form}}
    r = appel("POST", url, form={**form, "access_token": token})
    post = (r.get("json") or {}).get("id") if not r["erreur"] else None
    return {**r, "id": post, "url": f"https://www.facebook.com/{post}" if post else None}


def instagram(token: str, compte: str, texte: str, image: str | None, video: str | None, essai: bool,
              attente: float = 60, essais_max: int = 5) -> dict:
    """Conteneur, attente du traitement (vidéo : une interrogation par minute, cinq au plus, comme le demande Meta),
    puis publication : la séquence de l'API de publication Instagram."""
    form = {"caption": texte}
    if video:
        form.update({"media_type": "REELS", "video_url": video})
    else:
        form["image_url"] = image
    base = f"{GRAPH}/{urllib.parse.quote(compte)}"
    if essai:
        return {"essai": True, "requete": [{"POST": f"{base}/media", "form": form},
                                           {"POST": f"{base}/media_publish", "form": {"creation_id": "…"}}]}
    r = appel("POST", f"{base}/media", form={**form, "access_token": token})
    cid = (r.get("json") or {}).get("id") if not r["erreur"] else None
    if not cid:
        return {**r, "id": None}
    for _ in range(essais_max):  # les vidéos sont traitées en arrière-plan : FINISHED avant de publier
        st = appel("GET", f"{GRAPH}/{urllib.parse.quote(cid)}?" + urllib.parse.urlencode(
            {"fields": "status_code", "access_token": token}))
        code = (st.get("json") or {}).get("status_code")
        if code in (None, "FINISHED", "PUBLISHED") or st["erreur"]:
            break
        if code in ("ERROR", "EXPIRED"):
            return {**st, "id": None, "erreur": f"traitement du média : {code}"}
        time.sleep(attente)
    r = appel("POST", f"{base}/media_publish", form={"creation_id": cid, "access_token": token})
    mid = (r.get("json") or {}).get("id") if not r["erreur"] else None
    return {**r, "id": mid}


CSV_PINTEREST = ["Title", "Media URL", "Pinterest board", "Thumbnail", "Description", "Link", "Publish date",
                 "Keywords"]  # [À VÉRIFIER : comparer au modèle de Pinterest › Créer › Épingles en masse]


def pinterest_csv(entrees: list, sortie: str) -> dict:
    """Fichier de l'import en masse de Pinterest (200 épingles au plus) ; chaque texte relu, les 🔴 écartés."""
    lignes, ecartees = [], []
    for k, e in enumerate(entrees, 1):
        titre, texte = str(e.get("titre") or "").strip(), str(e.get("texte") or "").strip()
        manque = [n for n in ("titre", "image", "tableau") if not str(e.get(n) or "").strip()]
        bad = [b for b in (_https(e.get("image"), "image"), _https(e.get("lien"), "lien")) if b]
        stop = None if manque or bad else controler("pinterest", f"{titre} {texte}", True)
        if manque or bad or stop:
            ecartees.append((k, titre or "?", "manque " + ", ".join(manque) if manque else (bad[0] if bad else stop)))
            continue
        quand = str(e.get("date") or "").strip()
        lignes.append([titre[:100], e["image"], e["tableau"], e.get("miniature") or "", texte[:500], e.get("lien") or "",
                       quand, ", ".join(e.get("mots_cles") or [])])
    if len(lignes) > 200:
        raise ValueError(f"{len(lignes)} épingles : 200 au plus par fichier, découpe en plusieurs fichiers")
    with open(sortie, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_PINTEREST)
        w.writerows(lignes)
    return {"fichier": sortie, "epingles": len(lignes), "ecartees": ecartees}


# ------------------------------------------------------------------------------------------------ ligne de commande
def options(args: list) -> tuple:
    opts, flags, pos, i = {}, set(), [], 0
    while i < len(args):
        a = args[i]
        if a in ("--essai", "--json"):
            flags.add(a[2:])
        elif a.startswith("--") and i + 1 < len(args):
            opts[a[2:]] = args[i + 1]
            i += 1
        elif a.startswith("--"):
            raise ValueError(f"option incomplète : {a}")
        else:
            pos.append(a)
        i += 1
    return opts, flags, pos


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "--aide"):
        print(__doc__)
        return 0 if args else 1
    action = args[0]
    try:
        opts, flags, pos = options(args[1:])
    except ValueError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2
    essai = "essai" in flags
    if action == "acces":
        if not pos or pos[0] not in ENV:
            print("Erreur : acces pinterest|meta", file=sys.stderr)
            return 2
        return enregistrer_acces(pos[0])
    if action == "pinterest-csv":
        if not opts.get("entree") or not opts.get("sortie"):
            print("Erreur : --entree epingles.json --sortie epingles.csv", file=sys.stderr)
            return 2
        try:
            entrees = json.loads(Path(opts["entree"]).read_text(encoding="utf-8"))
            if not isinstance(entrees, list):
                raise ValueError("une liste d'épingles est attendue")
            r = pinterest_csv(entrees, opts["sortie"])
        except (OSError, ValueError) as exc:
            print(f"Erreur : {exc}", file=sys.stderr)
            return 2
        print(f"✓ {r['epingles']} épingle(s) → {r['fichier']} : Pinterest › Créer › Épingles en masse (👤 dépôt du "
              "fichier ; en-têtes à comparer au modèle de Pinterest la première fois)")
        for k, titre, why in r["ecartees"]:
            print(f"  écartée n° {k} ({titre}) : {why}")
        return 0 if r["epingles"] else 1
    if action == "etat":
        for nom in ENV:
            print(f"{'✓' if lire_acces(nom) else '·'} accès {nom}"
                  + ("" if lire_acces(nom) else f" : absent (python scripts/publier.py acces {nom}, dans un terminal)"))
        for plat, cap in PLAFOND.items():
            print(f"  {plat} : {publications_du_jour(plat)}/{cap} aujourd'hui")
        return 0
    plat = {"pinterest": "pinterest", "pinterest-tableaux": "pinterest", "facebook": "meta", "instagram": "meta"}.get(action)
    if not plat:
        print(f"Erreur : action inconnue {action}", file=sys.stderr)
        return 2
    token = lire_acces(plat)
    if not token and not essai:
        print(f"✗ accès {plat} absent : l'utilisateur le saisit une fois dans son terminal "
              f"(python scripts/publier.py acces {plat})", file=sys.stderr)
        return 3
    if action == "pinterest-tableaux":
        r = pinterest_tableaux(token)
        if r["erreur"]:
            print(f"✗ {r['erreur']}", file=sys.stderr)
            return 1
        for b in (r["json"] or {}).get("items") or []:
            print(f"{b.get('id')}  {b.get('name')}")
        return 0
    texte = opts.get("texte", "")
    need = {"pinterest": ("tableau", "titre", "texte", "lien", "image"), "facebook": ("page", "texte"),
            "instagram": ("compte", "texte")}[action]
    manque = [n for n in need if not opts.get(n)]
    if action == "instagram" and not (opts.get("image") or opts.get("video")):
        manque.append("image ou video")
    if manque:
        print("Erreur : il manque " + ", ".join(f"--{m}" for m in manque), file=sys.stderr)
        return 2
    for nom in ("lien", "image", "video"):
        bad = _https(opts.get(nom), nom)
        if bad:
            print(f"Erreur : {bad}", file=sys.stderr)
            return 2
    if action == "instagram" and opts.get("image") and not urllib.parse.urlsplit(opts["image"]).path.lower().endswith(
            (".jpg", ".jpeg")):
        print("Erreur : Instagram n'accepte que des images JPEG (adresse en .jpg ou .jpeg)", file=sys.stderr)
        return 2
    quand = None
    if action == "facebook" and opts.get("quand"):
        try:
            quand = quand_vers_unix(opts["quand"])
        except ValueError as exc:
            print(f"Erreur : {exc}", file=sys.stderr)
            return 2
    stop = controler(action, " ".join(x for x in (opts.get("titre"), texte) if x), essai)
    if stop:
        print(f"✗ {stop}", file=sys.stderr)
        return 4
    if action == "pinterest":
        r = pinterest(token, opts["tableau"], opts["titre"], texte, opts["lien"], opts["image"], essai)
    elif action == "facebook":
        r = facebook(token, opts["page"], texte, opts.get("lien"), essai, quand)
    else:
        r = instagram(token, opts["compte"], texte, opts.get("image"), opts.get("video"), essai)
    if r.get("essai"):
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    entry = {"date": _dt.datetime.now().replace(microsecond=0).isoformat(), "plateforme": action, "id": r.get("id"),
             "url": r.get("url"), "texte": texte[:120], "lien": opts.get("lien"), "erreur": r.get("erreur")}
    journaliser(entry)
    if r.get("erreur") or not r.get("id"):
        print(f"✗ {action} : {r.get('erreur') or 'réponse sans identifiant'} (rien de publié ; journalisé)",
              file=sys.stderr)
        return 1
    print(f"✓ {'programmé' if quand else 'publié'} sur {action} : {r.get('url') or r.get('id')}"
          + ("" if action != "instagram" else " (première fois : vérifie qu'il est visible déconnecté)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
