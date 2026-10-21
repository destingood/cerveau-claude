"""Où partent les tokens — mesuré sur les transcripts Claude Code des dernières heures (lecture locale, zéro token).
Contexte relu par requête, taille des premières requêtes, coût fixe au démarrage (skills, MCP, outils différés, hooks),
relances du cerveau, et habitudes coûteuses avec ce qu'elles « portent » : leur taille multipliée par le nombre de
requêtes qui la relisent jusqu'à la compaction suivante. Poids réel aux prix relatifs de l'API (`weigh`) : écritures et
lectures du cache, sortie, compactions, pauses, cache de 5 min et de 1 h simulés. Les leviers renvoient à `brain eco`."""
from __future__ import annotations

import json
import math
import re
import statistics
import time
from datetime import datetime

from .common import CHARS_PER_TOKEN, CLAUDE_HOME, load_config, log
from .journal import AUTO_RE

BIG_BASH, BIG_READ, BIG_SEARCH = 1500, 3000, 1500  # tokens
IMAGE_TOKENS = 1600  # ordre de grandeur d'une capture d'écran : une image ne se mesure pas au nombre de caractères
PREVIEW_CHARS = 2000  # une sortie Bash mise en fichier par le mode éco : Claude n'en garde que cet aperçu
STOP_MARKS = ("🧠 Cerveau — avant de conclure", "🧠 Cerveau — le contexte vient d'être compacté")
# Le rappel ouvre le texte de la ligne, à l'enrobage de Claude Code près (« Stop hook feedback: [commande]: ») :
# une citation plus loin dans un message n'en est pas un.
MARK_PREFIX = 400
BRAIN_MARKS = ("🧠", "📁")  # le texte injecté par les hooks du cerveau en porte toujours un
FIXED_KINDS = ("skill_listing", "mcp_instructions_delta", "deferred_tools_delta", "hook_additional_context")
HABITS = [
    ("bash", f"sorties Bash/PowerShell > {BIG_BASH} tokens", "filtrer : `| tail -n`, `grep -c`, options `-q`"),
    ("read", f"Read de fichiers entiers > {BIG_READ} tokens", "`explain`/Grep d'abord, puis Read offset/limit"),
    ("search", f"Grep/Glob > {BIG_SEARCH} tokens", "recherche très large → sous-agent Explore, sinon motif plus précis"),
    ("page", f"read_page / pages web > {BIG_SEARCH} tokens", "get_page_text ou find plutôt que l'arbre entier"),
    ("images", f"captures et images (≈ {IMAGE_TOKENS} tokens chacune)", "lire le texte de la page plutôt que la capturer"),
]


def _ctx(u) -> int:
    return u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)


def _size(c):
    """(caractères de texte, images) d'un résultat d'outil."""
    if isinstance(c, str):
        return len(c), 0
    chars = imgs = 0
    for b in c if isinstance(c, list) else []:
        if isinstance(b, dict) and b.get("type") == "image":
            imgs += 1
        elif isinstance(b, dict) and b.get("type") == "text":
            chars += len(b.get("text") or "")
        else:
            chars += len(json.dumps(b, ensure_ascii=False))
    return chars, imgs


def _habit(name, inp, tok, imgs):
    low = (name or "").lower()
    if imgs or "screenshot" in low or (low.endswith("computer") and inp.get("action") in ("screenshot", "zoom")):
        return "images"
    if ("read_page" in low or "get_page_text" in low or low == "webfetch") and tok > BIG_SEARCH:
        return "page"
    if name in ("Bash", "PowerShell") and tok > BIG_BASH:
        return "bash"
    if name == "Read" and tok > BIG_READ and not inp.get("limit") and not inp.get("offset"):
        return "read"
    if name in ("Grep", "Glob") and tok > BIG_SEARCH:
        return "search"
    return None


# Lectures une par une : chaque requête relit tout le contexte, donc deux lectures indépendantes faites en deux requêtes
# coûtent un contexte entier de plus qu'en une seule (plusieurs plages ou fichiers par commande, appels parallèles).
SOLO_TAIL = 8_000_000  # octets lus en fin de transcript : plusieurs cycles de compaction, même pour une session de 300 Mo
SOLO_MIN, SOLO_SHARE = 12, 0.3  # signalé à partir de 12 lectures enchaînées et 30 % des requêtes depuis la compaction
READ_TOOLS = {"Read", "Grep", "Glob"}
_READ_CMD = re.compile(r"^(?:\s*cd\s+[^;&|]+(?:&&|;))?\s*(?:sed\s+-n|cat|head|tail|grep|rg|ls|wc|find|nl|awk|"
                       r"git\s+(?:show|log|diff|status|grep|blame)|Get-Content|gc|Select-String|Get-ChildItem)\b", re.I)


def _is_read(name, inp) -> bool:
    if name in READ_TOOLS:
        return True
    cmd = inp.get("command") if name in ("Bash", "PowerShell") and isinstance(inp, dict) else None
    return isinstance(cmd, str) and bool(_READ_CMD.match(cmd))


def solo(path, tail=SOLO_TAIL) -> dict:
    """Depuis la dernière compaction (cherchée dans les `tail` derniers octets du transcript) → {"reqs": requêtes,
    "single": requêtes à un seul appel d'outil, "chained": lectures seules faites juste après une autre lecture seule
    (regroupables), "ctx": contexte moyen relu par requête}. Juste après la compaction (rien encore depuis), c'est le
    cycle qui vient de se terminer qui compte."""
    order, info, last = [], {}, ([], {})
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - tail))
            if size > tail:
                fh.readline()  # ligne coupée
            for raw in fh:
                if b"compact_boundary" in raw and b'"system"' in raw:
                    try:
                        o = json.loads(raw)
                    except ValueError:
                        continue
                    if o.get("type") == "system" and o.get("subtype") == "compact_boundary":
                        last = (order, info) if order else last
                        order, info = [], {}
                    continue
                if b'"assistant"' not in raw or b'"usage"' not in raw:
                    continue
                try:
                    o = json.loads(raw)
                except ValueError:
                    continue
                m = o.get("message") if o.get("type") == "assistant" and not o.get("isSidechain") else None
                mid = m.get("id") if isinstance(m, dict) else None
                if not mid or not isinstance(m.get("usage"), dict):
                    continue
                if mid not in info:
                    order.append(mid)
                    info[mid] = {"ctx": _ctx(m["usage"]), "tools": []}
                for b in m.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        info[mid]["tools"].append((b.get("name"), b.get("input") or {}))
    except OSError:
        return {"reqs": 0, "single": 0, "chained": 0, "ctx": 0}
    if not order:
        order, info = last
    single = chained = 0
    prev_read = False
    for mid in order:
        tools = info[mid]["tools"]
        alone = len(tools) == 1
        single += alone
        is_read = alone and _is_read(*tools[0])
        chained += is_read and prev_read
        prev_read = is_read
    ctx = sum(info[mid]["ctx"] for mid in order) // len(order) if order else 0
    return {"reqs": len(order), "single": single, "chained": chained, "ctx": ctx}


def solo_notice(path) -> str:
    """Après une compaction : une ligne si, depuis la précédente, beaucoup de lectures ont été faites une par une."""
    s = solo(path)
    if s["chained"] < SOLO_MIN or s["chained"] < SOLO_SHARE * s["reqs"]:
        return ""
    return (f"⚡ Tokens — depuis la compaction précédente : {s['reqs']} requêtes, {round(100 * s['single'] / s['reqs'])} % "
            f"à un seul appel, dont {s['chained']} lectures enchaînées une par une ; chaque appel relit tout le contexte "
            f"(≈ {round(s['ctx'] / 1000)} k tokens). Groupe les lectures (plusieurs plages ou fichiers dans une commande, "
            "Read plus large), lance les appels indépendants dans un même message, enchaîne les commandes dépendantes "
            "avec &&.")


def _strings(o) -> list:
    """Textes qu'une ligne de transcript ajoute à la conversation : message tapé (jamais un résultat d'outil) ou pièce
    jointe (`rendered` = ce que Claude lit, sinon le contenu de la pièce jointe)."""
    t = o.get("type")
    if t == "user":
        m = o.get("message")
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str):
            return [c]
        blocks = [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []
        if any(b.get("type") == "tool_result" for b in blocks):
            return []
        return [b["text"] for b in blocks if b.get("type") == "text" and isinstance(b.get("text"), str)]
    if t == "attachment":
        rendered = o.get("rendered")
        rendered = [rendered] if isinstance(rendered, str) else rendered if isinstance(rendered, list) else []
        texts = [r if isinstance(r, str) else r.get("content") for r in rendered
                 if isinstance(r, str) or (isinstance(r, dict) and isinstance(r.get("content"), str))]
        if texts:
            return texts
        a = o.get("attachment") if isinstance(o.get("attachment"), dict) else {}
        for k in ("content", "addedBlocks", "addedLines"):
            v = a.get(k)
            texts += [v] if isinstance(v, str) else [x for x in v if isinstance(x, str)] if isinstance(v, list) else []
        return texts
    return []


def _fixed(o, pre):
    """Pièce jointe vue avant la 1re réponse → coût fixe du démarrage (en caractères, par poste)."""
    a = o.get("attachment") if isinstance(o.get("attachment"), dict) else {}
    kind = a.get("type")
    if kind not in FIXED_KINDS:
        return
    texts = _strings(o)
    chars = sum(len(x) for x in texts)
    if kind == "skill_listing":
        n = a.get("skillCount")
        pre["skills"] += chars
        pre["skills_n"] += n if isinstance(n, int) else sum(1 for x in str(a.get("content") or "").split("\n")
                                                              if x.startswith("- "))
    elif kind == "mcp_instructions_delta":
        pre["mcp"] += chars
    elif kind == "deferred_tools_delta":
        pre["deferred"] += chars
    else:  # texte ajouté par un hook : celui du cerveau (🧠 / 📁) ou celui d'un autre
        pre["brain" if any(m in x for x in texts for m in BRAIN_MARKS) else "hooks"] += chars


def _is_prompt(o) -> bool:
    """Vrai message de l'utilisateur (ni résultat d'outil, ni rappel de hook, ni message automatique ou d'une autre
    session, ni résumé de compaction) — même règle que le journal."""
    if o.get("isMeta") or o.get("isCompactSummary"):
        return False
    origin = o.get("origin")
    if (o.get("turnOrigin") or (origin.get("kind") if isinstance(origin, dict) else None) or "human") != "human":
        return False
    m = o.get("message")
    c = m.get("content") if isinstance(m, dict) else None
    if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "image" for b in c):
        return True  # message fait d'une capture
    return any(x.strip() and not AUTO_RE.match(x.strip()) for x in _strings(o))


def _scan_file(path, cpt, out):
    """Un transcript → requêtes, premières requêtes, habitudes, paires de calibrage, coût fixe, relances du cerveau."""
    ev, seen, calls, first, per = [], set(), {}, True, {}
    last_req, between = None, []
    sub = "subagents" in path.parts
    pre = {"skills": 0, "skills_n": 0, "mcp": 0, "deferred": 0, "brain": 0, "hooks": 0}
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return
    with fh:
        for raw in fh:
            marked = "Cerveau" in raw and ("conclure" in raw or "compact" in raw)
            early = first and not sub and '"attachment"' in raw
            if not (early or marked or '"assistant"' in raw or '"user"' in raw or "compact_boundary" in raw):
                continue
            try:
                o = json.loads(raw)
            except ValueError:
                continue
            t = o.get("type")
            if marked and t in ("user", "attachment") and any(0 <= x.find(m) <= MARK_PREFIX
                                                              for x in _strings(o) for m in STOP_MARKS):
                ev.append(("B",))  # rappel de fin de tâche du cerveau
                continue
            if t == "attachment":
                if early:
                    _fixed(o, pre)
            elif t == "system" and o.get("subtype") == "compact_boundary":
                ev.append(("C",))
                last_req, between = None, []
            elif t == "assistant":
                m = o.get("message") or {}
                u, mid = m.get("usage"), m.get("id")
                p = per.setdefault(mid, [0, None, _ctx(u)]) if mid and isinstance(u, dict) else None
                for b in m.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        calls[b.get("id")] = (b.get("name"), b.get("input") or {})
                        if p is not None:  # appels de cette requête (un bloc par ligne, même id)
                            p[0] += 1
                            p[1] = p[1] or calls[b.get("id")]
                if not u or mid in seen:
                    continue
                seen.add(mid)
                c = _ctx(u)
                if first:
                    out["first_sub" if sub else "first_main"].append(c)
                    first = False
                if last_req and len(between) == 1 and between[0] > 3000:  # un seul gros résultat entre deux requêtes
                    tok = c - last_req[0] - last_req[1]
                    if tok > 200:
                        out["ratios"].append(between[0] / tok)
                last_req, between = (c, u.get("output_tokens", 0)), []
                ev.append(("R", c))
            elif t == "user":
                cont = (o.get("message") or {}).get("content")
                results = False
                for b in cont if isinstance(cont, list) else []:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        results = True
                        name, inp = calls.get(b.get("tool_use_id"), ("?", {}))
                        chars, imgs = _size(b.get("content"))
                        between.append(chars)
                        tok = chars / cpt + imgs * IMAGE_TOKENS
                        kind = _habit(name, inp if isinstance(inp, dict) else {}, chars / cpt, imgs)
                        if kind:
                            ev.append(("T", kind, tok))
                        if name in ("Bash", "PowerShell") and chars > out["eco_out"]:  # le mode éco la mettrait en fichier
                            ev.append(("E", (chars - PREVIEW_CHARS) / cpt))
                if not results and _is_prompt(o):
                    ev.append(("P",))
    prev = False
    for n, call, c in per.values():  # lectures seules juste après une autre : regroupables
        is_read = n == 1 and _is_read(*call)
        if is_read and prev:
            out["solo"][0] += 1
            out["solo"][1] += c
        prev = is_read
    out["solo"][2] += len(per)
    if not sub and not first:
        out["fixed"].append(pre)  # session principale qui a eu sa 1re réponse : coût fixe de son démarrage
    live = False
    for e in ev:  # relances : requêtes entre un rappel du cerveau et le vrai message suivant de l'utilisateur
        if e[0] == "B":
            out["relances"] += 1
            live = True
        elif e[0] == "P":
            live = False
        elif e[0] == "R" and live:
            out["relance_reqs"] += 1
            out["relance_ctx"] += e[1]
    after = 0
    for e in reversed(ev):  # ce qu'un résultat « porte » : relu par chaque requête suivante jusqu'à la compaction
        if e[0] == "C":
            after = 0
        elif e[0] == "R":
            after += 1
            out["reqs"].append(e[1])
        elif e[0] == "T":
            h = out["habits"].setdefault(e[1], [0, 0.0])
            h[0] += 1
            h[1] += e[2] * after
        elif e[0] == "E":
            out["eco_bash"][0] += 1
            out["eco_bash"][1] += e[1] * after


def measure(hours=48.0, cpt=None) -> dict:
    root = CLAUDE_HOME / "projects"
    cut = time.time() - hours * 3600
    files = [f for f in root.rglob("*.jsonl") if f.stat().st_mtime >= cut] if root.is_dir() else []
    try:
        eco_out = int((load_config().get("eco") or {}).get("bash_output_max_chars") or 10000)
    except (TypeError, ValueError):
        eco_out = 10000
    out = {"hours": hours, "files": len(files), "subfiles": sum("subagents" in f.parts for f in files),
           "reqs": [], "first_main": [], "first_sub": [], "habits": {}, "ratios": [],
           "fixed": [], "relances": 0, "relance_reqs": 0, "relance_ctx": 0, "eco_bash": [0, 0.0], "eco_out": eco_out,
           "solo": [0, 0, 0]}
    for f in files:
        _scan_file(f, cpt or CHARS_PER_TOKEN, out)
    return out


def _m(x) -> str:
    return f"{x / 1e6:.1f} M" if x >= 1e6 else f"{x / 1e3:.0f} k"


def _k(x) -> str:
    return f"{x / 1e3:.1f} k" if round(x) >= 1000 else f"{x:.0f}"


def _fixed_lines(d, cpt) -> list:
    """Coût fixe de chaque démarrage : médiane, sur les sessions principales, de ce qui est injecté avant la 1re réponse."""
    fx = d["fixed"]
    if not fx:
        return []
    med = lambda k: statistics.median(p[k] for p in fx)  # noqa: E731
    return [f"Coût fixe au démarrage (médiane de {len(fx)} session(s), avant la 1re réponse) :",
            f"  - skills : {med('skills_n'):.0f} listées ≈ {_k(med('skills') / cpt)} tok · instructions MCP "
            f"≈ {_k(med('mcp') / cpt)} · noms d'outils différés ≈ {_k(med('deferred') / cpt)}",
            f"  - cerveau (injection + 1er rappel) ≈ {_k(med('brain') / cpt)} · autres hooks ≈ {_k(med('hooks') / cpt)}"]


def _advice(d, cpt) -> list:
    """Une ligne par levier qui s'applique, tous vers `brain eco`."""
    from . import eco
    L, cur = [], {k: v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
                  for k, v in eco.current().items()}
    try:
        win = eco.targets()[1]
    except ValueError:
        win = eco.DEFAULT_WIN
    n_big, carried = d["eco_bash"]
    if n_big and not 0 < cur.get(eco.OUT_KEY, 0) <= d["eco_out"]:
        L.append(f"→ {n_big} sortie(s) Bash > {eco._n(d['eco_out'])} car. (porté jusqu'à {_m(carried)} tok) : "
                 "`brain eco --appliquer` les met en fichier, aperçu seul dans la conversation")
    over = [r for r in d["reqs"] if r > win]
    if over and not 0 < cur.get(eco.WIN_KEY, 0) <= win:
        L.append(f"→ {100 * len(over) / len(d['reqs']):.0f} % des requêtes relisent plus de {win // 1000} k tokens : "
                 "`brain eco --appliquer` résume la conversation plus tôt")
    n_solo, ctx_solo, n_reqs = d.get("solo") or (0, 0, 0)
    if n_reqs and n_solo >= SOLO_SHARE * n_reqs:
        L.append(f"→ {n_solo} lectures enchaînées une par une ({100 * n_solo / n_reqs:.0f} % des requêtes, {_m(ctx_solo)} "
                 "tok de contexte relus pour elles) : grouper plages et fichiers, appels indépendants dans un même message "
                 "(rappelé tout seul après chaque compaction)")
    rows = [r for r in eco.unused_plugins(cpt=cpt) if r[1] > 0]  # poids nul : agit par hooks ou MCP, rien à gagner ici
    if rows:
        L.append(f"→ {len(rows)} plugin(s) actif(s) jamais utilisé(s) en {eco.UNUSED_DAYS} j "
                 f"(≈ {_k(sum(t for _, t in rows))} tok de descriptions par session) : `brain eco`")
    synced = eco.unused_synced(cpt=cpt)
    if synced:
        L.append(f"→ {len(synced)} plugin(s) du compte claude.ai jamais utilisé(s) en {eco.UNUSED_DAYS} j "
                 f"({', '.join(n for n, _, _ in synced[:6])}) : à retirer dans l'app, `brain eco` pour le détail")
    return L


# ------------------------------------------------------------------------------------------ poids réel
WEIGHTS = {"in": 1.0, "w5": 1.25, "w1h": 2.0, "read": 0.1, "out": 5.0}  # prix relatifs de l'API : la mesure du quota
TTL_SIM = {"5m": (300, 1.25), "1h": (3600, 2.0)}  # cache de prompt : durée (s), prix d'une écriture
BIG_WRITE = 20_000  # écriture de cache assez grosse pour en chercher la cause
PAUSES = (("< 1 min", 60), ("1-5 min", 300), ("5-60 min", 3600), ("> 1 h", math.inf))
CAUSES = ("début", "compaction", "pause > 1 h", "pause > 5 min", "invalidation")


def _epoch(value) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _num(d, key) -> int:
    try:
        return int(d.get(key) or 0)
    except (AttributeError, TypeError, ValueError):
        return 0


def _events(path, seen, sub) -> tuple:
    """Un transcript → (événements dans l'ordre, titre). ("R", requête {t, in, w5, w1h, read, out, main}) ou ("C", heure,
    contexte avant, après) pour une compaction. Une requête écrite sur plusieurs lignes, ou recopiée dans un autre
    transcript (`seen`), ne compte qu'une fois, avec sa sortie la plus grande."""
    ev, mine, title, ai = [], {}, None, None
    with open(path, "rb") as fh:
        for raw in fh:
            if b'"usage"' in raw and b'"assistant"' in raw:
                try:
                    o = json.loads(raw)
                except ValueError:
                    continue
                m = o.get("message") if isinstance(o, dict) and o.get("type") == "assistant" else None
                u = m.get("usage") if isinstance(m, dict) else None
                if not isinstance(u, dict):
                    continue
                key = o.get("requestId") or m.get("id")
                if key in mine:
                    mine[key]["out"] = max(mine[key]["out"], _num(u, "output_tokens"))
                    continue
                if key in seen:
                    continue
                w = _num(u, "cache_creation_input_tokens")
                w1h = min(w, _num(u.get("cache_creation"), "ephemeral_1h_input_tokens"))
                r = {"t": _epoch(o.get("timestamp")), "in": _num(u, "input_tokens"), "w5": w - w1h, "w1h": w1h,
                     "read": _num(u, "cache_read_input_tokens"), "out": _num(u, "output_tokens"),
                     "main": not sub and not o.get("isSidechain")}
                if key:
                    mine[key] = r
                ev.append(("R", r))
            elif b'"compact_boundary"' in raw:
                try:
                    o = json.loads(raw)
                except ValueError:
                    continue
                md = o.get("compactMetadata") if isinstance(o, dict) and o.get("subtype") == "compact_boundary" else None
                if isinstance(md, dict) and not o.get("isSidechain"):
                    ev.append(("C", _epoch(o.get("timestamp")), _num(md, "preTokens"), _num(md, "postTokens")))
            elif b'"customTitle"' in raw or b'"aiTitle"' in raw:
                try:
                    o = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(o, dict):
                    title, ai = o.get("customTitle") or title, o.get("aiTitle") or ai
    seen.update(mine)
    return ev, title or ai


def weigh(hours=168.0) -> dict:
    """Poids réel des tokens sur `hours` heures, aux prix relatifs de l'API (entrée 1, écriture de cache 1,25 à 5 min ou
    2 à 1 h, lecture 0,1, sortie 5) → {total, reqs, parts, hidden (coût caché des compactions : relecture 0,1 × avant +
    résumé 5 × après), compactions, main, sub, causes des écritures > BIG_WRITE, gaps (pauses entre deux requêtes de la
    conversation principale), ttl {"5m", "1h" : coût du contexte simulé avec ce cache sur ces pauses, reqs, regime : le
    cache en service}, fenetre (compaction la moins chère B + √(20·K·g) : B contexte après une compaction, g croissance par
    requête sur les segments qui finissent en compaction, K coût d'une compaction ; ou None), fenetre_calc (B, g, K),
    sessions (les 3 plus lourdes)}."""
    root = CLAUDE_HOME / "projects"
    cut = time.time() - hours * 3600
    files = []
    for f in root.rglob("*.jsonl") if root.is_dir() else ():
        try:
            if f.stat().st_mtime >= cut:
                files.append(f)
        except OSError:
            continue
    seen, sessions = set(), {}
    parts = dict.fromkeys(WEIGHTS, 0.0)
    causes = {c: [0, 0.0] for c in CAUSES}
    gaps = {label: 0 for label, _ in PAUSES}
    sim = dict.fromkeys(TTL_SIM, 0.0)
    acc = {"reqs": 0, "main": 0.0, "sub": 0.0, "hidden": 0.0, "compactions": 0, "sim": 0, "w5": 0, "w1h": 0}
    after, kcost, slopes = [], [], []  # après une compaction : contexte, coût ; (croissance, requêtes) par segment
    for f in sorted(files):
        sub = "subagents" in f.parts
        sid = f.parent.parent.name if sub else f.stem
        try:
            ev, title = _events(f, seen, sub)
        except OSError:
            continue
        s = sessions.setdefault(sid, [0.0, None, 0, 0, 0.0])  # poids, titre, requêtes, compactions, dernière requête
        s[1] = s[1] or (None if sub else title)
        prev, pending, seg = None, None, None  # requête principale précédente (heure, contexte en cache, contexte) ;
        for e in ev:  # compaction en attente ; segment en cours [contexte au début, requêtes depuis]
            if e[0] == "C":
                pending = 0.1 * e[2] + 5 * e[3]  # le résumé : relecture de la conversation + sortie du résumé
                if not e[1] or e[1] >= cut:
                    acc["hidden"] += pending
                    acc["compactions"] += 1
                    s[0] += pending
                    s[3] += 1
                    if seg and seg[1] and e[2] > seg[0]:  # pente réelle d'un segment qui finit en compaction
                        slopes.append((e[2] - seg[0], seg[1]))
                seg = None
                continue
            r = e[1]
            on = not r["t"] or r["t"] >= cut
            cost = sum(r[k] * WEIGHTS[k] for k in WEIGHTS)
            if on:
                acc["reqs"] += 1
                for k in WEIGHTS:
                    parts[k] += r[k] * WEIGHTS[k]
                s[0] += cost
                s[2] += 1
                s[4] = max(s[4], r["t"])
                acc["main" if r["main"] else "sub"] += cost
            if not r["main"]:
                continue
            w = r["w5"] + r["w1h"]
            cached = r["read"] + w
            ctx = cached + r["in"]
            gap = r["t"] - prev[0] if prev and r["t"] and prev[0] else 0.0
            wcost = r["w5"] * WEIGHTS["w5"] + r["w1h"] * WEIGHTS["w1h"]
            if seg is None:
                seg = [ctx, 0]
            else:
                seg[1] += 1
            if on:
                acc["w5"] += r["w5"]
                acc["w1h"] += r["w1h"]
                if pending is not None:
                    after.append(ctx)
                    kcost.append(pending + wcost)
                if prev:
                    gaps[next(label for label, lim in PAUSES if gap < lim)] += 1
                if w >= BIG_WRITE:
                    c = ("début" if prev is None else "compaction" if pending is not None else "pause > 1 h"
                         if gap > 3600 else "pause > 5 min" if gap > 300 else "invalidation")
                    causes[c][0] += 1
                    causes[c][1] += wcost
                acc["sim"] += 1
                if prev is None or pending is not None:  # tout est écrit, quel que soit le cache
                    for k, (_, wt) in TTL_SIM.items():
                        sim[k] += r["in"] + 0.1 * r["read"] + wt * w
                else:
                    rr = r["read"]
                    if rr < 0.5 * prev[1] and gap > 300:  # cache expiré pour de vrai : ce qu'un cache plus long aurait lu
                        rr = min(prev[1], cached)
                    for k, (lim, wt) in TTL_SIM.items():
                        sim[k] += r["in"] + (0.1 * rr + wt * (cached - rr) if gap <= lim else wt * cached)
            prev, pending = (r["t"] or (prev[0] if prev else 0.0), cached, ctx), None
    fen, calc = None, None
    n = sum(x[1] for x in slopes)
    if len(after) >= 5 and n:  # par requête : 0,1 × contexte moyen (B + W) / 2 + K × g / (W − B) → minimum en
        b, g, k = statistics.median(after), sum(x[0] for x in slopes) / n, statistics.mean(kcost)  # B + √(20·K·g)
        fen = int(round(min(1_000_000, max(100_000, b + math.sqrt(20 * k * g))), -4))
        calc = {"base": round(b), "croissance": round(g), "cout": round(k), "segments": len(slopes)}
    regime = ("1h" if acc["w1h"] > acc["w5"] else "5m") if acc["w1h"] + acc["w5"] else None
    top = sorted(((v[0], v[1] or sid[:8]) for sid, v in sessions.items() if v[0] > 0), reverse=True)[:3]
    detail = [{"id": sid, "titre": v[1] or sid[:8], "poids": v[0], "requetes": v[2], "compactions": v[3],
               "derniere": v[4]} for sid, v in sorted(sessions.items(), key=lambda x: -x[1][0]) if v[0] > 0][:10]
    return {"hours": hours, "files": len(files), "reqs": acc["reqs"], "total": sum(parts.values()) + acc["hidden"],
            "parts": parts, "hidden": acc["hidden"], "compactions": acc["compactions"], "main": acc["main"],
            "sub": acc["sub"], "causes": causes, "gaps": gaps, "ttl": {**sim, "reqs": acc["sim"], "regime": regime},
            "fenetre": fen, "fenetre_calc": calc, "sessions": top, "detail": detail}


# Garde de consommation : une session qui mange la journée (souvent une session autonome qui tourne et se résume en
# boucle) est signalée au démarrage des autres sessions et sur la page Cerveau d'Obsidian. Calcul en arrière-plan.
GUARD_HOURS = 24
GUARD_SHARE, GUARD_MIN = 0.4, 20_000_000  # alerte : plus de 40 % du poids des 24 h ET plus de 20 M (prix relatifs)…
GUARD_ACTIVE = 2 * 3600  # … pour une session qui a encore tourné dans les 2 dernières heures
GUARD_EVERY = 2  # heures entre deux calculs


def guard(hours=GUARD_HOURS, now=None) -> dict:
    """Les sessions les plus lourdes des `hours` dernières heures → {le, heures, total, sessions [3 plus lourdes : id,
    titre, poids, part, requetes, compactions, derniere], alertes [ids]}, gardé dans la configuration (« garde »)."""
    from .common import now_iso, set_config
    b, now = weigh(hours), now or time.time()
    total = b["total"]
    rows = [{**r, "part": r["poids"] / total if total else 0.0} for r in b["detail"][:3]]
    alerts = [r["id"] for r in rows if r["poids"] >= GUARD_MIN and r["part"] >= GUARD_SHARE
              and 0 <= now - r["derniere"] <= GUARD_ACTIVE]
    out = {"le": now_iso(), "heures": hours, "total": total, "sessions": rows, "alertes": alerts}
    set_config("garde", out)
    return out


def _guard_row(r) -> str:
    return (f"« {str(r.get('titre'))[:60]} » {round(100 * (r.get('part') or 0))} % des tokens "
            f"(≈ {_m(r.get('poids') or 0)}, {r.get('requetes', 0)} requêtes, {r.get('compactions', 0)} résumés)")


def guard_notice(cfg=None, session_id=None) -> str:
    """La ligne d'alerte du démarrage (session lourde encore active, sauf celle qui démarre), ou ''."""
    g = (cfg or load_config()).get("garde")
    if not isinstance(g, dict) or not g.get("alertes"):
        return ""
    rows = [r for r in g.get("sessions") or () if isinstance(r, dict) and r.get("id") in g["alertes"]
            and r.get("id") != session_id]
    if not rows:
        return ""
    return ("🔥 Consommation : " + " · ".join(_guard_row(r) for r in rows) + f" sur les {g.get('heures', GUARD_HOURS):g} "
            "dernières heures, et elle tourne encore. → Le dire à l'utilisateur ; sur son accord : l'arrêter ou baisser "
            "son effort (outils de l'app stop_session, set_session_effort).")


def guard_lines(cfg=None) -> list:
    """Section « Consommation » de la page Cerveau d'Obsidian (dernier calcul de la garde), ou []."""
    g = (cfg or load_config()).get("garde")
    if not isinstance(g, dict) or not g.get("sessions"):
        return []
    out = [f"Sessions les plus lourdes des {g.get('heures', GUARD_HOURS):g} dernières heures (calcul du "
           f"{str(g.get('le'))[8:10]}/{str(g.get('le'))[5:7]} à {str(g.get('le'))[11:16]}) :", ""]
    out += [f"- {'🔥 ' if r.get('id') in (g.get('alertes') or ()) else ''}{_guard_row(r)}"
            for r in g["sessions"] if isinstance(r, dict)]
    if g.get("alertes"):
        out += ["", "_🔥 = session encore active qui mange la journée : l'arrêter ou baisser son effort dans l'app._"]
    return out


def _pc(x, total) -> str:
    return f"{100 * x / total:.1f} %".replace(".", ",") if total else "0 %"


def _weigh_lines(b) -> list:
    """Les lignes « poids réel » du rapport, avec les leviers qui s'y rattachent."""
    total, p = b["total"], b["parts"]
    if not total:
        return []
    from . import eco
    L = [f"Poids réel (prix relatifs de l'API : entrée 1 · écriture du cache 1,25 à 5 min, 2 à 1 h · lecture 0,1 · "
         f"sortie 5) : {_m(total)} sur {b['reqs']} requête(s)",
         f"  - lecture du cache {_pc(p['read'], total)} · écriture 1 h {_pc(p['w1h'], total)} · écriture 5 min "
         f"{_pc(p['w5'], total)} · sortie {_pc(p['out'], total)} · entrée {_pc(p['in'], total)} · résumés de "
         f"compaction (cachés) {_pc(b['hidden'], total)} ({b['compactions']}) · sous-agents {_pc(b['sub'], total)}"]
    big = [(c, n, w) for c, (n, w) in b["causes"].items() if n]
    if big:
        L.append(f"  - grosses écritures du cache (> {BIG_WRITE // 1000} k) : "
                 + " · ".join(f"{c} {n} ({_pc(w, total)})" for c, n, w in big))
    if any(b["gaps"].values()):
        L.append("  - pauses entre deux requêtes : " + " · ".join(f"{k} {v}" for k, v in b["gaps"].items()))
    t = b["ttl"]
    if t.get("reqs") and t.get("regime") in TTL_SIM:
        cur, best = t["regime"], min(TTL_SIM, key=lambda c: (t[c], c != t["regime"]))
        gain = (t[cur] - t[best]) / total
        other = next(c for c in TTL_SIM if c != cur)
        if best == cur:
            L.append(f"  - cache simulé sur ces pauses : {eco._ttl(cur)} (en service) reste le meilleur ; "
                     f"{eco._ttl(other)} coûterait {_pc(t[other] - t[cur], total)} de plus")
        else:
            L.append(f"  - cache simulé sur ces pauses : {eco._ttl(best)} ferait gagner {_pc(gain * total, total)} "
                     f"(en service : {eco._ttl(cur)}) → `brain eco --cache auto` le pose tout seul au-delà de "
                     f"{eco.CACHE_GAIN_NEW * 100:.0f} %")
    if b["sessions"]:
        L.append("  - sessions les plus lourdes : " + " · ".join(f"« {str(title)[:40]} » {_pc(w, total)}"
                                                                 for w, title in b["sessions"]))
    try:
        win = eco.targets()[1]
    except ValueError:
        win = eco.DEFAULT_WIN
    cur_win = eco.current().get(eco.WIN_KEY)
    cur_win = cur_win if isinstance(cur_win, int) and not isinstance(cur_win, bool) else win
    if b.get("fenetre") and abs(b["fenetre"] - cur_win) >= 20_000:
        L.append(f"→ fenêtre de compaction la moins chère d'après tes sessions ≈ {b['fenetre'] // 1000} k (en service "
                 f"{cur_win // 1000} k) : `brain eco --fenetre {b['fenetre']}` (plus bas = résumés plus fréquents)")
    try:
        props = eco.proposals()
    except Exception as exc:  # jamais bloquer le rapport sur un conseil
        log(f"tokens.propositions : {exc!r}")
        props = []
    if props:
        gain = sum(x[2] for x in props if x[2])
        L.append(f"→ {len(props)} réglage(s) sur accord ({', '.join(x[0] for x in props)}"
                 + (f", ≈ {_k(gain)} tok de moins par requête" if gain else "")
                 + ") : `brain eco` pour le détail, `brain eco --poser ID` après accord")
    return L


def report(hours=48.0) -> str:
    d = measure(hours)
    reqs = d["reqs"]
    if not reqs:
        return f"Aucune requête dans les transcripts des {hours:g} dernières heures."
    total = sum(reqs)
    big = [r for r in reqs if r > 300_000]
    ratios = d["ratios"]
    cpt = statistics.median(ratios) if len(ratios) >= 20 else CHARS_PER_TOKEN
    cal = (f"calibrage mesuré {cpt:.2f} car./token ({len(ratios)} paires)" if len(ratios) >= 20
           else f"calibrage {CHARS_PER_TOKEN} car./token")
    lines = [f"🧮 Tokens — {hours:g} h · {d['files']} transcripts (dont {d['subfiles']} de sous-agents) · {cal}",
             f"Requêtes : {len(reqs)} · contexte relu {_m(total)} · moyenne {_m(total / len(reqs))} · "
             f"> 300 k : {100 * len(big) / len(reqs):.0f} % des requêtes, {100 * sum(big) / total:.0f} % des tokens"]
    fm, fs = d["first_main"], d["first_sub"]
    if fm:
        lines.append(f"1re requête : sessions méd. {_m(statistics.median(fm))}"
                     + (f" · sous-agents méd. {_m(statistics.median(fs))} ({len(fs)})" if fs else ""))
    lines += _fixed_lines(d, cpt)
    lines.append(f"Relances du cerveau : {d['relances']} rappel(s) de fin de tâche → {d['relance_reqs']} requête(s) en plus"
                 + (f" (contexte relu {_m(d['relance_ctx'])})" if d["relance_reqs"] else ""))
    lines.append("Habitudes coûteuses (porté = taille × requêtes qui la relisent jusqu'à la compaction) :")
    found = [(key, label, tip) for key, label, tip in HABITS if d["habits"].get(key)]
    for key, label, tip in found:
        n, carried = d["habits"][key]
        lines.append(f"  - {label} : {n} · porté {_m(carried)} ({100 * carried / total:.0f} %) → {tip}")
    if not found:
        lines.append("  - aucune au-dessus des seuils")
    try:
        lines += _advice(d, cpt)
    except Exception as exc:  # jamais bloquer le rapport sur un conseil
        log(f"tokens.conseils : {exc!r}")
    try:
        lines += _weigh_lines(weigh(hours))
    except Exception as exc:
        log(f"tokens.poids : {exc!r}")
    return "\n".join(lines)
