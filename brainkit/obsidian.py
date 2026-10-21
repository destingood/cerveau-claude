"""Le coffre Obsidian du wiki, réglé pour servir le cerveau sans token : tableau de bord (Bases), propriétés typées,
rétroliens en bas de page, modèles (Alt+T), signets, couleurs du graphe et mode d'emploi ; page « Cerveau » (état du
cerveau) et carte des thèmes (Canvas), réécrites en fin de session ; note du jour (Alt+J) dont les lignes « À retenir »
deviennent des souvenirs au démarrage de la session suivante.

Tout reste local : aucun module tiers ni module d'IA n'est installé (Omnisearch et New 3D Graph sont conseillés dans le
mode d'emploi, à installer soi-même). Rien n'écrase un réglage de l'utilisateur : un fichier absent est créé, un fichier
présent reçoit seulement ce qui lui manque. Le passage se fait une fois par version (`.obsidian/cerveau.json`) : ce
que l'utilisateur retire ou désactive ensuite le reste."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
from pathlib import Path

from . import wikistore as ws
from .common import STATE_DIR, VIZ_FILE, fmt_date, fold, log, now_iso, path_within, short, write_text

VERSION = 3
STAMP = ".obsidian/cerveau.json"
TEMPLATES_DIR = f"{ws.PAGES}/_modeles"  # « _ » : le cerveau ne le lit pas (wikistore.scan)
DASHBOARD, GUIDE = "Tableau de bord.base", "Mode d'emploi Obsidian.md"
STATUS, CARD = "Cerveau.md", "Carte du cerveau.canvas"  # générés en fin de session (hors wiki/ : jamais relus)
DAYS_DIR, DAY_TEMPLATE, CAPTURE_HEAD = "Notes du jour", "Jour", "À retenir"
DAILY = {"folder": DAYS_DIR, "format": "YYYY-MM-DD", "template": f"{TEMPLATES_DIR}/{DAY_TEMPLATE}"}

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
CORE_ON = ("templates", "bases", "backlink", "properties", "bookmarks", "daily-notes", "canvas")
# raccourcis des modules conseillés : sans effet tant qu'ils ne sont pas installés
HOTKEYS = {"templates:insert-template": [{"modifiers": ["Alt"], "key": "T"}],
           "daily-notes": [{"modifiers": ["Alt"], "key": "J"}],  # « Ouvrir la note du jour » (obsidian.asar 1.12)
           "omnisearch:show-modal": [{"modifiers": ["Mod", "Shift"], "key": "O"}],
           "new-3d-graph:open-3d-graph-view": [{"modifiers": ["Mod", "Shift"], "key": "G"}]}
GRAPH_COLORS = {"Profil": 6333946, "Règles": 12616956, "Projets": 16486972, "Décisions": 16498468, "Faits": 3462041,
                "Apprentissages": 2282478, "Références": 10859727, "Entités": 16020150, "À faire": 16478597,
                "Sources": 9741240, "Concepts": 10741301, "Sujets": 16436245, "Analyses": 3003583}
# code tiers des modules : se réinstalle depuis Obsidian ; hors git, la recherche (rg) ne lit pas leurs gros fichiers.
# Page Cerveau et carte : régénérées sur chaque PC, versionnées elles se contrediraient d'un PC à l'autre (conflit git)
GITIGNORE_ADD = (".obsidian/plugins/*/main.js", ".obsidian/plugins/*/styles.css", f"/{STATUS}", f"/{CARD}")
# .ignore (lu par rg, donc par Grep/Glob de Claude, git ou pas) : ni les réglages ni la corbeille d'Obsidian, ni la page
# Cerveau et la carte (copies de ce que le cerveau sait déjà : doublons dans les recherches)
IGNORE_ADD = (".obsidian/", ".trash/", f"/{STATUS}", f"/{CARD}")
# Omnisearch : mots-clés et résumé d'une page comptent dans le classement (défauts : nom 10, titre 6, étiquettes 2)
OMNI_WEIGHTS = ({"name": "cles", "weight": 5}, {"name": "resume", "weight": 4})
# nom du modèle → (type, importance, échéance, corps)
TEMPLATES = {"À faire": ("todo", 3, True, ""), "Règle": ("feedback", 4, False, "**Pourquoi :** \n"),
             "Décision": ("decision", 3, False, "**Choix :** \n\n**Pourquoi :** \n"),
             "Apprentissage": ("learning", 3, False, "**Problème :** \n\n**Solution :** \n"),
             "Référence": ("reference", 2, False, "")}
# préfixe d'une ligne « À retenir » (replié : sans accents, minuscules) → type du souvenir ; sans préfixe : un fait
PREFIXES = {"regle": "feedback", "preference": "feedback", "decision": "decision", "a faire": "todo", "tache": "todo",
            "todo": "todo", "apprentissage": "learning", "astuce": "learning", "piege": "learning",
            "reference": "reference", "ref": "reference", "lien": "reference", "fait": "fact", "info": "fact"}
CAPTURE_QUIET = 600  # s : une note modifiée il y a moins de 10 min attend la session d'après (en cours d'écriture ?)
CAPTURE_DAYS = 60  # jours : au-delà, une note du jour n'est plus relue

DAY_TEXT = f"""# {{{{date:dddd D MMMM YYYY}}}}

## {CAPTURE_HEAD}
%% Une ligne par souvenir. Au début de la prochaine session de Claude, le cerveau la mémorise puis la marque ✓.
Préfixe facultatif : « règle : », « décision : », « à faire : … le 25/10 », « apprentissage : », « référence : »
(sans préfixe : un fait). %%
-{" "}

## Notes

"""

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

GUIDE_HEAD = "# Mode d'emploi : Obsidian et le cerveau"
LIVE_HEAD = "## Le cerveau dans Obsidian"
# ajoutée telle quelle au mode d'emploi d'avant la 8.8 (s'il est encore celui du cerveau : son titre est là)
GUIDE_LIVE = f"""{LIVE_HEAD}
| Quoi | Où |
|---|---|
| État du cerveau : échéances, à-faire, dernières sessions, santé du wiki, cerveau commun | Signet « Cerveau » (page `{STATUS}`) |
| Les grands thèmes de la mémoire, en cartes cliquables | Signet « Carte du cerveau » (Canvas) |
| Noter un souvenir sans ouvrir Claude | **Alt+J** (note du jour) → une ligne sous « {CAPTURE_HEAD} » |

- La page Cerveau et la carte sont réécrites à chaque fin de session de Claude : ne les modifie pas (pour garder une
  disposition de la carte, duplique le fichier). Elles restent hors de git : chaque PC a les siennes.
- Note du jour : une ligne par souvenir sous « {CAPTURE_HEAD} », avec un préfixe facultatif (« règle : », « décision : »,
  « à faire : … le 25/10 », « apprentissage : », « référence : » ; sans préfixe : un fait). Au début de la session
  suivante de Claude, le cerveau les mémorise en tâche de fond, sans rien ajouter à la discussion, et marque chaque
  ligne « ✓ … → [[page]] ». Une note modifiée il y a moins de 10 minutes attend la session d'après. Ces souvenirs
  restent privés (jamais envoyés au cerveau commun). Les notes vont dans `{DAYS_DIR}/`, hors de `wiki/` : Claude ne
  les lit pas.
"""

GUIDE_TEXT = f"""{GUIDE_HEAD}

Obsidian lit et modifie les mêmes fichiers que le cerveau. Tout se passe sur ton PC : **zéro token**.
Claude ne lit pas cette page (elle est hors de `wiki/`).

{GUIDE_LIVE}
## Avant de demander à Claude
Chaque question réglée ici évite une requête entière à Claude, soit des dizaines de milliers de tokens de contexte relus.

| Besoin | Dans Obsidian |
|---|---|
| Ce que j'ai à faire | Signet « Cerveau » · Tableau de bord → vue « À faire » |
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
    return [{"type": "file", "ctime": ms, "path": STATUS, "title": "Cerveau (échéances, sessions, santé du wiki)"},
            {"type": "file", "ctime": ms, "path": CARD, "title": "Carte du cerveau (grands thèmes)"},
            {"type": "file", "ctime": ms, "path": DASHBOARD, "title": "Tableau de bord (À faire, récents, projets…)"},
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


def _add_live(text):
    """Mode d'emploi d'avant la 8.8, encore celui du cerveau : la section « Le cerveau dans Obsidian » en tête."""
    if not text.startswith(GUIDE_HEAD) or LIVE_HEAD in text:
        return None
    i = text.find("\n## ")
    return text + "\n" + GUIDE_LIVE if i < 0 else text[:i + 1] + GUIDE_LIVE + text[i:]


# ------------------------------------------------------------------------------------------ page Cerveau, carte
def _names(brain) -> dict:
    files = (brain.data.get("wiki") or {}).get("files") or {}
    return {nid: ws.stem(v["path"]) for nid, v in files.items() if v.get("path")}


def _mine(brain) -> list:
    return [n for k, n in brain.data["nodes"].items() if not k.startswith("c--") and n.get("status", "active") == "active"]


def _link(names, n) -> str:
    return f"[[{names[n['id']]}]]" if n["id"] in names else f"« {short(n['title'], 80)} »"


def _put_if_changed(p, text, keep=lambda s: s) -> bool:
    try:
        if keep(p.read_text(encoding="utf-8")) == keep(text):
            return False
    except OSError:
        pass
    write_text(p, text)
    return True


def _live_ok(root) -> bool:
    """Page Cerveau et carte : seulement dans un coffre réglé par le cerveau, et jamais dans une session cloud."""
    return bool(root) and os.environ.get("CLAUDE_CODE_REMOTE") != "true" and (Path(root) / STAMP).is_file()


STATUS_STAMP = "_Réécrite par le cerveau"


def status_text(brain, root, today=None) -> str:
    """Page « Cerveau » : ce que Claude répondrait sur l'état du cerveau, lu dans Obsidian sans lui (zéro token)."""
    import datetime as _dt
    from . import __version__, dates, journal, wiki
    from .privacy import mask
    from .store import TYPES
    today = today or _dt.date.today()
    names, mine = _names(brain), _mine(brain)
    out = ["# 🧠 Cerveau", "", f"{STATUS_STAMP} à chaque fin de session de Claude : ne pas modifier. État du "
                                f"{today:%d/%m/%Y}, cerveau {__version__}._", ""]
    dated = sorted(((d, n) for n in mine for d in [dates.due_of(n, today)]
                    if d and dates.days_until(d, today) is not None and dates.days_until(d, today) <= 14),
                   key=lambda x: (x[0], x[1]["title"]))
    out += ["## ⏰ Échéances (14 jours)", ""]
    out += [f"- {'⚠️ ' if dates.days_until(d, today) < 0 else ''}{_link(names, n)} — {dates.human(d, today)}"
            + (f" · {n['project']}" if n.get("project") else "") for d, n in dated[:25]] or ["- Rien dans les 14 jours."]
    todo = sorted((n for n in mine if n["type"] == "todo" and not dates.due_of(n, today)),
                  key=lambda n: (-n.get("importance", 3), str(n.get("created") or "")))
    out += ["", f"## ☑️ À faire sans date ({len(todo)})", ""]
    out += [f"- {_link(names, n)}" + (f" · {n['project']}" if n.get("project") else "") for n in todo[:15]] or ["- Rien."]
    if len(todo) > 15:
        out.append(f"- … et {len(todo) - 15} autre(s) : [[{DASHBOARD}]] → vue « À faire »")
    rows = []
    for s in sorted((journal.load().get("sessions") or {}).values(),
                    key=lambda s: str(s.get("end") or s.get("start") or ""), reverse=True):
        what = s.get("title") or s.get("first") or s.get("brief")
        if not what:
            continue
        when = str(s.get("end") or s.get("start") or "")
        rows.append(f"- {fmt_date(when)[:5]} {when[11:16]} « {short(what, 90)} »"
                    + (f" · {s['project']}" if s.get("project") else "")
                    + (f" — dernière demande : « {short(s['last'], 120)} »" if s.get("last") and s.get("last") != s.get("first")
                       else ""))
        if len(rows) == 6:
            break
    out += ["", "## 💬 Dernières sessions", ""] + (rows or ["- Aucune encore."])
    st = ws.stats(brain.data)
    out += ["", "## 📚 Mémoire", "", "| Type | Pages |", "|---|---:|"]
    out += [f"| {TYPES.get(t, t)} | {c} |" for t, c in sorted(st["types"].items(), key=lambda x: (-x[1], x[0]))]
    out += ["", f"Archivées : {st['archived']} · liens : {len(brain.data.get('edges') or [])} · [[{CARD}|carte des thèmes]]"]
    rep = wiki.lint(brain, root, 1000)
    out += ["", "## 🩺 Santé du wiki", ""]
    out += [f"- **{title}** : {len(items)} — " + " · ".join(items[:3]) + (" …" if len(items) > 3 else "")
            for title, items in rep.items()] or ["- ✓ rien à signaler"]
    if rep:
        out += ["", "_À régler avec Claude : « entretiens le wiki » (`brain wiki lint`)._"]
    try:
        from . import commun
        out += ["", "## 🤝 Cerveau commun", "", commun.status(brain)]
    except Exception as exc:
        log(f"obsidian : cerveau commun : {exc!r}")
    from . import tokens
    conso = tokens.guard_lines()
    if conso:
        out += ["", "## 🔥 Consommation", ""] + conso
    out += ["", "## 📝 Noter sans Claude", "",
            f"**Alt+J** ouvre la note du jour : une ligne sous « {CAPTURE_HEAD} » devient un souvenir au début de la "
            "session suivante (préfixes : règle, décision, à faire, apprentissage, référence)."]
    return mask("\n".join(out) + "\n")[0]


def write_status(brain, root) -> bool:
    """`Cerveau.md` à jour (réécrite seulement si autre chose que sa date a changé). → écrite ?"""
    if not _live_ok(root):
        return False
    text = status_text(brain, root)
    return _put_if_changed(Path(root) / STATUS, text,
                           lambda s: "\n".join(x for x in s.split("\n") if not x.startswith(STATUS_STAMP)))


CARD_W, CARD_H, GAP, PER_ROW, GROUPS, PER_GROUP = 300, 120, 20, 3, 8, 10


def _cid(key) -> str:
    return hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:16]


def canvas_data(brain) -> dict:
    """Carte des thèmes (JSON Canvas 1.0) : les plus grandes communautés du graphe, une carte par page (couleur de son
    dossier), groupées par thème, avec les liens entre les cartes affichées."""
    from . import graph
    from .privacy import mask
    from .store import TYPES
    names = _names(brain)
    files = brain.data["wiki"]["files"]
    nodes = brain.data["nodes"]
    an = graph.ensure(brain)
    comms = []
    for c in an.get("communities") or []:
        mem = [i for i in c["members"] if i in names and not i.startswith("c--")
               and (nodes.get(i) or {}).get("status", "active") == "active"][:PER_GROUP]
        if len(mem) >= 2:
            comms.append((c, mem))
        if len(comms) == GROUPS:
            break
    gw = 2 * CARD_W + 3 * GAP
    out = [{"id": _cid("titre"), "type": "text", "x": 0, "y": -220, "width": PER_ROW * gw + (PER_ROW - 1) * 80,
            "height": 140, "text": "# Carte du cerveau\nLes grands thèmes de la mémoire, regroupés par le cerveau. Une carte "
            "= une page : clic sur son lien pour l'ouvrir. Réécrite quand les thèmes changent : pour garder ta "
            "disposition, duplique ce fichier."}]
    shown, y, row_h = {}, 0, 0
    for k, (c, mem) in enumerate(comms):
        if k and k % PER_ROW == 0:
            y, row_h = y + row_h + 80, 0
        gx = (k % PER_ROW) * (gw + 80)
        rows = (len(mem) + 1) // 2
        gh = rows * CARD_H + (rows + 1) * GAP
        out.append({"id": _cid(f"groupe {c['label']}"), "type": "group", "x": gx, "y": y, "width": gw, "height": gh,
                    "label": f"{c['label']} ({c['size']})"})
        for j, i in enumerate(mem):
            n = nodes[i]
            parts = files[i]["path"].split("/")
            rgb = GRAPH_COLORS.get(parts[1]) if len(parts) > 2 else None
            desc = (n.get("meta") or {}).get("resume") or n.get("body", "")
            if desc.startswith(n["title"]):  # corps qui redit le titre : la suite seulement
                desc = desc[len(n["title"]):].lstrip(" .:—-\n")
            card = {"id": _cid(i), "type": "text", "x": gx + GAP + (j % 2) * (CARD_W + GAP),
                    "y": y + GAP + (j // 2) * (CARD_H + GAP), "width": CARD_W, "height": CARD_H,
                    "text": mask(f"**[[{names[i]}]]**\n_{TYPES.get(n['type'], n['type'])}_"
                                 + (f" · {short(desc, 110)}" if desc.strip() else ""))[0]}
            if rgb is not None:
                card["color"] = f"#{rgb:06X}"
            out.append(card)
            shown[i] = card["id"]
        row_h = max(row_h, gh)
    edges, seen = [], set()
    for e in brain.data.get("edges") or []:
        a, b = shown.get(e["from"]), shown.get(e["to"])
        if a and b and a != b and frozenset((a, b)) not in seen:
            seen.add(frozenset((a, b)))
            edges.append({"id": _cid(f"{a}>{b}"), "fromNode": a, "toNode": b, "toEnd": "none"})
    return {"nodes": out, "edges": edges[:300]}


def write_canvas(brain, root) -> bool:
    if not _live_ok(root):
        return False
    return _put_if_changed(Path(root) / CARD, json.dumps(canvas_data(brain), ensure_ascii=False, indent="\t") + "\n")


# ------------------------------------------------------------------------------------------ note du jour → souvenirs
_ITEM = re.compile(r"^(\s*[-*+]\s+)(\[[ xX]\]\s+)?(\S.*?)\s*$")


def days_folder(root):
    """Dossier des notes du jour (réglage d'Obsidian, sinon celui du cerveau) ; None s'il sort du coffre."""
    root = Path(root)
    try:
        folder = json.loads((root / ".obsidian" / "daily-notes.json").read_text(encoding="utf-8")).get("folder")
    except (OSError, ValueError, AttributeError):
        folder = None
    p = root / (folder.strip("/") if isinstance(folder, str) else DAYS_DIR)
    return p if path_within(p.resolve(), root.resolve()) else None


def items(text) -> list:
    """Lignes à mémoriser sous « ## À retenir » → [(n° de ligne, texte, case à cocher ?)] : ni ✓ (déjà fait) ni ⚠
    (refusé), ni case cochée, ni commentaire %% … %%."""
    out, inside, comment = [], False, False
    for i, line in enumerate(text.split("\n")):
        s = line.strip()
        if comment or "%%" in s:
            if s.count("%%") % 2:
                comment = not comment
            continue
        if re.match(r"#{1,6}\s", s):
            inside = fold(s.lstrip("#").strip()) == fold(CAPTURE_HEAD)
            continue
        m = _ITEM.match(line) if inside else None
        if not m or m.group(3).startswith(("✓", "⚠")) or (m.group(2) or "").strip().lower() == "[x]":
            continue
        out.append((i, m.group(3), bool(m.group(2))))
    return out


def kind_of(text, box=False) -> tuple:
    """« décision : … » → ("decision", "…") ; sans préfixe connu : un fait (une case à cocher : un à-faire)."""
    head, sep, rest = text.partition(":")
    t = PREFIXES.get(" ".join(fold(head).split())) if sep and len(head) <= 16 else None
    return (t, rest.strip()) if t and rest.strip() else ("todo" if box else "fact", text)


def note_day(p):
    import datetime as _dt
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", Path(p).stem)
    try:
        return _dt.date(*map(int, m.groups())) if m else _dt.date.fromtimestamp(Path(p).stat().st_mtime)
    except (ValueError, OSError):
        return _dt.date.today()


def captures(root, now=None) -> list:
    """Lignes « À retenir » en attente dans les notes du jour récentes (lecture seule, rapide : démarrage)."""
    folder = days_folder(root) if root else None
    if folder is None or not folder.is_dir():
        return []
    now = now or time.time()
    out = []
    for p in sorted(folder.glob("*.md")):
        try:
            age = now - p.stat().st_mtime
            if age < CAPTURE_QUIET or age > CAPTURE_DAYS * 86400:
                continue
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if "retenir" in text.lower():
            out += [{"path": p, "line": i, "text": t, "box": box} for i, t, box in items(text)]
    return out


def capture(root) -> list:
    """Mémorise les lignes « À retenir » des notes du jour (`brain wiki capture`, lancé en arrière-plan au démarrage),
    puis marque chacune « ✓ … → [[page]] » (ou « ⚠ … » si elle n'a pas pu l'être). → lignes du compte rendu."""
    import contextlib
    import io
    from . import cli, dates
    from .store import Brain
    lock = STATE_DIR / "capture.lock"
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if lock.exists() and time.time() - lock.stat().st_mtime > 300:
            lock.unlink()
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        return ["· capture déjà en cours (autre session)"]
    report = []
    try:
        todo = {}
        for it in captures(root):
            todo.setdefault(it["path"], []).append(it)
        for p, its in todo.items():
            day = note_day(p)
            marks = {}
            for it in its:
                kind, text = kind_of(it["text"], it["box"])
                text = dates.absolutize(text, day)  # « demain » d'une note du 20/10 : le 21/10
                # corps = la ligne seule : une phrase d'origine commune relierait entre eux tous les souvenirs capturés
                # (graphe) ; l'origine se voit dans Obsidian, rétrolien depuis la note du jour
                args = ["add", "-t", kind, "-T", short(text, 90), "-p", "none", "--source", "utilisateur", "--commun", "non",
                        "-b", text]
                due = (dates.from_title(text, day) or dates.parse(text, day)) if kind == "todo" else None
                if due:  # « le 25/10 », « demain (21/10/2026) », « dans 2 semaines » : comptés depuis le jour de la note
                    args += ["--due", due]
                buf = io.StringIO()
                try:
                    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                        cli.main(args + (["-i", "4"] if kind == "feedback" else []))
                except SystemExit:
                    pass
                except Exception as exc:
                    buf.write(f"\n✗ {exc!r}")
                msg = buf.getvalue().strip()
                m = re.search(r"(?:mémorisé|complété dans) `([^`]+)`", msg)
                marks[it["line"]] = (it["text"], m.group(1) if m else None,
                                     "secret masqué" if "🔒" in msg else short(msg.splitlines()[-1] if msg else "?", 120))
            names = _names(Brain.load())
            report += _mark(p, marks, names)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
    return report


def _mark(p, marks, names) -> list:
    """Réécrit les lignes traitées de la note (si elle n'a pas bougé entre-temps : sinon la ligne attend, et l'anti-doublon
    du cerveau la reconnaîtra au prochain passage)."""
    try:
        lines = p.read_text(encoding="utf-8").split("\n")
    except OSError:
        return []
    report, changed = [], False
    for i, (text, nid, why) in marks.items():
        m = _ITEM.match(lines[i]) if i < len(lines) else None
        if not m or m.group(3) != text:
            continue
        if nid:
            lines[i] = f"{m.group(1)}✓ {text} → " + (f"[[{names[nid]}]]" if nid in names else f"`{nid}`") + \
                       (" (secret masqué dans le souvenir : retire-le de cette note)" if why == "secret masqué" else "")
            report.append(f"✓ « {short(text, 70)} » → `{nid}`")
        else:
            lines[i] = f"{m.group(1)}⚠ {text} — non mémorisé : {why}"
            report.append(f"⚠ « {short(text, 70)} » : {why}")
        changed = True
    if changed:
        write_text(p, "\n".join(lines))
    return report


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
    merge("daily-notes.json", DAILY, _setdefaults(DAILY))
    if (root / ".obsidian" / "plugins" / "omnisearch" / "data.json").is_file():  # module installé et déjà lancé
        merge("plugins/omnisearch/data.json", {}, _add_omni)
    put(".obsidian/graph.json", json.dumps({
        "search": f"path:{ws.PAGES}", "showTags": False, "showAttachments": False, "hideUnresolved": True,
        "showOrphans": True, "showArrow": False,
        "colorGroups": [{"query": f"path:{ws.PAGES}/{folder}", "color": {"a": 1, "rgb": rgb}}
                        for folder, rgb in GRAPH_COLORS.items()]}, ensure_ascii=False, indent=2) + "\n")
    put(DASHBOARD, DASHBOARD_TEXT)
    if (root / GUIDE).is_file():
        live = _add_live((root / GUIDE).read_text(encoding="utf-8"))
        if live:
            write_text(root / GUIDE, live)
            made.append(GUIDE)
    put(GUIDE, GUIDE_TEXT)
    for name, spec in TEMPLATES.items():
        put(f"{TEMPLATES_DIR}/{name}.md", template_text(*spec))
    put(f"{TEMPLATES_DIR}/{DAY_TEMPLATE}.md", DAY_TEXT)
    days = days_folder(root)
    if days is not None and not days.exists():
        days.mkdir(parents=True)
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
