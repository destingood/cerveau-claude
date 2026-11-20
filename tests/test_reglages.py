"""settings.json de Claude Code (eco.py, install.py) : relu juste avant d'écrire (un changement fait entre-temps n'est
jamais perdu), écrit atomiquement, lu en utf-8-sig (BOM d'un éditeur Windows). Tout en direct (import des modules), dans
des dossiers temporaires.

Lancement : python tests/test_reglages.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-reglages-test-"))
CODE = Path(__file__).resolve().parent.parent
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BASH_MAX_OUTPUT_LENGTH", "CLAUDE_CODE_AUTO_COMPACT_WINDOW"):
    os.environ.pop(k, None)
HOME = TMP / "claude"
HOME.mkdir(parents=True)
os.environ.update({"CLAUDE_CONFIG_DIR": str(HOME), "BRAIN_HOME": str(TMP / "brain"), "HOME": str(TMP / "home"),
                   "USERPROFILE": str(TMP / "home")})
sys.path.insert(0, str(CODE))
OK, FAIL = [], []


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


from brainkit import common, eco, install  # noqa: E402

SETTINGS = HOME / "settings.json"


def put(data, bom=False):
    SETTINGS.write_text(("﻿" if bom else "") + json.dumps(data, indent=2), encoding="utf-8")


def get():
    return json.loads(SETTINGS.read_text(encoding="utf-8-sig"))


def between_reads(change):
    """Fait `change()` (un autre programme écrit settings.json) juste après la PREMIÈRE lecture de eco.read_settings."""
    real, state = eco.read_settings, {"n": 0}

    def wrapped():
        res = real()
        state["n"] += 1
        if state["n"] == 1:
            change()
        return res

    eco.read_settings = wrapped
    return lambda: setattr(eco, "read_settings", real)


# --- eco : un changement entre la lecture et l'écriture n'est pas perdu
put({"theme": "dark", "enabledPlugins": {"a@m": True}})
restore = between_reads(lambda: put({"theme": "dark", "enabledPlugins": {"a@m": True}, "editorMode": "vim",
                                     "permissions": {"allow": ["Bash(ls)"]}}))
ok, posees, lignes = eco.commit([("cle", eco.OUT_KEY, 12345)])
restore()
now = get()
check(ok and eco.OUT_KEY in posees and now.get(eco.OUT_KEY) == 12345, "eco : la clé du cerveau est posée", (ok, lignes, now))
check(now.get("editorMode") == "vim" and now.get("permissions") == {"allow": ["Bash(ls)"]},
      "eco : le changement fait entre la lecture et l'écriture est gardé (contenu frais)", now)
check(now["theme"] == "dark" and now["enabledPlugins"] == {"a@m": True}, "eco : le reste du fichier est intact", now)
check(not list(HOME.glob("*.tmp")), "eco : écriture atomique, pas de fichier temporaire laissé", list(HOME.iterdir()))

# idem pour le retour (--annuler) : une clé ajoutée par un autre pendant le retour reste
restore = between_reads(lambda: put({**get(), "language": "français"}))
code, lignes = eco.undo()
restore()
now = get()
check(code == 0 and eco.OUT_KEY not in now and now.get("language") == "français" and now.get("editorMode") == "vim",
      "eco --annuler : le changement concurrent est gardé, la clé du cerveau retirée", (lignes, now))

# --- BOM (éditeur Windows) : lisible par eco, conservé le reste
put({"theme": "light"}, bom=True)
check(eco.read_settings() == ({"theme": "light"}, None), "eco : settings.json avec BOM lisible", eco.read_settings())
ok, posees, lignes = eco.commit([("cle", eco.OUT_KEY, 20000)])
check(ok and get() == {"theme": "light", eco.OUT_KEY: 20000}, "eco : écrit à partir d'un fichier avec BOM", (lignes, get()))
check(not SETTINGS.read_bytes().startswith(b"\xef\xbb\xbf"), "eco : réécrit sans BOM")

# --- install : même chose
common.PLUGIN = False  # dépôt de développement : `run` ne s'arrête pas au mode plugin
put({"theme": "dark", "permissions": {"deny": ["Bash(rm:*)"]}}, bom=True)
check(install.read_settings_file(SETTINGS) == {"theme": "dark", "permissions": {"deny": ["Bash(rm:*)"]}},
      "install : settings.json avec BOM lisible (finding B-10)")
install.run()
now = get()
check(now.get("hooks") and now["theme"] == "dark" and now["permissions"] == {"deny": ["Bash(rm:*)"]},
      "install : hooks posés, BOM sans conséquence, réglages gardés", now)
install.run(uninstall=True)
put({"theme": "dark"})
real, state = install.read_settings_file, {"n": 0}


def wrapped(path):
    res = real(path)
    state["n"] += 1
    if state["n"] == 1:
        put({"theme": "dark", "model": "opus"})  # Claude Code écrit pendant que le cerveau prépare
    return res


install.read_settings_file = wrapped
install.run()
install.read_settings_file = real
now = get()
check(now.get("model") == "opus" and now["theme"] == "dark" and "SessionStart" in (now.get("hooks") or {}),
      "install : le changement fait entre la lecture et l'écriture est gardé, les hooks posés", now)
check(not list(HOME.glob("settings.json.*.tmp")), "install : pas de fichier temporaire laissé", list(HOME.iterdir()))

from brainkit.common import remove_tree  # noqa: E402

remove_tree(TMP, wait=30)
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
