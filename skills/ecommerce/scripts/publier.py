#!/usr/bin/env python3
"""Publication par API officielle, sur les comptes de l'utilisateur, après une configuration unique.

Plateformes : Pinterest (épingle image), page Facebook (post, avec lien), Instagram professionnel (image ou Reel).
YouTube et la boutique Shopify passent par leurs connecteurs officiels (module 14 du skill), pas par ce script.

Avant chaque envoi : relecture du texte par relire_texte.py (un 🔴 bloque), plafond quotidien par plateforme (jamais
plus qu'un humain ne publierait), journal local de chaque publication. `--essai` montre la requête sans rien envoyer.

Accès : saisis une seule fois par l'utilisateur, dans SON terminal, à une invite masquée (`acces <plateforme>`) — ils
ne passent jamais par la conversation ni par la ligne de commande. Ils sont gardés dans ~/.claude/brain/acces/ (hors
sauvegardes et hors cerveau commun) ; une variable d'environnement (PINTEREST_TOKEN, META_TOKEN) a la priorité.

Bibliothèque standard uniquement. Usage :
  python scripts/publier.py acces pinterest|meta            (une fois, dans un terminal : invite masquée)
  python scripts/publier.py etat                            (accès présents, publications du jour)
  python scripts/publier.py pinterest-tableaux
  python scripts/publier.py pinterest --tableau <id> --titre "…" --texte "…" --lien <url> --image <url> [--essai]
  python scripts/publier.py facebook --page <id> --texte "…" [--lien <url>] [--essai]
  python scripts/publier.py instagram --compte <id> --texte "…" (--image <url> | --video <url>) [--essai]"""
from __future__ import annotations

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


def facebook(token: str, page: str, texte: str, lien: str | None, essai: bool) -> dict:
    form = {"message": texte}
    if lien:
        form["link"] = lien
    url = f"{GRAPH}/{urllib.parse.quote(page)}/feed"
    if essai:
        return {"essai": True, "requete": {"POST": url, "form": form}}
    r = appel("POST", url, form={**form, "access_token": token})
    post = (r.get("json") or {}).get("id") if not r["erreur"] else None
    return {**r, "id": post, "url": f"https://www.facebook.com/{post}" if post else None}


def instagram(token: str, compte: str, texte: str, image: str | None, video: str | None, essai: bool,
              attente: float = 5, essais_max: int = 60) -> dict:
    """Conteneur, attente du traitement (vidéo), puis publication : la séquence de l'API de publication Instagram."""
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
    stop = controler(action, " ".join(x for x in (opts.get("titre"), texte) if x), essai)
    if stop:
        print(f"✗ {stop}", file=sys.stderr)
        return 4
    if action == "pinterest":
        r = pinterest(token, opts["tableau"], opts["titre"], texte, opts["lien"], opts["image"], essai)
    elif action == "facebook":
        r = facebook(token, opts["page"], texte, opts.get("lien"), essai)
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
    print(f"✓ publié sur {action} : {r.get('url') or r.get('id')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
