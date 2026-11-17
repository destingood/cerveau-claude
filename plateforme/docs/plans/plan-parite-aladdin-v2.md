# Plan v2 — Réparer le cerveau et l'amener au niveau d'Aladdin dans tes domaines

Date : 17/11/2026 · Statut : **proposé**, en attente de ta validation.

Cette version remplace la v1 du même jour (`docs/plans/plan-parite-aladdin.md`, dans la
[PR #18](https://github.com/destingood/cerveau-claude/pull/18)). Elle garde l'étape 0 de la v1, déjà
faite dans cette PR, et ajoute ce que la v1 ne voyait pas : la
[PR #12](https://github.com/destingood/cerveau-claude/pull/12), le budget API nul, tes domaines hors
finance et l'organisation du dépôt.

## 0. En bref

1. Le cerveau, ce sont aujourd'hui deux programmes qui ne se parlent pas : le **plugin** (ta mémoire
   et tes skills dans Claude Code) et la **plateforme** (116 603 lignes : calculs, garde-fous, évals),
   qui n'a jamais servi en vrai.
2. Avec 0 € d'API, la plateforme ne peut pas réfléchir seule. **Claude Code, sur ton abonnement,
   devient donc le « Copilot »** : il dirige, et la plateforme lui prête ses outils, ses règles et sa
   mémoire par un serveur MCP (le branchement standard des outils de Claude). C'est le schéma
   d'Aladdin Copilot : un chef d'orchestre, un registre d'outils testés, des garde-fous.
3. D'abord, réparer : **un seul endroit pour le code** (il y en a trois, et `brain publish` écrase
   GitHub), puis **fusionner le travail qui attend** (PR #12 depuis 19 jours, PR #18 depuis cette nuit).
4. Ensuite, chacun de tes domaines devient un « pack » mesuré, avec le même cycle qu'Aladdin :
   données → analyse → décision → **action après ton accord** → résultat mesuré → leçon.
5. 16 étapes en 4 blocs : Réparer, Unifier, Étendre, Durer. Chaque étape finit par un critère
   mesurable et ton GO.

## 1. « Niveau Aladdin, dans tous les domaines » : ce que ça veut dire

Aladdin (BlackRock) n'est pas une IA qui sait tout. C'est **une seule** plateforme où toutes les
équipes partagent les mêmes données, le même langage du risque et les mêmes contrôles, de l'analyse
au résultat. Aladdin Copilot y ajoute un chef d'orchestre qui appelle des outils enregistrés, testés
et filtrés (méga-prompt, §2).

| Principe d'Aladdin | Dans ton cerveau |
|---|---|
| Une seule source de vérité | Une base par type de donnée (contacts, candidatures, vidéos, boutiques, positions, état du PC), datée ; jamais deux copies |
| Un langage du risque commun | Chaque action porte les mêmes étiquettes partout : sa classe (de « lecture » à « financière »), réversible ou non, le niveau d'autonomie. Une seule règle décide |
| Tout le cycle | Données → analyse → décision → action → résultat → leçon, pour une vidéo comme pour un ordre de bourse |
| Copilot | Claude Code dirige ; la plateforme fournit outils, règles, mémoire et journal |
| Développement par l'évaluation | Un jeu de cas (golden set) et un score par domaine ; un domaine non mesuré reste au niveau « conseil » |

« Tout faire dans tous les domaines », honnêtement : Claude sait déjà parler de presque tout. Le
cerveau lui ajoute des outils, de la mémoire, des règles et des mesures. Il n'est **fiable** que dans
un domaine mesuré ; ailleurs, il conseille (pack Généraliste, niveau N1). Restent hors de portée,
comme dans la v1 : les données propriétaires, les modèles de risque institutionnels, les marchés
privés.

## 2. Tes réponses du 17/11/2026

| Sujet | Ta réponse | Conséquence dans ce plan |
|---|---|---|
| Plan v1 | L'améliorer | Cette v2 ; l'étape 0 de la v1 est gardée |
| Domaines | Finance ; e-commerce et business ; création de contenu ; code et automatisation ; et en détail : montage vidéo, gestion client, recherche de clients, recherche d'emploi, CV (contenu et design), rétention (vidéos et clients), Windows, réseaux (sociaux et internet du PC) | 4 nouveaux packs (§5) |
| Autonomie hors finance | Agir après ton accord (N3) | Une seule chaîne d'approbation pour tous les domaines (étape 7) |
| PR #12 | L'intégrer d'abord | Étape 1 |
| Budget API | 0 € | Claude Code dirige (étape 4) ; aucune campagne payante ; mesures sur ton abonnement (étape 8) |
| Logiciel de montage | After Effects | Scripts After Effects générés et rendu en ligne de commande (étape 10) |

## 3. État mesuré le 17/11/2026

Mesures de cette session sur `main` (`176a9c2`, cerveau 8.22.0) : Linux, Python 3.13, git 2.43,
clone superficiel. Le reste vient des PR et de leur CI. Les lignes « Travail en attente » et
« Plugin, tests » tiennent compte des trois PR que tu as fusionnées pendant la rédaction
(`main` à `a190251`).

| Sujet | Constat |
|---|---|
| Où vit le code | À trois endroits : ton dossier de développement du plugin (avec le code Rust de `brain.exe`, absent du dépôt), le dépôt local de la plateforme (recopié ici en sous-arbre), et GitHub, que les sessions cloud modifient directement. `brain publish` efface le dépôt et le recopie depuis ton dossier ; il ne garde que `.git`, `CONTRIBUTORS.md` et `plateforme/` |
| Travail en attente | 6 PR ouvertes et 15 autres branches au moment de la mesure ; tu as fusionné depuis les PR #13, #14 et #16 (17/11, 04:19 UTC). Restent la PR #7, la PR #12 (phase 7 et pack Business : 499 fichiers, 77 689 lignes ajoutées), en attente depuis le 29/10, et la PR #18 (étape 0 de la v1), depuis cette nuit. Les PR #12 et #18 créent un **ADR-061** différent et modifient 4 mêmes fichiers. Ton prénom revient dans 23 lignes de la PR #18, alors que la PR #12 l'a retiré du dépôt. Depuis la fusion de la PR #14, la PR #18 est aussi en conflit avec `main` sur `tests/test_eco.py` |
| Plugin, tests | 8 scripts sur 12 passent. Échecs : `test_eco` (3), `test_ecommerce` (3, dont 2 données personnelles dans un dépôt public), `test_wiki` (1), `test_bascule` (ne démarre pas). La PR #18 les corrige ; sa CI passe sous Linux et macOS, échoue sous Windows (`test_commun`, envoi différé, cause inconnue). Depuis la fusion de la PR #14, `test_eco` passe sur `main` (203 vérifications) |
| Plugin, serveur MCP | Ne démarre pas quand le dépôt est ouvert comme projet (`${CLAUDE_PLUGIN_ROOT}` non défini), reproduit dans cette session. Corrigé dans la PR #18 |
| Plugin, code | 30 347 lignes ; 14 alertes de lint réelles (8 imports inutiles, 6 f-strings vides) ; `mapper.py` et `cli.py` dépassent 2 400 lignes |
| Plateforme, tests | 6 801 réussis, 205 échecs, 5 erreurs, en 17 min 32 s. 208 viennent de git 2.43 (le pack Code exige 2.45). 2 viennent de NautilusTrader : le plafond de montant diffère entre Linux et Windows (C18), et un cas trouvé par un test aléatoire, reproductible, où le backtest maison vend 999 499 titres et NautilusTrader 999 498 (C27). Avec un git récent, la CI de la PR #18 passe sous Linux |
| Plateforme, évals hors ligne | 0 violation R5. Seuils manqués : pack Code (git 2.43) et golden Finance 92/96 (solveur, corrigé par l'ADR-061 de la PR #18) |
| Plateforme, réglages | 14 fonctions disponibles, **38 bloquées** : budgets, approbations, API, bot Discord, alertes, paper trading, live… |
| Plateforme, usage réel | **Aucun** : jamais de campagne d'évals réelle ; `interfaces/mcp_server/` et `core/memory/` sont vides. Rien ne la relie à Claude Code |
| Backlog | 265 points ouverts (279 avec la PR #12) |
| Dépôt | **Public**. Le plugin publie tout le dépôt, plateforme comprise, chez chaque personne qui l'installe |

## 4. Tous les problèmes

### 4.1 Les problèmes de la v1 (C1 à C18) : où ils en sont

| # | Problème | État |
|---|---|---|
| C1, C2, C6 à C11, C18 | CI, garde-fous à la racine, serveur MCP, tests et lint du plugin, git < 2.45, plafond NautilusTrader | Corrigés dans la PR #18, pas encore fusionnée ; un échec Windows reste (C22) |
| C3 | Le plugin livre toute la plateforme | Ouvert → étape 2 |
| C4 | Données personnelles dans un dépôt public | Fichiers corrigés (PR #18) ; ton nom complet reste dans l'historique git → D4 |
| C5 | `brain.exe` sans son code source | Ouvert → étape 0 |
| C12 | 38 fonctions bloquées par des réglages | Ouvert → étape 6 |
| C13 | Aucune mesure réelle | Ouvert ; à 0 €, autre méthode → étape 8 |
| C14 | Plateforme sans mémoire | Ouvert → étape 5 |
| C15 | Sécurité avant toute action réelle | B200, B230, B292 et B316 fermés par la PR #12 (à vérifier après fusion). Restent B8, B9, B228, B235 → étapes 7 et 15 |
| C16 | Erreurs de calcul de la revue quantitative | Ouvert → étape 9 |
| C17 | `ref.db` à la racine (B148) | Ta décision, déjà au backlog |

### 4.2 Nouveaux problèmes

| # | Problème | Étape |
|---|---|---|
| C19 | **Trois endroits pour le code.** `brain publish` efface GitHub et le recopie depuis ton dossier : les corrections faites dans le cloud (PR #18 : CI, garde-fous, serveur MCP, tests) disparaîtront à la prochaine publication si personne ne les recopie à la main | 0 |
| C20 | PR #12 et PR #18 non fusionnées et en conflit : deux ADR-061, 4 fichiers modifiés des deux côtés, prénom réintroduit par la PR #18. La PR #18 est aussi en conflit avec `main` (`tests/test_eco.py`, modifié par la PR #14) | 1 |
| C21 | **À 0 € d'API, la plateforme ne fait rien en vrai.** Son chef d'orchestre (LangGraph) appelle l'API, et aucun serveur MCP ne la relie à Claude Code | 4 |
| C22 | `test_commun` échoue sous Windows (envoi différé) ; il n'avait jamais tourné ailleurs que sur ton PC | 1 |
| C23 | Dépôt encombré : 6 branches déjà fusionnées ou contenues ailleurs, 3 anciennes à vérifier, et désormais celles des PR #13, #14 et #16 ; la PR #7 attend une décision. Les dossiers `fortnite-arene-prestige/` et `fortnite-ile/` (PR #13 et #16) sont à la racine de `main`, hors de ce que `brain publish` garde : la prochaine publication les effacera, et chaque utilisateur du plugin les reçoit | 0 et 1 |
| C24 | Les hooks lancent `python` : sur un Mac ou un Linux sans cet alias, le cerveau ne tourne pas et ne le dit pas (le README donne la parade à la main) | 3 |
| C25 | 33 skills sans aucune mesure de qualité ; certaines automatisent des sites tiers (aspiration, rétro-ingénierie d'API) : conditions d'utilisation à vérifier (R15) | 3 |
| C26 | Hors finance, aucun critère pour passer de N1 à N3, et l'autonomie maximale écrite est N1 ou N2 : « agir après ton accord » est impossible aujourd'hui | 7 |
| C27 | Le backtest maison et NautilusTrader ne donnent pas les mêmes exécutions sur un marché trouvé par Hypothesis (999 499 titres contre 999 498). Le cas revient à chaque passage ici ; la CI, qui tire d'autres marchés au hasard, peut ne pas le voir | 1 |

## 5. Tes domaines : les packs

Un pack, c'est un domaine mesuré : un manifeste, un rôle, 3 à 5 outils (R13), un golden set d'au
moins 30 cas, des tests de comportement et une red team (R5 : offres d'emploi, e-mails, commentaires
ou sous-titres piégés). Il entre à N0 et monte par ses scores. Tout chiffre vient d'un outil (R1) :
durée d'une vidéo, correspondance d'un CV avec une offre, taux de réachat.

| Pack | Tes besoins | Déjà là | Outils à créer |
|---|---|---|---|
| **Contenu & vidéo** (nouveau) | Montage After Effects, rétention des vidéos, réseaux sociaux, YouTube, Fortnite | Skills `youtube` (rétention, blancs, chapitres, accroche, titre), `motion-design`, `fortnite` | Préparation (ffmpeg), sous-titres (sur ton PC), script After Effects et rendu, rétention, publication |
| **Clients** (nouveau) | Gestion client, recherche de clients, fidélisation | À-faire datés du plugin ; plugin `entreprises` (PR #12) ; panel de clients simulés (PR #7) | Fiches clients, prospects, relances, fidélité |
| **Emploi & CV** (nouveau) | Recherche d'emploi, CV optimisé, CV designé | Skill `carriere-commerciale` (CV, progression, salaires) | Offres, CV en deux versions, CV face à l'offre, candidatures |
| **PC Windows** (nouveau) | Optimisation de Windows, réseau internet du PC | `brain pc` (mémoire, processeur, carte graphique) | Diagnostic, diagnostic réseau, appliquer et annuler |
| **Business & e-commerce** (PR #12) | Boutique, marges, études de marché, fidélisation | Plugins `business_calc`, `insee_stats`, `entreprises` ; skill `ecommerce` | Données de ta boutique (D6) |
| **Finance** (existe) | Investissement | 7 plugins finance, Porte de risque, paper trading | Étapes 3 à 6 de la v1 |
| **Code & automatisation** (existe) | Code, automatisation | Pack Code ; Claude Code | Tâches planifiées ; push et PR après ton accord |
| Généraliste, Recherche, Juridique FR, Cyber (existent) | Tout le reste | Packs existants | Rien de neuf ; Juridique répond aux questions RGPD des autres packs |

Autonomie visée : N3 (« agir après ton accord ») partout, sauf Généraliste, Recherche, Juridique et
Cyber, qui restent au conseil (N1) : ils n'ont aucune action à faire.

## 6. L'architecture à 0 € d'API

```
Toi
└─ Claude Code (ton abonnement) + plugin cerveau : mémoire, skills, hooks
   └─ serveur MCP de la plateforme (à créer) : outils des packs, 25 au plus par domaine
      ├─ lecture et calcul → réponse directe, chaque chiffre tracé (R1)
      ├─ action → une intention seulement → moteur de politique → ton accord
      │    (code à usage unique sur ton téléphone) → exécutée par la plateforme, jamais par Claude
      └─ journal d'audit chaîné, mémoire, base de données unique
Tâches de fond
├─ sans modèle : la veille du plugin sur ton PC (toutes les 30 min)
└─ avec modèle : tâches planifiées de Claude Code (abonnement) ou modèle local (D9)
```

- Le chef d'orchestre LangGraph de la plateforme reste dans le code, pour le jour où un budget API
  existe ; un ADR acte le changement de chemin.
- 25 outils au plus par domaine : la règle d'Aladdin Copilot, dont la planification se dégradait
  au-delà de 40 à 50 outils.
- **Risque qui reste** (R5) : Claude Code lit les contenus non fiables (pages, e-mails, offres) et
  propose les actions. Une page piégée peut lui faire *proposer* une mauvaise action ; elle ne peut
  pas la faire *exécuter* sans ton code. D'où B228 (le secret des codes hors de portée de Claude)
  avant tout N3.

## 7. Les étapes

Chaque étape suit la méthode du dépôt : complément de plan, ta validation, code, tests, évals,
compte rendu, arrêt jusqu'à ton GO. « Toi » dit ce qui ne peut venir que de toi.

### Bloc A — Réparer

**Étape 0 — Un seul endroit pour le code** (C5, C19)
- Claude : `brain publish` construit la version depuis le dépôt lui-même et n'efface plus rien
  d'autre ; un test refuse une publication qui supprimerait un fichier suivi par git.
- Toi : ton dossier de développement devient un clone du dépôt (`git pull`, `git push`) ; tu y
  ajoutes le code Rust de `brain.exe`, ou tu choisis de l'abandonner (D2) ; la plateforme suit D3.
- Fin : une correction faite dans le cloud et une faite sur ton PC arrivent toutes les deux dans la
  version publiée (test).
- La PR #12 peut être fusionnée avant (étape 1) : elle ne touche que `plateforme/`, que
  `brain publish` n'efface pas.

**Étape 1 — Fusionner le travail en attente** (C20, C22, C23, C27)
1. PR #12 : CI verte (Linux, Windows, évals hors ligne), puis vérifier que B200, B230, B292 et B316
   sont bien fermés.
2. PR #18 remise à jour sur la nouvelle `main` : son ADR-061 devient ADR-068 ; les conflits, dont
   `tests/test_eco.py` avec la PR #14, sont résolus sans baisser un seuil ni retirer un cas (R9) ; le prénom devient « l'utilisateur », comme
   dans la PR #12.
3. Les deux échecs restants : `test_commun` sous Windows et le cas NautilusTrader de C27. Chacun
   est expliqué puis corrigé, sans désactiver le test ; le cas de C27 est gardé comme exemple fixe
   du test, pour que la CI le rejoue toujours.
4. PR #7 selon D10 ; dossiers Fortnite selon D11, avant toute publication ; branches fusionnées
   supprimées.
- Fin : `main` contient la phase 7, le pack Business et l'étape 0 de la v1 ; CI verte sous Linux,
  Windows et macOS ; chaque PR et chaque branche restante a une suite décidée.

**Étape 2 — Un dépôt public propre** (C3, C4)
- Selon D3 : le plugin reste public et ne contient que le plugin ; la plateforme passe dans un dépôt
  privé, avec son historique et son `.claude/` à la racine.
- Historique : réécrit ou non selon D4 (push forcé : toi seul l'autorises).
- Fin : installer le plugin ne télécharge plus la plateforme ; le contrôle « données personnelles »
  passe en CI.

**Étape 3 — Un plugin solide** (C10, C24, C25)
- Les hooks trouvent Python seuls (`python`, `python3` ou `py`), ou le disent clairement ;
  `brain doctor` signale un hook qui ne tourne pas.
- Tests pour les modules jamais testés : recherche, index, rêve, serveur MCP, confidentialité.
- `cli.py` et `mapper.py` découpés sans changer leur comportement, tests d'abord.
- Revue des 33 skills : conditions d'utilisation (R15), licences (R14), un test minimal pour chaque
  skill qui a des scripts.
- Fin : CI du plugin verte sur les trois systèmes, 0 alerte de lint, chaque module a ses tests.

### Bloc B — Unifier

**Étape 4 — Le pont : Claude Code dirige la plateforme** (C21) — le cœur du plan
- ADR « Claude Code chef d'orchestre à 0 € d'API ».
- `interfaces/mcp_server/` : un serveur MCP qui expose les outils des plugins enregistrés, filtrés
  par domaine ; chaque appel passe par le moteur de politique et entre au journal d'audit.
- Les outils d'action ne créent que des intentions. Un outil `verifier` contrôle que chaque chiffre
  d'une réponse vient d'un appel d'outil (R1).
- Le plugin déclare ce serveur sur ton PC seulement, jamais chez tes amis.
- Fin (test automatique, avec un client MCP de test) : « quel est le risque de mon portefeuille ? »
  répond avec les chiffres de `finance_risk`, et l'appel est au journal ; une demande d'ordre devient
  une intention, refusée en N0.

**Étape 5 — Une seule mémoire, une seule base** (C14)
- La plateforme lit la mémoire du plugin (préférences, faits, décisions), avec source, date,
  confiance et expiration (méga-prompt, §11) ; `/oublier` efface partout.
- Une base locale unique pour les données des domaines (contacts, candidatures, vidéos, boutiques,
  positions, état du PC), datée (point-in-time).
- Fin (test) : un fait appris dans une conversation sert à un outil de la plateforme ; `/oublier`
  l'efface des deux côtés.

**Étape 6 — Réglages et décisions** (C12) ; peut commencer dès l'étape 1, c'est surtout ton travail
- Marqueurs recomptés après la PR #12 ; budget API écrit à 0 € (aucun appel payant possible).
- Claude propose une valeur prudente et sourcée par marqueur (la PR #18 a commencé :
  `docs/plans/etape-1-reglages.md`).
- Toi : tu écris toi-même les valeurs de gouvernance (live, limites, autonomie).
- Fin : `cerveau config check` ne bloque plus que le live, N4 et ce qui attend un compte pas encore
  créé.

**Étape 7 — Une seule chaîne d'approbation, pour tous les domaines** (C15, C26)
- D'abord B228 : le secret des codes à usage unique vit hors de portée de Claude Code (compte de
  service ou téléphone).
- Une approbation proportionnée :
  - action locale et réversible (fichier, rendu vidéo, réglage Windows avec retour arrière) : ton
    accord dans Claude Code, et le journal ;
  - action externe ou irréversible (e-mail, publication, candidature, prospection, push de code,
    ordre) : intention, puis code à usage unique, puis exécution par la plateforme.
- Critères N1 → N2 → N3 pour chaque domaine hors finance : Claude propose (`A_DEFINIR`), tu fixes ;
  toi seul relèves `max_level`.
- Fin (tests) : une action de chaque classe passe par la même chaîne ; un code faux ou expiré est
  refusé ; Claude ne peut pas lire le secret.

**Étape 8 — Mesurer pour de vrai, à 0 €** (C13)
- Les évals hors ligne restent en CI.
- Mesure réelle sur ton abonnement : une skill fait passer les golden sets dans Claude Code, par
  petits lots, avec des sous-agents ; un autre modèle juge (par exemple Opus juge Sonnet) ; tu relis
  20 jugements par pack (méga-prompt, §12.3).
- La nuit, par des tâches planifiées de Claude Code, seulement si les limites de ton abonnement le
  permettent (`A_VERIFIER`).
- Fin : un score réel par pack, dans `evals/reports/` ; ce qui est sous le seuil passe avant toute
  fonction nouvelle.

### Bloc C — Étendre (ordre selon D5)

**Étape 9 — Finance au niveau Aladdin** (C16) : les étapes 3 à 6 de la v1, inchangées sur le fond
- Données gratuites (OpenBB, yfinance, FRED) ; risque et performance complets (corrections C16,
  facteurs, stress historiques, attribution) ; tes actifs (change, obligations et options avec
  QuantLib, crypto sur une plateforme agréée MiCA) ; courtier (D12) en lecture, puis 4 semaines de
  paper trading.
- Le Comité (débat haussier contre baissier) est joué par des sous-agents de Claude Code et
  journalisé par la plateforme : sans API.
- Fin : critères de la v1 (portefeuille réel valorisé chaque jour sans CSV ; chaque mesure recoupée
  par un calcul indépendant ; 4 semaines de paper sans écart inexpliqué).
- Avance en parallèle des étapes 10 à 13 : le paper trading prend surtout du temps calendaire.

**Étape 10 — Contenu & vidéo : montage, rétention, réseaux sociaux**
- Données : tes rushs ; tes statistiques (YouTube Analytics avec ton compte Google ; TikTok et
  Instagram par leurs API officielles ou leurs exports, `A_VERIFIER`).
- Outils :
  - `video_preparer` : ffmpeg coupe les blancs, normalise le son, recadre en 9:16 ;
  - `sous_titres` : faster-whisper, sur ton PC, gratuit ;
  - `after_effects` : un script .jsx crée la composition (plans, sous-titres animés, marqueurs de
    chapitres), puis `aerender` fait le rendu ;
  - `retention` : les moments où les spectateurs partent, lus sur la courbe de rétention ;
  - `publication` : un calendrier tiré de tes statistiques ; envoi par API officielle après ton
    accord.
- Fin : une vidéo brute devient, en une demande, un projet After Effects prêt (coupes, sous-titres,
  chapitres) et un Short ; la publication attend ton accord.

**Étape 11 — Clients : gestion, recherche, fidélisation**
- Données : fiches clients (base unique de l'étape 5), commandes de ta boutique (D6), e-mails
  (connecteur Gmail de Claude).
- Outils :
  - `crm` : fiches, historique, relances datées ;
  - `prospects` : registre des entreprises (plugin `entreprises`, sans données personnelles) et score
    calculé selon tes critères ;
  - `relance` : brouillon, puis envoi après ton accord, avec un plafond par jour ;
  - `fidelite` : cohortes, réachat, valeur client, clients sur le départ.
- Règles : prospection selon la CNIL (`A_VERIFIER`), droit d'opposition, durées de conservation
  (RGPD).
- Fin : « qui dois-je relancer cette semaine ? » répond depuis la base ; « trouve 20 prospects »
  rend une liste sourcée et scorée ; rien ne part sans ton accord.

**Étape 12 — Emploi & CV**
- Données : ton profil (expériences, compétences : une seule source), les offres (API « Offres
  d'emploi » de France Travail, inscription gratuite, conditions `A_VERIFIER`), tes candidatures.
- Outils :
  - `offres` : recherche et alertes ;
  - `cv` : un PDF en deux versions depuis les mêmes données, sobre pour les logiciels de tri,
    designé pour un humain ;
  - `cv_offre` : ce que ton CV couvre de l'offre et ce qui manque (calcul déterministe) ;
  - `candidatures` : suivi, relances datées, envoi par e-mail après ton accord.
- Interdits : inventer une expérience, un diplôme ou une compétence (test de comportement) ; aspirer
  LinkedIn ou Indeed (CGU, R15).
- Fin : pour une offre, en une demande : CV adapté en deux versions, lettre, correspondance
  expliquée, candidature suivie.

**Étape 13 — PC Windows : optimisation et réseau internet**
- Outils :
  - `pc_diagnostic` : démarrage, services, disque, mémoire (à partir de `brain pc`) ;
  - `reseau_diagnostic` : débit, latence et gigue vers les serveurs que tu choisis, DNS, signal
    Wi-Fi ;
  - `pc_appliquer` : une action à la fois, avec point de restauration, sauvegarde du réglage et
    retour arrière en une commande.
- Interdits : couper Defender, le pare-feu ou les mises à jour de sécurité ; scripts de
  « nettoyage » de tiers.
- Tests : sorties de Windows enregistrées puis rejouées ; CI Windows.
- Fin : un rapport avant/après chiffré (démarrage, mémoire libre, latence) ; chaque changement
  s'annule.

**Étape 14 — Code & automatisation**
- Claude Code reste l'agent de code ; la plateforme apporte ses contrôles (bac à sable Docker,
  lecture de la CI). Push d'une branche et PR après ton accord, jamais sur `main`.
- Automatisations : la veille du plugin (sans modèle) et les tâches planifiées de Claude Code (avec
  modèle, sur ton abonnement) ; par exemple le rapport du lundi, les relances dues, les nouvelles
  offres, les statistiques des vidéos.
- Fin : 4 tâches planifiées tournent 4 semaines sans intervention.

### Bloc D — Durer

**Étape 15 — Amélioration continue, puis N3 domaine par domaine**
- Mise en service de la phase 7 (PR #12) : registre des prévisions et score de Brier, couche apprise
  avec champion et challenger, rapports hebdomadaire et de sécurité. Toi : tu lances
  `infra/windows/install-schedule.ps1`.
- N3 domaine par domaine : rapport de promotion, ta signature, `max_level` relevé par toi.
- Finance en réel : étape 9 de la v1 (B8, B9, B228 et B235 fermés ; `docs/procedure-live.md` suivie
  à la main ; capital et limites fixés par toi). N4 reste hors du plan.
- Fin : 4 semaines de rapports sans intervention ; chaque domaine actif a un score réel au-dessus
  de son seuil.

**En continu** : à chaque étape, fermer les points du backlog qui touchent le code modifié.

## 8. Décisions demandées

À trancher avant de commencer :

| # | Décision | Ma recommandation |
|---|---|---|
| D1 | Où vit le code | GitHub ; ton PC travaille sur un clone |
| D2 | `brain.exe` | Code Rust dans le dépôt, exe construit en CI ; sinon, Python seul |
| D3 | Un dépôt ou deux | Deux : plugin public, plateforme privée |
| D4 | Ton nom complet dans l'historique public | Réécrire l'historique si le dépôt reste public (push forcé, toi seul) |

À trancher plus tard, à l'étape concernée :

| # | Décision | Ma recommandation |
|---|---|---|
| D5 | Ordre des étapes 10 à 13 | L'ordre de ta liste : vidéo, clients, emploi et CV, PC ; la finance en parallèle |
| D6 | Ta boutique : Shopify, WooCommerce, autre ? | À préciser avant l'étape 11 |
| D7 | Les réseaux sociaux visés | À préciser avant l'étape 10 |
| D8 | Canal des approbations | Discord, déjà construit ; alertes ntfy sur ton téléphone |
| D9 | Modèle local pour la nuit | Seulement si ta carte graphique le permet (`brain pc` le mesure) |
| D10 | PR #7 (panel de clients simulés) | L'intégrer au pack Clients |
| D11 | Dossiers Fortnite des PR #13 et #16, fusionnés le 17/11 | Les déplacer dans un dépôt à part pour tes projets ; sinon, les protéger de `brain publish` |
| D12 | Courtier | Interactive Brokers (v1, P5) |
| D13 | ADR-061 du solveur (PR #18) | Le valider, renuméroté ADR-068 |

## 9. Confiance et points à vérifier

- **Mesuré dans cette session** (confiance élevée) : tout le §3.
- **Annoncé par les PR, pas revérifié ici** (confiance moyenne) : les résultats de la PR #12
  (7 591 tests, golden 305/305) et la fermeture de B200, B230, B292 et B316.
- **Estimation** (confiance faible) : la durée. Le bloc A tient en quelques sessions ; les blocs B et
  C sont le gros du travail, des semaines à des mois.
- `[VERIFICATION REQUIRED]` :
  - conditions de l'API France Travail ;
  - quotas de YouTube Analytics ; API de publication de TikTok et d'Instagram ;
  - API de script d'After Effects pour ta version (ExtendScript ou UXP) et `aerender` ;
  - limites de ton abonnement pour les tâches planifiées et le mode non interactif de Claude Code ;
  - règles de la CNIL sur la prospection ;
  - licence de chaque nouvel outil (R14).

## 10. Ce que ce plan ne fait pas

- Aucun seuil baissé ni garde-fou assoupli (R9).
- Rien n'est activé par Claude : live, comptes, serveurs MCP, autonomie (R3).
- Aucune dépense d'API.
- Aucune action externe sans ton accord ; aucune aspiration contraire aux CGU ; aucun CV embelli.
- Pas de N4.

## 11. Prochaines étapes

1. Tu valides ce plan, ou tu le corriges, et tu tranches D1 à D4.
   **D'ici là, ne lance pas `brain publish`** : d'après `brainkit/publish.py` de `main`, il
   effacerait les dossiers Fortnite que tu viens de fusionner.
2. L'étape 1 peut commencer tout de suite par la PR #12 : elle ne touche que `plateforme/`.
3. L'étape 0 demande une action sur ton PC ; son complément de plan te donnera les commandes.
