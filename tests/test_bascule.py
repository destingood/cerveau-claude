"""Passage d'un cerveau classique au plugin (mises à jour automatiques, comme chez les amis), sur un faux PC : un
cerveau classique 8.0.0 installé avec ses souvenirs, puis le plugin construit par `brain publish` placé dans le cache
des plugins de Claude Code. Le premier démarrage du plugin doit prendre le relais sans rien perdre.

Lancement : python tests/test_bascule.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-bascule-test-"))
CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_HOME", "CLAUDE_CONFIG_DIR"):
    os.environ.pop(k, None)


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def env(home):
    e = {k: v for k, v in os.environ.items() if k not in ("BRAIN_HOME",)}
    e["CLAUDE_CONFIG_DIR"] = str(home)
    e.pop("BRAIN_COMMUN_FG", None)
    return e


def py(script, *args, home, inp=None):
    r = subprocess.run([sys.executable, "-I", "-S", str(script), *map(str, args)], capture_output=True, timeout=180,
                       input=(inp or "").encode("utf-8"), cwd=str(TMP), env=env(home))
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def classic_brain(home):
    """Cerveau classique 8.0.0 (le code publié sur main avant le cerveau commun) installé dans home/brain."""
    brain = home / "brain"
    brain.mkdir(parents=True)
    tar = subprocess.run(["git", "-C", str(CODE), "archive", "53ba68c", "brain.py", "brainkit", "tests", "skills"],
                         capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(brain)], input=tar, check=True)
    c, out = py(brain / "brain.py", "install", home=home)
    assert c == 0, out
    c, out = py(brain / "brain.py", "add", "-t", "learning", "-T", "Épingles verticales sur Pinterest",
                "-b", "Les épingles verticales avec texte convertissent mieux que les photos produit seules.",
                "-p", "none", home=home)
    assert c == 0, out
    return brain


def plugin_in_cache(home, version_dir="8.4.0"):
    """Le plugin tel que Claude Code l'installe : cache/<marketplace>/<plugin>/<version>/ + registre des marketplaces."""
    from brainkit import publish
    dest = home / "plugins" / "cache" / "cerveau" / "cerveau" / version_dir
    publish.build(dest, "Lucas", "destingood/cerveau-claude")
    (dest / ".git").exists() and shutil.rmtree(dest / ".git")
    write = {"cerveau": {"source": {"source": "git", "url": "https://github.com/destingood/cerveau-claude.git"},
                         "installLocation": str(home / "plugins" / "marketplaces" / "cerveau")}}
    (home / "plugins" / "known_marketplaces.json").write_text(json.dumps(write), encoding="utf-8")
    return dest


def hook(code_dir, event, home, sid="s1"):
    payload = json.dumps({"session_id": sid, "cwd": str(TMP), "source": "startup"})
    return py(code_dir / "brain.py", "hook", event, home=home, inp=payload)


def settings(home):
    return json.loads((home / "settings.json").read_text(encoding="utf-8"))


def graph_titles(brain):
    data = json.loads((brain / "graph.json").read_text(encoding="utf-8"))
    return {n.get("title") for n in data["nodes"].values()}


# ------------------------------------------------------------------ 1. le PC avant : cerveau classique en place
HOME = TMP / "lucas" / ".claude"
BRAIN = classic_brain(HOME)
before = settings(HOME)
user_hook = {"hooks": [{"type": "command", "command": "echo hook-a-moi"}]}
before.setdefault("hooks", {}).setdefault("Stop", []).append(user_hook)  # un hook de l'utilisateur, à garder
before["permissions"] = {"allow": ["Bash(git status)"]}
(HOME / "settings.json").write_text(json.dumps(before, indent=2), encoding="utf-8")
check(any("brain.py" in json.dumps(v) for v in before["hooks"].values()), "classique : hooks du cerveau dans settings.json")
check("BRAIN:START" in (HOME / "CLAUDE.md").read_text(encoding="utf-8"), "classique : bloc CLAUDE.md")
check((HOME / "skills" / "brain" / "SKILL.md").exists(), "classique : skill /brain")
titles_before = graph_titles(BRAIN)

# ------------------------------------------------------------------ 2. le plugin arrive : il prend le relais
PLUGIN = plugin_in_cache(HOME)
c, out = hook(PLUGIN, "session-start", HOME)
ctx = ""
try:  # la sortie du hook commence par le JSON pour Claude Code (une tâche de fond peut écrire après)
    ctx = json.JSONDecoder().raw_decode(out.lstrip())[0]["hookSpecificOutput"]["additionalContext"]
except (ValueError, KeyError, TypeError):
    pass
check(c == 0 and "🔄 Cerveau passé en mode plugin" in ctx, "premier démarrage du plugin : bascule annoncée", out[-600:])
check("Épingles verticales" in ctx or "épingles" in ctx.lower() or "Cerveau persistant" in ctx,
      "le même démarrage injecte déjà le cerveau (consignes et mémoire)", ctx[:400])
after = settings(HOME)
check(not any("brain.py" in json.dumps(e) and " hook " in json.dumps(e) for ev in after.get("hooks", {}).values()
              for e in ev), "hooks classiques retirés de settings.json", after.get("hooks"))
check(user_hook in (after.get("hooks") or {}).get("Stop", []) and after.get("permissions") == before["permissions"],
      "réglages de l'utilisateur intacts (son hook, ses permissions)", after)
check(((after.get("extraKnownMarketplaces") or {}).get("cerveau") or {}).get("autoUpdate") is True
      and after["extraKnownMarketplaces"]["cerveau"]["source"]["url"].endswith("cerveau-claude.git"),
      "mises à jour automatiques activées pour le marketplace « cerveau »", after.get("extraKnownMarketplaces"))
check((HOME / "settings.json.bak-cerveau-classique").exists(), "copie de settings.json gardée avant modification")
check("BRAIN:START" not in ((HOME / "CLAUDE.md").read_text(encoding="utf-8") if (HOME / "CLAUDE.md").exists() else ""),
      "bloc CLAUDE.md classique retiré (le plugin injecte ses consignes)")
check(not (HOME / "skills" / "brain").exists(), "skill /brain classique retirée (le plugin fournit /cerveau:brain)")
check(not (BRAIN / "brainkit").exists() and not (BRAIN / "tests").exists(), "code classique retiré de ~/.claude/brain")
cfg = json.loads((BRAIN / "config.json").read_text(encoding="utf-8"))
archive = Path(((cfg.get("plugin") or {}).get("archive")) or "/absent")
check(archive.is_dir() and '"8.0.0"' in (archive / "brainkit" / "__init__.py").read_text(encoding="utf-8")
      and (archive / "brain.py").exists(), "code classique archivé (8.0.0) avant d'être retiré", archive)
check(graph_titles(BRAIN) == titles_before and "Épingles verticales sur Pinterest" in titles_before,
      "souvenirs intacts", len(titles_before))
check("runpy" in (BRAIN / "brain.py").read_text(encoding="utf-8") and str(PLUGIN) in (BRAIN / "brain.py").read_text(
    encoding="utf-8"), "lanceur stable ~/.claude/brain/brain.py vers le code du plugin")

# ------------------------------------------------------------------ 3. ensuite : tout passe par le plugin
c, out = py(BRAIN / "brain.py", "--version", home=HOME)
from brainkit import __version__  # noqa: E402
check(c == 0 and __version__ in out, f"commande du cerveau → version du plugin ({__version__})", out)
c, out = py(BRAIN / "brain.py", "q", "épingles pinterest", home=HOME)
check(c == 0 and "Épingles verticales" in out, "les souvenirs se retrouvent par le plugin", out[-400:])
c, out = hook(PLUGIN, "session-start", HOME, sid="s2")
check(c == 0 and "🔄" not in out and "Cerveau persistant" in out, "démarrage suivant : plus d'annonce, cerveau actif",
      out[-300:])
c, out = py(BRAIN / "brain.py", "doctor", home=HOME)
check("passé du cerveau classique 8.0.0 au plugin" in out and "mises à jour automatiques du marketplace" in out,
      "doctor : bascule et mises à jour automatiques contrôlées", out[-900:])
# une nouvelle version du plugin (nouveau dossier dans le cache) : le lanceur suit
PLUGIN2 = plugin_in_cache(HOME, "8.4.1")
c, out = hook(PLUGIN2, "session-start", HOME, sid="s3")
check(c == 0 and str(PLUGIN2) in (BRAIN / "brain.py").read_text(encoding="utf-8"),
      "mise à jour du plugin : le lanceur vise la nouvelle version au démarrage suivant")

# ------------------------------------------------------------------ 4. garder le cerveau classique exprès
HOME2 = TMP / "garde" / ".claude"
BRAIN2 = classic_brain(HOME2)
c, out = py(BRAIN2 / "brain.py", "config", "plugin.garder_classique", "true", home=HOME2)
PLUGIN3 = plugin_in_cache(HOME2)
hooks_before = settings(HOME2).get("hooks")
c, out = hook(PLUGIN3, "session-start", HOME2)
check(c == 0 and out.strip() == "" and (BRAIN2 / "brainkit").is_dir() and settings(HOME2).get("hooks") == hooks_before,
      "config plugin.garder_classique : le plugin s'efface, rien n'est touché", out[-300:])

# ------------------------------------------------------------------ 4 bis. settings.json illisible : rien n'est touché
HOME4 = TMP / "casse" / ".claude"
BRAIN4 = classic_brain(HOME4)
(HOME4 / "settings.json").write_text("{ pas du json", encoding="utf-8")
PLUGIN5 = plugin_in_cache(HOME4)
c, out = hook(PLUGIN5, "session-start", HOME4)
check(c == 0 and (BRAIN4 / "brainkit").is_dir() and not (BRAIN4 / "archives").exists()
      and (HOME4 / "settings.json").read_text(encoding="utf-8") == "{ pas du json",
      "réglages illisibles : bascule reportée, cerveau classique intact, aucune archive en trop", out[-300:])

# ------------------------------------------------------------------ 5. un ami (pas de cerveau classique) : rien à basculer
HOME3 = TMP / "ami" / ".claude"
PLUGIN4 = plugin_in_cache(HOME3)
c, out = hook(PLUGIN4, "session-start", HOME3)
check(c == 0 and "🔄" not in out and (HOME3 / "brain" / "brain.py").exists() and not (HOME3 / "brain" / "archives").exists(),
      "chez un ami : démarrage normal, aucune archive", out[-300:])

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
