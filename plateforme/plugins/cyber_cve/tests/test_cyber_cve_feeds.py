"""The CISA KEV catalogue and the EPSS scores of FIRST."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from plugins.cyber_cve.common import CyberError, ResponseCache
from plugins.cyber_cve.epss import EpssSource, parse_scores
from plugins.cyber_cve.kev import FEED_URL, KevSource, parse_catalog
from plugins.cyber_cve.tests.support import (
    FIXED_NOW,
    FakeApi,
    epss_body,
    epss_item,
    kev_feed,
    kev_item,
    respond,
)

TODAY = date(2026, 10, 27)


def _json(body: Any) -> bytes:
    return json.dumps(body).encode("utf-8")


def test_a_catalogue_entry() -> None:
    catalog = parse_catalog(_json(kev_feed(kev_item())), TODAY)
    assert catalog.version == "2026.10.26"
    assert catalog.released == "2026-10-26T15:00:00.0000Z"
    entry = catalog.entries["CVE-2021-44228"]
    assert entry.date_added == "2021-12-10"
    assert entry.due_date == "2021-12-24"
    assert entry.vendor == "Apache"
    assert entry.product == "Log4j2"
    assert entry.ransomware == "Known"
    assert entry.required_action == "Apply updates per vendor instructions."
    assert entry.cwes == ["CWE-917", "CWE-20"]
    assert "notes" not in entry.model_dump()


def test_invalid_entries_are_skipped_and_the_first_duplicate_wins() -> None:
    feed = kev_feed(
        kev_item("CVE-2024-0001", vendorProject="Premier"),
        kev_item("CVE-2024-0001", vendorProject="Second"),
        kev_item("CVE-24-1"),
        kev_item("CVE-2024-0002", dateAdded="hier"),
        kev_item("CVE-2024-0003", dueDate=None, cwes="CWE-1", vendorProject="a‮b" * 80),
        "x",
    )
    entries = parse_catalog(_json(feed), TODAY).entries
    assert sorted(entries) == ["CVE-2024-0001", "CVE-2024-0003"]
    assert entries["CVE-2024-0001"].vendor == "Premier"
    third = entries["CVE-2024-0003"]
    assert third.due_date is None
    assert third.cwes == []
    assert third.vendor is not None
    assert len(third.vendor) == 100
    assert "‮" not in third.vendor


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ([], "liste des vulnérabilités absente"),
        ({"vulnerabilities": {}}, "liste des vulnérabilités absente"),
        ({"vulnerabilities": []}, "catalogue vide ou illisible"),
        ({"vulnerabilities": [{"cveID": "x"}]}, "catalogue vide ou illisible"),
        ({"count": 2, "vulnerabilities": [kev_item()]}, "catalogue tronqué"),
    ],
)
def test_an_unreadable_catalogue_is_refused(body: Any, message: str) -> None:
    with pytest.raises(CyberError, match=message):
        parse_catalog(_json(body), TODAY)


def test_the_catalogue_is_read_once_a_day(tmp_path: Path) -> None:
    api = FakeApi(lambda _: respond(kev_feed(kev_item())))
    cache = ResponseCache(tmp_path / "cache", now=lambda: FIXED_NOW)
    source = KevSource(api.fetcher(tmp_path, label="KEV", cache=cache))
    first = asyncio.run(source.catalog())
    second = asyncio.run(source.catalog())
    assert (first.cached, second.cached) == (False, True)
    assert len(api.requests) == 1
    (request,) = api.requests
    assert request.headers["host"] == "www.cisa.gov"
    assert str(request.url).endswith(FEED_URL.removeprefix("https://www.cisa.gov"))


def test_scores_by_identifier() -> None:
    body = epss_body(
        epss_item(),
        epss_item("CVE-2021-44228", epss="0.1"),
        epss_item("CVE-2024-0001", epss=0.5, percentile=0.75),
        epss_item("CVE-2024-0002", epss="1.5"),
        epss_item("CVE-2024-0003", percentile=None),
        epss_item("bad"),
        {"cve": "CVE-2024-0004", "epss": "0.2", "percentile": "0.3", "date": "x"},
        "x",
    )
    scores = parse_scores(_json(body), TODAY)
    assert sorted(scores) == ["CVE-2021-44228", "CVE-2024-0001"]
    first = scores["CVE-2021-44228"]
    assert (first.epss, first.percentile, first.date) == (0.94358, 0.99961, "2026-10-26")
    assert scores["CVE-2024-0001"].epss == 0.5


@pytest.mark.parametrize("body", [[], {"status": "OK"}, {"data": "none"}])
def test_an_answer_without_scores_is_refused(body: Any) -> None:
    with pytest.raises(CyberError, match="EPSS : réponse illisible"):
        parse_scores(_json(body), TODAY)


def test_one_request_for_all_identifiers_and_only_those_kept(tmp_path: Path) -> None:
    body = epss_body(epss_item(), epss_item("CVE-2024-0009"))
    api = FakeApi(lambda _: respond(body))
    source = EpssSource(api.fetcher(tmp_path, label="EPSS"))
    read = asyncio.run(source.scores(["CVE-2021-44228", "CVE-2021-45046"]))
    assert sorted(read.value) == ["CVE-2021-44228"]
    assert read.read_at == FIXED_NOW
    assert api.params() == {"cve": "CVE-2021-44228,CVE-2021-45046"}
    assert api.requests[0].headers["host"] == "api.first.org"
    assert api.requests[0].url.path == "/data/v1/epss"
