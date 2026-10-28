"""MCP stdio server of the ``finance_research`` plugin: ``strategy_lab`` (CALCUL, ADR-027).

The server reads the strategy registry, the research store and ``config/`` of ``CERVEAU_HOME`` at
each call, read only. For one registered strategy it gives its signals at the last decision known
at ``as_of``, the backtest of one grid point over a bounded window, or the latest verdict of the
protocol. No mode gives a verdict: only ``cerveau strategy protocol`` does, and every backtest
asked here is a trial the next protocol replays and counts (``core/finance/research/copilot.py``).
Every number is a figure with its French display and an id (R1).

No ``from __future__ import annotations`` here: the MCP SDK reads the tool signatures at runtime.
"""

import os
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import AwareDatetime, Field, ValidationError

from core.config.loader import BlockedFeatureError, ConfigError, load_config
from core.finance import views
from core.finance.model import ParamName, StrategyId
from core.finance.research.copilot import Mode
from core.finance.research.lab import StrategyLab
from core.finance.research.lab import strategy_lab as build_answer
from core.finance.research.view import LookAheadError
from core.finance.views import ViewError
from plugins.finance_research import __version__

INVALID_CONFIG = "configuration invalide : lancer `cerveau config check`"
INVALID_DATA = "une donnée du registre ou de la base ne passe plus ses contrôles à la relecture"
MAX_PARAMS = 16  # parameters of one grid point
ParamText = Annotated[str, Field(max_length=64)]

# Same text as plugin.yaml (a test keeps them equal).
DESCRIPTIONS = {
    "strategy_lab": (
        "Laboratoire d'une stratégie du registre, connu à as_of. Mode signaux : poids et "
        "indicateurs d'un point de la grille à la dernière décision connue. Mode backtest : "
        "backtest d'un point de la grille sur une fenêtre bornée, frais inclus ; c'est un essai "
        "que le prochain protocole compte. Mode protocole : dernier verdict enregistré. Aucun "
        "mode ne rend de verdict ; chaque nombre porte sa valeur, son affichage et un "
        "identifiant."
    ),
}
ANNOTATIONS = ToolAnnotations(
    read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False
)
INSTRUCTIONS = (
    "Recherche sur les stratégies du registre de CERVEAU, sur la base locale. Les chiffres "
    "viennent de l'outil : les citer avec leur affichage, ne jamais les recalculer (R1). Un "
    "backtest favorable n'est pas un verdict : rappeler le dernier verdict du protocole."
)


def now() -> datetime:
    return datetime.now(UTC)


def build_server(root: Path, config_dir: Path, clock: Callable[[], datetime] = now) -> MCPServer:
    server = MCPServer("finance_research", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(
        name="strategy_lab",
        description=DESCRIPTIONS["strategy_lab"],
        annotations=ANNOTATIONS,
        structured_output=True,
    )
    async def strategy_lab(
        strategie: Annotated[
            StrategyId,
            Field(description="Identifiant de la stratégie dans le registre"),
        ],
        mode: Annotated[
            Mode,
            Field(
                description=(
                    "signaux : poids et indicateurs ; backtest : un point de la grille sur une "
                    "fenêtre bornée ; protocole : dernier verdict enregistré"
                )
            ),
        ],
        params: Annotated[
            dict[ParamName, bool | int | float | ParamText] | None,
            Field(
                min_length=1,
                max_length=MAX_PARAMS,
                description=(
                    "Un point de la grille, types compris (10 n'est pas 10.0) ; requis en modes "
                    "signaux et backtest, refusé en mode protocole"
                ),
            ),
        ] = None,
        as_of: Annotated[
            AwareDatetime | None,
            Field(description="Moment « connu à », ISO 8601 avec fuseau ; défaut : maintenant"),
        ] = None,
        debut: Annotated[
            date | None,
            Field(
                description=(
                    "Mode backtest : premier jour ; défaut : la fenêtre la plus récente que "
                    "permet config/research.yaml"
                )
            ),
        ] = None,
        fin: Annotated[
            date | None,
            Field(description="Mode backtest : dernier jour ; défaut : dernière décision connue"),
        ] = None,
    ) -> StrategyLab:
        try:
            at = views.moment(as_of, clock())
            config = load_config(config_dir)
            return build_answer(
                root,
                config,
                strategy_id=strategie,
                mode=mode,
                at=at,
                params=params,
                start=debut,
                end=fin,
            )
        except ConfigError:
            raise ToolError(INVALID_CONFIG) from None
        except ValidationError:
            raise ToolError(INVALID_DATA) from None
        except (BlockedFeatureError, ViewError, LookAheadError, ValueError) as exc:
            raise ToolError(str(exc)) from None

    return server


def main() -> None:
    build_server(views.home_location(os.environ), views.config_location(os.environ)).run()
