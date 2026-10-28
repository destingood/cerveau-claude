"""MCP stdio server of the ``finance_optimize`` plugin: ``rebalance_proposal`` (CALCUL).

The server reads the finance store read only and ``config/`` at each call, so a value Lucas
changes applies at the next call and a marker blocks it (R7). It returns target weights of the
securities known at ``as_of`` under one optimizer, with the risk before and after and, once the
broker's costs are known (D13), the operations in whole units (ADR-019). Nothing is executed: at
N0 the output is an analysis, from N1 a proposal not executed. Every number is a figure with its
French display and an id (R1). The store and the configuration are the ones of ``CERVEAU_HOME``,
the only variable the MCP adapter passes through.

No ``from __future__ import annotations`` here: the MCP SDK reads the tool signatures at runtime.
"""

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import AwareDatetime, Field

from core.config.loader import BlockedFeatureError, ConfigError, load_config
from core.finance import views
from core.finance.optimize import Method
from core.finance.rebalance import MAX_SECTOR_CAPS, RebalanceProposal, SectorCap
from core.finance.rebalance import rebalance_proposal as build_proposal
from core.finance.views import ViewError
from plugins.finance_optimize import __version__

FEATURE = "finance.market_risk"
MEAN_VARIANCE = "finance.mean_variance"
INVALID_CONFIG = "configuration invalide : lancer `cerveau config check`"

# Same text as plugin.yaml (a test keeps them equal).
DESCRIPTIONS = {
    "rebalance_proposal": (
        "Proposition de rééquilibrage des titres du portefeuille connu à as_of, sans rien "
        "exécuter : poids cibles par variance minimale, CVaR minimale, parité de risque, HRP ou "
        "moyenne-variance (covariance de Ledoit-Wolf), sous poids maximal, plafonds sectoriels "
        "et rotation maximale ; rotation, parts de risque, volatilité et VaR avant et après ; "
        "opérations en quantités entières et frais seulement si les frais du courtier sont "
        "connus. Chaque nombre porte sa valeur, son affichage et un identifiant."
    ),
}
ANNOTATIONS = ToolAnnotations(
    read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False
)
INSTRUCTIONS = (
    "Propositions de rééquilibrage du portefeuille de Lucas, calculées sur la base finance "
    "locale ; rien n'est exécuté. Les chiffres viennent de l'outil : les citer avec leur "
    "affichage, leur statut et leurs hypothèses, ne jamais les recalculer (R1). Aide à la "
    "décision personnelle, pas un conseil en investissement (R16)."
)


def now() -> datetime:
    return datetime.now(UTC)


def build_server(store: Path, config_dir: Path, clock: Callable[[], datetime] = now) -> MCPServer:
    server = MCPServer("finance_optimize", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(
        name="rebalance_proposal",
        description=DESCRIPTIONS["rebalance_proposal"],
        annotations=ANNOTATIONS,
        structured_output=True,
    )
    async def rebalance_proposal(
        method: Annotated[
            Method,
            Field(
                description=(
                    "Méthode : variance_minimale, cvar_minimale, parite_de_risque (contributions "
                    "égales), hrp (parité hiérarchique) ou moyenne_variance"
                )
            ),
        ],
        as_of: Annotated[
            AwareDatetime | None,
            Field(description="Moment « connu à », ISO 8601 avec fuseau ; défaut : maintenant"),
        ] = None,
        max_weight: Annotated[
            float | None,
            Field(gt=0.0, le=1.0, description="Poids maximal d'un titre, 0.2 = 20 % des titres"),
        ] = None,
        sector_caps: Annotated[
            list[SectorCap],
            Field(
                max_length=MAX_SECTOR_CAPS,
                description=(
                    "Plafonds sectoriels, secteur tel qu'écrit dans le référentiel ; refusés "
                    "par hrp"
                ),
            ),
        ] = [],  # noqa: B006 - read by the SDK, never mutated
        max_turnover: Annotated[
            float | None,
            Field(
                ge=0.0,
                le=2.0,
                description=(
                    "Rotation maximale, somme des écarts de poids en valeur absolue (0.3 = 30 %) ; "
                    "variance_minimale, cvar_minimale et moyenne_variance seulement"
                ),
            ),
        ] = None,
        strict: Annotated[
            bool,
            Field(
                description=(
                    "Strict : seuls les imports et les données enregistrés avant as_of comptent "
                    "(rejeu d'une décision passée)"
                )
            ),
        ] = False,
    ) -> RebalanceProposal:
        try:
            at = views.moment(as_of, clock())
            config = load_config(config_dir)
            config.require(FEATURE)
            if method == "moyenne_variance":
                config.require(MEAN_VARIANCE)
            return views.read_store(
                store,
                lambda db: build_proposal(
                    db,
                    config,
                    as_of=at,
                    method=method,
                    max_weight=max_weight,
                    sector_caps=sector_caps,
                    max_turnover=max_turnover,
                    strict=strict,
                ),
            )
        except ConfigError:
            raise ToolError(INVALID_CONFIG) from None
        except (BlockedFeatureError, ViewError) as exc:
            raise ToolError(str(exc)) from None

    return server


def main() -> None:
    build_server(views.store_location(os.environ), views.config_location(os.environ)).run()
