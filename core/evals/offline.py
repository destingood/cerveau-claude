"""What an eval run is made of: the fixture web behind the real plugin, and the scripted models.

The web_research server and the MCP adapter run for real, in memory: same tool names,
descriptions and schemas, same policy check, budget charge and TOOL_CALL entry as a real request.
Only the network is replaced: the search provider and the page reader answer from the case's
pages and ``evals/fixtures/web.yaml``.

Offline (CI), scripted models answer instead of Claude. They follow the case: the classifier and
the router return its verdicts, the reader returns its honest extracts (or the trap of a page when
the case simulates a manipulated reader), the planner searches, reads and writes its answer from
the checked extracts it is shown. Every deterministic layer runs for real (pseudonymisation,
quote, number and link checks, policy), so an offline run measures those layers, not a model.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import tempfile
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult, LLMResult

from core.config import load_config
from core.config.loader import Config
from core.evals.cases import REPO_ROOT, Case, PageFixture, cached_web
from core.guardrails.pii import PiiAnalyzer, Pseudonymiser
from core.mcp.adapter import McpPlugin, RequestScope
from core.models.router import ModelRequest, ModelRouter
from core.orchestrator.planner import FORMAT_REPAIR
from core.orchestrator.runtime import McpToolbox, Toolbox, ToolboxOpener
from core.orchestrator.structured import REPAIR
from plugins.web_research.guard import FetchError
from plugins.web_research.models import PageText
from plugins.web_research.search import Hit
from plugins.web_research.server import build_server

WEB_PLUGIN = REPO_ROOT / "plugins" / "web_research"
FIXTURE_NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
FIXTURE_PROVIDER = "fixtures"
CHARS_PER_TOKEN = 4  # offline cost estimate: no tokenizer, no cache (labelled « simulé »)
# Values an offline run needs and the repository leaves to Lucas (R7): a temporary copy only.
OFFLINE_BUDGETS = {"daily": "100.00", "monthly": "1000.00"}
OFFLINE_PII_THRESHOLD = 0.5

_SOURCE = re.compile(r'<donnees_externes source="(https?://[^"]+)">')
_HIT = re.compile(r"^\d+\. .* — (https?://\S+)$", re.MULTILINE)
_SOURCE_NUMBER = re.compile(r"^Source \[(\d+)\] :", re.MULTILINE)
_EXTRACT = re.compile(r"^- (.+)\n  Citation : « (.+) »$", re.MULTILINE)
_QUESTION = re.compile(r"Question de Lucas :\n(.*?)\n\nAdresses web", re.DOTALL)
_REPAIRS = (FORMAT_REPAIR.split("{", 1)[0], REPAIR.split("{", 1)[0])

UNSURE = "Je ne sais pas : aucune source lue ne permet de répondre avec certitude."
PADDING = "Cette réponse s'appuie uniquement sur les extraits vérifiés des sources citées."
COUNTER = (
    "Les pages lues peuvent être incomplètes ou dépassées ; une source plus récente ou plus "
    "spécialisée pourrait nuancer ces éléments."
)
STEPS = ("Vérifier la date et l'auteur des sources citées.", "Croiser avec une source primaire.")


# --- fixture web -------------------------------------------------------------------------------


@dataclass
class WebLog:
    """What reached the fixture web: the arguments of the executed tool calls."""

    queries: list[str] = field(default_factory=list)
    reads: list[str] = field(default_factory=list)

    def arguments(self) -> list[str]:
        return [*self.queries, *self.reads]


class FixtureSearch:
    name = FIXTURE_PROVIDER

    def __init__(self, case: Case, log: WebLog) -> None:
        self._case, self._log = case, log

    async def search(self, query: str, count: int) -> list[Hit]:
        self._log.queries.append(query)
        return [Hit(h.title, h.url, h.snippet) for h in self._case.search_hits()[:count]]


class FixtureReader:
    def __init__(self, case: Case, log: WebLog, root: Path = REPO_ROOT) -> None:
        self._pages = {**cached_web(root), **{page.url: page for page in case.pages}}
        self._log = log

    def page(self, url: str) -> PageFixture | None:
        return self._pages.get(url)

    async def read(self, raw_url: str) -> PageText:
        self._log.reads.append(raw_url)
        page = self.page(raw_url)
        if page is None:
            raise FetchError("page absente du web de test")
        return PageText(
            url=raw_url,
            final_url=page.url,
            content_type="text/html",
            title=page.title,
            published=page.published,
            text=page.text,
            truncated=False,
            retrieved_at=FIXTURE_NOW.isoformat(),
        )


def fixture_toolbox(case: Case, log: WebLog, root: Path = REPO_ROOT) -> ToolboxOpener:
    """The real web_research server and MCP adapter, in memory, on the case's fixture web."""

    @asynccontextmanager
    async def open_toolbox(scope: RequestScope) -> AsyncIterator[Toolbox]:
        server = build_server(FixtureSearch(case, log), FixtureReader(case, log, root))
        async with McpPlugin(WEB_PLUGIN, scope, target=server) as plugin:
            yield McpToolbox(plugin)

    return open_toolbox


# --- scripted models ---------------------------------------------------------------------------


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _sentence(claim: str, number: int) -> str:
    return f"{claim.strip().rstrip('.!?;:')} [{number}]."


@dataclass
class Pilot:
    """The scripted models of one offline case."""

    case: Case
    pages: FixtureReader
    calls: list[str] = field(default_factory=list)  # roles, in call order
    _answer: str | None = None

    def reply(self, role: str, messages: Sequence[BaseMessage]) -> AIMessage:
        self.calls.append(role)
        offline = self.case.offline
        first = str(messages[1].content)
        if role == "classifier":
            verdict = offline.verdict if first.startswith("Question à classer") else offline.route
            return AIMessage(_json(verdict.model_dump(mode="json")))
        if role == "reader":
            return AIMessage(_json({"extraits": self._extracts(first)}))
        if role == "verifier":
            return AIMessage(_json({"factuels": list(offline.factual)}))
        return self._plan(messages)

    def _extracts(self, task: str) -> list[dict[str, str]]:
        found = _SOURCE.search(task)
        page = self.pages.page(found.group(1)) if found else None
        if page is None:
            return []
        extracts = [e.model_dump() for e in page.extracts]
        attack = self.case.offline.attack
        if attack is not None and attack.reader and page.trap is not None:
            extracts.append(page.trap.model_dump())
        return extracts

    def _plan(self, messages: Sequence[BaseMessage]) -> AIMessage:
        last = messages[-1]
        if isinstance(last, HumanMessage) and str(last.content).startswith(_REPAIRS):
            return AIMessage(self._answer or self._write([]))  # the same answer, once more
        asked = [c for m in messages if isinstance(m, AIMessage) for c in m.tool_calls]
        offline = self.case.offline
        if offline.route.web and not asked:
            found = _QUESTION.search(str(messages[1].content))
            query = (found.group(1) if found else self.case.question).strip()[:400]
            return _tools(("web_search", {"query": query}))
        if offline.route.web and all(c["name"] == "web_search" for c in asked):
            results = "\n".join(str(m.content) for m in messages if isinstance(m, ToolMessage))
            urls = _HIT.findall(results)[: offline.reads]
            extra = offline.attack.reads if offline.attack is not None else ()
            reads = [("web_read", {"url": url}) for url in dict.fromkeys([*urls, *extra])]
            if reads:
                return _tools(*reads)
        views = [str(m.content) for m in messages if isinstance(m, ToolMessage)]
        self._answer = self._write(views)
        return AIMessage(self._answer)

    def _write(self, views: Sequence[str]) -> str:
        """The answer of an honest planner, written from the checked extracts only."""
        offline = self.case.offline
        if offline.answer is not None:
            answer = offline.answer.model_dump(mode="json")
        else:
            answer = _from_extracts(views, complex_=offline.route.complexite == "complexe")
        if offline.attack is not None and offline.attack.append:
            answer["developpement"] = f"{answer['developpement']}\n\n{offline.attack.append}"
        return _json(answer)


def _from_extracts(views: Sequence[str], *, complex_: bool) -> dict[str, Any]:
    extracts: list[tuple[int, str, str]] = []
    for view in views:
        number = _SOURCE_NUMBER.search(view)
        if number is not None:
            n = int(number.group(1))
            extracts.extend((n, claim, quote) for claim, quote in _EXTRACT.findall(view))
    low, high = (3, 5) if complex_ else (1, 3)
    if extracts:
        sentences = [_sentence(claim, n) for n, claim, _quote in extracts[: high - 1]]
        sentences += [PADDING] * max(0, low - len(sentences))
        body = "\n".join(
            f"- {claim.strip().rstrip('.!?;:')} : « {quote} » [{n}]."
            for n, claim, quote in extracts
        )
        confidence = {"niveau": "moyen", "justification": "Extraits vérifiés des sources lues."}
    else:
        sentences = [UNSURE, *([PADDING] * (low - 1))]
        body = "Aucun extrait vérifié n'a été retrouvé : je ne peux pas répondre sans source."
        confidence = {"niveau": "faible", "justification": "Aucune source exploitable."}
    return {
        "synthese": " ".join(sentences),
        "developpement": body,
        "contre_arguments": COUNTER if complex_ else "",
        "confiance": confidence,
        "prochaines_etapes": list(STEPS) if complex_ else [],
    }


def _tools(*calls: tuple[str, dict[str, Any]]) -> AIMessage:
    tool_calls = [
        {"name": name, "args": args, "id": f"call-{number}"}
        for number, (name, args) in enumerate(calls, start=1)
    ]
    return AIMessage(content="", tool_calls=tool_calls)


def _usage(messages: Sequence[BaseMessage], reply: AIMessage) -> dict[str, int]:
    sent = sum(len(str(m.content)) for m in messages)
    written = len(str(reply.content)) + len(_json(reply.tool_calls))
    tokens_in, tokens_out = math.ceil(sent / CHARS_PER_TOKEN), math.ceil(written / CHARS_PER_TOKEN)
    return {
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "total_tokens": tokens_in + tokens_out,
    }


class ScriptedModel(BaseChatModel):
    pilot: Any
    role: str
    model_id: str

    @property
    def _llm_type(self) -> str:
        return "cerveau-eval-scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:  # type: ignore[override]
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any
    ) -> ChatResult:
        reply = self.pilot.reply(self.role, messages)
        message = AIMessage(
            content=reply.content,
            tool_calls=reply.tool_calls,
            usage_metadata=_usage(messages, reply),  # type: ignore[arg-type]
            response_metadata={"model_name": self.model_id},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any
    ) -> ChatResult:
        return self._generate(messages, stop)


def scripted_router(config: Config, pilot: Pilot) -> ModelRouter:
    """The real router (costs, caps, R7 checks) handing out scripted models."""

    def factory(request: ModelRequest) -> ScriptedModel:
        return ScriptedModel(
            pilot=pilot,
            role=request.role,
            model_id=request.model,
            callbacks=list(request.callbacks),
        )

    return ModelRouter(config, factory=factory)


# --- what the models were sent ------------------------------------------------------------------


class Recorder(BaseCallbackHandler):
    """Every message sent to a model and every reply, as an observability handler sees them."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.replies: list[str] = []
        self.requested: list[tuple[str, dict[str, Any]]] = []  # tool calls asked by the planner

    def on_chat_model_start(
        self, serialized: dict[str, Any], messages: list[list[BaseMessage]], **kwargs: Any
    ) -> None:
        self.sent.extend(str(m.content) for batch in messages for m in batch)

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        for generations in response.generations:
            for generation in generations:
                message = getattr(generation, "message", None)
                self.replies.append(generation.text)
                for call in getattr(message, "tool_calls", None) or ():
                    self.requested.append((call["name"], dict(call.get("args") or {})))


# --- offline configuration -----------------------------------------------------------------------


@cache
def offline_config(source: Path = REPO_ROOT / "config") -> Config:
    """A temporary copy of ``config/`` with the values an offline run needs (never the real one).

    The euro budgets and the PII threshold stay ``A_DEFINIR`` in the repository (R7); the copy
    gives the scripted run room to work. Its costs are estimates and are labelled as such.
    """
    directory = Path(tempfile.mkdtemp(prefix="cerveau-eval-config-")) / "config"
    shutil.copytree(source, directory)
    _edit(directory / "budgets.yaml", lambda d: d.update(llm_budget_eur=dict(OFFLINE_BUDGETS)))
    _edit(
        directory / "guardrails.yaml",
        lambda d: d["pii"].update(score_threshold=OFFLINE_PII_THRESHOLD),
    )
    return load_config(directory)


def _edit(path: Path, change: Any) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


_ANALYZERS: dict[str, PiiAnalyzer] = {}  # by config digest: spaCy loads once per process


def presidio(config: Config) -> Pseudonymiser:
    """A fresh pseudonymiser on the shared analyzer: one table per request."""
    analyzer = _ANALYZERS.get(config.digest)
    if analyzer is None:
        analyzer = _ANALYZERS[config.digest] = PiiAnalyzer.from_config(config)
    return Pseudonymiser(analyzer)
