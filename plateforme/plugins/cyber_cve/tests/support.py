"""Offline doubles for the cyber_cve tests: a fake API behind ``httpx.MockTransport`` reached
through a fake DNS, a rate limiter that never sleeps, and builders of NVD, KEV and EPSS answers
(shapes taken from the real answers of 2026-10-27, texts invented).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from core.net.throttle import SharedThrottle
from plugins.cyber_cve.common import HOSTS, Fetcher
from tests.net_doubles import PUBLIC_V4, FakeDns, chunks

FIXED_NOW = datetime(2026, 10, 27, 9, 30, tzinfo=UTC)
STAMP = "2026-10-27T09:30:00+00:00"
JSON_TYPE = "application/json"


async def no_sleep(_: float) -> None:
    await asyncio.sleep(0)


def respond(
    body: bytes | str | Any = b"", status: int = 200, content_type: str | None = JSON_TYPE
) -> httpx.Response:
    if isinstance(body, str):
        data = body.encode("utf-8")
    elif isinstance(body, bytes):
        data = body
    else:
        data = json.dumps(body).encode("utf-8")
    headers = {"content-type": content_type} if content_type else {}
    return httpx.Response(status, headers=headers, content=chunks(data))


Handler = Callable[[httpx.Request], Awaitable[httpx.Response] | httpx.Response]


@dataclass
class FakeApi:
    """Answers every request with ``handler`` and keeps the requests for inspection."""

    handler: Handler
    requests: list[httpx.Request] = field(default_factory=list)
    dns: FakeDns = field(default_factory=lambda: FakeDns({h: [PUBLIC_V4] for h in HOSTS}))

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        result = self.handler(request)
        return await result if isinstance(result, Awaitable) else result

    def fetcher(self, directory: Path, label: str = "NVD", **options: Any) -> Fetcher:
        throttle = SharedThrottle(directory, label.lower(), 0.0, sleep=no_sleep)
        options.setdefault("now", lambda: FIXED_NOW)
        options.setdefault("resolver", self.dns)
        return Fetcher(label, throttle, transport=httpx.MockTransport(self), **options)

    def params(self, index: int = -1) -> dict[str, str]:
        return dict(self.requests[index].url.params)


def static(body: Any, status: int = 200) -> FakeApi:
    return FakeApi(lambda _: respond(body, status))


def cvss_item(
    version: str = "3.1",
    score: Any = 9.8,
    source: str = "nvd@nist.gov",
    kind: str = "Primary",
    severity: str = "CRITICAL",
) -> dict[str, Any]:
    return {
        "source": source,
        "type": kind,
        "cvssData": {
            "version": version,
            "vectorString": f"CVSS:{version}/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            "baseScore": score,
            "baseSeverity": severity,
        },
    }


def cve(identifier: str = "CVE-2021-44228", **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": identifier,
        "sourceIdentifier": "security@apache.org",
        "published": "2021-12-10T10:15:09.143",
        "lastModified": "2025-02-04T15:15:13.773",
        "vulnStatus": "Analyzed",
        "descriptions": [
            {"lang": "es", "value": "Una descripción de prueba."},
            {"lang": "en", "value": "A test description of the flaw."},
        ],
        "metrics": {"cvssMetricV31": [cvss_item()]},
        "weaknesses": [{"source": "nvd@nist.gov", "description": [{"value": "CWE-502"}]}],
        "references": [
            {"url": "https://example.org/blog", "source": "x", "tags": ["Third Party Advisory"]},
            {"url": "https://vendor.example/advisory", "source": "x", "tags": ["Vendor Advisory"]},
        ],
    }
    base.update(overrides)
    return {key: value for key, value in base.items() if value is not None}


def page(*cves: dict[str, Any], total: int | None = None, start: int = 0) -> dict[str, Any]:
    return {
        "resultsPerPage": len(cves),
        "startIndex": start,
        "totalResults": len(cves) if total is None else total,
        "format": "NVD_CVE",
        "version": "2.0",
        "timestamp": "2026-10-27T09:29:00.000",
        "vulnerabilities": [{"cve": item} for item in cves],
    }


def kev_item(identifier: str = "CVE-2021-44228", **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "cveID": identifier,
        "vendorProject": "Apache",
        "product": "Log4j2",
        "vulnerabilityName": "Apache Log4j2 Remote Code Execution Vulnerability",
        "dateAdded": "2021-12-10",
        "shortDescription": "A test summary.",
        "requiredAction": "Apply updates per vendor instructions.",
        "dueDate": "2021-12-24",
        "knownRansomwareCampaignUse": "Known",
        "notes": "https://example.org/notes",
        "cwes": ["CWE-917", "CWE-20", "CWE-917"],
    }
    base.update(overrides)
    return {key: value for key, value in base.items() if value is not None}


def kev_feed(*items: dict[str, Any], version: str = "2026.10.26") -> dict[str, Any]:
    return {
        "title": "CISA Catalog of Known Exploited Vulnerabilities",
        "catalogVersion": version,
        "dateReleased": "2026-10-26T15:00:00.0000Z",
        "count": len(items),
        "vulnerabilities": list(items),
    }


def epss_item(
    identifier: str = "CVE-2021-44228", epss: Any = "0.94358", percentile: Any = "0.99961"
) -> dict[str, Any]:
    return {"cve": identifier, "epss": epss, "percentile": percentile, "date": "2026-10-26"}


def epss_body(*items: dict[str, Any]) -> dict[str, Any]:
    return {"status": "OK", "status-code": 200, "total": len(items), "data": list(items)}
