"""Vérifications du cerveau e-commerce (skills/ecommerce) et de sa livraison par le cerveau (plugin, self-update,
installation classique) — dans des dossiers temporaires, jamais sur la vraie mémoire.

Lancement : python tests/test_ecommerce.py   (sortie : « N vérifications OK, M échec(s) »)"""
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
