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
