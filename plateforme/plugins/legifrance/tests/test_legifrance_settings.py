"""Which PISTE environment the tools call: read from the configuration before every request."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from plugins.legifrance.legi import LegiError
from plugins.legifrance.settings import INVALID_CONFIG, config_target
from plugins.legifrance.tests.support import PRODUCTION, SANDBOX

ROOT = Path(__file__).resolve().parents[3]


def _config(tmp_path: Path) -> Path:
    return Path(shutil.copytree(ROOT / "config", tmp_path / "config"))


def _edit(config: Path, old: str, new: str) -> None:
    sources = config / "data_sources.yaml"
    text = sources.read_text(encoding="utf-8")
    assert old in text
    sources.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_the_reader_waits_for_owner_to_choose_the_environment(tmp_path: Path) -> None:
    target = config_target(_config(tmp_path))
    with pytest.raises(LegiError) as raised:
        target()
    message = str(raised.value)
    assert message.startswith("source officielle indisponible : ")
    assert "sources.legifrance.url = A_DEFINIR" in message


def test_the_target_is_read_again_at_each_call(tmp_path: Path) -> None:
    config = _config(tmp_path)
    target = config_target(config)
    _edit(config, "url: A_DEFINIR", f"url: {SANDBOX.api}/dila/legifrance/lf-engine-app")
    assert target() is SANDBOX
    _edit(config, f"url: {SANDBOX.api}", f"url: {PRODUCTION.api}")
    assert target() is PRODUCTION
    _edit(config, "enabled: true                     # H1", "enabled: false")
    with pytest.raises(LegiError, match=r"fonction bloquée « data.legifrance »"):
        target()


def test_a_url_outside_piste_is_refused(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _edit(config, "url: A_DEFINIR", "url: https://evil.example/dila/legifrance/lf-engine-app")
    with pytest.raises(LegiError, match="ni l'adresse de production ni celle du bac à sable"):
        config_target(config)()


def test_an_invalid_configuration_blocks_the_reader(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (config / "data_sources.yaml").write_text("sources: [\n", encoding="utf-8")
    with pytest.raises(LegiError) as raised:
        config_target(config)()
    assert str(raised.value) == f"source officielle indisponible : {INVALID_CONFIG}"
