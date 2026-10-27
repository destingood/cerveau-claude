"""The fixed ranking rule (G8): KEV, then EPSS, then CVSS, then the identifier."""

from __future__ import annotations

from itertools import pairwise

from hypothesis import given
from hypothesis import strategies as st

from plugins.cyber_cve.models import Cvss, EpssScore, KevEntry, NvdRecord
from plugins.cyber_cve.priority import Found, rank, ranking_cvss

KEV = KevEntry(
    date_added="2021-12-10",
    due_date=None,
    vendor=None,
    product=None,
    name=None,
    description=None,
    required_action=None,
    ransomware=None,
    cwes=[],
)


def _cvss(score: float, version: str = "3.1", primary: bool = True) -> Cvss:
    return Cvss(
        version=version,  # type: ignore[arg-type]
        base_score=score,
        severity=None,
        vector=None,
        source=None,
        primary=primary,
    )


def _record(identifier: str, scores: list[Cvss] | None = None) -> NvdRecord:
    return NvdRecord(
        id=identifier,
        status=None,
        published=None,
        last_modified=None,
        assigner=None,
        description=None,
        description_truncated=False,
        cvss=scores or [],
        ssvc=None,
        cwes=[],
        references=[],
        references_total=0,
        nvd_url=f"https://nvd.nist.gov/vuln/detail/{identifier}",
    )


def _found(
    identifier: str, kev: bool = False, epss: float | None = None, cvss: float | None = None
) -> Found:
    return Found(
        _record(identifier, [_cvss(cvss)] if cvss is not None else None),
        "2026-10-27T09:30:00+00:00",
        KEV if kev else None,
        EpssScore(epss=epss, percentile=0.5, date="2026-10-26") if epss is not None else None,
    )


def test_the_rule_in_order() -> None:
    ranked = rank(
        [
            _found("CVE-2024-0001", cvss=10.0),
            _found("CVE-2024-0002", epss=0.01),
            _found("CVE-2024-0003", kev=True),
            _found("CVE-2024-0004", epss=0.5, cvss=5.0),
            _found("CVE-2024-0005", epss=0.5, cvss=9.0),
            _found("CVE-2024-0006"),
            _found("CVE-2024-10000", epss=0.5, cvss=9.0),
            _found("CVE-2024-9999", epss=0.5, cvss=9.0),
            _found("CVE-2024-0007", kev=True, epss=0.9),
        ]
    )
    assert [r.id for r in ranked] == [
        "CVE-2024-0007",
        "CVE-2024-0003",
        "CVE-2024-0005",
        "CVE-2024-9999",
        "CVE-2024-10000",
        "CVE-2024-0004",
        "CVE-2024-0002",
        "CVE-2024-0001",
        "CVE-2024-0006",
    ]
    assert [r.rank for r in ranked] == list(range(1, 10))
    assert ranked[2].ranking_cvss == _cvss(9.0)
    assert ranked[-1].ranking_cvss is None
    assert ranked[0].kev == KEV
    assert ranked[0].nvd_retrieved_at == "2026-10-27T09:30:00+00:00"


def test_the_ranking_score_is_the_first_published_one() -> None:
    scores = [_cvss(6.0, "4.0", primary=False), _cvss(9.8)]
    assert ranking_cvss(scores) == scores[0]
    assert ranking_cvss([]) is None


_IDS = st.integers(1000, 99999).map(lambda n: f"CVE-2024-{n}")
_ITEMS = st.lists(
    st.tuples(
        _IDS,
        st.booleans(),
        st.none() | st.floats(0, 1),
        st.none() | st.floats(0, 10),
    ),
    max_size=10,
    unique_by=lambda item: item[0],
)


Item = tuple[str, bool, float | None, float | None]


@given(_ITEMS)
def test_ranking_is_a_total_order_of_the_input(items: list[Item]) -> None:
    found = [_found(i, kev, epss, cvss) for i, kev, epss, cvss in items]
    ranked = rank(found)
    assert sorted(r.id for r in ranked) == sorted(i for i, *_ in items)
    assert rank(list(reversed(found))) == ranked
    for higher, lower in pairwise(ranked):
        assert (higher.kev is not None) >= (lower.kev is not None)
        if (higher.kev is None) == (lower.kev is None):
            if higher.epss is None:
                assert lower.epss is None
            elif lower.epss is not None:
                assert higher.epss.epss >= lower.epss.epss
