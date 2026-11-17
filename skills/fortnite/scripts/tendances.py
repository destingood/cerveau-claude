#!/usr/bin/env python3
"""Tendances des îles Fortnite, lues dans l'API publique d'Epic (Fortnite Data API, sans clé ni compte) : ce qui monte
dans un genre, les chiffres des maps concurrentes, la barre à atteindre, et le suivi de sa propre île dans la durée.

    python tendances.py genres                                  # les 13 genres et leur identifiant
    python tendances.py classement battle-royale --top 30       # les 30 premières du genre, avec leurs chiffres
    python tendances.py classement shooter --top 50 --tag boxfight --mot "1v1"
    python tendances.py classement battle-royale --titres titres.txt    # leurs titres, pour fiche.py --concurrents
    python tendances.py ile 1234-5678-9012                      # une île : fiche, rang, 7 jours de chiffres
    python tendances.py comparer 1111-1111-1111 2222-2222-2222  # plusieurs îles côte à côte, et leur médiane
    python tendances.py nouveautes --tag zonewars --pages 3     # ce qui vient de sortir dans la niche
    python tendances.py suivre 1234-5678-9012                   # garde les chiffres du jour (l'API n'en garde que 7)
    … --json                                                    # sortie JSON (comparer --json nourrit diagnostic.py)

Ce que l'API donne, par île et par jour : joueurs uniques, parties, minutes jouées, minutes par joueur, pic de joueurs
simultanés, favoris, recommandations, rétention J1 et J7, rang dans son genre. Ce qu'elle ne donne pas : impressions,
clics, taux de clic, taux de rebond (portail créateur, pour ses propres îles seulement).
Limites écrites par Epic : 7 jours d'historique ; îles publiques seulement ; moins de 5 joueurs uniques sur la
période → valeur vide ; les chiffres peuvent différer de ceux du portail créateur.

Lecture seule, bibliothèque standard uniquement. Une pause entre deux appels (--pause, 0,3 s) ; sur un refus 429
(trop d'appels), le script attend puis réessaie. Adresse de l'API : variable FORTNITE_API (essais sur un serveur local)."""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = os.environ.get("FORTNITE_API", "https://api.fortnite.com/ecosystem/v1").rstrip("/")
UA = "cerveau-fortnite/1.0 (lecture publique de la Fortnite Data API)"
CODE = re.compile(r"^\d{4}-\d{4}-\d{4}$")
PAUSE = 0.3
METRIQUES = ("uniquePlayers", "plays", "minutesPlayed", "averageMinutesPerPlayer", "peakCCU", "favorites",
             "recommendations")
_dernier_appel = [0.0]


class Erreur(Exception):
    pass


def dossier() -> Path:
    """Où le suivi est gardé : ~/.claude/fortnite (FORTNITE_HOME pour le déplacer)."""
    return Path(os.environ.get("FORTNITE_HOME") or Path.home() / ".claude" / "fortnite")


def lire(chemin: str, params: dict | None = None, essais: int = 4):
    """GET sur l'API → JSON. 404 → None. 429 → attente puis nouvel essai."""
    url = API + chemin + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    for essai in range(essais):
        attente = PAUSE - (time.monotonic() - _dernier_appel[0])
        if attente > 0:
            time.sleep(attente)
        _dernier_appel[0] = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as rep:
                return json.loads(rep.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None
            if err.code == 429 and essai < essais - 1:
                try:
                    pause = float(err.headers.get("Retry-After") or 0)
                except ValueError:
                    pause = 0
                time.sleep(min(pause or 5 * 3 ** essai, 60))
                continue
            raise Erreur(f"l'API a répondu {err.code} pour {chemin}") from err
        except (urllib.error.URLError, OSError, ValueError) as err:
            raison = getattr(err, "reason", err)
            raise Erreur(f"API injoignable ({raison}) : {url}") from err
    raise Erreur(f"l'API refuse toujours les appels (429) : {chemin}")


def jour(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT00:00:00.000Z")


def fenetre(jours: int = 7, maintenant: datetime | None = None) -> dict:
    """Les `jours` derniers jours complets (UTC) : la journée en cours, partielle, fausserait les moyennes."""
    fin = (maintenant or datetime.now(timezone.utc)).replace(hour=0, minute=0, second=0, microsecond=0)
    return {"from": jour(fin - timedelta(days=jours)), "to": jour(fin)}


def nombres(serie) -> list:
    return [p["value"] for p in serie or [] if isinstance(p, dict) and isinstance(p.get("value"), (int, float))]


def resume(mesures: dict | None) -> dict:
    """Résumé d'une île sur la fenêtre : moyennes par jour, pic, rétention la plus récente, tendance."""
    m = mesures or {}
    r = {"jours": 0}
    series = {k: nombres(m.get(k)) for k in METRIQUES}
    r["jours"] = max((len(v) for v in series.values()), default=0)
    moy = lambda v: (sum(v) / len(v)) if v else None  # noqa: E731
    r["joueurs"] = moy(series["uniquePlayers"])
    r["parties"] = moy(series["plays"])
    r["minutes_par_joueur"] = moy(series["averageMinutesPerPlayer"])
    r["pic"] = max(series["peakCCU"]) if series["peakCCU"] else None
    joueurs, minutes = sum(series["uniquePlayers"]), sum(series["minutesPlayed"])
    r["minutes_par_partie"] = (minutes / sum(series["plays"])) if series["plays"] and sum(series["plays"]) else None
    r["parties_par_joueur"] = (sum(series["plays"]) / joueurs) if joueurs else None
    r["favoris_pour_1000"] = (1000 * sum(series["favorites"]) / joueurs) if joueurs and series["favorites"] else None
    r["recos_pour_1000"] = (1000 * sum(series["recommendations"]) / joueurs) if joueurs and series["recommendations"] else None
    # rétention : l'API renvoie une fraction (0,2 = 20 %), sa description parle d'un nombre de joueurs → les deux lus
    r["j1"] = r["j7"] = None
    for point in reversed(m.get("retention") or []):
        for cle in ("d1", "d7"):
            v = point.get(cle) if isinstance(point, dict) else None
            cible = "j1" if cle == "d1" else "j7"
            if r[cible] is None and isinstance(v, (int, float)):
                r[cible] = v * 100 if v <= 1 else v
    r["retention_en_joueurs"] = any(isinstance(p, dict) and isinstance(p.get("d1"), (int, float)) and p["d1"] > 1
                                    for p in m.get("retention") or [])
    # tendance : joueurs uniques des 3 derniers jours contre les 3 premiers (il faut 6 jours de chiffres)
    u = series["uniquePlayers"]
    r["tendance"] = ((sum(u[-3:]) / sum(u[:3]) - 1) * 100) if len(u) >= 6 and sum(u[:3]) else None
    return r


def ile(code: str, jours: int = 7, rang: bool = True, fiche: dict | None = None) -> dict | None:
    """Fiche, résumé et rang d'une île ; None si l'API ne la connaît pas (privée, non listée, code faux)."""
    fiche = fiche or lire(f"/islands/{code}")
    if not fiche:
        return None
    mesures = lire(f"/islands/{code}/metrics/day", fenetre(jours)) or {}
    d = {"code": code, "titre": fiche.get("title") or "", "createur": fiche.get("creatorCode") or "",
         "tags": fiche.get("tags") or [], "cree_dans": fiche.get("createdIn") or "", "mesures": mesures,
         **resume(mesures), "rangs": []}
    if rang:
        r = lire(f"/islands/{code}/rankings") or {}
        dernier = (r.get("data") or [{}])[-1]
        d["rangs"] = [{"genre": g.get("genre"), "slug": g.get("genreSlug"), "rang": g.get("rank")}
                      for g in dernier.get("genres") or []]
    if d["createur"]:
        d["lien"] = f"https://www.fortnite.com/@{d['createur']}/{code}"
    return d


def mediane(iles: list) -> dict:
    """La barre de la niche : médiane de chaque chiffre sur les îles données (les valeurs vides sont ignorées)."""
    cles = ("joueurs", "parties", "minutes_par_joueur", "minutes_par_partie", "parties_par_joueur", "pic", "j1", "j7",
            "favoris_pour_1000", "recos_pour_1000", "tendance")
    out = {}
    for cle in cles:
        v = [i[cle] for i in iles if isinstance(i.get(cle), (int, float))]
        out[cle] = statistics.median(v) if v else None
    out["iles"] = len(iles)
    return out


def filtre(d: dict, tags: list, mots: list) -> bool:
    etiquettes = {re.sub(r"[\s-]", "", t.lower()) for t in d.get("tags") or []}
    if any(re.sub(r"[\s-]", "", t.lower()) not in etiquettes for t in tags):
        return False
    return all(m.lower() in (d.get("titre") or d.get("title") or "").lower() for m in mots)


# ------------------------------------------------------------------ affichage
def n(v, fmt="{:,.0f}") -> str:
    return "—" if v is None else fmt.format(v).replace(",", " ")


def pct(v) -> str:
    return "—" if v is None else f"{v:.0f} %"


def signe(v) -> str:
    return "—" if v is None else f"{v:+.0f} %"


def ret(v) -> str:
    """Rétention telle que l'API la donne : une fraction (0,2 → 20 %) ou, d'après sa description, un nombre de joueurs."""
    return "—" if v is None else (f"{v * 100:.0f} %" if v <= 1 else f"{v:.0f}")


def tableau(iles: list, med: dict | None = None, rangs: bool = False) -> None:
    entete = (f"{'rang':>5} " if rangs else "") + (f"{'code':<14} {'joueurs/j':>10} {'min/joueur':>10} {'J1':>5} "
                                                   f"{'J7':>5} {'fav/1000':>8} {'pic':>8} {'7 j':>6}  titre")
    print(entete)
    for i in iles:
        print((f"{n(i.get('rang')):>5} " if rangs else "")
              + f"{i['code']:<14} {n(i['joueurs']):>10} {n(i['minutes_par_joueur'], '{:.1f}'):>10} {pct(i['j1']):>5} "
                f"{pct(i['j7']):>5} {n(i['favoris_pour_1000'], '{:.1f}'):>8} {n(i['pic']):>8} {signe(i['tendance']):>6}  "
                f"{i['titre'][:60]}  [{', '.join(i['tags'])}]")
    if med and med.get("iles", 0) > 1:
        print((f"{'':>5} " if rangs else "")
              + f"{'médiane':<14} {n(med['joueurs']):>10} {n(med['minutes_par_joueur'], '{:.1f}'):>10} "
                f"{pct(med['j1']):>5} {pct(med['j7']):>5} {n(med['favoris_pour_1000'], '{:.1f}'):>8} {n(med['pic']):>8} "
                f"{signe(med['tendance']):>6}  ({med['iles']} îles)")
    if any(i.get("retention_en_joueurs") for i in iles):
        print("Rétention donnée en nombre de joueurs par l'API pour certaines îles : colonnes J1 et J7 à lire en joueurs.")


def sans_mesures(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "mesures"}


# ------------------------------------------------------------------ commandes
def cmd_genres(a) -> int:
    lignes = (lire("/genres") or {}).get("data") or []
    if a.json:
        print(json.dumps(lignes, ensure_ascii=False, indent=1))
        return 0
    for g in lignes:
        print(f"{g.get('slug', ''):<24} {g.get('displayName', '')}")
    return 0


def cmd_classement(a) -> int:
    top = max(1, min(a.top, 200))
    data = lire(f"/genres/{a.genre}/rankings", {"size": top})
    if data is None:
        raise Erreur(f"genre inconnu : {a.genre} (liste : tendances.py genres)")
    meta = data.get("meta") or {}
    iles = []
    for ligne in data.get("data") or []:
        code = ligne.get("islandCode")
        fiche = lire(f"/islands/{code}") if code else None
        if not fiche:
            continue
        if not filtre(fiche, a.tag, a.mot):
            continue
        d = ile(code, a.jours, rang=False, fiche=fiche)
        if d:
            d["rang"] = ligne.get("rank")
            iles.append(d)
    med = mediane(iles)
    if a.titres:
        Path(a.titres).write_text("\n".join(i["titre"] for i in iles) + "\n", encoding="utf-8")
    if a.json:
        print(json.dumps({"genre": a.genre, "instantane": meta.get("snapshot"), "classees": meta.get("total"),
                          "iles": [sans_mesures(i) for i in iles], "mediane": med}, ensure_ascii=False, indent=1))
        return 0
    print(f"Genre {a.genre} — {n(meta.get('total'))} îles classées, relevé du {meta.get('snapshot') or '?'} ; "
          f"{len(iles)} île(s) retenue(s) parmi les {top} premières"
          + (f" (filtre : {' '.join(a.tag + a.mot)})" if a.tag or a.mot else "") + f", moyennes sur {a.jours} jours complets.\n")
    if not iles:
        print("Aucune île ne passe le filtre : élargis --top, ou change de genre (zone wars est rangé en battle-royale).")
        return 0
    tableau(iles, med, rangs=True)
    if a.titres:
        print(f"\nTitres écrits dans {a.titres} (pour fiche.py --concurrents).")
    return 0


def cmd_ile(a) -> int:
    d = ile(a.code, a.jours)
    if not d:
        raise Erreur(f"île {a.code} inconnue de l'API : code faux, île privée ou non listée, ou pas encore publiée")
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return 0
    print(f"{d['titre']} — {d['code']} — par {d['createur'] or '?'} ({d['cree_dans'] or '?'})")
    print(f"Tags : {', '.join(d['tags']) or 'aucun'}")
    for r in d["rangs"]:
        print(f"Rang {n(r['rang'])} dans le genre {r['genre']} ({r['slug']})")
    if not d["rangs"]:
        print("Aucun rang de genre dans le dernier relevé.")
    if d.get("lien"):
        print(d["lien"])
    par_jour = {}
    for cle in METRIQUES:
        for p in d["mesures"].get(cle) or []:
            par_jour.setdefault(p.get("timestamp", "")[:10], {})[cle] = p.get("value")
    for p in d["mesures"].get("retention") or []:
        par_jour.setdefault(p.get("timestamp", "")[:10], {}).update({"d1": p.get("d1"), "d7": p.get("d7")})
    print(f"\n{'jour':<11} {'joueurs':>9} {'parties':>9} {'min/joueur':>10} {'pic':>7} {'favoris':>8} {'recos':>6} {'J1':>5} {'J7':>5}")
    for date in sorted(par_jour):
        j = par_jour[date]
        print(f"{date:<11} {n(j.get('uniquePlayers')):>9} {n(j.get('plays')):>9} "
              f"{n(j.get('averageMinutesPerPlayer'), '{:.1f}'):>10} {n(j.get('peakCCU')):>7} {n(j.get('favorites')):>8} "
              f"{n(j.get('recommendations')):>6} {ret(j.get('d1')):>5} {ret(j.get('d7')):>5}")
    if not par_jour or d["joueurs"] is None:
        print("Pas de chiffres : l'API ne donne rien sous 5 joueurs uniques sur la période.")
    else:
        print(f"\nSur {d['jours']} jour(s) : {n(d['joueurs'])} joueurs par jour, {n(d['minutes_par_joueur'], '{:.1f}')} min "
              f"par joueur, {n(d['parties_par_joueur'], '{:.2f}')} partie(s) par joueur, {n(d['favoris_pour_1000'], '{:.1f}')} "
              f"favoris pour 1 000 joueurs, tendance {signe(d['tendance'])}.")
    return 0


def cmd_comparer(a) -> int:
    iles, absentes = [], []
    for code in a.codes:
        d = ile(code, a.jours, rang=False)
        (iles if d else absentes).append(d or code)
    med = mediane(iles)
    if a.json:
        print(json.dumps({"iles": [sans_mesures(i) for i in iles], "mediane": med, "absentes": absentes,
                          "jours": a.jours}, ensure_ascii=False, indent=1))
        return 0
    tableau(iles, med)
    for code in absentes:
        print(f"{code} : inconnue de l'API (code faux, île privée ou non listée).")
    return 0


def cmd_nouveautes(a) -> int:
    vues, retenues, params = 0, [], {"size": max(1, min(a.taille, 1000))}
    for _ in range(max(1, a.pages)):
        data = lire("/islands", params) or {}
        lot = data.get("data") or []
        vues += len(lot)
        retenues += [x for x in lot if filtre(x, a.tag, a.mot)]
        suivant = ((data.get("meta") or {}).get("page") or {}).get("nextCursor")
        if not suivant or not lot:
            break
        params = {"size": params["size"], "after": suivant}
    mots = {}
    for x in retenues:
        for m in set(re.findall(r"[a-z0-9à-ÿ]{3,}", (x.get("title") or "").lower())):
            mots[m] = mots.get(m, 0) + 1
    frequents = sorted(mots.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    if a.json:
        print(json.dumps({"vues": vues, "retenues": retenues, "mots_frequents": frequents}, ensure_ascii=False, indent=1))
        return 0
    print(f"{len(retenues)} île(s) sur les {vues} dernières publiées"
          + (f" (filtre : {' '.join(a.tag + a.mot)})" if a.tag or a.mot else "") + ".\n")
    for x in retenues[:a.max]:
        print(f"{x.get('code'):<14} {(x.get('title') or '')[:60]:<60}  par {x.get('creatorCode') or '?'}  "
              f"[{', '.join(x.get('tags') or [])}]")
    if len(retenues) > a.max:
        print(f"… et {len(retenues) - a.max} autre(s) (--max pour en voir plus).")
    if frequents:
        print("\nMots les plus fréquents dans leurs titres : " + ", ".join(f"{m} ({c})" for m, c in frequents))
    return 0


def cmd_suivre(a) -> int:
    base = dossier() / "suivi"
    base.mkdir(parents=True, exist_ok=True)
    tout = {}
    for code in a.codes:
        d = ile(code, 7)
        if not d:
            print(f"{code} : inconnue de l'API (pas encore publiée, privée ou non listée).")
            continue
        fichier = base / f"{code}.json"
        try:
            hist = json.loads(fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            hist = {"code": code, "jours": {}}
        hist["titre"], hist["tags"] = d["titre"], d["tags"]
        avant = len(hist["jours"])
        for cle in METRIQUES:
            for p in d["mesures"].get(cle) or []:
                if p.get("value") is not None:
                    hist["jours"].setdefault(p["timestamp"][:10], {})[cle] = p["value"]
        for p in d["mesures"].get("retention") or []:
            for cle in ("d1", "d7"):
                if p.get(cle) is not None:
                    hist["jours"].setdefault(p["timestamp"][:10], {})[cle] = p[cle]
        for r in d["rangs"]:
            if r.get("rang") is not None:
                hist.setdefault("rangs", {})[datetime.now(timezone.utc).strftime("%Y-%m-%d")] = {
                    "genre": r["slug"], "rang": r["rang"]}
        hist["jours"] = dict(sorted(hist["jours"].items()))
        fichier.write_text(json.dumps(hist, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tout[code] = hist
        if not a.json:
            jours = list(hist["jours"].items())
            print(f"{d['titre']} ({code}) : {len(jours)} jour(s) gardé(s), dont {len(jours) - avant} nouveau(x) → {fichier}")
            for date, j in jours[-10:]:
                print(f"  {date}  {n(j.get('uniquePlayers')):>9} joueurs  {n(j.get('averageMinutesPerPlayer'), '{:.1f}'):>6} "
                      f"min/joueur  J1 {ret(j.get('d1')):>5}  J7 {ret(j.get('d7')):>5}")
    if a.json:
        print(json.dumps(tout, ensure_ascii=False, indent=1))
    return 0


def main(argv=None) -> int:
    global PAUSE
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    commun = argparse.ArgumentParser(add_help=False)
    commun.add_argument("--json", action="store_true")
    commun.add_argument("--jours", type=int, default=7, help="jours complets lus (7 au plus : l'API n'en garde pas plus)")
    commun.add_argument("--pause", type=float, default=PAUSE, help="pause entre deux appels, en secondes")
    p = argparse.ArgumentParser(description="Tendances des îles Fortnite (Fortnite Data API, lecture publique).")
    sous = p.add_subparsers(dest="commande")
    sous.add_parser("genres", parents=[commun])
    c = sous.add_parser("classement", parents=[commun])
    c.add_argument("genre", help="identifiant du genre : battle-royale, shooter… (tendances.py genres)")
    c.add_argument("--top", type=int, default=30, help="îles lues en tête du classement (200 au plus)")
    c.add_argument("--tag", action="append", default=[], help="ne garder que les îles qui portent ce tag (répétable)")
    c.add_argument("--mot", action="append", default=[], help="ne garder que les titres qui contiennent ce mot")
    c.add_argument("--titres", help="écrit les titres retenus dans ce fichier")
    i = sous.add_parser("ile", parents=[commun])
    i.add_argument("code")
    k = sous.add_parser("comparer", parents=[commun])
    k.add_argument("codes", nargs="+")
    v = sous.add_parser("nouveautes", parents=[commun])
    v.add_argument("--pages", type=int, default=1)
    v.add_argument("--taille", type=int, default=1000, help="îles par page (1 000 au plus)")
    v.add_argument("--tag", action="append", default=[])
    v.add_argument("--mot", action="append", default=[])
    v.add_argument("--max", type=int, default=40, help="lignes affichées")
    s = sous.add_parser("suivre", parents=[commun])
    s.add_argument("codes", nargs="+")
    a = p.parse_args(argv)
    if not a.commande:
        print(__doc__)
        return 1
    PAUSE = max(0.0, a.pause)
    a.jours = max(1, min(a.jours, 7))
    for code in getattr(a, "codes", []) + ([a.code] if getattr(a, "code", None) else []):
        if not CODE.match(code):
            print(f"code d'île « {code} » : attendu 12 chiffres en trois groupes, 1234-5678-9012", file=sys.stderr)
            return 1
    try:
        return {"genres": cmd_genres, "classement": cmd_classement, "ile": cmd_ile, "comparer": cmd_comparer,
                "nouveautes": cmd_nouveautes, "suivre": cmd_suivre}[a.commande](a)
    except Erreur as err:
        print(f"✗ {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
