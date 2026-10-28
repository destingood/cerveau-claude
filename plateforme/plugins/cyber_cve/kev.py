"""CISA Known Exploited Vulnerabilities catalogue, read whole and cached 24 h (G2, G4, ADR-055).

The feed is about 1.8 MB (observed on 2026-10-27, 1 758 entries); the cap is 10 MB. The CISA
publishes it under CC0 1.0 and gives no endorsement (G9). The ``notes`` and ``forensicTriage``
fields are not kept: the first holds free links, the second is not needed by the tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from plugins.cyber_cve.common import (
    CyberError,
    Fetcher,
    Read,
    cve_id,
    day,
    is_cwe,
    load_json,
    short,
)
from plugins.cyber_cve.models import MAX_CWES, KevEntry

FEED_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
MAX_BYTES = 10_000_000


@dataclass(frozen=True)
class KevCatalog:
    version: str | None
    released: str | None
    entries: dict[str, KevEntry]


def _entry(item: dict[str, object], today: date) -> tuple[str, KevEntry] | None:
    raw_id = item.get("cveID")
    identifier = cve_id(raw_id, today) if isinstance(raw_id, str) else None
    added = day(item.get("dateAdded"))
    if identifier is None or added is None:
        return None
    due = day(item.get("dueDate"))
    cwes = item.get("cwes")
    kept = dict.fromkeys(c for c in cwes if is_cwe(c)) if isinstance(cwes, list) else {}
    return identifier, KevEntry(
        date_added=added.isoformat(),
        due_date=due.isoformat() if due else None,
        vendor=short(item.get("vendorProject"), 100),
        product=short(item.get("product"), 200),
        name=short(item.get("vulnerabilityName"), 200),
        description=short(item.get("shortDescription"), 1000),
        required_action=short(item.get("requiredAction"), 1000),
        ransomware=short(item.get("knownRansomwareCampaignUse"), 20),
        cwes=list(kept)[:MAX_CWES],
    )


def parse_catalog(body: bytes, today: date) -> KevCatalog:
    """The entries by identifier; invalid entries are skipped, an empty catalogue or one whose
    length differs from its announced ``count`` (a cut copy) is refused."""
    data = load_json(body, "KEV")
    if not isinstance(data, dict) or not isinstance(items := data.get("vulnerabilities"), list):
        raise CyberError("KEV : catalogue illisible (liste des vulnérabilités absente)")
    count = data.get("count")
    if isinstance(count, int) and not isinstance(count, bool) and count != len(items):
        raise CyberError("KEV : catalogue tronqué (nombre d'entrées différent du compte annoncé)")
    entries: dict[str, KevEntry] = {}
    for item in items:
        found = _entry(item, today) if isinstance(item, dict) else None
        if found is not None and found[0] not in entries:
            entries[found[0]] = found[1]
    if not entries:
        raise CyberError("KEV : catalogue vide ou illisible")
    return KevCatalog(
        version=short(data.get("catalogVersion"), 40),
        released=short(data.get("dateReleased"), 40),
        entries=entries,
    )


class KevSource:
    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    async def catalog(self) -> Read[KevCatalog]:
        today = self.fetcher.now().date()
        return await self.fetcher.get(FEED_URL, None, lambda body: parse_catalog(body, today))
