"""MCP client adapter: registry-scoped LangChain tools over the official SDK (ADR-007).

One ``McpPlugin`` serves one request. It starts the plugin server over stdio with a whitelisted
environment, keeps only the tools that the validated manifest declares *and* that the server
publishes identically (description, annotations, schemas), and asks the policy engine about each
tool's action class. Every call is checked again (kill switch, policy), counted in the request
budget, time-limited and journaled as ``TOOL_CALL`` without the result content.

The LangChain tools answer in ``content_and_artifact`` form: the message content is a neutral
status line and the structured result travels as the artifact. External content therefore never
reaches a model through this adapter; the graph decides what the reader and the planner see (R5).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool, ToolException
from mcp import Client, StdioServerParameters
from mcp.shared.exceptions import MCPError
from mcp.types import Tool

from core.audit.chain import AuditJournal
from core.budget.gate import RequestBudget, RequestBudgetExceeded
from core.config.loader import AutonomyConfig
from core.models.meter import Meter, SearchCall
from core.policy.engine import PolicyDecision, decide, kill_switch_engaged
from core.registry.manifest import PluginManifest, ToolSpec, validate_plugin

TOOL_TIMEOUT_S = 30.0
MAX_ARGUMENT_CHARS = 2048
MAX_ERROR_CHARS = 300


@dataclass(frozen=True)
class PluginRuntime:
    """How to start a plugin server. Not part of the C.1 manifest yet (backlog B26)."""

    module: str
    env: tuple[str, ...] = ()
    priced_tools: Mapping[str, str] = field(default_factory=dict)  # tool → pricing.search key


RUNTIMES: Mapping[str, PluginRuntime] = {
    "web_research": PluginRuntime(
        "plugins.web_research",
        env=("BRAVE_SEARCH_API_KEY",),
        priced_tools={"web_search": "brave"},
    ),
}


class McpAdapterError(Exception):
    """The plugin cannot be used: refused by the registry, unknown runtime, server down."""


class ToolRefusedError(Exception):
    """The policy refuses a call (kill switch, autonomy matrix); the request must stop."""

    def __init__(self, decision: PolicyDecision) -> None:
        super().__init__(" ; ".join(decision.reasons))
        self.decision = decision


@dataclass(frozen=True)
class RequestScope:
    """What every tool call of one request is checked against and journaled with."""

    request_id: str
    domain: str
    autonomy: AutonomyConfig
    journal: AuditJournal
    budget: RequestBudget
    meter: Meter
    project_root: Path


def server_environment(names: Sequence[str], environ: Mapping[str, str]) -> dict[str, str]:
    """The declared variables only, copied by name; their values are never logged.

    The SDK adds its own short list of non-secret system variables (PATH, SYSTEMROOT, TEMP…).
    """
    return {name: environ[name] for name in names if environ.get(name)}


def _published_annotations(tool: Tool) -> dict[str, Any] | None:
    if tool.annotations is None:
        return None
    return tool.annotations.model_dump(by_alias=True, exclude_none=True)


def _clip(arguments: Mapping[str, Any]) -> dict[str, Any]:
    clipped: dict[str, Any] = {}
    for key, value in arguments.items():
        if not isinstance(value, str | int | float | bool | None):
            value = json.dumps(value, ensure_ascii=False, default=str)
        if isinstance(value, str) and len(value) > MAX_ARGUMENT_CHARS:
            value = value[:MAX_ARGUMENT_CHARS] + "…"
        clipped[str(key)[:64]] = value
    return clipped


class McpPlugin:
    """A plugin server opened for one request: ``async with McpPlugin(...) as plugin``."""

    def __init__(
        self,
        directory: Path,
        scope: RequestScope,
        *,
        target: Any = None,
        timeout_s: float = TOOL_TIMEOUT_S,
        environ: Mapping[str, str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        report = validate_plugin(directory)
        if not report.ok or report.manifest is None:
            raise McpAdapterError(
                f"plugin « {directory.name} » refusé par le registre : " + " ; ".join(report.errors)
            )
        self.manifest: PluginManifest = report.manifest
        self.directory = directory
        self.runtime = RUNTIMES.get(self.manifest.id, PluginRuntime(""))
        if target is None:
            if not self.runtime.module:
                raise McpAdapterError(f"plugin « {self.manifest.id} » : démarrage inconnu")
            source = os.environ if environ is None else environ
            target = StdioServerParameters(
                command=sys.executable,
                args=["-m", self.runtime.module],
                env=server_environment(self.runtime.env, source),
                cwd=str(scope.project_root),
            )
        self._target = target
        self._scope = scope
        self._timeout_s = timeout_s
        self._clock = clock
        self._stack = AsyncExitStack()
        self._client: Client | None = None
        self.tools: list[BaseTool] = []
        self.skipped: dict[str, str] = {}

    async def __aenter__(self) -> McpPlugin:
        try:
            self._client = await self._stack.enter_async_context(Client(self._target))
            listed = (await self._client.list_tools()).tools
        except Exception as exc:
            await self._stack.aclose()
            raise McpAdapterError(
                f"plugin « {self.manifest.id} » : serveur injoignable ({type(exc).__name__})"
            ) from None
        self.tools = self._scope_tools(listed)
        return self

    async def __aexit__(
        self, kind: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self._stack.aclose()
        self._client = None

    @property
    def version(self) -> str:
        return f"{self.manifest.id}@{self.manifest.version}"

    def _decide(self, spec: ToolSpec) -> PolicyDecision:
        scope = self._scope
        return decide(
            scope.autonomy,
            request_id=scope.request_id,
            domain=scope.domain,
            action_class=spec.action_class,
            kill_switch=kill_switch_engaged(scope.project_root),
        )

    def _schema(self, path: str) -> dict[str, Any]:
        schema = json.loads((self.directory / path).read_text(encoding="utf-8"))
        schema.pop("$schema", None)
        return schema

    def _mismatch(self, spec: ToolSpec, tool: Tool | None) -> str | None:
        if tool is None:
            return "déclaré dans le manifeste mais non publié par le serveur"
        if tool.description != spec.description:
            return "description publiée différente du manifeste"
        if _published_annotations(tool) != spec.annotations.model_dump():
            return "annotations publiées différentes du manifeste"
        if tool.input_schema != self._schema(spec.input_schema):
            return "schéma d'entrée publié différent du manifeste"
        if tool.output_schema != self._schema(spec.output_schema):
            return "schéma de sortie publié différent du manifeste"
        return None

    def _scope_tools(self, listed: Sequence[Tool]) -> list[BaseTool]:
        published = {tool.name: tool for tool in listed}
        kept: list[BaseTool] = []
        for spec in self.manifest.tools:
            reason = self._mismatch(spec, published.pop(spec.name, None))
            if reason is None:
                decision = self._decide(spec)
                if not decision.allowed:
                    reason = "politique : " + " ; ".join(decision.reasons)
            if reason is not None:
                self.skipped[spec.name] = reason
            else:
                kept.append(self._as_langchain(spec))
        for name in published:
            self.skipped[name] = "publié par le serveur mais absent du manifeste"
        return kept

    def _as_langchain(self, spec: ToolSpec) -> BaseTool:
        async def run(**arguments: Any) -> tuple[str, dict[str, Any]]:
            return await self.call(spec, arguments)

        return StructuredTool.from_function(
            coroutine=run,
            name=spec.name,
            description=spec.description,
            args_schema=self._schema(spec.input_schema),
            response_format="content_and_artifact",
            handle_tool_error=True,
        )

    def _journal(self, spec: ToolSpec, arguments: Mapping[str, Any], **details: Any) -> None:
        self._scope.journal.append(
            actor="orchestrator",
            event="TOOL_CALL",
            request_id=self._scope.request_id,
            versions={"plugin": self.version},
            payload={
                "plugin": self.manifest.id,
                "tool": spec.name,
                "action_class": spec.action_class,
                "arguments": _clip(arguments),
                **details,
            },
            redactions=("result_content",),
        )

    async def call(
        self,
        spec: ToolSpec,
        arguments: dict[str, Any],
        *,
        journaled: Mapping[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """One checked, counted, time-limited and journaled call; errors become ToolException.

        ``journaled`` stands for ``arguments`` in the journal when these hold data about Lucas that
        the journal must not keep (R6): an address he gave goes there in its masked form.
        """
        shown = arguments if journaled is None else journaled
        decision = self._decide(spec)
        if not decision.allowed:
            self._journal(spec, shown, status="refuse", policy=decision.to_payload())
            raise ToolRefusedError(decision)
        try:
            self._scope.budget.charge_tool_call()
        except RequestBudgetExceeded as exc:
            self._journal(spec, shown, status="budget_depasse", limit=exc.limit)
            raise
        if self._client is None:
            raise McpAdapterError(f"plugin « {self.manifest.id} » : session fermée")
        timeout = min(self._timeout_s, self._scope.budget.remaining_seconds())
        provider = self.runtime.priced_tools.get(spec.name)
        search: SearchCall | None = None
        status, error, size, result = "ok", None, None, None
        start = self._clock()
        try:
            if provider is not None:  # counted once sent, whatever the outcome (prudence)
                search = self._scope.meter.record_search(provider)
            reply = await asyncio.wait_for(
                self._client.call_tool(spec.name, arguments, read_timeout_seconds=timeout),
                timeout,
            )
        except TimeoutError:
            status, error = "delai", f"délai de {timeout:.0f} s dépassé"
        except MCPError as exc:
            status, error = "erreur_protocole", f"MCP {exc.code} : {exc.message}"
        except Exception as exc:
            status, error = "erreur_client", f"appel impossible ({type(exc).__name__})"
        else:
            if reply.is_error:
                texts = (getattr(block, "text", "") for block in reply.content)
                status, error = "erreur", " ".join(texts).strip() or "erreur sans message"
            elif reply.structured_content is None:
                status, error = "resultat_invalide", "résultat non structuré"
            else:
                result = reply.structured_content
                size = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
        self._journal(
            spec,
            shown,
            status=status,
            duration_ms=round((self._clock() - start) * 1000),
            result_bytes=size,
            error=error[:MAX_ERROR_CHARS] if error else None,
            search=search.to_payload() if search else None,
            tool_calls=self._scope.budget.tool_calls,
        )
        if result is None:
            raise ToolException(f"{spec.name} : {(error or '')[:MAX_ERROR_CHARS]}")
        return f"{spec.name} : résultat structuré de {size} octets (données externes).", result
