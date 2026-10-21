"""Who owns a protected file and who may write it (B1): read from the system, never assumed."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from core.execution import ownership
from core.execution.ownership import (
    ACCESS_ALLOWED,
    ACCESS_DENIED,
    ADMINISTRATORS_SID,
    INHERIT_ONLY,
    SYSTEM_SID,
    Ace,
    Security,
    loose_aces,
    owner_sid,
    protected,
    security,
)

USER = "S-1-5-21-1-2-3-1001"
EVERYONE = "S-1-1-0"
INHERITED = 0x10
FULL = 0x1F01FF
READ = 0x120089  # what protect-live.ps1 grants the account on config/live.yaml
READ_EXECUTE = 0x1200A9  # and on governance/approvals/
WRITE_BITS = [0x2, 0x4, 0x10, 0x40, 0x100, 0x10000, 0x40000, 0x80000, 0x10000000, 0x40000000]


@pytest.mark.parametrize(
    ("aces", "loose"),
    [
        (None, ["DACL nulle : tous les droits à tous"]),
        ((), []),
        (
            (
                Ace(ACCESS_ALLOWED, INHERITED, FULL, ADMINISTRATORS_SID),
                Ace(ACCESS_ALLOWED, INHERITED, FULL, SYSTEM_SID),
                Ace(ACCESS_ALLOWED, 0, READ, USER),
            ),
            [],
        ),
        ((Ace(ACCESS_ALLOWED, 0x3, READ_EXECUTE, USER),), []),
        ((Ace(ACCESS_ALLOWED, INHERITED, FULL, USER),), [f"écriture accordée à {USER}"]),
        ((Ace(ACCESS_ALLOWED, INHERIT_ONLY | 0x3, 0x10000000, USER),), []),
        ((Ace(ACCESS_DENIED, 0, FULL, USER),), []),
        ((Ace(ACCESS_ALLOWED, 0, 0x40000000, EVERYONE),), [f"écriture accordée à {EVERYONE}"]),
        ((Ace(5, 0, READ, ""),), ["ACE de type 5 non vérifiable"]),
    ],
    ids=[
        "null-dacl",
        "empty-dacl",
        "as-protect-live-leaves-it",
        "read-execute",
        "inherited-full-control",
        "inherit-only",
        "denial",
        "generic-write-to-everyone",
        "object-ace",
    ],
)
def test_who_may_write_besides_the_administrators_and_system(
    aces: tuple[Ace, ...] | None, loose: list[str]
) -> None:
    assert loose_aces(aces) == loose


@pytest.mark.parametrize("bit", WRITE_BITS, ids=hex)
def test_every_write_right_is_loose(bit: int) -> None:
    assert loose_aces([Ace(ACCESS_ALLOWED, 0, bit, USER)]) == [f"écriture accordée à {USER}"]
    assert loose_aces([Ace(ACCESS_ALLOWED, 0, bit, SYSTEM_SID)]) == []


def test_a_missing_path_is_not_protected(tmp_path: Path) -> None:
    assert not protected(tmp_path / "absent")


@pytest.mark.skipif(sys.platform != "win32", reason="SID: Windows only")
def test_a_file_this_account_creates_is_not_protected(tmp_path: Path) -> None:
    created = tmp_path / "created.yaml"
    created.write_text("enabled: false\n", encoding="utf-8")
    found = security(created)
    assert found.owner.startswith("S-1-")
    assert found.owner == owner_sid(created)
    assert found.aces  # inherited from the folder of the account's profile
    # Whoever owns it, the account that wrote it may still write it.
    assert loose_aces(found.aces)
    assert not protected(created)


@pytest.mark.skipif(sys.platform != "win32", reason="SID: Windows only")
@pytest.mark.parametrize(
    ("found", "expected"),
    [
        (Security(ADMINISTRATORS_SID, (Ace(ACCESS_ALLOWED, 0, FULL, SYSTEM_SID),)), True),
        (Security(ADMINISTRATORS_SID, (Ace(ACCESS_ALLOWED, 0, FULL, USER),)), False),
        (Security(ADMINISTRATORS_SID, None), False),
        (Security(USER, (Ace(ACCESS_ALLOWED, 0, READ, USER),)), False),
    ],
    ids=["administrators-only", "user-may-write", "null-dacl", "user-owner"],
)
def test_protection_needs_the_owner_and_the_dacl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, found: Security, expected: bool
) -> None:
    created = tmp_path / "created.yaml"
    created.write_text("enabled: false\n", encoding="utf-8")
    monkeypatch.setattr(ownership, "security", lambda _path: found)
    assert protected(created) is expected


@pytest.mark.skipif(sys.platform != "win32", reason="SID: Windows only")
def test_an_unreadable_security_raises(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="sécurité illisible"):
        security(tmp_path / "absent")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX owner")
def test_a_file_this_account_creates_is_protected_only_for_root(tmp_path: Path) -> None:
    created = tmp_path / "created.yaml"
    created.write_text("enabled: false\n", encoding="utf-8")
    created.chmod(0o644)
    assert protected(created) is (os.geteuid() == 0)  # type: ignore[attr-defined]
    created.chmod(0o664)
    assert not protected(created)


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
    assert not protected(link)
