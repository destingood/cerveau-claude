"""The ntfy channel (ADR-038): ``POST <server>/<topic>`` with ``X-Title``, ``X-Priority``,
``X-Tags`` and, when a token is set, ``Authorization: Bearer`` (docs.ntfy.sh/publish, read on
21/10/2026).

On ntfy.sh every topic is public and the topic acts as a password: it lives in ``NTFY_TOPIC``, set
by Lucas, at least 32 random characters, never in the repository; so does the optional token in
``NTFY_TOKEN``. Neither is ever printed, journaled or kept in a ``repr``. The body is the alert's
French text; the title, a header, is ASCII only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

import httpx

from core.config.loader import NtfySettings
from core.notify.alerts import Alert

TOPIC_VARIABLE = "NTFY_TOPIC"
TOKEN_VARIABLE = "NTFY_TOKEN"  # noqa: S105 - the variable's name, not a token
MIN_TOPIC_CHARS = 32
# ntfy's topic names: letters, digits, "_" and "-", 64 at most.
_TOPIC = re.compile(rf"^[A-Za-z0-9_-]{{{MIN_TOPIC_CHARS},64}}$")
_TOKEN = re.compile(r"^[!-~]{1,256}$")  # printable ASCII: a header value


class NtfyNotifier:
    """Sends an alert to one ntfy topic; any answer other than 2xx raises."""

    channel = "ntfy"

    def __init__(
        self,
        server: str,
        topic: str,
        *,
        token: str | None,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not _TOPIC.match(topic):
            raise ValueError(
                f"sujet ntfy invalide : {MIN_TOPIC_CHARS} à 64 lettres, chiffres, « _ » ou « - »"
            )
        if token is not None and not _TOKEN.match(token):
            raise ValueError("jeton ntfy invalide")
        self._url = f"{server.rstrip('/')}/{topic}"
        self._token = token
        self._timeout = timeout_seconds
        self._transport = transport

    def __repr__(self) -> str:  # never the topic nor the token (R6)
        return "NtfyNotifier(sujet et jeton masqués)"

    def send(self, alert: Alert) -> None:
        headers = {
            "X-Title": alert.title,
            "X-Priority": str(alert.severity),
            "X-Tags": f"cerveau,{alert.kind}",
        }
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token}"
        with httpx.Client(
            timeout=self._timeout, transport=self._transport, follow_redirects=False
        ) as client:
            response = client.post(self._url, content=alert.text().encode(), headers=headers)
        if not response.is_success:
            raise NtfyError(response.status_code)


class NtfyError(Exception):
    """ntfy answered without accepting the alert: the status code only, never the URL."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"ntfy a répondu {status_code}")


def ntfy_from(
    settings: NtfySettings,
    environ: Mapping[str, str],
    *,
    transport: httpx.BaseTransport | None = None,
) -> tuple[NtfyNotifier | None, str | None]:
    """The ntfy channel, or None with the reason, which never quotes the topic nor the token."""
    if not isinstance(settings.server, str) or not settings.server.startswith("https://"):
        return None, "serveur ntfy à définir dans config/interfaces.yaml (R7)"
    topic = environ.get(TOPIC_VARIABLE, "")
    if not topic:
        return None, f"{TOPIC_VARIABLE} absente de l'environnement"
    try:
        notifier = NtfyNotifier(
            settings.server,
            topic,
            token=environ.get(TOKEN_VARIABLE) or None,
            timeout_seconds=settings.timeout_seconds,
            transport=transport,
        )
    except ValueError as exc:
        return None, f"{exc} ({TOPIC_VARIABLE} ou {TOKEN_VARIABLE})"
    return notifier, None
