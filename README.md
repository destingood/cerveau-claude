# 🧠 Cerveau pour Claude Code

Une mémoire persistante pour Claude Code, faite par destingood : Claude se souvient de toi, de tes projets, de tes
décisions et de ce qu'il a appris, d'une session à l'autre. Tout reste chez toi, sur ton PC.

![Version 8.43.0](https://img.shields.io/badge/version-8.43.0-2ea44f) ![Python 3.10 ou plus](https://img.shields.io/badge/python-3.10%2B-3776ab) ![Windows, macOS, Linux](https://img.shields.io/badge/Windows_%C2%B7_macOS_%C2%B7_Linux-555)

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
détail en bas. Les liens typés ont une flèche qui dit leur sens et, au survol, leur type et leurs dates. Un nœud
déplacé à la main reste où tu le poses (⚲ ou double-clic sur le fond pour tout libérer). Le bouton ◎ fait tourner la
caméra seule autour du cerveau, pour filmer, sauf si ton système demande moins d'animations. L'animation s'arrête
quand l'onglet est caché. À l'ouverture, chaque projet forme son amas à sa place, et les souvenirs sans projet se
regroupent par sujet ; ⊞ (touche G) revient à la disposition libre, et la vue s'en souvient.

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
- **Oublier une session** : chaque souvenir garde les sessions Claude Code qui l'ont écrit, et un journal garde
  l'ancien texte à chaque modification (`brain show <id> --history`). `brain oublier-session <id>` montre ce qu'une
  session a écrit, puis, sur ton accord (`--oui`), archive ce qu'elle seule a créé et remet comme avant ce qu'elle
  seule a changé ; ce qu'une autre session a repris est gardé, et c'est dit. `brain restore 1` annule.
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

Une skill qui a fait ses preuves (suivie par plusieurs membres) est proposée pour le plugin ; une fois que destingood l'a
relue et publiée, tous ceux qui ont le plugin la reçoivent à la mise à jour. `brain echange` montre où tu en es,
`brain echange non` arrête l'envoi et retire ce qui était parti, `brain echange recevoir non` coupe la réception.

Pour le lancer (destingood) : crée sur GitHub le dépôt **privé et vide** `destingood/cerveau-commun`,
invite tes amis (Settings → Collaborators → Add people), puis rejoins-le le premier (dis oui quand Claude le propose).

## Prérequis

**Python 3.10 ou plus, et la commande `python`** : les hooks du plugin la lancent ; sans elle, rien n'est enregistré, sans aucune erreur visible.
- macOS : `mkdir -p ~/.local/bin && ln -sf "$(command -v python3)" ~/.local/bin/python`, puis redémarre Claude Code · Debian/Ubuntu : `sudo apt install python-is-python3` · Windows : réinstalle Python depuis python.org en cochant « Add python.exe to PATH ».
- **Vérifier que le cerveau enregistre**, après ton premier message : `python ~/.claude/brain/brain.py doctor` puis `python ~/.claude/brain/brain.py journal` (macOS sans `python` : `python3`) ; si ce fichier n'existe pas, les hooks ne tournent pas : diagnostic direct avec `python3 "$(ls -d ~/.claude/plugins/cache/*/cerveau/*/ | tail -1)brain.py" doctor`.

## Désinstaller

`/plugin uninstall cerveau@cerveau`. Tes souvenirs restent dans `~/.claude/brain` (supprime ce dossier pour tout effacer).

Version 8.43.0.
