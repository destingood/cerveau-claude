#!/usr/bin/env python3
"""🧠 brain — cerveau persistant de Claude Code.

Mémoire en graphe (profil, règles, projets, décisions, apprentissages…) + cartes de projets
façon graphify + hooks qui injectent automatiquement le bon contexte à chaque session.

Usage : python brain.py <commande> …      (python brain.py -h pour l'aide complète)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
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
