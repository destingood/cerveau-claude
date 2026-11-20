"""Veille PC (pc.py) : elle propose, ne ferme jamais rien d'elle-même. Les décisions sont testées sur de faux processus
(fonctions pures, valables sur tout système : pc.py ne touche l'API Windows que pour mesurer).

Lancement : python tests/test_pc.py   (sortie : « N vérifications OK, M échec(s) »)"""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-pc-test-"))
CODE = Path(__file__).resolve().parent.parent
os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "claude")
os.environ["BRAIN_HOME"] = str(TMP / "brain")
sys.path.insert(0, str(CODE))
OK, FAIL = [], []


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


from brainkit import pc  # noqa: E402
from brainkit.common import DEFAULT_CONFIG  # noqa: E402

NOW = 1_800_000_000.0
MB = 1 << 20


def ft(age_min):
    """Date de création Windows (FILETIME) d'un processus lancé il y a age_min minutes."""
    return int((NOW - age_min * 60) * 1e7) + pc.EPOCH_FT


def fake(rows):
    """rows : (pid, ppid, nom, âge en min, ligne de commande) → (procs, cmds)."""
    procs, cmds = {}, {}
    for pid, ppid, name, age, cmd in rows:
        procs[pid] = pc.Proc(pid, ppid, name, ft(age), 0, 50 * MB, 50 * MB)
        cmds[pid] = cmd
    return procs, cmds


def orphans(rows, known=()):
    procs, cmds = fake(rows)
    return find(procs, cmds, known), procs


def find(procs, cmds, known=()):
    return pc.find_orphans(procs, cmds, pc.children_map(procs), NOW, DEFAULT_CONFIG["pc"], (), known)


# --- reconnaissance précise des serveurs MCP
MCP_YES = [
    r'node C:\Users\a\AppData\Roaming\npm\node_modules\@modelcontextprotocol\server-filesystem\dist\index.js',
    r'node C:\x\node_modules\mcp-server-fetch\index.js',
    r'python -m mcp_server_git',
    r'node C:\x\node_modules\@playwright\mcp\cli.js',
    r'node C:\x\node_modules\desktop-commander-mcp\dist\index.js',
    r'python C:\x\fastmcp_app.py',
    r'uvx mcp-server-time',
    r'uvx --python 3.12 some-tool-mcp',
    r'node C:\x\npx-cli.js -y @upstash/context7-mcp',
]
MCP_NO = [
    r'python C:\dev\mcp-tools\x.py',
    r'node C:\Users\a\mcp\script.js',
    r'python C:\projets\mcp_notes\main.py',
    r'node C:\dev\mon-mcp\serveur.js',  # dossier nommé …-mcp : pas un paquet
    r'cmd /c start dev-server',
]
for c in MCP_YES:
    check(bool(pc.mcp_reason(c)), f"serveur MCP reconnu : {c[-48:]}")
for c in MCP_NO:
    check(not pc.mcp_reason(c), f"« mcp » dans un dossier : pas un serveur ({c[-40:]})", pc.mcp_reason(c))

# --- find_orphans sur de faux processus
rows = [
    (10, 99999, "node.exe", 30, r"node C:\x\node_modules\@modelcontextprotocol\server-memory\dist\index.js"),
    (11, 99999, "python.exe", 30, r"python C:\dev\mcp-tools\x.py"),
    (12, 99999, "node.exe", 3, r"node C:\x\node_modules\mcp-server-fetch\index.js"),  # trop récent
    (13, 99999, "python.exe", 30, r"python C:\brain\brain.py mcp-server"),  # le cerveau lui-même
    (14, 99999, "node.exe", 30, ""),  # illisible
]
found, procs = orphans(rows)
pids = {o["pid"] for o in found}
check(pids == {10}, "seul le serveur MCP précis et assez ancien est suspect (pas le dossier mcp-tools)", pids)
o = found[0] if found else {}
check(o.get("age", 0) >= 29 * 60 and "MCP" in o.get("why", "") and o.get("auto"),
      "le suspect porte son âge et la raison", o)

# un PID réutilisé (parent plus récent que l'enfant) n'est pas un orphelin à tort, un vrai parent vivant non plus
procs, cmds = fake([(19, 99999, "explorer.exe", 90, ""), (20, 19, "claude.exe", 60, "claude --output-format stream-json"),
                    (21, 20, "node.exe", 30, r"node C:\x\node_modules\@modelcontextprotocol\server-memory\a.js")])
check(find(procs, cmds) == [], "serveur MCP encore rattaché à une session vivante : pas suspect")

# --- liste sans --oui, fermeture seulement avec
killed = []
pc.terminate = lambda pid, create: killed.append(pid) or True  # faux : aucune vraie fermeture
procs, cmds = fake(rows[:1])
sus = find(procs, cmds)
txt = pc.clean_report(sus, None, None, None)
check(not killed and "pid 10" in txt and "node.exe" in txt and "MB" not in txt and "--oui" in txt,
      "`brain pc --clean` sans --oui : liste PID, nom, âge, mémoire, raison, ne ferme rien", txt)
check("30 min" in txt or "30" in txt, "l'âge est affiché", txt)
done = pc.kill_orphans(sus, procs)
check(killed == [10] and len(done) == 1, "avec --oui (kill_orphans) : fermé", killed)
txt = pc.clean_report(sus, done, 100 * MB, 200 * MB)
check("fermé" in txt, "rapport de fermeture", txt)
killed.clear()
check(pc.kill_orphans([{**sus[0], "tree": [os.getpid()]}], {os.getpid(): pc.Proc(os.getpid(), 0, "python.exe", ft(5), 0, 0, 0)}) == []
      and not killed, "jamais un processus de sa propre lignée")

# --- la veille propose, ne ferme pas
st = {}
line = pc.suspect_line(st, sus, {"auto_clean": True})
check("1 serveur(s) MCP orphelin" in line and "brain pc --clean --oui" in line and line.count("\n") == 0,
      "la veille annonce en une ligne le nombre et la commande", line)
check(pc.suspect_line(st, sus, {"auto_clean": True}) == "", "la même ligne n'est pas répétée")
check(pc.suspect_line({}, sus, {"auto_clean": False}) == "", "auto_clean=False : pas de liste automatique")
src = (CODE / "brainkit" / "pc.py").read_text(encoding="utf-8")
watch_src = src[src.index("def watch("):src.index("def suspect_line")]
check("kill_orphans" not in watch_src and "terminate(" not in watch_src, "watch() n'appelle aucune fermeture")
check("mcp" not in DEFAULT_CONFIG["pc"]["orphan_patterns"], "le motif « mcp » nu n'est plus dans la configuration")

import shutil  # noqa: E402

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
