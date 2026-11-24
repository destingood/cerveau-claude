"""Stop hook for this repository: check the plugin before Claude ends a task (plan, step 10).

When plugin files (everything outside plateforme/) changed since the last green check, it runs the
CI lint on the changed Python files and the test scripts that cover the changed files, plus
test_decoupage. A failure sends Claude back to work with the output; nothing changed means
nothing is said. The CI still runs every script, on three systems.

- Changed files: the working tree against the branch's merge base with main, plus untracked
  files. Each one is fingerprinted by content; only files whose content differs from the last
  green check are checked again.
- State lives in the git directory (never committed): <git-dir>/cerveau-verifier.json.
- Same failing content twice: Claude is not sent back again; the user is told once instead. After
  MAX_BLOCKS consecutive failures, the hook stops sending Claude back and tells the user.
- No git, not a repository, or an internal error: the hook lets Claude stop (it is a convenience,
  not a guard-rail) and says why to the user.
- By hand: `python .claude/hooks/verifier.py --tout` checks every changed file, whatever the state.

Stdlib only, Python 3.10+.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_OF_SCOPE = ("plateforme/",)
ALWAYS = ("test_decoupage.py",)
# A changed brainkit module that no test imports or names: these exercise the whole CLI.
CORE = ("test_noyau.py", "test_commandes.py", "test_erreurs.py")
FIXED = {  # changed path (or prefix) → test scripts, on top of the automatic choice
    "brain.py": ("test_noyau.py", "test_bascule.py", "test_commandes.py"),
    "hooks/": ("test_hooks_situations.py", "test_demarrage.py", "test_consommation.py"),
    "brainkit/vue3d/": ("test_vue3d.py",),
    "tests/vue3d_navigateur.js": ("test_vue3d.py",),
    "skills/": ("test_scripts_skills.py", "test_skills_regroupees.py"),
    "agents/": ("test_delegation.py",),
    ".claude-plugin/": ("test_skills_regroupees.py", "test_bascule.py"),
    ".claude/hooks/": ("test_verifier.py",),
}
SELF_TEST = "test_verifier.py"
GENERIC_NAMES = {"__init__.py", "SKILL.md", "fiche.md", "LICENSE", "sources.md", "README.md"}
LINT_DIRS = ("brain.py", "brainkit/", "skills/", "tests/", ".claude/hooks/")
RUFF_VERSION = "0.17.1"  # the version the plugin CI pins (.github/workflows/plugin.yml)
TEST_TIMEOUT_S = 300
MAX_BLOCKS = 3
TAIL_LINES = 25


def git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def merge_base() -> str:
    for ref in ("origin/main", "main"):
        out = git("merge-base", "HEAD", ref)
        if out and out.strip():
            return out.strip()
    return "HEAD"


def in_scope(rel: str) -> bool:
    """Plugin files: everything outside plateforme/, bytecode excluded (a test run rewrites it)."""
    return not rel.startswith(OUT_OF_SCOPE) and "__pycache__/" not in rel and not rel.endswith(".pyc")


def changed_files() -> dict[str, str] | None:
    """{repo-relative path: content hash, or "deleted"} for the plugin files that differ from main."""
    diff = git("diff", "--name-only", "--no-renames", merge_base())
    untracked = git("ls-files", "--others", "--exclude-standard")
    if diff is None or untracked is None:
        return None
    out = {}
    for rel in sorted({*diff.splitlines(), *untracked.splitlines()}):
        rel = rel.strip()
        if not rel or not in_scope(rel):
            continue
        path = ROOT / rel
        try:
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else "deleted"
        except OSError:
            out[rel] = "unreadable"
    return out


def fingerprint(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:16]


# ------------------------------------------------------------------ which tests
def test_texts() -> dict[str, str]:
    """Text of each test script, the hook's own test left out: it quotes paths only as examples."""
    out = {}
    for p in sorted((ROOT / "tests").glob("test_*.py")):
        if p.name == SELF_TEST:
            continue
        try:
            out[p.name] = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    return out


def module_tests(module: str, texts: dict[str, str]) -> set[str]:
    """Tests that import or call a brainkit module, or one of its family (carte_graphe → carte)."""
    found = set()
    for name in {module, module.split("_")[0]}:
        rx = re.compile(rf"from brainkit import[^\n]*\b{name}\b|brainkit[./]{name}\b|\b{name}\.[a-z_]+\(")
        found |= {t for t, s in texts.items() if rx.search(s)}
        if f"test_{name}.py" in texts:
            found.add(f"test_{name}.py")
    return found


def mentions(text: str, word: str) -> bool:
    """`word` (a path or a file name) cited as a whole: « x.py » is not found in « index.py »."""
    return re.search(rf"(?<![\w/.-]){re.escape(word)}(?![\w-])", text) is not None


def select_tests(paths: list[str], texts: dict[str, str]) -> list[str]:
    tracked = (git("ls-files") or "").splitlines()
    name_count: dict[str, int] = {}
    for t in tracked:
        name_count[t.rsplit("/", 1)[-1]] = name_count.get(t.rsplit("/", 1)[-1], 0) + 1
    chosen = set(ALWAYS)
    for rel in paths:
        if not in_scope(rel):
            continue
        name = rel.rsplit("/", 1)[-1]
        if rel.startswith("tests/test_") and rel.endswith(".py"):
            chosen.add(name)
        for key, tests in FIXED.items():
            if rel == key or (key.endswith("/") and rel.startswith(key)):
                chosen.update(tests)
        if rel.startswith("skills/") and rel.count("/") >= 2:
            skill = rel.split("/")[1]
            chosen |= {t for t, s in texts.items() if f"skills/{skill}" in s}
            if f"test_{skill.split('-')[0]}.py" in texts:
                chosen.add(f"test_{skill.split('-')[0]}.py")
        by_name = name not in GENERIC_NAMES and name_count.get(name, 0) == 1  # one tracked file has it
        chosen |= {t for t, s in texts.items() if mentions(s, rel) or (by_name and mentions(s, name))}
        m = re.fullmatch(r"brainkit/([a-z0-9_]+)\.py", rel)
        if m and m.group(1) != "__init__":
            chosen |= module_tests(m.group(1), texts) or set(CORE)
    return sorted(t for t in chosen if (ROOT / "tests" / t).is_file())


# ------------------------------------------------------------------ checks
def ruff_command() -> list[str] | None:
    if shutil.which("ruff"):
        return ["ruff"]
    if shutil.which("uvx"):
        return ["uvx", f"ruff@{RUFF_VERSION}"]
    return None


def lint(paths: list[str]) -> tuple[bool, str, bool]:
    """→ (ok, output, ruff ran). Without ruff, a syntax check of each file stands in."""
    files = [p for p in paths if p.endswith(".py") and p.startswith(LINT_DIRS) and (ROOT / p).is_file()]
    if not files:
        return True, "", True
    cmd = ruff_command()
    if cmd is None:
        errors = []
        for rel in files:
            try:
                compile((ROOT / rel).read_text(encoding="utf-8"), rel, "exec")
            except (SyntaxError, ValueError, OSError) as exc:
                errors.append(f"{rel}: {exc}")
        return not errors, "\n".join(errors), False
    try:
        r = subprocess.run([*cmd, "check", "--isolated", "--select", "F,E9", *files], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        return True, f"lint non lancé : {exc}", False
    return r.returncode == 0, (r.stdout + r.stderr).strip(), True


def run_test(name: str) -> tuple[str, bool, str, float]:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")  # read back as UTF-8 below
    t0 = time.monotonic()
    try:
        r = subprocess.run([sys.executable, str(Path("tests") / name)], cwd=ROOT, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=TEST_TIMEOUT_S)
        ok, out = r.returncode == 0, (r.stdout + r.stderr)
    except subprocess.TimeoutExpired:
        ok, out = False, f"plus de {TEST_TIMEOUT_S} s : arrêté"
    except OSError as exc:
        ok, out = False, f"lancement impossible : {exc}"
    return name, ok, out, time.monotonic() - t0


def tail(text: str, n: int = TAIL_LINES) -> str:
    lines = text.strip().splitlines()
    failures = [ln for ln in lines if ln.lstrip().startswith("✗")]
    keep = (failures[:n - 1] + lines[-1:]) if failures else lines[-n:]
    return "\n".join(keep)


# ------------------------------------------------------------------ state and output
def state_file() -> Path | None:
    out = git("rev-parse", "--absolute-git-dir")
    return Path(out.strip()) / "cerveau-verifier.json" if out and out.strip() else None


def load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path: Path, data: dict) -> None:
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


# Run by hand: check every changed file, print plain text. Not "--force": the shell guard of this
# repository refuses any command line that holds it (plateforme/.claude/hooks/guard_shell.py).
MANUAL = "--tout" in sys.argv[1:]


def emit(**fields) -> None:
    if MANUAL:
        print(fields.get("reason") or fields.get("systemMessage") or "")
        sys.exit(1 if fields.get("decision") == "block" else 0)
    sys.stdout.write(json.dumps(fields))  # ASCII escapes: safe on a cp1252 console (Windows)
    sys.exit(0)


def read_input() -> dict:
    if MANUAL or sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def main() -> None:
    try:  # printed text by hand (`--tout`) on a Windows console without PYTHONUTF8
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    hook_input = read_input()
    files = changed_files()
    spath = state_file()
    if files is None or spath is None:
        if MANUAL:
            emit(systemMessage="Pas de dépôt git lisible ici : rien à vérifier.")
        return  # not a git checkout, or git missing: nothing to compare against
    state = {} if MANUAL else load_state(spath)
    if not files and state:  # every change undone: main is the reference, nothing stays to check
        save_state(spath, {})
        state = {}
    green = state.get("green") or {}
    delta = sorted(files) if MANUAL else [p for p, h in files.items() if green.get(p) != h]
    if not delta:
        if MANUAL:
            emit(systemMessage="Aucun fichier du plugin changé par rapport à main : rien à vérifier.")
        return
    fp = fingerprint(files)
    if state.get("failed") == fp:  # Claude already saw this failure and stopped anyway
        if not state.get("announced"):
            state["announced"] = True
            save_state(spath, state)
            emit(systemMessage="⚠ Vérification du plugin toujours en échec : "
                 + ", ".join(state.get("failed_checks") or ["?"])
                 + " (rien n'a changé depuis). `python .claude/hooks/verifier.py --tout` la relance.")
        return

    texts = test_texts()
    tests = select_tests(delta, texts)
    t0 = time.monotonic()
    lint_ok, lint_out, ruff_ran = lint(delta)
    workers = max(1, min(4, os.cpu_count() or 1))
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(run_test, tests))
    elapsed = time.monotonic() - t0
    failed = [(n, out) for n, ok, out, _ in results if not ok]
    note = "" if ruff_ran else " Lint : ruff introuvable, seule la syntaxe a été contrôlée."

    if lint_ok and not failed:
        save_state(spath, {"green": files, "checked_at": time.strftime("%Y-%m-%d %H:%M")})
        emit(systemMessage=f"✓ Plugin vérifié : lint et {len(tests)} script(s) de test verts "
             f"en {elapsed:.0f} s ({len(delta)} fichier(s) changé(s)).{note}")

    checks = (["lint"] if not lint_ok else []) + [n for n, _ in failed]
    # Consecutive sends-back within one turn; a new turn (stop_hook_active false) starts again at 1.
    blocks = (int(state.get("blocks") or 0) if hook_input.get("stop_hook_active") else 0) + 1
    capped = blocks > MAX_BLOCKS and not MANUAL
    save_state(spath, {"green": green, "failed": fp, "failed_checks": checks, "blocks": blocks,
                       "announced": capped})
    parts = [f"La vérification du plugin a échoué ({len(delta)} fichier(s) changé(s), "
             f"{len(tests)} script(s) lancé(s) en {elapsed:.0f} s)."]
    if not lint_ok:
        parts.append("Lint (ruff F,E9, comme la CI) :\n" + tail(lint_out))
    for name, out in failed:
        parts.append(f"{name} — relancer : `python tests/{name}`\n" + tail(out))
    parts.append("Corrige la cause, sans retirer ni affaiblir un test. Si l'échec ne vient pas de "
                 "tes changements, dis-le à l'utilisateur avec la sortie." + note)
    reason = "\n\n".join(parts)
    if capped:
        emit(systemMessage=f"⚠ Vérification du plugin en échec après {MAX_BLOCKS} essais : "
             + ", ".join(checks) + ". Claude n'y est plus renvoyé dans ce tour ; "
             "`python .claude/hooks/verifier.py --tout` la relance.")
    emit(decision="block", reason=reason)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # a broken check must not trap Claude in a loop
        sys.stdout.write(json.dumps({"systemMessage": f"Vérification du plugin impossible : "
                                     f"{type(exc).__name__}: {exc}"}))
    sys.exit(0)
