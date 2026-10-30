"""Connecteurs et serveurs MCP (Gmail, Agenda, Shopify, Canva, YouTube, France Travail…) : le cerveau retient lesquels
sont branchés (pièces jointes du transcript : outils différés annoncés, serveurs à authentifier, en échec), propose tout
seul le bon quand un message en a besoin — « 🔌 … ToolSearch select:… » : la requête exacte du premier coup, seulement
les outils utiles — et signale au démarrage les nouveaux qu'aucune phrase française ne déclenche. Zéro token hors réflexe."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .common import CLAUDE_HOME, STATE_DIR, fold, read_json, short, write_json

FILE = STATE_DIR / "outils.json"
V = 1
KINDS = ("deferred_tools_delta", "mcp_instructions_delta")
TOOL_RE = re.compile(r"^mcp__(.+?)__(.+)$")
# Outils de l'app (déjà chargés, ou propres à l'onglet Code) et le cerveau lui-même (sa CLI passe avant) : jamais soufflés
SKIP_RE = re.compile(r"^(?:ccd_|Claude_|visualize$|terminal$|plugin_cerveau_)")
NAME_RE = re.compile(r"[a-z]+(?:-[a-z]+)*")  # clé lisible (« omniroute »), pas un UUID de connecteur claude.ai
UUID_RE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
ADDR_RE = re.compile(r"https?://\S+|www\.\S+|[\w.+-]+@[\w-]+\.[\w.]+")
PLUGIN_RE = re.compile(r"plugin_[A-Za-z0-9-]+_([A-Za-z]+(?:-[A-Za-z]+)*)")  # plugin_marketing_klaviyo → klaviyo
FRESH_DAYS = 21  # serveur pas revu branché depuis plus longtemps : plus soufflé (débranché, compte changé)
LONG_CHARS = 600  # au-delà (texte collé), un mot seul ne suffit plus : il faut une phrase
SESSION_CAP, MAX_ITEMS = 6, 2

# Connecteurs connus, reconnus à leurs outils (fp : tous présents) et non au nom du serveur (UUID pour ceux du compte
# claude.ai). trig : phrases tolérantes (fautes, phonétique ; « a / b c » = a c ou b c, une seule jonction, mots du
# milieu seuls) ; exact : tournures où le possessif compte (« mes mails », pas « les mails de relance ») ; tools : ceux à
# charger d'abord ; query : recherche à la place (computer-use : toute la boîte d'un coup, consigne du serveur).
KNOWN = [
    {"id": "gmail", "label": "Gmail", "fp": ("search_threads", "get_thread", "create_draft"),
     "tools": ("search_threads", "get_thread", "create_draft"),
     "trig": ["gmail", "boîte mail", "mails non lus", "mail non lu", "nouveaux mails",
              "lis / trie / cherche / retrouve mails", "lis / trie / cherche / retrouve emails", "réponds au mail",
              "envoie / écris / rédige mail", "brouillon de mail", "brouillon de réponse"],
     "exact": ["mes mails", "mes e-mails", "mes emails", "ma boîte mail", "ma boîte de réception"]},
    {"id": "agenda", "label": "Google Agenda", "fp": ("list_events", "create_event"),
     "tools": ("list_events", "create_event", "suggest_time"),
     "trig": ["google agenda", "google calendar", "ajoute / note / programme / planifie / crée / cale / prends rdv",
              "ajoute / note / programme / planifie / crée / cale / prends rendez-vous", "créneau libre",
              "trouve un créneau", "planifie une réunion"],
     "exact": ["mon agenda", "mon calendrier", "mes rdv", "mes rendez-vous", "mon rdv", "mon rendez-vous",
               "dans l'agenda", "sur l'agenda", "un rdv", "un rendez-vous"]},
    {"id": "shopify", "label": "Shopify", "fp": ("get-shop-info", "list-orders"),
     "tools": ("get-shop-info", "list-orders", "run-analytics-query", "search_products"),
     "trig": ["shopify", "commandes / ventes / stock / produits de la boutique", "chiffre d'affaires de la boutique"],
     "exact": ["mes commandes", "mes ventes", "mes produits", "mon stock"]},
    {"id": "canva", "label": "Canva", "fp": ("generate-design", "search-designs"),
     "tools": ("search-designs", "generate-design", "export-design"),
     "trig": ["crée / génère / dessine visuel", "crée / génère / dessine affiche", "crée / génère / dessine flyer",
              "crée / génère / dessine bannière", "crée / génère / dessine miniature", "crée / génère / dessine logo"],
     "exact": ["canva", "sur canva", "dans canva", "fais une affiche", "fais un flyer", "fais un visuel",
               "fais une bannière", "fais une miniature", "fais un logo"]},
    {"id": "youtube", "label": "YouTube", "fp": ("search_you_tube", "load_captions"),
     "tools": ("search_you_tube", "video_details", "load_captions"),
     "trig": ["cherche sur youtube", "chaîne youtube", "statistiques de la chaîne", "sous-titres de la vidéo",
              "transcription de la vidéo", "résume la vidéo", "publie / poste / upload youtube"],
     "exact": ["youtu.be", "youtube.com"]},
    {"id": "francetravail", "label": "France Travail", "fp": ("search_jobs", "rome_search"),
     "tools": ("search_jobs", "get_job", "rome_search"),
     "trig": ["france travail", "pôle emploi", "offres d'emploi", "annonces d'emploi", "cherche / trouve / postule emploi",
              "cherche / trouve / postule job", "cherche / trouve / postule boulot", "cherche du travail", "fiche métier",
              "code rome"]},
    {"id": "registre", "label": "Registre des connecteurs", "fp": ("search_mcp_registry", "suggest_connectors"),
     "tools": ("search_mcp_registry", "suggest_connectors"),
     "trig": ["trouve / cherche serveur mcp"],
     "exact": ["un connecteur", "connecteurs pour", "nouveau connecteur", "nouveaux connecteurs", "un serveur mcp",
               "serveur mcp pour"]},
    {"id": "taches", "label": "Tâches planifiées", "fp": ("create_scheduled_task", "list_scheduled_tasks"),
     "tools": ("create_scheduled_task", "list_scheduled_tasks", "update_scheduled_task"),
     "trig": ["tâche planifiée", "planifie une tâche", "programme une tâche", "tâche récurrente"]},
    {"id": "chrome", "label": "Chrome (ton navigateur, tes comptes)", "fp": ("tabs_context_mcp", "navigate"),
     "tools": ("tabs_context_mcp", "navigate", "computer", "get_page_text", "find", "read_page", "tabs_create_mcp"),
     "trig": ["ouvre / utilise chrome", "extension chrome", "claude in chrome"],
     "exact": ["mon chrome", "avec chrome", "dans chrome", "sur chrome", "utilise mon navigateur", "ouvre mon navigateur",
               "avec mon navigateur", "pilote mon navigateur"]},
    {"id": "pc", "label": "Contrôle du PC (applications)", "fp": ("request_access", "screenshot"),
     "query": "computer-use", "max": 30,
     "trig": ["prends le contrôle", "clique à ma place"],
     "exact": ["pilote mon pc", "contrôle mon pc", "contrôle de mon pc", "pilote mon ordinateur", "contrôle mon ordinateur",
               "contrôle de mon ordinateur"]},
    {"id": "granola", "label": "Granola (notes de réunion)", "fp": ("get_meeting_attachment",),
     "trig": ["granola", "notes de réunion", "compte rendu de réunion"]},
    {"id": "github", "label": "Recherche de code GitHub", "fp": ("searchGitHub",), "tools": ("searchGitHub",),
     "trig": ["cherche / trouve sur github", "code sur github"]},
    {"id": "supermetrics", "label": "Supermetrics", "fp": ("get_business_context", "get_dashboards"),
     "trig": ["supermetrics"]},
    {"id": "ahrefs", "label": "Ahrefs", "fp": ("management-projects-create",), "trig": ["ahrefs", "backlinks", "brand radar"]},
    {"id": "contentsquare", "label": "Contentsquare", "fp": ("getErrorExplorer",), "trig": ["contentsquare"]},
]
BY_ID = {e["id"]: e for e in KNOWN}


def key_of(server: str) -> str:
    """Nom de serveur (« plugin:francetravail:francetravail ») → préfixe de ses outils (« plugin_francetravail_… »)."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", server)


# ------------------------------------------------------------------------------------------ collecte (transcript)
def _names(a, k) -> list:
    out = []
    vals = a.get(k)
    for v in vals if isinstance(vals, list) else ():
        v = v.get("name") if isinstance(v, dict) else v
        if isinstance(v, str) and v:
            out.append(v)
    return out


def collect(st, a) -> None:
    """Pièce jointe de la session principale → st["_outils"] (fusionné dans outils.json au Stop, puis retiré).
    Le dernier événement par serveur l'emporte : branché (outils annoncés), retiré, à authentifier, en échec."""
    o = st.setdefault("_outils", {"tools": {}, "srv": {}, "pending": [], "desc": {}, "full": False})
    if a.get("type") == "deferred_tools_delta":
        if not st.get("outils_debut"):  # 1re annonce de la session : la liste complète (les suivantes sont des écarts)
            st["outils_debut"] = o["full"] = True
        removed = set()
        for k in ("removedNames", "addedNames", "readdedNames"):
            for n in _names(a, k):
                m = TOOL_RE.match(n)
                if not m:
                    continue
                o["tools"][n] = k != "removedNames"
                if k == "removedNames":
                    removed.add(m.group(1))
                else:
                    o["srv"][m.group(1)] = "on"
        for key in removed:  # plus aucun de ses outils annoncés dans cette collecte : débranché
            if not any(on for n, on in o["tools"].items() if n.startswith(f"mcp__{key}__")):
                o["srv"][key] = "off"
        for k, state in (("needsAuthMcpServers", "auth"), ("failedMcpServers", "failed")):
            for v in _names(a, k):
                o["srv"][key_of(v)] = state
        pend = {key_of(v) for v in _names(a, "pendingMcpServers")}
        if pend:
            o["pending"] = sorted(pend | set(o["pending"]))
    elif a.get("type") == "mcp_instructions_delta":
        names, blocks = a.get("addedNames"), a.get("addedBlocks")
        for name, block in zip(names if isinstance(names, list) else (), blocks if isinstance(blocks, list) else ()):
            if isinstance(name, str) and isinstance(block, str):
                body = [ln.strip("# ").strip() for ln in block.splitlines()[1:]]
                body = [ln for ln in body if ln]
                if body:
                    o["desc"][key_of(name)] = short(body[0], 160)


def scan(path) -> dict:
    """Relit un transcript entier (pièces jointes seulement : lecture rapide, en octets) → collecte à fusionner."""
    st = {}
    try:
        fh = open(path, "rb")
    except OSError:
        return {}
    with fh:
        for raw in fh:
            if b"deferred_tools_delta" not in raw and b"mcp_instructions_delta" not in raw:
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("type") == "attachment" and not obj.get("isSidechain"):
                a = obj.get("attachment")
                if isinstance(a, dict) and a.get("type") in KINDS:
                    collect(st, a)
    return st.get("_outils") or {}


def recent_transcripts(n=5) -> list:
    """Les n derniers transcripts de sessions principales (pas les sous-agents), du plus ancien au plus récent."""
    root = CLAUDE_HOME / "projects"
    files = []
    for f in root.glob("*/*.jsonl") if root.is_dir() else ():
        try:
            files.append((f.stat().st_mtime, f))
        except OSError:
            continue
    return [f for _, f in sorted(files)[-n:]]


# ------------------------------------------------------------------------------------------ registre
def load() -> dict:
    reg = read_json(FILE, None)
    return reg if isinstance(reg, dict) and reg.get("v") == V and isinstance(reg.get("servers"), dict) \
        else {"v": V, "servers": {}}


def _off(s, now, why) -> None:
    if now >= s.get("off", 0):
        s["off"], s["why"] = now, why


def merge(o, now=None, reg=None) -> dict:
    """Fusionne une collecte dans outils.json (écrit toujours). Un serveur garde tous ses outils déjà vus (empreinte) ;
    « seen » = vu branché, « off » = vu débranché (retiré, absent de l'annonce complète d'une session, à authentifier,
    en échec) ; le plus récent l'emporte, quel que soit l'ordre des fusions (relecture d'anciens transcripts)."""
    now = now or time.time()
    reg = reg or load()
    srv, o = reg["servers"], o or {}
    by = {}
    for name, on in (o.get("tools") or {}).items():
        m = TOOL_RE.match(name)
        if m:
            by.setdefault(m.group(1), {})[m.group(2)] = on
    states, desc = o.get("srv") or {}, o.get("desc") or {}
    for key in set(by) | set(states) | set(desc):
        if SKIP_RE.match(key):
            continue
        s = srv.setdefault(key, {"first": now, "tools": []})
        s["first"] = min(s.get("first", now), now)
        tools = by.get(key, {})
        if tools:
            s["tools"] = sorted(set(s.get("tools", [])) | set(tools))[:300]
        state = states.get(key)
        if state == "on":
            s["seen"] = max(s.get("seen", 0), now)
        elif state in ("auth", "failed"):
            _off(s, now, state)
        elif state == "off" or (tools and not any(tools.values())):
            _off(s, now, "retiré")
        if desc.get(key):
            s["desc"] = desc[key]
    if o.get("full"):  # annonce complète : un serveur connu qui n'y figure pas n'est plus branché
        named = set(states) | set(o.get("pending") or ())
        for key, s in srv.items():
            if key not in named and s.get("seen", 0) < now:
                _off(s, now, "absent")
    write_json(FILE, reg)
    return reg


def session_on(prev, o) -> list:
    """Serveurs branchés dans la session (st["outils_on"]), tenus à jour à chaque fusion."""
    on = set(prev or ())
    for key, v in (o.get("srv") or {}).items():
        (on.add if v == "on" else on.discard)(key)
    return sorted(k for k in on if not SKIP_RE.match(k))


def identify(s) -> dict | None:
    tools = set(s.get("tools") or ())
    return next((e for e in KNOWN if set(e["fp"]) <= tools), None) if tools else None


def alive(s, now=None, fresh_days=FRESH_DAYS) -> bool:
    now = now or time.time()
    return bool(s.get("seen")) and s["seen"] >= s.get("off", 0) and now - s["seen"] <= fresh_days * 86400


_LABEL_STOP = {"this", "the", "you", "use", "a", "an", "it", "these", "here", "mcp", "server", "instructions",
               "important", "if", "when", "always", "never", "note", "please", "all", "for"}


def label_of(key, s) -> str:
    """Nom lisible : connecteur connu, sinon tiré des instructions du serveur (« Granola is… » → Granola), sinon la clé."""
    e = identify(s)
    if e:
        return e["label"]
    words = []
    for w in re.findall(r"[A-Za-z][\w.-]*", s.get("desc") or ""):
        if not w[0].isupper() or w.lower() in _LABEL_STOP:
            if words or w.lower() not in _LABEL_STOP:
                break
            continue
        words.append(w)
    return " ".join(words[:3]) or key


def auto_names(key, s) -> list:
    """Serveur inconnu : son nom sert de déclencheur exact (« omniroute », « klaviyo », « Granola »), pas un UUID."""
    lab = label_of(key, s)
    if lab == key:
        m = PLUGIN_RE.fullmatch(key)
        lab = m.group(1) if m else key
        if not NAME_RE.fullmatch(lab.lower()):
            return []
        lab = lab.replace("-", " ")
    return [lab] if len(lab) >= 5 else []


# ------------------------------------------------------------------------------------------ réflexe
_COMPILED: dict = {}


def _exact(phrase):
    """Tournure exacte : mots dans l'ordre, séparés par au moins un signe (« youtu.be » ≠ « youtube »), pluriel libre."""
    words = re.findall(r"[a-z0-9]+", fold(phrase))
    pat = r"\W+".join(re.escape(w[:-1]) + "s?" if len(w) > 2 and w.endswith("s") else re.escape(w) for w in words)
    return re.compile(rf"(?<![a-z0-9]){pat}(?![a-z0-9])")


def _phrases(e, key, s, own=()) -> list:
    """[(texte, groupes, regex)] : phrases tolérantes (groupes) ou exactes (regex) ; own = phrases de la config."""
    from .skills import phrase_groups
    ident = e["id"] if e else "~" + key
    got = _COMPILED.get(ident)
    if got is None:
        if e:
            got = [(p, g, None) for p in e.get("trig", ()) for g in [phrase_groups(p)] if g]
            got += [(p, None, _exact(p)) for p in e.get("exact", ())]
        else:
            got = [(p, None, _exact(p)) for p in auto_names(key, s)]
        _COMPILED[ident] = got
    return got + [(p, g, None) for p in own if isinstance(p, str) for g in [phrase_groups(p)] if g]


def _mine(key, e, own) -> list:
    """Phrases de la config pour ce serveur : sous l'id du connecteur connu (« gmail ») et sous sa clé."""
    return list(own.get(e["id"] if e else key) or []) + (list(own.get(key) or []) if e else [])


def phrases_of(key, s, oc=None) -> list:
    """Toutes les phrases qui déclenchent ce serveur : défauts du plugin (ou son nom), puis celles de la config."""
    e = identify(s)
    return [p for p, _, _ in _phrases(e, key, s, _mine(key, e, (oc or {}).get("triggers") or {}))]


def _weak(p, groups, rx) -> bool:
    """Un seul mot, ou une adresse (« youtu.be ») : ne suffit pas dans un long texte collé (article, sortie de commande)."""
    return len(groups) < 2 if rx is None else "." in p or len(re.findall(r"[a-z0-9]+", fold(p))) < 2


def _hit(groups, q) -> bool:
    from .skills import _covered
    n = len(groups)
    hits = sorted((p, gi) for gi, g in enumerate(groups) for p in q.positions(g))
    return _covered(hits, n, n + 3)


def match(text, oc=None, exclude=(), reg=None, now=None, live=None) -> list:
    """Connecteurs branchés que le message demande, le plus récemment vu d'abord (un seul par connecteur connu).
    live : serveurs branchés dans cette session (sinon : vus branchés ces derniers jours)."""
    oc = oc or {}
    reg = reg or load()
    if not text or not reg["servers"]:
        return []
    from .skills import Query
    own = oc.get("triggers") or {}
    fresh = oc.get("fresh_days", FRESH_DAYS)
    bare = ADDR_RE.sub(" ", text)  # « github.com/…/omniroute », « …@gmail.com » : une adresse n'est pas une demande
    q, ft, fb, long_text = None, fold(text), fold(bare), len(text) > oc.get("long_chars", LONG_CHARS)
    out, done = [], set(exclude)
    for key, s in sorted(reg["servers"].items(), key=lambda kv: -kv[1].get("seen", 0)):
        if SKIP_RE.match(key) or not (key in live if live else alive(s, now, fresh)):
            continue
        e = identify(s)
        ident = e["id"] if e else key
        if ident in done or key in done:
            continue
        why = None
        for p, groups, rx in _phrases(e, key, s, _mine(key, e, own)):
            if long_text and _weak(p, groups, rx):
                continue
            if rx is not None:
                hit = bool(rx.search(ft if "." in p else fb))
            else:
                q = q or Query(bare)
                hit = _hit(groups, q)
            if hit:
                why = p
                break
        if why:
            done.add(ident)
            out.append({"key": key, "id": ident, "entry": e, "server": s, "why": why})
    return out


def call_for(r) -> str:
    """La requête ToolSearch qui charge les bons outils du premier coup."""
    e, s, key = r["entry"] or {}, r["server"], r["key"]
    if e.get("query"):
        return f"ToolSearch « {e['query']} » (max_results {e.get('max', 30)})"
    have = s.get("tools") or []
    tools = [t for t in e.get("tools", ()) if t in have] or (have if len(have) <= 4 else [])
    if tools:
        return "ToolSearch `select:" + ",".join(f"mcp__{key}__{t}" for t in tools) + "`"
    return f"ToolSearch « +{key} <besoin> » (max_results 5)"


def hint_line(r) -> str:
    return f"🔌 {short_name(r['key'], r['server'])} est branché (« {r['why']} ») : s'il sert, ses outils en un seul {call_for(r)}"


def reflex(text, st, oc=None) -> list:
    """Lignes du réflexe pour un message (hook UserPromptSubmit) : un connecteur au plus une fois par session."""
    oc = oc or {}
    hinted = list(st.get("outils_hinted") or [])
    if not oc.get("enabled", True) or len(hinted) >= oc.get("session_cap", SESSION_CAP):
        return []
    res = match(text, oc, exclude=set(hinted), live=set(st.get("outils_on") or ()))[:oc.get("max_items", MAX_ITEMS)]
    if res:
        st["outils_hinted"] = hinted + [r["id"] for r in res]
    return [hint_line(r) for r in res]


# ------------------------------------------------------------------------------------------ état, démarrage, veille
def status(s, now=None, fresh_days=FRESH_DAYS) -> str:
    if alive(s, now, fresh_days):
        return "✅"
    if s.get("seen") and s["seen"] >= s.get("off", 0):
        return f"💤 pas vu depuis {fresh_days} j"
    return {"auth": "🔒 à authentifier (/mcp)", "failed": "⚠️ en échec", "retiré": "⛔ retiré"}.get(s.get("why"), "⛔ absent")


def date_of(ts) -> str:
    return time.strftime("%d/%m/%Y", time.localtime(ts)) if ts else "—"


def _mtime(p) -> float:
    try:
        return Path(p).stat().st_mtime
    except OSError:
        return time.time()


def bootstrap(paths) -> dict:
    """outils.json absent (cerveau installé en cours de session) : relit les transcripts donnés, du plus ancien au plus
    récent, pour connaître les serveurs tout de suite."""
    reg = load()
    for p in paths:
        reg = merge(scan(p), now=_mtime(p), reg=reg)
    return reg if paths else merge({}, reg=reg)


def has_triggers(key, s, oc=None) -> bool:
    return bool(phrases_of(key, s, oc))


def short_name(key, s) -> str:
    """Nom affiché : libellé, sinon nom du plugin (plugin_marketing_klaviyo → klaviyo), sinon la clé (UUID : son début)."""
    lab = label_of(key, s)
    if lab != key:
        return lab
    m = PLUGIN_RE.fullmatch(key)
    return m.group(1) if m else key[:8] if UUID_RE.fullmatch(key) else key


def ref_of(key, s, servers=()) -> str:
    """Ce qu'on tape dans `brain outils trig` : id du connecteur connu, sinon le début de l'UUID quand il suffit."""
    e = identify(s)
    if e:
        return e["id"]
    head = key[:8]
    return head if UUID_RE.fullmatch(key) and sum(k.startswith(head) for k in servers) == 1 else key


def resolve(ref, reg=None):
    """Ce que l'utilisateur tape (« gmail », « e33feaee », « Granola », « omniroute ») → (clé de config, serveur ou
    None si pas encore vu). ValueError si inconnu ou ambigu."""
    reg = reg or load()
    servers = {k: s for k, s in reg["servers"].items() if not SKIP_RE.match(k)}
    f = fold(ref).strip()
    if f in BY_ID:
        same = [s for s in servers.values() if (identify(s) or {}).get("id") == f]
        return f, max(same, key=lambda s: s.get("seen", 0), default=None)
    keys = ([ref] if ref in servers else [k for k in servers if f and fold(k).startswith(f)]
            or [k for k, s in servers.items() if f in (fold(label_of(k, s)), fold(short_name(k, s)))])
    if len(keys) != 1:
        raise ValueError(f"connecteur ambigu : {ref} ({few(sorted(keys), 5)})" if keys else
                         f"connecteur inconnu : {ref} — connus : {few(sorted(BY_ID), 20)} (branchés : `brain outils`)")
    s = servers[keys[0]]
    e = identify(s)
    return (e["id"] if e else keys[0]), s


_FR_RE = re.compile(r"[àâäçéèêëîïôöùûüÿœæ]|\b(?:le|la|les|un|une|des|du|de|mon|ma|mes|ton|ta|tes|ce|cette|pour|avec|sur"
                    r"|dans|et|je|tu|il|nous|vous|fais|mets|ajoute|trouve|cherche|quel|quelle|comment)\b", re.I)


def french(skill) -> bool:
    """La skill a au moins un déclencheur en français (ajouté par le cerveau ou la config, ou écrit en français)."""
    return any(p.get("added") or _FR_RE.search(p.get("text") or "") for p in skill.get("triggers") or ())


def few(names, n) -> str:
    return ", ".join(names[:n]) + (f" +{len(names) - n}" if len(names) > n else "")


def veille(catalog=None, oc=None, now=None, reg=None) -> str:
    """Au démarrage : nouveaux serveurs branchés et nouvelles skills qu'aucune phrase française ne déclenche (une ligne,
    seulement quand il y en a). La première fois, on prend l'existant pour base, sans rien annoncer."""
    oc = oc or {}
    reg = reg or load()
    fresh = oc.get("fresh_days", FRESH_DAYS)
    v = reg.setdefault("veille", {})
    changed, parts = False, []
    servers = {k: s for k, s in reg["servers"].items() if not SKIP_RE.match(k) and alive(s, now, fresh)}
    if servers:
        old = v.get("servers")
        if old is not None:
            new = [k for k in sorted(servers) if k not in old and not has_triggers(k, servers[k], oc)]
            for k in new[:3]:
                tools = servers[k].get("tools") or []
                parts.append(f"🔌 {short_name(k, servers[k])} ({len(tools)} outils : {few(tools, 3)}) — "
                             f"`brain outils trig {ref_of(k, servers[k], reg['servers'])} \"phrase\"`")
        if old is None or set(servers) - set(old):
            v["servers"], changed = sorted(set(servers) | set(old or ())), True
    if catalog is not None:  # liste vide (aucune skill) : base vide, la première installée sera vue
        names = {s["name"] for s in catalog}
        old = v.get("skills")
        if old is not None:
            new = sorted(s["name"] for s in catalog if s["name"] not in old and not french(s))
            if new:
                parts.append(f"🧩 {len(new)} skill(s) ({few(new, 5)}) — `brain skill trig <skill> \"phrase\"`")
        if old is None or names - set(old):
            v["skills"], changed = sorted(names | set(old or ())), True
    if changed:
        write_json(FILE, reg)
    if not parts:
        return ""
    return ("🆕 Nouveaux sans déclencheur français (le réflexe ne les proposera pas tout seul) : " + " · ".join(parts)
            + ". S'ils peuvent servir à l'utilisateur, ajoute 2 ou 3 phrases françaises avec ces commandes.")
