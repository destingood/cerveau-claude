# ADR-030 — Politique : `proposition` en N1, `paper` en N2, règle N1→N2, rétrogradation automatique

- Statut : accepté (D9 et D10 du plan de phase 4, validées par l'utilisateur le 20/10/2026)
- Date : 2026-10-20
- Phase : 4

## Contexte
La matrice de `config/autonomy.yaml` donne déjà, pour la classe `FINANCIERE`, `proposition` en N1
et `paper` en N2. Le moteur de politique (`core/policy/engine.py`) n'accorde pourtant que `auto`.
Le §8.3 exige qu'une promotion vers N2 passe une red team du domaine, mais `autonomy.yaml` n'a pas
de règle `N1_to_N2`. `PolicyDecision.risk_gate` existe depuis la phase 1 et reste vide.

Faits relevés le 20/10/2026 : la finance est en N0. `PolicyDecision` expose une propriété `allowed`
qui ne distingue pas « exécuter », « proposer » et « paper ». Six déclencheurs de rétrogradation
sont listés, aucun n'est branché.

## Options
1. Statu quo : aucune intention ne passe jamais la politique, la phase 4 n'a rien à tester.
2. **Accorder les deux décisions** au seul domaine finance, avec un effet explicite et une règle
   N1→N2 plus stricte que N0→N1.

## Décision
Option 2.

- **Décisions accordées** : `proposition` et `paper`, pour `FINANCIERE` et le domaine `finance`
  seulement. `simule` et `brouillon` restent refusés : aucun composant ne les porte.
  - `proposition` : l'intention est rédigée et passe la Porte, mais n'est jamais envoyée.
  - `paper` : l'intention n'est envoyée qu'à l'adaptateur paper.
- **Effet explicite** : `allowed` est remplacé par `effect`, qui vaut `executer`, `proposer`,
  `paper` ou `refuser`. `risk_gate` est rempli au format C.4. Un test parcourt toute la matrice et
  vérifie qu'aucun chemin n'est devenu plus permissif qu'avant.
- **Niveau** : la finance reste en N0, donc tout est refusé en usage réel. Le paper tourne en tests,
  en évals et en développement, avec un niveau injecté.
- **Règle `N1_to_N2` (D9)** : les conditions de N0→N1, plus une red team Finance à 0 violation,
  plus la signature manuelle de l'utilisateur. `cerveau promotion check` la vérifie. C'est un durcissement.
- **Rétrogradation automatique (D10)** : `execution_incident`, `limit_breach` et `drawdown_breach`
  déclenchent le kill switch (ADR-034), qui force N0 jusqu'au réarmement par l'utilisateur. Dérive de
  calibration, échec d'éval nocturne et SLO de plugin vont au backlog.
- **Défense en profondeur** : si la configuration live indique `enabled: true`, tout est refusé avec
  une alerte, car aucun adaptateur live n'existe en phase 4 (R3).

## Conséquences
- Un appelant ne peut plus confondre une proposition avec une exécution : il doit lire `effect`.
- La promotion de la finance reste une décision signée de l'utilisateur, après une campagne réelle et la
  red team `injection_execution`.
- **Tests** : matrice complète niveau × classe × domaine, kill switch prioritaire, live activé
  refusé, règle N1→N2 manquante ou incomplète refusée par `cerveau config check`.
