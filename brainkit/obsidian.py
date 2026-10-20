"""Le coffre Obsidian du wiki, réglé pour servir le cerveau sans token : tableau de bord (Bases), propriétés typées,
rétroliens en bas de page, modèles (Alt+T), signets, couleurs du graphe et mode d'emploi.

Tout reste local : aucun module tiers ni module d'IA n'est installé (Omnisearch et New 3D Graph sont conseillés dans le
mode d'emploi, à installer soi-même). Rien n'écrase un réglage de l'utilisateur : un fichier absent est créé, un fichier
présent reçoit seulement ce qui lui manque. Le passage se fait une fois par version (`.obsidian/cerveau.json`) : ce
que l'utilisateur retire ou désactive ensuite le reste."""
from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path

from . import wikistore as ws
from .common import VIZ_FILE, now_iso, write_text

VERSION = 2
STAMP = ".obsidian/cerveau.json"
TEMPLATES_DIR = f"{ws.PAGES}/_modeles"  # « _ » : le cerveau ne le lit pas (wikistore.scan)
DASHBOARD, GUIDE = "Tableau de bord.base", "Mode d'emploi Obsidian.md"

APP = {"attachmentFolderPath": "raw/assets", "newFileLocation": "folder", "newFileFolderPath": "raw",
       "alwaysUpdateLinks": True, "newLinkFormat": "shortest", "useMarkdownLinks": False,
       "userIgnoreFilters": [f"{ws.ARCHIVE}/", f"{TEMPLATES_DIR}/"], "showUnsupportedFiles": True}
# propriétés des pages (wikistore.page_text) : Obsidian les affiche et les filtre selon leur type
TYPES = {"aliases": "aliases", "tags": "tags", "importance": "number", "echeance": "date", "cree": "datetime",
         "maj": "datetime", "prive": "checkbox", "corps_auto": "checkbox",
         **{k: "multitext" for k in (*ws.REL_FM.values(), "sources", "domaine")},
         **{k: "text" for k in ("type", "id", "origine", "resume", "projet", "cles", "nom", "chemin", "stack",
                                "empreinte", "fichier_origine")}}
# fichier absent : la liste complète écrite par Obsidian 1.12 (une clé manquante n'est pas sûre d'être active)
CORE = {"file-explorer": True, "global-search": True, "switcher": True, "graph": True, "backlink": True,
        "outgoing-link": True, "tag-pane": True, "properties": True, "page-preview": True, "templates": True,
        "note-composer": True, "command-palette": True, "bookmarks": True, "outline": True, "word-count": True,
        "file-recovery": True, "sync": False, "publish": False, "daily-notes": False, "canvas": True,
        "footnotes": False, "slash-command": False, "editor-status": True, "zk-prefixer": False, "random-note": False,
        "slides": False, "audio-recorder": False, "workspaces": False, "bases": True, "webviewer": False}
CORE_ON = ("templates", "bases", "backlink", "properties", "bookmarks")
# raccourcis des modules conseillés : sans effet tant qu'ils ne sont pas installés
HOTKEYS = {"templates:insert-template": [{"modifiers": ["Alt"], "key": "T"}],
           "omnisearch:show-modal": [{"modifiers": ["Mod", "Shift"], "key": "O"}],
           "new-3d-graph:open-3d-graph-view": [{"modifiers": ["Mod", "Shift"], "key": "G"}]}
GRAPH_COLORS = {"Profil": 6333946, "Règles": 12616956, "Projets": 16486972, "Décisions": 16498468, "Faits": 3462041,
                "Apprentissages": 2282478, "Références": 10859727, "Entités": 16020150, "À faire": 16478597,
                "Sources": 9741240, "Concepts": 10741301, "Sujets": 16436245, "Analyses": 3003583}
# code tiers des modules : se réinstalle depuis Obsidian ; hors git, la recherche (rg) ne lit pas leurs gros fichiers
GITIGNORE_ADD = (".obsidian/plugins/*/main.js", ".obsidian/plugins/*/styles.css")
# .ignore (lu par rg, donc par Grep/Glob de Claude, git ou pas) : ni les réglages ni la corbeille d'Obsidian
IGNORE_ADD = (".obsidian/", ".trash/")
# Omnisearch : mots-clés et résumé d'une page comptent dans le classement (défauts : nom 10, titre 6, étiquettes 2)
OMNI_WEIGHTS = ({"name": "cles", "weight": 5}, {"name": "resume", "weight": 4})
# nom du modèle → (type, importance, échéance, corps)
TEMPLATES = {"À faire": ("todo", 3, True, ""), "Règle": ("feedback", 4, False, "**Pourquoi :** \n"),
             "Décision": ("decision", 3, False, "**Choix :** \n\n**Pourquoi :** \n"),
             "Apprentissage": ("learning", 3, False, "**Problème :** \n\n**Solution :** \n"),
             "Référence": ("reference", 2, False, "")}

DASHBOARD_TEXT = """filters:
  and:
    - file.inFolder("wiki")
    - 'file.ext == "md"'
    - not:
        - file.inFolder("wiki/_modeles")
formulas:
  etat: 'if(note.echeance.isEmpty(), "sans date", if(note.echeance < today(), "⚠️ en retard", if(note.echeance == today(), "aujourd’hui", note.echeance.relative())))'
  liens: 'file.backlinks.length'
properties:
  note.type:
    displayName: Type
  note.importance:
    displayName: Importance
  note.echeance:
    displayName: Échéance
  note.projet:
    displayName: Projet
  note.maj:
    displayName: Mis à jour
  note.chemin:
    displayName: Dossier
  note.stack:
    displayName: Stack
  formula.etat:
    displayName: État
  formula.liens:
    displayName: Pages qui y renvoient
views:
  - type: table
    name: À faire
    filters:
      and:
        - 'note.type == "afaire"'
    order:
      - file.name
      - formula.etat
      - note.echeance
      - note.importance
      - note.projet
    sort:
      - property: note.echeance
        direction: ASC
  - type: table
    name: Récents
    order:
      - file.name
      - note.type
      - note.projet
      - note.maj
    sort:
      - property: note.maj
        direction: DESC
    limit: 30
  - type: table
    name: Importants
    filters:
      and:
        - 'note.importance >= 4'
    order:
      - file.name
      - note.type
      - note.importance
      - note.projet
      - note.maj
    sort:
      - property: note.importance
        direction: DESC
  - type: table
    name: Projets
    filters:
      and:
        - 'note.type == "projet"'
    order:
      - file.name
      - formula.liens
      - note.chemin
      - note.stack
      - note.maj
    sort:
      - property: formula.liens
        direction: DESC
  - type: table
    name: Décisions
    filters:
      and:
        - 'note.type == "decision"'
    order:
      - file.name
      - note.projet
      - note.importance
      - note.maj
    sort:
      - property: note.maj
        direction: DESC
  - type: table
    name: Apprentissages
    filters:
      and:
        - 'note.type == "apprentissage"'
    order:
      - file.name
      - note.projet
      - note.importance
      - note.maj
    sort:
      - property: note.maj
        direction: DESC
  - type: table
    name: Tout, par type
    groupBy:
      property: note.type
      direction: ASC
    order:
      - file.name
      - note.importance
      - note.projet
      - note.maj
"""

GUIDE_TEXT = """# Mode d'emploi : Obsidian et le cerveau

Obsidian lit et modifie les mêmes fichiers que le cerveau. Tout se passe sur ton PC : **zéro token**.
Claude ne lit pas cette page (elle est hors de `wiki/`).

## Avant de demander à Claude
Chaque question réglée ici évite une requête entière à Claude, soit des dizaines de milliers de tokens de contexte relus.

| Besoin | Dans Obsidian |
|---|---|
| Ce que j'ai à faire | Signets → Cerveau → Tableau de bord → vue « À faire » |
| Retrouver un souvenir | **Ctrl+Maj+O** (Omnisearch, tolère les fautes) · **Ctrl+Maj+F** (recherche intégrée) · **Ctrl+O** (par titre) |
| Tout ce qui touche un projet | Ouvrir la page du projet : les rétroliens sont en bas |
| Dernières décisions, apprentissages | Tableau de bord → Décisions, Apprentissages, Récents |
| Les souvenirs qui comptent le plus | Tableau de bord → Importants |
| Vue d'ensemble | **Ctrl+G** (graphe, une couleur par dossier) · **Ctrl+Maj+G** (graphe 3D) · signet « Cerveau 3D » |

## Corriger la mémoire toi-même (zéro token)
- **Corriger** : modifie le texte ou une propriété (importance, échéance) de la page. Le cerveau la relit au message suivant.
- **Supprimer un souvenir faux** : supprime la page (elle part à la corbeille, récupérable).
- **Archiver** (tâche faite, info périmée) : déplace la page dans `archive/<même dossier>/`. Elle sort du rappel, donc
  Claude ne la recharge plus.
- **Ranger** : déplace une page dans un sous-dossier, le cerveau suit.
- **Ajouter** : clic droit sur le dossier (ex. « À faire ») → Nouvelle note → **Alt+T** → choisis le modèle.
- **Ne touche pas** : les propriétés `id`, `origine`, `cree`, `maj`, ni `index.md` et `log.md` (régénérés par le cerveau).

## Donner une source au cerveau
Dépose le fichier (article, PDF, notes) dans `raw/` (**Ctrl+N** crée une note dans `raw/` ; Obsidian Web Clipper :
dossier `raw`), puis dis à Claude « ingère raw/<nom> ». C'est moins cher que de coller le texte dans la discussion : un
texte collé est relu à chaque message suivant.

## Modules conseillés (facultatifs, à installer toi-même)
Paramètres → Modules complémentaires → Parcourir :
- **Omnisearch** (scambier) : recherche plein texte locale, aucun appel réseau. Version auditée : 1.31.0.
- **New 3D Graph** (Aryan Gupta) : graphe en 3D. Version auditée : 2.8.1.

Leurs raccourcis (Ctrl+Maj+O, Ctrl+Maj+G) sont déjà réglés. Leur code n'est pas versionné dans git : sur un autre
appareil, réinstalle-les depuis Obsidian.

## Volontairement absent
- Aucun module d'IA : il coûterait des tokens ou enverrait tes notes ailleurs.
- Smart Connections : écarté (il exécute du code chargé à distance, non épinglé).
- CLI d'Obsidian : non activée. Elle lance Obsidian si l'appli est fermée et n'apporte rien de plus que les commandes
  du cerveau.
- Serveur MCP Obsidian : non. Ses définitions d'outils seraient renvoyées à chaque requête.

## Mises à jour
Ne clique pas sur « Mettre à jour » pour un module : demande d'abord à Claude d'auditer la nouvelle version.
"""


def template_text(t, importance, due, body) -> str:
    fm = [f"type: {ws.FR_TYPES[t]}", 'resume: ""'] + (["echeance: {{date:YYYY-MM-DD}}"] if due else []) + \
         [f"importance: {importance}", "tags: []"]
    return "---\n" + "\n".join(fm) + "\n---\n# {{title}}\n\n" + body


def _bookmarks() -> list:
    ms = int(time.time() * 1000)
    return [{"type": "file", "ctime": ms, "path": DASHBOARD, "title": "Tableau de bord (À faire, récents, projets…)"},
            {"type": "file", "ctime": ms, "path": GUIDE, "title": "Mode d'emploi (Obsidian + cerveau)"},
            {"type": "url", "ctime": ms, "url": Path(VIZ_FILE).as_uri(), "title": "Cerveau 3D (vue complète)"},
            {"type": "file", "ctime": ms, "path": "index.md", "title": "Index du cerveau"}]


def _marks(items) -> set:
    out = set()
    for it in items or []:
        if isinstance(it, dict):
            out.add(it.get("path") or it.get("url") or "")
            out |= _marks(it.get("items"))
    return out


def _add_bookmarks(cur):
    items = cur.setdefault("items", [])
    have = _marks(items)
    new = [b for b in _bookmarks() if (b.get("path") or b.get("url")) not in have]
    if not new:
        return cur
    group = next((g for g in items if isinstance(g, dict) and g.get("type") == "group" and g.get("title") == "Cerveau"),
                 None)
    if group is None:
        items.append({"type": "group", "ctime": new[0]["ctime"], "title": "Cerveau", "items": new})
    else:
        group.setdefault("items", []).extend(new)
    return cur


def _combo(k) -> tuple:
    return tuple(sorted(k.get("modifiers") or [])), str(k.get("key") or "").upper()


def _add_hotkeys(cur):
    used = {_combo(k) for keys in cur.values() if isinstance(keys, list) for k in keys if isinstance(k, dict)}
    for cmd, keys in HOTKEYS.items():
        if cmd not in cur and not any(_combo(k) in used for k in keys):
            cur[cmd] = copy.deepcopy(keys)
    return cur


def _add_app(cur):
    for k, v in APP.items():
        cur.setdefault(k, copy.deepcopy(v))
    filters = cur["userIgnoreFilters"] if isinstance(cur.get("userIgnoreFilters"), list) else None
    for f in APP["userIgnoreFilters"] if filters is not None else ():
        if f not in filters:
            filters.append(f)
    return cur


def _add_core(cur):
    if isinstance(cur, list):  # ancien format : la liste des modules actifs
        return cur + [m for m in CORE_ON if m not in cur]
    cur.update({m: True for m in CORE_ON})
    return cur


def _add_types(cur):
    t = cur.setdefault("types", {})
    for k, v in TYPES.items():
        t.setdefault(k, v)
    return cur


def _add_omni(cur):
    w = cur.get("weightCustomProperties") if isinstance(cur, dict) else None
    if isinstance(w, list):
        names = {x.get("name") for x in w if isinstance(x, dict)}
        w += [dict(x) for x in OMNI_WEIGHTS if x["name"] not in names]
    return cur


def _setdefaults(values):
    def fn(cur):
        for k, v in values.items():
            cur.setdefault(k, v)
        return cur
    return fn


def setup(root, force=False) -> list:
    """Règle le coffre Obsidian du wiki (idempotent, une fois par version sauf `force`). → fichiers créés ou complétés.
    Jamais dans une session cloud : ses changements partiraient en pull request."""
    root = Path(root)
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true" and not force:
        return []
    try:
        done = json.loads((root / STAMP).read_text(encoding="utf-8")).get("version", 0) >= VERSION
    except (OSError, ValueError, AttributeError):
        done = False
    if done and not force:
        return []
    made = []

    def put(rel, text):
        p = root / rel
        if not p.exists():
            write_text(p, text)
            made.append(rel)

    def merge(rel, default, fn):
        p = root / ".obsidian" / rel
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            cur = None
        except (OSError, ValueError):
            return  # illisible (en cours d'écriture par Obsidian ?) : on n'y touche pas
        if cur is not None and not isinstance(cur, (dict, list)):
            return
        new = fn(copy.deepcopy(default if cur is None else cur))
        if new != cur:
            write_text(p, json.dumps(new, ensure_ascii=False, indent=2) + "\n")
            made.append(f".obsidian/{rel}")

    merge("app.json", APP, _add_app)
    merge("types.json", {"types": TYPES}, _add_types)
    merge("core-plugins.json", CORE, _add_core)
    merge("backlink.json", {"backlinkInDocument": True}, _setdefaults({"backlinkInDocument": True}))
    merge("templates.json", {"folder": TEMPLATES_DIR}, _setdefaults({"folder": TEMPLATES_DIR}))
    merge("hotkeys.json", HOTKEYS, _add_hotkeys)
    merge("bookmarks.json", {"items": []}, _add_bookmarks)
    if (root / ".obsidian" / "plugins" / "omnisearch" / "data.json").is_file():  # module installé et déjà lancé
        merge("plugins/omnisearch/data.json", {}, _add_omni)
    put(".obsidian/graph.json", json.dumps({
        "search": f"path:{ws.PAGES}", "showTags": False, "showAttachments": False, "hideUnresolved": True,
        "showOrphans": True, "showArrow": False,
        "colorGroups": [{"query": f"path:{ws.PAGES}/{folder}", "color": {"a": 1, "rgb": rgb}}
                        for folder, rgb in GRAPH_COLORS.items()]}, ensure_ascii=False, indent=2) + "\n")
    put(DASHBOARD, DASHBOARD_TEXT)
    put(GUIDE, GUIDE_TEXT)
    for name, spec in TEMPLATES.items():
        put(f"{TEMPLATES_DIR}/{name}.md", template_text(*spec))
    for rel, add, create in ((".gitignore", GITIGNORE_ADD, False), (".ignore", IGNORE_ADD, True)):
        p = root / rel
        if not p.is_file() and not create:
            continue
        text = p.read_text(encoding="utf-8") if p.is_file() else ""
        miss = [ln for ln in add if ln not in text.splitlines()]
        if miss:
            write_text(p, (text.rstrip("\n") + "\n" if text.strip() else "") + "\n".join(miss) + "\n")
            made.append(rel)
    write_text(root / STAMP, json.dumps({"version": VERSION, "le": now_iso()[:10],
                                         "note": "réglages Obsidian du cerveau appliqués (brain wiki obsidian)"},
                                        ensure_ascii=False) + "\n")
    return made
