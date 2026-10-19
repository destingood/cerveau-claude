"""Où partent les tokens — mesuré sur les transcripts Claude Code des dernières heures (lecture locale, zéro token).
Contexte relu par requête, taille des premières requêtes, coût fixe au démarrage (skills, MCP, outils différés, hooks),
relances du cerveau, et habitudes coûteuses avec ce qu'elles « portent » : leur taille multipliée par le nombre de
requêtes qui la relisent jusqu'à la compaction suivante. Les leviers renvoient à `brain eco`."""
from __future__ import annotations

import json
import statistics
import time

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
    ev, seen, calls, first = [], set(), {}, True
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
                for b in m.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        calls[b.get("id")] = (b.get("name"), b.get("input") or {})
                u, mid = m.get("usage"), m.get("id")
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
           "fixed": [], "relances": 0, "relance_reqs": 0, "relance_ctx": 0, "eco_bash": [0, 0.0], "eco_out": eco_out}
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
    rows = [r for r in eco.unused_plugins(cpt=cpt) if r[1] > 0]  # poids nul : agit par hooks ou MCP, rien à gagner ici
    if rows:
        L.append(f"→ {len(rows)} plugin(s) actif(s) jamais utilisé(s) en {eco.UNUSED_DAYS} j "
                 f"(≈ {_k(sum(t for _, t in rows))} tok de descriptions par session) : `brain eco`")
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
    return "\n".join(lines)
