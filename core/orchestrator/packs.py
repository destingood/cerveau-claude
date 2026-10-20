"""The domain packs the router may choose, and the plugins each one opens (section 9.1).

A pack's manifest is declarative (``domain_packs/<pack>/manifest.yaml``); only its id, its
plugin list and its committee matter to the graph. The order of the list is the order of the
planner's tools, so that the ``max_tools_to_planner`` cut keeps the pack's first tools. The
committee, if any, is a registered agent of ``plugins/`` (``kind: agent``, plan of phase 3, §10).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

PACKS_DIR = Path(__file__).resolve().parents[2] / "domain_packs"
DEFAULT_DOMAIN = "generaliste"
PACK_IDS: tuple[str, ...] = (DEFAULT_DOMAIN, "finance")  # the packs of phase 2
_PLUGIN_NAME = re.compile(r"^[a-z][a-z0-9_]*$")  # a directory of plugins/, never a path


class PackError(Exception):
    """A pack manifest is missing or malformed."""


class Pack(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str
    plugins: tuple[str, ...] = Field(min_length=1)
    comite: str | None = None  # the plugin of its committee (D15)

    @field_validator("comite")
    @classmethod
    def _committee(cls, comite: str | None) -> str | None:
        if comite is not None and not _PLUGIN_NAME.fullmatch(comite):
            raise ValueError(f"nom de Comité invalide : {comite}")
        return comite

    @field_validator("plugins")
    @classmethod
    def _names(cls, plugins: tuple[str, ...]) -> tuple[str, ...]:
        bad = [name for name in plugins if not _PLUGIN_NAME.fullmatch(name)]
        if bad:
            raise ValueError(f"noms de plugin invalides : {', '.join(bad)}")
        if len(set(plugins)) != len(plugins):
            raise ValueError("plugin listé deux fois")
        return plugins


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


def load_packs(
    pack_ids: Sequence[str] = PACK_IDS, packs_dir: Path = PACKS_DIR
) -> Mapping[str, Pack]:
    if DEFAULT_DOMAIN not in pack_ids:
        raise PackError(f"le pack de repli « {DEFAULT_DOMAIN} » manque")
    return MappingProxyType({pack_id: load_pack(pack_id, packs_dir) for pack_id in pack_ids})
