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

TOOLS = [
    {"name": "memory_search",
     "description": "Chercher dans la mémoire persistante de l'utilisateur (préférences, décisions, faits, apprentissages, "
                    "projets, à-faire), ses observations datées et ses sessions passées. Tolère fautes, écriture "
                    "phonétique et synonymes ; une question large (« où en est… ») reçoit d'abord la fiche de synthèse "
                    "du sujet. À utiliser AVANT de lui redemander une information.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "mots clés ou question"},
         "limit": {"type": "integer", "description": "nombre de résultats (défaut 6)"},
         "project": {"type": "string", "description": "id ou nom de projet pour restreindre"}},
         "required": ["query"]}},
    {"name": "memory_add",
     "description": "Mémoriser un fait durable (préférence ou correction de l'utilisateur, décision, état d'un travail, "
                    "piège résolu, ressource, à-faire). Anti-doublon et détection des mises à jour intégrés ; secrets masqués.",
     "inputSchema": {"type": "object", "properties": {
         "type": {"type": "string", "enum": TYPES},
         "title": {"type": "string", "description": "titre court"},
         "body": {"type": "string", "description": "le fait + pourquoi + comment l'appliquer"},
         "project": {"type": "string", "description": "id de projet, ou « none » pour global"},
         "due": {"type": "string", "description": "échéance d'un à-faire (10/11, demain, dans 2 semaines)"},
         "replaces": {"type": "string", "description": "id du souvenir que celui-ci remplace"},
         "keys": {"type": "string", "description": "mots-clés, synonymes, questions types pour le retrouver"},
         "resume": {"type": "string", "description": "page du wiki : une phrase qui dit l'essentiel"},
         "sources": {"type": "string", "description": "page du wiki : pages Sources qui l'appuient (« [[Titre]], … »)"},
         "commun": {"type": "string", "enum": ["oui", "non", "auto"],
                    "description": "cerveau commun des amis : oui = partager, non = garder privé, auto = règles par défaut"},
         "source": {"type": "string", "enum": ["utilisateur", "verifie", "claude", "deduit"],
                    "description": "provenance : dit par l'utilisateur, vérifié, Claude, déduit"}},
         "required": ["type", "title", "body"]}},
    {"name": "memory_show",
     "description": "Afficher un souvenir complet : contenu, liens, communauté, concepts, liens suggérés.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    {"name": "memory_update",
     "description": "Corriger ou compléter un souvenir existant (ajout de texte, nouveau contenu, titre, importance, "
                    "échéance), marquer un à-faire comme terminé (done) ou archiver un souvenir devenu faux.",
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string"},
         "append": {"type": "string", "description": "texte à ajouter à la fin"},
         "body": {"type": "string", "description": "nouveau contenu complet"},
         "title": {"type": "string"},
         "importance": {"type": "integer", "description": "1 à 5"},
         "due": {"type": "string", "description": "échéance, « none » pour l'enlever"},
         "resume": {"type": "string", "description": "page du wiki : nouveau résumé"},
         "sources": {"type": "string", "description": "page du wiki : pages Sources à ajouter"},
         "commun": {"type": "string", "enum": ["oui", "non", "auto"], "description": "cerveau commun : partager ou non"},
         "done": {"type": "boolean", "description": "à-faire terminé"},
         "archive": {"type": "boolean", "description": "archiver (réversible)"}},
         "required": ["id"]}},
    {"name": "memory_todo",
     "description": "Lister les à-faire de l'utilisateur triés par échéance (en retard, bientôt, sans date).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "memory_context",
     "description": "Ce que le cerveau sait d'emblée : profil, règles, projets, échéances, savoir global (et la fiche "
                    "d'un projet si un dossier est donné). À appeler en début de conversation.",
     "inputSchema": {"type": "object", "properties": {"folder": {"type": "string", "description": "dossier du projet"}}}},
    {"name": "wiki_status",
     "description": "Le wiki du cerveau (si le cerveau vit dans un wiki Markdown) : pages par type, sources à ingérer, "
                    "synchronisation git, dernières entrées du journal, et son schéma (méthode d'ingestion, conventions).",
     "inputSchema": {"type": "object", "properties": {"schema": {"type": "boolean", "description": "donner aussi le schéma complet"}}}},
    {"name": "wiki_add_source",
     "description": "Ranger une source dans le wiki (texte d'un article, d'une transcription, d'une note, d'une "
                    "conversation) : elle part dans raw/ (immuable) et sa page Sources est créée ; renvoie le plan "
                    "d'ingestion (pages concernées, entités repérées). Ensuite : remplir la page (memory_update), "
                    "mettre à jour les pages liées (memory_add / memory_update), puis wiki_log.",
     "inputSchema": {"type": "object", "properties": {
         "title": {"type": "string"}, "text": {"type": "string", "description": "contenu complet de la source"},
         "url": {"type": "string", "description": "adresse d'origine"},
         "format": {"type": "string", "description": "article, video, podcast, livre, note, conversation, donnees…"}},
         "required": ["title", "text"]}},
    {"name": "wiki_lint",
     "description": "Contrôle de santé du wiki : pages à créer, orphelines, sans résumé, sources à ingérer ou abîmées, "
                    "pages dépassées, doublons, contradictions, souvenirs à verser dans une page de savoir.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "wiki_log",
     "description": "Ajouter une entrée au journal du wiki (log.md) : opération (ingest, query, lint, note), titre, "
                    "lignes (pages touchées…). Régénère l'index.",
     "inputSchema": {"type": "object", "properties": {
         "operation": {"type": "string"}, "title": {"type": "string"},
         "lines": {"type": "array", "items": {"type": "string"}}}, "required": ["operation", "title"]}},
]


TOOLS += [
    {"name": "boutique_etat",
     "description": "Boutiques en ligne suivies par le cerveau (sans argument : la liste, avec la dernière semaine, le "
                    "plan et le dernier audit) ou le bilan complet d'une boutique (chiffres des dernières semaines, "
                    "tendance testée, plan en retard ou à venir, audits, trois priorités). À appeler avant de conseiller "
                    "une boutique.",
     "inputSchema": {"type": "object", "properties": {
         "boutique": {"type": "string", "description": "slug ou nom de la boutique (vide : la liste)"},
         "semaines": {"type": "integer", "description": "semaines dans le bilan (défaut 4)"}}}},
    {"name": "boutique_ajouter",
     "description": "Faire suivre une boutique par le cerveau : fichier de suivi privé et fiche contexte en mémoire.",
     "inputSchema": {"type": "object", "properties": {
         "nom": {"type": "string"}, "url": {"type": "string"},
         "plateforme": {"type": "string", "description": "shopify, woocommerce, site statique, marketplace…"},
         "chemin": {"type": "string", "enum": ["plateforme", "0euro"]},
         "type": {"type": "string", "enum": ["physique", "mode", "createur", "occasion", "niche", "prevente", "local",
                                             "numerique", "b2b"]},
         "marge_commande": {"type": "number", "description": "marge de contribution par commande (€)"}},
         "required": ["nom"]}},
    {"name": "boutique_plan",
     "description": "Créer le plan décollage daté d'une boutique (72 h, 14 jours, 30-60-90) sous forme d'à-faire du "
                    "cerveau, rappelés à l'approche de leur échéance.",
     "inputSchema": {"type": "object", "properties": {
         "boutique": {"type": "string"}, "debut": {"type": "string", "description": "premier jour (défaut aujourd'hui)"},
         "court": {"type": "boolean", "description": "72 h et 14 jours seulement"}},
         "required": ["boutique"]}},
    {"name": "boutique_kpi",
     "description": "Relever les chiffres d'une semaine complète (lundi-dimanche) d'une boutique : renvoie taux, panier "
                    "moyen, marge par heure, comparaison testée statistiquement aux semaines d'avant et goulot probable.",
     "inputSchema": {"type": "object", "properties": {
         "boutique": {"type": "string"}, "sessions": {"type": "number"}, "ajouts": {"type": "number"},
         "checkouts": {"type": "number"}, "commandes": {"type": "number"}, "ca": {"type": "number"},
         "heures": {"type": "number"}, "marge": {"type": "number", "description": "marge totale de la semaine"},
         "canaux": {"type": "array", "items": {"type": "string"},
                    "description": "par canal : « nom:sessions:commandes[:heures] »"},
         "semaine": {"type": "string", "description": "une date de la semaine (défaut : dernière semaine complète)"},
         "note": {"type": "string"}},
         "required": ["boutique", "sessions", "commandes"]}},
    {"name": "boutique_audit",
     "description": "Audit SEO/GEO express d'une boutique suivie ou d'une adresse : balises, données structurées, "
                    "robots des moteurs et des assistants IA, sitemap ; en option conformité (pages légales, "
                    "rétractation, médiateur, cookies…), pages du sitemap (doublons, erreurs, noindex) et vitesse "
                    "(PageSpeed Insights) ; historique gardé (corrigé / nouveau).",
     "inputSchema": {"type": "object", "properties": {
         "boutique": {"type": "string", "description": "slug d'une boutique suivie, ou une URL"},
         "conformite": {"type": "boolean", "description": "lire et contrôler les pages légales"},
         "pages": {"type": "integer", "description": "nombre de pages du sitemap à lire (0 à 50)"},
         "vitesse": {"type": "boolean", "description": "Core Web Vitals mobile (lent : 20 à 60 s)"}},
         "required": ["boutique"]}},
]

PROMPT = {"name": "contexte", "description": "Injecter ce que le cerveau sait de moi (profil, règles, projets, "
                                            "échéances) au début de la conversation."}


def _run_cli(argv):
    """Exécute une commande du cerveau et capture sa sortie (stdout est réservé au protocole MCP)."""
    from . import cli
    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()) as err:
        try:
            code = cli.main(argv) or 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        except Exception as exc:  # jamais de plantage du serveur
            code = 1
            print(f"erreur : {exc!r}")
    text, warn = buf.getvalue().strip(), err.getvalue().strip()
    if warn:  # erreurs (✗ …) et avertissements (🔒 secret masqué…) utiles au modèle
        text = f"{text}\n{warn}".strip()
    return text or ("erreur" if code else "(rien)"), bool(code)


def call_tool(name, args):
    args = args or {}
    if name == "memory_search":
        argv = ["q", str(args.get("query", "")), "-k", str(int(args.get("limit") or 6)), "--no-files"]
        if args.get("project"):
            argv += ["-p", str(args["project"])]
        return _run_cli(argv)
    if name == "memory_add":
        argv = ["add", "-t", str(args.get("type", "fact")), "-T", str(args.get("title", "")), "-b", str(args.get("body", ""))]
        argv += ["-p", str(args["project"])] if args.get("project") else ["-p", "none"]
        if args.get("due"):
            argv += ["--due", str(args["due"])]
        if args.get("replaces"):
            argv += ["--replaces", str(args["replaces"])]
        if args.get("keys"):
            argv += ["--keys", str(args["keys"])]
        for key in ("resume", "sources", "commun"):
            if args.get(key):
                argv += [f"--{key}", str(args[key])]
        argv += ["--source", str(args.get("source") or "mcp")]
        return _run_cli(argv)
    if name == "memory_show":
        return _run_cli(["show", str(args.get("id", ""))])
    if name == "memory_update":
        nid = str(args.get("id", ""))
        if args.get("done"):
            return _run_cli(["done", nid])
        if args.get("archive"):
            return _run_cli(["rm", nid])
        argv = ["edit", nid]
        for key, flag in (("append", "-a"), ("body", "-b"), ("title", "-T"), ("importance", "-i"), ("due", "--due"),
                          ("resume", "--resume"), ("sources", "--sources"), ("commun", "--commun")):
            if args.get(key) not in (None, ""):
                argv += [flag, str(args[key])]
        if len(argv) == 2:
            return "rien à modifier : donner append, body, title, importance, due, done ou archive", True
        return _run_cli(argv)
    if name == "memory_todo":
        return _run_cli(["todo"])
    if name == "memory_context":
        import os
        argv = ["context", "--cwd", str(args.get("folder") or os.path.expanduser("~"))]
        text, err = _run_cli(argv)
        return text.rsplit("\n--- injecté", 1)[0], err
    if name == "wiki_status":
        text, err = _run_cli(["wiki", "status"])
        if args.get("schema") and not err:
            more, _ = _run_cli(["wiki", "schema"])
            text = f"{text}\n\n{more}"
        return text, err
    if name == "wiki_add_source":
        from . import wiki
        try:
            info = wiki.add_source(None, title=str(args.get("title") or "Source"), fmt=args.get("format"),
                                   url=args.get("url"), text=str(args.get("text") or ""))
            text = wiki.ingest_plan(info)
            wiki.write_index()
            return text, False
        except Exception as exc:
            return f"✗ {exc}", True
    if name == "boutique_etat":
        if not args.get("boutique"):
            return _run_cli(["boutique", "liste"])
        return _run_cli(["boutique", "bilan", str(args["boutique"]), "--semaines", str(int(args.get("semaines") or 4))])
    if name == "boutique_ajouter":
        argv = ["boutique", "ajouter", str(args.get("nom", ""))]
        for key, flag in (("url", "--url"), ("plateforme", "--plateforme"), ("chemin", "--chemin"), ("type", "--type"),
                          ("marge_commande", "--marge-commande")):
            if args.get(key) not in (None, ""):
                argv += [flag, str(args[key])]
        return _run_cli(argv)
    if name == "boutique_plan":
        argv = ["boutique", "plan", str(args.get("boutique", ""))]
        if args.get("debut"):
            argv += ["--debut", str(args["debut"])]
        if args.get("court"):
            argv.append("--court")
        return _run_cli(argv)
    if name == "boutique_kpi":
        argv = ["boutique", "kpi", str(args.get("boutique", ""))]
        for key in ("sessions", "ajouts", "checkouts", "commandes", "ca", "heures", "marge", "semaine", "note"):
            if args.get(key) not in (None, ""):
                argv += [f"--{key}", str(args[key])]
        for spec in args.get("canaux") or []:
            argv += ["--canal", str(spec)]
        return _run_cli(argv)
    if name == "boutique_audit":
        argv = ["boutique", "audit", str(args.get("boutique", ""))]
        if args.get("conformite"):
            argv.append("--conformite")
        if args.get("vitesse"):
            argv.append("--vitesse")
        try:
            pages = max(0, min(int(args.get("pages") or 0), 50))
        except (TypeError, ValueError):
            pages = 0
        if pages:
            argv += ["--pages", str(pages)]
        return _run_cli(argv)
    if name == "wiki_lint":
        return _run_cli(["wiki", "lint"])
    if name == "wiki_log":
        lines = [str(x) for x in (args.get("lines") or [])]
        return _run_cli(["wiki", "log", str(args.get("operation") or "note"), str(args.get("title") or ""), *lines])
    return f"outil inconnu : {name}", True


def handle(msg):
    """Une requête JSON-RPC → la réponse (ou None pour une notification)."""
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:  # notification (initialized, cancelled…) : pas de réponse
        return None
    try:
        if method == "initialize":
            from . import __version__
            asked = (msg.get("params") or {}).get("protocolVersion")
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                "capabilities": {"tools": {"listChanged": False}, "prompts": {"listChanged": False}},
                "serverInfo": {"name": "cerveau", "version": __version__},
                "instructions": "Mémoire persistante de l'utilisateur : chercher (memory_search) avant de redemander, "
                                "mémoriser (memory_add) ce qui est durable, jamais de secret."}}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": mid, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
        if method == "tools/call":
            p = msg.get("params") or {}
            text, is_err = call_tool(p.get("name"), p.get("arguments"))
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text or "(vide)"}],
                                                             "isError": is_err}}
        if method == "prompts/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"prompts": [PROMPT]}}
        if method == "prompts/get":
            if (msg.get("params") or {}).get("name") != PROMPT["name"]:
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
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": repr(exc)}}


def serve():
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
