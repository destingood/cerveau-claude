"""Provenance des souvenirs par session et journal de leurs textes (étape 21 du plan, d'après `remove_episode` de
graphiti et la table history de mem0). `brain oublier-session` s'en sert (oubli.py).

- `meta.sessions` : les sessions Claude Code qui ont écrit un souvenir (ids seuls, de la plus ancienne à la plus
  récente, SESSIONS_MAX au plus : la première reste). Absent sur un souvenir d'avant : liste vide, rien n'est réécrit.
  Mode wiki : propriété `sessions` de la page.
- D'où vient l'id : l'entrée JSON d'un hook (`session_id`), sinon la variable CLAUDE_CODE_SESSION_ID que Claude Code
  pose dans les commandes de l'outil Bash, les hooks et les serveurs MCP stdio (documentation de Claude Code lue le
  28/11/2026 ; un serveur MCP garde l'id de son lancement, même après /clear). Sans elle (Claude Code ancien, terminal
  de l'utilisateur, app Claude par MCP) et dans une tâche de fond (BRAIN_BG : rêve, synchronisation du wiki…), aucune
  session n'est notée : `oublier-session` ne retire jamais ce qui a été écrit ainsi.
- history/textes.jsonl : à chaque écriture d'un souvenir, l'ancienne et la nouvelle valeur des champs changés (titre,
  contenu, type, étiquettes, importance, projet, statut, dates…), la session et l'heure. Hors du graphe : graph.json
  ne grossit pas, et aucun hook ne le lit. Borné : VERSIONS_MAX modifications par souvenir, JOURNAL_MAX octets en tout.
  Les secrets y sont masqués comme partout ; une suppression définitive y efface le souvenir."""
from __future__ import annotations

import json
import os

from . import common
from .common import BRAIN_DIR, log, now_iso, short

JOURNAL_FILE = BRAIN_DIR / "history" / "textes.jsonl"
JOURNAL_MAX = 2 << 20  # octets : au-delà, les modifications les plus anciennes partent (créations et suppressions restent)
VERSIONS_MAX = 10  # modifications gardées par souvenir
SESSIONS_MAX = 5  # sessions notées par souvenir : la première, puis les plus récentes
TEXT_MAX = 8000  # caractères d'un champ gardés au journal ; au-delà, coupé (et `oublier-session` ne le remet pas)
FIELDS = ("title", "body", "type", "tags", "importance", "project", "status")
META_FIELDS = ("due", "done", "keys", "valid_from", "valid_to", "superseded_by", "merged_into", "end_reason", "niveau",
               "domaine", "resume", "sources")
LABELS = {"title": "titre", "body": "contenu", "type": "type", "tags": "étiquettes", "importance": "importance",
          "project": "projet", "status": "statut", "meta.due": "échéance", "meta.done": "fait le", "meta.keys": "mots-clés",
          "meta.valid_from": "début", "meta.valid_to": "fin", "meta.superseded_by": "remplacé par",
          "meta.merged_into": "fusionné dans", "meta.end_reason": "raison de fin", "meta.niveau": "niveau",
          "meta.domaine": "domaine", "meta.resume": "résumé", "meta.sources": "sources"}


# ------------------------------------------------------------------------------ la session courante
def clean_id(value):
    """Un id de session lisible (lettres, chiffres, - et _ ; 80 caractères au plus), sinon None."""
    v = "".join(c for c in str(value or "").strip() if c.isalnum() or c in "-_")[:80]
    return v or None


def current():
    """Session qui écrit en ce moment : celle du hook en cours, sinon celle que Claude Code donne à la commande. None
    dans une tâche de fond, ou hors de Claude Code."""
    if os.environ.get("BRAIN_BG") == "1":
        return None
    return clean_id(common.SESSION or os.environ.get("CLAUDE_CODE_SESSION_ID"))


def sessions_of(node) -> list:
    """Sessions qui ont écrit ce souvenir (absent : aucune ; un nombre ou une chaîne « a, b » d'une page éditée à la main
    sont relus comme des ids)."""
    raw = (node.get("meta") or {}).get("sessions") if isinstance(node, dict) else None
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for x in raw:
        x = clean_id(x)
        if x and x not in out:
            out.append(x)
    return out


def _stamp(node, sid) -> None:
    have = sessions_of(node)
    if sid in have:
        return
    have.append(sid)
    if len(have) > SESSIONS_MAX:
        del have[1]
    meta = dict(node.get("meta") or {})
    meta["sessions"] = have
    node["meta"] = meta


# ------------------------------------------------------------------------------ état d'un souvenir
def snap(node) -> dict:
    """Les champs suivis d'un souvenir (meta.X pour ceux de meta), en valeurs JSON."""
    out = {}
    for k in FIELDS:
        v = node.get(k)
        out[k] = list(v) if isinstance(v, (list, tuple)) else v  # une copie : une liste changée sur place ensuite
    meta = node.get("meta") or {}
    for k in META_FIELDS:
        if meta.get(k) not in (None, "", []):
            v = meta[k]
            out[f"meta.{k}"] = list(v) if isinstance(v, (list, tuple)) else v
    if out.get("status") is None:
        out["status"] = "active"
    return out


def _diff(before, after):
    keys = [k for k in dict.fromkeys([*before, *after]) if before.get(k) != after.get(k)]
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


def _safe(values, cut) -> dict:
    """Textes masqués (une clé collée autrefois ne passe pas au journal) et coupés à TEXT_MAX."""
    from .privacy import mask
    out = {}
    for k, v in values.items():
        if isinstance(v, str):
            v = mask(v)[0]
            if len(v) > TEXT_MAX:
                v = v[:TEXT_MAX]
                cut.add(k)
        out[k] = v
    return out


def on_save(brain) -> None:
    """Appelé par Brain.save avant l'écriture : chaque souvenir créé ou modifié par ce cerveau (Brain._wrote) reçoit la
    session courante dans meta.sessions, et une ligne au journal. Brain._oubli (oubli.py) : ces écritures défont celles
    d'une session ; notées comme telles, elles ne font pas de la session courante un auteur. Jamais bloquant."""
    seen = brain.__dict__.pop("_avant", None)
    forgot = brain.__dict__.pop("_oubli", None)
    if not seen:
        return
    sid, ts, rows, purged = current(), now_iso(), [], set()
    for nid, before in seen.items():
        n = brain.nodes.get(nid)
        row = {"le": ts, "id": nid}
        if sid:
            row["s"] = sid
        if forgot:
            row["oubli"] = forgot
        if n is None:
            if before is not None:  # supprimé pour de bon : son texte quitte aussi le journal
                purged.add(nid)
                rows.append({**row, "op": "purge"})
            continue
        if before is None:
            row["op"] = "ajout"
        else:
            avant, apres = _diff(before, snap(n))
            if not avant:
                continue
            cut = set()
            row.update(op="modif", avant=_safe(avant, cut), apres=_safe(apres, cut))
            if cut:
                row["coupe"] = sorted(cut)
        if sid and not forgot:
            _stamp(n, sid)
        rows.append(row)
    try:
        _write(rows, purged)
    except Exception as exc:
        log(f"journal des textes : {exc!r}")


# ------------------------------------------------------------------------------ le journal
def rows(nid=None) -> list:
    """Lignes du journal, de la plus ancienne à la plus récente (une ligne abîmée est sautée)."""
    out = []
    try:
        text = JOURNAL_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for raw in text.splitlines():
        try:
            r = json.loads(raw)
        except ValueError:
            continue
        if isinstance(r, dict) and isinstance(r.get("id"), str) and r.get("op") in ("ajout", "modif", "purge") \
                and (nid is None or r["id"] == nid):
            if r["op"] == "modif" and not (isinstance(r.get("avant"), dict) and isinstance(r.get("apres"), dict)):
                continue
            out.append(r)
    return out


def _line(r) -> str:
    return json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"


def _write(new, purged=()) -> None:
    if not new:
        return
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(_line(r) for r in new)
    try:
        size = JOURNAL_FILE.stat().st_size
    except OSError:
        size = 0
    if not purged and size + len(text) <= JOURNAL_MAX:
        with open(JOURNAL_FILE, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return
    gone = set(purged)
    old = [r for r in rows() if r["id"] not in gone or r["op"] == "purge"]
    from .common import write_text
    write_text(JOURNAL_FILE, "".join(_line(r) for r in prune(old + new)))


def prune(all_rows) -> list:
    """VERSIONS_MAX modifications par souvenir, puis JOURNAL_MAX / 2 octets en tout : les modifications les plus
    anciennes partent d'abord ; les lignes de création et de suppression, petites, restent."""
    count, keep = {}, [True] * len(all_rows)
    for i in range(len(all_rows) - 1, -1, -1):
        r = all_rows[i]
        if r["op"] == "modif":
            count[r["id"]] = count.get(r["id"], 0) + 1
            keep[i] = count[r["id"]] <= VERSIONS_MAX
    sizes = [len(_line(r)) for r in all_rows]
    total = sum(s for s, k in zip(sizes, keep) if k)
    for i, r in enumerate(all_rows):
        if total <= JOURNAL_MAX // 2:
            break
        if keep[i] and r["op"] == "modif":
            keep[i] = False
            total -= sizes[i]
    return [r for r, k in zip(all_rows, keep) if k]


# ------------------------------------------------------------------------------ affichage (`brain show`)
def short_id(sid) -> str:
    return str(sid or "")[:8] or "?"


def value_text(key, v) -> str:
    if v in (None, "", []):
        return "rien"
    if key == "status":
        return {"active": "actif", "archived": "archivé"}.get(v, str(v))
    if isinstance(v, list):
        return ", ".join(map(str, v))
    return f"« {short(str(v).replace(chr(10), ' '), 70)} »" if isinstance(v, str) else str(v)


def change_text(avant, apres) -> str:
    parts = []
    for k in apres:
        a, b = avant.get(k), apres.get(k)
        if k == "body" and isinstance(a, str) and isinstance(b, str) and (len(a) > 70 or len(b) > 70):
            parts.append(f"contenu {len(a)} → {len(b)} car.")
        else:
            parts.append(f"{LABELS.get(k, k)} {value_text(k, a)} → {value_text(k, b)}")
    return " · ".join(parts)


def history_lines(nid) -> list:
    """Le journal d'un souvenir, pour `show --history` : chaque écriture, sa session, l'ancien et le nouveau texte."""
    from .common import fmt_date
    out = []
    for r in rows(nid):
        when = f"{fmt_date(r['le'])[:5]} {str(r['le'])[11:16]}"
        who = f"session {short_id(r['s'])}" if r.get("s") else "sans session"
        if r["op"] == "ajout":
            out.append(f"  {when} · {who} — créé")
        elif r["op"] == "purge":
            out.append(f"  {when} · {who} — supprimé définitivement")
        else:
            out.append(f"  {when} · {who} — {change_text(r['avant'], r['apres'])}")
            old = r["avant"].get("body")
            if isinstance(old, str) and "body" in r["apres"] and old:
                out.append(f"      ancien contenu : {short(old.replace(chr(10), ' '), 300)}")
    return out
