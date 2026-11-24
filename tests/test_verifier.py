"""Le hook Stop de ce dépôt (.claude/hooks/verifier.py, étape 10 du plan) : il vérifie le plugin avant que Claude
termine une tâche. Sur un faux dépôt git, dans un dossier temporaire : rien de changé ou un changement hors du plugin,
il ne dit rien ; un test qui échoue renvoie Claude au travail avec la sortie ; le même échec n'est pas renvoyé deux
fois ; trois renvois au plus dans un tour ; une erreur de syntaxe est vue même sans ruff. Puis le choix des tests sur
le vrai dépôt.

Lancement : python tests/test_verifier.py   (sortie : « N vérifications OK, M échec(s) »)"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
HOOK = CODE / ".claude" / "hooks" / "verifier.py"
TMP = Path(tempfile.mkdtemp(prefix="cerveau-verifier-test-"))
REPO = TMP / "depot"
OK, FAIL = [], []


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def git(*args, cwd=REPO):
    r = subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args], cwd=str(cwd),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


def write(rel, text, root=REPO):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def hook(active=False, args=(), root=REPO):
    """→ (code de sortie, sortie JSON lue ou None, texte brut)."""
    r = subprocess.run([sys.executable, str(root / ".claude" / "hooks" / "verifier.py"), *args], cwd=str(root),
                       input=json.dumps({"hook_event_name": "Stop", "stop_hook_active": active, "cwd": str(root)}),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                       env=dict(os.environ, PYTHONUTF8="1"))
    try:
        data = json.loads(r.stdout) if r.stdout.strip() and not args else None
    except ValueError:
        data = None
    return r.returncode, data, r.stdout + r.stderr


TEST_M = '''import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brainkit import m
ok = m.VALUE == 1
if not ok:
    print("✗ VALUE vaut 1 — " + repr(m.VALUE))
print(f"\\n{int(ok)} vérifications OK, {int(not ok)} échec(s)")
sys.exit(0 if ok else 1)
'''

# ------------------------------------------------------------------ le faux dépôt
REPO.mkdir()
git("-c", "init.defaultBranch=main", "init", "-q")
write(".claude/hooks/verifier.py", HOOK.read_text(encoding="utf-8"))
write("brainkit/__init__.py", "")
write("brainkit/m.py", "VALUE = 1\n")
write("tests/test_m.py", TEST_M)
write("plateforme/x.py", "X = 1\n")
code, out = git("add", "-A")
code, out = git("commit", "-q", "-m", "base")
check(code == 0, "faux dépôt créé", out)
STATE = REPO / ".git" / "cerveau-verifier.json"

# 1. rien de changé : silence
code, data, raw = hook()
check(code == 0 and not raw.strip(), "rien de changé : le hook ne dit rien", raw)

# 2. changement hors du plugin : silence
write("plateforme/x.py", "X = 2\n")
code, data, raw = hook()
check(code == 0 and not raw.strip(), "changement dans plateforme/ seulement : le hook ne dit rien", raw)

# 3. changement du plugin, tests verts : une ligne pour l'utilisateur, Claude n'est pas renvoyé
write("brainkit/m.py", "VALUE = 1  # commentaire\n")
code, data, raw = hook()
check(code == 0 and data and "decision" not in data and "✓ Plugin vérifié" in data.get("systemMessage", ""),
      "changement vert : message ✓ à l'utilisateur, pas de renvoi", raw)
check(STATE.exists() and "brainkit/m.py" in json.loads(STATE.read_text(encoding="utf-8")).get("green", {}),
      "l'état vert est gardé dans le dossier git", STATE.read_text(encoding="utf-8") if STATE.exists() else "absent")
code, data, raw = hook()
check(code == 0 and not raw.strip(), "même contenu déjà vérifié vert : silence (rien n'est relancé)", raw)
code, out = git("status", "--porcelain")
check("cerveau-verifier" not in out, "l'état n'apparaît pas dans git status", out)

# 4. échec simulé : Claude est renvoyé, avec le nom du test, la ligne ✗ et la commande pour le relancer
write("brainkit/m.py", "VALUE = 2\n")
code, data, raw = hook()
reason = (data or {}).get("reason", "")
check(code == 0 and data and data.get("decision") == "block", "test en échec : Claude est renvoyé (decision block)", raw)
check("test_m.py" in reason and "✗ VALUE vaut 1" in reason and "python tests/test_m.py" in reason,
      "le renvoi donne le test, la ligne en échec et la commande", reason)

# 5. Claude s'arrête sans rien changer : pas de second renvoi, l'utilisateur est prévenu une fois
code, data, raw = hook(active=True)
check(code == 0 and data and "decision" not in data and "toujours en échec" in data.get("systemMessage", ""),
      "même échec, rien de changé : pas de renvoi, l'utilisateur est prévenu", raw)
code, data, raw = hook()
check(code == 0 and not raw.strip(), "prévenu une fois seulement", raw)

# 6. trois renvois au plus dans un tour, et un nouveau tour repart de zéro
for i, value in enumerate((3, 4, 5), 1):
    write("brainkit/m.py", f"VALUE = {value}\n")
    code, data, raw = hook(active=True)
    if i < 3:
        check(data and data.get("decision") == "block", f"renvoi n° {i + 1} dans le même tour", raw)
    else:
        check(data and "decision" not in data and "après 3 essais" in data.get("systemMessage", ""),
              "au 4ᵉ échec du même tour : plus de renvoi, l'utilisateur est prévenu", raw)
write("brainkit/m.py", "VALUE = 6\n")
code, data, raw = hook(active=False)
check(data and data.get("decision") == "block", "nouveau tour : Claude est de nouveau renvoyé", raw)

# 7. corrigé : vert, et le compteur repart
write("brainkit/m.py", "VALUE = 1  # corrigé\n")
code, data, raw = hook(active=True)
check(data and "✓ Plugin vérifié" in data.get("systemMessage", ""), "corrigé : vert", raw)
check("blocks" not in json.loads(STATE.read_text(encoding="utf-8")), "vert : le compteur de renvois est remis à zéro")
write("brainkit/m.py", "VALUE = 9\n")
hook()
write("brainkit/m.py", "VALUE = 1\n")  # revenu au contenu de main : plus rien à vérifier, l'échec noté est oublié
code, data, raw = hook()
check(code == 0 and not raw.strip() and json.loads(STATE.read_text(encoding="utf-8")) == {},
      "changement annulé (contenu de main) : silence, l'état est vidé", raw + STATE.read_text(encoding="utf-8"))

# 8. erreur de syntaxe dans un fichier non suivi : vue par le lint (ruff, ou la syntaxe seule sans ruff)
write("brainkit/neuf.py", "def f(:\n")
code, data, raw = hook()
reason = (data or {}).get("reason", "")
check(data and data.get("decision") == "block" and "Lint" in reason and "neuf.py" in reason,
      "fichier nouveau, non suivi, avec une erreur de syntaxe : le lint le signale", raw)
(REPO / "brainkit" / "neuf.py").unlink()

# 9. à la main : `--tout` vérifie tout ce qui a changé, en texte, code 1 en cas d'échec
write("brainkit/m.py", "VALUE = 7\n")
code, data, raw = hook(args=("--tout",))
check(code == 1 and "test_m.py" in raw and not raw.lstrip().startswith("{"), "--tout : texte lisible, code 1 sur un échec",
      raw)
write("brainkit/m.py", "VALUE = 1  # corrigé\n")
code, data, raw = hook(args=("--tout",))
check(code == 0 and "✓ Plugin vérifié" in raw, "--tout : vert, code 0", raw)

# 10. hors d'un dépôt git : silence
BARE = TMP / "sans-git"
write(".claude/hooks/verifier.py", HOOK.read_text(encoding="utf-8"), root=BARE)
write("brainkit/m.py", "VALUE = 2\n", root=BARE)
code, data, raw = hook(root=BARE)
check(code == 0 and not raw.strip(), "hors d'un dépôt git : le hook ne dit rien", raw)

# ------------------------------------------------------------------ le choix des tests, sur le vrai dépôt
spec = importlib.util.spec_from_file_location("verifier", HOOK)
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
texts = v.test_texts()


def chosen(*paths):
    return set(v.select_tests(list(paths), texts))


check({"test_rappel.py", "test_decoupage.py"} <= chosen("brainkit/search.py"), "search.py → test_rappel (et test_decoupage)",
      chosen("brainkit/search.py"))
check("test_carte.py" in chosen("brainkit/carte_graphe.py"), "carte_graphe.py → test_carte (famille du module)")
check("test_noyau.py" in chosen("brainkit/lexicon.py"), "un module qu'aucun test n'importe → au moins le noyau")
check("test_vue3d.py" in chosen("brainkit/vue3d/page.html"), "la page de la vue 3D → test_vue3d")
check("test_carriere.py" in chosen("skills/carriere-commerciale/scripts/cv.py"), "skill carriere-commerciale → test_carriere")
check("test_page_reglages.py" in chosen("skills/brain/references/reglages.md"), "la page des réglages → test_page_reglages")
check("test_verifier.py" in chosen(".claude/hooks/verifier.py"), "le hook lui-même → ce test")
check(chosen("plateforme/core/x.py") == {"test_decoupage.py"}, "un fichier de la plateforme n'ajoute aucun test",
      chosen("plateforme/core/x.py"))
check(not v.in_scope("plateforme/docs/plans/plan-cerveau.md") and v.in_scope("brainkit/store.py"),
      "plateforme/ est hors du périmètre du hook")

# ------------------------------------------------------------------ grille de tri d'un échec (étape 19)
write("brainkit/m.py", "VALUE = 41\n")
code, data, raw = hook()
check(data and data.get("decision") == "block" and "Tri de chaque échec" in data.get("reason", "")
      and "test périmé" in data.get("reason", ""), "échec : la grille de tri (régression, instable, environnement, périmé)",
      raw)
write("brainkit/m.py", "VALUE = 1  # corrigé\n")
hook()

# ------------------------------------------------------------------ contrôle d'un CLAUDE.md avant écriture (étape 19)
CHECK = CODE / ".claude" / "hooks" / "claude_md.py"


def md_hook(tool, inp):
    r = subprocess.run([sys.executable, str(CHECK)], input=json.dumps({"tool_name": tool, "tool_input": inp}),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    return r.returncode, r.stderr


bad = "# Projet\n\n## Tests\n## Règles\nLe dépôt est dans /home/alice/projets/site.\n"
code, err = md_hook("Write", {"file_path": str(TMP / "CLAUDE.md"), "content": bad})
check(code == 2 and "chemin absolu" in err and "section vide" in err, "CLAUDE.md avec un chemin absolu et une section vide : "
      "écriture refusée, raisons dites", err)
code, err = md_hook("Write", {"file_path": str(TMP / "CLAUDE.md"), "content": "# Projet\n\n## Tests\n`python tests/x.py`\n"})
check(code == 0 and not err, "CLAUDE.md propre : écrit sans un mot", err)
code, err = md_hook("Write", {"file_path": str(TMP / "notes.md"), "content": bad})
check(code == 0 and not err, "un autre fichier n'est pas regardé", err)
(TMP / "CLAUDE.md").write_text("# Projet\n\n## Tests\n`python tests/x.py`\n", encoding="utf-8")
code, err = md_hook("Edit", {"file_path": str(TMP / "CLAUDE.md"), "old_string": "`python tests/x.py`",
                             "new_string": "clé : sk-ant-" + "abcdefghijklmnopqrstuv"})
check(code == 2 and "clé ou un jeton" in err, "Edit qui mettrait une clé dans un CLAUDE.md : refusé", err)
for real in (CODE / "CLAUDE.md", CODE / "plateforme" / "CLAUDE.md"):
    code, err = md_hook("Write", {"file_path": str(real), "content": real.read_text(encoding="utf-8")})
    check(code == 0, f"{real.relative_to(CODE)} tel qu'il est : accepté (pas de faux positif)", err)

settings = json.loads((CODE / ".claude" / "settings.json").read_text(encoding="utf-8"))
pre = [h for g in settings.get("hooks", {}).get("PreToolUse", []) for h in g.get("hooks", [])]
check(any("claude_md.py" in " ".join(h.get("args", [])) for h in pre), "le contrôle des CLAUDE.md est déclaré (PreToolUse)",
      pre)
stops = [h for g in settings.get("hooks", {}).get("Stop", []) for h in g.get("hooks", [])]
check(any("verifier.py" in " ".join(h.get("args", [])) for h in stops), "le hook est déclaré dans .claude/settings.json (Stop)",
      stops)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
