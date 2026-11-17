"""Fixtures of the Cyber pack's evals (ADR-057): the fake NVD, KEV and EPSS a case describes,
served to the real cyber_cve server, and the ATT&CK index the real cyber_attack server reads.

Every request goes through ``httpx.MockTransport`` after a fake DNS that names a public address,
under rate limits that never wait and without a cache: no request leaves the machine. The ATT&CK
index is built from the synthetic bundle of ``core/evals/attack_sample.py`` in the run's
temporary home, and its digest is recorded in a copy of the configuration: nothing is written
under ``var/`` or ``config/`` of the repository, and the real bundle is never read.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from core.cyber.attack import index_path, write_index
from core.cyber.fetch import SOURCES_FILE, _attack_block, record_sha256
from core.evals.attack_sample import SAMPLE, VERSION, build, bundle, sha256_of, technique
from core.evals.cases import CveFixture, CyberFixture, CyberSource, EpssFixture, KevFixture
from core.net.throttle import SharedThrottle
from plugins.cyber_attack.server import IndexReader
from plugins.cyber_cve import kev
from plugins.cyber_cve.common import HOSTS, MAX_BYTES, Fetcher
from plugins.cyber_cve.epss import EpssSource
from plugins.cyber_cve.kev import KevSource
from plugins.cyber_cve.nvd import NvdSource
from plugins.cyber_cve.server import Sources
from plugins.cyber_cve.settings import config_gate

NVD_HOST = "services.nvd.nist.gov"
KEV_HOST = "www.cisa.gov"
EPSS_HOST = "api.first.org"
SOURCE_OF_HOST: dict[str, CyberSource] = {NVD_HOST: "nvd", KEV_HOST: "kev", EPSS_HOST: "epss"}
# The NVD key the client sends when a case says so: a canary, never in an answer or a log (R6).
STAND_IN_NVD_KEY = "canari-nvd-cle-factice"
PUBLIC_V4 = "93.184.215.14"  # the address of every source name, so the network guard lets it be
_METRICS = {"4.0": "cvssMetricV40", "3.1": "cvssMetricV31", "3.0": "cvssMetricV30"}
# A digest already recorded (the user ran attack-fetch): the copy puts the marker back.
_RECORDED = re.compile(rb"^(    sha256: )[0-9a-f]{64}([ \t]*(?:#[^\r\n]*)?\r?\n)", re.M)
_VECTORS = {
    "4.0": "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N",
    "2.0": "AV:N/AC:L/Au:N/C:P/I:P/A:P",
}


async def _no_sleep(_: float) -> None:
    await asyncio.sleep(0)


async def _chunks(body: bytes, size: int = 64 * 1024) -> AsyncIterator[bytes]:
    """A streamed body: the plugin reads it in parts and stops past its limit."""
    for start in range(0, len(body), size):
        yield body[start : start + size]


def _respond(data: Any, status: int = 200) -> httpx.Response:
    body = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
    headers = {"content-type": "application/json"}
    return httpx.Response(status, headers=headers, content=_chunks(body))


async def _resolve(host: str, port: int) -> Sequence[str]:
    if host not in HOSTS:
        raise OSError("name not found")
    return [PUBLIC_V4]


def nvd_item(record: CveFixture) -> dict[str, Any]:
    """A CVE as the NVD API 2.0 writes it in ``vulnerabilities[].cve``."""
    metrics: dict[str, list[dict[str, Any]]] = {}
    for score in record.cvss:
        vector = _VECTORS.get(
            score.version, f"CVSS:{score.version}/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
        )
        data: dict[str, Any] = {
            "version": score.version,
            "vectorString": vector,
            "baseScore": score.score,
        }
        item: dict[str, Any] = {
            "source": score.source,
            "type": "Primary" if score.primary else "Secondary",
            "cvssData": data,
        }
        if score.version == "2.0":  # version 2 writes its severity beside cvssData
            item["baseSeverity"] = score.severity
        else:
            data["baseSeverity"] = score.severity
        metrics.setdefault(_METRICS.get(score.version, "cvssMetricV2"), []).append(item)
    found: dict[str, Any] = {
        "id": record.id,
        "sourceIdentifier": record.assigner,
        "published": record.published,
        "lastModified": record.last_modified,
        "vulnStatus": record.status,
        "descriptions": [{"lang": "en", "value": record.description}],
        "metrics": metrics,
        "references": [
            {"url": r.url, "source": record.assigner, "tags": list(r.tags)}
            for r in record.references
        ],
    }
    if record.cwes:
        found["weaknesses"] = [
            {"source": "nvd@nist.gov", "description": [{"lang": "en", "value": c}]}
            for c in record.cwes
        ]
    return found


def kev_item(entry: KevFixture) -> dict[str, Any]:
    return {
        "cveID": entry.id,
        "vendorProject": entry.vendor,
        "product": entry.product,
        "vulnerabilityName": entry.name,
        "dateAdded": entry.date_added.isoformat(),
        "shortDescription": entry.description,
        "requiredAction": entry.required_action,
        "dueDate": entry.due_date.isoformat(),
        "knownRansomwareCampaignUse": entry.ransomware,
        "notes": entry.notes,
        "cwes": list(entry.cwes),
    }


def epss_item(score: EpssFixture) -> dict[str, Any]:
    return {
        "cve": score.id,
        "epss": score.epss,
        "percentile": score.percentile,
        "date": score.day.isoformat(),
    }


def _page(items: list[dict[str, Any]], total: int, start: int) -> dict[str, Any]:
    return {
        "resultsPerPage": len(items),
        "startIndex": start,
        "totalResults": total,
        "format": "NVD_CVE",
        "version": "2.0",
        "timestamp": "2026-10-18T11:59:00.000",
        "vulnerabilities": [{"cve": item} for item in items],
    }


def _day(raw: str | None) -> date | None:
    try:
        return date.fromisoformat(raw[:10]) if raw else None
    except ValueError:
        return None


class FixtureApis:
    """The NVD, KEV and EPSS of one case, routed on the ``Host`` header (the URL carries the
    pinned address); a source the case lists as down answers HTTP 503, one listed as oversized
    answers one byte more than the plugin reads."""

    def __init__(self, fixture: CyberFixture) -> None:
        self.fixture = fixture
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        source = SOURCE_OF_HOST.get(request.headers.get("host", ""))
        if source is None:
            return _respond({"message": "not found"}, 404)
        # The key goes to the NVD only, and only when the case gives one (R6): a key that is
        # missing, wrong or sent elsewhere is refused.
        wanted = STAND_IN_NVD_KEY if source == "nvd" and self.fixture.nvd_key else None
        if request.headers.get("apikey") != wanted:
            return _respond({"message": "forbidden"}, 403)
        if source in self.fixture.down:
            return _respond({"message": "service unavailable"}, 503)
        if source in self.fixture.oversized:
            limit = kev.MAX_BYTES if source == "kev" else MAX_BYTES
            return _respond(b" " * (limit + 1))
        params = dict(request.url.params)
        if source == "kev":
            return _respond(self._catalog())
        if source == "epss":
            wanted = set(params.get("cve", "").split(","))
            items = [epss_item(e) for e in self.fixture.epss if e.id in wanted]
            return _respond(
                {"status": "OK", "status-code": 200, "total": len(items), "data": items}
            )
        return _respond(self._nvd(params))

    def _catalog(self) -> dict[str, Any]:
        return {
            "title": "CISA Catalog of Known Exploited Vulnerabilities",
            "catalogVersion": self.fixture.kev_version,
            "dateReleased": f"{self.fixture.kev_version.replace('.', '-')}T15:00:00.0000Z",
            "count": len(self.fixture.kev),
            "vulnerabilities": [kev_item(entry) for entry in self.fixture.kev],
        }

    def _nvd(self, params: dict[str, str]) -> dict[str, Any]:
        records = {record.id: record for record in self.fixture.nvd}
        if "cveId" in params:
            found = records.get(params["cveId"])
            return _page([nvd_item(found)] if found else [], 1 if found else 0, 0)
        word = params.get("keywordSearch", "").casefold()
        ids = next((v for k, v in self.fixture.searches.items() if k.casefold() == word), ())
        start, end = _day(params.get("pubStartDate")), _day(params.get("pubEndDate"))
        matched = [
            records[i]
            for i in ids
            if start is not None
            and end is not None
            and start <= date.fromisoformat(records[i].published[:10]) <= end
        ]
        first = int(params.get("startIndex", 0))
        size = int(params.get("resultsPerPage", 20))
        shown = matched[first : first + size]
        return _page([nvd_item(record) for record in shown], len(matched), first)


def cyber_config(source: Path, folder: Path) -> Path:
    """A copy of the configuration files the case may change (the ATT&CK digest), never the
    original. A digest the user has recorded goes back to its marker in the copy: the case records
    the digest of its own bundle, whatever the repository holds."""
    target = folder / "config"
    if not target.exists():
        target.mkdir(parents=True)
        for path in source.glob("*.yaml"):
            shutil.copyfile(path, target / path.name)
        sources = target / SOURCES_FILE
        text = sources.read_bytes()
        begin, end = _attack_block(text)
        block = _RECORDED.sub(rb"\g<1>A_VERIFIER\g<2>", text[begin:end])
        sources.write_bytes(text[:begin] + block + text[end:])
    return target


def cyber_sources(
    fixture: CyberFixture, folder: Path, config_dir: Path, now: Callable[[], datetime]
) -> Sources:
    """The cyber_cve sources of a case: the real clients and parsers on its fake APIs."""
    apis = FixtureApis(fixture)
    transport = httpx.MockTransport(apis)

    def fetcher(label: str, **options: Any) -> Fetcher:
        throttle = SharedThrottle(folder / "net", label.lower(), 0.0, sleep=_no_sleep)
        return Fetcher(label, throttle, transport=transport, resolver=_resolve, now=now, **options)

    products = folder / "sources.yaml"
    if fixture.products:
        products.write_text(
            yaml.safe_dump({"produits_suivis": list(fixture.products)}, allow_unicode=True),
            encoding="utf-8",
        )
    return Sources(
        NvdSource(
            fetcher("NVD", headers={"apiKey": STAND_IN_NVD_KEY} if fixture.nvd_key else None)
        ),
        KevSource(fetcher("KEV", max_bytes=kev.MAX_BYTES)),
        EpssSource(fetcher("EPSS")),
        gate=config_gate(config_dir),
        products_file=products,
        now=now,
    )


def attack_reader(fixture: CyberFixture, folder: Path, config_dir: Path) -> IndexReader:
    """The cyber_attack reader of a case: an index of the synthetic bundle in ``folder`` whose
    digest the configuration records (present), records otherwise (altered) or not at all."""
    if fixture.attack != "absent" and not index_path(folder, VERSION).exists():
        objects = [
            *SAMPLE,
            *(
                technique(t.id, t.name, t.tactic, description=t.description)
                for t in fixture.techniques
            ),
        ]
        index, _report = build(objects)
        path = index_path(folder, VERSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_index(path, index)
        body = bundle(objects)
        record_sha256(config_dir, sha256_of(body if fixture.attack == "present" else body + b"\n"))
    return IndexReader(folder, config_dir)
