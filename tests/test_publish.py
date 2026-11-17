"""`brain publish` (publish.py) : publication sur place depuis le clone du dépôt (D1 du plan v2 : GitHub est la seule
source du code), et garde-fou de l'ancien mode, qui n'efface jamais un fichier suivi par git qui n'appartient pas au
plugin (C23 : les dossiers d'un autre projet rangés dans le même dépôt).

Lancement : python tests/test_publish.py   (sortie : « N vérifications OK, M échec(s) »)"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-publish-test-"))
CODE = Path(__file__).resolve().parent.parent
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD"):
    os.environ.pop(k, None)
os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "claude")  # import en direct de publish.py : jamais le vrai PC
os.environ["BRAIN_HOME"] = str(TMP / "brain")
sys.path.insert(0, str(CODE))

from brainkit import publish  # noqa: E402
from brainkit.common import remove_tree  # noqa: E402

# Identité et signature neutres : les commits des tests passent sur un PC sans réglage git, sans clé de signature.
GIT_ENV = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_COMMITTER_NAME": "Test",
           "GIT_COMMITTER_EMAIL": "test@example.com", "GIT_CONFIG_COUNT": "3",
           "GIT_CONFIG_KEY_0": "commit.gpgsign", "GIT_CONFIG_VALUE_0": "false",
           "GIT_CONFIG_KEY_1": "tag.gpgsign", "GIT_CONFIG_VALUE_1": "false",
           "GIT_CONFIG_KEY_2": "init.defaultBranch", "GIT_CONFIG_VALUE_2": "main"}
os.environ.update(GIT_ENV)


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def repo_with(name, files):
    """Un dépôt git d'un commit, avec ces fichiers {chemin: texte}."""
    root = TMP / name
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "départ")
    return root


# ------------------------------------------------------------------ 1. ancien mode : un dossier qui n'est pas au plugin
dest = repo_with("ancien-mode", {"README.md": "x", "brainkit/vieux.py": "x = 1\n", "CONTRIBUTORS.md": "# C",
                                 "fortnite-ile/README.md": "# Île", "fortnite-ile/verse/boutique.verse": "x"})
check(publish.foreign_files(dest) == ["fortnite-ile/README.md", "fortnite-ile/verse/boutique.verse"],
      "fichiers suivis hors du plugin repérés", publish.foreign_files(dest))
try:
    publish.build(dest, repo="destingood/cerveau-claude")
    refus = ""
except RuntimeError as exc:
    refus = str(exc)
check("2 fichier(s)" in refus and "fortnite-ile/README.md" in refus and "rien n'a été effacé" in refus,
      "ancien mode : la construction refuse d'effacer un dossier suivi qui n'appartient pas au plugin", refus)
code, status = git(dest, "status", "--porcelain")
check(code == 0 and not status.strip() and (dest / "fortnite-ile" / "README.md").is_file()
      and (dest / "brainkit" / "vieux.py").is_file(), "ancien mode : rien n'est touché quand la construction refuse",
      status)

# ------------------------------------------------------------------ 2. ancien mode : ce qui est au plugin est refait
dest = repo_with("ancien-mode-propre", {"README.md": "x", "brainkit/vieux.py": "x = 1\n", "CONTRIBUTORS.md": "# C",
                                        "plateforme/README.md": "# P", ".github/workflows/ci.yml": "name: CI\n",
                                        ".mcp.json": "{}\n"})
check(publish.foreign_files(dest) == [], "rien hors du plugin : KEEP, AUTRES et ce que la construction refait")
files = publish.build(dest, repo="destingood/cerveau-claude")
check(not (dest / "brainkit" / "vieux.py").exists() and (dest / "brainkit" / "publish.py").is_file()
      and "brainkit/publish.py" in files and not (dest / ".mcp.json").exists(),
      "ancien mode : le code du plugin est reconstruit, .mcp.json (ancien, généré) retiré")
check((dest / "plateforme" / "README.md").is_file() and (dest / "CONTRIBUTORS.md").is_file()
      and (dest / ".github" / "workflows" / "ci.yml").is_file(), "ancien mode : ce qui n'est pas au plugin est gardé")

# ------------------------------------------------------------------ 3. le remote GitHub donne le dépôt
remote = repo_with("remote", {"a.txt": "a"})
for url in ("https://github.com/destingood/cerveau-claude.git", "git@github.com:destingood/cerveau-claude.git",
            "https://github.com/destingood/cerveau-claude"):
    git(remote, "remote", "remove", "origin")
    git(remote, "remote", "add", "origin", url)
    check(publish.origin_repo(remote) == "destingood/cerveau-claude", f"dépôt lu dans le remote : {url}",
          publish.origin_repo(remote))
git(remote, "remote", "set-url", "origin", "https://gitlab.example.com/a/b.git")
check(publish.origin_repo(remote) == "", "remote hors GitHub : aucun dépôt deviné")

# ------------------------------------------------------------------ 4. sur place, dans une copie du dépôt
tracked = publish.git_files(CODE)
if not tracked:  # code hors d'un clone git (archive, dossier de développement) : rien à copier
    print("· dossier du code hors git : publication sur place non vérifiée")
else:
    snap = TMP / "depot"
    for rel in tracked:
        src = CODE / rel
        if rel.split("/")[0] in publish.AUTRES or not src.is_file():  # autre projet du dépôt (lourd), sous-module
            continue
        (snap / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, snap / rel)
    git(snap, "init", "-q")
    git(snap, "add", "-A")
    git(snap, "commit", "-q", "-m", "copie du dépôt")
    # Faux dossier personnel plutôt que BRAIN_HOME : la skill /brain écrit le chemin du cerveau, qui doit rester
    # « $HOME/.claude/brain » comme dans le dépôt (jamais le vrai PC pour autant).
    env = {k: v for k, v in os.environ.items() if k not in ("BRAIN_HOME", "CLAUDE_CONFIG_DIR")}
    env.update(HOME=str(TMP / "maison"), USERPROFILE=str(TMP / "maison"))

    def publie():
        r = subprocess.run([sys.executable, str(snap / "brain.py"), "publish", "--no-check",
                            "--repo", "destingood/cerveau-claude"], capture_output=True, env=env, cwd=snap, timeout=300)
        return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")

    before = publish.git_files(snap)
    code, out = publie()
    check(code == 0 and "sur place" in out and "rien de nouveau" in out,
          "sur place : les fichiers générés du dépôt sont à jour, rien à publier", out)
    code, status = git(snap, "status", "--porcelain")
    check(not status.strip() and publish.git_files(snap) == before, "sur place : aucun fichier effacé ni modifié",
          status)

    (snap / "brouillon.txt").write_text("en cours", encoding="utf-8")
    code, out = publie()
    check(code == 1 and "pas validés" in out and "brouillon.txt" in out,
          "sur place : refus tant que des changements ne sont pas validés", out)
    (snap / "brouillon.txt").unlink()

    init = snap / "brainkit" / "__init__.py"
    text = init.read_text(encoding="utf-8")
    init.write_text(re.sub(r'__version__ = "[^"]+"', '__version__ = "99.0.0"', text), encoding="utf-8")
    git(snap, "commit", "-q", "-am", "version 99.0.0")
    code, out = publie()
    plugin = (snap / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    tagged = git(snap, "rev-parse", "-q", "--verify", "refs/tags/cerveau--v99.0.0")[0] == 0
    code_status, status = git(snap, "status", "--porcelain")
    check(code == 0 and tagged and '"version": "99.0.0"' in plugin and not status.strip()
          and set(before) <= set(publish.git_files(snap)),
          "sur place : nouvelle version, manifestes réécrits, commit et tag, rien d'effacé", out + status)

if not remove_tree(TMP, wait=60):
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
