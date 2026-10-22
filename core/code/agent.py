"""Host side of the code agent (ADR-054, F1 to F5): containers, network, proxy settings, reports.

One task runs two containers on a Docker network of its own, created ``--internal`` (no way
out). The API proxy (ADR-053) also joins the default bridge to reach ``api.anthropic.com``; it
gets the real key by name from the environment of its ``docker run`` only. The agent's container
has the throwaway copy as its only writable mount, a ``tmpfs``, an unprivileged user, no
capability, bounded processors, memory and processes, and an image pinned by content and never
pulled. Every command is built by a pure function, tested option by option.

The reports are read back as untrusted data: the proxy's state file (its counts, written in a
folder only the proxy mounts) gives the spend; the runner's line (which a command of the agent
could forge) only gives the outcome and a summary shown as data.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from core.code.sandbox import CONTAINER_USER, WORKDIR, Limits, SandboxError
from core.config.loader import ModelPricing, PriceTier

SCHEMA = 1  # task file, proxy settings and state (core/code/llm_proxy.py)
KEY_ENV = "ANTHROPIC_API_KEY"
PROXY_ALIAS = "llm-proxy"
PROXY_PORT = 8080
OUTSIDE = "bridge"
LABEL = "cerveau.code_agent=1"
TASK_DIR = "/task"
TASK_FILE = "task.json"
CONFIG_DIR = "/config"
SETTINGS_FILE = "settings.json"
STATE_DIR = "/state"
STATE_FILE = "state.json"
AGENT_TMPFS = "/tmp:rw,nosuid,nodev,size=524288k"  # noqa: S108 - inside the container
PROXY_TMPFS = "/tmp:rw,noexec,nosuid,nodev,size=16384k"  # noqa: S108 - inside the container
PROXY_LIMITS = Limits(cpus=0.5, memory_mb=256, pids=64)
MAX_BODY_BYTES = 32 << 20
UPSTREAM_TIMEOUT_S = 600
PRICES = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")
TOKENS = ("input", "cache_read", "cache_write_5m", "cache_write_1h", "output")
STATUSES = frozenset({"termine", "erreur"})
MAX_LINE_BYTES = 64_000
MAX_SUMMARY_CHARS = 4_000
MAX_FIELD_CHARS = 100


@dataclass(frozen=True)
class Names:
    network: str
    proxy: str
    agent: str


def names(task_id: str) -> Names:
    return Names(
        f"cerveau-agent-net-{task_id}", f"cerveau-agent-proxy-{task_id}", f"cerveau-agent-{task_id}"
    )


def _mount(source: Path, target: str, *, readonly: bool) -> str:
    text = str(source)
    if any(char in text for char in ',="'):
        raise SandboxError('dossier de la tâche refusé : « , », « = » ou « " » dans son chemin')
    return f"type=bind,source={text},target={target}" + (",readonly" if readonly else "")


def _confined(limits: Limits, tmpfs: str) -> list[str]:
    """Options common to both containers: read-only root, unprivileged, bounded, labelled so that
    a leftover can be found (``docker ps --filter label=...``)."""
    return [
        "--label",
        LABEL,
        "--pull",
        "never",
        "--read-only",
        "--tmpfs",
        tmpfs,
        "--user",
        CONTAINER_USER,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges=true",
        "--pids-limit",
        str(limits.pids),
        "--memory",
        f"{limits.memory_mb}m",
        "--memory-swap",
        f"{limits.memory_mb}m",
        "--cpus",
        f"{limits.cpus:g}",
    ]


def network_create(network: str) -> list[str]:
    return ["network", "create", "--internal", "--label", LABEL, network]


def network_connect(network: str, container: str) -> list[str]:
    return ["network", "connect", network, container]


def network_remove(network: str) -> list[str]:
    return ["network", "rm", network]


def kill(*containers: str) -> list[str]:
    return ["kill", *containers]


def proxy_command(task: Names, image: str, settings_dir: Path, state_dir: Path) -> list[str]:
    """``docker run`` of the proxy, detached; the key comes by name, never as a value (R6)."""
    return [
        "run",
        "--detach",
        "--rm",
        "--name",
        task.proxy,
        "--network",
        task.network,
        "--network-alias",
        PROXY_ALIAS,
        *_confined(PROXY_LIMITS, PROXY_TMPFS),
        "--mount",
        _mount(settings_dir, CONFIG_DIR, readonly=True),
        "--mount",
        _mount(state_dir, STATE_DIR, readonly=False),
        "--env",
        KEY_ENV,
        image,
        "--settings",
        f"{CONFIG_DIR}/{SETTINGS_FILE}",
        "--state",
        f"{STATE_DIR}/{STATE_FILE}",
        "--port",
        str(PROXY_PORT),
    ]


def agent_command(task: Names, image: str, work: Path, task_dir: Path, limits: Limits) -> list[str]:
    """``docker run`` of the agent: the copy is its only writable mount (F1, F5)."""
    return [
        "run",
        "--rm",
        "--name",
        task.agent,
        "--network",
        task.network,
        *_confined(limits, AGENT_TMPFS),
        "--init",
        "--mount",
        _mount(work, WORKDIR, readonly=False),
        "--mount",
        _mount(task_dir, TASK_DIR, readonly=True),
        "--workdir",
        WORKDIR,
        "--env",
        "HOME=/tmp",
        image,
        "--task",
        f"{TASK_DIR}/{TASK_FILE}",
    ]


def _price(value: Decimal | str, model: str) -> str:
    if not isinstance(value, Decimal):
        raise SandboxError(f"pricing.yaml : prix de {model} non défini ({value})")
    return str(value)


def _tier(tier: PriceTier, model: str, last: bool) -> dict[str, Any]:
    prices: dict[str, Any] = {name: _price(getattr(tier, name), model) for name in PRICES}
    if not last:
        prices["max_prompt_tokens"] = tier.max_prompt_tokens
    return prices


def proxy_settings(
    pricing: ModelPricing, model: str, max_usd: Decimal, max_requests: int
) -> dict[str, Any]:
    """Settings of the proxy: the task's model alone, its prices (R1) and the task's ceilings."""
    last = len(pricing.tiers) - 1
    return {
        "schema": SCHEMA,
        "models": {
            model: {"tiers": [_tier(t, model, i == last) for i, t in enumerate(pricing.tiers)]}
        },
        "max_usd": str(max_usd),
        "max_requests": max_requests,
        "max_body_bytes": MAX_BODY_BYTES,
        "upstream_timeout_s": UPSTREAM_TIMEOUT_S,
    }


def task_document(prompt: str, model: str, max_turns: int, max_usd: Decimal) -> dict[str, Any]:
    """The runner's task file (core/code/agent_runner.py)."""
    return {
        "schema": SCHEMA,
        "prompt": prompt,
        "model": model,
        "max_turns": max_turns,
        "max_usd": str(max_usd),
    }


@dataclass(frozen=True)
class ProxyState:
    """What the proxy counted; ``spend`` has the shape ``core/mcp/spend.py`` reads."""

    requests: int
    usd: Decimal
    stopped: str | None
    refusals: dict[str, int]
    spend: dict[str, Any]


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def _amount(value: object) -> Decimal:
    if not isinstance(value, str):
        raise ValueError
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError from None
    if not amount.is_finite() or amount < 0:
        raise ValueError
    return amount


def _tokens(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict) or set(raw) != set(TOKENS):
        raise ValueError
    return {name: _count(raw[name]) for name in TOKENS}


def read_state(text: str, model: str) -> ProxyState | None:
    """The proxy's state file; ``None`` when unreadable, another model in it included, so that
    the adapter charges the task's ceiling (R7). A request still on its way when the proxy was
    stopped may have cost what it never read: the cost is then unknown."""
    try:
        raw = json.loads(text)
        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
            raise ValueError
        models = raw["models"]
        refusals = raw["refusals"]
        stopped = raw["stopped"]
        unknown, pending = raw["unknown_cost"], raw["pending"]
        if not isinstance(models, dict) or set(models) - {model} or not isinstance(refusals, dict):
            raise ValueError
        if not (isinstance(unknown, bool) and isinstance(pending, bool)):
            raise ValueError
        if not (stopped is None or isinstance(stopped, str)):
            raise ValueError
        spend = {name: _tokens(count["tokens"]) for name, count in models.items()}
        return ProxyState(
            requests=_count(raw["requests"]),
            usd=_amount(raw["usd"]),
            stopped=stopped[:MAX_FIELD_CHARS] if stopped else None,
            refusals={str(k)[:MAX_FIELD_CHARS]: _count(v) for k, v in refusals.items()},
            spend={"modeles": spend, "cout_inconnu": unknown or pending},
        )
    except (ValueError, KeyError, TypeError, RecursionError):
        return None


@dataclass(frozen=True)
class RunnerReport:
    """The runner's last line: untrusted (ADR-054)."""

    status: str
    subtype: str | None
    turns: int | None
    summary: str | None
    error: str | None


def _short(value: object, limit: int) -> str | None:
    return value[:limit] if isinstance(value, str) else None


def read_report(stdout: bytes) -> RunnerReport | None:
    lines = [line for line in stdout[-MAX_LINE_BYTES:].splitlines() if line.strip()]
    if not lines:
        return None
    try:
        raw = json.loads(lines[-1].decode("utf-8"))
    except (ValueError, RecursionError):  # the line is the agent's: nested past the limit
        return None
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return None
    status, turns = raw.get("statut"), raw.get("tours")
    if status not in STATUSES:
        return None
    return RunnerReport(
        status=status,
        subtype=_short(raw.get("sous_type"), MAX_FIELD_CHARS),
        turns=turns if type(turns) is int and turns >= 0 else None,
        summary=_short(raw.get("resume"), MAX_SUMMARY_CHARS),
        error=_short(raw.get("erreur"), MAX_FIELD_CHARS),
    )


def watch(
    stop: threading.Event,
    engaged: Callable[[], bool],
    halt: Callable[[], None],
    interval: float,
) -> bool:
    """Until ``stop`` is set, check the kill switch every ``interval`` seconds (R4); once it is
    engaged, call ``halt`` (which kills both containers) and return ``True``."""
    while not stop.wait(interval):
        if engaged():
            halt()
            return True
    return False


def has_key(environ: Mapping[str, str]) -> bool:
    """Whether the key the proxy needs is set; its value is never read here (R6)."""
    return bool(environ.get(KEY_ENV))
