"""Allow-listed repositories of the code pack, their guard and their objects (ADR-047).

The configuration loader already refuses a listed path that overlaps CERVEAU. The guard checks
again each time a tool opens a repository, on what git itself reports: the folder must be the top
of its own repository, and neither its git directory, nor its common directory, nor its object
store may lie in CERVEAU (a worktree of CERVEAU placed elsewhere keeps its objects in CERVEAU's
``.git``); a repository that borrows objects from another (``alternates``) is refused.

Only committed objects are read, never the working tree: a symbolic link is a tree entry that is
refused, not a link that is followed, and uncommitted files stay out of reach. Paths are relative
POSIX paths that cannot climb out (``..``), reach ``.git``, or name a sensitive file (R6).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from core.code.git import GitError, GitRunner
from core.config.loader import (
    CERVEAU_ROOT,
    BlockedFeatureError,
    CodeRepository,
    ConfigError,
    load_config,
)

REPO_ID = r"^[a-z0-9][a-z0-9-]{0,39}$"
# A branch, a tag, a commit or a relative form (HEAD~2, main^). No range (..), no reflog (@{),
# no option (leading -), no path (:), no space; ".." is refused by check_rev.
REVISION = r"^[A-Za-z0-9_][A-Za-z0-9._/~^-]{0,99}$"
_REVISION = re.compile(REVISION)
_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
MAX_PATH_CHARS = 300
_SMALL = 8_000
MAX_TREE_BYTES = 8_000_000
# Header line of each object in ``cat-file --batch``: "<sha> blob <size>\n", plus the final "\n".
_BATCH_HEADER_BYTES = 100

# Content never shown (R6). Compared without case, on every segment of the path.
_SECRET_DIRS = frozenset({"secrets"})
_KEY_NAMES = frozenset(
    {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "id_ecdsa_sk", "id_ed25519_sk"}
)
_CREDENTIAL_NAMES = frozenset(
    {".netrc", "_netrc", ".git-credentials", ".pypirc", ".npmrc", ".dockercfg", "credentials"}
)
_KEY_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".ppk")

MODES = {
    "100644": "file",
    "100755": "file",
    "040000": "directory",
    "120000": "symlink",
    "160000": "submodule",
}


class RepoError(Exception):
    """A refused or failed read. The message is French and safe to show to the planner."""


@dataclass(frozen=True)
class Repository:
    id: str
    # Resolved, and checked against what git reports.
    root: Path
    github: str | None
    pytest: bool
    image: str | None


@dataclass(frozen=True)
class TreeItem:
    mode: str
    type: str
    sha: str
    # None for a directory or a submodule.
    size: int | None
    path: str

    @property
    def kind(self) -> str:
        return MODES.get(self.mode, "other")


def load_repositories(config_dir: Path) -> tuple[CodeRepository, ...]:
    """The allow list of ``code.yaml``, read again at each call; blocked while A_DEFINIR (E2)."""
    try:
        config = load_config(config_dir)
    except ConfigError:
        raise RepoError("configuration invalide : lancer `cerveau config check`") from None
    try:
        config.require("code.repositories")
    except BlockedFeatureError as exc:
        raise RepoError(str(exc)) from None
    return tuple(config.code.repositories)


def is_sensitive(path: str) -> bool:
    """Environment files, ``secrets/``, private keys and credential files (R6)."""
    for segment in path.lower().split("/"):
        if segment in _SECRET_DIRS or segment in _KEY_NAMES or segment in _CREDENTIAL_NAMES:
            return True
        if (segment.startswith(".env") and segment != ".env.example") or segment.endswith(".env"):
            return True
        if segment.endswith(_KEY_SUFFIXES):
            return True
    return False


def check_path(path: str) -> str:
    """A path relative to the top of the repository, in POSIX form, inside it, not sensitive."""
    path = path.removesuffix("/")
    if not path or len(path) > MAX_PATH_CHARS:
        raise RepoError(f"chemin vide ou de plus de {MAX_PATH_CHARS} caractères")
    if "\\" in path or ":" in path or any(unicodedata.category(c) in ("Cc", "Cf") for c in path):
        raise RepoError(
            "chemin refusé : « / » seulement, sans « \\ », « : » ni caractère invisible"
        )
    segments = path.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise RepoError("chemin refusé : relatif au dépôt, sans « . », « .. » ni « // »")
    if any(segment.lower() == ".git" for segment in segments):
        raise RepoError("chemin refusé : le dossier .git n'est pas lisible")
    if is_sensitive(path):
        raise RepoError(f"« {path} » : fichier sensible, jamais lu (R6)")
    return path


def check_rev(rev: str) -> str:
    if not _REVISION.match(rev) or ".." in rev:
        raise RepoError(f"révision « {rev} » refusée : une branche, une étiquette ou un commit")
    return rev


def _overlaps(first: Path, second: Path) -> bool:
    return first == second or first.is_relative_to(second) or second.is_relative_to(first)


class RepoReader:
    """Reads the objects of the allow-listed repositories through a ``GitRunner``."""

    def __init__(self, git: GitRunner, cerveau_root: Path = CERVEAU_ROOT) -> None:
        self.git = git
        self.cerveau = cerveau_root.resolve()

    def read(
        self,
        repo: Path,
        args: Sequence[str],
        max_bytes: int,
        *,
        literal_paths: bool = True,
        stdin: bytes | None = None,
    ) -> tuple[bytes, bool]:
        """Output of ``git -C repo <args>`` up to ``max_bytes``, and whether it was cut there."""
        try:
            out = self.git.run(
                repo, args, max_bytes=max_bytes, literal_paths=literal_paths, stdin=stdin
            )
        except GitError as exc:
            raise RepoError(str(exc)) from None
        if out.returncode != 0 and not out.truncated:
            raise RepoError(f"git {args[0]} a échoué")
        return out.stdout, out.truncated

    def _git(
        self,
        repo: Path,
        args: Sequence[str],
        max_bytes: int = _SMALL,
        *,
        stdin: bytes | None = None,
    ) -> bytes:
        stdout, truncated = self.read(repo, args, max_bytes, stdin=stdin)
        if truncated:
            raise RepoError(f"git {args[0]} : sortie de plus de {max_bytes} octets")
        return stdout

    def open(self, repositories: Sequence[CodeRepository], repo_id: str) -> Repository:
        if not repositories:
            raise RepoError("aucun dépôt autorisé : la liste blanche des dépôts est vide (E2)")
        listed = {repo.id: repo for repo in repositories}
        entry = listed.get(repo_id)
        if entry is None:
            allowed = ", ".join(sorted(listed))
            raise RepoError(f"dépôt « {repo_id} » non autorisé : liste blanche = {allowed}")
        root = entry.path.resolve()
        if _overlaps(root, self.cerveau):
            raise RepoError(f"dépôt « {repo_id} » : recouvre le dépôt CERVEAU (ADR-047)")
        if not root.is_dir():
            raise RepoError(f"dépôt « {repo_id} » : dossier introuvable")
        try:
            raw = self._git(
                root,
                [
                    "rev-parse",
                    "--path-format=absolute",
                    "--show-toplevel",
                    "--git-dir",
                    "--git-common-dir",
                ],
            )
        except RepoError:
            raise RepoError(f"dépôt « {repo_id} » : pas un dépôt git lisible") from None
        top, *stores = (Path(line).resolve() for line in raw.decode("utf-8").splitlines())
        if top != root:
            raise RepoError(f"dépôt « {repo_id} » : le dossier n'est pas la racine de son dépôt")
        common = stores[-1]
        stores.append((common / "objects").resolve())
        if any(_overlaps(store, self.cerveau) for store in stores):
            raise RepoError(f"dépôt « {repo_id} » : ses objets sont ceux de CERVEAU (ADR-047)")
        if (common / "objects" / "info" / "alternates").exists():
            raise RepoError(f"dépôt « {repo_id} » : objets empruntés (alternates) refusés")
        return Repository(entry.id, root, entry.github, entry.pytest, entry.image)

    def commit(self, repo: Repository, rev: str) -> str:
        """The full hash of the commit ``rev`` names."""
        check_rev(rev)
        try:
            raw = self._git(
                repo.root,
                ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{rev}^{{commit}}"],
            )
        except RepoError:
            raise RepoError(f"révision « {rev} » introuvable dans « {repo.id} »") from None
        sha = raw.decode("ascii").strip()
        if not _SHA.match(sha):
            raise RepoError(f"révision « {rev} » : réponse de git inattendue")
        return sha

    def tree(
        self, repo: Repository, treeish: str, path: str | None = None, *, recursive: bool = False
    ) -> list[TreeItem]:
        """Entries of a tree (``path`` None), or the one entry at ``path``; sizes in bytes.
        ``recursive`` lists every file and submodule below, with its full path, no folder."""
        args = ["ls-tree", "-z", "-l", *(["-r"] if recursive else []), treeish]
        if path is not None:
            args += ["--", check_path(path)]
        items = []
        limit = MAX_TREE_BYTES if recursive else 2_000_000
        for record in self._git(repo.root, args, max_bytes=limit).split(b"\0"):
            if not record:
                continue
            meta, _, name = record.decode("utf-8", errors="replace").partition("\t")
            mode, kind, sha, size = meta.split()
            items.append(TreeItem(mode, kind, sha, int(size) if size.isdigit() else None, name))
        return items

    def blob(self, repo: Repository, sha: str, max_bytes: int) -> bytes:
        """The content of a blob; refused past ``max_bytes``."""
        try:
            return self._git(repo.root, ["cat-file", "blob", sha], max_bytes=max_bytes)
        except RepoError:
            raise RepoError(f"fichier illisible ou de plus de {max_bytes} octets") from None

    def blobs(self, repo: Repository, shas: Sequence[str], max_bytes: int) -> dict[str, bytes]:
        """The contents of several blobs in one ``cat-file --batch`` call, ``max_bytes`` in all."""
        wanted = list(dict.fromkeys(shas))
        if not wanted:
            return {}
        if any(not _SHA.fullmatch(sha) for sha in wanted):
            raise RepoError("empreinte d'objet refusée")
        raw = self._git(
            repo.root,
            ["cat-file", "--batch"],
            max_bytes=max_bytes + _BATCH_HEADER_BYTES * len(wanted),
            stdin="".join(f"{sha}\n" for sha in wanted).encode("ascii"),
        )
        contents: dict[str, bytes] = {}
        position = 0
        for sha in wanted:
            end = raw.find(b"\n", position)
            header = raw[position:end].decode("ascii", errors="replace").split(" ")
            if end < 0 or len(header) != 3 or header[:2] != [sha, "blob"]:
                raise RepoError("git cat-file : réponse de git inattendue")
            size = int(header[2]) if header[2].isdigit() else -1
            start, stop = end + 1, end + 1 + size
            if size < 0 or raw[stop : stop + 1] != b"\n":
                raise RepoError("git cat-file : réponse de git inattendue")
            contents[sha] = raw[start:stop]
            position = stop + 1
        return contents
