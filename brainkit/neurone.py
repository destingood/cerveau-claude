"""Neurone du rappel : un petit réseau (une couche cachée de 12 neurones, Python pur) qui apprend, sur les échanges de
CET utilisateur, quels souvenirs lui servent vraiment, dans tous ses domaines.

Pour chaque message tapé, les 12 meilleurs candidats de la recherche sont décrits par 27 traits (score, couverture,
mots exacts ou seulement approchés, mots du titre, projet, contexte des messages précédents, âge, type…). Après la
réponse, chaque candidat est étiqueté « utile » si Claude a repris ses termes distinctifs ou ses valeurs (même règle
que « montré ≠ utilisé »). Au premier usage, les échanges des 30 derniers jours (transcripts locaux) amorcent
l'apprentissage. Le réseau ne prend la main que s'il fait au moins aussi bien que la règle fixe sur les messages les
plus récents, jamais vus à l'apprentissage, et en moins de tokens ; sinon la règle reste. En service : ligne complète
si la probabilité d'être utile est forte, titre seul (un `show` au besoin) pour le reste de ce que la règle accepte —
il ne cache rien de ce que la règle aurait montré (mesuré : le cacher faisait perdre les messages écrits en
phonétique). Rien ne sort de la machine : les exemples (des nombres, jamais de texte) et les poids restent
dans state/."""
from __future__ import annotations

import datetime as _dt
import json
import math
import random
import time

from . import hooks, journal, search
from .common import (CLAUDE_HOME, STATE_DIR, FileLock, fmt_date, fold, load_config, log, now_iso, parse_iso,
                     read_json, set_config, tokenize, write_json)
from .store import Brain

V = 1  # version des traits : la changer écarte les anciens poids
TOP = 12  # candidats décrits par message
TYPES = ["feedback", "user", "decision", "fact", "learning", "reference", "todo"]
NAMES = ["log score", "couverture", "termes trouvés", "log nb termes", "rang", "score/premier", "exacts", "approchés",
         "dans le titre", "rareté max", "mots inconnus", "règle", "importance", "longueur", "projet courant",
         "autre projet", "contexte score", "contexte couverture", "âge", "longueur message"] + TYPES
MODEL_FILE = STATE_DIR / "neurone.json"
EX_FILE = STATE_DIR / "neurone-ex.jsonl"
LOCK = STATE_DIR / "neurone.lock"
SPAWN_FILE = STATE_DIR / "neurone.spawn"
HIDDEN, EPOCHS, LR, L2 = 12, 60, 0.03, 3e-2
MAX_ROWS, MIN_ROWS, MIN_POS, MIN_TEST_POS = 5000, 300, 30, 8
RETRAIN_ROWS, SPAWN_EVERY, HARVEST_DAYS = 120, 600, 30


# ------------------------------------------------------------------------------------------ traits
def _days(a, b) -> float:
    try:
        return max(0.0, (_dt.datetime.fromisoformat(b[:19]) - _dt.datetime.fromisoformat(a[:19])).total_seconds() / 86400)
    except Exception:
        return 30.0


def _head(n) -> set:
    return set(tokenize(f"{n['title']} {' '.join(n.get('tags') or [])} {(n.get('meta') or {}).get('keys') or ''}"))


def features(idx, query, cands, accs, project, prev, when, raw_len) -> list:
    """Traits de chaque candidat (résultats de search_memories, dans l'ordre) ; `accs` : la règle fixe les accepte ;
    `prev` : requêtes des messages précédents de la session ; `when` : date du message."""
    if not cands:
        return []
    qt = list(dict.fromkeys(tokenize(query)))
    exp = {t: idx.expand(t) for t in qt}
    unseen = math.log(1 + (idx.N + 0.5) / 0.5)
    qidf = {t: (max(e for _, _, e, _ in exp[t]) if exp[t] else unseen) for t in qt}
    total = sum(qidf.values()) or 1.0
    unk = sum(1 for t in qt if not exp[t]) / max(1, len(qt))
    top = cands[0]["score"]
    pos = getattr(idx, "_pos", None)
    if pos is None:
        pos = idx._pos = {k: i for i, k in enumerate(idx.keys)}
    ctx = {r["key"]: r for r in idx.search(" ".join(prev[-2:]), limit=80)} if prev else {}
    out = []
    for k, (r, acc) in enumerate(zip(cands, accs)):
        n = r["node"]
        i = pos.get(n["id"])
        tf = idx.tfs[i] if i is not None else {}
        head = _head(n)
        exact = fuzzy = headw = maxidf = 0.0
        for t in qt:
            best = None
            for v, w, e, _ in exp[t]:
                if tf.get(v) and (best is None or w > best[0]):
                    best = (w, e, v)
            if best:
                w, e, v = best
                maxidf = max(maxidf, e)
                exact += qidf[t] if w >= 0.99 else 0
                fuzzy += qidf[t] if w <= 0.6 else 0
                headw += qidf[t] if (v in head or t in head) else 0
        cx = ctx.get(n["id"])
        f = [math.log1p(r["score"]), r.get("cov", 0.0), r["matched"] / max(1, r["nq"]), math.log1p(r["nq"]), k / 10,
             r["score"] / max(1e-6, top), exact / total, fuzzy / total, headw / total, maxidf / unseen, unk,
             float(acc), (n.get("importance", 3) - 3) / 2, math.log1p(len(n.get("body") or "")) / 8,
             float(bool(project) and n.get("project") == project),
             float(bool(n.get("project")) and n.get("project") != project),
             math.log1p(cx["score"]) if cx else 0.0, cx["cov"] if cx else 0.0,
             math.log1p(_days(n.get("created") or when, when)), math.log1p(raw_len) / 6]
        out.append(f + [float(n["type"] == t) for t in TYPES])
    return out


# ------------------------------------------------------------------------------------------ réseau
def _sig(z) -> float:
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))


class Model:
    """Une couche cachée (tanh), une sortie (sigmoïde) : probabilité qu'un candidat serve la réponse."""

    def __init__(self, d=len(NAMES), h=HIDDEN, seed=3):
        rnd = random.Random(seed)
        self.W1 = [[rnd.gauss(0, 1 / math.sqrt(d)) for _ in range(d)] for _ in range(h)]
        self.b1 = [0.0] * h
        self.w2 = [rnd.gauss(0, 1 / math.sqrt(h)) for _ in range(h)]
        self.b2 = 0.0
        self.mu, self.sd = [0.0] * d, [1.0] * d

    @classmethod
    def from_dict(cls, d):
        m = cls.__new__(cls)
        m.W1, m.b1, m.w2, m.b2, m.mu, m.sd = d["W1"], d["b1"], d["w2"], d["b2"], d["mu"], d["sd"]
        return m

    def to_dict(self) -> dict:
        r = lambda v: round(v, 6)
        return {"W1": [[r(w) for w in row] for row in self.W1], "b1": [r(b) for b in self.b1],
                "w2": [r(w) for w in self.w2], "b2": r(self.b2), "mu": [r(v) for v in self.mu],
                "sd": [r(v) for v in self.sd]}

    def _forward(self, x):
        hid = [math.tanh(sum(w * v for w, v in zip(row, x)) + b) for row, b in zip(self.W1, self.b1)]
        return _sig(sum(w * v for w, v in zip(self.w2, hid)) + self.b2), hid

    def predict(self, f) -> float:
        return self._forward([(v - m) / s for v, m, s in zip(f, self.mu, self.sd)])[0]

    def fit(self, X, Y, epochs=EPOCHS, lr=LR, l2=L2, seed=5):
        """Descente de gradient exemple par exemple (entropie croisée, L2), traits centrés-réduits."""
        n, d = len(X), len(X[0])
        self.mu = [sum(x[j] for x in X) / n for j in range(d)]
        self.sd = [max(1e-6, math.sqrt(sum((x[j] - self.mu[j]) ** 2 for x in X) / n)) for j in range(d)]
        Xs = [[(v - m) / s for v, m, s in zip(x, self.mu, self.sd)] for x in X]
        rnd, order = random.Random(seed), list(range(n))
        for ep in range(epochs):
            rnd.shuffle(order)
            a = lr / (1 + ep * 0.1)
            for i in order:
                x = Xs[i]
                p, hid = self._forward(x)
                g = p - Y[i]
                for k, hk in enumerate(hid):
                    gh = g * self.w2[k] * (1 - hk * hk)
                    self.w2[k] -= a * (g * hk + l2 * self.w2[k])
                    self.W1[k] = [w - a * (gh * v + l2 * w) for w, v in zip(self.W1[k], x)]
                    self.b1[k] -= a * gh
                self.b2 -= a * g
        return self


_CACHE = {}


def load():
    """Le réseau en service, ou None (pas encore appris, ou pas meilleur que la règle fixe)."""
    try:
        st = MODEL_FILE.stat()
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = _CACHE.get("m")
    if hit and hit[0] == key:
        return hit[1]
    d = read_json(MODEL_FILE, {}) or {}
    m = None
    if d.get("ready") and d.get("v") == V and len(d.get("mu") or ()) == len(NAMES):
        try:
            m = Model.from_dict(d)
        except (KeyError, TypeError):
            m = None
    _CACHE["m"] = (key, m)
    return m


def _pick(ids, probs, accs, injected, rc) -> list:
    hi, lo = rc.get("neurone_haut", 0.6), rc.get("neurone_bas", 0.0)
    out = []
    for i in sorted(range(len(ids)), key=lambda i: -probs[i]):
        if len(out) >= rc["max_items"]:
            break
        if ids[i] in injected:
            continue
        if probs[i] >= hi:
            out.append((i, True))
        elif probs[i] >= lo and accs[i]:
            out.append((i, False))
    return out


def choose(cands, probs, accs, injected, rc) -> list:
    """→ [(candidat, ligne complète ?)] : les plus probables d'abord ; ligne complète si p ≥ neurone_haut, titre seul
    si la règle fixe accepte le souvenir (et p ≥ neurone_bas, 0 par défaut) ; au plus max_items, jamais deux fois par
    session."""
    return [(cands[i], full) for i, full in _pick([r["node"]["id"] for r in cands], probs, accs, injected, rc)]


# ------------------------------------------------------------------------------------------ exemples
def _read_rows() -> list:
    rows = []
    try:
        fh = open(EX_FILE, encoding="utf-8")
    except OSError:
        return rows
    with fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and len(r.get("f") or ()) == len(NAMES) and r.get("t"):
                rows.append(r)
    return rows


def _append(rows):
    data = "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows)
    with FileLock(LOCK, timeout=2.0, stale=120.0, strict=False):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(EX_FILE, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(data)


def _row(t, sid, n, f, y, src) -> dict:
    return {"t": t, "s": str(sid or "")[:8], "id": n["id"], "f": [round(x, 4) for x in f], "y": int(y),
            "c": [len(hooks.memory_line(n)), len(hooks.memory_line(n, False))], "src": src}


def learn_turn(st, scan, sid, brain=None) -> int:
    """Fin de réponse : étiquette les candidats des derniers messages d'après ce que Claude a écrit ou fait (le
    souvenir a-t-il servi ?), les ajoute aux exemples et relance l'apprentissage en arrière-plan au besoin."""
    entries = st.pop("cands", None) or []
    if not scan or not entries:
        return 0
    text = fold(" ".join(scan))
    toks = set(tokenize(text))
    brain = brain or Brain.load()
    idx = search.memory_index(brain)
    rows = []
    for e in entries:
        for c in e.get("c") or []:
            n = brain.nodes.get(c.get("id"))
            if n and e.get("t") and len(c.get("f") or ()) == len(NAMES):
                rows.append({"t": e["t"], "s": str(sid or "")[:8], "id": n["id"], "f": c["f"],
                             "y": int(hooks.is_used(n, text, toks, idx)), "c": c.get("c") or [0, 0], "src": "live"})
    if rows:
        _append(rows)
        maybe_retrain()
    return len(rows)


def maybe_retrain() -> bool:
    """Apprentissage en arrière-plan (au plus toutes les 10 min) quand ~120 nouveaux exemples sont arrivés depuis le
    dernier ; la toute première fois, récolte d'abord les échanges passés de l'utilisateur."""
    try:
        size = EX_FILE.stat().st_size
    except OSError:
        size = 0
    m = read_json(MODEL_FILE, None)
    if isinstance(m, dict) and m.get("v") == V:
        if size - m.get("bytes", 0) < RETRAIN_ROWS * (m.get("bytes_per_row") or 300):
            return False
        args = ["neurone", "entrainer", "--quiet"]
    else:
        args = ["neurone", "apprendre", "--quiet"]
    try:
        if time.time() - SPAWN_FILE.stat().st_mtime < SPAWN_EVERY:
            return False
    except OSError:
        pass
    try:
        SPAWN_FILE.write_text(now_iso(), encoding="utf-8")
    except OSError:
        return False
    return hooks.spawn_background(args)


def _local(ts):
    """Horodatage d'un transcript (UTC, ISO) → heure locale, au format des dates du cerveau."""
    d = parse_iso(ts)
    return d.strftime("%Y-%m-%dT%H:%M:%S") if d else None


def _transcript_messages(days) -> list:
    """Messages tapés par l'utilisateur ces `days` derniers jours, et ce que Claude a écrit ou fait ensuite (même lecture
    que le journal ; sous-agents, résumés de compaction et avis automatiques écartés)."""
    root = CLAUDE_HOME / "projects"
    cutoff = time.time() - days * 86400
    try:
        files = sorted(p for p in root.rglob("*.jsonl") if p.stat().st_mtime >= cutoff)
    except OSError:
        files = []
    msgs, seen = [], set()
    for p in files:
        cur = None
        try:
            fh = open(p, "rb")
        except OSError:
            continue
        with fh:
            for line in fh:
                if b'"tool_result"' in line or (b'"user"' not in line and b'"assistant"' not in line):
                    continue  # sorties d'outils (le gros des transcripts), pièces jointes, instantanés : sans intérêt ici
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(o, dict) or o.get("isSidechain"):
                    continue
                typ = o.get("type")
                if typ == "user" and not o.get("isMeta") and not o.get("isCompactSummary"):
                    content = (o.get("message") or {}).get("content")
                    if isinstance(content, list):
                        content = " ".join(b.get("text", "") for b in content
                                           if isinstance(b, dict) and b.get("type") == "text")
                    if not isinstance(content, str) or not content.strip():
                        continue
                    text = journal.clean_prompt(content)
                    turn = o.get("turnOrigin")
                    human = turn == "human" if turn else (o.get("origin") or {}).get("kind", "human") == "human"
                    if not text or not human or journal.AUTO_RE.match(text):
                        continue
                    sid, raw = o.get("sessionId") or p.stem, content.strip()[:4000]
                    if (sid, raw) in seen:  # session reprise : messages recopiés
                        cur = None
                        continue
                    seen.add((sid, raw))
                    cur = {"t": o.get("timestamp") or "", "raw": raw, "cwd": o.get("cwd") or "", "sid": sid,
                           "r": [], "n": 0, "full": False}
                    msgs.append(cur)
                elif typ == "assistant" and cur is not None and not cur["full"]:
                    for b in (o.get("message") or {}).get("content") or []:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "text":
                            s = (b.get("text") or "")[:4000]
                        elif b.get("type") == "tool_use":
                            s = json.dumps(b.get("input") or {}, ensure_ascii=False)[:3000]
                        else:
                            continue
                        if cur["n"] + len(s) > 30000:
                            cur["full"] = True
                            break
                        cur["r"].append(s)
                        cur["n"] += len(s)
    msgs.sort(key=lambda m: m["t"])
    return msgs


def harvest(days=HARVEST_DAYS, brain=None, limit=4000) -> int:
    """Amorçage : rejoue les messages tapés ces `days` derniers jours avec les candidats que le cerveau aurait trouvés
    à ce moment-là (souvenirs déjà écrits), étiquetés d'après la vraie réponse ; sessions déjà apprises sautées.
    → nombre d'exemples ajoutés."""
    brain = brain or Brain.load()
    rc = load_config()["recall"]
    idx = search.memory_index(brain)
    known = {r.get("s") for r in _read_rows()}
    hist, rows = {}, []
    for m in _transcript_messages(days)[-limit:]:
        raw = m["raw"]
        if len(raw) < 6 or raw.startswith("/") or m["sid"][:8] in known:
            continue
        q = hooks.recall_query(raw)
        when = _local(m["t"])
        if not tokenize(q) or not when:
            continue
        proj = brain.project_for_path(m["cwd"]) if m["cwd"] else None
        pid = proj["id"] if proj else None
        prev = hist.setdefault(m["sid"], [])
        if m["r"]:
            found = search.search_memories(brain, q, limit=30, project=pid, expand=False)
            cands = [r for r in found if r["node"]["type"] != "project"
                     and (r["node"].get("created") or "")[:19] <= when][:TOP]
            accs = [search.accept_recall(r, rc["min_cov"], rc["min_score"], query=q) for r in cands]
            reply = fold("\n".join(m["r"]))
            toks = set(tokenize(reply))
            for r, f in zip(cands, features(idx, q, cands, accs, pid, prev, when, len(raw))):
                rows.append(_row(when, m["sid"], r["node"], f, hooks.is_used(r["node"], reply, toks, idx), "boot"))
        prev.append(hooks.context_query(raw, q))  # comme le hook : jamais de secret dans le contexte
        del prev[:-2]
    if rows:
        _append(rows)
    return len(rows)


# ------------------------------------------------------------------------------------------ apprentissage
def _simulate(msgs, pick, rc) -> dict:
    """Rejoue des messages (chacun avec ses candidats étiquetés) comme le hook : souvenirs injectés (une fois par
    session), utiles, et tokens du bloc (en-tête et lignes entières dans le budget)."""
    inj_by, res = {}, {"messages": 0, "injectes": 0, "utiles": 0, "tokens": 0}
    head = len(hooks.MEM_HEADER)
    for (s, _), rows in msgs:
        inj = inj_by.setdefault(s, set())
        used, size, shown = head + 1, head, []
        for i, full in pick(rows, inj):
            n = rows[i]["c"][0 if full else 1] + 1
            if used + n > rc["max_chars"]:
                break
            used, size = used + n, size + n
            shown.append(rows[i])
        if shown:
            inj.update(r["id"] for r in shown)
            res["messages"] += 1
            res["injectes"] += len(shown)
            res["utiles"] += sum(r["y"] for r in shown)
            res["tokens"] += int(size / 2.2)
    return res


def _rule_pick(rc):
    def pick(rows, inj):
        out = [(i, True) for i, r in enumerate(rows) if r["f"][11] and r["id"] not in inj]
        return out[:rc["max_items"]]
    return pick


def _model_pick(model, rc):
    def pick(rows, inj):
        return _pick([r["id"] for r in rows], [model.predict(r["f"]) for r in rows], [r["f"][11] for r in rows], inj, rc)
    return pick


def train() -> dict:
    """Apprend sur les exemples (au plus les 5 000 plus récents). Contrôle : appris sur les 3/4 les plus anciens des
    messages, rejoué sur le dernier quart contre la règle fixe ; en service seulement s'il garde (presque) autant de
    souvenirs utiles en ne coûtant pas plus de tokens. Le réseau final apprend ensuite sur tout."""
    rc = load_config()["recall"]
    with FileLock(LOCK, timeout=10.0, stale=120.0, strict=False):
        rows = _read_rows()
        rows.sort(key=lambda r: r["t"])
        if len(rows) > MAX_ROWS:
            rows = rows[-MAX_ROWS:]
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = EX_FILE.with_name(EX_FILE.name + ".tmp")
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                fh.writelines(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows)
            tmp.replace(EX_FILE)
        try:
            size = EX_FILE.stat().st_size
        except OSError:
            size = 0
    pos = sum(r["y"] for r in rows)
    out = {"v": V, "ready": False, "n": len(rows), "pos": pos, "bytes": size,
           "bytes_per_row": round(size / len(rows), 1) if rows else 300, "at": now_iso()}
    groups = {}
    for r in rows:
        groups.setdefault((r["s"], r["t"]), []).append(r)
    keys = sorted(groups, key=lambda k: k[1])
    out["messages"] = len(keys)
    cut = int(len(keys) * 0.75)
    test = [(k, sorted(groups[k], key=lambda r: r["f"][4])) for k in keys[cut:]]
    test_pos = sum(r["y"] for _, g in test for r in g)
    if len(rows) < MIN_ROWS or pos < MIN_POS or test_pos < MIN_TEST_POS:
        out["why"] = (f"pas encore assez d'exemples ({len(rows)} candidats dont {pos} utiles ; il en faut "
                      f"{MIN_ROWS} dont {MIN_POS} utiles, et {MIN_TEST_POS} utiles récents pour le contrôle)")
        write_json(MODEL_FILE, out, indent=None)
        return out
    train_rows = [r for k in keys[:cut] for r in groups[k]]
    trial = Model().fit([r["f"] for r in train_rows], [r["y"] for r in train_rows])
    ru, nn = _simulate(test, _rule_pick(rc), rc), _simulate(test, _model_pick(trial, rc), rc)
    out["metrics"] = {"messages_test": len(test), "regle": ru, "neurone": nn}
    slack = max(1, round(0.1 * ru["utiles"]))
    if nn["utiles"] < ru["utiles"] - slack:
        out["why"] = f"moins de souvenirs utiles que la règle fixe ({nn['utiles']} contre {ru['utiles']})"
    elif nn["tokens"] > ru["tokens"]:
        out["why"] = f"plus de tokens que la règle fixe ({nn['tokens']} contre {ru['tokens']})"
    else:
        out.update(Model().fit([r["f"] for r in rows], [r["y"] for r in rows]).to_dict(), ready=True, why="")
    write_json(MODEL_FILE, out, indent=None)
    _CACHE.clear()
    return out


# ------------------------------------------------------------------------------------------ commande
def report() -> str:
    mode = load_config()["recall"].get("neurone", "auto")
    m = read_json(MODEL_FILE, None) or {}
    rows = _read_rows()
    lines = []
    if mode == "off":
        state = "coupé (règle fixe seule ; `neurone auto` pour le rallumer)"
    elif m.get("ready") and m.get("v") == V:
        state = f"en service (appris le {fmt_date(m.get('at'))})"
    elif m:
        state = f"en apprentissage — {m.get('why') or 'pas encore prêt'} ; la règle fixe reste en service"
    else:
        state = "en apprentissage (pas encore entraîné) ; la règle fixe reste en service"
    lines.append(f"🧠 Neurone du rappel : {state}")
    msgs = len({(r["s"], r["t"]) for r in rows})
    lines.append(f"Exemples : {len(rows)} candidats de {msgs} messages ({sum(r['y'] for r in rows)} utiles), "
                 f"dont {sum(1 for r in rows if r.get('src') == 'live')} appris en direct — fichier local "
                 f"{EX_FILE.name}, jamais partagé")
    met = m.get("metrics")
    if met:
        ru, nn = met["regle"], met["neurone"]
        gain = f" ({100 * (nn['tokens'] - ru['tokens']) / ru['tokens']:+.0f} %)" if ru["tokens"] else ""
        lines.append(f"Contrôle sur les {met['messages_test']} messages les plus récents (jamais vus à l'apprentissage) :")
        lines.append(f"  règle fixe : {ru['injectes']} souvenirs injectés, {ru['utiles']} utiles, {ru['tokens']} tokens")
        lines.append(f"  neurone    : {nn['injectes']} souvenirs injectés, {nn['utiles']} utiles, {nn['tokens']} tokens{gain}")
    return "\n".join(lines)


def run_cli(action="etat", days=HARVEST_DAYS, quiet=False) -> str:
    if action in ("off", "auto"):
        set_config("recall.neurone", action)
        return "" if quiet else report()
    try:
        if action == "apprendre":
            added = harvest(days)
            train()
            if not quiet:
                return f"{added} exemples récoltés dans les échanges des {days} derniers jours.\n{report()}"
        elif action == "entrainer":
            train()
    except Exception as exc:
        log(f"neurone {action} : {exc!r}")
        if quiet:
            return ""
        raise
    return "" if quiet else report()
