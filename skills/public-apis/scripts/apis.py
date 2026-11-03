#!/usr/bin/env python3
"""apis.py — trouver une API gratuite dans public-apis (github.com/public-apis/public-apis, MIT), hors-ligne,
et vérifier qu'elle répond encore. Python seul, sans dépendance.

    python apis.py cherche weather --sans-cle --https
    python apis.py cherche "exchange rate" --cors --verifie
    python apis.py cherche --cat geocoding --sans-cle
    python apis.py categories
    python apis.py mcp email
    python apis.py verifie Open-Meteo https://wttr.in/:help
    python apis.py maj                                  # retélécharge la liste depuis GitHub
    python apis.py maj --depuis <clone> --vers data/apis.json   # reconstruit l'index embarqué

Les mots se cherchent en anglais (la liste est en anglais), sans accents ni casse, tous requis : nom > catégorie >
description. L'index embarqué est data/apis.json ; `maj` écrit ~/.claude/public-apis/apis.json, lu ensuite s'il
n'est pas plus ancien. Le README d'origine n'est jamais lu en entier par l'agent : seulement par ce script.
"""
import argparse
import ipaddress
import json
import re
import socket
import ssl
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

REPO = "public-apis/public-apis"
BUNDLED = Path(__file__).resolve().parent.parent / "data" / "apis.json"
# Comme le vérificateur de liens du dépôt d'origine (scripts/validate/links.py) : un navigateur ordinaire,
# beaucoup de sites renvoyant 403 aux robots déclarés.
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
REFUS = {401, 402, 403, 405, 406, 429, 451, 999}


def cache_file():
    return Path.home() / ".claude" / "public-apis" / "apis.json"


# ------------------------------------------------------------------ lecture du README
LINK = re.compile(r"^\[(.+?)\]\(\s*(\S+?)\s*\)$")
LINKS = re.compile(r"\[([^\]]+)\]\(\s*(\S+?)\s*\)")
WEB = re.compile(r"https?://", re.I)
CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f‪-‮⁦-⁩]")  # contrôles et inversions bidi (affichage piégé)


def clean_url(url):
    """Retire les paramètres de suivi (utm_…) : liens d'affiliation du README."""
    p = urllib.parse.urlsplit(url)
    if not p.query:
        return url
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    return urllib.parse.urlunsplit(p._replace(query=urllib.parse.urlencode(q)))


def cells(line):
    parts = line.strip().replace("\\|", "\0").strip("|").split("|")
    return [c.strip().replace("\0", "|") for c in parts]


def parse(text):
    """README de public-apis → {"apis": [...], "mcp": [...]}. Seules comptent les catégories (### sous « ## Index »)
    et la section « ## MCP Servers » ; le bloc sponsorisé du haut (APILayer) est laissé de côté. Texte de tiers :
    caractères de contrôle retirés, liens non web (file:, javascript:…) écartés."""
    apis, mcp, section, cat = [], [], None, None
    for line in text.splitlines():
        s = CTRL.sub(" ", line).strip()
        if s.startswith("## "):
            section, cat = s[3:].strip().lower(), None
            continue
        if s.startswith("### "):
            cat = s[4:].strip() if section == "index" else None
            continue
        if not s.startswith("| [") or len(s) > 2000:  # 621 caractères au plus en réalité : borne le coût des regex
            continue
        c = cells(s)
        m = LINK.match(c[0])
        if not m or len(c) < 5 or not WEB.match(m.group(2)):
            continue
        nom, url = m.group(1).strip(), clean_url(m.group(2))
        cle = c[2].strip("` ")
        cle = "" if cle.lower() in ("no", "non", "") else cle
        if section == "index" and cat:
            apis.append({"nom": nom, "url": url, "desc": c[1], "cat": cat, "cle": cle,
                         "https": c[3].strip("` ").lower() == "yes",
                         "cors": {"yes": "oui", "no": "non"}.get(c[4].strip("` ").lower(), "?")})
        elif section == "mcp servers":
            mcp.append({"nom": nom, "url": url, "desc": c[1], "cle": cle,
                        "transport": c[3].replace("`", "").strip(),
                        "install": [[a, clean_url(b)] for a, b in LINKS.findall(c[4]) if WEB.match(b)]})
    return {"apis": apis, "mcp": mcp}


def dump(idx, path):
    """Une entrée par ligne : des écarts lisibles dans git d'une mise à jour à l'autre."""
    head = {k: v for k, v in idx.items() if k not in ("apis", "mcp")}
    out = json.dumps(head, ensure_ascii=False)[:-1]
    for key in ("apis", "mcp"):
        out += f', "{key}": [\n' + ",\n".join(json.dumps(e, ensure_ascii=False) for e in idx[key]) + "\n]"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(out + "}\n", encoding="utf-8", newline="\n")
    tmp.replace(path)


def load():
    """L'index le plus récent : celui de `maj` s'il n'est pas plus ancien que l'index embarqué."""
    idx = json.loads(BUNDLED.read_text(encoding="utf-8"))
    cf = cache_file()
    if cf.exists():
        try:
            mine = json.loads(cf.read_text(encoding="utf-8"))
            if mine.get("date", "") >= idx.get("date", "") and mine.get("apis"):
                return mine
        except (ValueError, OSError) as e:
            print(f"(liste mise à jour illisible, index embarqué utilisé : {e})", file=sys.stderr)
    return idx


# ------------------------------------------------------------------ recherche
def norm(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def tokens(s):
    return re.findall(r"[a-z0-9]+", norm(s))


def forms(w):
    """Le mot et ses singuliers possibles : movies → movie, currencies → currency, addresses → address."""
    f = {w}
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        f.add(w[:-1])
        if len(w) > 4 and w.endswith("ies"):
            f.add(w[:-3] + "y")
        if len(w) > 4 and w.endswith("es"):
            f.add(w[:-2])
    return f


def score(entry, words):
    """Somme, mot par mot, du meilleur endroit trouvé (0 si un mot manque : tous les mots sont requis). Un mot
    entier (ou son singulier) vaut plus qu'un début de mot ; pas de début de mot sous 3 lettres (ip, tv, ai)."""
    total = 0
    for w in words:
        wf, best = forms(w), 0
        for text, exact, prefix in ((entry["nom"], 6, 4), (entry.get("cat", ""), 3, 3), (entry["desc"], 2, 1)):
            toks = tokens(text)
            if any(wf & forms(t) for t in toks):
                best = max(best, exact)
            elif len(w) >= 3 and any(t.startswith(x) for t in toks for x in wf):
                best = max(best, prefix)
        if not best:
            return 0
        total += best
    return total


def quality(e):
    """À score égal : sans clé, puis HTTPS, puis CORS ouvert."""
    return (e.get("cle", "") == "", e.get("https", True), e.get("cors") == "oui")


def search(idx, query, cat=None, sans_cle=False, https=False, cors=False):
    words = [w for w in tokens(" ".join(query))]
    found = {}
    for e in idx["apis"]:
        if cat and norm(cat) not in norm(e["cat"]):
            continue
        if (sans_cle and e["cle"]) or (https and not e["https"]) or (cors and e["cors"] != "oui"):
            continue
        sc = score(e, words) if words else 1
        if not sc:
            continue
        key = e["url"].rstrip("/").lower()
        if key in found:  # même API dans deux catégories : une seule ligne
            old = found[key]
            old["cats"] = sorted(set(old["cats"]) | {e["cat"]})
            old["score"] = max(old["score"], sc)
            continue
        found[key] = dict(e, cats=[e["cat"]], score=sc)
    return sorted(found.values(), key=lambda e: (-e["score"], [not q for q in quality(e)], e["nom"].lower()))


# ------------------------------------------------------------------ vérification
def domain(url):
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return ".".join(host.split(".")[-2:]) if not re.fullmatch(r"[\d.]+", host) else host


class NonPublique(Exception):
    pass


def publique(url):
    """http(s), et un hôte qui ne mène qu'à des adresses publiques, après résolution DNS : une entrée piégée de la
    liste ne doit pas faire ouvrir la box, un NAS ou un service de la machine (SSRF)."""
    try:
        p = urllib.parse.urlsplit(url)
        host = p.hostname
        if p.scheme.lower() not in ("http", "https") or not host:
            return False
        try:
            ips = {ipaddress.ip_address(host)}
        except ValueError:
            ips = {ipaddress.ip_address(i[4][0]) for i in socket.getaddrinfo(host, None)}
    except (OSError, UnicodeError):
        return True  # domaine introuvable : l'ouverture le dira (✗)
    except ValueError:  # URL mal formée
        return False
    ips = {getattr(ip, "ipv4_mapped", None) or ip for ip in ips}  # ::ffff:127.0.0.1 = 127.0.0.1
    return all(ip.is_global and not ip.is_multicast for ip in ips)


class Garde(urllib.request.HTTPRedirectHandler):
    """Une URL de la liste ne sort pas non plus du web public par une redirection."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not publique(newurl):
            raise NonPublique(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check(url, timeout=10, libre=False):
    """✓ répond · ⚠ répond mais refuse (robots, clé, quota) ou part vers un autre domaine · ✗ morte ou hors du web
    public. libre : URL tapée par l'utilisateur, ouverte même en local ; une URL de la liste, jamais."""
    if not libre and not publique(url):
        return {"url": url, "etat": "✗", "code": None, "note": "pas une adresse web publique : non ouverte (entrée suspecte)"}
    req = urllib.request.Request(urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~"),
                                 headers={"User-Agent": UA, "Accept": "text/html,application/json,*/*;q=0.8",
                                          "Accept-Language": "fr,en;q=0.8"})
    handlers = [urllib.request.HTTPSHandler(context=ssl.create_default_context())] + ([] if libre else [Garde()])
    t0 = time.monotonic()
    try:
        with urllib.request.build_opener(*handlers).open(req, timeout=timeout) as r:
            r.read(4096)
            code, final = r.status, r.geturl()
    except urllib.error.HTTPError as e:
        code, final = e.code, e.geturl() or url
    except NonPublique as e:
        return {"url": url, "etat": "✗", "code": None, "note": f"redirige vers {e}, hors du web public : non suivie"}
    except Exception as e:  # DNS, refus de connexion, délai, certificat…
        reason = getattr(e, "reason", e)
        txt = str(reason)
        if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE" in txt.upper():
            why = "certificat HTTPS invalide"
        elif isinstance(reason, TimeoutError) or "timed out" in txt:
            why = f"pas de réponse en {timeout} s"
        elif "getaddrinfo" in txt or "Name or service" in txt or "nodename" in txt:
            why = "nom de domaine introuvable"
        elif isinstance(reason, ConnectionRefusedError):
            why = "connexion refusée"
        elif isinstance(reason, ConnectionError):
            why = "connexion coupée"
        else:
            why = txt[:80]
        return {"url": url, "etat": "✗", "code": None, "note": why}
    dt = round(time.monotonic() - t0, 1)
    note = f"{dt} s".replace(".", ",")
    if domain(final) != domain(url):
        return {"url": url, "etat": "⚠", "code": code, "note": f"redirige vers {final}", "final": final}
    if 200 <= code < 400:
        return {"url": url, "etat": "✓", "code": code, "note": note, "final": final}
    if code in REFUS:
        return {"url": url, "etat": "⚠", "code": code, "note": "répond mais refuse (robot, clé ou quota) : ouvrir dans le navigateur"}
    return {"url": url, "etat": "✗", "code": code, "note": "page absente" if code in (404, 410) else "erreur du serveur"}


def check_all(urls, libres=()):
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(lambda u: check(u, libre=u in libres), urls))


def fmt_check(c):
    code = f" {c['code']}" if c.get("code") else ""
    return f"{c['etat']}{code} — {c['note']}"


# ------------------------------------------------------------------ sorties
def header(idx, extra=""):
    d = idx.get("date", "?")
    d = "/".join(reversed(d.split("-"))) if re.fullmatch(r"\d{4}-\d\d-\d\d", d) else d
    return f"public-apis du {d} ({distinct(idx['apis'])} API, {len(idx.get('mcp', []))} serveurs MCP){extra}"


def distinct(apis):
    """Nombre d'API distinctes : une même API peut être listée dans deux catégories (Open-Meteo)."""
    return len({e["url"].rstrip("/").lower() for e in apis})


def line(e, checked=None):
    cle = "sans clé" if not e["cle"] else f"clé {e['cle']}"
    https = "HTTPS" if e["https"] else "HTTP seulement"
    cors = {"oui": "CORS ouvert", "non": "CORS fermé"}.get(e["cors"], "CORS inconnu")
    out = f"{e['nom']} [{', '.join(e.get('cats') or [e['cat']])}] — {e['desc']} · {cle} · {https} · {cors}\n  {e['url']}"
    return out + (f"  {fmt_check(checked)}" if checked else "")


def cmd_cherche(a):
    idx = load()
    if not a.mots and not a.cat:
        sys.exit("Donne des mots (en anglais) ou --cat <catégorie> ; liste des catégories : apis.py categories")
    if a.cat and not any(norm(a.cat) in norm(e["cat"]) for e in idx["apis"]):
        sys.exit(f"Aucune catégorie ne contient « {a.cat} » ; liste : apis.py categories")
    res = search(idx, a.mots, a.cat, a.sans_cle, a.https, a.cors)
    shown = res[: a.max]
    checks = check_all([e["url"] for e in shown]) if a.verifie else [None] * len(shown)
    if a.json:
        for e, c in zip(shown, checks):
            e.pop("cat", None)
            if c:
                e["verif"] = c
        print(json.dumps({"source": header(idx), "total": len(res), "resultats": shown}, ensure_ascii=False, indent=1))
        return
    filtres = [f for f, on in (("sans clé", a.sans_cle), ("HTTPS", a.https), ("CORS ouvert", a.cors)) if on]
    what = f"« {' '.join(a.mots)} »" if a.mots else "toute la catégorie"
    what += f" dans {a.cat}" if a.cat else ""
    print(header(idx, f" — {len(res)} résultat(s) pour {what}" + (f" ({', '.join(filtres)})" if filtres else "")))
    if not res:
        print("Aucun résultat : essayer un synonyme anglais, un mot plus court, moins de filtres, ou --cat "
              "(apis.py categories).")
    for e, c in zip(shown, checks):
        print(line(e, c))
    if len(res) > len(shown):
        print(f"… {len(res) - len(shown)} autre(s) : --max {len(res)} pour tout voir.")


def cmd_categories(a):
    idx = load()
    counts = {}
    for e in idx["apis"]:
        counts[e["cat"]] = counts.get(e["cat"], 0) + 1
    print(header(idx, f" — {len(counts)} catégories"))
    for c in sorted(counts):
        print(f"{c} ({counts[c]})")


def cmd_mcp(a):
    idx = load()
    words = tokens(" ".join(a.mots))
    res = [m for m in idx.get("mcp", []) if not words or score(m, words)]
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return
    print(header(idx, f" — {len(res)} serveur(s) MCP" + (f" pour « {' '.join(a.mots)} »" if a.mots else "")))
    for m in res:
        cle = "sans clé" if not m["cle"] else f"clé {m['cle']}"
        inst = ", ".join(f"{n} {u}" for n, u in m["install"]) or "voir la page"
        print(f"{m['nom']} — {m['desc']} · {cle} · {m['transport']}\n  {m['url']}\n  installation : {inst}")


def cmd_verifie(a):
    idx = load()
    urls, libres = [], set()
    for x in a.cibles:
        if re.match(r"^https?://", x, re.I):
            urls.append(x)
            libres.add(x)
            continue
        hits = {e["url"] for e in idx["apis"] + idx.get("mcp", []) if norm(e["nom"]) == norm(x)}
        if not hits:
            print(f"✗ « {x} » : pas dans la liste (donner l'URL, ou chercher : apis.py cherche …)")
        urls.extend(sorted(hits))
    for u, c in zip(urls, check_all(urls, libres)):
        print(f"{u}  {fmt_check(c)}")


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "cerveau-public-apis", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
        return r.read().decode("utf-8")


def cmd_maj(a):
    if a.depuis:
        src = Path(a.depuis)
        readme = src / "README.md" if src.is_dir() else src
        text = readme.read_text(encoding="utf-8")
        commit, day = "?", date.today().isoformat()
        if src.is_dir():
            r = subprocess.run(["git", "-C", str(src), "log", "-1", "--format=%H %cs"], capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                commit, day = r.stdout.split()
    else:
        try:
            head = json.loads(fetch(f"https://api.github.com/repos/{REPO}/commits/master"))
            commit, day = head["sha"], head["commit"]["committer"]["date"][:10]
            if not (re.fullmatch(r"[0-9a-f]{40}", commit) and re.fullmatch(r"\d{4}-\d\d-\d\d", day)):
                raise ValueError(commit)  # irait dans l'URL du README et dans la date de l'index
        except Exception:
            commit, day = "master", date.today().isoformat()
        text = fetch(f"https://raw.githubusercontent.com/{REPO}/{commit}/README.md")
    idx = {"source": f"https://github.com/{REPO}", "commit": commit, "date": day,
           "licence": "MIT, (c) 2022 public-apis — voir LICENSE", **parse(text)}
    dest = Path(a.vers) if a.vers else cache_file()
    old = None
    if dest.exists():
        try:
            old = json.loads(dest.read_text(encoding="utf-8"))
        except ValueError:
            pass
    if old is None and not a.vers:
        old = json.loads(BUNDLED.read_text(encoding="utf-8"))
    if old and len(idx["apis"]) < len(old["apis"]) / 2:
        sys.exit(f"Liste suspecte : {len(idx['apis'])} API contre {len(old['apis'])} avant (format du README changé ?). "
                 "Rien d'écrit.")
    dump(idx, dest)
    cats = len({e["cat"] for e in idx["apis"]})
    msg = f"{distinct(idx['apis'])} API en {cats} catégories, {len(idx['mcp'])} serveurs MCP (commit {commit[:7]}, {day}) → {dest}"
    if old:
        before = {(e["nom"], e["url"]) for e in old["apis"]}
        after = {(e["nom"], e["url"]) for e in idx["apis"]}
        msg += f"\n+{len(after - before)} / −{len(before - after)} depuis la version précédente ({old.get('date', '?')})"
    print(msg)


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="apis.py", description="Trouver une API gratuite dans public-apis, hors-ligne.")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cherche", help="chercher par mots (anglais) et filtres")
    c.add_argument("mots", nargs="*")
    c.add_argument("--cat", help="catégorie, ou une partie de son nom (ex. geo, currency)")
    c.add_argument("--sans-cle", action="store_true", help="sans clé d'API ni compte")
    c.add_argument("--https", action="store_true", help="HTTPS seulement")
    c.add_argument("--cors", action="store_true", help="appelable depuis un navigateur (CORS ouvert)")
    c.add_argument("--max", type=int, default=15, help="nombre de résultats affichés (15)")
    c.add_argument("--verifie", action="store_true", help="vérifier que les résultats affichés répondent")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_cherche)
    sub.add_parser("categories", help="les catégories et leur nombre d'API").set_defaults(func=cmd_categories)
    m = sub.add_parser("mcp", help="les serveurs MCP de la liste")
    m.add_argument("mots", nargs="*")
    m.add_argument("--json", action="store_true")
    m.set_defaults(func=cmd_mcp)
    v = sub.add_parser("verifie", help="vérifier qu'une API (nom ou URL) répond encore")
    v.add_argument("cibles", nargs="+")
    v.set_defaults(func=cmd_verifie)
    u = sub.add_parser("maj", help="retélécharger la liste (GitHub) ou la relire depuis un clone")
    u.add_argument("--depuis", help="clone du dépôt ou README.md local, au lieu de GitHub")
    u.add_argument("--vers", help="fichier d'index à écrire (défaut : ~/.claude/public-apis/apis.json)")
    u.set_defaults(func=cmd_maj)
    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
