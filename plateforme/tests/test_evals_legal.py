"""The Juridique FR pack's offline evals (ADR-060): the fake Légifrance API, the configuration copy
naming its PISTE environment, and the honest planner's answer on what the real tools read."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from core.audit.chain import AuditJournal
from core.budget.gate import RequestBudget
from core.config import load_config
from core.config.loader import PerRequest
from core.evals.cases import Case, LegalFixture, LegiVersionFixture
from core.evals.legifrance_fixtures import (
    PUBLIC_V4,
    STAND_IN_ID,
    STAND_IN_SECRET,
    STAND_IN_TOKEN,
    FixturePiste,
    legal_config,
    legal_sources,
)
from core.evals.offline import (
    FIXTURE_NOW,
    LEGAL_COUNTER,
    LEGAL_STEPS,
    LEGAL_UNSURE,
    _from_legal,
    legal_toolboxes,
    uses_cyber,
    uses_finance,
    uses_legal,
)
from core.mcp.adapter import RequestScope
from core.models import CostCalculator, Meter
from plugins.legifrance.client import API_PATH, MAX_BYTES, OAUTH_PATH, LegiError
from plugins.legifrance.server import article, search
from tests.conftest import REPO_ROOT

CONFIG = load_config(REPO_ROOT / "config")
LIMITS = PerRequest(max_tool_calls=25, max_tokens=150000, max_seconds=120)
CIVIL = "LEGITEXT000006070721"
IN_FORCE = LegiVersionFixture(
    id="LEGIARTI000032041571",
    num="1240",
    text_id=CIVIL,
    title="Code civil",
    start=date(2016, 10, 1),
    text="Texte d'essai inventé : tout fait qui cause un dommage oblige à le réparer.",
)
FORMER = IN_FORCE.model_copy(
    update={
        "id": "LEGIARTI000006438819",
        "start": date(1804, 2, 19),
        "end": date(2016, 10, 1),
        "state": "MODIFIE",
    }
)


def _fixture(**fields: Any) -> LegalFixture:
    return LegalFixture(versions=(IN_FORCE, FORMER), searches={"dommage": (IN_FORCE.id,)}, **fields)


def _now() -> Any:
    return FIXTURE_NOW


def _sources(fixture: LegalFixture, folder: Path) -> Any:
    return legal_sources(fixture, folder, legal_config(REPO_ROOT / "config", folder, fixture), _now)


def _call(piste: FixturePiste, host: str, path: str, body: bytes, **headers: str) -> httpx.Response:
    request = httpx.Request("POST", f"https://{PUBLIC_V4}{path}", content=body, headers=headers)
    request.headers["host"] = host
    response = piste(request)
    asyncio.run(response.aread())  # the body is streamed, as the real API streams it
    return response


# --- fake API ----------------------------------------------------------------------------------


def test_the_fake_api_routes_on_the_host_and_wants_the_stand_in_credentials() -> None:
    piste = FixturePiste(_fixture(), FIXTURE_NOW.date())
    assert _call(piste, "example.org", "/", b"{}").status_code == 404
    form = f"grant_type=client_credentials&client_id={STAND_IN_ID}&client_secret=autre"
    assert _call(piste, "oauth.piste.gouv.fr", OAUTH_PATH, form.encode()).status_code == 401
    good = form.replace("autre", STAND_IN_SECRET).encode()
    token = _call(piste, "oauth.piste.gouv.fr", OAUTH_PATH, good)
    assert token.json()["access_token"] == STAND_IN_TOKEN
    path = API_PATH + "/consult/getArticle"
    asked = json.dumps({"id": IN_FORCE.id}).encode()
    assert _call(piste, "api.piste.gouv.fr", path, asked).status_code == 401
    bearer = {"authorization": f"Bearer {STAND_IN_TOKEN}"}
    found = _call(piste, "api.piste.gouv.fr", path, asked, **bearer).json()["article"]
    assert found["id"] == IN_FORCE.id and found["cid"] == FORMER.id  # the earliest version
    unknown = _call(piste, "api.piste.gouv.fr", API_PATH + "/autre", b"{}", **bearer)
    assert unknown.status_code == 404


def test_a_down_or_oversized_api_answers_503_or_a_byte_past_its_limit() -> None:
    bearer = {"authorization": f"Bearer {STAND_IN_TOKEN}"}
    path = API_PATH + "/search"
    down = FixturePiste(_fixture(down=True), FIXTURE_NOW.date())
    assert _call(down, "api.piste.gouv.fr", path, b"{}", **bearer).status_code == 503
    big = FixturePiste(_fixture(oversized=True), FIXTURE_NOW.date())
    assert len(_call(big, "api.piste.gouv.fr", path, b"{}", **bearer).content) == MAX_BYTES + 1


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"versions": (IN_FORCE, IN_FORCE)}, "identifiant"),
        ({"searches": {"x": ("LEGIARTI000000000001",)}}, "LEGIARTI000000000001"),
        ({"swapped": {IN_FORCE.id: "LEGIARTI000000000001"}}, "LEGIARTI000000000001"),
    ],
)
def test_an_inconsistent_fixture_is_refused(fields: dict[str, Any], reason: str) -> None:
    with pytest.raises(ValidationError, match=reason):
        LegalFixture.model_validate(fields)


def test_a_version_ending_before_it_starts_is_refused() -> None:
    with pytest.raises(ValidationError, match="fin avant le début"):
        IN_FORCE.model_validate({**IN_FORCE.model_dump(), "end": date(2000, 1, 1)})


# --- configuration copy ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("environment", "url"),
    [
        ("sandbox", "https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app"),
        ("production", "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app"),
        ("A_DEFINIR", "A_DEFINIR"),
    ],
)
def test_the_copy_names_the_case_environment_and_leaves_the_repository_alone(
    tmp_path: Path, environment: str, url: str
) -> None:
    original = (REPO_ROOT / "config" / "data_sources.yaml").read_bytes()
    copy = legal_config(REPO_ROOT / "config", tmp_path, LegalFixture(environment=environment))
    assert load_config(copy).data_sources.sources["legifrance"].url == url
    assert (REPO_ROOT / "config" / "data_sources.yaml").read_bytes() == original


def test_a_configuration_without_legifrance_block_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data_sources.yaml").write_text("sources:\n  autre:\n    url: x\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"bloc sources.legifrance absent"):
        legal_config(source, tmp_path / "copie", LegalFixture())


# --- the real tools on the fake API ------------------------------------------------------------


def test_the_real_tools_read_the_version_of_the_day_and_of_a_past_date(tmp_path: Path) -> None:
    sources = _sources(_fixture(), tmp_path)
    today = asyncio.run(article(sources, None, CIVIL, "1240", None))
    assert today.id == IN_FORCE.id and today.covers_reference_date
    past = asyncio.run(article(sources, None, CIVIL, "1240", "2010-01-01"))
    assert past.id == FORMER.id and past.covers_reference_date  # the version of that day
    later = asyncio.run(article(sources, IN_FORCE.id, None, None, "2010-01-01"))
    assert not later.covers_reference_date and later.version_for_date == FORMER.id
    found = asyncio.run(search(sources, "dommage", "CODE_ETAT", None, 5))
    assert [item.article_id for item in found.items] == [IN_FORCE.id]


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"environment": "A_DEFINIR"}, "data.legifrance"),
        ({"credentials": False}, "identifiants PISTE absents"),
        ({"down": True}, "HTTP 503"),
        ({"oversized": True}, "trop volumineuse"),
        ({"swapped": {IN_FORCE.id: FORMER.id}}, "réponse refusée"),
    ],
)
def test_each_failure_of_the_api_is_reported(
    tmp_path: Path, fields: dict[str, Any], reason: str
) -> None:
    sources = _sources(_fixture(**fields), tmp_path)
    with pytest.raises(Exception, match=reason) as raised:
        asyncio.run(article(sources, IN_FORCE.id, None, None, None))
    assert isinstance(raised.value, LegiError) or "data.legifrance" in str(raised.value)


def _scope(root: Path) -> RequestScope:
    meter = Meter(CostCalculator(CONFIG.pricing))
    return RequestScope(
        request_id="req-test",
        domain="juridique_fr",
        autonomy=CONFIG.autonomy,
        journal=AuditJournal(root / "audit" / "journal.jsonl"),
        budget=RequestBudget(LIMITS, meter, clock=lambda: 0.0),
        meter=meter,
        project_root=root,
        live_enabled=False,
    )


def test_the_toolbox_serves_the_real_server_behind_the_adapter(tmp_path: Path) -> None:
    case = _case(legal=_fixture().model_dump())
    opener = legal_toolboxes(case, tmp_path, REPO_ROOT / "config", _now)["legifrance"]

    async def go() -> dict[str, Any]:
        async with opener(_scope(tmp_path)) as toolbox:
            return await toolbox.call("legi_article", {"text_id": CIVIL, "num": "1240"})

    assert asyncio.run(go())["id"] == IN_FORCE.id
    assert (tmp_path / "juridique" / "config" / "data_sources.yaml").exists()


# --- which cases are legal ---------------------------------------------------------------------


def _case(**fields: Any) -> Case:
    return Case.model_validate(
        {
            "id": "cas-de-test",
            "suite": "golden",
            "group": "juridique_fr",
            "description": "d",
            "question": "Que dit l'article 1240 du code civil ?",
            **fields,
        }
    )


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"legal": {}}, True),
        ({"expect": {"tools": ["legi_article"]}}, True),
        ({}, False),
    ],
)
def test_a_case_uses_the_legal_server_by_its_fixture_or_its_tools(
    fields: dict[str, Any], expected: bool
) -> None:
    case = _case(**fields)
    assert uses_legal(case) is expected
    assert not uses_cyber(case)
    if expected:
        assert not uses_finance(case)


# --- the honest planner's answer ---------------------------------------------------------------


def _view(data: Any, tool: str) -> str:
    return f'<donnees_externes source="{tool}#1">\n{json.dumps(data)}\n</donnees_externes>'


def _read(tmp_path: Path, date_: str | None = None, **fields: Any) -> str:
    sources = _sources(_fixture(**fields), tmp_path)
    found = asyncio.run(article(sources, IN_FORCE.id, None, None, date_))
    return _view(found.model_dump(mode="json"), "legi_article")


def test_no_result_is_a_plain_i_do_not_know() -> None:
    answer = _from_legal([], complex_=True)
    assert answer["synthese"].startswith(LEGAL_UNSURE)
    assert answer["confiance"]["niveau"] == "faible"
    assert answer["contre_arguments"] == LEGAL_COUNTER
    assert answer["prochaines_etapes"] == list(LEGAL_STEPS)


def test_an_unavailable_tool_is_said_and_never_acted_on() -> None:
    view = "Erreur : l'outil « legi_deposer » n'est pas disponible."
    answer = _from_legal([view], complex_=False)
    assert answer["synthese"].startswith(LEGAL_UNSURE)
    assert (
        "« legi_deposer » n'est pas disponible : CERVEAU lit le droit sans agir"
        in (answer["synthese"])
    )


def test_the_article_is_cited_as_read_without_its_link(tmp_path: Path) -> None:
    answer = _from_legal([_read(tmp_path)], complex_=False)
    head = (
        "Article 1240 (Code civil), version LEGIARTI000032041571, état VIGUEUR, "
        "depuis le 2016-10-01 (legi_article)."
    )
    assert answer["synthese"].startswith(head)
    assert answer["confiance"]["niveau"] == "eleve"
    assert "Cette version couvre la date de référence." in answer["developpement"]
    assert "legifrance.gouv.fr" not in answer["synthese"] + answer["developpement"]


def test_a_version_not_covering_the_date_lowers_the_confidence(tmp_path: Path) -> None:
    answer = _from_legal([_read(tmp_path, "2010-01-01")], complex_=False)
    assert answer["confiance"]["niveau"] == "moyen"
    assert "ne couvre pas la date de référence" in answer["developpement"]
    assert f"Version qui s'applique à cette date : {FORMER.id}." in answer["developpement"]


def test_a_search_names_its_articles_and_an_empty_one_does_not_know(tmp_path: Path) -> None:
    sources = _sources(_fixture(), tmp_path)
    found = asyncio.run(search(sources, "dommage", "CODE_ETAT", None, 5))
    answer = _from_legal([_view(found.model_dump(mode="json"), "legi_search")], complex_=False)
    assert answer["synthese"].startswith("Recherche Légifrance « dommage » : article 1240")
    nothing = asyncio.run(search(sources, "rien", "CODE_ETAT", None, 5))
    empty = _from_legal([_view(nothing.model_dump(mode="json"), "legi_search")], complex_=False)
    assert empty["synthese"].startswith(LEGAL_UNSURE)
    assert "Légifrance ne trouve rien pour « rien » (legi_search)." in empty["synthese"]


def test_a_failed_call_is_said_without_its_numbers() -> None:
    error = "legi_article : Légifrance : service indisponible (HTTP 503)"
    view = (
        'Erreur de l\'outil :\n<donnees_externes source="legi_article (erreur)">\n'
        f"{error}\n</donnees_externes>"
    )
    answer = _from_legal([view], complex_=False)
    assert answer["synthese"].startswith(LEGAL_UNSURE)
    assert "service indisponible" in answer["synthese"] and "503" not in answer["synthese"]


def test_unreadable_or_foreign_results_are_ignored() -> None:
    views = [
        '<donnees_externes source="legi_article#1">\n{oops\n</donnees_externes>',
        _view([1, 2], "legi_article"),
        _view({"id": "x"}, "cve_lookup"),
    ]
    assert _from_legal(views, complex_=False)["synthese"].startswith(LEGAL_UNSURE)
