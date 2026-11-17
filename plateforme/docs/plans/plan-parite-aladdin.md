# Plan — Remise au vert et parité Aladdin

Date : 17/11/2026 · Statut : **validé** le 17/11/2026 (« ok valide le plan, commence l'étape 0 ») ;
décisions P2 à P9 encore ouvertes (§7). Étape 0 : `docs/rapports/etape-0-2026-11-17.md`.

Périmètre choisi par Lucas le 17/11/2026 : le plugin mémoire (`brainkit/`) **et** la plateforme
(`plateforme/`) ; exécution jusqu'au niveau **N3** (ordre réel après son accord) ; actions et ETF en
euros, actions étrangères, obligations et options, crypto ; données **gratuites d'abord**.

## 0. En une phrase

On corrige d'abord ce qui est cassé ou jamais exécuté, on débloque les 38 fonctions arrêtées par des
réglages manquants, on mesure une première fois avec de vrais modèles, puis on complète les fonctions
finance qui manquent face à Aladdin, jusqu'à un ordre réel approuvé par Lucas.

## 1. Ce que « niveau Aladdin » veut dire ici

Aladdin est une plateforme institutionnelle : données propriétaires, modèles de risque calibrés sur
des décennies et des milliers de portefeuilles, marchés privés, comptabilité multi-entités. Cela
reste `[Hors de portée]` (méga-prompt §2.3) et ce plan ne prétend pas l'atteindre.

La cible atteignable est la **parité fonctionnelle à l'échelle d'un portefeuille personnel** : les
onze fonctions F1 à F11 de la matrice (§10 du méga-prompt) présentes, mesurées et étiquetées, avec
une seule source de vérité pour les données et un langage de risque commun. Sur un point CERVEAU va
plus loin qu'Aladdin, qui ne décide d'aucun ordre : l'exécution après approbation (N3).

## 2. État mesuré le 17/11/2026

Mesures faites dans une session cloud (Linux, Python 3.13 pour le plugin, 3.12 par uv pour la
plateforme, git 2.43, clone superficiel).

| Sujet | Constat |
|---|---|
| Plugin, version | 8.21.0 ; 52 modules, 30 340 lignes ; 10 scripts de test |
| Plugin, tests | 7 scripts sur 10 verts. `test_eco.py` : 3 échecs. `test_ecommerce.py` : 7 échecs, dont 4 dus au `.venv` créé pour cette mesure. `test_wiki.py` : 1 échec. `test_bascule.py` : ne démarre pas |
| Plugin, lint | Aucune CI, aucun lint. `ruff` (règles F et B) : 48 alertes, dont 7 imports inutiles et 4 fonctions qui capturent une variable de boucle |
| Plateforme, taille | 116 603 lignes de Python ; 60 ADR ; phases 0 à 5 livrées, phase 6 jusqu'à P5 |
| Plateforme, lint | `ruff check` et `ruff format --check` : 0 erreur, 523 fichiers |
| Plateforme, tests | 6 801 réussis, 205 échecs, 5 erreurs, 12 ignorés, en 478 s. 209 des 210 viennent de git 2.43 (le pack Code exige 2.45, voir C11) ; le dernier est une différence entre Windows et Linux (C18). Le rapport P5 annonçait 7 017 réussis sur la machine de Lucas |
| Plateforme, configuration | Valide. **14 fonctions disponibles, 38 bloquées** par 57 marqueurs (39 `A_DEFINIR`, 18 `A_VERIFIER`) |
| Plateforme, backlog | 264 points ouverts sur 332 : 138 fonctionnels, 58 sécurité, 38 évals, 11 infrastructure, 11 auto-amélioration, 8 chaîne de livraison. 12 attendent une décision de Lucas |
| Plateforme, évals | Toutes hors ligne, avec des modèles scriptés. **Aucune campagne réelle n'a jamais tourné** : le score du juge, la résistance d'un vrai modèle aux injections et les coûts réels sont inconnus |
| Packs | Les 6 packs existants sont `experimental`. P6 Business n'existe pas. Phase 7 non commencée |

## 3. Problèmes à corriger

### 3.1 Bloquants (rien d'autre n'est fiable tant qu'ils restent)

| # | Problème | Preuve | Correction |
|---|---|---|---|
| C1 | **La CI ne tourne jamais.** GitHub ne lit que `.github/workflows/` à la racine ; le fichier est dans `plateforme/.github/workflows/ci.yml` | emplacement du fichier | Workflow à la racine, deux jobs (plugin, plateforme), `working-directory: plateforme` |
| C2 | **Les garde-fous de Claude Code risquent de ne pas s'appliquer** quand la session s'ouvre à la racine du dépôt : `settings.json` (hooks, permissions) se lit dans le `.claude/` du dossier d'ouverture, et celui de la plateforme est dans `plateforme/.claude/`. Non confirmé par un test : la session du 17/11, ouverte à la racine, n'a vu aucun refus, mais n'a tenté aucune action interdite | emplacement de `plateforme/.claude/settings.json` | Test d'abord (une action refusée depuis `plateforme/` doit l'être depuis la racine), puis décision P2 : `.claude/` à la racine, ou dépôt séparé pour la plateforme |
| C3 | **Le plugin livre toute la plateforme.** `source: "./"` : chaque personne qui installe le plugin reçoit `plateforme/` (116 000 lignes, le méga-prompt, le modèle de menaces) et `brain.exe` | `.claude-plugin/marketplace.json` | Décision P2 : séparer les deux, ou exclure `plateforme/` de la publication |
| C4 | **Contrôle « dépôt public sans donnée personnelle » en échec** sur 2 fichiers suivis : `plateforme/docs/MEGA-PROMPT-CERVEAU.md` (1 mot) et `plateforme/evals/redteam/injection_base/fuite_prompt.yaml` (2 mots) | `tests/test_ecommerce.py` | Lire les mots signalés, les retirer ou sortir `plateforme/` du dépôt publié (C3). À traiter en premier si le dépôt est public |
| C5 | **`brain.exe` (8,7 Mo) suivi par git sans son code source** : `brainkit/publish.py` le construit depuis `rust/`, absent du dépôt. Deux implémentations (Rust sous Windows, Python ailleurs) peuvent diverger sans qu'un test le voie | `git ls-files`, `publish.py:393` | Décision P3 : publier le source Rust et construire l'exe en CI, ou abandonner le portage |
| C6 | **Le serveur MCP `cerveau` ne se connecte pas** quand le dépôt est ouvert comme projet (« Connection closed »). Lancé à la main, il répond. Cause probable, non confirmée : `${CLAUDE_PLUGIN_ROOT}` n'existe pas hors du contexte plugin, et `.mcp.json` est lu comme configuration du projet | session du 17/11 | Reproduire, puis sortir la déclaration MCP du `.mcp.json` racine (la porter dans `plugin.json`) |

### 3.2 Défauts du plugin

| # | Problème | Correction |
|---|---|---|
| C7 | `test_eco.py`, 3 échecs sur les leviers `skillListingBudgetFraction` et `autoMemoryEnabled` (valeurs de l'utilisateur écrasées ou leviers non posés). Reproduit dans un environnement vide | Trouver la cause, corriger le code ou le test |
| C8 | `test_ecommerce.py` : « README.md du dépôt identique à celui de publish » en échec | Régénérer le README ou corriger le gabarit |
| C9 | `test_wiki.py` suppose Windows (tâche planifiée) et échoue sous Linux ; `test_bascule.py` exige l'historique complet (tag `v8.0.0`) | Rendre les deux tests portables ; ignorer proprement le cas absent |
| C10 | 52 modules pour 10 scripts de test ; `mapper.py` et `cli.py` dépassent 2 400 lignes ; 48 alertes `ruff` | Lint en CI, correction des alertes, tests des modules non couverts (`search`, `index`, `dream`, `mcp_server`, `privacy`) |

### 3.3 Défauts de la plateforme

| # | Problème | Correction |
|---|---|---|
| C11 | Avec git < 2.45, tout le pack Code répond « pas un dépôt git lisible » : git refuse l'option `--no-lazy-fetch` et l'erreur réelle est masquée. 209 tests échouent sur 6 fichiers (`code_agent` 75, `code_checks` 58, `code_repo` 53, `test_code_repos` 15, `test_code_sandbox` 5, `test_code_git` 2) (B271) | Vérifier la version de git au démarrage et le dire en clair ; fixer la version en CI |
| C18 | `tests/test_execution_nautilus.py:268` attend `MONEY_MAX` = 9 223 372 036, la valeur de NautilusTrader sous Windows ; sous Linux elle vaut 17 014 118 346 046. Le VPS visé est sous Linux : le plafond de montant y diffère (B122) | Lire la valeur dans la bibliothèque au lieu de l'écrire en dur ; tester les deux plateformes en CI |
| C12 | 57 marqueurs bloquent 38 fonctions, dont le paper trading, les budgets, les approbations, l'API, le bot Discord et les six portes d'évals | Étape 1 |
| C13 | Aucune mesure réelle (voir §2) | Étape 2 |
| C14 | `core/memory/` est vide (B58) : la plateforme n'a aucune mémoire, alors que le plugin en est une | Étape 7 |
| C15 | 58 points de sécurité ouverts. Avant tout ordre réel : B200 (les limites live ne sont pas appliquées par la Porte), B230 (heure de l'approbation donnée par l'appelant), B235 (ACL POSIX), B228 (secrets hérités par tout processus), B8 (ancre externe du journal d'audit), B9 (durcissement du VPS) | Étapes 6 et 9 |
| C16 | Erreurs de calcul relevées par la revue quantitative et encore ouvertes : B105 (fraîcheur jugée à la mauvaise date), B109 (variation de VaR), B110 (poids), B112 (VaR sur h séances), B113 (frais absents du rééquilibrage), B114 (ETF obligataire choqué comme une action), B115 (annualisation), B116 (ratio de split en flottant), B117 | Étape 4 |
| C17 | `ref.db` (données de portefeuille) à la racine, ni suivi ni ignoré (B148) | Décision de Lucas, déjà au backlog |

## 4. Écarts avec Aladdin, fonction par fonction

| # | Fonction | Présent | Manque pour la cible |
|---|---|---|---|
| F1 | Données | Référentiel, cours par CSV, BCE (taux, change), contrôles de qualité, point-in-time | OpenBB, yfinance et FRED désactivés ; ni fondamentaux, ni actualités structurées, ni séries de facteurs, ni indice de référence validé |
| F2 | Portefeuille | Import CSV, positions, transactions, plus-values | Lecture du courtier (aucun adaptateur IBKR), réconciliation quotidienne réelle |
| F3 | Risque | VaR et CVaR (historique, paramétrique, Monte-Carlo), Kupiec, GARCH, drawdown, bêta, HHI, contributions, stress hypothétiques | Régression factorielle (« non disponible »), stress historiques (dates `A_VERIFIER`), écart de suivi, risque de liquidité, corrections C16 |
| F4 | Optimisation | Moyenne-variance, min-CVaR, parité de risque, HRP (skfolio) | Aversion au risque `A_DEFINIR`, frais dans l'objectif (B113), backtest du rééquilibrage (B143) |
| F5 | Recherche | Criblage vectorbt, backtest NautilusTrader, protocole anti-surapprentissage, une stratégie de démonstration | Recherche ML point-in-time (Qlib), stratégies réelles, walk-forward enchaîné (B159) |
| F6 | Valorisation | **Rien** (QuantLib absent) | Obligations (courbe, duration, convexité), options (prix, grecques) |
| F7 | Pré-trade | Moteur de règles, Porte de risque couverte à 100 % | Limites live branchées (B200), univers et exclusions `A_DEFINIR` |
| F8 | Exécution | Machine à états, simulateur paper en euros, adaptateur live désactivé, kill switch, réconciliation | Change dans le simulateur (B166), courtier réel, crypto (ccxt), mesure du glissement réel |
| F9 | Performance | TWR, MWR, Sharpe, Sortino, Calmar, contributions par ligne | Attribution Brinson et factorielle (reportées faute d'indice), rapport HTML (B144) |
| F10 | Copilot | Orchestrateur 8 nœuds, garde-fous, vérification des chiffres | Qualité réelle jamais mesurée ; mémoire absente |
| F11 | Comité | Mode Comité, débats journalisés | Sources dans la synthèse (B130), traçage des chiffres (B124) |

## 5. Les étapes

Chaque étape suit la méthode du dépôt : complément de plan, validation, implémentation, tests,
évals, compte rendu, arrêt jusqu'au `GO`. L'ordre compte : une étape s'appuie sur les précédentes.

**Étape 0 — Remise au vert.** Corrige C1 à C11 et C18. Fin d'étape : la CI tourne à chaque pull request
sur Linux et Windows, plugin et plateforme ; tous les tests passent ; le contrôle de données
personnelles passe ; le serveur MCP se connecte ; les garde-fous s'appliquent quel que soit le
dossier d'ouverture.

**Étape 1 — Réglages et décisions.** Claude Code propose une valeur prudente et sourcée pour
chacun des 57 marqueurs, en un seul document ; Lucas valide, corrige ou refuse ligne par ligne et
écrit lui-même les valeurs de gouvernance. Les 12 décisions en attente du backlog sont tranchées au
même moment. Fin d'étape : `cerveau config check` ne laisse bloqués que le live et N4.

**Étape 2 — Première mesure réelle.** Budgets fixés, puis une campagne d'évals payante sur les six
packs (estimation du rapport de phase 1 : 6 à 12 $ pour 95 cas, non mesurée ; les suites en comptent
davantage aujourd'hui). Fin d'étape : score du juge par pack, 20 jugements relus par Lucas, coûts
p50 et p95, résistance réelle aux injections. Tout ce qui est sous le seuil devient la priorité de
l'étape suivante, avant toute fonction nouvelle.

**Étape 3 — Données gratuites (F1).** OpenBB, yfinance et FRED après lecture de leurs conditions ;
fondamentaux et actualités ; séries de facteurs et indice de référence ; qualité des séries de
change et de taux (B85). Fin d'étape : un portefeuille réel de Lucas valorisé chaque jour sans
fichier CSV manuel, chaque série avec son score de qualité.

**Étape 4 — Risque et performance complets (F3, F4, F9).** Corrections C16, chacune par ADR quand
le golden set fige une valeur (R9) ; exposition factorielle ; stress historiques ; écart de suivi ;
liquidité ; attribution Brinson et factorielle ; frais dans le rééquilibrage. Fin d'étape : chaque
mesure recoupée par un calcul indépendant, à la tolérance près.

**Étape 5 — Tous les actifs demandés.** Dans cet ordre : change dans le simulateur et les frais
(actions étrangères, B166) ; obligations puis options avec QuantLib (F6) ; crypto en lecture, puis
en paper, sur une plateforme dont le statut MiCA est vérifié. Fin d'étape : un portefeuille de
référence mêlant les quatre classes passe les rapports de risque et de performance.

**Étape 6 — Courtier et paper trading réel (F2, F8).** Choix du courtier (décision P5), lecture
seule d'abord, réconciliation quotidienne, puis paper trading sur le compte paper du courtier
pendant au moins quatre semaines. Corrige B200, B230 et B235. Fin d'étape : quatre semaines sans
écart de réconciliation non expliqué, kill switch mesuré sous sa cible.

**Étape 7 — Mémoire et Copilot (F10, F11).** Mémoire de la plateforme (B58) : décision P6 entre un
pont vers le plugin et un module propre. Pack P6 Business. Passage des packs de `experimental` à
« actif » pour ceux qui tiennent leur seuil réel. Fin d'étape : les cinq requêtes du §10.10
répondent sur le portefeuille réel, sources citées.

**Étape 8 — Amélioration continue (phase 7).** Calibration et score de Brier, champion et
challenger, rapport hebdomadaire, red team hebdomadaire, revue de sécurité mensuelle. Fin d'étape :
quatre semaines de rapports sans intervention.

**Étape 9 — Activation N3, par Lucas seul.** B8, B9 et B228 fermés ; `docs/procedure-live.md`
suivie à la main ; capital et limites fixés par Lucas ; premier ordre réel approuvé un par un.
Claude Code n'active rien (R3). N4 reste hors de ce plan.

En continu : à chaque étape, fermer les points de sécurité et d'évals du backlog qui touchent le
code modifié, plutôt qu'une étape « sécurité » à part.

## 6. Ce que ce plan ne fait pas

- Aucun assouplissement de seuil, de limite ou de garde-fou pour faire passer une étape (R9).
- Aucune activation du live, d'un compte ou d'un serveur MCP par Claude Code.
- Pas de N4, pas de marchés privés, pas d'analytique climat, pas de conseil à des tiers (R16).
- Pas de source payante tant que les sources gratuites n'ont pas montré leur limite par une mesure.

## 7. Décisions demandées à Lucas

| # | Décision | Recommandation |
|---|---|---|
| P1 | Valider l'ordre des étapes 0 à 9 | Oui : l'étape 0 d'abord, sans rien ajouter avant |
| P2 | Un dépôt ou deux (C2, C3) | **Deux** : le plugin reste public, la plateforme passe dans un dépôt privé avec son `.claude/` à la racine |
| P3 | `brain.exe` (C5) | Publier le source Rust et construire l'exe en CI ; sinon revenir au seul Python |
| P4 | Le dépôt est-il public ? Si oui, C4 passe avant tout | À confirmer par Lucas |
| P5 | Courtier pour la lecture et le paper trading | Interactive Brokers (adaptateur NautilusTrader marqué stable) ; conditions à lire par Lucas |
| P6 | Mémoire de la plateforme | Pont en lecture vers le plugin d'abord ; module propre seulement si une mesure le justifie |
| P7 | Budget de la première campagne réelle (étape 2) | Plafond fixé par Lucas dans `budgets.yaml` avant tout lancement |
| P8 | Ordre des actifs à l'étape 5 | Actions étrangères, obligations, options, crypto |
| P9 | Qui écrit les 57 valeurs de l'étape 1 | Claude Code propose, Lucas écrit lui-même celles de `config/live.yaml`, des limites et de l'autonomie |
