"""Sauvegarde du cerveau hors du disque système, et réparation automatique.

Le 14/10/2026, une réinstallation de Windows a effacé le disque C: : le cerveau (~/.claude/brain) y vit aussi.
Une archive est donc écrite chaque jour (en fin de session, en arrière-plan) sur un autre disque (D:, E:…) :
graphe, journal, configuration, derniers instantanés, rapports et résumés de cartes. Les cartes complètes
(map.json, search.json) ne sont pas copiées : elles se régénèrent avec `brain map`.

Réparation : si graph.json est illisible (corrompu), le cerveau repart automatiquement du dernier instantané valide,
puis de la dernière sauvegarde ; le fichier abîmé est gardé à côté (graph.corrupt-…json)."""
from __future__ import annotations

import io
import json
import os
import shutil
import string
import time
import zipfile
from pathlib import Path

from .common import BRAIN_DIR, CONFIG_FILE, GRAPH_FILE, INDEX_FILE, JOURNAL_FILE, PROJECTS_DIR, REPORT_FILE, load_config, log

FOLDER = "Sauvegardes-cerveau-Claude"


def default_dir():
    """Premier disque qui n'est pas celui du système, avec au moins 1 Go libre."""
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


def target_dir():
    cfg = load_config().get("backup", {})
    d = cfg.get("dir")
    return Path(d) if d else default_dir()


def backups(dest=None):
    dest = Path(dest) if dest else target_dir()
    if not dest or not dest.exists():
        return []
    return sorted(dest.glob("cerveau-*.zip"), key=lambda p: p.name, reverse=True)


def run(dest=None, force=False, keep=None):
    """Écrit une archive (une par jour sauf --force). → chemin de l'archive, ou None si rien à faire."""
    cfg = load_config().get("backup", {})
    dest = Path(dest) if dest else target_dir()
    if not dest:
        raise RuntimeError("aucun disque de sauvegarde trouvé (D:, E:…) — choisis un dossier : brain backup --to <dossier>")
    dest.mkdir(parents=True, exist_ok=True)
    today = time.strftime("%Y%m%d")
    if not force and any(p.name.startswith(f"cerveau-{today}") for p in backups(dest)):
        return None
    path = dest / f"cerveau-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    tmp = path.with_name(path.name + ".tmp")
    from . import history
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in (GRAPH_FILE, CONFIG_FILE, JOURNAL_FILE, INDEX_FILE, REPORT_FILE, BRAIN_DIR / "MEMOIRES.md",
                  BRAIN_DIR / "journal" / "observations.json", BRAIN_DIR / "journal" / "observations-archive.jsonl"):
            if f.exists():
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
        history.snapshot("avant-restauration-sauvegarde", force=True)
        from .common import write_json
        from .store import replace_all
        replace_all(graph)  # mode wiki : les pages suivent
        for rel in ("journal/sessions.json", "journal/observations.json", "config.json"):
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


def recover_graph():
    """graph.json illisible → données du dernier instantané valide, sinon de la dernière sauvegarde. → dict ou None."""
    from . import history
    for snap in history.snapshots():
        try:
            data = history.load(snap)
            if isinstance(data, dict) and isinstance(data.get("nodes"), dict):
                log(f"RÉPARATION : graph.json illisible → repris de l'instantané {snap.name}")
                return data
        except Exception:
            continue
    for zp in backups():
        try:
            with zipfile.ZipFile(zp) as z:
                data = json.loads(z.read("graph.json").decode("utf-8"))
            if isinstance(data, dict) and isinstance(data.get("nodes"), dict):
                log(f"RÉPARATION : graph.json illisible → repris de la sauvegarde {zp}")
                return data
        except Exception:
            continue
    return None
