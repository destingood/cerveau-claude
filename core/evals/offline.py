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

The scholarly and feeds servers run for real too, on the case's records and on the feeds of its
own allow-list. A deep research (``--approfondi``, ADR-045) runs the real engine: the scripted
planner proposes the case's sub-questions, the reader returns the extracts of the pages and
abstracts, and the writer cites the checked extracts it is shown, plus what the case adds.
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
from datetime import UTC, date, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult, LLMResult
from langchain_core.tools import BaseTool, ToolException
from mcp.server import MCPServer

from core.code.git import GitRunner
from core.code.repos import RepoReader
from core.config import load_config
from core.config.loader import Config
from core.evals.cases import (
    REPO_ROOT,
    Case,
    CommitteeTurn,
    PageFixture,
    QualityFixture,
    RecordFixture,
    cached_web,
)
from core.evals.code_fixtures import (
    CODE_REPO,
    FixtureDocker,
    FixtureGitHub,
    build_repo,
    check_settings,
    code_repositories,
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
from core.orchestrator.planner import FORMAT_REPAIR, sentence_count
from core.orchestrator.runtime import McpToolbox, Toolbox, ToolboxOpener
from core.orchestrator.structured import REPAIR
from core.verification.figures import Figure
from core.verification.trace import tool_output
from plugins.code_checks.server import build_server as checks_server
from plugins.code_ci.server import build_server as ci_server
from plugins.code_repo.server import build_server as repo_server
from plugins.feeds.allowlist import FeedSource
from plugins.feeds.models import FeedError
from plugins.feeds.server import build_server as feeds_server
from plugins.finance_data.server import build_server as finance_data_server
from plugins.finance_optimize.server import build_server as finance_optimize_server
from plugins.finance_portfolio.server import build_server as finance_portfolio_server
from plugins.finance_report.server import build_server as finance_report_server
from plugins.finance_research.server import build_server as finance_research_server
from plugins.finance_risk.server import build_server as finance_risk_server
from plugins.scholarly.common import ScholarError
from plugins.scholarly.models import ScholarRecord, Update
from plugins.scholarly.server import build_server as scholarly_server
from plugins.web_research.models import PageText
from plugins.web_research.search import Hit
from plugins.web_research.server import build_server

WEB_PLUGIN = REPO_ROOT / "plugins" / "web_research"
SCHOLARLY_PLUGIN = REPO_ROOT / "plugins" / "scholarly"
FEEDS_PLUGIN = REPO_ROOT / "plugins" / "feeds"
FIXTURE_DOI = "10.0000/fixture"  # the record a fixture's published update points to
FIXTURE_NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
# A run that reads the reference store is dated when the tools read it (R10): never before.
FINANCE_NOW = REFERENCE_READ_AT
IMPORTED_AT = REFERENCE_FETCHED_AT + timedelta(minutes=30)  # a case's files, before it is read
FIXTURE_PROVIDER = "fixtures"
CHARS_PER_TOKEN = 4  # offline cost estimate: no tokenizer, no cache (labelled « simulé »)
# Values an offline run needs and the repository leaves to Lucas (R7): a temporary copy only.
OFFLINE_BUDGETS = {"daily": "100.00", "monthly": "1000.00"}
OFFLINE_COMMITTEE = {"max_tokens": 400000, "max_seconds": 600, "max_tool_calls": 40}
OFFLINE_RESEARCH = {"max_tokens": 400000, "max_seconds": 600, "max_tool_calls": 40}
OFFLINE_PII_THRESHOLD = 0.5

_SOURCE = re.compile(r'<donnees_externes source="(https?://[^"]+)">')
_HIT = re.compile(r"^\d+\. .* — (https?://\S+)$", re.MULTILINE)
_SOURCE_NUMBER = re.compile(r"^Source \[(\d+)\] :", re.MULTILINE)
_EXTRACT = re.compile(r"^- (.+)\n  Citation : « (.+) »$", re.MULTILINE)
_QUESTION = re.compile(r"Question de Lucas :\n(.*?)\n\nAdresses web", re.DOTALL)
_REPAIRS = (FORMAT_REPAIR.split("{", 1)[0], REPAIR.split("{", 1)[0])
WEB_TOOLS = frozenset({"web_search", "web_read"})
RESEARCH_TOOLS = frozenset({"feed_read", "scholar_search", "scholar_record"})  # read, never compute
# What the deep research shows its planner and its writer (core/research/engine.py).
_RESEARCH_HEAD = re.compile(r"Question de Lucas :\n(.*?)\n\nDate du jour", re.DOTALL)
_PLAN_TASK = "\n\nPropose au plus "
_WRITE_TASK = "\n\nSous-questions étudiées :\n"
_RESEARCH_EXTRACT = re.compile(r"^- \[(\d+\.\d+)\] (.+)\n  Citation : « (.+) »$", re.MULTILINE)
SOURCES_SECTION = "Ce que disent les sources"
RESEARCH_REASON = "Extraits vérifiés des sources lues, croisés entre les sous-questions."
MAX_SYNTHESIS_CLAIMS = 5  # the synthesis of a complex answer has 3 to 5 sentences
MAX_SECTION_CLAIMS = 12
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
CODE_TOOLS = frozenset({"repo_log", "repo_diff", "repo_file", "run_checks", "ci_runs"})  # read
CODE_UNSURE = "Je ne sais pas : aucun outil de code n'a rendu de résultat exploitable."
CODE_PADDING = "Chaque compte et chaque citation de cette réponse viennent de l'outil cité."
CODE_COUNTER = (
    "Ces constats ne valent que pour la révision lue ; une autre révision, un autre "
    "environnement ou un contrôle relancé peuvent donner un autre résultat."
)
CODE_STEPS = (
    "Relire soi-même les fichiers et les diagnostics cités.",
    "Faire soi-même toute modification du dépôt : CERVEAU lit sans écrire.",
)
CODE_FAILED = "L'outil {tool} a refusé la demande"
CODE_REFUSED = (
    "Le résultat de {tool} est écarté : il contient un texte qui ressemble à une consigne."
)
CODE_UNAVAILABLE = "L'outil « {tool} » n'est pas disponible : CERVEAU lit le code sans le modifier."
STATUS_WORDS = {
    "ok": "réussi",
    "echec": "en échec",
    "erreur": "en erreur",
    "aucun_test": "sans test",
    "non_lance": "non lancé",
    "delai": "hors délai",
}
MAX_QUOTED_LINES = 10
MAX_REASON_CHARS = 200
_CODE_RESULT = re.compile(
    r'^<donnees_externes source="([a-z_]+)#[0-9]+">\n(.*)\n</donnees_externes>$', re.DOTALL
)
_CODE_ERROR = re.compile(
    r"^Erreur de l'outil :\n<donnees_externes source=\"([a-z_]+) \(erreur\)\">\n(.*)\n"
    r"</donnees_externes>$",
    re.DOTALL,
)
_CODE_REFUSAL = re.compile(r"^Refus : le résultat de ([a-z_]+) ")
_UNAVAILABLE = re.compile(r"^Erreur : l'outil « (.+?) » n'est pas disponible")
_DIGIT_PARENTHESES = re.compile(r"\s*\([^()]*[0-9][^()]*\)")


# --- fixture web -------------------------------------------------------------------------------


@dataclass
class WebLog:
    """What reached the fixture web: the arguments of the executed tool calls."""

    queries: list[str] = field(default_factory=list)
    reads: list[str] = field(default_factory=list)
    scholar: list[str] = field(default_factory=list)  # scholarly queries and identifiers
    feeds: list[str] = field(default_factory=list)  # feed addresses fetched

    def arguments(self) -> list[str]:
        return [*self.queries, *self.reads, *self.scholar, *self.feeds]


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


def _scholar_record(record: RecordFixture) -> ScholarRecord:
    return ScholarRecord(
        source=record.source,
        identifier=record.identifier,
        type="preprint" if record.preprint else "journal-article",
        preprint=record.preprint,
        title=record.title,
        authors=[],
        more_authors=0,
        published=record.published,
        updated=None,
        venue=None,
        doi=record.doi,
        url=record.url,
        abstract=record.abstract,
        abstract_truncated=False,
        update_to=[],
        updated_by=[Update(type=kind, doi=FIXTURE_DOI) for kind in record.updated_by],
        retrieved_at=FIXTURE_NOW.isoformat(),
    )


class FixtureScholar:
    """A scholarly source answering from the case's records of that source."""

    def __init__(self, name: str, case: Case, log: WebLog) -> None:
        self.name = name
        self._records = [record for record in case.records if record.source == name]
        self._log = log

    async def search(self, query: str, since: date | None, max_results: int) -> list[ScholarRecord]:
        self._log.scholar.append(query)
        return [_scholar_record(record) for record in self._records[:max_results]]

    async def record(self, identifier: str) -> ScholarRecord:
        self._log.scholar.append(identifier)
        for record in self._records:
            if record.identifier == identifier:
                return _scholar_record(record)
        raise ScholarError("notice absente des données de test")


def fixture_scholarly(case: Case, log: WebLog) -> ToolboxOpener:
    """The real scholarly server and MCP adapter, in memory, on the case's records."""

    @asynccontextmanager
    async def open_toolbox(scope: RequestScope) -> AsyncIterator[Toolbox]:
        sources = {name: FixtureScholar(name, case, log) for name in ("arxiv", "crossref")}
        server = scholarly_server(dict(sources))
        async with McpPlugin(SCHOLARLY_PLUGIN, scope, target=server) as plugin:
            yield McpToolbox(plugin)

    return open_toolbox


class FixtureFeedReader:
    def __init__(self, case: Case, log: WebLog) -> None:
        self._xml = {feed.url: feed.xml for feed in case.feeds}
        self._log = log

    async def fetch(self, raw_url: str) -> bytes:
        self._log.feeds.append(raw_url)
        xml = self._xml.get(raw_url)
        if xml is None:
            raise FeedError("flux absent du web de test")
        return xml.encode("utf-8")


def fixture_feeds(case: Case, log: WebLog) -> ToolboxOpener:
    """The real feeds server and MCP adapter, in memory, on the case's own allow-list (the
    repository's stays empty until Lucas fills it, D18)."""
    catalog = {
        feed.id: FeedSource(
            id=feed.id,
            titre=feed.titre,
            url=feed.url,
            licence=feed.licence,
            frequence=feed.frequence,
        )
        for feed in case.feeds
    }

    @asynccontextmanager
    async def open_toolbox(scope: RequestScope) -> AsyncIterator[Toolbox]:
        server = feeds_server(
            lambda: catalog, FixtureFeedReader(case, log), now=lambda: FIXTURE_NOW
        )
        async with McpPlugin(FEEDS_PLUGIN, scope, target=server) as plugin:
            yield McpToolbox(plugin)

    return open_toolbox


def research_toolboxes(case: Case, log: WebLog) -> dict[str, ToolboxOpener]:
    """The Recherche pack's plugins other than the web, on the case's records and feeds."""
    return {"scholarly": fixture_scholarly(case, log), "feeds": fixture_feeds(case, log)}


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
    if case.code is not None:  # the code pack reads its own repository, never the store
        return False
    computed = [call for call in case.offline.calls if call.tool not in RESEARCH_TOOLS]
    return case.group == "finance" or bool(computed or case.expect.tools or case.store is not None)


# --- code servers ------------------------------------------------------------------------------


def code_toolboxes(case: Case, home: Path) -> dict[str, ToolboxOpener]:
    """The code pack's real servers on the case's repository, a fake Docker and a fake GitHub
    (core/evals/code_fixtures.py); a case without one gets an empty allow-list, so that no real
    repository, container or request is ever reached."""
    folder = home / "code"
    repo = folder / CODE_REPO
    if case.code is not None:
        build_repo(case.code, repo)
    repositories = code_repositories(case.code, repo)
    settings = check_settings(repositories)
    runs = folder / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    reader = RepoReader(GitRunner(), cerveau_root=REPO_ROOT)
    checks = case.code.checks if case.code is not None else None
    docker, github = FixtureDocker(checks), FixtureGitHub(case.code)
    factories: dict[str, Callable[[], MCPServer]] = {
        "code_repo": lambda: repo_server(lambda: repositories, reader),
        "code_checks": lambda: checks_server(lambda: settings, reader, docker, runs),
        "code_ci": lambda: ci_server(
            lambda: repositories, github, now=lambda: FIXTURE_NOW, cerveau=REPO_ROOT
        ),
    }

    def opener(name: str, factory: Callable[[], MCPServer]) -> ToolboxOpener:
        @asynccontextmanager
        async def open_toolbox(scope: RequestScope) -> AsyncIterator[Toolbox]:
            async with McpPlugin(REPO_ROOT / "plugins" / name, scope, target=factory()) as plugin:
                yield McpToolbox(plugin)

        return open_toolbox

    return {name: opener(name, factory) for name, factory in factories.items()}


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
        if _RESEARCH_HEAD.match(first) and _PLAN_TASK in first:
            return self._research_plan(first, messages)
        if _RESEARCH_HEAD.match(first) and _WRITE_TASK in first:
            return self._research_write(first, messages)
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
        url = found.group(1) if found else None
        record = next((r for r in self.case.records if r.url == url), None)
        page: PageFixture | RecordFixture | None = record or (self.pages.page(url) if url else None)
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
        computed = [call for call in offline.calls if call.tool not in RESEARCH_TOOLS]
        if offline.answer is not None:
            answer = offline.answer.model_dump(mode="json")
        elif self.case.code is not None and not self.case.expect.figures:
            answer = _from_code(views, complex_=complex_)
        elif computed or self.case.expect.figures:
            answer = _from_figures(self.case, self.finance, views, complex_=complex_)
        else:
            answer = _from_extracts(views, complex_=complex_)
        if offline.attack is not None and offline.attack.append:
            answer["developpement"] = f"{answer['developpement']}\n\n{offline.attack.append}"
        return _json(answer)

    # --- deep research (core/research/engine.py) --------------------------------------------

    def _research_plan(self, task: str, messages: Sequence[BaseMessage]) -> AIMessage:
        """The case's scripted plans first (one per attempt), then an honest plan: one
        sub-question per angle, each searching the question itself."""
        research = self.case.offline.research
        used = sum(isinstance(message, AIMessage) for message in messages)
        if used < len(research.plans):
            return AIMessage(research.plans[used])
        found = _RESEARCH_HEAD.match(task)
        question = " ".join((found.group(1) if found else self.case.question).split())
        plan = [
            {
                "question": f"{question[:280]} (angle {n})",
                "angle": f"angle {n}",
                "requete_web": question[:200],
                "requete_scientifique": question[:200] if research.scholar else "",
                "source_scientifique": research.scholar or "crossref",
            }
            for n in range(1, research.sub_questions + 1)
        ]
        return AIMessage(_json({"sous_questions": plan}))

    def _research_write(self, task: str, messages: Sequence[BaseMessage]) -> AIMessage:
        """The case's scripted reports first, then an honest report: the case's own claims, then
        one claim per checked extract, each citing that extract only."""
        research = self.case.offline.research
        used = sum(isinstance(message, AIMessage) for message in messages)
        if used < len(research.reports):
            return AIMessage(research.reports[used])
        claims = [
            {"texte": _plain(claim), "extraits": [ref]}
            for ref, claim, _quote in _RESEARCH_EXTRACT.findall(task)
        ]
        scripted = [claim.model_dump(mode="json") for claim in research.claims]
        synthesis = [*scripted, *claims][:MAX_SYNTHESIS_CLAIMS]
        report = {
            "synthese": synthesis or [{"texte": UNSURE, "extraits": []}],
            "sections": [
                {
                    "titre": research.section or SOURCES_SECTION,
                    "affirmations": claims[:MAX_SECTION_CLAIMS],
                }
            ]
            if claims
            else [],
            "contre_arguments": claims[-1:],
            "confiance": {
                "niveau": research.level,
                "justification": research.reason or RESEARCH_REASON,
            },
            "prochaines_etapes": [*STEPS, *research.steps][:6],
        }
        return AIMessage(_json(report))


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


def _line(text: object) -> str:
    """A text of a code tool as the planner reads it, NFKC and spaces collapsed, marks kept."""
    return " ".join(unicodedata.normalize("NFKC", str(text)).split())


def _items(data: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    """The objects of a list, without the note a bounded view puts in their place."""
    return [item for item in data.get(key) or () if isinstance(item, Mapping)]


def _texts(data: Mapping[str, Any], key: str) -> list[str]:
    return [_line(item) for item in data.get(key) or () if str(item).strip()]


def _quoted(text: str) -> list[str]:
    lines = [_line(line) for line in text.splitlines()]
    return [f"  « {line} »" for line in lines if line][:MAX_QUOTED_LINES]


# Whether a result fell short: no step did ("none"), some did ("partial") or none concluded
# ("total"), as when Docker launched no container or every step ran out of time.
Shortfall = Literal["none", "partial", "total"]
CodeFacts = tuple[str, list[str], Shortfall]  # the headline, the details, the shortfall


def _log_facts(data: Mapping[str, Any]) -> CodeFacts:
    repo, commits = _line(data.get("repo", "")), _items(data, "commits")
    lines = [f"- « {_plain(str(c.get('subject')))} » ({_line(c.get('author'))})" for c in commits]
    if data.get("more_commits"):
        lines.append("D'autres commits, plus anciens, ne sont pas montrés.")
    if not commits:
        return f"Aucun commit lu dans {repo}.", lines, "none"
    first = commits[0]
    head = (
        f"Dernier commit de {repo} : « {_plain(str(first.get('subject')))} », "
        f"par {_line(first.get('author'))}."
    )
    return head, lines, "none"


def _changed(item: Mapping[str, Any]) -> str:
    added, deleted = item.get("added"), item.get("deleted")
    if added is None or deleted is None:
        return f"{_line(item.get('path'))} (fichier binaire)"
    return f"{_line(item.get('path'))}, {added} ligne(s) ajoutée(s) et {deleted} retirée(s)"


def _diff_facts(data: Mapping[str, Any]) -> CodeFacts:
    repo, files = _line(data.get("repo", "")), _items(data, "files")
    base, head = _line(data.get("base", "")), _line(data.get("head", ""))
    lines = [f"- {_changed(item)}" for item in files]
    if data.get("more_files"):
        lines.append(f"Autres fichiers modifiés, non montrés : {data['more_files']}.")
    if withheld := _texts(data, "withheld"):
        lines.append(f"Fichiers sensibles retenus par l'outil : {', '.join(withheld)}.")
    if data.get("note"):
        lines.append(f"Note de repo_diff : {_plain(str(data['note']))}.")
    patch = str(data.get("patch") or "").splitlines()
    added = [line[1:] for line in patch if line.startswith("+") and not line.startswith("+++")]
    if quoted := _quoted("\n".join(added)):
        lines += ["Lignes ajoutées :", *quoted]
    if data.get("patch_truncated"):
        lines.append("Le patch est tronqué par l'outil.")
    if not files:
        return f"Aucun fichier modifié lu entre {base} et {head} dans {repo}.", lines, "none"
    return f"Différences de {repo} entre {base} et {head} : {_changed(files[0])}.", lines, "none"


def _file_facts(data: Mapping[str, Any]) -> CodeFacts:
    repo, path = _line(data.get("repo", "")), _line(data.get("path") or "") or "racine"
    if data.get("kind") == "directory":
        names = [
            _line(e.get("name")) + (" (retenu : sensible)" if e.get("withheld") else "")
            for e in _items(data, "entries")
        ]
        lines = [f"- {name}" for name in names]
        if data.get("more_entries"):
            lines.append(f"Autres entrées, non montrées : {data['more_entries']}.")
        shown = ", ".join(names[:5]) or "aucune entrée lisible"
        return f"Le dossier « {path} » de {repo} contient {shown}.", lines, "none"
    lines = []
    content, total = data.get("content"), data.get("total_lines")
    if content is None:
        head = f"Le contenu de « {path} » dans {repo} n'est pas montré par l'outil."
    elif total is None:
        head = f"Le fichier « {path} » de {repo} est lu."
    else:
        head = f"Le fichier « {path} » de {repo} compte {total} ligne(s)."
    if content is not None and (quoted := _quoted(str(content))):
        lines += ["Extrait :", *quoted]
    if data.get("content_truncated"):
        lines.append("Le contenu est tronqué par l'outil.")
    return head, lines, "none"


def _checks_facts(data: Mapping[str, Any]) -> CodeFacts:
    repo = _line(data.get("repo", ""))
    steps = {
        name: data.get(key) if isinstance(data.get(key), Mapping) else {}
        for name, key in (
            ("ruff check", "ruff_check"),
            ("ruff format", "ruff_format"),
            ("pytest", "pytest"),
        )
    }
    words = {
        name: STATUS_WORDS.get(str(step.get("status")), _line(step.get("status")))
        for name, step in steps.items()
    }
    head = f"Contrôles de {repo} : " + ", ".join(f"{n} {w}" for n, w in words.items()) + "."
    check, fmt, pytest = steps.values()
    lines = []
    if check.get("count") is not None:
        lines.append(f"ruff check : {check['count']} diagnostic(s).")
    if by_code := check.get("by_code"):
        counts = ", ".join(f"{code} × {count}" for code, count in by_code.items())
        lines.append(f"Diagnostics par code : {counts}.")
    for item in _items(check, "diagnostics"):
        where = _line(item.get("path"))
        if item.get("line") is not None:
            where = f"{where}, ligne {item['line']}"
        lines.append(f"- {where} : {_line(item.get('code'))} {_plain(str(item.get('message')))}")
    if check.get("more_diagnostics"):
        lines.append(f"Autres diagnostics, non montrés : {check['more_diagnostics']}.")
    if fmt.get("count") is not None:
        lines.append(f"ruff format : {fmt['count']} fichier(s) à reformater.")
    lines += [f"- à reformater : {path}" for path in _texts(fmt, "files")]
    if counts := pytest.get("counts"):
        lines.append("pytest : " + ", ".join(f"{k} {v}" for k, v in counts.items()) + ".")
    lines += [f"- test en échec : {name}" for name in _texts(pytest, "failed")]
    lines += [f"- test en erreur : {name}" for name in _texts(pytest, "errors")]
    lines += [
        f"Note de {name} : {_plain(str(step['note']))}."
        for name, step in steps.items()
        if step.get("note")
    ]
    source = data.get("source") if isinstance(data.get("source"), Mapping) else {}
    if withheld := _texts(source, "withheld"):
        lines.append(f"Fichiers sensibles retenus de la copie : {', '.join(withheld)}.")
    if skipped := _texts(source, "skipped"):
        lines.append(f"Fichiers non copiés : {', '.join(skipped)}.")
    statuses = [step.get("status") for step in steps.values()]
    if not any(status in ("ok", "echec", "aucun_test") for status in statuses):
        return head, lines, "total"
    return head, lines, "partial" if {"erreur", "delai"} & set(statuses) else "none"


def _ci_facts(data: Mapping[str, Any]) -> CodeFacts:
    github, runs = _line(data.get("github", "")), _items(data, "runs")

    def state(run: Mapping[str, Any]) -> str:
        conclusion = _line(run.get("conclusion")) if run.get("conclusion") else "aucune"
        return f"{_line(run.get('status'))}, conclusion {conclusion}"

    lines = [
        f"- n°{run.get('run_number')} « {_plain(str(run.get('title')))} » "
        f"({_line(run.get('workflow'))}, branche {_line(run.get('branch'))}, "
        f"{_line(run.get('event'))}) : {state(run)}"
        for run in runs
    ]
    if by_conclusion := data.get("by_conclusion"):
        counts = ", ".join(f"{name} × {count}" for name, count in by_conclusion.items())
        lines.append(f"Runs montrés, par conclusion : {counts}.")
    if data.get("total_count") is not None:
        lines.append(f"Runs comptés par GitHub : {data['total_count']}.")
    if not runs:
        return f"Aucun run lu pour {github}.", lines, "none"
    first = runs[0]
    head = (
        f"Dernier run de {github} : n°{first.get('run_number')} "
        f"« {_plain(str(first.get('title')))} », {state(first)}."
    )
    return head, lines, "none"


CODE_FACTS: dict[str, Callable[[Mapping[str, Any]], CodeFacts]] = {
    "repo_log": _log_facts,
    "repo_diff": _diff_facts,
    "repo_file": _file_facts,
    "run_checks": _checks_facts,
    "ci_runs": _ci_facts,
}


def _code_problem(view: str) -> str | None:
    """The sentence an honest planner writes for a failed, refused or unavailable call."""
    if (found := _CODE_ERROR.match(view)) is not None:
        tool, error = found.groups()
        reason = _DIGIT_PARENTHESES.sub("", _plain(_tool_error(tool, error)))
        sentence = f"{CODE_FAILED.format(tool=tool)} : {reason[:MAX_REASON_CHARS]}."
        # The error is not part of the R1 trace: no number of it is written.
        if not reason or _DIGIT.search(reason) or sentence_count(sentence) != 1:
            sentence = f"{CODE_FAILED.format(tool=tool)}."
        return sentence
    if (found := _CODE_REFUSAL.match(view)) is not None:
        return CODE_REFUSED.format(tool=found.group(1))
    if (found := _UNAVAILABLE.match(view)) is not None:
        return CODE_UNAVAILABLE.format(tool=found.group(1))
    return None


def _from_code(views: Sequence[str], *, complex_: bool) -> dict[str, Any]:
    """The answer of an honest planner on the code tools' results: what they read, as they
    wrote it, with no count of its own (R1), and every failure or refusal said (R12)."""
    heads: list[str] = []
    details: list[str] = []
    problems: list[str] = []
    tools: list[str] = []
    shortfalls: list[Shortfall] = []
    for view in views:
        if (problem := _code_problem(view)) is not None:
            problems.append(problem)
            continue
        found = _CODE_RESULT.match(view)
        if found is None or found.group(1) not in CODE_FACTS:
            continue
        tool = found.group(1)
        try:
            data = json.loads(found.group(2))
        except ValueError:
            continue
        if not isinstance(data, Mapping):
            continue
        head, lines, shortfall = CODE_FACTS[tool](data)
        if data.get("masked"):
            lines.append(f"Secrets masqués par {tool} : {data['masked']}.")
        heads.append(head if sentence_count(head) == 1 else RESULT.format(tool=tool))
        details += lines
        tools.append(tool)
        shortfalls.append(shortfall)
    low, high = (3, 5) if complex_ else (1, 3)
    sentences = [*heads, *problems] if heads else [CODE_UNSURE, *problems]
    sentences = sentences[: high - 1]
    sentences += [CODE_PADDING] * max(0, low - len(sentences))
    names = ", ".join(dict.fromkeys(tools))
    if heads and not problems and set(shortfalls) == {"none"}:
        confidence = {"niveau": "eleve", "justification": f"Résultats lus par {names}."}
    elif heads and set(shortfalls) == {"total"}:
        # A result that concluded nothing (no container, every step out of time) founds no
        # answer: « je ne sais pas » stays the honest one (R12).
        confidence = {
            "niveau": "faible",
            "justification": f"{names} n'a conclu sur aucun contrôle.",
        }
    elif heads:
        confidence = {
            "niveau": "moyen",
            "justification": f"Résultats lus par {names}, avec les limites signalées.",
        }
    else:
        confidence = {"niveau": "faible", "justification": "Aucun résultat d'outil exploitable."}
    return {
        "synthese": " ".join(sentences),
        "developpement": "\n".join([*details, *problems]) or "Aucun résultat d'outil exploitable.",
        "contre_arguments": CODE_COUNTER if complex_ else "",
        "confiance": confidence,
        "prochaines_etapes": list(CODE_STEPS) if complex_ else [],
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

    The euro budgets, the committee's and the deep research's budgets and the PII threshold stay
    ``A_DEFINIR`` in the repository (R7); the copy gives the scripted run room to work. Its costs
    are estimates and are labelled as such.
    """
    directory = Path(tempfile.mkdtemp(prefix="cerveau-eval-config-")) / "config"
    shutil.copytree(source, directory)

    def budgets(data: dict[str, Any]) -> None:
        data.update(llm_budget_eur=dict(OFFLINE_BUDGETS), per_committee=dict(OFFLINE_COMMITTEE))
        data["per_deep_research"].update(OFFLINE_RESEARCH)  # its caps stay the repository's

    _edit(directory / "budgets.yaml", budgets)
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
