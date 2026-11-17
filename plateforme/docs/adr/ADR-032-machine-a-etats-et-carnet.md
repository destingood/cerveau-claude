# ADR-032 — Machine à états des ordres et carnet append-only

- Statut : accepté (plan de phase 4, §6, validé par l'utilisateur le 20/10/2026)
- Date : 2026-10-20
- Phase : 4

## Contexte
Le §10.8 impose une machine à états journalisée pour chaque ordre. R11 impose un journal
append-only. Le §9 classe toute incohérence d'exécution comme incident. Le journal accepte déjà le
type `ORDER_STATE` (Annexe C.3).

## Options
1. État de l'ordre stocké dans le seul journal d'audit.
2. **Carnet SQLite append-only** pour les montants, avec une entrée `ORDER_STATE` au journal par
   transition.

## Décision
Option 2, comme pour le portefeuille réel (les montants restent hors du journal).

- **Transitions permises** :

  | De | Vers |
  |---|---|
  | INTENTION | VALIDEE, REJETEE |
  | VALIDEE | ENVOYEE, ANNULEE |
  | ENVOYEE | PARTIELLE, EXECUTEE, ANNULEE, REJETEE |
  | PARTIELLE | EXECUTEE, ANNULEE |

  EXECUTEE, ANNULEE et REJETEE sont terminaux et immuables. Toute autre transition lève un incident
  d'exécution (ADR-034).
- **Carnet** `var/paper/orders.db` : tables des intentions, des transitions et des exécutions, en
  insertion seule. La base impose l'unicité de `intent_id`, qui sert d'identifiant client de
  l'ordre : un renvoi ne crée jamais un second ordre.
- **Journal** : chaque transition écrit `ORDER_STATE` avec `intent_id`, état, raison et SHA-256 de
  l'intention. Seule exception, l'annulation groupée du kill switch (ADR-034) : une transaction et
  une entrée `ORDER_STATE` qui liste chaque ordre (`intent_id` et SHA-256), tout ou rien. Avec un
  journal à environ 5 ms l'entrée, 1 000 entrées séparées dépasseraient la cible de 5 s.
- **Contrôles d'exécution** : la quantité exécutée cumulée ne dépasse jamais la quantité de l'ordre ;
  une exécution d'un ordre inconnu est un incident.
- **Glissement réel** : écart entre le prix d'exécution et le prix de décision, en points de base,
  par ordre et cumulé.

## Conséquences
- L'état d'un ordre se reconstruit à partir du carnet ; le journal permet de vérifier qu'il n'a
  pas été réécrit.
- **Tests** : `RuleBasedStateMachine` d'Hypothesis (aucune transition illégale, quantité exécutée
  ≤ quantité de l'ordre, état terminal stable) ; doublon d'`intent_id` refusé par la base.
