"""Patch of the code agent's changes (ADR-054): scan without following links, comparison with the
commit's blobs, and a round trip through ``git apply`` in a throwaway repository."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from core.code import patch as patch_module
from core.code.patch import (
    NO_NEWLINE,
    BaseFile,
    Patch,
    PatchError,
    _new_path_ok,
    compute_patch,
    file_diff,
    is_risky,
    scan,
    sets_checks,
)
from core.guardrails.secrets import MASK
from tests.code_support import git, make_repo

TOKEN = "ghp_" + "K9j8H7g6F5d4S3a2P1o0" * 2
LIMITS: dict[str, int] = {
    "max_entries": 1_000,
    "max_file_bytes": 10_000,
    "max_read_bytes": 50_000,
    "max_patch_bytes": 50_000,
}


def write(root: Path, files: Mapping[str, str | bytes]) -> Path:
    for name, content in files.items():
        target = root.joinpath(*name.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return root


def base_of(files: Mapping[str, str | bytes], **modes: str) -> dict[str, BaseFile]:
    return {
        name: BaseFile(
            modes.get(name, "100644"),
            content.encode("utf-8") if isinstance(content, str) else content,
        )
        for name, content in files.items()
    }


def compare(
    tmp_path: Path,
    before: Mapping[str, str | bytes],
    after: Mapping[str, str | bytes],
    reserved: tuple[str, ...] = (),
    **limits: int,
) -> Patch:
    copy = write(tmp_path / "copie", after)
    copy.mkdir(exist_ok=True)
    return compute_patch(base_of(before), reserved, copy, **{**LIMITS, **limits})


def tree(root: Path) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for folder, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name != ".git"]
        for name in names:
            path = Path(folder, name)
            found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


class FakeEntry:
    """A real entry seen as a link, a junction or a special file (no symlink without rights on
    Windows: WinError 1314)."""

    def __init__(self, entry: os.DirEntry[str], kind: str) -> None:
        self._entry, self._kind = entry, kind
        self.name = entry.name

    def is_symlink(self) -> bool:
        return self._kind == "lien"

    def is_junction(self) -> bool:
        return self._kind == "jonction"

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        assert not follow_symlinks
        return False

    def is_file(self, *, follow_symlinks: bool = True) -> bool:
        assert not follow_symlinks
        return False

    def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
        raise AssertionError("une entrée spéciale n'est jamais lue")


@contextmanager
def special(monkeypatch: pytest.MonkeyPatch, root: Path, **kinds: str) -> Iterator[None]:
    """``os.scandir`` of the module sees the named entries under ``root`` as ``kinds`` say."""
    real = os.scandir
    top = str(root)

    @contextmanager
    def fake(path: Any) -> Iterator[list[Any]]:
        with real(path) as entries:
            listed = list(entries)
        if not str(path).startswith(top):
            yield listed
            return
        yield [
            FakeEntry(entry, kinds[entry.name]) if entry.name in kinds else entry
            for entry in listed
        ]

    with monkeypatch.context() as patched:
        patched.setattr(patch_module.os, "scandir", fake)
        yield


# --- risky paths --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "risky"),
    [
        (".github/workflows/ci.yml", True),
        ("src/.Claude/settings.json", True),
        ("Makefile", True),
        ("tests/conftest.py", True),
        ("PyProject.toml", True),
        ("site/evil.pth", True),
        (".coveragerc", True),
        ("ruff.toml", True),
        ("pkg/.ruff.toml", True),
        ("uv.lock", True),
        ("requirements.txt", True),
        ("Requirements-Dev.txt", True),
        ("src/main.py", False),
        (".github", False),
        ("docs/makefile.md", False),
        ("requirements.md", False),
        ("docs/requirements", False),
    ],
)
def test_paths_that_run_code_on_lucass_machine_are_flagged(path: str, risky: bool) -> None:
    assert is_risky(path) is risky


@pytest.mark.parametrize(
    ("path", "sets"),
    [
        ("tests/conftest.py", True),
        ("PyProject.toml", True),
        ("pkg/.ruff.toml", True),
        (".coveragerc", True),
        ("setup.cfg", True),
        ("site/evil.pth", True),
        ("Makefile", False),
        (".github/workflows/ci.yml", False),
        ("src/conftest.py.bak", False),
        ("src/main.py", False),
    ],
)
def test_files_that_set_the_checks_are_known(path: str, sets: bool) -> None:
    # Changed by the agent, the checks of the changed copy prove nothing (ADR-054).
    assert sets_checks(path) is sets
    assert not sets or is_risky(path)


# --- the scan -----------------------------------------------------------------------------------


def test_the_scan_lists_regular_files_and_skips_caches(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "a.py": "abc",
            "pkg/b.py": "",
            "pkg/__pycache__/b.pyc": b"\0",
            ".git/config": "x",
            ".ruff_cache/x": "x",
        },
    )
    files, others = scan(tmp_path, 100)
    assert files == {"a.py": 3, "pkg/b.py": 0}
    assert others == []


def test_links_junctions_and_special_files_are_never_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path, {"lien/dedans.py": "x", "jonction/dedans.py": "x", "fifo": "", "a.py": ""})
    with special(monkeypatch, tmp_path, lien="lien", jonction="jonction", fifo="fifo"):
        files, others = scan(tmp_path, 100)
    assert files == {"a.py": 0}
    assert sorted(others) == ["fifo", "jonction", "lien"]


def test_the_scan_is_bounded(tmp_path: Path) -> None:
    write(tmp_path, {"a": "", "b": "", "c/d": ""})
    assert len(scan(tmp_path, 4)[0]) == 3
    with pytest.raises(PatchError, match="plus de 3 entrées"):
        scan(tmp_path, 3)


# --- one file's diff ----------------------------------------------------------------------------


def test_a_file_diff_has_gits_format() -> None:
    text, added, removed = file_diff("a.py", "modifie", "un\ndeux\n", "un\ntrois\nquatre", "100755")
    assert text == (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,3 @@\n un\n-deux\n"
        "+trois\n+quatre\n" + NO_NEWLINE
    )
    assert (added, removed) == (2, 1)


def test_an_added_and_a_deleted_file_have_their_mode() -> None:
    added = file_diff("n.py", "ajoute", "", "x\n", "100644")[0]
    assert added.startswith("diff --git a/n.py b/n.py\nnew file mode 100644\n--- /dev/null\n")
    deleted = file_diff("run.sh", "supprime", "x", "", "100755")[0]
    assert deleted.startswith("diff --git a/run.sh b/run.sh\ndeleted file mode 100755\n--- a/")
    assert "+++ /dev/null\n" in deleted and deleted.endswith("-x\n" + NO_NEWLINE)


def test_a_carriage_return_is_part_of_its_line() -> None:
    text, added, removed = file_diff("w.txt", "modifie", "a\r\nb\r\n", "a\r\nc\rd\r\n", "100644")
    assert "-b\r\n+c\rd\r\n" in text and (added, removed) == (1, 1)


# --- the comparison -----------------------------------------------------------------------------


def test_unchanged_files_give_an_empty_patch(tmp_path: Path) -> None:
    files = {"a.py": "x = 1\n", "vide.txt": "", "pkg/__pycache__/m.pyc": b"\0", ".git": "gitdir"}
    patch = compare(tmp_path, files, {k: v for k, v in files.items() if "pycache" not in k})
    assert patch == Patch("", (), (), (), (), ())
    assert (patch.masked, patch.risky) == (0, ())


def test_a_change_of_the_same_size_is_seen(tmp_path: Path) -> None:
    patch = compare(tmp_path, {"a.py": "x = 1\n"}, {"a.py": "x = 2\n"})
    assert [(c.path, c.change, c.added, c.removed) for c in patch.changes] == [
        ("a.py", "modifie", 1, 1)
    ]


def test_added_modified_and_deleted_files(tmp_path: Path) -> None:
    patch = compare(
        tmp_path,
        {"a.py": "un\n", "b.py": "deux\n", "Makefile": "all:\n"},
        {"a.py": "un\nplus\n", "c/n.py": "neuf\n", "Makefile": "all: x\n"},
    )
    assert [(c.path, c.change, c.risky) for c in patch.changes] == [
        ("Makefile", "modifie", True),
        ("a.py", "modifie", False),
        ("b.py", "supprime", False),
        ("c/n.py", "ajoute", False),
    ]
    assert patch.risky == ("Makefile",)


def test_a_new_sensitive_file_is_named_never_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = write(tmp_path / "copie", {".env": "VALEUR", "cles/id_rsa": "x", "ok.py": ""})
    read: list[Path] = []
    original = Path.read_bytes

    def spy(self: Path) -> bytes:
        read.append(self)
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", spy)
    patch = compute_patch({}, (), copy, **LIMITS)
    assert patch.sensitive == (".env", "cles/id_rsa")
    assert read == [copy / "ok.py"]
    assert "VALEUR" not in patch.text


@pytest.mark.parametrize(
    "name",
    [
        ".GIT",  # check_path: the .git folder, case aside
        "zéro.py",  # not plain ASCII
        "a b.py",  # a space: git would quote the path
        "invisible​.py",  # check_path: an invisible character
    ],
)
def test_a_new_path_that_is_not_plain_is_left_out(name: str, tmp_path: Path) -> None:
    patch = compare(tmp_path, {}, {name: "x\n"})
    assert (patch.ignored, patch.changes) == ((name,), ())


def test_a_new_path_must_be_portable_and_free() -> None:
    assert _new_path_ok("src/ok.py", set())
    assert not _new_path_ok("src/aux.txt", set())
    assert not _new_path_ok("src/fin.", set())
    assert not _new_path_ok("src/a:b", set())
    assert not _new_path_ok("Docs/Lien", {"docs/lien"})


def test_a_new_file_where_the_copy_left_an_entry_out_is_ignored(tmp_path: Path) -> None:
    patch = compare(tmp_path, {}, {"Docs/LIEN": "x", "src/autre": "y"}, reserved=("docs/lien",))
    assert patch.ignored == ("Docs/LIEN",)
    assert [c.path for c in patch.changes] == ["src/autre"]


def test_an_existing_path_that_is_not_plain_is_left_out(tmp_path: Path) -> None:
    patch = compare(tmp_path, {"é.md": "a\n", "à.md": "b\n"}, {"é.md": "c\n"})
    assert patch.ignored == ("à.md", "é.md")
    assert patch.changes == ()


def test_files_under_a_link_are_not_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = write(tmp_path / "copie", {"lib/a.py": "x\n", "lib/b.py": "y\n", "f": "z"})
    base = base_of({"lib/a.py": "x\n", "lib/b.py": "y\n", "f": "z", "g": "w"})
    with special(monkeypatch, copy, lib="lien", f="fifo"):
        patch = compute_patch(base, (), copy, **LIMITS)
    assert patch.ignored == ("f", "lib")
    assert [(c.path, c.change) for c in patch.changes] == [("g", "supprime")]


def test_binary_files_are_listed(tmp_path: Path) -> None:
    patch = compare(
        tmp_path,
        {"ancien.bin": b"\xff\xfe", "nul.txt": "a\n", "ok.txt": "a\n"},
        {"ancien.bin": b"\xff", "nul.txt": b"a\0", "neuf.bin": b"\x80", "ok.txt": "b\n"},
    )
    assert patch.binary == ("ancien.bin", "neuf.bin", "nul.txt")
    assert [c.path for c in patch.changes] == ["ok.txt"]


def test_large_files_are_listed_and_not_read(tmp_path: Path) -> None:
    after = {"a.txt": "a" * 60 + "\n", "b.txt": "b" * 30 + "\n", "c.txt": "c\n", "d.txt": "d\n"}
    patch = compare(tmp_path, {"c.txt": "x\n"}, after, max_file_bytes=50, max_read_bytes=34)
    # a: alone past the limit; b read (31 bytes); c and d: 2 bytes each, d past 34 in all.
    assert patch.too_big == ("a.txt", "d.txt")
    assert [c.path for c in patch.changes] == ["b.txt", "c.txt"]


def test_the_patch_is_bounded(tmp_path: Path) -> None:
    after = {"a.txt": "a\n", "b.txt": "b\n", "c.txt": "c\n"}
    one = len(compare(tmp_path / "1", {}, {"a.txt": "a\n"}).text.encode("utf-8"))
    patch = compare(tmp_path / "2", {}, after, max_patch_bytes=2 * one)
    assert patch.too_big == ("c.txt",)
    assert len(patch.text.encode("utf-8")) == 2 * one


def test_secrets_are_masked(tmp_path: Path) -> None:
    patch = compare(tmp_path, {"a.py": "x\n"}, {"a.py": f"cle = '{TOKEN}'\n", "b.py": TOKEN})
    assert TOKEN not in patch.text and patch.text.count(MASK) == 2
    assert [c.masked for c in patch.changes] == [1, 1] and patch.masked == 2


# --- round trip through git apply ---------------------------------------------------------------


def applied(
    tmp_path: Path,
    before: Mapping[str, str | bytes],
    after: Mapping[str, str | bytes],
    executable: tuple[str, ...] = (),
) -> Patch:
    repo = make_repo(tmp_path / "depot", before)
    for name in executable:
        git(repo, "update-index", "--chmod=+x", "--", name)
        git(repo, "commit", "-q", "-m", "exécutable")
    copy = write(tmp_path / "copie", after)
    base = base_of(before, **dict.fromkeys(executable, "100755"))
    patch = compute_patch(base, (), copy, **LIMITS)
    diff = tmp_path / "agent.patch"
    diff.write_bytes(patch.text.encode("utf-8"))
    git(repo, "apply", "--check", str(diff))
    git(repo, "apply", str(diff))
    assert tree(repo) == tree(copy)
    return patch


def test_the_patch_applies_with_git(tmp_path: Path) -> None:
    patch = applied(
        tmp_path,
        {
            "a.py": "un\ndeux\ntrois\nquatre\ncinq\nsix\nsept\nhuit\n",
            "sans_fin.txt": "a\nb",
            "crlf.txt": "a\r\nb\r\n",
            "vide.txt": "",
            "run.sh": "#!/bin/sh\n",
            "garde.py": "x\n",
        },
        {
            "a.py": "un\nDEUX\ntrois\nquatre\ncinq\nsix\nsept\nHUIT\n",
            "sans_fin.txt": "a\nc",
            "crlf.txt": "a\r\nc\r\n",
            "nouveau/vide.txt": "",
            "nouveau/sans_fin.py": "fin",
            "garde.py": "x\n",
        },
        executable=("run.sh",),
    )
    assert {c.path: c.change for c in patch.changes} == {
        "a.py": "modifie",
        "crlf.txt": "modifie",
        "nouveau/sans_fin.py": "ajoute",
        "nouveau/vide.txt": "ajoute",
        "run.sh": "supprime",
        "sans_fin.txt": "modifie",
        "vide.txt": "supprime",
    }
    assert "deleted file mode 100755\n" in patch.text


def test_a_file_that_loses_its_last_newline_applies(tmp_path: Path) -> None:
    applied(tmp_path, {"a.txt": "a\nb\n", "b.txt": "c"}, {"a.txt": "a\nb", "b.txt": "c\n"})
