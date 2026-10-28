"""MCP stdio server of the ``finance_data`` plugin: ``market_data`` (LECTURE).

The server opens the finance store read only at each call; only `cerveau finance sync` writes
it. It returns closes or reference cards as known at ``as_of`` (ADR-017), with the last quality
score recorded for each series (ADR-016). It returns no free text from a provider, neither a
description nor news (R5); the names went through ``plain_text`` when they were stored and
again when they are read. Fundamentals have no provider yet (ADR-013): asking for them is an
error that says so. The store is the one of ``CERVEAU_HOME``, the only variable the MCP adapter
passes through.

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

from core.finance import views
from core.finance.adjust import Adjustment
from core.finance.model import InstrumentId
from core.finance.views import MAX_INSTRUMENTS, MAX_SESSIONS, Kind, MarketData, ViewError
from plugins.finance_data import __version__

# Same text as plugin.yaml (a test keeps them equal).
DESCRIPTIONS = {
    "market_data": (
        "Données de marché de la base finance connues à as_of : clôtures des dernières séances "
        "(cours) ou fiches du référentiel (referentiel), avec score de qualité et fraîcheur. "
        "Fondamentaux indisponibles (aucun fournisseur). Chaque nombre porte sa valeur, son "
        "affichage et un identifiant."
    ),
}
ANNOTATIONS = ToolAnnotations(
    read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False
)
INSTRUCTIONS = (
    "Lecture des cours et du référentiel dans la base finance locale. Les chiffres viennent de "
    "l'outil : les citer avec leur affichage, ne jamais les recalculer (R1)."
)


def now() -> datetime:
    return datetime.now(UTC)


def build_server(store: Path, clock: Callable[[], datetime] = now) -> MCPServer:
    server = MCPServer("finance_data", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(
        name="market_data",
        description=DESCRIPTIONS["market_data"],
        annotations=ANNOTATIONS,
        structured_output=True,
    )
    async def market_data(
        instruments: Annotated[
            list[InstrumentId],
            Field(
                min_length=1,
                max_length=MAX_INSTRUMENTS,
                description="Identifiants CERVEAU des instruments (1 à 10)",
            ),
        ],
        kind: Annotated[Kind, Field(description="cours, referentiel ou fondamentaux")] = "cours",
        as_of: Annotated[
            AwareDatetime | None,
            Field(description="Moment « connu à », ISO 8601 avec fuseau ; défaut : maintenant"),
        ] = None,
        sessions: Annotated[
            int,
            Field(ge=1, le=MAX_SESSIONS, description="Nombre de séances de cours (1 à 260)"),
        ] = 20,
        adjust: Annotated[
            Adjustment,
            Field(description="Ajustement des cours : none, split ou total_return"),
        ] = "none",
        strict: Annotated[
            bool,
            Field(
                description=(
                    "Strict : seules les données enregistrées avant as_of comptent "
                    "(rejeu d'une décision passée)"
                )
            ),
        ] = False,
    ) -> MarketData:
        try:
            at = views.moment(as_of, clock())
            return views.read_store(
                store,
                lambda db: views.market_data(
                    db,
                    instruments,
                    kind=kind,
                    as_of=at,
                    sessions=sessions,
                    adjust=adjust,
                    strict=strict,
                ),
            )
        except ViewError as exc:
            raise ToolError(str(exc)) from None

    return server


def main() -> None:
    build_server(views.store_location(os.environ)).run()
