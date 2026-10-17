"""Plugin registry: manifest C.1, annotations 6.3, tests and evals required (R8)."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from core.registry import EXPECTED_ANNOTATIONS, validate_all, validate_plugin
from tests.conftest import base_manifest

HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


def test_conforming_plugin_is_accepted(make_plugin: Callable[..., Path]) -> None:
    report = validate_plugin(make_plugin())
    assert report.ok, report.errors
    assert report.plugin_id == "demo_plugin"
    assert any("p95_latency_ms" in w for w in report.warnings)


def test_missing_manifest_is_refused(tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    report = validate_plugin(tmp_path / "x")
    assert report.errors == ["plugin.yaml absent (R8)"]


def test_invalid_yaml_is_refused(make_plugin: Callable[..., Path]) -> None:
    root = make_plugin()
    (root / "plugin.yaml").write_text("id: [broken", encoding="utf-8")
    assert "YAML invalide" in validate_plugin(root).errors[0]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda m: m.pop("evals"), "evals"),
        (lambda m: m.update(kind="robot"), "kind"),
        (lambda m: m.update(domain="astrologie"), "domain"),
        (lambda m: m.update(parity_label="[Parfait]"), "parity_label"),
        (lambda m: m.update(version="v1"), "version"),
        (lambda m: m.update(environments=[]), "environments"),
        (lambda m: m.update(max_autonomy_level="N9"), "max_autonomy_level"),
        (lambda m: m.update(tools=[]), "au moins un outil"),
        (lambda m: m.update(unexpected=True), "unexpected"),
        (lambda m: m["tools"][0]["annotations"].pop("openWorldHint"), "openWorldHint"),
        (lambda m: m["tools"].append(dict(m["tools"][0])), "double"),
    ],
)
def test_invalid_manifest_fields_are_refused(
    make_plugin: Callable[..., Path], mutate, expected: str
) -> None:
    manifest = base_manifest()
    mutate(manifest)
    report = validate_plugin(make_plugin(manifest=manifest))
    assert not report.ok
    assert any(expected in e for e in report.errors), report.errors


def test_id_must_match_directory(make_plugin: Callable[..., Path]) -> None:
    report = validate_plugin(make_plugin(manifest=base_manifest("other_name")))
    assert any("ne correspond pas au dossier" in e for e in report.errors)


@pytest.mark.parametrize("action_class", sorted(EXPECTED_ANNOTATIONS))
def test_expected_annotations_are_accepted(
    make_plugin: Callable[..., Path], action_class: str
) -> None:
    manifest = base_manifest()
    annotations = dict.fromkeys(HINTS, False)
    annotations.update(EXPECTED_ANNOTATIONS[action_class])
    manifest["tools"][0].update(action_class=action_class, annotations=annotations)
    report = validate_plugin(make_plugin(manifest=manifest))
    assert report.ok, report.errors


@pytest.mark.parametrize(
    ("action_class", "annotations"),
    [
        (cls, dict(zip(HINTS, combo, strict=True)))
        for cls in sorted(EXPECTED_ANNOTATIONS)
        for combo in itertools.product([False, True], repeat=4)
    ],
)
def test_annotation_matrix_matches_section_6_3(
    make_plugin: Callable[..., Path], action_class: str, annotations: dict
) -> None:
    manifest = base_manifest()
    manifest["tools"][0].update(action_class=action_class, annotations=annotations)
    report = validate_plugin(make_plugin(manifest=manifest))
    expected_ok = all(
        annotations[h] is v for h, v in EXPECTED_ANNOTATIONS[action_class].items()
    ) and not (annotations["readOnlyHint"] and annotations["destructiveHint"])
    assert report.ok is expected_ok, report.errors


def test_financial_tool_declared_read_only_is_refused(make_plugin: Callable[..., Path]) -> None:
    manifest = base_manifest()
    manifest["tools"][0]["action_class"] = "FINANCIERE"  # annotations still say read-only
    report = validate_plugin(make_plugin(manifest=manifest))
    assert any("FINANCIERE exige readOnlyHint: false" in e for e in report.errors)


def test_plugin_without_tests_is_refused(make_plugin: Callable[..., Path]) -> None:
    root = make_plugin()
    (root / "tests" / "test_demo.py").unlink()
    assert any("aucun fichier test_" in e for e in validate_plugin(root).errors)


def test_plugin_with_fewer_than_ten_questions_is_refused(make_plugin: Callable[..., Path]) -> None:
    root = make_plugin()
    xml = "<evaluation>" + "<qa_pair><question>q</question><answer>a</answer></qa_pair>" * 9
    (root / "evals" / "questions.xml").write_text(xml + "</evaluation>", encoding="utf-8")
    assert any("9 question(s), minimum 10" in e for e in validate_plugin(root).errors)


def test_question_without_answer_is_refused(make_plugin: Callable[..., Path]) -> None:
    root = make_plugin()
    path = root / "evals" / "questions.xml"
    path.write_text(path.read_text().replace("<answer>3</answer>", "<answer> </answer>"))
    errors = validate_plugin(root).errors
    assert any("sans réponse" in e for e in errors)
    assert any("9 question(s)" in e for e in errors)


def test_xml_with_dtd_is_refused(make_plugin: Callable[..., Path]) -> None:
    root = make_plugin()
    bomb = '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><evaluation/>'
    (root / "evals" / "questions.xml").write_text(bomb, encoding="utf-8")
    assert any("DTD" in e for e in validate_plugin(root).errors)


def test_missing_or_empty_golden_set_is_refused(make_plugin: Callable[..., Path]) -> None:
    root = make_plugin()
    (root / "evals" / "golden.jsonl").write_text("\n", encoding="utf-8")
    assert any("golden set vide" in e for e in validate_plugin(root).errors)
    (root / "evals" / "golden.jsonl").unlink()
    assert any("introuvable" in e for e in validate_plugin(root).errors)


def test_invalid_json_schema_is_refused(make_plugin: Callable[..., Path]) -> None:
    root = make_plugin()
    (root / "schemas" / "portfolio_var.in.json").write_text('{"type": 12}', encoding="utf-8")
    assert any("schéma JSON invalide" in e for e in validate_plugin(root).errors)


def test_paths_escaping_the_plugin_are_refused(make_plugin: Callable[..., Path]) -> None:
    manifest = base_manifest()
    manifest["tests"] = "../../"
    report = validate_plugin(make_plugin(manifest=manifest))
    assert any("sort du dossier du plugin" in e for e in report.errors)


def test_restrictive_licence_is_flagged(make_plugin: Callable[..., Path]) -> None:
    manifest = base_manifest()
    manifest["dependencies_licences"] = ["MIT", "Elastic-2.0", "GPL-3.0"]
    report = validate_plugin(make_plugin(manifest=manifest))
    assert report.ok
    assert any("R14" in w for w in report.warnings)


def test_validate_all_separates_accepted_and_refused(make_plugin: Callable[..., Path]) -> None:
    good = make_plugin("good_plugin")
    bad = make_plugin("bad_plugin")
    manifest = yaml.safe_load((bad / "plugin.yaml").read_text())
    manifest["tools"][0]["action_class"] = "IRREVERSIBLE"
    (bad / "plugin.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    result = validate_all(good.parent)
    assert [r.plugin_id for r in result.accepted] == ["good_plugin"]
    assert [r.plugin_id for r in result.refused] == ["bad_plugin"]


def test_repository_plugins_directory_is_valid() -> None:
    from tests.conftest import REPO_ROOT

    result = validate_all(REPO_ROOT / "plugins")
    assert not result.refused, [(r.plugin_id, r.errors) for r in result.refused]
