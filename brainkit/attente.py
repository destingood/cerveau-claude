"""Souvenirs en attente d'entrer dans graph.json (étape 22 du plan). Le hook d'un message « retiens que… » ne réécrit
plus tout le cerveau pour un souvenir (13 ms à 3 000 souvenirs sous Python 3.13, 44 ms sous 3.10 à 3.12, dont
l'encodeur JSON indenté est écrit en Python) : il ajoute ce qu'il écrit à graph-attente.json, à côté de graph.json.

- Chaque lecture du cerveau (store._load_graph) applique ces lignes : `brain q`, le serveur MCP, les autres hooks et la
  synchronisation du wiki voient le souvenir aussitôt.
- La tâche de fond que le même hook lance (vues.py) les fait entrer dans graph.json tout de suite, avant de refaire les
  vues ; toute écriture du cerveau aussi (Brain.save). graph.json note jusqu'où il les contient (« attente » : époque
  et numéro), puis ces lignes quittent le fichier d'attente : une ligne déjà dans graph.json (arrêt entre son écriture
  et le ménage) n'est jamais appliquée deux fois.
- Rien ne se perd sur un arrêt : le fichier est remplacé d'un coup (jamais à moitié écrit) avant que le hook ne rende la
  main ; illisible, il est mis de côté, jamais écrasé.
- Un lecteur qui ne connaît pas ce fichier (version d'avant, brain.exe, une copie de graph.json) voit le souvenir une
  fois entré dans graph.json, d'ordinaire moins d'une seconde après. S'il écrit le cerveau entre-temps, le souvenir
  reste en attente et entre à l'écriture suivante.

Format : {"id": époque, "n": dernier numéro, "lignes": [{"n", "le", "noeuds": {id: souvenir}, "liens": [liens
ajoutés]}]}. Les compteurs de rappel d'un souvenir déjà dans graph.json restent ceux de graph.json (compteurs.json s'y
ajoute à la lecture, comme pour les autres)."""
from __future__ import annotations

import json
import os
import time

from .common import BRAIN_DIR, log

FILE = BRAIN_DIR / "graph-attente.json"
COUNTS = ("hits", "last_hit", "used", "last_used")  # tenus par graph.json et compteurs.json, pas par l'attente
MAX_ROWS = 40  # au-delà (tâche de fond qui ne part jamais), l'écriture suivante réécrit graph.json elle-même
MAX_BYTES = 256 * 1024


def read():
    """→ (octets, stat, contenu) du fichier d'attente, ou None s'il n'y en a pas (ou s'il est illisible : ses lignes
    restent dans le fichier, une lecture suivante les verra ; graph.json ne note jamais les avoir)."""
    for attempt in range(8):
        try:
            with open(FILE, "rb") as fh:
                raw = fh.read()
                st = os.fstat(fh.fileno())
            break
        except FileNotFoundError:
            return None
        except OSError as exc:  # Windows : fichier en cours de remplacement
            if attempt == 7:
                log(f"attente : lecture : {exc!r}")
                return None
            time.sleep(0.02 * (attempt + 1))
    try:
        pend = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        log(f"attente : fichier illisible : {exc!r}")
        return None
    if isinstance(pend, dict) and pend.get("id") and isinstance(pend.get("n"), int) \
            and isinstance(pend.get("lignes"), list):
        return raw, st, pend
    return None


def apply(data, pend) -> tuple:
    """Lignes d'attente pas encore dans `data` (graph.json lu) appliquées en place → (époque, numéro jusqu'où `data` les
    contient désormais, lignes appliquées)."""
    mark = data.get("attente") if isinstance(data.get("attente"), dict) else {}
    since = mark.get("n", 0) if mark.get("id") == pend["id"] and isinstance(mark.get("n"), int) else 0
    nodes, edges, last, applied, have = data["nodes"], data.setdefault("edges", []), since, 0, None
    for row in sorted((r for r in pend["lignes"] if isinstance(r, dict) and isinstance(r.get("n"), int)),
                      key=lambda r: r["n"]):
        if row["n"] <= since:
            continue  # (déjà dans graph.json : arrêt entre son écriture et le ménage)
        for nid, node in (row.get("noeuds") or {}).items():
            if not (isinstance(node, dict) and node.get("id") == nid and node.get("title") and node.get("type")):
                continue
            new, old = dict(node), nodes.get(nid)
            if isinstance(old, dict):
                for k in COUNTS:
                    if k in old:
                        new[k] = old[k]
                    else:
                        new.pop(k, None)
            nodes[nid] = new
        for e in row.get("liens") or ():
            if not (isinstance(e, dict) and e.get("from") in nodes and e.get("to") in nodes and e.get("rel")):
                continue
            if have is None:
                have = {(x.get("from"), x.get("to"), x.get("rel")) for x in edges if isinstance(x, dict)}
            key = (e["from"], e["to"], e["rel"])
            if key not in have:
                have.add(key)
                edges.append(dict(e))
        if isinstance(row.get("le"), str) and row["le"] > str(data.get("updated") or ""):
            data["updated"] = row["le"]
        last, applied = max(last, row["n"]), applied + 1
    return pend["id"], last, applied


def _put_aside() -> None:
    """Fichier d'attente illisible : gardé à côté sous un autre nom (rien n'est jamais effacé), pour `brain doctor`."""
    try:
        os.replace(FILE, FILE.with_name(f"graph-attente.illisible-{time.strftime('%Y%m%d-%H%M%S')}.json"))
    except OSError as exc:
        log(f"attente : mise de côté : {exc!r}")


def _write(pend):
    """Le fichier remplacé d'un coup → (octets, stat) du fichier écrit (pris avant qu'il ne remplace l'ancien)."""
    raw = json.dumps(pend, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    tmp = FILE.with_name(f"{FILE.name}.{os.getpid()}.tmp")
    with open(tmp, "wb") as fh:
        fh.write(raw)
    st = os.stat(tmp)
    for attempt in range(8):
        try:
            os.replace(tmp, FILE)
            break
        except PermissionError:  # Windows : lu au même instant par un autre processus
            time.sleep(0.05 * (attempt + 1))
    else:
        os.replace(tmp, FILE)
    return raw, st


def add(nodes, edges, stamp, held):
    """Une ligne de plus (sous le verrou du graphe, que tient l'appelant) : `nodes` {id: souvenir tel qu'il est
    maintenant}, `edges` les liens ajoutés, `stamp` l'heure de l'écriture, `held` (époque, numéro) de ce que le cerveau
    de l'appelant contient déjà. → (octets, stat, époque, numéro de la ligne), ou None si l'attente est pleine ou
    illisible : à l'appelant de réécrire graph.json."""
    if FILE.exists():
        got = read()
        if got is None:
            _put_aside()
            return None
        pend = got[2]
        if held and held[0] != pend["id"]:
            return None  # époque changée depuis la lecture : graph.json réécrit, plus sûr
    else:
        pend = {"id": f"{time.time_ns():x}-{os.getpid():x}", "n": 0, "lignes": []}
    if len(pend["lignes"]) >= MAX_ROWS:
        return None
    pend["n"] += 1
    pend["lignes"].append({"n": pend["n"], "le": stamp, "noeuds": nodes, "liens": edges})
    raw, st = _write(pend)
    if len(raw) > MAX_BYTES:  # (gardé : la prochaine écriture réécrira graph.json et videra l'attente)
        log(f"attente : {len(raw) // 1024} Ko en attente")
    return raw, st, pend["id"], pend["n"]


def can_defer(brain) -> bool:
    """Écriture d'un cerveau qui peut aller dans le fichier d'attente (Brain.save(defer=True)) : cerveau classique lu de
    graph.json (ni wiki ni cerveau commun), des souvenirs écrits ou modifiés (Brain._wrote) et des liens ajoutés, rien
    d'autre (aucun lien retiré, aucune suppression définitive)."""
    from .common import commun_member
    return bool(brain.__dict__.get("_avant")) and brain._graph_part is not None and not brain._purged \
        and not brain.data.get("wiki") and not brain.data.get("commun") and brain.data["edges"] is brain._edges0 \
        and len(brain.edges) >= brain._e0 and not commun_member()


def defer(brain, ids) -> bool:
    """Brain.save(defer=True) : les souvenirs `ids` et les liens ajoutés depuis la lecture → une ligne d'attente (add),
    notée aussi dans history/recents.jsonl comme une écriture de graph.json. → False s'il faut réécrire graph.json
    (attente pleine ou illisible)."""
    from . import history
    from .store import _stamp
    held = brain._attente
    try:
        got = add({i: brain.nodes[i] for i in ids if i in brain.nodes}, brain.edges[brain._e0:], brain.data["updated"],
                  held)
    except OSError as exc:
        log(f"attente : {exc!r}")
        got = None
    if got is None:
        return False
    raw, st, epoch, num = got
    brain._note_writes(brain.data, history)
    brain.dirty = False
    brain.stamp = f"{brain._graph_part}+{_stamp(raw, st)}"
    brain._attente = (epoch, num, (held[2] if held and held[0] == epoch else 0) + 1, brain._graph_part)
    return True


def settle(epoch, num) -> bool:
    """Après l'écriture de graph.json, sous le verrou du graphe : les lignes qu'il contient désormais quittent le
    fichier d'attente (le fichier disparaît s'il ne reste rien). → reste-t-il des lignes ?"""
    got = read()
    if got is None:
        return FILE.exists()
    pend = got[2]
    if pend["id"] != epoch:
        return True
    rows = [r for r in pend["lignes"] if isinstance(r, dict) and isinstance(r.get("n"), int) and r["n"] > num]
    try:
        if rows:
            if len(rows) != len(pend["lignes"]):
                pend["lignes"] = rows
                _write(pend)
            return True
        FILE.unlink()
    except OSError as exc:
        log(f"attente : ménage : {exc!r}")
        return True
    return False


def absorb(timeout=6.0) -> bool:
    """Les souvenirs en attente entrent dans graph.json (tâche de fond des vues, avant une copie de graph.json :
    sauvegarde, restauration). → graph.json réécrit ?"""
    if not FILE.exists():
        return False
    from .store import Brain
    with Brain.edit(timeout=timeout) as b:
        held = getattr(b, "_attente", None)
        if held and held[2]:
            b.dirty = True
        elif held:  # lignes déjà dans graph.json (arrêt avant le ménage) : seulement le ménage
            settle(held[0], held[1])
    return bool(held and held[2])
