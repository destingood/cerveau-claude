#!/usr/bin/env python3
"""Audit SEO/GEO express d'une page de boutique, en une commande et sans outil payant.

Lit la page comme un robot : titre, description, canonique, noindex, langue, Open Graph, titres H1, images sans
texte alternatif, données structurées (Product, Offer, livraison, retours, avis, Organization, fil d'Ariane), puis
le robots.txt (robots des moteurs et des assistants IA autorisés ou non, règles de la RFC 9309), le sitemap et
llms.txt. Ne mesure pas la vitesse réelle : pour les Core Web Vitals, PageSpeed Insights (lien donné).

Bibliothèque standard uniquement. Usage : python scripts/audit_site.py <url> [--json] [--timeout 20] [--ua "…"]"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

UA = "Mozilla/5.0 (compatible; cerveau-audit/2.0; audit SEO lancé par le propriétaire du site)"
MAX_BYTES = 4_000_000

# Robots à vérifier dans robots.txt : jeton, éditeur, rôle, faut-il l'autoriser pour être visible ? (documentation de
# chaque éditeur, vérifiée le 18/10/2026 ; module 07 du skill)
BOTS = [
    ("Googlebot", "Google", "Recherche Google, Aperçus IA, Mode IA", True),
    ("Bingbot", "Microsoft", "Recherche Bing et Copilot", True),
    ("OAI-SearchBot", "OpenAI", "Résultats de recherche de ChatGPT", True),
    ("ChatGPT-User", "OpenAI", "Pages ouvertes à la demande d'un utilisateur de ChatGPT", True),
    ("PerplexityBot", "Perplexity", "Index et réponses de Perplexity", True),
    ("Perplexity-User", "Perplexity", "Pages ouvertes à la demande d'un utilisateur", True),
    ("Claude-SearchBot", "Anthropic", "Recherche web de Claude", True),
    ("Claude-User", "Anthropic", "Pages ouvertes à la demande d'un utilisateur de Claude", True),
    ("Applebot", "Apple", "Siri, Spotlight, Safari", True),
    ("DuckAssistBot", "DuckDuckGo", "Réponses assistées de DuckDuckGo", True),
    ("facebookexternalhit", "Meta", "Aperçus des liens partagés (Facebook, Messenger, WhatsApp)", True),
    ("meta-externalagent", "Meta", "Meta AI : indexation des produits et entraînement", True),
    ("GPTBot", "OpenAI", "Entraînement des modèles (sans effet sur la recherche de ChatGPT)", False),
    ("ClaudeBot", "Anthropic", "Entraînement des modèles (sans effet sur la recherche de Claude)", False),
    ("Google-Extended", "Google", "Entraînement et ancrage de Gemini (sans effet sur la recherche Google)", False),
    ("Applebot-Extended", "Apple", "Refus de l'entraînement des modèles d'Apple", False),
    ("CCBot", "Common Crawl", "Corpus public réutilisé pour entraîner des modèles", False),
]


# ------------------------------------------------------------------------------------------------ réseau
def fetch(url: str, timeout: float = 20, ua: str = UA, limit: int = MAX_BYTES) -> dict:
    """GET sans exception : {status, url (finale), headers (clés en minuscules), body (texte), elapsed, error}."""
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "text/html,application/xhtml+xml,*/*",
                                               "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
                                               "Accept-Encoding": "identity"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(limit)
            status, final, headers = resp.status, resp.geturl(), resp.headers
    except urllib.error.HTTPError as exc:
        raw = exc.read(limit) if exc.fp else b""
        status, final, headers = exc.code, exc.geturl() or url, exc.headers
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return {"status": None, "url": url, "headers": {}, "body": "", "elapsed": time.time() - start,
                "error": str(reason)}
    charset = "utf-8"
    ctype = headers.get("Content-Type", "") if headers else ""
    m = re.search(r"charset=([\w.-]+)", ctype or "")
    if m:
        charset = m.group(1)
    try:
        body = raw.decode(charset, "replace")
    except LookupError:
        body = raw.decode("utf-8", "replace")
    return {"status": status, "url": final, "headers": {k.lower(): v for k, v in (headers or {}).items()},
            "body": body, "elapsed": time.time() - start, "error": None}


# ------------------------------------------------------------------------------------------------ HTML
class PageParser(HTMLParser):
    """Relève ce qui compte pour le référencement, sans exécuter le JavaScript (comme un premier passage de robot)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang = None
        self.title = None
        self.meta = {}
        self.canonical = []
        self.hreflang = []
        self.h1 = []
        self.images = 0
        self.images_no_alt = 0
        self.jsonld = []
        self.scripts = 0
        self.links = []
        self.itemtypes = []
        self._in = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html" and a.get("lang"):
            self.lang = a["lang"]
        elif tag == "title" and self.title is None:
            self._in, self._buf = "title", []
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key and key not in self.meta:
                self.meta[key] = a.get("content", "")
        elif tag == "link":
            rel = a.get("rel", "").lower().split()
            if "canonical" in rel:
                self.canonical.append(a.get("href", ""))
            if "alternate" in rel and a.get("hreflang"):
                self.hreflang.append(a["hreflang"])
        elif tag == "h1":
            self._in, self._buf = "h1", []
        elif tag == "img":
            self.images += 1
            if "alt" not in a:
                self.images_no_alt += 1
        elif tag == "script":
            if a.get("type", "").lower() == "application/ld+json":
                self._in, self._buf = "jsonld", []
            elif a.get("src"):
                self.scripts += 1
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if a.get("itemtype"):
            self.itemtypes.append(a["itemtype"])

    def handle_endtag(self, tag):
        if self._in == "title" and tag == "title":
            self.title = " ".join("".join(self._buf).split())
            self._in = None
        elif self._in == "h1" and tag == "h1":
            self.h1.append(" ".join("".join(self._buf).split()))
            self._in = None
        elif self._in == "jsonld" and tag == "script":
            self.jsonld.append("".join(self._buf))
            self._in = None

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)


def _types(obj) -> list:
    t = obj.get("@type") if isinstance(obj, dict) else None
    return [str(x) for x in t] if isinstance(t, list) else ([str(t)] if t else [])


def flatten_jsonld(blocks: list) -> tuple:
    """→ (objets typés trouvés, nombre de blocs illisibles). Parcourt @graph, les listes et les objets imbriqués."""
    found, broken = [], 0

    def walk(x):
        if isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            if _types(x):
                found.append(x)
            for k, v in x.items():
                if k != "@context":
                    walk(v)

    for raw in blocks:
        try:
            walk(json.loads(raw.strip().rstrip(";")))
        except ValueError:
            broken += 1
    return found, broken


def _as_list(v) -> list:
    return v if isinstance(v, list) else [v] if v else []


def first_offer(p: dict) -> dict:
    """Première offre d'un Product, ou de la première variante d'un ProductGroup (thèmes Shopify à variantes)."""
    for cand in [p] + [v for v in _as_list(p.get("hasVariant")) if isinstance(v, dict)]:
        offers = [o for o in _as_list(cand.get("offers")) if isinstance(o, dict)]
        if offers:
            return offers[0]
    return {}


def check_product(p: dict) -> list:
    """Champs manquants d'un Product (ou ProductGroup) pour les fiches marchandes de Google et les assistants IA.
    Livraison et retours sont traités à part : ils se déclarent de préférence dans la Search Console ou Merchant
    Center, voire au niveau de l'Organization (module 06)."""
    variants = [v for v in _as_list(p.get("hasVariant")) if isinstance(v, dict)]
    missing = [k for k in ("name", "image", "description") if not p.get(k)]
    ids = ("sku", "gtin", "gtin8", "gtin12", "gtin13", "gtin14", "mpn")
    if not any(c.get(k) for c in [p] + variants for k in ids):
        missing.append("sku/gtin/mpn")
    if not p.get("brand"):
        missing.append("brand")
    o = first_offer(p)
    if not o:
        return missing + ["offers"]
    if not (o.get("price") or o.get("lowPrice") or (o.get("priceSpecification") or {}).get("price")):
        missing.append("offers.price")
    if not (o.get("priceCurrency") or (o.get("priceSpecification") or {}).get("priceCurrency")):
        missing.append("offers.priceCurrency")
    if not o.get("availability"):
        missing.append("offers.availability")
    return missing


# ------------------------------------------------------------------------------------------------ robots.txt
def parse_robots(text: str) -> list:
    """Groupes de robots.txt : [{agents: [...], rules: [(allow?, motif)]}] (RFC 9309)."""
    groups, cur, last_was_agent = [], None, False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, val = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if cur is None or not last_was_agent:
                cur = {"agents": [], "rules": []}
                groups.append(cur)
            cur["agents"].append(val.lower())
            last_was_agent = True
        elif key in ("allow", "disallow"):
            if cur is not None and val:
                cur["rules"].append((key == "allow", val))
            last_was_agent = False
        elif key != "sitemap":  # Sitemap est hors groupe ; toute autre ligne (Crawl-delay…) clôt la liste des robots
            last_was_agent = False
    return groups


def _pattern(motif: str):
    rx = "".join(".*" if c == "*" else re.escape(c) for c in motif.rstrip("$"))
    return re.compile(rx + ("$" if motif.endswith("$") else ""))


def allowed(groups: list, token: str, path: str) -> tuple:
    """(autorisé ?, groupe utilisé : le jeton du robot, « * » ou aucun) — règle la plus longue, Allow en cas d'égalité."""
    tok = token.lower()
    mine = [g for g in groups if any(a == tok or a.startswith(tok + "/") for a in g["agents"])]
    used = token if mine else None
    if not mine:
        mine = [g for g in groups if "*" in g["agents"]]
        used = "*" if mine else None
    if path == "/robots.txt" or not mine:
        return True, used
    best = None
    for g in mine:
        for allow, motif in g["rules"]:
            if _pattern(motif).match(path):
                key = (len(motif), allow)
                if best is None or key > best:
                    best = key
    return (True if best is None else best[1]), used


# ------------------------------------------------------------------------------------------------ audit
def audit(url: str, timeout: float = 20, ua: str = UA) -> dict:
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    page = fetch(url, timeout, ua)
    rep = {"url": url, "url_finale": page["url"], "statut": page["status"], "erreur": page["error"],
           "duree_s": round(page["elapsed"], 2), "points": []}

    def point(niveau, sujet, constat, conseil="", module=""):
        rep["points"].append({"niveau": niveau, "sujet": sujet, "constat": constat, "conseil": conseil,
                              "module": module})

    if page["error"] or not page["status"]:
        point("✗", "Accès", f"page injoignable : {page['error']}", "vérifier l'adresse, le DNS, le pare-feu", "01")
        return rep
    if page["status"] >= 400:
        point("✗", "Accès", f"code HTTP {page['status']}", "une page en erreur ne peut pas être indexée", "06")
    final = urllib.parse.urlsplit(page["url"])
    root = f"{final.scheme}://{final.netloc}"
    html, headers = page["body"], page["headers"]
    rep["octets_html"] = len(html.encode("utf-8"))
    if final.scheme != "https":
        point("✗", "HTTPS", "la page n'est pas servie en HTTPS", "activer le certificat (gratuit sur toutes les "
              "plateformes)", "03")

    plateforme = ("Shopify" if ("cdn.shopify.com" in html or "Shopify.theme" in html) else
                  "WooCommerce" if "woocommerce" in html.lower() else
                  "PrestaShop" if "prestashop" in html.lower() else
                  "Wix" if "wix.com" in html.lower() or "wixstatic" in html.lower() else None)
    rep["plateforme"] = plateforme

    p = PageParser()
    try:
        p.feed(html)
    except Exception as exc:  # HTML très abîmé : on garde ce qui a été lu
        point("⚠", "HTML", f"lecture partielle du HTML ({exc!r})")
    meta = p.meta

    # Indexabilité
    robots_meta = (meta.get("robots", "") + " " + meta.get("googlebot", "")).lower()
    x_robots = headers.get("x-robots-tag", "").lower()
    if "noindex" in robots_meta or "noindex" in x_robots:
        point("✗", "Indexation", "la page demande à ne pas être indexée (noindex)",
              "retirer noindex si la page doit être trouvée", "06")
    else:
        point("✓", "Indexation", "pas de noindex")
    if p.canonical:
        canon = urllib.parse.urljoin(page["url"], p.canonical[0])
        same = canon.rstrip("/") == page["url"].split("#")[0].split("?")[0].rstrip("/")
        point("✓" if same else "⚠", "Canonique", canon if same else f"pointe ailleurs : {canon}",
              "" if same else "normal pour une variante ou une URL de collection ; sinon corriger", "06")
        if len(p.canonical) > 1:
            point("⚠", "Canonique", f"{len(p.canonical)} balises canonical", "n'en garder qu'une", "06")
    else:
        point("⚠", "Canonique", "absente", "ajouter <link rel=\"canonical\">", "06")

    # Titre, description, langue, titres
    t = p.title or ""
    if not t:
        point("✗", "Title", "absent", "un titre unique de 50 à 60 caractères environ", "06")
    else:
        point("✓" if 25 <= len(t) <= 65 else "⚠", "Title", f"{len(t)} caractères : « {t[:90]} »",
              "" if 25 <= len(t) <= 65 else "viser 50 à 60 caractères : produit + attribut clé + bénéfice", "06")
    d = meta.get("description", "")
    if not d:
        point("⚠", "Meta description", "absente", "environ 150 caractères : bénéfice + preuve + livraison/retours",
              "06")
    else:
        point("✓" if 70 <= len(d) <= 170 else "⚠", "Meta description", f"{len(d)} caractères",
              "" if 70 <= len(d) <= 170 else "viser environ 150 caractères", "06")
    point("✓" if p.lang else "⚠", "Langue", f"lang=\"{p.lang}\"" if p.lang else "attribut lang absent",
          "" if p.lang else "ajouter lang=\"fr\" sur <html>", "06")
    if p.hreflang:
        point("✓", "International", f"hreflang : {', '.join(sorted(set(p.hreflang)))[:120]}")
    if meta.get("viewport"):
        point("✓", "Mobile", "balise viewport présente")
    else:
        point("✗", "Mobile", "pas de balise viewport", "la page s'affichera mal sur mobile", "03")
    h1 = [h for h in p.h1 if h]
    if len(h1) == 1:
        point("✓", "H1", f"« {h1[0][:90]} »")
    else:
        point("⚠", "H1", f"{len(h1)} titre(s) H1", "un seul H1 clair : le nom du produit ou de la collection", "06")
    if p.images:
        manque = p.images_no_alt
        point("✓" if manque == 0 else "⚠", "Images", f"{p.images} image(s), {manque} sans attribut alt",
              "" if manque == 0 else "décrire fidèlement chaque image utile (alt)", "06")
    og = [k for k in ("og:title", "og:description", "og:image") if meta.get(k)]
    point("✓" if len(og) == 3 else "⚠", "Partage social", f"Open Graph : {', '.join(og) or 'aucune balise'}",
          "" if len(og) == 3 else "og:title, og:description, og:image pour de beaux aperçus en message privé", "05")

    # Données structurées
    objs, broken = flatten_jsonld(p.jsonld)
    types = sorted({x for o in objs for x in _types(o)})
    rep["types_jsonld"] = types
    if broken:
        point("✗", "Données structurées", f"{broken} bloc(s) JSON-LD illisible(s)",
              "corriger la syntaxe (test des résultats enrichis de Google)", "06")
    if not objs and not p.itemtypes:
        point("⚠", "Données structurées", "aucune (ni JSON-LD ni microdonnées)",
              "Product + Offer sur les fiches produit, Organization sur l'accueil", "06")
    elif types:
        point("✓", "Données structurées", "types : " + ", ".join(types))
    in_group = {id(v) for o in objs if "ProductGroup" in _types(o) for v in _as_list(o.get("hasVariant"))}
    products = [o for o in objs if ("Product" in _types(o) or "ProductGroup" in _types(o)) and id(o) not in in_group]
    for prod in products[:3]:
        missing = check_product(prod)
        name = str(prod.get("name") or "?")[:60]
        if missing:
            point("⚠", "Product", f"« {name} » : manque {', '.join(missing)}",
                  "compléter : utile aux fiches marchandes Google, aux fiches gratuites et aux assistants IA", "06")
        else:
            point("✓", "Product", f"« {name} » : champs essentiels présents")
    if products and not any("AggregateRating" in _types(o) or "Review" in _types(o) for o in objs):
        point("·", "Avis", "pas de note ni d'avis balisés", "seulement s'il existe de vrais avis visibles sur la page",
              "08")
    orgs = [o for o in objs if set(_types(o)) & {"Organization", "OnlineStore", "Store", "LocalBusiness", "Corporation"}]
    if products:
        offers = [first_offer(x) for x in products]
        ship = any(o.get("shippingDetails") for o in offers) or any(g.get("hasShippingService") for g in orgs)
        ret = (any(o.get("hasMerchantReturnPolicy") for o in offers)
               or any(g.get("hasMerchantReturnPolicy") for g in orgs))
        manque = [x for x, ok in (("livraison", ship), ("retours", ret)) if not ok]
        point("✓" if not manque else "·", "Livraison et retours",
              "balisés" if not manque else f"non balisés : {', '.join(manque)}",
              "" if not manque else "les déclarer dans la Search Console (Paramètres › Shopping) ou Merchant Center, "
              "qui priment sur le balisage ; sinon hasShippingService et hasMerchantReturnPolicy sur l'Organization",
              "06")
    if orgs:
        same_as = orgs[0].get("sameAs")
        point("✓" if same_as else "⚠", "Entité", "Organization" + (" avec sameAs" if same_as else " sans sameAs"),
              "" if same_as else "ajouter sameAs (réseaux, marketplaces) : même identité partout", "07")
    if "FAQPage" in types:
        point("·", "FAQ", "balisage FAQPage présent",
              "inoffensif, mais Google n'affiche plus de résultats enrichis FAQ depuis mai 2026 : la FAQ visible sert "
              "les visiteurs et les assistants IA, pas le balisage", "06")

    # robots.txt, sitemap, llms.txt
    parts = urllib.parse.urlsplit(page["url"])
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    rob = fetch(root + "/robots.txt", timeout, ua)
    rep["robots"] = {"statut": rob["status"]}
    sitemaps = []
    if rob["status"] and rob["status"] < 400:
        groups = parse_robots(rob["body"])
        sitemaps = re.findall(r"(?im)^\s*sitemap\s*:\s*(\S+)", rob["body"])
        verdicts = []
        for token, editeur, role, visible in BOTS:
            ok, used = allowed(groups, token, path)
            verdicts.append({"robot": token, "editeur": editeur, "role": role, "autorise": ok, "groupe": used,
                             "pour_la_visibilite": visible})
        rep["robots"]["robots"] = verdicts
        bloques = [v["robot"] for v in verdicts if v["pour_la_visibilite"] and not v["autorise"]]
        if bloques:
            point("✗", "Robots (moteurs et IA)", "bloqués sur cette page : " + ", ".join(bloques),
                  "les autoriser dans robots.txt pour être trouvé et cité (sur Shopify : robots.txt.liquid)", "07")
        else:
            point("✓", "Robots (moteurs et IA)", "moteurs et robots de recherche IA autorisés sur cette page")
        train = [v["robot"] for v in verdicts if not v["pour_la_visibilite"] and not v["autorise"]]
        if train:
            point("·", "Robots d'entraînement", "bloqués : " + ", ".join(train),
                  "choix possible : sans effet sur la recherche de ChatGPT ni sur Google", "07")
    elif rob["status"] and rob["status"] < 500:
        point("·", "robots.txt", f"absent (HTTP {rob['status']}) : tout est permis aux robots",
              "ajouter un robots.txt avec la ligne Sitemap", "06")
    else:
        point("✗", "robots.txt", f"injoignable ({rob['status'] or rob['error']}) : les robots peuvent s'abstenir de "
              "tout explorer", "corriger l'erreur serveur", "06")
    if plateforme != "Shopify" and ("cf-ray" in headers or "cloudflare" in headers.get("server", "").lower()):
        point("⚠", "Cloudflare", "site derrière Cloudflare",
              "vérifier dans le tableau de bord Cloudflare que les robots de recherche IA ne sont pas bloqués (blocage "
              "proposé par défaut depuis juillet 2025) : robots.txt ne suffit pas si le pare-feu les refuse", "07")
    sm_url = sitemaps[0] if sitemaps else root + "/sitemap.xml"
    sm = fetch(sm_url, timeout, ua)
    ok_sm = bool(sm["status"] and sm["status"] < 400 and "<" in sm["body"][:500])
    rep["sitemap"] = {"url": sm_url, "statut": sm["status"], "dans_robots": bool(sitemaps)}
    point("✓" if ok_sm else "✗", "Sitemap", f"{sm_url} (HTTP {sm['status']})" + ("" if sitemaps else
          " — non déclaré dans robots.txt"), "" if ok_sm else "générer un sitemap et le soumettre à la Search Console "
          "et à Bing Webmaster Tools", "06")
    llms = fetch(root + "/llms.txt", timeout, ua)
    rep["llms_txt"] = bool(llms["status"] and llms["status"] < 400)
    point("·", "llms.txt", "présent" if rep["llms_txt"] else "absent",
          "optionnel : aucun grand moteur n'a confirmé s'en servir", "07")

    rep["scripts_externes"] = p.scripts
    if p.scripts > 30:
        point("⚠", "Poids", f"{p.scripts} scripts externes", "chaque app ajoute du JavaScript : retirer l'inutile",
              "03")
    rep["pagespeed"] = "https://pagespeed.web.dev/analysis?url=" + urllib.parse.quote(page["url"], safe="")
    rep["test_resultats_enrichis"] = ("https://search.google.com/test/rich-results?url="
                                      + urllib.parse.quote(page["url"], safe=""))
    return rep


def texte(rep: dict) -> str:
    out = [f"Audit SEO/GEO express — {rep['url_finale']}"]
    if rep.get("statut"):
        out.append(f"HTTP {rep['statut']} · {rep.get('octets_html', 0) // 1024} Ko de HTML · {rep['duree_s']} s"
                   + (f" · plateforme : {rep['plateforme']}" if rep.get("plateforme") else ""))
    out.append("")
    for niveau in ("✗", "⚠", "✓", "·"):
        for pt in (x for x in rep["points"] if x["niveau"] == niveau):
            ligne = f"{pt['niveau']} {pt['sujet']} : {pt['constat']}"
            if pt["conseil"] and niveau != "✓":
                ligne += f"\n    → {pt['conseil']}" + (f" (module {pt['module']})" if pt["module"] else "")
            out.append(ligne)
    if rep.get("robots", {}).get("robots"):
        out.append("\nRobots (robots.txt, cette page) :")
        for v in rep["robots"]["robots"]:
            out.append(f"  {'✓' if v['autorise'] else '✗'} {v['robot']:<18} {v['role']}")
    if rep.get("pagespeed"):
        out.append(f"\nVitesse réelle (Core Web Vitals, mobile) : {rep['pagespeed']}")
        out.append(f"Test des résultats enrichis : {rep['test_resultats_enrichis']}")
    out.append("\nLimites : lecture sans JavaScript (comme un premier passage de robot) ; un contenu injecté par un "
               "script n'est pas vu ici.")
    return "\n".join(out)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "--aide"):
        print(__doc__)
        return 0 if args else 1
    as_json, timeout, ua, urls = False, 20.0, UA, []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            as_json = True
        elif a in ("--timeout", "--ua") and i + 1 < len(args):
            if a == "--timeout":
                try:
                    timeout = float(args[i + 1].replace(",", "."))
                except ValueError:
                    print(f"Erreur : --timeout attend un nombre de secondes, pas « {args[i + 1]} »", file=sys.stderr)
                    return 1
            else:
                ua = args[i + 1]
            i += 1
        elif a.startswith("--"):
            print(f"Erreur : option inconnue {a}", file=sys.stderr)
            return 1
        else:
            urls.append(a)
        i += 1
    if len(urls) != 1:
        print("Erreur : donne une seule adresse à auditer (python scripts/audit_site.py <url>)", file=sys.stderr)
        return 1
    rep = audit(urls[0], timeout, ua)
    print(json.dumps(rep, ensure_ascii=False, indent=2) if as_json else texte(rep))
    return 0 if rep.get("statut") and rep["statut"] < 400 else 2


if __name__ == "__main__":
    sys.exit(main())
