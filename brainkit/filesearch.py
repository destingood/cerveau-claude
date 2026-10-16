"""Recherche de fichiers légère, appelée à chaque message par le hook de rappel.

L'index BM25 d'une carte de projet est relu depuis un cache binaire (marshal, ~4× plus rapide que le JSON + la
reconstruction de l'index), invalidé dès que search.json change. Ce module n'importe pas le cartographe (mapper),
dont les centaines d'expressions régulières coûtent ~25 ms à compiler."""
from __future__ import annotations

import marshal
import os
import posixpath
import re
import sys
import time

from .common import PROJECTS_DIR, log, read_json
from .search import Index, accept_recall

BACKUP_RX = re.compile(r"(^|/)[^/]*(sauvegarde|backup|archive|snapshot|copie|export|ancien|\bold\b|\bbak\b)[^/]*/", re.I)
OUTPUT_RX = re.compile(r"(^|/)(_out|out|dist|build|node_modules|vendor|\.cache|tmp|temp|cache)/", re.I)
DATA_EXT = (".json", ".csv", ".tsv", ".xml")
CACHE_NAME = "search.idx"
RECALL_NAME = "recall.idx"  # index allégé du rappel automatique : sans sauvegardes, exports, données brutes ni sorties
TAG = f"1:{sys.version_info[0]}.{sys.version_info[1]}"  # le format marshal dépend de la version de Python


def _paths(pid, kind="full"):
    d = PROJECTS_DIR / pid
    return d / "search.json", d / (RECALL_NAME if kind == "recall" else CACHE_NAME)


def _useful(key) -> bool:
    return not BACKUP_RX.search(key) and not OUTPUT_RX.search(key) and posixpath.splitext(key)[1].lower() not in DATA_EXT


def _write(cache, idx, descs, st, name):
    blob = {"tag": TAG, "src": [st.st_mtime_ns, st.st_size], "keys": idx.keys, "tfs": idx.tfs, "lens": idx.lens,
            "df": dict(idx.df), "post": dict(idx.post), "pre": dict(idx.by_prefix), "descs": descs}
    tmp = cache.with_name(f"{name}.{os.getpid()}.tmp")
    with open(tmp, "wb") as fh:
        marshal.dump(blob, fh)
    for attempt in range(6):  # Windows : le cache peut être ouvert en lecture par un autre hook
        try:
            os.replace(tmp, cache)
            return
        except PermissionError:
            time.sleep(0.03 * (attempt + 1))
    os.remove(tmp)


def build_cache(pid, s=None, kind="full"):
    """Construit les deux index (complet et allégé pour le rappel) et les écrit en cache.
    → (Index, {chemin: description}) de l'index demandé, ou None."""
    src, _ = _paths(pid)
    if s is None:
        s = read_json(src, None)
    if not s or not s.get("keys"):
        return None
    descs = s.get("descs") or []
    full = Index.from_tfs(s["keys"], s["tfs"])
    sel = [i for i, k in enumerate(s["keys"]) if _useful(k)]
    slim = Index.from_tfs([s["keys"][i] for i in sel], [s["tfs"][i] for i in sel])
    slim_descs = [descs[i] for i in sel] if descs else []
    try:
        st = src.stat()
        _write(_paths(pid, "full")[1], full, descs, st, CACHE_NAME)
        _write(_paths(pid, "recall")[1], slim, slim_descs, st, RECALL_NAME)
    except Exception as exc:
        log(f"cache recherche {pid} : {exc!r}")
    if kind == "recall":
        return slim, dict(zip(slim.keys, slim_descs))
    return full, dict(zip(s["keys"], descs))


def load_index(pid, kind="full"):
    """(Index, descriptions) depuis le cache s'il est à jour, sinon reconstruit puis remis en cache."""
    src, cache = _paths(pid, kind)
    try:
        st = src.stat()
    except OSError:
        return None
    try:
        with open(cache, "rb") as fh:
            blob = marshal.loads(fh.read())  # marshal.load(fichier) lit par petits morceaux : 7× plus lent
        if blob.get("tag") == TAG and blob.get("src") == [st.st_mtime_ns, st.st_size]:
            return Index.from_state(blob), dict(zip(blob["keys"], blob["descs"]))
    except Exception:  # cache absent, ancien ou écrit par une autre version de Python
        pass
    return build_cache(pid, kind=kind)


def search_files(pid, query, limit=10, fuzzy=True, kind="full"):
    got = load_index(pid, kind)
    if not got:
        return []
    idx, descs = got
    idx.fuzzy = fuzzy  # coupé pour le rappel à chaque message : l'index phonétique de milliers de fichiers coûte ~30 ms
    idx.code = True  # « authentification » trouve auth.py : le code abrège en 4 lettres
    res = idx.search(query, limit * 4)
    for r in res:  # sauvegardes et données brutes passent après le code et les documents
        if BACKUP_RX.search(r["key"]):
            r["score"] *= 0.35
        if posixpath.splitext(r["key"])[1].lower() in (".json", ".csv", ".tsv", ".xml"):
            r["score"] *= 0.75
    res.sort(key=lambda r: -r["score"])
    return [dict(r, desc=descs.get(r["key"], "")) for r in res[:limit]]


def recall_files(pid, query, rc, exclude=()):
    """Fichiers à suggérer pour un message : filtre anti-bruit + une seule fois un même fichier copié ailleurs."""
    out, seen = [], set()
    for r in search_files(pid, query, 12, fuzzy=False, kind="recall"):
        if r["key"] in exclude or not accept_recall(r, rc["min_cov_files"]):
            continue
        sig = (posixpath.basename(r["key"]).lower(), r["desc"])
        if sig in seen:
            continue
        seen.add(sig)
        out.append({"path": r["key"], "desc": r["desc"]})
        if len(out) >= rc["max_files"]:
            break
    return out


def needs_refresh(pid, minutes=10) -> bool:
    try:
        return (time.time() - (PROJECTS_DIR / pid / "map.json").stat().st_mtime) > minutes * 60
    except OSError:
        return True
