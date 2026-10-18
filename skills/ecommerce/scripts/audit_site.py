#!/usr/bin/env python3
"""Audit SEO/GEO express d'une page de boutique, en une commande et sans outil payant.

Lit la page comme un robot : titre, description, canonique, noindex, langue, Open Graph, titres H1, images sans
texte alternatif, données structurées (Product, Offer, livraison, retours, avis, Organization, fil d'Ariane), puis
le robots.txt (robots des moteurs et des assistants IA autorisés ou non, règles de la RFC 9309), le sitemap et
llms.txt.

Options :
  --conformite   pages légales (mentions, CGV, retours, confidentialité, contact) lues et contrôlées : rétractation de
                 14 jours et formulaire, fonction « renoncer au contrat ici », garanties légales, médiateur, lien
                 périmé vers la plateforme européenne de litiges, identité et hébergeur, traceurs sans bandeau de
                 consentement, minuteurs d'urgence, avis sans information sur leur contrôle, allégations à risque
  --pages N      N pages du sitemap lues (produits, collections, pages) : erreurs, redirections, noindex, titres et
                 descriptions absents ou en double, H1, fiches produit sans données Product
  --vitesse      Core Web Vitals via l'API PageSpeed Insights (mobile) : visiteurs réels (28 jours) et mesure de
                 laboratoire, avec les 3 gains les plus importants ; clé facultative dans PAGESPEED_API_KEY
  --complet      les trois à la fois (--conformite --pages 10 --vitesse)
  --rapport f.md rapport Markdown prêt à envoyer (au client ou à soi-même)
  --pause S      pause entre deux pages lues (défaut 1 s, par politesse envers le serveur)

Bibliothèque standard uniquement. Usage : python scripts/audit_site.py <url> [--conformite] [--pages N] [--vitesse]
[--complet] [--rapport fichier.md] [--json] [--timeout 20] [--ua "…"]"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

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
        self.anchors = []  # (adresse, texte du lien)
        self.buttons = []
        self.script_srcs = []
        self.itemtypes = []
        self._in = None
        self._buf = []
        self._a = None
        self._btn = None

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
                self.script_srcs.append(a["src"])
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
            self._a = (a["href"], [a.get("title", ""), a.get("aria-label", "")])
        elif tag == "button":
            self._btn = [a.get("aria-label", "")]
        elif tag == "input" and a.get("type", "").lower() in ("submit", "button") and a.get("value"):
            self.buttons.append(a["value"])
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
        if tag == "a" and self._a:
            self.anchors.append((self._a[0], " ".join(" ".join(self._a[1]).split())))
            self._a = None
        elif tag == "button" and self._btn is not None:
            self.buttons.append(" ".join(" ".join(self._btn).split()))
            self._btn = None

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)
        if self._a:
            self._a[1].append(data)
        if self._btn is not None:
            self._btn.append(data)


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
def audit(url: str, timeout: float = 20, ua: str = UA, legal: bool = False, pages: int = 0, vitesse: bool = False,
          pause: float = 1.0) -> dict:
    """Audit d'une page ; legal : pages légales et conformité, pages : nombre de pages du sitemap à lire,
    vitesse : Core Web Vitals via PageSpeed Insights."""
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
    sitemaps, groups = [], None
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
    if legal:
        conformite(rep, point, html, p, page["url"], root, plateforme, timeout, ua)
    if pages:
        explorer(rep, point, root, page["url"], sitemaps, groups, pages, timeout, ua, pause)
    if vitesse:
        rep["vitesse"] = mesurer_vitesse(page["url"], timeout, ua)
        points_vitesse(point, rep["vitesse"], rep["pagespeed"])
    return rep


# ------------------------------------------------------------------------------------------------ texte visible
def visible(html_text: str) -> str:
    """Texte lisible d'une page (sans scripts, styles ni balises), une ligne par bloc."""
    t = re.sub(r"(?is)<(script|style|noscript|template|svg)\b.*?</\1>", " ", html_text or "")
    t = re.sub(r"(?i)<br\s*/?>|</(?:p|div|li|h[1-6]|tr|td|section|footer|header|nav)>", "\n", t)
    t = unescape(re.sub(r"<[^>]+>", " ", t))
    return "\n".join(" ".join(x.split()) for x in t.splitlines() if x.strip())


def _relire():
    """relire_texte.py, rangé à côté de ce script (allégations à risque)."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import relire_texte
    return relire_texte


def _court(u: str) -> str:
    parts = urllib.parse.urlsplit(u or "")
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return path if len(path) <= 60 else path[:57] + "…"


def _sans_query(u: str) -> str:
    return (u or "").split("#")[0].split("?")[0].rstrip("/")


# ------------------------------------------------------------------------------------------------ conformité
# Pages légales : clé, libellé, motif du texte du lien, motif de l'adresse, page standard de Shopify
LEGAL = [
    ("mentions", "Mentions légales", r"mentions? l[ée]gales?|legal notice|impressum|informations? l[ée]gales?",
     r"mentions|legal", "/policies/legal-notice"),
    ("cgv", "Conditions générales de vente", r"\bcgv\b|conditions? g[ée]n[ée]rales?|terms of (?:service|sale)",
     r"cgv|conditions-generales|terms-of-(?:service|sale)", "/policies/terms-of-service"),
    ("retours", "Retours et remboursements", r"rembours|r[ée]tractation|refund|politique de retours?|^retours?$|"
     r"retours? (?:et|&|/)|retours? (?:gratuits?|produits?)", r"refund|retours?|rembours|retractation",
     "/policies/refund-policy"),
    ("confidentialite", "Politique de confidentialité", r"confidentialit|privacy|donn[ée]es personnelles|\brgpd\b",
     r"confidentialite|privacy|donnees-personnelles|rgpd", "/policies/privacy-policy"),
    ("livraison", "Livraison", r"livraisons?\b|exp[ée]ditions?\b|shipping", r"livraison|expedition|shipping",
     "/policies/shipping-policy"),
    ("contact", "Contact", r"^contact|nous contacter|contactez|nous [ée]crire|service client", r"/contact",
     "/policies/contact-information"),
]
PAGE_LEGALE = {  # niveau si la page manque, ce qu'elle doit contenir
    "mentions": ("✗", "obligatoires : identité, immatriculation, coordonnées, hébergeur (LCEN, art. 1-1 et 19)"),
    "cgv": ("✗", "obligatoires pour vendre aux particuliers : prix, livraison, paiement, rétractation, garanties, "
                 "médiateur (C. conso., L111-1 et L221-5)"),
    "confidentialite": ("⚠", "dès qu'on collecte des données : finalités, durées, droits, contact (RGPD, art. 13)"),
    "retours": ("⚠", "délai de rétractation, frais de retour, remboursement sous 14 jours (C. conso., L221-18 et "
                     "L221-24)"),
    "livraison": ("·", "délais et frais de livraison connus avant la commande (C. conso., L111-1 et L216-1)"),
    "contact": ("⚠", "adresse postale, e-mail et téléphone (C. conso., R111-1 ; LCEN, art. 19)"),
}
TRACEURS = [
    ("Google Analytics / Ads", r"googletagmanager\.com/gtag/js|google-analytics\.com/(?:analytics|g/collect)"),
    ("Google Tag Manager", r"googletagmanager\.com/gtm\.js"),
    ("Meta Pixel", r"connect\.facebook\.net/[^\"']*fbevents\.js|fbq\(\s*['\"]init"),
    ("TikTok Pixel", r"analytics\.tiktok\.com"),
    ("Pinterest Tag", r"s\.pinimg\.com/ct/|pintrk\("),
    ("Snap Pixel", r"sc-static\.net/scevent"),
    ("Microsoft Clarity / UET", r"clarity\.ms/tag|bat\.bing\.com"),
    ("Hotjar", r"static\.hotjar\.com"),
]
CMP = (r"axeptio|didomi|cookiebot|onetrust|tarteaucitron|iubenda|complianz|cookieyes|usercentrics|sirdata|"
       r"consentmanager|termly|cookie-script|klaro|orejime|quantcast|pandectes|consentmo|privacy-banner|"
       r"customerprivacy|consent-tracking-api|cookie-?banner|cookie-?consent|gdpr-?cookie")
URGENCE = (r"countdown|count-down|hurrify|compte[- ]à[- ]rebours|plus que \d+ (?:en stock|articles?|pièces?|exemplaires?)|"
           r"\d+ personnes? (?:regardent|consultent)|offre (?:expire|se termine) dans")
AVIS = (r"judge\.me|judgeme|loox\.io|yotpo|stamped\.io|okendo|trustpilot|avis-verifies|skeepers|reviews\.io|ekomi|"
        r"trustedshops|ryviu|growave")
AVIS_CONTROLE = (r"avis (?:v[ée]rifi|contr[ôo]l)|contr[ôo]le des avis|proc[ée]dure de contr[ôo]le|non v[ée]rifi|"
                 r"(?:ne font|ne sont) pas l['’]objet d['’]un contr[ôo]le")


def pages_legales(p: PageParser, page_url: str, root: str, plateforme) -> dict:
    """Liens vers les pages légales repérés sur la page ; sur Shopify, pages standard en secours."""
    host = urllib.parse.urlsplit(root).netloc.lower()
    found = {}
    for key, _, rx_text, rx_href, std in LEGAL:
        for href, txt in p.anchors:
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            absu = urllib.parse.urljoin(page_url, href)
            parts = urllib.parse.urlsplit(absu)
            if parts.netloc.lower() != host or parts.path in ("", "/"):
                continue
            if re.search(r"accueil|haut de (?:la )?page|retour (?:à|au|aux|en arrière)\b|back to", txt, re.I):
                continue
            if re.search(rx_text, txt, re.I) or re.search(rx_href, urllib.parse.unquote(parts.path).lower()):
                found[key] = {"url": absu.split("#")[0], "lien": True}
                break
        if key not in found and plateforme == "Shopify":
            found[key] = {"url": root + std, "lien": False}
    return found


def conformite(rep: dict, point, html_text: str, p: PageParser, page_url: str, root: str, plateforme,
               timeout: float, ua: str) -> None:
    """Points de conformité (module 10 du skill) : pages légales et leur contenu, cookies, urgence, avis, allégations."""
    found = pages_legales(p, page_url, root, plateforme)
    textes, bruts = {}, {}
    lus = {}
    for key, info in found.items():
        if info["url"] not in lus:
            lus[info["url"]] = fetch(info["url"], timeout, ua)
        r = lus[info["url"]]
        info["statut"] = r["status"]
        if r["status"] and r["status"] < 400 and not r["error"]:
            bruts[key], textes[key] = r["body"], visible(r["body"])
    rep["conformite"] = found
    labels = {k: lbl for k, lbl, *_ in LEGAL}
    for key, (niveau, contenu) in PAGE_LEGALE.items():
        info = found.get(key)
        sujet = f"Conformité : {labels[key].lower()}" if key != "mentions" else "Conformité : mentions légales"
        if key in textes and info["lien"]:
            point("✓", sujet, _court(info["url"]))
        elif key in textes:
            point("⚠", sujet, f"page présente ({_court(info['url'])}) mais aucun lien repéré sur la page auditée",
                  "lien visible sur toutes les pages (pied de page)", "10")
        else:
            point(niveau, sujet, "page introuvable" + (f" ({_court(info['url'])} : HTTP {info.get('statut')})"
                                                       if info and info["lien"] else " (aucun lien repéré)"),
                  contenu, "10")

    page_txt = visible(html_text)
    tout = "\n".join([page_txt] + list(textes.values()))
    juridique = "\n".join(textes.get(k, "") for k in ("cgv", "retours"))
    if juridique.strip():
        ok14 = re.search(r"r[ée]tractation", juridique, re.I) and re.search(r"\b14\b|quatorze", juridique, re.I)
        point("✓" if ok14 else "✗", "Conformité : délai de rétractation",
              "14 jours indiqués" if ok14 else "délai de rétractation de 14 jours introuvable (CGV, page retours)",
              "" if ok14 else "« Vous disposez de 14 jours… » avec les exceptions (C. conso., L221-18 et L221-28)", "10")
        form = re.search(r"formulaire (?:type |standard )?de r[ée]tractation|mod[eè]le de formulaire", juridique, re.I)
        point("✓" if form else "⚠", "Conformité : formulaire de rétractation",
              "présent" if form else "formulaire type de rétractation introuvable",
              "" if form else "le joindre aux CGV (C. conso., L221-5 ; modèle en annexe de l'art. R221-1)", "10")
        glc = re.search(r"garantie l[ée]gale de conformit[ée]", juridique, re.I)
        point("✓" if glc else "✗", "Conformité : garantie légale de conformité",
              "mentionnée" if glc else "introuvable dans les CGV",
              "" if glc else "2 ans, réparation ou remplacement, encadré type (C. conso., L217-3 et suivants, D211-2)",
              "10")
        if not re.search(r"vices? cach[ée]s|\b1641\b", juridique, re.I):
            point("⚠", "Conformité : garantie des vices cachés", "non mentionnée",
                  "la citer dans les CGV (C. civ., art. 1641 et suivants)", "10")
    med = re.search(r"m[ée]diat(?:eur|ion)", tout, re.I)
    point("✓" if med else "✗", "Conformité : médiateur de la consommation",
          "mentionné" if med else "introuvable sur les pages lues",
          "" if med else "adhérer à un médiateur, afficher ses coordonnées et son site (C. conso., L612-1 et L616-1 ; "
          "amende jusqu'à 3 000 € pour une personne physique)", "10")
    if re.search(r"ec\.europa\.eu/(?:consumers/)?odr", html_text + "".join(bruts.values()), re.I):
        point("⚠", "Conformité : plateforme européenne de litiges", "lien présent",
              "plateforme fermée le 20/07/2025 (règlement (UE) 2024/3228) : retirer le lien", "10")
    if "mentions" in textes:
        ment = textes["mentions"]
        ident = re.search(r"\bsire[nt]\b|\brcs\b|\brne\b|registre national des entreprises|\b\d{3} ?\d{3} ?\d{3}\b",
                          ment, re.I)
        point("✓" if ident else "✗", "Conformité : identité de l'entreprise",
              "immatriculation indiquée" if ident else "SIREN ou immatriculation introuvable dans les mentions légales",
              "" if ident else "nom, forme, adresse, SIREN (LCEN, art. 1-1)", "10")
        if not re.search(r"h[ée]berg", ment, re.I):
            point("⚠", "Conformité : hébergeur", "absent des mentions légales",
                  "nom, adresse et téléphone de l'hébergeur (LCEN, art. 1-1)", "10")
    coord_txt = "\n".join(textes.get(k, "") for k in ("contact", "mentions", "cgv")) + "\n" + page_txt
    coord_raw = "".join(bruts.get(k, "") for k in ("contact", "mentions", "cgv")) + html_text
    manque = []
    if not (re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", coord_txt)
            or re.search(r"data-cfemail|email-protection|mailto:", coord_raw, re.I)):
        manque.append("e-mail")
    if not re.search(r"(?:\+33\s?|\b0)[1-9](?:[\s.-]?\d{2}){4}\b|tel:", coord_txt + coord_raw, re.I):
        manque.append("téléphone")
    if manque:
        point("⚠", "Conformité : coordonnées", f"introuvable(s) : {', '.join(manque)}",
              "un formulaire ne suffit pas : e-mail et téléphone joignables (C. conso., R111-1 ; LCEN, art. 19)", "10")
    libelles = " | ".join([t for _, t in p.anchors] + p.buttons)
    renonce = (re.search(r"renoncer au contrat", libelles + "\n" + tout, re.I)
               or re.search(r"(?:me |se |vous )?r[ée]tracter (?:du|de mon|de votre) contrat|r[ée]tractation en ligne",
                            libelles, re.I))
    point("✓" if renonce else "⚠", "Conformité : fonction de rétractation en ligne",
          "« renoncer au contrat » repéré" if renonce else "introuvable sur les pages lues",
          "" if renonce else "depuis le 19/06/2026 : fonction « renoncer au contrat ici » (ou formule analogue) "
          "accessible facilement pendant tout le délai (pied de page, espace client) : nom, prénom, contrat, e-mail, "
          "bouton « confirmer la rétractation », accusé de réception daté (C. conso., L221-21 et D221-5) — vérifier "
          "dans le navigateur si elle est chargée par un script", "10")
    vus = [nom for nom, rx in TRACEURS if re.search(rx, html_text, re.I)]
    cmp = re.search(CMP, html_text, re.I)
    if vus and not cmp:
        point("⚠", "Conformité : cookies", f"traceurs repérés ({', '.join(vus)}) sans bandeau de consentement dans le "
              "HTML", "aucun traceur publicitaire avant le choix du visiteur ; « Tout refuser » aussi simple que "
              "« Tout accepter » (CNIL ; loi Informatique et Libertés, art. 82) — le bandeau peut venir d'un script : "
              "vérifier dans le navigateur", "10")
    elif vus:
        point("✓", "Conformité : cookies", f"bandeau de consentement repéré ({cmp.group(0)}) ; traceurs : "
              f"{', '.join(vus)}")
    else:
        point("✓", "Conformité : cookies", "aucun traceur publicitaire dans le HTML (ceux chargés par script ou par "
              "les « web pixels » de Shopify ne sont pas vus ici)")
    urg = re.search(URGENCE, html_text, re.I)
    if urg:
        point("⚠", "Conformité : urgence affichée", f"« {urg.group(0)} » repéré",
              "légal seulement si c'est vrai : l'offre s'arrête à l'heure dite, stock et visiteurs affichés réels "
              "(pratiques commerciales trompeuses : C. conso., L121-4, 7° ; faux stock : L121-2)", "10")
    avis = re.search(AVIS, html_text, re.I)
    if avis and not re.search(AVIS_CONTROLE, tout, re.I):
        point("⚠", "Conformité : avis clients", f"widget d'avis repéré ({avis.group(0)}) sans information sur leur "
              "contrôle", "dire près des avis s'ils sont contrôlés et comment, avec leurs dates (C. conso., L111-7-2 "
              "et D111-17 ; L121-4, 27°) — vérifier dans le navigateur si le widget l'affiche", "10")
    try:
        rel = _relire().relire(page_txt, "page")
    except Exception:  # relire_texte.py absent ou abîmé : le reste de l'audit tient
        rel = {"points": []}
    rouges = {}
    for f in rel["points"]:
        if f["niveau"] == "🔴":
            rouges.setdefault(f["sujet"], {"conseil": f["conseil"], "extraits": []})["extraits"].append(f["extrait"])
    for sujet, info in list(rouges.items())[:3]:
        extraits = sorted({e.lower() for e in info["extraits"]})
        point("✗", f"Conformité : {sujet[0].lower() + sujet[1:]}", "« " + " », « ".join(extraits[:4]) + " »",
              info["conseil"], "10")


# ------------------------------------------------------------------------------------------------ pages du sitemap
def lire_sitemaps(depart: list, timeout: float = 20, ua: str = UA, maxi: int = 5000) -> tuple:
    """Adresses des sitemaps (index compris, 12 fichiers au plus). → ([(sitemap, adresse)], sitemaps lus)."""
    file, vus, urls, lus = list(depart), set(), [], []
    while file and len(lus) < 12 and len(urls) < maxi:
        sm = file.pop(0)
        if sm in vus or sm.lower().endswith(".gz"):
            continue
        vus.add(sm)
        r = fetch(sm, timeout, ua, limit=20_000_000)
        if r["error"] or not r["status"] or r["status"] >= 400:
            continue
        lus.append(sm)
        locs = [unescape(x.strip()) for x in re.findall(r"<loc>\s*(.*?)\s*</loc>", r["body"], re.S | re.I)]
        if re.search(r"<sitemapindex", r["body"], re.I):
            file += locs
        else:
            urls += [(sm, u) for u in locs]
    return urls[:maxi], lus


def echantillon(urls: list, n: int, host: str, exclure=()) -> list:
    """n adresses du même site, prises à tour de rôle dans chaque sitemap (produits, collections, pages…)."""
    par_sm = {}
    for sm, u in urls:
        if urllib.parse.urlsplit(u).netloc.lower() == host and _sans_query(u) not in exclure:
            lst = par_sm.setdefault(sm, [])
            if u not in lst:
                lst.append(u)
    out = []
    while len(out) < n and any(par_sm.values()):
        for sm in par_sm:
            if par_sm[sm] and len(out) < n:
                out.append(par_sm[sm].pop(0))
    return out


def resume_page(url: str, timeout: float = 20, ua: str = UA) -> dict:
    r = fetch(url, timeout, ua)
    d = {"url": url, "statut": r["status"], "url_finale": r["url"], "erreur": r["error"]}
    if r["error"] or not r["status"] or r["status"] >= 400:
        return d
    p = PageParser()
    try:
        p.feed(r["body"])
    except Exception:
        pass
    objs, broken = flatten_jsonld(p.jsonld)
    types = {x for o in objs for x in _types(o)}
    robots_meta = (p.meta.get("robots", "") + " " + p.meta.get("googlebot", "") + " "
                   + r["headers"].get("x-robots-tag", "")).lower()
    d.update(title=p.title or "", description=" ".join(p.meta.get("description", "").split()),
             h1=len([h for h in p.h1 if h]), noindex="noindex" in robots_meta,
             canonical=urllib.parse.urljoin(r["url"], p.canonical[0]) if p.canonical else None,
             produit=bool(types & {"Product", "ProductGroup"}), jsonld_casse=broken,
             images_sans_alt=p.images_no_alt)
    return d


def _doublons(pages: list, cle: str) -> list:
    groupes = {}
    for d in pages:
        v = " ".join(str(d.get(cle) or "").lower().split())
        if v:
            groupes.setdefault(v, []).append(d)
    return [g for g in groupes.values() if len(g) > 1]


def explorer(rep: dict, point, root: str, page_url: str, sitemaps: list, groups, n: int, timeout: float, ua: str,
             pause: float = 1.0) -> None:
    """Lit n pages du sitemap et relève ce qui se répète d'une page à l'autre (module 06 du skill)."""
    urls, lus = lire_sitemaps(sitemaps or [root + "/sitemap.xml"], timeout, ua)
    host = urllib.parse.urlsplit(root).netloc.lower()
    rep["site"] = {"sitemaps_lus": lus, "urls_sitemap": len(urls), "pages": [], "ignorees_robots": 0}
    if not urls:
        point("⚠", "Site : pages du sitemap", "aucune adresse lue dans le sitemap",
              "vérifier que le sitemap est joignable et au bon format", "06")
        return
    pages = []
    for u in echantillon(urls, n, host, {_sans_query(page_url)}):
        path = urllib.parse.urlsplit(u).path or "/"
        if groups is not None and not allowed(groups, "cerveau-audit", path)[0]:
            rep["site"]["ignorees_robots"] += 1
            continue
        if pages and pause > 0:
            time.sleep(pause)
        pages.append(resume_page(u, timeout, ua))
    rep["site"]["pages"] = pages
    ok = [d for d in pages if d.get("statut") and d["statut"] < 400]
    for d in pages:
        rq = []
        if not d.get("statut") or d["statut"] >= 400:
            rq.append(f"erreur {d.get('statut') or d.get('erreur')}")
        else:
            if _sans_query(d["url_finale"]) != _sans_query(d["url"]):
                rq.append("redirigée")
            if d["noindex"]:
                rq.append("noindex")
            if not d["title"]:
                rq.append("sans titre")
            if not d["description"]:
                rq.append("sans description")
            if d["h1"] != 1:
                rq.append(f"{d['h1']} H1")
            if re.search(r"/products?/|/produits?/", urllib.parse.urlsplit(d["url"]).path) and not d["produit"]:
                rq.append("fiche sans Product")
            if d["jsonld_casse"]:
                rq.append("JSON-LD illisible")
        d["remarques"] = rq
    point("·", "Site : pages lues", f"{len(pages)} page(s) du sitemap sur {len(urls)} adresse(s)"
          + (f" ({rep['site']['ignorees_robots']} interdite(s) par robots.txt)" if rep["site"]["ignorees_robots"]
             else ""))

    def exemples(lst):
        return ", ".join(_court(d["url"]) for d in lst[:4]) + (f" (+{len(lst) - 4})" if len(lst) > 4 else "")

    regles = [
        ("✗", "Site : pages en erreur", [d for d in pages if d not in ok],
         "les retirer du sitemap ou les rediriger (301) vers la page la plus proche"),
        ("✗", "Site : noindex dans le sitemap", [d for d in ok if d["noindex"]],
         "une page du sitemap doit être indexable : retirer noindex ou la sortir du sitemap"),
        ("⚠", "Site : pages redirigées", [d for d in ok if "redirigée" in d["remarques"]],
         "le sitemap doit lister les adresses finales"),
        ("⚠", "Site : titres absents", [d for d in ok if not d["title"]], "un titre unique par page"),
        ("⚠", "Site : meta descriptions absentes", [d for d in ok if not d["description"]],
         "une description unique d'environ 150 caractères par page"),
        ("⚠", "Site : H1 absent ou multiple", [d for d in ok if d["h1"] != 1], "un seul H1 par page"),
        ("⚠", "Site : fiches produit sans données Product", [d for d in ok if "fiche sans Product" in d["remarques"]],
         "Product + Offer sur chaque fiche (thème ou application)"),
        ("✗", "Site : JSON-LD illisible", [d for d in ok if d["jsonld_casse"]], "corriger la syntaxe du bloc"),
    ]
    for niveau, sujet, lst, conseil in regles:
        if lst:
            point(niveau, sujet, f"{len(lst)}/{len(pages)} : {exemples(lst)}", conseil, "06")
    for cle, sujet in (("title", "Site : titres en double"), ("description", "Site : meta descriptions en double")):
        groupes = _doublons(ok, cle)
        if groupes:
            g = groupes[0]
            point("⚠", sujet, f"{sum(len(x) for x in groupes)} page(s) concernée(s), ex. « {g[0][cle][:70]} » sur "
                  f"{exemples(g)}", "chaque page a son propre titre et sa propre description", "06")
    if ok and not any(d["remarques"] for d in ok) and len(ok) == len(pages):
        point("✓", "Site : pages du sitemap", f"{len(ok)} page(s) lue(s) sans défaut repéré")


# ------------------------------------------------------------------------------------------------ vitesse
PSI = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def mesurer_vitesse(url: str, timeout: float = 90, ua: str = UA) -> dict:
    """Core Web Vitals (mobile) via l'API PageSpeed Insights : terrain (CrUX, 28 jours) et laboratoire (Lighthouse)."""
    q = {"url": url, "strategy": "mobile", "category": "performance", "locale": "fr"}
    if os.environ.get("PAGESPEED_API_KEY"):
        q["key"] = os.environ["PAGESPEED_API_KEY"]
    r = fetch((os.environ.get("PSI_ENDPOINT") or PSI) + "?" + urllib.parse.urlencode(q), max(timeout, 90), ua,
              limit=40_000_000)
    if r["error"] or not r["status"] or r["status"] >= 400:
        msg = r["error"] or f"HTTP {r['status']}"
        try:
            msg = json.loads(r["body"])["error"]["message"][:160]
        except (ValueError, KeyError, TypeError):
            pass
        return {"erreur": msg}
    try:
        data = json.loads(r["body"])
    except ValueError:
        return {"erreur": "réponse illisible"}
    lh = data.get("lighthouseResult") or {}
    audits = lh.get("audits") or {}
    perf = ((lh.get("categories") or {}).get("performance") or {}).get("score")

    def num(k):
        return (audits.get(k) or {}).get("numericValue")

    labo = {"score": round(perf * 100) if isinstance(perf, (int, float)) else None,
            "lcp_ms": num("largest-contentful-paint"), "cls": num("cumulative-layout-shift"),
            "tbt_ms": num("total-blocking-time"), "fcp_ms": num("first-contentful-paint")}
    gains = []
    for k, a in audits.items():
        if not isinstance(a, dict) or (isinstance(a.get("score"), (int, float)) and a["score"] >= 0.9):
            continue
        det = a.get("details") or {}
        ms = det.get("overallSavingsMs") or 0
        sav = a.get("metricSavings") or {}
        ms = max(ms, sav.get("LCP") or 0, sav.get("FCP") or 0)
        if ms > 0 and k not in ("largest-contentful-paint", "first-contentful-paint", "speed-index", "interactive"):
            gains.append({"audit": k, "titre": a.get("title") or k, "gain_ms": ms, "detail": a.get("displayValue")})
    gains.sort(key=lambda g: -g["gain_ms"])
    terrain = None
    for src, portee in (("loadingExperience", "cette page"), ("originLoadingExperience", "tout le site")):
        le = data.get(src) or {}
        m = le.get("metrics") or {}
        if not m or (src == "loadingExperience" and le.get("origin_fallback")):
            continue

        def pc(k, m=m):
            return (m.get(k) or {}).get("percentile")

        def cat(k, m=m):
            return (m.get(k) or {}).get("category")

        cls = pc("CUMULATIVE_LAYOUT_SHIFT_SCORE")
        terrain = {"portee": portee, "categorie": le.get("overall_category"),
                   "lcp_ms": pc("LARGEST_CONTENTFUL_PAINT_MS"), "lcp": cat("LARGEST_CONTENTFUL_PAINT_MS"),
                   "inp_ms": pc("INTERACTION_TO_NEXT_PAINT"), "inp": cat("INTERACTION_TO_NEXT_PAINT"),
                   "cls": cls / 100 if isinstance(cls, (int, float)) else None,
                   "cls_cat": cat("CUMULATIVE_LAYOUT_SHIFT_SCORE")}
        break
    return {"labo": labo, "terrain": terrain, "gains": gains[:3], "lighthouse": lh.get("lighthouseVersion")}


def _s(ms) -> str:
    return "?" if ms is None else (f"{ms / 1000:.1f} s".replace(".", ",") if ms >= 1000 else f"{ms:.0f} ms")


def _cls(v) -> str:
    return "?" if v is None else f"{v:.2f}".replace(".", ",")


def points_vitesse(point, v: dict, lien: str) -> None:
    if v.get("erreur"):
        point("·", "Vitesse", f"PageSpeed Insights indisponible ({v['erreur']})", f"mesurer à la main : {lien}", "03")
        return
    t = v.get("terrain")
    if t:
        niveau = {"FAST": "✓", "AVERAGE": "⚠", "SLOW": "✗"}.get(t["categorie"], "·")
        point(niveau, "Vitesse (visiteurs réels, 28 jours)",
              f"LCP {_s(t['lcp_ms'])} · INP {_s(t['inp_ms'])} · CLS {_cls(t['cls'])} ({t['portee']}, 75e centile)",
              "" if niveau == "✓" else "seuils « bons » : LCP ≤ 2,5 s, INP ≤ 200 ms, CLS ≤ 0,1 — commencer par les "
              "gains ci-dessous", "03")
    else:
        point("·", "Vitesse (visiteurs réels, 28 jours)", "pas assez de visites Chrome pour des données terrain : se "
              "fier à la mesure de laboratoire")
    lab = v.get("labo") or {}
    if lab.get("score") is not None:
        sc = lab["score"]
        gains = "; ".join(f"{g['titre']}" + (f" ({g['detail']})" if g.get("detail") else "") for g in v.get("gains", []))
        point("✓" if sc >= 90 else "⚠" if sc >= 50 else "✗", "Vitesse (laboratoire, mobile)",
              f"score {sc}/100 · LCP {_s(lab['lcp_ms'])} · TBT {_s(lab['tbt_ms'])} · CLS {_cls(lab['cls'])}",
              ("gains possibles : " + gains) if gains and sc < 90 else "", "03")


# ------------------------------------------------------------------------------------------------ rapport Markdown
def markdown(rep: dict) -> str:
    u = rep.get("url_finale") or rep["url"]
    nb = {n: sum(p["niveau"] == n for p in rep["points"]) for n in ("✗", "⚠", "✓", "·")}
    out = [f"# Audit du site — {urllib.parse.urlsplit(u).netloc}", "",
           f"Page auditée : {u}  ", f"Date : {time.strftime('%d/%m/%Y')}"
           + (f" · plateforme : {rep['plateforme']}" if rep.get("plateforme") else ""), "",
           f"**{nb['✗']} point(s) bloquant(s) · {nb['⚠']} à améliorer · {nb['✓']} en place**", ""]
    titres = {"✗": "À corriger d'abord", "⚠": "À améliorer", "✓": "Déjà en place", "·": "Pour information"}
    for n in ("✗", "⚠", "✓", "·"):
        pts = [p for p in rep["points"] if p["niveau"] == n]
        if not pts:
            continue
        out += [f"## {n} {titres[n]}", ""]
        for p in pts:
            out.append(f"- **{p['sujet']}** — {p['constat']}")
            if p["conseil"] and n != "✓":
                out.append(f"  → {p['conseil']}")
        out.append("")

    def cell(x) -> str:
        return str(x).replace("|", "/").replace("\n", " ")

    v = rep.get("vitesse") or {}
    if v and not v.get("erreur"):
        out += ["## Vitesse (mobile)", "", "| Mesure | LCP | INP / TBT | CLS |", "|---|---|---|---|"]
        t, lab = v.get("terrain"), v.get("labo") or {}
        if t:
            out.append(f"| Visiteurs réels ({t['portee']}) | {_s(t['lcp_ms'])} | INP {_s(t['inp_ms'])} | "
                       f"{_cls(t['cls'])} |")
        out.append(f"| Laboratoire (score {lab.get('score')}/100) | {_s(lab.get('lcp_ms'))} | TBT "
                   f"{_s(lab.get('tbt_ms'))} | {_cls(lab.get('cls'))} |")
        out.append("")
        if v.get("gains"):
            out += ["Gains les plus importants :", ""] + [f"1. {cell(g['titre'])}" for g in v["gains"]] + [""]
    pages = (rep.get("site") or {}).get("pages") or []
    if pages:
        out += ["## Pages lues dans le sitemap", "", "| Page | HTTP | Titre | Remarques |", "|---|---|---|---|"]
        for d in pages:
            out.append(f"| {cell(_court(d['url']))} | {d.get('statut') or '—'} | {cell((d.get('title') or '')[:60])} | "
                       f"{cell(', '.join(d.get('remarques') or []) or 'RAS')} |")
        out.append("")
    robots = (rep.get("robots") or {}).get("robots") or []
    if robots:
        out += ["## Robots des moteurs et des assistants IA (robots.txt)", "", "| Robot | Rôle | Autorisé |",
                "|---|---|---|"]
        out += [f"| {x['robot']} | {cell(x['role'])} | {'oui' if x['autorise'] else 'non'} |" for x in robots]
        out.append("")
    out += ["## Pour aller plus loin", ""]
    if rep.get("pagespeed"):
        out += [f"- Vitesse détaillée : {rep['pagespeed']}", f"- Test des résultats enrichis : "
                f"{rep['test_resultats_enrichis']}"]
    out += ["", "## Méthode et limites", "",
            "Lecture automatique des pages publiques sans exécuter le JavaScript (comme un premier passage de robot) : "
            "un élément ajouté par un script (bandeau cookies, widget d'avis, bouton) peut exister sans être vu ici. "
            "Les points de conformité signalent quoi vérifier, ce n'est pas un avis juridique. Aucun résultat de vente "
            "n'est garanti.", ""]
    return "\n".join(out)


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
    legal, pages, vitesse, pause, rapport, complet = False, None, False, 1.0, None, False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            as_json = True
        elif a == "--conformite":
            legal = True
        elif a == "--vitesse":
            vitesse = True
        elif a == "--complet":
            legal, vitesse, complet = True, True, True
        elif a in ("--timeout", "--ua", "--pages", "--pause", "--rapport") and i + 1 < len(args):
            val = args[i + 1]
            if a == "--ua":
                ua = val
            elif a == "--rapport":
                rapport = val
            else:
                try:
                    n = float(val.replace(",", "."))
                    if n < 0 or n != n:
                        raise ValueError
                except ValueError:
                    print(f"Erreur : {a} attend un nombre positif, pas « {val} »", file=sys.stderr)
                    return 1
                if a == "--timeout":
                    timeout = n
                elif a == "--pause":
                    pause = n
                else:
                    pages = min(int(n), 200)
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
    if pages is None:  # --complet : 10 pages, sauf nombre donné avec --pages
        pages = 10 if complet else 0
    rep = audit(urls[0], timeout, ua, legal=legal, pages=pages, vitesse=vitesse, pause=pause)
    print(json.dumps(rep, ensure_ascii=False, indent=2) if as_json else texte(rep))
    if rapport:
        try:
            Path(rapport).write_text(markdown(rep), encoding="utf-8")
        except OSError as exc:
            print(f"Erreur : rapport non écrit ({exc})", file=sys.stderr)
            return 1
        if not as_json:
            print(f"\n✓ rapport Markdown : {rapport}")
    return 0 if rep.get("statut") and rep["statut"] < 400 else 2


if __name__ == "__main__":
    sys.exit(main())
