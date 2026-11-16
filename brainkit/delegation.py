"""Délégation — chaque tâche au modèle le moins cher qui suffit, dans un contexte à part.

Pourquoi : chaque appel d'outil du modèle principal relit toute la conversation, et ce qu'il lit y reste jusqu'à la
compaction. Une recherche ou une lecture confiée à un sous-agent ne laisse dans la conversation que son rapport ; sur un
modèle moins cher (Haiku pour chercher, lire, résumer ; Sonnet pour une modification cadrée), elle coûte aussi bien
moins par token (tarifs : `tokens.PRICES`).

Trois leviers, réglés par `delegation.mode` (« auto » par défaut, « max », « conseil », « off ») :
- les agents livrés avec le plugin (`agents/` : `cerveau:eclaireur`, `cerveau:ouvrier`, `cerveau:archiviste`), au modèle
  fixé dans leur en-tête ;
- la consigne de démarrage et un réflexe par message (ligne ↪, une fois par session et par genre de tâche) ;
- l'aiguillage (« auto » et « max ») : hook PreToolUse sur l'outil Agent. Un sous-agent lancé SANS modèle précisé reçoit
  Haiku si sa consigne est une recherche ou une lecture, Sonnet si elle demande de comprendre ce qui est lu ou si c'est
  une modification mécanique ; conception, débogage, revue, décision : jamais touché (« max » : tout sous-agent
  générique part au moins sur Sonnet). Jamais non plus quand l'appelant a choisi un modèle, quand l'agent vient d'un
  autre plugin, quand l'utilisateur a réglé CLAUDE_CODE_SUBAGENT_MODEL, quand le modèle principal n'est pas plus cher
  que la cible, ni en mode de permission « auto » (l'appel relu par le classifieur ne doit pas changer après coup :
  Claude Code pourrait le refuser).
Vérifié en session réelle (Claude Code 2.1.325, 16/11/2026) : `updatedInput` sans `permissionDecision` change bien le
modèle du sous-agent ; aucune permission n'est accordée par ce hook.

Python seul, sur toutes les plateformes : brain.py ne passe pas ces points d'entrée à brain.exe."""
from __future__ import annotations

import json
import os
import re
import sys
import time

from .common import CLAUDE_HOME, CMD, CODE_DIR, PLUGIN, STATE_DIR, FileLock, fold, load_config, log, read_json, \
    read_stdin_json, write_json

AGENTS = {"eclaireur": "haiku", "ouvrier": "sonnet", "archiviste": "sonnet"}  # agents livrés : modèle de leur en-tête
ROLES = {"eclaireur": "chercher, lire, résumer", "ouvrier": "modification déjà décidée", "archiviste": "entretien du cerveau"}
MODES = ("auto", "max", "conseil", "off")
ALIASES = ("haiku", "sonnet", "opus", "fable")
RANK = {"haiku": 0, "sonnet": 1, "opus": 2, "fable": 3, "mythos": 3}  # du moins cher au plus cher
WHY = {"lecture": "recherche ou lecture", "jugement": "lecture à comprendre", "mecanique": "modification mécanique"}
GENERIC = ("general-purpose", "claude", "")  # sous-agents à tout faire de Claude Code
SEARCH = ("Explore",)  # sous-agent de recherche en lecture seule de Claude Code
STATS_FILE = STATE_DIR / "delegation.json"
KEEP_DAYS = 45
TAIL = 256 * 1024  # fin du transcript lue pour connaître le modèle principal

# Sur le texte replié (minuscules, sans accents). Dans le doute, on ne touche à rien : une tâche prise pour difficile
# reste simplement sur le modèle prévu.
# Motifs compilés à la demande : chaque hook est un processus neuf, il ne compile que ceux dont il se sert.
_SRC, _COMPILED = {}, {}


def _rx(name):
    rx = _COMPILED.get(name)
    if rx is None:
        rx = _COMPILED[name] = re.compile(_SRC[name])
    return rx


_SRC["hard"] = (
    r"\b(?:bugs?|bogues?|debog\w*|debug\w*|plant(?:e|age)\w*|crash\w*|root cause|cause racine|pourquoi|why|diagnos\w*|"
    r"investig\w*|enquet\w*|concevoi\w*|concois|concoit|conception|design\w*|architect\w*|planifi\w*|plan d\w*|strateg\w*|"
    r"decid\w*|decision\w*|choisi\w*|tranch\w*|arbitr\w*|recommand\w*|recommend\w*|evalu\w*|assess\w*|revue|review\w*|"
    r"relecture|relis|audit\w*|securite|security|vulnerab\w*|faille\w*|refactor\w*|refonte|refond\w*|optimis\w*|"
    r"optimiz\w*|prouv\w*|prove|proof|demontr\w*|trade-?offs?|compromis|risqu\w*|corrig\w*|fix(?:e[sd]?|ing)?|repar\w*|"
    r"resou\w*|resolv\w*|solve[sd]?)\b")
_SRC["mech"] = (
    r"\b(?:renomm\w*|renam\w*|remplac\w* (?:toutes|tous|chaque|partout)|replac\w* (?:all|every)|reformat\w*|"
    r"mise? en forme|tradui\w*|translat\w*|(?:ecri\w*|ajout\w*|writ\w*|add\w*) (?:les |des |the |unit |some )?tests?|"
    r"tests? unitaires?|unit tests?|mets? a jour les imports|update (?:the )?imports|converti\w*|convert\w*|"
    r"docstrings?)\b")
_SRC["write"] = (
    r"\b(?:modifi\w*|ecri\w*|redig\w*|cree\w*|creer|ajout\w*|supprim\w*|efface\w*|remplac\w*|install\w*|deploi\w*|"
    r"publi\w*|envoi\w*|envoy\w*|commit\w*|push\w*|edit\w*|writ\w*|creat\w*|add(?:s|ed|ing)?|delet\w*|remov\w*|replac\w*|"
    r"updat\w*|chang\w*|implement(?:e[rsz]?|ing|ons)?|develop\w*|build\w*|construi\w*|genere\w*|generat\w*|migr\w*|"
    r"deploy\w*|send\w*|post\w*)\b")
_SRC["read"] = (
    r"\b(?:cherch\w*|trouv\w*|localis\w*|reper\w*|list\w*|enumer\w*|recens\w*|inventori\w*|lis|lire|lit|lisez|resum\w*|"
    r"extrai\w*|extract\w*|collect\w*|rassembl\w*|relev\w*|compt\w*|count\w*|ou (?:est|sont|se trouv\w*)|"
    r"quels? fichiers?|search\w*|find\w*|locat\w*|read\w*|summari[sz]\w*|gather\w*|grep\w*|scan\w*|"
    r"look(?:ing)? (?:for|up)|where (?:is|are|does)|which files?)\b")
_SRC["judge"] = (
    r"\b(?:compren\w*|expliqu\w*|explain\w*|understand\w*|comment (?:fonctionn\w*|march\w*|est|sont|se|ca)\b|"
    r"how (?:does|do|is|are|was|were|it|the|this)\b|"
    r"analys\w*|analyz\w*|compar\w*|verifi\w*|verify\w*|check\w*|control\w*|synthes\w*|synthesi[sz]\w*|interpret\w*)\b")


# ------------------------------------------------------------------------------------------ réglages
def settings(cfg=None) -> dict:
    d = (cfg or load_config()).get("delegation")
    return d if isinstance(d, dict) else {}


def mode(cfg=None) -> str:
    m = str(settings(cfg).get("mode") or "auto").lower()
    return m if m in MODES else "auto"


def agents_dir():
    """Dossier des agents livrés : celui du plugin, ou ~/.claude/agents en installation classique."""
    return CODE_DIR / "agents" if PLUGIN else CLAUDE_HOME / "agents"


def call_name(name) -> str:
    """Nom d'appel d'un agent livré, comme l'attend l'outil Agent : « cerveau:eclaireur » en plugin."""
    return f"cerveau:{name}" if PLUGIN else name


def available() -> list:
    """Agents du cerveau que Claude Code connaît ici (aucun dans une session cloud lancée par le wiki : le code y est
    récupéré sans que le plugin soit installé)."""
    if os.environ.get("CERVEAU_CLOUD"):
        return []
    d = agents_dir()
    return [n for n in AGENTS if (d / f"{n}.md").is_file()]


def model_of(name, cfg=None) -> str:
    """Modèle d'un agent livré : celui choisi par l'utilisateur (`delegation.modeles`), sinon celui de son en-tête."""
    m = str((settings(cfg).get("modeles") or {}).get(name) or "").lower()
    return m if m in ALIASES else AGENTS.get(name, "")


# ------------------------------------------------------------------------------------------ classement d'une consigne
def classify(text, readonly=False) -> str | None:
    """« dur » (conception, débogage, revue, décision…), « mecanique » (modification mécanique et cadrée), « lecture »
    (chercher, lire, lister, résumer : rien à écrire ni à juger), « jugement » (lecture qui demande de comprendre ou de
    comparer), ou None : écriture non mécanique, ou trop flou pour le dire. `readonly` : la consigne va à un sous-agent
    qui ne peut pas écrire (Explore) — un verbe d'écriture n'y décrit que ce qu'il doit chercher."""
    t = fold(text)[:6000]
    if _rx("hard").search(t):
        return "dur"
    if not readonly:
        if _rx("mech").search(t):
            return "mecanique"
        if _rx("write").search(t):
            return None
    if _rx("judge").search(t):
        return "jugement" if readonly or _rx("read").search(t) else None
    return "lecture" if _rx("read").search(t) else None


def target(subagent_type, kind, how="auto") -> str | None:
    """Modèle moins cher pour ce sous-agent, ou None (on n'y touche pas). `how` : « auto » (prudent) ou « max »."""
    st = str(subagent_type or "")
    if st in SEARCH:  # lecture seule par construction
        table = {"lecture": "haiku", "jugement": "sonnet"}
        return table.get(kind) or ("sonnet" if how == "max" else None)
    if st in GENERIC:
        table = {"lecture": "haiku", "jugement": "sonnet", "mecanique": "sonnet"}
        return table.get(kind) or ("sonnet" if how == "max" else None)
    return None


def family(model) -> str:
    """« claude-opus-5-5 », « opus[1m] »… → « opus » ; '' si inconnu."""
    m = str(model or "").lower()
    return next((k for k in RANK if k in m), "")


def main_model(transcript_path) -> str:
    """Famille du modèle de la conversation principale, lue dans la fin du transcript ('' si introuvable)."""
    try:
        with open(transcript_path, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            fh.seek(max(0, size - TAIL))
            lines = fh.read().split(b"\n")
    except (OSError, TypeError, ValueError):
        return ""
    for raw in reversed(lines):
        if b'"assistant"' not in raw or b'"model"' not in raw:
            continue
        try:
            o = json.loads(raw)
        except ValueError:
            continue
        if isinstance(o, dict) and o.get("type") == "assistant" and not o.get("isSidechain"):
            fam = family((o.get("message") or {}).get("model"))
            if fam:
                return fam
    return ""


def route(data, cfg=None) -> tuple:
    """Hook PreToolUse (Agent) → (modèle à poser ou None, raison). Voir l'en-tête du module pour les garde-fous."""
    cfg = cfg or load_config()
    how = mode(cfg)
    inp = data.get("tool_input")
    if data.get("tool_name") != "Agent" or not isinstance(inp, dict):
        return None, "pas un lancement de sous-agent"
    if how not in ("auto", "max"):
        return None, f"mode {how}"
    if inp.get("model"):
        return None, "modèle choisi par l'appelant"
    if data.get("agent_id"):
        return None, "lancé depuis un sous-agent"
    if data.get("permission_mode") == "auto":
        return None, "mode de permission auto"
    if os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL"):
        return None, "CLAUDE_CODE_SUBAGENT_MODEL réglé par l'utilisateur"
    st = str(inp.get("subagent_type") or "")
    chosen = settings(cfg).get("modeles") or {}
    short = st.rpartition(":")[2] if st.startswith("cerveau:") or not PLUGIN else ""
    if short in AGENTS and st == call_name(short):  # agent du cerveau : seulement le choix de l'utilisateur
        want = str(chosen.get(short) or "").lower()
        return (want, "choix de l'utilisateur") if want in ALIASES and want != AGENTS[short] else (None, "en-tête de l'agent")
    pick = str(chosen.get(st or "general-purpose") or "").lower()
    if pick == "off":
        return None, "aiguillage coupé pour ce type"
    if pick in ALIASES:
        want, why = pick, "choix de l'utilisateur"
    else:
        kind = classify(f"{inp.get('description') or ''}\n{inp.get('prompt') or ''}", readonly=st in SEARCH)
        want, why = target(st, kind, how), kind or "consigne non classée"
    if not want:
        return None, why
    main = main_model(data.get("transcript_path"))
    if main and RANK[want] >= RANK.get(main, 9):
        return None, f"modèle principal ({main}) pas plus cher"
    return want, why


# ------------------------------------------------------------------------------------------ suivi
def _bump(fields) -> None:
    """Compteurs du jour (state/delegation.json), sous verrou court : plusieurs sous-agents partent souvent ensemble."""
    day = time.strftime("%Y-%m-%d")
    try:
        with FileLock(str(STATS_FILE) + ".lock", timeout=1.0, stale=10.0, strict=False):
            st = read_json(STATS_FILE, {}) or {}
            days = st.setdefault("jours", {})
            cur = days.setdefault(day, {})
            for k, v in fields.items():
                if isinstance(v, dict):
                    sub = cur.setdefault(k, {})
                    for kk, vv in v.items():
                        sub[kk] = sub.get(kk, 0) + vv
                else:
                    cur[k] = cur.get(k, 0) + v
            for old in sorted(days)[:-KEEP_DAYS]:
                days.pop(old, None)
            write_json(STATS_FILE, st, indent=None)
    except Exception as exc:
        log(f"délégation (compteurs) : {exc!r}")


def counters(days=7) -> dict:
    """Somme des compteurs des `days` derniers jours → {vus, haiku, sonnet, types {type: n}}."""
    st = read_json(STATS_FILE, {}) or {}
    out = {"vus": 0, "haiku": 0, "sonnet": 0, "types": {}}
    cut = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    for day, cur in (st.get("jours") or {}).items():
        if day < cut or not isinstance(cur, dict):
            continue
        for k in ("vus", "haiku", "sonnet"):
            out[k] += int(cur.get(k) or 0)
        for t, n in (cur.get("types") or {}).items():
            out["types"][t] = out["types"].get(t, 0) + int(n or 0)
    return out


# ------------------------------------------------------------------------------------------ hook PreToolUse (Agent)
def on_pre_agent(data, cfg=None) -> dict | None:
    """→ sortie du hook (`updatedInput` avec le modèle moins cher, sans décision de permission), ou None."""
    inp = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    if data.get("tool_name") != "Agent":
        return None
    want, why = route(data, cfg)
    st = str(inp.get("subagent_type") or "general-purpose")
    fields = {"vus": 1, "types": {st[:60]: 1}}
    if want:
        fields[want] = 1
    _bump(fields)
    if not want:
        return None
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": {**inp, "model": want}}}
    sid = data.get("session_id")
    if sid:  # dit une fois par session à l'utilisateur (zéro token pour Claude)
        try:
            from . import plus
            state = plus.load_state(sid)
            if not state.get("deleg_dit"):
                state["deleg_dit"] = True
                plus.save_state(sid, state)
                out["systemMessage"] = (f"↪ Cerveau : sous-agent « {st} » lancé sur {want.capitalize()} ({WHY.get(why, why)}) — "
                                        f"délégation automatique, réglable : `{CMD} delegation`")
        except Exception as exc:
            log(f"délégation (annonce) : {exc!r}")
    return out


def hook() -> int:
    """Point d'entrée rapide (`brain.py hook pre-agent`) : n'importe que ce module et le socle."""
    try:
        data = read_stdin_json()
        if PLUGIN:
            from . import plugin
            if plugin.classic_install():
                return 0  # cerveau classique aux commandes : le plugin ne fait rien (jamais deux cerveaux à la fois)
        out = on_pre_agent(data)
        if out:
            sys.stdout.write(json.dumps(out, ensure_ascii=False))
            sys.stdout.flush()
    except Exception as exc:  # un hook ne casse jamais une session
        log(f"hook pre-agent ERREUR {exc!r}")
    return 0


# ------------------------------------------------------------------------------------------ consigne et réflexe
def instruction(cfg=None) -> str:
    """La ligne de délégation injectée au démarrage (rien si « off » ou si aucun agent du cerveau n'est connu ici)."""
    cfg = cfg or load_config()
    names = available()
    if mode(cfg) == "off" or not names:
        return ""
    parts = [f"`{call_name(n)}` ({model_of(n, cfg).capitalize()}) : {ROLES[n]}" for n in names]
    return ("↪ Délégation : passé 5 appels d'outils, confie la tâche au sous-agent le moins cher qui suffit (seul son "
            "rapport revient) — " + " ; ".join(parts) + ". Conception, débogage, décisions : toi.")


# Message de l'utilisateur qui annonce une lecture ou une recherche en masse, ou une modification mécanique.
_SRC["bulk"] = (
    r"\b(?:dans|sur|a travers|parmi) (?:tout|toute|tous|toutes|l'ensemble d[eu]s?) ?(?:le |la |les |mon |ma |mes |ce |ces )?"
    r"(?:projet|code|depot|repo|dossiers?|fichiers?|site|pages?|docs?|documentation|sources?)\b|"
    r"\b(?:tous|toutes) les (?:fichiers|pages|occurrences|endroits|appels|usages|utilisations|references)\b|"
    r"\b(?:cherche|recherche|regarde|fouille) partout\b|\bfai[st] (?:le tour|l'inventaire)\b|\bparcours (?:tout|tous|toutes|le |la |les )|"
    r"\b(?:liste|recense|inventorie)(?:[- ]moi)? (?:tous|toutes) les\b|"
    r"\bresume(?:[- ]moi)? (?:ce|cet|cette|ces|le|la|les|tous les|toutes les) (?:gros |long |longue )?"
    r"(?:fichiers?|documents?|pdfs?|pages?|articles?|dossiers?|depots?|repos?|docs?|rapports?|logs?|journaux)\b")
_SRC["url"] = (r"https?://\S+")
_SRC["web"] = (r"\b(?:resum\w*|lis|lire|extrai\w*|compar\w*|recup\w*|que dit|que disent)\b")
_SRC["mech_msg"] = (
    r"\b(?:renomme\w* .{0,60}\bpartout|remplace\w* (?:toutes|tous|chaque|partout)|reformate\w*|"
    r"tradui\w* (?:tous|toutes|les|le site|la doc)|mets? a jour (?:tous )?les imports|"
    r"(?:ecri\w*|ajoute\w*) (?:les |des )?tests? (?:pour|de|du|des)\b)")


def reflex(text, st, cfg=None) -> list:
    """→ lignes ↪ pour ce message (une fois par session et par genre) ; `st` : état « plus » de la session, modifié."""
    cfg = cfg or load_config()
    d = settings(cfg)
    if mode(cfg) == "off" or not d.get("reflexe", True):
        return []
    names, done = available(), list(st.get("deleg") or [])
    if not names or len(done) >= int(d.get("session_cap", 2)):
        return []
    t, out = fold(text)[:3000], []
    urls = _rx("url").findall(text or "")
    if "eclaireur" in names and "lecture" not in done and (_rx("bulk").search(t) or (len(urls) >= 2 and _rx("web").search(t))):
        done.append("lecture")
        out.append(f"↪ Recherche ou lecture en masse : confie-la à l'agent `{call_name('eclaireur')}` "
                   f"({model_of('eclaireur', cfg).capitalize()}, contexte à part : seul son rapport revient), puis décide toi-même.")
    if "ouvrier" in names and "mecanique" not in done and _rx("mech_msg").search(t):
        done.append("mecanique")
        out.append(f"↪ Modification mécanique : fixe d'abord la consigne et le critère de vérification, puis confie "
                   f"l'exécution à l'agent `{call_name('ouvrier')}` ({model_of('ouvrier', cfg).capitalize()}).")
    if out:
        st["deleg"] = done
    return out


# ------------------------------------------------------------------------------------------ mesure et commande
def _usd(x) -> str:
    return f"{x:,.2f} $".replace(",", " ").replace(".", ",")


def measure(days=7) -> dict:
    """Sur les transcripts des `days` derniers jours : requêtes et coût (tarif de l'API) par modèle, conversation et
    sous-agents à part, et ce que les mêmes sous-agents auraient coûté sur le modèle principal de leur session."""
    from . import tokens
    root = CLAUDE_HOME / "projects"
    cut = time.time() - days * 86400
    files = []
    for f in root.rglob("*.jsonl") if root.is_dir() else ():
        try:
            if f.stat().st_mtime >= cut:
                files.append(f)
        except OSError:
            continue
    seen, mains, subs = set(), {}, []
    out = {"main": {}, "sub": {}, "usd_main": 0.0, "usd_sub": 0.0, "usd_sub_si_main": 0.0, "sans_prix": 0, "files": len(files)}
    for f in sorted(files, key=lambda p: "subagents" in p.parts):  # conversations d'abord : le modèle principal de chacune
        sub = "subagents" in f.parts
        sid = f.parent.parent.name if sub else f.stem
        try:
            ev, _ = tokens._events(f, seen, sub)
        except OSError:
            continue
        for e in ev:
            if e[0] != "R" or (e[1]["t"] and e[1]["t"] < cut):
                continue
            r = e[1]
            usd = tokens.price(r)
            if usd is None:
                out["sans_prix"] += 1
                continue
            name = tokens.model_name(r["model"])
            if r["main"]:
                out["main"][name] = out["main"].get(name, 0) + 1
                out["usd_main"] += usd
                m = mains.setdefault(sid, {})
                m[r["model"]] = m.get(r["model"], 0) + 1
            else:
                out["sub"][name] = out["sub"].get(name, 0) + 1
                out["usd_sub"] += usd
                subs.append((sid, r))
    for sid, r in subs:
        m = mains.get(sid)
        ref = max(m, key=m.get) if m else None
        alt = tokens.price({**r, "model": ref}) if ref else None
        out["usd_sub_si_main"] += alt if alt is not None else (tokens.price(r) or 0.0)
    return out


def set_mode(value) -> str:
    from .common import set_config
    v = str(value or "").lower()
    if v not in MODES:
        return f"✗ mode inconnu : {value} (au choix : {', '.join(MODES)})"
    set_config("delegation.mode", v)
    what = {"auto": "aiguillage prudent des sous-agents lancés sans modèle, consigne et conseils",
            "max": "tout sous-agent générique lancé sans modèle part au moins sur Sonnet (plus d'économies, réponses "
                   "parfois moins bonnes sur le difficile)",
            "conseil": "consigne et conseils seulement, aucun modèle changé par le cerveau",
            "off": "ni aiguillage, ni consigne, ni conseil (les agents du plugin restent utilisables)"}[v]
    return f"✓ délégation : {v} — {what} · pris en compte dès le prochain message"


def set_model(spec) -> str:
    """`--modele eclaireur=sonnet` (agent du cerveau), `Explore=off|haiku|sonnet` (type intégré), `nom=defaut`."""
    from .common import update_config
    name, _, value = str(spec or "").partition("=")
    name, value = name.strip(), value.strip().lower()
    known = list(AGENTS) + list(SEARCH) + ["general-purpose"]
    if name not in known:
        return f"✗ inconnu : {name or '?'} (au choix : {', '.join(known)})"
    if value not in ALIASES + ("off", "defaut", "default", ""):
        return f"✗ valeur inconnue : {value} (au choix : {', '.join(ALIASES)}, off, defaut)"
    if value == "off" and name in AGENTS:
        return "✗ « off » ne vaut que pour Explore et general-purpose (un agent du cerveau garde un modèle)"

    def change(cfg):
        m = cfg.setdefault("delegation", {}).setdefault("modeles", {})
        if value in ("defaut", "default", ""):
            m.pop(name, None)
        else:
            m[name] = value
    update_config(change)
    return f"✓ {name} : " + ("modèle par défaut" if value in ("defaut", "default", "") else value)


def report(days=7, cfg=None) -> str:
    """`brain delegation` : mode, agents, ce qui est parti sur quel modèle, ce que ça a épargné, ce qui reste à déléguer."""
    cfg = cfg or load_config()
    how, names = mode(cfg), available()
    label = {"auto": "aiguillage prudent + conseils", "max": "aiguillage maximal + conseils",
             "conseil": "conseils seulement", "off": "coupée"}[how]
    L = [f"↪ Délégation — mode {how} ({label})"]
    L.append("  agents du cerveau : " + (" · ".join(f"`{call_name(n)}` {model_of(n, cfg).capitalize()} ({ROLES[n]})" for n in names)
                                        if names else "aucun connu ici (plugin pas encore rechargé, ou session cloud du wiki)"))
    if os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL"):
        L.append(f"  ⚠ CLAUDE_CODE_SUBAGENT_MODEL={os.environ['CLAUDE_CODE_SUBAGENT_MODEL']} : c'est ce réglage qui décide du "
                 "modèle des sous-agents sans en-tête, l'aiguillage du cerveau n'y touche pas")
    c = counters(days)
    if c["vus"]:
        types = ", ".join(f"{t} {n}" for t, n in sorted(c["types"].items(), key=lambda x: -x[1])[:6])
        L.append(f"Sur {days} j — sous-agents lancés : {c['vus']} ({types}) · envoyés par le cerveau sur Haiku : {c['haiku']}"
                 f", sur Sonnet : {c['sonnet']}")
    else:
        L.append(f"Sur {days} j — aucun lancement de sous-agent vu par le cerveau (le hook compte à partir de la version 8.21)")
    try:
        m = measure(days)
        if m["main"] or m["sub"]:
            mix = lambda d: ", ".join(f"{k} {v}" for k, v in sorted(d.items(), key=lambda x: -x[1])) or "—"  # noqa: E731
            L.append(f"  requêtes — conversation : {mix(m['main'])} · sous-agents : {mix(m['sub'])}")
            L.append(f"  au tarif de l'API — conversation ≈ {_usd(m['usd_main'])} · sous-agents ≈ {_usd(m['usd_sub'])}"
                     + (f" ; les mêmes sous-agents sur le modèle principal de leur session ≈ {_usd(m['usd_sub_si_main'])} "
                        f"(estimation : ≈ {_usd(m['usd_sub_si_main'] - m['usd_sub'])} épargnés)"
                        if m["usd_sub_si_main"] - m["usd_sub"] > 0.005 else ""))
        from . import tokens
        n_solo, ctx_solo, n_reqs = tokens.measure(days * 24).get("solo") or (0, 0, 0)
        if n_reqs and n_solo >= 12 and "eclaireur" in names:
            L.append(f"  à déléguer : {n_solo} lectures enchaînées une par une dans la conversation ({100 * n_solo / n_reqs:.0f} % "
                     f"des requêtes, {tokens._m(ctx_solo)} tok de contexte relus pour elles) → `{call_name('eclaireur')}`")
    except Exception as exc:  # jamais bloquer l'état sur la mesure
        log(f"délégation (mesure) : {exc!r}")
    L.append(f"Réglages : `{CMD} delegation --mode auto|max|conseil|off` · `{CMD} delegation --modele eclaireur=sonnet` "
             "(ou `Explore=off`, `general-purpose=off`, `nom=defaut`)")
    return "\n".join(L)
