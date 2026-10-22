"""Cartographe de projets façon graphify — 100 % local, sans dépendance externe.

fichiers → symboles (fonctions, classes, routes, variables d'env), imports/liens résolus → graphe,
centralité (PageRank), modules (propagation de labels), cycles, points d'entrée, stack technique.
Documents aussi : titres Markdown, Word (.docx), feuilles Excel (.xlsx), diapos (.pptx), PDF, CSV.

Sorties dans ~/.claude/brain/projects/<id>/ :
  map.json     données complètes → requêtes where / deps / explain / impact / path / files
  MAP.md       rapport lisible (structure, fichiers clés, modules, routes, docs, points d'attention)
  DIGEST.md    résumé court injecté automatiquement au démarrage d'une session dans ce projet
  search.json  index de recherche pré-calculé (rappel automatique des fichiers pertinents)
Incrémental : fichier inchangé (taille + date) → pas relu ; relu avec le même hash → pas re-parsé."""
from __future__ import annotations

import ast
import bisect
import fnmatch
import hashlib
import html
import itertools
import json
import os
import posixpath
import re
import sys
import tempfile
import time
import urllib.parse
import warnings
import zipfile
from collections import Counter, defaultdict, deque
from pathlib import Path

from .common import (CLAUDE_HOME, PROJECTS_DIR, FileLock, first_line, fmt_date, is_scratch, load_config, log,
                     norm_path, now_iso, path_within, read_json, short, tokenize, write_json, write_text)
from .search import Index
from .store import Brain

PARSER_VERSION = 4

IGNORE_DIRS = {
    "node_modules", "__pycache__", "venv", "env", "virtualenv", "dist", "build", "out", "target", "coverage",
    "vendor", "bower_components", "site-packages", "Pods", "obj", "__MACOSX", "$RECYCLE.BIN",
    "System Volume Information", "htmlcov", "storybook-static",
}
KEEP_DOT_DIRS = {".github", ".gitlab", ".devcontainer", ".storybook", ".husky"}
JUNK_FILES = {"thumbs.db", "desktop.ini", ".ds_store"}

LANG_BY_EXT = {
    ".py": "python", ".pyw": "python", ".pyi": "python",
    ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js", ".astro": "js",
    ".ts": "ts", ".tsx": "ts", ".mts": "ts", ".cts": "ts",
    ".vue": "vue", ".svelte": "svelte",
    ".php": "php", ".rb": "ruby", ".go": "go", ".rs": "rust", ".java": "java", ".scala": "java",
    ".kt": "kotlin", ".kts": "kotlin", ".cs": "csharp", ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp",
    ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".swift": "swift", ".dart": "dart", ".lua": "lua",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".ps1": "powershell", ".psm1": "powershell",
    ".bat": "batch", ".cmd": "batch", ".sql": "sql",
    ".html": "html", ".htm": "html", ".css": "css", ".scss": "css", ".sass": "css", ".less": "css",
    ".liquid": "liquid",
    ".md": "markdown", ".mdx": "markdown", ".markdown": "markdown", ".txt": "text", ".rst": "text",
    ".r": "text", ".log": "skip",
    ".json": "json", ".jsonc": "json", ".webmanifest": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".ini": "ini", ".cfg": "ini", ".conf": "ini", ".properties": "ini", ".xml": "xml",
    ".csv": "csv", ".tsv": "csv", ".ipynb": "notebook",
    ".docx": "docx", ".xlsx": "xlsx", ".xlsm": "xlsx", ".pptx": "pptx", ".pdf": "pdf",
    ".odt": "odt", ".rtf": "rtf", ".doc": "doc", ".xls": "xls",
}
SPECIAL_FILES = {
    "dockerfile": "docker", "makefile": "make", "procfile": "text", "gemfile": "ruby", "rakefile": "ruby",
    "jenkinsfile": "text", ".gitignore": "skip", ".gitattributes": "skip", ".editorconfig": "skip",
    ".prettierrc": "json", ".eslintrc": "json", ".babelrc": "json",
}
CODE = {"python", "js", "ts", "vue", "svelte", "php", "ruby", "go", "rust", "java", "kotlin", "csharp", "c", "cpp",
        "swift", "dart", "lua", "shell", "powershell", "batch", "sql", "liquid", "html", "css", "docker", "make"}
DOCS = {"markdown", "text", "docx", "pptx", "pdf", "odt", "rtf", "doc"}
DATA = {"json", "yaml", "toml", "ini", "xml", "csv", "xlsx", "xls", "requirements", "env", "notebook"}
LANG_LABEL = {
    "python": "Python", "js": "JavaScript", "ts": "TypeScript", "vue": "Vue", "svelte": "Svelte", "php": "PHP",
    "ruby": "Ruby", "go": "Go", "rust": "Rust", "java": "Java", "kotlin": "Kotlin", "csharp": "C#", "c": "C",
    "cpp": "C++", "swift": "Swift", "dart": "Dart", "lua": "Lua", "shell": "Shell", "powershell": "PowerShell",
    "batch": "Batch", "sql": "SQL", "liquid": "Liquid", "html": "HTML", "css": "CSS", "docker": "Docker",
    "make": "Make", "markdown": "Markdown", "docx": "Word", "xlsx": "Excel", "pptx": "PowerPoint", "pdf": "PDF",
}
ASSET_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp", ".tif", ".tiff", ".avif", ".heic", ".mp4",
    ".mov", ".avi", ".mkv", ".webm", ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".woff", ".woff2", ".ttf", ".otf",
    ".eot", ".zip", ".rar", ".7z", ".gz", ".tar", ".exe", ".msi", ".dll", ".so", ".dylib", ".bin", ".iso", ".psd",
    ".ai", ".fig", ".sketch", ".blend", ".fbx", ".obj", ".glb", ".gltf", ".db", ".sqlite", ".sqlite3", ".lock",
    ".map", ".pyc", ".class", ".jar",
}
SENSITIVE = re.compile(
    r"(^\.env(\..+)?$|\.(pem|key|p12|pfx|keystore|jks)$|^id_(rsa|ed25519|ecdsa|dsa)|^credentials?[\w.-]*\.json$"
    r"|^secrets?\.(json|ya?ml|toml)$|^\.(npmrc|pypirc|netrc)$|^service[-_]?account.*\.json$)", re.I)
SAFE_SUFFIX = re.compile(r"\.(example|sample|template|dist|defaults?)$", re.I)
NOT_NAMES = {"if", "for", "while", "switch", "return", "function", "catch", "else", "new", "typeof", "await",
             "async", "super", "this", "do", "try"}


# =============================================================================================== utilitaires
class Lines:
    """Position dans le texte → numéro de ligne (recherche dichotomique)."""
    __slots__ = ("starts",)

    def __init__(self, text):
        starts = [0]
        i = text.find("\n")
        while i != -1:
            starts.append(i + 1)
            i = text.find("\n", i + 1)
        self.starts = starts

    def at(self, pos):
        return bisect.bisect_right(self.starts, pos)


_PRELUDE = re.compile(r"^(?:﻿|#![^\n]*\n|[ \t]*['\"]use (?:strict|client|server)['\"];?[ \t]*\n|<\?php[ \t]*\n|[ \t]*\n)+")
_DOC = re.compile(
    r"[ \t]*(?:/\*\*?(.*?)\*/|((?:[ \t]*//[^\n]*\n?)+)|((?:[ \t]*#[^\n]*\n?)+)|\"\"\"(.*?)\"\"\"|'''(.*?)'''"
    r"|<!--(.*?)-->|((?:[ \t]*--[^\n]*\n?)+)|((?:[ \t]*(?:REM|::)[^\n]*\n?)+))", re.S)
_NOISE = re.compile(r"^(eslint|prettier|@ts-|global |jshint|noinspection|-\*-|coding[:=]|pylint|type: ?ignore|"
                    r"copyright|\(c\)|license|spdx|@flow|@jsx|vim:|!/usr|@echo)", re.I)


def leading_doc(text) -> str:
    """Première ligne utile du commentaire d'en-tête d'un fichier."""
    head = _PRELUDE.sub("", text[:4000], count=1)
    m = _DOC.match(head)
    if not m:
        return ""
    raw = next((g for g in m.groups() if g), "")
    for line in raw.splitlines():
        line = re.sub(r"^(?:[\s/#*\-:]+|rem\s+)", "", line, flags=re.I).strip()
        if len(line) >= 4 and not _NOISE.match(line):
            return short(line, 140)
    return ""


def _syms(text, patterns, lines, cap=200):
    out, seen = [], set()
    for rx, kind in patterns:
        for m in rx.finditer(text):
            name = m.group(1)
            if not name or name in seen or name in NOT_NAMES:
                continue
            seen.add(name)
            out.append({"n": name, "k": kind, "l": lines.at(m.start(1))})
            if len(out) >= cap:
                break
    out.sort(key=lambda s: s["l"])
    return out


def _is_local_ref(ref) -> bool:
    ref = (ref or "").strip()
    return bool(ref) and not re.match(r"^(?:[a-z][a-z0-9+.-]*:|//|\{\{|\{%|\$\{|#)", ref, re.I)


def _decode(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    if text.count("�") > 8:
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError:
            pass
    return text.lstrip("﻿")


def fmt_ts(ts) -> str:
    try:
        return time.strftime("%d/%m/%Y", time.localtime(int(ts)))
    except (TypeError, ValueError, OSError, OverflowError):
        return "?"


def _n(num) -> str:
    return f"{num:,}".replace(",", " ")


def _size(num) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if num < 1024:
            return f"{num:.0f} {unit}"
        num /= 1024
    return f"{num:.0f} To"


def _is_test(rel) -> bool:
    return bool(re.search(r"(^|/)(tests?|__tests__|spec|e2e)(/|$)|(_test|\.test|\.spec)\.|(^|/)test_", rel))


# =============================================================================================== parseurs
PY_ENV = re.compile(r"""os\.(?:environ\.get|getenv)\(\s*['"]([A-Za-z_]\w*)['"]|os\.environ\[\s*['"]([A-Za-z_]\w*)['"]\s*\]""")
DJANGO_PATH = re.compile(r"""\b(?:re_)?path\(\s*r?['"]([^'"]*)['"]\s*,\s*([\w.]+)""")
ROUTE_METHODS = {"route", "get", "post", "put", "patch", "delete", "websocket", "api_route", "head", "options"}


def _decorator_routes(fn):
    out = []
    for d in fn.decorator_list:
        if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)):
            continue
        meth = d.func.attr.lower()
        if meth not in ROUTE_METHODS or not d.args:
            continue
        a0 = d.args[0]
        if not (isinstance(a0, ast.Constant) and isinstance(a0.value, str)):
            continue
        verb = meth.upper()
        if meth in ("route", "api_route"):
            verb = "ANY"
            for kw in d.keywords:
                if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                    vals = [e.value for e in kw.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                    if vals:
                        verb = "/".join(v.upper() for v in vals)
        out.append(f"{verb} {a0.value} → {fn.name}")
    return out


def _is_main_guard(test) -> bool:
    return isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id == "__name__"


def parse_python(text, rel):
    out = {"symbols": [], "imports": [], "routes": []}
    try:
        with warnings.catch_warnings():  # échappements invalides dans le code analysé : pas notre affaire
            warnings.simplefilter("ignore")
            tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return parse_generic(text, rel, "python_fallback")
    doc = ast.get_docstring(tree)
    out["doc"] = first_line(doc) if doc else leading_doc(text)
    consts = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out["symbols"].append({"n": node.name, "k": "fn", "l": node.lineno})
            out["routes"] += _decorator_routes(node)
        elif isinstance(node, ast.ClassDef):
            out["symbols"].append({"n": node.name, "k": "class", "l": node.lineno})
            for sub in node.body[:80]:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if sub.name.startswith("__") and sub.name != "__init__":
                        continue
                    out["symbols"].append({"n": f"{node.name}.{sub.name}", "k": "method", "l": sub.lineno})
                    out["routes"] += _decorator_routes(sub)
        elif isinstance(node, ast.If) and _is_main_guard(node.test):
            out["main"] = True
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and consts < 12:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id.isupper() and len(t.id) > 2:
                    out["symbols"].append({"n": t.id, "k": "const", "l": node.lineno})
                    consts += 1
    binds, stars = {}, []  # noms importés (hors bibliothèque standard) → base du graphe d'appels
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out["imports"] += [a.name for a in node.names]
            for a in node.names:
                top = a.name.split(".")[0]
                if top not in STDLIB:
                    binds[a.asname or top] = ("m", a.name if a.asname else top)
        elif isinstance(node, ast.ImportFrom):
            dots = "." * (node.level or 0)
            mod = node.module or ""
            if mod:
                out["imports"].append(dots + mod)
            for a in node.names[:12]:
                if a.name != "*":
                    out["imports"].append(dots + (mod + "." if mod else "") + a.name)
            if dots or mod.split(".")[0] not in STDLIB:
                for a in node.names:
                    if a.name == "*":
                        stars.append(dots + mod)
                    else:
                        binds[a.asname or a.name] = ("f", dots + mod, a.name)
    out["env"] = sorted({a or b for a, b in PY_ENV.findall(text)})
    if rel.endswith("urls.py"):
        out["routes"] += [f"PATH /{p} → {v}" for p, v in DJANGO_PATH.findall(text)[:40]]
    out["imports"] = list(dict.fromkeys(out["imports"]))
    try:
        out["pyrefs"] = _py_refs(tree, out["symbols"], binds, stars)
    except Exception:  # graphe d'appels facultatif : jamais au prix des symboles
        pass
    out["pystar"] = list(dict.fromkeys(stars))
    return out


# =============================================================================================== graphe d'appels (Python)
# Façon graphify (« affected ») : qui appelle quoi, pour savoir ce qui casse avant de modifier. Les références sont
# notées brutes à l'analyse (par fichier : la carte reste incrémentale), puis résolues à la demande sur la carte entière.
# Règle reprise de graphify : un nom ambigu ne donne aucun lien plutôt qu'un faux.
MAX_REFS = 1500  # références gardées par fichier
CALL_NOISE_WORDS = frozenset((
    "add get set put pop run call start stop open close read write send load dump save join wait poll info debug "
    "warning error exception log update apply submit result cancel execute commit rollback connect fetch process "
    "handle check validate parse build create delete remove reset setup render show draw name value data exists "
    "mkdir glob rglob touch unlink rename acquire release notify emit dispatch trigger refresh reload flush seek tell "
    "readline readlines writelines headers json text content status raise_for_status iter_content add_argument "
    "add_parser parse_args set_defaults add_subparsers").split())
_CALL_NOISE = None


def _call_noise():
    """Noms trop courants pour deviner un appel : builtins, méthodes des types natifs, API usuelles."""
    global _CALL_NOISE
    if _CALL_NOISE is None:
        import builtins
        import datetime
        import io
        kinds = (str, bytes, bytearray, list, dict, set, frozenset, tuple, int, float, complex, object, Path,
                 io.TextIOWrapper, io.BufferedReader, io.BytesIO, io.StringIO, type(re.compile("")),
                 type(re.match("", "")), datetime.datetime, datetime.timedelta, deque, Counter, defaultdict)
        _CALL_NOISE = CALL_NOISE_WORDS.union(dir(builtins), *(dir(k) for k in kinds))
    return _CALL_NOISE


def _locals(fn):
    """Noms locaux d'une fonction (paramètres, affectations, boucles, with, except, définitions internes) : ils masquent
    les noms du module. Les imports faits dans la fonction n'en sont pas : ils restent des liens."""
    names, glob = set(), set()
    for n in ast.walk(fn):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = n.args
            names.update(x.arg for x in a.posonlyargs + a.args + a.kwonlyargs)
            names.update(x.arg for x in (a.vararg, a.kwarg) if x)
            if n is not fn and not isinstance(n, ast.Lambda):
                names.add(n.name)
        elif isinstance(n, ast.ClassDef):
            names.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            names.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            glob.update(n.names)
    return names - glob


def _py_refs(tree, symbols, binds, stars) -> dict:
    """Références d'un module Python, notées brutes : {appelant: ["ligne relation genre a [b [c]]", …]}.
    Appelant : « fonction », « Classe.méthode », « Classe » (bases, décorateurs, corps), CONSTANTE, « » (module).
    Relation : c appel · h héritage · r usage (fonction passée en valeur, table de rappels, constante).
    Genre : l nom du fichier · i nom importé (module, nom) · m module importé (chemin, attribut) · f nom importé suivi
    d'attributs (module, chemin, attribut) · s self.attr · p super().attr · * import étoile · a méthode devinée par
    son seul nom (gardée seulement si un seul candidat)."""
    noise = _call_noise()
    local = {s["n"] for s in symbols if "." not in s["n"]}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            for t in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(t, ast.Name) and t.id.isupper():
                    local.add(t.id)
    classes = {s["n"] for s in symbols if s["k"] == "class"}
    out, seen = {}, set()

    def note(caller, line, rel, r):
        if not r or len(seen) >= MAX_REFS:
            return
        k = (caller, rel) + r
        if k not in seen:
            seen.add(k)
            out.setdefault(caller, []).append(" ".join((str(line), rel) + r))

    def ref(e, cls, shadow):
        if isinstance(e, ast.Name):
            n = e.id
            if n in shadow:
                return None
            b = binds.get(n)
            if b:
                return ("i", b[1], b[2]) if b[0] == "f" else None
            if n in local:
                return ("l", n)
            return ("*", n) if stars and n not in noise else None
        if not isinstance(e, ast.Attribute):
            return None
        attr, chain, v = e.attr, [], e.value
        while isinstance(v, ast.Attribute):
            chain.append(v.attr)
            v = v.value
        chain.reverse()
        if isinstance(v, ast.Name):
            n = v.id
            if n in ("self", "cls") and cls and not chain:
                return ("s", cls, attr)
            if n not in shadow:
                b = binds.get(n)
                if b and b[0] == "m":
                    return ("m", ".".join([b[1]] + chain), attr)
                if b:
                    return ("f", b[1], ".".join([b[2]] + chain), attr)
                if n in classes and not chain:
                    return ("l", f"{n}.{attr}")
                return None  # module de la bibliothèque standard, variable globale… : rien à deviner
        elif isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "super":
            return ("p", cls, attr) if cls and not chain else None
        if attr.startswith("__") or len(attr) < 4 or attr in noise:
            return None
        return ("a", attr)

    def scan(nodes, caller, cls, shadow):
        stack = [(x, cls) for x in reversed(nodes)]
        while stack:
            e, c = stack.pop()
            if isinstance(e, ast.Call):
                note(caller, e.lineno, "c", ref(e.func, c, shadow))
                root = e.func
                while isinstance(root, ast.Attribute):
                    root = root.value
                if not isinstance(root, ast.Name):
                    stack.append((root, c))  # Panier().ajouter(), TABLE[k](x) : l'objet appelé se lit aussi
                args = list(e.args) + [k.value for k in e.keywords]
                for a in args:
                    if isinstance(a, ast.Attribute):
                        r = ref(a, c, shadow)
                        if r and r[0] in ("s", "p"):
                            note(caller, a.lineno, "r", r)  # Thread(target=self.boucle)
                stack.extend((a, c) for a in reversed(args))
            elif isinstance(e, ast.Name):
                if isinstance(e.ctx, ast.Load):
                    note(caller, e.lineno, "r", ref(e, c, shadow))
            elif isinstance(e, ast.Attribute):
                r = ref(e, c, shadow) if isinstance(e.ctx, ast.Load) else None
                if r and r[0] in ("m", "f", "l"):
                    note(caller, e.lineno, "r", r)
                else:
                    stack.append((e.value, c))
            else:
                if isinstance(e, ast.ClassDef):
                    c = None
                stack.extend((x, c) for x in reversed(list(ast.iter_child_nodes(e))))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scan([node], node.name, None, _locals(node))
        elif isinstance(node, ast.ClassDef):
            C = node.name
            for b in node.bases:
                r = ref(b, None, ())
                if r and r[0] != "a":
                    note(C, node.lineno, "h", r)
            scan(node.decorator_list + [k.value for k in node.keywords], C, None, set())
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    who = C if sub.name.startswith("__") and sub.name != "__init__" else f"{C}.{sub.name}"
                    scan([sub], who, C, _locals(sub))
                else:
                    scan([sub], C, C, set())
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            who = next((t.id for t in targets if isinstance(t, ast.Name) and t.id.isupper()), "")
            scan([x for x in (node.value, getattr(node, "annotation", None)) if x is not None], who, None, set())
        else:
            scan([node], "", None, set())
    return out


JS_IMPORT = re.compile(
    r"""(?:\bimport\s+(?:type\s+)?(?:[\w*$\s{},]+?\s+from\s+)?|\bexport\s+(?:type\s+)?(?:\*(?:\s+as\s+\w+)?|\{[^}]*\})\s+from\s+"""
    r"""|\brequire\s*\(\s*|\bimport\s*\(\s*)['"]([^'"\n]+)['"]""")
JS_PATTERNS = [
    (re.compile(r"^[ \t]*export\s+default\s+(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)", re.M), "fn"),
    (re.compile(r"^[ \t]*export\s+(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)", re.M), "fn"),
    (re.compile(r"^[ \t]*(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)", re.M), "class"),
    (re.compile(r"^[ \t]*export\s+(?:declare\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)", re.M), "type"),
    (re.compile(r"^[ \t]*export\s+(?:const|let|var)\s+([A-Za-z_$][\w$]*)", re.M), "const"),
    (re.compile(r"^(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)", re.M), "fn"),
    (re.compile(r"^(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(?:function\b|\([^)\n]*\)\s*(?::\s*[\w<>\[\]|, ]+)?\s*=>|[A-Za-z_$][\w$]*\s*=>)", re.M), "fn"),
    (re.compile(r"^(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)", re.M), "type"),
]
JS_ROUTE = re.compile(r"""\b(?:app|router|server|api|routes|fastify|r)\s*\.\s*(get|post|put|patch|delete|all)\s*\(\s*['"`]([^'"`\n]+)['"`]""")
JS_ENV = re.compile(r"""(?:process\.env|import\.meta\.env)\.([A-Z_][A-Z0-9_]*)|process\.env\[\s*['"]([A-Z_][A-Z0-9_]*)['"]\s*\]""")
SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S | re.I)
NEXT_APP = re.compile(r"(?:^|/)app/(.*?)/?(page|route)\.(?:t|j)sx?$")
NEXT_PAGES = re.compile(r"(?:^|/)pages/(.+?)\.(?:t|j)sx?$")


def _keep_scripts(text):
    """Garde uniquement les blocs <script> (Vue/Svelte) en conservant les numéros de ligne."""
    parts, last = [], 0
    for m in SCRIPT_BLOCK.finditer(text):
        parts.append("\n" * text.count("\n", last, m.start(1)))
        parts.append(m.group(1))
        last = m.end(1)
    return "".join(parts)


def _next_route(rel):
    m = NEXT_APP.search(rel)
    if m:
        segs = [s for s in m.group(1).split("/") if s and not (s.startswith("(") and s.endswith(")"))]
        return f"{'API' if m.group(2) == 'route' else 'PAGE'} /" + "/".join(segs)
    m = NEXT_PAGES.search(rel)
    if m and not posixpath.basename(m.group(1)).startswith("_"):
        path = re.sub(r"(^|/)index$", "", m.group(1))
        return ("API /" if path.startswith("api/") else "PAGE /") + path
    return None


def parse_js(text, rel):
    src = _keep_scripts(text) if rel.endswith((".vue", ".svelte", ".astro")) else text
    lines = Lines(src)
    out = {"symbols": _syms(src, JS_PATTERNS, lines),
           "imports": list(dict.fromkeys(m.group(1) for m in JS_IMPORT.finditer(src))),
           "routes": [f"{v.upper()} {p}" for v, p in JS_ROUTE.findall(src)][:40],
           "env": sorted({a or b for a, b in JS_ENV.findall(src)}),
           "doc": leading_doc(src)}
    nxt = _next_route(rel)
    if nxt:
        out["routes"].insert(0, nxt)
    if rel.endswith((".vue", ".svelte", ".astro")):
        out["symbols"].insert(0, {"n": posixpath.splitext(posixpath.basename(rel))[0], "k": "component", "l": 1})
    return out


HTML_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
HTML_SRC = re.compile(r"""<(?:script|iframe)\b[^>]*\bsrc\s*=\s*["']([^"'#?]+)""", re.I)
HTML_HREF = re.compile(r"""<(?:link|a)\b[^>]*\bhref\s*=\s*["']([^"'#?]+)""", re.I)
HTML_H = re.compile(r"<h([12])[^>]*>(.*?)</h\1>", re.S | re.I)
STRIP_TAGS = re.compile(r"<[^>]+>")
MEDIA_REF = re.compile(r"\.(png|jpe?g|gif|webp|svg|ico|avif|mp4|webm|mp3|woff2?|ttf|otf)$", re.I)


def parse_html(text, rel):
    out = {"headings": []}
    m = HTML_TITLE.search(text)
    if m:
        out["title"] = short(html.unescape(STRIP_TAGS.sub("", m.group(1))), 100)
    refs = HTML_SRC.findall(text) + HTML_HREF.findall(text)
    for block in SCRIPT_BLOCK.findall(text):
        refs += [m.group(1) for m in JS_IMPORT.finditer(block)]
    out["imports"] = [r for r in dict.fromkeys(refs) if _is_local_ref(r) and not MEDIA_REF.search(r)][:60]
    out["headings"] = [("#" * int(lvl)) + " " + short(html.unescape(STRIP_TAGS.sub("", h)), 80)
                       for lvl, h in HTML_H.findall(text)[:8]]
    forms = len(re.findall(r"<form\b", text, re.I))
    if forms:
        out["doc"] = f"{forms} formulaire(s)"
    return out


CSS_IMPORT = re.compile(r"""@import\s+(?:url\()?\s*['"]?([^'")\s;]+)""", re.I)


def parse_css(text, rel):
    return {"imports": [r for r in CSS_IMPORT.findall(text) if _is_local_ref(r)], "doc": leading_doc(text)}


LIQ_REF = re.compile(r"""\{%-?\s*(render|include|section|sections)\s+['"]([\w\-./]+)['"]""")
LIQ_ASSET = re.compile(r"""['"]([\w\-.]+\.(?:css|js|scss|json))['"]\s*\|\s*asset_url""")
LIQ_SCHEMA = re.compile(r"\{%-?\s*schema\s*-?%\}(.*?)\{%-?\s*endschema\s*-?%\}", re.S)


def parse_liquid(text, rel):
    out = {"imports": [f"liquid:{k}:{n}" for k, n in LIQ_REF.findall(text)]
           + [f"liquid:asset:{a}" for a in LIQ_ASSET.findall(text)]}
    m = LIQ_SCHEMA.search(text)
    if m:
        try:
            schema = json.loads(m.group(1))
            out["title"] = f"section « {schema.get('name', '?')} »"
            out["doc"] = f"{len(schema.get('settings', []))} réglages, {len(schema.get('blocks', []))} blocs"
        except Exception:
            pass
    out["imports"] = list(dict.fromkeys(out["imports"]))
    return out


MD_H = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$", re.M)
MD_LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")


def parse_markdown(text, rel):
    out = {}
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            fm = text[4:end]
            tm = re.search(r"(?m)^title:\s*['\"]?(.+?)['\"]?\s*$", fm)
            if tm:
                out["title"] = short(tm.group(1), 100)
            body = text[end + 4:]
    heads = [(len(h), short(t, 90)) for h, t in MD_H.findall(body)]
    out["headings"] = [("#" * lvl) + " " + t for lvl, t in heads[:15]]
    if not out.get("title"):
        h1 = next((t for lvl, t in heads if lvl == 1), None)
        if h1:
            out["title"] = h1
    in_code = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not s or s.startswith(("#", "---", "|", "<!--", "![", "<")) or len(s) < 15:
            continue
        out["doc"] = short(s.lstrip("-*> "), 140)
        break
    out["imports"] = [l for l in dict.fromkeys(MD_LINK.findall(body)) if _is_local_ref(l)][:40]
    return out


def _loads_loose(text):
    try:
        return json.loads(text)
    except Exception:
        pass
    t = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    t = re.sub(r"(?m)^\s*//.*$", "", t)
    t = re.sub(r",(\s*[}\]])", r"\1", t)
    try:
        return json.loads(t)
    except Exception:
        return None


def parse_json(text, rel):
    name = posixpath.basename(rel).lower()
    data = _loads_loose(text) if len(text) < 3_000_000 else None
    out = {}
    if isinstance(data, dict) and name == "package.json":
        deps = list((data.get("dependencies") or {}).keys())
        dev = list((data.get("devDependencies") or {}).keys())
        scripts = data.get("scripts") or {}
        out["pkg"] = {"name": str(data.get("name") or ""), "scripts": {k: short(v, 90) for k, v in list(scripts.items())[:25]}}
        out["deps"] = deps + dev
        if data.get("name"):
            out["title"] = str(data["name"])
        if data.get("description"):
            out["doc"] = short(data["description"], 140)
        refs = []
        if isinstance(data.get("main"), str):
            refs.append(data["main"])
        bins = data.get("bin")
        refs += list(bins.values()) if isinstance(bins, dict) else ([bins] if isinstance(bins, str) else [])
        for cmd in scripts.values():
            refs += re.findall(r"(?:node|tsx|ts-node|bun|deno run|python3?|py)\s+(?:-[\w-]+\s+)*([\w./\\-]+\.(?:m?js|cjs|ts|py))", str(cmd))
        out["imports"] = list(dict.fromkeys(r for r in refs if isinstance(r, str)))
    elif isinstance(data, dict) and name == "manifest.json" and "manifest_version" in data:
        refs = []
        bg = data.get("background") or {}
        if bg.get("service_worker"):
            refs.append(bg["service_worker"])
        refs += bg.get("scripts", []) or []
        for cs in data.get("content_scripts", []) or []:
            refs += (cs.get("js") or []) + (cs.get("css") or [])
        action = data.get("action") or data.get("browser_action") or {}
        for key in ("default_popup",):
            if action.get(key):
                refs.append(action[key])
        if data.get("options_page"):
            refs.append(data["options_page"])
        out["title"] = f"Extension navigateur « {data.get('name', '?')} » (MV{data.get('manifest_version')})"
        out["imports"] = [r for r in refs if isinstance(r, str)]
    elif isinstance(data, dict) and name in ("tsconfig.json", "jsconfig.json"):
        co = data.get("compilerOptions") or {}
        if co.get("paths"):
            out["paths"] = {"baseUrl": co.get("baseUrl"), "paths": co.get("paths")}
    elif isinstance(data, dict) and name == "composer.json":
        out["deps"] = list((data.get("require") or {}).keys())
        out["title"] = str(data.get("name") or "")
    elif isinstance(data, dict) and isinstance(data.get("sections"), dict) and ("templates/" in rel or "sections/" in rel):
        out["imports"] = list(dict.fromkeys(f"liquid:section:{v.get('type')}" for v in data["sections"].values()
                                            if isinstance(v, dict) and v.get("type")))
    elif isinstance(data, dict):
        out["doc"] = "clés : " + ", ".join(list(data.keys())[:10])
    elif isinstance(data, list):
        out["doc"] = f"liste de {len(data)} éléments"
    return out


TOP_KEY = re.compile(r"^([A-Za-z_][\w.\-]*)\s*[:=]", re.M)
TOML_SECTION = re.compile(r"^\[([^\]\n]+)\]", re.M)


def parse_config(text, rel):
    name = posixpath.basename(rel).lower()
    keys = list(dict.fromkeys(TOP_KEY.findall(text)))
    secs = TOML_SECTION.findall(text)
    out = {"doc": short("clés : " + ", ".join(keys[:10]) + (" · sections : " + ", ".join(secs[:8]) if secs else ""), 160)}
    if name == "pyproject.toml":
        deps = []
        m = re.search(r"(?ms)^dependencies\s*=\s*\[(.*?)\]", text)
        if m:
            deps += re.findall(r"['\"]\s*([A-Za-z0-9_.\-]+)", m.group(1))
        m = re.search(r"(?ms)^\[tool\.poetry\.dependencies\](.*?)(?=^\[|\Z)", text)
        if m:
            deps += [k for k in re.findall(r"(?m)^([A-Za-z0-9_.\-]+)\s*=", m.group(1)) if k.lower() != "python"]
        out["deps"] = list(dict.fromkeys(deps))
        nm = re.search(r'(?m)^name\s*=\s*"([^"]+)"', text)
        if nm:
            out["title"] = nm.group(1)
    elif name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        m = re.search(r"(?ms)^services:\s*\n(.*?)(?=^\S|\Z)", text)
        if m:
            services = re.findall(r"(?m)^  ([\w\-]+):", m.group(1))
            out["doc"] = "services : " + ", ".join(services[:12])
    elif rel.startswith(".github/workflows/"):
        nm = re.search(r"(?m)^name:\s*(.+)$", text)
        out["title"] = "CI : " + (nm.group(1).strip() if nm else posixpath.basename(rel))
    return out


def parse_requirements(text, rel):
    deps = []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        m = re.match(r"([A-Za-z0-9_.\-]+)", line)
        if m:
            deps.append(m.group(1))
    return {"deps": deps, "doc": "dépendances : " + ", ".join(deps[:12])}


def parse_env_names(text, rel):
    names = re.findall(r"(?m)^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", text)
    return {"env": names[:60], "doc": f"{len(names)} variables (noms seulement)"}


def parse_csv(text, rel):
    first = text.split("\n", 1)[0].strip()
    return {"doc": f"{_n(text.count(chr(10)))} lignes · colonnes : {short(first, 160)}"}


def parse_notebook(text, rel):
    data = _loads_loose(text) if len(text) < 6_000_000 else None
    if not isinstance(data, dict):
        return {}
    cells = data.get("cells") or []

    def src(c):
        s = c.get("source") or ""
        return "".join(s) if isinstance(s, list) else str(s)

    code = "\n".join(src(c) for c in cells if c.get("cell_type") == "code")
    md = "\n".join(src(c) for c in cells if c.get("cell_type") == "markdown")
    out = {"doc": f"notebook : {len(cells)} cellules",
           "imports": list(dict.fromkeys(re.findall(r"(?m)^\s*(?:import|from)\s+([\w.]+)", code)))[:40],
           "symbols": [{"n": n, "k": "fn", "l": 0} for n in re.findall(r"(?m)^def\s+(\w+)", code)][:30]}
    h = re.search(r"(?m)^#\s+(.+)$", md)
    if h:
        out["title"] = short(h.group(1), 90)
    return out


def parse_xml(text, rel):
    m = re.search(r"<([A-Za-z_][\w:.\-]*)[\s>/]", re.sub(r"<\?.*?\?>|<!--.*?-->|<!DOCTYPE[^>]*>", "", text[:5000], flags=re.S))
    return {"doc": f"XML <{m.group(1)}>"} if m else {}


def parse_text(text, rel):
    line = first_line(text, 140)
    return {"doc": line} if line else {}


def parse_docx(path):
    out = {}
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "docProps/core.xml" in names:
                core = z.read("docProps/core.xml").decode("utf-8", "replace")
                m = re.search(r"<dc:title>(.*?)</dc:title>", core, re.S)
                if m and m.group(1).strip():
                    out["title"] = short(html.unescape(m.group(1)), 100)
            if "word/document.xml" in names:
                with z.open("word/document.xml") as fh:
                    xml = fh.read(3_000_000).decode("utf-8", "replace")
                paras = []
                for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)[:600]:
                    t = html.unescape("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))).strip()
                    if t:
                        st = re.search(r'<w:pStyle w:val="([^"]+)"', p)
                        paras.append((st.group(1) if st else "", t))
                heads = [t for s, t in paras if re.match(r"(?i)(heading|titre|title|berschrift)", s)]
                if not out.get("title") and paras:
                    out["title"] = short(heads[0] if heads else paras[0][1], 100)
                out["headings"] = ["## " + short(h, 80) for h in heads[:12]]
                body = next((t for s, t in paras if len(t) > 40), "")
                if body:
                    out["doc"] = short(body, 140)
                out["words"] = sum(len(t.split()) for _, t in paras)
    except Exception as exc:
        out["err"] = short(repr(exc), 80)
    return out


def parse_xlsx(path):
    out = {}
    try:
        with zipfile.ZipFile(path) as z:
            wb = z.read("xl/workbook.xml").decode("utf-8", "replace")
            sheets = [html.unescape(s) for s in re.findall(r'<sheet\b[^>]*\bname="([^"]+)"', wb)]
            out["sheets"] = sheets[:30]
            out["doc"] = f"{len(sheets)} feuille(s) : " + ", ".join(sheets[:8])
    except Exception as exc:
        out["err"] = short(repr(exc), 80)
    return out


def parse_pptx(path):
    out = {}
    try:
        with zipfile.ZipFile(path) as z:
            slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                            key=lambda n: int(re.findall(r"\d+", n)[-1]))
            out["doc"] = f"{len(slides)} diapositives"
            titles = []
            for s in slides[:12]:
                texts = re.findall(r"<a:t>([^<]*)</a:t>", z.read(s).decode("utf-8", "replace"))
                if texts:
                    titles.append(short(html.unescape(" ".join(texts[:3])), 70))
            if titles:
                out["title"] = titles[0]
                out["headings"] = ["## " + t for t in titles[:10]]
    except Exception as exc:
        out["err"] = short(repr(exc), 80)
    return out


def parse_pdf(path, size):
    out = {}
    try:
        with open(path, "rb") as fh:
            head = fh.read(min(size, 6_000_000))
        m = re.search(rb"/Title\s*\(([^)]{1,300})\)", head)
        if m:
            raw = m.group(1)
            title = raw[2:].decode("utf-16-be", "replace") if raw.startswith(b"\xfe\xff") else raw.decode("latin-1", "replace")
            if title.strip():
                out["title"] = short(title, 100)
        pages = len(re.findall(rb"/Type\s*/Page[^s]", head))
        if pages:
            out["doc"] = f"{pages} page(s)" + ("" if size <= 6_000_000 else "+")
    except OSError:
        pass
    return out


def _rx(pats):
    return [(re.compile(p, re.M), k) for p, k in pats]


GENERIC = {
    "php": (_rx([(r"^\s*(?:abstract\s+|final\s+)?class\s+(\w+)", "class"), (r"^\s*(?:interface|trait|enum)\s+(\w+)", "type"),
                 (r"^\s*(?:(?:public|private|protected|static|final|abstract)\s+)*function\s+&?(\w+)", "fn")]),
            [r"""(?:require|include)(?:_once)?\s*\(?\s*(?:__DIR__\s*\.\s*)?['"]([^'"]+)['"]"""]),
    "ruby": (_rx([(r"^\s*class\s+([\w:]+)", "class"), (r"^\s*module\s+([\w:]+)", "type"), (r"^\s*def\s+(?:self\.)?([\w?!=]+)", "fn")]),
             [r"""require_relative\s+['"]([^'"]+)['"]"""]),
    "go": (_rx([(r"^func\s+(?:\([^)]*\)\s*)?(\w+)", "fn"), (r"^type\s+(\w+)\s+(?:struct|interface)", "type")]),
           [r"""^\s*(?:import\s+)?(?:\w+\s+)?"([\w.\-/]+)"\s*$"""]),
    "rust": (_rx([(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(\w+)", "fn"),
                  (r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|union)\s+(\w+)", "type"),
                  (r"^\s*(?:pub\s+)?mod\s+(\w+)", "mod")]),
             [r"^\s*(?:pub\s+)?mod\s+(\w+)\s*;", r"^\s*use\s+((?:crate|self|super)::[\w:]+)"]),
    "java": (_rx([(r"^\s*(?:(?:public|protected|private|abstract|final|static)\s+)*(?:class|interface|enum|record)\s+(\w+)", "class"),
                  (r"^\s+(?:(?:public|protected|private|static|final|synchronized|abstract)\s+)+[\w<>\[\], ]+\s+(\w+)\s*\(", "fn")]),
             [r"^\s*import\s+(?:static\s+)?([\w.]+)"]),
    "kotlin": (_rx([(r"^\s*(?:(?:data|sealed|open|abstract|private|internal)\s+)*(?:class|interface|object)\s+(\w+)", "class"),
                    (r"^\s*(?:(?:private|public|internal|override|suspend|inline)\s+)*fun\s+(?:<[^>]+>\s*)?(?:[\w.]+\.)?(\w+)", "fn")]),
               [r"^\s*import\s+([\w.]+)"]),
    "csharp": (_rx([(r"^\s*(?:(?:public|private|protected|internal|static|sealed|abstract|partial)\s+)*(?:class|interface|struct|enum|record)\s+(\w+)", "class"),
                    (r"^\s+(?:(?:public|private|protected|internal|static|virtual|override|async|abstract)\s+)+[\w<>\[\],? ]+\s+(\w+)\s*\(", "fn")]),
               []),
    "c": (_rx([(r"^[A-Za-z_][\w \t\*]{0,80}?\b([A-Za-z_]\w*)\s*\([^;{)\n]{0,200}\)\s*\{", "fn"), (r"^\s*(?:typedef\s+)?struct\s+(\w+)", "type")]),
          [r"""#\s*include\s*"([^"]+)\""""]),
    "cpp": (_rx([(r"^\s*(?:class|struct)\s+(\w+)", "class"), (r"^[A-Za-z_][\w \t\*&:<>,]{0,100}?\b([A-Za-z_]\w*)\s*\([^;{)\n]{0,200}\)\s*(?:const\s*)?\{", "fn")]),
            [r"""#\s*include\s*"([^"]+)\""""]),
    "swift": (_rx([(r"^\s*(?:(?:public|private|internal|open|final)\s+)*(?:class|struct|protocol|enum|extension)\s+(\w+)", "class"),
                   (r"^\s*(?:(?:public|private|internal|open|static|override|@\w+)\s+)*func\s+(\w+)", "fn")]), []),
    "dart": (_rx([(r"^\s*(?:abstract\s+)?class\s+(\w+)", "class"), (r"^\s*(?:[\w<>?]+\s+)?(\w+)\s*\([^)\n]*\)\s*(?:async\s*)?\{", "fn")]),
             [r"""^\s*import\s+['"]([^'"]+)['"]"""]),
    "lua": (_rx([(r"^\s*(?:local\s+)?function\s+([\w.:]+)", "fn")]), [r"""require\s*\(?\s*['"]([^'"]+)['"]"""]),
    "shell": (_rx([(r"^\s*(?:function\s+)?([\w\-]+)\s*\(\)\s*\{", "fn"), (r"^\s*function\s+([\w\-]+)", "fn")]),
              [r"""^\s*(?:source|\.)\s+['"]?([^'"\s;]+)"""]),
    "powershell": (_rx([(r"^\s*function\s+([\w\-]+)", "fn")]), [r"""^\s*\.\s+['"]?([^'"\s]+\.ps1)"""]),
    "batch": (_rx([(r"^:(\w+)", "label")]), [r"""(?i)^\s*call\s+['"]?([^'"\s]+\.(?:bat|cmd))"""]),
    "sql": (_rx([(r"(?i)^\s*create\s+(?:or\s+replace\s+)?(?:table|view|function|procedure|trigger|index)\s+(?:if\s+not\s+exists\s+)?([\w.\"`\[\]]+)", "table")]), []),
    "make": (_rx([(r"^([\w\-.]+)\s*:(?!=)", "target")]), []),
    "docker": ([], []),
    "python_fallback": (_rx([(r"^\s*def\s+(\w+)", "fn"), (r"^\s*class\s+(\w+)", "class")]),
                        [r"^\s*from\s+(\.*[\w.]*)\s+import", r"^\s*import\s+([\w.]+)"]),
}
GENERIC = {k: (pats, [re.compile(p, re.M) for p in imps]) for k, (pats, imps) in GENERIC.items()}


def parse_generic(text, rel, lang):
    pats, imps = GENERIC.get(lang, ([], []))
    out = {"symbols": _syms(text, pats, Lines(text)), "doc": leading_doc(text)}
    imports = []
    for rx in imps:
        for m in rx.finditer(text):
            spec = next((g for g in m.groups() if g), None)
            if spec:
                imports.append(spec)
    out["imports"] = list(dict.fromkeys(imports))[:80]
    if lang == "docker":
        frm = re.findall(r"(?im)^FROM\s+(\S+)", text)
        cmd = re.findall(r"(?im)^(?:CMD|ENTRYPOINT)\s+(.+)$", text)
        out["doc"] = short(("image " + ", ".join(frm[:2]) if frm else "") + (" · " + cmd[-1] if cmd else ""), 140)
    return out


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
NOT_ISOLATED = re.compile(r"(^|/)(__init__\.py|__main__\.py|setup\.py|conftest\.py|manage\.py|[\w.-]+\.config\.[cm]?[jt]s|"
                          r"[\w.-]+\.d\.ts|\.eslintrc\.[cm]?js)$")


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


def process_file(root, rel, prev, max_bytes, size=None, mtime=None):
    """→ (fiche, a_été_parsé) ou None si illisible."""
    path = os.path.join(root, rel)
    if size is None or mtime is None:
        try:
            st = os.stat(path)
        except OSError:
            return None
        size, mtime = st.st_size, int(st.st_mtime)
    if prev and prev.get("size") == size and prev.get("mtime") == mtime and prev.get("v") == PARSER_VERSION:
        return dict(prev), False
    name = posixpath.basename(rel)
    lang = classify(rel)
    ext = posixpath.splitext(name.lower())[1]
    rec = {"v": PARSER_VERSION, "size": size, "mtime": mtime, "lang": lang or ("asset" if ext in ASSET_EXT else "other")}
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
        prev.update(size=size, mtime=mtime)
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


def walk(root, max_files):
    """Parcours en largeur (niveau par niveau) : si la limite est atteinte, ce sont les profondeurs qui sont
    tronquées, pas des dossiers entiers. → [(chemin relatif, taille, mtime)], tronqué ?"""
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
        for e in entries:
            name = e.name
            rel = f"{rel_dir}/{name}" if rel_dir else name
            try:
                if e.is_symlink() or isjunction(e.path):
                    continue
                if e.is_dir():
                    if not (name in IGNORE_DIRS or (name.startswith(".") and name not in KEEP_DOT_DIRS) or ignored(rel, True)):
                        subdirs.append(rel)
                    continue
                if name.lower() in JUNK_FILES or name.startswith("~$") or ignored(rel, False):
                    continue
                st = e.stat()
            except OSError:
                continue
            files.append((rel, st.st_size, int(st.st_mtime)))
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


# =============================================================================================== résolution
NODE_BUILTINS = {"fs", "path", "os", "http", "https", "url", "util", "crypto", "stream", "events", "child_process",
                 "buffer", "zlib", "net", "tls", "dns", "readline", "assert", "querystring", "worker_threads",
                 "cluster", "timers", "process", "module", "vm", "perf_hooks", "string_decoder", "tty", "dgram",
                 "v8", "async_hooks", "inspector", "constants", "punycode", "test"}
JS_EXTS = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".json", ".d.ts", ".css", ".scss")
JS_INDEX = ("/index.ts", "/index.tsx", "/index.js", "/index.jsx", "/index.mjs", "/index.vue", "/index.svelte")
STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}


class Resolver:
    def __init__(self, files):
        self.files = files
        self.exact = set(files)
        self.lower = {k.lower(): k for k in files}
        self.by_name = defaultdict(list)
        for k in files:
            self.by_name[posixpath.basename(k).lower()].append(k)
        self.py_roots = [""] + [d + "/" for d in ("src", "app", "lib", "backend", "server")
                                if any(k.startswith(d + "/") for k in files)]
        self.aliases = self._aliases()
        self.alias_prefixes = tuple(a for a, _ in self.aliases)

    def has(self, p):
        if p in self.exact:
            return p
        return self.lower.get(p.lower())

    def _aliases(self):
        al = []
        for rel, f in self.files.items():
            pa = f.get("paths")
            if not pa:
                continue
            baseurl = posixpath.normpath(posixpath.join(posixpath.dirname(rel), pa.get("baseUrl") or "."))
            for key, targets in (pa.get("paths") or {}).items():
                prefix = key.rstrip("*")
                for t in targets if isinstance(targets, list) else [targets]:
                    tp = posixpath.normpath(posixpath.join(baseurl, str(t).rstrip("*")))
                    tp = "" if tp == "." else tp
                    al.append((prefix, tp + "/" if tp and str(t).endswith("/*") else tp))
        if any(k.startswith("src/") for k in self.files):
            al += [("@/", "src/"), ("~/", "src/")]
        al.sort(key=lambda x: -len(x[0]))
        return al

    def try_js(self, base):
        base = posixpath.normpath(base) if base else base
        if not base or base.startswith("..") or base == ".":
            return None
        for ext in JS_EXTS:
            hit = self.has(base + ext)
            if hit:
                return hit
        for idx in JS_INDEX:
            hit = self.has(base + idx)
            if hit:
                return hit
        if base.endswith((".js", ".jsx", ".mjs")):
            stem = base.rsplit(".", 1)[0]
            for ext in (".ts", ".tsx", ".mts"):
                hit = self.has(stem + ext)
                if hit:
                    return hit
        return None

    def js(self, rel, spec):
        if spec.startswith("."):
            return self.try_js(posixpath.join(posixpath.dirname(rel), spec)), None
        if spec.startswith("/"):
            return self.try_js(spec.lstrip("/")) or self.try_js("public/" + spec.lstrip("/")), None
        if self.alias_prefixes and spec.startswith(self.alias_prefixes):
            for prefix, target in self.aliases:
                if spec.startswith(prefix):
                    hit = self.try_js(target + spec[len(prefix):])
                    if hit:
                        return hit, None
            if spec.startswith(("@/", "~/")):
                return None, None
        if re.match(r"^[a-z][a-z0-9+.-]*:", spec):
            return None, None
        pkg = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
        if pkg in NODE_BUILTINS:
            return None, None
        return None, pkg

    def _try_py(self, cand):
        cand = cand.strip("/")
        if not cand:
            return None
        return self.has(cand + ".py") or self.has(cand + "/__init__.py")

    def py(self, rel, spec):
        if spec.startswith("."):
            level = len(spec) - len(spec.lstrip("."))
            parts = [p for p in spec[level:].split(".") if p]
            base = posixpath.dirname(rel)
            for _ in range(level - 1):
                base = posixpath.dirname(base)
            return self._try_py(posixpath.join(base, *parts) if parts else base), None
        parts = spec.split(".")
        here = posixpath.dirname(rel)
        for root in self.py_roots + ([here + "/"] if here else []):
            hit = self._try_py(root + "/".join(parts))
            if hit:
                return hit, None
        top = parts[0]
        if top in STDLIB:
            return None, None
        return None, top

    def path(self, rel, spec):
        spec = urllib.parse.unquote(spec.split("#")[0].split("?")[0].strip())
        if not spec:
            return None
        cand = posixpath.normpath(spec.lstrip("/") if spec.startswith("/") else posixpath.join(posixpath.dirname(rel), spec))
        if cand.startswith(".."):
            return None
        hit = self.has(cand)
        if hit:
            return hit
        hits = self.by_name.get(posixpath.basename(cand).lower(), [])
        return hits[0] if len(hits) == 1 else None

    def liquid(self, spec):
        _, kind, name = spec.split(":", 2)
        if kind == "asset":
            cands = [f"assets/{name}"]
        elif kind == "sections":
            cands = [f"sections/{name}.json", f"sections/{name}.liquid"]
        else:
            folder = "sections" if kind == "section" else "snippets"
            cands = [f"{folder}/{name}" if name.endswith(".liquid") else f"{folder}/{name}.liquid"]
        for c in cands:
            hit = self.has(c)
            if hit:
                return hit
        hits = self.by_name.get(posixpath.basename(cands[0]).lower(), [])
        return hits[0] if hits else None

    def module(self, rel, spec, lang):
        if lang in ("java", "kotlin"):
            tail = spec.replace(".", "/")
            for ext in (".java", ".kt", ".scala"):
                for k in self.by_name.get(posixpath.basename(tail).lower() + ext, []):
                    if k.lower().endswith((tail + ext).lower()):
                        return k
            return None
        if lang == "rust":
            parts = [p for p in spec.split("::") if p not in ("crate", "self", "super")]
            if not parts:
                return None
            for bd in (posixpath.dirname(rel), "src"):
                for n in range(len(parts), 0, -1):
                    cand = posixpath.join(bd, *parts[:n]) if bd else "/".join(parts[:n])
                    hit = self.has(cand + ".rs") or self.has(cand + "/mod.rs")
                    if hit:
                        return hit
        return None


def resolve(files):
    R = Resolver(files)
    for rel, f in files.items():
        imps = f.get("imports") or []
        if not imps:
            continue
        lang = f.get("lang")
        out, ext = [], []
        for spec in imps:
            hit = pkg = None
            try:
                if spec.startswith("liquid:"):
                    hit = R.liquid(spec)
                elif lang in ("python", "notebook"):
                    hit, pkg = R.py(rel, spec)
                elif lang in ("js", "ts", "vue", "svelte"):
                    hit, pkg = R.js(rel, spec)
                elif lang == "json":
                    hit = R.path(rel, spec) or R.try_js(posixpath.join(posixpath.dirname(rel), spec))
                elif lang in ("java", "kotlin", "rust"):
                    hit = R.module(rel, spec, lang)
                elif lang in ("go", "csharp", "swift"):
                    hit = None
                else:
                    hit = R.path(rel, spec)
            except Exception:
                hit = pkg = None
            if hit and hit != rel:
                out.append(hit)
            elif pkg:
                ext.append(pkg)
        if out:
            f["out"] = sorted(set(out))
        if ext:
            f["ext"] = sorted(set(ext))
    return files


# =============================================================================================== analyse du graphe
def pagerank(nodes, out_edges, d=0.85, iters=40):
    nodes = sorted(nodes)
    n = len(nodes)
    if not n:
        return {}
    idx = {k: i for i, k in enumerate(nodes)}
    outs = [[idx[t] for t in out_edges.get(k, ()) if t in idx] for k in nodes]
    pr = [1.0 / n] * n
    for _ in range(iters):
        nxt = [(1 - d) / n] * n
        dangling = sum(pr[i] for i in range(n) if not outs[i])
        for i in range(n):
            if outs[i]:
                share = d * pr[i] / len(outs[i])
                for j in outs[i]:
                    nxt[j] += share
        add = d * dangling / n
        pr = [x + add for x in nxt]
    return {k: pr[idx[k]] for k in nodes}


def communities(nodes, out_edges, max_iter=15):
    """Propagation de labels (déterministe), initialisée par dossier → modules lisibles."""
    nodes = sorted(nodes)
    adj = {k: set() for k in nodes}
    for a in nodes:
        for b in out_edges.get(a, ()):
            if b in adj and b != a:
                adj[a].add(b)
                adj[b].add(a)
    label = {k: posixpath.dirname(k) for k in nodes}
    for _ in range(max_iter):
        changed = 0
        for k in nodes:
            if not adj[k]:
                continue
            cnt = Counter(label[m] for m in adj[k])
            cnt[label[k]] += 0.5
            best = max(cnt.items(), key=lambda kv: (kv[1], kv[0] == label[k], kv[0]))[0]
            if best != label[k]:
                label[k] = best
                changed += 1
        if not changed:
            break
    groups = defaultdict(list)
    for k in nodes:
        groups[label[k]].append(k)
    return dict(groups)


def cycles(nodes, out_edges, limit=6):
    """Composantes fortement connexes (Tarjan itératif) de taille > 1 = cycles d'imports."""
    index, low, on, stack, res = {}, {}, set(), [], []
    counter = 0
    for start in sorted(nodes):
        if start in index:
            continue
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on.add(start)
        work = [(start, iter(out_edges.get(start, ())))]
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in nodes:
                    continue
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(out_edges.get(w, ()))))
                    advanced = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    res.append(sorted(comp))
    res.sort(key=len)
    return res[:limit]


def analyze(files):
    out_edges = {rel: f["out"] for rel, f in files.items() if f.get("out")}
    in_edges = defaultdict(list)
    for a, outs in out_edges.items():
        for b in outs:
            in_edges[b].append(a)
    part = set(out_edges) | set(in_edges)
    return in_edges, pagerank(part, out_edges), communities(part, out_edges), cycles(part, out_edges)


FW_JS = {
    "react": "React", "next": "Next.js", "vue": "Vue", "nuxt": "Nuxt", "svelte": "Svelte", "@sveltejs/kit": "SvelteKit",
    "@angular/core": "Angular", "express": "Express", "fastify": "Fastify", "koa": "Koa", "@nestjs/core": "NestJS",
    "vite": "Vite", "webpack": "Webpack", "tailwindcss": "Tailwind", "@prisma/client": "Prisma", "prisma": "Prisma",
    "mongoose": "Mongoose", "sequelize": "Sequelize", "typeorm": "TypeORM", "drizzle-orm": "Drizzle",
    "electron": "Electron", "react-native": "React Native", "expo": "Expo", "jest": "Jest", "vitest": "Vitest",
    "@playwright/test": "Playwright", "playwright": "Playwright", "puppeteer": "Puppeteer", "cypress": "Cypress",
    "axios": "axios", "socket.io": "Socket.IO", "stripe": "Stripe", "@shopify/shopify-api": "Shopify API",
    "@shopify/hydrogen": "Hydrogen", "@shopify/polaris": "Polaris", "@supabase/supabase-js": "Supabase",
    "firebase": "Firebase", "openai": "OpenAI", "@anthropic-ai/sdk": "Anthropic SDK", "langchain": "LangChain",
    "discord.js": "discord.js", "telegraf": "Telegraf", "three": "three.js", "jquery": "jQuery",
    "bootstrap": "Bootstrap", "chart.js": "Chart.js", "zod": "Zod", "hono": "Hono", "astro": "Astro",
    "@remix-run/react": "Remix", "@reduxjs/toolkit": "Redux Toolkit", "redux": "Redux", "zustand": "Zustand",
    "@tanstack/react-query": "React Query", "graphql": "GraphQL", "@apollo/client": "Apollo",
    "node-cron": "node-cron", "nodemailer": "Nodemailer", "cheerio": "Cheerio", "typescript": "TypeScript",
}
FW_PY = {
    "flask": "Flask", "django": "Django", "fastapi": "FastAPI", "streamlit": "Streamlit", "gradio": "Gradio",
    "pandas": "pandas", "numpy": "NumPy", "selenium": "Selenium", "playwright": "Playwright", "requests": "requests",
    "httpx": "httpx", "aiohttp": "aiohttp", "bs4": "BeautifulSoup", "beautifulsoup4": "BeautifulSoup",
    "scrapy": "Scrapy", "sqlalchemy": "SQLAlchemy", "pydantic": "Pydantic", "openai": "OpenAI",
    "anthropic": "Anthropic SDK", "langchain": "LangChain", "torch": "PyTorch", "tensorflow": "TensorFlow",
    "sklearn": "scikit-learn", "scikit-learn": "scikit-learn", "discord": "discord.py",
    "telegram": "python-telegram-bot", "python-telegram-bot": "python-telegram-bot", "aiogram": "aiogram",
    "pyqt5": "PyQt", "pyqt6": "PyQt", "pyside6": "PySide", "ccxt": "ccxt", "yfinance": "yfinance",
    "matplotlib": "matplotlib", "plotly": "Plotly", "celery": "Celery", "redis": "Redis", "pymongo": "MongoDB",
    "psycopg2": "PostgreSQL", "psycopg": "PostgreSQL", "pytest": "pytest", "uvicorn": "Uvicorn",
    "dotenv": "python-dotenv", "python-dotenv": "python-dotenv", "openpyxl": "openpyxl", "pil": "Pillow",
    "pillow": "Pillow", "cv2": "OpenCV", "opencv-python": "OpenCV", "pyautogui": "PyAutoGUI",
    "undetected_chromedriver": "undetected-chromedriver", "shopify": "ShopifyAPI", "stripe": "Stripe",
    "ollama": "Ollama", "transformers": "Transformers", "yaml": "PyYAML", "pyyaml": "PyYAML", "click": "Click",
    "typer": "Typer", "rich": "Rich", "apscheduler": "APScheduler", "gspread": "gspread",
    "googleapiclient": "Google API", "boto3": "AWS", "supabase": "Supabase", "firebase_admin": "Firebase",
}


def detect_stack(files):
    langs = Counter()
    for f in files.values():
        if f.get("lang") in CODE and f.get("lines"):
            langs[f["lang"]] += f["lines"]
    total = sum(langs.values()) or 1
    lang_txt = [f"{LANG_LABEL.get(l, l)} {round(100 * n / total)}%" for l, n in langs.most_common(5) if n / total >= 0.03]
    js, py = set(), set()
    for rel, f in files.items():
        lang = f.get("lang")
        if lang == "json" and posixpath.basename(rel) == "package.json":
            js |= set(f.get("deps", []))
        elif lang in ("requirements", "toml"):
            py |= {d.lower() for d in f.get("deps", [])}
        elif lang in ("python", "notebook"):
            py |= {e.lower() for e in f.get("ext", [])}
        elif lang in ("js", "ts", "vue", "svelte"):
            js |= set(f.get("ext", []))
    fws = list(dict.fromkeys([FW_JS[d] for d in sorted(js) if d in FW_JS] + [FW_PY[d] for d in sorted(py) if d in FW_PY]))
    names = {posixpath.basename(r).lower() for r in files}
    infra = []
    if "dockerfile" in names:
        infra.append("Docker")
    if names & {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
        infra.append("Compose")
    if any(r.startswith(".github/workflows/") for r in files):
        infra.append("GitHub Actions")
    for fname, label in (("vercel.json", "Vercel"), ("netlify.toml", "Netlify"), ("procfile", "Procfile")):
        if fname in names:
            infra.append(label)
    kinds = []
    if "layout/theme.liquid" in files or "config/settings_schema.json" in files:
        kinds.append("Thème Shopify")
    if any(str(f.get("title", "")).startswith("Extension navigateur") for f in files.values()):
        kinds.append("Extension navigateur")
    if any(f.get("lang") == "notebook" for f in files.values()):
        kinds.append("Notebooks")
    count = Counter(_kind(f) for f in files.values())
    if count["doc"] + count["data"] > max(5, 2 * count["code"]):
        kinds.append("Dossier surtout documentaire")
    summary = " · ".join(lang_txt + fws[:12] + infra + kinds)
    return {"langs": lang_txt, "frameworks": fws, "infra": infra, "kinds": kinds, "summary": summary}


ENTRY_STEMS = {"main", "index", "app", "server", "cli", "manage", "run", "bot", "wsgi", "asgi", "start", "__main__"}


def entry_points(files):
    eps = []

    def add(rel, why):
        if rel in files and all(rel != e for e, _ in eps):
            eps.append((rel, why))

    by_depth = sorted(files.items(), key=lambda kv: (kv[0].count("/"), kv[0]))
    for rel, f in by_depth:
        base = posixpath.basename(rel)
        if base in ("package.json", "manifest.json") and f.get("out") and not f.get("dup"):
            for o in f["out"]:
                add(o, "package.json" if base == "package.json" else "manifest")
    for rel, f in [kv for kv in by_depth if kv[1].get("main") and not kv[1].get("dup")][:6]:
        add(rel, "__main__")
    for rel, f in by_depth:
        if f.get("dup"):
            continue
        d = posixpath.dirname(rel)
        base = posixpath.basename(rel).lower()
        stem = posixpath.splitext(base)[0]
        if d in ("", "src", "app", "server", "backend", "cmd") and stem in ENTRY_STEMS and f.get("lang") in CODE - {"html", "css"}:
            add(rel, "nom")
        elif base == "index.html" and d in ("", "public", "src"):
            add(rel, "page")
        elif rel == "layout/theme.liquid":
            add(rel, "thème Shopify")
        elif base == "dockerfile":
            add(rel, "docker")
    return eps[:12]


def _kind(f):
    lang = f.get("lang")
    if lang in CODE:
        return "code"
    if lang in DOCS:
        return "doc"
    if lang in DATA:
        return "data"
    if lang in ("asset", "binary"):
        return "asset"
    return "other"


def file_desc(f, n_syms=5) -> str:
    bits = []
    head = f.get("title") or f.get("doc")
    if head:
        bits.append(short(head, 80))
    syms = [s["n"] for s in (f.get("symbols") or []) if s.get("k") not in ("method", "const")][:n_syms]
    if syms:
        bits.append(", ".join(syms))
    if f.get("routes"):
        bits.append("routes " + ", ".join(f["routes"][:3]))
    if not head and f.get("headings"):
        bits.append(" / ".join(h.lstrip("# ") for h in f["headings"][:3]))
    if f.get("sensitive"):
        bits.append("sensible (non lu)")
    if not bits:
        bits.append(LANG_LABEL.get(f.get("lang"), f.get("lang") or "?") + (f", {f['lines']} l." if f.get("lines") else ""))
    return " · ".join(bits)


# =============================================================================================== rapports
def tree_lines(files, depth=2, max_lines=45):
    count, exts = Counter(), defaultdict(Counter)
    for rel in files:
        parts = rel.split("/")
        for d in range(1, min(len(parts), depth + 1)):
            key = "/".join(parts[:d])
            count[key] += 1
            exts[key][posixpath.splitext(parts[-1])[1].lower() or "(sans ext.)"] += 1
    lines = []
    for d in sorted(count):
        detail = ", ".join(f"{n} {e}" for e, n in exts[d].most_common(3))
        lines.append(f"{'  ' * d.count('/')}- `{posixpath.basename(d)}/` ({count[d]} : {detail})")
        if len(lines) >= max_lines:
            lines.append("  - …")
            break
    root_files = sorted(r for r in files if "/" not in r)
    if root_files:
        more = f" … +{len(root_files) - 15}" if len(root_files) > 15 else ""
        lines.append("- racine : " + ", ".join(f"`{r}`" for r in root_files[:15]) + more)
    return lines


def cross_links(files, comms):
    label = {m: lab for lab, mem in comms.items() for m in mem}
    pairs = {}
    for rel, f in files.items():
        a = label.get(rel)
        for t in f.get("out", []):
            b = label.get(t)
            if a is None or b is None or a == b:
                continue
            n, ex = pairs.get((a, b), (0, (rel, t)))
            pairs[(a, b)] = (n + 1, ex)
    return sorted(pairs.items(), key=lambda kv: -kv[1][0])


from .filesearch import BACKUP_RX, build_cache, needs_refresh, recall_files, search_files  # noqa: E402,F401


def _weight(rel, pr):
    """Centralité ajustée : les dossiers de sauvegarde/export/archive comptent peu dans les classements."""
    return pr.get(rel, 0) * (0.1 if BACKUP_RX.search(rel) else 1.0)


def _ranked(files, pr, langs, limit):
    return [r for r in sorted(pr, key=lambda r: -_weight(r, pr))
            if files.get(r, {}).get("lang") in langs and not files[r].get("dup")][:limit]


def _socle(files, limit=4):
    """Socle (façon graphify « god nodes ») : fichiers de code importés partout qui n'importent presque rien
    (utilitaires communs). Montrés à part pour ne pas chasser les vrais fichiers clés du classement."""
    code = {r for r, f in files.items() if f.get("lang") in CODE and not f.get("dup")}
    indeg, linked = Counter(), set()
    for r in code:
        outs = [t for t in files[r].get("out") or [] if t in code]
        if outs:
            linked.add(r)
            linked.update(outs)
            if not _is_test(r):
                indeg.update(outs)
    if len(linked) < 6:
        return []
    need = max(3, -(-len(linked) * 15 // 100))  # importé par au moins 15 % des fichiers reliés
    cands = [r for r, n in indeg.items()
             if n >= need and sum(1 for t in files[r].get("out") or [] if t in code) <= 1]
    return sorted(cands, key=lambda r: (-indeg[r], r))[:limit]


def _modules(comms, pr, min_size=2):
    """Modules utiles d'abord ; ceux des dossiers de sauvegarde/export à la fin."""
    mods = [(lab, mem) for lab, mem in comms.items() if len(mem) >= min_size]
    return sorted(mods, key=lambda x: (bool(BACKUP_RX.search((x[0] or "") + "/")),
                                       -(sum(pr.get(m, 0) for m in x[1]) + 1e-6 * len(x[1]))))


def _label(lab, width=42):
    lab = lab or "(racine)"
    if len(lab) <= width:
        return lab
    tail = "/".join(lab.split("/")[-2:])
    return "…/" + (tail if len(tail) <= width else tail[-width:])


def build_report(meta, files, in_edges, pr, comms, sccs) -> str:
    kinds = Counter(_kind(f) for f in files.values())
    loc = sum(f.get("lines", 0) for f in files.values() if f.get("lang") in CODE)
    L = [f"# 🗺️ Carte du projet « {meta['name']} »",
         f"`{meta['root']}` · {len(files)} fichiers ({kinds['code']} code · {kinds['doc']} docs · {kinds['data']} données · "
         f"{kinds['asset']} médias · {kinds['other']} autres) · {_n(loc)} lignes de code · "
         f"générée le {fmt_date(meta['generated'])} en {meta['seconds']} s "
         f"({meta['parsed']} analysés, {len(files) - meta['parsed']} repris du cache)"]
    if meta.get("truncated"):
        L.append("> ⚠️ Limite de fichiers atteinte : carte partielle (`brain config map.max_files <n>`).")
    if meta["stack"].get("summary"):
        L.append(f"**Stack :** {meta['stack']['summary']}")
    if meta["entries"]:
        L.append("**Points d'entrée :** " + " · ".join(f"`{e}` ({why})" for e, why in meta["entries"][:10]))
    if meta.get("scripts"):
        L.append("**Scripts npm :** " + " · ".join(f"`{k}` → {short(v, 60)}" for k, v in list(meta["scripts"].items())[:10]))
    L += ["", "## Structure"] + tree_lines(files)

    socle = _socle(files)
    ranked = [r for r in _ranked(files, pr, CODE | {"json", "markdown"}, 15 + len(socle)) if r not in socle][:15]
    if ranked:
        L += ["", "## Fichiers clés (centralité dans le graphe d'imports/liens)"]
        for i, rel in enumerate(ranked, 1):
            f = files[rel]
            L.append(f"{i}. `{rel}` — {file_desc(f)} · importé par {len(in_edges.get(rel, []))} · importe {len(f.get('out', []))}")
    if socle:
        L += ["", "**Socle** (importé partout, n'importe presque rien — utilitaires communs) : "
              + " · ".join(f"`{r}` (importé par {len(in_edges.get(r, []))})" for r in socle)]
    big = _modules(comms, pr)
    if big:
        L += ["", "## Modules (communautés d'imports)"]
        for lab, mem in big[:12]:
            top = sorted(mem, key=lambda m: -_weight(m, pr))[:8]
            L.append(f"- **{_label(lab, 70)}** ({len(mem)}) : " + ", ".join(f"`{posixpath.basename(m)}`" for m in top))
        bridges = cross_links(files, comms)
        if bridges:
            L += ["", "## Liens entre modules"]
            L += [f"- {a or '(racine)'} → {b or '(racine)'} ({n}×), ex. `{ex[0]}` → `{ex[1]}`" for (a, b), (n, ex) in bridges[:8]]
    routes = [(rel, r) for rel, f in sorted(files.items()) for r in f.get("routes", [])]
    if routes:
        L += ["", f"## Routes / endpoints ({len(routes)})"] + [f"- `{r}` — `{rel}`" for rel, r in routes[:40]]
        if len(routes) > 40:
            L.append(f"- … +{len(routes) - 40}")
    env = sorted({v for f in files.values() for v in f.get("env", [])})
    if env:
        L += ["", "## Variables d'environnement (noms uniquement)", ", ".join(f"`{v}`" for v in env[:60])]
    docs = sorted((r for r, f in files.items() if _kind(f) == "doc" and not f.get("dup")),
                  key=lambda r: -files[r].get("mtime", 0))
    if docs:
        L += ["", f"## Documents ({len(docs)}, plus récents d'abord)"]
        L += [f"- `{r}` — {file_desc(files[r])} · {fmt_ts(files[r].get('mtime'))}" for r in docs[:25]]
        if len(docs) > 25:
            L.append(f"- … +{len(docs) - 25} (`brain files \"sujet\"`)")
    data = sorted((r for r, f in files.items() if f.get("lang") in ("csv", "xlsx", "xls", "notebook")
                   or (f.get("lang") == "json" and f.get("size", 0) > 20000)), key=lambda r: -files[r].get("mtime", 0))
    if data:
        L += ["", f"## Données ({len(data)})"] + [f"- `{r}` — {file_desc(files[r])}" for r in data[:15]]
    recent = sorted(files, key=lambda r: -files[r].get("mtime", 0))[:10]
    L += ["", "## Récemment modifiés"] + [f"- {fmt_ts(files[r].get('mtime'))} `{r}`" for r in recent]

    attn = []
    for comp in sccs:
        attn.append("Cycle d'imports : " + " ↔ ".join(f"`{c}`" for c in comp[:5]) + (" …" if len(comp) > 5 else ""))
    entry_set = {e for e, _ in meta["entries"]}
    lonely_langs = CODE - {"html", "css", "sql", "docker", "make", "batch", "shell", "powershell", "liquid"}
    if meta.get("dups"):
        where_dups = ", ".join(f"`{d}/` ({n})" for d, n in meta.get("dup_dirs", []))
        attn.append(f"Copies identiques : {meta['dups']} fichiers (surtout {where_dups}) — la plus récente sert de "
                    "référence, les copies sont ignorées dans les classements et la recherche.")
    isolated = [r for r, f in files.items() if f.get("lang") in lonely_langs and not f.get("out") and not f.get("dup")
                and r not in in_edges and r not in entry_set and not _is_test(r) and not NOT_ISOLATED.search(r)]
    if isolated and len(isolated) < len([1 for f in files.values() if f.get("lang") in lonely_langs]):
        attn.append(f"Fichiers code isolés (ni importés ni importants) : {len(isolated)} — ex. "
                    + ", ".join(f"`{r}`" for r in sorted(isolated)[:6]))
    bigf = sorted((r for r, f in files.items() if f.get("lang") in CODE and f.get("lines", 0) > 800),
                  key=lambda r: -files[r]["lines"])
    if bigf:
        attn.append("Gros fichiers : " + ", ".join(f"`{r}` ({files[r]['lines']} l.)" for r in bigf[:6]))
    todo_total = sum(f.get("todo", 0) for f in files.values())
    if todo_total:
        ex = [(r, t) for r, f in sorted(files.items()) for t in f.get("todos", [])][:5]
        attn.append(f"TODO/FIXME : {todo_total} — " + " · ".join(f"`{r}:{ln}` {k} {short(txt, 50)}" for r, (ln, k, txt) in ex))
    sens = [r for r, f in files.items() if f.get("sensitive")]
    if sens:
        attn.append("Fichiers sensibles (jamais lus) : " + ", ".join(f"`{r}`" for r in sens[:8]))
    errs = [r for r, f in files.items() if f.get("err")]
    if errs:
        attn.append(f"Fichiers non analysables : {len(errs)} (ex. `{errs[0]}`)")
    bigskip = [r for r, f in files.items() if f.get("big")]
    if bigskip:
        attn.append(f"Trop gros pour l'analyse : {len(bigskip)} (ex. `{bigskip[0]}`)")
    if attn:
        L += ["", "## Points d'attention"] + [f"- {a}" for a in attn]
    L += ["", "## Utiliser cette carte",
          "`brain files \"sujet\"` · `brain where <symbole>` · `brain explain <fichier>` · `brain deps <fichier>` · "
          "`brain impact <x>` (avant de modifier) · `brain path <a> <b>` · `brain map .` (mise à jour incrémentale)"]
    return "\n".join(L) + "\n"


def build_digest(meta, files, pr, comms, pid) -> str:
    if not files:
        return ("**🗺️ Carte du dossier** : aucun fichier visible (dossier vide ou seulement des fichiers cachés) — "
                "le travail de ce projet se fait ailleurs ; voir les sessions et souvenirs ci-dessus.")
    kinds = Counter(_kind(f) for f in files.values())
    parts = [f"**🗺️ Carte du dossier** ({fmt_date(meta['generated'])}) : {len(files)} fichiers — {kinds['code']} code, "
             f"{kinds['doc']} docs, {kinds['data']} données, {kinds['asset']} médias."]
    if meta["stack"].get("summary"):
        parts.append(f"Stack : {short(meta['stack']['summary'], 200)}")
    if meta["entries"]:
        parts.append("Entrées : " + ", ".join(f"`{e}`" for e, _ in meta["entries"][:4]))
    if meta.get("scripts"):
        parts.append("Scripts npm : " + ", ".join(f"`{k}`" for k in list(meta["scripts"])[:8]))
    socle = _socle(files)
    ranked = [r for r in _ranked(files, pr, CODE, 6 + len(socle)) if r not in socle][:6]
    if ranked:
        parts.append("Fichiers clés : " + " · ".join(f"`{r}` ({short(file_desc(files[r], 2), 48)})" for r in ranked))
    if socle:
        parts.append("Socle (importé partout) : " + " · ".join(f"`{r}`" for r in socle))
    mods = _modules(comms, pr, 3)[:5]
    if mods:
        parts.append("Modules : " + " · ".join(f"{_label(lab)} ({len(mem)})" for lab, mem in mods))
    docs = sorted((r for r, f in files.items() if _kind(f) == "doc" and not f.get("dup")),
                  key=lambda r: -files[r].get("mtime", 0))[:6]
    if meta.get("dups"):
        parts.append(f"Copies identiques ignorées : {meta['dups']} fichiers (sauvegardes/exports).")
    if docs:
        def label(r):
            t = files[r].get("title") or files[r].get("doc") or ""
            return f"`{r}`" + (f" « {short(t, 50)} »" if t else "")
        parts.append("Docs récents : " + " · ".join(label(r) for r in docs))
    parts.append(f"→ Avant d'explorer : `brain files \"sujet\"` · `brain where <symbole>` · `brain explain <fichier>` · "
                 f"avant de modifier : `brain impact <x>` · carte complète : `{PROJECTS_DIR / pid / 'MAP.md'}`")
    text = "\n".join(parts)
    return text if len(text) <= 1900 else text[:1899] + "…"


def build_search(files) -> dict:
    keys, tfs, descs = [], [], []
    for rel, f in files.items():
        if f.get("dup") or (f.get("lang") in ("asset", "binary", "other", "skip") and not f.get("title")):
            continue
        fields = [
            (re.sub(r"[/_.\-]", " ", rel), 3.0),
            (" ".join(s["n"] for s in (f.get("symbols") or [])[:120]), 2.0),
            (" ".join([f.get("title") or "", f.get("doc") or ""] + (f.get("headings") or [])[:20] + (f.get("sheets") or [])), 1.4),
            (" ".join(f.get("routes") or []), 1.5),
            (" ".join(w[2] for w in f.get("why") or []), 1.2),
        ]
        tf = Counter()
        for text, w in fields:
            for t in tokenize(text):
                tf[t] += w
        if tf:
            keys.append(rel)
            tfs.append({t: round(v, 1) for t, v in tf.items()})
            descs.append(file_desc(f))
    return {"keys": keys, "tfs": tfs, "descs": descs}


# =============================================================================================== orchestration
MARKERS = {".git", "package.json", "pyproject.toml", "requirements.txt", "setup.py", "cargo.toml", "go.mod",
           "composer.json", "gemfile", "pom.xml", "build.gradle", "claude.md", "readme.md", "index.html",
           "manifest.json", "dockerfile", "docker-compose.yml", "makefile", "deno.json", "pubspec.yaml"}


def looks_like_project(path) -> bool:
    """Dossier « projet » (code ou documents), pas un dossier système/perso trop large."""
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
    return sum(1 for e in low if os.path.splitext(e)[1] in LANG_BY_EXT) >= 3


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
    t0 = time.time()
    previous = {} if full else ((read_json(outdir / "map.json", {}) or {}).get("files") or {})
    listing, truncated = walk(root, max_files or cfg["max_files"])
    files, parsed = {}, 0
    max_bytes = cfg["max_file_kb"] * 1024
    for rel, size, mtime in listing:
        res = process_file(root, rel, previous.get(rel), max_bytes, size, mtime)
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
            "scripts": pkg.get("scripts") or {}, "dups": dup_count, "dup_dirs": dup_dirs.most_common(4)}
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


# =============================================================================================== requêtes
def load_map(pid):
    return read_json(PROJECTS_DIR / pid / "map.json", None)


def find_file(files, query, root=None):
    q = str(query).strip().strip("`")
    if root and os.path.isabs(q):
        try:
            q = os.path.relpath(q, root)
        except ValueError:
            pass
    q = q.replace("\\", "/").lstrip("./").lower()
    if not q:
        return []
    exact = [r for r in files if r.lower() == q]
    if exact:
        return exact
    rank = lambda r: (-files[r].get("pr", 0), len(r))  # noqa: E731
    for pred in (lambda r: r.lower().endswith("/" + q),
                 lambda r: posixpath.basename(r).lower().startswith(q),
                 lambda r: q in r.lower()):
        hits = [r for r in files if pred(r)]
        if hits:
            return sorted(hits, key=rank)
    return []


def where(m, name, limit=30):
    files = m["files"]
    q = name.lower().strip()
    buckets = ([], [], [])
    copies = 0
    for rel, f in files.items():
        if f.get("dup"):
            copies += sum(1 for s in f.get("symbols", []) if q in s["n"].lower())
            continue
        for s in f.get("symbols", []):
            n = s["n"].lower()
            tail = n.rsplit(".", 1)[-1]
            if q in (n, tail):
                buckets[0].append((rel, s))
            elif n.startswith(q) or tail.startswith(q):
                buckets[1].append((rel, s))
            elif q in n:
                buckets[2].append((rel, s))
    hits = buckets[0] + buckets[1] + buckets[2]
    lines = [f"{rel}:{s['l']}  {s['k']} {s['n']}" for rel, s in hits[:limit]]
    if len(hits) > limit:
        lines.append(f"… +{len(hits) - limit}")
    if copies:
        lines.append(f"(+{copies} occurrence(s) dans des copies identiques ignorées)")
    envs = [rel for rel, f in files.items() if any(v.lower() == q for v in f.get("env", []))]
    if envs:
        lines.append(f"variable d'env {name} utilisée dans : " + ", ".join(sorted(envs)[:15]))
    lines += [f"{rel}  route {r}" for rel, f in files.items() for r in f.get("routes", []) if q in r.lower()][:10]
    return lines


def deps(m, query):
    files = m["files"]
    cands = find_file(files, query, m["meta"].get("root"))
    if not cands:
        return [f"aucun fichier ne correspond à « {query} »"]
    rel = cands[0]
    f = files[rel]
    importers = sorted(r for r, g in files.items() if rel in (g.get("out") or []))
    lines = [f"`{rel}`" + (f"  (autres : {', '.join(cands[1:4])})" if len(cands) > 1 else "")]
    lines.append(f"→ importe ({len(f.get('out', []))}) : " + (", ".join(f.get("out", [])[:40]) or "—"))
    if f.get("ext"):
        lines.append("→ paquets externes : " + ", ".join(f["ext"][:40]))
    lines.append(f"← importé par ({len(importers)}) : " + (", ".join(importers[:40]) or "—"))
    return lines


def explain(m, target):
    files = m["files"]
    path, name = _split_target(target)
    if path:  # fichier:symbole
        cands = find_file(files, path, m["meta"].get("root"))
        if not cands:
            return [f"fichier introuvable : {path}"]
        r = cands[0]
        syms = _symbols(files, name, r)
        if not syms:
            return [f"« {name} » introuvable dans `{r}` (`brain where {name}`) :", ""] + explain(m, r)
        s = syms[0][1]
        return [f"Symbole « {s['n']} » : {r}:{s['l']}  {s['k']}"] + _call_lines(m, r, s) + [""] + explain(m, r)
    cands = find_file(files, target, m["meta"].get("root"))
    if not cands:
        hits = [l for l in where(m, target, 12)]
        if not hits:
            return [f"rien trouvé pour « {target} » (essaie `brain files \"{target}\"`)"]
        first = hits[0].split(":")[0]
        syms = _symbols(files, target, first) if first in files else []
        calls = _call_lines(m, first, syms[0][1]) if syms else []
        return [f"Symbole « {target} » :"] + hits + calls + [""] + explain(m, first)
    rel = cands[0]
    f = files[rel]
    importers = sorted(r for r, g in files.items() if rel in (g.get("out") or []))
    rank = sorted((r for r in files if files[r].get("pr")), key=lambda r: -files[r]["pr"])
    pos = rank.index(rel) + 1 if rel in rank else None
    head = f"`{rel}` — {LANG_LABEL.get(f.get('lang'), f.get('lang'))}"
    head += f" · {f['lines']} lignes" if f.get("lines") else ""
    head += f" · {_size(f.get('size', 0))}"
    head += f" · module {f['mod'] or '(racine)'}" if "mod" in f else ""
    head += f" · centralité #{pos}/{len(rank)}" if pos else ""
    head += f" · modifié le {fmt_ts(f.get('mtime'))}"
    L = [head]
    if len(cands) > 1:
        L.append("(autres correspondances : " + ", ".join(cands[1:5]) + ")")
    for key, label in (("title", "Titre"), ("doc", "Résumé")):
        if f.get(key):
            L.append(f"{label} : {f[key]}")
    syms = f.get("symbols", [])
    if syms:
        L.append(f"Symboles ({len(syms)}) : " + ", ".join(f"{s['n']} ({s['k']} l.{s['l']})" for s in syms[:60]))
    if f.get("headings"):
        L.append("Plan : " + " | ".join(f["headings"][:20]))
    if f.get("sheets"):
        L.append("Feuilles : " + ", ".join(f["sheets"]))
    if f.get("routes"):
        L.append("Routes : " + " · ".join(f["routes"][:20]))
    if f.get("env"):
        L.append("Variables d'env : " + ", ".join(f["env"]))
    if f.get("pkg", {}).get("scripts"):
        L.append("Scripts : " + " · ".join(f"{k} → {v}" for k, v in f["pkg"]["scripts"].items()))
    if f.get("deps"):
        L.append(f"Dépendances ({len(f['deps'])}) : " + ", ".join(f["deps"][:40]))
    if f.get("out"):
        L.append(f"Importe ({len(f['out'])}) : " + ", ".join(f["out"][:40]))
    if f.get("ext"):
        L.append("Paquets externes : " + ", ".join(f["ext"][:40]))
    if importers:
        L.append(f"Importé par ({len(importers)}) : " + ", ".join(importers[:40]))
    if f.get("todos"):
        L.append("TODO : " + " · ".join(f"l.{ln} {k} {t}" for ln, k, t in f["todos"]))
    if f.get("why"):
        L.append("Raisons notées : " + " · ".join(f"l.{ln} {k} {t}" for ln, k, t in f["why"]))
    if f.get("sensitive"):
        L.append("⚠️ fichier sensible : contenu volontairement jamais lu.")
    return L


def path_between(m, a, b):
    files = m["files"]
    root = m["meta"].get("root")
    A, B = find_file(files, a, root), find_file(files, b, root)
    if not A or not B:
        return [f"fichier introuvable : {a if not A else b}"]
    src, dst = A[0], B[0]
    adj = defaultdict(set)
    for rel, f in files.items():
        for t in f.get("out", []):
            adj[rel].add((t, "→"))
            adj[t].add((rel, "←"))
    prev = {src: None}
    q = deque([src])
    while q:
        cur = q.popleft()
        if cur == dst:
            break
        for nxt, d in sorted(adj[cur]):
            if nxt not in prev:
                prev[nxt] = (cur, d)
                q.append(nxt)
    if dst not in prev:
        return [f"aucun chemin d'imports entre `{src}` et `{dst}`"]
    chain, cur = [], dst
    while prev[cur]:
        p, d = prev[cur]
        chain.append((d, cur))
        cur = p
    chain.reverse()
    text = f"`{src}`" + "".join(f" {'importe' if d == '→' else 'est importé par'} `{c}`" for d, c in chain)
    return [f"{len(chain)} saut(s) : {text}"]


# =============================================================================================== impact (avant de modifier)
_REL_RANK = {"c": 0, "h": 1, "r": 2, "d": 3}
VERBS = {"c": "appelle", "h": "hérite de", "r": "utilise", "d": "appelle (déduit)"}
KIND_LABEL = {"fn": "fonction", "class": "classe", "method": "méthode", "const": "constante"}


def call_edges(m) -> list:
    """Liens d'appel résolus (Python) : [(fichier, appelant, ligne, fichier visé, symbole visé, relation)].
    Relation : c appel · h héritage · r usage · d appel déduit (méthode au nom unique parmi les fichiers atteignables).
    Résolution : imports relatifs et absolus, réexports d'un __init__, sous-modules, héritage ; un nom qui reste
    ambigu ne donne aucun lien."""
    files = m["files"]
    py = {r for r, f in files.items() if f.get("lang") == "python" and not f.get("dup")}
    R = Resolver(files)
    syms = {r: {s["n"] for s in files[r].get("symbols") or []} | (set(files[r].get("pyrefs") or {}) - {""}) for r in py}
    meth = defaultdict(list)
    for r in sorted(py):
        for s in files[r].get("symbols") or []:
            if s["k"] == "method":
                meth[s["n"].rsplit(".", 1)[1]].append((r, s["n"]))
    memo, reach_memo = {}, {}

    def mod(rel, spec):
        k = (posixpath.dirname(rel), spec)
        if k not in memo:
            try:
                hit = R.py(rel, spec)[0]
            except Exception:
                hit = None
            memo[k] = hit if hit in py else None
        return memo[k]

    def origins(f, head):  # « from .prix import total » dans f → module d'où vient « total »
        n = len(head)
        for e in files[f].get("imports") or []:
            if len(e) > n and e.endswith(head) and e[-n - 1] == ".":
                M = e[:-n]
                yield M if not M.strip(".") else M[:-1]

    def lookup(rel, M, dotted, hops):
        if hops > 4:
            return None
        parts = dotted.split(".")
        base = M if M.endswith(".") else M + "."
        for k in range(len(parts) - 1, 0, -1):  # sous-module le plus long d'abord : from pkg import mod ; mod.f()
            t = mod(rel, base + ".".join(parts[:k]))
            hit = member(t, ".".join(parts[k:]), hops + 1) if t else None
            if hit:
                return hit
        return member(mod(rel, M), dotted, hops + 1)

    def member(f, name, hops):
        if not f or hops > 4:
            return None
        if name in syms.get(f, ()):
            return f, name
        head, _, rest = name.partition(".")
        if rest and head in syms.get(f, ()):
            return inherited(f, head, rest, hops)
        for M in origins(f, head):
            hit = lookup(f, M, name, hops + 1)
            if hit:
                return hit
        return None

    def inherited(f, cls, attr, hops):
        for p in (files[f].get("pyrefs") or {}).get(cls) or []:
            p = p.split()
            if len(p) > 3 and p[1] == "h":
                base = target(f, p[2], p[3:], hops + 1)
                hit = member(base[0], f"{base[1]}.{attr}", hops + 1) if base else None
                if hit:
                    return hit
        return None

    def reach(rel):  # fichiers atteignables en 3 imports au plus
        if rel not in reach_memo:
            seen, frontier = {rel}, [rel]
            for _ in range(3):
                nxt = []
                for x in frontier:
                    for t in files.get(x, {}).get("out") or []:
                        if t not in seen:
                            seen.add(t)
                            nxt.append(t)
                frontier = nxt
            reach_memo[rel] = seen
        return reach_memo[rel]

    def target(rel, kind, args, hops=0):
        if kind == "l":
            return member(rel, args[0], hops)
        if kind == "i":
            return lookup(rel, args[0], args[1], hops)
        if kind == "f":
            return lookup(rel, args[0], f"{args[1]}.{args[2]}", hops)
        if kind == "m":
            hit = member(mod(rel, args[0]), args[1], hops)
            if not hit and "." in args[0]:
                head, last = args[0].rsplit(".", 1)
                hit = member(mod(rel, head), f"{last}.{args[1]}", hops)
            return hit
        if kind == "s":
            return member(rel, f"{args[0]}.{args[1]}", hops)
        if kind == "p":
            return inherited(rel, args[0], args[1], hops)
        if kind == "*":
            for M in files[rel].get("pystar") or []:
                hit = lookup(rel, M, args[0], hops)
                if hit:
                    return hit
            return None
        if kind == "a":
            cands = [x for x in meth.get(args[0], ()) if x[0] in reach(rel)]
            return cands[0] if len(cands) == 1 else None
        return None

    best, done = {}, {}
    for rel in sorted(py):
        for caller, refs in (files[rel].get("pyrefs") or {}).items():
            for s in refs:
                p = s.split()
                try:
                    line, rl, kind, args = int(p[0]), p[1], p[2], tuple(p[3:])
                    k = (rel, kind) + args
                    if k not in done:
                        done[k] = target(rel, kind, args)
                    hit = done[k]
                except (ValueError, IndexError, KeyError, RecursionError):
                    continue
                if not hit or tuple(hit) == (rel, caller):
                    continue
                rl = "d" if kind == "a" else rl
                key = (rel, caller) + tuple(hit)
                v = (_REL_RANK.get(rl, 9), line, rl)
                if key not in best or v < best[key]:
                    best[key] = v
    return [(k[0], k[1], v[1], k[2], k[3], v[2]) for k, v in best.items()]


def _split_target(t):
    """« fichier.py:symbole » → (fichier, symbole) ; sinon (None, cible). « C:… » (lecteur Windows) n'en est pas un."""
    t = str(t).strip().strip("`")
    mt = re.match(r"^(.+?):([A-Za-z_][\w.]*)$", t)
    if mt and len(mt.group(1)) > 1:
        return mt.group(1), mt.group(2)
    return None, t


def _looks_like_path(name) -> bool:
    return "/" in name or "\\" in name or posixpath.splitext(name.lower())[1] in LANG_BY_EXT


def _symbols(files, name, rel=None):
    """Définitions d'un nom, du plus précis au plus vague : nom complet, fin de nom (méthode), casse ignorée."""
    q = str(name).strip()
    ql = q.lower()
    tiers = ([], [], [])
    for r in ([rel] if rel else sorted(files)):
        f = files.get(r) or {}
        if f.get("dup"):
            continue
        for s in f.get("symbols") or []:
            n = s["n"]
            tail = n.rsplit(".", 1)[-1]
            if n == q:
                tiers[0].append((r, s))
            elif tail == q:
                tiers[1].append((r, s))
            elif ql in (n.lower(), tail.lower()):
                tiers[2].append((r, s))
    return next((t for t in tiers if t), [])


def impact(m, target, depth=2):
    """Ce qui dépend d'un fichier ou d'un symbole, à revoir avant de le modifier (façon graphify « affected »).
    → (lignes, code de sortie) : 0 trouvé · 3 nom ambigu (définitions listées) · 4 introuvable."""
    files, root = m["files"], m["meta"].get("root")
    depth = max(1, min(5, int(depth or 2)))
    stale = any(f.get("lang") == "python" and f.get("v") != PARSER_VERSION for f in files.values())
    hint = ["(carte d'une version précédente, sans graphe d'appels : lance d'abord `brain map .`)", ""] if stale else []
    path, name = _split_target(target)
    if path:
        cands = find_file(files, path, root)
        if not cands:
            return [f"fichier introuvable : {path}"], 4
        syms = _symbols(files, name, cands[0])
        if not syms:
            return [f"« {name} » introuvable dans `{cands[0]}` (`brain where {name}`)"], 4
    else:
        cands = find_file(files, name, root) if _looks_like_path(name) else []
        if cands:
            return hint + _impact_file(m, cands[0], depth), 0
        syms = _symbols(files, name)
        if not syms:
            cands = find_file(files, name, root)
            if not cands:
                return [f"rien trouvé pour « {name} » (essaie `brain where {name}` ou `brain files \"{name}\"`)"], 4
            return hint + _impact_file(m, cands[0], depth), 0
    if len(syms) > 1:
        L = [f"« {name} » est ambigu : {len(syms)} définitions. Précise avec `brain impact fichier:symbole` :"]
        L += [f"- {r}:{s['n']}  ({KIND_LABEL.get(s['k'], s['k'])}, l.{s['l']})" for r, s in syms[:10]]
        return L + ([f"… +{len(syms) - 10}"] if len(syms) > 10 else []), 3
    rel, s = syms[0]
    if files[rel].get("lang") != "python":
        return ([f"(graphe d'appels : Python seulement — impact du fichier qui définit « {s['n']} »)", ""]
                + _impact_file(m, rel, depth)), 0
    return hint + _impact_symbol(m, rel, s, depth), 0


def _impact_symbol(m, rel, s, depth):
    files = m["files"]
    rev = defaultdict(list)
    for src, caller, line, tf, ts, rl in call_edges(m):
        rev[(tf, ts)].append((src, caller, line, rl))
    name = s["n"]
    seeds = {(rel, name)}
    if s["k"] == "class":
        seeds |= {(rel, x["n"]) for x in files[rel].get("symbols") or [] if x["n"].startswith(name + ".")}
    seen, frontier, levels = set(seeds), seeds, []
    for _ in range(depth):
        hits = {}
        for t in frontier:
            for src, caller, line, rl in rev.get(t, ()):
                u, v = (src, caller), (_REL_RANK[rl], line, rl, t[1])
                if u not in seen and (u not in hits or v < hits[u]):
                    hits[u] = v
        if not hits:
            break
        levels.append(hits)
        seen |= set(hits)
        frontier = {u for u in hits if u[1]}  # le niveau module (« ») n'a pas d'appelant
    L = [f"Impact de « {name} » — {rel}:{s['l']} ({KIND_LABEL.get(s['k'], s['k'])}) · profondeur {depth}"]
    if not levels:
        L.append(f"Aucun appel ni usage repéré de « {name} » dans le code Python analysé "
                 "(les appels dynamiques — getattr, chaînes — ne sont pas visibles).")
        return L + _impact_footer(files, rel, set())
    touched, deduced = set(), False
    for d, hits in enumerate(levels, 1):
        rows = sorted(hits.items(), key=lambda kv: (kv[0][0], kv[1][1]))
        L += ["", f"Dépend directement ({len(rows)}) :" if d == 1 else f"Niveau {d} ({len(rows)}) :"]
        for (src, caller), (_, line, rl, ts) in rows[:40]:
            L.append(f"- {src}:{line}  {caller or '(niveau module)'} {VERBS[rl]} {ts}")
            deduced |= rl == "d"
        if len(rows) > 40:
            L.append(f"… +{len(rows) - 40}")
        touched |= {u[0] for u in hits}
    L += _impact_footer(files, rel, touched)
    if deduced:
        L.append("(« déduit » : méthode au nom unique dans le projet, appelée sur un objet : à confirmer)")
    return L


def _impact_file(m, rel, depth):
    files = m["files"]
    imp = defaultdict(set)
    for r, f in files.items():
        if not f.get("dup"):
            for t in f.get("out") or []:
                imp[t].add(r)
    uses = defaultdict(set)
    if files[rel].get("lang") == "python":
        for src, _, _, tf, ts, _ in call_edges(m):
            if tf == rel and src != rel:
                uses[src].add(ts)
    L = [f"Impact du fichier `{rel}` · profondeur {depth}"]
    seen, frontier, levels = {rel}, [rel], []
    for _ in range(depth):
        nxt = {}
        for x in frontier:
            for r in sorted(imp.get(x, ())):
                if r not in seen and r not in nxt:
                    nxt[r] = x
        if not nxt:
            break
        levels.append(nxt)
        seen |= set(nxt)
        frontier = list(nxt)
    if not levels:
        return L + ["Aucun fichier du projet ne l'importe."] + _impact_footer(files, rel, set())
    touched = set()
    for d, nxt in enumerate(levels, 1):
        rows = sorted(nxt.items())
        L += ["", f"Importé directement par ({len(rows)}) :" if d == 1 else f"Niveau {d} ({len(rows)}) :"]
        for r, via in rows[:40]:
            if d > 1:
                L.append(f"- `{r}` via `{via}`")
                continue
            u = sorted(uses.get(r, ()))
            L.append(f"- `{r}`" + (" — utilise : " + ", ".join(u[:8]) + (" …" if len(u) > 8 else "") if u else ""))
        if len(rows) > 40:
            L.append(f"… +{len(rows) - 40}")
        touched |= set(nxt)
    return L + _impact_footer(files, rel, touched)


def _impact_footer(files, rel, touched):
    tests = sorted({r for r in touched if _is_test(r)}
                   | {r for r, f in files.items() if _is_test(r) and not f.get("dup") and rel in (f.get("out") or [])})
    others = sorted(r for r in touched if r != rel and not _is_test(r))
    L = [""]
    if others:
        L.append(f"À revoir : {len(others)} fichier(s) — " + ", ".join(f"`{r}`" for r in others[:12])
                 + (" …" if len(others) > 12 else ""))
    L.append("Tests reliés : " + ", ".join(f"`{r}`" for r in tests[:12]) + (" …" if len(tests) > 12 else "")
             if tests else "Aucun test relié repéré.")
    return L


def _call_lines(m, rel, s, limit=15):
    """Appelants et appelés d'un symbole Python (fiche `explain`)."""
    files = m["files"]
    if (files.get(rel) or {}).get("lang") != "python":
        return []
    own = {s["n"]}
    if s["k"] == "class":
        own |= {x["n"] for x in files[rel].get("symbols") or [] if x["n"].startswith(s["n"] + ".")}
    callers, callees = {}, {}
    for src, caller, line, tf, ts, rl in call_edges(m):
        from_own, to_own = src == rel and caller in own, tf == rel and ts in own
        if to_own == from_own:
            continue
        side, k = (callers, (src, caller)) if to_own else (callees, (tf, ts))
        if k not in side or (_REL_RANK[rl], line) < (_REL_RANK[side[k][1]], side[k][0]):
            side[k] = (line, rl)
    tag = {"h": "héritage", "r": "usage", "d": "déduit"}
    L = []
    if callers:
        rows = sorted(callers.items(), key=lambda kv: (kv[0][0], kv[1][0]))
        L.append(f"Appelé par ({len(rows)}) : " + " · ".join(
            f"{c or '(niveau module)'} ({src}:{line}{', ' + tag[rl] if rl in tag else ''})"
            for (src, c), (line, rl) in rows[:limit]) + (" …" if len(rows) > limit else ""))
    if callees:
        rows = sorted(callees.items(), key=lambda kv: kv[1][0])
        L.append(f"Appelle ({len(rows)}) : " + " · ".join(
            f"{ts} (`{tf}`{', ' + tag[rl] if rl in tag else ''})"
            for (tf, ts), (line, rl) in rows[:limit]) + (" …" if len(rows) > limit else ""))
    return L or ["Appels : aucun repéré (les appels dynamiques ne sont pas visibles)."]
