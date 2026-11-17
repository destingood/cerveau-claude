"""The « cerveau-plateforme » MCP server (ADR-069): Claude Code as orchestrator at zero API budget.

Acceptance test of step 4 of plan v2: a risk question is answered with the figures of
``finance_risk``, the call is journaled, the numbers of a draft are traced to it, and an order
request only gets a policy decision, refused at N0. No network: the risk plugin runs in memory.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult

from core.audit import AuditJournal
from core.finance.fixtures import REFERENCE_READ_AT, reference_store
from core.verification.figures import figures_in
from interfaces.mcp_server.server import NAME, Bridge, build_server
from plugins.finance_risk.server import build_server as risk_server

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = {"ECRITURE_INTERNE", "COMMUNICATION_EXTERNE", "IRREVERSIBLE", "FINANCIERE"}


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return reference_store(tmp_path_factory.mktemp("finance") / "finance.db")


def bridge(tmp_path: Path, store: Path | None = None) -> Bridge:
    targets = (
        {"finance_risk": risk_server(store, ROOT / "config", lambda: REFERENCE_READ_AT)}
        if store is not None
        else {}
    )
    return Bridge(journal=AuditJournal(tmp_path / "audit" / "journal.jsonl"), targets=targets)


def run(server: Any, action: Callable[[Client], Awaitable[Any]]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def call(session: Bridge, tool: str, arguments: dict[str, Any]) -> CallToolResult:
    result: CallToolResult = run(build_server(session), lambda c: c.call_tool(tool, arguments))
    return result


def content(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error, " ".join(getattr(b, "text", "") for b in result.content)
    data: dict[str, Any] = result.structured_content or {}
    return data


def entries(journal: AuditJournal) -> list[dict[str, Any]]:
    if not journal.path.exists():
        return []
    lines = journal.path.read_text(encoding="utf-8").splitlines()
    return [
        {**entry, "payload": journal.read_payload(entry["payload_ref"])}
        for entry in map(json.loads, lines)
    ]


def test_the_server_lists_its_five_tools(tmp_path: Path) -> None:
    listed = run(build_server(bridge(tmp_path)), lambda c: c.list_tools()).tools
    assert {tool.name for tool in listed} == {
        "domaines",
        "outils",
        "appeler",
        "verifier",
        "proposer_action",
    }
    assert NAME == "cerveau-plateforme"  # « cerveau » is the memory plugin's server


def test_the_domains_come_with_their_effective_level(tmp_path: Path) -> None:
    rows = content(call(bridge(tmp_path), "domaines", {}))["domaines"]
    domains = {row["domaine"]: row for row in rows}
    assert {"generaliste", "finance"} <= set(domains)
    assert domains["generaliste"]["niveau"] == "N1"
    assert domains["finance"]["niveau"] == "N0"
    assert "finance_risk" in domains["finance"]["plugins"]


def test_each_domain_lists_at_most_25_tools_and_never_an_action(tmp_path: Path) -> None:
    session = bridge(tmp_path)
    for row in content(call(session, "domaines", {}))["domaines"]:
        tools = content(call(session, "outils", {"domaine": row["domaine"]}))["outils"]
        assert len(tools) <= 25, row["domaine"]
        assert not {tool["classe"] for tool in tools} & ACTIONS, row["domaine"]
        assert all(tool["classe"] != "EXECUTION_ISOLEE" for tool in tools)
        assert all(isinstance(tool["arguments"], dict) for tool in tools)
    finance = content(call(session, "outils", {"domaine": "finance"}))["outils"]
    assert "risk_report" in {tool["outil"] for tool in finance}


def test_a_risk_question_is_answered_journaled_and_its_figures_traced(
    tmp_path: Path, store: Path
) -> None:
    session = bridge(tmp_path, store)
    server = build_server(session)

    async def scenario(client: Client) -> tuple[CallToolResult, CallToolResult, CallToolResult]:
        report = await client.call_tool(
            "appeler", {"domaine": "finance", "outil": "risk_report", "arguments": {}}
        )
        figures, _ = figures_in(content(report)["resultat"])
        cited = f"Le chiffre clé du rapport est {figures[0].display}."
        good = await client.call_tool("verifier", {"brouillon": cited})
        bad = await client.call_tool("verifier", {"brouillon": "La perte probable est 987 654 €."})
        return report, good, bad

    report, good, bad = run(server, scenario)
    data = content(report)
    assert data["appel"] == "risk_report#1"
    assert figures_in(data["resultat"])[0], "the risk report carries figures (R1)"
    calls = [e for e in entries(session.log) if e["event"] == "TOOL_CALL"]
    assert calls and any("risk_report" in json.dumps(e["payload"]) for e in calls)
    assert content(good)["ok"] is True and content(good)["sans_source"] == []
    assert content(bad)["ok"] is False and content(bad)["sans_source"]


def test_an_order_request_gets_a_refusal_at_n0_and_nothing_runs(tmp_path: Path) -> None:
    session = bridge(tmp_path)
    data = content(
        call(
            session,
            "proposer_action",
            {"domaine": "finance", "classe": "FINANCIERE", "resume": "acheter 10 FICT-A"},
        )
    )
    assert data["effet"] == "refuser" and data["execute"] is False and data["raisons"]
    policy = [e for e in entries(session.log) if e["event"] == "POLICY"]
    assert len(policy) == 1
    assert policy[0]["payload"]["effect"] == "refuser"
    assert "acheter" not in json.dumps(policy[0]["payload"])  # only the summary's digest (R6)


def test_an_unknown_tool_or_domain_is_an_error(tmp_path: Path) -> None:
    session = bridge(tmp_path)
    unknown_tool = call(
        session, "appeler", {"domaine": "finance", "outil": "passer_un_ordre", "arguments": {}}
    )
    unknown_domain = call(session, "outils", {"domaine": "astrologie"})
    assert unknown_tool.is_error and unknown_domain.is_error
    assert entries(session.log) == []  # refused before any plugin starts
