"""Secret-looking strings (R6) in text CERVEAU stores outside the audit journal.

The pattern is the one the Claude Code hooks use (``.claude/hooks/_common.py``); a test keeps
the two identical. Masking is a safety net, not a guarantee: a secret has no place in a note.
"""

from __future__ import annotations

import re

_KEY_CHARS = r"[A-Za-z0-9+_=-]"
SECRET_LIKE = re.compile(
    r"sk-ant-[\w-]{8,}|sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}"
    r"|xox[abprs]-[\w-]{10,}"
    # long mixed-case alphanumeric runs (API keys, tokens), but not paths or hex hashes
    rf"|(?={_KEY_CHARS}*[a-z])(?={_KEY_CHARS}*[A-Z])(?={_KEY_CHARS}*\d){_KEY_CHARS}{{32,}}"
)
MASK = "[MASQUÉ]"


def mask_secrets(text: str) -> tuple[str, int]:
    """The text with each secret-looking string replaced by ``MASK``, and how many were."""
    return SECRET_LIKE.subn(MASK, text)
