"""Alerts: ntfy and Discord, minimal content, never blocking (ADR-038)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import httpx

from core.config.loader import Config
from core.notify.alerts import (
    ALERT_KINDS,
    NOTIFICATION_KEY,
    Alert,
    AlertKind,
    Alerts,
    Notifier,
    as_ref,
    budget_severity,
    stop_alerts,
)
from core.notify.ntfy import NtfyNotifier, ntfy_from
from core.notify.outbox import DiscordOutbox, Posted, default_outbox_path, read_outbox

__all__ = [
    "ALERT_KINDS",
    "NOTIFICATION_KEY",
    "Alert",
    "AlertKind",
    "Alerts",
    "DiscordOutbox",
    "Notifier",
    "NtfyNotifier",
    "Posted",
    "alerts_from",
    "as_ref",
    "budget_severity",
    "default_outbox_path",
    "read_outbox",
    "stop_alerts",
]


def alerts_from(
    config: Config | None,
    project_root: Path,
    environ: Mapping[str, str],
    *,
    transport: httpx.BaseTransport | None = None,
) -> tuple[Alerts, list[str]]:
    """The configured channels, and why each missing one is off, without any secret value.

    ntfy needs its server in ``config/interfaces.yaml`` and ``NTFY_TOPIC``; the Discord outbox
    needs the bot's settings, since only the API reads it for the bot (D23).
    """
    if config is None:
        return Alerts(), ["configuration invalide : alertes au journal et à la console seulement"]
    channels: list[Notifier] = []
    notes: list[str] = []
    ntfy, why = ntfy_from(config.interfaces.ntfy, environ, transport=transport)
    if ntfy is None:
        notes.append(f"alertes ntfy coupées : {why}")
    else:
        channels.append(ntfy)
    if config.blockers("interfaces.discord"):
        notes.append("alertes Discord coupées : bot et API à définir dans config/interfaces.yaml")
    else:
        channels.append(DiscordOutbox(default_outbox_path(project_root)))
    return Alerts(tuple(channels)), notes
