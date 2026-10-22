"""Code and git text shown to the planner (R5, R6).

Unlike ``core.net.text.clean_text``, code keeps its lines and its invisible characters are shown,
not dropped: a bidirectional override ("Trojan Source") or a zero-width character appears as its
code point, so the model reviews the text the interpreter would run. Private key blocks and
secret-looking strings are masked; the count of masks is returned so the answer can say so.
"""

from __future__ import annotations

import re
import unicodedata

from core.guardrails.secrets import MASK, mask_secrets

# mask_secrets does not cover a key block: its body is base64 split into short lines.
PEM_BLOCK = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)
_SHOWN = frozenset({"Cf", "Zl", "Zp"})
_KEPT = frozenset({"\n", "\t"})


def _shown(char: str) -> bool:
    category = unicodedata.category(char)
    return category in _SHOWN or (category == "Cc" and char not in _KEPT)


def visible(text: str) -> str:
    """Invisible format, separator and control characters (but newline and tab) as ⟨U+XXXX⟩."""
    return "".join(f"⟨U+{ord(c):04X}⟩" if _shown(c) else c for c in text)


def _mask_lines(match: re.Match[str]) -> str:
    # One mask per line, so line numbers stay right and a slice never starts inside a key.
    return "\n".join([MASK] * (match.group().count("\n") + 1))


def code_text(raw: str) -> tuple[str, int]:
    """Lines of code or of a patch: CRLF made LF, key blocks and secrets masked line for line,
    invisible characters shown; and the number of masks."""
    text, keys = PEM_BLOCK.subn(_mask_lines, raw.replace("\r\n", "\n"))
    text, secrets = mask_secrets(text)
    return visible(text), keys + secrets
