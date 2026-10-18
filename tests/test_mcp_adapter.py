"""MCP client adapter: registry scoping, policy, budget, time limits and audit (ADR-007).

No ``from __future__ import annotations`` here: the drift servers below declare MCP tools, whose
signatures the SDK reads at runtime.
"""

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import ToolMessage
from mcp import StdioServerParameters
from mcp.server import MCPServer

from core.audit.chain import AuditJournal, verify
from core.budget.gate import RequestBudget, RequestBudgetExceeded
from core.config import load_config
from core.config.loader import PerRequest
from core.mcp.adapter import (
    McpAdapterError,
    McpPlugin,
    RequestScope,
    ToolRefusedError,
    server_environment,
)
from core.models import CostCalculator, Meter
from core.policy.engine import KILL_SWITCH_FILE
from plugins.web_research.guard import FetchError
from plugins.web_research.models import PageText, SearchResults
from plugins.web_research.search import Hit
from plugins.web_research.server import ANNOTATIONS, DESCRIPTIONS, build_server

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
