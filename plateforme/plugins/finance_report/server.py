"""MCP stdio server of the ``finance_report`` plugin: ``performance_report`` (CALCUL).

The server reads the finance store read only and ``config/`` at each call, so a value the user
changes applies at the next call and a marker blocks it (R7). It returns the performance of the
book known at ``as_of`` over a period: TWR, MWR, volatility, Sharpe and Sortino over the €STR,
maximum drawdown and Calmar, and the contributions of each line and sector (ADR-020). Every number
is a figure with its French display and an id (R1). The store and the configuration are the ones
of ``CERVEAU_HOME``, the only variable the MCP adapter passes through.

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
from pydantic import AwareDatetime, Field

from core.config.loader import BlockedFeatureError, ConfigError, load_config
from core.finance import views
from core.finance.performance_report import PerformanceReport
from core.finance.performance_report import performance_report as build_report
from core.finance.views import ViewError
from plugins.finance_report import __version__

FEATURE = "finance.performance"
INVALID_CONFIG = "configuration invalide : lancer `cerveau config check`"

# Same text as plugin.yaml (a test keeps them equal).
DESCRIPTIONS = {
    "performance_report": (
        "Performance du portefeuille connu à as_of sur une période : valeurs de début et de fin, "
        "apports, dividendes et frais, TWR et MWR (annualisés sur au moins un an), volatilité, "
        "Sharpe et Sortino sur l'€STR, perte maximale avec ses dates, Calmar ; contributions au "
        "TWR de chaque ligne et de chaque secteur avec le résidu. Comparaison à l'indice et "
        "attribution factorielle indisponibles tant que l'indice et les facteurs ne sont pas "
        "validés. Chaque nombre porte sa valeur, son affichage et un identifiant."
    ),
}
ANNOTATIONS = ToolAnnotations(
    read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False
)
INSTRUCTIONS = (
    "Performance et attribution du portefeuille de l'utilisateur, calculées sur la base finance "
    "locale. "
    "Les chiffres viennent de l'outil : les citer avec leur affichage et leurs hypothèses, ne "
    "jamais les recalculer (R1). Aide à la décision personnelle, pas un conseil en "
    "investissement (R16)."
)


def now() -> datetime:
    return datetime.now(UTC)


def build_server(store: Path, config_dir: Path, clock: Callable[[], datetime] = now) -> MCPServer:
    server = MCPServer("finance_report", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(
        name="performance_report",
        description=DESCRIPTIONS["performance_report"],
        annotations=ANNOTATIONS,
        structured_output=True,
    )
    async def performance_report(
        start: Annotated[
            date | None,
            Field(
                description=(
                    "Début de la période (base, AAAA-MM-JJ) ; défaut : la première opération"
                )
            ),
        ] = None,
        end: Annotated[
            date | None,
            Field(description="Fin de la période (AAAA-MM-JJ) ; défaut : le jour de as_of"),
        ] = None,
        as_of: Annotated[
            AwareDatetime | None,
            Field(description="Moment « connu à », ISO 8601 avec fuseau ; défaut : maintenant"),
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
    ) -> PerformanceReport:
        try:
            at = views.moment(as_of, clock())
            config = load_config(config_dir)
            config.require(FEATURE)
            return views.read_store(
                store,
                lambda db: build_report(db, config, as_of=at, start=start, end=end, strict=strict),
            )
        except ConfigError:
            raise ToolError(INVALID_CONFIG) from None
        except (BlockedFeatureError, ViewError) as exc:
            raise ToolError(str(exc)) from None

    return server


def main() -> None:
    build_server(views.store_location(os.environ), views.config_location(os.environ)).run()
