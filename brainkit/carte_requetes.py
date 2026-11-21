"""Carte de projets : requêtes sur une carte — where, deps, explain, path, et impact d'une modification (graphe
d'appels). Partie de mapper.py, découpé le 21/11/2026."""
from __future__ import annotations

import os
import posixpath
import re
from collections import defaultdict, deque

from .carte_graphe import Resolver
from .carte_langages import _is_test, _size, fmt_ts, LANG_BY_EXT, LANG_LABEL
from .carte_parcours import PARSER_VERSION
from .common import PROJECTS_DIR, read_json

# =============================================================================================== requêtes
def load_map(pid):
    return read_json(PROJECTS_DIR / pid / "map.json", None)


def find_file(files, query, root=None):
    q = str(query).strip().strip("`")
    if root and os.path.isabs(q):
        try:
            q = os.path.relpath(q, root)
        except ValueError:
            pass
    q = q.replace("\\", "/").lstrip("./").lower()
    if not q:
        return []
    exact = [r for r in files if r.lower() == q]
    if exact:
        return exact
    rank = lambda r: (-files[r].get("pr", 0), len(r))  # noqa: E731
    for pred in (lambda r: r.lower().endswith("/" + q),
                 lambda r: posixpath.basename(r).lower().startswith(q),
                 lambda r: q in r.lower()):
        hits = [r for r in files if pred(r)]
        if hits:
            return sorted(hits, key=rank)
    return []


def where(m, name, limit=30):
    files = m["files"]
    q = name.lower().strip()
    buckets = ([], [], [])
    copies = 0
    for rel, f in files.items():
        if f.get("dup"):
            copies += sum(1 for s in f.get("symbols", []) if q in s["n"].lower())
            continue
        for s in f.get("symbols", []):
            n = s["n"].lower()
            tail = n.rsplit(".", 1)[-1]
            if q in (n, tail):
                buckets[0].append((rel, s))
            elif n.startswith(q) or tail.startswith(q):
                buckets[1].append((rel, s))
            elif q in n:
                buckets[2].append((rel, s))
    hits = buckets[0] + buckets[1] + buckets[2]
    lines = [f"{rel}:{s['l']}  {s['k']} {s['n']}" for rel, s in hits[:limit]]
    if len(hits) > limit:
        lines.append(f"… +{len(hits) - limit}")
    if copies:
        lines.append(f"(+{copies} occurrence(s) dans des copies identiques ignorées)")
    envs = [rel for rel, f in files.items() if any(v.lower() == q for v in f.get("env", []))]
    if envs:
        lines.append(f"variable d'env {name} utilisée dans : " + ", ".join(sorted(envs)[:15]))
    lines += [f"{rel}  route {r}" for rel, f in files.items() for r in f.get("routes", []) if q in r.lower()][:10]
    return lines


def deps(m, query):
    files = m["files"]
    cands = find_file(files, query, m["meta"].get("root"))
    if not cands:
        return [f"aucun fichier ne correspond à « {query} »"]
    rel = cands[0]
    f = files[rel]
    importers = sorted(r for r, g in files.items() if rel in (g.get("out") or []))
    lines = [f"`{rel}`" + (f"  (autres : {', '.join(cands[1:4])})" if len(cands) > 1 else "")]
    lines.append(f"→ importe ({len(f.get('out', []))}) : " + (", ".join(f.get("out", [])[:40]) or "—"))
    if f.get("ext"):
        lines.append("→ paquets externes : " + ", ".join(f["ext"][:40]))
    lines.append(f"← importé par ({len(importers)}) : " + (", ".join(importers[:40]) or "—"))
    return lines


def explain(m, target):
    files = m["files"]
    path, name = _split_target(target)
    if path:  # fichier:symbole
        cands = find_file(files, path, m["meta"].get("root"))
        if not cands:
            return [f"fichier introuvable : {path}"]
        r = cands[0]
        syms = _symbols(files, name, r)
        if not syms:
            return [f"« {name} » introuvable dans `{r}` (`brain where {name}`) :", ""] + explain(m, r)
        s = syms[0][1]
        return [f"Symbole « {s['n']} » : {r}:{s['l']}  {s['k']}"] + _call_lines(m, r, s) + [""] + explain(m, r)
    cands = find_file(files, target, m["meta"].get("root"))
    if not cands:
        hits = [l for l in where(m, target, 12)]
        if not hits:
            return [f"rien trouvé pour « {target} » (essaie `brain files \"{target}\"`)"]
        first = hits[0].split(":")[0]
        syms = _symbols(files, target, first) if first in files else []
        calls = _call_lines(m, first, syms[0][1]) if syms else []
        return [f"Symbole « {target} » :"] + hits + calls + [""] + explain(m, first)
    rel = cands[0]
    f = files[rel]
    importers = sorted(r for r, g in files.items() if rel in (g.get("out") or []))
    rank = sorted((r for r in files if files[r].get("pr")), key=lambda r: -files[r]["pr"])
    pos = rank.index(rel) + 1 if rel in rank else None
    head = f"`{rel}` — {LANG_LABEL.get(f.get('lang'), f.get('lang'))}"
    head += f" · {f['lines']} lignes" if f.get("lines") else ""
    head += f" · {_size(f.get('size', 0))}"
    head += f" · module {f['mod'] or '(racine)'}" if "mod" in f else ""
    head += f" · centralité #{pos}/{len(rank)}" if pos else ""
    head += f" · modifié le {fmt_ts(f.get('mtime'))}"
    L = [head]
    if len(cands) > 1:
        L.append("(autres correspondances : " + ", ".join(cands[1:5]) + ")")
    for key, label in (("title", "Titre"), ("doc", "Résumé")):
        if f.get(key):
            L.append(f"{label} : {f[key]}")
    syms = f.get("symbols", [])
    if syms:
        L.append(f"Symboles ({len(syms)}) : " + ", ".join(f"{s['n']} ({s['k']} l.{s['l']})" for s in syms[:60]))
    if f.get("headings"):
        L.append("Plan : " + " | ".join(f["headings"][:20]))
    if f.get("sheets"):
        L.append("Feuilles : " + ", ".join(f["sheets"]))
    if f.get("routes"):
        L.append("Routes : " + " · ".join(f["routes"][:20]))
    if f.get("env"):
        L.append("Variables d'env : " + ", ".join(f["env"]))
    if f.get("pkg", {}).get("scripts"):
        L.append("Scripts : " + " · ".join(f"{k} → {v}" for k, v in f["pkg"]["scripts"].items()))
    if f.get("deps"):
        L.append(f"Dépendances ({len(f['deps'])}) : " + ", ".join(f["deps"][:40]))
    if f.get("out"):
        L.append(f"Importe ({len(f['out'])}) : " + ", ".join(f["out"][:40]))
    if f.get("ext"):
        L.append("Paquets externes : " + ", ".join(f["ext"][:40]))
    if importers:
        L.append(f"Importé par ({len(importers)}) : " + ", ".join(importers[:40]))
    if f.get("todos"):
        L.append("TODO : " + " · ".join(f"l.{ln} {k} {t}" for ln, k, t in f["todos"]))
    if f.get("why"):
        L.append("Raisons notées : " + " · ".join(f"l.{ln} {k} {t}" for ln, k, t in f["why"]))
    if f.get("sensitive"):
        L.append("⚠️ fichier sensible : contenu volontairement jamais lu.")
    return L


def path_between(m, a, b):
    files = m["files"]
    root = m["meta"].get("root")
    A, B = find_file(files, a, root), find_file(files, b, root)
    if not A or not B:
        return [f"fichier introuvable : {a if not A else b}"]
    src, dst = A[0], B[0]
    adj = defaultdict(set)
    for rel, f in files.items():
        for t in f.get("out", []):
            adj[rel].add((t, "→"))
            adj[t].add((rel, "←"))
    prev = {src: None}
    q = deque([src])
    while q:
        cur = q.popleft()
        if cur == dst:
            break
        for nxt, d in sorted(adj[cur]):
            if nxt not in prev:
                prev[nxt] = (cur, d)
                q.append(nxt)
    if dst not in prev:
        return [f"aucun chemin d'imports entre `{src}` et `{dst}`"]
    chain, cur = [], dst
    while prev[cur]:
        p, d = prev[cur]
        chain.append((d, cur))
        cur = p
    chain.reverse()
    text = f"`{src}`" + "".join(f" {'importe' if d == '→' else 'est importé par'} `{c}`" for d, c in chain)
    return [f"{len(chain)} saut(s) : {text}"]


# =============================================================================================== impact (avant de modifier)
_REL_RANK = {"c": 0, "h": 1, "r": 2, "d": 3}
VERBS = {"c": "appelle", "h": "hérite de", "r": "utilise", "d": "appelle (déduit)"}
KIND_LABEL = {"fn": "fonction", "class": "classe", "method": "méthode", "const": "constante"}


def call_edges(m) -> list:
    """Liens d'appel résolus (Python) : [(fichier, appelant, ligne, fichier visé, symbole visé, relation)].
    Relation : c appel · h héritage · r usage · d appel déduit (méthode au nom unique parmi les fichiers atteignables).
    Résolution : imports relatifs et absolus, réexports d'un __init__, sous-modules, héritage ; un nom qui reste
    ambigu ne donne aucun lien."""
    files = m["files"]
    py = {r for r, f in files.items() if f.get("lang") == "python" and not f.get("dup")}
    R = Resolver(files)
    syms = {r: {s["n"] for s in files[r].get("symbols") or []} | (set(files[r].get("pyrefs") or {}) - {""}) for r in py}
    meth = defaultdict(list)
    for r in sorted(py):
        for s in files[r].get("symbols") or []:
            if s["k"] == "method":
                meth[s["n"].rsplit(".", 1)[1]].append((r, s["n"]))
    memo, reach_memo = {}, {}

    def mod(rel, spec):
        k = (posixpath.dirname(rel), spec)
        if k not in memo:
            try:
                hit = R.py(rel, spec)[0]
            except Exception:
                hit = None
            memo[k] = hit if hit in py else None
        return memo[k]

    def origins(f, head):  # « from .prix import total » dans f → module d'où vient « total »
        n = len(head)
        for e in files[f].get("imports") or []:
            if len(e) > n and e.endswith(head) and e[-n - 1] == ".":
                M = e[:-n]
                yield M if not M.strip(".") else M[:-1]

    def lookup(rel, M, dotted, hops):
        if hops > 4:
            return None
        parts = dotted.split(".")
        base = M if M.endswith(".") else M + "."
        for k in range(len(parts) - 1, 0, -1):  # sous-module le plus long d'abord : from pkg import mod ; mod.f()
            t = mod(rel, base + ".".join(parts[:k]))
            hit = member(t, ".".join(parts[k:]), hops + 1) if t else None
            if hit:
                return hit
        return member(mod(rel, M), dotted, hops + 1)

    def member(f, name, hops):
        if not f or hops > 4:
            return None
        if name in syms.get(f, ()):
            return f, name
        head, _, rest = name.partition(".")
        if rest and head in syms.get(f, ()):
            return inherited(f, head, rest, hops)
        for M in origins(f, head):
            hit = lookup(f, M, name, hops + 1)
            if hit:
                return hit
        return None

    def inherited(f, cls, attr, hops):
        for p in (files[f].get("pyrefs") or {}).get(cls) or []:
            p = p.split()
            if len(p) > 3 and p[1] == "h":
                base = target(f, p[2], p[3:], hops + 1)
                hit = member(base[0], f"{base[1]}.{attr}", hops + 1) if base else None
                if hit:
                    return hit
        return None

    def reach(rel):  # fichiers atteignables en 3 imports au plus
        if rel not in reach_memo:
            seen, frontier = {rel}, [rel]
            for _ in range(3):
                nxt = []
                for x in frontier:
                    for t in files.get(x, {}).get("out") or []:
                        if t not in seen:
                            seen.add(t)
                            nxt.append(t)
                frontier = nxt
            reach_memo[rel] = seen
        return reach_memo[rel]

    def target(rel, kind, args, hops=0):
        if kind == "l":
            return member(rel, args[0], hops)
        if kind == "i":
            return lookup(rel, args[0], args[1], hops)
        if kind == "f":
            return lookup(rel, args[0], f"{args[1]}.{args[2]}", hops)
        if kind == "m":
            hit = member(mod(rel, args[0]), args[1], hops)
            if not hit and "." in args[0]:
                head, last = args[0].rsplit(".", 1)
                hit = member(mod(rel, head), f"{last}.{args[1]}", hops)
            return hit
        if kind == "s":
            return member(rel, f"{args[0]}.{args[1]}", hops)
        if kind == "p":
            return inherited(rel, args[0], args[1], hops)
        if kind == "*":
            for M in files[rel].get("pystar") or []:
                hit = lookup(rel, M, args[0], hops)
                if hit:
                    return hit
            return None
        if kind == "a":
            cands = [x for x in meth.get(args[0], ()) if x[0] in reach(rel)]
            return cands[0] if len(cands) == 1 else None
        return None

    best, done = {}, {}
    for rel in sorted(py):
        for caller, refs in (files[rel].get("pyrefs") or {}).items():
            for s in refs:
                p = s.split()
                try:
                    line, rl, kind, args = int(p[0]), p[1], p[2], tuple(p[3:])
                    k = (rel, kind) + args
                    if k not in done:
                        done[k] = target(rel, kind, args)
                    hit = done[k]
                except (ValueError, IndexError, KeyError, RecursionError):
                    continue
                if not hit or tuple(hit) == (rel, caller):
                    continue
                rl = "d" if kind == "a" else rl
                key = (rel, caller) + tuple(hit)
                v = (_REL_RANK.get(rl, 9), line, rl)
                if key not in best or v < best[key]:
                    best[key] = v
    return [(k[0], k[1], v[1], k[2], k[3], v[2]) for k, v in best.items()]


def _split_target(t):
    """« fichier.py:symbole » → (fichier, symbole) ; sinon (None, cible). « C:… » (lecteur Windows) n'en est pas un."""
    t = str(t).strip().strip("`")
    mt = re.match(r"^(.+?):([A-Za-z_][\w.]*)$", t)
    if mt and len(mt.group(1)) > 1:
        return mt.group(1), mt.group(2)
    return None, t


def _looks_like_path(name) -> bool:
    return "/" in name or "\\" in name or posixpath.splitext(name.lower())[1] in LANG_BY_EXT


def _symbols(files, name, rel=None):
    """Définitions d'un nom, du plus précis au plus vague : nom complet, fin de nom (méthode), casse ignorée."""
    q = str(name).strip()
    ql = q.lower()
    tiers = ([], [], [])
    for r in ([rel] if rel else sorted(files)):
        f = files.get(r) or {}
        if f.get("dup"):
            continue
        for s in f.get("symbols") or []:
            n = s["n"]
            tail = n.rsplit(".", 1)[-1]
            if n == q:
                tiers[0].append((r, s))
            elif tail == q:
                tiers[1].append((r, s))
            elif ql in (n.lower(), tail.lower()):
                tiers[2].append((r, s))
    return next((t for t in tiers if t), [])


def impact(m, target, depth=2):
    """Ce qui dépend d'un fichier ou d'un symbole, à revoir avant de le modifier (façon graphify « affected »).
    → (lignes, code de sortie) : 0 trouvé · 3 nom ambigu (définitions listées) · 4 introuvable."""
    files, root = m["files"], m["meta"].get("root")
    depth = max(1, min(5, int(depth or 2)))
    stale = any(f.get("lang") == "python" and f.get("v") != PARSER_VERSION for f in files.values())
    hint = ["(carte d'une version précédente, sans graphe d'appels : lance d'abord `brain map .`)", ""] if stale else []
    path, name = _split_target(target)
    if path:
        cands = find_file(files, path, root)
        if not cands:
            return [f"fichier introuvable : {path}"], 4
        syms = _symbols(files, name, cands[0])
        if not syms:
            return [f"« {name} » introuvable dans `{cands[0]}` (`brain where {name}`)"], 4
    else:
        cands = find_file(files, name, root) if _looks_like_path(name) else []
        if cands:
            return hint + _impact_file(m, cands[0], depth), 0
        syms = _symbols(files, name)
        if not syms:
            cands = find_file(files, name, root)
            if not cands:
                return [f"rien trouvé pour « {name} » (essaie `brain where {name}` ou `brain files \"{name}\"`)"], 4
            return hint + _impact_file(m, cands[0], depth), 0
    if len(syms) > 1:
        L = [f"« {name} » est ambigu : {len(syms)} définitions. Précise avec `brain impact fichier:symbole` :"]
        L += [f"- {r}:{s['n']}  ({KIND_LABEL.get(s['k'], s['k'])}, l.{s['l']})" for r, s in syms[:10]]
        return L + ([f"… +{len(syms) - 10}"] if len(syms) > 10 else []), 3
    rel, s = syms[0]
    if files[rel].get("lang") != "python":
        return ([f"(graphe d'appels : Python seulement — impact du fichier qui définit « {s['n']} »)", ""]
                + _impact_file(m, rel, depth)), 0
    return hint + _impact_symbol(m, rel, s, depth), 0


def _impact_symbol(m, rel, s, depth):
    files = m["files"]
    rev = defaultdict(list)
    for src, caller, line, tf, ts, rl in call_edges(m):
        rev[(tf, ts)].append((src, caller, line, rl))
    name = s["n"]
    seeds = {(rel, name)}
    if s["k"] == "class":
        seeds |= {(rel, x["n"]) for x in files[rel].get("symbols") or [] if x["n"].startswith(name + ".")}
    seen, frontier, levels = set(seeds), seeds, []
    for _ in range(depth):
        hits = {}
        for t in frontier:
            for src, caller, line, rl in rev.get(t, ()):
                u, v = (src, caller), (_REL_RANK[rl], line, rl, t[1])
                if u not in seen and (u not in hits or v < hits[u]):
                    hits[u] = v
        if not hits:
            break
        levels.append(hits)
        seen |= set(hits)
        frontier = {u for u in hits if u[1]}  # le niveau module (« ») n'a pas d'appelant
    L = [f"Impact de « {name} » — {rel}:{s['l']} ({KIND_LABEL.get(s['k'], s['k'])}) · profondeur {depth}"]
    if not levels:
        L.append(f"Aucun appel ni usage repéré de « {name} » dans le code Python analysé "
                 "(les appels dynamiques — getattr, chaînes — ne sont pas visibles).")
        return L + _impact_footer(files, rel, set())
    touched, deduced = set(), False
    for d, hits in enumerate(levels, 1):
        rows = sorted(hits.items(), key=lambda kv: (kv[0][0], kv[1][1]))
        L += ["", f"Dépend directement ({len(rows)}) :" if d == 1 else f"Niveau {d} ({len(rows)}) :"]
        for (src, caller), (_, line, rl, ts) in rows[:40]:
            L.append(f"- {src}:{line}  {caller or '(niveau module)'} {VERBS[rl]} {ts}")
            deduced |= rl == "d"
        if len(rows) > 40:
            L.append(f"… +{len(rows) - 40}")
        touched |= {u[0] for u in hits}
    L += _impact_footer(files, rel, touched)
    if deduced:
        L.append("(« déduit » : méthode au nom unique dans le projet, appelée sur un objet : à confirmer)")
    return L


def _impact_file(m, rel, depth):
    files = m["files"]
    imp = defaultdict(set)
    for r, f in files.items():
        if not f.get("dup"):
            for t in f.get("out") or []:
                imp[t].add(r)
    uses = defaultdict(set)
    if files[rel].get("lang") == "python":
        for src, _, _, tf, ts, _ in call_edges(m):
            if tf == rel and src != rel:
                uses[src].add(ts)
    L = [f"Impact du fichier `{rel}` · profondeur {depth}"]
    seen, frontier, levels = {rel}, [rel], []
    for _ in range(depth):
        nxt = {}
        for x in frontier:
            for r in sorted(imp.get(x, ())):
                if r not in seen and r not in nxt:
                    nxt[r] = x
        if not nxt:
            break
        levels.append(nxt)
        seen |= set(nxt)
        frontier = list(nxt)
    if not levels:
        return L + ["Aucun fichier du projet ne l'importe."] + _impact_footer(files, rel, set())
    touched = set()
    for d, nxt in enumerate(levels, 1):
        rows = sorted(nxt.items())
        L += ["", f"Importé directement par ({len(rows)}) :" if d == 1 else f"Niveau {d} ({len(rows)}) :"]
        for r, via in rows[:40]:
            if d > 1:
                L.append(f"- `{r}` via `{via}`")
                continue
            u = sorted(uses.get(r, ()))
            L.append(f"- `{r}`" + (" — utilise : " + ", ".join(u[:8]) + (" …" if len(u) > 8 else "") if u else ""))
        if len(rows) > 40:
            L.append(f"… +{len(rows) - 40}")
        touched |= set(nxt)
    return L + _impact_footer(files, rel, touched)


def _impact_footer(files, rel, touched):
    tests = sorted({r for r in touched if _is_test(r)}
                   | {r for r, f in files.items() if _is_test(r) and not f.get("dup") and rel in (f.get("out") or [])})
    others = sorted(r for r in touched if r != rel and not _is_test(r))
    L = [""]
    if others:
        L.append(f"À revoir : {len(others)} fichier(s) — " + ", ".join(f"`{r}`" for r in others[:12])
                 + (" …" if len(others) > 12 else ""))
    L.append("Tests reliés : " + ", ".join(f"`{r}`" for r in tests[:12]) + (" …" if len(tests) > 12 else "")
             if tests else "Aucun test relié repéré.")
    return L


def _call_lines(m, rel, s, limit=15):
    """Appelants et appelés d'un symbole Python (fiche `explain`)."""
    files = m["files"]
    if (files.get(rel) or {}).get("lang") != "python":
        return []
    own = {s["n"]}
    if s["k"] == "class":
        own |= {x["n"] for x in files[rel].get("symbols") or [] if x["n"].startswith(s["n"] + ".")}
    callers, callees = {}, {}
    for src, caller, line, tf, ts, rl in call_edges(m):
        from_own, to_own = src == rel and caller in own, tf == rel and ts in own
        if to_own == from_own:
            continue
        side, k = (callers, (src, caller)) if to_own else (callees, (tf, ts))
        if k not in side or (_REL_RANK[rl], line) < (_REL_RANK[side[k][1]], side[k][0]):
            side[k] = (line, rl)
    tag = {"h": "héritage", "r": "usage", "d": "déduit"}
    L = []
    if callers:
        rows = sorted(callers.items(), key=lambda kv: (kv[0][0], kv[1][0]))
        L.append(f"Appelé par ({len(rows)}) : " + " · ".join(
            f"{c or '(niveau module)'} ({src}:{line}{', ' + tag[rl] if rl in tag else ''})"
            for (src, c), (line, rl) in rows[:limit]) + (" …" if len(rows) > limit else ""))
    if callees:
        rows = sorted(callees.items(), key=lambda kv: kv[1][0])
        L.append(f"Appelle ({len(rows)}) : " + " · ".join(
            f"{ts} (`{tf}`{', ' + tag[rl] if rl in tag else ''})"
            for (tf, ts), (line, rl) in rows[:limit]) + (" …" if len(rows) > limit else ""))
    return L or ["Appels : aucun repéré (les appels dynamiques ne sont pas visibles)."]
