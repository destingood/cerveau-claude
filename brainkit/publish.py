"""Plugin Claude Code « cerveau » pour les amis : `brain publish <dépôt>` construit le plugin (code, hooks, serveur MCP,
skill, marketplace) dans le clone local du dépôt GitHub, le vérifie dans un bac à sable, puis fait le commit et le tag
de la version. Chez un ami, Claude Code installe le plugin une fois, puis le met à jour tout seul (`autoUpdate`) à chaque
version publiée ; ses souvenirs restent chez lui, dans ~/.claude/brain, et ne partent jamais.

Ne part dans le dépôt que le code (brain.py, brainkit/) et les skills (/brain, et les skills métier de skills/<nom>/,
comme le cerveau e-commerce) et les styles de réponse (output-styles/) : jamais les souvenirs ni la configuration. Les tests publics que le dépôt a déjà
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
from pathlib import Path

from . import __version__
from .common import CODE_DIR, load_config, read_json, remove_tree, set_config

NAME = MARKET = "cerveau"
AUTRES = {"plateforme"}  # dossiers d'autres projets du même dépôt (PR #8) : ni effacés, ni contrôlés, ni commités ici
KEEP = {".git", "CONTRIBUTORS.md"} | AUTRES  # tenus dans le dépôt lui-même, jamais effacés par la construction
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
    """Le README du dépôt publié (la page GitHub) : installation d'abord, puis ce que fait le cerveau, par thème ;
    README.md de ce dépôt = readme("Lucas", "destingood/cerveau-claude"), régénéré par `brain publish`."""
    repo = repo or "PROPRIETAIRE/DEPOT"
    commun = (read_json(CODE_DIR / "brainkit" / "commun.json", {}) or {}).get("repo") or "PROPRIETAIRE/cerveau-commun"
    return f"""# 🧠 Cerveau pour Claude Code

Une mémoire persistante pour Claude Code, faite par {owner} : Claude se souvient de toi, de tes projets, de tes
décisions et de ce qu'il a appris, d'une session à l'autre. Tout reste chez toi, sur ton PC.

![Version {__version__}](https://img.shields.io/badge/version-{__version__}-2ea44f) ![Python 3.10 ou plus](https://img.shields.io/badge/python-3.10%2B-3776ab) ![Windows, macOS, Linux](https://img.shields.io/badge/Windows_%C2%B7_macOS_%C2%B7_Linux-555)

**Sommaire** — [Installer](#installer-une-seule-fois) · [Au quotidien](#au-quotidien) · [Ce que fait le cerveau](#ce-que-fait-le-cerveau) ·
[Moins de tokens](#moins-de-tokens) · [Wiki et veille](#le-cerveau-en-wiki-et-la-veille-automatique) · [E-commerce](#le-cerveau-e-commerce) ·
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
| « fais décoller ma boutique », « trouve-moi des clients sans pub », « audite mon site », « quel produit vendre ? », « fais le point de la semaine », « où en est ma boutique ? » | passe au [cerveau e-commerce](#le-cerveau-e-commerce) (ou tape `/cerveau:ecommerce`), qui tient le suivi de chaque boutique |
| « ingère cet article », « range cette réponse dans le wiki », « fais le point sur le wiki » | alimente ton [wiki](#le-cerveau-en-wiki-et-la-veille-automatique) ; le point, c'est un contrôle de santé (pages à créer, sources en attente, pages dépassées) |
| « installe agent-browser », « transforme ce site en API », « teste mon site dans le navigateur »… | installe sur ton PC, avec ton accord, [l'outil qui convient](#les-outils-que-claude-installe-pour-toi), puis le pilote |

Vue 3D de ta mémoire : `~/.claude/brain/cerveau.html` (souvenirs, projets, le cerveau e-commerce avec ses fiches et ses
outils, et tes boutiques suivies).

## Ce que fait le cerveau

- **Au démarrage** de chaque session : l'essentiel de ta mémoire et du projet courant est injecté.
- **À chaque message** : les souvenirs et fichiers vraiment liés remontent tout seuls (fautes de frappe, écriture
  phonétique et synonymes compris). Un souvenir rappelé montre les phrases qui répondent à ton message, pas seulement
  son début ; `brain recall --pourquoi` dit pourquoi un souvenir n'est pas remonté.
- **En fin de tâche** : Claude note ce qui mérite d'être retenu (décisions, pièges, préférences).
- **Cartes de tes projets** (fichiers clés, où est défini quoi), à-faire datés, vue 3D, serveur MCP.
- **Le rêve** : l'entretien de ta mémoire se fait hors conversation, chaque jour — dates relatives rendues réelles,
  observations anciennes condensées — et ce qui demande du jugement (corrections entendues, doublons, conflits,
  à-faire en retard) est tranché par Claude au démarrage suivant : ce qui est sûr est appliqué, un doute est laissé
  et cité, rien n'est inventé.
- **Le style concis** (`/output-style cerveau:concis`) : l'action d'abord, sans préambule ni récapitulatif. Il devient
  ton style par défaut, sauf si tu en avais déjà choisi un ; `brain config style off` pour revenir.
- **La relecture sécurité** (skill `/cerveau:securite`) relit le code exposé (site, API, formulaire) avant de le livrer.
- **Tout s'active seul, sans commande** : le style concis, les filtres appris sur tes commandes, l'ingestion des sources
  déposées dans le wiki et le rêve.

**Confidentialité** : tout reste chez toi, dans `~/.claude/brain` — ou dans ton wiki, sur ton PC et, si tu le choisis,
dans ton dépôt GitHub privé. Rien n'est envoyé ailleurs, sauf ta part publique si tu rejoins le cerveau commun ; chacun
garde sa propre mémoire.

## Moins de tokens

- **Le mode éco**, posé une fois au démarrage : les sorties de commandes très longues vont dans un fichier (aperçu
  seul dans la conversation), la conversation est résumée plus tôt, et `brain eco` liste les plugins jamais utilisés.
  `brain eco --annuler` pour revenir.
- **Sorties compactées** avant d'arriver à Claude : une liste JSON arrive en tableau, une sortie déjà lue dans la
  session renvoie vers la première, les erreurs sont toujours gardées.
- **Filtres appris** : `brain compact --decouvrir` repère le bruit qui revient dans les sorties de tes commandes et
  `brain compact --apprendre <commande> --enregistrer` en fait un filtre appliqué tout seul. L'entretien du jour le
  fait aussi de lui-même, annoncé une fois ; `brain compact --oublier <commande>` pour retirer un filtre.
- **Texte injecté plus court** au démarrage, à chaque message et dans la liste des outils.
- **Skills chargées d'office** : `brain config skills.auto '["ma-skill"]'` et, dès qu'un message correspond à la skill,
  le cerveau glisse lui-même son contenu dans la conversation, sans attendre que Claude l'ouvre ; il la ressert
  après chaque résumé de la conversation.
- **Le compteur** : `brain tokens` donne ta consommation et son coût au tarif de l'API, en dollars.

## Le cerveau en wiki et la veille automatique

**Le wiki** (le « LLM Wiki » d'Andrej Karpathy) : `brain wiki init <dossier>` range chaque souvenir dans une page
Markdown d'un dossier que tu ouvres dans Obsidian (idéalement un dépôt GitHub privé). Tu y déposes des sources
(articles, PDF, transcriptions, notes) ; Claude les lit tout seul et tient à jour des pages de synthèse (sources
résumées, entités, concepts, sujets, analyses), liées entre elles. Le schéma que suit Claude est dans le `CLAUDE.md` du
wiki : fais-le évoluer avec lui. Rien ne change tant que tu ne le lances pas.

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

## Les outils que Claude installe pour toi

Chaque outil s'installe sur ton PC, avec ton accord et jamais sans ; le plugin n'apporte que la marche à suivre.
Règles communes : Claude ne tape jamais ton mot de passe (tu te connectes toi-même dans une fenêtre visible), ne
branche ton vrai Chrome avec tes comptes que sur ton « oui », te demande avant d'envoyer un formulaire ou un message,
et ne copie jamais une clé ou un jeton dans la conversation.

| Tu dis… | Skill | Ce que fait Claude | D'après |
|---|---|---|---|
| « branche perplexity », puis « cherche sur perplexity … » | `/cerveau:perplexity` | recherche web filtrée par sites, langue, pays ou date, ou recherche approfondie avec sources, avec ton propre compte Perplexity | le serveur officiel de Perplexity |
| « installe agent-reach », puis « lis ce tweet », « lis ce fil reddit », « sous-titres de cette vidéo YouTube » | `/cerveau:agent-reach` | lit en lecture seule X/Twitter, Reddit, YouTube, LinkedIn, Instagram et d'autres, là où sa recherche web échoue | Agent Reach (Panniantong) |
| « clone cette app », « ma version de X » | `/cerveau:replica` | refait ta propre version d'une app existante en 11 étapes, jusqu'à la fiche App Store et la mise en ligne | replica-skill (Jake Schincariol, MIT) |
| « bonnes pratiques react », « revue de mon interface », « déploie sur vercel » | `/cerveau:vercel` | choisit et suit la bonne des 9 skills officielles de Vercel | agent-skills (Vercel Labs, MIT) |
| « teste mon site dans le navigateur », « teste le parcours », « capture d'écran de la page » | `/cerveau:playwright` | pilote un navigateur en lignes de commande, en moins de tokens que le MCP Playwright | playwright-cli (Microsoft, Apache-2.0) |
| « design system », « dans le style de Stripe », « comme le site d'Apple » | `/cerveau:design-md` | pose dans ton projet le DESIGN.md d'une des 86 marques connues, l'adapte à ta marque, puis code en le suivant | awesome-design-md (VoltAgent, MIT) |
| « transforme cette image en site », « code cette maquette », « capture d'écran en site » | `/cerveau:image-to-code` | transforme une capture ou une maquette en vrai site responsive qui lui ressemble au plus près | image-to-code-skill (Leonxlnx, MIT) |
| « installe agent-browser », puis « cherche les bugs de mon site », « extrais les données de la page », « ouvre ce site et… » | `/cerveau:agent-browser` | navigue, clique, lit et mesure (vitesse, web vitals) dans un navigateur sans fenêtre, puis te montre ce qu'il a trouvé | agent-browser (Vercel Labs, Apache-2.0) |
| « installe spec kit dans ce projet », puis `/speckit-…` | `/cerveau:spec-kit` | construit ton appli à partir d'une spec écrite : principes, spec, plan, tâches, code, contrôle | Spec Kit (GitHub, MIT) |
| « installe reverse api », puis « transforme ce site en API », « ce site n'a pas d'API » | `/cerveau:reverse-api-engineer` | lit les vraies requêtes d'un site et en tire un client d'API typé (10 langages), vérifié sur de vraies données | reverse-api-engineer (Kalil, MIT) |
| « installe rea », puis « analyse ce binaire », « décompile cette fonction », « comment marche la recherche dans cette appli » | `/cerveau:rea` | lit en local un exécutable, une appli Electron, un APK, un firmware, une base SQLite ou une capture réseau, et explique avec preuves comment ça marche, pour t'aider à en refaire ta version | REA, Reverse Engineer Anything (morluto, MIT) |
| « humanise ce texte », « sonne trop IA », « on dirait de l'IA » | `/cerveau:humanizer` | réécrit ton post, ta bio, ta lettre ou ta fiche produit pour qu'il sonne comme toi, sans rien ajouter ni changer à ce qu'il dit | Humanizer (blader, MIT) |
| « ajoute une animation », « anime ce bouton », « transition de page », « rends le site plus vivant » | `/cerveau:motion-design` | anime ton site comme un motion designer : style, durées, courbes et ordre d'apparition, avec une version calme pour qui demande moins de mouvement | Motion Design Skill (LottieFiles, MIT) |

<details>
<summary>Le détail de chaque outil</summary>

- **Perplexity** (skill `/cerveau:perplexity`) : dis « branche perplexity » et Claude ajoute le serveur officiel de Perplexity sur ton PC, puis te guide pour te connecter avec ton propre compte (payant à l'appel, à ta charge, rien de partagé). Ensuite, « cherche sur perplexity … » : recherche web filtrée par sites, langue, pays ou date, ou recherche approfondie avec sources. Sans ce mot, Claude garde sa recherche web intégrée, sans frais.
- **Agent Reach** (skill `/cerveau:agent-reach`) : dis « installe agent-reach » et Claude te guide pour installer sur ton PC l'outil libre Agent Reach (github.com/Panniantong/Agent-Reach). Ensuite, « lis ce tweet », « lis ce fil reddit », « sous-titres de cette vidéo YouTube » : Claude lit en lecture seule X/Twitter, Reddit, YouTube, LinkedIn, Instagram et d'autres là où sa recherche web échoue. L'outil est gratuit (seule la transcription audio demande ta propre clé Groq ou OpenAI) ; il ne poste jamais rien et ne se connecte jamais à ta place (compte secondaire conseillé).
- **Replica** (skill `/cerveau:replica`, d'après replica-skill de Jake Schincariol, MIT) : « clone cette app » ou « ma version de X » et Claude refait sa propre version d'une app existante en 11 étapes — analyse des écrans et parcours, architecture, design, construction, backend, tests, score de parité avec l'original, lecture des vrais avis (ce que les utilisateurs détestent devient tes corrections et ton angle de vente), nouvelle marque, page de lancement et fiche App Store, mise en ligne. Les fonctions et les parcours seulement, jamais le code, le logo, les textes ni le contenu de l'original. Six outils Python fournis, sans installation ni accès réseau.
- **Skills Vercel** (skill `/cerveau:vercel`, d'après agent-skills de Vercel Labs, MIT) : « bonnes pratiques react », « revue de mon interface », « déploie sur vercel » et Claude choisit la bonne des 9 skills officielles de Vercel (performances React et Next.js, composants, animations de page, React Native, revue d'interface et accessibilité, déploiement, coût d'un projet en ligne), puis l'installe sur ton PC avec ton accord ou la suit une fois sans rien installer. Jamais de déploiement sans ton « oui », jamais de jeton dans la conversation.
- **Playwright** (skill `/cerveau:playwright`, d'après playwright-cli de Microsoft, Apache-2.0) : « teste mon site dans le navigateur », « teste le parcours », « capture d'écran de la page » et Claude pilote un navigateur en lignes de commande, en moins de tokens que le MCP Playwright ; il l'installe sur ton PC avec ton accord. Il ne tape jamais ton mot de passe : tu te connectes toi-même dans une fenêtre visible.
- **DESIGN.md** (skill `/cerveau:design-md`, d'après awesome-design-md de VoltAgent, MIT) : « design system », « dans le style de Stripe », « comme le site d'Apple » et Claude installe dans ton projet le DESIGN.md d'une des 86 marques connues (couleurs, typographie, espacements, arrondis, composants), l'adapte à ta marque, puis code l'interface en le suivant. L'outil getdesign s'installe sur ton PC avec ton accord, travaille hors ligne, télémétrie coupée.
- **Image-to-code** (skill `/cerveau:image-to-code`, d'après image-to-code-skill de Leonxlnx, MIT) : « transforme cette image en site », « code cette maquette », « capture d'écran en site » et Claude transforme une capture, une maquette Figma exportée ou le site que tu veux imiter en vrai site responsive qui lui ressemble au plus près : il relève section par section les textes, polices, espacements, couleurs et boutons, code, puis compare sa page à l'image et corrige les écarts. Il génère d'abord la maquette si tu as branché un outil d'images (par exemple une clé Gemini) ; sinon, donne-lui une image. Jamais le logo, les textes ni les photos d'un autre site.
- **agent-browser** (skill `/cerveau:agent-browser`, d'après agent-browser de Vercel Labs, Apache-2.0) : dis « installe agent-browser » et Claude installe sur ton PC ce navigateur piloté en lignes de commande (rapide, sans fenêtre, il se sert de ton Chrome). Ensuite, « cherche les bugs de mon site », « extrais les données de la page », « vitesse de chargement de la page », « ouvre ce site et… » : Claude navigue, clique, lit et mesure, puis te montre ce qu'il a trouvé. Il ne tape jamais ton mot de passe et te demande avant d'envoyer un formulaire ou un message.
- **Spec Kit** (skill `/cerveau:spec-kit`, d'après Spec Kit de GitHub, MIT) : dis « installe spec kit dans ce projet » et Claude installe sur ton PC l'outil `specify` (avec ton accord), puis le pose dans ton projet. Ensuite, tu construis ton appli à partir d'une spec écrite : les principes du projet, ce que tu veux et pourquoi, le plan technique, la liste des tâches, le code, puis un contrôle que le code colle bien à la spec. Tout reste en fichiers dans ton projet, pour reprendre plus tard ou le passer à quelqu'un. Les commandes `/speckit-…` ne partent que quand tu les tapes : elles ne coûtent rien tant que tu ne t'en sers pas.
- **Reverse API Engineer** (skill `/cerveau:reverse-api-engineer`, d'après reverse-api-engineer de Kalil, MIT) : dis « installe reverse api » et Claude installe sur ton PC l'outil `rae` (avec ton accord), puis le règle. Ensuite, « transforme ce site en API », « ce site n'a pas d'API », « fais-moi un client API pour ce site » : un navigateur fait la tâche que tu décris (« toutes les offres de cette page carrières »), rae lit les vraies requêtes du site, et Claude en tire un client d'API propre et typé (Python, TypeScript, Go… 10 langages), avec son README, qu'il vérifie sur de vraies données avant de te le donner. Navigateur neuf par défaut ; ton vrai Chrome avec tes comptes seulement sur ton « oui ». Les captures (cookies, jetons) restent sur ton PC et ne vont jamais dans la conversation ; chaque capture coûte des tokens, Claude te dit combien.
- **REA** (skill `/cerveau:rea`, d'après REA de morluto, MIT) : dis « installe rea » et Claude installe sur ton PC REA (Reverse Engineer Anything, avec ton accord) et le branche à Claude Code. Ensuite, « analyse ce binaire », « décompile cette fonction », « comment marche la recherche dans cette appli » : Claude lit en local un exécutable, une appli Electron, un APK, un firmware, une base SQLite ou une capture réseau, explique avec preuves comment ça marche et t'aide à en refaire ta version. Seulement pour un logiciel à toi ou que tu as le droit d'examiner ; jamais pour contourner une licence ou une protection. Les moteurs natifs (Ghidra, Hopper, IDA) restent facultatifs et à ta charge.
- **Humanizer** (skill `/cerveau:humanizer`, d'après Humanizer de blader, MIT) : « humanise ce texte », « sonne trop IA », « on dirait de l'IA » et Claude réécrit ton post, ta bio, ta lettre de motivation ou ta fiche produit pour qu'il sonne comme toi, sans changer ce qu'il dit : il retire les tics d'écriture d'IA repérés par Wikipédia. Il n'ajoute aucun fait, chiffre ni compétence que tu n'as pas donnés. Il l'installe sur ton PC avec ton accord, ou le suit une fois sans rien installer.
- **Motion design** (skill `/cerveau:motion-design`, d'après Motion Design Skill de LottieFiles, MIT) : « ajoute une animation », « anime ce bouton », « transition de page », « rends le site plus vivant » et Claude anime ton site comme un motion designer : il choisit d'abord le style (ludique, haut de gamme, sobre ou dynamique), puis la durée, la courbe et l'ordre d'apparition de chaque élément, en CSS, Framer Motion, GSAP ou Lottie. Toujours une version calme pour ceux qui demandent moins de mouvement, et rien qui distrait sur un formulaire ou une page de paiement. Il l'installe sur ton PC avec ton accord, ou la suit une fois sans rien installer.

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
        if item.name not in KEEP:
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    shutil.copy2(CODE_DIR / "brain.py", dest / "brain.py")
    shutil.copytree(CODE_DIR / "brainkit", dest / "brainkit", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    hooks = {event: [{**({"matcher": matcher} if matcher else {}), "hooks": [_hook(arg, timeout, status)]}]
             for event, arg, timeout, status, matcher in EVENTS}
    _json(dest / "hooks" / "hooks.json", {"description": "Cerveau : injection au démarrage, rappel à chaque message, "
                                                         "sorties de commandes compactes, mémorisation en fin de tâche",
                                          "hooks": hooks})
    _json(dest / ".mcp.json", {"mcpServers": {"cerveau": {
        "command": "python", "args": ["-I", "-S", "${CLAUDE_PLUGIN_ROOT}/brain.py", "mcp"]}}})
    _lf(dest / "skills" / "brain" / "SKILL.md", SKILL)
    for name, src in skills.items():  # skills métier (cerveau e-commerce…) : Claude Code les lit dans le plugin
        shutil.copytree(src, dest / "skills" / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", SKILL_MARK))
    if (CODE_DIR / "output-styles").is_dir():  # styles de réponse : /output-style cerveau:<nom>, au choix de chacun
        shutil.copytree(CODE_DIR / "output-styles", dest / "output-styles")
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


def secrets_in(dest: Path) -> list:
    """Fichiers du dépôt qui contiennent un secret (clé, jeton, mot de passe) ou une adresse e-mail : rien ne part."""
    from .privacy import find
    email = re.compile(r"[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")  # pas « paquet@1.80.0 »
    bad = []
    for p in dest.rglob("*"):
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
    remove_tree(tmp, wait=60)
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
    subprocess.run(git + ["add", "-A", "--", "."] + [f":(exclude){d}" for d in sorted(AUTRES)], check=True)
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
