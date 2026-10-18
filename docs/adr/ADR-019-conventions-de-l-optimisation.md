# ADR-019 — Conventions de l'optimisation et de la proposition de rééquilibrage

- Statut : **proposé** (plan de phase 2, F4 ; à valider par Lucas au compte rendu de phase)
- Date : 2026-10-18
- Phase : 2

## Contexte
F4 propose des poids cibles et, une fois les frais connus, des opérations en quantités entières.
skfolio 1.8.1 fournit les optimiseurs. Plusieurs choix y sont implicites : quelle covariance,
quelle définition de la rotation, quelles contraintes chaque méthode accepte, que faire des
liquidités. Il faut les figer avant le golden set, comme ADR-014 l'a fait pour le risque.

## Décision
- **Univers** : les titres détenus à `as_of`, tous comptes réunis. Les liquidités ne sont pas
  réallouées `[Hypothèse]` ; les poids sont ceux de la poche investie et somment à 1.
- **Positions** : longues seulement, sans levier ni dérivés (`risk_limits.paper` : `allow`).
- **Covariance de l'optimiseur** : Ledoit-Wolf (`skfolio.moments.LedoitWolf`, maximum de
  vraisemblance, ddof = 0) sur la fenêtre de `market_risk.var.window_sessions` séances, fixée par
  `optimization.covariance: ledoit_wolf`.
- **Méthodes** et contraintes acceptées. Une contrainte non prise en charge est refusée avec sa
  raison, jamais ignorée.

  | Méthode | skfolio | Poids max | Plafonds sectoriels | Rotation max |
  |---|---|---|---|---|
  | `variance_minimale` | `MeanRisk`, `MINIMIZE_RISK`, `VARIANCE` | oui | oui | oui |
  | `cvar_minimale` | `MeanRisk`, `MINIMIZE_RISK`, `CVAR` (β = 1er niveau de VaR) | oui | oui | oui |
  | `parite_de_risque` | `RiskBudgeting`, budgets égaux, mesure variance | oui | oui | non |
  | `hrp` | `HierarchicalRiskParity`, distance de Pearson, liaison de Ward | oui | non | non |
  | `moyenne_variance` | `MeanRisk`, `MAXIMIZE_UTILITY` | oui | oui | oui |

- **Rotation** : Σ|wᵢ − w⁰ᵢ| sur la poche investie, comme `Portfolio.turnover` de skfolio. Le
  paramètre `max_turnover` de skfolio borne la rotation **de chaque titre** et non le total. Le
  plafond total passe donc par `add_constraints` (`cvxpy.norm1(w − w⁰) ≤ plafond`), possible
  seulement pour `MeanRisk`.
- **Contrôle a posteriori** : la solution est revérifiée contre chaque contrainte (tolérance
  1e-6). Un poids sous 1e-9 est un résidu du solveur, mis à zéro avant renormalisation.
- **Précision du solveur** : Clarabel avec les tolérances par défaut de skfolio (écarts 1e-9).
  L'optimum atteint concorde avec un solveur indépendant à 1e-5 près en relatif, les poids à 1e-3
  près. La tolérance D11 (1e-9) vaut pour les mesures en forme close (ADR-014), pas pour un
  solveur itératif. Des tolérances plus fines (1e-10 à 1e-12) font finir Clarabel en « solution
  peut-être inexacte » sur une partie des problèmes : écartées, pour ne pas rendre des poids au
  statut incertain. Un poids affiché à 0,01 % près peut donc bouger d'un centième avec une autre
  version du solveur : les chiffres du golden set valent pour les versions de `uv.lock`.
- **Moyenne-variance** : maximise rendement moyen − λ × variance quotidienne. La moyenne
  historique n'est pas une prévision `[Hypothèse]`. λ (`optimization.risk_aversion`) est une
  décision de Lucas ; tant qu'il vaut `A_DEFINIR`, la fonction `finance.mean_variance` est bloquée
  (R7).
- **Risque avant et après** : volatilité annualisée et VaR paramétrique sur une séance, avec la
  covariance de l'échantillon (ddof = 1) et les liquidités, comme `risk_report` : le « avant » est
  le chiffre de F3. Les parts de risque par ligne (Euler, ADR-014) prennent la covariance
  Ledoit-Wolf de l'optimiseur, celle qui définit la parité de risque.
- **Opérations** : seulement si `trading_costs` est entièrement connu (D13) ; sinon la sortie
  donne les poids cibles et dit la liste d'opérations indisponible (R7).
  - Quantité : (valeur cible − valeur actuelle) / cours en EUR, arrondie à 1e-6 puis tronquée
    vers zéro. Les poids atteints s'écartent donc un peu des poids cibles.
  - Cours : dernier cours connu converti au taux BCE du jour `[Hypothèse]`.
  - Frais par ordre : max(montant × `commission_pct` / 100, `min_commission_eur`) +
    montant × `slippage_bps` / 10 000 + (devise étrangère) montant × `fx_conversion_bps` / 10 000.
    `commission_pct` est un pourcentage : 0.1 pour 0,1 %.
  - Variation des liquidités = ventes − achats − frais ; un solde négatif est signalé.
- **Statut** : « analyse » quand le domaine finance est en N0, « proposition non exécutée » à
  partir de N1. Rien n'est exécuté : en phase 4, la proposition deviendra des intentions d'ordre
  soumises à la Porte de risque (§10.5). Mention R16 dans chaque sortie.
- **Étiquette de parité** : `[Approximation]`, et non `[Parité]` comme le prévoyait le plan. Les
  frais ne sont pas dans l'objectif, ils sont encore inconnus, et il n'y a ni modèle de facteurs ni
  indice de référence validé.

## Conséquences
- Contrôles indépendants dans les tests :
  - Ledoit-Wolf contre la formule de Ledoit et Wolf (2004) écrite dans le test ;
  - variance minimale contre scipy (SLSQP) ;
  - CVaR minimale contre le programme linéaire de Rockafellar et Uryasev (scipy, HiGHS) ;
  - parité de risque : parts d'Euler égales à 1/n ;
  - solutions analytiques à deux titres ;
  - propriétés Hypothesis : somme à 1, bornes, plafonds, rotation.
- Plafond de rotation pour la parité de risque, plafonds sectoriels pour HRP, frais dans
  l'objectif, réallocation des liquidités : au backlog, à rouvrir si les évals le justifient (R13).
- Réversible : oui ; tout changement de convention change les chiffres attendus du golden set.
