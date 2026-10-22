"""Installation / réparation / désinstallation : bloc CLAUDE.md global, skill /brain, skills métier (cerveau
e-commerce…), hooks dans settings.json.

Idempotent : relancer `brain install` remplace proprement les éléments du cerveau sans toucher au reste."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from .common import BRAIN_PY, CLAUDE_HOME, CMD, CODE_DIR, load_config, read_json, write_json, write_text

START, END = "<!-- BRAIN:START", "<!-- BRAIN:END -->"

CLAUDE_BLOCK = f"""<!-- BRAIN:START (géré par ~/.claude/brain — `brain install` le réécrit ; ne pas éditer entre ces balises) -->
# 🧠 Cerveau persistant (`~/.claude/brain`)
Injecté tout seul : index + fiche du projet au démarrage, souvenirs/fichiers pertinents à chaque message (blocs 🧠/📁).
S'en servir AVANT d'explorer ou de redemander. Outil : `{CMD} <cmd>` (Bash/PowerShell) — détail : skill `/brain`.
`q "sujet"` · `add -t <type> -T "titre" -b "fait + pourquoi + comment"` · `edit`/`show <id>` · `todo` · `files`/`where`/`explain`/`impact <x>` · `map .` · `wiki add <source>` · `commun` (cerveau des amis)
1. Projet : carte (MAP.md) et `files`/`where`/`explain` avant tout Glob/Grep/Read en masse ; pas de carte → `map .`.
2. Mémoriser aussitôt le durable — feedback (préférence, correction), user, decision, fact (travail en cours),
   learning (piège, solution), reference, todo (`--due`) — après un `q` anti-doublon.
3. Jamais : secrets, mots de passe, paiement, santé ou vie privée de tiers, ce que le code ou git disent déjà.
4. Fait qui change → `add … --replaces <id>` ; erreur → `edit`/`rm` ; vérifier un souvenir ancien avant d'agir.
Tokens : filtrer les sorties Bash (`| tail -n 30`, `grep -c`, `-q`) ; gros fichier → `explain`/Grep puis Read offset/limit ; Edit plutôt que réécrire un fichier ; chaque appel relit tout le contexte : grouper les lectures (plusieurs plages ou fichiers par commande) et les appels indépendants dans un même message ; ToolSearch : un seul `select:a,b,c` ; web : get_page_text/find plutôt que read_page entier ou capture (sinon `scale: 0.5`) ; sous-agent (repart de ~90 k) seulement pour une très large recherche ; pas de relecture ; réponses courtes, résultat vérifié.
<!-- BRAIN:END -->
"""

SKILL = f"""---
name: brain
description: Cerveau persistant de Claude : mémoire en graphe datée (souvenirs, concepts, liens), wiki Markdown tenu par Claude (sources ingérées, entités, concepts, sujets — coffre Obsidian, dépôt git), cartes de projets, à-faire, historique, MCP, vue 3D. Pour retrouver ou mémoriser un souvenir, ingérer une source dans le wiki, trouver un fichier ou un symbole sans explorer, reprendre une session, ou quand l'utilisateur dit « souviens-toi », « retiens », « cerveau », « wiki », « ingère », « /brain ».
---

# 🧠 Cerveau — référence

Commande : `{CMD} <commande>` (fonctionne dans Bash et PowerShell). Sortie compacte, pensée pour économiser les tokens.

## Ce qui se passe tout seul (hooks)
- **Démarrage de session** : index du cerveau + fiche du projet courant (souvenirs, 3 dernières sessions, fin de la
  dernière session, résumé de carte) injectés ; dans un projet, l'index global se resserre sur ce qui s'y rapporte ;
  les à-faire dont l'échéance approche (ou est dépassée) passent en tête (« ⏰ Échéances »). Dossier de projet inconnu → enregistré et cartographié en arrière-plan.
- **Chaque message** : rappel automatique des souvenirs/fichiers vraiment liés (filtre anti-bruit, jamais deux fois) ;
  la recherche tolère fautes, écriture phonétique et synonymes FR/EN (« boutik », « shopfy », « rdv » → agenda).
- **Fin de tâche importante** : rappel unique de noter 3 à 5 **observations datées** de la session (`obs "🔴 …" "🟡 …"`)
  et de mémoriser l'essentiel, avec les phrases de l'utilisateur qui ressemblent à une préférence ou une décision
  (« Candidats repérés… ») : juger, puis `add` ce qui est durable. Après une **compaction** du contexte, le Stop suivant
  demande les observations de la session (le détail n'est plus que résumé).
- **Usage réel** : un souvenir montré dont les termes ou les chiffres reviennent dans ta réponse ou tes commandes
  compte comme *utilisé* (montré ≠ utilisé) ; le classement de l'index en tient compte.
- **Réflexes de skills** : quand un message colle à une skill perso (`~/.claude/skills`, ou `.claude/skills` du
  projet) par un de ses déclencheurs « … », une ligne 🧩 dit de la charger d'abord (outil Skill) — une fois par session,
  rétrogradée en « peut-être » si le message contient un mot de sa partie « Ne pas utiliser… ». Une méthode ou un
  prompt structuré collé → 🧩 en faire une skill (`skill new`), ou mettre à jour celle qui lui ressemble.
- **Fin de session** : journal, vue 3D, et une fois par jour consolidation prudente (doublons évidents, souvenirs
  remplacés via `supersedes`, secrets) puis **rêve** (dates relatives rendues absolues, observations de plus de 7 jours
  condensées en un résumé par semaine et par projet, dossier `REVE.md` des points à trancher ; s'il y en a assez, une
  ligne 🌙 au démarrage propose de le confier à un sous-agent en arrière-plan :
  `dream` → appliquer ce qui est sûr → `dream --done`), avec instantané pris avant, et sauvegarde hors du disque système
  (`D:\\Sauvegardes-cerveau-Claude` par défaut : une réinstallation de Windows n'efface plus le cerveau).
- **Auto-réparation** : si graph.json est illisible, le cerveau repart du dernier instantané valide (ou de la
  dernière sauvegarde) et garde le fichier abîmé à côté ; jamais d'écrasement par un graphe vide.
- **Sécurité** : clés, jetons et mots de passe sont masqués automatiquement à l'écriture ; chaque modification
  peut être annulée (`history` / `restore`).
- La mémoire native de Claude Code (`~/.claude/projects/*/memory`) est importée automatiquement.

## Mémoire
| But | Commande |
|---|---|
| Chercher (souvenirs + voisins du graphe + sessions passées + fichiers du projet) | `q "mots clés" [-p projet] [-t type] [--only] [--no-graph]` — comprend les dates (« hier », « le 12/11 », « il y a 3 semaines ») et le deuxième saut (« ← lien (sato) » : souvenir relié par un nom propre) ; « ≈ à vérifier » = confiance basse |
| Mémoriser | `add -t <type> -T "titre court" -b "fait + pourquoi + comment appliquer" [--tags a,b] [-i 1-5] [-p .\\|none\\|id] [--link id] [--due 10/11] [--replaces id] [--keys "synonymes, questions"] [--src utilisateur\\|verifie\\|deduit]` (étiquettes auto si absentes, liens suggérés affichés ; « hier », « dans 2 semaines » deviennent des dates réelles) |
| Question large (« où en est la boutique ? », « le point sur… ») | `q` place d'abord la **fiche de synthèse** de la communauté dominante (phrases les plus centrales de ses souvenirs, à-faire, ids), puis les souvenirs qu'elle ne cite pas · `fiche` liste les fiches · `fiche <n°\\|mot\\|id>` |
| Observations datées de la session (mémoire épisodique, façon Mastra) | `obs "🔴 décision, blocage" "🟡 avancée" "🟢 détail"` (« 14:20 » en tête au besoin ; « hier » devient une date) · `obs` les dernières · `obs -p projet --days 7` — retrouvées par `q` (texte ou date : « on a fait quoi hier ? »), condensées par le rêve après 7 jours ; jamais injectées au démarrage |
| Fait qui change (façon Zep / mem0) | `add … --replaces <ancien>` ou `supersede <nouveau> <ancien>` : l'ancien est archivé avec sa date de fin, la chaîne reste visible dans `show`. Un `add` sur le même sujet remplace tout seul l'ancien si une valeur change (chiffre, négation, « désormais », autre nom propre) ; jamais quand le titre vise une autre entité ou une autre date ; « ↻ remplace peut-être » = à confirmer |
| Voyage dans le temps | `q "sujet" --at 15/10\\|hier\\|"il y a 3 jours"` (le cerveau tel qu'il était) · `show <id> --history` (versions successives) · `history --diff <n°\\|date>` (ce qui a changé depuis) |
| À-faire et échéances | `todo` (triés par échéance) · `done <id>` · `edit <id> --due "10/11"\\|"demain"\\|"dans 2 semaines"\\|none` |
| Corriger / compléter | `edit <id> [-T …] [-b …] [-a "ajout"] [-i 4] [--add-tags x]` |
| Voir / lister | `show <id>` · `ls [-t type] [-p projet]` |
| Lier | `link <a> <b> [-r relates\\|depends_on\\|fixes\\|supersedes\\|contradicts]` (ou `[[id]]` dans un contenu) · `link --suggest` liens déduits à confirmer |
| Archiver | `rm <id>` (réversible : `edit <id> --unarchive`) · `--purge` = définitif (instantané pris avant) |
| Historique / annuler | `history` (instantanés) · `restore <n°>` (l'état courant est sauvegardé d'abord) |
| Sauvegardes (autre disque) | `backup` · `backup --list` · `backup --restore <archive.zip>` · `backup --to <dossier>` |

Types : `user` (qui est l'utilisateur), `feedback` (règle/préférence/correction), `project` (un dossier), `decision`,
`fact` (état/fait sur un travail en cours), `learning` (piège, solution, astuce), `reference` (lien, doc, ressource),
`entity` (outil, service, contact pro), `todo`.
Projet par défaut = projet du dossier courant (sauf `user`/`feedback`, globaux) ; `-p none` force le global.
Anti-doublon intégré : un `add` quasi identique complète le souvenir existant au lieu d'en créer un autre.

**Bon souvenir** : précis, actionnable, daté si utile. Ex. `add -t learning -T "Stats Shopify polluées par robots" -b "92 %
des sessions sont des bots US : filtrer session_country='France' avant tout calcul de conversion."`
**À ne pas stocker** : secrets, données sensibles ou de tiers, ce que le code/git disent déjà, l'éphémère.

## Wiki (le « LLM Wiki » de Karpathy)
Le cerveau peut vivre dans un **wiki Markdown** (un dépôt git ouvert comme coffre Obsidian) : chaque souvenir y est
une page, et Claude y compile le savoir des sources — `raw/` (sources brutes, immuables), `wiki/<Type>/` (pages tenues
par Claude), `archive/`, `CLAUDE.md` (le schéma : conventions et méthodes, à suivre et à faire évoluer), `index.md`
(catalogue régénéré), `log.md` (journal, on ajoute en bas). Types de savoir en plus : `source`, `concept`, `topic`
(sujet), `analysis` (analyse) ; `add`/`edit`/`rm` créent, modifient, archivent les pages ; `q` cherche dans tout le wiki.

| But | Commande |
|---|---|
| Créer le wiki et y migrer le cerveau (rien n'est perdu : instantané + copie de graph.json) | `wiki init <dossier>` (idéalement le clone d'un dépôt GitHub privé) |
| Ingérer une source : rangée dans raw/, page Sources créée, plan affiché (pages concernées, entités repérées) | `wiki add <fichier\\|url\\|->` (`-` = texte par stdin, avec `-T "Titre" [--url …] [--format video]`) |
| Sources en attente (déposées dans raw/ par le Web Clipper, ou pages Sources à remplir) | `wiki pending` |
| Santé : pages à créer, orphelines, sans résumé, sources abîmées, pages dépassées, doublons, contradictions | `wiki lint [--log]` |
| Journal : noter une ingestion, une réponse rangée, un entretien · voir les dernières entrées | `wiki log ingest\\|query\\|lint\\|note "titre" "ligne" …` · `wiki log` |
| État (pages, sources, git) · schéma par défaut · index.md · commit + pull + push | `wiki` · `wiki schema` · `wiki index` · `wiki sync` |

Méthode d'ingestion (détail dans le CLAUDE.md du wiki) : lire la source → dire les points clés → remplir la page
Sources (remplacer « ⏳ à remplir », `resume:`) → intégrer dans les pages concernées (10 à 15 pages, `sources:`),
contradictions en `> [!contradiction]` → `wiki log ingest`. Une bonne réponse se range dans une page Analyses.
Sur le PC, commit/pull/push se font seuls en début et en fin de session ; dans une session cloud, pousser sur sa branche.

## Cerveau commun (avec les amis)
Ce que chacun apprend nourrit le cerveau de tous, presque en temps réel (envoi ~15 s après un ajout — corriger ou
`--commun non` dans ce délai et le premier jet ne part pas ; pages des amis récupérées au démarrage, à chaque message et
en fin de tour, au plus une fois par minute), **sans rien de privé**. Un
dépôt GitHub privé ; chaque cerveau publie sa part publique dans `membres/<nom>/` et lit celle des autres en lecture
seule (pages marquées 🤝 nom).
**Ne part jamais** : profil, règles, contenu sensible (santé, argent, intimité, identité, opinions, accès), page ayant
contenu un secret, personnes, documents personnels (source sans adresse web publique) et ce qui n'est tiré que d'eux,
références, domaine « perso », projets non partagés, ce qui est marqué privé, texte des sessions. Retirés du reste :
coordonnées, secrets, chemins de fichiers, liens d'accès (document partagé, invitation, réunion) ; lien vers une page
privée → « [privé] ». **Part** : le savoir (sources web, concepts, sujets, analyses, apprentissages, entités qui ne sont
pas des personnes : appuyées sur une source web ou étiquetées entreprise, outil, lieu, œuvre…), ce qui appartient à un
projet commun, ce qui est marqué partagé. Rien ne part avant l'accord : quand le démarrage propose le cerveau commun, le
dire à l'utilisateur avec l'aperçu, et n'entrer qu'avec son oui.

| But | Commande |
|---|---|
| État · ce qui partirait (et ce qui reste privé) · ce que je partage | `commun` · `commun apercu` · `commun liste` |
| Entrer (après l'accord de l'utilisateur) · refuser · sortir | `commun rejoindre --oui --nom <pseudo>` · `commun non` · `commun quitter [--garder]` |
| Partager un projet (ses tâches, décisions, faits, observations) · le rendre privé | `commun projet <id>` · `commun projet <id> --non` |
| Forcer pour un souvenir : partager · garder privé · règles par défaut | `add`/`edit … --commun oui\\|non\\|auto` |
| Synchroniser tout de suite | `commun sync` |

Pages des amis : s'en servir, les citer ; pour compléter, écrire sa propre page (elle part). Elles ne se modifient pas.

## Skills métier livrées avec le cerveau
**Cerveau e-commerce** (`/cerveau:ecommerce` en plugin, `/ecommerce` en installation classique) : faire décoller une
boutique en ligne sans pub et avec des outils gratuits (diagnostic, offre et marges, site et tunnel de vente, premiers
clients, vidéo et algorithmes, SEO, GEO, e-mails, gestion, conformité, pilotage du navigateur). Chaque boutique est
suivie par le cerveau : données privées (jamais dans le cerveau commun), comprises dans les sauvegardes.

| But | Commande |
|---|---|
| Boutiques suivies (dernière semaine, plan, dernier audit) · en faire suivre une (fichier de suivi + fiche contexte privée) | `boutique` · `boutique ajouter "Nom" --url https://… [--type physique\\|mode\\|createur\\|occasion\\|niche\\|prevente\\|local\\|numerique\\|b2b] [--chemin plateforme\\|0euro] [--marge-commande 12,5]` |
| Plan décollage en à-faire datés (72 h, 14 jours, 30-60-90, adapté au type), rappelés au démarrage | `boutique plan <boutique> [--debut 20/10] [--court] [--force]` |
| Chiffres d'une semaine complète → taux, test statistique contre les semaines d'avant, marge par heure par canal, goulot probable | `boutique kpi <boutique> --sessions … --ajouts … [--checkouts …] --commandes … [--ca …] [--heures …] [--canal nom:sessions:commandes[:heures]] [--semaine 12/10] [--note "…"]` |
| Audit SEO/GEO gardé en historique (corrigé, nouveau) ; conformité légale, pages du sitemap, vitesse | `boutique audit <boutique\\|url> [--conformite] [--pages 10] [--vitesse] [--complet] [--rapport audit.md]` |
| Revue (chiffres, plan, audits, trois priorités) · réglages | `boutique bilan <boutique> [--md bilan.md]` · `boutique regler <boutique> url=… marge=… seuil.ajout=6` |

Fiche « Boutique <nom> — fiche contexte » : `q "boutique <nom>"` ; décisions et apprentissages en `add` (chiffres en
`--commun non`).

## Ailleurs que dans l'onglet Code
| But | Commande |
|---|---|
| Coffre Obsidian / Markdown, synchronisé dans les deux sens (une note par souvenir, propriétés, liens `[[ ]]`) — sans objet en mode wiki (le wiki est le coffre) | `export --vault <dossier>` (dossier retenu ensuite : `export --vault`) — notes modifiées rapatriées champ par champ, nouvelle note dans « À trier » = nouveau souvenir, note supprimée = souvenir archivé, conflit = version Obsidian gardée dans « Conflits » · `--push` écrase le coffre |
| Serveur MCP (chat Claude, Cowork, tout client MCP) : outils memory_search / memory_add / memory_show / memory_update / memory_todo / memory_context, et wiki_status / wiki_add_source / wiki_lint / wiki_log | `mcp` (stdio) · `install --mcp` l'enregistre dans l'app Claude (`--uninstall` le retire) |

## Graphe (façon graphify)
| But | Commande |
|---|---|
| Rapport : communautés, nœuds clés, liens surprenants, liens suggérés, doublons, trous, questions | `report [--print]` (→ `RAPPORT.md`) |
| Chemin entre deux souvenirs (liens explicites d'abord, puis déduits) | `path <id_a> <id_b>` |
| Communauté, centralité, concepts et liens déduits d'un souvenir | `show <id>` |
| Fiche de synthèse d'une communauté (extractive, régénérée seulement quand un membre change) | `fiche [n°\\|mot\\|id]` |
| Concepts repérés (outils, sujets, sigles, domaines, produits) et souvenirs liés | `concept [nom]` |
| Vue 3D interactive (mémoire, concepts, chronologie, Maj+clic = chemin, cartes de projets) | `viz --open` → `cerveau.html` (`cerveau-2d.html` hors ligne) |

Liens **déduits** = similarité du contenu (raison : mots communs ; confiance forte/moyenne/faible), jamais écrits
dans le graphe tant qu'ils ne sont pas confirmés par `link`. Analyse en cache (`state/analysis.json`), recalculée
seulement quand le savoir change.

## Projets (façon graphify)
| But | Commande |
|---|---|
| Cartographier / mettre à jour (incrémental) | `map [dossier] [--full] [--bg]` |
| Fichiers liés à un sujet | `files "paiement panier"` |
| Où est défini X (fonction, classe, variable d'env, route) | `where X` |
| Fiche d'un fichier ou symbole | `explain <fichier\\|symbole>` |
| Ce qui dépend d'un fichier ou d'une fonction (avant de modifier) | `impact <fichier\\|symbole>` |
| Dépendances | `deps <fichier>` · chemin entre deux fichiers : `path <a> <b>` |
| Projets connus | `proj` · `proj add <dossier> -T "Nom" -b "description"` |

Carte complète : `~/.claude/brain/projects/<id>/MAP.md` (structure, fichiers clés par centralité, modules, routes,
variables d'env, documents, cycles, TODO, fichiers sensibles jamais lus).

## Entretien
`journal [-p projet]` sessions passées · `journal -s "mots"` chercher dans leur texte · `journal --backfill` importer celles que les hooks ont manquées · `context` ce qui est injecté ici · `recall "message"` tester le rappel ·
`consolidate [--dry-run]` fusion doublons/obsolètes · `dream` rêve (entretien : conflits, doublons, corrections entendues ; `--done`) · `stats` · `doctor` diagnostic (`doctor --fix` répare tout) ·
`bench` banc d'essai (qualité du rappel, faux rappels, tokens par démarrage, vitesse des hooks) · `tokens [--hours 48]` où partent les tokens (contexte relu, coût fixe au démarrage, relances, habitudes coûteuses, mesuré sur les transcripts) · `report` rapport du graphe ·
`eco` mode éco, moins de tokens sans rien perdre : état + plugins jamais utilisés · `eco --appliquer` (sorties de commandes longues mises en fichier, résumé de la conversation plus tôt, liste des skills réduite, mémoire auto coupée ; posé tout seul au 1er démarrage) · `eco --annuler` · `eco --poser ID` / `eco --retirer ID` (réglages sur accord : outils, connecteurs, git, effort, lecture, sous-agents — seulement après accord explicite de l'utilisateur) · `eco --cache auto|5m|1h|off` (durée du cache de prompt ; auto = choisie chaque jour d'après les pauses réelles) · `eco --desactiver nom@marketplace` (demande d'abord à l'utilisateur) · `eco --plugins-auto [on|off]` (veille quotidienne : désactive tout seul plugins et skills claude.ai jamais utilisés en 30 j ; seulement si l'utilisateur le demande) ·
`pc` état du PC (RAM/CPU/GPU) et ce qu'on peut libérer (sessions inactives, serveurs MCP) · `pc --clean` ferme les serveurs MCP orphelins (parent mort) · `pc --history [h]` mesures de la veille ·
`skill` skills perso (+ combien de fois soufflées et chargées) · `skill test "message"` laquelle se déclencherait · `skill check` contrôle (déclencheurs, liens, longueur) · `skill new <nom> -d "À utiliser quand… « … » Ne pas utiliser pour…" --body-file f` créer ·
`viz --open` vue 3D (`~/.claude/brain/cerveau.html`, régénérée en fin de session) · `export` (MEMOIRES.md lisible) ·
`config recall.enabled false` · `config skills.paste auto|propose|off` · `install` réparer.
"""

EVENTS = [
    ("SessionStart", "session-start", 20, "🧠 Chargement du cerveau…"),
    ("UserPromptSubmit", "prompt", 8, None),
    ("Stop", "stop", 10, None),
    ("PreCompact", "pre-compact", 15, None),
    ("PostCompact", "post-compact", 10, None),
    ("SessionEnd", "session-end", 15, None),
]


SKILL_MARK = ".cerveau"  # dans ~/.claude/skills/<nom>/ : skill métier posée par le cerveau (remplacée quand elle change,
# retirée à la désinstallation). Un dossier du même nom sans cette marque appartient à l'utilisateur : jamais touché.


def skill_sources() -> dict:
    """Skills métier livrées avec le cerveau, {nom: dossier} : skills/<nom>/SKILL.md à côté du code, hors « brain »
    (écrite depuis SKILL) ; à défaut, dans l'arbre de développement d'où vient le code (`brain self-update`)."""
    roots = [CODE_DIR / "skills"]
    source = (load_config().get("selfupdate") or {}).get("source")
    if source:
        roots.append(Path(source) / "skills")
    found = {}
    for root in roots:
        try:
            dirs = sorted(d for d in root.iterdir() if d.is_dir())
        except OSError:
            continue
        for d in dirs:
            if d.name != "brain" and d.name not in found and (d / "SKILL.md").is_file():
                found[d.name] = d
    return found


def _skill_stamp(src: Path) -> str:
    """Empreinte du contenu d'une skill : elle change dès qu'un de ses fichiers change."""
    h = hashlib.sha1()
    for p in sorted(src.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc" and p.name != SKILL_MARK:
            h.update(p.relative_to(src).as_posix().encode("utf-8") + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def sync_skills(uninstall=False, quick=False) -> list:
    """Cerveau classique : pose ou met à jour les skills métier dans ~/.claude/skills (en plugin, Claude Code les lit
    directement dans le plugin) ; uninstall les retire. quick (démarrage de session) : rien n'est relu tant que la
    marque porte la version du code. → lignes de compte rendu."""
    from . import __version__
    base = CLAUDE_HOME / "skills"
    done = []
    if uninstall:
        for mark in sorted(base.glob(f"*/{SKILL_MARK}")):
            shutil.rmtree(mark.parent, ignore_errors=True)
            done.append(f"✓ skill /{mark.parent.name} retirée")
        return done
    for name, src in skill_sources().items():
        dst = base / name
        mark = dst / SKILL_MARK
        if dst.exists() and not mark.exists():
            done.append(f"· skill /{name} : {dst} existe déjà sans la marque du cerveau — laissée telle quelle")
            continue
        old = read_json(mark, {}) or {}
        if quick and old.get("version") == __version__:
            continue
        stamp = _skill_stamp(src)
        if old.get("stamp") != stamp or _skill_stamp(dst) != stamp:  # source changée, ou copie installée abîmée
            # Préparée à côté de skills/ (Claude Code n'y cherche pas de skill), puis échangée par renommages : un
            # fichier verrouillé (Windows) fait échouer l'échange en entier, jamais à moitié.
            stage = CLAUDE_HOME / ".cerveau-skills"
            tmp, trash = stage / f"{name}.tmp", stage / f"{name}.old"
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(trash, ignore_errors=True)
            shutil.copytree(src, tmp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", SKILL_MARK))
            write_json(tmp / SKILL_MARK, {"version": __version__, "stamp": stamp})
            if dst.exists():
                os.replace(dst, trash)
            base.mkdir(parents=True, exist_ok=True)
            os.replace(tmp, dst)
            shutil.rmtree(trash, ignore_errors=True)
            done.append(f"✓ skill /{name} → {dst}")
        else:
            write_json(mark, {"version": __version__, "stamp": stamp})
    return done


def launcher() -> str:
    """Commande des hooks. Python lancé directement (pas via le lanceur « py », qui crée un 2e processus) et en mode
    isolé sans site (-I -S : le cerveau n'utilise que la bibliothèque standard) → ~30 ms de moins par hook.
    Si Python change de version, `brain install` (ou `doctor --fix`) remet le bon chemin."""
    script = str(BRAIN_PY).replace("\\", "/")
    exe = sys.executable or ""
    if exe and os.path.exists(exe) and "windowsapps" not in exe.lower() and not exe.lower().endswith("pythonw.exe"):
        return f'"{exe.replace(chr(92), "/")}" -I -S "{script}"'
    if os.name == "nt" and shutil.which("py"):
        return f'py -3 "{script}"'
    return f'"{exe.replace(chr(92), "/")}" "{script}"'


def _is_ours(entry) -> bool:
    return any("brain.py" in str(h.get("command", "")) and " hook " in str(h.get("command", ""))
               for h in entry.get("hooks", []) if isinstance(h, dict))


def merged_settings(settings: dict, remove_only=False) -> dict:
    out = dict(settings)
    hooks = dict(out.get("hooks") or {})
    for event, arg, timeout, status in EVENTS:
        entries = [e for e in hooks.get(event, []) if not (isinstance(e, dict) and _is_ours(e))]
        if not remove_only:
            hook = {"type": "command", "command": f"{launcher()} hook {arg}", "timeout": timeout}
            if status:
                hook["statusMessage"] = status
            entries.append({"hooks": [hook]})
        if entries:
            hooks[event] = entries
        else:
            hooks.pop(event, None)
    if hooks:
        out["hooks"] = hooks
    else:
        out.pop("hooks", None)
    return out


def merged_claude_md(text: str, remove_only=False) -> str:
    if START in text and END in text:
        before = text[: text.index(START)].rstrip()
        after = text[text.index(END) + len(END):].lstrip("\n")
        text = (before + ("\n\n" if before else "") + after).strip()
    if remove_only:
        return (text + "\n") if text else ""
    return (CLAUDE_BLOCK + ("\n" + text + "\n" if text else "")).rstrip() + "\n"


def run(dry=False, uninstall=False):
    from .common import PLUGIN
    if PLUGIN:
        print("🧩 Mode plugin : hooks, skill /brain et serveur MCP viennent du plugin « cerveau », que Claude Code met à "
              "jour tout seul ; les consignes sont injectées au démarrage de chaque session. Rien à installer ici.")
        return
    if not dry and not uninstall:
        from .store import ensure_usage_baseline
        if ensure_usage_baseline():
            print("✓ mesure de l'usage réel démarrée (montré ≠ utilisé)")
    settings_path = CLAUDE_HOME / "settings.json"
    claude_md = CLAUDE_HOME / "CLAUDE.md"
    skill_path = CLAUDE_HOME / "skills" / "brain" / "SKILL.md"

    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception as exc:
            sys.exit(f"✗ {settings_path} n'est pas un JSON valide ({exc}) : corrige-le avant d'installer.")
    new_settings = merged_settings(settings, remove_only=uninstall)
    old_md = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
    new_md = merged_claude_md(old_md, remove_only=uninstall)

    verb = "désinstaller" if uninstall else "installer"
    if dry:
        print(f"[simulation] {verb} :")
        print(f"- {settings_path} → hooks : " + json.dumps(new_settings.get("hooks", {}), ensure_ascii=False, indent=1))
        print(f"- {claude_md} → bloc cerveau {'retiré' if uninstall else 'présent'} ({len(new_md)} car.)")
        print(f"- {skill_path} → {'supprimé' if uninstall else 'écrit'}")
        for name in skill_sources():
            print(f"- {CLAUDE_HOME / 'skills' / name} → skill métier {'retirée' if uninstall else 'posée'}")
        return

    if new_settings != settings:
        if settings_path.exists():
            shutil.copy2(settings_path, settings_path.with_name("settings.json.bak-brain"))
        write_json(settings_path, new_settings, indent=2)
    if new_md != old_md:
        if new_md:
            write_text(claude_md, new_md)
        elif claude_md.exists():
            claude_md.unlink()
    if uninstall:
        if skill_path.exists():
            skill_path.unlink()
        for line in sync_skills(uninstall=True):
            print(line)
        print("✓ cerveau débranché (hooks, CLAUDE.md, skills). Les données restent dans ~/.claude/brain.")
    else:
        write_text(skill_path, SKILL)
        print(f"✓ hooks ({', '.join(e for e, *_ in EVENTS)}) → {settings_path}")
        print(f"✓ bloc « cerveau » → {claude_md}")
        print(f"✓ skill /brain → {skill_path}")
        for line in sync_skills():
            print(line)
        print("→ hooks actifs tout de suite, même dans les sessions ouvertes ; l'injection de démarrage et CLAUDE.md "
              "s'appliquent au prochain démarrage de session.")
