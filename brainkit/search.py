"""Recherche plein texte BM25, tolérante : préfixes (« dropship » → « dropshipping »), synonymes métier FR/EN
(« commande » → « order »), et pour un mot inconnu la même prononciation (« atin » → « atteint ») ou une faute de
frappe d'une lettre (« shopfy » → « shopify »).

Sert à la fois à la mémoire (souvenirs) et aux cartes de projets (fichiers, symboles, titres)."""
from __future__ import annotations

import hashlib
import marshal
import math
import os
import re
import sys
from collections import Counter, defaultdict

from .common import days_since, tokenize
from .lexicon import INFLEXIONS, SYN, deletes, faux_amis, phon, root, within_one

K1, B = 1.3, 0.7
SUBWORD_W, SUBWORD_DICE, SUBWORD_TOP = 0.5, 0.6, 3


def grams(w) -> set:
    """Trigrammes de lettres d'un mot, bornes comprises : « chat » → ^ch, cha, hat, at$."""
    w = f"^{w}$"
    return {w[i:i + 3] for i in range(len(w) - 2)}


class Index:
    fuzzy = True  # rapprochement phonétique / fautes de frappe pour les mots absents de l'index
    code = False  # index de fichiers et de symboles : toutes les troncatures de 4 lettres y sont gardées (voir expand)
    subword = False  # encodeur de sous-mots (trigrammes) pour un mot inconnu sans autre piste : index des souvenirs

    def __init__(self, docs=()):
        self.keys, self.tfs, self.named = [], [], {}
        for key, fields in docs:
            tf, nm = Counter(), Counter()
            for text, weight in fields:
                if text:
                    for tok in tokenize(text):
                        tf[tok] += weight
                    for tok in faux_amis(text):  # faux amis (« Microsoft Store ») : occurrences ignorées par les synonymes
                        nm[tok] += weight
            if nm:
                self.named[len(self.keys)] = dict(nm)
            self.keys.append(key)
            self.tfs.append(tf)
        self._finalize()

    @classmethod
    def from_tfs(cls, keys, tfs):
        obj = cls.__new__(cls)
        obj.keys, obj.tfs, obj.named = list(keys), list(tfs), {}
        obj._finalize()
        return obj

    @classmethod
    def from_state(cls, d):
        """Index déjà calculé (cache marshal) : aucune reconstruction."""
        obj = cls.__new__(cls)
        obj.keys, obj.tfs, obj.lens = d["keys"], d["tfs"], d["lens"]
        obj.N = len(obj.keys)
        obj.avgdl = (sum(obj.lens) / obj.N) if obj.N else 1.0
        obj.df, obj.post, obj.by_prefix = d["df"], d["post"], d["pre"]
        obj.named = d.get("named") or {}
        return obj

    def _finalize(self):
        self.lens = [sum(tf.values()) or 1.0 for tf in self.tfs]
        self.N = len(self.keys)
        self.avgdl = (sum(self.lens) / self.N) if self.N else 1.0
        self.df = Counter()
        self.post = defaultdict(list)
        for i, tf in enumerate(self.tfs):
            for tok in tf:
                self.df[tok] += 1
                self.post[tok].append(i)
        self.by_prefix = defaultdict(list)
        for tok in self.df:
            if len(tok) >= 3:
                self.by_prefix[tok[:3]].append(tok)

    def idf(self, tok) -> float:
        n = self.df.get(tok, 0)
        return math.log(1 + (self.N - n + 0.5) / (n + 0.5))

    def _fuzzy_maps(self):
        """Index phonétique et index des « suppressions d'une lettre » (façon SymSpell), construits à la demande."""
        if getattr(self, "_phon", None) is None:
            ph, dl, rt = {}, {}, {}
            for tok in self.df:
                if len(tok) >= 3:
                    ph.setdefault(phon(tok), []).append(tok)
                if len(tok) >= 4:
                    for d in deletes(tok) | {tok}:
                        dl.setdefault(d, []).append(tok)
                if len(tok) >= 6:
                    rt.setdefault(root(tok), []).append(tok)
            self._phon, self._del, self._root = ph, dl, rt
        return self._phon, self._del, self._root

    def _tri_maps(self):
        """Encodeur de sous-mots : trigrammes de chaque mot de l'index sous sa forme écrite et sa forme phonétique, et
        leur nombre (dénominateur du coefficient de Dice). Construit à la demande, gardé dans le cache des souvenirs."""
        if getattr(self, "_tri", None) is None:
            fo, ph, size = {}, {}, {}
            for tok in self.df:
                if len(tok) >= 4 and not tok.isdigit():
                    a, b = grams(tok), grams(phon(tok))
                    for g in a:
                        fo.setdefault(g, []).append(tok)
                    for g in b:
                        ph.setdefault(g, []).append(tok)
                    size[tok] = (len(a), len(b))
            self._tri = (fo, ph, size)
        return self._tri

    def subwords(self, q, top=SUBWORD_TOP, dice=SUBWORD_DICE) -> list:
        """Mots de l'index proches de `q` par leurs morceaux : au moins 2 trigrammes en commun et un coefficient de Dice
        ≥ dice, sous la forme écrite ou phonétique. Rattrape ce que les fautes d'une lettre et la phonétique exacte
        ratent : « inteligen » → « intelligence », « consomé » → « consommer ». → [(mot, dice)], les plus proches."""
        fo, ph, size = self._tri_maps()
        best = {}
        for k, (m, g) in enumerate(((fo, grams(q)), (ph, grams(phon(q))))):
            cnt = Counter(v for x in g for v in m.get(x, ()))
            for v, c in cnt.items():
                if c >= 2:
                    d = 2 * c / (len(g) + size[v][k])
                    if d >= dice and d > best.get(v, 0):
                        best[v] = d
        return sorted(best.items(), key=lambda kv: (-kv[1], -self.df.get(kv[0], 0)))[:top]

    def expand(self, q):
        """→ [(variante, poids, idf retenu, synonyme ?)] : le mot, ses préfixes, ses troncatures, ses synonymes métier
        et, mot inconnu, ses rapprochements phonétiques ou fautes de frappe."""
        out = [(q, 1.0)] if q in self.df else []
        if len(q) >= 4:
            # Préfixe : mot de l'index qui commence par le mot tapé (« dropship » → « dropshipping »). Troncature : mot de
            # l'index par lequel commence le mot tapé, gardé si c'est une autre forme du même mot (« tester » → « test »)
            # ou une abréviation d'au moins 5 lettres (« comptabilité » → « compta »). En prose, un début de 4 lettres
            # n'est souvent qu'un autre mot : « bout » (boutique), « disp » (disponible), « vide » (vidéo), « jour »
            # (journal). Le code abrège vraiment en 4 lettres (« auth », « conf ») : ses index (code) les gardent toutes.
            extra = []
            for v in self.by_prefix.get(q[:3], ()):
                if v == q:
                    continue
                if v.startswith(q):
                    extra.append((v, 0.75))
                elif len(v) >= 4 and q.startswith(v) and (len(v) >= 5 or self.code or q[len(v):] in INFLEXIONS):
                    extra.append((v, 0.55))
            extra.sort(key=lambda x: (-x[1], len(x[0])))
            out += extra[:15]
        seen = {v for v, _ in out}
        syn = [s for s in SYN.get(q, ()) if s in self.df and s not in seen]  # synonymes métier : toujours
        out += [(s, 0.8) for s in syn]
        seen.update(syn)
        strong = q in self.df or any(w >= 0.75 for _, w in out)
        if not strong and self.fuzzy and len(q) >= 4:  # mot inconnu : prononciation, faute de frappe ou même famille
            ph, dl, rt = self._fuzzy_maps()  # (mots courts exclus : « mer » ≈ « met » ferait du bruit)
            cands = {v: 0.6 for v in ph.get(phon(q), ()) if v != q and v not in seen and len(v) >= 4}
            if len(q) >= 5:
                for d in deletes(q) | {q}:
                    for v in dl.get(d, ()):
                        if v != q and v not in seen and within_one(q, v):
                            cands[v] = 0.6
            if len(q) >= 6:
                for v in rt.get(root(q), ()):
                    if v != q and v not in seen:
                        cands.setdefault(v, 0.55)
            out += sorted(cands.items(), key=lambda kv: (-kv[1], -self.df.get(kv[0], 0)))[:6]
        if not out and self.subword and len(q) >= 5 and not q.isdigit():  # dernier recours : les sous-mots, poids faible
            out = [(v, SUBWORD_W) for v, _ in self.subwords(q)]
        # Un synonyme ne compte jamais plus que le mot demandé : sans plafond, le plus rare l'emporte (« boutique », dans
        # 7 souvenirs, cédait la tête à son synonyme « store », dans 3). Référence : le mot lui-même s'il est dans l'index ;
        # sinon les synonymes valent un seul terme, le plus courant d'entre eux (comme les synonymes de Lucene). Les formes
        # du mot (« commandées » pour « commande ») gardent leur poids : elles disent le même mot.
        syn = set(syn)
        ref = self.idf(q) if q in self.df else min(map(self.idf, syn)) if syn else 0.0
        return [(v, w, min(self.idf(v), ref) if v in syn else self.idf(v), v in syn) for v, w in out]

    def search(self, query, limit=10):
        """→ [{key, score, matched (nb de termes trouvés), midf (poids des termes trouvés), nq}]"""
        qterms = list(dict.fromkeys(tokenize(query)))
        if not qterms or not self.N:
            return []
        exp = {q: self.expand(q) for q in qterms}
        unseen = math.log(1 + (self.N + 0.5) / 0.5)
        qidf = {q: (max(e for _, _, e, _ in exp[q]) if exp[q] else unseen) for q in qterms}
        total = sum(qidf.values()) or 1.0
        cand = set()
        for q in qterms:
            for v, *_ in exp[q]:
                cand.update(self.post.get(v, ()))
        nms = getattr(self, "named", None) or {}
        vs = {q: {q} | {v for v, *_ in exp[q]} for q in qterms}  # formes trouvées de chaque terme (proximité, plus bas)
        results = []
        for i in cand:
            tf, dl, nm = self.tfs[i], self.lens[i], nms.get(i)
            norm = K1 * (1 - B + B * dl / self.avgdl)
            score = midf = 0.0
            matched = 0
            for q in qterms:
                best = 0.0
                for v, w, e, syn in exp[q]:
                    f = tf.get(v)
                    if f and syn and nm and v in nm:
                        f = f - nm[v] if f - nm[v] > 1e-6 else 0  # faux ami (« Microsoft Store ») : pas un synonyme
                    if f:
                        s = e * f * (K1 + 1) / (f + norm) * w
                        if s > best:
                            best = s
                if best > 0:
                    score += best
                    matched += 1
                    midf += qidf[q]
            if score > 0:
                results.append({"key": self.keys[i], "score": score, "matched": matched,
                                "midf": midf, "cov": midf / total, "nq": len(qterms), "vars": vs})
        results.sort(key=lambda r: -r["score"])
        return results[:limit]


MEMIDX_TAG = f"m5:{sys.version_info[0]}.{sys.version_info[1]}"
_LOADED = {}  # index des souvenirs déjà chargé dans ce processus : {fichier: (empreinte, index)}


def _mem_sig(brain) -> str:
    """Empreinte du savoir indexé (titres, étiquettes, contenus) : les compteurs de rappel ne l'invalident pas."""
    h = hashlib.sha1()
    for nid in sorted(brain.nodes):
        n = brain.nodes[nid]
        if n.get("status", "active") == "active":
            keys = (n.get("meta") or {}).get("keys") or ""
            h.update(f"{nid}\x1e{n['title']}\x1e{' '.join(n.get('tags') or [])}\x1e{keys}\x1e{n.get('body', '')}\x1f"
                     .encode("utf-8"))
    return h.hexdigest()


def memory_index(brain, include_archived=False, use_cache=True) -> Index:
    """Index des souvenirs, relu depuis state/memidx.bin (avec ses tables phonétiques et de fautes) tant que le
    savoir n'a pas changé : le rappel à chaque message n'a plus rien à reconstruire."""
    if include_archived or not use_cache:
        return _build_memory_index(brain, include_archived)
    from .common import STATE_DIR
    path = STATE_DIR / "memidx.bin"
    sig = _mem_sig(brain)
    hit = _LOADED.get(str(path))
    if hit and hit[0] == sig:
        return hit[1]
    try:
        with open(path, "rb") as fh:
            blob = marshal.loads(fh.read())
        if blob.get("tag") == MEMIDX_TAG and blob.get("sig") == sig:
            idx = Index.from_state(blob)
            idx._phon, idx._del, idx._root, idx._tri = blob["phon"], blob["del"], blob["root"], blob["tri"]
            idx.subword = True
            _LOADED[str(path)] = (sig, idx)
            return idx
    except Exception:
        pass
    idx = _build_memory_index(brain, False)
    ph, dl, rt = idx._fuzzy_maps()
    _LOADED[str(path)] = (sig, idx)
    try:
        blob = {"tag": MEMIDX_TAG, "sig": sig, "keys": idx.keys, "tfs": [dict(t) for t in idx.tfs], "lens": idx.lens,
                "df": dict(idx.df), "post": dict(idx.post), "pre": dict(idx.by_prefix), "phon": ph, "del": dl, "root": rt,
                "tri": idx._tri_maps(), "named": idx.named}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"memidx.{os.getpid()}.tmp")
        with open(tmp, "wb") as fh:
            fh.write(marshal.dumps(blob))
        os.replace(tmp, path)
    except Exception:
        pass
    return idx


def _build_memory_index(brain, include_archived=False) -> Index:
    docs = []
    for n in brain.nodes.values():
        if not include_archived and n.get("status", "active") != "active":
            continue
        keys = (n.get("meta") or {}).get("keys") or ""  # mots-clés, synonymes, questions types donnés à l'écriture
        docs.append((n["id"], [(n["title"], 3.0), (" ".join(n.get("tags") or []), 2.2), (keys, 1.6),
                               (n.get("body", ""), 1.0)]))
    idx = Index(docs)
    idx.subword = True
    return idx


def search_memories(brain, query, limit=8, project=None, types=None, include_archived=False,
                    expand=True, only_project=False, use_cache=True, fuse=False, today=None):
    """Recherche classée (BM25 × importance × projet courant × fraîcheur) + voisins dans le graphe.
    fuse=True (commande `q`, serveur MCP) : fusion RRF de trois canaux — texte, dates, liens et entités partagées."""
    idx = memory_index(brain, include_archived, use_cache)
    out = []
    for r in idx.search(query, limit=80):
        n = brain.nodes[r["key"]]
        if types and n["type"] not in types:
            continue
        in_project = bool(project) and (n.get("project") == project or n["id"] == project)
        if only_project and project and not in_project:
            continue
        score = r["score"] * (1 + 0.1 * (n.get("importance", 3) - 3))
        if in_project:
            score *= 1.3
        if days_since(n.get("updated")) < 14:
            score *= 1.08
        out.append(dict(r, score=round(score, 2), node=n, via=None))
    out.sort(key=lambda r: -r["score"])
    if fuse:
        return _fuse(brain, query, out, limit, project, types, include_archived, only_project, today, use_cache)
    out = out[:limit]
    if expand and out:
        seen = {r["node"]["id"] for r in out}
        extra = []
        for r in out[:3]:
            for m, rel, _ in brain.neighbors(r["node"]["id"]):
                if m["id"] in seen or m.get("status", "active") != "active":
                    continue
                if types and m["type"] not in types:
                    continue
                seen.add(m["id"])
                extra.append({"key": m["id"], "score": round(r["score"] * 0.35, 2), "matched": 0,
                              "midf": 0.0, "nq": r["nq"], "node": m, "via": f"{r['node']['id']} · {rel}"})
        out += extra[:3]
    return out


RRF_K = 60


def _node_dates(n):
    """Dates d'un souvenir : écrit le, modifié le, fin de validité, échéance, et dates citées dans son texte."""
    import datetime as _dt
    from . import dates
    out = []
    for raw in (n.get("created"), n.get("updated"), (n.get("meta") or {}).get("valid_to"),
                (n.get("meta") or {}).get("due"), (n.get("meta") or {}).get("done")):
        try:
            out.append(_dt.date.fromisoformat(str(raw)[:10]))
        except (TypeError, ValueError):
            pass
    ref = out[0] if out else None
    out += dates.dates_in(f"{n.get('title', '')}\n{n.get('body', '')}", ref)
    return out


TYPED = ("depends_on", "part_of", "uses", "fixes", "about", "contradicts")


OVERVIEW_RX = re.compile(r"(?<!\w)(o[uù] en (?:est|sont|[eê]tes|es|sommes)|on en est o[uù]|le point|point sur|"
                         r"r[ée]sum|r[ée]cap|bilan|[ée]tat d[eu]s?|avancement|quoi de neuf|du nouveau|vue d'ensemble|"
                         r"tout ce qu['’]on sait|synth[èe]se)", re.I)  # pas « fiche » : « fiches produit » est un sujet
OVERVIEW_TOKENS = {"point", "resume", "resumer", "resumes", "recap", "recapitule", "recapitulatif", "bilan", "etat",
                   "avancement", "neuf", "nouveau", "nouvelle", "synthese", "vue", "ensemble", "situation", "sait",
                   "sommes", "etes", "sont"}
SPREAD = 0.35  # couverture du meilleur souvenir (part du score qu'il prend à lui seul) en dessous de laquelle c'est épars
DATED_RX = re.compile(r"(?<!\w)(hier|demain|avant[- ]hier|apr[eè]s[- ]demain|aujourd|semaines?|mois|ann[ée]es?|trimestre|"
                      r"lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|janvier|f[ée]vrier|mars|avril|mai|juin|"
                      r"juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre|il y a \d|\d{1,2}/\d{1,2})(?!\w)", re.I)


def _covers(node, terms) -> bool:
    """Le titre (ou les étiquettes, mots-clés) d'un souvenir contient-il TOUS les termes ? → question précise."""
    head = set(tokenize(f"{node['title']} {' '.join(node.get('tags') or [])} {(node.get('meta') or {}).get('keys') or ''}"))
    return all(t in head or (len(t) >= 5 and any(h.startswith(t[:5]) for h in head)) for t in terms)


def _fiche_for(brain, query, bm25, use_cache=True):
    """Question vague (peu de termes, aucun souvenir ne la couvre à lui seul, ou « où en est… », « le point sur… »)
    → fiche de la communauté qui porte l'essentiel des résultats, à placer en tête. Sinon None."""
    if DATED_RX.search(query):
        return None  # question datée (« le bilan du mois dernier ») : réponse par les dates, pas par une fiche
    cue = bool(OVERVIEW_RX.search(query))
    words = list(dict.fromkeys(tokenize(query)))
    topic = [t for t in words if not (cue and t in OVERVIEW_TOKENS)]  # « le point sur la boutique » → « boutique »
    top = bm25[:10]
    if not topic or len(topic) > (3 if cue else 2) or len(top) < (2 if cue else 4):
        return None
    total = sum(r["score"] for r in top) or 1.0
    first = top[0]["node"]
    if cue and len(words) > len(topic) and first["type"] != "project" and _covers(first, words):
        return None  # « le bilan des ventes » : le mot-signal fait partie du titre d'un souvenir, qu'il nomme
    if not cue:
        if top[0]["score"] / total >= SPREAD:
            return None  # un souvenir prend l'essentiel du score : il répond à lui seul
        if first["type"] != "project" and _covers(first, topic) \
                and sum(1 for r in top if _covers(r["node"], topic)) <= 2:
            return None  # son titre dit exactement la question (et ce n'est pas le nom d'un sujet partagé par beaucoup)
    from . import fiches, graph
    an = graph.ensure(brain, write=use_cache)
    mass, count = {}, {}
    for r in top:
        c = an.get("comm", {}).get(r["node"]["id"])
        if c is not None:
            mass[c] = mass.get(c, 0.0) + r["score"]
            count[c] = count.get(c, 0) + 1
    if not mass:
        return None
    # Un gros projet se découpe en plusieurs communautés (boutique : thème, produits, SEO…) : le seuil se juge sur le
    # sujet entier (communautés du même projet réunies), la fiche reste celle de la plus lourde.
    proj = {c["id"]: c.get("project") for c in an.get("communities", [])}
    subj = lambda c: proj.get(c) or f"#{c}"
    smass, scount = {}, {}
    for c in mass:
        smass[subj(c)] = smass.get(subj(c), 0.0) + mass[c]
        scount[subj(c)] = scount.get(subj(c), 0) + count[c]
    s = max(smass, key=lambda k: (smass[k], k))
    cid = max((c for c in mass if subj(c) == s), key=lambda c: (mass[c], -c))
    if smass[s] / total < (0.35 if cue else 0.45) or scount[s] < (2 if cue else 3):
        return None
    fs = fiches.ensure(brain, an, write=use_cache)
    f = fs.get(cid)
    if not f or not f["lines"]:
        return None
    others = [fs[c] for c in sorted(mass, key=lambda c: -mass[c]) if c != cid and c in fs and mass[c] / total >= 0.15][:3]
    node = {"id": f"fiche-{cid}", "type": "fiche", "title": f"Fiche « {f['label']} »", "body": fiches.text(f, others),
            "tags": [], "status": "active", "source": "verifie", "meta": {}}
    return {"key": node["id"], "score": round(mass[cid], 2), "matched": len(topic), "midf": 0.0,
            "cov": round(mass[cid] / total, 2), "nq": len(topic), "node": node, "via": "fiche", "fiche": f}


def _fuse(brain, query, bm25, limit, project, types, include_archived, only_project, today, use_cache=True):
    """Recherche fusionnée (commande `q`, serveur MCP) :
    - texte : BM25 tolérant (fautes, phonétique, synonymes) ;
    - dates, fusionnées par rangs (RRF k=60, façon Hindsight / Zep : aucun score à calibrer) : quand la question vise
      une période (« hier », « le 12/11 », « il y a 6 semaines »), les souvenirs écrits, modifiés ou datés dans cette
      plage remontent ;
    - deuxième saut : juste après l'un des deux premiers résultats, le souvenir qui partage avec lui un nom propre rare
      ou un lien typé (« coffret Hōjicha » → atelier Sato → « l'atelier Sato ferme en août ») ;
    - fiche de synthèse (façon Zep / MemOS) : une question large (« où en est la boutique ? ») reçoit d'abord la fiche de
      la communauté dominante, puis les souvenirs (la fiche ne prend pas de place dans la limite)."""
    from . import dates
    from .reconcile import entities

    def eligible(n):
        if not include_archived and n.get("status", "active") != "active":
            return False
        if types and n["type"] not in types:
            return False
        if only_project and project and n.get("project") != project and n["id"] != project:
            return False
        return True

    by_id = {r["node"]["id"]: r for r in bm25}
    order = [r["node"]["id"] for r in bm25]
    via = {}
    rng = dates.query_range(query, today)
    if rng:
        start, end = rng
        mid = start + (end - start) / 2
        hits = []
        for n in brain.nodes.values():
            if not eligible(n):
                continue
            ds = [d for d in _node_dates(n) if start <= d <= end]
            if ds:
                lex = by_id[n["id"]]["score"] if n["id"] in by_id else 0.0
                hits.append((-lex, min(abs((d - mid).days) for d in ds), -len(ds), n["id"]))
        hits.sort()
        fused = {}
        for ids in (order, [h[-1] for h in hits]):
            for rank, nid in enumerate(ids):
                fused[nid] = fused.get(nid, 0.0) + 1.0 / (RRF_K + rank + 1)
        for h in hits:
            via[h[-1]] = "texte + date" if h[-1] in by_id else "date"
        order = sorted(fused, key=lambda i: -fused[i])
    ranked, seen_titles = [], []
    for nid in order:
        n = brain.nodes.get(nid)
        if n is None or not eligible(n):
            continue
        toks = set(tokenize(f"{n['title']} {n.get('body', '')}"))
        if any(len(toks & t) / max(1, len(toks | t)) >= 0.85 for t in seen_titles):
            continue  # MMR : pas deux fois le même souvenir sous deux formes (titre ET contenu quasi identiques)
        seen_titles.append(toks)
        ranked.append(nid)
        if len(ranked) >= limit:
            break
    final, ents, df = [], None, {}
    for pos, nid in enumerate(ranked):
        if len(final) >= limit:
            break
        if nid in final:
            continue
        final.append(nid)
        if pos >= 2 or len(final) >= limit:
            continue
        if ents is None:
            ents = {n["id"]: entities(f"{n['title']}\n{n.get('body', '')}") for n in brain.nodes.values()
                    if eligible(n) or n["id"] in ranked}
            for es in ents.values():
                for e in es:
                    df[e] = df.get(e, 0) + 1
        cands, strength = {}, {}
        for m, rel, _ in brain.neighbors(nid):
            if rel in TYPED and m["id"] in ents:
                cands[m["id"]] = (2.0, rel.replace("_", " "))
        for e in sorted(ents.get(nid, ())):  # trié : un ensemble se parcourt dans un ordre qui change à chaque lancement
            if df.get(e, 0) in (2, 3):
                for other, es in ents.items():
                    if other != nid and e in es:
                        sc = 1.5 if df[e] == 2 else 0.7
                        strength[other] = strength.get(other, 0.0) + sc
                        if sc > cands.get(other, (0, ""))[0]:
                            cands[other] = (sc, e)
        # Ex aequo (départagés avant par l'ordre d'insertion : le lien changeait d'un lancement à l'autre pour 42 questions
        # sur 62) : le plus de noms rares partagés, puis le même projet, puis le plus proche de la question, puis l'id.
        home = brain.nodes[nid].get("project") or (nid if brain.nodes[nid]["type"] == "project" else None)

        def tie(x):
            other = brain.nodes.get(x[1]) or {}
            same = bool(home) and home in (other.get("project"), x[1])
            return -x[0], -strength.get(x[1], 0.0), not same, -(by_id[x[1]]["score"] if x[1] in by_id else 0.0), x[1]

        best = sorted(((sc, other, why) for other, (sc, why) in cands.items()
                       if other not in final and other not in ranked[:limit]), key=tie)
        if best and best[0][0] >= 0.7:
            final.append(best[0][1])
            via[best[0][1]] = f"lien ({best[0][2]})"
    out = []
    for nid in final:
        n = brain.nodes[nid]
        base = by_id.get(nid) or {"key": nid, "score": 0.0, "matched": 0, "midf": 0.0, "cov": 0.0,
                                  "nq": len(tokenize(query)), "node": n}
        out.append(dict(base, via=via.get(nid)))
    if not rng and not types and not include_archived and bm25:  # pas de fiche pour une question datée ou filtrée
        try:
            f = _fiche_for(brain, query, bm25, use_cache)
        except Exception as exc:
            from .common import log
            log(f"fiche : {exc!r}")
            f = None
        if f:
            out.insert(0, f)
    return out


LONG_BODY, LONG_COV = 400, 0.62
NEAR = 12  # mots : au-delà, deux termes du message ne parlent plus de la même chose dans le souvenir


def _near(node, vs, window=NEAR) -> bool:
    """Deux termes différents du message à moins de `window` mots l'un de l'autre dans le souvenir ? Vrai aussi quand
    on ne retrouve pas deux termes (forme approchée hors texte) : dans le doute, la règle d'avant décide.
    « qui a gagné la coupe du monde » ↛ « tout le monde » … 60 mots … « connecteurs coupés »."""
    last, found = {}, set()
    for i, t in enumerate(tokenize(f"{node['title']} {node.get('body') or ''}")):
        for q, forms in vs.items():
            if t in forms:
                found.add(q)
                if any(q2 != q and i - j <= window for q2, j in last.items()):
                    return True
                last[q] = i
    return len(found) < 2


def _head_hit(node, qterms) -> bool:
    head = set(tokenize(f"{node['title']} {' '.join(node.get('tags') or [])} {(node.get('meta') or {}).get('keys') or ''}"))
    return any(q in head or (len(q) >= 5 and any(h.startswith(q[:5]) for h in head)) for q in qterms)


def accept_recall(r, min_cov, min_score=0.0, query=None) -> bool:
    """Filtre anti-bruit du rappel automatique : assez de termes du message ET une bonne part de leur poids
    (un seul mot en commun avec un long message ne suffit jamais). Un long souvenir attrape des mots au hasard
    (« coupe du monde » → « coupé ») : sans couverture forte, son titre ou ses étiquettes doivent parler du sujet."""
    return not recall_refusal(r, min_cov, min_score, query)


def recall_refusal(r, min_cov, min_score=0.0, query=None) -> str:
    """Pourquoi le filtre du rappel écarte ce résultat ('' : accepté) : la règle d'`accept_recall` elle-même, donc
    le diagnostic (`brain recall --pourquoi`) ne peut pas s'en écarter."""
    nq = r["nq"]
    need = 1 if nq == 1 else 2 if nq <= 4 else 3
    if r["matched"] < need:
        return f"trop peu de mots du message retrouvés ({r['matched']}/{nq}, il en faut {need})"
    if r.get("cov", 0) < min_cov:
        return f"couverture {r.get('cov', 0):.3f} < min_cov {min_cov} : les mots retrouvés pèsent peu dans le message"
    if r["score"] < min_score:
        return f"score {r['score']} < min_score {min_score}"
    node = r.get("node")
    if query is not None and node is not None and len(node.get("body") or "") >= LONG_BODY and r.get("cov", 0) < LONG_COV:
        return "" if _head_hit(node, set(tokenize(query))) else \
            f"long souvenir, couverture {r.get('cov', 0):.3f} < {LONG_COV} et ni le titre ni les mots-clés ne parlent du sujet"
    # Termes épars : message pas entièrement retrouvé, titre muet, et ses mots semés loin les uns des autres → coïncidence
    # (342 rappels réels rejoués : 9 inutiles coupés, aucun utile perdu ; tous les mots retrouvés → la règle d'avant).
    if query is not None and node is not None and 2 <= r["matched"] < r["nq"] and r.get("vars") \
            and not _head_hit(node, set(tokenize(query))) and not _near(node, r["vars"]):
        return f"mots épars : retrouvés à plus de {NEAR} mots l'un de l'autre, titre muet (coïncidence probable)"
    return ""
