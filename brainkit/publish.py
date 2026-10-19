"""Plugin Claude Code « cerveau » pour les amis : `brain publish <dépôt>` construit le plugin (code, hooks, serveur MCP,
skill, marketplace) dans le clone local du dépôt GitHub, le vérifie dans un bac à sable, puis fait le commit et le tag
de la version. Chez un ami, Claude Code installe le plugin une fois, puis le met à jour tout seul (`autoUpdate`) à chaque
version publiée ; ses souvenirs restent chez lui, dans ~/.claude/brain, et ne partent jamais.

Ne part dans le dépôt que le code (brain.py, brainkit/) et les skills (/brain, et les skills métier de skills/<nom>/,
comme le cerveau e-commerce) : jamais les souvenirs ni la configuration. Les tests publics que le dépôt a déjà
(tests/) restent, mis à jour depuis le code ; les tests privés (PRIVATE_TESTS : ils lisent la mémoire de Lucas), jamais.
L'envoi sur GitHub est une publication : il n'a lieu qu'avec `--push`."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import __version__
from .common import CODE_DIR, load_config, read_json, set_config

NAME = MARKET = "cerveau"
DESC = ("Cerveau persistant pour Claude Code : souvenirs en graphe, rappel automatique à chaque message, wiki Markdown "
        "tenu par Claude (sources ingérées, coffre Obsidian, dépôt git), cartes de projets, à-faire datés, serveur MCP, "
        "et un cerveau e-commerce qui suit chaque boutique (clients sans pub, SEO, GEO, tunnel de vente, chiffres de "
        "la semaine). Tout reste chez toi.")
KEYWORDS = ["mémoire", "memory", "souvenirs", "rappel", "hooks", "mcp", "wiki", "obsidian", "e-commerce", "seo", "geo"]
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
    commun = (read_json(CODE_DIR / "brainkit" / "commun.json", {}) or {}).get("repo") or "PROPRIETAIRE/cerveau-commun"
    return f"""# 🧠 Cerveau pour Claude Code

Une mémoire persistante pour Claude Code, faite par {owner} : Claude se souvient de toi, de tes projets, de tes
décisions et de ce qu'il a appris, d'une session à l'autre.

- **Au démarrage** de chaque session : l'essentiel de ta mémoire et du projet courant est injecté.
- **À chaque message** : les souvenirs et fichiers vraiment liés remontent tout seuls (fautes de frappe, écriture
  phonétique et synonymes compris).
- **En fin de tâche** : Claude note ce qui mérite d'être retenu (décisions, pièges, préférences).
- Cartes de tes projets (fichiers clés, où est défini quoi), à-faire datés, vue 3D, serveur MCP.
- **Nouveau — le mode éco** : moins de tokens sans rien perdre — les sorties de commandes très longues vont dans un fichier (aperçu seul dans la conversation), la conversation est résumée plus tôt, et `brain eco` liste les plugins jamais utilisés ; posé une fois au démarrage, `brain eco --annuler` pour revenir.
- **Nouveau — le cerveau en wiki** (le « LLM Wiki » d'Andrej Karpathy) : `brain wiki init <dossier>` range chaque
  souvenir dans une page Markdown d'un dossier que tu ouvres dans Obsidian (idéalement un dépôt GitHub privé). Tu y
  déposes des sources (articles, PDF, transcriptions, notes) ; Claude les lit et tient à jour des pages de synthèse
  (sources résumées, entités, concepts, sujets, analyses), liées entre elles. Rien ne change tant que tu ne le lances pas.

- **Nouveau — le cerveau commun** : si tu le veux, ce que tu apprends (recherches, savoir, projets que tu déclares
  communs) nourrit aussi le cerveau de tes amis, et le leur nourrit le tien, presque en temps réel. Claude te le
  propose ; rien ne part avant ton oui, et jamais ton profil, tes préférences ni rien de personnel ou de sensible.

- **Nouveau — le cerveau e-commerce** (skill `/cerveau:ecommerce`) : un expert pour lancer ou faire décoller une
  boutique en ligne sans publicité et avec des outils gratuits — diagnostic, offre et marges, site et tunnel de vente,
  premiers clients, vidéo courte et algorithmes, SEO, GEO (ChatGPT, Perplexity, AI Overviews), e-mails, gestion,
  conformité. Il agit lui-même sur ta boutique et tes outils Google (fiches, SEO, flux), puis te dit ce qu'il a fait
  et comment l'annuler ; il te demande seulement pour l'argent (prix, promos) et les envois aux clients. Il publie sur
  ta page Facebook, ton Instagram pro ou YouTube une fois l'accès officiel branché, après ton « oui » sur le lot de la
  semaine ; ailleurs, il prépare et tu cliques. Le contexte de chaque boutique reste dans ta mémoire, chez toi.

- **Nouveau — le suivi de tes boutiques** : le cerveau suit chaque boutique comme un copilote. Un plan décollage daté
  (72 h, 14 jours, 30-60-90) dont les échéances te sont rappelées ; chaque lundi, les chiffres de la semaine avec un
  test statistique qui dit si une hausse est réelle ou du hasard, le canal qui rapporte le plus par heure et le goulot
  à traiter ; des audits gardés en historique (ce qui a été corrigé) avec contrôle de conformité légale, pages du site
  et vitesse ; un bilan avec trois priorités. Outils inclus : audit de tout le catalogue et flux Google Shopping,
  relecture des textes avant publication (allégations interdites, fausse urgence), comparaison des marges entre ta
  boutique, Etsy, Vinted ou TikTok Shop, modèles de textes prêts à adapter.

Tout reste chez toi, dans `~/.claude/brain` — ou dans ton wiki, sur ton PC et, si tu le choisis, dans ton dépôt
GitHub privé. Rien n'est envoyé ailleurs, sauf ta part publique si tu rejoins le cerveau commun ; chacun garde sa
propre mémoire.

## Prérequis

**Python 3.10 ou plus, et la commande `python`** : les hooks du plugin la lancent ; sans elle, rien n'est enregistré, sans aucune erreur visible.
- macOS : `mkdir -p ~/.local/bin && ln -sf "$(command -v python3)" ~/.local/bin/python`, puis redémarre Claude Code · Debian/Ubuntu : `sudo apt install python-is-python3` · Windows : réinstalle Python depuis python.org en cochant « Add python.exe to PATH ».
- **Vérifier que le cerveau enregistre**, après ton premier message : `python ~/.claude/brain/brain.py doctor` puis `python ~/.claude/brain/brain.py journal` (macOS sans `python` : `python3`) ; si ce fichier n'existe pas, les hooks ne tournent pas : diagnostic direct avec `python3 "$(ls -d ~/.claude/plugins/cache/*/cerveau/*/ | tail -1)brain.py" doctor`.

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

Tu avais déjà le cerveau en installation classique (code dans `~/.claude/brain`) ? Rien de plus à faire : au premier
démarrage, le plugin prend le relais tout seul — souvenirs gardés, ancien code archivé dans
`~/.claude/brain/archives`, anciens hooks retirés, mises à jour automatiques activées.

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
« retiens que … », ou tape `/brain`. Vue 3D de ta mémoire : `~/.claude/brain/cerveau.html` (souvenirs, projets,
le cerveau e-commerce avec ses fiches et ses outils, et tes boutiques suivies).

Pour une boutique : « fais décoller ma boutique », « trouve-moi des clients sans pub », « audite mon site », « quel
produit vendre ? », « fais le point de la semaine » — le cerveau e-commerce prend le relais tout seul (ou tape
`/cerveau:ecommerce`) et tient le suivi de chaque boutique (« où en est ma boutique ? »).

Avec un wiki : « ingère cet article », « range cette réponse dans le wiki », « fais le point sur le wiki » (contrôle de
santé : pages à créer, sources en attente, pages dépassées). Le schéma que suit Claude est dans le `CLAUDE.md` du wiki :
fais-le évoluer avec lui.

## Le cerveau commun (avec tes amis)

1. {owner} t'invite sur le dépôt GitHub privé du cerveau commun : accepte l'invitation (e-mail, ou
   https://github.com/notifications). Dépôt : `{commun}`.
2. Au démarrage suivant, Claude te le propose et te montre ce qui partirait. Rien ne part avant ton oui ; la première
   fois, une fenêtre de connexion à GitHub peut s'ouvrir.
3. Ensuite tout est automatique : ce que tu apprends part une quinzaine de secondes après (le temps de corriger ou de
   dire « garde ça pour moi »), ce que tes amis apprennent arrive à ton message suivant (moins de 2 minutes), marqué 🤝
   et en lecture seule.

Ne part jamais : ton profil et tes préférences, le contenu sensible (santé, argent, intimité, identité, opinions, mots
de passe), les personnes, tes documents personnels, tes projets tant que tu ne les déclares pas communs (« partage le
projet X avec les amis »), le texte de tes sessions. Coordonnées, secrets, chemins de fichiers et liens d'accès
(documents partagés, invitations, réunions) sont retirés du reste. « Garde ça pour moi » : la page reste privée.
`brain commun` montre l'état ; `brain commun quitter` pour en sortir (tes pages sont retirées).

Pour le lancer ({owner}) : crée sur GitHub le dépôt **privé et vide** `{commun}`,
invite tes amis (Settings → Collaborators → Add people), puis rejoins-le le premier (dis oui quand Claude le propose).

## Désinstaller

`/plugin uninstall cerveau@cerveau`. Tes souvenirs restent dans `~/.claude/brain` (supprime ce dossier pour tout effacer).

Version {__version__}.
"""


PRIVATE_TESTS = {"run_all.py", "test_all.py", "test_mcp.py", "test_units.py", "test_vault.py"}  # mémoire de Lucas


def public_tests(dest: Path) -> dict:
    """Les tests publics que le dépôt a déjà (posés à la main, par une session cloud ou un ami) : build() les garde, pris
    dans le code quand il les a. Un test n'y entre jamais tout seul, et un test privé jamais. → {chemin sous tests/: octets}"""
    root = Path(dest) / "tests"
    found = {}
    for p in sorted(root.rglob("*")) if root.is_dir() else []:
        rel = p.relative_to(root)
        if p.is_file() and p.suffix != ".pyc" and "__pycache__" not in rel.parts and p.name not in PRIVATE_TESTS:
            mine = CODE_DIR / "tests" / rel
            found[rel.as_posix()] = (mine if mine.is_file() else p).read_bytes()
    return found


def build(dest: Path, owner: str = "Lucas", repo: str = "") -> list:
    """Écrit le plugin complet dans dest (le clone du dépôt) : l'ancien contenu est remplacé, .git et les tests publics
    sont gardés. → liste des fichiers écrits (chemins relatifs)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / "brainkit").exists() and (dest / "graph.json").exists():
        raise RuntimeError(f"{dest} contient des souvenirs (graph.json) : ce n'est pas un dépôt de plugin")
    if dest.resolve() == CODE_DIR.resolve():
        raise RuntimeError(f"{dest} est le dossier du code lui-même : donne le clone du dépôt du plugin")
    from .install import EVENTS, SKILL, SKILL_MARK, skill_sources
    skills = skill_sources()  # relevées avant le nettoyage du dépôt
    tests = public_tests(dest)  # idem
    for item in dest.iterdir():
        if item.name != ".git":
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    shutil.copy2(CODE_DIR / "brain.py", dest / "brain.py")
    shutil.copytree(CODE_DIR / "brainkit", dest / "brainkit", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    hooks = {event: [{"hooks": [_hook(arg, timeout, status)]}] for event, arg, timeout, status in EVENTS}
    _json(dest / "hooks" / "hooks.json", {"description": "Cerveau : injection au démarrage, rappel à chaque message, "
                                                         "mémorisation en fin de tâche", "hooks": hooks})
    _json(dest / ".mcp.json", {"mcpServers": {"cerveau": {
        "command": "python", "args": ["-I", "-S", "${CLAUDE_PLUGIN_ROOT}/brain.py", "mcp"]}}})
    _lf(dest / "skills" / "brain" / "SKILL.md", SKILL)
    for name, src in skills.items():  # skills métier (cerveau e-commerce…) : Claude Code les lit dans le plugin
        shutil.copytree(src, dest / "skills" / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", SKILL_MARK))
    plugin = {"name": NAME, "version": __version__, "description": DESC, "author": {"name": owner},
              "keywords": KEYWORDS}
    if repo:
        plugin["homepage"] = plugin["repository"] = f"https://github.com/{repo}"
    _json(dest / ".claude-plugin" / "plugin.json", plugin)
    _json(dest / ".claude-plugin" / "marketplace.json", {
        "name": MARKET, "owner": {"name": owner},
        "metadata": {"description": f"Le cerveau persistant de {owner} pour Claude Code", "version": __version__},
        "plugins": [{"name": NAME, "source": "./", "description": DESC, "version": __version__}]})
    _lf(dest / "README.md", readme(owner, repo))
    _lf(dest / ".gitignore", "__pycache__/\n*.pyc\n")
    for rel, data in tests.items():
        (dest / "tests" / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / "tests" / rel).write_bytes(data)
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
    # Les hooks lancent des tâches de fond détachées (carte du dossier, synchro du wiki…) qui travaillent dans
    # ~/.claude/brain, ici dans tmp : sous Windows, tant qu'elles tournent, il ne s'efface pas (WinError 32). On ne
    # plante pas pour autant (ignore_cleanup_errors), et on retente quelques secondes, le temps qu'elles finissent.
    with tempfile.TemporaryDirectory(prefix="cerveau-ami-", ignore_cleanup_errors=True) as tmp:
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
    for _ in range(40):
        if not Path(tmp).exists():
            break
        time.sleep(0.5)
        shutil.rmtree(tmp, ignore_errors=True)
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
