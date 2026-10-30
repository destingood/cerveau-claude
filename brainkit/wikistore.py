"""Le cerveau en wiki (le « LLM Wiki » de Karpathy) : les pages Markdown d'un dossier — un dépôt git ouvert comme
coffre Obsidian — font foi ; graph.json n'en est plus que le cache, reconstruit dès qu'une page change.

- Une page par souvenir ou par page de savoir, rangée par type (`wiki/Règles/…`, `wiki/Concepts/…`) ; les pages
  archivées (remplacées, terminées) vont dans `archive/`. Titre = ligne « # », nom du fichier = titre (Obsidian relie
  par nom de fichier : `[[Titre]]`). Propriétés en tête (type, projet, tags, importance, échéance, relations typées…).
- Lecture : le dossier est parcouru (noms, dates, tailles) ; s'il n'a pas bougé depuis le dernier passage, le cache
  sert tel quel. Sinon seules les pages modifiées sont relues (state/wiki-pages.json), puis tout est relié en mémoire.
- Écriture : seules les pages dont le contenu change sont réécrites. Un titre changé par le cerveau renomme le fichier
  et met à jour les liens `[[…]]` des autres pages. Un fichier renommé ou déplacé dans Obsidian garde sa place.
- Les compteurs qui bougent à chaque message (rappels, usage, date de carte) restent dans le cache : rien ne se
  réécrit dans le wiki pour eux (pas de bruit dans git).
- Wiki introuvable (disque débranché, dossier déplacé) : le cerveau lit son cache sans rien écrire."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from .common import (BRAIN_DIR, GRAPH_FILE, STATE_DIR, clean_label, fold, load_config, log, now_iso, read_json,
                     slugify, write_json, write_text)

MARKER = ".cerveau-wiki"
PAGES, ARCHIVE, RAW = "wiki", "archive", "raw"
PARSE_FILE = STATE_DIR / "wiki-pages.json"
FOLDERS = {"user": "Profil", "feedback": "Règles", "project": "Projets", "decision": "Décisions", "fact": "Faits",
           "learning": "Apprentissages", "reference": "Références", "entity": "Entités", "todo": "À faire",
           "source": "Sources", "concept": "Concepts", "topic": "Sujets", "analysis": "Analyses"}
FOLDER_TYPE = {fold(v): k for k, v in FOLDERS.items()}
FR_TYPES = {"user": "profil", "feedback": "regle", "project": "projet", "decision": "decision", "fact": "fait",
            "learning": "apprentissage", "reference": "reference", "entity": "entite", "todo": "afaire",
            "source": "source", "concept": "concept", "topic": "sujet", "analysis": "analyse"}
# relation du graphe ↔ propriété de la page qui part (liste de liens)
REL_FM = {"relates": "lie_a", "part_of": "fait_partie_de", "depends_on": "depend_de", "uses": "utilise",
          "fixes": "corrige", "supersedes": "remplace", "contradicts": "contredit", "about": "a_propos_de"}
FM_REL = {v: k for k, v in REL_FM.items()}
# champs de `meta` ↔ propriétés (ordre d'écriture) ; les autres champs de meta gardent leur nom
META_FM = {"resume": "resume", "domaine": "domaine", "sources": "sources", "due": "echeance", "done": "fait_le",
           "valid_to": "fin", "superseded_by": "remplace_par", "merged_into": "fusionne_dans", "keys": "cles",
           "conf": "confiance", "path": "chemin", "aliases": "chemins_alt", "stack": "stack", "auto_body": "corps_auto",
           "format": "format", "url": "url", "auteur": "auteur", "date_source": "date_source", "brut": "brut",
           "sha1": "sha1", "origin": "fichier_origine", "hash": "empreinte", "name": "nom", "alias": "aliases"}
FM_META = {v: k for k, v in META_FM.items()}
LINK_META = ("superseded_by", "merged_into")  # un id de souvenir, écrit comme un lien
CORE_FM = ("id", "type", "projet", "tags", "importance", "origine", "cree", "maj", "titre")
VOLATILE = ("hits", "last_hit", "used", "last_used")
VOLATILE_META = ("hits0", "mapped")
LINK_RX = re.compile(r"\[\[([^\]\n|#]{1,160})(#[^\]\n|]*)?(?:\|([^\]\n]{1,160}))?\]\]")
CODE_RX = re.compile(r"^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?(?:^[ \t]*\1[ \t]*$|\Z)|(`+)[^\n]*?\2", re.M | re.S)
DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?$")
PLAIN_RX = re.compile(r"^[a-z][a-z0-9_\-]*$")
YAML_WORDS = {"true", "false", "yes", "no", "on", "off", "null", "y", "n"}
BAD = re.compile(r'[<>:"/\\|?*#^\[\]\x00-\x1f]+')
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}
MASS_DELETE = 0.3  # une écriture ordinaire qui effacerait plus de 30 % des pages est refusée (bogue, pas intention)
CONFLICTS = BRAIN_DIR / "conflits"  # version du cerveau d'une page modifiée dans Obsidian pendant l'opération


class WikiMissing(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------ où est le wiki ?
def _find_up(start) -> Path | None:
    try:
        p = Path(start).resolve()
    except (OSError, RuntimeError):
        return None
    for d in [p, *p.parents][:15]:
        if (d / MARKER).is_file():
            return d
    return None


def _cache_free_for(root) -> bool:
    """Un wiki trouvé depuis le dossier courant ne prend la main que si le cache ne contient pas un cerveau classique
    (graph.json d'un ami avec ses souvenirs) : il serait écrasé par le cache du wiki."""
    data = read_json(GRAPH_FILE, None)
    if not isinstance(data, dict) or not data.get("nodes"):
        return True
    return (data.get("wiki") or {}).get("root") == str(root)


def resolve(cwd=None):
    """→ ("wiki", racine) · ("missing", racine configurée introuvable) · ("classic", None).
    Ordre : réglage wiki.path (posé par `brain wiki init`), variable BRAIN_WIKI, puis un wiki contenant le dossier
    courant (session cloud ouverte dans le dépôt du wiki : le cerveau y travaille directement)."""
    path = (load_config().get("wiki") or {}).get("path") or os.environ.get("BRAIN_WIKI")
    if path:
        root = Path(os.path.expanduser(str(path)))
        if (root / MARKER).is_file():
            return "wiki", root.resolve()
        return "missing", root
    try:
        here = cwd or os.getcwd()
    except OSError:
        return "classic", None
    found = _find_up(here)
    if found and _cache_free_for(found):
        return "wiki", found
    return "classic", None


def root():
    mode, r = resolve()
    return r if mode == "wiki" else None


# ------------------------------------------------------------------------------------------ fichiers
def fname(title) -> str:
    """Titre → nom de fichier sûr (Windows, Obsidian : pas de : / \\ | ? * # ^ [ ])."""
    name = " ".join(BAD.sub(" ", str(title)).split()).strip(" .")[:90].strip(" .") or "sans titre"
    return name + "_" if name.split(".")[0].upper() in RESERVED else name


def scan(root) -> dict:
    """Pages du wiki : {chemin relatif POSIX: (mtime_ns, taille)} (dossiers et fichiers « . » ou « _ » ignorés)."""
    out = {}
    for top in (PAGES, ARCHIVE):
        stack = [(os.path.join(str(root), top), top)]
        while stack:
            d, rel = stack.pop()
            try:
                it = os.scandir(d)
            except OSError:
                continue
            with it:
                for e in it:
                    if e.name[:1] in "._":
                        continue
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append((e.path, f"{rel}/{e.name}"))
                        elif e.name.lower().endswith(".md"):
                            st = e.stat(follow_symlinks=False)
                            out[f"{rel}/{e.name}"] = (st.st_mtime_ns, st.st_size)
                    except OSError:
                        continue
    return out


def signature(entries) -> str:
    h = hashlib.sha1()
    for rel in sorted(entries):
        m, s = entries[rel]
        h.update(f"{rel}\t{m}\t{s}\n".encode("utf-8"))
    return h.hexdigest()


def stem(rel) -> str:
    return rel.rsplit("/", 1)[-1][:-3]


def place(rel):
    """Chemin d'une page → (type d'après son dossier ou None, archivée ?)."""
    parts = rel.split("/")
    archived = parts[0] == ARCHIVE
    t = FOLDER_TYPE.get(fold(parts[1])) if len(parts) > 2 else None
    return t, archived


# ------------------------------------------------------------------------------------------ lecture d'une page
def _scalar(raw):
    raw = raw.strip()
    if not raw:
        return ""
    try:
        return json.loads(raw)
    except ValueError:
        pass
    if raw[0] == "[" and raw[-1] == "]" and not raw.startswith("[["):
        return [_scalar(x) for x in raw[1:-1].split(",") if x.strip()]
    if len(raw) > 1 and raw[0] == raw[-1] == "'":
        return raw[1:-1].replace("''", "'")
    return raw


def parse_page(text) -> dict:
    """Page Markdown → {fm: propriétés, raw: texte brut de chaque propriété, t: titre (« # »), b: corps}.
    Propriétés en ligne ou en liste à tirets, comme Obsidian les écrit."""
    text = text.replace("\r\n", "\n").lstrip("﻿")
    fm, raw = {}, {}
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is not None:
            key = None
            for line in lines[1:end]:
                item = re.match(r"^\s*-\s+(.*)$", line) or re.match(r"^\s*-$", line)
                if item and key is not None and isinstance(fm.get(key), list):
                    val = item.group(1) if item.groups() else ""
                    fm[key].append(_scalar(val))
                    raw[key] += "\n" + val
                    continue
                k, sep, val = line.partition(":")
                if not sep or not k.strip() or k[0] in " \t#":
                    continue
                key = k.strip()
                fm[key] = _scalar(val) if val.strip() else []
                raw[key] = val.strip()
            text = "\n".join(lines[end + 1:])
    body = text.lstrip("\n")
    title = ""
    m = re.match(r"#[ \t]+(.+?)[ \t]*(?:\n|$)", body)
    if m:
        title = m.group(1).strip()
        body = body[m.end():]
    mark = body.find("<!-- cerveau : section générée")
    if mark != -1:
        body = body[:mark]
    return {"fm": fm, "raw": raw, "t": title, "b": body.strip()}


def links_in(text) -> list:
    """Cibles des liens [[…]] — comme Obsidian : pas ceux d'un bloc de code ni d'un `code` en ligne (exemples)."""
    return [m.group(1).strip() for m in LINK_RX.finditer(CODE_RX.sub(" ", str(text or "")))]


def first_ref(raw) -> str:
    """Texte brut d'une propriété à une seule cible (« "[[Boutique]]" », « boutique ») → la cible."""
    found = links_in(raw)
    if found:
        return found[0]
    v = _scalar(str(raw or ""))
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v or "").strip()


def _iso(value, fallback=None):
    v = str(value or "").strip().strip('"')
    if DATE_RX.match(v):
        v = v.replace(" ", "T")
        return (v + "T00:00:00")[:19] if len(v) == 10 else (v + ":00")[:19]
    return fallback


def _minute(value) -> str:
    v = str(value or "")
    return (v[:16] + ":00") if len(v) >= 16 else v


def _text_list(value) -> list:
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    v = str(value or "").strip()
    return [x.strip() for x in v.split(",") if x.strip()] if v else []


# ------------------------------------------------------------------------------------------ pages → graphe
def _resolver(nodes, stems):
    """Cible d'un lien ou d'une référence (nom de fichier, id, titre) → id, sans deviner par préfixe."""
    by_title = {}
    for n in nodes.values():
        by_title.setdefault(fold(n["title"]), n["id"])

    def find(ref):
        r = str(ref or "").strip().strip("\"'").strip()
        m = LINK_RX.fullmatch(r)
        if m:
            r = m.group(1).strip()
        if r.lower().endswith(".md"):
            r = r[:-3]
        if not r:
            return None
        if r in nodes:
            return r
        hit = stems.get(r.lower()) or stems.get(r.rsplit("/", 1)[-1].lower())
        if hit:
            return hit
        s = slugify(r, 40)
        if s in nodes:
            return s
        return by_title.get(fold(r))
    return find


def content_key(n, stems_by_id, out_rels) -> str:
    """Empreinte de tout ce qui s'écrit dans la page (y compris le nom des pages visées) : la page n'est réécrite
    que si elle change."""
    m = n.get("meta") or {}
    meta = sorted((k, v) for k, v in m.items() if k not in VOLATILE_META)
    rels = sorted((rel, stems_by_id.get(t, t)) for rel, t in out_rels)
    pid = n.get("project")
    blob = (n["title"], n["type"], n.get("body", ""), n.get("tags") or [], stems_by_id.get(pid, pid) if pid else None,
            n.get("importance", 3), _minute(n.get("created")), _minute(n.get("updated")), n.get("source"),
            n.get("status", "active"), meta, rels, [stems_by_id.get(m.get(k), m.get(k)) for k in LINK_META])
    return hashlib.sha1(repr(blob).encode("utf-8", "surrogatepass")).hexdigest()[:16]  # repr : ~3× plus vite que json


def build(root, pages, old=None) -> dict:
    """Pages lues ({chemin: page analysée}) → données du graphe (nœuds, liens, manifeste). Les compteurs volatils et
    les dates de création des liens sont repris de l'ancien cache."""
    from .store import clamp_importance, clean_tags, normalize_source, normalize_type
    old = old if isinstance(old, dict) else {}
    old_nodes = old.get("nodes") or {}
    nodes, paths, rels_raw = {}, {}, {}
    for rel in sorted(pages):
        p = pages[rel]
        fm, raw = p["fm"], p["raw"]
        ftype, archived = place(rel)
        ntype = ftype
        if not ntype:
            try:
                ntype = normalize_type(fm.get("type")) if fm.get("type") else "fact"
            except ValueError:
                ntype = "fact"
        nid = slugify(str(fm["id"]), 80) if fm.get("id") else slugify(stem(rel), 40)  # un id écrit n'est jamais tronqué
        base, i = nid, 2
        while nid in nodes:
            nid = f"{base}-{i}"
            i += 1
        title = clean_label(p["t"] or fm.get("titre") or stem(rel))
        meta = {}
        for k, v in fm.items():
            if k in CORE_FM or k in FM_REL:
                continue
            key = FM_META.get(k, k)
            if v in ("", [], None):
                continue
            meta[key] = v
        if "alias" in meta:
            meta["alias"] = [a for a in _text_list(meta["alias"]) if fold(a) != fold(title)]
            if not meta["alias"]:
                meta.pop("alias")
        for k in ("done", "valid_to", "due"):
            if k in meta:
                meta[k] = str(meta[k])[:10]
        mtime = _dt.datetime.fromtimestamp(p.get("m", 0) / 1e9).replace(microsecond=0).isoformat() if p.get("m") else now_iso()
        created = _iso(fm.get("cree"), mtime)
        node = {
            "id": nid, "type": ntype, "title": title or nid, "body": p["b"],
            "tags": clean_tags([str(t).lstrip("#") for t in _text_list(fm.get("tags"))]),
            "project": None, "importance": clamp_importance(fm.get("importance", 3)),
            "created": created, "updated": _iso(fm.get("maj"), created),
            "hits": 0, "last_hit": None, "source": normalize_source(fm.get("origine") or "wiki"),
            "status": "archived" if archived else "active", "meta": meta,
        }
        prev = old_nodes.get(nid)
        if prev:  # compteurs du cache (jamais écrits dans le wiki)
            for k in VOLATILE:
                if prev.get(k) is not None:
                    node[k] = prev[k]
            for k in VOLATILE_META:
                if (prev.get("meta") or {}).get(k) is not None:
                    node["meta"][k] = prev["meta"][k]
        nodes[nid] = node
        paths[nid] = rel
        rels_raw[nid] = (raw.get("projet", ""), {FM_REL[k]: links_in(raw[k]) or _text_list(fm.get(k))
                                                for k in raw if k in FM_REL},
                         {k: raw.get(META_FM[k], "") for k in LINK_META})
    stems = {stem(rel).lower(): nid for nid, rel in paths.items()}
    find = _resolver(nodes, stems)
    old_edges = {(e["from"], e["to"], e["rel"]): e.get("created") for e in old.get("edges") or []}
    edges, seen = [], set()
    today = now_iso()[:10]

    def add_edge(a, b, rel):
        if not b or a == b or (a, b, rel) in seen:
            return
        seen.add((a, b, rel))
        edges.append({"from": a, "to": b, "rel": rel, "created": old_edges.get((a, b, rel)) or today})

    for nid, (proj_raw, rels, link_meta) in rels_raw.items():
        n = nodes[nid]
        if proj_raw:
            pid = find(first_ref(proj_raw))
            if pid and nodes[pid]["type"] == "project" and pid != nid:
                n["project"] = pid
        for k, txt in link_meta.items():
            if txt:
                target = find(first_ref(txt))
                if target:
                    n["meta"][k] = target
                else:
                    n["meta"].pop(k, None)
        for rel, targets in rels.items():
            for t in targets:
                add_edge(nid, find(t), rel)
        for t in links_in(n["body"]):
            add_edge(nid, find(t), "relates")
    data = {k: v for k, v in old.items() if k not in ("nodes", "edges", "wiki")}
    data.setdefault("version", 1)
    data.setdefault("created", now_iso())
    data.update({"nodes": nodes, "edges": edges})
    stems_by_id = {nid: stem(rel) for nid, rel in paths.items()}
    out = {}
    for e in edges:
        out.setdefault(e["from"], []).append((e["rel"], e["to"]))
    data["wiki"] = {"root": str(root), "files": {
        nid: {"path": paths[nid], "title": n["title"], "type": n["type"], "status": n["status"],
              "k": content_key(n, stems_by_id, out.get(nid, []))} for nid, n in nodes.items()}}
    return data


def _parse_cache(root, parse_file=None) -> dict:
    pc = read_json(parse_file or PARSE_FILE, {}) or {}
    return dict(pc.get("files") or {}) if pc.get("root") == str(root) and pc.get("v") == 1 else {}


def _keep_classic(cache):
    """graph.json d'un cerveau classique sur le point de devenir le cache du wiki : copie gardée à côté (une fois par
    passage du classique au wiki : ensuite, le cache est celui du wiki)."""
    if isinstance(cache, dict) and cache.get("nodes") and not cache.get("wiki"):
        import shutil
        import time
        dest = GRAPH_FILE.with_name(f"graph.classique-{time.strftime('%Y%m%d-%H%M%S')}.json")
        try:
            shutil.copy2(GRAPH_FILE, dest)
            log(f"wiki : graph.json classique gardé dans {dest.name}")
        except OSError as exc:
            log(f"wiki : copie du graph.json classique : {exc!r}")


def load(root, write=True, cache_file=None, parse_file=None) -> dict:
    """Données du graphe d'après le wiki : le cache s'il est à jour, sinon relecture des seules pages modifiées.
    write=False (migration) : ni le cache ni graph.json ne sont touchés. cache_file / parse_file : caches d'un autre
    wiki que celui du cerveau (dossiers des amis dans le cerveau commun)."""
    root = Path(root)
    cache_file, parse_file = cache_file or GRAPH_FILE, parse_file or PARSE_FILE
    entries = scan(root)
    sig = signature(entries)
    cache = read_json(cache_file, None)
    if isinstance(cache, dict) and (cache.get("wiki") or {}).get("root") == str(root) \
            and cache["wiki"].get("sig") == sig and isinstance(cache.get("nodes"), dict):
        return cache
    if write and cache_file == GRAPH_FILE:
        _keep_classic(cache)
    files = _parse_cache(root, parse_file)
    pages, changed = {}, False
    for rel, (m, s) in entries.items():
        hit = files.get(rel)
        if hit and hit.get("m") == m and hit.get("s") == s:
            pages[rel] = hit
            continue
        try:
            with open(os.path.join(str(root), rel), encoding="utf-8", errors="replace") as fh:
                p = parse_page(fh.read())
        except OSError:
            continue
        p.update(m=m, s=s)
        pages[rel] = p
        changed = True
    if write and (changed or set(files) != set(pages)):
        try:
            write_json(parse_file, {"v": 1, "root": str(root), "files": pages}, indent=None)
        except Exception as exc:
            log(f"wiki : cache des pages : {exc!r}")
    old = cache if isinstance(cache, dict) and (cache.get("wiki") or {}).get("root") == str(root) else \
        (cache if isinstance(cache, dict) and not cache.get("wiki") else None)  # migration : compteurs du cerveau classique
    data = build(root, pages, old)
    data["wiki"]["sig"] = sig
    if write:
        try:
            write_json(cache_file, data)
        except Exception as exc:
            log(f"wiki : écriture du cache : {exc!r}")
    return data


def load_missing(root) -> dict:
    """Wiki configuré mais introuvable : le dernier cache, en lecture seule."""
    data = read_json(GRAPH_FILE, None)
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), dict):
        data = {"version": 1, "created": now_iso(), "nodes": {}, "edges": []}
    data["wiki"] = dict(data.get("wiki") or {}, root=str(root), missing=True)
    return data


# ------------------------------------------------------------------------------------------ graphe → pages
def _yv(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v) if isinstance(v, float) else str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(json.dumps(str(x), ensure_ascii=False) for x in v) + "]"
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    s = str(v)
    if DATE_RX.match(s):
        return s
    if PLAIN_RX.match(s) and s not in YAML_WORDS:  # id, type, origine : sans guillemets, plus lisible dans Obsidian
        try:
            json.loads(s)  # « 123 », « 1e5 » : nombres pour YAML, gardés entre guillemets
        except ValueError:
            return s
    return json.dumps(s, ensure_ascii=False)


def render(n, stems_by_id, out_rels) -> str:
    """Nœud → texte de la page (propriétés, titre, corps)."""
    def link(nid):
        return f"[[{stems_by_id[nid]}]]" if nid in stems_by_id else nid

    meta = dict(n.get("meta") or {})
    fm = [("id", n["id"]), ("type", FR_TYPES.get(n["type"], n["type"]))]
    if n.get("project"):
        fm.append(("projet", link(n["project"])))
    if n.get("tags"):
        fm.append(("tags", list(n["tags"])))
    fm.append(("importance", n.get("importance", 3)))
    fm.append(("origine", n.get("source") or "claude"))
    st = stems_by_id.get(n["id"])
    aliases = _text_list(meta.pop("alias", None))
    if st and fold(st) != fold(n["title"]) and n["title"] not in aliases:
        aliases.append(n["title"])
    for key, fkey in META_FM.items():
        if key == "alias" or key not in meta or key in VOLATILE_META:
            continue
        v = meta.pop(key)
        if v in (None, "", []):
            continue
        fm.append((fkey, link(v) if key in LINK_META else v))
    for key in sorted(meta):
        if key in VOLATILE_META or meta[key] in (None, "", []) or key in CORE_FM or key in FM_REL:
            continue
        fm.append((key, meta[key]))
    body = str(n.get("body") or "").strip()
    in_body = {t.lower() for t in links_in(body)}
    by_rel = {}
    for rel, t in out_rels:
        if t not in stems_by_id:
            continue
        if rel == "relates" and stems_by_id[t].lower() in in_body:
            continue  # déjà relié par un [[lien]] du texte
        by_rel.setdefault(rel, [])
        if link(t) not in by_rel[rel]:
            by_rel[rel].append(link(t))
    for rel, fkey in REL_FM.items():
        if by_rel.get(rel):
            fm.append((fkey, sorted(by_rel[rel], key=str.lower)))
    if aliases:
        fm.append(("aliases", aliases))
    fm.append(("cree", _minute(n.get("created"))[:16]))
    fm.append(("maj", _minute(n.get("updated"))[:16]))
    head = "\n".join(f"{k}: {_yv(v)}" for k, v in fm)
    return f"---\n{head}\n---\n# {n['title']}\n" + (f"\n{body}\n" if body else "")


def _assign(nodes, files):
    """Chemin de chaque page. Une page garde son chemin tant que le cerveau n'a changé ni son titre, ni son type, ni
    son statut (un renommage ou un rangement fait dans Obsidian est respecté). Noms uniques dans tout le wiki
    (insensibles à la casse, comme Windows et Obsidian) ; les pages actives passent avant les archivées."""
    from .store import priority
    paths, taken, renamed = {}, {}, {}
    pending = []
    for nid, n in nodes.items():
        prev = files.get(nid)
        if prev and prev.get("title") == n["title"] and prev.get("type") == n["type"] \
                and prev.get("status") == n.get("status", "active"):
            st = stem(prev["path"])
            if st.lower() not in taken:
                paths[nid] = prev["path"]
                taken[st.lower()] = nid
                continue
        pending.append(n)
    pending.sort(key=lambda n: (n.get("status", "active") != "active", -priority(n), n["id"]))
    for n in pending:
        nid = n["id"]
        prev = files.get(nid)
        top = ARCHIVE if n.get("status", "active") != "active" else PAGES
        folder = f"{top}/{FOLDERS.get(n['type'], 'Faits')}"
        if prev and prev.get("title") == n["title"]:
            want = stem(prev["path"])
        else:
            want = fname(n["title"])
        cands = [want, fname(f"{n['title']} ({(n.get('meta') or {}).get('valid_to') or n.get('updated', '')[:10]})")
                 if n.get("status", "active") != "active" else fname(f"{n['title']} ({FOLDERS.get(n['type'], '')})"),
                 fname(f"{n['title']} ({nid[-8:]})"), fname(f"{n['title']} ({nid})")]
        st = next((c for c in cands if c.lower() not in taken), f"{want} {len(taken)}")
        taken[st.lower()] = nid
        paths[nid] = f"{folder}/{st}.md"
        if prev and stem(prev["path"]).lower() != st.lower() and prev.get("title") != n["title"]:
            renamed[stem(prev["path"])] = st  # titre changé par le cerveau : les liens des autres pages suivent
    return paths, renamed


def _relink(body, renamed) -> str:
    low = {k.lower(): v for k, v in renamed.items()}

    def sub(m):
        new = low.get(m.group(1).strip().lower())
        if not new:
            return m.group(0)
        return f"[[{new}{m.group(2) or ''}" + (f"|{m.group(3)}" if m.group(3) else "") + "]]"
    return LINK_RX.sub(sub, body)


def _canon_links(body, find, stems_by_id, known) -> str:
    """[[id]] (forme du cerveau classique) → [[Nom de la page]] (forme Obsidian, casse exacte) ; liens vers rien
    laissés tels quels (pages à créer). `known` : nom de page en minuscules → id."""
    def sub(m):
        target = m.group(1).strip()
        nid = known.get(target.lower())
        if nid is not None and stems_by_id.get(nid) == target:
            return m.group(0)
        nid = nid or find(target)
        if not nid or nid not in stems_by_id:
            return m.group(0)
        alias = m.group(3)
        return f"[[{stems_by_id[nid]}{m.group(2) or ''}" + (f"|{alias}" if alias else "") + "]]"
    return LINK_RX.sub(sub, body)


def save(data, root=None, full=False, cache_file=None, parse_file=None, guard=True) -> dict:
    """Écrit dans le wiki les pages qui changent, déplace ou renomme celles qui le doivent, retire celles des souvenirs
    supprimés, puis le cache. full=True (restauration) : toutes les pages sont vérifiées et les effacements massifs
    permis. guard=False (export vers le cerveau commun) : pas de garde-fou contre les effacements massifs.
    → compte rendu {written, moved, removed}."""
    cache_file, parse_file = cache_file or GRAPH_FILE, parse_file or PARSE_FILE
    w = data.get("wiki") or {}
    if w.get("missing"):
        raise WikiMissing(f"wiki introuvable : {w.get('root')} — rebranche le disque, ou `brain config wiki.path <dossier>`")
    root = Path(root or w.get("root"))
    if not (root / MARKER).is_file():
        raise WikiMissing(f"wiki introuvable : {root} (fichier {MARKER} absent)")
    files = dict(w.get("files") or {})
    nodes, edges = data["nodes"], data["edges"]
    for n in nodes.values():  # le wiki écrit les dates à la minute : le cache aussi, pour rester identique au disque
        n["created"], n["updated"] = _minute(n.get("created")), _minute(n.get("updated"))
    paths, renamed = _assign(nodes, files)
    stems_by_id = {nid: stem(p) for nid, p in paths.items()}
    stems = {s.lower(): nid for nid, s in stems_by_id.items()}
    find = _resolver(nodes, stems)
    for n in nodes.values():
        body = n.get("body") or ""
        if "[[" in body:
            if renamed:
                body = _relink(body, renamed)
            n["body"] = _canon_links(body, find, stems_by_id, stems)
    out = {}
    for e in edges:
        if e["from"] in nodes and e["to"] in nodes:
            out.setdefault(e["from"], []).append((e["rel"], e["to"]))
    report = {"written": 0, "moved": 0, "removed": 0}
    gone = [nid for nid in files if nid not in nodes]
    if gone and guard and not full and len(files) >= 10 and len(gone) > MASS_DELETE * len(files):
        raise RuntimeError(f"écriture refusée : elle effacerait {len(gone)} pages sur {len(files)} du wiki")
    new_files, writes = {}, []
    for nid, n in nodes.items():
        k = content_key(n, stems_by_id, out.get(nid, []))
        prev = files.get(nid) or {}
        rel = paths[nid]
        new_files[nid] = {"path": rel, "title": n["title"], "type": n["type"], "status": n.get("status", "active"), "k": k}
        if prev.get("k") == k and prev.get("path") == rel and not full:
            continue
        text = render(n, stems_by_id, out.get(nid, []))
        target = root / rel
        if full and target.is_file():
            try:
                if target.read_text(encoding="utf-8") == text:
                    continue
            except OSError:
                pass
        writes.append((rel, text, prev.get("path")))
    if not writes and not gone:  # rien à écrire (un compteur, un rappel) : le cache seul, même signature
        data["wiki"] = {"root": str(root), "files": new_files, "sig": w.get("sig")}
        write_json(cache_file, data)
        return report
    # État connu des pages (dernière relecture + écritures du cerveau) : la signature en découle, si bien qu'une page
    # modifiée dans Obsidian entre-temps sera relue au prochain passage au lieu d'être masquée par le cache.
    pfiles = _parse_cache(root, parse_file)
    known = {r: (v.get("m"), v.get("s")) for r, v in pfiles.items()}
    keep = {p.lower() for p in paths.values()}
    clash = []
    for rel, text, _ in writes:
        if not full and _touched(root / rel, known.get(rel)):  # modifiée dans Obsidian depuis la lecture : elle gagne
            clash.append(rel)
            try:
                write_text(CONFLICTS / f"{now_iso()[:19].replace(':', '')} {Path(rel).name}", text)
            except OSError as exc:
                log(f"wiki : copie de conflit de {rel} : {exc!r}")
            continue
        write_text(root / rel, text)
        report["written"] += 1
        try:
            st = os.stat(root / rel)
        except OSError:
            continue
        p = parse_page(text)
        p.update(m=st.st_mtime_ns, s=st.st_size)
        pfiles[rel], known[rel] = p, (st.st_mtime_ns, st.st_size)
    olds = [(old, "moved") for rel, _, old in writes if old and old.lower() != rel.lower()]
    olds += [(files[nid].get("path"), "removed") for nid in gone]
    emptied = set()
    for old, what in olds:
        if not old or old.lower() in keep:
            continue
        if not full and _touched(root / old, known.get(old)):  # modifiée entre-temps : jamais effacée
            clash.append(old)
            continue
        try:
            (root / old).unlink()
            report[what] += 1
        except FileNotFoundError:
            pass
        except OSError as exc:
            log(f"wiki : suppression de {old} : {exc!r}")
            continue
        pfiles.pop(old, None)
        known.pop(old, None)
        emptied.add((root / old).parent)
    for d in sorted(emptied, key=lambda p: -len(p.parts)):  # dossiers que le cerveau vient de vider (pas les autres)
        try:
            while d.parent != root and not any(d.iterdir()):
                d.rmdir()
                d = d.parent
        except OSError:
            pass
    if writes or olds:
        try:
            write_json(parse_file, {"v": 1, "root": str(root), "files": pfiles}, indent=None)
        except Exception as exc:
            log(f"wiki : cache des pages : {exc!r}")
    data["wiki"] = {"root": str(root), "files": new_files, "sig": signature(known)}
    write_json(cache_file, data)
    if clash:  # leur signature reste l'ancienne : la prochaine lecture reprend la version d'Obsidian
        report["conflicts"] = clash
        msg = (f"wiki : {len(clash)} page(s) modifiée(s) dans Obsidian pendant l'opération, gardée(s) telle(s) quelle(s) : "
               + ", ".join(clash[:5]) + f" — version du cerveau dans {CONFLICTS}")
        log(msg)
        print(f"⚠ {msg}", file=sys.stderr)
    return report


def _touched(path, seen) -> bool:
    """La page a-t-elle changé sur le disque depuis la dernière lecture du cerveau (seen = (mtime_ns, taille)) ?
    Page jamais lue : non. Page effacée entre-temps : oui (l'effacement fait dans Obsidian l'emporte)."""
    if not seen or seen[0] is None:
        return False
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return (st.st_mtime_ns, st.st_size) != tuple(seen)


def replace_all(data) -> dict:
    """Restauration (instantané, sauvegarde) en mode wiki : l'état donné devient celui des pages."""
    from .store import load_graph
    cur = load_graph() or {}
    w = cur.get("wiki") or {}
    data = dict(data)
    data["wiki"] = {"root": w.get("root"), "files": w.get("files") or {}, "missing": w.get("missing")}
    return save(data, full=True)


def stats(data) -> dict:
    """Compte des pages par type (actives), des archivées et des sources brutes."""
    nodes = {k: v for k, v in (data.get("nodes") or {}).items() if not k.startswith("c--")}  # sans les pages des amis
    by = {}
    for n in nodes.values():
        if n.get("status", "active") == "active":
            by[n["type"]] = by.get(n["type"], 0) + 1
    return {"types": by, "archived": sum(1 for n in nodes.values() if n.get("status", "active") != "active")}
