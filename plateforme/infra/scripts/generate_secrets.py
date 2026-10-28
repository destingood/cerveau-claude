"""Create infra/.env with fresh random secrets for the local stack (run by Lucas, once).

Every empty ``KEY=`` line of the template receives a random hexadecimal secret (hex keeps the
values safe inside connection URLs). The output file is created exclusively: an existing file is
never overwritten, and no secret is ever printed (R6).
"""

from __future__ import annotations

import argparse
import contextlib
import os
import secrets
import sys
from collections.abc import Callable
from pathlib import Path

INFRA_DIR = Path(__file__).resolve().parents[1]

# Langfuse requires a 256-bit ENCRYPTION_KEY written as 64 hexadecimal characters.
_SPECIAL: dict[str, Callable[[], str]] = {"ENCRYPTION_KEY": lambda: secrets.token_hex(32)}


def _default_secret() -> str:
    return secrets.token_hex(24)


def render(template: str) -> tuple[str, int]:
    """Return the template with every empty value filled, and the number of secrets generated."""
    lines: list[str] = []
    generated = 0
    for line in template.splitlines():
        key, sep, value = line.partition("=")
        name = key.strip()
        if sep and name and not name.startswith("#") and not value.strip():
            line = f"{name}={_SPECIAL.get(name, _default_secret)()}"
            generated += 1
        lines.append(line)
    return "\n".join(lines) + "\n", generated


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="Génère infra/.env sans afficher les secrets.")
    parser.add_argument("--template", type=Path, default=INFRA_DIR / ".env.example")
    parser.add_argument("--output", type=Path, default=INFRA_DIR / ".env")
    args = parser.parse_args(argv)

    content, generated = render(args.template.read_text(encoding="utf-8"))
    try:
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError:
        print(f"{args.output} existe déjà : rien n'est écrasé.", file=sys.stderr)
        return 1
    with contextlib.suppress(OSError):
        os.chmod(args.output, 0o600)  # Owner-only on Unix; Windows keeps the folder's ACL.
    print(f"{args.output} créé : {generated} secret(s) généré(s), non affiché(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
