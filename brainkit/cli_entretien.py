"""Commandes d'entretien : regrouper, consolider, rêve, export, vues, statistiques, diagnostic (doctor), sauvegardes,
instantanés et restauration.

Découpé de cli.py (étape 8 du plan) sans rien changer : le parseur et main() restent dans cli.py, qui ne charge ce
module qu'au moment d'en lancer une commande."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import index as idx
from . import __version__, journal
from .cli_commun import die, refresh_views
from .common import (BRAIN_DIR, CLAUDE_HOME, CMD, EXPORT_FILE, GRAPH_FILE, INDEX_FILE, LOG_FILE, PROJECTS_DIR,
                     VIZ2D_FILE, VIZ_FILE, budget_chars, days_since, est_tokens, fmt_date, load_config, log, now_iso,
                     oserror_fr, set_config, short, tell_user)
from .store import TYPES, Brain, priority


def cmd_regroupe(a):
    """Doublons reformulés, souvenirs sans projet, sujets à réunir en fiche : montrer, puis appliquer ce qui est accepté
    (regroupe.py)."""
    from . import regroupe
    if a.appliquer and a.ecarter:
        die("--appliquer ou --ecarter, pas les deux à la fois", 2)
    try:
        if a.ecarter:
            for line in regroupe.ecarter(a.ecarter):
                print(f"✓ {line}")
            return
        if a.appliquer:
            rep = regroupe.apply(a.appliquer)
            for line in rep["done"]:
                print(f"✓ {line}")
            for line in rep["skipped"]:
                print(f"· {line}")
            if rep["done"]:
                refresh_views()
                print("Annuler : `brain restore 1` (instantané pris avant : "
                      f"{rep['snap'].name if rep['snap'] else 'aucun, graph.json absent'})")
            else:
                sys.exit(1)
            return
        brain = Brain.load()
        print(regroupe.show_text(brain, regroupe.propose(brain)))
    except (ValueError, LookupError) as exc:
        die(str(exc))


def cmd_consolidate(a):
    from . import history
    from .privacy import find as find_secrets
    dry = a.dry_run
    strict = getattr(a, "auto", False)  # mode automatique (fin de session) : seulement les fusions évidentes
    actions = []
    if not dry:
        history.snapshot("avant-consolidation", force=True)
    with Brain.edit() as b:
        if not dry:
            b.absorb_counters()  # compteurs de rappel en attente : écrits dans graph.json au moins une fois par jour
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
        from . import temps
        for n in list(b.active(own=True)):  # fin de validité écrite (`--jusqu 31/12`) passée : archivé le lendemain
            if temps.expired(n):
                actions.append(f"archivage (vrai jusqu'au {fmt_date(n['meta']['valid_to'])}) : `{n['id']}`")
                if not dry:
                    n["status"] = "archived"
                    n["updated"] = now_iso()
                    b.dirty = True
        merged = set()
        b.cache_similar()  # chaque souvenir découpé une fois par passage, et non une fois par comparaison
        # Passage automatique (une fois par jour, verrou du cerveau tenu) : seulement les souvenirs écrits depuis le
        # passage précédent, comparés à tous. Les paires plus anciennes ont déjà été vues. Avant, chaque passage comparait
        # toutes les paires : plus de 8 minutes à 3 000 souvenirs, pendant lesquelles aucune écriture n'aboutissait.
        # `brain consolidate` lancé à la main compare toujours tout.
        mark = BRAIN_DIR / "state" / "consolidation_auto_vue"
        started = now_iso()
        since = None
        if strict:
            try:
                since = mark.read_text(encoding="utf-8").strip()
            except OSError:  # premier passage : la dernière semaine (le passage manuel, lui, voit tout)
                import datetime as _dt
                since = (_dt.datetime.now() - _dt.timedelta(days=7)).replace(microsecond=0).isoformat()
        for n in [x for x in b.active(own=True) if x["type"] != "project"]:
            if n["id"] in merged or (since and max(n.get("updated") or "", n.get("created") or "") < since):
                continue
            # Doublon = même projet ET même contenu : deux « Objectif du mois » (boutique, chaîne YouTube) ne se
            # fusionnent plus sur leur seul titre.
            for score, m in b.similar(n["title"], n.get("body", ""), n["type"], limit=5, threshold=0.9 if strict else 0.82,
                                      exclude=n["id"], whole=True):
                if m["id"] in merged or (m.get("project") or None) != (n.get("project") or None):
                    continue
                keep, drop = (n, m) if priority(n) >= priority(m) else (m, n)
                actions.append(f"fusion : `{drop['id']}` → `{keep['id']}` (similarité {score})")
                merged.add(drop["id"])
                if not dry:
                    b.merge(keep["id"], drop["id"])  # textes, liens, compteurs et dates des deux (store.Brain.merge)
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
        if not dry:
            try:
                mark.parent.mkdir(parents=True, exist_ok=True)
                mark.write_text(started, encoding="utf-8")
            except OSError as exc:
                log(f"consolidation auto : repère non écrit {exc!r}")
        log("consolidation auto : " + (" | ".join(actions) if actions else "rien à faire"))
        try:  # rêve : partie sûre appliquée, dossier du reste préparé pour un sous-agent
            from . import dream
            _, pending = dream.prepare(apply_safe=True)
            log(f"rêve préparé : {pending} point(s) à trancher")
        except Exception as exc:
            log(f"rêve : {exc!r}")
        try:  # filtres de sorties appris du bruit qui revient (annoncés une fois au prochain démarrage)
            from . import compact
            for name, before, after in compact.auto_learn():
                log(f"filtre de sortie appris : {name} ({before} → {after} car.)")
        except Exception as exc:
            log(f"filtres appris : {exc!r}")
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
    if a.push and a.vault is None:  # avant : ignoré sans un mot, MEMOIRES.md écrit à la place
        die("--push s'applique au coffre Obsidian : `brain export --vault --push` (ou --vault <dossier> --push)")
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
                  f"(plus récente) est gardée, celle d'Obsidian mise à part dans Conflits/")
        for title, fields in rep.get("replaced") or []:
            print(f"  ⚠ conflit sur « {title} » ({', '.join(fields)}) : modifié des deux côtés, la note d'Obsidian "
                  f"(plus récente) est gardée, la version du cerveau mise à part dans Conflits/")
        for title, other in rep["duplicates"]:
            print(f"  ≈ « {title} » ressemble à « {other} » : laissé dans « À trier »")
        for line in rep["kept"]:
            print(f"  · {line}")
        return
    from . import vues
    with vues.lock():  # après la régénération en arrière-plan en cours, jamais en même temps qu'elle
        b = Brain.load()
        b.freeze_neighbors()  # lecture seule : voisins indexés une fois (0,7 s → quelques ms à 3 000 souvenirs)
        idx.export(b)
    print(f"✓ {EXPORT_FILE}")


def cmd_viz(a):
    from . import viz, vues
    with vues.lock():  # après la régénération en arrière-plan en cours, jamais en même temps qu'elle
        path = viz.render(Brain.load())
    print(f"✓ {path} (vue 3D) · {VIZ2D_FILE} (vue 2D, sans WebGL) — les deux fonctionnent hors ligne")
    if a.open:
        os.startfile(str(path)) if os.name == "nt" else print("(ouvre le fichier dans un navigateur)")


def cmd_vues(a):
    """Vues refaites après une écriture (BRAIN.md, MEMOIRES.md, vues 3D et 2D) : --fond, la tâche détachée qui les
    refait ; --attendre, attendre qu'elles soient à jour ; sans option, les refaire tout de suite."""
    from . import vues
    if a.fond:
        vues.background()
        return 0
    if a.attendre:
        done = vues.wait(a.delai)
        print("✓ vues à jour" if done else f"✗ vues toujours en cours après {a.delai:g} s")
        return 0 if done else 1
    vues.run_now(force=True)  # à la main : toutes, même celles dont rien n'a changé
    print(f"✓ vues refaites : {INDEX_FILE.name}, {EXPORT_FILE.name}, {VIZ_FILE.name}, {VIZ2D_FILE.name}")
    return 0


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
    from . import common as _common
    load_config()
    ok(not _common.CONFIG_ISSUES, "réglages (config.json) : " + (
        "valeurs valides" if not _common.CONFIG_ISSUES else _common.config_issues_line().split(" — ", 1)[-1]))
    from . import wikistore
    mode, wroot = wikistore.resolve()
    if mode == "wiki":
        from . import wiki
        st = wikistore.stats(b.data)
        git_ok = wiki.is_repo(wroot)
        ok(True, f"wiki : {wroot} — {sum(st['types'].values())} pages, {st['archived']} archivées · "
                 + (f"git ({wiki.remote(wroot) or 'sans origin'})" if git_ok else "pas de dépôt git (→ git init)"))
        wst = wiki.read_json(wiki.SYNC_STATE, {}) or {}
        conflict, failed = wst.get("conflict"), wst.get("failed")
        if conflict:
            ok(False, f"wiki : synchronisation git en conflit depuis le {fmt_date(conflict)} (→ brain wiki status, git status)")
        elif isinstance(failed, dict):
            ok(False, f"wiki : dernière synchronisation git ratée le {fmt_date(failed.get('le'))} — {failed.get('quoi')}")
    elif mode == "missing":
        ok(False, f"wiki introuvable : {wroot} — le cerveau lit son cache sans écrire (→ rebrancher, ou config wiki.path)")
    from . import commun as _commun
    if _commun.member():
        ok(not _commun.state().get("conflict"), _commun.status(b).replace("\n", " · "))
    from . import plugin as _plugin
    from .common import PLUGIN
    if PLUGIN:
        _doctor_plugin(ok)
    if PLUGIN or _plugin.installed():
        _doctor_python(ok)
    settings = CLAUDE_HOME / "settings.json"
    try:
        hooks = (json.loads(settings.read_text(encoding="utf-8")).get("hooks") or {}) if settings.exists() else {}
    except Exception:
        hooks = {}
    wanted = ("SessionStart", "UserPromptSubmit", "Stop", "PreCompact", "PostCompact", "SessionEnd", "PostToolUse")
    present = [ev for ev in wanted if "brain.py" in json.dumps(hooks.get(ev, []))]
    import re as _re
    exes = {m.group(1) for ev in wanted for h in hooks.get(ev, []) for x in h.get("hooks", [])
            for m in [_re.match(r'^"([^"]+\.exe)"', x.get("command", ""))] if m}
    missing = [e for e in exes if not os.path.exists(e)]
    if not PLUGIN:
        ok(not missing, "interpréteur des hooks : " + (", ".join(sorted(exes)) or "py -3")
           + (" — INTROUVABLE (Python a changé de version ?) → brain install" if missing else ""))
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
    _doctor_journal(ok)
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
    if os.name == "nt":
        from . import auto
        acfg = load_config().get("auto") or {}
        last = (read_json(auto.LAST, {}) or {}).get("le")
        seen = f" · dernière passe {last[8:10]}/{last[5:7]} {last[11:16]}" if last else ""
        if acfg.get("coupe"):
            ok(True, f"veille automatique : retirée exprès le {acfg['coupe'][8:10]}/{acfg['coupe'][5:7]}{seen} "
                     "(`brain auto --installer` la remet)")
        else:
            why = auto.broken(auto.task_action())
            ok(not why, f"veille automatique : {'toutes les ' + str(auto.EVERY) + ' min' if not why else why}{seen}"
               + (" → `brain doctor --fix` la répare" if why and acfg.get("tache")
                  else " → `brain auto --installer` la pose" if why else ""))
    if LOG_FILE.exists():
        errs = [l for l in LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines() if "ERREUR" in l][-3:]
        ok(not errs, "journal d'erreurs des hooks : " + ("vide" if not errs else " | ".join(short(e, 160) for e in errs)))


def cmd_backup(a):
    from . import backup
    if a.restore:
        if not Path(a.restore).is_file():
            die(f"archive introuvable : {a.restore} — les sauvegardes : `brain backup --list` (--to <dossier> pour un "
                "autre dossier)")
        try:
            n = backup.restore(a.restore)
        except OSError as exc:
            die(f"restauration impossible : {oserror_fr(exc)}")
        except Exception as exc:  # zip abîmé (BadZipFile, en anglais), archive sans graph.json…
            die("restauration impossible : " + ("ce n'est pas une archive zip lisible" if type(exc).__name__ ==
                                                "BadZipFile" else str(exc)))
        refresh_views()
        print(f"✓ cerveau restauré depuis {a.restore} ({n} nœuds) — l'état précédent est dans l'historique : `brain restore 1` pour annuler")
        return
    dest = a.to or backup.target_dir()
    if a.to and Path(a.to).exists() and not Path(a.to).is_dir():
        die(f"ce n'est pas un dossier : {a.to} — --to attend le dossier où ranger les sauvegardes")
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
        die(f"sauvegarde impossible : {oserror_fr(exc)}" if isinstance(exc, OSError) else str(exc))
    notice = "" if a.to else backup.home_notice(dest)  # dossier personnel faute de second disque : dit une fois
    if a.auto:
        log(f"sauvegarde auto : {path or 'déjà faite aujourd hui'}")
        if notice:
            tell_user("sauvegarde", notice)  # au démarrage suivant (la sauvegarde du jour tourne en arrière-plan)
        return
    print(f"✓ sauvegarde : {path} ({max(1, path.stat().st_size // 1024)} Ko) — restaurer : `brain backup --restore \"{path}\"`")
    if notice:
        print(notice)


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
          + (" — l'état précédent est sauvegardé : `brain restore 1` pour annuler" if before else ""))


def _doctor_plugin(ok):
    """Contrôles propres au mode plugin : version, fichiers du plugin, lanceur stable, cerveau classique en double."""
    from . import plugin
    from .common import CODE_DIR, read_json
    ok(True, f"plugin « cerveau » {__version__} : {CODE_DIR}")
    need = [CODE_DIR / "hooks" / "hooks.json", CODE_DIR / "skills" / "brain" / "SKILL.md"]
    gone = [str(p.relative_to(CODE_DIR)) for p in need if not p.exists()]
    manifest = read_json(CODE_DIR / ".claude-plugin" / "plugin.json", {}) or {}
    servers = manifest.get("mcpServers") if isinstance(manifest, dict) else None
    if not (isinstance(servers, dict) and "cerveau" in servers) and not (CODE_DIR / ".mcp.json").exists():
        gone.append("serveur MCP (.claude-plugin/plugin.json › mcpServers)")
    ok(not gone, "hooks, serveur MCP et skill du plugin" + (f" — manquants : {', '.join(gone)}" if gone else ""))
    from . import delegation
    agents = delegation.available()
    missing = [n for n in delegation.AGENTS if n not in agents]
    ok(not missing, f"agents de délégation ({', '.join(delegation.call_name(n) for n in agents) or 'aucun'}) · mode "
                    f"{delegation.mode()}" + (f" — manquants : {', '.join(missing)}" if missing else ""))
    pcfg = load_config().get("plugin") or {}
    if plugin.classic_install():
        ok(True, "cerveau classique présent dans ~/.claude/brain : " + (
            "gardé aux commandes (config plugin.garder_classique), le plugin s'efface" if pcfg.get("garder_classique")
            else "le plugin prendra le relais au prochain démarrage de session (souvenirs intacts)"))
    else:
        plugin.ensure_launcher()
        ok((BRAIN_DIR / "brain.py").exists(), f"lanceur stable : {BRAIN_DIR / 'brain.py'}")
        if pcfg.get("migre_le"):
            ok(not (BRAIN_DIR / "brainkit").exists(), f"passé du cerveau classique {pcfg.get('version_classique', '?')} "
               f"au plugin le {fmt_date(pcfg['migre_le'])} (archive : {pcfg.get('archive')})"
               + (" — reste de code classique à retirer (→ redémarrer Claude Code)" if (BRAIN_DIR / "brainkit").exists()
                  else ""))
    try:
        settings = json.loads((CLAUDE_HOME / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    name, _ = plugin._marketplace()
    if name:
        auto = ((settings.get("extraKnownMarketplaces") or {}).get(name) or {}).get("autoUpdate") is True
        ok(auto, f"mises à jour automatiques du marketplace « {name} »" + (
            "" if auto else " : désactivées (→ /plugin › marketplaces › {0} › Enable auto-update)".format(name)))


def _doctor_python(ok):
    """Les hooks du plugin lancent la commande `python` : s'il manque (macOS, Linux : souvent seulement `python3`), rien
    n'est enregistré, sans aucune erreur visible."""
    from .plugin import PYTHON_MIN, hook_python
    exe, ver = hook_python()
    want = ".".join(map(str, PYTHON_MIN))
    if exe and ver and ver >= PYTHON_MIN:
        ok(True, f"commande `python` des hooks : {'.'.join(map(str, ver))} ({exe})")
        return
    effet = "→ rien n'est enregistré automatiquement"
    if not exe:
        ok(False, f"les hooks du plugin lancent `python`, introuvable ici {effet}")
        print('  → macOS : mkdir -p ~/.local/bin && ln -sf "$(command -v python3)" ~/.local/bin/python  (puis redémarre Claude Code)')
        print("  → Debian/Ubuntu : sudo apt install python-is-python3")
        print("  → Windows : réinstalle Python depuis python.org en cochant « Add python.exe to PATH »")
        return
    ok(False, f"les hooks du plugin lancent `python` ({exe}) : "
       + (f"version {'.'.join(map(str, ver))} trop ancienne (il faut {want} ou plus)" if ver
          else "il ne se lance pas (alias du Microsoft Store ?)") + f" {effet}")
    print(f"  → installe Python {want} ou plus récent (python.org), fais-le résoudre par `python` dans le PATH, "
          "puis redémarre Claude Code")


def _doctor_journal(ok):
    """Sessions de Claude Code des 7 derniers jours absentes du journal : les hooks n'ont rien enregistré."""
    if not (load_config().get("journal") or {}).get("enabled", True):
        return
    lost = journal.missing()
    if lost:
        print(f"⚠ {len(lost)} session(s) de Claude Code absentes du journal → `brain journal --backfill` les importe")
        return
    known = journal.load()["sessions"]
    kept = sum(1 for p in journal.recent_transcripts() if p.stem in known)
    if kept:
        ok(True, f"sessions des 7 derniers jours : {kept} dans le journal, aucune manquante")


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
    refresh_views(wait=True)  # réparation : vues refaites tout de suite, pas en arrière-plan
    try:
        path = backup.run(force=True)
        print(f"✓ sauvegarde : {path}")
    except Exception as exc:
        print(f"✗ sauvegarde : {exc}")
    from . import auto
    for line in auto.heal():
        print(line)
    print("✓ index, caches de recherche, vue 3D et entretien refaits\n")
