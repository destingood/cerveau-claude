"""`cerveau cyber attack-fetch` (ADR-056): only ever in a temporary home, against a fake GitHub."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from core.audit import AuditJournal, default_journal_path
from core.config.loader import load_config
from core.cyber import fetch
from core.cyber.attack import index_path, read_index
from core.cyber.fetch import BUNDLE_HOST, SOURCES_FILE, Pin, git_blob_sha1, record_sha256
from core.policy.engine import KILL_SWITCH_FILE
from interfaces.cli import cyber as cyber_cli
from interfaces.cli.common import EXIT_BLOCKED, EXIT_ERROR
from interfaces.cli.main import app
from tests.attack_bundle import COMMIT, SAMPLE_RELATIONSHIPS, VERSION, bundle
from tests.net_doubles import PUBLIC_V4, FakeDns, FakeWeb, chunks

ROOT = Path(__file__).resolve().parents[1]
PATH = f"/mitre-attack/attack-stix-data/{COMMIT}/enterprise-attack/enterprise-attack-20.0.json"
NOW = datetime(2026, 10, 27, 9, 30, tzinfo=UTC)
runner = CliRunner()


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    shutil.copytree(ROOT / "config", root / "config")
    monkeypatch.setenv("CERVEAU_HOME", str(root))
    monkeypatch.setattr(cyber_cli, "now", lambda: NOW)
    return root


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> FakeWeb:
    """GitHub serving the synthetic bundle, pinned in place of the real 20.0 one."""
    body = bundle()
    found = FakeWeb()
    found.page(BUNDLE_HOST, PATH, body, content_type="application/json")
    pin = Pin(commit=COMMIT, size=len(body), blob_sha1=git_blob_sha1(body))
    monkeypatch.setitem(fetch.PINS, VERSION, pin)
    monkeypatch.setattr(cyber_cli, "attack_transport", lambda: httpx.MockTransport(found))
    monkeypatch.setattr(cyber_cli, "attack_resolver", lambda: FakeDns({BUNDLE_HOST: [PUBLIC_V4]}))
    return found


def attack_fetch(*args: str) -> Any:
    return runner.invoke(app, ["cyber", "attack-fetch", "--version", VERSION, *args])


def entries(home: Path) -> list[tuple[str, dict[str, Any]]]:
    path = default_journal_path(home)
    if not path.exists():
        return []
    journal = AuditJournal(path)
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return [(e["event"], journal.read_payload(e["payload_ref"])) for e in lines]


def digest(home: Path) -> str | None:
    return load_config(home / "config").data_sources.sources["attack"].sha256


def disable(home: Path, old: bytes, new: bytes) -> None:
    path = home / "config" / SOURCES_FILE
    data = path.read_bytes()
    assert old in data
    path.write_bytes(data.replace(old, new, 1))


def test_the_first_fetch_builds_the_index_and_records_the_digest(home: Path, web: FakeWeb) -> None:
    result = attack_fetch()
    assert result.exit_code == 0, result.output
    sha256 = hashlib.sha256(bundle()).hexdigest()
    assert digest(home) == sha256
    load_config(home / "config").require("data.attack")
    index = read_index(index_path(home, VERSION), VERSION)
    assert (index.bundle_sha256, index.commit, index.built_at) == (
        sha256,
        COMMIT,
        "2026-10-27T09:30:00+00:00",
    )
    assert f"SHA-256 {sha256} inscrit" in result.output
    assert "5 techniques, 2 sous-techniques" in result.output
    assert "`cerveau config check`" in result.output
    ((event, payload),) = entries(home)
    assert event == "TOOL_CALL"
    assert payload["command"] == "cyber attack-fetch"
    assert (payload["version"], payload["commit"], payload["sha256"]) == (VERSION, COMMIT, sha256)
    assert payload["sha256_recorded"] is True
    assert payload["kinds"]["technique"] == 5
    assert payload["relationships"] == SAMPLE_RELATIONSHIPS
    assert payload["bundle_bytes"] == len(bundle())
    written = index_path(home, VERSION).read_bytes()
    assert payload["index_sha256"] == hashlib.sha256(written).hexdigest()
    assert len(web.requests) == 1


def test_a_second_fetch_checks_the_recorded_digest(home: Path, web: FakeWeb) -> None:
    assert attack_fetch().exit_code == 0
    config = (home / "config" / SOURCES_FILE).read_bytes()
    result = attack_fetch()
    assert result.exit_code == 0, result.output
    assert "identique à celui de config/data_sources.yaml" in result.output
    assert (home / "config" / SOURCES_FILE).read_bytes() == config
    assert [p["sha256_recorded"] for _, p in entries(home)] == [True, False]


def test_another_recorded_digest_refuses_the_bundle(home: Path, web: FakeWeb) -> None:
    record_sha256(home / "config", "cd" * 32)
    result = attack_fetch()
    assert result.exit_code == EXIT_ERROR
    assert "SHA-256 différent" in result.output
    assert not index_path(home, VERSION).exists()
    assert digest(home) == "cd" * 32
    ((event, payload),) = entries(home)
    assert event == "ERROR"
    assert "SHA-256 différent" in payload["error"]


def test_a_body_that_does_not_match_the_pin_is_refused(
    home: Path, web: FakeWeb, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin = fetch.PINS[VERSION]
    monkeypatch.setitem(fetch.PINS, VERSION, Pin(pin.commit, pin.size, "0" * 40))
    result = attack_fetch()
    assert result.exit_code == EXIT_ERROR
    assert "empreinte différente de celle du commit épinglé" in result.output
    assert not index_path(home, VERSION).exists()
    assert digest(home) == "A_VERIFIER"


def test_a_disabled_source_blocks_before_any_request(home: Path, web: FakeWeb) -> None:
    disable(home, b"    enabled: true                     # G5", b"    enabled: false")
    result = attack_fetch()
    assert result.exit_code == EXIT_BLOCKED
    assert "Bloqué (R7) : source « attack » absente ou désactivée" in result.output
    assert web.requests == []
    assert [event for event, _ in entries(home)] == ["ERROR"]


def test_another_version_is_refused_before_any_request(home: Path, web: FakeWeb) -> None:
    result = runner.invoke(app, ["cyber", "attack-fetch", "--version", "19.1"])
    assert result.exit_code == EXIT_ERROR
    assert "attend ATT&CK 20.0, pas 19.1" in result.output
    malformed = runner.invoke(app, ["cyber", "attack-fetch", "--version", "20"])
    assert malformed.exit_code == EXIT_ERROR
    assert "version attendue sous la forme 20.0" in malformed.output
    assert web.requests == []


def test_a_version_without_pin_is_refused(
    home: Path, web: FakeWeb, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(fetch.PINS, VERSION)
    result = attack_fetch()
    assert result.exit_code == EXIT_ERROR
    assert "aucun commit épinglé pour ATT&CK 20.0" in result.output
    assert web.requests == []


def test_an_engaged_kill_switch_stops_before_any_request(home: Path, web: FakeWeb) -> None:
    kill = home / KILL_SWITCH_FILE
    kill.parent.mkdir(parents=True)
    kill.write_text("test", encoding="utf-8")
    result = attack_fetch()
    assert result.exit_code == EXIT_BLOCKED
    assert "Kill switch engagé" in result.output
    assert (web.requests, entries(home)) == ([], [])


def test_a_kill_switch_engaged_during_the_download_writes_nothing(home: Path, web: FakeWeb) -> None:
    body = bundle() + b" " * 200_000  # several chunks
    kill = home / KILL_SWITCH_FILE

    def engage_then_answer(_: httpx.Request) -> httpx.Response:
        kill.parent.mkdir(parents=True)
        kill.write_text("test", encoding="utf-8")
        return httpx.Response(200, content=chunks(body))

    web.on(BUNDLE_HOST, PATH, engage_then_answer)
    result = attack_fetch()
    assert result.exit_code == EXIT_BLOCKED
    assert "kill switch engagé : arrêt avant la fin" in result.output
    assert not index_path(home, VERSION).exists()
    assert digest(home) == "A_VERIFIER"
    ((event, payload),) = entries(home)
    assert (event, payload["commit"]) == ("ERROR", COMMIT)


def test_a_github_error_is_journaled(home: Path, web: FakeWeb) -> None:
    web.page(BUNDLE_HOST, PATH, b"", status=404)
    result = attack_fetch()
    assert result.exit_code == EXIT_ERROR
    assert "téléchargement : réponse HTTP 404" in result.output
    ((event, payload),) = entries(home)
    assert (event, payload["error"]) == ("ERROR", "téléchargement : réponse HTTP 404")


def test_an_index_that_cannot_be_written_is_refused(
    home: Path, web: FakeWeb, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full(*_: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(cyber_cli, "write_index", full)
    result = attack_fetch()
    assert result.exit_code == EXIT_ERROR
    assert "écriture impossible (No space left on device)" in result.output
    assert digest(home) == "A_VERIFIER"


def test_a_kill_switch_engaged_after_the_index_leaves_the_configuration(
    home: Path, web: FakeWeb, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = cyber_cli.write_index

    def write_then_engage(path: Path, index: Any) -> str:
        written = real(path, index)
        kill = home / KILL_SWITCH_FILE
        kill.parent.mkdir(parents=True)
        kill.write_text("test", encoding="utf-8")
        return written

    monkeypatch.setattr(cyber_cli, "write_index", write_then_engage)
    result = attack_fetch()
    assert result.exit_code == EXIT_BLOCKED
    assert "kill switch engagé" in result.output
    assert digest(home) == "A_VERIFIER"
    ((event, _),) = entries(home)
    assert event == "ERROR"


def test_an_unexpected_failure_is_journaled(
    home: Path, web: FakeWeb, monkeypatch: pytest.MonkeyPatch
) -> None:
    def exhausted(*_: object, **__: object) -> None:
        raise MemoryError

    monkeypatch.setattr(cyber_cli, "build_index", exhausted)
    result = attack_fetch()
    assert result.exit_code == EXIT_ERROR
    assert "échec inattendu (MemoryError)" in result.output
    assert not index_path(home, VERSION).exists()
    assert digest(home) == "A_VERIFIER"
    ((event, payload),) = entries(home)
    assert (event, payload["error"]) == ("ERROR", "échec inattendu (MemoryError)")
