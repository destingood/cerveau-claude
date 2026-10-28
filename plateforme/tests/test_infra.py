"""Static checks of infra/ (no Docker needed) and tests of infra/scripts/generate_secrets.py."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from tests.conftest import REPO_ROOT

INFRA = REPO_ROOT / "infra"
COMPOSE = INFRA / "docker-compose.yml"
ENV_EXAMPLE = INFRA / ".env.example"
INTERPOLATION = re.compile(r"\$\{([A-Z0-9_]+)([^}]*)\}")


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_secrets", INFRA / "scripts" / "generate_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generate_secrets = _load_generator()


def _example_keys() -> list[str]:
    keys = []
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, sep, value = line.partition("=")
            assert sep, f"line without '=' in .env.example: {line!r}"
            assert value == "", f"{key} must stay empty in .env.example"
            keys.append(key)
    return keys


def _compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_every_published_port_is_bound_to_loopback() -> None:
    for name, service in _compose()["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} beyond loopback"


def test_every_interpolated_variable_is_required_and_documented() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    found = INTERPOLATION.findall(text)
    assert found, "the compose file is expected to read its secrets from infra/.env"
    for name, modifier in found:
        assert modifier.startswith(":?"), f"${{{name}}} needs ':?' (no default, R7)"
    assert {name for name, _ in found} == set(_example_keys())


def test_langfuse_telemetry_is_off_and_profiles_are_split() -> None:
    services = _compose()["services"]
    assert services["db"]["profiles"] == ["core", "observability"]
    for name in ("langfuse-web", "langfuse-worker", "clickhouse", "minio", "redis"):
        assert services[name]["profiles"] == ["observability"], name
    for name in ("langfuse-web", "langfuse-worker"):
        assert services[name]["environment"]["TELEMETRY_ENABLED"] == "false"


def test_init_script_keeps_lf_line_endings() -> None:
    assert b"\r\n" not in (INFRA / "postgres" / "init" / "10-init.sh").read_bytes()


def test_render_fills_every_empty_value_without_touching_comments() -> None:
    template = "# KEY=\nALPHA=\nENCRYPTION_KEY=\nKEPT=value\n\n"
    content, generated = generate_secrets.render(template)
    values = dict(
        line.split("=", 1) for line in content.splitlines() if line and not line.startswith("#")
    )
    assert generated == 2
    assert content.startswith("# KEY=\n")
    assert values["KEPT"] == "value"
    assert re.fullmatch(r"[0-9a-f]{48}", values["ALPHA"])
    assert re.fullmatch(r"[0-9a-f]{64}", values["ENCRYPTION_KEY"])


def test_render_draws_a_fresh_secret_each_time() -> None:
    first, _ = generate_secrets.render("ALPHA=\n")
    second, _ = generate_secrets.render("ALPHA=\n")
    assert first != second


def test_main_creates_the_file_and_never_prints_a_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "generated.env"
    assert generate_secrets.main(["--template", str(ENV_EXAMPLE), "--output", str(output)]) == 0
    written = dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    assert set(written) == set(_example_keys())
    printed = capsys.readouterr()
    for secret in written.values():
        assert secret and secret not in printed.out + printed.err


def test_main_refuses_to_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "generated.env"
    output.write_text("KEEP=me\n", encoding="utf-8")
    assert generate_secrets.main(["--template", str(ENV_EXAMPLE), "--output", str(output)]) == 1
    assert output.read_text(encoding="utf-8") == "KEEP=me\n"
