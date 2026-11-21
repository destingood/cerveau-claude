"""Les hooks tournent même sans la commande `python` (décision E1 du plan, étape 6) : le lanceur essaie python3, python,
puis py, saute un Python trop ancien (ou Python 2), passe l'entrée, la sortie et le code de sortie tels quels, et sans
aucun Python utilisable dit en une ligne quoi installer. Chaque hook est lancé comme Claude Code le lance : forme exec
(`command` + `args`, cherché dans le PATH, sans shell) ou forme shell (`sh -c` ; Git Bash ou PowerShell sous Windows,
https://code.claude.com/docs/en/hooks). hooks.json, l'installation classique et `brain publish` disent la même chose.

Lancement : python tests/test_lanceur.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-lanceur-test-"))
CODE = Path(__file__).resolve().parent.parent
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS", "CERVEAU_PYTHON",
          "CERVEAU_LANCEUR"):
    os.environ.pop(k, None)
os.environ.update(CLAUDE_CONFIG_DIR=str(TMP / "claude"), BRAIN_HOME=str(TMP / "brain"), HOME=str(TMP / "home"),
                  USERPROFILE=str(TMP / "home"), BRAIN_OFFLINE="1")
for d in (TMP / "claude", TMP / "brain", TMP / "home", TMP / "work"):
    d.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(CODE))
WIN = os.name == "nt"
REAL = Path(sys.executable).as_posix()
SH = shutil.which("sh") or ("/bin/sh" if not WIN else None)  # sous Windows : le sh de Git Bash, s'il est là


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


try:
    from brainkit import lanceur
except ImportError:  # code d'avant le lanceur : les vérifications qui s'en servent échouent, les autres tournent
    lanceur = None
from brainkit import install, publish  # noqa: E402
from brainkit.common import remove_tree  # noqa: E402


def fake(folder, name, body):
    """Un faux interpréteur (script sh) seul dans son dossier du PATH."""
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / name
    exe.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8", newline="\n")
    exe.chmod(0o755)
    return folder


def relay(folder, name):
    """`name` qui lance le vrai Python de ce test."""
    return fake(folder, name, f'exec "{REAL}" "$@"')


# Un vrai Python, mais qui se dit 3.9.6 : brain.py le refuse comme il refuserait le macOS de base (Python 3.9.6).
TROP_VIEUX = (f'[ "$1" = -c ] && {{ echo 3.9.6; exit 0; }}; [ "$1" = -I ] && shift; [ "$1" = -S ] && shift; exec "{REAL}" '
              "-I -S -c \"import sys; sys.version_info = (3, 9, 6, 'final', 0); sys.argv = sys.argv[1:]; import runpy; "
              "runpy.run_path(sys.argv[0], run_name='__main__')\" \"$@\"")
PY2 = 'case "$1" in -I|-S) echo "Unknown option: -I" >&2; echo "usage: python [option] ..." >&2; exit 2;; esac; echo 2.7.18'

P = {"seul3": relay(TMP / "p-seul3", "python3"), "seulpython": relay(TMP / "p-seulpython", "python"),
     "vieux": fake(TMP / "p-vieux", "python3", TROP_VIEUX), "py2": fake(TMP / "p-py2", "python", PY2)}
P["rien"] = TMP / "p-rien"
P["rien"].mkdir()
P["vieux+bon"] = f"{P['vieux']}{os.pathsep}{P['seulpython']}"
P["vieux+py2"] = f"{P['vieux']}{os.pathsep}{P['py2']}"
SPEC = json.loads((CODE / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
PLUGIN_JSON = json.loads((CODE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))


def plugin_hook(event):
    """Le hook de hooks.json qui lance `brain.py hook <event>`."""
    for entries in SPEC.values():
        for e in entries:
            for h in e["hooks"]:
                text = " ".join([h.get("command", "")] + h.get("args", []))
                if f"hook {event}" in text:
                    return h
    raise KeyError(event)


def env_for(path, **extra):
    e = {k: v for k, v in os.environ.items() if k != "PATH"}
    e.update(PATH=str(path), CLAUDE_PLUGIN_ROOT=str(CODE), **extra)
    if WIN:
        e["PATH"] += os.pathsep + os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    return e


def run_like_claude(h, path, payload, shell=None, **extra):
    """Lance un hook comme Claude Code : forme exec (cherché dans le PATH du hook, sans shell ; ${CLAUDE_PLUGIN_ROOT}
    remplacé dans command et args) ou forme shell (sh -c). → (code, sortie, erreur) ; code None : ne démarre pas."""
    env = env_for(path, **extra)
    data = json.dumps(payload).encode("utf-8")
    if "args" in h:
        argv = [a.replace("${CLAUDE_PLUGIN_ROOT}", str(CODE)) for a in [h["command"], *h["args"]]]
        found = shutil.which(argv[0], path=env["PATH"]) if not os.path.dirname(argv[0]) else argv[0]
        if not found:  # ce que fait Claude Code : « failed to start », notice « hook error », rien d'enregistré
            return None, "", f"{argv[0]}: introuvable dans le PATH du hook"
        argv[0] = found
    else:
        argv = [shell or SH, "-c", h["command"]]
    r = subprocess.run(argv, input=data, capture_output=True, env=env, cwd=str(TMP / "work"), timeout=120)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def payload(sid, **kw):
    return {"session_id": sid, "cwd": str(TMP / "work"), **kw}


START = plugin_hook("session-start")
PROMPT = plugin_hook("prompt")

# ------------------------------------------------------------------ 1. le vrai lanceur, PATH par PATH (sh)
if SH:
    c, out, err = run_like_claude(START, P["seul3"], payload("a1", source="startup"))
    check(c == 0 and "Cerveau persistant" in out, "PATH avec python3 seul (macOS, Debian) : le démarrage injecte le "
          "cerveau", (c, out[:300], err[-300:]))
    c, out, err = run_like_claude(START, P["seulpython"], payload("a2", source="startup"))
    check(c == 0 and "Cerveau persistant" in out, "PATH avec python seul : le démarrage injecte le cerveau",
          (c, out[:300], err[-300:]))
    c, out, err = run_like_claude(START, P["vieux+bon"], payload("a3", source="startup"))
    check(c == 0 and "Cerveau persistant" in out, "python3 trop ancien (3.9) puis un bon `python` : le lanceur passe "
          "au suivant, qui reçoit l'entrée entière", (c, out[:300], err[-300:]))
    for label, key, words in (("aucun Python", "rien", "aucun Python trouvé"),
                              ("Python trop ancien seul (3.9)", "vieux", "Python trop ancien"),
                              ("Python 2 seul", "py2", "Python trop ancien"),
                              ("trop ancien, puis Python 2", "vieux+py2", "Python trop ancien")):
        c, out, err = run_like_claude(PROMPT, P[key], payload("a4", prompt="on continue"))
        lines = [x for x in err.splitlines() if x.strip()]
        check(c == 1 and out == "" and len(lines) == 1 and lines[0].startswith("🧠 cerveau en pause : " + words)
              and "3.10" in lines[0] and "python.org" in lines[0] and "Prérequis" in lines[0],
              f"{label} : une seule ligne, en français, qui dit quoi installer (code 1 : notice de Claude Code, "
              "jamais 2 qui bloquerait le message)", (c, out[:200], err[-500:]))
    for event in ("stop", "post-bash", "pre-agent", "session-end", "post-compact", "pre-compact"):
        c, out, err = run_like_claude(plugin_hook(event), P["rien"], payload("a5"))
        check(c == 0 and out == "" and err == "", f"aucun Python, hook {event} : silencieux (la ligne est dite au "
              "démarrage et à chaque message, pas trois fois par message)", (c, out, err))
    # Entrée, sortie, code de sortie et options passent tels quels.
    seen = TMP / "vu"
    spy = fake(TMP / "p-espion", "python3", f'printf "%s\\n" "$@" > "{seen.as_posix()}.args"; '
               f'echo "$CERVEAU_LANCEUR" > "{seen.as_posix()}.env"; exec "{REAL}" -c "import sys; '
               f"open(sys.argv[1], 'wb').write(sys.stdin.buffer.read()); sys.stdout.buffer.write('sortie brute é'.encode()); "
               f'sys.exit(5)" "{seen.as_posix()}.in"')
    data = {"session_id": "a6", "prompt": "accentué é — 🧠 \" ' $HOME `x`", "cwd": str(TMP / "work")}
    c, out, err = run_like_claude(PROMPT, spy, data)
    args = Path(f"{seen}.args").read_text(encoding="utf-8").split("\n") if Path(f"{seen}.args").exists() else []
    check(c == 5 and out == "sortie brute é" and Path(f"{seen}.in").read_bytes() == json.dumps(data).encode("utf-8")
          and args[:2] == ["-I", "-S"] and args[2].endswith("brain.py") and args[3:5] == ["hook", "prompt"]
          and Path(f"{seen}.env").read_text(encoding="utf-8").strip() == "1",
          "entrée, sortie et code de sortie passent tels quels ; Python lancé avec -I -S", (c, out, err, args))
    # CERVEAU_PYTHON, réglé par l'utilisateur : essayé en premier.
    c, out, err = run_like_claude(PROMPT, P["rien"], payload("a7", prompt="on continue"),
                                  CERVEAU_PYTHON=str(P["seul3"] / "python3"))
    check(c == 0 and err == "", "CERVEAU_PYTHON (chemin complet) : essayé en premier, même hors du PATH", (c, err[-300:]))
    # Alias du Microsoft Store (sans paquet Python du Store, il ouvre le Store) : sauté sans être lancé.
    store = TMP / "Users" / "x" / "AppData" / "Local" / "Microsoft" / "WindowsApps"
    fake(store, "python3", f'echo lance > "{(TMP / "store-lance").as_posix()}"; exit 49')
    c, out, err = run_like_claude(PROMPT, f"{store}{os.pathsep}{P['seulpython']}", payload("a8", prompt="on continue"))
    check(c == 0 and err == "" and not (TMP / "store-lance").exists(),
          "alias python3 du Microsoft Store sans Python du Store : sauté (jamais lancé), `python` prend le relais",
          (c, err[-300:]))
    (store / "PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0").mkdir()
    c, out, err = run_like_claude(PROMPT, f"{store}{os.pathsep}{P['seulpython']}", payload("a9", prompt="on continue"),
                                  OS="Windows_NT")
    check(c == 0 and err == "" and (TMP / "store-lance").exists(),
          "Python du Store installé : son alias est essayé ; code 9009 (49 dans Git Bash) → le suivant", (c, err[-300:]))
else:
    print("· lanceur en sh : sauté (pas de sh ici)")

# ------------------------------------------------------------------ 2. Windows sans Git Bash : la partie PowerShell
PWSH = [p for p in (shutil.which("pwsh"), shutil.which("powershell")) if p] if WIN else []
for ps in PWSH:
    def run_ps(h, path, data, **extra):
        """Comme Claude Code sans Git Bash : ${CLAUDE_PLUGIN_ROOT} → ${env:…}, -Command, et sa suite ajoutée."""
        cmd = h["command"].replace("${CLAUDE_PLUGIN_ROOT}", "${env:CLAUDE_PLUGIN_ROOT}")
        cmd += "\n; if (-not $?) { if ($LASTEXITCODE -eq 2) { exit 2 } }"
        r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                           input=json.dumps(data).encode("utf-8"), capture_output=True, env=env_for(path, **extra),
                           cwd=str(TMP / "work"), timeout=180)
        return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")

    shim = TMP / "p-cmd"
    shim.mkdir(exist_ok=True)
    (shim / "python3.cmd").write_text(f'@"{sys.executable}" %*\r\n@exit /b %errorlevel%\r\n', encoding="utf-8")
    name = Path(ps).stem
    c, out, err = run_ps(START, shim, payload("w1", source="startup"))
    check(c == 0 and "Cerveau persistant" in out, f"{name} : le démarrage passe par la partie PowerShell (entrée et "
          "sortie intactes, accents compris)", (c, out[:300], err[-400:]))
    c, out, err = run_ps(PROMPT, P["rien"], payload("w2", prompt="on continue"))
    lines = [x for x in err.splitlines() if x.strip()]
    check(c == 1 and out.strip() == "" and len(lines) == 1 and lines[0].startswith("🧠 cerveau en pause : aucun Python"),
          f"{name} : aucun Python → la ligne en français (UTF-8), code 1", (c, out[:200], err[-400:]))
    c, out, err = run_ps(plugin_hook("pre-agent"), P["rien"], payload("w3"))
    check(c == 0 and err.strip() == "", f"{name} : aucun Python, hook de l'outil Agent → code 0 (un autre code bloquerait "
          "l'outil sans Git Bash)", (c, err[-300:]))

# ------------------------------------------------------------------ 3. l'ancienne forme : le défaut corrigé
if not WIN:  # (sous Windows, CreateProcess cherche dans le PATH du parent : on ne peut pas imiter le hook)
    c, out, err = run_like_claude(PROMPT, P["seul3"], payload("b1", prompt="on continue"))
    check(c == 0, "hook du message avec python3 seul dans le PATH : il démarre (la forme exec `python` échouait)",
          (c, err[-300:]))

# ------------------------------------------------------------------ 4. hooks.json, installation classique, publish
want = {event: [{**({"matcher": m} if m else {}), "hooks": [publish._hook(arg, timeout, status)]}]
        for event, arg, timeout, status, m in install.EVENTS}
check(SPEC == want, "hooks.json = ce que construit `brain publish`")
classic = install.merged_settings({})["hooks"]
plugin_events = {ev: [(e.get("matcher"), h["timeout"], h.get("statusMessage"), h.get("async")) for e in v for h in e["hooks"]]
                 for ev, v in SPEC.items()}
classic_events = {ev: [(e.get("matcher"), h["timeout"], h.get("statusMessage"), h.get("async")) for e in v for h in e["hooks"]]
                  for ev, v in classic.items()}
check(plugin_events == classic_events and plugin_events.get("PreCompact") == [(None, 15, None, True)],
      "installation classique = plugin : mêmes événements, outils visés, délais, messages, PreCompact sans attente",
      (plugin_events, classic_events))
for event, arg, *_ in install.EVENTS:
    p = SPEC[event][0]["hooks"][0]
    k = classic[event][0]["hooks"][0]
    same = lanceur is not None and "args" not in p and lanceur.SH in p["command"] and f'"" hook {arg};' in p["command"]
    if lanceur is not None and not WIN:
        same = same and k["command"] == "/bin/sh" and k["args"][:2] == ["-c", lanceur.SH] and k["args"][-2:] == ["hook", arg]
        same = same and k["args"][3] == str(install.BRAIN_PY.parent) and os.path.isfile(k["args"][4])
    elif lanceur is not None:  # Windows : l'interpréteur de `brain install` directement (ni Git Bash ni PowerShell)
        same = same and k["args"][-3:] == [str(install.BRAIN_PY), "hook", arg] and k["args"][-5:-3] == ["-I", "-S"]
    check(same, f"{event} : plugin et installation classique lancent le même lanceur (brain.py hook {arg}, -I -S)", (p, k))
check(all(install._is_ours(e) for v in classic.values() for e in v) and all(install._is_ours(e) for v in SPEC.values()
                                                                            for e in v)
      and not install.merged_settings({"hooks": classic}, remove_only=True).get("hooks")
      and not install.merged_settings({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": (
          '"C:/Python312/python.exe" -I -S "C:/Users/x/.claude/brain/brain.py" hook stop')}]}]}}, remove_only=True).get("hooks"),
      "hooks du cerveau reconnus dans toutes leurs formes (désinstallation, passage au plugin), même ceux d'avant")
user_hook = {"hooks": [{"type": "command", "command": "echo mon-hook"}]}
check(install.merged_settings({"hooks": {"Stop": [user_hook]}}, remove_only=True)["hooks"]["Stop"] == [user_hook],
      "un hook de l'utilisateur n'est jamais pris pour celui du cerveau")
if SH and not WIN and lanceur is not None:
    c, out, err = run_like_claude(classic["SessionStart"][0]["hooks"][0], P["rien"], payload("c1", source="startup"))
    check(c == 0 and "Cerveau persistant" in out, "installation classique : l'interpréteur de `brain install` sert même "
          "sans aucun Python dans le PATH", (c, out[:200], err[-300:]))
    k = json.loads(json.dumps(classic["UserPromptSubmit"][0]["hooks"][0]))
    k["args"][4] = str(TMP / "python-disparu")
    c, out, err = run_like_claude(k, P["seul3"], payload("c2", prompt="on continue"))
    check(c == 0 and err == "", "installation classique, Python de `brain install` disparu : le lanceur prend python3",
          (c, err[-300:]))
server = (PLUGIN_JSON.get("mcpServers") or {}).get("cerveau") or {}
check(lanceur is not None and server.get("command") == lanceur.MCP_COMMAND == "${CERVEAU_PYTHON:-python}"
      and server.get("args") == ["-I", "-S", "${CLAUDE_PLUGIN_ROOT}/brain.py", "mcp"],
      "serveur MCP : forme exec seulement (pas de lanceur possible) → `python`, ou CERVEAU_PYTHON", server)
if lanceur is not None:
    for event in ("prompt", "pre-agent"):
        for part in (lanceur.SH, lanceur.ps(event)):
            check("'" not in part, f"lanceur ({event}) : aucune apostrophe droite dans une partie (sinon plus polyglotte)")
    gate = (CODE / "brain.py").read_text(encoding="utf-8")
    check(f"sys.exit({lanceur.TROP_ANCIEN})" in gate and "sys.version_info < (3, 10)" in gate
          and gate.index("sys.version_info < (3, 10)") < gate.index("from brainkit"),
          "brain.py refuse un Python trop ancien avant tout import du cerveau, avec le code que le lanceur attend")

# ------------------------------------------------------------------ 5. brain.py sous un Python trop ancien, à la main
r = subprocess.run([REAL, "-I", "-S", "-c", "import sys; sys.version_info = (3, 9, 6, 'final', 0); sys.argv = sys.argv[1:]; "
                    "import runpy; runpy.run_path(sys.argv[0], run_name='__main__')", str(CODE / "brain.py"), "doctor"],
                   capture_output=True, env={k: v for k, v in os.environ.items() if k != "CERVEAU_LANCEUR"}, timeout=60)
err = r.stderr.decode("utf-8", "replace")
check(r.returncode == 1 and "Python 3.9 est trop ancien" in err and "3.10" in err and "Traceback" not in err,
      "brain.py lancé à la main sous Python 3.9 : message en français, pas de trace", (r.returncode, err[-300:]))

# ------------------------------------------------------------------ 6. brain doctor : quel Python lancent les hooks
W = TMP / "doc"
(W / "claude" / "plugins").mkdir(parents=True)
(W / "claude" / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
    "cerveau@cerveau": [{"scope": "user", "installPath": str(CODE)}]}}), encoding="utf-8")


def doctor(path):
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(W / "claude"), BRAIN_HOME=str(W / "brain"), PATH=str(path))
    r = subprocess.run([REAL, "-I", "-S", str(CODE / "brain.py"), "doctor"], capture_output=True, env=env, timeout=180)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


if not WIN:
    c, out = doctor(P["seul3"])
    check(c == 0 and "✓ commande `python3` des hooks : " in out and "rien n'est enregistré" not in out,
          "doctor, python3 seul : les hooks lanceront python3 (✓)", out[-900:])
    check("✗ le serveur MCP du plugin lance `python`, introuvable ici" in out and "(les hooks, eux, tournent)" in out
          and '"CERVEAU_PYTHON": ' in out and "python-is-python3" in out,
          "doctor, python3 seul : le serveur MCP (`python`) ne démarre pas → la ligne CERVEAU_PYTHON toute prête", out[-900:])
    c, out = doctor(P["vieux"])
    check("✗ les hooks du plugin lancent `python3` (" in out and "version 3.9.6 trop ancienne" in out
          and "✗ les hooks du plugin lancent `python`, introuvable ici → rien n'est enregistré automatiquement" in out
          and "brew install python" in out, "doctor, python3 trop ancien seul : ✗ et quoi installer", out[-900:])
    c, out = doctor(P["vieux+bon"])
    check("✓ commande `python` des hooks : " in out and "ignorés avant lui : `python3`" in out,
          "doctor : python3 trop ancien ignoré, `python` retenu, et dit", out[-900:])

if not remove_tree(TMP, wait=60):  # tâches de fond du cerveau testé : on attend qu'elles aient fini d'y écrire
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
