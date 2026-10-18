"""What the `cerveau` sub-commands share: project root, options, exit codes, refusals."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, NoReturn

import typer

from core.config import BlockedFeatureError, ConfigError, load_config

if TYPE_CHECKING:
    from core.config.loader import Config

JournalOpt = Annotated[
    Path | None, typer.Option("--journal", help="Chemin du journal (défaut : var/audit).")
]
ConfigDirOpt = Annotated[
    Path | None, typer.Option("--config-dir", help="Dossier de configuration (défaut : config/).")
]
EXIT_ERROR, EXIT_BLOCKED, EXIT_BUDGET, EXIT_GAP = 1, 2, 3, 4


def project_root() -> Path:
    override = os.environ.get("CERVEAU_HOME")
    return Path(override) if override else Path(__file__).resolve().parents[2]


def fail(message: str, code: int) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code)


def load(config_dir: Path | None) -> Config:
    directory = config_dir or project_root() / "config"
    try:
        return load_config(directory)
    except ConfigError:
        fail(f"Configuration invalide ({directory}) : lancer `cerveau config check`.", EXIT_ERROR)


def blocked(exc: BlockedFeatureError) -> NoReturn:
    fail(f"Bloqué (R7) : {exc}. Voir `cerveau config check`.", EXIT_BLOCKED)
