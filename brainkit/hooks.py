"""Points d'accroche Claude Code : SessionStart, UserPromptSubmit, Stop, PreCompact, SessionEnd.

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
from .common import (BRAIN_DIR, BRAIN_PY, CMD, SESSIONS_DIR, fold, load_config, log, now_iso, read_json,
                     read_stdin_json, short, tokenize, write_json)
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
                  close_fds=True, cwd=str(BRAIN_DIR))
        if os.name == "nt":
            kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
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


# ------------------------------------------------------------------------------------------ SessionStart
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
    if not proj and cfg["auto_map"]["enabled"]:
        from . import mapper  # dossier inconnu seulement : le cartographe est lourd à importer
        if mapper.looks_like_project(cwd):
            with Brain.edit() as b:
                b.ensure_project(cwd, source="auto")
            brain = Brain.load()
            proj = brain.project_for_path(cwd)
    path = _project_path(proj)
    if path and cfg["auto_map"]["enabled"] and filesearch.needs_refresh(proj["id"], cfg["auto_map"]["refresh_minutes"]):
        spawn_background(["map", path, "-p", proj["id"], "--quiet"])
    text, ids, _ = idx.session_context(brain, cwd, cfg, session_id=sid)
    try:
        from . import dream
        note = dream.notice()
        if note:
            text = f"{text}\n\n{note}"
    except Exception as exc:
        log(f"rêve (démarrage) : {exc!r}")
    st = load_state(sid)
    st.update({"cwd": cwd, "project": proj["id"] if proj else None, "started": st.get("started") or now_iso()})
    st["injected"] = sorted(set(st.get("injected", [])) | set(ids))
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


# ------------------------------------------------------------------------------------------ UserPromptSubmit
def on_prompt(data, cfg):
    rc = cfg["recall"]
    raw = (data.get("prompt") or "").strip()
    if not rc["enabled"] or len(raw) < 6 or raw.startswith("/"):
        return
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
               [(n, f"- [{TYPES.get(n['type'], n['type'])}] {n['title']} — {short(n.get('body', ''), 220)} `{n['id']}`")
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
    if event == "session-end":
        try:  # visualisation 3D et analyse du graphe gardées à jour sans y penser
            from . import viz
            if viz.is_stale():
                viz.render(brain)
        except Exception as exc:
            log(f"viz fin de session : {exc!r}")


HANDLERS = {
    "session-start": on_session_start,
    "prompt": on_prompt,
    "stop": on_stop,
    "pre-compact": lambda d, c: on_session_end(d, c, "pre-compact"),
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
