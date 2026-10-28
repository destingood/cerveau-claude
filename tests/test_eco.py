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
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BASH_MAX_OUTPUT_LENGTH", "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
          "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS", "CLAUDE_CODE_DISABLE_AUTO_MEMORY",
          "FORCE_PROMPT_CACHING_5M", "CLAUDE_CODE_PROMPT_CACHE_TTL", "ENABLE_PROMPT_CACHING_1H"):
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
        cfg = self.brain_dir / "config.json"  # veille PC coupée : la RAM du vrai PC ne doit pas changer les messages
        cfg.exists() or cfg.write_text(json.dumps({"pc": {"enabled": False}}), encoding="utf-8")
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
        from brainkit.common import read_json  # réessaie si une tâche de fond (garde) réécrit le fichier
        cfg = read_json(self.brain_dir / "config.json", {}) or {}
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
ctx = context_of(msg)
eco_line = next((ln for ln in ctx.splitlines() if "⚡ Mode éco" in ln), "")
check(c == 0 and "⚡ Mode éco activé" in eco_line and "liste des skills plafonnée à 0,5 %" in eco_line
      and "mises en fichier" not in eco_line and "résumée vers" not in eco_line,
      "valeurs de l'utilisateur déjà là : gardées, seuls les autres leviers sont posés et annoncés", out[-400:])
check(W.settings() == {"bashOutputMaxChars": 20000, "autoCompactWindow": 300000, "skillListingBudgetFraction": 0.005,
                       "autoMemoryEnabled": False} and W.config("eco.applique_le"),
      "valeurs de l'utilisateur gardées ; liste des skills et mémoire auto posées (rien à importer)", W.settings())
c, msg, out = W.hook("session-start", "e2")
check(c == 0 and "⚡ Mode éco" not in context_of(msg) and W.settings()["bashOutputMaxChars"] == 20000,
      "démarrage suivant : rien de plus (pas d'essai à chaque démarrage)", out[-300:])
W = World("tout-regle")
mine = {"bashOutputMaxChars": 20000, "autoCompactWindow": 300000, "skillListingBudgetFraction": 0.02, "autoMemoryEnabled": True}
W.write_settings(mine)
c, msg, out = W.hook("session-start", "t1")
check(c == 0 and "⚡ Mode éco" not in context_of(msg) and W.settings() == mine and W.config("eco.applique_le"),
      "tout déjà réglé par l'utilisateur : rien posé, rien annoncé, application notée", W.settings())
# installation qui avait déjà le mode éco (1re version des leviers) : les nouveaux leviers posés une fois, annoncés à part
W = World("leviers-v2")
W.write_settings({"bashOutputMaxChars": 10000, "autoCompactWindow": 200000})
W.run("config", "eco.applique_le", '"2026-10-01T00:00:00"')
c, msg, out = W.hook("session-start", "l1")
eco_line = next((ln for ln in context_of(msg).splitlines() if "⚡ Mode éco" in ln), "")
check(c == 0 and "⚡ Mode éco — nouveaux réglages" in eco_line and "liste des skills plafonnée à 0,5 %" in eco_line
      and "mémoire auto de Claude Code coupée" in eco_line and "mises en fichier" not in eco_line,
      "nouveaux leviers d'une version plus récente : posés une fois, annonce « nouveaux réglages »", out[-400:])
check(W.settings() == {"bashOutputMaxChars": 10000, "autoCompactWindow": 200000, "skillListingBudgetFraction": 0.005,
                       "autoMemoryEnabled": False} and W.config("eco.leviers") == 2
      and W.config("eco.applique_le") == "2026-10-01T00:00:00",
      "nouveaux leviers : posés, eco.leviers à 2, date d'application d'origine gardée", (W.settings(), W.config("eco")))
c, msg, out = W.hook("session-start", "l2")
check(c == 0 and "⚡ Mode éco" not in context_of(msg), "nouveaux leviers annoncés une seule fois", out[-300:])
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
      and '"plugins_auto": false' in out and '"cache": "auto"' in out and '"alerte_pause": true' in out,
      "configuration eco par défaut (veille des plugins coupée, cache adaptatif, alerte de pause)", out)
c, out = W.run("--version")
from brainkit import __version__  # noqa: E402
check(__version__ in out, f"version {__version__}", out)
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
      and "eco --plugins-auto" in install.SKILL and "eco --poser" in install.SKILL and "eco --cache" in install.SKILL,
      "SKILL : eco dans la référence des commandes")
check("mode éco" in publish.readme("Moi", "moi/depot"), "README : le mode éco est présenté")
dest = Path(tempfile.mkdtemp(prefix="cerveau-publish-"))
(dest / "CONTRIBUTORS.md").write_text("# Contributeurs", encoding="utf-8")
(dest / "ancien.txt").write_text("x", encoding="utf-8")
(dest / "plateforme").mkdir()
(dest / "plateforme" / "README.md").write_text("# Plateforme\ncontact : equipe" + "@" + "plateforme.fr", encoding="utf-8")  # adresse en morceaux : pas d'e-mail dans le dépôt public
files = publish.build(dest, "Moi", "moi/depot")
check((dest / "CONTRIBUTORS.md").is_file() and not (dest / "ancien.txt").exists() and (dest / "brainkit").is_dir(),
      "publish : CONTRIBUTORS.md du dépôt gardé, le reste reconstruit")
check((dest / "plateforme" / "README.md").is_file() and not any(f.startswith("plateforme/") for f in files)
      and not publish.secrets_in(dest), "publish : plateforme/ (autre projet du dépôt) gardé, hors liste et hors contrôle")
shutil.rmtree(dest, ignore_errors=True)
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

# ------------------------------------------------------------------ 13. réglages sur accord : proposés, posés, retirés
from brainkit import eco  # noqa: E402

W = World("propositions")
write_transcript(W.home / "projects" / "-x" / "s.jsonl", [
    att("deferred_tools_delta", "outils différés", addedNames=["mcp__monserveur__outil1", "mcp__monserveur__outil2",
                                                                "mcp__ccd_session__x", "mcp__autre__y"]),
    prompt("bonjour"), asst("m1", 5000, ("mcp__autre__y", {}))])
orig = {"permissions": {"allow": ["Bash(ls)"]}}
W.write_settings(orig)
c, out = W.run("eco")
check(c == 0 and "Sur accord de l'utilisateur seulement" in out and "monserveur (2 outils)" in out
      and "autre (" not in out and "ccd_session" not in out,
      "eco : connecteur jamais utilisé proposé ; celui qui a servi et ceux de l'app, jamais", out)
check(W.settings() == orig, "eco sans option : aucune proposition n'est posée", W.settings())
c, out = W.run("eco", "--poser", "outils", "connecteurs", "git", "lecture")
now = W.settings()
check(c == 0 and now["permissions"]["deny"] == list(eco.TOOL_WEIGHTS) + ["mcp__monserveur"]
      and now["permissions"]["allow"] == ["Bash(ls)"] and now.get("includeGitInstructions") is False
      and now.get("env") == {"CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS": "12000"},
      "--poser : règles de refus (outils, connecteur), consignes git retirées, lecture plafonnée ; le reste gardé", now)
check(set(W.config("eco.propositions") or {}) == {"outils", "connecteurs", "git", "lecture"}
      and "eco --retirer outils connecteurs git lecture" in out, "--poser : retenu dans la configuration, retour indiqué", out)
c, out = W.run("eco")
check("✓ git posé" in out and "--poser effort sous-agents" in out, "eco : les posés marqués ✓, restent effort et sous-agents", out)
c, out = W.run("eco", "--retirer", "outils", "connecteurs", "git", "lecture")
check(c == 0 and W.settings() == orig and not W.config("eco.propositions"),
      "--retirer : réglages exactement comme avant", (W.settings(), out))
c, out = W.run("eco", "--poser", "bidon")
check(c != 0 and "proposition inconnue" in out and W.settings() == orig, "--poser inconnu : refusé, rien n'est écrit", out)
c, out = W.run("eco", "--retirer", "git")
check(c == 0 and "rien à retirer" in out, "--retirer ce qui n'est pas posé : dit tel quel", out)
W.run("eco", "--poser", "outils", "git")
c, out = W.run("eco", "--annuler")
check(c == 0 and W.settings() == orig, "--annuler retire aussi les réglages posés sur accord", W.settings())

# outils choisis par l'utilisateur (--refuser / --rendre) ; connecteurs claude.ai : jamais de règle de refus (mesuré le
# 21/10/2026 : elle bloque leurs appels sans les sortir du contexte)
APP = "mcp__0cf6aea5-9f89-4b04-93c1-92b003711eba"
W = World("refuser")
write_transcript(W.home / "projects" / "-x" / "s.jsonl", [
    att("deferred_tools_delta", "outils différés", addedNames=[f"{APP}__get_x", "mcp__monserveur__outil1"]),
    prompt("bonjour"), asst("m1", 5000, ("PowerShell", {}))])
W.write_settings(orig)
c, out = W.run("eco")
check(c == 0 and "Connecteurs claude.ai jamais utilisés depuis 30 j" in out and "0cf6aea5 (1 outils) — une règle" in out
      and "connecteurs — ≈" in out and "monserveur (1 outils)" in out and "eco --refuser NOM" in out,
      "eco : connecteur claude.ai à couper dans l'app, pas en règle de refus ; serveur MCP proposé", out)
c, out = W.run("eco", "--poser", "connecteurs")
check(c == 0 and W.settings()["permissions"]["deny"] == ["mcp__monserveur"],
      "--poser connecteurs : jamais de règle sur un connecteur claude.ai", W.settings())
c, out = W.run("eco", "--refuser", "Artifact", "PowerShell")
check(c == 0 and W.settings()["permissions"]["deny"] == ["mcp__monserveur", "Artifact", "PowerShell"]
      and W.config("eco.propositions.outils") == ["Artifact", "PowerShell"] and "eco --rendre Artifact PowerShell" in out,
      "--refuser : outils choisis retirés (même un outil déjà utilisé), retour indiqué", out)
for bad, why in (("Bash", "indispensable"), ("mcp__plugin_cerveau_cerveau", "indispensable"), (APP, "connecteur claude.ai"),
                 ("Bash(rm:*)", "nom d'outil invalide")):
    c, out = W.run("eco", "--refuser", bad)
    check(c != 0 and why in out and bad not in W.settings()["permissions"]["deny"], f"--refuser {bad} : refusé ({why})", out)
c, out = W.run("eco", "--rendre", "PowerShell", "Inconnu")
check(c == 0 and W.settings()["permissions"]["deny"] == ["mcp__monserveur", "Artifact"]
      and W.config("eco.propositions.outils") == ["Artifact"] and "Inconnu : pas refusé par le cerveau" in out,
      "--rendre : outil rendu ; un nom que le cerveau n'a pas refusé, dit tel quel", out)
W.run("eco", "--rendre", "Artifact")
W.run("eco", "--retirer", "connecteurs")
check(W.settings() == orig and not W.config("eco.propositions"), "--rendre et --retirer : réglages exactement comme avant",
      (W.settings(), W.config("eco")))
# correctif : les règles qu'une version d'avant avait posées sur des connecteurs claude.ai sont retirées une fois
W.run("eco", "--poser", "connecteurs")
W.run("eco", "--refuser", "mcp__autre")
for f in (W.settings_file, W.brain_dir / "config.json"):
    f.write_text(f.read_text(encoding="utf-8").replace("mcp__autre", APP), encoding="utf-8")
W.run("config", "eco.propositions", json.dumps({"connecteurs": ["mcp__monserveur", APP]}))
c, msg, out = W.hook("session-start", "r1")
check(c == 0 and "1 règle(s) de refus sur des connecteurs claude.ai retirée(s)" in context_of(msg)
      and W.settings()["permissions"]["deny"] == ["mcp__monserveur"]
      and W.config("eco.propositions") == {"connecteurs": ["mcp__monserveur"]} and APP not in json.dumps(W.config("eco")),
      "démarrage : règle sur un connecteur claude.ai retirée (état d'avant), le reste gardé, annoncé", out[-600:])
c, msg, out = W.hook("session-start", "r2")
check("connecteurs claude.ai retirée" not in context_of(msg), "correctif fait une seule fois", out[-300:])


# ------------------------------------------------------------------ 14. cache adaptatif (promptCacheTtl)
def ts_ago(sec):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - sec))


def req(mid, t, inp, w, read, out, w1h=None, **extra):
    """Une requête comme dans un vrai transcript : heure, entrée, cache écrit (dont w1h pour 1 h), cache lu, sortie."""
    w1h = w if w1h is None else w1h
    return {"type": "assistant", "timestamp": t, "requestId": f"req-{mid}", **extra,
            "message": {"id": mid, "role": "assistant", "content": [], "usage": {
                "input_tokens": inp, "cache_creation_input_tokens": w, "cache_read_input_tokens": read, "output_tokens": out,
                "cache_creation": {"ephemeral_5m_input_tokens": w - w1h, "ephemeral_1h_input_tokens": w1h}}}}


def quiet(fn):
    try:
        return fn()
    except (ValueError, OSError):
        return None


W = World("cache")
c, out = W.run("eco", "--cache", "5m")
check(c == 0 and W.settings() == {"promptCacheTtl": "5m"} and "cache fixé à 5 min" in out and W.config("eco.cache") == "5m",
      "--cache 5m : valeur fixée, plus de choix automatique", out)
c, out = W.run("eco", "--cache", "off")
check(c == 0 and "promptCacheTtl" not in W.settings() and "cache adaptatif coupé" in out and W.config("eco.cache") == "off",
      "--cache off : réglage retiré (état d'avant), cache adaptatif coupé", out)
W.run("eco", "--cache", "1h")
c, out = W.run("eco", "--cache", "auto")
check(c == 0 and "cache adaptatif actif" in out and "pas encore assez de requêtes" in out
      and W.settings() == {"promptCacheTtl": "1h"}, "--cache auto sans assez de requêtes : rien ne change, c'est dit", out)
W = World("cache-env", CLAUDE_CODE_PROMPT_CACHE_TTL="1h")
c, out = W.run("eco", "--cache", "auto")
check(c == 0 and "⚠ CLAUDE_CODE_PROMPT_CACHE_TTL=1h (variable d'environnement)" in out and "pas encore assez" not in out
      and not W.settings_file.exists(), "variable d'environnement du cache : signalée, rien n'est posé", out)
c, out = W.run("eco")
check("réglé par variable d'environnement" in out, "eco : cache réglé par variable d'environnement, dit tel quel", out)
W = World("cache-perso")
W.write_settings({"promptCacheTtl": "1h"})
c, out = W.run("eco", "--cache", "auto")
check(c == 0 and "réglé par toi, gardé" in out and "pas encore assez" not in out and W.settings() == {"promptCacheTtl": "1h"},
      "valeur du cache réglée par l'utilisateur : gardée", out)
W.run("eco", "--cache", "5m")
c, out = W.run("eco", "--cache", "off")
check(W.settings() == {"promptCacheTtl": "1h"}, "--cache 5m puis off : la valeur de l'utilisateur revient", (W.settings(), out))

PAUSES_COURTES = [req("k0", ts_ago(20000), 0, 55000, 0, 100)] + [  # 520 requêtes à 30 s d'écart, cache écrit pour 1 h
    req(f"k{i}", ts_ago(20000 - 30 * i), 0, 5000, 50000, 100) for i in range(1, 520)]
W = World("cache-simule")
write_transcript(W.home / "projects" / "-c" / "s.jsonl", PAUSES_COURTES)
c, out = W.run("eco", "--cache", "auto")
check(c == 0 and W.settings() == {"promptCacheTtl": "5m"} and "cache gardé 5 min" in out and "−24,4 %" in out
      and W.config("eco.bilan.meilleur") == "5m" and W.config("eco.annonce"),
      "cache adaptatif : pauses toujours courtes → 5 min posé (−24,4 % du poids des tokens), annonce gardée", out)
c, out = W.run("eco")
check("5 min posé, −24,4 %" in out, "eco : le cache adaptatif dit ce qu'il a posé et le gain simulé", out)
c, out = W.run("eco", "--cache", "auto")
check(c == 0 and "5 min est le meilleur" in out and W.settings() == {"promptCacheTtl": "5m"},
      "cache adaptatif relancé : 5 min reste le meilleur, rien ne bouge", out)
c, out = W.run("eco", "--cache", "off")
check(c == 0 and "promptCacheTtl" not in W.settings(), "--cache off : le 5 min posé par le cerveau est retiré", out)
W = World("cache-fond")
write_transcript(W.home / "projects" / "-c" / "s.jsonl", PAUSES_COURTES)
W.run("config", "eco.cache_vu_le", '"2000-01-01T00:00:00"')
c, msg, out = W.hook("session-start", "c1")
check(c == 0 and W.config("eco.cache_vu_le") != "2000-01-01T00:00:00",
      "démarrage : cache adaptatif dû → jour noté, lancé en arrière-plan", out[-300:])
check(wait_for(lambda: quiet(lambda: W.settings().get("promptCacheTtl") == "5m" and W.config("eco.annonce"))),
      "la tâche de fond pose le cache de 5 min et garde l'annonce", quiet(W.settings))
time.sleep(1)
c, msg, out = W.hook("session-start", "c2")
check("cache gardé 5 min" in context_of(msg), "démarrage suivant : l'annonce du cache adaptatif", out[-400:])

# ------------------------------------------------------------------ 15. brain tokens : le poids réel des tokens (en direct)
from brainkit import tokens  # noqa: E402

eco._SCANS.clear()
P = TMP / "unite" / "claude" / "projects" / "-w"
T0 = time.time() - 26 * 3600
ts = lambda s: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(T0 + s))  # noqa: E731
write_transcript(P / "sa.jsonl", [
    {"type": "custom-title", "customTitle": "Refonte du site"},
    req("a1", ts(0), 100, 30000, 0, 1000),
    req("a2", ts(30), 100, 2000, 30000, 50), req("a2", ts(30), 100, 2000, 30000, 500),  # une réponse sur 2 lignes
    req("a3", ts(630), 100, 32000, 0, 500),  # après 10 min : cache de 5 min perdu, 1 h gardé
    req("a4", ts(7830), 100, 33000, 0, 500),  # après 2 h : tout est réécrit
    req("a5", ts(7850), 100, 25000, 10000, 500)])  # 20 s plus tard, gros cache réécrit : invalidation
write_transcript(P / "sa" / "subagents" / "agent-1.jsonl", [
    req("s1", ts(100), 0, 10000, 0, 200, w1h=0, isSidechain=True),
    req("s2", ts(130), 0, 1000, 10000, 200, w1h=0, isSidechain=True)])
sb = [{"type": "ai-title", "aiTitle": "Compactions en série"}]
for k in range(6):
    sb += [req(f"b{k}1", ts(90 * k), 0, 20000, 0, 100), req(f"b{k}2", ts(90 * k + 30), 0, 10000, 20000, 100),
           req(f"b{k}3", ts(90 * k + 60), 0, 10000, 30000, 100)]
    if k < 5:
        sb.append({"type": "system", "subtype": "compact_boundary", "timestamp": ts(90 * k + 75),
                   "compactMetadata": {"preTokens": 40000, "postTokens": 5000}})
write_transcript(P / "sb.jsonl", sb)
write_transcript(P / "sc.jsonl", [req("a1", ts(0), 100, 30000, 0, 1000),  # requête déjà comptée (session reprise)
                                  req("c1", ts(20000), 50, 1000, 30000, 100, w1h=0)])
write_transcript(P / "old.jsonl", [req("o1", ts(0), 0, 90000, 0, 100)], age_days=10)  # hors des 7 jours
b = tokens.weigh(168)
near = lambda x, y: abs(x - y) < 0.01  # noqa: E731
check(b["files"] == 4 and b["reqs"] == 26 and b["compactions"] == 5 and near(b["hidden"], 145000),
      "weigh : 4 fichiers récents, 26 requêtes (doublons écartés), 5 compactions et leurs résumés cachés", b)
check(all(near(b["parts"].get(k, -1), v) for k, v in {"in": 550, "w5": 15000, "w1h": 724000, "read": 38000, "out": 26500}.items())
      and near(b["total"], 949050) and near(b["main"], 787300) and near(b["sub"], 16750),
      "weigh : poids par poste (entrée 1, cache écrit 1,25 / 2, lu 0,1, sortie 5), conversation / sous-agents", b)
check({k: (n, round(w)) for k, (n, w) in b["causes"].items()} == {
    "début": (2, 100000), "compaction": (5, 200000), "pause > 1 h": (1, 66000), "pause > 5 min": (1, 64000),
    "invalidation": (1, 50000)}, "weigh : causes des écritures de cache (début, compaction, pauses, invalidation)", b["causes"])
check(b["gaps"] == {"< 1 min": 19, "1-5 min": 0, "5-60 min": 1, "> 1 h": 1}, "weigh : pauses entre requêtes", b["gaps"])
check(near(b["ttl"]["5m"], 491300) and near(b["ttl"]["1h"], 702750) and b["ttl"]["reqs"] == 24 and b["ttl"]["regime"] == "1h",
      "weigh : cache de 5 min et de 1 h simulés sur les vraies pauses", b["ttl"])
check(b["fenetre"] == 140000 and b["fenetre_calc"] == {"base": 20000, "croissance": 10000, "cout": 69000, "segments": 5},
      "weigh : fenêtre de résumé la moins chère d'après les compactions", (b["fenetre"], b["fenetre_calc"]))
check([(round(w), n) for w, n in b["sessions"]] == [(664000, "Compactions en série"), (280250, "Refonte du site"), (4800, "sc")],
      "weigh : sessions les plus lourdes, avec leur titre (sous-agents comptés avec leur session)", b["sessions"])
lines = "\n".join(tokens._weigh_lines(b))
for want in ("949 k sur 26 requête(s)",
             "lecture du cache 4,0 % · écriture 1 h 76,3 % · écriture 5 min 1,6 % · sortie 2,8 % · entrée 0,1 % · "
             "résumés de compaction (cachés) 15,3 % (5) · sous-agents 1,8 %",
             "début 2 (10,5 %) · compaction 5 (21,1 %) · pause > 1 h 1 (7,0 %) · pause > 5 min 1 (6,7 %) · invalidation 1 (5,3 %)",
             "< 1 min 19 · 1-5 min 0 · 5-60 min 1 · > 1 h 1",
             "5 min ferait gagner 22,3 % (en service : 1 h)",
             "« Compactions en série » 70,0 % · « Refonte du site » 29,5 % · « sc » 0,5 %",
             "≈ 140 k (en service 200 k) : `brain eco --fenetre 140000`",
             "5 réglage(s) sur accord (outils, git, effort, lecture, sous-agents, ≈ 12.7 k tok de moins par requête)"):
    check(want in lines, f"brain tokens : « {want[:50]}… »", lines)

# garde de consommation : seuil abaissé pour ces petits transcripts (en vrai : 20 M et 40 % des 24 h)
GMIN, tokens.GUARD_MIN = tokens.GUARD_MIN, 0
g = tokens.guard(168, now=T0 + 600)  # 90 s après la dernière requête de « Compactions en série »
check(g["alertes"] == ["sb"] and [r["id"] for r in g["sessions"]] == ["sb", "sa", "sc"]
      and [(r["requetes"], r["compactions"]) for r in g["sessions"]] == [(18, 5), (7, 0), (1, 0)]
      and near(g["sessions"][0]["part"], 664000 / 949050) and eco.load_config()["garde"]["alertes"] == ["sb"],
      "garde : la session lourde et encore active est en alerte, la Refonte (30 %) non ; calcul gardé", g)
note = tokens.guard_notice()
check(note.startswith("🔥 Consommation : « Compactions en série » 70 % des tokens (≈ ") and "18 requêtes, 5 résumés" in note
      and "168 dernières heures" in note and "stop_session" in note and "Refonte" not in note,
      "garde : alerte au démarrage (titre, part, requêtes, résumés, que faire)", note)
check(tokens.guard_notice(session_id="sb") == "", "garde : la session en alerte n'est pas alertée sur elle-même")
gl = "\n".join(tokens.guard_lines())
check("- 🔥 « Compactions en série » 70 %" in gl and "- « Refonte du site » 30 %" in gl and "_🔥 = session" in gl,
      "garde : section Consommation de la page Cerveau, 🔥 devant l'alerte", gl)
g = tokens.guard(168)  # 26 h plus tard : plus active
check(g["alertes"] == [] and tokens.guard_notice() == "" and "🔥" not in "\n".join(tokens.guard_lines()),
      "garde : session arrêtée depuis plus de 2 h → plus d'alerte", g)
tokens.GUARD_MIN = GMIN
check(tokens.guard(168, now=T0 + 600)["alertes"] == [], "garde : sous 20 M, jamais d'alerte (bruit écarté)")
eco.set_config("garde", None)
W = World("garde")
c, msg, out = W.hook("session-start", "g1")
check(c == 0 and W.config("garde.lance_le"), "démarrage : garde lancée en arrière-plan, heure notée", out[-300:])
check(wait_for(lambda: quiet(lambda: W.config("garde.le"))), "la tâche de fond (tokens --garde) garde son calcul",
      quiet(lambda: W.config("garde")))
lance = W.config("garde.le")
W.hook("session-start", "g2")
check(W.config("garde.le") == lance and not W.config("garde.lance_le"), "garde : pas relancée avant 2 h", W.config("garde"))
c, out = W.run("tokens", "--garde")
check(c == 0 and "✓ aucune session ne mange la journée" in out, "brain tokens --garde : à la main, résultat dit", out)

# ------------------------------------------------------------------ 16. reprise après une pause qui a vidé le cache
PT = TMP / "pause.jsonl"


def paused(ago, kind):
    write_transcript(PT, [prompt("salut"), {"type": "assistant", "timestamp": ts_ago(ago), "message": {
        "id": "p1", "role": "assistant", "content": [], "usage": {
            "input_tokens": 2, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 148998, "output_tokens": 20,
            "cache_creation": {kind: 1000}}}}])


paused(7200, "ephemeral_5m_input_tokens")
size, when, ttl = hooks.last_request(PT)
check(size == 150000 and abs(when - (time.time() - 7200)) < 5 and ttl == 300,
      "last_request : taille du contexte, heure et cache de 5 min lus dans le transcript", (size, when, ttl))
paused(7200, "ephemeral_1h_input_tokens")
check(hooks.last_request(PT)[2] == 3600, "last_request : cache de 1 h vu dans les écritures", hooks.last_request(PT))
t_now = time.time()
note = hooks.pause_alert(150000, t_now - 600, 300, t_now)
check(note.startswith("⏸ Reprise après 10 min") and "≈150 k tokens" in note and "/clear" in note,
      "pause plus longue que le cache, grosse conversation : alerte avec la durée et la taille", note)
check(hooks.pause_alert(150000, t_now - 600, 3600, t_now) == "", "pause plus courte que le cache de 1 h : rien")
check(hooks.pause_alert(50000, t_now - 7200, 300, t_now) == "", "petite conversation : rien")
check(hooks.pause_alert(150000, t_now - 200, 0, t_now) == "", "pause de moins de 5 min : rien")
check(hooks.pause_alert(150000, t_now - 7200, 0, t_now).startswith("⏸ Reprise après 2 h"),
      "durée du cache inconnue : 1 h par défaut, pause de 2 h signalée")
W = World("pause")
paused(7200, "ephemeral_1h_input_tokens")
c, msg, out = W.hook("prompt", "z1", prompt="On reprend le travail d'hier", transcript_path=str(PT))
check(c == 0 and msg and "⏸ Reprise après 2 h" in msg.get("systemMessage", "") and "Reprise" not in context_of(msg),
      "message après 2 h de pause : signalé à l'utilisateur seulement (systemMessage)", out[-400:])
time.sleep(0.5)

# ------------------------------------------------------------------ 20. lectures une par une, plugins du compte claude.ai
SP = TMP / "solo" / "s.jsonl"
rd = lambda i, ctx=150000: asst(f"r{i}", ctx, ("Bash", {"command": f"cd /x && sed -n {i},+40p a.py"}))  # noqa: E731
split = [{"type": "assistant", "message": {"id": "r9", "content": [{"type": "text", "text": "je lis"}], "usage": usage(150000)}},
         {"type": "assistant", "message": {"id": "r9", "content": [{"type": "tool_use", "id": "t-r9", "name": "Read",
                                                                    "input": {"file_path": "a.py"}}], "usage": usage(150000)}}]
before = [prompt("go")] + [rd(i) for i in range(5)] + [{"type": "system", "subtype": "compact_boundary"}]
cycle = split + [rd(i) for i in range(10, 29)] + [asst("w1", 150000, ("Edit", {}), ("Read", {"file_path": "x"}))]
write_transcript(SP, before + cycle)
s = tokens.solo(SP)
check(s == {"reqs": 21, "single": 20, "chained": 19, "ctx": 150000},
      "lectures une par une : comptées depuis la dernière compaction, réponse sur 2 lignes comptée une fois", s)
note = tokens.solo_notice(SP)
check("21 requêtes, 95 % à un seul appel, dont 19 lectures enchaînées" in note and "≈ 150 k" in note and "&&" in note,
      "lectures une par une : la ligne dit combien et comment grouper", note)
write_transcript(SP, before + cycle + [{"type": "system", "subtype": "compact_boundary"}])
check(tokens.solo(SP)["chained"] == 19, "juste après la compaction : c'est le cycle qui vient de finir qui compte")
mixed = [prompt("go")] + [x for i in range(15) for x in (rd(i), asst(f"e{i}", 150000, ("Edit", {})))]
write_transcript(SP, mixed)
check(tokens.solo(SP)["chained"] == 0 and tokens.solo_notice(SP) == "", "lecture puis modification : rien à signaler")
check(tokens.solo(TMP / "absent.jsonl")["reqs"] == 0 and tokens.solo_notice(TMP / "absent.jsonl") == "",
      "transcript absent : rien, sans erreur")
write_transcript(SP, before + cycle + [{"type": "system", "subtype": "compact_boundary"}])
W = World("solo")
c, msg, out = W.hook("session-start", "c1", source="compact", transcript_path=str(SP))
check(c == 0 and "19 lectures enchaînées" in context_of(msg), "après une compaction : l'alerte part dans le contexte",
      out[-400:])
c, msg, out = W.hook("session-start", "c2", source="startup", transcript_path=str(SP))
check(c == 0 and "lectures enchaînées" not in context_of(msg), "démarrage normal : pas d'alerte de lectures")
write_transcript(TMP / "unite" / "claude" / "projects" / "-solo" / "s.jsonl", before + cycle)
d = tokens.measure(1000)
check(d["solo"][0] >= 23 and d["solo"][2] >= 26, "brain tokens : lectures enchaînées mesurées", d["solo"])

eco._SCANS.clear()
SY = TMP / "unite" / "claude" / "plugins" / "synced" / "compte"
for name, mcp in (("kindle", {"mcpServers": {"a": {}, "b": {}}}), ("sert", None), (eco.OWN_PLUGIN, None)):
    (SY / name).mkdir(parents=True, exist_ok=True)
    (SY / f"{name}.meta.json").write_text(json.dumps({"marketplace_name": "m"}), encoding="utf-8")
    if mcp:
        (SY / name / ".mcp.json").write_text(json.dumps(mcp), encoding="utf-8")
(SY / "orphelin.meta.json").write_text("{}", encoding="utf-8")  # métadonnées sans dossier : ignorées
write_transcript(TMP / "unite" / "claude" / "projects" / "-s" / "s.jsonl", [
    att("skill_listing", "skills", content=f"- kindle:notes: {'k' * 400}\n- sert:go: {'s' * 400}"),
    prompt("go"), asst("s1", 5000, ("Skill", {"skill": "sert:go"}))])
check(sorted(eco.synced_plugins()) == ["kindle", "sert"], "plugins du compte claude.ai trouvés (jamais le cerveau)",
      eco.synced_plugins())
rows = eco.unused_synced()
check(len(rows) == 1 and rows[0][0] == "kindle" and rows[0][1] > 90 and rows[0][2] == 2,
      "plugin du compte jamais utilisé : listé avec ses tokens de skills et ses serveurs MCP", rows)
st = eco.status()
check("Plugins du compte claude.ai jamais utilisés" in st and "- kindle ≈" in st and "2 serveur(s) MCP" in st
      and "- sert" not in st, "brain eco : plugins du compte inutilisés, à retirer dans l'app", st[-600:])

from brainkit.common import remove_tree  # noqa: E402

if not remove_tree(TMP, wait=60):  # tâches de fond du cerveau testé : on attend qu'elles aient fini d'y écrire
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
