"""The MCP server and its GitHub client, called in process; GitHub answers through
``httpx.MockTransport`` (support.py), so no request leaves the machine."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult

from core.code.repos import RepoError
from core.config.loader import CodeRepository
from core.registry.manifest import validate_plugin
from plugins.code_ci import server as server_module
from plugins.code_ci.github import (
    ACCEPT,
    API_VERSION,
    DEFAULT_WAIT_S,
    MAX_WAIT_S,
    USER_AGENT,
    GitHub,
    Pause,
    by_conclusion,
    iso,
    parse_runs,
    rate_of,
    utcnow,
    wait_of,
)
from plugins.code_ci.server import build_server
from plugins.code_ci.tests.support import (
    EXHAUSTED,
    FIXED_NOW,
    GITHUB,
    INJECTION,
    NOW_S,
    OTHER_SHA,
    RATE,
    RESET_S,
    SCENARIOS,
    SHA,
    TOKEN,
    Clock,
    FakeApi,
    a_run,
    allow_lists,
    page,
    respond,
)
from tests.code_support import listed
from tests.conftest import REPO_ROOT

PLUGIN = Path(__file__).resolve().parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
(SPEC,) = MANIFEST["tools"]
RUNS_PATH = f"/repos/{GITHUB}/actions/runs"


def run(server: Any, action: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def text(result: CallToolResult) -> str:
    return " ".join(getattr(block, "text", "") for block in result.content)


def data(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error, text(result)
    assert result.structured_content is not None
    return result.structured_content


def call(
    api: FakeApi,
    tmp_path: Path,
    arguments: Mapping[str, Any] | None = None,
    allow: Sequence[CodeRepository] | None = None,
    clock: Clock | None = None,
    **options: Any,
) -> CallToolResult:
    repositories = allow_lists(tmp_path / "exemple")["exemple"] if allow is None else allow
    github = api.github(tmp_path / "net", clock, **options)
    server = build_server(lambda: repositories, github, lambda: FIXED_NOW)
    return run(server, lambda c: c.call_tool("ci_runs", {"repo": "exemple", **(arguments or {})}))


def scenario(
    name: str, tmp_path: Path, arguments: Mapping[str, Any] | None = None, allow: str = "exemple"
) -> tuple[CallToolResult, FakeApi]:
    api = FakeApi(SCENARIOS[name])
    return call(api, tmp_path, arguments, allow_lists(tmp_path / "exemple")[allow]), api


def answering(*runs: Mapping[str, Any]) -> FakeApi:
    return FakeApi(lambda _: respond(page(*runs), headers=RATE))


def pause_file(tmp_path: Path) -> Path:
    return tmp_path / "net" / "github-pause.until"


# --- the manifest -----------------------------------------------------------------------------


def test_the_plugin_passes_the_registry() -> None:
    report = validate_plugin(PLUGIN)
    assert report.ok, report.errors
    assert report.plugin_id == "code_ci"


def test_the_published_tool_matches_the_manifest(tmp_path: Path) -> None:
    server = build_server(lambda: (), FakeApi(SCENARIOS["mixte"]).github(tmp_path))
    (tool,) = run(server, lambda c: c.list_tools()).tools
    assert tool.name == SPEC["name"] == "ci_runs"
    assert SPEC["action_class"] == "LECTURE"
    assert tool.description == SPEC["description"]
    assert tool.annotations.model_dump(by_alias=True, exclude_none=True) == SPEC["annotations"]
    for kind, schema in (
        ("input_schema", tool.input_schema),
        ("output_schema", tool.output_schema),
    ):
        on_disk = json.loads((PLUGIN / SPEC[kind]).read_text(encoding="utf-8"))
        on_disk.pop("$schema")
        assert schema == on_disk, f"{SPEC[kind]} is stale: regenerate it from the server"


# --- the request ------------------------------------------------------------------------------


def test_one_tokenless_get_of_the_listed_repository(tmp_path: Path) -> None:
    _, api = scenario("mixte", tmp_path)
    (request,) = api.requests
    assert request.method == "GET"
    assert (request.url.scheme, request.url.host, request.url.path) == (
        "https",
        "api.github.com",
        RUNS_PATH,
    )
    assert dict(request.url.params) == {"per_page": "10", "exclude_pull_requests": "true"}
    assert request.headers["user-agent"] == USER_AGENT
    assert request.headers["accept"] == ACCEPT
    assert request.headers["x-github-api-version"] == API_VERSION
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers


def test_a_branch_and_a_count_are_passed_on(tmp_path: Path) -> None:
    _, api = scenario("mixte", tmp_path, {"branch": "feature/ci-2.0", "max_runs": 3})
    (request,) = api.requests
    assert dict(request.url.params) == {
        "per_page": "3",
        "exclude_pull_requests": "true",
        "branch": "feature/ci-2.0",
    }


def test_proxies_and_tokens_of_the_environment_are_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("GH_TOKEN", TOKEN)
    result, api = scenario("mixte", tmp_path)
    assert data(result)["total_count"] == 57
    (request,) = api.requests
    assert "authorization" not in request.headers
    assert TOKEN not in str(request.url) + str(request.headers)


# --- what comes back --------------------------------------------------------------------------


def test_the_runs_are_read_and_counted(tmp_path: Path) -> None:
    result, _ = scenario("mixte", tmp_path)
    shown = data(result)
    assert {key: shown[key] for key in ("repo", "github", "branch", "total_count")} == {
        "repo": "exemple",
        "github": GITHUB,
        "branch": None,
        "total_count": 57,
    }
    assert [run["id"] for run in shown["runs"]] == [103, 102, 101]
    assert shown["by_conclusion"] == {"en_cours": 1, "failure": 1, "success": 1}
    assert shown["rate"] == {"limit": 60, "remaining": 57, "reset_at": "2026-10-22T10:00:00Z"}
    assert shown["retrieved_at"] == "2026-10-22T09:30:00Z"
    assert shown["runs"][1] == {
        "id": 102,
        "run_number": 42,
        "run_attempt": 1,
        "workflow": "CI",
        "event": "pull_request",
        "status": "completed",
        "conclusion": "failure",
        "branch": "essai",
        "head_sha": OTHER_SHA,
        "title": "Ajoute la lecture des runs",
        "created_at": "2026-10-21T18:02:11Z",
        "updated_at": "2026-10-21T18:05:40Z",
        "url": f"https://github.com/{GITHUB}/actions/runs/102",
    }
    assert (shown["runs"][0]["status"], shown["runs"][0]["conclusion"]) == ("in_progress", None)


def test_no_more_runs_than_asked_are_shown(tmp_path: Path) -> None:
    result, _ = scenario("mixte", tmp_path, {"max_runs": 2})
    shown = data(result)
    assert [run["id"] for run in shown["runs"]] == [103, 102]
    assert shown["total_count"] == 57
    assert shown["by_conclusion"] == {"en_cours": 1, "failure": 1}


def test_an_empty_history(tmp_path: Path) -> None:
    result, _ = scenario("vide", tmp_path)
    shown = data(result)
    assert (shown["total_count"], shown["runs"], shown["by_conclusion"]) == (0, [], {})


def test_the_link_is_built_never_taken_from_the_answer(tmp_path: Path) -> None:
    api = answering(a_run(html_url="https://piege.example/x", url="https://piege.example/y"))
    shown = json.dumps(data(call(api, tmp_path)), ensure_ascii=False)
    assert f'"url": "https://github.com/{GITHUB}/actions/runs/101"' in shown
    assert "piege" not in shown


def test_untrusted_texts_are_data_with_their_invisible_characters_shown(tmp_path: Path) -> None:
    result, _ = scenario("injection", tmp_path)
    (shown,) = data(result)["runs"]
    assert shown["title"] == INJECTION
    assert shown["workflow"] == "C⟨U+202E⟩i"
    assert shown["branch"] == "ma⟨U+200B⟩in"


def test_secrets_in_titles_are_masked(tmp_path: Path) -> None:
    result, _ = scenario("secret", tmp_path)
    (shown,) = data(result)["runs"]
    assert shown["title"] == "Ajoute le jeton [MASQUÉ]"
    assert TOKEN not in json.dumps(data(result))


def test_long_texts_are_clipped(tmp_path: Path) -> None:
    api = answering(a_run(display_title="mot " * 100, name="n" * 300, head_branch="b" * 300))
    (shown,) = data(call(api, tmp_path))["runs"]
    assert (len(shown["title"]), len(shown["workflow"]), len(shown["branch"])) == (200, 100, 200)
    assert shown["title"].endswith("…")


def test_odd_states_are_marked_not_standard(tmp_path: Path) -> None:
    result, _ = scenario("non_standard", tmp_path)
    (shown,) = data(result)["runs"]
    assert (shown["status"], shown["conclusion"]) == ("non standard", "non standard")
    assert "<b>" not in json.dumps(shown)
    assert data(result)["by_conclusion"] == {"non standard": 1}


def test_absent_fields_stay_absent(tmp_path: Path) -> None:
    api = answering(
        a_run(name=None, head_branch=None, run_attempt=None, status=None, conclusion=None)
    )
    shown = data(call(api, tmp_path))
    (only,) = shown["runs"]
    assert (only["workflow"], only["branch"], only["run_attempt"], only["status"]) == (
        None,
        None,
        None,
        None,
    )
    assert shown["by_conclusion"] == {"en_cours": 1}


def test_without_counters_no_rate_is_shown(tmp_path: Path) -> None:
    result, _ = scenario("secret", tmp_path)
    assert data(result)["rate"] is None


def test_the_conclusions_are_counted_most_frequent_first() -> None:
    runs = [
        a_run(1, conclusion="success"),
        a_run(2, conclusion="failure"),
        a_run(3, conclusion="success"),
        a_run(4, status="queued", conclusion=None),
        a_run(5, conclusion="cancelled"),
    ]
    _, parsed = parse_runs(page(*runs), GITHUB, 20)
    assert list(by_conclusion(parsed).items()) == [
        ("success", 2),
        ("cancelled", 1),
        ("en_cours", 1),
        ("failure", 1),
    ]


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (RATE, (60, 57, RESET_S)),
        ({**RATE, "x-ratelimit-remaining": " 7 "}, (60, 7, RESET_S)),
        ({key: value for key, value in RATE.items() if key != "x-ratelimit-reset"}, None),
        ({**RATE, "x-ratelimit-limit": "soixante"}, None),
        ({**RATE, "x-ratelimit-reset": "1" * 11}, None),
        ({**RATE, "x-ratelimit-remaining": "-1"}, None),
        ({}, None),
    ],
)
def test_the_counters_of_github(headers: dict[str, str], expected: Any) -> None:
    rate = rate_of(httpx.Headers(headers))
    assert (None if rate is None else (rate.limit, rate.remaining, rate.reset)) == expected


def test_the_retrieval_time_is_utc() -> None:
    assert utcnow().utcoffset() == timedelta(0)
    assert iso(RESET_S) == "2026-10-22T10:00:00Z"


# --- unreadable answers -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"head_sha": "main"}, "head_sha"),
        ({"head_sha": SHA.upper()}, "head_sha"),
        ({"created_at": "hier"}, "created_at"),
        ({"updated_at": "2026-10-21 18:05:40"}, "updated_at"),
        ({"id": True}, "id"),
        ({"id": -1}, "id"),
        ({"id": None}, "id"),
        ({"run_number": "42"}, "run_number"),
        ({"run_attempt": 1.5}, "run_attempt"),
        ({"event": 5}, "event"),
        ({"event": None}, "event"),
        ({"status": ["completed"]}, "status"),
        ({"display_title": None}, "display_title"),
        ({"name": {"x": 1}}, "name"),
    ],
)
def test_an_odd_run_is_refused_whole(fields: dict[str, Any], field: str, tmp_path: Path) -> None:
    result = call(answering(a_run(), a_run(102, **fields)), tmp_path)
    assert result.is_error
    assert f"GitHub : run illisible (champ « {field} »)" in text(result)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"{pas du json", "réponse illisible (JSON invalide)"),
        (b"\xff\xfe\x00", "réponse illisible (JSON invalide)"),
        (b"[]", "réponse illisible"),
        (
            b'{"total_count": true, "workflow_runs": []}',
            "réponse illisible (total_count ou workflow_runs)",
        ),
        (
            b'{"total_count": "3", "workflow_runs": []}',
            "réponse illisible (total_count ou workflow_runs)",
        ),
        (
            b'{"total_count": 3, "workflow_runs": {}}',
            "réponse illisible (total_count ou workflow_runs)",
        ),
        (b'{"workflow_runs": []}', "réponse illisible (total_count ou workflow_runs)"),
        (b'{"total_count": 1, "workflow_runs": ["run"]}', "run illisible"),
    ],
)
def test_an_odd_body_is_refused(body: bytes, message: str, tmp_path: Path) -> None:
    result = call(FakeApi(lambda _: respond(body)), tmp_path)
    assert result.is_error
    assert f"GitHub : {message}" in text(result)


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (
            respond(b'{"message": "Not Found"}', 404),
            f"dépôt GitHub « {GITHUB} » introuvable, privé ou sans Actions (aucun jeton, E6)",
        ),
        (
            respond(b"", 301, headers={"location": "https://exemple.org/"}),
            "redirection refusée : dépôt renommé ou déplacé ? corriger github dans "
            "config/code.yaml",
        ),
        (respond(b"", 503), "service indisponible (HTTP 503)"),
        (respond(b"", 401), "réponse HTTP 401 inattendue"),
        (respond(b"", 204), "réponse HTTP 204 inattendue"),
        (respond(b"<html></html>", content_type="text/html"), "réponse qui n'est pas du JSON"),
        (respond(page(), content_type=None), "réponse qui n'est pas du JSON"),
        (respond(page(), headers={"content-encoding": "br"}), "encodage « br » non pris en"),
    ],
)
def test_other_answers_are_errors_without_pause(
    answer: httpx.Response, message: str, tmp_path: Path
) -> None:
    api = FakeApi(lambda _: answer)
    result = call(api, tmp_path)
    assert result.is_error
    assert f"GitHub : {message}" in text(result)
    assert len(api.requests) == 1
    assert "exemple.org" not in text(result)
    assert not pause_file(tmp_path).exists()


def test_a_body_too_big_is_refused(tmp_path: Path) -> None:
    result = call(FakeApi(SCENARIOS["mixte"]), tmp_path, max_bytes=1_000)
    assert result.is_error
    assert "GitHub : page trop volumineuse" in text(result)


def test_a_slow_answer_is_cut_at_the_time_limit(tmp_path: Path) -> None:
    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return respond(page())

    result = call(FakeApi(slow), tmp_path, timeout_s=0.05)
    assert result.is_error
    assert "GitHub : délai de 0.05 s dépassé" in text(result)


def test_a_failed_connection(tmp_path: Path) -> None:
    result, _ = scenario("coupure", tmp_path)
    assert result.is_error
    assert text(result).endswith("GitHub : connexion impossible")
    assert "refused" not in text(result)


# --- GitHub's rate limits ---------------------------------------------------------------------


def test_an_exhausted_window_holds_every_request_until_its_reset(tmp_path: Path) -> None:
    clock = Clock()
    first = call(FakeApi(SCENARIOS["limite"]), tmp_path, clock=clock)
    assert first.is_error
    assert (
        "GitHub : limite de 60 requêtes par heure de GitHub atteinte (HTTP 403) : aucune "
        "requête avant 2026-10-22T10:00:00Z"
    ) in text(first)
    assert pause_file(tmp_path).exists()

    held = FakeApi(SCENARIOS["mixte"])
    clock.now = NOW_S + 600
    second = call(held, tmp_path, clock=clock)
    assert second.is_error
    assert "GitHub : limite de débit, aucune requête envoyée ; réessayer dans 1200 s" in text(
        second
    )
    assert held.requests == []

    clock.now = RESET_S
    assert data(call(held, tmp_path, clock=clock))["total_count"] == 57
    assert len(held.requests) == 1


def test_a_secondary_limit_waits_as_github_asks(tmp_path: Path) -> None:
    clock = Clock()
    first = call(FakeApi(SCENARIOS["secondaire"]), tmp_path, clock=clock)
    assert "requête refusée par GitHub (HTTP 429) : aucune requête pendant 30 s" in text(first)
    held = FakeApi(SCENARIOS["mixte"])
    assert "réessayer dans 30 s" in text(call(held, tmp_path, clock=clock))
    assert held.requests == []


def test_a_refusal_without_hint_waits_one_minute(tmp_path: Path) -> None:
    first = call(FakeApi(lambda _: respond(b"{}", 403)), tmp_path)
    assert "requête refusée par GitHub (HTTP 403) : aucune requête pendant 60 s" in text(first)
    assert Pause(pause_file(tmp_path), Clock()).left() == DEFAULT_WAIT_S


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (EXHAUSTED, 1_800.0),
        (EXHAUSTED | {"x-ratelimit-reset": str(int(NOW_S) - 5)}, 1.0),
        (EXHAUSTED | {"x-ratelimit-reset": str(int(NOW_S) + 90_000)}, MAX_WAIT_S),
        (EXHAUSTED | {"retry-after": "5"}, 1_800.0),
        (RATE | {"retry-after": "30"}, 30.0),
        (RATE | {"retry-after": "0"}, 1.0),
        (RATE | {"retry-after": "99999"}, MAX_WAIT_S),
        (RATE | {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}, DEFAULT_WAIT_S),
        ({"retry-after": "12"}, 12.0),
        ({}, DEFAULT_WAIT_S),
    ],
)
def test_the_wait_github_asks_for(headers: dict[str, str], expected: float) -> None:
    sent = httpx.Headers(headers)
    assert wait_of(sent, rate_of(sent), NOW_S) == expected


def test_no_pause_means_no_wait(tmp_path: Path) -> None:
    assert Pause(tmp_path / "absent" / "github-pause.until", Clock()).left() == 0.0


def test_a_pause_is_shared_through_its_file(tmp_path: Path) -> None:
    path = tmp_path / "net" / "github-pause.until"
    clock = Clock()
    assert Pause(path, clock).hold(90.0) == 90.0
    assert sorted(p.name for p in path.parent.iterdir()) == ["github-pause.until"]
    assert Pause(path, clock).left() == 90.0
    clock.now += 100
    assert Pause(path, clock).left() == 0.0


@pytest.mark.parametrize(
    "content",
    [b"demain", b"\xff\xfe", b"nan", repr(NOW_S + 2 * MAX_WAIT_S).encode()],
    ids=["texte", "octets", "nan", "trop_loin"],
)
def test_a_damaged_pause_waits_one_minute(content: bytes, tmp_path: Path) -> None:
    path = tmp_path / "github-pause.until"
    path.write_bytes(content)
    clock = Clock()
    assert Pause(path, clock).left() == DEFAULT_WAIT_S
    assert float(path.read_text(encoding="ascii")) == NOW_S + DEFAULT_WAIT_S


# --- the allow list ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("allow", "repo", "message"),
    [
        ("vide", "exemple", "aucun dépôt autorisé : la liste blanche des dépôts est vide (E2)"),
        ("exemple", "inconnu", "dépôt « inconnu » non autorisé : liste blanche = exemple"),
        ("cerveau", "cerveau", "dépôt « cerveau » : recouvre le dépôt CERVEAU (ADR-047)"),
        (
            "sans_github",
            "exemple",
            "dépôt « exemple » : aucun dépôt GitHub associé (champ github de config/code.yaml)",
        ),
    ],
)
def test_refusals_send_no_request(allow: str, repo: str, message: str, tmp_path: Path) -> None:
    result, api = scenario("mixte", tmp_path, {"repo": repo}, allow)
    assert result.is_error
    assert message in text(result)
    assert api.requests == []


@pytest.mark.parametrize(
    "path", [REPO_ROOT / "plugins", REPO_ROOT.parent], ids=["dedans", "autour"]
)
def test_a_repository_overlapping_cerveau_is_refused(path: Path, tmp_path: Path) -> None:
    api = FakeApi(SCENARIOS["mixte"])
    result = call(api, tmp_path, allow=[listed("exemple", path, github=GITHUB)])
    assert "recouvre le dépôt CERVEAU (ADR-047)" in text(result)
    assert api.requests == []


def test_an_invalid_configuration_is_reported_without_detail(tmp_path: Path) -> None:
    def broken() -> Sequence[CodeRepository]:
        raise RepoError("configuration invalide : lancer `cerveau config check`")

    api = FakeApi(SCENARIOS["mixte"])
    server = build_server(broken, api.github(tmp_path), lambda: FIXED_NOW)
    result = run(server, lambda c: c.call_tool("ci_runs", {"repo": "exemple"}))
    assert result.is_error
    assert "configuration invalide : lancer `cerveau config check`" in text(result)
    assert api.requests == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"repo": "Exemple"},
        {"repo": "C:/Users/User/Documents/projet"},
        {"branch": "-x"},
        {"branch": "a b"},
        {"branch": "x" * 101},
        {"branch": "main?per_page=100"},
        {"max_runs": 0},
        {"max_runs": 21},
    ],
)
def test_invalid_arguments_send_no_request(arguments: dict[str, Any], tmp_path: Path) -> None:
    result, api = scenario("mixte", tmp_path, arguments)
    assert result.is_error
    assert "validation" in text(result)
    assert api.requests == []


# --- start-up ---------------------------------------------------------------------------------


def test_main_wires_the_allow_list_and_a_tokenless_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    built: list[Any] = []

    class Stub:
        def run(self) -> None:
            built.append("run")

    def fake_build(repositories: Any, github: Any) -> Stub:
        built.extend([repositories, github])
        return Stub()

    loaded: list[Path] = []
    monkeypatch.setenv("CERVEAU_HOME", str(tmp_path))
    monkeypatch.setattr(server_module, "build_server", fake_build)
    monkeypatch.setattr(server_module, "load_repositories", lambda d: loaded.append(d) or ())
    server_module.main()
    repositories, github, ran = built
    assert repositories() == ()
    assert loaded == [tmp_path / "config"]
    assert isinstance(github, GitHub)
    assert github.transport is None
    assert github.pause.path == tmp_path / "var" / "net" / "github-pause.until"
    assert ran == "run"


# --- golden set -------------------------------------------------------------------------------


GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]


@pytest.mark.parametrize("case", GOLDEN, ids=[case["id"] for case in GOLDEN])
def test_golden_cases(case: dict[str, Any], tmp_path: Path) -> None:
    """Offline: GitHub answers as the case's scenario says, for the case's allow list."""
    result, _ = scenario(
        case.get("scenario", "mixte"), tmp_path, case["arguments"], case.get("allowlist", "exemple")
    )
    expected = case["expected"]
    assert result.is_error is expected["is_error"]
    shown = text(result) if result.is_error else json.dumps(data(result), ensure_ascii=False)
    assert expected["contains"] in shown
    for absent in expected.get("absent", []):
        assert absent not in shown


def test_the_golden_set_never_holds_the_example_secret() -> None:
    raw = (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8")
    assert TOKEN not in raw
    assert len(GOLDEN) >= 20
