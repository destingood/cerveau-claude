"""`cerveau paper` and `cerveau status` (ADR-033, B54, B177): only ever in a temporary home."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from core.execution.book import OrderBook, Recorder, default_book_path
from core.execution.broker import AccountStatement
from core.execution.loop import DayReport, LoopError, Outcome
from core.execution.paper import PaperSettings
from core.execution.reconcile import ReconciliationLog, default_log_path, reconcile
from core.finance.store import FinanceStore, default_store_path
from core.policy.engine import KILL_SWITCH_FILE
from interfaces.cli import paper as paper_cli
from interfaces.cli.main import app
from tests.execution_cases import MemoryJournal, make_intent
from tests.test_execution_book import sent
from tests.test_execution_loop import MONDAY, MONDAY_RUN, market
from tests.test_execution_paper import SETTINGS
from tests.test_execution_sources import promoted

runner = CliRunner()


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    root.mkdir()
    monkeypatch.setenv("CERVEAU_HOME", str(root))
    monkeypatch.setattr("interfaces.cli.paper._now", lambda: MONDAY_RUN)
    return root


@pytest.fixture
def costs(monkeypatch: pytest.MonkeyPatch) -> None:
    """The simulator's test costs: the real ones are still A_DEFINIR (B184)."""
    monkeypatch.setattr(PaperSettings, "from_config", staticmethod(lambda *_: SETTINGS))


def stored(home: Path) -> None:
    market(FinanceStore.open(default_store_path(home))).close()


def paper(config_dir: Path, *args: str) -> Any:
    return runner.invoke(app, ["paper", *args, "--config-dir", str(config_dir)])


def read(*args: str) -> Any:
    return runner.invoke(app, ["paper", *args])


def test_the_paper_run_waits_for_the_costs(home: Path, config_dir: Path) -> None:
    result = paper(config_dir, "run")
    assert result.exit_code == 2
    assert "Bloqué (R7) : trading_costs" in result.stderr
    assert not (home / "var").exists()


@pytest.mark.usefixtures("costs")
def test_the_paper_run_needs_the_finance_store(home: Path, config_dir: Path) -> None:
    result = paper(config_dir, "run")
    assert result.exit_code == 1
    assert "Base finance : " in result.stderr and "cerveau finance sync" in result.stderr


@pytest.mark.usefixtures("costs")
def test_a_paper_day_runs_once_and_can_be_read_back(home: Path, config_dir: Path) -> None:
    stored(home)
    first = paper(config_dir, "run")
    assert first.exit_code == 0, first.output
    assert "# Journée paper du 19/10/2026" in first.stdout
    assert "- Issue : journée traitée" in first.stdout
    report = home / "var" / "paper" / "reports" / "2026-10-19.md"
    assert report.read_text(encoding="utf-8") in first.stdout

    again = paper(config_dir, "run")
    assert again.exit_code == 0
    assert "journée déjà traitée" in again.stdout
    assert "journée traitée" in report.read_text(encoding="utf-8")  # not rewritten

    status = read("status")
    assert "Paper : 1 journée(s) traitée(s), la dernière le 19/10/2026." in status.stdout
    assert "Dernière valorisation (19/10/2026, source : journal de la boucle)" in status.stdout
    assert "Ordres ouverts au carnet : 0 sur 0." in status.stdout
    assert "Réconciliation : aucun écart ouvert." in status.stdout

    assert read("report").stdout == read("report", "--date", "2026-10-19").stdout
    assert "# Journée paper du 19/10/2026" in read("report").stdout
    missing = read("report", "--date", "2026-10-18")
    assert missing.exit_code == 1 and "Aucun rapport pour le 2026-10-18" in missing.stderr
    wrong = read("report", "--date", "19/10/2026")
    assert wrong.exit_code == 1 and "Date invalide" in wrong.stderr
    assert read("orders").stdout.strip() == "Aucun ordre ouvert."
    assert read("orders", "--tous").stdout.strip() == "Aucun ordre."


@pytest.mark.usefixtures("costs")
def test_a_refused_strategy_is_noted_in_the_report(home: Path, config_dir: Path) -> None:
    stored(home)
    promoted(home, audited=False)
    result = paper(config_dir, "run")
    assert result.exit_code == 0, result.output
    assert "- croisement_mm : aucune intention : " in result.stdout


@pytest.mark.usefixtures("costs")
@pytest.mark.parametrize(("outcome", "code"), [("attente_donnees", 4), ("arret", 2)])
def test_an_unfinished_day_exits_with_its_code(
    home: Path, config_dir: Path, monkeypatch: pytest.MonkeyPatch, outcome: Outcome, code: int
) -> None:
    stored(home)
    report = DayReport(day=MONDAY, as_of=MONDAY_RUN, request_id="cli-test", outcome=outcome)
    monkeypatch.setattr("interfaces.cli.paper.run_day", lambda *_, **__: report)
    result = paper(config_dir, "run")
    assert result.exit_code == code
    assert (home / "var" / "paper" / "reports" / "2026-10-19.md").is_file()


@pytest.mark.usefixtures("costs")
def test_a_day_the_loop_cannot_go_on_with_stops(
    home: Path, config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored(home)

    def refuse(*_: object, **__: object) -> DayReport:
        raise LoopError("valorisation déjà enregistrée avec un autre compte")

    monkeypatch.setattr("interfaces.cli.paper.run_day", refuse)
    result = paper(config_dir, "run")
    assert result.exit_code == 1
    assert "Journée arrêtée : valorisation déjà enregistrée" in result.stderr


def test_nothing_is_created_by_reading(home: Path) -> None:
    assert "Paper : 0 journée(s) traitée(s)." in read("status").stdout
    assert (
        read("orders").stdout.strip() == "Carnet vide : aucune journée n'a encore rédigé d'ordre."
    )
    empty = read("report")
    assert empty.exit_code == 1 and "Aucun rapport paper" in empty.stderr
    assert not (home / "var").exists()


def test_the_orders_of_the_book_are_listed(home: Path) -> None:
    with OrderBook.open(
        default_book_path(home), recorder=Recorder(MemoryJournal(), "policy", "setup")
    ) as book:
        intent = make_intent(0)
        sent(book, intent)
    [line] = read("orders").stdout.strip().splitlines()
    assert line.startswith(f"{intent.decision_date:%d/%m/%Y} {intent.side} {intent.quantity} ")
    assert ": ENVOYEE, exécuté 0 (committee, " in line


def gaps(home: Path, *, clean_again: bool) -> None:
    """A cash gap on an empty account, then, if asked, a clean reconciliation."""
    capital = SETTINGS.capital_eur
    with ReconciliationLog.open(
        default_log_path(home), Recorder(MemoryJournal(), "scheduler", "setup")
    ) as log:
        short = AccountStatement(cash_eur=capital - Decimal(1))
        log.record(reconcile([], short, capital_eur=capital, as_of=MONDAY_RUN), now=MONDAY_RUN)
        if clean_again:
            honest = AccountStatement(cash_eur=capital)
            log.record(reconcile([], honest, capital_eur=capital, as_of=MONDAY_RUN))


def test_an_open_gap_shows_and_blocks_the_acknowledgement(home: Path) -> None:
    assert "Aucune réconciliation enregistrée" in read("acquitter").stderr
    gaps(home, clean_again=False)
    assert "1 écart(s) ouverts, intentions bloquées" in read("status").stdout
    refused = read("acquitter")
    assert refused.exit_code == 2 and "terminal interactif" in refused.stderr


def test_lucas_acknowledges_a_gap_at_a_terminal(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gaps(home, clean_again=True)
    assert "1 écart(s) à acquitter (`cerveau paper acquitter`)" in read("status").stdout
    monkeypatch.setattr("interfaces.cli.paper.interactive_terminal", lambda: True)
    done = read("acquitter")
    assert done.exit_code == 0, done.output
    assert "1 écart(s) acquitté(s)" in done.stdout
    assert "Réconciliation : aucun écart ouvert." in read("status").stdout


def test_cerveau_status_reads_what_stands(home: Path, config_dir: Path) -> None:
    armed = runner.invoke(app, ["status", "--config-dir", str(config_dir)])
    assert armed.exit_code == 0, armed.output
    assert armed.stdout.splitlines()[:2] == [
        "Kill switch : armé.",
        "Live : désactivé (config/live.yaml, R3).",
    ]
    assert "Autonomie finance : N" in armed.stdout
    assert "Paper : 0 journée(s) traitée(s)." in armed.stdout
    kill = home / KILL_SWITCH_FILE
    kill.parent.mkdir(parents=True)
    kill.write_text("essai", encoding="utf-8")
    engaged = runner.invoke(app, ["status", "--config-dir", str(config_dir)])
    assert "Kill switch : ENGAGÉ (fichier KILL créé à la main)" in engaged.stdout


def test_the_paper_run_reads_the_utc_clock() -> None:
    before = datetime.now(UTC)
    assert before <= paper_cli._now() <= datetime.now(UTC)
