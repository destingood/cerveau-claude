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

from .common import days_since, fold, tokenize
from .lexicon import INFLEXIONS, SYN, deletes, faux_amis, other_sense, phon, root, within_one

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
    sig = None  # empreinte du savoir de l'index des souvenirs gardé (memory_index) ; None : construit à la volée
    # Index des souvenirs relu de memidx.bin : {mot: (n° des documents, fréquences)} en octets, décodés au premier usage
    # de chaque mot (posting). Avant, relire les fréquences de chaque souvenir (un dictionnaire par souvenir) prenait
    # 12 ms à chaque message à 3 000 souvenirs, 45 ms à 10 000 ; une recherche ne lit que les mots de la question.
    _pk = None

    def __init__(self, docs=()):
        self.keys, self.tfs, self.named = [], [], {}
        for key, fields in docs:
            tf, nm = self.doc(fields)
            if nm:
                self.named[len(self.keys)] = dict(nm)
            self.keys.append(key)
            self.tfs.append(tf)
        self._finalize()

    @staticmethod
    def doc(fields) -> tuple:
        """Champs d'un document [(texte, poids)] → (fréquences pondérées de ses mots, de ses faux amis) : Counter."""
        tf, nm = Counter(), Counter()
        for text, weight in fields:
            if text:
                for tok in tokenize(text):
                    tf[tok] += weight
                for tok in faux_amis(text):  # faux amis (« Microsoft Store ») : occurrences ignorées par les synonymes
                    nm[tok] += weight
        return tf, nm

    @classmethod
    def from_tfs(cls, keys, tfs):
        obj = cls.__new__(cls)
        obj.keys, obj.tfs, obj.named = list(keys), list(tfs), {}
        obj._finalize()
        return obj

    @classmethod
    def from_state(cls, d):
        """Index déjà calculé (cache marshal) : aucune reconstruction. `pk` (index des souvenirs) : les fréquences
        restent en octets jusqu'à ce qu'une recherche en ait besoin."""
        obj = cls.__new__(cls)
        obj.keys, obj.lens = d["keys"], d["lens"]
        obj.N = len(obj.keys)
        obj.avgdl = (sum(obj.lens) / obj.N) if obj.N else 1.0
        obj.df, obj.by_prefix = d["df"], d["pre"]
        obj.named = d.get("named") or {}
        if d.get("pk") is not None:
            obj._pk, obj._dec, obj._tfm = d["pk"], {}, {}
        else:
            obj.tfs, obj.post = d["tfs"], d["post"]
        return obj

    def __getattr__(self, name):
        """Index gardé (_pk) : les tables entières (fréquences de chaque document, documents de chaque mot), refaites
        seulement si quelqu'un les demande — la recherche, elle, passe par posting()."""
        if name in ("tfs", "post") and self._pk is not None:
            tfs, post = [{} for _ in self.keys], {}
            for tok in self._pk:
                docs, vals = self.posting(tok)
                post[tok] = docs
                for i, f in zip(docs, vals):
                    tfs[i][tok] = f
            self.tfs, self.post = tfs, post
            return tfs if name == "tfs" else post
        raise AttributeError(name)

    def posting(self, tok) -> tuple:
        """(documents qui contiennent `tok`, dans l'ordre ; sa fréquence pondérée dans chacun)."""
        if self._pk is None:
            docs = self.post.get(tok, ())
            return docs, [self.tfs[i][tok] for i in docs]
        got = self._dec.get(tok)
        if got is None:
            raw = self._pk.get(tok)
            got = self._dec[tok] = (memoryview(raw[0]).cast("I").tolist(), memoryview(raw[1]).cast("d").tolist()) \
                if raw else ((), ())
        return got

    def docs(self, tok):
        """Documents qui contiennent `tok`, dans l'ordre."""
        return self.post.get(tok, ()) if self._pk is None else self.posting(tok)[0]

    def doc_tf(self, i, toks) -> dict:
        """Fréquences pondérées des mots `toks` dans le document i ({mot: fréquence}, mots absents omis ; index construit
        en mémoire : toutes celles du document)."""
        if self._pk is None:
            return self.tfs[i]
        out = {}
        for tok in toks:
            m = self._tfm.get(tok)
            if m is None:
                m = self._tfm[tok] = dict(zip(*self.posting(tok)))
            f = m.get(i)
            if f is not None:
                out[tok] = f
        return out

    def _query_tfs(self, exp) -> dict:
        """Index gardé : {document: {variante: fréquence}} des seules variantes de la requête (`exp`, voir search)."""
        out = {}
        for vs in exp.values():
            for v, *_ in vs:
                docs, vals = self.posting(v)
                for i, f in zip(docs, vals):
                    d = out.get(i)
                    if d is None:
                        out[i] = {v: f}
                    else:
                        d[v] = f
        return out

    def packed(self) -> dict:
        """{mot: (n° des documents, fréquences)} en octets (voir _pk) : l'index des souvenirs tel que memidx.bin le garde."""
        from array import array
        vals = {}
        for tf in self.tfs:  # (dans l'ordre des documents, comme post)
            for tok, f in tf.items():
                got = vals.get(tok)
                if got is None:
                    vals[tok] = [f]
                else:
                    got.append(f)
        return {tok: (array("I", docs).tobytes(), array("d", vals[tok]).tobytes()) for tok, docs in self.post.items()}

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
        return [x[:4] for x in self.variants(q)]

    def variants(self, q, synonyms=True):
        """expand(), et pour chaque variante son degré d'approximation : 0 telle quelle (le mot, un préfixe, une forme,
        un synonyme), 1 approchée (prononciation, faute de frappe, même famille d'un mot absent de l'index), 2 sous-mots
        (dernier recours : quelques trigrammes en commun). `synonyms` faux : sans les synonymes métier (mot employé dans
        son autre sens, lexicon.other_sense)."""
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
        syn = [s for s in SYN.get(q, ()) if s in self.df and s not in seen] if synonyms else []  # synonymes métier
        out += [(s, 0.8) for s in syn]
        seen.update(syn)
        strong = q in self.df or any(w >= 0.75 for _, w in out)
        if strong and self.fuzzy and not self.code and len(q) >= 6:
            # Mot connu : les autres mots de sa famille aussi (« surveille » → « surveillance », « publie » →
            # « publication ») ; avant, la famille ne servait qu'aux mots absents de l'index.
            fam = sorted((v for v in self._fuzzy_maps()[2].get(root(q), ()) if v != q and v not in seen),
                         key=lambda v: (-self.df.get(v, 0), v))[:4]
            out += [(v, 0.55) for v in fam]
            seen.update(fam)
        approx = []
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
            approx = sorted(cands.items(), key=lambda kv: (-kv[1], -self.df.get(kv[0], 0)))[:6]
            out += approx
        sub = not out and self.subword and len(q) >= 5 and not q.isdigit()
        if sub:  # dernier recours : les sous-mots, poids faible
            out = approx = [(v, SUBWORD_W) for v, _ in self.subwords(q)]
        # Un synonyme ne compte jamais plus que le mot demandé : sans plafond, le plus rare l'emporte (« boutique », dans
        # 7 souvenirs, cédait la tête à son synonyme « store », dans 3). Référence : le mot lui-même s'il est dans l'index ;
        # sinon les synonymes valent un seul terme, le plus courant d'entre eux (comme les synonymes de Lucene). Les formes
        # du mot (« commandées » pour « commande ») gardent leur poids : elles disent le même mot.
        syn, approx = set(syn), {v for v, _ in approx}
        ref = self.idf(q) if q in self.df else min(map(self.idf, syn)) if syn else 0.0
        level = 2 if sub else 1
        return [(v, w, min(self.idf(v), ref) if v in syn else self.idf(v), v in syn, level if v in approx else 0)
                for v, w in out]

    def search(self, query, limit=10):
        """→ [{key, score, matched (nb de termes trouvés), strong (dont trouvés tels quels : mot, préfixe, forme,
        synonyme ; pas une forme approchée), loose (dont trouvés par leurs sous-mots seulement), midf (poids des termes
        trouvés), cov, nq, unknown (termes qu'aucun document ne contient tels quels), vars}]"""
        qterms = list(dict.fromkeys(tokenize(query)))
        if not qterms or not self.N:
            return []
        plain = other_sense(qterms)  # « le port 8080 » : pas les synonymes de la livraison
        exp = {q: self.variants(q, synonyms=q not in plain) for q in qterms}
        unseen = math.log(1 + (self.N + 0.5) / 0.5)
        qidf = {q: (max(x[2] for x in exp[q]) if exp[q] else unseen) for q in qterms}
        total = sum(qidf.values()) or 1.0
        unknown = sum(1 for q in qterms if all(x[4] for x in exp[q]))
        cand = set()
        for q in qterms:
            for v, *_ in exp[q]:
                cand.update(self.docs(v))
        tfs = self.tfs if self._pk is None else self._query_tfs(exp)
        nms = getattr(self, "named", None) or {}
        vs = {q: {q} | {v for v, *_ in exp[q]} for q in qterms}  # formes trouvées de chaque terme (proximité, plus bas)
        results = []
        for i in cand:
            tf, dl, nm = tfs[i], self.lens[i], nms.get(i)
            norm = K1 * (1 - B + B * dl / self.avgdl)
            score = midf = 0.0
            matched = strong = loose = 0
            for q in qterms:
                best, near = 0.0, 0
                for v, w, e, syn, fz in exp[q]:
                    f = tf.get(v)
                    if f and syn and nm and v in nm:
                        f = f - nm[v] if f - nm[v] > 1e-6 else 0  # faux ami (« Microsoft Store ») : pas un synonyme
                    if f:
                        s = e * f * (K1 + 1) / (f + norm) * w
                        if s > best:
                            best, near = s, fz
                if best > 0:
                    score += best
                    matched += 1
                    strong += not near
                    loose += near == 2
                    midf += qidf[q]
            if score > 0:
                results.append({"key": self.keys[i], "score": score, "matched": matched, "strong": strong, "loose": loose,
                                "midf": midf, "cov": midf / total, "nq": len(qterms), "unknown": unknown, "vars": vs})
        results.sort(key=lambda r: -r["score"])
        return results[:limit]


# m6 : stem() garde « refus », faux amis du port ; m7 : fréquences en octets (Index._pk), dans l'ordre des octets d'ici
MEMIDX_TAG = f"m7:{sys.version_info[0]}.{sys.version_info[1]}:{sys.byteorder[0]}"
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


def knowledge_sig(brain) -> str:
    """_mem_sig(brain) sans relire tout le savoir à chaque message : calculée une fois par cerveau chargé (pas modifié
    depuis : Brain.dirty l'efface), et d'un processus à l'autre reprise de state/memidx.key tant que graph.json est le
    même fichier, octet pour octet (Brain.stamp : taille, date, n° de fichier, CRC). Un compteur de rappel écrit dans
    graph.json change l'empreinte du fichier : l'empreinte du savoir est alors recalculée une fois, puis reprise."""
    sig = getattr(brain, "_memsig", None)
    if sig:
        return sig
    from .common import STATE_DIR, read_json, write_json
    stamp, key = getattr(brain, "stamp", None), STATE_DIR / "memidx.key"
    known = read_json(key, None) if stamp else None
    if isinstance(known, dict) and known.get("stamp") == stamp and known.get("tag") == MEMIDX_TAG \
            and isinstance(known.get("sig"), str):
        sig = known["sig"]
    else:
        sig = _mem_sig(brain)
        if stamp:
            try:
                write_json(key, {"tag": MEMIDX_TAG, "stamp": stamp, "sig": sig}, indent=None)
            except OSError:
                pass
    try:
        brain._memsig = sig
    except AttributeError:
        pass
    return sig


def memory_index(brain, include_archived=False, use_cache=True) -> Index:
    """Index des souvenirs, relu depuis state/memidx.bin (avec ses tables phonétiques et de fautes) tant que le
    savoir n'a pas changé : le rappel à chaque message n'a plus rien à reconstruire."""
    if include_archived or not use_cache:
        return _build_memory_index(brain, include_archived)
    from .common import STATE_DIR
    path = STATE_DIR / "memidx.bin"
    sig = knowledge_sig(brain)
    hit = _LOADED.get(str(path))
    if hit and hit[0] == sig:
        return hit[1]
    try:
        with open(path, "rb") as fh:
            blob = marshal.loads(fh.read())
        if blob.get("tag") == MEMIDX_TAG and blob.get("sig") == sig:
            idx = Index.from_state(blob)
            idx._phon, idx._del, idx._root, idx._tri = blob["phon"], blob["del"], blob["root"], blob["tri"]
            idx.subword, idx.sig = True, sig
            _LOADED[str(path)] = (sig, idx)
            return idx
    except Exception:
        pass
    # Savoir changé : l'index est refait, mais un souvenir dont les champs n'ont pas bougé n'est pas redécoupé (ses mots
    # sont gardés à côté, dans memidx-docs.bin). Avant, chaque ajout faisait tout redécouper au message suivant :
    # 250 ms à 3 000 souvenirs, 1,2 s à 10 000.
    words = path.with_name(DOCS_FILE)
    try:
        with open(words, "rb") as fh:
            got = marshal.loads(fh.read())
        reuse = got["docs"] if isinstance(got, dict) and got.get("tag") == MEMIDX_TAG else {}
    except Exception:
        reuse = {}
    keep = {}
    idx = _build_memory_index(brain, False, reuse=reuse, keep=keep)
    ph, dl, rt = idx._fuzzy_maps()
    idx.sig = sig  # (même savoir : les dates citées par les souvenirs se gardent avec lui, voir _cited)
    _LOADED[str(path)] = (sig, idx)
    try:
        blob = {"tag": MEMIDX_TAG, "sig": sig, "keys": idx.keys, "pk": idx.packed(), "lens": idx.lens,
                "df": dict(idx.df), "pre": dict(idx.by_prefix), "phon": ph, "del": dl, "root": rt,
                "tri": idx._tri_maps(), "named": idx.named}
        path.parent.mkdir(parents=True, exist_ok=True)
        for target, data in ((path, blob), (words, {"tag": MEMIDX_TAG, "docs": keep})):
            tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
            with open(tmp, "wb") as fh:
                fh.write(marshal.dumps(data))
            os.replace(tmp, target)
    except Exception:
        pass
    return idx


DOCS_FILE = "memidx-docs.bin"  # mots de chaque souvenir indexé : {id: (empreinte de ses champs, fréquences, faux amis)}


def _build_memory_index(brain, include_archived=False, reuse=None, keep=None) -> Index:
    """Index des souvenirs (titre, étiquettes, mots-clés, contenu). `reuse` : {id: (empreinte des champs, fréquences, faux
    amis)} d'un index précédent — un souvenir aux champs inchangés n'est pas redécoupé, l'index est le même ; `keep` :
    rempli de même pour le suivant."""
    keys, tfs, named = [], [], {}
    for n in brain.nodes.values():
        if not include_archived and n.get("status", "active") != "active":
            continue
        meta_keys = (n.get("meta") or {}).get("keys") or ""  # mots-clés, synonymes, questions types donnés à l'écriture
        fields = [(n["title"], 3.0), (" ".join(n.get("tags") or []), 2.2), (meta_keys, 1.6), (n.get("body", ""), 1.0)]
        fp = hit = None
        if reuse is not None or keep is not None:
            fp = hashlib.sha1("".join(f"{len(t)}:{t}" for t, _ in fields).encode("utf-8", "surrogatepass")).digest()
            hit = (reuse or {}).get(n["id"])
        if hit is not None and hit[0] == fp:
            tf, nm = hit[1], hit[2]
        else:
            tf, nm = Index.doc(fields)
            tf, nm = dict(tf), dict(nm)
        if keep is not None:
            keep[n["id"]] = (fp, tf, nm)
        if nm:
            named[len(keys)] = nm
        keys.append(n["id"])
        tfs.append(tf)
    idx = Index.from_tfs(keys, tfs)
    idx.named = named
    idx.subword = True
    return idx


def valid_today(n, today=None) -> bool:
    """Souvenir vrai ce jour-là d'après son début et sa fin écrits (temps.py, étape 12) : encore actif mais échu, ou pas
    encore commencé, il n'est pas rappelé (`--archived` le montre). Sans date écrite, rien à regarder."""
    meta = n.get("meta")
    if not meta or not (meta.get("valid_from") or meta.get("valid_to")):
        return True
    import datetime as _dt
    from .temps import valid_on
    return valid_on(n, (today or _dt.date.today()).isoformat())


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
        if not include_archived and not valid_today(n, today):
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
                if m["id"] in seen or m.get("status", "active") != "active" or not valid_today(m, today):
                    continue
                if types and m["type"] not in types:
                    continue
                if only_project and project and m.get("project") != project and m["id"] != project:
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
    from . import dates, noms

    def eligible(n):
        if not include_archived and (n.get("status", "active") != "active" or not valid_today(n, today)):
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
        if ents is None:  # noms de chaque souvenir : l'index nom → souvenirs gardé (noms.py), pas tout relu
            tab = noms.table(brain, use_cache)
            ents = {n["id"]: tab.get(n["id"], noms.NONE)[1] for n in brain.nodes.values()
                    if eligible(n) or n["id"] in ranked}
            who = {}
            for i, es in ents.items():
                for e in es:
                    df[e] = df.get(e, 0) + 1
                    who.setdefault(e, []).append(i)
        cands, strength = {}, {}
        for m, rel, _ in brain.neighbors(nid):
            if rel in TYPED and m["id"] in ents:
                cands[m["id"]] = (2.0, rel.replace("_", " "))
        for e in sorted(ents.get(nid, ())):  # trié : un ensemble se parcourt dans un ordre qui change à chaque lancement
            if df.get(e, 0) in (2, 3):
                for other in who[e]:
                    if other != nid:
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


_MONTHS = ("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre", "novembre",
           "decembre")
_MONTH_IN_TEXT = re.compile(r"\b(" + "|".join(_MONTHS) + r")\b(?:\s+(?:de\s+|d')?(\d{4}))?")
DATED_TOPIC = 3  # mots du sujet, au plus, d'une question datée : au-delà, la date n'est qu'un détail du message
# Sans date chiffrée ni nom de mois, un texte ne cite aucune période : ni fold() ni analyse (dates_in, _month_spans).
# Toujours plus large que ces deux-là, jamais plus étroit (abréviations « oct. », tirets longs que fold() redresse).
_MAYBE_DATED = re.compile(r"\d[/\-–−]\d|\b(?:janv(?:ier)?|f[ée]v(?:r(?:ier)?)?|mars|avr(?:il)?|mai|juin|juil(?:let)?|"
                          r"ao[uû]t|sept(?:embre)?|oct(?:obre)?|nov(?:embre)?|d[ée]c(?:embre)?)\b", re.I)


def _month_spans(text, ref) -> list:
    """Mois cités dans un texte (« Octobre 2026 : 6 480 € de ventes », « à lancer en janvier ») → [(1er, dernier jour)].
    Sans année : l'occurrence la plus proche de `ref`, la date où le souvenir a été écrit."""
    import datetime as _dt
    out = []
    for m in _MONTH_IN_TEXT.finditer(fold(text or "")):
        mo = _MONTHS.index(m.group(1)) + 1
        years = [int(m.group(2))] if m.group(2) else [ref.year - 1, ref.year, ref.year + 1]
        y = min(years, key=lambda y: abs((_dt.date(y, mo, 15) - ref).days))
        out.append((_dt.date(y, mo, 1), _dt.date(y + (mo == 12), mo % 12 + 1, 1) - _dt.timedelta(days=1)))
    return out


class _Cited(dict):
    """{id: (jour de référence, [(début, fin)] en jours ordinaux)} : les périodes que cite le texte de chaque souvenir."""
    changed = False


CITED_FILE = "memidx-dates.bin"


def _cited(idx):
    """Périodes déjà lues dans le texte des souvenirs (_Cited), gardées à côté de l'index (state/memidx-dates.bin) pour le
    même savoir : le texte d'un souvenir ne change pas sans changer l'empreinte de l'index, et sa date de référence (écrit
    le) est revérifiée à chaque fois. Avant, une question datée relisait les dates de tous les souvenirs du sujet (+40 ms
    à 3 000 souvenirs). None : index construit à la volée, rien à garder."""
    if idx.sig is None:
        return None
    got = getattr(idx, "_cited", None)
    if got is None:
        from .common import STATE_DIR
        got = _Cited()
        try:
            with open(STATE_DIR / CITED_FILE, "rb") as fh:
                blob = marshal.loads(fh.read())
            if blob.get("tag") == MEMIDX_TAG and blob.get("sig") == idx.sig:
                got.update(blob["cited"])
        except Exception:
            pass
        idx._cited = got
    return got


def _keep_cited(idx, cited) -> None:
    from .common import STATE_DIR
    try:
        path = STATE_DIR / CITED_FILE
        tmp = path.with_name(f"{CITED_FILE}.{os.getpid()}.tmp")
        with open(tmp, "wb") as fh:
            fh.write(marshal.dumps({"tag": MEMIDX_TAG, "sig": idx.sig, "cited": dict(cited)}))
        os.replace(tmp, path)
        cited.changed = False
    except Exception:
        pass


def _periods(n, cited=None) -> tuple:
    """→ (périodes dont parle le souvenir : jours et mois cités, échéance, fin de validité ; jours où il a été écrit).
    `cited` : périodes déjà lues dans les textes (_cited), reprises si la date de référence n'a pas bougé, complétées
    sinon."""
    import datetime as _dt
    from . import dates

    def day(raw):
        try:
            return _dt.date.fromisoformat(str(raw)[:10])
        except (TypeError, ValueError):
            return None

    written = [d for d in (day(n.get("created")), day(n.get("updated"))) if d]
    ref = written[0] if written else _dt.date.today()
    hit = cited.get(n["id"]) if cited is not None and written else None  # (sans date d'écriture : aujourd'hui, à relire)
    if hit is not None and hit[0] == ref.toordinal():
        about = [(_dt.date.fromordinal(a), _dt.date.fromordinal(b)) for a, b in hit[1]]
    else:
        text = f"{n.get('title', '')}\n{n.get('body', '')}"
        about = [(d, d) for d in dates.dates_in(text, ref)] + _month_spans(text, ref) if _MAYBE_DATED.search(text) else []
        if cited is not None and written:
            cited[n["id"]] = (ref.toordinal(), [(a.toordinal(), b.toordinal()) for a, b in about])
            cited.changed = True
    meta = n.get("meta") or {}
    about += [(d, d) for d in (day(meta.get(k)) for k in ("valid_to", "due", "done")) if d]
    return about, written


def undated(query) -> str:
    """La question sans ses mots de date (« combien on a vendu le mois dernier » → « vendu »)."""
    from .observations import _WHEN
    return " ".join(t for t in tokenize(DATED_RX.sub(" ", query or "")) if t not in _WHEN and not t.isdigit())


def dated_recall(brain, raw, query, project=None, today=None, limit=3, use_cache=True) -> list:
    """Rappel d'une question datée courte (« qu'est-ce qui s'est passé la semaine dernière pour ma recherche d'emploi ? »,
    « combien on a vendu le mois dernier ? », « qu'est-ce que j'ai noté hier sur la chaîne ? ») : le hook n'a pas le canal
    des dates de `q`, et ses mots de date comptaient comme des mots que le souvenir ne contenait pas. → les souvenirs de
    cette période (`raw` : le message, avec ses nombres) qui parlent du sujet (`query` sans les mots de date : un mot
    trouvé tel quel dans le souvenir ou dans le titre de son projet) ; sans autre sujet que la date, ceux du projet
    courant. Un souvenir parle des dates qu'il cite (jour, mois, échéance), sinon de celle où il a été écrit : ceux qui
    citent la période passent d'abord, et un souvenir écrit pendant la période mais qui en cite une autre (le chiffre de
    septembre noté début octobre) ne répond pas à « le mois dernier ». → [résultat (via « date »)]"""
    from . import dates
    rng = dates.query_range(raw, today)
    if not rng:
        return []
    start, end = rng
    topic = undated(query)
    terms = list(dict.fromkeys(tokenize(topic)))
    if len(terms) > DATED_TOPIC:
        return []
    idx = memory_index(brain, use_cache=use_cache)
    read = _cited(idx)  # périodes déjà lues dans les textes
    hits = {r["key"]: r for r in idx.search(topic, limit=10 ** 6)} if terms else {}
    forms = {t: {t} | {v for v, _, _, _, approx in idx.variants(t) if not approx} for t in terms}
    holds = {f: set(idx.docs(f)) for fs in forms.values() for f in fs}  # documents de chaque forme
    pos = {k: i for i, k in enumerate(idx.keys)}
    span = (end - start).days + 2  # un mois cité ne dit rien d'un jour (« en novembre » n'est pas « hier »)
    mid = start + (end - start) / 2
    cands, homes = [], {}
    for n in brain.active():
        if n["type"] == "project" or not valid_today(n, today):
            continue
        # Le sujet d'abord, les dates ensuite : le premier tri ne coûte que des recherches dans l'index (avant : les dates
        # de chacun des 3 000 souvenirs analysées, 170 ms de plus par question datée).
        if terms:  # la moitié au moins des mots du sujet, dans le souvenir ou dans le titre de son projet
            i = pos.get(n["id"])
            pid = n.get("project")
            if pid not in homes:
                home = brain.nodes.get(pid) if pid else None
                homes[pid] = set(tokenize(home["title"])) if home else set()
            title = homes[pid]
            if 2 * sum(1 for fs in forms.values() if any(i in holds[f] or f in title for f in fs)) < len(terms):
                continue
        elif project and n.get("project") != project:
            continue
        about, written = _periods(n, read)
        cited = [a + (b - a) / 2 for a, b in about if a <= end and b >= start and (b - a).days <= span]
        when = [d for d in written if start <= d <= end]
        if not cited and not when:
            continue
        own = hits.get(n["id"])
        cands.append((not cited, bool(about) and not cited, -(own["score"] if own else 0.0), n.get("project") != project,
                      min(abs((d - mid).days) for d in cited or when), n["id"], own, n))
    if read is not None and read.changed:
        _keep_cited(idx, read)
    if any(not c[0] for c in cands):
        cands = [c for c in cands if not c[1]]
    cands.sort(key=lambda c: c[:6])
    return [dict(c[6] or {"key": c[7]["id"], "score": 0.0, "matched": 0, "nq": len(terms)}, node=c[7], via="date")
            for c in cands[:limit]]


# Filtre du rappel : dans search_filtre.py (découpage de l'étape 12), réexporté ici sous les mêmes noms.
from .search_filtre import (LONG_BODY, LONG_COV, NEAR, _near, WORD, FILLER, drop_filler, _head_hit, accept_recall, recall_refusal, LONG_NQ, LONG_SCORE, AT_START, _long_refusal, _short_refusal)  # noqa: E402,F401
