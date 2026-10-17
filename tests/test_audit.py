"""Hash-chained audit journal (R11): tampering must always be detected."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.audit import GENESIS_HASH, AuditError, AuditJournal, entry_hash, verify


def make_journal(tmp_path: Path, n: int = 5) -> AuditJournal:
    journal = AuditJournal(tmp_path / "journal.jsonl")
    for i in range(n):
        journal.append(actor="orchestrator", event="TOOL_CALL", payload={"i": i})
    return journal


def lines(journal: AuditJournal) -> list[str]:
    return journal.path.read_text(encoding="utf-8").splitlines()


def write_lines(journal: AuditJournal, content: list[str]) -> None:
    journal.path.write_text("".join(f"{line}\n" for line in content), encoding="utf-8")


def test_empty_journal_is_valid(tmp_path: Path) -> None:
    report = verify(tmp_path / "absent.jsonl")
    assert report.ok
    assert report.entries == 0
    assert report.head_hash == GENESIS_HASH


def test_append_builds_a_valid_chain(tmp_path: Path) -> None:
    journal = make_journal(tmp_path, 3)
    entries = [json.loads(line) for line in lines(journal)]
    assert [e["seq"] for e in entries] == [1, 2, 3]
    assert entries[0]["prev_hash"] == GENESIS_HASH
    assert entries[1]["prev_hash"] == entries[0]["hash"]
    assert all(entry_hash(e) == e["hash"] for e in entries)
    report = verify(journal.path)
    assert report.ok, report.errors
    assert report.head_seq == 3


def test_entry_follows_annex_c3_schema(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path / "j.jsonl")
    entry = journal.append(
        actor="policy",
        event="POLICY",
        request_id="req-1",
        versions={"prompt": "system@1.0.0", "config": "sha256:" + "a" * 64},
        payload={"decision": "refus"},
        redactions=["pii"],
    )
    assert set(entry) == {
        "seq",
        "ts",
        "prev_hash",
        "hash",
        "request_id",
        "actor",
        "event",
        "versions",
        "payload_ref",
        "redactions",
    }
    assert entry["payload_ref"].startswith("sha256:")
    assert journal.read_payload(entry["payload_ref"]) == {"decision": "refus"}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"actor": "hacker", "event": "POLICY"}, "acteur"),
        ({"actor": "policy", "event": "NOPE"}, "événement"),
        ({"actor": "policy", "event": "POLICY", "versions": {"x": "1"}}, "version"),
    ],
)
def test_append_rejects_unknown_values(tmp_path: Path, kwargs: dict, message: str) -> None:
    with pytest.raises(AuditError, match=message):
        AuditJournal(tmp_path / "j.jsonl").append(**kwargs)


def test_modified_entry_is_detected(tmp_path: Path) -> None:
    journal = make_journal(tmp_path)
    content = lines(journal)
    entry = json.loads(content[2])
    entry["actor"] = "lucas"
    content[2] = json.dumps(entry)
    write_lines(journal, content)
    report = verify(journal.path)
    assert not report.ok
    assert any("hash invalide" in e for e in report.errors)


def test_modified_entry_with_recomputed_hash_breaks_next_link(tmp_path: Path) -> None:
    journal = make_journal(tmp_path)
    content = lines(journal)
    entry = json.loads(content[1])
    entry["event"] = "KILL"
    entry["hash"] = entry_hash(entry)
    content[1] = json.dumps(entry)
    write_lines(journal, content)
    report = verify(journal.path)
    assert not report.ok
    assert any("prev_hash" in e for e in report.errors)


def test_deleted_entry_is_detected(tmp_path: Path) -> None:
    journal = make_journal(tmp_path)
    content = lines(journal)
    del content[2]
    write_lines(journal, content)
    assert not verify(journal.path).ok


def test_reordered_entries_are_detected(tmp_path: Path) -> None:
    journal = make_journal(tmp_path)
    content = lines(journal)
    content[1], content[3] = content[3], content[1]
    write_lines(journal, content)
    assert not verify(journal.path).ok


def test_inserted_entry_is_detected(tmp_path: Path) -> None:
    journal = make_journal(tmp_path)
    content = lines(journal)
    content.insert(2, content[2])
    write_lines(journal, content)
    assert not verify(journal.path).ok


def test_modified_payload_is_detected(tmp_path: Path) -> None:
    journal = make_journal(tmp_path, 2)
    payload_file = next(journal.payload_dir.glob("*.json"))
    payload_file.write_text('{"i": 999}', encoding="utf-8")
    report = verify(journal.path)
    assert any("payload" in e and "modifié" in e for e in report.errors)


def test_deleted_payload_is_detected(tmp_path: Path) -> None:
    journal = make_journal(tmp_path, 2)
    next(journal.payload_dir.glob("*.json")).unlink()
    assert any("introuvable" in e for e in verify(journal.path).errors)


def test_partial_last_line_is_detected_and_blocks_append(tmp_path: Path) -> None:
    journal = make_journal(tmp_path, 2)
    with journal.path.open("ab") as f:
        f.write(b'{"seq": 3')
    assert not verify(journal.path).ok
    with pytest.raises(AuditError, match="incomplète"):
        journal.append(actor="policy", event="POLICY")


def test_append_refuses_to_chain_on_a_tampered_tail(tmp_path: Path) -> None:
    journal = make_journal(tmp_path, 2)
    content = lines(journal)
    entry = json.loads(content[-1])
    entry["actor"] = "lucas"
    content[-1] = json.dumps(entry)
    write_lines(journal, content)
    with pytest.raises(AuditError, match="hash"):
        journal.append(actor="policy", event="POLICY")


def test_truncation_is_detected_only_with_an_external_anchor(tmp_path: Path) -> None:
    journal = make_journal(tmp_path, 5)
    report = verify(journal.path)
    anchor = f"{report.head_seq}:{report.head_hash}"
    write_lines(journal, lines(journal)[:3])
    assert verify(journal.path).ok  # documented limit: a clean truncation is invisible
    truncated = verify(journal.path, anchor=anchor)
    assert not truncated.ok
    assert any("tronqué" in e for e in truncated.errors)


def test_anchor_still_matches_after_growth(tmp_path: Path) -> None:
    journal = make_journal(tmp_path, 3)
    report = verify(journal.path)
    anchor = f"{report.head_seq}:{report.head_hash}"
    journal.append(actor="scheduler", event="DECISION")
    assert verify(journal.path, anchor=anchor).ok


def test_invalid_anchor_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ancre"):
        verify(tmp_path / "j.jsonl", anchor="12:md5:abc")


def test_garbage_lines_never_crash_verify(tmp_path: Path) -> None:
    path = tmp_path / "j.jsonl"
    path.write_bytes(b'[1,2]\n{"seq":1}\nnot json\n\xff\xfe\n\n')
    report = verify(path)
    assert not report.ok
    assert report.entries == 0


def test_concurrent_appends_keep_the_chain_valid(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path / "j.jsonl")

    def worker() -> None:
        for _ in range(10):
            journal.append(actor="orchestrator", event="TOOL_CALL")

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    report = verify(journal.path)
    assert report.ok, report.errors
    assert report.entries == 40


# --- property-based tests ----------------------------------------------------------------------

json_scalars = st.none() | st.booleans() | st.integers() | st.text(max_size=20)
payloads = st.recursive(
    json_scalars,
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4)
    ),
    max_leaves=10,
)
FIELDS = ["seq", "ts", "prev_hash", "hash", "request_id", "actor", "event", "versions"]


@settings(max_examples=60, deadline=None)
@given(items=st.lists(payloads, min_size=1, max_size=8))
def test_any_appended_sequence_verifies(
    tmp_path_factory: pytest.TempPathFactory, items: list
) -> None:
    journal = AuditJournal(tmp_path_factory.mktemp("h") / "j.jsonl")
    for item in items:
        journal.append(actor="orchestrator", event="TOOL_CALL", payload=item)
    report = verify(journal.path)
    assert report.ok, report.errors
    assert report.entries == len(items)


@settings(max_examples=60, deadline=None)
@given(
    n=st.integers(min_value=2, max_value=8),
    data=st.data(),
)
def test_any_single_field_change_is_detected(
    tmp_path_factory: pytest.TempPathFactory, n: int, data: st.DataObject
) -> None:
    journal = make_journal(tmp_path_factory.mktemp("h"), n)
    content = lines(journal)
    idx = data.draw(st.integers(min_value=0, max_value=n - 1))
    key = data.draw(st.sampled_from(FIELDS))
    entry = json.loads(content[idx])
    new_value = data.draw(json_scalars.filter(lambda v, old=entry[key]: v != old))
    entry[key] = new_value
    content[idx] = json.dumps(entry)
    write_lines(journal, content)
    assert not verify(journal.path).ok


@settings(max_examples=60, deadline=None)
@given(n=st.integers(min_value=2, max_value=8), data=st.data())
def test_any_permutation_or_deletion_is_detected(
    tmp_path_factory: pytest.TempPathFactory, n: int, data: st.DataObject
) -> None:
    journal = make_journal(tmp_path_factory.mktemp("h"), n)
    original = lines(journal)
    if data.draw(st.booleans()):
        mutated = data.draw(st.permutations(original).filter(lambda p: p != original))
    else:
        drop = data.draw(st.integers(min_value=0, max_value=n - 2))  # not the tail
        mutated = original[:drop] + original[drop + 1 :]
    write_lines(journal, mutated)
    assert not verify(journal.path).ok
