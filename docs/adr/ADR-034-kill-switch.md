# ADR-034 — Kill switch : déclencheurs, effets mesurés sous 5 s, réarmement par Lucas seul

- Statut : accepté (D10 à D13 et D15 du plan de phase 4, validées par Lucas le 20/10/2026 ; cible
  de 5 s écrite à sa demande le 20/10/2026)
- Date : 2026-10-20
- Phase : 4

## Contexte
Le §8.5 et R4 imposent un arrêt total, prioritaire sur tout, sous une cible mesurée. Le kill switch
est aujourd'hui un fichier `governance/kill_switch/KILL` lu à six endroits. Le journal accepte déjà
le type `KILL`.

Faits relevés le 20/10/2026 : les hooks protègent `governance/approvals` et `var/audit`, pas
`governance/kill_switch`. Claude Code pourrait donc supprimer `KILL`, c'est-à-dire réarmer.
`kill_switch.target_seconds` et `data_loss_timeout_seconds` sont `A_DEFINIR`.

## Options
1. Fichier seul, réarmé par sa suppression manuelle.
2. **Fichier, commande et déclencheurs automatiques**, avec un réarmement interactif journalisé et
   des hooks durcis.

## Décision
Option 2.

- **Déclencheurs** :
  - le fichier `KILL` ou `cerveau kill` ;
  - un dépassement de perte du jour, de perte glissante ou de drawdown à la valorisation ;
  - des données perdues : cours de la séance attendue absent au lancement, au-delà de
    `max_staleness_sessions` (1) ;
  - un incident d'exécution : transition illégale, exécution d'un ordre inconnu, quantité exécutée
    excessive, cash négatif, écart de réconciliation issu d'un incident.
- **Effets** : annulation des ordres ouverts, blocage des nouvelles intentions, N0 forcé, entrée
  `KILL` au journal, rapport d'incident en français dans `var/incidents/`, alerte locale (journal et
  console ; ntfy au backlog, D13). Une annulation non confirmée est marquée comme telle et lève une
  alerte, dans un nombre d'essais borné par la cible.
- **Cible (D11)** : `kill_switch.target_seconds` = 5 s, fixée par Lucas le 20/10/2026. La durée va
  du déclenchement à l'état écrit, tous ordres annulés. `data_loss_timeout_seconds` reste
  `A_DEFINIR` jusqu'à une connexion continue.
- **Réarmement (D12)** : `cerveau rearm` refuse sans terminal interactif et sans phrase de
  confirmation, puis journalise `KILL` (« réarmement », acteur `lucas`). Une suppression manuelle
  du fichier est détectée et journalisée au lancement suivant.
- **Hooks** : ils refusent à Claude Code `cerveau rearm`, la suppression, le déplacement et la
  modification de `KILL`. La création reste permise, car elle arrête.

## Conséquences
- Seul Lucas sort d'un arrêt. Les hooks sont un confort ; la protection effective reste l'ACL
  Windows (ADR-003).
- **Tests** : durée sous la cible avec 1 000 ordres ouverts et un adaptateur lent ; réarmement
  refusé hors terminal interactif ; suppression manuelle détectée ; hooks.
