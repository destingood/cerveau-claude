"""Plugin Claude Code « cerveau » pour les amis : `brain publish <dépôt>` construit le plugin (code, hooks, serveur MCP,
skill, marketplace) dans le clone local du dépôt GitHub, le vérifie dans un bac à sable, puis fait le commit et le tag
de la version. Chez un ami, Claude Code installe le plugin une fois, puis le met à jour tout seul (`autoUpdate`) à chaque
version publiée ; ses souvenirs restent chez lui, dans ~/.claude/brain, et ne partent jamais.

Ne part dans le dépôt que le code (brain.py, brainkit/) : jamais les souvenirs, la configuration ni les tests (ils lisent
la mémoire de Lucas). L'envoi sur GitHub est une publication : il n'a lieu qu'avec `--push`."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__
from .common import CODE_DIR, load_config, set_config

NAME = MARKET = "cerveau"
DESC = ("Cerveau persistant pour Claude Code : souvenirs en graphe, rappel automatique à chaque message, cartes de "
        "projets, à-faire datés, serveur MCP. Tout reste sur ton PC.")
SETTINGS_SNIPPET = """{{
  "extraKnownMarketplaces": {{
    "cerveau": {{ "source": {{ "source": "git", "url": "https://github.com/{repo}.git" }}, "autoUpdate": true }}
  }},
  "enabledPlugins": {{ "cerveau@cerveau": true }}
}}"""  # URL https : pas besoin de clé SSH GitHub chez l'ami (la forme « proprietaire/depot » peut passer par SSH)


def _lf(path: Path, text: str) -> None:
    """Fichier texte en UTF-8 avec des fins de ligne LF, comme le reste du dépôt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def _json(path: Path, data) -> None:
    _lf(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _hook(arg: str, timeout: int, status=None) -> dict:
    """Hook en forme « exécutable + arguments » : aucun shell à lancer (Git Bash ou PowerShell sous Windows), aucun
    guillemet à échapper ; Python direct en mode isolé (-I -S), le plus rapide (le cerveau n'utilise que la stdlib)."""
    h = {"type": "command", "command": "python", "args": ["-I", "-S", "${CLAUDE_PLUGIN_ROOT}/brain.py", "hook", arg],
         "timeout": timeout}
    if status:
        h["statusMessage"] = status
    return h


def readme(owner: str, repo: str) -> str:
    repo = repo or "PROPRIETAIRE/DEPOT"
    return f"""# 🧠 Cerveau pour Claude Code

Une mémoire persistante pour Claude Code, faite par {owner} : Claude se souvient de toi, de tes projets, de tes
décisions et de ce qu'il a appris, d'une session à l'autre.

- **Au démarrage** de chaque session : l'essentiel de ta mémoire et du projet courant est injecté.
- **À chaque message** : les souvenirs et fichiers vraiment liés remontent tout seuls (fautes de frappe, écriture
  phonétique et synonymes compris).
- **En fin de tâche** : Claude note ce qui mérite d'être retenu (décisions, pièges, préférences).
- Cartes de tes projets (fichiers clés, où est défini quoi), à-faire datés, vue 3D, serveur MCP.

Tout reste sur ton PC, dans `~/.claude/brain` : rien n'est envoyé ailleurs, et chacun a sa propre mémoire.

## Installer (une seule fois)

1. **Python 3.10 ou plus récent** : https://www.python.org/downloads/ — pendant l'installation, coche
   **« Add python.exe to PATH »**. Et **Git** (https://git-scm.com/download/win), si Claude Code ne te l'a pas déjà
   fait installer.
2. **Le plugin**, dans Claude Code (onglet Code de l'app Claude, ou terminal) :
   ```
   /plugin marketplace add https://github.com/{repo}.git
   /plugin install cerveau@cerveau
   ```
3. **Les mises à jour automatiques**, une fois : `/plugin` → onglet des marketplaces → « cerveau » → *Enable
   auto-update*. Claude Code les laisse coupées par défaut pour un marketplace qui n'est pas d'Anthropic : c'est à
   toi de les autoriser.
4. **Redémarre Claude Code.** Au premier démarrage, le cerveau crée `~/.claude/brain`.

Variante sans commande, mises à jour automatiques comprises (`"autoUpdate": true`) : ajoute ceci à
`~/.claude/settings.json` (à fusionner avec ce qui s'y trouve déjà), puis redémarre Claude Code :

```json
{SETTINGS_SNIPPET.format(repo=repo)}
```

## Mises à jour

Une fois l'étape 3 faite, elles sont automatiques : quand une nouvelle version est publiée, Claude Code la récupère
pendant une session (quelques minutes après ton premier message) et l'applique au démarrage suivant. Tes souvenirs ne
sont jamais touchés par une mise à jour.

## Au quotidien

Rien à faire : parle normalement à Claude. Pour aller plus loin, demande-lui « qu'est-ce que tu sais sur … ? »,
« retiens que … », ou tape `/brain`. Vue 3D de ta mémoire : `~/.claude/brain/cerveau.html`.

## Désinstaller

`/plugin uninstall cerveau@cerveau`. Tes souvenirs restent dans `~/.claude/brain` (supprime ce dossier pour tout effacer).

Version {__version__}.
"""


def build(dest: Path, owner: str = "Lucas", repo: str = "") -> list:
    """Écrit le plugin complet dans dest (le clone du dépôt) : l'ancien contenu est remplacé, .git est gardé.
    → liste des fichiers écrits (chemins relatifs)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / "brainkit").exists() and (dest / "graph.json").exists():
        raise RuntimeError(f"{dest} contient des souvenirs (graph.json) : ce n'est pas un dépôt de plugin")
    for item in dest.iterdir():
        if item.name != ".git":
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    shutil.copy2(CODE_DIR / "brain.py", dest / "brain.py")
    shutil.copytree(CODE_DIR / "brainkit", dest / "brainkit", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    from .install import EVENTS, SKILL
    hooks = {event: [{"hooks": [_hook(arg, timeout, status)]}] for event, arg, timeout, status in EVENTS}
    _json(dest / "hooks" / "hooks.json", {"description": "Cerveau : injection au démarrage, rappel à chaque message, "
                                                         "mémorisation en fin de tâche", "hooks": hooks})
    _json(dest / ".mcp.json", {"mcpServers": {"cerveau": {
        "command": "python", "args": ["-I", "-S", "${CLAUDE_PLUGIN_ROOT}/brain.py", "mcp"]}}})
    _lf(dest / "skills" / "brain" / "SKILL.md", SKILL)
    plugin = {"name": NAME, "version": __version__, "description": DESC, "author": {"name": owner},
              "keywords": ["mémoire", "memory", "souvenirs", "rappel", "hooks", "mcp"]}
    if repo:
        plugin["homepage"] = plugin["repository"] = f"https://github.com/{repo}"
    _json(dest / ".claude-plugin" / "plugin.json", plugin)
    _json(dest / ".claude-plugin" / "marketplace.json", {
        "name": MARKET, "owner": {"name": owner},
        "metadata": {"description": f"Le cerveau persistant de {owner} pour Claude Code", "version": __version__},
        "plugins": [{"name": NAME, "source": "./", "description": DESC, "version": __version__}]})
    _lf(dest / "README.md", readme(owner, repo))
    _lf(dest / ".gitignore", "__pycache__/\n*.pyc\n")
    return sorted(str(p.relative_to(dest)).replace("\\", "/") for p in dest.rglob("*")
                  if p.is_file() and ".git" not in p.relative_to(dest).parts)


def claude_cli():
    """Le Claude Code embarqué dans l'app (le plus récent), ou celui du PATH : sert à valider le plugin."""
    found = shutil.which("claude")
    if found:
        return found
    root = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude-code"
    exes = sorted(root.glob("*/*/claude.exe"), key=lambda p: [int(x) if x.isdigit() else 0
                                                                for x in re.split(r"[.]", p.parent.parent.name)])
    return str(exes[-1]) if exes else None


def secrets_in(dest: Path) -> list:
    """Fichiers du dépôt qui contiennent un secret (clé, jeton, mot de passe) ou une adresse e-mail : rien ne part."""
    from .privacy import find
    email = re.compile(r"[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")  # pas « paquet@1.80.0 »
    bad = []
    for p in dest.rglob("*"):
        if p.is_file() and ".git" not in p.relative_to(dest).parts and p.suffix in (".py", ".json", ".md", ""):
            text = p.read_text(encoding="utf-8", errors="replace")
            hits = find(text) + (["e-mail"] if any("example" not in m.group(0) for m in email.finditer(text)) else [])
            if hits:
                bad.append(f"{p.relative_to(dest)} ({', '.join(sorted(set(hits)))})")
    return bad


def smoke(dest: Path) -> list:
    """Premier démarrage chez un « ami » fictif (profil Claude vide, mémoire vide) : hook de démarrage, rappel d'un
    message, serveur MCP. → liste des problèmes (vide = tout va bien)."""
    problems = []
    with tempfile.TemporaryDirectory(prefix="cerveau-ami-") as tmp:
        env = {k: v for k, v in os.environ.items() if k not in ("BRAIN_HOME",)}
        env.update(CLAUDE_CONFIG_DIR=str(Path(tmp) / "claude"), CLAUDE_PLUGIN_ROOT=str(dest), APPDATA=str(Path(tmp) / "app"))
        cmd = [sys.executable, "-I", "-S", str(dest / "brain.py")]

        def run(args, payload=None, timeout=60):
            r = subprocess.run(cmd + args, input=json.dumps(payload or {}).encode(), capture_output=True, env=env,
                               cwd=tmp, timeout=timeout)
            return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")

        c, o, e = run(["hook", "session-start"], {"session_id": "ami-1", "cwd": tmp})
        data = Path(tmp) / "claude" / "brain"
        if c or "Cerveau persistant" not in o:
            problems.append(f"démarrage : code {c}, sortie {o[:200]!r} {e[:300]!r}")
        if not (data / "brain.py").exists() or "runpy" not in (data / "brain.py").read_text(encoding="utf-8"):
            problems.append("lanceur stable ~/.claude/brain/brain.py absent")
        lanceur = [sys.executable, "-I", "-S", str(data / "brain.py")]

        def ajoute(t, titre, corps):
            return subprocess.run(lanceur + ["add", "-t", t, "-T", titre, "-b", corps, "-p", "none"],
                                  capture_output=True, env=env, cwd=tmp, timeout=60).returncode

        # Un vrai cerveau d'ami contient plusieurs souvenirs. Le rappel note chaque terme par sa rareté (IDF) : dans un
        # cerveau d'un seul souvenir, même une correspondance parfaite reste sous le seuil et ne remonterait jamais —
        # ce qui ne reflète pas l'usage réel. On sème donc quelques souvenirs sur d'autres sujets avant de vérifier que
        # « Pixel » remonte bien : c'est tout le trajet du hook de rappel qui est éprouvé, dans des conditions réalistes.
        graine = [
            ("fact", "Boutique Shopify de thé", "Vente de matcha en ligne, coffrets et mousseurs."),
            ("fact", "Voiture grise", "Une citadine de 2018, entretien chez le garage du coin."),
            ("learning", "Sauvegarde hebdomadaire", "Exporter la base avant chaque grosse mise à jour."),
            ("reference", "Doc de l'API du site", "Les webhooks produits arrivent en JSON sur l'endpoint configuré."),
            ("fact", "Ficus du salon", "Près de la fenêtre, arrosage une fois par semaine."),
            ("decision", "Choix de l'hébergeur", "Rester sur l'offre actuelle jusqu'à la fin de l'année."),
            ("fact", "Vélo de route", "Cadre aluminium, pneus à regonfler avant les sorties longues."),
            ("learning", "Historique du terminal", "Ctrl+R cherche dans les commandes déjà tapées."),
            ("fact", "Café du matin", "Un expresso serré, sans sucre."),
            ("reference", "Rapport de ventes", "Le bilan mensuel se télécharge en CSV depuis l'admin."),
            ("decision", "Langue du site", "Le site reste en français pour l'instant."),
            ("learning", "Nettoyage du disque", "Vider le cache du navigateur libère plusieurs giga."),
        ]
        semes = sum(ajoute(t, ti, b) == 0 for t, ti, b in graine)
        if ajoute("fact", "Mon chat s'appelle Pixel", "Chat tigré de 3 ans.") != 0:
            problems.append("add par le lanceur : code non nul")
        c, o, e = run(["hook", "prompt"], {"session_id": "ami-1", "cwd": tmp, "prompt": "comment s'appelle mon chat ?"})
        if "Pixel" not in o:
            problems.append(f"rappel d'un message ({semes + 1} souvenirs) : {o[:200]!r} {e[:200]!r}")
        req = "\n".join(json.dumps(x) for x in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05",
                                                                          "capabilities": {}, "clientInfo": {"name": "t"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})) + "\n"
        r = subprocess.run(cmd + ["mcp"], input=req.encode(), capture_output=True, env=env, cwd=tmp, timeout=60)
        if "memory_search" not in r.stdout.decode("utf-8", "replace"):
            problems.append(f"serveur MCP : {r.stdout[:200]!r} {r.stderr[:200]!r}")
    return problems


def run(dest=None, owner=None, repo=None, push=False, check=True) -> int:
    cfg = load_config().get("publish", {})
    dest = Path(dest or cfg.get("dir") or "")
    if not str(dest) or str(dest) == ".":
        print("✗ dossier du dépôt manquant : brain publish <dossier du clone GitHub> [--repo proprietaire/depot]")
        return 1
    owner = owner or cfg.get("owner") or "Lucas"
    repo = repo or cfg.get("repo") or ""
    files = build(dest, owner, repo)
    print(f"✓ plugin « cerveau » {__version__} construit dans {dest} ({len(files)} fichiers)")
    for key, val in (("publish.dir", str(dest)), ("publish.owner", owner), ("publish.repo", repo)):
        if val and cfg.get(key.split(".")[1]) != val:
            set_config(key, val)
    bad = secrets_in(dest)
    if bad:
        print("✗ secret ou adresse e-mail dans le dépôt, rien n'est publié :\n  " + "\n  ".join(bad))
        return 1
    print("✓ aucun secret ni adresse e-mail dans le dépôt")
    if check:
        exe = claude_cli()
        if exe:
            r = subprocess.run([exe, "plugin", "validate", str(dest)], capture_output=True, timeout=120)
            out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
            print(("✓ " if r.returncode == 0 else "✗ ") + "validation Claude Code : "
                  + (out.strip().splitlines()[-1] if out.strip() else f"code {r.returncode}"))
            if r.returncode:
                print(out)
                return 1
        else:
            print("· validation Claude Code sautée (claude introuvable)")
        problems = smoke(dest)
        if problems:
            print("✗ essai chez un ami fictif :\n  " + "\n  ".join(problems))
            return 1
        print("✓ essai chez un ami fictif : démarrage, lanceur stable, mémorisation, rappel, serveur MCP")
    if not (dest / ".git").exists():
        print(f"· pas de dépôt git dans {dest} : clone d'abord ton dépôt GitHub ici (git clone …), puis relance")
        return 0
    git = ["git", "-C", str(dest)]
    subprocess.run(git + ["add", "-A"], check=True)
    if subprocess.run(git + ["diff", "--cached", "--quiet"]).returncode == 0:
        print("✓ rien de nouveau depuis la dernière publication")
    else:
        tag = f"{NAME}--v{__version__}"
        if subprocess.run(git + ["rev-parse", "-q", "--verify", f"refs/tags/{tag}"], capture_output=True).returncode == 0:
            print(f"✗ la version {__version__} est déjà publiée (tag {tag}) : change __version__ (brainkit/__init__.py) "
                  f"pour que les amis reçoivent la mise à jour")
            subprocess.run(git + ["reset", "-q"])
            return 1
        subprocess.run(git + ["commit", "-q", "-m", f"cerveau {__version__}"], check=True)
        subprocess.run(git + ["tag", "-a", tag, "-m", f"cerveau {__version__}"], check=True)  # annoté : --follow-tags
        print(f"✓ commit et tag {tag} prêts")
    if push:
        r = subprocess.run(git + ["push", "--follow-tags", "origin", "HEAD"])
        print("✓ publié : les amis recevront la mise à jour au prochain démarrage de Claude Code" if r.returncode == 0
              else "✗ envoi refusé (connexion GitHub ?)")
        return r.returncode
    print("→ pour publier : brain publish --push (ou git push --follow-tags dans le dépôt)")
    return 0
