"""Mode plugin Claude Code (installation d'un ami) : le code arrive par le plugin « cerveau », que Claude Code met à
jour tout seul ; les souvenirs restent dans ~/.claude/brain.

- Lanceur stable ~/.claude/brain/brain.py, réécrit à chaque démarrage : les commandes données à Claude
  (`python "$HOME/.claude/brain/brain.py" …`) visent toujours le code de la version installée.
- Consignes du cerveau injectées au démarrage (un plugin n'écrit pas dans CLAUDE.md).
- Jamais deux cerveaux à la fois : installé là où tourne un cerveau classique (code dans ~/.claude/brain), le plugin
  prend le relais au premier démarrage (`migrate_classic`) — hooks, CLAUDE.md et skills classiques retirés, code
  classique archivé, souvenirs intacts, mises à jour automatiques activées. `config plugin.garder_classique true`
  (avant d'installer le plugin) garde au contraire le cerveau classique seul aux commandes."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

from .common import BRAIN_DIR, CLAUDE_HOME, CODE_DIR, PLUGIN, load_config, log, now_iso, read_json, set_config, \
    write_json, write_text

ARCHIVES = "archives"  # dans ~/.claude/brain : code classique mis de côté lors du passage au plugin
NOTICE = []  # lignes du passage au plugin, injectées une fois au démarrage de la session qui l'a fait

LAUNCHER = '''#!/usr/bin/env python3
"""🧠 Lanceur du cerveau (plugin Claude Code), réécrit à chaque démarrage de session : il lance le code du plugin,
que Claude Code met à jour tout seul. Les souvenirs restent dans ce dossier."""
import json
import os
import runpy
import sys

CODE = {code!r}


def active(code):
    """La version que Claude Code a installée (plugins/installed_plugins.json) : une mise à jour sert aussitôt aux
    commandes, sans attendre le prochain démarrage de session. Registre illisible ou absent : la version d'ici."""
    plugin, market = os.path.dirname(code), os.path.dirname(os.path.dirname(code))
    registry = os.path.join(os.path.dirname(os.path.dirname(market)), "installed_plugins.json")
    try:
        with open(registry, encoding="utf-8") as f:
            entries = json.load(f)["plugins"][os.path.basename(plugin) + "@" + os.path.basename(market)]
        for entry in sorted(entries, key=lambda e: e.get("scope") != "user"):
            path = entry.get("installPath")
            if path and os.path.isfile(os.path.join(path, "brain.py")):
                return path
    except Exception:
        pass
    return code


CODE = active(CODE)
os.environ.setdefault("BRAIN_HOME", os.path.dirname(os.path.abspath(__file__)))
sys.argv[0] = os.path.join(CODE, "brain.py")
runpy.run_path(sys.argv[0], run_name="__main__")
'''


def classic_install() -> bool:
    """Cerveau classique aux commandes (code et souvenirs dans ~/.claude/brain, pas encore passé au plugin) ?"""
    return (BRAIN_DIR / "brainkit").is_dir() and not (load_config().get("plugin") or {}).get("migre_le")


def migration_wanted() -> bool:
    """Le plugin doit-il prendre le relais du cerveau classique ? (oui, sauf `config plugin.garder_classique true`)"""
    return PLUGIN and classic_install() and not (load_config().get("plugin") or {}).get("garder_classique")


def _classic_version() -> str:
    try:
        text = (BRAIN_DIR / "brainkit" / "__init__.py").read_text(encoding="utf-8")
        m = re.search(r'__version__\s*=\s*["\']([^"\']+)', text)
        return m.group(1) if m else "?"
    except OSError:
        return "?"


def _marketplace():
    """(nom, source) du marketplace d'où vient ce plugin, d'après son dossier (plugins/cache/<marketplace>/<plugin>/
    <version>/, ou plugins/marketplaces/<marketplace>/…) et le registre des marketplaces connus de Claude Code
    (plugins/known_marketplaces.json). → (None, None) si introuvable."""
    known = read_json(CLAUDE_HOME / "plugins" / "known_marketplaces.json", {}) or {}
    known = known if isinstance(known, dict) else {}
    parts, name = CODE_DIR.parts, None
    for anchor in ("cache", "marketplaces"):
        if anchor in parts and len(parts) > parts.index(anchor) + 1 and parts[parts.index(anchor) - 1] == "plugins":
            name = parts[parts.index(anchor) + 1]
            break
    if name is None:  # autre emplacement : le marketplace dont le dossier contient ce plugin
        for key, entry in known.items():
            loc = entry.get("installLocation") if isinstance(entry, dict) else None
            try:
                if loc and CODE_DIR.resolve().is_relative_to(Path(loc).resolve()):
                    name = key
                    break
            except (OSError, ValueError):
                continue
    if name is None:
        return None, None
    entry = known.get(name)
    source = entry.get("source") if isinstance(entry, dict) else None
    return name, source if isinstance(source, dict) else None


def enable_autoupdate(settings: dict) -> tuple:
    """Mises à jour automatiques du marketplace du plugin, comme l'étape 3 du README (`"autoUpdate": true` dans
    extraKnownMarketplaces des réglages utilisateur). → (réglages, ligne de compte rendu ou None)."""
    name, source = _marketplace()
    known = dict(settings.get("extraKnownMarketplaces") or {})
    entry = dict(known.get(name) or {}) if name else {}
    if not name or not (entry.get("source") or source):
        return settings, None
    if entry.get("autoUpdate") is True:
        return settings, None
    entry.setdefault("source", source)
    entry["autoUpdate"] = True
    known[name] = entry
    out = dict(settings)
    out["extraKnownMarketplaces"] = known
    return out, f"✓ mises à jour automatiques activées (marketplace « {name} »)"


def _read_settings(path):
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))  # illisible : exception, rien n'est touché
    return data if isinstance(data, dict) else {}


def migrate_classic() -> list:
    """Le plugin prend le relais du cerveau classique, comme chez les amis (mises à jour par Claude Code). Les souvenirs
    ne bougent pas ; le code classique est archivé avant d'être retiré ; tout est fait dans un ordre qui laisse le
    cerveau classique intact si une étape échoue avant la bascule. → lignes de compte rendu (vides si rien n'est fait)."""
    from . import install
    if not migration_wanted():
        return []
    version = _classic_version()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    archive = BRAIN_DIR / ARCHIVES / f"code-classique-{version}-{stamp}"
    # 1. Copie du code classique, puis réglages de Claude Code : hooks classiques retirés (le plugin a les siens),
    #    mises à jour automatiques. Un échec ici laisse le cerveau classique tel quel (et ne laisse pas d'archive).
    settings_path = CLAUDE_HOME / "settings.json"
    try:
        settings = _read_settings(settings_path)  # illisible : on s'arrête avant de toucher à quoi que ce soit
        archive.mkdir(parents=True, exist_ok=False)
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        for name in ("brain.py", "brainkit", "tests", "skills"):
            src = BRAIN_DIR / name
            if src.is_dir():
                shutil.copytree(src, archive / name, ignore=ignore)
            elif src.is_file():
                shutil.copy2(src, archive / name)
        new = install.merged_settings(settings, remove_only=True)
        new, auto = enable_autoupdate(new)
        if new != settings:
            if settings_path.exists():
                shutil.copy2(settings_path, settings_path.with_name("settings.json.bak-cerveau-classique"))
            write_json(settings_path, new, indent=2)
    except Exception:
        shutil.rmtree(archive, ignore_errors=True)
        raise
    # 3. Bascule : à partir d'ici le plugin est aux commandes
    set_config("plugin.migre_le", now_iso())
    set_config("plugin.archive", str(archive))
    set_config("plugin.version_classique", version)
    lines = [f"🔄 Cerveau passé en mode plugin (comme chez les amis) : souvenirs intacts, code classique {version} "
             f"archivé dans {archive}"]
    lines.append(auto or "· mises à jour automatiques : déjà actives, ou à activer une fois dans /plugin › "
                         "marketplaces › cerveau › Enable auto-update")
    # 4. Ce que le plugin fournit déjà : bloc CLAUDE.md, skill /brain, skills métier posées par le cerveau
    try:
        claude_md = CLAUDE_HOME / "CLAUDE.md"
        if claude_md.exists():
            old = claude_md.read_text(encoding="utf-8")
            text = install.merged_claude_md(old, remove_only=True)
            if text != old:
                if text.strip():
                    write_text(claude_md, text)
                else:
                    claude_md.unlink()
        skill = CLAUDE_HOME / "skills" / "brain" / "SKILL.md"
        if skill.exists() and "Cerveau — référence" in skill.read_text(encoding="utf-8", errors="replace"):
            shutil.rmtree(skill.parent, ignore_errors=True)
        install.sync_skills(uninstall=True)
    except Exception as exc:  # le plugin fonctionne quand même ; le doctor le signalera
        log(f"passage au plugin (CLAUDE.md, skills) : {exc!r}")
    # 5. Code classique retiré (archivé plus haut) ; un fichier verrouillé sera retiré au prochain démarrage
    remove_classic_code()
    ensure_launcher()
    lines.append("→ rien à faire : à partir de maintenant, chaque version publiée arrive toute seule")
    NOTICE[:] = lines
    log(" · ".join(lines))
    return lines


def remove_classic_code() -> bool:
    """Retire le code classique déjà archivé (brainkit, tests, skills métier) ; True s'il n'en reste rien."""
    if not (load_config().get("plugin") or {}).get("migre_le"):
        return False
    for name in ("brainkit", "tests", "skills"):
        path = BRAIN_DIR / name
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    return not (BRAIN_DIR / "brainkit").exists()


def take_notice() -> str:
    """Compte rendu du passage au plugin (une seule fois) pour l'injection de démarrage."""
    if not NOTICE:
        return ""
    text = "\n".join(NOTICE) + ("\n(dis-le à l'utilisateur en une phrase au début de ta réponse)")
    NOTICE.clear()
    return text


def ensure_launcher() -> bool:
    """Écrit (ou met à jour) le lanceur stable. → True s'il a changé."""
    if not PLUGIN or classic_install():
        return False
    path = BRAIN_DIR / "brain.py"
    text = LAUNCHER.format(code=str(CODE_DIR))
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    write_text(path, text)
    return True


def instructions() -> str:
    """Le bloc CLAUDE.md du cerveau classique, sans ses balises : consignes de chaque session en mode plugin."""
    from .install import CLAUDE_BLOCK, skill_sources
    text = "\n".join(line for line in CLAUDE_BLOCK.strip().splitlines() if not line.startswith("<!--"))
    if os.environ.get("CERVEAU_CLOUD"):  # session cloud lancée par le wiki : code récupéré, pas de skill installée
        text = text.replace("skill `/brain`", f"référence complète : {CODE_DIR / 'skills' / 'brain' / 'SKILL.md'}")
        metier = " · ".join(f"{name} : {src / 'SKILL.md'}" for name, src in skill_sources().items())
        return text + (f"\nSkills métier (à lire dès qu'une demande s'y rapporte) — {metier}" if metier else "")
    return text.replace("skill `/brain`", "skill `/cerveau:brain`")
