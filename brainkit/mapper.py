"""Cartographe de projets façon graphify — 100 % local, sans dépendance externe.

fichiers → symboles (fonctions, classes, routes, variables d'env), imports/liens résolus → graphe,
centralité (PageRank), modules (propagation de labels), cycles, points d'entrée, stack technique.
Documents aussi : titres Markdown, Word (.docx), feuilles Excel (.xlsx), diapos (.pptx), PDF, CSV.

Sorties dans ~/.claude/brain/projects/<id>/ :
  map.json     données complètes → requêtes where / deps / explain / impact / path / files
  MAP.md       rapport lisible (structure, fichiers clés, modules, routes, docs, points d'attention)
  DIGEST.md    résumé court injecté automatiquement au démarrage d'une session dans ce projet
  search.json  index de recherche pré-calculé (rappel automatique des fichiers pertinents)
Incrémental : fichier inchangé (taille, date à la nanoseconde, n° du fichier) → pas relu ; relu avec le même hash →
pas re-parsé.

Le code est réparti en modules (découpage du 21/11/2026, sans changer le comportement) :
  carte_langages  extensions reconnues, utilitaires, parseurs des formats (sauf Python)
  carte_python    parseur Python et graphe d'appels
  carte_parcours  parcours du dossier, lecture incrémentale des fichiers, copies identiques
  carte_graphe    résolution des imports (paquets locaux compris), analyse du graphe, stack, points d'entrée
  carte_rapports  MAP.md, DIGEST.md, search.json
  carte_requetes  where, deps, explain, path, impact
Ce module garde l'orchestration (map_project) ; tous les noms d'avant le découpage restent accessibles ici
(`mapper.where`, `from .mapper import file_desc`…), chargés à la demande (__getattr__)."""
from __future__ import annotations

import importlib
import os
import tempfile
import time
from collections import Counter
from pathlib import Path

from .carte_langages import _kind, CODE, LANG_BY_EXT, SPECIAL_FILES
from .common import (CLAUDE_HOME, FileLock, is_scratch, load_config, log, norm_path, now_iso, path_within,
                     PROJECTS_DIR, read_json, write_json, write_text)
from .store import Brain

# =============================================================================================== orchestration
# Vrais marqueurs d'un projet : dépôt git, fichier de build ou de dépendances. README.md et CLAUDE.md n'en sont plus
# (audit du 20/11 : un dossier qui ne contenait qu'un README devenait un projet, recartographié toutes les 10 min).
MARKERS = {".git", "package.json", "pyproject.toml", "requirements.txt", "setup.py", "cargo.toml", "go.mod",
           "composer.json", "gemfile", "pom.xml", "build.gradle", "manifest.json", "dockerfile", "docker-compose.yml",
           "makefile", "deno.json", "pubspec.yaml"}
DOCS_MIN = 3  # sans marqueur ni fichier source : dossier de documents à partir de 3 fichiers lisibles


def looks_like_project(path) -> bool:
    """Dossier « projet », pas un dossier système/perso trop large : un vrai marqueur (MARKERS, .sln, .csproj), un
    fichier source (Python, JavaScript, HTML…), ou au moins DOCS_MIN documents ou données. Un README seul (ou avec un
    CLAUDE.md) ne suffit pas."""
    try:
        p = norm_path(path)
        if not os.path.isdir(p) or is_scratch(p):
            return False
        home = Path.home()
        blocked = {norm_path(home), norm_path(tempfile.gettempdir())} | {norm_path(home / d) for d in (
            "Desktop", "Documents", "Downloads", "OneDrive", "Pictures", "Music", "Videos", "AppData", "AppData/Local",
            "AppData/Roaming", "AppData/LocalLow")}  # Temp lui-même (session lancée là) : 15 000 fichiers, pas un projet
        if p in blocked or p == norm_path(os.path.splitdrive(p)[0] + os.sep) or path_within(p, CLAUDE_HOME):
            return False
        for var in ("WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
            if os.environ.get(var) and path_within(p, os.environ[var]):
                return False
        entries = os.listdir(p)
    except OSError:
        return False
    low = {e.lower() for e in entries}
    if low & MARKERS or any(e.endswith((".sln", ".csproj")) for e in low):
        return True
    if any(LANG_BY_EXT.get(os.path.splitext(e)[1]) in CODE or SPECIAL_FILES.get(e) in CODE for e in low):
        return True  # un fichier source
    return sum(1 for e in low if os.path.splitext(e)[1] in LANG_BY_EXT) >= DOCS_MIN


def map_project(path=None, project=None, quiet=False, full=False, max_files=None):
    cfg = load_config()["map"]
    explicit = path not in (None, "", ".")
    root = os.path.abspath(path or os.getcwd())
    if not os.path.isdir(root):
        raise ValueError(f"dossier introuvable : {root}")
    with Brain.edit() as b:
        proj = b.resolve_project(project, root) if project else None
        if not proj:
            proj = b.project_for_path(root)
            if proj and explicit and norm_path((proj.get("meta") or {}).get("path", "")) != norm_path(root):
                proj = None
            if not proj:
                proj, _ = b.ensure_project(root, source="map")
        pid, title = proj["id"], proj["title"]
        proj_root = (proj.get("meta") or {}).get("path")
        if proj_root and os.path.isdir(proj_root):
            root = proj_root
    outdir = PROJECTS_DIR / pid
    outdir.mkdir(parents=True, exist_ok=True)
    lock = FileLock(outdir / ".map.lock", timeout=0.2 if quiet else 300, stale=1800)
    try:
        lock.__enter__()
    except TimeoutError:
        return {"pid": pid, "skipped": "une cartographie de ce projet est déjà en cours"}
    try:
        return _map_locked(pid, title, root, outdir, cfg, full, max_files)
    finally:
        lock.__exit__()


def _map_locked(pid, title, root, outdir, cfg, full, max_files):
    # chargés ici, pas à l'import : un hook qui demande seulement looks_like_project ne charge pas les parseurs
    from .carte_graphe import analyze, detect_stack, entry_points, resolve
    from .carte_parcours import RACY_NS, mark_duplicates, process_file, walk
    from .carte_rapports import build_digest, build_report, build_search
    from .filesearch import build_cache
    t0 = time.time()
    old = {} if full else (read_json(outdir / "map.json", {}) or {})
    previous = old.get("files") or {}
    scanned = (old.get("meta") or {}).get("scan_ns")
    racy = scanned - RACY_NS if isinstance(scanned, int) else None
    scan_ns = time.time_ns()  # avant le parcours : un fichier modifié pendant celui-ci sera relu la fois suivante
    listing, truncated = walk(root, max_files or cfg["max_files"])
    files, parsed = {}, 0
    max_bytes = cfg["max_file_kb"] * 1024
    for rel, size, mtime, ino in listing:
        res = process_file(root, rel, previous.get(rel), max_bytes, size, mtime, ino, racy)
        if res is None:
            continue
        rec, was_parsed = res
        for k in ("out", "ext", "pr", "mod", "dup"):  # champs dérivés : recalculés à chaque passage
            rec.pop(k, None)
        files[rel] = rec
        parsed += int(was_parsed)
    dup_count, dup_dirs = mark_duplicates(files)
    resolve(files)
    in_edges, pr, comms, sccs = analyze(files)
    for rel, score in pr.items():
        files[rel]["pr"] = round(score, 6)
    for lab, mem in comms.items():
        for m in mem:
            files[m]["mod"] = lab
    pkg = (files.get("package.json") or {}).get("pkg") or {}
    meta = {"pid": pid, "name": title, "root": root, "generated": now_iso(), "truncated": truncated,
            "n_files": len(files), "parsed": parsed, "stack": detect_stack(files), "entries": entry_points(files),
            "scripts": pkg.get("scripts") or {}, "dups": dup_count, "dup_dirs": dup_dirs.most_common(4),
            "scan_ns": scan_ns}
    meta["seconds"] = round(time.time() - t0, 2)
    write_json(outdir / "map.json", {"meta": meta, "files": files, "cycles": sccs}, indent=None)
    write_text(outdir / "MAP.md", build_report(meta, files, in_edges, pr, comms, sccs))
    write_text(outdir / "DIGEST.md", build_digest(meta, files, pr, comms, pid))
    search_data = build_search(files)
    write_json(outdir / "search.json", search_data, indent=None)
    build_cache(pid, search_data)  # le rappel à chaque message lit ce cache binaire
    _update_project_node(pid, meta, files)
    return meta


def _update_project_node(pid, meta, files):
    try:
        with Brain.edit() as b:
            n = b.nodes.get(pid)
            if not n:
                return
            m = n.setdefault("meta", {})
            m["mapped"] = meta["generated"]
            m["stack"] = meta["stack"].get("summary", "")
            if not n.get("body") or m.get("auto_body"):
                kinds = Counter(_kind(f) for f in files.values())
                n["body"] = (f"{meta['stack'].get('summary') or 'Dossier'} — {meta['n_files']} fichiers "
                             f"({kinds['code']} code, {kinds['doc']} docs, {kinds['data']} données). "
                             f"Description auto, à préciser : `brain edit {pid} -b \"…\"`.")
                m["auto_body"] = True
            b.dirty = True
    except Exception as exc:
        log(f"maj projet {pid} : {exc!r}")


# =============================================================================================== noms d'avant le découpage
_PARTS = ("carte_langages", "carte_python", "carte_parcours", "carte_graphe", "carte_rapports", "carte_requetes")
_FROM_FILESEARCH = ("BACKUP_RX", "build_cache", "needs_refresh", "recall_files", "search_files")  # déjà donnés ici avant


def __getattr__(name):
    """mapper.where, mapper.walk, mapper.PARSERS… : cherchés dans les modules de la carte (dans l'ordre des couches),
    puis gardés ici. Un nom inconnu reste une AttributeError, comme avant."""
    if name in _FROM_FILESEARCH:
        from . import filesearch
        value = globals()[name] = getattr(filesearch, name)
        return value
    if not name.startswith("__"):
        for part in _PARTS:
            mod = importlib.import_module(f".{part}", __package__)
            if name in vars(mod):
                value = globals()[name] = vars(mod)[name]
                return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
