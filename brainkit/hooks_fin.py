"""Hooks de fin : Stop (fin de tour), PreCompact et SessionEnd, PostCompact ; souvenirs montrés puis utilisés.

Découpé de hooks.py (étape 8 du plan) sans rien changer ; chargé seulement par ces hooks."""
from __future__ import annotations

import json
import sys
import time

from . import hooks as h
from . import journal
from .common import (commun_member, fold, log, now_iso, short, tokenize)
from .hooks import (STOP_REASON, WIKI_REASON, _auto_sync, _Later, _mappable, _project_path, _Rx, daily_due,
                    durable_cue, load_state, project_of, save_state)
from .store import Brain

search = _Later("search", "search", globals())  # chargé au premier usage, comme dans hooks


def _merge_outils(st, tx, tp=None) -> None:
    """Fin de tour : connecteurs vus dans le transcript → outils.json et st["outils_on"] ; registre absent (cerveau
    installé en cours de session) → relu dans les derniers transcripts."""
    o = tx.pop("_outils", None)
    try:
        from . import outils
        if o:
            outils.merge(o)
            st["outils_on"] = outils.session_on(st.get("outils_on"), o)
        elif tp and not outils.FILE.exists():
            outils.bootstrap(outils.recent_transcripts(5))
    except Exception as exc:
        log(f"outils : {exc!r}")


# ------------------------------------------------------------------------------------------ Montré ≠ utilisé
NUM_VAL = _Rx(r"\d+[.,]\d+|\d{3,}")
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


def is_used(n, text, toks, idx) -> bool:
    """Le souvenir a-t-il servi ? Son id, ses termes distinctifs ou une de ses valeurs chiffrées réapparaissent dans
    `text` (ce que Claude a écrit ou fait, déjà plié ; `toks` : ses mots)."""
    keys = _key_terms(n, idx)
    hit = sum(1 for t in keys if t in toks)
    nums = {x for x in NUM_VAL.findall(fold(n.get("body", ""))) if len(x) >= 4 and x not in YEARS}
    return n["id"] in text or (bool(keys) and hit >= min(2, len(keys))) or any(x in text for x in nums)


def track_usage(st, scan, brain=None):
    """Un souvenir injecté compte comme UTILISÉ si ses termes distinctifs (ou une de ses valeurs chiffrées)
    réapparaissent dans ce que Claude a écrit ou fait ensuite. Sert au classement (index, rappel, archivage)."""
    todo = set(st.get("injected", [])) - set(st.get("used", []))
    if not todo or not scan:
        return []
    text = fold(" ".join(scan))
    toks = set(tokenize(text))
    brain = brain or Brain.load()
    idx = search.memory_index(brain)
    used = []
    for nid in sorted(todo):
        n = brain.nodes.get(nid)
        if n and n["type"] != "project" and is_used(n, text, toks, idx):
            used.append(nid)
    if used:
        st["used"] = sorted(set(st.get("used", [])) | set(used))
        h.bump_used(used)
    return used


def after_turn(st, scan, sid):
    """Après une réponse : souvenirs montrés puis utilisés, et exemples étiquetés pour le neurone du rappel. → le cerveau
    s'il a fallu le lire (le reste du hook s'en sert : graph.json lu une seule fois), sinon None."""
    if not scan:
        st.pop("cands", None)  # rien d'écrit ni de fait : pas d'étiquette possible
        return None
    brain = None
    if set(st.get("injected", [])) - set(st.get("used", [])):
        try:
            brain = Brain.load()
            track_usage(st, scan, brain)
        except Exception as exc:
            log(f"usage : {exc!r}")
    if st.get("cands"):
        try:
            from . import neurone
            brain = brain or Brain.load()
            neurone.learn_turn(st, scan, sid, brain)
        except Exception as exc:
            log(f"neurone : {exc!r}")
            st.pop("cands", None)
    return brain


# ------------------------------------------------------------------------------------------ Stop
def unsaved_durable(tx, st) -> list:
    """Messages de l'utilisateur depuis la dernière sauvegarde (`brain add`/`obs`… de la session) qui contiennent une
    phrase durable (même détecteur que le rêve : durable_cue) et que ni le hook (« retiens… ») ni un rappel précédent
    n'ont déjà pris en charge. Vide = le Stop ne bloque pas."""
    base = tx.get("last_save_tools", 0)
    done = set(st.get("auto_saved", [])) | set(st.get("reminded", []))
    return [p["t"] for p in tx.get("recent", []) if p.get("i", 0) >= base and durable_cue(p["t"]) and p["t"] not in done]


def on_stop(data, cfg):
    sid, tp = data.get("session_id"), data.get("transcript_path")
    if not sid or not tp:
        return
    st = load_state(sid)
    tx = journal.parse_transcript(tp, st.get("tx"))
    scan = tx.pop("_scan", None)
    st["tx"] = tx
    _merge_outils(st, tx, tp)
    brain = after_turn(st, scan, sid)
    if tx.get("skills"):
        try:
            from . import skills
            skills.record_usage(st, tx)
        except Exception as exc:
            log(f"skills (usage) : {exc!r}")
    if cfg["journal"]["enabled"] and time.time() - st.get("journal_at", 0) > 60:
        pid = project_of(tx.get("cwd") or data.get("cwd") or st.get("cwd") or "", brain)
        journal.upsert(sid, tx, pid, cfg["journal"]["keep"])
        st["journal_at"] = time.time()
    cands = []
    st.pop("obs_due", None)  # ancien rappel d'après compaction (retiré : seul un message durable fait bloquer)
    if cfg["stop_reminder"]["enabled"] and not data.get("stop_hook_active"):  # jamais deux blocages de suite
        cands = unsaved_durable(tx, st)
        if cands:  # les mêmes phrases ne sont pas redemandées au tour suivant, même si Claude n'a rien enregistré
            st["reminded"] = (st.get("reminded", []) + cands)[-15:]
    save_state(sid, st)
    try:  # cerveau commun : récupéré pendant que l'utilisateur lit la réponse → son prochain message voit les nouveautés
        if commun_member(cfg):
            from . import commun
            commun.maybe_pull()
    except Exception as exc:
        log(f"commun (fin de tour) : {exc!r}")
    if cands:
        reason = STOP_REASON
        # capture assistée : les phrases de l'utilisateur qui ressemblent à une préférence ou une décision, pas encore gardées
        reason += " Candidats repérés dans ses messages : " + " · ".join(f"« {short(c, 160)} »" for c in cands[-3:]) + "."
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
    _merge_outils(st, tx, tp)
    after_turn(st, scan, sid)
    if tx.get("skills"):
        try:
            from . import skills
            skills.record_usage(st, tx)
        except Exception as exc:
            log(f"skills (usage) : {exc!r}")
    save_state(sid, st)
    from . import wikistore
    # Le projet du dossier suffit (project_of : sans relire graph.json s'il n'a pas changé) ; le wiki, lui, lit le cerveau
    brain = Brain.load() if event == "session-end" and wikistore.resolve()[0] != "classic" else None
    pid = project_of(tx.get("cwd") or data.get("cwd") or st.get("cwd") or "", brain)
    if cfg["journal"]["enabled"]:
        journal.upsert(sid, tx, pid, cfg["journal"]["keep"])
    if event == "session-end" and pid and tx.get("edits") and cfg["auto_map"]["enabled"]:
        brain = brain or Brain.load()
        path = _project_path(brain.nodes.get(pid))
        if path and _mappable(brain.nodes.get(pid), path):
            h.spawn_background(["map", path, "-p", pid, "--quiet"])
    if event == "session-end":  # entretien et sauvegarde automatiques, une fois par jour (en arrière-plan)
        for args in daily_due(cfg):
            h.spawn_background(args)
    in_wiki = event == "session-end" and brain is not None and bool((brain.data.get("wiki") or {}).get("root")) \
        and not brain.data["wiki"].get("missing")
    if in_wiki:
        try:  # wiki : journal de ce PC et entrée « session » de log.md, sur le disque avant le commit qui suit (quelques ms)
            from . import wiki
            proj = brain.nodes.get(pid) if pid else None
            wiki.session_close(brain, proj["title"] if proj else None, derived=False)
        except Exception as exc:
            log(f"wiki fin de session : {exc!r}")
    # BRAIN.md, vues 3D et 2D (avec l'analyse du graphe à jour) et index du démarrage de ce projet, prêts pour la session
    # suivante ou celle d'après la compaction : la tâche de fond des vues (vues.py) — avant, 120 à 350 ms dans le hook.
    # En mode wiki, elle refait aussi index.md, la page Cerveau et la carte du coffre (avant : 250 à 300 ms dans le hook
    # à 3 000 pages ; aucun n'est dans git, tous se refont à la fin de session suivante si le PC s'éteint avant).
    # Demandées même si d'autres sont en cours : celles-là ont pu lire le journal avant cette session.
    queued = False
    try:
        from . import vues
        queued = vues.request(wiki=in_wiki)
    except Exception as exc:
        log(f"vues ({event}) : {exc!r}")
    if in_wiki:
        try:
            if not queued:  # aucune tâche de fond possible : refaites ici, comme avant
                from . import wiki
                wiki.write_derived(brain)
            if _auto_sync(brain, cfg):  # commit + pull + push en arrière-plan
                h.spawn_background(["wiki", "sync", "--auto"])
        except Exception as exc:
            log(f"wiki fin de session : {exc!r}")
    if event == "session-end":
        try:  # cerveau commun : ma part publique (et le journal des projets communs) part en fin de session
            from . import commun
            if commun.member():
                commun.spawn(["commun", "sync", "--auto"])
        except Exception as exc:
            log(f"commun fin de session : {exc!r}")


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
