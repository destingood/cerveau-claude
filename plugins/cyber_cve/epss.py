"""EPSS scores of FIRST: one request for up to 10 identifiers, cached 24 h (G4, ADR-055).

The API answers ``{"status": "OK", "data": [{"cve", "epss", "percentile", "date"}]}`` with the
scores as decimal strings; an identifier it does not know is simply absent (observed on
2026-10-27). FIRST asks for attribution when the scores are used (G9).
"""

from __future__ import annotations

from datetime import date

from plugins.cyber_cve.common import CyberError, Fetcher, Read, cve_id, day, load_json, number
from plugins.cyber_cve.models import EpssScore

API_URL = "https://api.first.org/data/v1/epss"


def parse_scores(body: bytes, today: date) -> dict[str, EpssScore]:
    """Scores by identifier; an entry with a missing or out-of-range value is skipped."""
    data = load_json(body, "EPSS")
    if not isinstance(data, dict) or not isinstance(items := data.get("data"), list):
        raise CyberError("EPSS : réponse illisible (liste des scores absente)")
    scores: dict[str, EpssScore] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(raw := item.get("cve"), str):
            continue
        identifier = cve_id(raw, today)
        epss, percentile = number(item.get("epss"), 0, 1), number(item.get("percentile"), 0, 1)
        computed = day(item.get("date"))
        if identifier and epss is not None and percentile is not None and computed:
            scores.setdefault(
                identifier,
                EpssScore(epss=epss, percentile=percentile, date=computed.isoformat()),
            )
    return scores


class EpssSource:
    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    async def scores(self, identifiers: list[str]) -> Read[dict[str, EpssScore]]:
        """The scores of the requested identifiers only, whatever else the answer holds."""
        today = self.fetcher.now().date()
        read = await self.fetcher.get(
            API_URL, {"cve": ",".join(identifiers)}, lambda body: parse_scores(body, today)
        )
        wanted = {i: s for i, s in read.value.items() if i in identifiers}
        return Read(wanted, read.read_at, read.cached)
