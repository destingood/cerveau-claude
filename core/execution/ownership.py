"""Whether a protected file is out of reach: its owner and who may write it (B1, ADR-003).

``protect-live.ps1`` hands ``config/live.yaml`` and ``governance/approvals/`` to the
Administrators group and leaves the account that runs CERVEAU and Claude Code a read right
only. The live adapter checks both at every submission: a file the current account could have
deleted and recreated belongs to that account, and an access list that still lets it write
(an inherited ACE, a grant left by hand) is just as loose. Either is refused.
"""

from __future__ import annotations

import stat
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

ADMINISTRATORS_SID = "S-1-5-32-544"  # the same group on every Windows, whatever its language
SYSTEM_SID = "S-1-5-18"
WRITERS = frozenset({ADMINISTRATORS_SID, SYSTEM_SID})  # the only SIDs that may write
ACCESS_ALLOWED = 0
ACCESS_DENIED = 1
INHERIT_ONLY = 0x08  # an ACE passed on to children, without effect on the object itself
# Every right that changes a file, a folder's content, its attributes or its protection:
# write or add a file, append or add a folder, write the extended attributes, delete a child,
# write the attributes, delete, write the DACL, take ownership, generic all, generic write.
WRITE_RIGHTS = (
    0x2 | 0x4 | 0x10 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000 | 0x10000000 | 0x40000000
)
_SE_FILE_OBJECT = 1
_OWNER_SECURITY_INFORMATION = 0x1
_DACL_SECURITY_INFORMATION = 0x4
_SID_OFFSET = 8  # header (4 bytes) and mask (4 bytes) of an allowed or denied ACE


class Ace(NamedTuple):
    """One entry of an access list: its type, flags, rights mask and SID (empty if unread)."""

    type: int
    flags: int
    mask: int
    sid: str


class Security(NamedTuple):
    """The owner's SID and the access list of a file; ``aces`` is None for a null DACL."""

    owner: str
    aces: tuple[Ace, ...] | None


def loose_aces(aces: Sequence[Ace] | None) -> list[str]:
    """What lets someone else than the Administrators group or SYSTEM change a file, in words.

    A null DACL grants everything to everyone. An inherit-only ACE does not apply to the object
    and a denial adds no right; any other type of ACE (object, callback) cannot be read here and
    counts as loose, so the check fails closed.
    """
    if aces is None:
        return ["DACL nulle : tous les droits à tous"]
    loose: list[str] = []
    for ace in aces:
        if ace.flags & INHERIT_ONLY or ace.type == ACCESS_DENIED:
            continue
        if ace.type != ACCESS_ALLOWED:
            loose.append(f"ACE de type {ace.type} non vérifiable")
        elif ace.mask & WRITE_RIGHTS and ace.sid not in WRITERS:
            loose.append(f"écriture accordée à {ace.sid}")
    return loose


def security(path: Path) -> Security:
    """The owner and the DACL of ``path`` (Windows); raises OSError when they cannot be read."""
    if sys.platform != "win32":
        raise OSError(f"SID de propriétaire : Windows seulement ({sys.platform})")
    import ctypes
    from ctypes import wintypes

    class AclHeader(ctypes.Structure):
        _fields_ = (
            ("revision", ctypes.c_ubyte),
            ("sbz1", ctypes.c_ubyte),
            ("size", wintypes.WORD),
            ("count", wintypes.WORD),
            ("sbz2", wintypes.WORD),
        )

    class AceStart(ctypes.Structure):
        _fields_ = (
            ("type", ctypes.c_ubyte),
            ("flags", ctypes.c_ubyte),
            ("size", wintypes.WORD),
            ("mask", wintypes.DWORD),
        )

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info = advapi32.GetNamedSecurityInfoW
    get_info.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_info.restype = wintypes.DWORD
    get_ace = advapi32.GetAce
    get_ace.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    get_ace.restype = wintypes.BOOL
    to_text = advapi32.ConvertSidToStringSidW
    to_text.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    to_text.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    def sid_text(sid: int | None) -> str:
        text = wintypes.LPWSTR()
        if not to_text(sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return str(text.value)
        finally:
            local_free(ctypes.cast(text, ctypes.c_void_p))

    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    status = get_info(
        str(path),
        _SE_FILE_OBJECT,
        _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if status != 0:
        raise OSError(status, f"GetNamedSecurityInfoW : sécurité illisible ({path.name})")
    try:
        if not dacl.value:
            return Security(sid_text(owner.value), None)
        header = AclHeader.from_address(dacl.value)
        aces: list[Ace] = []
        for index in range(header.count):
            entry = ctypes.c_void_p()
            if not get_ace(dacl, index, ctypes.byref(entry)) or not entry.value:
                raise ctypes.WinError(ctypes.get_last_error())
            ace = AceStart.from_address(entry.value)
            readable = ace.type in (ACCESS_ALLOWED, ACCESS_DENIED)
            sid = sid_text(entry.value + _SID_OFFSET) if readable else ""
            aces.append(Ace(ace.type, ace.flags, ace.mask, sid))
        return Security(sid_text(owner.value), tuple(aces))
    finally:
        local_free(descriptor)


def owner_sid(path: Path) -> str:
    """The string SID of the owner of ``path`` (Windows); raises OSError when it cannot be read."""
    return security(path).owner


def protected(path: Path) -> bool:
    """True when ``path`` exists, belongs to the Administrators group and lets no one else but
    that group and SYSTEM write it (Windows), or belongs to root with no write right for its
    group or the others (POSIX). Anything unreadable is False."""
    try:
        if sys.platform == "win32":
            if path.is_symlink() or not path.exists():
                return False
            found = security(path)
            return found.owner == ADMINISTRATORS_SID and not loose_aces(found.aces)
        info = path.lstat()
        return (
            not stat.S_ISLNK(info.st_mode)
            and info.st_uid == 0
            and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        )
    except OSError:
        return False
