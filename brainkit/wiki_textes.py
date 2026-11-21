"""Squelette du wiki : le schéma (CLAUDE.md), le README, .gitignore et .gitattributes, le lanceur des sessions cloud
et ses hooks, et `scaffold`, qui pose ces fichiers sans rien écraser.

Découpé de wiki.py le 21/11/2026 (étape 8 du plan), sans changer le comportement : ces noms restent accessibles
depuis wiki (`wiki.SCHEMA`, `wiki.scaffold`…)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import obsidian, wikistore as ws
from .common import load_config, now_iso, owner_name, read_json, write_text
from .wiki import INDEX, LOG, README_FILE, SCHEMA_FILE, TODO_MARK, render_index


SCHEMA = """# 🧠 Wiki — schéma

Ce dépôt **est** la mémoire de Claude : un wiki Markdown que Claude écrit et tient à jour, et que {owner} lit dans
Obsidian (le « LLM Wiki » d'Andrej Karpathy). Claude ne repart jamais de zéro : chaque source, chaque question,
chaque session enrichit des pages qui restent. {Owner} choisit les sources, oriente, pose les questions ; Claude fait
tout le reste (résumés, liens, classement, mises à jour, cohérence).

Le cerveau (plugin « cerveau ») lit ces pages : il en injecte l'essentiel au démarrage de chaque session, rappelle à
chaque message les pages liées, et les cherche avec `{cmd} q "…"` (fautes, phonétique et synonymes compris).
Ci-dessous, `{cmd}` = `{full}` (Bash comme PowerShell).

## Les trois couches
1. **`raw/`** — les sources brutes : articles (Obsidian Web Clipper), PDF, transcriptions de vidéos et de podcasts,
   notes, conversations, données ; images dans `raw/assets/`. **Immuables** : on les lit, on ne les modifie jamais.
2. **`wiki/`** — les pages, un dossier par type (tableau plus bas). `archive/` garde les pages remplacées ou
   terminées : consultables, hors index.
3. **`CLAUDE.md`** (ce fichier) — le schéma. Il évolue avec l'usage : quand une convention gêne, proposer de la changer.

`index.md` : catalogue de toutes les pages, **régénéré par le cerveau** sur chaque PC (ne pas l'éditer ; pas dans git,
`{cmd} wiki index` le refait). `log.md` : journal
chronologique du wiki, on ajoute **en bas** des entrées `## [AAAA-MM-JJ] opération | titre`. `journal/<PC>/AAAA-MM.md` :
l'historique des sessions et des observations datées, mois par mois, un dossier par PC (`journal/cloud/` pour les
sessions cloud, `journal/ancien/` pour les mois d'avant la 8.31.0) ; généré par le cerveau, à lire, pas à éditer.
`{cmd} q` trouve aussi les sessions des autres PC.

## Types de pages
| Dossier | `type` | Pour |
|---|---|---|
| Sources | source | une source ingérée : résumé, points clés, citations exactes, ce qu'elle apporte ou contredit |
| Entités | entite | personne, entreprise, produit, outil, lieu, œuvre, personnage |
| Concepts | concept | idée, méthode, technique, thème, notion |
| Sujets | sujet | synthèse vivante d'un sujet, vue d'ensemble d'un domaine, thèse qui évolue |
| Analyses | analyse | réponse rangée : comparaison, analyse, chronologie, question tranchée (datée) |
| Profil | profil | qui est l'utilisateur |
| Règles | regle | préférence, consigne, correction (valable dans toutes les sessions) |
| Projets | projet | un projet, un dossier de travail |
| Décisions | decision | un choix et son pourquoi |
| Faits | fait | l'état d'un travail en cours, un fait daté |
| Apprentissages | apprentissage | piège résolu, solution qui marche, astuce |
| Références | reference | lien, documentation, ressource |
| À faire | afaire | une suite à faire (`echeance`) |

## Format d'une page
```markdown
---
type: concept
resume: "Une phrase qui dit l'essentiel de la page (index et rappel s'en servent)."
tags: ["…"]
domaine: ["business"]        # business, recherche, perso, lecture…
sources: ["[[Titre d'une page Sources]]"]
importance: 3                # 1 à 5
---
# Titre de la page

Texte en Markdown. Lien vers une autre page : [[Titre de la page]] (= nom du fichier, sans .md).
```
- Titre court et unique : c'est aussi le nom du fichier. Une page = un sujet.
- Le cerveau ajoute seul `id`, `origine`, `cree`, `maj` : les laisser tels quels.
- Relations typées (listes de liens, en propriétés) : `lie_a`, `fait_partie_de`, `depend_de`, `utilise`, `corrige`,
  `remplace`, `contredit`, `a_propos_de`. `projet: "[[Nom du projet]]"` rattache une page à un projet.
- Un fichier ou un dossier dont le nom commence par `_` est ignoré (modèles).

## Méthodes
### Ingérer une source
1. `{cmd} wiki add <fichier | url | ->` (texte par l'entrée standard, avec `-T "Titre"`) : la source est rangée dans
   `raw/`, sa page Sources est créée, et le plan s'affiche (pages sans doute concernées, entités repérées).
   Source déjà déposée dans `raw/` (Web Clipper, glisser-déposer) : `{cmd} wiki pending` puis `{cmd} wiki add raw/…`.
   Vidéo YouTube : récupérer la transcription, puis `{cmd} wiki add - -T "Titre" --url <lien> --format video`.
2. Lire toute la source (PDF : par pages ; images : les regarder une par une après le texte).
3. Sauf ingestion en lot demandée, dire à l'utilisateur les 3 à 5 points clés et ce qui est nouveau, avant d'écrire.
4. Remplir la page de la source (remplacer « {todo} ») : résumé, points clés, citations exactes entre guillemets,
   ce qui confirme ou contredit le wiki, et `resume:`.
5. Mettre à jour les pages concernées — entités, concepts, sujets : intégrer (pas empiler), ajouter la source dans
   `sources:`, revoir `resume:`, créer les pages importantes qui manquent. Toucher 10 à 15 pages est normal.
6. Contradiction : la noter dans les deux pages par un encadré `> [!contradiction]` (qui dit quoi, quelle source,
   quelle date) ; ne jamais écraser une affirmation sans trace.
7. `{cmd} wiki log ingest "Titre de la source" "pages touchées : [[A]], [[B]]…"` (régénère l'index).

### Répondre à une question
1. `{cmd} q "…"` (tout le wiki : pages, souvenirs, sessions passées), ou `index.md` ; puis lire les pages.
2. Répondre en citant les pages (`[[Page]]`) et les sources ; dire ce qui manque.
3. Une bonne réponse (comparaison, analyse, lien découvert) ne doit pas se perdre dans la conversation : la ranger dans
   Analyses (`{cmd} add -t analyse -T "…" -b -` ou écrire la page), puis `{cmd} wiki log query "La question"`.

### Rechercher un sujet sur le web
Skill `/cerveau:recherche` (« fais un dossier sur… », « recherche à fond… ») : 3 tours de 5 sources au plus, sources
primaires d'abord, position contraire cherchée ; chaque affirmation est **établie** (deux sources indépendantes si
santé, droit, argent), **provisoire**, **contestée** ou **non étayée**. Le dossier va dans Analyses avec ses sources ;
la mise à jour des autres pages est proposée à part, après accord.

### Mémoriser en travaillant
`{cmd} add -t <type> -T "titre" -b "fait + pourquoi + comment l'appliquer"` crée une page (anti-doublon,
remplacements, secrets masqués) ; `{cmd} edit <id|titre>` la corrige, `{cmd} rm` l'archive. Écrire une page à la main
en suivant le format marche aussi : le cerveau la lit au passage suivant.

### Entretenir
`{cmd} wiki lint` : pages à créer (liens vers rien), pages orphelines, pages sans `resume`, sections vides,
propriétés invalides (type, importance, dates), sources pas encore
ingérées ou modifiées depuis, pages peut-être dépassées par une source plus récente, doublons, contradictions
signalées, souvenirs à verser dans une page de savoir. Corriger, compléter, proposer des questions à creuser et des
sources à chercher, puis `{cmd} wiki log lint "…"`. Le rêve quotidien du cerveau en reprend l'essentiel.

## Règles
- Écrire en français, net et précis ; dater les faits (« le 18/10/2026 ») ; un chiffre vient avec sa source.
- Ne jamais modifier `raw/` ni `index.md` ; ne jamais effacer `log.md` (on ajoute en bas).
- Jamais de secret (clé, jeton, mot de passe) ni de donnée sensible sur un tiers : le dépôt est privé, mais quand même.
- Préférer enrichir une page existante plutôt qu'en créer une voisine ; garder `resume:` à jour.
- Synchronisation : sur le PC, le cerveau fait commit, pull et push tout seul en début et en fin de session ; dans une
  session cloud, faire le commit et pousser sur la branche de la session. Une page modifiée sur deux PC garde la version
  de GitHub, et celle de l'autre PC est posée à côté : « Titre (conflit PC 2026-11-21 14h05).md ». Le cerveau ne la lit
  pas comme une page : reprendre ce qui compte dans la page, puis supprimer la copie.
"""


README = """# 🧠 Wiki de {owner}

La mémoire de Claude, sous forme de wiki : Claude écrit et entretient les pages, tu les lis (et tu y déposes des
sources). Le schéma qui guide Claude est dans [CLAUDE.md](CLAUDE.md).

- **`raw/`** : tes sources (articles, PDF, transcriptions, notes). Claude les lit, ne les modifie jamais.
- **`wiki/`** : les pages tenues par Claude (souvenirs, sources résumées, entités, concepts, sujets, analyses).
- **`index.md`** : le catalogue (refait sur chaque PC, hors de git) · **[log.md](log.md)** : le journal du wiki ·
  **`journal/`** : l'historique
  des sessions et des observations, mois par mois, un dossier par PC.

## Sur ton PC
1. Clone ce dépôt, puis ouvre le dossier dans Obsidian (« Ouvrir un dossier comme coffre »). Signet « Cerveau » :
   tableau de bord (À faire, récents, projets…), mode d'emploi, index ; modèles de pages avec Alt+T.
2. Dans Claude Code, demande « installe le cerveau dans ce wiki : <dossier du clone> », ou lance
   `{cmd} wiki init "<dossier du clone>"` — le cerveau migre tes souvenirs en pages et travaille désormais ici
   (copie de l'ancien cerveau gardée). Commit, pull et push se font tout seuls en début et en fin de session.
3. Dépose des sources dans `raw/` (Obsidian Web Clipper : dossier `raw`), puis demande à Claude « ingère les nouvelles
   sources ». Une note que tu crées dans Obsidian arrive aussi dans `raw/` : c'est une source.

## Dans une session cloud (claude.ai/code)
Ouvre la session sur ce dépôt (seul, sans autre dépôt) : `CLAUDE.md` est lu tout seul, et les hooks de
`.claude/settings.json` lancent le cerveau (rappel automatique, recherche, entretien) — son code est récupéré au
démarrage depuis le dépôt public du plugin. Les changements faits depuis le cloud arrivent sur une branche, en pull
request : fusionne-la pour que ton PC les récupère.

Images : Obsidian les range dans `raw/assets/` (Réglages → Fichiers et liens). Le dépôt doit rester **privé**.
"""


# index.md : régénéré sur chaque PC à partir de ses pages ; suivi dans git, il entrait en conflit dès que deux PC
# changeaient quelque chose, et toute synchronisation restait bloquée (avant la 8.30.0)
GITIGNORE = """*.tmp
/index.md
.obsidian/workspace*.json
.obsidian/cache
.obsidian/plugins/*/data.json
.obsidian/plugins/*/main.js
.obsidian/plugins/*/styles.css
.trash/
.DS_Store
Thumbs.db
desktop.ini
"""


# log.md (on ajoute en bas) et .gitignore : les lignes des deux PC sont gardées, sans conflit
UNION = ("log.md merge=union", ".gitignore merge=union")


GITATTRIBUTES = """* text=auto eol=lf
log.md merge=union
.gitignore merge=union
*.pdf binary
*.png binary
*.jpg binary
*.jpeg binary
*.gif binary
*.webp binary
*.mp3 binary
*.mp4 binary
*.zip binary
*.docx binary
*.xlsx binary
"""


# Session cloud (claude.ai/code) ouverte sur le wiki : un plugin déclaré par le dépôt n'y est pas installé, mais les
# hooks du .claude/settings.json du dépôt s'y exécutent. Ils appellent ce lanceur, qui récupère une fois le code du
# cerveau (dépôt public du plugin) et lui passe l'événement ; sur le PC il sort aussitôt (le cerveau installé suffit).
CLOUD_EVENTS = (("SessionStart", "session-start", 90), ("UserPromptSubmit", "prompt", 10), ("Stop", "stop", 15),
                ("PreCompact", "pre-compact", 20), ("PostCompact", "post-compact", 15), ("SessionEnd", "session-end", 20))


CLOUD_LAUNCHER = '''#!/usr/bin/env python3
"""Cerveau dans une session cloud (claude.ai/code) ouverte sur ce wiki.

Un plugin déclaré par le dépôt n'est pas installé dans une session cloud, mais les hooks de .claude/settings.json s'y
exécutent : ce lanceur récupère une fois le code du cerveau (dépôt public du plugin), puis lui passe chaque événement.
Sur le PC, il ne fait rien : le cerveau installé y travaille déjà. Il ne bloque jamais une session."""
import os
import subprocess
import sys

REPO = "{repo}"


def main():
    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        return 0
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    code = os.environ.get("CERVEAU_CODE") or os.path.join(os.path.expanduser("~"), ".cache", "cerveau-claude")
    brain = os.path.join(code, "brain.py")
    if not os.path.isfile(brain):
        if event != "session-start":
            return 0  # jamais de téléchargement pendant un message : seulement au démarrage
        try:
            subprocess.run(["git", "clone", "-q", "--depth", "1", os.environ.get("CERVEAU_REPO") or REPO, code],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=80)
        except Exception:
            return 0
        if not os.path.isfile(brain):
            return 0
    os.environ["CERVEAU_CLOUD"] = "1"
    args = [sys.executable, "-I", "-S", brain, "hook", event]
    if os.name == "nt":  # os.execv ne met pas de guillemets sous Windows : « Program Files » coupé en deux
        return subprocess.run(args).returncode
    os.execv(sys.executable, args)


if __name__ == "__main__":
    sys.exit(main())
'''


def cloud_settings() -> dict:
    """Hooks du dépôt du wiki pour les sessions cloud (sans effet sur le PC : le lanceur sort aussitôt)."""
    hook = 'python -I -S "$CLAUDE_PROJECT_DIR"/.claude/cerveau.py {arg}'
    return {"hooks": {event: [{"hooks": [{"type": "command", "command": hook.format(arg=arg), "timeout": timeout}]}]
                      for event, arg, timeout in CLOUD_EVENTS}}


# ------------------------------------------------------------------------------------------ squelette
def _owner() -> str:
    return owner_name() or "l'utilisateur"


def _plugin_repo() -> str:
    repo = (load_config().get("publish") or {}).get("repo")
    if not repo:
        from .common import CODE_DIR
        meta = read_json(CODE_DIR / ".claude-plugin" / "plugin.json", {}) or {}
        m = re.search(r"github\.com/([^/\s]+/[^/\s]+?)(?:\.git)?/?$", str(meta.get("repository") or ""))
        repo = m.group(1) if m else "destingood/cerveau-claude"
    return repo


def schema_text() -> str:
    owner = _owner()
    return SCHEMA.format(owner=owner, Owner=owner[:1].upper() + owner[1:], cmd="brain",
                         full='python "$HOME/.claude/brain/brain.py"', todo=TODO_MARK)


def scaffold(root) -> list:
    """Squelette du wiki (idempotent : n'écrase jamais un fichier existant). → fichiers créés."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    made = []

    def put(rel, text):
        p = root / rel
        if not p.exists():
            write_text(p, text)
            made.append(rel)

    put(ws.MARKER, json.dumps({"version": 1, "created": now_iso()[:10],
                               "note": "dossier du wiki du cerveau : ne pas supprimer"}, ensure_ascii=False) + "\n")
    put(SCHEMA_FILE, schema_text())
    put(README_FILE, README.format(owner=_owner(), cmd='python "$HOME/.claude/brain/brain.py"'))
    put(LOG, "# 🗒️ Journal du wiki\n\n_Chronologique : on ajoute en bas, jamais on n'efface. Entrées "
             "`## [AAAA-MM-JJ] opération | titre` (ingest, query, lint, session, migration, note) — les 5 dernières : "
             "`grep \"^## \\[\" log.md | tail -5`._\n")
    put(".gitignore", GITIGNORE)
    put(".gitattributes", GITATTRIBUTES)
    put(".claude/settings.json", json.dumps(cloud_settings(), ensure_ascii=False, indent=2) + "\n")
    put(".claude/cerveau.py", CLOUD_LAUNCHER.format(repo=f"https://github.com/{_plugin_repo()}.git"))
    put(f"{ws.RAW}/assets/.gitkeep", "")
    for folder in ws.FOLDERS.values():
        put(f"{ws.PAGES}/{folder}/.gitkeep", "")
    if not (root / INDEX).exists():
        write_text(root / INDEX, render_index({"nodes": {}, "edges": []}, root))
        made.append(INDEX)
    made += obsidian.setup(root, force=True)  # coffre Obsidian : tableau de bord, modèles, signets, mode d'emploi
    return made
