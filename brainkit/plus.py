"""Couche « plus » : ce que le cerveau ajoute à la sortie de ses hooks, quel que soit le moteur qui les exécute.

Les hooks du cerveau tournent en Python (macOS, Linux) ou dans brain.exe (Windows, version Rust, qui repasse à Python
pour ce qu'elle ne fait pas). Tout ce qui est né après ce portage vit ici, en Python seul, et s'ajoute à la sortie du
hook principal sans rien y changer : la même chose partout, sans attendre un nouveau brain.exe.
- Python aux commandes : `hooks.run` capture la sortie du hook, puis `apply` la complète.
- brain.exe aux commandes : brain.py capture sa sortie (BRAIN_PLUS=0 dans son environnement : un retour à Python ne
  l'applique pas une deuxième fois), puis `apply` la complète.

Ce qui s'ajoute : la délégation (consigne au démarrage, réflexe ↪ par message), l'apprentissage (erreurs résolues
jointes au rappel de fin de tâche, dossier d'apprentissage annoncé au démarrage) et l'échange de skills avec les amis
(skills reçues soufflées quand un message colle, annonces). Règle d'or des hooks : ne jamais casser ni ralentir une
session — tout est protégé, et une sortie qu'on ne sait pas lire repart telle quelle.

État propre à cette couche : state/plus/<session>.json (jamais l'état du hook principal, qu'un autre processus écrit
peut-être au même moment)."""
from __future__ import annotations

import json
import time

from .common import PLUGIN, STATE_DIR, load_config, log, read_json, write_json

EVENTS = ("session-start", "prompt", "stop", "session-end")
HOOK_NAMES = {"session-start": "SessionStart", "prompt": "UserPromptSubmit"}
PLUS_DIR = STATE_DIR / "plus"
MAX_CONTEXT = 9800  # le contexte ajouté par un hook est plafonné à 10 000 caractères : au-delà, Claude n'en voit qu'un aperçu
AUTO_PREFIX = ("Background (from", "<task-notification>", "[SYSTEM NOTIFICATION")
STOP_MARK = "🧠 Cerveau — avant de conclure"  # début du rappel de fin de tâche (hooks.STOP_REASON)
MIN_ROOM = 120  # sous cette place, rien ne tient : inutile de chercher


# ------------------------------------------------------------------------------------------ état de session
def _file(sid):
    safe = "".join(c for c in str(sid) if c.isalnum() or c in "-_")[:80] or "anon"
    return PLUS_DIR / f"{safe}.json"


def load_state(sid) -> dict:
    return (read_json(_file(sid), {}) or {}) if sid else {}


def save_state(sid, st) -> None:
    if sid:
        write_json(_file(sid), st, indent=None)


def cleanup(max_days=5) -> None:
    try:
        now = time.time()
        for f in PLUS_DIR.glob("*.json"):
            if now - f.stat().st_mtime > max_days * 86400:
                f.unlink()
    except OSError:
        pass


def _member(cfg) -> bool:
    """Membre du cerveau commun, d'après la configuration seule (sans charger commun.py, git, hashlib…)."""
    c = cfg.get("commun") if isinstance(cfg, dict) else None
    return isinstance(c, dict) and c.get("etat") == "membre" and bool(c.get("nom"))


def _taker(room, sep=2):
    """→ fonction `take(ligne)` : True si la ligne tient dans la place qui reste sous le plafond de contexte du hook, et
    sa place est alors réservée. Chaque producteur ne note « montré » (annonce faite, conseil donné, skill soufflée)
    que ce que `take` a accepté : rien n'est consommé puis perdu, ce qui ne tient pas attend la prochaine occasion."""
    left = [room]

    def take(line):
        need = len(line or "") + sep
        if not line or need > left[0]:
            return False
        left[0] -= need
        return True
    return take


def _guard(label, fn, default):
    """Chaque ajout est indépendant : une erreur dans l'un ne prive pas des autres."""
    try:
        return fn()
    except Exception as exc:
        log(f"plus ({label}) : {exc!r}")
        return default


# ------------------------------------------------------------------------------------------ par événement
def session_start(data, cfg, take=None) -> str:
    """Lignes ajoutées à l'injection de démarrage. Reprise d'une session : l'injection de départ est encore dans
    l'historique, seules les annonces nouvelles passent. `take` : voir _taker — la consigne de délégation d'abord,
    puis les annonces faites une seule fois, chacune seulement si elle tient."""
    take = take or (lambda line: True)
    sid, source = data.get("session_id"), data.get("source") or "startup"
    cleanup()
    st = load_state(sid)
    lines = []
    if not PLUGIN:  # cerveau classique : agents de délégation posés ou mis à jour dans ~/.claude/agents
        from . import install
        _guard("agents", install.sync_agents, None)
    if source != "resume" or not st.get("started"):
        from . import delegation
        line = _guard("délégation", lambda: delegation.instruction(cfg), "")
        if line and take(line):
            lines.append(line)
    if source in ("compact", "clear"):  # les conseils déjà donnés ont quitté le contexte : à resservir
        st["deleg"], st["recues"] = [], []
    from . import apprendre
    line = _guard("apprentissage", lambda: apprendre.notice(cfg, take), "")
    if line:
        lines.append(line)
    if _member(cfg):
        from . import echange
        line = _guard("échange", lambda: echange.notice(cfg, take), "")
        if line:
            lines.append(line)
    st["started"] = st.get("started") or time.strftime("%Y-%m-%dT%H:%M:%S")
    save_state(sid, st)
    return "\n\n".join(lines)


def prompt(data, cfg, take=None) -> str:
    """Lignes ajoutées au rappel d'un message tapé par l'utilisateur (rien sur une commande « / », un brief de
    sous-agent ou un message de l'appli). `take` : voir _taker."""
    raw = (data.get("prompt") or "").strip()
    if len(raw) < 6 or raw.startswith("/") or raw.startswith(AUTO_PREFIX) or data.get("agent_id"):
        return ""
    from . import journal
    if journal.is_auto(raw):
        return ""
    take = take or (lambda line: True)
    sid = data.get("session_id")
    st = load_state(sid)
    before = json.dumps(st, sort_keys=True)
    text = journal.clean_prompt(raw, 2000, pasted=False)
    lines = []
    if st.get("started"):  # session ouverte avant la mise à jour qui apporte les agents : elle ne les connaît pas encore
        from . import delegation
        lines += _guard("délégation", lambda: delegation.reflex(text, st, cfg, take), [])
    if _member(cfg):  # l'échange (et git, hashlib…) n'est chargé que pour un membre du cerveau commun
        from . import echange
        lines += _guard("échange", lambda: echange.reflex(text, st, cfg, take), [])
    if (read_json(STATE_DIR / "apprendre.json", {}) or {}).get("annonces"):  # rare : module chargé seulement alors
        from . import apprendre
        lines += _guard("apprentissage", lambda: apprendre.take_annonces(take), [])
    if json.dumps(st, sort_keys=True) != before:
        save_state(sid, st)
    return "\n".join(lines)


def stop(data, cfg, blocking=False) -> str:
    """Fin de tour : ce que la session vient d'apprendre (lecture incrémentale du transcript). `blocking` : le rappel de
    fin de tâche a lieu → phrase à lui joindre (erreurs résolues à mémoriser) ; sinon elles attendent le prochain rappel,
    ou le dossier d'apprentissage en fin de session."""
    from . import apprendre
    return _guard("apprentissage", lambda: apprendre.on_stop(data, cfg, blocking), "")


def session_end(data, cfg) -> None:
    from . import apprendre
    _guard("apprentissage", lambda: apprendre.on_session_end(data, cfg), None)
    if _member(cfg):
        from . import echange
        _guard("échange", lambda: echange.on_session_end(cfg), None)


# ------------------------------------------------------------------------------------------ fusion des sorties
def _split(out_text):
    """Sortie d'un hook → (objet JSON ou None, reste). Vide : ({}, '')."""
    text = out_text or ""
    if not text.strip():
        return {}, ""
    lead = len(text) - len(text.lstrip())
    try:
        obj, end = json.JSONDecoder().raw_decode(text, lead)
    except ValueError:
        return None, text
    return (obj, text[end:]) if isinstance(obj, dict) else (None, text)


def _add_context(obj, event, extra) -> bool:
    name = HOOK_NAMES[event]
    hso = obj.get("hookSpecificOutput")
    if hso is None:
        hso = obj["hookSpecificOutput"] = {"hookEventName": name}
    if not isinstance(hso, dict) or hso.get("hookEventName", name) != name:
        return False
    cur = hso.get("additionalContext") or ""
    if not isinstance(cur, str) or len(cur) + len(extra) + 2 > MAX_CONTEXT:  # (ne devrait plus arriver : voir _taker)
        log(f"couche plus, {event} : ajout laissé de côté ({len(extra)} car. : le contexte du hook atteindrait le plafond)")
        return False
    hso.setdefault("hookEventName", name)
    hso["additionalContext"] = f"{cur}\n\n{extra}" if cur else extra
    return True


def apply(event, out_text, data, cfg=None) -> str:
    """Sortie finale du hook `event` : celle du hook principal, complétée. Jamais d'exception : au pire, la sortie
    d'origine."""
    try:
        if event not in EVENTS or not isinstance(data, dict):
            return out_text
        if PLUGIN:
            from . import plugin
            if plugin.classic_install():
                return out_text  # cerveau classique aux commandes : le plugin ne fait rien
        cfg = cfg or load_config()
        obj, rest = _split(out_text)
        if event == "session-end":
            session_end(data, cfg)
            return out_text
        if event == "stop":  # seulement le rappel de fin de tâche, pas celui d'après compaction (observations seules)
            blocking = (isinstance(obj, dict) and obj.get("decision") == "block" and isinstance(obj.get("reason"), str)
                        and STOP_MARK in obj["reason"])
            extra = stop(data, cfg, blocking)
            if extra and blocking:
                obj["reason"] = f"{obj['reason']} {extra}"
                return json.dumps(obj, ensure_ascii=False) + rest
            return out_text
        if obj is None:
            return out_text
        hso = obj.get("hookSpecificOutput")
        cur = hso.get("additionalContext") if isinstance(hso, dict) else ""
        room = MAX_CONTEXT - len(cur) if isinstance(cur, str) else MAX_CONTEXT if cur is None else 0
        if event == "prompt" and room < MIN_ROOM:
            return out_text  # rappel déjà plein (skill chargée d'office…) : rien ne tiendrait
        take = _taker(room)
        extra = session_start(data, cfg, take) if event == "session-start" else prompt(data, cfg, take)
        if not extra:
            return out_text
        return json.dumps(obj, ensure_ascii=False) + rest if _add_context(obj, event, extra) else out_text
    except Exception as exc:
        log(f"plus ({event}) ERREUR {exc!r}")
        return out_text


def apply_raw(event, out_bytes, payload) -> str:
    """Variante pour brain.py (brain.exe aux commandes) : sortie et charge utile en octets."""
    text = out_bytes.decode("utf-8", "replace")
    try:
        data = json.loads(payload.decode("utf-8", "replace") or "{}")
    except ValueError:
        return text
    return apply(event, text, data if isinstance(data, dict) else {})
