#!/usr/bin/env python3
"""🧠 brain — cerveau persistant de Claude Code.

Mémoire en graphe (profil, règles, projets, décisions, apprentissages…) + cartes de projets
façon graphify + hooks qui injectent automatiquement le bon contexte à chaque session.

Usage : python brain.py <commande> …      (python brain.py -h pour l'aide complète)
"""
import os
import sys

if sys.version_info < (3, 10):  # avant tout import du cerveau, qui suppose Python 3.10 ou plus récent
    sys.stderr.buffer.write(("🧠 cerveau : Python %d.%d est trop ancien, il faut Python 3.10 ou plus récent "
                             "(python.org ; README du cerveau, section « Prérequis »).\n" % sys.version_info[:2])
                            .encode("utf-8", "replace"))
    sys.exit(1)

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
    """brain.exe livré à côté (Windows) : la version Rust, seulement sur demande (BRAIN_IMPL=rust). Elle est restée à la
    8.18.2 et son code source n'est pas encore dans le dépôt : aucun correctif depuis ne lui parvient. Par défaut, tout
    passe donc par Python (décision de l'utilisateur, 20/11/2026), en attendant que le code Rust revienne dans le dépôt,
    corrigé et optimisé. Lancée, elle repasse elle-même à Python (BRAIN_IMPL=python) pour ce qu'elle ne fait pas."""
    exe = os.path.join(HERE, "brain.exe")
    return exe if os.name == "nt" and os.environ.get("BRAIN_IMPL") == "rust" and os.path.isfile(exe) else None


# Python seul, jamais brain.exe : le serveur MCP (rien de porté) et ce qui est né après le portage en Rust.
PYTHON_ONLY = ("mcp", "delegation", "deleguer", "apprendre", "apprentissage", "echange", "skills-communes",
               "oublier-session", "forget-session")
PYTHON_HOOKS = ("pre-agent",)  # hook PreToolUse de l'outil Agent (brainkit/delegation.py)
PLUS_HOOKS = ("session-start", "prompt", "stop", "session-end")  # sortie complétée par brainkit/plus.py


def hook_with_plus(exe, event):
    """Hook exécuté par brain.exe, puis complété par la couche « plus » (Python : délégation, apprentissage, échange de
    skills). BRAIN_PLUS=0 dans l'environnement de l'exe : s'il repasse à Python, la couche ne s'applique pas deux fois.
    Une sortie qu'on ne sait pas compléter repart telle quelle. OSError au lancement (exe bloqué) : l'entrée déjà lue
    est rendue à Python, qui fait tout."""
    import subprocess
    import tempfile
    payload = sys.stdin.buffer.read()
    env = dict(os.environ, BRAIN_PYTHON=sys.executable, BRAIN_PLUS="0")
    # Sortie de l'exe dans un fichier temporaire, pas dans un tube : un tube ne se ferme que lorsque TOUS les processus
    # qui en ont hérité sont finis, et l'exe lance des tâches de fond détachées (carte du projet, synchro…) — on
    # attendrait leur fin, au-delà du délai du hook. Avec un fichier, on n'attend que l'exe.
    try:
        tmp = tempfile.TemporaryFile()
    except OSError:
        tmp = None  # dossier temporaire inutilisable : l'exe écrit lui-même sa sortie, sans la couche « plus »
    try:
        r = subprocess.run([exe] + sys.argv[1:], input=payload, stdout=tmp, env=env)
    except OSError:
        import io
        if tmp is not None:
            tmp.close()
        sys.stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")  # rien n'a tourné : Python reprend l'entrée
        raise
    if tmp is None:
        return r.returncode
    try:  # (l'exe a tourné : quoi qu'il arrive ensuite, le hook n'est pas relancé)
        tmp.seek(0)
        out = tmp.read()
    except OSError:
        out = b""
    finally:
        tmp.close()
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


def _pipe(stream) -> bool:
    try:
        import stat
        return stat.S_ISFIFO(os.fstat(stream.fileno()).st_mode)
    except (AttributeError, OSError, ValueError):
        return False


def run_exe(exe, args):
    """Commande ordinaire exécutée par brain.exe → son code de sortie. Sortie vers un tube (outil Bash de Claude Code,
    script, test) : l'exe écrit dans des fichiers temporaires, recopiés quand il a fini. Même raison que pour les hooks :
    un tube ne se ferme que lorsque TOUS les processus qui en ont hérité sont finis, et sous Windows les tâches de fond
    de l'exe en héritent (envoi différé du cerveau commun : 15 s). L'appelant attendrait leur fin, et un « garde ça pour
    moi » juste après un ajout n'arriverait qu'une fois le premier jet parti. Console ou fichier : sortie au fil de
    l'eau, comme avant. OSError au lancement (exe bloqué) : rien n'a tourné, Python fait tout."""
    import subprocess
    import tempfile
    files = {}
    for name in ("stdout", "stderr"):
        if _pipe(getattr(sys, name)):
            try:
                files[name] = tempfile.TemporaryFile()
            except OSError:
                pass  # dossier temporaire inutilisable : l'exe écrit lui-même dans le tube (on attend ses tâches de fond)
    try:
        return subprocess.run([exe] + list(args), env=dict(os.environ, BRAIN_PYTHON=sys.executable), **files).returncode
    finally:
        for name, tmp in files.items():
            try:
                tmp.seek(0)
                out = getattr(sys, name).buffer
                out.write(tmp.read())
                out.flush()
            except (OSError, ValueError):
                pass
            finally:
                tmp.close()


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
        try:
            if hook_event in PLUS_HOOKS and os.environ.get("BRAIN_PLUS") != "0":
                sys.exit(hook_with_plus(exe, hook_event))
            sys.exit(run_exe(exe, sys.argv[1:]))
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
        from brainkit.common import exit_now
        exit_now(run(sys.argv[2]))  # (sans libérer le cerveau lu objet par objet : voir exit_now)
    if len(sys.argv) == 2 and sys.argv[1] == "mcp":  # serveur MCP (stdio) : démarrage direct
        from brainkit.mcp_server import serve
        sys.exit(serve())
    from brainkit.cli import main
    sys.exit(main())
