"""Consommation (étape 5 du plan) : ce que le cerveau met dans le contexte de Claude. Consignes du démarrage gardées à
l'essentiel, même après un résumé (compaction) ou /clear, sans perdre une règle ni une ligne du profil ; serveur MCP :
outils de la mémoire seulement par défaut, résultats bornés et paginés ; skill /brain courte, le détail dans ses fichiers
de référence ; un dossier qui n'a qu'un README n'est pas un projet ; mode éco : descriptions des skills plafonnées
(décision E2) ; tâche des vues : seulement ce qui a changé. Aucune mesure de temps : on compte ce qui est injecté,
listé ou réécrit.

Lancement : python tests/test_consommation.py   (sortie : « N vérifications OK, M échec(s) »)"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-conso-test-"))
CODE = Path(__file__).resolve().parent.parent
PLUGIN = (CODE / ".claude-plugin" / "plugin.json").exists()
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS"):
    os.environ.pop(k, None)
os.environ.update(CLAUDE_CONFIG_DIR=str(TMP / "claude"), BRAIN_HOME=str(TMP / "brain"), HOME=str(TMP / "home"),
                  USERPROFILE=str(TMP / "home"), BRAIN_OFFLINE="1")
WORK, NEUTRE = TMP / "boutique", TMP / "ailleurs"
for d in (WORK, NEUTRE, TMP / "home", TMP / "claude", TMP / "brain" / "state"):
    d.mkdir(parents=True)
(WORK / "package.json").write_text("{}", encoding="utf-8")
os.chdir(TMP)
sys.path.insert(0, str(CODE))

from brainkit import install, mapper, mcp_server, store, vues  # noqa: E402
from brainkit.common import (EXPORT_FILE, GRAPH_FILE, INDEX_FILE, STATE_DIR, VIZ2D_FILE, VIZ_FILE,  # noqa: E402
                             remove_tree, set_config)
from brainkit.store import Brain  # noqa: E402


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def run(*args, env=None, cwd=TMP, inp=None):
    r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), *map(str, args)], capture_output=True,
                       input=inp, env=env or dict(os.environ), cwd=str(cwd), timeout=300)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def hook(event, sid, cwd=WORK, env=None, **extra):
    c, out = run("hook", event, env=env, cwd=cwd, inp=json.dumps({"session_id": sid, "cwd": str(cwd), **extra}).encode())
    try:
        return json.JSONDecoder().raw_decode(out.lstrip())[0] if out.strip() else {}
    except ValueError:
        return {"brut": out}


def ctx(obj) -> str:
    return (obj.get("hookSpecificOutput") or {}).get("additionalContext") or obj.get("brut", "")


# ------------------------------------------------------------------ cerveau d'essai : 9 règles, 4 lignes de profil
OLD = "2026-03-10T09:00:00"
now = dt.datetime.now().replace(microsecond=0).isoformat()


def node(nid, ntype, title, body, project=None, **meta):
    return {"id": nid, "type": ntype, "title": title, "body": body, "tags": [], "project": project, "importance": 3,
            "created": OLD, "updated": OLD, "hits": 0, "source": "utilisateur", "status": "active", "meta": meta}


REGLES = [f"Règle numéro {i} : {s}" for i, s in enumerate(
    ("vouvoyer les clients", "prix toujours TTC", "photos sur fond blanc", "livraison offerte dès 60 €",
     "jamais de promesse de délai", "factures en PDF", "réponses sous 24 h", "emballage sans plastique",
     "avis clients publiés tels quels"))]
PROFIL = ["Prénom et métier", "Équipement de l'atelier", "Disponibilités de la semaine", "Objectifs 2026"]
nodes = [node("boutique", "project", "Boutique Atelier", "Boutique Shopify de céramique.", path=str(WORK))]
nodes += [node(f"r{i}", "feedback", t, f"Pour la boutique : {t.split(' : ')[1]}, sans exception, et le rappeler aux "
               "clients quand ils posent la question.") for i, t in enumerate(REGLES)]
nodes += [node(f"u{i}", "user", t, f"{t} : détail connu de l'utilisateur, à garder en tête dans chaque réponse.")
          for i, t in enumerate(PROFIL)]
SUJETS = ["livraison Colissimo", "thème Dawn", "transporteur Mondial Relay", "photos des vases", "prix des bols",
          "fiche produit tasse", "frais de port", "emballage des colis", "retours clients", "stock des assiettes"]
nodes += [node(f"b{i}", ("fact", "learning", "decision")[i % 3], f"Boutique : {s} ({i})",
               f"Pour la boutique, {s} : réglage numéro {i}, vu avec le transporteur et le thème.", "boutique")
          for i, s in enumerate(SUJETS * 2)]
nodes.append(node("gros", "reference", "Notes complètes de l'atelier", "\n".join(
    f"- Ligne {i} des notes : cuisson du grès à 1 280 °C, émail {i % 7}, four électrique, refroidissement lent."
    for i in range(300))))  # un souvenir très long (page de wiki, notes collées) : 27 000 caractères
nodes += [node(f"t{i}", "todo", f"À faire numéro {i} : relancer le fournisseur de {s}",
               f"Relancer le fournisseur de {s}, vérifier le stock, mettre à jour la fiche produit et noter le délai "
               "annoncé, puis prévenir les clients qui attendent une commande. " * 2) for i, s in enumerate(SUJETS * 4)]
GRAPH_FILE.write_text(json.dumps({"version": 1, "created": OLD, "nodes": {n["id"]: n for n in nodes}, "edges": [
    {"from": "b0", "to": "b1", "rel": "relates", "created": OLD[:10]}]}), encoding="utf-8")
(TMP / "brain" / "config.json").write_text(json.dumps({  # rien en arrière-plan : ni carte, ni mode éco, ni sauvegarde
    "auto_map": {"enabled": False}, "eco": {"auto": False}, "backup": {"enabled": False}, "pc": {"enabled": False},
    "journal": {"rattrapage_le": now}, "garde": {"le": now}}), encoding="utf-8")
(STATE_DIR / "last_consolidate").write_text(now, encoding="utf-8")

# ------------------------------------------------------------------ 1. injection du démarrage
LIST = '`q "sujet"` · `add -t <type> -T "titre" -b "fait + pourquoi + comment"` · `edit`/`show <id>`'  # la liste d'avant
starts = {"hors projet": ctx(hook("session-start", "n1", cwd=NEUTRE, source="startup")),
          "projet": ctx(hook("session-start", "p1", source="startup"))}
starts["après un résumé"] = ctx(hook("session-start", "p1", source="compact"))
starts["après /clear"] = ctx(hook("session-start", "p1", source="clear"))
for label, text in starts.items():
    missing = [t for t in REGLES + PROFIL if t not in text]
    check(text and not missing, f"démarrage ({label}) : les 9 règles et les 4 lignes de profil, au moins par leur titre",
          missing or text[:300])
if PLUGIN:  # plugin : les consignes passent par l'injection (cerveau classique : par CLAUDE.md, le même bloc)
    blocks = {label: text.split("\n\n", 1)[0] for label, text in starts.items()}
    block = blocks["projet"]
    size = len(block) - len(install.CMD)  # (le chemin du cerveau d'essai est plus long que le vrai)
    check(block.startswith("# 🧠 Cerveau persistant") and size <= 1000,
          f"consignes du démarrage à l'essentiel : {size} caractères hors chemin de la commande (2 000 avant)", block)
    check(all(b == block for b in blocks.values()),
          "les mêmes consignes courtes hors projet, dans un projet, après un résumé et après /clear", blocks)
    check(all(s in block for s in ("skill `/cerveau:brain`", "`add -t", "--replaces", "Jamais :", "`securite`",
                                   "`files`/`where`/`explain`")),
          "consignes : quand chercher, quoi mémoriser et comment, ce qu'on ne garde jamais, où sont les commandes", block)
    check(all(LIST not in text for text in starts.values()),
          "la liste des commandes n'est plus injectée à chaque démarrage", block)
    deleg = next((ln for ln in starts["projet"].splitlines() if ln.startswith("↪ Délégation")), "")
    check(deleg and len(deleg) <= 260, f"ligne de délégation courte ({len(deleg)} caractères, 329 avant)", deleg)
else:
    size = len(install.CLAUDE_BLOCK) - len(install.CMD)
    check(size <= 1200, f"bloc CLAUDE.md à l'essentiel : {size} caractères (2 000 avant)", install.CLAUDE_BLOCK)
check(all(s in install.SKILL for s in ('q "', "add -t", "edit <id>", "show <id>", "`todo`", 'files "', "where X",
                                       "explain <", "impact <", "map [dossier]", "wiki add", "`commun`")),
      "les commandes de l'ancienne liste sont dans la skill /brain", install.SKILL[:400])
bare = {k: len(v.replace(str(TMP), "~").replace(TMP.as_posix(), "~")) for k, v in starts.items()}  # (chemins à part)
check(bare["hors projet"] <= 5000 and bare["projet"] <= 5300 and bare["après un résumé"] <= 5300,
      f"injection du démarrage : {bare['hors projet']} caractères hors projet, {bare['projet']} dans le projet, "
      f"{bare['après un résumé']} après un résumé (5 760, 6 060 et 6 020 avant sur ce cerveau)", bare)

# ------------------------------------------------------------------ 2. serveur MCP
MEMORY = ["memory_search", "memory_add", "memory_show", "memory_update", "memory_todo", "memory_context"]


def rpc(method, params=None, mid=1):
    msg = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        msg["params"] = params
    return mcp_server.handle(msg)


def listed():
    return [t["name"] for t in rpc("tools/list")["result"]["tools"]]


def tool(name, **args):
    res = rpc("tools/call", {"name": name, "arguments": args})["result"]
    return res["content"][0]["text"], res["isError"]


req = "\n".join(json.dumps(x) for x in (
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})) + "\n"
c, out = run("mcp", inp=req.encode())
resp = {x.get("id"): x for x in (json.loads(y) for y in out.splitlines() if y.strip().startswith("{"))}
got = (resp.get(2) or {}).get("result") or {}
size = len(json.dumps(got, ensure_ascii=False, separators=(",", ":")))
check([t["name"] for t in got.get("tools", [])] == MEMORY and size <= 3600,
      f"MCP par défaut : les 6 outils de la mémoire, {size} caractères listés (15 outils et 6 600 avant)",
      [t["name"] for t in got.get("tools", [])])
set_config("mcp.groupes", ["wiki"])
check(listed() == MEMORY + ["wiki_status", "wiki_add_source", "wiki_lint", "wiki_log"],
      "mcp.groupes [\"wiki\"] : les outils du wiki s'ajoutent, pas ceux des boutiques", listed())
set_config("mcp.groupes", "wiki, boutique")
check(len(listed()) == 15 and listed()[-1] == "boutique_audit", "mcp.groupes « wiki, boutique » : les 15 outils", listed())
set_config("mcp.groupes", "tout")
check(len(listed()) == 15, "mcp.groupes « tout » : les 15 outils", listed())
set_config("mcp.groupes", [])
out, err = tool("boutique_etat")
check(err and "mcp.groupes" in out and listed() == MEMORY,
      "outil d'un groupe pas activé : refusé, avec la commande qui l'active", out)

full, _ = mcp_server._run_cli(["show", "gros"])
pages, page = [], 1
while page < 20:
    text, err = tool("memory_show", id="gros", page=page)
    pages.append(text)
    if "page: " not in text.rsplit("\n", 1)[-1]:
        break
    page += 1
body = "\n".join(p.rsplit("\n… page ", 1)[0] if i < len(pages) - 1 else p for i, p in enumerate(pages))
check(len(full) > 8000 and len(pages) >= 2 and all(len(p) <= 8000 + 200 for p in pages)
      and f"page 1/{len(pages)}" in pages[0] and "page: 2" in pages[0] and "… page" not in body
      and all(body.count(f"- Ligne {i} des notes :") == 1 for i in range(300)),
      f"résultat long (memory_show, {len(full)} caractères) : pages de 8 000 au plus, la fin dit comment avoir la "
      "suite, rien de perdu ni de répété", [len(p) for p in pages])
set_config("mcp.max_car", 1500)
text, err = tool("memory_show", id="gros")
check(len(text) <= 1500 + 200 and "page: 2" in text, "mcp.max_car 1500 : pages plus courtes", len(text))
text, err = tool("memory_show", id="gros", page=999)
check(err and "page(s)" in text, "page au-delà de la dernière : dit combien il y en a", text)
set_config("mcp.max_car", 8000)
calls = []
real = mcp_server._run_cli
mcp_server._run_cli = lambda argv: (calls.append(argv), ("ok", False))[1]
try:
    tool("memory_search", query="livraison", limit=500)
    tool("memory_add", type="fact", title="Fait ajouté par MCP", body="Texte.", page=2)
finally:
    mcp_server._run_cli = real
check(calls and calls[0][calls[0].index("-k") + 1] == "30" and len(calls) == 1,
      "memory_search : limite ramenée à 30 ; memory_add page 2 sans résultat gardé : rien de relancé (rien d'écrit "
      "deux fois)", calls)
before = len(Brain.load().nodes)
out, err = tool("memory_add", type="fact", title="Fait ajouté par MCP", body="Texte court.")
check(not err and len(Brain.load().nodes) == before + 1 and "page" not in out, "memory_add : résultat court, en entier",
      out)

# ------------------------------------------------------------------ 3. skill /brain : l'essentiel, le reste à la demande
desc = re.search(r"(?m)^description: (.*)$", install.SKILL).group(1)
check(len(install.SKILL) <= 7500, f"skill /brain : {len(install.SKILL)} caractères gardés dans le contexte (24 500 "
      "avant)", len(install.SKILL))
check(len(desc) <= 250, f"description de la skill /brain : {len(desc)} caractères, sous le plafond du mode éco (250)",
      desc)
refs = getattr(install, "SKILL_REFS", {})
named = set(re.findall(r"references/([\w-]+\.md)", install.SKILL))
check(refs and named == set(refs), "chaque fichier de référence est nommé par la skill, et seulement ceux-là",
      (sorted(named), sorted(refs)))
everything = install.SKILL + "".join(refs.values())
check(all(h in everything for h in ("## Ce qui se passe tout seul (hooks)", "## Mémoire", "## Wiki", "## Cerveau commun",
                                    "## Délégation, apprentissage, échange de skills", "## Skills métier",
                                    "## Ailleurs que dans l'onglet Code", "## Graphe", "## Projets", "## Entretien",
                                    "## Consignes en détail")),
      "rien de perdu : chaque partie de l'ancienne skill est dans un fichier de référence", sorted(refs))
REPO = CODE / "skills" / "brain"
if (REPO / "SKILL.md").exists() and PLUGIN:  # dépôt du plugin : fichiers générés par `brain publish`
    friend = 'python "$HOME/.claude/brain/brain.py"'
    same = [n for n, t in refs.items() if (REPO / "references" / n).is_file()
            and (REPO / "references" / n).read_text(encoding="utf-8") == t.replace(install.CMD, friend)]
    check(sorted(same) == sorted(refs) and sorted(p.name for p in (REPO / "references").glob("*.md")) == sorted(refs),
          "skills/brain/references du dépôt identiques à install.SKILL_REFS", sorted(same))
dest = TMP / "skill-classique"
(dest / "references").mkdir(parents=True)
(dest / "references" / "ancien.md").write_text("x", encoding="utf-8")
(dest / "a-moi.txt").write_text("à l'utilisateur", encoding="utf-8")
if hasattr(install, "write_brain_skill"):
    install.write_brain_skill(dest)
    check((dest / "SKILL.md").read_text(encoding="utf-8") == install.SKILL
          and sorted(p.name for p in (dest / "references").iterdir()) == sorted(refs),
          "installation classique : SKILL.md et ses fichiers de référence posés, un ancien retiré", list(dest.rglob("*")))
    install.remove_brain_skill(dest)
    check(not (dest / "SKILL.md").exists() and not (dest / "references").exists() and (dest / "a-moi.txt").exists(),
          "désinstallation : la skill et ses références retirées, le reste du dossier gardé", list(dest.rglob("*")))
else:
    check(False, "installation classique : SKILL.md et ses fichiers de référence posés (install.write_brain_skill)")

# ------------------------------------------------------------------ 4. un README seul n'est pas un projet
cases = {"readme": (["README.md"], False), "readme-claude": (["README.md", "CLAUDE.md"], False),
         "python": (["main.py"], True), "node": (["package.json"], True), "site": (["index.html"], True),
         "documents": (["notes.md", "plan.md", "budget.csv"], True), "make": (["Makefile"], True)}
wrong = []
for name, (files, want) in cases.items():
    d = TMP / "dossiers" / name
    d.mkdir(parents=True)
    for f in files:
        (d / f).write_text("x\n", encoding="utf-8")
    if mapper.looks_like_project(d) != want:
        wrong.append(name)
(TMP / "dossiers" / "git" / ".git").mkdir(parents=True)
(TMP / "dossiers" / "git" / "README.md").write_text("x\n", encoding="utf-8")
check(not wrong and mapper.looks_like_project(TMP / "dossiers" / "git"),
      "projet : .git, package.json, un fichier source ou 3 documents ; pas un README seul (ni README + CLAUDE.md)", wrong)
set_config("auto_map", {"enabled": True, "refresh_minutes": 10})
hook("session-start", "r1", cwd=TMP / "dossiers" / "readme", source="startup")
hook("session-start", "r2", cwd=TMP / "dossiers" / "python", source="startup")
b = Brain.load()
check(not b.project_for_path(str(TMP / "dossiers" / "readme")) and b.project_for_path(str(TMP / "dossiers" / "python")),
      "démarrage dans un dossier qui n'a qu'un README : aucun projet créé (un dossier de code, si)",
      [p["id"] for p in b.projects()])
from brainkit import hooks  # noqa: E402
old_auto = {"source": "auto", "meta": {"path": str(TMP / "dossiers" / "readme")}}
check(hasattr(hooks, "_mappable") and not hooks._mappable(old_auto, str(TMP / "dossiers" / "readme"))
      and hooks._mappable(dict(old_auto, source="map"), str(TMP / "dossiers" / "readme")),
      "projet créé tout seul autrefois pour un README seul : plus recartographié toutes les 10 min (un projet ajouté "
      "à la main, si)")
set_config("auto_map", {"enabled": False, "refresh_minutes": 10})
vues.wait(120)

# ------------------------------------------------------------------ 5. mode éco : descriptions des skills (décision E2)
ECO = TMP / "eco"


def eco_world(name, settings, config=None):
    root = ECO / name
    (root / "claude").mkdir(parents=True)
    (root / "brain").mkdir(parents=True)
    (root / "claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    (root / "brain" / "config.json").write_text(json.dumps({"pc": {"enabled": False}, **(config or {})}),
                                                encoding="utf-8")
    return root, dict(os.environ, CLAUDE_CONFIG_DIR=str(root / "claude"), BRAIN_HOME=str(root / "brain"))


def settings_of(root):
    return json.loads((root / "claude" / "settings.json").read_text(encoding="utf-8"))


root, env = eco_world("neuf", {"theme": "dark"})
c, out = run("eco", "--appliquer", env=env)
s = settings_of(root)
check(c == 0 and s.get("skillListingMaxDescChars") == 250 and s.get("skillListingBudgetFraction") == 0.005
      and s.get("theme") == "dark", "eco --appliquer : skillListingMaxDescChars 250 posé, fraction 0,5 % gardée", s)
c, out = run("eco", env=env)
check("skillListingMaxDescChars" in out, "brain eco : le réglage est dans l'état", out[-600:])
c, out = run("eco", "--annuler", env=env)
check(c == 0 and settings_of(root) == {"theme": "dark"}, "eco --annuler : retiré, comme avant", settings_of(root))
root, env = eco_world("place-a-moi", {"skillListingBudgetFraction": 0.02})
run("eco", "--appliquer", env=env)
check("skillListingMaxDescChars" not in settings_of(root) and settings_of(root)["skillListingBudgetFraction"] == 0.02,
      "place de la liste réglée par l'utilisateur : ni gardée autrement, ni descriptions coupées", settings_of(root))
root, env = eco_world("leviers-v3", {"bashOutputMaxChars": 10000, "autoCompactWindow": 200000,
                                     "skillListingBudgetFraction": 0.005, "autoMemoryEnabled": False},
                      {"eco": {"applique_le": "2026-10-01T00:00:00", "leviers": 3,
                               "pose": {"cles": {"skillListingBudgetFraction": 0.005, "autoMemoryEnabled": False}}}})
(root / "work").mkdir()
obj = hook("session-start", "e1", cwd=root / "work", env=env, source="startup")
line = next((ln for ln in (ctx(obj) + "\n" + "\n".join(str(v) for v in obj.values())).splitlines() if "⚡" in ln), "")
cfg = json.loads((root / "brain" / "config.json").read_text(encoding="utf-8"))
check(settings_of(root).get("skillListingMaxDescChars") == 250 and "250 caractères" in line
      and cfg["eco"].get("leviers") == 4,
      "installation qui avait le mode éco : le nouveau réglage posé une fois et annoncé", (settings_of(root), line))
obj = hook("session-start", "e2", cwd=root / "work", env=env, source="startup")
check("⚡" not in ctx(obj), "annoncé une seule fois", ctx(obj)[-300:])

# ------------------------------------------------------------------ 6. tâche des vues : seulement ce qui a changé
OUTS = {"MEMOIRES.md": EXPORT_FILE, "cerveau.html": VIZ_FILE, "cerveau-2d.html": VIZ2D_FILE,
        "mots.bin": STATE_DIR / "mots.bin", "termes.bin": STATE_DIR / "termes.bin", "BRAIN.md": INDEX_FILE}


def stamps():  # BRAIN.md : son contenu (la tâche des vues remet sa date à celle de ses sources, même gardé)
    return {k: ((f.read_text(encoding="utf-8") if k == "BRAIN.md" else f.stat().st_mtime_ns) if f.exists() else None)
            for k, f in OUTS.items()}


def changed(before):
    after = stamps()
    return sorted(k for k in OUTS if after[k] != before[k])


vues.wait(180)
vues.run_now()
transcript = TMP / "claude" / "projects" / "-boutique" / "s1.jsonl"
transcript.parent.mkdir(parents=True)
transcript.write_text("\n".join(json.dumps(x) for x in [
    {"type": "user", "cwd": str(WORK), "message": {"role": "user", "content": "ok merci"}},
    {"type": "assistant", "message": {"id": "m1", "role": "assistant", "content": [{"type": "text", "text": "De rien."}]}},
]) + "\n", encoding="utf-8")
before = stamps()
hook("session-end", "v1", transcript_path=str(transcript))
vues.wait(180)
check(all(before.values()) and not set(changed(before)) - {"BRAIN.md"},
      "fin de session qui n'a rien changé : la tâche des vues ne refait ni l'export, ni les vues 3D et 2D, ni les mots "
      "(BRAIN.md au plus : sa liste des projets suit leur dernière session)", changed(before))
g = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
g["nodes"]["boutique"]["meta"]["mapped"] = now  # le cartographe réécrit graph.json pour la date de la carte
GRAPH_FILE.write_text(json.dumps(g), encoding="utf-8")
before = stamps()
vues.request()
vues.wait(180)
check(not changed(before), "graph.json réécrit pour la date de la carte seulement : aucune vue refaite", changed(before))
before = stamps()
store.bump_hits(["b3", "r1"])  # compteurs de rappel : montrés dans l'export et les vues 3D, pas dans les mots
vues.request()
vues.wait(180)
check({"MEMOIRES.md", "cerveau.html", "cerveau-2d.html"} <= set(changed(before))
      and not {"mots.bin", "termes.bin"} & set(changed(before)),
      "compteurs de rappel : export et vues 3D refaits, mots gardés", changed(before))
before = stamps()
with Brain.edit() as eb:
    eb.add("fact", "Nouveau transporteur pour les colis lourds", "Les colis de plus de 5 kg partent avec DPD.",
           project="boutique")
vues.request()
vues.wait(180)
check(set(OUTS) - {"BRAIN.md"} <= set(changed(before)) and "Nouveau transporteur" in EXPORT_FILE.read_text("utf-8"),
      "un souvenir ajouté : toutes les vues refaites", changed(before))
VIZ2D_FILE.unlink()
vues.request()
vues.wait(180)
check(VIZ2D_FILE.exists(), "une vue effacée est refaite", VIZ2D_FILE.exists())
saved = vues._today if hasattr(vues, "_today") else None
before = stamps()
try:
    vues._today = lambda: "2099-01-01"
    with vues.lock():
        done = vues.regenerate()
finally:
    if saved:
        vues._today = saved
check(isinstance(done, list) and "export" in done and "vue 3D" not in done and "MEMOIRES.md" in changed(before)
      and "cerveau.html" not in changed(before), "le lendemain : l'export refait (sa date), pas la vue 3D", done)
before = stamps()
c, out = run("vues")
check(c == 0 and set(OUTS) - {"BRAIN.md"} <= set(changed(before)), "`brain vues` à la main : toutes refaites",
      changed(before))
vues.wait(180)

if not remove_tree(TMP, wait=60):
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
