"""Deterministic ranking of CVEs (G8, R1): no threshold, no weight, no score computed here.

KEV listing first, then the EPSS of FIRST, then the published CVSS base score, then the
identifier. A missing value comes after every known one, so an unscored CVE is never ranked
above a scored one by accident.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from plugins.cyber_cve.common import cve_order
from plugins.cyber_cve.models import CveRecord, Cvss, EpssScore, KevEntry, NvdRecord


def ranking_cvss(scores: Sequence[Cvss]) -> Cvss | None:
    """The score of the most recent published version, the primary one first (the list order)."""
    return scores[0] if scores else None


def rank_key(
    identifier: str, in_kev: bool, epss: float | None, cvss: float | None
) -> tuple[bool, bool, float, bool, float, tuple[int, int]]:
    return (
        not in_kev,
        epss is None,
        -epss if epss is not None else 0.0,
        cvss is None,
        -cvss if cvss is not None else 0.0,
        cve_order(identifier),
    )


@dataclass(frozen=True)
class Found:
    record: NvdRecord
    retrieved_at: str
    kev: KevEntry | None
    epss: EpssScore | None


def rank(found: Sequence[Found]) -> list[CveRecord]:
    def key(item: Found) -> tuple[bool, bool, float, bool, float, tuple[int, int]]:
        best = ranking_cvss(item.record.cvss)
        return rank_key(
            item.record.id,
            item.kev is not None,
            item.epss.epss if item.epss else None,
            best.base_score if best else None,
        )

    return [
        CveRecord(
            **item.record.model_dump(),
            rank=position,
            ranking_cvss=ranking_cvss(item.record.cvss),
            nvd_retrieved_at=item.retrieved_at,
            kev=item.kev,
            epss=item.epss,
        )
        for position, item in enumerate(sorted(found, key=key), start=1)
    ]
