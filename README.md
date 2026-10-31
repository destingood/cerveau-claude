# 🧠 Cerveau pour Claude Code

Une mémoire persistante pour Claude Code, faite par destingood : Claude se souvient de toi, de tes projets, de tes
décisions et de ce qu'il a appris, d'une session à l'autre. Tout reste chez toi, sur ton PC.

![Version 8.17.1](https://img.shields.io/badge/version-8.17.1-2ea44f) ![Python 3.10 ou plus](https://img.shields.io/badge/python-3.10%2B-3776ab) ![Windows, macOS, Linux](https://img.shields.io/badge/Windows_%C2%B7_macOS_%C2%B7_Linux-555)

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
   /plugin marketplace add https://github.com/destingood/cerveau-claude.git
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
{
  "extraKnownMarketplaces": {
    "cerveau": { "source": { "source": "git", "url": "https://github.com/destingood/cerveau-claude.git" }, "autoUpdate": true }
  },
  "enabledPlugins": { "cerveau@cerveau": true }
}
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
- **Les bons outils, tout seuls** : quand un message parle de mails, d'agenda, d'un visuel Canva ou de la boutique, le
  cerveau souffle à Claude le connecteur branché qui convient et la recherche exacte qui charge ses outils en un seul
  appel, sans charger les autres. Les skills de tes plugins et de ton compte claude.ai se déclenchent sur des phrases
  en français (65 en ont d'office) ; un connecteur ou une skill qui arrive sans phrase française est signalé au
  démarrage, et `brain outils trig` ou `brain skill trig` lui en donne. `brain outils` montre ce qui est branché.
- **Le compteur** : `brain tokens` donne ta consommation et son coût au tarif de l'API, en dollars.

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
| « script de ma vidéo », « titre et miniature », « coupe les blancs », « audit de ma chaîne » | `/cerveau:youtube` | prépare, écrit et analyse tes vidéos en 11 étapes : planning, ce qui marche dans ta niche, script et accroche notée, titre et miniature, coupes, chapitres, description, Shorts, commentaires, rétention, audit ; rien ne se publie sans toi | youtube-agent-skill (Jake Schincariol, MIT) |
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
| « installe scrapegraph », puis « scrape ce site », « récupère tous les produits et les prix de… », « liste les prix des concurrents » | `/cerveau:scrapegraph` | extrait en JSON ce que tu demandes d'une ou plusieurs pages, ou d'une recherche web, avec un modèle local gratuit | ScrapeGraphAI (MIT) |

<details>
<summary>Le détail de chaque outil</summary>

- **Perplexity** (skill `/cerveau:perplexity`) : dis « branche perplexity » et Claude ajoute le serveur officiel de Perplexity sur ton PC, puis te guide pour te connecter avec ton propre compte (payant à l'appel, à ta charge, rien de partagé). Ensuite, « cherche sur perplexity … » : recherche web filtrée par sites, langue, pays ou date, ou recherche approfondie avec sources. Sans ce mot, Claude garde sa recherche web intégrée, sans frais.
- **Agent Reach** (skill `/cerveau:agent-reach`) : dis « installe agent-reach » et Claude te guide pour installer sur ton PC l'outil libre Agent Reach (github.com/Panniantong/Agent-Reach). Ensuite, « lis ce tweet », « lis ce fil reddit », « sous-titres de cette vidéo YouTube » : Claude lit en lecture seule X/Twitter, Reddit, YouTube, LinkedIn, Instagram et d'autres là où sa recherche web échoue. L'outil est gratuit (seule la transcription audio demande ta propre clé Groq ou OpenAI) ; il ne poste jamais rien et ne se connecte jamais à ta place (compte secondaire conseillé).
- **Replica** (skill `/cerveau:replica`, d'après replica-skill de Jake Schincariol, MIT) : « clone cette app » ou « ma version de X » et Claude refait sa propre version d'une app existante en 11 étapes — analyse des écrans et parcours, architecture, design, construction, backend, tests, score de parité avec l'original, lecture des vrais avis (ce que les utilisateurs détestent devient tes corrections et ton angle de vente), nouvelle marque, page de lancement et fiche App Store, mise en ligne. Les fonctions et les parcours seulement, jamais le code, le logo, les textes ni le contenu de l'original. Six outils Python fournis, sans installation ni accès réseau.
- **YouTube** (skill `/cerveau:youtube`, d'après youtube-agent-skill de Jake Schincariol, MIT) : « script de ma vidéo », « mon CTR est bas », « fais des shorts de ma vidéo », « audit de ma chaîne » et Claude t'aide pour tes propres vidéos en 11 étapes — planning de la semaine, vidéos qui battent leur chaîne dans ta niche (lues avec yt-dlp, en lecture publique), script avec cinq accroches notées, titre et texte de miniature, liste de coupes (blancs, « euh », reprises), chapitres valides, description et tags, Shorts, réponses aux commentaires, courbe de rétention de Studio, audit avec une seule correction prioritaire. Six petits outils Python sans réseau, adaptés au français (scores non calibrés en français : un repère, pas un verdict). Ton profil de voix vit dans `~/.claude/youtube/voice.md`. Claude écrit, toi tu publies : rien ne part sur ta chaîne sans ton oui.
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
- **ScrapeGraphAI** (skill `/cerveau:scrapegraph`, d'après Scrapegraph-ai de ScrapeGraphAI, MIT) : dis « installe scrapegraph » et Claude installe sur ton PC la bibliothèque libre et un modèle local Ollama (≈ 7 Go, gratuit, sans compte). Ensuite, « scrape ce site », « récupère tous les produits et les prix de… », « liste les prix des concurrents » : les pages sont lues par le modèle de ton PC et seul le tableau JSON revient à Claude, ce qui économise des tokens sur plusieurs pages. La télémétrie de l'éditeur, qui enverrait le contenu des pages, est coupée. Un petit modèle peut se tromper sur un chiffre : Claude revérifie ceux qui comptent, et ne contourne ni connexion ni protection anti-robot.

</details>

## Le cerveau commun (avec tes amis)

Si tu le veux, ce que tu apprends (recherches, savoir, projets que tu déclares communs) nourrit aussi le cerveau de
tes amis, et le leur nourrit le tien, presque en temps réel. Claude te le propose ; rien ne part avant ton oui, et
jamais ton profil, tes préférences ni rien de personnel ou de sensible.

1. destingood t'invite sur le dépôt GitHub privé du cerveau commun : accepte l'invitation (e-mail, ou
   https://github.com/notifications). Dépôt : `destingood/cerveau-commun`.
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

Pour le lancer (destingood) : crée sur GitHub le dépôt **privé et vide** `destingood/cerveau-commun`,
invite tes amis (Settings → Collaborators → Add people), puis rejoins-le le premier (dis oui quand Claude le propose).

## Prérequis

**Python 3.10 ou plus, et la commande `python`** : les hooks du plugin la lancent ; sans elle, rien n'est enregistré, sans aucune erreur visible.
- macOS : `mkdir -p ~/.local/bin && ln -sf "$(command -v python3)" ~/.local/bin/python`, puis redémarre Claude Code · Debian/Ubuntu : `sudo apt install python-is-python3` · Windows : réinstalle Python depuis python.org en cochant « Add python.exe to PATH ».
- **Vérifier que le cerveau enregistre**, après ton premier message : `python ~/.claude/brain/brain.py doctor` puis `python ~/.claude/brain/brain.py journal` (macOS sans `python` : `python3`) ; si ce fichier n'existe pas, les hooks ne tournent pas : diagnostic direct avec `python3 "$(ls -d ~/.claude/plugins/cache/*/cerveau/*/ | tail -1)brain.py" doctor`.

## Désinstaller

`/plugin uninstall cerveau@cerveau`. Tes souvenirs restent dans `~/.claude/brain` (supprime ce dossier pour tout effacer).

Version 8.17.1.
