"""What one request carries through the graph besides its state.

The graph state may be traced (commit 13); the ``Run`` is not. It holds the raw question, the
pseudonym table and the raw URLs Lucas gave, and it hands out the metered models (each call
checked against the request's budget and the kill switch) and the tools of the routed pack's
plugins. A plugin's server starts at the call of its first tool (B98): a request that calls two
of the finance pack's seven plugins starts two processes, not seven.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool, ToolException

from core.audit import AuditJournal
from core.budget.gate import RequestBudget, RequestBudgetExceeded
from core.config.loader import Config
from core.mcp.adapter import McpAdapterError, McpPlugin, RequestScope
from core.models.meter import Meter
from core.models.router import ModelRouter, Role, Seat
from core.orchestrator.packs import Pack, load_packs
from core.orchestrator.prompts import PromptSet
from core.policy.engine import kill_switch_engaged

if TYPE_CHECKING:
    from core.committee.engine import CommitteeSpec

# Output ceilings per role, below what is left of the request's token budget (R9: a change here
# changes the behaviour under evaluation).
OUTPUT_CAPS: Mapping[Role, int] = MappingProxyType(
    {
        "classifier": 800,
        "verifier": 800,
        "reader": 4000,
        "planner": 8000,
        "planner_complex": 16000,
        "committee": 8000,
    }
)
WEB_PLUGIN = "web_research"


class KillSwitchEngaged(Exception):
    """R4: the kill switch was engaged while the request ran; no model is called again."""


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
    async def call(
        self, name: str, arguments: dict[str, Any], *, journaled: Mapping[str, Any] | None = None
    ) -> dict[str, Any]: ...


ToolboxOpener = Callable[[RequestScope], AbstractAsyncContextManager[Toolbox]]
PluginOpeners = Callable[[str], ToolboxOpener | None]  # plugin → its opener, None if unknown


class McpToolbox:
    def __init__(self, plugin: McpPlugin) -> None:
        self._plugin = plugin
        self._tools = tuple(plugin.tools)  # planned or published: those given to the planner
        kept = {tool.name for tool in self._tools}
        self._specs = {spec.name: spec for spec in plugin.manifest.tools if spec.name in kept}

    @property
    def tools(self) -> Sequence[BaseTool]:
        return self._tools

    @property
    def skipped(self) -> Mapping[str, str]:
        return dict(self._plugin.skipped)

    @property
    def version(self) -> str:
        return self._plugin.version

    async def call(
        self, name: str, arguments: dict[str, Any], *, journaled: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        spec = self._specs.get(name)
        if spec is None:
            raise ToolException(f"{name} : outil indisponible pour cette requête")
        _content, result = await self._plugin.call(spec, arguments, journaled=journaled)
        return result


class LazyPlugin:
    """A plugin's MCP server, started at the call of its first tool (B98).

    ``plan`` gives its tools at once, from the manifest that the registry has checked and as the
    policy engine scopes them; the holder starts the server at the first call (McpPlugin). Called
    as an opener, it starts the server at once.
    """

    def __init__(self, plugin_dir: Path, *, target: Any = None) -> None:
        self.plugin_dir = plugin_dir
        self._target = target

    @asynccontextmanager
    async def __call__(self, scope: RequestScope) -> AsyncIterator[Toolbox]:
        async with McpPlugin(self.plugin_dir, scope, target=self._target) as plugin:
            yield McpToolbox(plugin)

    def plan(self, scope: RequestScope, holder: _Holder) -> Toolbox:
        plugin = McpPlugin(self.plugin_dir, scope, target=self._target)

        @asynccontextmanager
        async def enter(_scope: RequestScope) -> AsyncIterator[Toolbox]:
            async with plugin:
                yield McpToolbox(plugin)

        async def connect() -> None:
            await holder.open(enter, scope)

        plugin.plan(connect)
        return McpToolbox(plugin)


def mcp_toolbox(plugin_dir: Path) -> LazyPlugin:
    return LazyPlugin(plugin_dir)


class PluginSet:
    """The tools of the routed pack's plugins as one toolbox, in the order of the pack's manifest.

    A plugin that failed to open, a tool whose name another plugin of the pack already gave and a
    tool beyond ``limit`` (``max_tools_to_planner``) are skipped, each with its reason.
    """

    def __init__(
        self, opened: Sequence[tuple[str, Toolbox]], failed: Mapping[str, str], limit: int
    ) -> None:
        self._owners: dict[str, Toolbox] = {}
        tools: list[BaseTool] = []
        skipped = dict(failed)
        for plugin, toolbox in opened:
            skipped.update(toolbox.skipped)
            for tool in toolbox.tools:
                if tool.name in self._owners:
                    skipped[f"{plugin}.{tool.name}"] = "nom déjà donné par un autre plugin du pack"
                elif len(tools) >= limit:
                    skipped[tool.name] = f"au-delà des {limit} outils transmis au planificateur"
                else:
                    self._owners[tool.name] = toolbox
                    tools.append(tool)
        self._tools = tuple(tools)
        self._skipped = skipped
        self._version = ", ".join(toolbox.version for _plugin, toolbox in opened) or "aucun"

    @property
    def tools(self) -> Sequence[BaseTool]:
        return self._tools

    @property
    def skipped(self) -> Mapping[str, str]:
        return dict(self._skipped)

    @property
    def version(self) -> str:
        return self._version

    async def call(
        self, name: str, arguments: dict[str, Any], *, journaled: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        owner = self._owners.get(name)
        if owner is None:
            raise ToolException(f"{name} : outil indisponible pour cette requête")
        return await owner.call(name, arguments, journaled=journaled)


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
        try:
            return await ready
        except asyncio.CancelledError:  # a start cut at its timeout (B98): the server task stops
            self._task.cancel()
            raise

    async def aclose(self) -> None:
        self._release.set()
        if self._task is not None:
            await asyncio.wait({self._task})
            if not self._task.cancelled():
                self._task.exception()  # retrieved: an error on closing never masks the answer


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
    packs: Mapping[str, Pack] = field(default_factory=load_packs)
    open_plugin: PluginOpeners | None = None
    callbacks: tuple[BaseCallbackHandler, ...] = ()
    url_map: dict[str, str] = field(default_factory=dict, repr=False)  # as shown → as given
    toolbox: PluginSet | None = None
    models_used: dict[str, str] = field(default_factory=dict)  # role (or seat label) → model id
    audited: bool = False  # the DECISION entry of node 8 is written
    last_state: Any = field(default=None, repr=False)  # the state the running node was given
    committee_forced: bool = False  # cerveau ask --comite (D15)
    committee_for: Callable[[str], CommitteeSpec | None] | None = field(default=None, repr=False)
    budget_clock: Callable[[], float] | None = field(default=None, repr=False)
    _holders: list[_Holder] = field(default_factory=list, repr=False)

    def _time_exceeded(self) -> RequestBudgetExceeded:
        maximum = self.budget.max_seconds  # the request's, or the committee session's
        return RequestBudgetExceeded("seconds", round(self.budget.elapsed_s, 3), maximum)

    async def invoke(
        self,
        role: Role,
        messages: Sequence[BaseMessage],
        *,
        tools: Sequence[BaseTool] = (),
        seat: Seat | None = None,
    ) -> AIMessage:
        """One model call within what is left of the request's tokens and seconds (R4: never with
        the kill switch engaged). ``seat``: the committee member speaking (role ``committee``)."""
        if kill_switch_engaged(self.project_root):
            raise KillSwitchEngaged
        self.budget.check()
        remaining = self.budget.remaining_seconds()
        if remaining <= 0:
            raise self._time_exceeded()
        cap = min(OUTPUT_CAPS[role], self.budget.remaining_tokens())
        model = self.router.chat(
            role, self.meter, timeout_s=remaining, max_output_tokens=cap, seat=seat
        )
        self.models_used[seat.label if seat else role] = self.router.model_id(role, seat)
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

    async def open_tools(self, domain: str, plugins: Sequence[str]) -> PluginSet:
        """The plugins' tools, once per request; one that fails is skipped. A ``LazyPlugin``
        starts at its first call (B98), any other opener at once, side by side."""
        if self.toolbox is not None:
            return self.toolbox
        scope = RequestScope(
            request_id=self.request_id,
            domain=domain,
            autonomy=self.config.autonomy,
            journal=self.journal,
            budget=self.budget,
            meter=self.meter,
            project_root=self.project_root,
            live_enabled=self.config.live.enabled,
        )

        async def open_one(plugin: str) -> Toolbox | str:
            opener = self.open_plugin(plugin) if self.open_plugin is not None else None
            if opener is None:
                return "plugin non configuré"
            holder = _Holder()
            self._holders.append(holder)
            try:
                if isinstance(opener, LazyPlugin):
                    return opener.plan(scope, holder)
                return await holder.open(opener, scope)
            except McpAdapterError as exc:
                return str(exc)

        results = await asyncio.gather(*(open_one(plugin) for plugin in plugins))
        opened = [(p, r) for p, r in zip(plugins, results, strict=True) if not isinstance(r, str)]
        failed = {p: r for p, r in zip(plugins, results, strict=True) if isinstance(r, str)}
        limit = self.config.models.routing.max_tools_to_planner
        self.toolbox = PluginSet(opened, failed, limit)
        return self.toolbox

    async def aclose(self) -> None:
        await asyncio.gather(*(holder.aclose() for holder in self._holders))
