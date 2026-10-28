"""Allow-listed repositories and their guard (ADR-047): CERVEAU refused, objects read only."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from core.code.git import GitError, GitOutput, GitRunner
from core.code.repos import (
    MAX_PATH_CHARS,
    RepoError,
    RepoReader,
    Repository,
    TreeItem,
    check_path,
    check_rev,
    is_sensitive,
    load_repositories,
)
from tests.code_support import add_entry, blob, commit, git, listed, make_repo
from tests.conftest import REPO_ROOT


class FakeGit:
    """A runner that answers without git, to reach the replies git should never give."""

    def __init__(self, output: GitOutput | None = None, error: str | None = None) -> None:
        self.output = output
        self.error = error
        self.calls: list[list[str]] = []
        self.stdin: list[bytes | None] = []

    def run(
        self,
        repo: Path,
        args: Sequence[str],
        *,
        max_bytes: int,
        literal_paths: bool = False,
        stdin: bytes | None = None,
    ) -> GitOutput:
        self.calls.append(list(args))
        self.stdin.append(stdin)
        if self.error is not None:
            raise GitError(self.error)
        assert self.output is not None
        return self.output


def fake_reader(output: GitOutput | None = None, error: str | None = None) -> RepoReader:
    return RepoReader(cast(GitRunner, FakeGit(output, error)), cerveau_root=Path("/cerveau-absent"))


@pytest.fixture
def cerveau(tmp_path: Path) -> Path:
    """A stand-in for the CERVEAU checkout, so worktrees of it can be made in tmp_path."""
    return make_repo(tmp_path / "cerveau", {"README.md": "CERVEAU\n"})


@pytest.fixture
def reader(cerveau: Path) -> RepoReader:
    return RepoReader(GitRunner(), cerveau_root=cerveau)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(
        tmp_path / "projet",
        {"README.md": "Projet\n", "src/app.py": "print('ok')\n", ".env.example": "X=\n"},
    )


# --- paths, revisions -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "config/.env.local",
        ".envrc",
        "deploy/prod.env",
        "secrets/token.txt",
        "app/Secrets/db.yaml",
        "id_rsa",
        "home/.ssh/id_ed25519",
        "certs/server.pem",
        "tls/server.KEY",
        "store.p12",
        ".netrc",
        ".git-credentials",
        ".npmrc",
        ".aws/credentials",
        "config/secrets.yaml",
        "secret/token",
        ".secrets",
        "gcp/credentials.json",
        ".pgpass",
        "web/.htpasswd",
        "infra/prod.tfvars",
        "infra/prod.tfvars.json",
        "terraform.tfstate",
        "terraform.tfstate.backup",
        "vault.kdbx",
        "keys/private.asc",
        "backup.gpg",
        ".docker/config.json",
        "home/.Docker/config.json",
    ],
)
def test_sensitive_paths(path: str) -> None:
    assert is_sensitive(path)


@pytest.mark.parametrize(
    "path",
    [
        ".env.example",
        "src/environment.py",
        "docs/secrets.md",
        "keys.py",
        "id_rsa.pub",
        "README.md",
        "src/secret_scanner.py",
        "docs/credentials.rst",
        "docker/config.json",
    ],
)
def test_ordinary_paths(path: str) -> None:
    assert not is_sensitive(path)


@pytest.mark.parametrize("path", ["src/app.py", "README.md", "src/", "a b/c-d_e.f"])
def test_a_relative_path_inside_the_repository_is_accepted(path: str) -> None:
    assert check_path(path) == path.removesuffix("/")


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("", "chemin vide"),
        ("a" * (MAX_PATH_CHARS + 1), "chemin vide ou de plus de"),
        ("../autre/x.py", "sans « . », « .. »"),
        ("src/../../x", "sans « . », « .. »"),
        ("./src", "sans « . », « .. »"),
        ("/etc/passwd", "sans « . », « .. » ni « // »"),
        ("src//app.py", "« // »"),
        ("C:/Windows/win.ini", "« : »"),
        ("src\\app.py", "« \\ »"),
        ("src/app\u202e.py", "caractère invisible"),
        ("src/app\n.py", "caractère invisible"),
        (".git/config", "le dossier .git"),
        ("sub/.GIT/hooks/x", "le dossier .git"),
        (".env", "fichier sensible"),
        ("deploy/secrets/x", "fichier sensible"),
    ],
)
def test_a_path_that_could_leave_or_leak_is_refused(path: str, reason: str) -> None:
    with pytest.raises(RepoError, match=re.escape(reason)):
        check_path(path)


@pytest.mark.parametrize(
    "rev", ["HEAD", "main", "HEAD~2", "main^", "v1.2.0", "origin/main", "a" * 40]
)
def test_a_plain_revision_is_accepted(rev: str) -> None:
    assert check_rev(rev) == rev


@pytest.mark.parametrize(
    "rev",
    ["main..HEAD", "main...HEAD", "--all", "-n", "HEAD@{1}", "@", "HEAD:src", "a b", "", "x" * 101],
)
def test_a_range_an_option_or_a_path_is_not_a_revision(rev: str) -> None:
    with pytest.raises(RepoError, match="refusée"):
        check_rev(rev)


# --- the allow list ---------------------------------------------------------------------------


def test_the_allow_list_is_blocked_while_lucas_has_not_filled_it() -> None:
    with pytest.raises(RepoError, match=re.escape("fonction bloquée « code.repositories »")):
        load_repositories(REPO_ROOT / "config")


def test_an_invalid_configuration_is_reported_without_detail(config_dir: Path) -> None:
    (config_dir / "code.yaml").write_text("repositories: 3\n", encoding="utf-8")
    with pytest.raises(RepoError, match="configuration invalide"):
        load_repositories(config_dir)


def test_the_allow_list_is_read_from_the_configuration(
    config_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    # Outside the parent of the configuration copy, which the loader takes for CERVEAU.
    repo = tmp_path_factory.mktemp("projet")
    path = config_dir / "code.yaml"
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["repositories"] = [{"id": "projet", "path": str(repo)}]
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    (entry,) = load_repositories(config_dir)
    assert (entry.id, entry.path) == ("projet", repo)


# --- opening a repository ---------------------------------------------------------------------


def test_a_listed_repository_opens(reader: RepoReader, repo: Path) -> None:
    opened = reader.open([listed("projet", repo, github="lucas/projet")], "projet")
    assert (opened.id, opened.root, opened.github, opened.pytest) == (
        "projet",
        repo.resolve(),
        "lucas/projet",
        False,
    )


def test_an_empty_allow_list_opens_nothing(reader: RepoReader) -> None:
    with pytest.raises(RepoError, match="liste blanche des dépôts est vide"):
        reader.open([], "projet")


def test_an_unlisted_repository_is_refused_and_the_list_named(
    reader: RepoReader, repo: Path
) -> None:
    with pytest.raises(RepoError, match="« autre » non autorisé : liste blanche = a, projet"):
        reader.open([listed("projet", repo), listed("a", repo)], "autre")


@pytest.mark.parametrize("where", ["root", "inside", "parent"])
def test_cerveau_is_refused_at_run_time(reader: RepoReader, cerveau: Path, where: str) -> None:
    path = {"root": cerveau, "inside": cerveau / "src", "parent": cerveau.parent}[where]
    with pytest.raises(RepoError, match=re.escape("recouvre le dépôt CERVEAU (ADR-047)")):
        reader.open([listed("x", path)], "x")


def test_the_real_cerveau_root_is_the_default(repo: Path) -> None:
    reader = RepoReader(GitRunner())
    assert reader.cerveau == REPO_ROOT.resolve()
    with pytest.raises(RepoError, match="recouvre le dépôt CERVEAU"):
        reader.open([listed("x", REPO_ROOT / "core")], "x")


def test_a_missing_folder_is_refused(reader: RepoReader, tmp_path: Path) -> None:
    with pytest.raises(RepoError, match="dossier introuvable"):
        reader.open([listed("x", tmp_path / "absent")], "x")


def test_a_folder_that_is_not_a_repository_is_refused(reader: RepoReader, tmp_path: Path) -> None:
    (tmp_path / "vide").mkdir()
    with pytest.raises(RepoError, match="pas un dépôt git lisible"):
        reader.open([listed("x", tmp_path / "vide")], "x")


def test_a_subfolder_of_a_repository_is_refused(reader: RepoReader, repo: Path) -> None:
    with pytest.raises(RepoError, match="n'est pas la racine de son dépôt"):
        reader.open([listed("x", repo / "src")], "x")


def test_a_worktree_of_cerveau_placed_elsewhere_is_refused(
    reader: RepoReader, cerveau: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "ailleurs"
    git(cerveau, "worktree", "add", "-q", "--detach", str(elsewhere))
    with pytest.raises(RepoError, match=re.escape("ses objets sont ceux de CERVEAU (ADR-047)")):
        reader.open([listed("x", elsewhere)], "x")


def test_borrowed_objects_are_refused(reader: RepoReader, repo: Path, tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", "--shared", str(repo), str(clone))
    with pytest.raises(RepoError, match="alternates"):
        reader.open([listed("x", clone)], "x")


# --- reading objects --------------------------------------------------------------------------


def test_a_revision_resolves_to_its_commit(reader: RepoReader, repo: Path) -> None:
    second = commit(repo, {"b.txt": "b\n"}, "second")
    opened = reader.open([listed("p", repo)], "p")
    assert reader.commit(opened, "HEAD") == second
    assert reader.commit(opened, "main") == second
    assert reader.commit(opened, "HEAD~1") == git(repo, "rev-parse", "HEAD~1").strip()


@pytest.mark.parametrize("rev", ["absente", "HEAD~9"])
def test_an_unknown_revision_is_an_error(reader: RepoReader, repo: Path, rev: str) -> None:
    opened = reader.open([listed("p", repo)], "p")
    with pytest.raises(RepoError, match=f"révision « {re.escape(rev)} » introuvable"):
        reader.commit(opened, rev)


def test_a_tag_naming_a_blob_is_not_a_commit(reader: RepoReader, repo: Path) -> None:
    git(repo, "tag", "fichier", blob(repo, b"x\n"))
    opened = reader.open([listed("p", repo)], "p")
    with pytest.raises(RepoError, match="introuvable"):
        reader.commit(opened, "fichier")


def test_an_unexpected_reply_is_refused(repo: Path) -> None:
    fake = fake_reader(GitOutput(0, b"pas-un-commit\n", "", False))
    with pytest.raises(RepoError, match="réponse de git inattendue"):
        fake.commit(Repository("p", repo, None, False, None), "HEAD")


def test_a_tree_lists_its_entries_with_their_size(reader: RepoReader, repo: Path) -> None:
    opened = reader.open([listed("p", repo)], "p")
    entries = {item.path: item for item in reader.tree(opened, "HEAD")}
    assert set(entries) == {".env.example", "README.md", "src"}
    assert (entries["README.md"].kind, entries["README.md"].size) == ("file", 7)
    assert (entries["src"].kind, entries["src"].size) == ("directory", None)
    (item,) = reader.tree(opened, "HEAD", "src/app.py")
    assert (item.path, item.kind, item.size) == ("src/app.py", "file", 12)
    assert reader.blob(opened, item.sha, 1000) == b"print('ok')\n"


def test_tree_paths_are_literal(reader: RepoReader, repo: Path) -> None:
    sha = blob(repo, b"x\n")
    add_entry(repo, "100644", sha, "[ab].txt", "brackets")
    add_entry(repo, "100644", sha, "a.txt", "other")
    opened = reader.open([listed("p", repo)], "p")
    assert [item.path for item in reader.tree(opened, "HEAD", "[ab].txt")] == ["[ab].txt"]
    assert reader.tree(opened, "HEAD", "?.txt") == []


def test_links_and_submodules_are_entries_never_followed(reader: RepoReader, repo: Path) -> None:
    add_entry(repo, "120000", blob(repo, b"../../etc/passwd"), "lien", "link")
    add_entry(repo, "160000", git(repo, "rev-parse", "HEAD").strip(), "sous", "submodule")
    opened = reader.open([listed("p", repo)], "p")
    kinds = {item.path: item.kind for item in reader.tree(opened, "HEAD")}
    assert (kinds["lien"], kinds["sous"]) == ("symlink", "submodule")


def test_an_unknown_mode_is_other() -> None:
    assert TreeItem("100664", "blob", "a" * 40, 1, "x").kind == "other"


def test_a_sensitive_tree_path_is_refused_before_git(repo: Path) -> None:
    fake = fake_reader(GitOutput(0, b"", "", False))
    with pytest.raises(RepoError, match="fichier sensible"):
        fake.tree(Repository("p", repo, None, False, None), "HEAD", ".env")
    assert cast(FakeGit, fake.git).calls == []


def test_a_recursive_tree_lists_every_file_with_its_full_path(
    reader: RepoReader, repo: Path
) -> None:
    add_entry(repo, "120000", blob(repo, b"src"), "lien", "link")
    opened = reader.open([listed("p", repo)], "p")
    items = {item.path: item.kind for item in reader.tree(opened, "HEAD", recursive=True)}
    assert items == {
        ".env.example": "file",
        "README.md": "file",
        "src/app.py": "file",
        "lien": "symlink",
    }


def test_blobs_are_read_in_one_call(reader: RepoReader, repo: Path) -> None:
    empty = blob(repo, b"")
    binary = blob(repo, b"\x00\n\xff\nend")
    opened = reader.open([listed("p", repo)], "p")
    readme = reader.tree(opened, "HEAD", "README.md")[0].sha
    contents = reader.blobs(opened, [readme, empty, binary, readme], 100)
    assert contents == {readme: b"Projet\n", empty: b"", binary: b"\x00\n\xff\nend"}


def test_no_blob_asked_needs_no_git() -> None:
    fake = fake_reader(GitOutput(0, b"", "", False))
    assert fake.blobs(Repository("p", Path("/x"), None, False, None), [], 10) == {}
    assert cast(FakeGit, fake.git).calls == []


def test_blobs_are_asked_by_hash_on_stdin() -> None:
    sha = "a" * 40
    fake = fake_reader(GitOutput(0, f"{sha} blob 2\nok\n".encode(), "", False))
    assert fake.blobs(Repository("p", Path("/x"), None, False, None), [sha], 10) == {sha: b"ok"}
    fake_git = cast(FakeGit, fake.git)
    assert fake_git.calls == [["cat-file", "--batch"]]
    assert fake_git.stdin == [f"{sha}\n".encode()]


@pytest.mark.parametrize("sha", ["HEAD", "a" * 39, "--batch-all-objects", "a" * 40 + "\n"])
def test_a_blob_name_that_is_not_a_hash_is_refused(sha: str) -> None:
    fake = fake_reader(GitOutput(0, b"", "", False))
    with pytest.raises(RepoError, match="empreinte d'objet refusée"):
        fake.blobs(Repository("p", Path("/x"), None, False, None), [sha], 10)
    assert cast(FakeGit, fake.git).calls == []


A = "a" * 40
B = "b" * 40


@pytest.mark.parametrize(
    "reply",
    [
        f"{A} missing\n",
        f"{A} tree 2\nok\n",
        f"{B} blob 2\nok\n",
        f"{A} blob x\nok\n",
        f"{A} blob 2\nok!",
        f"{A} blob 9\nok\n",
        f"{A} blob 2",
        "",
    ],
)
def test_an_unexpected_batch_reply_is_refused(reply: str) -> None:
    fake = fake_reader(GitOutput(0, reply.encode(), "", False))
    with pytest.raises(RepoError, match="réponse de git inattendue"):
        fake.blobs(Repository("p", Path("/x"), None, False, None), [A], 100)


def test_blobs_past_their_limit_are_refused(reader: RepoReader, repo: Path) -> None:
    opened = reader.open([listed("p", repo)], "p")
    big = blob(repo, b"x" * 5_000)
    with pytest.raises(RepoError, match="sortie de plus de"):
        reader.blobs(opened, [big], 1_000)


def test_a_blob_past_its_limit_is_refused(reader: RepoReader, repo: Path) -> None:
    opened = reader.open([listed("p", repo)], "p")
    (item,) = reader.tree(opened, "HEAD", "README.md")
    with pytest.raises(RepoError, match="plus de 3 octets"):
        reader.blob(opened, item.sha, 3)


def test_a_cut_output_is_returned_by_read_and_refused_by_strict_calls(repo: Path) -> None:
    fake = fake_reader(GitOutput(1, b"partiel", "", True))
    assert fake.read(repo, ["log"], 7) == (b"partiel", True)
    with pytest.raises(RepoError, match="sortie de plus de"):
        fake.tree(Repository("p", repo, None, False, None), "HEAD")


def test_a_git_failure_becomes_a_repo_error(repo: Path) -> None:
    with pytest.raises(RepoError, match="délai"):
        fake_reader(error="git : délai de 10 s dépassé").read(repo, ["log"], 10)
    with pytest.raises(RepoError, match="git log a échoué"):
        fake_reader(GitOutput(128, b"", "fatal", False)).read(repo, ["log"], 10)
