"""Offline doubles for the web_research tests: the network doubles of ``tests.net_doubles`` (no
socket is ever opened) and a ``WebReader`` wired to them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from plugins.web_research.fetcher import WebReader
from tests.net_doubles import OTHER_V4, PUBLIC_V4, FakeDns, FakeWeb, chunks

__all__ = ["ARTICLE", "FIXED_NOW", "OTHER_V4", "PUBLIC_V4", "FakeDns", "FakeWeb", "chunks"]

FIXED_NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def make_reader(web: FakeWeb, dns: FakeDns, **options: Any) -> WebReader:
    return WebReader(
        resolver=dns,
        transport=httpx.MockTransport(web),
        clock=lambda: FIXED_NOW,
        **options,
    )


ARTICLE = """<html><head><title>Titre de test</title>
<meta property="article:published_time" content="2024-05-01T10:00:00Z"></head>
<body><nav>menu accueil contact</nav><article><h1>Titre de test</h1>
<p>Le premier paragraphe de l'article explique en détail le sujet principal de la page avec
assez de mots pour être retenu par l'extracteur.</p>
<p>Un second paragraphe ajoute des précisions utiles et un chiffre : 42 pour cent.</p>
</article><footer>pied de page</footer></body></html>"""
