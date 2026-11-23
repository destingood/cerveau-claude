"""Regroupement des souvenirs (`brain regroupe`, étape 8 du plan) : montre d'abord, n'applique que ce qui est accepté.

Trois sortes de propositions, numérotées :
1. **doublons reformulés** — deux souvenirs qui disent la même chose avec d'autres mots (« Prétentions salariales » et
   « Salaire demandé »). La consolidation ne les voyait jamais : leurs mots en commun (similarité de Jaccard 0,11 à
   0,39) restaient loin de ses seuils (0,82 à 0,9). Ils se trouvent par l'index de recherche, qui connaît les formes
   d'un mot et ses synonymes : chaque souvenir y est cherché par ses mots les plus distinctifs ; une paire est proposée
   quand chacun est le plus proche de l'autre, de même sorte et du même projet (jamais deux projets : « Objectif du
   mois » de la boutique et celui de la chaîne restent deux souvenirs), assez proche, et sans repère de temps qui les
   distingue (« septembre » et « octobre » : deux bilans, pas un doublon) ;
2. **souvenirs sans projet** à rattacher — seulement sur plusieurs indices qui concordent, jamais sur un seul : un nom
   propre qu'on ne trouve que dans les souvenirs d'un même projet, la communauté du graphe (l'analyse en place), les
   plus proches souvenirs dans l'index ; et aucun indice contraire. Le profil et les règles restent globaux ;
3. **sujets à réunir en fiche** — plusieurs petits souvenirs d'un même projet sur un même sujet (un nom, un sigle :
   « Kraken », « Mondial Relay »), qui se citent entre eux. La fiche est un nouveau souvenir (référence) qui les résume
   en une ligne chacun ; ils restent tels quels, reliés à elle.

`brain regroupe` montre la liste (gardée dans state/regroupe.json avec l'état de chaque souvenir concerné) ;
`--appliquer 1,3` ou `--appliquer tout` l'applique, après un instantané forcé (`brain restore 1` annule) ; une
proposition dont un souvenir a changé depuis n'est pas appliquée. `--ecarter 2` : ne plus la proposer.
Jamais dans un hook : quelques secondes à 10 000 souvenirs."""
from __future__ import annotations

import re
from collections import Counter

from .common import STATE_DIR, fold, now_iso, read_json, short, tokenize, write_json

PLAN_FILE = STATE_DIR / "regroupe.json"
ECARTES_FILE = STATE_DIR / "regroupe-ecartes.json"
TERMS = 12  # mots les plus distinctifs d'un souvenir pour le chercher dans l'index
NEAR = 20  # voisins gardés par souvenir (assez pour trouver ceux du même projet derrière ceux des autres)
CAP_MIN, CAP_DIV = 25, 400  # mot trop courant pour chercher : dans plus de max(25, 1 souvenir sur 400)
DUP_MIN = 0.30  # proximité minimale d'un doublon (score de l'autre / score de soi, dans les deux sens)
COVER_SHORT, COVER_LONG, MATCH_MIN = 0.40, 0.33, 4  # couverture du plus court par le plus long, et l'inverse ; mots
NB_MIN = 0.15  # proximité minimale du plus proche voisin pour qu'il compte comme indice de projet
FICHE_MIN, FICHE_MAX, FICHE_SMALL = 3, 12, 400  # membres d'une fiche ; « petit » souvenir : contenu court
FICHE_SHOW = 8
TIE_MIN = 0.12  # un membre d'une fiche doit avoir un autre membre parmi ses 3 plus proches souvenirs, à ce niveau
GLOBAL_TYPES = ("user", "feedback")  # profil et règles : globaux par nature, jamais rattachés à un projet
# fêtes, mois et jours : écrits avec une majuscule, ce ne sont pas des noms de choses (« Cadeau de Noël »)
_NOT_A_NAME = {"janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre",
               "novembre", "decembre", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche", "noel",
               "paques", "toussaint", "ascension", "pentecote"}


# ------------------------------------------------------------------------------------------ voisins
def neighbours(brain, idx=None) -> dict:
    """Chaque souvenir actif → [(id voisin, proximité, couverture, mots trouvés)] du plus proche au moins proche, pour
    une requête faite de ses mots les plus distinctifs : proximité = score du voisin / score du souvenir lui-même ;
    couverture = part (pondérée par la rareté) de ces mots que le voisin contient, sous une forme ou une autre. Les mots
    trop courants (présents dans plus d'un souvenir sur 40) ne servent pas à chercher : ils ne distinguent rien, et ils
    feraient examiner tout le cerveau pour chaque souvenir."""
    from . import search
    idx = idx or search.memory_index(brain)
    memo, base = {}, idx.variants

    def variants(q, synonyms=True):  # chaque mot rare revient dans plusieurs requêtes : ses formes calculées une fois
        got = memo.get((q, synonyms))
        if got is None:
            got = memo[(q, synonyms)] = base(q, synonyms)
        return got

    idx.variants = variants  # (le temps de cette passe : l'index gardé en mémoire retrouve ensuite sa méthode)
    try:
        return _neighbours(brain, idx)
    finally:
        del idx.variants


def _neighbours(brain, idx) -> dict:
    tfs, cap = idx.tfs, _cap(idx)
    pos = {k: i for i, k in enumerate(idx.keys)}
    out = {}
    for n in brain.active(own=True):
        i = pos.get(n["id"])
        if n["type"] == "project" or i is None or _is_fiche(n):
            continue
        tf = tfs[i]
        terms = sorted((t for t in tf if idx.df.get(t, 0) <= cap), key=lambda t: (-tf[t] * idx.idf(t), t))[:TERMS]
        if not terms:
            continue
        hits = idx.search(" ".join(terms), limit=NEAR + 1)
        own = next((h["score"] for h in hits if h["key"] == n["id"]), None)
        if not own:
            continue
        out[n["id"]] = [(h["key"], round(h["score"] / own, 3), round(h["cov"], 3), h["matched"]) for h in hits
                        if h["key"] != n["id"] and h["key"] in brain.nodes and not _is_fiche(brain.nodes[h["key"]])]
    return out


def _cap(idx) -> int:
    """Nombre de souvenirs au-delà duquel un mot est trop courant pour chercher avec. Un plafond qui suit la taille du
    cerveau (1 sur 40) faisait examiner des centaines de souvenirs par requête à 10 000 : 12 s au lieu de 1,7."""
    return max(CAP_MIN, idx.N // CAP_DIV)


def _name_cap(idx) -> int:
    """Nombre de souvenirs au-delà duquel un nom propre est trop courant pour dire où vit un souvenir."""
    return max(25, idx.N // 40)


def _is_fiche(n) -> bool:
    """Fiche créée par `brain regroupe` : elle reprend ses membres, ce n'est ni un doublon ni un membre possible."""
    return bool((n.get("meta") or {}).get("fiche"))


def _proj(brain, nid):
    n = brain.nodes.get(nid) or {}
    return nid if n.get("type") == "project" else n.get("project") or None


def _linked(brain, a, b, rels=("supersedes", "contradicts")) -> bool:
    return any({e["from"], e["to"]} == {a, b} and e["rel"] in rels for e in brain.edges)


# ------------------------------------------------------------------------------------------ 1. doublons
def duplicates(brain, near, ecartes=frozenset()) -> list:
    """Paires de doublons reformulés : [{kind, keep, drop, score}] (keep : le souvenir à garder, priorité du cerveau)."""
    from .reconcile import other_event
    from .store import priority
    best = {}
    for nid, hits in near.items():
        n = brain.nodes[nid]
        for hit in hits:
            o = brain.nodes.get(hit[0])
            if not o or o.get("status", "active") != "active" or o["type"] != n["type"] \
                    or (o.get("project") or None) != (n.get("project") or None):
                continue
            best[nid] = hit  # le plus proche de même sorte et du même projet
            break
    out = []
    for a, (b, r, cov_ab, m_ab) in best.items():
        if a > b or best.get(b, (None,))[0] != a:
            continue  # chacun doit être le plus proche de l'autre
        _, r_ba, cov_ba, m_ba = best[b]
        score = min(r, r_ba)
        na, nb = brain.nodes[a], brain.nodes[b]
        if score < DUP_MIN or frozenset((a, b)) in ecartes or _linked(brain, a, b):
            continue
        # le plus court se retrouve dans le plus long, et le plus long en bonne partie dans le plus court : deux
        # souvenirs qui se ressemblent par quelques mots rares (« Alerte de prix sur Hermès », « Outils d'analyse »)
        # n'en sont pas un seul
        short_first = len(na.get("body") or "") <= len(nb.get("body") or "")
        cov_short, cov_long = (cov_ab, cov_ba) if short_first else (cov_ba, cov_ab)
        if cov_short < COVER_SHORT or cov_long < COVER_LONG or min(m_ab, m_ba) < MATCH_MIN:
            continue
        old, new = sorted((na, nb), key=lambda x: x.get("created") or "")
        if other_event(old["title"], old.get("body", ""), new["title"], new.get("body", "")):
            continue  # autre mois, autre semaine, autre numéro : une série, pas un doublon
        keep, drop = (na, nb) if (priority(na), na.get("created") or "") >= (priority(nb), nb.get("created") or "") \
            else (nb, na)
        out.append({"kind": "doublon", "keep": keep["id"], "drop": drop["id"], "score": round(score, 2)})
    out.sort(key=lambda x: -x["score"])
    return out


# ------------------------------------------------------------------------------------------ 2. rattachements
def _names(text) -> dict:
    """Mots qui ressemblent à des noms propres (majuscule, sigle, code), début de phrase compris → {replié: tel
    qu'écrit}. Ils ne comptent que s'ils sont aussi des noms dans un autre souvenir (voir _name_votes)."""
    out = {}
    for m in re.finditer(r"(?<![\w'’])([A-ZÀ-Ý][\wÀ-ÿ.\-]+|[\w]*\d[\w]*[A-Za-z][\w]*)", str(text or "")):
        raw = m.group(1).strip(".-")
        w = fold(raw)
        if len(w) >= 2 and w not in _NOT_A_NAME:
            out.setdefault(w, raw)
    return out


def _quote(words) -> str:
    """[« Klaviyo »] → « « Klaviyo » n'apparaît », deux noms ou plus → « … apparaissent »."""
    q = ", ".join(f"« {w} »" for w in words)
    return q + (" n'apparaît" if len(words) == 1 else " n'apparaissent")


def _name_votes(brain, idx, nid, cap, seen) -> dict:
    """Noms propres du souvenir → Counter des projets (None : global) des AUTRES souvenirs qui les citent comme noms.
    `seen` : noms propres de chaque souvenir déjà regardé ({id: set}), d'un souvenir sans projet à l'autre."""
    from .reconcile import entities
    n = brain.nodes[nid]
    votes = {}
    for w, raw in _names(f"{n['title']}\n{n.get('body', '')}").items():
        toks = tokenize(w)
        if len(toks) != 1:
            continue
        docs = [idx.keys[i] for i in idx.docs(toks[0])]
        docs = [d for d in docs if d != nid and d in brain.nodes]
        if not docs or len(docs) > cap:
            continue
        ps = Counter()
        for d in docs:
            got = seen.get(d)
            if got is None:
                o = brain.nodes[d]
                got = seen[d] = entities(f"{o['title']}\n{o.get('body', '')}")
            if w in got:  # un nom là-bas aussi, pas un mot courant
                ps[_proj(brain, d)] += 1
        if ps:
            votes[raw] = ps
    return votes


def _strong_for(ps):
    """Counter de projets → (projet, nombre) si le nom vit dans un seul projet, plus que dans les souvenirs globaux."""
    projs = {p: c for p, c in ps.items() if p}
    if len(projs) != 1:
        return None
    p, c = next(iter(projs.items()))
    return (p, c) if c > ps.get(None, 0) else None


def attachments(brain, near, an, idx, ecartes=frozenset()) -> list:
    """Souvenirs sans projet à rattacher : [{kind, id, project, why}], seulement sur au moins deux indices concordants
    (un nom propre, la communauté du graphe, les plus proches souvenirs) et sans indice contraire."""
    from . import graph
    cap = _name_cap(idx)
    out, seen = [], {}
    for n in brain.active(own=True):
        if n["type"] == "project" or n["type"] in GLOBAL_TYPES or n.get("project") or _is_fiche(n):
            continue
        votes = _name_votes(brain, idx, n["id"], cap, seen)
        names = {}  # projet → [(nom, nombre de souvenirs)]
        weak = {}
        against = set()
        for w, ps in votes.items():
            got = _strong_for(ps)
            projs = {p: c for p, c in ps.items() if p}
            if got and got[1] >= 2:
                names.setdefault(got[0], []).append((w, got[1]))
            elif got:
                weak.setdefault(got[0], []).append(w)
            elif projs:  # un nom partagé entre plusieurs projets : indice contraire s'il penche nettement ailleurs
                top, c = max(projs.items(), key=lambda kv: kv[1])
                if c >= 2 and c * 3 >= 2 * sum(projs.values()):
                    against.add(top)
        c = graph.community_of(an, n["id"]) if an else None
        comm = c.get("project") if c else None
        near_p = [_proj(brain, h[0]) for h in near.get(n["id"], []) if _proj(brain, h[0])][:3]
        first_r = next((h[1] for h in near.get(n["id"], []) if _proj(brain, h[0])), 0)
        nb = near_p[0] if len(near_p) == 3 and len(set(near_p)) == 1 and first_r >= NB_MIN else None
        for p in sorted(set(names) | set(weak) | {comm, nb} - {None}):
            signals = []
            if p in names:
                ws = names[p]
                signals.append(f"{_quote([w for w, _ in ws[:2]])} que dans ce projet ({max(k for _, k in ws)} "
                               "autres souvenirs)")
            if comm == p:
                signals.append("sa communauté du graphe est celle de ce projet")
            if nb == p:
                signals.append("ses 3 plus proches souvenirs en sont")
            strong = p in names
            if p in weak and not strong and len(signals) >= 2:  # un seul autre souvenir : compte s'il y a les deux autres
                signals.insert(0, f"{_quote(weak[p][:1])} que dans ce projet (1 autre souvenir)")
                strong = True
            contrary = (against - {p}) or (set(names) - {p}) or (comm and comm != p)
            if strong and len(signals) >= 2 and not contrary and (n["id"], p) not in ecartes:
                out.append({"kind": "projet", "id": n["id"], "project": p, "why": signals})
                break
    return out


# ------------------------------------------------------------------------------------------ 3. fiches
def fiches(brain, concepts, near, ecartes=frozenset(), merged=frozenset()) -> list:
    """Sujets à réunir en fiche : [{kind, key, label, project, ids}]. Sujet = un concept (nom, sigle, sujet connu :
    graph.concepts_all, tous, pas seulement les 40 plus cités que garde l'analyse — avant, un sujet de quelques
    souvenirs n'était presque jamais vu dans un gros cerveau) cité par FICHE_MIN à FICHE_MAX souvenirs actifs d'un même
    projet (ou tous globaux), petits pour la plupart, qui se retrouvent entre eux dans l'index, et pas déjà réunis dans
    une fiche. `merged` : souvenirs qu'un doublon de la même liste fond dans un autre (ils n'y entrent pas : l'autre
    suffit)."""
    done = {(n.get("meta") or {}).get("fiche") for n in brain.active(own=True)} - {None}
    titles = {p["id"]: {fold(w) for w in re.findall(r"[\wÀ-ÿ]+", p["title"])} for p in brain.projects()}
    every = set().union(*titles.values()) if titles else set()
    out = []
    for c in concepts or []:
        if c.get("kind") == "fichier" or c["key"] in done or not FICHE_MIN <= len(c["members"]):
            continue
        mem = [brain.nodes[i] for i in c["members"] if i in brain.nodes]
        mem = [m for m in mem if m.get("status", "active") == "active" and m["type"] not in ("project", "user")
               and m["id"] not in merged and not _is_fiche(m)]
        by = Counter(m.get("project") or None for m in mem)
        if not by:
            continue
        scope, size = by.most_common(1)[0]
        group = [m for m in mem if (m.get("project") or None) == scope]
        if not FICHE_MIN <= size <= FICHE_MAX or (c["key"], scope) in ecartes:
            continue
        words = {fold(w) for w in re.findall(r"[\wÀ-ÿ]+", c["label"])}
        if words <= (titles.get(scope, set()) if scope else every):
            continue  # le nom d'un projet : c'est déjà le projet
        lens = sorted(len(m.get("body", "")) for m in group)
        if lens[len(lens) // 2] > FICHE_SMALL:
            continue
        ids = {m["id"] for m in group}
        tied = sum(1 for m in group if any(h[0] in ids and h[1] >= TIE_MIN for h in near.get(m["id"], [])[:3]))
        if tied * 3 < 2 * len(group):
            continue  # un nom cité au passage (une ville, un outil) : pas un sujet commun
        out.append({"kind": "fiche", "key": c["key"], "label": _spelled(c["label"], group), "project": scope,
                    "ids": sorted(ids, key=lambda i: brain.nodes[i].get("created") or "")})
    out.sort(key=lambda f: (-len(f["ids"]), f["label"].lower()))
    return out[:FICHE_SHOW]


def _spelled(label, nodes) -> str:
    """Nom d'un sujet tel que ses souvenirs l'écrivent le plus souvent, en entier (« Linked » → « LinkedIn »)."""
    rx = re.compile(rf"(?<![\wÀ-ÿ]){re.escape(label)}[\wÀ-ÿ]*", re.I)
    seen = Counter(m.group(0) for n in nodes for m in rx.finditer(f"{n['title']}\n{n.get('body', '')}"))
    return seen.most_common(1)[0][0] if seen else label


def fiche_body(brain, ids) -> str:
    """Une ligne par souvenir : titre — début du contenu, et son id (`brain show <id>`). Rien d'inventé."""
    rows = []
    for i in ids:
        n = brain.nodes[i]
        body = " ".join(str(n.get("body") or "").split())
        rows.append(f"- {n['title']}" + (f" — {short(body, 160)}" if body else "") + f" `{i}`")
    return "\n".join(rows)


# ------------------------------------------------------------------------------------------ liste et application
def _ecartes() -> set:
    raw = read_json(ECARTES_FILE, {}) or {}
    out = set()
    for item in raw.get("items", []) if isinstance(raw, dict) else []:
        if isinstance(item, list) and len(item) == 2 and item[0] == "doublon" and isinstance(item[1], list):
            out.add(frozenset(item[1]))
        elif isinstance(item, list) and len(item) == 3:
            out.add((item[1], item[2]))
    return out


def _fp(brain, ids) -> dict:
    return {i: (brain.nodes.get(i) or {}).get("updated") for i in ids}


def _ids(item) -> list:
    if item["kind"] == "doublon":
        return [item["keep"], item["drop"]]
    return [item["id"]] if item["kind"] == "projet" else list(item["ids"])


def propose(brain=None) -> list:
    """Toutes les propositions, numérotées, gardées dans state/regroupe.json avec l'état de leurs souvenirs."""
    from . import graph, search
    from .store import Brain
    brain = brain or Brain.load()
    idx = search.memory_index(brain)
    near = neighbours(brain, idx)
    an = graph.ensure(brain, wait=True)
    ecartes = _ecartes()
    items = duplicates(brain, near, ecartes)
    used = {i for it in items for i in _ids(it)}
    items += [a for a in attachments(brain, near, an, idx, ecartes) if a["id"] not in used]
    concepts = graph.concepts_all(list(brain.active()))  # tous les sujets, pas les 40 de l'analyse (0,75 s à 10 000)
    items += fiches(brain, concepts, near, ecartes, {it["drop"] for it in items if it["kind"] == "doublon"})
    for k, it in enumerate(items, 1):
        it["n"] = k
        it["fp"] = _fp(brain, _ids(it) + ([it["project"]] if it.get("project") else []))
    write_json(PLAN_FILE, {"made": now_iso(), "items": items})
    return items


def describe(brain, it) -> list:
    """Lignes d'affichage d'une proposition."""
    def t(i):
        return short((brain.nodes.get(i) or {}).get("title", i), 60)

    def p(pid):
        return t(pid) if pid else "global"

    if it["kind"] == "doublon":
        k = brain.nodes.get(it["keep"]) or {}
        return [f"{it['n']:>3}. « {t(it['keep'])} » ⇐ « {t(it['drop'])} » · {p(k.get('project'))} · proximité "
                f"{str(it['score']).replace('.', ',')}",
                f"     `{it['keep']}` garde son id ; `{it['drop']}` y est fusionné (textes, liens, compteurs, dates) puis "
                "archivé"]
    if it["kind"] == "projet":
        return [f"{it['n']:>3}. « {t(it['id'])} » → projet {p(it['project'])}",
                f"     pourquoi : {' ; '.join(it['why'])}"]
    names = ", ".join(f"« {t(i)} »" for i in it["ids"][:4]) + (" …" if len(it["ids"]) > 4 else "")
    return [f"{it['n']:>3}. Fiche « {it['label']} » · {p(it['project'])} · {len(it['ids'])} souvenirs : {names}",
            "     une nouvelle fiche les résume et les relie ; ils restent tels quels"]


def show_text(brain, items) -> str:
    if not items:
        return ("✓ rien à regrouper : aucun doublon reformulé, aucun souvenir à rattacher à un projet, aucun sujet à "
                "réunir en fiche")
    counts = Counter(it["kind"] for it in items)
    head = (f"🧩 Regroupement — {counts['doublon']} doublon(s), {counts['projet']} rattachement(s), {counts['fiche']} "
            "fiche(s) proposés. Rien n'est appliqué sans ton accord.")
    lines = [head]
    for kind, title in (("doublon", "Doublons reformulés (le même souvenir dit deux fois)"),
                        ("projet", "Souvenirs sans projet, à rattacher"),
                        ("fiche", "Sujets à réunir en fiche")):
        group = [it for it in items if it["kind"] == kind]
        if group:
            lines += ["", f"{title} :"]
            for it in group:
                lines += describe(brain, it)
    lines += ["", "Appliquer : `brain regroupe --appliquer 1,3` (ou `--appliquer tout`) — un instantané est pris avant "
              "(`brain restore 1` annule). Ne plus proposer : `brain regroupe --ecarter 2`."]
    return "\n".join(lines)


def parse_numbers(spec, total) -> list:
    """« 1,3,5 », « 2-4 », « tout » → [numéros] ; ValueError (message en français) si un numéro n'existe pas."""
    spec = str(spec or "").strip().lower()
    if spec in ("tout", "tous", "toutes", "all"):
        return list(range(1, total + 1))
    out = []
    for part in re.split(r"[,;\s]+", spec):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise ValueError(f"« {part} » n'est pas un numéro de la liste (exemple : --appliquer 1,3 ou 2-4)")
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        for k in range(lo, hi + 1):
            if not 1 <= k <= total:
                raise ValueError(f"numéro inconnu : {k} (la liste en a {total}) — relance `brain regroupe` pour la "
                                 "revoir")
            if k not in out:
                out.append(k)
    if not out:
        raise ValueError("aucun numéro donné (exemple : --appliquer 1,3, ou --appliquer tout)")
    return out


def saved() -> list:
    plan = read_json(PLAN_FILE, None)
    if not isinstance(plan, dict) or not isinstance(plan.get("items"), list):
        raise LookupError("aucune liste à appliquer : lance d'abord `brain regroupe` pour la voir")
    return plan["items"]


def apply(spec) -> dict:
    """Applique les propositions `spec` (« 1,3 », « 2-4 », « tout ») de la liste gardée.
    → {"done": [lignes], "skipped": [lignes], "snap": instantané pris avant}"""
    from . import history
    from .store import Brain
    items = saved()
    chosen = [items[k - 1] for k in parse_numbers(spec, len(items))]
    snap, done, skipped = None, [], []
    with Brain.edit() as b:
        moved = {}  # état d'avant cette application : les propositions d'une même liste ne s'invalident pas entre elles
        for it in chosen:
            now = _fp(b, list(it["fp"]))
            moved[it["n"]] = [i for i in it["fp"] if i not in b.nodes or now[i] != it["fp"][i]
                              or b.nodes[i].get("status", "active") != "active"]
        if any(not it.get("applied") and not moved[it["n"]] for it in chosen):
            # graph.json tel qu'il est avant : `brain restore 1` l'annule (pas d'instantané quand rien n'est fait, sinon
            # `restore 1` ramènerait l'état d'après la première application)
            snap = history.snapshot("avant-regroupement", force=True)
        for it in chosen:
            if it.get("applied"):
                skipped.append(f"{it['n']} : déjà appliqué")
                continue
            if moved[it["n"]]:
                skipped.append(f"{it['n']} : `{moved[it['n']][0]}` a changé depuis la liste — relance `brain regroupe`")
                continue
            if it["kind"] == "doublon":
                b.merge(it["keep"], it["drop"])
                done.append(f"{it['n']} : `{it['drop']}` fusionné dans `{it['keep']}`")
            elif it["kind"] == "projet":
                b.update(it["id"], project=it["project"])
                b.nodes[it["id"]]["updated"] = now_iso()
                done.append(f"{it['n']} : `{it['id']}` rattaché au projet `{it['project']}`")
            else:
                f = b.add("reference", f"Fiche : {it['label']}", fiche_body(b, it["ids"]), project=it["project"],
                          tags=[it["label"]], importance=3, source="auto",
                          meta={"fiche": it["key"], "membres": list(it["ids"])})
                for i in it["ids"]:
                    b.link(i, f["id"], "part_of")
                done.append(f"{it['n']} : fiche `{f['id']}` créée, {len(it['ids'])} souvenirs reliés")
            it["applied"] = True
    write_json(PLAN_FILE, {"made": now_iso(), "items": items})
    return {"done": done, "skipped": skipped, "snap": snap}


def ecarter(spec) -> list:
    """Ne plus proposer ces numéros de la liste gardée. → lignes de compte rendu."""
    items = saved()
    chosen = [items[k - 1] for k in parse_numbers(spec, len(items))]
    raw = read_json(ECARTES_FILE, {}) or {}
    keep = list(raw.get("items", [])) if isinstance(raw, dict) else []
    out = []
    for it in chosen:
        if it["kind"] == "doublon":
            keep.append(["doublon", sorted((it["keep"], it["drop"]))])
        elif it["kind"] == "projet":
            keep.append(["projet", it["id"], it["project"]])
        else:
            keep.append(["fiche", it["key"], it["project"]])
        out.append(f"{it['n']} : écarté, il ne sera plus proposé")
    write_json(ECARTES_FILE, {"items": keep})
    return out
