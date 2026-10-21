from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _no_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lucas's own LANGFUSE_* variables never reach a test: no trace leaves a test run."""
    for name in [name for name in os.environ if name.startswith("LANGFUSE_")]:
        monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def _no_ntfy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lucas's NTFY_TOPIC and NTFY_TOKEN never reach a test: no alert leaves a test run."""
    for name in ("NTFY_TOPIC", "NTFY_TOKEN"):
        monkeypatch.delenv(name, raising=False)


QUESTIONS_XML = (
    "<evaluation>\n"
    + "".join(
        f"  <qa_pair><question>Question {i} ?</question><answer>{i}</answer></qa_pair>\n"
        for i in range(10)
    )
    + "</evaluation>\n"
)


def base_manifest(plugin_id: str = "demo_plugin") -> dict:
    return {
        "id": plugin_id,
        "version": "0.1.0",
        "domain": "finance",
        "kind": "tool",
        "transport": "mcp-stdio",
        "parity_label": "[Approximation]",
        "environments": ["dev", "paper"],
        "max_autonomy_level": "N2",
        "tools": [
            {
                "name": "portfolio_var",
                "description": "VaR et CVaR du portefeuille de test.",
                "action_class": "CALCUL",
                "annotations": {
                    "readOnlyHint": True,
                    "idempotentHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                },
                "input_schema": "schemas/portfolio_var.in.json",
                "output_schema": "schemas/portfolio_var.out.json",
            }
        ],
        "tests": "tests/",
        "evals": {"questions": "evals/questions.xml", "golden": "evals/golden.jsonl"},
        "slo": {"success_rate_min": 0.99, "p95_latency_ms": "A_DEFINIR"},
        "dependencies_licences": ["BSD-3-Clause", "MIT"],
    }


def agent_manifest(plugin_id: str = "demo_agent") -> dict:
    """An in-process agent (ADR-028): no tool, its entry point in its own package."""
    manifest = base_manifest(plugin_id)
    manifest.update(
        kind="agent",
        transport="in-process",
        tools=[],
        agent={"entrypoint": f"plugins.{plugin_id}.graph:build_graph"},
    )
    return manifest


@pytest.fixture
def make_plugin(tmp_path: Path) -> Callable[..., Path]:
    """Build a conforming plugin directory; callers then break one thing at a time."""

    def _make(plugin_id: str = "demo_plugin", manifest: dict | None = None) -> Path:
        root = tmp_path / "plugins" / plugin_id
        (root / "schemas").mkdir(parents=True)
        (root / "tests").mkdir()
        (root / "evals").mkdir()
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}
        for name in ("portfolio_var.in.json", "portfolio_var.out.json"):
            (root / "schemas" / name).write_text(json.dumps(schema), encoding="utf-8")
        (root / "tests" / "test_demo.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
        (root / "evals" / "questions.xml").write_text(QUESTIONS_XML, encoding="utf-8")
        (root / "evals" / "golden.jsonl").write_text(
            '{"input": "q", "expected": "a"}\n', encoding="utf-8"
        )
        data = manifest if manifest is not None else base_manifest(plugin_id)
        (root / "plugin.yaml").write_text(
            yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
        )
        return root

    return _make


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A copy of the real config/ directory that tests may modify freely."""
    target = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", target)
    return target
