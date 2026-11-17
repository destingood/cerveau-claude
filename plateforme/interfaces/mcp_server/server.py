"""Serveur MCP « cerveau-plateforme » (ADR-069) : Claude Code chef d'orchestre, à budget API nul.

Claude Code, sur l'abonnement de l'utilisateur, appelle par ce serveur les outils des plugins
enregistrés, sous la gouvernance de CERVEAU :
- outils listés par domaine, 25 au plus, dans l'ordre du pack (méga-prompt, §6.4) ;
- moteur de politique, kill switch et budget à chaque appel, par l'adaptateur des plugins ;
- chaque appel écrit au journal d'audit chaîné (R11) ;
- aucune action réelle : une classe d'action ne reçoit qu'une décision de politique (R2) ;
- chaque chiffre d'un brouillon vérifié contre les sorties d'outils de la session (R1).

Il n'est activé nulle part : l'utilisateur le déclare lui-même (`.mcp.json`, `guard_mcp`).
"""

import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from langchain_core.tools import ToolException
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from core.audit import AuditJournal
from core.audit.chain import default_journal_path
from core.budget.gate import RequestBudget, RequestBudgetExceeded
from core.config.loader import AutonomyConfig, Config, load_config
from core.governance.signatures import effective_autonomy
from core.mcp.adapter import McpAdapterError, McpPlugin, RequestScope, ToolRefusedError
from core.models.costs import CostCalculator
from core.models.meter import Meter
from core.orchestrator.packs import Pack, load_packs
from core.policy.engine import decide, kill_switch_engaged
from core.registry.manifest import ToolSpec, validate_plugin
from core.verification.trace import Evidence, ToolOutput, tool_output, trace

ROOT = Path(__file__).resolve().parents[2]
NAME = "cerveau-plateforme"
VERSION = "0.1.0"
ISOLATED = "EXECUTION_ISOLEE"  # l'agent de code, dans son conteneur : jamais par ce serveur
ActionClass = Literal["ECRITURE_INTERNE", "COMMUNICATION_EXTERNE", "IRREVERSIBLE", "FINANCIERE"]

INSTRUCTIONS = (
    "Outils de la plateforme CERVEAU. `domaines` liste les domaines et leur niveau d'autonomie ; "
    "`outils` donne les outils permis d'un domaine et leurs arguments ; `appeler` lance un outil. "
    "Chaque chiffre de ta réponse doit venir d'une sortie d'outil : passe ton brouillon à "
    "`verifier` avant de répondre. Une action réelle (e-mail, publication, ordre, suppression) ne "
    "s'exécute jamais ici : `proposer_action` rend la décision de la politique."
)
READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
CALLS = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
)
DECIDES = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)


@dataclass
class Bridge:
    """L'état d'une session : la configuration, le journal et les sorties d'outils déjà rendues.

    ``targets`` remplace, pour un plugin, son serveur stdio par un serveur en mémoire (tests).
    """

    root: Path = ROOT
    config: Config | None = None
    journal: AuditJournal | None = None
    targets: Mapping[str, Any] = field(default_factory=dict)
    environ: Mapping[str, str] | None = None
    outputs: list[ToolOutput] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)

    def __post_init__(self) -> None:
        if self.config is None:
            self.config = load_config(self.root / "config")
        if self.journal is None:
            self.journal = AuditJournal(default_journal_path(self.root))

    @property
    def cfg(self) -> Config:
        if self.config is None:  # posé par __post_init__
            raise RuntimeError("configuration non chargée")
        return self.config

    @property
    def log(self) -> AuditJournal:
        if self.journal is None:  # posé par __post_init__
            raise RuntimeError("journal d'audit non ouvert")
        return self.journal

    def autonomy(self) -> AutonomyConfig:
        """Le niveau effectif, jamais un niveau écrit au-dessus de ce que l'utilisateur a signé
        (ADR-036)."""
        return effective_autonomy(self.cfg.autonomy, self.root).autonomy

    def packs(self) -> Mapping[str, Pack]:
        return load_packs(self.root / "domain_packs")

    def pack(self, domain: str) -> Pack:
        packs = self.packs()
        if domain not in packs:
            raise ToolError(f"domaine inconnu : {domain} (domaines : {', '.join(sorted(packs))})")
        return packs[domain]

    def allowed(self, domain: str) -> list[tuple[str, ToolSpec, Path]]:
        """Les outils que la politique permet dans ``domain``, dans l'ordre du pack, 25 au plus :
        la même règle que l'adaptateur des plugins (``McpPlugin._refusal``)."""
        pack = self.pack(domain)
        autonomy = self.autonomy()
        kill = kill_switch_engaged(self.root)
        found: list[tuple[str, ToolSpec, Path]] = []
        for plugin in pack.plugins:
            directory = self.root / "plugins" / plugin
            report = validate_plugin(directory)
            manifest = report.manifest
            if not report.ok or manifest is None or manifest.transport == "in-process":
                continue
            for spec in manifest.tools:
                if spec.action_class == ISOLATED:
                    continue
                decision = decide(
                    autonomy,
                    request_id="liste",
                    domain=domain,
                    action_class=spec.action_class,
                    kill_switch=kill,
                    live_enabled=self.cfg.live.enabled,
                    max_level=manifest.max_autonomy_level,
                )
                if decision.effect == "executer":
                    found.append((plugin, spec, directory))
        return found[: self.cfg.models.routing.max_tools_to_planner]

    def domains(self) -> list[dict[str, Any]]:
        autonomy = self.autonomy()
        rows = []
        for domain, pack in self.packs().items():
            level = autonomy.domains.get(domain)
            rows.append(
                {
                    "domaine": domain,
                    "statut": pack.statut,
                    "niveau": level.level if level else None,
                    "niveau_max": level.max_level if level else None,
                    "plugins": list(pack.plugins),
                }
            )
        return rows

    def tools(self, domain: str) -> list[dict[str, Any]]:
        rows = []
        for plugin, spec, directory in self.allowed(domain):
            schema = json.loads((directory / spec.input_schema).read_text(encoding="utf-8"))
            schema.pop("$schema", None)
            rows.append(
                {
                    "outil": spec.name,
                    "plugin": plugin,
                    "classe": spec.action_class,
                    "description": spec.description,
                    "arguments": schema,
                }
            )
        return rows

    async def call(self, domain: str, tool: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        match = next(((p, s, d) for p, s, d in self.allowed(domain) if s.name == tool), None)
        if match is None:
            raise ToolError(
                f"outil « {tool} » absent ou refusé dans le domaine « {domain} » : voir `outils`"
            )
        plugin, spec, directory = match
        meter = Meter(CostCalculator(self.cfg.pricing))
        scope = RequestScope(
            request_id=f"mcp-{uuid.uuid4().hex[:16]}",
            domain=domain,
            autonomy=self.autonomy(),
            journal=self.log,
            budget=RequestBudget(self.cfg.budgets.per_request, meter),
            meter=meter,
            project_root=self.root,
            live_enabled=self.cfg.live.enabled,
            web_allowlist=self.cfg.data_sources.web_allowlist(domain),
        )
        target = self.targets.get(plugin)
        try:
            async with McpPlugin(directory, scope, target=target, environ=self.environ) as opened:
                if spec.name in opened.skipped:
                    raise ToolError(f"outil « {tool} » refusé : {opened.skipped[spec.name]}")
                status, structured = await opened.call(spec, dict(arguments))
        except (McpAdapterError, ToolException, ToolRefusedError, RequestBudgetExceeded) as exc:
            raise ToolError(str(exc)) from None
        self.counts[tool] += 1
        call_id = f"{tool}#{self.counts[tool]}"
        self.outputs.append(tool_output(call_id, tool, structured))
        return {"appel": call_id, "statut": status, "resultat": structured}

    def verify(self, draft: str) -> dict[str, Any]:
        rows = trace(draft, Evidence(outputs=self.outputs))
        return {
            "ok": all(row.traced for row in rows),
            "verifies": [{"valeur": row.text, "source": row.origin} for row in rows if row.traced],
            "sans_source": [row.text for row in rows if row.origin is None],
            "signe_contraire": [row.text for row in rows if row.contrary],
        }

    def propose(self, domain: str, action_class: ActionClass, summary: str) -> dict[str, Any]:
        """Une action réelle demandée : la décision de la politique, journalisée, jamais exécutée.
        Le résumé ne va au journal que par son empreinte (R6)."""
        self.pack(domain)
        request_id = f"mcp-{uuid.uuid4().hex[:16]}"
        decision = decide(
            self.autonomy(),
            request_id=request_id,
            domain=domain,
            action_class=action_class,
            kill_switch=kill_switch_engaged(self.root),
            live_enabled=self.cfg.live.enabled,
        )
        self.log.append(
            actor="interface",
            event="POLICY",
            request_id=request_id,
            payload={
                "source": NAME,
                "domain": domain,
                "action_class": action_class,
                "decision": decision.decision,
                "effect": decision.effect,
                "reasons": list(decision.reasons),
                "summary_sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
            },
        )
        return {
            "demande": request_id,
            "decision": decision.decision,
            "effet": decision.effect,
            "raisons": list(decision.reasons),
            "execute": False,
        }


Domain = Annotated[str, Field(min_length=1, max_length=64, description="Domaine, voir `domaines`")]


def build_server(bridge: Bridge | None = None) -> MCPServer:
    session = bridge or Bridge()
    server = MCPServer(NAME, version=VERSION, instructions=INSTRUCTIONS)

    @server.tool(
        name="domaines",
        description="Les domaines, leur statut, leur niveau d'autonomie et leurs plugins.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def domaines() -> dict[str, Any]:
        return {"domaines": session.domains()}

    @server.tool(
        name="outils",
        description="Les outils permis dans un domaine (25 au plus), avec leurs arguments.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def outils(domaine: Domain) -> dict[str, Any]:
        return {"domaine": domaine, "outils": session.tools(domaine)}

    @server.tool(
        name="appeler",
        description=(
            "Lance un outil permis d'un domaine. Politique, kill switch et budget s'appliquent ; "
            "l'appel est écrit au journal d'audit. Rend l'identifiant de l'appel et la sortie."
        ),
        annotations=CALLS,
        structured_output=True,
    )
    async def appeler(
        domaine: Domain,
        outil: Annotated[str, Field(min_length=1, max_length=64, description="Nom de l'outil")],
        arguments: Annotated[
            dict[str, Any] | None, Field(description="Arguments de l'outil, voir `outils`")
        ] = None,
    ) -> dict[str, Any]:
        return await session.call(domaine, outil, arguments or {})

    @server.tool(
        name="verifier",
        description=(
            "Vérifie que chaque chiffre et chaque date d'un brouillon vient d'une sortie d'outil "
            "de cette session (R1). À passer avant toute réponse qui cite un chiffre."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def verifier(
        brouillon: Annotated[str, Field(min_length=1, max_length=20000, description="Brouillon")],
    ) -> dict[str, Any]:
        return session.verify(brouillon)

    @server.tool(
        name="proposer_action",
        description=(
            "Une action réelle demandée (écriture, e-mail, publication, suppression, ordre) : "
            "rend la décision de la politique et l'écrit au journal. Rien n'est exécuté."
        ),
        annotations=DECIDES,
        structured_output=True,
    )
    async def proposer_action(
        domaine: Domain,
        classe: Annotated[ActionClass, Field(description="Classe d'action (section 6.3)")],
        resume: Annotated[str, Field(min_length=1, max_length=2000, description="L'action")],
    ) -> dict[str, Any]:
        return session.propose(domaine, classe, resume)

    return server


def main() -> None:
    build_server().run()
