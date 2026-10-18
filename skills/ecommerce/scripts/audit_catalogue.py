#!/usr/bin/env python3
"""Audit du catalogue d'une boutique Shopify : tous les produits d'un coup, sans compte ni outil payant.

Deux sources :
- --url https://boutique.fr : le catalogue public (/products.json), seulement si robots.txt l'autorise ;
- --csv produits.csv : l'export de l'admin Shopify (Produits › Exporter), plus complet (codes-barres, textes
  alternatifs, titres et descriptions SEO, statut).

Par produit : titre (longueur, texte promotionnel, majuscules), description (absente, courte, identique à celle d'un
autre produit, restes de texte fournisseur, en anglais, risques juridiques via relire_texte.py), images (absentes, trop
peu, sans texte alternatif), prix (à 0, prix barré à justifier), code-barres (GTIN), marque, type, rupture affichée,
titre et description SEO. Les produits à corriger en premier sont classés.
--flux fichier.tsv : flux produits pour Google ou Microsoft Merchant Center (sites sans application de flux) : une ligne
par variante, attributs de variante (couleur, taille, matière, motif), GTIN seulement s'ils sont valides, prix réel (pas
de prix barré : voir L112-1-1).

Bibliothèque standard uniquement. Usage : python scripts/audit_catalogue.py (--url <boutique> | --csv <export.csv>)
[--site https://boutique.fr] [--max 1000] [--flux flux.tsv] [--json]"""
from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_site  # noqa: E402  (même dossier : robots.txt, réseau)
import relire_texte  # noqa: E402  (même dossier : risques juridiques du texte)

POIDS = {"🔴": 10, "⚠": 3, "·": 1}
PROMO_TITRE = re.compile(r"(?<!\w)(?:promo(?:tion)?s?|soldes?|-\s?\d{1,2} ?%|livraison (?:offerte|gratuite)|gratuite?s?|"
                         r"meilleur prix|offre spéciale|best ?seller)(?!\w)", re.I)
FOURNISSEUR = re.compile(r"100 ?% brand new|package (?:includes?|content)|due to the (?:different|difference)|"
                         r"please allow|aliexpress|dropship|high quality|specifications?:|item type:|"
                         r"note: (?:the|due|please)", re.I)
VARIANTE = {"couleur": "color", "coloris": "color", "teinte": "color", "color": "color", "colour": "color",
            "taille": "size", "pointure": "size", "format": "size", "contenance": "size", "poids": "size",
            "volume": "size", "size": "size", "matière": "material", "matiere": "material", "material": "material",
            "motif": "pattern", "imprimé": "pattern", "pattern": "pattern"}
EN = {"the", "and", "with", "for", "your", "this", "is", "of", "to", "are", "you", "it", "from", "will", "can"}
FR = {"le", "la", "les", "et", "avec", "pour", "votre", "ce", "est", "de", "des", "du", "un", "une", "vous", "sur"}


def _norm(s) -> str:
    return " ".join(unicodedata.normalize("NFC", str(s or "")).split())


def gtin_ok(code) -> bool:
    """GTIN-8, 12, 13 ou 14 avec la bonne clé de contrôle, hors codes internes (EAN commençant par 2, UPC par 2 ou 4)."""
    c = re.sub(r"[\s-]", "", str(code or ""))
    if not re.fullmatch(r"\d{8}|\d{12,14}", c) or not c.strip("0"):
        return False
    if (len(c) == 13 and c[0] == "2") or (len(c) == 12 and c[0] in "24"):
        return False
    d = [int(x) for x in c]
    total = sum(x * (3 if i % 2 == 0 else 1) for i, x in enumerate(reversed(d[:-1])))
    return (10 - total % 10) % 10 == d[-1]


def _price(v):
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------------ sources
def depuis_url(url: str, maxi: int = 1000, timeout: float = 20) -> tuple:
    """Catalogue public /products.json (pagination par 250). → (produits, racine, message ou None)."""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    root = f"{parts.scheme}://{parts.netloc}"
    rob = audit_site.fetch(root + "/robots.txt", timeout)
    if rob["status"] and rob["status"] < 400:
        ok, _ = audit_site.allowed(audit_site.parse_robots(rob["body"]), "cerveau-audit", "/products.json")
        if not ok:
            return [], root, ("robots.txt de la boutique interdit /products.json aux robots : utilise l'export de "
                              "l'admin (Produits › Exporter) avec --csv")
    out, page = [], 1
    while len(out) < maxi:
        r = audit_site.fetch(f"{root}/products.json?limit=250&page={page}", timeout)
        if r["error"] or not r["status"] or r["status"] >= 400:
            if not out:
                return [], root, (f"catalogue public illisible ({r['status'] or r['error']}) : boutique non Shopify, "
                                  "protégée par mot de passe, ou catalogue fermé → --csv")
            break
        try:
            items = json.loads(r["body"]).get("products") or []
        except ValueError:
            return [], root, "réponse illisible pour /products.json : boutique non Shopify ? → --csv"
        if not items:
            break
        out += [_from_json(p, root) for p in items]
        if len(items) < 250:
            break
        page += 1
    return out[:maxi], root, None


def _from_json(p: dict, root: str) -> dict:
    imgs = p.get("images") or []
    names = [_norm(o.get("name") if isinstance(o, dict) else o) for o in p.get("options") or []]
    return {"handle": p.get("handle") or "", "title": _norm(p.get("title")), "html": p.get("body_html") or "",
            "vendor": _norm(p.get("vendor")), "type": _norm(p.get("product_type")), "status": "active",
            "options": names,
            "variants": [{"id": v.get("id"), "options": [_norm(v.get(f"option{k}")) for k in (1, 2, 3)][:len(names)],
                          "sku": v.get("sku"), "price": _price(v.get("price")),
                          "compare_at": _price(v.get("compare_at_price")), "barcode": v.get("barcode"),
                          "available": v.get("available"), "qty": None, "grams": v.get("grams"),
                          "requires_shipping": v.get("requires_shipping", True)} for v in p.get("variants") or []],
            "images": [{"src": i.get("src"), "alt": i.get("alt")} for i in imgs],
            "alt_known": any("alt" in i for i in imgs), "barcode_known": any("barcode" in v for v in p.get("variants") or []),
            "seo_title": None, "seo_description": None, "url": f"{root}/products/{p.get('handle') or ''}",
            "source": "json"}


def depuis_csv(path: str, site: str | None = None) -> list:
    """Export produits de l'admin Shopify (une ligne par variante ou image, regroupées par Handle)."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return []
    keys = {re.sub(r"[^a-z0-9]", "", k.lower()): k for k in rows[0].keys() if k}

    def col(row, *names):
        for n in names:
            k = keys.get(re.sub(r"[^a-z0-9]", "", n.lower()))
            if k and row.get(k) not in (None, ""):
                return row[k]
        return None

    root = site.rstrip("/") if site else ""
    prods, order = {}, []
    for row in rows:
        h = col(row, "Handle")
        if not h:
            continue
        if h not in prods:
            prods[h] = {"handle": h, "title": "", "html": "", "vendor": "", "type": "", "status": "active",
                        "options": [], "variants": [], "images": [], "alt_known": True, "barcode_known": True, "seo_title": None,
                        "seo_description": None, "url": f"{root}/products/{h}" if root else "", "source": "csv"}
            order.append(h)
        p = prods[h]
        if col(row, "Title"):
            p["title"] = _norm(col(row, "Title"))
            p["html"] = col(row, "Body (HTML)", "Body HTML", "Body") or ""
            p["vendor"] = _norm(col(row, "Vendor"))
            p["type"] = _norm(col(row, "Type", "Product Type"))
            p["seo_title"] = _norm(col(row, "SEO Title")) or None
            p["seo_description"] = _norm(col(row, "SEO Description")) or None
            status = (col(row, "Status") or "").lower()
            published = (col(row, "Published") or "").lower()
            p["status"] = status or ("draft" if published in ("false", "faux", "0") else "active")
            p["options"] = [_norm(col(row, f"Option{k} Name")) for k in (1, 2, 3)]
        price = col(row, "Variant Price")
        if price is not None:
            qty = col(row, "Variant Inventory Qty")
            tracker = col(row, "Variant Inventory Tracker")
            p["variants"].append({"id": None, "options": [_norm(col(row, f"Option{k} Value")) for k in (1, 2, 3)],
                                  "sku": col(row, "Variant SKU"), "price": _price(price),
                                  "compare_at": _price(col(row, "Variant Compare At Price")),
                                  "barcode": col(row, "Variant Barcode"),
                                  "qty": int(float(qty)) if qty not in (None, "") and tracker else None,
                                  "available": None, "grams": _price(col(row, "Variant Grams")),
                                  "requires_shipping": (col(row, "Variant Requires Shipping") or "true").lower() != "false"})
        src = col(row, "Image Src")
        if src and all(i["src"] != src for i in p["images"]):
            p["images"].append({"src": src, "alt": col(row, "Image Alt Text") or ""})
    return [prods[h] for h in order]


# ------------------------------------------------------------------------------------------------ contrôles
def texte(html_text: str) -> str:
    return _norm(relire_texte.texte_brut(html_text or ""))


def controler(products: list) -> dict:
    actifs = [p for p in products if p.get("status") in ("active", "actif", "")]
    debut = {}
    for p in actifs:
        t = texte(p["html"]).lower()
        if len(t) >= 80:
            debut.setdefault(t[:300], []).append(p["handle"])
    resultats = []
    for p in actifs:
        pb = []
        title, t = p["title"], texte(p["html"])

        def add(niveau, code, msg):
            pb.append({"niveau": niveau, "code": code, "message": msg})

        if len(title) < 15:
            add("⚠", "titre-court", f"titre court ({len(title)} car.) : produit + attribut clé + usage")
        if len(title) > 150:
            add("⚠", "titre-long", f"titre de {len(title)} car. : coupé à 150 par Merchant Center")
        if PROMO_TITRE.search(title):
            add("⚠", "titre-promo", f"texte promotionnel dans le titre (« {PROMO_TITRE.search(title).group(0)} ») : "
                                    "à retirer des titres envoyés à Merchant Center")
        valeurs = {o for v in p["variants"] for o in v.get("options") or []
                   if o and o.lower() not in ("default title", "titre par défaut")}
        if len(p["variants"]) > 1:
            dedans = sorted(o for o in valeurs if len(o) > 1 and re.search(rf"(?<!\w){re.escape(o)}(?!\w)", title, re.I))
            if dedans:
                add("·", "titre-variante", f"le titre cite « {dedans[0]} », une valeur de variante : chaque variante "
                                           "hérite de ce titre (flux, partages) — le retirer")
        lettres = [c for c in title if c.isalpha()]
        if len(lettres) >= 10 and sum(c.isupper() for c in lettres) / len(lettres) > 0.5:
            add("⚠", "titre-majuscules", "titre en majuscules")
        if not t:
            add("🔴", "description-absente", "aucune description")
        else:
            if len(t) < 300:
                add("⚠", "description-courte", f"description courte ({len(t)} car.) : bénéfices, usage, dimensions, "
                                               "matière, entretien, livraison")
            twins = [h for h in debut.get(t.lower()[:300], []) if h != p["handle"]]
            if twins:
                add("⚠", "description-dupliquee", f"description identique à {len(twins)} autre(s) produit(s) "
                                                  f"({', '.join(twins[:3])})")
            if FOURNISSEUR.search(t):
                add("⚠", "texte-fournisseur", f"restes de texte fournisseur (« {FOURNISSEUR.search(t).group(0)} ») : "
                                              "réécrire à partir des caractéristiques vérifiées")
            mots = re.findall(r"[a-zà-ÿ']+", t.lower())
            en, fr = sum(m in EN for m in mots), sum(m in FR for m in mots)
            if en >= 8 and en > fr:
                add("⚠", "description-anglais", "description en anglais : le français est obligatoire (loi Toubon)")
            rel = relire_texte.relire(p["html"], "fiche")
            for f in [f for f in rel["points"] if f["niveau"] == "🔴"][:3]:
                add("🔴", "texte-juridique", f"{f['sujet']} : « {f['extrait']} »")
        imgs = p["images"]
        if not imgs:
            add("🔴", "images-absentes", "aucune image")
        elif len(imgs) < 3:
            add("⚠", "images-peu", f"{len(imgs)} image(s) : viser 5 (fond neutre, échelle, détail, usage)")
        if imgs and p.get("alt_known"):
            sans = sum(not _norm(i.get("alt")) for i in imgs)
            if sans:
                add("⚠", "images-sans-alt", f"{sans} image(s) sans texte alternatif")
            elif len(imgs) > 1 and len({_norm(i.get('alt')).lower() for i in imgs}) == 1:
                add("·", "alt-recopie", "même texte alternatif sur toutes les images : décrire chaque photo")
        vs = p["variants"]
        if any((v.get("price") or 0) <= 0 for v in vs):
            add("🔴", "prix-zero", "variante à 0 € (ou sans prix)")
        barres = [v for v in vs if v.get("compare_at") and v.get("price") and v["compare_at"] > v["price"]]
        if barres:
            v = barres[0]
            add("⚠", "prix-barre", f"prix barré affiché ({v['compare_at']:.2f} € → {v['price']:.2f} €) : le prix de "
                                   "référence doit être le plus bas des 30 jours précédents (C. conso., art. L112-1-1)")
        codes = [_norm(v.get("barcode")) for v in vs if _norm(v.get("barcode"))]
        faux = [c for c in codes if not gtin_ok(c)]
        if faux:
            add("⚠", "gtin-invalide", f"code-barres « {faux[0]} » refusé par Merchant Center (longueur, clé de contrôle "
                                      "ou code interne) : corriger ou laisser vide")
        elif p.get("barcode_known") and vs and not codes:
            add("·", "sans-gtin", "pas de code-barres (GTIN) : à renseigner s'il existe (fiches marchandes)")
        if vs and all(v.get("requires_shipping", True) and not v.get("grams") for v in vs):
            add("·", "poids-zero", "poids à 0 : frais de port calculés faux")
        if not p["vendor"]:
            add("⚠", "sans-marque", "marque (vendor) vide : attribut brand des fiches gratuites")
        if not p["type"]:
            add("·", "sans-type", "type de produit vide")
        stock = [v.get("qty") for v in vs if v.get("qty") is not None]
        dispo = [v.get("available") for v in vs if v.get("available") is not None]
        if (stock and all(q <= 0 for q in stock)) or (dispo and not any(dispo)):
            add("⚠", "rupture", "en rupture mais en ligne : dépublier ou annoncer un délai réel")
        if p.get("source") == "csv":  # titres et descriptions SEO : seulement dans l'export de l'admin
            st, sd = p.get("seo_title"), p.get("seo_description")
            if not st:
                add("·", "seo-titre-vide", "titre SEO vide : le titre du produit est repris tel quel")
            elif len(st) > 70:
                add("⚠", "seo-titre-long", f"titre SEO de {len(st)} car. (60 au plus conseillé)")
            if not sd:
                add("·", "seo-description-vide", "méta-description vide : le début de la description est repris, "
                                                  "souvent coupé")
            elif len(sd) > 160:
                add("⚠", "seo-description-longue", f"méta-description de {len(sd)} car. (155 au plus conseillé)")
        resultats.append({"handle": p["handle"], "titre": title, "url": p.get("url"), "problemes": pb,
                          "score": sum(POIDS[x["niveau"]] for x in pb)})
    codes = {}
    for r in resultats:
        for k in {(x["niveau"], x["code"]) for x in r["problemes"]}:
            codes[k] = codes.get(k, 0) + 1
    resultats.sort(key=lambda r: -r["score"])
    return {"produits": len(products), "audites": len(actifs), "brouillons": len(products) - len(actifs),
            "avec_rouge": sum(any(x["niveau"] == "🔴" for x in r["problemes"]) for r in resultats),
            "sans_probleme": sum(not r["problemes"] for r in resultats),
            "par_code": [{"niveau": k[0], "code": k[1], "produits": v}
                         for k, v in sorted(codes.items(), key=lambda kv: (-POIDS[kv[0][0]], -kv[1]))],
            "resultats": resultats}


# ------------------------------------------------------------------------------------------------ sorties
def rapport(res: dict, source: str) -> str:
    out = [f"Audit du catalogue — {source}",
           f"{res['audites']} produit(s) en ligne audité(s)" + (f", {res['brouillons']} brouillon(s) ignoré(s)"
                                                                 if res["brouillons"] else "")
           + f" · {res['avec_rouge']} avec un point 🔴 · {res['sans_probleme']} sans remarque", ""]
    if res["par_code"]:
        out.append("Problèmes les plus fréquents :")
        for c in res["par_code"][:12]:
            out.append(f"  {c['niveau']} {c['code']} : {c['produits']} produit(s)")
        out.append("")
    a_faire = [r for r in res["resultats"] if r["problemes"]][:15]
    if a_faire:
        out.append("À corriger en premier :")
        for r in a_faire:
            out.append(f"• {r['titre'] or r['handle']} ({r['handle']}) — score {r['score']}")
            for x in sorted(r["problemes"], key=lambda x: -POIDS[x["niveau"]])[:6]:
                out.append(f"    {x['niveau']} {x['message']}")
    out.append("\nEnsuite : corriger en lot (module 12 du skill : proposition avant/après, puis validation), relancer "
               "l'audit pour mesurer le progrès.")
    return "\n".join(out)


def _tsv(v) -> str:
    return _norm(v).replace('"', "”")


def flux(products: list, path: str, site: str = "") -> dict:
    """Flux produits (TSV) pour Google ou Microsoft Merchant Center : une ligne par variante en ligne.
    → {"lignes": n, "exclus": [(handle, raison)], "a_revoir": [(handle, raison)]}"""
    cols = ["id", "item_group_id", "title", "description", "link", "image_link", "additional_image_link",
            "availability", "price", "brand", "gtin", "mpn", "identifier_exists", "condition", "product_type",
            "color", "size", "material", "pattern"]
    n, exclus, a_revoir = 0, [], []
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(cols)
        for p in products:
            if p.get("status") not in ("active", "actif", ""):
                continue
            imgs = [i["src"] for i in p["images"] if i.get("src")]
            if not imgs:
                exclus.append((p["handle"], "aucune image"))
                continue
            if PROMO_TITRE.search(p["title"]):
                a_revoir.append((p["handle"], "texte promotionnel dans le titre (risque de refus)"))
            base = p.get("url") or (f"{site.rstrip('/')}/products/{p['handle']}" if site else "")
            desc = _tsv(texte(p["html"]))[:5000] or _tsv(p["title"])
            vs = [v for v in p["variants"] if v.get("price")]
            if len(vs) < len(p["variants"]):
                exclus.append((p["handle"], f"{len(p['variants']) - len(vs)} variante(s) sans prix"))
            groupe = len(vs) > 1
            if groupe and p.get("source") == "csv" and len({v["price"] for v in vs}) > 1:
                a_revoir.append((p["handle"], "variantes à prix différents sans lien ?variant= (export CSV) : vérifier "
                                              "le prix affiché par la page dans Merchant Center"))
            for k, v in enumerate(vs, 1):
                attrs, extra = {}, []
                for name, val in zip(p.get("options") or [], v.get("options") or []):
                    if not val or val.lower() in ("default title", "titre par défaut"):
                        continue
                    key = VARIANTE.get((name or "").lower())
                    if key and key not in attrs:
                        attrs[key] = val
                    if groupe and val.lower() not in p["title"].lower():
                        extra.append(val)
                title = _tsv(p["title"] + (" – " + " / ".join(extra) if extra else ""))[:150]
                stock, dispo = v.get("qty"), v.get("available")
                avail = "out_of_stock" if (stock is not None and stock <= 0) or dispo is False else "in_stock"
                code = _norm(v.get("barcode"))
                gtin = code if gtin_ok(code) else ""
                mpn = _norm(v.get("sku")) if not gtin and p["vendor"] else ""
                link = base + (f"?variant={v['id']}" if groupe and v.get("id") and base else "")
                w.writerow([_norm(v.get("sku")) or f"{p['handle']}-{k}", p["handle"] if groupe else "", title, desc,
                            link, imgs[0], ",".join(imgs[1:11]), avail, f"{v['price']:.2f} EUR", _tsv(p["vendor"]),
                            gtin, mpn, "" if gtin or mpn else "no", "new", _tsv(p["type"]),
                            attrs.get("color", ""), attrs.get("size", ""), attrs.get("material", ""),
                            attrs.get("pattern", "")])
                n += 1
    return {"fichier": path, "lignes": n, "exclus": exclus, "a_revoir": a_revoir}


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "--aide"):
        print(__doc__)
        return 0 if args else 1
    opts = {"--url": None, "--csv": None, "--site": None, "--max": "1000", "--flux": None, "--timeout": "20"}
    as_json = False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            as_json = True
        elif a in opts and i + 1 < len(args):
            opts[a] = args[i + 1]
            i += 1
        else:
            print(f"Erreur : option inconnue ou incomplète {a}", file=sys.stderr)
            return 2
        i += 1
    if bool(opts["--url"]) == bool(opts["--csv"]):
        print("Erreur : donne --url <boutique> ou --csv <export.csv> (l'un des deux)", file=sys.stderr)
        return 2
    try:
        maxi, timeout = int(opts["--max"]), float(opts["--timeout"])
    except ValueError:
        print("Erreur : --max et --timeout attendent des nombres", file=sys.stderr)
        return 2
    if opts["--csv"]:
        try:
            products = depuis_csv(opts["--csv"], opts["--site"])
        except OSError as exc:
            print(f"Erreur : {exc}", file=sys.stderr)
            return 2
        source, site = opts["--csv"], opts["--site"] or ""
    else:
        products, site, msg = depuis_url(opts["--url"], maxi, timeout)
        if msg:
            print(f"✗ {msg}", file=sys.stderr)
            return 2
        source = site
    res = controler(products[:maxi])
    if opts["--flux"]:
        try:
            res["flux"] = flux(products[:maxi], opts["--flux"], site)
        except OSError as exc:
            print(f"Erreur : flux non écrit ({exc})", file=sys.stderr)
            return 2
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(rapport(res, source))
        if opts["--flux"]:
            fx = res["flux"]
            print(f"\n✓ flux Merchant Center : {fx['lignes']} ligne(s) → {fx['fichier']} (à vérifier dans Merchant "
                  "Center avant envoi : 🟠)")
            for h, why in fx["exclus"][:10]:
                print(f"  écarté : {h} — {why}")
            for h, why in fx["a_revoir"][:10]:
                print(f"  à revoir : {h} — {why}")
            if not site:
                print("  ⚠ sans --site, la colonne link est vide : Merchant Center l'exige")
    return 1 if res["avec_rouge"] else 0


if __name__ == "__main__":
    sys.exit(main())
