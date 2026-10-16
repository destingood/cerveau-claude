"""Historique du cerveau : instantanés compressés de graph.json, pour revenir en arrière.

- automatique : avant une écriture, au plus un instantané toutes les 30 minutes (l'état d'avant la modification) ;
- forcé avant toute opération destructrice (suppression définitive, consolidation, restauration) ;
- 60 instantanés gardés (quelques Ko chacun). `brain history` les liste, `brain restore <n>` en remet un
  (l'état courant est d'abord sauvegardé : une restauration s'annule elle-même)."""
from __future__ import annotations

import gzip
import json
import os
import re
import time

from .common import BRAIN_DIR, GRAPH_FILE, log, slugify

HIST_DIR = BRAIN_DIR / "history"
KEEP = 60
AUTO_EVERY = 1800


NAME_RX = re.compile(r"graph-(\d{8})-(\d{6})(?:-(\d{3}))?-(.+)\.json\.gz$")


def parse(path):
    """→ (date AAAAMMJJ, heure HHMMSS, millisecondes, raison) d'après le nom du fichier."""
    m = NAME_RX.match(path.name)
    return (m.group(1), m.group(2), m.group(3) or "000", m.group(4)) if m else ("", "", "000", path.name)


def snapshots():
    """Du plus récent au plus ancien (horodatage à la milliseconde : deux instantanés de la même seconde restent ordonnés)."""
    if not HIST_DIR.exists():
        return []
    return sorted(HIST_DIR.glob("graph-*.json.gz"), key=lambda p: (parse(p)[:3], p.stat().st_mtime_ns), reverse=True)


def snapshot(reason="auto", force=False):
    """Copie compressée de graph.json tel qu'il est sur le disque (avant la modification en cours)."""
    try:
        if not GRAPH_FILE.exists():
            return None
        snaps = snapshots()
        if not force and snaps and time.time() - snaps[0].stat().st_mtime < AUTO_EVERY:
            return None
        HIST_DIR.mkdir(parents=True, exist_ok=True)
        now = time.time()
        path = HIST_DIR / f"graph-{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}-{int(now * 1000) % 1000:03d}-{slugify(reason, 24)}.json.gz"
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        with gzip.open(tmp, "wb", compresslevel=6) as fh:
            fh.write(GRAPH_FILE.read_bytes())
        os.replace(tmp, path)
        for old in snapshots()[KEEP:]:
            old.unlink()
        return path
    except Exception as exc:  # l'historique ne doit jamais empêcher une écriture
        log(f"instantané : {exc!r}")
        return None


def load(path) -> dict:
    with gzip.open(path, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def find(ref):
    """Instantané par numéro (1 = le plus récent) ou par début de nom (date « 20261016-0130 »…)."""
    snaps = snapshots()
    ref = str(ref).strip()
    if ref.isdigit() and 1 <= int(ref) <= len(snaps):
        return snaps[int(ref) - 1]
    for p in snaps:
        if p.name.startswith(f"graph-{ref}") or ref in p.name:
            return p
    return None


def state_at(stamp):
    """État du graphe à une date « AAAAMMJJ-HHMMSS » : le premier instantané pris APRÈS cette date contient l'état
    d'alors (il est pris juste avant la modification suivante) ; sans instantané plus récent, c'est l'état actuel.
    Précision : à 30 minutes près (rythme des instantanés automatiques). → (données, libellé) ou (None, raison)."""
    snaps = list(reversed(snapshots()))  # du plus ancien au plus récent
    if not snaps:
        return None, "aucun instantané"
    first = parse(snaps[0])
    if stamp < f"{first[0]}-{first[1]}":
        return None, f"historique disponible depuis le {first[0][6:8]}/{first[0][4:6]}/{first[0][:4]} {first[1][:2]}:{first[1][2:4]}"
    for p in snaps:
        day, hms, _, _ = parse(p)
        if f"{day}-{hms}" > stamp:
            return load(p), p.name
    from .common import read_json
    return read_json(GRAPH_FILE, None), "état actuel"


def versions(nid):
    """Versions successives d'un souvenir à travers les instantanés (puis l'état actuel)."""
    from .common import read_json
    out, last = [], None
    items = [(p, parse(p)) for p in reversed(snapshots())]
    for p, (day, hms, _, _) in items + [(None, ("maintenant", "", "", ""))]:
        try:
            data = load(p) if p else read_json(GRAPH_FILE, None)
        except Exception:
            continue
        n = (data or {}).get("nodes", {}).get(nid)
        sig = None if not n else (n.get("title"), n.get("body", ""), n.get("status", "active"), n.get("importance", 3),
                                  tuple(n.get("tags") or []), (n.get("meta") or {}).get("due"))
        if sig != last:
            out.append((day, hms, n))
            last = sig
    return out


def describe(path) -> dict:
    try:
        d = load(path)
        nodes = d.get("nodes", {})
        active = sum(1 for n in nodes.values() if n.get("status", "active") == "active")
        return {"nodes": len(nodes), "active": active, "edges": len(d.get("edges", []))}
    except Exception:
        return {"nodes": "?", "active": "?", "edges": "?"}
