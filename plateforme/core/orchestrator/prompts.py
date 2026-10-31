"""Prompt templates of the graph: annex D for the planner, one template per other node.

Each file may start with an HTML comment for maintainers; it is stripped before use. Placeholders
are ``{{name}}`` and substitution is strict and single-pass: the values given must be exactly the
placeholders of the template, and a value is never substituted again (a page that contains
``{{now}}`` stays as it is). The version written to the audit journal (R11) names the annex D
version and hashes every template and the role of every domain pack, so that any change is
visible; the system prompt carries the role of the pack the request was routed to.

The learned sections of a pack (``learned/<pack>/``, ADR-065) follow its role under a title that
says they are unverified lessons; they are hashed into the version too, so a promotion or a
rollback shows in the journal. A pack without learned sections keeps the version it had.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from core.learning.layer import LEARNED_DIR, SECTION_TITLES, SECTIONS, LockedCoreError, read_section
from core.orchestrator.packs import PACKS_DIR, pack_ids
from core.orchestrator.state import RequestContext

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
TEMPLATES = (
    "system",
    "input_check",
    "route",
    "reader",
    "reader_task",
    "verifier",
    "planner_task",
)

_HEADER = re.compile(r"\A\s*<!--.*?-->[ \t]*\n?", re.DOTALL)
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_SYSTEM_VERSION = re.compile(r"\bversion (\d+\.\d+)\b")


class PromptError(Exception):
    """A template is missing, malformed or rendered with the wrong values."""


@dataclass(frozen=True)
class Template:
    name: str
    text: str  # without the header comment

    @property
    def placeholders(self) -> frozenset[str]:
        return frozenset(_PLACEHOLDER.findall(self.text))

    def render(self, **values: str) -> str:
        expected, given = self.placeholders, frozenset(values)
        if given != expected:
            missing = ", ".join(sorted(expected - given)) or "aucune"
            extra = ", ".join(sorted(given - expected)) or "aucune"
            raise PromptError(
                f"gabarit « {self.name} » : variables manquantes {missing}, inattendues {extra}"
            )
        return _PLACEHOLDER.sub(lambda match: values[match.group(1)], self.text)


def strip_header(text: str) -> str:
    return _HEADER.sub("", text, count=1)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptError(f"gabarit illisible : {path.name} ({type(exc).__name__})") from None


@dataclass(frozen=True)
class PromptSet:
    templates: Mapping[str, Template]
    roles: Mapping[str, str]  # pack → its role, inserted as {{domain_pack_role}}
    version: str  # "system@<annex D version>+sha256:<12 hex>"

    @classmethod
    def load(
        cls,
        packs: Sequence[str] | None = None,  # None: the packs of domain_packs/ (ADR-043)
        *,
        prompts_dir: Path = PROMPTS_DIR,
        packs_dir: Path = PACKS_DIR,
        learned_dir: Path = LEARNED_DIR,
    ) -> PromptSet:
        digest = hashlib.sha256()
        templates: dict[str, Template] = {}
        raw_system = ""
        for name in TEMPLATES:
            raw = _read(prompts_dir / f"{name}.md")
            digest.update(f"{name}\0{raw}\0".encode())
            templates[name] = Template(name, strip_header(raw).strip() + "\n")
            if name == "system":
                raw_system = raw
        roles: dict[str, str] = {}
        for pack in pack_ids(packs_dir) if packs is None else packs:
            raw_role = _read(packs_dir / pack / "prompts" / "role.md")
            digest.update(f"role:{pack}\0{raw_role}\0".encode())
            role = strip_header(raw_role).strip()
            if not role or _PLACEHOLDER.search(role):
                raise PromptError(f"rôle du pack « {pack} » vide ou contenant une variable")
            for section in SECTIONS:
                try:
                    learned = read_section(pack, section, learned_dir)
                except LockedCoreError as exc:  # fail closed: no prompt from a refused section
                    raise PromptError(f"couche apprise du pack « {pack} » : {exc}") from None
                if learned is not None:
                    digest.update(f"learned:{pack}:{section}\0{learned}\0".encode())
                    role += f"\n\n{SECTION_TITLES[section]} :\n{learned}"
            roles[pack] = role
        header = _HEADER.match(raw_system)
        version = _SYSTEM_VERSION.search(header.group(0)) if header else None
        if version is None:
            raise PromptError("system.md : version absente de l'en-tête")
        return cls(
            templates=MappingProxyType(templates),
            roles=MappingProxyType(roles),
            version=f"system@{version.group(1)}+sha256:{digest.hexdigest()[:12]}",
        )

    def render(self, name: str, **values: str) -> str:
        if name == "system":
            raise PromptError("le prompt système se construit avec PromptSet.system()")
        return self.templates[name].render(**values)

    def system(self, context: RequestContext) -> str:
        role = self.roles.get(context.domain)
        if role is None:
            raise PromptError(f"aucun rôle chargé pour le pack « {context.domain} »")
        return self.templates["system"].render(
            now=context.now,
            domain=context.domain,
            autonomy_level=context.autonomy_level,
            environment=context.environment,
            app_context=context.app_context,
            memory_snippets=context.memory,
            domain_pack_role=role,
        )
