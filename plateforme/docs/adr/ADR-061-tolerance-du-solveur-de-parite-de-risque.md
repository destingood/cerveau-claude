# ADR-061 — Tolérance du solveur de la parité de risque et correction d'une référence du golden

- Statut : **proposé** (R9 : une valeur attendue du golden Finance change ; à valider par Lucas)
- Date : 2026-11-17
- Phase : plan de remise au vert, étape 0 (`docs/plans/plan-parite-aladdin.md`, C18)

## Contexte
Sous Linux (Python 3.12 par uv, skfolio 1.8.1, cvxpy 1.9.3, Clarabel), le golden Finance échouait
sur 4 cas de parité de risque, tous verts sous Windows au rapport P5 :

| Cas | Chiffre | Linux, réglages par défaut | Attendu |
|---|---|---|---|
| `Q3-contributeur-et-parite-de-risque`, `q3-ligne-dominante-dans-la-var`, `q3-globex-essentiel-du-risque` | `lignes/FICT-GLOBEX/poids_cible` | 4,09 % | 4,10 % |
| `optim-plafond-souverain` | `rotation` | 72,32 % | 72,33 % |

`RiskBudgeting` était résolu avec les tolérances par défaut de Clarabel. Le poids de Globex en
sortait à 0,0409470 sous Linux ; une même résolution peut tomber de l'autre côté de l'arrondi
d'affichage selon la plateforme. Un chiffre décisionnel qui dépend du système viole R1.

## Mesures (portefeuille de référence fictif, 17/11/2026)

Poids de Globex sans plafond, selon la tolérance (`tol_gap_abs`, `tol_gap_rel`, `tol_feas`) :

| Tolérance | Poids | Affiché |
|---|---|---|
| défaut | 0,0409470 | 4,09 % |
| 1e-10 | 0,0409504 | 4,10 % |
| 1e-12 | 0,0409514 | 4,10 % |
| 1e-13, 1e-14 | 0,0409515 | 4,10 %, Clarabel signale une solution imprécise |

Contrôle indépendant de la parité de risque (contributions au risque `w_i (Σw)_i`, normalisées,
qui doivent être égales) : écart relatif entre la plus grande et la plus petite de **4,4e-4** à
1e-8, de **6,6e-6** à 1e-12. La solution serrée est la bonne.

Rotation du cas plafonné (Souverain ≤ 20 %) : 0,7232686 à 1e-8, puis 0,7232398 (1e-10),
0,7232371 (1e-11), 0,7232372 (1e-12), 0,7232373 (1e-13). La valeur convergée s'affiche
**72,32 %**. La référence « 72,33 % » du golden venait d'une résolution imprécise.

VaR à 99 % après rééquilibrage, sans plafond (`risque/apres/var/99`, golden du plugin
`finance_optimize`, cas `fo-015`) : 1 088,61 € à 1e-8, 1 088,558 € (1e-10), 1 088,561 €
(1e-12 et 1e-13). La valeur convergée s'affiche **1 088,56 €** ; la référence « 1 088,57 € »
venait elle aussi d'une résolution imprécise. Constaté par la CI Linux du 17/11/2026.

## Options
- Tolérance 1e-12 pour `RiskBudgeting` seul (retenu) : la plus serrée sans avertissement ; les
  poids se stabilisent à environ 1e-7.
- Toutes les méthodes : aucune autre méthode n'échoue d'une plateforme à l'autre aujourd'hui ;
  changer `MeanRisk` déplacerait d'autres chiffres du golden sans mesure qui le justifie (R13).
- Garder les réglages par défaut et comparer avec une tolérance : un chiffre affiché resterait
  dépendant du système (R1).

## Décision
- `core/finance/optimize.py` : `RiskBudgeting` reçoit `solver="CLARABEL"` et les trois
  tolérances à `RISK_BUDGETING_TOLERANCE = 1e-12`.
- Golden Finance, cas `optim-plafond-souverain` : la rotation attendue passe de « 72,33 % » à
  « 72,32 % » (chiffre de référence et point clé). Aucun seuil ne change, aucun cas n'est retiré.
  Les trois cas Globex gardent « 4,10 % », que la solution serrée confirme.
- Golden du plugin `finance_optimize`, cas `fo-015` : la VaR à 99 % après rééquilibrage attendue
  passe de « 1 088,57 € » à « 1 088,56 € ».

## Conséquences
- Golden Finance 96/96 sous Linux. Sous Windows, à revérifier par la CI (job `windows-latest`).
- Une résolution de parité de risque coûte quelques itérations de plus (non mesuré, petit
  portefeuille).
- Si une version de skfolio ou de Clarabel change le résultat au-delà de 1e-7, le golden le
  signalera : relancer ces mesures avant de toucher une référence.
