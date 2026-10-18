"""`cerveau ask` and `cerveau eval`: budgets, keys and live campaigns come before any call."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from core.audit import AuditJournal, verify
from core.budget.gate import BudgetGate
from core.config import load_config
from core.config.loader import Config
from core.models import COST_SCHEMA
from core.observability import NoTracer, Tracer
from core.orchestrator.graph import RunResult
from core.orchestrator.state import Answer
from interfaces.cli import evaluate, main
from interfaces.cli.main import app
from tests.conftest import REPO_ROOT

runner = CliRunner()
FAKE_KEY = "test-not-a-key"


@pytest.fixture
def journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "audit" / "journal.jsonl"
    monkeypatch.setenv("CERVEAU_AUDIT_JOURNAL", str(path))
    return path


@pytest.fixture
def budgeted(config_dir: Path) -> Path:
    """A copy of config/ whose € budgets are set, as Lucas will set them."""
    path = config_dir / "budgets.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["llm_budget_eur"] = {"daily": "1.00", "monthly": "10.00"}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return config_dir


def _spend(journal: Path, eur: str) -> None:
    AuditJournal(journal).append(
        actor="orchestrator",
        event="DECISION",
        payload={"cost": {"cost_schema": COST_SCHEMA, "cost_usd": "0", "cost_eur": eur}},
    )


def _entries(journal: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]


# --- cerveau ask -------------------------------------------------------------------------------


class FakeOrchestrator:
    def __init__(self, config: Config, journal: Path, tracer: Tracer | None) -> None:
        self.config, self.journal, self.tracer = config, journal, tracer
        self.questions: list[str] = []

    async def ask(self, question: str) -> RunResult:
        self.questions.append(question)
        check = BudgetGate(self.config, AuditJournal(self.journal)).check()  # D9 refusal
        return RunResult(
            request_id="req-1",
            answer=Answer(statut="refus", message="Non."),
            cost_eur=Decimal("0.0123"),
            tokens=456,
            tool_calls=2,
            elapsed_s=3.25,
            budget_alerts=tuple(alert.message() for alert in check.highest()),
        )


@pytest.fixture
def fake(budgeted: Path, journal: Path, monkeypatch: pytest.MonkeyPatch) -> list[FakeOrchestrator]:
    built: list[FakeOrchestrator] = []

    def build(config: Config, root: Path, tracer: Tracer | None = None) -> FakeOrchestrator:
        built.append(FakeOrchestrator(config, journal, tracer))
        return built[-1]

    monkeypatch.setattr(main, "build_orchestrator", build)
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", FAKE_KEY)
    return built


def test_ask_prints_the_answer_and_a_footer(fake: list[FakeOrchestrator], budgeted: Path) -> None:
    result = runner.invoke(app, ["ask", "Une question ?", "--config-dir", str(budgeted)])
    assert result.exit_code == 0, result.output
    assert result.stdout == "**Refus.** Non.\n"
    assert "— requête req-1 · 0,0123 € · 456 jetons · 2 appel(s) d'outil · 3,2 s" in result.stderr
    assert fake[0].questions == ["Une question ?"]
    assert FAKE_KEY not in result.output


def test_ask_without_langfuse_keys_warns_and_answers(
    fake: list[FakeOrchestrator], budgeted: Path
) -> None:
    result = runner.invoke(app, ["ask", "Q ?", "--config-dir", str(budgeted)])
    assert result.exit_code == 0, result.output
    assert "avertissement : traces Langfuse désactivées : aucune clé" in result.stderr
    assert isinstance(fake[0].tracer, NoTracer)


def test_ask_refuses_to_trace_to_a_remote_langfuse(
    fake: list[FakeOrchestrator], budgeted: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", FAKE_KEY)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", FAKE_KEY)
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    result = runner.invoke(app, ["ask", "Q ?", "--config-dir", str(budgeted)])
    assert result.exit_code == 0, result.output
    assert "serveur non local refusé (cloud.langfuse.com, ADR-004)" in result.stderr
    assert isinstance(fake[0].tracer, NoTracer)
    assert FAKE_KEY not in result.output


def test_ask_json_and_budget_alerts(
    fake: list[FakeOrchestrator], budgeted: Path, journal: Path
) -> None:
    _spend(journal, "0.85")
    result = runner.invoke(app, ["ask", "Q ?", "--json", "--config-dir", str(budgeted)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["statut"] == "refus"
    assert "alerte budget : Budget du jour" in result.stderr
    assert "à 80 %" in result.stderr


def test_ask_is_refused_at_100_percent(
    fake: list[FakeOrchestrator], budgeted: Path, journal: Path
) -> None:
    _spend(journal, "1.00")
    result = runner.invoke(app, ["ask", "Q ?", "--config-dir", str(budgeted)])
    assert result.exit_code == 3
    assert result.stderr.splitlines()[-1].startswith("Refus (D9) : ")
    assert result.stdout == ""


def test_ask_is_blocked_while_budgets_are_undefined(
    journal: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "build_orchestrator", pytest.fail)
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    result = runner.invoke(app, ["ask", "Q ?", "--config-dir", str(REPO_ROOT / "config")])
    assert result.exit_code == 2
    assert result.stderr.startswith("Bloqué (R7) : ")
    assert not journal.exists()


def test_ask_needs_the_anthropic_key(
    fake: list[FakeOrchestrator], budgeted: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY")
    result = runner.invoke(app, ["ask", "Q ?", "--config-dir", str(budgeted)])
    assert result.exit_code == 2
    assert "ANTHROPIC_API_KEY absente" in result.stderr
    assert fake == []


def test_ask_warns_without_the_search_key(
    fake: list[FakeOrchestrator], budgeted: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY")
    result = runner.invoke(app, ["ask", "Q ?", "--config-dir", str(budgeted)])
    assert result.exit_code == 0
    assert "BRAVE_SEARCH_API_KEY absente" in result.stderr


def test_ask_reports_an_error_in_one_line(
    fake: list[FakeOrchestrator], budgeted: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(self: FakeOrchestrator, question: str) -> RunResult:
        raise RuntimeError("première ligne\nseconde ligne")

    monkeypatch.setattr(FakeOrchestrator, "ask", broken)
    result = runner.invoke(app, ["ask", "Q ?", "--config-dir", str(budgeted)])
    assert result.exit_code == 1
    assert "ERREUR : RuntimeError : première ligne" in result.stderr
    assert "seconde ligne" not in result.stderr


def test_missing_keys_is_a_presence_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CERVEAU_TEST_PRESENT", "")
    monkeypatch.delenv("CERVEAU_TEST_ABSENT", raising=False)
    assert main.missing_keys(("CERVEAU_TEST_PRESENT", "CERVEAU_TEST_ABSENT")) == [
        "CERVEAU_TEST_ABSENT"
    ]


# --- cerveau eval ------------------------------------------------------------------------------


class Runs:
    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.calls: list[tuple[list[str], dict[str, str], Path]] = []

    def __call__(self, command: Sequence[str], *, env: Mapping[str, str], cwd: Path) -> int:
        self.calls.append((list(command), dict(env), cwd))
        return self.code


@pytest.fixture
def home(tmp_path: Path, journal: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    suites = root / evaluate.SUITES_DIR
    suites.mkdir(parents=True)
    for name in ("beta", "alpha"):
        (suites / f"{name}.yaml").write_text("description: test\n", encoding="utf-8")
    monkeypatch.setenv("CERVEAU_HOME", str(root))
    monkeypatch.setattr(main.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", FAKE_KEY)
    return root


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> Runs:
    fake = Runs()
    monkeypatch.setattr(evaluate, "run_suite", fake)
    return fake


def test_offline_eval_runs_every_suite_without_keys(home: Path, runs: Runs, journal: Path) -> None:
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 0, result.output
    assert "2/2 suite(s) réussie(s)" in result.stdout
    assert [call[0][5] for call in runs.calls] == [
        str(home / evaluate.SUITES_DIR / f"{name}.yaml") for name in ("alpha", "beta")
    ]
    command, env, cwd = runs.calls[0]
    assert command[:4] == ["/bin/npx", "-y", evaluate.PROMPTFOO, "eval"]
    assert command[7] == str(home / "var" / "evals" / "offline" / "alpha.json")
    assert "-j" not in command and cwd == home
    assert env["CERVEAU_EVAL_MODE"] == "offline" and env["CERVEAU_HOME"] == str(home)
    assert "ANTHROPIC_API_KEY" not in env and "LANGFUSE_SECRET_KEY" not in env
    assert "CERVEAU_EVAL_CAMPAIGN" not in env
    assert not journal.exists()  # an offline run journals nothing


def test_eval_runs_the_named_suites_once(home: Path, runs: Runs) -> None:
    result = runner.invoke(app, ["eval", "beta", "beta"])
    assert result.exit_code == 0, result.output
    assert len(runs.calls) == 1 and runs.calls[0][0][5].endswith("beta.yaml")


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["eval", "gamma"], "suite(s) inconnue(s) : gamma ; disponibles : alpha, beta"),
        (["eval", "--live", "alpha"], "--live exige --campaign"),
        (["eval", "--live", "--campaign", "x", "alpha"], "--live exige --campaign"),
        (["eval", "--live", "--campaign", "Bad_Name", "alpha"], "--live exige --campaign"),
        (["eval", "--live", "--campaign", "essai-1"], "--live exige la liste des suites"),
        (["eval", "--campaign", "essai-1", "alpha"], "--campaign ne vaut qu'avec --live"),
    ],
)
def test_eval_usage_is_refused_before_any_run(
    home: Path, runs: Runs, journal: Path, args: list[str], message: str
) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert message in result.stderr
    assert runs.calls == [] and not journal.exists()


def test_a_failed_suite_fails_the_command(home: Path, runs: Runs) -> None:
    runs.code = 1
    result = runner.invoke(app, ["eval", "alpha"])
    assert result.exit_code == 1
    assert "Suite(s) en échec : alpha" in result.stderr


def test_eval_needs_npx(home: Path, runs: Runs, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.shutil, "which", lambda name: None)
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 1 and "npx introuvable" in result.stderr
    assert runs.calls == []


def test_live_eval_is_blocked_while_budgets_are_undefined(
    home: Path, runs: Runs, journal: Path
) -> None:
    config = str(REPO_ROOT / "config")
    args = ["eval", "--live", "--campaign", "essai-1", "alpha", "--config-dir", config]
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert result.stderr.startswith("Bloqué (R7) : ")
    assert runs.calls == [] and not journal.exists()


def test_live_eval_is_refused_at_100_percent(
    home: Path, runs: Runs, journal: Path, budgeted: Path
) -> None:
    _spend(journal, "1.00")
    args = ["eval", "--live", "--campaign", "essai-1", "alpha", "--config-dir", str(budgeted)]
    result = runner.invoke(app, args)
    assert result.exit_code == 3 and result.stderr.startswith("Refus (D9) : ")
    assert runs.calls == []
    actors = [entry["actor"] for entry in _entries(journal)]
    assert actors[0] == "orchestrator" and set(actors[1:]) == {"policy"}  # threshold alerts


def test_live_eval_needs_the_anthropic_key(
    home: Path, runs: Runs, budgeted: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    args = ["eval", "--live", "--campaign", "essai-1", "alpha", "--config-dir", str(budgeted)]
    result = runner.invoke(app, args)
    assert result.exit_code == 2 and "ANTHROPIC_API_KEY absente" in result.stderr
    assert runs.calls == []


def test_live_eval_journals_its_campaign(
    home: Path, runs: Runs, journal: Path, budgeted: Path
) -> None:
    args = ["eval", "--live", "--campaign", "essai-1", "alpha", "--config-dir", str(budgeted)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    command, env, _ = runs.calls[0]
    assert command[-2:] == ["-j", "1"]
    assert command[7] == str(home / "var" / "evals" / "essai-1" / "alpha.json")
    assert env["CERVEAU_EVAL_MODE"] == "live" and env["CERVEAU_EVAL_CAMPAIGN"] == "essai-1"
    assert env["ANTHROPIC_API_KEY"] == FAKE_KEY  # a live run uses the real models
    (entry,) = _entries(journal)
    assert (entry["actor"], entry["event"], entry["request_id"]) == (
        "orchestrator",
        "DECISION",
        "eval-essai-1",
    )
    payload = AuditJournal(journal).read_payload(entry["payload_ref"])
    assert payload == {
        "status": "campagne_eval",
        "campaign": "essai-1",
        "mode": "live",
        "suites": ["alpha"],
    }
    assert entry["versions"] == {"config": load_config(budgeted).digest}
    assert verify(journal).ok


def test_the_repository_suites_are_found() -> None:
    assert "promptfooconfig" in [path.stem for path in evaluate.find_suites(REPO_ROOT, [])]
