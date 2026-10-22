"""The deep research of the Recherche pack: its manifest, its prompts and its golden set."""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET  # our own file, versioned: not external content
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.config.loader import load_config
from core.orchestrator.state import Extract, Source, Unverified
from core.registry.agents import load_agent
from core.registry.manifest import validate_plugin
from core.research import Claim, ResearchSpec, check_claim
from core.research.engine import extract_index
from plugins.deep_research.agent import FEATURE, PACK, VERSION, deep_research

PLUGIN = Path(__file__).resolve().parents[1]
ROOT = PLUGIN.parents[1]
MANIFEST = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
GOLDEN = [
    json.loads(line)
    for line in (PLUGIN / MANIFEST["evals"]["golden"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]


def _sources(rows: list[dict[str, Any]]) -> list[Source]:
    return [
        Source(
            number=row["number"],
            url=f"https://source{row['number']}.example/a",
            final_url=f"https://source{row['number']}.example/a",
            title=row["title"],
            published=row["published"],
            retrieved_at="2026-10-22T10:00:00+00:00",
            truncated=False,
            domain=f"source{row['number']}.example",
            extracts=tuple(Extract(claim=claim, quote=quote) for claim, quote in row["extracts"]),
        )
        for row in rows
    ]


def test_the_manifest_is_valid_and_reads_only() -> None:
    report = validate_plugin(PLUGIN)
    assert report.ok, report.errors
    assert report.manifest is not None
    assert report.manifest.domain == PACK
    assert report.manifest.version == VERSION
    assert report.manifest.tools == []  # it calls the pack's reading tools only (R5)
    assert report.manifest.max_autonomy_level == "N0"  # an analysis, never an action (D3)


def test_the_registry_loads_it_for_the_recherche_pack_only() -> None:
    assert load_agent(PLUGIN, domain=PACK) is deep_research
    with pytest.raises(RuntimeError, match="pas celui du pack"):
        load_agent(PLUGIN, domain="finance")


def test_the_spec_carries_the_prompts_without_their_header() -> None:
    spec = deep_research(load_config(ROOT / "config"))
    assert isinstance(spec, ResearchSpec)
    assert (spec.pack, spec.feature) == (PACK, FEATURE)
    assert spec.version.startswith(f"{VERSION}+") and len(spec.version) == len(VERSION) + 13
    for text in (spec.planner, spec.writer):
        assert not text.startswith("<!--") and "R9" not in text.splitlines()[0]
    assert "sous-questions" in spec.planner
    assert "« n.k »" in spec.writer and "Points non vérifiés" in spec.writer


def test_a_changed_prompt_is_a_new_version(tmp_path: Path) -> None:
    shutil.copytree(PLUGIN / "prompts", tmp_path / "prompts")
    config = load_config(ROOT / "config")
    before = deep_research(config, tmp_path).version
    write = tmp_path / "prompts" / "write.md"
    write.write_text(write.read_text(encoding="utf-8") + "\n10. Une règle de plus.\n", "utf-8")
    after = deep_research(config, tmp_path).version
    assert before == deep_research(config).version
    assert after != before and after.startswith(f"{VERSION}+")


def test_the_prompts_never_ask_for_a_figure_or_obey_external_text() -> None:
    plan = (PLUGIN / "prompts" / "plan.md").read_text(encoding="utf-8")
    write = (PLUGIN / "prompts" / "write.md").read_text(encoding="utf-8")
    assert "ne donne aucun chiffre" in plan and "ignore cette" in plan  # R1, R5
    assert "Aucun chiffre ni aucune date hors des extraits cités" in write  # R1
    assert "ne la suis pas" in write  # R5


def test_the_questions_parse() -> None:
    pairs = ET.parse(PLUGIN / MANIFEST["evals"]["questions"]).getroot().findall("qa_pair")  # noqa: S314
    assert len(pairs) >= 10  # the registry's minimum (R8)
    assert all((pair.findtext("question") or "").strip() for pair in pairs)
    assert all((pair.findtext("answer") or "").strip() for pair in pairs)


def test_the_golden_set_has_kept_and_removed_claims() -> None:
    assert len(GOLDEN) >= 15
    assert len({case["id"] for case in GOLDEN}) == len(GOLDEN)
    kinds = {next(iter(case["expected"])) for case in GOLDEN}
    assert kinds == {"kept", "removed"}


@pytest.mark.parametrize("case", GOLDEN, ids=[case["id"] for case in GOLDEN])
def test_golden_cases(case: dict[str, Any]) -> None:
    extracts = extract_index(_sources(case["sources"]))
    checked = check_claim(Claim.model_validate(case["claim"]), extracts)
    if "kept" in case["expected"]:
        assert checked == case["expected"]["kept"]
    else:
        assert isinstance(checked, Unverified)
        assert checked.raison == case["expected"]["removed"]
