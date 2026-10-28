"""NVD CVE API 2.0: one record by identifier, or the CVEs published in a date range (ADR-055).

Only the fields the tools publish are kept. The scores are those the NVD and the CNA published
(R1); references tagged ``Exploit`` are left out (R15). The API refuses ranges of more than 120
days (HTTP 404 with a ``message`` header, observed on 2026-10-27), so the tool refuses them first.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from plugins.cyber_cve.common import (
    CyberError,
    Fetcher,
    Read,
    cve_id,
    is_cwe,
    load_json,
    short,
    text,
)
from plugins.cyber_cve.models import (
    MAX_CWES,
    MAX_REFERENCES,
    Cvss,
    CvssVersion,
    NvdRecord,
    Reference,
    Ssvc,
)

API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
DETAIL_URL = "https://nvd.nist.gov/vuln/detail/"
MAX_RANGE_DAYS = 120
PAGE_SIZE = 20
DESCRIPTION_MAX = 2000
VECTOR_MAX = 200
URL_MAX = 500
TAG_MAX = 40
TAGS_MAX = 8
PER_VERSION = 2
# Most recent version first: the first score of the list is the one the ranking uses (G8).
VERSIONS: tuple[tuple[str, CvssVersion], ...] = (
    ("cvssMetricV40", "4.0"),
    ("cvssMetricV31", "3.1"),
    ("cvssMetricV30", "3.0"),
    ("cvssMetricV2", "2.0"),
)
# Advice to act on comes first; the order of the NVD is kept otherwise.
REFERENCE_PRIORITY = ("Vendor Advisory", "Patch", "Mitigation", "Third Party Advisory")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}")
# Printable ASCII only: no space, control, bidirectional or look-alike character in a link.
_URL = re.compile(r"https?://[\x21-\x7e]+")


@dataclass(frozen=True)
class NvdPage:
    total: int
    start: int
    records: list[NvdRecord]


def timestamp(value: object) -> str | None:
    """``YYYY-MM-DDTHH:MM:SS`` of an NVD timestamp (written without time zone), else None."""
    if not isinstance(value, str) or _TIMESTAMP.fullmatch(value[:19]) is None:
        return None
    try:
        datetime.fromisoformat(value[:19])
    except ValueError:
        return None
    return value[:19]


def _dicts(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _cvss(item: dict[str, Any], version: CvssVersion) -> Cvss | None:
    data = item.get("cvssData")
    if not isinstance(data, dict) or data.get("version", version) != version:
        return None
    score = data.get("baseScore")
    if isinstance(score, bool) or not isinstance(score, int | float) or not 0 <= score <= 10:
        return None
    return Cvss(
        version=version,
        base_score=float(score),
        severity=short(data.get("baseSeverity", item.get("baseSeverity")), 20),
        vector=short(data.get("vectorString"), VECTOR_MAX),
        source=short(item.get("source"), 100),
        primary=item.get("type") == "Primary",
    )


def parse_cvss(metrics: object) -> list[Cvss]:
    """Published scores, most recent version first, the primary score first in each version."""
    if not isinstance(metrics, dict):
        return []
    found: list[Cvss] = []
    for key, version in VERSIONS:
        scores = [s for s in (_cvss(i, version) for i in _dicts(metrics.get(key))) if s]
        found.extend(sorted(scores, key=lambda s: not s.primary)[:PER_VERSION])
    return found


def parse_ssvc(metrics: object) -> Ssvc | None:
    """The SSVC decision points of the most recent ``ssvcV*`` block (CISA ADP), if any."""
    if not isinstance(metrics, dict):
        return None
    for key in sorted((k for k in metrics if k.startswith("ssvc")), reverse=True):
        for item in _dicts(metrics[key]):
            data = item.get("ssvcData")
            if not isinstance(data, dict):
                continue
            options: dict[str, object] = {}
            for option in _dicts(data.get("options")):
                options.update(option)
            found = Ssvc(
                exploitation=short(options.get("exploitation"), 40),
                automatable=short(options.get("automatable"), 40),
                technical_impact=short(options.get("technicalImpact"), 40),
                role=short(data.get("role"), 60),
                timestamp=timestamp(data.get("timestamp")),
            )
            if any(found.model_dump().values()):
                return found
    return None


def parse_cwes(weaknesses: object) -> list[str]:
    cwes: list[str] = []
    for weakness in _dicts(weaknesses):
        for item in _dicts(weakness.get("description")):
            value = item.get("value")
            if is_cwe(value) and value not in cwes:
                cwes.append(value)
    return cwes[:MAX_CWES]


def _tags(value: object) -> list[str]:
    tags = [short(tag, TAG_MAX) for tag in value] if isinstance(value, list) else []
    return [tag for tag in tags if tag][:TAGS_MAX]


def parse_references(references: object) -> tuple[list[Reference], int]:
    """Links to act on (advisories, patches) first; links tagged Exploit are never kept (R15)."""
    items = _dicts(references)
    kept: list[tuple[int, Reference]] = []
    for item in items:
        url, raw_tags = item.get("url"), item.get("tags")
        if not isinstance(url, str) or len(url) > URL_MAX or _URL.fullmatch(url) is None:
            continue
        if isinstance(raw_tags, list) and "Exploit" in raw_tags:
            continue
        tags = _tags(raw_tags)
        ranks = [REFERENCE_PRIORITY.index(tag) for tag in tags if tag in REFERENCE_PRIORITY]
        rank = min(ranks, default=len(REFERENCE_PRIORITY))
        kept.append((rank, Reference(url=url, tags=tags)))
    kept.sort(key=lambda pair: pair[0])
    return [reference for _, reference in kept[:MAX_REFERENCES]], len(items)


def _description(descriptions: object) -> tuple[str, bool] | None:
    for item in _dicts(descriptions):
        if item.get("lang") == "en" and (found := text(item.get("value"), DESCRIPTION_MAX)):
            return found
    return None


def parse_cve(cve: object, today: date) -> NvdRecord | None:
    """The record of one ``cve`` object; None when its identifier is not a valid CVE id."""
    if not isinstance(cve, dict) or not isinstance(cve.get("id"), str):
        return None
    identifier = cve_id(cve["id"], today)
    if identifier is None:
        return None
    description = _description(cve.get("descriptions"))
    references, total = parse_references(cve.get("references"))
    return NvdRecord(
        id=identifier,
        status=short(cve.get("vulnStatus"), 40),
        published=timestamp(cve.get("published")),
        last_modified=timestamp(cve.get("lastModified")),
        assigner=short(cve.get("sourceIdentifier"), 100),
        description=description[0] if description else None,
        description_truncated=description[1] if description else False,
        cvss=parse_cvss(cve.get("metrics")),
        ssvc=parse_ssvc(cve.get("metrics")),
        cwes=parse_cwes(cve.get("weaknesses")),
        references=references,
        references_total=total,
        nvd_url=DETAIL_URL + identifier,
    )


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def parse_page(body: bytes, today: date) -> NvdPage:
    """A page of the API; records whose identifier is invalid are left out."""
    data = load_json(body, "NVD")
    if not isinstance(data, dict):
        raise CyberError("NVD : réponse illisible (objet attendu)")
    total, start = _count(data.get("totalResults")), _count(data.get("startIndex", 0))
    items = data.get("vulnerabilities")
    if total is None or start is None or not isinstance(items, list):
        raise CyberError("NVD : réponse illisible (champs de pagination absents)")
    records = [r for r in (parse_cve(i.get("cve"), today) for i in _dicts(items)) if r]
    return NvdPage(total=total, start=start, records=records)


@dataclass(frozen=True)
class Published:
    records: list[NvdRecord]
    total: int
    more_available: bool
    read_at: datetime


class NvdSource:
    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    def _today(self) -> date:
        return self.fetcher.now().date()

    async def _page(self, params: Mapping[str, str | int], *, keep_empty: bool) -> Read[NvdPage]:
        today = self._today()
        return await self.fetcher.get(
            API_URL,
            params,
            lambda body: parse_page(body, today),
            # A CVE that is not published yet may be tomorrow: an empty answer is not kept.
            keep=lambda page: keep_empty or page.total > 0,
        )

    async def record(self, identifier: str) -> Read[NvdRecord | None]:
        """The record of a valid identifier; None when the NVD does not know it."""
        read = await self._page({"cveId": identifier}, keep_empty=False)
        if read.value.total == 0:
            return Read(None, read.read_at, read.cached)
        for record in read.value.records:
            if record.id == identifier:
                return Read(record, read.read_at, read.cached)
        raise CyberError("NVD : la réponse ne contient pas la fiche demandée")

    async def published(self, keyword: str, since: date, until: date) -> Published:
        """The CVEs matching ``keyword`` published in ``[since, until]``, newest last read.

        The API sorts by publication date, oldest first: when more than one page matches, the
        last page is read instead, so the newest entries are the ones returned.
        """
        params: dict[str, str | int] = {
            "keywordSearch": keyword,
            "pubStartDate": f"{since.isoformat()}T00:00:00.000Z",
            "pubEndDate": f"{until.isoformat()}T23:59:59.999Z",
            "resultsPerPage": PAGE_SIZE,
            "startIndex": 0,
        }
        read = await self._page(params, keep_empty=True)
        total, more = read.value.total, False
        if total > PAGE_SIZE:
            read = await self._page({**params, "startIndex": total - PAGE_SIZE}, keep_empty=True)
            more = True
        records = [r for r in read.value.records if _within(r.published, since, until)]
        return Published(records, total, more, read.read_at)


def _within(published: str | None, since: date, until: date) -> bool:
    """The code checks the range itself: no entry outside it is ever returned (plan, G10)."""
    return published is not None and since <= date.fromisoformat(published[:10]) <= until
