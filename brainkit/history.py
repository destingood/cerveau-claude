"""Historique du cerveau : instantanés compressés de graph.json, pour revenir en arrière.

- automatique : avant une écriture, au plus un instantané toutes les 30 minutes (l'état d'avant la modification) ;
- forcé avant toute opération destructrice (suppression définitive, consolidation, restauration) ;
- 60 instantanés gardés (quelques Ko chacun). `brain history` les liste, `brain restore <n>` en remet un
  (l'état courant est d'abord sauvegardé : une restauration s'annule elle-même).

Pour réparer un graph.json abîmé sans perdre la dernière demi-heure (reparation.py), deux filets à chaque écriture :
- `precedent.json` : la version d'avant la dernière écriture, gardée par un lien vers l'ancien fichier (0,1 ms ; une
  copie là où le disque n'a pas de liens). Un instantané compressé à chaque écriture coûterait 150 ms à 10 000
  souvenirs (mesuré le 21/11/2026), le lien rien ;
- `recents.jsonl` : les souvenirs touchés par chaque écriture (et ceux supprimés pour de bon), quelques centaines
  d'écritures au plus. Le journal des sessions ne garde pas le contenu des souvenirs : il ne permet pas de les rejouer."""
from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import time

from .common import BRAIN_DIR, GRAPH_FILE, log, slugify

HIST_DIR = BRAIN_DIR / "history"
KEEP = 60
AUTO_EVERY = 1800
PREV_FILE = HIST_DIR / "precedent.json"
RECENT_FILE = HIST_DIR / "recents.jsonl"
RECENT_MAX = 1 << 20  # octets : au-delà, la moitié la plus ancienne part (des centaines d'écritures restent)
_NO_LINK = []  # disque sans liens (FAT, certains partages) : copie, essayée une seule fois par processus


def keep_previous(copy=False) -> None:
    """graph.json tel qu'il est sur le disque devient precedent.json, juste avant d'être remplacé (lien : l'ancien fichier
    n'est plus nommé graph.json ensuite ; copy=True quand graph.json reste en place). Jamais bloquant."""
    try:
        if not GRAPH_FILE.exists():
            return
        HIST_DIR.mkdir(parents=True, exist_ok=True)
        tmp = PREV_FILE.with_name(f"{PREV_FILE.name}.{os.getpid()}.tmp")
        tmp.unlink(missing_ok=True)
        if not _NO_LINK and not copy:
            try:
                os.link(GRAPH_FILE, tmp)
            except OSError:
                _NO_LINK.append(1)
        if _NO_LINK or copy:
            shutil.copyfile(GRAPH_FILE, tmp)
        os.replace(tmp, PREV_FILE)
    except Exception as exc:  # comme un instantané : ne doit jamais empêcher une écriture
        log(f"version précédente : {exc!r}")


def restart() -> None:
    """Après une restauration (graph.json remplacé en entier) : l'état restauré devient la version précédente et les
    écritures récentes, celles de l'état quitté, sont oubliées (une réparation ne doit pas les rejouer)."""
    try:
        RECENT_FILE.unlink(missing_ok=True)
    except OSError as exc:
        log(f"écritures récentes : {exc!r}")
    keep_previous(copy=True)  # copie : graph.json reste en place, une modification sur place ne toucherait pas les deux


def record(stamp, nodes, removed=(), edges=()) -> None:
    """Une ligne de recents.jsonl : les souvenirs touchés par cette écriture, les ids supprimés pour de bon, les liens
    ajoutés. Jamais bloquant. Une suppression définitive efface aussi le souvenir des lignes plus anciennes."""
    if not (nodes or removed or edges):
        return
    try:
        HIST_DIR.mkdir(parents=True, exist_ok=True)
        row = {"le": stamp, "n": nodes}
        if removed:
            row["x"] = sorted(removed)
        if edges:
            row["e"] = list(edges)
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            size = RECENT_FILE.stat().st_size
        except OSError:
            size = 0
        if removed or size + len(line) > RECENT_MAX:
            rows = recent()
            if removed:
                gone = set(removed)
                for r in rows:
                    r["n"] = {k: v for k, v in (r.get("n") or {}).items() if k not in gone}
            text = "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows)
            if len(text) + len(line) > RECENT_MAX // 2:  # les lignes les plus récentes restent, coupées à une fin de ligne
                cut = text.find("\n", len(text) - RECENT_MAX // 2)
                text = text[cut + 1:] if cut >= 0 else ""
            from .common import write_text
            write_text(RECENT_FILE, text + line)
            return
        with open(RECENT_FILE, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
    except Exception as exc:
        log(f"écritures récentes : {exc!r}")


def recent() -> list:
    """Lignes lisibles de recents.jsonl, de la plus ancienne à la plus récente (une ligne abîmée est sautée)."""
    out = []
    try:
        text = RECENT_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for raw in text.splitlines():
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("le"), str) and isinstance(row.get("n", {}), dict):
            out.append(row)
    return out


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
