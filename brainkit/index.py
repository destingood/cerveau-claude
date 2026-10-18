"""Génère l'index BRAIN.md (injecté au démarrage de chaque session), la fiche du projet courant
et l'export lisible MEMOIRES.md. Tout est borné en taille : le cerveau doit faire économiser des tokens."""
from __future__ import annotations

import datetime as _dt
import re

from . import journal
from .common import (CMD, EXPORT_FILE, GRAPH_FILE, INDEX_FILE, JOURNAL_FILE, PROJECTS_DIR, budget_chars, fmt_date,
                     load_config, now_iso, short, write_text)
from .store import TYPES, priority

ID_RE = re.compile(r"`([a-z0-9][a-z0-9\-]*)`")
# Poids des sections (échéances, profil, règles, projets, savoir, références, à faire, wiki, commun). Partage max-min : une
# section qui demande moins que sa part la reçoit entière, les autres se partagent le reste au prorata. Profil et règles
# raccourcissent leurs corps pour tenir en entier ; dans un projet, la fiche du projet porte déjà l'essentiel.
WEIGHTS = (1.5, 2.5, 3.0, 2.5, 2.0, 0.6, 0.8, 0.9, 0.7)
WEIGHTS_FOCUS = (1.5, 2.5, 3.0, 0.0, 1.2, 0.4, 0.6, 0.6, 0.5)  # avant-dernière : savoir du wiki ; dernière : cerveau commun


def _allocate(needs, weights, total):
    """Partage max-min pondéré du budget `total` entre des sections qui demandent `needs` caractères."""
    alloc = [0] * len(needs)
    active = [i for i, n in enumerate(needs) if n > 0 and weights[i] > 0]
    while active:
        wsum = sum(weights[i] for i in active)
        fits = [i for i in active if needs[i] <= total * weights[i] / wsum]
        if not fits:
            for i in active:
                alloc[i] = int(total * weights[i] / wsum)
            break
        for i in fits:
            alloc[i] = needs[i]
            total -= needs[i]
        active = [i for i in active if i not in fits]
    return alloc
# Lignes du résumé de carte utiles au cartographe mais rarement à Claude : servies en dernier s'il reste de la place.
DIGEST_LAST = ("Entrées", "Scripts npm", "Copies identiques")


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
    desc = short(p.get("body", ""), 70)
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


def build_index(brain, cfg=None, focus=None, previews=None) -> str:
    """Index injecté au démarrage. Avec un projet courant (focus), le savoir global lié à ce projet passe devant
    et le reste recule : moins de tokens, plus de pertinence. Dans un projet, savoir global, références et à-faire
    hors projet ne sont donnés que par leur titre : leurs ids vont dans `previews` (rappelables à chaque message)."""
    from . import dates
    cfg = cfg or load_config()
    # dans un projet, la fiche du projet porte déjà l'essentiel : l'index global se resserre sur ce qui s'y rapporte
    budget = budget_chars(cfg["inject"], "index_tokens_project" if focus else "index_tokens")
    act = list(brain.active(own=True))
    friends = sorted((n for n in brain.active() if n["id"].startswith("c--")),  # cerveau commun : le plus récent d'abord
                     key=lambda n: n.get("updated") or "", reverse=True)
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
        body = short((n.get("meta") or {}).get("resume") or n.get("body", ""), chars)
        return f"- **{n['title']}**" + (f" — {body}" if body else "") + f" `{n['id']}`"

    def title_line(n):
        return f"- {n['title']} `{n['id']}`"

    def core(nodes, allowance, longest=200, shortest=110):
        """Profil et règles valent dans toutes les sessions : le corps se raccourcit pour qu'ils tiennent tous,
        plutôt que d'en cacher (avant : 2 profils sur 4 et 3 règles sur 4 visibles dans un projet)."""
        if not nodes:
            return []
        over = sum(len(n["title"]) + len(n["id"]) + 12 for n in nodes) / len(nodes)
        chars = int(max(shortest, min(longest, (allowance - 30) / len(nodes) - over)))
        return [line(n, chars) for n in nodes]

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
    if focus:  # dans un projet, les autres ne servent qu'à s'y retrouver : une ligne de noms suffit
        others = []
    else:
        others = [project_line(brain, p, seen) for p in projects][:12]
    def rest(pred, chars, cap):
        nodes = nodes_of(lambda n: pred(n) and not n.get("project"))[:cap]
        return lambda a: [title_line(n) if focus else line(n, chars) for n in nodes]

    sections = [
        ("⏰ Échéances", lambda a: [f"- **{n['title']}** — {dates.human(d)} `{n['id']}`" for _, n, d in dues][:6]),
        ("👤 Profil", lambda a: core(nodes_of(lambda n: n["type"] == "user")[:8], a)),
        ("📏 Règles & préférences", lambda a: core(nodes_of(lambda n: n["type"] == "feedback")[:12], a)),
        ("📂 Projets" if not focus else "📂 Autres projets", lambda a: others),
        ("💡 Savoir global (décisions, faits, apprentissages)" + (" — titres" if focus else ""),
         rest(lambda n: n["type"] in ("decision", "fact", "learning"), 130, 10)),
        ("🔗 Références & entités", rest(lambda n: n["type"] in ("reference", "entity"), 100, 6)),
        ("☑️ À faire", rest(lambda n: n["type"] == "todo", 100, 6)),
        ("📚 Wiki (sujets, concepts, analyses)" + (" — titres" if focus else ""),
         rest(lambda n: n["type"] in ("topic", "concept", "analysis"), 110, 8)),
        ("🤝 Cerveau commun — récent chez les amis (lecture seule)" + (" — titres" if focus else ""),
         lambda a: [(title_line(n) if focus else line(n, 100)).replace(f" `{n['id']}`", f" 🤝 {(n.get('meta') or {}).get('commun_par', '?')} `{n['id']}`")
                    for n in friends[:8]]),
    ]
    header = f"# 🧠 Cerveau — mémoire persistante (index du {fmt_date(now_iso())})"
    footer = f"_{len(act)} souvenirs · {len(brain.edges)} liens — `show <id>` pour le détail._"
    if focus and projects:
        footer = "_Autres projets : " + " · ".join(f"`{p['id']}`" for p in projects[:12]) + " — " + footer[1:]
    lines = [header]
    avail = max(800, budget - len(header) - len(footer) - 4)

    def put(title, items, allowance, preview=False):
        block = _fit([f"\n## {title}"] + items, allowance)
        if len(block) < 2:
            return 0
        lines.extend(block)
        used = sum(len(x) + 1 for x in block)
        if preview and previews is not None:
            previews.extend(ID_RE.findall("\n".join(block[1:])))
        hidden = len(items) - (len(block) - 1)
        if hidden > 0:
            lines.append(f"- … +{hidden} (`q` ou `ls`)")
            used += 20
        return used

    full = [make(10 ** 6) for _, make in sections]
    needs = [len(t) + 5 + sum(len(x) + 1 for x in items) if items else 0 for (t, _), items in zip(sections, full)]
    for i, ((title, make), allowance) in enumerate(zip(sections, _allocate(needs, WEIGHTS_FOCUS if focus else WEIGHTS,
                                                                            avail))):
        if allowance:  # savoir global, références et à-faire d'un index de projet : titres rappelables
            put(title, full[i] if needs[i] <= allowance else make(allowance), allowance, preview=bool(focus) and i > 3)
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
            f.exists() and f.stat().st_mtime > INDEX_FILE.stat().st_mtime
            for f in (GRAPH_FILE, JOURNAL_FILE, type(GRAPH_FILE)(__file__))) \
            or _dt.date.fromtimestamp(INDEX_FILE.stat().st_mtime) != _dt.date.today()  # échéances : « dans 3 j » change chaque jour
    except OSError:
        stale = True
    if stale:
        return rebuild(brain, cfg)
    return INDEX_FILE.read_text(encoding="utf-8")


def fit_digest(digest, budget):
    """Résumé de carte borné : lignes entières (240 car. max chacune), les moins utiles en dernier, renvoi au détail.
    Avant : ajouté en entier hors budget (≈ 850 tokens pour la boutique, relus à chaque requête)."""
    lines = [ln for ln in digest.splitlines() if ln.strip()]
    if sum(len(x) + 1 for x in lines) <= budget:
        return "\n".join(lines)
    lines = lines[:1] + [x for x in lines[1:] if not x.startswith(DIGEST_LAST)] + \
        [x for x in lines[1:] if x.startswith(DIGEST_LAST)]
    out, used = [], 0
    for ln in lines:
        ln = short(ln, 240)
        if used + len(ln) + 1 <= budget:
            out.append(ln)
            used += len(ln) + 1
    out.append("_Carte abrégée — détail : `brain files <mot>` · `explain <fichier>` · MAP.md du projet._")
    return "\n".join(out)


def project_card(brain, p, cfg=None, exclude_session=None, previews=None):
    """Fiche du projet courant, remplie ligne à ligne dans le budget (jamais coupée au milieu d'une ligne).
    Les souvenirs du projet n'y figurent que par leur titre : leurs ids vont dans `previews` (s'il est fourni) pour
    que le rappel à chaque message puisse encore apporter leur contenu quand la demande s'y rapporte."""
    cfg = cfg or load_config()
    budget = budget_chars(cfg["inject"], "project_tokens")
    meta = p.get("meta") or {}
    head = [f"## 📂 Projet courant : {p['title']} (`{p['id']}`) — `{meta.get('path', '?')}`"]
    if p.get("body"):
        head.append(short(p["body"], 320))
    digest_file = PROJECTS_DIR / p["id"] / "DIGEST.md"
    try:
        digest = digest_file.read_text(encoding="utf-8").strip() if digest_file.exists() else ""
    except OSError:
        digest = ""
    if not digest:
        digest = ("_Pas encore de carte de ce dossier : elle se génère en arrière-plan s'il contient du code ou des "
                  "documents (`brain map .` pour la forcer)._")
    digest = fit_digest(digest, budget_chars(cfg["inject"], "digest_tokens") or 10 ** 6)
    mems = sorted(brain.project_members(p["id"]), key=lambda n: -priority(n))
    mem_lines = [f"- [{TYPES.get(n['type'], n['type'])}] {n['title']} `{n['id']}`" for n in mems[:12]]
    sessions = journal.recent(project=p["id"], limit=3, exclude=exclude_session)
    sess_lines = [journal.session_line(s) for s in sessions]
    cont = (f"↪ Fin de la dernière session : « {short(sessions[0]['answer'], 230)} »"
            if sessions and sessions[0].get("answer") else "")  # reprendre où on en était : place réservée
    rest = budget - sum(len(x) + 1 for x in head) - len(digest) - 2 - (len(cont) + 1 if cont else 0)
    out = list(head)
    if mem_lines:
        block = _fit(["**Souvenirs du projet** (titres ; le contenu revient tout seul quand la demande s'y rapporte) :"]
                     + mem_lines, max(300, int(rest * 0.62)))
        if previews is not None:
            previews.extend(ID_RE.findall("\n".join(block[1:])))
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
    """Ce qui est injecté au démarrage : index global + fiche du projet courant. → (texte, ids, projet)
    `ids` = souvenirs déjà visibles en entier (le rappel ne les répète pas) ; les aperçus de la fiche en sont exclus."""
    cfg = cfg or load_config()
    proj = brain.project_for_path(cwd) if cwd else None
    previews = []
    parts = [build_index(brain, cfg, focus=proj["id"], previews=previews) if proj else ensure_index(brain, cfg)]
    if proj:
        parts.append(project_card(brain, proj, cfg, exclude_session=session_id, previews=previews))
    text = "\n\n".join(parts)
    limit = budget_chars(cfg["inject"], "max_tokens")
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    ids = sorted({i for i in ID_RE.findall(text) if i in brain.nodes} - set(previews))
    return text, ids, proj


def resume_delta(brain, since, cfg=None) -> str:
    """Reprise d'une session (--resume, réouverture) : son injection de départ est encore dans l'historique (vérifié
    sur 7 reprises sur 7). On n'ajoute que les souvenirs créés ou modifiés depuis ; rien s'il n'y en a pas.
    Avant : ~2 000 tokens réinjectés à chaque reprise."""
    if not since:
        return ""
    cfg = cfg or load_config()
    limit = cfg["inject"].get("resume_items", 5)
    new = sorted((n for n in brain.active() if n["type"] != "project" and (n.get("updated") or "") > since),
                 key=lambda n: n.get("updated") or "", reverse=True)
    if not new:
        return ""
    lines = ["🧠 Cerveau — nouveautés depuis le début de cette session :"]
    lines += [f"- [{TYPES.get(n['type'], n['type'])}] **{n['title']}** — {short(n.get('body', ''), 160)} `{n['id']}`"
              for n in new[:limit]]
    if len(new) > limit:
        lines.append(f"- … +{len(new) - limit} (`brain ls`)")
    return "\n".join(lines)


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
