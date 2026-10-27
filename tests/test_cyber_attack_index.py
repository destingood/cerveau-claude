"""Frozen ATT&CK index (ADR-056): build from a synthetic bundle, bounds, write and read back."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from core.cyber import attack
from core.cyber.attack import (
    DESCRIPTION_MAX,
    KINDS,
    NOTICE,
    AttackError,
    index_path,
    read_index,
    write_index,
)
from tests.attack_bundle import (
    APT,
    COMMIT,
    DUMPING,
    EXECUTION,
    INTERPRETER,
    LSASS,
    POWERSHELL,
    PREVENTION,
    SAMPLE,
    SAMPLE_RELATIONSHIPS,
    SOURCE_URL,
    VERSION,
    build,
    bundle,
    collection,
    obj,
    relation,
    tactic,
    technique,
)


def by_id(objects: list[dict[str, Any]] | None = None) -> dict[str, attack.AttackObject]:
    index, _ = build(objects)
    return {o.id: o for o in index.objects}


def test_the_sample_bundle_gives_the_index() -> None:
    index, report = build()
    assert (index.version, index.collection_version) == ("20.0", "20.0")
    assert index.spec_versions == ["3.3.0"]
    assert (index.commit, index.source_url, index.notice) == (COMMIT, SOURCE_URL, NOTICE)
    assert index.bundle_bytes == len(bundle())
    assert dict(report.kinds) == {
        "tactic": 3,
        "technique": 5,
        "subtechnique": 2,
        "mitigation": 3,
        "detection_strategy": 1,
        "group": 1,
        "software": 1,
        "campaign": 1,
    }
    assert (report.skipped, report.duplicates, report.relationships) == (0, 0, SAMPLE_RELATIONSHIPS)
    kinds = [KINDS.index(o.kind) for o in index.objects]
    assert kinds == sorted(kinds)
    found = {o.id: o for o in index.objects}
    assert found["T1059"].tactics == ["TA0002"]
    assert found["T1059"].subtechniques == ["T1059.001"]
    assert found["T1059"].mitigations == ["M1038"]
    assert found["T1059.001"].parent == "T1059"
    assert (found["T1059.001"].mitigations, found["T1059.001"].detection_strategies) == (
        ["M1042"],
        ["DET0001"],
    )
    assert found["T1059.001"].platforms == ["Windows", "Linux", "macOS"]
    assert found["M1043"].techniques == ["T1003.001"]
    assert found["DET0001"].techniques == ["T1059.001"]
    assert found["G0007"].techniques == ["T1003.001", "T1059.001"]  # the tool it uses is not one
    assert found["G0007"].aliases == ["Sofacy", "Fancy Bear"]  # its own name is not an alias
    assert found["S0002"].aliases == []  # software aliases come from x_mitre_aliases
    assert found["C0024"].techniques == ["T1059"]
    assert found["TA0002"].tactics == []  # a tactic is not linked to itself
    assert found["TA0002"].url == "https://attack.mitre.org/tactics/TA0002"


def test_retired_objects_are_kept_with_their_status() -> None:
    found = by_id()
    assert (found["T1086"].revoked, found["T1086"].revoked_by) == (True, "T1059.001")
    assert (found["T1064"].deprecated, found["T1064"].mitigations) == (True, [])
    assert "T1064" not in found["M1038"].techniques  # a link to a retired technique is not shown


def test_citations_and_hidden_characters_leave_the_description() -> None:
    found = by_id()
    assert found["T1059.001"].description == (
        "Adversaries may abuse PowerShell commands and scripts for execution."
    )
    hidden = technique(
        "T1105",
        "Ingress Tool Transfer",
        "command-and-control",
        description="Line one​.\nLine\ttwo \ud800(Citation: Example)‮ end.",
    )
    text = by_id([*SAMPLE, hidden])["T1105"].description
    assert "Citation" not in text
    assert not any(c in text for c in "​\n\t\ud800‮")
    assert text.startswith("Line one")
    assert text.endswith("end.")


def test_a_long_description_is_cut() -> None:
    long = technique("T1105", "Ingress Tool Transfer", description="word " * 1000)
    found = by_id([*SAMPLE, long])["T1105"]
    assert len(found.description) <= DESCRIPTION_MAX
    assert found.description_truncated
    assert not by_id()["T1059"].description_truncated


def test_a_page_outside_attack_mitre_org_is_dropped() -> None:
    foreign = technique("T1105", "Ingress Tool Transfer")
    foreign["external_references"][0]["url"] = "https://attack.example/techniques/T1105"
    assert by_id([*SAMPLE, foreign])["T1105"].url is None


@pytest.mark.parametrize(
    "bad",
    [
        obj("course-of-action", "T1234", "Mitigation with a technique id"),
        obj("course-of-action", "M9999", ""),
        obj("course-of-action", "M9999", "No mitre reference", external_references=[]),
        technique("TA0099", "Technique with a tactic id"),
        {**technique("T1999", "No STIX id"), "id": 7},
    ],
    ids=["wrong-id", "no-name", "no-ref", "wrong-tech", "no-stix"],
)
def test_an_object_without_a_fitting_identifier_is_skipped(bad: dict[str, Any]) -> None:
    index, report = build([*SAMPLE, bad])
    assert report.skipped == 1
    assert len(index.objects) == len(build()[0].objects)


def test_objects_of_unknown_types_are_ignored() -> None:
    _, report = build([*SAMPLE, {"type": "marking-definition", "id": "x"}, "text", 3])
    assert (report.skipped, report.duplicates) == (0, 0)


def test_a_duplicate_keeps_the_current_then_the_latest_object() -> None:
    retired = technique("T1059", "Old interpreter", x_mitre_deprecated=True, modified="2030")
    retired["id"] = "attack-pattern--retired"
    later = technique("T1003", "OS Credential Dumping, later", modified="2026-01-01T00:00:00.000Z")
    later["id"] = "attack-pattern--later"
    index, report = build([*SAMPLE, retired, later])
    found = {o.id: o for o in index.objects}
    assert report.duplicates == 2
    assert (found["T1059"].name, found["T1059"].deprecated) == (
        "Command and Scripting Interpreter",
        False,
    )
    assert found["T1003"].name == "OS Credential Dumping, later"
    # The relations of the object left out are lost with it (ADR-056): T1003.001 had DUMPING.
    assert found["T1003"].subtechniques == []
    assert found["T1003.001"].parent is None


def test_a_duplicate_with_the_same_date_keeps_the_smaller_stix_identifier() -> None:
    twin = technique("T1003", "Twin")
    twin["id"] = "attack-pattern--0"
    assert by_id([*SAMPLE, twin])["T1003"].name == "Twin"
    assert DUMPING["id"] > twin["id"]


def test_retired_relations_and_odd_links_are_not_kept() -> None:
    gone = relation("mitigates", PREVENTION, POWERSHELL, revoked=True)
    old = relation("detects", PREVENTION, LSASS, x_mitre_deprecated=True)
    wrong = relation("mitigates", APT, INTERPRETER)  # a group mitigates nothing
    across = relation("revoked-by", PREVENTION, INTERPRETER)  # a mitigation by a technique
    unknown = relation("uses", APT, {"id": "attack-pattern--unknown"})
    _, report = build([*SAMPLE, gone, old, wrong, across, unknown])
    found = by_id([*SAMPLE, gone, old, wrong, across, unknown])
    assert report.relationships == SAMPLE_RELATIONSHIPS
    assert found["T1059.001"].mitigations == ["M1042"]
    assert found["M1038"].revoked_by is None
    assert found["G0007"].techniques == ["T1003.001", "T1059.001"]


def test_a_current_tactic_wins_over_a_retired_one() -> None:
    retired = tactic("TA0099", "Old execution", "execution", x_mitre_deprecated=True)
    for objects in ([*SAMPLE, retired], [retired, *SAMPLE]):
        assert by_id(objects)["T1059"].tactics == ["TA0002"]


def test_a_phase_of_another_kill_chain_is_not_a_tactic() -> None:
    other = technique("T1105", "Ingress Tool Transfer")
    other["kill_chain_phases"] = [
        {"kill_chain_name": "mitre-mobile-attack", "phase_name": "execution"},
        {"kill_chain_name": "mitre-attack", "phase_name": "Execution!"},
    ]
    assert by_id([*SAMPLE, other])["T1105"].tactics == []
    assert EXECUTION["x_mitre_shortname"] == "execution"


def test_a_bundle_of_another_version_is_refused() -> None:
    with pytest.raises(AttackError, match=r"version 19\.1 et non 20\.0"):
        build([collection("19.1"), *SAMPLE[1:]])


def test_a_bundle_without_collection_keeps_its_requested_version() -> None:
    index, _ = build(SAMPLE[1:])
    assert (index.version, index.collection_version) == (VERSION, None)


def test_a_bundle_without_technique_is_refused() -> None:
    with pytest.raises(AttackError, match="sans technique"):
        build([collection(), EXECUTION, PREVENTION])


@pytest.mark.parametrize(
    "body",
    [b"{", b"[]", b'{"type": "report", "objects": []}', b'{"type": "bundle", "objects": {}}'],
    ids=["json", "list", "type", "objects"],
)
def test_a_body_that_is_not_a_bundle_is_refused(body: bytes) -> None:
    with pytest.raises(AttackError, match="illisible"):
        attack.build_index(
            body,
            version=VERSION,
            commit=COMMIT,
            source_url=SOURCE_URL,
            sha256="0" * 64,
            built_at="2026-10-27T09:30:00+00:00",
        )


def test_private_unassigned_and_rebuilt_citations_leave_the_description() -> None:
    odd = technique(
        "T1105",
        "Ingress Tool Transfer",
        "command-and-control",
        description="Start \ue000 (Cit(Citation: A)ation: B) \u0378end.",
    )
    assert by_id([*SAMPLE, odd])["T1105"].description == "Start end."


def test_values_out_of_the_index_bounds_are_refused() -> None:
    with pytest.raises(AttackError, match="hors des bornes"):
        build(built_at="x" * 41)


def test_the_index_is_written_whole_and_read_back(tmp_path: Path) -> None:
    index, _ = build()
    path = index_path(tmp_path, VERSION)
    assert path == tmp_path / "var" / "cyber" / "attack" / "enterprise-attack-20.0.index.json"
    write_index(path, index)
    assert read_index(path, VERSION) == index
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_a_failed_write_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    path = index_path(tmp_path, VERSION)
    with pytest.raises(OSError, match="disk full"):
        write_index(path, build()[0])
    assert list(path.parent.iterdir()) == []


def test_a_missing_index_names_the_command(tmp_path: Path) -> None:
    with pytest.raises(AttackError) as caught:
        read_index(index_path(tmp_path, VERSION), VERSION)
    assert str(caught.value) == (
        "index ATT&CK 20.0 absent : lancer `cerveau cyber attack-fetch --version 20.0` (Lucas)"
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda data: data.update(bundle_sha256="A_VERIFIER"),
        lambda data: data.update(extra="field"),
        lambda data: data["objects"][0].update(id="X1"),
        lambda data: data["objects"][0].update(url="https://attack.example/x"),
        lambda data: data.update(notice="Another notice"),
        lambda data: data.update(format=2),
        lambda data: data["objects"][0].update(name="Power\u200bShell"),
        lambda data: data["objects"][0].update(description="Line one.\nLine two."),
        lambda data: data["objects"][0].update(description="Text (Citation: Example)."),
        lambda data: data["objects"][0].update(aliases=["Alias\ue000"]),
        lambda data: data["objects"].append(data["objects"][0]),
    ],
    ids=[
        *("sha", "extra", "id", "url", "notice", "format"),
        *("hidden", "lines", "cited", "private", "duplicate"),
    ],
)
def test_an_altered_index_is_refused(tmp_path: Path, change: Any) -> None:
    path = index_path(tmp_path, VERSION)
    write_index(path, build()[0])
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(AttackError, match="illisible ou altéré"):
        read_index(path, VERSION)


def test_an_index_too_large_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = index_path(tmp_path, VERSION)
    write_index(path, build()[0])
    monkeypatch.setattr(attack, "MAX_INDEX_BYTES", path.stat().st_size - 1)
    with pytest.raises(AttackError, match="illisible ou altéré"):
        read_index(path, VERSION)
