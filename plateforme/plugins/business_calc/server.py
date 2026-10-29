"""MCP stdio server of the ``business_calc`` plugin: ``biz_calc`` (CALCUL, ADR-061).

One tool, one closed list of operations (I2): the arithmetic lives in ``core/business/calc.py``
and every number leaves as a figure with its French display (R1). The VAT operation reads
``config/`` at each call, so a rate Lucas sets applies at the next call and a marker refuses it
(R7). Nothing leaves the machine: no network, no file written. ``CERVEAU_HOME`` names the served
project, the only variable the MCP adapter passes through.

No ``from __future__ import annotations`` here: the MCP SDK reads the tool signatures at runtime.
"""

import os
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from core.business.calc import BizCalc, CalcError, Request, Tva, calculate
from core.config.loader import BlockedFeatureError, ConfigError, load_config
from core.finance.views import config_location
from plugins.business_calc import __version__

FEATURE = "business.vat"
INVALID_CONFIG = "configuration invalide : lancer `cerveau config check`"
PARIS = ZoneInfo("Europe/Paris")

# Same text as plugin.yaml (a test keeps them equal).
DESCRIPTIONS = {
    "biz_calc": (
        "Calcul commercial déterministe, en décimal exact, pour une opération d'une liste "
        "fermée : marge (marge brute, taux de marge, taux de marque, coefficient), "
        "prix_de_vente (depuis un coût et une cible), tva (HT vers TTC ou l'inverse, au taux "
        "de config/business.yaml), seuil_rentabilite (seuil, point mort en jours, marge de "
        "sécurité), cac_ltv (CAC, LTV sur marge brute, rapport), variation et tcac. Rend les "
        "paramètres repris, les résultats avec leur affichage, les formules et les arrondis : "
        "les citer tels quels, sans recalcul."
    ),
}
ANNOTATIONS = ToolAnnotations(
    read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False
)
INSTRUCTIONS = (
    "Calculs commerciaux de Lucas : marges, prix, TVA, seuil de rentabilité, CAC et LTV, "
    "croissance. Les chiffres viennent de l'outil : les citer avec leur affichage et leur "
    "formule, ne jamais les recalculer (R1). Une entrée manquante se demande, elle ne se devine "
    "pas. Aide à la décision personnelle, pas un conseil (R16)."
)


def today() -> date:
    return datetime.now(UTC).astimezone(PARIS).date()


def build_server(config_dir: Path, clock: Callable[[], date] = today) -> MCPServer:
    server = MCPServer("business_calc", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(
        name="biz_calc",
        description=DESCRIPTIONS["biz_calc"],
        annotations=ANNOTATIONS,
        structured_output=True,
    )
    async def biz_calc(
        calcul: Annotated[
            Request,
            Field(description="L'opération et ses paramètres ; montants en euros"),
        ],
    ) -> BizCalc:
        try:
            if not isinstance(calcul, Tva):
                return calculate(calcul, today=clock())
            config = load_config(config_dir)
            config.require(FEATURE)
            return calculate(calcul, vat=config.business.vat, today=clock())
        except ConfigError:
            raise ToolError(INVALID_CONFIG) from None
        except (BlockedFeatureError, CalcError) as exc:
            raise ToolError(str(exc)) from None

    return server


def main() -> None:
    build_server(config_location(os.environ)).run()
