# Plan — Phase 7 : amélioration continue et préparation de N4

- Statut : **validé par Lucas le 29/10/2026** (« Vsy »), avec les recommandations D2, D3, D4 et D6
  du §11 ; D1 et D5 restent `A_DEFINIR` (R7)
- Date : 2026-10-29
- Base : §17 (phase 7), §8.3, §11 (boucle d'apprentissage), §12, ADR-011 (accepté), backlog B74 à B78

## 0. En une phrase

CERVEAU enregistre ses prévisions et les note à l'échéance (score de Brier). Il apprend de ses
erreurs derrière une porte champion / challenger, sans toucher au noyau verrouillé, et produit
seul ses rapports hebdomadaires et mensuels. Les critères de passage en N4 sont mesurés, mais
N4 reste activable par Lucas seul.

## 1. Existant (lu dans le code le 29/10/2026)

| Brique | Où | État |
|---|---|---|
| Entrées `ERROR` et `FEEDBACK`, `cerveau feedback` | `core/learning/` (ADR-011) | écrites depuis la phase 1, lues par personne |
| Juge, rapport d'évals `--report` | `core/evals/judge.py`, `core/evals/report.py` | hors ligne ; le juge tourne en mode réel seulement |
| Rapport de promotion | `interfaces/cli/promotion.py` (ADR-040) | N2 → N3 ; N3 → N4 absent (B220) |
| Seuils N3 → N4 | `config/autonomy.yaml` | `approvals_min` et `agreement_rate_min` à `A_DEFINIR`, sans bornes dans le schéma (B248) |
| Acteur `scheduler` du journal | `core/audit/chain.py` | existe ; aucune tâche planifiée |
| Alertes ntfy et Discord | `core/notify/` | coupées (non définies) |
| Stockage local | SQLite sous `var/` (approbations, carnet, boucle) | modèle à réutiliser |
| Prévisions, score de Brier, champion / challenger | — | **absents** |

## 2. Périmètre (§17)

| Livrable | Livré en phase 7 | Reporté |
|---|---|---|
| Boucle d'apprentissage : calibration, Brier | lot 7.1 | — |
| Champion / challenger | lot 7.2 : couche apprise, porte, retour arrière, noyau verrouillé | promotion réelle tant que les budgets sont à `A_DEFINIR` |
| Rapport hebdomadaire | lot 7.3 | — |
| Red teaming hebdomadaire | lot 7.3 : suites hors ligne, chaque semaine | red team réelle (payante), à lancer sur accord |
| Revue sécurité mensuelle | lot 7.3 : contrôles automatiques et rapport | revue par agent sur demande |
| Critères N4 instrumentés | lot 7.4 | activation de N4 : Lucas seul (R3) |

**Critère de sortie (§17)** : les rapports sont générés automatiquement 4 semaines de suite, sans
intervention. Le code peut être prêt en quelques jours, mais **le compte rendu de phase 7 arrive
au plus tôt 4 semaines après la mise en route de la planification**.

## 3. Lot 7.1 — Prévisions et calibration (ADR-064)

- **Registre** `core/learning/forecasts.py` (SQLite, `var/learning/forecasts.db`). Chaque entrée
  porte :
  - un identifiant et le `request_id` ;
  - le domaine ;
  - l'énoncé, pseudonymisé ;
  - le type : probabilité ou estimation ;
  - la valeur annoncée ;
  - la date d'échéance ;
  - la source de résolution.
- **Origine** : le format 7.3 a déjà une partie « estimations ».
  - Une probabilité ou une estimation datée y est extraite par le code et enregistrée (R12, §11).
  - Le LLM ne calcule aucun score (R1).
- **Résolution**, avec R10 (aucune donnée postérieure n'entre dans la prévision, seulement dans sa
  note) :
  - `cerveau forecast resolve <id> {oui|non|valeur}`, acteur `lucas` ;
  - en finance, résolution automatique depuis le store point-in-time.
- **Scores déterministes**, sous tests de propriétés (Hypothesis) :
  - Brier, avec sa décomposition de Murphy (fiabilité, résolution, incertitude) ;
  - courbe de calibration par tranches ;
  - erreur absolue et relative pour les estimations.
- **Dérive de calibration** : déclencheur de rétrogradation (§8.3). Seuil et taille minimale
  d'échantillon : `A_DEFINIR`. En dessous du minimum, le rapport dit « pas assez de données ».

## 4. Lot 7.2 — Boucle d'apprentissage et champion / challenger (ADR-065, ADR-011, B74 à B78)

- **Couche apprise** : dossier dédié, versionné, hors de `config/` ; emplacement à décider (D3).
  - Il contient les sections de prompt des packs (rôle, exemples, leçons) et des paramètres de
    routage et de recherche.
  - Tout le reste est refusé.
- **Noyau verrouillé** : tout ce que liste ADR-011.
  - Le moteur refuse d'écrire hors de la couche apprise par une liste fermée de chemins, testée,
    et non par une liste d'exclusion.
  - La protection effective reste l'ACL (ADR-003), que Lucas pose (B77).
- **Apprentissage** : lecture des `ERROR` et `FEEDBACK` et des notes (marquées non fiables, R5).
  - Regroupement par motif.
  - Proposition d'un challenger : leçon ou exemple ajouté à une section apprise.
  - Rédiger un challenger demande un LLM, donc les budgets. Hors ligne, des challengers scriptés
    testent toute la mécanique.
- **Porte** : le challenger passe golden, comportements et red team complets, comparé au
  champion.
  - **Jeu tenu à l'écart** : une partie du golden que l'apprentissage ne voit jamais, contre la loi
    de Goodhart (ADR-011).
  - Rejet si le challenger est moins bon.
  - R9 tient : aucun seuil ni golden modifié.
  - Marge, métriques et taille d'échantillon : `A_DEFINIR`.
- **Retour arrière** : une baisse en production pendant la fenêtre `A_DEFINIR` fait revenir au
  champion. Chaque promotion et chaque retour arrière sont journalisés (R11).
- **Empoisonnement** (B78) :
  - retours plafonnés par utilisateur ;
  - un retour seul ne change rien ;
  - une consigne dans une note est écartée (R5) ;
  - red team dédiée.
- **Mode de promotion** (D4) : ADR-011 prévoit une promotion automatique. Tant que les évals
  réelles sont impossibles (budgets à `A_DEFINIR`), la porte tourne et produit son verdict, mais
  aucun challenger n'est mis en ligne.

## 5. Lot 7.3 — Rapports planifiés (ADR-066)

- **Hebdomadaire** : `cerveau report weekly` écrit `evals/reports/hebdo-AAAA-Sww.md`, sans LLM,
  avec :
  - les évals hors ligne et le score de chaque pack (§9) ;
  - la red team hors ligne complète ;
  - la calibration ;
  - les coûts (réels et simulés) ;
  - les refus du journal ;
  - les incidents ;
  - les SLO des plugins ;
  - l'état de la porte d'apprentissage.
- **Mensuel sécurité** : `cerveau report security` écrit
  `docs/rapports/securite-AAAA-MM.md`, avec :
  - gitleaks ;
  - pip-audit et npm audit ;
  - `audit verify` ;
  - `config check` ;
  - les tests des hooks ;
  - l'écart au modèle de menaces ;
  - les dépendances dépassées.
- **Planification** (D2) : le script `infra/scripts/install-schedule.ps1` (Planificateur de tâches
  Windows, rattrapage si le PC était éteint).
  - **Lucas le lance lui-même** : c'est une configuration persistante du système.
  - Chaque exécution laisse une entrée `scheduler` dans le journal.
  - Un échec produit un rapport « échec » plutôt qu'un silence, et une alerte si ntfy ou Discord
    sont activés.
- **Preuve du critère** : `cerveau report streak` compte les semaines consécutives sans
  intervention, d'après le journal.

## 6. Lot 7.4 — Critères N4 instrumentés et dette de sûreté (ADR-067)

- Le rapport de promotion N3 → N4 (B220) donne :
  - le nombre d'approbations N3 ;
  - le taux d'accord entre Lucas et CERVEAU ;
  - les conditions de risque ;
  - l'état de chaque déclencheur de rétrogradation.
- Les bornes de `PromotionN3N4` (B248) bloquent un minimum nul ou un taux hors de [0, 1].
- Les déclencheurs de rétrogradation sont branchés : dérive de calibration, échec de l'éval
  planifiée, plugin hors SLO.
  - Ils rétrogradent automatiquement : un pas vers plus de prudence, jamais l'inverse.
- Dette de sûreté incluse :
  - B292 (`max_autonomy_level` d'un plugin, appliqué nulle part) ;
  - B200 et B230 (gardes live) ;
  - la remarque de la revue `risk-gate-auditor` de P6 : la garde de non-régression de la politique
    doit couvrir `code` et `business` ;
  - B262 (test instable) ;
  - B316 (porte de couverture).
- Rien n'active N4 : la promotion reste une signature manuelle et une modification manuelle de
  `live.yaml` (R3).

## 7. Évaluations et tests

- Comportements :
  - une probabilité annoncée est enregistrée (R12) ;
  - aucun score n'est écrit par le LLM (R1) ;
  - le rapport hebdomadaire ne contient aucun chiffre sans outil.
- Red team `injection_learning` (≥ 10 cas) :
  - une consigne dans un retour ;
  - un retour en masse ;
  - un challenger qui vise le noyau ;
  - un challenger qui touche un golden ou un seuil ;
  - une note qui demande une promotion.
- Tests sans réseau :
  - propriétés du Brier (borné dans [0, 1], nul pour une prévision parfaite) ;
  - moteur refusé sur chaque chemin du noyau ;
  - retour arrière ;
  - rapports à horloge figée.
- Aucune suite existante n'est modifiée (R9).

## 8. Nouvelles dépendances

Aucune prévue : scores en Python standard, planification par le système.

## 9. Hors périmètre → `docs/backlog.md`

- Mode public et contributions de tiers (phase 8).
- Postgres et pgvector pour la mémoire.
- Campagnes réelles des packs (B315, B332, B343…), chacune sur accord.
- Le reste de la dette marquée « 7 » qui ne touche pas la sûreté : il reste ouvert.

## 10. Coût estimé (non mesuré)

- Hors ligne : 0 €.
- Rédiger des challengers et lancer la red team réelle chaque semaine coûte des appels LLM : non
  estimé ici, plafonné par les budgets, qui sont à `A_DEFINIR`.

## 11. Décisions demandées à Lucas

**[QUESTIONS DE CLARIFICATION]**

| # | Décision | Options | Ma recommandation |
|---|---|---|---|
| D1 | Budgets quotidien et mensuel en € | montants | à fixer : ils bloquent toute partie réelle (R7) |
| D2 | Planification | Planificateur Windows / GitHub Actions planifié / conteneur cron | Planificateur Windows : le journal et `var/` sont locaux ; GitHub n'a ni journal ni données |
| D3 | Emplacement de la couche apprise | `learned/` versionné dans git / `var/learned/` hors git | `learned/` versionné : chaque leçon est traçable et réversible par un `git revert` |
| D4 | Mise en ligne d'un challenger | automatique (ADR-011) dès que les évals réelles tournent / proposition seulement en phase 7 | automatique comme décidé dans ADR-011, mais seulement avec les évals réelles ; hors ligne, verdict sans mise en ligne |
| D5 | Seuils de la porte et de la calibration | marge de promotion, taille d'échantillon, fenêtre de retour arrière, seuil de dérive du Brier, `regression_block_delta` | à fixer par toi ; sans eux, la porte et la dérive restent bloquées (R7) |
| D6 | Taille du jeu tenu à l'écart | 20 % / 30 % du golden de chaque pack | 20 % |

## 12. Commits atomiques (en anglais, `make ci` vert à chaque étape)

1. `docs: add the phase 7 plan` (après validation)
2. `feat(learning): forecast registry and Brier calibration` et ADR-064
3. `feat(learning): learned layer, locked core and champion/challenger gate` et ADR-065
4. `feat(learning): rollback and poisoning defences`
5. `feat(reports): weekly and monthly security reports, schedule script` et ADR-066
6. `feat(promotion): N3 to N4 report, bounds and demotion triggers` et ADR-067
7. `fix: safety debt B292, B200, B230, policy non-regression guard`
8. `test(evals): learning behaviours and injection_learning red team`
9. `docs: threat model and backlog`
10. Compte rendu de mise en route ; compte rendu §18 après 4 semaines de rapports.

Revues :
- `risk-gate-auditor` sur le lot 7.4 ;
- `security-reviewer` sur les lots 7.2 et 7.3 ;
- `quant-reviewer` sur le Brier ;
- `eval-engineer` sur la red team.
