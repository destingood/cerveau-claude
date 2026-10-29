"""code.yaml: allow list of repositories, pinned check image and its bounds (ADR-047, ADR-048)."""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.config import ConfigError, load_config
from core.config.loader import AGENT_CEILINGS, CERVEAU_ROOT, CHECKS_CEILINGS
from tests.conftest import REPO_ROOT

IMAGE = "sha256:" + "a" * 64


def edit_code(config_dir: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    path = config_dir / "code.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def with_repositories(config_dir: Path, *repositories: dict[str, Any]) -> None:
    edit_code(config_dir, lambda d: d.update(repositories=list(repositories)))


@pytest.fixture
def repo_path(tmp_path_factory: pytest.TempPathFactory) -> str:
    """A repository folder outside the copy of the configuration and outside CERVEAU."""
    return str(tmp_path_factory.mktemp("depot"))


def test_the_repositories_and_the_image_wait_for_owner() -> None:
    config = load_config(REPO_ROOT / "config")
    assert config.code.repositories == "A_DEFINIR"  # E2
    assert config.code.checks.image == "A_DEFINIR"  # E4
    assert config.blockers("code.repositories") == ["code.yaml › repositories = A_DEFINIR"]
    assert config.blockers("code.checks") == [
        "code.yaml › repositories = A_DEFINIR",
        "code.yaml › checks.image = A_DEFINIR",
    ]


def test_the_bounds_are_those_of_e5() -> None:
    checks = load_config(REPO_ROOT / "config").code.checks
    bounds = {name: getattr(checks, name) for name in CHECKS_CEILINGS}
    assert bounds == dict(CHECKS_CEILINGS)
    assert bounds == {"cpus": 2, "memory_mb": 2048, "pids": 256, "timeout_seconds": 300}
    with pytest.raises(TypeError):
        CHECKS_CEILINGS["pids"] = 4096  # type: ignore[index]


def test_a_listed_repository_and_a_pinned_image_unblock_the_checks(
    config_dir: Path, repo_path: str
) -> None:
    with_repositories(config_dir, {"id": "mon-projet", "path": repo_path, "github": "owner/projet"})
    edit_code(config_dir, lambda d: d["checks"].update(image=IMAGE))
    config = load_config(config_dir)
    assert config.blockers("code.repositories") == []
    assert config.blockers("code.checks") == []
    (repo,) = config.code.repositories
    assert (repo.id, repo.path, repo.github, repo.pytest, repo.image) == (
        "mon-projet",
        Path(repo_path),
        "owner/projet",
        False,  # E3: pytest only when the user says so
        None,
    )


def test_an_empty_list_allows_no_repository(config_dir: Path) -> None:
    with_repositories(config_dir)
    config = load_config(config_dir)
    assert config.code.repositories == []
    assert config.blockers("code.repositories") == []


@pytest.mark.parametrize(
    ("field", "value"),
    [("cpus", 2.5), ("memory_mb", 4096), ("pids", 512), ("timeout_seconds", 600)],
)
def test_a_bound_cannot_go_above_e5(config_dir: Path, field: str, value: float) -> None:
    edit_code(config_dir, lambda d: d["checks"].update({field: value}))
    with pytest.raises(ConfigError, match=re.escape(f"{field} : {value} dépasse le plafond")):
        load_config(config_dir)


def test_the_bounds_may_be_lowered(config_dir: Path) -> None:
    lower = {"cpus": 0.5, "memory_mb": 512, "pids": 64, "timeout_seconds": 60}
    edit_code(config_dir, lambda d: d["checks"].update(lower))
    checks = load_config(config_dir).code.checks
    assert {name: getattr(checks, name) for name in lower} == lower


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cpus", 0),
        ("cpus", float("nan")),
        ("cpus", True),
        ("memory_mb", 0),
        ("memory_mb", True),
        ("memory_mb", 512.5),
        ("pids", "256"),
        ("timeout_seconds", -1),
    ],
)
def test_a_bound_is_a_positive_number(config_dir: Path, field: str, value: object) -> None:
    edit_code(config_dir, lambda d: d["checks"].update({field: value}))
    with pytest.raises(ConfigError, match=re.escape(f"checks.{field}")):
        load_config(config_dir)


@pytest.mark.parametrize(
    "image",
    [
        IMAGE,
        "python:3.12-slim@sha256:" + "0123456789abcdef" * 4,
        "registry.local:5000/cerveau/checks@sha256:" + "f" * 64,
    ],
)
def test_an_image_pinned_by_content_is_accepted(config_dir: Path, image: str) -> None:
    edit_code(config_dir, lambda d: d["checks"].update(image=image))
    assert load_config(config_dir).code.checks.image == image


@pytest.mark.parametrize(
    "image",
    [
        "python:3.12-slim",  # a tag moves
        "python",
        "sha256:" + "A" * 64,
        "sha256:" + "a" * 63,
        "python@sha256:" + "a" * 65,
        "Python@sha256:" + "a" * 64,
        " " + IMAGE,
        "--privileged",
    ],
)
def test_an_image_not_pinned_by_content_is_refused(config_dir: Path, image: str) -> None:
    edit_code(config_dir, lambda d: d["checks"].update(image=image))
    with pytest.raises(ConfigError, match=re.escape("checks.image")):
        load_config(config_dir)


def test_a_repository_may_have_its_own_pinned_image(config_dir: Path, repo_path: str) -> None:
    with_repositories(config_dir, {"id": "a", "path": repo_path, "pytest": True, "image": IMAGE})
    (repo,) = load_config(config_dir).code.repositories
    assert (repo.pytest, repo.image) == (True, IMAGE)
    with_repositories(config_dir, {"id": "a", "path": repo_path, "image": "python:3.12-slim"})
    with pytest.raises(ConfigError, match=re.escape("repositories.list[CodeRepository].0.image")):
        load_config(config_dir)


@pytest.mark.parametrize(
    "where",
    [
        lambda config_dir: CERVEAU_ROOT,
        lambda config_dir: CERVEAU_ROOT / "plugins",
        lambda config_dir: CERVEAU_ROOT / "plugins" / ".." / "core",
        lambda config_dir: CERVEAU_ROOT.parent,  # it would hold CERVEAU
        lambda config_dir: config_dir.parent,  # the root of the configuration being loaded
        lambda config_dir: config_dir.parent / "docs",
    ],
)
def test_cerveau_itself_is_refused_even_when_listed(
    config_dir: Path, where: Callable[[Path], Path]
) -> None:
    with_repositories(config_dir, {"id": "cerveau", "path": str(where(config_dir))})
    with pytest.raises(
        ConfigError,
        match=re.escape("repositories.cerveau.path : recouvre le dépôt CERVEAU (ADR-047)"),
    ):
        load_config(config_dir)


def test_cerveau_is_the_root_of_this_checkout() -> None:
    assert CERVEAU_ROOT == REPO_ROOT
    assert (CERVEAU_ROOT / "config" / "code.yaml").is_file()


def test_a_relative_path_is_refused(config_dir: Path) -> None:
    with_repositories(config_dir, {"id": "a", "path": "mon-projet"})
    with pytest.raises(ConfigError, match="chemin absolu attendu"):
        load_config(config_dir)


def test_two_repositories_cannot_share_an_id(config_dir: Path, repo_path: str) -> None:
    with_repositories(config_dir, {"id": "a", "path": repo_path}, {"id": "a", "path": repo_path})
    with pytest.raises(ConfigError, match="identifiants de dépôt en double"):
        load_config(config_dir)


@pytest.mark.parametrize("repo_id", ["Mon-Projet", "-a", "a b", "a/b", "", "a" * 41])
def test_a_repository_id_is_a_short_slug(config_dir: Path, repo_path: str, repo_id: str) -> None:
    with_repositories(config_dir, {"id": repo_id, "path": repo_path})
    with pytest.raises(ConfigError, match=re.escape("repositories.list[CodeRepository].0.id")):
        load_config(config_dir)


@pytest.mark.parametrize("github", ["owner/..", "owner/.", "owner", "lu cas/x", "a/b/c", "a/b?c"])
def test_a_github_slug_cannot_climb_the_api_path(
    config_dir: Path, repo_path: str, github: str
) -> None:
    with_repositories(config_dir, {"id": "a", "path": repo_path, "github": github})
    with pytest.raises(ConfigError, match=re.escape("repositories.list[CodeRepository].0.github")):
        load_config(config_dir)


def test_a_github_slug_may_hold_dots(config_dir: Path, repo_path: str) -> None:
    with_repositories(config_dir, {"id": "a", "path": repo_path, "github": "owner/mon.projet"})
    assert load_config(config_dir).code.repositories[0].github == "owner/mon.projet"


@pytest.mark.parametrize("value", ["oui", 1])
def test_pytest_is_a_plain_boolean(config_dir: Path, repo_path: str, value: object) -> None:
    with_repositories(config_dir, {"id": "a", "path": repo_path, "pytest": value})
    with pytest.raises(ConfigError, match=re.escape("repositories.list[CodeRepository].0.pytest")):
        load_config(config_dir)


def test_no_token_field_exists(config_dir: Path, repo_path: str) -> None:
    """E6: code_ci reads public repositories without a token; none can be written here."""
    with_repositories(config_dir, {"id": "a", "path": repo_path, "token": "x"})
    with pytest.raises(ConfigError, match=re.escape("repositories.list[CodeRepository].0.token")):
        load_config(config_dir)


# --- the code agent (ADR-054, F5, F6) ------------------------------------------------------------

AGENT_BLOCKERS = [
    "code.yaml › repositories = A_DEFINIR",
    "code.yaml › checks.image = A_DEFINIR",
    "code.yaml › agent.image = A_DEFINIR",
    "code.yaml › agent.proxy_image = A_DEFINIR",
    "code.yaml › agent.max_requests = A_DEFINIR",
    "budgets.yaml › llm_budget_eur.daily = A_DEFINIR",
    "budgets.yaml › llm_budget_eur.monthly = A_DEFINIR",
    "budgets.yaml › per_code_agent.max_tokens = A_DEFINIR",
    "budgets.yaml › per_code_agent.max_seconds = A_DEFINIR",
    "budgets.yaml › per_code_agent.max_tool_calls = A_DEFINIR",
]


def unblock_agent(config_dir: Path, repo_path: str, **per_code_agent: int) -> None:
    """Every value the code agent waits for, as the user would set them."""
    with_repositories(config_dir, {"id": "mon-projet", "path": repo_path})
    agent = {"image": IMAGE, "proxy_image": "sha256:" + "b" * 64, "max_requests": 60}
    edit_code(config_dir, lambda d: (d["checks"].update(image=IMAGE), d["agent"].update(agent)))
    path = config_dir / "budgets.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["llm_budget_eur"] = {"daily": "5.00", "monthly": "50.00"}
    limits = {"max_tokens": 2_000_000, "max_seconds": 1000, "max_tool_calls": 5}
    data["per_code_agent"] = limits | per_code_agent
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_the_agent_waits_for_owner() -> None:
    config = load_config(REPO_ROOT / "config")
    agent = config.code.agent
    assert (agent.image, agent.proxy_image, agent.max_requests) == ("A_DEFINIR",) * 3
    assert agent.model == "claude-sonnet-5-5"  # F6
    assert config.blockers("code.agent") == AGENT_BLOCKERS


def test_the_agent_unblocks_once_every_value_is_set(config_dir: Path, repo_path: str) -> None:
    unblock_agent(config_dir, repo_path)
    config = load_config(config_dir)
    assert config.blockers("code.agent") == []
    limits = config.budgets.per_code_agent
    assert (limits.max_tokens, limits.max_seconds, limits.max_tool_calls) == (2_000_000, 1000, 5)


def test_the_agent_bounds_are_those_of_f5() -> None:
    agent = load_config(REPO_ROOT / "config").code.agent
    bounds = {name: getattr(agent, name) for name in AGENT_CEILINGS}
    assert bounds == dict(AGENT_CEILINGS)
    assert bounds == {
        "max_turns": 30,
        "max_usd": Decimal(2),
        "timeout_seconds": 900,
        "cpus": 2,
        "memory_mb": 4096,
        "pids": 512,
    }
    with pytest.raises(TypeError):
        AGENT_CEILINGS["max_turns"] = 100  # type: ignore[index]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_turns", 31),
        ("max_usd", "2.01"),
        ("timeout_seconds", 901),
        ("cpus", 2.5),
        ("cpus", 2.01),
        ("memory_mb", 8192),
        ("memory_mb", 4097),
        ("pids", 513),
    ],
)
def test_an_agent_bound_cannot_go_above_f5(config_dir: Path, field: str, value: object) -> None:
    edit_code(config_dir, lambda d: d["agent"].update({field: value}))
    with pytest.raises(ConfigError, match=re.escape(f"{field} : {value} dépasse le plafond")):
        load_config(config_dir)


def test_the_agent_bounds_may_be_lowered(config_dir: Path) -> None:
    lower = {
        "max_turns": 10,
        "max_usd": "0.50",
        "timeout_seconds": 300,
        "cpus": 1.0,
        "memory_mb": 2048,
        "pids": 128,
    }
    edit_code(config_dir, lambda d: d["agent"].update(lower))
    agent = load_config(config_dir).code.agent
    assert {name: getattr(agent, name) for name in lower} == lower | {"max_usd": Decimal("0.50")}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_usd", "0"),
        ("max_usd", "-1"),
        ("max_usd", "0.005"),  # cents at most
        ("max_usd", "NaN"),
        ("max_usd", "Infinity"),
        ("max_turns", 0),
        ("max_turns", True),
        ("max_requests", 0),
        ("max_requests", "60"),
        ("timeout_seconds", 1.5),
        ("cpus", float("nan")),
        ("pids", -1),
    ],
)
def test_an_agent_bound_is_a_positive_number(config_dir: Path, field: str, value: object) -> None:
    edit_code(config_dir, lambda d: d["agent"].update({field: value}))
    with pytest.raises(ConfigError, match=re.escape(f"agent.{field}")):
        load_config(config_dir)


@pytest.mark.parametrize("model", ["sonnet", "claude-Sonnet-5-5", "claude-sonnet 5", "gpt-5"])
def test_the_agent_model_is_a_claude_identifier(config_dir: Path, model: str) -> None:
    edit_code(config_dir, lambda d: d["agent"].update(model=model))
    with pytest.raises(ConfigError, match=re.escape("agent.model")):
        load_config(config_dir)


def test_the_agent_model_must_be_priced(config_dir: Path) -> None:
    """R1: the proxy and the meter price its calls; an unpriced model is refused at load."""
    edit_code(config_dir, lambda d: d["agent"].update(model="claude-sonnet-9-9"))
    with pytest.raises(ConfigError, match=re.escape("prix absent pour claude-sonnet-9-9")):
        load_config(config_dir)


@pytest.mark.parametrize("field", ["image", "proxy_image"])
def test_an_agent_image_must_be_pinned_by_content(config_dir: Path, field: str) -> None:
    edit_code(config_dir, lambda d: d["agent"].update({field: "cerveau/agent:latest"}))
    with pytest.raises(ConfigError, match=re.escape(f"agent.{field}")):
        load_config(config_dir)


def test_no_agent_field_may_be_added(config_dir: Path) -> None:
    """The key, the tools and the network are not settings: the code fixes them (ADR-054)."""
    edit_code(config_dir, lambda d: d["agent"].update(api_key="x"))
    with pytest.raises(ConfigError, match=re.escape("agent.api_key")):
        load_config(config_dir)
