"""MCP stdio server of the ``finance_portfolio`` plugin: ``portfolio_snapshot`` (LECTURE).

The server opens the finance store read only at each call; only Lucas's commands write it
(`cerveau portfolio import`, `cerveau finance sync`). It returns the positions, the cash, the
weights, the exposures and the reconciliation status as known at ``as_of`` (ADR-018). Every
number is a figure with its French display and an id (R1); the quantities of a reconciliation
gap are shown by the CLI only. The store is the one of ``CERVEAU_HOME``, the only variable the
MCP adapter passes through.

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
from core.finance.views import Snapshot, ViewError
from plugins.finance_portfolio import __version__

# Same text as plugin.yaml (a test keeps them equal).
DESCRIPTIONS = {
    "portfolio_snapshot": (
        "Instantané du portefeuille connu à as_of : positions, espèces, poids, expositions par "
        "secteur, pays et devise, état du rapprochement avec le dernier relevé. Chaque nombre "
        "porte sa valeur, son affichage et un identifiant."
    ),
}
ANNOTATIONS = ToolAnnotations(
    read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False
)
INSTRUCTIONS = (
    "Lecture du portefeuille de Lucas dans la base finance locale. Les chiffres viennent de "
    "l'outil : les citer avec leur affichage, ne jamais les recalculer (R1)."
)


def now() -> datetime:
    return datetime.now(UTC)


def build_server(store: Path, clock: Callable[[], datetime] = now) -> MCPServer:
    server = MCPServer("finance_portfolio", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(
        name="portfolio_snapshot",
        description=DESCRIPTIONS["portfolio_snapshot"],
        annotations=ANNOTATIONS,
        structured_output=True,
    )
    async def portfolio_snapshot(
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
    ) -> Snapshot:
        try:
            at = views.moment(as_of, clock())
            return views.read_store(
                store, lambda db: views.portfolio_snapshot(db, as_of=at, strict=strict)
            )
        except ViewError as exc:
            raise ToolError(str(exc)) from None

    return server


def main() -> None:
    build_server(views.store_location(os.environ)).run()
