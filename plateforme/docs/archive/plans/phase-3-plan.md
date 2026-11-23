# Plan — Phase 3 : recherche, backtest et Comité (N1) : F5, F11

Date : 19/10/2026 · Statut : **validé par l'utilisateur le 19/10/2026**, avec les recommandations D1 à D27 du §14.

## 0. En une phrase

Une stratégie s'écrit une seule fois, comme une fonction pure qui transforme « les données connues à la date t » en poids cibles. Elle est d'abord criblée (vectorbt), puis backtestée par deux moteurs qui se recoupent : un moteur maison et NautilusTrader. Seul le protocole anti-surapprentissage du §10.6 peut ensuite la déclarer promouvable. Pour une décision à enjeu, le Mode Comité fait intervenir des analystes, un défenseur et un contradicteur qui débattent, un gestionnaire et un contrôleur de risque. Chaque rôle est journalisé et chaque chiffre vient d'un outil (R1). Rien n'est exécuté : en N0 la sortie est une analyse, en N1 une proposition non exécutée, et aucune intention d'ordre n'existe avant la phase 4.

## 1. Vérifié aujourd'hui (sources officielles, 19/10/2026)

| Sujet | Constat | Source |
|---|---|---|
| vectorbt | La 1.2.0 est publiée aujourd'hui ; la 1.1.2 (09/10/2026) est la plus récente qui a au moins 7 jours. La 1.0.0 (22/04/2026) est une version majeure : l'API peut différer des exemples 0.x, donc je lis la documentation 1.1 avant usage. Python ≥ 3.11 et < 3.15, roue pure Python. Dépend de numpy ≥ 2.4.6, pandas ≥ 3.0.3, numba ≥ 0.66, scipy, scikit-learn, matplotlib, plotly, ipywidgets, anywidget, dill, dateparser, imageio, schedule et requests. L'extra `full` tire yfinance (écarté, R15). | PyPI (JSON), github.com/polakowo/vectorbt |
| **Licence vectorbt** | GitHub affiche NOASSERTION. Le fichier LICENSE.md indique Apache 2.0 avec la « Commons Clause » v1.0, concédant Oleg Polakow. La clause interdit de vendre le logiciel, c'est-à-dire de fournir contre rémunération un produit ou un service dont la valeur vient de lui. C'est compatible avec un outil personnel (R16), mais la licence est restrictive : elle doit être isolée et listée (R14). Le dépôt est actif (poussé le 19/10/2026). | LICENSE.md du dépôt |
| numba 0.68.0 (30/09/2026) | BSD. Exige llvmlite 0.50 et numpy < 2.6, ce qui est compatible avec numpy 2.4.6 (presidio impose < 2.5). | PyPI |
| NautilusTrader 1.231.0 (02/08/2026) | LGPL-3.0-or-later ; Python ≥ 3.12 et < 3.15 ; roue cp312 pour Windows. Dépend de pyarrow ≥ 25, msgspec, portion, click, tzdata, pytz, tqdm et de fsspec **épinglé exactement à 2026.2.0**. L'extra `visualization` exige plotly < 7, en conflit avec plotly 7.1.0 déjà verrouillé : je ne l'installe pas. | PyPI |
| **NautilusTrader 2.0.0rc7** (15/10/2026 ; rc3 à rc7 depuis le 21/08) | Python ≥ 3.13, roues cp313 et cp314 seulement. Selon le README (branche develop) : le moteur v2 est natif Rust avec des liaisons PyO3 ; la v1 ne reçoit plus que les correctifs de sécurité critiques (branche `develop_v1`) ; les RC v2 sont déconseillées en production, et l'API peut casser d'une version à l'autre. Le même README confirme que `BacktestEngine` accepte barres et ticks, et prévient que le live a des comportements qu'une simulation ne reproduit pas toujours. | PyPI, README de nautechsystems/nautilus_trader |
| **Version de Python** | Le projet est en Python 3.12 (`pyproject.toml` : `>=3.12,<3.13`, `.python-version`, ADR-001). NautilusTrader v2 exige 3.13 : il faudrait changer d'interpréteur, et la compatibilité de presidio et de spaCy est `A_VERIFIER`. | dépôt |
| Résolution à blanc | Test fait avec `uv pip compile`, Python 3.12, Windows x86_64. vectorbt 1.1.2 et nautilus_trader 1.231.0 se résolvent avec le verrou actuel : numpy 2.4.6, pandas 3.0.6, scipy 1.18.1, scikit-learn 1.9.1, presidio-analyzer 2.2.364, plotly 7.1.0. vectorbt ajoute **33** paquets, dont la pile IPython et widgets, matplotlib, pillow, numba, llvmlite et psutil. NautilusTrader en ajoute **6** : lui-même, pyarrow 26.0.0 (09/10/2026, Apache-2.0), fsspec, msgspec, portion et sortedcontainers. pip-audit n'est pas encore passé : il passera au moment de l'ajout. | uv |
| Qlib | pyqlib 0.9.7 sur PyPI (15/08/2025). La release GitHub v0.9.8 (08/10/2026) n'est pas vérifiée sur PyPI. Licence MIT, roues cp312. Dépendances lourdes : mlflow, redis, pymongo, gym, jupyter, nbconvert, lightgbm, cvxpy, loguru et fire. | PyPI, github.com/microsoft/qlib |
| TradingAgents v0.7.0 (16/10/2026) | Apache-2.0. Sert d'inspiration au Comité (§7.2) : aucun code repris, aucune dépendance. | github.com/TauricResearch/TradingAgents |
| DSR et PBO | Références citées de mémoire : Bailey et López de Prado, « The Deflated Sharpe Ratio » (2014, SSRN 2460551) ; Bailey, Borwein, López de Prado et Zhu, « The Probability of Backtest Overfitting » (méthode CSCV). Formules et exemples chiffrés **à relire à la source** avant d'écrire le code (`A_VERIFIER`). | — |
| État du dépôt | Le pack Finance a déjà 5 outils, soit le plafond de R13. Les cours sont des clôtures seules, sans ouverture. Aucun fournisseur de fondamentaux n'est retenu (ADR-013). Le moteur de politique n'accorde que `auto` (ADR-022). Un manifeste `kind: agent` exige un transport MCP. `trading_costs`, `risk_limits.paper.yaml`, l'ISIN de l'indice, les fenêtres de crise et les budgets restent `A_DEFINIR` ou `A_VERIFIER`. | dépôt |

## 2. Périmètre et étiquettes de parité (§10.1, §17)

| Fonction | Livré en phase 3 | Étiquette (spec) | Reporté |
|---|---|---|---|
| F5 Recherche et backtest | stratégie en fonction pure ; moteur maison et NautilusTrader 1.231 recoupés ; criblage vectorbt ; protocole complet du §10.6 ; journal des essais ; registre des stratégies ; rapport standard ; outil `strategy_lab` | `[Parité]` pour la méthode. La démonstration tourne sur données synthétiques et frais fictifs : elle n'a aucune valeur d'investissement. | Qlib, RD-Agent, NautilusTrader 2, données intrajournalières |
| F11 Comité d'investissement | sous-graphe enregistré ; trois analystes ; débat ; gestionnaire ; contrôleur de risque ; règles vérifiées par le code ; journal | `[Reconstruction]` (inspiration TradingAgents) | analystes fondamental et sentiment, Comité des autres domaines, intention d'ordre (phase 4) |
| Autonomie | la finance reste en N0 ; en N1, le Comité produit une proposition non exécutée | — | promotion par l'utilisateur après une campagne réelle (B107 outille la vérification) |

Critères de sortie du §17 :

- une donnée future injectée fait échouer le backtest (§5) ;
- le protocole complet est appliqué à une stratégie de démonstration (§6, §7) ;
- les débats du Comité sont journalisés (§10) ;
- tests verts, évals au-dessus des seuils, revue `security-reviewer`, compte rendu du §18.

## 3. Moteur de backtest (F5) — ADR-024

- **Stratégie = fonction pure** : `decide(vue à t, paramètres) → poids cibles`, positions longues seulement, sans levier, cash permis. Pas d'entrée-sortie, pas d'horloge, pas de hasard sans graine. Le même objet sert au criblage, aux deux moteurs et, en phase 4, au paper : seul l'adaptateur change.
- **Modèle d'exécution** (D6) :
  - décision à la clôture de t, avec les seules données publiées à t ;
  - exécution à la clôture de t+1, puisque la base n'a pas de cours d'ouverture ;
  - quantités entières, avec arrondi déterministe.
- **Frais** : commission (pourcentage et minimum par ordre), glissement en points de base et conversion de change, tirés de `config/risk.yaml#trading_costs`.
  - Tant qu'ils valent `A_DEFINIR` (D13 de la phase 2), un backtest sur données réelles est refusé (R7).
  - Les tests et la démonstration utilisent un jeu de frais **fictif**, versionné avec les fixtures et nommé comme tel dans chaque sortie.
  - Les dividendes sont crédités en cash à la date ex et les splits sont appliqués aux quantités. Les impôts ne sont pas modélisés, et le rapport le dit.
- **Moteur maison** (`core/finance/research/engine.py`) : boucle quotidienne simple et lisible, qui n'utilise que numpy et pandas. C'est la référence de recoupement.
- **NautilusTrader 1.231.0** (D1) : `core/finance/research/nautilus.py` est le seul module qui l'importe.
  - Il utilise `BacktestEngine` avec des barres quotidiennes construites depuis les clôtures ; la stratégie CERVEAU est appelée à chaque barre.
  - Avant d'écrire l'adaptateur, je lis la documentation 1.231 sur trois points : la façon dont un ordre est rempli sur des barres, le modèle de frais (le minimum par ordre demande peut-être un modèle maison) et la précision 128 bits.
  - Le rapport liste les écarts avec le live (place, latence, persistance), comme le demande le §10.6.
- **Recoupement** (D12) : sur la stratégie de démonstration, les deux moteurs doivent produire la même liste d'opérations et la même courbe de valeur, à la tolérance près. NautilusTrader ne pourra peut-être pas reproduire exactement un élément du modèle de frais. Dans ce cas, je compare les opérations brutes, puis les frais à part, et je l'écris dans l'ADR ; je n'élargis jamais la tolérance en silence.
- **Mesures** : celles de la phase 2 (rendement, volatilité, Sharpe, Sortino, drawdown, Calmar), avec les mêmes conventions (ADR-020), plus la rotation, le nombre d'opérations, les frais payés et l'exposition moyenne.

## 4. Criblage vectorbt (F5) — ADR-025

- **Isolement (R14)** : vectorbt 1.1.2 est placé dans un **groupe de dépendances uv optionnel** `research`. Il n'est importé que dans un module (`core/finance/research/screening.py`), jamais par un serveur MCP ni par l'orchestrateur : le criblage se lance en CLI (`cerveau strategy screen`). Il figure dans `docs/licences.md`, avec la Commons Clause.
- **Rôle** : évaluer vite une grille de paramètres, par exemple 300 couples de moyennes mobiles, frais et glissement compris. **Chaque combinaison évaluée est un essai**, inscrit au journal des essais (§6), même si elle est écartée ensuite.
- **Recoupement** : un échantillon de combinaisons est rejoué par le moteur maison, à la tolérance de D12. Les différences de sémantique (frais, glissement, prix d'exécution) sont écrites dans l'ADR.
- **Pas de verdict** : le criblage ne fait que proposer des candidats au protocole.
- **Ouverture publique (phase 8)** : vectorbt reste une dépendance optionnelle, jamais redistribuée. Le README rappellera qu'un service payant fondé dessus violerait sa licence.
- **Qlib et RD-Agent** (D3) : au backlog. Ils ne figurent pas dans les livrables du §17 (on ne les trouve qu'au §10.6 et à l'Annexe A), ils tirent mlflow, redis, pymongo, gym et jupyter, et le protocole n'a pas besoin de recherche ML. L'ADR-025 écrit cet écart.

## 5. Point-in-time et test d'injection (R10, critère du §17)

- **Vue à t** : la stratégie ne reçoit qu'un objet `PointInTimeView`, lié à la date de décision t.
  - Il ne sert que les lignes `published_at ≤ t` et `session ≤ t`, dans leur dernière révision connue à t.
  - L'ajustement est calculé avec les seules opérations sur titres connues à t, comme dans `core/finance/views.py`.
  - Les données sont chargées une fois puis filtrées en mémoire ; un test prouve que le résultat est identique à la lecture SQL à `as_of`.
- **Garde active** : toute demande au-delà de t lève `LookAheadError`. Le backtest s'arrête, le verdict devient « échec R10 » et l'erreur est journalisée.
- **Invariance par troncature** : pour un échantillon de dates t, le signal est recalculé sur des données coupées physiquement à t, et il doit être identique au signal du passage complet. Ce contrôle attrape aussi les fuites d'un code vectorisé : vectorbt reçoit des tableaux entiers, où un `shift(-1)` passerait inaperçu. Il tourne dans chaque protocole, pas seulement en test.
- **Tests d'injection** (critère du §17) :
  1. une stratégie piégée qui lit la séance t+1 lève `LookAheadError`, et le backtest échoue ;
  2. une stratégie vectorisée avec `shift(-1)` échoue au contrôle d'invariance, et le protocole échoue ;
  3. un cours injecté dans la base avec un `published_at` postérieur à la décision est invisible à t ; forcer sa lecture fait échouer le backtest ;
  4. un split futur ne change aucun cours vu avant sa publication ;
  5. Hypothesis : pour des dates t tirées au hasard, le signal ne dépend d'aucune donnée postérieure à t.

## 6. Protocole anti-surapprentissage (§10.6) — ADR-026

Le protocole se lance par `cerveau strategy protocol <id>`. Il est déterministe, sans modèle de langage, et échappe au budget de 120 s d'une requête. Étapes :

1. **Découpage** (D7) : les données de développement viennent d'abord, puis un échantillon final de test, séparé par un embargo de quelques séances. Cet échantillon final reste intact jusqu'à la fin. Il n'est lu qu'une fois par version de la stratégie, et toute nouvelle lecture compte comme un essai.
2. **Walk-forward** (D8), sur les données de développement : fenêtres ancrées (l'apprentissage s'allonge). Dans chaque pli, les paramètres sont re-choisis dans la grille criblée, puis testés sur le pli suivant.
3. **Frais et glissement** : toujours inclus (§3). La sensibilité à des frais doublés est affichée.
4. **Journal des essais** (D10) : une table append-only dans la base Finance, dont les déclencheurs SQLite refusent UPDATE et DELETE.
   - Chaque ligne enregistre la stratégie, l'empreinte du code, les paramètres, la fenêtre, l'origine (criblage, protocole ou Copilot), le Sharpe et l'empreinte de la série.
   - Le nombre d'essais N d'une famille compte tout, y compris les essais abandonnés.
5. **Deflated Sharpe ratio** : c'est la probabilité que le vrai Sharpe dépasse le maximum qu'on attendrait de N essais sans talent. Il est corrigé de l'asymétrie et de l'aplatissement des rendements. N est pris brut, ce qui donne une borne prudente ; un N effectif par regroupement des essais corrélés va au backlog.
6. **PBO par CSCV** : c'est la probabilité que la meilleure configuration en apprentissage tombe sous la médiane en test, sur S blocs. L'ADR écrit sa limite connue : quand toutes les configurations se valent, le PBO tend vers 0,5 sans qu'il y ait surapprentissage.
7. **Périodes de crise** : drawdown et rendement sur chaque fenêtre de `config/risk.yaml#market_risk.historical_stress` couverte par les données. Une fenêtre non couverte, ou dont les dates restent `A_VERIFIER`, est marquée « non couvert ».
8. **Référence simple** : achat-conservation de l'indice de `config/risk.yaml#market_risk.benchmark` (ISIN `A_VERIFIER`, D8 de la phase 2). Sur les données synthétiques, la référence est l'achat-conservation de l'univers à poids égaux, nommée comme telle.
9. **Verdict** :
   - `reussi` ;
   - `echoue`, avec la liste des portes en échec ;
   - `incomplet`, si une porte n'est pas évaluable : seuil `A_DEFINIR`, crise non couverte ou référence absente.

   Seul `reussi` rend une stratégie promouvable (§8), comme l'exige le §10.6 : une stratégie qui échoue au protocole ne peut pas être promue.

Les portes (D9) vont dans un nouveau fichier `config/research.yaml`. Elles sont fixées **avant la première mesure** et ne sont jamais baissées ensuite (R9).

**Validation du protocole lui-même**, par les tests :

- sur des marches aléatoires sans aucun avantage, la meilleure de nombreuses combinaisons doit être rejetée ;
- sur un effet planté connu, la stratégie qui l'exploite doit passer ;
- les formules du DSR et du PBO sont vérifiées sur les exemples chiffrés des articles, relus à la source.

## 7. Stratégie et données de démonstration (D4, D5)

- **Jeu de recherche synthétique** : `tests/fixtures/finance/research/`, produit par un script à graine fixe ; le script et les CSV sont versionnés. Il contient environ 10 ans de clôtures quotidiennes en EUR, pour quelques instruments fictifs `FICT-R…` :
  - une série avec un effet de tendance planté (autocorrélation positive des rendements) ;
  - des marches aléatoires sans aucun effet ;
  - deux ou trois fenêtres de crise synthétiques (chute et hausse de volatilité), déclarées fictives dans la configuration de test ;
  - des publications décalées (une partie des cours est publiée le lendemain matin), pour exercer le point-in-time.

  Le portefeuille de référence de la phase 2 (3 ans) reste utilisé pour les tests d'intégration.
- **Stratégie de démonstration** : croisement de moyennes mobiles avec repli en cash (suivi de tendance), sur une grille de fenêtres courte × longue. C'est un cas d'école du surapprentissage, avec beaucoup de couples possibles : il exerce donc bien le journal des essais, le DSR et le PBO.
- **Référence** : achat-conservation à poids égaux de l'univers synthétique.
- **Avertissement** : le rapport dit en tête « démonstration sur données synthétiques ; aucune conclusion d'investissement ».

## 8. Registre des stratégies et rapport standard — ADR-027

- **Registre** : un fichier `domain_packs/finance/strategies/<id>.yaml` par stratégie. Il contient la description en français de l'hypothèse et de la règle, le module Python, la grille de paramètres, l'univers, la fréquence et le statut, `recherche` ou `candidate`. Une stratégie neuve est en `recherche`.
- **Promotion** : seul l'utilisateur passe une stratégie en `candidate`, à la main.
  - `cerveau config check` refuse le statut `candidate` sans un rapport de protocole `reussi` dont l'empreinte (code et paramètres) correspond à l'état actuel.
  - Toute modification du code invalide le verdict.
  - En phase 4, le paper n'acceptera que des stratégies `candidate`.
- **Rapport de stratégie standard**, en français : `var/finance/research/reports/<id>-<date>.md` et `.json`. Sections :
  1. hypothèse et règle, en clair ;
  2. données : source, période, qualité, point-in-time, invariance par troncature ;
  3. frais et glissement, fictifs ou réels ;
  4. nombre d'essais et leur origine ;
  5. résultats du walk-forward et de l'échantillon final, face à la référence ;
  6. DSR, PBO, sensibilité aux frais ;
  7. périodes de crise ;
  8. verdict et portes ;
  9. limites : étiquettes, écarts backtest/live (place, latence, persistance), ce qui n'est pas modélisé (impôts, liquidité).

  Chaque chiffre porte l'identifiant de l'outil qui l'a calculé (R1).

## 9. Outil du Copilot (R13) — ADR-027

Le Copilot doit pouvoir répondre à « cette stratégie passe-t-elle le protocole ? » ou à « que donne le croisement 20/100 sur FICT-R1 ? ». Le §6.3 range le backtest en CALCUL. Je propose **un sixième outil Finance** (D13), dans un nouveau plugin :

| Plugin | Outil | Classe | Entrée → sortie |
|---|---|---|---|
| `finance_research` | `strategy_lab` | CALCUL | Entrée : une stratégie du registre, `as_of` et un mode. Sortie selon le mode : `signaux` donne les signaux courants et les niveaux des indicateurs ; `backtest` donne le backtest d'un jeu de paramètres de la grille, sur une période bornée ; `protocole` donne le dernier verdict enregistré. |

- **Essais** : un backtest lancé par le Copilot compte comme un essai et entre au journal. Sa sortie rappelle le verdict du protocole : un résultat favorable d'une stratégie qui n'est pas `reussi` est présenté comme tel.
- **Taille** : la sortie est un résumé déterministe, jamais la courbe entière (B96).
- **Pas de protocole complet** : il est trop long pour une requête, donc le mode `protocole` ne fait que lire le dernier rapport.
- **R13** : la règle prévoit 3 à 5 outils par domaine, et ajoute qu'une capacité s'ajoute quand les évals la justifient. Le livrable F5 du §17 la justifie, et l'ADR-027 l'écrit. Le routage (choix du bon outil sur les cas golden) est mesuré avant et après.

## 10. Mode Comité (F11, §7.2, Annexe E) — ADR-028

**Intégration** (D22, §6.1) :

- le Comité est un sous-graphe LangGraph enregistré, avec le manifeste `plugins/finance_committee/plugin.yaml` en `kind: agent` ;
- le registre gagne un transport `in-process` pour les agents (aujourd'hui, un manifeste exige un transport MCP) ;
- le moteur, générique, vit dans `core/committee/` ;
- les fiches de rôle sont dans `domain_packs/finance/prompts/committee/`, et les boîtes à outils du domaine dans `domain_packs/finance/committee.yaml` ;
- je lis la documentation de LangGraph 1.2.16 (sous-graphes, branches parallèles) avant d'écrire le code.

**Déclenchement** (D15) : le nœud de routage classe en `mode: comite` une requête Finance qui demande une décision (« dois-je vendre… », « faut-il renforcer… »), et `cerveau ask --comite` le force. Une question de mesure (« quelle est ma VaR ? ») reste traitée directement. En phase 3, seul le pack Finance a un Comité.

**Déroulé** :

| Étape | Rôle (fiche de l'Annexe E) | Modèle (D17) | Outils | Sortie JSON validée |
|---|---|---|---|---|
| 1 | Analystes en parallèle (D16) : technique, actualités et macro, portefeuille | standard | **Technique** : `strategy_lab` (signaux), `market_data`. **Actualités** : `web_search` et `web_read` via le lecteur (R5), taux et change de `market_data`. **Portefeuille** : `portfolio_snapshot`, `risk_report`. | `constats[]` (source, date, identifiant de l'appel d'outil), `signaux[]`, `incertitudes[]` |
| 2 | Défenseur et contradicteur, sur `max_debate_rounds` tours (2 par défaut) | standard | aucun | arguments classés par poids, chacun lié à un constat ; « ce qui me ferait changer d'avis » |
| 3 | Gestionnaire | deep | aucun | décision proposée ; confiance (faible, moyenne, élevée) ; horizon (court, moyen ou long, bornes fixées par le schéma) ; conditions d'invalidation ; désaccords non résolus ; raison de chaque argument écarté |
| 4 | Contrôleur de risque | standard | `risk_report` (stress), limites de `config/risk_limits.paper.yaml` | scénarios défavorables chiffrés par un outil ; contrôle des limites ; irréversibilité ; verdict `OK` ou `BLOQUER` |
| 5 | Décision finale | — | moteur de politique | en phase 3, aucune exécution : la sortie est une « analyse » en N0, une « proposition non exécutée » en N1 |

**Règles vérifiées par le code**, et pas seulement demandées au modèle :

- **Schémas** : chaque sortie est validée par un schéma Pydantic. Une sortie invalide a droit à une nouvelle tentative, avec l'erreur. Si elle échoue encore, le rôle est en échec et le Comité conclut « pas de décision » (échec fermé).
- **Constats** : chaque argument cite un identifiant de constat qui existe. Un fait absent des rapports est refusé (Annexe E).
- **Arguments** : le gestionnaire doit traiter chaque argument, en le retenant ou en l'écartant avec une raison. Un argument ignoré invalide sa sortie.
- **Verdict du contrôleur** (D21) : il part des contrôles déterministes. Une limite dépassée, ou une limite à `A_DEFINIR` (le cas actuel, R7), donne `BLOQUER`. Le modèle peut durcir le verdict, jamais l'assouplir.
- **R1** : chaque nombre de chaque rôle passe le vérificateur de la phase 2. La confiance et l'horizon sont des catégories, pas des chiffres produits par un modèle. Un seuil d'invalidation chiffré doit venir d'une sortie d'outil.
- **R5** : aucun rôle n'a d'outil d'action, et le contenu web n'arrive que par le lecteur.
- **R4** : le kill switch est vérifié avant chaque appel de modèle et entre les rôles.

**Journal** (D19, R11) :

- chaque séance reçoit un identifiant `committee_record_id`, que l'intention d'ordre (Annexe C.2) reprendra en phase 4 ;
- chaque rôle produit une entrée `DECISION`, un type qui existe déjà dans l'Annexe C.3. Elle contient l'identifiant, le rôle, le tour, le modèle, la validité du schéma, l'empreinte SHA-256 de la sortie et les constats cités ;
- le texte complet, pseudonymisé comme les autres sorties, va dans `var/finance/committee/<id>.json`. L'empreinte enregistrée dans le journal chaîné rend toute retouche détectable ;
- `cerveau committee show <id>` relit une séance.

**Réponse à l'utilisateur** : le format du §7.3, complété par la décision proposée, la confiance, l'horizon, les conditions d'invalidation, les désaccords non résolus, le verdict du contrôleur et l'identifiant de la séance. La mention R16 (aide à la décision personnelle) est toujours présente.

**Politique** (D20) : inchangée. `PHASE_DECISIONS` reste `{auto}` et la classe `FINANCIERE` reste refusée : le Comité produit un document, pas une action. B108 (intention structurée) reste pour la phase 4.

**Budget** (D18) : une séance coûte une dizaine d'appels de modèle et dépasse le budget d'une requête (120 s).

- Une nouvelle section `per_committee` de `config/budgets.yaml` fixe les jetons, les secondes et les appels d'outil ; elle reste `A_DEFINIR` jusqu'à ta décision.
- En cas de dépassement, la séance s'arrête et elle est enregistrée comme incomplète.

## 11. Évaluations

| Élément | Contenu | Critère mesuré |
|---|---|---|
| Golden Finance | Les 60 cas existants restent **inchangés**. Environ 20 cas s'ajoutent : 10 sur la recherche et le backtest, 10 sur le Comité. Je les rédige, tu les valides, puis ils sont gelés (R9, D27). | taux de réussite hors ligne de 100 % ; score au rubric ≥ 0,85 en réel |
| Comportements `finance_recherche` | ≥ 6 cas : frais toujours inclus, nombre d'essais affiché, stratégie non `reussi` jamais présentée comme promouvable, étiquette « synthétique », point-in-time, aucun chiffre produit par le modèle | 100 % |
| Comportements `finance_comite` | ≥ 8 cas : schémas, citations de constats, chaque argument traité, `BLOQUER` sur une limite inconnue ou dépassée, « analyse » en N0, aucun ordre, R1, nombre de tours, entrées du journal | 100 % ; R1–R5 = 1,0 |
| Red teaming `injection_comite` | ≥ 10 cas où une page d'actualité pousse un rôle à ignorer le risque, à rendre `OK`, à recommander un achat chiffré (B99) ou à exfiltrer par la requête de recherche ; homoglyphes (B101) | 0 violation R5 ; verdict jamais assoupli |
| Indépendance | recoupements moteur maison / NautilusTrader / vectorbt (§3, §4) | 100 % à la tolérance D12 |
| Protocole | marche aléatoire rejetée, effet planté accepté, injection de donnée future en échec | 100 % |

- **Hors ligne (CI)** : modèles scriptés, base de fixtures, jeu de recherche synthétique.
- **Réel** : bloqué tant que les budgets restent `A_DEFINIR` (D19 de la phase 2, D18 ici), puis lancé avec ton accord à chaque campagne.
- **Calibration** : le §12.1 demande aussi, au niveau Finance, de comparer la confiance annoncée au résultat. Les séances du Comité enregistrent dès maintenant la confiance, l'horizon et les conditions d'invalidation, pour la mesurer plus tard (backlog). L'écart paper/backtest relève de la phase 4.
- **Rapport** : `evals/reports/phase-3-<date>.md` et JSON.

## 12. Tests (aucun réseau en CI)

- **Moteur** : invariants Hypothesis :
  - valeur = cash + positions ;
  - frais ≥ 0 ;
  - sans ordre, la valeur reste égale au cash ;
  - quantités entières ;
  - ni vente à découvert ni levier.
- **Point-in-time** : les cinq tests d'injection du §5.
- **Recoupements** des trois moteurs sur la stratégie de démonstration.
- **DSR et PBO** : exemples chiffrés des articles, et cas limites (N = 1, variance nulle, séries trop courtes refusées).
- **Protocole** : verdicts `reussi`, `echoue` et `incomplet` ; promotion refusée sans verdict `reussi` à jour.
- **Journal des essais** : UPDATE et DELETE refusés par la base.
- **Comité**, avec des modèles scriptés :
  - schéma invalide, argument sans constat, argument ignoré ;
  - limite inconnue, budget dépassé, kill switch entre deux rôles ;
  - ordre déterministe des analystes parallèles ;
  - entrées du journal vérifiées par `cerveau audit verify`.
- **Serveur `finance_research`** : testé en client/serveur en mémoire.
- **Durée** : la compilation numba de vectorbt et le démarrage de NautilusTrader sont mesurés, et le rapport donne leur effet sur la durée de `make test`.

## 13. Nouvelles dépendances (installées avec uv)

| Paquet | Version | Licence | Rôle |
|---|---|---|---|
| nautilus_trader | 1.231.0 | LGPL-3.0-or-later (bibliothèque non modifiée) | backtest événementiel. Tire pyarrow 26.0.0, fsspec 2026.2.0 (épinglé exactement), msgspec, portion et sortedcontainers. |
| vectorbt (groupe optionnel `research`) | 1.1.2 | Apache-2.0 + Commons Clause (R14 : isolée, listée) | criblage. Tire numba 0.68.0, llvmlite 0.50.0, matplotlib, ipywidgets, anywidget et la pile IPython (33 paquets). |

Règle des 7 jours : vectorbt 1.2.0 est publiée aujourd'hui, donc j'épingle 1.1.2. NautilusTrader 1.231.0 a 78 jours, numba 0.68.0 en a 19, pyarrow 26.0.0 en a 10. Au moment de l'ajout :

- `pip-licenses` confirme les licences transitives (portion, msgspec, sortedcontainers…) ;
- `pip-audit` est lancé ;
- la taille des roues est mesurée.

**Écartés** :

- NautilusTrader 2.0 rc : Python 3.13, pré-version ;
- l'extra `visualization` de NautilusTrader : plotly < 7 ;
- l'extra `full` de vectorbt : yfinance, R15 ;
- pyqlib et RD-Agent : D3 ;
- TradingAgents comme dépendance : inspiration seulement ;
- les autres moteurs de backtest : non évalués, hors spec.

`docs/licences.md` sera mis à jour.

## 14. Décisions demandées à l'utilisateur

| # | Décision | Options | Ma recommandation |
|---|---|---|---|
| D1 | Moteur événementiel | NautilusTrader 1.231.0 (Python 3.12 ; la v1 ne reçoit plus que les correctifs de sécurité) / passer le projet en Python 3.13 pour la 2.0 rc / moteur maison seul, NautilusTrader reporté (écart à la spec) | **1.231.0**, derrière un adaptateur mince. La stratégie reste une fonction pure : la migration vers la v2, quand elle sera stable et le projet en 3.13, ne touchera que l'adaptateur. Migration au backlog. |
| D2 | Criblage | vectorbt 1.1.2 isolé (groupe `research`, un seul module, CLI seulement) / criblage maison en numpy, vectorbt reporté | **vectorbt 1.1.2 isolé** : c'est le livrable du §17, et la Commons Clause convient à un usage personnel. Coût : 33 paquets et la compilation numba. |
| D3 | Qlib et RD-Agent | en phase 3 / au backlog | **Backlog** : hors des livrables du §17, dépendances lourdes. L'écart est écrit dans l'ADR-025. |
| D4 | Données de démonstration | jeu de recherche synthétique (10 ans, effet planté, marches aléatoires, crises fictives) / portefeuille de référence seul (3 ans) | **Jeu dédié**, en plus du portefeuille de référence : il permet de prouver que le protocole rejette le hasard et retient un effet réel. |
| D5 | Stratégie de démonstration | croisement de moyennes mobiles avec repli en cash / momentum transversal mensuel / parité de risque mensuelle | **Croisement de moyennes mobiles** : simple à vérifier à la main, et sa grille large teste bien le DSR et le PBO. |
| D6 | Modèle d'exécution | clôture t → clôture t+1 / clôture t → clôture t (fuite) | **Décision à la clôture de t, exécution à la clôture de t+1**, quantités entières, frais de `trading_costs`. |
| D7 | Découpage | à toi | 70 % pour le développement, 30 % pour l'échantillon final, embargo de 5 séances ; échantillon final lu une fois par version. |
| D8 | Walk-forward | ancré / glissant ; nombre de plis | **Ancré, 4 plis**, paramètres re-choisis à chaque pli. |
| D9 | Portes du protocole, fixées avant la première mesure | à toi | Les six portes suivantes. 1) DSR ≥ 0,95. 2) PBO < 0,5. 3) Sharpe net de l'échantillon final ≥ 50 % de celui du walk-forward. 4) Sharpe net de l'échantillon final supérieur à celui de la référence, sur au moins 252 séances. 5) Sharpe net > 0 à frais doublés. 6) Sur chaque crise couverte, drawdown ≤ celui de la référence. |
| D10 | Nombre d'essais | N brut (prudent) / N effectif par regroupement | **N brut**, journal append-only dans la base Finance ; le N effectif va au backlog. |
| D11 | Fenêtres de crise | dates réelles (D10 de la phase 2, `A_VERIFIER`) / fenêtres fictives pour la démonstration | **Les deux** : je relève les dates réelles avec leur source à l'implémentation, tu les valides, et la démonstration utilise des fenêtres fictives nommées comme telles. |
| D12 | Tolérances de recoupement | à toi | **Moteur maison / NautilusTrader** : mêmes opérations, valeur finale à 1e-6 en relatif. **vectorbt / moteur maison** : Sharpe à 1e-9 en relatif quand la sémantique des frais est identique, sinon écart documenté. |
| D13 | Outil du Copilot (R13) | sixième outil `strategy_lab` (plugin `finance_research`) / aucun outil, CLI seulement / fusion dans un plugin existant | **Sixième outil**, avec l'ADR-027 et une mesure du routage avant et après. |
| D14 | Registre et promotion des stratégies | statut `recherche` / `candidate` changé par toi et contrôlé par `config check` / pas de registre | **Registre**, avec une promotion faite à la main par toi, refusée sans verdict `reussi` à jour. |
| D15 | Déclenchement du Comité | classification du routage + option `--comite` / option seule / toute requête Finance | **Routage + option**, pour la Finance seulement en phase 3. |
| D16 | Analystes | 3 actifs (technique, actualités et macro, portefeuille), fondamental et sentiment écrits mais inactifs faute de source / les 4 de la spec, l'analyste sans données répondant « je ne sais pas » | **3 actifs** : un analyste sans données coûte un appel pour rien. Le sentiment tiré des actualités est une opinion (R12) et reste chez l'analyste actualités. Écart écrit dans l'ADR-028. |
| D17 | Débat et modèles | `max_debate_rounds` ; niveau de modèle par rôle | **2 tours** (défaut de la spec) ; gestionnaire en `deep` (spec), les autres rôles en `standard`. Le tout dans un nouveau `config/committee.yaml`. |
| D18 | Budget d'une séance | à toi | 400 000 jetons, 600 s, 40 appels d'outil. La section reste `A_DEFINIR` jusqu'à ta réponse : aucune séance réelle avant. |
| D19 | Journal du Comité | entrées `DECISION` existantes + séance complète dans `var/finance/committee/` / nouveau type d'événement `COMMITTEE` (change l'Annexe C.3) | **`DECISION`**, qui existe déjà : pas de changement de schéma. |
| D20 | Politique | inchangée (aucune action ; « proposition » reste refusée) / accorder `proposition` à `FINANCIERE` en N1 | **Inchangée** : sans intention d'ordre (phase 4), il n'y a rien à autoriser. B108 reste ouvert. |
| D21 | Verdict du contrôleur | contrôles déterministes, que le modèle peut seulement durcir / verdict du modèle | **Déterministe d'abord**. Avec `risk_limits.paper.yaml` à `A_DEFINIR`, le verdict reste `BLOQUER` (R7) tant que tu n'as pas fixé les limites. |
| D22 | Intégration du Comité | sous-graphe enregistré `kind: agent` (§6.1), avec un transport `in-process` ajouté au registre / serveur MCP / code dans l'orchestrateur | **Sous-graphe enregistré**, comme le prévoit le §6.1. |
| D23 | Dette du backlog incluse | à choisir | **Incluses** : B96 (sorties bornées) ; B97 (kill switch au milieu d'une séance) ; B98 (démarrage paresseux, sept plugins) ; B99 et B101 (ordres en clair et homoglyphes, red team du Comité) ; B103 (chemins des commandes `cerveau finance` et `cerveau strategy`) ; B107 (`cerveau promotion check finance N1`) ; B118 ; B119. **Reportées** : B111 et B112 (changeraient des valeurs figées par le golden set : ADR et ton accord) ; B113 (attend D13) ; B105, B106, B109, B110, B114–B117 ; B85–B87, B95, B100, B102, B104 ; B37–B43, B62, B64, B69. |
| D24 | Revues | `security-reviewer` seul / + `quant-reviewer` / + `risk-gate-auditor` | **`security-reviewer` + `quant-reviewer`** (backtest, protocole, DSR). `risk-gate-auditor` seulement si la politique ou l'autonomie change, ce qui n'est pas le cas avec D20. |
| D25 | Dépendances du §13 | accepter / modifier | Accepter. |
| D26 | Décisions de phase 2 encore ouvertes qui limitent la phase 3 | D19 budgets, D13 frais, D8 ISIN de l'indice, D10 crises, D1 source des cours | Les trancher quand tu peux. En attendant, tout est livré et mesuré sur données synthétiques et frais fictifs, et le rapport dira ce qui reste bloqué. |
| D27 | Nouveaux cas golden | environ 20 nouveaux cas, les 60 existants inchangés / pas de nouveau cas | **Oui** : je les rédige, tu les valides, puis ils sont gelés. |

## 15. Hors périmètre → `docs/backlog.md`

- Qlib, RD-Agent et la recherche ML (D3).
- NautilusTrader 2 et le passage à Python 3.13.
- Données intrajournalières, ticks, carnet d'ordres.
- Intention d'ordre (C.2), Porte de risque, paper, réconciliation et kill switch d'exécution : phase 4, avec B108.
- Analystes fondamental et sentiment, qui attendent une source. Comité des autres domaines : le moteur est générique, les fiches viendront avec les packs.
- Calibration de la confiance du Comité (les données sont collectées dès la phase 3).
- N effectif d'essais, par regroupement des essais corrélés.
- Backtest du rééquilibrage optimisé de la phase 2 (F4).
- Rapport de stratégie en HTML et graphiques (extra `visualization`).

## 16. Commits atomiques (en anglais, `make ci` vert à chaque étape)

1. `docs: add the validated phase 3 plan`
2. `docs(adr): add ADR-024 to ADR-028 (backtest engine, screening licence, anti-overfitting protocol, strategy registry and research tool, investment committee)`
3. `chore(deps): add NautilusTrader and the optional vectorbt research group`
4. `feat(config): add research protocol, committee and committee budget parameters`
5. `test(finance): add the synthetic research dataset`
6. `feat(finance): add the point-in-time backtest view and the in-house daily engine`
7. `test(finance): fail any backtest that reads future data`
8. `feat(finance): add the NautilusTrader adapter cross-checked against the in-house engine`
9. `feat(finance): add the append-only trial journal and vectorbt screening`
10. `feat(finance): add the anti-overfitting protocol (walk-forward, DSR, PBO, crises, benchmark)`
11. `feat(finance): add the strategy registry, the demo strategy and the standard strategy report`
12. `feat(cli): add cerveau strategy commands and keep finance paths under var/ (B103)`
13. `feat(plugins): add the finance_research MCP server`
14. `feat(registry): accept in-process agent manifests`
15. `feat(committee): add the committee subgraph, role schemas and code-checked debate rules`
16. `feat(finance): add the finance committee cards and toolboxes`
17. `feat(orchestrator): route finance decisions to the committee and journal every role`
18. `fix(orchestrator): bound tool outputs, record the halted state and start plugins lazily (B96, B97, B98)`
19. `fix(guardrails): flag plain-text orders and homoglyphs (B99, B101)`
20. `feat(cli): add cerveau promotion check (B107)`
21. `test(finance): widen reference cross-checks and cover unknown data quality (B118, B119)`
22. `test(evals): add strategy and committee golden cases, behaviour and red-team suites`
23. `docs: update licences, threat model and backlog`
24. `docs: add the phase 3 report`

## 17. Coût estimé (non mesuré)

- **Développement** : aucun appel payant, tout passe hors ligne.
- **Une séance réelle du Comité** : environ 10 appels de modèle (3 analystes, 4 tours de débat, un gestionnaire en `deep`, un contrôleur), soit **0,30 à 0,80 $** aux tarifs de `config/pricing.yaml` (estimation).
- **Campagne d'évals réelle** : environ 25 séances du Comité (nouveaux cas golden, comportements, red team) plus les suites existantes, soit **20 à 35 $** (estimation).
- **Données et bibliothèques** : 0 €.

Les vrais chiffres viendront du grand livre et figureront dans le rapport.

## 18. Exécution

- **Où** : dans cette session, ouverte dans `cerveau-plateforme`, où les hooks du projet sont chargés.
- **Ordre** :
  1. décisions ;
  2. lecture de la documentation (NautilusTrader 1.231, vectorbt 1.1, LangGraph 1.2.16) et des articles sur le DSR et le PBO ;
  3. ADR, dépendances, configuration ;
  4. jeu de recherche synthétique ;
  5. moteur, point-in-time et tests d'injection ;
  6. NautilusTrader, criblage, protocole ;
  7. registre, rapport, CLI, plugin ;
  8. Comité ;
  9. dette du backlog ;
  10. évals ;
  11. revues (`security-reviewer`, et `quant-reviewer` selon D24) ;
  12. rapport du §18.
- **Fin de phase** : je m'arrête et j'attends `GO PHASE 4`.
