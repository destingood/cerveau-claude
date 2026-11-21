"""Réparation d'un graph.json abîmé sans perdre de souvenir (étape 7 du plan).

Avant, le cerveau repartait du dernier instantané, qui peut dater de 30 minutes : les souvenirs de la dernière
demi-heure disparaissaient. Maintenant, dans l'ordre :
1. la base : la copie lisible la plus récente — la version d'avant la dernière écriture (history/precedent.json),
   sinon le dernier instantané, sinon la dernière sauvegarde ;
2. par-dessus, les écritures notées depuis (history/recents.jsonl : souvenirs touchés, suppressions définitives) ;
3. par-dessus, chaque souvenir et chaque lien encore lisible dans le fichier abîmé lui-même (le plus récent).
Le fichier abîmé est gardé à côté (graph.corrupt-….json), jamais un cerveau vide n'est écrit, et l'utilisateur
l'apprend une fois, au démarrage suivant, avec les nombres (common.tell_user)."""
from __future__ import annotations

import json
import re
import time
import zipfile

from .common import GRAPH_FILE, LockBusy, log, tell_user, write_bytes, write_json

TOP_RX = re.compile(r'\n "((?:[^"\\\n]|\\.)*)": ')  # clés du premier niveau (graph.json est écrit avec indent=1)
NODE_RX = re.compile(r'\n  "((?:[^"\\\n]|\\.)*)": \{')  # un souvenir, dans "nodes"
EDGE_RX = re.compile(r"\n  \{")  # un lien, dans "edges"


def _is_node(n, nid=None) -> bool:
    return (isinstance(n, dict) and isinstance(n.get("id"), str) and n["id"] and (nid is None or n["id"] == nid)
            and isinstance(n.get("type"), str) and isinstance(n.get("title"), str))


def _is_edge(e) -> bool:
    return isinstance(e, dict) and all(isinstance(e.get(k), str) for k in ("from", "to", "rel"))


def _walk(value, out, depth=0):
    """JSON lisible mais pas à la forme d'un cerveau ({"nodes": [...]}, une liste…) : souvenirs et liens où qu'ils soient."""
    if depth > 4:
        return
    if _is_node(value):
        out["nodes"].setdefault(value["id"], value)
        return
    if _is_edge(value):
        out["edges"].append(value)
        return
    items = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
    for v in items:
        _walk(v, out, depth + 1)


def salvage(raw: bytes) -> dict:
    """Tout ce qui se lit encore dans un graph.json abîmé (coupé, octets nuls, ajout au bout, mauvaise forme).
    → {"top": clés du premier niveau, "nodes", "edges", "nodes_whole"/"edges_whole" : lus en entier ?}"""
    out = {"top": {}, "nodes": {}, "edges": [], "nodes_whole": False, "edges_whole": False}
    text = (raw or b"").decode("utf-8", "replace")  # octets nuls gardés : le JSON strict refuse le passage qui en contient
    dec = json.JSONDecoder()
    try:
        whole = json.loads(text)
    except ValueError:
        whole = None
    else:
        if isinstance(whole, dict) and isinstance(whole.get("nodes"), dict):  # lisible une fois les octets non UTF-8 remplacés
            out["nodes"] = {k: n for k, n in whole["nodes"].items() if _is_node(n, k)}
            out["edges"] = [e for e in whole.get("edges") or () if _is_edge(e)]
            out["top"] = {k: v for k, v in whole.items() if k not in ("nodes", "edges")}
            out["nodes_whole"] = out["edges_whole"] = True
        else:
            _walk(whole, out)
        return out
    for m in TOP_RX.finditer(text):
        try:
            key = json.loads(f'"{m.group(1)}"')
            val, _ = dec.raw_decode(text, m.end())
        except ValueError:
            continue
        if key == "nodes":
            if isinstance(val, dict):
                out["nodes"] = {k: n for k, n in val.items() if _is_node(n, k)}
                out["nodes_whole"] = True
        elif key == "edges":
            if isinstance(val, list):
                out["edges"] = [e for e in val if _is_edge(e)]
                out["edges_whole"] = True
        else:
            out["top"].setdefault(key, val)
    if not out["nodes_whole"]:  # souvenir par souvenir : ceux d'avant et d'après le passage abîmé
        for m in NODE_RX.finditer(text):
            try:
                key = json.loads(f'"{m.group(1)}"')
                val, _ = dec.raw_decode(text, m.end() - 1)
            except ValueError:
                continue
            if _is_node(val, key):
                out["nodes"][key] = val
    if not out["edges_whole"]:
        for m in EDGE_RX.finditer(text):
            try:
                val, _ = dec.raw_decode(text, m.end() - 1)
            except ValueError:
                continue
            if _is_edge(val):
                out["edges"].append(val)
    return out


def _valid(data) -> bool:
    return isinstance(data, dict) and isinstance(data.get("nodes"), dict)


PREV_LABEL = "la version d'avant la dernière écriture"


def _read_prev(p):
    return json.loads(p.read_bytes().decode("utf-8"))


def _read_zip(p):
    with zipfile.ZipFile(p) as z:
        return json.loads(z.read("graph.json").decode("utf-8"))


def base_copy():
    """La copie lisible la plus récente, d'après la date de son fichier (un instantané pris après la dernière écriture
    passe avant la version précédente) : version d'avant la dernière écriture, instantanés, sauvegardes.
    → (données, libellé, date de son contenu « AAAA-MM-JJTHH:MM:SS ») ou (None, None, None)."""
    import datetime as dt
    from . import backup, history
    cands = [(history.PREV_FILE, PREV_LABEL, _read_prev)]
    cands += [(p, "l'instantané", history.load) for p in history.snapshots()]
    cands += [(p, f"la sauvegarde {p.name}", _read_zip) for p in backup.backups()]
    dated = []
    for path, label, read in cands:
        try:
            dated.append((path.stat().st_mtime, path, label, read))
        except OSError:
            continue
    for mtime, path, label, read in sorted(dated, key=lambda x: x[0], reverse=True):
        try:
            data = read(path)
        except Exception:
            continue
        if _valid(data):  # date du contenu : celle de sa dernière écriture, sinon celle du fichier
            when = str(data.get("updated") or "") or dt.datetime.fromtimestamp(mtime).replace(microsecond=0).isoformat()
            return data, label, when
    return None, None, None


def _newer(a, b) -> bool:
    """La version a d'un souvenir est-elle au moins aussi récente que b ? (dates ISO, comparées comme du texte)"""
    return str(a.get("updated") or "") >= str(b.get("updated") or "")


def rebuild(raw):
    """→ (cerveau réparé, compte rendu) ou (None, None) s'il n'y a vraiment rien. Le compte rendu dit d'où vient chaque
    souvenir : la base, les écritures récentes, le fichier abîmé."""
    from . import history
    sal = salvage(raw)
    base, label, when = base_copy()
    if base is None and not sal["nodes"]:
        return None, None
    data = json.loads(json.dumps(base)) if base else {"version": 1, "nodes": {}, "edges": []}
    data.setdefault("edges", [])
    origin = {nid: "base" for nid in data["nodes"]}
    # Un souvenir absent du fichier abîmé n'est jamais pris pour une suppression : un passage abîmé peut donner un
    # JSON encore lisible où des souvenirs manquent. Seules les suppressions définitives notées dans le journal comptent.
    replayed = [r for r in history.recent() if not when or r["le"] >= when]
    for row in replayed:  # du plus ancien au plus récent (deux écritures de la même seconde : la dernière gagne)
        for nid, n in (row.get("n") or {}).items():
            have = data["nodes"].get(nid)
            if _is_node(n, nid) and (have is None or (have != n and _newer(n, have))):
                data["nodes"][nid] = n
                origin[nid] = "journal"
        for nid in row.get("x") or ():
            data["nodes"].pop(nid, None)
            origin.pop(nid, None)
    gone = {nid for r in replayed for nid in r.get("x") or ()} - {nid for r in replayed for nid in r.get("n") or ()}
    for nid, n in sal["nodes"].items():
        have = data["nodes"].get(nid)
        if nid in gone and have is None:
            continue
        if have is not None and "�" in json.dumps(n, ensure_ascii=False):
            continue  # octets abîmés dans ce souvenir : la copie intacte le garde
        if have is None or (have != n and _newer(n, have)):
            data["nodes"][nid] = n
            origin[nid] = "fichier"
    for k, v in sal["top"].items():  # premier niveau (dates, compteurs…) : celui du fichier abîmé, plus récent
        data[k] = v
    if sal["edges_whole"]:
        edges = sal["edges"]
    else:
        edges = list(data["edges"]) + [e for r in replayed for e in r.get("e") or () if _is_edge(e)] + sal["edges"]
    seen, data["edges"] = set(), []
    for e in edges:
        key = (e["from"], e["to"], e["rel"])
        if key not in seen and e["from"] in data["nodes"] and e["to"] in data["nodes"]:
            seen.add(key)
            data["edges"].append(e)
    counts = {k: sum(1 for v in origin.values() if v == k) for k in ("base", "journal", "fichier")}
    report = {"total": len(data["nodes"]), **counts, "label": label, "when": when, "whole": sal["nodes_whole"]}
    return data, report


def message(rep, kept) -> str:
    """Le compte rendu en une phrase, pour l'utilisateur."""
    from .common import fmt_date
    parts = []
    if rep["base"]:
        w = rep.get("when") or ""
        when = f" du {fmt_date(w)[:5]} à {w[11:16]}" if len(w) >= 16 and fmt_date(w) != "?" else ""
        parts.append(f"{rep['base']} repris de {rep['label']}{when}")
    if rep["journal"]:
        parts.append(f"{rep['journal']} retrouvé(s) dans le journal des écritures récentes")
    if rep["fichier"]:
        parts.append(f"{rep['fichier']} lu(s) dans le fichier abîmé")
    text = (f"⚠ Cerveau : graph.json était abîmé et a été réparé — {rep['total']} souvenir(s) : " + ", ".join(parts)
            + f". Le fichier abîmé est gardé : {kept}.")
    if not rep["whole"] and rep.get("label") and rep["label"] != PREV_LABEL:
        text += (" Ce qui a changé après la copie et n'était plus lisible a pu être perdu : `brain history` montre les "
                 "instantanés.")
    return text


def repair(raw):
    """graph.json illisible (octets `raw`) → cerveau réparé, réécrit sous le verrou du cerveau, ou None s'il n'y a rien
    pour le réparer. Si un autre processus l'a réparé entre-temps, c'est sa version qui sert."""
    from . import common, store
    lock = None if store._HELD else store.FileLock(store.LOCK_FILE, timeout=1.0 if common.HOOK else 6.0)
    try:
        if lock:
            lock.__enter__()
    except LockBusy:
        return rebuild(raw)[0]  # verrou occupé : réparé en mémoire seulement ; le prochain qui le lit l'enregistre
    try:
        try:
            now = GRAPH_FILE.read_bytes()
        except OSError:
            now = raw
        if now != raw:  # réparé (ou réécrit) par un autre processus pendant qu'on attendait le verrou
            try:
                data = json.loads(now.decode("utf-8"))
                if _valid(data):
                    return data
            except ValueError:
                raw = now
        data, rep = rebuild(raw)
        if data is None:
            return None
        kept = GRAPH_FILE.with_name(f"graph.corrupt-{time.strftime('%Y%m%d-%H%M%S')}.json")
        try:
            write_bytes(kept, raw)  # copie des octets lus : graph.json n'est jamais absent, même un instant
        except OSError as exc:
            log(f"réparation : copie du fichier abîmé impossible : {exc!r}")
        write_json(GRAPH_FILE, data)
        line = message(rep, kept.name)
        log("RÉPARATION : " + line)
        tell_user("reparation", line)
        return data
    finally:
        if lock:
            lock.__exit__(None, None, None)
