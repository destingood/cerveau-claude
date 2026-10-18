# ADR-020 — Conventions de la mesure de performance et de l'attribution

- Statut : **proposé** (plan de phase 2, F9 ; à valider par Lucas au compte rendu de phase)
- Date : 2026-10-18
- Phase : 2

## Contexte
F9 mesure la performance du portefeuille sur une période et l'attribue aux lignes et aux secteurs.
quantstats est écarté (D14), les mesures sont donc écrites dans le dépôt. Plusieurs choix y sont
implicites : quels jours valoriser, quand compter un apport, comment capitaliser l'€STR, comment
répartir le gain d'un jour entre les lignes. Il faut les figer avant le golden set, comme ADR-014
l'a fait pour le risque et ADR-019 pour l'optimisation.

## Décision
- **Jours de valorisation** : le début de la période (base), puis chaque jour TARGET jusqu'à la
  fin. Une fin hors TARGET remplace le dernier jour TARGET : un week-end n'ajoute pas de rendement
  nul. Début par défaut : la première opération ; fin par défaut : la date de lecture (Paris).
- **Valeur d'un jour** : le livre rejoué jusqu'à ce jour (opérations datées de ce jour comprises)
  et valorisé exactement comme `portfolio_snapshot` (dernier cours et dernier taux BCE publiés à
  `as_of`, aucun après ce jour, R10). Une valeur inconnue un seul jour refuse toute la période :
  pas de performance partielle (R12).
- **Flux externes** : dépôts et retraits seulement, comptés en fin de journée `[Hypothèse]`.
  Dividendes (nets de retenue), frais et conversions restent dans le rendement.
- **TWR** : rₜ = (Vₜ − Vₜ₋₁ − Fₜ) / Vₜ₋₁, chaîné en logarithmes. Annualisé en ACT/365, seulement si
  la période couvre au moins 365 jours ; sinon l'annualisation est dite indisponible.
- **MWR** : taux qui annule la valeur actuelle des flux (base, apports, valeur finale), temps en
  jours calendaires rapportés à la période, résolu par Brent sur le logarithme du facteur
  (bornes ±30, `xtol` 1e-14). Pas de changement de signe : MWR indisponible.
- **Volatilité, Sharpe, Sortino** : écart type de l'échantillon (ddof = 1) des rendements
  quotidiens, × √`annualisation_sessions` (252) `[Hypothèse]` : les jours de valorisation sont des
  jours TARGET, pas les séances de chaque place.
  - Rendement sans risque d'un intervalle : €STR capitalisé comme la BCE, chaque jour calendaire
    au fixing du dernier jour TARGET, intérêt simple ACT/360 sur les jours couverts par un fixing.
  - Un fixing pas encore publié à `as_of` (l'€STR d'un jour paraît le jour TARGET suivant) est
    remplacé par le dernier connu ; les jours concernés sont signalés `[Hypothèse]`.
  - Sharpe = moyenne / écart type des rendements excédentaires ; Sortino = moyenne / écart à la
    baisse, √(Σ min(e, 0)² / (n − 1)), soit la semi-déviation de skfolio de cible zéro.
- **Perte maximale** : sur l'indice TWR, la base comptant comme un sommet (convention de
  `skfolio.measures.get_drawdowns`), avec sommet, creux et retour au sommet. Calmar = TWR annualisé
  / perte maximale, seulement sur au moins un an.
- **Gain d'une ligne un jour** : variation de sa valeur moins ce qui y est entré, plus ses
  dividendes. Chaque opération est mesurée en euros au taux BCE de sa date de transaction : un
  achat sort des liquidités ce qu'il apporte au titre, une conversion déplace la même valeur d'une
  devise à l'autre. Les gains des lignes somment exactement au gain du jour (Vₜ − Vₜ₋₁ − Fₜ). Les
  liquidités sont regroupées par devise (`liquidites-USD`), les frais de compte forment la ligne
  `frais`. L'effet de change d'un titre étranger reste dans la ligne du titre.
- **Contribution** : Σₜ Iₜ₋₁ × gainᵢ,ₜ / Vₜ₋₁, où I est l'indice TWR de la veille (1 à la base).
  Les contributions somment au TWR lui-même ; le résidu affiché ne mesure que l'arrondi. Ce
  chaînage remplace la somme arithmétique simple du plan, dont le résidu (−1,47 point sur le
  portefeuille de référence) n'aurait rien expliqué. Secteurs : ceux du référentiel ; une ligne
  sans fiche va en « non classé » avec un avertissement.
- **Indisponibles** : comparaison à l'indice (ISIN `A_VERIFIER`, D8), attribution factorielle
  (D9), attribution de Brinson (reportée, faute d'indice validé).

## Conséquences
- Contrôles indépendants dans les tests :
  - valeur de chaque jour égale à `value(build_book(day))` ;
  - TWR contre la méthode des parts (valeur liquidative unitaire) ;
  - MWR : valeur actuelle nulle au taux trouvé, forme close pour un flux unique ;
  - volatilité, semi-déviation et perte maximale contre `skfolio.measures` ;
  - somme des gains des lignes égale au gain du jour, contributions égales au TWR ;
  - propriétés Hypothesis sur des séries synthétiques.
- La fonction `finance.performance` dépend de `market_risk.annualisation_sessions` et
  `market_risk.risk_free` : un marqueur sur l'un ou l'autre la bloque (R7).
- Réversible : oui ; tout changement de convention change les chiffres attendus du golden set.
