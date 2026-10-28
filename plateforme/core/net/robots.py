"""robots.txt as specified by RFC 9309 (R15).

``urllib.robotparser`` is not used: it ignores the ``*`` and ``$`` patterns and applies the first
matching rule, where RFC 9309 applies the longest one. Here the group of our user-agent token is
used if present (all such groups merged), else the ``*`` groups; the longest matching rule wins
and ``allow`` wins a tie. ``/robots.txt`` itself is always allowed.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from urllib.parse import quote

ROBOTS_AGENT = "CERVEAU"

_PERCENT = re.compile(r"%([0-9A-Fa-f]{2})")
_UNRESERVED = frozenset(string.ascii_letters + string.digits + "-._~")
_SAFE = "!#$&'()*+,/:;=?@[]%"


def normalise(path: str) -> str:
    """RFC 9309 §2.2.2: decode percent-encoded unreserved octets, encode non-ASCII ones."""

    def _decode(match: re.Match[str]) -> str:
        char = chr(int(match[1], 16))
        return char if char in _UNRESERVED else f"%{match[1].upper()}"

    return quote(_PERCENT.sub(_decode, path), safe=_SAFE)


@dataclass(frozen=True)
class Rule:
    allow: bool
    pattern: str
    regex: re.Pattern[str]

    @classmethod
    def of(cls, allow: bool, pattern: str) -> Rule:
        norm = normalise(pattern)
        anchored = norm.endswith("$")
        body = norm[:-1] if anchored else norm
        regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
        return cls(allow, norm, re.compile(regex + ("$" if anchored else ""), re.DOTALL))


@dataclass(frozen=True)
class RobotsPolicy:
    rules: tuple[Rule, ...] = ()
    disallow_all: bool = False

    @classmethod
    def allow_everything(cls) -> RobotsPolicy:
        return cls()

    @classmethod
    def deny_everything(cls) -> RobotsPolicy:
        return cls(disallow_all=True)

    def allows(self, path: str) -> bool:
        """``path`` is the URL path with its query, as sent on the request line."""
        target = normalise(path or "/")
        if target == "/robots.txt":
            return True
        if self.disallow_all:
            return False
        best: tuple[int, bool] | None = None
        for rule in self.rules:
            if rule.regex.match(target):
                key = (len(rule.pattern), rule.allow)
                if best is None or key > best:
                    best = key
        return best is None or best[1]


def parse_robots(text: str, agent: str = ROBOTS_AGENT) -> RobotsPolicy:
    groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []
    in_rules = False
    for raw in text.removeprefix(chr(0xFEFF)).splitlines():
        line = raw.split("#", 1)[0].strip()
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if in_rules:
                groups.append((agents, rules))
                agents, rules, in_rules = [], [], False
            agents.append(value.split("/", 1)[0].strip().lower())
        elif key in ("allow", "disallow") and agents:
            in_rules = True
            if value:  # an empty rule matches nothing
                rules.append((key == "allow", value))
    if agents:
        groups.append((agents, rules))
    wanted = agent.lower()
    if not any(wanted in names for names, _ in groups):
        wanted = "*"
    chosen = [rule for names, group in groups if wanted in names for rule in group]
    return RobotsPolicy(tuple(Rule.of(allow, pattern) for allow, pattern in chosen))
