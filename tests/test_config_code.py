"""code.yaml: allow list of repositories, pinned check image and its bounds (ADR-047, ADR-048)."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.config import ConfigError, load_config
from core.config.loader import CERVEAU_ROOT, CHECKS_CEILINGS
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


def test_the_repositories_and_the_image_wait_for_lucas() -> None:
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
    with_repositories(config_dir, {"id": "mon-projet", "path": repo_path, "github": "lucas/projet"})
    edit_code(config_dir, lambda d: d["checks"].update(image=IMAGE))
    config = load_config(config_dir)
    assert config.blockers("code.repositories") == []
    assert config.blockers("code.checks") == []
    (repo,) = config.code.repositories
    assert (repo.id, repo.path, repo.github, repo.pytest, repo.image) == (
        "mon-projet",
        Path(repo_path),
        "lucas/projet",
        False,  # E3: pytest only when Lucas says so
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


@pytest.mark.parametrize("github", ["lucas/..", "lucas/.", "lucas", "lu cas/x", "a/b/c", "a/b?c"])
def test_a_github_slug_cannot_climb_the_api_path(
    config_dir: Path, repo_path: str, github: str
) -> None:
    with_repositories(config_dir, {"id": "a", "path": repo_path, "github": github})
    with pytest.raises(ConfigError, match=re.escape("repositories.list[CodeRepository].0.github")):
        load_config(config_dir)


def test_a_github_slug_may_hold_dots(config_dir: Path, repo_path: str) -> None:
    with_repositories(config_dir, {"id": "a", "path": repo_path, "github": "lucas/mon.projet"})
    assert load_config(config_dir).code.repositories[0].github == "lucas/mon.projet"


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
