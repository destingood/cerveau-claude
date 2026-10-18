"""Ligne de commande du cerveau : python brain.py <commande> … (aide : -h, ou <commande> -h)."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path

from . import __version__
from . import index as idx
from . import journal, search
from .common import (BRAIN_DIR, CLAUDE_HOME, CMD, CONFIG_FILE, EXPORT_FILE, GRAPH_FILE, INDEX_FILE, JOURNAL_FILE,
                     LOG_FILE, PROJECTS_DIR, REPORT_FILE, VIZ2D_FILE, VIZ_FILE, budget_chars, days_since, est_tokens, fmt_date,
                     fold, load_config, log, now_iso, set_config, setup_io, short, slugify, write_text)
from .store import GLOBAL_REFS, TYPES, Brain, bump_hits, clean_tags, normalize_type, priority


def die(msg, code=1):
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(code)


def refresh_views():
    """Après une modification : index injecté, export lisible et visualisation à jour (mode wiki : index.md aussi)."""
    try:
        b = Brain.load()
        idx.rebuild(b)
        idx.export(b)
        if b.data.get("wiki") and not b.data["wiki"].get("missing"):
            from . import wiki
            wiki.write_index(b)
        from . import viz
        viz.render(b)
    except Exception as exc:
        log(f"refresh_views : {exc!r}")


def body_of(a):
    if getattr(a, "body_file", None):
        return Path(a.body_file).read_text(encoding="utf-8")
    body = getattr(a, "body", None)
    if body == "-":
        return sys.stdin.read()
    return body


def types_of(spec):
    if not spec:
        return None
    try:
        return [normalize_type(t) for t in spec.split(",") if t.strip()]
    except ValueError as exc:
        die(str(exc))


def project_arg(b, ref, cwd=None):
    """-p : id/nom/chemin, « . » = projet courant, « none » = global."""
    if ref is None:
        return None, False
    if str(ref).lower() in GLOBAL_REFS:
        return None, True
    proj = b.resolve_project(ref, cwd)
    if not proj:
        die(f"projet introuvable : {ref} (voir `brain proj`)")
    return proj, True


def wiki_meta(a, meta):
    """--resume, --sources, --domaine (pages du wiki), --commun (cerveau commun) → champs de meta ; « none » les retire."""
    share = fold(getattr(a, "commun", None) or "")
    if share in ("oui", "yes", "partage", "partager", "public"):
        meta["partage"] = True
        meta.pop("prive", None)
    elif share in ("non", "no", "prive", "privee"):
        meta["prive"] = True
        meta.pop("partage", None)
    elif share == "auto":
        meta.pop("partage", None)
        meta.pop("prive", None)
    if getattr(a, "resume", None) is not None:
        if fold(a.resume) in ("none", "aucun", "-", ""):
            meta.pop("resume", None)
        else:
            meta["resume"] = " ".join(a.resume.split())
    if getattr(a, "sources", None) is not None:
        import re
        from .wikistore import links_in
        raw = a.sources.strip()
        if fold(raw) in ("none", "aucune", "-", ""):
            meta.pop("sources", None)
        else:  # « [[A]], [[B]] » ou « A, B »
            refs = [f"[[{t}]]" for t in (links_in(raw) or [x.strip() for x in re.split(r"[,;\n]", raw) if x.strip()])]
            meta["sources"] = list(dict.fromkeys(list(meta.get("sources") or []) + refs))
    if getattr(a, "domaine", None) is not None:
        doms = [slugify(x, 30) for x in a.domaine.split(",") if x.strip() and fold(x.strip()) not in ("none", "-")]
        if doms:
            meta["domaine"] = doms
        else:
            meta.pop("domaine", None)
    return meta


def node_line(n, chars=110):
    body = short((n.get("meta") or {}).get("resume") or n.get("body", ""), chars)  # page du wiki : son résumé d'abord
    arch = " (archivé)" if n.get("status", "active") != "active" else ""
    who = (n.get("meta") or {}).get("commun_par")
    return (f"[{TYPES.get(n['type'], n['type'])}{f' 🤝 {who}' if who else ''}] {n['title']}" + (f" — {body}" if body else "")
            + f"  `{n['id']}`{arch}")


# ================================================================================== mémoire
def cmd_q(a):
    from . import filesearch
    from .store import confidence
    text = " ".join(a.text)
    if a.at:
        from . import dates, history
        day = dates.parse(a.at)
        if not day:
            die(f"date illisible : « {a.at} » (ex. 15/10, hier, 2026-10-15)")
        data, label = history.state_at(day.replace("-", "") + "-235959")
        if data is None:
            die(f"pas d'état connu au {fmt_date(day)} : {label}")
        b = Brain(data)
        import datetime as _dt
        res = search.search_memories(b, text, limit=a.k, include_archived=False, expand=False, use_cache=False,
                                     fuse=True, today=_dt.date.fromisoformat(day))
        print(f"🕰️ Le cerveau tel qu'il était le {fmt_date(day)} (source : {label}, à 30 min près) :")
        if res and res[0].get("via") == "fiche":
            print(res.pop(0)["node"]["body"])
        for i, r in enumerate(res, 1):
            print(f"{i}. {node_line(r['node'], 220)}")
        if not res:
            print("Aucun souvenir correspondant à cette date.")
        return
    b = Brain.load()
    proj, _ = project_arg(b, a.project)
    if a.project is None:
        proj = b.project_for_path(os.getcwd())
    types = types_of(a.type)
    res = search.search_memories(b, text, limit=a.k, project=proj["id"] if proj else None, types=types,
                                 include_archived=a.archived, only_project=a.only, expand=False, fuse=True)
    fiche = res.pop(0) if res and res[0].get("via") == "fiche" else None  # question large : la fiche d'abord
    if res and not a.no_graph:  # traversée façon graphify : voisins explicites puis déduits des meilleurs résultats
        try:
            from . import graph
            res += graph.expand(b, graph.ensure(b), res, {r["node"]["id"] for r in res}, limit=3, types=types)
        except Exception as exc:
            log(f"q : expansion par le graphe : {exc!r}")
    if a.json:
        rows = [{"id": fiche["node"]["id"], "type": "fiche", "title": fiche["node"]["title"], "body": fiche["node"]["body"],
                 "members": fiche["fiche"]["members"], "via": "fiche"}] if fiche else []
        print(json.dumps(rows + [{"id": r["node"]["id"], "type": r["node"]["type"], "title": r["node"]["title"],
                                  "body": r["node"].get("body", ""), "project": r["node"].get("project"),
                                  "score": r["score"], "via": r.get("via")} for r in res], ensure_ascii=False, indent=1))
        return
    hidden = 0
    if fiche:
        from . import fiches
        print(fiche["node"]["body"])
        cited = fiches.cited(fiche["fiche"])
        hidden = sum(1 for r in res if r["node"]["id"] in cited)
        res = [r for r in res if r["node"]["id"] not in cited]  # déjà lus dans la fiche : pas deux fois
    if res:
        print(f"Souvenirs ({len(res)}" + (f", +{hidden} déjà dans la fiche" if hidden else "") + ") :")
        for i, r in enumerate(res, 1):
            n = r["node"]
            line = f"{i}. {node_line(n, 110 if fiche else 260)}"  # après une fiche : des renvois courts suffisent
            if n.get("project") and n["type"] != "project":
                line += f" · projet {n['project']}"
            via = r.get("via") or ""
            if via.startswith("lien"):
                line += f"  ← {via}"
            elif "date" in via:
                line += "  ← date"
            elif via:
                line += f"  (lié à {via})"
            if confidence(n) < 0.6:
                line += "  ≈ à vérifier"
            print(line)
        bump_hits([r["node"]["id"] for r in res if not r.get("via") or "texte" in r["via"]][:5])
    elif not fiche:
        print("Aucun souvenir correspondant.")
    try:
        from . import observations
        seen = observations.search(text, 3, project=proj["id"] if proj else None)
    except Exception as exc:
        log(f"q : observations : {exc!r}")
        seen = []
    if seen:
        print("\nObservations datées :")
        for o in seen:
            print(observations.line(o))
    sessions = _search_sessions(text, proj["id"] if proj and a.only else None)
    if sessions:
        print("\nSessions passées :")
        for s in sessions:
            print(journal.session_line(s) + (f"  [{s['project']}]" if s.get("project") else ""))
    if proj and not a.no_files:
        files = filesearch.search_files(proj["id"], text, 6)
        if files:
            print(f"\nFichiers du projet `{proj['id']}` :")
            for f in files:
                print(f"- {f['key']} — {short(f['desc'], 120)}")


def cmd_obs(a):
    """Observations datées de la session (mémoire épisodique) : noter, ou lister les dernières."""
    from . import observations
    b = Brain.load()
    proj, explicit = project_arg(b, a.project, os.getcwd())
    if not explicit:
        proj = b.project_for_path(os.getcwd())
    pid = proj["id"] if proj else None
    if a.text:
        added, skipped = observations.add(a.text, project=pid)
        why = f"{skipped} ignorée(s) (déjà notée ces 3 jours ou trop courte)"
        if not added:
            print(f"≈ rien de nouveau : {why}")
            return
        print(f"✓ {len(added)} observation(s) notée(s) le {fmt_date(added[0]['at'])}" + (f" · projet {pid}" if pid else "")
              + (f" · {why}" if skipped else ""))
        return
    items = observations.recent(a.n, pid if explicit else None, a.days)
    if not items:
        print(f"(aucune observation — en noter : `obs \"🔴 …\" \"🟡 …\"`)")
        return
    print(f"🗒️ Observations ({len(items)}, les plus récentes d'abord) :")
    for o in items:
        print(observations.line(o))


def cmd_fiche(a):
    """Fiches de synthèse des communautés (extractives, régénérées seulement quand un membre change)."""
    from . import fiches, graph
    b = Brain.load()
    an = graph.ensure(b)
    fs = fiches.ensure(b, an)
    items = list(fs.values())
    if not items:
        print(f"Aucune fiche : il faut des communautés d'au moins {fiches.MIN_SIZE} souvenirs.")
        return
    term = " ".join(a.name or []).strip()
    if not term:
        print(f"📋 {len(items)} fiche(s) de synthèse (une par communauté d'au moins {fiches.MIN_SIZE} souvenirs) :")
        for i, f in enumerate(items, 1):
            first = f["lines"][0]["t"] if f["lines"] else ""
            print(f"{i}. « {f['label']} » ({f['size']}) — {short(first, 110)}")
        print("→ `fiche <n°|mot|id>` pour en lire une.")
        return
    pick = items[int(term) - 1] if term.isdigit() and 1 <= int(term) <= len(items) else None
    if pick is None:
        n = b.get(term)
        pick = fs.get(an.get("comm", {}).get(n["id"])) if n else None
    if pick is None:
        index = search.Index((f["cid"], [(f["label"], 2.0), (" ".join(x["t"] for x in f["lines"]), 1.0),
                                         (" ".join(x["t"] for x in f["todo"]), 0.6)]) for f in items)
        hit = index.search(term, 1)
        pick = fs.get(hit[0]["key"]) if hit else None
    if pick is None:
        die(f"aucune fiche ne parle de « {term} » (`fiche` pour la liste)")
    print(fiches.text(pick))


def _search_sessions(text, project=None, limit=3):
    items = [s for s in journal.load()["sessions"].values() if project is None or s.get("project") == project]
    if not items:
        return []
    index = search.Index((s["id"], [(s.get("title") or "", 2.5), (s.get("first") or "", 1.0), (s.get("last") or "", 1.0),
                                    (s.get("answer") or "", 0.8)])
                         for s in items)
    by_id = {s["id"]: s for s in items}
    res = [r for r in index.search(text, limit) if r["matched"] >= min(2, r["nq"])]
    return [by_id[r["key"]] for r in res]


def cmd_add(a):
    from . import dates, graph
    body = body_of(a) or ""
    cwd = os.getcwd()
    try:
        ntype = normalize_type(a.type)
    except ValueError as exc:
        die(str(exc))
    due = dates.parse(a.due) if a.due else None
    if a.due and not due:
        die(f"échéance illisible : « {a.due} » (ex. 10/11, 10/11/2026, 3 novembre, demain, dans 2 semaines)")
    auto_tags = not a.tags
    tags = a.tags or clean_tags(graph.concept_tags(f"{a.title}\n{body}"))
    created = None
    with Brain.edit() as b:
        proj, explicit = project_arg(b, a.project, cwd)
        if not explicit:
            proj = None if ntype in ("user", "feedback") else b.project_for_path(cwd)
        pid = proj["id"] if proj else None
        from . import reconcile
        dec, why, node = None, [], True
        if not a.force and not a.replaces:
            dec = reconcile.decide(b, ntype, a.title, body, pid)  # mêmes règles que mem0 / Zep, sans LLM
            if dec["action"] == "merge":
                n = dec["target"]
                merged_body = n.get("body", "")
                if body and fold(body) not in fold(merged_body):
                    merged_body = f"{merged_body}\n{body}".strip()
                b.update(n["id"], body=merged_body, tags=list(n.get("tags", [])) + clean_tags(a.tags or []),
                         importance=max(n.get("importance", 3), a.importance or 3))
                b.adjust_confidence(n["id"], +0.1)  # redit : un peu plus sûr
                print(f"≈ déjà connu → complété dans `{n['id']}` ({n['title']}). `--force` pour créer un doublon.")
                node = None
            elif dec["action"] == "update":
                why = dec["why"]
        if node:
            meta = {"due": due} if due else {}
            if a.keys:
                meta["keys"] = " ".join(a.keys.split())
            wiki_meta(a, meta)
            node = b.add(ntype, a.title, body, tags=tags, project=pid, importance=a.importance or 3,
                         source=a.source, nid=a.id, meta=meta or None)
            created = node["id"]
            target = b.get(a.replaces) if a.replaces else (dec["target"] if dec and dec["action"] == "update" else None)
            if a.replaces and not target:
                print(f"(remplacement ignoré : `{a.replaces}` introuvable)")
            elif target and target["id"].startswith("c--"):
                print(f"(remplacement ignoré : `{target['id']}` est la page d'un ami, en lecture seule — la tienne est créée)")
                target = None
            if target and b.supersede(created, target["id"]):
                print(f"↻ remplace `{target['id']}` ({target['title']}" + (f" — {', '.join(why)}" if why else "")
                      + f") : archivé avec sa date de fin, consultable : `brain show {target['id']}`")
            elif dec:
                for s, m, value in reconcile.suggestions(dec):
                    print(f"↻ remplace peut-être `{m['id']}` ({m['title']} — {', '.join(value)}) → si oui : "
                          f"`brain supersede {created} {m['id']}`")
            for spec in a.link or []:
                target, _, rel = spec.partition(":")
                t = b.get(target)
                if t:
                    b.link(node["id"], t["id"], rel or "relates")
                else:
                    print(f"(lien ignoré : `{target}` introuvable)")
            near = [m for s, m in b.similar(a.title, body, None, exclude=node["id"], threshold=0.5)][:2]
            for m in near:
                b.link(node["id"], m["id"], "relates")
            extra = (f" · projet {pid}" if pid else " · global") + (
                " · lié à " + ", ".join(f"`{m['id']}`" for m in near) if near else "")
            due_txt = dates.due_of(node)
            print(f"✓ mémorisé `{node['id']}` [{TYPES[ntype]}]{extra}"
                  + (f" · échéance {dates.human(due_txt)}" if due_txt else "")
                  + (f" · étiquettes auto : {', '.join(tags)}" if auto_tags and tags else ""))
    refresh_views()
    if created:
        try:
            sug = [x for x in graph.inferred_of(graph.ensure(Brain.load()), created, 3) if x[2] != "faible"][:2]
            if sug:
                print("Liens suggérés : " + " · ".join(f"`{o}` ({', '.join(why)}) → `brain link {created} {o}`"
                                                        for o, w, conf, why in sug))
        except Exception as exc:
            log(f"add : suggestions : {exc!r}")


def cmd_supersede(a):
    with Brain.edit() as b:
        new, old = b.get(a.new), b.get(a.old)
        if not new or not old:
            die(f"introuvable : {a.new if not new else a.old}")
        if not b.supersede(new["id"], old["id"]):
            die("remplacement impossible (même souvenir ?)")
        print(f"✓ `{new['id']}` remplace `{old['id']}` — l'ancien est archivé (valable jusqu'à aujourd'hui), "
              f"toujours consultable : `brain show {old['id']}`")
    refresh_views()


def cmd_edit(a):
    with Brain.edit() as b:
        n = b.get(a.id)
        if not n:
            die(f"introuvable : {a.id}")
        fields = {}
        if a.title:
            fields["title"] = a.title
        body = body_of(a)
        if body is not None:
            fields["body"] = body
        if a.append:
            fields["body"] = f"{fields.get('body', n.get('body', ''))}\n{a.append}".strip()
        if a.type:
            fields["type"] = a.type
        if a.tags is not None:
            fields["tags"] = a.tags
        if a.add_tags:
            fields["tags"] = list(n.get("tags", [])) + clean_tags(a.add_tags)
        if a.importance:
            fields["importance"] = a.importance
        if a.project is not None:
            proj, _ = project_arg(b, a.project)
            fields["project"] = proj["id"] if proj else ""
        if a.unarchive:
            fields["status"] = "active"
        if a.due is not None:
            from . import dates
            meta = dict(n.get("meta") or {})
            if fold(a.due) in ("none", "aucune", "-"):
                meta.pop("due", None)
            else:
                d = dates.parse(a.due)
                if not d:
                    die(f"échéance illisible : « {a.due} »")
                meta["due"] = d
            fields["meta"] = meta
        if a.keys is not None:
            meta = dict(fields.get("meta") or n.get("meta") or {})
            if fold(a.keys) in ("none", "aucun", "-", ""):
                meta.pop("keys", None)
            else:
                meta["keys"] = " ".join(a.keys.split())
            fields["meta"] = meta
        if a.resume is not None or a.sources is not None or a.domaine is not None or a.commun is not None:
            fields["meta"] = wiki_meta(a, dict(fields.get("meta") or n.get("meta") or {}))
        if a.path:
            if n["type"] != "project":
                die("--path ne s'applique qu'à un projet")
            n.setdefault("meta", {})["path"] = os.path.abspath(a.path)
        if "body" in fields:
            (n.get("meta") or {}).pop("auto_body", None)
        try:
            b.update(n["id"], **fields)
        except ValueError as exc:
            die(str(exc))
        print(f"✓ modifié `{n['id']}`")
    refresh_views()


def cmd_rm(a):
    if a.purge:
        from . import history
        history.snapshot("avant-suppression", force=True)
    with Brain.edit() as b:
        n = b.get(a.id)
        if not n:
            die(f"introuvable : {a.id}")
        b.remove(n["id"], purge=a.purge)
        print(f"✓ {'supprimé définitivement' if a.purge else 'archivé'} `{n['id']}`"
              + ("" if a.purge else " (restaurable : `brain edit " + n["id"] + " --unarchive`)"))
    refresh_views()


def cmd_link(a):
    if a.suggest or not (a.a and a.b):
        from . import graph
        b = Brain.load()
        sug = [e for e in graph.ensure(b)["inferred"] if e["s"] in b.nodes and e["t"] in b.nodes][: a.n]
        if not sug:
            print("Aucun lien à suggérer.")
            return
        print("Liens suggérés (déduits du contenu) — pour en confirmer un : brain link <a> <b> [-r relation]")
        for e in sug:
            print(f"- `{e['s']}` ↔ `{e['t']}` · confiance {e['conf']} ({e['w']:.2f}) · {', '.join(e['why'])}")
        return
    with Brain.edit() as b:
        x, y = b.get(a.a), b.get(a.b)
        if not x or not y:
            die(f"introuvable : {a.a if not x else a.b}")
        if x["id"].startswith("c--") or y["id"].startswith("c--"):
            die("page d'un ami (cerveau commun) : pas de lien enregistré — cite-la dans ton texte ([[titre]])")
        ok = b.link(x["id"], y["id"], a.rel)
        print(f"✓ lien `{x['id']}` —{a.rel}→ `{y['id']}`" if ok else "(lien déjà présent)")
    refresh_views()


def cmd_unlink(a):
    with Brain.edit() as b:
        x, y = b.get(a.a), b.get(a.b)
        if not x or not y:
            die("souvenir introuvable")
        print(f"✓ {b.unlink(x['id'], y['id'], a.rel)} lien(s) retiré(s)")
    refresh_views()


def cmd_show(a):
    b = Brain.load()
    n = b.get(a.id)
    if not n:
        die(f"introuvable : {a.id} (essaie `brain q \"{a.id}\"`)")
    print(f"[{TYPES[n['type']]}] {n['title']}  `{n['id']}`" + ("  (archivé)" if n.get("status", "active") != "active" else ""))
    from .store import confidence
    meta = [f"importance {n.get('importance', 3)}/5", f"créé {fmt_date(n.get('created'))}", f"maj {fmt_date(n.get('updated'))}",
            f"montré {n.get('hits', 0)}× · utilisé {n.get('used', 0) or 0}×", f"source {n.get('source')}",
            f"confiance {confidence(n):.2f}"]
    if n.get("project"):
        meta.append(f"projet {n['project']}")
    if n.get("tags"):
        meta.append("tags " + ", ".join(n["tags"]))
    print(" · ".join(meta))
    if n["type"] == "project":
        m = n.get("meta") or {}
        has_map = (PROJECTS_DIR / n["id"] / "MAP.md").exists()
        print(f"chemin : {m.get('path')} · carte : {'✓ ' + fmt_date(m.get('mapped')) if has_map else 'aucune'}"
              + (f" · stack : {m['stack']}" if m.get("stack") else ""))
        members = sorted(b.project_members(n["id"]), key=lambda x: -priority(x))
        if members:
            print("souvenirs : " + " · ".join(f"`{x['id']}`" for x in members[:20]))
    m_ = n.get("meta") or {}
    if m_.get("superseded_by"):
        print(f"↻ remplacé par `{m_['superseded_by']}` — valable du {fmt_date(n.get('created'))} au {fmt_date(m_.get('valid_to'))}")
    olds = [e["to"] for e in b.edges if e["from"] == n["id"] and e["rel"] == "supersedes"]
    if olds:
        print("↻ remplace : " + ", ".join(f"`{o}`" for o in olds))
    if m_.get("keys"):
        print(f"mots-clés : {m_['keys']}")
    if n.get("body"):
        print("\n" + n["body"])
    if getattr(a, "history", False):
        from . import history
        vs = history.versions(n["id"])
        print(f"\nVersions ({len(vs)}) :")
        prev = None
        for day, hms, node in vs:
            when = "maintenant" if day == "maintenant" else f"{day[6:8]}/{day[4:6]} {hms[:2]}:{hms[2:4]}"
            if node is None:
                print(f"  {when} — absent" if prev else f"  {when} — pas encore créé")
            elif prev is None:
                print(f"  {when} — {node['title']} ({len(node.get('body', ''))} car.)")
            else:
                ch = [k for k, lab in (("title", "titre"), ("body", "contenu"), ("status", "statut"), ("importance", "importance"),
                                       ("tags", "étiquettes")) if node.get(k) != prev.get(k)]
                delta = len(node.get("body", "")) - len(prev.get("body", ""))
                print(f"  {when} — modifié : {', '.join(ch) or 'méta'}" + (f" ({delta:+d} car.)" if delta else "")
                      + (f" · {node.get('status')}" if "statut" in ch else ""))
            prev = node
    nb = b.neighbors(n["id"])
    if nb:
        print("\nLiens :")
        for m, rel, d in nb:
            print(f"  {d} {rel} `{m['id']}` — {m['title']}")
    if n.get("status", "active") == "active":
        try:
            from . import graph
            an = graph.ensure(b)
            c = graph.community_of(an, n["id"])
            inf = [(o, w, conf, why) for o, w, conf, why in graph.inferred_of(an, n["id"], 4) if o in b.nodes]
            if c is not None:
                print(f"\nCommunauté : {c['label']} ({c['size']} nœuds) · centralité {an['pr'].get(n['id'], 0):.2f}")
            cons = [x["label"] for x in an.get("concepts", []) if n["id"] in x["members"]]
            if cons:
                print("Concepts : " + ", ".join(cons[:12]))
            if inf:
                print("Liens déduits (suggestions, à confirmer avec `brain link a b`) :")
                for o, w, conf, why in inf:
                    print(f"  ≈ `{o}` — {b.nodes[o]['title']} · confiance {conf} ({', '.join(why)})")
        except Exception as exc:
            log(f"show : analyse du graphe : {exc!r}")
    bump_hits([n["id"]])


def cmd_ls(a):
    b = Brain.load()
    types = types_of(a.type)
    proj, _ = project_arg(b, a.project)
    nodes = [n for n in b.nodes.values()
             if (a.archived or n.get("status", "active") == "active") and (not types or n["type"] in types)
             and (not proj or n.get("project") == proj["id"] or n["id"] == proj["id"])]
    order = list(TYPES)
    nodes.sort(key=lambda n: (order.index(n["type"]), -priority(n)))
    for n in nodes[: a.n]:
        print(node_line(n))
    if len(nodes) > a.n:
        print(f"… {len(nodes) - a.n} de plus (-n {len(nodes)})")
    if not nodes:
        print("(vide)")


def cmd_proj(a):
    b = Brain.load()
    if a.action in (None, "ls"):
        seen = journal.last_seen_by_project()
        for p in sorted(b.projects(), key=lambda p: seen.get(p["id"], ""), reverse=True):
            m = p.get("meta") or {}
            ok = os.path.isdir(m.get("path", ""))
            has_map = (PROJECTS_DIR / p["id"] / "MAP.md").exists()
            print(f"- {p['title']} `{p['id']}` — {m.get('path')}{'' if ok else ' ⚠️ introuvable'} · "
                  f"{'carte ✓' if has_map else 'sans carte'} · {len(b.project_members(p['id']))} souvenirs"
                  + (f" · vu le {fmt_date(seen[p['id']])}" if p["id"] in seen else ""))
        if not b.projects():
            print("(aucun projet)")
        return
    if a.action == "add":
        if not a.target or not os.path.isdir(a.target):
            die("usage : brain proj add <dossier> [-T titre] [-b description]")
        with Brain.edit() as eb:
            node, created = eb.ensure_project(a.target, title=a.title, body=a.body or "", source="claude")
            if not created and (a.title or a.body):
                eb.update(node["id"], title=a.title, body=a.body)
        print(f"✓ projet `{node['id']}` {'créé' if created else 'déjà connu (mis à jour)'} — cartographie : `brain map \"{a.target}\"`")
        refresh_views()
        return
    if a.action == "show":
        cmd_show(argparse.Namespace(id=a.target))
        return
    die("actions : ls | add <dossier> | show <id>")


# ================================================================================== cartes de projets
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
    print("  Ensuite : `brain files \"sujet\"` · `brain where <symbole>` · `brain explain <fichier>`")


def cmd_where(a):
    from . import mapper
    _, m = map_for(a)
    print("\n".join(mapper.where(m, a.name, a.n)) or f"« {a.name} » introuvable dans la carte (essaie `brain files`)")


def cmd_deps(a):
    from . import mapper
    _, m = map_for(a)
    print("\n".join(mapper.deps(m, a.file)))


def cmd_explain(a):
    from . import mapper
    _, m = map_for(a)
    print("\n".join(mapper.explain(m, a.target)))


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
    print("\n".join(mapper.path_between(m, a.a, a.b)))


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


# ================================================================================== contexte, journal, entretien
def cmd_index(a):
    text = idx.rebuild(Brain.load())
    print(text if a.print else f"✓ BRAIN.md régénéré ({len(text)} car. ≈ {est_tokens(text)} tokens)")


def cmd_context(a):
    cwd = a.cwd or os.getcwd()
    text, ids, proj = idx.session_context(Brain.load(), cwd)
    print(text)
    print(f"\n--- injecté au démarrage ici : {len(text)} car. ≈ {est_tokens(text)} tokens · projet : "
          f"{proj['id'] if proj else 'aucun'} · {len(ids)} souvenirs référencés")


def cmd_recall(a):
    from . import hooks
    data = {"prompt": " ".join(a.text), "cwd": a.cwd or os.getcwd(), "session_id": None}
    buf = io.StringIO()
    saved = hooks.bump_hits
    hooks.bump_hits = lambda ids: None
    try:
        with contextlib.redirect_stdout(buf):
            hooks.on_prompt(data, load_config())
    finally:
        hooks.bump_hits = saved
    out = buf.getvalue()
    print(json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else "(rien ne serait injecté pour ce message)")


def cmd_journal(a):
    b = Brain.load()
    if a.search:
        hits = journal.search_transcripts(a.search, limit=a.n)
        if not hits:
            print("Rien trouvé dans les sessions passées.")
        for h in hits:
            print(f"- {fmt_date(h['date'])} « {short(h['title'], 60)} » ({h['count']}×) — … {h['snippet']} …"
                  + (f"  [{h['project']}]" if h.get("project") else ""))
        return
    if a.backfill:
        print(f"✓ {journal.backfill(b)} session(s) importée(s) dans le journal")
        refresh_views()
    proj, _ = project_arg(b, a.project)
    items = journal.recent(project=proj["id"] if proj else None, limit=a.n)
    for s in items:
        print(journal.session_line(s) + (f"  [{s['project']}]" if s.get("project") and not proj else ""))
    if not items:
        print("(journal vide)")


def cmd_consolidate(a):
    from . import history
    from .privacy import find as find_secrets
    dry = a.dry_run
    strict = getattr(a, "auto", False)  # mode automatique (fin de session) : seulement les fusions évidentes
    actions = []
    if not dry:
        history.snapshot("avant-consolidation", force=True)
    with Brain.edit() as b:
        for n in list(b.active(own=True)):
            leaks = find_secrets(f"{n['title']}\n{n.get('body', '')}")
            if leaks:
                actions.append(f"secret masqué dans `{n['id']}` : {', '.join(sorted(set(leaks)))}")
                if not dry:
                    b.update(n["id"], title=n["title"], body=n.get("body", ""))
        for e in list(b.edges):  # « A remplace B » : B est archivé (il reste consultable) — jamais une page d'ami
            if e["rel"] == "supersedes" and not e["to"].startswith("c--") and e["to"] in b.nodes \
                    and b.nodes[e["to"]].get("status", "active") == "active" \
                    and e["from"] in b.nodes and b.nodes[e["from"]].get("status", "active") == "active":
                actions.append(f"archivage (remplacé par `{e['from']}`) : `{e['to']}`")
                if not dry:
                    b.nodes[e["to"]]["status"] = "archived"
                    b.nodes[e["to"]].setdefault("meta", {})["superseded_by"] = e["from"]
                    b.dirty = True
        merged = set()
        for n in [x for x in b.active(own=True) if x["type"] != "project"]:
            if n["id"] in merged:
                continue
            for score, m in b.similar(n["title"], n.get("body", ""), n["type"], limit=5, threshold=0.9 if strict else 0.82,
                                      exclude=n["id"]):
                if m["id"] in merged:
                    continue
                keep, drop = (n, m) if priority(n) >= priority(m) else (m, n)
                actions.append(f"fusion : `{drop['id']}` → `{keep['id']}` (similarité {score})")
                merged.add(drop["id"])
                if not dry:
                    if drop.get("body") and fold(drop["body"]) not in fold(keep.get("body", "")):
                        keep["body"] = f"{keep.get('body', '')}\n{drop['body']}".strip()
                    keep["tags"] = clean_tags(keep.get("tags", []) + drop.get("tags", []))
                    keep["importance"] = max(keep.get("importance", 3), drop.get("importance", 3))
                    keep["hits"] = keep.get("hits", 0) + drop.get("hits", 0)
                    for e in b.edges:
                        if e["from"] == drop["id"]:
                            e["from"] = keep["id"]
                        if e["to"] == drop["id"]:
                            e["to"] = keep["id"]
                    drop["status"] = "archived"
                    drop.setdefault("meta", {})["merged_into"] = keep["id"]
                    b.dirty = True
                if drop is n:
                    break
        for n in list(b.active(own=True)):
            if (n["type"] in ("learning", "reference", "todo", "entity") and n.get("importance", 3) <= 2
                    and not n.get("hits") and days_since(n.get("updated")) > 180):
                actions.append(f"archivage (ancien, peu important, jamais rappelé) : `{n['id']}`")
                if not dry:
                    n["status"] = "archived"
                    b.dirty = True
        for n in b.active(("todo",), own=True):
            if days_since(n.get("updated")) > 45:
                actions.append(f"à vérifier (tâche de plus de 45 j) : `{n['id']}` {n['title']}")
        seen, clean = set(), []
        for e in b.edges:
            key = (e["from"], e["to"], e["rel"])
            if e["from"] not in b.nodes or e["to"] not in b.nodes or e["from"] == e["to"] or key in seen:
                continue
            seen.add(key)
            clean.append(e)
        if len(clean) != len(b.edges):
            actions.append(f"liens invalides/en double retirés : {len(b.edges) - len(clean)}")
            if not dry:
                b.data["edges"] = clean
                b.dirty = True
        for p in b.projects():
            path = (p.get("meta") or {}).get("path", "")
            if not os.path.isdir(path):
                actions.append(f"projet introuvable sur le disque : `{p['id']}` ({path}) → `brain edit {p['id']} --path …` "
                               f"ou `brain rm {p['id']}`")
    if not dry:
        refresh_views()
    if strict:
        log("consolidation auto : " + (" | ".join(actions) if actions else "rien à faire"))
        try:  # rêve : partie sûre appliquée, dossier du reste préparé pour un sous-agent
            from . import dream
            _, pending = dream.prepare(apply_safe=True)
            log(f"rêve préparé : {pending} point(s) à trancher")
        except Exception as exc:
            log(f"rêve : {exc!r}")
        return
    print("\n".join(actions) if actions else "✓ rien à consolider")
    if dry and actions:
        print("(simulation : relance sans --dry-run pour appliquer)")


def cmd_dream(a):
    from . import dream
    if a.done:
        dream.done()
        print("✓ rêve clos — le prochain se prépare tout seul (fin de session, une fois par jour)")
        return
    text, pending = dream.prepare(apply_safe=not a.no_apply)
    print(text)
    if not a.no_apply:
        refresh_views()


def cmd_export(a):
    if a.vault is not None:
        from . import vault, wikistore
        if wikistore.resolve()[0] != "classic":
            die(f"le cerveau vit déjà dans un wiki Markdown : ouvre {wikistore.resolve()[1]} comme coffre dans Obsidian "
                "(pas de coffre à synchroniser en plus)")
        path = a.vault or (load_config().get("vault") or {}).get("path")
        if not path:
            die("dossier du coffre ? ex. : export --vault \"D:\\Cerveau\" (retenu pour les fois suivantes)")
        try:
            rep = vault.sync(path, do_import=not a.push)
        except (RuntimeError, OSError) as exc:
            die(str(exc))
        set_config("vault.path", rep["root"])
        if rep["imported"] or rep["created"] or rep["archived"]:
            refresh_views()
        print(f"✓ Coffre à jour : {rep['root']} — {rep['notes']} notes · {rep['written']} écrite(s) · "
              f"{rep['removed']} retirée(s) · ouvrir ce dossier comme coffre dans Obsidian")
        for title, fields in rep["imported"]:
            print(f"  ↩ rapatrié d'Obsidian : « {title} » ({', '.join(fields)})")
        for title in rep["created"]:
            print(f"  ＋ nouvelle note importée : « {title} »")
        for title, nid in rep["archived"]:
            print(f"  🗄 archivé (note supprimée du coffre) : « {title} » — annuler : {CMD} edit {nid} --unarchive")
        for title, fields in rep["conflicts"]:
            print(f"  ⚠ conflit sur « {title} » ({', '.join(fields)}) : modifié des deux côtés, la version du cerveau "
                  f"(plus récente) est gardée")
        for title, other in rep["duplicates"]:
            print(f"  ≈ « {title} » ressemble à « {other} » : laissé dans « À trier »")
        for line in rep["kept"]:
            print(f"  · {line}")
        return
    idx.export(Brain.load())
    print(f"✓ {EXPORT_FILE}")


def cmd_viz(a):
    from . import viz
    path = viz.render(Brain.load())
    print(f"✓ {path} (vue 3D) · {VIZ2D_FILE} (vue 2D, fonctionne hors ligne)")
    if a.open:
        os.startfile(str(path)) if os.name == "nt" else print("(ouvre le fichier dans un navigateur)")


def cmd_stats(a):
    b = Brain.load()
    act = list(b.active())
    archived = len(b.nodes) - len(act)
    by_type = {t: sum(1 for n in act if n["type"] == t) for t in TYPES}
    mapped = sum(1 for p in b.projects() if (PROJECTS_DIR / p["id"] / "MAP.md").exists())
    sessions = len(journal.load()["sessions"])
    print(f"🧠 {len(act) - by_type['project']} souvenirs actifs ({archived} archivés) · {len(b.edges)} liens · "
          f"{by_type['project']} projets ({mapped} cartographiés) · {sessions} sessions au journal")
    print("Par type : " + " · ".join(f"{TYPES[t]} {c}" for t, c in by_type.items() if c))
    top = sorted((n for n in act if n.get("hits")), key=lambda n: -n["hits"])[:5]
    if top:
        print("Les plus rappelés : " + " · ".join(f"{n['title']} ({n['hits']}×)" for n in top))
    try:
        from . import graph
        an = graph.ensure(b)
        print(f"Graphe : {sum(1 for c in an['communities'] if c['size'] >= 2)} communautés · {len(an['inferred'])} liens "
              "déduits · nœuds clés : " + ", ".join(b.nodes[i]["title"] for i in an["key"][:3] if i in b.nodes))
        from . import fiches, observations
        od = observations.load()
        print(f"Fiches de synthèse : {len(fiches.ensure(b, an))} · observations datées : {len(od['obs'])} récentes, "
              f"{len(od['digests'])} résumé(s) de semaine")
    except Exception as exc:
        log(f"stats : analyse du graphe : {exc!r}")
    if INDEX_FILE.exists():
        text = INDEX_FILE.read_text(encoding="utf-8")
        print(f"Index injecté : {len(text)} car. ≈ {est_tokens(text)} tokens · graph.json "
              f"{GRAPH_FILE.stat().st_size // 1024 if GRAPH_FILE.exists() else 0} Ko")


def cmd_doctor(a):
    ok = lambda c, msg: print(("✓ " if c else "✗ ") + msg)  # noqa: E731
    if getattr(a, "fix", False):
        _doctor_fix()
    print(f"🧠 brain {__version__} — {BRAIN_DIR}")
    ok(sys.version_info >= (3, 9), f"Python {sys.version.split()[0]} ({sys.executable})")
    b = Brain.load()
    dangling = sum(1 for e in b.edges if e["from"] not in b.nodes or e["to"] not in b.nodes)
    ok((GRAPH_FILE.exists() or not b.nodes) and not dangling,  # cerveau neuf (ami) : pas encore de graph.json
       (f"graphe : {len(b.nodes)} nœuds, {len(b.edges)} liens" if b.nodes else "graphe : vide (aucun souvenir pour l'instant)")
       + (f", {dangling} liens cassés (→ consolidate)" if dangling else ""))
    if INDEX_FILE.exists():
        text = INDEX_FILE.read_text(encoding="utf-8")
        ok(True, f"index BRAIN.md : {len(text)} car. ≈ {est_tokens(text)} tokens")
    else:
        ok(False, "index BRAIN.md absent (→ brain index)")
    from . import wikistore
    mode, wroot = wikistore.resolve()
    if mode == "wiki":
        from . import wiki
        st = wikistore.stats(b.data)
        git_ok = wiki.is_repo(wroot)
        ok(True, f"wiki : {wroot} — {sum(st['types'].values())} pages, {st['archived']} archivées · "
                 + (f"git ({wiki.remote(wroot) or 'sans origin'})" if git_ok else "pas de dépôt git (→ git init)"))
        conflict = (wiki.read_json(wiki.SYNC_STATE, {}) or {}).get("conflict")
        if conflict:
            ok(False, f"wiki : synchronisation git en conflit depuis le {fmt_date(conflict)} (→ brain wiki status, git status)")
    elif mode == "missing":
        ok(False, f"wiki introuvable : {wroot} — le cerveau lit son cache sans écrire (→ rebrancher, ou config wiki.path)")
    from . import commun as _commun
    if _commun.member():
        ok(not _commun.state().get("conflict"), _commun.status(b).replace("\n", " · "))
    from .common import PLUGIN
    if PLUGIN:
        _doctor_plugin(ok)
    settings = CLAUDE_HOME / "settings.json"
    try:
        hooks = (json.loads(settings.read_text(encoding="utf-8")).get("hooks") or {}) if settings.exists() else {}
    except Exception:
        hooks = {}
    wanted = ("SessionStart", "UserPromptSubmit", "Stop", "PreCompact", "PostCompact", "SessionEnd")
    present = [ev for ev in wanted if "brain.py" in json.dumps(hooks.get(ev, []))]
    import re as _re
    exes = {m.group(1) for ev in wanted for h in hooks.get(ev, []) for x in h.get("hooks", [])
            for m in [_re.match(r'^"([^"]+\.exe)"', x.get("command", ""))] if m}
    missing = [e for e in exes if not os.path.exists(e)]
    if not PLUGIN:
        ok(not missing, "interpréteur des hooks : " + (", ".join(sorted(exes)) or "py -3")
           + (f" — INTROUVABLE (Python a changé de version ?) → brain install" if missing else ""))
        ok(len(present) == len(wanted), "hooks : " + (", ".join(present) or "aucun")
           + ("" if len(present) == len(wanted) else f" — manquants : {', '.join(e for e in wanted if e not in present)} (→ brain install)"))
        claude_md = CLAUDE_HOME / "CLAUDE.md"
        ok(claude_md.exists() and "BRAIN:START" in claude_md.read_text(encoding="utf-8", errors="replace"),
           "CLAUDE.md : bloc « cerveau »")
        ok((CLAUDE_HOME / "skills" / "brain" / "SKILL.md").exists(), "skill /brain")
        from .install import SKILL_MARK, skill_sources
        for name in skill_sources():
            there = (CLAUDE_HOME / "skills" / name / SKILL_MARK).exists()
            ok(there, f"skill métier /{name}" + ("" if there else " absente (→ brain install)"))
    elif present:
        ok(False, f"hooks du cerveau aussi dans settings.json ({', '.join(present)}) : en double avec le plugin "
                  f"(→ brain install --uninstall)")
    try:
        from . import graph
        an = graph.ensure(b)
        ok(True, f"analyse du graphe : {sum(1 for c in an['communities'] if c['size'] >= 2)} communautés, "
                 f"{len(an['inferred'])} liens déduits, {len(an['dups'])} doublon(s) possible(s)")
    except Exception as exc:
        ok(False, f"analyse du graphe : {exc!r}")
    ok(VIZ_FILE.exists(), f"visualisation 3D : {VIZ_FILE}" + ("" if VIZ_FILE.exists() else " absente (→ brain viz)"))
    from . import history
    from .privacy import find as find_secrets
    leaks = [n["id"] for n in b.active() if find_secrets(f"{n['title']}\n{n.get('body', '')}")]
    ok(not leaks, "aucun secret stocké" if not leaks else f"secrets détectés dans : {', '.join(leaks)} (→ brain consolidate les masque)")
    snaps = history.snapshots()
    ok(True, f"historique : {len(snaps)} instantané(s)" + (f", le dernier du {fmt_date(snaps[0].name[6:10] + '-' + snaps[0].name[10:12] + '-' + snaps[0].name[12:14])}" if snaps else ""))
    for p in b.projects():
        m = p.get("meta") or {}
        exists = os.path.isdir(m.get("path", ""))
        mp = PROJECTS_DIR / p["id"] / "map.json"
        age = f"carte de {fmt_date(m.get('mapped'))}" if mp.exists() else "pas de carte"
        ok(exists, f"projet `{p['id']}` : {m.get('path')} · {age}")
    ok(True, f"journal : {len(journal.load()['sessions'])} sessions")
    try:
        from . import fiches, observations
        od = observations.load()
        ok(True, f"fiches de synthèse : {len(fiches.ensure(b))} · observations datées : {len(od['obs'])} récentes, "
                 f"{len(od['digests'])} résumé(s) de semaine")
    except Exception as exc:
        ok(False, f"fiches / observations : {exc!r}")
    text, _, proj = idx.session_context(b, os.getcwd())
    ok(len(text) <= budget_chars(load_config()["inject"], "max_tokens"),
       f"injection au démarrage ici : {len(text)} car. ≈ {est_tokens(text)} tokens (projet : {proj['id'] if proj else 'aucun'})")
    import time as _time
    from .common import STATE_DIR, read_json
    pcfg, pcst = load_config().get("pc", {}), read_json(STATE_DIR / "pc.json", {}) or {}
    if os.name != "nt":
        ok(True, "veille PC : Windows seulement (inactive ici)")
    elif not pcfg.get("enabled", True):
        ok(True, "veille PC : désactivée (config pc.enabled)")
    else:
        last, lm = pcst.get("checked", 0), pcst.get("last") or {}
        when = _time.strftime("%d/%m %H:%M", _time.localtime(last)) if last else "pas encore (au prochain prompt)"
        ram = f" · RAM libre {lm['avail'] / (1 << 30):.1f} Go".replace(".", ",") if lm.get("avail") else ""
        stale = bool(last) and (_time.time() - last > 86400)
        ok(not stale, f"veille PC : {('dernière mesure ' + when) if last else when}{ram} · "
           f"{pcst.get('killed_total', 0)} serveur(s) MCP orphelin(s) fermé(s) au total"
           + (" · hooks inactifs depuis plus de 24 h ?" if stale else ""))
    if LOG_FILE.exists():
        errs = [l for l in LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines() if "ERREUR" in l][-3:]
        ok(not errs, "journal d'erreurs des hooks : " + ("vide" if not errs else " | ".join(short(e, 160) for e in errs)))


def cmd_backup(a):
    from . import backup
    if a.restore:
        try:
            n = backup.restore(a.restore)
        except Exception as exc:
            die(f"restauration impossible : {exc}")
        refresh_views()
        print(f"✓ cerveau restauré depuis {a.restore} ({n} nœuds) — l'état précédent est dans l'historique : `brain restore 1` pour annuler")
        return
    dest = a.to or backup.target_dir()
    if a.list:
        items = backup.backups(dest)
        print(f"Sauvegardes dans {dest} ({len(items)}) :" if items else f"Aucune sauvegarde dans {dest}.")
        for p in items[:20]:
            print(f"- {p.name} · {max(1, p.stat().st_size // 1024)} Ko")
        return
    try:
        path = backup.run(dest, force=not a.auto)
    except Exception as exc:
        if a.auto:
            log(f"sauvegarde auto : {exc!r}")
            return
        die(str(exc))
    if a.auto:
        log(f"sauvegarde auto : {path or 'déjà faite aujourd hui'}")
        return
    print(f"✓ sauvegarde : {path} ({max(1, path.stat().st_size // 1024)} Ko) — restaurer : `brain backup --restore \"{path}\"`")


def cmd_todo(a):
    from . import dates
    b = Brain.load()
    items = []
    for n in b.active(("todo",)):
        d = dates.due_of(n)
        items.append((dates.days_until(d) if d else 10 ** 6, n, d))
    if not items:
        print("Aucune tâche en cours.")
        return
    items.sort(key=lambda x: (x[0], x[1].get("created") or ""))
    print(f"À faire ({len(items)}) — terminer : `brain done <id>` · dater : `brain edit <id> --due 10/11`")
    for k, n, d in items:
        when = dates.human(d) if d else "sans échéance"
        flag = "⚠️ " if d and k < 0 else "⏰ " if d and k <= 3 else ""
        print(f"- {flag}[{when}] {n['title']} `{n['id']}`" + (f" · projet {n['project']}" if n.get("project") else ""))


def cmd_done(a):
    from .common import now_iso
    with Brain.edit() as b:
        n = b.get(a.id)
        if not n:
            die(f"introuvable : {a.id}")
        meta = dict(n.get("meta") or {})
        meta["done"] = now_iso()[:10]
        b.update(n["id"], status="archived", meta=meta)
        print(f"✓ terminé : {n['title']} `{n['id']}` (archivé — `brain edit {n['id']} --unarchive` pour le rouvrir)")
    refresh_views()


def cmd_bench(a):
    from . import bench
    print(bench.run(quick=a.quick))


def cmd_tokens(a):
    from . import tokens
    print(tokens.report(a.hours))


def cmd_optimize(a):
    from . import optimize
    if a.apply:
        print(optimize.apply())
    else:
        print(optimize.report(a.hours, show_all=a.all))


def cmd_history(a):
    from . import history
    if a.diff:
        p = history.find(a.diff)
        if not p:
            from . import dates
            day = dates.parse(a.diff)
            data, label = history.state_at(day.replace("-", "") + "-000000") if day else (None, "date illisible")
        else:
            data, label = history.load(p), p.name
        if data is None:
            die(f"instantané introuvable : {a.diff} ({label})")
        then = {k: v for k, v in data.get("nodes", {}).items() if v.get("status", "active") == "active"}
        cur = Brain.load()
        now = {n["id"]: n for n in cur.active()}
        added = [now[i] for i in now if i not in then]
        gone = [then[i] for i in then if i not in now]
        changed = [now[i] for i in now if i in then and (now[i]["title"], now[i].get("body", "")) != (then[i]["title"], then[i].get("body", ""))]
        print(f"Depuis {label} : {len(added)} ajouté(s) · {len(changed)} modifié(s) · {len(gone)} archivé(s) ou supprimé(s)")
        for lab, items in (("+", added), ("~", changed), ("-", gone)):
            for n in items[:12]:
                print(f"  {lab} {n['title']} `{n['id']}`")
        return
    snaps = history.snapshots()
    if not snaps:
        print("Aucun instantané pour l'instant (le premier est pris à la prochaine modification).")
        return
    print(f"Instantanés du cerveau ({len(snaps)}, du plus récent au plus ancien) — restaurer : `brain restore <n°>`")
    for i, p in enumerate(snaps[: a.n], 1):
        d = history.describe(p)
        day, hms, _, reason = history.parse(p)
        print(f"{i:3}. {day[6:8]}/{day[4:6]}/{day[:4]} {hms[:2]}:{hms[2:4]}:{hms[4:6]} · {reason:20} · "
              f"{d['active']} souvenirs actifs · {d['edges']} liens · {p.stat().st_size // 1024 or 1} Ko")


def cmd_pc(a):
    from . import pc
    if a.clean:
        print(pc.clean())
    elif a.history is not None:
        print(pc.history(a.history))
    else:
        print(pc.report(a.seconds, show_all=a.all))


def cmd_restore(a):
    from . import history
    from .store import replace_all
    path = history.find(a.ref)
    if not path:
        die(f"instantané introuvable : {a.ref} (voir `brain history`)")
    data = history.load(path)
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), dict):
        die("instantané illisible")
    before = history.snapshot("avant-restauration", force=True)
    try:
        replace_all(data)
    except RuntimeError as exc:
        die(str(exc))
    refresh_views()
    d = history.describe(path)
    print(f"✓ cerveau restauré depuis {path.name} ({d['active']} souvenirs actifs, {d['edges']} liens)"
          + (f" — l'état précédent est sauvegardé : `brain restore 1` pour annuler" if before else ""))


def _doctor_plugin(ok):
    """Contrôles propres au mode plugin : version, fichiers du plugin, lanceur stable, cerveau classique en double."""
    from . import plugin
    from .common import CODE_DIR
    ok(True, f"plugin « cerveau » {__version__} : {CODE_DIR}")
    need = [CODE_DIR / "hooks" / "hooks.json", CODE_DIR / ".mcp.json", CODE_DIR / "skills" / "brain" / "SKILL.md"]
    gone = [str(p.relative_to(CODE_DIR)) for p in need if not p.exists()]
    ok(not gone, "hooks, serveur MCP et skill du plugin" + (f" — manquants : {', '.join(gone)}" if gone else ""))
    if plugin.classic_install():
        ok(True, "cerveau classique présent dans ~/.claude/brain : le plugin s'efface (il ne fait rien)")
    else:
        plugin.ensure_launcher()
        ok((BRAIN_DIR / "brain.py").exists(), f"lanceur stable : {BRAIN_DIR / 'brain.py'}")


def _doctor_fix():
    """Réparation en une commande : hooks/CLAUDE.md/skill, index, caches, vue 3D, secrets, liens cassés, sauvegarde."""
    from . import backup, filesearch, install
    print("🔧 Réparation…")
    install.run()
    b = Brain.load()
    idx.rebuild(b)
    for p in b.projects():
        if (PROJECTS_DIR / p["id"] / "search.json").exists():
            filesearch.build_cache(p["id"])
    ns = argparse.Namespace(dry_run=False, auto=True)
    cmd_consolidate(ns)
    refresh_views()
    try:
        path = backup.run(force=True)
        print(f"✓ sauvegarde : {path}")
    except Exception as exc:
        print(f"✗ sauvegarde : {exc}")
    print("✓ index, caches de recherche, vue 3D et entretien refaits\n")


def cmd_wiki(a):
    """Le cerveau en wiki (« LLM Wiki ») : squelette et migration, sources, index, journal, santé, synchronisation."""
    from . import wiki, wikistore as ws
    act = fold(a.action or "status")
    if act == "init":
        if not a.args:
            die("dossier du wiki manquant : brain wiki init <dossier> (idéalement le clone d'un dépôt GitHub privé)")
        try:
            for line in wiki.init(a.args[0], migrate=not a.no_migrate, push=not a.no_push):
                print(line)
        except RuntimeError as exc:
            die(str(exc))
        refresh_views()
        return
    if act in ("status", "etat"):
        print(wiki.status())
        return
    if act in ("schema", "schéma"):
        print(wiki.schema_text())
        return
    root = ws.root()
    if not root:
        die("pas de wiki : `brain wiki init <dossier>` (le cerveau y migre ses souvenirs)"
            if ws.resolve()[0] == "classic" else f"wiki introuvable : {ws.resolve()[1]}")
    if act in ("add", "ingest", "ajoute", "ingere"):
        src = a.args[0] if a.args else "-"
        text = sys.stdin.read() if src == "-" else None
        if src == "-" and not (text or "").strip():
            die("rien reçu sur l'entrée standard (texte de la source) — ou : brain wiki add <fichier|url>")
        try:
            info = wiki.add_source(src, title=a.title, fmt=a.format, url=a.url, author=a.author, text=text)
        except RuntimeError as exc:
            die(str(exc))
        print(wiki.ingest_plan(info))
        wiki.write_index()
    elif act in ("pending", "attente"):
        b = Brain.load()
        items = wiki.pending(b.data, root)
        if not items:
            print("✓ aucune source en attente")
        for p in items[: a.n]:
            print(f"- {p['raw']} — page « {p['page']['title']} » à remplir" if p["page"]
                  else f"- {p['raw']} — `brain wiki add {p['raw']}`")
        if len(items) > a.n:
            print(f"- … +{len(items) - a.n}")
    elif act == "lint":
        b = Brain.load()
        rep = wiki.lint(b, root, limit=a.n)
        print(wiki.lint_text(rep))
        wiki.write_index(b, root)
        if a.log:
            wiki.log_append("lint", f"{sum(len(v) for v in rep.values())} point(s)",
                            [f"{k} : {len(v)}" for k, v in rep.items()], root=root)
    elif act == "index":
        print("✓ index.md régénéré" if wiki.write_index() else "✓ index.md déjà à jour")
    elif act in ("log", "journal"):
        if not a.args:
            rows = wiki.log_entries(root, a.n)
            print("\n".join(rows) if rows else "(journal vide)")
            return
        try:
            head = wiki.log_append(a.args[0], a.args[1] if len(a.args) > 1 else "", a.args[2:], root=root)
        except (RuntimeError, TimeoutError) as exc:
            die(str(exc))
        wiki.write_index()
        print(f"✓ {head}")
    elif act in ("sync", "synchro"):
        for line in wiki.sync(root, push=not a.no_push, pull=not a.no_pull, auto=a.auto):
            print(line)
        if a.auto and not a.no_pull:
            wiki.mark_pulled()
    else:
        die(f"action inconnue : {a.action} — init, add, pending, lint, index, log, status, sync, schema")


def cmd_boutique(a):
    """Boutiques en ligne suivies par le cerveau : fiche, plan daté, indicateurs de la semaine, audits, bilan."""
    from . import boutique
    act = fold(a.action or "liste")
    args = list(a.args or [])
    try:
        if act in ("liste", "list", "etat", "status"):
            lines = boutique.liste()
        elif act in ("ajouter", "add", "nouvelle", "creer"):
            if not args:
                die("nom manquant : brain boutique ajouter \"Nom\" [--url …] [--type …] [--chemin plateforme|0euro]")
            lines = boutique.ajouter(" ".join(args), url=a.url, plateforme=a.plateforme, chemin=a.chemin, type_=a.type,
                                     marge_commande=a.marge_commande)
        elif act in ("plan", "planifier"):
            lines = boutique.plan(args[0] if args else None, debut=a.debut, type_=a.type, court=a.court, force=a.force)
        elif act in ("kpi", "releve", "semaine", "chiffres"):
            lines = boutique.kpi(args[0] if args else None, sessions=a.sessions, ajouts=a.ajouts, commandes=a.commandes,
                                 ca=a.ca, checkouts=a.checkouts, heures=a.heures, marge=a.marge, canaux=a.canal or (),
                                 semaine=a.semaine, note=a.note)
        elif act in ("audit", "auditer"):
            pages = 10 if a.complet and not a.pages else (a.pages or 0)
            lines = boutique.audit(args[0] if args else None, timeout=a.timeout, legal=a.conformite or a.complet,
                                   pages=pages, vitesse=a.vitesse or a.complet, rapport=a.rapport)
        elif act in ("bilan", "revue", "point"):
            lines = boutique.bilan(args[0] if args else None, semaines=a.semaines, md=a.md)
        elif act in ("regler", "reglage", "set"):
            if len(args) < 2:
                die("brain boutique regler <boutique> cle=valeur … (url, plateforme, nom, chemin, type, marge, "
                    "seuil.sessions|ajout|paiement|panier_commande)")
            lines = boutique.regler(args[0], args[1:])
        else:
            die(f"action inconnue : {a.action} (liste, ajouter, plan, kpi, audit, bilan, regler)")
    except (LookupError, ValueError, RuntimeError) as exc:
        die(str(exc))
    for line in lines:
        print(line)
    if act in ("ajouter", "add", "nouvelle", "creer", "plan", "planifier"):
        refresh_views()


def cmd_commun(a):
    """Le cerveau commun : ce que chacun apprend nourrit le cerveau de tous, sans rien de privé."""
    from . import commun
    act = fold(a.action or "etat")
    try:
        if act in ("etat", "status"):
            print(commun.status())
        elif act in ("apercu", "preview"):
            print(commun.apercu_text(Brain.load()))
        elif act in ("rejoindre", "join"):
            for line in commun.join(nom=a.nom, oui=a.oui):
                print(line)
        elif act in ("non", "refuser", "decline"):
            print(commun.decline())
        elif act in ("quitter", "leave"):
            for line in commun.leave(keep=a.garder):
                print(line)
        elif act == "projet":
            if not a.args:
                die("projet manquant : brain commun projet <id> [--non]")
            print(commun.set_project(a.args[0], share=not a.non))
        elif act in ("sync", "synchro"):
            if a.delai and os.environ.get("BRAIN_COMMUN_FG") != "1":
                import time
                time.sleep(min(float(a.delai), 600))  # envoi différé (après un ajout) : les ajouts suivants partent avec
            for line in commun.sync(pull=True, push=not a.no_push, auto=a.auto):
                print(line)
        elif act in ("verifier", "check"):  # accès au dépôt commun (lancé en arrière-plan au démarrage)
            ok = commun.check_access(commun.repo_url(commun.settings().get("repo")))
            commun.save_state(access=ok, access_checked=now_iso())
            print("✓ accès au cerveau commun" if ok else "· pas (encore) d'accès au cerveau commun")
        elif act in ("liste", "list"):
            b = Brain.load()
            mine = [n for n in commun.preview(b)["shared"]]
            print(f"Ce que tu partages ({len(mine)}) :")
            for n in sorted(mine, key=lambda n: n["title"]):
                print(f"- {node_line(n, 80)}")
        else:
            die(f"action inconnue : {a.action} — etat, apercu, rejoindre, non, quitter, projet, sync, liste")
    except RuntimeError as exc:
        die(str(exc))


def cmd_import(a):
    from . import importer
    rep = importer.sync(force=a.force, dry=a.dry_run)
    if not rep:
        print("✓ mémoire native déjà synchronisée")
    for item in rep:
        print("- " + " ".join(str(x) for x in item))
    if rep and not a.dry_run:
        refresh_views()


def cmd_config(a):
    cfg = load_config()
    if not a.key:
        print(json.dumps(cfg, ensure_ascii=False, indent=1))
        print(f"(fichier : {CONFIG_FILE})")
        return
    if a.value is None:
        cur = cfg
        for k in a.key.split("."):
            cur = cur.get(k) if isinstance(cur, dict) else None
        print(json.dumps(cur, ensure_ascii=False))
        return
    try:
        value = json.loads(a.value)
    except json.JSONDecodeError:
        value = a.value
    set_config(a.key, value)
    print(f"✓ {a.key} = {json.dumps(value, ensure_ascii=False)}")


def cmd_hook(a):
    from . import hooks
    return hooks.run(a.event)


def cmd_mcp(a):
    from . import mcp_server
    return mcp_server.serve()


def cmd_publish(a):
    from . import publish
    sys.exit(publish.run(a.dir, owner=a.owner, repo=a.repo, push=a.push, check=not a.no_check))


def cmd_selfupdate(a):
    from . import selfupdate
    sys.exit(selfupdate.run(a.source, force=a.force, verify=not a.no_verify, dry_run=a.dry_run))


def cmd_install(a):
    if a.mcp:
        from . import mcp_server
        try:
            path, changed = mcp_server.register(dry=a.dry_run, remove=a.uninstall)
        except (RuntimeError, OSError, ValueError) as exc:
            die(str(exc))
        verb = "retiré de" if a.uninstall else "ajouté à"
        if not changed:
            print(f"✓ rien à faire : serveur MCP « cerveau » déjà {'absent de' if a.uninstall else 'présent dans'} {path}")
        elif a.dry_run:
            print(f"(simulation) le serveur MCP « cerveau » serait {verb} {path}")
        else:
            print(f"✓ serveur MCP « cerveau » {verb} {path} (copie de sauvegarde à côté) — redémarrer l'app Claude")
        return
    from . import install
    install.run(dry=a.dry_run, uninstall=a.uninstall)


# ================================================================================== parseur
def build_parser():
    p = argparse.ArgumentParser(prog="brain", description="🧠 Cerveau persistant de Claude : mémoire en graphe + "
                                "cartes de projets (façon graphify) + hooks d'injection automatique.",
                                epilog=f"Exemples : {CMD} q \"shopify robots\" · {CMD} add -t learning -T \"…\" -b \"…\" · "
                                       f"{CMD} map . · {CMD} where login")
    p.add_argument("--version", action="version", version=f"brain {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="<commande>")

    def cmd(name, func, help_, aliases=()):
        sp = sub.add_parser(name, aliases=list(aliases), help=help_)
        sp.set_defaults(func=func)
        return sp

    s = cmd("q", cmd_q, "chercher dans la mémoire (+ sessions passées et fichiers du projet courant)", ["query", "search", "cherche"])
    s.add_argument("text", nargs="+")
    s.add_argument("-k", type=int, default=8, help="nombre de résultats")
    s.add_argument("-p", "--project", help="projet (id/nom/chemin, « . » = courant)")
    s.add_argument("-t", "--type", help="types séparés par des virgules")
    s.add_argument("--only", action="store_true", help="seulement le projet")
    s.add_argument("--no-files", action="store_true")
    s.add_argument("--archived", action="store_true")
    s.add_argument("--json", action="store_true")
    s.add_argument("--no-graph", action="store_true", help="sans les voisins (explicites et déduits) du graphe")
    s.add_argument("--at", help="chercher dans le cerveau tel qu'il était à une date (15/10, hier…)")

    s = cmd("add", cmd_add, "mémoriser (anti-doublon automatique)", ["save", "retiens"])
    s.add_argument("-t", "--type", default="learning", help=f"type : {', '.join(TYPES)} (défaut learning)")
    s.add_argument("-T", "--title", required=True)
    s.add_argument("-b", "--body", help="contenu (« - » = lire stdin)")
    s.add_argument("--body-file")
    s.add_argument("--tags", type=lambda v: clean_tags(v))
    s.add_argument("-p", "--project", help="projet (défaut : projet courant, sauf user/feedback) ; « none » = global")
    s.add_argument("-i", "--importance", type=int, default=3, help="1 à 5 (défaut 3)")
    s.add_argument("--link", action="append", help="id[:relation] (répétable)")
    s.add_argument("--id")
    s.add_argument("--source", "--src", dest="source", default="claude",
                   help="provenance : utilisateur (dit par l'utilisateur ; « lucas » accepté), verifie, claude (défaut), deduit")
    s.add_argument("--keys", help="mots-clés, synonymes, questions types (indexés, pour retrouver le souvenir autrement)")
    s.add_argument("--force", action="store_true", help="créer même si un souvenir quasi identique existe")
    s.add_argument("--due", help="échéance (10/11, 10/11/2026, 3 novembre, demain, dans 2 semaines)")
    s.add_argument("--replaces", "--supersede", dest="replaces", help="id du souvenir que celui-ci remplace (l'ancien est archivé)")
    s.add_argument("--resume", help="page du wiki : une phrase qui dit l'essentiel (index, rappel)")
    s.add_argument("--commun", choices=["oui", "non", "auto"], help="cerveau commun : oui = partager, non = garder privé, "
                                                                 "auto = règles par défaut")
    s.add_argument("--sources", help="page du wiki : pages Sources qui l'appuient (« [[Titre]], [[Autre]] »)")
    s.add_argument("--domaine", help="page du wiki : domaines séparés par des virgules (business, recherche, perso, lecture…)")
    s = cmd("supersede", cmd_supersede, "« nouveau » remplace « ancien » : l'ancien est archivé avec sa date de fin", ["remplace"])
    s.add_argument("new")
    s.add_argument("old")

    s = cmd("edit", cmd_edit, "modifier un souvenir", ["maj"])
    s.add_argument("id")
    s.add_argument("-T", "--title")
    s.add_argument("-b", "--body")
    s.add_argument("--body-file")
    s.add_argument("-a", "--append", help="ajouter du texte à la fin")
    s.add_argument("-t", "--type")
    s.add_argument("--tags", type=lambda v: clean_tags(v))
    s.add_argument("--add-tags")
    s.add_argument("-i", "--importance", type=int)
    s.add_argument("-p", "--project")
    s.add_argument("--path", help="nouveau chemin (projets)")
    s.add_argument("--unarchive", action="store_true")
    s.add_argument("--due", help="échéance (« none » pour l'enlever)")
    s.add_argument("--keys", help="mots-clés indexés (« none » pour les enlever)")
    s.add_argument("--resume", help="page du wiki : son résumé (« none » pour l'enlever)")
    s.add_argument("--commun", choices=["oui", "non", "auto"], help="cerveau commun : oui = partager, non = garder privé, "
                                                                 "auto = règles par défaut")
    s.add_argument("--sources", help="page du wiki : pages Sources à ajouter (« [[Titre]] » ; « none » pour vider)")
    s.add_argument("--domaine", help="page du wiki : domaines (« none » pour les enlever)")

    s = cmd("rm", cmd_rm, "archiver un souvenir (--purge = supprimer définitivement)", ["archive"])
    s.add_argument("id")
    s.add_argument("--purge", action="store_true")

    s = cmd("link", cmd_link, "relier deux souvenirs (--suggest : liens déduits à confirmer)")
    s.add_argument("a", nargs="?")
    s.add_argument("b", nargs="?")
    s.add_argument("-r", "--rel", default="relates")
    s.add_argument("--suggest", action="store_true", help="lister les liens déduits du contenu")
    s.add_argument("-n", type=int, default=12)
    s = cmd("unlink", cmd_unlink, "retirer un lien")
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("-r", "--rel")

    s = cmd("show", cmd_show, "afficher un souvenir et ses liens (--history : ses versions)", ["voir"])
    s.add_argument("id")
    s.add_argument("--history", action="store_true", help="versions successives (instantanés)")
    s = cmd("ls", cmd_ls, "lister", ["list"])
    s.add_argument("-t", "--type")
    s.add_argument("-p", "--project")
    s.add_argument("-n", type=int, default=60)
    s.add_argument("--archived", action="store_true")

    s = cmd("proj", cmd_proj, "projets : ls | add <dossier> | show <id>", ["projects", "projet"])
    s.add_argument("action", nargs="?")
    s.add_argument("target", nargs="?")
    s.add_argument("-T", "--title")
    s.add_argument("-b", "--body")

    s = cmd("map", cmd_map, "cartographier un projet (incrémental) façon graphify", ["carte"])
    s.add_argument("path", nargs="?")
    s.add_argument("-p", "--project")
    s.add_argument("--full", action="store_true", help="tout ré-analyser (ignore le cache)")
    s.add_argument("--quiet", action="store_true")
    s.add_argument("--bg", action="store_true", help="en arrière-plan")
    s.add_argument("--max-files", type=int)

    s = cmd("where", cmd_where, "où est défini un symbole (fonction, classe, variable d'env, route)", ["ou"])
    s.add_argument("name")
    s.add_argument("-p", "--project")
    s.add_argument("-n", type=int, default=30)
    s = cmd("deps", cmd_deps, "imports et importeurs d'un fichier")
    s.add_argument("file")
    s.add_argument("-p", "--project")
    s = cmd("explain", cmd_explain, "fiche d'un fichier ou d'un symbole", ["explique"])
    s.add_argument("target")
    s.add_argument("-p", "--project")
    s = cmd("path", cmd_path, "chemin entre deux souvenirs (graphe de mémoire) ou deux fichiers (imports)", ["chemin"])
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("-p", "--project")
    s = cmd("files", cmd_files, "trouver les fichiers liés à un sujet", ["fichiers"])
    s.add_argument("text", nargs="+")
    s.add_argument("-p", "--project")
    s.add_argument("-n", type=int, default=10)

    s = cmd("index", cmd_index, "régénérer l'index BRAIN.md")
    s.add_argument("--print", action="store_true")
    s = cmd("context", cmd_context, "voir ce qui est injecté au démarrage d'une session ici")
    s.add_argument("--cwd")
    s = cmd("recall", cmd_recall, "tester le rappel automatique pour un message")
    s.add_argument("text", nargs="+")
    s.add_argument("--cwd")
    s = cmd("journal", cmd_journal, "sessions passées (--backfill : importer l'historique)")
    s.add_argument("-p", "--project")
    s.add_argument("-n", type=int, default=12)
    s.add_argument("--backfill", action="store_true")
    s.add_argument("-s", "--search", help="chercher dans le texte des sessions passées")
    s = cmd("todo", cmd_todo, "à-faire triés par échéance", ["taches"])
    s = cmd("done", cmd_done, "marquer un à-faire comme terminé", ["fait"])
    s.add_argument("id")
    s = cmd("consolidate", cmd_consolidate, "fusionner les doublons, archiver l'obsolète et le remplacé, masquer les secrets")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)
    s = cmd("dream", cmd_dream, "rêve : entretien hors conversation (dossier REVE.md : conflits, doublons, corrections "
                               "entendues…) — --done pour le clore", ["reve"])
    s.add_argument("--done", action="store_true", help="marquer le rêve comme traité")
    s.add_argument("--no-apply", action="store_true", help="ne rien appliquer, seulement préparer le dossier")
    s = cmd("backup", cmd_backup, "sauvegarde hors du disque système (D:, E:…) — --list, --restore <archive>", ["sauvegarde"])
    s.add_argument("--to", help="dossier de sauvegarde (défaut : D:\\Sauvegardes-cerveau-Claude ou équivalent)")
    s.add_argument("--list", action="store_true")
    s.add_argument("--restore", help="archive .zip à restaurer")
    s.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)
    s = cmd("bench", cmd_bench, "banc d'essai : qualité du rappel, faux rappels, tokens, vitesse des hooks")
    s.add_argument("--quick", action="store_true", help="sans la mesure de vitesse")
    s = cmd("tokens", cmd_tokens, "où partent les tokens : contexte relu, 1res requêtes, habitudes coûteuses (transcripts)")
    s.add_argument("--hours", type=float, default=48, help="période mesurée (défaut 48 h)")
    s = cmd("optimize", cmd_optimize, "optimiser le cerveau (tokens d'abord) : coût réel de l'injection/du rappel/du "
            "corpus + ce qu'on peut alléger — --apply applique le sûr et réversible", ["optimise", "opti"])
    s.add_argument("--apply", action="store_true", help="appliquer les actions sûres et réversibles (ménage du corpus, rappel d'habitude)")
    s.add_argument("--all", action="store_true", help="tout détailler, sans troncature")
    s.add_argument("--hours", type=float, default=48, help="période mesurée pour l'habitude la plus coûteuse (défaut 48 h)")
    s = cmd("history", cmd_history, "instantanés du cerveau (pour revenir en arrière) — --diff <n°|date>", ["historique"])
    s.add_argument("-n", type=int, default=15)
    s.add_argument("--diff", help="ce qui a changé depuis un instantané (n°) ou une date")
    s = cmd("restore", cmd_restore, "restaurer un instantané (n° de `history` ou date) — réversible", ["restaurer"])
    s.add_argument("ref")
    s = cmd("export", cmd_export, "écrire MEMOIRES.md — ou --vault <dossier> : coffre Obsidian synchronisé dans les deux sens")
    s.add_argument("--vault", nargs="?", const="", help="dossier du coffre (retenu pour les fois suivantes)")
    s.add_argument("--push", action="store_true", help="écraser le coffre avec le cerveau, sans rapatrier les modifications")
    s = cmd("concept", cmd_concept, "concepts repérés (outils, sujets, sigles…) et les souvenirs qui en parlent", ["concepts"])
    s.add_argument("name", nargs="*")
    s = cmd("fiche", cmd_fiche, "fiches de synthèse des communautés (« où en est … ») : liste, ou fiche <n°|mot|id>",
            ["fiches", "synthese"])
    s.add_argument("name", nargs="*")
    s = cmd("obs", cmd_obs, "observations datées de la session : obs \"🔴 …\" \"🟡 …\" \"🟢 …\" (sans texte : les dernières)",
            ["observe", "observations"])
    s.add_argument("text", nargs="*", help="une observation par argument ; 🔴/🟡/🟢 (ou !!!/!!/!) et « 14:20 » en tête au besoin")
    s.add_argument("-p", "--project", help="projet (défaut : projet courant) ; « none » = global")
    s.add_argument("-n", type=int, default=15)
    s.add_argument("--days", type=int, help="seulement les N derniers jours")
    s = cmd("report", cmd_report, "rapport façon graphify : communautés, nœuds clés, liens surprenants, trous", ["rapport"])
    s.add_argument("--print", action="store_true", help="afficher le rapport complet")
    s.add_argument("--force", action="store_true", help="recalculer l'analyse")
    s = cmd("viz", cmd_viz, "générer cerveau.html (graphe 3D interactif) et cerveau-2d.html")
    s.add_argument("--open", action="store_true")
    s = cmd("pc", cmd_pc, "RAM/CPU/GPU + ce qu'on peut libérer (sessions, serveurs MCP) — --clean, --history, --all", ["ram"])
    s.add_argument("--all", action="store_true", help="tout détailler, sans troncature")
    s.add_argument("--clean", action="store_true", help="fermer maintenant les serveurs MCP orphelins (parent mort)")
    s.add_argument("--history", nargs="?", type=float, const=24, metavar="H",
                   help="historique des mesures de la veille sur H heures (défaut 24)")
    s.add_argument("--seconds", type=float, default=2.0, help="durée de mesure du CPU/GPU (défaut 2 s)")
    cmd("stats", cmd_stats, "statistiques")
    s = cmd("doctor", cmd_doctor, "diagnostic complet de l'installation (--fix : tout réparer)")
    s.add_argument("--fix", action="store_true", help="réinstaller, reconstruire, nettoyer et sauvegarder")
    s = cmd("wiki", cmd_wiki, "le cerveau en wiki (LLM Wiki, coffre Obsidian, dépôt git) : init <dossier> · add <fichier|url|-> · "
            "pending · lint · index · log [op titre lignes…] · status · sync · schema")
    s.add_argument("action", nargs="?", help="init, add, pending, lint, index, log, status (défaut), sync, schema")
    s.add_argument("args", nargs="*", help="init : dossier · add : fichier, url ou « - » (stdin) · log : opération titre lignes…")
    s.add_argument("-T", "--title", help="add : titre de la source")
    s.add_argument("--url", help="add : adresse d'origine (texte reçu par stdin)")
    s.add_argument("--format", help="add : article, pdf, video, podcast, livre, note, conversation, donnees, image, document")
    s.add_argument("--author", "--auteur", dest="author", help="add : auteur")
    s.add_argument("-n", type=int, default=12, help="nombre de lignes (lint, pending, log)")
    s.add_argument("--log", action="store_true", help="lint : noter le passage au journal")
    s.add_argument("--no-migrate", action="store_true", help="init : ne pas migrer le cerveau classique")
    s.add_argument("--no-push", action="store_true", help="init/sync : ne pas envoyer sur GitHub")
    s.add_argument("--no-pull", action="store_true", help="sync : ne pas récupérer")
    s.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)
    s = cmd("boutique", cmd_boutique, "boutiques en ligne suivies (données privées) : liste · ajouter \"Nom\" · plan · "
            "kpi (semaine) · audit · bilan · regler", ["boutiques", "shop"])
    s.add_argument("action", nargs="?", help="liste (défaut), ajouter, plan, kpi, audit, bilan, regler")
    s.add_argument("args", nargs="*", help="la boutique (slug ou nom) ; ajouter : son nom ; regler : cle=valeur …")
    s.add_argument("--url", help="ajouter : adresse de la boutique")
    s.add_argument("--plateforme", help="ajouter : shopify, woocommerce, prestashop, site statique, marketplace…")
    s.add_argument("--chemin", help="ajouter : plateforme (abonnement accepté) ou 0euro (aucun coût fixe)")
    s.add_argument("--type", help="physique, mode, createur, occasion, niche, prevente, local, numerique, b2b")
    s.add_argument("--marge-commande", dest="marge_commande", help="marge de contribution par commande (€)")
    s.add_argument("--debut", help="plan : premier jour (défaut aujourd'hui ; demain, 20/10…)")
    s.add_argument("--court", action="store_true", help="plan : 72 h et 14 jours seulement")
    s.add_argument("--force", action="store_true", help="plan : recréer (l'ancien plan ouvert est archivé)")
    s.add_argument("--sessions", help="kpi : visites de la semaine")
    s.add_argument("--ajouts", help="kpi : sessions avec ajout au panier")
    s.add_argument("--checkouts", help="kpi : paiements commencés")
    s.add_argument("--commandes", help="kpi : commandes")
    s.add_argument("--ca", help="kpi : chiffre d'affaires TTC de la semaine (€)")
    s.add_argument("--heures", help="kpi : heures passées sur la boutique dans la semaine")
    s.add_argument("--marge", help="kpi : marge de contribution totale de la semaine (sinon : commandes × marge par commande)")
    s.add_argument("--canal", action="append", help="kpi : nom:sessions:commandes[:heures] (répétable)")
    s.add_argument("--semaine", help="kpi : une date de la semaine (défaut : la dernière semaine complète)")
    s.add_argument("--note", help="kpi : ce qui s'est passé (lancement, vidéo virale, rupture…)")
    s.add_argument("--semaines", type=int, default=4, help="bilan : semaines affichées (défaut 4)")
    s.add_argument("--md", help="bilan : écrire aussi le bilan dans ce fichier Markdown")
    s.add_argument("--timeout", type=float, default=20.0, help="audit : délai par requête (s)")
    s.add_argument("--conformite", action="store_true", help="audit : pages légales et points de conformité")
    s.add_argument("--pages", type=int, help="audit : nombre de pages du sitemap à lire (doublons, erreurs, noindex)")
    s.add_argument("--vitesse", action="store_true", help="audit : Core Web Vitals (PageSpeed Insights, mobile)")
    s.add_argument("--complet", action="store_true", help="audit : conformité + 10 pages + vitesse")
    s.add_argument("--rapport", help="audit : écrire aussi le rapport dans ce fichier Markdown")
    s = cmd("commun", cmd_commun, "cerveau commun avec les amis (jamais rien de privé) : etat · apercu · rejoindre --oui · "
            "non · quitter · projet <id> · sync · liste", ["partage"])
    s.add_argument("action", nargs="?", help="etat (défaut), apercu, rejoindre, non, quitter, projet, sync, liste")
    s.add_argument("args", nargs="*")
    s.add_argument("--oui", action="store_true", help="rejoindre : accord donné (sinon : aperçu seulement)")
    s.add_argument("--nom", help="rejoindre : pseudo affiché aux amis")
    s.add_argument("--garder", action="store_true", help="quitter : laisser tes pages aux amis")
    s.add_argument("--non", action="store_true", help="projet : le rendre de nouveau privé")
    s.add_argument("--no-push", action="store_true", help="sync : récupérer seulement")
    s.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)
    s.add_argument("--delai", type=float, help=argparse.SUPPRESS)
    s = cmd("import", cmd_import, "importer la mémoire native de Claude Code (~/.claude/projects/*/memory)")
    s.add_argument("--force", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s = cmd("config", cmd_config, "lire/modifier la configuration (ex : config recall.enabled false)")
    s.add_argument("key", nargs="?")
    s.add_argument("value", nargs="?")
    s = cmd("hook", cmd_hook, "point d'entrée des hooks Claude Code (usage interne)")
    s.add_argument("event", choices=["session-start", "prompt", "stop", "pre-compact", "post-compact", "session-end"])
    s = cmd("install", cmd_install, "installer/réparer : CLAUDE.md, skill /brain, hooks (--mcp : serveur MCP de l'app)")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--uninstall", action="store_true")
    s.add_argument("--mcp", action="store_true", help="enregistrer le serveur MCP « cerveau » dans l'app Claude (chat, Cowork)")
    cmd("mcp", cmd_mcp, "serveur MCP (stdio) : la même mémoire dans le chat Claude, Cowork ou tout client MCP")
    s = cmd("publish", cmd_publish, "publier le plugin Claude Code « cerveau » pour les amis (code seul, jamais les "
                                    "souvenirs) dans le clone du dépôt GitHub", ["publier"])
    s.add_argument("dir", nargs="?", help="clone local du dépôt (retenu ensuite)")
    s.add_argument("--repo", help="dépôt GitHub « proprietaire/depot » (retenu ensuite)")
    s.add_argument("--owner", help="nom affiché de l'auteur (défaut : Lucas)")
    s.add_argument("--push", action="store_true", help="envoyer sur GitHub après le commit (publication)")
    s.add_argument("--no-check", action="store_true", help="sans validation ni essai chez un ami fictif")
    s = cmd("self-update", cmd_selfupdate, "déployer le code (brain.py, brainkit/, tests/, skills métier) de l'arbre "
            "de développement vers ~/.claude/brain : sauvegarde, vérifie, revient en arrière si besoin — jamais les "
            "données (souvenirs, config…)", ["autodeploy", "deploy", "maj-code"])
    s.add_argument("source", nargs="?", help="dossier de l'arbre de développement (retenu ensuite)")
    s.add_argument("--force", action="store_true", help="déployer même une version plus ancienne, identique, ou qui retire des fichiers")
    s.add_argument("--no-verify", action="store_true", help="ne pas lancer la suite de tests après la copie")
    s.add_argument("--dry-run", action="store_true", help="montrer ce qui serait fait, sans rien toucher")
    return p


def main(argv=None):
    setup_io()
    if os.environ.get("BRAIN_BG") == "1":  # tâche de fond lancée par un hook : CPU/disque/mémoire en priorité basse
        try:
            from . import pc
            pc.background_mode()
        except Exception as exc:
            log(f"mode arrière-plan : {exc!r}")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    from .store import ReadOnly
    from .wikistore import WikiMissing
    try:
        return args.func(args) or 0
    except KeyboardInterrupt:
        return 130
    except TimeoutError as exc:
        die(f"{exc} — une autre session écrit dans le cerveau, réessaie.")
    except WikiMissing as exc:  # wiki débranché ou déplacé : rien n'est écrit, le cache reste lisible
        die(str(exc))
    except ReadOnly as exc:  # page d'un ami (cerveau commun)
        die(str(exc))
