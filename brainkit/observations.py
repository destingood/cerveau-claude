"""Observations datées — la recette « Observational Memory » de Mastra, sans LLM en plus : la mémoire épisodique.

En fin de tâche importante (hook Stop) et après une compaction du contexte (PreCompact), Claude note 3 à 5 faits datés
et priorisés de la session (`obs "🔴 …" "🟡 …"`) : 🔴 décision, blocage, préférence · 🟡 avancée, constat · 🟢 détail.
Elles vivent à part du graphe (journal/observations.json) : le bloc injecté au démarrage ne bouge pas, et `q` les
retrouve par le texte comme par la date (« qu'est-ce qu'on a fait hier ? »).

Le rêve (dream.py) les condense chaque jour, comme le « Reflector » de Mastra : passé 7 jours, celles d'une même semaine
et d'un même projet deviennent un résumé (🔴 gardées, doublons fusionnés, 🟢 écartées) ; les originales partent dans
journal/observations-archive.jsonl (rien n'est perdu). Les 🔴 qu'aucun souvenir ne reflète sont proposées dans REVE.md."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import marshal
import os
import re

from .common import (BRAIN_DIR, STATE_DIR, FileLock, fmt_date, fold, jaccard, parse_iso, read_json, short, tokenize,
                     write_json)

OBS_FILE = BRAIN_DIR / "journal" / "observations.json"
ARCHIVE_FILE = BRAIN_DIR / "journal" / "observations-archive.jsonl"
LOCK = OBS_FILE.with_name("observations.lock")
INDEX_FILE = STATE_DIR / "obsidx.bin"  # index du rappel des observations (voir _pool_index)
PRIO = {3: "🔴", 2: "🟡", 1: "🟢"}
KEEP_DAYS = 7  # au-delà, condensées par le rêve en un résumé par semaine et par projet
PER_DIGEST = {3: 6, 2: 4, 1: 1}  # lignes gardées par priorité dans un résumé de semaine
MAX_TEXT, MAX_ITEMS = 220, 8
_PRIO_RX = re.compile(r"^\s*(🔴|🟡|🟢|!!!|!!|!|\[(?:haute|moyenne|basse|high|medium|low)\]|(?:haute|moyenne|basse)\s*:)\s*",
                      re.I)
_TIME_RX = re.compile(r"^\s*([01]?\d|2[0-3])\s*[:h]\s*([0-5]\d)(?!\d)\s*[-–—:]?\s*")


def load() -> dict:
    d = read_json(OBS_FILE, None)
    if not isinstance(d, dict) or not isinstance(d.get("obs"), list):
        d = {"version": 1, "obs": [], "digests": []}
    d.setdefault("digests", [])
    return d


def _day(o) -> _dt.date:
    d = parse_iso(o.get("at"))
    return d.date() if d else _dt.date.today()


def parse_item(raw):
    """« 🔴 14:20 L'utilisateur choisit Mondial Relay » → (3, (14, 20), « L'utilisateur choisit Mondial Relay »)."""
    text = " ".join(str(raw).split())
    prio, hm = 2, None
    for _ in range(2):  # priorité et heure, dans n'importe quel ordre
        m = _PRIO_RX.match(text)
        if m:
            tag = fold(m.group(1)).strip(" :[]")
            prio = 3 if tag in ("🔴", "!!!", "haute", "high") else 1 if tag in ("🟢", "!", "basse", "low") else 2
            text = text[m.end():]
        m = _TIME_RX.match(text)
        if m and hm is None:
            hm = (int(m.group(1)), int(m.group(2)))
            text = text[m.end():]
    return prio, hm, text.strip(" -–—")


def add(items, project=None, now=None):
    """Note des observations (8 au plus par appel) → (ajoutées, ignorées : trop courtes ou déjà notées ces 3 jours)."""
    from .dates import absolutize
    from .privacy import redact_contacts
    now = now or _dt.datetime.now().replace(microsecond=0)
    added, skipped = [], 0
    with FileLock(LOCK, timeout=3):
        d = load()
        recent = [o for o in d["obs"] if o.get("proj") == project and abs((now.date() - _day(o)).days) <= 3]
        for raw in list(items)[:MAX_ITEMS]:
            prio, hm, text = parse_item(raw)
            if len(tokenize(text)) < 2:
                skipped += 1
                continue
            at = now.replace(hour=hm[0], minute=hm[1], second=0) if hm else now
            text = short(redact_contacts(absolutize(text, at.date())), MAX_TEXT)  # « hier » → date réelle ; ni secret ni coordonnées
            toks = set(tokenize(text))
            if any(jaccard(toks, set(tokenize(o["t"]))) >= 0.75 for o in recent + added):
                skipped += 1
                continue
            o = {"id": "o" + hashlib.sha1(f"{at.isoformat()}|{project}|{text}".encode("utf-8")).hexdigest()[:9],
                 "at": at.isoformat(), "p": prio, "t": text, "proj": project}
            d["obs"].append(o)
            added.append(o)
        if added:
            d["obs"].sort(key=lambda o: o["at"])
            write_json(OBS_FILE, d, indent=None)
    return added, skipped


def _items(d=None):
    """Observations brutes + lignes des résumés de semaine, à plat (pour chercher et lister)."""
    d = d or load()
    out = [dict(o, kind="obs") for o in d["obs"]]
    for g in d["digests"]:
        out += [dict(x, proj=g.get("proj"), kind="résumé", week=g["from"]) for x in g.get("lines", [])]
    return out


def line(o) -> str:
    when = fmt_date(o["at"]) + (f" {o['at'][11:16]}" if o.get("kind") == "obs" and len(o.get("at", "")) >= 16 else "")
    tail = (f" · {o['proj']}" if o.get("proj") else "") + (" (résumé de la semaine)" if o.get("kind") == "résumé" else "")
    return f"- {when} {PRIO.get(o.get('p', 2), '🟡')} {o['t']}{tail}"


def search(query, limit=3, project=None, today=None):
    """Observations liées à une question : par les dates qu'elle vise (« hier », « la semaine dernière »), sinon par
    le texte (au moins deux mots en commun quand la question en a deux), les plus importantes d'abord."""
    from . import dates
    from .search import DATED_RX, Index
    items = _items()
    if not items:
        return []
    rng = dates.query_range(query, today)
    pool = [o for o in items if rng[0] <= _day(o) <= rng[1]] if rng else items
    if not pool:
        return []
    text = query
    if rng:  # « les photos de la semaine dernière » → « photos »
        text = " ".join(t for t in tokenize(DATED_RX.sub(" ", query)) if t not in _WHEN and not t.isdigit())
        if not text:
            return sorted(pool, key=lambda o: (-o.get("p", 2), o["at"]))[:limit]  # seulement datée : « on a fait quoi hier ? »
    idx = Index((i, [(o["t"], 1.0)]) for i, o in enumerate(pool))
    scored = [(h["score"] * (1 + 0.2 * (pool[h["key"]].get("p", 2) - 2))
               * (1.2 if project and pool[h["key"]].get("proj") == project else 1.0), pool[h["key"]])
              for h in idx.search(text, 30) if h["matched"] >= min(2, h["nq"])]
    return [o for _, o in sorted(scored, key=lambda x: (-x[0], x[1]["at"]))][:limit]


_WHEN = {"dernier", "derniere", "prochain", "prochaine", "passe", "passee", "debut", "fin", "cours"}


def key(o) -> str:
    """Identifiant d'une observation, ligne de résumé comprise (qui n'en a pas) : pour ne pas la montrer deux fois."""
    return o.get("id") or "r" + hashlib.sha1(f"{o.get('at')}|{o.get('t')}".encode("utf-8")).hexdigest()[:9]


def recall(query, raw="", project=None, limit=1, exclude=(), min_cov=0.5, today=None):
    """Rappel à chaque message, quand aucun souvenir ne répond : les observations notées en fin de tâche que le message
    vise, avec la règle ordinaire du rappel des souvenirs (assez de mots du message, une bonne part de leur poids ;
    search.recall_refusal), les 🔴 d'abord, celles du projet courant devant. Question datée (`raw`, le message avec ses
    nombres : « hier », « la semaine dernière ») : celles de la période ; sans autre mot que la date, les plus importantes
    de la période. Avant, seul `q` les retrouvait. → [observation]"""
    from . import dates
    from .search import recall_refusal, undated
    every = _items()
    items = [o for o in every if key(o) not in exclude]
    rng = dates.query_range(raw or query, today)
    pool = [o for o in items if rng[0] <= _day(o) <= rng[1]] if rng else items
    if not pool:
        return []
    text = undated(query) if rng else query
    if not tokenize(text):
        return sorted(pool, key=lambda o: (-o.get("p", 2), o["at"]))[:limit] if rng else []
    idx, keep = _pool_index(pool, every)
    scored = [(h["score"] * (1 + 0.2 * (pool[h["key"]].get("p", 2) - 2))
               * (1.2 if project and pool[h["key"]].get("proj") == project else 1.0), pool[h["key"]])
              for h in idx.search(text, 30) if not recall_refusal(h, min_cov)]
    keep(idx)
    return [o for _, o in sorted(scored, key=lambda x: (-x[0], x[1]["at"]))][:limit]


def _pool_index(pool, every=()):
    """Index BM25 (search.Index) des observations `pool`, dans cet ordre, le même qu'avant (positions pour clés, chaque
    texte de poids 1) : gardé dans state/obsidx.bin tant que leurs textes sont les mêmes, avec ses tables de fautes et de
    prononciation une fois construites (avant : tout redécoupé à chaque message sans souvenir, 43 ms à 2 000
    observations). Les mots de chaque texte (`every` : toutes les observations) y restent pour une autre liste (une
    observation ajoutée, une autre déjà montrée dans la session) : seuls les nouveaux textes sont découpés.
    → (index, keep(index) : réécrit le fichier si quelque chose a changé)."""
    from collections import Counter
    from .lexicon import faux_amis
    from .search import MEMIDX_TAG, Index
    texts = [o["t"] for o in pool]
    sig = hashlib.sha1("".join(f"{len(t)}:{t}" for t in texts).encode("utf-8", "surrogatepass")).hexdigest()
    tag = f"o1-{MEMIDX_TAG}"  # (le découpage des mots change avec l'index des souvenirs)
    try:
        with open(INDEX_FILE, "rb") as fh:
            blob = marshal.loads(fh.read())
        blob = blob if isinstance(blob, dict) and blob.get("tag") == tag else {}
    except Exception:
        blob = {}
    docs = blob.get("docs") or b""  # {texte: (mots, faux amis)}, lu seulement si la liste a changé
    fuzzy = blob.get("fuzzy") if blob.get("sig") == sig else None
    if blob.get("sig") == sig:
        idx = Index.from_state(blob["index"])
        if fuzzy:
            idx._phon, idx._del, idx._root = fuzzy
    else:
        try:
            got_docs = marshal.loads(docs) if docs else {}
        except Exception:
            got_docs = {}
        tfs, named = [], {}
        for i, text in enumerate(texts):
            got = got_docs.get(text)
            if got is None:  # comme search.Index(…) : chaque mot du texte, poids 1
                tf, nm = Counter(), Counter()
                if text:
                    for tok in tokenize(text):
                        tf[tok] += 1.0
                    for tok in faux_amis(text):
                        nm[tok] += 1.0
                got = got_docs[text] = (dict(tf), dict(nm))
            tfs.append(got[0])
            if got[1]:
                named[i] = got[1]
        idx = Index.from_tfs(range(len(texts)), tfs)
        idx.named = named
        alive = {o["t"] for o in every} | set(texts)
        docs = None  # à réécrire
        kept_docs = {t: v for t, v in got_docs.items() if t in alive}

    def keep(idx):
        built = getattr(idx, "_phon", None) is not None and not fuzzy  # tables de fautes construites par cette recherche
        if docs is not None and not built:
            return
        try:
            out = {"tag": tag, "sig": sig, "docs": docs if docs is not None else marshal.dumps(kept_docs),
                   "index": {"keys": idx.keys, "tfs": idx.tfs, "lens": idx.lens, "df": dict(idx.df),
                             "post": dict(idx.post), "pre": dict(idx.by_prefix), "named": idx.named},
                   "fuzzy": (idx._phon, idx._del, idx._root) if getattr(idx, "_phon", None) is not None else None}
            INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = INDEX_FILE.with_name(f"obsidx.{os.getpid()}.tmp")
            with open(tmp, "wb") as fh:
                fh.write(marshal.dumps(out))
            os.replace(tmp, INDEX_FILE)
        except Exception:
            pass
    return idx, keep


def recent(n=15, project=None, days=None):
    items = [o for o in _items() if project is None or o.get("proj") == project]
    if days is not None:
        cut = _dt.date.today() - _dt.timedelta(days=days)
        items = [o for o in items if _day(o) >= cut]
    return sorted(items, key=lambda o: o["at"], reverse=True)[:n]


# ------------------------------------------------------------------------------------------ rêve : condensation
def condense(today=None, keep_days=KEEP_DAYS):
    """Le « Reflector » : passé keep_days, une semaine d'observations d'un même projet → un résumé (🔴 d'abord, doublons
    fusionnés, 🟢 écartées). Les originales sont d'abord copiées dans l'archive. → (observations condensées, résumés)."""
    today = today or _dt.date.today()
    with FileLock(LOCK, timeout=3):
        d = load()
        old = [o for o in d["obs"] if (today - _day(o)).days > keep_days]
        if not old:
            return 0, 0
        groups = {}
        for o in old:
            y, w, _ = _day(o).isocalendar()
            groups.setdefault((o.get("proj"), y, w), []).append(o)
        for (proj, y, w), obs in groups.items():
            monday = _dt.date.fromisocalendar(y, w, 1)
            dg = next((g for g in d["digests"] if g.get("proj") == proj and g["from"] == monday.isoformat()), None)
            pool = (dg["lines"] if dg else []) + [{"p": o["p"], "t": o["t"], "at": o["at"]} for o in obs]
            pool.sort(key=lambda x: (-x["p"], x["at"]))
            kept = []
            for x in pool:  # doublon : la version la plus prioritaire (puis la plus ancienne) reste
                toks = set(tokenize(x["t"]))
                if not any(jaccard(toks, set(tokenize(k["t"]))) >= 0.5 for k in kept):
                    kept.append(x)
            lines = [x for p in (3, 2, 1) for x in [k for k in kept if k["p"] == p][:PER_DIGEST[p]]]
            entry = {"from": monday.isoformat(), "to": (monday + _dt.timedelta(days=6)).isoformat(), "proj": proj,
                     "lines": sorted(lines, key=lambda x: x["at"]), "n": (dg.get("n", 0) if dg else 0) + len(obs)}
            if dg:
                dg.update(entry)
            else:
                d["digests"].append(entry)
        ARCHIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ARCHIVE_FILE, "a", encoding="utf-8", newline="\n") as fh:  # archive d'abord : jamais de perte
            for o in old:
                fh.write(json.dumps(o, ensure_ascii=False) + "\n")
        gone = {o["id"] for o in old}
        d["obs"] = [o for o in d["obs"] if o["id"] not in gone]
        d["digests"].sort(key=lambda g: (g["from"], g.get("proj") or ""))
        write_json(OBS_FILE, d, indent=None)
    return len(old), len(groups)


def unsaved(brain, since=None, limit=6):
    """🔴 notées depuis le dernier rêve qu'aucun souvenir du graphe ne reflète encore : à mémoriser (ou pas) en durable."""
    out = []
    for o in sorted((x for x in _items() if x.get("p") == 3), key=lambda x: x["at"]):
        if since and (parse_iso(o["at"]) or since) < since:
            continue
        if brain.similar(o["t"][:120], o["t"], None, limit=1, threshold=0.3):
            continue
        out.append(o)
    return out[-limit:]
