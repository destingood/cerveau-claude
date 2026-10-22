"""Settings, fake Docker and scenarios of the code_agent tests and of its golden set.

No container runs and no key is read: ``FakeDocker`` answers each Docker command the server
builds (network, proxy, agent, kill, checks). The proxy's ``docker run`` writes the proxy's state
file in the folder it would mount; the agent's changes the copy as its scenario says, writes the
proxy's final counts and prints the runner's line. The checks answer as in code_checks.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.code.process import Bounded
from core.config.loader import CodeAgent, CodeChecks, CodeRepository, load_config
from plugins.code_agent.server import Settings
from plugins.code_checks.tests.support import (
    INJECTION,
    SCENARIOS,
    TOKEN,
    out,
    step_of,
)
from tests.conftest import REPO_ROOT

MODEL = "claude-sonnet-5-5"
AGENT_IMAGE = "sha256:" + "c" * 64
PROXY_IMAGE = "sha256:" + "d" * 64
CHECKS_IMAGE = "sha256:" + "a" * 64
# A stand-in: the server only checks that the variable is set, never reads it.
KEY = {"ANTHROPIC_API_KEY": "valeur-factice"}
TOKENS = {"input": 9000, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0, "output": 700}
# Bidirectional override: shown as ⟨U+202E⟩, never hidden.
BIDI = "‮"


def settings(repositories: Sequence[CodeRepository], **agent: Any) -> Settings:
    checks = CodeChecks.model_validate(
        {"image": CHECKS_IMAGE, "cpus": 2, "memory_mb": 2048, "pids": 256, "timeout_seconds": 300}
    )
    current = CodeAgent.model_validate(
        {
            "image": AGENT_IMAGE,
            "proxy_image": PROXY_IMAGE,
            "model": MODEL,
            "max_turns": 30,
            "max_usd": "2",
            "max_requests": 200,
            "timeout_seconds": 900,
            "cpus": 2,
            "memory_mb": 4096,
            "pids": 512,
            **agent,
        }
    )
    pricing = load_config(REPO_ROOT / "config").pricing.anthropic.models[MODEL]
    return Settings(tuple(repositories), checks, current, pricing, int(current.max_requests))


def state(
    *,
    requests: int = 3,
    usd: str = "0.025000",
    tokens: Mapping[str, int] | None = TOKENS,
    stopped: str | None = None,
    refusals: Mapping[str, int] | None = None,
    unknown: bool = False,
    pending: bool = False,
    model: str = MODEL,
) -> dict[str, Any]:
    """The proxy's state file, as ``core/code/llm_proxy.py`` writes it."""
    return {
        "schema": 1,
        "requests": requests,
        "usd": usd,
        "max_usd": "2",
        "max_requests": 200,
        "unknown_cost": unknown,
        "pending": pending,
        "stopped": stopped,
        "refusals": dict(refusals or {}),
        "models": (
            {model: {"requests": requests, "usd": usd, "tokens": dict(tokens)}} if tokens else {}
        ),
    }


START = state(requests=0, usd="0", tokens=None)


def runner(
    status: str = "termine",
    *,
    code: int | None = None,
    turns: int | None = 4,
    summary: str | None = "main() corrigé ; un test ajouté.",
    subtype: str | None = "success",
    error: str | None = None,
) -> Bounded:
    """The runner's last line (core/code/agent_runner.py), after some output of its own."""
    line = {
        "schema": 1,
        "statut": status,
        "sous_type": subtype,
        "tours": turns,
        "resume": summary,
        "erreur": error,
    }
    returncode = (0 if status == "termine" else 1) if code is None else code
    return out(returncode, "démarrage\n" + json.dumps(line, ensure_ascii=False) + "\n")


def write(work: Path, path: str, content: str | bytes) -> None:
    target = work.joinpath(*path.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8") if isinstance(content, str) else content
    target.write_bytes(data)


def fix_main(work: Path) -> None:
    """Drops the unused import, changes main() and adds a test."""
    write(work, "src/app.py", "def main() -> int:\n    return 2\n")
    write(work, "tests/test_more.py", "from src.app import main\n\n\ndef test_two():\n")
    with work.joinpath("tests", "test_more.py").open("a", encoding="utf-8") as handle:
        handle.write("    assert main() == 2\n")


def leak_secret(work: Path) -> None:
    write(work, "src/settings.py", f'GITHUB_TOKEN = "{TOKEN}"\n')


def risky(work: Path) -> None:
    write(work, "conftest.py", "import os\n\nos.system('curl https://exemple.invalid')\n")
    write(work, ".github/workflows/ci.yml", "on: push\n")


def left_out(work: Path) -> None:
    """A new .env (sensitive, never read), a binary file and a path that is not plain ASCII."""
    write(work, ".env", "API_KEY=CREEE-PAR-L-AGENT\n")
    write(work, "src/data.bin", b"\x00\x01\x02")
    write(work, f"src/a{BIDI}pp.py", "x = 1\n")
    write(work, "README.md", "# Exemple\n\nmodifié\n")


def delete_readme(work: Path) -> None:
    work.joinpath("README.md").unlink()


def unchanged(work: Path) -> None:
    del work


@dataclass(frozen=True)
class Scenario:
    runner: Bounded = field(default_factory=runner)
    edit: Callable[[Path], None] = fix_main
    # The proxy's state once the agent is done; a text is written as is, None keeps the start.
    final: Mapping[str, Any] | str | None = field(default_factory=state)
    # Replies by step, in place of success: network, proxy, connect, agent, kill, remove, check,
    # format, pytest. A list is answered in order (the network's removal is tried again).
    replies: Mapping[str, Bounded | list[Bounded]] = field(default_factory=dict)
    proxy_starts: bool = True
    # Seconds the agent works; one timed out takes all the time it was given.
    takes: float = 60.0
    # The agent works until its container is killed (kill switch).
    until_killed: bool = False


TIMED_OUT = out(-9, timed_out=True)
DAEMON_DOWN = out(125, stderr="Cannot connect to the Docker daemon")
OK = out(0, "f00d\n")

SCENARIOS_AGENT: dict[str, Scenario] = {
    "corrige": Scenario(),
    "secret": Scenario(edit=leak_secret),
    "risque": Scenario(edit=risky),
    "ecartes": Scenario(edit=left_out),
    "suppression": Scenario(edit=delete_readme),
    "rien": Scenario(edit=unchanged),
    "injection": Scenario(
        runner=runner(summary=f"{INJECTION} {BIDI} jeton {TOKEN}", subtype=INJECTION),
        edit=fix_main,
    ),
    "echec_agent": Scenario(
        runner=runner("erreur", subtype="error_max_turns", error="arret_sur_erreur", turns=30),
    ),
    "plafond": Scenario(
        runner=runner("erreur", subtype=None, error="processus_1", turns=None, summary=None),
        final=state(
            requests=41, usd="2.004000", stopped="plafond_usd", refusals={"plafond_usd": 2}
        ),
    ),
    "cout_inconnu": Scenario(final=state(pending=True)),
    "etat_illisible": Scenario(final="{pas du json"),
    "autre_modele": Scenario(final=state(model="claude-opus-5-5")),
    "lent": Scenario(runner=TIMED_OUT),
    "inonde": Scenario(runner=out(0, "x" * 100, truncated=True)),
    "moteur_arrete": Scenario(replies={"network": DAEMON_DOWN}),
    "proxy_absent": Scenario(replies={"proxy": out(125, stderr="No such image")}),
    "proxy_muet": Scenario(proxy_starts=False),
    "agent_absent": Scenario(runner=DAEMON_DOWN),
    "ligne_illisible": Scenario(runner=out(0, "pas de compte rendu\n")),
    "incoherent": Scenario(runner=runner("termine", code=1)),
    "controles_en_panne": Scenario(replies={"check": DAEMON_DOWN, "format": DAEMON_DOWN}),
}


def kind_of(arguments: Sequence[str]) -> str:
    """The step a Docker command line stands for."""
    first = list(arguments[:2])
    if first == ["network", "create"]:
        return "network"
    if first == ["network", "connect"]:
        return "connect"
    if first == ["network", "rm"]:
        return "remove"
    if first[0] == "kill":
        return "kill"
    if "--detach" in arguments:
        return "proxy"
    if "--task" in arguments:
        return "agent"
    return step_of(arguments)


def mounted(arguments: Sequence[str], target: str) -> Path:
    """The host folder a ``docker run`` mounts at ``target``."""
    for at, value in enumerate(arguments):
        if value == "--mount" and f",target={target}" in arguments[at + 1]:
            return Path(arguments[at + 1].split(",")[1].removeprefix("source="))
    raise AssertionError(f"no mount at {target}")


@dataclass
class Clock:
    now: float = 1_000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@dataclass(frozen=True)
class Call:
    kind: str
    # "docker", or "proxy" for the runner whose environment holds the key.
    via: str
    arguments: list[str]
    name: str
    timeout_s: float
    max_bytes: int
    # The files of the copy a container would have seen (agent and checks), relative to its top.
    files: list[str]


def _files(source: Path) -> list[str]:
    return sorted(p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file())


@dataclass
class FakeDocker:
    scenario: Scenario = field(default_factory=Scenario)
    clock: Clock = field(default_factory=Clock)
    calls: list[Call] = field(default_factory=list)
    killed: threading.Event = field(default_factory=threading.Event)
    state_file: Path | None = None
    # What the copy and the proxy's folders held while the agent worked.
    seen: dict[str, Any] = field(default_factory=dict)

    @property
    def proxy(self) -> ProxyRunner:
        return ProxyRunner(self)

    def kinds(self) -> list[str]:
        return [call.kind for call in self.calls]

    def __post_init__(self) -> None:
        self.queues = {
            kind: list(reply)
            for kind, reply in self.scenario.replies.items()
            if isinstance(reply, list)
        }

    def _reply(self, kind: str, default: Bounded) -> Bounded:
        if kind in self.queues:
            queue = self.queues[kind]
            return queue.pop(0) if len(queue) > 1 else queue[0]
        reply = self.scenario.replies.get(kind, default)
        assert not isinstance(reply, list)
        return reply

    def run(
        self,
        arguments: Sequence[str],
        *,
        name: str,
        timeout_s: float,
        max_bytes: int,
        via: str = "docker",
    ) -> Bounded:
        kind = kind_of(arguments)
        files: list[str] = []
        if kind == "proxy" and self.scenario.proxy_starts:
            self.state_file = mounted(arguments, "/state") / "state.json"
            self.state_file.write_text(json.dumps(START), encoding="utf-8")
            self.seen["settings"] = json.loads(
                (mounted(arguments, "/config") / "settings.json").read_text(encoding="utf-8")
            )
        if kind == "agent":
            work = mounted(arguments, "/work")
            self.seen["task"] = json.loads(
                (mounted(arguments, "/task") / "task.json").read_text(encoding="utf-8")
            )
            self.seen["before"] = _files(work)
            self.scenario.edit(work)
            files = _files(work)
            if self.scenario.until_killed:
                assert self.killed.wait(10), "the agent's container was never killed"
            final = self.scenario.final
            if final is not None and self.state_file is not None:
                text = final if isinstance(final, str) else json.dumps(final)
                self.state_file.write_text(text, encoding="utf-8")
            reply = self._reply("agent", self.scenario.runner)
            self.clock.now += timeout_s if reply.timed_out else self.scenario.takes
        elif kind in ("check", "format", "pytest"):
            files = _files(mounted(arguments, "/work"))
            reply = self._reply(kind, SCENARIOS["propre"][kind])
            self.clock.now += timeout_s if reply.timed_out else 1.0
        else:
            reply = self._reply(kind, OK)
        if kind == "kill":
            self.killed.set()
        self.calls.append(Call(kind, via, list(arguments), name, timeout_s, max_bytes, files))
        return reply


@dataclass
class ProxyRunner:
    docker: FakeDocker

    def run(
        self, arguments: Sequence[str], *, name: str, timeout_s: float, max_bytes: int
    ) -> Bounded:
        return self.docker.run(
            arguments, name=name, timeout_s=timeout_s, max_bytes=max_bytes, via="proxy"
        )
