"""prompts.chat (https://prompts.chat/api/mcp) : la bibliothèque ouverte de prompts et de skills, branchée sur le cerveau.

Automatique : quand un message demande un prompt, un skill, un rôle (« agis comme… ») ou un contenu à créer (fiche
produit, e-mail, image…), le hook UserPromptSubmit cherche des modèles proches et en montre 0 à 2, seulement s'ils
correspondent vraiment. La bibliothèque est surtout anglophone : les mots-clés du message sont traduits par un lexique
(seuls les termes reconnus servent, un mot français inconnu ne ferait que du bruit).
À la main : `brain prompts "…"` (recherche), `brain prompts get <id>` (texte complet), `--skills`, `--hook "message"`.
Jamais bloquant : délai court, cache local, toute erreur réseau = rien d'injecté."""
from __future__ import annotations

import json
import os
import re
import time

from .common import STATE_DIR, fold, log, read_json, short, tokenize, write_json

ENDPOINT = "https://prompts.chat/api/mcp"
CACHE_FILE = STATE_DIR / "promptlib.json"
CACHE_DAYS, CACHE_MAX, COOLDOWN = 7, 200, 900

# Demande explicite : la bibliothèque est la réponse directe (un seul terme reconnu suffit).
ASK_RX = re.compile(r"\b(prompts?|skills?|agis comme|agir comme|act as|joue (?:le role|un|une)|persona|system prompt|"
                    r"midjourney|dall ?e|stable diffusion|nano banana|sora|veo|kling|runway)\b")
# Contenu à créer : au moins deux termes reconnus dont un contenu (CONTENT), sinon « fais le code du site » sortirait
# n'importe quel « website ».
MAKE_RX = re.compile(r"\b(ecri[st]?|ecrire|redige[sr]?|rediger|genere[sr]?|generer|cree[sr]?|creer|fai[st]|faire|"
                     r"propose[sr]?|proposer|imagine[sr]?|invente[sr]?|ameliore[sr]?|ameliorer|write|create|generate|"
                     r"draft|improve)\b")
TYPE_HINT = (("IMAGE", re.compile(r"\b(images?|photos?|visuels?|logos?|affiches?|illustrations?|portraits?|selfies?|"
                                  r"midjourney|dall ?e|stable diffusion|nano banana)\b")),
             ("VIDEO", re.compile(r"\b(sora|veo|kling|runway|clip video|video (?:ia|ai))\b")))

# Français (sans accents) → anglais de la bibliothèque. Les expressions passent avant les mots seuls ;
# les termes déjà anglais ou les marques se traduisent par eux-mêmes.
LEX = {
    "fiche produit": "product description", "fiches produits": "product description",
    "description produit": "product description", "page produit": "product page", "page d'accueil": "landing page",
    "landing page": "landing page", "reseaux sociaux": "social media", "reseau social": "social media",
    "service client": "customer support", "lettre de motivation": "cover letter", "nom de marque": "brand name",
    "nom de domaine": "domain name", "plan d'affaires": "business plan", "business plan": "business plan",
    "etude de marche": "market research", "cold email": "cold email", "e mail": "email", "e-mail": "email",
    "mail": "email", "mails": "email", "emails": "email", "email": "email", "newsletter": "newsletter",
    "publicite": "ads", "publicites": "ads", "pub": "ads", "pubs": "ads", "annonce": "listing", "annonces": "listing",
    "referencement": "seo", "seo": "seo", "article": "article", "articles": "article", "blog": "blog",
    "image": "image", "images": "image", "photo": "photo", "photos": "photo", "video": "video", "videos": "video",
    "logo": "logo", "logos": "logo", "miniature": "thumbnail", "miniatures": "thumbnail", "affiche": "poster",
    "illustration": "illustration", "infographie": "infographic", "portrait": "portrait", "selfie": "selfie",
    "paysage": "landscape", "realiste": "realistic", "photorealiste": "photorealistic", "cinematique": "cinematic",
    "packshot": "product photo", "mannequin": "model", "emballage": "packaging", "titre": "title", "titres": "title",
    "slogan": "slogan", "accroche": "hook", "script": "script", "scripts": "script", "legende": "caption",
    "legendes": "caption", "hashtags": "hashtags", "post": "post", "posts": "post", "marque": "brand",
    "client": "customer", "clients": "customer", "avis": "review", "traduction": "translation", "traduire": "translate",
    "resume": "summary", "resumer": "summarize", "code": "code", "site": "website", "site web": "website",
    "strategie": "strategy", "marketing": "marketing", "contenu": "content", "contenus": "content",
    "redaction": "copywriting", "copywriting": "copywriting", "redacteur": "copywriter", "copywriter": "copywriter",
    "vente": "sales", "ventes": "sales", "vendeur": "sales", "negociation": "negotiation", "objections": "objection",
    "expert": "expert", "coach": "coach", "professeur": "teacher", "prof": "teacher", "developpeur": "developer",
    "juridique": "legal", "avocat": "lawyer", "contrat": "contract", "comptable": "accountant",
    "comptabilite": "accounting", "finance": "finance", "trading": "trading", "investissement": "investment",
    "cv": "resume", "entretien": "interview", "recette": "recipe", "recettes": "recipe", "matcha": "matcha",
    "cuisine": "cooking", "voyage": "travel", "sante": "health", "sport": "fitness",
    "cours": "course", "formation": "course", "livre": "book", "livres": "book", "histoire": "story",
    "roman": "novel", "poeme": "poem", "chanson": "song", "musique": "music", "jeu": "game", "dessin": "drawing",
    "presentation": "presentation", "tableur": "spreadsheet", "excel": "excel", "analyse": "analysis",
    "donnees": "data", "recherche": "research", "idees": "ideas", "idee": "ideas", "produit": "product",
    "produits": "product", "prix": "pricing", "tarif": "pricing", "boutique": "store", "ecommerce": "ecommerce",
    "e-commerce": "ecommerce", "dropshipping": "dropshipping", "startup": "startup", "entreprise": "business",
    "business": "business", "agent": "agent", "automatisation": "automation", "chatbot": "chatbot",
    "tiktok": "tiktok", "instagram": "instagram", "youtube": "youtube", "pinterest": "pinterest",
    "facebook": "facebook", "linkedin": "linkedin", "twitter": "twitter", "shopify": "shopify", "amazon": "amazon",
    "etsy": "etsy", "notion": "notion", "wordpress": "wordpress", "python": "python", "javascript": "javascript",
    "react": "react", "n8n": "n8n", "midjourney": "midjourney", "ux": "ux", "ui": "ui", "design": "design",
    "debutant": "beginner", "persuasion": "persuasion", "storytelling": "storytelling", "ugc": "ugc",
}
CONTENT = {"product description", "product page", "email", "newsletter", "cold email", "ads", "listing", "article",
           "blog", "image", "photo", "video", "logo", "thumbnail", "poster", "illustration", "infographic", "portrait",
           "selfie", "product photo", "slogan", "hook", "script", "caption", "hashtags", "post", "cover letter",
           "copywriting", "recipe", "story", "novel", "poem", "song", "presentation", "brand name", "business plan"}
# Termes trop larges pour ancrer une recherche seuls (ils comptent quand même dans le titre).
GENERIC = {"store", "business", "content", "marketing", "expert", "product", "strategy", "ideas", "customer",
           "website", "post", "title", "brand", "sales", "design", "data", "analysis", "research", "course",
           "review", "pricing", "agent", "code", "image", "photo", "video", "realistic", "model"}
_PHRASES = sorted((k for k in LEX if " " in k or "-" in k or "'" in k), key=len, reverse=True)


def detect(raw) -> tuple:
    """Message → (déclencheur « ask »/« make »/None, termes anglais reconnus, type d'image/vidéo suggéré)."""
    from .journal import clean_prompt
    text = fold(clean_prompt(raw, 600))
    kind = "ask" if ASK_RX.search(text) else "make" if MAKE_RX.search(text) else None
    if not kind:
        return None, [], None
    terms, seen = [], set()

    def add(en):
        if en not in seen:
            seen.add(en)
            terms.append(en)
    for ph in _PHRASES:
        if ph in text:
            add(LEX[ph])
            text = text.replace(ph, " ")
    for w in re.findall(r"[a-z0-9]+", text):
        w = w if w in LEX or not w.endswith(("s", "x")) else w[:-1]  # « newsletters », « réseaux » → singulier
        if w in LEX:
            add(LEX[w])
    hint = next((t for t, rx in TYPE_HINT if rx.search(fold(raw))), None)
    return kind, terms, hint


# ------------------------------------------------------------------------------------------ Réseau
def call(tool, args, timeout=3.0):
    """Un appel d'outil MCP (HTTP « streamable », sans session) → le JSON du résultat. Lève une erreur sinon.
    BRAIN_OFFLINE=1 (tests, machine sans réseau) : aucun appel, erreur immédiate."""
    if os.environ.get("BRAIN_OFFLINE"):
        raise RuntimeError("réseau désactivé (BRAIN_OFFLINE)")
    import urllib.request
    from . import __version__
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": args}}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
        "User-Agent": f"cerveau-claude/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(4_000_000).decode("utf-8", "replace")
    data = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
    msg = json.loads(data[-1] if data else raw)
    if msg.get("error"):
        raise RuntimeError(msg["error"].get("message") or "erreur MCP")
    res = msg.get("result") or {}
    text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
    try:
        out = json.loads(text)
    except ValueError:
        out = {"text": text}
    if res.get("isError") or (isinstance(out, dict) and out.get("error") and len(out) == 1):
        raise RuntimeError(out.get("error") if isinstance(out, dict) else text)
    return out


def _slim(p) -> dict:
    return {"id": p.get("id"), "title": p.get("title") or "", "description": p.get("description") or "",
            "type": p.get("type") or ("SKILL" if "fileNames" in p else ""), "category": p.get("category") or "",
            "tags": [t if isinstance(t, str) else (t or {}).get("name", "") for t in p.get("tags") or []],
            "votes": p.get("votes") or 0, "author": p.get("author") or ""}


def _key(query, skills, limit) -> str:
    return f"{'skills' if skills else 'prompts'}:{fold(query).strip()}:{limit}"


def fetch(queries, skills=False, limit=50, timeout=3.0) -> dict:
    """Plusieurs recherches → {requête: éléments allégés}. Cache de CACHE_DAYS jours ; les manquantes partent en
    parallèle (≈ 0,3 s en tout) ; le cache est relu et écrit une seule fois (pas de course entre fils). Le site limite
    le débit : sur un HTTP 429, plus aucun appel pendant COOLDOWN secondes (le hook ne doit jamais insister)."""
    import urllib.error
    from concurrent.futures import ThreadPoolExecutor
    cache, now = read_json(CACHE_FILE, {}) or {}, time.time()
    res = {}
    for q in queries:
        hit = cache.get(_key(q, skills, limit))
        if hit and now - hit.get("t", 0) < CACHE_DAYS * 86400:
            res[q] = hit["items"]
    miss = [q for q in queries if q not in res]
    if not miss:
        return res
    wait = cache.get("_cooldown", 0) - now
    if wait > 0:
        raise RuntimeError(f"prompts.chat limite le débit : nouvel essai possible dans {int(wait // 60) + 1} min")
    tool = "search_skills" if skills else "search_prompts"
    with ThreadPoolExecutor(max_workers=len(miss)) as ex:
        futs = {q: ex.submit(call, tool, {"query": q, "limit": limit}, timeout) for q in miss}
    errors = []
    for q, f in futs.items():
        try:
            out = f.result()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                cache["_cooldown"] = now + COOLDOWN
            errors.append(exc)
            continue
        except Exception as exc:
            errors.append(exc)
            continue
        res[q] = [_slim(x) for x in (out.get("skills" if skills else "prompts") or []) if x.get("id")]
        cache[_key(q, skills, limit)] = {"t": now, "items": res[q]}
    entries = [k for k in cache if not k.startswith("_")]
    for k in sorted(entries, key=lambda k: cache[k].get("t", 0))[: max(0, len(entries) - CACHE_MAX)]:
        cache.pop(k, None)
    write_json(CACHE_FILE, cache, indent=None)
    if errors:
        log(f"prompts.chat : {len(errors)} recherche(s) en échec, ex. {errors[0]!r}")
        if not res:
            raise RuntimeError(f"prompts.chat injoignable : {errors[0]}")
    return res


def queries(terms, n=3) -> list:
    """La recherche du site cherche l'expression entière, mot à mot dans tout le texte et par date, pas par
    pertinence (« instagram post » : 0 ; « email » : un validateur de calendrier en tête). D'où : l'expression des
    deux premiers termes (précise), puis les termes seuls, les plus spécifiques d'abord ; le tri se fait dans `rank`."""
    qs = [f"{terms[0]} {terms[1]}"] if len(terms) >= 2 else []
    for t in sorted(terms, key=lambda t: t in GENERIC):
        if t not in qs:
            qs.append(t)
    return qs[:n]


# ------------------------------------------------------------------------------------------ Pertinence
def _has(term, toks) -> bool:
    return all(w in toks for w in tokenize(term, keep_stop=True))


# Écriture non latine (arabe, cyrillique, CJK…) : le modèle ne servira pas tel quel à un francophone.
FOREIGN_RX = re.compile(r"[\u0400-\u04ff\u0590-\u06ff\u0e00-\u0e7f\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]")


def rank(items, terms, hint=None, strict=True, need=None) -> list:
    """Classe et FILTRE sur le TITRE (le reste du texte matche trop large) : au moins `need` termes dans le titre
    (défaut min(2, nb de termes)), dont un spécifique s'il y en a. strict=False (commande manuelle) : tout est gardé,
    juste trié. Bonus au titre centré sur le sujet, malus à l'écriture non latine."""
    if not terms:
        return list(items) if not strict else []
    specific = [t for t in terms if t not in GENERIC]
    need = min(2, len(terms)) if need is None else need
    out, seen = [], set()
    for p in items:
        if p["id"] in seen:
            continue
        seen.add(p["id"])
        title = set(tokenize(p["title"], keep_stop=True))
        rest = title | set(tokenize(" ".join([p["description"], p["category"], *p["tags"]]), keep_stop=True))
        t_hits = [t for t in terms if _has(t, title)]
        if strict and (len(t_hits) < need or (specific and not set(t_hits) & set(specific))):
            continue
        # un terme spécifique dans le titre pèse 3, un générique (« store », « marketing »…) 1 seul
        score = (sum(1 if t in GENERIC else 3 for t in t_hits) + sum(1 for t in terms if _has(t, rest))
                 + (1 if hint and p["type"] == hint else 0) + 2 * len(t_hits) / max(1, len(title))
                 - (3 if FOREIGN_RX.search(p["title"] + p["description"]) else 0))
        out.append((score + min(p["votes"], 50) / 50, p))
    out.sort(key=lambda x: -x[0])
    return [p for _, p in out]


def suggest(raw, cfg, exclude=()) -> list:
    """Ce que le hook doit montrer pour ce message : 0 à max_items éléments vraiment liés, jamais d'exception."""
    try:
        kind, terms, hint = detect(raw)
        if not kind or not terms or (kind == "make" and (len(terms) < 2 or not CONTENT & set(terms))):
            return []
        skills = kind == "ask" and re.search(r"\bskills?\b", fold(raw)) is not None
        found = fetch(queries(terms, cfg.get("max_calls", 3)), skills=skills, timeout=cfg.get("timeout", 2.5))
        items = [p for q in found for p in found[q]]
        # demande explicite (« agis comme un expert SEO ») : un terme spécifique dans le titre suffit
        need = 1 if kind == "ask" and any(t not in GENERIC for t in terms[:4]) else None
        picks = [p for p in rank(items, terms[:4], hint, need=need) if p["id"] not in exclude]
        return picks[: cfg.get("max_items", 2)]
    except Exception as exc:  # réseau coupé, site en panne, format changé : le hook continue sans rien dire
        log(f"prompts.chat : {exc!r}")
        return []


def line(p) -> str:
    kind = p["type"] or "?"
    desc = f" — {short(p['description'], 110)}" if p["description"] else ""
    return f"- {short(p['title'], 70)} [{kind}]{desc} `{p['id']}`"


HEADER = "📚 prompts.chat — modèles proches (texte complet : `brain prompts get <id>`, à adapter) :"


# ------------------------------------------------------------------------------------------ Commande
def show(p) -> str:
    """Texte complet d'un prompt ou d'un skill (tous ses fichiers)."""
    try:
        data = call("get_prompt", {"id": p}, timeout=10)
    except RuntimeError:
        data = None
    if data is None or data.get("type") == "SKILL" or not data.get("content"):
        try:
            skill = call("get_skill", {"id": p}, timeout=10)
            files = skill.get("files") or []
            head = f"# {skill.get('title', '')} (skill, {skill.get('author') or '?'})\n{skill.get('description', '')}"
            body = [f"\n===== {f.get('filename') or f.get('name') or f.get('path')} =====\n{f.get('content', '')}"
                    for f in files]
            if files:
                return head + "".join(body)
        except RuntimeError:
            pass
    if data is None:
        return f"✗ introuvable sur prompts.chat : {p}"
    out = [f"# {data.get('title', '')} [{data.get('type', '')}] — {data.get('author') or '?'}"]
    if data.get("description"):
        out.append(data["description"])
    out.append("")
    out.append(data.get("content", ""))
    vars_ = data.get("variables") or []
    if vars_:
        out.append("\nVariables : " + ", ".join(v.get("name", str(v)) if isinstance(v, dict) else str(v) for v in vars_))
    return "\n".join(out)


def report(query, skills=False, n=8) -> str:
    _, terms, hint = detect(f"prompt {query}")
    q = " ".join(terms[:4]) or query
    try:
        found = fetch(queries(terms, 4) if terms else [query], skills=skills, timeout=10)
    except RuntimeError as exc:
        return f"✗ {exc}"
    items = [p for k in found for p in found[k]]
    strong = rank(items, terms[:4], hint)
    shown = (strong + [p for p in rank(items, terms[:4], hint, strict=False) if p not in strong])[:n]
    if not shown:
        return f"Rien sur prompts.chat pour « {q} »."
    head = f"prompts.chat — {len(shown)} résultat(s) pour « {q} »" + (f" (traduit de « {query} »)" if q != query else "")
    return "\n".join([head, *(line(p) for p in shown), "Texte complet : brain prompts get <id>"])
