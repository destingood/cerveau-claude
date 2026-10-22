"""The offline world of the code pack's evals (core/evals/code_fixtures.py) and the honest
planner's answer on the code tools' results (core/evals/offline.py): no network, no container."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from core.code.checks import parse_pytest, parse_ruff
from core.config.loader import BlockedFeatureError
from core.evals.cases import CodeChecksFixture, CodeFixture
from core.evals.code_fixtures import (
    CERVEAU_ID,
    CODE_REPO,
    FICTITIOUS_KEY,
    FICTITIOUS_TOKEN,
    NO_DOCKER,
    REPO_IMAGE,
    FixtureDocker,
    FixtureGitHub,
    build_repo,
    code_repositories,
    filled,
    step_of,
)
from core.evals.offline import (
    AGENT_COUNTER,
    AGENT_RETRY,
    AGENT_STEPS,
    CODE_COUNTER,
    CODE_UNSURE,
    _agent_facts,
    _from_code,
    _patch_lines,
    offline_config,
)
from plugins.code_ci.github import CiError
from tests.code_support import git


def _fixture(**fields: Any) -> CodeFixture:
    return CodeFixture.model_validate(
        {"commits": [{"message": "Initial commit", "files": {"a.py": "x = 1\n"}}], **fields}
    )


def test_the_markers_become_fictitious_secrets_only_when_built() -> None:
    text = filled("TOKEN=«JETON_FICTIF»\n«CLE_PRIVEE»")
    assert text == f"TOKEN={FICTITIOUS_TOKEN}\n{FICTITIOUS_KEY}"
    assert "«" not in text


def test_the_repository_holds_the_commits_in_order_with_links_and_deletions(
    tmp_path: Path,
) -> None:
    fixture = CodeFixture.model_validate(
        {
            "commits": [
                {"message": "Initial commit", "files": {"a.py": "x = 1\n", "b.py": "y = 2\n"}},
                {
                    "message": "Add the token\n\nBody «JETON_FICTIF»",
                    "files": {"b.py": None, "s.py": "T = '«JETON_FICTIF»'\n"},
                    "links": {"docs/config": "../../outside"},
                },
            ]
        }
    )
    repo = build_repo(fixture, tmp_path / "projet")
    assert git(repo, "log", "--format=%s").splitlines() == ["Add the token", "Initial commit"]
    assert FICTITIOUS_TOKEN in git(repo, "log", "-1", "--format=%b")
    assert git(repo, "show", "HEAD:s.py") == f"T = '{FICTITIOUS_TOKEN}'\n"
    tree = git(repo, "ls-tree", "-r", "HEAD").splitlines()
    assert [line.split("\t")[1] for line in tree] == ["a.py", "docs/config", "s.py"]
    assert tree[1].startswith("120000 ")  # a symbolic link, in the index only
    assert not (repo / "docs" / "config").exists()
    assert git(repo, "show", "HEAD:docs/config") == "../../outside"


def test_the_allow_list_is_the_case_repository_with_cerveau_when_asked(tmp_path: Path) -> None:
    assert code_repositories(None, tmp_path) == ()
    (alone,) = code_repositories(_fixture(), tmp_path)
    assert (alone.id, alone.pytest, alone.image) == (CODE_REPO, False, None)
    listed = code_repositories(_fixture(pytest=True, cerveau=True), tmp_path)
    assert [repository.id for repository in listed] == [CODE_REPO, CERVEAU_ID]
    assert listed[0].image == REPO_IMAGE


def _arguments(program: str, step: str) -> list[str]:
    return ["run", "--rm", "--entrypoint", program, "sha256:image", step, "--output-format=json"]


def test_the_step_is_read_from_the_entrypoint() -> None:
    assert step_of(_arguments("ruff", "check")) == "check"
    assert step_of(_arguments("ruff", "format")) == "format"
    assert step_of(_arguments("python", "-m")) == "pytest"


def _docker(checks: CodeChecksFixture | None, step: tuple[str, str]) -> Any:
    return FixtureDocker(checks).run(_arguments(*step), name="n", timeout_s=1.0, max_bytes=1000)


def test_without_checks_every_step_answers_that_docker_is_down() -> None:
    out = _docker(None, ("ruff", "check"))
    assert (out.returncode, out.stdout) == (NO_DOCKER, b"")


def test_the_fake_docker_answers_each_step_as_the_case_says() -> None:
    checks = CodeChecksFixture.model_validate(
        {
            "lint": [{"path": "a.py", "code": "F401", "message": "unused", "row": 1, "column": 8}],
            "unformatted": ["b.py"],
            "pytest_code": 1,
            "pytest_output": "F\nFAILED t.py::test_x - assert 0\n1 failed in 0.1s\n",
            "timed_out": ["format"],
        }
    )
    (diagnostic,) = parse_ruff(_docker(checks, ("ruff", "check")).stdout)
    assert (diagnostic.path, diagnostic.code, diagnostic.line) == ("a.py", "F401", 1)
    assert _docker(checks, ("ruff", "format")).timed_out
    tests = _docker(checks, ("python", "-m"))
    assert tests.returncode == 1
    assert parse_pytest(tests.stdout).failed == ("t.py::test_x",)
    docker = FixtureDocker(checks.model_copy(update={"docker": 125}))
    assert docker.run(_arguments("ruff", "check"), name="n", timeout_s=1.0, max_bytes=9).returncode
    assert docker.steps == ["check"]


def test_the_fake_github_lists_the_runs_newest_first_and_filters_a_branch() -> None:
    fixture = _fixture(
        runs=[
            {"title": "Fix", "conclusion": "failure"},
            {"title": "Feature", "branch": "feature"},
            {"title": "Initial commit"},
        ],
        total_runs=40,
    )
    github = FixtureGitHub(fixture)
    body, rate = asyncio.run(github.runs("lucas-exemple/projet", None, 2))
    data = json.loads(body)
    assert rate is None
    assert data["total_count"] == 40
    assert [run["display_title"] for run in data["workflow_runs"]] == ["Fix", "Feature"]
    assert [run["run_number"] for run in data["workflow_runs"]] == [3, 2]
    body, _ = asyncio.run(github.runs("lucas-exemple/projet", "feature", 5))
    assert [run["head_branch"] for run in json.loads(body)["workflow_runs"]] == ["feature"]
    assert github.asked == [
        ("lucas-exemple/projet", None, 2),
        ("lucas-exemple/projet", "feature", 5),
    ]


@pytest.mark.parametrize(
    ("fixture", "reason"),
    [(None, "introuvable, privé ou sans Actions"), (_fixture(ci_status=403), "HTTP 403")],
)
def test_the_fake_github_refuses_as_the_api_would(fixture: CodeFixture | None, reason: str) -> None:
    with pytest.raises(CiError, match=reason):
        asyncio.run(FixtureGitHub(fixture).runs("lucas-exemple/projet", None, 5))


def _view(data: dict[str, Any], tool: str = "run_checks") -> str:
    return f'<donnees_externes source="{tool}#1">\n{json.dumps(data)}\n</donnees_externes>'


def _checks(**statuses: str) -> dict[str, Any]:
    return {
        "repo": "projet",
        **{key: {"status": status} for key, status in statuses.items()},
    }


@pytest.mark.parametrize(
    ("statuses", "level"),
    [
        ({"ruff_check": "ok", "ruff_format": "ok", "pytest": "echec"}, "eleve"),
        ({"ruff_check": "ok", "ruff_format": "delai", "pytest": "non_lance"}, "moyen"),
        ({"ruff_check": "erreur", "ruff_format": "erreur", "pytest": "erreur"}, "faible"),
        ({"ruff_check": "delai", "ruff_format": "delai", "pytest": "delai"}, "faible"),
    ],
)
def test_the_confidence_follows_what_the_checks_concluded(
    statuses: dict[str, str], level: str
) -> None:
    answer = _from_code([_view(_checks(**statuses))], complex_=False)
    assert answer["confiance"]["niveau"] == level
    assert answer["synthese"].startswith("Contrôles de projet : ")


def test_no_usable_result_is_a_plain_i_do_not_know() -> None:
    answer = _from_code(["Erreur : l'outil « git_push » n'est pas disponible."], complex_=True)
    assert answer["synthese"].startswith(CODE_UNSURE)
    assert answer["confiance"]["niveau"] == "faible"
    assert answer["prochaines_etapes"]  # a complex question keeps its steps


def _agent(
    *, status: str = "termine", files: int = 1, checks: bool = True, **extra: Any
) -> dict[str, Any]:
    items = [
        {"path": f"src/projet/m{n}.py", "change": "ajoute", "added": 2, "removed": 0}
        for n in range(files)
    ]
    data: dict[str, Any] = {
        "repo": "projet",
        "agent": {"status": status, "turns": 3, "summary": "Fait."},
        "patch": {"folder": "var/code/agent/abc", "files": items},
        "proxy": {"requests": 2, "usd": "0.010000"},
        "cleanup": {"copy_removed": True, "network_removed": True, "containers_stopped": True},
    }
    if checks:
        data["checks"] = {
            **_checks(ruff_check="ok", ruff_format="ok", pytest="ok"),
            "conclusive": True,
        }
    return {**data, **extra}


def test_a_clean_agent_patch_is_cited_and_left_for_lucas_to_apply() -> None:
    answer = _from_code([_view(_agent(), "agent_task")], complex_=True)
    assert answer["synthese"].startswith(
        "L'agent de code a terminé sur une copie de projet et rend un patch : premier fichier "
        "src/projet/m0.py, ajouté."
    )
    details = answer["developpement"]
    assert "Patch enregistré sous var/code/agent/abc, appliqué nulle part." in details
    assert "copie modifiée de projet" in details
    assert answer["confiance"]["niveau"] == "eleve"
    assert answer["contre_arguments"] == AGENT_COUNTER
    assert answer["prochaines_etapes"] == list(AGENT_STEPS)


@pytest.mark.parametrize(
    ("change", "line"),
    [
        ({"agent": {"status": "erreur"}}, "s'est arrêté en erreur"),
        ({"patch": {"folder": "f", "risky": ["ci.yml"]}}, "Chemins à risque"),
        ({"proxy": None}, "Comptes du proxy illisibles"),
        ({"cleanup": {"copy_removed": False}}, "Nettoyage incomplet : copie non supprimée."),
        ({"checks": None}, "Patch enregistré"),
    ],
)
def test_each_doubt_on_the_agent_lowers_the_confidence(change: dict[str, Any], line: str) -> None:
    data = {**_agent(), **change}
    if "patch" in change:
        data["patch"] = {**change["patch"], "files": _agent()["patch"]["files"]}
    if data.get("checks") is None:
        data.pop("checks")
    head, lines, shortfall = _agent_facts(data)
    assert shortfall == "partial"
    assert line in " ".join([head, *lines])


def test_the_patch_lines_name_what_was_left_out_and_masked() -> None:
    lines = _patch_lines(
        {
            "folder": "var/code/agent/abc",
            "files": [
                {"path": "a.py", "change": "inconnu", "added": 1, "removed": 1, "masked": True}
            ],
            "more_files": 4,
            "masked": 1,
            "binary": ["logo.png"],
            "sensitive": ["deploy/id_ed25519"],
            "more_left_out": 2,
        }
    )
    assert lines[0] == "- a.py : changé, 1 ligne(s) ajoutée(s) et 1 retirée(s) (secret masqué)"
    assert "Autres fichiers du patch, non montrés : 4." in lines
    assert "Secrets masqués dans le patch : 1 ; il ne s'applique pas tel quel." in lines
    assert "Fichiers écartés du patch : logo.png, deploy/id_ed25519." in lines
    assert "Autres fichiers écartés, non montrés : 2." in lines


@pytest.mark.parametrize("status", ["erreur", "delai", "arrete", "autre"])
def test_an_agent_without_patch_is_an_i_do_not_know_with_steps_to_retry(status: str) -> None:
    data = _agent(status=status, files=0, checks=False, checks_note="aucun fichier changé")
    answer = _from_code([_view(data, "agent_task")], complex_=True)
    assert answer["synthese"].startswith("Je ne sais pas : l'agent de code ")
    assert "Patch vide : aucun fichier à appliquer." in answer["developpement"]
    assert answer["confiance"]["niveau"] == "faible"
    assert answer["contre_arguments"] == CODE_COUNTER
    assert answer["prochaines_etapes"] == list(AGENT_RETRY)


def test_an_agent_that_ended_well_without_changing_anything_says_so() -> None:
    head, _, shortfall = _agent_facts(_agent(files=0, checks=False))
    assert head.endswith("sans y changer de fichier lisible : aucun patch à appliquer.")
    assert shortfall == "none"


def test_the_offline_world_leaves_the_task_budget_unset_only_when_the_case_asks() -> None:
    offline_config().require("code.agent")
    with pytest.raises(BlockedFeatureError, match="per_code_agent"):
        offline_config(agent_budget=False).require("code.agent")
