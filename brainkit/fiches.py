"""Fiches de synthèse par communauté — les « community summaries » de Zep / Graphiti et les résumés de MemOS, sans LLM.

Chaque communauté du graphe (Louvain, graph.py) d'au moins trois souvenirs a une fiche courte et extractive : les phrases
les plus centrales de ses membres (TextRank sur les phrases, amorcé par la centralité, l'importance et la fraîcheur de
chaque souvenir ; une phrase par souvenir au plus, sans redite), puis ses à-faire ouverts. Chaque ligne garde l'id de son
souvenir (`show <id>` pour le détail) : rien n'est inventé, tout se vérifie.

Cache state/fiches.json, clé = contenu des membres : une fiche n'est recalculée que si l'un d'eux change.
Une question large (« où en est la boutique ? ») reçoit la fiche de la communauté dominante avant les souvenirs épars
(search._fuse : commande `q` et serveur MCP)."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter

from .common import STATE_DIR, days_since, read_json, short, tokenize, write_json

FICHES_FILE = STATE_DIR / "fiches.json"
VERSION = 1
MIN_SIZE = 3
MAX_CHARS = 760
TYPE_W = {"project": 1.2, "decision": 1.15, "fact": 1.1, "learning": 1.05, "entity": 0.9, "reference": 0.8,
          "feedback": 0.5}
SKIP_TYPES = ("todo", "user")  # à-faire : ligne à part ; profil : déjà dans l'index, ne dit pas où en est un sujet
_WIKI = re.compile(r"\[\[([^\]|#\n]+)(?:[|#][^\]\n]*)?\]\]")
_LINK = re.compile(r"\[([^\]\n]+)\]\([^)\s]+\)")
_MD = re.compile(r"\*\*|__|`|^\s*#+\s*|^\s*>\s*", re.M)
_SPLIT = re.compile(r"\n+|(?<=[.!?…])\s+(?=[A-ZÀ-ÝÉ«\"(0-9])|\s+[-•·]\s+(?=[A-ZÀ-ÝÉ«0-9])")
_WHY = re.compile(r"^(pourquoi|car|sinon|why|because|ex\b|exemple)\b", re.I)  # une raison seule ne dit pas où on en est
_REF = re.compile(r"^(note|livrable|voir|lire aussi|fichier|chemin|source|sauvegarde|cf\b|dossier|lien)\b", re.I)
# chemins, fichiers, adresses, ids de souvenirs : partagés par beaucoup de souvenirs, ils ne disent rien du sujet
_NOISE = re.compile(r"https?://\S+|(?:[A-Za-z]:)?[\w~.$-]*[/\\][\w~./\\$-]+|\b[\w-]+\.(?:md|py|json|html|js|ts|csv|xlsx|"
                    r"docx|pdf|ps1|txt|liquid|zip|bat|ya?ml)\b|\b[a-z0-9]+(?:-[a-z0-9]+){3,}\b")


# ------------------------------------------------------------------------------------------ phrases
def sentences(text) -> list:
    """Contenu d'un souvenir → phrases utiles (balisage Markdown, liens [[ ]] et listes retirés)."""
    text = _MD.sub("", _LINK.sub(r"\1", _WIKI.sub(r"\1", str(text or ""))))
    out = []
    for raw in _SPLIT.split(text):
        s = " ".join(raw.strip(" -•·*\t").split())
        if len(s) >= 25 and len(tokenize(s)) >= 3:
            out.append(s)
    return out


def _terms(text) -> list:
    """Mots porteurs de sens pour la similarité : sans chemins, fichiers, ids ni nombres (les dates relient tout)."""
    return [t for t in tokenize(_NOISE.sub(" ", text)) if not any(c.isdigit() for c in t)]


def _noise_share(s) -> float:
    return sum(len(m.group(0)) for m in _NOISE.finditer(s)) / max(1, len(s))


def _vecs(texts):
    tfs = [Counter(_terms(t)) for t in texts]
    df = Counter(t for tf in tfs for t in tf)
    n = len(tfs) or 1
    out = []
    for tf in tfs:
        v = {t: (1 + math.log(f)) * math.log(1 + n / df[t]) for t, f in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        out.append({t: x / norm for t, x in v.items()})
    return out


def _cos(a, b) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def textrank(vecs, prior, groups, d=0.85, iters=50, min_sim=0.05) -> list:
    """TextRank personnalisé : une phrase est centrale si les AUTRES souvenirs de la communauté parlent comme elle
    (pas de lien entre deux phrases d'un même souvenir) ; la téléportation suit le poids de son souvenir."""
    n = len(vecs)
    w = [{} for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if groups[i] != groups[j]:
                s = _cos(vecs[i], vecs[j])
                if s >= min_sim:
                    w[i][j] = w[j][i] = s
    tot = sum(prior) or 1.0
    p = [x / tot for x in prior]
    out = [sum(x.values()) for x in w]
    r = list(p)
    for _ in range(iters):
        dangling = sum(r[i] for i in range(n) if not out[i])
        new = [(1 - d + d * dangling) * p[i] for i in range(n)]
        for i in range(n):
            if out[i]:
                share = d * r[i] / out[i]
                for j, x in w[i].items():
                    new[j] += share * x
        r = new
    return r


# ------------------------------------------------------------------------------------------ fiche
def _member_weight(n, pr) -> float:
    w = 0.35 + pr.get(n["id"], 0.0)  # centralité dans le graphe (PageRank normalisé : 1 = le plus central)
    w *= 1 + 0.15 * (n.get("importance", 3) - 3)
    age = days_since(n.get("updated"))
    w *= 1.15 if age < 14 else 1.0 if age < 60 else 0.9
    return w * TYPE_W.get(n["type"], 1.0)


def _line(n, s, is_title=False) -> str:
    """Phrase retenue, précédée du titre de son souvenir quand elle ne le redit pas déjà."""
    tt, st = set(tokenize(n["title"])), set(tokenize(s))
    if is_title or n["type"] == "project" or not tt or len(tt & st) / len(tt) >= 0.6:
        return short(s, 190)
    title = re.split(r"\s[(—–]", n["title"])[0].strip() or n["title"]
    return short(f"{short(title, 60)} — {s}", 190)


def _key(nodes) -> str:
    """Empreinte du contenu des membres (pas des compteurs de rappel) : la fiche ne change que si l'un d'eux change."""
    h = hashlib.sha1(f"fiche{VERSION}".encode())
    for n in sorted(nodes, key=lambda x: x["id"]):
        h.update(json.dumps([n["id"], n["type"], n["title"], n.get("body", ""), n.get("importance", 3), n.get("project"),
                             (n.get("meta") or {}).get("due")], ensure_ascii=False).encode("utf-8"))
    return h.hexdigest()[:16]


def build(nodes, pr) -> dict:
    """Fiche extractive d'un groupe de souvenirs → {lines: [{t, id}], todo: [{t, id, due}], members}."""
    from .dates import due_of
    todos = [n for n in nodes if n["type"] == "todo"]
    pool = []  # (souvenir, phrase, rang dans le souvenir ; -1 = son titre)
    for n in nodes:
        if n["type"] in SKIP_TYPES:
            continue
        if n["type"] != "project" and len(_terms(n["title"])) >= 3:
            pool.append((n, n["title"], -1))  # titre d'un bon souvenir = le fait en une ligne
        sents = sentences(n.get("body", ""))
        pool += [(n, s, k) for k, s in enumerate(sents[:2 if n["type"] == "project" else 8])]  # projet : sa présentation
    pool = [(n, s, k) for n, s, k in pool if _terms(s)]
    lines = []
    if pool:
        vecs = _vecs([s for _, s, _ in pool])
        per = Counter(n["id"] for n, _, _ in pool)
        mw = {n["id"]: _member_weight(n, pr) for n in nodes}
        prior = []
        for n, s, k in pool:
            x = mw[n["id"]] / math.sqrt(per[n["id"]])
            x *= 1.3 if k <= 0 else 1.0  # titre et première phrase portent d'ordinaire le fait principal
            x *= 0.6 if _WHY.match(s) else 1.0
            x *= 0.3 if _REF.match(s) or _noise_share(s) >= 0.35 else 1.0  # « Note : dossier/fichier.md » : un renvoi
            prior.append(x)
        rank = textrank(vecs, prior, [n["id"] for n, _, _ in pool])
        size = len(nodes)
        k_max = 3 if size <= 5 else 4 if size <= 9 else 5

        def fit(s):
            return 0.55 if len(s) < 35 else 0.7 if len(s) > 260 else 0.85 if len(s) > 190 else 1.0

        def score(i):
            n, s, k = pool[i]
            return rank[i] * fit(s) * (0.3 if _REF.match(s) or _noise_share(s) >= 0.35 else 1.0)

        picked, used, chars = [], set(), 0
        for i in sorted(range(len(pool)), key=lambda i: (-score(i), i)):
            n, s, k = pool[i]
            if n["id"] in used or any(_cos(vecs[i], vecs[j]) >= 0.5 for j in picked):
                continue
            line = _line(n, s, k < 0)
            if picked and chars + len(line) > MAX_CHARS:
                continue
            picked.append(i)
            used.add(n["id"])
            chars += len(line)
            if len(picked) >= k_max:
                break
        lines = [{"t": _line(pool[i][0], pool[i][1], pool[i][2] < 0), "id": pool[i][0]["id"]} for i in picked]
    todos.sort(key=lambda n: (due_of(n) or "9999", -n.get("importance", 3), n["id"]))
    todo = [{"t": short(n["title"], 80), "id": n["id"], "due": due_of(n)} for n in todos[:3]]
    return {"lines": lines, "todo": todo, "members": sorted(n["id"] for n in nodes)}


def ensure(brain, an=None, write=True) -> dict:
    """Fiches à jour de toutes les communautés d'au moins MIN_SIZE souvenirs → {id de communauté: fiche}.
    write=False (banc d'essai, `q --at`) : rien n'est lu ni écrit sur le disque."""
    from . import graph
    an = an or graph.ensure(brain, write=write)
    cache = (read_json(FICHES_FILE, {}) or {}) if write else {}
    items = cache.get("items", {}) if cache.get("version") == VERSION else {}
    out, keep, changed = {}, {}, False
    for c in an.get("communities", []):
        nodes = [brain.nodes[i] for i in c["members"] if i in brain.nodes]
        if len(nodes) < MIN_SIZE:
            continue
        k = _key(nodes)
        f = items.get(k)
        if f is None:
            f = build(nodes, an.get("pr", {}))
            changed = True
        keep[k] = f
        out[c["id"]] = dict(f, cid=c["id"], label=c["label"], project=c.get("project"), size=len(nodes))
    if write and (changed or set(keep) != set(items)):
        try:
            write_json(FICHES_FILE, {"version": VERSION, "items": keep}, indent=None)
        except Exception:
            pass
    return out


def text(f, others=()) -> str:
    """Fiche → bloc compact (une ligne par phrase retenue, ids gardés)."""
    from .dates import human
    head = f"📋 Fiche « {f['label']} » — {f['size']} souvenirs (extraits les plus centraux, sans LLM) :"
    rows = [head] + [f"- {x['t']} `{x['id']}`" for x in f["lines"]]
    if f.get("todo"):
        rows.append("☑️ À faire : " + " · ".join(f"{x['t']}" + (f" ({human(x['due'])})" if x.get("due") else "")
                                                 + f" `{x['id']}`" for x in f["todo"]))
    if others:
        rows.append("↳ Autres fiches liées : " + " · ".join(f"« {o['label']} » ({o['size']})" for o in others)
                    + " — `fiche <mot>`")
    return "\n".join(rows)


def cited(f) -> set:
    return {x["id"] for x in f.get("lines", [])} | {x["id"] for x in f.get("todo", [])}
