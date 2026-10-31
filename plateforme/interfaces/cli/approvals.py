"""`cerveau approvals enroll`: create the TOTP secret of the N3 approvals (D2, ADR-035).

The user runs it once, at an interactive terminal, and copies the secret into his authenticator
application and into the user environment variable ``CERVEAU_TOTP_SECRET``. Nothing is written:
the secret is shown once, never stored, logged nor journaled. Claude Code's hooks refuse it.
"""

from __future__ import annotations

import typer

from core.approvals.totp import SECRET_ENV, generate_secret, provisioning_uri
from core.execution.reconcile import interactive_terminal
from interfaces.cli.common import EXIT_BLOCKED, fail

approvals_app = typer.Typer(
    help="Approbations N3 : secret TOTP de l'utilisateur.", no_args_is_help=True
)


@approvals_app.command("enroll")
def enroll_command() -> None:
    """Crée un secret TOTP et l'affiche une seule fois, pour l'application d'authentification."""
    if not interactive_terminal():
        fail(
            "Enrôlement refusé : il se fait par l'utilisateur, dans un terminal interactif (D2).",
            EXIT_BLOCKED,
        )
    secret = generate_secret()
    typer.echo("Secret TOTP (affiché une seule fois, jamais enregistré par CERVEAU) :")
    typer.echo(f"  {secret}")
    typer.echo("URI pour l'application d'authentification (ou saisie manuelle du secret) :")
    typer.echo(f"  {provisioning_uri(secret)}")
    typer.echo(
        f"Posez ensuite {SECRET_ENV} comme variable d'environnement utilisateur, puis relancez "
        "l'API. Un nouvel enrôlement remplace l'ancien secret : les codes de l'ancien ne "
        "valent plus."
    )
