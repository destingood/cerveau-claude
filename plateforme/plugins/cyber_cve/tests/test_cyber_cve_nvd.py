"""NVD records and pages: only published values are kept, Exploit links never (R1, R15)."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from plugins.cyber_cve.common import CyberError, ResponseCache
from plugins.cyber_cve.nvd import (
    DESCRIPTION_MAX,
    NvdSource,
    parse_cve,
    parse_cvss,
    parse_cwes,
    parse_page,
    parse_references,
    parse_ssvc,
    timestamp,
)
from plugins.cyber_cve.tests.support import FIXED_NOW, FakeApi, cve, cvss_item, page, respond

TODAY = date(2026, 10, 27)


def test_a_full_record() -> None:
    record = parse_cve(cve(), TODAY)
    assert record is not None
    assert record.id == "CVE-2021-44228"
    assert record.status == "Analyzed"
    assert record.published == "2021-12-10T10:15:09"
    assert record.last_modified == "2025-02-04T15:15:13"
    assert record.assigner == "security@apache.org"
    assert record.description == "A test description of the flaw."
    assert record.description_truncated is False
    assert [(s.version, s.base_score, s.primary) for s in record.cvss] == [("3.1", 9.8, True)]
    assert record.cvss[0].severity == "CRITICAL"
    assert record.cwes == ["CWE-502"]
    assert [r.url for r in record.references] == [
        "https://vendor.example/advisory",
        "https://example.org/blog",
    ]
    assert record.references_total == 2
    assert record.nvd_url == "https://nvd.nist.gov/vuln/detail/CVE-2021-44228"
    assert record.ssvc is None


@pytest.mark.parametrize("value", [None, 42, {"id": 5}, {"id": "CVE-21-1"}, {"id": "GHSA-x"}])
def test_an_object_without_a_valid_identifier_is_dropped(value: object) -> None:
    assert parse_cve(value, TODAY) is None


def test_a_record_with_nothing_but_its_identifier() -> None:
    record = parse_cve({"id": "cve-2024-0001"}, TODAY)
    assert record is not None
    assert record.id == "CVE-2024-0001"
    assert record.description is None
    assert record.cvss == record.cwes == record.references == []
    assert record.references_total == 0


def test_the_description_is_cleaned_and_clipped() -> None:
    long = "x" * (DESCRIPTION_MAX + 50)
    record = parse_cve(cve(descriptions=[{"lang": "en", "value": long}]), TODAY)
    assert record is not None
    assert record.description is not None
    assert len(record.description) == DESCRIPTION_MAX
    assert record.description_truncated is True
    hidden = parse_cve(cve(descriptions=[{"lang": "en", "value": "a‮​b\x00c"}]), TODAY)
    assert hidden is not None
    assert hidden.description == "ab c"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2021-12-10T10:15:09.143", "2021-12-10T10:15:09"),
        ("2021-12-10T10:15:09", "2021-12-10T10:15:09"),
        ("2021-13-10T10:15:09", None),
        ("2021-12-10", None),
        (None, None),
    ],
)
def test_timestamp(value: object, expected: str | None) -> None:
    assert timestamp(value) == expected


def test_cvss_most_recent_version_first_and_primary_first() -> None:
    metrics = {
        "cvssMetricV2": [
            {
                "source": "nvd@nist.gov",
                "type": "Primary",
                "baseSeverity": "HIGH",
                "cvssData": {"version": "2.0", "vectorString": "AV:N", "baseScore": 9.3},
            }
        ],
        "cvssMetricV31": [
            cvss_item(score=10.0, source="cna@example.org", kind="Secondary"),
            cvss_item(score=9.8),
        ],
        "cvssMetricV40": [cvss_item(version="4.0", score=9.3, kind="Secondary")],
    }
    scores = parse_cvss(metrics)
    assert [(s.version, s.base_score, s.primary) for s in scores] == [
        ("4.0", 9.3, False),
        ("3.1", 9.8, True),
        ("3.1", 10.0, False),
        ("2.0", 9.3, True),
    ]
    assert scores[-1].severity == "HIGH"


@pytest.mark.parametrize(
    "item",
    [
        cvss_item(version="3.0"),
        cvss_item(score=True),
        cvss_item(score="9.8"),
        cvss_item(score=10.5),
        cvss_item(score=-1),
        {"source": "x", "type": "Primary", "cvssData": "9.8"},
        "9.8",
    ],
)
def test_a_score_that_is_not_a_published_score_is_dropped(item: Any) -> None:
    assert parse_cvss({"cvssMetricV31": [item]}) == []


def test_at_most_two_scores_per_version() -> None:
    items = [cvss_item(score=s, kind="Secondary") for s in (5.0, 6.0, 7.0)]
    assert len(parse_cvss({"cvssMetricV31": items})) == 2
    assert parse_cvss(["cvssMetricV31"]) == []


def test_ssvc_decision_points_are_merged() -> None:
    metrics = {
        "ssvcV203": [
            {"source": "x", "ssvcData": "bad"},
            {
                "source": "134c704f-9b21-4f2e-91b3-4a467353bcc0",
                "ssvcData": {
                    "timestamp": "2025-02-04T14:25:34.416117Z",
                    "options": [
                        {"exploitation": "active"},
                        {"automatable": "yes"},
                        {"technicalImpact": "total"},
                    ],
                    "role": "CISA Coordinator",
                    "version": "2.0.3",
                },
            },
        ]
    }
    ssvc = parse_ssvc(metrics)
    assert ssvc is not None
    assert (ssvc.exploitation, ssvc.automatable, ssvc.technical_impact) == (
        "active",
        "yes",
        "total",
    )
    assert ssvc.role == "CISA Coordinator"
    assert ssvc.timestamp == "2025-02-04T14:25:34"
    assert parse_ssvc({"ssvcV203": [{"ssvcData": {"options": []}}]}) is None
    assert parse_ssvc(None) is None


def test_cwes_are_checked_and_deduplicated() -> None:
    weaknesses = [
        {"description": [{"value": "CWE-502"}, {"value": "CWE-502"}, {"value": "NVD-CWE-noinfo"}]},
        {"description": [{"value": "<script>"}, {"value": "CWE-20 "}, {"value": 20}]},
        "CWE-1",
    ]
    assert parse_cwes(weaknesses) == ["CWE-502", "NVD-CWE-noinfo"]
    many = [{"description": [{"value": f"CWE-{n}"} for n in range(15)]}]
    assert len(parse_cwes(many)) == 10


def test_references_exclude_exploits_and_bad_links() -> None:
    refs = [
        {"url": "https://example.org/poc", "tags": ["Exploit", "Third Party Advisory"]},
        {"url": "https://example.org/a b", "tags": []},
        {"url": "javascript:alert(1)", "tags": ["Patch"]},
        {"url": "https://examplе.org/x", "tags": ["Patch"]},
        {"url": "https://example.org/" + "a" * 500, "tags": ["Patch"]},
        {"url": 5, "tags": ["Patch"]},
        {"url": "https://example.org/mailing", "tags": ["Mailing List"]},
        {"url": "https://example.org/mitigation", "tags": ["Mitigation"]},
        {"url": "https://example.org/patch", "tags": ["Patch", "Vendor Advisory"]},
        {"url": "http://example.org/plain"},
    ]
    kept, total = parse_references(refs)
    assert [r.url for r in kept] == [
        "https://example.org/patch",
        "https://example.org/mitigation",
        "https://example.org/mailing",
        "http://example.org/plain",
    ]
    assert kept[0].tags == ["Patch", "Vendor Advisory"]
    assert kept[-1].tags == []
    assert total == len(refs)


_TAGS = st.lists(
    st.sampled_from(["Exploit", "Patch", "Vendor Advisory", "Mitigation", "Issue Tracking", 3]),
    max_size=4,
)


@given(st.lists(st.fixed_dictionaries({"url": st.just("https://e.org/x"), "tags": _TAGS})))
def test_no_exploit_link_ever_and_at_most_ten(refs: list[dict[str, Any]]) -> None:
    kept, total = parse_references(refs)
    assert total == len(refs)
    assert len(kept) == min(10, sum("Exploit" not in r["tags"] for r in refs))
    assert all("Exploit" not in r.tags for r in kept)


def test_a_page_and_its_invalid_records() -> None:
    body = page(cve(), cve("CVE-2021-45046"), total=3)
    body["vulnerabilities"] += [{"cve": {"id": "nope"}}, "x", {"other": 1}]
    found = parse_page(_json(body), TODAY)
    assert found.total == 3
    assert found.start == 0
    assert [r.id for r in found.records] == ["CVE-2021-44228", "CVE-2021-45046"]


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"totalResults": -1, "vulnerabilities": []},
        {"totalResults": True, "vulnerabilities": []},
        {"totalResults": 1},
        {"vulnerabilities": []},
        {"totalResults": 1, "startIndex": "0", "vulnerabilities": []},
    ],
)
def test_a_page_without_its_pagination_is_refused(body: Any) -> None:
    with pytest.raises(CyberError, match="NVD : réponse illisible"):
        parse_page(_json(body), TODAY)


def _json(body: Any) -> bytes:
    return json.dumps(body).encode("utf-8")


# ---------------------------------------------------------------------------------------------
# The source


def _source(api: FakeApi, directory: Path) -> NvdSource:
    cache = ResponseCache(directory / "cache", now=lambda: FIXED_NOW)
    return NvdSource(api.fetcher(directory, cache=cache))


def test_record_asks_for_one_identifier(tmp_path: Path) -> None:
    api = FakeApi(lambda _: respond(page(cve())))
    read = asyncio.run(_source(api, tmp_path).record("CVE-2021-44228"))
    assert read.value is not None
    assert read.value.id == "CVE-2021-44228"
    assert read.read_at == FIXED_NOW
    assert api.params() == {"cveId": "CVE-2021-44228"}
    assert api.requests[0].url.path == "/rest/json/cves/2.0"


def test_an_unknown_identifier_is_none_and_not_cached(tmp_path: Path) -> None:
    api = FakeApi(lambda _: respond(page()))
    source = _source(api, tmp_path)
    for _ in range(2):
        assert asyncio.run(source.record("CVE-2026-99999")).value is None
    assert len(api.requests) == 2


def test_a_known_record_is_cached(tmp_path: Path) -> None:
    api = FakeApi(lambda _: respond(page(cve())))
    source = _source(api, tmp_path)
    asyncio.run(source.record("CVE-2021-44228"))
    assert asyncio.run(source.record("CVE-2021-44228")).cached is True
    assert len(api.requests) == 1


def test_a_reply_for_another_identifier_is_refused(tmp_path: Path) -> None:
    api = FakeApi(lambda _: respond(page(cve("CVE-2021-45046"))))
    with pytest.raises(CyberError, match="ne contient pas la fiche demandée"):
        asyncio.run(_source(api, tmp_path).record("CVE-2021-44228"))


def _published(identifier: str, when: str) -> dict[str, Any]:
    return cve(identifier, published=when)


def test_published_sends_the_range_and_filters_it(tmp_path: Path) -> None:
    body = page(
        _published("CVE-2026-1001", "2026-10-01T08:00:00.000"),
        _published("CVE-2026-1002", "2026-09-30T23:59:59.000"),
        _published("CVE-2026-1003", "2026-10-27T10:00:00.000"),
        _published("CVE-2026-1004", "2026-10-28T00:00:00.000"),
        cve("CVE-2026-1005", published=None),
    )
    api = FakeApi(lambda _: respond(body))
    found = asyncio.run(
        _source(api, tmp_path).published("log4j", date(2026, 10, 1), date(2026, 10, 27))
    )
    assert [r.id for r in found.records] == ["CVE-2026-1001", "CVE-2026-1003"]
    assert found.total == 5
    assert found.more_available is False
    assert found.read_at == FIXED_NOW
    assert api.params() == {
        "keywordSearch": "log4j",
        "pubStartDate": "2026-10-01T00:00:00.000Z",
        "pubEndDate": "2026-10-27T23:59:59.999Z",
        "resultsPerPage": "20",
        "startIndex": "0",
    }


def test_published_reads_the_last_page_when_there_are_more(tmp_path: Path) -> None:
    def answer(request: Any) -> Any:
        start = int(request.url.params["startIndex"])
        when = "2026-10-20T08:00:00.000"
        return respond(page(_published("CVE-2026-2000", when), total=45, start=start))

    api = FakeApi(answer)
    found = asyncio.run(
        _source(api, tmp_path).published("openssl", date(2026, 10, 1), date(2026, 10, 27))
    )
    assert [api.params(i)["startIndex"] for i in range(2)] == ["0", "25"]
    assert found.total == 45
    assert found.more_available is True


def test_published_keeps_even_an_empty_range_in_cache(tmp_path: Path) -> None:
    api = FakeApi(lambda _: respond(page()))
    source = _source(api, tmp_path)
    for _ in range(2):
        found = asyncio.run(source.published("x", date(2026, 10, 1), date(2026, 10, 27)))
        assert found.records == []
    assert len(api.requests) == 1
