"""Where the « cerveau » plugin keeps its brain, and one read of it (plan step B2, ADR-072).

The format is the plugin's (``brainkit/store.py``, ``brainkit/wikistore.py``), learnt from its code
and never imported. The brain is opened for reading only: nothing is written, copied or kept, so a
memory forgotten in the plugin is gone for the platform at the next read (section 11, ``/oublier``).

- Classic brain: ``graph.json`` is the brain. An older graph loads as it is: a missing field takes
  its deduced value later, an unknown field is ignored.
- Wiki brain: the Markdown pages are the truth and ``graph.json`` only their cache, rebuilt by the
  plugin when a page changes. The platform never parses the pages: it reads the cache only when
  the wiki has not moved since (the plugin's own signature of the pages: path, date, size). A page
  edited or deleted since, or a wiki out of reach, gives no memory until the plugin reads it again.
- A missing, unreadable, oversized or malformed brain gives no memory and a reason, never a crash.
  Reasons never hold a path: they may reach a model's prompt (ADR-071).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

GRAPH_FILE = "graph.json"
CONFIG_FILE = "config.json"
WIKI_MARKER = ".cerveau-wiki"
WIKI_TOPS = ("wiki", "archive")
MAX_GRAPH_BYTES = 64 * 1024 * 1024
MAX_CONFIG_BYTES = 1024 * 1024
READ_ATTEMPTS = 4
# A git conflict copy next to a page (brainkit/wikistore.py, CONFLICT_COPY): not a page.
_CONFLICT_COPY = re.compile(
    r" \(conflit [^()\n/]{1,40} \d{4}-\d{2}-\d{2} \d{2}h\d{2}(?: \d{1,3})?\)(?:\.[^./\s]{1,10})?$"
)

Mode = Literal["classique", "wiki", "absent"]


def brain_home(configured: str | None, env: Mapping[str, str]) -> Path:
    """``memory.yaml › brain_home``, else ``BRAIN_HOME``, else the plugin's default folder.

    The plugin's default is ``brain`` under Claude Code's folder: ``CLAUDE_CONFIG_DIR`` when set,
    else ``~/.claude`` (``brainkit/common.py``).
    """
    if configured:
        return Path(configured).expanduser()
    if env.get("BRAIN_HOME"):
        return Path(env["BRAIN_HOME"]).expanduser()
    claude = env.get("CLAUDE_CONFIG_DIR")
    return (Path(claude).expanduser() if claude else Path.home() / ".claude") / "brain"


@dataclass(frozen=True)
class BrainRead:
    """One read: the stored nodes (id → node) or the reason there are none."""

    mode: Mode
    nodes: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    reason: str | None = None


class _Unreadable(Exception):
    """The file cannot be used; the message is the reason, without a path."""


def _read_bytes(path: Path, limit: int) -> bytes:
    """The file's bytes, opened read only; a short retry while Windows swaps it (plugin's save)."""
    attempt = 0
    while True:
        try:
            with path.open("rb") as handle:
                raw = handle.read(limit + 1)
            break
        except PermissionError:
            attempt += 1
            if attempt == READ_ATTEMPTS:
                raise _Unreadable(f"{path.name} inaccessible (accès refusé)") from None
            time.sleep(0.05 * attempt)
        except OSError as exc:
            raise _Unreadable(f"{path.name} illisible ({type(exc).__name__})") from None
    if len(raw) > limit:
        raise _Unreadable(f"{path.name} trop gros (plus de {limit // (1024 * 1024)} Mo)")
    return raw


def _json(path: Path, limit: int) -> Any:
    raw = _read_bytes(path, limit)
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise _Unreadable(f"{path.name} illisible (JSON invalide)") from None


def _configured_wiki(home: Path, env: Mapping[str, str]) -> Path | None:
    """The wiki the plugin is set to (``config.json › wiki.path``, else ``BRAIN_WIKI``).

    An unreadable ``config.json`` counts as empty, as the plugin reads it (defaults everywhere).
    """
    path: object = None
    config_file = home / CONFIG_FILE
    if config_file.is_file():
        try:
            config = _json(config_file, MAX_CONFIG_BYTES)
        except _Unreadable:
            config = None
        wiki = config.get("wiki") if isinstance(config, dict) else None
        path = wiki.get("path") if isinstance(wiki, dict) else None
    if not path:
        path = env.get("BRAIN_WIKI")
    return Path(os.path.expanduser(str(path))) if path else None


def _scan(root: Path) -> dict[str, tuple[int, int]]:
    """The wiki's pages as the plugin lists them (``wikistore.scan``): relative path → (date, size).

    Folders and files starting with « . » or « _ » and git conflict copies are skipped; links are
    not followed.
    """
    out: dict[str, tuple[int, int]] = {}
    for top in WIKI_TOPS:
        stack = [(os.path.join(str(root), top), top)]
        while stack:
            directory, rel = stack.pop()
            try:
                entries = os.scandir(directory)
            except OSError:
                continue
            with entries:
                for entry in entries:
                    if entry.name[:1] in "._" or _CONFLICT_COPY.search(entry.name):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append((entry.path, f"{rel}/{entry.name}"))
                        elif entry.name.lower().endswith(".md"):
                            stat = entry.stat(follow_symlinks=False)
                            out[f"{rel}/{entry.name}"] = (stat.st_mtime_ns, stat.st_size)
                    except OSError:
                        continue
    return out


def wiki_signature(root: Path) -> str:
    """The plugin's signature of the wiki's pages (``wikistore.signature``)."""
    digest = hashlib.sha1(usedforsecurity=False)  # the plugin's choice: a change detector
    for rel, (mtime, size) in sorted(_scan(root).items()):
        digest.update(f"{rel}\t{mtime}\t{size}\n".encode())
    return digest.hexdigest()


def _wiki_check(data: Mapping[str, Any], root: Path) -> str | None:
    """Why the wiki's cache cannot be read as it is; ``None`` when it matches the pages."""
    if not (root / WIKI_MARKER).is_file():
        return "wiki du cerveau introuvable : aucun souvenir lu (le cache peut être périmé)"
    wiki = data.get("wiki")
    resolved = str(root.resolve())
    if not isinstance(wiki, dict) or wiki.get("root") != resolved:
        return "cache du wiki absent : le plugin le refait à sa prochaine lecture"
    if wiki.get("sig") != wiki_signature(root):
        return (
            "le wiki a changé depuis la dernière lecture du plugin : aucun souvenir lu tant "
            "qu'une session Claude Code ne l'a pas relu"
        )
    return None


def read_brain(home: Path, env: Mapping[str, str]) -> BrainRead:
    """Read the brain under ``home`` once, read only. Never raises for a bad brain."""
    graph = home / GRAPH_FILE
    if not graph.is_file():
        return BrainRead("absent", reason="cerveau du plugin introuvable (pas de graph.json)")
    try:
        data = _json(graph, MAX_GRAPH_BYTES)
    except _Unreadable as exc:
        return BrainRead("absent", reason=str(exc))
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), dict):
        return BrainRead("absent", reason="graph.json n'a pas la forme d'un cerveau")
    root = _configured_wiki(home, env)
    cached = data.get("wiki")
    if root is None and isinstance(cached, dict) and cached.get("root"):
        found = Path(str(cached["root"]))
        # A cache whose wiki is gone and that no setting names: the plugin reads it as a classic
        # brain (« wiki débranché »), and so does the platform.
        root = found if (found / WIKI_MARKER).is_file() else None
    if root is not None:
        reason = _wiki_check(data, root)
        if reason is not None:
            return BrainRead("wiki", reason=reason)
        return BrainRead("wiki", MappingProxyType(data["nodes"]))
    return BrainRead("classique", MappingProxyType(data["nodes"]))
