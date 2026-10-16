"""Synchronise la mémoire automatique native de Claude Code (~/.claude/projects/*/memory/*.md) dans le cerveau,
pour que tout ce qui a été mémorisé dans un projet soit aussi trouvable depuis n'importe où."""
from __future__ import annotations

import hashlib
import json
import re

from .common import CLAUDE_HOME, STATE_DIR, is_scratch, read_json, write_json
from .store import Brain, normalize_type

STATE_FILE = STATE_DIR / "automem.json"
# Types de la mémoire native → types du cerveau (« project » natif = fait sur un travail en cours, pas un dossier).
NATIVE_TYPES = {"project": "fact", "user": "user", "feedback": "feedback", "reference": "reference"}
FRONT = re.compile(r"^﻿?---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)$", re.S)
INDEX_LINE = re.compile(r"^\s*-\s*\[([^\]]+)\]\(([^)]+\.md)\)")


def mini_yaml(text) -> dict:
    """Sous-ensemble YAML suffisant pour les en-têtes de mémoire (clés, sous-blocs indentés)."""
    root = {}
    stack = [(-1, root)]
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        indent = len(line) - len(line.lstrip())
        key, _, val = line.strip().partition(":")
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        val = val.strip()
        if not val:
            child = {}
            parent[key.strip()] = child
            stack.append((indent, child))
        else:
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            parent[key.strip()] = val
    return root


def parse_memory_file(text):
    m = FRONT.match(text)
    if not m:
        return {}, text.strip()
    return mini_yaml(m.group(1)), m.group(2).strip()


def _cwd_for(project_dir):
    for path in sorted(project_dir.glob("*.jsonl")):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    if i > 300:
                        break
                    if '"cwd"' not in line:
                        continue
                    try:
                        cwd = json.loads(line).get("cwd")
                    except Exception:
                        continue
                    if cwd:
                        return cwd
        except OSError:
            continue
    return None


def _signature(files) -> str:
    parts = []
    for f in sorted(files):
        st = f.stat()
        parts.append(f"{f.name}:{int(st.st_mtime)}:{st.st_size}")
    return ";".join(parts)


def sync(force=False, dry=False) -> list:
    root = CLAUDE_HOME / "projects"
    if not root.is_dir():
        return []
    state = read_json(STATE_FILE, {}) or {}
    todo = []
    for memdir in sorted(root.glob("*/memory")):
        files = [f for f in memdir.glob("*.md") if f.name.lower() != "memory.md"]
        if not files:
            continue
        sig = _signature(files)
        key = memdir.parent.name
        if not force and state.get(key) == sig:
            continue
        titles = {}
        index_md = memdir / "MEMORY.md"
        if index_md.exists():
            for line in index_md.read_text(encoding="utf-8", errors="replace").splitlines():
                m = INDEX_LINE.match(line)
                if m:
                    titles[m.group(2).strip()] = m.group(1).strip()
        todo.append((key, sig, _cwd_for(memdir.parent), files, titles))
    if dry or not todo:
        return [("à importer", key, len(files)) for key, _, _, files, _ in todo]
    report = []
    with Brain.edit() as b:
        by_origin = {(n.get("meta") or {}).get("origin"): n for n in b.nodes.values()
                     if (n.get("meta") or {}).get("origin")}
        touched = []
        for key, sig, cwd, files, titles in todo:
            proj = None
            if cwd and not is_scratch(cwd):
                proj, _ = b.ensure_project(cwd, source="import")
            for f in files:
                try:
                    meta, body = parse_memory_file(f.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
                md = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
                name = meta.get("name") or f.stem
                desc = meta.get("description") or ""
                raw_type = str(md.get("type") or meta.get("type") or "reference").strip().lower()
                try:
                    ntype = normalize_type(NATIVE_TYPES.get(raw_type, raw_type))
                except ValueError:
                    ntype = "fact"
                title = titles.get(f.name) or desc or name
                if desc and desc != title:
                    body = f"{desc}\n\n{body}"
                digest = hashlib.sha1(body.encode("utf-8")).hexdigest()[:16]
                origin = str(f)
                pid = proj["id"] if proj and ntype not in ("user", "feedback") else None
                node = by_origin.get(origin)
                if node:
                    if (node.get("meta") or {}).get("hash") != digest or node["type"] != ntype or node.get("project") != pid:
                        b.update(node["id"], title=title, body=body, type=ntype, project=pid or "")
                        node.setdefault("meta", {})["hash"] = digest
                        report.append(("mis à jour", node["id"]))
                    touched.append(node["id"])
                    continue
                node = b.add(ntype, title, body, project=pid, source="import:auto-memory",
                             meta={"origin": origin, "hash": digest, "name": name}, nid=name)
                by_origin[origin] = node
                touched.append(node["id"])
                report.append(("nouveau", node["id"]))
            state[key] = sig
        for nid in touched:  # 2e passe : les [[liens]] vers des souvenirs importés juste après
            b.sync_wikilinks(nid)
    write_json(STATE_FILE, state)
    return report
