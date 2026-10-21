"""The domain packs the router may choose, and the plugins each one opens (section 9.1, ADR-043).

A pack is a directory ``domain_packs/<id>/`` whose id is one of ``DOMAINS``, read in that order
(section 9.2). A directory without a manifest is ignored; a malformed manifest blocks the start.
A manifest is declarative: only its id, its status, its plugin list and its agent matter to the
graph. The order of the list is the order of the planner's tools, so that the
``max_tools_to_planner`` cut keeps the pack's first tools. The agent, if any, is a registered agent
of ``plugins/`` (``kind: agent``) that runs only when asked for (D14): the committee of a pack is
the agent of mode ``comite`` (ADR-028).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from core.registry.manifest import DOMAINS

if TYPE_CHECKING:
    from core.config.loader import Config

PACKS_DIR = Path(__file__).resolve().parents[2] / "domain_packs"
DEFAULT_DOMAIN = "generaliste"
_PLUGIN_NAME = re.compile(r"^[a-z][a-z0-9_]*$")  # a directory of plugins/, never a path


class PackError(Exception):
    """A pack manifest is missing or malformed, or the configuration lacks one of its entries."""


def experimental_note(pack_id: str) -> str:
    """The line an answer of a pack not yet measured carries (R12, D2); no figure, R1."""
    return f"Pack « {pack_id} » expérimental : sa qualité n'est pas encore mesurée."


def golden_threshold_name(pack_id: str) -> str:
    """The key of the pack's golden set threshold in ``config/evals.yaml`` (D4)."""
    return f"{pack_id}_golden_min_score"


class PackAgent(BaseModel):
    """The pack's long agent; ``mode`` says how it is asked for (D14)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plugin: str
    mode: Literal["comite"]  # the router or ``--comite`` convenes it (ADR-028)

    @field_validator("plugin")
    @classmethod
    def _name(cls, plugin: str) -> str:
        if not _PLUGIN_NAME.fullmatch(plugin):
            raise ValueError(f"nom de plugin d'agent invalide : {plugin}")
        return plugin


class Pack(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str
    statut: Literal["experimental", "actif"]  # only Lucas writes « actif » (D2)
    plugins: tuple[str, ...] = Field(min_length=1)
    agent: PackAgent | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_committee_field(cls, data: Any) -> Any:
        # Ignored silently, the old field would drop the committee: refused instead.
        if isinstance(data, Mapping) and "comite" in data:
            raise ValueError("champ « comite » remplacé par « agent » (ADR-043)")
        return data

    @field_validator("plugins")
    @classmethod
    def _names(cls, plugins: tuple[str, ...]) -> tuple[str, ...]:
        bad = [name for name in plugins if not _PLUGIN_NAME.fullmatch(name)]
        if bad:
            raise ValueError(f"noms de plugin invalides : {', '.join(bad)}")
        if len(set(plugins)) != len(plugins):
            raise ValueError("plugin listé deux fois")
        return plugins

    @property
    def comite(self) -> str | None:
        """The plugin of its committee (D15), if its agent is one."""
        if self.agent is None or self.agent.mode != "comite":
            return None
        return self.agent.plugin

    @property
    def experimental(self) -> bool:
        return self.statut == "experimental"


def load_pack(pack_id: str, packs_dir: Path = PACKS_DIR) -> Pack:
    path = packs_dir / pack_id / "manifest.yaml"
    where = f"pack « {pack_id} » : manifeste"
    try:
        pack = Pack.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except OSError as exc:
        raise PackError(f"{where} illisible ({type(exc).__name__})") from None
    except yaml.YAMLError:
        raise PackError(f"{where} invalide (YAML)") from None
    except ValidationError as exc:
        reasons = "; ".join(str(error["msg"]) for error in exc.errors())
        raise PackError(f"{where} invalide ({reasons})") from None
    if pack.id != pack_id:
        raise PackError(f"pack « {pack_id} » : identifiant « {pack.id} » différent du dossier")
    return pack


def pack_ids(packs_dir: Path = PACKS_DIR) -> tuple[str, ...]:
    """The domains whose directory holds a manifest, in the order of section 9.2."""
    return tuple(domain for domain in DOMAINS if (packs_dir / domain / "manifest.yaml").is_file())


def load_packs(packs_dir: Path = PACKS_DIR) -> Mapping[str, Pack]:
    ids = pack_ids(packs_dir)
    if DEFAULT_DOMAIN not in ids:
        raise PackError(f"le pack de repli « {DEFAULT_DOMAIN} » manque")
    return MappingProxyType({pack_id: load_pack(pack_id, packs_dir) for pack_id in ids})


def pack_problems(packs: Mapping[str, Pack], config: Config) -> list[str]:
    """What a pack needs from the configuration and lacks: each one blocks the start."""
    problems = []
    for pack_id in packs:
        if pack_id not in config.autonomy.domains:
            problems.append(f"pack « {pack_id} » : domaine absent de config/autonomy.yaml")
        name = golden_threshold_name(pack_id)
        if name not in type(config.evals.thresholds).model_fields:
            problems.append(f"pack « {pack_id} » : seuil {name} absent de config/evals.yaml")
        elif isinstance(threshold := getattr(config.evals.thresholds, name), str):
            # A marker would let the pack answer without a measurable floor (R7, R9).
            problems.append(f"pack « {pack_id} » : seuil {name} non défini ({threshold})")
    return problems


def check_packs(packs: Mapping[str, Pack], config: Config) -> None:
    problems = pack_problems(packs, config)
    if problems:
        raise PackError(" ; ".join(problems))
