"""Hook SessionStart (début, reprise, compaction, /clear) : l'index du démarrage et ce qui se dit une fois.

Découpé de hooks.py (étape 8 du plan) sans rien changer ; chargé seulement par le démarrage."""
from __future__ import annotations

import json
import os

from . import hooks as h
from . import journal
from .common import (BRAIN_DIR, STATE_DIR, budget_chars, days_since, log, now_iso, read_json, set_config, write_json)
from .hooks import (_Later, _auto_sync, _mappable, _project_path, _within, cleanup_states, emit, garde_due, gist,
                    journal_catchup, label, load_state, save_state)
from .store import Brain

idx = _Later("idx", "index", globals())  # chargé au premier usage, comme dans hooks
search = _Later("search", "search", globals())  # chargé au premier usage, comme dans hooks


def wiki_start(brain, cfg) -> str:
    """Démarrage en mode wiki : la ligne du wiki pour Claude, et un pull en arrière-plan (au plus toutes les 30 min)."""
    from . import obsidian, wiki, wikistore as ws
    if _auto_sync(brain, cfg) and wiki.due_sync((cfg.get("wiki") or {}).get("sync_minutes", 30)):
        wiki.mark_pulled()
        h.spawn_background(["wiki", "sync", "--auto", "--no-push"])
    text = wiki.notice(brain)
    root = ws.root()
    try:  # une fois par version : coffre Obsidian réglé (rien d'écrasé), puis sa page Cerveau et sa carte
        made = obsidian.setup(root)
        if made:
            obsidian.write_status(brain, root)
            obsidian.write_canvas(brain, root)
    except Exception as exc:
        made = []
        log(f"obsidian (démarrage) : {exc!r}")
    if made:
        text += (f"\n🟣 Coffre Obsidian réglé pour le cerveau ({len(made)} fichier(s) : page Cerveau, carte du cerveau, "
                 f"note du jour Alt+J, tableau de bord, modèles Alt+T, signets, mode d'emploi) — à dire à l'utilisateur : "
                 f"redémarrer Obsidian s'il est ouvert, puis signet « Cerveau » → « {obsidian.GUIDE[:-3]} ».")
    try:  # notes du jour : lignes « À retenir » → souvenirs, en arrière-plan (jamais dans le délai du hook)
        if root and os.environ.get("CLAUDE_CODE_REMOTE") != "true" and obsidian.captures(root):
            h.spawn_background(["wiki", "capture"])
    except Exception as exc:
        log(f"obsidian (notes du jour) : {exc!r}")
    return text


# ------------------------------------------------------------------------------------------ SessionStart
COMPACT_MAX_AGE = 600  # s : un résumé gardé plus vieux n'est pas celui de cette compaction
COMPACT_MIN_SCORE, COMPACT_MIN_COV, COMPACT_ITEMS = 20, 0.10, 3


def _recent(ts, seconds) -> bool:
    """Horodatage ISO (local sans fuseau, ou UTC « Z » des transcripts) vieux de moins de `seconds` ?"""
    import datetime as dt
    try:
        t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    now = dt.datetime.now(t.tzinfo) if t.tzinfo else dt.datetime.now()
    return abs((now - t).total_seconds()) <= seconds


def compact_recall(brain, st, data, cfg, proj):
    """Après une compaction : les souvenirs liés au travail en cours, d'après la section « Current Work » du résumé.
    Règle stricte mesurée sur 5 vrais résumés : 3 au plus, score ≥ 20 et couverture ≥ 0,10, hors souvenirs déjà
    visibles → 12 pertinents sur 15 (le résumé entier, lui, faisait remonter les longs souvenirs génériques)."""
    budget = budget_chars(cfg["inject"], "compact_recall_tokens")
    query = st.get("compact_summary") if _recent(st.get("compacted_at"), COMPACT_MAX_AGE) else None
    if not query and data.get("transcript_path"):  # PostCompact pas encore passé : l'ordre des hooks n'est pas garanti
        text, ts = journal.last_compact_summary(data["transcript_path"])
        if text and _recent(ts, COMPACT_MAX_AGE):
            query = journal.summary_part(text, stop="optional next step", limit=2500)
    if budget <= 0 or not query:
        return "", []
    injected = set(st.get("injected", []))
    picks = [r["node"] for r in search.search_memories(brain, query, limit=10, project=proj["id"] if proj else None,
                                                        expand=False)
             if r["node"]["id"] not in injected and r["node"]["type"] != "project"
             and r["score"] >= COMPACT_MIN_SCORE and r.get("cov", 0) >= COMPACT_MIN_COV][:COMPACT_ITEMS]
    lines, shown = ["🧠 Souvenirs liés au travail en cours (d'après le résumé de compaction) :"], []
    used = len(lines[0]) + 1
    for n in picks:
        line = f"- [{label(n)}] {n['title']} — {gist(n)} `{n['id']}`"
        if used + len(line) + 1 > budget:
            break
        lines.append(line)
        used += len(line) + 1
        shown.append(n["id"])
    if not shown:
        return "", []
    h.bump_hits(shown)
    return "\n".join(lines), shown


def config_warning() -> str:
    """Réglages faux dans config.json (écrits à la main, ou avant que `brain config` ne vérifie) : chaque lecture les
    remplace par leur défaut (common.load_config), et l'utilisateur l'apprend une fois — de nouveau seulement si la
    liste change. Rien à lire ni à écrire quand tout va bien."""
    from . import common
    if not common.CONFIG_ISSUES:
        return ""
    line = common.config_issues_line()
    sig = json.dumps([[k, w] for k, _, w in common.CONFIG_ISSUES], ensure_ascii=False)
    mark = STATE_DIR / "config-signale.json"
    if (read_json(mark, {}) or {}).get("sig") == sig:
        return ""
    try:
        write_json(mark, {"sig": sig, "le": now_iso()})
    except OSError:
        return ""  # dossier en lecture seule : mieux vaut se taire que le redire à chaque session
    log(line)
    return line


def _join(said, line):
    """Une ligne de plus pour l'utilisateur (systemMessage : aucun token), à la suite des précédentes."""
    return f"{said}\n{line}" if said else line


def on_session_start(data, cfg):
    """Démarrage, reprise, compaction ou /clear. Les étapes, dans l'ordre où elles se font (chacune protégée comme
    avant : seules la lecture du cerveau, le projet du dossier, l'index et l'écriture de l'état peuvent arrêter le hook,
    et _run le dit alors à l'utilisateur) :
    1. ce qui se dit une fois à l'utilisateur avant de lire le cerveau : mémoire native trop grosse, réglage faux ;
    2. les nouveautés des amis (cerveau commun), puis le cerveau, puis les messages en attente (étape 7 du plan) ;
    3. le projet du dossier, créé et cartographié en arrière-plan s'il en a l'air ;
    4. le mode éco et les tâches de fond du jour ;
    5. reprise : seulement les nouveautés depuis la dernière injection ;
    6. sinon l'index du démarrage, puis après une compaction ou un /clear ce qui a quitté le contexte, ou au démarrage
       les avis du jour ; puis le wiki et le cerveau commun ;
    7. l'état de la session, puis les consignes du plugin (ou les skills métier du cerveau classique), et la sortie."""
    sid = data.get("session_id")
    cwd = data.get("cwd") or os.getcwd()
    cleanup_states()
    said = _said_first()
    _pull_friends()
    brain = Brain.load()
    said = _with_notices(said)
    brain, proj, wiki_root = _project_here(brain, cwd, cfg)
    st = load_state(sid)
    source = data.get("source") or "startup"
    st.update({"cwd": cwd, "project": proj["id"] if proj else None, "wiki": bool(wiki_root)})
    eco_line = _eco(cfg)
    _daily_tasks(cfg, sid)
    if source == "resume" and st.get("started"):
        _resume(brain, st, sid, cfg, eco_line, said)
        return
    text, ids, _ = idx.session_context(brain, cwd, cfg, session_id=sid)
    if source in ("compact", "clear"):
        text = _after_compact(text, ids, brain, st, data, cfg, proj, sid, source)
    else:
        st["injected"] = sorted(set(st.get("injected", [])) | set(ids))
        text = _day_notices(text, cfg, cwd, sid)
    text = _shared_notices(text, brain, cfg, wiki_root)
    st["started"] = st.get("started") or now_iso()
    st["injected_at"] = now_iso()
    save_state(sid, st)
    emit("SessionStart", _finish(text, eco_line), said)


def _said_first():
    """Étape 1 : mémoire native de Claude Code importée (seulement si elle a changé) ; un fichier trop gros ignoré et un
    réglage faux dans config.json (le défaut sert) se disent une fois, à l'utilisateur (0 token). → texte ou None."""
    from . import importer
    big = []
    try:
        importer.sync(skipped=big)  # mémoire native de Claude Code → cerveau (seulement si elle a changé)
    except Exception as exc:
        log(f"import auto-memory : {exc!r}")
    said = importer.too_big_line(big) or None  # fichier trop gros ignoré : dit une fois, à l'utilisateur (0 token)
    bad_cfg = config_warning()  # réglage faux dans config.json : le défaut sert, dit une fois à l'utilisateur
    return _join(said, bad_cfg) if bad_cfg else said


def _pull_friends() -> None:
    """Étape 2 : cerveau commun, les nouveautés des amis avant de construire l'index (attente brève si la dernière est
    vieille)."""
    try:
        from . import commun
        commun.maybe_pull(wait=4)
    except Exception as exc:
        log(f"commun (démarrage) : {exc!r}")


def _with_notices(said):
    """Étape 2 : graph.json réparé, sauvegarde rangée chez toi… (common.tell_user) : dit une fois, à l'utilisateur."""
    from .common import take_notices
    for line in take_notices():
        said = _join(said, line)
    return said


def _project_here(brain, cwd, cfg):
    """Étape 3 : le projet du dossier. Un dossier inconnu qui a l'air d'un projet devient un projet (pas le dossier du
    wiki) ; sa carte est refaite en arrière-plan quand elle est vieille. → (cerveau, projet ou None, racine du wiki)."""
    from . import filesearch
    proj = brain.project_for_path(cwd)
    wiki_root = (brain.data.get("wiki") or {}).get("root")
    in_wiki = bool(wiki_root) and _within(cwd, wiki_root)  # le dossier du wiki n'est pas un projet à cartographier
    if not proj and cfg["auto_map"]["enabled"] and not in_wiki:
        from . import mapper  # dossier inconnu seulement : le cartographe est lourd à importer
        if mapper.looks_like_project(cwd):
            with Brain.edit() as b:
                b.ensure_project(cwd, source="auto")
            brain = b  # tel qu'il vient d'être écrit : pas besoin de le relire (20 à 60 ms)
            proj = brain.project_for_path(cwd)
    path = _project_path(proj)
    if path and cfg["auto_map"]["enabled"] and filesearch.needs_refresh(proj["id"], cfg["auto_map"]["refresh_minutes"]) \
            and _mappable(proj, path):
        h.spawn_background(["map", path, "-p", proj["id"], "--quiet"])
    return brain, proj, wiki_root


def _eco(cfg) -> str:
    """Étape 4 : mode éco — réglages posés UNE fois, puis les nouveaux leviers d'une version plus récente (annulable :
    `brain eco --annuler`), annonces de la veille ; cache adaptatif et veille des plugins une fois par jour, en
    arrière-plan. → la ligne à annoncer à l'utilisateur, ou ''."""
    eco_line = ""
    ecfg = cfg.get("eco") or {}
    if ecfg.get("auto", True) or ecfg.get("annonce"):
        try:  # mode éco : réglages posés UNE fois, puis les nouveaux leviers d'une version plus récente (annulable :
            from . import eco  # `brain eco --annuler`) + annonces de la veille (plugins, cache)
            eco_line = eco.start(cfg)
        except Exception as exc:
            log(f"éco (démarrage) : {exc!r}")
    if ecfg.get("auto", True) and (ecfg.get("cache") or "auto") == "auto" and days_since(ecfg.get("cache_vu_le")) >= 1:
        try:  # cache adaptatif : durée du cache choisie d'après les pauses réelles, une fois par jour, en arrière-plan
            set_config("eco.cache_vu_le", now_iso())
            h.spawn_background(["eco", "--cache", "auto"])
        except Exception as exc:
            log(f"éco (cache) : {exc!r}")
    if ecfg.get("plugins_auto") and days_since(ecfg.get("plugins_vus_le")) >= 1:
        try:  # veille quotidienne des plugins inutilisés : en arrière-plan (le parcours des transcripts ne tient pas dans le hook)
            set_config("eco.plugins_vus_le", now_iso())  # jour réservé : une autre session qui démarre n'en lance pas une 2e
            h.spawn_background(["eco", "--plugins-auto"])
        except Exception as exc:
            log(f"éco (veille des plugins) : {exc!r}")
    return eco_line


def _daily_tasks(cfg, sid) -> None:
    """Étape 4 : tâches de fond dues — garde de consommation (toutes les 2 h au plus), rattrapage du journal et veille
    automatique Windows (une fois par jour)."""
    try:  # garde de consommation : sessions qui mangent la journée (toutes les 2 h au plus, en arrière-plan)
        if garde_due(cfg):
            h.spawn_background(["tokens", "--garde"])
    except Exception as exc:
        log(f"garde de consommation : {exc!r}")
    try:  # sessions que les hooks ont manquées (une fois par jour) : importées au journal en arrière-plan
        journal_catchup(cfg, sid)
    except Exception as exc:
        log(f"rattrapage du journal : {exc!r}")
    try:  # veille automatique posée un jour : reposée si elle a disparu ou vise un Python absent (une fois par jour)
        acfg = cfg.get("auto") or {}
        if os.name == "nt" and acfg.get("tache") and not acfg.get("coupe") and days_since(acfg.get("verifie_le")) >= 1:
            set_config("auto.verifie_le", now_iso())
            h.spawn_background(["auto", "--reparer"])
    except Exception as exc:
        log(f"veille (réparation) : {exc!r}")


def _resume(brain, st, sid, cfg, eco_line, said) -> None:
    """Étape 5 : reprise — l'injection de départ est encore dans l'historique (7 reprises sur 7) → les nouveautés
    seulement."""
    text = idx.resume_delta(brain, st.get("injected_at") or st["started"], cfg)
    st["injected_at"] = now_iso()
    save_state(sid, st)
    if eco_line:
        text = f"{text}\n\n{eco_line}".strip()
    if text or said:
        emit("SessionStart", text, said)


def _after_compact(text, ids, brain, st, data, cfg, proj, sid, source) -> str:
    """Étape 6, compaction ou /clear : l'injection précédente et les rappels ont quitté le contexte, on repart de ce qui
    est visible maintenant (avant : « déjà injectés » gardés, donc plus jamais rappelés après une compaction). Après une
    compaction : les souvenirs du travail en cours, et l'avis des lectures une par une."""
    st["injected"], st["files"], st["recalled"], st["recall_hist"] = sorted(ids), [], 0, []
    st["skills_hinted"] = []  # skills soufflées ou chargées d'office : sorties du contexte, à resservir
    st["outils_hinted"] = []  # connecteurs soufflés : idem
    from . import compact
    compact.forget(sid)  # sorties déjà lues sorties du contexte : plus de renvoi « identique » vers elles
    if source == "compact":
        extra, shown = compact_recall(brain, st, data, cfg, proj)
        if extra:
            text = f"{text}\n\n{extra}"
            st["injected"] = sorted(set(ids) | set(shown))
        try:
            from . import tokens
            line = tokens.solo_notice(data["transcript_path"]) if data.get("transcript_path") else ""
            if line:
                text = f"{text}\n\n{line}"
        except Exception as exc:
            log(f"lectures une par une (compaction) : {exc!r}")
    return text


def _day_notices(text, cfg, cwd, sid) -> str:
    """Étape 6, démarrage : les avis du jour — rêve (consolidation), skills mal formées, nouveaux connecteurs et skills
    sans phrase française, conseil d'optimisation, garde de consommation."""
    try:
        from . import dream
        note = dream.notice()
        if note:
            text = f"{text}\n\n{note}"
    except Exception as exc:
        log(f"rêve (démarrage) : {exc!r}")
    try:
        from . import skills
        if (cfg.get("skills") or {}).get("enabled", True):
            warn = skills.notice()
            if warn:
                text = f"{text}\n\n{warn}"
    except Exception as exc:
        log(f"skills (démarrage) : {exc!r}")
    try:  # veille : nouveaux connecteurs et skills qu'aucune phrase française ne déclenche
        oc, kc = cfg.get("outils") or {}, cfg.get("skills") or {}
        if oc.get("enabled", True) and oc.get("veille", True):
            from . import outils, skills
            line = outils.veille(skills.index(cwd, kc) if kc.get("enabled", True) else None, oc)
            if line:
                text = f"{text}\n\n{line}"
    except Exception as exc:
        log(f"outils (démarrage) : {exc!r}")
    try:
        from . import optimize
        tip = optimize.notice(cfg)
        if tip:
            text = f"{text}\n\n{tip}"
    except Exception as exc:
        log(f"optimize (démarrage) : {exc!r}")
    try:
        from . import tokens
        line = tokens.guard_notice(cfg, sid)
        if line:
            text = f"{text}\n\n{line}"
    except Exception as exc:
        log(f"garde de consommation (démarrage) : {exc!r}")
    return text


def _shared_notices(text, brain, cfg, wiki_root) -> str:
    """Étape 6 : la ligne du wiki (mode wiki), puis le cerveau commun — état (membre) ou proposition d'y entrer (une fois
    par jour, s'il est ouvert)."""
    if wiki_root:
        try:
            text = f"{text}\n\n{wiki_start(brain, cfg)}".rstrip()
        except Exception as exc:
            log(f"wiki (démarrage) : {exc!r}")
    try:  # cerveau commun : état (membre) ou proposition d'y entrer (une fois par jour, s'il est ouvert)
        from . import commun
        line = commun.notice(brain)
        if line:
            text = f"{text}\n\n{line}"
    except Exception as exc:
        log(f"commun (démarrage) : {exc!r}")
    return text


def _finish(text, eco_line) -> str:
    """Étape 7. Plugin : lanceur stable à jour, et les consignes du bloc CLAUDE.md passent par l'injection (l'annonce du
    mode éco par le même canal que le passage au plugin). Cerveau classique : l'annonce du mode éco, et les skills métier
    (cerveau e-commerce…) posées ou mises à jour dans ~/.claude/skills. → le texte injecté."""
    from .common import PLUGIN
    if PLUGIN:  # plugin : lanceur stable à jour, et les consignes du bloc CLAUDE.md passent par l'injection
        from . import plugin
        try:
            if (BRAIN_DIR / "brainkit").exists():  # reste du code classique déjà archivé (fichier verrouillé la veille)
                plugin.remove_classic_code()
            plugin.ensure_launcher()
        except OSError as exc:
            log(f"lanceur du plugin : {exc!r}")
        if eco_line:
            plugin.NOTICE.append(eco_line)  # même canal que le passage au plugin : annoncé une fois à l'utilisateur
        notice = plugin.take_notice()
        return f"{plugin.instructions()}\n\n" + (f"{notice}\n\n" if notice else "") + text
    if eco_line:  # comme le passage au plugin : annoncé une fois à l'utilisateur
        text = f"{text}\n\n{eco_line} (dis-le à l'utilisateur en une phrase au début de ta réponse)"
    try:
        from . import install
        install.sync_skills(quick=True)
    except Exception as exc:
        log(f"skills métier (démarrage) : {exc!r}")
    return text
