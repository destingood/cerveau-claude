"""MCP client adapter: registry scoping, policy, budget, time limits and audit (ADR-007).

No ``from __future__ import annotations`` here: the drift servers below declare MCP tools, whose
signatures the SDK reads at runtime.
"""

import asyncio
import json
import shutil
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from langchain_core.messages import ToolMessage
from langchain_core.tools import ToolException
from mcp import Client, StdioServerParameters
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from core.audit.chain import AuditJournal, verify
from core.budget.gate import RequestBudget, RequestBudgetExceeded
from core.config import load_config
from core.config.loader import PerRequest
from core.finance.fixtures import REFERENCE_READ_AT, reference_store
from core.mcp.adapter import (
    ISOLATION_REFUSAL,
    TASK_LIMIT_REFUSAL,
    TOOL_TIMEOUT_S,
    McpAdapterError,
    McpPlugin,
    RequestScope,
    ToolRefusedError,
    server_environment,
)
from core.mcp.spend import IsolatedTask
from core.mcp.time_limit import TIME_LIMIT_META_KEY
from core.models import CostCalculator, Meter
from core.models.meter import CEILING_TIER
from core.net.guard import FetchError
from core.orchestrator.runtime import LazyPlugin, _Holder
from core.policy.engine import KILL_SWITCH_FILE
from plugins.finance_risk.server import build_server as build_risk_server
from plugins.web_research.models import PageText, SearchResults
from plugins.web_research.search import Hit
from plugins.web_research.server import ANNOTATIONS, DESCRIPTIONS, build_server
from tests.conftest import agent_manifest

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "web_research"
CONFIG = load_config(REPO / "config")
LIMITS = PerRequest(max_tool_calls=25, max_tokens=150000, max_seconds=120)
PAGE = PageText(
    url="https://example.org/a",
    final_url="https://example.org/a",
    content_type="text/html",
    title="Titre",
    published=None,
    text="Contenu confidentiel de la page, jamais journalisé.",
    truncated=False,
    retrieved_at="2026-10-18T12:00:00+00:00",
)
HITS = [Hit("Un", "https://a.example/", "Extrait externe à ne pas journaliser")]


class FakeProvider:
    name = "fake"

    async def search(self, query: str, count: int) -> list[Hit]:
        return HITS


class FakeReader:
    def __init__(self, error: str | None = None, delay_s: float = 0.0) -> None:
        self.error, self.delay_s = error, delay_s

    async def read(self, raw_url: str) -> PageText:
        await asyncio.sleep(self.delay_s)
        if self.error:
            raise FetchError(self.error)
        return PAGE


def make_scope(root: Path, limits: PerRequest = LIMITS) -> RequestScope:
    meter = Meter(CostCalculator(CONFIG.pricing))
    return RequestScope(
        request_id="req-test",
        domain="generaliste",
        autonomy=CONFIG.autonomy,
        journal=AuditJournal(root / "audit" / "journal.jsonl"),
        budget=RequestBudget(limits, meter, clock=lambda: 0.0),
        meter=meter,
        project_root=root,
        live_enabled=False,
    )


@pytest.fixture
def scope(tmp_path: Path) -> RequestScope:
    return make_scope(tmp_path)


def session(
    scope: RequestScope,
    action: Callable[[McpPlugin], Awaitable[Any]],
    target: Any = None,
    **kwargs: Any,
) -> Any:
    server = build_server(FakeProvider(), FakeReader()) if target is None else target

    async def go() -> Any:
        async with McpPlugin(PLUGIN, scope, target=server, **kwargs) as plugin:
            return await action(plugin)

    return asyncio.run(go())


async def invoke(plugin: McpPlugin, name: str, args: dict[str, Any]) -> ToolMessage:
    tool = next(tool for tool in plugin.tools if tool.name == name)
    return await tool.ainvoke({"type": "tool_call", "id": "call-1", "name": name, "args": args})


def entries(scope: RequestScope) -> list[dict[str, Any]]:
    lines = scope.journal.path.read_text(encoding="utf-8").splitlines()
    return [
        {**entry, "payload": scope.journal.read_payload(entry["payload_ref"])}
        for entry in map(json.loads, lines)
    ]


@pytest.mark.parametrize("domain", ["finance", "generaliste"])
def test_a_computing_tool_is_kept_in_the_finance_pack_only(tmp_path: Path, domain: str) -> None:
    store = reference_store(tmp_path / "finance.db")
    server = build_risk_server(store, REPO / "config", clock=lambda: REFERENCE_READ_AT)
    scope = replace(make_scope(tmp_path), domain=domain)

    async def go() -> McpPlugin:
        async with McpPlugin(REPO / "plugins" / "finance_risk", scope, target=server) as plugin:
            return plugin

    plugin = asyncio.run(go())
    if domain == "finance":
        assert [tool.name for tool in plugin.tools] == ["risk_report"]
        assert plugin.skipped == {}
    else:
        assert list(plugin.tools) == []
        assert plugin.skipped == {
            "risk_report": "politique : matrice CALCUL × N1 : auto ; aucune capacité CALCUL "
            "pour le domaine « generaliste » dans cette phase : refus"
        }


def test_the_manifest_tools_are_exposed(scope: RequestScope) -> None:
    plugin = session(scope, lambda p: asyncio.sleep(0, p))
    assert sorted(tool.name for tool in plugin.tools) == ["web_read", "web_search"]
    assert plugin.skipped == {}
    assert plugin.version == "web_research@0.1.0"


def test_a_search_returns_an_artifact_and_is_journaled(scope: RequestScope) -> None:
    message = session(scope, lambda p: invoke(p, "web_search", {"query": "thé"}))
    assert message.status == "success"
    assert message.artifact["results"][0]["url"] == "https://a.example/"
    assert "Extrait externe" not in message.content  # external text only travels as the artifact
    (entry,) = entries(scope)
    assert (entry["actor"], entry["event"], entry["request_id"]) == (
        "orchestrator",
        "TOOL_CALL",
        "req-test",
    )
    assert entry["versions"] == {"plugin": "web_research@0.1.0"}
    assert entry["redactions"] == ["result_content"]
    payload = entry["payload"]
    assert payload["status"] == "ok"
    assert payload["arguments"] == {"query": "thé"}
    assert payload["action_class"] == "LECTURE"
    assert payload["search"]["provider"] == "brave"
    assert payload["tool_calls"] == 1
    assert len(scope.meter.search_calls) == 1
    assert verify(scope.journal.path).ok


def test_the_journal_keeps_the_masked_arguments(scope: RequestScope) -> None:
    async def search(plugin: McpPlugin) -> tuple[str, dict[str, Any]]:
        spec = next(spec for spec in plugin.manifest.tools if spec.name == "web_search")
        masked = {"query": "thé chez <PERSON_1>"}
        return await plugin.call(spec, {"query": "thé chez Jean Dupont"}, journaled=masked)

    _content, result = session(scope, search)
    assert result["query"] == "thé chez Jean Dupont"  # the plugin got the real arguments
    (entry,) = entries(scope)
    assert entry["payload"]["arguments"] == {"query": "thé chez <PERSON_1>"}
    assert "Dupont" not in json.dumps(entry, ensure_ascii=False)


def test_no_page_content_reaches_the_journal(scope: RequestScope) -> None:
    async def both(plugin: McpPlugin) -> None:
        await invoke(plugin, "web_search", {"query": "q"})
        await invoke(plugin, "web_read", {"url": PAGE.url})

    session(scope, both)
    stored = scope.journal.path.read_text(encoding="utf-8") + "".join(
        path.read_text(encoding="utf-8") for path in scope.journal.payload_dir.glob("*.json")
    )
    assert "Contenu confidentiel" not in stored
    assert "Extrait externe" not in stored
    read_entry = entries(scope)[1]["payload"]
    assert read_entry["search"] is None
    assert read_entry["result_bytes"] > 0


def test_tool_errors_go_back_to_the_model_and_the_journal(scope: RequestScope) -> None:
    server = build_server(FakeProvider(), FakeReader(error="URL refusée : hôte absent"))
    message = session(scope, lambda p: invoke(p, "web_read", {"url": "http:///"}), server)
    assert message.status == "error"
    assert "hôte absent" in message.content
    payload = entries(scope)[0]["payload"]
    assert payload["status"] == "erreur"
    assert "hôte absent" in payload["error"]


def test_a_slow_call_is_cut_at_the_timeout(scope: RequestScope) -> None:
    server = build_server(FakeProvider(), FakeReader(delay_s=5))
    message = session(
        scope, lambda p: invoke(p, "web_read", {"url": PAGE.url}), server, timeout_s=0.05
    )
    assert message.status == "error"
    assert "délai" in message.content
    assert entries(scope)[0]["payload"]["status"] == "delai"


def _sent_limits(scope: RequestScope, directory: Path = PLUGIN) -> list[Any]:
    """The ``_meta`` of each call that reached the client, after one web_search."""
    sent: list[Any] = []

    async def action(plugin: McpPlugin) -> ToolMessage:
        client = plugin._client
        assert client is not None
        original = client.call_tool

        async def recording(*args: Any, **kwargs: Any) -> Any:
            sent.append(kwargs.get("meta"))
            return await original(*args, **kwargs)

        client.call_tool = recording  # type: ignore[method-assign]
        return await invoke(plugin, "web_search", {"query": "q"})

    server = build_server(FakeProvider(), FakeReader())

    async def go() -> None:
        async with McpPlugin(directory, scope, target=server) as plugin:
            message = await action(plugin)
            assert message.status != "error", message.content

    asyncio.run(go())
    return sent


def test_each_call_sends_the_limit_it_is_cut_at(tmp_path: Path) -> None:
    """ADR-052: without a declared limit, 30 s; the request's budget may cut it sooner."""
    assert _sent_limits(make_scope(tmp_path / "a")) == [{TIME_LIMIT_META_KEY: TOOL_TIMEOUT_S}]
    short = PerRequest(max_tool_calls=25, max_tokens=150000, max_seconds=12)
    assert _sent_limits(make_scope(tmp_path / "b", short)) == [{TIME_LIMIT_META_KEY: 12.0}]


def _declaring(root: Path, seconds: float) -> Path:
    """A copy of web_research whose manifest declares ``seconds`` for a call."""
    directory = root / "plugins" / "web_research"
    shutil.copytree(PLUGIN, directory, ignore=shutil.ignore_patterns("__pycache__"))
    manifest = yaml.safe_load((directory / "plugin.yaml").read_text(encoding="utf-8"))
    manifest["runtime"]["tool_timeout_s"] = seconds
    (directory / "plugin.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return directory


def test_a_manifest_may_give_its_calls_a_longer_limit(tmp_path: Path) -> None:
    directory = _declaring(tmp_path, 90)
    assert _sent_limits(make_scope(tmp_path), directory) == [{TIME_LIMIT_META_KEY: 90.0}]
    short = PerRequest(max_tool_calls=25, max_tokens=150000, max_seconds=60)
    sent = _sent_limits(make_scope(tmp_path / "b", short), directory)
    assert sent == [{TIME_LIMIT_META_KEY: 60.0}]  # the request's budget comes first


def test_a_server_start_keeps_the_default_limit(
    scope: RequestScope, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A long call is not a long start: a server that does not start is cut at 30 s."""
    plugin = McpPlugin(_declaring(tmp_path, 900), scope, target=object())
    waited: list[float] = []

    async def at_once(awaitable: Any, timeout: float) -> Any:
        waited.append(timeout)
        awaitable.close()
        raise TimeoutError

    async def never() -> None:
        await asyncio.sleep(30)

    monkeypatch.setattr(asyncio, "wait_for", at_once)
    plugin.plan(never)
    with pytest.raises(McpAdapterError, match="démarrage au-delà de 30 s"):
        asyncio.run(plugin.call(spec(plugin, "web_search"), {"query": "q"}))
    assert waited == [TOOL_TIMEOUT_S]


def test_the_request_tool_budget_is_enforced(tmp_path: Path) -> None:
    scope = make_scope(tmp_path, PerRequest(max_tool_calls=1, max_tokens=150000, max_seconds=120))

    async def twice(plugin: McpPlugin) -> None:
        await invoke(plugin, "web_search", {"query": "un"})
        await invoke(plugin, "web_search", {"query": "deux"})

    with pytest.raises(RequestBudgetExceeded):
        session(scope, twice)
    assert [e["payload"]["status"] for e in entries(scope)] == ["ok", "budget_depasse"]
    assert len(scope.meter.search_calls) == 1


def test_the_kill_switch_hides_every_tool(scope: RequestScope, tmp_path: Path) -> None:
    (tmp_path / KILL_SWITCH_FILE).parent.mkdir(parents=True)
    (tmp_path / KILL_SWITCH_FILE).write_text("", encoding="utf-8")
    plugin = session(scope, lambda p: asyncio.sleep(0, p))
    assert plugin.tools == []
    assert all("kill switch" in reason for reason in plugin.skipped.values())


def test_the_kill_switch_stops_a_running_request(scope: RequestScope, tmp_path: Path) -> None:
    async def engage_then_call(plugin: McpPlugin) -> ToolMessage:
        (tmp_path / KILL_SWITCH_FILE).parent.mkdir(parents=True)
        (tmp_path / KILL_SWITCH_FILE).write_text("", encoding="utf-8")
        return await invoke(plugin, "web_search", {"query": "q"})

    with pytest.raises(ToolRefusedError, match="kill switch"):
        session(scope, engage_then_call)
    payload = entries(scope)[0]["payload"]
    assert payload["status"] == "refuse"
    assert payload["policy"]["decision"] == "refus"
    assert scope.budget.tool_calls == 0
    assert scope.meter.search_calls == ()


def test_an_enabled_live_configuration_hides_every_tool(tmp_path: Path) -> None:
    scope = replace(make_scope(tmp_path), live_enabled=True)
    plugin = session(scope, lambda p: asyncio.sleep(0, p))
    assert plugin.tools == []
    assert plugin.skipped
    assert all("ALERTE" in reason for reason in plugin.skipped.values())


def test_a_domain_absent_from_autonomy_gets_no_tool(tmp_path: Path) -> None:
    scope = replace(make_scope(tmp_path), domain="inconnu")
    plugin = session(scope, lambda p: asyncio.sleep(0, p))
    assert plugin.tools == []


def _drifting_server() -> MCPServer:
    server = MCPServer("web_research")

    @server.tool(
        name="web_search",
        description="Une autre description.",
        annotations=ANNOTATIONS,
        structured_output=True,
    )
    def web_search(query: str, max_results: int = 5) -> SearchResults:
        raise AssertionError("never called")

    @server.tool(
        name="web_read",
        description=DESCRIPTIONS["web_read"],
        annotations=ANNOTATIONS.model_copy(update={"read_only_hint": False}),
        structured_output=True,
    )
    def web_read(url: str) -> PageText:
        raise AssertionError("never called")

    @server.tool(name="run_shell", description="Lance une commande.")
    def run_shell(command: str) -> str:
        raise AssertionError("never called")

    return server


def _renamed_argument_server() -> MCPServer:
    server = MCPServer("web_research")

    @server.tool(
        name="web_read",
        description=DESCRIPTIONS["web_read"],
        annotations=ANNOTATIONS,
        structured_output=True,
    )
    def web_read(link: str) -> PageText:
        raise AssertionError("never called")

    return server


@pytest.mark.parametrize(
    ("factory", "expected"),
    [
        (
            _drifting_server,
            {
                "web_search": "description publiée différente du manifeste",
                "web_read": "annotations publiées différentes du manifeste",
                "run_shell": "publié par le serveur mais absent du manifeste",
            },
        ),
        (
            _renamed_argument_server,
            {
                "web_search": "déclaré dans le manifeste mais non publié par le serveur",
                "web_read": "schéma d'entrée publié différent du manifeste",
            },
        ),
    ],
)
def test_a_server_drifting_from_its_manifest_is_not_trusted(
    scope: RequestScope, factory: Callable[[], MCPServer], expected: dict[str, str]
) -> None:
    plugin = session(scope, lambda p: asyncio.sleep(0, p), factory())
    assert plugin.tools == []
    assert plugin.skipped == expected


def test_a_plugin_refused_by_the_registry_is_never_started(
    scope: RequestScope, make_plugin: Callable[..., Path]
) -> None:
    directory = make_plugin()
    (directory / "plugin.yaml").write_text("id: [broken\n", encoding="utf-8")
    with pytest.raises(McpAdapterError, match="refusé par le registre"):
        McpPlugin(directory, scope)


def test_a_plugin_without_a_runtime_is_refused(
    scope: RequestScope, make_plugin: Callable[..., Path]
) -> None:
    with pytest.raises(McpAdapterError, match="démarrage inconnu"):
        McpPlugin(make_plugin(), scope)


def test_an_in_process_agent_is_never_opened_as_a_server(
    scope: RequestScope, make_plugin: Callable[..., Path]
) -> None:
    root = make_plugin("demo_agent", manifest=agent_manifest())
    (root / "graph.py").write_text("def build_graph():\n    return None\n", encoding="utf-8")
    with pytest.raises(McpAdapterError, match="agent in-process, il ne s'ouvre pas"):
        McpPlugin(root, scope, target=object())


def test_only_declared_variables_reach_the_server(scope: RequestScope) -> None:
    environ = {
        "BRAVE_SEARCH_API_KEY": "test-key-not-a-secret",
        "ANTHROPIC_API_KEY": "must-not-leak",
        "LANGFUSE_SECRET_KEY": "must-not-leak",
    }
    assert server_environment(("BRAVE_SEARCH_API_KEY", "MISSING"), environ) == {
        "BRAVE_SEARCH_API_KEY": "test-key-not-a-secret"
    }
    assert server_environment(("EMPTY",), {"EMPTY": ""}) == {}
    target = McpPlugin(PLUGIN, scope, environ=environ)._target
    assert isinstance(target, StdioServerParameters)
    assert (target.command, target.args) == (sys.executable, ["-m", "plugins.web_research"])
    assert target.env == {"BRAVE_SEARCH_API_KEY": "test-key-not-a-secret"}


def test_the_real_server_over_stdio(scope: RequestScope) -> None:
    """The subprocess path, without a key: no network, the search refuses before any request."""

    async def go() -> tuple[list[str], ToolMessage]:
        async with McpPlugin(PLUGIN, scope, environ={}) as plugin:
            names = sorted(tool.name for tool in plugin.tools)
            return names, await invoke(plugin, "web_search", {"query": "q"})

    names, message = asyncio.run(go())
    assert names == ["web_read", "web_search"]
    assert "BRAVE_SEARCH_API_KEY absente" in message.content


def test_a_server_that_cannot_start_is_reported(scope: RequestScope) -> None:
    target = StdioServerParameters(command=sys.executable, args=["-c", "raise SystemExit(3)"])
    with pytest.raises(McpAdapterError, match="serveur injoignable"):
        session(scope, lambda p: asyncio.sleep(0, p), target)


# --- a server started at its first call (B98) --------------------------------------------------


def planned(
    scope: RequestScope, target: Any = None, **kwargs: Any
) -> tuple[McpPlugin, _Holder, list[str]]:
    """A plugin planned as ``LazyPlugin.plan`` does, with the starts of its server counted."""
    server = build_server(FakeProvider(), FakeReader()) if target is None else target
    plugin = McpPlugin(PLUGIN, scope, target=server, **kwargs)
    holder, starts = _Holder(), []

    @asynccontextmanager
    async def enter(_scope: RequestScope) -> AsyncIterator[Any]:
        starts.append(plugin.manifest.id)
        async with plugin:
            yield plugin

    async def connect() -> None:
        await holder.open(enter, scope)

    plugin.plan(connect)
    return plugin, holder, starts


def spec(plugin: McpPlugin, name: str) -> Any:
    return next(tool for tool in plugin.manifest.tools if tool.name == name)


def test_a_planned_plugin_gives_its_tools_before_its_server_starts(scope: RequestScope) -> None:
    async def go() -> tuple[list[str], list[str], dict[str, Any]]:
        plugin, holder, starts = planned(scope)
        names = sorted(tool.name for tool in plugin.tools)
        before = list(starts)
        try:
            _content, result = await plugin.call(spec(plugin, "web_search"), {"query": "q"})
        finally:
            await holder.aclose()
        return names, [*before, "|", *starts], result

    names, starts, result = asyncio.run(go())
    assert names == ["web_read", "web_search"]
    assert starts == ["|", "web_research"]
    assert result["results"][0]["url"] == HITS[0].url
    assert [e["payload"]["status"] for e in entries(scope)] == ["ok"]


def test_concurrent_first_calls_start_the_server_once(scope: RequestScope) -> None:
    async def go() -> list[str]:
        plugin, holder, starts = planned(scope)
        search = spec(plugin, "web_search")
        try:
            await asyncio.gather(*(plugin.call(search, {"query": f"q{i}"}) for i in range(4)))
        finally:
            await holder.aclose()
        return starts

    assert asyncio.run(go()) == ["web_research"]
    assert [e["payload"]["status"] for e in entries(scope)] == ["ok"] * 4


def test_a_tool_published_differently_is_refused_at_its_call(scope: RequestScope) -> None:
    async def go() -> tuple[list[str], str]:
        plugin, holder, _starts = planned(scope, _renamed_argument_server())
        names = sorted(tool.name for tool in plugin.tools)  # the manifest's, before the start
        try:
            with pytest.raises(ToolException, match="outil indisponible") as error:
                await plugin.call(spec(plugin, "web_read"), {"url": PAGE.url})
        finally:
            await holder.aclose()
        return names, str(error.value)

    names, error = asyncio.run(go())
    assert names == ["web_read", "web_search"]
    assert "schéma d'entrée publié différent du manifeste" in error
    payload = entries(scope)[0]["payload"]
    assert payload["status"] == "indisponible"
    assert "schéma d'entrée" in payload["error"]


def test_a_planned_server_that_cannot_start_is_reported_at_each_call(
    scope: RequestScope,
) -> None:
    target = StdioServerParameters(command=sys.executable, args=["-c", "raise SystemExit(3)"])

    async def go() -> list[str]:
        plugin, holder, starts = planned(scope, target)
        search = spec(plugin, "web_search")
        try:
            for query in ("un", "deux"):
                with pytest.raises(McpAdapterError, match="serveur injoignable"):
                    await plugin.call(search, {"query": query})
        finally:
            await holder.aclose()
        return starts

    assert asyncio.run(go()) == ["web_research"]  # one attempt, its reason kept
    assert [e["payload"]["status"] for e in entries(scope)] == ["demarrage_impossible"] * 2


def test_a_start_beyond_the_time_limit_is_cut(scope: RequestScope) -> None:
    plugin = McpPlugin(PLUGIN, scope, target=object(), timeout_s=0.05)

    async def never() -> None:
        await asyncio.sleep(30)

    plugin.plan(never)
    with pytest.raises(McpAdapterError, match="démarrage au-delà"):
        asyncio.run(plugin.call(spec(plugin, "web_search"), {"query": "q"}))
    assert entries(scope)[0]["payload"]["status"] == "demarrage_impossible"


def test_a_start_cut_short_leaves_no_task_behind() -> None:
    closed: list[str] = []

    @asynccontextmanager
    async def hanging(_scope: RequestScope) -> AsyncIterator[Any]:
        try:
            await asyncio.sleep(30)
            yield None
        finally:
            closed.append("fermé")

    async def go() -> None:
        holder = _Holder()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(holder.open(hanging, None), 0.05)  # type: ignore[arg-type]
        await asyncio.wait_for(holder.aclose(), 1)

    asyncio.run(go())
    assert closed == ["fermé"]


def test_the_kill_switch_stops_a_planned_plugin_before_its_start(
    scope: RequestScope, tmp_path: Path
) -> None:
    plugin, _holder, starts = planned(scope)
    (tmp_path / KILL_SWITCH_FILE).parent.mkdir(parents=True)
    (tmp_path / KILL_SWITCH_FILE).write_text("", encoding="utf-8")
    with pytest.raises(ToolRefusedError, match="kill switch"):
        asyncio.run(plugin.call(spec(plugin, "web_search"), {"query": "q"}))
    assert starts == []
    assert entries(scope)[0]["payload"]["status"] == "refuse"


def test_a_planned_plugin_keeps_the_policy_scope(tmp_path: Path) -> None:
    plugin, _holder, starts = planned(replace(make_scope(tmp_path), domain="inconnu"))
    assert plugin.tools == []
    assert set(plugin.skipped) == {"web_read", "web_search"}
    assert all(reason.startswith("politique : ") for reason in plugin.skipped.values())
    assert starts == []


def test_lazy_plugin_plans_a_toolbox_without_starting_it(scope: RequestScope) -> None:
    async def go() -> tuple[list[str], dict[str, Any]]:
        holder = _Holder()
        opener = LazyPlugin(PLUGIN, target=build_server(FakeProvider(), FakeReader()))
        toolbox = opener.plan(scope, holder)
        names = [tool.name for tool in toolbox.tools]
        try:
            return names, await toolbox.call("web_search", {"query": "q"})
        finally:
            await holder.aclose()

    names, result = asyncio.run(go())
    assert sorted(names) == ["web_read", "web_search"]
    assert result["results"][0]["title"] == HITS[0].title


# --- an isolated tool, the code agent's (ADR-054) ----------------------------------------------

TASK_DESCRIPTION = "Tâche de code dans un conteneur isolé (double de test)."
ISOLATED_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False, idempotent_hint=False, destructive_hint=False, open_world_hint=False
)
TASK = IsolatedTask(model="claude-sonnet-5-5", max_usd=Decimal(2))
TOKENS = {"input": 1000, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0, "output": 100}
SPEND = {"modeles": {TASK.model: TOKENS}, "cout_inconnu": False}  # 1000 × 2 + 100 × 10 per MTok


class AgentReply(BaseModel):
    patch: str | dict[str, Any]
    depense: dict[str, Any] | None = None


def _isolated_server(replies: list[Any]) -> MCPServer:
    """One isolated tool; each call takes the next reply, raising it when it is an exception and
    sleeping that many seconds when it is a number."""
    server = MCPServer("web_research")

    @server.tool(
        name="agent_task",
        description=TASK_DESCRIPTION,
        annotations=ISOLATED_ANNOTATIONS,
        structured_output=True,
    )
    async def agent_task(task: str) -> AgentReply:
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, float):
            await asyncio.sleep(reply)
        return AgentReply.model_validate(reply)

    return server


def _isolated_plugin(root: Path) -> Path:
    """A copy of web_research whose manifest declares one EXECUTION_ISOLEE tool."""
    directory = root / "plugins" / "web_research"
    shutil.copytree(PLUGIN, directory, ignore=shutil.ignore_patterns("__pycache__"))

    async def published() -> Any:
        async with Client(_isolated_server([])) as client:
            return (await client.list_tools()).tools

    [tool] = asyncio.run(published())
    draft = "https://json-schema.org/draft/2020-12/schema"
    for name, schema in (("in", tool.input_schema), ("out", tool.output_schema)):
        path = directory / "schemas" / f"agent_task.{name}.json"
        path.write_text(json.dumps({"$schema": draft, **schema}), encoding="utf-8")
    manifest = yaml.safe_load((directory / "plugin.yaml").read_text(encoding="utf-8"))
    manifest["tools"] = [
        {
            "name": "agent_task",
            "description": TASK_DESCRIPTION,
            "action_class": "EXECUTION_ISOLEE",
            "annotations": {
                "readOnlyHint": False,
                "idempotentHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
            },
            "input_schema": "schemas/agent_task.in.json",
            "output_schema": "schemas/agent_task.out.json",
        }
    ]
    manifest["runtime"].pop("priced_tools", None)
    (directory / "plugin.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return directory


def code_scope(
    root: Path, isolation: IsolatedTask | None = TASK, limits: PerRequest = LIMITS
) -> RequestScope:
    """A request of the code pack; its task is a copy, so that what it counts stays its own."""
    task = None if isolation is None else IsolatedTask(isolation.model, isolation.max_usd)
    return replace(make_scope(root, limits), domain="code", isolation=task)


def isolated_session(
    scope: RequestScope,
    directory: Path,
    replies: list[Any],
    action: Callable[..., Any],
    timeout_s: float | None = None,
) -> Any:
    async def go() -> Any:
        server = _isolated_server(replies)
        async with McpPlugin(directory, scope, target=server, timeout_s=timeout_s) as plugin:
            return await action(plugin)

    return asyncio.run(go())


async def _never() -> None:
    raise AssertionError("never started")


def test_an_isolated_tool_is_offered_only_to_an_isolated_request(tmp_path: Path) -> None:
    directory = _isolated_plugin(tmp_path)
    for root, isolation in ((tmp_path / "a", None), (tmp_path / "b", TASK)):
        scope = code_scope(root, isolation)
        listed = isolated_session(scope, directory, [], lambda p: asyncio.sleep(0, p))
        planned = McpPlugin(directory, scope, target=object())
        planned.plan(_never)
        for plugin in (listed, planned):
            if isolation is None:
                assert (plugin.tools, plugin.skipped) == ([], {"agent_task": ISOLATION_REFUSAL})
            else:
                assert [tool.name for tool in plugin.tools] == ["agent_task"]
                assert plugin.skipped == {}


def test_isolation_does_not_bypass_the_policy(tmp_path: Path) -> None:
    """A task scope outside the code pack: the policy still refuses (ADR-051)."""
    scope = replace(code_scope(tmp_path), domain="generaliste")
    plugin = isolated_session(scope, _isolated_plugin(tmp_path), [], lambda p: asyncio.sleep(0, p))
    assert plugin.tools == []
    assert plugin.skipped["agent_task"].startswith("politique : ")
    assert "aucune capacité EXECUTION_ISOLEE" in plugin.skipped["agent_task"]


def test_a_call_outside_isolation_is_refused_before_anything(tmp_path: Path) -> None:
    scope = code_scope(tmp_path, None)
    plugin = McpPlugin(_isolated_plugin(tmp_path), scope, target=object())
    plugin.plan(_never)
    with pytest.raises(ToolException, match=r"agent_task : classe EXECUTION_ISOLEE"):
        asyncio.run(plugin.call(spec(plugin, "agent_task"), {"task": "corrige"}))
    [entry] = entries(scope)
    assert (entry["payload"]["status"], entry["payload"]["error"]) == (
        "hors_perimetre",
        ISOLATION_REFUSAL,
    )
    assert (scope.budget.tool_calls, scope.meter.llm_calls) == (0, ())


def test_an_isolated_call_charges_the_spend_it_reports(tmp_path: Path) -> None:
    scope = code_scope(tmp_path)
    reply = {"patch": "diff --git a/x b/x", "depense": SPEND}
    message = isolated_session(
        scope,
        _isolated_plugin(tmp_path),
        [reply],
        lambda p: invoke(p, "agent_task", {"task": "corrige"}),
    )
    assert message.status != "error", message.content
    [call] = scope.meter.llm_calls
    assert (call.role, call.tier, call.model) == ("web_research", "agent", TASK.model)
    assert call.usd == Decimal("0.003000")
    assert scope.meter.total_tokens == 1100  # counted against the task's budget
    [entry] = entries(scope)
    assert entry["payload"]["status"] == "ok"
    assert entry["payload"]["spend"] == [call.to_payload()]


@pytest.mark.parametrize(
    ("reply", "status"),
    [
        ({"patch": "diff"}, "ok"),
        ({"patch": "diff", "depense": {"modeles": {}}}, "ok"),
        (ValueError("échec de la tâche"), "erreur"),
    ],
    ids=["no-report", "unreadable", "failed"],
)
def test_a_sent_task_without_a_readable_report_costs_its_ceiling(
    tmp_path: Path, reply: Any, status: str
) -> None:
    scope = code_scope(tmp_path)
    isolated_session(
        scope,
        _isolated_plugin(tmp_path),
        [reply],
        lambda p: invoke(p, "agent_task", {"task": "corrige"}),
    )
    [call] = scope.meter.llm_calls
    assert (call.tier, call.usd) == (CEILING_TIER, Decimal("2.000000"))
    [entry] = entries(scope)
    assert entry["payload"]["status"] == status
    assert entry["payload"]["spend"] == [call.to_payload()]


def test_a_task_whose_server_cannot_start_costs_nothing(tmp_path: Path) -> None:
    """Nothing was sent: no model could run, so nothing is charged."""
    scope = code_scope(tmp_path)
    plugin = McpPlugin(_isolated_plugin(tmp_path), scope, target=object())

    async def failing() -> None:
        raise McpAdapterError("plugin « web_research » : démarrage impossible")

    plugin.plan(failing)
    with pytest.raises(McpAdapterError, match="démarrage impossible"):
        asyncio.run(plugin.call(spec(plugin, "agent_task"), {"task": "corrige"}))
    assert scope.meter.llm_calls == ()
    [entry] = entries(scope)
    assert entry["payload"]["status"] == "demarrage_impossible"
    assert "spend" not in entry["payload"]


def test_a_tool_of_another_class_charges_no_spend(scope: RequestScope) -> None:
    session(scope, lambda p: invoke(p, "web_search", {"query": "q"}))
    assert scope.meter.llm_calls == ()
    assert entries(scope)[0]["payload"]["spend"] is None
    assert "patch_sha256" not in entries(scope)[0]["payload"]


DIGEST = "0123456789abcdef" * 4


@pytest.mark.parametrize(
    ("patch", "digest"),
    [
        ({"sha256": DIGEST}, DIGEST),
        ({"sha256": DIGEST.upper()}, None),
        ({"sha256": DIGEST[:-1]}, None),
        ({"sha256": 7}, None),
        ("diff --git a/x b/x", None),
    ],
    ids=["digest", "upper-case", "short", "not-text", "not-a-mapping"],
)
def test_an_isolated_call_journals_the_digest_of_its_patch(
    tmp_path: Path, patch: Any, digest: str | None
) -> None:
    """The patch Lucas applies is traced to its request (R11); a malformed digest is not kept."""
    scope = code_scope(tmp_path)
    isolated_session(
        scope,
        _isolated_plugin(tmp_path),
        [{"patch": patch, "depense": SPEND}],
        lambda p: invoke(p, "agent_task", {"task": "corrige"}),
    )
    [entry] = entries(scope)
    assert entry["payload"]["patch_sha256"] == digest


def test_a_failed_isolated_call_journals_no_digest(tmp_path: Path) -> None:
    scope = code_scope(tmp_path)
    isolated_session(
        scope,
        _isolated_plugin(tmp_path),
        [ValueError("échec de la tâche")],
        lambda p: invoke(p, "agent_task", {"task": "corrige"}),
    )
    [entry] = entries(scope)
    assert (entry["payload"]["status"], entry["payload"]["patch_sha256"]) == ("erreur", None)


def test_an_isolated_task_counts_nothing_into_its_equality() -> None:
    assert IsolatedTask(TASK.model, TASK.max_usd, sent=1) == TASK


@pytest.mark.parametrize("concurrent", [False, True], ids=["one-after-the-other", "together"])
def test_a_request_sends_one_isolated_task_at_most(tmp_path: Path, concurrent: bool) -> None:
    """A task charged its ceiling counts no token: one task keeps the spend near max_usd (C1)."""
    scope = code_scope(tmp_path)
    reply = {"patch": "diff --git a/x b/x", "depense": SPEND}

    async def twice(plugin: McpPlugin) -> list[ToolMessage]:
        calls = [invoke(plugin, "agent_task", {"task": task}) for task in ("un", "deux")]
        if concurrent:
            return list(await asyncio.gather(*calls))
        return [await call for call in calls]

    messages = isolated_session(scope, _isolated_plugin(tmp_path), [reply, reply], twice)
    assert sorted(message.status for message in messages) == ["error", "success"]
    [refused] = [message for message in messages if message.status == "error"]
    assert TASK_LIMIT_REFUSAL in str(refused.content)
    assert len(scope.meter.llm_calls) == 1
    assert scope.budget.tool_calls == 1
    assert scope.isolation is not None and scope.isolation.sent == 1
    payloads = sorted((entry["payload"] for entry in entries(scope)), key=lambda p: p["status"])
    assert [p["status"] for p in payloads] == ["budget_depasse", "ok"]
    assert payloads[0]["limit"] == "isolated_tasks"
    assert "spend" not in payloads[0]


def _engage(root: Path) -> None:
    (root / KILL_SWITCH_FILE).parent.mkdir(parents=True, exist_ok=True)
    (root / KILL_SWITCH_FILE).write_text("", encoding="utf-8")


@pytest.mark.parametrize("cause", ["kill-switch", "live"])
def test_an_open_isolation_still_obeys_the_policy_at_its_call(tmp_path: Path, cause: str) -> None:
    """The kill switch or an enabled live configuration refuses the task: nothing sent or paid."""
    scope = code_scope(tmp_path)
    plugin = McpPlugin(_isolated_plugin(tmp_path), scope, target=object())
    plugin.plan(_never)
    assert [tool.name for tool in plugin.tools] == ["agent_task"]
    if cause == "live":
        scope = replace(scope, live_enabled=True)
        plugin._scope = scope
    else:
        _engage(tmp_path)
    with pytest.raises(ToolRefusedError):
        asyncio.run(plugin.call(spec(plugin, "agent_task"), {"task": "corrige"}))
    [entry] = entries(scope)
    assert entry["payload"]["status"] == "refuse"
    assert (scope.budget.tool_calls, scope.meter.llm_calls) == (0, ())
    assert scope.isolation is not None and scope.isolation.sent == 0


def test_an_open_isolation_still_obeys_the_request_budget(tmp_path: Path) -> None:
    limits = PerRequest(max_tool_calls=1, max_tokens=150000, max_seconds=120)
    scope = code_scope(tmp_path, limits=limits)
    scope.budget.charge_tool_call()  # an earlier call took the last one
    plugin = McpPlugin(_isolated_plugin(tmp_path), scope, target=object())
    plugin.plan(_never)
    with pytest.raises(RequestBudgetExceeded):
        asyncio.run(plugin.call(spec(plugin, "agent_task"), {"task": "corrige"}))
    [entry] = entries(scope)
    assert (entry["payload"]["status"], entry["payload"]["limit"]) == (
        "budget_depasse",
        "tool_calls",
    )
    assert scope.meter.llm_calls == ()
    assert scope.isolation is not None and scope.isolation.sent == 0


def test_a_task_cut_at_its_timeout_costs_its_ceiling(tmp_path: Path) -> None:
    """The proxy may have spent until the cut: its ceiling is charged (R7)."""
    scope = code_scope(tmp_path)
    message = isolated_session(
        scope,
        _isolated_plugin(tmp_path),
        [5.0],
        lambda p: invoke(p, "agent_task", {"task": "corrige"}),
        timeout_s=0.05,
    )
    assert message.status == "error"
    [call] = scope.meter.llm_calls
    assert (call.tier, call.usd) == (CEILING_TIER, Decimal("2.000000"))
    [entry] = entries(scope)
    assert entry["payload"]["status"] == "delai"
    assert entry["payload"]["spend"] == [call.to_payload()]
