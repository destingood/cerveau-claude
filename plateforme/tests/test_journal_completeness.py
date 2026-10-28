"""The journal alone tells each intent's cycle (plan §15, B195): two paper days at N3 on a real
hash-chained journal, from the draft to the reconciliation, then `audit verify`, then the cycle of
each intent read back from the journal without a gap."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from typer.testing import CliRunner

from core.approvals.store import ApprovalStore, Trail
from core.audit import AuditJournal
from core.execution.intent import sizing_tool
from core.execution.loop import send_approved
from interfaces.cli.main import app
from tests.test_execution_loop import (
    APPROVAL_RULES,
    MONDAY,
    MONDAY_RUN,
    SENDING,
    TUESDAY,
    Fixed,
    World,
    config,
    grant,
    ingest,
    run_at,
)

Entry = dict[str, Any]


@dataclass(frozen=True)
class Cycle:
    world: World
    journal: AuditJournal
    sent: UUID  # Monday's intent: approved, sent, filled on Tuesday
    waiting: UUID  # Tuesday's intent: still waiting for Lucas's answer


@pytest.fixture(scope="module")
def cycle(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Cycle]:
    """Monday at N3: an intent gated and asked to Lucas, granted, gated again and sent. Tuesday:
    its fill, the reconciliation, and a second intent that waits for Lucas."""
    root: Path = tmp_path_factory.mktemp("cycle")
    journal = AuditJournal(root / "audit" / "journal.jsonl")
    built = World(root, config("N3"), Fixed(days=(MONDAY, TUESDAY)), journal=journal)
    built.env.approvals = ApprovalStore.memory(APPROVAL_RULES, Trail(journal, "loop-test"))
    try:
        [sent] = built.run(MONDAY_RUN).intents
        grant(built, sent.intent_id)
        assert len(send_approved(built.env, now=SENDING).sent) == 1
        ingest(built.store, TUESDAY, 100.2)
        [waiting] = built.run(run_at(TUESDAY)).intents
        yield Cycle(built, journal, sent.intent_id, waiting.intent_id)
    finally:
        built.env.approvals.close()
        built.store.close()


def entries(journal: AuditJournal) -> list[Entry]:
    """Every line of the journal, its payload read back from the payload store."""
    lines = journal.path.read_text(encoding="utf-8").splitlines()
    return [
        {**entry, "payload": journal.read_payload(entry["payload_ref"])}
        for entry in map(json.loads, lines)
    ]


def of_intent(journal: AuditJournal, intent_id: UUID) -> list[Entry]:
    """The entries that name ``intent_id``, in the journal's order."""
    return [e for e in entries(journal) if e["payload"].get("intent_id") == str(intent_id)]


def step(entry: Entry) -> tuple[str, str, str]:
    """Who did what: the Gate's result, the policy's decision or the state reached."""
    payload = entry["payload"]
    mark = payload.get("result") or payload.get("decision") or payload["state"]
    return entry["actor"], entry["event"], mark


GATED = [("risk_gate", "POLICY", "ACCEPTE"), ("policy", "POLICY", "approbation")]
ASKED = [("policy", "ORDER_STATE", "INTENTION"), ("policy", "APPROVAL", "DEMANDEE")]


def test_the_journal_of_two_days_verifies(cycle: Cycle) -> None:
    lines = cycle.journal.path.read_text(encoding="utf-8").splitlines()
    result = CliRunner().invoke(
        app, ["audit", "verify"], env={"CERVEAU_AUDIT_JOURNAL": str(cycle.journal.path)}
    )
    assert result.exit_code == 0, result.output
    assert f"OK : {len(lines)} entrée(s)" in result.output


def test_each_intent_s_cycle_reads_from_the_journal_without_a_gap(cycle: Cycle) -> None:
    assert [step(e) for e in of_intent(cycle.journal, cycle.sent)] == [
        *GATED,
        *ASKED,
        ("lucas", "APPROVAL", "ACCORDEE"),
        *GATED,  # replayed on the approved intent, just before sending
        ("policy", "APPROVAL", "CONSOMMEE"),
        ("policy", "ORDER_STATE", "VALIDEE"),
        ("policy", "ORDER_STATE", "ENVOYEE"),
        ("policy", "ORDER_STATE", "EXECUTEE"),
    ]
    assert [step(e) for e in of_intent(cycle.journal, cycle.waiting)] == [*GATED, *ASKED]


@pytest.mark.parametrize("which", ["sent", "waiting"])
def test_the_journal_holds_the_intent_and_states_the_book_holds(cycle: Cycle, which: str) -> None:
    intent_id: UUID = getattr(cycle, which)
    journaled = of_intent(cycle.journal, intent_id)
    assert {e["payload"]["intent_sha256"] for e in journaled} == {
        cycle.world.book.order(intent_id).intent.sha256()
    }
    booked = cycle.world.book._conn.execute(
        "SELECT state, reason FROM transitions WHERE intent_id = ? ORDER BY seq",
        (str(intent_id),),
    )
    assert [
        (e["payload"]["state"], e["payload"]["reason"])
        for e in journaled
        if e["event"] == "ORDER_STATE"
    ] == [tuple(row) for row in booked]
    approvals = [e for e in journaled if "approval_id" in e["payload"]]
    assert len({e["payload"]["approval_id"] for e in approvals}) == 1  # one request, followed


def test_the_fill_is_journaled_then_reconciled(cycle: Cycle) -> None:
    everything = entries(cycle.journal)
    [filled] = [e for e in everything if e["payload"].get("state") == "EXECUTEE"]
    [(fill_id, fill_sha256)] = cycle.world.book._conn.execute(
        "SELECT fill_id, fill_sha256 FROM fills WHERE intent_id = ?", (str(cycle.sent),)
    )
    assert (filled["payload"]["fill_id"], filled["payload"]["fill_sha256"]) == (
        fill_id,
        fill_sha256,
    )
    after = next(e for e in everything if e["event"] == "DECISION" and e["seq"] > filled["seq"])
    assert after["actor"] == "scheduler"
    assert (after["payload"]["reconciliation"], after["payload"]["fills"]) == ("propre", 1)


@pytest.mark.parametrize("which", ["sent", "waiting"])
def test_the_calls_an_intent_cites_are_journaled_by_its_run_before_the_gate(
    cycle: Cycle, which: str
) -> None:
    """B195: the Gate checks which tool sized the intent; the loop journals that call first."""
    intent = cycle.world.book.order(getattr(cycle, which)).intent
    everything = entries(cycle.journal)
    gate = next(
        e
        for e in everything
        if e["actor"] == "risk_gate" and e["payload"].get("intent_id") == str(intent.intent_id)
    )
    for source in (intent.price_source, intent.sizing_source):
        [call] = [
            e
            for e in everything
            if e["event"] == "TOOL_CALL"
            and e["payload"].get("call_id") == source.call_id
            and e["ts"] == gate["ts"]  # the same run, not the same call id on another day
        ]
        assert call["seq"] < gate["seq"]
        assert call["payload"]["tool"] == source.tool
    [rationale] = [check for check in gate["payload"]["checks"] if check["name"] == "rationale"]
    assert rationale["value"] == intent.sizing_source.tool == sizing_tool(intent.origin)
