# Plan du cerveau — le plan unique

Date : 20/11/2026, mis à jour le 21/11 · Remplace le plan v1 (`plan-parite-aladdin.md`) et le plan v2
(`plan-parite-aladdin-v2.md`), gardés en archive · Statut : **en cours** ; chaque étape attend ton GO,
sauf les correctifs sûrs, faits tout de suite à ta demande.

## 0. En bref

1. **La version 8.23.0 est publiée** (17/11) : publication sur place, tests du noyau et des skills,
   pont MCP de la plateforme (pas encore branché).
2. **Audit du 20/11.** Onze agents ont relu le plugin et la plateforme, chacun sur un morceau. Ils ont
   reproduit chaque défaut quand c'était possible, sur des cerveaux de test de 0 à 10 000 souvenirs
   (sous Linux). Bilan : près de 130 constats, dont 28 graves.
3. **Tes quatre gênes ont des causes précises** (§4) :
   - *il oublie* : le filtre du rappel écarte le bon souvenir même quand il est classé premier.
     Sur 62 questions naturelles, le rappel automatique en retrouve 53 %, contre 84 % pour `brain q`.
     Au-delà de 12 souvenirs dans une session, plus rien n'est rappelé. La consolidation de chaque jour
     fusionnait deux souvenirs de projets différents dès que leurs titres étaient les mêmes ;
   - *il est lent* : sur un gros cerveau, la consolidation de chaque jour bloquait toute écriture
     plusieurs minutes ; le premier démarrage après un changement recalcule l'analyse du graphe ;
     `brain add` réécrit trois gros fichiers ;
   - *il consomme* : environ 7 000 caractères au démarrage, 6 600 pour la liste des outils MCP, un tour
     de plus à chaque rappel de fin de tâche. Les descriptions de tes 33 skills (29 000 caractères) ne
     tiennent pas dans la place que Claude Code leur donne : la plupart ne se déclenchent pas seules ;
   - *des erreurs s'affichent* : sur Mac et Linux, `python` n'existe pas toujours (« hook error » à
     chaque message) ; des traces Python en anglais ; « Stop hook feedback » quand le cerveau rappelle
     de mémoriser.
4. **Sécurité** (§5) : du texte venu d'ailleurs entrait dans le contexte de Claude comme s'il venait
   du cerveau (site prompts.chat, pages d'un ami du cerveau commun) ; un mot de passe dit en phrase
   était enregistré en clair ; des données personnelles passent dans le cerveau commun. Côté
   plateforme, le pont MCP (pas encore branché) laisse passer des chiffres inventés et garde en clair,
   dans le journal d'audit, ce que Claude lui envoie : à corriger **avant** de le brancher.
5. **Déjà fait** (§9) : étape 1 le 20/11, douze défauts, dont tous ceux qui faisaient perdre un souvenir
   sans le dire ; étape 2 le 20/11, la sécurité restante (8.25.0) ; étape 3 le 21/11, le rappel (8.26.0) :
   le bon souvenir revient pour 58 questions sur 62, contre 33, sans faux rappel de plus ; étape 4 le 21/11, la
   vitesse (8.27.0) : à 3 000 souvenirs, chaque hook sous 150 ms, `brain add` de 2,1 s à 0,17 s ; étape 5 le 21/11,
   la consommation (8.28.0) : 18 skills au lieu de 33, démarrage et outils MCP −30 %.
6. **Attention, sous Windows.** `brain.exe`, la version Rust du cerveau, n'a pas changé depuis la
   8.18.2 du 10/11, et son code source n'est pas dans le dépôt. C'est lui qui exécute, sur ton PC, les
   hooks de session, le rappel, `done`, le verrou et le masquage des mots de passe. L'audit a mesuré
   et corrigé le code Python. Sur ton PC, ces correctifs et les améliorations Python faites depuis le
   10/11 ne valaient donc pas pour ces chemins. **Décision du 20/11 (E12) : Python partout** ; `brain.exe`
   ne tourne plus que sur demande, en attendant son code source, corrigé et optimisé.
7. **La suite** : 9 étapes pour le plugin (Réparer, Accélérer, Alléger, Regrouper), puis les étapes de
   la plateforme reprises du plan v2. Tes décisions sont au §10, les commandes à lancer sur ton PC au
   §11.

## 1. Ce que tu as demandé

| Date | Demande | Ce que le plan en fait |
|---|---|---|
| 17/11 | Plan v1 à améliorer, niveau Aladdin, tous tes domaines | Plan v2, repris ici (Bloc B à D) |
| 17/11 | Budget API 0 € ; agir après ton accord (N3) ; After Effects | Inchangé (§9, Blocs B et C) |
| 20/11 | « Toutes les améliorations, réglages, corrections, optimisation, regroupement » | Ce plan |
| 20/11 | Périmètre : plugin **et** plateforme | §3 à §8 |
| 20/11 | Regrouper : souvenirs, skills, code et dépôts, plans et documents | §7 |
| 20/11 | Gênes : il oublie, il est lent, il consomme trop, des erreurs s'affichent | §4 |
| 20/11 | Corriger le sûr tout de suite, le reste après ton GO | Étape 1 faite (PR des correctifs sûrs) |
| 20/11 | « Continue le plan », puis « continue » | Étapes 2 (8.25.0) et 3 (8.26.0) faites |
| 21/11 | Fusionner la 8.26.0 dès la CI verte ; étape suivante : la vitesse | 8.26.0 fusionnée ; étape 4 faite (8.27.0) |
| 21/11 | Fusionner la 8.27.0 ; étape 5 ; regrouper les skills, E2, E8, outils MCP de la mémoire seulement | 8.27.0 fusionnée ; étape 5 faite (8.28.0) |

## 2. Comment l'audit a été fait, et ses limites

- Onze agents : rappel et regroupement ; cœur et hooks ; commandes ; carte de projets et outils ;
  partage, wiki et visualisation ; vitesse et consommation ; skills ; documentation de Claude Code ;
  réglages ; état de la plateforme ; chemin de gouvernance du pont MCP.
- Chaque constat donne son fichier et sa ligne, et dit s'il a été **reproduit** (commande et sortie)
  ou seulement **lu**. Le détail technique est en annexe.
- Limites : rien n'a tourné sous Windows ni sur ton vrai cerveau. Les temps viennent d'une machine
  Linux à 4 cœurs ; sous Windows, chaque lancement de Python coûte plus cher. Les commandes du §11
  donnent les vrais chiffres sur ton PC.

## 3. État mesuré le 20/11

| Sujet | Constat |
|---|---|
| Plugin | cerveau 8.23.0 dans `main` ; 31 000 lignes de Python ; 15 scripts de tests (2 min 30) ; CI verte sous Linux, Windows et macOS |
| Tests du plugin | Ils font tourner 74 % des lignes. Les moins couverts : `vault` 10 %, `pc` 13 %, `importer` 18 %, `compact` 19 %, `selfupdate` 27 %, `promptlib` 28 %, `neurone` 31 % ; `bench.py` n'est jamais testé |
| Qualité du code | Aucun bloc copié-collé de plus de 10 lignes. 171 `except Exception` qui avalent l'erreur, 17 `except: pass`. 179 fonctions trop complexes, dont 17 très complexes (`mapper.call_edges`, `hooks.on_session_start`, `mcp_server.call_tool`…). `cli.py` et `mapper.py` dépassent 2 400 lignes |
| Réglages du plugin | 107 réglages, dont 99 expliqués nulle part ; 60 commandes et 53 alias, dont 9 documentées nulle part |
| Plateforme | 7 387 tests réussis. Les 207 échecs d'ici viennent tous de l'environnement : git 2.43 (le pack Code demande 2.45) et 2 tests qui échouent seulement sous l'administrateur. La CI est verte. Lint propre, aucun contrôle des types |
| Plateforme, réglages | 17 fonctions disponibles, **42 bloquées** par des réglages `A_DEFINIR` / `A_VERIFIER` (55 marqueurs dans 12 fichiers) |
| Plateforme, documents | Backlog : 279 points ouverts sur 359. 69 ADR, dont 41 encore « proposé ». 15 plans et 16 comptes rendus. README de 3 lignes |
| Dépôt | 15 branches en trop : toutes déjà dans `main` (vérifié ligne à ligne) |
| `brain.exe` (Windows) | Version Rust 8.18.2 du 10/11, livrée telle quelle depuis, sans son code source (C5, D2). Ses textes montrent qu'il traite les hooks de session, le rappel (`min_cov`, `session_cap_items`), `done`, le verrou du graphe et les mots de passe ; il rend le reste à Python |

## 4. Tes quatre gênes : causes et corrections

Effort : **S** moins d'une heure, **M** une demi-journée, **L** davantage. ✅ = corrigé le 20/11.

### 4.1 Il oublie ou rappelle mal

Mesure : un cerveau de test de 213 souvenirs, 62 questions écrites comme tu les écrirais, 14 qui ne
doivent rien rappeler. Le rappel automatique retrouve le bon souvenir dans 33 cas sur 62 et ne se
trompe jamais. `brain q` le classe dans ses trois premiers 52 fois sur 62. Dans 22 des 29 ratés, le bon
souvenir était dans les trois premiers, et le filtre l'a écarté.

**Après l'étape 3 (21/11)** : 58 sur 62 (94 %), toujours 2 faux rappels sur 38 pièges (`tests/test_rappel.py`,
par le vrai hook). Les chiffres de chaque ligne sont ceux mesurés après chaque correction, l'une après l'autre.

| Problème | Correction | Effort | Étape |
|---|---|---|---|
| Le filtre exige trop de mots du message : un message de trois phrases ne rappelle jamais rien | ✅ Mots de remplissage retirés (était, déjà…) ; seconde voie pour les messages de 5 mots ou plus, avec des garde-fous : 43/62, toujours 2 faux rappels sur 38 (sans garde-fous : 5) | M | 3 |
| Au-delà de 12 souvenirs par session, plus aucun rappel, sans le dire | ✅ 12 souvenirs sur les 20 derniers messages, une ligne quand le rappel fait une pause ; « tu te souviens… » passe toujours | S | 3 |
| La consolidation de chaque jour fusionnait deux souvenirs de deux projets au même titre | ✅ Même projet et même contenu exigés | S | 1 |
| Ajouter « Note 9 » archive « Note 7 » : même titre, chiffres différents = « mise à jour » | ✅ Une autre date, semaine, mois, année ou un autre numéro = un autre fait ; « le prix passe de 12 € à 14 € » reste une mise à jour | S | 3 |
| Au démarrage, 5 de tes 9 règles et préférences ne sont pas montrées (place manquante) | ✅ Toutes les règles et tout le profil, au moins par leur titre | S | 3 |
| « retiens / note… » enregistre des phrases qui n'en sont pas, des doublons et des infos sur des tiers | ✅ Ni « retiens-le », ni un ordre (« …, relance-le ») ; doublon reformulé reconnu ; rien de privé sur un tiers ; « n'oublie pas de… avant jeudi » devient un à-faire ; une ligne te dit ce qui a été retenu | M | 3 |
| Le rappel de mémoriser n'arrive qu'après 15 appels d'outils : une conversation courte n'est jamais retenue | ✅ Seulement sur une phrase durable pas encore enregistrée, quel que soit le nombre d'appels (E3) | S | 2 |
| Questions de date (« la semaine dernière ») : rien par le hook | ✅ Canal des dates dans le hook : 58/62 | M | 3 |
| Synonymes manquants ; racines des mots trop faibles (« refus » → « refu », « entreprise » trouve « entre ») | ✅ Racines corrigées : 45/62 ; 8 groupes de synonymes, gardés seulement s'ils n'ajoutent aucun faux rappel, et `--keys` demandé au moment de mémoriser : 54/62 ; « port » ne vaut livraison que pour la boutique, pas pour un serveur | M | 3 |
| Les observations notées en fin de tâche ne sont jamais rappelées | ✅ Une observation quand aucun souvenir ne passe (6 au plus par session) : 4 questions sur 4 qu'elles seules savent | M | 3 |
| Un souvenir montré coupé au démarrage reste bloqué toute la session | ✅ Bloqué seulement s'il a été montré en entier | S | 3 |
| `brain bench` annonce 100 % là où des questions réelles donnent 53 % | ✅ `tests/test_rappel.py` : 62 questions et 38 pièges, plus 8 messages longs et 16 pièges longs, par le vrai hook ; `brain bench` en donne le résultat | M | 3 (en premier) |

### 4.2 Il est lent

Mesures sous Linux, médianes de 9 essais. Avec 300 souvenirs, chaque hook prend 30 à 65 ms. Avec 3 000 :
65 à 160 ms. Avec 10 000 : jusqu'à 410 ms. Le reste du temps se perd dans les cas ci-dessous.

**Après l'étape 4 (21/11)**, médianes de 5 essais, mêmes cerveaux de test (`scratchpad/vitesse/hooks_baseline.py`) :

| Hook | 3 000 : avant → après | 10 000 : avant → après |
|---|---|---|
| Premier démarrage dans un nouveau dossier (le projet est créé) | 1 213 → 235 ms | 4 417 → 644 ms |
| Démarrage juste après une écriture, avant la tâche de fond | 933 → 134 ms | 3 434 → 307 ms |
| Démarrage de session | 180 → 89 ms | 380 → 167 ms |
| Message avec rappel | 174 → 92 ms | 444 → 169 ms |
| Question datée | 176 → 85 ms | 434 → 188 ms |
| Message sans rappel | 75 → 34 ms | 150 → 39 ms |
| Fin de réponse (Stop) | 77 → 38 ms | 130 → 47 ms |
| Avant et après un résumé (compaction) | 142 → 32 ms, 34 → 26 ms | 375 → 45 ms, 35 → 26 ms |
| Fin de session | 157 → 45 ms | 391 → 56 ms |
| `brain add` | 2 108 → 165 ms | 11 462 → 460 ms |

| Problème | Mesure | Correction | Effort | Étape |
|---|---|---|---|---|
| Consolidation de chaque jour : toutes les paires comparées, cerveau verrouillé | ✅ Plus de 8 min → 15 s à 3 000 souvenirs ; `brain optimize` 82 s → 3,8 s | Seulement les souvenirs écrits depuis le passage précédent ; mots découpés une fois | M | 1 |
| Premier démarrage après un changement : analyse du graphe recalculée dans le hook | +1 s à 3 000, +4,2 s à 10 000 | ✅ Jamais calculée dans un hook : l'analyse précédente sert, la tâche de fond des vues la refait (933 → 134 ms) | M | 4 |
| `brain add` réécrit l'export et les deux visualisations | 2,3 s à 3 000, 13 s à 10 000 | ✅ Le graphe seulement ; les vues refaites en arrière-plan, une fois pour plusieurs ajouts ; mots des souvenirs gardés (2,1 s → 0,17 s) | S-M | 4 |
| Chaque rappel réécrit tout graph.json pour compter les rappels | −116 ms sur 387 à 10 000 | ✅ Compteurs dans `state/compteurs.json`, repris à la prochaine écriture du graphe, jamais comptés deux fois | M | 4 |
| Travail en double à chaque message (empreinte calculée deux fois, graphe lu deux fois) | −68 ms à 10 000 | ✅ Empreinte du fichier lue une fois ; index des souvenirs repris sans relire chaque souvenir, refait seulement pour ceux qui changent | S | 4 |
| Index du démarrage reconstruit à chaque session de projet | −200 ms à 10 000 | ✅ Gardé tant que rien de ce qu'il montre ne change ; préparé par la tâche de fond pour les deux derniers projets | M | 4 |
| Fin de session et résumé : visualisation et index refaits dans le hook | −120 à −350 ms | ✅ Laissés à la tâche de fond des vues ; PreCompact en `async` (documentation de Claude Code : hook non attendu, sortie ignorée) ; SessionEnd et PostCompact restent synchrones | S | 4 |
| prompts.chat : un serveur lent tenait chaque message jusqu'à 40 s | ✅ Délai total | | S | 1 |
| Import de la mémoire de Claude Code sans limite de taille | Un fichier de 63 Mo : 34 s et 788 Mo de mémoire | ✅ Fichiers de plus de 64 Ko ignorés, une ligne le dit ; `brain import --max-ko 0` les prend quand même | S | 4 |
| Le réflexe de skills relit chaque SKILL.md à chaque message | 60 ms (20 skills), 170 ms (800) | ✅ Catalogue gardé, relu seulement pour un fichier changé ; motif d'une skill compilé seulement si son nom est dans le message (800 skills : 69 → 23 ms) | S | 4 |
| Question datée (« la semaine dernière ») : le canal des dates ajouté à l'étape 3 lisait les dates de chaque souvenir | ✅ À 3 000 souvenirs, hook 107 → 276 ms, puis 124 → 166 ms une fois corrigé (le sujet d'abord) | ✅ Dates de chaque souvenir gardées avec l'index (176 → 85 ms) | S | 3, puis 4 |
| Observations de fin de tâche cherchées à chaque message qui ne rappelle aucun souvenir (étape 3) | 6 ms (300 observations), 43 ms (2 000) | ✅ Leur index gardé entre deux messages (2 000 : 41 → 6 ms) | S | 4 |
| Modules chargés inutilement par chaque hook | −8 à −15 ms par hook | ✅ Modules et motifs chargés au premier usage ; `commun` seulement pour un membre (imports d'un message sans rappel : 50 → 29 ms) | S | 4 |
| Sous Windows, quatre hooks lancent `brain.exe` puis Python : deux démarrages | Non mesuré ici | ✅ Python seul par défaut depuis la décision E12 | — | 2 |
| Reste : premier démarrage dans un nouveau dossier (création du projet, carte, tâches de fond) | 235 ms à 3 000, une fois par dossier | Écrire le projet sans instantané de l'historique ; carte en arrière-plan | S | 8 |
| Reste : graph.json lu en entier à chaque hook | 52 à 77 ms à 10 000 | Une copie marshal du graphe (30 ms, mais 3 à 8 Mo de plus) : seulement au-delà de 10 000 souvenirs | S | — |
| Reste : la tâche de fond refait toutes les vues après chaque fin de session et chaque résumé | Quelques secondes de calcul en arrière-plan à 10 000 | Ne refaire que les vues dont les sources ont changé | S | 5 |
| Reste : `brain q` et le serveur MCP calculent l'analyse sur place, une fois après un changement | 1 à 4 s | La prendre comme les hooks, même périmée | S | 6 |

### 4.3 Il consomme trop

Coût mesuré, en caractères (le cerveau compte 2,2 caractères par token, une valeur qu'il a mesurée sur
tes échanges) :

| Quand | Quoi | Caractères |
|---|---|---|
| Chaque session | Injection du démarrage (index, règles, projet, consignes) | 6 600 |
| Chaque session | Liste des 15 outils du serveur MCP du cerveau | 6 600 à 7 000 |
| Chaque session | Style « concis » ; descriptions des 3 agents | 1 250 ; ≈ 1 000 |
| Chaque message | Rappel : 0 si rien ne passe, 700 à 900 sinon | 0 à 900 |
| Après 15 appels d'outils ou 3 modifications, puis tous les 150 appels, et après chaque résumé | Rappel de mémoriser (hook Stop) **plus un tour complet du modèle** | 1 060 + un tour |

**Après l'étape 5 (21/11)**, mesuré par de vrais processus sur les cerveaux de test : injection du démarrage
7 725 → 6 728 caractères dans un projet (300 souvenirs), 8 069 → 7 072 (3 000) ; liste des outils MCP 6 588 → 3 204 ;
les deux ensemble −30 %. Descriptions des skills listées : 29 758 → 4 180 caractères. Skill `brain` : 23 802 → 5 377.

| Problème | Correction | Effort | Étape |
|---|---|---|---|
| Les 33 descriptions de skills (29 000 caractères) dépassent la place que Claude Code leur donne (1 % du contexte, environ 8 000 caractères ; le mode éco l'abaisse à 0,5 %). Les descriptions en trop sont retirées, en commençant par les skills les moins utilisées | ✅ Phrases-déclencheurs dans `metadata.triggers` (le réflexe les lit là, Claude Code les ignore) ; 18 skills (§7.2), chaque description sous 250 caractères : 4 180 caractères en tout | M | 5 |
| Le rappel de mémoriser relance un tour entier du modèle | ✅ Seulement sur une vraie phrase durable (décision E3) | S | 2 |
| Bloc de consignes réinjecté au démarrage, après un résumé et après `/clear` | ✅ L'essentiel seulement, le même bloc partout (1 916 → 1 009 caractères) ; la liste des commandes va dans la skill | S | 5 |
| 15 outils MCP exposés (mémoire, boutique, wiki), résultats sans limite de taille | ✅ Les 6 outils de la mémoire par défaut (ta décision du 21/11) ; boutique et wiki avec `brain config mcp.groupes '["boutique", "wiki"]'` ; chaque résultat coupé à 8 000 caractères, par pages | S | 5 |
| La skill `brain` fait 24 500 caractères et reste dans le contexte une fois chargée | ✅ 5 377 caractères ; le reste, mot pour mot, dans 7 fichiers `references/` lus au besoin | M | 5 |
| Un dossier qui contient seulement un README devient un projet, cartographié toutes les 10 min | ✅ Un vrai marqueur exigé (code, fichier de projet, ou 3 documents) ; les anciens projets de ce genre ne sont plus recartographiés | S | 5 |
| Mode éco : place des descriptions de skills (décision E2) | ✅ Toujours 0,5 % du contexte, et `skillListingMaxDescChars` à 250 : plus de skills tiennent pour le même coût | S | 5 |
| La tâche de fond refait toutes les vues après chaque fin de session (reste de l'étape 4) | ✅ Seulement les vues dont les sources ont changé : 580–660 ms → 40 ms par passage à 3 000 souvenirs | S | 5 |
| Reste : l'injection seule baisse de 12 à 17 %, pas d'un tiers : à 3 000 souvenirs, ce sont surtout les titres des 393 règles et profils, qu'on ne retire pas | Baisser `inject.project_tokens` et `index_tokens`, ce qui montre moins de savoir au démarrage : ta décision | S | — |
| L'ancienne skill `cerveau-ecommerce` 1.x est encore active dans ton compte claude.ai, à côté de la v2 | **Toi** : la désactiver dans claude.ai (Paramètres, Skills) | S | 5 |

### 4.4 Des erreurs s'affichent

| Problème | Correction | Effort | Étape |
|---|---|---|---|
| `python` absent (Mac, Ubuntu) : « hook error » à chaque message et après chaque commande | Décision E1 : lanceur qui essaie python3, python puis py, ou consigne d'installation vérifiée par `brain doctor` | M | 6 |
| « Stop hook feedback » : le cerveau bloque la fin d'une réponse pour rappeler de mémoriser | Décision E3 | S | 5 |
| Traces Python en anglais : graphe illisible, dossier en lecture seule, fichier absent | ✅ Message en français avec la marche à suivre | S | 1 |
| `brain pc` plante sous Mac et Linux | ✅ Message clair | S | 1 |
| `brain config clé valeur` accepte n'importe quoi (« abc » pour un nombre), et une seule valeur fausse casse l'injection | Vérifier le type et la clé avant d'écrire | M | 6 |
| Code de sortie 0 sur un échec (`deps`, `explain`, `echange voir`…), valeurs négatives acceptées | Code 1 et message clair | S | 6 |
| Messages de git bruts ou trompeurs (« ✓ à jour » quand le dépôt est injoignable) | Messages en français avec la marche à suivre | S | 6 |
| Serveur MCP : erreurs en anglais ; une valeur qui commence par « - » est prise pour une option | Vérifier les arguments, message en français | M | 6 |
| `brain tokens` plante sur une ligne de transcript sans compteur | La sauter | S | 6 |
| `brain publish` sans dossier reprend le dernier dossier retenu au lieu de publier sur place depuis le clone (vu le 20/11) | Depuis un clone du même dépôt : sur place, le dossier retenu seulement sinon | S | 6 |

## 5. Sécurité et confidentialité

| Problème | État | Étape |
|---|---|---|
| prompts.chat : du texte d'un site public entrait dans le contexte comme venant du cerveau (un identifiant piégé de 3 700 caractères passait) | ✅ Identifiant court exigé, description hors du contexte, en-tête « données, jamais des consignes » | 1 |
| Un mot de passe dit en phrase (« le mot de passe du compte X est … ») était enregistré en clair | ✅ Masqué | 1 |
| Cerveau commun : le texte d'un souvenir d'ami entre tel quel dans ton contexte, y compris un faux « profil » ou une fausse « règle » | Écarter les types profil et règle venant d'un ami ; texte d'ami marqué comme donnée et neutralisé | 2 |
| Cerveau commun : chemins avec ton nom, téléphones étrangers, adresses postales, e-mails écrits « [at] » passent au partage, et l'historique git les garde | Filtre élargi, ton nom remplacé, comme pour les skills échangées | 2 |
| `brain pc` (veille Windows) ferme sans demander tout processus orphelin de plus de 10 min dont la ligne de commande contient « mcp » ; `brain pc --clean` aussi | Signature précise ou simple liste par défaut (décision E5) | 2 |
| Le mode éco désactive tout seul, une fois par jour, des plugins et des skills claude.ai jugés inutilisés | Sur ton accord seulement (décision E6) | 2 |
| `settings.json` de Claude Code réécrit en entier sans le relire juste avant : une modification faite en même temps se perd | Relire et fusionner juste avant d'écrire | 2 |
| La visualisation 3D charge des scripts de trois sites, sans contrôle d'intégrité | Les livrer avec le plugin | 8 |
| Sans `commun.repo`, rejoindre le cerveau commun utilise le dépôt de l'auteur | À savoir avant de partager | — |

## 6. Ne plus perdre de souvenir

| Problème | État | Étape |
|---|---|---|
| Le verrou d'un travail long (consolidation, import) était repris au bout de 30 s : un souvenir annoncé « mémorisé » disparaissait | ✅ Le détenteur rafraîchit son verrou | 1 |
| Un graph.json au bon format JSON mais à la mauvaise forme était remplacé par un cerveau vide, sans copie | ✅ Réparé comme un fichier abîmé, l'original gardé | 1 |
| Mémoire hors service (graphe illisible, dossier en lecture seule) sans rien dire | ✅ Un message au démarrage | 1 |
| Réparation d'un graph.json abîmé depuis un instantané qui peut dater de 30 min : les souvenirs récents disparaissent | Instantané toutes les N écritures ; récupérer les souvenirs lisibles du fichier abîmé ; prévenir | M · 7 |
| Sauvegarde automatique seulement sous Windows avec un second disque | Dossier par défaut dans ton dossier personnel ; prévenir une fois (décision E7) | S · 7 |
| Wiki sur deux PC par git : bloqué pour de bon dès le premier conflit sur `index.md` | Ne plus suivre `index.md` ; `log.md` fusionné ; copie de conflit au lieu d'abandonner | M · 7 |
| Wiki : un verrou git oublié bloque tout envoi, alors que l'écran dit « ✓ » | Nettoyer le verrou comme le cerveau commun ; ne plus afficher ✓ | S · 7 |
| Synchro avec un coffre Obsidian : une modification faite dans le cerveau se perd si la note a été touchée après | Copie de conflit chaque fois que les deux côtés ont changé | S · 7 |
| Mise à jour automatique (`self-update`) : une copie à moitié faite n'est pas annulée | Retour arrière sur toute erreur | M · 7 |

## 7. Regroupement

### 7.1 Les souvenirs

- ✅ La consolidation ne fusionne plus deux projets (étape 1).
- Les doublons reformulés ne sont jamais vus : les 7 paires plantées obtenaient 0,11 à 0,39 de
  similarité, pour un seuil de 0,6 à 0,9. Chercher les candidats par l'index de recherche (M, étape 8).
- 40 souvenirs sur 209 n'ont pas de projet. L'analyse du graphe en place en rattache déjà 4 sur 5 au
  bon projet. Nouvelle commande `brain regroupe` : elle montre d'abord ce qu'elle ferait (doublons à
  fusionner, souvenirs à rattacher à un projet, sujets à réunir en fiche), puis attend ton accord
  (L, étape 8).

### 7.2 Les skills : de 33 à 18

| Groupe | Aujourd'hui | Proposition |
|---|---|---|
| Design et interface | taste-skill, impeccable, design-md, skillui, image-to-code, emil-kowalski, motion-design, animejs, kokonutui, uiverse, bklit-ui, logo-design (12) | 4 : **design**, **animation**, **composants** (des aiguillages qui lisent la bonne fiche au besoin), **logo-design** |
| Web et recherche | agent-browser, playwright, scrapegraph, agent-reach, reverse-api-engineer, perplexity, recherche, public-apis (8) | 3 : **web** (aiguillage), **recherche** (avec perplexity), **public-apis** |
| Doublons de plugins installés | humanizer, vercel (2) | Retirées ; leurs phrases-déclencheurs passent au cerveau (décision E8) |
| À garder | brain, obsidian, ecommerce, fortnite, carriere-commerciale, youtube, replica, securite, spec-kit, rea, automaton (11) | Inchangées ; spec-kit, rea et automaton seulement sur demande (`disable-model-invocation`) |

Ce qui se perd : une commande `/cerveau:…` par outil, et une lecture de fichier de plus à l'usage.
Avant de regrouper : déplacer les phrases-déclencheurs dans les déclencheurs du cerveau, sinon son
réflexe ne trouve plus rien. Corrections au passage : chemin du script de scrapegraph (Windows
seulement, relatif au dossier courant), test cité par image-to-code qui n'existe pas, déclencheurs
de logo-design contraires à son contenu, le mot « logo » trop court pour déclencher.

**Fait le 21/11** (étape 5), comme proposé et validé par toi : `design` (taste-skill, impeccable, design-md, skillui,
image-to-code), `animation` (motion-design, animejs, emil-kowalski), `composants` (kokonutui, uiverse, bklit-ui),
`web` (agent-browser, playwright, scrapegraph, agent-reach, reverse-api-engineer), `recherche` (avec perplexity),
plus logo-design, public-apis et les 11 inchangées. Chaque ancienne skill est une fiche `<groupe>/<nom>/fiche.md`,
avec ses scripts, ses références et sa licence. Seul écart : « motion design », « site animé » et « effet au
scroll » mènent à `animation` (qui renvoie à la fiche taste-skill pour un site entier). Toutes les corrections
ci-dessus sont faites.

### 7.3 Le code et les dépôts

- Découper `cli.py` (2 416 lignes, une commande par module) et `mapper.py` (2 415 : parcours, langages,
  requêtes), tests d'abord, sans changer le comportement ; puis `hooks.on_session_start`, la fonction
  la plus complexe du plugin (L, étape 8).
- Carte de projets, défauts reproduits : paquet local compté comme externe ; dossiers `build/`, `env/`,
  `out/` ignorés à toute profondeur ; `exports.x =` non indexé ; un changement dans la même seconde
  pas vu (S chacun, étape 8).
- Deux dépôts (D3) et les dossiers Fortnite à part (D11) : toujours en attente de tes dépôts privés.
- 15 branches à supprimer : rien ne manque à `main` (ton accord, étape 8).
- Plateforme : environ 6 000 lignes servent seulement au chef d'orchestre LangGraph, inutilisable à
  0 € (décision E9). 5 blocs dupliqués entre plugins (client HTTP, arguments Docker).

### 7.4 Les plans et les documents

- **Ce fichier est le seul plan à jour.** Les plans v1 et v2 sont gardés pour l'historique.
- À faire (étape 9) :
  - ranger les plans de phase et les comptes rendus dans `docs/archive/` ;
  - au backlog, fermer les points devenus sans objet avec 0 € d'API (B20, B28, B31, B43, B44, B46,
    B47, B51 à B53, B95, B104, B130, B258, B286 à B288, B294, B296) et ceux déjà faits (B14, B56) ;
    fusionner les doublons (B297 à B299, B264/B265/B281, B282 à B284, B168/B182/B191) ;
  - ADR : marquer ADR-002 comme modifié par ADR-069 ; trancher ADR-013 (« pas de yfinance ») contre
    l'étape 9 du plan v2 ;
  - réécrire la mission de `CLAUDE.md` (encore « orchestrateur LangGraph ») ;
  - un vrai README pour la plateforme.
- **Toi** : valider en une fois les 41 ADR « proposé », et les 5 retraits de cas d'évaluation
  (ADR-021, 046, 050, 057, 060) que la règle R9 te réserve.

## 8. Réglages

- **Le mode éco écrit dans les réglages de Claude Code** (une fois, annulable avec
  `brain eco --annuler`) :

  | Réglage | Valeur posée | Avis |
  |---|---|---|
  | `bashOutputMaxChars` | 10 000 (30 000 par défaut) | Garder |
  | `autoCompactWindow` | 200 000 | Garder |
  | `autoMemoryEnabled` | false (la mémoire automatique de Claude Code ferait double emploi) | Garder |
  | `outputStyle` | cerveau:concis | Garder, mais le dire |
  | `skillListingBudgetFraction` | 0,005 (la moitié du défaut) | Décision E2 |
  | `enabledPlugins`, skills claude.ai | Désactivés s'ils semblent inutilisés | Décision E6 |

- **Rappel** : `min_cov` 0,5 ; à 0,4, il retrouve 38 souvenirs sur 62 au lieu de 33, pour un faux
  rappel de plus sur 14. Décision E4, après le banc d'essai de l'étape 3.
- **prompts.chat** est actif par défaut : une recherche sur internet à certains messages (« agis comme
  un expert… »). Décision E10.
- **107 réglages, 99 sans explication** : `brain config` vérifiera les valeurs (étape 6) ; une page
  générée les expliquera tous (étape 9).
- `skillOverrides` ne s'applique pas aux skills d'un plugin (documentation de Claude Code) : pour celles
  du cerveau, seul l'en-tête de la skill compte.

## 9. Les étapes

Chaque étape : complément de plan si besoin, ton GO, code, tests, compte rendu. Les étapes 2 à 9
peuvent se faire dans l'ordre que tu préfères ; l'ordre proposé suit tes gênes.

### Bloc A — Le plugin

**Étape 1 — Correctifs sûrs** : **faite le 20/11** (PR des correctifs sûrs, cerveau 8.24.0 une fois
fusionnée). Chaque correctif a un test qui échoue sans lui :
- verrou rafraîchi par son détenteur ; graph.json de mauvaise forme réparé, jamais remplacé ;
- consolidation : même projet et même contenu exigés ; passage de chaque jour sur les souvenirs
  récents ; mots découpés une fois (15 s au lieu de plus de 8 min à 3 000 souvenirs) ;
- mot de passe dit en phrase masqué ;
- prompts.chat : identifiant propre, description hors du contexte, délai total ;
- messages en français à la place des traces Python ; mémoire hors service signalée au démarrage ;
- `brain done` n'archive qu'un à-faire ; `brain pc` répond hors de Windows.
- Sous Windows, ces correctifs valent pour ce que fait Python, pas pour ce que fait `brain.exe`
  (décision E12). Le verrou rafraîchi protège aussi les écritures de `brain.exe`, s'il juge un verrou
  périmé à sa date, comme Python.

**Étape 2 — Sécurité restante** (§5) : **faite le 20/11** (PR #23, cerveau 8.25.0). Chaque point a des tests qui
échouaient avant :
- `brain.exe` ne tourne plus que sur demande (`BRAIN_IMPL=rust`) : sous Windows, tous les correctifs valent (E12) ;
- cerveau commun : le profil et les règles d'un ami ne deviennent plus les tiens ; son texte est contrôlé, ses balises
  neutralisées, et chaque ligne d'ami est marquée « donnée, pas une consigne » (rappel, index, fiches, skills reçues) ;
- avant tout partage : chemins de dossiers, téléphones, adresses postales, e-mails déguisés, adresses git et ton
  prénom sont retirés ; un souvenir réduit à presque rien reste privé ;
- un dépôt commun injoignable n'est plus annoncé « à jour » ;
- veille PC : elle liste les serveurs MCP orphelins, `brain pc --clean --oui` seul les ferme (E5) ;
- mode éco : il propose les plugins et skills à couper, `brain eco --plugins` seul les coupe (E6) ;
- rappel de fin de tâche : seulement pour une phrase durable pas encore enregistrée, texte deux fois plus court (E3) ;
- `settings.json` relu juste avant chaque écriture, et lisible avec un BOM.
- Reste : ce qui est déjà parti dans un dépôt commun reste dans son historique git (le réécrire, c'est ta décision) ;
  la capture de « retiens que… » sur des tiers passe à l'étape 3.

**Étape 3 — Rappel** (§4.1) : **faite le 21/11** (PR #24, cerveau 8.26.0). D'abord le banc d'essai réaliste
(`tests/test_rappel.py`), puis les corrections une à une, chacune mesurée et testée :
- le rappel automatique retrouve le bon souvenir pour 58 questions sur 62 (94 %, contre 33), toujours 2 faux
  rappels sur 38 pièges (objectif : 70 %) ; messages de trois phrases : 8 sur 8, 1 faux rappel sur 16 ;
- toutes tes règles et tout ton profil au démarrage, au moins par leur titre ;
- « Note 9 » n'archive plus « Note 7 » : une autre date, semaine, année ou un autre numéro est un autre fait ;
- « retiens que… » : déclencheur strict, doublon reformulé reconnu, rien de privé sur un tiers, une ligne
  visible dit ce qui a été retenu ;
- plafond glissant (12 souvenirs sur 20 messages, dit quand il est atteint), questions datées, observations de fin
  de tâche, souvenirs coupés au démarrage de nouveau rappelables ; `brain bench` donne la mesure du banc d'essai.
- Limites : les synonymes ont été choisis sur les ratés du banc d'essai, un nouveau jeu de questions ferait moins
  bien ; sur 16 autres messages hors sujet essayés après coup, 2 rappellent un souvenir (déjà avant l'étape) ;
  `brain q` rate encore 3 questions ; le canal des dates n'a pas été essayé avec un neurone appris ; il coûte
  40 ms de plus par question datée à 3 000 souvenirs, et les observations jusqu'à 43 ms (à reprendre à l'étape 4).

**Étape 4 — Vitesse** (§4.2) : **faite le 21/11** (PR #25, cerveau 8.27.0). Objectif : à 3 000 souvenirs, aucun
hook au-dessus de 150 ms, premier démarrage après un changement compris ; `brain add` sous 300 ms.
- Atteint : à 3 000 souvenirs, chaque hook prend de 26 à 92 ms, le démarrage juste après une écriture 134 ms
  (933 avant) ; `brain add` 165 ms (2,1 s avant). À 10 000, les hooks courants sont sous 190 ms (307 ms juste
  après une écriture) et `brain add` à 0,46 s.
- Les écritures : le graphe seulement ; une tâche de fond refait l'index, l'export et les vues une fois les écritures
  calmées ; les compteurs de rappel ne réécrivent plus graph.json.
- Le démarrage : l'analyse du graphe n'est plus calculée dans un hook ; l'index du démarrage est gardé tant que rien
  de ce qu'il montre ne change ; fin de session et résumé laissent le travail lourd à la tâche de fond.
- Le message : index des souvenirs, catalogue des skills, dates citées et observations gardés d'un message à
  l'autre ; modules chargés au premier usage. Le banc du rappel ne change pas (58/62, 2 faux rappels sur 38).
- Tests : `test_ecriture`, `test_demarrage` et `test_vitesse_message` (63 vérifications) comptent le travail fait
  au lieu de le chronométrer ; 51 sur 63 échouent sur l'ancien code, les 12 autres vérifient que ce qui doit rester
  pareil le reste (exports identiques, aucun cache périmé servi).
- Reste au-dessus de 150 ms : le tout premier démarrage dans un nouveau dossier (235 ms, une fois par dossier).
  Autres restes au §4.2 (graphe lu en entier à 10 000, vues refaites après chaque session, `brain q` après un
  changement). Le premier ajout après la mise à jour prend environ 1 s à 3 000 souvenirs (mots des souvenirs
  gardés une fois pour toutes).

**Étape 5 — Consommation** (§4.3) et regroupement des skills (§7.2) : **faite le 21/11** (PR #26, cerveau
8.28.0), avec tes décisions du 21/11 (regroupement comme proposé, E2, E8, outils MCP de la mémoire seulement).
- Injection du démarrage et outils MCP : −30 % ensemble (l'injection seule −12 à −17 %, voir le reste au §4.3).
- La liste des skills du cerveau tient dans sa place : 18 skills, 4 180 caractères au lieu de 29 758.
- « fais-moi un logo » et « scrape ce site » trouvent leur skill, comme 29 demandes typiques des anciennes skills ;
  « c'est impeccable » ou « film d'animation » n'en chargent aucune.
- Le réflexe des skills nomme enfin les plugins synchronisés depuis claude.ai comme l'outil Skill les nomme, et voit
  humanizer ; la description de la skill `brain` était du YAML invalide.
- Tests : `test_skills_regroupees` (155 vérifications, 54 échouent sur l'ancienne disposition) et
  `test_consommation` (44, dont 26 échouent sur la 8.27.0).
- Toi, si tu as aussi l'installation classique : `brain self-update --force` une fois (beaucoup de fichiers de skills
  disparaissent). Une skill de ton compte claude.ai reste à désactiver toi-même (§4.3).

**Étape 6 — Erreurs et messages** (§4.4), dont la décision E1 sur `python`.
- Fin : aucune trace Python dans les 400 cas d'essai des commandes ; `brain config` refuse une valeur
  fausse ; hooks qui tournent sur un Mac sans `python`.

**Étape 7 — Ne plus perdre de souvenir** (§6).
- Fin (tests) : graphe abîmé réparé sans perte des souvenirs de la dernière demi-heure ; wiki sur deux
  PC qui se resynchronise après un conflit ; aucune modification perdue avec Obsidian.

**Étape 8 — Regrouper** : souvenirs (`brain regroupe`), code (`cli.py`, `mapper.py`), défauts de la
carte de projets, branches (ton accord), visualisation 3D sans site extérieur.
- Fin : `brain regroupe` montre puis applique ; aucun fichier de plus de 1 000 lignes ; tests verts.

**Étape 9 — Documents** (§7.4) : archives, backlog trié, ADR, README, page des réglages.
- Fin : un seul plan, un backlog sans point mort, chaque réglage expliqué.

### Bloc B — Unifier la plateforme (plan v2, étapes 2 et 4 à 8)

- **Deux dépôts** (D3, D11) : toi, tu crées `cerveau-plateforme` et `mes-projets` et tu y pousses ta
  plateforme ; Claude reporte les changements faits ici, déplace les dossiers Fortnite, puis tu retires
  `plateforme/` du dépôt public. Puis D4 (historique public).
- **Le pont MCP** (fait, pas encore branché). La relecture de gouvernance n'a trouvé aucun moyen
  d'atteindre un outil interdit, et `proposer_action` n'a jamais répondu autre chose qu'un refus
  (28 cas sur 28). À corriger avant de le brancher, dans cet ordre :
  1. **`verifier` laisse passer des chiffres inventés** (R1) : 16 brouillons sur 21 qui devaient être
     refusés passent. Exemples : « 10'000'000 € » reconstitué à partir de trois morceaux pris
     ailleurs ; « 0 Md€ » ; un chiffre lu sur une page web présenté comme une VaR. À l'inverse, 7
     textes justes sur 18 sont refusés (la date du jour, « Étape 2 », tes propres chiffres).
  2. **Le journal d'audit garde les arguments en clair** (R6) : nom, adresse, IBAN, jeton dans une
     URL. Il doit n'en garder que les noms et des empreintes.
  3. Une entrée au journal pour chaque appel, refus et pannes compris (R11) ; une limite de temps au
     démarrage d'un plugin (un démarrage bloqué tenait l'appel plus de 37 s) ; le kill switch qui
     arrête aussi un appel en cours, et qui reste engagé si son dossier est remplacé par un fichier
     (R4) ; un plafond par session et par jour, et le contrôle du budget quotidien jamais appelé
     (R7) ; le texte des pages web marqué comme donnée (R5) ; les messages d'erreur sans chemins.
  4. Plus tard : `proposer_action` ne mène à rien (le résumé est perdu, son empreinte se devine) ; il
     faudra une file d'intentions hors de portée de Claude (étape de la chaîne d'approbation). Chaque
     appel lance un nouveau processus : 1,2 à 1,6 s pour un outil de 8 ms.
  - Puis tu le branches (`.mcp.json`, liste des outils de `guard_mcp.py`, ADR-069). Point à savoir : le
    pont dépend encore de `langchain_core`.
- **Une seule mémoire** : la plateforme lit celle du plugin ; `core/memory/` est vide aujourd'hui.
- **Réglages** : 42 fonctions bloquées ; Claude propose une valeur prudente par marqueur, tu fixes
  celles de gouvernance (courtier, capital, limites de perte, seuils d'autonomie, comptes à créer).
- **Une chaîne d'approbation** : B228 d'abord (le secret des codes à usage unique hors de portée de
  Claude), puis B353 (la porte du live lue depuis `live.yaml`).
- **Mesurer pour de vrai à 0 €** : les jeux de cas passés dans Claude Code, un autre modèle juge ; le
  jeu de cas passe de 37 à 300 (B62). Le test Docker du pack Code (B270) est à toi ; le bac à sable
  n'a pas encore de limite de temps (B282).

### Bloc C — Étendre (plan v2, étapes 9 à 14, inchangées)

Finance au niveau Aladdin ; contenu et vidéo (After Effects, rétention, réseaux) ; clients ; emploi et
CV ; PC Windows et réseau ; code et automatisation. Le détail est au §7 du plan v2. Ordre : décision D5.

### Bloc D — Durer (plan v2, étape 15)

Amélioration continue, puis N3 domaine par domaine. N4 reste hors du plan.

## 10. Décisions demandées

| # | Décision | Ma recommandation |
|---|---|---|
| E1 | `python` absent sur Mac et Linux | Un petit lanceur qui essaie python3, python puis py, essayé sur un Windows sans Git Bash avant de le livrer |
| E2 | Place des skills dans le contexte (mode éco : 0,5 %) | **Tranché le 21/11 : 0,5 % et `skillListingMaxDescChars` à 250** (étape 5) |
| E3 | Rappel de mémoriser en fin de tâche (hook Stop) | **Tranché le 20/11 : seulement quand une phrase durable a été dite, texte deux fois plus court** (étape 2) |
| E4 | Seuil du rappel (`min_cov`) | **Réglé par le banc d'essai de l'étape 3 : 0,5 reste**, 0,4 rappelait un mauvais souvenir |
| E5 | Veille PC qui ferme des processus | **Tranché le 20/11 : lister et proposer**, plus rien fermé sans ton accord (étape 2) |
| E6 | Plugins et skills désactivés tout seuls | **Tranché le 20/11 : te les proposer**, plus rien coupé sans ton accord (étape 2) |
| E7 | Sauvegarde sans second disque | Dans ton dossier personnel, avec un message une fois |
| E8 | Retirer les skills humanizer et vercel (tes plugins les ont déjà) | **Tranché le 21/11 : retirées** ; leurs phrases mènent aux skills de tes plugins (étape 5) |
| E9 | Code de la plateforme qui sert seulement avec un budget API (≈ 6 000 lignes) | Le mettre de côté dans une branche, pas le supprimer |
| E10 | prompts.chat actif par défaut | Le garder, maintenant que son texte est filtré ; le couper si tu ne t'en sers pas |
| E11 | Fusionner la PR des correctifs sûrs et publier 8.24.0 | **Fait le 20/11** |
| E12 | `brain.exe` (Rust 8.18.2) tant que son code source n'est pas dans le dépôt | **Tranché le 20/11 : Python partout, puis optimiser en Rust.** Fait : `brain.exe` ne tourne plus que sur demande (`BRAIN_IMPL=rust`), tous les correctifs valent sous Windows. Ensuite (D2) : tu ajoutes le code Rust au dépôt ; Claude y reporte les correctifs faits depuis la 8.18.2, l'optimise, et l'exe est construit en CI |

Toujours ouvertes depuis le plan v2 : D4 (ton nom dans l'historique public), D5 (ordre des domaines),
D6 (ta boutique), D7 (réseaux sociaux visés), D8 (canal des approbations), D9 (modèle local),
D12 (courtier), D13 (ADR-068).

## 11. Sur ton PC

Ces commandes ne changent rien (aucune option `--apply` ou `--appliquer`). Lance-les dans PowerShell et
colle-moi le résultat : elles donnent les vrais chiffres de ton cerveau sous Windows.

```powershell
python "$env:USERPROFILE\.claude\brain\brain.py" doctor
python "$env:USERPROFILE\.claude\brain\brain.py" bench
python "$env:USERPROFILE\.claude\brain\brain.py" tokens --hours 72
python "$env:USERPROFILE\.claude\brain\brain.py" context
(Get-Item "$env:USERPROFILE\.claude\brain\graph.json").Length
1..10 | % { (Measure-Command { python -I -S -c pass }).TotalMilliseconds }
git --version
```

Dans Claude Code : `/context` (ce que coûtent les skills et les outils) et `/doctor`.

## 12. Confiance et points à vérifier

- **Reproduit dans l'audit** (confiance élevée) : chaque ligne marquée « reproduit » en annexe.
- **Lu seulement** (confiance moyenne) : le comportement sous Windows (veille PC, verrous de fichiers,
  `brain.exe`), Git Credential Manager, les chemins Windows des skills.
- **Relecture de gouvernance du pont MCP** : faite par des essais (13 fichiers de tests, rejoués trois
  fois avec les mêmes résultats), sans les plugins de finance en vrai processus (ils auraient lu ta
  vraie base) ni sous Windows.
- `[VERIFICATION REQUIRED]` : le coût réel des skills et des outils MCP dans ta session (`/context`) ;
  le compte réel des tokens (le cerveau estime 2,2 caractères par token) ; les vitesses sous Windows.

## Annexe — Constats techniques

Référence pour les sessions qui feront le travail. R = rappel, A = cœur et hooks, B = commandes,
T = outils, S = partage, M = mesures, K = skills, G = pont MCP, P = plateforme. « rep. » = reproduit,
« lu » = lu.

**Rappel** — R-1 `search.py:573-583` filtre trop strict (rep., ✅) · R-2 `hooks.py:847-851` plafond de 12
(rep., ✅) · R-3 `cli.py:835`, `store.py:343` fusion entre projets (rep., ✅) · R-4 `index.py:131-138,
180-199` règles cachées (rep., ✅) · R-5 `hooks.py:600-690`, `privacy.py:28-29` capture « retiens » (rep.,
✅) · R-6 `hooks.py:1158-1164` rappel Stop après 15 appels (rep., ✅ étape 2) · R-7 `store.py:333-348`,
`reconcile.py:107-123` doublons reformulés (rep. ; ✅ pour « retiens… », pas encore pour `brain add`) · R-8
`cli.py:295-298` pas de regroupement (rep.) · R-9 `hooks.py:759`, `search.py:451-470` dates (rep., ✅) ·
R-10 `lexicon.py:13-56` synonymes (rep., ✅) · R-11 `common.py:418-421` racines (rep., ✅) · R-12
`bench.py:47-118` banc trop facile (rep., ✅) · R-13 `reconcile.py:119-121`, `dream.py:72-78` chiffres
différents = remplacement (rep., ✅) · R-14 observations jamais rappelées (rep., ✅) · R-15 `hooks.py:377`,
`index.py:302` (rep. en partie, ✅).

**Cœur et hooks** — A-1 `common.py:267-271` verrou repris (rep., ✅) · A-2 `hooks/hooks.json` `python`
(rep.) · A-3 `history.py:44`, `backup.py:123-143` réparation ancienne (rep.) · A-4 `store.py:198-199`
mauvaise forme (rep., ✅) · A-5 `hooks.py:1160-1188` blocage Stop (lu) · A-6 mémoire coupée sans le
dire (rep., ✅) · A-7 `cli.py:2407-2416` traces (rep., ✅) · A-8 `backup.py:25-37` sauvegarde Windows
seulement (rep.) · A-9 consolidation O(n²) (rep., ✅) · A-10 `hooks.py:1302-1304` (rep., ✅) · A-11
`common.py:262-276` lecture seule sous Windows (lu) · A-12/A-13 `mcp_server.py:163-191, 306` erreurs
et taille (rep.) · A-14 `compact.py:287-331`, `fiches.py:208` écritures sans verrou (lu) · A-15
`hooks.py:219-221` repère quotidien posé avant la tâche (lu).

**Commandes** — B-1 `pc.py:148` (rep., ✅) · B-2 `cli.py:1923-1927` config sans contrôle (rep.) ·
B-3 `done` sur un non-à-faire (rep., ✅) · B-4 `--body-file` absent (rep., ✅ par le message général) ·
B-5 `eco.py:738-842, 900-935` plugins coupés (lu) · B-6 `tokens.py:262-263, 329-338` plus de 100 %
(rep.) · B-7 `eco.py:259-321`, `install.py:453-455` settings.json (lu) · B-8 `delegation.py:68, 130`
tâches d'écriture envoyées à Haiku (rep.) · B-9 `selfupdate.py:30-52` (lu) · B-10 `install.py:430-435`
BOM (lu) · B-11 `eco.py:264, 322` (lu) · B-12 settings.json en JSONC (lu) · B-13 codes de sortie
(rep.) · B-14 `tokens.py:37` (rep.).

**Outils** — T-1 `promptlib.py:229-232` (rep., ✅) · T-2 `promptlib.py:117-129` (rep., ✅) · T-3
`importer.py:100` taille (rep.) · T-4 `pc.py:587-627` fermeture « mcp » (lu) · T-5 `pc.py:964-977`
(lu) · T-6 = B-1 · T-7 `mapper.py:1174-1190` paquet local (rep.) · T-8 `mapper.py:40-44` dossiers
ignorés (lu) · T-9 exports CommonJS (rep.) · T-10 `hooks.py:296-304`, `mapper.py:1794-1819` (lu) ·
T-11 `cli.py` ~1259 (rep., ✅ par le message général) · T-12 `mapper.py:941` (rep.) · T-13
`boutique.py:530-567` réseau malgré BRAIN_OFFLINE (rep.).

**Partage** — S-1 `wiki.py:385, 412-419` (rep.) · S-2 `commun.py:84`, `privacy.py:32-33` (rep.) ·
S-3 `commun.py:545-579` (rep.) · S-4 `wiki.py:367-389, 405-430` (rep.) · S-5 `vault.py:276, 301-307`
(rep.) · S-6 messages git (rep.) · S-7 `wiki.py:314-318` invites d'identifiants (lu) · S-8
`commun.py:417-437` (rep.) · S-9 `wikistore.py:114-117` noms réservés Windows (rep.) · S-10
`commun.py:622` (rep.) · S-11 `viz3d.py:8-20` (rep.) · S-12 un utilisateur sur deux PC (lu).

**Mesures** — M-1 `graph.py:297-306, 474-492` (✅) · M-3 exports à l'ajout (✅) · M-5 `store.py:571-577` (✅) ·
M-6 `search.py:227-247` (✅) · M-7 `index.py:295` (✅) · M-8 `hooks.py:1230-1241` (✅) · M-9 = A-5 · M-10
`hooks.py:443` · M-11 = A-13 · M-12 `search.py:239-275` (✅) · M-13 `hooks.py:14-19` (✅) · M-14 `brain context`
et `brain optimize` sous-estiment (rep.). Étape 4 : les ✅ du 21/11.

**Skills** — K-1 descriptions hors budget · K-2 `skills.py:214-215` déclencheurs dans les descriptions
· K-3 `skillListingMaxDescChars` · K-4 `skillOverrides` sans effet sur les skills d'un plugin · K-5
`skills.py:634` · K-6 `skills.py:544-546, 602` mots courts · K-7 à K-9 regroupements · K-10 skill
`brain` · K-11 `scrapegraph/SKILL.md:24, 39-47` · K-12 logo-design · K-13 `image-to-code/SKILL.md:63` ·
K-14 `brain/SKILL.md:22-27` · K-15 ancienne skill claude.ai.

**Pont MCP** — G-1 `core/verification/numbers.py:50-64, 91-109, 221-229`, `trace.py:139-141`,
`server.py:207` chiffres inventés acceptés (rep.) · G-2 `core/mcp/adapter.py:354, 438, 455`,
`server.py:198` arguments en clair au journal (rep.) · G-3 `server.py:175-200` refus non journalisés
(rep.) · G-4 `adapter.py:213-216` démarrage sans limite de temps (rep.) · G-5 `adapter.py:378` kill
switch et appel en cours (rep.) · G-6 `adapter.py:394-460` journal écrit après l'appel (rep.) · G-7
`server.py:181-192` aucun plafond, `BudgetGate` jamais appelé (rep.) · G-8 `server.py:204` texte web
rendu tel quel (rep.) · G-9 `verifier` facultatif, non journalisé (rep.) · G-10 faux refus (rep.) ·
G-11 deux plugins, même nom d'outil (rep.) · G-12 `core/policy/engine.py:126-132` kill switch ouvert
si son dossier est un fichier (rep.) · G-13 `server.py:215-248` `proposer_action` sans suite (rep.) ·
G-14 1,2 à 1,6 s par appel (rep.) · G-15 `adapter.py:436-438, 462` chemins dans les erreurs (rep.).

**Plateforme** — P-1 B228 · P-2 aucune mesure réelle (B60) · P-3 B353 · P-4 README et `cerveau ask` ·
P-5 `core/memory/` vide, B270 · P-6 42 fonctions bloquées · P-7 documents en retard · P-8 41 ADR
« proposé » · P-9 code LangGraph · P-10 B282 · P-11 pas de contrôle des types · P-12 5 blocs
dupliqués · P-13 fonctions complexes (`interfaces/api/app.py:96`) · P-14
`test_code_agent_server.py:929` sous l'administrateur · P-15 test de 72 s, avertissements Pandas
(B151).
