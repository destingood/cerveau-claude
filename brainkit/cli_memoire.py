"""Commandes de la mémoire : chercher, mémoriser, modifier, relier, lister, projets, à-faire, et ce qui est injecté
(index, contexte, rappel, journal des sessions).

Découpé de cli.py (étape 8 du plan) sans rien changer : le parseur et main() restent dans cli.py, qui ne charge ce
module qu'au moment d'en lancer une commande."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os

from . import index as idx
from . import journal, search
from .cli_commun import body_of, die, node_line, project_arg, refresh_views, types_of, wiki_meta
from .common import PROJECTS_DIR, est_tokens, fmt_date, fold, load_config, log, now_iso, short, slugify
from .store import TYPES, Brain, bump_hits, clean_tags, normalize_type, priority


def cmd_q(a):
    from . import common, filesearch
    from .store import confidence
    common.LAZY = True  # analyse du graphe : celle en cache, même périmée (refaite en arrière-plan), jamais 1 à 4 s ici
    text = " ".join(a.text)
    if a.at:
        from . import dates, history
        day = dates.parse(a.at, nearest=True)  # « --at 15/10 » : le 15/10 le plus proche, pas celui de l'an prochain
        if not day:
            die(f"date illisible : « {a.at} » (ex. 15/10, hier, 2026-10-15)")
        data, label = history.state_at(day.replace("-", "") + "-235959")
        rebuilt = data is None  # avant le premier instantané gardé (ou aucun) : reconstruit d'après les dates
        if rebuilt:
            from . import temps
            data = temps.state_on(Brain.load().data, day)
        b = Brain(data)
        import datetime as _dt
        res = search.search_memories(b, text, limit=a.k, include_archived=False, expand=False, use_cache=False,
                                     fuse=True, today=_dt.date.fromisoformat(day))
        print(f"🕰️ Le cerveau tel qu'il était le {fmt_date(day)} " + (
            f"(reconstruit d'après les dates ; le texte des souvenirs est celui d'aujourd'hui — {label}) :" if rebuilt
            else f"(source : {label}, à 30 min près) :"))
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
        print("(aucune observation — en noter : `obs \"🔴 …\" \"🟡 …\"`)")
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
    items = [s for s in journal.all_sessions() if project is None or s.get("project") == project]
    if not items:
        return []
    index = search.Index((s["id"], [(s.get("title") or "", 2.5), (s.get("first") or "", 1.0), (s.get("last") or "", 1.0),
                                    (s.get("answer") or "", 0.8)])
                         for s in items)
    by_id = {s["id"]: s for s in items}
    res = [r for r in index.search(text, limit) if r["matched"] >= min(2, r["nq"])]
    return [by_id[r["key"]] for r in res]


def time_meta(a, meta, node=None) -> dict:
    """--depuis, --jusqu, --niveau → meta (valid_from, valid_to, niveau) ; « none » les retire. Une date illisible ou un
    début après la fin arrêtent tout, avant la moindre écriture."""
    from . import dates, temps
    for opt, key, near in (("depuis", "valid_from", True), ("jusqu", "valid_to", False)):
        raw = getattr(a, opt, None)
        if raw is None:
            continue
        if fold(raw) in ("none", "aucun", "aucune", "-", ""):
            meta.pop(key, None)
            continue
        d = dates.parse(raw, nearest=near)
        if not d:
            die(f"date illisible pour --{opt} : « {raw} » (ex. 01/09, 31/12/2026, il y a 3 mois, demain)")
        meta[key] = d
    raw = getattr(a, "niveau", None)
    if raw is not None:
        if fold(raw) in ("none", "aucun", "-", ""):
            meta.pop("niveau", None)
        else:
            level = temps.normalize_level(raw)
            if not level:
                die(f"niveau inconnu « {raw} » — niveaux : {', '.join(temps.LEVELS)}")
            meta["niveau"] = level
    start = meta.get("valid_from") or (temps.day(node.get("created")) if node else now_iso()[:10])
    if start and meta.get("valid_to") and meta["valid_to"] < start:
        die(f"fin de validité ({fmt_date(meta['valid_to'])}) avant le début ({fmt_date(start)}) : rien n'est enregistré "
            "— donne aussi --depuis, ou une autre fin")
    return meta


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
        # Ids donnés vérifiés avant toute écriture : un souvenir mémorisé à moitié (sans le lien ou le remplacement
        # voulus) laissait un doublon à côté de l'ancien, et l'appel répété (serveur MCP) en ajoutait d'autres.
        if a.replaces and not b.get(a.replaces):
            die(f"souvenir à remplacer introuvable : `{a.replaces}` — rien n'est mémorisé (l'id : `brain q \"…\"`, "
                "ou sans --replaces)")
        for spec in a.link or []:
            if not b.get(spec.partition(":")[0]):
                die(f"souvenir à relier introuvable : `{spec.partition(':')[0]}` — rien n'est mémorisé (l'id : "
                    "`brain q \"…\"`, ou sans --link)")
        if a.id and slugify(a.id, 40) in b.nodes:
            die(f"l'id `{slugify(a.id, 40)}` est déjà pris ({b.nodes[slugify(a.id, 40)]['title']}) — rien n'est "
                f"mémorisé : choisis-en un autre, ou modifie celui-là (`brain edit {slugify(a.id, 40)}`)")
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
            time_meta(a, meta)
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
            if target and b.supersede(created, target["id"], why=getattr(a, "why", None)):
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
    from . import mots
    sug = []
    if created:
        try:  # les liens déduits du seul nouveau souvenir, comme l'analyse complète du graphe les donnerait
            sug = [x for x in mots.inferred(b, created, 3) if x[2] != "faible"][:2]
        except Exception as exc:
            log(f"add : suggestions : {exc!r}")
    refresh_views(b)
    if sug:
        print("Liens suggérés : " + " · ".join(f"`{o}` ({', '.join(why)}) → `brain link {created} {o}`"
                                                for o, w, conf, why in sug))
    mots.keep(b)  # premier ajout après une mise à jour : les mots de tout le cerveau, gardés pour les suivants


def cmd_supersede(a):
    with Brain.edit() as b:
        new, old = b.get(a.new), b.get(a.old)
        if not new or not old:
            die(f"introuvable : {a.new if not new else a.old}")
        if not b.supersede(new["id"], old["id"], why=a.why):
            die("remplacement impossible (même souvenir ?)")
        print(f"✓ `{new['id']}` remplace `{old['id']}` — l'ancien est archivé (valable jusqu'à aujourd'hui), "
              f"toujours consultable : `brain show {old['id']}`" + ("" if a.why else
              f" · la raison, si tu la connais : `brain supersede {new['id']} {old['id']} --parce-que \"…\"`"))
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
        if a.depuis is not None or a.jusqu is not None or a.niveau is not None:
            fields["meta"] = time_meta(a, dict(fields.get("meta") or n.get("meta") or {}), n)
            from . import temps
            if temps.expired({**n, "meta": fields["meta"], "status": "active"}) and not a.unarchive:
                fields["status"] = "archived"  # fin déjà passée : archivé tout de suite, comme le ferait l'entretien
        if a.path:
            if n["type"] != "project":
                die("--path ne s'applique qu'à un projet")
            n.setdefault("meta", {})["path"] = os.path.abspath(a.path)
        if not fields and not a.path:  # avant : « ✓ modifié » sans rien changer
            die(f"rien à modifier dans `{n['id']}` : donne -T titre, -b texte, -a ajout, -i importance, --due, --tags… "
                f"(aide : `brain edit -h`)")
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
        if x["id"] == y["id"]:
            die(f"un souvenir ne se relie pas à lui-même (`{x['id']}`) : donne deux ids différents")
        ok = b.link(x["id"], y["id"], a.rel)
        print(f"✓ lien `{x['id']}` —{a.rel}→ `{y['id']}`" if ok else "(lien déjà présent)")
    refresh_views()


def cmd_unlink(a):
    with Brain.edit() as b:
        x, y = b.get(a.a), b.get(a.b)
        if not x or not y:
            die(f"souvenir introuvable : {a.a if not x else a.b}")
        gone = b.unlink(x["id"], y["id"], a.rel)
        if not gone:
            die(f"aucun lien entre `{x['id']}` et `{y['id']}`" + (f" (relation « {a.rel} »)" if a.rel else "")
                + f" : rien à retirer — liens du souvenir : `brain show {x['id']}`")
        print(f"✓ {gone} lien(s) retiré(s)")
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
    from . import temps
    print(f"valable {temps.span(n)} · {temps.axes_line(n, b.nodes)}"
          + (f" · fin : {m_['end_reason']}" if m_.get("end_reason") and not m_.get("superseded_by") else ""))
    chain = temps.lineage(b, n["id"])
    if len(chain) > 1:  # plus récent ← … ← plus ancien, avec dates et raisons
        print("↻ lignée : " + temps.lineage_line(chain))
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
    data = {"prompt": " ".join(a.text), "cwd": a.cwd or os.getcwd(), "session_id": None, "simulation": True}
    buf = io.StringIO()
    saved = hooks.bump_hits
    hooks.bump_hits = lambda ids: None
    try:
        with contextlib.redirect_stdout(buf):
            hooks.on_prompt(data, load_config())
    finally:
        hooks.bump_hits = saved
    out = buf.getvalue()
    ctx = (json.loads(out).get("hookSpecificOutput") or {}).get("additionalContext") if out else None
    if a.pourquoi or a.attendu:
        print(hooks.diagnose(data["prompt"], data["cwd"], load_config(), ctx or "", a.attendu))
        return
    print(ctx or "(rien ne serait injecté pour ce message)")


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
        if n["type"] != "todo":  # `done` sur un fait ou une règle l'archivait sans rien dire
            die(f"`{n['id']}` n'est pas un à-faire ({n['type']}) : rien n'est archivé. Pour l'archiver quand même : "
                f"`brain rm {n['id']}`")
        meta = dict(n.get("meta") or {})
        meta["done"] = now_iso()[:10]
        b.update(n["id"], status="archived", meta=meta)
        print(f"✓ terminé : {n['title']} `{n['id']}` (archivé — `brain edit {n['id']} --unarchive` pour le rouvrir)")
    refresh_views()
