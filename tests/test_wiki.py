"""Vérifications du cerveau en wiki (wikistore.py, wiki.py) — dans un dossier temporaire, jamais sur la vraie mémoire.

Lancement : python tests/test_wiki.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-wiki-test-"))
os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "claude")
os.environ["BRAIN_HOME"] = str(TMP / "brain")
os.environ.pop("BRAIN_WIKI", None)
os.environ.pop("CLAUDE_CODE_REMOTE", None)
CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
WORK = TMP / "work"
WORK.mkdir(parents=True)
os.chdir(WORK)

from brainkit import wiki, wikistore as ws  # noqa: E402
from brainkit.common import GRAPH_FILE, write_json  # noqa: E402
from brainkit.store import Brain  # noqa: E402

OK, FAIL = [], []


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {detail}" if detail else ""))


def brain(*args, inp=None, cwd=None):
    r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), *args], input=(inp or "").encode("utf-8"),
                       capture_output=True, cwd=str(cwd or WORK), env=os.environ.copy(), timeout=120)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def page(rel):
    return (WIKI / rel).read_text(encoding="utf-8")


# ------------------------------------------------------------------ 1. un cerveau classique de départ
PROJ = WORK / "boutique"
PROJ.mkdir()
classic = {"version": 1, "created": "2026-09-01T10:00:00", "usage_since": "2026-09-01T10:00:00", "edges": [], "nodes": {}}


def node(nid, t, title, body="", **kw):
    n = {"id": nid, "type": t, "title": title, "body": body, "tags": kw.pop("tags", []), "project": kw.pop("project", None),
         "importance": kw.pop("importance", 3), "created": "2026-09-02T09:15:42", "updated": "2026-09-03T18:20:05",
         "hits": kw.pop("hits", 0), "last_hit": None, "source": kw.pop("source", "claude"),
         "status": kw.pop("status", "active"), "meta": kw.pop("meta", {})}
    n.update(kw)
    classic["nodes"][nid] = n


node("lucas", "user", "Lucas, e-commerçant", "Vend du thé matcha en ligne.", source="utilisateur", importance=5, hits=7, used=3)
node("tutoiement", "feedback", "Toujours tutoyer", "Pourquoi : préférence de Lucas.", importance=4)
node("boutique", "project", "Boutique", "Shopify de thé.", meta={"path": str(PROJ), "stack": "Shopify"})
node("choix-hebergeur", "decision", "Choix de l'hébergeur: OVH", "On reste chez OVH. Pourquoi : prix.", project="boutique",
     tags=["hebergement"], meta={"keys": "serveur, hosting"})
node("stats-robots", "learning", "Stats Shopify polluées par robots",
     "92 % de bots : filtrer. Voir [[choix-hebergeur]] et [[boutique|la boutique]].", project="boutique", tags=["shopify", "stats"])
node("relancer-fournisseur", "todo", "Relancer le fournisseur", "Atelier Sato.", project="boutique", meta={"due": "2026-11-10"})
node("prix-matcha-v1", "fact", "Prix du matcha", "12 € les 30 g.", project="boutique", status="archived",
     meta={"valid_to": "2026-09-20", "superseded_by": "prix-matcha"})
node("prix-matcha", "fact", "Prix du matcha", "14 € les 30 g.", project="boutique", importance=4)
classic["edges"] = [
    {"from": "stats-robots", "to": "choix-hebergeur", "rel": "relates", "created": "2026-09-03"},
    {"from": "stats-robots", "to": "boutique", "rel": "relates", "created": "2026-09-03"},
    {"from": "prix-matcha", "to": "prix-matcha-v1", "rel": "supersedes", "created": "2026-09-20"},
    {"from": "choix-hebergeur", "to": "tutoiement", "rel": "depends_on", "created": "2026-09-04"},
    {"from": "relancer-fournisseur", "to": "lucas", "rel": "relates", "created": "2026-09-05"},
]
GRAPH_FILE.parent.mkdir(parents=True, exist_ok=True)
write_json(GRAPH_FILE, classic)
check(ws.resolve()[0] == "classic", "mode classique au départ")

# ------------------------------------------------------------------ 2. init + migration
WIKI = TMP / "monwiki"
rep = wiki.init(WIKI, push=False)
print("\n".join(rep))
check((WIKI / ws.MARKER).is_file() and (WIKI / "CLAUDE.md").is_file() and (WIKI / "log.md").is_file(), "squelette créé")
check(ws.resolve() == ("wiki", WIKI.resolve()), "mode wiki après init", str(ws.resolve()))
check(any(TMP.joinpath("brain").glob("graph.avant-wiki-*.json")), "copie du cerveau classique gardée")
b = Brain.load()
check(set(b.nodes) == set(classic["nodes"]), "tous les souvenirs migrés", str(set(classic["nodes"]) ^ set(b.nodes)))
n = b.nodes["choix-hebergeur"]
check(n["title"] == "Choix de l'hébergeur: OVH" and n["project"] == "boutique" and n["tags"] == ["hebergement"],
      "titre, projet, étiquettes", json.dumps(n, ensure_ascii=False))
check((n.get("meta") or {}).get("keys") == "serveur, hosting", "mots-clés gardés")
check(b.nodes["relancer-fournisseur"]["meta"].get("due") == "2026-11-10", "échéance gardée")
check(b.nodes["lucas"].get("hits") == 7 and b.nodes["lucas"].get("used") == 3, "compteurs repris du cache")
check(b.nodes["prix-matcha-v1"]["status"] == "archived" and b.nodes["prix-matcha-v1"]["meta"].get("superseded_by") == "prix-matcha",
      "archivé + remplacé par", json.dumps(b.nodes["prix-matcha-v1"], ensure_ascii=False))
rels = {(e["from"], e["to"], e["rel"]) for e in b.edges}
for e in classic["edges"]:
    check((e["from"], e["to"], e["rel"]) in rels, f"lien {e['from']} -{e['rel']}-> {e['to']}")
files = b.data["wiki"]["files"]
check(files["choix-hebergeur"]["path"] == "wiki/Décisions/Choix de l'hébergeur OVH.md", "nom de fichier sûr",
      files["choix-hebergeur"]["path"])
check(files["prix-matcha"]["path"] == "wiki/Faits/Prix du matcha.md", "page active : nom propre", files["prix-matcha"]["path"])
check(files["prix-matcha-v1"]["path"].startswith("archive/Faits/Prix du matcha ("), "archivée : rangée dans archive/ avec sa date",
      files["prix-matcha-v1"]["path"])
txt = page(files["stats-robots"]["path"])
check("[[Choix de l'hébergeur OVH]]" in txt and "[[Boutique|la boutique]]" in txt, "liens [[id]] → [[Nom de page]]", txt)
check('projet: "[[Boutique]]"' in txt, "propriété projet en lien")
txt = page(files["choix-hebergeur"]["path"])
check('depend_de: ["[[Toujours tutoyer]]"]' in txt, "relation typée en propriété", txt)
check('aliases: ["Choix de l\'hébergeur: OVH"]' in txt, "alias = vrai titre quand le nom de fichier diffère", txt)
check("[[Choix de l" not in page(files["relancer-fournisseur"]["path"]) and 'lie_a: ["[[Lucas, e-commerçant]]"]'
      in page(files["relancer-fournisseur"]["path"]), "lien sans [[ ]] dans le texte → lie_a")
idx = page("index.md")
check("[[Prix du matcha]]" in idx and "Prix du matcha (" not in idx, "index : pages actives seulement")
check("migration" in page("log.md"), "journal : entrée de migration")
cs = json.loads(page(".claude/settings.json"))
check(set(cs.get("hooks", {})) == {"SessionStart", "UserPromptSubmit", "Stop", "PreCompact", "PostCompact", "SessionEnd"}
      and "enabledPlugins" not in cs and (WIKI / ".claude/cerveau.py").is_file(),
      "squelette : hooks du dépôt + lanceur cloud (pas de plugin déclaré, ignoré par le cloud)", json.dumps(cs))

# ------------------------------------------------------------------ 3. relecture sans changement : rien n'est réécrit
before = {p: p.stat().st_mtime_ns for p in WIKI.rglob("*.md")}
time.sleep(0.05)
with Brain.edit() as b2:
    b2.touch(["lucas"])  # compteur seulement
after = {p: p.stat().st_mtime_ns for p in WIKI.rglob("*.md")}
check(before == after, "un compteur ne réécrit aucune page")
check(Brain.load().nodes["lucas"]["hits"] == 8, "compteur gardé dans le cache")


# ------------------------------------------------------------------ 4. commandes du cerveau en mode wiki
code, out = brain("add", "-t", "concept", "-T", "Dropshipping", "-b", "Vendre sans stock. Lié à [[Boutique]].", "-p", "none",
                  "--tags", "ecommerce")
check(code == 0 and (WIKI / "wiki/Concepts/Dropshipping.md").is_file(), "add → page dans wiki/Concepts", out)
code, out = brain("edit", "dropshipping", "-T", "Dropshipping (vente sans stock)")
f = Brain.load().data["wiki"]["files"]["dropshipping"]["path"]
check(f == "wiki/Concepts/Dropshipping (vente sans stock).md" and not (WIKI / "wiki/Concepts/Dropshipping.md").exists(),
      "titre changé → fichier renommé", f + out)
code, out = brain("add", "-t", "learning", "-T", "Marges du dropshipping", "-b", "Voir [[Dropshipping (vente sans stock)]].",
                  "-p", "none")
code, out = brain("edit", "dropshipping", "-T", "Dropshipping")
txt = page(Brain.load().data["wiki"]["files"]["marges-du-dropshipping"]["path"])
check("[[Dropshipping]]" in txt and "vente sans stock)]]" not in txt, "renommage → liens des autres pages suivis", txt)
code, out = brain("rm", "marges-du-dropshipping")
f = Brain.load().data["wiki"]["files"]["marges-du-dropshipping"]["path"]
check(f.startswith("archive/Apprentissages/") and (WIKI / f).is_file(), "rm → page archivée (déplacée)", f)
code, out = brain("edit", "marges-du-dropshipping", "--unarchive")
f = Brain.load().data["wiki"]["files"]["marges-du-dropshipping"]["path"]
check(f == "wiki/Apprentissages/Marges du dropshipping.md", "désarchiver → retour dans wiki/", f)
code, out = brain("add", "-t", "fact", "-T", "Prix du matcha", "-b", "15 € les 30 g désormais.", "-p", "boutique",
                  "--replaces", "prix-matcha")
b = Brain.load()
new = [n for n in b.nodes.values() if n["title"] == "Prix du matcha" and n["status"] == "active"]
old = b.nodes["prix-matcha"]
check(len(new) == 1 and old["status"] == "archived", "remplacement : l'ancien archivé, le nouveau actif", out)
fp = b.data["wiki"]["files"]
check(fp[new[0]["id"]]["path"] == "wiki/Faits/Prix du matcha.md" and fp["prix-matcha"]["path"].startswith("archive/"),
      "le nouveau prend le nom propre", json.dumps({k: fp[k]["path"] for k in fp if "prix" in k}, ensure_ascii=False))
check("15 €" in page("wiki/Faits/Prix du matcha.md"), "contenu du nouveau dans la page")
code, out = brain("rm", "marges-du-dropshipping", "--purge")
check("marges-du-dropshipping" not in Brain.load().nodes and not (WIKI / "wiki/Apprentissages/Marges du dropshipping.md").exists(),
      "purge → page supprimée", out)
code, out = brain("link", "dropshipping", "lucas", "-r", "about")
check('a_propos_de: ["[[Lucas, e-commerçant]]"]' in page("wiki/Concepts/Dropshipping.md"), "link -r about → propriété", out)
code, out = brain("q", "dropshipping")
check("Dropshipping" in out, "q trouve la page", out)
code, out = brain("show", "Dropshipping")
check("Dropshipping" in out and code == 0, "show par nom de page", out)

# ------------------------------------------------------------------ 5. Obsidian : modifier, créer, supprimer à la main
p = WIKI / "wiki/Concepts/Dropshipping.md"
p.write_text(p.read_text(encoding="utf-8").replace("Vendre sans stock.", "Vendre sans stock (modifié dans Obsidian)."),
             encoding="utf-8")
check("modifié dans Obsidian" in Brain.load().nodes["dropshipping"]["body"], "modification à la main relue")
(WIKI / "wiki/Entités").mkdir(exist_ok=True)
(WIKI / "wiki/Entités/Atelier Sato.md").write_text("# Atelier Sato\n\nFournisseur de matcha à Uji. Voir [[Boutique]].\n",
                                                   encoding="utf-8")
b = Brain.load()
sato = b.nodes.get("atelier-sato")
check(sato is not None and sato["type"] == "entity", "page écrite à la main = nouveau nœud (type d'après le dossier)",
      str(sato))
check(any(e["from"] == "atelier-sato" and e["to"] == "boutique" for e in b.edges), "ses [[liens]] deviennent des liens")
check(b.get("Atelier Sato") is sato, "get() par nom de page")
(WIKI / "wiki/Entités/Atelier Sato.md").unlink()
check("atelier-sato" not in Brain.load().nodes, "page supprimée à la main → nœud retiré")
code, out = brain("edit", "dropshipping", "-a", "Ajout par le cerveau.")
txt = page("wiki/Concepts/Dropshipping.md")
check("modifié dans Obsidian" in txt and "Ajout par le cerveau." in txt, "écriture du cerveau après une modif Obsidian : rien perdu", txt)
mv = WIKI / "wiki/Concepts/Dropshipping.md"
(WIKI / "wiki/Concepts/Sous-dossier").mkdir()
mv.rename(WIKI / "wiki/Concepts/Sous-dossier/Dropshipping.md")
code, out = brain("edit", "dropshipping", "-i", "4")
check((WIKI / "wiki/Concepts/Sous-dossier/Dropshipping.md").is_file() and not mv.exists(),
      "rangement fait dans Obsidian respecté", out)

# ------------------------------------------------------------------ 6. wiki introuvable : lecture seule
cfg = json.loads((TMP / "brain" / "config.json").read_text(encoding="utf-8"))
real = cfg["wiki"]["path"]
cfg["wiki"]["path"] = str(TMP / "absent")
(TMP / "brain" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
code, out = brain("q", "dropshipping")
check("Dropshipping" in out, "wiki absent : lecture depuis le cache", out)
code, out = brain("add", "-t", "fact", "-T", "Ne doit pas s'écrire", "-b", "x", "-p", "none")
check(code != 0 and "introuvable" in out and "Traceback" not in out, "wiki absent : écriture refusée (message clair)", out)
cfg["wiki"]["path"] = real
(TMP / "brain" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


# ------------------------------------------------------------------ 7. sources : texte, fichier, page web, déjà dans raw/
article = ("# Le matcha de cérémonie\n\nLe matcha de cérémonie vient d'Uji, près de Kyoto. L'Atelier Sato le cultive à "
           "l'ombre trois semaines. L'Atelier Sato vend aussi du hojicha. Le dropshipping de matcha marche mal : "
           "la fraîcheur compte. Voir aussi Shopify.\n")
code, out = brain("wiki", "add", "-", "-T", "Le matcha de cérémonie", "--url", "https://exemple.fr/matcha", inp=article)
check(code == 0 and "page à remplir" in out, "wiki add - : source rangée + plan", out)
raws = sorted((WIKI / "raw").glob("*.md"))
check(len(raws) == 1 and "source: \"https://exemple.fr/matcha\"" in raws[0].read_text(encoding="utf-8"),
      "raw/ : fichier daté avec son adresse", str(raws))
check("Dropshipping" in out and "atelier sato" in out.lower(), "plan : pages concernées et noms repérés", out)
b = Brain.load()
src = [n for n in b.nodes.values() if n["type"] == "source"]
check(len(src) == 1 and src[0]["meta"].get("brut", "").startswith("raw/") and src[0]["meta"].get("sha1"),
      "page Sources avec brut + sha1", json.dumps(src[0] if src else {}, ensure_ascii=False))
code, out = brain("wiki", "add", "-", "-T", "Doublon", inp=article)
check("déjà connue" in out and len(list((WIKI / "raw").glob("*.md"))) == 1, "même contenu : pas de doublon", out)
code, out = brain("wiki", "pending")
check("à remplir" in out, "pending : page Sources à remplir", out)
(WIKI / "raw" / "Article clippé.md").write_text("---\ntitle: \"Guide Shopify\"\nsource: \"https://ex.fr/shopify\"\n"
                                               "author: [\"[[Jean Dupont]]\"]\n---\n\nShopify en 10 étapes.\n", encoding="utf-8")
code, out = brain("wiki", "pending")
check("raw/Article clippé.md" in out, "pending : fichier déposé dans raw/ (Web Clipper)", out)
code, out = brain("wiki", "add", "raw/Article clippé.md")
b = Brain.load()
g = [n for n in b.nodes.values() if n["type"] == "source" and n["title"] == "Guide Shopify"]
check(code == 0 and g and g[0]["meta"].get("url") == "https://ex.fr/shopify" and g[0]["meta"].get("auteur") == "Jean Dupont",
      "source déjà dans raw/ : titre, adresse, auteur du Web Clipper", out + json.dumps(g[0] if g else {}, ensure_ascii=False))
check(len(list((WIKI / "raw").glob("*.md"))) == 2, "fichier de raw/ référencé, pas copié")
pdf = WORK / "rapport.pdf"
pdf.write_bytes(b"%PDF-1.4 faux pdf")
code, out = brain("wiki", "add", str(pdf))
check(code == 0 and "texte non extrait" in out and any(p.suffix == ".pdf" for p in (WIKI / "raw").iterdir()),
      "PDF : copié dans raw/, à lire directement", out)
import http.server, threading  # noqa: E401
html = ("<html><head><title>Article de test</title></head><body><nav>menu</nav><article><h1>Thé vert</h1>"
        "<p>Le <b>sencha</b> est un thé vert japonais. " + "Phrase de remplissage pour avoir un article. " * 12 +
        "</p><ul><li>Uji</li><li>Shizuoka</li></ul><p><a href='/plus'>en savoir plus</a></p></article>"
        "<footer>pied</footer></body></html>").encode("utf-8")


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
env_np = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
env_np["NO_PROXY"] = "127.0.0.1,localhost"
r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "wiki", "add", f"http://127.0.0.1:{srv.server_port}/a"],
                   capture_output=True, cwd=str(WORK), env=env_np, timeout=60)
out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
srv.shutdown()
web = [p for p in (WIKI / "raw").glob("*Article de test*.md")]
wtxt = web[0].read_text(encoding="utf-8") if web else ""
check(r.returncode == 0 and web and "# Thé vert" in wtxt and "**sencha**" in wtxt and "- Uji" in wtxt and "menu" not in wtxt
      and "pied" not in wtxt, "page web → Markdown (article gardé, menu et pied écartés)", out + wtxt[:400])
code, out = brain("wiki", "add", "https://www.youtube.com/watch?v=abc")
check(code != 0 and "transcription" in out, "YouTube : demande la transcription", out)

# ------------------------------------------------------------------ 8. lint, journal, index
code, out = brain("add", "-t", "topic", "-T", "Thé japonais", "-b", "Synthèse. Voir [[Uji]] et [[Kyoto]] et [[Dropshipping]].",
                  "-p", "none")
code, out = brain("wiki", "lint")
check("[[Uji]]" in out and "Pages à créer" in out, "lint : liens vers rien = pages à créer", out)
check("Sources à ingérer" in out and "sans `resume:`" in out, "lint : sources en attente, pages sans résumé", out)
code, out = brain("wiki", "log", "ingest", "Le matcha de cérémonie", "pages touchées : [[Thé japonais]]")
check(code == 0 and "## [" in page("log.md").split("migration")[1] and "- pages touchées : [[Thé japonais]]" in page("log.md"),
      "log : entrée ajoutée en bas", out)
code, out = brain("wiki", "log")
check("ingest | Le matcha de cérémonie" in out, "log : dernières entrées", out)
idx = page("index.md")
check("## Sujets (1)" in idx and "[[Thé japonais]]" in idx and "## Sources" in idx, "index.md régénéré avec les nouveaux types", idx)
code, out = brain("wiki")
check("Pages :" in out and "Sources brutes" in out, "wiki (état)", out)

# ------------------------------------------------------------------ 9. git : commit, pull, push vers un dépôt distant
REMOTE = TMP / "distant.git"
subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(REMOTE)], check=True)
for args in (["init", "-q", "-b", "main"], ["config", "user.email", "test@example.com"], ["config", "user.name", "Test"],
             ["remote", "add", "origin", str(REMOTE)]):
    subprocess.run(["git", "-C", str(WIKI), *args], check=True)
code, out = brain("wiki", "sync")
check(code == 0 and "✓ commit" in out and "✓ push" in out, "sync : commit + push", out)
CLONE = TMP / "autre-pc"
subprocess.run(["git", "clone", "-q", str(REMOTE), str(CLONE)], check=True)
check((CLONE / "wiki/Sujets/Thé japonais.md").is_file(), "le dépôt distant a les pages")
(CLONE / "wiki/Sujets/Thé japonais.md").write_text(
    (CLONE / "wiki/Sujets/Thé japonais.md").read_text(encoding="utf-8") + "\nAjout depuis un autre poste.\n", encoding="utf-8")
for args in (["config", "user.email", "t@example.com"], ["config", "user.name", "T"], ["commit", "-qam", "autre poste"],
             ["push", "-q"]):
    subprocess.run(["git", "-C", str(CLONE), *args], check=True)
code, out = brain("wiki", "sync", "--no-push")
check("✓ pull" in out and "Ajout depuis un autre poste." in Brain.load().get("Thé japonais")["body"],
      "sync : pull → modification d'un autre poste relue", out)
code, out = brain("wiki", "status")
check("Git :" in out and str(REMOTE) in out, "status : dépôt et adresse", out)

# ------------------------------------------------------------------ 10. hooks : démarrage, rappel, fin de session
def hook(event, payload, cwd=None):
    r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "hook", event], input=json.dumps(payload).encode(),
                       capture_output=True, cwd=str(cwd or WORK), env=os.environ.copy(), timeout=120)
    return r.stdout.decode("utf-8", "replace")


o = hook("session-start", {"session_id": "s1", "cwd": str(WORK)})
check("📚 Le cerveau vit dans le wiki" in o and "à ingérer" in o, "démarrage : ligne du wiki", o[-600:])
o = hook("prompt", {"session_id": "s9", "cwd": str(WORK), "prompt": "parle-moi de la synthèse japonaise sur Kyoto et Uji"})
check("Thé japonais" in o, "rappel : page du wiki remontée", o)
check("Thé japonais" in hook("session-start", {"session_id": "s3", "cwd": str(WORK)}), "index de démarrage : section wiki")
o = hook("session-start", {"session_id": "s2", "cwd": str(WIKI)})
check("wiki" not in [n["id"] for n in Brain.load().projects()], "le dossier du wiki n'est pas cartographié comme projet")
with Brain.edit() as b2:
    b2.add("learning", "Astuce de fin de session", "Une page créée pendant la session.")
hook("session-end", {"session_id": "s1", "cwd": str(WORK)})
check("session | hors projet" in page("log.md"), "fin de session : entrée « session » au journal", page("log.md")[-400:])

# ------------------------------------------------------------------ 11. MCP
req = "\n".join(json.dumps(x) for x in (
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "wiki_add_source", "arguments": {
        "title": "Conversation sur le sencha", "text": "Le sencha se boit à 70 °C.", "format": "conversation"}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "wiki_status", "arguments": {}}})) + "\n"
r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "mcp"], input=req.encode(), capture_output=True,
                   cwd=str(WORK), env=os.environ.copy(), timeout=60)
resp = [json.loads(x) for x in r.stdout.decode("utf-8").splitlines() if x.strip()]
names = [t["name"] for t in resp[1]["result"]["tools"]]
check("wiki_add_source" in names and "wiki_lint" in names, "MCP : outils du wiki listés", str(names))
check(not resp[2]["result"]["isError"] and "page à remplir" in resp[2]["result"]["content"][0]["text"],
      "MCP : wiki_add_source", json.dumps(resp[2], ensure_ascii=False)[:400])
check("Pages :" in resp[3]["result"]["content"][0]["text"], "MCP : wiki_status")

# ------------------------------------------------------------------ 12. session cloud : wiki trouvé depuis le dossier courant
FRESH = TMP / "cloud"
env2 = dict(os.environ, CLAUDE_CONFIG_DIR=str(FRESH / "claude"), BRAIN_HOME=str(FRESH / "brain"), CLAUDE_CODE_REMOTE="true")
r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "q", "thé japonais"], capture_output=True,
                   cwd=str(CLONE), env=env2, timeout=60)
out = r.stdout.decode("utf-8", "replace")
check("Thé japonais" in out, "cloud : cerveau vide + dossier du wiki → le wiki sert de mémoire", out + r.stderr.decode()[-300:])
r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "wiki", "sync", "--auto"], capture_output=True,
                   cwd=str(CLONE), env=env2, timeout=60)
check("session cloud" in r.stdout.decode("utf-8", "replace"), "cloud : pas de synchro automatique")
OTHER = TMP / "ami"
env3 = dict(os.environ, CLAUDE_CONFIG_DIR=str(OTHER / "claude"), BRAIN_HOME=str(OTHER / "brain"))
subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "add", "-t", "fact", "-T", "Souvenir d'un ami", "-b", "x",
                "-p", "none"], capture_output=True, cwd=str(OTHER.parent), env=env3, timeout=60)
r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "q", "souvenir ami"], capture_output=True,
                   cwd=str(CLONE), env=env3, timeout=60)
out = r.stdout.decode("utf-8", "replace")
g3 = json.loads((OTHER / "brain" / "graph.json").read_text(encoding="utf-8"))
check("Souvenir d'un ami" in out and not g3.get("wiki") and "souvenir-d-un-ami" in g3["nodes"],
      "cerveau classique avec souvenirs : un wiki dans le dossier courant ne le remplace pas", out)


# ------------------------------------------------------------------ 13. le reste du cerveau en mode wiki
for args in (["doctor"], ["consolidate"], ["dream", "--no-apply"], ["report"], ["fiche"], ["viz"], ["export"], ["stats"],
             ["todo"], ["ls"], ["context"], ["recall", "thé japonais Kyoto"], ["history"]):
    code, out = brain(*args)
    check(code == 0 and "Traceback" not in out, f"`{' '.join(args)}` en mode wiki", out[-500:])
code, out = brain("doctor")
check("✓ wiki :" in out, "doctor : ligne du wiki", out)
code, out = brain("dream", "--no-apply")
check("Wiki —" in (TMP / "brain" / "REVE.md").read_text(encoding="utf-8"), "rêve : section du wiki", out)
code, out = brain("export", "--vault", str(TMP / "coffre"))
check(code != 0 and "déjà dans un wiki" in out, "export --vault refusé en mode wiki", out)
n_before = len(Brain.load().nodes)
code, out = brain("add", "-t", "fact", "-T", "Fait à annuler", "-b", "temporaire", "-p", "none")
check((WIKI / "wiki/Faits/Fait à annuler.md").is_file(), "page créée avant restauration")
from brainkit import history  # noqa: E402
history.snapshot("test", force=True)  # état contenant la page
code, out = brain("rm", "fait-a-annuler", "--purge")
code, out = brain("restore", "1")
check(code == 0 and (WIKI / "wiki/Faits/Fait à annuler.md").is_file() and "fait-a-annuler" in Brain.load().nodes,
      "restore : la page revient dans le wiki", out)


# ------------------------------------------------------------------ 14. propriétés du wiki depuis la ligne de commande
code, out = brain("add", "-t", "concept", "-T", "Ombrage du thé", "-b", "Trois semaines à l'ombre.", "-p", "none",
                  "--resume", "Cultiver à l'ombre augmente la L-théanine.", "--sources", "Le matcha de cérémonie",
                  "--domaine", "recherche, business")
txt = page("wiki/Concepts/Ombrage du thé.md")
check('resume: "Cultiver à l\'ombre augmente la L-théanine."' in txt and 'sources: ["[[Le matcha de cérémonie]]"]' in txt
      and 'domaine: ["recherche", "business"]' in txt, "add --resume --sources --domaine", txt)
code, out = brain("edit", "ombrage-du-the", "--sources", "[[Guide Shopify]]", "--resume", "none")
txt = page("wiki/Concepts/Ombrage du thé.md")
check('sources: ["[[Le matcha de cérémonie]]", "[[Guide Shopify]]"]' in txt and "resume:" not in txt,
      "edit --sources ajoute, --resume none retire", txt)
code, out = brain("q", "ombrage")
check("Ombrage du thé" in out, "q : page créée avec ses propriétés", out)


# ------------------------------------------------------------------ 15. débrancher le wiki : retour au classique
code, out = brain("config", "wiki.path", "null")
code, out = brain("add", "-t", "fact", "-T", "Fait après débranchement", "-b", "classique", "-p", "none")
g = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
check(code == 0 and not g.get("wiki") and "fait-apres-debranchement" in g["nodes"] and "ombrage-du-the" in g["nodes"]
      and not (WIKI / "wiki/Faits/Fait après débranchement.md").exists(),
      "wiki.path vide : le cerveau repart en classique depuis le cache, sans écrire dans le wiki", out)
code, out = brain("config", "wiki.path", json.dumps(str(WIKI.resolve())))
check("fait-apres-debranchement" not in Brain.load().nodes, "rebranché : le wiki refait foi")
kept = [json.loads(p.read_text(encoding="utf-8")) for p in (TMP / "brain").glob("graph.classique-*.json")]
check(any("fait-apres-debranchement" in k.get("nodes", {}) for k in kept), "rebranché : le cerveau classique d'entre-temps est gardé à côté")


# ------------------------------------------------------------------ 16. lanceur cloud du wiki (.claude/cerveau.py)
launcher = CLONE / ".claude" / "cerveau.py"
check(launcher.is_file(), "le lanceur cloud est dans le dépôt du wiki")
payload = json.dumps({"session_id": "c1", "cwd": str(CLONE), "source": "startup"}).encode()
env_pc = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_REMOTE"}
r = subprocess.run([sys.executable, "-I", "-S", str(launcher), "session-start"], input=payload, capture_output=True,
                   cwd=str(CLONE), env=env_pc, timeout=60)
check(r.returncode == 0 and not r.stdout, "lanceur sur le PC : ne fait rien (le cerveau installé suffit)", r.stdout[:200])
CLOUD2 = TMP / "cloud2"
env_c = {k: v for k, v in os.environ.items() if k not in ("BRAIN_HOME", "CLAUDE_CODE_REMOTE")}
env_c.update(CLAUDE_CODE_REMOTE="true", CLAUDE_CONFIG_DIR=str(CLOUD2 / "claude"), CERVEAU_CODE=str(CODE))
r = subprocess.run([sys.executable, "-I", "-S", str(launcher), "session-start"], input=payload, capture_output=True,
                   cwd=str(CLONE), env=env_c, timeout=120)
out = r.stdout.decode("utf-8", "replace")
check(r.returncode == 0 and "📚 Le cerveau vit dans le wiki" in out and "SKILL.md" in out,
      "lanceur en session cloud : le cerveau démarre sur le wiki (consignes avec la référence SKILL.md)",
      out[-400:] + r.stderr.decode("utf-8", "replace")[-400:])
check((CLOUD2 / "claude" / "brain" / "brain.py").is_file(), "lanceur en session cloud : lanceur stable du cerveau écrit")
r = subprocess.run([sys.executable, "-I", "-S", str(launcher), "prompt"], capture_output=True, cwd=str(CLONE), env=env_c,
                   input=json.dumps({"session_id": "c2", "cwd": str(CLONE),
                                     "prompt": "parle-moi de la synthèse japonaise sur Kyoto et Uji"}).encode(), timeout=60)
check(r.returncode == 0 and "Thé japonais" in r.stdout.decode("utf-8", "replace"), "lanceur en session cloud : rappel",
      r.stdout.decode("utf-8", "replace")[-300:])
CODE3 = TMP / "code-clone"
env_c.update(CERVEAU_CODE=str(CODE3), CERVEAU_REPO=f"file://{CODE}", CLAUDE_CONFIG_DIR=str(TMP / "cloud3" / "claude"))
r = subprocess.run([sys.executable, "-I", "-S", str(launcher), "prompt"], input=payload, capture_output=True,
                   cwd=str(CLONE), env=env_c, timeout=60)
check(r.returncode == 0 and not (CODE3 / "brain.py").exists(), "lanceur : aucun téléchargement pendant un message")
r = subprocess.run([sys.executable, "-I", "-S", str(launcher), "session-start"], input=payload, capture_output=True,
                   cwd=str(CLONE), env=env_c, timeout=120)
check((CODE3 / "brain.py").is_file() and "Le cerveau vit dans le wiki" in r.stdout.decode("utf-8", "replace"),
      "lanceur : code du cerveau récupéré au démarrage (git clone)", r.stderr.decode("utf-8", "replace")[-300:])

print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
(shutil.rmtree(TMP, ignore_errors=True) if not FAIL and not os.environ.get("KEEP") else print(f"(dossier gardé : {TMP})"))
sys.exit(1 if FAIL else 0)
