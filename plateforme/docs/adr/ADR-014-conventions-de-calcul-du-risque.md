# ADR-014 — Conventions de calcul du risque et de la performance

- Statut : **accepté par Lucas le 18/10/2026** (plan de phase 2, D7, D8, D11)
- Date : 2026-10-18
- Phase : 2

## Contexte
Un même mot (VaR, volatilité, Sharpe) recouvre plusieurs définitions. Le critère de phase exige
que les mesures du portefeuille de référence concordent avec un calcul indépendant à une
tolérance donnée. Il faut donc figer chaque définition avant de mesurer.

## Décision
- **Rendements** : simples, quotidiens, sur les séances communes à toutes les lignes, en EUR, au
  taux de référence BCE du jour (le dernier publié au plus tard à cette date).
- **VaR et CVaR** : perte positive, en EUR et en % de la valeur du portefeuille ; niveaux 95 % et
  99 % ; horizons 1 et 10 séances ; fenêtre de 500 séances.
  - **historique** : quantile empirique des pertes, avec l'interpolation linéaire de
    `numpy.quantile` (méthode `linear`) ; la CVaR est la moyenne des pertes au-delà de ce
    quantile ;
  - **paramétrique** : loi normale, moyenne et covariance de l'échantillon ;
  - **Monte-Carlo** : 10 000 tirages normaux multivariés, graine fixe 2026 ;
  - **horizon h** : mise à l'échelle √h, étiquetée `[Approximation]`.
- **Backtest de Kupiec** : test du rapport de vraisemblance sur la couverture, 250 séances, seuil
  de 5 %.
- **Volatilité** : écart-type de l'échantillon (ddof = 1), annualisé par √252 ; GARCH(1,1) estimé
  par arch, sur des rendements en %.
- **Contributions** : décomposition d'Euler, wᵢ(Σw)ᵢ/σ(w) pour la volatilité ; la somme des
  contributions est égale au risque total.
- **Variation de VaR entre deux dates** : effet positions (nouveaux poids, ancienne covariance),
  effet marché (anciens poids, nouvelle covariance), résidu.
- **Performance** : TWR par chaînage des rendements quotidiens hors flux ; MWR par XIRR ; Sharpe et
  Sortino annualisés, taux sans risque €STR ; indice de référence : un ETF MSCI World en EUR,
  dividendes réinvestis (ticker `A_VERIFIER`).
- **Contrôle indépendant** : chaque mesure du portefeuille de référence est recalculée par une
  autre implémentation (skfolio quand la définition est identique, sinon une forme fermée). La
  tolérance est un écart relatif de 1e-9 pour une même définition, et de 2 % pour Monte-Carlo
  contre la forme fermée (100 000 tirages). GARCH est contrôlé sur sa capacité à retrouver des
  paramètres connus sur données simulées.

## Conséquences
- Chaque sortie d'outil nomme sa méthode, sa fenêtre et ses paramètres. Le LLM cite ces chiffres
  sans les recalculer (R1).
- Si une définition de skfolio diffère de la nôtre, le test aligne la comparaison sur la même
  définition, et l'écart est écrit ici ; on ne modifie jamais la tolérance (R9).
- Les paramètres vivent dans `config/risk.yaml` (`market_risk`) ; les changer relance les évals.
- Réversible : oui, mais tout changement de définition change les chiffres attendus du golden set.

## Précisions de mise en œuvre (plugin `finance_risk`, 18/10/2026)
- **Lignes** : une ligne par instrument (tous comptes réunis) et une par devise de liquidités
  (`liquidites-<DEV>`, de prix 1/taux en EUR). Le taux BCE d'une séance est le dernier publié au
  plus tard ce jour-là. Les poids du portefeuille à `as_of` s'appliquent à toute la fenêtre
  `[Hypothèse]`.
- **Écart de définition avec skfolio** : `value_at_risk` et `cvar` de skfolio 1.8.1 prennent un
  rang empirique, sans interpolation linéaire. La VaR historique est donc contrôlée contre un
  quantile linéaire (type 7 de Hyndman et Fan) écrit dans le test. skfolio contrôle la volatilité
  (ddof = 1), le drawdown maximal (richesse composée partant de 1) et le nombre de lignes
  effectives (1/Σw²). La tolérance n'a pas bougé.
- **Monte-Carlo** : les tirages passent par la racine carrée symétrique de la covariance, qui est
  unique. Le résultat ne dépend donc ni du signe ni de l'ordre des vecteurs propres renvoyés par
  LAPACK, et une ligne de variance nulle (l'euro) est admise. Les pertes simulées se lisent avec
  les estimateurs historiques.
  - À 10 000 tirages, l'erreur d'échantillonnage atteint quelques %.
  - À 100 000 tirages, l'écart à la forme fermée reste sous 2 % (test du portefeuille de
    référence et de quatre graines).
- **Concentration** : Herfindahl sur la valeur investie, liquidités exclues.
- **Variance nulle** : une ligne constante se détecte exactement (max = min). L'écart-type arrondi
  d'une constante non nulle n'est pas toujours nul.
- **Stress de taux (+100 pb)** : deux parties, dont la somme est le stress publié.
  - Les obligations de duration connue passent par la duration modifiée `[Approximation]`.
  - Les autres lignes en titres passent par une sensibilité estimée par MCO aux variations
    quotidiennes de l'€STR `[Estimation]`, publiée avec son écart-type et sa p-value. L'€STR est un
    taux au jour le jour : la sensibilité est bruitée (p = 0,459 sur le portefeuille de référence).
  - Une obligation sans duration connue n'est pas estimée.
- **Stress historiques** : trois statuts.
  - `bloque` : une date ou la source vaut `A_VERIFIER` (D10), ou le début n'est pas avant la fin.
  - `non_couvert` : l'historique ne couvre pas la fenêtre.
  - `calcule` : les lignes actuelles subissent les variations de prix entre les dernières clôtures
    au plus tard au début et à la fin, et la source est citée.
- **Mesures indisponibles** : elles sont dites indisponibles avec leur raison, jamais estimées.
  - Bêta et choc actions par le bêta : l'indice de référence est bloqué (ISIN `A_VERIFIER`, D8).
  - Facteurs : aucune source validée (D9).
- **Configuration** : les paramètres typés de `market_risk` refusent les marqueurs. Une valeur
  inconnue y rend la configuration invalide : l'outil refuse, sans recopier la valeur, et la
  fonction reste bloquée (R7). La porte de fonction `finance.market_risk` ne voit donc jamais de
  marqueur dans ces champs.
- **Étiquette de parité** : `[Approximation]`. Le moteur de risque d'Aladdin est approché sans
  modèle de facteurs, sans indice de référence validé, avec un choc de taux en partie estimé et
  la règle de √h.
