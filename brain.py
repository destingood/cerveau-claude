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


def rust_exe():
    """brain.exe livré à côté (Windows) : la version Rust, qui repasse elle-même à Python (BRAIN_IMPL=python) pour ce
    qu'elle ne fait pas encore. Absent, ou BRAIN_IMPL=python : Python seul."""
    exe = os.path.join(HERE, "brain.exe")
    return exe if os.name == "nt" and os.environ.get("BRAIN_IMPL") != "python" and os.path.isfile(exe) else None


# Python seul, jamais brain.exe : le serveur MCP (rien de porté) et ce qui est né après le portage en Rust.
PYTHON_ONLY = ("mcp", "delegation", "deleguer", "apprendre", "apprentissage", "echange", "skills-communes")
PYTHON_HOOKS = ("pre-agent",)  # hook PreToolUse de l'outil Agent (brainkit/delegation.py)
PLUS_HOOKS = ("session-start", "prompt", "stop", "session-end")  # sortie complétée par brainkit/plus.py


def hook_with_plus(exe, event):
    """Hook exécuté par brain.exe, puis complété par la couche « plus » (Python : délégation, apprentissage, échange de
    skills). BRAIN_PLUS=0 dans l'environnement de l'exe : s'il repasse à Python, la couche ne s'applique pas deux fois.
    Une sortie qu'on ne sait pas compléter repart telle quelle. OSError (exe bloqué) : l'entrée déjà lue est rendue à
    Python, qui fait tout."""
    import subprocess
    import tempfile
    payload = sys.stdin.buffer.read()
    # Sortie de l'exe dans un fichier temporaire, pas dans un tube : un tube ne se ferme que lorsque TOUS les processus
    # qui en ont hérité sont finis, et l'exe lance des tâches de fond détachées (carte du projet, synchro…) — on
    # attendrait leur fin, au-delà du délai du hook. Avec un fichier, on n'attend que l'exe.
    with tempfile.TemporaryFile() as tmp:
        try:
            r = subprocess.run([exe] + sys.argv[1:], input=payload, stdout=tmp,
                               env=dict(os.environ, BRAIN_PYTHON=sys.executable, BRAIN_PLUS="0"))
        except OSError:
            import io
            sys.stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
            raise
        tmp.seek(0)
        out = tmp.read()
    text = None
    if r.returncode == 0:
        try:
            from brainkit.common import setup_io
            setup_io()
            from brainkit.plus import apply_raw
            text = apply_raw(event, out, payload)
        except Exception:
            text = None
    if text is None:
        sys.stdout.buffer.write(out)
        sys.stdout.buffer.flush()
    else:
        sys.stdout.write(text)
        sys.stdout.flush()
    return r.returncode


if __name__ == "__main__":
    relay = newer_install()
    if relay:
        import runpy
        sys.argv[0] = os.path.join(relay, "brain.py")
        runpy.run_path(sys.argv[0], run_name="__main__")
        sys.exit(0)
    hook_event = sys.argv[2] if len(sys.argv) >= 3 and sys.argv[1] == "hook" else None
    python_only = sys.argv[1:2] and sys.argv[1] in PYTHON_ONLY or hook_event in PYTHON_HOOKS
    exe = None if python_only else rust_exe()
    if exe:
        import subprocess
        try:
            if hook_event in PLUS_HOOKS and os.environ.get("BRAIN_PLUS") != "0":
                sys.exit(hook_with_plus(exe, hook_event))
            sys.exit(subprocess.run([exe] + sys.argv[1:], env=dict(os.environ, BRAIN_PYTHON=sys.executable)).returncode)
        except OSError:
            pass  # exe bloqué (antivirus…) : Python fait tout
    if hook_event:  # chemin rapide des hooks : ni argparse ni CLI à charger
        from brainkit.common import setup_io
        setup_io()
        if hook_event == "post-bash":  # après chaque commande : le plus léger possible (ni index ni recherche)
            from brainkit.compact import hook
            sys.exit(hook())
        if hook_event == "pre-agent":  # avant chaque sous-agent : ce module et le socle seulement
            from brainkit.delegation import hook
            sys.exit(hook())
        from brainkit.hooks import run
        sys.exit(run(sys.argv[2]))
    if len(sys.argv) == 2 and sys.argv[1] == "mcp":  # serveur MCP (stdio) : démarrage direct
        from brainkit.mcp_server import serve
        sys.exit(serve())
    from brainkit.cli import main
    sys.exit(main())
