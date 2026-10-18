"""Points d'accroche Claude Code : SessionStart, UserPromptSubmit, Stop, PreCompact, PostCompact, SessionEnd.

Règle d'or : un hook ne doit JAMAIS casser ni ralentir une session → tout est protégé, rapide et silencieux.
Le travail lourd (cartographie) part en arrière-plan dans un processus détaché."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from . import index as idx
from . import journal, search
from .common import (BRAIN_DIR, BRAIN_PY, CMD, SESSIONS_DIR, STATE_DIR, budget_chars, fold, load_config, log, now_iso,
                     read_json, read_stdin_json, short, tokenize, write_json)
from .store import TYPES, Brain, bump_hits, bump_used

OBS_HOW = (f"une ligne courte chacune, priorisées (🔴 décision, blocage, préférence · 🟡 avancée, constat · 🟢 détail) : "
           f"`{CMD} obs \"🔴 …\" \"🟡 …\"`")
STOP_REASON = (
    f"🧠 Cerveau — avant de conclure : 1) note 3 à 5 observations datées de cette session, {OBS_HOW} ; "
    "2) enregistre le durable (0 à 3 entrées) : préférence ou correction de l'utilisateur (feedback), info sur lui "
    "(user), décision (decision), état d'un travail en cours (fact), piège résolu / solution qui marche (learning), "
    f"ressource (reference), suite à faire (todo) — doublons : `{CMD} q \"…\"` (sinon `edit <id>`), puis "
    f"`{CMD} add -t <type> -T \"titre court\" -b \"fait + pourquoi + comment l'appliquer\"` (`-p none` si hors du "
    "projet courant). Jamais de secrets, mots de passe ni infos sensibles sur des tiers."
)
WIKI_REASON = (" 3) Wiki : une réponse qui vaut d'être gardée (synthèse, comparaison, analyse) → page Analyses "
               f"(`{CMD} add -t analyse -T … -b - --resume …`) puis `{CMD} wiki log query \"…\"` ; une source lue ou "
               f"citée → `{CMD} wiki add` puis la méthode du CLAUDE.md du wiki.")
OBS_REASON = ("🧠 Cerveau — le contexte vient d'être compacté : avant de conclure, note 3 à 5 observations datées de "
              f"cette session (d'après le résumé et la suite), {OBS_HOW}.")
REMEMBER_RX = re.compile(r"\b(souviens[- ]toi|retiens|m[ée]moris|note (?:que|bien|[çc]a)|n'oublie pas|"
                         r"garde (?:[çc]a |le |la |les )?en m[ée]moire|remember|ajoute (?:[çc]a |le |la )?(?:au|dans le) cerveau)",
                         re.I)
NUM_NOISE = re.compile(r"(?<![\w-])(?:\d{1,2}|(?:19|20)\d{2})(?![\w-])")
CAPTURE_RX = re.compile(r"\b(je (?:veux|voudrais|pr[ée]f[èe]re|n'aime pas|d[ée]teste)|toujours|jamais|plut[ôo]t|"
                        r"arr[êe]te de|ne (?:fais|mets|touche|change) (?:pas|plus|jamais)|n'oublie pas|retiens|"
                        r"d[ée]sormais|dor[ée]navant|[àa] partir de maintenant|on part sur|on garde|c'est bon pour|"
                        r"ok pour|vas-y pour|pas comme [çc]a|c'est faux|corrige|il faut que tu|tu dois)\b", re.I)
RECALL_RX = re.compile(r"\b(tu te souviens|te rappelles|rappelle[- ]moi|on avait (?:dit|fait|d[ée]cid)|"
                       r"la derni[èe]re fois|d[ée]j[àa] (?:fait|vu|dit)|qu'est-ce qu'on avait)", re.I)


def recall_query(raw) -> str:
    """Message → requête de rappel : blocs collés et balises retirés, nombres sans valeur (« 12 fois 8 », « le 15/10 »,
    « 2026 ») effacés. Partagé avec `brain bench` pour mesurer exactement ce que fait le hook."""
    return NUM_NOISE.sub(" ", journal.clean_prompt(raw, 600))


def gist(n, chars=220) -> str:
    """Ce qu'on montre d'un souvenir : le résumé d'une page du wiki s'il existe, sinon le début de son contenu."""
    return short((n.get("meta") or {}).get("resume") or n.get("body", ""), chars)


def emit(event, context):
    if context:
        sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}},
                                    ensure_ascii=False))
        sys.stdout.flush()


def _state_file(sid):
    safe = "".join(c for c in str(sid) if c.isalnum() or c in "-_")[:80] or "anon"
    return SESSIONS_DIR / f"{safe}.json"


def load_state(sid) -> dict:
    return (read_json(_state_file(sid), {}) or {}) if sid else {}


def save_state(sid, st):
    if sid:
        write_json(_state_file(sid), st, indent=None)


def cleanup_states(max_days=5):
    try:
        now = time.time()
        for f in SESSIONS_DIR.glob("*.json"):
            if now - f.stat().st_mtime > max_days * 86400:
                f.unlink()
    except OSError:
        pass


def spawn_background(args) -> bool:
    """Lance `brain.py <args>` dans un processus détaché (aucune fenêtre, n'attend pas)."""
    import subprocess  # importé seulement ici : ~5 ms épargnées à chaque hook
    try:
        exe = Path(sys.executable)
        if os.name == "nt" and (exe.parent / "pythonw.exe").exists():
            exe = exe.parent / "pythonw.exe"
        kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                  close_fds=True, cwd=str(BRAIN_DIR), env={**os.environ, "BRAIN_BG": "1"})
        if os.name == "nt":
            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | BELOW_NORMAL_PRIORITY_CLASS : invisible, priorité basse
            kw["creationflags"] = 0x00000008 | 0x00000200 | 0x00004000
        else:
            kw["start_new_session"] = True
        subprocess.Popen([str(exe), str(BRAIN_PY), *args], **kw)
        return True
    except Exception as exc:
        log(f"spawn_background {args}: {exc!r}")
        return False


def _project_path(proj):
    path = (proj.get("meta") or {}).get("path") if proj else None
    return path if path and os.path.isdir(path) else None


def _within(path, root) -> bool:
    from .common import path_within
    try:
        return path_within(path, root)
    except Exception:
        return False


def _auto_sync(brain, cfg) -> bool:
    """Synchronisation git automatique du wiki : sur le PC seulement (une session cloud pousse sur sa branche)."""
    w = brain.data.get("wiki") or {}
    return bool(w.get("root")) and not w.get("missing") and (cfg.get("wiki") or {}).get("auto_sync", True) \
        and not os.environ.get("CLAUDE_CODE_REMOTE") and (Path(w["root"]) / ".git").exists()


def wiki_start(brain, cfg) -> str:
    """Démarrage en mode wiki : la ligne du wiki pour Claude, et un pull en arrière-plan (au plus toutes les 30 min)."""
    from . import wiki
    if _auto_sync(brain, cfg) and wiki.due_sync((cfg.get("wiki") or {}).get("sync_minutes", 30)):
        wiki.mark_pulled()
        spawn_background(["wiki", "sync", "--auto", "--no-push"])
    return wiki.notice(brain)


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
        line = f"- [{TYPES.get(n['type'], n['type'])}] {n['title']} — {gist(n)} `{n['id']}`"
        if used + len(line) + 1 > budget:
            break
        lines.append(line)
        used += len(line) + 1
        shown.append(n["id"])
    if not shown:
        return "", []
    bump_hits(shown)
    return "\n".join(lines), shown


def on_session_start(data, cfg):
    from . import filesearch, importer
    sid = data.get("session_id")
    cwd = data.get("cwd") or os.getcwd()
    cleanup_states()
    try:
        importer.sync()  # mémoire native de Claude Code → cerveau (seulement si elle a changé)
    except Exception as exc:
        log(f"import auto-memory : {exc!r}")
    brain = Brain.load()
    proj = brain.project_for_path(cwd)
    wiki_root = (brain.data.get("wiki") or {}).get("root")
    in_wiki = bool(wiki_root) and _within(cwd, wiki_root)  # le dossier du wiki n'est pas un projet à cartographier
    if not proj and cfg["auto_map"]["enabled"] and not in_wiki:
        from . import mapper  # dossier inconnu seulement : le cartographe est lourd à importer
        if mapper.looks_like_project(cwd):
            with Brain.edit() as b:
                b.ensure_project(cwd, source="auto")
            brain = Brain.load()
            proj = brain.project_for_path(cwd)
    path = _project_path(proj)
    if path and cfg["auto_map"]["enabled"] and filesearch.needs_refresh(proj["id"], cfg["auto_map"]["refresh_minutes"]):
        spawn_background(["map", path, "-p", proj["id"], "--quiet"])
    st = load_state(sid)
    source = data.get("source") or "startup"
    st.update({"cwd": cwd, "project": proj["id"] if proj else None, "wiki": bool(wiki_root)})
    if source == "resume" and st.get("started"):
        # Reprise : l'injection de départ est encore dans l'historique (7 reprises sur 7) → les nouveautés seulement.
        text = idx.resume_delta(brain, st.get("injected_at") or st["started"], cfg)
        st["injected_at"] = now_iso()
        save_state(sid, st)
        if text:
            emit("SessionStart", text)
        return
    text, ids, _ = idx.session_context(brain, cwd, cfg, session_id=sid)
    if source in ("compact", "clear"):
        # L'injection précédente et les rappels ont quitté le contexte : on repart de ce qui est visible maintenant
        # (avant : « déjà injectés » gardés, donc plus jamais rappelés après une compaction).
        st["injected"], st["files"], st["recalled"] = sorted(ids), [], 0
        if source == "compact":
            extra, shown = compact_recall(brain, st, data, cfg, proj)
            if extra:
                text = f"{text}\n\n{extra}"
                st["injected"] = sorted(set(ids) | set(shown))
    else:
        st["injected"] = sorted(set(st.get("injected", [])) | set(ids))
        try:
            from . import dream
            note = dream.notice()
            if note:
                text = f"{text}\n\n{note}"
        except Exception as exc:
            log(f"rêve (démarrage) : {exc!r}")
        try:
            from . import optimize
            tip = optimize.notice(cfg)
            if tip:
                text = f"{text}\n\n{tip}"
        except Exception as exc:
            log(f"optimize (démarrage) : {exc!r}")
    if wiki_root:
        try:
            text = f"{text}\n\n{wiki_start(brain, cfg)}".rstrip()
        except Exception as exc:
            log(f"wiki (démarrage) : {exc!r}")
    st["started"] = st.get("started") or now_iso()
    st["injected_at"] = now_iso()
    save_state(sid, st)
    from .common import PLUGIN
    if PLUGIN:  # plugin : lanceur stable à jour, et les consignes du bloc CLAUDE.md passent par l'injection
        from . import plugin
        try:
            plugin.ensure_launcher()
        except OSError as exc:
            log(f"lanceur du plugin : {exc!r}")
        text = f"{plugin.instructions()}\n\n{text}"
    emit("SessionStart", text)


# ------------------------------------------------------------------------------------------ veille PC
def pc_watch(cfg):
    """Veille PC (Windows) : au plus une mesure toutes les check_minutes. On lit « checked » dans pc.json pour
    éviter d'importer tout le module entre deux. Renvoie une ligne pour Claude seulement si le PC est saturé."""
    pcfg = cfg.get("pc") or {}
    if os.name != "nt" or not pcfg.get("enabled", True):
        return ""
    checked = (read_json(STATE_DIR / "pc.json", {}) or {}).get("checked", 0)
    if time.time() - checked < pcfg.get("check_minutes", 10) * 60:
        return ""
    try:
        from . import pc
        return pc.watch(cfg)
    except Exception as exc:
        log(f"veille PC : {exc!r}")
        return ""


# ------------------------------------------------------------------------------------------ UserPromptSubmit
def on_prompt(data, cfg):
    rc = cfg["recall"]
    raw = (data.get("prompt") or "").strip()
    if not rc["enabled"] or len(raw) < 6 or raw.startswith("/"):
        return
    pcline = pc_watch(cfg)
    query = recall_query(raw)
    sid = data.get("session_id")
    st = load_state(sid)
    brain = Brain.load()
    cwd = data.get("cwd") or st.get("cwd")
    proj = brain.project_for_path(cwd) if cwd else None
    injected = set(st.get("injected", []))
    lines = []
    if REMEMBER_RX.search(raw):
        lines.append(f"🧠 L'utilisateur demande de mémoriser : enregistre-le avec `{CMD} add -t <type> -T … -b …` "
                     "(vérifie d'abord les doublons avec `q`).")
    elif RECALL_RX.search(raw):
        lines.append(f"🧠 L'utilisateur fait appel à un souvenir : cherche avec `{CMD} q \"…\"` et `{CMD} journal`.")
    picks = []
    recalled = st.get("recalled", 0)
    if tokenize(query) and recalled < rc["session_cap_items"]:
        for r in search.search_memories(brain, query, limit=10, project=proj["id"] if proj else None, expand=False):
            n = r["node"]
            if n["id"] in injected or n["type"] == "project":
                continue
            if not search.accept_recall(r, rc["min_cov"], rc["min_score"], query=query):
                continue
            picks.append(n)
            if len(picks) >= rc["max_items"]:
                break
    files = []
    if rc["files"] and proj and tokenize(query) and len(st.get("files", [])) < rc["session_cap_files"]:
        from . import filesearch
        files = filesearch.recall_files(proj["id"], query, rc, exclude=set(st.get("files", [])))
    # Lignes entières seulement, dans le budget (jamais une ligne coupée qu'on paierait sans pouvoir s'en servir) ;
    # seuls les éléments vraiment affichés sont marqués « déjà injectés ».
    budget = rc["max_chars"]
    out = list(lines)
    used = sum(len(x) + 1 for x in out)
    shown_mem, shown_files = [], []
    groups = [("🧠 Souvenirs pertinents (cerveau) :",
               [(n, f"- [{TYPES.get(n['type'], n['type'])}] {n['title']} — {gist(n)} `{n['id']}`")
                for n in picks], shown_mem)]
    if files:
        groups.append((f"📁 Fichiers probablement concernés (carte `{proj['id']}`) :",
                       [(f, f"- `{f['path']}` — {short(f['desc'], 100)}") for f in files], shown_files))
    for title, items, shown in groups:
        block, cost = [], len(title) + 1
        for obj, line in items:
            if used + cost + len(line) + 1 > budget:
                break
            block.append(line)
            cost += len(line) + 1
            shown.append(obj)
        if block:
            out += [title] + block
            used += cost
    if pcline:  # la veille PC passe toujours, avant les souvenirs
        out = [pcline] + out
    if not out:
        return
    ctx = "\n".join(out)
    st["recalled"] = recalled + len(shown_mem)
    st["injected"] = sorted(injected | {n["id"] for n in shown_mem})
    st["files"] = sorted(set(st.get("files", [])) | {f["path"] for f in shown_files})
    st["cwd"] = cwd
    save_state(sid, st)
    bump_hits([n["id"] for n in shown_mem])
    emit("UserPromptSubmit", ctx)


# ------------------------------------------------------------------------------------------ Montré ≠ utilisé
NUM_VAL = re.compile(r"\d+[.,]\d+|\d{3,}")
YEARS = {str(y) for y in range(2020, 2036)}


def _key_terms(n, idx, k=4):
    """Les termes les plus distinctifs d'un souvenir (titre + noms propres), par rareté dans tout le cerveau."""
    from .reconcile import entities
    toks = set(tokenize(n["title"]))
    for e in entities(f"{n['title']}\n{n.get('body', '')}"):
        toks.update(tokenize(e))
    toks = [t for t in toks if len(t) >= 4 and not t.isdigit()]
    toks.sort(key=lambda t: (-idx.idf(t), t))
    return toks[:k]


def track_usage(st, scan):
    """Un souvenir injecté compte comme UTILISÉ si ses termes distinctifs (ou une de ses valeurs chiffrées)
    réapparaissent dans ce que Claude a écrit ou fait ensuite. Sert au classement (index, rappel, archivage)."""
    todo = set(st.get("injected", [])) - set(st.get("used", []))
    if not todo or not scan:
        return []
    text = fold(" ".join(scan))
    toks = set(tokenize(text))
    brain = Brain.load()
    idx = search.memory_index(brain)
    used = []
    for nid in sorted(todo):
        n = brain.nodes.get(nid)
        if not n or n["type"] == "project":
            continue
        keys = _key_terms(n, idx)
        hit = sum(1 for t in keys if t in toks)
        nums = {x for x in NUM_VAL.findall(fold(n.get("body", ""))) if len(x) >= 4 and x not in YEARS}
        if nid in text or (keys and hit >= min(2, len(keys))) or any(x in text for x in nums):
            used.append(nid)
    if used:
        st["used"] = sorted(set(st.get("used", [])) | set(used))
        bump_used(used)
    return used


# ------------------------------------------------------------------------------------------ Stop
def on_stop(data, cfg):
    sid, tp = data.get("session_id"), data.get("transcript_path")
    if not sid or not tp:
        return
    st = load_state(sid)
    tx = journal.parse_transcript(tp, st.get("tx"))
    scan = tx.pop("_scan", None)
    st["tx"] = tx
    if scan:
        try:
            track_usage(st, scan)
        except Exception as exc:
            log(f"usage : {exc!r}")
    if cfg["journal"]["enabled"] and time.time() - st.get("journal_at", 0) > 60:
        brain = Brain.load()
        proj = brain.project_for_path(tx.get("cwd") or data.get("cwd") or st.get("cwd") or "")
        journal.upsert(sid, tx, proj["id"] if proj else None, cfg["journal"]["keep"])
        st["journal_at"] = time.time()
    sr = cfg["stop_reminder"]
    block = after_compact = False
    if sr["enabled"] and not data.get("stop_hook_active"):
        base = max(tx.get("last_save_tools", 0), st.get("reminded_at", 0))
        first = base == 0
        threshold = sr["min_tool_calls"] if first else sr["repeat_after"]
        if tx["tools"] - base >= threshold or (first and len(tx.get("edits", [])) >= sr["min_edits"]):
            st["reminded_at"] = tx["tools"]
            block = True
        due = st.pop("obs_due", None)  # posé par PreCompact : le détail de ce qui précède n'est plus que résumé
        noted = tx.get("last_obs_tools", 0)
        if due is not None and not block and not (noted and noted >= due - 20):  # rien de noté juste avant ou après
            st["reminded_at"] = tx["tools"]
            block = after_compact = True
    save_state(sid, st)
    if after_compact:
        sys.stdout.write(json.dumps({"decision": "block", "reason": OBS_REASON}, ensure_ascii=False))
    elif block:
        reason = STOP_REASON
        base = tx.get("last_save_tools", 0)
        cands = [p["t"] for p in tx.get("recent", []) if p.get("i", 0) >= base and CAPTURE_RX.search(p["t"])][-3:]
        if cands:  # capture assistée : les phrases de l'utilisateur qui ressemblent à une préférence ou une décision
            reason += " Candidats repérés dans ses messages : " + " · ".join(f"« {short(c, 160)} »" for c in cands) + "."
        if st.get("wiki"):
            reason += WIKI_REASON
        sys.stdout.write(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


# ------------------------------------------------------------------------------------------ PreCompact / SessionEnd
def on_session_end(data, cfg, event="session-end"):
    sid, tp = data.get("session_id"), data.get("transcript_path")
    st = load_state(sid)
    tx = journal.parse_transcript(tp, st.get("tx")) if tp else (st.get("tx") or {})
    scan = tx.pop("_scan", None)
    st["tx"] = tx
    if scan:
        try:
            track_usage(st, scan)
        except Exception as exc:
            log(f"usage : {exc!r}")
    if event == "pre-compact" and sid and cfg["stop_reminder"]["enabled"]:
        st["obs_due"] = tx.get("tools", 0)  # PreCompact ne peut rien dire à Claude : le Stop suivant demandera les observations
    save_state(sid, st)
    brain = Brain.load()
    proj = brain.project_for_path(tx.get("cwd") or data.get("cwd") or st.get("cwd") or "")
    if cfg["journal"]["enabled"]:
        journal.upsert(sid, tx, proj["id"] if proj else None, cfg["journal"]["keep"])
    path = _project_path(proj)
    if event == "session-end" and path and tx.get("edits") and cfg["auto_map"]["enabled"]:
        spawn_background(["map", path, "-p", proj["id"], "--quiet"])
    if event == "session-end":  # entretien et sauvegarde automatiques, une fois par jour (en arrière-plan)
        daily = [("last_consolidate", ["consolidate", "--auto"], True)]
        daily.append(("last_backup", ["backup", "--auto"], cfg.get("backup", {}).get("enabled", True)))
        for name, args, enabled in daily:
            marker = BRAIN_DIR / "state" / name
            try:
                if enabled and (not marker.exists() or time.time() - marker.stat().st_mtime > 86400):
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_text(now_iso(), encoding="utf-8")
                    spawn_background(args)
            except OSError as exc:
                log(f"{name} : {exc!r}")
    brain = Brain.load()
    idx.rebuild(brain, cfg)
    if event == "session-end" and (brain.data.get("wiki") or {}).get("root") and not brain.data["wiki"].get("missing"):
        try:  # wiki : index.md, entrée « session » au journal, puis commit + pull + push en arrière-plan
            from . import wiki
            wiki.session_close(brain, proj["title"] if proj else None)
            if _auto_sync(brain, cfg):
                spawn_background(["wiki", "sync", "--auto"])
        except Exception as exc:
            log(f"wiki fin de session : {exc!r}")
    if event == "session-end":
        try:  # visualisation 3D et analyse du graphe gardées à jour sans y penser
            from . import viz
            if viz.is_stale():
                viz.render(brain)
        except Exception as exc:
            log(f"viz fin de session : {exc!r}")


# ------------------------------------------------------------------------------------------ PostCompact
def on_post_compact(data, cfg):
    """Après une compaction : le résumé est gardé, dans l'état de session (rappel du SessionStart « compact ») et au
    journal (« où on en était »). Muet : la sortie de ce hook ne s'affiche qu'à l'utilisateur."""
    sid = data.get("session_id")
    summary = data.get("compact_summary")
    if not summary and data.get("transcript_path"):
        summary, _ = journal.last_compact_summary(data["transcript_path"])
    if not sid or not summary:
        return
    st = load_state(sid)
    st["compact_summary"] = journal.summary_part(summary, stop="optional next step", limit=2500)
    st["compacted_at"] = now_iso()
    tx = st.get("tx") or {}
    if tx:
        tx["summary"] = journal.summary_part(summary, limit=800)
        st["tx"] = tx
    save_state(sid, st)
    if tx and cfg["journal"]["enabled"]:
        brain = Brain.load()
        proj = brain.project_for_path(tx.get("cwd") or data.get("cwd") or st.get("cwd") or "")
        journal.upsert(sid, tx, proj["id"] if proj else None, cfg["journal"]["keep"])


HANDLERS = {
    "session-start": on_session_start,
    "prompt": on_prompt,
    "stop": on_stop,
    "pre-compact": lambda d, c: on_session_end(d, c, "pre-compact"),
    "post-compact": on_post_compact,
    "session-end": on_session_end,
}


def run(event) -> int:
    data = read_stdin_json()
    from .common import PLUGIN
    if PLUGIN:
        from . import plugin
        if plugin.classic_install():
            return 0  # plugin installé là où le cerveau classique tourne déjà : ses propres hooks font le travail
    t0 = time.time()
    try:
        handler = HANDLERS.get(event)
        if handler:
            handler(data, load_config())
        else:
            log(f"hook inconnu : {event}")
    except Exception as exc:
        import traceback  # seulement en cas d'erreur : ~7 ms épargnées à chaque hook
        log(f"hook {event} ERREUR {exc!r}\n{traceback.format_exc()}")
    finally:
        elapsed = time.time() - t0
        if elapsed > 2:
            log(f"hook {event} lent : {elapsed:.2f}s")
    return 0
