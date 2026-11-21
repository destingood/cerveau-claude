"""Commandes des cartes de projets : cartographier, où est un symbole, imports, fiche d'un fichier, impact, chemin,
fichiers liés, concepts et rapport du graphe.

Découpé de cli.py (étape 8 du plan) sans rien changer : le parseur et main() restent dans cli.py, qui ne charge ce
module qu'au moment d'en lancer une commande."""
from __future__ import annotations

import os

from .cli_commun import die, node_line, project_arg, refresh_views
from .common import PROJECTS_DIR, REPORT_FILE, fold, short, write_text
from .store import Brain


def map_for(a):
    from . import mapper
    b = Brain.load()
    proj, _ = project_arg(b, getattr(a, "project", None))
    if getattr(a, "project", None) is None:
        proj = b.project_for_path(os.getcwd())
    if not proj:
        die("aucun projet connu ici — `brain map .` pour cartographier ce dossier (ou -p <projet>)")
    m = mapper.load_map(proj["id"])
    if not m:
        die(f"pas encore de carte pour `{proj['id']}` — lance `brain map .`")
    return proj, m


def cmd_map(a):
    from . import mapper
    if a.bg:
        from .hooks import spawn_background
        args = ["map", os.path.abspath(a.path or os.getcwd()), "--quiet"] + (["-p", a.project] if a.project else []) \
            + (["--full"] if a.full else [])
        print("✓ cartographie lancée en arrière-plan" if spawn_background(args) else "✗ lancement impossible")
        return
    try:
        meta = mapper.map_project(a.path, a.project, quiet=a.quiet, full=a.full, max_files=a.max_files)
    except ValueError as exc:
        die(str(exc))
    if meta.get("skipped"):
        if not a.quiet:
            print(f"… {meta['skipped']}")
        return
    refresh_views()
    if a.quiet:
        return
    print(f"✓ Carte de `{meta['pid']}` : {meta['n_files']} fichiers ({meta['parsed']} analysés, "
          f"{meta['n_files'] - meta['parsed']} repris du cache) en {meta['seconds']} s"
          + (" — ⚠️ partielle (limite atteinte)" if meta.get("truncated") else ""))
    if meta["stack"].get("summary"):
        print(f"  Stack : {meta['stack']['summary']}")
    if meta["entries"]:
        print("  Entrées : " + ", ".join(e for e, _ in meta["entries"][:6]))
    print(f"  Rapport : {PROJECTS_DIR / meta['pid'] / 'MAP.md'}")
    print("  Ensuite : `brain files \"sujet\"` · `brain where <symbole>` · `brain explain <fichier>` · `brain impact <x>`")


def _map_answer(lines, *misses):
    """Réponse d'une commande de la carte : rien trouvé (première ligne d'un de ces débuts) → message et sortie 1."""
    if not lines or lines[0].startswith(misses):
        die(lines[0] if lines else "rien trouvé")
    print("\n".join(lines))


def cmd_where(a):
    from . import mapper
    _, m = map_for(a)
    _map_answer(mapper.where(m, a.name, a.n) or [f"« {a.name} » introuvable dans la carte (essaie `brain files`)"],
                f"« {a.name} » introuvable")


def cmd_deps(a):
    from . import mapper
    _, m = map_for(a)
    _map_answer(mapper.deps(m, a.file), "aucun fichier ne correspond")


def cmd_explain(a):
    from . import mapper
    _, m = map_for(a)
    _map_answer(mapper.explain(m, a.target), "fichier introuvable", "rien trouvé pour")


def cmd_impact(a):
    from . import mapper
    _, m = map_for(a)
    lines, code = mapper.impact(m, a.target, a.depth)
    if code == 4:  # introuvable : un échec, dit comme les autres (code 4 gardé, mapper.impact le documente)
        die("\n".join(lines), code)
    print("\n".join(lines))
    return code


def cmd_path(a):
    b = Brain.load()
    looks_file = lambda ref: any(c in ref for c in "/\\.")  # noqa: E731
    x = None if looks_file(a.a) else b.get(a.a)
    y = None if looks_file(a.b) else b.get(a.b)
    if x and y:  # deux souvenirs : chemin dans le graphe de mémoire (explicites d'abord, puis déduits)
        from . import graph
        chain = graph.shortest_path(b, graph.ensure(b), x["id"], y["id"])
        if chain is None:
            print(f"aucun chemin entre `{x['id']}` et `{y['id']}` dans le graphe de mémoire")
            return
        out = [f"`{x['id']}` {x['title']}"]
        for nid, rel, sens in chain:
            arrow = f"—{rel}→" if sens == "→" else f"←{rel}—" if sens == "←" else rel
            out.append(f"  {arrow} `{nid}` {b.nodes[nid]['title']}")
        print(f"{len(chain)} saut(s) :\n" + "\n".join(out))
        return
    from . import mapper
    _, m = map_for(a)
    _map_answer(mapper.path_between(m, a.a, a.b), "fichier introuvable")


def cmd_files(a):
    from . import filesearch
    proj, _ = map_for(a)
    res = filesearch.search_files(proj["id"], " ".join(a.text), a.n)
    if not res:
        print("Aucun fichier correspondant.")
    for r in res:
        print(f"- {r['key']} — {short(r['desc'], 140)}")


def cmd_concept(a):
    from . import graph
    b = Brain.load()
    cs = graph.ensure(b).get("concepts", [])
    if not a.name:
        if not cs:
            print("Aucun concept partagé par au moins deux souvenirs pour l'instant.")
            return
        print(f"Concepts repérés ({len(cs)}) — détail : `brain concept <nom>`")
        print(" · ".join(f"{c['label']} ({len(c['members'])})" for c in cs))
        return
    q = fold(" ".join(a.name))
    import re as _re
    match = ([c for c in cs if fold(c["label"]) == q or c["key"] == q]
             or [c for c in cs if _re.search(rf"(?<![a-z0-9]){_re.escape(q)}", fold(c["label"]))]
             or [c for c in cs if q in fold(c["label"])])
    if not match:
        die(f"concept inconnu : {' '.join(a.name)} (liste : `brain concept`)")
    c = match[0]
    print(f"{c['label']} — {c['kind']} · {len(c['members'])} souvenirs :")
    for i in c["members"]:
        n = b.nodes.get(i)
        if n:
            print(f"- {node_line(n, 150)}")


def cmd_report(a):
    from . import graph
    b = Brain.load()
    an = graph.ensure(b, force=a.force)
    text = graph.report(b, an)
    write_text(REPORT_FILE, text)
    if a.print:
        print(text)
        return
    comms = [c for c in an["communities"] if c["size"] >= 2]
    print(f"✓ {REPORT_FILE} — {an['n']} nœuds · {an['explicit']} liens explicites · {len(an['inferred'])} liens déduits · "
          f"{len(comms)} communautés")
    print("Communautés : " + " · ".join(f"{c['label']} ({c['size']})" for c in comms[:5]))
    print("Nœuds clés : " + " · ".join(f"{b.nodes[i]['title']}" for i in an["key"][:3] if i in b.nodes))
    g = an["gaps"]
    print(f"Entretien : {len(an['dups'])} doublon(s) possible(s) · {len(g['isolated'])} isolé(s) · "
          f"{len(g['old_todos'])} à-faire ancien(s) · {len([e for e in an['inferred'] if e['conf'] != 'faible'])} lien(s) suggéré(s)"
          " — détail : `brain report --print`")
