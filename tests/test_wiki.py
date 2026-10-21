"""Vérifications du cerveau en wiki (wikistore.py, wiki.py) — dans un dossier temporaire, jamais sur la vraie mémoire.

Lancement : python tests/test_wiki.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import re
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
# historique : sessions passées et observations datées (dont une condensée par le rêve, dans l'archive)
write_json(TMP / "brain" / "journal" / "sessions.json", {"sessions": {
    "s-a": {"id": "s-a", "project": "boutique", "title": "Refaire la fiche produit matcha", "first": "refais la fiche",
            "last": "publie-la", "edits": ["fiche.liquid"], "start": "2026-09-03T10:00:00", "end": "2026-09-03T11:30:00"},
    "s-b": {"id": "s-b", "project": None, "title": "Jeton ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8 collé par erreur",
            "first": "x", "start": "2026-09-04T09:00:00", "end": "2026-09-04T09:10:00"}}})
write_json(TMP / "brain" / "journal" / "observations.json", {"version": 1, "digests": [], "obs": [
    {"id": "o1", "at": "2026-09-03T11:00:00", "p": 3, "t": "Lucas choisit Mondial Relay pour les colis", "proj": "boutique"}]})
(TMP / "brain" / "journal" / "observations-archive.jsonl").write_text(json.dumps(
    {"id": "o0", "at": "2026-08-20T15:00:00", "p": 2, "t": "Première version du site en ligne", "proj": "boutique"},
    ensure_ascii=False) + "\n", encoding="utf-8")
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
j9 = page("journal/2026-09.md") if (WIKI / "journal/2026-09.md").is_file() else ""
check("💬 11:30 « Refaire la fiche produit matcha »" in j9 and "🔴 11:00 Lucas choisit Mondial Relay" in j9
      and "jeudi 3 septembre" in j9, "historique : sessions et observations dans journal/2026-09.md", j9[:600])
check("Première version du site en ligne" in page("journal/2026-08.md"), "historique : observations archivées par le rêve aussi")
check("ghp_a1B2" not in j9, "historique : secrets masqués", j9)
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

# ------------------------------------------------------------------ 5 bis. coffre Obsidian réglé par le cerveau
from brainkit import obsidian  # noqa: E402

OB = WIKI / ".obsidian"


def obs(name):
    return json.loads((OB / name).read_text(encoding="utf-8"))


cfg = {f: obs(f) for f in ("app.json", "types.json", "core-plugins.json", "backlink.json", "templates.json",
                           "hotkeys.json", "bookmarks.json", "graph.json")}
check(len(cfg["types.json"]["types"]) == 29 and cfg["types.json"]["types"]["echeance"] == "date"
      and cfg["types.json"]["types"]["lie_a"] == "multitext", "Obsidian : propriétés typées", str(cfg["types.json"]))
check(all(cfg["core-plugins.json"].get(m) for m in ("templates", "bases", "backlink")) and cfg["backlink.json"]["backlinkInDocument"],
      "Obsidian : modules Modèles, Bases et rétroliens actifs")
check(cfg["templates.json"]["folder"] == "wiki/_modeles" and "templates:insert-template" in cfg["hotkeys.json"],
      "Obsidian : modèles avec Alt+T")
check({"archive/", "wiki/_modeles/"} <= set(cfg["app.json"]["userIgnoreFilters"]) and cfg["app.json"]["newFileFolderPath"] == "raw",
      "Obsidian : archive et modèles hors recherche, nouvelles notes dans raw/")
check({"Tableau de bord.base", "Mode d'emploi Obsidian.md", "index.md"} <= obsidian._marks(cfg["bookmarks.json"]["items"]),
      "Obsidian : signets du groupe Cerveau", str(cfg["bookmarks.json"]))
check(len(cfg["graph.json"]["colorGroups"]) == len(ws.FOLDERS), "Obsidian : une couleur par dossier dans le graphe")
check('file.inFolder("wiki/_modeles")' in page("Tableau de bord.base") and "Alt+T" in page("Mode d'emploi Obsidian.md"),
      "Obsidian : tableau de bord (modèles exclus) et mode d'emploi")
tpl = sorted(p.stem for p in (WIKI / "wiki/_modeles").glob("*.md"))
paths = [v.get("path", "") for v in Brain.load().data["wiki"]["files"].values()]
check(len(tpl) == 6 and "echeance: {{date:YYYY-MM-DD}}" in page("wiki/_modeles/À faire.md")
      and "## À retenir" in page("wiki/_modeles/Jour.md") and not any("_modeles" in p for p in paths),
      "Obsidian : 6 modèles (dont la note du jour), que le cerveau ne prend pas pour des pages", str(tpl))
check(".obsidian/plugins/*/main.js" in page(".gitignore"), "Obsidian : code des modules tiers hors git")
check(page(".ignore").splitlines() == [".obsidian/", ".trash/", "/Cerveau.md", "/Carte du cerveau.canvas"],
      "Obsidian : réglages, corbeille, page Cerveau et carte hors des recherches de Claude")
dn = obs("daily-notes.json")
check(dn == obsidian.DAILY and cfg["core-plugins.json"].get("daily-notes") and cfg["core-plugins.json"].get("canvas")
      and cfg["hotkeys.json"].get("daily-notes") == [{"modifiers": ["Alt"], "key": "J"}] and (WIKI / "Notes du jour").is_dir()
      and {"/Cerveau.md", "/Carte du cerveau.canvas"} <= set(page(".gitignore").splitlines()),
      "Obsidian : note du jour (Alt+J, modèle Jour, dossier créé), page Cerveau et carte hors git", str(dn))
check(obsidian.LIVE_HEAD in page("Mode d'emploi Obsidian.md") and "Alt+J" in page("Mode d'emploi Obsidian.md"),
      "Obsidian : mode d'emploi avec la page Cerveau, la carte et la note du jour")
check(not (OB / "plugins").exists(), "Obsidian : réglages d'Omnisearch jamais créés s'il n'est pas installé")
check(obsidian.setup(WIKI) == [], "Obsidian : réglé une seule fois par version")
# réglages changés par l'utilisateur : rien d'écrasé, seul le manquant revient
(OB / "hotkeys.json").write_text(json.dumps({"editor:toggle-bold": [{"modifiers": ["Alt"], "key": "t"}]}), encoding="utf-8")
(OB / "app.json").write_text(json.dumps(dict(cfg["app.json"], newFileFolderPath="Boîte", userIgnoreFilters=["perso/"])),
                             encoding="utf-8")
(OB / "types.json").write_text(json.dumps({"types": {"importance": "text"}}), encoding="utf-8")
(OB / "bookmarks.json").write_text(json.dumps({"items": [{"type": "file", "path": "index.md", "title": "Mon index"}]}),
                                   encoding="utf-8")
(WIKI / "Mode d'emploi Obsidian.md").write_text("à moi\n", encoding="utf-8")
(WIKI / ".ignore").write_text("perso/\n.trash/\n", encoding="utf-8")
(OB / "plugins" / "omnisearch").mkdir(parents=True)
(OB / "plugins/omnisearch/data.json").write_text(json.dumps({"weightBasename": 9, "weightCustomProperties": [
    {"name": "cles", "weight": 8}]}), encoding="utf-8")
made = obsidian.setup(WIKI, force=True)
hk, app, ty, bm = obs("hotkeys.json"), obs("app.json"), obs("types.json"), obs("bookmarks.json")
om = obs("plugins/omnisearch/data.json")
check(page(".ignore").splitlines() == ["perso/", ".trash/", ".obsidian/", "/Cerveau.md", "/Carte du cerveau.canvas"],
      "Obsidian : .ignore complété, lignes gardées")
check(om == {"weightBasename": 9, "weightCustomProperties": [{"name": "cles", "weight": 8}, {"name": "resume", "weight": 4}]},
      "Obsidian : Omnisearch, poids du résumé ajouté, choix de l'utilisateur gardés", str(om))
check("templates:insert-template" not in hk and "editor:toggle-bold" in hk and "omnisearch:show-modal" in hk,
      "Obsidian : raccourci déjà pris par l'utilisateur gardé", str(hk))
check(app["newFileFolderPath"] == "Boîte" and app["userIgnoreFilters"] == ["perso/", "archive/", "wiki/_modeles/"],
      "Obsidian : réglages gardés, exclusions ajoutées", str(app))
check(ty["types"]["importance"] == "text" and ty["types"]["echeance"] == "date", "Obsidian : type choisi par l'utilisateur gardé")
check(page("Mode d'emploi Obsidian.md") == "à moi\n", "Obsidian : fichier existant jamais écrasé")
check(sum(1 for b in json.dumps(bm).split('"index.md"')) == 2 and bm["items"][0]["title"] == "Mon index"
      and len(bm["items"][1]["items"]) == 5, "Obsidian : signets complétés sans doublon", str(bm))
check(obsidian.setup(WIKI, force=True) == [], "Obsidian : deuxième passage, rien à faire", str(made))
old = f"{obsidian.GUIDE_HEAD}\n\nIntro.\n\n## Avant de demander à Claude\nTexte.\n"
(WIKI / obsidian.GUIDE).write_text(old, encoding="utf-8")
made = obsidian.setup(WIKI, force=True)
g = page(obsidian.GUIDE)
check(made == [obsidian.GUIDE] and g.startswith(f"{obsidian.GUIDE_HEAD}\n\nIntro.\n\n{obsidian.LIVE_HEAD}")
      and g.endswith("## Avant de demander à Claude\nTexte.\n") and obsidian.setup(WIKI, force=True) == [],
      "Obsidian : mode d'emploi d'avant complété une fois (section en tête, rien d'autre touché)", g[:300])
# page Cerveau et carte des thèmes (réécrites en fin de session, seulement si quelque chose a changé)
b0 = Brain.load()
check(obsidian.write_status(b0, WIKI) and not obsidian.write_status(b0, WIKI)
      and all(h in page("Cerveau.md") for h in ("# 🧠 Cerveau", "## ⏰ Échéances", "## 📚 Mémoire", "## 🩺 Santé du wiki",
                                                "## 🤝 Cerveau commun", "Alt+J")),
      "Obsidian : page Cerveau écrite, pas réécrite sans changement", page("Cerveau.md")[:600])
cv = json.loads(page("Carte du cerveau.canvas")) if obsidian.write_canvas(b0, WIKI) else {}
ids = {n["id"] for n in cv.get("nodes", [])}
check(cv and not obsidian.write_canvas(b0, WIKI) and len(ids) == len(cv["nodes"])
      and all(e["fromNode"] in ids and e["toNode"] in ids for e in cv["edges"])
      and all(re.fullmatch(r"#[0-9A-F]{6}", n["color"]) for n in cv["nodes"] if "color" in n)
      and all({"x", "y", "width", "height", "type"} <= set(n) for n in cv["nodes"]),
      "Obsidian : carte du cerveau en JSON Canvas valide (ids uniques, liens entre cartes, couleurs #RRGGBB)",
      json.dumps(cv, ensure_ascii=False)[:600])
(WIKI / "Cerveau.md").unlink()
os.environ["CLAUDE_CODE_REMOTE"] = "true"
check(not obsidian.write_status(b0, WIKI) and not (WIKI / "Cerveau.md").exists(), "Obsidian : page Cerveau jamais écrite en session cloud")
os.environ.pop("CLAUDE_CODE_REMOTE")
# note du jour → souvenirs
check(obsidian.kind_of("Décision : on garde Shopify") == ("decision", "on garde Shopify")
      and obsidian.kind_of("à faire : appeler X", False)[0] == "todo" and obsidian.kind_of("rappeler", True)[0] == "todo"
      and obsidian.kind_of("Note : ceci est un fait") == ("fact", "Note : ceci est un fait"),
      "note du jour : préfixes lus (sinon un fait, une case à cocher = un à-faire)")
note = WIKI / "Notes du jour" / "2026-09-10.md"
note.write_text(page("wiki/_modeles/Jour.md").replace("{{date:dddd D MMMM YYYY}}", "jeudi 10 septembre 2026").replace(
    "\n- \n", "\n- règle : toujours tutoyer les clients\n- [ ] rappeler le grossiste demain\n- Le thé d'Uji pousse près de Kyoto\n"
    "- à faire : commander les sachets le 25/09\n- [x] déjà fait\n- ✓ déjà mémorisé → [[index]]\n"), encoding="utf-8")
os.utime(note, (time.time() - 3600, time.time() - 3600))
fresh = WIKI / "Notes du jour" / "2026-09-11.md"
fresh.write_text("## À retenir\n- note en cours d'écriture\n", encoding="utf-8")
check([c["text"] for c in obsidian.captures(WIKI)] == ["règle : toujours tutoyer les clients", "rappeler le grossiste demain",
                                                       "Le thé d'Uji pousse près de Kyoto",
                                                       "à faire : commander les sachets le 25/09"],
      "note du jour : 4 lignes en attente (ni cochée, ni déjà faite, ni note en cours d'écriture)",
      str(obsidian.captures(WIKI)))
code, out = brain("wiki", "capture")
txt, b1 = note.read_text(encoding="utf-8"), Brain.load()
got = {n["title"]: n for n in b1.nodes.values() if n.get("source") == "utilisateur"}
rule = got.get("toujours tutoyer les clients") or {}
todo = next((n for t, n in got.items() if t.startswith("rappeler le grossiste")), {})
check(code == 0 and out.count("✓") == 4 and txt.count("- ✓ ") == 5 and txt.count(" → [[") == 5
      and "- [x] déjà fait" in txt and "note en cours d'écriture" in fresh.read_text(encoding="utf-8")
      and f"[[{obsidian._names(b1).get(rule.get('id'))}]]" in txt,
      "note du jour : lignes mémorisées puis marquées ✓ → [[page]]", out + "\n" + txt)
check(rule.get("type") == "feedback" and rule.get("importance") == 4 and not rule.get("project")
      and (rule.get("meta") or {}).get("prive") and todo.get("type") == "todo" and "11/09/2026" in todo.get("title", "")
      and todo["meta"].get("due") == "2026-09-11"
      and (got.get("commander les sachets le 25/09") or {"meta": {}})["meta"].get("due") == "2026-09-25"
      and got.get("Le thé d'Uji pousse près de Kyoto", {}).get("type") == "fact",
      "note du jour : bon type, globale, privée, échéance (« demain », « le 25/09 ») comptée depuis le jour de la note", json.dumps(got, ensure_ascii=False)[:800])
code, out = brain("wiki", "capture")
check("rien à mémoriser" in out and note.read_text(encoding="utf-8") == txt, "note du jour : deuxième passage, rien de refait", out)
(WIKI / obsidian.STAMP).unlink()  # installation d'avant la 8.7 : réglée au prochain démarrage (section 10)
(WIKI / "wiki/_modeles/Référence.md").unlink()

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
check("Coffre Obsidian réglé" in o and (WIKI / "wiki/_modeles/Référence.md").is_file() and (WIKI / obsidian.STAMP).is_file()
      and "Coffre Obsidian" not in hook("session-start", {"session_id": "s0", "cwd": str(WORK)}),
      "démarrage : coffre Obsidian réglé une fois (installation existante)", o[-600:])
o = hook("prompt", {"session_id": "s9", "cwd": str(WORK), "prompt": "parle-moi de la synthèse japonaise sur Kyoto et Uji"})
check("Thé japonais" in o, "rappel : page du wiki remontée", o)
check("Thé japonais" in hook("session-start", {"session_id": "s3", "cwd": str(WORK)}), "index de démarrage : section wiki")
o = hook("session-start", {"session_id": "s2", "cwd": str(WIKI)})
check("wiki" not in [n["id"] for n in Brain.load().projects()], "le dossier du wiki n'est pas cartographié comme projet")
with Brain.edit() as b2:
    b2.add("learning", "Astuce de fin de session", "Une page créée pendant la session.")
    b2.add("todo", "Rappeler le torréfacteur de Shizuoka", "À faire créé pendant la session.")
check((WIKI / "Cerveau.md").is_file() and (WIKI / "Carte du cerveau.canvas").is_file()
      and "Rappeler le torréfacteur" not in page("Cerveau.md"), "démarrage : page Cerveau et carte écrites au réglage du coffre")
hook("session-end", {"session_id": "s1", "cwd": str(WORK)})
check("session | hors projet" in page("log.md"), "fin de session : entrée « session » au journal", page("log.md")[-400:])
check("Rappeler le torréfacteur de Shizuoka" in page("Cerveau.md"), "fin de session : page Cerveau à jour (nouvel à-faire)",
      page("Cerveau.md")[:800])

# ------------------------------------------------------------------ 10 bis. veille automatique (brain auto), sans Claude
from brainkit import auto  # noqa: E402
from brainkit.common import set_config  # noqa: E402

STATE = TMP / "brain" / "state"
jour = WIKI / "Notes du jour" / "2026-09-12.md"
jour.write_text("## À retenir\n- apprentissage : la veille mémorise sans Claude\n", encoding="utf-8")
os.utime(jour, (time.time() - 3600, time.time() - 3600))
with Brain.edit() as b2:
    b2.add("todo", "Vérifier la veille du cerveau", "À faire créé hors session.")
code, out = brain("auto")
check(code == 0 and "✓ notes du jour" in out and "- ✓ " in jour.read_text(encoding="utf-8")
      and any(n["title"] == "la veille mémorise sans Claude" for n in Brain.load().nodes.values()),
      "veille : note du jour mémorisée sans session", out + "\n" + jour.read_text(encoding="utf-8"))
check("Vérifier la veille du cerveau" in page("Cerveau.md"), "veille : page Cerveau à jour", out)
check("synchro du wiki" not in out, "veille : pas de synchro git pendant une session de Claude", out)
last = json.loads((STATE / "auto.json").read_text(encoding="utf-8"))
code, out2 = brain("auto", "--etat")
check(last.get("le") and any(r["etape"] == "notes du jour" for r in last["etapes"]) and "Dernière passe" in out2
      and "✓ notes du jour" in out2, "veille : compte rendu gardé, lisible par --etat", out2)
for f in (STATE / "sessions").glob("*.json"):
    os.utime(f, (time.time() - 3600, time.time() - 3600))
(WIKI / "wiki/Sujets/Thé japonais.md").write_text(page("wiki/Sujets/Thé japonais.md") + "\nAjout hors session.\n",
                                                  encoding="utf-8")
code, out = brain("auto")
head = subprocess.run(["git", "-C", str(REMOTE), "show", "main:wiki/Sujets/Thé japonais.md"], capture_output=True)
check("✓ synchro du wiki" in out and "Ajout hors session." in head.stdout.decode("utf-8", "replace"),
      "veille : wiki synchronisé (commit + push) quand aucune session n'est ouverte", out)
(STATE / "auto.lock").write_text("1", encoding="utf-8")
code, out = brain("auto")
(STATE / "auto.lock").unlink()
check("déjà en cours" in out, "veille : jamais deux passes à la fois", out)
before = (STATE / "auto.json").read_text(encoding="utf-8")
os.environ["CLAUDE_CODE_REMOTE"] = "true"
code, out = brain("auto")
os.environ.pop("CLAUDE_CODE_REMOTE")
check("session cloud" in out and (STATE / "auto.json").read_text(encoding="utf-8") == before,
      "veille : aucune passe en session cloud", out)
brain("config", "auto.enabled", "false")
code, out = brain("auto")
brain("config", "auto.enabled", "true")
check("coupée" in out, "veille : coupée par la configuration", out)
code, out = brain("auto", "--installer", "--dry-run")
check(code == 0 and "rien n'est fait" in out and "<Interval>PT30M</Interval>" in out and "pythonw.exe" in out
      and "InteractiveToken" in out and "LeastPrivilege" in out and "&quot; auto" not in out and '" auto</Arguments>' in out,
      "veille : --installer --dry-run montre la tâche (30 min, pythonw, sans mot de passe, droits limités)", out[:900])
# textes d'Obsidian : la veille n'est annoncée que si la tâche est posée ; mode d'emploi 8.8 mis à jour une fois
check("toutes les 30 min" not in page("Cerveau.md"), "Obsidian : page Cerveau sans veille annoncée (tâche non posée)")
set_config("auto.tache", "2026-09-12T10:00:00")
obsidian.write_status(Brain.load(), WIKI)
check("toutes les 30 min (veille automatique)" in page("Cerveau.md") and "passe suivante de la veille" in page("Cerveau.md"),
      "Obsidian : page Cerveau annonce la veille quand la tâche est posée", page("Cerveau.md")[:300])
set_config("auto.tache", None)
v3 = f"{obsidian.GUIDE_HEAD}\n\nIntro.\n\n{obsidian.GUIDE_LIVE_V3}\n## Avant de demander à Claude\nTexte.\n"
(WIKI / obsidian.GUIDE).write_text(v3, encoding="utf-8")
made = obsidian.setup(WIKI, force=True)
g = page(obsidian.GUIDE)
check(made == [obsidian.GUIDE] and obsidian.GUIDE_LIVE in g and obsidian.GUIDE_LIVE_V3 not in g
      and g.endswith("## Avant de demander à Claude\nTexte.\n") and obsidian.setup(WIKI, force=True) == [],
      "Obsidian : mode d'emploi 8.8 passé à la veille automatique, une fois", g[:400])
mine = v3.replace("ne les modifie pas", "ne les touche pas")
(WIKI / obsidian.GUIDE).write_text(mine, encoding="utf-8")
check(obsidian.setup(WIKI, force=True) == [] and page(obsidian.GUIDE) == mine,
      "Obsidian : mode d'emploi retouché à la main jamais réécrit")

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
html = (TMP / "brain" / "cerveau.html").read_text(encoding="utf-8")
wp = [n["wpath"] for n in json.loads(html.split("const DATA = ", 1)[1].split(";</script>", 1)[0])["nodes"] if n.get("wpath")]
check(wp and all(Path(p).is_file() and Path(p).resolve().is_relative_to(WIKI.resolve()) for p in wp)
      and "obsidian://open?path=" in html and "obsidian://open?path=" in (TMP / "brain" / "cerveau-2d.html").read_text(encoding="utf-8"),
      "vues 3D et 2D : bouton « Ouvrir dans Obsidian » vers la page du wiki", str(wp[:3]))
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
# Le lanceur récupère le plugin publié : on en construit un ici (publish.build), dépôt git compris. Toujours avec un
# BRAIN_HOME temporaire : lancé depuis un arbre de développement, ce test ne touche jamais la vraie mémoire.
from brainkit import publish  # noqa: E402
PLUG = TMP / "plugin-publie"
publish.build(PLUG, owner="Test", repo="exemple/cerveau")
for args in (["init", "-q", "-b", "main"], ["add", "-A"],
             ["-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-qm", "plugin"]):
    subprocess.run(["git", "-C", str(PLUG), *args], check=True, capture_output=True)
launcher = CLONE / ".claude" / "cerveau.py"
check(launcher.is_file(), "le lanceur cloud est dans le dépôt du wiki")
payload = json.dumps({"session_id": "c1", "cwd": str(CLONE), "source": "startup"}).encode()
env_pc = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_REMOTE"}
r = subprocess.run([sys.executable, "-I", "-S", str(launcher), "session-start"], input=payload, capture_output=True,
                   cwd=str(CLONE), env=env_pc, timeout=60)
check(r.returncode == 0 and not r.stdout, "lanceur sur le PC : ne fait rien (le cerveau installé suffit)", r.stdout[:200])
CLOUD2 = TMP / "cloud2"
env_c = dict(os.environ, CLAUDE_CODE_REMOTE="true", CLAUDE_CONFIG_DIR=str(CLOUD2 / "claude"),
             BRAIN_HOME=str(CLOUD2 / "claude" / "brain"), CERVEAU_CODE=str(PLUG))
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
env_c.update(CERVEAU_CODE=str(CODE3), CERVEAU_REPO=PLUG.as_uri(), CLAUDE_CONFIG_DIR=str(TMP / "cloud3" / "claude"),
             BRAIN_HOME=str(TMP / "cloud3" / "claude" / "brain"))
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
