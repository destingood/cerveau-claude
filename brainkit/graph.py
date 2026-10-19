"""Analyse du graphe de mémoire, façon graphify.

- liens déduits : similarité TF-IDF (titre, tags, contenu) entre souvenirs que rien ne relie encore, avec leur
  raison (mots communs) et une confiance (forte / moyenne / faible). Les liens écrits à la main restent « explicites » ;
- communautés : algorithme de Louvain sur le graphe pondéré (explicites + appartenance aux projets + déduits) ;
- nœuds clés : PageRank pondéré ; liens surprenants : liens qui traversent communautés ou projets ;
- trous : souvenirs isolés, doublons possibles, à-faire anciens, souvenirs vieux et jamais rappelés, contradictions ;
- chemins : plus court chemin entre deux souvenirs (liens explicites d'abord, puis déduits).

Le résultat est mis en cache dans state/analysis.json, recalculé seulement quand le contenu du graphe change
(les compteurs de rappel ne déclenchent pas de recalcul)."""
from __future__ import annotations

import hashlib
import heapq
import json
import math
import re
from collections import Counter, defaultdict

from .common import _CAMEL, STATE_DIR, STOPWORDS, days_since, fold, now_iso, read_json, short, slugify, stem, write_json
from .store import TYPES, Brain

ANALYSIS_FILE = STATE_DIR / "analysis.json"
VERSION = 8
W_EXPLICIT, W_MEMBER, W_INFERRED = 1.0, 0.6, 1.6
MIN_SIM, TOP_K, DUP_SIM = 0.16, 3, 0.5
WORD = re.compile(r"[^\W_]+", re.UNICODE)


# ------------------------------------------------------------------------------------------ vecteurs
def _terms(text):
    """Mots utiles → (clé de recherche, forme d'origine). Les nombres seuls (dates…) ne relient rien."""
    for w in WORD.findall(_CAMEL.sub(" ", str(text or ""))):
        f = fold(w)
        if len(f) < 3 or f.isdigit() or f in STOPWORDS:
            continue
        yield stem(f), w.lower()


def _vectors(nodes):
    raw, disp = {}, defaultdict(Counter)
    for n in nodes:
        tf = Counter()
        for text, w in ((n["title"], 3.0), (" ".join(n.get("tags") or []), 2.2), (n.get("body", ""), 1.0)):
            for key, orig in _terms(text):
                tf[key] += w
                disp[key][orig] += 1
        raw[n["id"]] = tf
    N = len(raw) or 1
    df = Counter(k for tf in raw.values() for k in tf)
    idf = {k: math.log((N + 1) / (d + 1)) + 1.0 for k, d in df.items()}
    vecs = {}
    for nid, tf in raw.items():
        v = {k: (1 + math.log(f)) * idf[k] for k, f in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs[nid] = {k: x / norm for k, x in v.items()}
    label = {k: c.most_common(1)[0][0] for k, c in disp.items()}
    return vecs, df, label


def _similarities(vecs, df):
    """Cosinus entre toutes les paires qui partagent un mot discriminant (index inversé : pas de O(N²) inutile)."""
    N = len(vecs)
    cap = max(2, min(int(0.3 * N), 50))
    inv = defaultdict(list)
    for nid, v in vecs.items():
        for k, x in v.items():
            if df[k] <= cap:
                inv[k].append((nid, x))
    sims = defaultdict(float)
    for lst in inv.values():
        if len(lst) < 2:
            continue
        for i in range(len(lst)):
            a, xa = lst[i]
            for j in range(i + 1, len(lst)):
                b, xb = lst[j]
                sims[(a, b) if a < b else (b, a)] += xa * xb
    return sims


def _why(va, vb, label, n=3):
    shared = sorted(((va[k] * vb[k], k) for k in va.keys() & vb.keys()), reverse=True)[:n]
    return [label.get(k, k) for _, k in shared]


def _short_title(title) -> str:
    """« Boutique Atelier Lune (Shopify, dropshipping) » → « Boutique Atelier Lune »."""
    t = re.split(r"\s[(—–-]", str(title))[0].strip()
    return t or str(title)


def confidence(w) -> str:
    return "forte" if w >= 0.40 else "moyenne" if w >= 0.25 else "faible"



# ------------------------------------------------------------------------------------------ concepts
# Concepts (façon graphify) : outils, sujets, sigles, domaines, fichiers et noms qui reviennent dans plusieurs
# souvenirs. Ils ne sont pas stockés : recalculés avec l'analyse, ils relient les souvenirs par ce dont ils parlent.
KNOWN = """Shopify|AutoDS|Leboncoin|Gmail|Google Calendar|Google Agenda|Google Analytics|Search Console|PageSpeed|
Lighthouse|Python|PowerShell|Git Bash|Node.js|Windows|BIOS|UEFI|Claude Code|claude.ai|Claude|MCP|Discord|iPhone|iVCam|
WO Mic|Canva|Ahrefs|AliExpress|Stripe|PayPal|Facebook|Instagram|TikTok|Pinterest|YouTube|Notion|Excel|Google Sheets|n8n|
Zapier|ChatGPT|Anthropic|Légifrance|EUR-Lex|GPSR|DEEE|CGV|CGU|RGPD|SEO|CRO|AMD|Ryzen|Gigabyte|NVIDIA|G-Assist|DDR5|
EXPO|MSIX|Microsoft Store|matcha|mousseur|coffret|kit|thème|hooks|skills|plugins|connecteur|tokens|
graphify|planificateur de tâches|tâche planifiée|copie de thème|bandeau|FAQ|redirection|301"""
KNOWN_TERMS = sorted({t.strip() for t in KNOWN.replace("\n", "").split("|") if t.strip()}, key=len, reverse=True)
KNOWN_DISPLAY = {fold(t): t for t in KNOWN_TERMS}
KNOWN_RX = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(fold(t)) for t in KNOWN_TERMS) + r")(?:s|es)?(?![a-z0-9])")
ACR_RX = re.compile(r"\b[A-Z][A-Z0-9]{2,6}\b")
UPPER_TOKEN = re.compile(r"\b(?=[A-Z0-9-]*[A-Z])[A-Z0-9][A-Z0-9-]+\b")  # B850, AORUS, ELITE, ICE…
ACR_STOP = {"OK", "TTC", "HT", "NB", "PS", "TODO", "III", "VII", "VIII", "XII", "USA", "URL", "PDF", "HTML", "JSON", "CSV",
            "ZIP", "USB", "API", "CLI", "LES", "DES", "UNE", "THE", "AND", "NON", "OUI", "ETC", "UTC", "GMT", "CET", "CEST"}
DOM_RX = re.compile(r"(?<![\w.@-])([a-z0-9][a-z0-9-]{1,40}(?:\.[a-z0-9-]{2,40})*\.(?:fr|com|ai|io|net|org|dev|app|co|eu|shop|store))(?![\w-])")
FILE_RX = re.compile(r"`([\w./\\-]+\.(?:py|md|json|html|js|ts|liquid|csv|xlsx|docx|pdf|ps1|bat|txt|ya?ml|toml))`")
CAP_RX = re.compile(r"(?<=[a-zà-ÿ0-9,;:)»] )([A-ZÀ-Ý][a-zà-ÿ]{2,}(?:[ -][A-ZÀ-Ý][a-zà-ÿ]{2,}){0,2})")
CAP_STOP = {fold(w) for w in """Lucas Le La Les Un Une Des Pour Par Avec Sans Dans Sur Mais Donc Puis Ensuite Comment Pourquoi
Quand Janvier Février Mars Avril Mai Juin Juillet Août Septembre Octobre Novembre Décembre Lundi Mardi Mercredi Jeudi
Vendredi Samedi Dimanche Fait Faits Constat Règle Cause Why How Pourquoi Comment Voir Note Étape Point Points Files
Program Store Devices Device Mobile Service Services Edition Home Data App Apps Code Pro Settings Paramètres""".split()}


def concept_tags(text, limit=4):
    """Étiquettes proposées pour un nouveau souvenir : outils, sujets, sigles et domaines qu'il mentionne."""
    out, seen = [], set()
    ftext = fold(text)
    found = [(m.start(), KNOWN_DISPLAY.get(m.group(1), m.group(1))) for m in KNOWN_RX.finditer(ftext)]
    found += [(m.start(), m.group(0)) for m in ACR_RX.finditer(text)
              if len(m.group(0)) <= 5 and m.group(0) not in ACR_STOP and sum(c.isalpha() for c in m.group(0)) >= 2]
    found += [(m.start(), m.group(1)) for m in DOM_RX.finditer(ftext)]
    for _, label in sorted(found):
        k = fold(label)
        if k not in seen:
            seen.add(k)
            out.append(label)
    return out[:limit]


def _concepts(nodes):
    found, disp, kind = defaultdict(set), defaultdict(Counter), {}
    lower = set()  # mots déjà vus en minuscules : écrits en capitales, ce sont des mots normaux (PUBLIER, NOTE…)
    for n in nodes:
        lower.update(w for w in WORD.findall(f"{n['title']} {n.get('body', '')}") if w.islower())

    def hit(key, nid, label, k):
        found[key].add(nid)
        disp[key][label] += 1
        kind.setdefault(key, k)

    for n in nodes:
        nid, text = n["id"], f"{n['title']}\n{n.get('body', '')}"
        ftext = fold(text)
        for m in KNOWN_RX.finditer(ftext):
            hit(m.group(1), nid, KNOWN_DISPLAY.get(m.group(1), m.group(1)), "sujet")
        runs, cur_run, last_end = [], [], -2
        for m in UPPER_TOKEN.finditer(text):  # « B850 AORUS ELITE ICE » = un nom de produit, pas quatre sigles
            if cur_run and text[last_end:m.start()] == " ":
                cur_run.append(m)
            else:
                if cur_run:
                    runs.append(cur_run)
                cur_run = [m]
            last_end = m.end()
        if cur_run:
            runs.append(cur_run)
        for run in runs:
            if len(run) >= 2:
                phrase = text[run[0].start():run[-1].end()]
                if sum(c.isalpha() for c in phrase) >= 4:
                    hit(fold(phrase), nid, phrase, "nom")
                continue
            tok = run[0].group(0)
            if ACR_RX.fullmatch(tok) and len(tok) <= 5 and tok not in ACR_STOP and sum(c.isalpha() for c in tok) >= 2 \
                    and tok.lower() not in lower:
                hit(fold(tok), nid, tok, "sigle")
        for m in DOM_RX.finditer(ftext):
            hit(m.group(1), nid, m.group(1), "domaine")
        for m in FILE_RX.finditer(text):
            base = re.split(r"[/\\]", m.group(1))[-1]
            hit(fold(base), nid, base, "fichier")
        for m in CAP_RX.finditer(text):
            phrase = m.group(1)
            words = [fold(w) for w in re.split(r"[ -]", phrase)]
            if all(w in CAP_STOP or w in STOPWORDS for w in words) or words[0] in CAP_STOP:
                continue
            if len(words) == 1 and phrase.lower() in lower:  # un seul mot qui existe aussi en minuscules : pas un nom
                continue
            hit(fold(phrase), nid, phrase, "nom")
    N = len(nodes) or 1
    out = []
    for key, mem in found.items():
        if len(mem) < 2 or len(mem) > max(3, 0.6 * N):
            continue
        out.append({"key": key, "label": disp[key].most_common(1)[0][0], "kind": kind[key], "members": sorted(mem)})
    keys = {c["key"]: c for c in out}
    final = []
    for c in out:  # « Atelier » disparaît derrière « Atelier Lune » s'il ne dit rien de plus
        longer = [o for o in out if o is not c and len(o["key"]) > len(c["key"])
                  and (o["key"].startswith(c["key"])
                       or re.search(rf"(?<![a-z0-9]){re.escape(c['key'])}(?![a-z0-9])", o["key"]))]
        if any(set(c["members"]) <= set(o["members"]) for o in longer):
            continue
        final.append(c)
    final.sort(key=lambda c: (-len(c["members"]), c["label"].lower()))
    for c in final:
        c["id"] = "concept:" + slugify(c["key"], 40)
    del keys
    return final[:40]


# ------------------------------------------------------------------------------------------ algorithmes
def louvain(adj, resolution=1.0, max_levels=10):
    """Communautés par optimisation de la modularité (Louvain). adj : {nœud: {voisin: poids}} symétrique."""
    nodes = sorted(adj)
    member = {n: n for n in nodes}          # nœud d'origine → nœud du niveau courant
    level = {n: dict(adj[n]) for n in nodes}
    for _ in range(max_levels):
        k = {i: sum(nb.values()) for i, nb in level.items()}
        m2 = sum(k.values())
        if m2 <= 0:
            break
        comm = {i: i for i in level}
        tot = dict(k)
        order = sorted(level, key=lambda i: (-k[i], str(i)))
        moved_any = False
        for _pass in range(20):
            moved = False
            for i in order:
                ci = comm[i]
                wto = defaultdict(float)
                for j, w in level[i].items():
                    if j != i:
                        wto[comm[j]] += w
                tot[ci] -= k[i]
                best, best_gain = ci, wto.get(ci, 0.0) - resolution * tot[ci] * k[i] / m2
                for c, w in sorted(wto.items(), key=lambda x: str(x[0])):
                    gain = w - resolution * tot[c] * k[i] / m2
                    if gain > best_gain + 1e-12:
                        best, best_gain = c, gain
                tot[best] += k[i]
                if best != ci:
                    comm[i] = best
                    moved = moved_any = True
            if not moved:
                break
        if not moved_any:
            break
        nxt = defaultdict(lambda: defaultdict(float))
        for i, nb in level.items():
            for j, w in nb.items():
                nxt[comm[i]][comm[j]] += w
        for i in comm:
            nxt.setdefault(comm[i], defaultdict(float))
        level = {c: dict(nb) for c, nb in nxt.items()}
        member = {n: comm[member[n]] for n in nodes}
    groups = defaultdict(list)
    for n in nodes:
        groups[member[n]].append(n)
    return list(groups.values())


def pagerank(adj, d=0.85, iters=60):
    nodes = list(adj)
    N = len(nodes) or 1
    pr = {n: 1.0 / N for n in nodes}
    wsum = {n: sum(adj[n].values()) for n in nodes}
    for _ in range(iters):
        new = {n: (1 - d) / N for n in nodes}
        dangling = sum(pr[n] for n in nodes if wsum[n] == 0)
        for n in nodes:
            if wsum[n]:
                share = d * pr[n] / wsum[n]
                for m, w in adj[n].items():
                    new[m] += share * w
        for n in nodes:
            new[n] += d * dangling / N
        pr = new
    return pr


# ------------------------------------------------------------------------------------------ analyse
def _signature(brain) -> str:
    """Empreinte du contenu (pas des compteurs de rappel) : l'analyse ne se recalcule que si le savoir change."""
    payload = [VERSION]
    for nid in sorted(brain.nodes):
        n = brain.nodes[nid]
        payload.append([nid, n.get("type"), n.get("title"), n.get("body", ""), n.get("tags"), n.get("project"),
                        n.get("status", "active"), n.get("importance", 3)])
    payload.append(sorted((e["from"], e["to"], e["rel"]) for e in brain.edges))
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def analyze(brain) -> dict:
    nodes = [n for n in brain.active()]
    by_id = {n["id"]: n for n in nodes}
    vecs, df, label = _vectors(nodes)
    sims = _similarities(vecs, df)

    # liens explicites (écrits) + appartenance aux projets
    explicit, pairs = [], set()
    for e in brain.edges:  # un lien aller-retour ne compte qu'une fois
        a, b = e["from"], e["to"]
        if a in by_id and b in by_id and a != b and frozenset((a, b)) not in pairs:
            explicit.append((a, b, e["rel"]))
            pairs.add(frozenset((a, b)))
    member_pairs = []
    for n in nodes:
        p = n.get("project")
        if p in by_id and p != n["id"] and frozenset((n["id"], p)) not in pairs:
            member_pairs.append((n["id"], p))
            pairs.add(frozenset((n["id"], p)))

    # liens déduits : k meilleurs voisins de chaque souvenir au-dessus du seuil
    per = defaultdict(list)
    raw_sim = {}
    for (a, b), s in sims.items():
        if s < MIN_SIM * 0.8 or frozenset((a, b)) in pairs:
            continue
        na, nb = by_id[a], by_id[b]
        bonus = 0.06 * min(2, len(set(na.get("tags") or []) & set(nb.get("tags") or [])))
        if na.get("project") and na.get("project") == nb.get("project"):
            bonus += 0.03
        w = s + bonus
        if w < MIN_SIM:
            continue
        raw_sim[(a, b)] = s
        per[a].append((w, b))
        per[b].append((w, a))
    keep = {}
    for a, lst in per.items():
        lst.sort(key=lambda x: (-x[0], x[1]))
        for w, b in lst[:TOP_K]:
            key = (a, b) if a < b else (b, a)
            keep[key] = max(keep.get(key, 0.0), w)
    inferred = [{"s": a, "t": b, "w": round(w, 3), "conf": confidence(w), "why": _why(vecs[a], vecs[b], label)}
                for (a, b), w in sorted(keep.items(), key=lambda kv: (-kv[1], kv[0]))]

    # graphe pondéré pour communautés et PageRank
    adj = {n["id"]: defaultdict(float) for n in nodes}

    def add(a, b, w):
        adj[a][b] += w
        adj[b][a] += w

    for a, b, _ in explicit:
        add(a, b, W_EXPLICIT)
    for a, b in member_pairs:
        add(a, b, W_MEMBER)
    for e in inferred:
        add(e["s"], e["t"], min(1.0, e["w"] * W_INFERRED))
    adj = {k: dict(v) for k, v in adj.items()}
    pr = pagerank(adj)
    top = max(pr.values()) if pr else 1.0
    pr = {k: round(v / top, 4) for k, v in pr.items()}

    groups = louvain(adj)
    comms = []
    for g in groups:
        projs = Counter(by_id[i].get("project") or (i if by_id[i]["type"] == "project" else None) for i in g)
        proj, cnt = (projs.most_common(1)[0] if projs else (None, 0))
        score = Counter()
        for i in g:
            for k, x in vecs[i].items():
                score[k] += x
        words = [label.get(k, k) for k, _ in score.most_common(6)]
        title = _short_title(by_id[proj]["title"]) if proj in by_id and cnt * 2 >= len(g) else None
        if title:
            tw = {stem(fold(w)) for w in WORD.findall(title)}
            extra = [w for w in words if stem(fold(w)) not in tw][:2]
            lab = short(title, 30) + (" · " + " · ".join(extra) if extra and len(g) > 1 else "")
        else:
            lab = " · ".join(words[:3]) or "divers"
        comms.append({"members": sorted(g, key=lambda i: -pr.get(i, 0)), "project": proj if title else None,
                      "label": lab, "words": words[:4], "size": len(g)})
    comms.sort(key=lambda c: (-c["size"], c["label"]))
    comm_of = {}
    for cid, c in enumerate(comms):
        c["id"] = cid
        for i in c["members"]:
            comm_of[i] = cid

    deg = Counter()
    for a, b, _ in explicit:
        deg[a] += 1
        deg[b] += 1
    for a, b in member_pairs:
        deg[a] += 1
        deg[b] += 1
    key_nodes = [i for i in sorted(pr, key=lambda i: -pr[i]) if by_id[i]["type"] != "project"][:8]

    # liens surprenants : ils traversent communautés ou projets
    def proj_of(i):
        n = by_id[i]
        return n["id"] if n["type"] == "project" else n.get("project")

    bridges = []
    for a, b, rel in explicit:
        if comm_of.get(a) != comm_of.get(b):
            cross = proj_of(a) != proj_of(b)
            bridges.append({"s": a, "t": b, "kind": "explicite", "why": [rel], "w": round(W_EXPLICIT * (1.4 if cross else 1) * 1.25, 3)})
    for e in inferred:
        if comm_of.get(e["s"]) != comm_of.get(e["t"]):
            cross = proj_of(e["s"]) != proj_of(e["t"])
            bridges.append({"s": e["s"], "t": e["t"], "kind": "déduit", "why": e["why"],
                            "w": round(e["w"] * (1.4 if cross else 1), 3)})
    best = {}
    for br in bridges:  # une seule entrée par paire
        k = frozenset((br["s"], br["t"]))
        if k not in best or br["w"] > best[k]["w"]:
            best[k] = br
    bridges = sorted(best.values(), key=lambda x: -x["w"])

    # trous de connaissance
    isolated = [n["id"] for n in nodes if n["type"] not in ("project", "user", "feedback") and not deg[n["id"]]]
    dups = [{"s": a, "t": b, "w": round(s, 3)} for (a, b), s in sorted(raw_sim.items(), key=lambda kv: -kv[1])
            if s >= DUP_SIM and by_id[a]["type"] == by_id[b]["type"] and by_id[a]["type"] != "project"][:10]
    stale = [n["id"] for n in nodes if n["type"] not in ("project", "user", "feedback")
             and not n.get("hits") and days_since(n.get("updated")) > 60]
    old_todos = [n["id"] for n in nodes if n["type"] == "todo" and days_since(n.get("updated")) > 14]
    contradictions = [[a, b] for a, b, rel in explicit if rel == "contradicts"]

    questions = []
    for br in bridges[:2]:
        questions.append(f"Quel rapport entre « {short(by_id[br['s']]['title'], 50)} » et « {short(by_id[br['t']]['title'], 50)} » ? "
                         f"({'lien ' + br['why'][0] if br['kind'] == 'explicite' else 'mots communs : ' + ', '.join(br['why'])})")
    if key_nodes:
        k0 = by_id[key_nodes[0]]
        questions.append(f"Tout ce qui dépend de « {short(k0['title'], 60)} » : `brain show {k0['id']}` puis `brain q`.")
    for c in comms:
        if not c["project"] and c["size"] >= 3:
            questions.append(f"Que regroupe la communauté « {c['label']} » ({c['size']} souvenirs) ? "
                             f"Sa fiche de synthèse : `brain fiche {c['words'][0] if c['words'] else c['id']}`.")
            break
    if isolated:
        questions.append(f"« {short(by_id[isolated[0]]['title'], 60)} » n'est relié à rien : à rattacher (`brain link`) ou à archiver ?")

    concepts = _concepts(nodes)
    return {"version": VERSION, "generated": now_iso(), "n": len(nodes), "explicit": len(explicit) + len(member_pairs),
            "concepts": concepts,
            "inferred": inferred, "communities": comms, "comm": comm_of, "pr": pr, "deg": dict(deg),
            "key": key_nodes, "bridges": bridges[:12], "dups": dups,
            "gaps": {"isolated": isolated, "stale": stale, "old_todos": old_todos, "contradictions": contradictions},
            "questions": questions[:5]}


_MEMO = {}  # analyses calculées sans écrire (banc d'essai, `q --at`) : une par état du graphe, en mémoire seulement


def ensure(brain=None, force=False, write=True) -> dict:
    """Analyse à jour (cache state/analysis.json, recalcul seulement si le contenu du graphe a changé).
    write=False : rien n'est lu ni écrit sur le disque (monde fictif du banc d'essai, état passé)."""
    brain = brain or Brain.load()
    sig = _signature(brain)
    if not write:
        if sig not in _MEMO:
            if len(_MEMO) >= 4:
                _MEMO.pop(next(iter(_MEMO)))
            _MEMO[sig] = dict(analyze(brain), sig=sig)
        return _MEMO[sig]
    if not force:
        cached = read_json(ANALYSIS_FILE, None)
        if isinstance(cached, dict) and cached.get("sig") == sig and cached.get("version") == VERSION:
            return cached
    data = analyze(brain)
    data["sig"] = sig
    try:
        write_json(ANALYSIS_FILE, data, indent=None)
    except Exception:
        pass
    return data


# ------------------------------------------------------------------------------------------ requêtes
def inferred_of(an, nid, limit=3):
    """Liens déduits d'un souvenir : [(autre id, poids, confiance, mots communs)]."""
    out = []
    for e in an.get("inferred", []):
        if e["s"] == nid:
            out.append((e["t"], e["w"], e["conf"], e["why"]))
        elif e["t"] == nid:
            out.append((e["s"], e["w"], e["conf"], e["why"]))
    out.sort(key=lambda x: -x[1])
    return out[:limit]


def community_of(an, nid):
    cid = an.get("comm", {}).get(nid)
    if cid is None:
        return None
    for c in an.get("communities", []):
        if c["id"] == cid:
            return c
    return None


def _adjacency(brain, an):
    """Graphe pour les chemins : coût 1 par lien explicite, 1,5 par appartenance, plus cher pour un lien déduit."""
    act = {n["id"]: n for n in brain.active()}
    adj = defaultdict(list)
    for e in brain.edges:
        a, b = e["from"], e["to"]
        if a in act and b in act:
            adj[a].append((b, 1.0, e["rel"], "→"))
            adj[b].append((a, 1.0, e["rel"], "←"))
    for n in act.values():
        p = n.get("project")
        if p in act and p != n["id"]:
            adj[n["id"]].append((p, 1.5, "part_of", "→"))
            adj[p].append((n["id"], 1.5, "part_of", "←"))
    for e in an.get("inferred", []):
        if e["s"] in act and e["t"] in act:
            cost = 1.2 + 2.0 * (1 - min(1.0, e["w"] * 2))
            why = "≈ déduit (" + ", ".join(e["why"]) + ")"
            adj[e["s"]].append((e["t"], cost, why, "≈"))
            adj[e["t"]].append((e["s"], cost, why, "≈"))
    return act, adj


def shortest_path(brain, an, a, b):
    """Plus court chemin pondéré (Dijkstra) entre deux souvenirs → [(id, relation, sens)] ou None."""
    act, adj = _adjacency(brain, an)
    if a not in act or b not in act:
        return None
    dist, prev = {a: 0.0}, {a: None}
    heap = [(0.0, a)]
    while heap:
        d, cur = heapq.heappop(heap)
        if cur == b:
            break
        if d > dist.get(cur, 1e9):
            continue
        for nxt, cost, rel, sens in adj[cur]:
            nd = d + cost
            if nd < dist.get(nxt, 1e9):
                dist[nxt], prev[nxt] = nd, (cur, rel, sens)
                heapq.heappush(heap, (nd, nxt))
    if b not in prev:
        return None
    chain, cur = [], b
    while prev[cur]:
        p, rel, sens = prev[cur]
        chain.append((cur, rel, sens))
        cur = p
    chain.reverse()
    return chain


def expand(brain, an, hits, seen, limit=3, types=None):
    """Voisins des meilleurs résultats d'une recherche : liens explicites d'abord, puis déduits (traversée façon graphify)."""
    extra = []
    for r in hits[:3]:
        nid = r["node"]["id"]
        cands = [(m, 0.4, f"{nid} · {rel}") for m, rel, _ in brain.neighbors(nid)]
        cands += [(brain.nodes.get(o), 0.3 * min(1.0, w * 2), f"{nid} · ≈ {', '.join(why)}")
                  for o, w, _, why in inferred_of(an, nid, 3)]
        for m, factor, via in cands:
            if not m or m["id"] in seen or m.get("status", "active") != "active":
                continue
            if types and m["type"] not in types:
                continue
            seen.add(m["id"])
            extra.append({"key": m["id"], "score": round(r["score"] * factor, 2), "matched": 0, "midf": 0.0,
                          "nq": r["nq"], "node": m, "via": via})
    extra.sort(key=lambda x: -x["score"])
    return extra[:limit]


# ------------------------------------------------------------------------------------------ rapport
def report(brain, an) -> str:
    """RAPPORT.md, l'équivalent du GRAPH_REPORT.md de graphify pour la mémoire."""
    by_id = brain.nodes
    t = lambda i: by_id[i]["title"] if i in by_id else i  # noqa: E731
    lines = [f"# 🧠 Rapport du cerveau ({an['generated'][:10]})", "",
             f"{an['n']} nœuds · {an['explicit']} liens explicites · {len(an['inferred'])} liens déduits · "
             f"{len(an['communities'])} communautés.", ""]
    from . import journal
    week = [n for n in brain.active() if n["type"] != "project" and days_since(n.get("created")) <= 7]
    upd = [n for n in brain.active() if n["type"] != "project" and days_since(n.get("created")) > 7
           and days_since(n.get("updated")) <= 7]
    sess = [s for s in journal.load()["sessions"].values() if days_since(s.get("end")) <= 7]
    per = Counter(s.get("project") or "hors projet" for s in sess)
    lines += ["## Cette semaine", "",
              f"- {len(week)} nouveau(x) souvenir(s), {len(upd)} mis à jour · {len(sess)} session(s)"
              + (" (" + ", ".join(f"{p} {c}" for p, c in per.most_common(4)) + ")" if per else "")]
    for n in sorted(week, key=lambda x: x.get("created") or "", reverse=True)[:6]:
        lines.append(f"- nouveau : {short(n['title'], 70)} `{n['id']}`")
    lines += ["", "## Communautés", ""]
    for c in an["communities"]:
        if c["size"] < 2:
            continue
        mem = ", ".join(f"{short(t(i), 42)}" for i in c["members"][:4])
        lines.append(f"- **{c['label']}** ({c['size']}) — {mem}" + (" …" if c["size"] > 4 else ""))
    singles = sum(1 for c in an["communities"] if c["size"] < 2)
    if singles:
        lines.append(f"- _{singles} souvenir(s) seul(s) dans leur communauté_")
    try:
        from . import fiches
        fs = fiches.ensure(brain, an)
    except Exception:
        fs = {}
    if fs:
        lines += ["", "## Fiches de synthèse (extractives, régénérées quand un membre change)", ""]
        for f in fs.values():
            lines.append(f"- **{f['label']}** ({f['size']}) — " + " · ".join(short(x["t"], 110) for x in f["lines"][:2]))
    if an.get("concepts"):
        lines += ["", "## Concepts (repérés automatiquement)", "",
                  " · ".join(f"{c['label']} ({len(c['members'])})" for c in an["concepts"][:16])]
    lines += ["", "## Nœuds clés (les plus centraux)", ""]
    for i in an["key"][:6]:
        lines.append(f"- {t(i)} `{i}` — centralité {an['pr'].get(i, 0):.2f} · {an['deg'].get(i, 0)} lien(s) explicite(s)")
    if an["bridges"]:
        lines += ["", "## Liens surprenants (entre communautés ou projets)", ""]
        for br in an["bridges"][:6]:
            why = br["why"][0] if br["kind"] == "explicite" else "mots communs : " + ", ".join(br["why"])
            lines.append(f"- {short(t(br['s']), 50)} ↔ {short(t(br['t']), 50)} — {br['kind']} ({why})")
    sugg = [e for e in an["inferred"] if e["conf"] != "faible"][:8]
    if sugg:
        lines += ["", "## Liens suggérés (déduits, à confirmer avec `brain link a b`)", ""]
        for e in sugg:
            lines.append(f"- `{e['s']}` ↔ `{e['t']}` — confiance {e['conf']} ({e['w']:.2f}) · {', '.join(e['why'])}")
    g = an["gaps"]
    lines += ["", "## Trous et entretien", ""]
    if an["dups"]:
        lines.append("- Doublons possibles : " + " · ".join(f"`{d['s']}` ≈ `{d['t']}` ({d['w']:.2f})" for d in an["dups"][:5])
                     + " → `brain consolidate`")
    if g["isolated"]:
        lines.append(f"- Isolés ({len(g['isolated'])}) : " + ", ".join(f"`{i}`" for i in g["isolated"][:8]))
    if g["old_todos"]:
        lines.append(f"- À-faire de plus de 14 jours : " + ", ".join(f"`{i}`" for i in g["old_todos"][:8]))
    if g["stale"]:
        lines.append(f"- Jamais rappelés depuis 60 jours ou plus : " + ", ".join(f"`{i}`" for i in g["stale"][:8]))
    if g["contradictions"]:
        lines.append("- Contradictions : " + " · ".join(f"`{a}` ⟂ `{b}`" for a, b in g["contradictions"]))
    if lines[-1] == "":
        lines.append("- Rien à signaler.")
    if an["questions"]:
        lines += ["", "## Questions suggérées", ""] + [f"- {q}" for q in an["questions"]]
    return "\n".join(lines) + "\n"
