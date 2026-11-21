"""Mots de chaque souvenir gardés d'une commande à l'autre : `brain add` cherche ses doublons (Brain.similar) et ses
liens suggérés sans redécouper tout le cerveau ni en refaire toute l'analyse.

- state/mots.bin : mots du titre et du titre + contenu de chaque souvenir (anti-doublons, Brain.similar) ;
- state/termes.bin : termes pondérés de chaque souvenir (titre, étiquettes, contenu) et formes écrites de chaque terme
  dans tout le cerveau, tels que l'analyse du graphe (graph.py) les calcule pour ses liens déduits.
Chaque entrée porte l'empreinte du texte dont elle vient : un souvenir modifié depuis est redécoupé, jamais lu faux. Les
deux fichiers sont refaits en arrière-plan avec les vues (vues.py) ; une commande qui a dû beaucoup recalculer (premier
ajout après une mise à jour, fichiers effacés) les écrit elle-même pour les suivantes (keep)."""
from __future__ import annotations

import marshal
import math
import os
import sys
import time
import zlib
from collections import Counter

from .common import STATE_DIR, log, tokenize

TAG = f"mots2:{sys.version_info[0]}.{sys.version_info[1]}"  # le format de marshal change d'une version de Python à l'autre
MOTS_FILE = STATE_DIR / "mots.bin"
TERMES_FILE = STATE_DIR / "termes.bin"
KEEP_MIN = 64  # entrées recalculées par une commande à partir desquelles elle réécrit elle-même le fichier
_LOADED = {}  # fichier → ((mtime, taille), contenu) : relu seulement s'il a changé
_MISSED = {"mots": 0, "termes": 0}  # entrées absentes ou périmées rencontrées par ce processus
_TERMS = {}  # derniers termes vus par inferred() (termes, empreintes, formes), pour keep()


class _Labels:
    """Forme affichée d'un terme (graph._why) : la plus fréquente dans tout le cerveau, à égalité la première vue —
    comptes de termes.bin, puis ceux des souvenirs redécoupés, dans l'ordre des souvenirs, comme graph._vectors.
    Calculée seulement pour les quelques mots montrés."""

    def __init__(self, disp, extra):
        self.disp, self.extra = disp, extra

    def get(self, key, default=None):
        c = Counter(self.disp.get(key) or {})
        for more in self.extra.get(key, ()):
            c.update(more)
        return c.most_common(1)[0][0] if c else default


def digest(n) -> tuple:
    """Empreinte du texte d'un souvenir (titre, contenu, étiquettes) : une entrée gardée ne vaut que pour ce texte-là.
    CRC-32 et longueurs : 1 µs par souvenir (le cerveau entier est revu à chaque `add`), et une collision exigerait
    en plus les mêmes longueurs."""
    title, body, tags = str(n["title"]), str(n.get("body", "")), n.get("tags") or ()
    c = zlib.crc32(body.encode("utf-8", "surrogatepass"), zlib.crc32(title.encode("utf-8", "surrogatepass")))
    if tags:
        c = zlib.crc32(" ".join(map(str, tags)).encode("utf-8", "surrogatepass"), c)
    return c, len(title), len(body), len(tags)


def _load(path) -> dict:
    try:
        st = path.stat()
    except OSError:
        return {}
    sig = (st.st_mtime_ns, st.st_size)
    hit = _LOADED.get(str(path))
    if hit is not None and hit[0] == sig:
        return hit[1]
    try:
        with open(path, "rb") as fh:
            blob = marshal.loads(fh.read())
        if not (isinstance(blob, dict) and blob.get("v") == TAG and isinstance(blob.get("rows"), dict)):
            blob = {}
    except Exception:  # fichier tronqué, autre version de Python : on recalcule
        blob = {}
    _LOADED[str(path)] = (sig, blob)
    return blob


def _interned(words) -> frozenset:
    """Mots partagés (sys.intern) : marshal écrit chaque mot distinct une fois et ne crée qu'un objet par mot à la
    relecture — fichier plus petit, relu et libéré plus vite (des centaines de milliers de chaînes sinon)."""
    return frozenset(sys.intern(w) for w in words)


def _terms_shared(tf) -> dict:
    return {sys.intern(k): f for k, f in tf.items()}


def _write(path, blob) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        with open(tmp, "wb") as fh:
            fh.write(marshal.dumps(blob))
        for attempt in range(8):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:  # Windows : fichier ouvert un instant par un lecteur
                time.sleep(0.05 * (attempt + 1))
        os.replace(tmp, path)
    except Exception as exc:
        log(f"mots : {path.name} : {exc!r}")


def _tokens(n) -> tuple:
    """Mots du titre et du titre + contenu, exactement comme Brain.similar les découpe."""
    title, body = n["title"], n.get("body", "")
    return _interned(tokenize(title)), _interned(tokenize(f"{title} {body}"))


def _terms_of(n) -> tuple:
    """Termes pondérés d'un souvenir et leurs formes écrites, exactement comme graph._vectors. → (tf, formes)"""
    from .graph import _terms
    tf, disp = Counter(), {}
    for text, w in ((n["title"], 3.0), (" ".join(n.get("tags") or []), 2.2), (n.get("body", ""), 1.0)):
        for key, orig in _terms(text):
            tf[key] += w
            d = disp.get(key)
            if d is None:
                d = disp[key] = Counter()
            d[orig] += 1
    return dict(tf), disp


def prime(brain) -> dict:
    """Entrées de Brain.similar() déjà connues ({id: ((titre, contenu), mots du titre, mots du tout)}), pour les
    souvenirs dont le texte n'a pas changé depuis l'écriture de mots.bin."""
    rows = _load(MOTS_FILE).get("rows") or {}
    out = {}
    for n in brain.active(own=True):
        if n["type"] == "project":
            continue
        r = rows.get(n["id"]) if rows else None
        if r is not None and r[0] == digest(n):
            out[n["id"]] = ((n["title"], n.get("body", "")), r[1], r[2])
        else:
            _MISSED["mots"] += 1
    return out


def inferred(brain, nid, limit=3) -> list:
    """Liens déduits du souvenir `nid`, ceux que graph.inferred_of(graph.ensure(brain), nid, limit) donnerait, sans
    analyser tout le graphe (0,9 s à 3 000 souvenirs, 4 s à 10 000) : mêmes termes et mêmes formules que graph.analyze
    (TF-IDF sur tous les souvenirs actifs, mots discriminants, bonus d'étiquettes et de projet, liens écrits exclus,
    k meilleurs voisins), calculés pour ce seul souvenir. → [(autre id, poids, confiance, mots communs)]"""
    from . import graph
    nodes = list(brain.active())
    x = next((n for n in nodes if n["id"] == nid), None)
    if x is None:
        return []
    stored = _load(TERMES_FILE)
    rows = stored.get("rows") or {}
    disp = (stored.get("disp") or {}) if rows else {}
    tfs, digests, extra = {}, {}, {}
    for n in nodes:  # dans l'ordre des souvenirs, comme graph._vectors : mêmes formes affichées à égalité
        d = digests[n["id"]] = digest(n)
        r = rows.get(n["id"]) if rows else None
        if r is not None and r[0] == d:
            tfs[n["id"]] = r[1]
            continue
        _MISSED["termes"] += 1
        tfs[n["id"]], forms = _terms_of(n)
        for k, c in forms.items():
            extra.setdefault(k, []).append(c)
    labels = _Labels(disp, extra)
    _TERMS.update(rows=tfs, digests=digests, disp=disp, extra=extra)
    count = len(tfs) or 1
    df = Counter()
    for tf in tfs.values():
        df.update(tf.keys())
    idf = {}

    def vec(tf):
        v = {}
        for k, f in tf.items():
            i = idf.get(k)
            if i is None:
                i = idf[k] = math.log((count + 1) / (df[k] + 1)) + 1.0
            v[k] = (1 + math.log(f)) * i
        norm = math.sqrt(sum(t * t for t in v.values())) or 1.0
        return {k: t / norm for k, t in v.items()}

    cap = max(2, min(int(0.3 * count), 50))  # mots discriminants : comme graph._similarities
    vx = vec(tfs[nid])
    disc = [k for k in vx if df[k] <= cap]
    if not disc:
        return []
    discset = set(disc)
    linked = {e["to"] if e["from"] == nid else e["from"] for e in brain.edges if nid in (e["from"], e["to"])}
    proj, tags = x.get("project"), set(x.get("tags") or [])
    cands = []
    for n in nodes:
        m = n["id"]
        tf = tfs[m]
        if m == nid or tf.keys().isdisjoint(discset) or m in linked or m == proj or n.get("project") == nid:
            continue  # liens écrits et appartenance au projet : déjà explicites, jamais suggérés
        vy = vec(tf)
        s = sum(vx[k] * vy[k] for k in disc if k in vy)
        if s < graph.MIN_SIM * 0.8:
            continue
        bonus = 0.06 * min(2, len(tags & set(n.get("tags") or [])))
        if proj and proj == n.get("project"):
            bonus += 0.03
        w = s + bonus
        if w >= graph.MIN_SIM:
            cands.append((w, m, vy))
    cands.sort(key=lambda c: (-c[0], c[1]))  # ses k meilleurs voisins, dans l'ordre de graph.analyze
    out = [(m, round(w, 3), graph.confidence(w), graph._why(vx, vy, labels)) for w, m, vy in cands[:graph.TOP_K]]
    out.sort(key=lambda o: -o[1])  # comme graph.inferred_of
    return out[:limit]


def keep(brain) -> None:
    """Fin d'une commande qui a dû beaucoup redécouper (premier `add` après une mise à jour, fichiers effacés) : les
    fichiers sont réécrits tout de suite et les commandes suivantes repartent de là. Sinon rien : la tâche des vues les
    refait en arrière-plan."""
    try:
        if _MISSED["mots"] >= KEEP_MIN:
            rows = {}
            for nid, (text, tt, bt) in (brain._sim_cache or {}).items():
                n = brain.nodes.get(nid)
                if n is not None and text == (n["title"], n.get("body", "")):
                    rows[nid] = (digest(n), _interned(tt), _interned(bt))
            _write(MOTS_FILE, {"v": TAG, "rows": rows})
            _MISSED["mots"] = 0
        if _MISSED["termes"] >= KEEP_MIN and _TERMS.get("rows"):
            disp = {k: dict(c) for k, c in _TERMS["disp"].items()}
            for k, more in _TERMS["extra"].items():  # (formes d'un souvenir modifié comptées deux fois jusqu'à rebuild)
                c = Counter(disp.get(k) or {})
                for m in more:
                    c.update(m)
                disp[sys.intern(k)] = {sys.intern(o): v for o, v in c.items()}
            rows = {nid: (_TERMS["digests"][nid], _terms_shared(tf)) for nid, tf in _TERMS["rows"].items()}
            _write(TERMES_FILE, {"v": TAG, "rows": rows, "disp": disp})
            _MISSED["termes"] = 0
    except Exception as exc:
        log(f"mots : {exc!r}")


def rebuild(brain) -> None:
    """Les deux fichiers refaits pour tout le cerveau (tâche des vues, en arrière-plan) : formes écrites exactes."""
    stored = _load(MOTS_FILE).get("rows") or {}
    mots, termes, merged = {}, {}, {}
    for n in brain.active():
        d = digest(n)
        if n["type"] != "project" and not n["id"].startswith("c--"):  # ce que Brain.similar compare
            r = stored.get(n["id"])
            mots[n["id"]] = r if r is not None and r[0] == d else (d, *_tokens(n))
        tf, forms = _terms_of(n)
        termes[n["id"]] = (d, _terms_shared(tf))
        for k, c in forms.items():
            if k in merged:
                merged[k].update(c)
            else:
                merged[k] = c
    _write(MOTS_FILE, {"v": TAG, "rows": mots})
    _write(TERMES_FILE, {"v": TAG, "rows": termes,
                         "disp": {sys.intern(k): {sys.intern(o): v for o, v in c.items()} for k, c in merged.items()}})
