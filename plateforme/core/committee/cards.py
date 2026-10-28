"""A pack's committee: who sits, with which tools, and what each role card says (Annexe E).

``domain_packs/<pack>/committee.yaml`` names the members and their toolboxes; the card of each
active member is ``prompts/committee/<member>.md`` next to it, whose leading comment is
dropped. The structure follows Annexe E and
is checked here, before any model is called: analysts and the risk controller have tools, the
debaters and the manager have none, and at most five tools sit in one toolbox (R13).

The version a session keeps is the file's own version plus a digest of the file and of every card,
so that a changed card is a new version of the committee (R9). Line endings are normalised before
hashing, so a Windows checkout gives the same version as a Unix one.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from core.committee.engine import Card, CommitteeSpec, LimitChecks
from core.committee.schemas import MemberKind

COMMITTEE_FILE = "committee.yaml"
CARDS_DIR = Path("prompts") / "committee"
MAX_TOOLS = 5  # R13: three to five tools per domain, and so per toolbox
_HEADER = re.compile(r"\A\s*<!--.*?-->[ \t]*\n?", re.DOTALL)  # as in the orchestrator's prompts

MemberName = Annotated[str, Field(pattern=r"^[a-z][a-z_]*$", max_length=40)]
ToolName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]


class CommitteeError(ValueError):
    """A pack's committee file or one of its role cards is missing or malformed."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Member(_Strict):
    membre: MemberName
    outils: tuple[ToolName, ...] = Field(default=(), max_length=MAX_TOOLS)

    @field_validator("outils")
    @classmethod
    def _once(cls, tools: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(tools)) != len(tools):
            raise ValueError("un outil est listé deux fois")
        return tools


class Inactive(_Strict):
    membre: MemberName
    raison: str = Field(min_length=1, max_length=200)


class CommitteeFile(_Strict):
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    analystes: tuple[Member, ...] = Field(min_length=1, max_length=6)
    defenseur: Member
    contradicteur: Member
    gestionnaire: Member
    controleur: Member
    inactifs: tuple[Inactive, ...] = ()

    def members(self) -> list[tuple[MemberKind, Member]]:
        """Every active member with its kind, in the order of the cards."""
        return [
            *(("analyste", member) for member in self.analystes),
            ("defenseur", self.defenseur),
            ("contradicteur", self.contradicteur),
            ("gestionnaire", self.gestionnaire),
            ("controleur", self.controleur),
        ]

    @model_validator(mode="after")
    def _annex_e(self) -> CommitteeFile:
        unarmed = [
            m.membre
            for kind, m in self.members()
            if kind in ("analyste", "controleur") and not m.outils
        ]
        if unarmed:
            raise ValueError(
                "un analyste ou le contrôleur établit ses faits par ses outils (Annexe E) : "
                + ", ".join(unarmed)
            )
        armed = [
            m.membre for m in (self.defenseur, self.contradicteur, self.gestionnaire) if m.outils
        ]
        if armed:
            raise ValueError(
                "le débat et la décision se font sans outil, sur les seuls constats (Annexe E) : "
                + ", ".join(armed)
            )
        names = [m.membre for _, m in self.members()]
        twice = sorted({name for name in names if names.count(name) > 1})
        if twice:
            raise ValueError("membre listé deux fois : " + ", ".join(twice))
        inactive = [i.membre for i in self.inactifs]
        both = sorted(set(inactive) & set(names))
        if both or len(set(inactive)) != len(inactive):
            raise ValueError("un membre inactif est listé deux fois ou siège aussi")
        return self


def read_committee(pack_dir: Path, pack: str) -> tuple[CommitteeFile, str]:
    """The pack's committee file, validated, and its text with normalised line endings."""
    path = pack_dir / COMMITTEE_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CommitteeError(f"{pack} : {COMMITTEE_FILE} illisible ({type(exc).__name__})") from exc
    try:
        return CommitteeFile.model_validate(yaml.safe_load(text)), text
    except (yaml.YAMLError, ValidationError) as exc:
        raise CommitteeError(f"{pack} : {COMMITTEE_FILE} invalide : {exc}") from exc


def load_committee(
    pack_dir: Path, *, pack: str, feature: str, limit_checks: LimitChecks
) -> CommitteeSpec:
    """The committee of the pack in ``pack_dir``, every active member with its card."""
    file, text = read_committee(pack_dir, pack)
    digest = hashlib.sha256(text.encode("utf-8"))
    cards: dict[str, Card] = {}
    for kind, member in file.members():
        path = pack_dir / CARDS_DIR / f"{member.membre}.md"
        try:
            system = _HEADER.sub("", path.read_text(encoding="utf-8")).strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise CommitteeError(
                f"{pack} : fiche de rôle illisible pour {member.membre} "
                f"({(CARDS_DIR / path.name).as_posix()})"
            ) from exc
        if not system:
            raise CommitteeError(f"{pack} : fiche de rôle vide pour {member.membre}")
        digest.update(f"\0{member.membre}\0{system}".encode())
        cards[member.membre] = Card(member.membre, kind, system, member.outils)
    return CommitteeSpec(
        pack=pack,
        feature=feature,
        analysts=tuple(cards[m.membre] for m in file.analystes),
        defender=cards[file.defenseur.membre],
        challenger=cards[file.contradicteur.membre],
        manager=cards[file.gestionnaire.membre],
        controller=cards[file.controleur.membre],
        limit_checks=limit_checks,
        version=f"{file.version}+{digest.hexdigest()[:12]}",
    )
