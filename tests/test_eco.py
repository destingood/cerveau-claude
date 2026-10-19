"""Mode éco du cerveau (eco.py) sur de faux PC : réglages officiels de Claude Code posés avec copie de sécurité et retour
exact, application unique au démarrage, plugins jamais utilisés, coût fixe et relances dans `brain tokens`, alerte de
contexte à l'utilisateur, rappel de fin de tâche en un seul appel.

Lancement : python tests/test_eco.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-eco-test-"))
CODE = Path(__file__).resolve().parent.parent
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BASH_MAX_OUTPUT_LENGTH", "CLAUDE_CODE_AUTO_COMPACT_WINDOW"):
    os.environ.pop(k, None)
os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "unite" / "claude")  # import en direct de hooks.py : jamais le vrai PC
os.environ["BRAIN_HOME"] = str(TMP / "unite" / "brain")
sys.path.insert(0, str(CODE))


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


class World:
    """Un faux PC : ~/.claude (réglages, plugins, transcripts) et ~/.claude/brain (souvenirs, configuration)."""

    def __init__(self, name, code=CODE, **extra):
        self.root = TMP / name
        self.home, self.brain_dir, self.work = self.root / "claude", self.root / "brain", self.root / "work"
        for d in (self.home, self.brain_dir, self.work):
            d.mkdir(parents=True, exist_ok=True)
        self.code = Path(code)
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.home), "BRAIN_HOME": str(self.brain_dir), **extra}
        self.settings_file = self.home / "settings.json"

    def run(self, *args, inp=None):
        r = subprocess.run([sys.executable, "-I", "-S", str(self.code / "brain.py"), *map(str, args)], capture_output=True,
                           timeout=180, input=(inp or "").encode("utf-8"), cwd=str(self.root), env=self.env)
        return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")

    def hook(self, event, sid="s1", **payload):
        data = {"session_id": sid, "cwd": str(self.work), **payload}
        c, out = self.run("hook", event, inp=json.dumps(data))
        try:  # la sortie du hook est UN objet JSON (une tâche de fond peut écrire après)
            return c, json.JSONDecoder().raw_decode(out.lstrip())[0] if out.strip() else {}, out
        except ValueError:
            return c, None, out

    def settings(self):
        return json.loads(self.settings_file.read_text(encoding="utf-8"))

    def write_settings(self, data):
        self.settings_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def config(self, key=None):
        cfg = json.loads((self.brain_dir / "config.json").read_text(encoding="utf-8")) \
            if (self.brain_dir / "config.json").exists() else {}
        for part in (key or "").split("."):
            cfg = cfg.get(part) if part and isinstance(cfg, dict) else cfg
        return cfg


def context_of(msg):
    return ((msg or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")


# ------------------------------------------------------------------ 1. poser les réglages : le reste du fichier est gardé
W = World("pose")
original = {"theme": "dark", "permissions": {"allow": ["Bash(git status)"], "deny": []},
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mon-hook"}]}]}, "language": "français"}
W.write_settings(original)
c, out = W.run("eco")
check(c == 0 and "non réglé" in out and "pas encore appliqué" in out and "10 000" in out and "200 k" in out,
      "eco sans option : état actuel et valeurs du mode éco", out)
check(W.settings() == original, "eco sans option : rien n'est écrit")
c, out = W.run("eco", "--appliquer")
now = W.settings()
check(c == 0 and now.get("bashOutputMaxChars") == 10000 and now.get("autoCompactWindow") == 200000,
      "eco --appliquer : bashOutputMaxChars 10000 et autoCompactWindow 200000", out)
check(all(now.get(k) == v for k, v in original.items()), "toutes les autres clés de settings.json sont gardées", now)
backup = W.home / "settings.json.bak-cerveau-eco"
check(backup.exists() and json.loads(backup.read_text(encoding="utf-8")) == original,
      "copie de sécurité settings.json.bak-cerveau-eco = le fichier d'avant")
check(W.config("eco.applique_le") and W.config("eco.avant.cles.bashOutputMaxChars") == {"absent": True},
      "la configuration retient l'état d'avant (eco.avant) et la date (eco.applique_le)", W.config("eco"))
c, out = W.run("eco")
check("appliqué le" in out and "10 000 ✓" in out and "annuler" in out, "eco après application : état + retour possible", out)
stamp = backup.stat().st_mtime_ns
c, out = W.run("eco", "--appliquer")
check(c == 0 and "déjà" in out and backup.stat().st_mtime_ns == stamp and W.settings() == now,
      "eco --appliquer une 2e fois : rien ne bouge, copie d'origine intacte", out)
c, out = W.run("eco", "--sortie", "8000", "--fenetre", "150000")
check(c == 0 and W.settings().get("bashOutputMaxChars") == 8000 and W.settings().get("autoCompactWindow") == 150000,
      "--sortie/--fenetre : ses propres valeurs se changent sans --forcer", out)
check(W.config("eco.bash_output_max_chars") == 8000 and W.config("eco.auto_compact_window") == 150000,
      "--sortie/--fenetre : la valeur choisie devient la cible (configuration)", W.config("eco"))
c, out = W.run("optimize", "--apply")
check(W.settings().get("bashOutputMaxChars") == 8000 and W.settings().get("autoCompactWindow") == 150000,
      "optimize --apply garde la valeur choisie (8000 / 150 k) au lieu de revenir aux défauts", W.settings())
c, out = W.run("eco", "--annuler")
check(c == 0 and W.settings() == original, "eco --annuler : le fichier est exactement celui d'avant", W.settings())
check(W.config("eco.auto") is False and all(k not in W.config("eco") for k in ("applique_le", "avant", "pose")),
      "eco --annuler : application automatique coupée, enregistrement effacé", W.config("eco"))
c, out = W.run("eco", "--annuler")
check(c == 0 and W.settings() == original, "eco --annuler deux fois : sans effet", out)

# ------------------------------------------------------------------ 2. une valeur de l'utilisateur n'est jamais écrasée
W = World("respect")
W.write_settings({"bashOutputMaxChars": 50000, "model": "x"})
c, out = W.run("eco", "--appliquer")
check(c == 0 and W.settings()["bashOutputMaxChars"] == 50000 and W.settings()["autoCompactWindow"] == 200000
      and "gardé" in out and "50 000" in out and "--forcer" in out,
      "valeur déjà réglée par l'utilisateur : gardée et signalée, l'autre réglage posé", out)
c, out = W.run("eco", "--appliquer", "--forcer")
check(c == 0 and W.settings()["bashOutputMaxChars"] == 10000, "--forcer remplace la valeur de l'utilisateur", out)
c, out = W.run("eco", "--annuler")
check(W.settings() == {"bashOutputMaxChars": 50000, "model": "x"},
      "--annuler après --forcer : la valeur de l'utilisateur revient, l'autre clé est retirée", W.settings())
W = World("modifie")
W.run("eco", "--appliquer")
st = W.settings()
st["autoCompactWindow"] = 400000  # l'utilisateur change la valeur après coup (par exemple avec /autocompact)
W.write_settings(st)
c, out = W.run("eco", "--annuler")
check(W.settings().get("autoCompactWindow") == 400000 and "bashOutputMaxChars" not in W.settings() and "modifié depuis" in out,
      "--annuler ne touche pas une valeur que l'utilisateur a changée depuis", out)

# ------------------------------------------------------------------ 3. réglages illisibles : rien n'est touché
W = World("illisible")
broken = '{"theme": "dark",, ceci n\'est pas du JSON'
W.settings_file.write_text(broken, encoding="utf-8")
c, out = W.run("eco", "--appliquer")
check(c != 0 and "illisible" in out and W.settings_file.read_text(encoding="utf-8") == broken
      and not (W.home / "settings.json.bak-cerveau-eco").exists() and not W.config("eco.applique_le"),
      "réglages illisibles : rien n'est modifié ni sauvegardé, explication donnée", out)
c, out = W.run("eco", "--annuler")
check(c != 0 and W.settings_file.read_text(encoding="utf-8") == broken, "réglages illisibles : --annuler ne touche à rien", out)
c, msg, out = W.hook("session-start")
check(c == 0 and W.settings_file.read_text(encoding="utf-8") == broken and "Mode éco activé" not in context_of(msg),
      "réglages illisibles : le démarrage de session n'y touche pas non plus", out[-300:])
W.settings_file.write_text("[1, 2]", encoding="utf-8")
c, out = W.run("eco", "--appliquer")
check(c != 0 and W.settings_file.read_text(encoding="utf-8") == "[1, 2]", "réglages qui ne sont pas un objet JSON : refusés", out)

# ------------------------------------------------------------------ 4. limites des valeurs
W = World("limites")
W.write_settings(original)
for opts, label in ((("--sortie", "3999"), "--sortie 3999"), (("--sortie", "128001"), "--sortie 128001"),
                    (("--fenetre", "99999"), "--fenetre 99999"), (("--fenetre", "1000001"), "--fenetre 1000001"),
                    (("--appliquer", "--sortie", "0"), "--sortie 0")):
    c, out = W.run("eco", *opts)
    check(c != 0 and "hors limites" in out and W.settings() == original and not W.config("eco.applique_le"),
          f"{label} : refusé, rien n'est écrit", out)
c, out = W.run("eco", "--appliquer", "--sortie", "4000", "--fenetre", "1000000")
check(c == 0 and W.settings().get("bashOutputMaxChars") == 4000 and W.settings().get("autoCompactWindow") == 1000000,
      "bornes incluses (4000 et 1 000 000) acceptées", out)
c, out = W.run("eco", "--appliquer", "--annuler")
check(c != 0, "--appliquer et --annuler ensemble : refusé", out)

# ------------------------------------------------------------------ 5. au démarrage : posé une seule fois, annoncé une fois
W = World("demarrage")
W.write_settings({"theme": "dark"})
c, msg, out = W.hook("session-start", "d1")
ctx = context_of(msg)
check(c == 0 and "⚡ Mode éco activé" in ctx and "> 10 000 caractères mises en fichier" in ctx
      and "résumée vers 200 k tokens" in ctx and "eco --annuler" in ctx,
      "1er démarrage (plugin) : la ligne « Mode éco activé » avec les vraies valeurs", out[-400:])
check(W.settings().get("bashOutputMaxChars") == 10000 and W.settings().get("autoCompactWindow") == 200000
      and W.settings().get("theme") == "dark", "1er démarrage : réglages posés dans settings.json", W.settings())
check(W.config("eco.applique_le"), "1er démarrage : eco.applique_le enregistré")
c, msg, out = W.hook("session-start", "d2")
check(c == 0 and "Mode éco activé" not in context_of(msg) and "Cerveau" in context_of(msg),
      "2e démarrage : rien de plus à annoncer (appliqué une seule fois)", out[-300:])
W.run("eco", "--annuler")
c, msg, out = W.hook("session-start", "d3")
check(c == 0 and "Mode éco activé" not in context_of(msg) and "bashOutputMaxChars" not in W.settings()
      and "autoCompactWindow" not in W.settings(), "après --annuler : plus jamais reposé tout seul", W.settings())
W = World("sans-auto")
W.run("config", "eco.auto", "false")
c, msg, out = W.hook("session-start", "a1")
check(c == 0 and not W.settings_file.exists() and "Mode éco activé" not in context_of(msg),
      "eco.auto false : le démarrage ne pose rien", out[-300:])
W = World("existant")
W.write_settings({"bashOutputMaxChars": 20000, "autoCompactWindow": 300000})
c, msg, out = W.hook("session-start", "e1")
check(c == 0 and "Mode éco activé" not in context_of(msg) and W.settings() == {"bashOutputMaxChars": 20000, "autoCompactWindow": 300000}
      and W.config("eco.applique_le"), "valeurs de l'utilisateur déjà là : rien posé, rien annoncé, pas d'essai à chaque démarrage",
      W.settings())
# cerveau classique (code dans le dossier des souvenirs, pas de .claude-plugin) : même ligne, ajoutée à l'injection
classic = TMP / "classique-code"
classic.mkdir()
shutil.copy2(CODE / "brain.py", classic / "brain.py")
shutil.copytree(CODE / "brainkit", classic / "brainkit", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
W = World("classique", code=classic)
W.write_settings({"theme": "dark"})
c, msg, out = W.hook("session-start", "k1")
check(c == 0 and "⚡ Mode éco activé" in context_of(msg) and W.settings().get("autoCompactWindow") == 200000,
      "cerveau classique : ligne « Mode éco activé » et réglages posés", out[-400:])
c, msg, out = W.hook("session-start", "k2")
check(c == 0 and "Mode éco activé" not in context_of(msg), "cerveau classique : annoncé une seule fois", out[-300:])

# ------------------------------------------------------------------ 6. ce qui l'emporte sur les réglages
W = World("priorites")
W.write_settings({"modelSettings": {"claude-x": {"autoCompactWindow": 500000}}})
c, out = W.run("eco")
check("modelSettings.claude-x.autoCompactWindow" in out and "500 k" in out and "l'emporte" in out,
      "modelSettings.<modèle>.autoCompactWindow signalé (il l'emporte sur la clé générale)", out)
W.env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "300000"
W.env["BASH_MAX_OUTPUT_LENGTH"] = "50000"
c, out = W.run("eco")
check("CLAUDE_CODE_AUTO_COMPACT_WINDOW=300000" in out and "BASH_MAX_OUTPUT_LENGTH=50000" in out,
      "variables d'environnement qui l'emportent : signalées", out)
c, out = W.run("eco", "--appliquer")
check(c == 0 and "bashOutputMaxChars" not in W.settings() and "autoCompactWindow" not in W.settings()
      and "déjà réglé par toi" in out, "variables d'environnement de l'utilisateur : respectées sans --forcer", out)
c, out = W.run("eco", "--appliquer", "--forcer")
check(c == 0 and W.settings().get("bashOutputMaxChars") == 10000, "variables d'environnement : posé avec --forcer", out)

# ------------------------------------------------------------------ 7. plugins jamais utilisés
DAY = 86400
iso = lambda days: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - days * DAY))  # noqa: E731
entry = lambda name, days=100: [{"scope": "user", "installPath": f"/x/{name}", "version": "1.0.0",  # noqa: E731
                                 "installedAt": iso(days), "lastUpdated": iso(days)}]
SKILLS = "\n".join([f"- alpha:run: {'a' * 300}", f"- beta:go: {'b' * 300}", f"- gamma:one: {'g' * 1500}",
                    f"- gamma:two: {'h' * 1500}", f"- delta:x: {'d' * 300}", "- brain: ce plugin-ci"])
GAMMA_CHARS = len(f"- gamma:one: {'g' * 1500}") + len(f"- gamma:two: {'h' * 1500}") + 2
AI_SKILLS = "\n".join([f"- anthropic-skills:docx: {'x' * 400}", f"- anthropic-skills:pdf: {'y' * 400}"])  # skills de claude.ai
AI_CHARS = sum(len(x) + 1 for x in AI_SKILLS.split("\n"))


def usage(ctx):
    return {"input_tokens": 2, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": ctx - 1002, "output_tokens": 20}


def asst(mid, ctx, *tools, text="ok"):
    content = [{"type": "text", "text": text}] + [{"type": "tool_use", "id": f"t-{mid}-{i}", "name": n, "input": inp}
                                                   for i, (n, inp) in enumerate(tools)]
    return {"type": "assistant", "message": {"id": mid, "role": "assistant", "content": content, "usage": usage(ctx)}}


def prompt(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def result(mid, n, text="ok"):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": f"t-{mid}-{n}", "content": text}]}}


def att(kind, text, **extra):
    return {"type": "attachment", "attachment": {"type": kind, **extra}, "rendered": [{"content": text}]}


def write_transcript(path, lines, age_days=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n", encoding="utf-8")
    if age_days:
        t = time.time() - age_days * DAY
        os.utime(path, (t, t))


def plugin_world(name, ai=None, **settings):
    """Faux PC avec 8 plugins installés et une session. ai : None (pas de skills claude.ai listées), « inutilisees »
    (listées, aucune n'a servi) ou « utilisee » (listées, l'une a servi)."""
    W = World(name)
    (W.home / "plugins").mkdir()
    (W.home / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
        "alpha@marche": entry("alpha"), "beta@marche": entry("beta"), "gamma@marche": entry("gamma"),
        "delta@marche": entry("delta"), "epsilon@marche": entry("epsilon", 1), "zeta@marche": entry("zeta"),
        "omega@marche": entry("omega"), "cerveau@cerveau": entry("cerveau")}}), encoding="utf-8")
    listing = SKILLS + ("\n" + AI_SKILLS if ai else "")
    write_transcript(W.home / "projects" / "-work" / "ancienne.jsonl", [
        prompt("vieux"), asst("o1", 9000, ("Skill", {"skill": "gamma:one"}))], age_days=40)  # hors des 30 jours
    write_transcript(W.home / "projects" / "-work" / "session-a.jsonl", [
        att("skill_listing", "The following skills are available:\n\n" + listing, content=listing, skillCount=6, isInitial=True),
        prompt("bonjour"),
        asst("a1", 20000, ("Skill", {"skill": "alpha:run"})), result("a1", 0),
        asst("a2", 21000, ("mcp__plugin_beta_srv__do", {})), result("a2", 0),
        asst("a3", 22000, ("Bash", {"command": "ls"})), result("a3", 0, "x"),
        {"type": "user", "message": {"role": "user", "content": "<command-name>/zeta:go</command-name>"}},
        asst("a4", 23000)] + ([asst("a5", 24000, ("Skill", {"skill": "anthropic-skills:docx"}))] if ai == "utilisee" else []))
    W.write_settings({"theme": "dark", "enabledPlugins": {"delta@marche": False, "alpha@marche": True}, **settings})
    return W


W = plugin_world("plugins")
before_plugins = W.settings()
c, out = W.run("eco")
want = f"gamma@marche ≈ {GAMMA_CHARS / 2.2 / 1000:.1f} k tokens"  # 3,0 k car. ÷ 2,2 car./token
check(c == 0 and want in out, "plugin jamais utilisé repéré, avec son poids dans la liste de skills", out)
check(all(n not in out for n in ("alpha@", "beta@", "delta@", "epsilon@", "zeta@", "cerveau@")),
      "alpha (skill utilisée), beta (outil MCP), zeta (commande tapée), delta (désactivé), epsilon (récent) et le cerveau "
      "ne sont pas proposés", out)
check("eco --desactiver nom@marketplace" in out and "demande d'abord à l'utilisateur" in out,
      "la proposition renvoie à --desactiver en demandant d'abord à l'utilisateur", out)
check(W.settings() == before_plugins, "eco sans option ne désactive jamais rien", W.settings())
c, out = W.run("tokens")
check("plugin(s) actif(s) jamais utilisé(s) en 30 j" in out and "`brain eco`" in out,
      "brain tokens recommande brain eco pour les plugins inutilisés", out)
c, out = W.run("eco", "--desactiver", "cerveau@cerveau", "nope@marche")
check(c != 0 and "jamais" in out and "inconnu" in out and W.settings() == before_plugins,
      "--desactiver : le cerveau est protégé, un plugin inconnu refusé", out)
c, out = W.run("eco", "--desactiver", "gamma@marche")
now = W.settings()
check(c == 0 and now["enabledPlugins"] == {"delta@marche": False, "alpha@marche": True, "gamma@marche": False}
      and now["theme"] == "dark", "--desactiver nom@marketplace : enabledPlugins à false, le reste est gardé", now)
check((W.home / "settings.json.bak-cerveau-eco").exists(), "--desactiver : copie de sécurité faite")
c, out = W.run("eco")
check("gamma@" not in out, "un plugin désactivé n'est plus proposé", out)
c, out = W.run("eco", "--annuler")
check(c == 0 and W.settings() == before_plugins and "réactivé" in out, "--annuler réactive le plugin : réglages comme avant", W.settings())
W2 = World("plugins-nu")
shutil.copytree(W.home / "plugins", W2.home / "plugins", dirs_exist_ok=True)
shutil.copytree(W.home / "projects", W2.home / "projects", dirs_exist_ok=True)
W2.write_settings({"theme": "light"})
c, out = W2.run("eco", "--desactiver", "gamma")  # nom seul : accepté s'il n'y a qu'un marketplace
check(c == 0 and W2.settings().get("enabledPlugins") == {"gamma@marche": False}, "--desactiver nom (sans marketplace) accepté", out)
c, out = W2.run("eco", "--annuler")
check(W2.settings() == {"theme": "light"}, "--annuler retire enabledPlugins qu'il avait créé : fichier comme avant", W2.settings())

# ------------------------------------------------------------------ 8. brain tokens : coût fixe au démarrage et relances
W = World("tokens")
STOP = "🧠 Cerveau — avant de conclure, en UN SEUL appel Bash (commandes enchaînées avec &&) : 1) note 3 à 5 observations"
OBS = "🧠 Cerveau — le contexte vient d'être compacté : avant de conclure, note 3 à 5 observations datées"
pad = lambda n, head="": head + "a" * (n - len(head))  # noqa: E731


def session(path, skills, with_stop=True):
    lines = [att("skill_listing", pad(skills), content="- a: x\n- b: y\n- c: z", skillCount=3),
             att("mcp_instructions_delta", pad(1100), addedNames=["srv"]),
             att("deferred_tools_delta", pad(2200), addedNames=["T"]),
             att("hook_additional_context", pad(880, "🧠 Cerveau — mémoire "), content=["x"]),
             att("hook_additional_context", pad(220, "Autre hook : "), content=["y"]),
             att("date", pad(5000)),  # pas un poste du coût fixe
             prompt("bonjour"),
             asst("r1", 30000, ("Bash", {"command": "cat gros.log"})), result("r1", 0, "L" * 20000),
             asst("r2", 38000)]
    if with_stop:
        lines += [
            {"type": "user", "isMeta": True, "message": {"role": "user", "content": "Stop hook feedback:\n[python -I -S "
                                                          "/home/x/.claude/plugins/cache/cerveau/cerveau/8.5.0/brain.py hook stop]: " + STOP}},
            {"type": "user", "isMeta": True, "turnOrigin": "peer", "message": {"role": "user", "content": "Un message d'une autre session"}},
            {"type": "user", "turnOrigin": "task_notification", "message": {"role": "user", "content": "<task-notification>fini</task-notification>"}},
            asst("r3", 38500, ("Bash", {"command": "brain.py obs x && brain.py add y"})), result("r3", 0),
            asst("r4", 39000),
            att("hook_blocking_error", "Stop hook error: " + OBS),  # même rappel, autre forme de pièce jointe
            asst("r5", 39500),
            result("r5", 0, "extrait du code : " + STOP),  # un résultat d'outil qui cite le texte n'est pas un rappel
            {"type": "assistant", "message": {"id": "r6", "role": "assistant", "usage": usage(40000),
                                              "content": [{"type": "text", "text": "je cite : " + STOP}]}},
            prompt("merci, autre chose. " + "Pour info, " * 60 + "le texte du rappel commence par : " + STOP),
            asst("r7", 41000)]
    write_transcript(path, lines)


session(W.home / "projects" / "-p" / "s1.jsonl", 2200)
session(W.home / "projects" / "-p" / "s2.jsonl", 4400, with_stop=False)
session(W.home / "projects" / "-p" / "s3.jsonl", 8800, with_stop=False)
write_transcript(W.home / "projects" / "-p" / "s1" / "subagents" / "agent-1.jsonl", [  # un sous-agent : hors du coût fixe
    att("skill_listing", pad(90000), content="- z: z", skillCount=1), prompt("tâche"), asst("g1", 12000)])
c, out = W.run("tokens")
check(c == 0 and "Coût fixe au démarrage (médiane de 3 session(s)" in out, "tokens : section « Coût fixe au démarrage », 3 sessions", out)
check("3 listées ≈ 2.0 k tok" in out and "instructions MCP ≈ 500" in out and "noms d'outils différés ≈ 1.0 k" in out,
      "tokens : skills (médiane 4400 car. = 2.0 k), MCP et outils différés mesurés avec le calibrage du module", out)
check("cerveau (injection + 1er rappel) ≈ 400" in out and "autres hooks ≈ 100" in out,
      "tokens : injection du cerveau (🧠) séparée des autres hooks", out)
check("Relances du cerveau : 2 rappel(s) de fin de tâche → 4 requête(s) en plus (contexte relu 157 k)" in out,
      "tokens : 2 rappels du cerveau (message méta + pièce jointe), 4 requêtes jusqu'au vrai message suivant, citations "
      "ignorées", out)
check("3 sortie(s) Bash > 10 000 car." in out and "`brain eco --appliquer`" in out,
      "tokens : recommandation « sorties Bash longues » vers brain eco --appliquer", out)
check("brain eco" in out, "tokens : les recommandations renvoient à brain eco")
newlines = [ln for ln in out.splitlines() if ln.startswith(("Coût fixe", "  - skills", "  - cerveau", "Relances", "→"))]
check(len(newlines) <= 12, "tokens : au plus 12 lignes ajoutées", newlines)
W.write_settings({"bashOutputMaxChars": 10000, "autoCompactWindow": 200000})
c, out = W.run("tokens")
check("sortie(s) Bash >" not in out and "résume la conversation plus tôt" not in out,
      "tokens : plus de recommandation une fois le mode éco posé", out)

# ------------------------------------------------------------------ 9. alerte de contexte (UserPromptSubmit)
W = World("alerte")
TP = W.root / "transcript.jsonl"


def talk(ctx, extra=()):
    write_transcript(TP, [prompt("salut"), asst("m1", 5000), *extra, asst("m2", ctx)])


def ask(sid="p1", text="On continue avec la suite du travail", **kw):
    return W.hook("prompt", sid, prompt=text, transcript_path=str(TP), **kw)


talk(155010)
c, msg, out = ask()
check(c == 0 and msg and "systemMessage" in msg and "≈155 k tokens" in msg["systemMessage"]
      and "/clear" in msg["systemMessage"] and "/compact" in msg["systemMessage"] and "hookSpecificOutput" not in msg,
      "contexte > 150 k : message à l'utilisateur seulement (systemMessage), rien dans le contexte de Claude", out)
c, msg, out = ask()
check(c == 0 and not out.strip(), "même palier au message suivant : pas de 2e alerte", out)
talk(310000)
c, msg, out = ask()
check(msg and "≈310 k tokens" in msg.get("systemMessage", ""), "palier suivant (300 k) : nouvelle alerte avec le vrai chiffre", out)
c, msg, out = ask()
check(not out.strip(), "palier 300 k signalé une fois", out)
talk(20000)
c, msg, out = ask()
check(not out.strip(), "après compaction (contexte petit) : pas d'alerte", out)
talk(160000)
c, msg, out = ask()
check(msg and "≈160 k tokens" in msg.get("systemMessage", ""), "les paliers se réarment quand le contexte redescend", out)
talk(400000)
c, msg, out = ask("p2", "/clear")
check(not out.strip(), "message commençant par / (/clear, /compact) : pas d'alerte", out)
talk(100000)
c, msg, out = ask("p3")
check(not out.strip(), "sous le premier palier : rien", out)
for titre in ("Facturation mensuelle des abonnements", "Réglage du serveur de messagerie", "Couleurs de la charte graphique",
              "Tarifs de livraison en Europe", "Politique de retours clients", "Calendrier des soldes d'hiver",
              "Fournisseur de cartons recyclés", "Horaires de l'atelier"):  # un corpus assez grand pour que le rappel note
    W.run("add", "-t", "learning", "-T", titre, "-b", f"Note sur {titre}, avec quelques détails sans rapport.", "-p", "none")
c, out = W.run("add", "-t", "learning", "-T", "Épingles verticales Pinterest",
               "-b", "Les épingles verticales avec texte convertissent mieux que les photos produit seules.", "-p", "none")
talk(170000)
c, msg, out = ask("p4", "Comment améliorer les épingles verticales Pinterest avec texte ?")
check(msg and "systemMessage" in msg and "Épingles verticales" in context_of(msg),
      "rappel de souvenir + alerte : UN seul objet JSON avec additionalContext et systemMessage", out)
c, msg, out = W.hook("prompt", "p6", prompt="Un message sans fichier de transcript", transcript_path=str(W.root / "absent.jsonl"))
check(c == 0 and not out.strip(), "transcript introuvable : aucune erreur, aucune alerte", out)
W.run("config", "eco.alerte_contexte", "[]")
talk(500000)
c, msg, out = ask("p5")
check(not out.strip(), "eco.alerte_contexte [] : alerte coupée", out)

# lecture de la fin du transcript (en direct)
from brainkit import hooks  # noqa: E402

big = TMP / "gros.jsonl"
write_transcript(big, [asst("b1", 7000), {"type": "assistant", "message": {"id": "b2", "role": "assistant", "usage": usage(9000),
                                           "content": [{"type": "text", "text": "x" * 600_000}]}}])
check(hooks.last_context(big) == 9000, "last_context : dernière réponse plus grosse que la fin lue (fenêtre élargie)")
write_transcript(big, [asst("b1", 7000), asst("b1", 7000), {"type": "assistant", "message": {"id": "z", "usage": {
    "input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0}, "content": []}},
    {"type": "last-prompt"}])
big.write_text(big.read_text(encoding="utf-8") + "ligne cassée {\n", encoding="utf-8")
check(hooks.last_context(big) == 7000, "last_context : usage nul et lignes cassées ignorés, réponses d'un même id jamais additionnées")
check(hooks.last_context(TMP / "absent.jsonl") == 0 and hooks.last_context(None) == 0, "last_context : fichier absent → 0")

# ------------------------------------------------------------------ 10. rappel de fin de tâche, optimize, réglages par défaut
check("UN SEUL appel" in hooks.STOP_REASON and "&&" in hooks.STOP_REASON, "STOP_REASON : tout en UN SEUL appel Bash, chaîné avec &&")
check("UN SEUL appel" in hooks.OBS_REASON and "&&" in hooks.OBS_REASON, "OBS_REASON : tout en UN SEUL appel Bash")
check("doublons : `" not in hooks.STOP_REASON and "obs" in hooks.STOP_REASON and "add -t" in hooks.STOP_REASON,
      "STOP_REASON : plus d'étape « doublons » séparée, obs et add conservés")
from brainkit import journal  # noqa: E402

chain = TMP / "chaine.jsonl"
cmd = ('python "$HOME/.claude/brain/brain.py" obs "🔴 décision prise" "🟡 avancée" && '
       'python "$HOME/.claude/brain/brain.py" add -t learning -T "titre" -b "corps"')
write_transcript(chain, [prompt("fais le travail"), asst("c1", 9000, ("Read", {"file_path": "x"})),
                         asst("c2", 9500, ("Bash", {"command": cmd})), asst("c3", 9800)])
tx = journal.parse_transcript(str(chain))
check(tx["tools"] == 2 and tx["last_save_tools"] == 2 and tx["last_obs_tools"] == 2,
      "observations + souvenir chaînés en UN appel Bash : comptés comme faits (pas de nouveau rappel)", tx)
W = World("defauts")
c, out = W.run("config", "stop_reminder.repeat_after")
check(out.strip() == "150", "rappel de fin de tâche : repeat_after 150 par défaut", out)
c, out = W.run("config", "eco")
check('"auto": true' in out and "10000" in out and "200000" in out and "150000" in out and "300000" in out
      and '"plugins_auto": false' in out, "configuration eco par défaut (veille des plugins coupée)", out)
c, out = W.run("--version")
check("8.5.0" in out, "version 8.5.0", out)
W.write_settings({"theme": "dark"})
c, out = W.run("optimize")
check("Mode éco" in out and "optimize --apply" in out, "optimize (rapport) propose le mode éco", out)
c, out = W.run("optimize", "--apply")
check(c == 0 and "mode éco activé" in out and "brain eco --annuler" in out and W.settings().get("bashOutputMaxChars") == 10000,
      "optimize --apply applique le mode éco et le dit", out)
c, out = W.run("optimize", "--apply")
check(c == 0 and "mode éco : déjà actif" in out, "optimize --apply une 2e fois : mode éco déjà actif", out)
W = World("optimize-annule")
W.run("config", "eco.auto", "false")
c, out = W.run("optimize", "--apply")
check(c == 0 and not W.settings_file.exists() and "laissé de côté" in out, "optimize --apply respecte un mode éco annulé", out)

# ------------------------------------------------------------------ 11. référence et README
from brainkit import install, publish  # noqa: E402

check("`eco`" in install.SKILL and "eco --annuler" in install.SKILL and "eco --desactiver" in install.SKILL
      and "eco --plugins-auto" in install.SKILL, "SKILL : eco dans la référence des commandes")
check("mode éco" in publish.readme("Moi", "moi/depot"), "README : le mode éco est présenté")
c, out = World("aide").run("econome")
check(c == 0 and "Mode éco" in out, "alias « econome »", out)

# ------------------------------------------------------------------ 12. veille quotidienne des plugins inutilisés
def wait_for(fn, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.2)
    return False


W = plugin_world("veille", ai="inutilisees")
original = W.settings()
c, out = W.run("eco")
check("veille quotidienne des plugins inutilisés : non" in out and "--plugins-auto" in out and "omega@marche (aucune skill listée" in out,
      "eco : la veille est présentée (coupée par défaut), un plugin sans skill listée est signalé « à vérifier »", out)
c, out = W.run("eco", "--plugins-auto")
now = W.settings()
saved = (GAMMA_CHARS + AI_CHARS) / 2.2
check(c == 0 and "⚡ Mode éco : 1 plugin(s) inutilisé(s) depuis 30 jours désactivé(s) (gamma@marche)" in out
      and "skills claude.ai non chargées" in out and f"≈{saved / 1000:.1f} k tokens de moins par session" in out
      and "eco --annuler" in out, "--plugins-auto : annonce (plugin désactivé, skills claude.ai coupées, tokens gagnés)", out)
check(now["enabledPlugins"] == {"delta@marche": False, "alpha@marche": True, "gamma@marche": False}
      and now.get("syncClaudeAiSkills") is False and now["theme"] == "dark",
      "--plugins-auto : le plugin inutilisé désactivé, syncClaudeAiSkills false ; omega (sans skill listée), alpha, beta, zeta, "
      "epsilon et le cerveau intacts", now)
check(W.config("eco.plugins_auto") is True and W.config("eco.plugins_vus_le") and W.config("eco.annonce") == out.splitlines()[0]
      and (W.home / "settings.json.bak-cerveau-eco").exists(),
      "--plugins-auto : veille activée, jour noté, annonce gardée, copie de sécurité faite", W.config("eco"))
c, msg, out = W.hook("session-start", "v1")
ctx = context_of(msg)
check("⚡ Mode éco : 1 plugin(s) inutilisé(s)" in ctx and "skills claude.ai non chargées" in ctx and not W.config("eco.annonce"),
      "démarrage suivant : l'annonce est montrée (et effacée)", out[-500:])
c, msg, out = W.hook("session-start", "v2")
check(c == 0 and "skills claude.ai non chargées" not in context_of(msg), "l'annonce n'est montrée qu'une fois", out[-300:])
c, out = W.run("eco")
check("veille quotidienne des plugins inutilisés : oui" in out and "plugins-auto off" in out, "eco : la veille est dite active", out)
c, out = W.run("eco", "--annuler")
check(c == 0 and W.settings() == original and "réactivé" in out and "syncClaudeAiSkills retiré" in out,
      "--annuler remet tout : plugin réactivé, syncClaudeAiSkills retiré, réglages comme avant", W.settings())
check(W.config("eco.plugins_auto") is False and not W.config("eco.annonce"), "--annuler coupe aussi la veille", W.config("eco"))

# une skill de claude.ai a servi → on n'y touche pas ; une valeur de l'utilisateur est respectée
W = plugin_world("veille-usage", ai="utilisee")
c, out = W.run("eco", "--plugins-auto")
check(c == 0 and "syncClaudeAiSkills" not in W.settings() and "skills claude.ai" not in out and "gamma@marche" in out
      and W.settings()["enabledPlugins"].get("gamma@marche") is False,
      "skills claude.ai utilisée : syncClaudeAiSkills n'est pas touché, le plugin inutilisé est quand même désactivé", out)
W = plugin_world("veille-valeur", ai="inutilisees", syncClaudeAiSkills=True)
c, out = W.run("eco", "--plugins-auto", "on")
check(c == 0 and W.settings()["syncClaudeAiSkills"] is True and "skills claude.ai" not in out,
      "syncClaudeAiSkills réglé par l'utilisateur : respecté", W.settings())
W = World("veille-vide")
c, out = W.run("eco", "--plugins-auto")
check(c == 0 and "rien à retirer" in out and W.config("eco.plugins_auto") is True and not W.config("eco.annonce")
      and not W.settings_file.exists(), "rien à retirer : dit tel quel, aucun réglage écrit", out)
W.settings_file.write_text("{ cassé", encoding="utf-8")
c, out = W.run("eco", "--plugins-auto")
check(c != 0 and "illisible" in out and W.settings_file.read_text(encoding="utf-8") == "{ cassé",
      "--plugins-auto : réglages illisibles, rien n'est touché", out)

# lancée toute seule au démarrage, en arrière-plan, au plus une fois par jour ; coupée par « off »
W = plugin_world("veille-fond")
W.run("config", "eco.plugins_auto", "true")
W.run("config", "eco.plugins_vus_le", '"2000-01-01T00:00:00"')
before = W.settings()
c, msg, out = W.hook("session-start", "f1")
claimed = W.config("eco.plugins_vus_le")
check(c == 0 and claimed != "2000-01-01T00:00:00", "démarrage : veille due → jour réservé et tâche lancée en arrière-plan", out[-300:])
check(wait_for(lambda: W.config("eco.annonce")) and W.settings()["enabledPlugins"].get("gamma@marche") is False
      and "syncClaudeAiSkills" not in W.settings(), "la tâche de fond désactive le plugin inutilisé (pas de skills claude.ai listées)",
      W.settings())
time.sleep(1)
c, msg, out = W.hook("session-start", "f2")
check("⚡ Mode éco : 1 plugin(s) inutilisé(s)" in context_of(msg), "démarrage suivant : l'annonce de la tâche de fond", out[-400:])
half_day = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 12 * 3600))
W.run("config", "eco.plugins_vus_le", json.dumps(half_day))
c, msg, out = W.hook("session-start", "f3")
time.sleep(1.5)
check(W.config("eco.plugins_vus_le") == half_day, "veille faite il y a moins d'un jour : pas relancée", W.config("eco"))
W.run("config", "eco.plugins_vus_le", '"2000-01-01T00:00:00"')
c, out = W.run("eco", "--plugins-auto", "off")
check(c == 0 and W.config("eco.plugins_auto") is False and "coupée" in out, "--plugins-auto off : veille coupée", out)
c, msg, out = W.hook("session-start", "f4")
time.sleep(1.5)
check(W.config("eco.plugins_vus_le") == "2000-01-01T00:00:00", "veille coupée : rien n'est lancé au démarrage", W.config("eco"))
time.sleep(0.5)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
