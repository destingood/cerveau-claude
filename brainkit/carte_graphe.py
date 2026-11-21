"""Carte de projets : résolution des imports en liens entre fichiers (paquets locaux compris), analyse du graphe
(centralité, modules, cycles), stack technique et points d'entrée. Partie de mapper.py, découpé le 21/11/2026."""
from __future__ import annotations

import posixpath
import re
import urllib.parse
from collections import Counter, defaultdict

from .carte_langages import _kind, CODE, LANG_LABEL, STDLIB

# =============================================================================================== résolution
NODE_BUILTINS = {"fs", "path", "os", "http", "https", "url", "util", "crypto", "stream", "events", "child_process",
                 "buffer", "zlib", "net", "tls", "dns", "readline", "assert", "querystring", "worker_threads",
                 "cluster", "timers", "process", "module", "vm", "perf_hooks", "string_decoder", "tty", "dgram",
                 "v8", "async_hooks", "inspector", "constants", "punycode", "test"}
JS_EXTS = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".json", ".d.ts", ".css", ".scss")
JS_INDEX = ("/index.ts", "/index.tsx", "/index.js", "/index.jsx", "/index.mjs", "/index.vue", "/index.svelte")


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
        self._locals()
        self._py_roots_hit, self._py_rest, self._dirs = {}, {}, None
        self.aliases = self._aliases()
        self.alias_prefixes = tuple(a for a, _ in self.aliases)

    def _locals(self):
        """Paquets du dépôt lui-même (monorepo, dépendances file:/link:/workspace:/path) : un import vers eux est
        résolu vers leurs fichiers, ou au moins n'est pas compté comme un paquet externe (avant, il l'était)."""
        self.js_pkgs, self.js_local, self.py_local, roots = {}, set(), set(), []
        for rel, f in self.files.items():
            base, d = posixpath.basename(rel).lower(), posixpath.dirname(rel)
            if base == "package.json":
                pkg = f.get("pkg") or {}
                if pkg.get("name"):
                    self.js_pkgs.setdefault(pkg["name"], (d, pkg.get("main") or ""))
                self.js_local.update(f.get("local") or ())
            elif base in ("pyproject.toml", "setup.py", "setup.cfg") or f.get("lang") == "requirements":
                self.py_local.update(_py_name(n) for n in f.get("local") or ())
                if base == "pyproject.toml" and f.get("title"):
                    self.py_local.add(_py_name(f["title"]))
                if d and f.get("lang") != "requirements":  # libs/x/pyproject.toml : libs/x/src/ et libs/x/ sont des racines
                    roots += [d + "/src/", d + "/"]
        # nom d'import de premier niveau → racines où il existe (x.py ou x/__init__.py) : une recherche directe, au lieu
        # d'essayer chaque racine pour chaque import (+30 ms à chaque carte d'un dépôt à 40 paquets Python)
        rootset, self.py_tops = set(roots), defaultdict(list)
        for k in self.files if rootset else ():
            if not k.endswith(".py"):
                continue
            parts = k.split("/")
            for i in range(1, len(parts)):
                prefix = "/".join(parts[:i]) + "/"
                if prefix in rootset:
                    top = parts[i][:-3] if i == len(parts) - 1 else parts[i]
                    if prefix not in self.py_tops[top]:
                        self.py_tops[top].append(prefix)
        for top in self.py_tops:  # même ordre qu'avant : libs/x/src/ avant libs/x/
            self.py_tops[top].sort(key=lambda r, order={r: i for i, r in enumerate(dict.fromkeys(roots))}: order[r])

    def _py_is_local(self, top) -> bool:
        """Un nom d'import de premier niveau est-il un paquet du dépôt ? Dossier du projet (même sans __init__.py :
        paquet « espace de noms »), paquet d'un sous-projet, ou dépendance locale déclarée."""
        if self._dirs is None:
            self._dirs = set()
            for k in self.files:
                parts = k.split("/")[:-1]
                for i in range(1, len(parts) + 1):
                    self._dirs.add("/".join(parts[:i]))
        return (top in self.py_tops or _py_name(top) in self.py_local
                or any(root + top in self._dirs for root in self.py_roots))

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
        if pkg in self.js_pkgs:  # paquet du dépôt (monorepo) : son fichier, par son point d'entrée ou son chemin
            d, entry = self.js_pkgs[pkg]
            sub = spec[len(pkg):].lstrip("/")

            def at(x):
                return posixpath.join(d, x) if d else x
            if sub:
                return self.try_js(at(sub)) or self.try_js(at("src/" + sub)), None
            return ((self.try_js(at(entry)) if entry else None) or self.try_js(at("src/index"))
                    or self.try_js(at("index"))), None
        if pkg in self.js_local:  # file:/link: vers un dossier hors du dépôt : local quand même
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
        path = spec.replace(".", "/")
        hit = self._py_roots_hit.get(spec, 0)  # ne dépend pas du fichier qui importe : calculé une fois par nom
        if hit == 0:
            hit = next((h for h in (self._try_py(root + path) for root in self.py_roots) if h), None)
            self._py_roots_hit[spec] = hit
        if hit:
            return hit, None
        here = posixpath.dirname(rel)
        hit = self._try_py(here + "/" + path) if here else None
        if hit:
            return hit, None
        res = self._py_rest.get(spec)
        if res is None:
            top = spec.split(".")[0]
            if top in STDLIB:
                res = (None, None)
            else:  # paquets Python du dépôt (libs/x/src/x/…), puis paquets locaux hors du dépôt : pas externes
                hit = next((h for h in (self._try_py(root + path) for root in self.py_tops.get(top, ())) if h), None)
                res = (hit, None) if hit else (None, None) if self._py_is_local(top) else (None, top)
            self._py_rest[spec] = res
        return res

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


def _py_name(name) -> str:
    """Nom de paquet Python comparable à un nom d'import : « Mon-Paquet.x » → « mon_paquet_x »."""
    return re.sub(r"[-_.]+", "_", str(name)).lower()


def resolve(files):
    R = Resolver(files)
    py_tops = set()  # premiers noms d'imports Python résolus vers un fichier du dépôt
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
                if lang in ("python", "notebook") and not spec.startswith("."):
                    py_tops.add(spec.split(".")[0])
            elif pkg:
                ext.append(pkg)
        if out:
            f["out"] = sorted(set(out))
        if ext:
            f["ext"] = sorted(set(ext))
    # `from pkg.mod import nom` note aussi pkg.mod.nom, qui n'est pas un fichier : son premier nom (pkg) passait pour un
    # paquet externe alors que pkg.mod a été trouvé dans le dépôt. Un premier nom résolu quelque part est local partout.
    for f in files.values():
        if f.get("ext") and f.get("lang") in ("python", "notebook"):
            kept = [e for e in f["ext"] if e not in py_tops]
            if kept:
                f["ext"] = kept
            else:
                del f["ext"]
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
