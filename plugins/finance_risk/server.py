"""MCP stdio server of the ``finance_risk`` plugin: ``risk_report`` (CALCUL).

The server reads the finance store read only and ``config/risk.yaml`` at each call, so a value
Lucas changes applies at the next call and a marker blocks it (R7). It returns the market risk
of the portfolio known at ``as_of``: volatility and GARCH, VaR and CVaR by three methods,
backtest, drawdown, beta, correlations, concentration, Euler contributions, stresses and the
split of a VaR change (ADR-014). Every number is a figure with its French display and an id
(R1). The store and the configuration are the ones of ``CERVEAU_HOME``, the only variable the MCP
adapter passes through.

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
from core.finance.risk_report import (
    MAX_SECTOR_SHOCKS,
    MEASURES,
    Measure,
    RiskReport,
    SectorShock,
)
from core.finance.risk_report import risk_report as build_report
from core.finance.views import ViewError
from plugins.finance_risk import __version__

FEATURE = "finance.market_risk"
INVALID_CONFIG = "configuration invalide : lancer `cerveau config check`"

# Same text as plugin.yaml (a test keeps them equal).
DESCRIPTIONS = {
    "risk_report": (
        "Risque de marché du portefeuille connu à as_of : volatilité et GARCH, VaR et CVaR "
        "historique, paramétrique et Monte Carlo, backtest de Kupiec, drawdown, bêta, "
        "corrélations, concentration, contributions d'Euler, stress de taux, d'actions, de "
        "change, sectoriels et historiques, décomposition d'une variation de VaR depuis "
        "compare_to. Chaque nombre porte sa valeur, son affichage et un identifiant ; une mesure "
        "impossible est dite, jamais estimée."
    ),
}
ANNOTATIONS = ToolAnnotations(
    read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False
)
INSTRUCTIONS = (
    "Mesures de risque du portefeuille de Lucas, calculées sur la base finance locale. Les "
    "chiffres viennent de l'outil : les citer avec leur affichage et leurs hypothèses, ne jamais "
    "les recalculer ni les extrapoler (R1)."
)


def now() -> datetime:
    return datetime.now(UTC)


def build_server(store: Path, config_dir: Path, clock: Callable[[], datetime] = now) -> MCPServer:
    server = MCPServer("finance_risk", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(
        name="risk_report",
        description=DESCRIPTIONS["risk_report"],
        annotations=ANNOTATIONS,
        structured_output=True,
    )
    async def risk_report(
        as_of: Annotated[
            AwareDatetime | None,
            Field(description="Moment « connu à », ISO 8601 avec fuseau ; défaut : maintenant"),
        ] = None,
        measures: Annotated[
            list[Measure] | None,
            Field(
                min_length=1,
                max_length=len(MEASURES),
                description="Mesures demandées ; défaut : toutes sauf les corrélations",
            ),
        ] = None,
        compare_to: Annotated[
            AwareDatetime | None,
            Field(
                description=(
                    "Moment antérieur à as_of : ajoute la décomposition de la variation de VaR "
                    "(effet positions, effet marché)"
                )
            ),
        ] = None,
        sector_shocks: Annotated[
            list[SectorShock],
            Field(
                max_length=MAX_SECTOR_SHOCKS,
                description="Chocs sectoriels du stress, secteur tel qu'écrit dans le référentiel",
            ),
        ] = [],  # noqa: B006 - read by the SDK, never mutated
        strict: Annotated[
            bool,
            Field(
                description=(
                    "Strict : seuls les imports et les données enregistrés avant as_of comptent "
                    "(rejeu d'une décision passée)"
                )
            ),
        ] = False,
    ) -> RiskReport:
        try:
            at = views.moment(as_of, clock())
            config = load_config(config_dir)
            config.require(FEATURE)
            market = config.risk.market_risk
            return views.read_store(
                store,
                lambda db: build_report(
                    db,
                    market,
                    as_of=at,
                    measures=measures,
                    compare_to=compare_to,
                    sector_shocks=sector_shocks,
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
