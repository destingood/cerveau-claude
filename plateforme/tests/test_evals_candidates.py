"""The candidate golden cases awaiting the user's review (B62): loadable, never run, never frozen.

R9: a golden set is never edited to make something pass, and a case is frozen only once the user
has validated it. The candidates therefore sit beside the general golden set, in
``candidats.jsonl``, which no suite reads; these tests only check that each one would load as a
golden case the day the user keeps it, without clashing with a case already there.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

import pytest

from core.evals.cases import GOLDEN_FILE, Case, golden_files, load_cases, load_web
from core.evals.offline import FIXTURE_NOW
from tests.conftest import REPO_ROOT

CANDIDATES = GOLDEN_FILE.with_name("candidats.jsonl")
FICTITIOUS_HOST = re.compile(r"(^|\.)(example|example\.(com|org|net))$")


def _candidates() -> list[Case]:
    path = REPO_ROOT / CANDIDATES
    if not path.is_file():  # every candidate reviewed: nothing left to check
        pytest.skip("aucun cas candidat en attente de validation")
    pack = GOLDEN_FILE.parent.parent.name
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [
        Case.model_validate({"suite": "golden", "group": pack, **json.loads(line)})
        for line in lines
    ]


def test_each_candidate_loads_as_a_golden_case() -> None:
    cases = _candidates()
    assert cases
    web = load_web()
    for case in cases:
        served = {page.url for page in case.pages} | set(web)
        assert all(hit.url in served for hit in case.search_hits()), case.id
        assert case.expect.key_points, case.id  # what the judge looks for
        hosts = {urlsplit(page.url).hostname or "" for page in case.pages}
        assert all(FICTITIOUS_HOST.search(host) for host in hosts), case.id
        days = [page.published for page in case.pages if page.published]
        assert all(day <= FIXTURE_NOW.date().isoformat() for day in days), case.id  # R10


def test_the_candidates_never_clash_with_the_suites() -> None:
    ids = [case.id for case in _candidates()]
    assert len(ids) == len(set(ids))
    existing = {
        case.id for suite in ("golden", "behaviors", "injection") for case in load_cases(suite)
    }
    assert not set(ids) & existing


def test_the_candidates_are_never_run_with_the_golden_set() -> None:
    _candidates()
    assert CANDIDATES not in golden_files()
