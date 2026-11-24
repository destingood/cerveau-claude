"""Serveur MCP du cerveau (stdio, JSON-RPC 2.0) : la même mémoire depuis le chat Claude, Cowork ou tout client MCP.

Lancement : `python brain.py mcp` (c'est ce que le client exécute). Enregistrement dans l'app Claude desktop :
`brain install --mcp` (ajoute « cerveau » aux mcpServers de claude_desktop_config.json, avec sauvegarde du fichier).
Les outils renvoient le texte compact des commandes du cerveau : mêmes garde-fous (secrets masqués, anti-doublon,
historique), mêmes économies de tokens."""
from __future__ import annotations

import contextlib
import io
import json
import sys

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
TYPES = ["user", "feedback", "project", "decision", "fact", "learning", "reference", "entity", "todo", "source", "concept",
         "topic", "analysis"]

# Descriptions courtes (v8.13) : chaque client relit la liste des outils à chaque appel ; les commandes en disent
# le détail dans leur réponse.
PAGE = {"type": "integer", "description": "suite d'un résultat coupé"}  # outils de lecture : la suite d'un long résultat
TOOLS = [
    {"name": "memory_search",
     "description": "Chercher dans la mémoire de l'utilisateur (souvenirs, observations, sessions passées) ; tolère "
                    "fautes et synonymes. AVANT de lui redemander une information.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "mots clés ou question"},
         "limit": {"type": "integer", "description": "défaut 6, 30 au plus"},
         "project": {"type": "string", "description": "id ou nom"},
         "at": {"type": "string", "description": "état à une date passée"}, "page": PAGE},
         "required": ["query"]}},
    {"name": "memory_add",
     "description": "Mémoriser un fait durable (préférence, correction, décision, état d'un travail, piège résolu, "
                    "ressource, à-faire) ; anti-doublon.",
     "inputSchema": {"type": "object", "properties": {
         "type": {"type": "string", "enum": TYPES},
         "title": {"type": "string", "description": "court"},
         "body": {"type": "string", "description": "fait + pourquoi + comment l'appliquer"},
         "project": {"type": "string", "description": "id, « none » : global"},
         "due": {"type": "string", "description": "échéance (10/11, demain…)"},
         "replaces": {"type": "string", "description": "id du souvenir remplacé"},
         "keys": {"type": "string", "description": "synonymes pour le retrouver"},
         "resume": {"type": "string", "description": "wiki : une phrase, l'essentiel"},
         "sources": {"type": "string", "description": "wiki : « [[Titre]], … »"},
         "commun": {"type": "string", "enum": ["oui", "non", "auto"], "description": "partage aux amis"},
         "source": {"type": "string", "enum": ["utilisateur", "verifie", "claude", "deduit"],
                    "description": "provenance"}},
         "required": ["type", "title", "body"]}},
    {"name": "memory_show",
     "description": "Un souvenir en entier, avec ses liens.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "page": PAGE}, "required": ["id"]}},
    {"name": "memory_update",
     "description": "Corriger ou compléter un souvenir ; done : à-faire terminé ; archive : souvenir devenu faux.",
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string"},
         "append": {"type": "string", "description": "ajouté à la fin"},
         "body": {"type": "string", "description": "contenu complet"},
         "title": {"type": "string"},
         "importance": {"type": "integer", "description": "1 à 5"},
         "due": {"type": "string", "description": "« none » : sans échéance"},
         "resume": {"type": "string", "description": "wiki : résumé"},
         "sources": {"type": "string", "description": "wiki : Sources ajoutées"},
         "commun": {"type": "string", "enum": ["oui", "non", "auto"]},
         "done": {"type": "boolean"},
         "archive": {"type": "boolean"}},
         "required": ["id"]}},
    {"name": "memory_todo",
     "description": "À-faire triés par échéance.",
     "inputSchema": {"type": "object", "properties": {"page": PAGE}}},
    {"name": "memory_context",
     "description": "Ce que le cerveau sait d'emblée (profil, règles, projets, échéances ; fiche du projet si folder). "
                    "En début de conversation.",
     "inputSchema": {"type": "object", "properties": {"folder": {"type": "string", "description": "dossier du projet"},
                                                      "page": PAGE}}},
    {"name": "wiki_status",
     "description": "État du wiki : pages par type, sources à ingérer, git, journal.",
     "inputSchema": {"type": "object", "properties": {"schema": {"type": "boolean", "description": "avec sa méthode complète"}}}},
    {"name": "wiki_add_source",
     "description": "Ranger une source (article, transcription, note…) : raw/ + page Sources, renvoie le plan "
                    "d'ingestion. Puis memory_update / memory_add des pages liées, puis wiki_log.",
     "inputSchema": {"type": "object", "properties": {
         "title": {"type": "string"}, "text": {"type": "string", "description": "contenu complet"},
         "url": {"type": "string"},
         "format": {"type": "string", "description": "article, video, podcast, livre, note, conversation…"}},
         "required": ["title", "text"]}},
    {"name": "wiki_lint",
     "description": "Santé du wiki : pages manquantes, orphelines, sans résumé, dépassées, doublons, contradictions.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "wiki_log",
     "description": "Entrée au journal du wiki (log.md : ingest, query, lint, note) ; régénère l'index.",
     "inputSchema": {"type": "object", "properties": {
         "operation": {"type": "string"}, "title": {"type": "string"},
         "lines": {"type": "array", "items": {"type": "string"}}}, "required": ["operation", "title"]}},
]


TOOLS += [
    {"name": "boutique_etat",
     "description": "Boutiques suivies (liste) ou bilan d'une boutique : chiffres, tendance testée, plan, audits, "
                    "3 priorités. Avant de conseiller une boutique.",
     "inputSchema": {"type": "object", "properties": {
         "boutique": {"type": "string", "description": "slug ou nom (vide : la liste)"},
         "semaines": {"type": "integer", "description": "défaut 4"}}}},
    {"name": "boutique_ajouter",
     "description": "Suivre une boutique : fichier de suivi privé + fiche en mémoire.",
     "inputSchema": {"type": "object", "properties": {
         "nom": {"type": "string"}, "url": {"type": "string"},
         "plateforme": {"type": "string", "description": "shopify, woocommerce, site statique…"},
         "chemin": {"type": "string", "enum": ["plateforme", "0euro"]},
         "type": {"type": "string", "enum": ["physique", "mode", "createur", "occasion", "niche", "prevente", "local",
                                             "numerique", "b2b"]},
         "marge_commande": {"type": "number", "description": "€ par commande"}},
         "required": ["nom"]}},
    {"name": "boutique_plan",
     "description": "Plan décollage daté (72 h, 14 j, 30-60-90) en à-faire rappelés à l'échéance.",
     "inputSchema": {"type": "object", "properties": {
         "boutique": {"type": "string"}, "debut": {"type": "string", "description": "défaut aujourd'hui"},
         "court": {"type": "boolean", "description": "72 h et 14 j seulement"}},
         "required": ["boutique"]}},
    {"name": "boutique_kpi",
     "description": "Chiffres d'une semaine (lundi-dimanche) : taux, panier, marge par heure, comparaison testée, goulot.",
     "inputSchema": {"type": "object", "properties": {
         "boutique": {"type": "string"}, "sessions": {"type": "number"}, "ajouts": {"type": "number"},
         "checkouts": {"type": "number"}, "commandes": {"type": "number"}, "ca": {"type": "number"},
         "heures": {"type": "number"}, "marge": {"type": "number", "description": "totale"},
         "canaux": {"type": "array", "items": {"type": "string"}, "description": "« nom:sessions:commandes[:heures] »"},
         "semaine": {"type": "string", "description": "une date (défaut : dernière semaine complète)"},
         "note": {"type": "string"}},
         "required": ["boutique", "sessions", "commandes"]}},
    {"name": "boutique_audit",
     "description": "Audit SEO/GEO d'une boutique ou d'une URL : balises, données structurées, robots IA, sitemap ; "
                    "options : conformité légale, pages, vitesse.",
     "inputSchema": {"type": "object", "properties": {
         "boutique": {"type": "string", "description": "slug ou URL"},
         "conformite": {"type": "boolean", "description": "pages légales"},
         "pages": {"type": "integer", "description": "pages du sitemap lues (0 à 50)"},
         "vitesse": {"type": "boolean", "description": "Core Web Vitals mobile, 20 à 60 s"}},
         "required": ["boutique"]}},
]

# Groupes d'outils (décision du 21/11) : la mémoire toujours ; le wiki et les boutiques seulement si la configuration
# les ajoute (`brain config mcp.groupes '["wiki", "boutique"]'`) — 15 outils listés à chaque requête, c'était 6 600
# caractères relus par chaque client, Claude Code compris (le plugin déclare ce serveur).
GROUPS = {"memory_": "memoire", "wiki_": "wiki", "boutique_": "boutique"}
EXTRA = ("wiki", "boutique")
ALL = ("tout", "tous", "all")
MAX_CHARS = 8000  # défaut de mcp.max_car : au-delà, le résultat est coupé en pages
READ_ONLY = {"memory_search", "memory_show", "memory_todo", "memory_context", "wiki_status", "wiki_lint", "boutique_etat"}
_PAGES = {}  # (outil, arguments sans « page ») → résultat complet du dernier appel coupé (le serveur vit toute la session)
_PAGES_KEEP = 8

PROMPT = {"name": "contexte", "description": "Injecter ce que le cerveau sait de moi (profil, règles, projets, "
                                            "échéances) au début de la conversation."}


def _cfg() -> dict:
    try:
        from .common import load_config
        c = load_config().get("mcp")
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def groups(cfg=None) -> list:
    """Groupes d'outils listés : « memoire », plus ceux de mcp.groupes (liste, ou texte « wiki,boutique » ; « tout »)."""
    cfg = _cfg() if cfg is None else cfg
    want = cfg.get("groupes") or []
    if isinstance(want, str):
        want = [w for w in want.replace(";", ",").split(",")]
    want = {str(w).strip().lower() for w in want if isinstance(w, (str, int))} if isinstance(want, (list, tuple)) else set()
    extra = list(EXTRA) if want & set(ALL) else [g for g in EXTRA if g in want]
    return ["memoire", *extra]


def group_of(name) -> str:
    return next((g for prefix, g in GROUPS.items() if str(name).startswith(prefix)), "")


def tools(cfg=None) -> list:
    """La liste rendue par tools/list : les outils des groupes actifs seulement."""
    active = groups(cfg)
    return [t for t in TOOLS if group_of(t["name"]) in active]


def _limit(cfg=None) -> int:
    cfg = _cfg() if cfg is None else cfg
    v = cfg.get("max_car", MAX_CHARS)
    return max(1000, v) if isinstance(v, int) and not isinstance(v, bool) else MAX_CHARS


def pages_of(text, limit) -> list:
    """Le texte en pages d'au plus `limit` caractères, coupées entre deux lignes (une ligne plus longue qu'une page est
    coupée elle-même)."""
    out, cur = [], ""
    for line in str(text).split("\n"):
        while len(line) > limit:
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:limit])
            line = line[limit:]
        if cur and len(cur) + 1 + len(line) > limit:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur or not out:
        out.append(cur)
    return out


def bounded(name, args, run, limit=None):
    """Résultat d'un outil borné à `limit` caractères (mcp.max_car) : page `args["page"]` d'un résultat plus long, avec
    en fin de page ce qui reste et comment demander la suite. La suite d'un outil qui écrit (memory_add…) vient du
    résultat gardé, jamais d'un second appel : rien n'est écrit deux fois."""
    limit = limit or _limit()
    try:
        page = max(1, int(args.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    key = (name, json.dumps({k: v for k, v in args.items() if k != "page"}, sort_keys=True, ensure_ascii=False,
                            default=str))
    if page > 1 and key in _PAGES:
        text, err = _PAGES[key]
    elif page > 1 and name not in READ_ONLY:
        return (f"page {page} : le résultat de {name} n'est plus gardé ; relancer l'outil sans « page » (il écrit : "
                "vérifier d'abord avec memory_search que ce n'est pas déjà fait)"), True
    else:
        text, err = run()
    parts = pages_of(text, limit)
    if len(parts) > 1:
        _PAGES.pop(key, None)
        _PAGES[key] = (text, err)
        while len(_PAGES) > _PAGES_KEEP:
            _PAGES.pop(next(iter(_PAGES)))
    if page > len(parts):
        return f"page {page} : ce résultat n'a que {len(parts)} page(s)", True
    out = parts[page - 1]
    if page < len(parts):
        rest = sum(len(x) + 1 for x in parts[page:])
        out += (f"\n… page {page}/{len(parts)} — encore {rest} caractères : rappeler {name} avec les mêmes arguments "
                f"et page: {page + 1}")
    return out, err


def _run_cli(argv):
    """Exécute une commande du cerveau et capture sa sortie (stdout est réservé au protocole MCP)."""
    from . import cli
    if "--" in argv:  # seulement s'il sert : Python 3.10 et 3.11 refusent « -- » après une sous-commande de sous-commande
        i = argv.index("--")  # (« boutique etat -- atelier » : argument inattendu)
        if not any(str(x).startswith("-") for x in argv[i + 1:]):
            argv = argv[:i] + argv[i + 1:]
    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()) as err:
        try:
            code = cli.main(argv) or 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        except Exception as exc:  # jamais de plantage du serveur, jamais de trace Python dans un résultat
            code = 1
            print(_internal(exc, argv[0] if argv else "?"))
    text, warn = buf.getvalue().strip(), err.getvalue().strip()
    if warn:  # erreurs (✗ …) et avertissements (🔒 secret masqué…) utiles au modèle ; pas l'aide de la ligne de commande
        lines = [x for x in warn.splitlines() if not x.startswith(("utilisation : ", "  aide : `brain", " " * 6))]
        text = f"{text}\n" + "\n".join(lines)
    text = text.strip()
    return text or (f"échec sans message (code {code})" if code else "(rien)"), bool(code)



def _value_first(argv, value):
    """« boutique <action> <valeur> --options… » : la valeur juste après l'action. Python 3.10 et 3.11 rangent un argument
    positionnel facultatif trop tôt quand une option le précède (« boutique bilan --semaines=4 atelier » : argument
    inattendu) ; après « -- » seulement si elle commence par « - »."""
    head, opts = argv[:2], argv[2:]
    return head + [value] + opts if not str(value).startswith("-") else argv + ["--", value]


def _internal(exc, where) -> str:
    """Erreur inattendue → une phrase en français (le détail, trace comprise, va au journal du cerveau)."""
    import traceback
    try:
        from .common import LOG_FILE, log
        log(f"serveur MCP ({where}) : {exc!r}\n{traceback.format_exc()}")
        detail = f" ; détail dans {LOG_FILE}"
    except Exception:
        detail = ""
    return f"✗ erreur inattendue du cerveau ({type(exc).__name__}) pendant {where}{detail} — `brain doctor` pour le diagnostic"


class Bad(ValueError):
    """Argument d'outil refusé : le message (en français) part tel quel dans le résultat, isError vrai."""


def _kind(v) -> str:
    return {list: "une liste", dict: "un objet", bool: "vrai/faux"}.get(type(v), type(v).__name__)


def _txt(args, key, required=False, missing=None):
    """Argument texte : absent ou vide → None (ou refus s'il est obligatoire : `missing`, sinon « argument manquant ») ;
    nombre accepté ; liste, objet → refus."""
    v = args.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise Bad(missing or f"argument manquant : « {key} » (texte)")
        return None
    if isinstance(v, bool) or not isinstance(v, (str, int, float)):
        raise Bad(f"« {key} » : texte attendu, pas {_kind(v)}")
    return str(v)


def _int(args, key, lo, hi, default=None, clamp=False):
    v = args.get(key)
    if v is None or v == "":
        return default
    try:
        if isinstance(v, bool) or (isinstance(v, float) and v != int(v)):
            raise ValueError
        n = int(v)
    except (TypeError, ValueError):
        raise Bad(f"« {key} » : nombre entier attendu ({lo} à {hi}), pas {json.dumps(v, ensure_ascii=False)[:40]}") from None
    if clamp:
        return max(lo, min(n, hi))
    if not lo <= n <= hi:
        raise Bad(f"« {key} » : {n} hors limites, de {lo} à {hi}")
    return n


def _num(args, key):
    v = args.get(key)
    if v is None or v == "":
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise Bad(f"« {key} » : nombre attendu, pas {_kind(v)}")
    try:
        float(str(v).replace(",", "."))
    except ValueError:
        raise Bad(f"« {key} » : nombre attendu, pas « {str(v)[:40]} »") from None
    return str(v)


def _flag(args, key) -> bool:
    v = args.get(key)
    if v is None or isinstance(v, bool):
        return bool(v)
    if isinstance(v, str) and v.strip().lower() in ("true", "false", "oui", "non", "1", "0", ""):
        return v.strip().lower() in ("true", "oui", "1")
    if isinstance(v, int):
        return bool(v)
    raise Bad(f"« {key} » : vrai ou faux attendu (true/false), pas {json.dumps(v, ensure_ascii=False)[:40]}")


def _choice(args, key, options):
    v = _txt(args, key)
    if v is not None and v not in options:
        raise Bad(f"« {key} » : « {v} » inconnu — au choix : {', '.join(options)}")
    return v


def _opt(argv, flag, value):
    """Option collée à sa valeur (« --title=-rf ») : une valeur qui commence par « - » n'est jamais prise pour une
    option (avant : « unrecognized arguments » d'argparse, en anglais, dans le résultat)."""
    if value is not None:
        argv.append(f"{flag}={value}")


def call_tool(name, args):
    """Un appel d'outil → (texte, erreur ?). Un outil d'un groupe désactivé répond comment l'activer ; tout résultat est
    borné (bounded). Arguments vérifiés (type, obligatoires, bornes) : un refus dit en français ce qui ne va pas."""
    if not isinstance(name, str) or not name:
        return "nom d'outil manquant (« name » dans params)", True
    if args is not None and not isinstance(args, dict):
        return f"« arguments » : objet JSON attendu, pas {_kind(args)}", True
    args = args or {}
    if not any(t["name"] == name for t in TOOLS):
        return f"outil inconnu : {name} — outils de ce serveur : {', '.join(t['name'] for t in tools())}", True
    group = group_of(name)
    if group and group not in groups():
        return (f"outil {name} désactivé sur ce serveur : `brain config mcp.groupes '[\"{group}\"]'` l'ajoute à la liste "
                "(les outils de la mémoire sont toujours là)"), True
    try:
        _int(args, "page", 1, 10 ** 6)
    except Bad as exc:
        return f"✗ {exc}", True

    def run():
        try:
            return _call(name, args)
        except Bad as exc:
            return f"✗ {exc}", True
        except Exception as exc:
            return _internal(exc, name), True
    return bounded(name, args, run)


def _call(name, args):
    if name == "memory_search":
        argv = ["q", "-k", str(_int(args, "limit", 1, 30, 6, clamp=True)), "--no-files"]
        _opt(argv, "--project", _txt(args, "project"))
        _opt(argv, "--at", _txt(args, "at"))
        return _run_cli(argv + ["--", _txt(args, "query", required=True)])
    if name == "memory_add":
        argv = ["add", f"--type={_choice(args, 'type', TYPES) or 'fact'}", f"--title={_txt(args, 'title', True, 'titre vide : « title » est obligatoire (court)')}",
                f"--body={_txt(args, 'body', required=True)}", f"--project={_txt(args, 'project') or 'none'}"]
        for key in ("due", "replaces", "keys", "resume", "sources"):
            _opt(argv, f"--{key}", _txt(args, key))
        _opt(argv, "--commun", _choice(args, "commun", ("oui", "non", "auto")))
        _opt(argv, "--source", _choice(args, "source", ("utilisateur", "verifie", "claude", "deduit")) or "mcp")
        return _run_cli(argv)
    if name == "memory_show":
        return _run_cli(["show", "--", _txt(args, "id", required=True)])
    if name == "memory_update":
        nid = _txt(args, "id", required=True)
        if _flag(args, "done"):
            return _run_cli(["done", "--", nid])
        if _flag(args, "archive"):
            return _run_cli(["rm", "--", nid])
        argv = ["edit"]
        for key in ("append", "body", "title", "due", "resume", "sources"):
            _opt(argv, f"--{key}", _txt(args, key))
        imp = _int(args, "importance", 1, 5)
        _opt(argv, "--importance", None if imp is None else str(imp))
        _opt(argv, "--commun", _choice(args, "commun", ("oui", "non", "auto")))
        if len(argv) == 1:
            return "rien à modifier : donner append, body, title, importance, due, done ou archive", True
        return _run_cli(argv + ["--", nid])
    if name == "memory_todo":
        return _run_cli(["todo"])
    if name == "memory_context":
        import os
        text, err = _run_cli(["context", f"--cwd={_txt(args, 'folder') or os.path.expanduser('~')}"])
        return text.rsplit("\n--- injecté", 1)[0], err
    if name == "wiki_status":
        text, err = _run_cli(["wiki", "status"])
        if _flag(args, "schema") and not err:
            more, _ = _run_cli(["wiki", "schema"])
            text = f"{text}\n\n{more}"
        return text, err
    if name == "wiki_add_source":
        from . import wiki
        title, text, url, fmt = (_txt(args, "title", required=True), _txt(args, "text", required=True),
                                 _txt(args, "url"), _txt(args, "format"))
        try:
            info = wiki.add_source(None, title=title, fmt=fmt, url=url, text=text)
            out = wiki.ingest_plan(info)
            wiki.write_index()
            return out, False
        except OSError as exc:
            from .common import oserror_fr
            return f"✗ {oserror_fr(exc)}", True
        except (RuntimeError, ValueError) as exc:
            return f"✗ {exc}", True
    if name == "boutique_etat":
        shop = _txt(args, "boutique")
        if not shop:
            return _run_cli(["boutique", "liste"])
        return _run_cli(_value_first(["boutique", "bilan", f"--semaines={_int(args, 'semaines', 1, 520, 4)}"], shop))
    if name == "boutique_ajouter":
        argv = ["boutique", "ajouter"]
        _opt(argv, "--url", _txt(args, "url"))
        _opt(argv, "--plateforme", _txt(args, "plateforme"))
        _opt(argv, "--chemin", _choice(args, "chemin", ("plateforme", "0euro")))
        _opt(argv, "--type", _choice(args, "type", ("physique", "mode", "createur", "occasion", "niche", "prevente",
                                                     "local", "numerique", "b2b")))
        _opt(argv, "--marge-commande", _num(args, "marge_commande"))
        return _run_cli(_value_first(argv, _txt(args, "nom", required=True)))
    if name == "boutique_plan":
        argv = ["boutique", "plan"]
        _opt(argv, "--debut", _txt(args, "debut"))
        if _flag(args, "court"):
            argv.append("--court")
        return _run_cli(_value_first(argv, _txt(args, "boutique", required=True)))
    if name == "boutique_kpi":
        argv = ["boutique", "kpi"]
        shop = _txt(args, "boutique", required=True)
        for key in ("sessions", "commandes"):
            if args.get(key) in (None, ""):
                raise Bad(f"argument manquant : « {key} » (nombre)")
        for key in ("sessions", "ajouts", "checkouts", "commandes", "ca", "heures", "marge"):
            _opt(argv, f"--{key}", _num(args, key))
        for key in ("semaine", "note"):
            _opt(argv, f"--{key}", _txt(args, key))
        canaux = args.get("canaux") or []
        if not isinstance(canaux, list):
            raise Bad("« canaux » : liste attendue, ex. [\"google:120:3\"]")
        for spec in canaux:
            _opt(argv, "--canal", str(spec))
        return _run_cli(_value_first(argv, shop))
    if name == "boutique_audit":
        argv = ["boutique", "audit"]
        if _flag(args, "conformite"):
            argv.append("--conformite")
        if _flag(args, "vitesse"):
            argv.append("--vitesse")
        pages = _int(args, "pages", 0, 50, 0, clamp=True)
        if pages:
            argv.append(f"--pages={pages}")
        return _run_cli(_value_first(argv, _txt(args, "boutique", required=True)))
    if name == "wiki_lint":
        return _run_cli(["wiki", "lint"])
    if name == "wiki_log":
        lines = args.get("lines") or []
        if not isinstance(lines, list):
            raise Bad("« lines » : liste de lignes attendue")
        return _run_cli(["wiki", "log", "--", _txt(args, "operation") or "note", _txt(args, "title", required=True),
                         *[str(x) for x in lines]])
    return f"outil inconnu : {name}", True


def handle(msg):
    """Une requête JSON-RPC → la réponse (ou None pour une notification)."""
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:  # notification (initialized, cancelled…) : pas de réponse
        return None
    try:
        if method == "initialize":
            from . import __version__
            asked = msg["params"].get("protocolVersion") if isinstance(msg.get("params"), dict) else None
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                "capabilities": {"tools": {"listChanged": False}, "prompts": {"listChanged": False}},
                "serverInfo": {"name": "cerveau", "version": __version__},
                "instructions": "Mémoire persistante de l'utilisateur : chercher (memory_search) avant de redemander, "
                                "mémoriser (memory_add) ce qui est durable, jamais de secret."}}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": mid, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools()}}
        if method == "tools/call":
            p = msg.get("params") or {}
            if not isinstance(p, dict):
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": "params : objet JSON attendu "
                                                                                          "({\"name\": …, \"arguments\": {…}})"}}
            text, is_err = call_tool(p.get("name"), p.get("arguments"))
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text or "(vide)"}],
                                                             "isError": is_err}}
        if method == "prompts/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"prompts": [PROMPT]}}
        if method == "prompts/get":
            if not isinstance(msg.get("params"), dict) or msg["params"].get("name") != PROMPT["name"]:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "prompt inconnu"}}
            text, _ = call_tool("memory_context", {})
            return {"jsonrpc": "2.0", "id": mid, "result": {"description": PROMPT["description"], "messages": [
                {"role": "user", "content": {"type": "text", "text": "Contexte de ma mémoire persistante (à utiliser "
                                                                     "sans le répéter) :\n\n" + text}}]}}
        if method == "resources/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"resources": []}}
        if method == "resources/templates/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"resourceTemplates": []}}
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"méthode inconnue : {method}"}}
    except Exception as exc:  # jamais de trace ni de repr Python en anglais : une phrase, le détail au journal
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": _internal(exc, str(method))}}


def serve():
    from . import common
    common.LAZY = True  # comme les hooks : l'analyse du graphe en cache, même périmée, jamais recalculée pendant un appel
    out = sys.stdout.buffer
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON invalide"}}
        else:
            resp = handle(msg) if isinstance(msg, dict) else None
        if resp is not None:
            out.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
            out.flush()
    return 0


def register(dry=False, remove=False):
    """Ajoute (ou retire) « cerveau » des serveurs MCP de l'app Claude desktop (claude_desktop_config.json), avec
    sauvegarde du fichier. Rien d'autre n'est touché dans la configuration."""
    import os
    import shutil
    import time
    from pathlib import Path
    from .common import BRAIN_DIR, PLUGIN
    script = (BRAIN_DIR if PLUGIN else Path(__file__).resolve().parent.parent) / "brain.py"  # plugin : lanceur stable
    cfg_path = os.path.join(os.environ.get("APPDATA", ""), "Claude", "claude_desktop_config.json")
    if not os.path.exists(cfg_path):
        raise RuntimeError(f"configuration de l'app introuvable : {cfg_path}")
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    entry = {"command": sys.executable, "args": ["-I", "-S", str(script), "mcp"]}
    servers = cfg.get("mcpServers") or {}
    if (remove and "cerveau" not in servers) or (not remove and servers.get("cerveau") == entry):
        return cfg_path, False
    if dry:
        return cfg_path, True
    shutil.copy2(cfg_path, f"{cfg_path}.avant-cerveau-{time.strftime('%Y%m%d-%H%M%S')}.bak")
    if remove:
        servers.pop("cerveau", None)
    else:
        servers["cerveau"] = entry
    cfg["mcpServers"] = servers
    tmp = cfg_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, cfg_path)
    return cfg_path, True
