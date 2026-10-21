"""Live activation needs every manual step (plan of phase 5, §7 and §17).

Two proofs. The 2⁶ combinations of the six conditions, each set up for real under ``tmp_path``:
one, all true, reaches the broker once; in the 63 others the broker is never called and the
refusal names exactly the conditions that fail. Then a static scan: no module of ``core/`` or
``interfaces/`` writes to ``config/live.yaml`` or to ``governance/approvals/``.
"""

from __future__ import annotations

import ast
import itertools
from pathlib import Path
from typing import Any

import pytest

from core.approvals.store import ApprovalStore, Trail
from core.execution.live import ActivationCheck, Condition, LiveAdapter, LiveDisabled
from core.governance.signatures import EffectiveAutonomy
from core.policy.engine import KILL_SWITCH_FILE
from tests.execution_cases import MemoryJournal, make_intent
from tests.test_execution_live import COMPLETE, NOW, REPO, RULES, Client, granted, project

COMBINATIONS = list(itertools.product((True, False), repeat=len(Condition)))


def _uncapped(autonomy: Any, root: Path, *, signed: Any = None) -> EffectiveAutonomy:
    """The written levels, as if no signature capped them: the level condition then holds or
    fails on its own, and the signature condition alone must still stop the order."""
    return EffectiveAutonomy(autonomy, (), ())


@pytest.mark.parametrize(
    "holds",
    COMBINATIONS,
    ids=["".join("1" if held else "0" for held in holds) for holds in COMBINATIONS],
)
def test_only_the_six_conditions_together_reach_the_broker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, holds: tuple[bool, ...]
) -> None:
    want = dict(zip(Condition, holds, strict=True))
    if not want[Condition.SIGNATURE]:
        # Without a signature the effective level is capped too: uncouple the two.
        monkeypatch.setattr("core.execution.live.effective_autonomy", _uncapped)
    root = project(
        tmp_path,
        live=COMPLETE if want[Condition.CONFIGURATION] else {**COMPLETE, "enabled": False},
        written="N3" if want[Condition.NIVEAU] else "N2",
        signed="N3" if want[Condition.SIGNATURE] else None,
    )
    if not want[Condition.KILL_SWITCH]:
        (root / KILL_SWITCH_FILE).parent.mkdir(parents=True, exist_ok=True)
        (root / KILL_SWITCH_FILE).write_text("test\n", encoding="utf-8")
    intent = make_intent(0)
    client = Client()
    with ApprovalStore.memory(RULES, Trail(MemoryJournal(), "live-64")) as store:
        if want[Condition.APPROBATION]:
            granted(store, intent)
        owned = want[Condition.ACL]
        check = ActivationCheck(root, store, owner=lambda _path: owned)
        live = LiveAdapter(client, store, check, call_timeout_s=5, kill_target_s=10)
        failing = {condition for condition, held in want.items() if not held}
        if failing:
            with pytest.raises(LiveDisabled, match="aucun appel au courtier") as caught:
                live.submit(intent, now=NOW)
            assert set(caught.value.conditions) == failing
            assert client.calls == []
        else:
            assert live.submit(intent, now=NOW).accepted
            assert client.calls == ["submit"]


def test_the_combinations_are_all_there() -> None:
    assert len(set(COMBINATIONS)) == 2 ** len(Condition) == 64


# Static scan ----------------------------------------------------------------------------------

PROTECTED_TEXT = ("live.yaml", "approvals")  # in a string literal of the written path
PROTECTED_NAMES = frozenset({"LIVE_FILE", "SIGNATURES_DIR"})
WRITING_METHODS = frozenset(
    {
        "write_text",
        "write_bytes",
        "touch",
        "mkdir",
        "unlink",
        "rmdir",
        "rename",
        "symlink_to",
        "hardlink_to",
        "chmod",
    }
)
WRITING_FUNCTIONS = frozenset(
    {
        ("os", "replace"),
        ("os", "rename"),
        ("os", "remove"),
        ("os", "unlink"),
        ("os", "chmod"),
        ("os", "makedirs"),
    }
)


def _names_protected(node: ast.AST, tainted: set[str]) -> bool:
    for part in ast.walk(node):
        if (
            isinstance(part, ast.Constant)
            and isinstance(part.value, str)
            and any(text in part.value for text in PROTECTED_TEXT)
        ):
            return True
        if isinstance(part, ast.Name) and (part.id in PROTECTED_NAMES or part.id in tainted):
            return True
        if isinstance(part, ast.Attribute) and part.attr in PROTECTED_NAMES:
            return True
    return False


def _writes(call: ast.Call) -> list[ast.AST]:
    """The paths this call writes to, if it is a write primitive."""
    func = call.func
    if isinstance(func, ast.Name) and func.id == "open":
        mode = call.args[1] if len(call.args) > 1 else None
        for keyword in call.keywords:
            if keyword.arg == "mode":
                mode = keyword.value
        if isinstance(mode, ast.Constant) and set(str(mode.value)) & set("wax+"):
            return call.args[:1]
        return []
    if not isinstance(func, ast.Attribute):
        return []
    owner = func.value.id if isinstance(func.value, ast.Name) else None
    if owner == "shutil":
        return list(call.args)  # copy, move, rmtree: any path they touch
    if (owner, func.attr) in WRITING_FUNCTIONS:
        return list(call.args)
    if func.attr in WRITING_METHODS:
        return [func.value, *call.args]
    if func.attr == "replace" and len(call.args) == 1:  # Path.replace, not str.replace
        return [func.value, *call.args]
    if func.attr == "open":
        mode = call.args[0] if call.args else None
        for keyword in call.keywords:
            if keyword.arg == "mode":
                mode = keyword.value
        if isinstance(mode, ast.Constant) and set(str(mode.value)) & set("wax+"):
            return [func.value]
    return []


def protected_writes(source: str) -> list[tuple[int, str]]:
    """The lines that write to a protected path, each with the function it is in. A name ever
    assigned from a protected path is protected everywhere in the module: wider than Python's
    scopes, never narrower."""
    tree = ast.parse(source)
    assigns = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
    tainted: set[str] = set()
    while True:
        more = {
            target.id
            for node in assigns
            if _names_protected(node.value, tainted)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        if more <= tainted:
            break
        tainted |= more
    where: dict[ast.AST, str] = {}
    for node in ast.walk(tree):  # breadth first: an inner function overwrites its outer one
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            where.update(dict.fromkeys(ast.walk(node), node.name))
    return sorted(
        (node.lineno, where.get(node, "<module>"))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and any(_names_protected(target, tainted) for target in _writes(node))
    )


@pytest.mark.parametrize(
    "source",
    [
        "Path('config/live.yaml').write_text('enabled: true')",
        "open(root / 'config' / 'live.yaml', 'w')",
        "open(root / LIVE_FILE, mode='a')",
        "(root / SIGNATURES_DIR / 'x.md').write_bytes(b'')",
        "path = root / SIGNATURES_DIR\npath.joinpath('x.md').touch()",
        "shutil.copy(source, root / 'governance' / 'approvals')",
        "os.replace(tmp, root / LIVE_FILE)",
        "(root / LIVE_FILE).open('w')",
        "target = root / 'var' / 'approvals'\ntarget.replace(other)",
    ],
)
def test_the_scan_sees_a_write_to_a_protected_path(source: str) -> None:
    assert protected_writes(source)


@pytest.mark.parametrize(
    "source",
    [
        "Path('config/live.yaml').read_text()",
        "open(root / LIVE_FILE)",
        "(root / 'var' / 'audit.jsonl').write_text('x')",
        "label = 'approvals'.replace('a', 'b')",
    ],
)
def test_the_scan_lets_a_read_or_another_path_through(source: str) -> None:
    assert not protected_writes(source)


# The one writer allowed: an eval case signs its level in the TemporaryDirectory that run_paper
# gives it as home, never under the project root. Listed here, it is also proof the scan sees it.
EXEMPT = {("core/evals/paper.py", "_sign")}


def test_no_module_writes_to_the_live_file_or_the_signatures() -> None:
    modules = sorted((REPO / "core").rglob("*.py")) + sorted((REPO / "interfaces").rglob("*.py"))
    assert len(modules) > 50
    found = {
        (module.relative_to(REPO).as_posix(), function)
        for module in modules
        for _, function in protected_writes(module.read_text(encoding="utf-8"))
    }
    assert found == EXEMPT
