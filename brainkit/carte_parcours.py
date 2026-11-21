"""Carte de projets : parcours du dossier (dossiers ignorés, .gitignore, limite de fichiers), lecture
incrémentale de chaque fichier (process_file) et copies identiques. Partie de mapper.py, découpé le 21/11/2026."""
from __future__ import annotations

import fnmatch
import hashlib
import itertools
import os
import posixpath
import re
from collections import Counter, defaultdict, deque

from .carte_langages import (_decode, ASSET_EXT, CODE, LANG_BY_EXT, Lines, parse_config, parse_css, parse_csv,
                             parse_docx, parse_env_names, parse_generic, parse_html, parse_js, parse_json,
                             parse_liquid, parse_markdown, parse_notebook, parse_pdf, parse_pptx, parse_requirements,
                             parse_text, parse_xlsx, parse_xml, SPECIAL_FILES)
from .carte_python import parse_python
from .common import short

PARSER_VERSION = 5  # 5 : exports CommonJS, paquets locaux

# Dossiers ignorés partout : dépendances installées, caches, sorties qui ne portent que ce nom.
IGNORE_DIRS = {
    "node_modules", "__pycache__", "venv", "virtualenv", "vendor", "bower_components", "site-packages", "Pods",
    "__MACOSX", "$RECYCLE.BIN", "System Volume Information", "htmlcov", "storybook-static",
}
# Sorties de build : ignorées à la racine du projet ou à côté d'un fichier de build (package.json, pyproject.toml…),
# gardées ailleurs. Avant, `src/build/` ou `app/out/` (du vrai code) disparaissaient de la carte (audit du 20/11).
BUILD_DIRS = {"dist", "build", "out", "target", "obj", "coverage"}
# Environnement Python : ignoré seulement s'il en a l'air (pyvenv.cfg, conda-meta, script activate) ; `src/env/` reste.
ENV_DIRS = {"env"}
ENV_MARKS = ("pyvenv.cfg", "conda-meta", "bin/activate", "Scripts/activate", "Scripts/activate.bat")
BUILD_FILES = {"package.json", "pyproject.toml", "setup.py", "setup.cfg", "cargo.toml", "go.mod", "pom.xml",
               "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "composer.json", "gemfile",
               "cmakelists.txt", "makefile", "meson.build", "tsconfig.json", "angular.json", "deno.json", "pubspec.yaml",
               "build.xml", "project.json", "mix.exs", "stack.yaml", "dune-project", "build.sbt"}
BUILD_FILE_RX = re.compile(r"\.(?:sln|csproj|fsproj|vbproj|vcxproj)$|^(?:vite|webpack|rollup|next|nuxt|svelte|astro|"
                           r"vue|gatsby|remix|tsup|esbuild|parcel|quasar)\.config\.[cm]?[jt]s$|^(?:gulpfile|gruntfile)\.", re.I)
KEEP_DOT_DIRS = {".github", ".gitlab", ".devcontainer", ".storybook", ".husky"}
JUNK_FILES = {"thumbs.db", "desktop.ini", ".ds_store"}
SENSITIVE = re.compile(
    r"(^\.env(\..+)?$|\.(pem|key|p12|pfx|keystore|jks)$|^id_(rsa|ed25519|ecdsa|dsa)|^credentials?[\w.-]*\.json$"
    r"|^secrets?\.(json|ya?ml|toml)$|^\.(npmrc|pypirc|netrc)$|^service[-_]?account.*\.json$)", re.I)
SAFE_SUFFIX = re.compile(r"\.(example|sample|template|dist|defaults?)$", re.I)


PARSERS = {
    "python": parse_python, "js": parse_js, "ts": parse_js, "vue": parse_js, "svelte": parse_js,
    "html": parse_html, "css": parse_css, "liquid": parse_liquid, "markdown": parse_markdown, "json": parse_json,
    "yaml": parse_config, "toml": parse_config, "ini": parse_config, "xml": parse_xml,
    "requirements": parse_requirements, "env": parse_env_names, "csv": parse_csv, "notebook": parse_notebook,
    "text": parse_text,
}
TODO_RX = re.compile(r"(?:#|//|/\*|<!--|^[ \t]*\*|--|\bREM\b)[ \t]*\b(TODO|FIXME|HACK|XXX)\b[:\s]*(.{0,90})", re.M)
WHY_RX = re.compile(r"(?:#|//|/\*|<!--|^[ \t]*\*|--)[ \t]*\b(WHY|NOTE|IMPORTANT|POURQUOI|ATTENTION|NB|RAISON)\b"
                    r"[ \t]*:[ \t]*(.{3,140})", re.M)  # raisons notées dans le code (façon graphify « rationale »)


# =============================================================================================== parcours
def classify(rel):
    low = posixpath.basename(rel).lower()
    if low in SPECIAL_FILES:
        return SPECIAL_FILES[low]
    if re.match(r"requirements.*\.txt$", low):
        return "requirements"
    if low.startswith(".env"):
        return "env"
    return LANG_BY_EXT.get(posixpath.splitext(low)[1])


RACY_NS = 2_000_000_000  # dates de fichier à 2 s près (FAT, exFAT) : marge de la règle « racy » de git


def process_file(root, rel, prev, max_bytes, size=None, mtime=None, ino=0, racy=None):
    """→ (fiche, a_été_parsé) ou None si illisible. `mtime` en nanosecondes ; `ino` : n° du fichier (0 s'il est
    inconnu). Fiche réutilisée sans relire le fichier si taille, date à la nanoseconde et n° sont les mêmes, et si sa
    date n'est pas trop proche de la carte précédente (`racy` : début de son parcours moins RACY_NS) : modifié dans la
    même seconde que la carte précédente, sur un disque aux dates grossières, il est relu (et pas re-analysé si son
    contenu n'a pas changé). Avant, la date à la seconde près cachait un changement fait dans la même seconde."""
    path = os.path.join(root, rel)
    if size is None or mtime is None:
        try:
            st = os.stat(path)
        except OSError:
            return None
        size, mtime, ino = st.st_size, st.st_mtime_ns, st.st_ino
    if (prev and prev.get("size") == size and prev.get("mns") == mtime and prev.get("ino", 0) == (ino or 0)
            and prev.get("v") == PARSER_VERSION and (racy is None or mtime < racy)):
        return dict(prev), False
    name = posixpath.basename(rel)
    lang = classify(rel)
    ext = posixpath.splitext(name.lower())[1]
    rec = {"v": PARSER_VERSION, "size": size, "mtime": mtime // 1_000_000_000, "mns": mtime,
           "lang": lang or ("asset" if ext in ASSET_EXT else "other")}
    if ino:
        rec["ino"] = ino
    if SENSITIVE.search(name) and not SAFE_SUFFIX.search(name):
        rec["sensitive"] = True  # jamais lu : peut contenir des secrets
        return rec, True
    if lang in ("docx", "xlsx", "pptx"):
        rec.update({"docx": parse_docx, "xlsx": parse_xlsx, "pptx": parse_pptx}[lang](path))
        return rec, True
    if lang == "pdf":
        rec.update(parse_pdf(path, size))
        return rec, True
    if not lang or lang in ("skip", "odt", "rtf", "doc", "xls"):
        return rec, True
    big = size > max_bytes
    try:
        with open(path, "rb") as fh:
            data = fh.read(65536 if big else size + 1)
    except OSError:
        return rec, True
    if b"\x00" in data[:8192]:
        rec["lang"] = "binary"
        return rec, True
    if big:
        rec["big"] = True
        if lang == "csv":
            rec["doc"] = f"gros fichier · colonnes : {short(_decode(data).split(chr(10), 1)[0], 160)}"
        return rec, True
    sha = hashlib.sha1(data).hexdigest()
    if prev and prev.get("sha1") == sha and prev.get("v") == PARSER_VERSION:
        prev = dict(prev)
        prev.update(size=size, mtime=rec["mtime"], mns=mtime)
        prev.pop("ino", None)
        if ino:
            prev["ino"] = ino
        return prev, False
    text = _decode(data)
    rec["sha1"] = sha
    rec["lines"] = text.count("\n") + (0 if text.endswith("\n") else 1)
    parser = PARSERS.get(lang)
    try:
        rec.update(parser(text, rel) if parser else parse_generic(text, rel, lang))
    except Exception as exc:  # un parseur ne doit jamais casser la carte
        rec["err"] = short(repr(exc), 100)
    if lang in CODE:
        lines = Lines(text)
        todos = [(lines.at(m.start()), m.group(1), short(m.group(2), 80))
                 for m in itertools.islice(TODO_RX.finditer(text), 60)]
        if todos:
            rec["todo"] = len(todos)
            rec["todos"] = todos[:3]
        why = [(lines.at(m.start()), m.group(1), short(re.sub(r"\s*(\*/|-->)\s*$", "", m.group(2).strip()), 110))
               for m in itertools.islice(WHY_RX.finditer(text), 6)]
        if why:
            rec["why"] = why
    return {k: v for k, v in rec.items() if v not in (None, "", [], {})}, True


def _gitignore(root):
    pats = []
    try:
        with open(os.path.join(root, ".gitignore"), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith(("#", "!")):
                    continue
                dir_only = line.endswith("/")
                line = line.strip("/")
                if line:
                    pats.append((line, dir_only, "/" in line))
    except OSError:
        pass

    def ignored(rel, is_dir):
        name = rel.rsplit("/", 1)[-1]
        for pat, dir_only, anchored in pats:
            if dir_only and not is_dir:
                continue
            if fnmatch.fnmatch(rel if anchored else name, pat):
                return True
        return False

    return ignored


def _has_build_file(entries) -> bool:
    for e in entries:
        low = e.name.lower()
        if low in BUILD_FILES or BUILD_FILE_RX.search(low):
            try:
                if e.is_file():
                    return True
            except OSError:
                continue
    return False


def _looks_like_env(path) -> bool:
    return any(os.path.exists(os.path.join(path, m)) for m in ENV_MARKS)


def walk(root, max_files):
    """Parcours en largeur (niveau par niveau) : si la limite est atteinte, ce sont les profondeurs qui sont
    tronquées, pas des dossiers entiers. → [(chemin relatif, taille, date en ns, n° du fichier)], tronqué ?"""
    ignored = _gitignore(root)
    isjunction = getattr(os.path, "isjunction", lambda p: False)
    files = []
    queue = deque([""])
    while queue:
        rel_dir = queue.popleft()
        try:
            entries = sorted(os.scandir(os.path.join(root, rel_dir) if rel_dir else root), key=lambda e: e.name.lower())
        except OSError:
            continue
        subdirs = []
        beside = None  # ce dossier contient-il un fichier de build ? (calculé seulement s'il a un dossier build/, out/…)
        for e in entries:
            name = e.name
            rel = f"{rel_dir}/{name}" if rel_dir else name
            try:
                if e.is_symlink() or isjunction(e.path):
                    continue
                if e.is_dir():
                    if name in BUILD_DIRS and beside is None:
                        beside = not rel_dir or _has_build_file(entries)
                    if not (name in IGNORE_DIRS or (name.startswith(".") and name not in KEEP_DOT_DIRS)
                            or (name in BUILD_DIRS and beside) or (name in ENV_DIRS and _looks_like_env(e.path))
                            or ignored(rel, True)):
                        subdirs.append(rel)
                    continue
                if name.lower() in JUNK_FILES or name.startswith("~$") or ignored(rel, False):
                    continue
                st = e.stat()
            except OSError:
                continue
            files.append((rel, st.st_size, st.st_mtime_ns, st.st_ino))
            if len(files) >= max_files:
                return files, True
        queue.extend(subdirs)
    return files, False


def mark_duplicates(files):
    """Copies identiques (sauvegardes, exports de thème…) : la plus récente reste la référence, les autres
    sont marquées `dup` et ignorées dans les classements et la recherche."""
    groups = defaultdict(list)
    for rel, f in files.items():
        if f.get("sha1") and f.get("size", 0) > 64:
            groups[f["sha1"]].append(rel)
    dirs = Counter()
    count = 0
    for rels in groups.values():
        if len(rels) < 2:
            continue
        rels.sort(key=lambda r: (-files[r].get("mtime", 0), r.count("/"), r))
        for r in rels[1:]:
            files[r]["dup"] = rels[0]
            dirs[r.split("/")[0] if "/" in r else "(racine)"] += 1
            count += 1
    return count, dirs
