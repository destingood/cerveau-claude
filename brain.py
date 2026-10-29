#!/usr/bin/env python3
"""🧠 brain — cerveau persistant de Claude Code.

Mémoire en graphe (profil, règles, projets, décisions, apprentissages…) + cartes de projets
façon graphify + hooks qui injectent automatiquement le bon contexte à chaque session.

Usage : python brain.py <commande> …      (python brain.py -h pour l'aide complète)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def newer_install():
    """Copie du plugin d'une session ouverte avant une mise à jour (son CLAUDE_PLUGIN_ROOT ne change qu'au redémarrage) :
    le dossier de la version installée (plugins/installed_plugins.json) quand elle est plus récente, pour qu'elle prenne
    le relais dès l'événement suivant. Seulement depuis le cache des plugins, jamais le dossier de dev."""
    plugin = os.path.dirname(HERE)
    market = os.path.dirname(plugin)
    if os.path.basename(os.path.dirname(market)) != "cache":
        return None
    try:
        import json
        with open(os.path.join(os.path.dirname(os.path.dirname(market)), "installed_plugins.json"), encoding="utf-8") as f:
            entries = json.load(f)["plugins"][os.path.basename(plugin) + "@" + os.path.basename(market)]
        version = lambda p: tuple(int(x) for x in os.path.basename(os.path.normpath(p)).split("."))
        for entry in sorted(entries, key=lambda e: e.get("scope") != "user"):
            path = entry.get("installPath")
            if path and os.path.isfile(os.path.join(path, "brain.py")):
                return path if version(path) > version(HERE) else None
    except Exception:
        pass
    return None


if __name__ == "__main__":
    relay = newer_install()
    if relay:
        import runpy
        sys.argv[0] = os.path.join(relay, "brain.py")
        runpy.run_path(sys.argv[0], run_name="__main__")
        sys.exit(0)
    if len(sys.argv) >= 3 and sys.argv[1] == "hook":  # chemin rapide des hooks : ni argparse ni CLI à charger
        from brainkit.common import setup_io
        setup_io()
        if sys.argv[2] == "post-bash":  # après chaque commande : le plus léger possible (ni index ni recherche)
            from brainkit.compact import hook
            sys.exit(hook())
        from brainkit.hooks import run
        sys.exit(run(sys.argv[2]))
    if len(sys.argv) == 2 and sys.argv[1] == "mcp":  # serveur MCP (stdio) : démarrage direct
        from brainkit.mcp_server import serve
        sys.exit(serve())
    from brainkit.cli import main
    sys.exit(main())
