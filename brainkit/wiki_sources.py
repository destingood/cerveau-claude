"""Ingestion d'une source dans le wiki : fichier (texte, PDF, Word, sous-titres, HTML) ou adresse web (contrôlée,
jamais une adresse locale sans --local), copie dans raw/, texte extrait, et le plan d'ingestion pour Claude (pages
liées, candidates à enrichir).

Découpé de wiki.py le 21/11/2026 (étape 8 du plan), sans changer le comportement : ces noms restent accessibles
depuis wiki (`wiki.add_source`, `wiki.UrlRefusee`…)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import wikistore as ws
from .common import fold, log, now_iso, short, tokenize
from .wiki import SCHEMA_FILE, TODO_MARK, _summary, content_digest, raw_files, sha1_file, type_label


TEXT_EXT = (".md", ".markdown", ".txt", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml", ".org", ".rst")


HTML_EXT = (".html", ".htm", ".xhtml")


SUB_EXT = (".vtt", ".srt")


FORMATS = ("article", "pdf", "video", "podcast", "livre", "note", "conversation", "donnees", "image", "document")


YOUTUBE = re.compile(r"^https?://(?:www\.|m\.)?(?:youtube\.com|youtu\.be)/", re.I)


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


class UrlRefusee(ValueError):
    """Adresse refusée avant tout envoi (schéma non web, ou hôte local/privé sans --local)."""


def check_url(url, allow_local=False):
    """Façon graphify (validate_url) : http(s) seulement, et jamais une adresse locale ou privée (127.0.0.1, 10.x,
    192.168.x, 169.254.x des métadonnées cloud…) sauf --local : une adresse lue dans une page ne doit pas faire sonder
    le réseau interne. Revérifiée à chaque redirection."""
    import ipaddress
    import socket
    import urllib.parse
    p = urllib.parse.urlsplit(str(url))
    if p.scheme.lower() not in ("http", "https") or not p.hostname:
        raise UrlRefusee(f"adresse refusée : {short(str(url), 80)} (http ou https seulement)")
    if allow_local:
        return
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme.lower() == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError, ValueError):
        return  # nom introuvable : le téléchargement échouera de lui-même
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
        ip = getattr(ip, "ipv4_mapped", None) or ip
        if not ip.is_global:
            raise UrlRefusee(f"adresse locale ou privée refusée : {p.hostname} ({ip}) — "
                             "`brain wiki add … --local` pour l'autoriser")


def fetch(url, allow_local=False) -> tuple:
    """URL → (titre, contenu en octets, extension). HTML converti en Markdown ; PDF et autres gardés tels quels.
    Adresse vérifiée avant l'envoi et à chaque redirection (check_url)."""
    import urllib.request

    class _Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            check_url(newurl, allow_local)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    check_url(url, allow_local)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (cerveau-wiki)",
                                               "Accept": "text/html,application/xhtml+xml,application/pdf,*/*"})
    with urllib.request.build_opener(_Redirect).open(req, timeout=30) as r:
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


def add_source(src, title=None, fmt=None, url=None, author=None, text=None, allow_local=False) -> dict:
    """Range une source dans raw/ (copie d'un fichier, page web téléchargée, texte reçu) et crée sa page Sources à
    remplir. Une source déjà présente (même contenu) n'est pas dupliquée. Adresse locale ou privée refusée sauf
    allow_local. → {raw, page, text, created}."""
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
            t, content, ext = fetch(src, allow_local=allow_local)
        except UrlRefusee as exc:
            raise RuntimeError(str(exc)) from None
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
