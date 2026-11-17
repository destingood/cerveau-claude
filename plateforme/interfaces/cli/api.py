"""`cerveau api serve`: the local internal API, on the loopback only (D1, D16, ADR-037).

The user starts it himself, with ``CERVEAU_API_TOKEN`` set as a user environment variable; Claude
Code's hooks refuse to start it (D22). Without a long enough token the API does not start.
"""

from __future__ import annotations

import os
from typing import cast

import typer

from core.config import BlockedFeatureError
from interfaces.api import ApiError, create_app
from interfaces.cli.common import EXIT_BLOCKED, ConfigDirOpt, blocked, fail, load, project_root

api_app = typer.Typer(help="API interne locale (127.0.0.1) du bot et du dashboard.")


@api_app.command("serve")
def serve_command(config_dir: ConfigDirOpt = None) -> None:
    """Lance l'API interne sur 127.0.0.1 ; arrêt par Ctrl+C."""
    import uvicorn  # the server is loaded only to serve

    root = project_root()
    config = load(config_dir)
    try:
        config.require("interfaces.api")
    except BlockedFeatureError as exc:
        blocked(exc)
    settings = config.interfaces.api
    port = cast(int, settings.port)  # require() above refused a marker (B210)
    try:
        app = create_app(root, environ=os.environ, config_dir=config_dir)
    except ApiError as exc:
        fail(f"API non démarrée : {exc}.", EXIT_BLOCKED)
    typer.echo(f"API interne sur http://{settings.host}:{port} (Ctrl+C pour arrêter).")
    uvicorn.run(
        app,
        host=settings.host,
        port=port,
        log_level="warning",
        server_header=False,
        proxy_headers=False,
    )
