"""PreToolUse hook (Edit|Write) for this repository: check a CLAUDE.md before it is written (plan, step 19).

A CLAUDE.md is read by every session that opens the folder. The hook refuses a write that would put in it an absolute
path of one machine (breaks Windows, macOS and Linux alike), a secret-looking value, or an empty section (a heading
directly followed by another heading or the end). Anything else passes. Only files named CLAUDE.md or CLAUDE.local.md
are looked at; every other write passes untouched and silently.

Adapted from the CLAUDE.md checks of muhammadusmangm/claude-code-best-practices (MIT): `tools/lint-claude-md.sh`,
`guides/anti-patterns.md` AP-2 to AP-6. Stdlib only, Python 3.10+.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

NAMES = {"claude.md", "claude.local.md"}
ABSOLUTE = re.compile(r"(?<![\w.~/-])(?:/(?:home|Users|root)/[\w.-]+/|[A-Za-z]:\\\\?(?:Users|Documents and Settings)\\\\?)")
SECRET = re.compile(r"sk-ant-[\w-]{12,}|sk-(?:proj-)?[A-Za-z0-9]{24,}|gh[pousr]_[A-Za-z0-9]{24,}|AKIA[0-9A-Z]{16}"
                    r"|xox[abprs]-[\w-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----")
HEADING = re.compile(r"^(#{1,6})\s+\S")


def problems(text: str) -> list:
    out = []
    lines = text.splitlines()
    in_code = False
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        if ABSOLUTE.search(line):
            out.append(f"ligne {i} : chemin absolu d'une machine ({ABSOLUTE.search(line).group(0)}…) — mettre un chemin "
                       "relatif au dépôt ou `~`")
        if SECRET.search(line):
            out.append(f"ligne {i} : valeur qui ressemble à une clé ou un jeton — jamais dans un CLAUDE.md")
    heads = [(i, HEADING.match(line)) for i, line in enumerate(lines) if HEADING.match(line) and not in_code]
    for k, (i, m) in enumerate(heads):
        nxt = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        body = [x for x in lines[i + 1:nxt] if x.strip()]
        deeper = k + 1 < len(heads) and len(heads[k + 1][1].group(1)) > len(m.group(1))
        if not body and not deeper:
            out.append(f"ligne {i + 1} : section vide « {lines[i].strip()} »")
    return out


def new_text(tool: str, inp: dict) -> str | None:
    """Le texte du fichier après l'écriture, quand on peut le connaître."""
    path = Path(str(inp.get("file_path") or ""))
    if tool == "Write":
        return str(inp.get("content") or "")
    if tool == "Edit":
        try:
            cur = path.read_text(encoding="utf-8")
        except OSError:
            return None
        old, new = str(inp.get("old_string") or ""), str(inp.get("new_string") or "")
        return cur.replace(old, new) if inp.get("replace_all") else cur.replace(old, new, 1)
    return None


def main() -> int:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except ValueError:
        return 0
    inp = data.get("tool_input") if isinstance(data, dict) else None
    if not isinstance(inp, dict) or Path(str(inp.get("file_path") or "")).name.lower() not in NAMES:
        return 0
    text = new_text(str(data.get("tool_name") or ""), inp)
    found = problems(text) if text is not None else []
    if not found:
        return 0
    sys.stderr.write("CLAUDE.md refusé par le contrôle du dépôt :\n- " + "\n- ".join(found[:8]) + "\n")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # un contrôle cassé ne bloque jamais une écriture : il le dit
        sys.stderr.write(f"(contrôle du CLAUDE.md impossible : {type(exc).__name__}: {exc})\n")
        sys.exit(0)
