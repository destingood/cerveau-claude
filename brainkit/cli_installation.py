"""Commandes d'installation et de réglage : config, hooks, serveur MCP, publication, mise à jour, installation.

Découpé de cli.py (étape 8 du plan) sans rien changer : le parseur et main() restent dans cli.py, qui ne charge ce
module qu'au moment d'en lancer une commande."""
from __future__ import annotations

import json
import sys

from .cli_commun import die
from .common import CONFIG_FILE, load_config, set_config


def cmd_config(a):
    from . import common, reglages
    cfg = load_config()
    if not a.key:
        print(json.dumps(cfg, ensure_ascii=False, indent=1))
        print(f"(fichier : {CONFIG_FILE})")
        if common.CONFIG_ISSUES:
            print(common.config_issues_line())
        return
    if a.value is None:
        cur, seen = cfg, True
        for k in a.key.split("."):
            seen = seen and isinstance(cur, dict) and k in cur
            cur = cur.get(k) if isinstance(cur, dict) else None
        if not seen and not reglages.known(a.key):
            die(reglages.unknown(a.key).replace(" ; rien n'est écrit", ""))
        print(json.dumps(cur, ensure_ascii=False))
        bad = [x for x in common.CONFIG_ISSUES if x[0] == a.key or x[0].startswith(a.key + ".")]
        if bad:
            print(f"⚠ valeur écrite ignorée : {json.dumps(bad[0][1], ensure_ascii=False)} ({bad[0][2]} attendu) — "
                  "le défaut ci-dessus sert à sa place")
        return
    try:
        value, raw = json.loads(a.value), None
    except json.JSONDecodeError:
        value = raw = a.value
    value, err = reglages.check(a.key, value, raw)
    if err:
        die(err)
    set_config(a.key, value)
    print(f"✓ {a.key} = {json.dumps(value, ensure_ascii=False)}")
    if a.key == "style":  # le réglage de Claude Code suit tout de suite (posé, ou remis comme avant pour « off »)
        from . import eco
        lines = eco.sync_style()
        if lines:
            print(lines)


def cmd_hook(a):
    if a.event == "post-bash":
        from . import compact
        return compact.hook()
    if a.event == "pre-agent":
        from . import delegation
        return delegation.hook()
    from . import hooks
    return hooks.run(a.event)


def cmd_mcp(a):
    from . import mcp_server
    return mcp_server.serve()


def cmd_publish(a):
    from . import publish
    sys.exit(publish.run(a.dir, owner=a.owner, repo=a.repo, push=a.push, check=not a.no_check))


def cmd_selfupdate(a):
    from . import selfupdate
    sys.exit(selfupdate.run(a.source, force=a.force, verify=not a.no_verify, dry_run=a.dry_run))


def cmd_install(a):
    if a.mcp:
        from . import mcp_server
        try:
            path, changed = mcp_server.register(dry=a.dry_run, remove=a.uninstall)
        except (RuntimeError, OSError, ValueError) as exc:
            die(str(exc))
        verb = "retiré de" if a.uninstall else "ajouté à"
        if not changed:
            print(f"✓ rien à faire : serveur MCP « cerveau » déjà {'absent de' if a.uninstall else 'présent dans'} {path}")
        elif a.dry_run:
            print(f"(simulation) le serveur MCP « cerveau » serait {verb} {path}")
        else:
            print(f"✓ serveur MCP « cerveau » {verb} {path} (copie de sauvegarde à côté) — redémarrer l'app Claude")
        return
    from . import install
    install.run(dry=a.dry_run, uninstall=a.uninstall)
