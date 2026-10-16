"""Génère l'index BRAIN.md (injecté au démarrage de chaque session), la fiche du projet courant
et l'export lisible MEMOIRES.md. Tout est borné en taille : le cerveau doit faire économiser des tokens."""
from __future__ import annotations

import datetime as _dt
import re

from . import journal
from .common import (CMD, EXPORT_FILE, GRAPH_FILE, INDEX_FILE, JOURNAL_FILE, PROJECTS_DIR, fmt_date,
                     load_config, now_iso, short, write_text)
from .store import TYPES, priority

ID_RE = re.compile(r"`([a-z0-9][a-z0-9\-]*)`")
SECTION_SHARES = (0.08, 0.20, 0.26, 0.22, 0.14, 0.05, 0.05)


def _fit(lines, budget):
    out, used = [], 0
    for line in lines:
        if used + len(line) + 1 > budget:
            break
        out.append(line)
        used += len(line) + 1
    return out


def project_line(brain, p, seen) -> str:
    meta = p.get("meta") or {}
    has_map = (PROJECTS_DIR / p["id"] / "MAP.md").exists()
    n_mem = len(brain.project_members(p["id"]))
    bits = [f"`{meta.get('path', '?')}`", "carte ✓" if has_map else "sans carte"]
    if n_mem:
        bits.append(f"{n_mem} souvenir{'s' if n_mem > 1 else ''}")
    if seen.get(p["id"]):
        bits.append(f"vu le {fmt_date(seen[p['id']])}")
    desc = short(p.get("body", ""), 120)
    return f"- **{p['title']}** (`{p['id']}`)" + (f" — {desc}" if desc else "") + " · " + " · ".join(bits)


def _relevance(brain, focus):
    """Lien de chaque souvenir avec le projet courant : liens écrits, liens déduits, concepts partagés."""
    try:
        from . import graph
        an = graph.ensure(brain)
    except Exception:
        return {}
    members = {n["id"] for n in brain.project_members(focus)} | {focus}
    rel = {}

    def bump(i, v):
        rel[i] = rel.get(i, 0) + v

    for e in brain.edges:
        if e["from"] in members and e["to"] not in members:
            bump(e["to"], 15)
        elif e["to"] in members and e["from"] not in members:
            bump(e["from"], 15)
    for e in an.get("inferred", []):
        if e["s"] in members and e["t"] not in members:
            bump(e["t"], 30 * e["w"])
        elif e["t"] in members and e["s"] not in members:
            bump(e["s"], 30 * e["w"])
    for c in an.get("concepts", []):
        mem = set(c["members"])
        if mem & members:
            for i in mem - members:
                bump(i, 4)
    return rel


def build_index(brain, cfg=None, focus=None) -> str:
    """Index injecté au démarrage. Avec un projet courant (focus), le savoir global lié à ce projet passe devant
    et le reste recule : moins de tokens, plus de pertinence."""
    from . import dates
    cfg = cfg or load_config()
    # dans un projet, la fiche du projet porte déjà l'essentiel : l'index global se resserre sur ce qui s'y rapporte
    budget = cfg["inject"].get("index_chars_project", 3000) if focus else cfg["inject"]["index_chars"]
    act = list(brain.active())
    seen = journal.last_seen_by_project()
    rel = _relevance(brain, focus) if focus else {}

    def score(n):
        s = priority(n)
        if focus and n["type"] not in ("user", "feedback"):  # profil et règles valent partout : ordre d'importance
            r = rel.get(n["id"], 0)
            s += min(r, 30)
            if not r and n["type"] in ("decision", "fact", "learning", "reference", "entity", "todo"):
                s -= 12
        return s

    def nodes_of(pred):
        return sorted((n for n in act if pred(n)), key=lambda n: -score(n))

    def line(n, chars):
        body = short(n.get("body", ""), chars)
        return f"- **{n['title']}**" + (f" — {body}" if body else "") + f" `{n['id']}`"

    ahead = cfg.get("due", {}).get("days_ahead", 7)
    dues = []
    for n in act:
        d = dates.due_of(n)
        k = dates.days_until(d) if d else None
        if k is not None and k <= ahead and n["type"] == "todo":
            dues.append((k, n, d))
    dues.sort(key=lambda x: x[0])
    projects = sorted(nodes_of(lambda n: n["type"] == "project" and n["id"] != focus), key=lambda p: seen.get(p["id"], ""),
                      reverse=True)
    sections = [
        ("⏰ Échéances", [f"- **{n['title']}** — {dates.human(d)} `{n['id']}`" for _, n, d in dues][:6]),
        ("👤 Profil", [line(n, 200) for n in nodes_of(lambda n: n["type"] == "user")][:8]),
        ("📏 Règles & préférences", [line(n, 200) for n in nodes_of(lambda n: n["type"] == "feedback")][:12]),
        ("📂 Projets" if not focus else "📂 Autres projets", [project_line(brain, p, seen) for p in projects][:12]),
        ("💡 Savoir global (décisions, faits, apprentissages)",
         [line(n, 160) for n in nodes_of(lambda n: n["type"] in ("decision", "fact", "learning") and not n.get("project"))][:10]),
        ("🔗 Références & entités",
         [line(n, 120) for n in nodes_of(lambda n: n["type"] in ("reference", "entity") and not n.get("project"))][:6]),
        ("☑️ À faire", [line(n, 110) for n in nodes_of(lambda n: n["type"] == "todo" and not n.get("project"))][:6]),
    ]
    header = f"# 🧠 Cerveau — mémoire persistante (index du {fmt_date(now_iso())})"
    footer = f"_{len(act)} souvenirs · {len(brain.edges)} liens — `show <id>` pour le détail._"
    lines = [header]
    avail = max(800, budget - len(header) - len(footer) - 4)
    carry = 0
    for (title, items), share in zip(sections, SECTION_SHARES):
        allowance = int(avail * share) + carry
        if not items:
            carry = allowance
            continue
        block = _fit([f"\n## {title}"] + items, allowance)
        used = sum(len(x) + 1 for x in block) if len(block) > 1 else 0
        if len(block) > 1:
            lines += block
            hidden = len(items) - (len(block) - 1)
            if hidden > 0:
                lines.append(f"- … +{hidden} (`q` ou `ls`)")
                used += 20
        carry = max(0, allowance - used)
    lines.append("\n" + footer)
    return "\n".join(lines)


def rebuild(brain, cfg=None) -> str:
    text = build_index(brain, cfg)
    write_text(INDEX_FILE, text)
    return text


def ensure_index(brain, cfg=None) -> str:
    """Régénère BRAIN.md si le graphe ou le journal ont bougé depuis."""
    try:
        stale = (not INDEX_FILE.exists()) or any(
            f.exists() and f.stat().st_mtime > INDEX_FILE.stat().st_mtime for f in (GRAPH_FILE, JOURNAL_FILE)) \
            or _dt.date.fromtimestamp(INDEX_FILE.stat().st_mtime) != _dt.date.today()  # échéances : « dans 3 j » change chaque jour
    except OSError:
        stale = True
    if stale:
        return rebuild(brain, cfg)
    return INDEX_FILE.read_text(encoding="utf-8")


def project_card(brain, p, cfg=None, exclude_session=None):
    """Fiche du projet courant, remplie ligne à ligne dans le budget (jamais coupée au milieu d'une ligne)."""
    cfg = cfg or load_config()
    budget = cfg["inject"]["project_chars"]
    meta = p.get("meta") or {}
    head = [f"## 📂 Projet courant : {p['title']} (`{p['id']}`) — `{meta.get('path', '?')}`"]
    if p.get("body"):
        head.append(short(p["body"], 450))
    digest_file = PROJECTS_DIR / p["id"] / "DIGEST.md"
    try:
        digest = digest_file.read_text(encoding="utf-8").strip() if digest_file.exists() else ""
    except OSError:
        digest = ""
    if not digest:
        digest = ("_Pas encore de carte de ce dossier : elle se génère en arrière-plan s'il contient du code ou des "
                  "documents (`brain map .` pour la forcer)._")
    mems = sorted(brain.project_members(p["id"]), key=lambda n: -priority(n))
    mem_lines = [f"- [{TYPES.get(n['type'], n['type'])}] **{n['title']}** — {short(n.get('body', ''), 120)} `{n['id']}`"
                 for n in mems[:10]]
    sessions = journal.recent(project=p["id"], limit=3, exclude=exclude_session)
    sess_lines = [journal.session_line(s) for s in sessions]
    cont = (f"↪ Fin de la dernière session : « {short(sessions[0]['answer'], 230)} »"
            if sessions and sessions[0].get("answer") else "")  # reprendre où on en était : place réservée
    rest = budget - sum(len(x) + 1 for x in head) - len(digest) - 2 - (len(cont) + 1 if cont else 0)
    out = list(head)
    if mem_lines:
        block = _fit(["**Souvenirs du projet :**"] + mem_lines, max(300, int(rest * 0.62)))
        hidden = len(mems) - (len(block) - 1)
        if hidden > 0:
            block.append(f"- … +{hidden} autres (`brain ls -p {p['id']}`)")
        out += block
        rest -= sum(len(x) + 1 for x in block)
    if sess_lines and rest > 200:
        block = _fit(["**Dernières sessions ici :**"] + sess_lines, rest)
        out += block
        rest -= sum(len(x) + 1 for x in block)
    if cont:
        out.append(cont)
    out.append(digest)
    return "\n".join(out)


def session_context(brain, cwd, cfg=None, session_id=None):
    """Ce qui est injecté au démarrage : index global + fiche du projet courant. → (texte, ids, projet)"""
    cfg = cfg or load_config()
    proj = brain.project_for_path(cwd) if cwd else None
    parts = [build_index(brain, cfg, focus=proj["id"]) if proj else ensure_index(brain, cfg)]
    if proj:
        parts.append(project_card(brain, proj, cfg, exclude_session=session_id))
    text = "\n\n".join(parts)
    limit = cfg["inject"]["max_chars"]
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    ids = sorted({i for i in ID_RE.findall(text) if i in brain.nodes})
    return text, ids, proj


def export(brain) -> str:
    """MEMOIRES.md : vue complète et lisible de tout le cerveau (pour l'utilisateur)."""
    lines = [f"# 🧠 Mémoires — export complet ({fmt_date(now_iso())})", "",
             "_Généré automatiquement. Pour modifier : `brain edit <id>` (ou demander à Claude)._", ""]
    projects = {p["id"]: p for p in brain.nodes.values() if p["type"] == "project"}
    for t in TYPES:
        nodes = sorted((n for n in brain.nodes.values() if n["type"] == t),
                       key=lambda n: (n.get("status", "active") != "active", -priority(n)))
        if not nodes:
            continue
        lines += [f"## {TYPES[t]} ({len(nodes)})", ""]
        for n in nodes:
            flag = " _(archivé)_" if n.get("status", "active") != "active" else ""
            lines.append(f"### {n['title']}{flag}")
            meta = [f"`{n['id']}`", f"importance {n.get('importance', 3)}", f"maj {fmt_date(n.get('updated'))}"]
            if n.get("hits"):
                meta.append(f"rappelé {n['hits']}×")
            if n.get("project") in projects:
                meta.append(f"projet : {projects[n['project']]['title']}")
            if n.get("tags"):
                meta.append("tags : " + ", ".join(n["tags"]))
            if t == "project":
                meta.append(f"chemin : `{(n.get('meta') or {}).get('path', '?')}`")
            lines.append(" · ".join(meta))
            if n.get("body"):
                lines += ["", n["body"]]
            links = [f"{d} {rel} `{m['id']}`" for m, rel, d in brain.neighbors(n["id"])]
            if links:
                lines += ["", "Liens : " + " · ".join(links)]
            lines.append("")
    text = "\n".join(lines)
    write_text(EXPORT_FILE, text)
    return text
