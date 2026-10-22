"""Code text shown to the planner: invisible characters shown, keys and secrets masked (R5, R6)."""

from __future__ import annotations

import pytest

from core.code.text import code_text, visible
from core.guardrails.secrets import MASK

TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0" * 2


def armour(label: str, *lines: str, end: bool = True) -> str:
    """A key block built from parts, so that no key-looking text sits in the repository."""
    dashes = "-" * 5
    block = [f"{dashes}BEGIN {label}{dashes}", *lines]
    if end:
        block.append(f"{dashes}END {label}{dashes}")
    return "\n".join(block)


PRIVATE = "PRIVATE" + " KEY"


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("if access != 'user\u202e \u2066// admin\u2069':", "⟨U+202E⟩"),
        ("x = 1\u200b", "x = 1⟨U+200B⟩"),
        ("a\u2028b", "a⟨U+2028⟩b"),
        ("bell\x07", "bell⟨U+0007⟩"),
        ("cr\rlf", "cr⟨U+000D⟩lf"),
    ],
)
def test_invisible_characters_are_shown(raw: str, shown: str) -> None:
    assert shown in visible(raw)


def test_newlines_and_tabs_are_kept() -> None:
    assert visible("def f():\n\treturn 1\n") == "def f():\n\treturn 1\n"


def test_crlf_becomes_lf() -> None:
    assert code_text("a\r\nb\r\n") == ("a\nb\n", 0)


def test_a_key_block_is_masked_line_for_line() -> None:
    key = armour(f"RSA {PRIVATE}", "MIIEow", "AAAA")
    text, masked = code_text(f"avant\n{key}\naprès\n")
    assert text == "avant\n" + "\n".join([MASK] * 4) + "\naprès\n"
    assert masked == 1
    assert "MIIEow" not in text


def test_an_unterminated_key_block_is_masked_to_the_end() -> None:
    key = armour(f"OPENSSH {PRIVATE}", "b3BlbnNzaC1rZXk", "zz", end=False)
    text, masked = code_text(f"x\n{key}")
    assert text == "x\n" + "\n".join([MASK] * 3)
    assert masked == 1


def test_secret_looking_strings_are_masked_and_counted() -> None:
    text, masked = code_text(f"TOKEN = '{TOKEN}'\nOTHER = '{TOKEN}'\n")
    assert TOKEN not in text
    assert text == f"TOKEN = '{MASK}'\nOTHER = '{MASK}'\n"
    assert masked == 2


def test_a_public_key_is_not_masked() -> None:
    public = armour("PUBLIC KEY", "MFkw")
    assert code_text(public) == (public, 0)
