# ADR-064 — Registre des prévisions et calibration (score de Brier)

- Statut : proposé
- Date : 2026-10-29
- Phase : 7 (lot 7.1 du plan validé le 2026-10-29)

## Contexte
La spécification (section 11) demande, pour chaque prévision ou décision :
- une échéance ;
- à l'échéance, le résultat réel, un score (Brier pour une probabilité, erreur pour une
  estimation) et une leçon ;
- un rapport hebdomadaire de calibration.

La section 8.3 fait d'une dérive de calibration un motif de rétrogradation automatique. Avant cet
ADR, CERVEAU n'enregistrait aucune prévision.

Contraintes :
- R1 : aucun modèle ne calcule un score ;
- R10 : un résultat n'est jamais connu avant l'échéance où il est jugé ;
- R11 : tout est journalisé ;
- R7 : seuils inconnus = `A_DEFINIR`.

Le score de Brier (Brier 1950) est la moyenne de (p − o)², bornée dans [0, 1]. La décomposition de
Murphy (1973) le sépare en fiabilité, résolution et incertitude. Avec des prévisions regroupées en
classes, elle est exacte pour les moyennes de classe, pas pour les valeurs individuelles. Ces
définitions sont classiques ; le code les teste par propriétés.

## Options
1. **Registre SQLite local à insertion seule, scores en Python standard** (retenue) : même modèle
   que le carnet d'ordres et les approbations (ADR-032, ADR-035), sans dépendance nouvelle.
2. **Table dans le journal d'audit** : le journal garde des comptes et des codes, pas des énoncés
   (R6) ; une prévision doit pouvoir être relue et listée.
3. **Bibliothèque de scores (scikit-learn `brier_score_loss`)** : dépendance lourde pour une
   formule d'une ligne ; pas de décomposition de Murphy.

## Décision
- `core/learning/forecasts.py` crée `var/learning/forecasts.db`, avec deux tables : `forecasts` et
  `resolutions`.
  - UPDATE et DELETE sont refusés par des déclencheurs.
  - L'échéance doit être postérieure au jour de création.
  - La résolution est unique et refusée avant l'échéance (R10).
  - L'énoncé passe le filtre `plain_text` (R5).
- Chaque ajout et chaque résolution écrit une entrée `FORECAST` (nouvel événement du journal),
  dans la même transaction. L'entrée donne l'identifiant, le domaine, le type et l'échéance, jamais
  l'énoncé ni les valeurs.
- `core/learning/calibration.py` calcule :
  - le score de Brier ;
  - la décomposition de Murphy ;
  - la table de fiabilité par classes ;
  - l'erreur absolue et relative des estimations ;
  - `calibration_drift`.
- La commande `cerveau forecast` a quatre sous-commandes : `add`, `resolve`, `list`, `calibration`.
- `config/evals.yaml › calibration` contient `min_resolved`, `window_days` et `brier_drift_max`, à
  `A_DEFINIR`.
  - La fonction `learning.calibration_drift` reste bloquée tant qu'ils ne sont pas fixés.
  - Les scores, eux, s'affichent toujours.
- Les deux modules entrent dans la porte de couverture à 100 %.

## Conséquences
- Une prévision se note sans modèle, et la base refuse de la réécrire après coup.
- Résolution :
  - par Lucas (`resolve`) en phase 7 ;
  - la résolution automatique en finance (point-in-time, depuis le store) et l'extraction
    automatique des prévisions des réponses restent à faire (backlog).
- Le déclencheur de rétrogradation (lot 7.4) lit `calibration_drift` ; il ne fait rien tant que
  les trois seuils sont à `A_DEFINIR`.
- Réversible : le registre est un fichier local sous `var/`, hors de git.
