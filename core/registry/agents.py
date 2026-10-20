"""Loading an in-process agent (section 6.1, ADR-028).

An agent is validated by the registry before anything of it is imported (R8), and only from its
own folder: the ``plugins`` package must resolve ``plugins.<id>`` to the directory the registry
checked, and the imported module must come from it.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.registry.manifest import validate_plugin


class AgentLoadError(RuntimeError):
    """An agent the registry refuses, or whose entry point is not the one it validated."""


def load_agent(directory: Path) -> Callable[..., Any]:
    """The entry point of the in-process agent in ``directory``, validated before any import."""
    report = validate_plugin(directory)
    if not report.ok or report.manifest is None:
        raise AgentLoadError(
            f"agent « {directory.name} » refusé par le registre : " + " ; ".join(report.errors)
        )
    manifest, agent = report.manifest, report.manifest.agent
    if agent is None:
        raise AgentLoadError(f"plugin « {manifest.id} » : ce n'est pas un agent in-process")
    folder = directory.resolve()
    package = importlib.import_module("plugins")
    if folder.parent not in [Path(p).resolve() for p in package.__path__]:
        raise AgentLoadError(f"agent « {manifest.id} » : son dossier est hors du paquet plugins")
    module = importlib.import_module(agent.module)
    origin = Path(module.__file__ or "").resolve()
    if not origin.is_relative_to(folder):
        raise AgentLoadError(
            f"agent « {manifest.id} » : le module {agent.module} ne vient pas du dossier validé"
        )
    target = getattr(module, agent.function, None)
    if not callable(target):
        raise AgentLoadError(f"agent « {manifest.id} » : {agent.entrypoint} n'est pas une fonction")
    return target
