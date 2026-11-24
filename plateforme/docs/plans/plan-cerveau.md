# Plan du cerveau — le plan unique

Date : 20/11/2026, mis à jour le 24/11 · Remplace le plan v1 (`plan-parite-aladdin.md`) et le plan v2
(`plan-parite-aladdin-v2.md`), gardés dans `docs/archive/plans/` · Statut : **en cours** ; chaque étape attend ton GO,
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
   la consommation (8.28.0) : 18 skills au lieu de 33, démarrage et outils MCP −30 % ; étape 6 le 21/11, les erreurs
   (8.29.0) : plus aucune trace Python ni message en anglais dans les 400 cas d'essai des commandes ; étape 7 le 21/11, ne plus
   perdre de souvenir (8.30.0) : un graph.json abîmé se répare avec les souvenirs des dernières minutes, et le wiki
   sur deux PC ne se bloque plus au premier conflit ; étape 8 le 21/11, regrouper (8.31.0) : `brain regroupe` (doublons
   reformulés, souvenirs sans projet, fiches), aucun fichier du code au-delà de 1 000 lignes, vue 3D sans site extérieur ;
   étape 9 le 21/11, les documents (8.32.0) : un seul plan, backlog trié, chaque réglage expliqué.
6. **Attention, sous Windows.** `brain.exe`, la version Rust du cerveau, n'a pas changé depuis la
   8.18.2 du 10/11, et son code source n'est pas dans le dépôt. C'est lui qui exécute, sur ton PC, les
   hooks de session, le rappel, `done`, le verrou et le masquage des mots de passe. L'audit a mesuré
   et corrigé le code Python. Sur ton PC, ces correctifs et les améliorations Python faites depuis le
   10/11 ne valaient donc pas pour ces chemins. **Décision du 20/11 (E12) : Python partout** ; `brain.exe`
   ne tourne plus que sur demande, en attendant son code source, corrigé et optimisé.
7. **La suite** : 9 étapes pour le plugin (Réparer, Accélérer, Alléger, Regrouper), puis les étapes de
   la plateforme reprises du plan v2. Tes décisions sont au §10, les commandes à lancer sur ton PC au
   §11.
8. **Le cerveau en 4D** (24/11, Bloc E du §9). Ta synthèse demande un graphe de souvenirs daté, une mémoire
   par MCP et une vue 3D avec le temps. Le cerveau en a déjà la plus grande part : graphe à liens typés,
   « A remplace B » avec date de fin, PageRank, vue 3D avec curseur. Il reste quatre manques, donc quatre
   étapes (10 à 13) : les réglages Claude Code du dépôt, le temps dans le modèle de données, le rappel et
   les piliers, la vue 3D rejouable. Les quatre étapes sont faites le 24/11, sur Opus 5.5 (cerveau 8.36.0) : le Bloc E est terminé.

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
| 21/11 | Garder l'injection du démarrage ; étape 6 ; E1 : pas de lanceur Python | 8.28.0 fusionnée ; étape 6 faite (8.29.0) |
| 21/11 | Fusionner la 8.29.0 ; étape 7 ; E7 : sauvegarde dans ton dossier personnel | 8.29.0 fusionnée ; étape 7 faite (8.30.0) |
| 21/11 | Fusionner la 8.30.0 ; étape 8 ; supprimer les 15 vieilles branches | 8.30.0 fusionnée ; étape 8 faite (8.31.0) ; branches : la session n'a pas le droit de les supprimer, la commande est au §11 |
| 21/11 | Fusionner la 8.31.0 ; étape 9 ; garder l'ADR-013 (pas de yfinance) | 8.31.0 fusionnée ; étape 9 faite (8.32.0) |
| 23/11 | Valider les 7 retraits R9 ; relire d'abord les autres ADR | ADR-021, 046, 050, 057, 060 et 068 acceptés ; 35 ADR à relire (`docs/adr/A-VALIDER.md`) |
| 23/11 | Fusionner la 8.32.0 ; puis les restes du plugin | 8.32.0 fusionnée ; restes faits (8.33.0) : fin de session wiki en 88 ms, `brain regroupe` complété |
| 24/11 | Synthèse « cerveau en 4D » (graphe daté, mémoire par MCP, vue 3D avec le temps) ; « fais le plan et passe à Opus 5.5 » | Bloc E, étapes 10 à 13. Tes réponses du 24/11 : les quatre manques, reprendre les idées de Graphiti et mem0 sans les installer, rappel lexical avec filtre par date, tu changes le modèle toi-même |
| 24/11 | Passage sur Opus 5.5, « GO étape 10 » | Étape 10 faite : `CLAUDE.md` à la racine, hook de vérification en fin de tâche (E20 appliquée telle que recommandée) |
| 24/11 | « Go étape 11 » | Étape 11 faite (8.34.0) ; E19 et E21 appliquées telles que recommandées |
| 24/11 | « Continue le plan » | Étapes 12 (8.35.0, piliers livrés après mesure) et 13 (8.36.0) faites : Bloc E terminé |
| 24/11 | « Regarde chaque lien GitHub que je t'ai envoyé et mets dans le cerveau ce qui est utile » | Bloc F, étapes 14 à 19, en attente de ton choix |

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
| `python` absent (Mac, Ubuntu) : « hook error » à chaque message et après chaque commande | Décision E1 du 21/11 : **pas de lanceur** (mesuré sous Windows : +39 ms par hook avec Git Bash, +200 à +280 ms sans) ; les hooks gardent `python`, `brain doctor` vérifie le `python` des hooks et sa version, et un Python avant 3.10 est refusé par une ligne en français | M | 6 |
| « Stop hook feedback » : le cerveau bloque la fin d'une réponse pour rappeler de mémoriser | ✅ Seulement sur une phrase durable pas encore enregistrée (E3) | S | 2 |
| Traces Python en anglais : graphe illisible, dossier en lecture seule, fichier absent | ✅ Message en français avec la marche à suivre | S | 1 |
| `brain pc` plante sous Mac et Linux | ✅ Message clair | S | 1 |
| `brain config clé valeur` accepte n'importe quoi (« abc » pour un nombre), et une seule valeur fausse casse l'injection | ✅ Clé, type et bornes vérifiés avant d'écrire, avec un exemple ; une valeur fausse déjà enregistrée reprend son défaut, et tu en es prévenu une fois | M | 6 |
| Code de sortie 0 sur un échec (`deps`, `explain`, `echange voir`…), valeurs négatives acceptées | ✅ Code 1 et message clair (2 pour une commande mal écrite) | S | 6 |
| Messages de git bruts ou trompeurs (« ✓ à jour » quand le dépôt est injoignable) | ✅ Une phrase en français : ce qui s'est passé et quoi faire (wiki, publication) | S | 6 |
| Serveur MCP : erreurs en anglais ; une valeur qui commence par « - » est prise pour une option | ✅ Arguments vérifiés, réponses en français, jamais de trace Python | M | 6 |
| `brain tokens` plante sur une ligne de transcript sans compteur | ✅ Sautée | S | 6 |
| `brain publish` sans dossier reprend le dernier dossier retenu au lieu de publier sur place depuis le clone (vu le 20/11) | ✅ Depuis un clone du même dépôt : sur place, le dossier retenu seulement sinon | S | 6 |

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
| La visualisation 3D charge des scripts de trois sites, sans contrôle d'intégrité | ✅ Livrés avec le plugin (licence MIT, empreintes SHA-256), dans la page : elle s'ouvre sans connexion | 8 |
| Sans `commun.repo`, rejoindre le cerveau commun utilise le dépôt de l'auteur | À savoir avant de partager | — |

## 6. Ne plus perdre de souvenir

| Problème | État | Étape |
|---|---|---|
| Le verrou d'un travail long (consolidation, import) était repris au bout de 30 s : un souvenir annoncé « mémorisé » disparaissait | ✅ Le détenteur rafraîchit son verrou | 1 |
| Un graph.json au bon format JSON mais à la mauvaise forme était remplacé par un cerveau vide, sans copie | ✅ Réparé comme un fichier abîmé, l'original gardé | 1 |
| Mémoire hors service (graphe illisible, dossier en lecture seule) sans rien dire | ✅ Un message au démarrage | 1 |
| Réparation d'un graph.json abîmé depuis un instantané qui peut dater de 30 min : les souvenirs récents disparaissent | ✅ Version d'avant chaque écriture gardée (un lien, 0,1 ms), écritures récentes notées, souvenirs lisibles du fichier abîmé repris ; un message avec les nombres | 7 |
| Sauvegarde automatique seulement sous Windows avec un second disque | ✅ Sans second disque (ou hors Windows) : `~/Sauvegardes-cerveau-Claude`, annoncé une fois (E7) | 7 |
| Wiki sur deux PC par git : bloqué pour de bon dès le premier conflit sur `index.md` | ✅ `index.md` hors de git ; `log.md` fusionné ; une page changée sur les deux PC : la version de GitHub en place, l'autre en copie à côté | 7 |
| Wiki : un verrou git oublié bloque tout envoi, alors que l'écran dit « ✓ » | ✅ Verrous de plus de 2 min retirés ; une étape ratée n'affiche plus ✓ (code 1, dite au démarrage) | 7 |
| Synchro avec un coffre Obsidian : une modification faite dans le cerveau se perd si la note a été touchée après | ✅ Les deux côtés ont changé : le plus récent en place, l'autre dans `Conflits/` | 7 |
| Mise à jour automatique (`self-update`) : une copie à moitié faite n'est pas annulée | ✅ Retour arrière sur toute erreur, Ctrl+C compris ; rien touché si la copie de sûreté échoue | 7 |

## 7. Regroupement

### 7.1 Les souvenirs

- ✅ La consolidation ne fusionne plus deux projets (étape 1).
- Les doublons reformulés ne sont jamais vus : les 7 paires plantées obtenaient 0,11 à 0,39 de
  similarité, pour un seuil de 0,6 à 0,9. ✅ `brain regroupe` cherche les candidats par l'index de recherche : 6 paires
  sur 7 trouvées, aucune fausse (étape 8).
- 40 souvenirs sur 209 n'ont pas de projet. ✅ `brain regroupe` propose le projet quand deux indices concordent et
  qu'aucun ne contredit : 4 sur 5 rattachés, aucun souvenir vraiment général rattaché à tort. Il propose aussi des
  fiches (sujets cités par 3 à 12 petits souvenirs), montre d'abord, puis applique ce que tu choisis
  (`--appliquer 1,3`), instantané pris avant (étape 8).

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

- ✅ Découpés, tests d'abord, sans changer le comportement (étape 8) : `cli.py` (8 modules), `mapper.py` (7),
  `wiki.py` (5), `hooks.py` (5), `eco.py`, `pc.py`, `commun.py` et `echange.py` (3 chacun), `skills.py` (2) ; aucun
  fichier au-delà de 1 000 lignes. `hooks.on_session_start` se lit en sept étapes nommées.
- ✅ Carte de projets (étape 8) : paquet local compté comme externe ; dossiers `build/`, `env/`, `out/` ignorés à toute
  profondeur ; `exports.x =` non indexé ; un changement dans la même seconde pas vu. Sur ce dépôt, 2 839 liens au lieu
  de 506.
- Deux dépôts (D3) et les dossiers Fortnite à part (D11) : toujours en attente de tes dépôts privés.
- 15 branches à supprimer : rien ne manque à `main`. Ton accord le 21/11 ; la session n'a pas le droit de supprimer une
  branche sur GitHub (refus 403) : la commande est au §11.
- Plateforme : environ 6 000 lignes servent seulement au chef d'orchestre LangGraph, inutilisable à
  0 € (décision E9). 5 blocs dupliqués entre plugins (client HTTP, arguments Docker).

### 7.4 Les plans et les documents

- **Ce fichier est le seul plan à jour.** Les plans v1 et v2, les plans de phase et les comptes rendus sont dans
  `docs/archive/` (étape 9) ; les nouveaux comptes rendus vont toujours dans `docs/rapports/`.
- ✅ Fait (étape 9) :
  - backlog : 16 points fermés (14 sans objet avec 0 € d'API, B14 et B56 déjà faits), 8 fusionnés dans le plus petit
    numéro (B297, B264, B282, B168) ; B43, B47, B95, B104 et B258 restent ouverts (ils valent encore pour le pont
    MCP, ou attendent ta décision) ; chaque point ouvert nomme son étape suivante ou ce qui le bloque ;
  - ADR : ADR-002 marqué modifié par ADR-069 ; ADR-013 fait foi (ta décision du 21/11), le plan v2 corrigé : BCE,
    tes exports CSV, puis une API officielle que tu choisis ; FRED utilisable sous ses conditions (clé gratuite,
    mention obligatoire, séries « Copyright » à usage personnel), par un ADR qui l'ajoutera ;
  - mission de `CLAUDE.md` réécrite (Claude Code dirige par le pont MCP, LangGraph en place sans tourner) ; règles
    et interdits inchangés ;
  - un vrai README pour la plateforme.
- **Toi** : les 7 retraits R9 validés le 23/11 (ADR-021, 046, 050, 057, 060, 063 et 068). Restent 35 ADR
  « proposé » à relire, une ligne chacun dans `docs/adr/A-VALIDER.md` : réponds en une fois (« tout validé », ou
  les numéros à revoir).

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
- **107 réglages, 99 sans explication** : `brain config` vérifie les valeurs (étape 6). ✅ Étape 9 : une page générée
  depuis le code les explique tous (124 entrées, dont 17 tenues par le cerveau) : `brain config --page`, et
  `skills/brain/references/reglages.md` que Claude lit à la demande.
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

**Étape 6 — Erreurs et messages** (§4.4) : **faite le 21/11** (PR #27, cerveau 8.29.0).
- Les 400 cas d'essai des commandes de l'audit : plus aucune trace Python, aucun échec avec le code 0, aucun message en
  anglais (sur la 8.28.0 : 17 échecs avec le code 0 et 33 messages en anglais) ; `tests/test_erreurs.py` en rejoue 80.
- `brain config` refuse une clé inconnue, un mauvais type ou une valeur hors bornes ; une valeur fausse déjà enregistrée
  n'empêche plus le démarrage.
- Messages de git, du serveur MCP, du réseau et du système en français ; `brain tokens`, `brain publish` corrigés ;
  `brain q` et le serveur MCP prennent l'analyse en cache comme les hooks.
- Hooks sur un Mac sans `python` : **non** (ta décision E1 du 21/11, après la mesure du lanceur sous Windows). Un Mac ou
  un Linux sans `python` crée l'alias ; `brain doctor` et le README disent comment.
- Corrigé au passage pour Python 3.10 et 3.11 : messages d'argparse traduits, outils MCP de la boutique.

**Étape 7 — Ne plus perdre de souvenir** (§6) : **faite le 21/11** (PR #28, cerveau 8.30.0), avec ta décision E7.
- graph.json abîmé (coupé au milieu, octets en trop, mauvaise forme) : réparé à partir de la version d'avant la dernière
  écriture, des écritures notées depuis (`history/recents.jsonl`, 1 Mo au plus) et de chaque souvenir encore lisible
  dans le fichier abîmé. Les souvenirs ajoutés depuis le dernier instantané restent ; le fichier abîmé est gardé à
  côté ; tu l'apprends une fois au démarrage, avec les nombres. Un instantané compressé à chaque écriture aurait coûté
  146 ms à 10 000 souvenirs : la version d'avant est gardée par un lien (0,1 ms). `brain add` : 411 → 414 ms à 10 000
  souvenirs, 157 → 163 ms à 3 000 ; hooks inchangés.
- Sauvegarde : sous Windows le second disque reste le premier choix ; sinon `~/Sauvegardes-cerveau-Claude`, annoncé une
  fois. Sous Mac et Linux, la sauvegarde du jour échouait sans rien dire : elle tourne.
- Wiki sur deux PC : `index.md` (et les pages régénérées) hors de git, `log.md` fusionné des deux côtés ; une page changée
  sur les deux PC garde la version de GitHub, celle de ce PC est posée à côté (« Titre (conflit PC 2026-11-21 14h05).md »),
  non lue comme souvenir, dite au démarrage suivant et dans `brain wiki status`. Verrous git oubliés retirés ; plus de
  « ✓ » pour un commit ou un envoi raté.
- Coffre Obsidian : une note changée des deux côtés garde les deux versions (le plus récent en place, l'autre dans
  `Conflits/`).
- `self-update` revient en arrière sur toute erreur ; si le retour arrière lui-même échoue, le message dit où est la copie.
- Tests : `test_pertes` (80 vérifications, 48 échouent sur la 8.29.0) et `test_wiki_conflits` (46, deux PC et un faux
  GitHub ; 24 échouent sur la 8.29.0).
- Restes : `journal/AAAA-MM.md` du wiki est refait par chaque PC depuis ses propres sessions, GitHub garde le mois écrit
  en dernier (rien ne se perd sur les PC, rien ne bloque) : un journal par PC, à l'étape 8. Une suppression définitive
  faite juste avant qu'un graph.json s'abîme peut revenir si sa ligne d'écriture manque : un souvenir revenu plutôt
  qu'un souvenir perdu.

**Étape 8 — Regrouper** : **faite le 21/11** (PR #29, cerveau 8.31.0).
- `brain regroupe` (§7.1) : sur le monde de l'audit (209 souvenirs), 6 doublons reformulés sur 7, 4 rattachements sur 5,
  4 fiches, aucune fausse proposition. Le souvenir gardé reçoit les textes, liens, compteurs et dates des deux ; l'autre
  est archivé, son titre devient un mot-clé. 2,6 s à 10 000 souvenirs (6 s la première fois). `brain consolidate`
  fusionne maintenant de la même façon.
- Code (§7.3) : plus aucun fichier au-delà de 1 000 lignes (le plus gros : 997). Chaque découpage a d'abord été figé par
  des tests : 240 commandes, 90 étapes de hooks et 253 sorties du wiki, du cerveau commun et de l'échange de skills,
  identiques à l'octet avant et après. Hooks aussi rapides (ou un peu plus : `brain --version` 43 → 35 ms, démarrage
  en mode wiki 137 → 129 ms).
- Carte de projets : les quatre défauts corrigés ; la première carte après la mise à jour relit chaque fichier une fois.
- Vue 3D : 3d-force-graph 1.80.0 et three 0.183.0 (MIT) dans la page, plus aucun site extérieur ; la page pèse 1,9 Mo.
  Corrigé au passage : un souvenir contenant `<!--` puis `<script` pouvait casser la page.
- Journal du wiki : un dossier par PC (`journal/<PC>/AAAA-MM.md`), les anciens mois rangés dans `journal/ancien/` ;
  `brain q` et la page Cerveau d'Obsidian lisent les sessions de tous les PC.
- Tests : `test_regroupe` (53), `test_carte` (64, dont 24 échouent sur la 8.30.0), `test_vue3d` (51),
  `test_commandes` (471), `test_hooks_situations` (37), `test_decoupage` (43), `test_wiki_conflits` (60) ; 34 scripts.
- Restes : 15 branches à supprimer de ton PC (§11). ✅ Faits le 23/11 (cerveau 8.33.0, ta demande « les restes du
  plugin ») :
  - en mode wiki, la fin de session passe de 364 à 88 ms (budget 150) : `index.md`, la page Cerveau d'Obsidian et sa
    carte se refont en arrière-plan (presque tout le temps partait dans le contrôle complet du wiki de la page
    Cerveau). Le journal de la session, la page du mois de ce PC et l'entrée de `log.md` restent écrits avant la fin
    du hook ; les pages refaites suivent environ une seconde après ;
  - `brain regroupe` propose des fiches pour tous les sujets de l'analyse, plus seulement les 40 plus gros ; il
    retrouve la paire « Rythme de publication » / « Calendrier de sortie » (synonymes « rythme, cadence,
    calendrier ») : 7 doublons plantés sur 7, toujours aucune fausse proposition. « Idée : kits de bricolage » reste
    sans projet, exprès : un indice contraire existe (Shopify, cité par la boutique), et la note parle d'une autre
    boutique.

**Étape 9 — Documents** (§7.4) : **faite le 21/11** (PR #30, cerveau 8.32.0), avec tes décisions du 21/11 (ADR-013) et du
23/11 (retraits R9).
- Un seul plan à jour ; plans de phase, plans v1 et v2 et comptes rendus rangés dans `docs/archive/` (historique git
  gardé).
- Backlog sans point mort : 16 points fermés, 8 fusionnés, chaque point ouvert dit ce qui vient ensuite.
- ADR-002 et ADR-013 mis à jour ; `CLAUDE.md` (mission seulement) et un README pour la plateforme.
- Page des réglages : 123 réglages expliqués et 17 entrées tenues par le cerveau, générée depuis le code (aucune dérive
  possible : `test_page_reglages`, 46 vérifications) ; `brain config --page [clé]`. Rien au démarrage de session.
- Reste à toi : relire les 35 ADR de `docs/adr/A-VALIDER.md`.

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

### Bloc E — Le cerveau en 4D (plugin, étapes 10 à 13)

Ta demande du 24/11 : un cerveau « en 4D », c'est-à-dire un graphe de souvenirs (les trois dimensions) où chaque
souvenir et chaque lien porte ses dates (la quatrième). Plan écrit le 24/11. L'exécution se fait sur Opus 5.5 :
une étape par PR, chacune après ton GO. Ce bloc ne dépend pas des blocs B à D ; il peut passer avant.

**Pour reprendre** (toi, puis le modèle qui exécute) : passe la session sur Opus 5.5 (sélecteur de modèle, ou
`/model`), puis écris `GO étape 10`. Le modèle lit ce bloc, les décisions E16 à E21 du §10 et les fichiers cités
dans l'étape, écrit un complément de plan si un point reste flou, puis code.

**E.1 Ce que le cerveau a déjà.** Lu dans le code de la 8.33.0 le 24/11, sans essai. La plus grande part de ta
synthèse est en place ; le plan ne traite que la colonne de droite.

| Ta synthèse demande | Le cerveau 8.33.0 | Ce qui manque |
|---|---|---|
| Un graphe d'entités et de liens | 13 types de souvenirs, 8 types de liens (`store.py`) | rien |
| Une fin de validité, l'historique gardé | `brain supersede` archive l'ancien avec sa date de fin (`valid_to`) et son remplaçant | pas de date de début distincte de la date d'enregistrement ; pas de fin posée à l'avance (« vrai jusqu'au 31/12 ») ; un lien retiré est effacé, pas daté |
| Interroger le passé | `brain q --at` relit un instantané de `graph.json` (`history.state_at`) | 60 instantanés gardés : plus loin, la commande répond « pas d'état connu » |
| Pourquoi B a remplacé A | le lien `supersedes` | la raison n'est notée nulle part |
| Les axes domaine et abstraction | type, projet, étiquettes, communauté | ni domaine ni niveau d'abstraction |
| Fraîcheur et réactivation | `usage()` (utilisé sur montré, atténué sur 45 jours) et `priority()` (`store.py`) | rien ne fait revoir un souvenir important qui ne sert plus |
| Les nœuds centraux comme piliers | PageRank et « nœuds clés » (`graph.py`), utilisés par les fiches et `brain graph` | l'injection du démarrage trie par `priority()` seul (`index.build_index`) : la centralité n'y compte pas |
| Une recherche qui filtre par date et statut | rappel lexical ; un souvenir archivé n'est pas rappelé | pas de filtre sur les dates de validité elles-mêmes |
| La consolidation en fin de session | hook Stop, puis le rêve chaque jour (`dream.py`) | rien |
| La mémoire par MCP | serveur MCP du plugin, 6 outils de mémoire | pas de date dans `memory_search` |
| Une vue 3D avec curseur de temps | `cerveau.html` : 3d-force-graph intégré, curseur et lecture ▶ | le curseur cache seulement les souvenirs pas encore créés ; les souvenirs archivés ne sont pas dans la page ; les liens n'y ont pas de date |
| CLAUDE.md, hooks, permissions | `.claude/settings.json` (14 interdits, 2 hooks), `plateforme/CLAUDE.md` | pas de `CLAUDE.md` à la racine pour le plugin ; aucune vérification en fin de tâche |
| Skills à chargement progressif, sous-agents, CI | 18 skills, 3 agents, CI sur trois systèmes | rien |

**E.2 Hors du plan**, d'après tes réponses du 24/11 :
- Graphiti, mem0 et toute base de graphe (E16) : ils demandent Neo4j ou FalkorDB et des appels payants à un
  modèle. Le plan reprend leurs deux idées utiles, la double datation et le lien daté au lieu d'effacé.
- Les embeddings (E17) : le rappel reste lexical.
- La revue de code par Claude dans la CI : pas demandée.
- Les quatre dépôts de guides et de skills que tu cites n'ont pas été lus pour ce plan. L'étape 10 lit les deux
  guides et ne reprend que ce que la documentation de Claude Code confirme.

**E.3 Règles des quatre étapes.**
- Zéro dépendance : bibliothèque standard seule, le plugin tourne toujours en `python -I -S`.
- Aucune migration ne réécrit tes souvenirs : un champ absent prend sa valeur déduite à la lecture. Un
  `graph.json` de la 8.33.0 se charge tel quel, et une 8.33.0 qui lit un graphe plus récent (un ami du cerveau
  commun, ton second PC) ne casse pas. Chaque étape le prouve par un test.
- En mode wiki, tout nouveau champ fait l'aller-retour entre la page et le graphe (`wikistore.py`), avec une clé
  française dans les propriétés.
- Les budgets de la 8.33.0 tiennent : chaque hook sous 150 ms à 3 000 souvenirs, texte du démarrage et liste des
  outils MCP pas plus longs (`test_consommation`), rappel à 58 questions sur 62 au moins (`test_rappel`), aucun
  fichier au-delà de 1 000 lignes (`test_decoupage`). `search.py` en a 997 : il se découpe avant de grossir.
- Chaque changement a un test qui échoue sans lui. Une version mineure par étape ; README et page des réglages à
  jour. `brain.exe` n'est pas touché (E12).

**Étape 10 — Les réglages Claude Code du dépôt** (rien de livré aux utilisateurs du plugin) : **faite le 24/11**
(PR #32, avec ce bloc). Détail plus bas, après le plan de l'étape.
- Un `CLAUDE.md` à la racine, 60 lignes au plus : ce qu'est le dépôt (le plugin à la racine, la plateforme à part
  avec son propre `CLAUDE.md`), les commandes (le lint de la CI, un script de test, tous les scripts), les règles
  E.3, les interdits (`brain.exe`, les bibliothèques de `brainkit/vue3d/` refaites par `fabriquer.py` seulement),
  la façon de publier une version.
- La vérification en fin de tâche (E20) : un hook Stop, `.claude/hooks/verifier.py`. Si des fichiers du plugin ont
  changé depuis son dernier passage vert, il lance le lint et les scripts de test qui portent sur les fichiers
  touchés, plus `test_decoupage`. Un échec rend la main à Claude avec la sortie ; sans changement, le hook ne dit
  rien. Tous les scripts restent lancés par la CI. Modèle à suivre : `plateforme/.claude/hooks/quick_checks.py`.
- Aucun interdit de `.claude/settings.json` n'est retiré ni assoupli.
- Fini quand : le hook a son test (échec simulé, rien de changé, hors du plugin) ; une session neuve à qui tu dis
  « lance les tests du rappel » trouve la commande sans chercher.
- ✅ Fait le 24/11 :
  - `CLAUDE.md` à la racine, 59 lignes : carte, commandes, « quel test pour quoi », règles E.3, interdits, publier
    une version. Trouvé en le rédigeant : `README.md`, `hooks/hooks.json`, les manifestes et toute la skill
    `skills/brain/` sont générés par `brainkit/publish.py` ; le `CLAUDE.md` dit de changer le code qui les écrit.
  - `.claude/hooks/verifier.py`, déclaré en hook Stop dans `.claude/settings.json` (aucun interdit retiré). Il
    compare le dossier de travail à `main`, ne revérifie que les fichiers changés depuis son dernier passage vert
    (état dans le dossier `.git`, jamais commité), lance le lint de la CI et les scripts qui portent sur ces
    fichiers (imports, famille du module, chemins cités ; à défaut, le noyau), plus `test_decoupage`, quatre à la
    fois. Un échec renvoie Claude avec la ligne ✗ et la commande à relancer ; le même échec n'est pas renvoyé deux
    fois (tu es prévenu une fois) ; trois renvois au plus par tour. À la main : `--tout` (pas `--force`, que le
    garde-fou des commandes refuse).
  - Mesures (Linux, 4 cœurs) : rien de changé, 0,17 s ; `search.py` changé, 7 scripts ; pire cas (`common.py`),
    30 scripts en 55 s au lieu d'environ 3 min 20 l'un après l'autre, sans échec en parallèle.
  - Tests : nouveau `tests/test_verifier.py` (32 vérifications, sur un faux dépôt git). Une session neuve (Haiku,
    sans outil de recherche) à qui « lance les tests du rappel » a été dit a lancé `python tests/test_rappel.py`
    du premier coup.
  - Les deux guides (claude-code-ultimate-guide, claude-code-best-practices) ont été lus par un agent et comparés
    à la documentation de Claude Code. Retenu parce que la documentation le confirme : des commandes concrètes dans
    `CLAUDE.md`, moins de 200 lignes, une règle qui doit tenir passe par un hook ou un interdit (le `CLAUDE.md`
    n'est qu'un conseil), un hook Stop qui lance les tests. Le reste n'a pas été repris.

**Étape 11 — Le temps dans le modèle de données** (cerveau 8.34.0) : **faite le 24/11** (PR #32). Détail après le
plan de l'étape.
1. *Début et fin de validité.* `meta.valid_from` : le jour où le fait est devenu vrai ; absent, c'est la date
   d'enregistrement. `brain add --depuis 01/09`, `brain edit --depuis … --jusqu 31/12`. Une fin posée à l'avance
   laisse le souvenir actif jusque-là ; le rêve l'archive le lendemain. Dans le wiki : propriétés `debut` et `fin`.
2. *Liens datés.* Un lien retiré (`brain unlink`, lien disparu d'une page du wiki, fusion de doublons) reçoit une
   date de fin au lieu d'être effacé. `Brain.edges` ne rend que les liens vivants, donc ses 38 usages dans 11
   fichiers gardent leur sens ; `Brain.all_edges` rend tout. La suppression définitive d'un souvenir efface
   toujours ses liens. En mode wiki, l'endroit où garder un lien terminé est la décision E21.
3. *Le pourquoi.* `brain supersede <nouveau> <ancien> --parce-que "…"`, et la même option sur
   `brain add --replaces`. La raison est gardée sur le lien. `brain show` affiche la lignée :
   « C (depuis le 24/11) ← B (du 01/10 au 24/11, parce que …) ← A ».
4. *Les deux axes.* `store.axes(souvenir)` rend un domaine et un niveau, déduits et corrigeables.
   Niveau, quatre valeurs : vision (projet, profil), architecture (décision, concept, sujet, analyse), procédure
   (règle, apprentissage), détail (fait, référence, entité, à-faire, source) ; `--niveau` le corrige.
   Domaine : porté par le projet (`brain proj … --domaine`), hérité par ses souvenirs ; liste à la décision E19.
5. *Le passé sans instantané.* Hors de la fenêtre des 60 instantanés, `brain q --at` reconstruit l'état d'après
   les dates (souvenir : début ≤ jour < fin ; lien : création ≤ jour < fin) et le dit : « reconstruit d'après les
   dates ; le texte des souvenirs est celui d'aujourd'hui ». `memory_search` reçoit `at`, si la liste des outils
   MCP ne s'allonge pas.
- Fichiers : `store.py`, `cli.py`, `cli_memoire.py`, `wikistore.py`, `history.py`, `search.py`, `dream.py`,
  `mcp_server.py`, `bench.py`, `skills/brain/references/memoire.md`.
- Tests : nouveau `tests/test_temps.py` ; `test_wiki` (aller-retour), `test_commandes`, `test_consommation`.
- Fini quand : un graphe 8.33.0 se charge sans être réécrit ; un lien terminé n'est vu que par la lignée, `--at`
  et la vue ; sur un cerveau d'essai, `brain q --at` répond pour une date vieille de six mois.
- Risque principal : une lecture qui verrait un lien terminé fausserait le PageRank, les communautés et les
  fusions. Paré par `Brain.edges` filtré et par un test sur chaque module qui lit les liens.
- ✅ Fait le 24/11 (cerveau 8.34.0), dans un nouveau module `brainkit/temps.py` (191 lignes) :
  - *Le risque principal est écarté autrement, et plus sûrement.* Les liens terminés ne sont pas dans `edges` avec
    une date de fin : ils sont dans une liste à part, `ended_edges`. `Brain.edges` reste la liste des liens vivants,
    sans filtre ; ses 38 usages ne changent pas et ne peuvent pas voir un lien terminé. `graph.json` s'écrit en
    entier : une 8.33.0 ignore cette liste et la garde (essayé avec le vrai code de la 8.33.0, tiré de git).
  - Début et fin : `--depuis` (la date la plus proche, passée ou future : « depuis le 01/09 » dit le 24/11 est le
    01/09 passé) et `--jusqu` sur `add` et `edit`. La fin est le dernier jour vrai, comprise : un souvenir est
    valable du début à la fin incluse ; un lien, de sa création au jour où il est retiré. Une fin avant le début est
    refusée avant toute écriture. Une fin passée posée par `edit` archive tout de suite ; l'entretien du jour archive
    les autres le lendemain.
  - Liens terminés : `brain unlink` et un `[[lien]]` retiré à la main d'une page du wiki (repéré en comparant avec le
    cache, puis écrit dans la page à l'écriture suivante). Écart avec le plan : une fusion de doublons ne termine
    pas de lien, elle reporte les liens de l'archivé sur le gardé ; ne disparaissent que les doublons et les boucles,
    dont l'information reste dans le lien gardé. La suppression définitive emporte aussi les liens terminés.
  - La raison : `--parce-que` sur `supersede` et `add --replaces`. Écart avec le plan : elle est gardée sur l'ancien
    souvenir (`meta.end_reason`, propriété `raison_fin` du wiki) plutôt que sur le lien : c'est la raison de sa fin,
    et elle fait l'aller-retour du wiki sans format nouveau. `brain show` donne la lignée et « valable du … au … ».
  - Axes : `temps.axes` ; niveau déduit du type, `--niveau` le corrige. Domaine : le `--domaine` libre qui existait
    déjà (pages du wiki) sert d'axe, posé sur le souvenir ou hérité de son projet (`brain edit <projet> --domaine
    code`) ; pas d'option `brain proj --domaine`. La liste d'E19 est proposée dans l'aide, pas imposée.
  - Le passé sans instantané : `brain q --at`, avant le premier des 60 instantanés, reconstruit d'après les dates et
    le dit. `memory_search` reçoit `at` ; la liste des outils MCP reste à 3 204 caractères (des mots retirés
    ailleurs). Corrigé au passage, un défaut ancien : `--at 15/10` visait le 15/10 de l'an prochain.
  - Mode wiki : propriétés `debut`, `raison_fin`, `niveau`, `anciens_liens` (« relation · id · créé → retiré », en
    texte : Obsidian ne les dessine pas comme des liens vivants). Le `CLAUDE.md` des wikis n'en parle pas : son texte
    est tenu par une empreinte de `test_decoupage`, relevée avant le découpage, que je n'ai pas voulu changer ; elles
    sont expliquées dans `references/memoire.md` de la skill /brain.
  - Tests : nouveau `tests/test_temps.py` (49 vérifications), dont la 8.33.0 qui lit, écrit et garde un graphe
    récent, et un cache du wiki refait depuis les seules pages. Les 37 scripts passent.

**Étape 12 — Rappel et piliers** (cerveau 8.35.0, après l'étape 11) : **faite le 24/11** (PR #32). Détail après le
plan de l'étape.
1. *Filtre par validité.* Le rappel automatique et `brain q` écartent un souvenir pas encore valable ou échu,
   même encore actif ; `--archived` le montre.
2. *Souvenirs en conflit.* Deux souvenirs actifs liés par `contradicts` et rappelés ensemble : le plus récent
   passe devant et la ligne dit « contredit … ».
3. *Piliers au démarrage.* La centralité, déjà calculée, entre dans l'ordre de tri de l'injection du démarrage, à
   nombre de caractères égal. C'est une hypothèse : si le banc d'essai ne montre pas les nœuds clés de chaque
   projet dans l'injection, ou si le rappel descend sous 58 sur 62, ce point n'est pas livré.
4. *Réactivation.* Un souvenir d'importance 4 ou 5 qui n'a pas servi depuis 30 jours entre dans le dossier du
   rêve, section « À revoir ». L'archiviste le tranche au démarrage suivant : toujours vrai (la date est notée et
   le délai double : 30, 60, 120 jours…), corrigé, ou archivé. Trois par jour au plus ; rien dans la conversation.
- Fichiers : `search.py`, `hooks_message.py`, `index.py`, `dream.py`, `store.py`.
- Tests : `test_rappel`, `test_demarrage`, `test_consommation`, `brain bench` avant et après.
- ✅ Fait le 24/11 (cerveau 8.35.0) :
  - `search.py` découpé d'abord : le filtre d'acceptation du rappel part dans `search_filtre.py` (127 lignes), réexporté
    sous les mêmes noms ; `search.py` passe de 997 à 894 lignes.
  - Filtre par validité (`search.valid_today`) : rappel automatique, `brain q`, question datée et voisins du graphe.
    Un souvenir sans date écrite n'est pas regardé (coût nul). Trouvé en l'écrivant, un défaut de l'étape 11 corrigé :
    un remplacement repoussait à aujourd'hui une fin déjà écrite et passée.
  - Contradictions (`temps.contradictions`) : dans le rappel automatique et dans `brain q`, le plus récent passe juste
    devant, l'autre reçoit « ⚠ contredit par … ».
  - Piliers : **livrés**, la mesure ayant tenu les deux critères. Poids de la centralité 10 (`index.PILLAR_W`), dans
    l'index et dans la fiche du projet. Mesuré sur le cerveau du banc du rappel, avec le vrai hook de démarrage depuis
    chaque projet : les 3 souvenirs les plus centraux de chaque projet sont à l'écran 11 fois sur 15 au lieu de 9
    (10, 20 ou 30 donnent pareil), pour un peu moins de texte (24 533 caractères au lieu de 24 961) ; rappel inchangé
    (58/62, mêmes faux rappels). Temps du démarrage à 3 000 souvenirs : hors projet inchangé (≈ 95 ms), dans un projet
    100 ms au lieu de 88 (l'analyse en cache est lue une fois de plus) ; budget 150.
  - Revue espacée (`temps.to_review`) : section « À revoir » du rêve, trois au plus ; `brain edit <id> --revu` note la
    date et double le délai (30, 60, 120… 480 j). Écart avec le plan : c'est le rêve habituel qui la présente (le
    même dossier que les doublons et les conflits), pas un passage à part de l'archiviste.
  - Tests : `tests/test_temps.py` passe à 68 vérifications (étape 12 : validité, contradictions, revue, piliers,
    fin déjà passée gardée). Les 37 scripts passent.

**Étape 13 — La vue 3D rejouable** (cerveau 8.36.0, après l'étape 11) : **faite le 24/11** (PR #32). Détail après
le plan de l'étape.
1. *Données.* `viz.render` ajoute aux souvenirs leur début et leur fin, aux liens leur création et leur fin, la
   raison d'un remplacement, le domaine et le niveau, et les souvenirs archivés qui ont une date de fin (les
   2 000 plus récents au plus). Le poids de la page est mesuré avant et après.
2. *Le curseur montre le passé.* À une date, un souvenir est visible entre son début et sa fin, un lien entre sa
   création et sa fin. Curseur à droite : la vue d'aujourd'hui, identique à celle de la 8.33.0.
3. *La lecture ▶.* Naissances (effet existant), extinctions en fondu, remplacement montré par une impulsion de
   l'ancien vers le nouveau. Le réglage « moins d'animations » du système reste respecté.
4. *Les axes à l'écran.* Deux couleurs de plus, « domaine » et « chaleur » (dernier usage). Une disposition
   « couches », sur un bouton : la hauteur d'un souvenir est fixée par son niveau, vision en haut, détail en bas.
5. *Le panneau d'un souvenir* affiche sa lignée : ce qu'il remplace, ce qui l'a remplacé, les dates, la raison.
6. La vue 2D et le tableau acceptent les nouveaux champs et ne montrent que le présent.
- Fichiers : `viz.py`, `brainkit/vue3d/page.html`, `tests/test_vue3d.py`, `tests/vue3d_navigateur.js`. Les
  bibliothèques intégrées ne changent pas.
- Fini quand : dans le test en navigateur, à une date passée, un souvenir remplacé depuis est visible et son
  remplaçant absent ; curseur à droite, la page affiche les mêmes nœuds et liens qu'en 8.33.0.
- ✅ Fait le 24/11 (cerveau 8.36.0) :
  - Données : `DATA.nodes` et `DATA.edges` restent le présent ; le passé arrive à part (`DATA.past` : souvenirs
    archivés qui ont une fin, 2 000 au plus ; `DATA.pastEdges` : liens vers eux et liens terminés). La vue 2D, le
    tableau, la légende et les compteurs ne le voient donc pas, sans y toucher. Chaque souvenir ne porte que les
    champs de temps qu'il a (début, fin, raison, remplaçant, domaine, niveau corrigé, dernier usage).
  - Comparé au vrai code de la 8.33.0 tiré de git, sur le même cerveau : mêmes souvenirs, mêmes liens, mêmes
    compteurs dans les données. Dans Chromium, curseur à droite : exactement le présent (aucun nœud en plus ni en
    moins, aucun lien du passé). Le passé caché tient à peine dans la disposition (liens de force 0,02, répulsion
    -12 au lieu de -190), pour ne pas déformer la vue d'aujourd'hui.
  - À une date passée : le souvenir remplacé depuis est visible, son remplaçant pas encore ; un lien terminé est
    visible avant sa fin, plus après. Le curseur s'arrête aussi au lendemain de chaque fin, pour voir l'extinction.
  - Lecture ▶ : naissances (effet existant), extinctions en fondu (0,76 s), impulsion de l'ancien vers le nouveau ;
    rien de tout cela si le système demande moins d'animations ou si les effets sont coupés.
  - Couleurs « domaine » et « chaleur » (dernier usage : semaine, mois, trimestre, plus ancien) ; bouton ☷ des
    couches (vision, architecture, procédure, détail, de haut en bas) ; le panneau d'un souvenir donne sa validité,
    son niveau, son domaine et sa lignée.
  - Poids de la page, sur le cerveau du banc du rappel avec 20 remplacements et 30 liens retirés : 2 039 043
    octets au lieu de 2 022 093 (+0,8 %). Les bibliothèques intégrées ne changent pas.
  - Tests : `test_vue3d` passe à 68 vérifications (dont la comparaison avec la 8.33.0 et, quand Playwright est là,
    `tests/vue3d_chronologie.js` dans Chromium : présent, passé, lien terminé, couches, couleurs, lecture). La CI
    n'a pas Playwright : ces vérifications-là y sont sautées, comme celles du navigateur existantes.

**Ordre.** L'étape 10 d'abord : elle sert aux trois autres. Puis la 11. Les étapes 12 et 13 s'appuient sur la 11
et se font dans l'ordre que tu veux.

### Bloc F — Ce qu'apportent les 8 dépôts cités le 24/11 (plugin, étapes 14 à 19)

Ta demande du 24/11 : « regarde chaque lien GitHub que je t'ai envoyé et mets dans le cerveau ce qui est intéressant
et utile ». Quatre agents ont lu les 8 dépôts le 24/11 (README, docs, code ; commits cités dans leurs rapports). Le
cerveau en avait déjà une bonne part : cycle de vie par hooks, graphe typé et daté, remplacement sans effacer, fusion
RRF, doublons exacts, montré ≠ utilisé, provenance et confiance, contrôle des skills reçues, sorties de commandes qui
contiennent un secret jamais gardées. Écarté pour toutes les étapes : embeddings, Neo4j ou FalkorDB, appels à une
API payante (extraction par LLM à chaque ajout, rerankers, `claude -p` en boucle), code Node.js à embarquer.
Licences : Graphiti, mem0 Apache-2.0 ; best-practices, skills de Matt Pocock, obra, tapestry, l'auditeur de skills,
3d-force-graph MIT ; le guide de F. Bruniaux CC BY-SA 4.0 (on reprend des idées, pas son texte).

**Étape 14 — Une mémoire plus juste** (Graphiti, mem0) : **points 1 à 4, 6 et 8 faits le 24/11** (cerveau
8.38.0) ; 5, 7 et 9 reportés (raisons dans le détail). Tout en code déterministe, à l'écriture ou au rêve : aucun
coût pour le rappel.
1. Dates tirées du texte à l'ajout : « depuis le », « à partir du », « jusqu'au », et le futur (« va », « prévu »,
   « d'ici le ») ; une échéance n'est pas une fin. Proposées à Claude, pas posées en silence. (S, graphiti
   `temporal_edge_utils.py`)
2. Un remplacement clôt l'ancien à la date de début du nouveau, pas à la date du jour ; un nouveau qui commence avant
   l'ancien n'est pas le remplaçant ; deux périodes qui ne se chevauchent pas ne se contredisent pas. (S, graphiti
   `edge_operations.py`)
3. Contradictions cherchées aussi parmi les souvenirs qui partagent un nom propre rare, pas seulement les textes
   proches ; un événement ne contredit jamais un état. (S, graphiti `dedupe_edges.py`)
4. Les variantes d'un même nom réunies (« Mondial Relay », « MondialRelay », « mondial-relay ») : trigrammes et
   MinHash en bibliothèque standard, au rêve. (S, graphiti `dedup_helpers.py`)
5. Index nom → souvenirs gardé avec le graphe, au lieu de tout relire à chaque question. (S, mem0 `main.py`)
6. Règles d'écriture d'un souvenir dans le rappel de fin de tâche : il tient seul, sans pronom ; noms et chiffres
   exacts ; un changement s'écrit « X → Y, parce que… » ; dates absolues ; rien de ce que Claude a seulement répété.
   (S, prompt d'extraction de mem0)
7. Provenance par session (`meta.sessions`) et `brain oublier-session <id>` qui retire ce qui ne reposait que sur
   elle ; journal ancien/nouveau texte par souvenir. (M, graphiti `remove_episode`, table history de mem0)
8. Au rêve, des souvenirs « motif » rédigés par Claude ou l'archiviste à partir d'une communauté, liés à leurs
   preuves, sans doublon d'un rêve à l'autre. (M, Dream de mem0)
9. Usage : un facteur de déclin d'après les derniers rappels (ACT-R), comme trait du neurone, jamais comme filtre ;
   diversité des souvenirs rappelés (MMR) au lieu de l'élimination des seuls quasi-doublons. (S, mem0, graphiti,
   guide Bruniaux §9) — mesuré sur le banc du rappel avant d'être gardé, comme les piliers.

- ✅ Fait le 24/11 (cerveau 8.38.0) :
  - Dates dites dans le texte (`temps.text_dates`) : proposées après `add` (ligne 📅 avec la commande), jamais posées
    seules ; « d'ici le » reste une échéance.
  - Remplacement daté (`temps.end_for`) : l'ancien finit la veille du `--depuis` du nouveau ; un remplaçant qui ne
    commence que plus tard laisse l'ancien vrai et actif jusque-là (l'entretien du jour l'archive après sa fin, et ne
    l'archive plus avant) ; un « nouveau » qui commence avant l'ancien est refusé (`supersede`) ou ignoré (`add
    --replaces`, remplacement automatique).
  - Réconciliation : deux souvenirs aux périodes écrites distinctes ne se fusionnent ni ne se remplacent ; les
    variantes d'un même nom comptent pour un (`reconcile.names` : « Mondial Relay », « MondialRelay » → mondialrelay) ;
    un souvenir qui partage un nom propre rare (3 souvenirs au plus le portent) est suggéré (« remplace peut-être »),
    jamais remplacé tout seul. Le banc des remplacements de `brain bench` reste à 12 sur 12, sans faux remplacement.
    Pas fait : la règle « un événement ne contredit jamais un état » (les types du cerveau ne disent pas assez
    nettement ce qui est un événement).
  - Rappel de fin de tâche : « Un souvenir tient seul : noms, chiffres et dates exacts ; un changement : « X → Y,
    parce que… » » (593 caractères, budget 600).
  - Rêve : un « motif » à écrire par sujet d'au moins 8 souvenirs qui n'en a pas, un par rêve, avec la commande qui
    le relie à ses preuves ; le titre « Motif : … » évite les doublons.
  - Reportés : 5 (l'index des noms n'accélère que `brain q`, pas le rappel des hooks), 7 (la provenance par session
    demande l'identifiant de session dans chaque commande ; à vérifier d'abord), 9 (déclin d'usage et diversité :
    un nouveau trait du neurone rendrait inutilisable le modèle déjà appris sur ton PC).
  - Tests : nouveau `tests/test_justesse.py` (16 vérifications). Les 39 scripts passent.

**Étape 15 — La mémoire protégée** (guides Claude Code) : **points 1 à 4 faits le 24/11** (cerveau 8.37.0) ;
le point 5 après l'étape 18, qui change les skills. Détail après la liste.
1. Anti-empoisonnement à l'écriture : le contrôle des pages d'amis (`lint_text`) passe aussi sur ce qui entre dans la
   mémoire depuis le web, une transcription ou une source du wiki ; un texte qui donne des consignes est mis de côté
   et signalé, pas ré-injecté à chaque message. (S, guide Bruniaux §7.1)
2. Canari de portée dans `brain bench` : un souvenir planté dans un projet ne doit jamais revenir dans un autre.
   (S, guide Bruniaux §1)
3. Au démarrage, le `CLAUDE.md` du projet ouvert passé au même contrôle (consignes cachées, `curl | bash`, base64,
   commentaires HTML). (S, `claudemd-scanner.sh`)
4. Une règle apprise (filtre de commande, déclencheur de skill) passe par « candidate » avant « active », avec sa
   preuve et une date d'expiration. (M, guide Bruniaux)
5. Déclenchement des skills calibré : phrases positives et négatives par skill, seuil par skill, mesuré hors des
   hooks. (M, `bm25-routing` du guide Bruniaux)
- ✅ Fait le 24/11 (cerveau 8.37.0) :
  - Anti-empoisonnement (`brainkit/garde.py`) : à l'écriture d'un souvenir qui ne vient pas de l'utilisateur, et chaque
    jour pour les pages changées hors du cerveau. Seules les familles du contrôle des skills qui trahissent une
    injection comptent (consigne qui annule celles de l'utilisateur, action cachée, téléchargement exécuté,
    caractères invisibles, commentaire caché) : appliqué tel quel, ce contrôle aurait caché des règles légitimes
    (« ne jamais faire git push --force », « la clé reste dans le fichier d'environnement »). Un souvenir mis de côté
    porte `meta.a_verifier` (propriété du même nom dans le wiki) ; le rappel et le démarrage n'en montrent que le
    titre et l'avertissement ; `brain edit <id> --verifie` le lève.
  - `CLAUDE.md`, `CLAUDE.local.md` et `.claude/CLAUDE.md` du projet ouvert contrôlés au démarrage ; verdict gardé par
    version du fichier : Claude est prévenu à chaque session, l'utilisateur une fois.
  - Canari de portée : écart avec le plan. Le rappel montre exprès un souvenir d'un autre projet (sans le bonus du
    projet courant) ; « ne jamais revenir dans un autre projet » contredirait cette règle. Le test vérifie la règle
    réelle : à texte égal, le souvenir du projet courant passe devant.
  - Règles apprises : chaque filtre de sortie appris garde sa preuve (la commande, masquée) et une échéance de
    180 jours ; à l'échéance il est prolongé s'il retire encore assez de bruit, retiré sinon, et c'est annoncé. Pas
    d'étape « candidat » : le filtre ne servirait qu'avec retard, et il était déjà annoncé et retirable.
  - Tests : nouveau `tests/test_protection.py` (27 vérifications). Les 38 scripts passent.

**Étape 16 — Le serveur MCP** (serveurs de référence) : **points 1 à 3 faits le 24/11** (cerveau 8.39.0) ; le 4
non fait (pas demandé).
1. Erreurs conformes : outil inconnu → erreur JSON-RPC -32602 ; ajout ou modification en partie refusés → le dire
   (« ignoré : … ») sans échouer. (S, aucun caractère de plus dans la liste des outils)
2. Ressources `memoire://{id}` : un souvenir se joint à une conversation sans appel d'outil. (M, 0 caractère de plus)
3. `structuredContent` dans les réponses et le protocole 2026-07-28 (`server/discover`) à côté de l'actuel, pour
   rester compatible avec les prochaines versions de Claude Code. (M, 0 caractère de plus)
4. Annotations des outils (lecture seule, destructif) : +550 caractères dans chaque session ; à ne faire que si tu
   veux ce confort. (S)
- ✅ Fait le 24/11 (cerveau 8.39.0), par un agent en parallèle puis repris sur la branche :
  - Erreurs : outil inconnu et paramètres malformés → erreur JSON-RPC -32602 (spécification MCP 2025-11-25) ; un outil
    qui échoue reste un résultat en erreur préfixé « ✗ » ; « ignoré : … » dit ce qu'un ajout ou une modification
    n'applique pas ; `memory_update` ne perd plus les champs donnés avec `done` ou `archive`.
  - Ressource `memoire://{id}` (modèle de ressource, lecture paginée ; souvenir inconnu : -32002, ou -32602 en
    2026-07-28, qui a changé ce code).
  - Protocole 2026-07-28 servi à côté de l'actuel (`server/discover`, `_meta.protocolVersion`, résultats
    structurés). Limite trouvée : d'après plusieurs tickets de Claude Code, quand une réponse a un `structuredContent`,
    le modèle ne voit que lui ; les clients qui commencent par `initialize` (Claude Code aujourd'hui) reçoivent donc
    les mêmes réponses qu'avant.
  - Liste des outils : toujours 3 204 caractères. Tests : nouveau `tests/test_serveur_mcp.py` (37 vérifications) ;
    `test_noyau` et `test_erreurs` attendent désormais le code exact de la spécification.

**Étape 17 — La vue 3D, suite** (3d-force-graph).
1. Flèches sur les liens typés, et au survol d'un lien son type et ses dates. (S)
2. Un nœud déplacé à la main reste où on le pose (bibliothèque passée de 1.80.0 à 1.80.2 pour le correctif du
   glissement). (S)
3. Orbite automatique de la caméra, pour une capture vidéo YouTube. (S)
4. L'animation se met en pause quand l'onglet est caché. (S)

**Étape 18 — Six skills de plus** (toutes gratuites, sans clé ; réécrites en français, licence et auteur cités).
1. Auditeur de skills (MIT, bibliothèque standard) : avant d'installer ou de mettre à jour une skill tierce, un
   verdict « sûre / à vérifier / refusée » ; aussi branché sur l'échange de skills avec tes amis. (M)
2. « Cuisine-moi » (grilling, M. Pocock) : Claude t'interroge question par question sur un projet (boutique, map,
   module de la plateforme), avec sa réponse recommandée à chaque fois. (S)
3. Passation (handoff) : un document qui résume la conversation pour la reprendre ailleurs. (S)
4. Preuve avant « fini » (obra) : rien d'annoncé fini sans la commande qui le prouve et sa sortie lue. (S)
5. Apprendre en livrant (ship-learn-next) : un tutoriel ou une vidéo devient une suite de petits projets. (S)
6. Factures et reçus : renommés, classés, CSV pour le comptable (réception des factures électroniques obligatoire
   depuis le 01/09/2026). (S-M) — et, plus petits : tirage au sort pour concours, analyse d'un appel de vente dans
   carriere-commerciale.
Et deux pratiques : la description d'une skill dit quand s'en servir, jamais comment (à corriger dans les 18) ; un
test de comportement par skill (sans la skill, puis avec). (S, M)

**Étape 19 — Ce dépôt** (outillage, rien de livré) : **points 1 et 2 faits le 24/11** ; le 3 attend ta décision.
1. Grille de tri d'un test en échec (régression, instable, environnement, test périmé) proposée par le hook de
   vérification. (S, best-practices `test-triage`)
2. Contrôle d'un `CLAUDE.md` avant écriture (chemins absolus, secrets, sections vides). (S)
3. À ta décision, pas à la mienne : le garde-fou des commandes de la plateforme (`guard_shell.py`) résout les chemins
   relatifs par rapport au dépôt, pas au dossier courant après un `cd` ; il a refusé à tort un `git clone` dans un
   dossier temporaire. Le corriger touche un garde-fou (règle du `CLAUDE.md` de la plateforme) : je ne le fais pas
   sans toi.

- ✅ Fait le 24/11 : la grille de tri (régression, instable, environnement, test périmé) s'ajoute au renvoi du hook de
  vérification quand un test échoue ; `.claude/hooks/claude_md.py`, nouveau hook PreToolUse (Edit|Write), refuse un
  `CLAUDE.md` qui contiendrait un chemin absolu d'une machine, une valeur qui ressemble à une clé, ou une section vide
  (aucun faux positif sur les deux `CLAUDE.md` du dépôt). Aucun interdit ni hook existant retiré. `test_verifier` :
  40 vérifications.

**Serveurs à brancher sur ton PC** (rien à coder, à ta demande) : Fetch (lire une offre d'emploi ou une fiche
concurrente par morceaux), Time, Git, Filesystem en lecture seule sur le coffre Obsidian. Pas le serveur « memory » :
il fait doublon avec le cerveau.

**Ordre proposé** : 15 (protéger d'abord, petit et sûr), 14, 18, puis 16, 17, 19.

## 10. Décisions demandées

| # | Décision | Ma recommandation |
|---|---|---|
| E1 | `python` absent sur Mac et Linux | **Tranché le 21/11 : pas de lanceur**, Python direct (le lanceur coûtait +39 ms par hook sous Windows avec Git Bash, +200 à +280 ms sans) |
| E2 | Place des skills dans le contexte (mode éco : 0,5 %) | **Tranché le 21/11 : 0,5 % et `skillListingMaxDescChars` à 250** (étape 5) |
| E3 | Rappel de mémoriser en fin de tâche (hook Stop) | **Tranché le 20/11 : seulement quand une phrase durable a été dite, texte deux fois plus court** (étape 2) |
| E4 | Seuil du rappel (`min_cov`) | **Réglé par le banc d'essai de l'étape 3 : 0,5 reste**, 0,4 rappelait un mauvais souvenir |
| E5 | Veille PC qui ferme des processus | **Tranché le 20/11 : lister et proposer**, plus rien fermé sans ton accord (étape 2) |
| E6 | Plugins et skills désactivés tout seuls | **Tranché le 20/11 : te les proposer**, plus rien coupé sans ton accord (étape 2) |
| E7 | Sauvegarde sans second disque | **Tranché le 21/11 : dans ton dossier personnel** (`~/Sauvegardes-cerveau-Claude`), annoncé une fois (étape 7) |
| E8 | Retirer les skills humanizer et vercel (tes plugins les ont déjà) | **Tranché le 21/11 : retirées** ; leurs phrases mènent aux skills de tes plugins (étape 5) |
| E9 | Code de la plateforme qui sert seulement avec un budget API (≈ 6 000 lignes) | Le mettre de côté dans une branche, pas le supprimer |
| E10 | prompts.chat actif par défaut | Le garder, maintenant que son texte est filtré ; le couper si tu ne t'en sers pas |
| E11 | Fusionner la PR des correctifs sûrs et publier 8.24.0 | **Fait le 20/11** |
| E12 | `brain.exe` (Rust 8.18.2) tant que son code source n'est pas dans le dépôt | **Tranché le 20/11 : Python partout, puis optimiser en Rust.** Fait : `brain.exe` ne tourne plus que sur demande (`BRAIN_IMPL=rust`), tous les correctifs valent sous Windows. Ensuite (D2) : tu ajoutes le code Rust au dépôt ; Claude y reporte les correctifs faits depuis la 8.18.2, l'optimise, et l'exe est construit en CI |
| E13 | ADR-013 (« pas de yfinance ») contre l'étape 9 du plan v2 | **Tranché le 21/11 : l'ADR-013 fait foi**, le plan v2 corrigé (étape 9) |
| E14 | Retraits de cas d'évaluation réservés par R9 | **Validés le 23/11** : ADR-021, 046, 050, 057, 060, 063 (le retrait) et 068 |
| E15 | 35 ADR encore « proposé » | À relire dans `docs/adr/A-VALIDER.md` (ta réponse du 23/11 : relire d'abord) |
| E16 | Graphiti, mem0 ou une base de graphe pour le cerveau en 4D | **Tranché le 24/11 : reprendre leurs idées, ne rien installer** (Bloc E) |
| E17 | Recherche par embeddings | **Tranché le 24/11 : le rappel reste lexical**, avec un filtre par validité en plus (étape 12) |
| E18 | Modèle qui exécute le Bloc E | **Tranché le 24/11 : Opus 5.5**, tu changes le modèle de la session toi-même |
| E19 | Liste des domaines, pour l'axe « domaine » (étape 11) | **Appliquée le 24/11 telle que recommandée**, proposée et non imposée (le `--domaine` libre existait déjà). Sept domaines portés par le projet : code, business, contenu, finance, infra, recherche, perso. À toi de corriger la liste |
| E20 | Vérification en fin de tâche dans ce dépôt (étape 10) | **Appliquée le 24/11 telle que recommandée** (ton GO, sans autre consigne) : le lint et les tests des fichiers touchés ; tous les scripts (3 min 50 mesurées le 24/11 sous Linux) restent pour la CI. À changer si tu veux tout lancer |
| E21 | Où garder un lien terminé en mode wiki (étape 11) | **Appliquée le 24/11 telle que recommandée.** Dans une propriété `anciens_liens` de la page, pour qu'il survive à une reconstruction de `graph.json` |

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

Les 15 vieilles branches (ton accord du 21/11 ; la session cloud n'a pas le droit de les supprimer), une seule commande,
dans ton clone du dépôt :

```powershell
git push origin --delete cerveau-plateforme claude/clever-heisenberg-lgjfhn claude/compassionate-gauss-txr1ff claude/eloquent-lovelace-ds7vsi claude/gallant-einstein-itr2km claude/reverse-api-engineer claude/skill-rea claude/sleepy-brahmagupta-nqxaed claude/tender-hawking-0qf1id claude/upbeat-cerf-h65b5u claude/vibrant-bardeen-x40dsb claude/vibrant-pascal-chu3e3 claude/wizardly-goldberg-v4yxlu phase-7-mise-en-route plateforme-phase-6-p6
```

## 12. Confiance et points à vérifier

- **Reproduit dans l'audit** (confiance élevée) : chaque ligne marquée « reproduit » en annexe.
- **Lu seulement** (confiance moyenne) : le comportement sous Windows (veille PC, verrous de fichiers,
  `brain.exe`), Git Credential Manager, les chemins Windows des skills.
- **Relecture de gouvernance du pont MCP** : faite par des essais (13 fichiers de tests, rejoués trois
  fois avec les mêmes résultats), sans les plugins de finance en vrai processus (ils auraient lu ta
  vraie base) ni sous Windows.
- `[VERIFICATION REQUIRED]` : le coût réel des skills et des outils MCP dans ta session (`/context`) ;
  le compte réel des tokens (le cerveau estime 2,2 caractères par token) ; les vitesses sous Windows.
- **Bloc E** : le tableau E.1 vient d'une lecture du code le 24/11, fichier par fichier, pas d'essais.
  État de départ mesuré le 24/11 sous Linux (Python 3.13) : les 35 scripts de test passent sans échec en 3 min 50, le lint de la CI ne signale rien. Les quatre dépôts de guides et
  de skills cités dans ta synthèse n'ont pas été lus. Les piliers au démarrage (étape 12, point 3) sont une
  hypothèse, livrée seulement si le banc d'essai la confirme.

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
