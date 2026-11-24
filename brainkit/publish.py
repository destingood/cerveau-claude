"""Plugin Claude Code « cerveau » pour les amis : `brain publish <dépôt>` construit le plugin (code, hooks, serveur MCP,
skill, marketplace) dans le clone local du dépôt GitHub, le vérifie dans un bac à sable, puis fait le commit et le tag
de la version. Chez un ami, Claude Code installe le plugin une fois, puis le met à jour tout seul (`autoUpdate`) à chaque
version publiée ; ses souvenirs restent chez lui, dans ~/.claude/brain, et ne partent jamais.

Ne part dans le dépôt que le code (brain.py, brainkit/) et les skills (/brain, et les skills métier de skills/<nom>/,
comme le cerveau e-commerce) et les styles de réponse (output-styles/) : jamais les souvenirs ni la configuration. Les tests publics que le dépôt a déjà
(tests/) restent, mis à jour depuis le code ; les tests privés (PRIVATE_TESTS : ils lisent la vraie mémoire), jamais.
L'envoi sur GitHub est une publication : il n'a lieu qu'avec `--push`.

Lancé depuis le clone du dépôt lui-même (D1 du plan v2 : GitHub est la seule source du code), `brain publish` publie
sur place : il ne réécrit que les fichiers générés (hooks, skill /brain, manifestes, README) et brain.exe, refuse de
partir avec des changements non validés, et n'efface rien. Depuis un autre dossier (l'ancien mode, qui recopie le code
dans le clone), il refuse d'effacer un fichier suivi par git qui n'appartient pas au plugin."""
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
from .common import CODE_DIR, load_config, read_json, remove_tree, set_config

NAME = MARKET = "cerveau"
AUTRES = {"plateforme"}  # dossiers d'autres projets du même dépôt (PR #8) : ni effacés, ni contrôlés, ni commités ici
# Tenus dans le dépôt lui-même, jamais effacés : CI (.github) et garde-fous de Claude Code ouverts à la racine (.claude)
KEEP = {".git", ".github", ".claude", "CONTRIBUTORS.md"} | AUTRES
# Ce que la construction écrit à la racine du dépôt (et .mcp.json, qu'elle écrivait avant la 8.22) : elle peut le
# refaire. Un fichier suivi par git hors de KEEP et d'OWNED appartient à autre chose : il n'est jamais effacé (C23).
OWNED = {"brain.py", "brain.exe", "brainkit", "hooks", "skills", "output-styles", "agents", ".claude-plugin",
         "README.md", ".gitignore", "tests", ".mcp.json"}
# Serveur MCP du plugin, déclaré dans plugin.json et non dans un .mcp.json à la racine : ce fichier est aussi lu comme
# configuration du projet quand le dépôt est ouvert dans Claude Code, où ${CLAUDE_PLUGIN_ROOT} n'existe pas (le
# serveur échouait : « python: can't open file '…/${CLAUDE_PLUGIN_ROOT}/brain.py' »).
MCP_SERVERS = {"cerveau": {"command": "python", "args": ["-I", "-S", "${CLAUDE_PLUGIN_ROOT}/brain.py", "mcp"]}}
DESC = ("Cerveau persistant pour Claude Code : souvenirs en graphe, rappel automatique à chaque message, wiki Markdown "
        "tenu par Claude (sources ingérées, coffre Obsidian, dépôt git), cartes de projets, à-faire datés, serveur MCP, "
        "et un cerveau e-commerce qui suit chaque boutique (clients sans pub, SEO, GEO, tunnel de vente, chiffres de "
        "la semaine). Tout reste chez toi.")
KEYWORDS = ["mémoire", "memory", "souvenirs", "rappel", "hooks", "mcp", "wiki", "obsidian", "e-commerce", "seo", "geo",
            "fortnite", "vente"]
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
    from .install import ASYNC
    h = {"type": "command", "command": "python", "args": ["-I", "-S", "${CLAUDE_PLUGIN_ROOT}/brain.py", "hook", arg],
         "timeout": timeout}
    if status:
        h["statusMessage"] = status
    if arg in ASYNC:  # sortie inutile, rien ne l'attend : lancé sans bloquer (install.ASYNC)
        h["async"] = True
    return h


def readme(owner: str, repo: str) -> str:
    """Le README du dépôt publié (la page GitHub) : installation d'abord, puis ce que fait le cerveau, par thème ;
    README.md de ce dépôt = readme("destingood", "destingood/cerveau-claude"), régénéré par `brain publish`."""
    repo = repo or "PROPRIETAIRE/DEPOT"
    commun = (read_json(CODE_DIR / "brainkit" / "commun.json", {}) or {}).get("repo") or "PROPRIETAIRE/cerveau-commun"
    return f"""# 🧠 Cerveau pour Claude Code

Une mémoire persistante pour Claude Code, faite par {owner} : Claude se souvient de toi, de tes projets, de tes
décisions et de ce qu'il a appris, d'une session à l'autre. Tout reste chez toi, sur ton PC.

![Version {__version__}](https://img.shields.io/badge/version-{__version__}-2ea44f) ![Python 3.10 ou plus](https://img.shields.io/badge/python-3.10%2B-3776ab) ![Windows, macOS, Linux](https://img.shields.io/badge/Windows_%C2%B7_macOS_%C2%B7_Linux-555)

**Sommaire** — [Installer](#installer-une-seule-fois) · [Au quotidien](#au-quotidien) · [Ce que fait le cerveau](#ce-que-fait-le-cerveau) ·
[Moins de tokens](#moins-de-tokens) · [Il apprend tout seul](#le-cerveau-apprend-tout-seul) ·
[Wiki et veille](#le-cerveau-en-wiki-et-la-veille-automatique) · [E-commerce](#le-cerveau-e-commerce) ·
[Outils installés pour toi](#les-outils-que-claude-installe-pour-toi) · [Cerveau commun](#le-cerveau-commun-avec-tes-amis) ·
[Prérequis et dépannage](#prérequis) · [Désinstaller](#désinstaller)

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
   toi de les autoriser. Ensuite, quand une nouvelle version est publiée, Claude Code la récupère pendant une session
   (quelques minutes après ton premier message) et l'applique au démarrage suivant. Tes souvenirs ne sont jamais
   touchés par une mise à jour.
4. **Redémarre Claude Code.** Au premier démarrage, le cerveau crée `~/.claude/brain`. Pour vérifier qu'il
   enregistre bien : [Prérequis](#prérequis).

Tu avais déjà le cerveau en installation classique (code dans `~/.claude/brain`) ? Rien de plus à faire : au premier
démarrage, le plugin prend le relais tout seul — souvenirs gardés, ancien code archivé dans
`~/.claude/brain/archives`, anciens hooks retirés, mises à jour automatiques activées.

<details>
<summary>Variante sans commande, mises à jour automatiques comprises</summary>

Ajoute ceci à `~/.claude/settings.json` (à fusionner avec ce qui s'y trouve déjà ; `"autoUpdate": true` = mises à
jour automatiques), puis redémarre Claude Code :

```json
{SETTINGS_SNIPPET.format(repo=repo)}
```

</details>

## Au quotidien

Rien à faire : parle normalement à Claude. Pour aller plus loin :

| Tu dis… | Et le cerveau… |
|---|---|
| « qu'est-ce que tu sais sur … ? », « retiens que … », ou `/brain` | répond depuis ta mémoire, ou y note ce que tu lui confies |
| « fais décoller ma boutique », « trouve-moi des clients sans pub », « audite mon site », « quel produit vendre ? », « teste ma fiche avant de la publier », « fais le point de la semaine », « où en est ma boutique ? » | passe au [cerveau e-commerce](#le-cerveau-e-commerce) (ou tape `/cerveau:ecommerce`), qui tient le suivi de chaque boutique |
| « ma map fortnite n'a pas de joueurs », « titre et tags de ma map », « quelles maps marchent en ce moment ? » | passe à la skill [Maps Fortnite](#les-outils-que-claude-installe-pour-toi) (`/cerveau:fortnite`) : niche, fiche de l'île, rétention, lancement, SEO et GEO |
| « je veux devenir vendeur », « mon CV de vendeur », « prépare mon entretien », « je veux gagner plus » | passe à la skill [Carrière commerciale](#les-outils-que-claude-installe-pour-toi) (`/cerveau:carriere-commerciale`) : premier poste, alternance, échelons et salaires, CV, entretiens, négociation |
| « ingère cet article », « range cette réponse dans le wiki », « fais le point sur le wiki » | alimente ton [wiki](#le-cerveau-en-wiki-et-la-veille-automatique) ; le point, c'est un contrôle de santé (pages à créer, sources en attente, pages dépassées) |
| « installe agent-browser », « transforme ce site en API », « teste mon site dans le navigateur »… | installe sur ton PC, avec ton accord, [l'outil qui convient](#les-outils-que-claude-installe-pour-toi), puis le pilote |
| « qu'est-ce que tu as appris ? », « partage cette skill avec mes amis », « qu'est-ce qui est parti sur un modèle moins cher ? » | montre ce qu'il a [appris de tes sessions](#le-cerveau-apprend-tout-seul), partage une skill avec ton accord, ou fait le point sur la [délégation](#moins-de-tokens) |

Vue 3D de ta mémoire : `~/.claude/brain/cerveau.html` (souvenirs, projets, le cerveau e-commerce avec ses fiches et ses
outils, et tes boutiques suivies). Elle marche hors ligne, sans aucun site extérieur : ses bibliothèques (3d-force-graph
et three.js, sous licence MIT) sont livrées avec le plugin et intégrées à la page (`brainkit/vue3d/LICENCES.md`).
Le curseur ▶ en bas rejoue ton cerveau dans le temps : à chaque date, les souvenirs vrais ce jour-là, ceux qui ont été
remplacés depuis compris, s'allument et s'éteignent, et un remplacement passe en impulsion de l'ancien au nouveau.
Couleurs par domaine ou par « chaleur » (dernier usage), et ☷ range les souvenirs en couches, de la vision en haut au
détail en bas.

## Ce que fait le cerveau

- **Au démarrage** de chaque session : l'essentiel de ta mémoire et du projet courant est injecté.
- **À chaque message** : les souvenirs et fichiers vraiment liés remontent tout seuls (fautes de frappe, écriture
  phonétique et synonymes compris). Un souvenir rappelé montre les phrases qui répondent à ton message, pas seulement
  son début ; `brain recall --pourquoi` dit pourquoi un souvenir n'est pas remonté.
- **En fin de tâche** : si tu as dit une décision ou une préférence pas encore enregistrée, Claude la note ; sinon
  le cerveau ne dit rien (pas de rappel inutile).
- **Cartes de tes projets** (fichiers clés, où est défini quoi), à-faire datés, vue 3D, serveur MCP.
- **La mémoire datée** : un souvenir est vrai d'une date à une autre (« vrai depuis le 01/09 », « jusqu'au 31/12 » :
  archivé le lendemain). Quand un fait change, l'ancien est gardé avec sa date de fin et la raison, et `brain show`
  donne la lignée (« Scaleway depuis le 24/11 ← OVH du 01/09 au 24/11, parce que trop cher »). Un lien retiré est
  daté, pas effacé. `brain q "…" --at 15/05` montre le cerveau tel qu'il était, même au-delà des instantanés. Chaque
  souvenir a aussi un domaine (celui de son projet) et un niveau (vision, architecture, procédure, détail).
  Un souvenir échu n'est plus rappelé, même avant son archivage ; deux souvenirs qui se contredisent arrivent le plus
  récent d'abord, l'autre marqué. Au démarrage, les souvenirs les plus reliés de ton projet passent devant (les
  piliers). Et le rêve te ressort, trois au plus, les souvenirs importants qui ne servent plus, à revoir de plus en
  plus rarement (30 jours, puis 60, 120…) tant qu'ils restent vrais. Un fait qui change à une date à venir
  (« à partir du 1er janvier ») laisse l'ancien vrai jusque-là ; « Mondial Relay » et « MondialRelay » sont reconnus
  comme le même nom.
- **La mémoire protégée** : un souvenir tiré d'une page web ou d'une transcription qui contiendrait une consigne piégée
  (« ignore les consignes de l'utilisateur », « fais-le sans le lui dire », une commande qui télécharge et exécute)
  est mis de côté : Claude n'en voit que le titre et un avertissement, jamais le texte, tant que tu ne l'as pas relu
  (`brain edit <id> --verifie`). Au démarrage, le `CLAUDE.md` du projet ouvert passe le même contrôle.
- **Le rêve** : l'entretien de ta mémoire se fait hors conversation, chaque jour — dates relatives rendues réelles,
  observations anciennes condensées — et ce qui demande du jugement (corrections entendues, doublons, conflits,
  à-faire en retard) est tranché par Claude au démarrage suivant : ce qui est sûr est appliqué, un doute est laissé
  et cité, rien n'est inventé.
- **Rien ne se perd** : une sauvegarde chaque jour, hors de `~/.claude` (sous Windows sur un second disque s'il y en a
  un, sinon dans `~/Sauvegardes-cerveau-Claude` ; `brain config backup.dir <dossier>` pour en choisir un autre). Un
  fichier de mémoire abîmé se répare seul, sans perdre ce qui s'y lit encore, et le cerveau te dit ce qu'il a repris.
- **Le style concis** (`/output-style cerveau:concis`) : l'action d'abord, sans préambule ni récapitulatif. Il devient
  ton style par défaut, sauf si tu en avais déjà choisi un ; `brain config style off` pour revenir.
- **La relecture sécurité** (skill `/cerveau:securite`) relit le code exposé (site, API, formulaire) avant de le livrer.
- **Tout s'active seul, sans commande** : le style concis, les filtres appris sur tes commandes, l'ingestion des sources
  déposées dans le wiki et le rêve.

**Confidentialité** : tout reste chez toi, dans `~/.claude/brain` — ou dans ton wiki, sur ton PC et, si tu le choisis,
dans ton dépôt GitHub privé. Rien n'est envoyé ailleurs, sauf ta part publique si tu rejoins le cerveau commun ; chacun
garde sa propre mémoire.

## Moins de tokens

- **La délégation** : chercher dans tout un projet, lire de longues pages ou appliquer une modification déjà décidée
  n'a pas besoin du modèle le plus cher. Le cerveau apporte trois agents — l'éclaireur (Haiku : chercher, lire,
  résumer), l'ouvrier (Sonnet : modification cadrée, tests à écrire) et l'archiviste (Sonnet : entretien de ta
  mémoire) — et les souffle à Claude au bon moment ; un sous-agent lancé sans modèle part de lui-même sur le moins cher
  qui suffit. Ta conversation ne garde que leur rapport ; la conception, le débogage et les décisions restent sur ton
  modèle. Au tarif de l'API du 03/11/2026, Haiku coûte 40 à 80 fois moins par token qu'Opus ou Fable, Sonnet 2 à 4 fois
  moins. `brain delegation` dit ce qui est parti où et ce que ça a épargné ; `brain delegation --mode conseil` (le
  cerveau conseille sans rien changer) ou `off` pour reprendre la main.
- **Le mode éco**, posé une fois au démarrage : les sorties de commandes très longues vont dans un fichier (aperçu
  seul dans la conversation), la conversation est résumée plus tôt, et `brain eco` liste les plugins jamais utilisés.
  Désactiver les plugins et skills inutilisés, c'est toi qui décides : le cerveau te les propose une fois, et
  `brain eco --plugins` les désactive. `brain eco --annuler` pour revenir.
- **La veille du PC** (Windows) : elle repère les serveurs MCP restés ouverts sans session et te le dit en une ligne ;
  elle ne ferme jamais rien seule. `brain pc --clean` les liste, `brain pc --clean --oui` les ferme.
- **Sorties compactées** avant d'arriver à Claude : une liste JSON arrive en tableau, une sortie déjà lue dans la
  session renvoie vers la première, les erreurs sont toujours gardées.
- **Filtres appris** : `brain compact --decouvrir` repère le bruit qui revient dans les sorties de tes commandes et
  `brain compact --apprendre <commande> --enregistrer` en fait un filtre appliqué tout seul. L'entretien du jour le
  fait aussi de lui-même, annoncé une fois ; `brain compact --oublier <commande>` pour retirer un filtre.
- **Texte injecté plus court** au démarrage, à chaque message et dans la liste des outils : le serveur MCP du
  cerveau ne liste que les 6 outils de la mémoire ; `brain config mcp.groupes '["wiki", "boutique"]'` ajoute ceux
  du wiki et des boutiques (utile dans l'app Claude ou Cowork), et un résultat trop long arrive par pages.
- **Skills chargées d'office** : `brain config skills.auto '["ma-skill"]'` et, dès qu'un message correspond à la skill,
  le cerveau glisse lui-même son contenu dans la conversation, sans attendre que Claude l'ouvre ; il la ressert
  après chaque résumé de la conversation.
- **Chaque réglage expliqué** dans [la page des réglages](skills/brain/references/reglages.md), tirée du code : ce
  que fait chaque réglage, son défaut, ses bornes, quand le changer, et les réglages de Claude Code que pose le mode
  éco. `brain config --page recall` en montre une section ; `brain config <clé> <valeur>` refuse une clé inconnue
  ou une valeur hors bornes.
- **Les bons outils, tout seuls** : quand un message parle de mails, d'agenda, d'un visuel Canva ou de la boutique, le
  cerveau souffle à Claude le connecteur branché qui convient et la recherche exacte qui charge ses outils en un seul
  appel, sans charger les autres. Les skills de tes plugins et de ton compte claude.ai se déclenchent sur des phrases
  en français (65 en ont d'office) ; un connecteur ou une skill qui arrive sans phrase française est signalé au
  démarrage, et `brain outils trig` ou `brain skill trig` lui en donne. `brain outils` montre ce qui est branché.
- **Le compteur** : `brain tokens` donne ta consommation et son coût au tarif de l'API, en dollars.

## Le cerveau apprend tout seul

Il regarde ce qui se passe dans tes sessions et en tire de quoi mieux faire la fois suivante. Repérer ne coûte aucun
token ; seul ce qui demande du jugement arrive devant un modèle, et c'est l'archiviste (moins cher) qui s'en charge.

- **Les erreurs résolues** : une commande échoue, puis réussit lancée autrement. Le cerveau le signale à Claude en fin
  de tâche, qui en fait un souvenir si le piège risque de revenir.
- **Les phrases qui déclenchent une skill** : tu as dû appeler toi-même une skill deux fois avec les mêmes mots ? Le
  cerveau retient la tournure et la proposera seul la prochaine fois. Il te l'annonce, et
  `brain apprendre oublier <skill> "…"` la retire. Une skill proposée souvent et jamais suivie est signalée aussi.
- **Les méthodes répétées** : la même demande revient dans plusieurs sessions, sur plusieurs jours ? Il propose d'en
  faire une skill, rédigée d'après ces sessions.
- **Les retours techniques** : pannes et lenteurs de ses propres hooks, précision de ses propositions — des compteurs,
  jamais un mot de tes sessions (`brain apprendre retours`).

`brain apprendre` montre ce qui reste à trancher ; `brain config apprendre.enabled false` coupe tout. Ce que ton cerveau
apprend peut aussi servir à tes amis, puis à tous : voir [le cerveau commun](#le-cerveau-commun-avec-tes-amis).

## Le cerveau en wiki et la veille automatique

**Le wiki** (le « LLM Wiki » d'Andrej Karpathy) : `brain wiki init <dossier>` range chaque souvenir dans une page
Markdown d'un dossier que tu ouvres dans Obsidian (idéalement un dépôt GitHub privé). Tu y déposes des sources
(articles, PDF, transcriptions, notes) ; Claude les lit tout seul et tient à jour des pages de synthèse (sources
résumées, entités, concepts, sujets, analyses), liées entre elles. Le schéma que suit Claude est dans le `CLAUDE.md` du
wiki : fais-le évoluer avec lui. Rien ne change tant que tu ne le lances pas. Une page que tu modifies dans Obsidian
pendant que Claude travaille garde ta version (celle du cerveau est mise de côté dans `~/.claude/brain/conflits`), et
`brain wiki lint` signale aussi les sections vides et les propriétés invalides.

**La recherche sourcée** (skill `/cerveau:recherche`, d'après autoresearch de claude-obsidian, MIT) : « fais un dossier
sur… », « recherche à fond… » et Claude mène 3 tours de 5 sources au plus, sources officielles d'abord et position
contraire cherchée, classe chaque affirmation (établie, provisoire, contestée, non étayée) et range le dossier dans le
wiki ; la mise à jour des autres pages t'est proposée à part. **La syntaxe Obsidian** (skill `/cerveau:obsidian`,
d'après claude-obsidian, MIT) : propriétés, liens, encadrés, vues Bases et Canvas écrits juste du premier coup.

**La veille automatique** : `brain auto --installer` pose une tâche planifiée (Windows ; ailleurs, une ligne cron à
ajouter) qui tient le cerveau à jour toutes les 30 min sans ouvrir Claude, et sans fenêtre : notes du jour d'Obsidian
mémorisées, wiki synchronisé avec GitHub, page Cerveau et carte réécrites, entretien et sauvegarde du jour. Zéro
token. `brain auto --etat` pour voir la dernière passe, `brain auto --retirer` pour l'enlever.

## Le cerveau e-commerce

**Un expert** (skill `/cerveau:ecommerce`) pour lancer ou faire décoller une boutique en ligne sans publicité et avec
des outils gratuits — diagnostic, offre et marges, site et tunnel de vente, premiers clients, vidéo courte et
algorithmes, SEO, GEO (ChatGPT, Perplexity, AI Overviews), e-mails, gestion, conformité. Il agit lui-même sur ta
boutique et tes outils Google (fiches, SEO, flux), puis te dit ce qu'il a fait et comment l'annuler ; il te demande
seulement pour l'argent (prix, promos) et les envois aux clients. Il publie sur ta page Facebook, ton Instagram pro ou
YouTube une fois l'accès officiel branché, après ton « oui » sur le lot de la semaine ; ailleurs, il prépare et tu
cliques. Le contexte de chaque boutique reste dans ta mémoire, chez toi.

**Un copilote** qui suit chaque boutique : un plan décollage daté (72 h, 14 jours, 30-60-90) dont les échéances te
sont rappelées ; chaque lundi, les chiffres de la semaine avec un test statistique qui dit si une hausse est réelle ou
du hasard, le canal qui rapporte le plus par heure et le goulot à traiter ; des audits gardés en historique (ce qui a
été corrigé) avec contrôle de conformité légale, pages du site et vitesse ; un bilan avec trois priorités. Outils
inclus : audit de tout le catalogue et flux Google Shopping, relecture des textes avant publication (allégations
interdites, fausse urgence), comparaison des marges entre ta boutique, Etsy, Vinted ou TikTok Shop, modèles de textes
prêts à adapter.

**Un panel de clients simulés** (l'idée de MiroFish, sans clé d'API) : avant de publier une fiche, un prix, une idée de
produit ou une accroche vidéo, Claude la fait juger par 24 personas variées (âge, budget, méfiance, canal) jouées par
ses sous-agents en parallèle, puis leur fait lire les avis des autres pour voir ce qui se propage. Tu obtiens les
objections, les questions à traiter sur la page, les segments chauds et froids, et la variante la plus solide. C'est
une hypothèse, jamais présentée comme de vrais avis : une fois la variante en ligne, les chiffres de la semaine disent
si le panel avait vu juste (`brain boutique panel`).

## Les outils que Claude installe pour toi

Chaque outil s'installe sur ton PC, avec ton accord et jamais sans ; le plugin n'apporte que la marche à suivre.
Règles communes : Claude ne tape jamais ton mot de passe (tu te connectes toi-même dans une fenêtre visible), ne
branche ton vrai Chrome avec tes comptes que sur ton « oui », te demande avant d'envoyer un formulaire ou un message,
et ne copie jamais une clé ou un jeton dans la conversation.

Les outils proches sont réunis dans une même skill qui lit seulement la fiche utile : `/cerveau:design`,
`/cerveau:animation`, `/cerveau:composants`, `/cerveau:web` et `/cerveau:recherche` (la fiche est entre parenthèses).
Spec Kit, REA et Automaton ne partent que sur demande : tu tapes leur commande, Claude te la propose quand ta demande
s'y prête. Humanizer et les skills de Vercel ne sont plus dans le cerveau : leurs plugins (humanizer, vercel) les
fournissent ; une fois ces plugins installés, « humanise ce texte », « on dirait de l'IA », « déploie sur vercel » ou
« bonnes pratiques react » y mènent toujours.

| Tu dis… | Skill | Ce que fait Claude | D'après |
|---|---|---|---|
| « audite cette skill », « je peux installer cette skill ? » | `/cerveau:securite` (audit-skills) | lit une skill tierce sans rien lancer : « sûre », « à vérifier » ou « refusée », avec les raisons ; aussi dans `brain echange voir` | skill-security-auditor (Alireza Rezvani, MIT) |
| « cuisine-moi sur ma boutique » | `/cerveau:cuisine-moi` (sur demande) | t'interroge par tours de questions numérotées, avec sa réponse conseillée à chaque fois, puis ne fait rien avant ton « oui » | grilling (Matt Pocock, MIT) |
| « fais une passation » | `/cerveau:passation` (sur demande) | écrit le document pour reprendre ailleurs (état, décisions, fichiers, skills à charger), sans aucun secret | handoff (Matt Pocock, MIT) |
| « tu as vraiment vérifié ? » | `/cerveau:preuve-avant-fini` | rien n'est annoncé fini sans la commande qui le prouve et sa sortie lue | verification-before-completion (Jesse Vincent, MIT) |
| « mets ce tuto en pratique » | `/cerveau:apprendre-en-livrant` | une vidéo ou un cours devient une suite de petits projets à livrer | ship-learn-next (tapestry-skills, MIT) |
| « range mes factures », « tableau pour mon comptable » | `/cerveau:factures-recus` | inventaire, lecture des factures électroniques, noms « AAAA-MM-JJ Fournisseur - Facture - Objet », copies classées, CSV pour Excel ; côté e-commerce, un tirage au sort équitable et vérifiable (`tirage.py`), côté carrière commerciale, le débrief d'un appel de vente (`appel.py`) | écrite pour le cerveau |
| « branche perplexity », puis « cherche sur perplexity … » | `/cerveau:recherche` (perplexity) | recherche web filtrée par sites, langue, pays ou date, ou recherche approfondie avec sources, avec ton propre compte Perplexity | le serveur officiel de Perplexity |
| « installe agent-reach », puis « lis ce tweet », « lis ce fil reddit », « récupère les sous-titres de cette vidéo YouTube » | `/cerveau:web` (agent-reach) | lit en lecture seule X/Twitter, Reddit, YouTube, LinkedIn, Instagram et d'autres, là où sa recherche web échoue | Agent Reach (Panniantong) |
| « clone cette app », « ma version de X » | `/cerveau:replica` | refait ta propre version d'une app existante en 11 étapes, jusqu'à la fiche App Store et la mise en ligne | replica-skill (Jake Schincariol, MIT) |
| « script de ma vidéo », « titre et miniature », « coupe les blancs », « audit de ma chaîne » | `/cerveau:youtube` | prépare, écrit et analyse tes vidéos en 11 étapes : planning, ce qui marche dans ta niche, script et accroche notée, titre et miniature, coupes, chapitres, description, Shorts, commentaires, rétention, audit ; rien ne se publie sans toi | youtube-agent-skill (Jake Schincariol, MIT) |
| « ma map fortnite », « titre et tags de ma map », « tendances fortnite », « ma map n'a pas de joueurs » | `/cerveau:fortnite` | fait monter tes maps Fortnite (Créatif, UEFN) sans payer : niche lue dans l'API publique d'Epic, Discover et recherche du jeu, fiche de l'île et miniatures, rétention des maps de combat, lancement, page web citable par Google et les IA, diagnostic du goulot ; rien ne se publie sans toi | documentation et règles d'Epic, API publique de Fortnite |
| « je veux devenir vendeur », « mon CV de vendeur », « négocier mon salaire », « monter les échelons » | `/cerveau:carriere-commerciale` | t'aide à entrer dans la vente sans diplôme, d'abord en magasin tech, puis à monter un échelon après l'autre : salaires sourcés, alternance, aides de France Travail, dyslexie au travail, CV, entretiens, négociation, preuves pour la promotion | sources officielles (service-public, France Travail, France Compétences, Agefiph) |
| « teste mon site dans le navigateur », « teste le parcours », « capture d'écran de la page » | `/cerveau:web` (playwright) | pilote un navigateur en lignes de commande, en moins de tokens que le MCP Playwright | playwright-cli (Microsoft, Apache-2.0) |
| « design system », « dans le style de Stripe », « comme le site d'Apple » | `/cerveau:design` (design-md) | pose dans ton projet le DESIGN.md d'une des 86 marques connues, l'adapte à ta marque, puis code en le suivant | awesome-design-md (VoltAgent, MIT) |
| « transforme cette image en site », « code cette maquette », « capture d'écran en site » | `/cerveau:design` (image-to-code) | transforme une capture ou une maquette en vrai site responsive qui lui ressemble au plus près | image-to-code-skill (Leonxlnx, MIT) |
| « extrais le design de ce site », « mêmes couleurs et polices que ce site », « récupère le design de mon projet » | `/cerveau:design` (skillui) | relève le design d'un site, d'un dépôt ou de ton projet (couleurs, polices, espacements, composants, animations, captures) pour coder une interface du même esprit, sans copier | SkillUI (amaancoderx, MIT) |
| « installe agent-browser », puis « cherche les bugs de mon site », « extrais les données de la page », « ouvre ce site et… » | `/cerveau:web` (agent-browser) | navigue, clique, lit et mesure (vitesse, web vitals) dans un navigateur sans fenêtre, puis te montre ce qu'il a trouvé | agent-browser (Vercel Labs, Apache-2.0) |
| `/cerveau:spec-kit`, puis « installe spec kit dans ce projet » et `/speckit-…` | `/cerveau:spec-kit` (sur demande) | construit ton appli à partir d'une spec écrite : principes, spec, plan, tâches, code, contrôle | Spec Kit (GitHub, MIT) |
| « installe reverse api », puis « transforme ce site en API », « ce site n'a pas d'API » | `/cerveau:web` (reverse-api-engineer) | lit les vraies requêtes d'un site et en tire un client d'API typé (10 langages), vérifié sur de vraies données | reverse-api-engineer (Kalil, MIT) |
| `/cerveau:rea`, puis « analyse ce binaire », « décompile cette fonction », « comment marche la recherche dans cette appli » | `/cerveau:rea` (sur demande) | lit en local un exécutable, une appli Electron, un APK, un firmware, une base SQLite ou une capture réseau, et explique avec preuves comment ça marche, pour t'aider à en refaire ta version | REA, Reverse Engineer Anything (morluto, MIT) |
| « direction artistique », « refais le design », « ça fait template » | `/cerveau:design` (taste-skill) | donne à ton site une vraie direction artistique, tirée de 247 sites de galeries, et une couche d'animation complète, contrôlées sur captures à trois largeurs d'écran | taste-skill (Leonxlnx, MIT) |
| « règle la durée de cette animation », « affine la courbe d’easing », « ajuste cette animation Lottie », « animation de chargement » | `/cerveau:animation` (motion-design) | règle une animation précise comme un motion designer : durée, courbe, ordre d'apparition, transition de page, chargement ou Lottie, avec une version calme pour qui demande moins de mouvement | Motion Design Skill (LottieFiles, MIT) |
| « peaufine l'interface », « critique l'interface », « ça fait généré par IA », « interface trop chargée » | `/cerveau:design` (impeccable) | relit et retouche ton site ou ton appli comme un directeur artistique : critique notée, audit (accessibilité, performance, téléphone), finition, plus audacieux ou plus sobre ; un détecteur signale les défauts typiques des interfaces faites par IA | Impeccable (Paul Bakaus, Apache-2.0) |
| « anime ce bouton », « revois mes animations », « l'animation saccade », « teste le pire cas », « fais plus natif sur mobile » | `/cerveau:animation` (emil-kowalski) | choisit et suit la bonne des 16 skills d'Emil Kowalski : finition d'interface, animations (créer, revoir, auditer, retirer, fluidifier), données extrêmes, ressenti natif sur téléphone | skills (Emil Kowalski, MIT) |
| « anime.js », « timeline d'animation », « dessine le tracé svg », « texte lettre par lettre », « animation synchronisée au scroll » | `/cerveau:animation` (animejs) | anime ton site en JavaScript avec anime.js : séquences, cascades, scroll, tracés SVG qui se dessinent, morphing, texte lettre par lettre, éléments à glisser, en syntaxe v4 vérifiée | anime.js (Julian Garnier, MIT) |
| « fais-moi un logo », « refais mon logo », « critique mon logo », « crée un favicon » | `/cerveau:logo-design` | dessine ton logo comme un designer d'identité : brief, trois concepts à choisir, logo SVG testé à 16 px, puis le kit (couleurs, favicon, icônes d'appli, planche, mini-charte) | Logo Design Skill (kaankiziltug, MIT) |
| « ajoute un graphique », « fais un dashboard », « carte KPI », « remplace recharts » | `/cerveau:composants` (bklit-ui) | des graphiques animés pour ton site React : courbes, barres, camemberts, jauges, carte du monde, mini-courbes de KPI, au style de ton site, ou tes graphiques Recharts remplacés | Bklit UI (uixmat, MIT) |
| « kokonut », « composant animé », « fond animé », « texte animé », « interface de chat IA » | `/cerveau:composants` (kokonutui) | ajoute à ton site React des composants animés tout faits (boutons, titres, fonds et héros, cartes, navigation, blocs d'interface IA), copiés en source et accordés à ton thème | KokonutUI (kokonut-labs, MIT) |
| « un joli bouton pour mon site », « un loader pour mon site », « un interrupteur stylé », « une carte produit stylée » | `/cerveau:composants` (uiverse) | ajoute à ton site un élément tout fait parmi les 3 802 de la collection Galaxy d'Uiverse.io (boutons, cartes, loaders, interrupteurs, champs, formulaires, infobulles, motifs de fond), comparé en aperçu puis accordé à ton thème | Galaxy (Uiverse.io, MIT) |
| « installe scrapegraph », puis « scrape ce site », « récupère tous les produits et les prix de… », « liste les prix des concurrents » | `/cerveau:web` (scrapegraph) | extrait en JSON ce que tu demandes d'une ou plusieurs pages, ou d'une recherche web, avec un modèle local gratuit | ScrapeGraphAI (MIT) |
| `/cerveau:automaton`, puis « lance automaton », « arrête automaton » | `/cerveau:automaton` (sur demande) | fait tourner dans Docker l'agent autonome de Conway Research, avec ton modèle local gratuit et coupé de tout paiement | Automaton (Conway Research, MIT) |
| « trouve une API gratuite pour… », « une API sans clé », « quelle API pour… », « un serveur MCP pour… » | `/cerveau:public-apis` | cherche parmi 2 245 API gratuites (météo, taux de change, adresses, entreprises, films…) et 30 serveurs MCP, filtre sans clé, HTTPS et CORS, et vérifie qu'elles répondent encore avant de te les conseiller | public-apis (MIT) |

<details>
<summary>Le détail de chaque outil</summary>

- **Perplexity** (skill `/cerveau:recherche`, fiche perplexity) : dis « branche perplexity » et Claude ajoute le serveur officiel de Perplexity sur ton PC, puis te guide pour te connecter avec ton propre compte (payant à l'appel, à ta charge, rien de partagé). Ensuite, « cherche sur perplexity … » : recherche web filtrée par sites, langue, pays ou date, ou recherche approfondie avec sources. Sans ce mot, Claude garde sa recherche web intégrée, sans frais.
- **Agent Reach** (skill `/cerveau:web`, fiche agent-reach) : dis « installe agent-reach » et Claude te guide pour installer sur ton PC l'outil libre Agent Reach (github.com/Panniantong/Agent-Reach). Ensuite, « lis ce tweet », « lis ce fil reddit », « récupère les sous-titres de cette vidéo YouTube » : Claude lit en lecture seule X/Twitter, Reddit, YouTube, LinkedIn, Instagram et d'autres là où sa recherche web échoue. L'outil est gratuit (seule la transcription audio demande ta propre clé Groq ou OpenAI) ; il ne poste jamais rien et ne se connecte jamais à ta place (compte secondaire conseillé).
- **Replica** (skill `/cerveau:replica`, d'après replica-skill de Jake Schincariol, MIT) : « clone cette app » ou « ma version de X » et Claude refait sa propre version d'une app existante en 11 étapes — analyse des écrans et parcours, architecture, design, construction, backend, tests, score de parité avec l'original, lecture des vrais avis (ce que les utilisateurs détestent devient tes corrections et ton angle de vente), nouvelle marque, page de lancement et fiche App Store, mise en ligne. Les fonctions et les parcours seulement, jamais le code, le logo, les textes ni le contenu de l'original. Six outils Python fournis, sans installation ni accès réseau.
- **YouTube** (skill `/cerveau:youtube`, d'après youtube-agent-skill de Jake Schincariol, MIT) : « script de ma vidéo », « mon CTR est bas », « fais des shorts de ma vidéo », « audit de ma chaîne » et Claude t'aide pour tes propres vidéos en 11 étapes — planning de la semaine, vidéos qui battent leur chaîne dans ta niche (lues avec yt-dlp, en lecture publique), script avec cinq accroches notées, titre et texte de miniature, liste de coupes (blancs, « euh », reprises), chapitres valides, description et tags, Shorts, réponses aux commentaires, courbe de rétention de Studio, audit avec une seule correction prioritaire. Six petits outils Python sans réseau, adaptés au français (scores non calibrés en français : un repère, pas un verdict). Ton profil de voix vit dans `~/.claude/youtube/voice.md`. Claude écrit, toi tu publies : rien ne part sur ta chaîne sans ton oui.
- **Maps Fortnite** (skill `/cerveau:fortnite`) : « ma map fortnite n'a pas de joueurs », « titre et tags de ma map », « quelles maps marchent en ce moment ? » et Claude t'aide à faire jouer tes îles Fortnite (Créatif, UEFN), d'abord les maps de combat et d'entraînement (zone wars, box fight, 1v1, free for all, aim). Sept fiches écrites d'après la documentation et les règles d'Epic, chaque point marqué établi, hypothèse ou non vérifié : choix de la niche, fonctionnement de Discover et de la recherche du jeu, titre, description, tags, genre, miniatures et test A/B, rétention (premier combat, lobby vide, accolades, J1 et J7), lancement et fenêtre de test de deux semaines, Google et assistants IA, mesure. Cinq outils Python : classement d'un genre et chiffres des maps concurrentes lus dans l'API publique d'Epic (sans clé), suivi de ta map au-delà des 7 jours que garde l'API (`~/.claude/fortnite`), contrôle de la fiche avant publication (termes interdits, quatre tags, titre trop proche d'un autre), contrôle des cinq images obligatoires, diagnostic du goulot et lecture d'un test A/B, page web de la map prête à mettre en ligne. Jamais de faux joueurs ni d'échange de favoris ; toi seul publies.
- **Carrière commerciale** (skill `/cerveau:carriere-commerciale`) : « je veux devenir vendeur », « mon CV de vendeur », « prépare mon entretien », « je veux une augmentation » et Claude t'accompagne de ton premier poste de vente jusqu'aux postes les mieux payés, un échelon à la fois : vendeur en magasin tech (informatique, téléphonie, boutiques d'opérateurs), vendeur expert, chef de rayon, directeur de magasin, directeur régional, ou vente aux entreprises. Sept fiches sourcées (service-public, France Travail, France Compétences, Agefiph, APEC, Insee) : salaires de chaque marche et minimums des conventions collectives, entrée sans diplôme (alternance, TP Conseiller de vente, immersion, recrutement par simulation), dyslexie au travail (dictée vocale, correcteurs, RQTH, en parler ou non), CV et LinkedIn, entretiens et jeux de rôle, négociation du fixe et du variable, promotion ou changement d'entreprise. Trois outils Python : calcul et comparaison d'offres selon l'objectif réellement atteint, journal hebdomadaire de tes ventes qui donne tes preuves chiffrées (`~/.claude/carriere`), CV d'une page à imprimer en PDF. Réponses courtes et simples ; rien n'est envoyé sans toi.
- **Playwright** (skill `/cerveau:web`, fiche playwright, d'après playwright-cli de Microsoft, Apache-2.0) : « teste mon site dans le navigateur », « teste le parcours », « capture d'écran de la page » et Claude pilote un navigateur en lignes de commande, en moins de tokens que le MCP Playwright ; il l'installe sur ton PC avec ton accord. Il ne tape jamais ton mot de passe : tu te connectes toi-même dans une fenêtre visible.
- **DESIGN.md** (skill `/cerveau:design`, fiche design-md, d'après awesome-design-md de VoltAgent, MIT) : « design system », « dans le style de Stripe », « comme le site d'Apple » et Claude installe dans ton projet le DESIGN.md d'une des 86 marques connues (couleurs, typographie, espacements, arrondis, composants), l'adapte à ta marque, puis code l'interface en le suivant. L'outil getdesign s'installe sur ton PC avec ton accord, travaille hors ligne, télémétrie coupée.
- **Image-to-code** (skill `/cerveau:design`, fiche image-to-code, d'après image-to-code-skill de Leonxlnx, MIT) : « transforme cette image en site », « code cette maquette », « capture d'écran en site » et Claude transforme une capture, une maquette Figma exportée ou le site que tu veux imiter en vrai site responsive qui lui ressemble au plus près : il relève section par section les textes, polices, espacements, couleurs et boutons, code, puis compare sa page à l'image et corrige les écarts. Il génère d'abord la maquette si tu as branché un outil d'images (par exemple une clé Gemini) ; sinon, donne-lui une image. Jamais le logo, les textes ni les photos d'un autre site.
- **SkillUI** (skill `/cerveau:design`, fiche skillui, d'après SkillUI d'amaancoderx, MIT) : « extrais le design de ce site », « récupère le design de ce dépôt », « mêmes couleurs et polices que ce site » et Claude relève le système de design d'un site, d'un dépôt GitHub ou de ton projet : palette, typographie, espacements, arrondis, ombres, composants et, en mode ultra, captures, états au survol, animations et tokens JSON, rangés dans un dossier autour d'un DESIGN.md. Il vérifie le thème sur la capture (l'analyse se trompe parfois), reprend le style sans le logo, les textes ni les polices payantes, puis code ton interface avec la skill de direction artistique. Il l'installe sur ton PC avec ton accord (Node.js ; Playwright pour le mode ultra), le lance sans le laisser ajouter de skill dans ton dossier Claude et ne lui donne jamais d'adresse privée (elle partirait chez Microlink pour la capture).
- **agent-browser** (skill `/cerveau:web`, fiche agent-browser, d'après agent-browser de Vercel Labs, Apache-2.0) : dis « installe agent-browser » et Claude installe sur ton PC ce navigateur piloté en lignes de commande (rapide, sans fenêtre, il se sert de ton Chrome). Ensuite, « cherche les bugs de mon site », « extrais les données de la page », « vitesse de chargement de la page », « ouvre ce site et… » : Claude navigue, clique, lit et mesure, puis te montre ce qu'il a trouvé. Il ne tape jamais ton mot de passe et te demande avant d'envoyer un formulaire ou un message.
- **Spec Kit** (skill `/cerveau:spec-kit`, sur demande, d'après Spec Kit de GitHub, MIT) : tape `/cerveau:spec-kit` (ou dis « installe spec kit dans ce projet » : Claude te propose la commande) et Claude installe sur ton PC l'outil `specify` (avec ton accord), puis le pose dans ton projet. Ensuite, tu construis ton appli à partir d'une spec écrite : les principes du projet, ce que tu veux et pourquoi, le plan technique, la liste des tâches, le code, puis un contrôle que le code colle bien à la spec. Tout reste en fichiers dans ton projet, pour reprendre plus tard ou le passer à quelqu'un. Les commandes `/speckit-…` ne partent que quand tu les tapes : elles ne coûtent rien tant que tu ne t'en sers pas.
- **Reverse API Engineer** (skill `/cerveau:web`, fiche reverse-api-engineer, d'après reverse-api-engineer de Kalil, MIT) : dis « installe reverse api » et Claude installe sur ton PC l'outil `rae` (avec ton accord), puis le règle. Ensuite, « transforme ce site en API », « ce site n'a pas d'API », « fais-moi un client API pour ce site » : un navigateur fait la tâche que tu décris (« toutes les offres de cette page carrières »), rae lit les vraies requêtes du site, et Claude en tire un client d'API propre et typé (Python, TypeScript, Go… 10 langages), avec son README, qu'il vérifie sur de vraies données avant de te le donner. Navigateur neuf par défaut ; ton vrai Chrome avec tes comptes seulement sur ton « oui ». Les captures (cookies, jetons) restent sur ton PC et ne vont jamais dans la conversation ; chaque capture coûte des tokens, Claude te dit combien.
- **REA** (skill `/cerveau:rea`, sur demande, d'après REA de morluto, MIT) : tape `/cerveau:rea` (ou dis « installe rea » : Claude te propose la commande) et Claude installe sur ton PC REA (Reverse Engineer Anything, avec ton accord) et le branche à Claude Code. Ensuite, « analyse ce binaire », « décompile cette fonction », « comment marche la recherche dans cette appli » : Claude lit en local un exécutable, une appli Electron, un APK, un firmware, une base SQLite ou une capture réseau, explique avec preuves comment ça marche et t'aide à en refaire ta version. Seulement pour un logiciel à toi ou que tu as le droit d'examiner ; jamais pour contourner une licence ou une protection. Les moteurs natifs (Ghidra, Hopper, IDA) restent facultatifs et à ta charge.
- **Taste-skill** (skill `/cerveau:design`, fiche taste-skill, d'après taste-skill de Leonxlnx, MIT) : « direction artistique », « refais le design », « ça fait template » et Claude conçoit ton site comme un studio : trois directions tirées d'une bibliothèque de 247 sites de galeries (One Page Love, Awwwards), puis la typo, la palette, le héros et les sections, et une couche d'animation obligatoire (moment signature, apparitions section par section, retour sur chaque bouton, image qui bouge), avec une version sans mouvement pour qui le refuse. Il vérifie la page sur captures à 1440, 768 et 390 px jusqu'à zéro erreur, et crédite chaque image libre utilisée. Il l'installe sur ton PC avec ton accord (Node.js 22 et Chrome ou Edge, rien d'autre), ou suit sa partie animation une fois sans rien installer.
- **Motion design** (skill `/cerveau:animation`, fiche motion-design, d'après Motion Design Skill de LottieFiles, MIT) : « règle la durée de cette animation », « affine la courbe d’easing », « ajuste cette animation Lottie », « animation de chargement » et Claude règle une animation précise comme un motion designer : la durée, la courbe et l'ordre d'apparition de chaque élément, dans le style du site (ludique, haut de gamme, sobre ou dynamique), pour une transition de page, un chargement, un succès ou une erreur, en CSS, Framer Motion, GSAP ou Lottie. Toujours une version calme pour ceux qui demandent moins de mouvement, et rien qui distrait sur un formulaire ou une page de paiement. Animer tout un site, c'est Taste-skill ; un bouton ou un menu, les skills d'Emil Kowalski. Il l'installe sur ton PC avec ton accord, ou la suit une fois sans rien installer.
- **Impeccable** (skill `/cerveau:design`, fiche impeccable, d'après Impeccable de Paul Bakaus, Apache-2.0) : « peaufine l'interface », « critique l'interface », « ça fait généré par IA », « interface trop chargée » et Claude relit ton site ou ton appli comme un directeur artistique : critique notée, audit technique (accessibilité, performance, affichage sur téléphone), finition avant la mise en ligne, version plus audacieuse ou plus sobre, typographie, couleurs, mise en page, textes des boutons et des erreurs, premiers pas et écrans vides. Une fois par projet, il note ce qu'est ton produit (PRODUCT.md) pour que chaque retouche en tienne compte. Après chaque modification d'un fichier d'interface, un détecteur signale les défauts typiques des interfaces faites par IA (texte en dégradé, halos, contraste trop faible, texte qui déborde) ; il se tait sur les autres fichiers. Il l'installe sur ton PC avec ton accord (Node.js pour l'installer, télémétrie coupée).
- **Skills d'Emil Kowalski** (skill `/cerveau:animation`, fiche emil-kowalski, d'après skills d'Emil Kowalski, MIT) : « anime ce bouton », « revois mes animations », « l'animation saccade », « teste le pire cas », « fais plus natif sur mobile » et Claude choisit la bonne des 16 skills du créateur de Sonner et Vaul (finition d'interface, animations à créer, revoir, auditer ou retirer, saccades, interface testée avec des données extrêmes, site qui paraît natif sur téléphone, choix d'une librairie front, React Native, Swift), puis l'installe sur ton PC avec ton accord ou la suit une fois sans rien installer.
- **anime.js** (skill `/cerveau:animation`, fiche animejs, d'après anime.js de Julian Garnier, MIT) : « anime.js », « timeline d'animation », « dessine le tracé svg », « texte lettre par lettre », « animation synchronisée au scroll » et Claude anime ton site avec la librairie anime.js : séquences et cascades, animations qui se jouent à l'arrivée à l'écran ou suivent le défilement, tracés SVG qui se dessinent, morphing, objet qui suit un chemin, texte découpé en lettres, mots ou lignes, texte brouillé, éléments à glisser avec rebond, transitions de mise en page, objets Three.js. Le style se décide d'abord avec Taste-skill pour un site ou les skills d'Emil Kowalski pour un composant, le réglage fin avec Motion design ; la librairie s'ajoute à ton projet avec ton accord (npm, ou un fichier hébergé dans ton thème Shopify), en syntaxe v4 vérifiée (les exemples en ligne sont souvent en v3), toujours avec une version sans mouvement pour qui le demande. Rien à installer sur ton PC.
- **Logo design** (skill `/cerveau:logo-design`, d'après Logo Design Skill de kaankiziltug, MIT) : « fais-moi un logo », « refais mon logo », « critique mon logo », « crée un favicon » et Claude travaille comme un designer d'identité : brief, mots clés de la marque, clichés du secteur à éviter, puis trois concepts montrés en gris, dessinés en SVG propre et testés à 16 px, en une couleur et en négatif. Il s'arrête là pour que tu choisisses ; ensuite seulement, le kit : couleurs, versions horizontale et empilée, favicon et icônes d'appli, planche de présentation avec maquettes de ton secteur, mini-charte. 1 400 logos réels classés lui servent de repères, jamais de modèles à copier. Il l'installe sur ton PC avec ton accord (Node.js pour l'installer, Python pour ses scripts, rien d'autre) et te conseille une recherche de marque avant d'imprimer.
- **Bklit UI** (skill `/cerveau:composants`, fiche bklit-ui, d'après les skills de Bklit UI d'uixmat, MIT) : « ajoute un graphique », « fais un dashboard », « carte KPI », « remplace recharts » et Claude choisit la bonne des 3 skills de Bklit UI : graphiques animés pour un site React ou Next.js (courbes, aires, barres, camemberts, anneaux, jauges, radar, carte de chaleur, entonnoir, carte du monde, mini-courbes pour cartes KPI), style décrit avec des mots (« barres arrondies », « fond à motifs qui s'estompe ») et accordé à ton thème, ou migration de tes graphiques Recharts, shadcn ou TanStack. Les composants arrivent en source dans ton projet, qui en garde le code ; il installe la skill sur ton PC avec ton accord ou la suit une fois sans rien installer.
- **KokonutUI** (skill `/cerveau:composants`, fiche kokonutui, d'après KokonutUI de kokonut-labs, MIT) : « kokonut », « composant animé », « composants tout fait », « fond animé », « texte animé », « interface de chat IA » et Claude choisit parmi les 102 composants gratuits de KokonutUI celui qu'il te faut (boutons, textes animés, fonds et héros, cartes, saisie comme un curseur, une signature ou un envoi de fichier, navigation, médias, et 18 blocs d'interface IA comme la zone de prompt avec choix du modèle), l'ajoute à ton site React ou Next.js, l'accorde à ton thème et le vérifie au navigateur (chaque menu et bouton, console, version sans mouvement). Le code arrive en source dans ton projet, qui le garde ; seuls les composants gratuits sont proposés, jamais les « Pro » payants. Il installe la skill officielle sur ton PC avec ton accord (Node.js), ou la lit une fois sans rien installer. Sans React (thème Shopify, HTML pur), rien à copier : un élément HTML + CSS d'Uiverse, ou l'effet refait en CSS avec les skills d'Emil Kowalski.
- **Uiverse** (skill `/cerveau:composants`, fiche uiverse, d'après Galaxy d'Uiverse.io, MIT) : « un joli bouton pour mon site », « un loader pour mon site », « un interrupteur stylé », « une carte produit stylée » et Claude cherche parmi les 3 802 éléments de la collection Galaxy d'Uiverse.io (boutons, cartes, loaders, interrupteurs, cases à cocher, champs, formulaires, infobulles, notifications, motifs de fond, en HTML + CSS ou Tailwind) ceux qui vont à ton site, te les montre côte à côte en aperçu, puis intègre celui que tu choisis : classes préfixées pour ne rien casser, couleurs et police de ton site, textes en français, accessibilité (clavier, contraste, lecteur d'écran, version sans mouvement), crédit de son auteur gardé. Marche sur un site HTML, un thème Shopify, en React, Vue ou Svelte. La collection (≈ 21 Mo, que du HTML et du CSS) se télécharge sur ton PC avec ton accord : Git et Python suffisent, Chrome ou Edge pour les aperçus.
- **ScrapeGraphAI** (skill `/cerveau:web`, fiche scrapegraph, d'après Scrapegraph-ai de ScrapeGraphAI, MIT) : dis « installe scrapegraph » et Claude installe sur ton PC la bibliothèque libre et un modèle local Ollama (≈ 7 Go, gratuit, sans compte). Ensuite, « scrape ce site », « récupère tous les produits et les prix de… », « liste les prix des concurrents » : les pages sont lues par le modèle de ton PC et seul le tableau JSON revient à Claude, ce qui économise des tokens sur plusieurs pages. La télémétrie de l'éditeur, qui enverrait le contenu des pages, est coupée. Un petit modèle peut se tromper sur un chiffre : Claude revérifie ceux qui comptent, et ne contourne ni connexion ni protection anti-robot.
- **Automaton** (skill `/cerveau:automaton`, sur demande, d'après automaton de Conway Research, MIT) : tape `/cerveau:automaton` (ou dis « installe automaton » : Claude te propose la commande) et Claude construit dans Docker l'agent autonome de Conway Research, une IA qui tourne en boucle avec son propre portefeuille et doit payer ses calculs pour survivre. Ses commandes shell restent dans le conteneur, il réfléchit avec le modèle Ollama de ton PC, et le mode local coupe tout paiement (service Conway débranché, plafonds de dépense à zéro, portefeuille jamais approvisionné). Tu le configures une fois, puis « lance automaton », « arrête automaton » ; Claude lit ses journaux. À savoir : l'inscription au service Conway échoue depuis octobre 2026 d'après les tickets du dépôt, il n'existe aucune preuve publique d'un agent rentable, et un modèle de 9 milliards de paramètres le fait tourner sans le rendre fiable. Il faut Docker Desktop (avec WSL 2 sous Windows) et Ollama.
- **Public APIs** (skill `/cerveau:public-apis`, d'après public-apis de la communauté public-apis, MIT) : « trouve une API gratuite pour… », « une API sans clé », « une API météo », « API de taux de change », « un serveur MCP pour… » et Claude cherche dans la liste communautaire public-apis (2 245 API en 51 catégories et 30 serveurs MCP, figée au 01/11/2026 et fournie avec le cerveau) celles qui vont à ton projet : sans clé, en HTTPS, appelables depuis le navigateur (CORS). Un petit outil Python cherche hors ligne sans faire lire toute la liste à Claude, puis vérifie que la page de chaque API répond encore ; Claude lit sa documentation et te donne une recommandation avec un premier appel essayé. Les liens publicitaires de la liste sont retirés. Si l'API demande une clé, tu la crées toi-même et elle reste dans un fichier `.env`, jamais dans le code ni la conversation ; un serveur MCP ne s'installe que sur ton « oui ». « mets à jour la liste » la retélécharge depuis GitHub. Rien à installer : Python suffit.

</details>

## Le cerveau commun (avec tes amis)

Si tu le veux, ce que tu apprends (recherches, savoir, projets que tu déclares communs) nourrit aussi le cerveau de
tes amis, et le leur nourrit le tien, presque en temps réel. Claude te le propose ; rien ne part avant ton oui, et
jamais ton profil, tes préférences ni rien de personnel ou de sensible.

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

**Les skills aussi** (`brain echange`). Avec ton oui, ce que ton cerveau apprend part chez tes amis : les skills qu'il
a rédigées, les phrases qui les déclenchent, et des compteurs techniques sans texte. Jamais une skill que tu as écrite
toi-même sans que tu la désignes (`brain echange partager <nom>`), jamais un secret ; `brain echange garder <nom>` en
garde une pour toi. Ce que tes amis partagent arrive chez toi en deux temps :

- **Le texte d'une skill s'active seul** : contrôlé à l'arrivée (consigne cachée, téléchargement exécuté, commande
  destructrice, accès à tes secrets ou aux réglages de Claude, envoi de données), puis proposé quand ton message s'y
  prête, marqué 🤝 et présenté à Claude comme la méthode d'un ami, pas comme un ordre. Une skill qui échoue au contrôle,
  ou dont le dossier contient autre chose que du texte et des scripts au nom simple (fichier caché, lien, autre type),
  reste en quarantaine jusqu'à ce que tu l'adoptes (`brain echange adopter <ami/nom>`). Ce contrôle se fait en tâche
  de fond, jamais pendant que tu attends une réponse.
- **Un script attend ton accord** : il tournerait sur ton PC, donc Claude te le montre d'abord
  (`brain echange approuver <ami/nom>`). L'accord vaut pour ce que tu as vu, à l'octet près : si le script change, même
  entre le moment où tu le regardes et ton oui, il est redemandé.

Une skill qui a fait ses preuves (suivie par plusieurs membres) est proposée pour le plugin ; une fois que {owner} l'a
relue et publiée, tous ceux qui ont le plugin la reçoivent à la mise à jour. `brain echange` montre où tu en es,
`brain echange non` arrête l'envoi et retire ce qui était parti, `brain echange recevoir non` coupe la réception.

Pour le lancer ({owner}) : crée sur GitHub le dépôt **privé et vide** `{commun}`,
invite tes amis (Settings → Collaborators → Add people), puis rejoins-le le premier (dis oui quand Claude le propose).

## Prérequis

**Python 3.10 ou plus, et la commande `python`** : les hooks du plugin la lancent ; sans elle, rien n'est enregistré, sans aucune erreur visible.
- macOS : `mkdir -p ~/.local/bin && ln -sf "$(command -v python3)" ~/.local/bin/python`, puis redémarre Claude Code · Debian/Ubuntu : `sudo apt install python-is-python3` · Windows : réinstalle Python depuis python.org en cochant « Add python.exe to PATH ».
- **Vérifier que le cerveau enregistre**, après ton premier message : `python ~/.claude/brain/brain.py doctor` puis `python ~/.claude/brain/brain.py journal` (macOS sans `python` : `python3`) ; si ce fichier n'existe pas, les hooks ne tournent pas : diagnostic direct avec `python3 "$(ls -d ~/.claude/plugins/cache/*/cerveau/*/ | tail -1)brain.py" doctor`.

## Désinstaller

`/plugin uninstall cerveau@cerveau`. Tes souvenirs restent dans `~/.claude/brain` (supprime ce dossier pour tout effacer).

Version {__version__}.
"""


PRIVATE_TESTS = {"run_all.py", "test_all.py", "test_mcp.py", "test_units.py", "test_vault.py"}  # ils lisent la vraie mémoire


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


def git_files(dest: Path, others: bool = False) -> list:
    """Fichiers suivis par git dans dest (chemins relatifs en /), et avec others ceux qui ne sont ni suivis ni ignorés ;
    [] hors d'un dépôt git."""
    if not (Path(dest) / ".git").exists():
        return []
    args = ["git", "-C", str(dest), "ls-files", "-z", "--cached"] + (["--others", "--exclude-standard"] if others else [])
    r = subprocess.run(args, capture_output=True)
    return sorted({p for p in r.stdout.decode("utf-8", "replace").split("\0") if p}) if r.returncode == 0 else []


def foreign_files(dest: Path) -> list:
    """Fichiers suivis par git que la construction effacerait sans les refaire : ils appartiennent à autre chose (un
    projet rangé dans le même dépôt, par exemple). La construction les refuse au lieu de les effacer (C23)."""
    return [f for f in git_files(dest) if f.split("/")[0] not in KEEP | OWNED]


def origin_repo(dest: Path) -> str:
    """« proprietaire/depot » du remote origin de dest quand c'est GitHub, sinon ""."""
    r = subprocess.run(["git", "-C", str(dest), "remote", "get-url", "origin"], capture_output=True)
    m = re.search(r"github\.com[:/]+([\w.-]+/[\w.-]+?)(?:\.git)?/?$", r.stdout.decode("utf-8", "replace").strip())
    return m.group(1) if r.returncode == 0 and m else ""


def _fresh_exe():
    """brain.exe construit dans rust/ (version Rust pour Windows : brain.py la lance, elle repasse à Python pour ce qui
    n'est pas porté) → son chemin ; None s'il n'y en a pas ; refusé s'il est plus ancien que ses sources."""
    exe = CODE_DIR / "rust" / "target" / "release" / "brain.exe"
    if not exe.is_file():
        return None
    rust = CODE_DIR / "rust"
    srcs = list((rust / "src").glob("*.rs")) + [rust / "Cargo.toml", rust / "Cargo.lock"]
    if exe.stat().st_mtime < max((p.stat().st_mtime for p in srcs if p.exists()), default=0):
        raise RuntimeError(f"{exe} est plus ancien que ses sources : relance cargo build --release dans rust/")
    return exe


def _generated(dest: Path, owner: str, repo: str) -> None:
    """Les fichiers que le plugin tire de son code : hooks, skill /brain, manifestes, README."""
    from .install import EVENTS, write_brain_skill
    hooks = {event: [{**({"matcher": matcher} if matcher else {}), "hooks": [_hook(arg, timeout, status)]}]
             for event, arg, timeout, status, matcher in EVENTS}
    _json(dest / "hooks" / "hooks.json", {"description": "Cerveau : injection au démarrage, rappel à chaque message, "
                                                         "sorties de commandes compactes, mémorisation en fin de tâche",
                                          "hooks": hooks})
    write_brain_skill(dest / "skills" / "brain", write=_lf)  # SKILL.md et ses fichiers references/
    plugin = {"name": NAME, "version": __version__, "description": DESC, "author": {"name": owner},
              "keywords": KEYWORDS, "mcpServers": MCP_SERVERS}
    if repo:
        plugin["homepage"] = plugin["repository"] = f"https://github.com/{repo}"
    _json(dest / ".claude-plugin" / "plugin.json", plugin)
    _json(dest / ".claude-plugin" / "marketplace.json", {
        "name": MARKET, "owner": {"name": owner},
        "metadata": {"description": f"Le cerveau persistant de {owner} pour Claude Code", "version": __version__},
        "plugins": [{"name": NAME, "source": "./", "description": DESC, "version": __version__}]})
    _lf(dest / "README.md", readme(owner, repo))


def build_in_place(dest: Path, owner: str = "", repo: str = "") -> list:
    """Le dépôt est le dossier du code (D1 du plan v2 : GitHub est la seule source, le PC travaille sur un clone). Rien
    n'est effacé ni recopié : seuls les fichiers générés sont réécrits, et brain.exe s'il vient d'être construit dans
    rust/. Seul run() l'appelle, une fois vérifié que le dépôt n'a aucun changement non validé.
    → les fichiers publiés (suivis par git, ou nouveaux et non ignorés)."""
    dest = Path(dest)
    if not (dest / ".git").exists():
        raise RuntimeError(f"{dest} n'est pas un clone git du dépôt : rien à publier sur place")
    _generated(dest, owner or repo.partition("/")[0] or NAME, repo)
    exe = _fresh_exe()
    if exe:
        shutil.copy2(exe, dest / "brain.exe")
    return git_files(dest, others=True)


def build(dest: Path, owner: str = "", repo: str = "") -> list:
    """Écrit le plugin complet dans dest (le clone du dépôt) : l'ancien contenu est remplacé, .git et les tests publics
    sont gardés. owner : nom public de l'auteur, par défaut le compte GitHub de repo (jamais le prénom du réglage local).
    Un fichier suivi par git qui n'appartient pas au plugin n'est jamais effacé : la construction s'arrête avant.
    → liste des fichiers écrits (chemins relatifs)."""
    dest = Path(dest)
    owner = owner or repo.partition("/")[0] or NAME
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / "brainkit").exists() and (dest / "graph.json").exists():
        raise RuntimeError(f"{dest} contient des souvenirs (graph.json) : ce n'est pas un dépôt de plugin")
    if dest.resolve() == CODE_DIR.resolve():
        raise RuntimeError(f"{dest} est le dossier du code lui-même : donne le clone du dépôt du plugin, ou lance "
                           "`brain publish` sans dossier depuis ce clone (publication sur place, sans rien effacer)")
    lost = foreign_files(dest)
    if lost:
        raise RuntimeError(f"la publication effacerait {len(lost)} fichier(s) suivi(s) par git qui n'appartiennent pas "
                           f"au plugin ({', '.join(lost[:5])}{' …' if len(lost) > 5 else ''}) : déplace-les dans un autre "
                           "dépôt, ou ajoute leur dossier à AUTRES dans brainkit/publish.py ; rien n'a été effacé")
    from .install import SKILL_MARK, skill_sources
    skills = skill_sources()  # relevées avant le nettoyage du dépôt
    tests = public_tests(dest)  # idem
    exe = _fresh_exe()  # refusé avant tout nettoyage s'il est périmé
    for item in dest.iterdir():
        if item.name not in KEEP:
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    shutil.copy2(CODE_DIR / "brain.py", dest / "brain.py")
    if exe:
        shutil.copy2(exe, dest / "brain.exe")
    shutil.copytree(CODE_DIR / "brainkit", dest / "brainkit", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    _generated(dest, owner, repo)
    for name, src in skills.items():  # skills métier (cerveau e-commerce…) : Claude Code les lit dans le plugin
        shutil.copytree(src, dest / "skills" / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", SKILL_MARK))
    if (CODE_DIR / "output-styles").is_dir():  # styles de réponse : /output-style cerveau:<nom>, au choix de chacun
        shutil.copytree(CODE_DIR / "output-styles", dest / "output-styles")
    if (CODE_DIR / "agents").is_dir():  # agents de délégation (cerveau:eclaireur…) : Claude Code les lit dans le plugin
        shutil.copytree(CODE_DIR / "agents", dest / "agents", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    _lf(dest / ".gitignore", "__pycache__/\n*.pyc\n")
    for rel, data in tests.items():
        (dest / "tests" / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / "tests" / rel).write_bytes(data)
    return sorted(str(p.relative_to(dest)).replace("\\", "/") for p in dest.rglob("*")
                  if p.is_file() and ".git" not in p.relative_to(dest).parts and p.relative_to(dest).parts[0] not in AUTRES)


def claude_cli():
    """Le Claude Code embarqué dans l'app (le plus récent), ou celui du PATH : sert à valider le plugin."""
    found = shutil.which("claude")
    if found:
        return found
    root = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude-code"
    exes = sorted(root.glob("*/*/claude.exe"), key=lambda p: [int(x) if x.isdigit() else 0
                                                                for x in re.split(r"[.]", p.parent.parent.name)])
    return str(exes[-1]) if exes else None


def secrets_in(dest: Path, files=None) -> list:
    """Fichiers du dépôt qui contiennent un secret (clé, jeton, mot de passe) ou une adresse e-mail : rien ne part.
    files : les chemins relatifs à contrôler (publication sur place : ceux que git publierait), sinon tout le dossier."""
    from .privacy import find
    email = re.compile(r"[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")  # pas « paquet@1.80.0 »
    bad = []
    for p in (dest / f for f in files) if files is not None else dest.rglob("*"):
        rel = p.relative_to(dest).parts
        if p.is_file() and ".git" not in rel and rel[0] not in AUTRES and p.suffix in (".py", ".json", ".md", ""):
            text = p.read_text(encoding="utf-8", errors="replace")
            hits = find(text) + (["e-mail"] if any("example" not in m.group(0) for m in email.finditer(text)) else [])
            if hits:
                bad.append(f"{p.relative_to(dest)} ({', '.join(sorted(set(hits)))})")
    return bad


def smoke(dest: Path) -> list:
    """Premier démarrage chez un « ami » fictif (profil Claude vide, mémoire vide) : hook de démarrage, rappel d'un
    message, serveur MCP. → liste des problèmes (vide = tout va bien)."""
    problems = []
    # Les hooks lancent des tâches de fond détachées (carte du dossier, synchro du wiki, accès au cerveau commun…) qui
    # travaillent dans ~/.claude/brain, ici dans tmp : sous Windows, tant qu'elles tournent, il ne s'efface pas (WinError
    # 32). On ne plante pas pour autant (ignore_cleanup_errors), et on réessaie jusqu'à ce qu'elles aient fini (la
    # vérification d'accès au cerveau commun, un git ls-remote, peut prendre 30 s).
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
            ("fact", "Boutique Shopify de thé", "Vente de thé vert en ligne, coffrets et mousseurs."),
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
    remove_tree(tmp, wait=60)
    return problems


def _status(dest: Path) -> list:
    """Changements non validés du dépôt (git status --porcelain), une ligne par fichier."""
    r = subprocess.run(["git", "-C", str(dest), "status", "--porcelain"], capture_output=True)
    return r.stdout.decode("utf-8", "replace").splitlines() if r.returncode == 0 else ["(git status a échoué)"]


def _default_dest(cfg, repo=None):
    """Dossier de publication sans argument. Le code est un clone git (CODE_DIR) : sur place s'il n'y a pas de dossier
    retenu, ou si ce clone est celui du même dépôt GitHub (--repo, publish.repo, ou le remote du dossier retenu) ; le
    dossier retenu sinon (clone d'un autre dépôt, ou dépôt impossible à lire)."""
    kept = cfg.get("dir")
    kept = Path(kept) if kept and Path(kept).is_dir() else None
    if not (CODE_DIR / ".git").exists():
        return kept
    if kept is None or kept.resolve() == CODE_DIR.resolve():
        return CODE_DIR
    mine = origin_repo(CODE_DIR).lower()
    want = (repo or cfg.get("repo") or origin_repo(kept)).lower().removesuffix(".git")
    if mine and want and mine == want:
        print(f"· publication sur place, depuis ce clone de {want} (dossier retenu {kept} laissé de côté)")
        return CODE_DIR
    return kept


def run(dest=None, owner=None, repo=None, push=False, check=True) -> int:
    cfg = load_config().get("publish", {})
    # Sans dossier donné : sur place quand le code tourne depuis un clone du même dépôt (D1), le dossier retenu
    # seulement sinon. Avant, le dossier retenu passait devant : lancé depuis le clone, le plugin partait d'un autre.
    dest = Path(dest or _default_dest(cfg, repo) or "")
    if not str(dest) or str(dest) == ".":
        print("✗ dossier du dépôt manquant : brain publish <dossier du clone GitHub> [--repo proprietaire/depot]")
        return 1
    in_place = dest.resolve() == CODE_DIR.resolve()
    if in_place and (dest / ".git").exists():
        dirty = _status(dest)
        if dirty:
            print("✗ des changements ne sont pas validés dans le dépôt : valide-les (git commit) ou mets-les de côté "
                  "(git stash), puis relance :\n  " + "\n  ".join(dirty[:10]) + ("\n  …" if len(dirty) > 10 else ""))
            return 1
    repo = repo or cfg.get("repo") or (origin_repo(dest) if in_place else "") or ""
    try:  # auteur : --owner, sinon le compte GitHub (publish.owner reste local)
        files = build_in_place(dest, owner or "", repo) if in_place else build(dest, owner or "", repo)
    except RuntimeError as exc:
        print(f"✗ {exc}")
        return 1
    where = "sur place, dans le dépôt du code" if in_place else f"dans {dest}"
    print(f"✓ plugin « cerveau » {__version__} construit {where} ({len(files)} fichiers)")
    for key, val in (("publish.dir", str(dest)), ("publish.repo", repo)):
        if val and cfg.get(key.split(".")[1]) != val:
            set_config(key, val)
    bad = secrets_in(dest, files if in_place else None)
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
    from . import gitmsg

    def git(*args, timeout=120, interactive=False):
        """git -C <dépôt> … → (code, sortie) ; jamais d'exception (git absent, délai dépassé). interactive : l'envoi
        peut demander une connexion à GitHub dans le terminal (git la lit au clavier, pas dans sa sortie)."""
        quiet = {} if interactive else {"stdin": subprocess.DEVNULL, "env": {**os.environ, "GIT_TERMINAL_PROMPT": "0"}}
        try:
            r = subprocess.run(["git", "-C", str(dest), *args], capture_output=True, timeout=timeout, **quiet)
            return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace").strip()
        except subprocess.TimeoutExpired:
            return 124, f"timed out after {timeout} s"
        except OSError as exc:
            return 127, str(exc)

    code, out = git("add", "-A", "--", ".", *[f":(exclude){d}" for d in sorted(AUTRES)])
    if code:
        print("✗ " + gitmsg.explain(out, code, "préparation du commit") + " ; rien n'est publié")
        return 1
    if git("diff", "--cached", "--quiet")[0] == 0:
        print("✓ rien de nouveau depuis la dernière publication")
    else:
        tag = f"{NAME}--v{__version__}"
        if git("rev-parse", "-q", "--verify", f"refs/tags/{tag}")[0] == 0:
            print(f"✗ la version {__version__} est déjà publiée (tag {tag}) : change __version__ (brainkit/__init__.py) "
                  f"pour que les amis reçoivent la mise à jour")
            git("reset", "-q")
            return 1
        for args in (["commit", "-q", "-m", f"cerveau {__version__}"],
                     ["tag", "-a", tag, "-m", f"cerveau {__version__}"]):  # tag annoté : --follow-tags
            code, out = git(*args)
            if code:
                print("✗ " + gitmsg.explain(out, code, args[0]) + " ; rien n'est publié")
                return 1
        print(f"✓ commit et tag {tag} prêts")
    if push:
        code, out = git("push", "--follow-tags", "origin", "HEAD", timeout=300, interactive=True)
        print("✓ publié : les amis recevront la mise à jour au prochain démarrage de Claude Code" if code == 0
              else "✗ " + gitmsg.explain(out, code, "envoi sur GitHub") + " ; le commit et le tag restent prêts, "
              "`brain publish --push` les renverra")
        return 0 if code == 0 else 1
    print("→ pour publier : brain publish --push (ou git push --follow-tags dans le dépôt)")
    return 0
