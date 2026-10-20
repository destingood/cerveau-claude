"""`cerveau strategy` (ADR-025 to ADR-027) and the var/ bound of the finance paths (B103)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import math
import shutil
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import Result
from typer.testing import CliRunner

from core.audit import AuditJournal, default_journal_path
from core.budget.gate import RequestBudget
from core.config import load_config
from core.config.loader import PerRequest
from core.finance.research.registry import (
    PROTOCOL_COMMAND,
    REGISTRY_DIR,
    audited_reports,
    report_sha256,
)
from core.finance.research.report import VERDICT, default_reports_dir, latest_report, write_report
from core.finance.store import FinanceStore
from core.mcp.adapter import McpPlugin, RequestScope
from core.models import CostCalculator, Meter
from interfaces.cli import strategy as strategy_cli
from interfaces.cli.main import app
from plugins.finance_research.server import build_server as research_server

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / REGISTRY_DIR / "croisement_mm.yaml"
MODULE = Path("core/finance/research/strategies/croisement_mm.py")
CONFIG = ["--config-dir", str(REPO / "config")]
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
runner = CliRunner()


def make_home(root: Path, **changes: Any) -> Path:
    """A CERVEAU_HOME holding the demo entry, narrowed to the planted trend and four points."""
    raw = yaml.safe_load(DEMO.read_text(encoding="utf-8"))
    raw.update(univers=["FICT-RTEND"], grille={"short": [10, 20], "long": [50, 100]}, **changes)
    registry = root / REGISTRY_DIR
    registry.mkdir(parents=True)
    text = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)
    (registry / "croisement_mm.yaml").write_text(text, encoding="utf-8")
    (root / MODULE).parent.mkdir(parents=True)
    shutil.copyfile(REPO / MODULE, root / MODULE)
    return root


def entries(journal: Path) -> list[tuple[str, dict[str, Any]]]:
    audit = AuditJournal(journal)
    lines = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    return [(e["event"], audit.read_payload(e["payload_ref"])) for e in lines]


def strategy(*args: str) -> Result:
    return runner.invoke(app, ["strategy", *args])


def copilot_backtest(home: Path, **arguments: Any) -> dict[str, Any]:
    """One strategy_lab backtest asked through the MCP adapter, journaled as the Copilot's are."""
    settings = load_config(REPO / "config")
    meter = Meter(CostCalculator(settings.pricing))
    limits = PerRequest(max_tool_calls=5, max_tokens=1000, max_seconds=120)
    scope = RequestScope(
        request_id="req-copilote",
        domain="finance",
        autonomy=settings.autonomy,
        journal=AuditJournal(default_journal_path(home)),
        budget=RequestBudget(limits, meter, clock=lambda: 0.0),
        meter=meter,
        project_root=home,
    )
    server = research_server(home, REPO / "config", lambda: NOW)

    async def go() -> dict[str, Any]:
        async with McpPlugin(REPO / "plugins" / "finance_research", scope, target=server) as lab:
            [spec] = lab.manifest.tools
            asked = {"strategie": "croisement_mm", "mode": "backtest", **arguments}
            _, result = await lab.call(spec, asked)
            return result

    return asyncio.run(go())


@dataclasses.dataclass(frozen=True)
class Ran:
    home: Path
    screened: Result
    protocol: Result

    @property
    def journal(self) -> Path:
        return default_journal_path(self.home)

    @property
    def store(self) -> Path:
        return strategy_cli.synthetic_store_path(self.home)


@pytest.fixture(scope="module")
def ran(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Ran]:
    """One screening then one protocol of the narrowed demo, in a temporary CERVEAU_HOME."""
    home = make_home(tmp_path_factory.mktemp("strategy") / "home")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CERVEAU_HOME", str(home))
        patch.delenv("CERVEAU_AUDIT_JOURNAL", raising=False)
        patch.setattr(strategy_cli, "now", lambda: NOW)
        screened = strategy("screen", "croisement_mm", *CONFIG)
        protocol = strategy("protocol", "croisement_mm", *CONFIG)
        yield Ran(home, screened, protocol)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = make_home(tmp_path / "home")
    monkeypatch.setenv("CERVEAU_HOME", str(root))
    monkeypatch.delenv("CERVEAU_AUDIT_JOURNAL", raising=False)
    monkeypatch.setattr(strategy_cli, "now", lambda: NOW)
    return root


def test_the_screening_records_every_point_before_the_final_sample(ran: Ran) -> None:
    assert ran.screened.exit_code == 0, ran.screened.output
    assert "4 combinaison(s)" in ran.screened.output
    assert "Indicatif, aucun verdict" in ran.screened.output
    with FinanceStore.open(ran.store, read_only=True) as db:
        trials = [t.trial for t in db.trials("croisement_mm")]
    screened = [t for t in trials if t.origin == "criblage"]
    final = [t for t in trials if t.origin == "protocole-final"]
    assert len(screened) == 4 and len(final) == 1
    # Screening reads the development window only: the final sample stays untouched (D7).
    assert max(t.end for t in screened) < final[0].start
    (event, payload), *_ = entries(ran.journal)
    assert event == "TOOL_CALL" and payload["command"] == "strategy screen"
    assert payload["combinaisons"] == 4 and payload["essais"] == 4
    assert payload["fenetre"][1] == max(t.end for t in screened).isoformat()


def test_the_protocol_writes_its_report_and_a_decision_citing_its_print(ran: Ran) -> None:
    assert ran.protocol.exit_code == 0, ran.protocol.output
    reports = default_reports_dir(ran.home)
    assert sorted(p.name for p in reports.iterdir()) == [
        "croisement_mm-2026-10-20.json",
        "croisement_mm-2026-10-20.md",
    ]
    sha = report_sha256(reports / "croisement_mm-2026-10-20.json")
    assert f"SHA-256 {sha}" in ran.protocol.output
    decisions = [p for e, p in entries(ran.journal) if e == "DECISION"]
    [decision] = decisions
    assert decision["command"] == PROTOCOL_COMMAND and decision["rapport_sha256"] == sha
    assert (decision["donnees"], decision["rapport"]) == (
        "synthetiques",
        "croisement_mm-2026-10-20.json",
    )
    assert audited_reports(ran.journal) == frozenset({sha})
    found = latest_report("croisement_mm", reports)
    assert found is not None
    assert decision["verdict"] == found[1].verdict
    assert f"verdict {VERDICT[found[1].verdict]}" in ran.protocol.output


def test_list_and_show_cite_the_last_report_without_an_approval_text(ran: Ran) -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CERVEAU_HOME", str(ran.home))
        listed, shown = strategy("list"), strategy("show", "croisement_mm")
    found = latest_report("croisement_mm", default_reports_dir(ran.home))
    assert found is not None
    assert f"dernier verdict : {VERDICT[found[1].verdict]} (croisement_mm-2026-10-20.json)" in (
        listed.output
    )
    assert shown.exit_code == 0, shown.output
    assert "Essais de la famille (N) :" in shown.output and "criblage 4" in shown.output
    assert "inscrit au journal d'audit" in shown.output
    assert "Aucun texte d'approbation" in shown.output
    assert "rapport sur données synthétiques" in shown.output
    assert "rapport à frais fictifs" in shown.output
    assert "À recopier" not in shown.output


def test_the_approval_text_needs_a_promotable_audited_report(
    ran: Ran, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    shutil.copytree(ran.home, home)
    monkeypatch.setenv("CERVEAU_HOME", str(home))
    monkeypatch.delenv("CERVEAU_AUDIT_JOURNAL", raising=False)
    monkeypatch.setattr(strategy_cli, "now", lambda: NOW)
    found = latest_report("croisement_mm", default_reports_dir(home))
    assert found is not None
    # A report as a real run would stamp it: what show checks is the stamp, not how it was made.
    stamped = found[1].model_copy(
        update={
            "donnees": "reelles",
            "frais": "reels",
            "verdict": "reussi",
            "genere_le": datetime(2026, 10, 21, 8, 0, tzinfo=UTC),
        }
    )
    written = write_report(stamped, default_reports_dir(home))
    unaudited = strategy("show", "croisement_mm")
    assert "absente du journal d'audit" in unaudited.output
    assert "À recopier" not in unaudited.output
    AuditJournal(default_journal_path(home)).append(
        actor="lucas",
        event="DECISION",
        payload={"command": PROTOCOL_COMMAND, "rapport_sha256": written.sha256},
    )
    shown = strategy("show", "croisement_mm")
    assert shown.exit_code == 0, shown.output
    text = shown.output[shown.output.index("# À recopier") :]
    body = yaml.safe_load(text)
    assert body["rapport_sha256"] == written.sha256 and body["date"] == "2026-10-20"
    assert not (home / "governance").exists()  # printed, never written (D14)


def test_real_data_stays_blocked_while_its_parameters_are_undefined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_home(tmp_path / "home", donnees="reelles")
    monkeypatch.setenv("CERVEAU_HOME", str(root))
    for command in ("screen", "protocol"):
        result = strategy(command, "croisement_mm", *CONFIG)
        assert result.exit_code == 2, result.output
        assert "Bloqué (R7)" in result.output
    assert not (root / "var").exists()


def test_a_synthetic_entry_refuses_a_store(home: Path) -> None:
    store = home / "var" / "finance" / "finance.db"
    result = strategy("screen", "croisement_mm", "--store", str(store), *CONFIG)
    assert result.exit_code == 1
    assert "ne s'applique qu'aux données réelles" in result.output
    assert not (home / "var").exists()


def test_an_unknown_strategy_is_refused(home: Path) -> None:
    result = strategy("show", "absente")
    assert result.exit_code == 1 and "Stratégie inconnue : absente" in result.output


@pytest.mark.parametrize(
    ("command", "option"),
    [
        (["strategy", "screen", "croisement_mm"], "--journal"),
        (["strategy", "protocol", "croisement_mm"], "--journal"),
        (["finance", "sync", "ecb"], "--store"),
        (["finance", "sync", "ecb"], "--journal"),
        (["finance", "plus-values", "--annee", "2025"], "--store"),
        (["finance", "plus-values", "--annee", "2025"], "--journal"),
        (["portfolio", "reconcile", "{csv}"], "--store"),
        (["portfolio", "reconcile", "{csv}"], "--journal"),
    ],
)
def test_paths_outside_var_need_an_explicit_option(
    home: Path, tmp_path: Path, command: list[str], option: str
) -> None:
    csv = tmp_path / "releve.csv"
    csv.write_text("date,compte,nature,identifiant,quantite\n", encoding="utf-8")
    args = [part.format(csv=csv) for part in command]
    for target in (tmp_path / "ailleurs", home / "var" / ".." / "ailleurs"):
        result = runner.invoke(app, [*args, option, str(target), *CONFIG])
        assert result.exit_code == 1, result.output
        assert f"Refus (B103) : {option}" in result.output and "--hors-var" in result.output
        assert not target.exists()
    assert not (home / "var").exists()


def test_a_path_under_var_needs_no_option(home: Path) -> None:
    journal = home / "var" / "audit" / "essai.jsonl"
    result = strategy("screen", "croisement_mm", "--journal", str(journal), *CONFIG)
    assert result.exit_code == 0, result.output
    [(event, _)] = entries(journal)
    assert event == "TOOL_CALL" and not default_journal_path(home).exists()


def test_config_check_refuses_a_candidate_without_approval(home: Path) -> None:
    make_home(home.parent / "candidate", statut="candidate", donnees="reelles")
    shutil.copyfile(
        home.parent / "candidate" / REGISTRY_DIR / "croisement_mm.yaml",
        home / REGISTRY_DIR / "croisement_mm.yaml",
    )
    result = runner.invoke(app, ["config", "check", *CONFIG])
    assert result.exit_code == 1
    assert "Registre des stratégies (1) : promotions refusées" in result.output
    assert "aucune approbation dans governance/approvals/strategies/croisement_mm.yaml" in (
        result.output
    )
    (home / REGISTRY_DIR / "casse.yaml").write_text("id: [", encoding="utf-8")
    broken = runner.invoke(app, ["config", "check", *CONFIG])
    assert broken.exit_code == 1 and "Registre des stratégies invalide" in broken.output


def test_config_check_accepts_the_research_registry(home: Path) -> None:
    result = runner.invoke(app, ["config", "check", *CONFIG])
    assert result.exit_code == 0, result.output
    assert "Registre des stratégies (1) : conforme" in result.output


def test_the_synthetic_store_is_loaded_once(home: Path) -> None:
    path = strategy_cli.synthetic_store(home)
    with FinanceStore.open(path, read_only=True) as db:
        before = Counter(i.instrument_id for i in db.instruments(as_of=NOW))
    stamp = path.stat().st_mtime_ns
    assert strategy_cli.synthetic_store(home) == path and path.stat().st_mtime_ns == stamp
    assert "FICT-RTEND" in before
    assert [p.name for p in path.parent.iterdir()] == ["synthetique.db"]


def test_the_protocol_counts_each_copilot_backtest_once(home: Path) -> None:
    """ADR-027: a backtest asked of the Copilot is a trial of the family, replayed and counted."""
    window = {"as_of": "2026-10-20T12:00:00Z", "debut": "2020-01-02", "fin": "2021-12-31"}
    asked = copilot_backtest(home, params={"short": 20, "long": 50}, **window)
    [(event, call)] = entries(default_journal_path(home))
    assert event == "TOOL_CALL" and call["status"] == "ok"
    assert call["arguments"]["params"] == '{"short": 20, "long": 50}'
    first = strategy("protocol", "croisement_mm", *CONFIG)
    assert first.exit_code == 0, first.output
    assert "Essais du Copilote rejoués depuis le journal d'audit et comptés dans N : 1." in (
        first.output
    )
    second = strategy("protocol", "croisement_mm", *CONFIG)
    assert second.exit_code == 0, second.output
    assert "Essais du Copilote" not in second.output
    decisions = [p for e, p in entries(default_journal_path(home)) if e == "DECISION"]
    assert [d["essais_copilote"] for d in decisions] == [1, 0]
    with FinanceStore.open(strategy_cli.synthetic_store_path(home), read_only=True) as db:
        [replayed] = [t.trial for t in db.trials("croisement_mm") if t.trial.origin == "copilote"]
    assert replayed.source is not None and replayed.source.startswith("audit#1 ")
    assert replayed.params == {"short": 20, "long": 50}
    assert (replayed.start.isoformat(), replayed.end.isoformat()) == (
        asked["backtest"]["debut"],
        asked["backtest"]["fin"],
    )
    assert replayed.sharpe_annual is not None
    assert math.isclose(replayed.sharpe_annual, asked["backtest"]["sharpe"]["value"])


def test_a_copilot_backtest_that_no_longer_replays_refuses_the_protocol(home: Path) -> None:
    """B121: a trial that cannot be replayed would leave N short, so the protocol stops."""
    copilot_backtest(home, params={"short": 20, "long": 50}, as_of="2026-10-20T12:00:00Z")
    entry = home / REGISTRY_DIR / "croisement_mm.yaml"
    raw = yaml.safe_load(entry.read_text(encoding="utf-8"))
    raw["grille"] = {"short": [10], "long": [50, 100]}
    entry.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    result = strategy("protocol", "croisement_mm", *CONFIG)
    assert result.exit_code == 1, result.output
    assert "non rejouable" in result.output
    assert not default_reports_dir(home).exists()
    assert [e for e, _ in entries(default_journal_path(home))] == ["TOOL_CALL", "ERROR"]
