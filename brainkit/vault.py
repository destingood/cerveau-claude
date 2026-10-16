"""Coffre Markdown façon Obsidian / Basic Memory : une note par souvenir (propriétés YAML, liens [[wiki]]), une page
d'accueil, et la synchronisation dans les deux sens. Ce qui est modifié dans Obsidian revient dans le cerveau (fusion
champ par champ : chacun garde ses changements, le plus récent l'emporte s'ils touchent le même champ) ; une note
déposée dans « À trier » devient un souvenir ; une note supprimée archive son souvenir (réversible)."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from . import dates
from .common import BRAIN_DIR, fmt_date, now_iso, parse_iso, read_json, write_json, write_text
from .store import TYPES, Brain, clamp_importance, clean_tags, normalize_type, priority

MANIFEST = ".cerveau-coffre.json"
FOLDERS = {"user": "Profil", "feedback": "Règles", "project": "Projets", "decision": "Décisions", "fact": "Faits",
           "learning": "Apprentissages", "reference": "Ressources", "entity": "Entités", "todo": "À faire"}
INBOX = "À trier"
HOME = "Accueil.md"
MARK = "<!-- cerveau : section générée — pour relier deux notes, écrire [[Titre]] dans le texte au-dessus -->"
BAD = re.compile(r'[<>:"/\\|?*#^\[\]\x00-\x1f]+')
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}
LINK = re.compile(r"\[\[([^\]\n|#]{1,120})(#[^\]\n|]*)?(?:\|([^\]\n]{1,120}))?\]\]")
REL = {"relates": ("lié à", "lié à"), "part_of": ("fait partie de", "contient"), "depends_on": ("dépend de", "requis par"),
       "uses": ("utilise", "utilisé par"), "fixes": ("corrige", "corrigé par"), "supersedes": ("remplace", "remplacé par"),
       "contradicts": ("contredit", "contredit par"), "about": ("à propos de", "sujet de")}
FIELDS = ("title", "type", "project", "importance", "tags", "due")
FR = {"title": "titre", "body": "contenu", "project": "projet", "meta": "échéance"}
CONFLICTS = "Conflits"
SKIP_DIRS = {".obsidian", ".trash", ".git", INBOX, CONFLICTS}


def _sha(data) -> str:
    return hashlib.sha1(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()[:16]


def fname(title) -> str:
    """Titre → nom de fichier sûr (Windows, Obsidian : pas de : / \\ | ? * # ^ [ ])."""
    name = " ".join(BAD.sub(" ", str(title)).split()).strip(" .")[:90].strip(" .") or "sans titre"
    return name + "_" if name.split(".")[0].upper() in RESERVED else name


# ------------------------------------------------------------------------------------ YAML minimal
def _yaml(value) -> str:
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(json.dumps(str(v), ensure_ascii=False) for v in value) + "]"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _scalar(raw):
    raw = raw.strip()
    if not raw:
        return ""
    try:
        return json.loads(raw)
    except ValueError:
        pass
    if raw[0] == "[" and raw[-1] == "]":
        return [_scalar(x) for x in raw[1:-1].split(",") if x.strip()]
    if len(raw) > 1 and raw[0] == raw[-1] == "'":
        return raw[1:-1].replace("''", "'")
    return raw


def parse_note(text) -> dict:
    """Note Markdown → {meta, title, body} (propriétés en ligne ou en liste à tirets, comme les écrit Obsidian)."""
    text = text.replace("\r\n", "\n").lstrip("﻿")
    meta = {}
    if text.startswith("---\n"):
        end = text.find("\n---", 3)
        if end != -1:
            key = None
            for line in text[4:end].split("\n"):
                item = re.match(r"^\s+-\s*(.*)$", line) or re.match(r"^-\s+(.*)$", line)
                if item and key and isinstance(meta.get(key), list):
                    meta[key].append(_scalar(item.group(1)))
                    continue
                k, sep, val = line.partition(":")
                if not sep or not k.strip() or k[0] in " #":
                    continue
                key = k.strip()
                meta[key] = _scalar(val) if val.strip() else []
            text = text[end + 4:]
            text = text[1:] if text.startswith("\n") else text
    body = text.lstrip("\n")
    title = ""
    m = re.match(r"#[ \t]+(.+)(?:\n|$)", body)
    if m:
        title = m.group(1).strip()
        body = body[m.end():]
    if MARK in body:
        body = body.split(MARK, 1)[0]
    return {"meta": meta, "title": title, "body": body.strip()}


# ------------------------------------------------------------------------------------ liens
def _links_out(body, names, brain):
    """[[id]] du cerveau → [[Nom de la note|texte]] (Obsidian relie par nom de fichier)."""
    def sub(m):
        target = brain.get(m.group(1))
        if not target or target["id"] not in names:
            return m.group(0)
        name, alias = names[target["id"]], m.group(3) or m.group(1)
        head = m.group(2) or ""
        return f"[[{name}{head}]]" if alias == name else f"[[{name}{head}|{alias}]]"
    return LINK.sub(sub, body)


def _links_in(body, stems, brain):
    """[[Nom de la note]] écrit dans Obsidian → [[id|texte]] (le cerveau relie par id)."""
    def sub(m):
        target_id = stems.get(m.group(1).strip().lower())
        if not target_id:
            node = brain.get(m.group(1))
            target_id = node["id"] if node else None
        if not target_id:
            return m.group(0)
        alias, head = m.group(3) or m.group(1), m.group(2) or ""
        return f"[[{target_id}{head}]]" if alias == target_id else f"[[{target_id}{head}|{alias}]]"
    return LINK.sub(sub, body)


def _project_ref(value, stems, brain):
    """Valeur de la propriété « project » ([[Projet]], id, nom) → id de projet, None (global) ou False (illisible)."""
    if isinstance(value, list):
        value = value[0] if value else ""
    v = str(value or "").strip()
    if not v or v.lower() in ("none", "aucun", "global", "-", "null"):
        return None
    m = LINK.fullmatch(v)
    ref = m.group(1).strip() if m else v
    pid = stems.get(ref.lower())
    node = brain.nodes.get(pid) if pid else brain.get(ref)
    return node["id"] if node and node["type"] == "project" else False


# ------------------------------------------------------------------------------------ rendu
def _fields(node):
    meta = node.get("meta") or {}
    return {"title": node["title"], "type": node["type"], "project": node.get("project"),
            "importance": node.get("importance", 3), "tags": list(node.get("tags") or []), "due": meta.get("due")}


def render(node, names, brain) -> tuple:
    """Une note par souvenir → (texte, corps exporté)."""
    meta = node.get("meta") or {}
    fm = {"brain_id": node["id"], "type": node["type"]}
    pid = node.get("project")
    if pid:
        fm["project"] = f"[[{names[pid]}]]" if pid in names else pid
    if node.get("tags"):
        fm["tags"] = list(node["tags"])
    fm["importance"] = node.get("importance", 3)
    if meta.get("due"):
        fm["due"] = meta["due"]
    if node["type"] == "project" and meta.get("path"):
        fm["path"] = meta["path"]
    fm["created"] = str(node.get("created") or "")[:10]
    fm["updated"] = str(node.get("updated") or "")[:10]
    if names[node["id"]] != node["title"]:
        fm["aliases"] = [node["title"]]
    body = _links_out(str(node.get("body") or "").strip(), names, brain)
    lines = ["---"] + [f"{k}: {_yaml(v)}" for k, v in fm.items()] + ["---", f"# {node['title']}", ""]
    if body:
        lines += [body, ""]
    links = []
    for m, rel, d in sorted(brain.neighbors(node["id"]), key=lambda x: (x[1], x[0]["title"])):
        label = REL.get(rel, (rel, rel))[0 if d == "→" else 1]
        target = f"[[{names[m['id']]}]]" if m["id"] in names else f"« {m['title']} » _(archivé)_"
        links.append(f"- {label} {target}")
    gen = ["## Liens", *links] if links else []
    if node["type"] == "project":
        members = sorted((n for n in brain.project_members(node["id"]) if n["id"] in names),
                         key=lambda n: (list(TYPES).index(n["type"]), -priority(n)))
        if members:
            gen += ([""] if gen else []) + [f"## Souvenirs du projet ({len(members)})"]
            gen += [f"- {TYPES[n['type']]} : [[{names[n['id']]}]]" for n in members]
    if gen:
        lines += [MARK, *gen, ""]
    return "\n".join(lines).rstrip("\n") + "\n", body


def _home(brain, nodes, names) -> str:
    by_type = {}
    for n in nodes:
        by_type.setdefault(n["type"], []).append(n)
    out = ["# 🧠 Cerveau — accueil", "",
           f"_Coffre généré par le cerveau le {fmt_date(now_iso())} · {len(nodes)} notes. Cette page est réécrite à "
           f"chaque export ; les autres notes se modifient librement : `brain export --vault` rapatrie les changements "
           f"(titre = ligne « # », propriétés type / project / tags / importance / due). Nouvelle note → dossier "
           f"« {INBOX} ». Supprimer une note archive son souvenir._", ""]
    sections = [("user", "👤 Profil"), ("feedback", "📏 Règles"), ("project", "📂 Projets"), ("todo", "☑️ À faire")]
    for t, label in sections:
        items = sorted(by_type.get(t, []), key=lambda n: -priority(n))
        if not items:
            continue
        out += [f"## {label}", ""]
        for n in items:
            extra = ""
            if t == "project":
                k = len([m for m in brain.project_members(n["id"]) if m["id"] in names])
                extra = f" — {k} souvenir{'s' if k > 1 else ''}"
            elif t == "todo":
                due = dates.due_of(n)
                extra = f" — échéance {fmt_date(due)}" if due else ""
            out.append(f"- [[{names[n['id']]}]]{extra}")
        out.append("")
    recent = sorted((n for n in nodes if n["type"] != "project"), key=lambda n: n.get("updated") or "", reverse=True)[:12]
    out += ["## 🕒 Modifiés récemment", ""] + [f"- [[{names[n['id']]}]] ({fmt_date(n.get('updated'))})" for n in recent]
    out += ["", "## 🗂️ Par type", ""]
    out += [f"- {FOLDERS[t]} : {len(by_type[t])}" for t in TYPES if by_type.get(t)]
    return "\n".join(out) + "\n"


def _assign_names(nodes, previous):
    """id → nom de fichier unique dans tout le coffre (insensible à la casse, comme Windows et Obsidian)."""
    names, taken = {}, set()
    for n in sorted(nodes, key=lambda n: (-priority(n), n["id"])):
        base = fname(n["title"])
        old = Path(previous.get(n["id"], {}).get("path", "")).stem
        cands = ([old] if old and (old == base or old.startswith(base + " (")) else []) + [
            base, f"{base} ({TYPES[n['type']]})", f"{base} ({n['id'][-8:]})"]
        name = next((c for c in cands if c.lower() not in taken), f"{base} ({n['id']})")
        names[n["id"]] = name
        taken.add(name.lower())
    return names


def _scan(root):
    """Notes gérées présentes dans le coffre : brain_id → chemin (même renommées ou déplacées)."""
    found = {}
    for p in root.rglob("*.md"):
        rel = p.relative_to(root)
        if rel.parts[0] in SKIP_DIRS or p.name == HOME:
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                head = fh.read(800)
        except OSError:
            continue
        m = re.search(r"^brain_id:\s*\"?([a-z0-9][a-z0-9\-]*)\"?\s*$", head, re.M)
        if m and m.group(1) not in found:
            found[m.group(1)] = p
    return found


# ------------------------------------------------------------------------------------ synchronisation
def _apply(brain, node, entry, note, path, stems, report):
    """Fusion à trois : valeur exportée / valeur actuelle du cerveau / valeur du fichier."""
    f0 = entry.get("f") or {}
    cur = _fields(node)
    file_newer = os.path.getmtime(path) >= (parse_iso(node.get("updated")).timestamp()
                                            if parse_iso(node.get("updated")) else 0)
    meta = note["meta"]
    stem = Path(path).stem
    new = {"title": note["title"] or (f0.get("title") if stem == Path(entry.get("path", "")).stem else stem)}
    try:
        new["type"] = normalize_type(meta["type"]) if meta.get("type") else f0.get("type")
    except ValueError:
        new["type"] = f0.get("type")
    proj = _project_ref(meta.get("project"), stems, brain) if "project" in meta else None
    new["project"] = f0.get("project") if proj is False else proj
    new["importance"] = clamp_importance(meta.get("importance", f0.get("importance", 3)))
    tags = meta.get("tags", [])
    new["tags"] = clean_tags([t.lstrip("#") for t in tags] if isinstance(tags, list) else str(tags))
    due = meta.get("due")
    new["due"] = (dates.parse(str(due)) or f0.get("due")) if due else None
    changes, conflicts = {}, []
    for key in FIELDS:
        if new[key] == f0.get(key):
            continue  # pas touché dans Obsidian
        if cur[key] != f0.get(key) and cur[key] != new[key] and not file_newer:
            conflicts.append(key)  # modifié des deux côtés, le cerveau est plus récent
            continue
        if new[key] != cur[key]:
            changes[key] = new[key]
    if _sha(note["body"]) != entry.get("body_h"):
        body = _links_in(note["body"], stems, brain)
        brain_changed = _sha(str(node.get("body") or "").strip()) != entry.get("b0")
        if brain_changed and not file_newer and body != str(node.get("body") or "").strip():
            conflicts.append("contenu")
        elif body != str(node.get("body") or "").strip():
            changes["body"] = body
    if changes:
        due_change = changes.pop("due", "∅")
        if due_change != "∅":
            m = dict(node.get("meta") or {})
            if due_change:
                m["due"] = due_change
            else:
                m.pop("due", None)
            changes["meta"] = m
        if "project" in changes and changes["project"] is None:
            node["project"] = None  # update() ignore None
        brain.update(node["id"], **changes)
        report["imported"].append((node["title"], sorted(FR.get(k, k) for k in changes)))
    if conflicts:
        report["conflicts"].append((node["title"], conflicts))
    return bool(changes)


def _inbox(brain, root, stems, report):
    box = root / INBOX
    if not box.is_dir():
        return
    for p in sorted(box.glob("*.md")):
        if p.name.startswith(("_", ".")):
            continue
        try:
            note = parse_note(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        meta = note["meta"]
        if meta.get("brain_id"):
            continue
        title = note["title"] or p.stem
        if not title.strip() or not (note["body"] or note["title"]):
            continue
        try:
            ntype = normalize_type(meta.get("type") or "fact")
        except ValueError:
            ntype = "fact"
        dup = brain.similar(title, note["body"], ntype, threshold=0.8)
        if dup:
            report["duplicates"].append((title, dup[0][1]["title"]))
            continue
        proj = _project_ref(meta.get("project"), stems, brain) if meta.get("project") else None
        tags = meta.get("tags") or []
        due = dates.parse(str(meta["due"])) if meta.get("due") else None
        node = brain.add(ntype, title, _links_in(note["body"], stems, brain),
                         tags=[t.lstrip("#") for t in tags] if isinstance(tags, list) else tags,
                         project=proj or None, importance=meta.get("importance", 3), source="obsidian",
                         meta={"due": due} if due else None)
        report["created"].append(node["title"])
        try:
            p.unlink()
        except OSError:
            pass


def sync(root, do_import=True) -> dict:
    """Coffre ⇄ cerveau. Renvoie le compte rendu (rapatrié, créé, archivé, conflits, écrit, retiré)."""
    root = Path(os.path.expanduser(str(root))).resolve()
    if root.exists() and not root.is_dir():
        raise RuntimeError(f"ce n'est pas un dossier : {root}")
    if root == BRAIN_DIR or BRAIN_DIR in root.parents:
        raise RuntimeError("le coffre doit être en dehors du dossier du cerveau")
    root.mkdir(parents=True, exist_ok=True)
    man = read_json(root / MANIFEST, {}) or {}
    if man.get("brain") and Path(man["brain"]) != BRAIN_DIR:
        raise RuntimeError(f"ce coffre appartient à un autre cerveau ({man['brain']})")
    previous = man.get("files") or {}
    report = {"root": str(root), "imported": [], "created": [], "archived": [], "conflicts": [], "duplicates": [],
              "written": 0, "removed": 0, "kept": [], "notes": 0}
    found = _scan(root)
    handled = set()
    if do_import and (previous or (root / INBOX).is_dir()):
        stems = {Path(e["path"]).stem.lower(): i for i, e in previous.items()}
        stems.update({p.stem.lower(): i for i, p in found.items()})
        missing = [i for i in previous if i not in found]
        mass = len(previous) >= 5 and len(missing) > 0.3 * len(previous)
        if mass:
            report["kept"].append(f"{len(missing)} notes absentes du coffre : rien archivé (coffre déplacé ou vidé ?)")
        changed = [i for i, e in previous.items() if i not in found or _sha(found[i].read_bytes()) != e.get("hash")]
        if changed or any((root / INBOX).glob("*.md")):
            from . import history
            history.snapshot("avant import du coffre", force=True)
        with Brain.edit() as brain:
            for nid, entry in previous.items():
                node = brain.nodes.get(nid)
                if node is None or node.get("status", "active") != "active":
                    handled.add(nid)
                    continue
                path = found.get(nid)
                if path is None:
                    if not mass:
                        brain.remove(nid)
                        report["archived"].append((node["title"], nid))
                    continue
                raw = path.read_bytes()
                if _sha(raw) == entry.get("hash"):
                    handled.add(nid)
                    continue
                before = len(report["conflicts"])
                _apply(brain, node, entry, parse_note(raw.decode("utf-8", "replace")), path, stems, report)
                if len(report["conflicts"]) > before:  # la version d'Obsidian est gardée à part : rien ne se perd
                    copy = root / CONFLICTS / f"{path.stem} ({now_iso()[:16].replace(':', 'h')}).md"
                    copy.parent.mkdir(exist_ok=True)
                    copy.write_bytes(raw)
                    report["kept"].append(f"version Obsidian en conflit gardée : {copy.relative_to(root)}")
                handled.add(nid)
            _inbox(brain, root, stems, report)
    else:
        handled = set(previous)
    # ---- export : le cerveau → le coffre
    brain = Brain.load()
    nodes = [n for n in brain.active() if n["type"] in FOLDERS]
    names = _assign_names(nodes, previous)
    files, written = {}, set()
    for n in nodes:
        rel = f"{FOLDERS[n['type']]}/{names[n['id']]}.md"
        text, body = render(n, names, brain)
        raw = text.encode("utf-8")
        p = root / rel
        if not p.exists() or p.read_bytes() != raw:
            write_text(p, text)
            report["written"] += 1
        written.add(os.path.normcase(str(p)))
        files[n["id"]] = {"path": rel, "hash": _sha(raw), "updated": n.get("updated"), "body_h": _sha(body.strip()),
                          "b0": _sha(str(n.get("body") or "").strip()), "f": _fields(n)}
    for nid, p in found.items():  # notes gérées qui n'ont plus lieu d'être (renommées, archivées…)
        if os.path.normcase(str(p)) in written or nid not in previous:
            continue
        if nid not in handled and _sha(p.read_bytes()) != previous[nid].get("hash"):
            report["kept"].append(f"{p.relative_to(root)} (modifiée, non rapatriée)")
            continue
        try:
            p.unlink()
            report["removed"] += 1
        except OSError:
            pass
    home = _home(brain, nodes, names)
    hp = root / HOME
    if not hp.exists() or hp.read_text(encoding="utf-8", errors="replace") != home:
        write_text(hp, home)
    (root / INBOX).mkdir(exist_ok=True)
    write_json(root / MANIFEST, {"version": 1, "brain": str(BRAIN_DIR), "exported": now_iso(), "files": files})
    report["notes"] = len(nodes)
    return report
