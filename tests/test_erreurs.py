"""Erreurs et messages (étape 6 du plan) : jamais de trace Python, des messages en français, le bon code de sortie.

Un échantillon des 400 cas de l'audit des commandes (scratchpad/audit/commandes/run_cases.py), rejoué sur un petit
cerveau d'essai : valeurs manquantes, inconnues, négatives, commençant par « - », réseau coupé. Puis `brain config`
(clé et type vérifiés avant d'écrire, valeur fausse déjà écrite remplacée par son défaut et signalée une fois),
`brain tokens` sur un transcript sans compteur, le serveur MCP (arguments vérifiés, réponses en français), et l'analyse du
graphe prise en cache par `brain q` et le serveur MCP au lieu d'être recalculée sur place.

Lancement : python tests/test_erreurs.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-erreurs-test-"))
CODE = Path(__file__).resolve().parent.parent
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS", "BRAIN_DEBUG"):
    os.environ.pop(k, None)
SEED, CASE, CFG, HOME = TMP / "seed", TMP / "brain", TMP / "claude", TMP / "home"
P1, P2 = TMP / "proj un", TMP / "proj2"
os.environ.update(CLAUDE_CONFIG_DIR=str(CFG), BRAIN_HOME=str(CASE), HOME=str(HOME), USERPROFILE=str(HOME),
                  PYTHONIOENCODING="utf-8",
                  # réseau coupé (proxy mort) : prompts.chat et les autres sites répondent « connexion refusée »
                  HTTPS_PROXY="http://127.0.0.1:1", HTTP_PROXY="http://127.0.0.1:1", https_proxy="http://127.0.0.1:1",
                  http_proxy="http://127.0.0.1:1", NO_PROXY="")
for d in (P1 / "src", P2 / "src", CFG, HOME):
    d.mkdir(parents=True)
(P1 / "src" / "app.py").write_text("import os\n\ndef login(user):\n    return os.getcwd()\n\nclass Cart:\n    pass\n")
(P1 / "src" / "util.py").write_text("from app import login\n\ndef helper():\n    return login('x')\n")
(P2 / "src" / "main.js").write_text("export function render(){}\n")
sys.path.insert(0, str(CODE))
# Messages d'argparse ou de Python restés en anglais (le cerveau parle français à l'utilisateur et à Claude)
ENGLISH = re.compile(r"Traceback|unrecognized arguments|arguments are required|invalid choice|expected one argument|"
                     r"invalid \w+ value|error:|usage:|No such file|\[Errno|urlopen error|show this help")


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def brain(*args, stdin=None, cwd=P1, home=None):
    env = dict(os.environ, BRAIN_HOME=str(home or os.environ["BRAIN_HOME"]))
    r = subprocess.run([sys.executable, str(CODE / "brain.py"), *map(str, args)], input=stdin, capture_output=True,
                       env=env, cwd=str(cwd), timeout=120)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def fresh():
    """Chaque cas part d'une copie neuve du cerveau d'essai, dans son propre dossier : aucun cas ne dépend d'un autre, et
    la tâche de fond des vues lancée par un cas ne gêne pas le suivant."""
    global CASE
    CASE = TMP / f"cas{len(list(TMP.glob('cas*')))}"
    shutil.copytree(SEED, CASE)
    os.environ["BRAIN_HOME"] = str(CASE)


# ------------------------------------------------------------------ cerveau d'essai : 2 projets cartographiés, 8 souvenirs
now = time.strftime("%Y-%m-%dT%H:%M:%S")
SEED.mkdir()
(SEED / "config.json").write_text(json.dumps({  # rien d'autre en arrière-plan pendant les cas
    "auto_map": {"enabled": False}, "eco": {"auto": False}, "backup": {"enabled": False}, "pc": {"enabled": False},
    "journal": {"rattrapage_le": now}, "garde": {"le": now}}), encoding="utf-8")
brain("proj", "add", P1, home=SEED)
brain("proj", "add", P2, home=SEED)
for i, (ty, title) in enumerate([("decision", "Robots.txt bloque les robots d'IA"),
                                 ("learning", "Le login expire après trente minutes"),
                                 ("fact", "Le panier garde les articles sept jours"), ("todo", "Recompter le stock des bols"),
                                 ("fact", "Balises SEO des fiches produits"), ("learning", "Relancer les paniers abandonnés"),
                                 ("decision", "Connexion par lien magique"), ("fact", "Sitemap envoyé à Google")], 1):
    extra = ["--due", "demain"] if ty == "todo" else []
    brain("add", "-t", ty, "-T", title, "-b", f"{title}, réglé ainsi (note {i}).", "--id", f"m{i}", "--force", *extra,
          home=SEED)
brain("map", P1, "--quiet", home=SEED)
brain("map", P2, "--quiet", home=SEED)
brain("report", home=SEED)  # analyse du graphe à jour au départ
NOT_DIR = P1 / "src" / "app.py"

# (arguments, code de sortie attendu, texte attendu dans la sortie ou None) — 0 réussite, 1 échec, 2 ligne de commande
CASES = [
    # réussites
    (["q", "panier"], 0, "panier"), (["q", "--", "-rf"], 0, None), (["ls"], 0, "Sitemap"),
    (["add", "-T", "Café « œuvre » naïve", "-b", "it's \"quoted\" $HOME"], 0, "✓ mémorisé"),
    (["add", "--title=-rf", "-b", "x"], 0, "✓ mémorisé"), (["deps", "src/util.py"], 0, None),
    (["explain", "src/app.py"], 0, "Symboles"), (["where", "login"], 0, "src/app.py"),
    (["path", "src/util.py", "src/app.py"], 0, "saut"), (["link", "m1", "m2"], 0, "✓ lien"),
    (["config", "recall.enabled", "false"], 0, "✓"), (["config", "recall.max_items", "4"], 0, "✓"),
    (["config", "mcp.groupes", "wiki"], 0, "✓"), (["tokens"], 0, None), (["stats"], 0, None), (["context"], 0, None),
    (["q", "-h"], 0, "afficher cette aide"), (["--version"], 0, "brain"), (["impact", "login"], 0, "Impact"),
    # échecs : code 1 et un message en français qui commence par ✗ (avant : code 0 pour la plupart)
    (["deps", "zzz.py"], 1, "aucun fichier ne correspond"), (["explain", "zzzqq"], 1, "rien trouvé"),
    (["path", "zzz", "yyy"], 1, "introuvable"), (["where", "zzzqq"], 1, "introuvable"),
    (["echange", "voir", "zzz/zzz"], 1, "introuvable"), (["echange", "partager", "zzz"], 1, "introuvable"),
    (["echange", "adopter", "a/b"], 1, "introuvable"), (["config", "zzz.yyy", "1"], 1, "clé inconnue"),
    (["config", "recall.k", "abc"], 1, "clé inconnue"), (["config", "recall.max_items", "abc"], 1, "nombre entier"),
    (["config", "recall.max_items", "-3"], 1, "d'au moins 0"), (["config", "recall.enabled", "é"], 1, "oui/non"),
    (["config", "skills.paste", "n"], 1, "auto, propose, off"), (["config", "recall.min_cov", "1.5"], 1, "de 0 à 1"),
    (["link", "m1", "m1"], 1, "lui-même"), (["unlink", "m4", "m8"], 1, "aucun lien"),
    (["add", "-T", "x", "--link", "zzzz"], 1, "rien n'est mémorisé"),
    (["add", "-T", "x", "--replaces", "zzzz"], 1, "rien n'est mémorisé"),
    (["add", "-T", "x", "--id", "m1"], 1, "déjà pris"), (["edit", "m5"], 1, "rien à modifier"),
    (["delegation", "--modele", "eclaireur"], 1, "nom=modèle"), (["apprendre", "oublier", "zzz", "x"], 1, "inconnue"),
    (["outils", "scan", "-1"], 1, "au moins 1"), (["backup", "--restore", TMP / "absent.zip"], 1, "introuvable"),
    (["backup", "--to", NOT_DIR], 1, "pas un dossier"), (["compact", "--apprendre", "npm"], 1, "Aucune sortie"),
    (["prompts", "get", "zzz"], 1, "connexion impossible"), (["prompts", "seo"], 1, "injoignable"),
    (["done", "m1"], 1, "pas un à-faire"), (["show", "zzz"], 1, "introuvable"), (["impact", "zzzqq"], 4, "rien trouvé"),
    # ligne de commande : code 2, message d'argparse traduit, et la façon de donner une valeur qui commence par « - »
    (["q"], 2, "argument manquant"), (["q", "-rf"], 2, "brain q -- -rf"), (["show", "-rf"], 2, "brain show -- -rf"),
    (["add", "-T", "-rf", "-b", "x"], 2, "-T=-rf"), (["config", "recall.enabled", "-rf"], 2, "-- -rf"),
    (["q", "x", "-k", "-5"], 2, "de 1 à 200"), (["q", "x", "-k", "0"], 2, "de 1 à 200"),
    (["q", "x", "-k", "abc"], 2, "nombre entier attendu"), (["ls", "-n", "-1"], 2, "d'au moins 1"),
    (["tokens", "--hours", "-5"], 2, "refusé"), (["tokens", "--hours", "abc"], 2, "nombre attendu"),
    (["neurone", "apprendre", "--jours", "-1"], 2, "refusé"), (["obs", "--days", "-1"], 2, "refusé"),
    (["journal", "-n", "-1"], 2, "refusé"), (["pc", "--seconds", "-1"], 2, "refusé"),
    (["delegation", "--jours", "-3"], 2, "refusé"), (["add", "-T", "x", "-i", "9"], 2, "de 1 à 5"),
    (["edit", "m5", "-i", "0"], 2, "de 1 à 5"), (["impact", "login", "-d", "0"], 2, "de 1 à 5"),
    (["map", P2, "--max-files", "0"], 2, "d'au moins 1"), (["zzzz"], 2, "commande inconnue"),
    (["neurone", "zzz"], 2, "choix inconnu"), (["index", "zzz"], 2, "argument inattendu"),
]
for args, want, text in CASES:
    fresh()
    code, out = brain(*args)
    label = "brain " + " ".join(str(x) for x in args)
    check("Traceback" not in out, f"{label} : aucune trace Python", out)
    check(not ENGLISH.search(out), f"{label} : message en français", out)
    check(code == want, f"{label} : code de sortie {want}", f"code {code} : {out}")
    if text:
        check(text in out, f"{label} : la sortie dit « {text} »", out)
    if want:
        check("✗" in out, f"{label} : l'échec est marqué ✗", out)

# ------------------------------------------------------------------ config : rien de faux n'est écrit
fresh()
before = (CASE / "config.json").read_text(encoding="utf-8")
for key, value in (("zzz.yyy", "1"), ("recall.k", "abc"), ("inject.max_tokens", "abc"), ("recall.max_items", "-3")):
    brain("config", key, value)
check((CASE / "config.json").read_text(encoding="utf-8") == before, "config : une clé inconnue ou une valeur fausse "
      "n'est jamais écrite")
code, out = brain("config", "recall.max_items", "abc")
check("ex. `brain config recall.max_items 3`" in out, "config : le refus donne le type attendu et un exemple", out)
for key, value, stored in (("recall.enabled", "False", False), ("recall.enabled", "oui", True),
                           ("mcp.groupes", '["wiki", "boutique"]', ["wiki", "boutique"]), ("wiki.path", "null", None),
                           ("skills.triggers.ma-skill", "bonjour", ["bonjour"]), ("commun.repo", "a/b", "a/b"),
                           ("eco.alerte_contexte", "[]", [])):
    code, out = brain("config", key, value)
    cur = json.loads((CASE / "config.json").read_text(encoding="utf-8"))
    for part in key.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    check(code == 0 and cur == stored, f"config : {key} {value} accepté, écrit {json.dumps(stored)}", out)

# ------------------------------------------------------------------ config : une valeur déjà fausse ne casse plus rien
fresh()
cfg = json.loads((CASE / "config.json").read_text(encoding="utf-8"))
cfg.update(inject={"max_tokens": "abc"}, recall={"max_items": -2, "enabled": "False"}, skills="n'importe quoi")
(CASE / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
code, out = brain("context")
check(code == 0 and "Traceback" not in out and "Cerveau" in out,
      "config fausse (« abc » pour un nombre, texte pour une section) : l'injection du démarrage marche (défauts)", out)


def session_start(sid):
    r = subprocess.run([sys.executable, str(CODE / "brain.py"), "hook", "session-start"], capture_output=True,
                       input=json.dumps({"session_id": sid, "cwd": str(P1), "source": "startup"}).encode(),
                       env=dict(os.environ), cwd=str(P1), timeout=120)
    out = r.stdout.decode("utf-8", "replace")
    try:
        return json.loads(out) if out.strip() else {}
    except ValueError:
        return {"brut": out + r.stderr.decode("utf-8", "replace")}


first, second = session_start("s1"), session_start("s2")
said = first.get("systemMessage") or ""
check("réglage ignoré" in said and "inject.max_tokens" in said and "nombre entier" in said
      and "additionalContext" in json.dumps(first.get("hookSpecificOutput") or {}),
      "config fausse : le démarrage injecte quand même, et le dit à l'utilisateur (clé, type attendu)", first)
check("réglage ignoré" not in (second.get("systemMessage") or "") and second.get("hookSpecificOutput"),
      "config fausse : dit une seule fois, pas à chaque session", second)
code, out = brain("doctor")
check("✗ réglages (config.json)" in out and "inject.max_tokens" in out, "brain doctor : la valeur fausse est montrée",
      out)
code, out = brain("config", "recall.enabled", "true")
check(code == 0 and json.loads((CASE / "config.json").read_text(encoding="utf-8"))["skills"] == "n'importe quoi",
      "config : écrire une autre clé ne touche pas aux valeurs fausses déjà là (rien n'est perdu sans le dire)", out)

# ------------------------------------------------------------------ brain tokens : lignes de transcript sans compteur
fresh()
proj = CFG / "projects" / "-tmp-x"
proj.mkdir(parents=True)
stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def asst(mid, usage, content=None):
    return json.dumps({"type": "assistant", "timestamp": stamp, "requestId": f"r{mid}", "message": {
        "id": f"m{mid}", "model": "claude-sonnet-5-5", "content": content or [{"type": "text", "text": "ok"}],
        "usage": usage}})


lines = [json.dumps({"type": "user", "timestamp": stamp, "message": {"content": "bonjour"}}),
         asst(1, {"input_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 9000, "output_tokens": 50}),
         asst(2, {"input_tokens": None, "cache_read_input_tokens": None, "cache_creation_input_tokens": None}),
         asst(3, {"input_tokens": "abc", "output_tokens": None}), asst(4, "pas un objet"), asst(5, {}),
         json.dumps({"type": "assistant", "message": "texte"}), json.dumps([1, 2]), "{pas du json",
         asst(6, {"input_tokens": 10, "cache_read_input_tokens": 9000, "cache_creation_input_tokens": 500, "output_tokens": 40})]
(proj / "s1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
for cmd in (["tokens"], ["optimize"]):
    code, out = brain(*cmd)
    check(code == 0 and "Traceback" not in out, f"brain {cmd[0]} : une ligne sans compteur (null, texte, absent) est "
          "sautée, pas de plantage", out)
code, out = brain("tokens")
check("Requêtes : 2 " in out and "sur 2 requête(s)" in out, "brain tokens : les 2 vraies requêtes sont comptées, les "
      "lignes sans compteur ni comptées ni prises pour des requêtes", out)

# ------------------------------------------------------------------ serveur MCP : arguments vérifiés, réponses en français
fresh()


def mcp(*calls):
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}]
    msgs += [{"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": n, "arguments": a}}
             for i, (n, a) in enumerate(calls, 1)]
    msgs += [{"jsonrpc": "2.0", "id": 98, "method": "tools/call", "params": "x"}, {"jsonrpc": "2.0", "id": 99, "method": "zzz"}]
    r = subprocess.run([sys.executable, str(CODE / "brain.py"), "mcp"], capture_output=True, cwd=str(P1), timeout=120,
                       input=("\n".join(json.dumps(m) for m in msgs) + "\n").encode(), env=dict(os.environ))
    out = {}
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        o = json.loads(line)
        res = o.get("result") or {}
        out[o["id"]] = ((res.get("content") or [{}])[0].get("text", ""), res.get("isError")) if "content" in res \
            else (json.dumps(o.get("error") or res, ensure_ascii=False), None)
    return out, r.stderr.decode("utf-8", "replace")


got, err = mcp(("memory_add", {"type": "fact", "title": "-rf efface tout", "body": "-rf efface le dossier sans retour"}),
               ("memory_search", {"query": "-rf efface"}), ("memory_show", {"id": "rf-efface-tout"}),
               ("memory_update", {"id": "rf-efface-tout", "append": "-x aussi"}),
               ("memory_search", {}), ("memory_search", {"query": "x", "limit": "abc"}),
               ("memory_search", {"query": ["liste"]}), ("memory_add", {"type": "zzz", "title": "x", "body": "y"}),
               ("memory_add", {"type": "fact", "title": "x"}), ("memory_update", {"id": "m1", "importance": 9}),
               ("memory_update", {"id": "m1", "done": "peut-être"}), ("zzz", {}), ("memory_todo", [1]),
               ("memory_add", {"type": "fact", "title": "y", "body": "z", "replaces": "-zz"}),
               ("memory_search", {"query": "x", "page": "deux"}))
check(got.get(1, ("", True))[1] is False and "✓ mémorisé" in got[1][0], "MCP : un titre qui commence par « - » est "
      "mémorisé (avant : refus d'argparse, en anglais)", got.get(1))
check(got.get(2, ("", True))[1] is False and "-rf efface tout" in got[2][0], "MCP : une recherche qui commence par « - »",
      got.get(2))
check(got.get(3, ("", True))[1] is False and "-rf efface tout" in got[3][0], "MCP : memory_show", got.get(3))
check(got.get(4, ("", True))[1] is False and "✓ modifié" in got[4][0], "MCP : un ajout qui commence par « - »", got.get(4))
for i, want in ((5, "argument manquant : « query »"), (6, "nombre entier attendu"), (7, "texte attendu"),
                (8, "« type » : « zzz » inconnu"), (9, "argument manquant : « body »"), (10, "hors limites, de 1 à 5"),
                (11, "vrai ou faux attendu"), (12, "outil inconnu : zzz"), (13, "objet JSON attendu"),
                (14, "introuvable"), (15, "nombre entier attendu")):
    text, is_err = got.get(i, ("(pas de réponse)", None))
    check(is_err is True and want in text, f"MCP : refus en français (« {want} »)", text)
check(all("Traceback" not in t and not ENGLISH.search(t) for t, _ in got.values()) and "Traceback" not in err,
      "MCP : aucune trace Python ni message anglais dans les résultats", got)
check("méthode inconnue" in got.get(99, ("",))[0], "MCP : méthode inconnue dite en français", got.get(99))

# ------------------------------------------------------------------ synchronisation du wiki : dépôt injoignable
fresh()
ident = "test" + "@" + "example.com"  # en morceaux : le contrôle des adresses de `brain publish` lit ce fichier
os.environ.update(GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL=ident, GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL=ident,
                  GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="commit.gpgsign", GIT_CONFIG_VALUE_0="false",
                  GIT_CONFIG_KEY_1="init.defaultBranch", GIT_CONFIG_VALUE_1="main")
WIKI = TMP / "wiki"
WIKI.mkdir()
subprocess.run(["git", "init", "-q", str(WIKI)], capture_output=True)
code, out = brain("wiki", "init", WIKI, "--no-push")
check(code == 0 and (WIKI / ".git").is_dir(), "wiki d'essai créé (dépôt git local)", out)
for url, want in ((str(TMP / "absent.git"), "dépôt introuvable"), ("https://127.0.0.1:1/cerveau.git", "GitHub injoignable")):
    subprocess.run(["git", "-C", str(WIKI), "remote", "remove", "origin"], capture_output=True)
    subprocess.run(["git", "-C", str(WIKI), "remote", "add", "origin", url], capture_output=True)
    (WIKI / "note.md").write_text(f"Note pour {url}\n", encoding="utf-8")
    code, out = brain("wiki", "sync")
    check(f"✗ pull : {want}" in out and "rien n'est perdu" in out and "✓ pull" not in out and "✓ push" not in out
          and not re.search(r"^\s*(fatal|error):", out, re.M) and "Traceback" not in out,
          f"wiki sync, origine {url} : « {want} » dit en français, avec quoi faire (avant : rien sur le pull, la sortie "
          "brute de git pour le push)", out)
    state = json.loads((CASE / "state" / "wiki-sync.json").read_text(encoding="utf-8")) \
        if (CASE / "state" / "wiki-sync.json").is_file() else {}
    check("conflict" not in state, "wiki sync : un dépôt injoignable n'est pas noté comme un conflit", state)
for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_CONFIG_COUNT",
          "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "GIT_CONFIG_KEY_1", "GIT_CONFIG_VALUE_1"):
    os.environ.pop(k, None)

# ------------------------------------------------------------------ brain q et MCP : l'analyse du graphe prise en cache
fresh()
os.environ["BRAIN_HOME"] = str(CASE)
from brainkit import graph, vues  # noqa: E402  (BRAIN_HOME posé : le cerveau d'essai)
from brainkit.common import read_json  # noqa: E402
from brainkit.store import Brain  # noqa: E402


def analysis_sig():
    return (read_json(graph.ANALYSIS_FILE, {}) or {}).get("sig")


with vues.lock():  # la tâche des vues ne peut pas refaire l'analyse tant que le test tient leur verrou
    before = analysis_sig()
    with Brain.edit() as b:
        b.add("fact", "Le transporteur livre le panier en 48 h", "Le panier part chez le transporteur en 48 h.")
    current = graph._signature(Brain.load())
    code, out = brain("q", "transporteur panier")
    check(code == 0 and "transporteur" in out and analysis_sig() == before != current,
          "brain q juste après un changement : l'analyse en cache sert (pas de recalcul sur place, 1 à 4 s sur un gros "
          "cerveau), la tâche des vues la refera", f"analyse {analysis_sig()} avant {before} contenu {current} : {out}")
    got, _ = mcp(("memory_search", {"query": "transporteur panier"}))
    check(got.get(1, ("", True))[1] is False and "transporteur" in got[1][0] and analysis_sig() == before,
          "serveur MCP juste après un changement : l'analyse en cache sert aussi", got.get(1))
code, out = brain("report", "--force")
check(code == 0 and analysis_sig() == current, "brain report --force : l'analyse est refaite quand on la demande",
      analysis_sig())
vues.wait(120)  # la tâche des vues demandée par q finit avant d'effacer le dossier

from brainkit.common import remove_tree  # noqa: E402
if not remove_tree(TMP, wait=60):
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
