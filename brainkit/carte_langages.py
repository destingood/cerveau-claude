"""Carte de projets : langages et formats — extensions reconnues, utilitaires de lecture, et parseurs de tous
les formats sauf Python (JavaScript/TypeScript, Vue, Svelte, HTML, CSS, Liquid, Markdown, JSON, YAML/TOML/INI,
requirements, CSV, notebooks, XML, texte, Word, Excel, PowerPoint, PDF, langages génériques). Partie de mapper.py,
découpé le 21/11/2026 sans changer son comportement."""
from __future__ import annotations

import bisect
import html
import json
import posixpath
import re
import sys
import time
import zipfile

from .common import first_line, short

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
    # CommonJS : exports.x = …, module.exports.x = …, module.exports = function nom / class Nom (avant, non indexés)
    (re.compile(r"^[ \t]*(?:module\.)?exports\.([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(?:function\b|\([^)\n]*\)\s*=>|"
                r"[A-Za-z_$][\w$]*\s*=>)", re.M), "fn"),
    (re.compile(r"^[ \t]*(?:module\.)?exports\.([A-Za-z_$][\w$]*)\s*=\s*class\b", re.M), "class"),
    (re.compile(r"^[ \t]*(?:module\.)?exports\.([A-Za-z_$][\w$]*)\s*=(?!=)", re.M), "const"),
    (re.compile(r"^[ \t]*module\.exports\s*=\s*(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)", re.M), "fn"),
    (re.compile(r"^[ \t]*module\.exports\s*=\s*class\s+([A-Za-z_$][\w$]*)", re.M), "class"),
]
CJS_OBJECT = re.compile(r"^[ \t]*module\.exports\s*=\s*\{", re.M)
CJS_ITEM = re.compile(r"\s*(?:async\s+)?\*?\s*(?:['\"]([A-Za-z_$][\w$]*)['\"]|([A-Za-z_$][\w$]*))\s*(:|\(|$)", re.S)
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


def _cjs_object(src, lines, seen):
    """module.exports = { a, b: c, d() {…} } → les noms exportés pas encore vus (une fonction définie plus haut sous le
    même nom l'est déjà : elle garde sa ligne)."""
    out = []
    for m in CJS_OBJECT.finditer(src):
        depth, i, start, items = 1, m.end(), m.end(), []
        while i < len(src) and depth and i - m.end() < 20000:
            ch = src[i]
            if ch in "{[(":
                depth += 1
            elif ch in "}])":
                depth -= 1
            elif ch in "'\"`":  # chaîne : sautée en entier (une virgule ou une accolade dedans ne compte pas)
                j = i + 1
                while j < len(src) and src[j] != ch and src[j] != "\n":
                    j += 2 if src[j] == "\\" else 1
                i = j
            if (ch == "," and depth == 1) or depth == 0:
                items.append((start, i))
                start = i + 1
            i += 1
        for a, b in items:
            im = CJS_ITEM.match(src, a, b)
            name = im and (im.group(1) or im.group(2))
            if not name or name in seen or name in NOT_NAMES or src[a:b].lstrip().startswith("..."):
                continue
            seen.add(name)
            kind = "fn" if im.group(3) == "(" or re.match(r"\s*(?:async\s+)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)",
                                                         src[im.end():b]) else "const"
            out.append({"n": name, "k": kind, "l": lines.at(a + len(src[a:b]) - len(src[a:b].lstrip()))})
    return out


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
    syms = _syms(src, JS_PATTERNS, lines)
    if "module.exports" in src:
        more = _cjs_object(src, lines, {s["n"] for s in syms})
        if more:
            syms = sorted(syms + more, key=lambda s: s["l"])[:200]
    out = {"symbols": syms,
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


LOCAL_SPEC = re.compile(r"^\s*(?:file:|link:|workspace:|portal:|\.{1,2}/|/|~/)")  # dépendance prise dans un dossier


def _pkg_entry(data) -> str:
    """Fichier d'entrée d'un package.json : main, module, exports["."], source."""
    exp = data.get("exports")
    if isinstance(exp, dict):
        exp = exp.get(".", exp if not any(str(k).startswith(".") for k in exp) else None)
    while isinstance(exp, dict):  # {"import": …, "require": …, "default": …}
        exp = next((v for k, v in exp.items() if k in ("default", "require", "import", "node") and v), None) \
            or next((v for v in exp.values() if isinstance(v, (str, dict))), None)
    for cand in (data.get("main"), data.get("module"), exp, data.get("source")):
        if isinstance(cand, str) and cand.strip():
            return cand.strip()
    return ""


def parse_json(text, rel):
    name = posixpath.basename(rel).lower()
    data = _loads_loose(text) if len(text) < 3_000_000 else None
    out = {}
    if isinstance(data, dict) and name == "package.json":
        deps = list((data.get("dependencies") or {}).keys())
        dev = list((data.get("devDependencies") or {}).keys())
        scripts = data.get("scripts") or {}
        out["pkg"] = {"name": str(data.get("name") or ""), "scripts": {k: short(v, 90) for k, v in list(scripts.items())[:25]}}
        entry = _pkg_entry(data)
        if entry:
            out["pkg"]["main"] = entry
        out["deps"] = deps + dev
        local = [k for sec in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
                 for k, v in (data.get(sec) or {}).items() if isinstance(v, str) and LOCAL_SPEC.match(v)]
        if local:  # paquets d'un dossier à soi (monorepo, file:, link:, workspace:) : pas des dépendances externes
            out["local"] = sorted(set(local))
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
        local = re.findall(r"""['"]\s*([A-Za-z0-9_.\-]+)\s*(?:\[[^\]'"]*\])?\s*@\s*(?:file:|\.{1,2}/|/)""", text)
        local += re.findall(r"(?m)^([A-Za-z0-9_.\-]+)\s*=\s*\{[^}\n]*\b(?:path|workspace)\s*=", text)  # poetry, uv
        if local:
            out["local"] = sorted(set(local))
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
    deps, local = [], []
    for raw in text.splitlines():
        egg = re.search(r"#egg=([A-Za-z0-9_.\-]+)", raw)
        line = re.sub(r"(?:^|\s)#.*$", "", raw.replace(egg.group(0), "") if egg else raw).strip()
        path = re.match(r"^(?:-e|--editable)\s+(\S+)$", line)
        target = path.group(1) if path else line
        named = re.match(r"^([A-Za-z0-9_.\-]+)\s*(?:\[[^\]]*\])?\s*@\s*(\S+)", target)
        if named and LOCAL_SPEC.match(named.group(2)):  # nom @ file:… : un paquet d'un dossier à soi
            local.append(named.group(1))
            continue
        if target and (LOCAL_SPEC.match(target) or target in (".", "..")):  # -e ./lib/outil, ../commun : idem
            name = egg.group(1) if egg else posixpath.basename(target.replace("\\", "/").rstrip("/"))
            if name and name not in (".", ".."):
                local.append(name)
            continue
        if not line or line.startswith("-"):
            continue
        if re.match(r"^(?:git|hg|svn|bzr)\+|^https?://", line):  # dépôt distant : son nom est dans #egg=
            if egg:
                deps.append(egg.group(1))
            continue
        m = re.match(r"([A-Za-z0-9_.\-]+)", line)
        if m:
            deps.append(m.group(1))
    out = {"deps": deps, "doc": "dépendances : " + ", ".join(deps[:12])}
    if local:
        out["local"] = sorted(set(local))
    return out


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
STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}


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
