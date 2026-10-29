# ADR-067 — Rapport de promotion N3 → N4, bornes et rétrogradation automatique

- Statut : proposé
- Date : 2026-10-29
- Phase : 7 (lot 7.4 du plan validé le 2026-10-29)

## Contexte
N4 (autonome dans des limites) est le dernier niveau (§8). Une signature N4 ne comptait pas faute de
rapport (B220) et `PromotionN3N4` n'avait aucune borne (B248). La section 8.3 prévoit aussi une
rétrogradation automatique d'un niveau sur `demotion_triggers` (`config/autonomy.yaml`), sans
qu'aucun code ne la branche. Règles concernées : R1 (chiffres tirés d'outils), R2, R7 (inconnu
bloquant), R9, R11. N4 n'est activé que par Lucas, à la main.

## Options
1. Rapport N3 → N4 seul, rétrogradation laissée à Lucas : simple, mais un échec d'évals planifié
   laisserait le niveau intact jusqu'à sa lecture du rapport.
2. Rapport N3 → N4 et rétrogradation automatique d'un pas, levée manuelle seulement (retenue).
3. Rétrogradation qui réécrit `config/autonomy.yaml` : interdit (le niveau écrit appartient à Lucas)
   et invisible dans le journal.

## Décision
Option 2.
- `cerveau promotion report finance --to N4` : niveau N3 atteint, approbations N3 décidées par Lucas
  (journal vérifié : ACCORDEE par `lucas`, REFUSEE par `lucas` ou `interface`), taux d'accord,
  incidents, drawdown live (non évaluable : aucun outil, B350), rétrogradations en vigueur (aucune
  attendue), évals réelles. Seuils `A_DEFINIR` → non évaluable (R7).
- `PromotionN3N4` bornée comme N2 → N3 : `approvals_min` entier strict ≥ 1, `agreement_rate_min`
  dans ]0, 1], ni NaN ni infini.
- Une rétrogradation est une ligne de `var/governance/demotions.jsonl` et une entrée `policy` /
  `DECISION` du journal. Elle abaisse le niveau effectif d'un seul pas, jamais en dessous de N0 ;
  `effective_autonomy` applique le plancher le plus bas par domaine. Aucun code ne la lève : Lucas
  retire la ligne à la main. Un fichier illisible ou trop gros tient tous les domaines à N0.
- Branché : `nightly_eval_failure`, par le rapport hebdomadaire (ADR-066) quand un seuil d'évals est
  manqué ; le seuil d'un groupe vise son domaine, un seuil sans domaine les vise tous.
- Non branchés : `calibration_drift` (seuils `A_DEFINIR`, B351), `critical_plugin_slo_breach` (SLO
  non fixés, B349), `execution_incident`, `limit_breach`, `drawdown_breach` (le kill switch arrête
  déjà tout ; rétrogradation à brancher, B352).

## Conséquences
- Une signature N4 devient vérifiable, mais reste non évaluable tant que les seuils et le drawdown
  live manquent : aucun N4 possible aujourd'hui, ce qui est voulu.
- Un domaine rétrogradé le reste jusqu'à l'intervention de Lucas, même si les évals repassent :
  prudent mais manuel.
- Réversible : supprimer le fichier de rétrogradations rend les niveaux écrits.
- Tâches : B350, B351, B352.
