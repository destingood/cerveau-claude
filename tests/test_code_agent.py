"""Host side of the code agent (ADR-054): docker commands, proxy settings, reports, offline."""

from __future__ import annotations

import json
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from core.code import agent, llm_proxy
from core.code.agent import (
    AGENT_TMPFS,
    KEY_ENV,
    LABEL,
    MAX_FIELD_CHARS,
    MAX_LINE_BYTES,
    MAX_SUMMARY_CHARS,
    PROXY_ALIAS,
    PROXY_LIMITS,
    PROXY_TMPFS,
    ProxyState,
    RunnerReport,
)
from core.code.sandbox import CONTAINER_USER, WORKDIR, Limits, SandboxError
from core.config import load_config
from core.config.loader import ModelPricing, PriceTier
from tests.test_llm_proxy import STREAM_USAGE, call, make_proxy, upstream_reply

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"
PRICING = load_config(REPO_CONFIG).pricing.anthropic.models
SONNET = "claude-sonnet-5-5"
TASK = agent.names("0123456789ab")
IMAGE = "sha256:" + "b" * 64
LIMITS = Limits(cpus=2, memory_mb=4096, pids=512)
TOKENS = {"input": 9000, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0, "output": 700}


def option(arguments: list[str], name: str) -> list[str]:
    """Every value given to an option."""
    return [arguments[i + 1] for i, value in enumerate(arguments) if value == name]


# --- docker commands --------------------------------------------------------------------------


def test_each_task_has_its_own_names() -> None:
    assert (TASK.network, TASK.proxy, TASK.agent) == (
        "cerveau-agent-net-0123456789ab",
        "cerveau-agent-proxy-0123456789ab",
        "cerveau-agent-0123456789ab",
    )


def test_the_network_has_no_way_out() -> None:
    assert agent.network_create(TASK.network) == [
        "network",
        "create",
        "--internal",
        "--label",
        LABEL,
        TASK.network,
    ]
    assert agent.network_connect("bridge", TASK.proxy) == [
        "network",
        "connect",
        "bridge",
        TASK.proxy,
    ]
    assert agent.network_remove(TASK.network) == ["network", "rm", TASK.network]
    assert agent.kill(TASK.agent, TASK.proxy) == ["kill", TASK.agent, TASK.proxy]


def confined(arguments: list[str], limits: Limits, tmpfs: str) -> None:
    assert option(arguments, "--label") == [LABEL]
    assert option(arguments, "--pull") == ["never"]
    assert "--read-only" in arguments
    assert option(arguments, "--tmpfs") == [tmpfs]
    assert option(arguments, "--user") == [CONTAINER_USER]
    assert option(arguments, "--cap-drop") == ["ALL"]
    assert option(arguments, "--security-opt") == ["no-new-privileges=true"]
    assert option(arguments, "--pids-limit") == [str(limits.pids)]
    assert option(arguments, "--memory") == option(arguments, "--memory-swap")
    assert option(arguments, "--memory") == [f"{limits.memory_mb}m"]
    assert option(arguments, "--cpus") == [f"{limits.cpus:g}"]
    assert "--privileged" not in arguments and "--cap-add" not in arguments
    assert "--publish" not in arguments and "-p" not in arguments


def test_the_proxy_gets_the_key_by_name_only(tmp_path: Path) -> None:
    command = agent.proxy_command(TASK, IMAGE, tmp_path / "config", tmp_path / "state")
    assert command[:3] == ["run", "--detach", "--rm"]
    assert option(command, "--name") == [TASK.proxy]
    assert option(command, "--network") == [TASK.network]
    assert option(command, "--network-alias") == [PROXY_ALIAS]
    confined(command, PROXY_LIMITS, PROXY_TMPFS)
    assert "noexec" in PROXY_TMPFS
    assert option(command, "--env") == [KEY_ENV]
    assert option(command, "--mount") == [
        f"type=bind,source={tmp_path / 'config'},target=/config,readonly",
        f"type=bind,source={tmp_path / 'state'},target=/state",
    ]
    assert command[command.index(IMAGE) :] == [
        IMAGE,
        "--settings",
        "/config/settings.json",
        "--state",
        "/state/state.json",
        "--port",
        "8080",
    ]


def test_the_agent_writes_to_its_copy_only(tmp_path: Path) -> None:
    command = agent.agent_command(TASK, IMAGE, tmp_path / "work", tmp_path / "task", LIMITS)
    assert command[:2] == ["run", "--rm"] and "--detach" not in command
    assert option(command, "--name") == [TASK.agent]
    assert option(command, "--network") == [TASK.network]
    confined(command, LIMITS, AGENT_TMPFS)
    assert "--init" in command
    assert option(command, "--mount") == [
        f"type=bind,source={tmp_path / 'work'},target={WORKDIR}",
        f"type=bind,source={tmp_path / 'task'},target=/task,readonly",
    ]
    assert option(command, "--workdir") == [WORKDIR]
    # No key, not even by name: the runner hands a dummy one to the CLI.
    assert option(command, "--env") == ["HOME=/tmp"]
    assert command[command.index(IMAGE) :] == [IMAGE, "--task", "/task/task.json"]


@pytest.mark.parametrize("name", ["a,b", "a=b", 'a"b'])
def test_a_folder_that_would_change_the_mount_is_refused(name: str, tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="dossier de la tâche refusé"):
        agent.agent_command(TASK, IMAGE, tmp_path / name, tmp_path / "task", LIMITS)


# --- settings of the proxy and task file ------------------------------------------------------


def test_the_proxy_settings_are_the_ones_the_proxy_loads() -> None:
    payload = agent.proxy_settings(PRICING[SONNET], SONNET, Decimal(2), 200)
    assert list(payload["models"]) == [SONNET]
    assert (payload["max_usd"], payload["max_requests"]) == ("2", 200)
    loaded = llm_proxy.load_settings(json.dumps(payload))
    assert list(loaded.models) == [SONNET]
    assert loaded.max_usd == Decimal(2) and loaded.max_requests == 200
    assert loaded.max_body_bytes == agent.MAX_BODY_BYTES
    tiers = loaded.models[SONNET]
    assert [t.output for t in tiers] == [t.output for t in PRICING[SONNET].tiers]


def tier(bound: int | None, price: Any = "3") -> PriceTier:
    prices = {name: price for name in agent.PRICES}
    return PriceTier.model_validate({"max_prompt_tokens": bound, **prices})


def test_every_tier_but_the_last_keeps_its_bound() -> None:
    pricing = ModelPricing(tiers=[tier(200_000), tier(None, "6")])
    (model,) = agent.proxy_settings(pricing, "m", Decimal("0.5"), 1)["models"].values()
    assert model["tiers"][0]["max_prompt_tokens"] == 200_000
    assert "max_prompt_tokens" not in model["tiers"][1]
    assert model["tiers"][1]["output"] == "6"
    llm_proxy.load_settings(json.dumps(agent.proxy_settings(pricing, "m", Decimal("0.5"), 1)))


def test_an_undefined_price_stops_the_task() -> None:
    pricing = ModelPricing(tiers=[tier(None, "A_VERIFIER")])
    with pytest.raises(SandboxError, match="prix de m non défini"):
        agent.proxy_settings(pricing, "m", Decimal(2), 1)


def test_the_task_file_is_the_runners() -> None:
    from core.code.agent_runner import read_task

    document = agent.task_document("Corrige main().", SONNET, 30, Decimal("2.00"))
    task = read_task(json.dumps(document))
    assert (task.prompt, task.model, task.max_turns, task.max_usd) == (
        "Corrige main().",
        SONNET,
        30,
        2.0,
    )


# --- the proxy's state ------------------------------------------------------------------------


def state(**changes: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "schema": 1,
        "requests": 3,
        "usd": "0.025000",
        "max_usd": "2",
        "max_requests": 200,
        "unknown_cost": False,
        "pending": False,
        "stopped": None,
        "refusals": {},
        "models": {SONNET: {"requests": 3, "usd": "0.025000", "tokens": TOKENS}},
    }
    raw.update(changes)
    return raw


def test_the_state_the_proxy_writes_is_read_back(tmp_path: Path) -> None:
    proxy, _, path = make_proxy(tmp_path, upstream_reply())
    call(proxy)
    read = agent.read_state(path.read_text(encoding="utf-8"), SONNET)
    assert read is not None
    assert (read.requests, read.stopped, read.refusals) == (1, None, {})
    assert read.spend == {
        "modeles": {SONNET: STREAM_USAGE.to_payload()},
        "cout_inconnu": False,
    }
    assert set(STREAM_USAGE.to_payload()) == set(agent.TOKENS)


def test_a_state_is_read() -> None:
    assert agent.read_state(json.dumps(state()), SONNET) == ProxyState(
        requests=3,
        usd=Decimal("0.025000"),
        stopped=None,
        refusals={},
        spend={"modeles": {SONNET: TOKENS}, "cout_inconnu": False},
    )


@pytest.mark.parametrize(("unknown", "pending"), [(True, False), (False, True)])
def test_a_cost_unknown_or_on_its_way_is_unknown(unknown: bool, pending: bool) -> None:
    read = agent.read_state(json.dumps(state(unknown_cost=unknown, pending=pending)), SONNET)
    assert read is not None and read.spend["cout_inconnu"] is True


def test_long_codes_are_cut() -> None:
    read = agent.read_state(
        json.dumps(state(stopped="s" * 500, refusals={"r" * 500: 1}, models={})), SONNET
    )
    assert read is not None
    assert read.stopped == "s" * MAX_FIELD_CHARS
    assert read.refusals == {"r" * MAX_FIELD_CHARS: 1}
    assert read.spend == {"modeles": {}, "cout_inconnu": False}


@pytest.mark.parametrize(
    "text",
    [
        "pas du JSON",
        "[]",
        json.dumps(state(schema=2)),
        json.dumps({k: v for k, v in state().items() if k != "pending"}),
        json.dumps(state(models={"claude-haiku-5-5": {"tokens": TOKENS}})),
        json.dumps(state(models=[])),
        json.dumps(state(refusals=[])),
        json.dumps(state(unknown_cost=0)),
        json.dumps(state(pending="non")),
        json.dumps(state(stopped=1)),
        json.dumps(state(models={SONNET: {"tokens": {**TOKENS, "autre": 1}}})),
        json.dumps(state(models={SONNET: {"tokens": {**TOKENS, "output": -1}}})),
        json.dumps(state(models={SONNET: {"tokens": {**TOKENS, "output": True}}})),
        json.dumps(state(models={SONNET: {"tokens": []}})),
        json.dumps(state(requests=1.5)),
        json.dumps(state(usd=1)),
        json.dumps(state(usd="beaucoup")),
        json.dumps(state(usd="NaN")),
        json.dumps(state(usd="-1")),
        json.dumps(state(refusals={"a": -1})),
        pytest.param("[" * 100_000 + "]" * 100_000, id="imbrique"),
    ],
)
def test_an_unreadable_state_charges_the_ceiling(text: str) -> None:
    assert agent.read_state(text, SONNET) is None


# --- the runner's line ------------------------------------------------------------------------


def line(**fields: Any) -> bytes:
    raw = {"schema": 1, "statut": "termine", "sous_type": "success", "tours": 4, "resume": "ok"}
    raw.update(fields)
    return (json.dumps(raw) + "\n").encode("utf-8")


def test_the_last_line_is_the_report() -> None:
    stdout = b"bruit\n" + line(statut="erreur") + b"\n  \n" + line(erreur="aucun_resultat")
    assert agent.read_report(stdout) == RunnerReport(
        status="termine", subtype="success", turns=4, summary="ok", error="aucun_resultat"
    )


def test_its_fields_are_bounded() -> None:
    report = agent.read_report(
        line(sous_type="s" * 500, tours=-1, resume="r" * 9000, erreur="e" * 500)
    )
    assert report == RunnerReport(
        status="termine",
        subtype="s" * MAX_FIELD_CHARS,
        turns=None,
        summary="r" * MAX_SUMMARY_CHARS,
        error="e" * MAX_FIELD_CHARS,
    )
    other = agent.read_report(line(sous_type=3, tours=True, resume=None))
    assert other is not None and (other.subtype, other.turns, other.summary) == (None, None, None)


def test_only_the_end_of_a_long_output_is_read() -> None:
    assert agent.read_report(b"x" * (2 * MAX_LINE_BYTES) + b"\n" + line()) is not None
    assert agent.read_report(line() + b"y" * MAX_LINE_BYTES) is None


@pytest.mark.parametrize(
    "stdout",
    [
        b"",
        b"\n \n",
        b"pas du JSON\n",
        b"\xff\n",
        pytest.param(b"[" * 50_000 + b"\n", id="imbrique"),
        b"[1]\n",
        line(schema=2),
        line(statut="reussi"),
    ],
)
def test_an_unreadable_report_is_none(stdout: bytes) -> None:
    assert agent.read_report(stdout) is None


# --- kill switch watcher and key --------------------------------------------------------------


def test_the_watcher_halts_once_the_switch_is_engaged() -> None:
    reads = iter([False, False, True])
    halted: list[bool] = []
    assert agent.watch(threading.Event(), lambda: next(reads), lambda: halted.append(True), 0)
    assert halted == [True]


def test_the_watcher_ends_with_the_task() -> None:
    stop = threading.Event()
    stop.set()
    assert agent.watch(stop, lambda: True, lambda: pytest.fail("arrêté"), 0) is False


@pytest.mark.parametrize(
    ("environ", "present"),
    [({}, False), ({KEY_ENV: ""}, False), ({KEY_ENV: "valeur-factice"}, True)],
)
def test_the_key_is_only_checked_for(environ: dict[str, str], present: bool) -> None:
    assert agent.has_key(environ) is present
