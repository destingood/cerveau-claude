"""Who owns a protected file (B1): read from the system, never assumed."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from core.execution.ownership import ADMINISTRATORS_SID, owner_sid, protected_owner


def test_a_missing_path_is_not_protected(tmp_path: Path) -> None:
    assert not protected_owner(tmp_path / "absent")


@pytest.mark.skipif(sys.platform != "win32", reason="SID: Windows only")
def test_a_file_this_account_creates_is_owned_by_it(tmp_path: Path) -> None:
    created = tmp_path / "created.yaml"
    created.write_text("enabled: false\n", encoding="utf-8")
    sid = owner_sid(created)
    assert sid.startswith("S-1-")
    # An elevated session creates files owned by the Administrators group.
    assert protected_owner(created) is (sid == ADMINISTRATORS_SID)


@pytest.mark.skipif(sys.platform != "win32", reason="SID: Windows only")
def test_an_unreadable_owner_raises(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="propriétaire illisible"):
        owner_sid(tmp_path / "absent")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX owner")
def test_a_file_this_account_creates_is_protected_only_for_root(tmp_path: Path) -> None:
    created = tmp_path / "created.yaml"
    created.write_text("enabled: false\n", encoding="utf-8")
    created.chmod(0o644)
    assert protected_owner(created) is (os.geteuid() == 0)  # type: ignore[attr-defined]
    created.chmod(0o664)
    assert not protected_owner(created)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX owner")
def test_the_sid_is_windows_only(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="Windows seulement"):
        owner_sid(tmp_path)


def test_a_link_is_never_protected(tmp_path: Path) -> None:
    target = tmp_path / "target.yaml"
    target.write_text("enabled: false\n", encoding="utf-8")
    link = tmp_path / "link.yaml"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symbolic links need a privilege on this system")
    assert not protected_owner(link)
