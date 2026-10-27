"""Vérifications du suivi des boutiques (`brain boutique`, brainkit/boutique.py) : fiche privée, plan daté, relevés de
la semaine avec test statistique, diagnostic, canaux, audits gardés en historique, bilan, sauvegarde, outils MCP —
dans des dossiers temporaires, jamais sur la vraie mémoire, avec un faux site local.

Lancement : python tests/test_boutique.py   (sortie : « N vérifications OK, M échec(s) »)"""
import datetime as dt
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-boutique-test-"))
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD"):
    os.environ.pop(k, None)
os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "claude")
os.environ["BRAIN_HOME"] = str(TMP / "brain")
CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
OK, FAIL = [], []


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def brain(*args, env=None):
    (TMP / "work").mkdir(exist_ok=True)
    r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), *map(str, args)], capture_output=True,
                       cwd=str(TMP / "work"), env=env or os.environ.copy(), timeout=180)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def graph():
    return json.loads((TMP / "brain" / "graph.json").read_text(encoding="utf-8"))["nodes"]


def shop_file(slug="atelier-lumiere"):
    return json.loads((TMP / "brain" / "boutiques" / f"{slug}.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ faux site (audit)
SITE = TMP / "site"
(SITE / "pages").mkdir(parents=True)
(SITE / "products").mkdir()
(SITE / "index.html").write_text("""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>Atelier Lumière – bougies coulées à la main</title><meta name="viewport" content="width=device-width">
<meta name="description" content="Bougies artisanales en cire de colza, livraison 48 h, retours 30 jours, paiement sécurisé.">
<link rel="canonical" href="/"></head><body><h1>Bougies artisanales</h1>
<footer><a href="/pages/mentions.html">Mentions légales</a> <a href="/pages/cgv.html">CGV</a></footer></body></html>""",
                                  encoding="utf-8")
(SITE / "pages" / "mentions.html").write_text("<html><body>Atelier Lumière, SIREN 123 456 789, hébergé par Hôte "
                                              "SAS.</body></html>", encoding="utf-8")
(SITE / "pages" / "cgv.html").write_text("<html><body>Rétractation : 14 jours. Garantie légale de conformité. "
                                         "Médiateur de la consommation : Médiateur Test.</body></html>",
                                         encoding="utf-8")
for name in ("a", "b"):
    (SITE / "products" / f"{name}.html").write_text(f"<html><head><title>Bougie {name}</title></head><body><h1>B</h1>"
                                                    "</body></html>", encoding="utf-8")


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SITE), **kw)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
(SITE / "robots.txt").write_text(f"User-agent: *\nDisallow: /cart\n\nSitemap: {BASE}/sitemap.xml\n", encoding="utf-8")
(SITE / "sitemap.xml").write_text(f'<?xml version="1.0"?><urlset><url><loc>{BASE}/products/a.html</loc></url>'
                                  f'<url><loc>{BASE}/products/b.html</loc></url></urlset>', encoding="utf-8")

# ------------------------------------------------------------------ 1. ajouter
c, out = brain("boutique")
check(c == 0 and "Aucune boutique suivie" in out, "liste vide : la commande pour commencer est donnée", out)
c, out = brain("boutique", "ajouter", "Atelier Lumière", "--url", BASE + "/", "--type", "fait-main", "--chemin",
               "0euro", "--marge-commande", "12,5", "--plateforme", "site statique")
check(c == 0 and "boutique suivie" in out, "ajouter : boutique suivie", out)
s = shop_file()
check(s["type"] == "createur" and s["chemin"] == "0euro" and s["marge_commande"] == 12.5,
      "ajouter : type (alias fait-main → createur), chemin et marge enregistrés", s)
fiche = graph().get(s.get("fiche") or "", {})
check(fiche.get("type") == "fact" and (fiche.get("meta") or {}).get("prive") is True
      and "boutique" in fiche.get("tags", []), "ajouter : fiche contexte en mémoire, marquée privée", fiche)
c, out = brain("boutique", "ajouter", "Atelier Lumière")
check(c != 0 and "déjà suivie" in out, "ajouter deux fois : refusé", out)
c, out = brain("boutique", "ajouter", "Autre", "--type", "inconnu")
check(c != 0 and "type inconnu" in out, "type inconnu refusé", out)

# privé : la fiche ne part jamais dans le cerveau commun
from brainkit import commun  # noqa: E402
check(commun.verdict(fiche, {})[0] is False, "fiche de boutique jamais partagée (cerveau commun)", commun.verdict(fiche, {}))

# ------------------------------------------------------------------ 2. plan daté
c, out = brain("boutique", "plan", "atelier", "--debut", "01/10/2026")
s = shop_file()
todos = [graph()[p["id"]] for p in s["plan"]]
dues = sorted(t["meta"]["due"] for t in todos)
check(c == 0 and len(todos) == 22, f"plan : 22 à-faire pour une boutique de créateur ({len(todos)})", out)
check(dues[0] == "2026-10-01" and dues[-1] == "2026-12-30", "plan : de J0 (01/10) à J90 (30/12)", dues[:2] + dues[-2:])
check(all(t["type"] == "todo" and t["meta"].get("prive") and t["meta"].get("boutique") == "atelier-lumiere"
          for t in todos), "plan : à-faire privés, rattachés à la boutique")
check(any("Etsy" in t["title"] for t in todos), "plan : canal n° 1 du type (Etsy pour un créateur)")
c, out = brain("boutique", "plan", "atelier")
check(c != 0 and "--force" in out, "plan déjà en cours : il faut --force", out)
old_ids = [p["id"] for p in s["plan"]]
c, out = brain("boutique", "plan", "atelier", "--force", "--court", "--debut", "01/10/2026")
s = shop_file()
g = graph()
check(c == 0 and len(s["plan"]) == 17, f"plan --court : J0 à J14 seulement ({len(s['plan'])})", out)
check(all(g[i]["status"] == "archived" and g[i]["meta"].get("annule") for i in old_ids),
      "plan --force : l'ancien plan est archivé (marqué annulé)")

# ------------------------------------------------------------------ 3. relevés de la semaine
c, out = brain("boutique", "kpi", "atelier", "--semaine", "21/09/2026", "--sessions", "1000", "--ajouts", "60",
               "--checkouts", "30", "--commandes", "20", "--ca", "700", "--heures", "10")
check(c == 0 and "semaine du 21/09" in out and "2,00 %" in out and "première semaine" in out,
      "kpi : première semaine = base de mesure", out)
check("marge 250 € · 10,0 h → 25,00 € par heure" in out, "kpi : marge par heure (marge par commande × commandes)", out)
c, out = brain("boutique", "kpi", "atelier", "--semaine", "28/09/2026", "--sessions", "1 000", "--ajouts", "62",
               "--commandes", "21", "--ca", "735,50")
check(c == 0 and "pas significatif" in out and "la semaine d'avant" in out, "kpi : +0,1 pt → pas significatif", out)
c, out = brain("boutique", "kpi", "atelier", "--semaine", "05/10/2026", "--sessions", "1000", "--ajouts", "90",
               "--commandes", "45", "--ca", "1600", "--heures", "6", "--canal", "tiktok:400:10:5", "--canal",
               "pinterest:300:5:1", "--note", "vidéo reprise par un créateur")
check(c == 0 and "variation réelle (p < 0,001)" in out and "les 2 semaines d'avant" in out,
      "kpi : 4,5 % contre 2,05 % → variation réelle (test de deux proportions)", out)
check("n° 1 : pinterest" in out, "kpi : canaux classés par marge par heure (pinterest 62,50 €/h > tiktok 25 €/h)", out)
c, out = brain("boutique", "kpi", "atelier", "--semaine", "06/10/2026", "--sessions", "1000", "--commandes", "44")
s = shop_file()
check(c == 0 and len(s["kpi"]) == 3 and s["kpi"][-1]["commandes"] == 44,
      "kpi : un second relevé de la même semaine remplace le premier", [k["semaine"] for k in s["kpi"]])
c, out = brain("boutique", "kpi", "atelier", "--semaine", "12/10/2026", "--sessions", "10", "--commandes", "20")
check(c != 0 and "incohérent" in out, "kpi incohérent refusé (plus de commandes que de sessions)", out)
c, out = brain("boutique", "kpi", "atelier", "--semaine", "12/10/2026", "--sessions", "abc", "--commandes", "1")
check(c != 0 and "invalide" in out, "kpi : nombre illisible refusé", out)
obs = (TMP / "brain" / "journal" / "observations.json")
check(obs.exists() and "Atelier Lumière semaine du" in obs.read_text(encoding="utf-8"),
      "kpi : observation 🟡 ajoutée au journal")

from brainkit import boutique  # noqa: E402

p, why = boutique.ztest(20, 1000, 21, 1000)
check(p is not None and 0.8 < p < 0.95, f"z-test : 2,0 % contre 2,1 % → p ≈ 0,87 ({p})")
check(boutique.ztest(1, 20, 0, 20)[0] is None, "z-test : trop peu d'événements → pas de conclusion")
check(boutique.ztest(5, 100, 5, 0)[0] is None, "z-test : pas de semaine de comparaison")
shop = {"marge_commande": 10, "seuils": {}}
diag = lambda e: boutique.diagnostic(e, shop)[0][1]  # noqa: E731
check("le trafic" in diag({"sessions": 50, "commandes": 1}), "diagnostic : moins de 100 sessions → trafic")
check("l'offre ou la fiche" in diag({"sessions": 1000, "ajouts": 20, "commandes": 5}),
      "diagnostic : 2 % d'ajouts → offre ou fiche produit")
check("le paiement" in diag({"sessions": 1000, "ajouts": 80, "checkouts": 40, "commandes": 10}),
      "diagnostic : 25 % des paiements aboutissent → paiement")
check("panier et paiement" in diag({"sessions": 1000, "ajouts": 80, "commandes": 10}),
      "diagnostic : 12,5 % des ajouts deviennent des commandes → panier")
check("pas de goulot" in diag({"sessions": 1000, "ajouts": 80, "checkouts": 40, "commandes": 30}),
      "diagnostic : entonnoir sain → amplifier")
check("marge par commande nulle" in boutique.diagnostic({"sessions": 1000, "commandes": 30},
                                                        {"marge_commande": 0})[0][1],
      "diagnostic : marge nulle signalée en premier")
check(boutique.parse_canal("Instagram Reels:300:4:2,5") == ("instagram-reels", {"sessions": 300, "commandes": 4,
                                                                                 "heures": 2.5}),
      "canal : nom:sessions:commandes:heures (virgule décimale)")
try:
    boutique.parse_canal("tiktok:300")
    refused = False
except ValueError:
    refused = True
check(refused, "canal incomplet refusé")
check(boutique.week_of("15/10/2026") == "2026-10-12" and boutique.week_of(None, dt.date(2026, 10, 18)) == "2026-10-05",
      "semaine : lundi de la date donnée ; par défaut, la dernière semaine complète")
check(boutique._portee("✗ Conformité : médiateur") == "legal" and boutique._portee("⚠ Site : titres") == "pages"
      and boutique._portee("✗ Vitesse (laboratoire)") == "vitesse" and boutique._portee("⚠ H1 : x") == "base",
      "audit : chaque point est rattaché à la partie de l'audit qui l'a produit")

# ------------------------------------------------------------------ 4. réglages
c, out = brain("boutique", "regler", "atelier", "seuil.ajout=8", "marge=15", f"url={BASE}/")
s = shop_file()
check(c == 0 and s["seuils"]["ajout"] == 8 and s["marge_commande"] == 15, "regler : seuil et marge", out)
c, out = brain("boutique", "regler", "atelier", "couleur=bleu")
check(c != 0 and "inconnu" in out, "regler : clé inconnue refusée", out)

# ------------------------------------------------------------------ 5. audits gardés en historique
c, out = brain("boutique", "audit", "atelier", "--conformite", "--pages", "2", "--timeout", "10")
s = shop_file()
a1 = s["audits"][-1] if s.get("audits") else {}
check(c == 0 and "Conformité : délai de rétractation" in out and "Site : pages lues" in out,
      "audit --conformite --pages : pages légales et pages du sitemap lues", out[-600:])
check(a1.get("portee") == ["base", "legal", "pages"], "audit : portée gardée dans l'historique", a1.get("portee"))
check(any("Conformité : formulaire de rétractation" in x for x in a1.get("points", [])),
      "audit : formulaire de rétractation manquant relevé", a1.get("points"))
c, out = brain("boutique", "audit", "atelier", "--timeout", "10")
check(c == 0 and "Depuis l'audit du" in out and "(sur les points vérifiés les deux fois)" in out
      and "corrigé : ⚠ Conformité" not in out and "corrigé : ✗ Conformité" not in out,
      "audit simple après un audit complet : la conformité non revérifiée n'est pas « corrigée »", out[-700:])
rapport = TMP / "audit.md"
c, out = brain("boutique", "audit", BASE + "/", "--conformite", "--rapport", rapport, "--timeout", "10")
check(c == 0 and rapport.exists() and "# Audit du site" in rapport.read_text(encoding="utf-8")
      and len(shop_file()["audits"]) == 2, "audit d'une adresse non suivie : rapport Markdown, pas d'historique",
      out[-300:])

# ------------------------------------------------------------------ 6. bilan et liste
md = TMP / "bilan.md"
c, out = brain("boutique", "bilan", "atelier", "--md", md)
text = md.read_text(encoding="utf-8") if md.exists() else ""
check(c == 0 and all(h in text for h in ("## Chiffres", "## Plan", "## Audits", "## Trois priorités")),
      "bilan : chiffres, plan, audits et trois priorités (fichier Markdown)", out[-500:])
check("| 05/10 |" in text and "| 21/09 |" in text, "bilan : tableau des semaines relevées", text[:800])
c, out = brain("boutique", "liste")
check(c == 0 and "Atelier Lumière" in out and "plan 0/17" in out and "audit du" in out, "liste : état de la boutique",
      out)

# ------------------------------------------------------------------ 6 bis. la vue 3D montre la boutique et le cerveau e-commerce
PROJET = TMP / "Boutique Atelier Lumière"  # le dossier du site, cartographié : son projet porte le nom de la boutique
PROJET.mkdir()
(PROJET / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
brain("map", PROJET)
c, out = brain("viz")
html = (TMP / "brain" / "cerveau.html").read_text(encoding="utf-8") if (TMP / "brain" / "cerveau.html").exists() else ""
try:
    data = json.JSONDecoder().raw_decode(html[html.index('{"generated"'):].replace("<\\/", "</"))[0]
except ValueError:
    data = {"nodes": [], "edges": [], "comms": [], "stats": {}}
vnodes = {n["id"]: n for n in data["nodes"]}
shop_node = vnodes.get("boutique:atelier-lumiere", {})
check(c == 0 and shop_node.get("t") == "boutique" and "1 000" not in shop_node.get("body", "x")
      and "plan : 17 étapes" in shop_node.get("body", ""), "vue 3D : la boutique suivie est un nœud (chiffres, plan)",
      shop_node)
check(vnodes.get("skill:ecommerce", {}).get("t") == "skill" and sum(1 for i in vnodes if i.startswith("skill:ecommerce:"))
      >= 20, "vue 3D : le cerveau e-commerce, ses fiches et ses outils", [i for i in vnodes if i.startswith("skill:")][:3])
links = {(e["s"], e["t"]) for e in data["edges"]}
fiche_id = shop_file()["fiche"]
check(("boutique:atelier-lumiere", fiche_id) in links and ("boutique:atelier-lumiere", "skill:ecommerce") in links
      and sum(1 for s_, t in links if t == "boutique:atelier-lumiere") >= 17,
      "vue 3D : boutique reliée à sa fiche, au cerveau e-commerce et à son plan")
check(data["stats"].get("shops") == 1 and data["stats"].get("skills") == 1
      and data["stats"].get("memories") == sum(1 for n in data["nodes"] if n["t"] not in ("project", "skill", "boutique")),
      "vue 3D : compteurs (boutiques, compétences ; les souvenirs ne les comptent pas)", data["stats"])
check({"Cerveau e-commerce", "Boutiques suivies"} <= {c_["label"] for c_ in data["comms"]},
      "vue 3D : groupes « Cerveau e-commerce » et « Boutiques suivies » dans la légende")
menu = {v["label"]: v for v in data.get("views", [])}
eco, shop_view = menu.get("Cerveau e-commerce", {}), menu.get("Atelier Lumière", {})
check(eco.get("icon") == "🛒" and "skill:ecommerce" in (eco.get("members") or []) and len(eco["members"]) >= 20,
      "menu des vues : entrée « 🛒 Cerveau e-commerce » (ses fiches et ses outils)", list(menu))
projet_id = next((n["id"] for n in data["nodes"] if n["t"] == "project" and "Atelier Lumière" in n["title"]), None)
check(shop_view.get("icon") == "🏪" and projet_id and {"boutique:atelier-lumiere", projet_id, fiche_id, "skill:ecommerce"}
      <= set(shop_view.get("members") or []) and ("boutique:atelier-lumiere", projet_id) in links,
      "menu des vues : une entrée par boutique, reliée au projet qui porte son nom", (projet_id, shop_view))
html2d = (TMP / "brain" / "cerveau-2d.html").read_text(encoding="utf-8")
check('value="v:${i}"' in html and 'startsWith("v:")' in html and "memoryView(new Set(g.members))" in html2d,
      "menu des vues : branché dans la vue 3D et dans la vue 2D")
vide = {**os.environ, "BRAIN_HOME": str(TMP / "cerveau-sans-boutique")}
c, out = brain("viz", env=vide)
html_vide = (TMP / "cerveau-sans-boutique" / "cerveau.html").read_text(encoding="utf-8") if c == 0 else ""
check("Aucune boutique suivie pour l'instant" in html_vide and "Cerveau e-commerce" in html_vide,
      "menu des vues sans boutique suivie : il dit où elle apparaîtra", out[-300:])

# ------------------------------------------------------------------ 6 ter. panels de clients simulés
PANEL = CODE / "skills" / "ecommerce" / "scripts" / "panel_clients.py"
PD = TMP / "panel"
PD.mkdir()
(PD / "a.md").write_text("Bougie 180 g — 24,90 €.", encoding="utf-8")
(PD / "b.md").write_text("Bougie 180 g, 40 h, livraison offerte dès 35 €.", encoding="utf-8")


def panel_script(*args):
    r = subprocess.run([sys.executable, str(PANEL), *map(str, args)], capture_output=True, timeout=60)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


panel_script("preparer", "--nom", "Bougie", "--stimulus", PD / "a.md", "--variante", PD / "b.md", "--nb", "8",
             "--lots", "1", "--graine", "5", "--dossier", PD / "p")
pj = json.loads((PD / "p" / "panel.json").read_text(encoding="utf-8"))
(PD / "p" / "t1-lot1.json").write_text(json.dumps([
    {"id": p["id"], "variante": v, "intention": 2 if v == "A" else 4,
     "objections": ["livraison"] if v == "A" else (["confiance"] if k % 2 else []), "question": "Quelle durée ?"}
    for k, p in enumerate(pj["personas"]) for v in "AB"]), encoding="utf-8")
panel_script("reponses", PD / "p")
c, out = brain("boutique", "panel", "atelier")
check(c == 0 and "Aucun panel simulé" in out, "panel : aucun pour l'instant, la marche à suivre est donnée", out)
c, out = brain("boutique", "panel", "atelier", "--importer", PD / "p")
s = shop_file()
check(c == 0 and "panel S1 gardé" in out and "B devant A" in out and "--applique S1 --variante B" in out
      and "Quelle durée ?" in out, "panel importé (synthèse recalculée depuis le dossier) : verdict et suite", out)
check(len(s.get("panels") or []) == 1 and s["panels"][0]["gagnante"] == "B" and s["panels"][0]["metrique"] == "ajout"
      and s["panels"][0]["objections"] == [["confiance", 50]], "panel gardé dans le suivi (privé)", s.get("panels"))
panel_script("synthese", PD / "p")
c, out = brain("boutique", "panel", "atelier", "--importer", PD / "p" / "synthese.json")
check(c == 0 and "panel S1 mis à jour" in out and len(shop_file()["panels"]) == 1,
      "panel réimporté (synthese.json) : même identifiant, pas de doublon", out)
c, out = brain("boutique", "panel", "atelier", "--applique", "1", "--le", "2026-10-05")
check(c == 0 and "S1 : variante B en ligne depuis le 05/10" in out and "attend une semaine complète" in out,
      "panel : variante mise en ligne (la semaine du 05/10 n'a pas d'ajouts relevés → on attend)", out)
c, out = brain("boutique", "panel", "atelier", "--applique", "S7")
check(c != 0 and "panel inconnu" in out, "panel : identifiant inconnu refusé", out)
c, out = brain("boutique", "panel", "atelier", "--applique", "S1", "--variante", "Z")
check(c != 0 and "--variante" in out, "panel : variante inconnue refusée", out)
c, out = brain("boutique", "panel", "atelier", "--importer", TMP / "rien.json")
check(c != 0 and "ni dossier de panel" in out, "panel : fichier qui n'est pas un panel refusé", out)
c, out = brain("boutique", "bilan", "atelier")
check(c == 0 and "## Panels simulés" in out and "S1 (" in out, "bilan : section des panels simulés", out[-800:])
c, out = brain("boutique", "liste")
check(c == 0 and "1 panel(s) simulé(s)" in out, "liste : nombre de panels", out)

rec = {"applique": "B", "applique_le": "2026-10-12", "actuelle": "A", "metrique": "ajout",
       "variantes": {"A": {"moyenne": 2.0}, "B": {"moyenne": 3.5}}}


def semaines(*xs):
    return {"kpi": [{"semaine": w, "sessions": n, "ajouts": a} for w, n, a in xs]}


AVANT = (("2026-09-28", 1000, 30), ("2026-10-05", 1000, 30))
verdict = lambda shop, r=rec: boutique.verdict_panel(shop, r)  # noqa: E731
juste = verdict(semaines(*AVANT, ("2026-10-12", 1000, 55)))
check(juste[0] == "juste" and "3,00 % → 5,50 %" in juste[1] and "p < 0,001" in juste[1],
      "verdict : ajouts au panier 3 % → 5,5 %, le panel voyait B devant A → vu juste", juste)
check(verdict(semaines(*AVANT, ("2026-10-12", 1000, 12)))[0] == "faux", "verdict : baisse réelle → contredit")
check(verdict(semaines(*AVANT, ("2026-10-12", 1000, 33)))[0] == "bruit", "verdict : 3 % → 3,3 % → pas encore tranché")
check(verdict(semaines(*AVANT))[0] == "attente", "verdict : pas encore de semaine après la mise en ligne")
check(verdict(semaines(("2026-10-12", 1000, 55)))[0] == "attente", "verdict : pas de semaine avant → pas de base")
check(verdict(semaines(*AVANT, ("2026-10-12", 1000, 55)), dict(rec, applique_le="2026-10-14"))[0] == "attente",
      "verdict : la semaine coupée par la mise en ligne ne compte ni avant ni après")
check(verdict(semaines(*AVANT, ("2026-10-12", 1000, 55)), dict(rec, applique="A"))[0] == "na",
      "verdict : version actuelle gardée → rien à comparer")
check(verdict(semaines(*AVANT, ("2026-10-12", 1000, 55)), dict(rec, metrique=None))[0] == "na",
      "verdict : idée de produit ou contenu → pas de mesure automatique")
plat = dict(rec, variantes={"A": {"moyenne": 2.0}, "B": {"moyenne": 2.1}})
check(verdict(semaines(*AVANT, ("2026-10-12", 1000, 55)), plat)[0] == "faux",
      "verdict : le panel ne voyait pas d'écart, il y en a un → contredit")
fiab = boutique.fiabilite(dict(semaines(*AVANT, ("2026-10-12", 1000, 55)), panels=[rec, plat]))
check(fiab and "1 vu juste sur 2 vérifiés" in fiab, "fiabilité du panel : 1 vu juste sur 2", fiab)

# ------------------------------------------------------------------ 7. sauvegarde et restauration
c, out = brain("backup", "--to", TMP / "sauvegardes")
zips = sorted((TMP / "sauvegardes").glob("cerveau-*.zip"))
names = zipfile.ZipFile(zips[-1]).namelist() if zips else []
check(c == 0 and "boutiques/atelier-lumiere.json" in names, "sauvegarde : suivi des boutiques compris", names)
(TMP / "brain" / "boutiques" / "atelier-lumiere.json").unlink()
c, out = brain("backup", "--restore", zips[-1] if zips else "absent.zip")
check(c == 0 and (TMP / "brain" / "boutiques" / "atelier-lumiere.json").exists() and len(shop_file()["kpi"]) == 3,
      "restauration : le suivi de la boutique revient", out)

# ------------------------------------------------------------------ 8. outils MCP
req = "\n".join(json.dumps(x) for x in (
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "boutique_etat", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "boutique_etat",
                                                                    "arguments": {"boutique": "atelier"}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "boutique_kpi", "arguments": {
        "boutique": "atelier", "semaine": "12/10/2026", "sessions": 900, "commandes": 30, "ajouts": 70}}},
    {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "boutique_audit", "arguments": {
        "boutique": BASE + "/", "pages": 1}}})) + "\n"
r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "mcp"], input=req.encode(), capture_output=True,
                   cwd=str(TMP / "work"), env=os.environ.copy(), timeout=120)
resp = {x["id"]: x for x in (json.loads(y) for y in r.stdout.decode("utf-8").splitlines() if y.strip())}
names = [t["name"] for t in resp.get(2, {}).get("result", {}).get("tools", [])]
check({"boutique_etat", "boutique_ajouter", "boutique_plan", "boutique_kpi", "boutique_audit"} <= set(names),
      "MCP : outils boutique listés", names)
txt = lambda i: resp.get(i, {}).get("result", {}).get("content", [{}])[0].get("text", "")  # noqa: E731
check("Atelier Lumière" in txt(3), "MCP : boutique_etat sans boutique → la liste", txt(3)[:300])
check("## Trois priorités" in txt(4), "MCP : boutique_etat d'une boutique → le bilan", txt(4)[:300])
check("semaine du 12/10" in txt(5) and len(shop_file()["kpi"]) == 4, "MCP : boutique_kpi enregistre la semaine",
      txt(5)[:300])
check("Site : pages lues" in txt(6), "MCP : boutique_audit avec pages du sitemap", txt(6)[-400:])

srv.shutdown()
from brainkit.common import remove_tree  # noqa: E402

if not remove_tree(TMP, wait=60):  # tâches de fond du cerveau testé : on attend qu'elles aient fini d'y écrire
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
