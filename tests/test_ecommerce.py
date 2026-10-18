"""Vérifications du cerveau e-commerce (skills/ecommerce) et de sa livraison par le cerveau (plugin, self-update,
installation classique) — dans des dossiers temporaires, jamais sur la vraie mémoire.

Lancement : python tests/test_ecommerce.py   (sortie : « N vérifications OK, M échec(s) »)"""
import csv
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-ecommerce-test-"))
os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "claude")
os.environ["BRAIN_HOME"] = str(TMP / "brain")
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD"):
    os.environ.pop(k, None)
CODE = Path(__file__).resolve().parent.parent
SKILL_DIR = CODE / "skills" / "ecommerce"
sys.path.insert(0, str(CODE))

from brainkit import install, publish, selfupdate  # noqa: E402

OK, FAIL = [], []


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def run(*args, cwd=None, env=None):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, cwd=str(cwd or TMP), timeout=120,
                       env=env or os.environ.copy())
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


# ------------------------------------------------------------------ 1. le skill lui-même
skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
front = re.match(r"^---\n(.*?)\n---\n", skill, re.S)
check(front is not None, "SKILL.md : en-tête YAML")
meta = dict(re.findall(r"(?m)^(\w+): (.*)$", front.group(1))) if front else {}
check(meta.get("name") == "ecommerce", "SKILL.md : name = ecommerce", meta.get("name"))
desc = meta.get("description", "")
check(0 < len(desc) <= 1024, f"SKILL.md : description de 1 à 1024 caractères ({len(desc)})")
check(len(skill.splitlines()) < 500, f"SKILL.md : moins de 500 lignes ({len(skill.splitlines())})")
mentioned = sorted(set(re.findall(r"`((?:references|scripts|assets)/[\w./-]+)", skill)))
missing = [m for m in mentioned if not (SKILL_DIR / m).exists()]
check(mentioned and not missing, f"SKILL.md : les {len(mentioned)} fichiers cités existent", missing)
refs = sorted(p.name for p in (SKILL_DIR / "references").glob("*.md"))
orphans = [r for r in refs if f"references/{r}" not in skill]
check(refs and not orphans, f"chaque module de references/ est routé depuis SKILL.md ({len(refs)})", orphans)
for ref in refs:
    text = (SKILL_DIR / "references" / ref).read_text(encoding="utf-8")
    check(text.startswith("# "), f"{ref} : commence par un titre")
    for cible in set(re.findall(r"`((?:references|scripts|assets)/[\w./-]+)`", text)):
        check((SKILL_DIR / cible).exists(), f"{ref} : {cible} existe")

every = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in SKILL_DIR.rglob("*") if p.is_file())
for mot in ("TAKUMI", "Takumi", "takumi", "Droppilot", "Caen", "Normandie", "DesTinGOOD"):
    check(mot not in every, f"skill générique : aucune donnée personnelle (« {mot} »)")
check(not publish.secrets_in(SKILL_DIR), "skill : ni secret ni adresse e-mail (contrôle de brain publish)",
      publish.secrets_in(SKILL_DIR))

# ------------------------------------------------------------------ 2. calcul de marge
UE = SKILL_DIR / "scripts" / "unit_economics.py"
c, out = run(UE, "--prix", "39,90", "--cout", "12", "--livraison", "5,50", "--frais-pct", "2,9", "--frais-fixe",
             "0,30", "--retours-pct", "3", "--cotisations-pct", "12", "--marge-cible", "8", "--fixes-mois", "39",
             "--heures", "0,5", "--json")
try:
    res = json.loads(out)["resultats"]
except ValueError:
    res = {}
# cotisations sur le CA net des remboursements : 39,90 × (1 − 3 %) × 12 % ; facteur = 1 − 2,9 % − 3 % − 12 % × 0,97
check(c == 0 and abs(res.get("marge", 0) - (39.9 - 17.5 - 1.4571 - 1.197 - 39.9 * 0.97 * 0.12)) < 1e-6,
      "marge de contribution exacte (cotisations nettes des remboursements)", out[:300])
check(abs(res.get("prix_plancher_ttc", 0) - 25.8 / 0.8246) < 1e-6, "prix plancher exact", res)
check(abs(res.get("prix_equilibre_ttc", 0) - 17.8 / 0.8246) < 1e-6, "prix d'équilibre exact", res)
check(res.get("commandes_par_mois") == 3, "seuil de rentabilité : 3 commandes pour 39 € de fixes", res)
check(abs(res.get("marge_par_heure", 0) - res.get("marge", 0) / 0.5) < 1e-9, "marge par heure investie", res)
c, out = run(UE, "--prix", "29,90", "--port-client", "4,90", "--cout", "9", "--livraison", "5,20", "--frais-pct", "2,9",
             "--frais-fixe", "0,25", "--cotisations-pct", "12,415", "--tva-pct", "20", "--remuneration-mois", "500",
             "--json")
res = json.loads(out)["resultats"] if c == 0 else {}
check(abs(res.get("ca_ht", 0) - 29.0) < 1e-9 and abs(res.get("marge", 0) - 9.94045) < 1e-4,
      "port facturé au client : dans le CA, les frais et les cotisations", out[:300])
eq = res.get("prix_equilibre_ttc", 0)
total = eq + 4.9
marge_eq = total / 1.2 - 14.2 - (total * 0.029 + 0.25) - total / 1.2 * 0.12415
check(abs(marge_eq) < 1e-9, "prix d'équilibre avec port facturé : marge nulle à ce prix", res)
check(res.get("commandes_par_mois") == 51, "ventes par mois pour se payer 500 € (ceil(500 / 9,94))", res)
c, out = run(UE, "--prix", "10", "--cout", "3", "--tva-pct", "20", "--json")
res = json.loads(out)["resultats"] if c == 0 else {}
check(abs(res.get("ca_ht", 0) - 8.3333) < 0.001 and abs(res.get("marge", 0) - 5.3333) < 0.001,
      "TVA 20 % : prix HT et marge", out[:300])
c, out = run(UE, "--prix", "abc", "--cout", "3")
check(c == 1 and "invalide" in out, "valeur invalide refusée", out)
c, out = run(UE, "--prix", "10", "--cout", "3", "--frais", "2")
check(c == 1 and "inconnue" in out, "option inconnue refusée", out)
c, out = run(UE, "--prix", "20", "--cout", "30")
check(c == 0 and "Marge négative" in out, "marge négative signalée", out)
c, out = run(UE, "--aide")
check(c == 0 and "--prix" in out, "aide du calcul de marge")


# ------------------------------------------------------------------ 3. audit SEO/GEO express (site local)
SITE = TMP / "site"
(SITE / "products").mkdir(parents=True)
(SITE / "products" / "lampe.html").write_text("""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>Lampe de chevet tactile en bois – lumière chaude | Maison Test</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="canonical" href="/products/lampe.html">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Product","name":"Lampe tactile",
"image":"/l.jpg","description":"Lampe","sku":"L1","brand":{"@type":"Brand","name":"Maison Test"},"offers":{"@type":"Offer",
"price":"39.90","priceCurrency":"EUR","availability":"https://schema.org/InStock"}},{"@type":"Organization",
"name":"Maison Test","url":"/"}]}</script>
<script type="application/ld+json">{"@type": "FAQPage", cassé</script>
</head><body><h1>Lampe tactile</h1><h1>Autre</h1><img src="a.jpg"><img src="b.jpg" alt="Lampe allumée"></body></html>
""", encoding="utf-8")
(SITE / "products" / "cache.html").write_text('<html><head><meta name="robots" content="noindex"><title>x</title>'
                                              '</head><body></body></html>', encoding="utf-8")
(SITE / "sitemap.xml").write_text('<?xml version="1.0"?><urlset></urlset>', encoding="utf-8")
(SITE / "products" / "groupe.html").write_text("""<html lang="fr"><head><title>Tasse émaillée bleue – 35 cl | Maison
Test</title><script type="application/ld+json">[{"@context":"https://schema.org","@type":"ProductGroup","name":"Tasse",
"image":"/t.jpg","description":"Tasse émaillée","brand":{"@type":"Brand","name":"Maison Test"},"hasVariant":[
{"@type":"Product","name":"Tasse bleue","sku":"T-B","offers":{"@type":"Offer","price":"19.00","priceCurrency":"EUR",
"availability":"https://schema.org/InStock"}},{"@type":"Product","name":"Tasse verte","sku":"T-V","offers":{"@type":
"Offer","price":"19.00","priceCurrency":"EUR","availability":"https://schema.org/InStock"}}]},{"@type":"Organization",
"name":"Maison Test","sameAs":["https://www.instagram.com/maisontest"],"hasMerchantReturnPolicy":{"@type":
"MerchantReturnPolicy"},"hasShippingService":{"@type":"ShippingService"}}]</script></head><body><h1>Tasse</h1></body>
</html>""", encoding="utf-8")


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SITE), **kw)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
(SITE / "robots.txt").write_text(f"""User-agent: *
Disallow: /cart

User-agent: GPTBot
Disallow: /

User-agent: PerplexityBot
User-agent: OAI-SearchBot
Crawl-delay: 2
Disallow: /products/
Allow: /products/lampe.html$

Sitemap: {BASE}/sitemap.xml
""", encoding="utf-8")

sys.path.insert(0, str(SKILL_DIR / "scripts"))
import audit_site  # noqa: E402

rep = audit_site.audit(f"{BASE}/products/lampe.html", timeout=10)
points = {(p["sujet"], p["niveau"]) for p in rep["points"]}
texts = " | ".join(f"{p['niveau']} {p['sujet']} : {p['constat']}" for p in rep["points"])
check(rep["statut"] == 200, "audit : page lue", rep.get("erreur"))
check(("Données structurées", "✗") in points, "audit : bloc JSON-LD cassé repéré", texts)
check(("H1", "⚠") in points, "audit : deux H1 repérés", texts)
check(("Meta description", "⚠") in points, "audit : meta description absente repérée", texts)
check(any(p["sujet"] == "Livraison et retours" and p["niveau"] == "·" and "livraison, retours" in p["constat"]
          for p in rep["points"]), "audit : livraison et retours non balisés signalés (à déclarer en Search Console)",
      texts)
check(any(p["sujet"] == "Images" and "1 sans attribut alt" in p["constat"] for p in rep["points"]),
      "audit : image sans alt comptée", texts)
check(("Entité", "⚠") in points, "audit : Organization sans sameAs", texts)
check("Product" in rep.get("types_jsonld", []), "audit : types JSON-LD relevés (via @graph)", rep.get("types_jsonld"))
check(("Sitemap", "✓") in points and rep["sitemap"]["dans_robots"], "audit : sitemap déclaré et joignable", texts)
check(rep.get("llms_txt") is False, "audit : llms.txt absent signalé (optionnel)")
verdicts = {v["robot"]: v for v in rep["robots"]["robots"]}
check(verdicts["GPTBot"]["autorise"] is False, "robots.txt : GPTBot bloqué (groupe dédié)")
check(verdicts["PerplexityBot"]["autorise"] and verdicts["OAI-SearchBot"]["autorise"],
      "robots.txt : Allow plus long l'emporte (groupe à deux robots, Crawl-delay au milieu)")
check(verdicts["Googlebot"]["autorise"] and verdicts["Googlebot"]["groupe"] == "*", "robots.txt : repli sur « * »")
check(("Robots (moteurs et IA)", "✓") in points, "audit : robots de recherche IA autorisés sur la page", texts)
groups = audit_site.parse_robots((SITE / "robots.txt").read_text(encoding="utf-8"))
check(audit_site.allowed(groups, "PerplexityBot", "/products/autre.html") == (False, "PerplexityBot"),
      "robots.txt : Disallow appliqué hors de l'exception")
check(audit_site.allowed(groups, "Bingbot", "/cart") == (False, "*"), "robots.txt : Disallow du groupe « * »")
check(audit_site.allowed(groups, "GPTBot", "/robots.txt")[0], "robots.txt toujours lisible")
check(audit_site.allowed(audit_site.parse_robots("User-agent: *\nDisallow: /*.json$\n"), "Googlebot", "/a.json")[0]
      is False, "robots.txt : jokers * et $")
rep4 = audit_site.audit(f"{BASE}/products/groupe.html", timeout=10)
prods = [p for p in rep4["points"] if p["sujet"] == "Product"]
check(len(prods) == 1 and prods[0]["niveau"] == "✓", "audit : ProductGroup (variantes Shopify) lu via hasVariant, "
      "variantes non comptées en double", prods)
check(any(p["sujet"] == "Livraison et retours" and p["niveau"] == "✓" for p in rep4["points"]),
      "audit : livraison et retours au niveau de l'Organization reconnus")
check(any(p["sujet"] == "Entité" and p["niveau"] == "✓" for p in rep4["points"]), "audit : Organization avec sameAs")
rep2 = audit_site.audit(f"{BASE}/products/cache.html", timeout=10)
check(any(p["sujet"] == "Indexation" and p["niveau"] == "✗" for p in rep2["points"]), "audit : noindex repéré")
check(any(p["sujet"] == "Robots (moteurs et IA)" and p["niveau"] == "✗" and "PerplexityBot" in p["constat"]
          for p in rep2["points"]), "audit : robot de recherche IA bloqué sur la page signalé")
rep3 = audit_site.audit("http://127.0.0.1:9/nulle-part", timeout=3)
check(rep3["statut"] is None and rep3["points"][0]["niveau"] == "✗", "audit : site injoignable sans plantage")
c, out = run(SKILL_DIR / "scripts" / "audit_site.py", f"{BASE}/products/lampe.html", "--json", "--timeout", "10")
check(c == 0 and json.loads(out).get("statut") == 200, "audit en ligne de commande (--json)", out[:300])
c, out = run(SKILL_DIR / "scripts" / "audit_site.py", f"{BASE}/products/lampe.html")
check(c == 0 and "Robots (robots.txt, cette page)" in out and "pagespeed.web.dev" in out, "audit : rapport texte",
      out[:300])
c, out = run(SKILL_DIR / "scripts" / "audit_site.py", "--bidule", BASE)
check(c == 1 and "inconnue" in out, "audit : option inconnue refusée", out)
srv.shutdown()

# ------------------------------------------------------------------ 3 bis. relecture des textes de vente
import relire_texte  # noqa: E402

r = relire_texte.relire("<p>Bougie écologique qui soigne vos migraines. La meilleure du marché !</p>", "fiche")
sujets = {(f["niveau"], f["sujet"]) for f in r["points"]}
check(("🔴", "Allégation environnementale générique") in sujets, "relecture : allégation verte générique 🔴", sujets)
check(("🔴", "Promesse de santé") in sujets, "relecture : promesse de santé 🔴", sujets)
check(("🔴", "Superlatif invérifiable") in sujets, "relecture : superlatif invérifiable 🔴", sujets)
check(any(f["sujet"] == "Information attendue absente" and f["extrait"] == "prix" for f in r["points"]),
      "relecture : fiche sans prix signalée")
r = relire_texte.relire("Nos meilleures ventes. Traitement de la commande sous 24 h, bougie anti-stress. Prix : 24,90 €, "
                        "livraison 48 h, retours 30 jours, 8 x 9 cm, en verre.", "fiche")
check(r["rouges"] == 0 and not any(f["sujet"] == "Information attendue absente" for f in r["points"]),
      "relecture : pas de faux positif (meilleures ventes, traitement de la commande, anti-stress)", r["points"])
r = relire_texte.relire("Ma bougie préférée, code promo LUNA10 !", "post")
check(any(f["sujet"] == "Partenariat sans mention" for f in r["points"]), "relecture : partenariat sans « Publicité »")
r = relire_texte.relire("Publicité — ma bougie préférée, code promo LUNA10", "post")
check(not any(f["sujet"] == "Partenariat sans mention" for f in r["points"]), "relecture : mention « Publicité » vue")
(TMP / "fiche.txt").write_text("Crème 100 % naturelle qui guérit l'acné.", encoding="utf-8")
c, out = run(SKILL_DIR / "scripts" / "relire_texte.py", TMP / "fiche.txt")
check(c == 1 and "Promesse de santé" in out, "relecture en ligne de commande : code 1 s'il reste un 🔴", out[:300])
modeles = relire_texte.relire((SKILL_DIR / "assets" / "modeles-textes.md").read_text(encoding="utf-8"), "email")
check(modeles["rouges"] == 0, "modèles de textes : aucun risque juridique 🔴 (ils passent leur propre relecture)",
      [f for f in modeles["points"] if f["niveau"] == "🔴"])
(TMP / "mail.txt").write_text("Bonjour, votre commande est partie ce matin.", encoding="utf-8")
c, out = run(SKILL_DIR / "scripts" / "relire_texte.py", TMP / "mail.txt", "--type", "email")
check(c == 0 and "Information attendue" not in out, "relecture d'un e-mail : pas d'attentes de fiche produit", out)

# ------------------------------------------------------------------ 3 ter. audit du catalogue et flux Merchant Center
import audit_catalogue  # noqa: E402

check(audit_catalogue.gtin_ok("3760000000000") and audit_catalogue.gtin_ok("036000291452")
      and audit_catalogue.gtin_ok("96385074"), "GTIN : clés de contrôle EAN-13, UPC-A et EAN-8 valides")
check(not audit_catalogue.gtin_ok("3760000000001") and not audit_catalogue.gtin_ok("2000000000008")
      and not audit_catalogue.gtin_ok("0000000000000") and not audit_catalogue.gtin_ok("12345"),
      "GTIN : mauvaise clé, code interne (préfixe 2), zéros et longueur refusés")
CSV = TMP / "export.csv"
CSV.write_text("""Handle,Title,Body (HTML),Vendor,Type,Published,Option1 Name,Option1 Value,Variant SKU,Variant Grams,\
Variant Inventory Tracker,Variant Inventory Qty,Variant Price,Variant Compare At Price,Variant Requires Shipping,\
Variant Barcode,Image Src,Image Alt Text,SEO Title,SEO Description,Status
bougie-lavande,Bougie parfumée lavande 200 g,"<p>Bougie coulée à la main en cire de colza, mèche en coton, parfum lavande \
de Provence. Durée de combustion : environ 40 heures. Dimensions : 8 x 9 cm. Livraison en 48 h, retours sous 14 jours. \
Entretien : couper la mèche à 5 mm avant chaque allumage pour une flamme régulière. Matière : verre recyclé.</p>",\
Atelier Test,Bougie,TRUE,Taille,200 g,BL-200,250,shopify,12,24.90,,TRUE,3760000000001,https://cdn.example/b1.jpg,\
Bougie allumée,Bougie lavande 200 g,Bougie artisanale en cire de colza,active
bougie-lavande,,,,,,,350 g,BL-350,400,shopify,0,32.90,,TRUE,3760000000000,https://cdn.example/b2.jpg,Vue de dessus,,,
bougie-lavande,,,,,,,,,,,,,,,,https://cdn.example/b3.jpg,Dans un salon,,,
coque-iphone,PROMO COQUE IPHONE ANTI CHOC -50% LIVRAISON GRATUITE,"<p>100% brand new and high quality. Package \
includes: 1 x case. This case is the best for your phone and will protect it from the drops.</p>",,,TRUE,Title,\
Default Title,,0,shopify,0,9.90,19.90,TRUE,,https://cdn.example/c1.jpg,,,,active
creme-bio,Crème visage,<p>Crème écologique qui guérit l'acné. Produit neutre en carbone.</p>,Atelier Test,Cosmétique,\
TRUE,Title,Default Title,CB-1,50,,,0,,TRUE,,,,,,active
brouillon,Produit brouillon,,Atelier Test,,FALSE,Title,Default Title,BR-1,100,,,10.00,,TRUE,,,,,,draft
""", encoding="utf-8")
prods = audit_catalogue.depuis_csv(str(CSV), "https://boutique.example")
check(len(prods) == 4 and len(prods[0]["variants"]) == 2 and len(prods[0]["images"]) == 3
      and prods[0]["options"][0] == "Taille", "catalogue CSV : lignes regroupées par produit (variantes, images, options)",
      [(p["handle"], len(p["variants"]), len(p["images"])) for p in prods])
res = audit_catalogue.controler(prods)
by = {x["handle"]: {pb["code"] for pb in x["problemes"]} for x in res["resultats"]}
check(res["audites"] == 3 and res["brouillons"] == 1, "catalogue : brouillons ignorés", res["audites"])
check({"gtin-invalide", "titre-variante"} <= by.get("bougie-lavande", set()),
      "catalogue : code-barres invalide et valeur de variante dans le titre", by.get("bougie-lavande"))
check({"titre-promo", "titre-majuscules", "texte-fournisseur", "description-anglais", "prix-barre", "rupture",
       "sans-marque"} <= by.get("coque-iphone", set()), "catalogue : fiche importée d'un fournisseur repérée",
      by.get("coque-iphone"))
check({"texte-juridique", "images-absentes", "prix-zero"} <= by.get("creme-bio", set()),
      "catalogue : allégations interdites, sans image, prix à 0", by.get("creme-bio"))
check(res["resultats"][0]["handle"] == "creme-bio", "catalogue : produits classés du plus urgent au moins urgent")
check(next(x for x in res["par_code"] if x["code"] == "texte-juridique")["produits"] == 1,
      "catalogue : problèmes comptés par produit (3 allégations sur 1 produit = 1 produit)", res["par_code"])
FLUX = TMP / "flux.tsv"
fx = audit_catalogue.flux(prods, str(FLUX), "https://boutique.example")
rows = list(csv.DictReader(FLUX.open(encoding="utf-8"), delimiter="\t"))
row = {x["id"]: x for x in rows}
check(fx["lignes"] == 3 and len(rows) == 3 and ("creme-bio", "aucune image") in fx["exclus"],
      "flux : une ligne par variante en ligne, produit sans image écarté", fx)
v = row.get("BL-350", {})
check(v.get("item_group_id") == "bougie-lavande" and v.get("size") == "350 g" and v.get("title", "").endswith("– 350 g")
      and v.get("availability") == "out_of_stock" and v.get("gtin") == "3760000000000",
      "flux : variante (groupe, taille, titre, rupture, GTIN valide)", v)
check(row.get("BL-200", {}).get("gtin") == "" and row.get("BL-200", {}).get("mpn") == "BL-200",
      "flux : GTIN invalide jamais envoyé (référence vendeur en MPN)", row.get("BL-200"))
cq = row.get("coque-iphone-1", {})
check(cq.get("item_group_id") == "" and cq.get("identifier_exists") == "no" and cq.get("price") == "9.90 EUR",
      "flux : produit simple sans groupe ; sans identifiant → identifier_exists=no ; prix réel (pas le prix barré)", cq)
check(any(h == "coque-iphone" for h, _ in fx["a_revoir"]) and any(h == "bougie-lavande" for h, _ in fx["a_revoir"]),
      "flux : titres promotionnels et prix de variantes à vérifier signalés", fx["a_revoir"])
c, out = run(SKILL_DIR / "scripts" / "audit_catalogue.py", "--csv", CSV, "--site", "https://boutique.example", "--flux",
             TMP / "flux2.tsv")
check(c == 1 and "À corriger en premier" in out and "flux Merchant Center : 3 ligne(s)" in out,
      "audit du catalogue en ligne de commande (code 1 : il reste un 🔴)", out[-400:])
c, out = run(SKILL_DIR / "scripts" / "audit_catalogue.py", "--csv", CSV, "--url", "https://x.example")
check(c == 2 and "l'un des deux" in out, "catalogue : --url et --csv ensemble refusés", out)

ROBOTS = {"txt": "User-agent: *\nDisallow: /checkout\n"}


class Catalogue(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/robots.txt":
            body, ctype = ROBOTS["txt"].encode(), "text/plain"
        elif path == "/products.json":
            page = int(dict(x.split("=") for x in query.split("&") if "=" in x).get("page", 1))
            start, n = (page - 1) * 250, 250 if page == 1 else (10 if page == 2 else 0)
            items = [{"handle": f"p{i}", "title": f"Plaid en lin lavé n° {i}", "body_html": "<p>Plaid en lin.</p>",
                      "vendor": "Maison", "product_type": "Linge", "options": [{"name": "Couleur"}],
                      "variants": [{"id": 1000 + i, "sku": f"S{i}-B", "price": "29.90", "available": True,
                                    "option1": "Bleu", "grams": 300},
                                   {"id": 5000 + i, "sku": f"S{i}-V", "price": "29.90", "available": False,
                                    "option1": "Vert", "grams": 300}],
                      "images": [{"src": f"https://cdn.example/{i}.jpg"}]} for i in range(start, start + n)]
            body, ctype = json.dumps({"products": items}).encode(), "application/json"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


cat_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Catalogue)
threading.Thread(target=cat_srv.serve_forever, daemon=True).start()
CAT = f"http://127.0.0.1:{cat_srv.server_address[1]}"
prods, root, msg = audit_catalogue.depuis_url(CAT, 1000, 10)
check(msg is None and len(prods) == 260 and prods[-1]["handle"] == "p259",
      "catalogue public : /products.json lu page par page (250 + 10)", (msg, len(prods)))
fx = audit_catalogue.flux(prods[:1], str(TMP / "flux3.tsv"))
rows = list(csv.DictReader((TMP / "flux3.tsv").open(encoding="utf-8"), delimiter="\t"))
check(len(rows) == 2 and rows[0]["link"].endswith("/products/p0?variant=1000") and rows[0]["color"] == "Bleu"
      and rows[1]["availability"] == "out_of_stock", "flux depuis le catalogue public : lien de variante, couleur, "
      "disponibilité", rows[:1])
ROBOTS["txt"] = "User-agent: *\nDisallow: /products.json\n"
prods, root, msg = audit_catalogue.depuis_url(CAT, 1000, 10)
check(prods == [] and msg and "robots.txt" in msg, "catalogue public : interdit par robots.txt → respecté", msg)
cat_srv.shutdown()

# ------------------------------------------------------------------ 3 quater. marges par canal et prix testés
c, out = run(UE, "--prix", "39,90", "--cout", "12", "--livraison", "5,50", "--frais-pct", "2,9", "--frais-fixe", "0,30",
             "--canal", "Etsy;commission=6,5;paiement=4;paiement-fixe=0,30;fixe=0,18", "--canal", "Vinted:heures=0,75",
             "--prix-test", "34,90/44,90", "--json")
res = json.loads(out) if c == 0 else {}
canaux = {x["canal"]: x for x in res.get("canaux", [])}
check([x["canal"] for x in res.get("canaux", [])] == ["Vinted", "Boutique", "Etsy"],
      "canaux classés par marge par commande", res.get("canaux"))
check(abs(canaux.get("Etsy", {}).get("marge", 0) - (39.9 - 17.5 - 0.18 - 39.9 * 0.065 - 39.9 * 0.04 - 0.30)) < 1e-9
      and abs(canaux["Etsy"]["frais_canal"] - (39.9 * 0.105 + 0.48)) < 1e-9,
      "canal : commission, frais de paiement et frais fixes de la plateforme à la place de ceux de la boutique", canaux)
check(abs(canaux.get("Vinted", {}).get("marge", 0) - 22.4) < 1e-9
      and abs(canaux["Vinted"]["marge_par_heure"] - 22.4 / 0.75) < 1e-9 and canaux["Boutique"]["marge_par_heure"] is None,
      "canal sans frais vendeur ; heures propres au canal (marge par heure)", canaux.get("Vinted"))
base = 39.9 - 17.5 - (39.9 * 0.029 + 0.3)
essai = 34.9 - 17.5 - (34.9 * 0.029 + 0.3)
check(abs(res.get("prix_test", [{}])[0].get("ventes_relatives", 0) - base / essai) < 1e-9,
      "prix testé : ventes nécessaires pour garder la même marge totale", res.get("prix_test"))
c, out = run(UE, "--prix", "39,90", "--cout", "12", "--livraison", "5,50", "--frais-pct", "2,9", "--frais-fixe", "0,30",
             "--canal", "Etsy;commission=6,5;paiement=4;paiement-fixe=0,30", "--prix-test", "34,90/44,90")
check(c == 0 and "Comparaison des canaux" in out and "il faut + 30 % de ventes pour gagner autant" in out
      and "19 % de ventes en moins suffisent" in out, "comparaison en texte : canaux et prix testés", out[-900:])
c, out = run(UE, "--prix", "10", "--cout", "3", "--canal", "commission=5")
check(c == 1 and "nom du canal" in out, "canal sans nom refusé", out)
c, out = run(UE, "--prix", "10", "--cout", "3", "--canal", "X;taux=5")
check(c == 1 and "inconnu" in out, "clé de canal inconnue refusée", out)
c, out = run(UE, "--prix", "10", "--cout", "3", "--prix-test", "a/b")
check(c == 1 and "invalide" in out, "prix testé illisible refusé", out)

# ------------------------------------------------------------------ 3 quinquies. audit étendu : conformité, pages, vitesse
S2 = TMP / "site2"
(S2 / "products").mkdir(parents=True)
(S2 / "pages").mkdir()
(S2 / "policies").mkdir()
(S2 / "index.html").write_text("""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Maison Test – bougies
artisanales</title><meta name="viewport" content="width=device-width"><link rel="canonical" href="/">
<script src="https://www.googletagmanager.com/gtag/js?id=G-TEST"></script>
<script>fbq('init','123');</script><script src="https://cdn.judge.me/widget.js"></script></head>
<body><h1>Bougies</h1><div class="countdown-timer">Offre se termine dans 02:59:59</div>
<p>Nos bougies écologiques, neutres en carbone.</p>
<footer><a href="/pages/mentions.html">Mentions légales</a> <a href="/pages/cgv.html">CGV</a>
<a href="/pages/retours.html">Retours et remboursements</a> <a href="/pages/confidentialite.html">Confidentialité</a>
<a href="/pages/contact.html">Nous contacter</a> <a href="/">Retour à l'accueil</a>
<a href="https://ec.europa.eu/consumers/odr">Plateforme RLL</a></footer></body></html>""", encoding="utf-8")
(S2 / "pages" / "mentions.html").write_text("<p>Maison Test, EI, 75000 Paris.</p>", encoding="utf-8")
(S2 / "pages" / "cgv.html").write_text("<p>Rétractation : vous disposez de 14 jours.</p><p>Garantie légale de "
                                       "conformité : 2 ans.</p>", encoding="utf-8")
(S2 / "pages" / "retours.html").write_text("<p>Retours sous 30 jours.</p>", encoding="utf-8")
(S2 / "pages" / "confidentialite.html").write_text("<p>RGPD</p>", encoding="utf-8")
(S2 / "pages" / "contact.html").write_text("<form action='/contact'></form>", encoding="utf-8")
(S2 / "shopify.html").write_text('<html lang="fr"><head><title>Boutique Shopify de test</title><script '
                                 'src="https://cdn.shopify.com/s/files/theme.js"></script></head><body><h1>Accueil</h1>'
                                 '<p>Bienvenue. <a href="/renoncer">Renoncer au contrat ici</a></p></body></html>',
                                 encoding="utf-8")
(S2 / "policies" / "refund-policy").write_text("<p>Rétractation de 14 jours. Formulaire type de rétractation ci-dessous."
                                               "</p>", encoding="utf-8")
for name, title, desc, extra in [("a", "Bougie lavande", "Bougie parfumée",
                                  '<script type="application/ld+json">{"@type":"Product","name":"A"}</script>'),
                                 ("b", "Bougie lavande", "Bougie parfumée", ""),
                                 ("c", "Bougie vanille", "", '<meta name="robots" content="noindex">')]:
    (S2 / "products" / f"{name}.html").write_text(f"<html><head><title>{title}</title><meta name='description' "
                                                  f"content='{desc}'>{extra}</head><body><h1>{title}</h1></body></html>",
                                                  encoding="utf-8")
PSI_JSON = json.dumps({
    "lighthouseResult": {"lighthouseVersion": "13.0.0", "categories": {"performance": {"score": 0.42}}, "audits": {
        "largest-contentful-paint": {"numericValue": 5230.0, "score": 0.1},
        "cumulative-layout-shift": {"numericValue": 0.18, "score": 0.4},
        "total-blocking-time": {"numericValue": 640.0, "score": 0.3},
        "first-contentful-paint": {"numericValue": 2100.0, "score": 0.5},
        "render-blocking-insight": {"title": "Requêtes de blocage de l'affichage", "score": 0,
                                    "metricSavings": {"LCP": 1200, "FCP": 900}},
        "image-delivery-insight": {"title": "Améliorer l'envoi des images", "score": 0,
                                   "metricSavings": {"LCP": 2400}, "displayValue": "850 Kio"},
        "uses-text-compression": {"title": "Compression", "score": 1, "details": {"type": "opportunity",
                                                                               "overallSavingsMs": 0}}}},
    "loadingExperience": {"origin_fallback": True, "metrics": {}},
    "originLoadingExperience": {"overall_category": "AVERAGE", "metrics": {
        "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 3100, "category": "AVERAGE"},
        "INTERACTION_TO_NEXT_PAINT": {"percentile": 180, "category": "FAST"},
        "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5, "category": "FAST"}}}}).encode()


class Site2(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(S2), **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/psi"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(PSI_JSON)))
            self.end_headers()
            self.wfile.write(PSI_JSON)
            return
        if self.path.startswith("/policies/"):
            self.path = self.path.split("?")[0]
        return super().do_GET()


srv2 = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site2)
threading.Thread(target=srv2.serve_forever, daemon=True).start()
B2 = f"http://127.0.0.1:{srv2.server_address[1]}"
(S2 / "robots.txt").write_text(f"User-agent: *\nDisallow: /cart\n\nSitemap: {B2}/sitemap.xml\n", encoding="utf-8")
(S2 / "sitemap.xml").write_text(f'<?xml version="1.0"?><sitemapindex><sitemap><loc>{B2}/sitemap_products_1.xml</loc>'
                                f'</sitemap><sitemap><loc>{B2}/sitemap_pages_1.xml</loc></sitemap></sitemapindex>',
                                encoding="utf-8")
(S2 / "sitemap_products_1.xml").write_text(
    '<?xml version="1.0"?><urlset>' + "".join(f"<url><loc>{B2}/products/{n}.html</loc></url>" for n in "abcz")
    + "</urlset>", encoding="utf-8")
(S2 / "sitemap_pages_1.xml").write_text(f'<?xml version="1.0"?><urlset><url><loc>{B2}/pages/cgv.html</loc></url>'
                                        f'<url><loc>{B2}/</loc></url></urlset>', encoding="utf-8")
os.environ["PSI_ENDPOINT"] = B2 + "/psi"
rep = audit_site.audit(B2 + "/", timeout=10, legal=True, pages=10, vitesse=True, pause=0)
pts = {p["sujet"]: p for p in rep["points"]}
lvl = lambda s: pts.get(s, {}).get("niveau")  # noqa: E731
texts = " | ".join(f"{p['niveau']} {p['sujet']} : {p['constat']}" for p in rep["points"])
check(lvl("Conformité : médiateur de la consommation") == "✗" and lvl("Conformité : identité de l'entreprise") == "✗",
      "conformité : médiateur et immatriculation absents → ✗", texts)
check(lvl("Conformité : délai de rétractation") == "✓" and lvl("Conformité : garantie légale de conformité") == "✓"
      and lvl("Conformité : formulaire de rétractation") == "⚠", "conformité : CGV lues (14 jours, garantie, formulaire)",
      texts)
check(lvl("Conformité : plateforme européenne de litiges") == "⚠", "conformité : lien vers la plateforme fermée signalé")
check(lvl("Conformité : cookies") == "⚠" and "Meta Pixel" in pts["Conformité : cookies"]["constat"],
      "conformité : traceurs sans bandeau de consentement", texts)
check(lvl("Conformité : urgence affichée") == "⚠" and lvl("Conformité : avis clients") == "⚠",
      "conformité : minuteur et widget d'avis sans information sur le contrôle", texts)
check(lvl("Conformité : allégation environnementale générique") == "✗", "conformité : allégation verte sur la page",
      texts)
check(lvl("Conformité : fonction de rétractation en ligne") == "⚠" and lvl("Conformité : coordonnées") == "⚠",
      "conformité : fonction « renoncer au contrat ici » et coordonnées introuvables", texts)
check(rep["conformite"]["retours"]["url"].endswith("/pages/retours.html"),
      "conformité : « Retour à l'accueil » n'est pas pris pour la page retours", rep["conformite"].get("retours"))
check(lvl("Site : pages en erreur") == "✗" and "/products/z.html" in pts["Site : pages en erreur"]["constat"]
      and lvl("Site : noindex dans le sitemap") == "✗", "pages du sitemap : erreur 404 et noindex", texts)
check(lvl("Site : titres en double") == "⚠" and lvl("Site : fiches produit sans données Product") == "⚠",
      "pages du sitemap : titres en double, fiches sans Product", texts)
check(len(rep["site"]["pages"]) == 5 and rep["site"]["urls_sitemap"] == 6,
      "pages du sitemap : index lu, page auditée non relue", rep.get("site", {}).get("urls_sitemap"))
check(lvl("Vitesse (laboratoire, mobile)") == "✗" and "score 42/100" in pts["Vitesse (laboratoire, mobile)"]["constat"]
      and "Améliorer l'envoi des images" in pts["Vitesse (laboratoire, mobile)"]["conseil"].split(";")[0],
      "vitesse : score de laboratoire et plus gros gain d'abord", texts)
check(lvl("Vitesse (visiteurs réels, 28 jours)") == "⚠" and "tout le site" in pts["Vitesse (visiteurs réels, 28 jours)"][
    "constat"], "vitesse : données terrain du site quand la page n'en a pas", texts)
md = audit_site.markdown(rep)
check("## Vitesse (mobile)" in md and "| /products/z.html | 404 |" in md and "## ✗ À corriger d'abord" in md,
      "rapport Markdown : priorités, vitesse, pages lues", md[:400])
rep2 = audit_site.audit(B2 + "/shopify.html", timeout=10, legal=True)
p2 = {p["sujet"]: p for p in rep2["points"]}
check(p2.get("Conformité : retours et remboursements", {}).get("niveau") == "⚠"
      and "aucun lien" in p2["Conformité : retours et remboursements"]["constat"],
      "Shopify : page standard /policies/ trouvée sans lien sur la page → à relier", p2.get(
          "Conformité : retours et remboursements"))
check(p2.get("Conformité : fonction de rétractation en ligne", {}).get("niveau") == "✓"
      and p2.get("Conformité : formulaire de rétractation", {}).get("niveau") == "✓",
      "conformité : « Renoncer au contrat ici » et formulaire repérés", [k for k in p2 if "Conformité" in k])
os.environ["PSI_ENDPOINT"] = B2 + "/absent"
rep3 = audit_site.audit(B2 + "/products/a.html", timeout=10, vitesse=True)
check(any(p["sujet"] == "Vitesse" and p["niveau"] == "·" and "pagespeed.web.dev" in p["conseil"] for p in rep3["points"]),
      "vitesse : API indisponible → lien pour mesurer à la main, sans plantage")
os.environ.pop("PSI_ENDPOINT", None)
c, out = run(SKILL_DIR / "scripts" / "audit_site.py", B2 + "/", "--conformite", "--pages", "2", "--pause", "0",
             "--rapport", TMP / "audit.md", "--timeout", "10")
check(c == 0 and (TMP / "audit.md").exists() and "rapport Markdown" in out and "Site : pages lues" in out,
      "audit étendu en ligne de commande avec rapport", out[-300:])
c, out = run(SKILL_DIR / "scripts" / "audit_site.py", B2 + "/", "--pages", "beaucoup")
check(c == 1 and "nombre" in out, "audit : --pages non numérique refusé", out)
srv2.shutdown()

# ------------------------------------------------------------------ 3 sexies. publication par API officielle
import publier  # noqa: E402

APPELS = []


class FakeAPI(http.server.BaseHTTPRequestHandler):
    statut = {"n": 0}

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        APPELS.append(("GET", self.path, self.headers.get("Authorization"), None))
        if self.path.startswith("/pin/v5/boards"):
            return self._send(200, {"items": [{"id": "b1", "name": "Bougies"}]})
        if self.path.startswith("/graph/c42"):
            FakeAPI.statut["n"] += 1
            return self._send(200, {"status_code": "IN_PROGRESS" if FakeAPI.statut["n"] < 2 else "FINISHED"})
        self._send(404, {"message": "inconnu"})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        APPELS.append(("POST", self.path, self.headers.get("Authorization"), raw))
        if self.path == "/pin/v5/pins":
            return self._send(201, {"id": "987"})
        if self.path == "/graph/p1/feed":
            return self._send(200, {"id": "p1_55"})
        if self.path == "/graph/ig1/media":
            return self._send(200, {"id": "c42"})
        if self.path == "/graph/ig1/media_publish":
            return self._send(200, {"id": "m77"})
        if self.path == "/graph/refus/feed":
            return self._send(400, {"error": {"message": "(#200) Permissions error"}})
        self._send(404, {"message": "inconnu"})


api = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
threading.Thread(target=api.serve_forever, daemon=True).start()
APIB = f"http://127.0.0.1:{api.server_address[1]}"
publier.PINTEREST, publier.GRAPH = APIB + "/pin/v5", APIB + "/graph"
os.environ["PINTEREST_TOKEN"] = "pin-" + "x" * 30
os.environ["META_TOKEN"] = "meta-" + "y" * 30
PUB = [SKILL_DIR / "scripts" / "publier.py"]
penv = dict(os.environ, PUBLIER_API_PINTEREST=APIB + "/pin/v5", PUBLIER_API_GRAPH=APIB + "/graph")
c, out = run(*PUB, "pinterest", "--tableau", "b1", "--titre", "Bougie lavande 200 g", "--texte",
             "Coulée à la main, cire de colza, 40 h de combustion.", "--lien", "https://boutique.example/p/bougie",
             "--image", "https://cdn.example/b.jpg", env=penv)
post = [a for a in APPELS if a[0] == "POST" and a[1] == "/pin/v5/pins"]
body = json.loads(post[-1][3]) if post else {}
check(c == 0 and "pinterest.com/pin/987" in out and post and post[-1][2] == "Bearer " + os.environ["PINTEREST_TOKEN"]
      and body.get("board_id") == "b1" and body.get("media_source", {}).get("source_type") == "image_url",
      "Pinterest : épingle créée par l'API v5 (jeton en en-tête, tableau, image, lien)", out)
check(os.environ["PINTEREST_TOKEN"] not in out, "le jeton n'apparaît jamais dans la sortie")
journal = (Path(os.environ["BRAIN_HOME"]) / "acces" / "publications.jsonl")
check(journal.exists() and '"pinterest"' in journal.read_text(encoding="utf-8"), "publication journalisée")
c, out = run(*PUB, "pinterest-tableaux", env=penv)
check(c == 0 and "b1  Bougies" in out, "Pinterest : liste des tableaux", out)
c, out = run(*PUB, "facebook", "--page", "p1", "--texte", "Nouvel arrivage : bougies au parfum de figue.", "--lien",
             "https://boutique.example/c/nouveautes", env=penv)
fb = [a for a in APPELS if a[1] == "/graph/p1/feed"]
check(c == 0 and "p1_55" in out and fb and "access_token=" in fb[-1][3] and "link=" in fb[-1][3],
      "Page Facebook : post avec lien", out)
c, out = run(*PUB, "facebook", "--page", "refus", "--texte", "Bonjour à tous", env=penv)
check(c == 1 and "Permissions error" in out and "rien de publié" in out, "erreur de l'API rapportée, rien de publié",
      out)
FakeAPI.statut["n"] = 0
r = publier.instagram(os.environ["META_TOKEN"], "ig1", "Le geste qui allume la bougie.", None,
                      "https://cdn.example/r.mp4", False, attente=0)
seq = [a[1].split("?")[0] for a in APPELS if a[1].startswith("/graph/ig1") or a[1].startswith("/graph/c42")]
check(r.get("id") == "m77" and seq[-4:] == ["/graph/ig1/media", "/graph/c42", "/graph/c42", "/graph/ig1/media_publish"],
      "Instagram : conteneur Reel, attente du traitement, publication", seq[-5:])
c, out = run(*PUB, "instagram", "--compte", "ig1", "--texte", "Crème écologique qui soigne l'acné", "--image",
             "https://cdn.example/i.jpg", env=penv)
check(c == 4 and "relecture" in out and not any("Crème" in (a[3] or "") for a in APPELS),
      "texte avec un 🔴 : rien n'est envoyé", out)
c, out = run(*PUB, "instagram", "--compte", "ig1", "--texte", "Ma bougie préférée, code promo LUNA10", "--image",
             "https://cdn.example/i.jpg", env=penv)
check(c == 4 and "Publicité" in out, "contenu promotionnel sans mention : rien n'est envoyé", out)
c, out = run(*PUB, "pinterest", "--tableau", "b1", "--titre", "T", "--texte", "Texte", "--lien",
             "http://boutique.example", "--image", "https://cdn.example/b.jpg", env=penv)
check(c == 2 and "https" in out, "lien non https refusé", out)
for _ in range(publier.PLAFOND["facebook"]):
    publier.journaliser({"date": publier._dt.datetime.now().isoformat(), "plateforme": "facebook", "id": "x"})
c, out = run(*PUB, "facebook", "--page", "p1", "--texte", "Encore un post", env=penv)
check(c == 4 and "plafond du jour" in out, "plafond quotidien : la suite attend demain", out)
c, out = run(*PUB, "facebook", "--page", "p1", "--texte", "Encore un post", "--essai", env=penv)
check(c == 0 and '"essai": true' in out, "--essai : requête montrée, rien n'est envoyé, plafond ignoré", out)
env_sans = {k: v for k, v in penv.items() if k not in ("PINTEREST_TOKEN", "META_TOKEN")}
c, out = run(*PUB, "pinterest-tableaux", env=env_sans)
check(c == 3 and "acces pinterest" in out, "sans accès : l'utilisateur le saisit une fois dans son terminal", out)
c, out = run(*PUB, "acces", "pinterest", env=penv)
check(c == 2 and "terminal" in out, "accès jamais saisi hors d'un vrai terminal (pas par la conversation)", out)
quand = (publier._dt.datetime.now() + publier._dt.timedelta(days=2)).replace(microsecond=0).isoformat(timespec="minutes")
c, out = run(*PUB, "facebook", "--page", "p1", "--texte", "Atelier ouvert samedi", "--quand", quand, "--essai", env=penv)
check(c == 0 and '"published": "false"' in out and "scheduled_publish_time" in out,
      "Page Facebook : publication programmée (published=false + horodatage)", out)
c, out = run(*PUB, "facebook", "--page", "p1", "--texte", "Trop tôt", "--quand",
             publier._dt.datetime.now().isoformat(timespec="minutes"), "--essai", env=penv)
check(c == 2 and "10 minutes et 75 jours" in out, "programmation hors des bornes de Facebook refusée", out)
c, out = run(*PUB, "instagram", "--compte", "ig1", "--texte", "Bougie", "--image", "https://cdn.example/i.png",
             env=penv)
check(c == 2 and "JPEG" in out, "Instagram : image non JPEG refusée avant l'envoi", out)
EPI = TMP / "epingles.json"
EPI.write_text(json.dumps([
    {"titre": "Bougie lavande 200 g", "texte": "Coulée à la main en cire de colza.", "image": "https://cdn.example/1.jpg",
     "tableau": "Bougies", "lien": "https://boutique.example/p/1", "date": "2026-10-25T18:00:00",
     "mots_cles": ["bougie", "lavande"]},
    {"titre": "Bougie miracle", "texte": "Elle guérit l'insomnie.", "image": "https://cdn.example/2.jpg",
     "tableau": "Bougies"},
    {"titre": "Sans image", "texte": "…", "tableau": "Bougies"}]), encoding="utf-8")
c, out = run(*PUB, "pinterest-csv", "--entree", EPI, "--sortie", TMP / "epingles.csv", env=penv)
rows = list(csv.reader((TMP / "epingles.csv").open(encoding="utf-8"))) if (TMP / "epingles.csv").exists() else []
check(c == 0 and len(rows) == 2 and rows[0][:3] == ["Title", "Media URL", "Pinterest board"]
      and rows[1][2] == "Bougies" and rows[1][7] == "bougie, lavande" and "écartée n° 2" in out and "écartée n° 3" in out,
      "Pinterest : fichier d'import en masse (relu ; allégation de santé et épingle sans image écartées)", out)
api.shutdown()
os.environ.pop("PINTEREST_TOKEN", None)
os.environ.pop("META_TOKEN", None)

# ------------------------------------------------------------------ 4. livraison : plugin (brain publish)
dest = TMP / "plugin"
files = publish.build(dest, "Lucas", "proprietaire/depot")
check("skills/ecommerce/SKILL.md" in files and "skills/ecommerce/scripts/audit_site.py" in files,
      "brain publish : le cerveau e-commerce part dans le plugin")
check((dest / "skills" / "ecommerce" / "SKILL.md").read_bytes() == (SKILL_DIR / "SKILL.md").read_bytes(),
      "brain publish : SKILL.md copié à l'identique")
check(not any("__pycache__" in f or f.endswith(".cerveau") for f in files), "brain publish : ni cache ni marque")
plugin_json = json.loads((dest / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
check("e-commerce" in plugin_json["keywords"] and "e-commerce" in plugin_json["description"],
      "plugin.json : le cerveau e-commerce est annoncé")
check("/cerveau:ecommerce" in (dest / "README.md").read_text(encoding="utf-8"), "README du plugin : skill présentée")
repo_plugin = json.loads((CODE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
for key in ("version", "description", "keywords"):
    check(plugin_json[key] == repo_plugin[key], f"plugin.json du dépôt à jour ({key})")
gen = json.loads((dest / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
repo_market = json.loads((CODE / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
check(gen["metadata"]["version"] == repo_market["metadata"]["version"] and gen["plugins"] == repo_market["plugins"],
      "marketplace.json du dépôt à jour (version, description)")
readme = (dest / "README.md").read_text(encoding="utf-8").replace("proprietaire/depot", "destingood/cerveau-claude")
check(readme == (CODE / "README.md").read_text(encoding="utf-8"), "README.md du dépôt identique à celui de publish")
try:
    publish.build(CODE)
    refused = False
except RuntimeError:
    refused = True
check(refused and (CODE / "brain.py").exists(), "brain publish refuse d'écrire dans le dossier du code")
check(publish.secrets_in(dest) == [], "plugin construit : ni secret ni adresse e-mail", publish.secrets_in(dest))

# ------------------------------------------------------------------ 5. livraison : self-update (cerveau classique)
code = selfupdate._code_files(CODE)
check("skills/ecommerce/SKILL.md" in code and "skills/ecommerce/scripts/unit_economics.py" in code,
      "self-update : les fichiers du skill font partie du code déployé")
check(not any(k.startswith("skills/brain/") for k in code), "self-update : skills/brain reste écrite par install")

# ------------------------------------------------------------------ 6. livraison : installation classique
home = Path(os.environ["CLAUDE_CONFIG_DIR"])
lines = install.sync_skills()
target = home / "skills" / "ecommerce"
check((target / "SKILL.md").read_bytes() == (SKILL_DIR / "SKILL.md").read_bytes() and (target / ".cerveau").exists(),
      "installation classique : skill posée dans ~/.claude/skills/ecommerce avec sa marque", lines)
check(install.sync_skills() == [] and install.sync_skills(quick=True) == [], "deuxième passage : rien à refaire")
stage = home / ".cerveau-skills"
check(not [p.name for p in (home / "skills").iterdir() if p.name.startswith(".")]
      and not (stage / "ecommerce.tmp").exists() and not (stage / "ecommerce.old").exists(),
      "aucun dossier de travail laissé dans ~/.claude/skills ni dans la zone de préparation")
mine = home / "skills" / "maison"
mine.mkdir(parents=True)
(mine / "SKILL.md").write_text("---\nname: maison\n---\n", encoding="utf-8")
(target / "references" / "00-decollage.md").write_text("abîmé", encoding="utf-8")
(target / "vieux.md").write_text("reste d'une ancienne version", encoding="utf-8")
check(install.sync_skills(quick=True) == [], "démarrage (quick) : même version → rien n'est relu")
lines = install.sync_skills()
check((target / "references" / "00-decollage.md").read_bytes()
      == (SKILL_DIR / "references" / "00-decollage.md").read_bytes() and not (target / "vieux.md").exists(),
      "copie installée abîmée → réparée par brain install (fichiers en trop retirés)", lines)
marque = json.loads((target / ".cerveau").read_text(encoding="utf-8"))
marque["version"] = "0.0.1"
(target / ".cerveau").write_text(json.dumps(marque), encoding="utf-8")
install.sync_skills(quick=True)
check(json.loads((target / ".cerveau").read_text(encoding="utf-8"))["version"] != "0.0.1",
      "démarrage (quick) : nouvelle version du code → marque mise à jour")
autre = home / "skills" / "ecommerce-perso"
shutil.copytree(target, autre)
(autre / ".cerveau").unlink()
removed = install.sync_skills(uninstall=True)
check(not target.exists() and mine.exists() and autre.exists(),
      "désinstallation : seules les skills posées par le cerveau sont retirées", removed)

# un cerveau classique complet (arbre sans .claude-plugin) : le démarrage de session pose la skill tout seul
classic = TMP / "classique"
classic.mkdir()
shutil.copy2(CODE / "brain.py", classic / "brain.py")
shutil.copytree(CODE / "brainkit", classic / "brainkit", ignore=shutil.ignore_patterns("__pycache__"))
shutil.copytree(CODE / "skills", classic / "skills", ignore=shutil.ignore_patterns("__pycache__"))
env = {k: v for k, v in os.environ.items() if k != "BRAIN_HOME"}
env["CLAUDE_CONFIG_DIR"] = str(TMP / "claude-classique")
r = subprocess.run([sys.executable, "-I", "-S", str(classic / "brain.py"), "hook", "session-start"],
                   input=json.dumps({"session_id": "t1", "cwd": str(TMP)}).encode(), capture_output=True, env=env,
                   cwd=str(TMP), timeout=120)
posee = TMP / "claude-classique" / "skills" / "ecommerce" / "SKILL.md"
check(r.returncode == 0 and posee.exists(), "cerveau classique : le démarrage de session pose /ecommerce",
      r.stdout.decode("utf-8", "replace")[-300:] + r.stderr.decode("utf-8", "replace")[-300:])

# session cloud ouverte sur le wiki : les consignes donnent le chemin du skill
env = dict(os.environ, CERVEAU_CLOUD="1")
c, out = run("-I", "-S", "-c", "import sys; sys.path.insert(0, sys.argv[1]); from brainkit import plugin; "
             "print(plugin.instructions())", CODE, env=env)
check(c == 0 and "skills/ecommerce/SKILL.md" in out.replace("\\", "/"), "session cloud : chemin du skill e-commerce "
      "dans les consignes", out[-400:])

# la skill /brain du dépôt est bien celle qu'écrit le cerveau
# (le test tourne avec un BRAIN_HOME temporaire : la commande du cerveau y pointe, on la ramène à celle des amis)
check((CODE / "skills" / "brain" / "SKILL.md").read_text(encoding="utf-8")
      == install.SKILL.replace(install.CMD, 'python "$HOME/.claude/brain/brain.py"'),
      "skills/brain/SKILL.md identique à install.SKILL")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
