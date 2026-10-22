"""The example repository of the code_repo tests and of its golden set, built in tmp_path.

History, oldest first (fixed dates and identity, so the hashes are the same on every run):
1. ``initial``: README, a 450-line module, a binary file, ``.env.example``; tagged ``v1``.
2. ``ajoute un lien``: a symbolic link to ``../../etc/passwd`` (an entry, never a file on disk).
3. ``ajoute un sous-module``: a submodule entry ``vendor/lib``.
4. ``rotation du jeton <token>``: a token in ``src/app.py`` and in the subject, a ``.env`` file,
   a Trojan Source comment.
"""

from __future__ import annotations

from pathlib import Path

from tests.code_support import add_entry, blob, commit, git, make_repo

# Built from parts: no token-looking text sits in the repository.
TOKEN = "ghp_" + "Z9y8X7w6V5u4T3s2R1q0" * 2
ENV_VALUE = "VALEUR-DU-FICHIER-ENV"
LONG_LINES = 450

README = "# Exemple\n\nProjet de démonstration du pack code.\n"
APP_BEFORE = "def main() -> int:\n    return 1\n"
# A Trojan Source comment: the right-to-left override hides how the line really reads.
TROJAN = "access = 'user'  # \u202e \u2066admin\u2069\n"
APP_AFTER = f'def main() -> int:\n    return 2\nTOKEN = "{TOKEN}"\n{TROJAN}'


def example_repo(root: Path) -> Path:
    repo = make_repo(
        root,
        {
            "README.md": README,
            "src/app.py": APP_BEFORE,
            "src/long.py": "".join(f"x_{i} = {i}\n" for i in range(1, LONG_LINES + 1)),
            "data.bin": b"\x89PNG\r\n\x1a\n\x00\x00\x00",
            ".env.example": "API_KEY=\n",
        },
    )
    git(repo, "tag", "v1")
    add_entry(repo, "120000", blob(repo, b"../../etc/passwd"), "lien", "ajoute un lien")
    add_entry(repo, "160000", git(repo, "rev-parse", "v1").strip(), "vendor/lib", "sous-module")
    commit(
        repo,
        {"src/app.py": APP_AFTER, ".env": f"API_KEY={ENV_VALUE}\n"},
        f"rotation du jeton {TOKEN}",
    )
    return repo
