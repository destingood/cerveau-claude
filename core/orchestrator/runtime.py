"""What one request carries through the graph besides its state.

The graph state may be traced (commit 13); the ``Run`` is not. It holds the raw question, the
pseudonym table and the raw URLs Lucas gave, and it hands out the metered models (each call
checked against the request's budget) and the plugin's tools.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool, ToolException

from core.audit import AuditJournal
from core.budget.gate import RequestBudget, RequestBudgetExceeded
from core.config.loader import Config
from core.mcp.adapter import McpAdapterError, McpPlugin, RequestScope
from core.models.meter import Meter
from core.models.router import ModelRouter, Role
from core.orchestrator.prompts import PromptSet

# Output ceilings per role, below what is left of the request's token budget (R9: a change here
# changes the behaviour under evaluation).
OUTPUT_CAPS: Mapping[Role, int] = MappingProxyType(
    {
        "classifier": 800,
        "verifier": 800,
        "reader": 4000,
        "planner": 8000,
        "planner_complex": 16000,
    }
)
WEB_PLUGIN = "web_research"


class PseudonymiserLike(Protocol):
    def pseudonymise(self, text: str) -> str: ...
    def reidentify(self, text: str) -> str: ...
    def counts(self) -> dict[str, int]: ...


class Toolbox(Protocol):
    """The tools of one plugin, already scoped by the registry and the policy engine."""

    @property
    def tools(self) -> Sequence[BaseTool]: ...
    @property
    def skipped(self) -> Mapping[str, str]: ...
    @property
    def version(self) -> str: ...
    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


ToolboxOpener = Callable[[RequestScope], AbstractAsyncContextManager[Toolbox]]


class McpToolbox:
    def __init__(self, plugin: McpPlugin) -> None:
        self._plugin = plugin
        kept = {tool.name for tool in plugin.tools}
        self._specs = {spec.name: spec for spec in plugin.manifest.tools if spec.name in kept}

    @property
    def tools(self) -> Sequence[BaseTool]:
        return tuple(self._plugin.tools)

    @property
    def skipped(self) -> Mapping[str, str]:
        return dict(self._plugin.skipped)

    @property
    def version(self) -> str:
        return self._plugin.version

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = self._specs.get(name)
        if spec is None:
            raise ToolException(f"{name} : outil indisponible pour cette requête")
        _content, result = await self._plugin.call(spec, arguments)
        return result


def mcp_toolbox(plugin_dir: Path) -> ToolboxOpener:
    @asynccontextmanager
    async def open_toolbox(scope: RequestScope) -> AsyncIterator[Toolbox]:
        async with McpPlugin(plugin_dir, scope) as plugin:
            yield McpToolbox(plugin)

    return open_toolbox


class _Holder:
    """Keeps a toolbox open in a task of its own.

    The MCP client runs an anyio task group, which must be left by the task that entered it;
    LangGraph runs each node in its own task, so the toolbox cannot be opened in a node and
    closed by the runner. The holder task opens it, waits, and closes it on ``aclose``.
    """

    def __init__(self) -> None:
        self._release = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def open(self, opener: ToolboxOpener, scope: RequestScope) -> Toolbox:
        loop = asyncio.get_running_loop()
        ready: asyncio.Future[Toolbox] = loop.create_future()

        async def hold() -> None:
            try:
                async with opener(scope) as toolbox:
                    ready.set_result(toolbox)
                    await self._release.wait()
            except BaseException as exc:
                if not ready.done():
                    ready.set_exception(exc)
                else:
                    raise

        self._task = asyncio.create_task(hold())
        return await ready

    async def aclose(self) -> None:
        self._release.set()
        if self._task is not None:
            with suppress(Exception):
                await self._task


@dataclass(eq=False)
class Run:
    request_id: str
    config: Config
    router: ModelRouter
    meter: Meter
    budget: RequestBudget
    journal: AuditJournal
    project_root: Path
    prompts: PromptSet
    now: datetime
    pseudonymiser: PseudonymiserLike = field(repr=False)
    raw_question: str = field(repr=False)
    open_toolbox: ToolboxOpener | None = None
    callbacks: tuple[BaseCallbackHandler, ...] = ()
    url_map: dict[str, str] = field(default_factory=dict, repr=False)  # as shown → as given
    toolbox: Toolbox | None = None
    toolbox_error: str | None = None
    models_used: dict[str, str] = field(default_factory=dict)  # role → model id
    audited: bool = False  # the DECISION entry of node 8 is written
    _holder: _Holder = field(default_factory=_Holder, repr=False)

    def _time_exceeded(self) -> RequestBudgetExceeded:
        maximum = self.config.budgets.per_request.max_seconds
        return RequestBudgetExceeded("seconds", round(self.budget.elapsed_s, 3), maximum)

    async def invoke(
        self, role: Role, messages: Sequence[BaseMessage], *, tools: Sequence[BaseTool] = ()
    ) -> AIMessage:
        """One model call within what is left of the request's tokens and seconds."""
        self.budget.check()
        remaining = self.budget.remaining_seconds()
        if remaining <= 0:
            raise self._time_exceeded()
        cap = min(OUTPUT_CAPS[role], self.budget.remaining_tokens())
        model = self.router.chat(role, self.meter, timeout_s=remaining, max_output_tokens=cap)
        self.models_used[role] = self.router.model_id(role)
        runnable = model.bind_tools(list(tools)) if tools else model
        call = runnable.ainvoke(list(messages), config={"callbacks": list(self.callbacks)})
        try:
            reply = await asyncio.wait_for(call, remaining)
        except TimeoutError:
            raise self._time_exceeded() from None
        except Exception:
            self.budget.check()  # the HTTP client's own time-out is the request's time limit
            raise
        if not isinstance(reply, AIMessage):
            raise TypeError(f"réponse inattendue du modèle : {type(reply).__name__}")
        return reply

    async def open_tools(self, domain: str) -> Toolbox | None:
        """Opens the plugin once per request; ``None`` (and ``toolbox_error``) if unavailable."""
        if self.toolbox is not None or self.toolbox_error is not None:
            return self.toolbox
        if self.open_toolbox is None:
            self.toolbox_error = "aucun plugin d'outils configuré"
            return None
        scope = RequestScope(
            request_id=self.request_id,
            domain=domain,
            autonomy=self.config.autonomy,
            journal=self.journal,
            budget=self.budget,
            meter=self.meter,
            project_root=self.project_root,
        )
        try:
            self.toolbox = await self._holder.open(self.open_toolbox, scope)
        except McpAdapterError as exc:
            self.toolbox_error = str(exc)
        return self.toolbox

    async def aclose(self) -> None:
        await self._holder.aclose()
