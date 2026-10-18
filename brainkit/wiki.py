"""Le wiki du cerveau, au quotidien (le « LLM Wiki » de Karpathy) : trois couches dans un dossier — un dépôt git
ouvert comme coffre Obsidian.

- `raw/` : les sources brutes (articles, PDF, transcriptions, notes, données, images dans raw/assets/), immuables ;
- `wiki/` : les pages, écrites et tenues à jour par Claude (souvenirs et pages de savoir), `archive/` pour l'ancien ;
- `CLAUDE.md` : le schéma (conventions, méthodes d'ingestion, de réponse, d'entretien), qui évolue avec l'usage.

Ce module : création du squelette et migration du cerveau classique (`init`), dépôt d'une source avec son plan
d'ingestion (`add_source`), sources en attente, catalogue `index.md` (régénéré), journal `log.md` (on ajoute en bas),
contrôle de santé (`lint`), état, synchronisation git (commit, pull --rebase, push ; automatique en début et fin de
session sur le PC, jamais dans une session cloud, qui pousse sur sa propre branche)."""
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
from .common import (BRAIN_DIR, STATE_DIR, FileLock, fmt_date, fold, load_config, log, now_iso, read_json, set_config,
                     short, tokenize, write_json, write_text)

INDEX, LOG, SCHEMA_FILE, README_FILE = "index.md", "log.md", "CLAUDE.md", "README.md"
TODO_MARK = "⏳ à remplir"
KNOWLEDGE = ("source", "entity", "concept", "topic", "analysis")
INDEX_ORDER = ("topic", "concept", "entity", "source", "analysis", "project", "decision", "fact", "learning",
               "reference", "feedback", "user", "todo")
TEXT_EXT = (".md", ".markdown", ".txt", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml", ".org", ".rst")
HTML_EXT = (".html", ".htm", ".xhtml")
SUB_EXT = (".vtt", ".srt")
FORMATS = ("article", "pdf", "video", "podcast", "livre", "note", "conversation", "donnees", "image", "document")
LOG_HEAD = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\] ([^|\n]+?) \| (.*)$", re.M)
GIT_LOCK = STATE_DIR / "wiki-git.lock"
LOG_LOCK = STATE_DIR / "wiki-log.lock"
SYNC_STATE = STATE_DIR / "wiki-sync.json"
YOUTUBE = re.compile(r"^https?://(?:www\.|m\.)?(?:youtube\.com|youtu\.be)/", re.I)

SCHEMA = """# 🧠 Wiki — schéma

Ce dépôt **est** la mémoire de Claude : un wiki Markdown que Claude écrit et tient à jour, et que {owner} lit dans
Obsidian (le « LLM Wiki » d'Andrej Karpathy). Claude ne repart jamais de zéro : chaque source, chaque question,
chaque session enrichit des pages qui restent. {owner} choisit les sources, oriente, pose les questions ; Claude fait
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

`index.md` : catalogue de toutes les pages, **régénéré par le cerveau** (ne pas l'éditer). `log.md` : journal
chronologique, on ajoute **en bas** des entrées `## [AAAA-MM-JJ] opération | titre`.

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

### Mémoriser en travaillant
`{cmd} add -t <type> -T "titre" -b "fait + pourquoi + comment l'appliquer"` crée une page (anti-doublon,
remplacements, secrets masqués) ; `{cmd} edit <id|titre>` la corrige, `{cmd} rm` l'archive. Écrire une page à la main
en suivant le format marche aussi : le cerveau la lit au passage suivant.

### Entretenir
`{cmd} wiki lint` : pages à créer (liens vers rien), pages orphelines, pages sans `resume`, sources pas encore
ingérées ou modifiées depuis, pages peut-être dépassées par une source plus récente, doublons, contradictions
signalées, souvenirs à verser dans une page de savoir. Corriger, compléter, proposer des questions à creuser et des
sources à chercher, puis `{cmd} wiki log lint "…"`. Le rêve quotidien du cerveau en reprend l'essentiel.

## Règles
- Écrire en français, net et précis ; dater les faits (« le 18/10/2026 ») ; un chiffre vient avec sa source.
- Ne jamais modifier `raw/` ni `index.md` ; ne jamais effacer `log.md` (on ajoute en bas).
- Jamais de secret (clé, jeton, mot de passe) ni de donnée sensible sur un tiers : le dépôt est privé, mais quand même.
- Préférer enrichir une page existante plutôt qu'en créer une voisine ; garder `resume:` à jour.
- Synchronisation : sur le PC, le cerveau fait commit, pull et push tout seul en début et en fin de session ; dans une
  session cloud, faire le commit et pousser sur la branche de la session.
"""

README = """# 🧠 Wiki de {owner}

La mémoire de Claude, sous forme de wiki : Claude écrit et entretient les pages, tu les lis (et tu y déposes des
sources). Le schéma qui guide Claude est dans [CLAUDE.md](CLAUDE.md).

- **`raw/`** : tes sources (articles, PDF, transcriptions, notes). Claude les lit, ne les modifie jamais.
- **`wiki/`** : les pages tenues par Claude (souvenirs, sources résumées, entités, concepts, sujets, analyses).
- **[index.md](index.md)** : le catalogue · **[log.md](log.md)** : le journal.

## Sur ton PC
1. Clone ce dépôt, puis ouvre le dossier dans Obsidian (« Ouvrir un dossier comme coffre »).
2. Dans Claude Code, demande « installe le cerveau dans ce wiki : <dossier du clone> », ou lance
   `{cmd} wiki init "<dossier du clone>"` — le cerveau migre tes souvenirs en pages et travaille désormais ici
   (copie de l'ancien cerveau gardée). Commit, pull et push se font tout seuls en début et en fin de session.
3. Dépose des sources dans `raw/` (Obsidian Web Clipper : dossier `raw`), puis demande à Claude « ingère les nouvelles
   sources ». Une note que tu crées dans Obsidian arrive aussi dans `raw/` : c'est une source.

## Dans une session cloud (claude.ai/code)
Ouvre la session sur ce dépôt : `CLAUDE.md` est lu tout seul, et `.claude/settings.json` déclare le plugin « cerveau »
(rappel automatique, recherche, entretien). Les changements faits depuis le cloud arrivent sur une branche, en pull
request : fusionne-la pour que ton PC les récupère.

Images : Obsidian les range dans `raw/assets/` (Réglages → Fichiers et liens). Le dépôt doit rester **privé**.
"""

GITIGNORE = """*.tmp
.obsidian/workspace*.json
.obsidian/cache
.obsidian/plugins/*/data.json
.trash/
.DS_Store
Thumbs.db
desktop.ini
"""
GITATTRIBUTES = """* text=auto eol=lf
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
OBSIDIAN_APP = {"attachmentFolderPath": "raw/assets", "newFileLocation": "folder", "newFileFolderPath": "raw",
                "alwaysUpdateLinks": True, "newLinkFormat": "shortest", "useMarkdownLinks": False,
                "userIgnoreFilters": ["archive/"], "showUnsupportedFiles": True}


# ------------------------------------------------------------------------------------------ squelette
def _owner() -> str:
    return (load_config().get("publish") or {}).get("owner") or "Lucas"


def _plugin_repo() -> str:
    repo = (load_config().get("publish") or {}).get("repo")
    if not repo:
        from .common import CODE_DIR
        meta = read_json(CODE_DIR / ".claude-plugin" / "plugin.json", {}) or {}
        m = re.search(r"github\.com/([^/\s]+/[^/\s]+?)(?:\.git)?/?$", str(meta.get("repository") or ""))
        repo = m.group(1) if m else "destingood/cerveau-claude"
    return repo


def schema_text() -> str:
    return SCHEMA.format(owner=_owner(), cmd="brain", full='python "$HOME/.claude/brain/brain.py"', todo=TODO_MARK)


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
    put(".obsidian/app.json", json.dumps(OBSIDIAN_APP, ensure_ascii=False, indent=2) + "\n")
    put(".claude/settings.json", json.dumps({
        "extraKnownMarketplaces": {"cerveau": {"source": {"source": "git",
                                                          "url": f"https://github.com/{_plugin_repo()}.git"}}},
        "enabledPlugins": {"cerveau@cerveau": True}}, ensure_ascii=False, indent=2) + "\n")
    put(f"{ws.RAW}/assets/.gitkeep", "")
    for folder in ws.FOLDERS.values():
        put(f"{ws.PAGES}/{folder}/.gitkeep", "")
    if not (root / INDEX).exists():
        write_text(root / INDEX, render_index({"nodes": {}, "edges": []}, root))
        made.append(INDEX)
    return made


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


def _upstream(root):
    """→ arguments de `git pull` adaptés : la branche suivie, sinon la branche du même nom sur origin si elle existe,
    sinon None (dépôt distant encore vide : rien à récupérer)."""
    if git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", timeout=10)[0] == 0:
        return ["pull", "--rebase", "--autostash"]
    code, branch = git(root, "rev-parse", "--abbrev-ref", "HEAD", timeout=10)
    if code or not branch or branch == "HEAD":
        return None
    code, heads = git(root, "ls-remote", "--heads", "origin", branch, timeout=60)
    return ["pull", "--rebase", "--autostash", "origin", branch] if code == 0 and heads.strip() else None


def commit(root, message=None) -> str:
    """Commit de tout ce qui a changé. → résumé (vide s'il n'y avait rien)."""
    rows = _changes(root)
    if not rows:
        return ""
    pages = [p for _, p in rows if p.startswith((ws.PAGES + "/", ws.ARCHIVE + "/")) and p.endswith(".md")]
    raws = [p for _, p in rows if p.startswith(ws.RAW + "/")]
    if not message:
        bits = []
        if pages:
            bits.append(f"{len(pages)} page(s)")
        if raws:
            bits.append(f"{len(raws)} source(s)")
        others = len(rows) - len(pages) - len(raws)
        if others:
            bits.append(f"{others} autre(s)")
        names = ", ".join(ws.stem(p) for p in pages[:6]) + (" …" if len(pages) > 6 else "")
        message = "cerveau : " + ", ".join(bits) + (f" — {names}" if names else "")
    git(root, "add", "-A", timeout=60)
    code, out = git(root, "commit", "-q", "-m", message, timeout=60)
    if code:
        return f"✗ commit : {short(out, 200)}"
    return message


def sync(root=None, push=True, pull=True, auto=False) -> list:
    """Commit, puis pull --rebase et push si le dépôt a une adresse GitHub. Un conflit annule le rebase (rien ne reste
    à moitié fait) et se signale au démarrage suivant. → lignes de compte rendu."""
    root = Path(root or ws.root() or "")
    if not str(root) or not (root / ws.MARKER).is_file():
        return ["✗ pas de wiki ici : `brain wiki init <dossier>`"]
    if not is_repo(root):
        return ["· pas de dépôt git dans le wiki : `git init` (ou clone ton dépôt GitHub) pour l'historique et la "
                "synchronisation"]
    if auto and os.environ.get("CLAUDE_CODE_REMOTE"):
        return ["· session cloud : pas de synchronisation automatique (commit et push sur la branche de la session)"]
    out = []
    try:
        with FileLock(GIT_LOCK, timeout=2 if auto else 20, stale=600):
            msg = commit(root)
            if msg:
                out.append(("✗ " if msg.startswith("✗") else "✓ commit : ") + msg.lstrip("✗ "))
            url = remote(root)
            st = read_json(SYNC_STATE, {}) or {}
            how = _upstream(root) if url and pull else None
            if how:
                code, txt = git(root, *how, timeout=120)
                if code:
                    git(root, "rebase", "--abort", timeout=30)
                    st["conflict"] = now_iso()
                    out.append(f"✗ pull : {short(txt, 240)} — rien n'est perdu (rebase annulé) ; à régler à la main dans "
                               f"{root} (`git status`)")
                    push = False
                else:
                    st.pop("conflict", None)
                    out.append("✓ pull" + ("" if "up to date" in txt.lower() or "à jour" in txt.lower() else
                                          f" : {short(txt.splitlines()[-1] if txt else '', 120)}"))
            if url and push:
                code, txt = git(root, "push", "-u", "origin", "HEAD", timeout=120)
                out.append("✓ push" if code == 0 else f"✗ push : {short(txt, 240)}")
            elif not url:
                out.append("· pas d'adresse GitHub (origin) : historique local seulement — `git remote add origin <url>`")
            st["synced"] = now_iso()
            write_json(SYNC_STATE, st)
    except TimeoutError:
        out.append("· synchronisation déjà en cours ailleurs")
    if auto:
        log("wiki sync : " + " | ".join(out))
    return out


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
    nodes = [n for n in (data.get("nodes") or {}).values() if n.get("status", "active") == "active"]
    files = (data.get("wiki") or {}).get("files") or {}
    names = {nid: ws.stem(v["path"]) for nid, v in files.items() if v.get("path")}
    raw = raw_files(root)
    pend = len(pending(data, root, raw))
    archived = sum(1 for n in (data.get("nodes") or {}).values() if n.get("status", "active") != "active")
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
    """Sources brutes (chemins relatifs POSIX), hors raw/assets/ et fichiers cachés."""
    base = Path(root) / ws.RAW
    out = []
    if not base.is_dir():
        return out
    for p in base.rglob("*"):
        rel = p.relative_to(root).as_posix()
        parts = rel.split("/")
        if not p.is_file() or any(x[:1] in "._" for x in parts[1:]) or (len(parts) > 2 and parts[1] == "assets"):
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
    srcs = [n for n in (data.get("nodes") or {}).values() if n["type"] == "source"]
    known = {str((n.get("meta") or {}).get("brut") or "").replace("\\", "/").lower() for n in srcs}
    out = [{"raw": r, "page": None} for r in raw if r.lower() not in known]
    for n in srcs:
        if n.get("status", "active") == "active" and TODO_MARK in (n.get("body") or ""):
            out.append({"raw": (n.get("meta") or {}).get("brut"), "page": n})
    return out


def _vtt_text(text) -> str:
    keep, last = [], None
    for line in text.replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if not s or s == "WEBVTT" or s.isdigit() or "-->" in s or s.startswith(("NOTE", "Kind:", "Language:")):
            continue
        s = re.sub(r"<[^>]+>", "", s)
        if s != last:
            keep.append(s)
            last = s
    return "\n".join(keep)


def _docx_text(path) -> str:
    import zipfile
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").strip()


def extract_text(path) -> str:
    """Texte d'une source pour en préparer l'ingestion (vide si Claude doit la lire lui-même : PDF, images…)."""
    p = Path(path)
    ext = p.suffix.lower()
    try:
        if ext in TEXT_EXT:
            return p.read_text(encoding="utf-8", errors="replace")
        if ext in HTML_EXT:
            return html_to_md(p.read_text(encoding="utf-8", errors="replace"))[1]
        if ext in SUB_EXT:
            return _vtt_text(p.read_text(encoding="utf-8", errors="replace"))
        if ext == ".docx":
            return _docx_text(p)
    except Exception as exc:
        log(f"wiki : texte de {p.name} : {exc!r}")
    return ""


def html_to_md(html, base_url="") -> tuple:
    """Page HTML → (titre, Markdown) : titres, paragraphes, listes, liens, citations, code ; menus, scripts et pieds
    de page écartés ; l'article principal (<article>, <main>) gardé s'il existe."""
    from html.parser import HTMLParser
    from urllib.parse import urljoin

    class P(HTMLParser):
        SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form", "button", "iframe",
                "template", "select", "canvas"}

        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.bufs = {"all": [], "article": [], "main": []}
            self.depth = {"article": 0, "main": 0}
            self.skip = 0
            self.pre = 0
            self.href = []
            self.title = ""
            self.in_title = False
            self.og = ""

        def emit(self, s):
            for k, buf in self.bufs.items():
                if k == "all" or self.depth.get(k):
                    buf.append(s)

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "meta" and a.get("property") == "og:title":
                self.og = a.get("content") or ""
            if tag == "title":
                self.in_title = True
            if tag in self.depth:
                self.depth[tag] += 1
            if tag in self.SKIP:
                self.skip += 1
                return
            if self.skip:
                return
            if re.fullmatch(r"h[1-6]", tag):
                self.emit("\n\n" + "#" * int(tag[1]) + " ")
            elif tag in ("p", "div", "section", "table", "figure", "ul", "ol", "dl"):
                self.emit("\n\n")
            elif tag in ("br", "tr"):
                self.emit("\n")
            elif tag == "li":
                self.emit("\n- ")
            elif tag == "blockquote":
                self.emit("\n\n> ")
            elif tag == "pre":
                self.pre += 1
                self.emit("\n\n```\n")
            elif tag == "code" and not self.pre:
                self.emit("`")
            elif tag in ("strong", "b"):
                self.emit("**")
            elif tag in ("em", "i"):
                self.emit("_")
            elif tag == "a":
                self.href.append(a.get("href") or "")
                self.emit("[")
            elif tag == "img" and (a.get("src") or "").strip():
                self.emit(f"![{a.get('alt') or ''}]({urljoin(base_url, a['src'])})")
            elif tag in ("td", "th"):
                self.emit(" | ")

        def handle_endtag(self, tag):
            if tag == "title":
                self.in_title = False
            if tag in self.depth and self.depth[tag]:
                self.depth[tag] -= 1
            if tag in self.SKIP:
                self.skip = max(0, self.skip - 1)
                return
            if self.skip:
                return
            if tag == "pre":
                self.pre = max(0, self.pre - 1)
                self.emit("\n```\n\n")
            elif tag == "code" and not self.pre:
                self.emit("`")
            elif tag in ("strong", "b"):
                self.emit("**")
            elif tag in ("em", "i"):
                self.emit("_")
            elif tag == "a":
                href = self.href.pop() if self.href else ""
                self.emit(f"]({urljoin(base_url, href)})" if href and not href.startswith(("#", "javascript:")) else "]")
            elif tag in ("p", "blockquote", "ul", "ol", "table") or re.fullmatch(r"h[1-6]", tag):
                self.emit("\n\n")

        def handle_data(self, data):
            if self.in_title:
                self.title += data
            if self.skip:
                return
            self.emit(data if self.pre else re.sub(r"\s+", " ", data))

    p = P()
    try:
        p.feed(html)
        p.close()
    except Exception as exc:
        log(f"wiki : html : {exc!r}")
    pick = next((k for k in ("article", "main") if len("".join(p.bufs[k]).strip()) > 400), "all")
    text = "".join(p.bufs[pick])
    text = re.sub(r"\[\s*\]\([^)]*\)", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return " ".join((p.og or p.title or "").split()), text


def fetch(url) -> tuple:
    """URL → (titre, contenu en octets, extension). HTML converti en Markdown ; PDF et autres gardés tels quels."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (cerveau-wiki)",
                                               "Accept": "text/html,application/xhtml+xml,application/pdf,*/*"})
    with urllib.request.urlopen(req, timeout=30) as r:
        ctype = (r.headers.get("Content-Type") or "").lower()
        raw = r.read(20 * 1024 * 1024)
        final = r.geturl()
    if "html" in ctype or raw[:500].lstrip().lower().startswith((b"<!doctype html", b"<html")):
        m = re.search(r"charset=([\w-]+)", ctype) or re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:4000], re.I)
        enc = (m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)) if m else "utf-8"
        try:
            html = raw.decode(enc, "replace")
        except LookupError:
            html = raw.decode("utf-8", "replace")
        title, md = html_to_md(html, final)
        return title, md.encode("utf-8"), ".md"
    ext = ".pdf" if "pdf" in ctype or final.lower().endswith(".pdf") else (Path(final.split("?")[0]).suffix or ".bin")
    return Path(final.split("?")[0]).stem.replace("-", " ").replace("_", " "), raw, ext


def _guess_format(ext, url="") -> str:
    if YOUTUBE.match(url or ""):
        return "video"
    return {".pdf": "pdf", ".vtt": "video", ".srt": "video", ".csv": "donnees", ".tsv": "donnees", ".json": "donnees",
            ".xlsx": "donnees", ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".gif": "image",
            ".docx": "document", ".mp3": "podcast", ".m4a": "podcast"}.get(ext, "article" if url else "note")


def _frontmatter_title(text) -> tuple:
    """Titre, adresse, auteur d'une source Markdown (Web Clipper : title, source, author)."""
    page = ws.parse_page(text)
    fm = page["fm"]
    title = page["t"] or str(fm.get("title") or fm.get("titre") or "")
    url = str(fm.get("source") or fm.get("url") or "")
    author = fm.get("author") or fm.get("auteur") or ""
    if isinstance(author, list):
        author = ", ".join(str(a).strip("[]") for a in author)
    return title.strip(), url.strip(), str(author).strip(), str(fm.get("published") or fm.get("date") or "")[:10]


def _unique_raw(root, name) -> Path:
    base = Path(root) / ws.RAW
    base.mkdir(parents=True, exist_ok=True)
    stem_, ext = os.path.splitext(name)
    p, i = base / name, 2
    while p.exists():
        p = base / f"{stem_} ({i}){ext}"
        i += 1
    return p


def related(brain, text, exclude=(), k=8) -> list:
    """Pages du wiki les plus proches d'un texte (ses termes les plus distinctifs, cherchés dans tout le cerveau)."""
    from collections import Counter
    from . import search
    idx = search.memory_index(brain)
    # seuls les mots que le wiki connaît peuvent mener à une page : les plus distinctifs d'entre eux
    tf = Counter(t for t in tokenize(text) if len(t) >= 4 and not t.isdigit() and idx.df.get(t))
    if not tf:
        return []
    terms = sorted(tf, key=lambda t: -(1 + tf[t] ** 0.5) * idx.idf(t))[:14]
    out = []
    for r in idx.search(" ".join(terms), limit=k * 3):
        n = brain.nodes.get(r["key"])
        if not n or n["id"] in exclude or n.get("status", "active") != "active" or n["type"] == "project":
            continue
        out.append((round(r["score"], 1), n))
        if len(out) >= k:
            break
    return out


def candidates(brain, text, k=10) -> list:
    """Noms propres et sigles cités au moins deux fois dans la source, sans page à eux dans le wiki."""
    from collections import Counter
    from .reconcile import entities
    found = entities(text)
    if not found:
        return []
    low = fold(text)
    have = {fold(n["title"]) for n in brain.nodes.values()} | set(brain.stem_map())
    counts = Counter({e: low.count(e) for e in found if len(e) >= 3})
    return [(e, c) for e, c in counts.most_common(40) if c >= 2 and e not in have][:k]


def add_source(src, title=None, fmt=None, url=None, author=None, text=None) -> dict:
    """Range une source dans raw/ (copie d'un fichier, page web téléchargée, texte reçu) et crée sa page Sources à
    remplir. Une source déjà présente (même contenu) n'est pas dupliquée. → {raw, page, text, created}."""
    from .store import Brain
    root = ws.root()
    if not root:
        raise RuntimeError("pas de wiki : `brain wiki init <dossier>`")
    day = now_iso()[:10]
    content, ext, src_url = None, "", url or ""
    raw_path = None
    if text is not None:
        content, ext = text.encode("utf-8"), ".md"
        if not title:
            title = (ws.parse_page(text)["t"] or next((ln.strip("# ").strip() for ln in text.splitlines() if ln.strip()),
                                                      "")[:90]) or "Note"
    elif re.match(r"^https?://", str(src or ""), re.I):
        src_url = src_url or src
        if YOUTUBE.match(src):
            raise RuntimeError("vidéo YouTube : récupère d'abord la transcription (outil de transcription, ou copie), "
                               f"puis `brain wiki add - -T \"Titre\" --url {src} --format video` (texte par l'entrée "
                               "standard)")
        try:
            t, content, ext = fetch(src)
        except Exception as exc:
            raise RuntimeError(f"téléchargement impossible ({short(str(exc), 160)}) : enregistre la page avec Obsidian "
                               f"Web Clipper dans raw/, ou passe le texte : `brain wiki add - -T \"Titre\" --url {src}`")
        title = title or t or src_url
    else:
        p = Path(os.path.expanduser(str(src))).resolve()
        if not p.is_file():
            alt = (root / str(src)).resolve()
            if alt.is_file():
                p = alt
            else:
                raise RuntimeError(f"fichier introuvable : {src}")
        ext = p.suffix.lower()
        try:
            inside = p.relative_to(root.resolve()).as_posix()
        except ValueError:
            inside = None
        if inside and inside.startswith(ws.RAW + "/"):
            raw_path = p  # déjà déposée (Web Clipper, glisser-déposer) : on la référence telle quelle
        else:
            content = p.read_bytes()
        if not title and ext in (".md", ".markdown"):
            t, u, a, d = _frontmatter_title(p.read_text(encoding="utf-8", errors="replace"))
            title, src_url, author = title or t, src_url or u, author or a
        title = title or p.stem
    title = " ".join(str(title).split())[:120] or "Source"
    if raw_path is None:
        digest = content_digest(content)
        for rel in raw_files(root):  # même contenu déjà dans raw/ : pas de doublon
            try:
                if (root / rel).stat().st_size < 50 * 1024 * 1024 and content_digest((root / rel).read_bytes()) == digest:
                    raw_path = root / rel
                    break
            except OSError:
                continue
        if raw_path is None:
            if ext == ".md" and src_url and not content.lstrip().startswith(b"---"):
                head = "---\n" + "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in
                                           (("title", title), ("source", src_url), ("recupere", day)) if v) + "\n---\n\n"
                content = head.encode("utf-8") + content
            raw_path = _unique_raw(root, f"{day} {ws.fname(title)[:80]}{ext or '.md'}")
            with open(raw_path, "wb") as fh:
                fh.write(content)
    rel = raw_path.relative_to(root).as_posix()
    sha = sha1_file(raw_path)
    body_text = extract_text(raw_path)
    created = False
    with Brain.edit() as b:
        page = next((n for n in b.nodes.values() if n["type"] == "source"
                     and str((n.get("meta") or {}).get("brut") or "").lower() == rel.lower()), None)
        if page is None:
            meta = {"brut": rel, "sha1": sha, "format": fmt or _guess_format(ext, src_url), "resume": ""}
            if src_url:
                meta["url"] = src_url
            if author:
                meta["auteur"] = author
            skeleton = (f"## Résumé\n{TODO_MARK} — lire la source `{rel}` puis écrire ce qu'elle dit d'essentiel.\n\n"
                        "## Points clés\n- \n\n## Citations\n> \n\n## Ce que ça change dans le wiki\n- ")
            page = b.add("source", title, skeleton, project=None, importance=3, source="claude", meta=meta)
            page["meta"].pop("resume", None)
            created = True
    return {"raw": rel, "page": page, "text": body_text, "created": created, "root": root}


def ingest_plan(info) -> str:
    """Le plan d'ingestion affiché après `wiki add` : où est la source, sa taille, les pages à revoir, les noms repérés."""
    from .common import est_tokens
    from .store import Brain
    brain = Brain.load()
    page, text, root = info["page"], info["text"], info["root"]
    files = (brain.data.get("wiki") or {}).get("files") or {}
    page_path = (files.get(page["id"]) or {}).get("path") or f"{ws.PAGES}/Sources/{ws.fname(page['title'])}.md"
    lines = [("✓ source rangée" if info["created"] else "· source déjà connue") + f" : {info['raw']}",
             f"✓ page à remplir : {page_path} (`{page['id']}`)"]
    if text:
        lines.append(f"· texte : {len(text)} car. ≈ {est_tokens(text)} tokens"
                     + (" — lire par morceaux (Read offset/limit)" if len(text) > 60000 else ""))
        rel = related(brain, text, exclude={page["id"]})
        if rel:
            lines.append("· pages sans doute concernées (à relire, compléter, relier) :")
            lines += [f"  - [[{ws.stem(files[n['id']]['path']) if n['id'] in files else n['title']}]] "
                      f"({type_label(n['type'])}) — {short(_summary(n, 90), 90)}" for s, n in rel]
        cands = candidates(brain, text)
        if cands:
            lines.append("· noms cités sans page à eux (entités ou concepts à créer s'ils comptent) : "
                         + ", ".join(f"{e} ({c}×)" for e, c in cands))
    else:
        lines.append(f"· texte non extrait (PDF, image, binaire) : lire directement {root / info['raw']}")
    lines.append(f"→ Suite (schéma {root / SCHEMA_FILE}) : lire la source · dire les points clés à l'utilisateur · "
                 f"remplir la page (remplacer « {TODO_MARK} », `resume:`) · mettre à jour/créer les pages concernées "
                 f"(ajouter la source dans `sources:`) · contradictions en `> [!contradiction]` · "
                 f"`brain wiki log ingest \"{page['title']}\" \"pages touchées : …\"`")
    return "\n".join(lines)


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
    nodes = data["nodes"]
    stems = {s.lower(): nid for nid, s in names.items()}
    find = ws._resolver(nodes, stems)
    active = [n for n in nodes.values() if n.get("status", "active") == "active"]
    inbound = {}
    for e in data["edges"]:
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
        lines.append(f"Git : {url or 'local (pas d origin)'}" + (f" · {len(rows)} fichier(s) non commités" if rows else "")
                     + (" · " + " · ".join(sync_bits) if sync_bits else "")
                     + (f" · dernière synchro {fmt_date(st_.get('synced'))}" if st_.get("synced") else "")
                     + (" · ⚠ conflit à régler à la main" if st_.get("conflict") else ""))
    else:
        lines.append("Git : pas de dépôt (historique et synchronisation absents) — `git init` dans le wiki")
    last = log_entries(root, 5)
    if last:
        lines.append("Journal (dernières entrées) :")
        lines += [f"  {x[3:]}" for x in last]
    return "\n".join(lines)


def notice(brain) -> str:
    """Ligne injectée au démarrage d'une session (mode wiki) : où est le wiki, ce qui attend, la méthode."""
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
    conflict = (read_json(SYNC_STATE, {}) or {}).get("conflict")
    return (f"📚 Le cerveau vit dans le wiki {root} ({total} pages dont {know} de savoir) — schéma : {root / SCHEMA_FILE} ; "
            f"`brain q` y cherche, `brain wiki add <source>` ingère, `brain wiki lint` entretient."
            + (f" ⏳ {pend} source(s) à ingérer (`brain wiki pending`)." if pend else "")
            + (" ⚠ Synchro git en conflit : `brain wiki status`." if conflict else ""))


def init(path, migrate=True, push=True) -> list:
    """Crée (ou complète) le wiki dans `path`, y migre le cerveau classique, et fait de ce wiki la mémoire du cerveau.
    Rien n'est perdu : coffre Obsidian rapatrié d'abord, instantané et copie de graph.json gardés."""
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
            report.append("✓ push vers GitHub" if code == 0 else f"✗ push : {short(txt, 200)} (relance : `brain wiki sync`)")
    else:
        report.append("· pas de dépôt git : `git init` (ou clone ton dépôt GitHub privé) pour l'historique et la synchro")
    report.append(f"→ ouvre {root} dans Obsidian ; le schéma (à faire évoluer) : {root / SCHEMA_FILE}")
    return report


def session_close(brain, project=None) -> str:
    """Fin de session (mode wiki) : index à jour, entrée « session » au journal si des pages ont changé."""
    root = ws.root()
    if not root:
        return ""
    write_index(brain, root)
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
