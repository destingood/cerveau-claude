"""Boutiques en ligne : le cerveau suit chaque boutique comme un copilote (méthode du skill e-commerce, skills/ecommerce).

- `ajouter` : la boutique entre dans le cerveau, avec sa fiche contexte en mémoire (souvenir privé).
- `plan` : le plan décollage devient des à-faire datés (72 h, 14 jours, 30-60-90) que les échéances du cerveau
  rappellent au démarrage des sessions.
- `kpi` : les chiffres d'une semaine complète → taux, panier moyen, marge par heure (par canal), goulot probable, et un
  test statistique qui dit si une variation est réelle ou du bruit.
- `audit` : l'audit SEO/GEO express du skill, gardé en historique (ce qui a été corrigé, ce qui est apparu).
- `panel` : les panels de clients simulés du skill (scripts/panel_clients.py), gardés en historique ; une fois la
  variante choisie en ligne, les relevés de la semaine disent si le panel avait vu juste (fiabilité du panel).
- `bilan` : la revue de la semaine (tendance, plan tenu ou en retard, audits, panels, trois priorités).

Les données restent chez l'utilisateur : BRAIN_DIR/boutiques/<slug>.json, jamais envoyé au cerveau commun, compris dans
les sauvegardes ; les souvenirs créés (fiche, à-faire) sont marqués privés. Aucun réseau, sauf pour `audit`."""
from __future__ import annotations

import datetime as _dt
import importlib.util
import math
from pathlib import Path
from statistics import NormalDist

from .common import BRAIN_DIR, FileLock, fold, now_iso, read_json, slugify, write_json, write_text

DIR = BRAIN_DIR / "boutiques"
LOCK = DIR / ".boutiques.lock"
CHEMINS = ("plateforme", "0euro")
# [HEURISTIQUES du cerveau, à recaler sur la boutique avec `brain boutique regler <boutique> seuil.ajout=…`] :
# sessions par semaine sous lesquelles un taux ne veut rien dire, et taux (%) sous lesquels une étape est le goulot.
SEUILS = {"sessions": 100, "ajout": 4.0, "paiement": 35.0, "panier_commande": 25.0}

# type de boutique → (libellé, canal n° 1 pour aller vite, canal n° 2, actif durable) — module 00 du skill
TYPES = {
    "physique": ("produit physique démontrable", "vidéo courte (TikTok, Reels, Shorts) et fiches gratuites Google",
                 "TikTok Shop ou une marketplace", "SEO des collections, Pinterest"),
    "mode": ("mode, déco, cadeaux", "Pinterest et Instagram (trial reels)", "Vinted Pro ou Leboncoin Pro en appoint",
             "Pinterest et SEO des collections"),
    "createur": ("créations, fait main, personnalisé", "Etsy", "Instagram et Pinterest", "SEO, marque, liste e-mail"),
    "occasion": ("seconde main, reconditionné", "Leboncoin Pro, eBay, Vinted Pro", "groupes et forums de la niche",
                 "avis et SEO longue traîne"),
    "niche": ("niche technique ou passion", "forums, Reddit et groupes (valeur d'abord) et SEO longue traîne",
              "eBay et Merchant Center", "tutos YouTube, guides comparatifs"),
    "prevente": ("produit nouveau à financer", "prévente Ulule et liste d'attente", "presse locale et créateurs",
                 "communauté des contributeurs"),
    "local": ("commerce local avec boutique physique", "Google Business Profile et retrait en magasin",
              "Instagram local et groupes de la ville", "avis Google, SEO local"),
    "numerique": ("produits numériques", "communautés et tutos vidéo", "Product Hunt et partenaires",
                  "SEO, liste e-mail"),
    "b2b": ("vente aux professionnels", "prospection B2B ciblée, une par une (e-mail, téléphone, LinkedIn à la main)",
            "annuaires professionnels, salons", "SEO, études de cas"),
}
TYPE_ALIASES = {"produit": "physique", "physiques": "physique", "deco": "mode", "cadeau": "mode", "cadeaux": "mode",
                "fait-main": "createur", "artisan": "createur", "creation": "createur", "creations": "createur",
                "seconde-main": "occasion", "reconditionne": "occasion", "passion": "niche", "technique": "niche",
                "crowdfunding": "prevente", "ulule": "prevente", "magasin": "local", "digital": "numerique",
                "infoproduit": "numerique", "pro": "b2b", "professionnels": "b2b"}

# (jour, étape, action, livrable et indicateur, modules du skill, types pour lesquels l'action ne s'applique pas)
PLAN = [
    (0, "J0", "Offre, marge et fiche produit mobile vérifiées",
     "1 produit héros, marge positive (scripts/unit_economics.py), premier écran mobile complet", "02, 03", ()),
    (0, "J0", "Gate de conformité", "mentions légales, CGV, livraison et retours, bouton « renoncer au contrat ici », "
     "médiateur, sécurité du produit", "10", ()),
    (0, "J0", "Mesure en place", "Search Console et sitemap, Bing Webmaster Tools, convention UTM ; "
     "`brain boutique audit` sans ✗", "06, 04", ()),
    (0, "J0", "Fiches gratuites Google et Microsoft", "Merchant Center (livraison et retours), flux importé dans "
     "Microsoft Merchant Center", "07", ("b2b",)),
    (0, "J0", "Capture d'e-mails", "inscription avec consentement et e-mail de bienvenue", "08", ()),
    (1, "J1", "Réseau proche", "20 à 50 messages individuels (script du module 04)", "04", ()),
    (1, "J1", "Canal n° 1 : {c1}", "premières publications ou annonces soignées", "00, 05, 16", ()),
    (1, "J1", "3 premières vidéos", "démo, problème → solution, POV ; divulgation de l'auto-promotion activée sur "
     "TikTok", "05", ("b2b",)),
    (1, "J1", "Communautés", "1 contribution utile dans 2 communautés de la niche, sans lien", "04", ("local",)),
    (3, "J3", "Production", "3 à 6 vidéos de plus (une idée nouvelle chacune) ; réponse à tous les commentaires",
     "05", ("b2b",)),
    (3, "J3", "Partenaires", "5 micro-créateurs et 3 boutiques complémentaires contactés un par un", "04", ()),
    (3, "J3", "Analyse 72 h", "quelle source ajoute au panier ? canal n° 1 retenu (`brain add -t decision`)",
     "00, 09", ()),
    (7, "J7", "Relevé de la semaine", "`brain boutique kpi` puis `brain boutique bilan`", "09", ()),
    (7, "J7", "Doubler ce qui marche", "angles gagnants, trial reels, annonces vues sans favoris retravaillées",
     "05, 16", ()),
    (14, "J14", "Décision de cap", "arrêter, itérer ou amplifier, d'après le bilan des 14 jours", "00, 09", ()),
    (14, "J14", "Actifs durables", "1 page collection optimisée, 1 guide ou comparatif citable, FAQ des vraies "
     "questions", "06, 07", ()),
    (14, "J14", "Relevé de la semaine", "`brain boutique kpi` puis `brain boutique bilan`", "09", ()),
    (21, "J21", "Relevé de la semaine", "`brain boutique kpi` puis `brain boutique bilan`", "09", ()),
    (30, "J30", "Bilan 30 jours", "1 canal rentable trouvé ? flows bienvenue, panier abandonné et post-achat en place",
     "08, 09", ()),
    (60, "J60", "Industrialiser le canal n° 1", "production par lots, partenariats, SEO des collections, présence "
     "chez les tiers ({actif})", "00, 06, 07", ()),
    (90, "J90", "Second canal : {c2}", "parrainage, procédures écrites, revue du chemin (plateforme ou 0 €)",
     "00, 08, 09, 13", ()),
    (90, "J90", "Mise à jour du cerveau e-commerce", "revérifier frais des marketplaces, règles des plateformes, "
     "valeurs fiscales (references/sources.md du skill)", "sources", ()),
]


# ------------------------------------------------------------------------------------------------ données
def _path(slug):
    return DIR / f"{slug}.json"


def _num(value, name):
    """« 1 240 », « 703,50 » → nombre ≥ 0."""
    if value is None:
        return None
    try:
        v = float(str(value).replace(" ", "").replace("\xa0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        v = math.nan
    if not math.isfinite(v) or v < 0:
        raise ValueError(f"valeur invalide pour {name} : {value}")
    return v


def norm_type(value):
    if not value:
        return None
    key = slugify(fold(value), 20)
    key = TYPE_ALIASES.get(key, key)
    if key not in TYPES:
        raise ValueError(f"type inconnu « {value} » — types : {', '.join(TYPES)}")
    return key


def all_shops() -> list:
    out = []
    for p in sorted(DIR.glob("*.json")) if DIR.is_dir() else []:
        shop = read_json(p, None)
        if isinstance(shop, dict) and shop.get("slug"):
            out.append(shop)
    return out


def find(ref=None) -> dict:
    """Boutique par slug, nom ou début de nom ; sans référence : la seule suivie."""
    shops = all_shops()
    if not shops:
        raise LookupError("aucune boutique suivie : `brain boutique ajouter \"Nom\" --url https://…`")
    if not ref:
        if len(shops) == 1:
            return shops[0]
        raise LookupError("plusieurs boutiques suivies : précise laquelle (" + ", ".join(s["slug"] for s in shops) + ")")
    key = slugify(ref, 48)
    for s in shops:
        if s["slug"] == key or fold(s["nom"]) == fold(ref):
            return s
    hits = [s for s in shops if key and (s["slug"].startswith(key) or key in s["slug"])]
    if len(hits) == 1:
        return hits[0]
    raise LookupError(f"boutique introuvable : « {ref} » — suivies : " + ", ".join(s["slug"] for s in shops))


def lock():
    """Verrou des fichiers de suivi (deux sessions qui écrivent en même temps)."""
    return FileLock(LOCK, timeout=5)


def save(shop):
    shop["maj"] = now_iso()
    DIR.mkdir(parents=True, exist_ok=True)
    write_json(_path(shop["slug"]), shop, indent=1)


def _monday(day) -> _dt.date:
    return day - _dt.timedelta(days=day.weekday())


def week_of(text=None, today=None) -> str:
    """Lundi de la semaine visée : par défaut la dernière semaine complète ; sinon la semaine qui contient la date."""
    from . import dates
    today = today or _dt.date.today()
    if not text:
        return (_monday(today) - _dt.timedelta(days=7)).isoformat()
    iso = dates.parse(text, today)
    if not iso:
        raise ValueError(f"semaine illisible : « {text} » (ex. 12/10, 12/10/2026, il y a 7 jours)")
    return _monday(_dt.date.fromisoformat(iso)).isoformat()


def _fr(x, dec=0):
    if x is None:
        return "—"
    s = f"{x:,.{dec}f}".replace(",", " ").replace(".", ",")
    return s


def _pct(x, dec=1):
    return "—" if x is None else f"{_fr(x, dec)} %"


def _eur(x, dec=0):
    return "—" if x is None else f"{_fr(x, dec)} €"


def _p(p):
    return "p < 0,001" if p < 0.001 else f"p = {_fr(p, 3 if p < 0.1 else 2)}"


def _day(iso):
    try:
        return _dt.date.fromisoformat(iso[:10]).strftime("%d/%m")
    except (TypeError, ValueError):
        return "?"


# ------------------------------------------------------------------------------------------------ ajouter, régler
def ajouter(nom, url=None, plateforme=None, chemin=None, type_=None, marge_commande=None) -> list:
    """La boutique entre dans le cerveau (fichier de suivi + fiche contexte en mémoire, privée). → lignes."""
    nom = " ".join(str(nom or "").split())
    if not nom:
        raise ValueError("nom manquant : brain boutique ajouter \"Nom de la boutique\"")
    slug = slugify(nom, 40) or "boutique"
    with lock():
        return _ajouter(nom, slug, url, plateforme, chemin, type_, marge_commande)


def _ajouter(nom, slug, url, plateforme, chemin, type_, marge_commande) -> list:
    from .store import Brain
    if _path(slug).exists():
        raise ValueError(f"déjà suivie : `{slug}` (`brain boutique regler {slug} …` pour la modifier)")
    if chemin and fold(chemin).replace(" ", "") not in ("plateforme", "0euro", "0€", "zero"):
        raise ValueError("chemin : « plateforme » (abonnement accepté) ou « 0euro » (aucun coût fixe)")
    chemin = None if not chemin else ("plateforme" if fold(chemin).startswith("plat") else "0euro")
    type_ = norm_type(type_)
    marge = _num(marge_commande, "--marge-commande")
    shop = {"version": 1, "slug": slug, "nom": nom, "url": url or None, "plateforme": plateforme or None,
            "chemin": chemin, "type": type_, "marge_commande": marge, "creee": now_iso()[:10], "seuils": dict(SEUILS),
            "kpi": [], "audits": [], "plan": []}
    lines = [f"✓ boutique suivie : {nom} `{slug}` → {_path(slug)}"]
    title = f"Boutique {nom} — fiche contexte"
    with Brain.edit() as b:
        found = next((n for n in b.active(("fact",)) if fold(n.get("title", "")) == fold(title)), None)
        if found:
            shop["fiche"] = found["id"]
            lines.append(f"· fiche contexte déjà en mémoire : `{found['id']}`")
        else:
            body = _fiche_body(shop)
            node = b.add("fact", title, body, tags=["boutique", "ecommerce", slug], importance=5,
                         meta={"prive": True, "keys": f"{nom}, {slug}, ma boutique, mon site, boutique en ligne"})
            shop["fiche"] = node["id"]
            lines.append(f"✓ fiche contexte en mémoire (privée) : `{node['id']}` — à compléter avec le modèle "
                         "assets/modele-contexte-boutique.md du skill")
    save(shop)
    lines.append(f"→ ensuite : `brain boutique plan {slug}` (plan daté), `brain boutique audit {slug}`, chaque lundi "
                 f"`brain boutique kpi {slug} --sessions … --ajouts … --commandes … --ca …`")
    return lines


def _fiche_body(shop) -> str:
    t = TYPES.get(shop.get("type") or "")
    parts = [f"URL : {shop.get('url') or '?'}", f"Plateforme : {shop.get('plateforme') or '?'}",
             f"Chemin : {shop.get('chemin') or '?'}", f"Type : {t[0] if t else '?'}"]
    if t:
        parts.append(f"Canal n° 1 conseillé : {t[1]} ; canal n° 2 : {t[2]}")
    if shop.get("marge_commande") is not None:
        parts.append(f"Marge de contribution par commande : {_eur(shop['marge_commande'], 2)}")
    parts.append(f"Suivi chiffré : `brain boutique bilan {shop['slug']}` (données privées).")
    return "\n".join(parts)


def regler(ref, pairs) -> list:
    """Modifie le profil : url=, plateforme=, chemin=, type=, marge=, nom=, seuil.<sessions|ajout|paiement|panier_commande>=."""
    with lock():
        return _regler(find(ref), pairs)


def _regler(shop, pairs) -> list:
    done = []
    for pair in pairs or []:
        key, sep, val = str(pair).partition("=")
        key, val = fold(key.strip()), val.strip()
        if not sep:
            raise ValueError(f"réglage illisible : « {pair} » (forme clé=valeur)")
        if key in ("url", "plateforme", "nom"):
            shop[key] = val or None
        elif key == "chemin":
            if fold(val).replace(" ", "") not in ("plateforme", "0euro", "0€", "zero"):
                raise ValueError("chemin : plateforme ou 0euro")
            shop["chemin"] = "plateforme" if fold(val).startswith("plat") else "0euro"
        elif key == "type":
            shop["type"] = norm_type(val)
        elif key in ("marge", "marge_commande", "marge-commande"):
            shop["marge_commande"] = _num(val, "marge")
            key = "marge_commande"
        elif key.startswith("seuil."):
            name = key.split(".", 1)[1].replace("-", "_")
            if name not in SEUILS:
                raise ValueError(f"seuil inconnu : {name} ({', '.join(SEUILS)})")
            shop.setdefault("seuils", dict(SEUILS))[name] = _num(val, key)
        else:
            raise ValueError(f"réglage inconnu : {key} (url, plateforme, nom, chemin, type, marge, seuil.…)")
        done.append(f"{key} = {val}")
    if not done:
        raise ValueError("rien à régler : brain boutique regler <boutique> cle=valeur …")
    save(shop)
    return [f"✓ {shop['nom']} : " + " · ".join(done)]


# ------------------------------------------------------------------------------------------------ plan daté
def plan(ref, debut=None, type_=None, court=False, force=False, today=None) -> list:
    """Le plan décollage en à-faire datés (privés) ; les échéances proches remontent au démarrage des sessions."""
    with lock():
        return _plan(find(ref), debut, type_, court, force, today)


def _plan(shop, debut, type_, court, force, today) -> list:
    from . import dates
    from .store import Brain
    today = today or _dt.date.today()
    if type_:
        shop["type"] = norm_type(type_)
    kind = shop.get("type") or "physique"
    lab, c1, c2, actif = TYPES[kind]
    start_iso = dates.parse(debut, today) if debut else today.isoformat()
    if not start_iso:
        raise ValueError(f"date de début illisible : « {debut} »")
    start = _dt.date.fromisoformat(start_iso)
    lines = []
    with Brain.edit() as b:
        open_ids = [p["id"] for p in shop.get("plan") or [] if (b.nodes.get(p["id"]) or {}).get("status") == "active"]
        if open_ids and not force:
            raise ValueError(f"plan déjà en cours ({len(open_ids)} à-faire ouverts) : `--force` pour le recréer "
                             "(les à-faire ouverts de l'ancien plan sont archivés)")
        for nid in open_ids:
            meta = dict(b.nodes[nid].get("meta") or {})
            meta["annule"] = now_iso()[:10]
            b.update(nid, status="archived", meta=meta)
        shop["plan"] = []
        for day, etape, action, detail, modules, skip in PLAN:
            if kind in skip or (court and day > 14):
                continue
            action = action.format(c1=c1, c2=c2, actif=actif)
            detail = detail.format(c1=c1, c2=c2, actif=actif)
            due = (start + _dt.timedelta(days=day)).isoformat()
            node = b.add("todo", f"{shop['nom']} · {etape} : {action}",
                         f"{detail}\nModules du skill e-commerce : {modules}.",
                         tags=["boutique", "plan", shop["slug"]], importance=4 if day <= 3 else 3,
                         meta={"due": due, "prive": True, "boutique": shop["slug"]})
            shop["plan"].append({"id": node["id"], "etape": etape, "due": due})
    shop["plan_debut"] = start.isoformat()
    save(shop)
    lines.append(f"✓ plan décollage de {shop['nom']} ({lab}) : {len(shop['plan'])} à-faire datés, du "
                 f"{start.strftime('%d/%m')} au {_day(shop['plan'][-1]['due']) if shop['plan'] else '?'}")
    lines.append(f"  canal n° 1 : {c1} · canal n° 2 : {c2} · actif durable : {actif}")
    lines.append("  les échéances proches remontent au démarrage de chaque session ; terminer : `brain done <id>` · "
                 f"suivre : `brain boutique bilan {shop['slug']}`")
    return lines


# ------------------------------------------------------------------------------------------------ indicateurs
def ztest(x1, n1, x0, n0):
    """Test bilatéral de deux proportions → (p-valeur, raison) ; p = None si le test n'a pas de sens ici."""
    if not n1 or not n0:
        return None, "pas de semaine de comparaison"
    p = (x1 + x0) / (n1 + n0)
    if p <= 0 or p >= 1:
        return None, "taux nul : rien à comparer"
    if min(n1 * p, n1 * (1 - p), n0 * p, n0 * (1 - p)) < 5:
        return None, "trop peu d'événements pour conclure"
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n0))
    z = (x1 / n1 - x0 / n0) / se
    return 2 * (1 - NormalDist().cdf(abs(z))), ""


def rates(e, marge_commande=None) -> dict:
    s, a, c, o, ca, h = (e.get(k) for k in ("sessions", "ajouts", "checkouts", "commandes", "ca", "heures"))
    marge = e.get("marge")
    if marge is None and marge_commande is not None and o is not None:
        marge = marge_commande * o
    return {"ajout": a / s * 100 if s and a is not None else None,
            "conversion": o / s * 100 if s and o is not None else None,
            "paiement": o / c * 100 if c and o is not None else None,
            "panier_commande": o / a * 100 if a and o is not None else None,
            "panier_moyen": ca / o if o and ca is not None else None,
            "marge": marge, "marge_heure": marge / h if marge is not None and h else None,
            "ca_heure": ca / h if ca is not None and h else None}


def diagnostic(e, shop) -> list:
    """Goulot probable de la semaine → [(niveau, texte)] (règles du module 01 du skill)."""
    seuils = dict(SEUILS, **(shop.get("seuils") or {}))
    r = rates(e, shop.get("marge_commande"))
    out = []
    if shop.get("marge_commande") is not None and shop["marge_commande"] <= 0:
        out.append(("🔴", "marge par commande nulle ou négative : chaque vente coûte de l'argent → prix, coûts, "
                          "bundles (module 02)"))
    if (e.get("sessions") or 0) < seuils["sessions"]:
        out.append(("🔴", f"goulot : le trafic ({_fr(e.get('sessions') or 0)} visites ; sous "
                          f"{_fr(seuils['sessions'])}, un taux ne veut encore rien dire) → plan décollage, "
                          "acquisition, vidéo, marketplaces (modules 00, 04, 05, 16)"))
    elif r["ajout"] is not None and r["ajout"] < seuils["ajout"]:
        out.append(("🔴", f"goulot probable : l'offre ou la fiche produit ({_pct(r['ajout'])} d'ajouts au panier, "
                          f"repère {_pct(seuils['ajout'])}) → offre, prix, premier écran mobile, preuves, confiance "
                          "(modules 02, 03, 15)"))
    elif r["paiement"] is not None and r["paiement"] < seuils["paiement"]:
        out.append(("🔴", f"goulot probable : le paiement ({_pct(r['paiement'])} des paiements commencés aboutissent, "
                          f"repère {_pct(seuils['paiement'])}) → frais et délais affichés tôt, paiements express, "
                          "réassurance (module 03)"))
    elif r["paiement"] is None and r["panier_commande"] is not None and r["panier_commande"] < seuils["panier_commande"]:
        out.append(("🔴", f"goulot probable : panier et paiement ({_pct(r['panier_commande'])} des ajouts deviennent "
                          f"des commandes, repère {_pct(seuils['panier_commande'])}) → frais, délais, checkout "
                          "(module 03) et relance des paniers abandonnés (module 08)"))
    else:
        out.append(("🟢", "pas de goulot évident dans l'entonnoir : amplifier le canal qui a la meilleure marge par "
                          "heure (module 09)"))
    return out


def _canaux(e, marge_commande):
    rows = []
    for name, c in (e.get("canaux") or {}).items():
        s, o, h = c.get("sessions"), c.get("commandes"), c.get("heures")
        marge = marge_commande * o if marge_commande is not None and o is not None else None
        rows.append({"canal": name, "sessions": s, "commandes": o, "heures": h,
                     "conversion": o / s * 100 if s and o is not None else None,
                     "marge_heure": marge / h if marge is not None and h else None})
    key = (lambda r: r["marge_heure"]) if any(r["marge_heure"] is not None for r in rows) else (lambda r: r["commandes"])
    rows.sort(key=lambda r: (key(r) is None, -(key(r) or 0)))
    return rows


def parse_canal(spec):
    """« tiktok:450:6:5 » → ("tiktok", {sessions, commandes, heures})."""
    parts = [p.strip() for p in str(spec).split(":")]
    if len(parts) < 3 or not parts[0]:
        raise ValueError(f"canal illisible : « {spec} » (forme nom:sessions:commandes[:heures])")
    vals = [_num(p, f"canal {parts[0]}") for p in parts[1:4]]
    return slugify(parts[0], 30), {"sessions": vals[0], "commandes": vals[1], "heures": vals[2] if len(vals) > 2 else None}


def kpi(ref, sessions=None, ajouts=None, commandes=None, ca=None, checkouts=None, heures=None, marge=None, canaux=(),
        semaine=None, note=None, today=None) -> list:
    """Enregistre la semaine (remplace un relevé de la même semaine) et dit ce qu'elle montre. → lignes."""
    from . import observations
    with lock():
        shop = find(ref)
        e, lines = _kpi(shop, sessions, ajouts, commandes, ca, checkouts, heures, marge, canaux, semaine, note, today)
    r = rates(e, shop.get("marge_commande"))
    goulot = diagnostic(e, shop)[0][1].split(" → ")[0]
    try:
        observations.add([f"🟡 {shop['nom']} semaine du {_day(e['semaine'])} : {_fr(e['sessions'])} sessions, "
                          f"{_fr(e['commandes'])} commandes ({_pct(r['conversion'], 2)})"
                          + (f", CA {_eur(e.get('ca'))}" if e.get("ca") is not None else "") + f" ; {goulot}"])
    except Exception:  # l'observation n'est qu'un plus : le relevé est déjà enregistré
        pass
    return lines


def _kpi(shop, sessions, ajouts, commandes, ca, checkouts, heures, marge, canaux, semaine, note, today):
    e = {"semaine": week_of(semaine, today), "sessions": _num(sessions, "--sessions"), "ajouts": _num(ajouts, "--ajouts"),
         "checkouts": _num(checkouts, "--checkouts"), "commandes": _num(commandes, "--commandes"),
         "ca": _num(ca, "--ca"), "heures": _num(heures, "--heures"), "marge": _num(marge, "--marge"),
         "note": " ".join(str(note).split()) if note else None, "releve": now_iso()[:10]}
    if e["sessions"] is None or e["commandes"] is None:
        raise ValueError("il faut au moins --sessions et --commandes (et idéalement --ajouts et --ca)")
    if (e["ajouts"] is not None and e["ajouts"] > e["sessions"]) or e["commandes"] > e["sessions"]:
        raise ValueError("incohérent : plus d'ajouts au panier ou de commandes que de sessions")
    e["canaux"] = dict(parse_canal(c) for c in canaux or ())
    e = {k: v for k, v in e.items() if v not in (None, {}, "")}
    shop["kpi"] = sorted([k for k in shop.get("kpi") or [] if k.get("semaine") != e["semaine"]] + [e],
                         key=lambda k: k["semaine"])
    save(shop)
    return e, report(shop, e)


def report(shop, e) -> list:
    """Lecture d'une semaine : chiffres, comparaison testée aux 4 semaines d'avant, canaux, goulot."""
    mc = shop.get("marge_commande")
    r = rates(e, mc)
    head = (f"🛒 {shop['nom']} — semaine du {_day(e['semaine'])} : {_fr(e['sessions'])} sessions · "
            f"{_fr(e['commandes'])} commandes ({_pct(r['conversion'], 2)})")
    if e.get("ca") is not None:
        head += f" · CA {_eur(e['ca'])} · panier moyen {_eur(r['panier_moyen'], 2)}"
    lines = [head]
    funnel = []
    if r["ajout"] is not None:
        funnel.append(f"ajouts au panier {_fr(e['ajouts'])} ({_pct(r['ajout'])})")
    if r["paiement"] is not None:
        funnel.append(f"paiements commencés {_fr(e['checkouts'])} → {_pct(r['paiement'])} aboutis")
    elif r["panier_commande"] is not None:
        funnel.append(f"{_pct(r['panier_commande'])} des ajouts deviennent des commandes")
    if funnel:
        lines.append("  entonnoir : " + " · ".join(funnel))
    if r["marge"] is not None:
        lines.append(f"  marge {_eur(r['marge'])}" + (f" · {_fr(e['heures'], 1)} h → {_eur(r['marge_heure'], 2)} "
                                                       "par heure" if r["marge_heure"] is not None else ""))
    elif e.get("heures") and r["ca_heure"] is not None:
        lines.append(f"  {_fr(e['heures'], 1)} h → {_eur(r['ca_heure'], 2)} de CA par heure (marge par commande "
                     f"inconnue : `brain boutique regler {shop['slug']} marge=…`)")
    prev = [k for k in shop.get("kpi") or [] if k["semaine"] < e["semaine"]][-4:]
    if prev:
        s0, o0 = sum(k.get("sessions") or 0 for k in prev), sum(k.get("commandes") or 0 for k in prev)
        p, why = ztest(e["commandes"], e["sessions"], o0, s0)
        conv0 = o0 / s0 * 100 if s0 else None
        delta = (r["conversion"] - conv0) if conv0 is not None and r["conversion"] is not None else None
        avant = "la semaine d'avant" if len(prev) == 1 else f"les {len(prev)} semaines d'avant"
        trend = (f"  conversion {_pct(r['conversion'], 2)} contre {_pct(conv0, 2)} sur {avant} "
                 f"({'+' if (delta or 0) >= 0 else ''}{_fr(delta, 2)} pt)")
        if p is None:
            trend += f" : {why}"
        elif p < 0.05:
            trend += f" : variation réelle ({_p(p)})"
        else:
            trend += f" : pas significatif ({_p(p)}), ne pas conclure"
        lines.append(trend)
        a0 = sum(k.get("ajouts") or 0 for k in prev if k.get("ajouts") is not None)
        s0a = sum(k.get("sessions") or 0 for k in prev if k.get("ajouts") is not None)
        if e.get("ajouts") is not None and s0a:
            p2, why2 = ztest(e["ajouts"], e["sessions"], a0, s0a)
            if p2 is not None and p2 < 0.05:
                lines.append(f"  ajouts au panier {_pct(r['ajout'])} contre {_pct(a0 / s0a * 100)} : variation réelle "
                             f"({_p(p2)})")
        ventes0 = o0 / len(prev)
        if e["commandes"] and ventes0:
            lines.append(f"  commandes : {_fr(e['commandes'])} contre {_fr(ventes0, 1)} en moyenne avant")
    else:
        lines.append("  première semaine relevée : elle devient la base de mesure (état « avant »)")
    rows = _canaux(e, mc)
    if rows:
        best = rows[0]
        lines.append("  canaux : " + " · ".join(
            f"{x['canal']} {_pct(x['conversion'], 2)}" + (f", {_eur(x['marge_heure'], 2)}/h" if x["marge_heure"] is not None
                                                         else "") for x in rows) + f" → n° 1 : {best['canal']}")
    for niveau, text in diagnostic(e, shop):
        lines.append(f"  {niveau} {text}")
    return lines


# ------------------------------------------------------------------------------------------------ audit
def _script(name, quoi):
    """Outil du skill e-commerce (scripts/<name>.py), chargé comme module."""
    from .install import skill_sources
    src = skill_sources().get("ecommerce")
    path = src / "scripts" / f"{name}.py" if src else None
    if not path or not path.is_file():
        raise RuntimeError(f"{quoi} introuvable (skill e-commerce absent : `brain install` le pose)")
    spec = importlib.util.spec_from_file_location(f"cerveau_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _audit_module():
    return _script("audit_site", "outil d'audit")


def _portee(point: str) -> str:
    """Quelle partie de l'audit a produit ce point (« ✗ Conformité : … » → legal)."""
    sujet = point[2:] if len(point) > 2 else point
    return ("legal" if sujet.startswith("Conformité") else "pages" if sujet.startswith("Site :")
            else "vitesse" if sujet.startswith("Vitesse") else "base")


def audit(ref_or_url, timeout=20.0, legal=False, pages=0, vitesse=False, rapport=None) -> list:
    """Audit express d'une boutique suivie (son URL) ou d'une adresse ; historique gardé pour une boutique suivie.
    legal : pages légales et conformité · pages : pages du sitemap lues · vitesse : PageSpeed Insights ·
    rapport : fichier Markdown écrit en plus."""
    shop = None
    target = str(ref_or_url or "")
    if not target.startswith(("http://", "https://")):
        shop = find(target or None)
        target = shop.get("url") or ""
        if not target:
            raise ValueError(f"pas d'URL pour {shop['nom']} : `brain boutique regler {shop['slug']} url=https://…`")
    mod = _audit_module()
    rep = mod.audit(target, timeout=timeout, legal=legal, pages=max(0, min(int(pages or 0), 200)), vitesse=vitesse)
    lines = mod.texte(rep).splitlines()
    if rapport:
        Path(rapport).expanduser().write_text(mod.markdown(rep), encoding="utf-8")
        lines.append(f"\n✓ rapport Markdown : {rapport}")
    if shop is None:
        return lines
    pts = [f"{p['niveau']} {p['sujet']} : {p['constat']}" for p in rep["points"] if p["niveau"] in ("✗", "⚠")]
    portee = ["base"] + [x for x, on in (("legal", legal), ("pages", pages), ("vitesse", vitesse)) if on]
    entry = {"date": now_iso()[:10], "url": rep.get("url_finale") or target, "statut": rep.get("statut"),
             "x": sum(p["niveau"] == "✗" for p in rep["points"]), "warn": sum(p["niveau"] == "⚠" for p in rep["points"]),
             "points": pts, "portee": portee}
    with lock():  # relu après l'audit (réseau) : un relevé fait entre-temps n'est pas écrasé
        shop = find(shop["slug"])
        before = (shop.get("audits") or [])[-1:] or [None]
        shop["audits"] = (shop.get("audits") or [])[-19:] + [entry]
        save(shop)
    prev = before[0]
    if prev:
        # comparaison sur ce que les deux audits ont regardé (un audit simple ne « corrige » pas la conformité)
        commun = set(prev.get("portee") or ["base"]) & set(portee)
        key = lambda s: s.split(" : ", 1)[0]  # niveau + sujet : le constat chiffré peut bouger
        old = {key(s) for s in prev.get("points") or [] if _portee(s) in commun}
        new = {key(s) for s in pts if _portee(s) in commun}
        fixed, appeared = sorted(old - new), sorted(new - old)
        nb = lambda keys, n: sum(k.startswith(n) for k in keys)
        lines.append(f"\nDepuis l'audit du {_day(prev['date'])} : ✗ {nb(old, '✗')} → {nb(new, '✗')} · "
                     f"⚠ {nb(old, '⚠')} → {nb(new, '⚠')}"
                     + ("" if commun == set(portee) == set(prev.get("portee") or ["base"])
                        else " (sur les points vérifiés les deux fois)"))
        lines += [f"  ✓ corrigé : {s}" for s in fixed] + [f"  ✗ nouveau : {s}" for s in appeared]
    lines.append(f"(audit gardé dans le suivi de {shop['nom']} : `brain boutique bilan {shop['slug']}`)")
    return lines


# ------------------------------------------------------------------------------------------------ panels simulés
def _lire_synthese(chemin):
    """Dossier d'un panel (synthèse recalculée), son panel.json ou son synthese.json → (synthèse, dossier)."""
    p = Path(chemin).expanduser()
    if p.is_dir() or p.name == "panel.json":
        mod = _script("panel_clients", "outil du panel de clients simulés")
        dossier, data = mod.charger(p)
        return mod.synthese(data), dossier
    s = read_json(p, None)
    if not isinstance(s, dict) or s.get("outil") != "panel_clients" or "par_variante" not in s:
        raise ValueError(f"{p} : ni dossier de panel, ni synthese.json (skill e-commerce, scripts/panel_clients.py)")
    return s, p.parent


def _panel_record(s, source) -> dict:
    pred, comp, ref = s.get("prediction") or {}, s.get("comparaison") or {}, s.get("reference")
    return {"empreinte": s.get("empreinte"), "date": s.get("cree") or now_iso()[:10], "importe": now_iso()[:10],
            "nom": s.get("nom"), "type": s.get("type"), "personas": s.get("personas"), "tours": s.get("tours"),
            "variantes": {v: {"libelle": x.get("libelle"), "prix": x.get("prix"), "moyenne": x.get("moyenne"),
                              "interesses": x.get("interesses")} for v, x in (s.get("par_variante") or {}).items()},
            "actuelle": s.get("actuelle"), "gagnante": pred.get("gagnante"), "force": comp.get("force"),
            "ecart": comp.get("ecart"), "metrique": pred.get("metrique"),
            "objections": [[o["code"], round(o["part"])] for o in (s.get("objections") or {}).get(ref, [])[:3]],
            "questions": [q["question"] for q in (s.get("questions") or [])[:5]], "source": str(source)}


def _panel_ligne(rec) -> str:
    vs = rec.get("variantes") or {}
    res = "aucune réponse"
    tri = sorted((v for v in vs if vs[v].get("moyenne") is not None), key=lambda v: -vs[v]["moyenne"])
    g = rec.get("gagnante")
    if len(tri) > 1 and g:
        autre = next(v for v in tri if v != g)
        res = (f"{g} devant {autre} ({_fr(vs[g]['moyenne'], 1)} contre {_fr(vs[autre]['moyenne'], 1)} sur 5, écart "
               f"{rec.get('force') or '?'})")
    elif len(tri) > 1:
        res = "pas d'écart net entre " + ", ".join(tri)
    elif tri:
        res = f"intention {_fr(vs[tri[0]]['moyenne'], 1)} sur 5"
    if rec.get("objections"):
        res += " · objections : " + ", ".join(f"{c} {p} %" for c, p in rec["objections"])
    return f"{rec.get('type')} « {rec.get('nom')} » : {res}"


def verdict_panel(shop, rec) -> tuple:
    """La variante mise en ligne a-t-elle fait ce que le panel prévoyait ? Semaines relevées entières avant et après la
    mise en ligne (4 au plus de chaque côté), test de deux proportions. → (code, texte) ; code : juste, faux, bruit,
    attente, na."""
    v, le, act, met = rec.get("applique"), rec.get("applique_le"), rec.get("actuelle"), rec.get("metrique")
    if not v:
        return "na", "pas encore en ligne"
    if not act:
        return "na", "pas de version de départ : rien à comparer automatiquement"
    if v == act:
        return "na", "version actuelle gardée : rien à comparer"
    if not met:
        return "na", "pas de mesure automatique pour ce type de test : compare à la main"
    d = _dt.date.fromisoformat(le)
    champ = "ajouts" if met == "ajout" else "commandes"
    kpis = [k for k in shop.get("kpi") or [] if k.get(champ) is not None and k.get("sessions")]
    avant = [k for k in kpis if _dt.date.fromisoformat(k["semaine"]) + _dt.timedelta(days=7) <= d][-4:]
    apres = [k for k in kpis if _dt.date.fromisoformat(k["semaine"]) >= d][:4]
    if not avant:
        return "attente", f"aucune semaine relevée avant le {_day(le)} : pas de base de comparaison"
    if not apres:
        return "attente", f"attend une semaine complète relevée après le {_day(le)} (`brain boutique kpi`)"
    x0, n0 = sum(k[champ] for k in avant), sum(k["sessions"] for k in avant)
    x1, n1 = sum(k[champ] for k in apres), sum(k["sessions"] for k in apres)
    nom = "ajouts au panier" if met == "ajout" else "conversion"
    base = f"{nom} {_pct(x0 / n0 * 100, 2)} → {_pct(x1 / n1 * 100, 2)}"
    vs = rec.get("variantes") or {}
    pred = (vs.get(v, {}).get("moyenne") or 0) - (vs.get(act, {}).get("moyenne") or 0)
    vu = (f"le panel voyait {v} {'devant' if pred > 0 else 'derrière'} {act} "
          f"({'+' if pred > 0 else ''}{_fr(pred, 1)})" if abs(pred) >= 0.25
          else f"le panel ne voyait pas d'écart entre {v} et {act}")
    p, why = ztest(x1, n1, x0, n0)
    if p is None:
        return "attente", f"{base} : {why}"
    if p >= 0.05:
        return "bruit", f"≈ {base} : pas encore de variation réelle ({_p(p)}), ni confirmé ni contredit ; {vu}"
    reel = 1 if x1 / n1 > x0 / n0 else -1
    predit = 0 if abs(pred) < 0.25 else (1 if pred > 0 else -1)
    if predit == reel:
        return "juste", f"✓ vu juste : {base} (variation réelle, {_p(p)}) ; {vu}"
    return "faux", f"✗ contredit : {base} (variation réelle, {_p(p)}) ; {vu}"


def fiabilite(shop):
    """« fiabilité du panel : 2 vus justes sur 3 vérifiés » ; None tant qu'aucun panel n'est vérifié."""
    codes = [verdict_panel(shop, p)[0] for p in shop.get("panels") or []]
    j, n = codes.count("juste"), codes.count("juste") + codes.count("faux")
    if not n:
        return None
    return (f"fiabilité du panel : {j} vu{'s' if j > 1 else ''} juste{'s' if j > 1 else ''} sur {n} vérifié"
            f"{'s' if n > 1 else ''}" + (" (indice seulement : il faut plusieurs tests)" if n < 5 else ""))


def panel(ref, importer=None, applique=None, variante=None, le=None, today=None) -> list:
    """Panels de clients simulés d'une boutique : importer une synthèse, noter la variante mise en ligne, ou lister
    (avec le verdict des vrais chiffres). → lignes."""
    today = today or _dt.date.today()
    if importer:
        s, source = _lire_synthese(importer)
        with lock():
            shop = find(ref)
            return _panel_importer(shop, s, source)
    if applique:
        with lock():
            shop = find(ref)
            return _panel_appliquer(shop, applique, variante, le, today)
    return panels(find(ref))


def _panel_importer(shop, s, source) -> list:
    from . import observations
    liste_ = shop.get("panels") or []
    rec = _panel_record(s, source)
    old = next((p for p in liste_ if rec["empreinte"] and p.get("empreinte") == rec["empreinte"]), None)
    if old:  # le même panel, relu après un tour de plus : même id, mise en ligne gardée
        rec.update({"id": old["id"], "applique": old.get("applique"), "applique_le": old.get("applique_le")})
        liste_[liste_.index(old)] = rec
    else:
        n = max((int(p["id"][1:]) for p in liste_ if str(p.get("id", ""))[1:].isdigit()), default=0) + 1
        rec["id"] = f"S{n}"
        liste_.append(rec)
    shop["panels"] = liste_[-30:]
    save(shop)
    lines = [f"✓ panel {rec['id']} {'mis à jour' if old else 'gardé'} dans le suivi de {shop['nom']} (privé) : "
             f"{_panel_ligne(rec)}"]
    if rec["questions"]:
        lines.append("  questions à traiter sur la page : " + " · ".join(rec["questions"][:3]))
    g, act = rec["gagnante"], rec["actuelle"]
    if g and act and g != act and rec["metrique"]:
        lines.append(f"→ quand {g} est en ligne (une seule modification à la fois) : `brain boutique panel "
                     f"{shop['slug']} --applique {rec['id']} --variante {g} [--le <date>]`, puis chaque lundi "
                     "`brain boutique kpi` : le bilan dira si le panel avait vu juste")
    elif not rec["metrique"]:
        lines.append("· pas de vérification automatique pour ce type de test (idée de produit, contenu) : compare à "
                     "la main avec les vrais résultats, puis `brain add -t learning …`")
    elif g and g == act:
        lines.append("· le panel préfère la version actuelle : garde-la, et travaille ses objections")
    else:
        lines.append("· pas d'écart net entre les variantes : travaille plutôt les objections de la version actuelle")
    try:
        observations.add([f"🟡 {shop['nom']} : panel simulé {rec['id']} ({_panel_ligne(rec)}) — hypothèse, pas de "
                          "vrais clients"])
    except Exception:  # l'observation n'est qu'un plus : le panel est déjà gardé
        pass
    return lines


def _panel_appliquer(shop, applique, variante, le, today) -> list:
    from . import dates
    key = str(applique).strip().upper()
    key = f"S{key}" if key.isdigit() else key
    rec = next((p for p in shop.get("panels") or [] if p.get("id") == key), None)
    if not rec:
        ids = ", ".join(p["id"] for p in shop.get("panels") or []) or "aucun"
        raise LookupError(f"panel inconnu : {applique} (panels de {shop['nom']} : {ids})")
    v = str(variante or rec.get("gagnante") or "").strip().upper()
    if v not in (rec.get("variantes") or {}):
        noms = ", ".join(rec.get("variantes") or {})
        raise ValueError(f"--variante : une des variantes du panel {rec['id']} ({noms})")
    iso = dates.parse(le, today) if le else today.isoformat()
    if not iso:
        raise ValueError(f"date illisible : « {le} » (ex. 02/11, hier, 2026-11-02)")
    rec["applique"], rec["applique_le"] = v, iso
    save(shop)
    return [f"✓ {rec['id']} : variante {v} en ligne depuis le {_day(iso)} → {verdict_panel(shop, rec)[1]}"]


def panels(shop) -> list:
    liste_ = shop.get("panels") or []
    if not liste_:
        return [f"Aucun panel simulé pour {shop['nom']} : `python scripts/panel_clients.py preparer …` (skill "
                f"e-commerce, module 17), puis `brain boutique panel {shop['slug']} --importer <dossier>`"]
    lines = [f"🧪 Panels simulés de {shop['nom']} ({len(liste_)}) — des personas jouées par Claude, pas de vrais "
             "clients"]
    for p in liste_[-10:]:
        lines.append(f"- {p['id']} · {_day(p['date'])} · {_panel_ligne(p)}")
        if p.get("applique"):
            lines.append(f"    {p['applique']} en ligne depuis le {_day(p['applique_le'])} → "
                         f"{verdict_panel(shop, p)[1]}")
        elif p.get("gagnante") and p.get("actuelle") and p["gagnante"] != p["actuelle"] and p.get("metrique"):
            lines.append(f"    pas encore en ligne : `brain boutique panel {shop['slug']} --applique {p['id']} "
                         f"--variante {p['gagnante']} [--le <date>]`")
    f = fiabilite(shop)
    if f:
        lines.append(f[0].upper() + f[1:])
    return lines


# ------------------------------------------------------------------------------------------------ bilan et liste
def _plan_state(shop, b, today):
    from . import dates
    late, soon, done, total = [], [], 0, 0
    for p in shop.get("plan") or []:
        n = b.nodes.get(p["id"])
        if not n or (n.get("meta") or {}).get("annule"):
            continue
        total += 1
        if n.get("status") != "active":
            done += 1
            continue
        k = dates.days_until(p.get("due"), today)
        if k is not None and k < 0:
            late.append((k, n))
        elif k is not None and k <= 7:
            soon.append((k, n))
    return sorted(late, key=lambda x: x[0]), sorted(soon, key=lambda x: x[0]), done, total


def bilan(ref, semaines=4, md=None, today=None) -> list:
    """Revue de la semaine, en Markdown (imprimée, et écrite dans un fichier avec md)."""
    from .store import Brain
    shop = find(ref)
    today = today or _dt.date.today()
    t = TYPES.get(shop.get("type") or "")
    out = [f"# Bilan — {shop['nom']} (au {today.strftime('%d/%m/%Y')})", ""]
    ident = [x for x in (shop.get("url"), shop.get("plateforme"),
                         {"0euro": "chemin 0 €", "plateforme": "chemin plateforme"}.get(shop.get("chemin") or ""),
                         t[0] if t else None) if x]
    if ident:
        out += [" · ".join(ident), ""]
    weeks = (shop.get("kpi") or [])[-max(1, int(semaines or 4)):]
    out.append("## Chiffres")
    if weeks:
        out += ["", "| Semaine | Sessions | Ajouts | Conversion | Commandes | CA | Panier moyen | Marge/h |",
                "|---|---|---|---|---|---|---|---|"]
        for k in weeks:
            r = rates(k, shop.get("marge_commande"))
            out.append(f"| {_day(k['semaine'])} | {_fr(k.get('sessions'))} | {_pct(r['ajout'])} | "
                       f"{_pct(r['conversion'], 2)} | {_fr(k.get('commandes'))} | {_eur(k.get('ca'))} | "
                       f"{_eur(r['panier_moyen'], 2)} | {_eur(r['marge_heure'], 2)} |")
        out += [""] + report(shop, weeks[-1])[1:]
    else:
        out.append(f"Aucun relevé : `brain boutique kpi {shop['slug']} --sessions … --ajouts … --commandes … --ca …` "
                   "(semaine complète, lundi-dimanche).")
    b = Brain.load()
    late, soon, done, total = _plan_state(shop, b, today)
    out += ["", "## Plan"]
    if total:
        out.append(f"{done}/{total} à-faire terminés.")
        out += [f"- ⚠️ en retard de {-k} j : {n['title']} `{n['id']}`" for k, n in late[:8]]
        out += [f"- ⏰ {'aujourd’hui' if k == 0 else f'dans {k} j'} : {n['title']} `{n['id']}`" for k, n in soon[:8]]
    else:
        out.append(f"Pas de plan daté : `brain boutique plan {shop['slug']}`.")
    audits = shop.get("audits") or []
    out += ["", "## Audits"]
    if audits:
        a = audits[-1]
        out.append(f"Dernier audit le {_day(a['date'])} ({a.get('url')}) : ✗ {a.get('x', 0)} · ⚠ {a.get('warn', 0)}"
                   + (f" (au premier audit, le {_day(audits[0]['date'])} : ✗ {audits[0].get('x', 0)} · "
                      f"⚠ {audits[0].get('warn', 0)})" if len(audits) > 1 else ""))
        out += [f"- {p}" for p in a.get("points", [])[:6]]
    else:
        out.append(f"Aucun audit : `brain boutique audit {shop['slug']}`.")
    sims = shop.get("panels") or []
    if sims:
        out += ["", "## Panels simulés"]
        for p in sims[-3:]:
            out.append(f"- {p['id']} ({_day(p['date'])}) {_panel_ligne(p)}")
            if p.get("applique"):
                out.append(f"  - {p['applique']} en ligne depuis le {_day(p['applique_le'])} : "
                           f"{verdict_panel(shop, p)[1]}")
        f = fiabilite(shop)
        if f:
            out.append(f[0].upper() + f[1:] + ".")
    prio = []
    if weeks:
        niveau, text = diagnostic(weeks[-1], shop)[0]
        prio.append(text[0].upper() + text[1:])
    if late:
        prio.append(f"Rattraper : {late[0][1]['title']}")
    if audits and audits[-1].get("x"):
        prio.append(f"Corriger les {audits[-1]['x']} point(s) ✗ du dernier audit")
    if soon:
        prio.append(f"Préparer : {soon[0][1]['title']}")
    if not weeks:
        prio.append("Relever la semaine passée (base de mesure)")
    out += ["", "## Trois priorités", ""] + [f"{i}. {p}" for i, p in enumerate(prio[:3], 1)]
    text = "\n".join(out).rstrip() + "\n"
    if md:
        write_text(md, text)
    return text.splitlines() + ([f"\n(écrit dans {md})"] if md else [])


def liste(today=None) -> list:
    from .store import Brain
    shops = all_shops()
    if not shops:
        return ["Aucune boutique suivie. `brain boutique ajouter \"Nom\" --url https://… [--type physique|mode|createur|"
                "occasion|niche|prevente|local|numerique|b2b] [--chemin plateforme|0euro] [--marge-commande 12,5]`"]
    today = today or _dt.date.today()
    b = Brain.load()
    lines = [f"🛒 Boutiques suivies ({len(shops)}) — détail : `brain boutique bilan <boutique>`"]
    for s in shops:
        bits = [x for x in (s.get("plateforme"), s.get("type")) if x]
        k = (s.get("kpi") or [])[-1:] or [None]
        if k[0]:
            r = rates(k[0], s.get("marge_commande"))
            bits.append(f"semaine du {_day(k[0]['semaine'])} : {_fr(k[0].get('commandes'))} commandes, "
                        f"conversion {_pct(r['conversion'], 2)}")
        else:
            bits.append("aucun relevé")
        late, soon, done, total = _plan_state(s, b, today)
        if total:
            bits.append(f"plan {done}/{total}" + (f", {len(late)} en retard" if late else ""))
        if s.get("audits"):
            a = s["audits"][-1]
            bits.append(f"audit du {_day(a['date'])} : ✗ {a.get('x', 0)} ⚠ {a.get('warn', 0)}")
        if s.get("panels"):
            bits.append(f"{len(s['panels'])} panel(s) simulé(s)")
        lines.append(f"- {s['nom']} `{s['slug']}` · " + " · ".join(bits))
    return lines

