"""Who owns a protected file: the Administrators group on Windows, root elsewhere (B1, ADR-003).

``protect-live.ps1`` hands ``config/live.yaml`` and ``governance/approvals/`` to the
Administrators group; the account that runs CERVEAU and Claude Code then only reads them. The
live adapter checks that ownership at every submission: a file the current account could have
deleted and recreated belongs to that account, and is refused.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

ADMINISTRATORS_SID = "S-1-5-32-544"  # the same group on every Windows, whatever its language
_SE_FILE_OBJECT = 1
_OWNER_SECURITY_INFORMATION = 1


def owner_sid(path: Path) -> str:
    """The string SID of the owner of ``path`` (Windows); raises OSError when it cannot be read."""
    if sys.platform != "win32":
        raise OSError(f"SID de propriétaire : Windows seulement ({sys.platform})")
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info = advapi32.GetNamedSecurityInfoW
    get_info.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_info.restype = wintypes.DWORD
    to_text = advapi32.ConvertSidToStringSidW
    to_text.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    to_text.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    sid = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    status = get_info(
        str(path),
        _SE_FILE_OBJECT,
        _OWNER_SECURITY_INFORMATION,
        ctypes.byref(sid),
        None,
        None,
        None,
        ctypes.byref(descriptor),
    )
    if status != 0:
        raise OSError(status, f"GetNamedSecurityInfoW : propriétaire illisible ({path.name})")
    try:
        text = wintypes.LPWSTR()
        if not to_text(sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return str(text.value)
        finally:
            local_free(ctypes.cast(text, ctypes.c_void_p))
    finally:
        local_free(descriptor)


def protected_owner(path: Path) -> bool:
    """True when ``path`` exists and belongs to the Administrators group (Windows), or to root
    with no write right for its group or the others (POSIX). Anything unreadable is False."""
    try:
        if sys.platform == "win32":
            if path.is_symlink() or not path.exists():
                return False
            return owner_sid(path) == ADMINISTRATORS_SID
        info = path.lstat()
        return (
            not stat.S_ISLNK(info.st_mode)
            and info.st_uid == 0
            and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        )
    except OSError:
        return False
