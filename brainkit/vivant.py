"""Rappel plus vivant (plan, étape 14, point 9 ; d'après ACT-R, mem0, graphiti) : l'usage réel des souvenirs
réordonnerait-il utilement le rappel ? Mesure seulement, pour `brain bench` : le rappel des hooks n'en dépend pas.

- Activation de base d'ACT-R : Σ t^-d sur les reprises passées d'un souvenir (t en jours, d = 0,5), approchée d'après
  le compte et la dernière reprise (Petrov 2006), comme le cerveau les tient déjà (« montré ≠ utilisé » : `used`,
  `last_used`). Elle donnerait un petit bonus de rang (au plus +20 % de pertinence, pour l'ordre seulement) à un
  souvenir que Claude a vraiment repris, récemment ou souvent, APRÈS le classement (règle fixe ou neurone appris) :
  jamais un filtre, un souvenir jamais repris garde son rang, aucun n'est caché.
- Le neurone n'y est pas touché : ni ses traits, ni ses poids, ni son fichier ; un modèle déjà appris sert tel quel.
- Mesure sur les échanges de l'utilisateur : ses exemples étiquetés (ceux du neurone, state/neurone-ex.jsonl) sont
  rejoués dans l'ordre du temps, avec le classement en service seul puis avec l'usage en plus, l'usage de chaque
  souvenir pris dans les seuls messages d'avant (aucune fuite du futur).

Mesuré le 28/11 sur le banc du rappel : rien de gagné (58/62, 2 faux rappels, avec ou sans), ni sur un mois simulé de
ses questions posées et reposées (souvenirs utiles montrés identiques, 6 tirages) : le cerveau d'essai a rarement plus
de 3 souvenirs acceptés pour un message, et l'ordre de ceux qui sont montrés ne change pas ce que Claude lit. Pas mis
en service ; cette mesure dit, sur un vrai cerveau, si l'usage y changerait quelque chose. Écartée de même : la
diversité (MMR) — rien de gagné, et une session longue rappelait moins (28 questions sur 58 au lieu de 33)."""
from __future__ import annotations

import datetime as _dt
import math

from .common import parse_iso

DECAY = 0.5  # d d'ACT-R
USAGE_W = 0.2  # bonus de pertinence au plus (pour l'ordre) ; a / (1 + a) : une reprise d'hier en vaut la moitié
MIN_T = 1 / 24  # une reprise de moins d'une heure compte comme une heure (t^-d borné)


def _days(a, b) -> float:
    return max(0.0, (b - a).total_seconds() / 86400) if a and b else 0.0


def strength(k, last, created, now) -> float:
    """Σ t^-d de k reprises, la dernière à `last`, les autres réparties entre `created` et elle (Petrov 2006). 0 sans
    reprise."""
    if not isinstance(k, (int, float)) or isinstance(k, bool) or k <= 0 or last is None or now is None:
        return 0.0
    t = max(MIN_T, _days(last, now))
    a = t ** -DECAY
    life = max(t, _days(created, now)) if created else t
    if k > 1 and life > t:
        a += (k - 1) * (life ** (1 - DECAY) - t ** (1 - DECAY)) / ((1 - DECAY) * (life - t))
    return a


def activation(n, now=None) -> float:
    """Activation d'un souvenir d'après ses compteurs (absents, d'un ancien graphe : 0, jamais d'erreur)."""
    return strength(n.get("used") or 0, parse_iso(n.get("last_used")), parse_iso(n.get("created")),
                    now or _dt.datetime.now())


def order(nodes, rel, now=None) -> list:
    """Ordre de présentation de souvenirs déjà retenus (`rel` : leur pertinence, score ou probabilité du neurone, dans
    l'ordre du classement) → indices, tous gardés. Sans usage : l'ordre du classement, inchangé (tri stable)."""
    if len(nodes) < 2:
        return list(range(len(nodes)))
    now = now or _dt.datetime.now()
    key = []
    for n, x in zip(nodes, rel):
        a = activation(n, now)
        key.append(x * (1 + USAGE_W * a / (1 + a)))
    return sorted(range(len(nodes)), key=lambda i: -key[i])


def replay(rows, rc, model=None, created=None) -> dict:
    """Rejoue les exemples étiquetés (neurone-ex.jsonl), message par message dans l'ordre du temps, avec le classement en
    service seul (règle fixe, ou neurone appris `model`) puis avec l'usage en plus. L'usage d'un souvenir à un message :
    ses reprises dans les messages d'avant seulement (montré par le classement seul et utile, une fois par session, comme
    le compte de fin de tâche). → {"regle"|"neurone": {...}, "usage": {...}, "messages": n}."""
    from . import neurone
    created = created or {}
    groups = {}
    for r in rows:
        groups.setdefault((r["s"], r["t"]), []).append(r)
    msgs = [(k, sorted(groups[k], key=lambda r: r["f"][4])) for k in sorted(groups, key=lambda k: k[1])]
    wide = dict(rc, max_items=neurone.TOP)  # sans plafond : le plafond vient après l'ordre
    base = neurone._model_pick(model, wide) if model is not None else neurone._rule_pick(wide)
    top = rc["max_items"]
    hist, inj_by, done_by, snap = {}, {}, {}, {}
    for k, rs in msgs:  # usage connu avant chaque message : ce que le classement seul a montré et qui a servi
        snap[id(rs)] = (parse_iso(k[1]), {r["id"]: dict(hist[r["id"]]) for r in rs if r["id"] in hist})
        inj, done = inj_by.setdefault(k[0], set()), done_by.setdefault(k[0], set())
        for i, _ in base(rs, inj)[:top]:
            r = rs[i]
            inj.add(r["id"])
            if r["y"] and r["id"] not in done:
                done.add(r["id"])
                h = hist.setdefault(r["id"], {"used": 0, "created": created.get(r["id"]) or k[1]})
                h["used"] += 1
                h["last_used"] = k[1]

    def plain(rs, inj):
        return base(rs, inj)[:top]

    def lively(rs, inj):
        when, h = snap[id(rs)]
        got = base(rs, inj)
        rel = [model.predict(rs[i]["f"]) if model is not None else math.expm1(rs[i]["f"][0]) for i, _ in got]
        return [got[j] for j in order([h.get(rs[i]["id"], {}) for i, _ in got], rel, when)][:top]

    return {"neurone" if model is not None else "regle": neurone._simulate(msgs, plain, rc),
            "usage": neurone._simulate(msgs, lively, rc), "messages": len(msgs)}


def measure(brain=None) -> dict:
    """La mesure sur les échanges de cet utilisateur (exemples du neurone), avec le classement en service : le neurone
    s'il est appris (et `recall.neurone` pas sur « off »), sinon la règle fixe. Rien n'est écrit."""
    from . import neurone
    from .common import load_config
    rc = load_config()["recall"]
    model = neurone.load() if rc.get("neurone", "auto") != "off" else None
    created = {k: n.get("created") for k, n in brain.nodes.items()} if brain is not None else {}
    res = replay(neurone._read_rows(), rc, model, created)
    res["with"] = "neurone" if model is not None else "regle"
    return res


def line(res) -> str:
    """Ligne de `brain bench`."""
    if not res["messages"]:
        return ("Usage (ACT-R) : pas encore d'échanges étiquetés à rejouer (exemples du neurone du rappel) ; le rappel "
                "ne s'en sert pas")
    a, b = res[res["with"]], res["usage"]
    who = "le neurone" if res["with"] == "neurone" else "la règle fixe"
    return (f"Usage (ACT-R), rejoué sur tes {res['messages']} derniers messages étiquetés : {a['utiles']} souvenirs utiles "
            f"montrés par {who} seul, {b['utiles']} avec l'usage ({a['tokens']} → {b['tokens']} tokens) ; mesure seulement, "
            "le rappel ne s'en sert pas")
