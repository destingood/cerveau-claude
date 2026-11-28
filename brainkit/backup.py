"""Sauvegarde quotidienne du cerveau, hors de ~/.claude.

Le 14/10/2026, une réinstallation de Windows a effacé le disque C: : le cerveau (~/.claude/brain) y vit aussi.
Une archive est donc écrite chaque jour (en fin de session, en arrière-plan) : graphe, journal, configuration, suivi des
boutiques, derniers instantanés, rapports et résumés de cartes. Les cartes complètes (map.json, search.json) ne sont
pas copiées : elles se régénèrent avec `brain map`.

Où (décision E7 du 21/11/2026) : `backup.dir` s'il est réglé ; sinon, sous Windows, le premier autre disque (D:, E:…) ;
sinon (un seul disque, macOS, Linux) ~/Sauvegardes-cerveau-Claude, et l'utilisateur l'apprend une fois : une
réinstallation du système peut effacer ce dossier. Avant, sans second disque, il n'y avait aucune sauvegarde.

Réparation d'un graph.json abîmé : reparation.py (la dernière sauvegarde y sert de dernier recours)."""
from __future__ import annotations

import json
import os
import shutil
import string
import time
import zipfile
from pathlib import Path

from .common import (BRAIN_DIR, CONFIG_FILE, GRAPH_FILE, INDEX_FILE, JOURNAL_FILE, PROJECTS_DIR, REPORT_FILE, STATE_DIR,
                     load_config)

FOLDER = "Sauvegardes-cerveau-Claude"
HOME_SAID = STATE_DIR / "sauvegarde-perso-dite"  # le dossier personnel choisi faute de second disque a été annoncé


def second_disk():
    """Windows : premier disque qui n'est pas celui du système, avec au moins 1 Go libre. Ailleurs : None."""
    if os.name != "nt":
        return None
    sysdrive = (os.environ.get("SystemDrive") or "C:").upper().rstrip("\\")
    for letter in string.ascii_uppercase[3:]:  # D: … Z:
        root = f"{letter}:\\"
        if f"{letter}:" == sysdrive or not os.path.isdir(root):
            continue
        try:
            if shutil.disk_usage(root).free >= 1 << 30:
                return Path(root) / FOLDER
        except OSError:
            continue
    return None


def home_dir() -> Path:
    """Sans second disque : ~/Sauvegardes-cerveau-Claude (hors de ~/.claude). Un cerveau rangé hors du dossier
    personnel (BRAIN_HOME ailleurs) garde ses sauvegardes à côté de lui."""
    home = Path.home()
    try:
        inside = BRAIN_DIR.resolve().is_relative_to(home.resolve())
    except OSError:
        inside = True
    return home / FOLDER if inside else BRAIN_DIR.resolve().parent / FOLDER


def default_dir():
    return second_disk() or home_dir()


def target_dir():
    cfg = load_config().get("backup", {})
    d = cfg.get("dir")
    return Path(d) if d else default_dir()


def home_notice(dest):
    """Première sauvegarde rangée dans le dossier personnel faute de second disque (ni `backup.dir` ni --to) : la phrase
    à dire, une seule fois. → texte, ou "" (déjà dit, ou ce n'est pas le cas)."""
    if not dest or (load_config().get("backup") or {}).get("dir") or HOME_SAID.exists():
        return ""
    try:
        if Path(dest).resolve() != home_dir().resolve():
            return ""
        HOME_SAID.parent.mkdir(parents=True, exist_ok=True)
        HOME_SAID.write_text(str(dest), encoding="utf-8")
    except OSError:
        return ""
    return (f"💾 Sauvegarde du cerveau : faute de second disque, elle va chaque jour dans {dest}. Une réinstallation "
            "du système peut effacer ce dossier : pour en choisir un autre (disque externe, dossier synchronisé), "
            "`brain config backup.dir <dossier>` (ou `brain backup --to <dossier>` pour une fois).")


def backups(dest=None):
    dest = Path(dest) if dest else target_dir()
    if not dest or not dest.exists():
        return []
    return sorted(dest.glob("cerveau-*.zip"), key=lambda p: p.name, reverse=True)


def _absorb() -> None:
    """Avant de copier graph.json (sauvegarde, instantané avant restauration) : les souvenirs en attente y entrent
    (attente.py), sinon la copie ne les aurait pas."""
    try:
        from . import attente
        attente.absorb()
    except Exception as exc:
        from .common import log
        log(f"sauvegarde : souvenirs en attente : {exc!r}")


def run(dest=None, force=False, keep=None):
    """Écrit une archive (une par jour sauf --force). → chemin de l'archive, ou None si rien à faire."""
    cfg = load_config().get("backup", {})
    dest = Path(dest) if dest else target_dir()
    dest.mkdir(parents=True, exist_ok=True)
    today = time.strftime("%Y%m%d")
    if not force and any(p.name.startswith(f"cerveau-{today}") for p in backups(dest)):
        return None
    _absorb()
    path = dest / f"cerveau-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    tmp = path.with_name(path.name + ".tmp")
    from . import history
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in (GRAPH_FILE, CONFIG_FILE, JOURNAL_FILE, INDEX_FILE, REPORT_FILE, BRAIN_DIR / "MEMOIRES.md",
                  BRAIN_DIR / "journal" / "observations.json", BRAIN_DIR / "journal" / "observations-archive.jsonl"):
            if f.exists():
                z.write(f, f.relative_to(BRAIN_DIR).as_posix())
        for f in sorted((BRAIN_DIR / "boutiques").glob("*.json")):  # suivi des boutiques (chiffres, audits, plan)
            z.write(f, f.relative_to(BRAIN_DIR).as_posix())
        for snap in history.snapshots()[:10]:
            z.write(snap, f"history/{snap.name}")
        for name in ("MAP.md", "DIGEST.md"):
            for f in PROJECTS_DIR.glob(f"*/{name}"):
                z.write(f, f.relative_to(BRAIN_DIR).as_posix())
        z.writestr("LISEZ-MOI.txt", "Sauvegarde du cerveau de Claude (~/.claude/brain).\n"
                                    "Restaurer : python brain.py backup --restore <ce fichier>\n"
                                    "Les cartes complètes de projets se régénèrent avec : python brain.py map <dossier>\n")
    os.replace(tmp, path)
    for old in backups(dest)[keep or cfg.get("keep", 14):]:
        try:
            old.unlink()
        except OSError:
            pass
    return path


def restore(zip_path):
    """Remet graphe, journal et configuration depuis une archive (instantané de l'état courant pris avant)."""
    from . import history
    zp = Path(zip_path)
    with zipfile.ZipFile(zp) as z:
        names = set(z.namelist())
        if "graph.json" not in names:
            raise ValueError("archive sans graph.json")
        graph = json.loads(z.read("graph.json").decode("utf-8"))
        if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), dict):
            raise ValueError("graph.json de l'archive illisible")
        _absorb()
        history.snapshot("avant-restauration-sauvegarde", force=True)
        from .common import write_json
        from .store import replace_all
        replace_all(graph)  # mode wiki : les pages suivent
        boutiques = sorted(r for r in names if r.startswith("boutiques/") and r.endswith(".json") and "/" not in r[10:])
        for rel in ("journal/sessions.json", "journal/observations.json", "config.json", *boutiques):
            if rel in names:
                data = json.loads(z.read(rel).decode("utf-8"))
                write_json(BRAIN_DIR / rel, data)
        if "journal/observations-archive.jsonl" in names:
            from .common import write_text
            write_text(BRAIN_DIR / "journal" / "observations-archive.jsonl",
                       z.read("journal/observations-archive.jsonl").decode("utf-8"))
        for rel in names:
            if rel.startswith("history/") and rel.endswith(".json.gz"):
                out = BRAIN_DIR / rel
                if not out.exists():
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(z.read(rel))
    return len(graph.get("nodes", {}))
