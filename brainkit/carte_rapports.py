"""Carte de projets : rapports — MAP.md (lisible), DIGEST.md (injecté au démarrage) et index de recherche
(search.json). Partie de mapper.py, découpé le 21/11/2026."""
from __future__ import annotations

import posixpath
import re
from collections import Counter, defaultdict

from .carte_langages import _is_test, _kind, _n, CODE, fmt_ts, LANG_LABEL
from .common import fmt_date, PROJECTS_DIR, short, tokenize
from .filesearch import BACKUP_RX

NOT_ISOLATED = re.compile(r"(^|/)(__init__\.py|__main__\.py|setup\.py|conftest\.py|manage\.py|[\w.-]+\.config\.[cm]?[jt]s|"
                          r"[\w.-]+\.d\.ts|\.eslintrc\.[cm]?js)$")


def file_desc(f, n_syms=5) -> str:
    bits = []
    head = f.get("title") or f.get("doc")
    if head:
        bits.append(short(head, 80))
    syms = [s["n"] for s in (f.get("symbols") or []) if s.get("k") not in ("method", "const")][:n_syms]
    if syms:
        bits.append(", ".join(syms))
    if f.get("routes"):
        bits.append("routes " + ", ".join(f["routes"][:3]))
    if not head and f.get("headings"):
        bits.append(" / ".join(h.lstrip("# ") for h in f["headings"][:3]))
    if f.get("sensitive"):
        bits.append("sensible (non lu)")
    if not bits:
        bits.append(LANG_LABEL.get(f.get("lang"), f.get("lang") or "?") + (f", {f['lines']} l." if f.get("lines") else ""))
    return " · ".join(bits)


# =============================================================================================== rapports
def tree_lines(files, depth=2, max_lines=45):
    count, exts = Counter(), defaultdict(Counter)
    for rel in files:
        parts = rel.split("/")
        for d in range(1, min(len(parts), depth + 1)):
            key = "/".join(parts[:d])
            count[key] += 1
            exts[key][posixpath.splitext(parts[-1])[1].lower() or "(sans ext.)"] += 1
    lines = []
    for d in sorted(count):
        detail = ", ".join(f"{n} {e}" for e, n in exts[d].most_common(3))
        lines.append(f"{'  ' * d.count('/')}- `{posixpath.basename(d)}/` ({count[d]} : {detail})")
        if len(lines) >= max_lines:
            lines.append("  - …")
            break
    root_files = sorted(r for r in files if "/" not in r)
    if root_files:
        more = f" … +{len(root_files) - 15}" if len(root_files) > 15 else ""
        lines.append("- racine : " + ", ".join(f"`{r}`" for r in root_files[:15]) + more)
    return lines


def cross_links(files, comms):
    label = {m: lab for lab, mem in comms.items() for m in mem}
    pairs = {}
    for rel, f in files.items():
        a = label.get(rel)
        for t in f.get("out", []):
            b = label.get(t)
            if a is None or b is None or a == b:
                continue
            n, ex = pairs.get((a, b), (0, (rel, t)))
            pairs[(a, b)] = (n + 1, ex)
    return sorted(pairs.items(), key=lambda kv: -kv[1][0])


def _weight(rel, pr):
    """Centralité ajustée : les dossiers de sauvegarde/export/archive comptent peu dans les classements."""
    return pr.get(rel, 0) * (0.1 if BACKUP_RX.search(rel) else 1.0)


def _ranked(files, pr, langs, limit):
    return [r for r in sorted(pr, key=lambda r: -_weight(r, pr))
            if files.get(r, {}).get("lang") in langs and not files[r].get("dup")][:limit]


def _socle(files, limit=4):
    """Socle (façon graphify « god nodes ») : fichiers de code importés partout qui n'importent presque rien
    (utilitaires communs). Montrés à part pour ne pas chasser les vrais fichiers clés du classement."""
    code = {r for r, f in files.items() if f.get("lang") in CODE and not f.get("dup")}
    indeg, linked = Counter(), set()
    for r in code:
        outs = [t for t in files[r].get("out") or [] if t in code]
        if outs:
            linked.add(r)
            linked.update(outs)
            if not _is_test(r):
                indeg.update(outs)
    if len(linked) < 6:
        return []
    need = max(3, -(-len(linked) * 15 // 100))  # importé par au moins 15 % des fichiers reliés
    cands = [r for r, n in indeg.items()
             if n >= need and sum(1 for t in files[r].get("out") or [] if t in code) <= 1]
    return sorted(cands, key=lambda r: (-indeg[r], r))[:limit]


def _modules(comms, pr, min_size=2):
    """Modules utiles d'abord ; ceux des dossiers de sauvegarde/export à la fin."""
    mods = [(lab, mem) for lab, mem in comms.items() if len(mem) >= min_size]
    return sorted(mods, key=lambda x: (bool(BACKUP_RX.search((x[0] or "") + "/")),
                                       -(sum(pr.get(m, 0) for m in x[1]) + 1e-6 * len(x[1]))))


def _label(lab, width=42):
    lab = lab or "(racine)"
    if len(lab) <= width:
        return lab
    tail = "/".join(lab.split("/")[-2:])
    return "…/" + (tail if len(tail) <= width else tail[-width:])


def build_report(meta, files, in_edges, pr, comms, sccs) -> str:
    kinds = Counter(_kind(f) for f in files.values())
    loc = sum(f.get("lines", 0) for f in files.values() if f.get("lang") in CODE)
    L = [f"# 🗺️ Carte du projet « {meta['name']} »",
         f"`{meta['root']}` · {len(files)} fichiers ({kinds['code']} code · {kinds['doc']} docs · {kinds['data']} données · "
         f"{kinds['asset']} médias · {kinds['other']} autres) · {_n(loc)} lignes de code · "
         f"générée le {fmt_date(meta['generated'])} en {meta['seconds']} s "
         f"({meta['parsed']} analysés, {len(files) - meta['parsed']} repris du cache)"]
    if meta.get("truncated"):
        L.append("> ⚠️ Limite de fichiers atteinte : carte partielle (`brain config map.max_files <n>`).")
    if meta["stack"].get("summary"):
        L.append(f"**Stack :** {meta['stack']['summary']}")
    if meta["entries"]:
        L.append("**Points d'entrée :** " + " · ".join(f"`{e}` ({why})" for e, why in meta["entries"][:10]))
    if meta.get("scripts"):
        L.append("**Scripts npm :** " + " · ".join(f"`{k}` → {short(v, 60)}" for k, v in list(meta["scripts"].items())[:10]))
    L += ["", "## Structure"] + tree_lines(files)

    socle = _socle(files)
    ranked = [r for r in _ranked(files, pr, CODE | {"json", "markdown"}, 15 + len(socle)) if r not in socle][:15]
    if ranked:
        L += ["", "## Fichiers clés (centralité dans le graphe d'imports/liens)"]
        for i, rel in enumerate(ranked, 1):
            f = files[rel]
            L.append(f"{i}. `{rel}` — {file_desc(f)} · importé par {len(in_edges.get(rel, []))} · importe {len(f.get('out', []))}")
    if socle:
        L += ["", "**Socle** (importé partout, n'importe presque rien — utilitaires communs) : "
              + " · ".join(f"`{r}` (importé par {len(in_edges.get(r, []))})" for r in socle)]
    big = _modules(comms, pr)
    if big:
        L += ["", "## Modules (communautés d'imports)"]
        for lab, mem in big[:12]:
            top = sorted(mem, key=lambda m: -_weight(m, pr))[:8]
            L.append(f"- **{_label(lab, 70)}** ({len(mem)}) : " + ", ".join(f"`{posixpath.basename(m)}`" for m in top))
        bridges = cross_links(files, comms)
        if bridges:
            L += ["", "## Liens entre modules"]
            L += [f"- {a or '(racine)'} → {b or '(racine)'} ({n}×), ex. `{ex[0]}` → `{ex[1]}`" for (a, b), (n, ex) in bridges[:8]]
    routes = [(rel, r) for rel, f in sorted(files.items()) for r in f.get("routes", [])]
    if routes:
        L += ["", f"## Routes / endpoints ({len(routes)})"] + [f"- `{r}` — `{rel}`" for rel, r in routes[:40]]
        if len(routes) > 40:
            L.append(f"- … +{len(routes) - 40}")
    env = sorted({v for f in files.values() for v in f.get("env", [])})
    if env:
        L += ["", "## Variables d'environnement (noms uniquement)", ", ".join(f"`{v}`" for v in env[:60])]
    docs = sorted((r for r, f in files.items() if _kind(f) == "doc" and not f.get("dup")),
                  key=lambda r: -files[r].get("mtime", 0))
    if docs:
        L += ["", f"## Documents ({len(docs)}, plus récents d'abord)"]
        L += [f"- `{r}` — {file_desc(files[r])} · {fmt_ts(files[r].get('mtime'))}" for r in docs[:25]]
        if len(docs) > 25:
            L.append(f"- … +{len(docs) - 25} (`brain files \"sujet\"`)")
    data = sorted((r for r, f in files.items() if f.get("lang") in ("csv", "xlsx", "xls", "notebook")
                   or (f.get("lang") == "json" and f.get("size", 0) > 20000)), key=lambda r: -files[r].get("mtime", 0))
    if data:
        L += ["", f"## Données ({len(data)})"] + [f"- `{r}` — {file_desc(files[r])}" for r in data[:15]]
    recent = sorted(files, key=lambda r: -files[r].get("mtime", 0))[:10]
    L += ["", "## Récemment modifiés"] + [f"- {fmt_ts(files[r].get('mtime'))} `{r}`" for r in recent]

    attn = []
    for comp in sccs:
        attn.append("Cycle d'imports : " + " ↔ ".join(f"`{c}`" for c in comp[:5]) + (" …" if len(comp) > 5 else ""))
    entry_set = {e for e, _ in meta["entries"]}
    lonely_langs = CODE - {"html", "css", "sql", "docker", "make", "batch", "shell", "powershell", "liquid"}
    if meta.get("dups"):
        where_dups = ", ".join(f"`{d}/` ({n})" for d, n in meta.get("dup_dirs", []))
        attn.append(f"Copies identiques : {meta['dups']} fichiers (surtout {where_dups}) — la plus récente sert de "
                    "référence, les copies sont ignorées dans les classements et la recherche.")
    isolated = [r for r, f in files.items() if f.get("lang") in lonely_langs and not f.get("out") and not f.get("dup")
                and r not in in_edges and r not in entry_set and not _is_test(r) and not NOT_ISOLATED.search(r)]
    if isolated and len(isolated) < len([1 for f in files.values() if f.get("lang") in lonely_langs]):
        attn.append(f"Fichiers code isolés (ni importés ni importants) : {len(isolated)} — ex. "
                    + ", ".join(f"`{r}`" for r in sorted(isolated)[:6]))
    bigf = sorted((r for r, f in files.items() if f.get("lang") in CODE and f.get("lines", 0) > 800),
                  key=lambda r: -files[r]["lines"])
    if bigf:
        attn.append("Gros fichiers : " + ", ".join(f"`{r}` ({files[r]['lines']} l.)" for r in bigf[:6]))
    todo_total = sum(f.get("todo", 0) for f in files.values())
    if todo_total:
        ex = [(r, t) for r, f in sorted(files.items()) for t in f.get("todos", [])][:5]
        attn.append(f"TODO/FIXME : {todo_total} — " + " · ".join(f"`{r}:{ln}` {k} {short(txt, 50)}" for r, (ln, k, txt) in ex))
    sens = [r for r, f in files.items() if f.get("sensitive")]
    if sens:
        attn.append("Fichiers sensibles (jamais lus) : " + ", ".join(f"`{r}`" for r in sens[:8]))
    errs = [r for r, f in files.items() if f.get("err")]
    if errs:
        attn.append(f"Fichiers non analysables : {len(errs)} (ex. `{errs[0]}`)")
    bigskip = [r for r, f in files.items() if f.get("big")]
    if bigskip:
        attn.append(f"Trop gros pour l'analyse : {len(bigskip)} (ex. `{bigskip[0]}`)")
    if attn:
        L += ["", "## Points d'attention"] + [f"- {a}" for a in attn]
    L += ["", "## Utiliser cette carte",
          "`brain files \"sujet\"` · `brain where <symbole>` · `brain explain <fichier>` · `brain deps <fichier>` · "
          "`brain impact <x>` (avant de modifier) · `brain path <a> <b>` · `brain map .` (mise à jour incrémentale)"]
    return "\n".join(L) + "\n"


def build_digest(meta, files, pr, comms, pid) -> str:
    if not files:
        return ("**🗺️ Carte du dossier** : aucun fichier visible (dossier vide ou seulement des fichiers cachés) — "
                "le travail de ce projet se fait ailleurs ; voir les sessions et souvenirs ci-dessus.")
    kinds = Counter(_kind(f) for f in files.values())
    counts = ", ".join(f"{kinds[k]} {w}" for k, w in (("code", "code"), ("doc", "docs"), ("data", "données"),
                                                       ("asset", "médias")) if kinds[k])
    parts = [f"**🗺️ Carte du dossier** ({fmt_date(meta['generated'])}) : {len(files)} fichiers — {counts}."]
    if meta["stack"].get("summary"):
        parts.append(f"Stack : {short(meta['stack']['summary'], 200)}")
    if meta["entries"]:
        parts.append("Entrées : " + ", ".join(f"`{e}`" for e, _ in meta["entries"][:4]))
    if meta.get("scripts"):
        parts.append("Scripts npm : " + ", ".join(f"`{k}`" for k in list(meta["scripts"])[:8]))
    socle = _socle(files)
    ranked = [r for r in _ranked(files, pr, CODE, 6 + len(socle)) if r not in socle][:6]
    if ranked:
        parts.append("Fichiers clés : " + " · ".join(f"`{r}` ({short(file_desc(files[r], 2), 48)})" for r in ranked))
    if socle:
        parts.append("Socle (importé partout) : " + " · ".join(f"`{r}`" for r in socle))
    mods = _modules(comms, pr, 3)[:5]
    if mods:
        parts.append("Modules : " + " · ".join(f"{_label(lab)} ({len(mem)})" for lab, mem in mods))
    docs = sorted((r for r, f in files.items() if _kind(f) == "doc" and not f.get("dup")),
                  key=lambda r: -files[r].get("mtime", 0))[:6]
    if meta.get("dups"):
        parts.append(f"Copies identiques ignorées : {meta['dups']} fichiers (sauvegardes/exports).")
    if docs:
        def label(r):
            t = files[r].get("title") or files[r].get("doc") or ""
            return f"`{r}`" + (f" « {short(t, 50)} »" if t else "")
        parts.append("Docs récents : " + " · ".join(label(r) for r in docs))
    parts.append(f"→ Carte complète : `{PROJECTS_DIR / pid / 'MAP.md'}`")  # files/where/explain/impact : bloc CLAUDE.md
    text = "\n".join(parts)
    return text if len(text) <= 1900 else text[:1899] + "…"


def build_search(files) -> dict:
    keys, tfs, descs = [], [], []
    for rel, f in files.items():
        if f.get("dup") or (f.get("lang") in ("asset", "binary", "other", "skip") and not f.get("title")):
            continue
        fields = [
            (re.sub(r"[/_.\-]", " ", rel), 3.0),
            (" ".join(s["n"] for s in (f.get("symbols") or [])[:120]), 2.0),
            (" ".join([f.get("title") or "", f.get("doc") or ""] + (f.get("headings") or [])[:20] + (f.get("sheets") or [])), 1.4),
            (" ".join(f.get("routes") or []), 1.5),
            (" ".join(w[2] for w in f.get("why") or []), 1.2),
        ]
        tf = Counter()
        for text, w in fields:
            for t in tokenize(text):
                tf[t] += w
        if tf:
            keys.append(rel)
            tfs.append({t: round(v, 1) for t, v in tf.items()})
            descs.append(file_desc(f))
    return {"keys": keys, "tfs": tfs, "descs": descs}
