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
from .common import (BRAIN_DIR, BRAIN_PY, CMD, SESSIONS_DIR, STATE_DIR, budget_chars, days_since, fold, load_config, log,
                     now_iso, parse_iso, read_json, read_stdin_json, set_config, short, tokenize, write_json)
from .store import TYPES, Brain, bump_hits, bump_used

OBS_HOW = (f"une ligne courte chacune, priorisées (🔴 décision, blocage, préférence · 🟡 avancée, constat · 🟢 détail) : "
           f"`{CMD} obs \"🔴 …\" \"🟡 …\"`")
STOP_REASON = (
    "🧠 Cerveau — avant de conclure, en UN SEUL appel Bash (commandes enchaînées avec &&) : 1) note 3 à 5 observations "
    f"datées de cette session, {OBS_HOW} ; 2) enregistre le durable (0 à 3 entrées) : préférence ou correction de "
    "l'utilisateur (feedback), info sur lui (user), décision (decision), état d'un travail en cours (fact), piège "
    "résolu / solution qui marche (learning), ressource (reference), suite à faire (todo) — "
    f"`{CMD} add -t <type> -T \"titre court\" -b \"fait + pourquoi + comment l'appliquer\"` (`-p none` si hors du "
    "projet courant ; `add` écarte seul les doublons évidents, `edit <id>` corrige un souvenir). Jamais de secrets, "
    "mots de passe ni infos sensibles sur des tiers."
)
WIKI_REASON = (" 3) Wiki : une réponse qui vaut d'être gardée (synthèse, comparaison, analyse) → page Analyses "
               f"(`{CMD} add -t analyse -T … -b - --resume …`) puis `{CMD} wiki log query \"…\"` ; une source lue ou "
               f"citée → `{CMD} wiki add` puis la méthode du CLAUDE.md du wiki.")
OBS_REASON = ("🧠 Cerveau — le contexte vient d'être compacté : avant de conclure, note 3 à 5 observations datées de "
              "cette session (d'après le résumé et la suite) en UN SEUL appel Bash (commandes enchaînées avec &&), "
              f"{OBS_HOW}.")
REMEMBER_RX = re.compile(r"\b(souviens[- ]toi|retiens|m[ée]moris|note (?:que|bien|[çc]a)|n'oublie pas|"
                         r"garde (?:[çc]a |le |la |les )?en m[ée]moire|remember|ajoute (?:[çc]a |le |la )?(?:au|dans le) cerveau)",
                         re.I)
NUM_NOISE = re.compile(r"(?<![\w-])(?:\d{1,2}|(?:19|20)\d{2})(?![\w-])")
CAPTURE_RX = re.compile(r"\b(je (?:veux|voudrais|pr[ée]f[èe]re|n'aime pas|d[ée]teste)|toujours|jamais|plut[ôo]t|"
                        r"arr[êe]te de|ne (?:fais|mets|touche|change) (?:pas|plus|jamais)|n'oublie pas|retiens|"
                        r"d[ée]sormais|dor[ée]navant|[àa] partir de maintenant|on part sur|on garde|c'est bon pour|"
                        r"ok pour|vas-y pour|pas comme [çc]a|c'est faux|corrige|il faut que tu|tu dois)\b", re.I)
TASK_CUES = {"corrige", "il faut que tu", "tu dois"}  # seuls, un ordre du moment (« oui corrige les 4 tests »)


def durable_cue(text) -> bool:
    """Préférence, correction ou décision possible ? Pas quand le seul indice est un ordre de travail."""
    return bool({fold(m.group(1)) for m in CAPTURE_RX.finditer(text)} - TASK_CUES)


RECALL_RX = re.compile(r"\b(tu te souviens|te rappelles|rappelle[- ]moi|on avait (?:dit|fait|d[ée]cid)|"
                       r"la derni[èe]re fois|d[ée]j[àa] (?:fait|vu|dit)|qu'est-ce qu'on avait)", re.I)


def recall_query(raw) -> str:
    """Message → requête de rappel : blocs collés et balises retirés, nombres sans valeur (« 12 fois 8 », « le 15/10 »,
    « 2026 ») effacés. Partagé avec `brain bench` pour mesurer exactement ce que fait le hook."""
    return NUM_NOISE.sub(" ", journal.clean_prompt(raw, 600))


def context_query(raw, query) -> str:
    """Requête gardée dans l'état de la session, contexte des messages suivants pour le neurone du rappel : sans secret
    ni coordonnées de tiers, comme au journal."""
    from .privacy import redact_contacts
    clean = redact_contacts(raw)
    return query if clean == raw else recall_query(re.sub(r"«[^»]*»", " ", clean))


def gist(n, chars=220) -> str:
    """Ce qu'on montre d'un souvenir : le résumé d'une page du wiki s'il existe, sinon le début de son contenu."""
    return short((n.get("meta") or {}).get("resume") or n.get("body", ""), chars)


def label(n) -> str:
    """Type d'un souvenir, avec l'ami qui l'a partagé pour une page du cerveau commun."""
    who = (n.get("meta") or {}).get("commun_par")
    return TYPES.get(n["type"], n["type"]) + (f" 🤝 {who}" if who else "")


def emit(event, context, message=None):
    """Sortie du hook : un seul objet JSON — `additionalContext` (lu par Claude) et/ou `systemMessage` (vu par
    l'utilisateur seulement : aucun token de contexte)."""
    out = {}
    if message:
        out["systemMessage"] = message
    if context:
        out["hookSpecificOutput"] = {"hookEventName": event, "additionalContext": context}
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
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
        if os.name == "nt" and exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
            exe = exe.parent / "python.exe"  # sans console (pythonw), git se bloque : voir creationflags
        kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                  close_fds=True, cwd=str(BRAIN_DIR), env={**os.environ, "BRAIN_BG": "1"})
        if os.name == "nt":
            # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | BELOW_NORMAL_PRIORITY_CLASS : console cachée, priorité basse.
            # Pas pythonw + DETACHED_PROCESS : sans console, git ne répond plus (Git 2.56, Windows 11, 21/10/2026)
            kw["creationflags"] = 0x08000000 | 0x00000200 | 0x00004000
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
    from . import obsidian, wiki, wikistore as ws
    if _auto_sync(brain, cfg) and wiki.due_sync((cfg.get("wiki") or {}).get("sync_minutes", 30)):
        wiki.mark_pulled()
        spawn_background(["wiki", "sync", "--auto", "--no-push"])
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
            spawn_background(["wiki", "capture"])
    except Exception as exc:
        log(f"obsidian (notes du jour) : {exc!r}")
    return text


def journal_catchup(cfg, sid, launch=spawn_background) -> bool:
    """Rattrapage du journal, au plus une fois par jour : des sessions de Claude Code des 7 derniers jours que les hooks
    n'ont pas vues (`python` introuvable, plugin tout neuf…) → import en arrière-plan, jamais dans le délai du hook."""
    jc = cfg.get("journal") or {}
    if not jc.get("enabled", True) or days_since(jc.get("rattrapage_le")) < 1:
        return False
    set_config("journal.rattrapage_le", now_iso())  # jour réservé : une autre session qui démarre n'en lance pas une 2e
    return bool(journal.missing(exclude=(sid,), limit=1)) and launch(["journal", "--backfill"])


def garde_due(cfg) -> bool:
    """Garde de consommation due (toutes les 2 h au plus) ? Si oui, le créneau est réservé : une autre session qui
    démarre, ou la veille automatique, n'en lance pas une deuxième."""
    garde = cfg.get("garde") if isinstance(cfg.get("garde"), dict) else {}
    if min(days_since(garde.get("le")), days_since(garde.get("lance_le"))) * 24 < 2:
        return False
    set_config("garde.lance_le", now_iso())
    return True


def daily_due(cfg) -> list:
    """Entretien et sauvegarde automatiques, une fois par jour : arguments de brain.py des tâches dues (marqueur posé)."""
    out = []
    for name, args, enabled in (("last_consolidate", ["consolidate", "--auto"], True),
                                ("last_backup", ["backup", "--auto"], cfg.get("backup", {}).get("enabled", True))):
        marker = BRAIN_DIR / "state" / name
        try:
            if enabled and (not marker.exists() or time.time() - marker.stat().st_mtime > 86400):
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(now_iso(), encoding="utf-8")
                out.append(args)
        except OSError as exc:
            log(f"{name} : {exc!r}")
    return out


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
    try:  # cerveau commun : les nouveautés des amis avant de construire l'index (attente brève si la dernière est vieille)
        from . import commun
        commun.maybe_pull(wait=4)
    except Exception as exc:
        log(f"commun (démarrage) : {exc!r}")
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
            spawn_background(["eco", "--cache", "auto"])
        except Exception as exc:
            log(f"éco (cache) : {exc!r}")
    if ecfg.get("plugins_auto") and days_since(ecfg.get("plugins_vus_le")) >= 1:
        try:  # veille quotidienne des plugins inutilisés : en arrière-plan (le parcours des transcripts ne tient pas dans le hook)
            set_config("eco.plugins_vus_le", now_iso())  # jour réservé : une autre session qui démarre n'en lance pas une 2e
            spawn_background(["eco", "--plugins-auto"])
        except Exception as exc:
            log(f"éco (veille des plugins) : {exc!r}")
    try:  # garde de consommation : sessions qui mangent la journée (toutes les 2 h au plus, en arrière-plan)
        if garde_due(cfg):
            spawn_background(["tokens", "--garde"])
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
            spawn_background(["auto", "--reparer"])
    except Exception as exc:
        log(f"veille (réparation) : {exc!r}")
    if source == "resume" and st.get("started"):
        # Reprise : l'injection de départ est encore dans l'historique (7 reprises sur 7) → les nouveautés seulement.
        text = idx.resume_delta(brain, st.get("injected_at") or st["started"], cfg)
        st["injected_at"] = now_iso()
        save_state(sid, st)
        if eco_line:
            text = f"{text}\n\n{eco_line}".strip()
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
            from . import skills
            if (cfg.get("skills") or {}).get("enabled", True):
                warn = skills.notice()
                if warn:
                    text = f"{text}\n\n{warn}"
        except Exception as exc:
            log(f"skills (démarrage) : {exc!r}")
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
    st["started"] = st.get("started") or now_iso()
    st["injected_at"] = now_iso()
    save_state(sid, st)
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
        text = f"{plugin.instructions()}\n\n" + (f"{notice}\n\n" if notice else "") + text
    else:  # cerveau classique : skills métier (cerveau e-commerce…) posées ou mises à jour dans ~/.claude/skills
        if eco_line:  # comme le passage au plugin : annoncé une fois à l'utilisateur
            text = f"{text}\n\n{eco_line} (dis-le à l'utilisateur en une phrase au début de ta réponse)"
        try:
            from . import install
            install.sync_skills(quick=True)
        except Exception as exc:
            log(f"skills métier (démarrage) : {exc!r}")
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
TAIL_BYTES = 256 * 1024  # fin du transcript lue pour la taille du contexte (élargie si la dernière réponse est plus grosse)


PAUSE_MIN_CTX = 100_000  # en dessous, relire la conversation après une pause coûte peu : pas d'alerte


def _epoch(value) -> float:
    d = parse_iso(value)
    return d.timestamp() if d else 0.0


def last_request(path) -> tuple:
    """Dernière requête de la conversation principale, lue dans la FIN du transcript → (taille du contexte en tokens :
    entrée + cache créé + cache lu, heure en secondes epoch ou 0, durée du cache vue dans les dernières écritures — 300
    ou 3600 s — ou 0). Les lignes d'une même réponse portent le même usage : jamais additionnées. (0, 0, 0) si
    introuvable ; aucune erreur ne remonte."""
    ctx, ts = 0, 0.0
    try:
        with open(path, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            for tail in (TAIL_BYTES, 4 * TAIL_BYTES, 16 * TAIL_BYTES):
                fh.seek(max(0, size - tail))
                lines = fh.read().split(b"\n")
                if size > tail:
                    lines = lines[1:]  # la première ligne est coupée
                for raw in reversed(lines):
                    if b'"usage"' not in raw or b'"assistant"' not in raw:
                        continue
                    try:
                        o = json.loads(raw)
                        u = o["message"]["usage"] if o.get("type") == "assistant" and not o.get("isSidechain") else None
                        total = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                                   "cache_read_input_tokens")) if u else 0
                        cc = u.get("cache_creation") if total else None
                        h1 = int(cc.get("ephemeral_1h_input_tokens") or 0) if isinstance(cc, dict) else 0
                        m5 = int(cc.get("ephemeral_5m_input_tokens") or 0) if isinstance(cc, dict) else 0
                    except (ValueError, TypeError, KeyError, AttributeError):
                        continue
                    if not total:
                        continue
                    if not ctx:
                        ctx, ts = total, _epoch(o.get("timestamp"))
                    if h1 or m5:  # durée du cache : celle des dernières écritures
                        return ctx, ts, 3600 if h1 >= m5 else 300
                if ctx or size <= tail:
                    break
    except (OSError, TypeError, ValueError):
        pass
    return ctx, ts, 0


def last_context(path) -> int:
    """Taille du contexte (tokens) à la dernière requête de la conversation ; 0 si introuvable."""
    return last_request(path)[0]


def _cache_ttl() -> int:
    """Durée du cache de prompt (s) d'après les réglages, quand le transcript ne la montre pas : 1 h par défaut
    (abonnement, conversation principale), 5 min quand c'est demandé (variables d'environnement, promptCacheTtl)."""
    if os.environ.get("FORCE_PROMPT_CACHING_5M", "").strip().lower() not in ("", "0", "false"):
        return 300
    v = os.environ.get("CLAUDE_CODE_PROMPT_CACHE_TTL", "").strip().lower()
    if not v:
        try:
            from . import eco
            settings, _ = eco.read_settings()
            v = str(settings.get("promptCacheTtl") or "").strip().lower()
        except Exception:
            v = ""
    return 300 if v == "5m" else 3600


def _duree(sec) -> str:
    return f"{round(sec / 86400)} j" if sec >= 86400 else f"{round(sec / 3600)} h" if sec >= 3600 else f"{round(sec / 60)} min"


def pause_alert(size, ts, ttl=0, now=None) -> str:
    """Retour après une pause plus longue que la durée du cache, sur une grosse conversation : ce message relit tout au
    prix fort. Un message pour l'UTILISATEUR (zéro token pour Claude), ou ''."""
    if size < PAUSE_MIN_CTX or not ts:
        return ""
    gap = (now or time.time()) - ts
    if gap <= 300 or gap <= (ttl or _cache_ttl()):
        return ""
    return (f"⏸ Reprise après {_duree(gap)} : le cache a expiré, ce message relit toute la conversation "
            f"(≈{round(size / 1000)} k tokens) au prix fort. Après une pause, nouveau sujet → /clear d'abord (le cerveau "
            "garde l'essentiel).")


def context_alert(data, cfg) -> str:
    """Un message pour l'UTILISATEUR (`systemMessage`), jamais pour Claude — chaque message relit toute la conversation :
    reprise après une pause qui a vidé le cache (`eco.alerte_pause`), sinon palier suivant de `eco.alerte_contexte`
    (signalé une fois par session)."""
    ecfg = cfg.get("eco") or {}
    steps = sorted(int(x) for x in ecfg.get("alerte_contexte") or [] if isinstance(x, (int, float)))
    pause = ecfg.get("alerte_pause", True)
    sid, tp = data.get("session_id"), data.get("transcript_path")
    if not (steps or pause) or not sid or not tp:
        return ""
    size, ts, ttl = last_request(tp)
    note = pause_alert(size, ts, ttl) if pause else ""
    if not steps:
        return note
    reached = max((x for x in steps if size >= x), default=0)
    st = load_state(sid)
    done = st.get("eco_alerte", 0)
    if reached != done:
        st["eco_alerte"] = reached  # plus bas qu'avant (compaction, /clear) : les paliers se réarment
        save_state(sid, st)
        if reached > done and not note:
            note = (f"💡 Conversation à ≈{round(size / 1000)} k tokens : chaque message la relit en entier. Nouveau "
                    "sujet ? Tape /clear (le cerveau garde l'essentiel) ou /compact.")
    return note


# Demande explicite (« retiens que… ») : le hook l'enregistre lui-même.
REM_BLOCK_RX = re.compile(r"```.*?```|<pasted_content[^>]*>.*?</pasted_content>|<(system-reminder|ide_[a-z_]+)[^>]*>.*?</\1>",
                          re.S)
REM_LEAD_RX = re.compile(r"(?:(?:ok|okay|bon|alors|donc|et|puis|aussi|dis|[ée]coute|stp|svp|please)\b[\s,;:!.\-–—]*)*", re.I)
REM_LINK_RX = re.compile(r"[\s,;:!\-–—]*(?:(?:bien|[çc]a|cela|ceci)\b[\s,;:!\-–—]*)*(?:(?:que\b|qu['’]|that\b|to\b)\s*)?", re.I)
REM_STATEMENT_RX = re.compile(r"\s*(?:qu(?:e\b|['’])|that\b|:)", re.I)  # « n'oublie pas que… » : un fait, pas un rappel
REM_OBJECT_RX = re.compile(r"\s*(?:qu(?:e\b|['’])|that\b|[çc]a\b|cela\b|ceci\b|bien\b|:)", re.I)
REM_ANAPHORA_RX = re.compile(r"(?:tout\s+)?ce\s+(?:que|qu['’]|qui)\b[^:]*:?", re.I)  # « retiens ce que je viens de dire »
REM_TITLE, REM_BODY, REM_MAX = 80, 600, 3  # car. du titre, du texte gardé ; phrases enregistrées par message


def remember_texts(raw) -> list:
    """Les phrases à retenir d'un message « retiens… » : celle du déclencheur, sans lui ni ses liaisons (« retiens que… »,
    « n'oublie pas de… »). Rien (Claude, lui, voit de quoi il s'agit) si le déclencheur n'ouvre pas la phrase (« ne retiens
    pas… »), si c'est une question, si rien ne suit ou si ça renvoie à autre chose (« retiens ça », « ce que je viens de
    dire »), si « n'oublie pas de… » ou « souviens-toi de… » ne sont qu'un rappel ou un appel au souvenir (il faut « que… »
    ou une règle : « toujours », « jamais »…), ou si « mémorise les résultats » parle de code.
    Un déclencheur suivi de « : » prend la suite du paragraphe (liste)."""
    out = []
    for para in re.split(r"\n\s*\n", REM_BLOCK_RX.sub(" ", str(raw)[:20000])):
        sents = [re.sub(r"^\s*(?:[-*•>]+|\d+[.)])\s*", "", x).strip() for x in re.split(r"(?<=[.!?…])\s+|\n", para)]
        sents = [x for x in sents if x]
        for i, sent in enumerate(sents):
            m = REMEMBER_RX.search(sent)
            head = sent[:m.start()].strip() if m else ""
            if not m or sent.endswith("?") or (head and not head.endswith((",", ";", ":")) and not REM_LEAD_RX.fullmatch(head)):
                continue
            end = m.end()
            while end < len(sent) and sent[end].isalpha():  # « mémoris » → « mémorise »
                end += 1
            word, tail = fold(m.group(0)), sent[end:]
            if (word.startswith("memoris") and not REM_OBJECT_RX.match(tail)) \
                    or (word.startswith(("n'oublie", "souviens", "remember"))
                        and not (REM_STATEMENT_RX.match(tail) or CAPTURE_RX.search(tail))):
                continue
            tail = tail[REM_LINK_RX.match(tail).end():]
            if word.startswith(("n'oublie", "souviens")):
                tail = re.sub(r"^(?:de\b|d['’])\s*", "", tail, flags=re.I)
            text = f"{'' if REM_LEAD_RX.fullmatch(head) else head} {tail}"
            if sent.endswith(":"):
                text += " ; ".join([""] + sents[i + 1:])
            text = " ".join(text.split()).strip(" ;,:-–—").rstrip(".!?… ")
            if REM_ANAPHORA_RX.match(text):  # ce que je viens de dire : toujours pnpm → ce qui suit les deux-points
                text = text.split(":", 1)[1].strip() if ":" in text else ""
            if len(tokenize(text, keep_stop=True)) >= 3 and text[:1].upper() + text[1:] not in out:
                out.append(text[:1].upper() + text[1:])
            if sent.endswith(":"):
                break
    return out[:REM_MAX]


def _remember_one(b, text, cwd) -> str:
    """Un souvenir enregistré comme `brain add` : complète celui qui dit déjà ça, remplace celui dont la valeur change,
    sinon en crée un (règle si c'est une préférence, sinon fait du projet courant). → son id."""
    from . import reconcile
    from .common import fmt_date
    ntype = "feedback" if CAPTURE_RX.search(text) else "fact"
    title, body = short(text, REM_TITLE), f"{short(text, REM_BODY)} (noté le {fmt_date(now_iso())})"
    proj = None if ntype == "feedback" else b.project_for_path(cwd)
    pid = proj["id"] if proj else None
    dec = reconcile.decide(b, ntype, title, text, pid)  # comparé sans la date : le même propos redit un autre jour = doublon
    if dec["action"] == "merge":
        old = dec["target"]
        has = fold(text) in fold(old.get("body", ""))
        b.update(old["id"], body=old.get("body", "") if has else f"{old.get('body', '')}\n{body}".strip())
        b.adjust_confidence(old["id"], +0.1)  # redit : un peu plus sûr
        return old["id"]
    node = b.add(ntype, title, body, project=pid, source="auto")
    if dec["action"] == "update":  # même sujet, valeur changée : l'ancien est archivé (consultable)
        b.supersede(node["id"], dec["target"]["id"])
    return node["id"]


def remember_now(data, raw) -> str:
    """Demande explicite (« retiens que… ») : enregistrée par le hook lui-même — zéro token, et rien n'est perdu si Claude
    oublie. Mêmes règles que `brain add` : anti-doublon, jamais de secret (la phrase est alors écartée).
    → la ligne pour Claude, ou '' si le hook ne peut pas s'en charger (Claude fait alors `add`, comme avant)."""
    from .privacy import find
    found = {t: find(t) for t in remember_texts(raw)}
    leaks = sorted({x for v in found.values() for x in v})
    texts, ids = [t for t, v in found.items() if not v], []
    if texts and data.get("simulation"):  # `brain recall` : montrer sans enregistrer
        return "🧠 (simulation) serait enregistré tel quel : " + " · ".join(
            f"[{TYPES['feedback' if CAPTURE_RX.search(t) else 'fact']}] « {short(t, REM_TITLE)} »" for t in texts)
    if texts:
        with Brain.edit(timeout=2.5) as b:
            ids = [_remember_one(b, text, data.get("cwd")) for text in texts]
        sid = data.get("session_id")
        if sid:  # déjà montrés à Claude : ni rappelés dans ce message, ni redemandés en fin de tâche
            st = load_state(sid)
            st["injected"] = sorted(set(st.get("injected", [])) | set(ids))
            said = journal.clean_prompt(raw, 300)
            st["auto_saved"] = [x for x in st.get("auto_saved", []) if x != said][-9:] + [said]
            save_state(sid, st)
    lines = []
    if ids:
        many = len(ids) > 1
        lines.append(f"🧠 Déjà enregistré{'s tels quels' if many else ' tel quel'} ({', '.join(f'`{x}`' for x in ids)}) : "
                     f"complète-{'les' if many else 'le'} avec `{CMD} edit {'<id>' if many else ids[0]}` seulement si c'est utile")
    if leaks:
        lines.append(f"🧠 Secret probable dans le message ({', '.join(leaks)}) : non enregistré, ne le copie jamais dans le cerveau")
    return "\n".join(lines)


def on_prompt(data, cfg):
    raw = (data.get("prompt") or "").strip()
    try:  # cerveau commun : les pages des amis, récupérées en arrière-plan (au plus une fois par minute)
        from . import commun
        commun.maybe_pull(wait=2.5)
    except Exception as exc:
        log(f"commun (message) : {exc!r}")
    alert = ""
    if not raw.startswith("/"):
        try:
            alert = context_alert(data, cfg)
        except Exception as exc:
            log(f"alerte contexte : {exc!r}")
    saved = ""
    if not raw.startswith("/") and REMEMBER_RX.search(raw):
        try:  # « retiens que… » : enregistré ici même, indépendamment du rappel automatique
            saved = remember_now(data, raw)
        except Exception as exc:
            log(f"mémorisation automatique : {exc!r}")
    ctx = recall_context(data, cfg, raw, saved) if cfg["recall"]["enabled"] and len(raw) >= 6 and not raw.startswith("/") \
        else saved
    emit("UserPromptSubmit", ctx, alert)


MEM_HEADER = "🧠 Souvenirs pertinents (cerveau) :"


def memory_line(n, full=True) -> str:
    """Ligne d'un souvenir dans le rappel : complète (type, titre, résumé, id) ou titre seul (`show <id>` au besoin)."""
    if full:
        return f"- [{label(n)}] {n['title']} — {gist(n)} `{n['id']}`"
    return f"- [{label(n)}] {n['title']} `{n['id']}`"


def _rule_picks(found, injected, rc, accept) -> list:
    """Règle fixe : dans l'ordre du classement, les souvenirs que le filtre anti-bruit laisse passer."""
    out = []
    for r in found:
        n = r["node"]
        if n["id"] in injected or n["type"] == "project" or not accept(r):
            continue
        out.append((n, memory_line(n)))
        if len(out) >= rc["max_items"]:
            break
    return out


def pick_memories(brain, query, rc, project=None, injected=(), before=None, prev=(), raw=None, log_to=None) -> list:
    """Souvenirs à injecter pour un message → [(souvenir, ligne)].
    Règle fixe (`recall.neurone` « off », ou neurone pas encore appris) : ceux que `accept_recall` laisse passer, en
    ligne complète. Neurone appris sur les échanges de cet utilisateur (neurone.py) : les meilleurs candidats classés
    par probabilité d'être utiles ; ligne complète si elle est forte (≥ neurone_haut), titre seul pour les autres que la
    règle accepte (rien de ce qu'elle aurait montré n'est caché) — Claude lit le reste d'un `show` s'il en a besoin.
    `before` : rejeu (seuls les souvenirs écrits avant) ; `prev` : requêtes des messages précédents de la session ;
    `log_to` : liste qui reçoit les candidats et leurs traits (apprentissage, étiquetés au Stop)."""
    learn = rc.get("neurone", "auto") != "off"
    found = search.search_memories(brain, query, limit=30 if before or learn else 10, project=project, expand=False)
    if before:
        found = [r for r in found if (r["node"].get("created") or "")[:19] <= before]

    def accept(r):
        return search.accept_recall(r, rc["min_cov"], rc["min_score"], query=query)

    if not learn:
        return _rule_picks(found, injected, rc, accept)
    from . import neurone
    cands = [r for r in found if r["node"]["type"] != "project"][:neurone.TOP]
    accs = [accept(r) for r in cands]
    feats = neurone.features(search.memory_index(brain), query, cands, accs, project, prev, before or now_iso(),
                             len(raw or query))
    if log_to is not None:
        log_to.extend({"id": r["node"]["id"], "f": [round(x, 4) for x in f],
                       "c": [len(memory_line(r["node"])), len(memory_line(r["node"], False))]}
                      for r, f in zip(cands, feats))
    model = neurone.load()
    if model is None:  # pas encore assez d'exemples (ou pas mieux que la règle) : la règle, comme avant
        return _rule_picks(found if before else found[:10], injected, rc, accept)
    probs = [model.predict(f) for f in feats]
    return [(r["node"], memory_line(r["node"], full)) for r, full in neurone.choose(cands, probs, accs, injected, rc)]


FICHE_CHARS = 800  # part du budget du rappel prise au plus par une fiche de synthèse


def overview_lines(brain, query, proj, st) -> tuple:
    """Question large (« où en est la boutique ? », « le point sur… », « bilan ») : aucun souvenir ne la couvre seul,
    la fiche de synthèse du sujet si → (lignes entières dans FICHE_CHARS, une fois par fiche et par session ; projet
    nommé ou None, pour écarter les souvenirs d'autres sujets qui ne font que le citer)."""
    if not search.OVERVIEW_RX.search(query):
        return [], None
    found = search.search_memories(brain, query, limit=10, project=proj["id"] if proj else None, expand=False)
    f = search._fiche_for(brain, query, found) if found else None
    # Projet nommé (« le point sur nestwise », « où en est le projet aide ») : sa fiche projet, que le rappel ordinaire
    # écarte, sauf si la fiche de synthèse trouvée est déjà la sienne (boutique → fiche dropshipping). Nommé = titre qui
    # couvre la question, parmi les 3 premiers, et seul projet dans ce cas (« le cerveau » : cerveau-dev ou -plateforme ?).
    topic = [t for t in tokenize(query) if t not in search.OVERVIEW_TOKENS and t not in ("projet", "projets")]
    named = [r for r in found if r["node"]["type"] == "project" and search._covers(r["node"], topic)] if topic else []
    top = named[0]["node"] if len(named) == 1 and named[0] in found[:3] \
        and named[0]["score"] >= 0.5 * found[0]["score"] else None
    if top and (not f or (f["fiche"].get("project") or "") != top["id"]):
        if top["id"] in st.get("fiches", []):
            return [], top["id"]
        st["fiches"] = st.get("fiches", []) + [top["id"]]
        return [f"📂 Projet « {top['title']} » `{top['id']}` — {gist(top, 400)}"], top["id"]
    if not f or f["key"] in st.get("fiches", []):
        return [], None
    out, used = [], 0
    for line in f["node"]["body"].splitlines():
        if used + len(line) + 1 > FICHE_CHARS:
            break
        out.append(line)
        used += len(line) + 1
    if len(out) < 2:
        return [], None
    st["fiches"] = st.get("fiches", []) + [f["key"]]
    return out, None


def recall_context(data, cfg, raw, saved="") -> str:
    """Rappel automatique du message : souvenirs et fichiers liés (texte pour Claude), ou ''. `saved` : la ligne de
    l'enregistrement automatique d'une demande « retiens… » (sinon Claude est prié de la mémoriser)."""
    rc = cfg["recall"]
    pcline = pc_watch(cfg)
    query = recall_query(raw)
    sid = data.get("session_id")
    st = load_state(sid)
    brain = Brain.load()
    cwd = data.get("cwd") or st.get("cwd")
    proj = brain.project_for_path(cwd) if cwd else None
    injected = set(st.get("injected", []))
    lines = []
    if saved:
        lines.append(saved)
    elif REMEMBER_RX.search(raw):
        lines.append(f"🧠 L'utilisateur demande de mémoriser : enregistre-le avec `{CMD} add -t <type> -T … -b …` "
                     "(vérifie d'abord les doublons avec `q`).")
    elif RECALL_RX.search(raw):
        lines.append(f"🧠 L'utilisateur fait appel à un souvenir : cherche avec `{CMD} q \"…\"` et `{CMD} journal`.")
    picks, logged, learn = [], [], False
    recalled = st.get("recalled", 0)
    if tokenize(query):
        prev = st.get("prev_q") or []
        if recalled < rc["session_cap_items"] or rc.get("neurone", "auto") != "off":
            picks = pick_memories(brain, query, rc, proj["id"] if proj else None, injected, prev=prev, raw=raw,
                                  log_to=logged)
            if recalled >= rc["session_cap_items"]:
                picks = []  # plafond de la session atteint : rien de plus à l'écran, mais l'apprentissage continue
        # Messages tapés seulement (pas les avis automatiques) : contexte de la session et exemples pour le neurone
        if not journal.AUTO_RE.match(journal.clean_prompt(raw)):
            if rc.get("neurone", "auto") != "off":
                st["prev_q"] = (prev + [context_query(raw, query)])[-2:]
            if logged:
                st["cands"] = (st.get("cands") or [])[-2:] + [{"t": now_iso(), "c": logged}]
            learn = True
    named = None
    if tokenize(query) and not saved:
        try:
            ov, named = overview_lines(brain, query, proj, st)
            lines += ov
            if named:  # « où en est le projet aide » : pas la décision globale qui cite « aide » en passant
                picks = [(n, l) for n, l in picks if n.get("project") == named or search._covers(n, [named])]
        except Exception as exc:
            log(f"fiche (rappel) : {exc!r}")
    files = []
    if rc["files"] and proj and named in (None, proj["id"]) and tokenize(query)             and len(st.get("files", [])) < rc["session_cap_files"]:  # autre projet nommé : pas les fichiers d'ici
        from . import filesearch
        files = filesearch.recall_files(proj["id"], query, rc, exclude=set(st.get("files", [])))
    # Lignes entières seulement, dans le budget (jamais une ligne coupée qu'on paierait sans pouvoir s'en servir) ;
    # seuls les éléments vraiment affichés sont marqués « déjà injectés ».
    budget = rc["max_chars"]
    out = list(lines)
    used = sum(len(x) + 1 for x in out)
    shown_mem, shown_files = [], []
    groups = [(MEM_HEADER, picks, shown_mem)]
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
    # prompts.chat : modèles de prompts/skills proches, seulement sur une demande de prompt ou de contenu à créer et
    # seulement s'ils collent vraiment (budget à part : 0 à 2 lignes courtes).
    plcfg, shown_pl = cfg.get("promptlib") or {}, []
    if plcfg.get("auto") and len(st.get("prompts", [])) < plcfg.get("session_cap", 6):
        from . import promptlib
        shown_pl = promptlib.suggest(raw, plcfg, exclude=set(st.get("prompts", [])))
        if shown_pl:
            out += [promptlib.HEADER] + [promptlib.line(p) for p in shown_pl]
    # Réflexes de skills : la skill perso qui colle au message (une fois par session), et une méthode collée à
    # transformer en skill. Passent avant les souvenirs : charger la bonne méthode d'abord.
    sk_lines, sk_names = skill_reflex(raw, st, cfg, cwd)
    if sk_lines:
        out = sk_lines + out
    if pcline:  # la veille PC passe toujours, avant les souvenirs
        out = [pcline] + out
    if not out:
        if learn:  # rien à montrer, mais le contexte de la session et les candidats sont gardés
            st["cwd"] = cwd
            save_state(sid, st)
        return ""
    ctx = "\n".join(out)
    if sk_names:
        st["skills_hinted"] = sorted(set(st.get("skills_hinted", [])) | set(sk_names))
    if shown_pl:
        st["prompts"] = st.get("prompts", []) + [p["id"] for p in shown_pl]
    st["recalled"] = recalled + len(shown_mem)
    st["injected"] = sorted(injected | {n["id"] for n in shown_mem})
    st["files"] = sorted(set(st.get("files", [])) | {f["path"] for f in shown_files})
    st["cwd"] = cwd
    save_state(sid, st)
    bump_hits([n["id"] for n in shown_mem])
    if sk_names:
        from . import skills
        skills.bump(sk_names, "hinted")
    return ctx


def skill_reflex(raw, st, cfg, cwd=None) -> tuple:
    """→ (lignes, skills soufflées). Rien sur un brief de sous-agent ni sur une skill déjà soufflée ou chargée."""
    kc = cfg.get("skills") or {}
    if not kc.get("enabled", True) or raw.startswith("Background (from"):
        return [], []
    try:
        from . import skills
        catalog = skills.index(cwd)
        if not catalog:
            return [], []
        lines, names = [], []
        if st.get("pastes", 0) < 3:
            pl = skills.paste_line(raw, kc, catalog)
            if pl:
                lines.append(pl)
                st["pastes"] = st.get("pastes", 0) + 1
        hinted = set(st.get("skills_hinted", []))
        if len(hinted) < kc.get("session_cap", 6):
            done = hinted | set((st.get("tx") or {}).get("skills", [])) | set(kc.get("exclude", ["brain"]))
            text = journal.clean_prompt(raw, 2000)
            for r in skills.match(text, catalog, exclude=done, min_score=kc.get("min_score", 4.0))[:kc.get("max_items", 1)]:
                lines.append(skills.hint_line(r))
                names.append(r["name"])
        return lines, names
    except Exception as exc:
        log(f"skills : {exc!r}")
        return [], []


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
        bump_used(used)
    return used


def after_turn(st, scan, sid):
    """Après une réponse : souvenirs montrés puis utilisés, et exemples étiquetés pour le neurone du rappel."""
    if not scan:
        st.pop("cands", None)  # rien d'écrit ni de fait : pas d'étiquette possible
        return
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
            neurone.learn_turn(st, scan, sid, brain)
        except Exception as exc:
            log(f"neurone : {exc!r}")
            st.pop("cands", None)


# ------------------------------------------------------------------------------------------ Stop
def on_stop(data, cfg):
    sid, tp = data.get("session_id"), data.get("transcript_path")
    if not sid or not tp:
        return
    st = load_state(sid)
    tx = journal.parse_transcript(tp, st.get("tx"))
    scan = tx.pop("_scan", None)
    st["tx"] = tx
    after_turn(st, scan, sid)
    if tx.get("skills"):
        try:
            from . import skills
            skills.record_usage(st, tx)
        except Exception as exc:
            log(f"skills (usage) : {exc!r}")
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
    try:  # cerveau commun : récupéré pendant que l'utilisateur lit la réponse → son prochain message voit les nouveautés
        from . import commun
        commun.maybe_pull()
    except Exception as exc:
        log(f"commun (fin de tour) : {exc!r}")
    if after_compact:
        sys.stdout.write(json.dumps({"decision": "block", "reason": OBS_REASON}, ensure_ascii=False))
    elif block:
        reason = STOP_REASON
        base = tx.get("last_save_tools", 0)
        done = st.get("auto_saved", [])  # demandes « retiens… » déjà enregistrées par le hook
        cands = [p["t"] for p in tx.get("recent", []) if p.get("i", 0) >= base and durable_cue(p["t"])
                 and p["t"] not in done][-3:]
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
    after_turn(st, scan, sid)
    if tx.get("skills"):
        try:
            from . import skills
            skills.record_usage(st, tx)
        except Exception as exc:
            log(f"skills (usage) : {exc!r}")
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
        for args in daily_due(cfg):
            spawn_background(args)
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
        try:  # cerveau commun : ma part publique (et le journal des projets communs) part en fin de session
            from . import commun
            if commun.member():
                commun.spawn(["commun", "sync", "--auto"])
        except Exception as exc:
            log(f"commun fin de session : {exc!r}")
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
            if event != "session-start" or not plugin.migration_wanted():
                return 0  # cerveau classique aux commandes (gardé exprès, ou bascule au prochain démarrage)
            try:  # premier démarrage du plugin chez un cerveau classique : il prend le relais, souvenirs intacts
                plugin.migrate_classic()
            except Exception as exc:
                log(f"passage au plugin impossible, le cerveau classique reste aux commandes : {exc!r}")
                return 0
            if plugin.classic_install():
                return 0
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
