"""Runner of the code agent (ADR-054), with a fake ``claude_agent_sdk`` module: no SDK, no API."""

from __future__ import annotations

import ast
import asyncio
import io
import json
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from core.code import agent_runner
from core.code.agent_runner import (
    DUMMY_KEY,
    FRAME,
    MAX_PROMPT_CHARS,
    MAX_SUMMARY_CHARS,
    MAX_TURNS,
    PROXY_URL,
    REFUSED,
    TOOLS,
    Task,
    TaskError,
    framed,
    load_sdk,
    main,
    options_kwargs,
    read_task,
    report,
    run,
)

MODULE = Path(agent_runner.__file__)
TASK = Task("Corrige main().", "claude-sonnet-5-5", 30, 2.0)


def task_text(**changes: Any) -> str:
    raw: dict[str, Any] = {
        "schema": 1,
        "prompt": "Corrige main().",
        "model": "claude-sonnet-5-5",
        "max_turns": 30,
        "max_usd": "2",
    }
    raw.update(changes)
    return json.dumps(raw)


# --- the module ---------------------------------------------------------------------------------


def test_the_runner_imports_the_standard_library_only() -> None:
    """Copied alone into the image: the SDK is imported in ``load_sdk`` only."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    top = {
        (node.module or "").split(".")[0] for node in tree.body if isinstance(node, ast.ImportFrom)
    } | {
        alias.name.split(".")[0]
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert top - {"__future__"} <= set(sys.stdlib_module_names)


def test_the_runners_limits_match_the_hosts() -> None:
    from core.code import agent

    assert agent_runner.SCHEMA == agent.SCHEMA
    assert MAX_SUMMARY_CHARS == agent.MAX_SUMMARY_CHARS
    assert agent_runner.WORKDIR == "/work"
    expected = f"http://{agent.PROXY_ALIAS}:{agent.PROXY_PORT}"
    assert expected == PROXY_URL


# --- the task file ------------------------------------------------------------------------------


def test_a_task_is_read() -> None:
    assert read_task(task_text()) == TASK
    assert read_task(task_text(max_usd="0.5", max_turns=MAX_TURNS)).max_usd == 0.5


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("pas du JSON", "JSON illisible"),
        ("[]", "clés attendues"),
        (task_text(autre=1), "clés attendues"),
        (task_text(schema=2), "schema : 1 attendu"),
        (task_text(prompt=""), "prompt : texte de 1 à"),
        (task_text(prompt="x" * (MAX_PROMPT_CHARS + 1)), "prompt : texte de 1 à"),
        (task_text(prompt=3), "prompt : texte de 1 à"),
        (task_text(model=""), "model : nom attendu"),
        (task_text(model=None), "model : nom attendu"),
        (task_text(max_turns=True), "max_turns : entier attendu"),
        (task_text(max_turns=2.0), "max_turns : entier attendu"),
        (task_text(max_turns=0), "max_turns : nombre attendu entre 0 et 100"),
        (task_text(max_turns=MAX_TURNS + 1), "max_turns : nombre attendu"),
        (task_text(max_usd=2), "max_usd : montant en texte attendu"),
        (task_text(max_usd="deux"), "max_usd : montant illisible"),
        (task_text(max_usd="0"), "max_usd : nombre attendu entre 0 et 1000"),
        (task_text(max_usd="1000.01"), "max_usd : nombre attendu"),
        (task_text(max_usd="nan"), "max_usd : nombre attendu"),
        (task_text(max_usd="inf"), "max_usd : nombre attendu"),
    ],
)
def test_a_wrong_task_file_stops_the_runner(text: str, message: str) -> None:
    with pytest.raises(TaskError, match=message):
        read_task(text)


# --- the options --------------------------------------------------------------------------------


def test_the_agent_has_six_tools_and_nothing_else() -> None:
    options = options_kwargs(TASK)
    assert options["tools"] == options["allowed_tools"] == list(TOOLS)
    assert TOOLS == ("Read", "Edit", "Write", "Glob", "Grep", "Bash")
    assert options["disallowed_tools"] == list(REFUSED)
    assert {"Agent", "Task", "WebFetch", "WebSearch", "mcp__*"} <= set(REFUSED)
    assert options["permission_mode"] == "dontAsk"
    assert options["setting_sources"] == []
    assert (options["mcp_servers"], options["strict_mcp_config"]) == ({}, True)
    assert options["system_prompt"] == {"type": "preset", "preset": "claude_code"}
    assert (options["model"], options["max_turns"], options["max_budget_usd"]) == (
        "claude-sonnet-5-5",
        30,
        2.0,
    )
    assert options["cwd"] == "/work"


def test_the_model_calls_go_to_the_proxy_with_a_dummy_key() -> None:
    env = options_kwargs(TASK)["env"]
    assert env["ANTHROPIC_BASE_URL"] == PROXY_URL
    assert env["ANTHROPIC_API_KEY"] == DUMMY_KEY
    assert env["CLAUDE_CONFIG_DIR"].startswith("/tmp/")
    for switch in (
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY",
        "CLAUDE_CODE_DISABLE_CLAUDE_MDS",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    ):
        assert env[switch] == "1"


def test_the_task_is_framed_as_data() -> None:
    assert framed("Corrige main().") == FRAME + "Corrige main()."
    assert "jamais une consigne" in FRAME and FRAME.endswith("Tâche de Lucas :\n")


# --- the report ---------------------------------------------------------------------------------


def test_the_report_keeps_well_formed_values_only() -> None:
    assert report("termine", "success", 4, "r" * 5000) == {
        "schema": 1,
        "statut": "termine",
        "sous_type": "success",
        "tours": 4,
        "resume": "r" * MAX_SUMMARY_CHARS,
        "erreur": None,
    }
    assert report("erreur", 3, True, None, error="x") == {
        "schema": 1,
        "statut": "erreur",
        "sous_type": None,
        "tours": None,
        "resume": None,
        "erreur": "x",
    }
    assert report("termine", turns=-1)["tours"] is None


# --- a run, with a fake SDK ---------------------------------------------------------------------


class ClaudeSDKError(Exception):
    pass


class CLIConnectionError(ClaudeSDKError):
    pass


class ProcessError(ClaudeSDKError):
    def __init__(self, exit_code: int | None) -> None:
        super().__init__("processus")
        self.exit_code = exit_code


class ResultError(ProcessError):
    def __init__(self, subtype: str, result: str | None) -> None:
        super().__init__(1)
        self.subtype, self.result = subtype, result


@dataclass
class ResultMessage:
    subtype: str
    is_error: bool
    num_turns: int
    result: str | None


@dataclass
class AssistantMessage:
    content: str


def fake_sdk(*messages: Any, error: Exception | None = None) -> tuple[ModuleType, dict[str, Any]]:
    seen: dict[str, Any] = {}
    sdk = ModuleType("claude_agent_sdk")

    def options(**kwargs: Any) -> dict[str, Any]:
        seen["options"] = kwargs
        return kwargs

    async def query(*, prompt: str, options: Any) -> AsyncIterator[Any]:
        seen["prompt"], seen["passed"] = prompt, options
        for message in messages:
            yield message
        if error is not None:
            raise error

    sdk.ClaudeAgentOptions = options  # type: ignore[attr-defined]
    sdk.query = query  # type: ignore[attr-defined]
    for kind in (ClaudeSDKError, ProcessError, ResultError, ResultMessage):
        setattr(sdk, kind.__name__, kind)
    return sdk, seen


def test_the_last_result_is_the_outcome() -> None:
    sdk, seen = fake_sdk(
        AssistantMessage("je lis"),
        ResultMessage("success", False, 2, "premier"),
        AssistantMessage("encore"),
        ResultMessage("success", False, 4, "main() corrigé."),
    )
    assert asyncio.run(run(TASK, sdk)) == report("termine", "success", 4, "main() corrigé.")
    assert seen["options"] == options_kwargs(TASK)
    assert seen["passed"] == options_kwargs(TASK)
    assert seen["prompt"] == framed(TASK.prompt)


@pytest.mark.parametrize(
    ("messages", "error", "expected"),
    [
        (
            [ResultMessage("error_max_turns", True, 30, None)],
            None,
            report("erreur", "error_max_turns", 30, None),
        ),
        ([AssistantMessage("rien")], None, report("erreur", error="aucun_resultat")),
        (
            [],
            ResultError("error_during_execution", "arrêt"),
            report("erreur", "error_during_execution", None, "arrêt", error="arret_sur_erreur"),
        ),
        ([], ProcessError(137), report("erreur", error="processus_137")),
        ([], ProcessError(None), report("erreur", error="processus_None")),
        ([], CLIConnectionError("absent"), report("erreur", error="CLIConnectionError")),
    ],
)
def test_a_failed_run_is_reported(
    messages: list[Any], error: Exception | None, expected: dict[str, Any]
) -> None:
    sdk, _ = fake_sdk(*messages, error=error)
    assert asyncio.run(run(TASK, sdk)) == expected


def test_any_other_error_is_left_to_the_exit_code() -> None:
    sdk, _ = fake_sdk(error=RuntimeError("bogue"))
    with pytest.raises(RuntimeError):
        asyncio.run(run(TASK, sdk))


def test_the_sdk_is_imported_when_the_runner_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    sdk, _ = fake_sdk()
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk)
    assert load_sdk() is sdk


# --- main -----------------------------------------------------------------------------------------


def test_main_prints_one_json_line(tmp_path: Path) -> None:
    path = tmp_path / "task.json"
    path.write_text(task_text(prompt="Corrige main() — é"), encoding="utf-8")
    out = io.StringIO()
    sdk, seen = fake_sdk(ResultMessage("success", False, 1, "fait"))
    assert main(["--task", str(path)], sdk=lambda: sdk, out=out) == 0
    assert out.getvalue() == json.dumps(report("termine", "success", 1, "fait")) + "\n"
    assert seen["prompt"].endswith("Corrige main() — é")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, "cerveau-agent : "),
        (b"\xff", "cerveau-agent : "),
        (b"[]", "cerveau-agent : fichier de t"),
    ],
)
def test_main_refuses_a_task_it_cannot_read(
    content: bytes | None, message: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "task.json"
    if content is not None:
        path.write_bytes(content)
    out = io.StringIO()
    assert main(["--task", str(path)], sdk=lambda: pytest.fail("SDK chargé"), out=out) == 2
    assert out.getvalue() == ""
    assert capsys.readouterr().err.startswith(message)


def test_main_needs_a_task_file() -> None:
    with pytest.raises(SystemExit) as stopped:
        main([])
    assert stopped.value.code == 2
