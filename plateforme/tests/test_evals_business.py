"""The Business pack's offline evals (ADR-063): the fake API Recherche d'entreprises and Melodi
API, the real servers behind the adapter, and the honest planner's answer on their figures."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.tools import ToolException
from pydantic import ValidationError

from core.audit.chain import AuditJournal
from core.budget.gate import RequestBudget
from core.config import load_config
from core.config.loader import PerRequest
from core.evals.business_fixtures import CANARIES, PUBLIC_V4, FixtureApis
from core.evals.cases import BusinessFixture, Case
from core.evals.offline import (
    BUSINESS_COUNTER,
    BUSINESS_STEPS,
    FIXTURE_NOW,
    FinanceLog,
    _from_figures,
    business_toolboxes,
    uses_business,
    uses_finance,
    uses_legal,
)
from core.mcp.adapter import RequestScope
from core.models import CostCalculator, Meter
from tests.conftest import REPO_ROOT

CONFIG = load_config(REPO_ROOT / "config")
LIMITS = PerRequest(max_tool_calls=25, max_tokens=150000, max_seconds=120)
POPREF = "DS_POPULATIONS_REFERENCE"
COMPANY = {
    "siren": "356000000",
    "nom": "Atelier Boulangerie Essai",
    "creation": "2019-03-01",
    "commune": "LYON",
    "code_postal": "69003",
    "departement": "69",
    "finances": {"2023": {"ca": 245678, "resultat_net": -1234}},
    "mise_a_jour": "2026-10-01",
}
DATASET = {
    "updated": "2025-12-18",
    "observations": [
        {
            "dimensions": {
                "GEO": "2025-DEP-44",
                "FREQ": "A",
                "TIME_PERIOD": "2023",
                "POPREF_MEASURE": "PTOT",
            },
            "value": 1517043.0,
        }
    ],
}
VAT = {"calcul": {"operation": "tva", "montant": "100", "sens": "ht_vers_ttc", "taux": "normal"}}


def _fixture(**fields: Any) -> BusinessFixture:
    return BusinessFixture.model_validate(
        {"companies": [COMPANY], "datasets": {POPREF: DATASET}, **fields}
    )


def _get(apis: FixtureApis, host: str, path: str) -> httpx.Response:
    request = httpx.Request("GET", f"https://{PUBLIC_V4}{path}")
    request.headers["host"] = host
    response = apis(request)
    asyncio.run(response.aread())  # the body is streamed, as the real APIs stream it
    return response


# --- fake APIs ---------------------------------------------------------------------------------


def test_the_registry_finds_by_siren_or_name_and_adds_the_person_to_drop() -> None:
    apis = FixtureApis(_fixture())
    host = "recherche-entreprises.api.gouv.fr"
    found = _get(apis, host, "/search?q=356000000").json()
    assert found["total_results"] == 1
    assert found["results"][0]["dirigeants"][0]["nom"] in CANARIES  # the plugin must drop it
    assert _get(apis, host, "/search?q=boulangerie%20atelier").json()["total_results"] == 1
    assert _get(apis, host, "/search?q=boulangerie&departement=75").json()["total_results"] == 0
    assert _get(apis, "example.org", "/search?q=x").status_code == 404


def test_melodi_serves_the_data_and_catalog_of_known_datasets_only() -> None:
    apis = FixtureApis(_fixture())
    host = "api.insee.fr"
    data = _get(apis, host, f"/melodi/data/{POPREF}?GEO=DEP-44").json()
    assert data["observations"][0]["measures"]["OBS_VALUE_NIVEAU"]["value"] == 1517043.0
    catalog = _get(apis, host, f"/melodi/catalog/{POPREF}").json()
    assert catalog["modified"].startswith("2025-12-18")
    assert _get(apis, host, "/melodi/data/DS_INCONNU").status_code == 404


def test_a_down_api_answers_503() -> None:
    apis = FixtureApis(_fixture(down=["entreprises", "insee_melodi"]))
    assert _get(apis, "recherche-entreprises.api.gouv.fr", "/search?q=x").status_code == 503
    assert _get(apis, "api.insee.fr", f"/melodi/data/{POPREF}").status_code == 503


def test_a_duplicate_or_malformed_company_is_refused() -> None:
    with pytest.raises(ValidationError, match="SIREN en double"):
        BusinessFixture.model_validate({"companies": [COMPANY, COMPANY]})
    with pytest.raises(ValidationError):
        BusinessFixture.model_validate({"companies": [{**COMPANY, "departement": "2C"}]})


# --- the real servers behind the adapter -------------------------------------------------------


def _scope(root: Path) -> RequestScope:
    meter = Meter(CostCalculator(CONFIG.pricing))
    return RequestScope(
        request_id="req-test",
        domain="business",
        autonomy=CONFIG.autonomy,
        journal=AuditJournal(root / "audit" / "journal.jsonl"),
        budget=RequestBudget(LIMITS, meter, clock=lambda: 0.0),
        meter=meter,
        project_root=root,
        live_enabled=False,
    )


def _case(**fields: Any) -> Case:
    return Case.model_validate(
        {
            "id": "cas-de-test",
            "suite": "golden",
            "group": "business",
            "description": "d",
            "question": "Quel est le chiffre d'affaires de cette entreprise ?",
            **fields,
        }
    )


def _run(root: Path, case: Case, calls: list[tuple[str, str, dict[str, Any]]]) -> FinanceLog:
    log = FinanceLog()
    openers = business_toolboxes(case, root, REPO_ROOT / "config", lambda: FIXTURE_NOW, log)

    async def go() -> None:
        for plugin, tool, arguments in calls:
            async with openers[plugin](_scope(root)) as toolbox:
                with contextlib.suppress(ToolException):  # a failed call is logged: checked
                    await toolbox.call(tool, arguments)

    asyncio.run(go())
    return log


def test_the_toolboxes_serve_the_real_servers_and_log_their_figures(tmp_path: Path) -> None:
    case = _case(business=_fixture().model_dump(mode="json"))
    log = _run(
        tmp_path,
        case,
        [
            ("entreprises", "company_search", {"siren": "356000000"}),
            ("insee_stats", "stats_series", {"jeu": POPREF, "geo": "DEP-44", "periode": "2023"}),
            ("business_calc", "biz_calc", VAT),
        ],
    )
    assert log.tools() == ["company_search", "stats_series", "biz_calc"]
    assert log.display("company_search", "356000000.2023.chiffre_affaires") is not None
    assert log.display("stats_series", f"{POPREF}.A.2025-DEP-44.PTOT.2023") is not None
    assert log.display("biz_calc", "resultat.ttc") is not None
    written = json.dumps([result for _tool, result in log.results()], ensure_ascii=False)
    assert not any(canary in written for canary in CANARIES)  # I4
    assert not (tmp_path / "business" / "cache").exists()  # no cache in an eval


def test_a_down_api_is_a_logged_error_not_a_figure(tmp_path: Path) -> None:
    case = _case(business=_fixture(down=["entreprises"]).model_dump(mode="json"))
    log = _run(tmp_path, case, [("entreprises", "company_search", {"siren": "356000000"})])
    assert log.calls == []
    assert [tool for tool, _error in log.errors] == ["company_search"]


def test_the_kill_switch_stops_every_read(tmp_path: Path) -> None:
    (tmp_path / "governance" / "kill_switch").mkdir(parents=True)
    (tmp_path / "governance" / "kill_switch" / "KILL").write_text("", encoding="utf-8")
    case = _case(business=_fixture().model_dump(mode="json"))
    log = _run(tmp_path, case, [("entreprises", "company_search", {"siren": "356000000"})])
    assert log.calls == []


# --- which cases are business ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"business": {}}, True),
        ({"expect": {"tools": ["biz_calc"]}}, True),
        ({"offline": {"calls": [{"tool": "stats_series", "args": {}}]}}, True),
        ({}, False),
    ],
)
def test_a_case_uses_the_business_servers_by_its_fixture_or_its_tools(
    fields: dict[str, Any], expected: bool
) -> None:
    case = _case(**fields)
    assert uses_business(case) is expected
    assert not uses_legal(case)
    if expected:
        assert not uses_finance(case)  # never the finance store nor its date


def test_the_honest_answer_cites_each_figure_with_its_tool(tmp_path: Path) -> None:
    case = _case(
        business=_fixture().model_dump(mode="json"),
        expect={
            "tools": ["biz_calc"],
            "figures": [
                {
                    "tool": "biz_calc",
                    "id": "resultat.ttc",
                    "display": "120,00 €",
                    "label": "Prix TTC",
                }
            ],
        },
    )
    log = _run(tmp_path, case, [("business_calc", "biz_calc", VAT)])
    answer = _from_figures(case, log, [], complex_=True)
    assert "Prix TTC : 120,00 € (biz_calc)" in answer["developpement"]
    assert answer["contre_arguments"] == BUSINESS_COUNTER
    assert answer["prochaines_etapes"] == list(BUSINESS_STEPS)
