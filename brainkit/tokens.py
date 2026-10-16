"""Où partent les tokens — mesuré sur les transcripts Claude Code des dernières heures (lecture locale, zéro token).
Contexte relu par requête, taille des premières requêtes, et habitudes coûteuses avec ce qu'elles « portent » :
leur taille multipliée par le nombre de requêtes qui la relisent jusqu'à la compaction suivante."""
from __future__ import annotations

import json
import statistics
import time

from .common import CHARS_PER_TOKEN, CLAUDE_HOME

BIG_BASH, BIG_READ, BIG_SEARCH = 1500, 3000, 1500  # tokens
IMAGE_TOKENS = 1600  # ordre de grandeur d'une capture d'écran : une image ne se mesure pas au nombre de caractères
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


def _scan_file(path, cpt, out):
    """Un transcript → requêtes, premières requêtes, habitudes, paires de calibrage."""
    ev, seen, calls, first = [], set(), {}, True
    last_req, between = None, []
    sub = "subagents" in path.parts
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return
    with fh:
        for raw in fh:
            if '"assistant"' not in raw and '"user"' not in raw and "compact_boundary" not in raw:
                continue
            try:
                o = json.loads(raw)
            except ValueError:
                continue
            t = o.get("type")
            if t == "system" and o.get("subtype") == "compact_boundary":
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
                for b in cont if isinstance(cont, list) else []:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        name, inp = calls.get(b.get("tool_use_id"), ("?", {}))
                        chars, imgs = _size(b.get("content"))
                        between.append(chars)
                        tok = chars / cpt + imgs * IMAGE_TOKENS
                        kind = _habit(name, inp if isinstance(inp, dict) else {}, chars / cpt, imgs)
                        if kind:
                            ev.append(("T", kind, tok))
    after = 0
    for e in reversed(ev):  # ce qu'un résultat « porte » : relu par chaque requête suivante jusqu'à la compaction
        if e[0] == "C":
            after = 0
        elif e[0] == "R":
            after += 1
            out["reqs"].append(e[1])
        else:
            h = out["habits"].setdefault(e[1], [0, 0.0])
            h[0] += 1
            h[1] += e[2] * after


def measure(hours=48.0, cpt=None) -> dict:
    root = CLAUDE_HOME / "projects"
    cut = time.time() - hours * 3600
    files = [f for f in root.rglob("*.jsonl") if f.stat().st_mtime >= cut] if root.is_dir() else []
    out = {"hours": hours, "files": len(files), "subfiles": sum("subagents" in f.parts for f in files),
           "reqs": [], "first_main": [], "first_sub": [], "habits": {}, "ratios": []}
    for f in files:
        _scan_file(f, cpt or CHARS_PER_TOKEN, out)
    return out


def _m(x) -> str:
    return f"{x / 1e6:.1f} M" if x >= 1e6 else f"{x / 1e3:.0f} k"


def report(hours=48.0) -> str:
    d = measure(hours)
    reqs = d["reqs"]
    if not reqs:
        return f"Aucune requête dans les transcripts des {hours:g} dernières heures."
    total = sum(reqs)
    big = [r for r in reqs if r > 300_000]
    ratios = d["ratios"]
    cal = (f"calibrage mesuré {statistics.median(ratios):.2f} car./token ({len(ratios)} paires)" if len(ratios) >= 20
           else f"calibrage {CHARS_PER_TOKEN} car./token")
    lines = [f"🧮 Tokens — {hours:g} h · {d['files']} transcripts (dont {d['subfiles']} de sous-agents) · {cal}",
             f"Requêtes : {len(reqs)} · contexte relu {_m(total)} · moyenne {_m(total / len(reqs))} · "
             f"> 300 k : {100 * len(big) / len(reqs):.0f} % des requêtes, {100 * sum(big) / total:.0f} % des tokens"]
    fm, fs = d["first_main"], d["first_sub"]
    if fm:
        lines.append(f"1re requête : sessions méd. {_m(statistics.median(fm))}"
                     + (f" · sous-agents méd. {_m(statistics.median(fs))} ({len(fs)})" if fs else ""))
    lines.append("Habitudes coûteuses (porté = taille × requêtes qui la relisent jusqu'à la compaction) :")
    found = [(key, label, tip) for key, label, tip in HABITS if d["habits"].get(key)]
    for key, label, tip in found:
        n, carried = d["habits"][key]
        lines.append(f"  - {label} : {n} · porté {_m(carried)} ({100 * carried / total:.0f} %) → {tip}")
    if not found:
        lines.append("  - aucune au-dessus des seuils")
    return "\n".join(lines)
