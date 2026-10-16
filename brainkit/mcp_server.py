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
TYPES = ["user", "feedback", "project", "decision", "fact", "learning", "reference", "entity", "todo"]

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
        for key, flag in (("append", "-a"), ("body", "-b"), ("title", "-T"), ("importance", "-i"), ("due", "--due")):
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
