"""What an eval run is made of: the fixture web behind the real plugin, and the scripted models.

The web_research server and the MCP adapter run for real, in memory: same tool names,
descriptions and schemas, same policy check, budget charge and TOOL_CALL entry as a real request.
Only the network is replaced: the search provider and the page reader answer from the case's
pages and ``evals/fixtures/web.yaml``. The five finance servers run for real too, in memory, on
a copy of the fictitious reference store read at ``REFERENCE_READ_AT`` (ADR-023): never on the
store of Lucas. A case that adds files or quality scores to the store gets a copy of its own,
built with the real import functions: a trapped file is refused as Lucas's import would refuse it.

Offline (CI), scripted models answer instead of Claude. They follow the case: the classifier and
the router return its verdicts, the reader returns its honest extracts (or the trap of a page when
the case simulates a manipulated reader), the planner makes the case's tool calls, searches, reads
and writes its answer from the figures the tools computed and the checked extracts it is shown.
Every deterministic layer runs for real (pseudonymisation, quote, number and link checks, policy),
so an offline run measures those layers, not a model.

A committee session runs the real engine too (ADR-028): its schemas, its R1 and R5 checks, its
repair, its limit checks and its journal. Each member is scripted: the case's replies first (what
a manipulated or mistaken member would say), then honest ones. Honest analysts call their tools
and cite the case's expected figures by the call that computed them; the news analyst searches,
reads and cites the checked extracts; the debaters cite the findings; the manager treats every
argument and proposes to wait; the controller prices a stress scenario and blocks whenever a
limit is unknown or exceeded. The research server reads a project root of its own: the
repository's registry, and no trial nor report of Lucas.
"""

from __future__ import annotations

import copy
import json
import math
import re
import shutil
import sqlite3
import tempfile
import unicodedata
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager, closing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult, LLMResult
from langchain_core.tools import BaseTool, ToolException
from mcp.server import MCPServer

from core.config import load_config
from core.config.loader import Config
from core.evals.cases import (
    REPO_ROOT,
    Case,
    CommitteeTurn,
    PageFixture,
    QualityFixture,
    cached_web,
)
from core.finance.fixtures import REFERENCE_FETCHED_AT, REFERENCE_READ_AT, reference_store
from core.finance.portfolio import PortfolioError, import_transactions
from core.finance.providers.base import ProviderError
from core.finance.research.registry import REGISTRY_DIR
from core.finance.schema import QUALITY_COLUMNS
from core.finance.store import FinanceStore, FinanceStoreError
from core.finance.sync import import_instruments
from core.guardrails.pii import PiiAnalyzer, Pseudonymiser
from core.mcp.adapter import McpPlugin, RequestScope
from core.models.router import ModelRequest, ModelRouter
from core.net.guard import FetchError
from core.orchestrator.planner import FORMAT_REPAIR
from core.orchestrator.runtime import McpToolbox, Toolbox, ToolboxOpener
from core.orchestrator.structured import REPAIR
from core.verification.figures import Figure
from core.verification.trace import tool_output
from plugins.finance_data.server import build_server as finance_data_server
from plugins.finance_optimize.server import build_server as finance_optimize_server
from plugins.finance_portfolio.server import build_server as finance_portfolio_server
from plugins.finance_report.server import build_server as finance_report_server
from plugins.finance_research.server import build_server as finance_research_server
from plugins.finance_risk.server import build_server as finance_risk_server
from plugins.web_research.models import PageText
from plugins.web_research.search import Hit
from plugins.web_research.server import build_server

WEB_PLUGIN = REPO_ROOT / "plugins" / "web_research"
FIXTURE_NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
# A run that reads the reference store is dated when the tools read it (R10): never before.
FINANCE_NOW = REFERENCE_READ_AT
IMPORTED_AT = REFERENCE_FETCHED_AT + timedelta(minutes=30)  # a case's files, before it is read
FIXTURE_PROVIDER = "fixtures"
CHARS_PER_TOKEN = 4  # offline cost estimate: no tokenizer, no cache (labelled « simulé »)
# Values an offline run needs and the repository leaves to Lucas (R7): a temporary copy only.
OFFLINE_BUDGETS = {"daily": "100.00", "monthly": "1000.00"}
OFFLINE_COMMITTEE = {"max_tokens": 400000, "max_seconds": 600, "max_tool_calls": 40}
OFFLINE_PII_THRESHOLD = 0.5

_SOURCE = re.compile(r'<donnees_externes source="(https?://[^"]+)">')
_HIT = re.compile(r"^\d+\. .* — (https?://\S+)$", re.MULTILINE)
_SOURCE_NUMBER = re.compile(r"^Source \[(\d+)\] :", re.MULTILINE)
_EXTRACT = re.compile(r"^- (.+)\n  Citation : « (.+) »$", re.MULTILINE)
_QUESTION = re.compile(r"Question de Lucas :\n(.*?)\n\nAdresses web", re.DOTALL)
_REPAIRS = (FORMAT_REPAIR.split("{", 1)[0], REPAIR.split("{", 1)[0])
WEB_TOOLS = frozenset({"web_search", "web_read"})
# What the committee engine shows a member (core/committee/engine.py).
_CALL = re.compile(r'<donnees_externes source="([a-z_]+:([a-z_]+)#[0-9]+)">')
_ASKED = re.compile(r"^Question de Lucas : (.*)$", re.MULTILINE)
_OFFERED = re.compile(r"^Outils à ta disposition : (.*)\.$", re.MULTILINE)
_CONSTAT = re.compile(r"^(C[0-9]+) \[([a-z_]+)\] (.*)$", re.MULTILINE)
_ARGUMENT = re.compile(r"^([DX][0-9]+\.[0-9]+) \[", re.MULTILINE)
_DEBATE_TASK = re.compile(r"^Débat, tour [0-9]+ sur", re.MULTILINE)
_MANAGER_TASK = re.compile(r"^Traite chaque argument une fois", re.MULTILINE)
_CONTROLLER_TASK = re.compile(r"^Proposition du gestionnaire :$", re.MULTILINE)
_TREAT = re.compile(r"avec sa raison : ([^\n]*)\.\n")
_CONTROLS = re.compile(r"calculés par le code[^\n]*:\n((?:- [^\n]*\n)+)")
_CONTROL_STATE = re.compile(r"^- .*? : (respectée|dépassée|inconnue) \(", re.MULTILINE)
_DIGIT = re.compile(r"[0-9]")
DEFAULT_CALLS: dict[str, dict[str, Any]] = {  # an analyst whose tools the case does not call
    "strategy_lab": {
        "strategie": "croisement_mm",
        "mode": "signaux",
        "params": {"short": 10, "long": 100},
    },
    "portfolio_snapshot": {},
    "risk_report": {"measures": ["var"]},
}
MAX_FINDINGS = 12
MAX_FINDING_CHARS = 300
MAX_PROPOSAL_CHARS = 600

UNSURE = "Je ne sais pas : aucune source lue ne permet de répondre avec certitude."
PADDING = "Cette réponse s'appuie uniquement sur les extraits vérifiés des sources citées."
COUNTER = (
    "Les pages lues peuvent être incomplètes ou dépassées ; une source plus récente ou plus "
    "spécialisée pourrait nuancer ces éléments."
)
STEPS = ("Vérifier la date et l'auteur des sources citées.", "Croiser avec une source primaire.")
FINANCE_PADDING = "Chaque chiffre de cette réponse vient de l'outil cité entre parenthèses."
FINANCE_COUNTER = (
    "Ces mesures reposent sur l'historique des séances et sur des hypothèses de modèle ; un "
    "régime de marché nouveau peut les mettre en défaut."
)
RESULT = "Résultat de {tool} obtenu ; ses chiffres restent ceux de l'outil."
FAILED_TOOL = "Erreur de l'outil"
TOOL_FAILED = "Un appel d'outil a échoué ou n'a rien donné : ce constat manque."
NO_NEWS = "Aucune page lue ne donne de constat vérifié sur la question."
DEFENCE = "Les constats chiffrés par les outils appuient une attente prudente, sans exposition."
CHALLENGE = "Ces constats ne suffisent pas à agir : données de démonstration et limites inconnues."
DEFENDER_MIND = "Un constat d'outil défavorable, ou une limite dépassée, me ferait changer d'avis."
CHALLENGER_MIND = "Un protocole réussi sur des données réelles me ferait changer d'avis."
WAIT = "Attendre, sans exposition nouvelle."
RETAINED = "Constats chiffrés retenus : "
INVALIDATION = "Un nouveau constat des outils contredit ceux qui fondent l'attente."
KEPT = "Argument appuyé sur des constats calculés par les outils."
SET_ASIDE = "Argument pris en compte : l'attente n'engage aucune exposition."
SCENARIO = "Choc de taux défavorable sur le portefeuille, chiffré par le stress de l'outil."
IRREVERSIBILITY = "Attendre n'engage rien d'irréversible : aucune position n'est ouverte."
BLOCKED = "Une limite est inconnue ou dépassée : le blocage du code s'applique."
UNBLOCKED = "Les limites contrôlées sont respectées et le scénario défavorable est chiffré."
FINANCE_STEPS = (
    "Relire les hypothèses et les limites signalées par les outils.",
    "Décider soi-même de toute suite à donner : aucun ordre n'est passé.",
)


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


# --- finance servers ----------------------------------------------------------------------------


@cache
def finance_store() -> Path:
    """The fictitious reference store, built once per process in a temporary directory."""
    directory = Path(tempfile.mkdtemp(prefix="cerveau-eval-finance-"))
    return reference_store(directory / "finance.db")


def _record_quality(store: FinanceStore, fixture: QualityFixture) -> None:
    """A score of ``fixture.score`` on every sub-score but the unknown ones, which leave the
    score unknown; the details are those of the series' last recorded score, so that the record
    reads like a real one."""
    history = store.quality_history(fixture.instrument_id)
    if not history:
        raise ValueError(f"{fixture.instrument_id} : aucun score de référence à compléter")
    store.record_quality(
        fixture.instrument_id,
        as_of=fixture.assessed_at,
        sub_scores={
            name: None if name in fixture.unknown else fixture.score for name in QUALITY_COLUMNS
        },
        score=None if fixture.unknown else fixture.score,
        details=str(history[-1]["details"]),
        computed_at=fixture.computed_at or fixture.assessed_at,
    )


def case_store(case: Case, directory: Path) -> tuple[Path, tuple[str, ...]]:
    """The store the case's run reads, and the reasons of the imports refused (R5).

    Without ``case.store``, the shared reference store. Otherwise a copy of it in ``directory``,
    to which the case's CSV files are imported as Lucas would import them (instruments first,
    then transactions), then its quality scores recorded. A refused file changes nothing.
    """
    fixture = case.store
    if fixture is None:
        return finance_store(), ()
    path = directory / "finance.db"
    with (
        closing(sqlite3.connect(finance_store())) as source,
        closing(sqlite3.connect(path)) as copy,
    ):
        source.backup(copy)
    at = fixture.imported_at or IMPORTED_AT
    refused: list[str] = []
    with FinanceStore.open(path) as store:
        imports: list[tuple[str, str | None, Callable[[Path], object]]] = [
            (
                "instruments.csv",
                fixture.instruments_csv,
                lambda file: import_instruments(store, file, recorded_at=at),
            ),
            (
                "transactions.csv",
                fixture.transactions_csv,
                lambda file: import_transactions(store, file, "cerveau", imported_at=at),
            ),
        ]
        for name, text, load in imports:
            if text is None:
                continue
            file = directory / name
            file.write_text(text, encoding="utf-8")
            try:
                load(file)
            except (ProviderError, PortfolioError, FinanceStoreError) as exc:
                refused.append(_plain(str(exc)))
        for quality in fixture.quality:
            _record_quality(store, quality)
    return path, tuple(refused)


ServerFactory = Callable[[Path, Path], MCPServer]  # (store, config directory) → server
FINANCE_SERVERS: dict[str, ServerFactory] = {
    "finance_data": lambda store, _config: finance_data_server(store, clock=lambda: FINANCE_NOW),
    "finance_portfolio": lambda store, _config: finance_portfolio_server(
        store, clock=lambda: FINANCE_NOW
    ),
    "finance_risk": lambda store, config: finance_risk_server(
        store, config, clock=lambda: FINANCE_NOW
    ),
    "finance_optimize": lambda store, config: finance_optimize_server(
        store, config, clock=lambda: FINANCE_NOW
    ),
    "finance_report": lambda store, config: finance_report_server(
        store, config, clock=lambda: FINANCE_NOW
    ),
    # The registry lives under the project, not in the eval's store: a root of its own.
    "finance_research": lambda _store, config: finance_research_server(
        research_root(), config, clock=lambda: FINANCE_NOW
    ),
}


@cache
def research_root() -> Path:
    """A project root for the research server: the repository's registry and no ``var/``, so
    that a run never reads the trials nor the protocol reports of Lucas (N stays that of the
    fixture) and never writes next to them."""
    root = Path(tempfile.mkdtemp(prefix="cerveau-eval-research-"))
    shutil.copytree(REPO_ROOT / REGISTRY_DIR, root / REGISTRY_DIR)
    return root


@dataclass
class FinanceLog:
    """What the finance servers answered: tool, arguments and result of each executed call."""

    calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)  # tool and error of a failed call

    def tools(self) -> list[str]:
        return [tool for tool, _args, _result in self.calls]

    def results(self, tool: str | None = None) -> list[tuple[str, dict[str, Any]]]:
        return [(name, result) for name, _args, result in self.calls if tool in (None, name)]

    @staticmethod
    def figures(tool: str, result: dict[str, Any]) -> tuple[Figure, ...]:
        return tool_output(tool, tool, result).figures

    def display(self, tool: str, figure_id: str) -> str | None:
        """The display of a figure in the first result of ``tool`` that has it."""
        for _name, result in self.results(tool):
            for figure in self.figures(tool, result):
                if figure.id == figure_id:
                    return figure.display
        return None


class LoggedToolbox:
    """A toolbox whose executed calls are logged; everything else is the real one."""

    def __init__(self, toolbox: Toolbox, log: FinanceLog) -> None:
        self._toolbox, self._log = toolbox, log

    @property
    def tools(self) -> Sequence[BaseTool]:
        return self._toolbox.tools

    @property
    def skipped(self) -> Mapping[str, str]:
        return self._toolbox.skipped

    @property
    def version(self) -> str:
        return self._toolbox.version

    async def call(
        self, name: str, arguments: dict[str, Any], *, journaled: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            result = await self._toolbox.call(name, arguments, journaled=journaled)
        except ToolException as exc:  # a blocked function or a missing provider (R7, R12)
            self._log.errors.append((name, str(exc)))
            raise
        self._log.calls.append((name, dict(arguments), result))
        return result


def finance_toolboxes(
    log: FinanceLog, config_dir: Path = REPO_ROOT / "config", store: Path | None = None
) -> dict[str, ToolboxOpener]:
    """The real finance servers and MCP adapter, in memory, on ``store`` (by default, the
    reference store)."""

    def opener(name: str, factory: ServerFactory) -> ToolboxOpener:
        @asynccontextmanager
        async def open_toolbox(scope: RequestScope) -> AsyncIterator[Toolbox]:
            server = factory(store or finance_store(), config_dir)
            async with McpPlugin(REPO_ROOT / "plugins" / name, scope, target=server) as plugin:
                yield LoggedToolbox(McpToolbox(plugin), log)

        return open_toolbox

    return {name: opener(name, factory) for name, factory in FINANCE_SERVERS.items()}


def uses_finance(case: Case) -> bool:
    """A case whose run reads the reference store, so is dated when the store is read."""
    return case.group == "finance" or bool(
        case.offline.calls or case.expect.tools or case.store is not None
    )


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
    finance: FinanceLog = field(default_factory=FinanceLog)
    calls: list[str] = field(default_factory=list)  # roles, in call order
    _answer: str | None = None
    _turns: dict[str, int] = field(default_factory=dict)  # scripted replies used, by member

    def reply(
        self, role: str, messages: Sequence[BaseMessage], member: str | None = None
    ) -> AIMessage:
        self.calls.append(role)
        if role == "committee":
            return self._committee(member or "", messages)
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

    # --- committee --------------------------------------------------------------------------

    def _committee(self, member: str, messages: Sequence[BaseMessage]) -> AIMessage:
        """A member of the committee: the case's scripted replies first, then honest ones."""
        scripted = self.case.offline.committee.get(member, ())
        used = self._turns.get(member, 0)
        if used < len(scripted):
            self._turns[member] = used + 1
            return _turn(scripted[used])
        task = str(messages[1].content)
        if _CONTROLLER_TASK.search(task):
            return self._controller(task, messages)
        if _DEBATE_TASK.search(task):
            return AIMessage(_json(_debate_turn(member, task)))
        if _MANAGER_TASK.search(task):
            return AIMessage(_json(_manager_decision(task)))
        return self._analyst(task, messages)

    def _analyst(self, task: str, messages: Sequence[BaseMessage]) -> AIMessage:
        tools = _offered(task)
        asked = _asked(messages)
        views = _views(messages)
        if "web_search" in tools:
            return self._news(task, asked, views)
        if not asked:
            calls = [(c.tool, dict(c.args)) for c in self.case.offline.calls if c.tool in tools]
            calls = calls or [(t, copy.deepcopy(a)) for t, a in DEFAULT_CALLS.items() if t in tools]
            if calls:
                return _tools(*calls)
        return AIMessage(_json(self._findings(views)))

    def _findings(self, views: Sequence[str]) -> dict[str, Any]:
        """The findings of an honest analyst: each expected figure its session computed, cited by
        the call that computed it, then one finding per other call, without a figure."""
        calls: dict[str, str] = {}  # tool → first call of the session
        for view in views:
            for call, tool in _CALL.findall(view):
                calls.setdefault(tool, call)
        constats: list[dict[str, Any]] = []
        for figure in self.case.expect.figures:
            display = self.finance.display(figure.tool, figure.id)
            if figure.tool in calls and display is not None:
                text = f"{figure.label} : {_plain(display)}"
                constats.append({"texte": text, "appel": calls[figure.tool]})
        cited = {constat["appel"] for constat in constats}
        constats += [
            {"texte": RESULT.format(tool=tool), "appel": call}
            for tool, call in calls.items()
            if call not in cited
        ]
        failed = any(FAILED_TOOL in view for view in views)
        return {
            "constats": constats[:MAX_FINDINGS],
            "signaux": [],
            "incertitudes": [TOOL_FAILED] if failed or not constats else [],
        }

    def _news(self, task: str, asked: Sequence[str], views: Sequence[str]) -> AIMessage:
        """The news analyst: a search on the question, the reads, the checked extracts."""
        if "web_search" not in asked:
            found = _ASKED.search(task)
            query = (found.group(1) if found else self.case.question).strip()[:400]
            return _tools(("web_search", {"query": query}))
        if "web_read" not in asked:
            urls = _HIT.findall("\n".join(views))[: self.case.offline.reads]
            if urls:
                return _tools(*(("web_read", {"url": url}) for url in dict.fromkeys(urls)))
        constats = [
            {"texte": _plain(claim), "appel": f"source [{n}]"}
            for n, claim, _quote in _checked_extracts(views)
            if len(_plain(claim)) <= MAX_FINDING_CHARS
        ]
        report = {
            "constats": constats[:MAX_FINDINGS],
            "signaux": [],
            "incertitudes": [] if constats else [NO_NEWS],
        }
        return AIMessage(_json(report))

    def _controller(self, task: str, messages: Sequence[BaseMessage]) -> AIMessage:
        """Prices a stress scenario, then blocks unless every limit the code checked is met."""
        if not _asked(messages) and "risk_report" in _offered(task):
            return _tools(("risk_report", {"measures": ["stress"]}))
        calls = [call for view in _views(messages) for call, _tool in _CALL.findall(view)]
        shown = _CONTROLS.search(task)
        states = _CONTROL_STATE.findall(shown.group(1)) if shown else []
        blocked = not states or any(state != "respectée" for state in states)
        report = {
            "scenarios": [{"texte": SCENARIO, "appel": calls[0] if calls else None}],
            "irreversibilite": IRREVERSIBILITY,
            "verdict": "BLOQUER" if blocked else "OK",
            "raisons": [BLOCKED if blocked else UNBLOCKED],
        }
        return AIMessage(_json(report))

    # --- planner ----------------------------------------------------------------------------

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
        web = [c for c in asked if c["name"] in WEB_TOOLS]
        if offline.calls and len(web) == len(asked):  # the computing tools first, once
            return _tools(*((call.tool, dict(call.args)) for call in offline.calls))
        if offline.route.web and not web:
            found = _QUESTION.search(str(messages[1].content))
            query = (found.group(1) if found else self.case.question).strip()[:400]
            return _tools(("web_search", {"query": query}))
        if offline.route.web and all(c["name"] == "web_search" for c in web):
            results = "\n".join(str(m.content) for m in messages if isinstance(m, ToolMessage))
            urls = _HIT.findall(results)[: offline.reads]
            attack = offline.attack
            extra = attack.reads if attack is not None else ()
            reads = [("web_read", {"url": url}) for url in dict.fromkeys([*urls, *extra])]
            searched = {str(c["args"].get("query", "")) for c in web}
            dictated = attack.searches if attack is not None else ()
            searches = [("web_search", {"query": q}) for q in dictated if q not in searched]
            if reads or searches:
                return _tools(*reads, *searches)
        views = [str(m.content) for m in messages if isinstance(m, ToolMessage)]
        self._answer = self._write(views)
        return AIMessage(self._answer)

    def _write(self, views: Sequence[str]) -> str:
        """The answer of an honest planner: the tools' figures and the checked extracts only."""
        offline = self.case.offline
        complex_ = offline.route.complexite == "complexe"
        if offline.answer is not None:
            answer = offline.answer.model_dump(mode="json")
        elif offline.calls or self.case.expect.figures:
            answer = _from_figures(self.case, self.finance, views, complex_=complex_)
        else:
            answer = _from_extracts(views, complex_=complex_)
        if offline.attack is not None and offline.attack.append:
            answer["developpement"] = f"{answer['developpement']}\n\n{offline.attack.append}"
        return _json(answer)


def _turn(turn: CommitteeTurn) -> AIMessage:
    if turn.tool is not None:
        return _tools((turn.tool, dict(turn.args)))
    return AIMessage(turn.text if turn.text is not None else _json(turn.output))


def _offered(task: str) -> set[str]:
    found = _OFFERED.search(task)
    return set(found.group(1).split(", ")) if found else set()


def _asked(messages: Sequence[BaseMessage]) -> list[str]:
    return [c["name"] for m in messages if isinstance(m, AIMessage) for c in m.tool_calls]


def _views(messages: Sequence[BaseMessage]) -> list[str]:
    return [str(m.content) for m in messages if isinstance(m, ToolMessage)]


def _debate_turn(member: str, task: str) -> dict[str, Any]:
    """One argument on the findings, answering the other side's from the second round."""
    constats = [found[0] for found in _CONSTAT.findall(task)]
    challenger = member.startswith("contradicteur")
    other = "D" if challenger else "X"
    earlier = [point for point in _ARGUMENT.findall(task) if point.startswith(other)]
    argument = {
        "texte": CHALLENGE if challenger else DEFENCE,
        "poids": "moyen",
        "constats": constats[:6],
        "repond_a": earlier[:6],
    }
    return {
        "arguments": [argument],
        "changer_avis": CHALLENGER_MIND if challenger else DEFENDER_MIND,
    }


def _manager_decision(task: str) -> dict[str, Any]:
    """Every argument treated once (the defender's kept, the challenger's set aside) and a
    proposal to wait that repeats the figured findings as the analysts wrote them."""
    found = _TREAT.search(task)
    ids = [point for point in (found.group(1).split(", ") if found else ()) if point]
    findings = _CONSTAT.findall(task)
    figured = [text.rstrip(" .") for _id, _member, text in findings if _DIGIT.search(text)]
    proposal = WAIT
    for n in range(len(figured), 0, -1):
        candidate = f"{WAIT} {RETAINED}{' ; '.join(figured[:n])}."
        if len(candidate) <= MAX_PROPOSAL_CHARS:
            proposal = candidate
            break
    invalidation = [{"condition": INVALIDATION, "constats": [findings[0][0]]}] if findings else []
    return {
        "decision": "attendre",
        "proposition": proposal,
        "confiance": "moyen",
        "horizon": "court",
        "invalidation": invalidation,
        "desaccords": [],
        "arguments": [
            {
                "id": point,
                "sort": "retenu" if point.startswith("D") else "ecarte",
                "raison": KEPT if point.startswith("D") else SET_ASIDE,
            }
            for point in ids
        ],
    }


def _checked_extracts(views: Sequence[str]) -> list[tuple[int, str, str]]:
    """(source number, claim, quote) of each checked extract the planner was shown."""
    extracts: list[tuple[int, str, str]] = []
    for view in views:
        number = _SOURCE_NUMBER.search(view)
        if number is not None:
            n = int(number.group(1))
            extracts.extend((n, claim, quote) for claim, quote in _EXTRACT.findall(view))
    return extracts


def _from_extracts(views: Sequence[str], *, complex_: bool) -> dict[str, Any]:
    extracts = _checked_extracts(views)
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


def _plain(text: str) -> str:
    """One line of a tool's text, as the planner reads it: NFKC, spaces collapsed, no end mark."""
    return " ".join(unicodedata.normalize("NFKC", text).split()).rstrip(" .;:")


def _tool_error(tool: str, error: str) -> str:
    """The reason of a failed call, without the adapter's and the server's prefixes."""
    prefix = rf"^{re.escape(tool)} : (?:Error executing tool {re.escape(tool)}: )?"
    return re.sub(prefix, "", error)


def _limits(log: FinanceLog) -> list[str]:
    """The limits the tools reported (R12): warnings, unavailable measures, errors, each once."""
    lines: list[str] = []
    for tool, result in log.results():
        texts = [str(w) for w in result.get("warnings") or ()]
        texts += [str(w) for w in result.get("avertissements") or ()]
        texts += [str(u.get("reason", "")) for u in result.get("unavailable") or ()]
        lines += [f"Limite signalée par {tool} : {_plain(t)}." for t in texts if t.strip()]
    for tool, error in log.errors:
        lines.append(f"Limite signalée par {tool} : {_plain(_tool_error(tool, error))}.")
    return list(dict.fromkeys(lines))


def _assumptions(result: Mapping[str, Any]) -> list[str]:
    """The assumptions a tool states, labelled by the tool itself (R12), wherever they are."""
    method = result.get("method")
    found = [*(result.get("assumptions") or ()), *(result.get("hypotheses") or ())]
    if isinstance(method, Mapping):
        found += method.get("assumptions") or ()
    return [str(text) for text in found if str(text).strip()]


def _frame(log: FinanceLog) -> list[str]:
    """The frame of the analysis as the tools state it: their notice, their status (R16), their
    parity label and their labelled assumptions (R12), each once."""
    lines: list[str] = []
    for tool, result in log.results():
        if result.get("notice"):
            lines.append(f"Cadre : {_plain(str(result['notice']))}.")
        if result.get("status") == "analyse":
            level = _plain(str(result.get("autonomy_level") or ""))
            lines.append(f"Statut : analyse au niveau {level} ; aucun ordre n'est passé.")
        if result.get("parity_label"):
            lines.append(f"Étiquette de {tool} : {_plain(str(result['parity_label']))}.")
        if result.get("rappel"):
            lines.append(f"Rappel de {tool} : {_plain(str(result['rappel']))}.")
        lines += [f"Convention de {tool} : {_plain(text)}." for text in _assumptions(result)]
    return list(dict.fromkeys(lines))


def _from_figures(
    case: Case, log: FinanceLog, views: Sequence[str], *, complex_: bool
) -> dict[str, Any]:
    """The answer of an honest planner on computed figures: each one cited with its tool (R1)."""
    facts = []
    for figure in case.expect.figures:
        display = log.display(figure.tool, figure.id)
        if display is not None:  # a figure the tool did not compute is never written
            facts.append(f"{figure.label} : {_plain(display)} ({figure.tool})")
    extracts = _checked_extracts(views)
    sourced = [_sentence(claim, n) for n, claim, _quote in extracts]
    ordered = [*(f"{fact}." for fact in facts[:1]), *sourced[:1]]
    ordered += [*(f"{fact}." for fact in facts[1:]), *sourced[1:]]
    limits = _limits(log)
    low, high = (3, 5) if complex_ else (1, 3)
    sentences = ordered[: high - 1] or limits[:1]
    sentences += [FINANCE_PADDING] * max(0, low - len(sentences))
    body = [
        *(f"- {fact}." for fact in facts),
        *(
            f"- {claim.strip().rstrip('.!?;:')} : « {quote} » [{n}]."
            for n, claim, quote in extracts
        ),
        *_frame(log),
        *limits,
    ]
    tools = ", ".join(dict.fromkeys(log.tools())) or "aucun outil"
    if facts and len(facts) == len(case.expect.figures) and not limits:
        confidence = {"niveau": "eleve", "justification": f"Chiffres calculés par {tools}."}
    elif facts or extracts:
        confidence = {
            "niveau": "moyen",
            "justification": f"Chiffres calculés par {tools}, avec les limites signalées.",
        }
    else:
        confidence = {"niveau": "faible", "justification": "Aucun chiffre calculé par un outil."}
    return {
        "synthese": " ".join(sentences),
        "developpement": "\n".join(body) or "Aucun chiffre n'a été calculé par un outil.",
        "contre_arguments": FINANCE_COUNTER if complex_ else "",
        "confiance": confidence,
        "prochaines_etapes": list(FINANCE_STEPS) if complex_ else [],
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
    member: str | None = None  # the committee member, for the role "committee"

    @property
    def _llm_type(self) -> str:
        return "cerveau-eval-scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:  # type: ignore[override]
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any
    ) -> ChatResult:
        reply = self.pilot.reply(self.role, messages, self.member)
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
            member=request.member,
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

    The euro budgets, the committee's session budget and the PII threshold stay ``A_DEFINIR``
    in the repository (R7); the copy gives the scripted run room to work. Its costs are
    estimates and are labelled as such.
    """
    directory = Path(tempfile.mkdtemp(prefix="cerveau-eval-config-")) / "config"
    shutil.copytree(source, directory)
    _edit(
        directory / "budgets.yaml",
        lambda d: d.update(
            llm_budget_eur=dict(OFFLINE_BUDGETS), per_committee=dict(OFFLINE_COMMITTEE)
        ),
    )
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
