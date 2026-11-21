"""Délégation aux modèles moins chers (delegation.py) et couche « plus » (plus.py), sur de faux PC : classement d'une
consigne, aiguillage d'un sous-agent lancé sans modèle (hook PreToolUse de l'outil Agent) et tous ses garde-fous, consigne
de démarrage, réflexe par message, fusion avec la sortie du hook principal (Python ou brain.exe simulé), agents livrés,
installation classique, mesure des économies.

Lancement : python tests/test_delegation.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-delegation-test-"))
CODE = Path(__file__).resolve().parent.parent
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "CLAUDE_CODE_SUBAGENT_MODEL", "BRAIN_PLUS", "BRAIN_IMPL"):
    os.environ.pop(k, None)
os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "unite" / "claude")  # import en direct : jamais le vrai PC
os.environ["BRAIN_HOME"] = str(TMP / "unite" / "brain")
sys.path.insert(0, str(CODE))


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


class World:
    """Un faux PC : ~/.claude et ~/.claude/brain."""

    def __init__(self, name, **extra):
        self.root = TMP / name
        self.home, self.brain_dir, self.work = self.root / "claude", self.root / "brain", self.root / "work"
        for d in (self.home, self.brain_dir, self.work):
            d.mkdir(parents=True, exist_ok=True)
        cfg = self.brain_dir / "config.json"  # veille PC coupée : la RAM du vrai PC ne doit pas changer les messages
        cfg.exists() or cfg.write_text(json.dumps({"pc": {"enabled": False}}), encoding="utf-8")
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.home), "BRAIN_HOME": str(self.brain_dir), **extra}

    def run(self, *args, inp=None, env=None):
        r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), *map(str, args)], capture_output=True,
                           timeout=180, input=(inp or "").encode("utf-8"), cwd=str(self.work), env=env or self.env)
        return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")

    def hook(self, event, sid="s1", env=None, **payload):
        data = {"session_id": sid, "cwd": str(self.work), **payload}
        c, out = self.run("hook", event, inp=json.dumps(data), env=env)
        try:
            return c, json.JSONDecoder().raw_decode(out.lstrip())[0] if out.strip() else {}, out
        except ValueError:
            return c, None, out

    def context(self, event, sid="s1", **payload):
        _, obj, out = self.hook(event, sid, **payload)
        return ((obj or {}).get("hookSpecificOutput") or {}).get("additionalContext") or "", out


def agent(prompt, kind="general-purpose", sid="a1", mode="default", **more):
    inp = {"description": "tâche", "prompt": prompt, "subagent_type": kind, "run_in_background": False}
    inp.update(more.pop("inp", {}))
    return {"session_id": sid, "permission_mode": mode, "hook_event_name": "PreToolUse", "tool_name": "Agent",
            "tool_input": inp, **more}


from brainkit import delegation, plus  # noqa: E402

# ------------------------------------------------------------------ 1. classement d'une consigne
CASES = [
    ("Search the codebase and list all files that define API endpoints", "lecture"),
    ("Trouve où est définie la fonction slugify et liste ses appels", "lecture"),
    ("Lis le fichier README.md et résume-le en cinq lignes", "lecture"),
    ("Find where the retry logic lives and explain how it works", "jugement"),
    ("Cherche les usages de fetch et compare les deux implémentations", "jugement"),
    ("Écris les tests unitaires de la fonction slugify dans tests/test_text.py", "mecanique"),
    ("Rename the function getUser to fetchUser in every file", "mecanique"),
    ("Traduis tous les messages d'erreur en français", "mecanique"),
    ("Find the root cause of the failing login test and fix it", "dur"),
    ("Pourquoi ce test échoue ? trouve la cause", "dur"),
    ("Conçois l'architecture du module de paiement", "dur"),
    ("Review this pull request for security issues", "dur"),
    ("Implement the new export feature in the dashboard", None),
    ("Ajoute un bouton de partage sur la page produit", None),
    ("Bonjour", None),
]
bad = [(t, k, delegation.classify(t)) for t, k in CASES if delegation.classify(t) != k]
check(not bad, f"classement : {len(CASES)} consignes (lecture, jugement, mécanique, difficile, inconnu)", bad)
check(delegation.classify("Find where the export feature is implemented and how it was created") is None
      and delegation.classify("Find where the export feature is implemented and how it was created", readonly=True) == "jugement"
      and delegation.classify("List the files that create or update orders", readonly=True) == "lecture"
      and delegation.classify("List general settings files") == "lecture",
      "classement : pour un sous-agent en lecture seule, un verbe d'écriture ne décrit que ce qu'il cherche")
check(delegation.target("Explore", "lecture") == "haiku" and delegation.target("Explore", "jugement") == "sonnet"
      and delegation.target("Explore", "dur") is None and delegation.target("Explore", None) is None,
      "cible : Explore en lecture → Haiku, à comprendre → Sonnet, difficile ou flou → rien")
check(delegation.target("general-purpose", "mecanique") == "sonnet" and delegation.target("general-purpose", None) is None
      and delegation.target("general-purpose", "dur") is None and delegation.target("", "lecture") == "haiku",
      "cible : sous-agent générique — mécanique → Sonnet, lecture → Haiku, difficile ou flou → rien")
check(delegation.target("Plan", "lecture") is None and delegation.target("vercel:ai-architect", "lecture") is None,
      "cible : Plan et les agents d'un autre plugin ne sont jamais touchés")
check(delegation.target("general-purpose", None, "max") == "sonnet" and delegation.target("Explore", "dur", "max") == "sonnet"
      and delegation.target("vercel:ai-architect", "lecture", "max") is None,
      "cible en mode max : tout sous-agent générique au moins sur Sonnet, jamais ceux d'un autre plugin")

# ------------------------------------------------------------------ 2. aiguillage et garde-fous (route)
CFG = {"delegation": {"mode": "auto", "modeles": {}}}
READ = "Search the repository and list every markdown file"


def route(data, cfg=CFG):
    return delegation.route(data, cfg)[0]


def transcript(model, name="t.jsonl"):
    p = TMP / "unite" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"type": "assistant", "message": {"id": "m1", "model": model, "role": "assistant",
                                                             "content": [{"type": "text", "text": "ok"}]}}) + "\n",
                 encoding="utf-8")
    return str(p)


check(route(agent(READ, "Explore")) == "haiku", "aiguillage : Explore lancé sans modèle pour une recherche → Haiku")
check(route(agent(READ, "Explore", inp={"model": "opus"})) is None, "garde-fou : modèle choisi par l'appelant → rien")
check(route(agent(READ, "Explore", mode="auto")) is None, "garde-fou : mode de permission auto → rien (appel déjà relu)")
check(route(agent(READ, "Explore", agent_id="sub-1")) is None, "garde-fou : lancé depuis un sous-agent → rien")
check(route(agent(READ, "shopify-devkit:liquid-author")) is None, "garde-fou : agent d'un autre plugin → rien")
check(route(agent("Find the root cause of the crash", "Explore")) is None, "garde-fou : consigne difficile → rien")
os.environ["CLAUDE_CODE_SUBAGENT_MODEL"] = "sonnet"
check(route(agent(READ, "Explore")) is None, "garde-fou : CLAUDE_CODE_SUBAGENT_MODEL réglé par l'utilisateur → rien")
os.environ.pop("CLAUDE_CODE_SUBAGENT_MODEL")
check(route(agent(READ, "Explore", transcript_path=transcript("claude-haiku-5-5"))) is None,
      "garde-fou : modèle principal déjà Haiku → rien")
check(route(agent("Écris les tests unitaires de slugify", transcript_path=transcript("claude-sonnet-5-5"))) is None
      and route(agent(READ, "Explore", transcript_path=transcript("claude-sonnet-5-5"))) == "haiku",
      "garde-fou : modèle principal Sonnet → pas de Sonnet (pas moins cher), mais Haiku pour une lecture")
check(route(agent(READ, "Explore", transcript_path=transcript("claude-fable-5-2"))) == "haiku"
      and route(agent(READ, "Explore", transcript_path=str(TMP / "absent.jsonl"))) == "haiku",
      "aiguillage : modèle principal Fable, ou transcript introuvable → Haiku")
for m in ("conseil", "off"):
    check(route(agent(READ, "Explore"), {"delegation": {"mode": m}}) is None, f"mode {m} : aucun modèle changé")
check(route(agent("Implement the export feature"), {"delegation": {"mode": "max"}}) == "sonnet"
      and route(agent("Implement the export feature")) is None,
      "mode max : consigne non classée → Sonnet ; mode auto : rien")
check(route(agent(READ, "Explore"), {"delegation": {"mode": "auto", "modeles": {"Explore": "off"}}}) is None
      and route(agent("Design the schema"), {"delegation": {"mode": "auto", "modeles": {"general-purpose": "haiku"}}}) == "haiku",
      "choix de l'utilisateur : Explore=off coupe l'aiguillage de ce type, general-purpose=haiku l'impose")
check(route(agent("Cherche X", "cerveau:eclaireur")) is None
      and route(agent("Cherche X", "cerveau:eclaireur"), {"delegation": {"mode": "auto", "modeles": {"eclaireur": "sonnet"}}}) == "sonnet"
      and route(agent("Cherche X", "cerveau:eclaireur"), {"delegation": {"mode": "auto", "modeles": {"eclaireur": "haiku"}}}) is None,
      "agent du cerveau : son en-tête décide, sauf choix de l'utilisateur (eclaireur=sonnet)")
check(route({"tool_name": "Bash", "tool_input": {"command": "ls"}}) is None, "un autre outil que Agent n'est jamais touché")

# ------------------------------------------------------------------ 3. le hook pre-agent, de bout en bout
W = World("hook")
c, obj, out = W.hook("pre-agent", **{k: v for k, v in agent(READ, "Explore", sid="h1").items() if k != "session_id"}, sid="h1")
hso = (obj or {}).get("hookSpecificOutput") or {}
upd = hso.get("updatedInput") or {}
check(c == 0 and hso.get("hookEventName") == "PreToolUse" and upd.get("model") == "haiku"
      and upd.get("prompt") == READ and upd.get("subagent_type") == "Explore" and upd.get("run_in_background") is False,
      "hook : updatedInput reprend toute l'entrée de l'outil, avec le modèle moins cher", out)
check("permissionDecision" not in hso, "hook : aucune décision de permission (rien n'est approuvé à la place de l'utilisateur)", hso)
check("Haiku" in (obj or {}).get("systemMessage", "") and "delegation" in obj.get("systemMessage", ""),
      "hook : la première fois de la session, un message le dit à l'utilisateur (zéro token)", obj)
c, obj2, out = W.hook("pre-agent", **{k: v for k, v in agent(READ, "Explore").items() if k != "session_id"}, sid="h1")
check("systemMessage" not in (obj2 or {}) and ((obj2 or {}).get("hookSpecificOutput") or {}).get("updatedInput"),
      "hook : ensuite, aiguillage sans message", out)
c, obj3, out = W.hook("pre-agent", **{k: v for k, v in agent("Why does the build fail?").items() if k != "session_id"}, sid="h1")
check(c == 0 and not out.strip(), "hook : consigne difficile → aucune sortie (le sous-agent part comme prévu)", out)
c, out = W.run("hook", "pre-agent", inp="pas du json")
check(c == 0 and not out.strip(), "hook : entrée illisible → rien, jamais d'erreur", out)
c, out = W.run("delegation")
check(c == 0 and "mode auto" in out and "sous-agents lancés : 3" in out and "sur Haiku : 2" in out and "Explore 2" in out,
      "brain delegation : lancements vus et envois comptés", out)
check("`cerveau:eclaireur` Haiku" in out and "`cerveau:ouvrier` Sonnet" in out and "`cerveau:archiviste` Sonnet" in out,
      "brain delegation : les trois agents du cerveau et leur modèle", out)

# ------------------------------------------------------------------ 4. réglages par la commande
c, out = W.run("delegation", "--mode", "conseil")
check(c == 0 and "✓ délégation : conseil" in out, "brain delegation --mode conseil", out)
c, obj, out = W.hook("pre-agent", **{k: v for k, v in agent(READ, "Explore").items() if k != "session_id"}, sid="h2")
check(not out.strip(), "mode conseil : le hook ne change plus aucun modèle", out)
c, out = W.run("delegation", "--mode", "auto", "--modele", "eclaireur=sonnet", "--modele", "Explore=off")
check(c == 0 and "✓ eclaireur : sonnet" in out and "✓ Explore : off" in out, "brain delegation --modele (agent et type intégré)", out)
c, out = W.run("delegation")
check("`cerveau:eclaireur` Sonnet" in out, "brain delegation : le modèle choisi pour l'éclaireur est affiché", out)
c, obj, out = W.hook("pre-agent", **{k: v for k, v in agent(READ, "Explore").items() if k != "session_id"}, sid="h2")
check(not out.strip(), "Explore=off : plus d'aiguillage pour Explore", out)
c, obj, out = W.hook("pre-agent", **{k: v for k, v in agent("Cherche X", "cerveau:eclaireur").items() if k != "session_id"}, sid="h2")
check(((obj or {}).get("hookSpecificOutput") or {}).get("updatedInput", {}).get("model") == "sonnet",
      "eclaireur=sonnet : l'agent du cerveau est lancé sur le modèle choisi", out)
c, out = W.run("delegation", "--modele", "eclaireur=defaut", "--modele", "Explore=defaut")
check(c == 0 and out.count("modèle par défaut") == 2, "brain delegation --modele nom=defaut : retour à l'en-tête", out)
c, out = W.run("delegation", "--modele", "eclaireur=off")
check(c == 1 and "✗" in out, "brain delegation : « off » refusé pour un agent du cerveau", out)
c, out = W.run("delegation", "--modele", "inconnu=haiku")
check(c == 1 and "✗ inconnu" in out, "brain delegation : nom inconnu refusé", out)

# ------------------------------------------------------------------ 5. consigne de démarrage
S = World("start")
ctx, out = S.context("session-start", "d1")
check("Cerveau persistant" in ctx and "↪ Délégation" in ctx and "`cerveau:eclaireur` (Haiku)" in ctx
      and "`cerveau:ouvrier` (Sonnet)" in ctx and "`cerveau:archiviste` (Sonnet)" in ctx,
      "démarrage : la ligne de délégation suit l'injection du cerveau", ctx[-600:])
check(ctx.index("Cerveau persistant") < ctx.index("↪ Délégation") and len(ctx) < plus.MAX_CONTEXT,
      "démarrage : ajoutée à la fin, sous le plafond de contexte d'un hook", len(ctx))
line = next(ln for ln in ctx.splitlines() if ln.startswith("↪ Délégation"))
check(len(line) <= 420, f"démarrage : la ligne de délégation reste courte ({len(line)} car.)", line)
ctx, out = S.context("session-start", "d1", source="resume")
check("↪ Délégation" not in ctx, "reprise d'une session : la ligne n'est pas réinjectée (elle est encore dans l'historique)", ctx[-300:])
ctx, out = S.context("session-start", "d1", source="compact")
check("↪ Délégation" in ctx, "après une compaction : la ligne est resservie", ctx[-300:])
S.run("delegation", "--mode", "off")
ctx, out = S.context("session-start", "d2")
check("Cerveau persistant" in ctx and "↪ Délégation" not in ctx, "mode off : aucune ligne de délégation au démarrage", ctx[-300:])
S.run("delegation", "--mode", "auto")
c, obj, out = S.hook("session-start", "d4", env={**S.env, "CERVEAU_CLOUD": "1"})
cloud = ((obj or {}).get("hookSpecificOutput") or {}).get("additionalContext") or ""
check("↪ Délégation" not in cloud, "session cloud du wiki (plugin non installé) : pas d'agents, pas de ligne", cloud[-300:])

# ------------------------------------------------------------------ 6. réflexe par message
P = World("prompt")
P.hook("session-start", "p1")


def ask(text, sid="p1"):
    return P.context("prompt", sid, prompt=text)[0]


a = ask("cherche dans tout le projet où on utilise la vieille API et liste tous les fichiers concernés")
check("↪ Recherche ou lecture en masse" in a and "`cerveau:eclaireur` (Haiku" in a, "réflexe : recherche en masse → l'éclaireur", a)
check("↪" not in ask("cherche partout les appels à fetch dans tous les fichiers"), "réflexe : une seule fois par session et par genre")
a = ask("renomme la fonction getUser en fetchUser partout")
check("↪ Modification mécanique" in a and "`cerveau:ouvrier` (Sonnet)" in a, "réflexe : modification mécanique → l'ouvrier", a)
check("↪" not in ask("pourquoi ce test échoue ?", "p2") and "↪" not in ask("ajoute un bouton sur la page", "p2")
      and "↪" not in ask("où est le fichier de config ?", "p2"),
      "réflexe : rien sur une question, une tâche ordinaire ou une recherche d'un seul fichier")
check("↪" not in ask("liste tous les fichiers du dépôt et parcours tout le code", "p-ancienne"),
      "session ouverte avant la mise à jour (jamais démarrée avec les agents) : aucun conseil vers un agent qu'elle ne connaît pas")
for sid in ("p3", "p6"):
    P.hook("session-start", sid)
a = ask("résume ces deux articles : https://exemple.org/a et https://exemple.org/b", "p3")
check("`cerveau:eclaireur`" in a, "réflexe : plusieurs pages web à lire → l'éclaireur", a)
check("↪" not in ask("/compact dans tout le projet", "p4") and "↪" not in ask("<task-notification> dans tout le projet", "p4")
      and "↪" not in ask("Background (from the session x): cherche dans tout le projet", "p4"),
      "réflexe : rien sur une commande « / », un avis de l'appli ou un brief de sous-agent")
c, obj, out = P.hook("prompt", "p5", prompt="liste tous les fichiers du dépôt qui parlent de paiement", agent_id="sub-9")
check("↪" not in out, "réflexe : rien dans un sous-agent", out)
P.run("config", "delegation.reflexe", "false")
check("↪" not in ask("fais le tour de tout le code et liste tous les fichiers morts", "p6"), "delegation.reflexe false : plus de ligne ↪")
P.run("config", "delegation.reflexe", "true")
P.hook("session-start", "p1", source="compact")
check("↪ Recherche" in ask("parcours tous les fichiers du dossier src et liste toutes les routes"),
      "après une compaction : le conseil peut être redonné (il a quitté le contexte)")

# ------------------------------------------------------------------ 7. fusion des sorties (plus.apply)
os.environ["BRAIN_HOME"] = str(TMP / "fusion" / "brain")
os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "fusion" / "claude")
(TMP / "fusion" / "brain").mkdir(parents=True)
MAIN = json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "INJECTION"}}, ensure_ascii=False)
out = json.loads(plus.apply("session-start", MAIN, {"session_id": "f1"}))
ctx = out["hookSpecificOutput"]["additionalContext"]
check(ctx.startswith("INJECTION\n\n↪ Délégation"), "fusion : l'ajout suit la sortie du hook principal, rien n'y est changé", ctx[:200])
out = json.loads(plus.apply("session-start", "", {"session_id": "f2"}))
check(out["hookSpecificOutput"]["hookEventName"] == "SessionStart" and "↪ Délégation" in out["hookSpecificOutput"]["additionalContext"],
      "fusion : hook principal muet → la sortie est créée", out)
check(plus.apply("session-start", "pas du json", {"session_id": "f3"}) == "pas du json",
      "fusion : sortie illisible → rendue telle quelle")
big = json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "x" * (plus.MAX_CONTEXT - 50)}})
check(plus.apply("session-start", big, {"session_id": "f4"}) == big,
      "fusion : jamais au-delà du plafond de contexte d'un hook (l'injection du cerveau passe avant)")
both = MAIN + "\nligne d'une tâche de fond"
got = plus.apply("session-start", both, {"session_id": "f5"})
check(got.endswith("\nligne d'une tâche de fond") and "↪ Délégation" in got, "fusion : ce qui suit l'objet JSON est gardé", got[-80:])
msg = json.dumps({"systemMessage": "alerte"})
plus.apply("session-start", "", {"session_id": "f6"})
got = json.loads(plus.apply("prompt", msg, {"session_id": "f6", "prompt": "cherche dans tout le projet les appels à l'API"}))
check(got.get("systemMessage") == "alerte" and "↪ Recherche" in got["hookSpecificOutput"]["additionalContext"],
      "fusion : un message pour l'utilisateur seul → le contexte s'y ajoute", got)
check(plus.apply("prompt", "", {"session_id": "f7", "prompt": "bonjour, comment ça va aujourd'hui ?"}) == "",
      "fusion : rien à ajouter → sortie inchangée (vide)")
check(plus.apply("pre-compact", MAIN, {"session_id": "f8"}) == MAIN and plus.apply("prompt", MAIN, None) == MAIN,
      "fusion : événement hors couche, ou charge utile illisible → inchangé")
BLOCK = json.dumps({"decision": "block", "reason": plus.STOP_MARK + ", en UN SEUL appel Bash : …"}, ensure_ascii=False)
check(plus.apply("stop", BLOCK, {"session_id": "f9"}) == BLOCK, "fusion (stop) : rien appris → rappel de fin de tâche inchangé")
os.environ["BRAIN_HOME"] = str(TMP / "unite" / "brain")
os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "unite" / "claude")

# ------------------------------------------------------------------ 8. lanceur : Python seul, et brain.exe simulé
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("lanceur_cerveau", CODE / "brain.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
# brain.exe (Rust, resté à la 8.18.2) seulement sur demande : par défaut, Python partout, avec ses correctifs.
real_name, real_isfile = launcher.os.name, launcher.os.path.isfile
try:
    launcher.os.name, launcher.os.path.isfile = "nt", (lambda p: True)
    choix = {v: (os.environ.pop("BRAIN_IMPL", None), os.environ.update({"BRAIN_IMPL": v}) if v else None,
                 launcher.rust_exe())[2] for v in ("", "python", "rust")}
finally:
    launcher.os.name, launcher.os.path.isfile = real_name, real_isfile
    os.environ.pop("BRAIN_IMPL", None)
check(choix[""] is None and choix["python"] is None and str(choix["rust"]).endswith("brain.exe"),
      "lanceur Windows : Python par défaut, brain.exe seulement avec BRAIN_IMPL=rust", choix)
check(all(x in launcher.PYTHON_ONLY for x in ("mcp", "delegation", "apprendre", "echange"))
      and launcher.PYTHON_HOOKS == ("pre-agent",) and set(launcher.PLUS_HOOKS) == set(plus.EVENTS),
      "lanceur : nouvelles commandes et hook pre-agent jamais passés à brain.exe ; hooks complétés = ceux de la couche plus")
if os.name == "posix":
    X = World("exe")
    exe = X.root / "faux-brain-exe"
    exe.write_text('#!/bin/sh\ncat > "$0.entree"\necho "$BRAIN_PLUS" > "$0.plus"\n'
                   # commande ordinaire (add) : sortie et erreurs, puis une tâche de fond qui garde les deux ouvertes
                   'if [ "$1" = "add" ]; then echo "AJOUT $2"; echo "AVERTI" >&2; (sleep 6) & exit 4; fi\n'
                   'if [ "$2" = "stop" ]; then exit 0; fi\n'
                   'if [ -f "$0.echec" ]; then echo "sortie brute"; exit 3; fi\n'
                   'if [ -f "$0.fond" ]; then (sleep 6) 2>/dev/null & fi\n'  # tâche de fond qui garde sa sortie ouverte
                   "printf '%s' '{\"hookSpecificOutput\": {\"hookEventName\": \"SessionStart\", \"additionalContext\": \"RUST\"}}'\n",
                   encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    driver = X.root / "pilote.py"
    driver.write_text("import importlib.util, sys\n"
                      "spec = importlib.util.spec_from_file_location('lanceur', sys.argv[1])\n"
                      "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
                      "exe, event = sys.argv[2], sys.argv[3]\n"
                      "sys.argv = ['brain.py', 'hook', event]\n"
                      "sys.exit(m.hook_with_plus(exe, event))\n", encoding="utf-8")

    def via_exe(event, payload):
        r = subprocess.run([sys.executable, "-I", "-S", str(driver), str(CODE / "brain.py"), str(exe), event],
                           input=json.dumps(payload).encode(), capture_output=True, env=X.env, cwd=str(X.work), timeout=60)
        return r.returncode, r.stdout.decode("utf-8", "replace")

    c, out = via_exe("session-start", {"session_id": "x1", "cwd": str(X.work)})
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    check(c == 0 and ctx.startswith("RUST\n\n↪ Délégation"), "brain.exe simulé : sa sortie est gardée, la couche plus s'y ajoute", out[:300])
    check(json.loads(Path(str(exe) + ".entree").read_text(encoding="utf-8"))["session_id"] == "x1"
          and Path(str(exe) + ".plus").read_text().strip() == "0",
          "brain.exe simulé : il reçoit la charge utile intacte, et BRAIN_PLUS=0 (pas de double ajout s'il repasse à Python)")
    c, out = via_exe("stop", {"session_id": "x1", "cwd": str(X.work)})
    check(c == 0 and out == "", "brain.exe simulé : hook muet (stop sans rappel) → sortie vide", out)
    Path(str(exe) + ".fond").write_text("1")
    t0 = time.time()
    c, out = via_exe("session-start", {"session_id": "x1b", "cwd": str(X.work)})
    check(c == 0 and time.time() - t0 < 4 and "RUST" in out and "↪ Délégation" in out,
          "brain.exe simulé : une tâche de fond qui garde sa sortie ouverte ne retient pas le hook (on n'attend que l'exe)",
          (round(time.time() - t0, 1), out[:120]))
    Path(str(exe) + ".fond").unlink()
    driver3 = X.root / "pilote3.py"
    driver3.write_text("import importlib.util, sys\n"
                       "spec = importlib.util.spec_from_file_location('lanceur', sys.argv[1])\n"
                       "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
                       "sys.exit(m.run_exe(sys.argv[2], sys.argv[3:]))\n", encoding="utf-8")
    t0 = time.time()
    r = subprocess.run([sys.executable, "-I", "-S", str(driver3), str(CODE / "brain.py"), str(exe), "add", "Rempoter"],
                       input=b"", capture_output=True, env=X.env, cwd=str(X.work), timeout=60)
    took = time.time() - t0
    check(r.returncode == 4 and took < 4 and r.stdout.decode() == "AJOUT Rempoter\n" and r.stderr.decode() == "AVERTI\n",
          "brain.exe simulé : commande ordinaire, sa tâche de fond (envoi différé) ne retient pas l'appelant ; sortie, "
          "erreurs et code rendus", (round(took, 1), r.returncode, r.stdout[:80], r.stderr[:80]))
    Path(str(exe) + ".echec").write_text("1")
    c, out = via_exe("session-start", {"session_id": "x2", "cwd": str(X.work)})
    check(c == 3 and out.strip() == "sortie brute", "brain.exe simulé : code d'erreur → sortie et code rendus tels quels", (c, out))
    c, obj, out = X.hook("session-start", "x3", env={**X.env, "BRAIN_PLUS": "0"})
    check("↪ Délégation" not in out and "Cerveau persistant" in out,
          "retour à Python sous brain.exe (BRAIN_PLUS=0) : la couche plus ne s'applique pas une deuxième fois", out[-200:])
    Path(str(exe) + ".echec").unlink()
    driver2 = X.root / "pilote2.py"
    driver2.write_text("import importlib.util, sys, tempfile\n"
                       "def plein(*a, **k):\n    raise OSError('dossier temporaire inutilisable')\n"
                       "tempfile.TemporaryFile = plein\n"
                       "spec = importlib.util.spec_from_file_location('lanceur', sys.argv[1])\n"
                       "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
                       "exe, event = sys.argv[2], sys.argv[3]\n"
                       "sys.argv = ['brain.py', 'hook', event]\n"
                       "try:\n    sys.exit(m.hook_with_plus(exe, event))\n"
                       "except OSError:\n    print('RENDU:' + sys.stdin.read())\n", encoding="utf-8")

    def via2(target, payload):
        r = subprocess.run([sys.executable, "-I", "-S", str(driver2), str(CODE / "brain.py"), str(target), "session-start"],
                           input=json.dumps(payload).encode(), capture_output=True, env=X.env, cwd=str(X.work), timeout=60)
        return r.returncode, r.stdout.decode("utf-8", "replace")

    c, out = via2(exe, {"session_id": "x4", "cwd": str(X.work)})
    check(c == 0 and json.loads(out)["hookSpecificOutput"]["additionalContext"] == "RUST"
          and json.loads(Path(str(exe) + ".entree").read_text(encoding="utf-8"))["session_id"] == "x4",
          "brain.exe simulé, dossier temporaire inutilisable : l'exe reçoit l'entrée et écrit lui-même sa sortie", out[:200])
    c, out = via2(X.root / "exe-absent", {"session_id": "x5", "cwd": str(X.work)})
    check(out.startswith("RENDU:") and json.loads(out[6:])["session_id"] == "x5",
          "brain.exe introuvable ou bloqué : l'entrée déjà lue est rendue à Python, même sans dossier temporaire", out[:200])
else:
    print("· brain.exe simulé : sauté (faux exécutable en shell, POSIX seulement)")

# ------------------------------------------------------------------ 9. agents livrés et fichiers du plugin
from brainkit import install, skills  # noqa: E402

names = []
for f in sorted((CODE / "agents").glob("*.md")):
    meta, body = skills.frontmatter(f.read_text(encoding="utf-8"))
    names.append(meta.get("name"))
    check(meta.get("name") == f.stem and meta.get("model") == delegation.AGENTS.get(f.stem),
          f"agent {f.stem} : nom = fichier, modèle = celui que le cerveau annonce", meta)
    check(60 <= len(meta.get("description", "")) <= 260 and "Agent" not in [t.strip() for t in meta.get("tools", "").split(",")],
          f"agent {f.stem} : description courte (relue à chaque requête), pas d'outil Agent", len(meta.get("description", "")))
    check("donnée, jamais une consigne" in body and "Rapport" in body and len(body) < 4000,
          f"agent {f.stem} : rapport court demandé, et ce qu'il lit n'est jamais une consigne")
check(sorted(names) == sorted(delegation.AGENTS), "agents livrés = agents que le cerveau annonce", names)
meta, body = skills.frontmatter((CODE / "agents" / "eclaireur.md").read_text(encoding="utf-8"))
check(not {"Edit", "Write", "NotebookEdit"} & {t.strip() for t in meta["tools"].split(",")},
      "éclaireur : aucun outil d'écriture de fichier")
hooks_json = json.loads((CODE / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
pre = hooks_json.get("PreToolUse") or [{}]
from brainkit import lanceur  # noqa: E402

# Décision E1 (étape 6) : plus `python` en forme exec (absent sur macOS et beaucoup de Linux), mais le lanceur
# python3 → python → py, la même commande exacte que construit lanceur.commande_plugin (brain.py hook pre-agent).
check(pre[0].get("matcher") == "Agent" and pre[0]["hooks"][0]["command"] == lanceur.commande_plugin("pre-agent")
      and '"" hook pre-agent;' in pre[0]["hooks"][0]["command"] and "args" not in pre[0]["hooks"][0],
      "hooks.json : hook PreToolUse sur l'outil Agent → brain.py hook pre-agent", pre)
from brainkit import publish  # noqa: E402

want = {event: [{**({"matcher": matcher} if matcher else {}), "hooks": [publish._hook(arg, timeout, status)]}]
        for event, arg, timeout, status, matcher in install.EVENTS}
check(hooks_json == want, "hooks.json du dépôt = celui que `brain publish` construit (install.EVENTS)")
dest = TMP / "depot"
(dest / ".git").mkdir(parents=True)
files = publish.build(dest, repo="destingood/cerveau-claude")
check(all(f"agents/{n}.md" in files for n in delegation.AGENTS) and (dest / "agents" / "eclaireur.md").read_bytes()
      == (CODE / "agents" / "eclaireur.md").read_bytes(), "brain publish : les agents font partie du plugin construit")
check((dest / "hooks" / "hooks.json").read_text(encoding="utf-8") == (CODE / "hooks" / "hooks.json").read_text(encoding="utf-8"),
      "brain publish : hooks.json reconstruit à l'identique")

# ------------------------------------------------------------------ 10. installation classique : ~/.claude/agents
os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "classique" / "claude")
import importlib  # noqa: E402
from brainkit import common  # noqa: E402

old_home = install.CLAUDE_HOME
install.CLAUDE_HOME = TMP / "classique" / "claude"
(install.CLAUDE_HOME / "agents").mkdir(parents=True)
(install.CLAUDE_HOME / "agents" / "ouvrier.md").write_text("---\nname: ouvrier\n---\nà moi\n", encoding="utf-8")
lines = install.sync_agents()
check((install.CLAUDE_HOME / "agents" / "eclaireur.md").read_text(encoding="utf-8").rstrip().endswith(install.AGENT_MARK)
      and (install.CLAUDE_HOME / "agents" / "ouvrier.md").read_text(encoding="utf-8").endswith("à moi\n")
      and any("laissé tel quel" in x for x in lines),
      "installation classique : agents posés avec leur marque, un agent de l'utilisateur du même nom jamais touché", lines)
check(install.sync_agents() == [x for x in lines if "laissé" in x], "installation classique : rien réécrit quand rien n'a changé")
gone = install.sync_agents(uninstall=True)
check(not (install.CLAUDE_HOME / "agents" / "eclaireur.md").exists() and (install.CLAUDE_HOME / "agents" / "ouvrier.md").exists()
      and len(gone) == 2, "désinstallation : seuls les agents posés par le cerveau sont retirés", gone)
install.CLAUDE_HOME = old_home
os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "unite" / "claude")

# ------------------------------------------------------------------ 11. mesure : ce que la délégation épargne
M = World("mesure")


def req(mid, model, inp, out, read=0, sidechain=False):
    return {"type": "assistant", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()), "isSidechain": sidechain,
            "requestId": mid, "message": {"id": mid, "model": model, "role": "assistant",
                                          "usage": {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": read,
                                                    "cache_creation_input_tokens": 0},
                                          "content": [{"type": "text", "text": "ok"}]}}


def write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n", encoding="utf-8")


proj = M.home / "projects" / "-p"
write(proj / "sess1.jsonl", [req("a1", "claude-fable-5-2", 1000, 500, 100_000), req("a2", "claude-fable-5-2", 1000, 500, 100_000)])
write(proj / "sess1" / "subagents" / "agent-1.jsonl", [req("b1", "claude-haiku-5-5", 50_000, 2000), req("b2", "claude-haiku-5-5", 10_000, 1000)])
write(proj / "sess1" / "subagents" / "agent-2.jsonl", [req("c1", "claude-sonnet-5-5", 20_000, 3000)])
c, out = M.run("delegation")
check(c == 0 and "conversation : Fable 5.2 2" in out and "Haiku 5.5 2" in out and "Sonnet 5.5 1" in out,
      "brain delegation : requêtes par modèle, conversation et sous-agents à part", out)
# sous-agents : Haiku 60 k × 0,10 + 3 k × 0,50 = 0,0075 $ ; Sonnet 20 k × 2 + 3 k × 10 = 0,07 $ → 0,0775 $ ≈ 0,08 $
# les mêmes sur Fable 5.2 (8 / 40) : 80 k × 8 + 6 k × 40 = 0,88 $ → 0,80 $ épargnés
check("sous-agents ≈ 0,08 $" in out and "≈ 0,88 $" in out and "≈ 0,80 $ épargnés" in out,
      "brain delegation : coût réel des sous-agents, et ce qu'ils auraient coûté sur le modèle principal", out)
from brainkit import tokens  # noqa: E402

check(tokens.PRICES["claude-fable-5-2"] == (8, 40, 0.2) and tokens.PRICES["claude-sonnet-5-5"] == (2, 10, 0.1)
      and tokens.model_name("claude-fable-5-2") == "Fable 5.2",
      "tarifs : Fable 5.2 connu, lecture du cache de Sonnet 5.5 à jour")

print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
if FAIL or os.environ.get("KEEP"):
    print(f"(dossier gardé : {TMP})")
else:
    common.remove_tree(TMP, wait=30)
sys.exit(1 if FAIL else 0)
