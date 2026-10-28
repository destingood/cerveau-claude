# ADR-016 — Contrôles de qualité des séries de cours

- Statut : **proposé** (les deux seuils attendent la décision de Lucas)
- Date : 2026-10-18
- Phase : 2

## Contexte
D12 fixe deux paramètres : la fraîcheur, `max_staleness_sessions` = 1 séance de clôture, et le
score minimal `min_quality_score_above_N1` = 0,90. Une décision au-delà de N1 n'est pas permise
sans un score « suffisant ». D12 ne dit pas comment calculer ce score. Une série de cours peut
être fausse de quatre façons : une séance manque, un split ou un dividende est mal pris en compte,
un cours est aberrant, ou la dernière clôture est trop ancienne. Deux de ces contrôles ont besoin
d'un seuil que personne n'a encore fixé. La règle R7 interdit de deviner ces seuils.

## Options
1. **Un score pondéré** des quatre contrôles. Les poids seraient eux-mêmes des paramètres à
   régler, et une moyenne cacherait une anomalie grave derrière trois contrôles parfaits.
2. **Le minimum de quatre sous-scores**, chacun compris entre 0 et 1, ou « non évaluable ». Le
   score vaut « non évaluable » dès qu'un sous-score l'est.
3. **Des contrôles statistiques plus fins** (GARCH, détection de ruptures). Ils sont plus lourds,
   et leurs hypothèses sont discutables sur 500 séances.

## Décision
L'option 2 est retenue. Le calcul est déterministe et se trouve dans `core/finance/quality.py`.
Il porte sur la fenêtre de la VaR, soit les 500 dernières séances de la place closes à la date
d'évaluation (D7). Le calendrier de chaque place vient d'exchange-calendars.

| Sous-score | Calcul |
|---|---|
| `gaps` (séances manquantes) | 1 − (séances manquantes + cours datés d'un jour sans séance) / séances attendues. Les séances attendues vont du premier au dernier cours reçu dans la fenêtre : un historique court n'est pas un trou, et un retard relève de la fraîcheur. |
| `corporate_actions` (opérations sur titres) | 0 dès qu'un cours varie de `max_unexplained_move` ou plus une fois les splits et dividendes déclarés appliqués, ou dès qu'un dividende est supérieur ou égal à la clôture précédente ; 1 sinon. |
| `outliers` (cours aberrants) | Part des rendements logarithmiques dont le z modifié, 0,6745 (r − médiane) / MAD (Iglewicz et Hoaglin), reste inférieur ou égal à `outlier_robust_z`. Une MAD nulle rend le contrôle non évaluable. |
| `freshness` (fraîcheur) | 1 si la dernière clôture reçue a au plus `max_staleness_sessions` séances closes de retard, 0 sinon. |

Le sous-score « opérations sur titres » vaut 0 ou 1, et non une proportion. Un split non déclaré,
un split déclaré que les cours ne montrent pas, ou un cours erroné faussent en effet tous les
rendements calculés avant ce point. Les deux seuils restent `A_DEFINIR` dans
`config/data_sources.yaml`. Tant qu'ils ne sont pas fixés, les deux sous-scores qu'ils
gouvernent, le score et la fonction `data.quality_gate` restent « non évaluables », donc
bloquants au-delà de N1. Propositions soumises à Lucas :

- `outlier_robust_z` = **3,5** : c'est le seuil recommandé par Iglewicz et Hoaglin (1993) pour le
  z modifié ;
- `max_unexplained_move` = **0,30** : un cours multiplié ou divisé par 1,30 en une séance. Le
  chargeur impose une valeur inférieure à 0,5 pour qu'un split de 3 pour 2 oublié se voie
  toujours.

Seul un score calculé en mode strict (« connu à » : publié **et** ingéré avant la date) est
enregistré dans `quality_scores`. Il ne peut donc plus changer : un second score différent pour la
même série et la même date est refusé.

## Conséquences
- Les décisions N0 et N1 ne sont pas touchées. Au-delà, rien ne passe tant que Lucas n'a pas fixé
  les deux seuils.
- Un grand mouvement réel (faillite, offre publique) laisse « opérations sur titres » à 0 sur
  toute la fenêtre, faute d'un moyen de le reconnaître comme vérifié (backlog B86).
- Les séries de change et de taux n'ont pas encore de contrôle de qualité (backlog B85).
- Si une place n'a pas de calendrier connu, les contrôles « séances manquantes » et « fraîcheur »
  sont non évaluables, donc le score aussi.
