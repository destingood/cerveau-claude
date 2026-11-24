"""Le wiki du cerveau, au quotidien (le « LLM Wiki » de Karpathy) : trois couches dans un dossier — un dépôt git
ouvert comme coffre Obsidian.

- `raw/` : les sources brutes (articles, PDF, transcriptions, notes, données, images dans raw/assets/), immuables ;
- `wiki/` : les pages, écrites et tenues à jour par Claude (souvenirs et pages de savoir), `archive/` pour l'ancien ;
- `CLAUDE.md` : le schéma (conventions, méthodes d'ingestion, de réponse, d'entretien), qui évolue avec l'usage.

Ce module : création du squelette et migration du cerveau classique (`init`), dépôt d'une source avec son plan
d'ingestion (`add_source`), sources en attente, catalogue `index.md` (régénéré), journal `log.md` (on ajoute en bas),
contrôle de santé (`lint`), état, synchronisation git (commit, pull --rebase, push ; automatique en début et fin de
session sur le PC, jamais dans une session cloud, qui pousse sur sa propre branche).

Le code est réparti en modules (découpage du 21/11/2026, sans changer le comportement) :
  wiki_textes   squelette : schéma CLAUDE.md, README, .gitignore, .gitattributes, lanceur cloud, `scaffold`
  wiki_journal  journal/<PC>/AAAA-MM.md (sessions et observations datées) et les sessions des autres PC
  wiki_git      synchronisation git sur plusieurs PC : conflits réglés seuls, git interrompu nettoyé
  wiki_sources  ingestion d'une source (fichier ou adresse web) et son plan d'ingestion
Ce module garde ce dont les hooks se servent (avis du démarrage, fin de session, index.md, log.md, état, contrôle
de santé) et `init` ; tous les noms d'avant le découpage restent accessibles ici (`wiki.sync`,
`from .wiki import add_source`…), chargés à la demande (__getattr__)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import wikistore as ws
from .common import (BRAIN_DIR, STATE_DIR, FileLock, fmt_date, fold, load_config, log, now_iso, read_json,
                     set_config, short, write_json, write_text)

INDEX, LOG, SCHEMA_FILE, README_FILE = "index.md", "log.md", "CLAUDE.md", "README.md"
JOURNAL_DIR = "journal"  # historique des sessions et des observations, mois par mois (généré)
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
          "décembre")
DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
TODO_MARK = "⏳ à remplir"
KNOWLEDGE = ("source", "entity", "concept", "topic", "analysis")
INDEX_ORDER = ("topic", "concept", "entity", "source", "analysis", "project", "decision", "fact", "learning",
               "reference", "feedback", "user", "todo")
LOG_HEAD = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\] ([^|\n]+?) \| (.*)$", re.M)
GIT_LOCK = STATE_DIR / "wiki-git.lock"
LOG_LOCK = STATE_DIR / "wiki-log.lock"
SYNC_STATE = STATE_DIR / "wiki-sync.json"


# ------------------------------------------------------------------------------------------ git
def git(root, *args, timeout=60):
    """git -C <wiki> … → (code, sortie). Jamais d'exception (git absent, délai dépassé)."""
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)


def is_repo(root) -> bool:
    return (Path(root) / ".git").exists()


def remote(root) -> str:
    code, out = git(root, "remote", "get-url", "origin", timeout=10)
    return out if code == 0 else ""


def _changes(root) -> list:
    """Chemins modifiés : [(état, chemin)] (format -z : noms accentués et espaces tels quels)."""
    try:
        r = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "-z", "-uall"], capture_output=True,
                           timeout=20, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode:
        return []
    rows, parts, i = [], r.stdout.decode("utf-8", "replace").split("\0"), 0
    while i < len(parts):
        item = parts[i]
        i += 1
        if len(item) < 4:
            continue
        state, path = item[:2], item[3:]
        if "R" in state or "C" in state:
            i += 1  # nom d'origine d'un renommage : l'entrée suivante
        rows.append((state.strip() or "?", path))
    return rows


def pc_name() -> str:
    """Nom de ce PC dans les copies de conflit (lettres, chiffres, tirets)."""
    import platform
    raw = os.environ.get("COMPUTERNAME") or platform.node() or ""
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", raw.split(".")[0]).strip("-")[:30]
    return name or "ce-PC"


# ------------------------------------------------------------------------------------------ index.md et log.md
def _summary(n, chars=130) -> str:
    """Résumé d'une page : sa propriété `resume`, sinon sa première ligne de texte (pas un intertitre)."""
    res = (n.get("meta") or {}).get("resume")
    if res:
        return short(res, chars)
    for line in str(n.get("body") or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return short(line.strip(" -*>`"), chars)
    return ""


def render_index(data, root) -> str:
    from .dates import due_of
    from .store import TYPES, priority
    nodes = [n for n in (data.get("nodes") or {}).values() if n.get("status", "active") == "active"
             and not n["id"].startswith("c--")]  # le wiki, ce sont mes pages (pas celles des amis)
    files = (data.get("wiki") or {}).get("files") or {}
    names = {nid: ws.stem(v["path"]) for nid, v in files.items() if v.get("path")}
    raw = raw_files(root)
    pend = len(pending(data, root, raw))
    archived = sum(1 for n in (data.get("nodes") or {}).values() if n.get("status", "active") != "active"
                   and not n["id"].startswith("c--"))
    out = ["# 📚 Index du wiki", "",
           f"_Catalogue régénéré par le cerveau — ne pas modifier à la main. {len(nodes)} pages · {len(raw)} sources "
           f"brutes" + (f" ({pend} à ingérer)" if pend else "") + f" · {archived} archivée{'s' if archived > 1 else ''}. Chercher : "
           "`brain q \"…\"` · schéma : [CLAUDE.md](CLAUDE.md) · journal : [log.md](log.md)._", ""]
    for t in INDEX_ORDER:
        items = [n for n in nodes if n["type"] == t]
        if not items:
            continue
        if t == "source":  # sources : les plus récentes d'abord
            items.sort(key=lambda n: (str(n.get("created") or ""), n["title"]), reverse=True)
        else:
            items.sort(key=lambda n: (-priority(n), fold(n["title"])))
        out += [f"## {ws.FOLDERS.get(t, TYPES.get(t, t))} ({len(items)})", ""]
        for n in items:
            name = names.get(n["id"]) or ws.fname(n["title"])
            bits = []
            if t == "todo" and due_of(n):
                bits.append(f"⏰ {fmt_date(due_of(n))}")
            srcs = (n.get("meta") or {}).get("sources")
            if isinstance(srcs, list) and srcs:
                bits.append(f"{len(srcs)} source{'s' if len(srcs) > 1 else ''}")
            summ = _summary(n)
            out.append(f"- [[{name}]]" + (f" — {summ}" if summ else "") + (f" · {' · '.join(bits)}" if bits else ""))
        out.append("")
    if not nodes:
        out += ["_Encore vide : le cerveau y range ses pages dès la migration (`brain wiki init`) ou la première source._",
                ""]
    return "\n".join(out).rstrip() + "\n"


def write_index(brain=None, root=None) -> bool:
    """index.md à jour (écrit seulement s'il change). → True s'il a été réécrit."""
    from .store import Brain
    root = Path(root or ws.root() or "")
    if not str(root) or not (root / ws.MARKER).is_file():
        return False
    brain = brain or Brain.load()
    text = render_index(brain.data, root)
    p = root / INDEX
    try:
        if p.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    write_text(p, text)
    return True


def log_append(op, title, lines=(), root=None, day=None) -> str:
    """Ajoute une entrée en bas de log.md : « ## [AAAA-MM-JJ] op | titre » puis une ligne par élément."""
    root = Path(root or ws.root() or "")
    if not str(root) or not (root / ws.MARKER).is_file():
        raise RuntimeError("pas de wiki : `brain wiki init <dossier>`")
    head = f"## [{day or now_iso()[:10]}] {' '.join(str(op).split())} | {' '.join(str(title).split())}"
    body = [ln if ln.lstrip().startswith(("-", ">", "*")) else f"- {ln}" for ln in (str(x).strip() for x in lines) if ln]
    with FileLock(LOG_LOCK, timeout=5):
        p = root / LOG
        try:
            cur = p.read_text(encoding="utf-8")
        except OSError:
            cur = "# 🗒️ Journal du wiki\n"
        write_text(p, cur.rstrip("\n") + "\n\n" + "\n".join([head, *body]) + "\n")
    return head


def log_entries(root=None, n=10) -> list:
    root = Path(root or ws.root() or "")
    try:
        text = (root / LOG).read_text(encoding="utf-8")
    except OSError:
        return []
    return [m.group(0) for m in LOG_HEAD.finditer(text)][-n:]


# ------------------------------------------------------------------------------------------ sources brutes
def raw_files(root) -> list:
    """Sources brutes (chemins relatifs POSIX), hors raw/assets/, fichiers cachés, fichiers vides et vues Bases
    d'Obsidian (.base) : un « Sans titre » créé dans raw/ par Obsidian n'est pas une source à ingérer."""
    base = Path(root) / ws.RAW
    out = []
    if not base.is_dir():
        return out
    for p in base.rglob("*"):
        rel = p.relative_to(root).as_posix()
        parts = rel.split("/")
        if not p.is_file() or any(x[:1] in "._" for x in parts[1:]) or (len(parts) > 2 and parts[1] == "assets"):
            continue
        try:
            if p.suffix.lower() == ".base" or not p.stat().st_size:
                continue
        except OSError:
            continue
        out.append(rel)
    return sorted(out)


def sha1_file(path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def content_digest(data: bytes) -> str:
    """Empreinte du contenu d'une source sans son en-tête de propriétés (titre, adresse, date de récupération) :
    le même article déposé deux fois, avec ou sans adresse, est reconnu."""
    if data.startswith(b"---"):
        end = data.find(b"\n---", 3)
        if end != -1:
            data = data[end + 4:]
    return hashlib.sha1(data.strip()).hexdigest()


def pending(data, root, raw=None) -> list:
    """Sources à ingérer : fichiers de raw/ sans page Sources, et pages Sources encore à remplir."""
    raw = raw_files(root) if raw is None else raw
    srcs = [n for n in (data.get("nodes") or {}).values() if n["type"] == "source" and not n["id"].startswith("c--")]
    known = {str((n.get("meta") or {}).get("brut") or "").replace("\\", "/").lower() for n in srcs}
    out = [{"raw": r, "page": None} for r in raw if r.lower() not in known]
    for n in srcs:
        if n.get("status", "active") == "active" and TODO_MARK in (n.get("body") or ""):
            out.append({"raw": (n.get("meta") or {}).get("brut"), "page": n})
    return out


def type_label(t) -> str:
    from .store import TYPES
    return TYPES.get(t, t)


# ------------------------------------------------------------------------------------------ contrôle de santé
def lint(brain, root=None, limit=12) -> dict:
    """Santé du wiki → {nom de section: [lignes]} (sections vides absentes)."""
    from .privacy import find as find_secrets
    root = Path(root or ws.root() or "")
    data = brain.data
    files = (data.get("wiki") or {}).get("files") or {}
    names = {nid: ws.stem(v["path"]) for nid, v in files.items() if v.get("path")}
    nodes = {k: v for k, v in data["nodes"].items() if not k.startswith("c--")}  # mes pages, pas celles des amis
    stems = {s.lower(): nid for nid, s in names.items()}
    find = ws._resolver(nodes, stems)
    active = [n for n in nodes.values() if n.get("status", "active") == "active"]
    inbound = {}
    for e in data["edges"]:
        if e["to"] in nodes:
            inbound[e["to"]] = inbound.get(e["to"], 0) + 1
    broken = {}
    for n in active:
        for t in ws.links_in(n.get("body", "")):
            if not find(t):
                broken.setdefault(t, set()).add(n["id"])
    out = {}
    if broken:
        rows = sorted(broken.items(), key=lambda kv: (-len(kv[1]), fold(kv[0])))
        out["Pages à créer (liens vers rien)"] = [
            f"[[{t}]] — cité par {len(ids)} page(s) : " + ", ".join(f"[[{names.get(i, i)}]]" for i in sorted(ids)[:4])
            for t, ids in rows[:limit]]
    know = [n for n in active if n["type"] in KNOWLEDGE]
    orph = [n for n in know if not inbound.get(n["id"]) and n["type"] != "source"]
    if orph:
        out["Pages orphelines (aucun lien n'y mène)"] = [f"[[{names.get(n['id'], n['title'])}]] ({type_label(n['type'])})"
                                                        for n in orph[:limit]]
    nores = [n for n in know if not (n.get("meta") or {}).get("resume") and TODO_MARK not in (n.get("body") or "")]
    if nores:
        out["Pages sans `resume:`"] = [f"[[{names.get(n['id'], n['title'])}]]" for n in nores[:limit]]
    raw = raw_files(root) if str(root) else []
    pend = pending(data, root, raw) if str(root) else []
    if pend:
        out["Sources à ingérer"] = [(f"{p['raw']} — page « {p['page']['title']} » à remplir" if p["page"]
                                     else f"{p['raw']} — pas encore de page : `brain wiki add {p['raw']}`")
                                    for p in pend[:limit]]
    srcbad = []
    for n in nodes.values():
        if n["type"] != "source":
            continue
        m = n.get("meta") or {}
        brut = m.get("brut")
        if not brut:
            continue
        p = root / brut
        if not p.is_file():
            srcbad.append(f"[[{names.get(n['id'], n['title'])}]] — fichier brut introuvable : {brut}")
        elif m.get("sha1") and sha1_file(p) != m["sha1"]:
            srcbad.append(f"[[{names.get(n['id'], n['title'])}]] — {brut} modifié depuis l'ingestion (raw/ est immuable : "
                          "nouvelle source, ou ré-ingérer)")
    if srcbad:
        out["Sources abîmées"] = srcbad[:limit]
    stale = []
    srcs = [n for n in active if n["type"] == "source" and TODO_MARK not in (n.get("body") or "")]
    for s in srcs:
        cited = {find(t) for t in ws.links_in(s.get("body", ""))} | {e["to"] for e in data["edges"] if e["from"] == s["id"]}
        for nid in cited:
            n = nodes.get(nid)
            if not n or n["type"] not in ("entity", "concept", "topic", "analysis") or n.get("status", "active") != "active":
                continue
            if str(n.get("updated") or "") < str(s.get("created") or ""):
                stale.append(f"[[{names.get(nid, n['title'])}]] — pas revue depuis la source [[{names.get(s['id'], s['title'])}]]"
                             f" ({fmt_date(s.get('created'))})")
    if stale:
        out["Pages peut-être dépassées"] = sorted(set(stale))[:limit]
    seen, dups = {}, []
    for n in active:
        k = fold(n["title"])
        if k in seen and seen[k]["id"] != n["id"]:
            dups.append(f"[[{names.get(seen[k]['id'], k)}]] ≈ [[{names.get(n['id'], k)}]] (même titre) → fusionner")
        seen.setdefault(k, n)
    if dups:
        out["Doublons"] = dups[:limit]
    contra = [f"[[{names.get(n['id'], n['title'])}]]" for n in active if "[!contradiction]" in (n.get("body") or "")]
    if contra:
        out["Contradictions signalées (à trancher ou à garder visibles)"] = contra[:limit]
    marks = [f"[[{names.get(n['id'], n['title'])}]]" for n in nodes.values()
             if re.search(r"^(<{7}|>{7}|={7})( |$)", n.get("body") or "", re.M)]
    if marks:
        out["Conflits git non résolus (<<<<<<<)"] = marks[:limit]
    leaks = [f"[[{names.get(n['id'], n['title'])}]] ({', '.join(sorted(set(find_secrets(n.get('body') or ''))))})"
             for n in active if find_secrets(n.get("body") or "")]
    if leaks:
        out["Secrets à retirer"] = leaks[:limit]
    hollow = [f"[[{names.get(n['id'], n['title'])}]] — " + ", ".join(f"« {h} »" for h in heads[:3])
              for n in active if TODO_MARK not in (n.get("body") or "") for heads in [empty_sections(n.get("body") or "")]
              if heads]
    if hollow:
        out["Sections vides (titre sans texte : remplir ou retirer)"] = hollow[:limit]
    bad = [f"[[{ws.stem(rel)}]] — {why}" for rel, p in sorted(ws._parse_cache(root).items()) if str(root)
           for why in bad_properties(p.get("fm") or {})]
    if bad:
        out["Propriétés invalides (le cerveau les remplace par une valeur par défaut)"] = bad[:limit]
    big = [f"[[{names.get(n['id'], n['title'])}]] ({len(n.get('body') or '') // 1000} k car.) → découper"
           for n in active if len(n.get("body") or "") > 15000]
    if big:
        out["Pages très longues"] = big[:limit]
    tied = set()
    for e in data["edges"]:
        a, b2 = nodes.get(e["from"]), nodes.get(e["to"])
        if a and b2 and (a["type"] in KNOWLEDGE) != (b2["type"] in KNOWLEDGE):
            tied.update((a["id"], b2["id"]))
    from .store import priority
    loose = sorted((n for n in active if n["type"] in ("learning", "reference", "fact", "decision") and not n.get("project")
                    and n["id"] not in tied and n.get("importance", 3) >= 3), key=lambda n: -priority(n))
    if loose and know:
        out["Souvenirs à verser dans une page de savoir (concept, sujet, entité)"] = [
            f"[[{names.get(n['id'], n['title'])}]] ({type_label(n['type'])})" for n in loose[:min(limit, 8)]]
    return out


HEAD_RX = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$", re.M)
DATE_FM = ("echeance", "fait_le", "fin", "cree", "maj")


def empty_sections(body) -> list:
    """Titres de section sans aucun texte jusqu'au titre suivant de même niveau ou plus haut (code ignoré)."""
    body = ws.CODE_RX.sub("·", body)
    heads = [(m.start(), m.end(), len(m.group(1)), m.group(2)) for m in HEAD_RX.finditer(body)]
    out = []
    for i, (_, end, level, title) in enumerate(heads):
        stop = next((h[0] for h in heads[i + 1:] if h[2] <= level), len(body))
        if not body[end:stop].strip():
            out.append(title)
    return out


def bad_properties(fm) -> list:
    """Propriétés qu'Obsidian accepte mais que le cerveau ne sait pas lire : type inconnu, importance hors 1 à 5,
    date qui n'en est pas une."""
    import datetime as _dt

    from .store import normalize_type
    out = []
    t = fm.get("type")
    if t not in (None, "", []):
        try:
            normalize_type(str(t))
        except ValueError:
            out.append(f"type « {t} » inconnu")
    imp = fm.get("importance")
    if imp not in (None, "", []) and (isinstance(imp, bool) or str(imp).strip() not in ("1", "2", "3", "4", "5")):
        out.append(f"importance « {imp} » (1 à 5)")
    for k in DATE_FM:
        v = fm.get(k)
        if v in (None, "", []):
            continue
        try:
            _dt.date.fromisoformat(str(v)[:10])
            ok = bool(ws.DATE_RX.match(str(v)))
        except ValueError:
            ok = False
        if not ok:
            out.append(f"{k} « {v} » (date AAAA-MM-JJ)")
    return out


def lint_text(report) -> str:
    if not report:
        return "✓ wiki en bonne santé : rien à signaler"
    rows = []
    for title, items in report.items():
        rows += [f"## {title} ({len(items)})"] + [f"- {x}" for x in items] + [""]
    return "\n".join(rows).rstrip()


# ------------------------------------------------------------------------------------------ état, avis, migration
def status(brain=None) -> str:
    from .store import Brain, TYPES
    mode, root = ws.resolve()
    if mode == "classic":
        return ("· le cerveau n'est pas (encore) en wiki — `brain wiki init <dossier>` : crée le wiki (dossier, idéalement "
                "le clone d'un dépôt GitHub privé) et y migre les souvenirs")
    if mode == "missing":
        return f"✗ wiki introuvable : {root} — le cerveau lit son cache sans rien écrire (rebranche le disque ?)"
    brain = brain or Brain.load()
    st = ws.stats(brain.data)
    raw = raw_files(root)
    pend = pending(brain.data, root, raw)
    lines = [f"📚 Wiki : {root}",
             "Pages : " + " · ".join(f"{TYPES.get(t, t)} {c}" for t, c in sorted(st["types"].items(), key=lambda x: -x[1]))
             + f" · archivées {st['archived']}",
             f"Sources brutes : {len(raw)}" + (f" · à ingérer : {len(pend)}" if pend else "")]
    if is_repo(root):
        url = remote(root)
        rows = _changes(root)
        code, ab = git(root, "rev-list", "--left-right", "--count", "@{upstream}...HEAD", timeout=10) if url else (1, "")
        sync_bits = []
        if code == 0 and ab.split():
            behind, ahead = ab.split()[:2]
            if ahead != "0":
                sync_bits.append(f"{ahead} commit(s) à pousser")
            if behind != "0":
                sync_bits.append(f"{behind} à récupérer")
        st_ = read_json(SYNC_STATE, {}) or {}
        failed = st_.get("failed") if isinstance(st_.get("failed"), dict) else None
        lines.append(f"Git : {url or 'local (pas d origin)'}" + (f" · {len(rows)} fichier(s) non commités" if rows else "")
                     + (" · " + " · ".join(sync_bits) if sync_bits else "")
                     + (f" · dernière synchro réussie {fmt_date(st_.get('synced'))}" if st_.get("synced") else "")
                     + (" · ⚠ conflit à régler à la main" if st_.get("conflict") else "")
                     + (f" · ⚠ dernière synchro ratée le {fmt_date(failed.get('le'))} : {failed.get('quoi')}"
                        if failed else
                        f" · ⚠ dernière récupération ratée le {fmt_date(st_['pull_failed'])} (GitHub injoignable : "
                        "réseau ou accès)" if st_.get("pull_failed") else ""))
        copies = [c for c in st_.get("copies_vues") or [] if (root / c).exists()]
        if copies:
            lines.append(f"Copies de conflit à relire ({len(copies)}) : " + ", ".join(copies[:8])
                         + (" …" if len(copies) > 8 else ""))
    else:
        lines.append("Git : pas de dépôt (historique et synchronisation absents) — `git init` dans le wiki")
    last = log_entries(root, 5)
    if last:
        lines.append("Journal (dernières entrées) :")
        lines += [f"  {x[3:]}" for x in last]
    return "\n".join(lines)


def notice(brain) -> str:
    """Ligne injectée au démarrage d'une session (mode wiki) : où est le wiki, ce qui attend, la méthode. Dit une fois
    les copies de conflit posées par la dernière synchro, et une synchro ratée (hors réseau absent) tant qu'elle l'est.
    index.md absent (clone tout frais : il n'est plus dans git) : il est régénéré ici."""
    root = ws.root()
    if not root:
        return ""
    st = ws.stats(brain.data)
    know = sum(c for t, c in st["types"].items() if t in KNOWLEDGE)
    total = sum(st["types"].values())
    try:
        pend = len(pending(brain.data, root))
    except Exception:
        pend = 0
    if not (root / INDEX).exists():
        try:
            write_index(brain, root)
        except Exception as exc:
            log(f"wiki : index.md : {exc!r}")
    sync = read_json(SYNC_STATE, {}) or {}
    failed = sync.get("failed") if isinstance(sync.get("failed"), dict) else None
    copies = [c for c in sync.get("copies") or [] if (root / c).exists()]
    if sync.get("copies"):  # une seule fois : ensuite dans `brain wiki status`, tant que la copie existe
        sync["copies_vues"] = sorted(set(sync.get("copies_vues") or []) | set(copies))
        sync.pop("copies")
        write_json(SYNC_STATE, sync)
    names = ", ".join(f"« {c.rsplit('/', 1)[-1]} »" for c in copies[:4]) + (" …" if len(copies) > 4 else "")
    return (f"📚 Le cerveau vit dans le wiki {root} ({total} pages dont {know} de savoir) — schéma : {root / SCHEMA_FILE} ; "
            f"`brain q` y cherche, `brain wiki add <source>` ingère, `brain wiki lint` entretient."
            + (f" ⏳ {pend} source(s) à ingérer (`brain wiki pending`)." if pend else "")
            + (" ⚠ Synchro git en conflit : `brain wiki status`." if sync.get("conflict") else "")
            + (f" ⚠ Dernière synchro git du wiki ratée : {failed.get('quoi')} (`brain wiki status`)."
               if failed and not failed.get("reseau") and not sync.get("conflict") else "")
            + (f" ⚠ Page(s) modifiée(s) ici et sur un autre PC : la version de GitHub est gardée, celle de ce PC mise à "
               f"côté en copie de conflit — à dire à l'utilisateur, qui relit puis supprime la copie : {names}."
               if copies else ""))


def init(path, migrate=True, push=True) -> list:
    """Crée (ou complète) le wiki dans `path`, y migre le cerveau classique, et fait de ce wiki la mémoire du cerveau.
    Rien n'est perdu : coffre Obsidian rapatrié d'abord, instantané et copie de graph.json gardés."""
    from .wiki_git import commit
    from .wiki_journal import write_journal
    from .wiki_textes import scaffold
    from . import history
    from .common import GRAPH_FILE
    from .store import Brain
    root = Path(os.path.expanduser(str(path))).resolve()
    if root.exists() and not root.is_dir():
        raise RuntimeError(f"ce n'est pas un dossier : {root}")
    if root == BRAIN_DIR.resolve():
        raise RuntimeError("le wiki ne peut pas être le dossier du cerveau lui-même")
    report = []
    made = scaffold(root)
    if made:
        report.append(f"✓ squelette : {len(made)} fichier(s) ({', '.join(m for m in made if '/' not in m)[:200]} …)")
    mode, cur = ws.resolve()
    if mode == "wiki" and cur == root:
        report.append("· le cerveau travaille déjà dans ce wiki")
        migrate = False
    if migrate:
        vault = (load_config().get("vault") or {}).get("path")
        if vault and Path(vault).is_dir() and mode == "classic":
            try:
                from . import vault as vlt
                rep = vlt.sync(vault, do_import=True)
                report.append(f"✓ coffre Obsidian rapatrié d'abord ({len(rep['imported'])} note(s) modifiée(s), "
                              f"{len(rep['created'])} nouvelle(s))")
            except Exception as exc:
                report.append(f"· coffre Obsidian non rapatrié ({short(str(exc), 120)}) : `brain export --vault` avant, si besoin")
        history.snapshot("avant-wiki", force=True)
        classic = Brain.load().data if mode != "wiki" else {"nodes": {}, "edges": []}
        if mode == "classic" and GRAPH_FILE.exists():
            keep = GRAPH_FILE.with_name(f"graph.avant-wiki-{time.strftime('%Y%m%d-%H%M%S')}.json")
            shutil.copy2(GRAPH_FILE, keep)
            report.append(f"✓ copie du cerveau classique gardée : {keep}")
        data = ws.load(root, write=False)  # pages déjà là (dépôt utilisé depuis une session cloud, par ex.)
        added, kept, remap = 0, 0, {}
        for nid, n in (classic.get("nodes") or {}).items():
            have = data["nodes"].get(nid)
            if have and fold(have["title"]) == fold(n["title"]):
                for k in ws.VOLATILE:
                    if n.get(k) is not None:
                        have[k] = n[k]
                kept += 1
                continue
            new_id, i = nid, 2
            while new_id in data["nodes"]:
                new_id = f"{nid}-{i}"
                i += 1
            remap[nid] = new_id
            node = json.loads(json.dumps(n))
            node["id"] = new_id
            if node.get("project"):
                node["project"] = remap.get(node["project"], node["project"])
            data["nodes"][new_id] = node
            added += 1
        for n in data["nodes"].values():  # projets et renvois vers des ids renommés
            if n.get("project") in remap:
                n["project"] = remap[n["project"]]
            m = n.get("meta") or {}
            for k in ws.LINK_META:
                if m.get(k) in remap:
                    m[k] = remap[m[k]]
        have_edges = {(e["from"], e["to"], e["rel"]) for e in data["edges"]}
        for e in classic.get("edges") or []:
            a, b2 = remap.get(e["from"], e["from"]), remap.get(e["to"], e["to"])
            if a in data["nodes"] and b2 in data["nodes"] and (a, b2, e["rel"]) not in have_edges:
                data["edges"].append(dict(e, **{"from": a, "to": b2}))
                have_edges.add((a, b2, e["rel"]))
        for k in ("usage_since", "created"):
            if classic.get(k) and not data.get(k):
                data[k] = classic[k]
        rep = ws.save(data, root)
        set_config("wiki.path", str(root))
        if vault:
            set_config("vault.path", None)
            report.append(f"· le coffre {vault} n'est plus synchronisé : le wiki est le coffre désormais (ouvre {root} "
                          "dans Obsidian)")
        report.append(f"✓ {added} souvenir(s) devenus pages ({rep['written']} fichier(s) écrits)"
                      + (f", {kept} déjà présents" if kept else ""))
        months = write_journal(root)
        if months:
            report.append(f"✓ historique (sessions passées, observations datées) : {months} mois dans {JOURNAL_DIR}/")
        log_append("migration", f"{added} souvenirs du cerveau classique → pages", root=root)
    else:
        set_config("wiki.path", str(root))
    write_index(Brain.load(), root)
    if is_repo(root):
        msg = commit(root, "cerveau : wiki initialisé" if migrate else None)
        if msg:
            report.append(("" if msg.startswith("✗") else "✓ commit : ") + msg)
        if push and remote(root):
            code, txt = git(root, "push", "-u", "origin", "HEAD", timeout=120)
            from . import gitmsg
            report.append("✓ push vers GitHub" if code == 0 else "✗ " + gitmsg.explain(txt, code, "push")
                          + " ; le wiki est prêt ici (relance : `brain wiki sync`)")
    else:
        report.append("· pas de dépôt git : `git init` (ou clone ton dépôt GitHub privé) pour l'historique et la synchro")
    report.append(f"→ ouvre {root} dans Obsidian ; le schéma (à faire évoluer) : {root / SCHEMA_FILE}")
    return report


def write_derived(brain, root=None) -> None:
    """index.md, page « Cerveau » et carte du coffre Obsidian, refaits d'après les pages. Aucun n'est dans git (chaque PC
    a les siens) et chacun se refait à tout moment : la fin de session les confie à la tâche de fond des vues (vues.py),
    car ils coûtaient 250 à 300 ms dans le hook à 3 000 pages (la page Cerveau passe tout le wiki au contrôle de santé)."""
    root = root or ws.root()
    if not root:
        return
    write_index(brain, root)
    try:  # coffre Obsidian : page « Cerveau » et carte des thèmes, lues sans Claude
        from . import obsidian
        obsidian.write_status(brain, root)
        obsidian.write_canvas(brain, root)
    except Exception as exc:
        log(f"wiki : obsidian : {exc!r}")


def session_close(brain, project=None, derived=True) -> str:
    """Fin de session (mode wiki) : journal du wiki de ce PC et entrée « session » de log.md si des pages ont changé —
    sur le disque avant la synchronisation git qui suit, et avant que le PC puisse s'éteindre. `derived` : refaire aussi
    index.md, la page Cerveau et la carte (write_derived) ; le hook de fin de session les laisse à la tâche des vues."""
    from .wiki_journal import write_journal
    root = ws.root()
    if not root:
        return ""
    if derived:
        write_derived(brain, root)
    try:
        write_journal(root)
    except Exception as exc:
        log(f"wiki : journal : {exc!r}")
    if not is_repo(root):
        return ""
    rows = [p for _, p in _changes(root) if p.startswith((ws.PAGES + "/", ws.ARCHIVE + "/", ws.RAW + "/"))]
    pages = [ws.stem(p) for p in rows if p.endswith(".md") and not p.startswith(ws.RAW + "/")]
    if not rows:
        return ""
    st = read_json(SYNC_STATE, {}) or {}
    key = hashlib.sha1("\n".join(sorted(rows)).encode("utf-8")).hexdigest()[:12]
    if st.get("logged") == key:
        return ""  # mêmes changements déjà notés (deux fins de session de suite)
    raws = [p for p in rows if p.startswith(ws.RAW + "/")]
    title = (project or "hors projet") + f" — {len(pages)} page(s)" + (f", {len(raws)} source(s)" if raws else "")
    lines = [", ".join(f"[[{p}]]" for p in pages[:12]) + (" …" if len(pages) > 12 else "")] if pages else []
    log_append("session", title, lines, root=root)
    st["logged"] = key
    write_json(SYNC_STATE, st)
    return title


def due_sync(minutes=30) -> bool:
    """Au plus une synchronisation automatique de démarrage toutes les `minutes`."""
    st = read_json(SYNC_STATE, {}) or {}
    from .common import days_since
    return days_since(st.get("pulled")) * 1440 >= minutes


def mark_pulled():
    st = read_json(SYNC_STATE, {}) or {}
    st["pulled"] = now_iso()
    write_json(SYNC_STATE, st)


# Noms déplacés par le découpage du 21/11/2026 : toujours accessibles ici (`wiki.sync`, `from .wiki import sync`),
# chargés à la demande depuis leur module.
_PARTS = {
    "wiki_textes": frozenset("""
        CLOUD_EVENTS CLOUD_LAUNCHER GITATTRIBUTES GITIGNORE README SCHEMA UNION _owner _plugin_repo cloud_settings
        scaffold schema_text
    """.split()),
    "wiki_journal": frozenset("""
        CLOUD_JOURNAL DAY_RX JOURNAL_PC_FILE MONTH_RX OLD_JOURNAL SESSION_RX _cloud _merge_month _migrate_journal
        _sections journal_months journal_pages journal_pc other_sessions write_journal
    """.split()),
    "wiki_git": frozenset("""
        GENERATED LINES_UNION UNTRACKED _blob _ensure_lines _prepare_repo _pull _rebasing _resolve _union_lines
        _union_log _unmerged _unstick _upstream commit conflict_copy_name push_pending sync
    """.split()),
    "wiki_sources": frozenset("""
        FORMATS HTML_EXT SUB_EXT TEXT_EXT UrlRefusee YOUTUBE _docx_text _frontmatter_title _guess_format
        _unique_raw _vtt_text add_source candidates check_url extract_text fetch html_to_md ingest_plan related
    """.split()),
}


def __getattr__(name):
    """Un nom déplacé est cherché dans son module la première fois, puis gardé ici ; un nom inconnu reste une
    AttributeError, comme avant."""
    for part, names in _PARTS.items():
        if name in names:
            import importlib
            value = globals()[name] = getattr(importlib.import_module(f".{part}", __package__), name)
            return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
