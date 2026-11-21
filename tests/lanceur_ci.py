"""Le lanceur des hooks sur de vrais interpréteurs (CI : job « launcher » de .github/workflows/plugin.yml). En plus de
tests/test_lanceur.py (faux interpréteurs, sur tout PC) : un vrai Python 3.9 (`uv python install 3.9`) que brain.py
doit refuser, le python3 d'Apple sur macOS, et sous Windows PowerShell 5.1 et 7 sans Git Bash dans le PATH, avec le
vrai python.exe. Chaque hook est lancé comme Claude Code le lance (https://code.claude.com/docs/en/hooks) : `sh -c`,
Git Bash, ou PowerShell -Command après réécriture de ${CLAUDE_PLUGIN_ROOT}.

Lancement (CI) : uv python install 3.9 puis python tests/lanceur_ci.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="cerveau-lanceur-ci-"))
WIN = os.name == "nt"
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS", "CERVEAU_PYTHON",
          "CERVEAU_LANCEUR"):
    os.environ.pop(k, None)
BASE = dict(os.environ, CLAUDE_CONFIG_DIR=str(TMP / "claude"), BRAIN_HOME=str(TMP / "brain"), HOME=str(TMP / "home"),
            USERPROFILE=str(TMP / "home"), BRAIN_OFFLINE="1", CLAUDE_PLUGIN_ROOT=str(CODE))
for d in ("claude", "brain", "home", "work"):
    (TMP / d).mkdir()
SPEC = json.loads((CODE / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
HOOK = {ev: SPEC[name][0]["hooks"][0]["command"] for ev, name in (("session-start", "SessionStart"),
                                                                   ("prompt", "UserPromptSubmit"),
                                                                   ("pre-agent", "PreToolUse"))}
SYS32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    print(("✓ " if cond else "✗ ") + label + ("" if cond else f" — {str(detail)[-900:]}"))


def run(argv, path, event, **kw):
    env = dict(BASE, PATH=path)
    data = {"session_id": f"ci-{len(OK) + len(FAIL)}", "cwd": str(TMP / "work"), "source": "startup",
            "prompt": "on continue"}
    r = subprocess.run(argv, input=json.dumps(data).encode("utf-8"), capture_output=True, env=env,
                       cwd=str(TMP / "work"), timeout=180, **kw)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def posix(path, event):
    return run(["/bin/sh", "-c", HOOK[event]], path, event)


def powershell(exe, path, event):
    """Claude Code sans Git Bash : placeholders réécrits en ${env:…}, -Command, puis sa suite ajoutée."""
    cmd = HOOK[event].replace("${CLAUDE_PLUGIN_ROOT}", "${env:CLAUDE_PLUGIN_ROOT}")
    cmd += "\n; if (-not $?) { if ($LASTEXITCODE -eq 2) { exit 2 } }"
    return run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd], path, event)


def git_bash():
    """Le Git Bash que Claude Code prendrait (CLAUDE_CODE_GIT_BASH_PATH, Program Files, ou à côté de git)."""
    found = [os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"), r"C:\Program Files\Git\bin\bash.exe",
             r"C:\Program Files (x86)\Git\bin\bash.exe"]
    git = shutil.which("git")
    if git:
        found.append(os.path.join(os.path.dirname(git), "..", "..", "bin", "bash.exe"))
        found.append(os.path.join(os.path.dirname(git), "..", "bin", "bash.exe"))
    return next((p for p in found if p and os.path.isfile(p)), None)


def link(folder, name, target):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).symlink_to(target)
    return str(folder)


def started(res):
    c, out, err = res
    return c == 0 and "Cerveau persistant" in out


def says(res, words):
    c, out, err = res
    lines = [x for x in err.splitlines() if x.strip()]
    return c == 1 and len(lines) == 1 and lines[0].startswith("🧠 cerveau en pause : " + words)


r = subprocess.run(["uv", "python", "find", "3.9"], capture_output=True, text=True)
OLD = r.stdout.strip() if r.returncode == 0 else ""
if not OLD:
    print("· Python 3.9 introuvable (uv python install 3.9) : cas du Python trop ancien sautés")
NEW = getattr(sys, "_base_executable", None) or sys.executable  # l'interpréteur lui-même, pas celui d'un venv

if not WIN:
    only3 = link(TMP / "seul3", "python3", NEW)
    res = posix(only3, "session-start")
    check(started(res), "python3 seul (vrai Python, aucun `python`) : le démarrage injecte le cerveau", res)
    if OLD:
        old3 = link(TMP / "vieux3", "python3", OLD)
        res = posix(old3, "prompt")
        check(says(res, "Python trop ancien"), "vrai Python 3.9 seul : refusé, une ligne en français", res)
        good = link(TMP / "bon", "python", NEW)
        res = posix(f"{old3}:{good}", "session-start")
        check(started(res), "vrai Python 3.9 puis un bon `python` : le second reçoit l'entrée entière", res)
    res = posix(str(TMP / "work"), "prompt")
    check(says(res, "aucun Python"), "aucun Python : une ligne en français", res)
    if sys.platform == "darwin":  # le python3 d'Apple (outils de développement, 3.9.6), sans `python`
        res = posix("/usr/bin:/bin:/usr/sbin:/sbin", "prompt")
        check(res[0] == 0 or says(res, "Python trop ancien"), "macOS de base (/usr/bin/python3 d'Apple) : le cerveau "
              "tourne, ou la ligne « Python trop ancien », jamais une erreur opaque", res)
else:
    here = os.path.dirname(NEW)
    for exe in [p for p in (shutil.which("powershell"), shutil.which("pwsh")) if p]:
        name = Path(exe).stem
        res = powershell(exe, f"{here};{SYS32}", "session-start")
        check(started(res), f"{name}, sans Git Bash dans le PATH, vrai python.exe : le démarrage injecte le cerveau", res)
        if OLD:
            res = powershell(exe, f"{os.path.dirname(OLD)};{SYS32}", "prompt")
            check(says(res, "Python trop ancien"), f"{name}, vrai Python 3.9 seul : refusé, une ligne en français", res)
        res = powershell(exe, SYS32, "prompt")
        check(says(res, "aucun Python"), f"{name}, aucun Python : une ligne en français", res)
        res = powershell(exe, SYS32, "pre-agent")
        check(res[0] == 0 and not res[2].strip(), f"{name}, aucun Python, hook de l'outil Agent : code 0 (sinon "
              "l'outil serait bloqué sans Git Bash)", res)
    bash = git_bash()
    if bash:
        res = run([bash, "-c", HOOK["session-start"]], f"{here};{SYS32}", "session-start")
        check(started(res), "Git Bash, vrai python.exe : le démarrage injecte le cerveau", res)
    else:
        print("· Git Bash introuvable : cas Git Bash sauté")

if not FAIL and not OK:
    FAIL.append("aucun cas lancé")
sys.path.insert(0, str(CODE))
from brainkit.common import remove_tree  # noqa: E402

remove_tree(TMP, wait=60)
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
