"""Le temps dans le graphe (plan, étape 11) : chaque souvenir et chaque lien porte ses dates.

- Validité d'un souvenir : du `meta.valid_from` (absent : sa date d'enregistrement) au `meta.valid_to`, dernier jour
  où il est vrai (absent : toujours vrai ; un souvenir archivé sans fin écrite a fini le jour de son archivage). Une fin
  posée à l'avance laisse le souvenir actif jusque-là ; l'entretien du jour l'archive le lendemain.
- Liens terminés : un lien retiré (`brain unlink`, lien disparu d'une page du wiki) n'est pas effacé, il passe dans
  `ended_edges` avec le jour où il a été retiré (`ended`). `Brain.edges` reste la liste des liens vivants : le rappel,
  le PageRank, les communautés et les fusions ne voient jamais un lien terminé. Une version plus ancienne du cerveau
  ignore cette liste et la garde telle quelle (graph.json s'écrit en entier).
- Lignée : « C ← B ← A », chaîne des remplacements, avec les dates et la raison (`meta.end_reason`).
- Deux axes : le domaine (celui du souvenir, sinon celui de son projet) et le niveau d'abstraction, déduit du type et
  corrigeable (`meta.niveau`).
- Le cerveau à une date sans instantané (`state_on`) : reconstruit d'après ces dates, avec le texte d'aujourd'hui.

Rien n'est réécrit à la lecture : un champ absent prend sa valeur déduite ici."""
from __future__ import annotations

import copy

from .common import fold, now_iso

ENDED = "ended_edges"
LEVELS = {"vision": "vision", "architecture": "architecture", "procedure": "procédure", "detail": "détail"}
LEVEL_ALIASES = {"vue": "vision", "strategie": "vision", "archi": "architecture", "conception": "architecture",
                 "methode": "procedure", "regle": "procedure", "recette": "procedure", "details": "detail",
                 "fait": "detail", "code": "detail", "log": "detail"}
TYPE_LEVEL = {"project": "vision", "user": "vision", "decision": "architecture", "concept": "architecture",
              "topic": "architecture", "analysis": "architecture", "feedback": "procedure", "learning": "procedure"}
# Domaines proposés (décision E19 du plan) ; `--domaine` reste libre, comme avant.
DOMAINS = ("code", "business", "contenu", "finance", "infra", "recherche", "perso")


def day(value) -> str | None:
    v = str(value or "")[:10]
    return v if len(v) == 10 and v[4] == "-" and v[7] == "-" else None


# ------------------------------------------------------------------ validité d'un souvenir
def valid_from(n) -> str | None:
    return day((n.get("meta") or {}).get("valid_from")) or day(n.get("created"))


def valid_to(n) -> str | None:
    """Dernier jour où le souvenir est vrai ; None : il l'est toujours."""
    end = day((n.get("meta") or {}).get("valid_to"))
    if end:
        return end
    return day(n.get("updated")) if n.get("status", "active") != "active" else None


def valid_on(n, when) -> bool:
    start, end = valid_from(n), valid_to(n)
    return (not start or start <= when) and (not end or when <= end)


def expired(n, today=None) -> bool:
    """Souvenir encore actif dont la fin écrite est passée (l'entretien du jour l'archive)."""
    end = day((n.get("meta") or {}).get("valid_to"))
    return n.get("status", "active") == "active" and bool(end) and end < (today or now_iso()[:10])


# ------------------------------------------------------------------ liens terminés
def ended(data) -> list:
    out = data.get(ENDED)
    return out if isinstance(out, list) else []


def end_edges(data, edges, when=None) -> int:
    """Les liens retirés passent dans `ended_edges`, datés du jour. → nombre ajouté."""
    when = when or now_iso()[:10]
    rows = ended(data)
    have = {(e.get("from"), e.get("to"), e.get("rel"), e.get("ended")) for e in rows}
    added = 0
    for e in edges:
        row = {"from": e["from"], "to": e["to"], "rel": e["rel"], "created": day(e.get("created")) or when,
               "ended": when}
        key = (row["from"], row["to"], row["rel"], when)
        if key not in have:
            have.add(key)
            rows.append(row)
            added += 1
    if added:
        data[ENDED] = rows
    return added


def forget_node(data, nid) -> None:
    """Suppression définitive d'un souvenir : ses liens terminés partent avec lui."""
    rows = ended(data)
    if any(nid in (e.get("from"), e.get("to")) for e in rows):
        data[ENDED] = [e for e in rows if nid not in (e.get("from"), e.get("to"))]


def edges_on(data, when) -> list:
    """Liens qui existaient ce jour-là : créés avant (ou ce jour), et pas encore retirés."""
    live = [e for e in data.get("edges") or [] if (day(e.get("created")) or "") <= when]
    old = [e for e in ended(data) if (day(e.get("created")) or "") <= when < (day(e.get("ended")) or "9999")]
    return live + [{k: e[k] for k in ("from", "to", "rel", "created") if k in e} for e in old]


# ------------------------------------------------------------------ le cerveau à une date
def state_on(data, when) -> dict:
    """État du graphe le jour `when` (AAAA-MM-JJ), reconstruit d'après les dates : les souvenirs valables ce jour-là
    (actifs dans l'état rendu), les liens qui existaient entre eux. Le texte est celui d'aujourd'hui."""
    nodes = {}
    for nid, n in (data.get("nodes") or {}).items():
        if not isinstance(n, dict) or not valid_on(n, when):
            continue
        if n.get("status", "active") != "active":
            n = copy.copy(n)
            n["status"] = "active"
        nodes[nid] = n
    edges = [e for e in edges_on(data, when) if e["from"] in nodes and e["to"] in nodes]
    out = {k: v for k, v in data.items() if k not in ("nodes", "edges", ENDED, "wiki")}
    out.update(nodes=nodes, edges=edges)
    return out


# ------------------------------------------------------------------ lignée
def lineage(brain, nid, limit=12) -> list:
    """Chaîne des remplacements qui passe par ce souvenir, du plus récent au plus ancien. [n] s'il n'en a pas."""
    nodes = brain.nodes
    cur, seen = nodes.get(nid), set()
    while cur and (cur.get("meta") or {}).get("superseded_by") in nodes and cur["id"] not in seen and len(seen) < limit:
        seen.add(cur["id"])
        cur = nodes[cur["meta"]["superseded_by"]]
    if not cur:
        return []
    olds = {}
    for e in list(brain.edges) + ended(brain.data):
        if e.get("rel") == "supersedes" and e.get("to") in nodes:
            olds.setdefault(e["from"], []).append(nodes[e["to"]])
    chain, seen = [cur], {cur["id"]}
    while len(chain) < limit:
        prev = [o for o in olds.get(chain[-1]["id"], []) if o["id"] not in seen]
        if not prev:
            break
        prev.sort(key=lambda o: valid_to(o) or "", reverse=True)
        chain.append(prev[0])
        seen.add(prev[0]["id"])
    return chain


def _fr(iso) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else "?"


def span(n) -> str:
    start, end = valid_from(n), valid_to(n)
    if end:
        return f"du {_fr(start)} au {_fr(end)}"
    return f"depuis le {_fr(start)}"


def lineage_line(chain) -> str:
    parts = []
    for n in chain:
        why = (n.get("meta") or {}).get("end_reason")
        inner = span(n) + (f", parce que {why}" if why else "")
        parts.append(f"`{n['id']}` ({inner})")
    return " ← ".join(parts)


# ------------------------------------------------------------------ dates dites dans le texte (étape 14, d'après graphiti)
_DATE_WORDS = (r"(\d{1,2}/\d{1,2}(?:/\d{2,4})?|\d{4}-\d{2}-\d{2}|(?:1er|\d{1,2})\s+(?:janv\w*|f[ée]v\w*|mars|avr\w*|mai|juin|"
               r"juil\w*|ao[uû]t|sept\w*|oct\w*|nov\w*|d[ée]c\w*)(?:\s+\d{4})?)")
_FROM_RX = None
_TO_RX = None


def text_dates(text, today=None) -> dict:
    """Début et fin de validité dits dans un texte : « depuis le 01/09 », « à partir du 1er janvier », « dès le … »,
    « jusqu'au 31/12 ». Une échéance (« d'ici le », « avant le ») n'est pas une fin. → {"valid_from"?, "valid_to"?}
    (AAAA-MM-JJ), proposés à Claude, jamais posés en silence."""
    import re
    from . import dates
    global _FROM_RX, _TO_RX
    if _FROM_RX is None:
        _FROM_RX = re.compile(r"\b(?:depuis\s+(?:le\s+)?|[àa]\s+partir\s+du?\s+|d[èe]s\s+le\s+)" + _DATE_WORDS, re.I)
        _TO_RX = re.compile(r"\bjusqu[’']?(?:au|à|a)\s+(?:le\s+)?" + _DATE_WORDS, re.I)
    out = {}
    m = _FROM_RX.search(str(text or ""))
    if m and dates.parse(m.group(1), today, nearest=True):
        out["valid_from"] = dates.parse(m.group(1), today, nearest=True)
    m = _TO_RX.search(str(text or ""))
    if m and dates.parse(m.group(1), today):
        out["valid_to"] = dates.parse(m.group(1), today)
    if out.get("valid_from") and out.get("valid_to") and out["valid_to"] < out["valid_from"]:
        out.pop("valid_to")
    return out


def end_for(old, new, today=None) -> tuple:
    """Fin de validité de `old` quand `new` le remplace (étape 14, d'après graphiti) : la veille du début écrit de
    `new` s'il en a un, sinon aujourd'hui ; jamais plus tard qu'une fin déjà écrite. → (fin, encore vrai aujourd'hui ?) :
    un remplaçant qui ne commence que plus tard laisse l'ancien vrai jusque-là."""
    import datetime as _dt
    today = today or now_iso()[:10]
    start = day((new.get("meta") or {}).get("valid_from"))
    end = today
    if start:
        end = (_dt.date.fromisoformat(start) - _dt.timedelta(days=1)).isoformat()
        end = max(end, valid_from(old) or end)  # jamais avant son propre début
    written = day((old.get("meta") or {}).get("valid_to"))
    if written:
        end = min(end, written)
    return end, end >= today and bool(start) and start > today


def starts_before(new, old) -> bool:
    """Le « nouveau » commence avant l'ancien (dates écrites) : ce n'est pas son remplaçant."""
    a, b = day((new.get("meta") or {}).get("valid_from")), valid_from(old)
    return bool(a and b and a < b)


def overlap(a, b) -> bool:
    """Les périodes écrites de deux souvenirs se chevauchent (sans date écrite : on ne sait pas, donc oui)."""
    ma, mb = a.get("meta") or {}, b.get("meta") or {}
    if not any(m.get(k) for m in (ma, mb) for k in ("valid_from", "valid_to")):
        return True
    a0, a1, b0, b1 = valid_from(a) or "", valid_to(a) or "9999", valid_from(b) or "", valid_to(b) or "9999"
    return a0 <= b1 and b0 <= a1


# ------------------------------------------------------------------ souvenirs en conflit, revue espacée
def _recency(n) -> tuple:
    return valid_from(n) or "", str(n.get("updated") or "")


def contradictions(edges, nodes) -> tuple:
    """Souvenirs montrés ensemble et liés par `contradicts` (étape 12) : le plus récent passe juste devant l'autre, et
    l'autre est noté. `nodes` dans l'ordre d'affichage → (même liste réordonnée, {id de l'ancien: id du récent})."""
    pos = {n["id"]: i for i, n in enumerate(nodes)}
    if len(pos) < 2:
        return list(nodes), {}
    notes, order = {}, list(nodes)
    for e in edges:
        if e.get("rel") != "contradicts" or e.get("from") not in pos or e.get("to") not in pos:
            continue
        a, b = nodes[pos[e["from"]]], nodes[pos[e["to"]]]
        new, old = (a, b) if _recency(a) >= _recency(b) else (b, a)
        notes[old["id"]] = new["id"]
        i, j = order.index(new), order.index(old)
        if i > j:  # le récent était après : il passe juste devant l'ancien
            order.insert(j, order.pop(i))
    return order, notes


REVIEW_FIRST, REVIEW_MAX = 30, 480  # jours : première revue, puis le délai double à chaque « toujours vrai »


def to_review(brain, limit=3, today=None) -> list:
    """Souvenirs importants (4 ou 5) qui n'ont ni servi ni été revus depuis leur délai de revue : à revoir, façon
    répétition espacée. → [(jours sans usage, souvenir)], les plus oubliés d'abord, `limit` au plus."""
    import datetime as _dt
    today = today or _dt.date.today()
    out = []
    for n in brain.active(own=True):
        if (n.get("importance", 3) or 3) < 4 or n["type"] == "project":
            continue
        meta = n.get("meta") or {}
        delay = int(meta.get("revue_delai") or REVIEW_FIRST)
        last = max(day(meta.get("revu_le")) or "", day(n.get("last_used")) or "", day(n.get("updated")) or "")
        if not last:
            continue
        idle = (today - _dt.date.fromisoformat(last)).days
        if idle >= delay:
            out.append((idle, n))
    out.sort(key=lambda x: (-x[0], x[1]["id"]))
    return out[:limit]


def reviewed(meta, today=None) -> dict:
    """« Toujours vrai » : la date de la revue est notée et le délai avant la suivante double (30, 60, 120… 480 j)."""
    meta = dict(meta or {})
    delay = int(meta.get("revue_delai") or REVIEW_FIRST)
    meta["revu_le"] = today or now_iso()[:10]
    meta["revue_delai"] = min(REVIEW_MAX, delay * 2)
    return meta


# ------------------------------------------------------------------ axes
def normalize_level(value) -> str | None:
    v = fold(value or "").strip()
    v = LEVEL_ALIASES.get(v, v)
    return v if v in LEVELS else None


def _first(value) -> str | None:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    v = str(value or "").split(",")[0].strip()
    return v or None


def axes(n, nodes=None) -> tuple:
    """→ (domaine ou None, niveau) : le domaine du souvenir, sinon celui de son projet ; le niveau écrit, sinon celui
    de son type."""
    meta = n.get("meta") or {}
    level = normalize_level(meta.get("niveau")) or TYPE_LEVEL.get(n.get("type"), "detail")
    domain = _first(meta.get("domaine"))
    if not domain and nodes and n.get("project") in nodes:
        domain = _first((nodes[n["project"]].get("meta") or {}).get("domaine"))
    return domain, level


def axes_line(n, nodes=None) -> str:
    domain, level = axes(n, nodes)
    return f"niveau {LEVELS[level]}" + (f" · domaine {domain}" if domain else "")
