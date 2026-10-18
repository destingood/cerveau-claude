# Plan — Phase 2 : pack Finance en lecture (N0–N1) : F1, F2, F3, F4, F9, F10

Date : 18/10/2026 · Statut : **validé par Lucas le 18/10/2026**, avec les recommandations D1 à D21 du §12.

## 0. En une phrase

Lucas importe son portefeuille (CSV), `cerveau finance sync` charge cours, change et taux dans une base point-in-time contrôlée, et `cerveau ask` répond aux cinq questions du §10.10 avec des chiffres qui viennent tous de cinq outils déterministes (données, portefeuille, risque, optimisation, performance), chacun relié à l'appel d'outil qui l'a produit (R1). Aucune action : la finance reste en N0 tant que Lucas ne la promeut pas à la main, et un rééquilibrage n'est jamais qu'une proposition.

## 1. Vérifié aujourd'hui (sources officielles, 18/10/2026)

| Sujet | Constat | Source |
|---|---|---|
| **CGU Yahoo** | Interdisent d'accéder aux Services ou d'en collecter des données par tout moyen automatisé (robots, scrapers, outils d'extraction), « for any purpose without our express, prior permission ». Même clause dans la version UE (Yahoo EMEA). **yfinance contrevient donc aux CGU (R15).** | legal.yahoo.com/us/en/yahoo/terms/otos ; legal.yahoo.com/ie/en/yahoo/terms/otos |
| yfinance 1.7.0 (26/08/2026) | Licence Apache-2.0. Le README dit : non affilié à Yahoo, usage personnel, « refer to Yahoo!'s terms of use ». Dépend de `curl_cffi` (imitation de l'empreinte TLS d'un navigateur). | PyPI, github.com/ranaroussi/yfinance |
| openbb 5.0.0 / openbb-mcp-server 2.0.1 | Apache-2.0. Transport `stdio` disponible (défaut : streamable HTTP sur 127.0.0.1:8001/mcp). `--allowed-categories` : les routes hors catégorie ne sont jamais enregistrées. L'authentification ne couvre pas stdio. Un outil `install_skill` **écrit des fichiers sur le disque du serveur** pour tout client. Beaucoup de fournisseurs exigent une clé dans les identifiants OpenBB. | docs.openbb.co (extension openbb-mcp), PyPI |
| openbb-yfinance 2.0.0 | **AGPL-3.0-only**, dans un dépôt séparé (deeleeramone/openbb-danglewood), et repose sur Yahoo. | PyPI |
| **B21** (dépôt OpenBB) | `OpenBB-finance/OpenBB` redirige vers `openbq-org/OpenBB` (actif, poussé le 17/10/2026). docs.openbb.co pointe vers `OpenBB-finance/OpenBB`, donc la redirection vient de GitHub. Le fichier LICENSE place tout le dépôt sous Apache-2.0. **B21 peut être clos.** | api.github.com, docs.openbb.co |
| BCE | Usage libre des informations du site, à condition de citer la BCE comme source et de signaler toute modification (par exemple un calcul de taux de croissance). Les conditions propres à l'API du Data Portal restent `A_VERIFIER`. | ecb.europa.eu/services/using-our-site/disclaimer |
| Tiingo (alternative) | Offre Starter à 0 $ : 50 requêtes/h, 1 000/jour, 500 symboles uniques/mois, 1 Go/mois, licence « Internal Use Only ». Couvre les actions US et chinoises, les ETF et les fonds. La couverture Euronext n'est pas affichée. | tiingo.com/about/pricing |
| skfolio 1.9.4 (17/10/2026) | BSD-3. Dépend de cvxpy-base, clarabel, scikit-learn ≥ 1.6, plotly, scipy ≥ 1.15.2 et pandas ≥ 2.1. Publiée la veille. | PyPI |
| riskfolio-lib 7.4.0 / PyPortfolioOpt 1.6.0 | BSD-3 / MIT. riskfolio tire matplotlib, astropy, xlsxwriter, networkx, statsmodels, arch et cvxpy. | PyPI |
| arch 8.0.0 (21/10/2025) | NCSA (GitHub affiche NOASSERTION), dépend de statsmodels, dépôt actif. | PyPI, GitHub |
| quantstats 0.0.86 | Apache-2.0, mais **tire yfinance**, matplotlib, seaborn et tabulate. | PyPI |
| ib-async 2.1.0 | BSD-2 sur GitHub, mais classé « Other/Proprietary » sur PyPI. Épingle `tzdata<2026.0` : conflit possible, `A_VERIFIER` au `uv lock`. | PyPI, GitHub |
| Calendriers, base, calcul | exchange-calendars 4.13.2 (Apache-2.0), pandas-market-calendars 5.5.0 (MIT), duckdb 1.5.6 (MIT), numpy 2.5.4, pandas 3.0.6, scipy 1.18.1, scikit-learn 1.9.1, cvxpy 1.9.3 (Apache-2.0). | PyPI |
| **B65** (hook MCP en session réelle) | Dans cette session, le hook `guard_mcp.py` a refusé `mcp__Claude_Browser__javascript_tool` (outil non listé). Le matcher `^mcp__` se déclenche donc bien en session réelle. **B65 peut être clos.** | journal de cette session |

## 2. Périmètre et étiquettes de parité (§10.1)

| Fonction | Livré en phase 2 | Étiquette (spec) | Reporté |
|---|---|---|---|
| F1 Données | référentiel versionné, cours bruts et opérations sur titres, change et taux BCE, contrôles qualité, base point-in-time | `[Approximation]` | OpenBB (D3), crypto, macro FRED/INSEE, actualités par fournisseur |
| F2 Portefeuille | import CSV, positions et cash multidevise reconstruits depuis les transactions, rapprochement quotidien avec le relevé du courtier | `[Parité]` | API IBKR (D5) ; blocage des intentions par le rapprochement (phase 4, il n'y a pas d'intention avant) |
| F3 Risque | volatilité historique et GARCH, VaR et CVaR (historique, paramétrique, Monte-Carlo), backtest de Kupiec, drawdown, bêta, corrélations, HHI, contributions au risque, stress hypothétiques et historiques, variation de VaR entre deux dates, régression factorielle si la source est validée (D9) | `[Approximation]` | — |
| F4 Optimisation | moyenne-variance contrainte, min-CVaR, parité de risque, HRP, covariance avec shrinkage, contraintes de poids, de secteur, de rotation et de coûts ; **proposition seulement** | `[Parité]` | intentions d'ordre (phase 4) |
| F9 Performance | TWR, MWR, volatilité, Sharpe, Sortino, drawdown, contributions par position et par secteur, export annuel des plus-values | `[Parité]` | attribution Brinson contre l'indice, rapport HTML |
| F10 Copilot | les cinq requêtes du §10.10 couvertes par les évals | `[Parité]` d'architecture | — |

Une approximation n'est jamais présentée comme une parité : l'étiquette figure dans la sortie de chaque outil et le rubric la vérifie.

## 3. Données : référentiel, point-in-time, qualité (F1) — ADR-012 et ADR-013

**Stockage (ADR-012).** Base SQLite de la bibliothèque standard dans `var/finance/finance.db` (ignorée par git), avec un schéma versionné et des migrations testées (D6). Tables :

- `instruments` : référentiel versionné (`valid_from`, `valid_to`) ; ISIN, nom, classe d'actif, devise, place (MIC), secteur, pays, duration pour les obligations (saisie, `A_DEFINIR` par ligne) ;
- `instrument_ids` : identifiant par source ;
- `prices` : cours **bruts** non ajustés, volume, source, `published_at`, `ingested_at`, révision ;
- `corporate_actions` : splits et dividendes, avec date ex, `published_at` et `ingested_at` ;
- `fx_rates` et `rates` : change de référence et taux (€STR, courbe de rendement) de la BCE ;
- `quality_scores` : score par série et par date d'évaluation.

**Point-in-time (R10).** Toute lecture prend une date `as_of`. Une ligne n'est visible que si `published_at ≤ as_of`, dans sa dernière révision publiée avant cette date. Les cours ajustés sont calculés à la lecture avec les seules opérations connues à `as_of`. Une série ajustée en arrière, comme celle que livrent les fournisseurs, intègre en effet des splits futurs : c'est une fuite d'information. `ingested_at` sert à l'audit et au mode strict « connu à », que l'on utilisera pour rejouer une décision passée.

**Ingestion.** `cerveau finance sync` (CLI lancée par Lucas, réseau, écriture journalisée) est séparée des outils, qui ne font que lire la base (classe LECTURE). Fournisseurs derrière une interface `MarketDataProvider` :

- `fixtures` : hors ligne, pour les tests et les évals ;
- `csv` : cours exportés par Lucas, par exemple depuis son courtier ;
- `ecb` : change de référence, €STR et taux (httpx, sans clé) ;
- le fournisseur de cours choisi en D1.

**Contrôles qualité.** Quatre sous-scores dans [0, 1] par série :

- trous : séances manquantes par rapport au calendrier de la place (exchange-calendars) ;
- opérations sur titres : saut de cours inexpliqué, ou split déclaré sans saut ;
- cours aberrants : z-score robuste (médiane et MAD) des rendements ;
- fraîcheur : dernière séance attendue contre dernière séance reçue.

Le score est le **minimum** des quatre : aucun poids à régler, et une seule anomalie suffit à faire baisser le score. Sous `min_quality_score_above_N1`, la décision est plafonnée à N1 et la réponse affiche le score. Tant que ce seuil vaut `A_DEFINIR`, l'outil signale « qualité non évaluable » (R7, D12).

## 4. Portefeuille (F2)

- **Format CERVEAU** (CSV documenté) : date, compte, type (achat, vente, dividende, frais, dépôt, retrait, change), identifiant, quantité, prix, devise, frais. Un adaptateur par courtier convertit l'export réel (D4).
- **Import** : `cerveau portfolio import <fichier> --format <courtier>`, lancé par Lucas. L'import est idempotent (empreinte du fichier) et journalisé, et le planificateur n'a pas cet outil. Le CSV est un contenu externe : ses champs texte sont bornés en longueur et passent `injection_signals` (R5).
- **Positions** : reconstruites depuis les transactions (quantité et prix moyen pondéré), cash par devise, valeur en EUR au change BCE.
- **Rapprochement** : `cerveau portfolio reconcile <relevé>` compare les positions calculées au relevé de positions du courtier. Tout écart produit une alerte dans la CLI et le journal, et marque `rapprochement: ecart` dans chaque sortie d'outil. Le blocage des intentions arrive en phase 4 (il n'y a aucune intention avant).
- **IBKR** : export CSV ou Flex téléchargé par Lucas, via l'adaptateur CSV (D5). Aucune connexion de compte par Claude Code.
- **Portefeuille de référence fictif** : `tests/fixtures/finance/reference/`. Il contient une dizaine d'instruments fictifs (`FICT-…`), répartis entre actions, ETF, obligations et or, en EUR, USD et GBP, avec du cash EUR et USD. Il est accompagné de trois ans de cours **synthétiques**, générés par un script à graine fixe (script et CSV versionnés). Aucune donnée d'un fournisseur n'est commise, à cause de leurs droits de redistribution et de l'ouverture publique prévue en phase 8. Anomalies placées volontairement :
  - un split, des dividendes ;
  - un trou, un cours aberrant ;
  - une hausse de volatilité et un renforcement de position la dernière semaine, pour la question « pourquoi la VaR a-t-elle augmenté depuis lundi ? » ;
  - une obligation avec duration.

## 5. Risque (F3) — ADR-014 (conventions de calcul)

- **Conventions** :
  - rendements simples, convertis en EUR au change BCE ;
  - alignement sur les séances communes ;
  - VaR et CVaR exprimées comme une perte positive, en EUR et en % de la valeur ;
  - mise à l'échelle √h étiquetée `[Approximation]` ;
  - quantile historique selon une interpolation documentée.
- **Mesures** :
  - volatilité historique et GARCH(1,1) (arch) ;
  - VaR et CVaR historique, paramétrique et Monte-Carlo (graine fixe, donc déterministe) ;
  - backtest de Kupiec (LR de couverture) ;
  - drawdown courant et maximal ;
  - bêta contre l'indice (D8), matrice de corrélation, HHI ;
  - contributions marginales et par composante (Euler) à la volatilité et à la VaR.
- **Variation de VaR entre deux dates** : la VaR est calculée à chaque date, et l'écart est décomposé en un effet positions (nouveaux poids, ancienne covariance), un effet marché (anciens poids, nouvelle covariance) et un résidu. Cela répond à la première question du §10.10 sans laisser le LLM inventer l'explication.
- **Stress hypothétiques** :
  - taux +100 pb : duration pour les obligations, sensibilité estimée aux taux BCE pour le reste, étiquetée `[Approximation]` ;
  - actions −20 %, directement et ajusté du bêta ;
  - EUR/USD ±10 % : réévaluation exacte ;
  - choc sectoriel paramétrable.

  Le LLM ne choisit l'ampleur du choc qu'à partir de la question, dont les chiffres sont admis par R1.
- **Stress historiques** : fenêtres de crise `A_VERIFIER` (D10), appliquées seulement si les données couvrent la fenêtre ; sinon la sortie dit « non couvert ».
- **Facteurs** : régression sur la source validée en D9 ; sans source, la mesure est « non disponible » (R7).
- **Paramètres** : nouvelle section `market_risk` de `config/risk.yaml` (niveaux de confiance, horizons, fenêtre, tirages, graine, fenêtre de Kupiec, scénarios), à `A_DEFINIR` jusqu'à D7.
- **Critère « calcul indépendant »** : sur le portefeuille de référence, chaque mesure est recalculée par une implémentation indépendante. Il s'agit des mesures de skfolio quand la définition est identique, sinon de formes fermées (VaR paramétrique normale, portefeuille à un actif, actifs indépendants). Les deux résultats sont comparés à la tolérance de D11. Monte-Carlo est comparé à la forme fermée avec une tolérance statistique, et GARCH sur sa capacité à retrouver des paramètres connus sur données simulées. Si une définition diffère (interpolation du quantile, par exemple), je l'écris dans l'ADR et j'aligne le test sur la même définition, jamais l'inverse.

## 6. Optimisation (F4)

- **skfolio** : `MeanRisk` (variance ou CVaR), `RiskBudgeting` (parité de risque), `HierarchicalRiskParity`, covariance avec shrinkage (Ledoit-Wolf). Je lis la documentation 1.8.x avant usage : la contrainte de rotation et les coûts de transaction sont `A_VERIFIER` dans l'API.
- **Contraintes** :
  - positions longues seulement, sans levier (cohérent avec `risk_limits.paper.yaml`) ;
  - poids maximal, plafonds par secteur, rotation maximale, frais (D13).
- **Sortie** : poids cibles, liste d'opérations en quantités entières (arrondi déterministe), rotation, frais estimés, risque avant et après. La sortie est étiquetée « proposition non exécutée » en N1 et « analyse » en N0. Tant que les frais valent `A_DEFINIR`, l'outil donne les poids cibles mais refuse la liste d'opérations (R7).
- **Tests de propriétés (Hypothesis)** : somme des poids égale à 1, bornes respectées, contributions égales à la tolérance près pour la parité de risque, rotation sous le plafond, solution analytique retrouvée sur deux actifs.

## 7. Performance et attribution (F9)

- **Mesures** : TWR (chaînage quotidien hors flux), MWR (XIRR), volatilité, Sharpe et Sortino (taux sans risque €STR, D8), drawdown maximal, Calmar. Elles sont recoupées avec les mesures de skfolio sur le portefeuille de référence.
- **Attribution** : contributions au rendement par position et par secteur, avec le résidu affiché ; attribution factorielle seulement si D9 est validée. Brinson contre l'indice demande la composition sectorielle de l'indice : reporté.
- **quantstats écarté** : il tire yfinance et la pile graphique. Les métriques sont maison, testées et recoupées (D14).
- **Plus-values** : `cerveau finance plus-values --annee AAAA` écrit un CSV dans `var/finance/exports/`. Pour chaque cession, il donne le prix moyen pondéré, les frais et la plus-value brute en EUR au change BCE du jour. Les règles fiscales sont `A_VERIFIER` (article 150-0 D du CGI, à confirmer avec sa source). Il n'y a **aucun calcul d'impôt ni de déclaration**.

## 8. Copilot (F10) : outils, orchestrateur, R1 — ADR-015

**Cinq outils Finance (R13 : 3 à 5 par domaine)**, plus `web_search` et `web_read` partagés avec le pack Généraliste pour les actualités et l'analyse de société (D15) :

| Plugin | Outil | Classe | Entrée → sortie |
|---|---|---|---|
| `finance_data` | `market_data` | LECTURE | instruments, `as_of`, type (`cours`, `referentiel`, `fondamentaux`) → séries ou fiches, score qualité, fraîcheur |
| `finance_portfolio` | `portfolio_snapshot` | LECTURE | `as_of` → positions, cash, poids, expositions par secteur, pays et devise, état du rapprochement |
| `finance_risk` | `risk_report` | CALCUL | `as_of`, mesures, `compare_to`, scénarios → mesures, contributions, stress, décomposition de la variation |
| `finance_optimize` | `rebalance_proposal` | CALCUL | méthode, contraintes → proposition (§6) |
| `finance_report` | `performance_report` | CALCUL | période → performance et attribution (§7) |

- **Fondamentaux** : multiples et états financiers résumés, marqués « non point-in-time » (révisés par le fournisseur), donc exclus de tout backtest. Valorisation par multiples ; un DCF relève de F6 et reste reporté.
- **Texte externe** : `finance_data` ne renvoie aucun texte libre de fournisseur (ni description ni actualité). Les noms d'instruments sont bornés et passent `injection_signals`. Les actualités passent par `web_research` et le lecteur (R5, ADR-008). L'ordre « par impact » de la cinquième question suit l'exposition de la position, qui vient de l'outil. Le jugement qualitatif du LLM est étiqueté comme opinion (R12).
- **Orchestrateur** :
  - `PACKS` gagne `finance` et le prompt de routage connaît ce domaine ;
  - le manifeste du pack liste ses plugins, et le nœud de routage ouvre une boîte à outils multi-plugin, limitée à `max_tools_to_planner` ;
  - le démarrage de chaque plugin passe dans son manifeste (**B26**, ADR-015) ;
  - le kill switch est vérifié avant chaque appel de modèle (**B70**).
- **Traçabilité R1** :
  - chaque nombre d'une sortie d'outil porte sa valeur, son affichage français (« 2,34 % », « 12 450 € ») et un identifiant ;
  - le vérificateur rapproche chaque nombre de la réponse d'une valeur ou d'un affichage, en tenant compte du passage fraction ↔ % et de l'arrondi à la précision affichée ;
  - il contrôle aussi les dates, les petits entiers (**B33**) et le sens d'une variation (**B35**) ;
  - un nombre orphelin déclenche `[VERIFICATION REQUIRED]` ;
  - l'enregistrement d'audit garde la table nombre → appel d'outil, ce qui mesure le critère « 100 % des chiffres traçables ».
- **Autonomie** : la finance reste en **N0** (`autonomy.yaml`), et Claude Code ne la change jamais. En N0, le résultat de l'optimiseur est présenté comme une analyse. La promotion N0 → N1 est faite par Lucas, à la main, après le rapport (D16).
- **R16** : le rubric Finance exige la mention « aide à la décision personnelle, pas un conseil en investissement » dès qu'une réponse compare des choix. Toute demande d'ordre est refusée, puisqu'aucune classe FINANCIERE n'existe en phase 2.

## 9. Évaluations

| Élément | Contenu | Critère mesuré |
|---|---|---|
| `domain_packs/finance/` | manifeste (plugins, autonomie maximale N4 comme `autonomy.yaml` — le §9.2 prévoit N2, puis N3 et N4 par promotion —, niveau courant N0), `prompts/role.md`, `prompts/rubric.md`, `knowledge/sources.yaml`, `evals/golden.jsonl`, `evals/behaviors.yaml`, `README.md` | — |
| Golden set Finance | **60 cas**, rédigés par moi, validés par toi, puis **gelés** (R9). Répartition : 15 sur les requêtes du §10.10 (3 variantes chacune), 10 risque, 6 stress, 6 optimisation, 6 performance et attribution, 6 données, qualité et point-in-time, 4 portefeuille et rapprochement, 7 refus (R16, ordre, hors périmètre). Chaque cas fixe les outils attendus et les chiffres attendus du portefeuille de référence. | ≥ 50 cas ; score au rubric ≥ seuil D17 (mode réel) |
| Comportements Finance | R1 (traçabilité), R10 (`as_of` respecté), R12 (étiquettes), R16, étiquettes de parité, « analyse » en N0 contre proposition, qualité faible signalée et plafonnée, ≥ 5 cas chacun | R1–R5 = 1,0 ; 100 % des chiffres traçables |
| Red teaming Finance | ≥ 10 cas : consignes dans un CSV importé, un nom d'instrument ou une page d'actualité | 0 violation R5 |
| Indépendance | tests du §5 sur le portefeuille de référence | 100 % des mesures à la tolérance D11 |

- **Hors ligne (CI)** : modèles factices scriptés, base de fixtures. Ce mode vérifie la plomberie, les chiffres attendus et la traçabilité.
- **Réel** : bloqué tant que les budgets restent `A_DEFINIR` (D19), puis lancé avec ton accord à chaque campagne. Le pack Finance ne devient « actif » qu'avec un score mesuré en mode réel.
- **Rapport** : `evals/reports/phase-2-<date>.md` et JSON.

## 10. Tests (aucun réseau en CI)

- Tests unitaires par module ; propriétés Hypothesis (point-in-time, optimisation, positions) ; recoupements indépendants (§5).
- Serveurs MCP testés en client/serveur en mémoire.
- Import CSV : formats invalides, doublons, champs piégés.
- Anti look-ahead : un cours publié après `as_of` n'apparaît jamais, et un split futur ne modifie pas un cours passé.
- Contrôles qualité testés sur les anomalies placées.
- Fournisseurs (BCE, D1) testés avec `httpx.MockTransport` et des réponses synthétiques ; `pytest-socket` bloque le reste.

## 11. Nouvelles dépendances (installées avec uv)

| Paquet | Version | Licence | Rôle |
|---|---|---|---|
| numpy | 2.5.4 | BSD-3 | calcul |
| pandas | 3.0.6 | BSD-3 | séries |
| scipy | 1.18.1 | BSD-3 | lois, optimisation, XIRR |
| arch | 8.0.0 | NCSA | GARCH |
| skfolio | 1.8.1 | BSD-3 | optimisation, shrinkage, recoupement des mesures (tire cvxpy-base, clarabel, scikit-learn, plotly) |
| exchange-calendars | 4.13.2 | Apache-2.0 | calendriers des places |

Licences de numpy, pandas et scipy à confirmer par `pip-licenses` au moment de l'ajout. skfolio 1.9.4 a été publiée la veille, et les versions 1.8.2 à 1.9.4 ont toutes moins de 7 jours au 18/10/2026 : j'épingle 1.8.1 (10/10/2026), la plus récente d'au moins 7 jours (prudence vis-à-vis de la chaîne d'approvisionnement).

**Écartés** :

- `yfinance` : CGU Yahoo ;
- `openbb*` : D3, et `openbb-yfinance` est sous AGPL ;
- `quantstats` : tire yfinance ;
- `riskfolio-lib` : lourd, skfolio suffit ;
- `PyPortfolioOpt` : pas de parité de risque native ;
- `ib-async` : D5 ;
- `duckdb` : SQLite suffit ;
- `pandas-market-calendars` : exchange-calendars suffit.

`docs/licences.md` et `pip-audit` seront mis à jour.

## 12. Décisions demandées à Lucas

| # | Décision | Options | Ma recommandation |
|---|---|---|---|
| D1 | Source des cours | yfinance / Tiingo Starter (gratuit, API officielle, usage interne) / fournisseur couvrant Euronext (EODHD, FMP… CGU et prix `A_VERIFIER`) / cours en CSV seulement | **Pas de yfinance** (CGU, R15). Interface + CSV tout de suite, puis Tiingo si tes titres sont surtout US, sinon un fournisseur Euronext que je vérifie. Tu crées le compte et la clé (variable d'environnement) ; je ne la lis jamais. |
| D2 | `config/data_sources.yaml` | passer `yfinance` à `enabled: false` (resserrement), `ecb` à `enabled: true` avec ses conditions vérifiées | **Oui** |
| D3 | OpenBB | maintenant (stdio, catégories autorisées, `install_skill` exclu par la liste du manifeste) / backlog | **Backlog** : pile lourde, outil qui écrit sur le disque, intérêt seulement avec des fournisseurs à clé. Écart au livrable écrit dans ADR-013. |
| D4 | Courtier(s), comptes et marchés | à toi : courtier, PEA ou CTO, places, crypto oui ou non | Donne-moi le courtier ; j'écris l'adaptateur de son export. Crypto (ccxt) au backlog. |
| D5 | IBKR en lecture | export CSV ou Flex manuel / Flex Web Service (jeton) / ib_async (TWS ou Gateway) | **Export manuel** maintenant : zéro secret, zéro connexion. L'API passe au backlog. |
| D6 | Stockage | SQLite / DuckDB / Postgres (infra Docker) | **SQLite** (bibliothèque standard, un fichier, aucune dépendance) ; migration vers Postgres avec la mémoire (§11). |
| D7 | Paramètres de risque | à toi | Confiance 95 % et 99 % ; horizons 1 et 10 séances ; fenêtre de 500 séances ; 10 000 tirages, graine 2026 ; Kupiec sur 250 séances ; chocs du §10.4 (+100 pb, −20 %, ±10 %). |
| D8 | Indice de référence et taux sans risque | à toi | Un ETF MSCI World en EUR, dividendes réinvestis (ticker à vérifier) ; €STR de la BCE. |
| D9 | Source des facteurs | Kenneth French Data Library (CGU `A_VERIFIER`) / pas de régression en phase 2 | French si ses conditions le permettent, sinon backlog. |
| D10 | Fenêtres de crise | 2008 (faillite de Lehman), 2020 (Covid), 2022 (hausse des taux), dates exactes `A_VERIFIER` | Oui ; je relève les dates avec leur source avant usage. |
| D11 | Tolérance du critère d'indépendance | à toi | Écart relatif 1e-9 pour une même définition ; 2 % pour Monte-Carlo contre la forme fermée (100 000 tirages). |
| D12 | Qualité des données | `max_staleness` en séances ; `min_quality_score_above_N1` | 1 séance (données de clôture) ; seuil 0,90. |
| D13 | Frais et glissement | à toi : commission, minimum par ordre, glissement | Ceux de ton courtier ; d'ici là, pas de liste d'opérations (R7). |
| D14 | quantstats | écarté, métriques maison recoupées / ajouté | **Écarté** (il tire yfinance). |
| D15 | Nombre d'outils (R13) | 5 outils Finance + 2 outils web partagés / 8 outils plus fins | **5 + 2** ; une capacité ne s'ajoute que si les évals le montrent. |
| D16 | Promotion Finance N0 → N1 | ajouter `promotion.finance.N0_to_N1` (golden ≥ D17, 0 violation R1–R5, signature manuelle) dans `autonomy.yaml`, après relecture par `risk-gate-auditor` | **Oui** ; c'est toi qui fais la promotion. |
| D17 | Seuil du golden Finance | à toi, **fixé avant la première mesure** | 0,85 |
| D18 | Dette du backlog incluse | à choisir | **Incluses** : B26, B33, B35, B48 (couvert par les outils CALCUL Finance), B61, B70, plus le durcissement de `web_research` pour les actualités (B22, B24, B66, B67, B68, B72) ; B21 et B65 clos (§1). **Reportées** : B38–B41, B43, B69 (dépendent d'une campagne réelle), B29, B32, B62, B71, B73. |
| D19 | Budgets jour et mois (toujours `A_DEFINIR` depuis la phase 1) | à toi | Sans eux, ni `cerveau ask` réel ni score réel du golden Finance (§9). |
| D20 | Revues | `security-reviewer` seul (exigé par le §17) / plus `quant-reviewer` une fois en fin de phase | **Les deux** : les calculs de risque méritent une relecture quantitative. Coût : une revue de plus en tokens. |
| D21 | Dépendances du §11 | accepter / modifier | Accepter |

## 13. Hors périmètre → `docs/backlog.md`

- OpenBB MCP (D3) et ses fournisseurs à clé.
- Crypto (ccxt), macro FRED et INSEE.
- API IBKR (D5).
- Blocage des intentions par le rapprochement (phase 4).
- Attribution Brinson, rapport HTML de performance.
- DCF et valorisation d'instruments (F6), backtest (F5).
- Synchronisation planifiée et alertes ntfy.
- Actualités par fournisseur (aujourd'hui via `web_research`).
- Fondamentaux point-in-time.
- Migration vers Postgres.

## 14. Commits atomiques (en anglais, `make ci` vert à chaque étape)

1. `docs: add the validated phase 2 plan`
2. `docs(adr): add ADR-012 to ADR-015 (finance store, market data sources, risk conventions, multi-plugin toolbox)`
3. `chore(deps): add phase 2 dependencies`
4. `feat(config): add market risk, cost and data quality parameters`
5. `feat(registry): declare the plugin runtime in the manifest (B26)`
6. `feat(finance): add the point-in-time store and the instrument reference`
7. `feat(finance): add data quality checks`
8. `feat(finance): add the CSV and ECB providers and cerveau finance sync`
9. `test(finance): add the fictitious reference portfolio and synthetic prices`
10. `feat(finance): add CSV portfolio import, positions and reconciliation`
11. `feat(plugins): add the finance_data and finance_portfolio MCP servers`
12. `feat(plugins): add finance_risk with independent cross-checks`
13. `feat(plugins): add finance_optimize`
14. `feat(plugins): add finance_report and the capital gains export`
15. `feat(verification): trace tool numbers, dates and signs (R1, B33, B35)`
16. `feat(orchestrator): open multi-plugin toolboxes, route to the finance pack, check the kill switch before each model call (B70)`
17. `fix(web_research): harden robots cache, ports and error messages (B22, B24, B66–B68, B72)`
18. `test(evals): add the finance pack, golden set, behaviour and red-team suites`
19. `docs: update licences, threat model and backlog`
20. `docs: add the phase 2 report`

Le commit du fournisseur de cours D1 s'insère après le 8 dès que la source est choisie.

## 15. Coût estimé (non mesuré)

- **Développement** : aucun appel payant, tout passe hors ligne.
- **Campagne d'évals réelle** : environ 60 cas golden et 50 cas de comportement, avec plus d'appels d'outils qu'en phase 1, soit 8 à 15 $ (estimation).
- **Données** : 0 € avec Tiingo Starter ou des CSV ; sinon le prix du fournisseur choisi en D1.

Les vrais chiffres viendront du grand livre et figureront dans le rapport.

## 16. Exécution

- **Où** : dans cette session, ouverte dans `cerveau-plateforme`. Les hooks du projet y sont chargés (preuve : le refus du §1, B65).
- **Ordre** :
  1. décisions ;
  2. ADR, dépendances, configuration ;
  3. base, qualité et fournisseurs ;
  4. fixtures ;
  5. plugins ;
  6. traçabilité R1 ;
  7. orchestrateur ;
  8. évals ;
  9. revues (`security-reviewer`, et `quant-reviewer` selon D20) ;
  10. rapport du §18.
- **Fin de phase** : je m'arrête et j'attends `GO PHASE 3`.
